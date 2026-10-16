"""Rarete des cartes : cache local alimente depuis TCGdex par l'APPLICATION (jamais par Claude).

Pourquoi : le catalogue local (cards_cache.json) ne connait la rarete que de quelques cartes, et le champ
« rarity » des cartes du stock est vide. Les mots-cles d'annonce « AR », « Gold », « Alt » (et « Shiny » hors plage) en ont
besoin (voir services/listing_keyword_rules.py).

Regles de securite :
  * la rarete est ecrite dans un fichier de cache DEDIE (`.cache/cards_rarity_cache.json`, dossier ignore par
    Git et non synchronise par le Cloud) : jamais dans data.json, vinted_drops.json ni cards_cache.json
    (que l'appli reecrit en entier depuis sa memoire) ;
  * sauvegarde du cache dans backups/ avant chaque ecriture, ecriture atomique, JAMAIS de remplacement d'une
    rarete deja presente ;
  * recuperation par petits lots, avec reprise (les cartes deja traitees ne sont pas redemandees), limitation
    de debit, arret apres plusieurs erreurs reseau de suite, annulation possible, journal ligne par ligne.

Ce module n'utilise pas Streamlit. Le reseau passe par une fonction `http_get` injectable (les tests utilisent
des reponses TCGdex simulees).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(APP_DIR, ".cache")
RARITY_CACHE_FILE = os.path.join(CACHE_DIR, "cards_rarity_cache.json")
BACKUP_DIR = os.path.join(APP_DIR, "backups")
LOG_DIR = os.path.join(APP_DIR, "logs")
JOURNAL_FILE = os.path.join(LOG_DIR, "rarity_fetch_journal.jsonl")

CACHE_VERSION = 1
TCGDEX_CARD_URL = "https://api.tcgdex.net/v2/fr/cards/{card_id}"
USER_AGENT = "Pokestock/1.0 (recuperation de la rarete des cartes)"
REQUEST_TIMEOUT_SECONDS = 10
MIN_INTERVAL_SECONDS = 0.25          # ~4 requetes par seconde au maximum
MAX_RETRIES = 2                      # tentatives supplementaires sur 429 / 5xx / reseau
RETRY_BACKOFF_SECONDS = 2.0
MAX_CONSECUTIVE_ERRORS = 5           # arret du lot apres autant d'echecs de suite
BATCH_SECONDS = 6.0                  # duree maximale d'un lot (la page se rafraichit entre deux lots)

STATUS_OK = "ok"
STATUS_NOT_FOUND = "not_found"
STATUS_ERROR = "error"

NO_RARITY_VALUES = {"", "sans rarete", "sans rareté", "none", "null", "n/a", "na", "-", "?", "inconnue", "inconnu"}


# --------------------------------------------------------------------------- normalisation / classement

def _fold(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower().strip()


def is_meaningful_rarity(value) -> bool:
    """Vrai si `value` est une vraie rarete (ni vide ni « Sans Rareté »)."""
    return _fold(value) not in {_fold(v) for v in NO_RARITY_VALUES}


# Libelles TCGdex (francais et anglais, apres _fold) d'une « Illustration spéciale rare » : mot « Alt » dans l'annonce.
SPECIAL_ILLUSTRATION_LABELS = frozenset({
    "illustration speciale rare", "rare illustration speciale", "special illustration rare",
})


# Sous-types de cartes « Ultra Rare » : FA automatique pour ex / EX / V / GX et les Dresseurs / Supporters ;
# VMAX, VSTAR et tout le reste (V-UNION, Energie, sous-type inconnu...) sont listes pour accord, sans mot ajoute.
FA_AUTO_SUFFIXES = frozenset({"ex", "gx", "v"})
FA_REVIEW_SUFFIXES = frozenset({"vmax", "vstar"})
TRAINER_CATEGORIES = frozenset({"dresseur", "trainer", "supporter"})


def ultra_rare_subtype(category="", suffix="", name="") -> str:
    """Sous-type d'une carte Ultra Rare : « ex », « gx », « v », « trainer » (FA automatique), « vmax », « vstar »
    ou « unknown » (a valider). Lit d'abord le suffixe TCGdex, puis la fin du nom (« Chef-de-Fer-ex », « Pikachu V »)."""
    suffix_fold, name_fold, category_fold = _fold(suffix), _fold(name), _fold(category)
    for token in FA_REVIEW_SUFFIXES:  # VMAX / VSTAR d'abord : « Dracaufeu VMAX » ne doit jamais passer pour un V
        if suffix_fold == token or re.search(rf"(^|[\s-]){token}$", name_fold):
            return token
    if category_fold in TRAINER_CATEGORIES:
        return "trainer"
    if suffix_fold in FA_AUTO_SUFFIXES:
        return suffix_fold
    match = re.search(r"(^|[\s-])(ex|gx|v)$", name_fold)
    if match:
        return match.group(2)
    return "unknown"


def classify_rarity(rarity, category="", suffix="", name="") -> str:
    """Classe de rarete, ou « unknown » quand on ne sait pas.

    Classes : shiny, ar, gold, sir (Illustration speciale rare -> « Alt »), fa (Ultra Rare ex / EX / V / GX / Dresseur -> « FA »),
    fa_review (Ultra Rare VMAX, VSTAR ou sous-type inconnu : listee pour accord, rien d'ajoute), secret, alternate,
    ambiguous (VMAX, VSTAR, regional, promo...), other, unknown.
    Les comparaisons sont insensibles aux accents et a la casse, et acceptent les libelles TCGdex francais
    et anglais.
    """
    if not is_meaningful_rarity(rarity):
        return "unknown"
    r = _fold(rarity)
    if "shiny" in r or "chromatique" in r:
        return "shiny"
    if r in SPECIAL_ILLUSTRATION_LABELS:  # seulement les libelles certains, jamais par numero ni par nom
        return "sir"
    if "alternat" in r or "alt art" in r:
        return "alternate"
    if "secret" in r:
        return "secret"
    if r in {"illustration rare", "rare illustration"}:
        return "ar"
    if r in {"hyper rare", "rare hyper", "hyper-rare"}:
        return "gold"
    if any(token in r for token in ("vmax", "vstar", "v-union", "regional", "promo", "radiant", "amazing", "rainbow")):
        return "ambiguous"
    if r in {"ultra rare", "rare ultra"}:
        # « fa » : mot FA automatique (ex / EX / V / GX / Dresseur) ; « fa_review » : a valider (VMAX, VSTAR, autres)
        return "fa" if ultra_rare_subtype(category, suffix, name) in {"ex", "gx", "v", "trainer"} else "fa_review"
    if "full art" in r:
        return "fa_review"
    return "other"


def rarity_class_for_entry(entry) -> str:
    if not isinstance(entry, dict):
        return "unknown"
    return classify_rarity(entry.get("rarity", ""), entry.get("category", ""), entry.get("suffix", ""), entry.get("name", ""))


# --------------------------------------------------------------------------- cache disque

_CACHE_MEMO = {"path": None, "stamp": None, "entries": {}}


def _empty_cache():
    return {"version": CACHE_VERSION, "updated_at": "", "cards": {}}


def read_cache_file(path=None):
    """Contenu complet du cache (structure vide si absent ou illisible)."""
    path = path or RARITY_CACHE_FILE
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _empty_cache()
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
        return _empty_cache()
    return data


def load_rarity_entries(path=None):
    """{id TCGdex: entree}, relu seulement quand le fichier change (date + taille)."""
    path = path or RARITY_CACHE_FILE
    try:
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {}
    if _CACHE_MEMO["path"] == path and _CACHE_MEMO["stamp"] == stamp:
        return _CACHE_MEMO["entries"]
    entries = read_cache_file(path).get("cards", {})
    _CACHE_MEMO.update(path=path, stamp=stamp, entries=entries)
    return entries


def _backup_file(path, backup_dir, tag):
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = os.path.join(backup_dir, f"{os.path.basename(path)}.backup_{stamp}_{tag}")
    counter = 1
    while os.path.exists(target):
        counter += 1
        target = os.path.join(backup_dir, f"{os.path.basename(path)}.backup_{stamp}_{tag}{counter}")
    shutil.copy2(path, target)
    return target


def save_cache(cache, path=None, backup_dir=None, backup=True):
    """Ecrit `cache` de facon atomique ; sauvegarde d'abord l'ancien fichier s'il existe."""
    path = path or RARITY_CACHE_FILE
    folder = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(folder, exist_ok=True)
    backup_path = None
    if backup and os.path.exists(path):
        backup_path = _backup_file(path, backup_dir or BACKUP_DIR, "avant_rarete")
    cache = dict(cache)
    cache["version"] = CACHE_VERSION
    cache["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder, delete=False, suffix=".tmp") as tmp:
            tmp_path = tmp.name
            json.dump(cache, tmp, ensure_ascii=False)
            tmp.flush()
            os.fsync(tmp.fileno())
        with open(tmp_path, "r", encoding="utf-8") as check:
            json.load(check)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return backup_path


def merge_entry(cards, card_id, entry):
    """Ajoute `entry` a `cards` SANS jamais remplacer une rarete deja presente. Retourne True si ecrit."""
    existing = cards.get(card_id)
    if isinstance(existing, dict) and is_meaningful_rarity(existing.get("rarity")):
        return False
    if isinstance(existing, dict) and existing.get("status") == STATUS_OK and not is_meaningful_rarity(entry.get("rarity")):
        return False
    cards[card_id] = entry
    return True


def append_journal(entries, journal_path=None):
    path = journal_path or JOURNAL_FILE
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- lecture de la rarete d'une carte

def card_id_of(card) -> str:
    return str((card or {}).get("id") or "").strip()


def cached_entry_for_card(card, entries=None):
    entries = load_rarity_entries() if entries is None else entries
    entry = entries.get(card_id_of(card))
    return entry if isinstance(entry, dict) else None


def rarity_for_card(card, entries=None) -> str:
    """Rarete propre de la carte si elle est renseignee, sinon celle du cache TCGdex, sinon chaine vide."""
    own = (card or {}).get("rarity", "")
    if is_meaningful_rarity(own):
        return str(own)
    entry = cached_entry_for_card(card, entries)
    if entry and is_meaningful_rarity(entry.get("rarity")):
        return str(entry["rarity"])
    return ""


def rarity_class_for_card(card, entries=None) -> str:
    entry = cached_entry_for_card(card, entries) or {}
    return classify_rarity(
        rarity_for_card(card, entries), entry.get("category", ""), entry.get("suffix", ""),
        (card or {}).get("name") or entry.get("name", ""),
    )


# --------------------------------------------------------------------------- reseau (TCGdex)

def default_http_get(url, timeout=REQUEST_TIMEOUT_SECONDS):
    """(code HTTP, JSON decode ou None). Code 0 = erreur reseau."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, None


def entry_from_tcgdex(payload, now=None):
    """Entree de cache tiree d'une reponse TCGdex (champs utiles seulement)."""
    payload = payload if isinstance(payload, dict) else {}
    rarity = str(payload.get("rarity") or "").strip()
    return {
        "status": STATUS_OK,
        "rarity": rarity if is_meaningful_rarity(rarity) else "",
        "category": str(payload.get("category") or ""),
        "suffix": str(payload.get("suffix") or ""),
        "stage": str(payload.get("stage") or ""),
        "name": str(payload.get("name") or ""),
        "source": "tcgdex-fr",
        "fetched_at": (now or datetime.now()).isoformat(timespec="seconds"),
    }


def fetch_card(card_id, http_get=None, sleep=time.sleep, retries=MAX_RETRIES):
    """(statut, entree ou None). 404 -> not_found ; reseau/429/5xx -> nouvelles tentatives puis error."""
    http_get = http_get or default_http_get
    url = TCGDEX_CARD_URL.format(card_id=urllib.parse.quote(str(card_id), safe=".-_"))
    code = 0
    for attempt in range(retries + 1):
        code, payload = http_get(url)
        if code == 200 and isinstance(payload, dict):
            return STATUS_OK, entry_from_tcgdex(payload)
        if code == 404:
            return STATUS_NOT_FOUND, {
                "status": STATUS_NOT_FOUND, "rarity": "", "category": "", "suffix": "", "stage": "", "name": "",
                "source": "tcgdex-fr", "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
        if attempt < retries:
            sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    return STATUS_ERROR, {"code": code}


# --------------------------------------------------------------------------- file d'attente

def _stock_index_by_uid(data):
    index = {}
    for lot in (data or {}).get("lots", []) or []:
        for card in lot.get("cards", []) or []:
            uid = str(card.get("card_uid") or "").strip()
            if uid:
                index[uid] = card
    return index


def drop_cards(drops, data):
    """Cartes du stock (dict) correspondant aux cartes de tous les Drops ; l'id TCGdex vient du stock.

    Une ligne de Drop ne porte pas toujours l'id : on la relie a la carte du stock par `card_uid`.
    """
    index = _stock_index_by_uid(data)
    output = []
    for drop in (drops or {}).get("drops", []) or []:
        for ref in drop.get("cards", []) or []:
            card = index.get(str(ref.get("card_uid") or "").strip())
            if card is not None:
                output.append(card)
            elif card_id_of(ref):
                output.append(ref)
    return output


def drop_card_ids(drops, data=None):
    """Identifiants (ordre stable, sans doublon) des cartes de tous les Drops."""
    seen, output = set(), []
    for card in drop_cards(drops, data):
        card_id = card_id_of(card)
        if card_id and card_id not in seen:
            seen.add(card_id)
            output.append(card_id)
    return output


def _stock_cards(data):
    for lot in (data or {}).get("lots", []) or []:
        for card in lot.get("cards", []) or []:
            yield card


def stock_card_ids(data):
    seen, output = set(), []
    for card in _stock_cards(data):
        card_id = card_id_of(card)
        if card_id and card_id not in seen:
            seen.add(card_id)
            output.append(card_id)
    return output


def _ids_with_own_rarity(data, drops):
    own = set()
    for card in list(_stock_cards(data)):
        if is_meaningful_rarity(card.get("rarity")) and card_id_of(card):
            own.add(card_id_of(card))
    for card in drop_cards(drops, data):
        if is_meaningful_rarity(card.get("rarity")) and card_id_of(card):
            own.add(card_id_of(card))
    return own


def build_queue(data, drops, entries, include_stock=False):
    """Identifiants a demander, Drop d'abord. Exclut : deja traites (ok / introuvable) et deja avec rarete propre.

    Retourne {"drop": [...], "stock": [...], "already_done": n, "own_rarity": n, "without_id": n}.
    Les cartes sans identifiant TCGdex ne peuvent pas etre demandees (comptees dans `without_id`).
    """
    entries = entries or {}
    own = _ids_with_own_rarity(data, drops)

    def pending(ids):
        return [i for i in ids if i not in own and (entries.get(i) or {}).get("status") not in (STATUS_OK, STATUS_NOT_FOUND)]

    drop_ids = drop_card_ids(drops, data)
    stock_ids = [i for i in stock_card_ids(data) if i not in set(drop_ids)]
    all_ids = drop_ids + stock_ids
    done = sum(1 for i in all_ids if (entries.get(i) or {}).get("status") in (STATUS_OK, STATUS_NOT_FOUND))
    without_id = sum(1 for card in _stock_cards(data) if not card_id_of(card))
    return {
        "drop": pending(drop_ids),
        "stock": pending(stock_ids) if include_stock else [],
        "stock_all": pending(stock_ids),
        "already_done": done,
        "own_rarity": len([i for i in all_ids if i in own]),
        "without_id": without_id,
    }


def run_batch(queue, *, path=None, backup_dir=None, journal_path=None, http_get=None, sleep=time.sleep,
              clock=time.monotonic, max_seconds=BATCH_SECONDS, interval=MIN_INTERVAL_SECONDS,
              should_cancel=None, consecutive_errors=0, batch_label=""):
    """Traite le debut de `queue` pendant `max_seconds` au plus, puis sauvegarde le cache (une seule ecriture).

    Retourne un dict : processed (liste d'ids traites), ok, not_found, errors, written (entrees ajoutees),
    consecutive_errors, stopped ("" | "annule" | "erreurs" | "termine"), backup.
    Les cartes en erreur restent hors du cache (elles seront redemandees a la prochaine reprise).
    """
    http_get = http_get or default_http_get
    cache = read_cache_file(path)
    cards = cache["cards"]
    started = clock()
    stats = {"processed": [], "ok": 0, "not_found": 0, "errors": 0, "written": 0, "stopped": "", "backup": None,
             "consecutive_errors": consecutive_errors, "rarities": {}}
    journal = []
    for card_id in list(queue):
        if should_cancel and should_cancel():
            stats["stopped"] = "annule"
            break
        if stats["processed"] and clock() - started >= max_seconds:
            break
        status, entry = fetch_card(card_id, http_get=http_get, sleep=sleep)
        stats["processed"].append(card_id)
        if status == STATUS_ERROR:
            stats["errors"] += 1
            stats["consecutive_errors"] += 1
            journal.append({"ts": datetime.now().isoformat(timespec="seconds"), "event": "erreur", "id": card_id,
                            "code": (entry or {}).get("code", 0), "batch": batch_label})
            if stats["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                stats["stopped"] = "erreurs"
                break
        else:
            stats["consecutive_errors"] = 0
            stats[status] += 1
            if merge_entry(cards, card_id, entry):
                stats["written"] += 1
            if status == STATUS_OK:
                label = entry.get("rarity") or "(vide)"
                stats["rarities"][label] = stats["rarities"].get(label, 0) + 1
            journal.append({"ts": datetime.now().isoformat(timespec="seconds"), "event": status, "id": card_id,
                            "rarity": entry.get("rarity", ""), "batch": batch_label})
        sleep(interval)
    if not stats["stopped"] and len(stats["processed"]) >= len(queue):
        stats["stopped"] = "termine"
    if stats["written"]:
        stats["backup"] = save_cache(cache, path=path, backup_dir=backup_dir)
    if journal:
        append_journal(journal, journal_path)
    return stats


# --------------------------------------------------------------------------- bilan (rapport)

SUBTYPE_LABELS = {"ex": "Pokémon ex / EX", "gx": "Pokémon GX", "v": "Pokémon V", "trainer": "Dresseur / Supporter",
                  "vmax": "VMAX", "vstar": "VSTAR", "unknown": "Sous-type inconnu"}


def rarity_report(cards, entries=None):
    """Compte les cartes par classe de rarete (pour le rapport et l'ecran). `cards` : liste de cartes.

    Retourne aussi : `fa_cases` (a valider avant d'ajouter « FA » : Ultra Rare VMAX / VSTAR / inconnu, cas ambigus),
    `listed_cases` (Secret / Alternate, listees sans rien ajouter) et `ultra_cases` (TOUTES les Ultra Rare avec la decision).
    """
    entries = load_rarity_entries() if entries is None else entries
    counts, labels, fa_cases, listed_cases, ultra_cases = {}, {}, [], [], []
    for card in cards:
        klass = rarity_class_for_card(card, entries)
        counts[klass] = counts.get(klass, 0) + 1
        label = rarity_for_card(card, entries)
        if label:
            labels[label] = labels.get(label, 0) + 1
        entry = cached_entry_for_card(card, entries) or {}
        if klass in {"fa_review", "ambiguous", "secret", "alternate"}:  # « fa » = deja applique, pas un cas a lister
            case = {"id": card_id_of(card), "name": card.get("name", ""), "number": card.get("number", ""),
                    "set": card.get("set", ""), "rarity": label, "category": entry.get("category", ""),
                    "suffix": entry.get("suffix", ""), "class": klass}
            (fa_cases if klass in {"fa_review", "ambiguous"} else listed_cases).append(case)
        if klass in {"fa", "fa_review"}:
            subtype = ultra_rare_subtype(entry.get("category", ""), entry.get("suffix", ""), card.get("name") or entry.get("name", ""))
            ultra_cases.append({"Carte": card.get("name", ""), "Numéro": card.get("number", ""), "Extension": card.get("set", ""),
                                "Type": SUBTYPE_LABELS.get(subtype, subtype),
                                "Décision": "FA appliqué" if klass == "fa" else "À valider (rien ajouté)",
                                "id": card_id_of(card)})
    return {"counts": counts, "labels": labels, "fa_cases": fa_cases, "listed_cases": listed_cases, "ultra_cases": ultra_cases}

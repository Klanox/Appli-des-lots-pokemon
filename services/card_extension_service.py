"""Extension (« set ») des cartes : detection, recuperation, correction et journal.

Contexte : une carte sans extension (champ `set` vide, « N/A », drapeau 🇯🇵 seul...) donne une annonce
Vinted sans nom d'extension. Cause identifiee : depuis le 09/06/2026 la recherche locale compare
`utils.normalize_name` (qui GARDE espaces et tirets) a des cles de `cards_cache.json` fabriquees SANS
espaces ni tirets ; un nom a plusieurs mots (« Sorcilence VMAX », « Roue-de-Fer-ex ») ne trouve donc plus
rien dans le cache et l'appli retombe sur l'API TCGdex, dont la liste par nom ne contient pas d'objet
`set` -> `set = ""`. `compact_name_key` retablit la normalisation d'avant le 09/06.

Ce module est PUR (aucun import Streamlit, aucun reseau). Les ecritures de donnees passent par les
fonctions de sauvegarde normales de l'appli, passees en parametres (`save_data`, `save_drops`).
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import unicodedata
import uuid
from datetime import datetime

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(APP_DIR, "backups")
LOG_DIR = os.path.join(APP_DIR, "logs")  # dossier ignore par Git
JOURNAL_FILE = os.path.join(LOG_DIR, "extension_corrections_journal.jsonl")  # journal hors JSON metier
TRACE_FLAG_FILE = os.path.join(LOG_DIR, "trace_extension.on")
TRACE_LOG_FILE = os.path.join(LOG_DIR, "extension_trace.log")
TRACE_ENV = "POKESTOCK_TRACE_EXTENSION"

# Noms d'extensions absents du catalogue local (cards_cache.json / sets_reference.json), donnes par
# l'utilisateur. Convention de l'appli : le nom TCGdex SANS le prefixe « Méga-Évolution »
# (« Flammes Fantasmagoriques », « Héros Transcendants », « Équilibre Parfait », « Chaos Ascendant »).
EXTRA_SET_NAMES = {
    "me05": "Nuit Noire",
}

MISSING_TOKENS = {
    "", "n/a", "na", "none", "null", "-", "?", "pokemon", "inconnu", "unknown", "autre", "divers", "nan",
}
_FLAG_CHARS = re.compile(r"[\U0001F1E6-\U0001F1FF\s]+")

CONF_CERTAIN = "certaine"
CONF_PROBABLE = "probable"
CONF_AMBIGUOUS = "ambiguë"
CONF_NONE = "aucune"
CONF_ORDER = (CONF_CERTAIN, CONF_PROBABLE, CONF_AMBIGUOUS, CONF_NONE)


# --------------------------------------------------------------------------- normalisation

def _fold(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def compact_name_key(value) -> str:
    """Normalisation des CLES de cards_cache.json (celle d'app.py avant le 09/06/2026).

    Minuscules, sans accents, sans espaces ni tirets/apostrophes/points : « Sorcilence VMAX » -> « sorcilencevmax ».
    """
    text = _fold(value).lower()
    for ch in ("-", "‐", "‑", "–", "—", "_", "'", "’", ".", ":", " "):
        text = text.replace(ch, "")
    return text


def _alnum(value) -> str:
    return re.sub(r"[^a-z0-9]", "", _fold(value).lower())


def _norm_number(value) -> str:
    text = str(value or "").split("/")[0].strip().lower()
    stripped = text.lstrip("0")
    return stripped or text


def _s(value) -> str:
    return str(value or "").strip()


# --------------------------------------------------------------------------- extension manquante ?

def is_missing_extension(value) -> bool:
    """Vrai si `value` ne nomme pas une vraie extension (vide, N/A, « Pokémon », drapeau 🇯🇵 seul...)."""
    text = _FLAG_CHARS.sub("", _s(value))
    if not text:
        return True
    return _fold(text).lower() in MISSING_TOKENS


def card_extension_name(card) -> str:
    """Nom d'extension exploitable de la carte (`set` puis `extension`), sinon chaine vide."""
    if not isinstance(card, dict):
        return ""
    for key in ("set", "extension"):
        value = _s(card.get(key))
        if value and not is_missing_extension(value):
            return value
    return ""


def card_is_missing_extension(card) -> bool:
    return not card_extension_name(card)


def card_set_id(card) -> str:
    """Identifiant d'extension TCGdex de la carte : set_id, sinon prefixe de l'id, sinon URL d'image."""
    if not isinstance(card, dict):
        return ""
    if _s(card.get("set_id")):
        return _s(card.get("set_id"))
    card_id = _s(card.get("id"))
    if "-" in card_id:
        return card_id.rsplit("-", 1)[0]
    match = re.search(r"tcgdex\.net/\w+/\w+/([^/]+)/", _s(card.get("image_url")))
    return match.group(1) if match else ""


# --------------------------------------------------------------------------- catalogue local

class Catalogue:
    """Index en lecture seule : id de carte -> extension, id d'extension -> nom, (nom, numero) -> extensions."""

    def __init__(self):
        self.by_card_id = {}      # card id -> {set_name}
        self.set_names = {}       # set id (casefold) -> {set_name}
        self.by_name_number = {}  # (alnum(name), norm number) -> {(set_name, set_id, card_id)}
        self.all_set_names = set()

    # -- construction
    def add_card(self, card, set_name, set_id):
        set_name = _s(set_name)
        if not set_name or not isinstance(card, dict):
            return
        card_id = _s(card.get("id"))
        if card_id:
            self.by_card_id.setdefault(card_id, set()).add(set_name)
        if _s(set_id):
            self.set_names.setdefault(_s(set_id).casefold(), set()).add(set_name)
        self.all_set_names.add(set_name)
        key = (_alnum(card.get("name")), _norm_number(card.get("localId") or card.get("number")))
        self.by_name_number.setdefault(key, set()).add((set_name, _s(set_id), card_id))

    def add_set(self, set_id, set_name):
        if _s(set_id) and _s(set_name):
            self.set_names.setdefault(_s(set_id).casefold(), set()).add(_s(set_name))
            self.all_set_names.add(_s(set_name))

    # -- requetes
    def names_for_card_id(self, card_id):
        return sorted(self.by_card_id.get(_s(card_id), ()))

    def names_for_set_id(self, set_id):
        return sorted(self.set_names.get(_s(set_id).casefold(), ()))

    def names_for_name_number(self, name, number):
        return sorted({entry[0] for entry in self.by_name_number.get((_alnum(name), _norm_number(number)), ())})

    def search_set_names(self, query, limit=25):
        """Extensions dont le nom contient `query` (sans accents ni casse), pour le selecteur."""
        q = _alnum(query)
        names = sorted(self.all_set_names, key=lambda n: _alnum(n))
        if not q:
            return names[:limit]
        return [n for n in names if q in _alnum(n)][:limit]


def build_catalogue(cards_index=None, sets_reference=None, extra_names=None) -> Catalogue:
    catalogue = Catalogue()
    for entries in (cards_index or {}).values():
        for entry in entries or ():
            try:
                card, set_name, set_id = entry[0], entry[1], entry[2]
            except (TypeError, IndexError):
                continue
            catalogue.add_card(card, set_name, set_id)
    blocks = ((sets_reference or {}).get("sets") or {}) if isinstance(sets_reference, dict) else {}
    for block in blocks.values():
        for info in (block or {}).get("sets", []) or []:
            catalogue.add_set(info.get("code"), info.get("name"))
    for set_id, set_name in (EXTRA_SET_NAMES if extra_names is None else extra_names).items():
        catalogue.add_set(set_id, set_name)
    return catalogue


_CATALOGUE_CACHE = {}


def load_catalogue(base_dir=None) -> Catalogue:
    """Catalogue construit depuis cards_cache.json + sets_reference.json (mis en cache selon les dates de fichier)."""
    base_dir = base_dir or APP_DIR
    cards_path = os.path.join(base_dir, "cards_cache.json")
    sets_path = os.path.join(base_dir, "sets_reference.json")

    def _stamp(path):
        try:
            stat = os.stat(path)
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None

    signature = (_stamp(cards_path), _stamp(sets_path))
    cached = _CATALOGUE_CACHE.get(base_dir)
    if cached and cached[0] == signature:
        return cached[1]
    cards_index, sets_reference = {}, {}
    try:
        with open(cards_path, "r", encoding="utf-8") as handle:
            cards_index = (json.load(handle) or {}).get("cards_index", {}) or {}
    except (OSError, ValueError):
        pass
    try:
        with open(sets_path, "r", encoding="utf-8") as handle:
            sets_reference = json.load(handle) or {}
    except (OSError, ValueError):
        pass
    catalogue = build_catalogue(cards_index, sets_reference)
    _CATALOGUE_CACHE[base_dir] = (signature, catalogue)
    return catalogue


# --------------------------------------------------------------------------- recuperation (propositions)

def resolve_by_id(card, catalogue):
    """Extension retrouvee A PARTIR DE L'IDENTIFIANT de la carte (pour le garde-fou, sans confrontation au stock).

    Retourne (nom, source) ou ("", ""). Un identifiant qui donnerait plusieurs extensions n'est pas resolu.
    """
    card_id = _s(card.get("id")) if isinstance(card, dict) else ""
    if not card_id or catalogue is None:
        return "", ""
    names = catalogue.names_for_card_id(card_id)
    if len(names) == 1:
        return names[0], "catalogue (id de la carte)"
    if names:
        return "", ""
    set_id = card_set_id(card)
    names = catalogue.names_for_set_id(set_id) if set_id else []
    if len(names) == 1:
        return names[0], f"catalogue (extension {set_id})"
    return "", ""


class ProposalContext:
    """Connaissances tirees du stock (cartes AVEC extension) + catalogue, pour proposer une extension."""

    def __init__(self, data, archives, catalogue):
        self.catalogue = catalogue
        self.by_id = {}
        self.by_name_number = {}
        self.by_set_id = {}
        for lots in ((data or {}).get("lots", []) or [], archives or []):
            for lot in lots:
                for card in lot.get("cards", []) or []:
                    name = card_extension_name(card)
                    if not name:
                        continue
                    if _s(card.get("id")):
                        self.by_id.setdefault(_s(card["id"]), set()).add(name)
                    self.by_name_number.setdefault((_alnum(card.get("name")), _norm_number(card.get("number"))), set()).add(name)
                    set_id = card_set_id(card)
                    if set_id:
                        self.by_set_id.setdefault(set_id.casefold(), set()).add(name)


def propose_extension(card, ctx: ProposalContext):
    """Propose une extension pour une carte sans extension.

    Retourne {"confidence", "value", "source", "candidates", "proposals"} :
      certaine : exemplaire identique du stock (meme id) ou catalogue par id, ou nom connu de l'utilisateur ;
      probable : une seule extension, deduite de l'extension de l'image/id ou du couple nom + numero ;
      ambiguë  : plusieurs extensions possibles (`candidates` les liste) ;
      aucune   : rien trouve (selecteur / saisie libre).
    Ne modifie rien.
    """
    proposals = []  # (source, [noms], niveau)
    card_id = _s(card.get("id"))
    cat = ctx.catalogue
    if card_id and ctx.by_id.get(card_id):
        names = sorted(ctx.by_id[card_id])
        proposals.append(("exemplaire identique dans le stock", names, CONF_CERTAIN if len(names) == 1 else CONF_AMBIGUOUS))
    if card_id and cat is not None and cat.names_for_card_id(card_id):
        names = cat.names_for_card_id(card_id)
        proposals.append(("catalogue local (id de la carte)", names, CONF_CERTAIN if len(names) == 1 else CONF_AMBIGUOUS))
    sid = card_set_id(card)
    if sid and EXTRA_SET_NAMES.get(sid.casefold()):
        proposals.append(("nom fourni par l'utilisateur (Pokepedia)", [EXTRA_SET_NAMES[sid.casefold()]], CONF_CERTAIN))
    elif sid and (not card_id or cat is None or not cat.names_for_card_id(card_id)):
        names = set(ctx.by_set_id.get(sid.casefold(), set()))
        if cat is not None:
            names |= set(cat.names_for_set_id(sid))
        if names:
            names = sorted(names)
            proposals.append((f"extension {sid} (id / image)", names, CONF_PROBABLE if len(names) == 1 else CONF_AMBIGUOUS))
    key = (_alnum(card.get("name")), _norm_number(card.get("number")))
    names = set(ctx.by_name_number.get(key, set()))
    if cat is not None:
        names |= set(cat.names_for_name_number(card.get("name"), card.get("number")))
    if names and key[0]:
        names = sorted(names)
        proposals.append(("même nom + numéro (stock / catalogue)", names, CONF_PROBABLE if len(names) == 1 else CONF_AMBIGUOUS))

    certain = [p for p in proposals if p[2] == CONF_CERTAIN]
    probable = [p for p in proposals if p[2] == CONF_PROBABLE]
    if certain and len({tuple(p[1]) for p in certain}) == 1:
        level, value, source = CONF_CERTAIN, certain[0][1][0], " + ".join(p[0] for p in certain)
    elif not certain and probable and len({tuple(p[1]) for p in probable}) == 1:
        level, value, source = CONF_PROBABLE, probable[0][1][0], " + ".join(p[0] for p in probable)
    elif proposals:
        level, value, source = CONF_AMBIGUOUS, "", "plusieurs extensions possibles"
    else:
        level, value, source = CONF_NONE, "", "rien trouvé"
    candidates = sorted({n for p in proposals for n in p[1]})
    return {"confidence": level, "value": value, "source": source, "candidates": candidates,
            "proposals": [{"source": p[0], "names": p[1], "confidence": p[2]} for p in proposals]}


# --------------------------------------------------------------------------- parcours des cartes

def iter_missing_stock_cards(data, archives=None):
    """Genere (origine, indice_lot, lot, carte) pour chaque carte du stock/archives sans extension."""
    for origin, lots in (("stock", (data or {}).get("lots", []) or []), ("archive", archives or [])):
        for lot_index, lot in enumerate(lots):
            for card in lot.get("cards", []) or []:
                if card_is_missing_extension(card):
                    yield origin, lot_index, lot, card


def iter_drop_refs(drops):
    for drop in (drops or {}).get("drops", []) or []:
        for ref in drop.get("cards", []) or []:
            yield drop, ref


def count_missing_extensions(data, drops=None, archives=None):
    """Compteur permanent : cartes sans extension dans le stock et dans le Drop."""
    stock = sum(1 for _ in iter_missing_stock_cards(data, archives))
    stock_with_quantity = 0
    for _origin, _i, _lot, card in iter_missing_stock_cards(data, archives):
        try:
            remaining = int(card.get("quantity", 0) or 0) - int(card.get("sold_quantity", 0) or 0)
        except (TypeError, ValueError):
            remaining = 0
        if remaining > 0:
            stock_with_quantity += 1
    drop_total = 0
    by_status = {}
    for _drop, ref in iter_drop_refs(drops):
        if is_missing_extension(ref.get("set")) and not _s(ref.get("extension")):
            drop_total += 1
            status = _s(ref.get("status")) or "inconnu"
            by_status[status] = by_status.get(status, 0) + 1
    return {"stock": stock, "stock_en_quantite": stock_with_quantity, "drop": drop_total, "drop_par_statut": by_status}


# --------------------------------------------------------------------------- file de correction

DROP_STATUS_LABELS = {
    "to_photograph": "À photographier",
    "sorted": "Triée",
    "draft": "Brouillon",
    "online": "En ligne",
    "sold": "Vendue",
}


def build_queue(data, drops=None, archives=None, catalogue=None):
    """Liste de TOUTES les cartes sans extension avec leur proposition de recuperation.

    Chaque element : origin, lot_uid, lot_name, card_uid, name, number, id, set_raw, image_url, quantity,
    drop (None ou {status, status_label, restock, drop_name, drop_item_id}), flag_only, confidence, value,
    source, candidates. Ne modifie rien.
    """
    ctx = ProposalContext(data, archives, catalogue)
    refs_by_uid = {}
    for drop, ref in iter_drop_refs(drops):
        refs_by_uid.setdefault(_s(ref.get("card_uid")), []).append((drop, ref))
    items = []
    for origin, _lot_index, lot, card in iter_missing_stock_cards(data, archives):
        uid = _s(card.get("card_uid"))
        proposal = propose_extension(card, ctx)
        drop_info = None
        for drop, ref in refs_by_uid.get(uid, []):
            status = _s(ref.get("status")) or "sorted"
            restock = bool(_s(drop.get("drop_launched_at")) and _s(ref.get("added_at")) > _s(drop.get("drop_launched_at")))
            drop_info = {"status": status, "status_label": DROP_STATUS_LABELS.get(status, status), "restock": restock,
                         "drop_name": _s(drop.get("name")), "drop_item_id": _s(ref.get("drop_item_id"))}
            if status == "online":
                break
        try:
            quantity = int(card.get("quantity", 0) or 0) - int(card.get("sold_quantity", 0) or 0)
        except (TypeError, ValueError):
            quantity = 0
        items.append({
            "origin": origin, "lot_uid": _s(lot.get("lot_uid")), "lot_name": _s(lot.get("nom")), "card_uid": uid,
            "name": _s(card.get("name")), "number": _s(card.get("number")), "id": _s(card.get("id")),
            "set_raw": _s(card.get("set")), "image_url": _s(card.get("image_url")), "manual_image_path": _s(card.get("manual_image_path")),
            "quantity": quantity, "drop": drop_info, "flag_only": bool(re.search(r"[\U0001F1E6-\U0001F1FF]", _s(card.get("set")))),
            "confidence": proposal["confidence"], "value": proposal["value"], "source": proposal["source"],
            "candidates": proposal["candidates"],
        })
    return items


def queue_change(item, new_value=None, confidence=None, source=None):
    """Convertit un element de file en entree pour `apply_corrections`."""
    return {"card_uid": item["card_uid"], "lot_uid": item["lot_uid"], "new": new_value if new_value is not None else item["value"],
            "source": source or item["source"], "confidence": confidence or item["confidence"],
            "label": f"{item['name']} {item['number']}".strip()}


# --------------------------------------------------------------------------- trace de diagnostic (desactivee par defaut)

def trace_enabled() -> bool:
    if str(os.environ.get(TRACE_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}:
        return True
    try:
        return os.path.exists(TRACE_FLAG_FILE)
    except OSError:
        return False


def trace(event, **fields):
    """Ecrit une ligne dans logs/extension_trace.log SI (et seulement si) le fichier-marqueur existe.

    N'ecrit jamais de JSON metier ; ne leve jamais d'exception.
    """
    if not trace_enabled():
        return
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        line = json.dumps({"at": datetime.now().isoformat(timespec="milliseconds"), "event": event, **fields},
                          ensure_ascii=False, default=str)
        with open(TRACE_LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- garde-fou central a l'ecriture

def _disk_card_uids(data_path):
    uids = set()
    try:
        with open(data_path, "r", encoding="utf-8") as handle:
            on_disk = json.load(handle)
    except (OSError, ValueError):
        return None
    for lot in (on_disk or {}).get("lots", []) or []:
        for card in lot.get("cards", []) or []:
            if _s(card.get("card_uid")):
                uids.add(_s(card["card_uid"]))
    return uids


def complete_new_cards_extension(data, data_path, catalogue=None):
    """GARDE-FOU central (appele par `sd()`) : complete l'extension VIDE des cartes NOUVELLES.

    - « nouvelle » = card_uid absent du data.json actuellement sur disque ; une carte deja enregistree
      n'est jamais modifiee ici (les cartes existantes passent par la file « Extensions manquantes ») ;
    - ne remplace jamais une extension deja renseignee ;
    - n'utilise que le catalogue local (aucun reseau) a partir de l'identifiant de la carte.
    Retourne la liste des cartes completees (vide si rien).
    """
    if not isinstance(data, dict) or not isinstance(data.get("lots"), list):
        return []
    candidates = [
        (lot, card) for lot in data["lots"] for card in lot.get("cards", []) or []
        if card_is_missing_extension(card) and _s(card.get("id")) and _s(card.get("card_uid"))
    ]
    if not candidates:
        return []
    known = _disk_card_uids(data_path)
    if known is None:
        return []
    catalogue = catalogue or load_catalogue(os.path.dirname(os.path.abspath(data_path)))
    changes = []
    for lot, card in candidates:
        if _s(card["card_uid"]) in known:
            continue
        name, source = resolve_by_id(card, catalogue)
        trace("garde-fou", card=card.get("name"), card_id=card.get("id"), resolu=name, source=source)
        if not name:
            continue
        card["set"] = name
        changes.append({"card_uid": card["card_uid"], "name": card.get("name"), "id": card.get("id"),
                        "lot": lot.get("nom"), "new": name, "source": source})
    return changes


# --------------------------------------------------------------------------- journal (hors JSON metier) + annulation

def read_journal(journal_path=None):
    path = journal_path or JOURNAL_FILE
    entries = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return entries


def append_journal(entries, journal_path=None):
    path = journal_path or JOURNAL_FILE
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _backup(path, backup_dir, tag):
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = os.path.join(backup_dir, f"{os.path.basename(path)}.backup_{stamp}_{tag}")
    counter = 1
    while os.path.exists(target):
        counter += 1
        target = os.path.join(backup_dir, f"{os.path.basename(path)}.backup_{stamp}_{tag}{counter}")
    shutil.copy2(path, target)
    return target


def _find_stock_card(data, lot_uid, card_uid):
    for lot in (data or {}).get("lots", []) or []:
        if lot_uid and _s(lot.get("lot_uid")) != lot_uid:
            continue
        for card in lot.get("cards", []) or []:
            if _s(card.get("card_uid")) == card_uid:
                return lot, card
    return None, None


def _matching_drop_refs(drops, lot_uid, card_uid):
    for _drop, ref in iter_drop_refs(drops):
        if _s(ref.get("card_uid")) == card_uid and (not lot_uid or not _s(ref.get("lot_uid")) or _s(ref.get("lot_uid")) == lot_uid):
            yield ref


def apply_corrections(changes, *, load_data, save_data, load_drops, save_drops, data_path, drops_path,
                      backup_dir=None, journal_path=None, allow_replace=False, batch_label=""):
    """Applique des corrections d'extension. `changes` : liste de dicts
    {card_uid, lot_uid, new, source, confidence}.

    - ne remplit que des extensions VIDES (un `set` deja renseigne n'est remplace que si `allow_replace`
      est vrai, c'est-a-dire apres confirmation explicite de l'utilisateur) ;
    - met la meme valeur dans la copie de la carte dans vinted_drops.json, sans toucher a aucun autre champ ;
    - sauvegarde data.json (et vinted_drops.json si necessaire) dans backups/ AVANT d'ecrire ;
    - ecrit via `save_data` / `save_drops` (fonctions normales de l'appli, synchro Cloud comprise) ;
    - ajoute une ligne de journal par carte modifiee.
    Retourne {"ok", "applied", "skipped", "batch", "backups", "message"}.
    """
    backup_dir = backup_dir or BACKUP_DIR
    data = load_data()
    drops = load_drops() if load_drops else {"drops": []}
    plan, skipped = [], []
    seen = set()
    for change in changes or []:
        card_uid, lot_uid = _s(change.get("card_uid")), _s(change.get("lot_uid"))
        new_value = _s(change.get("new"))
        label = change.get("label") or card_uid
        if not new_value or is_missing_extension(new_value):
            skipped.append((label, "valeur d'extension vide ou invalide"))
            continue
        if (lot_uid, card_uid) in seen:
            continue
        seen.add((lot_uid, card_uid))
        lot, card = _find_stock_card(data, lot_uid, card_uid)
        if card is None:
            skipped.append((label, "carte introuvable (a changé depuis l'aperçu)"))
            continue
        old_value = _s(card.get("set"))
        if card_extension_name(card) and not allow_replace:
            skipped.append((label, f"extension déjà renseignée (« {card_extension_name(card)} ») : confirmation requise"))
            continue
        plan.append((lot, card, old_value, new_value, change))
    if not plan:
        return {"ok": False, "applied": 0, "skipped": skipped, "batch": "", "backups": [],
                "message": "Aucune carte à corriger."}

    backups = [_backup(data_path, backup_dir, "extensions")]
    touched_drop_refs = []
    for _lot, card, _old, new_value, change in plan:
        for ref in _matching_drop_refs(drops, _s(change.get("lot_uid")), _s(card.get("card_uid"))):
            if is_missing_extension(ref.get("set")) or allow_replace:
                touched_drop_refs.append((ref, _s(ref.get("set")), new_value))
    if touched_drop_refs:
        backups.append(_backup(drops_path, backup_dir, "extensions"))

    batch = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat(timespec="seconds")
    journal = []
    for lot, card, old_value, new_value, change in plan:
        card["set"] = new_value
        refs = [r for r, _o, _n in touched_drop_refs if _s(r.get("card_uid")) == _s(card.get("card_uid"))]
        for ref, _old, new_ref in touched_drop_refs:
            if _s(ref.get("card_uid")) == _s(card.get("card_uid")):
                ref["set"] = new_ref
        journal.append({
            "action": "set", "batch": batch, "at": now, "label": batch_label,
            "card_uid": _s(card.get("card_uid")), "lot_uid": _s(lot.get("lot_uid")), "lot": _s(lot.get("nom")),
            "card": _s(card.get("name")), "number": _s(card.get("number")), "id": _s(card.get("id")),
            "old": old_value, "new": new_value,
            "source": _s(change.get("source")), "confidence": _s(change.get("confidence")),
            "drop_item_ids": [_s(r.get("drop_item_id")) for r in refs],
        })
    save_data(data)
    if touched_drop_refs:
        save_drops(drops)
    append_journal(journal, journal_path)
    return {"ok": True, "applied": len(plan), "skipped": skipped, "batch": batch, "backups": backups,
            "message": f"{len(plan)} extension(s) renseignée(s)."}


def journal_batches(journal_path=None):
    """Lots de corrections encore annulables : [{batch, at, count, entries}] (du plus recent au plus ancien)."""
    entries = read_journal(journal_path)
    undone = {e.get("batch") for e in entries if e.get("action") == "undo"}
    batches = {}
    for entry in entries:
        if entry.get("action") == "set" and entry.get("batch") not in undone:
            batches.setdefault(entry["batch"], []).append(entry)
    out = [{"batch": b, "at": items[0].get("at", ""), "count": len(items), "entries": items, "label": items[0].get("label", "")}
           for b, items in batches.items()]
    out.sort(key=lambda b: b["at"], reverse=True)
    return out


def undo_batch(batch, *, load_data, save_data, load_drops, save_drops, data_path, drops_path,
               backup_dir=None, journal_path=None):
    """Annule un lot de corrections en relisant le journal : remet l'ancienne valeur, carte par carte, SEULEMENT
    si la valeur actuelle est encore celle ecrite par la correction (sinon la carte est laissee telle quelle)."""
    backup_dir = backup_dir or BACKUP_DIR
    entries = [e for e in read_journal(journal_path) if e.get("action") == "set" and e.get("batch") == batch]
    if not entries:
        return {"ok": False, "undone": 0, "skipped": [], "message": "Lot de corrections introuvable dans le journal."}
    if any(e.get("batch") == batch for e in read_journal(journal_path) if e.get("action") == "undo"):
        return {"ok": False, "undone": 0, "skipped": [], "message": "Ce lot a déjà été annulé."}
    data = load_data()
    drops = load_drops() if load_drops else {"drops": []}
    todo, skipped = [], []
    for entry in entries:
        lot, card = _find_stock_card(data, _s(entry.get("lot_uid")), _s(entry.get("card_uid")))
        if card is None:
            skipped.append((entry.get("card"), "carte introuvable"))
        elif _s(card.get("set")) != _s(entry.get("new")):
            skipped.append((entry.get("card"), "extension modifiée depuis : laissée telle quelle"))
        else:
            todo.append((card, entry))
    if not todo:
        return {"ok": False, "undone": 0, "skipped": skipped, "message": "Rien à annuler."}
    backups = [_backup(data_path, backup_dir, "annulation_extensions")]
    drop_touched = False
    for card, entry in todo:
        card["set"] = entry.get("old", "")
        for ref in _matching_drop_refs(drops, _s(entry.get("lot_uid")), _s(card.get("card_uid"))):
            if _s(ref.get("set")) == _s(entry.get("new")):
                if not drop_touched:
                    backups.append(_backup(drops_path, backup_dir, "annulation_extensions"))
                    drop_touched = True
                ref["set"] = entry.get("old", "")
    save_data(data)
    if drop_touched:
        save_drops(drops)
    append_journal([{"action": "undo", "batch": batch, "at": datetime.now().isoformat(timespec="seconds"),
                     "undone": len(todo)}], journal_path)
    return {"ok": True, "undone": len(todo), "skipped": skipped, "backups": backups,
            "message": f"{len(todo)} extension(s) remise(s) à leur valeur d'origine."}


# --------------------------------------------------------------------------- annonces en ligne a mettre a jour

def mark_listing_updated(drop_item_id, journal_path=None):
    append_journal([{"action": "listing_updated", "drop_item_id": _s(drop_item_id),
                     "at": datetime.now().isoformat(timespec="seconds")}], journal_path)


def listings_marked_updated(journal_path=None):
    return {_s(e.get("drop_item_id")) for e in read_journal(journal_path) if e.get("action") == "listing_updated"}


def online_listings_to_update(data, drops, journal_path=None):
    """Annonces EN LIGNE dont le titre a ete genere sans extension.

    - cartes corrigees (journal) dont la copie Drop est « en ligne » : l'annonce Vinted porte l'ancien titre ;
    - cartes « en ligne » qui n'ont toujours pas d'extension (a corriger d'abord).
    Retourne [{ref, card, was_missing, still_missing, correction}] ; ne modifie rien.
    """
    entries = [e for e in read_journal(journal_path) if e.get("action") == "set"]
    undone = {e.get("batch") for e in read_journal(journal_path) if e.get("action") == "undo"}
    corrected = {}
    for entry in entries:
        if entry.get("batch") in undone:
            continue
        if is_missing_extension(entry.get("old")):
            corrected[_s(entry.get("card_uid"))] = entry
    out = []
    for _drop, ref in iter_drop_refs(drops):
        if _s(ref.get("status")) != "online":
            continue
        uid = _s(ref.get("card_uid"))
        lot, card = _find_stock_card(data, _s(ref.get("lot_uid")), uid)
        stock_card = card if card is not None else ref
        still_missing = card_is_missing_extension(stock_card)
        if uid in corrected or still_missing:
            out.append({"ref": ref, "card": stock_card, "still_missing": still_missing, "correction": corrected.get(uid)})
    return out

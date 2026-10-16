"""Brouillons d'un Drop lance : liste complete, mise en ligne groupee avec horodatage, journal et annulation.

Diagnostic du 16/10/2026
------------------------
* Avant : l'encadre « Brouillons a publier » partait du RESULTAT DE L'ANALYSE PHOTO en cours
  (``recognition_payload``) : seules les annonces de la serie de photos analysee apparaissaient. Les brouillons
  d'une analyse precedente disparaissaient de la liste tant qu'on n'avait pas rejoue cette analyse.
* Maintenant : la liste vient UNIQUEMENT de vinted_drops.json (references au statut « brouillon prete » qui ne sont
  ni en ligne, ni vendues, ni deja marquees comme publiees). Elle ne depend plus d'aucune analyse photo.
* Le champ d'horodatage est ``online_at`` (deja ecrit par « Marquer en ligne » et par le lancement du Drop). Il est
  maintenant pose a la date et a l'heure choisies par l'utilisateur ; ``listing_posted_at`` recoit la meme valeur.
  ``online_at`` / ``listing_posted_at`` des references deja en ligne ne sont jamais modifies, ni aucun statut « vendue ».

Ce module ne depend pas de Streamlit. Les ecritures passent par ``save_drops`` (fonction normale de l'appli, synchro
Cloud comprise), apres sauvegarde dans backups/, avec un journal dans logs/ qui permet d'annuler le dernier lot.
"""

from __future__ import annotations

import copy
import os
import uuid
from datetime import datetime, timedelta

from services import card_extension_service as ext
from services.vinted_drops_service import (
    drop_is_launched,
    drop_item_status,
    drop_ref_is_restock_draft,
    find_drop,
)

JOURNAL_FILE = os.path.join(ext.LOG_DIR, "drop_online_marking_journal.jsonl")
SERIES_GAP_HOURS = 3.0
ONLINE_FIELDS = ("status", "draft_ready_at", "online_at", "listing_posted", "listing_posted_at")
ACTION_MARK = "mark_online"
ACTION_UNDO = "undo"


def _s(value):
    return str(value or "").strip()


def parse_iso(value):
    try:
        return datetime.fromisoformat(_s(value))
    except (TypeError, ValueError):
        return None


def _qty(ref):
    try:
        return max(1, int(ref.get("quantity", 1) or 1))
    except (TypeError, ValueError):
        return 1


def _price(ref):
    try:
        return float(ref.get("price_at_add") or 0)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- date de premiere mise en ligne

def drop_first_online_at(drop):
    """Date ISO de la PREMIERE mise en ligne du Drop (origine des statistiques).

    = la plus ancienne ``online_at`` d'une reference en ligne ou vendue ; a defaut (aucune date connue),
    ``drop_launched_at``. Aucune date n'est inventee : "" si ni l'une ni l'autre n'existe.
    """
    dates = []
    for ref in (drop or {}).get("cards", []) or []:
        if drop_item_status(ref) not in {"online", "sold"}:
            continue
        stamp = parse_iso(ref.get("online_at"))
        if stamp:
            dates.append(stamp)
    if dates:
        return min(dates).isoformat(timespec="seconds")
    return _s((drop or {}).get("drop_launched_at"))


def drop_has_online_stamps(drop):
    """Vrai si au moins une reference en ligne / vendue porte un ``online_at`` exploitable."""
    return any(
        parse_iso(ref.get("online_at")) and drop_item_status(ref) in {"online", "sold"}
        for ref in (drop or {}).get("cards", []) or []
    )


def drop_cards_online_by(drop, cutoff):
    """Cartes (quantites) en ligne ou vendues a l'instant ``cutoff``, chaque carte comptee a SA date de mise en ligne.

    Une carte en ligne / vendue sans ``online_at`` est comptee depuis la premiere mise en ligne du Drop
    (jamais de date inventee). Brouillons et cartes a traiter ne comptent pas.
    """
    origin = parse_iso(drop_first_online_at(drop))
    total = 0
    for ref in (drop or {}).get("cards", []) or []:
        if drop_item_status(ref) not in {"online", "sold"}:
            continue
        stamp = parse_iso(ref.get("online_at")) or origin
        if stamp is None or cutoff is None:
            total += _qty(ref)
            continue
        try:
            if stamp <= cutoff:
                total += _qty(ref)
        except TypeError:  # dates naives / avec fuseau melangees : on compte plutot que de deviner
            total += _qty(ref)
    return total


# --------------------------------------------------------------------------- liste complete des brouillons

def _series_numbers(refs, gap_hours=SERIES_GAP_HOURS):
    """{drop_item_id: numero de serie} : un nouvel ecart de plus de ``gap_hours`` entre deux brouillons ouvre une serie."""
    dated = sorted(
        ((parse_iso(ref.get("draft_ready_at")), _s(ref.get("drop_item_id"))) for ref in refs),
        key=lambda pair: (pair[0] is None, pair[0] or datetime.min),
    )
    numbers, current, previous = {}, 0, None
    for stamp, item_id in dated:
        if stamp is None:
            numbers[item_id] = 0
            continue
        if previous is None or stamp - previous > timedelta(hours=gap_hours):
            current += 1
        numbers[item_id] = current
        previous = stamp
    return numbers


def draft_listings(drop):
    """TOUS les brouillons du Drop (statut « brouillon prete », ni en ligne ni vendus), une ligne par annonce.

    Source : vinted_drops.json uniquement. Les cartes d'une meme annonce multi-cartes (enregistrees dans
    ``listing_texts`` avec leurs ``card_uids``) sont regroupees ; toute autre reference est une annonce seule.
    Retourne des dicts : key, group_id, item_ids, card_uids, refs, cards (quantite), value, name, number, set,
    created_at (ISO du brouillon le plus recent), series (1, 2, ... ; 0 = date inconnue), series_count.
    """
    if not drop:
        return []
    drafts = [ref for ref in drop.get("cards", []) or [] if drop_ref_is_restock_draft(ref)]
    series = _series_numbers(drafts)
    by_uid = {}
    for ref in drafts:
        by_uid.setdefault(_s(ref.get("card_uid")), []).append(ref)
    used = set()
    groups = []
    texts = drop.get("listing_texts") or {}
    for group_id, record in texts.items():
        uids = [_s(uid) for uid in (record or {}).get("card_uids") or [] if _s(uid)]
        if len(uids) < 2:
            continue
        picked, taken = [], set()
        for uid in uids:
            ref = next((r for r in by_uid.get(uid, []) if id(r) not in used and id(r) not in taken), None)
            if ref is None:
                picked = []
                break
            picked.append(ref)
            taken.add(id(ref))
        if len(picked) >= 2:
            used |= taken
            groups.append((_s(group_id), picked))
    for ref in drafts:
        if id(ref) not in used:
            groups.append(("", [ref]))
    listings = []
    for group_id, refs in groups:
        first = refs[0]
        stamps = [parse_iso(r.get("draft_ready_at")) for r in refs]
        stamps = [s for s in stamps if s]
        item_ids = [_s(r.get("drop_item_id")) for r in refs]
        listings.append({
            "key": item_ids[0] or _s(first.get("card_uid")),
            "group_id": group_id,
            "item_ids": item_ids,
            "card_uids": [_s(r.get("card_uid")) for r in refs],
            "refs": refs,
            "cards": sum(_qty(r) for r in refs),
            "value": sum(_price(r) * _qty(r) for r in refs),
            "name": " + ".join(_s(r.get("name")) or "Carte" for r in refs),
            "number": " + ".join(_s(r.get("display_number") or r.get("number")) for r in refs if _s(r.get("display_number") or r.get("number"))),
            "set": _s(first.get("set")),
            "created_at": max(stamps).isoformat(timespec="seconds") if stamps else "",
            "series": max((series.get(i, 0) for i in item_ids), default=0),
        })
    count = max((item["series"] for item in listings), default=0)
    for item in listings:
        item["series_count"] = count
    listings.sort(key=lambda item: (item["series"] == 0, item["series"], item["created_at"], item["name"]))
    return listings


# --------------------------------------------------------------------------- mise en ligne groupee

def validate_online_at(drop, online_at, *, now=None):
    """('', datetime) si la date/heure choisie est acceptable, sinon (message, None)."""
    stamp = online_at if isinstance(online_at, datetime) else parse_iso(online_at)
    if stamp is None:
        return "Date ou heure de mise en ligne invalide.", None
    reference = now or datetime.now()
    if stamp > reference + timedelta(minutes=1):
        return "La mise en ligne ne peut pas être dans le futur.", None
    launched = parse_iso((drop or {}).get("drop_launched_at"))
    if launched and stamp < launched:
        return "La mise en ligne ne peut pas précéder le lancement du Drop.", None
    return "", stamp


def apply_mark_online(drop_id, item_ids, online_at, *, load_drops, save_drops, drops_path=None, backup_dir=None,
                      journal_path=None, confirmed=False, now=None):
    """Marque en ligne les brouillons ``item_ids`` du Drop, avec l'horodatage ``online_at`` choisi.

    * ``confirmed`` doit etre vrai ; seules les references encore « brouillon » (draft_ready, ni en ligne ni
      vendues) changent : tout autre statut est ignore et signale ;
    * relit vinted_drops.json avant d'ecrire (``load_drops``), sauvegarde dans backups/, ecrit via ``save_drops`` ;
    * une ligne de journal par reference (etat d'avant), de quoi annuler le lot.
    Retourne {"ok", "batch", "marked", "skipped", "message", "backups"}.
    """
    base = {"ok": False, "batch": "", "marked": 0, "skipped": [], "backups": []}
    if not confirmed:
        return {**base, "message": "Confirmation requise : rien n'a été écrit."}
    wanted = {_s(i) for i in item_ids or [] if _s(i)}
    if not wanted:
        return {**base, "message": "Aucune annonce sélectionnée : rien n'a été écrit."}
    drops = load_drops()
    drop = find_drop(drops, drop_id)
    if drop is None:
        return {**base, "message": "Drop introuvable : rien n'a été écrit."}
    if not drop_is_launched(drop):
        return {**base, "message": "Le Drop n'est pas encore lancé : rien n'a été écrit."}
    error, stamp = validate_online_at(drop, online_at, now=now)
    if error:
        return {**base, "message": error}
    stamp_text = stamp.isoformat(timespec="seconds")
    batch = uuid.uuid4().hex[:12]
    at = (now or datetime.now()).isoformat(timespec="seconds")
    journal, skipped = [], []
    for ref in drop.get("cards", []) or []:
        item_id = _s(ref.get("drop_item_id"))
        if item_id not in wanted:
            continue
        if not drop_ref_is_restock_draft(ref):
            skipped.append((_s(ref.get("name")) or item_id, "n'est plus un brouillon : laissée telle quelle"))
            continue
        before = {field: copy.deepcopy(ref.get(field)) for field in ONLINE_FIELDS}
        ref["status"] = "online"
        ref["online_at"] = stamp_text
        ref["listing_posted"] = True
        ref["listing_posted_at"] = stamp_text
        journal.append({
            "action": ACTION_MARK, "batch": batch, "at": at, "drop_id": _s(drop_id), "drop_item_id": item_id,
            "label": _s(ref.get("name")), "online_at": stamp_text,
            "value": _price(ref) * _qty(ref), "before": before,
        })
    if not journal:
        return {**base, "skipped": skipped, "message": "Rien n'a été écrit (aucun brouillon à marquer en ligne)."}
    backups = []
    if drops_path and os.path.exists(drops_path):
        backups.append(ext._backup(drops_path, backup_dir or ext.BACKUP_DIR, "mise_en_ligne_brouillons"))
    save_drops(drops)
    ext.append_journal(journal, journal_path or JOURNAL_FILE)
    return {"ok": True, "batch": batch, "marked": len(journal), "skipped": skipped, "backups": backups,
            "message": f"{len(journal)} annonce(s) marquée(s) en ligne le {stamp.strftime('%d/%m/%Y à %H:%M')}."}


def last_marking_batch(drop_id=None, journal_path=None):
    """Dernier lot de mise en ligne non annule (optionnellement pour un Drop) : {batch, at, online_at, count, value, entries}."""
    entries = ext.read_journal(journal_path or JOURNAL_FILE)
    undone = {e.get("batch") for e in entries if e.get("action") == ACTION_UNDO}
    batches = {}
    for entry in entries:
        if entry.get("action") != ACTION_MARK or entry.get("batch") in undone:
            continue
        if drop_id is not None and _s(entry.get("drop_id")) != _s(drop_id):
            continue
        item = batches.setdefault(entry["batch"], {"batch": entry["batch"], "at": entry.get("at", ""),
                                                   "online_at": entry.get("online_at", ""), "entries": []})
        item["entries"].append(entry)
    if not batches:
        return None
    latest = max(batches.values(), key=lambda b: b["at"])
    latest["count"] = len(latest["entries"])
    latest["value"] = sum(float(e.get("value") or 0) for e in latest["entries"])
    return latest


def undo_marking_batch(batch, *, load_drops, save_drops, drops_path=None, backup_dir=None, journal_path=None, now=None):
    """Annule un lot : remet « brouillon prete » et retire l'horodatage, SEULEMENT pour les references encore
    dans l'etat ecrit par le lot (en ligne, meme ``online_at``). Une carte vendue ou modifiee depuis est laissee."""
    journal_path = journal_path or JOURNAL_FILE
    all_entries = ext.read_journal(journal_path)
    entries = [e for e in all_entries if e.get("action") == ACTION_MARK and e.get("batch") == batch]
    if not entries:
        return {"ok": False, "undone": 0, "skipped": [], "message": "Lot introuvable dans le journal."}
    if any(e.get("action") == ACTION_UNDO and e.get("batch") == batch for e in all_entries):
        return {"ok": False, "undone": 0, "skipped": [], "message": "Ce lot a déjà été annulé."}
    drops = load_drops()
    undone, skipped = 0, []
    for entry in entries:
        drop = find_drop(drops, entry.get("drop_id"))
        ref = next((r for r in (drop or {}).get("cards", []) or []
                    if _s(r.get("drop_item_id")) == _s(entry.get("drop_item_id"))), None)
        label = entry.get("label") or entry.get("drop_item_id")
        if ref is None:
            skipped.append((label, "carte introuvable"))
            continue
        if (drop_item_status(ref) != "online" or _s(ref.get("online_at")) != _s(entry.get("online_at"))
                or _s(ref.get("sold_at"))):
            skipped.append((label, "n'est plus dans l'état écrit par ce lot : laissée telle quelle"))
            continue
        for field, value in (entry.get("before") or {}).items():
            if value is None:
                ref.pop(field, None)
            else:
                ref[field] = copy.deepcopy(value)
        undone += 1
    if not undone:
        return {"ok": False, "undone": 0, "skipped": skipped, "message": "Rien à annuler."}
    backups = []
    if drops_path and os.path.exists(drops_path):
        backups.append(ext._backup(drops_path, backup_dir or ext.BACKUP_DIR, "annulation_mise_en_ligne_brouillons"))
    save_drops(drops)
    ext.append_journal([{"action": ACTION_UNDO, "batch": batch, "at": (now or datetime.now()).isoformat(timespec="seconds"),
                         "undone": undone}], journal_path)
    return {"ok": True, "undone": undone, "skipped": skipped, "backups": backups,
            "message": f"{undone} annonce(s) remise(s) en brouillon, horodatage retiré."}

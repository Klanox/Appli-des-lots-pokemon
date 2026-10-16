"""Textes d'annonces Vinted : « a jour / ancien format / modifie a la main », regeneration en bloc, liste Vinted.

Diagnostic du 15/10/2026
------------------------
* Titre, description et prix ne sont ENREGISTRES NULLE PART (ni data.json, ni vinted_drops.json, ni les sessions
  d'analyse) : ils sont recalcules par services/vinted_listing_service.py a chaque affichage d'une annonce, puis
  gardes dans la session du navigateur (champs de l'etape 4 + une « ombre » qui sert a restaurer le texte quand
  l'ecran est quitte puis retrouve).
* Un ancien texte survivait donc UNIQUEMENT dans une session de navigateur ouverte avant le changement de regles,
  ou dans le brouillon / l'annonce DEJA publie(e) sur Vinted (que l'application ne peut pas modifier).
* Depuis ce correctif, le texte reellement utilise est memorise dans vinted_drops.json au clic sur
  « Brouillon cree » (drop["listing_texts"][groupe], avec un indicateur « modifie a la main »), ce qui permet de
  savoir a l'avenir ce qui est parti chez Vinted. Pour les brouillons deja crees, rien n'etait memorise : le texte
  « enregistre » est alors SUPPOSE egal a ce que produisait l'ancien generateur (services/listing_legacy, copie
  figee). En cas de doute (texte different de l'ancien ET du nouveau generateur) : considere comme modifie a la main,
  jamais ecrase.

Ce module ne depend pas de Streamlit. Il n'ecrit que dans vinted_drops.json (cles listing_texts et vinted_updates
du Drop), via les fonctions de sauvegarde normales qu'on lui passe, apres sauvegarde dans backups/ et avec un
journal (logs/) qui permet d'annuler un lot. Prix, photos, statuts, ordre et cartes ne sont jamais touches.
"""

from __future__ import annotations

import copy
import os
import uuid
from datetime import datetime

from services import card_extension_service as ext
from services.listing_legacy.generator import prepare_listing as _legacy_prepare_listing
from services.vinted_listing_service import prepare_listing as _current_prepare_listing

RULES_VERSION = "2026-10-15"
TEXTS_KEY = "listing_texts"
UPDATES_KEY = "vinted_updates"
JOURNAL_FILE = os.path.join(ext.LOG_DIR, "listing_text_regeneration_journal.jsonl")

STATE_UP_TO_DATE = "a_jour"
STATE_LEGACY = "ancien_format"
STATE_MANUAL = "manuel"

STATUS_TO_PREPARE = "to_prepare"
STATUS_DRAFT = "draft_ready"
STATUS_ONLINE = "online"
STATUS_SOLD = "sold"
STATUS_OTHER = "other"

KIND_DRAFT = "draft"
KIND_ONLINE = "online"
UPDATE_LABELS = {
    KIND_DRAFT: "Brouillon Vinted à mettre à jour",
    KIND_ONLINE: "Annonce en ligne à mettre à jour",
}

ACTION_OK = "ok"
ACTION_REGENERATE = "regenerate"
ACTION_DISPLAY = "recalcul_affichage"
ACTION_SKIP_MANUAL = "skip_manual"
ACTION_UPDATE_ONLINE = "vinted_update_online"
ACTION_SKIP = "skip"


def _s(value):
    return str(value or "").strip()


def _norm(value):
    return "\n".join(line.rstrip() for line in str(value or "").replace("\r\n", "\n").strip().split("\n"))


# --------------------------------------------------------------------------- generateurs et etat d'un texte

def current_texts(cards, listing_type):
    prepared = _current_prepare_listing(list(cards or []), listing_type)
    return {"title": prepared["title"], "description": prepared["description"]}


def legacy_texts(cards, listing_type):
    """Texte que l'ancien generateur aurait produit (None si l'ancien generateur n'y arrive pas)."""
    try:
        prepared = _legacy_prepare_listing(list(cards or []), listing_type)
    except Exception:
        return None
    return {"title": prepared["title"], "description": prepared["description"]}


def text_state(title, description, current, legacy=None, *, manual=False):
    """« a_jour » (= regles actuelles), « ancien_format » (= ancien generateur) ou « manuel » (autre, ou indicateur).

    Champ par champ : un seul champ qui n'est ni le texte actuel ni l'ancien suffit a classer l'ensemble « manuel ».
    """
    if manual:
        return STATE_MANUAL
    legacy_hit = False
    for name, value in (("title", title), ("description", description)):
        value = _norm(value)
        if value == _norm(current.get(name)):
            continue
        if legacy and value == _norm(legacy.get(name)):
            legacy_hit = True
            continue
        return STATE_MANUAL
    return STATE_LEGACY if legacy_hit else STATE_UP_TO_DATE


def state_label(state):
    return {STATE_UP_TO_DATE: "Texte à jour", STATE_LEGACY: "Texte ancien format",
            STATE_MANUAL: "Texte modifié à la main"}.get(state, "")


def stored_record(drop, group_id, card_uids=None):
    """Texte memorise pour cette annonce, ou None. Ignore un enregistrement dont les cartes ne correspondent plus."""
    record = ((drop or {}).get(TEXTS_KEY) or {}).get(_s(group_id))
    if not isinstance(record, dict):
        return None
    if card_uids is not None and sorted(_s(u) for u in record.get("card_uids") or []) != sorted(_s(u) for u in card_uids):
        return None
    return record


def make_record(title, description, *, state, card_uids, listing_type, origin, now=None):
    return {
        "title": title, "description": description, "origin": origin,
        "manual": state == STATE_MANUAL, "state": state,
        "saved_at": now or datetime.now().isoformat(timespec="seconds"), "rules": RULES_VERSION,
        "card_uids": [_s(u) for u in card_uids or []], "listing_type": listing_type,
    }


def record_draft_text(drop, group_id, title, description, cards, listing_type, card_uids):
    """Memorise le texte reellement utilise au clic « Brouillon cree » (dans le dict du Drop, a sauvegarder ensuite).

    Retourne l'etat du texte (a_jour / ancien_format / manuel)."""
    current = current_texts(cards, listing_type)
    state = text_state(title, description, current, legacy_texts(cards, listing_type))
    drop.setdefault(TEXTS_KEY, {})[_s(group_id)] = make_record(
        title, description, state=state, card_uids=card_uids, listing_type=listing_type,
        origin="manual" if state == STATE_MANUAL else "auto",
    )
    return state


# --------------------------------------------------------------------------- apercu (rien n'est ecrit)

def build_plan(entries, drop, *, progress=None):
    """Calcule ce que ferait la regeneration. ``entries`` : une par annonce du Drop affiche
    {group_id, label, status_class, cards, listing_type, card_uids, order}.

    Aucune ecriture. ``progress(phase, done, total)`` (optionnel) recoit l'avancement.
    """
    total = len(entries)
    rows = []
    counts = {"total": total, "ok": 0, "regenerate": 0, "display": 0, "manual": 0, "update_online": 0,
              "skipped": 0, "to_prepare": 0, "draft": 0, "online": 0}
    if progress:
        progress("textes", 0, max(1, total))
    for index, entry in enumerate(entries, start=1):
        row = _plan_row(entry, drop)
        rows.append(row)
        action = row["action"]
        counts[{ACTION_OK: "ok", ACTION_REGENERATE: "regenerate", ACTION_DISPLAY: "display",
                ACTION_SKIP_MANUAL: "manual", ACTION_UPDATE_ONLINE: "update_online"}.get(action, "skipped")] += 1
        if row["status_class"] == STATUS_TO_PREPARE:
            counts["to_prepare"] += 1
        elif row["status_class"] == STATUS_DRAFT:
            counts["draft"] += 1
        elif row["status_class"] == STATUS_ONLINE:
            counts["online"] += 1
        if progress:
            progress("textes", index, max(1, total))
    changed = [r for r in rows if r["action"] in (ACTION_REGENERATE, ACTION_DISPLAY, ACTION_UPDATE_ONLINE)]
    changed.sort(key=lambda r: {STATUS_DRAFT: 0, STATUS_ONLINE: 1}.get(r["status_class"], 2))  # exemples : brouillons d'abord
    return {"drop_id": _s((drop or {}).get("id")), "rows": rows, "counts": counts, "changed": changed,
            "examples": changed[:5], "to_write": [r for r in rows if r["action"] == ACTION_REGENERATE],
            "to_list": [r for r in rows if r.get("update_kind")]}


def _plan_row(entry, drop):
    group_id = _s(entry.get("group_id"))
    status = entry.get("status_class") or STATUS_OTHER
    cards, listing_type = entry.get("cards") or [], entry.get("listing_type") or "Carte seule"
    row = {"group_id": group_id, "label": entry.get("label") or group_id, "order": entry.get("order"),
           "status_class": status, "listing_type": listing_type, "card_uids": list(entry.get("card_uids") or []),
           "action": ACTION_SKIP, "state": "", "update_kind": "", "before_title": "", "after_title": "",
           "before_description": "", "after_description": "", "record_before": None, "assumed": False, "reason": ""}
    if status in (STATUS_SOLD, STATUS_OTHER) or not cards:
        row["reason"] = "vendue" if status == STATUS_SOLD else "statut mixte ou carte introuvable"
        return row
    current = current_texts(cards, listing_type)
    legacy = legacy_texts(cards, listing_type)
    record = stored_record(drop, group_id, row["card_uids"])
    if record:
        before = {"title": _s(record.get("title")), "description": _s(record.get("description"))}
        state = text_state(before["title"], before["description"], current, legacy, manual=bool(record.get("manual")))
        row["record_before"] = copy.deepcopy(record)
    elif legacy:
        before, row["assumed"] = legacy, True
        state = text_state(before["title"], before["description"], current, legacy)
    else:
        row["reason"] = "ancien texte introuvable"
        return row
    row.update(state=state, before_title=before["title"], after_title=current["title"],
               before_description=before["description"], after_description=current["description"])
    if state == STATE_MANUAL:
        row["action"] = ACTION_SKIP_MANUAL
        row["reason"] = "texte modifié à la main : laissé tel quel"
    elif state == STATE_UP_TO_DATE:
        row["action"] = ACTION_OK
    elif status == STATUS_TO_PREPARE:
        row["action"] = ACTION_DISPLAY  # rien d'enregistre : le texte est recalcule a l'ouverture de l'annonce
    elif status == STATUS_DRAFT:
        row["action"] = ACTION_REGENERATE
        row["update_kind"] = KIND_DRAFT
    elif status == STATUS_ONLINE:
        row["action"] = ACTION_UPDATE_ONLINE  # jamais modifiee dans l'appli : seulement signalee
        row["update_kind"] = KIND_ONLINE
    return row


# --------------------------------------------------------------------------- ecriture et annulation

def apply_plan(plan, *, load_drops, save_drops, drops_path, backup_dir=None, journal_path=None, confirmed=False):
    """Ecrit le resultat d'un apercu confirme. Retourne {"ok", "batch", "regenerated", "listed", "skipped", "message"}.

    * ``confirmed`` doit etre vrai (confirmation explicite de l'utilisateur) ;
    * releit vinted_drops.json avant d'ecrire et ne touche pas une annonce dont l'enregistrement a change depuis
      l'apercu ;
    * sauvegarde vinted_drops.json dans backups/ puis ecrit via ``save_drops`` (synchro Cloud comprise) ;
    * une ligne de journal par annonce (logs/), de quoi annuler le lot.
    """
    if not confirmed:
        return {"ok": False, "batch": "", "regenerated": 0, "listed": 0, "skipped": [],
                "message": "Confirmation requise : rien n'a été écrit."}
    rows = [r for r in plan.get("rows", []) if r["action"] in (ACTION_REGENERATE, ACTION_UPDATE_ONLINE)]
    if not rows:
        return {"ok": True, "batch": "", "regenerated": 0, "listed": 0, "skipped": [],
                "message": "Rien à écrire : aucun texte à régénérer."}
    drops = load_drops()
    drop = next((d for d in drops.get("drops", []) if _s(d.get("id")) == plan.get("drop_id")), None)
    if drop is None:
        return {"ok": False, "batch": "", "regenerated": 0, "listed": 0, "skipped": [],
                "message": "Drop introuvable : rien n'a été écrit."}
    batch = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat(timespec="seconds")
    skipped, journal, regenerated, listed = [], [], 0, 0
    texts = drop.setdefault(TEXTS_KEY, {})
    updates = drop.setdefault(UPDATES_KEY, [])
    for row in rows:
        group_id = row["group_id"]
        existing = texts.get(group_id)
        if row["action"] == ACTION_REGENERATE and (existing or None) != (row["record_before"] or None):
            skipped.append((row["label"], "texte modifié depuis l'aperçu : laissé tel quel"))
            continue
        entry = {"action": "regenerate", "batch": batch, "at": now, "drop_id": plan["drop_id"], "group_id": group_id,
                 "label": row["label"], "status": row["status_class"], "kind": row["update_kind"],
                 "title_before": row["before_title"], "title_after": row["after_title"],
                 "assumed_before": row["assumed"], "record_before": copy.deepcopy(existing), "record_after": None,
                 "update_id": ""}
        if row["action"] == ACTION_REGENERATE:
            record = make_record(row["after_title"], row["after_description"], state=STATE_UP_TO_DATE,
                                 card_uids=row["card_uids"], listing_type=row["listing_type"], origin="regenerated", now=now)
            texts[group_id] = record
            entry["record_after"] = copy.deepcopy(record)
            regenerated += 1
        update_id = f"{plan['drop_id']}:{group_id}"
        updates[:] = [u for u in updates if not (u.get("id") == update_id and not u.get("done_at"))]
        updates.append({
            "id": update_id, "batch": batch, "group_id": group_id, "kind": row["update_kind"],
            "label": UPDATE_LABELS[row["update_kind"]], "cards": row["label"],
            "title_before": row["before_title"], "title_after": row["after_title"],
            "description_after": row["after_description"], "assumed_before": row["assumed"],
            "created_at": now, "done_at": "",
        })
        entry["update_id"] = update_id
        listed += 1
        journal.append(entry)
    if not journal:
        return {"ok": False, "batch": "", "regenerated": 0, "listed": 0, "skipped": skipped,
                "message": "Rien n'a été écrit (les annonces ont changé depuis l'aperçu)."}
    backups = []
    if drops_path and os.path.exists(drops_path):
        backups.append(ext._backup(drops_path, backup_dir or ext.BACKUP_DIR, "regeneration_textes"))
    save_drops(drops)
    ext.append_journal(journal, journal_path or JOURNAL_FILE)
    return {"ok": True, "batch": batch, "regenerated": regenerated, "listed": listed, "skipped": skipped,
            "backups": backups,
            "message": f"{regenerated} texte(s) régénéré(s) et {listed} annonce(s) ajoutée(s) à la liste « à mettre à jour sur Vinted »."}


def journal_batches(journal_path=None):
    """Lots annulables, du plus recent au plus ancien : [{batch, at, count, entries}]."""
    entries = ext.read_journal(journal_path or JOURNAL_FILE)
    undone = {e.get("batch") for e in entries if e.get("action") == "undo"}
    batches = {}
    for entry in entries:
        if entry.get("action") != "regenerate" or entry.get("batch") in undone:
            continue
        batches.setdefault(entry["batch"], {"batch": entry["batch"], "at": entry.get("at", ""), "entries": []})["entries"].append(entry)
    out = list(batches.values())
    for item in out:
        item["count"] = len(item["entries"])
    return sorted(out, key=lambda b: b["at"], reverse=True)


def undo_batch(batch, *, load_drops, save_drops, drops_path, backup_dir=None, journal_path=None):
    """Annule un lot : remet l'ancien enregistrement (ou le supprime) SEULEMENT si le texte est encore celui ecrit par
    la regeneration, et retire de la liste « a mettre a jour » les lignes de ce lot qui n'ont pas ete traitees."""
    journal_path = journal_path or JOURNAL_FILE
    all_entries = ext.read_journal(journal_path)
    entries = [e for e in all_entries if e.get("action") == "regenerate" and e.get("batch") == batch]
    if not entries:
        return {"ok": False, "undone": 0, "skipped": [], "message": "Lot introuvable dans le journal."}
    if any(e.get("action") == "undo" and e.get("batch") == batch for e in all_entries):
        return {"ok": False, "undone": 0, "skipped": [], "message": "Ce lot a déjà été annulé."}
    drops = load_drops()
    undone, skipped = 0, []
    for entry in entries:
        drop = next((d for d in drops.get("drops", []) if _s(d.get("id")) == _s(entry.get("drop_id"))), None)
        if drop is None:
            skipped.append((entry.get("label"), "Drop introuvable"))
            continue
        texts = drop.setdefault(TEXTS_KEY, {})
        after = entry.get("record_after")
        if after is not None and texts.get(entry["group_id"]) != after:
            skipped.append((entry.get("label"), "texte modifié depuis : laissé tel quel"))
            continue
        if after is not None:
            if entry.get("record_before") is None:
                texts.pop(entry["group_id"], None)
            else:
                texts[entry["group_id"]] = entry["record_before"]
        drop[UPDATES_KEY] = [u for u in drop.get(UPDATES_KEY, []) if not (u.get("id") == entry.get("update_id")
                                                                           and u.get("batch") == batch and not u.get("done_at"))]
        undone += 1
    if not undone:
        return {"ok": False, "undone": 0, "skipped": skipped, "message": "Rien à annuler."}
    backups = []
    if drops_path and os.path.exists(drops_path):
        backups.append(ext._backup(drops_path, backup_dir or ext.BACKUP_DIR, "annulation_regeneration_textes"))
    save_drops(drops)
    ext.append_journal([{"action": "undo", "batch": batch, "at": datetime.now().isoformat(timespec="seconds"),
                         "undone": undone}], journal_path)
    return {"ok": True, "undone": undone, "skipped": skipped, "backups": backups,
            "message": f"{undone} annonce(s) remise(s) dans leur état d'avant."}


# --------------------------------------------------------------------------- liste « a mettre a jour sur Vinted »

def pending_updates(drops):
    """[(drop, update)] non traites, tous Drops confondus (le plus recent d'abord)."""
    out = []
    for drop in (drops or {}).get("drops", []) or []:
        for update in drop.get(UPDATES_KEY, []) or []:
            if not update.get("done_at"):
                out.append((drop, update))
    return sorted(out, key=lambda pair: pair[1].get("created_at", ""), reverse=True)


def pending_update_group_ids(drop):
    return {u.get("group_id") for u in (drop or {}).get(UPDATES_KEY, []) or [] if not u.get("done_at")}


def mark_update_done(drops, drop_id, update_id, *, save_drops):
    for drop in drops.get("drops", []) or []:
        if _s(drop.get("id")) != _s(drop_id):
            continue
        for update in drop.get(UPDATES_KEY, []) or []:
            if update.get("id") == update_id and not update.get("done_at"):
                update["done_at"] = datetime.now().isoformat(timespec="seconds")
                save_drops(drops)
                return True
    return False

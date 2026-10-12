from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime

from utils import safe_write_json
from services.cloud_sync_service import save_synced_dataset
from services.card_identity import card_identity_fingerprint
from services.vinted_channels import normalize_vinted_channel, is_vinted_channel
from services.vinted_listing_service import card_search_blob, full_card_number, normalize_search_text


VINTED_DROPS_FILE = "vinted_drops.json"
DROP_ITEM_STATUSES = {
    "to_photograph": "À photographier",
    "needs_review": "À vérifier",
    "sorted": "Triée",
    "to_prepare": "À préparer",
    "draft_ready": "Brouillon prêt",
    "online": "En ligne",
    "sold": "Vendue",
}

DROP_CARD_IDENTITY_FIELDS = (
    "name",
    "number",
    "num",
    "localId",
    "full_number",
    "display_number",
    "collector_number",
    "printed_number",
    "card_number",
    "set",
    "serie",
    "extension",
    "set_name",
    "set_id",
    "card_id",
    "lang",
    "language",
    "japanese",
    "is_japanese",
    "reverse",
    "is_reverse",
    "first_edition",
    "is_ed1",
    "firstEdition",
    "stamp",
    "stamp_label",
    "is_stamp",
    "promo",
    "is_promo",
    "master_ball",
    "is_master_ball",
    "poke_ball",
    "is_poke_ball",
    "variant",
    "version",
    "finish",
    "foil",
    "special",
    "special_tag",
    "rarity",
    "category",
    "tags",
    "metadata_tags",
    "card_tags",
    "subtypes",
    "types",
    "manual_image_path",
    "manual_image_url",
    "local_image",
    "local_image_path",
    "image_path",
    "photo_path",
    "cached_image_path",
    "resolved_collection_image_url",
    "image_url_ja",
    "image_url_jp",
    "image_url_japanese",
    "image_ja",
    "image_jp",
    "image_url",
    "image_url_en",
    "image_en",
    "image",
    "imageUrl",
)


def default_drops_data():
    return {"drops": []}


def load_vinted_drops(path=VINTED_DROPS_FILE):
    if not os.path.exists(path):
        return default_drops_data()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default_drops_data()
    if not isinstance(data, dict):
        return default_drops_data()
    drops = data.get("drops", [])
    if not isinstance(drops, list):
        drops = []
    data["drops"] = drops
    return data


def save_vinted_drops(data, path=VINTED_DROPS_FILE):
    if path == VINTED_DROPS_FILE:
        save_synced_dataset("vinted_drops", data, indent=2)
    else:
        safe_write_json(path, data, indent=2)


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def create_drop(data, name, channel=""):
    name = str(name or "").strip()
    if not name:
        name = f"Drop Vinted {datetime.now().strftime('%d/%m/%Y')}"
    drop = {
        "id": uuid.uuid4().hex,
        "name": name,
        "channel": normalize_vinted_channel(channel),
        "created_at": _now_iso(),
        "drop_launched_at": "",
        "archived": False,
        "archived_at": "",
        "cards": [],
    }
    data.setdefault("drops", []).append(drop)
    return drop


def rename_drop(data, drop_id, name):
    name = str(name or "").strip()
    if not name:
        return False
    drop = find_drop(data, drop_id)
    if not drop:
        return False
    drop["name"] = name
    return True


def delete_drop(data, drop_id):
    before = len(data.get("drops", []))
    data["drops"] = [drop for drop in data.get("drops", []) if drop.get("id") != drop_id]
    return len(data["drops"]) != before


def update_drop_channel(data, drop_id, channel):
    drop = find_drop(data, drop_id)
    if not drop:
        return False
    drop["channel"] = normalize_vinted_channel(channel)
    return True


def drop_is_archived(drop):
    return bool((drop or {}).get("archived"))


def active_drops(data):
    """Drops shown in the working lists (not archived)."""
    return [drop for drop in (data or {}).get("drops", []) or [] if not drop_is_archived(drop)]


def archived_drops(data):
    return [drop for drop in (data or {}).get("drops", []) or [] if drop_is_archived(drop)]


def archive_drop(data, drop_id):
    """Flag a drop as archived. Cards, statuses and sales links are untouched."""
    drop = find_drop(data, drop_id)
    if not drop or drop_is_archived(drop):
        return False
    drop["archived"] = True
    drop["archived_at"] = _now_iso()
    return True


def restore_drop(data, drop_id):
    drop = find_drop(data, drop_id)
    if not drop or not drop_is_archived(drop):
        return False
    drop["archived"] = False
    drop["archived_at"] = ""
    return True


def find_drop(data, drop_id):
    for drop in data.get("drops", []):
        if drop.get("id") == drop_id:
            return drop
    return None


def resolve_drop_item_card_identity(drop_item, source_card=None):
    """Return a Drop item with its current source-card identity when UID matches.

    Workflow state, dates, listing prices and sales links intentionally remain
    on the Drop item. Old rows without a reliable card UID keep their snapshot.
    """
    item = dict(drop_item or {})
    source = source_card if isinstance(source_card, dict) else {}
    item_uid = str(item.get("card_uid") or "").strip()
    source_uid = str(source.get("card_uid") or "").strip()
    if not item_uid or item_uid != source_uid:
        return item

    for field in DROP_CARD_IDENTITY_FIELDS:
        if field in source:
            item[field] = source[field]

    display_number = full_card_number(source)
    if display_number:
        item["display_number"] = display_number
    item["identity_fingerprint"] = card_identity_fingerprint(item)
    return item


def drop_card_key(card_ref):
    return "::".join(
        [
            str(card_ref.get("lot_uid") or ""),
            str(card_ref.get("card_uid") or ""),
            str(card_ref.get("lot_idx") or 0),
            str(card_ref.get("card_idx") or 0),
            str(card_ref.get("name") or ""),
            str(card_ref.get("number") or ""),
            str(card_ref.get("set") or ""),
        ]
    )


_POSITIONAL_UID_RE = re.compile(r"^\d+:\d+$")


def drop_card_identity(card_ref):
    """Stable identity of a card inside a Drop: (card_uid, lot_uid).

    Positional indexes (lot_idx/card_idx), names and numbers change when lots
    are reordered/archived or cards are renamed, so they must not decide whether
    a card is already in a Drop. A missing card_uid (or the positional fallback
    "3:5" built by the UI for cards without uid) returns None: callers then fall
    back to the legacy drop_card_key for old data.
    """
    ref = card_ref or {}
    card_uid = str(ref.get("card_uid") or "").strip()
    if not card_uid or _POSITIONAL_UID_RE.match(card_uid):
        return None
    return (card_uid, str(ref.get("lot_uid") or "").strip())


def drop_card_match_key(card_ref):
    """Key used to decide that two card refs are the same Drop item."""
    identity = drop_card_identity(card_ref)
    if identity is not None:
        return ("uid",) + identity
    return ("legacy", drop_card_key(card_ref or {}))


def _drop_match_keys(drop):
    return {drop_card_match_key(ref) for ref in (drop or {}).get("cards", []) or []}


def _ref_quantity(ref):
    try:
        return max(1, int((ref or {}).get("quantity", 1) or 1))
    except (TypeError, ValueError):
        return 1


def drop_matching_refs(drop, card):
    """All Drop refs that point to the same card line (card_uid, lot_uid)."""
    key = drop_card_match_key(card)
    return [ref for ref in (drop or {}).get("cards", []) or [] if drop_card_match_key(ref) == key]


def drop_remaining_quantity(drop, card, matches=None):
    """Copies of a card still available and not reserved by an active Drop ref.

    Returns None when the card carries no stock information (``available_qty``),
    so callers keep the historical "one ref = already in drop" behaviour.
    Sold refs do not reserve anything: their copy already left the stock and is
    already subtracted from ``available_qty``.
    """
    if card is None or card.get("available_qty") is None:
        return None
    try:
        available = int(card.get("available_qty"))
    except (TypeError, ValueError):
        return None
    refs = drop_matching_refs(drop, card) if matches is None else matches
    reserved = sum(_ref_quantity(ref) for ref in refs if drop_item_status(ref) != "sold")
    return available - reserved


def find_drop_ref(drop, item_key):
    """Return one Drop ref from its drop_item_id.

    Falls back to the legacy card key only for old callers/data; in that case an
    active (non-sold) ref is preferred so a sold twin is never modified by mistake.
    """
    key = str(item_key or "")
    if not key:
        return None
    refs = (drop or {}).get("cards", []) or []
    for ref in refs:
        if str(ref.get("drop_item_id") or "") == key:
            return ref
    legacy = [ref for ref in refs if drop_card_key(ref) == key]
    for ref in legacy:
        if drop_item_status(ref) != "sold":
            return ref
    return legacy[0] if legacy else None


def drop_ref_key(ref):
    """Unique key of a Drop ref (drop_item_id, legacy card key if missing)."""
    return str((ref or {}).get("drop_item_id") or "") or drop_card_key(ref or {})


def make_card_ref(card):
    try:
        quantity = int(card.get("drop_quantity", card.get("quantity_to_add", card.get("quantity", 1))) or 1)
    except Exception:
        quantity = 1
    quantity = max(1, quantity)
    return {
        "lot_uid": card.get("lot_uid", ""),
        "card_uid": card.get("card_uid", ""),
        "lot_idx": card.get("lot_idx", 0),
        "card_idx": card.get("card_idx", 0),
        "name": card.get("name", ""),
        "number": card.get("number", ""),
        "display_number": full_card_number(card),
        "set": card.get("set", ""),
        "image_url": card.get("image_url", "") or card.get("image_url_en", ""),
        "price_at_add": card.get("price", card.get("suggested_price", 0)),
        "quantity": quantity,
        "identity_fingerprint": card.get("identity_fingerprint") or card_identity_fingerprint(card),
        "drop_item_id": card.get("drop_item_id") or uuid.uuid4().hex,
        "status": "to_photograph",
        "added_at": _now_iso(),
        "draft_ready_at": "",
        "online_at": "",
        "sold_at": "",
        "listing_posted": bool(card.get("listing_posted", False)),
        "listing_posted_at": card.get("listing_posted_at", ""),
    }


def add_cards_to_drop(data, drop_id, cards):
    drop = find_drop(data, drop_id)
    if not drop:
        return 0, len(list(cards or []))
    drop.setdefault("cards", [])
    added = 0
    duplicates = 0
    for card in cards or []:
        matches = drop_matching_refs(drop, card)
        if matches:
            # Same card line already in the Drop: only add copies that are still
            # in stock and not reserved by an active (non-sold) ref.
            remaining = drop_remaining_quantity(drop, card, matches)
            if remaining is None or remaining <= 0:
                duplicates += 1
                continue
            card = dict(card)
            requested = card.get("drop_quantity", card.get("quantity_to_add", card.get("quantity", 1)))
            try:
                requested = max(1, int(requested or 1))
            except (TypeError, ValueError):
                requested = 1
            card["drop_quantity"] = min(requested, remaining)
        ref = make_card_ref(card)
        used_ids = {str(item.get("drop_item_id") or "") for item in drop["cards"]}
        if ref["drop_item_id"] in used_ids:
            ref["drop_item_id"] = uuid.uuid4().hex
        drop["cards"].append(ref)
        added += 1
    return added, duplicates


def card_is_in_drop(drop, card):
    """True when no further copy of this card line can be added to the Drop."""
    matches = drop_matching_refs(drop, card)
    if not matches:
        return False
    remaining = drop_remaining_quantity(drop, card, matches)
    if remaining is None:
        return True
    return remaining <= 0


def add_card_to_drop(data, drop_id, card):
    added, duplicates = add_cards_to_drop(data, drop_id, [card])
    return added == 1, duplicates == 1


def remove_card_from_drop(data, drop_id, card_key):
    drop = find_drop(data, drop_id)
    if not drop:
        return False
    ref = find_drop_ref(drop, card_key)
    if ref is None:
        return False
    drop["cards"] = [card for card in drop.get("cards", []) if card is not ref]
    return True


def drop_item_status(ref):
    status = str((ref or {}).get("status") or "").strip()
    if status in DROP_ITEM_STATUSES:
        return status
    if (ref or {}).get("sold_at"):
        return "sold"
    if (ref or {}).get("online_at") or (ref or {}).get("listing_posted"):
        return "online"
    if (ref or {}).get("draft_ready_at"):
        return "draft_ready"
    return "to_prepare"


# Statuts "pas encore traites" : une reference dans l'un de ces statuts n'a ni annonce
# creee (draft_ready), ni annonce en ligne (online), ni vente (sold).
DROP_UNPROCESSED_STATUSES = frozenset({"to_photograph", "needs_review", "sorted", "to_prepare"})


def drop_is_launched(drop):
    return bool(str((drop or {}).get("drop_launched_at") or "").strip())


def drop_ref_is_unprocessed(ref):
    """Vrai si la reference n'a encore ete ni mise en brouillon, ni publiee, ni vendue.

    Double controle : le statut ET les marqueurs historiques (listing_posted, online_at,
    sold_at). En cas de contradiction, la reference est consideree comme traitee.
    """
    if not isinstance(ref, dict):
        return False
    if drop_item_status(ref) not in DROP_UNPROCESSED_STATUSES:
        return False
    if ref.get("listing_posted") or ref.get("online_at") or ref.get("sold_at"):
        return False
    return True


def drop_restock_refs(drop):
    """References d'un drop DEJA LANCE qui restent a traiter (reassort). Vide si non lance."""
    if not drop_is_launched(drop):
        return []
    return [ref for ref in (drop or {}).get("cards", []) or [] if drop_ref_is_unprocessed(ref)]


def drop_has_restock(drop):
    return bool(drop_restock_refs(drop))


def drop_ref_is_restock_draft(ref):
    """Reference de reassort dont le brouillon est cree mais qui n'est pas encore en ligne."""
    if not isinstance(ref, dict):
        return False
    if drop_item_status(ref) != "draft_ready":
        return False
    return not (ref.get("listing_posted") or ref.get("online_at") or ref.get("sold_at"))


def drop_restock_scope_refs(drop):
    """Perimetre du workflow de reassort : references a traiter + brouillons pas encore en ligne.

    Les brouillons restent dans le perimetre pour que l'ensemble des candidats de la
    reconnaissance reste stable pendant tout le workflow (sinon passer une carte en
    « brouillon cree » rendrait l'analyse photo perimee). Jamais de online / sold.
    """
    if not drop_is_launched(drop):
        return []
    return [
        ref
        for ref in (drop or {}).get("cards", []) or []
        if drop_ref_is_unprocessed(ref) or drop_ref_is_restock_draft(ref)
    ]


def drop_has_restock_scope(drop):
    return bool(drop_restock_scope_refs(drop))


def drop_item_status_label(ref_or_status):
    status = ref_or_status if isinstance(ref_or_status, str) else drop_item_status(ref_or_status)
    return DROP_ITEM_STATUSES.get(status, "À préparer")


def set_drop_card_status(data, drop_id, card_key, status):
    if status not in DROP_ITEM_STATUSES:
        return False
    drop = find_drop(data, drop_id)
    if not drop:
        return False
    now = _now_iso()
    ref = find_drop_ref(drop, card_key)
    if ref is None:
        return False
    ref["status"] = status
    if status == "draft_ready":
        ref["draft_ready_at"] = ref.get("draft_ready_at") or now
    elif status == "online":
        ref["online_at"] = ref.get("online_at") or now
        ref["listing_posted"] = True
        ref["listing_posted_at"] = ref.get("listing_posted_at") or now
    elif status == "sold":
        ref["sold_at"] = ref.get("sold_at") or now
    return True


def toggle_drop_card_posted(data, drop_id, card_key, posted=None):
    drop = find_drop(data, drop_id)
    if not drop:
        return False
    ref = find_drop_ref(drop, card_key)
    if ref is None:
        return False
    new_value = (not bool(ref.get("listing_posted"))) if posted is None else bool(posted)
    ref["listing_posted"] = new_value
    ref["listing_posted_at"] = _now_iso() if new_value else ""
    if new_value:
        ref["status"] = "online"
        ref["online_at"] = ref.get("online_at") or ref["listing_posted_at"]
    return True


def launch_drop(data, drop_id, mode="workflow"):
    """Launch a drop once, using the regular or manual publication workflow."""
    drop = find_drop(data, drop_id)
    if not drop or drop.get("drop_launched_at"):
        return False
    cards = drop.get("cards", []) or []
    if not cards:
        return False

    mode = str(mode or "workflow").strip().lower()
    if mode not in {"workflow", "manual"}:
        return False
    if mode == "manual" and not is_vinted_channel(drop.get("channel", "")):
        return False

    now = _now_iso()
    drop["drop_launched_at"] = now
    if mode == "manual":
        # The listings already exist on Vinted: publish every unsold drop item
        # directly, without manufacturing draft metadata.
        drop["launch_mode"] = "manual"

    for ref in cards:
        status = drop_item_status(ref)
        should_publish = mode == "manual" and status != "sold"
        should_publish = should_publish or (mode == "workflow" and status == "draft_ready")
        if should_publish:
            ref["status"] = "online"
            ref["online_at"] = ref.get("online_at") or now
            ref["listing_posted"] = True
            ref["listing_posted_at"] = ref.get("listing_posted_at") or now
    return True


def resolve_drop_cards_from_data(drop, available_cards):
    by_key = {}
    by_uid = {}
    for card in available_cards or []:
        by_key[drop_card_key(make_card_ref(card))] = card
        uid = str(card.get("card_uid") or "").strip()
        lot_uid = str(card.get("lot_uid") or "").strip()
        if uid:
            by_uid[(lot_uid, uid)] = card
            by_uid[("", uid)] = card

    resolved = []
    missing = []
    for ref in drop.get("cards", []):
        key = drop_card_key(ref)
        ref_uid = str(ref.get("card_uid") or "").strip()
        ref_lot_uid = str(ref.get("lot_uid") or "").strip()
        card = by_uid.get((ref_lot_uid, ref_uid)) or by_uid.get(("", ref_uid)) or by_key.get(key)
        if card:
            enriched = dict(card)
            enriched.update(resolve_drop_item_card_identity(ref, card))
            enriched["_drop_ref_key"] = drop_ref_key(ref)
            enriched["listing_posted"] = bool(ref.get("listing_posted", False))
            enriched["listing_posted_at"] = ref.get("listing_posted_at", "")
            enriched["drop_item_id"] = ref.get("drop_item_id", "")
            enriched["status"] = drop_item_status(ref)
            enriched["status_label"] = drop_item_status_label(ref)
            enriched["draft_ready_at"] = ref.get("draft_ready_at", "")
            enriched["online_at"] = ref.get("online_at", "")
            enriched["sold_at"] = ref.get("sold_at", "")
            enriched["photo_order"] = ref.get("photo_order", "")
            enriched["drop_quantity"] = max(1, int(ref.get("quantity", 1) or 1))
            enriched["price_at_add"] = ref.get("price_at_add", card.get("suggested_price", 0))
            enriched["identity_fingerprint"] = card_identity_fingerprint(enriched)
            enriched["_drop_available"] = True
            resolved.append(enriched)
        else:
            ref = dict(ref)
            ref.setdefault("quantity", 1)
            ref["status"] = drop_item_status(ref)
            ref["status_label"] = drop_item_status_label(ref)
            ref["identity_fingerprint"] = ref.get("identity_fingerprint") or card_identity_fingerprint(ref)
            ref["_drop_ref_key"] = drop_ref_key(ref)
            ref["_drop_available"] = False
            missing.append(ref)
    return resolved, missing


def filter_drop_cards(cards, query):
    q = normalize_search_text(query)
    if not q:
        return list(cards or [])
    terms = [term for term in q.split() if term]
    results = []
    for card in cards or []:
        blob = normalize_search_text(
            " ".join(
                [
                    card_search_blob(card),
                    full_card_number(card),
                    str(card.get("lot_name", "")),
                ]
            )
        )
        if all(term in blob for term in terms):
            results.append(card)
    return results


def _drop_sort_key(drop):
    return str(drop.get("drop_launched_at") or drop.get("created_at") or "")


def link_sale_entry_to_drop(data, sale_entry, canal):
    if not is_vinted_channel(canal):
        return False
    channel = normalize_vinted_channel(canal)
    drops = [
        drop for drop in data.get("drops", []) or []
        if normalize_vinted_channel(drop.get("channel", "")) == channel
    ]
    if not drops:
        return False

    card_uid = str((sale_entry or {}).get("card_uid") or "").strip()
    lot_uid = str((sale_entry or {}).get("lot_uid") or "").strip()
    chosen_drop = None
    chosen_ref = None
    if card_uid:
        matches = []
        for drop in drops:
            for ref in drop.get("cards", []) or []:
                if str(ref.get("card_uid") or "").strip() != card_uid:
                    continue
                if lot_uid and str(ref.get("lot_uid") or "").strip() not in ("", lot_uid):
                    continue
                matches.append((drop, ref))
        if matches:
            launched = [item for item in matches if item[0].get("drop_launched_at")]
            pool = launched or matches
            # A card line can have several refs (one per added copy): link the
            # sale to a ref that is not sold yet, online ones first.
            def _sale_link_rank(item):
                status = drop_item_status(item[1])
                return (status == "sold", status != "online")
            chosen_drop, chosen_ref = sorted(
                sorted(pool, key=lambda item: _drop_sort_key(item[0]), reverse=True),
                key=_sale_link_rank,
            )[0]

    method = "card_match"
    if chosen_drop is None:
        launched = [drop for drop in drops if drop.get("drop_launched_at") and not drop_is_archived(drop)]
        if not launched:
            return False
        chosen_drop = sorted(launched, key=_drop_sort_key, reverse=True)[0]
        method = "channel_latest"

    sale_entry["drop_id"] = chosen_drop.get("id", "")
    sale_entry["drop_name"] = chosen_drop.get("name", "")
    sale_entry["drop_channel"] = channel
    sale_entry["drop_link_method"] = method
    if chosen_ref is not None:
        chosen_ref.setdefault("drop_item_id", uuid.uuid4().hex)
        sale_entry["drop_item_id"] = chosen_ref.get("drop_item_id", "")
        chosen_ref["status"] = "sold"
        chosen_ref["sold_at"] = chosen_ref.get("sold_at") or sale_entry.get("date") or _now_iso()
    return True


def link_sale_to_vinted_drop_if_applicable(sale_entry, canal):
    if not is_vinted_channel(canal):
        return False
    data = load_vinted_drops()
    if not link_sale_entry_to_drop(data, sale_entry, canal):
        return False
    save_vinted_drops(data)
    return True

from __future__ import annotations

import json
import os
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


def find_drop(data, drop_id):
    for drop in data.get("drops", []):
        if drop.get("id") == drop_id:
            return drop
    return None


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
    existing = {drop_card_key(card) for card in drop["cards"]}
    added = 0
    duplicates = 0
    for card in cards or []:
        ref = make_card_ref(card)
        key = drop_card_key(ref)
        if key in existing:
            duplicates += 1
            continue
        drop["cards"].append(ref)
        existing.add(key)
        added += 1
    return added, duplicates


def card_is_in_drop(drop, card):
    key = drop_card_key(make_card_ref(card))
    return any(drop_card_key(ref) == key for ref in drop.get("cards", []))


def add_card_to_drop(data, drop_id, card):
    added, duplicates = add_cards_to_drop(data, drop_id, [card])
    return added == 1, duplicates == 1


def remove_card_from_drop(data, drop_id, card_key):
    drop = find_drop(data, drop_id)
    if not drop:
        return False
    before = len(drop.get("cards", []))
    drop["cards"] = [card for card in drop.get("cards", []) if drop_card_key(card) != card_key]
    return len(drop["cards"]) != before


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
    for ref in drop.get("cards", []):
        if drop_card_key(ref) != card_key:
            continue
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
    return False


def toggle_drop_card_posted(data, drop_id, card_key, posted=None):
    drop = find_drop(data, drop_id)
    if not drop:
        return False
    for ref in drop.get("cards", []):
        if drop_card_key(ref) != card_key:
            continue
        new_value = (not bool(ref.get("listing_posted"))) if posted is None else bool(posted)
        ref["listing_posted"] = new_value
        ref["listing_posted_at"] = _now_iso() if new_value else ""
        if new_value:
            ref["status"] = "online"
            ref["online_at"] = ref.get("online_at") or ref["listing_posted_at"]
        return True
    return False


def launch_drop(data, drop_id):
    drop = find_drop(data, drop_id)
    if not drop:
        return False
    now = _now_iso()
    if not drop.get("drop_launched_at"):
        drop["drop_launched_at"] = now
    for ref in drop.get("cards", []):
        if drop_item_status(ref) == "draft_ready":
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
            enriched["_drop_ref_key"] = key
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
            # The source card remains authoritative for visible identity fields.
            enriched["identity_fingerprint"] = card_identity_fingerprint(enriched)
            enriched["_drop_available"] = True
            if ref.get("display_number"):
                enriched["display_number"] = ref.get("display_number")
            resolved.append(enriched)
        else:
            ref = dict(ref)
            ref.setdefault("quantity", 1)
            ref["status"] = drop_item_status(ref)
            ref["status_label"] = drop_item_status_label(ref)
            ref["identity_fingerprint"] = ref.get("identity_fingerprint") or card_identity_fingerprint(ref)
            ref["_drop_ref_key"] = key
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
            chosen_drop, chosen_ref = sorted(pool, key=lambda item: _drop_sort_key(item[0]), reverse=True)[0]

    method = "card_match"
    if chosen_drop is None:
        launched = [drop for drop in drops if drop.get("drop_launched_at")]
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

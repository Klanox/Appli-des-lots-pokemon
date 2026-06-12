from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from utils import safe_write_json
from services.vinted_listing_service import card_search_blob, full_card_number, normalize_search_text


VINTED_DROPS_FILE = "vinted_drops.json"


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
    safe_write_json(path, data, indent=2)


def create_drop(data, name):
    name = str(name or "").strip()
    if not name:
        name = f"Drop Vinted {datetime.now().strftime('%d/%m/%Y')}"
    drop = {
        "id": uuid.uuid4().hex,
        "name": name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
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
        "added_at": datetime.now().isoformat(timespec="seconds"),
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


def toggle_drop_card_posted(data, drop_id, card_key, posted=None):
    drop = find_drop(data, drop_id)
    if not drop:
        return False
    for ref in drop.get("cards", []):
        if drop_card_key(ref) != card_key:
            continue
        new_value = (not bool(ref.get("listing_posted"))) if posted is None else bool(posted)
        ref["listing_posted"] = new_value
        ref["listing_posted_at"] = datetime.now().isoformat(timespec="seconds") if new_value else ""
        return True
    return False


def resolve_drop_cards_from_data(drop, available_cards):
    by_key = {}
    for card in available_cards or []:
        by_key[drop_card_key(make_card_ref(card))] = card

    resolved = []
    missing = []
    for ref in drop.get("cards", []):
        key = drop_card_key(ref)
        card = by_key.get(key)
        if card:
            enriched = dict(card)
            enriched["_drop_ref_key"] = key
            enriched["listing_posted"] = bool(ref.get("listing_posted", False))
            enriched["listing_posted_at"] = ref.get("listing_posted_at", "")
            if ref.get("display_number"):
                enriched["display_number"] = ref.get("display_number")
            resolved.append(enriched)
        else:
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

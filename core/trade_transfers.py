"""Pure helpers for moving received trade cards between system lots."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from core.trade_economics import allocate_amount, rounded, safe_float, safe_int, trade_card_unit_cost


def _is_trade_lot(lot):
    return bool(lot.get("is_trade") or lot.get("nom") in ("Trade", "🔄 Trade"))


def _is_storage_lot(lot):
    return bool(lot.get("is_storage") or lot.get("nom") in ("Stockage", "📈 Stockage"))


def _is_collection_lot(lot):
    return bool(lot.get("is_collection_lot") or lot.get("nom") in ("Collection", "🧾 Collection"))


def _card_available_qty(card):
    return max(
        safe_int(card.get("quantity"), 0)
        - safe_int(card.get("sold_quantity"), 0)
        - safe_int(card.get("exchange_out_quantity"), 0)
        - safe_int(card.get("stored_quantity"), 0),
        0,
    )


def _find_destination_lot(data, destination):
    wanted = str(destination or "").strip().lower()
    for index, lot in enumerate(data.get("lots", []) or []):
        if wanted == "collection" and _is_collection_lot(lot):
            return index
        if wanted == "stockage" and _is_storage_lot(lot):
            return index
    return None


def _scaled_mapping(mapping, total_amount):
    if not isinstance(mapping, dict) or not mapping:
        return mapping
    keys = list(mapping.keys())
    weights = [max(safe_float(mapping.get(key)), 0.0) for key in keys]
    parts = allocate_amount(total_amount, weights)
    return {key: part for key, part in zip(keys, parts)}


def _scaled_contributors(contributors, total_amount):
    if not isinstance(contributors, list) or not contributors:
        return contributors
    weights = [
        max(safe_float(item.get("remaining_cost"), safe_float(item.get("historical_cost_contributed"))), 0.0)
        for item in contributors
    ]
    parts = allocate_amount(total_amount, weights)
    ratio_total = sum(parts)
    scaled = []
    for item, part in zip(contributors, parts):
        copied = dict(item)
        if "remaining_cost" in copied:
            copied["remaining_cost"] = part
        if "historical_cost_contributed" in copied:
            copied["historical_cost_contributed"] = part
        if ratio_total > 0:
            copied["ratio"] = safe_float(part) / ratio_total
        scaled.append(copied)
    return scaled


def _apply_moved_quantity(card, quantity, unit_cost):
    card["quantity"] = int(quantity)
    card["sold_quantity"] = 0
    card["sold_entries"] = []
    card["exchange_out_quantity"] = 0
    card["exchange_out_entries"] = []
    card["stored_quantity"] = 0
    card["storage_entries"] = []

    if unit_cost > 0:
        total_cost = rounded(unit_cost * quantity)
        card["trade_acquisition_unit_cost"] = rounded(unit_cost)
        for field in (
            "trade_acquisition_total_cost",
            "trade_acquisition_cost",
            "trade_historical_total_cost",
            "historical_total_cost",
        ):
            if field in card:
                card[field] = total_cost
        if isinstance(card.get("exchange_repartition"), dict):
            card["exchange_repartition"] = _scaled_mapping(card["exchange_repartition"], total_cost)
        if isinstance(card.get("trade_contributors"), list):
            card["trade_contributors"] = _scaled_contributors(card["trade_contributors"], total_cost)


def _apply_source_remaining(card, new_quantity, unit_cost):
    card["quantity"] = int(new_quantity)
    if unit_cost <= 0:
        return
    total_cost = rounded(unit_cost * new_quantity)
    card["trade_acquisition_unit_cost"] = rounded(unit_cost)
    for field in (
        "trade_acquisition_total_cost",
        "trade_acquisition_cost",
        "trade_historical_total_cost",
        "historical_total_cost",
    ):
        if field in card:
            card[field] = total_cost
    if isinstance(card.get("exchange_repartition"), dict):
        card["exchange_repartition"] = _scaled_mapping(card["exchange_repartition"], total_cost)
    if isinstance(card.get("trade_contributors"), list):
        card["trade_contributors"] = _scaled_contributors(card["trade_contributors"], total_cost)


def transfer_trade_card(data, trade_lot_idx, card_idx, destination, quantity, new_uid_func):
    """Move available units from the Trade lot to Collection or Stockage.

    This is an internal storage transfer: no sale, exchange-out entry or revenue
    is created.  The caller owns persistence.
    """
    lots = data.get("lots", []) or []
    if trade_lot_idx < 0 or trade_lot_idx >= len(lots):
        return False, "Lot Trade introuvable.", None
    source_lot = lots[trade_lot_idx]
    if not _is_trade_lot(source_lot):
        return False, "Cette action est réservée au lot Trade.", None
    cards = source_lot.get("cards", []) or []
    if card_idx < 0 or card_idx >= len(cards):
        return False, "Carte introuvable dans Trade.", None

    destination_key = str(destination or "").strip().lower()
    if destination_key not in ("collection", "stockage"):
        return False, "Destination inconnue.", None
    dest_idx = _find_destination_lot(data, destination_key)
    if dest_idx is None:
        return False, f"Lot {destination_key.title()} introuvable.", None

    source_card = cards[card_idx]
    available = _card_available_qty(source_card)
    move_qty = min(max(safe_int(quantity, 1), 1), available)
    if move_qty <= 0:
        return False, "Aucune quantité disponible à déplacer.", None

    original_uid = source_card.get("card_uid")
    unit_cost = trade_card_unit_cost(source_card)
    moved_card = deepcopy(source_card)
    full_available_move = move_qty == available
    used_qty = max(safe_int(source_card.get("quantity"), 0) - available, 0)

    if not full_available_move or used_qty > 0:
        moved_card["card_uid"] = new_uid_func("card")
        if original_uid:
            moved_card["split_from_card_uid"] = original_uid
    _apply_moved_quantity(moved_card, move_qty, unit_cost)

    moved_card["received_by_exchange"] = True
    moved_card["moved_from_trade"] = True
    moved_card["trade_transfer_destination"] = destination_key
    moved_card["trade_transfer_date"] = datetime.now().isoformat()
    moved_card["trade_source_lot_uid"] = source_lot.get("lot_uid")
    if original_uid:
        moved_card["trade_source_card_uid"] = original_uid

    if destination_key == "collection":
        moved_card["is_collection_keep"] = True
        moved_card["is_collection"] = True
        moved_card["collection_source"] = "trade_transfer"
        moved_card["collection_current_value"] = safe_float(moved_card.get("suggested_price"), 0.0)
        moved_card.setdefault("collection_purchase_price", rounded(unit_cost))
        moved_card.setdefault("collection_purchase_total", rounded(unit_cost * move_qty))
    else:
        moved_card["is_collection_keep"] = False
        moved_card["is_collection"] = False

    remaining_available = available - move_qty
    if remaining_available > 0:
        new_source_quantity = used_qty + remaining_available
        _apply_source_remaining(source_card, new_source_quantity, unit_cost)
    elif used_qty > 0:
        _apply_source_remaining(source_card, used_qty, unit_cost)
    else:
        del cards[card_idx]

    lots[dest_idx].setdefault("cards", []).append(moved_card)
    return True, f"Carte déplacée vers {destination_key.title()}.", {
        "destination_lot_idx": dest_idx,
        "moved_card": moved_card,
        "remaining_trade_quantity": remaining_available,
    }

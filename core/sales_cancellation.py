"""Helpers to cancel recorded sales without guessing by date/name/price."""

from __future__ import annotations

from copy import deepcopy


def _sale_id(value) -> str:
    return str(value or "").strip()


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _drop_status_after_cancel(drop: dict, ref: dict) -> str:
    if drop.get("drop_launched_at"):
        return "online"
    if ref.get("draft_ready_at"):
        return "draft_ready"
    return "to_prepare"


def _restore_drop_items_for_sales(sales):
    changed = False
    try:
        from services.vinted_drops_service import load_vinted_drops, save_vinted_drops
    except Exception:
        return False

    drop_item_ids = {
        _sale_id(sale.get("drop_item_id"))
        for sale in sales or []
        if _sale_id(sale.get("drop_item_id"))
    }
    if not drop_item_ids:
        return False

    drops_data = load_vinted_drops()
    for drop in drops_data.get("drops", []) or []:
        for ref in drop.get("cards", []) or []:
            if _sale_id(ref.get("drop_item_id")) not in drop_item_ids:
                continue
            if ref.get("status") == "sold" or ref.get("sold_at"):
                ref["status"] = _drop_status_after_cancel(drop, ref)
                ref["sold_at"] = ""
                changed = True
    if changed:
        save_vinted_drops(drops_data)
    return changed


def _remove_exchange_allocations(cd: dict, sale_ids: set[str]) -> int:
    removed = 0
    for lot in cd.get("lots", []) or []:
        kept = []
        for sale in lot.get("ventes", []) or []:
            if sale.get("is_exchange_allocation") and _sale_id(sale.get("source_sale_id")) in sale_ids:
                removed += 1
                continue
            kept.append(sale)
        if removed and len(kept) != len(lot.get("ventes", []) or []):
            lot["ventes"] = kept
    return removed


def _remove_brocante_transactions(sale_ids: set[str]) -> int:
    try:
        from services.brocante_data import load_brocantes, save_brocantes
    except Exception:
        return 0

    data = load_brocantes()
    removed = 0
    for session in data.get("sessions", []) or []:
        kept = []
        for tx in session.get("transactions", []) or []:
            if _sale_id(tx.get("transaction_id")) in sale_ids:
                removed += 1
                continue
            kept.append(tx)
        if len(kept) != len(session.get("transactions", []) or []):
            session["transactions"] = kept
    if removed:
        save_brocantes(data)
    return removed


def _find_sale_transaction_id(cd: dict, sale_id: str) -> str:
    for lot in cd.get("lots", []) or []:
        for card in lot.get("cards", []) or []:
            for sale in card.get("sold_entries", []) or []:
                if _sale_id(sale.get("sale_id")) == sale_id:
                    return _sale_id(sale.get("sale_transaction_id"))
        for sale in lot.get("ventes", []) or []:
            if sale.get("is_off_stock") and _sale_id(sale.get("sale_id")) == sale_id:
                return _sale_id(sale.get("sale_transaction_id"))
    for sale in cd.get("ventes_hors_stock", []) or []:
        if _sale_id(sale.get("sale_id")) == sale_id:
            return _sale_id(sale.get("sale_transaction_id"))
    return ""


def _find_card_sale_group(cd: dict, sale_id: str, transaction_id: str = ""):
    target = None
    for lot_idx, lot in enumerate(cd.get("lots", []) or []):
        for card_idx, card in enumerate(lot.get("cards", []) or []):
            for sale in card.get("sold_entries", []) or []:
                if _sale_id(sale.get("sale_id")) == sale_id:
                    target = (lot_idx, card_idx, sale)
                    break
            if target:
                break
        if target:
            break
    if not target and not transaction_id:
        return []

    tx_id = transaction_id or _sale_id(target[2].get("sale_transaction_id"))
    matches = []
    for lot_idx, lot in enumerate(cd.get("lots", []) or []):
        for card_idx, card in enumerate(lot.get("cards", []) or []):
            for sale in card.get("sold_entries", []) or []:
                same_tx = tx_id and _sale_id(sale.get("sale_transaction_id")) == tx_id
                same_sale = _sale_id(sale.get("sale_id")) == sale_id
                if same_tx or same_sale:
                    matches.append((lot_idx, card_idx, card, sale))
    return matches


def _remove_card_sales(cd: dict, sale_id: str, transaction_id: str = ""):
    matches = _find_card_sale_group(cd, sale_id, transaction_id)
    if not matches:
        return None

    removed_sales = []
    removed_sale_ids = set()
    for _lot_idx, _card_idx, card, sale in matches:
        removed_sales.append(deepcopy(sale))
        removed_sale_ids.add(_sale_id(sale.get("sale_id")))
        quantity = max(0, _safe_int(sale.get("quantity"), 0))
        card["sold_entries"] = [
            entry for entry in card.get("sold_entries", []) or []
            if _sale_id(entry.get("sale_id")) != _sale_id(sale.get("sale_id"))
        ]
        card["sold_quantity"] = max(0, _safe_int(card.get("sold_quantity"), 0) - quantity)

    allocation_count = _remove_exchange_allocations(cd, removed_sale_ids)
    return {
        "kind": "card",
        "sales_removed": len(removed_sales),
        "allocation_removed": allocation_count,
        "sales": removed_sales,
    }


def _remove_off_stock_sale(cd: dict, sale_id: str, transaction_id: str = ""):
    def matches(sale):
        same_sale = _sale_id(sale.get("sale_id")) == sale_id
        same_transaction = transaction_id and _sale_id(sale.get("sale_transaction_id")) == transaction_id
        return same_sale or same_transaction

    removed_sales = []
    for lot in cd.get("lots", []) or []:
        kept = []
        for sale in lot.get("ventes", []) or []:
            if sale.get("is_off_stock") and matches(sale):
                removed_sales.append(deepcopy(sale))
                continue
            kept.append(sale)
        if len(kept) != len(lot.get("ventes", []) or []):
            lot["ventes"] = kept

    kept_root = []
    for sale in cd.get("ventes_hors_stock", []) or []:
        if matches(sale):
            removed_sales.append(deepcopy(sale))
            continue
        kept_root.append(sale)
    if len(kept_root) != len(cd.get("ventes_hors_stock", []) or []):
        cd["ventes_hors_stock"] = kept_root

    if not removed_sales:
        return None
    return {
        "kind": "off_stock",
        "sales_removed": len(removed_sales),
        "allocation_removed": 0,
        "sales": removed_sales,
    }


def cancel_sale_by_id(cd: dict, sale_id: str):
    """Mutate cd to cancel a reliable sale id. Returns (ok, message, details)."""
    sale_id = _sale_id(sale_id)
    if not sale_id:
        return False, "Identifiant de vente manquant.", {}

    transaction_id = _find_sale_transaction_id(cd, sale_id)
    card_details = _remove_card_sales(cd, sale_id, transaction_id)
    off_stock_details = _remove_off_stock_sale(cd, sale_id, transaction_id)
    if card_details or off_stock_details:
        removed_sales = [
            *((card_details or {}).get("sales", []) or []),
            *((off_stock_details or {}).get("sales", []) or []),
        ]
        _restore_drop_items_for_sales(removed_sales)
        identifiers = {_sale_id(sale.get("sale_id")) for sale in removed_sales}
        if transaction_id:
            identifiers.add(transaction_id)
        brocante_removed = _remove_brocante_transactions(identifiers)
        details = {
            "kind": "transaction" if transaction_id else (card_details or off_stock_details).get("kind"),
            "transaction_id": transaction_id,
            "sales_removed": len(removed_sales),
            "card_sales_removed": (card_details or {}).get("sales_removed", 0),
            "off_stock_sales_removed": (off_stock_details or {}).get("sales_removed", 0),
            "allocation_removed": (card_details or {}).get("allocation_removed", 0),
            "brocante_transactions_removed": brocante_removed,
            "sales": removed_sales,
        }
        return True, "Transaction annulée." if transaction_id else "Vente annulée.", details

    return False, "Vente introuvable ou déjà annulée.", {}

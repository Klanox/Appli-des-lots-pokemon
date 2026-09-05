"""Read-only economic previews using the existing history cost calculators."""

from copy import deepcopy
from math import isfinite

from core.trade_economics import card_historical_unit_cost, trade_card_unit_cost, trade_sale_stat_rows
from core.sales_actions import _source_lot_index


def _amount_known(record, fields):
    for field in fields:
        value = record.get(field)
        if value not in (None, ""):
            try:
                return isfinite(float(value)) and float(value) >= 0
            except (TypeError, ValueError):
                return False
    return False


def historical_unit_cost_or_none(lot, card):
    """Keep missing costs distinct from a documented zero-cost acquisition."""
    trade_fields = (
        "trade_acquisition_unit_cost", "trade_historical_unit_cost", "historical_unit_cost",
        "acquisition_unit_cost", "trade_acquisition_total_cost", "trade_historical_total_cost",
        "historical_total_cost", "collection_purchase_total",
    )
    if _amount_known(card, trade_fields) or card.get("exchange_repartition"):
        return trade_card_unit_cost(card)
    if _amount_known(card, ("purchase_price", "collection_purchase_price")):
        return card_historical_unit_cost(lot, card)
    if card.get("received_by_exchange"):
        return None
    fields = ("prix_achat_reel", "prix_achat") if lot.get("is_mixte") else ("prix_achat",)
    if _amount_known(lot, fields) and float(card.get("suggested_price", 0) or 0) > 0:
        return card_historical_unit_cost(lot, card)
    return None


def off_stock_history_cost(sale, lot=None, valeur_est_hist=None, effective_purchase_price_func=None):
    if sale.get("cost_basis_known"):
        try:
            return float(sale.get("cost_basis", 0) or 0)
        except (TypeError, ValueError):
            return None
    if not lot or not callable(effective_purchase_price_func):
        return None
    try:
        price = float(sale.get("price", 0) or 0)
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        return 0.0
    try:
        if lot.get("is_mixte") and float(lot.get("valeur_totale", 0) or 0) > 0:
            return (price / float(lot.get("valeur_totale", 1) or 1)) * float(lot.get("prix_achat_reel", lot.get("prix_achat", 0)) or 0)
        return (price / (float(valeur_est_hist or 0) or 1.0)) * effective_purchase_price_func(lot)
    except Exception:
        return None


def preview_sale(data, items, *, resolve_card, calc_cost, effective_purchase_price):
    """Stage only affected lots; never call persistence or Drop-linking actions.

    Lot-linked off-stock revenue must be present before calculating any cost:
    it contributes to the same denominator used by the final history.
    """
    lots = {}
    staged = []
    for item in items:
        quantity = max(int(item.get("quantity", 1) or 1), 1)
        price = quantity * max(float(item.get("unit_price", item.get("price_base", 0)) or 0), 0)
        sale = {"price": price, "quantity": quantity}
        off_stock = bool(item.get("is_off_stock") or item.get("line_type") == "off_stock")
        if off_stock:
            li = _source_lot_index(data, item)
            sale.update(cost_basis_known=bool(item.get("cost_basis_known") and item.get("cost_basis") not in (None, "")),
                        cost_basis=max(float(item.get("cost_basis") or 0), 0), is_off_stock=True)
            card = None
        else:
            li, ci, _lot, original = resolve_card(data, dict(item))
            if original is None:
                staged.append((None, None, sale, False))
                continue
        if li is not None:
            if li not in lots:
                lots[li] = deepcopy(data["lots"][li])
            lot = lots[li]
            if off_stock:
                lot.setdefault("ventes", []).append(sale)
            else:
                card = lot["cards"][ci]
                sale["suggested_price_at_sale"] = float(card.get("suggested_price", price / quantity))
                card.setdefault("sold_entries", []).append(sale)
                card["sold_quantity"] = int(card.get("sold_quantity", 0)) + quantity
        staged.append((li, card, sale, off_stock))

    calculated = {li: calc_cost(lot) for li, lot in lots.items()}
    costs = {id(sale): cost for rows, _ in calculated.values() for _, sale, cost in rows}
    profits = []
    for li, card, sale, off_stock in staged:
        lot = lots.get(li)
        if off_stock:
            basis = calculated[li][1] if li in calculated else None
            cost = off_stock_history_cost(sale, lot, basis, effective_purchase_price)
            if not sale["cost_basis_known"] and lot and not _amount_known(
                lot, ("prix_achat_reel", "prix_achat") if lot.get("is_mixte") else ("prix_achat",)
            ):
                cost = None
            profits.append(None if cost is None else sale["price"] - cost)
        elif card is None or historical_unit_cost_or_none(lot, card) is None:
            profits.append(None)
        elif card.get("received_by_exchange") and (card.get("trade_contributors") or card.get("exchange_repartition")):
            profits.append(sum(row["benef"] for row in trade_sale_stat_rows(card, sale, lot.get("nom", "Trade"))))
        else:
            profits.append(sale["price"] - costs[id(sale)])
    missing = sum(value is None for value in profits)
    known_profit = sum(value for value in profits if value is not None)
    return {"total": sum(sale["price"] for _, _, sale, _ in staged),
            "profit": known_profit if not missing else None,
            "known_profit": known_profit, "unknown_lines": missing}

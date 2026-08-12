"""Pure helpers for trade economics.

The helpers in this module do not read or write Pokestock JSON files.  They
only transform data already loaded by the caller.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4


def safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def rounded(value):
    return round(safe_float(value), 2)


def allocate_amount(amount, weights):
    """Allocate amount proportionally and keep the rounded sum exact."""
    amount = rounded(amount)
    weights = [max(safe_float(weight), 0.0) for weight in weights]
    if not weights:
        return []
    total = sum(weights)
    if total <= 0:
        weights = [1.0 for _ in weights]
        total = float(len(weights))
    parts = []
    running = 0.0
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            part = rounded(amount - running)
        else:
            part = rounded(amount * weight / total)
            running = rounded(running + part)
        parts.append(part)
    return parts


def card_reference_value(card):
    return safe_float(card.get("suggested_price"), 0.0)


def _card_sold_reference(card):
    value = 0.0
    qty = 0
    for sale in card.get("sold_entries", []) or []:
        sale_qty = max(safe_int(sale.get("quantity"), 1), 1)
        ref = safe_float(
            sale.get("suggested_price_at_sale"),
            safe_float(card.get("suggested_price"), 0.0),
        )
        value += ref * sale_qty
        qty += sale_qty
    return value, qty


def lot_reference_value(lot):
    value = 0.0
    for card in lot.get("cards", []) or []:
        sold_value, sold_qty = _card_sold_reference(card)
        out_qty = safe_int(card.get("exchange_out_quantity"), 0)
        qty = max(safe_int(card.get("quantity"), 0) - sold_qty - out_qty, 0)
        value += sold_value + qty * card_reference_value(card)
    for sale in lot.get("ventes", []) or []:
        if not sale.get("is_exchange_benefit"):
            value += safe_float(sale.get("price"), 0.0)
    return value


def effective_lot_purchase_price(lot):
    if lot.get("is_mixte"):
        return safe_float(lot.get("prix_achat_reel"), safe_float(lot.get("prix_achat"), 0.0))
    return safe_float(lot.get("prix_achat"), 0.0)


def trade_card_unit_cost(card):
    qty = max(safe_int(card.get("quantity"), 1), 1)
    explicit_unit_fields = (
        "trade_acquisition_unit_cost",
        "trade_historical_unit_cost",
        "historical_unit_cost",
        "acquisition_unit_cost",
    )
    for field in explicit_unit_fields:
        value = card.get(field)
        if value not in (None, ""):
            return max(safe_float(value), 0.0)

    total_fields = (
        "trade_acquisition_total_cost",
        "trade_historical_total_cost",
        "historical_total_cost",
        "collection_purchase_total",
    )
    for field in total_fields:
        value = card.get(field)
        if value not in (None, ""):
            return max(safe_float(value), 0.0) / qty

    repartition = card.get("exchange_repartition") or {}
    if isinstance(repartition, dict) and repartition:
        return max(sum(safe_float(v) for v in repartition.values()), 0.0) / qty

    return 0.0


def card_historical_unit_cost(lot, card):
    """Find the real historical unit cost without falling back to cote."""
    trade_cost = trade_card_unit_cost(card)
    if trade_cost > 0:
        return trade_cost

    for field in ("purchase_price", "collection_purchase_price"):
        value = card.get(field)
        if value not in (None, ""):
            return max(safe_float(value), 0.0)

    ref = card_reference_value(card)
    if ref <= 0:
        return 0.0

    if lot.get("is_divers") and card.get("purchase_price") not in (None, ""):
        return max(safe_float(card.get("purchase_price")), 0.0)

    if lot.get("is_mixte") and safe_float(lot.get("valeur_totale"), 0.0) > 0:
        paid = safe_float(lot.get("prix_achat_reel"), safe_float(lot.get("prix_achat"), 0.0))
        return max(ref / safe_float(lot.get("valeur_totale"), 1.0) * paid, 0.0)

    lot_value = lot_reference_value(lot)
    if lot_value <= 0:
        return 0.0
    return max(ref / lot_value * effective_lot_purchase_price(lot), 0.0)


def _lot_contributor(lot_idx, lot, amount):
    return {
        "source_type": "lot",
        "lot_idx": int(lot_idx),
        "lot_uid": lot.get("lot_uid"),
        "lot_name": lot.get("nom", ""),
        "historical_cost_contributed": rounded(amount),
        "remaining_cost": rounded(amount),
        "ratio": 0.0,
    }


def contributors_from_card(lot_idx, lot, card, amount):
    """Return contributors for one given card unit, preserving Trade ancestry."""
    amount = max(safe_float(amount), 0.0)
    if amount <= 0:
        return []

    existing = card.get("trade_contributors") or []
    if isinstance(existing, list) and existing:
        base_total = sum(max(safe_float(c.get("remaining_cost")), 0.0) for c in existing)
        if base_total <= 0:
            base_total = sum(max(safe_float(c.get("historical_cost_contributed")), 0.0) for c in existing)
        if base_total > 0:
            parts = allocate_amount(amount, [max(safe_float(c.get("remaining_cost"), safe_float(c.get("historical_cost_contributed"))), 0.0) for c in existing])
            result = []
            for contributor, part in zip(existing, parts):
                if part <= 0:
                    continue
                copied = dict(contributor)
                copied["historical_cost_contributed"] = part
                copied["remaining_cost"] = part
                copied["ratio"] = 0.0
                result.append(copied)
            return result

    repartition = card.get("exchange_repartition") or {}
    if isinstance(repartition, dict) and repartition:
        weights = [max(safe_float(v), 0.0) for v in repartition.values()]
        parts = allocate_amount(amount, weights)
        result = []
        for key, part in zip(repartition.keys(), parts):
            if part <= 0:
                continue
            try:
                contrib_idx = int(key)
                contrib_lot = lot if contrib_idx == lot_idx else {}
            except (TypeError, ValueError):
                continue
            result.append(_lot_contributor(contrib_idx, contrib_lot, part))
        if result:
            return result

    return [_lot_contributor(lot_idx, lot, amount)]


def aggregate_contributors(given_records, cash_paid=0.0, cash_received=0.0):
    totals = {}
    for record in given_records:
        for contributor in record.get("contributors", []) or []:
            if contributor.get("source_type") == "lot":
                key = f"lot:{contributor.get('lot_idx')}"
            else:
                key = str(contributor.get("source_type") or "unknown")
            if key not in totals:
                totals[key] = dict(contributor)
            else:
                target = totals[key]
                target["historical_cost_contributed"] = rounded(
                    safe_float(target.get("historical_cost_contributed")) + safe_float(contributor.get("historical_cost_contributed"))
                )
                target["remaining_cost"] = rounded(
                    safe_float(target.get("remaining_cost")) + safe_float(contributor.get("remaining_cost"))
                )

    cash_paid = max(safe_float(cash_paid), 0.0)
    if cash_paid > 0:
        totals["cash:paid"] = {
            "source_type": "cash_paid",
            "lot_idx": None,
            "lot_uid": None,
            "lot_name": "Cash ajouté",
            "historical_cost_contributed": rounded(cash_paid),
            "remaining_cost": rounded(cash_paid),
            "ratio": 0.0,
        }

    contributors = list(totals.values())
    before_cash = sum(max(safe_float(c.get("remaining_cost")), 0.0) for c in contributors)
    remaining_total = max(0.0, before_cash - max(safe_float(cash_received), 0.0))
    remaining_parts = allocate_amount(remaining_total, [max(safe_float(c.get("remaining_cost")), 0.0) for c in contributors])
    for contributor, part in zip(contributors, remaining_parts):
        contributor["remaining_cost"] = part

    ratio_total = sum(max(safe_float(c.get("remaining_cost")), 0.0) for c in contributors)
    for contributor in contributors:
        contributor["ratio"] = safe_float(contributor.get("remaining_cost")) / ratio_total if ratio_total > 0 else 0.0
    return contributors, rounded(before_cash), rounded(remaining_total)


def allocate_received_cards(received_cards, total_cost, contributors):
    weights = [max(safe_float(card.get("value")), 0.0) for card in received_cards]
    card_costs = allocate_amount(total_cost, weights)
    contributor_weights = [max(safe_float(c.get("remaining_cost")), 0.0) for c in contributors]
    result = []
    for card, card_cost in zip(received_cards, card_costs):
        contrib_parts = allocate_amount(card_cost, contributor_weights)
        card_contributors = []
        exchange_repartition = {}
        for contributor, part in zip(contributors, contrib_parts):
            copied = dict(contributor)
            copied["remaining_cost"] = part
            copied["historical_cost_contributed"] = part
            copied["ratio"] = safe_float(contributor.get("ratio"), 0.0)
            if part > 0:
                card_contributors.append(copied)
                if copied.get("source_type") == "lot" and copied.get("lot_idx") is not None:
                    exchange_repartition[str(copied.get("lot_idx"))] = part
        enriched = dict(card)
        enriched["trade_acquisition_total_cost"] = card_cost
        enriched["trade_acquisition_unit_cost"] = card_cost
        enriched["trade_contributors"] = card_contributors
        enriched["exchange_repartition"] = exchange_repartition
        result.append(enriched)
    return result


def build_trade_id():
    return f"trade_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def compute_trade_summary(given_value, received_value, cash_paid=0.0, cash_received=0.0, given_historical_cost=0.0):
    given_value = safe_float(given_value)
    received_value = safe_float(received_value)
    cash_paid = max(safe_float(cash_paid), 0.0)
    cash_received = max(safe_float(cash_received), 0.0)
    historical_before = max(safe_float(given_historical_cost), 0.0) + cash_paid
    historical_remaining = max(0.0, historical_before - cash_received)
    economic_given = given_value + cash_paid
    economic_received = received_value + cash_received
    return {
        "trade_given_cards_value": rounded(given_value),
        "trade_received_cards_value": rounded(received_value),
        "trade_cash_paid": rounded(cash_paid),
        "trade_cash_received": rounded(cash_received),
        "trade_economic_given_total": rounded(economic_given),
        "trade_economic_received_total": rounded(economic_received),
        "trade_value_difference": rounded(economic_received - economic_given),
        "trade_given_historical_cost": rounded(given_historical_cost),
        "trade_historical_cost_before_cash": rounded(historical_before),
        "trade_acquisition_total_cost": rounded(historical_remaining),
        "trade_cost_method": "historical_cost_plus_cash_paid_minus_cash_received",
    }


def card_trade_sale_cost(card, quantity=1):
    quantity = max(safe_int(quantity, 1), 1)
    unit = trade_card_unit_cost(card)
    if unit > 0:
        return rounded(unit * quantity)
    return 0.0


def sale_allocation_for_trade_card(card, sale_price, quantity=1):
    sale_price = rounded(sale_price)
    cost = card_trade_sale_cost(card, quantity)
    profit = rounded(sale_price - cost)
    contributors = card.get("trade_contributors") or []
    if not contributors and isinstance(card.get("exchange_repartition"), dict):
        total = sum(safe_float(v) for v in card.get("exchange_repartition", {}).values())
        for lot_idx, value in card.get("exchange_repartition", {}).items():
            contributors.append({
                "source_type": "lot",
                "lot_idx": safe_int(lot_idx, None),
                "remaining_cost": safe_float(value),
                "ratio": safe_float(value) / total if total > 0 else 0.0,
            })
    weighted_contributors = [
        c for c in contributors
        if max(safe_float(c.get("remaining_cost")), 0.0) > 0
    ]
    weights = [max(safe_float(c.get("remaining_cost")), 0.0) for c in weighted_contributors]
    revenue_parts = allocate_amount(sale_price, weights)
    profit_parts = allocate_amount(profit, weights)
    allocations = []
    for contributor, revenue, profit_part in zip(weighted_contributors, revenue_parts, profit_parts):
        if contributor.get("source_type") != "lot" or contributor.get("lot_idx") is None:
            continue
        allocations.append({
            "lot_idx": safe_int(contributor.get("lot_idx")),
            "lot_uid": contributor.get("lot_uid"),
            "lot_name": contributor.get("lot_name", ""),
            "revenue": revenue,
            "profit": profit_part,
            "ratio": safe_float(contributor.get("ratio"), 0.0),
        })
    return {"cost": cost, "profit": profit, "allocations": allocations}


def trade_sale_stat_rows(card, sale, host_lot_name="Trade"):
    """Return stat rows for one sold Trade card without double-counting.

    When allocations exist, one row is returned per contributing lot. The host
    Trade row is omitted because the allocation rows already sum to the real
    sale revenue and profit. If no allocation is available, a single host row is
    returned as a safe fallback.
    """
    qty = max(safe_int(sale.get("quantity"), 1), 1)
    price = safe_float(sale.get("price"), 0.0)
    allocation = sale_allocation_for_trade_card(card, price, qty)
    rows = []
    for item in allocation.get("allocations", []):
        rows.append({
            "lot": item.get("lot_name") or f"Lot {item.get('lot_idx')}",
            "price": safe_float(item.get("revenue"), 0.0),
            "cost": safe_float(item.get("revenue"), 0.0) - safe_float(item.get("profit"), 0.0),
            "benef": safe_float(item.get("profit"), 0.0),
            "quantity": qty,
            "allocation": True,
            "lot_idx": item.get("lot_idx"),
            "ratio": safe_float(item.get("ratio"), 0.0),
        })
    if rows:
        return rows
    return [{
        "lot": host_lot_name,
        "price": price,
        "cost": allocation["cost"],
        "benef": allocation["profit"],
        "quantity": qty,
        "allocation": False,
        "lot_idx": None,
        "ratio": 1.0,
    }]


def normalize_number(value):
    return str(value or "").strip().lstrip("0") or str(value or "").strip()


def search_received_cards(query, cards_index, normalize_func, limit=12):
    """Search the existing local TCGDex cache for received trade cards."""
    query = str(query or "").strip()
    if len(query) < 2 or not isinstance(cards_index, dict):
        return []
    q_norm = normalize_func(query)
    q_num = normalize_number(query) if any(ch.isdigit() for ch in query) else ""
    matches = []
    seen = set()

    def add(card, set_name, set_id, score):
        key = card.get("id") or f"{card.get('name')}|{set_name}|{card.get('localId') or card.get('number')}"
        if key in seen:
            return
        seen.add(key)
        matches.append((score, card, set_name, set_id))

    for idx_name, rows in cards_index.items():
        idx_norm = normalize_func(idx_name)
        for row in rows:
            if len(row) == 3:
                card, set_name, set_id = row
            else:
                card, set_name = row[:2]
                set_id = ""
            number = normalize_number(card.get("localId") or card.get("number"))
            name_norm = normalize_func(card.get("name") or idx_name)
            blob = " ".join(
                normalize_func(part)
                for part in (
                    idx_name,
                    card.get("name", ""),
                    card.get("localId", ""),
                    card.get("number", ""),
                    set_name,
                    set_id,
                )
            )
            if q_num and number == q_num:
                add(card, set_name, set_id, 100)
            elif name_norm == q_norm or idx_norm == q_norm:
                add(card, set_name, set_id, 90)
            elif name_norm.startswith(q_norm) or idx_norm.startswith(q_norm):
                add(card, set_name, set_id, 75)
            elif q_norm in blob:
                add(card, set_name, set_id, 55)
    matches.sort(key=lambda item: (-item[0], str(item[1].get("name", "")), str(item[2])))
    return [(card, set_name, set_id) for _, card, set_name, set_id in matches[:limit]]

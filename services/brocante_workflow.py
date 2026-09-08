"""Event orchestration. Pure staging; existing sale and Trade engines own economics."""
from copy import deepcopy
from math import isfinite

from core.brocante import new_id, now_iso, record_exchange, record_transaction, session_by_id
from core.trade_economics import allocate_amount


def all_sales(stock):
    for lot in stock.get("lots", []):
        for card in lot.get("cards", []):
            yield from (s for s in card.get("sold_entries", []) if not s.get("is_exchange"))
        yield from (s for s in lot.get("ventes", []) if s.get("is_off_stock"))
    yield from stock.get("ventes_hors_stock", [])


def event_sales(stock, event_id):
    return [s for s in all_sales(stock) if s.get("brocante_id") == event_id]


def project_event(event, stock):
    """Recover newly recorded operations without writing or rewriting legacy metadata."""
    orders = {}
    for sale in event_sales(stock, event["id"]):
        order = sale.get("brocante_order")
        if order:
            orders[order["transaction_id"]] = order
    # Durable v2 orders disappear when the shared cancellation removes their sales.
    event["transactions"] = [t for t in event.get("transactions", [])
                             if not t.get("projected_from_sales") or t.get("transaction_id") in orders]
    for order in orders.values():
        record_transaction(event, {**order, "projected_from_sales": True})
    purchases = {p["purchase_id"]: p for p in event.get("purchases", [])}
    for lot in stock.get("lots", []):
        if lot.get("brocante_id") == event["id"] and lot.get("brocante_purchase_lot"):
            event["purchase_lot_uid"] = lot["lot_uid"]
            purchases.update({p["purchase_id"]: deepcopy(p) for p in lot.get("brocante_purchases", [])})
    event["purchases"] = list(purchases.values())
    for trade in stock.get("trade_history", []):
        if trade.get("brocante_id") == event["id"] and trade.get("brocante_context_version") == 2:
            record_exchange(event, {
                "exchange_id": trade["exchange_id"], "created_at": trade["date"],
                "given": trade.get("given_cards", []), "received": trade.get("received_cards", []),
                "cash_given": trade.get("trade_cash_paid", 0),
                "cash_received": trade.get("trade_cash_received", 0),
            })
    return event


def require_active(events, event_id):
    event = session_by_id(events, event_id)
    if not event or event.get("status") != "active":
        raise ValueError("Cette brocante n'est plus en cours.")
    return event


def money(value):
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError("Le montant doit être positif ou nul.")
    return round(value, 2)


def finalize_brocante_purchase_costs(lot, *, allocated_at=None):
    """Freeze pending Brocante purchase costs once every card price is known.

    Allocation is performed per purchase, so a later purchase never rewrites a
    cost basis already established for earlier cards in the same daily lot.
    """
    if not lot.get("brocante_purchase_lot"):
        return {"changed": False, "allocated": 0, "pending": 0}

    cards_by_uid = {
        str(card.get("card_uid")): card
        for card in lot.get("cards", [])
        if card.get("card_uid")
    }
    changed = False
    allocated = 0
    pending = 0
    allocation_time = allocated_at or now_iso()

    for purchase in lot.get("brocante_purchases", []):
        status = purchase.get("cost_allocation_status")
        if status == "allocated":
            allocated += 1
            continue

        references = list(purchase.get("cards", []))
        if status not in (None, "pending"):
            pending += 1
            continue

        purchase_cards = []
        for reference in references:
            card = cards_by_uid.get(str(reference.get("card_uid") or ""))
            if card is not None:
                purchase_cards.append((reference, card))
        # Purchases written by the previous workflow already own frozen costs.
        # Never reinterpret them from today's prices.
        if status is None and references and len(purchase_cards) == len(references) and all(
            reference.get("cost") is not None
            and card.get("purchase_price") is not None
            and not card.get("cost_basis_pending")
            for reference, card in purchase_cards
        ):
            allocated += 1
            continue
        amount = money(purchase.get("amount", 0))
        ready = bool(references) and len(purchase_cards) == len(references) and (
            amount == 0
            or all(float(card.get("suggested_price", 0) or 0) > 0 for _, card in purchase_cards)
        )
        if not ready:
            if status != "pending":
                purchase["cost_allocation_status"] = "pending"
                changed = True
            pending += 1
            continue

        weights = [
            max(float(card.get("suggested_price", 0) or 0), 0.0)
            * max(int(card.get("quantity", 1) or 1), 1)
            for _, card in purchase_cards
        ]
        allocations = allocate_amount(amount, weights)
        for (reference, card), card_cost in zip(purchase_cards, allocations):
            quantity = max(int(card.get("quantity", 1) or 1), 1)
            card["purchase_total"] = card_cost
            card["purchase_price"] = round(card_cost / quantity, 6)
            card["cost_basis_pending"] = False
            card["cost_basis_allocated_at"] = allocation_time
            reference["cost"] = card_cost
        purchase["cost_allocation_status"] = "allocated"
        purchase["cost_allocated_at"] = allocation_time
        allocated += 1
        changed = True

    lot_status = "pending" if pending else "allocated"
    if lot.get("brocante_cost_allocation_status") != lot_status:
        lot["brocante_cost_allocation_status"] = lot_status
        changed = True
    if lot.get("cost_basis_method") != "per_card":
        lot["cost_basis_method"] = "per_card"
        changed = True
    return {"changed": changed, "allocated": allocated, "pending": pending}


def stage_purchase(stock, events, event_id, lines, amount, payment, purchase_id):
    stock, events = deepcopy(stock), deepcopy(events)
    event = require_active(events, event_id)
    project_event(event, stock)
    if any(p["purchase_id"] == purchase_id for p in event.get("purchases", [])):
        return stock, events
    amount = money(amount)
    if not lines or not purchase_id:
        raise ValueError("Ajoute au moins une carte au rachat.")
    quantities = [int(line.get("quantity", 1)) for line in lines]
    if any(q < 1 for q in quantities):
        raise ValueError("Quantité invalide.")
    lots = stock.setdefault("lots", [])
    lot = next((l for l in lots if l.get("brocante_purchase_lot") and l.get("brocante_id") == event_id), None)
    if lot is None:
        from datetime import date
        day = date.fromisoformat(event["date"]).strftime("%d/%m/%Y")
        lot = {"lot_uid": new_id("lot"), "nom": f"Rachats · {event['name']} · {day}",
               "created": now_iso(), "date": event["date"], "prix_achat": 0.0,
               "cards": [], "ventes": [], "cost_basis_method": "per_card",
               "brocante_purchase_lot": True, "brocante_id": event_id, "brocante_purchases": []}
        lots.append(lot)
    cards = []
    for line, qty in zip(lines, quantities):
        source = line["card"]
        # Catalog identity and images only; never inherit another physical card's history.
        card = {k: deepcopy(source[k]) for k in (
            "id", "name", "set", "set_id", "number", "rarity", "lang", "language",
            "image_url", "image_url_en", "image_url_ja", "variant", "is_reverse", "is_ed1",
        ) if k in source}
        if not card.get("name"):
            raise ValueError("L'identité d'une carte est manquante.")
        card.update(card_uid=new_id("card"), quantity=qty, sold_quantity=0, sold_entries=[],
                    condition=source.get("condition", "NM"), suggested_price=0.0,
                    purchase_price=None, purchase_total=None, cost_basis_pending=True, added_at=now_iso(),
                    brocante_id=event_id, brocante_purchase_id=purchase_id, provenance="Brocante / rachat")
        lot["cards"].append(card)
        cards.append({"card_uid": card["card_uid"], "quantity": qty, "cost": None})
    purchase = {"purchase_id": purchase_id, "created_at": now_iso(), "amount": amount,
                "payment_method": payment, "cards": cards, "lot_uid": lot["lot_uid"],
                "cost_allocation_status": "pending"}
    lot["prix_achat"] = round(float(lot.get("prix_achat", 0)) + amount, 2)
    lot.setdefault("brocante_purchases", []).append(purchase)
    lot["brocante_cost_allocation_status"] = "pending"
    if amount == 0:
        finalize_brocante_purchase_costs(lot)
    project_event(event, stock)
    return stock, events


def tag_trade(stock, event_id, trade_id):
    for history in stock.get("trade_history", []):
        if history.get("exchange_id") == trade_id:
            history.update(brocante_id=event_id, canal="Brocante", brocante_context_version=2)
    for lot in stock.get("lots", []):
        for card in lot.get("cards", []):
            if card.get("exchange_id") == trade_id:
                card["brocante_id"] = event_id
            for entry in card.get("exchange_out_entries", []):
                if entry.get("exchange_id") == trade_id:
                    entry["brocante_id"] = event_id


def deletion_audit(stock, events, event_id, drops=None):
    event = deepcopy(session_by_id(events, event_id))
    if event is None:
        raise ValueError("Brocante introuvable.")
    project_event(event, stock)
    sales = event_sales(stock, event_id)
    linked = {str(s.get("sale_transaction_id") or s.get("sale_id")) for s in sales}
    blockers = []
    if event.get("exchanges"):
        blockers.append("Cette brocante contient un échange : aucune annulation Trade complète n'est disponible.")
    if any(t.get("brocante_id") == event_id for t in stock.get("trade_history", [])):
        blockers.append("Un échange de cette brocante est présent dans l'historique Trade.")
    if any(str(t.get("transaction_id")) not in linked for t in event.get("transactions", [])):
        blockers.append("Une vente historique n'a pas de lien fiable vers sa transaction. Audit nécessaire.")
    if any(not s.get("sale_id") or s.get("drop_item_id") or s.get("drop_id") for s in sales):
        blockers.append("Une vente est liée à un Drop ou n'a pas d'identifiant fiable.")
    transaction_ids = {s.get("sale_transaction_id") for s in sales if s.get("sale_transaction_id")}
    if any(s.get("sale_transaction_id") in transaction_ids and s.get("brocante_id") != event_id for s in all_sales(stock)):
        blockers.append("Une commande contient aussi des ventes extérieures à cette brocante.")
    purchase_lots = [(i, l) for i, l in enumerate(stock.get("lots", []))
                     if l.get("brocante_purchase_lot") and l.get("brocante_id") == event_id]
    expected = {c["card_uid"]: c for p in event.get("purchases", []) for c in p.get("cards", [])}
    actual = {c.get("card_uid"): c for _, l in purchase_lots for c in l.get("cards", [])}
    all_cards = [c for l in stock.get("lots", []) for c in l.get("cards", [])]
    if any(sum(c.get("card_uid") == uid for c in all_cards) != 1 for uid in actual):
        blockers.append("L'identité d'une carte rachetée est dupliquée dans le stock.")
    if expected.keys() != actual.keys():
        blockers.append("Des cartes rachetées ont été déplacées, retirées ou ajoutées au lot.")
    for uid, card in actual.items():
        used = any(card.get(k) for k in ("sold_quantity", "exchange_out_quantity", "stored_quantity",
                   "sold_entries", "exchange_out_entries", "storage_entries", "is_collection_keep", "transfers"))
        if used or card.get("quantity") != expected.get(uid, {}).get("quantity"):
            blockers.append(f"{card.get('name', uid)} : carte rachetée déjà utilisée ou quantité modifiée.")
    if any(c.get("card_uid") in actual for d in (drops or {}).get("drops", []) for c in d.get("cards", [])):
        blockers.append("Une carte rachetée est liée à un Drop.")
    if purchase_lots and purchase_lots[-1][0] != len(stock.get("lots", [])) - 1:
        blockers.append("Le lot de rachat est suivi d'autres lots : suppression bloquée pour protéger les références historiques par position.")
    if any(l.get("ventes") for _, l in purchase_lots):
        blockers.append("Le lot de rachat possède un historique de ventes.")
    return {"blockers": list(dict.fromkeys(blockers)), "sales": sales, "event": event,
            "purchase_lots": purchase_lots, "has_activity": any(event.get(k) for k in ("transactions", "exchanges", "purchases", "expenses"))}


def stage_delete(stock, events, event_id, drops=None):
    from core.sales_cancellation import cancel_sale_by_id
    audit = deletion_audit(stock, events, event_id, drops)
    if audit["blockers"]:
        raise ValueError(" ".join(audit["blockers"]))
    stock, events = deepcopy(stock), deepcopy(events)
    done = set()
    for sale in audit["sales"]:
        identity = sale.get("sale_transaction_id") or sale["sale_id"]
        if identity in done:
            continue
        ok, message, _ = cancel_sale_by_id(stock, sale["sale_id"], sync_related=False)
        if not ok:
            raise ValueError(message)
        done.add(identity)
    for index, _ in reversed(audit["purchase_lots"]):
        stock["lots"].pop(index)
    events["sessions"] = [s for s in events["sessions"] if s["id"] != event_id]
    return stock, events


def commit_staged(before_stock, before_events, after_stock, after_events, save_stock, save_events):
    """Compensate local write failures. No claim of atomicity across Cloud stores."""
    try:
        if before_stock != after_stock:
            save_stock(after_stock)
        save_events(after_events)
    except Exception:
        if before_stock != after_stock:
            save_stock(before_stock)
        save_events(before_events)
        raise

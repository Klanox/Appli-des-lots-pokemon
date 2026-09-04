"""Sales and cart actions for Pokestock.

Extracted conservatively from app.py. Dependencies are injected from app.py
to preserve formulas and sold_entries behavior.
"""

import time

from core.brocante import append_off_stock_sale, record_transaction
from core.trade_economics import sale_allocation_for_trade_card
from services.brocante_data import load_brocantes, save_brocantes
from services.vinted_drops_service import link_sale_to_vinted_drop_if_applicable


def configure_sales_actions(context):
    globals().update(context)


def _scu_in_data(cd, li, ci, q, p, canal="Main propre", transaction_id=None):
    """Vend une carte dans un data.json deja charge, sans sauvegarder tout de suite."""
    crd=cd["lots"][li]["cards"][ci]
    if card_available_qty(crd) < q:
        return False,"Stock insuffisant"
    crd.setdefault("card_uid", new_uid("card"))
    crd["sold_quantity"]=crd.get("sold_quantity",0)+q
    prix_total = p*q
    sale_id = f"{crd.get('card_uid')}_{int(time.time()*1000)}"
    transaction_id = transaction_id or sale_id
    sale_entry = {
        "sale_id": sale_id,
        "sale_transaction_id": transaction_id,
        "date":datetime.now().isoformat(),
        "quantity":q,
        "price":prix_total,
        "card_name":crd["name"],
        "card_set":crd["set"],
        "card_number":crd["number"],
        "card_uid": crd.get("card_uid"),
        "lot_uid": cd["lots"][li].get("lot_uid"),
        "suggested_price_at_sale": float(crd.get("suggested_price", p)),
        "canal": canal,
    }
    link_sale_to_vinted_drop_if_applicable(sale_entry, canal)
    crd.setdefault("sold_entries",[]).append(sale_entry)

    # ── Redistribution du bénéfice aux lots contributeurs ──
    # Si cette carte a été reçue par échange avec contribution de plusieurs lots,
    if crd.get("received_by_exchange") and (crd.get("trade_contributors") or crd.get("exchange_repartition")):
        allocation = sale_allocation_for_trade_card(crd, prix_total, q)
        crd["last_trade_sale_cost"] = allocation["cost"]
        crd["last_trade_sale_profit"] = allocation["profit"]
        crd["last_trade_sale_allocations"] = allocation["allocations"]
        for item in allocation["allocations"]:
            lot_idx_contrib = item.get("lot_idx")
            if lot_idx_contrib is None or lot_idx_contrib == li:
                continue
            if lot_idx_contrib >= len(cd.get("lots", [])):
                continue
            cd["lots"][lot_idx_contrib].setdefault("ventes", []).append({
                "date": datetime.now().isoformat(),
                "price": item["revenue"],
                "card_name": f"[Echange] Allocation CA {crd['name']}",
                "is_exchange_benefit": True,
                "is_exchange_allocation": True,
                "allocated_profit": item["profit"],
                "from_lot": cd["lots"][li]["nom"],
                "from_card": crd["name"],
                "source_sale_id": sale_id,
                "part_pct": round(float(item.get("ratio", 0.0)) * 100, 2),
            })

    return True,"Vendu!"

def scu(li,ci,q,p,canal="Main propre"):
    """Sell card units. Si la carte vient d'un échange, redistribue le bénéfice
    proportionnellement aux lots contributeurs via des ventes virtuelles."""
    cd=ld()
    ok, msg = _scu_in_data(cd, li, ci, q, p, canal)
    if not ok:
        return ok, msg
    sd(cd)
    return True,"Vendu!"

def _is_off_stock_item(item):
    return bool(item.get("is_off_stock") or item.get("line_type") == "off_stock")


def _source_lot_index(cd, item):
    source_lot_id = str(item.get("source_lot_id") or "").strip()
    if source_lot_id:
        for index, lot in enumerate(cd.get("lots", []) or []):
            if str(lot.get("lot_uid") or lot.get("id") or "").strip() == source_lot_id:
                return index
    try:
        index = int(item.get("source_lot_idx"))
    except (TypeError, ValueError):
        return None
    return index if 0 <= index < len(cd.get("lots", []) or []) else None


def _record_off_stock_brocante_order(sales, transaction_id):
    by_session = {}
    for sale in sales:
        brocante_id = str(sale.get("brocante_id") or "").strip()
        if brocante_id:
            by_session.setdefault(brocante_id, []).append(sale)
    if not by_session:
        return

    brocante_data = load_brocantes()
    changed = False
    for session in brocante_data.get("sessions", []) or []:
        grouped = by_session.get(str(session.get("id") or ""))
        if not grouped:
            continue
        amount = sum(float(sale.get("price", 0) or 0) for sale in grouped)
        quantity = sum(max(int(sale.get("quantity", 1) or 1), 1) for sale in grouped)
        labels = [str(sale.get("card_name") or "Vente hors stock") for sale in grouped]
        known_costs = [sale.get("cost_basis") for sale in grouped if sale.get("cost_basis_known")]
        all_costs_known = len(known_costs) == len(grouped)
        record_transaction(
            session,
            {
                "transaction_id": transaction_id,
                "type": "off_stock_sale",
                "label": " + ".join(labels),
                "items": labels,
                "quantity": quantity,
                "amount": amount,
                "payment_method": "Non renseigné",
                "inventory_impact": "none",
                "cost_basis_known": all_costs_known,
                "cost_basis": sum(float(value or 0) for value in known_costs) if all_costs_known else None,
            },
        )
        changed = True
    if changed:
        save_brocantes(brocante_data)


def scu_many(items, canal="Main propre"):
    """Persist one cart as one transaction, including optional off-stock rows."""
    items = list(items or [])
    if not items:
        return False, "Le panier est vide."
    cd = ld()
    transaction_id = new_uid("sale_tx")
    requested = {}
    for item in items:
        if _is_off_stock_item(item):
            if float(item.get("unit_price", item.get("price_base", 0)) or 0) < 0:
                return False, "Le montant hors stock ne peut pas être négatif."
            continue
        lot_idx, card_idx, lot, crd = resolve_card_ref(cd, item)
        if crd is None:
            return False, f"Carte introuvable dans le panier: {item.get('card_name', 'carte inconnue')}"
        item["lot_idx"] = lot_idx
        item["card_idx"] = card_idx
        item["lot_uid"] = lot.get("lot_uid")
        item["card_uid"] = crd.get("card_uid")
        key = (lot_idx, card_idx)
        requested[key] = requested.get(key, 0) + item["quantity"]
    for (lot_idx, card_idx), qty in requested.items():
        crd = cd["lots"][lot_idx]["cards"][card_idx]
        if card_available_qty(crd) < qty:
            return False, f"Stock insuffisant pour {crd.get('name', 'cette carte')}"
    off_stock_sales = []
    for item in items:
        if _is_off_stock_item(item):
            quantity = max(int(item.get("quantity", 1) or 1), 1)
            unit_price = max(float(item.get("unit_price", item.get("price_base", 0)) or 0), 0.0)
            sale = append_off_stock_sale(
                cd,
                category=item.get("category") or "Autre",
                description=item.get("description") or item.get("card_name") or "",
                quantity=quantity,
                amount=unit_price * quantity,
                payment_method=item.get("payment_method") or "Non renseigné",
                canal=canal,
                source_lot_idx=_source_lot_index(cd, item),
                cost_basis=item.get("cost_basis") if item.get("cost_basis_known") else None,
                notes=item.get("notes") or "",
                brocante_id=item.get("brocante_id"),
                transaction_id=transaction_id,
            )
            off_stock_sales.append(sale)
            continue
        ok, msg = _scu_in_data(
            cd,
            item["lot_idx"],
            item["card_idx"],
            item["quantity"],
            item["unit_price"],
            canal,
            transaction_id=transaction_id,
        )
        if not ok:
            return False, msg
    sd(cd)
    _record_off_stock_brocante_order(off_stock_sales, transaction_id)
    return True, "Vendu!"


def bulk_cart_add_off_stock(item):
    """Add an untracked article to the cart without persisting a sale."""
    st.session_state.setdefault("bulk_cart", [])
    quantity = max(int(item.get("quantity", 1) or 1), 1)
    amount = max(float(item.get("amount", 0) or 0), 0.0)
    line = {
        **item,
        "line_type": "off_stock",
        "is_off_stock": True,
        "quantity": quantity,
        "price_base": amount / quantity,
        "card_name": str(item.get("description") or item.get("category") or "Article hors stock").strip(),
        "card_set": "Hors stock",
        "lot_name": str(item.get("source_lot_name") or "Non attribuée"),
    }
    st.session_state.bulk_cart.append(line)
    save_activity_state()

def bulk_cart_add(item):
    st.session_state.setdefault("bulk_cart", [])
    cd = ld()
    lot_idx, card_idx, lot, card = resolve_card_ref(cd, item)
    if card is None:
        return
    item.update({
        "lot_idx": lot_idx,
        "card_idx": card_idx,
        "lot_uid": lot.get("lot_uid"),
        "card_uid": card.get("card_uid"),
        "lot_name": lot.get("nom", item.get("lot_name", "")),
        "card_name": card.get("name", item.get("card_name", "")),
        "card_set": card.get("set", item.get("card_set", "")),
        "price_base": float(card.get("suggested_price", item.get("price_base", 0))),
    })
    stock = card_available_qty(card)
    item["quantity"] = min(max(int(item.get("quantity", 1)), 1), max(stock, 1))
    exists = any(
        it.get("card_uid") == item.get("card_uid")
        for it in st.session_state.bulk_cart
    )
    if not exists:
        st.session_state.bulk_cart.append(item)
        save_activity_state()

def bulk_cart_remove(lot_idx=None, card_idx=None, card_uid=None):
    st.session_state.bulk_cart = [
        it for it in st.session_state.get("bulk_cart", [])
        if not ((card_uid and it.get("card_uid") == card_uid) or (it.get("lot_idx") == lot_idx and it.get("card_idx") == card_idx))
    ]
    save_activity_state()

def bulk_cart_set_quantity(index):
    cd = ld()
    cart = st.session_state.get("bulk_cart", [])
    if 0 <= index < len(cart):
        if _is_off_stock_item(cart[index]):
            key = f"cart_qty_{index}"
            cart[index]["quantity"] = min(max(int(st.session_state.get(key, 1)), 1), 9999)
            save_activity_state()
            return
        lot_idx, card_idx, lot, card = resolve_card_ref(cd, cart[index])
        if card is None:
            cart.pop(index)
        else:
            stock = card_available_qty(card)
            key = f"cart_qty_{index}"
            cart[index]["quantity"] = min(max(int(st.session_state.get(key, 1)), 1), max(stock, 1))
    save_activity_state()

def bulk_cart_increment(index):
    cd = ld()
    cart = st.session_state.get("bulk_cart", [])
    if 0 <= index < len(cart):
        if _is_off_stock_item(cart[index]):
            cart[index]["quantity"] = min(int(cart[index].get("quantity", 1)) + 1, 9999)
            save_activity_state()
            return
        lot_idx, card_idx, lot, card = resolve_card_ref(cd, cart[index])
        if card is None:
            cart.pop(index)
        else:
            stock = card_available_qty(card)
            cart[index]["quantity"] = min(cart[index]["quantity"] + 1, stock)
    save_activity_state()

def bulk_cart_pop(index):
    cart = st.session_state.get("bulk_cart", [])
    if 0 <= index < len(cart):
        cart.pop(index)
    save_activity_state()

def bulk_cart_clear():
    st.session_state.bulk_cart = []
    save_activity_state()

def bulk_sale_prepare(sale_type, price=None):
    if sale_type == "negociated":
        price = st.session_state.get("negociated_price", price)
    try:
        price = round(max(float(price or 0.0), 0.0), 2)
    except (TypeError, ValueError):
        price = 0.0
    st.session_state["pending_bulk_sale"] = {"type": sale_type, "price": price}
    st.session_state["show_canal_dialog_bulk"] = True

def scroll_to_cart_prepare():
    st.session_state["scroll_to_cart"] = True


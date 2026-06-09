"""Sales and cart actions for Pokestock.

Extracted conservatively from app.py. Dependencies are injected from app.py
to preserve formulas and sold_entries behavior.
"""


def configure_sales_actions(context):
    globals().update(context)


def _scu_in_data(cd, li, ci, q, p, canal="Main propre"):
    """Vend une carte dans un data.json deja charge, sans sauvegarder tout de suite."""
    crd=cd["lots"][li]["cards"][ci]
    if card_available_qty(crd) < q:
        return False,"Stock insuffisant"
    crd.setdefault("card_uid", new_uid("card"))
    crd["sold_quantity"]=crd.get("sold_quantity",0)+q
    prix_total = p*q
    sale_id = f"{crd.get('card_uid')}_{int(time.time()*1000)}"
    crd.setdefault("sold_entries",[]).append({
        "sale_id": sale_id,
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
    })

    # ── Redistribution du bénéfice aux lots contributeurs ──
    # Si cette carte a été reçue par échange avec contribution de plusieurs lots,
    # on ajoute une vente virtuelle dans chaque lot contributeur proportionnelle à leur part
    repartition = crd.get("exchange_repartition", {})
    if repartition:
        # valeur totale des contributions
        total_contrib = sum(float(v) for v in repartition.values()) or 1.
        for lot_idx_str, valeur_contrib in repartition.items():
            lot_idx_contrib = int(lot_idx_str)
            if lot_idx_contrib == li:
                continue  # le lot hôte garde son bénéfice normalement
            if lot_idx_contrib >= len(cd.get("lots", [])):
                continue
            # Part de bénéfice pour ce lot = (sa contribution / total) × prix de vente
            part = float(valeur_contrib) / total_contrib
            benefice_part = prix_total * part
            # Vente virtuelle dans ce lot pour matérialiser sa part du bénéfice
            cd["lots"][lot_idx_contrib].setdefault("ventes", []).append({
                "date": datetime.now().isoformat(),
                "price": benefice_part,
                "card_name": f"[Échange] Part bénéf. {crd['name']}",
                "is_exchange_benefit": True,
                "from_lot": cd["lots"][li]["nom"],
                "from_card": crd["name"],
                "source_sale_id": sale_id,
                "part_pct": round(part * 100, 1),
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

def scu_many(items, canal="Main propre"):
    """Vend plusieurs cartes avec une seule lecture et une seule sauvegarde."""
    cd = ld()
    requested = {}
    for item in items:
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
    for item in items:
        ok, msg = _scu_in_data(
            cd,
            item["lot_idx"],
            item["card_idx"],
            item["quantity"],
            item["unit_price"],
            canal,
        )
        if not ok:
            return False, msg
    sd(cd)
    return True, "Vendu!"

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

def bulk_sale_prepare(sale_type, price):
    st.session_state["pending_bulk_sale"] = {"type": sale_type, "price": price}
    st.session_state["show_canal_dialog_bulk"] = True

def scroll_to_cart_prepare():
    st.session_state["scroll_to_cart"] = True


"""Mobile-first Brocante page."""

from __future__ import annotations

from datetime import date, datetime

from core.brocante import (
    BRO_CATEGORIES,
    PAYMENT_METHODS,
    active_session,
    add_expense,
    brocante_stats,
    checklist_summary,
    close_session,
    lot_uid,
    make_session,
    new_id,
    payment_key,
    preparing_session,
    record_exchange,
    record_transaction,
    reopen_session,
    session_by_id,
    start_session,
)
from services.brocante_data import load_brocantes, save_brocantes
from core.trade_economics import (
    aggregate_contributors,
    allocate_received_cards,
    build_trade_id,
    card_historical_unit_cost,
    compute_trade_summary,
    contributors_from_card,
)
from ui.mobile_scan import render_assisted_scan


def _money(value, fp_func):
    try:
        return fp_func(float(value or 0))
    except Exception:
        return f"{float(value or 0):.2f}€"


def _lot_label(lot, index):
    return f"{index + 1}. {lot.get('nom', f'Lot {index + 1}')}"


def _lot_options(data):
    return [("Non attribuée", None)] + [(_lot_label(lot, idx), idx) for idx, lot in enumerate(data.get("lots", []) or [])]


def _append_off_stock_sale(cd, session, *, category, description, quantity, amount, payment_method, source_lot_idx, cost_basis, notes):
    tx_id = new_id("bro_offstock")
    sale = {
        "sale_id": tx_id,
        "date": datetime.now().isoformat(),
        "price": float(amount or 0),
        "quantity": int(quantity or 1),
        "card_name": f"Hors stock · {category}",
        "category": category,
        "description": description,
        "canal": "Brocante",
        "brocante_id": session.get("id"),
        "payment_method": payment_method,
        "sale_origin": "brocante",
        "inventory_impact": "none",
        "source_lot_id": None,
        "cost_basis_known": float(cost_basis or 0) > 0,
        "cost_basis": float(cost_basis or 0),
        "notes": notes,
        "is_off_stock": True,
    }
    if source_lot_idx is not None and 0 <= source_lot_idx < len(cd.get("lots", [])):
        source_lot = cd["lots"][source_lot_idx]
        sale["source_lot_id"] = lot_uid(source_lot, source_lot_idx)
        sale["source_lot_name"] = source_lot.get("nom")
        source_lot.setdefault("ventes", []).append(sale)
    else:
        cd.setdefault("ventes_hors_stock", []).append(sale)
    record_transaction(
        session,
        {
            "transaction_id": tx_id,
            "type": "off_stock_sale",
            "label": sale["card_name"],
            "category": category,
            "description": description,
            "quantity": int(quantity or 1),
            "amount": float(amount or 0),
            "payment_method": payment_method,
            "inventory_impact": "none",
            "source_lot_id": sale.get("source_lot_id"),
            "source_lot_name": sale.get("source_lot_name"),
            "cost_basis_known": sale["cost_basis_known"],
            "cost_basis": sale["cost_basis"],
            "notes": notes,
        },
    )
    return tx_id


def _render_goals(st, session, stats, fp_func):
    goals = session.setdefault("goals", {})
    st.markdown("### Objectifs")
    goal_defs = [
        ("ca", "Objectif CA", stats["ca"], "€"),
        ("net_cash", "Objectif trésorerie", stats["net_cash"], "€"),
        ("profit", "Objectif bénéfice calculable", stats["calculable_profit"], "€"),
        ("cards", "Objectif cartes vendues", stats["cards_sold"], ""),
        ("sales", "Objectif ventes", stats["sales_count"], ""),
        ("exchanges", "Objectif échanges", stats["exchanges_count"], ""),
    ]
    for key, label, current, suffix in goal_defs:
        target = float(goals.get(key, 0) or 0)
        if target > 0:
            pct = min(current / target * 100, 100) if target else 0
            st.progress(pct / 100)
            st.caption(f"{label} : {_money(current, fp_func) if suffix == '€' else int(current)} / {_money(target, fp_func) if suffix == '€' else int(target)}")
    custom = session.setdefault("custom_goals", [])
    if custom:
        for idx, goal in enumerate(custom):
            if goal.get("kind") == "checkbox":
                goal["done"] = st.checkbox(goal.get("label", "Objectif"), value=bool(goal.get("done")), key=f"bro_custom_goal_{session['id']}_{idx}")
            else:
                value = st.number_input(goal.get("label", "Objectif"), 0.0, 999999.0, float(goal.get("value", 0) or 0), 1.0, key=f"bro_custom_num_{session['id']}_{idx}")
                goal["value"] = value


def _render_dashboard(st, session, fp_func):
    stats = brocante_stats(session)
    c1, c2 = st.columns(2)
    c1.metric("CA", _money(stats["ca"], fp_func))
    c2.metric("Trésorerie", _money(stats["net_cash"], fp_func))
    c3, c4 = st.columns(2)
    c3.metric("Ventes", stats["sales_count"])
    c4.metric("Échanges", stats["exchanges_count"])
    _render_goals(st, session, stats, fp_func)


def _render_create(st, data, fp_func):
    with st.expander("Créer une brocante", expanded=True):
        name = st.text_input("Nom", key="bro_new_name", placeholder="Brocante du dimanche")
        event_date = st.date_input("Date", value=date.today(), key="bro_new_date")
        location = st.text_input("Lieu", key="bro_new_location")
        notes = st.text_area("Notes", key="bro_new_notes")
        st.caption("Objectifs facultatifs")
        g1, g2 = st.columns(2)
        goals = {
            "ca": g1.number_input("CA (€)", 0.0, 999999.0, 0.0, 5.0, key="bro_goal_ca"),
            "net_cash": g2.number_input("Trésorerie (€)", 0.0, 999999.0, 0.0, 5.0, key="bro_goal_cash"),
            "profit": g1.number_input("Bénéfice calculable (€)", 0.0, 999999.0, 0.0, 5.0, key="bro_goal_profit"),
            "cards": g2.number_input("Cartes vendues", 0, 9999, 0, 1, key="bro_goal_cards"),
            "sales": g1.number_input("Nombre de ventes", 0, 9999, 0, 1, key="bro_goal_sales"),
            "exchanges": g2.number_input("Nombre d'échanges", 0, 9999, 0, 1, key="bro_goal_exchanges"),
        }
        if st.button("Créer la brocante", type="primary", width="stretch", key="bro_create"):
            session = make_session(name, event_date, location, notes, goals, data.get("checklist_template"))
            data.setdefault("sessions", []).append(session)
            save_brocantes(data)
            st.success("Brocante créée.")
            st.rerun()


def _render_checklist(st, data, session):
    st.markdown("### Checklist")
    summary = checklist_summary(session)
    st.caption(f"{summary['done']} / {summary['total']} terminée(s)")
    for task in sorted(session.get("checklist", []), key=lambda x: int(x.get("order", 0) or 0)):
        label = f"{task.get('category', 'Divers')} · {task.get('title', '')}"
        if task.get("required"):
            label += " · obligatoire"
        task["done"] = st.checkbox(label, value=bool(task.get("done")), key=f"bro_task_{session['id']}_{task['id']}")
    new_task = st.text_input("Ajouter une tâche", key=f"bro_new_task_{session['id']}")
    if st.button("Ajouter la tâche", key=f"bro_add_task_{session['id']}", width="stretch") and new_task.strip():
        session.setdefault("checklist", []).append(
            {"id": new_id("task"), "title": new_task.strip(), "category": "Divers", "done": False, "required": False, "order": len(session.get("checklist", [])) + 1}
        )
        save_brocantes(data)
        st.rerun()


def _render_preparing(st, data, session, fp_func):
    st.markdown(f"## {session.get('name')}")
    st.caption(f"{session.get('date')} · {session.get('location') or 'Lieu non renseigné'}")
    _render_checklist(st, data, session)
    _render_dashboard(st, session, fp_func)
    missing = checklist_summary(session)["required_missing"]
    if missing:
        st.warning(f"{len(missing)} tâche(s) obligatoire(s) restent à confirmer.")
        force = st.checkbox("Démarrer quand même", key=f"bro_force_start_{session['id']}")
    else:
        force = True
    if st.button("Démarrer la brocante", type="primary", width="stretch", key=f"bro_start_{session['id']}"):
        ok, msg = start_session(data, session["id"], force=force)
        if ok:
            save_brocantes(data)
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)


def _render_stock_sale(st, data, session, context, fp_func):
    normalize_name = context["normalize_name"]
    cd = context["ld"]()
    st.markdown("### Vente stockée")
    st.caption("Canal automatiquement défini sur Brocante.")
    cart_key = f"bro_cart_{session['id']}"
    st.session_state.setdefault(cart_key, [])
    search = st.text_input("Rechercher une carte", key=f"bro_stock_search_{session['id']}", placeholder="Nom de carte")
    if search:
        rows = []
        for li, lot in enumerate(cd.get("lots", []) or []):
            for ci, card in enumerate(lot.get("cards", []) or []):
                if context["card_available_qty"](card) > 0 and normalize_name(search) in normalize_name(card.get("name", "")):
                    rows.append((li, ci, lot, card))
        for li, ci, lot, card in rows[:8]:
            cols = st.columns([3, 1, 1])
            cols[0].markdown(f"**{card.get('name')}**")
            cols[0].caption(f"{lot.get('nom')} · #{card.get('number', '')} · stock {context['card_available_qty'](card)}")
            qty = cols[1].number_input("Qté", 1, max(context["card_available_qty"](card), 1), 1, key=f"bro_stock_qty_{li}_{ci}")
            if cols[2].button("Ajouter", key=f"bro_stock_add_{li}_{ci}"):
                st.session_state[cart_key].append(
                    {
                        "lot_idx": li,
                        "card_idx": ci,
                        "lot_uid": lot.get("lot_uid"),
                        "card_uid": card.get("card_uid"),
                        "lot_name": lot.get("nom"),
                        "card_name": card.get("name"),
                        "card_set": card.get("set", ""),
                        "quantity": qty,
                        "price_base": float(card.get("suggested_price", 0) or 0),
                    }
                )
                st.rerun()
    with st.expander("Scanner une carte", expanded=False):
        def on_scan(candidate):
            card = candidate["card"]
            for li, lot in enumerate(cd.get("lots", []) or []):
                for ci, stock_card in enumerate(lot.get("cards", []) or []):
                    if stock_card.get("card_uid") == card.get("card_uid") or (
                        normalize_name(stock_card.get("name", "")) == normalize_name(card.get("name", ""))
                        and str(stock_card.get("number", "")).lstrip("0") == str(candidate.get("number", "")).lstrip("0")
                    ):
                        st.session_state[cart_key].append(
                            {
                                "lot_idx": li,
                                "card_idx": ci,
                                "lot_uid": lot.get("lot_uid"),
                                "card_uid": stock_card.get("card_uid"),
                                "lot_name": lot.get("nom"),
                                "card_name": stock_card.get("name"),
                                "card_set": stock_card.get("set", ""),
                                "quantity": 1,
                                "price_base": float(stock_card.get("suggested_price", 0) or 0),
                            }
                        )
                        return
            st.warning("Carte trouvée dans le cache, mais pas disponible dans le stock.")
        render_assisted_scan(
            key_prefix=f"bro_stock_scan_{session['id']}",
            cards_index=st.session_state.get("cards_index", {}) or {},
            normalize_name_func=normalize_name,
            proxy_img_func=context.get("proxy_img"),
            on_confirm=on_scan,
            button_label="Ajouter",
        )
    cart = st.session_state.get(cart_key, [])
    if cart:
        st.markdown("#### Panier")
        total = 0.0
        for idx, item in enumerate(list(cart)):
            total += item["quantity"] * item["price_base"]
            cols = st.columns([3, 1])
            cols[0].caption(f"{item['card_name']} · x{item['quantity']} · {_money(item['quantity'] * item['price_base'], fp_func)}")
            if cols[1].button("Retirer", key=f"bro_cart_rm_{idx}"):
                cart.pop(idx)
                st.rerun()
        negotiated = st.number_input("Prix global encaissé", 0.0, 999999.0, float(total), 0.5, key=f"bro_stock_total_{session['id']}")
        payment = st.selectbox("Paiement", PAYMENT_METHODS, key=f"bro_stock_payment_{session['id']}")
        paid = st.number_input("Montant donné en espèces", 0.0, 999999.0, 0.0, 0.5, key=f"bro_stock_cash_given_{session['id']}")
        if payment_key(payment) == "cash" and paid > 0:
            st.caption(f"Monnaie à rendre : {_money(max(paid - negotiated, 0), fp_func)}")
        tx_key = f"bro_stock_tx_{session['id']}_{round(negotiated, 2)}_{len(cart)}"
        if st.button("Valider la vente stockée", type="primary", width="stretch", key=f"bro_stock_validate_{session['id']}"):
            if st.session_state.get("bro_last_stock_tx") == tx_key:
                st.warning("Vente déjà validée.")
                return
            if total > 0 and abs(negotiated - total) > 0.01:
                items = [{**item, "unit_price": negotiated * ((item["quantity"] * item["price_base"]) / total) / item["quantity"]} for item in cart]
            else:
                items = [{**item, "unit_price": item["price_base"]} for item in cart]
            ok, msg = context["scu_many"](items, canal="Brocante")
            if ok:
                st.session_state["bro_last_stock_tx"] = tx_key
                record_transaction(session, {"type": "stock_sale", "label": "Vente stockée", "quantity": sum(i["quantity"] for i in items), "amount": negotiated, "payment_method": payment, "inventory_impact": "stock_decrement"})
                save_brocantes(data)
                st.session_state[cart_key] = []
                st.success("Vente stockée enregistrée.")
                st.rerun()
            else:
                st.error(msg)


def _render_off_stock_sale(st, data, session, context, fp_func):
    st.markdown("### Vente hors stock")
    cd = context["ld"]()
    category = st.selectbox("Catégorie", BRO_CATEGORIES, key=f"bro_off_cat_{session['id']}")
    description = st.text_input("Description facultative", key=f"bro_off_desc_{session['id']}")
    quantity = st.number_input("Quantité", 1, 9999, 1, 1, key=f"bro_off_qty_{session['id']}")
    amount = st.number_input("Prix total encaissé", 0.0, 999999.0, 0.0, 0.5, key=f"bro_off_amount_{session['id']}")
    payment = st.selectbox("Paiement", PAYMENT_METHODS, key=f"bro_off_payment_{session['id']}")
    options = _lot_options(cd)
    selected = st.selectbox("Lot source facultatif", [label for label, _ in options], key=f"bro_off_lot_{session['id']}")
    source_lot_idx = next(idx for label, idx in options if label == selected)
    cost = st.number_input("Coût d'achat attribué facultatif", 0.0, 999999.0, 0.0, 0.5, key=f"bro_off_cost_{session['id']}")
    notes = st.text_area("Notes facultatives", key=f"bro_off_notes_{session['id']}")
    if cost <= 0:
        st.caption("Coût inconnu : le bénéfice sera indiqué comme partiel/inconnu.")
    tx_key = f"off|{session['id']}|{category}|{quantity}|{amount}|{selected}|{description}"
    if st.button("Enregistrer la vente hors stock", type="primary", width="stretch", key=f"bro_off_save_{session['id']}"):
        if amount <= 0:
            st.error("Renseigne un prix encaissé.")
            return
        if st.session_state.get("bro_last_off_tx") == tx_key:
            st.warning("Vente déjà validée.")
            return
        _append_off_stock_sale(
            cd,
            session,
            category=category,
            description=description,
            quantity=quantity,
            amount=amount,
            payment_method=payment,
            source_lot_idx=source_lot_idx,
            cost_basis=cost,
            notes=notes,
        )
        context["sd"](cd)
        save_brocantes(data)
        st.session_state["bro_last_off_tx"] = tx_key
        st.success("Vente hors stock enregistrée sans baisse de stock.")
        st.rerun()


def _render_exchange(st, data, session, context, fp_func):
    st.markdown("### Échange brocante")
    st.caption("Les cartes reçues rejoignent le lot Trade. Les valeurs d'échange ne sont pas du CA.")
    cd = context["ld"]()
    normalize_name = context["normalize_name"]
    give_key = f"bro_ex_give_{session['id']}"
    recv_key = f"bro_ex_recv_{session['id']}"
    st.session_state.setdefault(give_key, [])
    st.session_state.setdefault(recv_key, [])
    search = st.text_input("Carte que tu donnes", key=f"bro_ex_search_{session['id']}")
    if search:
        for li, lot in enumerate(cd.get("lots", []) or []):
            for ci, card in enumerate(lot.get("cards", []) or []):
                if context["card_available_qty"](card) > 0 and normalize_name(search) in normalize_name(card.get("name", "")):
                    cols = st.columns([3, 1])
                    cols[0].caption(f"{card.get('name')} · {lot.get('nom')} · {_money(card.get('suggested_price', 0), fp_func)}")
                    if cols[1].button("Donner", key=f"bro_ex_give_add_{li}_{ci}"):
                        st.session_state[give_key].append({"lot_idx": li, "card_idx": ci, "card_uid": card.get("card_uid"), "card_name": card.get("name"), "value": float(card.get("suggested_price", 0) or 0)})
                        st.rerun()
                    break
    with st.expander("Carte reçue", expanded=True):
        rn = st.text_input("Nom reçu", key=f"bro_ex_recv_name_{session['id']}")
        rnum = st.text_input("Numéro", key=f"bro_ex_recv_num_{session['id']}")
        rval = st.number_input("Valeur manuelle", 0.0, 999999.0, 0.0, 0.5, key=f"bro_ex_recv_val_{session['id']}")
        if st.button("Ajouter la carte reçue", key=f"bro_ex_recv_add_{session['id']}"):
            if rn.strip():
                st.session_state[recv_key].append({"name": rn.strip(), "number": rnum.strip(), "value": rval, "set": "", "image_url": ""})
                st.rerun()
    given = st.session_state[give_key]
    received = st.session_state[recv_key]
    total_give = sum(float(x.get("value", 0) or 0) for x in given)
    total_recv = sum(float(x.get("value", 0) or 0) for x in received)
    cash_direction = st.radio("Complément espèces", ["Aucun", "Tu reçois", "Tu ajoutes"], horizontal=True, key=f"bro_ex_cash_dir_{session['id']}")
    cash_amount = st.number_input("Montant espèces", 0.0, 999999.0, 0.0, 0.5, key=f"bro_ex_cash_{session['id']}")
    cash_received = cash_amount if cash_direction == "Tu reçois" else 0.0
    cash_given = cash_amount if cash_direction == "Tu ajoutes" else 0.0
    st.caption(f"Tu donnes {_money(total_give, fp_func)} · tu reçois {_money(total_recv, fp_func)} · espèces nettes {_money(cash_received - cash_given, fp_func)}")
    if given:
        st.caption("À donner : " + ", ".join(x["card_name"] for x in given))
    if received:
        st.caption("À recevoir : " + ", ".join(x["name"] for x in received))
    if st.button("Confirmer l'échange", type="primary", width="stretch", key=f"bro_ex_confirm_{session['id']}"):
        if not given or not received:
            st.error("Ajoute au moins une carte donnée et une carte reçue.")
            return
        trade_id = build_trade_id()
        trade_date = datetime.now().isoformat()
        trade_idx = context["ensure_trade_lot"](cd)
        given_records = []
        for g in given:
            li, ci, lot, card = context["resolve_card_ref"](cd, g)
            if not card:
                continue
            historical_cost = card_historical_unit_cost(lot, card)
            contributors = contributors_from_card(li, lot, card, historical_cost)
            given_records.append({
                "lot_idx": li,
                "card_idx": ci,
                "lot": lot,
                "card": card,
                "reference_value": float(g.get("value", 0) or 0),
                "historical_cost": historical_cost,
                "contributors": contributors,
            })

        contributors, historical_before_cash, historical_remaining = aggregate_contributors(
            given_records, cash_paid=cash_given, cash_received=cash_received
        )
        summary = compute_trade_summary(
            total_give, total_recv, cash_paid=cash_given, cash_received=cash_received,
            given_historical_cost=sum(item["historical_cost"] for item in given_records),
        )
        received_allocated = allocate_received_cards(received, historical_remaining, contributors)
        received_names = ", ".join(r.get("name", "") for r in received)

        for record in given_records:
            card = record["card"]
            lot = record["lot"]
            card.setdefault("card_uid", context["new_uid"]("card"))
            card["exchange_out_quantity"] = int(card.get("exchange_out_quantity", 0) or 0) + 1
            card.setdefault("exchange_out_entries", []).append({
                "exchange_id": trade_id,
                "date": trade_date,
                "quantity": 1,
                "card_uid": card.get("card_uid"),
                "card_name": card.get("name"),
                "card_set": card.get("set", ""),
                "card_number": card.get("number", ""),
                "image_url": card.get("image_url", ""),
                "image_url_en": card.get("image_url_en", ""),
                "reference_value": record["reference_value"],
                "historical_cost": round(record["historical_cost"], 2),
                "lot_idx": record["lot_idx"],
                "lot_uid": lot.get("lot_uid"),
                "lot_name": lot.get("nom", ""),
                "contributors": record["contributors"],
                "exchanged_for": received_names,
                "brocante_id": session.get("id"),
            })

        for r in received_allocated:
            cd["lots"][trade_idx].setdefault("cards", []).append(
                {
                    "card_uid": context["new_uid"]("card"),
                    "name": r["name"],
                    "set": r.get("set", ""),
                    "number": r.get("number", ""),
                    "suggested_price": float(r.get("value", 0) or 0),
                    "quantity": 1,
                    "sold_quantity": 0,
                    "condition": "NM",
                    "image_url": r.get("image_url", ""),
                    "image_url_en": r.get("image_url_en", ""),
                    "sold_entries": [],
                    "received_by_exchange": True,
                    "exchange_id": trade_id,
                    "exchange_date": trade_date[:10],
                    "exchange_cash_paid": cash_given,
                    "exchange_cash_received": cash_received,
                    "trade_acquisition_cost": r.get("trade_acquisition_total_cost", 0.0),
                    "trade_acquisition_unit_cost": r.get("trade_acquisition_unit_cost", 0.0),
                    "trade_acquisition_total_cost": r.get("trade_acquisition_total_cost", 0.0),
                    "trade_contributors": r.get("trade_contributors", []),
                    "exchange_repartition": r.get("exchange_repartition", {}),
                    "trade_received_cards_value": summary["trade_received_cards_value"],
                    "trade_given_cards_value": summary["trade_given_cards_value"],
                    "trade_cash_paid": summary["trade_cash_paid"],
                    "trade_cash_received": summary["trade_cash_received"],
                    "trade_economic_received_total": summary["trade_economic_received_total"],
                    "trade_economic_given_total": summary["trade_economic_given_total"],
                    "trade_value_difference": summary["trade_value_difference"],
                    "trade_cost_method": summary["trade_cost_method"],
                    "brocante_id": session.get("id"),
                }
            )
        cd.setdefault("trade_history", []).append({
            "exchange_id": trade_id,
            "date": trade_date,
            **summary,
            "trade_historical_cost_before_cash": historical_before_cash,
            "trade_acquisition_total_cost": historical_remaining,
            "contributors": contributors,
            "given_cards": given,
            "received_cards": received,
            "brocante_id": session.get("id"),
        })
        context["sd"](cd)
        record_exchange(session, {"given": given, "received": received, "cash_received": cash_received, "cash_given": cash_given, "value_given": total_give, "value_received": total_recv})
        save_brocantes(data)
        st.session_state[give_key] = []
        st.session_state[recv_key] = []
        st.success("Échange enregistré.")
        st.rerun()


def _render_expenses_and_close(st, data, session, fp_func):
    st.markdown("### Frais et clôture")
    with st.expander("Ajouter des frais de journée", expanded=False):
        label = st.text_input("Libellé", key=f"bro_exp_label_{session['id']}")
        category = st.selectbox("Catégorie", ["Emplacement", "Transport", "Nourriture", "Matériel", "Autre"], key=f"bro_exp_cat_{session['id']}")
        amount = st.number_input("Montant", 0.0, 999999.0, 0.0, 0.5, key=f"bro_exp_amount_{session['id']}")
        note = st.text_input("Note", key=f"bro_exp_note_{session['id']}")
        if st.button("Ajouter le frais", key=f"bro_exp_add_{session['id']}", width="stretch") and amount > 0:
            add_expense(session, label, amount, category, note)
            save_brocantes(data)
            st.rerun()
    stats = brocante_stats(session)
    st.caption(f"CA ventes : {_money(stats['ca'], fp_func)}")
    st.caption(f"Espèces théoriques : {_money(stats['payments']['cash'] + stats['exchange_cash_received'] - stats['exchange_cash_given'] - stats['fees'], fp_func)}")
    st.caption(f"PayPal : {_money(stats['payments']['paypal'], fp_func)} · Autres : {_money(stats['payments']['other'], fp_func)}")
    st.caption(f"Frais : {_money(stats['fees'], fp_func)} · Trésorerie nette : {_money(stats['net_cash'], fp_func)}")
    st.caption(f"Ventes hors stock sans coût : {stats['unknown_cost_sales']}")
    counted = st.number_input("Espèces réellement comptées", 0.0, 999999.0, 0.0, 0.5, key=f"bro_counted_cash_{session['id']}")
    note = st.text_area("Note d'écart éventuel", key=f"bro_close_note_{session['id']}")
    confirm = st.checkbox("Je confirme la clôture", key=f"bro_close_confirm_{session['id']}")
    if st.button("Clôturer la brocante", type="primary", width="stretch", key=f"bro_close_{session['id']}", disabled=not confirm):
        close_session(session, counted, note)
        save_brocantes(data)
        st.success("Brocante clôturée.")
        st.rerun()


def _render_history(st, data, fp_func):
    closed = [s for s in data.get("sessions", []) if s.get("status") == "closed"]
    st.markdown("### Historique")
    if not closed:
        st.info("Aucune brocante clôturée pour le moment.")
        return
    stats_rows = [(s, brocante_stats(s)) for s in closed]
    avg_ca = sum(row[1]["ca"] for row in stats_rows) / len(stats_rows)
    best_ca = max(stats_rows, key=lambda row: row[1]["ca"])
    for session, stats in sorted(stats_rows, key=lambda row: row[0].get("date", ""), reverse=True):
        with st.container(border=True):
            st.markdown(f"**{session.get('date')} · {session.get('name')}**")
            st.caption(f"CA {_money(stats['ca'], fp_func)} · trésorerie {_money(stats['net_cash'], fp_func)} · ventes {stats['sales_count']} · échanges {stats['exchanges_count']}")
            if avg_ca > 0:
                st.caption(f"CA : {(stats['ca'] - avg_ca) / avg_ca * 100:+.0f}% par rapport à la moyenne")
            if session.get("id") == best_ca[0].get("id"):
                st.caption(f"Meilleur CA sur {len(closed)} brocante(s)")


def render_brocante_page(context):
    globals().update(context)
    st.markdown(render_page_header("Brocante", "Préparation, ventes mobiles, échanges et clôture", "🧺"), unsafe_allow_html=True)
    data = load_brocantes()
    active = active_session(data)
    preparing = preparing_session(data)
    tabs = st.tabs(["Aujourd'hui", "Vente rapide", "Hors stock", "Échange", "Frais / clôture", "Historique"])
    with tabs[0]:
        if active:
            st.success("Brocante en cours")
            st.markdown(f"## {active.get('name')}")
            _render_dashboard(st, active, fp)
        elif preparing:
            _render_preparing(st, data, preparing, fp)
        else:
            st.info("Aucune brocante active.")
            _render_create(st, data, fp)
    current = active or preparing
    with tabs[1]:
        if active:
            _render_stock_sale(st, data, active, context, fp)
        else:
            st.info("Démarre une brocante pour vendre depuis ce module.")
    with tabs[2]:
        if active:
            _render_off_stock_sale(st, data, active, context, fp)
        else:
            st.info("Démarre une brocante pour enregistrer une vente hors stock.")
    with tabs[3]:
        if active:
            _render_exchange(st, data, active, context, fp)
        else:
            st.info("Démarre une brocante pour enregistrer un échange.")
    with tabs[4]:
        if active:
            _render_expenses_and_close(st, data, active, fp)
        elif current and current.get("status") == "closed":
            st.info("Brocante clôturée.")
        else:
            st.info("Aucune brocante active à clôturer.")
    with tabs[5]:
        _render_history(st, data, fp)
        closed = [s for s in data.get("sessions", []) if s.get("status") == "closed"]
        if closed:
            labels = [f"{s.get('date')} · {s.get('name')}" for s in closed]
            choice = st.selectbox("Réouvrir une brocante clôturée", [""] + labels, key="bro_reopen_choice")
            if choice:
                session = closed[labels.index(choice)]
                if st.checkbox("Confirmer la réouverture", key=f"bro_reopen_confirm_{session['id']}"):
                    if st.button("Réouvrir", key=f"bro_reopen_{session['id']}"):
                        ok, msg = reopen_session(data, session["id"])
                        if ok:
                            save_brocantes(data)
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

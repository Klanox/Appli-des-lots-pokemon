"""Event workspace using the main Sale and Trade renderers and engines."""
from copy import deepcopy
from datetime import date
from html import escape

from core.brocante import (
    BRO_CATEGORIES, PAYMENT_METHODS, active_session, add_expense, brocante_stats,
    checklist_summary, close_session, make_session, new_id, preparing_session,
    reopen_session, start_session,
)
from core.trade_economics import search_received_cards
from services.brocante_data import load_brocantes, save_brocantes
from services.brocante_workflow import commit_staged, deletion_audit, project_event, stage_delete, stage_purchase
from ui.inventory_live_search import inventory_live_search

VIEWS = ["Aujourd’hui", "Vente", "Rachat", "Hors stock", "Échange", "Frais / clôture", "Historique"]
CSS = """
<style>
.bro-header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:4px 0 12px}
.bro-header h2{font-size:22px!important;margin:0 0 2px!important;padding:0!important;color:#111827}.bro-meta{color:#6b7280;font-size:13px}
.bro-badge{font-size:12px;font-weight:700;border:1px solid #bbf7d0;padding:4px 8px;border-radius:6px;color:#15803d;background:#f0fdf4;white-space:nowrap}
.bro-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:8px 0 12px}
.bro-kpi{border:1px solid #e5e7eb;border-top:3px solid var(--accent);background:white;border-radius:8px;padding:12px;min-width:0}
.bro-kpi strong{font-size:23px;display:block;color:var(--accent);margin:4px 0}.bro-kpi small{color:#6b7280}
.bro-ledger{background:white;border:1px solid #e5e7eb;border-radius:8px;margin:8px 0 12px}
.bro-ledger div{display:flex;justify-content:space-between;gap:12px;padding:8px 10px;border-bottom:1px solid #f1f3f5;font-size:13px}
.bro-ledger span{min-width:0;overflow-wrap:anywhere}.bro-ledger strong{white-space:nowrap}
[class*="st-key-bro_actions"] [data-testid="stButton"] button{min-height:42px}[class*="st-key-bro_actions_primary"] [data-testid="stButton"] button{min-height:46px;font-size:15px}
.bro-closing-flow{display:grid;gap:2px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:6px 10px;margin:8px 0 12px}.bro-closing-flow div{display:flex;justify-content:space-between;gap:10px;padding:7px 0;font-size:13px;border-bottom:1px solid #f1f3f5}.bro-closing-flow .in{color:#15803d}.bro-closing-flow .out{color:#c2410c}.bro-closing-flow .total{border:0;color:#6d28d9;font-size:15px;font-weight:800}
[data-testid="stSegmentedControl"]{margin:2px 0 8px}[data-testid="stSegmentedControl"] [role="radiogroup"]{gap:4px}
@media(max-width:900px){.bro-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){[data-testid="stSegmentedControl"]{overflow-x:auto;padding-bottom:3px}[data-testid="stSegmentedControl"] [role="radiogroup"]{flex-wrap:nowrap!important;min-width:max-content}[data-testid="stSegmentedControl"] button{min-height:42px!important;white-space:nowrap}.bro-header{align-items:flex-start;margin:2px 0 8px}.bro-header h2{font-size:20px!important}.bro-meta{font-size:12px}.bro-kpi{padding:10px}.bro-kpi strong{font-size:21px}.bro-ledger div{padding:8px 9px}.bro-actions{gap:7px}.bro-closing-flow{padding:5px 9px}}
</style>
"""


def money(value):
    return "Non renseigné" if value is None else f"{float(value):,.2f} €".replace(",", " ").replace(".", ",")


def ledger(st, rows):
    st.html('<div class="bro-ledger">' + ''.join(
        f'<div><span>{escape(str(label))}</span><strong>{escape(str(value))}</strong></div>'
        for label, value in rows) + '</div>')


def go(st, view):
    st.session_state["brocante_view"] = view


def saved(st, data, message):
    save_brocantes(data)
    st.session_state["brocante_flash"] = message
    st.rerun()


def header(st, event):
    status = {"active": "En cours", "preparing": "Préparation", "draft": "Préparation", "closed": "Clôturée"}.get(event.get("status"), "")
    st.html(f'<div class="bro-header"><div><h2>{escape(event["name"])}</h2><div class="bro-meta">'
            f'{escape(event.get("date", ""))} · {escape(event.get("location") or "Lieu non renseigné")}'
            f'</div></div><span class="bro-badge">{status}</span></div>')


def dashboard(st, event, data=None, *, actions=False, compact=False, mobile=False):
    s = brocante_stats(event)
    metrics = [("Chiffre d’affaires", money(s["ca"]), "#6d28d9", f'{s["sales_count"]} commandes'),
               ("Bénéfice calculable", money(s["calculable_profit"]), "#15803d", "Après frais"),
               ("Caisse théorique", money(s["theoretical_cash"]), "#111827", "Espèces disponibles"),
               ("Cartes vendues", str(s["cards_sold"]), "#2563eb", "Cartes physiques")]
    st.html('<div class="bro-kpis">' + ''.join(
        f'<div class="bro-kpi" style="--accent:{color}"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>'
        for label, value, color, detail in metrics) + '</div>')
    if s["unknown_cost_sales"]:
        st.caption(f'{s["unknown_cost_sales"]} commande(s) sans coût complet : bénéfice partiel.')
    st.caption(f'{s["purchases_count"]} rachats · {money(s["purchased_amount"])} dépensés · {s["exchanges_count"]} échanges · {money(s["fees"])} de frais')
    if actions:
        if mobile:
            with st.container(key="bro_actions_primary"):
                st.button("Nouvelle vente", key="bro_quick_Nouvelle vente", type="primary", on_click=go,
                          args=(st, "Vente"), width="stretch")
            with st.container(key="bro_actions"):
                for col, (label, view) in zip(
                    st.columns(2),
                    (("Nouveau rachat", "Rachat"), ("Hors stock", "Hors stock")),
                ):
                    col.button(label, key=f'bro_quick_{label}', on_click=go, args=(st, view), width="stretch")
                for col, (label, view) in zip(
                    st.columns(2),
                    (("Nouvel échange", "Échange"), ("Ajouter un frais", "Frais / clôture")),
                ):
                    col.button(label, key=f'bro_quick_{label}', on_click=go, args=(st, view), width="stretch")
            st.divider()
            st.button("Clôturer la journée", key="bro_quick_Clôturer", on_click=go,
                      args=(st, "Frais / clôture"), width="stretch")
        else:
            actions_top = (("Nouvelle vente", "Vente", "primary"), ("Nouveau rachat", "Rachat", "secondary"),
                           ("Hors stock", "Hors stock", "secondary"))
            for col, (label, view, button_type) in zip(st.columns(3), actions_top):
                col.button(label, key=f'bro_quick_{label}', type=button_type, on_click=go, args=(st, view), width="stretch")
            actions_bottom = (("Nouvel échange", "Échange"), ("Ajouter un frais", "Frais / clôture"))
            for col, (label, view) in zip(st.columns(2), actions_bottom):
                col.button(label, key=f'bro_quick_{label}', on_click=go, args=(st, view), width="stretch")
            st.divider()
            st.button("Clôturer la journée", key="bro_quick_Clôturer", on_click=go,
                      args=(st, "Frais / clôture"))
    if compact:
        return s
    left, right = (st.container(), st.container()) if mobile else st.columns(2)
    with left:
        st.markdown("### Encaissements")
        ledger(st, [("Fonds initial", money(s["initial_cash"])), ("Ventes espèces", money(s["payments"]["cash"])),
                    ("PayPal / autres", money(sum(s["payments"][k] for k in ("paypal", "other", "unknown")))),
                    ("CA stock", money(s["ca"]-s["ca_off_stock"])), ("CA hors stock", money(s["ca_off_stock"])),
                    ("Trésorerie générée", money(s["net_cash"]))])
    with right:
        st.markdown("### Objectifs")
        definitions = [("ca", "CA", s["ca"]), ("net_cash", "Trésorerie générée", s["net_cash"]),
                       ("profit", "Bénéfice", s["calculable_profit"]), ("cards", "Cartes vendues", s["cards_sold"]),
                       ("sales", "Ventes", s["sales_count"]), ("exchanges", "Échanges", s["exchanges_count"])]
        visible = False
        for key, label, current in definitions:
            target = float(event.get("goals", {}).get(key, 0) or 0)
            if target > 0:
                visible = True
                st.progress(min(max(current/target, 0), 1), text=f'{label} · {current:g} / {target:g}')
        for i, goal in enumerate(event.get("custom_goals", [])):
            visible = True
            field = "done" if goal.get("kind") == "checkbox" else "value"
            initial = goal.get(field, False if field == "done" else 0.0)
            widget = st.checkbox if field == "done" else st.number_input
            value = widget(goal.get("label", "Objectif"), value=initial, key=f'bro_goal_{event["id"]}_{i}', disabled=not actions)
            if actions and value != initial:
                goal[field] = value
                saved(st, data, "Objectif mis à jour.")
        if not visible:
            st.caption("Aucun objectif chiffré pour cette journée.")


def create(st, data):
    st.subheader("Préparer une brocante")
    with st.form("bro_create_form"):
        a, b = st.columns(2)
        name = a.text_input("Nom", placeholder="Brocante du dimanche")
        day = b.date_input("Date", value=date.today())
        location = a.text_input("Lieu")
        cash = b.number_input("Fonds de caisse initial (€)", min_value=0.0, value=None, step=5.0, placeholder="Obligatoire avant démarrage")
        with st.expander("Notes et objectifs"):
            notes = st.text_area("Notes", height=80)
            c, d = st.columns(2)
            goals = {}
            for i, (key, label) in enumerate((("ca", "CA (€)"), ("net_cash", "Trésorerie (€)"), ("profit", "Bénéfice (€)"),
                                               ("cards", "Cartes vendues"), ("sales", "Ventes"), ("exchanges", "Échanges"))):
                goals[key] = (c if i % 2 == 0 else d).number_input(f'Objectif {label}', min_value=0.0, step=1.0)
        if st.form_submit_button("Créer la brocante", type="primary"):
            data.setdefault("sessions", []).append(make_session(name, day, location, notes, goals, data.get("checklist_template"), initial_cash=cash))
            saved(st, data, "Brocante créée. Prépare la journée avant de démarrer.")


def preparing(st, data, event):
    header(st, event)
    summary = checklist_summary(event)
    st.progress(summary["done"]/max(summary["total"], 1), text=f'Préparation · {summary["done"]} / {summary["total"]}')
    with st.form(f'bro_checklist_{event["id"]}'):
        cols, values = st.columns(2), {}
        categories = list(dict.fromkeys(t.get("category", "Divers") for t in event.get("checklist", [])))
        for i, category in enumerate(categories):
            with cols[i % 2]:
                st.markdown(f"**{category}**")
                for task in event["checklist"]:
                    if task.get("category", "Divers") == category:
                        label = task["title"] + (" · Obligatoire" if task.get("required") else "")
                        values[task["id"]] = st.checkbox(label, value=bool(task.get("done")), key=f'bro_task_{event["id"]}_{task["id"]}')
        if st.form_submit_button("Enregistrer la préparation"):
            for task in event["checklist"]:
                task["done"] = values[task["id"]]
            saved(st, data, "Préparation enregistrée.")
    with st.expander("Ajouter une tâche"):
        with st.form(f'bro_add_task_{event["id"]}', clear_on_submit=True):
            title, required = st.text_input("Tâche"), st.checkbox("Obligatoire")
            if st.form_submit_button("Ajouter") and title.strip():
                event["checklist"].append(dict(id=new_id("task"), title=title.strip(), category="Divers", required=required,
                                                done=False, order=len(event["checklist"])+1))
                saved(st, data, "Tâche ajoutée.")
    with st.form(f'bro_start_form_{event["id"]}'):
        initial_cash = event.get("initial_cash")
        cash = st.number_input("Fonds de caisse initial (€)", min_value=0.0,
                               value=float(initial_cash) if initial_cash is not None else None, step=5.0)
        st.caption(f'Objectif CA : {money(event.get("goals", {}).get("ca", 0))} · Trésorerie : {money(event.get("goals", {}).get("net_cash", 0))}')
        if summary["required_missing"]:
            st.warning(f'{len(summary["required_missing"])} tâche(s) obligatoire(s) non confirmée(s).')
        force = st.checkbox("Démarrer quand même", disabled=not summary["required_missing"])
        if st.form_submit_button("Démarrer la brocante", type="primary"):
            event["initial_cash"] = cash
            ok, message = start_session(data, event["id"], force=force)
            if ok:
                saved(st, data, message)
            st.error(message)


def catalog_image(st, card, *, width=90):
    image = card.get("image_url_ja") or card.get("image_url") or card.get("image_url_en") or card.get("image")
    if isinstance(image, str) and image and image != "__placeholder__":
        if image.startswith("https://assets.tcgdex.net/") and not image.endswith((".png", ".jpg", ".webp")):
            image += "/low.webp"
        st.image(image, width=width)


def purchase(st, event, context):
    st.subheader("Rachat de cartes")
    st.caption("Ajoute les cartes proposées puis indique le montant total payé.")
    mobile = bool(context.get("is_mobile_mode", lambda: False)())
    key = f'bro_purchase_cart_{event["id"]}'
    cart = st.session_state.setdefault(key, [])
    query = inventory_live_search("Rechercher une carte", key=f'bro_purchase_query_{event["id"]}', placeholder="Nom, numéro… FR / JAP")
    results = search_received_cards(query, st.session_state.get("cards_index", {}), context["normalize_name"], limit=12) if query.strip() else []
    if not query.strip():
        st.caption("Recherche une carte pour commencer.")
    if query and not results:
        st.caption("Aucune carte trouvée.")
    result_columns = 2 if mobile else 4
    for offset in range(0, len(results), result_columns):
        for col, (card, set_name, set_id) in zip(st.columns(result_columns), results[offset:offset + result_columns]):
            with col:
                with st.container(border=True):
                    catalog_image(st, card)
                    st.markdown(f'**{card.get("name", "Carte")}**')
                    st.caption(f'{card.get("localId", card.get("number", ""))} · {set_name} · {card.get("lang", "fr").upper()}')
                    if st.button("Sélectionner", key=f'bro_buy_pick_{offset}_{set_id}_{card.get("id", card.get("name"))}'):
                        selected = context["ecd"](card, set_name, lang=card.get("lang", "fr"))
                        selected["set_id"] = set_id
                        st.session_state[f'{key}_selected'] = selected
                        st.rerun()
    selected = st.session_state.get(f'{key}_selected')
    if selected:
        with st.form(f'{key}_add', clear_on_submit=True):
            st.markdown(f'**{selected["name"]} · {selected.get("number", "")}**')
            qty = st.number_input("Quantité", min_value=1, max_value=9999, value=1)
            if st.form_submit_button("Ajouter au panier de rachat"):
                cart.append({"card": deepcopy(selected), "quantity": qty})
                st.session_state.pop(f'{key}_selected', None)
                st.rerun()
    if not cart:
        st.caption("Ajoute une ou plusieurs cartes au rachat.")
        return
    purchase_quantity = sum(int(row.get("quantity", 1) or 1) for row in cart)
    st.markdown(f"### Panier de rachat · {purchase_quantity} carte{'s' if purchase_quantity != 1 else ''}")
    for i, row in enumerate(cart):
        image_col, info_col, action_col = st.columns([1, 3, 1.4])
        with image_col:
            catalog_image(st, row["card"], width=56)
        info_col.write(f'{row["card"]["name"]} · {row["card"].get("number", "")}')
        info_col.caption(f'{row["card"].get("set", "Extension non renseignée")} · Qté {row["quantity"]}')
        if action_col.button("Retirer", key=f'bro_buy_remove_{i}', width="stretch"):
            cart.pop(i)
            st.rerun()
    with st.form(f'{key}_confirm'):
        if mobile:
            amount = st.number_input("Montant total réellement payé (€)", min_value=0.0, value=None, step=0.5)
            payment = st.selectbox("Paiement", PAYMENT_METHODS)
        else:
            a, b = st.columns(2)
            amount = a.number_input("Montant total réellement payé (€)", min_value=0.0, value=None, step=0.5)
            payment = b.selectbox("Paiement", PAYMENT_METHODS)
        if st.form_submit_button("Valider le rachat", type="primary"):
            if amount is None:
                st.error("Renseigne le montant total payé.")
                return
            stock, fresh = context["ld"](), load_brocantes()
            attempt = st.session_state.setdefault(f'{key}_attempt', new_id("purchase"))
            try:
                after_stock, after_events = stage_purchase(stock, fresh, event["id"], cart, amount, payment, attempt)
                commit_staged(stock, fresh, after_stock, after_events, context["sd"], save_brocantes)
            except (ValueError, OSError) as error:
                st.error(str(error))
                return
            st.session_state[key] = []
            st.session_state.pop(f'{key}_attempt', None)
            st.session_state["brocante_flash"] = "Rachat enregistré dans le lot de la journée."
            st.rerun()


def offstock(st, event, context):
    st.subheader("Vente hors stock")
    stock = context["ld"]()
    mobile = bool(context.get("is_mobile_mode", lambda: False)())
    with st.form(f'bro_offstock_{event["id"]}', clear_on_submit=True):
        if mobile:
            category = st.selectbox("Catégorie", BRO_CATEGORIES)
            description = st.text_input("Description")
            qty = st.number_input("Quantité", min_value=1, max_value=9999, value=1)
            amount = st.number_input("Prix total encaissé (€)", min_value=0.0, value=None, step=0.5)
            payment = st.selectbox("Paiement", PAYMENT_METHODS)
        else:
            a, b = st.columns(2)
            category, description = a.selectbox("Catégorie", BRO_CATEGORIES), b.text_input("Description")
            qty = a.number_input("Quantité", min_value=1, max_value=9999, value=1)
            amount = b.number_input("Prix total encaissé (€)", min_value=0.0, value=None, step=0.5)
            payment = a.selectbox("Paiement", PAYMENT_METHODS)
        with st.expander("Options"):
            lot_idx = st.selectbox("Lot source", [None] + list(range(len(stock.get("lots", [])))),
                                   format_func=lambda i: "Non attribué" if i is None else stock["lots"][i]["nom"])
            cost = st.number_input("Coût total attribué (€)", min_value=0.0, value=None, step=0.5, help="Vide : coût inconnu. Zéro : coût connu et nul.")
            notes = st.text_input("Notes")
        if st.form_submit_button("Enregistrer la vente", type="primary"):
            if amount is None:
                st.error("Renseigne le montant encaissé.")
                return
            attempt_key = f'bro_offstock_attempt_{event["id"]}'
            st.session_state.setdefault(attempt_key, new_id("sale_tx"))
            line = dict(line_type="off_stock", quantity=qty, unit_price=amount/qty, category=category,
                        description=description, source_lot_idx=lot_idx, cost_basis=cost,
                        cost_basis_known=cost is not None, notes=notes)
            ok, message = context["scu_many"]([line], "Brocante", brocante_id=event["id"], payment_method=payment,
                                             transaction_id=st.session_state[attempt_key])
            if ok:
                st.session_state.pop(attempt_key, None)
                st.session_state["brocante_flash"] = "Vente hors stock enregistrée."
                st.rerun()
            st.error(message)


def closing(st, data, event):
    st.subheader("Frais et clôture")
    with st.expander("Ajouter un frais"):
        with st.form(f'bro_expense_{event["id"]}', clear_on_submit=True):
            a, b = st.columns(2)
            category = a.selectbox("Catégorie", ["Emplacement", "Nourriture", "Transport", "Matériel", "Parking", "Divers"])
            label, amount = b.text_input("Description"), a.number_input("Montant (€)", min_value=0.0, step=0.5)
            payment, note = b.selectbox("Paiement", PAYMENT_METHODS), st.text_input("Notes")
            if st.form_submit_button("Ajouter le frais") and amount > 0:
                add_expense(event, label, amount, category, note, payment_method=payment)
                saved(st, data, "Frais enregistré.")
    if event.get("expenses"):
        ledger(st, [(f'{e["label"]} · {e.get("payment_method", "Espèces")}', money(e["amount"])) for e in event["expenses"]])
    s = dashboard(st, event, compact=True)
    st.markdown("### Caisse")
    st.html(
        '<div class="bro-closing-flow">'
        f'<div><span>Fonds initial</span><strong>{escape(money(s["initial_cash"]))}</strong></div>'
        f'<div class="in"><span>+ Ventes espèces</span><strong>{escape(money(s["payments"]["cash"]))}</strong></div>'
        f'<div class="in"><span>+ Compléments reçus</span><strong>{escape(money(s["exchange_cash_received"]))}</strong></div>'
        f'<div class="out"><span>− Rachats espèces</span><strong>{escape(money(s["cash_purchases"]))}</strong></div>'
        f'<div class="out"><span>− Frais espèces</span><strong>{escape(money(s["cash_fees"]))}</strong></div>'
        f'<div class="out"><span>− Compléments donnés</span><strong>{escape(money(s["exchange_cash_given"]))}</strong></div>'
        f'<div class="total"><span>= Caisse théorique</span><strong>{escape(money(s["theoretical_cash"]))}</strong></div>'
        '</div>'
    )
    if s["initial_cash"] is None:
        st.warning("Fonds initial absent dans cet historique : l'écart de caisse ne peut pas être calculé.")
    counted = st.number_input("Espèces réellement comptées (€)", min_value=0.0, value=None, step=0.5, key=f'bro_counted_{event["id"]}')
    if counted is not None and s["theoretical_cash"] is not None:
        variance = counted-s["theoretical_cash"]
        (st.success if abs(variance) < 0.005 else st.warning)(f'Écart de caisse : {money(variance)}')
    note = st.text_area("Note d'écart", height=80, key=f'bro_variance_note_{event["id"]}')
    confirm = st.checkbox("Je confirme la clôture de cette brocante", key=f'bro_close_confirm_{event["id"]}')
    if st.button("Clôturer la brocante", type="primary", disabled=not confirm or counted is None):
        close_session(event, counted, note)
        saved(st, data, "Brocante clôturée.")


def management(st, data, event, context):
    with st.expander("Archiver / supprimer"):
        if event["status"] == "closed":
            archived = bool(event.get("archived"))
            if st.button("Désarchiver" if archived else "Archiver", key=f'bro_archive_{event["id"]}'):
                event["archived"] = not archived
                saved(st, data, "Archivage mis à jour. Les ventes sont conservées.")
        from services.vinted_drops_service import load_vinted_drops
        audit = deletion_audit(context["ld"](), data, event["id"], load_vinted_drops())
        s = brocante_stats(audit["event"])
        st.caption(f'{s["sales_count"]} ventes · {s["cards_sold"]} cartes · {s["off_stock_sales"]} commandes hors stock · {s["purchases_count"]} rachats · {s["exchanges_count"]} échanges · {len(event.get("expenses", []))} frais')
        for _, lot in audit["purchase_lots"]:
            st.caption(f'Lot concerné : {lot["nom"]}')
        for reason in audit["blockers"]:
            st.warning(reason)
        if audit["blockers"]:
            return
        if audit["has_activity"]:
            st.warning("Les ventes liées seront annulées et leur stock restauré. Les rachats inutilisés et les frais seront retirés.")
            confirmed = st.text_input("Saisis le nom de la brocante pour confirmer", key=f'bro_delete_name_{event["id"]}') == event["name"]
        else:
            confirmed = st.checkbox("Supprimer cette brocante vide", key=f'bro_delete_empty_{event["id"]}')
        if st.button("Supprimer définitivement", disabled=not confirmed, key=f'bro_delete_{event["id"]}'):
            before_stock, before_events = context["ld"](), load_brocantes()
            try:
                after_stock, after_events = stage_delete(before_stock, before_events, event["id"], load_vinted_drops())
                commit_staged(before_stock, before_events, after_stock, after_events, context["sd"], save_brocantes)
            except (ValueError, OSError) as error:
                st.error(str(error))
                return
            st.session_state["brocante_flash"] = "Brocante supprimée."
            st.rerun()


def history(st, data, context):
    st.subheader("Historique des brocantes")
    archives = st.checkbox("Inclure les archives", key="bro_show_archived")
    closed = [e for e in data.get("sessions", []) if e["status"] == "closed" and (archives or not e.get("archived"))]
    if not closed:
        st.info("Aucune brocante clôturée à afficher.")
        return
    closed = sorted(closed, key=lambda e: e.get("date", ""), reverse=True)
    options = []
    for event in closed:
        s = brocante_stats(event)
        variance = event.get("closure", {}).get("cash_variance")
        options.append((
            f'{event.get("date", "")} · {event["name"]} · {money(s["ca"])} · {money(s["calculable_profit"])}',
            event,
            f'{s["sales_count"]} ventes · {s["purchases_count"]} rachats · {money(variance)} écart',
        ))
    labels = [label for label, _, _ in options]
    selected_label = st.selectbox("Brocante à consulter", labels, key="bro_history_event")
    _, event, summary = next(item for item in options if item[0] == selected_label)
    st.caption(summary)
    header(st, event)
    dashboard(st, event, compact=True)
    ledger(st, [("Caisse comptée", money(event.get("closure", {}).get("counted_cash"))),
                ("Écart de caisse", money(event.get("closure", {}).get("cash_variance")))])
    st.caption(event.get("closure", {}).get("variance_note", ""))
    with st.expander("Opérations de la journée"):
        for label, collection in (("Ventes", "transactions"), ("Rachats", "purchases"), ("Frais", "expenses")):
            st.markdown(f'**{label}**')
            ledger(st, [(f'{r.get("created_at", "")} · {r.get("label", label)}', money(r.get("amount", 0))) for r in event.get(collection, [])])
        for trade in event.get("exchanges", []):
            st.caption(f'Échange · {trade.get("created_at", "")} · reçu {money(trade.get("cash_received", 0))} · donné {money(trade.get("cash_given", 0))}')
    confirm = st.checkbox("Confirmer la réouverture", key=f'bro_reopen_confirm_{event["id"]}')
    if st.button("Réouvrir", disabled=not confirm, key=f'bro_reopen_{event["id"]}'):
        ok, message = reopen_session(data, event["id"])
        if ok:
            saved(st, data, message)
        st.error(message)
    management(st, data, event, context)


def render_brocante_page(context):
    st = context["st"]
    st.html(CSS)
    data = load_brocantes()
    st.markdown(context["render_page_header"]("Brocante", "Préparer la journée, vendre et suivre la caisse", "🧺"), unsafe_allow_html=True)
    flash = st.session_state.pop("brocante_flash", None)
    if flash:
        st.success(flash)
    st.session_state.setdefault("brocante_view", VIEWS[0])
    view = st.segmented_control("Brocante", VIEWS, key="brocante_view", label_visibility="collapsed") or VIEWS[0]
    active, planned = active_session(data), preparing_session(data)
    relevant = data.get("sessions", []) if view == "Historique" else [e for e in (active, planned) if e]
    if relevant:
        stock = context["ld"]()
        for event in relevant:
            project_event(event, stock)
    if view == "Historique":
        history(st, data, context)
    elif view == "Aujourd’hui":
        if active:
            header(st, active)
            dashboard(st, active, data, actions=True, mobile=bool(context.get("is_mobile_mode", lambda: False)()))
            management(st, data, active, context)
        elif planned:
            preparing(st, data, planned)
            management(st, data, planned, context)
        else:
            create(st, data)
    elif not active:
        st.info("Démarre une brocante depuis Aujourd’hui pour enregistrer des opérations.")
        st.button("Préparer la journée", on_click=go, args=(st, VIEWS[0]))
    elif view in ("Vente", "Échange"):
        from ui.pages.sales import render_sales_page
        header(st, active)
        render_sales_page({**context, "brocante_session": active, "brocante_section": view, "run_html": lambda *a, **k: None})
    elif view == "Rachat":
        header(st, active)
        purchase(st, active, context)
    elif view == "Hors stock":
        header(st, active)
        offstock(st, active, context)
    elif view == "Frais / clôture":
        header(st, active)
        closing(st, data, active)

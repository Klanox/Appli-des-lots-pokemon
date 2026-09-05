"""Home page renderer for Pokestock.

This module contains only Streamlit UI rendering for the Accueil page.
It does not save application data.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import os

import streamlit as st
from ui.inventory_live_search import inventory_live_search
from core.sale_preview import historical_unit_cost_or_none

from services.inventory_ordering import card_matches_inventory_query, sort_inventory_records
from services.stock_history_service import (
    add_stock_annotation,
    delete_stock_annotation,
    record_stock_value,
)


def _filter_stock_points(points, period):
    if period == "Tout":
        return points
    days = {"1 mois": 31, "3 mois": 92, "6 mois": 183, "1 an": 366}.get(period)
    if not days:
        return points
    threshold = datetime.now() - timedelta(days=days)
    filtered = []
    for point in points:
        raw = str(point.get("captured_at") or "")
        try:
            point_date = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if point_date >= threshold:
            filtered.append(point)
    return filtered


def _add_stock_note_from_state():
    comment = str(st.session_state.get("stock_note_comment") or "").strip()
    if not comment:
        return
    add_stock_annotation(st.session_state.get("stock_note_date", date.today()), comment)
    st.session_state["stock_note_comment"] = ""


def _home_card_available_qty(card, card_available_qty_func=None):
    if card_available_qty_func is not None:
        try:
            return max(int(card_available_qty_func(card) or 0), 0)
        except (TypeError, ValueError):
            return 0
    try:
        quantity = int(card.get("quantity", 0) or 0)
        sold = int(card.get("sold_quantity", 0) or 0)
        exchange_out = int(card.get("exchange_out_quantity", 0) or 0)
        stored = int(card.get("stored_quantity", 0) or 0)
    except (TypeError, ValueError):
        return 0
    if card.get("is_collection_keep"):
        return 0
    return max(quantity - sold - exchange_out - stored, 0)


def _home_is_collection_lot(lot):
    name = str(lot.get("nom") or lot.get("name") or "").strip().lower()
    return bool(lot.get("is_collection_system") or lot.get("is_collection_lot") or name == "collection")


def _home_result_key(lot_idx, card_idx, lot_uid="", card_uid=""):
    raw = f"{lot_idx}|{card_idx}|{lot_uid}|{card_uid}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"home_search_{digest}"


def _chunked(items, size):
    for start in range(0, len(items), size):
        yield start // size, items[start:start + size]


def _inject_home_search_grid_styles():
    st.markdown(
        """
        <style>
        [data-testid="stHorizontalBlock"][class*="st-key-search_results_grid_home_row_"],
        [class*="st-key-search_results_grid_home_row_"] > [data-testid="stHorizontalBlock"] {
            display:flex !important;
            flex-direction:row !important;
            flex-wrap:wrap !important;
            justify-content:flex-start !important;
            align-items:flex-start !important;
            gap:.46rem !important;
            width:100% !important;
            max-width:100% !important;
            overflow-x:hidden !important;
        }
        [data-testid="stHorizontalBlock"][class*="st-key-search_results_grid_home_row_"] > [data-testid="stLayoutWrapper"],
        [data-testid="stHorizontalBlock"][class*="st-key-search_results_grid_home_row_"] > [data-testid="column"],
        [class*="st-key-search_results_grid_home_row_"] > [data-testid="stHorizontalBlock"] > [data-testid="stLayoutWrapper"],
        [class*="st-key-search_results_grid_home_row_"] > [data-testid="stHorizontalBlock"] > [data-testid="column"] {
            flex:0 0 calc((100% - 2.3rem) / 6) !important;
            max-width:calc((100% - 2.3rem) / 6) !important;
            min-width:0 !important;
            box-sizing:border-box !important;
        }
        [class*="st-key-search_result_card_home_"] {
            width:100% !important;
            max-width:100% !important;
            min-width:0 !important;
            box-sizing:border-box !important;
        }
        [class*="st-key-search_result_card_home_"] img {
            width:100% !important;
            max-width:100% !important;
            height:auto !important;
        }
        @media (max-width:768px) {
            [data-testid="stHorizontalBlock"][class*="st-key-search_results_grid_home_row_"],
            [class*="st-key-search_results_grid_home_row_"] > [data-testid="stHorizontalBlock"] {
                gap:.3rem !important;
            }
            [data-testid="stHorizontalBlock"][class*="st-key-search_results_grid_home_row_"] > [data-testid="stLayoutWrapper"],
            [data-testid="stHorizontalBlock"][class*="st-key-search_results_grid_home_row_"] > [data-testid="column"],
            [class*="st-key-search_results_grid_home_row_"] > [data-testid="stHorizontalBlock"] > [data-testid="stLayoutWrapper"],
            [class*="st-key-search_results_grid_home_row_"] > [data-testid="stHorizontalBlock"] > [data-testid="column"] {
                flex:0 0 calc((100% - .3rem) / 2) !important;
                max-width:calc((100% - .3rem) / 2) !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _find_home_search_card(cd, result):
    lots = cd.get("lots", []) or []
    lot_uid = result.get("lot_uid")
    card_uid = result.get("card_uid")
    if lot_uid and card_uid:
        for lot_idx, lot in enumerate(lots):
            if str(lot.get("lot_uid") or lot.get("uid") or lot.get("id") or "") != str(lot_uid):
                continue
            for card_idx, card in enumerate(lot.get("cards", []) or []):
                if str(card.get("card_uid") or card.get("uid") or card.get("id") or "") == str(card_uid):
                    return lot_idx, card_idx, card

    lot_idx = result.get("lot_idx")
    card_idx = result.get("card_idx")
    if isinstance(lot_idx, int) and isinstance(card_idx, int):
        try:
            card = lots[lot_idx].get("cards", [])[card_idx]
        except (IndexError, AttributeError):
            return None, None, None
        if card_uid and str(card.get("card_uid") or card.get("uid") or card.get("id") or "") != str(card_uid):
            return None, None, None
        return lot_idx, card_idx, card

    return None, None, None


def render_home_page(
    *,
    sts,
    ld_func,
    fp_func,
    normalize_name_func,
    proxy_img_func,
    render_page_header_func,
    render_kpi_card_func,
    kpi_accents,
    set_current_page_func,
    sd_func=None,
    delete_card_func=None,
    card_available_qty_func=None,
    clear_stats_cache_func=None,
):
    st.markdown(
        render_page_header_func("Tableau de bord", "Vue d'ensemble de votre activité", "📊"),
        unsafe_allow_html=True,
    )

    metrics_main = [
        ("Vendues", str(sts["sold_cards"]), None, "✅"),
        ("En stock", str(sts["remaining_cards"]), None, "📦"),
        ("Valeur stock", fp_func(sts["stock_value"]), None, "💎"),
        ("Chiffre d'affaires", fp_func(sts["total_revenue"]), None, "💰"),
        ("Bénéfice net", fp_func(sts["total_profit"]), fp_func(sts["total_profit"]) if sts["total_profit"] != 0 else None, "📈"),
    ]

    cols = st.columns(len(metrics_main))
    for idx, (label, value, delta, icon) in enumerate(metrics_main):
        with cols[idx]:
            st.metric(label, value, delta=delta)

    c1, c2 = st.columns(2)
    if c1.button("💰 Nouvelle vente", width="stretch", type="primary"):
        set_current_page_func("Vente")
    if c2.button("📦 Gérer les lots", width="stretch"):
        set_current_page_func("Lots")

    st.markdown("---")
    st.markdown(
        render_page_header_func("Évolution de la valeur du stock", "Valeur réelle du stock au fil du temps", "💎"),
        unsafe_allow_html=True,
    )
    stock_history, _ = record_stock_value(sts["stock_value"])
    stock_points = stock_history.get("points", []) or []
    stock_annotations = stock_history.get("annotations", []) or []
    period = st.selectbox(
        "Période",
        ["Tout", "1 an", "6 mois", "3 mois", "1 mois"],
        key="stock_value_history_period",
        label_visibility="collapsed",
    )
    visible_points = _filter_stock_points(stock_points, period)
    if visible_points:
        try:
            import plotly.graph_objects as go
            point_dates = [point.get("captured_at", "") for point in visible_points]
            point_values = [float(point.get("value", 0) or 0) for point in visible_points]
            fig_stock = go.Figure()
            fig_stock.add_trace(go.Scatter(
                x=point_dates,
                y=point_values,
                mode="lines+markers",
                name="Valeur stock",
                line=dict(color="#7c3aed", width=3),
                marker=dict(size=7, color="#7c3aed"),
                fill="tozeroy",
                fillcolor="rgba(124,58,237,0.10)",
                hovertemplate="%{x}<br>Valeur stock : %{y:.2f}€<extra></extra>",
            ))
            annotations_in_range = []
            first_visible = datetime.fromisoformat(str(visible_points[0].get("captured_at", ""))).date()
            last_visible = datetime.fromisoformat(str(visible_points[-1].get("captured_at", ""))).date()
            for annotation in stock_annotations:
                ann_date = str(annotation.get("date") or "")[:10]
                try:
                    ann_dt = datetime.fromisoformat(ann_date).date()
                except ValueError:
                    continue
                if first_visible <= ann_dt <= last_visible:
                    annotations_in_range.append(annotation)
            if annotations_in_range:
                y_top = max(point_values) if point_values else 0
                fig_stock.add_trace(go.Scatter(
                    x=[item.get("date") for item in annotations_in_range],
                    y=[y_top for _ in annotations_in_range],
                    mode="markers",
                    name="Notes",
                    marker=dict(size=11, color="#f59e0b", symbol="diamond"),
                    text=[item.get("comment", "") for item in annotations_in_range],
                    hovertemplate="%{x}<br>%{text}<extra>Note</extra>",
                ))
            fig_stock.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Plus Jakarta Sans", color="#0f172a", size=12),
                legend=dict(orientation="h", y=1.12, font=dict(size=11)),
                margin=dict(l=12, r=12, t=12, b=12),
                xaxis=dict(gridcolor="#e2e8f0", showgrid=True, linecolor="#e2e8f0"),
                yaxis=dict(gridcolor="#e2e8f0", showgrid=True, ticksuffix="€", linecolor="#e2e8f0"),
                height=320,
            )
            st.plotly_chart(fig_stock, width="stretch", key="stock_value_history_chart")
        except ImportError:
            st.line_chart({"Valeur stock": [point.get("value", 0) for point in visible_points]}, width="stretch")
    else:
        st.info("Aucun historique fiable antérieur n'a été trouvé. Le suivi démarre avec la valeur actuelle.")

    with st.expander("+ Ajouter une note", expanded=False):
        note_date = st.date_input("Date", value=date.today(), key="stock_note_date")
        note_comment = st.text_input("Commentaire court", max_chars=180, key="stock_note_comment")
        st.button(
            "Ajouter la note",
            key="stock_note_add",
            disabled=not note_comment.strip(),
            on_click=_add_stock_note_from_state,
        )
        if stock_annotations:
            st.markdown("**Notes enregistrées**")
            for annotation in sorted(stock_annotations, key=lambda item: str(item.get("date") or ""), reverse=True):
                col_note, col_delete = st.columns([5, 1])
                col_note.caption(f"{annotation.get('date', '—')} — {annotation.get('comment', '')}")
                col_delete.button(
                    "Supprimer",
                    key=f"delete_stock_note_{annotation.get('id')}",
                    on_click=delete_stock_annotation,
                    args=(annotation.get("id"),),
                )

    st.markdown("---")
    st.markdown(
        render_page_header_func("Évolution", "Chiffre d'affaires et bénéfice cumulés", "📈"),
        unsafe_allow_html=True,
    )

    all_sales = []
    cd_graph = ld_func()
    total_cost_graph = sum(l.get("prix_achat", 0.) for l in cd_graph.get("lots", []))

    archive_file = "lots_archives.json"
    all_lots_graph = list(cd_graph.get("lots", []))
    if os.path.exists(archive_file):
        try:
            with open(archive_file, "r", encoding="utf-8") as f:
                archives = json.load(f)
                all_lots_graph += archives
                total_cost_graph += sum(l.get("prix_achat", 0.) for l in archives)
        except Exception as e:
            st.warning(f"Erreur lors de la lecture des archives: {e}")
            pass

    for lot_g in all_lots_graph:
        for v in lot_g.get("ventes", []):
            if v.get("date"):
                all_sales.append({"date": v["date"][:10], "amount": v.get("price", 0.)})
        for c in lot_g.get("cards", []):
            for s in c.get("sold_entries", []):
                if s.get("date"):
                    all_sales.append({"date": s["date"][:10], "amount": s.get("price", 0.)})

    if all_sales:
        daily = defaultdict(float)
        for s in all_sales:
            daily[s["date"]] += s["amount"]

        dates_sorted = sorted(daily.keys())
        ca_cumul = []
        running = 0.
        for d in dates_sorted:
            running += daily[d]
            ca_cumul.append(running)

        benef_cumul = [ca - total_cost_graph for ca in ca_cumul]

        try:
            import plotly.graph_objects as go
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates_sorted, y=ca_cumul,
                mode='lines+markers', name='CA cumulé',
                line=dict(color='#3b4cca', width=3),
                marker=dict(size=6),
                fill='tozeroy', fillcolor='rgba(59,76,202,0.1)'
            ))
            fig.add_trace(go.Scatter(
                x=dates_sorted, y=benef_cumul,
                mode='lines+markers', name='Bénéfice cumulé',
                line=dict(color='#22c55e', width=3),
                marker=dict(size=6),
                fill='tozeroy', fillcolor='rgba(34,197,94,0.1)'
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="#ee1515", line_width=1, opacity=0.5)
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font=dict(family='Plus Jakarta Sans', color='#0f172a', size=12),
                legend=dict(orientation='h', y=1.12, font=dict(size=11)),
                margin=dict(l=12, r=12, t=12, b=12),
                xaxis=dict(gridcolor='#e2e8f0', showgrid=True, linecolor='#e2e8f0'),
                yaxis=dict(gridcolor='#e2e8f0', showgrid=True, ticksuffix='€', linecolor='#e2e8f0'),
                height=360,
            )
            st.plotly_chart(fig, width="stretch", key="home_sales_profit_chart")
        except ImportError:
            col_g1, col_g2 = st.columns(2)
            col_g1.metric("CA cumulé", fp_func(ca_cumul[-1]) if ca_cumul else "0.00€")
            col_g2.metric("Bénéfice cumulé", fp_func(benef_cumul[-1]) if benef_cumul else "0.00€")
    else:
        st.info("Aucune vente enregistrée pour afficher le graphique.")

    st.markdown("---")
    st.markdown(
        render_page_header_func("Recherche globale", "Trouver une carte dans tous les lots", "🔍"),
        unsafe_allow_html=True,
    )
    search_global = inventory_live_search(
        "🔍 Recherche", key="global_search_live",
        placeholder="Chercher une carte dans tous les lots...", collapsed=False,
    )
    if st.session_state.pop("home_card_deleted_toast", False):
        st.toast("Carte supprimée")

    if search_global.strip():
        cd_search = cd_graph
        results_found = []

        all_lots_search = [
            (lot_idx, lot, "actif")
            for lot_idx, lot in enumerate(cd_search.get("lots", []) or [])
            if not _home_is_collection_lot(lot)
        ]

        for lot_idx, lot_s, lot_type in all_lots_search:
            for ci, card in enumerate(lot_s.get("cards", [])):
                stock = _home_card_available_qty(card, card_available_qty_func)
                if stock <= 0:
                    continue
                if card_matches_inventory_query(card, search_global):
                    lot_uid = lot_s.get("lot_uid") or lot_s.get("uid") or lot_s.get("id") or ""
                    card_uid = card.get("card_uid") or card.get("uid") or card.get("id") or ""
                    results_found.append({
                        "card": card,
                        "lot": lot_s,
                        "lot_idx": lot_idx,
                        "card_idx": ci,
                        "lot_uid": lot_uid,
                        "card_uid": card_uid,
                        "result_key": _home_result_key(lot_idx, ci, lot_uid, card_uid),
                        "lot_name": lot_s["nom"],
                        "lot_type": lot_type,
                        "stock": stock,
                    })

        results_found = sort_inventory_records(results_found)

        if results_found:
            _inject_home_search_grid_styles()
            st.caption(f"{len(results_found)} résultat(s) pour « {search_global} »")
            for row_index, row in _chunked(results_found, 6):
                with st.container(key=f"search_results_grid_home_row_{row_index}", horizontal=True, gap="small"):
                    for res in row:
                        with st.container(key=f"search_result_card_home_{res['result_key']}"):
                            if res["card"].get("image_url"):
                                st.image(proxy_img_func(res["card"]["image_url"]), width="stretch")
                            st.markdown(f"**{res['card']['name']}**")
                            st.caption(f"{res['card']['set']} · #{res['card']['number']}")
                            st.caption(f"📦 {res['lot_name']} ({res['lot_type']})")
                            stock_color = "#22c55e" if res["stock"] > 0 else "#94a3b8"
                            st.markdown(f'<span style="color:{stock_color};font-weight:700;font-size:0.85rem;">{"✅ Stock : "+str(res["stock"]) if res["stock"] > 0 else "❌ Épuisé"}</span>', unsafe_allow_html=True)
                            purchase_cost = historical_unit_cost_or_none(res["lot"], res["card"])
                            purchase_label = fp_func(purchase_cost) if purchase_cost is not None else "—"
                            st.caption(f"Prix : {fp_func(res['card'].get('suggested_price', 0))} · Achat : {purchase_label}")
                            edit_key = f"{res['result_key']}_edit_price"
                            value_key = f"{res['result_key']}_price_value"
                            save_key = f"{res['result_key']}_save_price"
                            cancel_key = f"{res['result_key']}_cancel_price"
                            open_key = f"{res['result_key']}_open_price"
                            delete_confirm_key = f"{res['result_key']}_confirm_delete"
                            delete_open_key = f"{res['result_key']}_open_delete"
                            delete_yes_key = f"{res['result_key']}_yes_delete"
                            delete_no_key = f"{res['result_key']}_no_delete"

                            if st.session_state.get(edit_key):
                                current_price = float(res["card"].get("suggested_price", 0) or 0)
                                st.number_input(
                                    "Nouveau prix (€)",
                                    min_value=0.0,
                                    value=current_price,
                                    step=0.5,
                                    format="%.2f",
                                    key=value_key,
                                )
                                btn_save, btn_cancel = st.columns(2)
                                if btn_save.button("Enregistrer", key=save_key, width="stretch"):
                                    if sd_func is None:
                                        st.error("Sauvegarde indisponible depuis cette vue.")
                                    else:
                                        cd_update = ld_func()
                                        _, _, target_card = _find_home_search_card(cd_update, res)
                                        if target_card is None:
                                            st.error("Carte introuvable dans son lot.")
                                        else:
                                            new_price = round(float(st.session_state.get(value_key) or 0), 2)
                                            old_price = round(float(target_card.get("suggested_price", 0) or 0), 2)
                                            target_card["suggested_price"] = new_price
                                            if new_price != old_price:
                                                target_card.setdefault("price_history", []).append({
                                                    "date": datetime.now().isoformat()[:10],
                                                    "price": new_price,
                                                })
                                            sd_func(cd_update)
                                            if clear_stats_cache_func is not None:
                                                clear_stats_cache_func()
                                            st.session_state[edit_key] = False
                                            st.success("Prix mis à jour.")
                                            st.rerun()
                                if btn_cancel.button("Annuler", key=cancel_key, width="stretch"):
                                    st.session_state[edit_key] = False
                                    st.rerun()
                            elif st.button("Modifier le prix", key=open_key, width="stretch"):
                                st.session_state[edit_key] = True
                                st.rerun()

                            if st.session_state.get(delete_confirm_key):
                                card_name = res["card"].get("name") or "Carte"
                                card_number = res["card"].get("number") or "N/A"
                                total_qty = int(res["card"].get("quantity", 0) or 0)
                                st.warning("Supprimer cette carte ?")
                                st.caption(
                                    f"{card_name} · #{card_number} · {res['lot_name']} · "
                                    f"Qté actuelle : {total_qty}"
                                )
                                delete_cols = st.columns(2)
                                if delete_cols[0].button("Annuler", key=delete_no_key, width="stretch"):
                                    st.session_state[delete_confirm_key] = False
                                    st.rerun()
                                if delete_cols[1].button("Supprimer", key=delete_yes_key, type="primary", width="stretch"):
                                    if delete_card_func is None:
                                        st.error("Suppression indisponible depuis cette vue.")
                                    else:
                                        ok, msg = delete_card_func(
                                            res["lot_idx"],
                                            res["card_idx"],
                                            lot_uid=res.get("lot_uid"),
                                            card_uid=res.get("card_uid"),
                                        )
                                        if ok:
                                            if clear_stats_cache_func is not None:
                                                clear_stats_cache_func()
                                            st.session_state[delete_confirm_key] = False
                                            st.session_state["home_card_deleted_toast"] = True
                                            st.rerun()
                                        else:
                                            st.error(msg or "Suppression impossible.")
                            elif st.button("🗑️ Supprimer", key=delete_open_key, width="stretch"):
                                st.session_state[delete_confirm_key] = True
                                st.session_state[edit_key] = False
                                st.rerun()
        else:
            st.info(f"Aucune carte trouvée pour « {search_global} »")
    elif not search_global:
        st.caption("Saisis un caractère pour lancer la recherche globale.")

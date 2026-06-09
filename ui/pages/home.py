"""Home page renderer for Pokestock.

This module contains only Streamlit UI rendering for the Accueil page.
It does not save application data.
"""

from collections import defaultdict
import json
import os

import streamlit as st


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

    c1, c2, c3, c4, c5 = st.columns(5)
    cols = [c1, c2, c3, c4, c5]
    for idx, (col, (label, value, delta, icon)) in enumerate(zip(cols, metrics_main)):
        with col:
            st.markdown(
                render_kpi_card_func(
                    label,
                    value,
                    delta=delta,
                    accent=kpi_accents[idx % len(kpi_accents)],
                    icon=icon,
                ),
                unsafe_allow_html=True,
            )

    c1, c2 = st.columns(2)
    c1.button("💰 Nouvelle vente", width="stretch", type="primary", on_click=set_current_page_func, args=("Vente",))
    c2.button("📦 Gérer les lots", width="stretch", on_click=set_current_page_func, args=("Lots",))

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
            st.plotly_chart(fig, width="stretch")
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
    search_global = st.text_input("🔍 Recherche", placeholder="Chercher une carte dans tous les lots...", key="global_search")

    if search_global and len(search_global) >= 2:
        cd_search = ld_func()
        results_found = []

        all_lots_search = [(l, "actif") for l in cd_search.get("lots", [])]
        if os.path.exists("lots_archives.json"):
            try:
                with open("lots_archives.json", "r", encoding="utf-8") as f:
                    for l in json.load(f):
                        all_lots_search.append((l, "archivé"))
            except:
                pass

        for lot_s, lot_type in all_lots_search:
            for ci, card in enumerate(lot_s.get("cards", [])):
                if normalize_name_func(search_global) in normalize_name_func(card.get("name", "")):
                    results_found.append({
                        "card": card,
                        "lot_name": lot_s["nom"],
                        "lot_type": lot_type,
                        "stock": card["quantity"] - card.get("sold_quantity", 0)
                    })

        if results_found:
            st.caption(f"{len(results_found)} résultat(s) pour « {search_global} »")
            COLS_S = 8
            for row_start in range(0, len(results_found), COLS_S):
                cols_s = st.columns(COLS_S)
                for col_idx, res in enumerate(results_found[row_start:row_start + COLS_S]):
                    with cols_s[col_idx]:
                        if res["card"].get("image_url"):
                            st.image(proxy_img_func(res["card"]["image_url"]), width="stretch")
                        st.markdown(f"**{res['card']['name']}**")
                        st.caption(f"{res['card']['set']} · #{res['card']['number']}")
                        st.caption(f"📦 {res['lot_name']} ({res['lot_type']})")
                        stock_color = "#22c55e" if res["stock"] > 0 else "#94a3b8"
                        st.markdown(f'<span style="color:{stock_color};font-weight:700;font-size:0.85rem;">{"✅ Stock : "+str(res["stock"]) if res["stock"] > 0 else "❌ Épuisé"}</span>', unsafe_allow_html=True)
                        st.caption(f"💰 {fp_func(res['card'].get('suggested_price', 0))}")
        else:
            st.info(f"Aucune carte trouvée pour « {search_global} »")

"""Statistics page renderer for Pokestock.

This module contains the existing Streamlit UI rendering for the Statistiques page.
It preserves the current calculations and monthly_goals.json behavior.
"""

from collections import defaultdict
import datetime as dt_module
import json
import os
from datetime import datetime

import streamlit as st


def render_statistics_page(
    *,
    ld_func,
    safe_write_json_func,
    calc_cout_lot_func,
    effective_purchase_price_func,
    proxy_img_func,
    lots_archives_path="lots_archives.json",
    monthly_goals_path="monthly_goals.json",
):
    import plotly.graph_objects as go

    st.markdown("## 📊 Statistiques & Défis")

    cd = ld_func()
    now = datetime.now()
    current_month = now.strftime("%Y-%m")
    MOIS_FR = {1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
               7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"}
    def mois_label(dt):
        return f"{MOIS_FR[dt.month]} {dt.year}"

    current_month_label = mois_label(now)
    with st.expander("⚙️ Calcul du bénéfice", expanded=False):
        st.caption("Le coût d'achat d'une carte vendue est calculé avec sa cote au moment de la vente, la valeur estimée totale de son lot et le prix d'achat du lot.")
        st.markdown("**Formule :** coût carte = cote carte vendue ÷ valeur estimée du lot × prix d'achat du lot.")
        st.caption("Pour les lots mixtes, la formule utilise directement prix réel payé ÷ valeur totale du lot, afin de ne pas double compter les cartes déjà vendues.")
        st.caption("Le bénéfice utilise ensuite le prix réellement vendu, donc les négociations sont bien prises en compte.")

    # ── Collecter TOUTES les ventes : sold_entries (vente rapide) + ventes[] (vente en lot) ──
    # On exclut les "ventes initiales" créées à la création du lot (is_lot_sale=True)
    all_sales = []
    all_lots = list(cd.get("lots", []))
    archives_list = []
    if os.path.exists(lots_archives_path):
        with open(lots_archives_path, "r", encoding="utf-8") as f:
            archives_list = json.load(f)

    for lot_idx_s, lot in enumerate(all_lots + archives_list):
        real_lot_idx = lot_idx_s if lot_idx_s < len(all_lots) else None
        ventes_avec_cout, valeur_est = calc_cout_lot_func(lot, lot_idx=real_lot_idx)

        # Ventes en lot
        for v in lot.get("ventes", []):
            if v.get("is_lot_sale") or v.get("is_exchange_benefit"):
                continue
            try:
                d = datetime.fromisoformat(v["date"])
                price = float(v.get("price", 0))
                qty = int(v.get("quantity", 1))
                if lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
                    cout_v = (price / float(lot.get("valeur_totale", 1.) or 1.)) * float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
                else:
                    cout_v = (price / (valeur_est or 1.0)) * effective_purchase_price_func(lot)
                all_sales.append({
                    "date": d, "month": d.strftime("%Y-%m"),
                    "price": price, "quantity": qty,
                    "card_name": v.get("card_name", "Vente lot"),
                    "card_image": v.get("card_image", ""),
                    "lot": lot.get("nom", "?"),
                    "unit_price": price / max(qty, 1),
                    "cost": cout_v, "benef": price - cout_v,
                    "cote": price,
                })
            except:
                pass

        # Ventes rapides
        for card, se, cout_total in ventes_avec_cout:
            if se.get("is_exchange"):
                continue
            try:
                d = datetime.fromisoformat(se["date"])
                qty = int(se.get("quantity", 1))
                price = float(se.get("price", 0))
                card_img = card.get("image_url", "") or card.get("image", "")
                cote_total = float(se.get("suggested_price_at_sale", 0.) or card.get("suggested_price", 0.) or 0.) * qty
                if cote_total <= 0:
                    cote_total = price
                all_sales.append({
                    "date": d, "month": d.strftime("%Y-%m"),
                    "price": price, "quantity": qty,
                    "card_name": se.get("card_name", card.get("name", "?")),
                    "card_image": card_img,
                    "lot": lot.get("nom", "?"),
                    "unit_price": price / max(qty, 1),
                    "cost": cout_total,
                    "benef": price - cout_total,
                    "cote": cote_total,
                })
            except:
                pass

    # ── CA, quantités et bénéfice par mois ──
    ca_by_month = defaultdict(float)
    qty_by_month = defaultdict(int)
    benef_by_month = defaultdict(float)

    for s in all_sales:
        ca_by_month[s["month"]] += s["price"]
        qty_by_month[s["month"]] += s["quantity"]
        benef_by_month[s["month"]] += s.get("benef", s["price"] - s.get("cost", 0))

    months_sorted = sorted(ca_by_month.keys())

    if not months_sorted:
        st.info("Aucune vente enregistrée pour le moment. Commence à vendre des cartes pour voir tes statistiques !")
        st.stop()

    import datetime as dt_module
    prev_month = (now.replace(day=1) - dt_module.timedelta(days=1)).strftime("%Y-%m")
    ca_this = ca_by_month.get(current_month, 0)
    ca_prev = ca_by_month.get(prev_month, 0)
    qty_this = qty_by_month.get(current_month, 0)
    qty_prev = qty_by_month.get(prev_month, 0)
    benef_this = benef_by_month.get(current_month, 0)
    benef_prev = benef_by_month.get(prev_month, 0)

    def pct_change(new, old):
        if old == 0:
            return None
        return ((new - old) / old) * 100

    pct_ca = pct_change(ca_this, ca_prev)
    pct_qty = pct_change(qty_this, qty_prev)

    # ─────────────────────────────────────────────
    # SECTION 1 : KPIs du mois courant
    # ─────────────────────────────────────────────
    st.markdown(f"### 📅 {current_month_label}")

    k1, k2, k3, k4 = st.columns(4)

    def delta_str(pct):
        if pct is None: return None
        return f"{'+' if pct >= 0 else ''}{pct:.1f}% vs mois préc."

    k1.metric("💰 CA du mois", f"{ca_this:.2f}€", delta_str(pct_ca))
    k2.metric("🃏 Cartes vendues", str(qty_this), delta_str(pct_qty))

    # Bénéfice du mois (CA × part - coût × part)
    pct_benef = pct_change(benef_this, benef_prev)
    k3.metric("💎 Bénéfice estimé", f"{benef_this:.2f}€", delta_str(pct_benef))

    # Prix moyen par carte
    avg_price = (ca_this / qty_this) if qty_this > 0 else 0
    avg_price_prev = (ca_prev / qty_prev) if qty_prev > 0 else 0
    pct_avg = pct_change(avg_price, avg_price_prev)
    k4.metric("📈 Prix moyen / carte", f"{avg_price:.2f}€", delta_str(pct_avg))

    st.markdown("---")

    # ─────────────────────────────────────────────
    # SECTION 2 : Graphiques
    # ─────────────────────────────────────────────
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.markdown("#### 📊 CA par mois")
        months_labels = [mois_label(datetime.strptime(m, "%Y-%m")) for m in months_sorted]
        ca_values = [ca_by_month[m] for m in months_sorted]
        colors = ["#3b4cca" if m != current_month else "#ffcb05" for m in months_sorted]
        fig_bar = go.Figure(go.Bar(
            x=months_labels, y=ca_values,
            marker_color=colors,
            text=[f"{v:.0f}€" for v in ca_values],
            textposition="outside",
            hovertemplate="%{x}<br>CA : %{y:.2f}€<extra></extra>"
        ))
        fig_bar.update_layout(
            height=300, margin=dict(t=20, b=0, l=0, r=0),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(gridcolor="#f1f5f9", showgrid=True),
            xaxis=dict(showgrid=False),
            showlegend=False,
        )
        st.plotly_chart(fig_bar, width="stretch")

    with col_g2:
        st.markdown("#### 🃏 Cartes vendues par mois")
        qty_values = [qty_by_month[m] for m in months_sorted]
        fig_qty = go.Figure(go.Bar(
            x=months_labels, y=qty_values,
            marker_color=["#10b981" if m != current_month else "#f59e0b" for m in months_sorted],
            text=[str(v) for v in qty_values],
            textposition="outside",
            hovertemplate="%{x}<br>Cartes : %{y}<extra></extra>"
        ))
        fig_qty.update_layout(
            height=300, margin=dict(t=20, b=0, l=0, r=0),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(gridcolor="#f1f5f9", showgrid=True),
            xaxis=dict(showgrid=False),
            showlegend=False,
        )
        st.plotly_chart(fig_qty, width="stretch")

    st.markdown("#### 💎 Bénéfice par mois")
    benef_values = [benef_by_month[m] for m in months_sorted]
    fig_benef_month = go.Figure(go.Bar(
        x=months_labels,
        y=benef_values,
        marker_color=["#10b981" if v >= 0 else "#ef4444" for v in benef_values],
        text=[f"{v:.0f}€" for v in benef_values],
        textposition="outside",
        hovertemplate="%{x}<br>Bénéfice : %{y:.2f}€<extra></extra>",
    ))
    fig_benef_month.update_layout(
        height=280, margin=dict(t=20, b=0, l=0, r=0),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(gridcolor="#f1f5f9", showgrid=True, zeroline=True, zerolinecolor="#cbd5e1"),
        xaxis=dict(showgrid=False),
        showlegend=False,
    )
    st.plotly_chart(fig_benef_month, width="stretch")

    with st.expander("🔎 Détail du bénéfice du mois"):
        detail_rows = []
        for s in sorted([x for x in all_sales if x["month"] == current_month], key=lambda x: x["date"], reverse=True):
            detail_rows.append({
                "Date": s["date"].strftime("%d/%m/%Y"),
                "Carte": s.get("card_name", ""),
                "Lot": s.get("lot", ""),
                "Vendu": round(float(s.get("price", 0)), 2),
                "Cote utilisée": round(float(s.get("cote", s.get("price", 0))), 2),
                "Coût estimé": round(float(s.get("cost", 0)), 2),
                "Bénéfice": round(float(s.get("benef", 0)), 2),
            })
        st.dataframe(detail_rows, width="stretch", hide_index=True)
        st.caption("Calcul actuel : coût = cote vendue ÷ valeur estimée du lot × prix d'achat du lot. Pour les lots mixtes : coût = cote vendue ÷ valeur totale du lot × prix réel payé.")

    # Graphique tendance CA (courbe lissée)
    if len(months_sorted) >= 2:
        st.markdown("#### 📈 Tendance du CA — évolution mensuelle")
        fig_line = go.Figure()
        fig_line.add_trace(go.Scatter(
            x=months_labels, y=ca_values,
            mode="lines+markers+text",
            line=dict(color="#3b4cca", width=3),
            marker=dict(size=10, color=colors, line=dict(width=2, color="white")),
            text=[f"{v:.0f}€" for v in ca_values],
            textposition="top center",
            fill="tozeroy",
            fillcolor="rgba(59,76,202,0.08)",
            hovertemplate="%{x}<br>CA : %{y:.2f}€<extra></extra>"
        ))
        fig_line.update_layout(
            height=250, margin=dict(t=20, b=0, l=0, r=0),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(gridcolor="#f1f5f9"),
            xaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_line, width="stretch")

    # ── CA et bénéfice par lot — mois courant ──
    st.markdown("---")
    pie1, pie2 = st.columns(2)

    ca_by_lot_month = defaultdict(float)
    benef_by_lot_month = defaultdict(float)
    for s in all_sales:
        if s["month"] == current_month:
            ca_by_lot_month[s["lot"]] += s["price"]
            benef_by_lot_month[s["lot"]] += s.get("benef", s["price"] - s.get("cost", 0))

    PALETTE = ["#3b4cca","#ffcb05","#10b981","#f59e0b","#8b5cf6","#ef4444"]

    with pie1:
        st.markdown("#### 🗂️ CA par lot — ce mois")
        top_ca = sorted(ca_by_lot_month.items(), key=lambda x: x[1], reverse=True)[:6]
        if top_ca:
            names_ca, vals_ca = zip(*top_ca)
            fig_ca = go.Figure(go.Pie(
                labels=names_ca, values=vals_ca, hole=0.4,
                marker_colors=PALETTE,
                textinfo="percent+label",
                hovertemplate="%{label}<br>CA : %{value:.2f}€<extra></extra>"
            ))
            fig_ca.update_layout(height=280, margin=dict(t=10,b=0,l=0,r=0),
                                 paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
            st.plotly_chart(fig_ca, width="stretch")
        else:
            st.info("Aucune vente ce mois.")

    with pie2:
        st.markdown("#### 💎 Bénéfice par lot — ce mois")
        top_benef = sorted(benef_by_lot_month.items(), key=lambda x: x[1], reverse=True)[:8]
        if top_benef:
            names_b = [t[0] for t in top_benef]
            vals_b = [t[1] for t in top_benef]
            colors_b = ["#10b981" if v >= 0 else "#ef4444" for v in vals_b]
            fig_benef = go.Figure(go.Bar(
                x=vals_b,
                y=names_b,
                orientation="h",
                marker_color=colors_b,
                text=[f"{v:+.1f}€" for v in vals_b],
                textposition="outside",
                hovertemplate="%{y}<br>Bénéfice : %{x:.2f}€<extra></extra>",
            ))
            fig_benef.update_layout(
                height=280, margin=dict(t=10, b=0, l=0, r=60),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=True, gridcolor="#f1f5f9", zeroline=True, zerolinecolor="#cbd5e1", zerolinewidth=2),
                yaxis=dict(showgrid=False),
                showlegend=False,
            )
            st.plotly_chart(fig_benef, width="stretch")
        else:
            st.info("Aucune donnée de bénéfice ce mois.")

    # ─────────────────────────────────────────────
    # SECTION 3 : DÉFIS MENSUELS
    # ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🎯 Défis du mois")

    # ── Chargement du fichier objectifs ──
    GOALS_FILE = monthly_goals_path
    if os.path.exists(GOALS_FILE):
        with open(GOALS_FILE, "r", encoding="utf-8") as f:
            goals_data = json.load(f)
    else:
        goals_data = {}

    # ── Auto-génération des objectifs si le mois n'en a pas encore ──
    # Logique : on prend les données réelles du mois précédent et on ajoute +15%
    PROGRESSION_RATE = 0.15  # +15% par mois automatiquement
    if current_month not in goals_data:
        prev_ca_real = ca_by_month.get(prev_month, 0)
        prev_qty_real = qty_by_month.get(prev_month, 0)
        prev_avg_real = (prev_ca_real / prev_qty_real) if prev_qty_real > 0 else 0

        if prev_ca_real > 0:
            prev_benef_real = benef_by_month.get(prev_month, 0)
            auto_ca = round(prev_ca_real * (1 + PROGRESSION_RATE), 2)
            auto_qty = max(1, round(prev_qty_real * (1 + PROGRESSION_RATE)))
            auto_benef = round(prev_benef_real * (1 + PROGRESSION_RATE), 2) if prev_benef_real > 0 else round(auto_ca * 0.3, 2)
            goals_data[current_month] = {
                "ca_target": auto_ca,
                "qty_target": auto_qty,
                "benef_target": auto_benef,
                "auto_generated": True,
                "based_on": prev_month,
            }
        else:
            mois_avec_data = [m for m in months_sorted if m < current_month and ca_by_month.get(m, 0) > 0]
            if mois_avec_data:
                ref_month = mois_avec_data[-1]
                ref_ca = ca_by_month.get(ref_month, 100)
                ref_qty = qty_by_month.get(ref_month, 20)
                ref_benef = benef_by_month.get(ref_month, ref_ca * 0.3)
                goals_data[current_month] = {
                    "ca_target": round(ref_ca * (1 + PROGRESSION_RATE), 2),
                    "qty_target": max(1, round(ref_qty * (1 + PROGRESSION_RATE))),
                    "benef_target": round(ref_benef * (1 + PROGRESSION_RATE), 2),
                    "auto_generated": True,
                    "based_on": ref_month,
                }
            else:
                goals_data[current_month] = {"ca_target": 100.0, "qty_target": 20, "benef_target": 30.0, "auto_generated": False}
        safe_write_json_func(GOALS_FILE, goals_data)

    month_goals = goals_data[current_month]

    # ── Affichage info auto-génération ──
    if month_goals.get("auto_generated"):
        ref = month_goals.get("based_on", "")
        try:
            ref_label = mois_label(datetime.strptime(ref, "%Y-%m"))
        except:
            ref_label = ref
        st.info(f"🤖 Objectifs générés automatiquement (+{int(PROGRESSION_RATE*100)}% par rapport à **{ref_label}**). Tu peux les ajuster ci-dessous.")

    # ── Formulaire modification manuelle ──
    with st.expander("⚙️ Modifier mes objectifs du mois"):
        gc1, gc2, gc3 = st.columns(3)
        new_ca_t = gc1.number_input("🎯 Objectif CA (€)", 0., 99999., value=float(month_goals.get("ca_target", 100.)), step=10.)
        new_qty_t = gc2.number_input("🎯 Cartes à vendre", 0, 9999, value=int(month_goals.get("qty_target", 20)), step=5)
        new_benef_t = gc3.number_input("🎯 Objectif bénéfice (€)", 0., 99999., value=float(month_goals.get("benef_target", 30.)), step=10.)
        if st.button("💾 Sauvegarder les objectifs"):
            goals_data[current_month] = {
                "ca_target": new_ca_t,
                "qty_target": new_qty_t,
                "benef_target": new_benef_t,
                "auto_generated": False,
            }
            safe_write_json_func(GOALS_FILE, goals_data)
            st.success("✅ Objectifs mis à jour !")
            st.rerun()

    ca_target = month_goals.get("ca_target", 100.)
    qty_target = month_goals.get("qty_target", 20)
    benef_target = month_goals.get("benef_target", ca_target * 0.3)

    def render_challenge(label, current, target, unit="€", icon="🎯", color="#3b4cca", motivation=""):
        pct = min((current / target * 100) if target > 0 else 0, 100)
        done = pct >= 100
        bar_color = "#10b981" if done else color
        emoji = "🏆" if done else icon
        val_fmt = f"{current:.0f}" if unit == "" else f"{current:.2f}"
        tgt_fmt = f"{target:.0f}"
        status = "ACCOMPLI !" if done else f"{val_fmt}{unit} / {tgt_fmt}{unit}"
        remaining = max(0, target - current)
        msg = "✅ Objectif atteint, bravo !" if done else motivation.format(remaining=f"{remaining:.1f}{unit}")

        st.markdown(f"""
        <div style="background:white;border-radius:16px;padding:1.2rem 1.5rem;margin-bottom:1rem;
                    border:2px solid {'#10b981' if done else '#e2e8f0'};
                    box-shadow:{'0 4px 12px rgba(16,185,129,0.15)' if done else '0 2px 8px rgba(0,0,0,0.06)'};">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem;">
            <span style="font-size:1rem;font-weight:700;color:#1e293b;">{emoji} {label}</span>
            <span style="font-size:0.95rem;font-weight:800;color:{bar_color};">{status}</span>
          </div>
          <div style="background:#f1f5f9;border-radius:99px;height:14px;overflow:hidden;">
            <div style="height:100%;width:{pct:.1f}%;background:{'linear-gradient(90deg,#10b981,#34d399)' if done else f'linear-gradient(90deg,{color},{color}cc)'};
                        border-radius:99px;"></div>
          </div>
          <div style="margin-top:0.5rem;font-size:0.82rem;color:{'#10b981' if done else '#64748b'};">{msg}</div>
        </div>
        """, unsafe_allow_html=True)

    render_challenge(
        "Chiffre d'affaires du mois", ca_this, ca_target, "€", "💰", "#3b4cca",
        "Plus que {remaining} à réaliser pour atteindre ton objectif, tu y es presque !"
    )
    render_challenge(
        "Cartes vendues", float(qty_this), float(qty_target), "", "🃏", "#8b5cf6",
        "Il te reste {remaining} cartes à vendre ce mois-ci, allez !"
    )
    render_challenge(
        "Bénéfice du mois", benef_this, benef_target, "€", "💎", "#10b981",
        "Plus que {remaining} de bénéfice à réaliser, continue !"
    )

    # ─────────────────────────────────────────────
    # SECTION 4 : RECORDS & PALMARES
    # ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🏅 Records & Palmarès")

    rec1, rec2, rec3 = st.columns(3)

    # Meilleur mois CA
    best_month = max(ca_by_month, key=ca_by_month.get) if ca_by_month else None
    if best_month:
        bm_label = mois_label(datetime.strptime(best_month, "%Y-%m"))
        rec1.metric("🥇 Meilleur mois (CA)", bm_label, f"{ca_by_month[best_month]:.2f}€")

    # Meilleur mois quantité
    best_qty_month = max(qty_by_month, key=qty_by_month.get) if qty_by_month else None
    if best_qty_month:
        bqm_label = mois_label(datetime.strptime(best_qty_month, "%Y-%m"))
        rec2.metric("🃏 Plus de ventes", bqm_label, f"{qty_by_month[best_qty_month]} cartes")

    # CA total cumulé
    total_ca = sum(ca_by_month.values())
    rec3.metric("💎 CA total cumulé", f"{total_ca:.2f}€", f"{len(all_sales)} ventes au total")

    # ── Carte la plus chère vendue ce mois ──
    sales_this_month = [s for s in all_sales if s["month"] == current_month]
    if sales_this_month:
        best_sale = max(sales_this_month, key=lambda s: s["unit_price"])
        st.markdown("---")
        st.markdown("#### 🌟 Meilleure vente du mois")
        img_col, info_col = st.columns([1, 3])
        with img_col:
            img_url = best_sale.get("card_image", "")
            if img_url:
                st.markdown(f'<img src="{proxy_img_func(img_url)}" style="width:100%;border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,0.15);">', unsafe_allow_html=True)
            else:
                st.markdown('<div style="width:100%;aspect-ratio:0.71;background:#f1f5f9;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:2rem;">🃏</div>', unsafe_allow_html=True)
        with info_col:
            st.markdown(f"""
            <div style="padding:1rem;">
              <div style="font-size:1.3rem;font-weight:800;color:#1e293b;">{best_sale['card_name']}</div>
              <div style="font-size:0.9rem;color:#64748b;margin-top:0.3rem;">Lot : {best_sale['lot']}</div>
              <div style="font-size:2rem;font-weight:900;color:#3b4cca;margin-top:0.5rem;">{best_sale['unit_price']:.2f}€</div>
              <div style="font-size:0.85rem;color:#94a3b8;">Vendue le {best_sale['date'].strftime('%d/%m/%Y')}</div>
            </div>
            """, unsafe_allow_html=True)

    # Streak : combien de mois consécutifs avec des ventes
    streak = 0
    check_m = now
    for _ in range(24):
        mk = check_m.strftime("%Y-%m")
        if mk in ca_by_month and ca_by_month[mk] > 0:
            streak += 1
            check_m = (check_m.replace(day=1) - dt_module.timedelta(days=1))
        else:
            break

    # Message de motivation dynamique
    if ca_this == 0:
        motivation_msg = "💤 Aucune vente ce mois-ci... C'est le moment de sortir tes meilleures cartes !"
        motivation_color = "#64748b"
    elif pct_ca and pct_ca > 20:
        motivation_msg = f"🚀 En feu ce mois-ci ! +{pct_ca:.0f}% par rapport au mois dernier, continue comme ça !"
        motivation_color = "#10b981"
    elif pct_ca and pct_ca < -20:
        motivation_msg = f"📉 Mois un peu calme... {abs(pct_ca):.0f}% de moins que le mois dernier. Relance la machine !"
        motivation_color = "#f59e0b"
    else:
        motivation_msg = f"👍 Mois régulier — {streak} mois consécutif{'s' if streak > 1 else ''} avec des ventes !"
        motivation_color = "#3b4cca"

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{motivation_color}15,{motivation_color}05);
                border-left:4px solid {motivation_color};border-radius:12px;
                padding:1rem 1.5rem;margin-top:1.5rem;font-size:1.05rem;font-weight:600;color:{motivation_color};">
        {motivation_msg}
    </div>
    """, unsafe_allow_html=True)

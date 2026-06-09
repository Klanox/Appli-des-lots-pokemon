"""History page renderer for Pokestock.

This module contains the existing Streamlit UI rendering for the Historique page.
It keeps the same filters, sorting, progressive display and calculations.
"""

import json
import os
from datetime import datetime

import streamlit as st


def render_history_page(
    *,
    ld_func,
    calc_cout_lot_func,
    effective_purchase_price_func,
    normalize_name_func,
    proxy_img_func,
    render_page_header_func,
    run_html_func,
    lots_archives_path="lots_archives.json",
):
    st.markdown(
        render_page_header_func("Historique des ventes", "Toutes vos transactions et leur rentabilité", "📋"),
        unsafe_allow_html=True,
    )
    
    cd_hist = ld_func()
    
    # ── Construire l'historique enrichi avec coût d'achat par carte ──
    hist_enriched = []
    
    archives_hist = []
    if os.path.exists(lots_archives_path):
        with open(lots_archives_path,"r",encoding="utf-8") as f:
            archives_hist = json.load(f)
    
    all_lots_hist = cd_hist.get("lots",[])
    for lot_idx_h, lot in enumerate(all_lots_hist + archives_hist):
        prix_lot = float(lot.get("prix_achat", 0.))
        real_idx = lot_idx_h if lot_idx_h < len(all_lots_hist) else None
        ventes_avec_cout, valeur_est_hist = calc_cout_lot_func(lot, lot_idx=real_idx)
    
        # Ventes en lot (ventes[])
        for v in lot.get("ventes",[]):
            if v.get("is_lot_sale") or v.get("is_exchange_benefit"):
                continue
            price_v = float(v.get("price",0))
            if lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
                cout_v = (price_v / float(lot.get("valeur_totale", 1.) or 1.)) * float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
            else:
                cout_v = (price_v / (valeur_est_hist or 1.0)) * effective_purchase_price_func(lot)
            hist_enriched.append({
                "date": v.get("date",""),
                "card_name": v.get("card_name","Vente lot"),
                "card_set": "", "card_number": "",
                "lot_name": lot.get("nom","?"),
                "price": price_v,
                "cout": cout_v,
                "benef": price_v - cout_v,
                "image_url": "",
                "type": "lot",
            })
    
        # Ventes rapides — coût calculé par calc_cout_lot
        for card, se, cout_total in ventes_avec_cout:
            if se.get("is_exchange"):
                continue
            img = card.get("image_url","") or card.get("image","")
            price = float(se.get("price",0))
            hist_enriched.append({
                "date": se.get("date",""),
                "card_name": se.get("card_name", card.get("name","?")),
                "card_set": se.get("card_set", card.get("set","")),
                "card_number": se.get("card_number", card.get("number","")),
                "lot_name": lot.get("nom","?"),
                "price": price,
                "cout": cout_total,
                "benef": price - cout_total,
                "image_url": img,
                "type": "card",
                "quantity": int(se.get("quantity",1)),
                "canal": se.get("canal",""),
            })
    
    hist_enriched = sorted(hist_enriched, key=lambda x: x.get("date",""), reverse=True)
    
    if not hist_enriched:
        st.info("Aucune vente enregistrée.")
    else:
        # ── Filtres ──
        col_search, col_filter, col_sort = st.columns([3, 1, 1])
        search_hist = col_search.text_input("🔍 Rechercher une carte", placeholder="Nom de carte...", key="search_historique")
    
        # Mois en FR
        MOIS_FR_HIST = {1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
                        7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"}
        def mois_fr_label(m_str):
            try:
                d = datetime.strptime(m_str, "%Y-%m")
                return f"{MOIS_FR_HIST[d.month]} {d.year}"
            except:
                return m_str
    
        mois_disponibles = sorted({h["date"][:7] for h in hist_enriched if h.get("date")}, reverse=True)
        mois_labels = ["Tous"] + [mois_fr_label(m) for m in mois_disponibles]
        mois_map = {mois_fr_label(m): m for m in mois_disponibles}
    
        filter_month_label = col_filter.selectbox("Mois", mois_labels)
        filter_month = mois_map.get(filter_month_label, None)
    
        sort_opt = col_sort.selectbox("Trier par", ["Date (récent)", "Date (ancien)", "Prix (↓)", "Prix (↑)", "Bénéf (↓)", "Bénéf (↑)"])
    
        filtered = hist_enriched
        if search_hist:
            search_hist_norm = normalize_name_func(search_hist)
            filtered = [
                h for h in filtered
                if search_hist_norm in normalize_name_func(str(h.get("card_name", "")))
            ]
        if filter_month:
            filtered = [h for h in filtered if h.get("date","").startswith(filter_month)]
    
        # Tri
        if sort_opt == "Date (récent)":
            filtered = sorted(filtered, key=lambda h: h.get("date",""), reverse=True)
        elif sort_opt == "Date (ancien)":
            filtered = sorted(filtered, key=lambda h: h.get("date",""))
        elif sort_opt == "Prix (↓)":
            filtered = sorted(filtered, key=lambda h: h.get("price", 0), reverse=True)
        elif sort_opt == "Prix (↑)":
            filtered = sorted(filtered, key=lambda h: h.get("price", 0))
        elif sort_opt == "Bénéf (↓)":
            filtered = sorted(filtered, key=lambda h: h.get("benef", 0), reverse=True)
        elif sort_opt == "Bénéf (↑)":
            filtered = sorted(filtered, key=lambda h: h.get("benef", 0))
    
        # ── Résumé ──
        total_ca_h = sum(h["price"] for h in filtered)
        total_benef_h = sum(h.get("benef", h["price"]) for h in filtered)
        total_nb_h = sum(int(h.get("quantity", 1)) for h in filtered)
    
        s1,s2,s3 = st.columns(3)
        s1.metric("🧾 Ventes", str(total_nb_h))
        s2.metric("💰 CA", f"{total_ca_h:.2f}€")
        s3.metric("💎 Bénéfice estimé", f"{total_benef_h:.2f}€")
    
        current_hist_signature = f"{search_hist}|{filter_month or ''}|{sort_opt}|{len(filtered)}"
        if st.session_state.get("history_signature") != current_hist_signature:
            st.session_state["history_signature"] = current_hist_signature
            st.session_state["history_visible_count"] = 40
        history_visible_count = int(st.session_state.get("history_visible_count", 40))
        visible_history = filtered[:history_visible_count]
        if len(visible_history) < len(filtered):
            st.caption(f"Affichage progressif : {len(visible_history)} vente(s) sur {len(filtered)}.")
        st.markdown("---")
    
        # ── Lignes de l'historique ──
        for h in visible_history:
            benef = h.get("benef", h["price"])
            cout = h.get("cout", 0.)
            benef_color = "#10b981" if benef >= 0 else "#ef4444"
            date_str = h.get("date","")[:10] if h.get("date") else "—"
    
            img_col, info_col, prix_col = st.columns([1, 4, 2])
    
            with img_col:
                img = h.get("image_url","")
                if img:
                    st.markdown(f'<img loading="lazy" src="{proxy_img_func(img)}" style="width:60px;border-radius:6px;box-shadow:0 2px 6px rgba(0,0,0,0.12);">', unsafe_allow_html=True)
                else:
                    st.markdown('<div style="width:60px;height:84px;background:#f1f5f9;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:1.4rem;">🃏</div>', unsafe_allow_html=True)
    
            with info_col:
                set_num = f" · {h['card_set']} #{h['card_number']}" if h.get("card_set") else ""
                qty_h = int(h.get("quantity", 1))
                qty_badge = f' <span style="background:#dbeafe;color:#1d4ed8;border-radius:999px;padding:1px 7px;font-size:0.72rem;font-weight:800;">x{qty_h}</span>' if qty_h > 1 else ""
                canal_h = h.get("canal", "")
                canal_icons = {"Main propre":"🤝","Brocante":"🎪","Dexify_TCG":"⚡","Pokédeal":"🎴","Échange":"🔄"}
                canal_badge = f' <span style="background:#f1f5f9;border-radius:6px;padding:1px 6px;font-size:0.72rem;color:#64748b;">{canal_icons.get(canal_h,"📦")} {canal_h}</span>' if canal_h else ""
                st.markdown(f"""
                <div style="padding:0.2rem 0;">
                  <div style="font-weight:700;font-size:0.98rem;color:#1e293b;">{h['card_name']}{qty_badge}{canal_badge}</div>
                  <div style="font-size:0.8rem;color:#64748b;margin-top:2px;">{h['lot_name']}{set_num}</div>
                  <div style="font-size:0.78rem;color:#94a3b8;margin-top:2px;">📅 {date_str}</div>
                </div>
                """, unsafe_allow_html=True)
    
            with prix_col:
                st.markdown(f"""
                <div style="text-align:right;padding:0.2rem 0;">
                  <div style="font-size:1.1rem;font-weight:800;color:#1e293b;">{h['price']:.2f}€</div>
                  <div style="font-size:0.78rem;color:#94a3b8;">Acheté ~{cout:.2f}€</div>
                  <div style="font-size:0.85rem;font-weight:700;color:{benef_color};">Bénéf : {benef:+.2f}€</div>
                </div>
                """, unsafe_allow_html=True)
    
            st.markdown('<hr style="margin:0.4rem 0;border:none;border-top:1px solid #f1f5f9;">', unsafe_allow_html=True)
    
        if len(visible_history) < len(filtered):
            st.markdown('<div id="history-load-more-anchor"></div>', unsafe_allow_html=True)
            if st.button("Charger plus d'historique", key="history_load_more", width="stretch"):
                st.session_state["history_visible_count"] = history_visible_count + 40
                st.rerun()
            run_html_func("""
            <script>
            (function() {
                const win = parent.window;
                const doc = parent.document;
                if (win.codexHistoryAutoLoadAttached) return;
                win.codexHistoryAutoLoadAttached = true;
                win.addEventListener('scroll', function() {
                    clearTimeout(win.codexHistoryAutoLoadTimer);
                    win.codexHistoryAutoLoadTimer = setTimeout(function() {
                        const anchor = doc.getElementById('history-load-more-anchor');
                        if (!anchor) return;
                        const rect = anchor.getBoundingClientRect();
                        if (rect.top > win.innerHeight + 300) return;
                        const buttons = Array.from(doc.querySelectorAll('button'));
                        const btn = buttons.find(function(b) {
                            return (b.innerText || '').trim() === "Charger plus d'historique";
                        });
                        if (btn && !btn.disabled) btn.click();
                    }, 200);
                }, {passive: true});
            })();
            </script>
            """, height=0)

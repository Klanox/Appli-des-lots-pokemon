"""Counters page renderer for Pokestock.

This module contains the existing Streamlit UI rendering for the Compteurs page.
It keeps the same counters.json behavior and does not write application data.
"""

import datetime as dt_module
import json
import os
from datetime import datetime

import streamlit as st


def render_counters_page(*, ld_func, safe_write_json_func, canal_key_func):
    st.markdown("## 🎰 Compteurs de ventes")
    st.caption("Suivi de tes ventes par canal depuis des dates de référence.")

    COUNTERS_FILE = "counters.json"

    # ── Charger ou initialiser le fichier compteurs ──
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    year_str = str(now.year)

    if os.path.exists(COUNTERS_FILE):
        with open(COUNTERS_FILE, "r", encoding="utf-8") as f:
            counters = json.load(f)
    else:
        counters = {}

    # Structure par défaut
    counters.setdefault("main_brocante", {
        "start_date": today_str,
        "label": "Main propre & Brocante",
        "reset_mode": "manual",
    })
    counters.setdefault("dexify", {
        "year": year_str,
        "start_date": today_str,
        "label": "Dexify_TCG",
        "reset_mode": "manual",
    })
    counters.setdefault("pokedeal", {
        "year": year_str,
        "start_date": today_str,
        "label": "Pokédeal",
        "reset_mode": "manual",
    })
    counters["main_brocante"].setdefault("start_date", today_str)
    counters["dexify"].setdefault("start_date", f"{counters['dexify'].get('year', year_str)}-01-01")
    counters["pokedeal"].setdefault("start_date", f"{counters['pokedeal'].get('year', year_str)}-01-01")

    # ── Calculer les compteurs depuis les ventes réelles ──
    cd = ld_func()
    all_lots = cd.get("lots", [])
    archives_cnt = []
    if os.path.exists("lots_archives.json"):
        with open("lots_archives.json", "r", encoding="utf-8") as f:
            archives_cnt = json.load(f)

    start_date_mb = counters["main_brocante"]["start_date"]
    dexify_year = counters["dexify"].get("year", year_str)
    pokedeal_year = counters["pokedeal"].get("year", year_str)
    dexify_start_date = counters["dexify"].get("start_date", f"{dexify_year}-01-01")
    pokedeal_start_date = counters["pokedeal"].get("start_date", f"{pokedeal_year}-01-01")
    start_dt_mb = counters["main_brocante"].get("start_datetime", start_date_mb)
    dexify_start_dt = counters["dexify"].get("start_datetime", dexify_start_date)
    pokedeal_start_dt = counters["pokedeal"].get("start_datetime", pokedeal_start_date)

    def sale_after_start(sale_date, start_date, start_datetime):
        sale_date = str(sale_date or "")
        if "T" in str(start_datetime):
            return sale_date >= str(start_datetime)
        return sale_date[:10] >= str(start_date)

    with st.expander("⚙️ Données de départ (à saisir une seule fois)", expanded=True):
        st.caption("Ces valeurs sont ajoutées aux ventes calculées par l'application. Elles sont lues avant l'affichage des compteurs.")
        vi1, vi2, vi3 = st.columns(3)
        mb_init_ca = vi1.number_input("🤝 Main propre & Brocante — CA (€)", 0., 999999., float(counters["main_brocante"].get("init_ca", 0.)), key="counter_mb_init")
        dx_init_ca = vi2.number_input("⚡ Dexify_TCG — CA (€)", 0., 999999., float(counters["dexify"].get("init_ca", 0.)), key="counter_dx_init")
        pk_init_ca = vi3.number_input("🎴 Pokédeal — CA (€)", 0., 999999., float(counters["pokedeal"].get("init_ca", 0.)), key="counter_pk_init")
        if st.button("💾 Sauvegarder les données de départ", type="primary", key="save_counter_inits"):
            counters["main_brocante"]["init_ca"] = float(mb_init_ca)
            counters["dexify"]["init_ca"] = float(dx_init_ca)
            counters["pokedeal"]["init_ca"] = float(pk_init_ca)
            counters["main_brocante"]["start_date"] = today_str
            counters["dexify"]["start_date"] = today_str
            counters["pokedeal"]["start_date"] = today_str
            counters["main_brocante"]["start_datetime"] = now.isoformat()
            counters["dexify"]["start_datetime"] = now.isoformat()
            counters["pokedeal"]["start_datetime"] = now.isoformat()
            counters["dexify"]["year"] = year_str
            counters["pokedeal"]["year"] = year_str
            safe_write_json_func(COUNTERS_FILE, counters)
            st.success("✅ Valeurs initiales sauvegardées ! Les compteurs repartent d'aujourd'hui.")
            st.rerun()

    init_mb_display = float(mb_init_ca)
    init_dx_display = float(dx_init_ca)
    init_pk_display = float(pk_init_ca)

    # Compteurs calculés
    cnt_main_brocante = {"nb": 0, "ca": 0.}
    cnt_dexify = {"nb": 0, "ca": 0.}
    cnt_pokedeal = {"nb": 0, "ca": 0.}

    for lot in all_lots + archives_cnt:
        for v in lot.get("ventes", []):
            if v.get("is_lot_sale") or v.get("is_exchange_benefit"):
                continue
            canal = canal_key_func(v.get("canal", ""))
            if not canal:
                continue
            raw_date = v.get("date", "")
            date_str = raw_date[:10]
            price = float(v.get("price", 0))
            if canal in ("main", "brocante"):
                if sale_after_start(raw_date, start_date_mb, start_dt_mb):
                    cnt_main_brocante["ca"] += price
            elif canal == "dexify":
                if sale_after_start(raw_date, dexify_start_date, dexify_start_dt):
                    cnt_dexify["ca"] += price
            elif canal == "pokedeal":
                if sale_after_start(raw_date, pokedeal_start_date, pokedeal_start_dt):
                    cnt_pokedeal["ca"] += price
        for card in lot.get("cards", []):
            for se in card.get("sold_entries", []):
                canal = canal_key_func(se.get("canal", ""))
                if not canal:
                    continue  # ignorer les ventes sans canal (avant la mise à jour)
                raw_date = se.get("date", "")
                date_str = raw_date[:10]
                price = float(se.get("price", 0))
                qty = int(se.get("quantity", 1))

                if canal in ("main", "brocante"):
                    if sale_after_start(raw_date, start_date_mb, start_dt_mb):
                        cnt_main_brocante["ca"] += price

                elif canal == "dexify":
                    if sale_after_start(raw_date, dexify_start_date, dexify_start_dt):
                        cnt_dexify["ca"] += price

                elif canal == "pokedeal":
                    if sale_after_start(raw_date, pokedeal_start_date, pokedeal_start_dt):
                        cnt_pokedeal["ca"] += price

    # ── Affichage ──
    st.markdown("---")

    # ── Compteur Main propre & Brocante ──
    col_mb, col_dx, col_pk = st.columns(3)

    with col_mb:
        days_since = (now.date() - dt_module.date.fromisoformat(start_date_mb)).days
        total_mb_ca = cnt_main_brocante["ca"] + init_mb_display
        st.markdown(f"""
        <div style="background:white;border-radius:16px;padding:1.5rem;border:2px solid #e2e8f0;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);text-align:center;">
          <div style="font-size:1rem;font-weight:700;color:#64748b;margin-bottom:0.5rem;">🤝 Main propre & Brocante</div>
          <div style="font-size:3rem;font-weight:900;color:#10b981;">{total_mb_ca:.2f}€</div>
          <div style="font-size:0.75rem;color:#94a3b8;margin-top:0.5rem;">Depuis le {dt_module.date.fromisoformat(start_date_mb).strftime('%d/%m/%Y')} ({days_since}j)</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔄 Remettre à zéro", key="reset_mb", width="stretch"):
            st.session_state["confirm_reset_mb"] = True
        if st.session_state.get("confirm_reset_mb"):
            st.warning("Confirmer la remise à zéro ?")
            r1, r2 = st.columns(2)
            if r1.button("✅ Oui", key="reset_mb_ok"):
                counters["main_brocante"]["start_date"] = today_str
                counters["main_brocante"]["init_ca"] = 0.
                st.session_state["init_mb_ca_input"] = 0.
                safe_write_json_func(COUNTERS_FILE, counters)
                st.session_state["confirm_reset_mb"] = False
                st.success(f"✅ Compteur remis à zéro depuis aujourd'hui ({today_str})")
                st.rerun()
            if r2.button("❌ Non", key="reset_mb_no"):
                st.session_state["confirm_reset_mb"] = False

    with col_dx:
        total_dx_ca = cnt_dexify["ca"] + init_dx_display
        st.markdown(f"""
        <div style="background:white;border-radius:16px;padding:1.5rem;border:2px solid #e2e8f0;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);text-align:center;">
          <div style="font-size:1rem;font-weight:700;color:#64748b;margin-bottom:0.5rem;">⚡ Dexify_TCG</div>
          <div style="font-size:3rem;font-weight:900;color:#10b981;">{total_dx_ca:.2f}€</div>
          <div style="font-size:0.75rem;color:#94a3b8;margin-top:0.5rem;">Depuis le {dexify_start_date}</div>
        </div>
        """, unsafe_allow_html=True)
        new_year_dx = st.selectbox("Année affichée", [str(y) for y in range(2023, now.year+2)],
                                    index=[str(y) for y in range(2023, now.year+2)].index(dexify_year),
                                    key="sel_year_dx")
        if new_year_dx != dexify_year:
            counters["dexify"]["year"] = new_year_dx
            safe_write_json_func(COUNTERS_FILE, counters)
            st.rerun()

    with col_pk:
        total_pk_ca = cnt_pokedeal["ca"] + init_pk_display
        st.markdown(f"""
        <div style="background:white;border-radius:16px;padding:1.5rem;border:2px solid #e2e8f0;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);text-align:center;">
          <div style="font-size:1rem;font-weight:700;color:#64748b;margin-bottom:0.5rem;">🎴 Pokédeal</div>
          <div style="font-size:3rem;font-weight:900;color:#10b981;">{total_pk_ca:.2f}€</div>
          <div style="font-size:0.75rem;color:#94a3b8;margin-top:0.5rem;">Depuis le {pokedeal_start_date}</div>
        </div>
        """, unsafe_allow_html=True)
        new_year_pk = st.selectbox("Année affichée", [str(y) for y in range(2023, now.year+2)],
                                    index=[str(y) for y in range(2023, now.year+2)].index(pokedeal_year),
                                    key="sel_year_pk")
        if new_year_pk != pokedeal_year:
            counters["pokedeal"]["year"] = new_year_pk
            safe_write_json_func(COUNTERS_FILE, counters)
            st.rerun()

    # ── Récap global ──
    st.markdown("---")
    st.markdown("### 📊 Récapitulatif")
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("🤝 Main propre & Brocante", f"{total_mb_ca:.2f}€")
    rc2.metric("⚡ Dexify_TCG", f"{total_dx_ca:.2f}€")
    rc3.metric("🎴 Pokédeal", f"{total_pk_ca:.2f}€")





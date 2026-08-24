"""Counters page renderer for Pokestock.

This module contains the existing Streamlit UI rendering for the Compteurs page.
It keeps the same counters.json behavior and does not write application data.
"""

import datetime as dt_module
import json
import os
from datetime import datetime

import streamlit as st

from services.vinted_channels import VINTED_CHANNELS, normalize_vinted_channel, vinted_channel_key


VINTED_COUNTER_ICONS = {
    "Dexify": "⚡",
    "Pokédeal": "🎴",
    "ChoppeTaCarte": "🛍️",
}


def _vinted_counter_defs():
    return [
        {
            "channel": channel,
            "key": vinted_channel_key(channel),
            "label": "Dexify_TCG" if channel == "Dexify" else channel,
            "icon": VINTED_COUNTER_ICONS.get(channel, "🛒"),
        }
        for channel in VINTED_CHANNELS
    ]


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
    vinted_defs = _vinted_counter_defs()
    for channel_def in vinted_defs:
        counters.setdefault(channel_def["key"], {
            "year": year_str,
            "start_date": today_str,
            "label": channel_def["label"],
            "reset_mode": "manual",
        })
        counters[channel_def["key"]].setdefault("label", channel_def["label"])
    counters["main_brocante"].setdefault("start_date", today_str)
    for channel_def in vinted_defs:
        channel_key = channel_def["key"]
        counters[channel_key].setdefault("start_date", f"{counters[channel_key].get('year', year_str)}-01-01")

    # ── Calculer les compteurs depuis les ventes réelles ──
    cd = ld_func()
    all_lots = cd.get("lots", [])
    archives_cnt = []
    if os.path.exists("lots_archives.json"):
        with open("lots_archives.json", "r", encoding="utf-8") as f:
            archives_cnt = json.load(f)

    start_date_mb = counters["main_brocante"]["start_date"]
    start_dt_mb = counters["main_brocante"].get("start_datetime", start_date_mb)
    vinted_counter_state = {}
    for channel_def in vinted_defs:
        channel_key = channel_def["key"]
        channel_year = counters[channel_key].get("year", year_str)
        channel_start_date = counters[channel_key].get("start_date", f"{channel_year}-01-01")
        vinted_counter_state[channel_key] = {
            "year": channel_year,
            "start_date": channel_start_date,
            "start_datetime": counters[channel_key].get("start_datetime", channel_start_date),
        }

    def sale_after_start(sale_date, start_date, start_datetime):
        sale_date = str(sale_date or "")
        if "T" in str(start_datetime):
            return sale_date >= str(start_datetime)
        return sale_date[:10] >= str(start_date)

    with st.expander("⚙️ Données de départ (à saisir une seule fois)", expanded=True):
        st.caption("Ces valeurs sont ajoutées aux ventes calculées par l'application. Elles sont lues avant l'affichage des compteurs.")
        init_columns = st.columns(1 + len(vinted_defs))
        mb_init_ca = init_columns[0].number_input("🤝 Main propre & Brocante — CA (€)", 0., 999999., float(counters["main_brocante"].get("init_ca", 0.)), key="counter_mb_init")
        vinted_init_values = {}
        for idx, channel_def in enumerate(vinted_defs, start=1):
            channel_key = channel_def["key"]
            vinted_init_values[channel_key] = init_columns[idx].number_input(
                f"{channel_def['icon']} {channel_def['label']} — CA (€)",
                0.,
                999999.,
                float(counters[channel_key].get("init_ca", 0.)),
                key=f"counter_{channel_key}_init",
            )
        if st.button("💾 Sauvegarder les données de départ", type="primary", key="save_counter_inits"):
            counters["main_brocante"]["init_ca"] = float(mb_init_ca)
            counters["main_brocante"]["start_date"] = today_str
            counters["main_brocante"]["start_datetime"] = now.isoformat()
            for channel_def in vinted_defs:
                channel_key = channel_def["key"]
                counters[channel_key]["init_ca"] = float(vinted_init_values[channel_key])
                counters[channel_key]["start_date"] = today_str
                counters[channel_key]["start_datetime"] = now.isoformat()
                counters[channel_key]["year"] = year_str
            safe_write_json_func(COUNTERS_FILE, counters)
            st.success("✅ Valeurs initiales sauvegardées ! Les compteurs repartent d'aujourd'hui.")
            st.rerun()

    init_mb_display = float(mb_init_ca)
    vinted_init_display = {channel_key: float(value) for channel_key, value in vinted_init_values.items()}

    # Compteurs calculés
    cnt_main_brocante = {"nb": 0, "ca": 0.}
    cnt_vinted = {channel_def["key"]: {"nb": 0, "ca": 0.} for channel_def in vinted_defs}

    def counter_key_for_sale(canal):
        normalized = normalize_vinted_channel(canal)
        if normalized in VINTED_CHANNELS:
            return vinted_channel_key(normalized)
        return canal_key_func(canal)

    for lot in all_lots + archives_cnt:
        for v in lot.get("ventes", []):
            if v.get("is_lot_sale") or v.get("is_exchange_benefit"):
                continue
            canal = counter_key_for_sale(v.get("canal", ""))
            if not canal:
                continue
            raw_date = v.get("date", "")
            price = float(v.get("price", 0))
            qty = int(v.get("quantity", 1) or 1)
            if canal in ("main", "brocante"):
                if sale_after_start(raw_date, start_date_mb, start_dt_mb):
                    cnt_main_brocante["ca"] += price
                    cnt_main_brocante["nb"] += qty
            elif canal in cnt_vinted:
                channel_state = vinted_counter_state[canal]
                if sale_after_start(raw_date, channel_state["start_date"], channel_state["start_datetime"]):
                    cnt_vinted[canal]["ca"] += price
                    cnt_vinted[canal]["nb"] += qty
        for card in lot.get("cards", []):
            for se in card.get("sold_entries", []):
                canal = counter_key_for_sale(se.get("canal", ""))
                if not canal:
                    continue  # ignorer les ventes sans canal (avant la mise à jour)
                raw_date = se.get("date", "")
                price = float(se.get("price", 0))
                qty = int(se.get("quantity", 1))

                if canal in ("main", "brocante"):
                    if sale_after_start(raw_date, start_date_mb, start_dt_mb):
                        cnt_main_brocante["ca"] += price
                        cnt_main_brocante["nb"] += qty

                elif canal in cnt_vinted:
                    channel_state = vinted_counter_state[canal]
                    if sale_after_start(raw_date, channel_state["start_date"], channel_state["start_datetime"]):
                        cnt_vinted[canal]["ca"] += price
                        cnt_vinted[canal]["nb"] += qty

    # ── Affichage ──
    st.markdown("---")

    # ── Compteur Main propre & Brocante ──
    counter_columns = st.columns(1 + len(vinted_defs))

    with counter_columns[0]:
        days_since = (now.date() - dt_module.date.fromisoformat(start_date_mb)).days
        total_mb_ca = cnt_main_brocante["ca"] + init_mb_display
        st.markdown(f"""
        <div style="background:white;border-radius:16px;padding:1.5rem;border:2px solid #e2e8f0;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);text-align:center;">
          <div style="font-size:1rem;font-weight:700;color:#64748b;margin-bottom:0.5rem;">🤝 Main propre & Brocante</div>
          <div style="font-size:3rem;font-weight:900;color:#10b981;">{total_mb_ca:.2f}€</div>
          <div style="font-size:0.85rem;color:#64748b;font-weight:700;">{cnt_main_brocante["nb"]} vente(s)</div>
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

    total_vinted_ca = {}
    for col, channel_def in zip(counter_columns[1:], vinted_defs):
        channel_key = channel_def["key"]
        channel_state = vinted_counter_state[channel_key]
        total_vinted_ca[channel_key] = cnt_vinted[channel_key]["ca"] + vinted_init_display[channel_key]
        with col:
            st.markdown(f"""
            <div style="background:white;border-radius:16px;padding:1.5rem;border:2px solid #e2e8f0;
                        box-shadow:0 2px 8px rgba(0,0,0,0.06);text-align:center;">
              <div style="font-size:1rem;font-weight:700;color:#64748b;margin-bottom:0.5rem;">{channel_def['icon']} {channel_def['label']}</div>
              <div style="font-size:3rem;font-weight:900;color:#10b981;">{total_vinted_ca[channel_key]:.2f}€</div>
              <div style="font-size:0.85rem;color:#64748b;font-weight:700;">{cnt_vinted[channel_key]["nb"]} vente(s)</div>
              <div style="font-size:0.75rem;color:#94a3b8;margin-top:0.5rem;">Depuis le {channel_state['start_date']}</div>
            </div>
            """, unsafe_allow_html=True)
            year_options = [str(y) for y in range(2023, now.year+2)]
            channel_year = channel_state["year"] if channel_state["year"] in year_options else year_str
            new_year = st.selectbox(
                "Année affichée",
                year_options,
                index=year_options.index(channel_year),
                key=f"sel_year_{channel_key}",
            )
            if new_year != channel_state["year"]:
                counters[channel_key]["year"] = new_year
                counters[channel_key]["start_date"] = f"{new_year}-01-01"
                safe_write_json_func(COUNTERS_FILE, counters)
                st.rerun()

    # ── Récap global ──
    st.markdown("---")
    st.markdown("### 📊 Récapitulatif")
    recap_columns = st.columns(1 + len(vinted_defs))
    recap_columns[0].metric("🤝 Main propre & Brocante", f"{total_mb_ca:.2f}€")
    for col, channel_def in zip(recap_columns[1:], vinted_defs):
        channel_key = channel_def["key"]
        col.metric(f"{channel_def['icon']} {channel_def['label']}", f"{total_vinted_ca[channel_key]:.2f}€")





"""Counters page renderer for Pokestock.

This module contains the existing Streamlit UI rendering for the Compteurs page.
It keeps the same counters.json behavior and does not write application data.
"""

import datetime as dt_module
import html
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

COUNTER_VISUALS = {
    "main_brocante": {
        "icon": "🤝",
        "accent": "#F97316",
        "label": "Main propre & Brocante",
    },
    "dexify": {
        "icon": "⚡",
        "accent": "#6D28D9",
        "label": "Dexify_TCG",
    },
    "pokedeal": {
        "icon": "🎴",
        "accent": "#E11D48",
        "label": "Pokédeal",
    },
    "choppetacarte": {
        "icon": "🛍️",
        "accent": "#06B6D4",
        "label": "ChoppeTaCarte",
    },
}


def _fmt_eur(value):
    return f"{float(value or 0):,.2f}€".replace(",", " ").replace(".", ",")


def _fmt_date(value):
    try:
        return dt_module.date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(value or "N/A")


def _inject_counters_css():
    st.markdown(
        """
        <style>
        .ps-counters-page{font-family:"Plus Jakarta Sans",sans-serif;color:#111827}
        .ps-counters-hero{position:relative;overflow:hidden;border:1px solid #D1D5DB;border-top:5px solid #6D28D9;border-radius:20px;padding:1.05rem 1.15rem;margin:.1rem 0 .9rem;background:#FFFFFF;box-shadow:0 10px 24px rgba(17,24,39,.08)}
        .ps-counters-kicker{color:#6D28D9;font-size:.75rem;font-weight:950;letter-spacing:.11em;text-transform:uppercase}
        .ps-counters-title{font-size:clamp(1.65rem,4vw,2.65rem);font-weight:950;line-height:1;margin:.18rem 0;color:#111827;letter-spacing:0}
        .ps-counters-sub{color:#374151;font-size:.9rem;font-weight:760;max-width:720px;margin:.35rem 0 0}
        .ps-counters-modern-expander div[data-testid="stExpander"]{border:1px solid #D1D5DB;border-radius:18px;background:#FFFFFF;box-shadow:0 8px 18px rgba(17,24,39,.06)}
        .ps-counter-init-note{color:#64748b;font-size:.84rem;font-weight:750;margin:.1rem 0 .55rem}
        div[class*="st-key-counter_card_"]{height:100%}
        div[class*="st-key-counter_card_"]>div{height:100%;border:1px solid #D1D5DB;border-left:6px solid var(--counter-accent);border-radius:20px;padding:.82rem .85rem .9rem;background:#FFFFFF;box-shadow:0 10px 22px rgba(17,24,39,.08);transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease}
        div[class*="st-key-counter_card_"]>div:hover{transform:translateY(-2px);box-shadow:0 14px 28px rgba(17,24,39,.13);border-color:#9CA3AF;border-left-color:var(--counter-accent)}
        .ps-counter-card-head{display:flex;align-items:center;gap:.7rem;margin-bottom:.7rem}
        .ps-counter-icon{width:42px;height:42px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:1.25rem;background:var(--counter-accent);color:#FFFFFF}
        .ps-counter-name{font-size:.92rem;font-weight:950;color:#111827;line-height:1.12}
        .ps-counter-badge{display:inline-flex;align-items:center;border-radius:999px;padding:.22rem .5rem;margin-top:.28rem;font-size:.68rem;font-weight:950;color:#FFFFFF;background:var(--counter-accent);border:1px solid var(--counter-accent)}
        .ps-counter-amount{font-size:clamp(1.9rem,3.7vw,2.7rem);font-weight:950;color:#111827;line-height:.98;margin:.25rem 0 .2rem;overflow-wrap:anywhere}
        .ps-counter-sales{font-size:.82rem;color:#374151;font-weight:850;margin-bottom:.55rem}
        .ps-counter-period{display:inline-flex;align-items:center;gap:.28rem;max-width:100%;border-radius:999px;background:#F8FAFC;border:1px solid #CBD5E1;color:#111827;font-size:.72rem;font-weight:900;padding:.34rem .52rem;margin-bottom:.65rem}
        div[class*="st-key-counter_card_"] label{font-size:.76rem!important;font-weight:900!important;color:#111827!important}
        div[class*="st-key-counter_card_"] button{border-radius:999px!important;font-weight:900!important}
        div[class*="st-key-save_counter_inits"] button{border-radius:999px!important;font-weight:900!important}
        .ps-counter-mini-summary{margin:.8rem 0 0;color:#111827;font-size:.84rem;font-weight:900;background:#FFFFFF;border:1px solid #D1D5DB;border-left:5px solid #6D28D9;border-radius:14px;padding:.52rem .75rem;width:max-content;max-width:100%;box-shadow:0 6px 14px rgba(17,24,39,.06)}
        @media (max-width:768px){
            .ps-counters-hero{border-radius:18px;padding:.9rem}
            div[class*="st-key-counter_card_"]>div{border-radius:18px;padding:.78rem}
            .ps-counter-card-head{gap:.58rem}
            .ps-counter-icon{width:38px;height:38px;border-radius:13px}
            .ps-counter-mini-summary{width:100%}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_counter_hero():
    st.markdown(
        """
        <div class="ps-counters-page">
          <div class="ps-counters-hero">
            <div class="ps-counters-kicker">Suivi par canal</div>
            <div class="ps-counters-title">Compteurs de ventes</div>
            <div class="ps-counters-sub">Un tableau de bord compact pour suivre tes ventes depuis les dates de référence, canal par canal.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _counter_card_html(*, key, label, icon, total_ca, nb_sales, period_label):
    visual = COUNTER_VISUALS.get(key, COUNTER_VISUALS["main_brocante"])
    style = f"--counter-accent:{visual['accent']};"
    return f"""
    <div class="ps-counter-card-shell" style="{style}">
      <div class="ps-counter-card-head">
        <div class="ps-counter-icon">{html.escape(icon)}</div>
        <div>
          <div class="ps-counter-name">{html.escape(label)}</div>
          <div class="ps-counter-badge">Canal suivi</div>
        </div>
      </div>
      <div class="ps-counter-amount">{html.escape(_fmt_eur(total_ca))}</div>
      <div class="ps-counter-sales">{int(nb_sales)} vente(s) comptabilisée(s)</div>
      <div class="ps-counter-period">{html.escape(period_label)}</div>
    </div>
    """


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
    _inject_counters_css()
    _render_counter_hero()

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
    counters["main_brocante"].setdefault("year", year_str)
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

    main_brocante_year = counters["main_brocante"].get("year", year_str)
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

    def sale_in_year(sale_date, year):
        return str(sale_date or "")[:4] == str(year)

    with st.expander("⚙️ Données de départ", expanded=False):
        st.markdown(
            '<div class="ps-counter-init-note">Ces valeurs restent disponibles pour les canaux Vinted. Main propre & Brocante est calculé automatiquement sur toute l’année affichée.</div>',
            unsafe_allow_html=True,
        )
        init_columns = st.columns(len(vinted_defs))
        vinted_init_values = {}
        for idx, channel_def in enumerate(vinted_defs):
            channel_key = channel_def["key"]
            vinted_init_values[channel_key] = init_columns[idx].number_input(
                f"{channel_def['icon']} {channel_def['label']} — CA (€)",
                0.,
                999999.,
                float(counters[channel_key].get("init_ca", 0.)),
                key=f"counter_{channel_key}_init",
            )
        if st.button("💾 Sauvegarder les données de départ", type="primary", key="save_counter_inits"):
            for channel_def in vinted_defs:
                channel_key = channel_def["key"]
                counters[channel_key]["init_ca"] = float(vinted_init_values[channel_key])
                counters[channel_key]["start_date"] = today_str
                counters[channel_key]["start_datetime"] = now.isoformat()
                counters[channel_key]["year"] = year_str
            safe_write_json_func(COUNTERS_FILE, counters)
            st.success("✅ Valeurs initiales sauvegardées ! Les compteurs repartent d'aujourd'hui.")
            st.rerun()

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
                if sale_in_year(raw_date, main_brocante_year):
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
                    if sale_in_year(raw_date, main_brocante_year):
                        cnt_main_brocante["ca"] += price
                        cnt_main_brocante["nb"] += qty

                elif canal in cnt_vinted:
                    channel_state = vinted_counter_state[canal]
                    if sale_after_start(raw_date, channel_state["start_date"], channel_state["start_datetime"]):
                        cnt_vinted[canal]["ca"] += price
                        cnt_vinted[canal]["nb"] += qty

    # ── Cartes compteurs ──
    counter_columns = st.columns(1 + len(vinted_defs))

    with counter_columns[0]:
        total_mb_ca = cnt_main_brocante["ca"]
        with st.container(key="counter_card_main_brocante"):
            st.markdown(
                _counter_card_html(
                    key="main_brocante",
                    label=COUNTER_VISUALS["main_brocante"]["label"],
                    icon=COUNTER_VISUALS["main_brocante"]["icon"],
                    total_ca=total_mb_ca,
                    nb_sales=cnt_main_brocante["nb"],
                    period_label=f"Année {main_brocante_year}",
                ),
                unsafe_allow_html=True,
            )
            year_options = [str(y) for y in range(2023, now.year+2)]
            selected_main_year = main_brocante_year if main_brocante_year in year_options else year_str
            new_main_year = st.selectbox(
                "Année affichée",
                year_options,
                index=year_options.index(selected_main_year),
                key="sel_year_main_brocante",
            )
            if new_main_year != main_brocante_year:
                counters["main_brocante"]["year"] = new_main_year
                safe_write_json_func(COUNTERS_FILE, counters)
                st.rerun()

    total_vinted_ca = {}
    for col, channel_def in zip(counter_columns[1:], vinted_defs):
        channel_key = channel_def["key"]
        channel_state = vinted_counter_state[channel_key]
        total_vinted_ca[channel_key] = cnt_vinted[channel_key]["ca"] + vinted_init_display[channel_key]
        with col:
            with st.container(key=f"counter_card_{channel_key}"):
                st.markdown(
                    _counter_card_html(
                        key=channel_key,
                        label=channel_def["label"],
                        icon=channel_def["icon"],
                        total_ca=total_vinted_ca[channel_key],
                        nb_sales=cnt_vinted[channel_key]["nb"],
                        period_label=f"Depuis le {_fmt_date(channel_state['start_date'])}",
                    ),
                    unsafe_allow_html=True,
                )
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

    total_display_ca = total_mb_ca + sum(total_vinted_ca.values())
    total_display_sales = cnt_main_brocante["nb"] + sum(row["nb"] for row in cnt_vinted.values())
    st.markdown(
        f'<div class="ps-counter-mini-summary">{html.escape(_fmt_eur(total_display_ca))} suivis · {int(total_display_sales)} vente(s) sur les périodes affichées</div>',
        unsafe_allow_html=True,
    )





"""Data Health page renderer for Pokestock.

Scan a la demande (bouton « Scanner ») : liste les anomalies detectees par
services/data_health_service.py sans rien corriger tout seul. Chaque anomalie propose
« Aller vérifier » (navigation vers la bonne page, lot et carte) et, quand une correction
simple et sure existe, un bouton qui l'applique apres sauvegarde du fichier concerne.
"""

from __future__ import annotations

import copy
from datetime import datetime

import streamlit as st

from services.data_health_service import (
    CHECK_LABELS,
    apply_fix,
    load_archives,
    scan_data_health,
)

RESULT_KEY = "data_health_result"
FLASH_KEY = "data_health_flash"
FOCUS_KEY = "data_health_focus"

SEVERITY_BADGE = {
    "error": ("🔴", "Erreur"),
    "warning": ("🟠", "À vérifier"),
    "info": ("🔵", "Information"),
}


# --------------------------------------------------------------------------- focus (banniere sur la page cible)

def render_data_health_focus(page, *, lot_uid=None, drop_id=None):
    """Banniere affichee sur la page cible quand on arrive depuis Data Health."""
    focus = st.session_state.get(FOCUS_KEY)
    if not focus or focus.get("page") != page:
        return
    if lot_uid is not None and focus.get("lot_uid") and focus.get("lot_uid") != lot_uid:
        return
    if drop_id is not None and focus.get("drop_id") and focus.get("drop_id") != drop_id:
        return
    left, right = st.columns([8, 1])
    left.warning(f"🩺 **Data Health** — {focus.get('message', 'Élément à vérifier.')}")
    if right.button("✕", key=f"data_health_focus_close_{page}", help="Masquer ce rappel"):
        st.session_state.pop(FOCUS_KEY, None)
        st.rerun()


def clear_focus_if_left(page):
    """A appeler quand on change de page : le rappel ne suit pas l'utilisateur ailleurs."""
    focus = st.session_state.get(FOCUS_KEY)
    if focus and focus.get("page") != page:
        st.session_state.pop(FOCUS_KEY, None)


# --------------------------------------------------------------------------- navigation

def prepare_navigation(target, data):
    """Prepare l'etat de session pour ouvrir le bon lot / la bonne carte / le bon Drop. Retourne la page cible."""
    page = target.get("page", "Accueil")
    st.session_state[FOCUS_KEY] = {
        "page": page,
        "lot_uid": target.get("lot_uid", ""),
        "drop_id": target.get("drop_id", ""),
        "message": target.get("message", ""),
    }
    if page == "Lots":
        lots = (data or {}).get("lots", []) or []
        index = None
        if target.get("lot_uid"):
            index = next((i for i, lot in enumerate(lots) if lot.get("lot_uid") == target["lot_uid"]), None)
        if index is None and target.get("lot_name"):
            index = next((i for i, lot in enumerate(lots) if lot.get("nom") == target["lot_name"]), None)
        if index is not None:
            st.session_state["active_lot_ix"] = index
            st.session_state.pop("lots_filter_v2", None)  # repasse sur « Tous » pour que le lot soit visible
            if target.get("card_name"):
                st.session_state[f"lot_card_search_{index}"] = target["card_name"]
    elif page == "Annonces Vinted" and target.get("drop_id"):
        st.session_state["vinted_active_drop_id"] = target["drop_id"]
    return page


# --------------------------------------------------------------------------- scan

def run_scan(ld_func, load_brocantes_func=None, load_drops_func=None, archives_path=None):
    data = copy.deepcopy(ld_func())
    drops = load_drops_func() if load_drops_func else {"drops": []}
    archives = load_archives(archives_path)
    brocantes = None
    if load_brocantes_func:
        try:
            brocantes = load_brocantes_func()
        except Exception:
            brocantes = None
    return scan_data_health(data, drops, archives, brocantes)


def render_data_health_page(
    *,
    ld_func,
    sd_func,
    render_page_header_func,
    navigate_func,
    load_drops_func,
    save_drops_func,
    load_brocantes_func=None,
    data_path="data.json",
    drops_path="vinted_drops.json",
    archives_path="lots_archives.json",
    backup_dir=None,
):
    st.markdown(
        render_page_header_func(
            "Data Health",
            "Détecte les incohérences dans tes données — rien n'est corrigé sans ton clic",
            "🩺",
        ),
        unsafe_allow_html=True,
    )

    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])

    top_left, top_right = st.columns([1, 3])
    scan_clicked = top_left.button("🔍 Scanner", type="primary", key="data_health_scan", use_container_width=True)
    top_right.caption(
        "Le scan lit data.json, vinted_drops.json, lots_archives.json et brocantes.json sans rien modifier. "
        "Les corrections proposées sauvegardent d'abord le fichier concerné dans `backups/`."
    )

    if scan_clicked:
        with st.spinner("Analyse des données…"):
            st.session_state[RESULT_KEY] = run_scan(ld_func, load_brocantes_func, load_drops_func, archives_path)
        st.rerun()

    result = st.session_state.get(RESULT_KEY)
    if not result:
        st.info("Clique sur **Scanner** pour lancer l'analyse. Elle n'est jamais lancée automatiquement.")
        return

    anomalies = result["anomalies"]
    scanned_at = result.get("scanned_at", "")
    try:
        scanned_label = datetime.fromisoformat(scanned_at).strftime("%d/%m/%Y à %H:%M:%S")
    except ValueError:
        scanned_label = scanned_at
    st.caption(f"Dernier scan : {scanned_label} — {len(anomalies)} point(s) relevé(s).")

    if not anomalies:
        st.success("✅ Aucune anomalie détectée.")
        return

    metric_cols = st.columns(len(CHECK_LABELS))
    for col, (check, label) in zip(metric_cols, CHECK_LABELS.items()):
        col.metric(label, result["counts"].get(check, 0))

    options = ["Toutes"] + [f"{label} ({result['counts'].get(check, 0)})" for check, label in CHECK_LABELS.items()
                            if result["counts"].get(check, 0)]
    choice = st.radio("Filtrer", options, horizontal=True, label_visibility="collapsed", key="data_health_filter")
    wanted_check = None
    if choice != "Toutes":
        wanted_check = next(check for check, label in CHECK_LABELS.items() if choice.startswith(label))
    hide_info = st.checkbox("Masquer les informations (aucune action requise)", value=False, key="data_health_hide_info")

    shown = [a for a in anomalies
             if (wanted_check is None or a["check"] == wanted_check) and not (hide_info and a["severity"] == "info")]
    if not shown:
        st.info("Aucune anomalie pour ce filtre.")
        return

    for anomaly in shown:
        icon, severity_label = SEVERITY_BADGE.get(anomaly["severity"], ("⚪", ""))
        with st.container(border=True):
            st.markdown(f"**{icon} {anomaly['title']}**  \n:gray[{CHECK_LABELS[anomaly['check']]} · {severity_label}]")
            st.write(anomaly["explanation"])
            nav_col, fix_col, _spacer = st.columns([1.2, 2.2, 3])
            if nav_col.button("🔎 Aller vérifier", key=f"dh_go_{anomaly['id']}", use_container_width=True):
                page = prepare_navigation(anomaly["target"], ld_func())
                navigate_func(page)
            fix = anomaly.get("fix")
            if fix and fix_col.button(f"🛠️ {fix['label']}", key=f"dh_fix_{anomaly['id']}", use_container_width=True,
                                       help="Sauvegarde le fichier concerné dans backups/ puis applique la correction."):
                ok, message = apply_fix(
                    fix,
                    load_data=ld_func,
                    save_data=sd_func,
                    load_drops=load_drops_func,
                    save_drops=save_drops_func,
                    data_path=data_path,
                    drops_path=drops_path,
                    backup_dir=backup_dir,
                )
                st.session_state[FLASH_KEY] = (ok, message)
                if ok:  # le resultat affiche doit refleter les donnees corrigees
                    st.session_state[RESULT_KEY] = run_scan(ld_func, load_brocantes_func, load_drops_func, archives_path)
                st.rerun()

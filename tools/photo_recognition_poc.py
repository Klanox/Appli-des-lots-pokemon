"""Streamlit POC for Vinted drop photo recognition.

Run with:
    streamlit run tools/photo_recognition_poc.py

This tool is isolated from the real Drop workflow. It reads photos and JSON
datasets, but never writes to Pokestock business data.
"""

from __future__ import annotations

import sys
import math
import base64
import hashlib
import json
import time
import unicodedata
from datetime import datetime
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from PIL import Image, ImageOps

from services.photo_recognition_service import (
    PHOTO_ROLES,
    POC_ANALYSIS_PIPELINE_VERSION,
    POC_MATCHING_REFRESH_VERSION,
    POC_DIR,
    POC_GROUND_TRUTH_PATH,
    VALIDATED_GROUP_STATUSES,
    active_drop_candidates,
    analyze_sample,
    candidate_identity,
    candidate_identity_key,
    candidate_set_signature,
    ensure_ground_truth_sample,
    list_ordered_photos,
    load_cached_analysis_result,
    load_latest_cached_analysis_result,
    load_poc_ground_truth,
    load_vinted_drops,
    photo_key,
    photo_window_signature,
    sample_ground_truth_key,
    stable_group_id_from_photos,
    update_ground_truth_sample,
    normalize_group_status,
    refresh_result_candidates,
)


ROLE_LABELS = {
    "primary_front": "primary_front",
    "back_western": "back_western",
    "back_japanese": "back_japanese",
    "card_front": "card_front",
    "card_back": "card_back",
    "extra": "extra",
    "uncertain": "uncertain",
}

STATUS_LABELS = {
    "green": "🟢 Reconnu",
    "orange": "🟠 À vérifier",
    "red": "🔴 Non reconnu",
}

VIEW_OPTIONS = [
    "Vue d’ensemble",
    "À vérifier",
    "Cas sensibles",
    "Validés",
    "Grouping",
    "Diagnostic",
]

DIAGNOSTIC_OPTIONS = [
    "Diagnostic ciblé",
    "Résultats / debug reconnaissance",
    "Erreurs uniquement",
    "Propositions modifiées",
    "Cas japonais",
    "Nouveaux autos",
    "Validation des groupes",
    "Contrôle verts",
    "Vérification complète",
    "Métriques historiques",
    "Ordre de capture",
]

LEGACY_VIEW_ROUTES = {
    "Synthèse complète": ("Vue d’ensemble", None),
    "File à vérifier": ("À vérifier", None),
    "File non reconnus": ("À vérifier", None),
    "Cas sensibles": ("Cas sensibles", None),
    "Carte du grouping": ("Grouping", None),
    "Singles / grouping reviews": ("Grouping", None),
    "Résultats / debug reconnaissance": ("Diagnostic", "Résultats / debug reconnaissance"),
    "Erreurs uniquement": ("Diagnostic", "Erreurs uniquement"),
    "Propositions modifiées": ("Diagnostic", "Propositions modifiées"),
    "Cas japonais": ("Diagnostic", "Cas japonais"),
    "Nouveaux autos V13": ("Diagnostic", "Nouveaux autos"),
    "Validation des groupes": ("Diagnostic", "Validation des groupes"),
    "Contrôle verts": ("Diagnostic", "Contrôle verts"),
    "Vérification complète": ("Diagnostic", "Vérification complète"),
}

CURRENT_RESULT_KEY = "photo_poc_current_result"


st.set_page_config(page_title="POC reconnaissance photos", layout="wide")


def _photo_folder_token(folder: str) -> str:
    root = Path(folder)
    if not root.exists():
        return "missing"
    rows = []
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        try:
            stat = path.stat()
            rows.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
        except OSError:
            rows.append(f"{path.name}:unreadable")
    return hashlib.sha1("|".join(sorted(rows)).encode("utf-8")).hexdigest()


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


@st.cache_data(show_spinner=False)
def _cached_ordered_photos(folder: str, folder_token: str):
    del folder_token
    return list_ordered_photos(folder)

st.markdown(
    """
    <style>
    :root { --poc-bg:#f8fafc; --poc-ink:#111827; --poc-muted:#64748b; --poc-line:#e5e7eb;
      --poc-violet:#6d28d9; --poc-blue:#2563eb; --poc-cyan:#06b6d4; --poc-green:#16a34a;
      --poc-orange:#f97316; --poc-rose:#e11d48; --poc-amber:#f59e0b; }
    .stApp { background:var(--poc-bg); color:var(--poc-ink); }
    [data-testid="stHeader"] { background:rgba(248,250,252,0.96); }
    .block-container { max-width:1440px; padding:1.15rem 1.55rem 2.25rem; }
    .poc-shell { background:transparent; border:0; padding:0; margin:0; }
    .poc-shell h1 { margin:0; color:var(--poc-ink); font-size:1.5rem; font-weight:800; letter-spacing:0; }
    .poc-shell p { margin:.18rem 0 0; color:var(--poc-muted); font-size:.84rem; }
    .poc-eyebrow { color:var(--poc-violet); font-weight:800; font-size:.71rem; letter-spacing:.08em; text-transform:uppercase; }
    .poc-chip { display:inline-flex; align-items:center; border-radius:4px; padding:.16rem .45rem;
      font-size:.69rem; font-weight:800; border:1px solid currentColor; margin-right:.25rem; }
    .poc-green { color:#15803d; background:#fff; } .poc-orange { color:#c2410c; background:#fff; }
    .poc-red, .poc-rose { color:#be123c; background:#fff; } .poc-violet { color:var(--poc-violet); background:#fff; }
    .poc-cyan { color:#0891b2; background:#fff; } .poc-amber { color:#b45309; background:#fff; }
    .poc-kpi { background:#fff; border:1px solid var(--poc-line); border-top:1px solid var(--poc-line);
      padding:.66rem .75rem; min-height:82px; }
    .poc-kpi[data-tone="violet"] { border-left:3px solid var(--poc-violet); } .poc-kpi[data-tone="green"] { border-left:3px solid var(--poc-green); }
    .poc-kpi[data-tone="orange"] { border-left:3px solid var(--poc-orange); } .poc-kpi[data-tone="rose"] { border-left:3px solid var(--poc-rose); }
    .poc-kpi[data-tone="blue"] { border-left:3px solid var(--poc-blue); } .poc-kpi[data-tone="cyan"] { border-left:3px solid var(--poc-cyan); }
    .poc-kpi-label { color:var(--poc-muted); font-size:.73rem; font-weight:800; text-transform:uppercase; letter-spacing:.045em; }
    .poc-kpi-value { color:var(--poc-ink); font-size:1.55rem; font-weight:850; line-height:1.15; margin-top:.2rem; }
    .poc-card { background:#fff; border:1px solid var(--poc-line); border-radius:6px; padding:.82rem; margin:.45rem 0; }
    .poc-card-subtle { background:#fff; border-left:3px solid var(--poc-violet); border-top:1px solid var(--poc-line); border-right:1px solid var(--poc-line); border-bottom:1px solid var(--poc-line); padding:.8rem .9rem; }
    .poc-muted { color:var(--poc-muted); font-size:.81rem; } .poc-mini { color:var(--poc-muted); font-size:.74rem; }
    .poc-section-title { color:var(--poc-ink); font-size:1.08rem; font-weight:850; margin:.9rem 0 .35rem; }
    .poc-validated { color:var(--poc-green); font-weight:850; }
    .poc-workflow { display:flex; gap:.28rem; align-items:center; flex-wrap:wrap; margin:0 0 .52rem; }
    .poc-workflow-step { color:var(--poc-muted); border-bottom:2px solid var(--poc-line); padding:.2rem .38rem; font-size:.72rem; font-weight:800; }
    .poc-workflow-step.active { color:var(--poc-violet); border-bottom-color:var(--poc-violet); }
    .poc-workflow-arrow { color:#94a3b8; font-size:.75rem; }
    .poc-setup { background:#fff; border:1px solid var(--poc-line); border-top:3px solid var(--poc-violet); padding:1.1rem 1.2rem; margin:0; }
    .poc-setup-grid { display:grid; grid-template-columns:1fr 1fr; gap:.65rem; margin:.75rem 0 1rem; }
    .poc-setup-item { border:1px solid var(--poc-line); border-radius:4px; padding:.72rem .8rem; background:#fff; }
    .poc-setup-item strong { display:block; color:var(--poc-ink); font-size:.82rem; margin-bottom:.18rem; }
    .poc-empty-note { color:var(--poc-muted); font-size:.82rem; margin:0 0 .85rem; }
    .poc-summary { background:#fff; border:1px solid var(--poc-line); padding:1.05rem; min-height:100%; }
    .poc-summary h2 { font-size:1rem; margin:0 0 .85rem; color:var(--poc-ink); }
    .poc-summary-grid { display:grid; grid-template-columns:1fr 1fr; gap:.6rem; }
    .poc-summary-metric { border:1px solid var(--poc-line); border-radius:4px; padding:.7rem; min-height:72px; }
    .poc-summary-metric strong { display:block; font-size:1.18rem; line-height:1.1; color:var(--poc-ink); }
    .poc-summary-metric span { display:block; margin-top:.27rem; font-size:.72rem; color:var(--poc-muted); }
    .poc-context-row { display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; margin:.65rem 0 .9rem; }
    .poc-context-chip { display:inline-flex; align-items:center; min-height:2.25rem; padding:.35rem .65rem; border:1px solid var(--poc-line); background:#fff; border-radius:5px; font-size:.79rem; color:#374151; }
    .poc-context-chip strong { color:var(--poc-ink); }
    .poc-context-chip.status::before { content:""; width:.48rem; height:.48rem; border-radius:50%; background:var(--poc-green); margin-right:.42rem; }
    .poc-photo-grid img { border:1px solid var(--poc-line); border-radius:4px; }
    .poc-surface-heading { display:flex; justify-content:space-between; align-items:center; gap:.8rem; flex-wrap:wrap; margin:0 0 .8rem; }
    .poc-surface-heading h2 { color:var(--poc-ink); font-size:1.08rem; margin:0; font-weight:850; }
    .poc-surface-heading p { color:var(--poc-muted); font-size:.78rem; margin:.2rem 0 0; }
    .poc-panel-label { color:var(--poc-muted); font-size:.7rem; font-weight:850; letter-spacing:.055em; text-transform:uppercase; margin:0 0 .5rem; }
    .poc-review-meta { display:flex; align-items:center; gap:.4rem; flex-wrap:wrap; margin:.12rem 0 .8rem; color:var(--poc-muted); font-size:.78rem; }
    .poc-review-photos { background:#fafafa; border:1px solid var(--poc-line); border-radius:8px; padding:.75rem; }
    .poc-candidate-title { margin:0 0 .58rem; color:var(--poc-ink); font-size:.96rem; font-weight:850; }
    .poc-action-note { color:var(--poc-muted); font-size:.73rem; margin:.45rem 0 0; }
    .poc-toolbar { display:flex; align-items:center; justify-content:space-between; gap:.7rem; border-top:1px solid var(--poc-line); margin-top:.9rem; padding-top:.8rem; }
    .poc-toolbar-caption { color:var(--poc-muted); font-size:.76rem; }
    .poc-filter-label { color:var(--poc-muted); font-size:.73rem; font-weight:800; margin:.1rem 0 .35rem; }
    .poc-table-row { display:grid; grid-template-columns:70px minmax(180px,1.65fr) minmax(120px,1fr) 100px; gap:.75rem; align-items:center; padding:.62rem 0; border-top:1px solid var(--poc-line); }
    .poc-group-row { display:grid; grid-template-columns:70px 88px minmax(180px,1fr) 96px 86px; gap:.7rem; align-items:center; padding:.65rem 0; border-top:1px solid var(--poc-line); }
    .poc-list-thumb { width:56px; height:56px; display:grid; place-items:center; border:1px solid var(--poc-line); border-radius:5px; overflow:hidden; background:#fafafa; color:var(--poc-muted); }
    .poc-list-thumb img { width:100%; height:100%; object-fit:cover; }
    .poc-photos-caption { color:var(--poc-muted); font-size:.7rem; margin:.26rem 0 .1rem; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-radius:9px; border-color:var(--poc-line); background:#fff; box-shadow:none; }
    div[data-testid="stButton"] > button { border-radius:5px; border-color:#d1d5db; font-weight:750; min-height:2.15rem; }
    div[data-testid="stButton"] > button[kind="primary"] { background:var(--poc-violet); border-color:var(--poc-violet); }
    div[data-testid="stButton"] > button[kind="secondary"]:hover { border-color:var(--poc-violet); color:var(--poc-violet); }
    div[data-testid="stRadio"] label { font-size:.82rem; font-weight:700; }
    div[data-testid="stNumberInput"] input, div[data-testid="stTextInput"] input { border-radius:5px; border-color:#d1d5db; }
    div[data-testid="stSelectbox"] [data-baseweb="select"] > div { border-radius:5px; border-color:#d1d5db; }
    div[data-testid="stExpander"] details { border:1px solid var(--poc-line); border-radius:5px; background:#fff; }
    .poc-product-meta { display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; margin:.32rem 0 .42rem; }
    .poc-product-meta span { color:var(--poc-muted); font-size:.82rem; }
    .poc-product-meta .poc-product-drop { color:var(--poc-ink); font-weight:760; }
    .poc-candidate-name { color:var(--poc-ink); font-size:1.08rem; font-weight:850; line-height:1.22; margin:0 0 .2rem; }
    .poc-candidate-identity { color:#374151; font-size:.87rem; font-weight:750; margin:0 0 .42rem; }
    .poc-score-secondary { color:var(--poc-muted); font-size:.72rem; margin:.45rem 0 0; }
    .poc-card-subtle strong { font-size:1rem; }
    [data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--poc-line); }
    @media (min-width: 901px) {
      [data-testid="stSidebar"] { min-width:225px !important; max-width:225px !important; }
      [data-testid="stSidebar"] > div:first-child { width:225px !important; }
    }
    [data-testid="stSidebar"] .block-container { padding:1.25rem .72rem 1rem; }
    .poc-nav-brand { font-size:1.22rem; font-weight:850; color:var(--poc-ink); padding:.1rem .55rem 1.5rem; }
    .poc-nav-brand span { color:var(--poc-violet); }
    .poc-nav-section { color:var(--poc-muted); font-size:.67rem; font-weight:800; letter-spacing:.06em; padding:.15rem .55rem .5rem; }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button { justify-content:flex-start; text-align:left; border:0; box-shadow:none; background:transparent; color:#374151; min-height:2.55rem; padding:.45rem .6rem; }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button:hover { background:#f3f4f6; color:var(--poc-ink); }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"] { background:#f3f0ff; color:var(--poc-violet); border-left:3px solid var(--poc-violet); border-radius:4px; }
    .poc-nav-hint { color:var(--poc-muted); font-size:.72rem; line-height:1.45; padding:.8rem .55rem; border-top:1px solid var(--poc-line); margin-top:1rem; }
    .poc-nav-footer { position:fixed; bottom:0; width:198px; padding:.75rem .55rem 1rem; background:#fff; border-top:1px solid var(--poc-line); }
    @media (max-width: 900px) {
      [data-testid="stSidebar"] { min-width:0 !important; max-width:none !important; }
      [data-testid="stSidebar"] > div:first-child { width:auto !important; }
    }
    @media (min-width: 701px) and (max-width: 900px) {
      section[data-testid="stMain"] { margin-left:-18.7rem !important; width:calc(100% + 18.7rem) !important; }
    }
    @media (max-width: 700px) {
      .block-container { padding: .85rem .8rem 1.5rem; }
      .poc-shell { padding:.8rem .85rem; } .poc-shell h1 { font-size:1.15rem; }
      .poc-kpi { min-height:70px; padding:.55rem; } .poc-kpi-value { font-size:1.16rem; }
      .poc-setup { padding:.85rem; } .poc-setup-grid { grid-template-columns:1fr; }
      .poc-summary { margin-top:.65rem; } .poc-nav-footer { position:static; width:auto; }
      .poc-toolbar { align-items:stretch; flex-direction:column; } .poc-table-row, .poc-group-row { grid-template-columns:56px 1fr; gap:.4rem .6rem; }
      .poc-table-row > :nth-child(n+3), .poc-group-row > :nth-child(n+3) { grid-column:2; }
      div[data-testid="stHorizontalBlock"] { gap:.45rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _rerun():
    st.rerun()


def _request_view(view_name: str):
    _stage_view(view_name)
    _rerun()


def _stage_view(view_name: str):
    """Stage a view change; callbacks get their normal Streamlit rerun for free."""
    primary_view, diagnostic_view = LEGACY_VIEW_ROUTES.get(view_name, (view_name, None))
    if primary_view in VIEW_OPTIONS:
        st.session_state["photo_poc_pending_view"] = primary_view
        if diagnostic_view:
            st.session_state["photo_poc_pending_diagnostic"] = diagnostic_view


def _navigate_view_callback(view_name: str):
    _stage_view(view_name)


def _apply_pending_view():
    current = st.session_state.get("photo_poc_view")
    if current in LEGACY_VIEW_ROUTES:
        primary_view, diagnostic_view = LEGACY_VIEW_ROUTES[current]
        st.session_state["photo_poc_view"] = primary_view
        if diagnostic_view:
            st.session_state["photo_poc_diagnostic_view"] = diagnostic_view
    pending = st.session_state.pop("photo_poc_pending_view", None)
    if pending in VIEW_OPTIONS:
        st.session_state["photo_poc_view"] = pending
    pending_diagnostic = st.session_state.pop("photo_poc_pending_diagnostic", None)
    if pending_diagnostic in DIAGNOSTIC_OPTIONS:
        st.session_state["photo_poc_diagnostic_view"] = pending_diagnostic


def _analysis_meta_for(
    *,
    folder: str,
    photos: list,
    drop_id: str | None,
    start_index: int,
    target_announcements: int,
    max_photos: int,
    candidate_signature: str = "",
) -> dict:
    start_index = max(1, int(start_index or 1))
    max_photos = max(1, int(max_photos or 1))
    photo_window = photos[start_index - 1 : start_index - 1 + max_photos]
    photo_signature = photo_window_signature(photo_window)
    return {
        "pipeline_version": POC_ANALYSIS_PIPELINE_VERSION,
        "folder": str(Path(folder).resolve()),
        "drop_id": drop_id,
        "start_index": start_index,
        "target_announcements": int(target_announcements or 0),
        "max_photos": int(max_photos or 0),
        "photo_count": len(photo_window),
        "photo_signature": photo_signature,
        "candidate_signature": candidate_signature,
    }


def _result_matches_analysis(result: dict | None, expected: dict) -> bool:
    if not isinstance(result, dict):
        return False
    meta = result.get("analysis_meta")
    if not isinstance(meta, dict):
        return False
    for key, value in expected.items():
        if key == "candidate_signature":
            continue
        if meta.get(key) != value:
            return False
    return True


def _save_sample(sample_key: str, sample: dict):
    update_ground_truth_sample(sample_key, sample)
    st.session_state[f"photo_poc_sample_{sample_key}"] = sample
    st.toast("Validation enregistrée")


def _load_sample(sample_key: str) -> dict:
    cached = st.session_state.get(f"photo_poc_sample_{sample_key}")
    if isinstance(cached, dict):
        return cached
    payload = load_poc_ground_truth()
    sample = payload.get("samples", {}).get(sample_key, {"groups": []})
    st.session_state[f"photo_poc_sample_{sample_key}"] = sample
    return sample


def _set_group_status(sample_key: str, group_id: str, status: str):
    sample = _load_sample(sample_key)
    for group in sample.get("groups", []) or []:
        if str(group.get("group_id")) == str(group_id):
            group["status"] = status
            break
    update_ground_truth_sample(sample_key, sample)
    st.session_state[f"photo_poc_sample_{sample_key}"] = sample


@st.cache_data(show_spinner=False)
def _cached_image_crop(path: str, kind: str, orientation_degrees: int, file_mtime_ns: int):
    del file_mtime_ns
    try:
        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")
            img.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            if orientation_degrees:
                img = img.rotate(-int(orientation_degrees), expand=True)
            w, h = img.size
            if kind == "name":
                return img.crop((0, 0, w, int(h * 0.36)))
            if kind == "number":
                return img.crop((0, int(h * 0.68), w, h))
            if kind == "artwork":
                return img.crop((int(w * 0.09), int(h * 0.16), int(w * 0.91), int(h * 0.64)))
            return img
    except Exception:
        return None


def _image_crop(path: str, kind: str, orientation_degrees: int = 0):
    try:
        file_mtime_ns = Path(path).stat().st_mtime_ns
    except OSError:
        file_mtime_ns = 0
    return _cached_image_crop(path, kind, int(orientation_degrees or 0), file_mtime_ns)


@st.cache_data(show_spinner=False)
def _thumbnail_bytes(path: str, max_height: int = 300) -> bytes:
    with Image.open(path) as raw:
        img = ImageOps.exif_transpose(raw).convert("RGB")
        ratio = max_height / max(1, img.height)
        img = img.resize((max(1, int(img.width * ratio)), max_height), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=82)
        return buffer.getvalue()


def _render_metrics(metrics: dict):
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Photos", metrics.get("photos_analyzed", 0))
    k2.metric("Annonces", metrics.get("announcements_detected", 0))
    k3.metric("Primary front", metrics.get("primary_front", 0))
    k4.metric("Multi-cartes", metrics.get("multi_card_fronts", 0))
    k5.metric("Candidats", metrics.get("candidate_cards", 0))
    k6.metric("Temps", f"{metrics.get('duration_seconds', 0)} s")

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Dos occidentaux", metrics.get("back_western", 0))
    b2.metric("Dos japonais", metrics.get("back_japanese", 0))
    b3.metric("Backs inférés", metrics.get("back_inferred_by_sequence", 0))
    b4.metric("Grouping à vérifier", metrics.get("grouping_to_review", 0))

    o1, o2, o3, o4 = st.columns(4)
    o1.metric("OCR nom", metrics.get("ocr_name_detected", 0))
    o2.metric("OCR numéro", metrics.get("ocr_number_detected", 0))
    o3.metric("OCR nom + numéro", metrics.get("ocr_both_detected", 0))
    o4.metric("OCR inutilisable", metrics.get("ocr_unusable", 0))

    m1, m2, m3 = st.columns(3)
    m1.metric("Reconnu", metrics.get("auto_recognized", 0))
    m2.metric("À vérifier", metrics.get("to_review", 0))
    m3.metric("Non reconnu", metrics.get("unrecognized", 0))


def _manual_validation_summary(sample: dict, result: dict | None = None) -> dict:
    review_fixed = 0
    fail_fixed = 0
    green_checked = 0
    green_wrong = 0
    manual_choices = 0
    group_by_id = {}
    if result:
        for group in result.get("groups", []) or []:
            group_id = _result_group_id(group)
            group_by_id[group_id] = group
    for group in sample.get("groups", []) or []:
        group_id = str(group.get("group_id") or "")
        result_group = group_by_id.get(group_id) or {}
        level = result_group.get("confidence_level")
        matches = result_group.get("matches", []) or []
        for match_index, match in enumerate(matches):
            validation = _recognition_validation(sample, group_id, match_index, match)
            state = _validation_state(validation, match)
            if state.get("state") not in {"compatible", "explicit_truth"}:
                continue
            status = state.get("status")
            if level == "orange":
                review_fixed += 1
            elif level == "red":
                fail_fixed += 1
            elif level == "green":
                green_checked += 1
                if not state.get("resolved_correct"):
                    green_wrong += 1
            if status == "manual_choice":
                manual_choices += 1
    return {
        "review_fixed": review_fixed,
        "fail_fixed": fail_fixed,
        "green_checked": green_checked,
        "green_wrong": green_wrong,
        "manual_choices": manual_choices,
    }


def _validation_bilan(sample: dict, result: dict) -> dict:
    controlled_groups = 0
    auto_checked = 0
    auto_correct = 0
    auto_wrong = 0
    jp_correct = 0
    jp_wrong = 0
    multi_correct = 0
    multi_wrong = 0
    review_fixed = 0
    fail_fixed = 0
    not_in_drop = 0
    prepared_additions = 0
    manual_choices = 0
    for group in result.get("groups", []) or []:
        group_id = _result_group_id(group)
        source = _source_group(sample, group_id)
        matches = group.get("matches", []) or []
        group_level = str(group.get("confidence_level") or "")
        if _recognition_is_done(sample, group_id, matches):
            controlled_groups += 1
        is_multi = len(matches) > 1 or int(group.get("expected_cards") or 1) > 1
        is_jp = bool(group.get("v13_japanese_candidate")) or str(group.get("v13_back_type") or "").startswith("back_japanese")
        group_wrong = False
        group_done = bool(matches)
        for match_index, match in enumerate(matches):
            validation = _recognition_validation(sample, group_id, match_index, match)
            state = _validation_state(validation, match)
            if state.get("state") not in {"compatible", "explicit_truth"}:
                group_done = False
                continue
            status = state.get("status")
            group_wrong = group_wrong or not state.get("resolved_correct")
            # The validation report describes the current V14 decision. Older
            # per-match status snapshots may predate V10/V13 safety overlays and
            # must not turn reviewed cases back into apparent automatic matches.
            if group_level == "green":
                auto_checked += 1
                if not state.get("resolved_correct"):
                    auto_wrong += 1
                else:
                    auto_correct += 1
            elif group_level == "orange":
                review_fixed += 1
            else:
                fail_fixed += 1
            manual_choices += int(status == "manual_choice")
            not_in_drop += int(bool(match.get("v13_not_in_drop_confidence")))
        if is_jp and group_done:
            jp_wrong += int(group_wrong)
            jp_correct += int(not group_wrong)
        if is_multi and group_done:
            multi_wrong += int(group_wrong)
            multi_correct += int(not group_wrong)
        prepared_additions += len(source.get("prepared_drop_additions") or {})
    return {
        "controlled_groups": controlled_groups,
        "total_groups": len(result.get("groups", []) or []),
        "auto_checked": auto_checked,
        "auto_correct": auto_correct,
        "auto_wrong": auto_wrong,
        "review_fixed": review_fixed,
        "fail_fixed": fail_fixed,
        "grouping_corrected": sum(1 for group in sample.get("groups", []) or [] if group.get("status") == "corrected"),
        "jp_correct": jp_correct,
        "jp_wrong": jp_wrong,
        "multi_correct": multi_correct,
        "multi_wrong": multi_wrong,
        "not_in_drop": not_in_drop,
        "prepared_additions": prepared_additions,
        "manual_corrections": manual_choices + prepared_additions,
    }


def _match_primary_candidate(match: dict) -> dict:
    return (((match.get("candidates") or [{}])[0]).get("candidate") or {})


def _ground_truth_error_rows(result: dict, sample: dict) -> list[dict]:
    rows = []
    for group in result.get("groups", []) or []:
        group_id = _result_group_id(group)
        for match_index, match in enumerate(group.get("matches", []) or []):
            validation = _recognition_validation(sample, group_id, match_index, match)
            state = _validation_state(validation, match)
            if state.get("state") not in {"compatible", "explicit_truth"} or state.get("resolved_correct"):
                continue
            candidate = _match_primary_candidate(match)
            rows.append(
                {
                    "annonce": group.get("announcement_index"),
                    "photos": " ".join(str(photo.get("capture_index")) for photo in _group_photo_payloads(group)),
                    "niveau_v9": group.get("v9_confidence_level") or group.get("confidence_level"),
                    "niveau_v10": group.get("confidence_level"),
                    "proposition": f"{candidate.get('name') or '—'} · {candidate.get('number') or '—'}",
                    "variante": _variant_label(candidate) if candidate else "—",
                    "score": match.get("score"),
                    "marge": match.get("margin"),
                    "cause": match.get("v10_safety_reason") or match.get("diagnostic_reason") or "validation utilisateur: faux",
                    "ocr_nom": " / ".join((match.get("ocr") or {}).get("name_texts") or []),
                    "ocr_numéro": " / ".join((match.get("ocr") or {}).get("collector_number_texts") or (match.get("ocr") or {}).get("number_texts") or []),
                }
            )
    return rows


def _apply_v10_ground_truth_overlay(result: dict, sample: dict):
    false_green_downgraded = 0
    checked_auto = 0
    correct_auto = 0
    wrong_auto = 0
    jp_detected = 0
    jp_wrong = 0
    multi_groups = 0
    special_layout = 0
    missing_front = 0
    not_in_drop_strong = 0
    not_in_drop_possible = 0
    for group in result.get("groups", []) or []:
        group_id = _result_group_id(group)
        source = _source_group(sample, group_id)
        validations = source.get("recognition_validation") or {}
        group.setdefault("v9_confidence_level", group.get("confidence_level"))
        if int(group.get("expected_cards") or 1) > 1 or len(group.get("matches", []) or []) > 1:
            multi_groups += 1
        if not group.get("primary_front"):
            missing_front += 1
        group_has_jp = False
        group_has_special = False
        group_not_in_drop_strong = False
        group_not_in_drop_possible = False
        for match_index, match in enumerate(group.get("matches", []) or []):
            match.setdefault("v10_original_status", match.get("status"))
            candidate = _match_primary_candidate(match)
            group_has_jp = (
                group_has_jp
                or bool(candidate.get("japanese"))
                or bool(source.get("jp_physical"))
                or str(group.get("v13_back_type") or "").startswith("back_japanese")
            )
            layout_type = str(match.get("layout_type") or "standard").upper()
            group_has_special = group_has_special or (
                layout_type in {"LEGEND_HALF", "UNKNOWN_SPECIAL"}
                or (bool(match.get("special_layout")) and layout_type != "V_UNION")
            )
            if match.get("v13_not_in_drop_confidence") == "strong":
                group_not_in_drop_strong = True
            elif match.get("v13_not_in_drop_confidence") == "possible":
                group_not_in_drop_possible = True
            validation = _recognition_validation(sample, group_id, match_index, match)
            validation_state = _validation_state(validation, match)
            original_status = match.get("v10_original_status") or match.get("status")
            if original_status == "recognized" and validation_state.get("state") in {"compatible", "explicit_truth"}:
                checked_auto += 1
                if validation_state.get("resolved_correct"):
                    correct_auto += 1
                else:
                    wrong_auto += 1
            if (
                validation_state.get("state") in {"compatible", "explicit_truth"}
                and not validation_state.get("resolved_correct")
                and original_status == "recognized"
            ):
                false_green_downgraded += 1
                match["status"] = "review"
                match["v10_safety_reason"] = "validation terrain: vert V9 faux, revue obligatoire"
                match["diagnostic_reason"] = match["v10_safety_reason"]
                group["confidence_level"] = "orange"
        if group_has_jp:
            jp_detected += 1
            if any(
                not _validation_state(
                    _recognition_validation(sample, group_id, idx, current_match),
                    current_match,
                ).get("resolved_correct")
                and _validation_state(
                    _recognition_validation(sample, group_id, idx, current_match),
                    current_match,
                ).get("state") in {"compatible", "explicit_truth"}
                for idx, current_match in enumerate(group.get("matches", []) or [])
            ):
                jp_wrong += 1
        if group_has_special:
            special_layout += 1
        if group_not_in_drop_strong:
            not_in_drop_strong += 1
        elif group_not_in_drop_possible:
            not_in_drop_possible += 1
    metrics = result.setdefault("metrics", {})
    metrics["auto_recognized"] = sum(1 for group in result.get("groups", []) or [] if group.get("confidence_level") == "green")
    metrics["to_review"] = sum(1 for group in result.get("groups", []) or [] if group.get("confidence_level") == "orange")
    metrics["unrecognized"] = sum(1 for group in result.get("groups", []) or [] if group.get("confidence_level") == "red")
    metrics["v10_false_green_downgraded"] = false_green_downgraded
    metrics["v10_checked_auto"] = checked_auto
    metrics["v10_correct_auto"] = correct_auto
    metrics["v10_wrong_auto_before_overlay"] = wrong_auto
    metrics["v10_jp_candidate_groups"] = jp_detected
    metrics["v10_jp_wrong_groups"] = jp_wrong
    metrics["v10_multi_card_groups"] = multi_groups
    metrics["v10_special_layout_groups"] = special_layout
    metrics["v10_missing_front_groups"] = missing_front
    metrics["v10_not_in_drop_groups"] = not_in_drop_strong + not_in_drop_possible
    metrics["v13_not_in_drop_strong"] = not_in_drop_strong
    metrics["v13_not_in_drop_possible"] = not_in_drop_possible
    diagnostic_causes = {}
    for group in result.get("groups", []) or []:
        if group.get("confidence_level") == "green":
            continue
        prefix = "grouping à vérifier + " if group.get("grouping_status") == "review" else ""
        for match in group.get("matches", []) or []:
            reason = prefix + str(match.get("diagnostic_reason") or "à vérifier")
            diagnostic_causes[reason] = diagnostic_causes.get(reason, 0) + 1
        if not group.get("matches"):
            reason = prefix + ("recto manquant" if not group.get("primary_front") else "aucune zone reconnue")
            diagnostic_causes[reason] = diagnostic_causes.get(reason, 0) + 1
    metrics["diagnostic_causes"] = diagnostic_causes


def _render_overview(result: dict, sample: dict):
    metrics = result.get("metrics") or {}
    bilan = _validation_bilan(sample, result)
    total = max(1, int(metrics.get("announcements_detected") or 0))
    pending = sum(
        1
        for group in result.get("groups", []) or []
        if group.get("confidence_level") != "green"
        and not _recognition_is_done(sample, _result_group_id(group), group.get("matches", []) or [])
    )
    kpis = [
        ("Photos", metrics.get("photos_analyzed", 0), "violet"),
        ("Annonces", metrics.get("announcements_detected", 0), "blue"),
        ("Auto", metrics.get("auto_recognized", 0), "green"),
        ("À vérifier", metrics.get("to_review", 0), "orange"),
        ("Non reconnus", metrics.get("unrecognized", 0), "rose"),
    ]
    cols = st.columns(5)
    for column, (label, value, tone) in zip(cols, kpis):
        with column:
            _render_kpi(label, value, tone=tone)

    secondary = st.columns(4)
    secondary[0].caption(f"JP · {metrics.get('v13_japanese_candidate_groups', metrics.get('v10_jp_candidate_groups', 0))}")
    secondary[1].caption(f"Multi · {metrics.get('v10_multi_card_groups', metrics.get('multi_card_fronts', 0))}")
    secondary[2].caption(f"Grouping reviews · {metrics.get('grouping_to_review', 0)}")
    secondary[3].caption(
        f"Not in Drop · {metrics.get('v13_not_in_drop_strong', 0) + metrics.get('v13_not_in_drop_possible', 0)}"
    )

    progress = min(1.0, bilan["controlled_groups"] / total)
    st.markdown("<div class='poc-section-title'>Progression de contrôle</div>", unsafe_allow_html=True)
    st.progress(progress, text=f"{bilan['controlled_groups']} / {total} annonces contrôlées")

    action_left, action_right = st.columns([3, 1])
    with action_left:
        st.markdown(
            f"<div class='poc-card-subtle'><strong>À faire maintenant</strong><div class='poc-muted'>"
            f"{pending} cas nécessitent encore ton attention. Les résultats reconnus restent consultables sans alourdir la file.</div></div>",
            unsafe_allow_html=True,
        )
    with action_right:
        st.button("Continuer la vérification", type="primary", use_container_width=True, on_click=_navigate_view_callback, args=("À vérifier",))


def _review_workspace_groups(result: dict, sample: dict) -> list[dict]:
    return [
        group
        for group in result.get("groups", []) or []
        if group.get("confidence_level") in {"orange", "red"}
        and not _recognition_is_done(sample, _result_group_id(group), group.get("matches", []) or [])
    ]


@st.fragment
def _render_review_workspace(sample_key: str, sample: dict, result: dict):
    groups = _review_workspace_groups(result, sample)
    if not groups:
        st.success("Toutes les annonces à vérifier sont traitées.")
        st.button("Voir la vue d’ensemble", on_click=_navigate_view_callback, args=("Vue d’ensemble",))
        return
    index_key = "photo_poc_review_workspace_index"
    st.session_state[index_key] = min(int(st.session_state.get(index_key, 0) or 0), len(groups) - 1)
    current_index = st.session_state[index_key]
    group = groups[current_index]
    group_id = _result_group_id(group)
    matches = group.get("matches", []) or []
    _render_review_surface(
        sample_key, sample, result, group, index_key=index_key, current_index=current_index,
        group_count=len(groups), key_prefix="review", heading="À vérifier",
    )


def _render_review_surface(
    sample_key: str,
    sample: dict,
    result: dict,
    group: dict,
    *,
    index_key: str,
    current_index: int,
    group_count: int,
    key_prefix: str,
    heading: str,
    badges: list[str] | None = None,
):
    """One compact review surface shared by the main and sensitive queues."""
    group_id = _result_group_id(group)
    matches = group.get("matches", []) or []
    expected_cards = int(group.get("expected_cards") or 1)
    badges_html = "".join(
        f"<span class='poc-chip {tone}'>{label}</span>"
        for label, tone in (badges or [])
    )
    with st.container(border=True):
        st.markdown(
            "<div class='poc-surface-heading'><div>"
            f"<h2>{heading} <span class='poc-muted'>· {current_index + 1} / {group_count}</span></h2>"
            f"<p>Annonce #{group.get('announcement_index')} · {expected_cards} carte(s)</p>"
            f"</div><div>{badges_html}</div></div>",
            unsafe_allow_html=True,
        )
        photos_col, proposal_col = st.columns([1.18, 1], gap="large")
        with photos_col:
            st.markdown("<div class='poc-panel-label'>Photos physiques</div>", unsafe_allow_html=True)
            _render_group_photos(
                {"photos": _group_photo_payloads(group)}, _photo_path_by_key(result), compact=True,
            )
        with proposal_col:
            st.markdown("<div class='poc-panel-label'>Identification</div>", unsafe_allow_html=True)
            if not matches:
                st.warning("Recto ou zone carte indisponible pour cette annonce.")
            elif len(matches) == 1:
                _render_status_chip(group.get("confidence_level", "red"))
                st.markdown("<div class='poc-candidate-title'>Carte proposée</div>", unsafe_allow_html=True)
                _render_candidate_summary(
                    matches[0], sample_key=sample_key, sample=sample, group_id=group_id, match_index=0,
                )
                _render_match_actions(
                    sample_key, sample, group_id, 0, matches[0], index_key=index_key,
                    current_index=current_index, group_count=group_count, matches=matches, key_prefix=key_prefix,
                    show_next=False,
                )
            else:
                st.markdown(f"<div class='poc-candidate-title'>{len(matches)} sous-cartes</div>", unsafe_allow_html=True)
                card_cols = st.columns(min(2, len(matches)))
                for match_index, match in enumerate(matches):
                    with card_cols[match_index % len(card_cols)]:
                        st.markdown(f"<div class='poc-panel-label'>Carte {match_index + 1}</div>", unsafe_allow_html=True)
                        _render_candidate_summary(
                            match, compact=True, sample_key=sample_key, sample=sample,
                            group_id=group_id, match_index=match_index,
                        )
                        _render_match_actions(
                            sample_key, sample, group_id, match_index, match, index_key=index_key,
                            current_index=current_index, group_count=group_count, matches=matches,
                            key_prefix=f"{key_prefix}_multi", show_next=False,
                        )
            if matches:
                with st.expander("Détails de reconnaissance", expanded=False):
                    for match_index, match in enumerate(matches):
                        _render_match_debug(match, sample_key, sample, group_id, match_index, result.get("candidates", []))
        st.markdown("<div class='poc-toolbar'></div>", unsafe_allow_html=True)
        previous_col, spacer_col, next_col = st.columns([1, 3, 1])
        previous_col.button(
            "← Précédent", key=f"{key_prefix}_previous_{group_id}", disabled=current_index == 0,
            use_container_width=True, on_click=_set_queue_index, args=(index_key, current_index - 1),
        )
        spacer_col.markdown("<div class='poc-toolbar-caption'>Validation enregistrée instantanément</div>", unsafe_allow_html=True)
        next_col.button(
            "Suivant →", key=f"{key_prefix}_next_{group_id}", disabled=current_index >= group_count - 1,
            use_container_width=True, on_click=_set_queue_index,
            args=(index_key, min(group_count - 1, current_index + 1)),
        )


def _validated_groups(result: dict, sample: dict, query: str) -> list[dict]:
    query = _fold_text(query)
    rows = []
    for group in result.get("groups", []) or []:
        matches = group.get("matches", []) or []
        if not matches or not _recognition_is_resolved_correct(sample, _result_group_id(group), matches):
            continue
        candidate_text = " ".join(
            f"{_match_primary_candidate(match).get('name', '')} {_match_primary_candidate(match).get('number', '')}"
            for match in matches
        )
        if query and query not in _fold_text(candidate_text):
            continue
        rows.append(group)
    return rows


def _render_validated_view(sample: dict, result: dict):
    with st.container(border=True):
        st.markdown("<div class='poc-surface-heading'><div><h2>Validés</h2><p>Les annonces confirmées, dans un format de gestion compact.</p></div></div>", unsafe_allow_html=True)
        query = st.text_input("Rechercher une carte validée", placeholder="Nom ou numéro", key="photo_poc_validated_query")
        groups = _validated_groups(result, sample, query)
        page_size = 18
        max_page = max(1, math.ceil(len(groups) / page_size))
        pager_left, pager_right = st.columns([4, 1])
        pager_left.caption(f"{len(groups)} annonce(s) validée(s)")
        page = pager_right.number_input("Page", min_value=1, max_value=max_page, value=1, key="photo_poc_validated_page", label_visibility="collapsed")
        visible = groups[(int(page) - 1) * page_size : int(page) * page_size]
        path_by_key = _photo_path_by_key(result)
        for group in visible:
            match = (group.get("matches") or [{}])[0]
            candidate = _match_primary_candidate(match)
            photo = match.get("photo")
            thumb = ""
            if photo and (path := path_by_key.get(photo_key(photo))):
                try:
                    thumb = base64.b64encode(_thumbnail_bytes(path, 120)).decode("ascii")
                except Exception:
                    thumb = ""
            image_html = f"<img src='data:image/jpeg;base64,{thumb}' />" if thumb else "<span>—</span>"
            st.markdown(
                "<div class='poc-table-row'><div class='poc-list-thumb'>" + image_html + "</div>"
                f"<div><strong>{candidate.get('name') or 'Carte'}</strong><div class='poc-mini'>{candidate.get('number') or '—'} · {candidate.get('set') or '—'}</div></div>"
                f"<div class='poc-mini'>{_variant_label(candidate)}</div><div><span class='poc-chip poc-green'>Validé</span></div></div>",
                unsafe_allow_html=True,
            )


def _render_grouping_workspace(result: dict):
    with st.container(border=True):
        st.markdown("<div class='poc-surface-heading'><div><h2>Grouping</h2><p>Une ligne par annonce, les photos détaillées seulement à l’ouverture.</p></div></div>", unsafe_allow_html=True)
        filter_name = st.pills(
            "Filtre grouping", ["Tous", "Reviews", "Multi"], selection_mode="single", default="Tous",
            key="photo_poc_grouping_filter", label_visibility="collapsed",
        ) or "Tous"
        groups = result.get("groups", []) or []
        if filter_name == "Reviews":
            groups = [group for group in groups if group.get("grouping_status") == "review"]
        elif filter_name == "Multi":
            groups = [group for group in groups if int(group.get("expected_cards") or 1) > 1]
        st.caption(f"{len(groups)} groupe(s) affiché(s)")
        path_by_key = _photo_path_by_key(result)
        for group in groups:
            photo_payloads = _group_photo_payloads(group)
            captures = [photo.get("capture_index") for photo in photo_payloads]
            status = "GROUPING" if group.get("grouping_status") == "review" else "OK"
            kind = "MULTI" if int(group.get("expected_cards") or 1) > 1 else "SIMPLE"
            st.markdown(
                f"<div class='poc-group-row'><div><strong>#{group.get('announcement_index')}</strong></div>"
                f"<div class='poc-mini'>{len(photo_payloads)} photos<br>{group.get('expected_cards', 1)} carte(s)</div>"
                f"<div class='poc-mini'>{' · '.join(str(value) for value in captures)}</div>"
                f"<div><span class='poc-chip {'poc-orange' if status == 'GROUPING' else 'poc-green'}'>{status}</span></div>"
                f"<div><span class='poc-chip poc-violet'>{kind}</span></div></div>",
                unsafe_allow_html=True,
            )
            with st.expander(f"Voir les photos · groupe {group.get('announcement_index')}", expanded=False):
                _render_group_photos({"photos": photo_payloads}, path_by_key, compact=True)


def _render_diagnostic_view(sample_key: str, sample: dict, result: dict):
    selected = st.selectbox(
        "Diagnostic",
        DIAGNOSTIC_OPTIONS,
        key="photo_poc_diagnostic_view",
    )
    if selected == "Résultats / debug reconnaissance":
        _render_results_view(sample_key, sample, result)
    elif selected == "Erreurs uniquement":
        _render_errors_view(sample_key, sample, result)
    elif selected == "Propositions modifiées":
        _render_changed_proposals_view(sample_key, sample, result)
    elif selected == "Cas japonais":
        _render_v13_japanese_cases(result)
    elif selected == "Nouveaux autos":
        _render_v13_new_autos(result)
    elif selected == "Validation des groupes":
        _render_validation_view(sample_key, sample, result)
    elif selected == "Contrôle verts":
        _render_green_quality_view(sample_key, sample, result)
    elif selected == "Vérification complète":
        _render_full_check_view(sample_key, sample, result)
    elif selected == "Métriques historiques":
        _render_full_summary(result, sample)
    elif selected == "Ordre de capture":
        st.dataframe(
            [
                {
                    "capture_index": photo.capture_index,
                    "filename": photo.filename,
                    "capture_datetime": photo.capture_datetime,
                    "source": photo.order_source,
                    "taille Mo": round(photo.size_bytes / 1024 / 1024, 2),
                }
                for photo in result.get("ordered_photos", []) or []
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        metrics = result.get("metrics") or {}
        st.markdown("<div class='poc-section-title'>Pipeline et cache</div>", unsafe_allow_html=True)
        cols = st.columns(4)
        cols[0].metric("Cache persistant", "Actif" if metrics.get("persistent_cache_hit") else "Écrit")
        cols[1].metric("Restauration", f"{metrics.get('persistent_cache_restore_seconds', 0)} s")
        cols[2].metric("Refresh Drop", f"{metrics.get('candidate_refresh_seconds', 0)} s")
        cols[3].metric("Groupes rematchés", metrics.get("candidate_groups_rematched", 0))
        st.json({
            "pipeline": result.get("analysis_meta", {}).get("pipeline_version"),
            "matching": result.get("analysis_meta", {}).get("matching_refresh_version"),
            "metrics": {key: value for key, value in metrics.items() if isinstance(value, (str, int, float, bool))},
        })


def _render_full_summary(result: dict, sample: dict):
    metrics = result.get("metrics") or {}
    st.markdown("### Synthèse complète")
    _render_metrics(metrics)
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Taux auto", f"{round(metrics.get('auto_recognized', 0) / max(1, metrics.get('announcements_detected', 0)) * 100, 1)} %")
    s2.metric("JP détectées", metrics.get("back_japanese", 0))
    s3.metric("Multi-cartes", metrics.get("multi_card_fronts", 0))
    s4.metric("Temps / annonce", f"{metrics.get('avg_seconds_per_announcement', 0)} s")

    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Photos / annonce", metrics.get("photos_per_announcement", "—"))
    g2.metric("Écart ordre ~90", metrics.get("expected_announcements_delta", "—"))
    g3.metric("Groupes 1 photo", metrics.get("one_photo_groups", 0))
    g4.metric("Grouping review", metrics.get("grouping_to_review", 0))

    vg1, vg2 = st.columns(2)
    vg1.metric("Fusions V11 singles", metrics.get("v11_single_fusions", 0))
    vg2.metric("Singles restants", metrics.get("one_photo_groups", 0))
    single_reasons = metrics.get("v11_single_unmerged_reasons") or {}
    if single_reasons:
        with st.expander("Singles non fusionnés V11", expanded=False):
            st.dataframe(
                [{"raison": reason, "cas": count} for reason, count in sorted(single_reasons.items(), key=lambda item: item[1], reverse=True)],
                width="stretch",
                hide_index=True,
            )

    manual = _manual_validation_summary(sample, result)
    v1, v2, v3, v4 = st.columns(4)
    v1.metric("Reviews corrigées", manual["review_fixed"])
    v2.metric("Fails corrigés", manual["fail_fixed"])
    v3.metric("Verts contrôlés", manual["green_checked"])
    v4.metric("Verts faux", manual["green_wrong"])
    if manual["green_checked"]:
        st.caption(f"Précision observée : {manual['green_checked'] - manual['green_wrong']} / {manual['green_checked']} autos contrôlés.")

    st.markdown("#### Bilan de validation")
    ground_truth_state = _ground_truth_state(sample, result)
    st.caption("État du ground truth — seules les validations compatibles avec la proposition actuelle alimentent le bilan.")
    gt1, gt2, gt3, gt4 = st.columns(4)
    gt1.metric("Validations compatibles", ground_truth_state.get("compatible", 0))
    gt2.metric("Vérités explicites", ground_truth_state.get("explicit_truth", 0))
    gt3.metric("Validations stales", ground_truth_state.get("stale", 0))
    gt4.metric("Cas restant à revoir", ground_truth_state.get("remaining", 0))
    bilan = _validation_bilan(sample, result)
    b1, b2, b3, b4, b5 = st.columns(5)
    b1.metric("Annonces contrôlées", f"{bilan['controlled_groups']} / {bilan['total_groups']}")
    b2.metric("Autos contrôlés", bilan["auto_checked"])
    b3.metric("Autos corrects", bilan["auto_correct"])
    b4.metric("Autos faux", bilan["auto_wrong"])
    b5.metric("Corrections utilisateur", bilan["manual_corrections"])
    if bilan["auto_checked"]:
        st.success(
            f"Précision auto observée : {bilan['auto_correct']} / {bilan['auto_checked']} autos contrôlés. "
            "Cette mesure décrit les validations disponibles; elle ne constitue pas une garantie à 100 %."
        )
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Reviews corrigées", bilan["review_fixed"])
    d2.metric("Fails corrigés", bilan["fail_fixed"])
    d3.metric("Grouping corrigés", bilan["grouping_corrected"])
    d4.metric("Not in Drop", bilan["not_in_drop"])
    st.caption(
        f"JP corrects/faux : {bilan['jp_correct']} / {bilan['jp_wrong']} · "
        f"Multi corrects/faux : {bilan['multi_correct']} / {bilan['multi_wrong']} · "
        f"Ajouts au Drop préparés (POC) : {bilan['prepared_additions']}"
    )
    st.caption(
        f"Régressions autos observées sur la baseline validée : {manual['green_wrong']} · "
        f"autos protégés et toujours corrects : {manual['green_checked'] - manual['green_wrong']}"
    )

    vm1, vm2, vm3 = st.columns(3)
    vm1.metric("Cas visuels", metrics.get("visual_matching_cases", 0))
    vm2.metric("Visuel large", metrics.get("visual_matching_broad_cases", 0))
    vm3.metric("Temps visuel", f"{metrics.get('visual_matching_seconds', 0)} s")

    vt1, vt2, vt3, vt4 = st.columns(4)
    vt1.metric("Faux verts V9 corrigés", metrics.get("v10_false_green_downgraded", 0))
    vt2.metric("JP candidats", metrics.get("v13_japanese_candidate_groups", metrics.get("v10_jp_candidate_groups", 0)))
    vt3.metric("Multi-cartes V10", metrics.get("v10_multi_card_groups", 0))
    vt4.metric("Spéciaux / LÉGENDE", metrics.get("v10_special_layout_groups", 0))

    vx1, vx2, vx3 = st.columns(3)
    vx1.metric("Recto manquant", metrics.get("v10_missing_front_groups", 0))
    vx2.metric("Absent du Drop · fort", metrics.get("v13_not_in_drop_strong", 0))
    vx3.metric("Absent du Drop · possible", metrics.get("v13_not_in_drop_possible", 0))

    jp1, jp2, jp3, jp4 = st.columns(4)
    jp1.metric("Versos JP confirmés", metrics.get("v13_back_japanese", 0))
    jp2.metric("Signaux JAP", metrics.get("v13_back_japanese_candidates", 0))
    jp3.metric("JP auto / review", f"{metrics.get('v13_japanese_auto', 0)} / {metrics.get('v13_japanese_review', 0)}")
    jp4.metric("Conflits langue", metrics.get("v13_japanese_conflicts", 0))

    causes = metrics.get("v13_non_auto_causes") or metrics.get("diagnostic_causes") or {}
    if causes:
        st.markdown("#### Causes principales orange/rouge")
        st.dataframe(
            [{"cause": cause, "cas": count} for cause, count in sorted(causes.items(), key=lambda item: item[1], reverse=True)],
            width="stretch",
            hide_index=True,
        )

    gt_errors = _ground_truth_error_rows(result, sample)
    if gt_errors:
        st.markdown("#### Erreurs V9 vs vérité terrain")
        st.dataframe(gt_errors, width="stretch", hide_index=True)

    new_auto_rows = []
    for group in result.get("groups", []) or []:
        for match in group.get("matches", []) or []:
            reason = match.get("v13_auto_reason")
            reason = reason or match.get("v8_auto_reason")
            reason = match.get("v9_auto_reason") or reason
            if not reason:
                continue
            candidate = (((match.get("candidates") or [{}])[0]).get("candidate") or {})
            new_auto_rows.append(
                {
                    "annonce": group.get("announcement_index"),
                    "photos": " ".join(str(photo.get("capture_index")) for photo in _group_photo_payloads(group)),
                    "carte": candidate.get("name"),
                    "numéro": candidate.get("number"),
                    "score": match.get("score"),
                    "marge": match.get("margin"),
                    "visuel": (((match.get("candidates") or [{}])[0]).get("visual_artwork_score") or ((match.get("candidates") or [{}])[0]).get("visual_score")),
                    "raison": reason,
                }
            )
    if new_auto_rows:
        st.markdown("#### Nouveaux autos V8/V9/V13")
        st.dataframe(new_auto_rows, width="stretch", hide_index=True)

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Voir les erreurs", type="primary"):
        _request_view("File à vérifier" if metrics.get("to_review", 0) else "File non reconnus")
    if c2.button("Carte du grouping"):
        _request_view("Carte du grouping")
    if c3.button("Voir les reconnaissances"):
        _request_view("Résultats / debug reconnaissance")
    if c4.button("Tout afficher"):
        _request_view("Résultats / debug reconnaissance")


def _render_v13_japanese_cases(result: dict):
    metrics = result.get("metrics") or {}
    st.markdown("### Cas japonais")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Versos JP confirmés", metrics.get("v13_back_japanese", 0))
    c2.metric("Signaux JAP", metrics.get("v13_back_japanese_candidates", 0))
    c3.metric("JP auto / review", f"{metrics.get('v13_japanese_auto', 0)} / {metrics.get('v13_japanese_review', 0)}")
    c4.metric("JP fail", metrics.get("v13_japanese_fail", 0))
    st.caption("Un signal JAP ne devient pas automatiquement un verso JP : les conflits restent en vérification.")

    path_by_key = _photo_path_by_key(result)
    cases = [
        group
        for group in result.get("groups", []) or []
        if group.get("v13_japanese_candidate") or str(group.get("v13_back_type") or "").startswith("back_japanese")
    ]
    for group in cases:
        top = _match_primary_candidate((group.get("matches") or [{}])[0])
        label = (
            f"Annonce #{group.get('announcement_index')} · {group.get('v13_back_type')} · "
            f"{top.get('name') or 'sans candidat'} · {group.get('confidence_level')}"
        )
        with st.expander(label, expanded=False):
            st.caption(
                f"Verso : {group.get('v13_back_reason') or '—'} · scores {group.get('v13_back_scores') or {}} · "
                f"conflit : {group.get('v13_language_conflict') or 'aucun'}"
            )
            _render_group_photos({"photos": _group_photo_payloads(group)}, path_by_key, compact=True)
            for match_index, match in enumerate(group.get("matches", []) or []):
                _render_match_readonly(match, match_index)


def _render_v13_new_autos(result: dict):
    st.markdown("### Nouveaux autos V13")
    rows = []
    for group in result.get("groups", []) or []:
        for match in group.get("matches", []) or []:
            reason = str(match.get("v13_auto_reason") or "")
            if not reason:
                continue
            candidate_row = (match.get("candidates") or [{}])[0]
            candidate = candidate_row.get("candidate") or {}
            rows.append(
                {
                    "annonce": group.get("announcement_index"),
                    "captures": " ".join(str(photo.get("capture_index")) for photo in _group_photo_payloads(group)),
                    "carte": candidate.get("name"),
                    "numéro": candidate.get("number"),
                    "langue": "JAP" if candidate.get("japanese") else "FR",
                    "score": match.get("score"),
                    "marge": match.get("margin"),
                    "visuel": candidate_row.get("visual_artwork_score") or candidate_row.get("visual_score"),
                    "preuve": reason,
                }
            )
    if not rows:
        st.info("Aucun nouveau vert attribuable aux règles V13 dans cette analyse.")
        return
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption("Cette liste est volontairement courte et sert au contrôle manuel des seules conversions V13.")


def _render_grouping_map(result: dict):
    metrics = result.get("metrics") or {}
    st.markdown("### Carte du grouping")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Photos", metrics.get("photos_analyzed", 0))
    c2.metric("Annonces", metrics.get("announcements_detected", 0))
    c3.metric("Photos / annonce", metrics.get("photos_per_announcement", "—"))
    c4.metric("V11 → V12", f"{metrics.get('v12_baseline_groups', 0)} → {metrics.get('announcements_detected', 0)}")
    c5.metric("Review", metrics.get("grouping_to_review", 0))

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("1 photo", metrics.get("one_photo_groups", 0))
    d2.metric("2 photos", metrics.get("two_photo_groups", 0))
    d3.metric("3 photos", metrics.get("three_photo_groups", 0))
    d4.metric("4+ photos", metrics.get("four_plus_photo_groups", 0))

    v1, v2, v3, v4 = st.columns(4)
    v1.metric("Singles V11", metrics.get("v12_baseline_singles", 0))
    v2.metric("Singles V12", metrics.get("one_photo_groups", 0))
    v3.metric("Multi récupérés", metrics.get("v12_recovered_multi_groups", 0))
    v4.metric("Grouping seul", f"{metrics.get('v12_grouping_seconds', 0)} s")

    lost = metrics.get("v12_photos_lost", 0)
    duplicated = metrics.get("v12_photos_duplicated", 0)
    if lost or duplicated:
        st.error(f"Photos perdues : {lost} · dupliquées : {duplicated}")
    else:
        st.success(f"Intégrité : {metrics.get('photos_analyzed', 0)} photos couvertes une seule fois.")

    grouping_filter = st.selectbox(
        "Filtre grouping",
        ["Tous", "Groupes 1 photo", "Groupes modifiés V12", "Grouping review"],
        key="photo_poc_grouping_filter",
    )

    rows = []
    for group in result.get("groups", []) or []:
        photos = _group_photo_payloads(group)
        indexes = " ".join(f"[{photo.get('capture_index')}]" for photo in photos)
        size = len(photos)
        is_review = group.get("grouping_status") == "review"
        is_multi = int(group.get("expected_cards") or 1) > 1 or len(group.get("matches", []) or []) > 1
        is_v12 = bool(group.get("v12_changed"))
        if grouping_filter == "Groupes 1 photo" and size != 1:
            continue
        if grouping_filter == "Groupes modifiés V12" and not is_v12:
            continue
        if grouping_filter == "Grouping review" and not is_review:
            continue
        if size == 1:
            state = "⚠ incomplet"
        elif is_multi:
            state = "MULTI"
        elif group.get("v12_recovered_multi"):
            state = "MULTI V12"
        elif is_v12:
            state = "✓ modifié V12"
        elif is_review:
            state = "⚠ review"
        else:
            state = "✓"
        rows.append(
            {
                "groupe": group.get("announcement_index"),
                "photos": indexes,
                "nb": size,
                "statut": state,
                "V11": " · ".join("[" + ",".join(str(value) for value in layout) + "]" for layout in group.get("v12_previous_layout", []) or []),
                "score": group.get("v12_pair_score"),
                "raison": " · ".join(group.get("grouping_reasons") or group.get("v11_single_unmerged_reason") or []),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)


def _render_v12_grouping_issues(result: dict):
    metrics = result.get("metrics") or {}
    groups = result.get("groups", []) or []
    path_by_key = _photo_path_by_key(result)
    st.markdown("### Singles / grouping reviews")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Singles", f"{metrics.get('v12_baseline_singles', 0)} → {metrics.get('one_photo_groups', 0)}")
    c2.metric("Reviews", f"{metrics.get('v12_baseline_reviews', 0)} → {metrics.get('grouping_to_review', 0)}")
    c3.metric("Groupes modifiés", metrics.get("v12_changed_groups", 0))
    c4.metric("Multi récupérés", metrics.get("v12_recovered_multi_groups", 0))

    patterns = metrics.get("v12_single_patterns_before") or {}
    if patterns:
        st.markdown("#### Cartographie V11 des 31 singles")
        st.dataframe(
            [{"pattern": pattern, "nombre": count} for pattern, count in sorted(patterns.items(), key=lambda item: (-item[1], item[0]))],
            width="stretch",
            hide_index=True,
        )
        with st.expander("Voir le détail des singles V11", expanded=False):
            st.dataframe(metrics.get("v12_single_map_before") or [], width="stretch", hide_index=True)

    review_reasons = metrics.get("v12_review_reasons") or {}
    if review_reasons:
        st.markdown("#### Reviews V12 restantes")
        st.dataframe(
            [{"cause": reason, "nombre": count} for reason, count in sorted(review_reasons.items(), key=lambda item: (-item[1], item[0]))],
            width="stretch",
            hide_index=True,
        )

    issues = [
        group
        for group in groups
        if group.get("grouping_status") == "review" or group.get("v12_changed") or len(group.get("photos", []) or []) == 1
    ]
    show = st.selectbox(
        "Cas affichés",
        ["Problèmes restants", "Groupes modifiés V12", "Tous les cas ciblés"],
        key="photo_poc_v12_issue_filter",
    )
    if show == "Problèmes restants":
        issues = [group for group in issues if group.get("grouping_status") == "review"]
    elif show == "Groupes modifiés V12":
        issues = [group for group in issues if group.get("v12_changed")]

    for group in issues:
        payloads = _group_photo_payloads(group)
        captures = [photo.get("capture_index") for photo in payloads]
        previous = " · ".join(
            "[" + ",".join(str(value) for value in layout) + "]"
            for layout in group.get("v12_previous_layout", []) or []
        ) or "—"
        st.markdown(
            f"**Groupe #{group.get('announcement_index')}** · V11 {previous} → V12 {captures} · "
            f"{'review' if group.get('grouping_status') == 'review' else 'résolu'}"
        )
        _render_group_photos({"photos": payloads}, path_by_key, compact=True)
        reason = " · ".join(group.get("grouping_reasons") or [])
        score = group.get("v12_pair_score")
        st.caption(f"Raison : {reason}" + (f" · score {score}" if score is not None else ""))
        st.divider()


def _role_caption(photo_payload: dict) -> str:
    return f"#{photo_payload.get('capture_index')} · {photo_payload.get('role', 'uncertain')}"


def _photo_path_by_key(result: dict) -> dict[str, str]:
    by_key = {}
    for photo in result.get("ordered_photos", []) or []:
        by_key[photo_key(photo)] = photo.path
    for photo in result.get("sample_photos", []) or []:
        by_key[photo_key(photo)] = photo.path
    return by_key


def _render_group_photos(group: dict, path_by_key: dict[str, str], *, compact=False, show_filenames=False):
    photos = group.get("photos", []) or []
    if not photos:
        st.caption("Aucune photo dans ce groupe.")
        return
    cols = st.columns(min(3 if compact else 5, len(photos)))
    for idx, photo_payload in enumerate(photos):
        with cols[idx % len(cols)]:
            path = path_by_key.get(photo_key(photo_payload))
            if path:
                try:
                    st.image(_thumbnail_bytes(path, 285 if compact else 320), width="stretch")
                except Exception:
                    st.image(path, width="stretch")
            st.markdown(f"<div class='poc-photos-caption'>{_role_caption(photo_payload)}</div>", unsafe_allow_html=True)
            if show_filenames:
                st.caption(photo_payload.get("filename", ""))


def _status_tone(level: str) -> str:
    return {"green": "poc-green", "orange": "poc-orange", "red": "poc-red"}.get(level, "poc-red")


def _status_label(level: str) -> str:
    return {"green": "Reconnu", "orange": "À vérifier", "red": "Non reconnu"}.get(level, "Non reconnu")


def _render_status_chip(level: str):
    st.markdown(
        f'<span class="poc-chip {_status_tone(level)}">{_status_label(level)}</span>',
        unsafe_allow_html=True,
    )


def _render_kpi(label: str, value, *, tone="violet"):
    st.markdown(
        f'<div class="poc-kpi" data-tone="{tone}"><div class="poc-kpi-label">{label}</div>'
        f'<div class="poc-kpi-value">{value}</div></div>',
        unsafe_allow_html=True,
    )


def _workflow_stage(result: dict, sample: dict) -> tuple[str, int]:
    pending = sum(
        1
        for group in result.get("groups", []) or []
        if not _recognition_is_done(sample, _result_group_id(group), group.get("matches", []) or [])
    )
    if pending:
        return "Vérification", pending
    if result.get("groups"):
        return "Prêt", 0
    return "Analyse", 0


def _render_premium_header(result: dict, sample: dict, *, drop_candidates_changed: bool):
    stage, pending = _workflow_stage(result, sample)
    if drop_candidates_changed:
        st.markdown(
            '<div class="poc-product-meta"><span class="poc-chip poc-orange">Mise à jour requise</span>'
            '<span>Les cartes du Drop ont évolué.</span></div>',
            unsafe_allow_html=True,
        )

    stages = ["Import", "Analyse", "Vérification", "Prêt"]
    active_index = stages.index(stage) if stage in stages else 1
    workflow_html = []
    for index, item in enumerate(stages):
        active = " active" if index <= active_index else ""
        workflow_html.append(f'<span class="poc-workflow-step{active}">{item}</span>')
        if index < len(stages) - 1:
            workflow_html.append('<span class="poc-workflow-arrow">→</span>')
    st.markdown('<div class="poc-workflow">' + "".join(workflow_html) + "</div>", unsafe_allow_html=True)


def _render_initial_header(*, drop_name: str, photo_count: int, drop_card_count: int):
    header_left, header_right = st.columns([4, 1.25])
    with header_left:
        st.markdown(
            f"""
            <div class="poc-shell">
              <div class="poc-eyebrow">POKÉSTOCK · DROP VINTED</div>
              <h1>Reconnaissance photos</h1>
              <p>{drop_name or 'Drop non défini'} · {photo_count} photos détectées · {drop_card_count} cartes dans le Drop</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with header_right:
        st.markdown(
            '<div class="poc-card-subtle"><span class="poc-chip poc-violet">Prêt à analyser</span>'
            '<div class="poc-mini" style="margin-top:.5rem">Choisis le type d’analyse dans le panneau ci-dessous.</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="poc-workflow"><span class="poc-workflow-step active">Import</span>'
        '<span class="poc-workflow-arrow">→</span><span class="poc-workflow-step">Analyse</span>'
        '<span class="poc-workflow-arrow">→</span><span class="poc-workflow-step">Vérification</span>'
        '<span class="poc-workflow-arrow">→</span><span class="poc-workflow-step">Prêt</span></div>',
        unsafe_allow_html=True,
    )


def _render_workspace_topbar(drops: list[dict]) -> tuple[str, list, str | None, int, int, int, bool, bool]:
    """Render the product header and return the small set of configuration inputs."""
    drop_options = {
        f"{drop.get('name', 'Drop sans nom')} · {len(drop.get('cards', []) or [])} cartes": drop.get("id")
        for drop in drops
    }
    header_left, header_actions = st.columns([4.2, 1.8])
    with header_left:
        st.markdown(
            "<div class='poc-shell'><div class='poc-eyebrow'>POKÉSTOCK · DROP VINTED</div>"
            "<h1>Reconnaissance photos</h1></div>",
            unsafe_allow_html=True,
        )
    current_result = st.session_state.get(CURRENT_RESULT_KEY)
    result_is_current = isinstance(current_result, dict) and bool(current_result.get("groups"))
    refresh_requested = False
    with header_actions:
        st.markdown("<div style='height:1.35rem'></div>", unsafe_allow_html=True)
        refresh_col, settings_col = st.columns([1.12, 1])
        with refresh_col:
            refresh_requested = st.button(
                ":material/refresh: Actualiser", key="photo_poc_top_refresh", use_container_width=True,
                disabled=not result_is_current, help="Relit uniquement les candidats du Drop.",
            )
        with settings_col:
            _render_settings_popover = st.popover
            with _render_settings_popover(":material/tune: Paramètres", use_container_width=True):
                st.caption("Source et réglages d’analyse")
                folder = st.text_input("Dossier photos", value=str(POC_DIR), key="photo_poc_folder")
                photos = _cached_ordered_photos(folder, _photo_folder_token(folder))
                selected_drop_label = st.selectbox(
                    "Drop candidat",
                    list(drop_options) or ["Aucun drop"],
                    key="photo_poc_drop_label",
                    disabled=not bool(drop_options),
                )
                with st.expander("Paramètres avancés", expanded=False):
                    start_index = st.number_input(
                        "capture_index de départ", min_value=1, max_value=max(1, len(photos)), value=1, step=1,
                    )
                    target_announcements = st.number_input(
                        "annonces visées", min_value=5, max_value=35, value=30, step=1,
                    )
                    max_photos = st.number_input(
                        "photos max à analyser", min_value=10, max_value=max(10, len(photos)),
                        value=min(75, max(10, len(photos))), step=5,
                    )
                    force_rebuild = st.checkbox(
                        "Forcer une reconstruction complète",
                        value=False,
                        help="Option technique : ignore le résultat persistant et relance tout le pipeline.",
                    )

    # A widget value is available on the same rerun; resolve the display data once.
    folder = st.session_state.get("photo_poc_folder", str(POC_DIR))
    photos = _cached_ordered_photos(folder, _photo_folder_token(folder))
    selected_drop_label = st.session_state.get("photo_poc_drop_label", next(iter(drop_options), "Aucun drop"))
    selected_drop_id = drop_options.get(selected_drop_label)
    selected_drop = next((drop for drop in drops if drop.get("id") == selected_drop_id), {})
    status_label = "Analyse à jour" if result_is_current else "Prêt à analyser"
    st.markdown(
        "<div class='poc-context-row'>"
        f"<span class='poc-context-chip'><strong>{selected_drop.get('name') or 'Drop non défini'}</strong></span>"
        f"<span class='poc-context-chip'>{len(photos)} photos</span>"
        f"<span class='poc-context-chip'>{len(selected_drop.get('cards', []) or [])} cartes</span>"
        f"<span class='poc-context-chip status'>{status_label}</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    return (
        folder,
        photos,
        selected_drop_id,
        int(start_index),
        int(target_announcements),
        int(max_photos),
        bool(force_rebuild),
        bool(refresh_requested),
    )


def _render_empty_state(*, folder: str, photo_count: int, drop_name: str, drop_card_count: int, view: str) -> tuple[bool, bool]:
    if view != "Vue d’ensemble":
        st.markdown(f"<div class='poc-section-title'>{view}</div>", unsafe_allow_html=True)
        st.markdown("<p class='poc-empty-note'>Cette vue sera disponible dès qu’une analyse aura été lancée.</p>", unsafe_allow_html=True)
    setup_col, summary_col = st.columns([2.25, 1], gap="large")
    with setup_col:
        st.markdown(
            "<div class='poc-setup'><div class='poc-section-title' style='margin-top:0'>Préparer l’analyse</div>"
            "<p class='poc-empty-note'>Sélectionne la source et lance l’analyse automatique des photos du Drop.</p>"
            "<div class='poc-setup-grid'>"
            f"<div class='poc-setup-item'><strong>Dossier source</strong>{folder}<br><span class='poc-mini'>{photo_count} photo(s) disponible(s)</span></div>"
            f"<div class='poc-setup-item'><strong>Drop sélectionné</strong>{drop_name or 'Aucun Drop sélectionné'}<br><span class='poc-mini'>{drop_card_count} carte(s) candidate(s)</span></div>"
            "</div></div>",
            unsafe_allow_html=True,
        )
        action_col, sample_col, _ = st.columns([1.38, 1, 1.7])
        with action_col:
            run_all = st.button(":material/auto_awesome: Analyser les photos", type="primary", use_container_width=True)
        with sample_col:
            run = st.button(":material/science: Échantillon", use_container_width=True)
        st.caption("L’analyse complète réutilise le cache local si la source et le Drop n’ont pas changé.")
    with summary_col:
        st.markdown(
            "<div class='poc-summary'><h2>Résumé du Drop</h2><div class='poc-summary-grid'>"
            f"<div class='poc-summary-metric'><strong>{photo_count}</strong><span>Photos importées</span></div>"
            f"<div class='poc-summary-metric'><strong>{drop_card_count}</strong><span>Cartes candidates</span></div>"
            "<div class='poc-summary-metric'><strong>Local</strong><span>Analyse privée</span></div>"
            "<div class='poc-summary-metric'><strong>Prêt</strong><span>Cache disponible</span></div>"
            "</div></div>",
            unsafe_allow_html=True,
        )
    return bool(run), bool(run_all)


def _render_candidate_summary(
    match: dict,
    *,
    compact=False,
    sample_key: str | None = None,
    sample: dict | None = None,
    group_id: str | None = None,
    match_index: int = 0,
):
    candidate = _match_primary_candidate(match)
    not_in_drop = str(match.get("v13_not_in_drop_confidence") or "")
    if not candidate and not not_in_drop:
        st.markdown('<div class="poc-card"><strong>Aucune carte proposée</strong><div class="poc-muted">La reconnaissance ne dispose pas de candidat fiable.</div></div>', unsafe_allow_html=True)
        return
    if not_in_drop:
        confidence = "forte confiance" if not_in_drop == "strong" else "à confirmer"
        st.markdown(
            f'<div class="poc-card" style="border-left:3px solid #e11d48"><strong>Carte absente du Drop</strong>'
            f'<div class="poc-muted">{confidence} · {match.get("diagnostic_reason") or "Aucun candidat exact dans le Drop"}</div></div>',
            unsafe_allow_html=True,
        )
        if sample_key and sample is not None and group_id:
            ocr_payload = match.get("ocr") or {}
            with st.popover("Préparer l’ajout", use_container_width=True):
                st.caption("Préparation POC uniquement. Aucune donnée du Drop ne sera modifiée.")
                with st.form(f"poc_premium_prepare_{group_id}_{match_index}"):
                    name = st.text_input("Nom", value=((ocr_payload.get("name_texts") or [""])[0]))
                    number = st.text_input(
                        "Numéro",
                        value=((ocr_payload.get("collector_number_texts") or ocr_payload.get("number_texts") or [""])[0]),
                    )
                    set_name = st.text_input("Set", value="")
                    if st.form_submit_button("Préparer l’ajout", type="primary"):
                        photo = match.get("photo")
                        _prepare_drop_addition(
                            sample_key,
                            sample,
                            group_id,
                            match_index,
                            {
                                "name": name.strip(),
                                "number": number.strip(),
                                "set": set_name.strip(),
                                "source_photo": getattr(photo, "filename", ""),
                                "capture_index": getattr(photo, "capture_index", None),
                                "status": "prepared_only",
                            },
                        )
                    st.success("Ajout préparé localement.")
        return
    photo_col, text_col = st.columns([0.72, 1.45] if not compact else [0.55, 1.45])
    with photo_col:
        if candidate.get("image_url"):
            st.image(candidate["image_url"], width=92 if compact else 170)
        else:
            st.caption("Image indisponible")
    with text_col:
        st.markdown(
            f"<div class='poc-candidate-name'>{candidate.get('name') or 'Carte inconnue'}</div>"
            f"<div class='poc-candidate-identity'>{candidate.get('number') or '—'} · "
            f"{candidate.get('set') or 'Set non renseigné'}</div>",
            unsafe_allow_html=True,
        )
        tags = []
        if candidate.get("japanese"):
            tags.append('<span class="poc-chip poc-rose">JAP</span>')
        variant = _variant_label(candidate)
        if variant and variant not in {"Standard", "FR", "JAP"}:
            tags.append(f'<span class="poc-chip poc-violet">{variant}</span>')
        if tags:
            st.markdown("".join(tags), unsafe_allow_html=True)
        st.markdown(
            f"<div class='poc-score-secondary'>Confiance {match.get('score', 0)} · "
            f"marge {match.get('margin', 0)}</div>",
            unsafe_allow_html=True,
        )


def _render_match_actions(
    sample_key: str,
    sample: dict,
    group_id: str,
    match_index: int,
    match: dict,
    *,
    index_key: str,
    current_index: int,
    group_count: int,
    matches: list[dict],
    key_prefix: str,
    show_next=True,
):
    validation = _recognition_validation(sample, group_id, match_index, match)
    state = _validation_state(validation, match)
    if state.get("state") in {"compatible", "explicit_truth"}:
        result = "Correct" if state.get("resolved_correct") else "À reprendre"
        tone = "poc-green" if state.get("resolved_correct") else "poc-red"
        st.markdown(f'<span class="poc-chip {tone}">Validation · {result}</span>', unsafe_allow_html=True)
        return
    if state.get("state") == "stale":
        st.markdown('<span class="poc-chip poc-orange">Proposition modifiée</span>', unsafe_allow_html=True)
    action_columns = st.columns([1, 1, 1] if show_next else [1, 1])
    left, middle = action_columns[:2]
    left.button(
        "✕ Mauvais",
        key=f"{key_prefix}_wrong_{group_id}_{match_index}",
        width="stretch",
        on_click=_full_check_validation_callback,
        args=(sample_key, sample, group_id, match_index, "wrong", index_key, current_index, group_count, matches, match),
    )
    middle.button(
        "✓ Correct",
        type="primary",
        key=f"{key_prefix}_correct_{group_id}_{match_index}",
        width="stretch",
        on_click=_full_check_validation_callback,
        args=(sample_key, sample, group_id, match_index, "correct", index_key, current_index, group_count, matches, match),
    )
    if show_next:
        action_columns[2].button(
            "Suivant →",
            key=f"{key_prefix}_next_{group_id}_{match_index}",
            width="stretch",
            on_click=_set_queue_index,
            args=(index_key, min(group_count - 1, current_index + 1)),
        )


def _render_recognition_details(match: dict, sample_key: str, sample: dict, group_id: str, match_index: int, candidates: list[dict]):
    with st.expander("Détails de reconnaissance", expanded=False):
        _render_match_debug(match, sample_key, sample, group_id, match_index, candidates)


def _group_photo_payloads(group: dict) -> list[dict]:
    payloads = []
    for entry in group.get("photos", []) or []:
        photo = entry.get("photo")
        if not photo:
            continue
        payloads.append(
            {
                "filename": photo.filename,
                "capture_index": photo.capture_index,
                "role": entry.get("ground_truth_role") or entry.get("classification", {}).get("class", "photo"),
            }
        )
    return payloads


def _result_group_id(group: dict) -> str:
    if group.get("ground_truth_group_id"):
        return str(group.get("ground_truth_group_id"))
    payloads = _group_photo_payloads(group)
    if payloads:
        return stable_group_id_from_photos(payloads)
    return str(group.get("announcement_index"))


def _source_group(sample: dict, group_id: str) -> dict:
    return next((group for group in sample.get("groups", []) or [] if str(group.get("group_id")) == str(group_id)), {})


def _sync_current_result_index(result: dict) -> dict:
    """Expose one candidate/status object per physical subcard for every view."""
    current_index = {}
    for group in result.get("groups", []) or []:
        group_id = _result_group_id(group)
        matches = group.get("matches", []) or []
        recognized_cards = group.get("recognized_cards", []) or []
        for match_index, match in enumerate(matches):
            subcard_id = _subcard_id(match, match_index)
            key = f"{group_id}:{subcard_id}"
            if key in current_index:
                raise ValueError(f"Sous-carte physique dupliquée dans le résultat courant : {key}")
            candidate = _match_candidate(match)
            current_status = (
                "not_in_drop" if match.get("v13_not_in_drop_confidence") else str(match.get("status") or "fail")
            )
            current_index[key] = {
                "group_id": group_id,
                "subcard_id": subcard_id,
                "candidate_card_uid": str(candidate.get("card_uid") or ""),
                "status": current_status,
                "layout": str(match.get("layout_type") or "standard"),
                "not_in_drop": str(match.get("v13_not_in_drop_confidence") or ""),
            }
            if match_index < len(recognized_cards):
                recognized_cards[match_index]["candidate"] = candidate or None
                recognized_cards[match_index]["status"] = current_status
                recognized_cards[match_index]["not_in_drop_confidence"] = str(
                    match.get("v13_not_in_drop_confidence") or ""
                )
                recognized_cards[match_index]["subcard_id"] = subcard_id
        if len(recognized_cards) != len(matches):
            raise ValueError(
                f"Structure multi incohérente pour {group_id}: {len(matches)} match(es), "
                f"{len(recognized_cards)} sous-carte(s)"
            )
    result["current_match_index"] = current_index
    return current_index


def _move_photo(sample: dict, group_index: int, photo_index: int, direction: int):
    groups = sample.get("groups", [])
    target_index = group_index + direction
    if target_index < 0 or target_index >= len(groups):
        return
    photo = groups[group_index].get("photos", []).pop(photo_index)
    if direction < 0:
        groups[target_index].setdefault("photos", []).append(photo)
    else:
        groups[target_index].setdefault("photos", []).insert(0, photo)
    groups[group_index]["status"] = "corrected"
    groups[target_index]["status"] = "corrected"


def _merge_group(sample: dict, group_index: int, direction: int):
    groups = sample.get("groups", [])
    target_index = group_index + direction
    if target_index < 0 or target_index >= len(groups):
        return
    if direction < 0:
        groups[target_index].setdefault("photos", []).extend(groups[group_index].get("photos", []))
        groups[target_index]["status"] = "corrected"
        groups.pop(group_index)
    else:
        groups[group_index].setdefault("photos", []).extend(groups[target_index].get("photos", []))
        groups[group_index]["status"] = "corrected"
        groups.pop(target_index)


def _split_group(sample: dict, group_index: int, split_at: int):
    groups = sample.get("groups", [])
    photos = groups[group_index].get("photos", [])
    if split_at <= 0 or split_at >= len(photos):
        return
    new_photos = photos[split_at:]
    groups[group_index]["photos"] = photos[:split_at]
    groups[group_index]["status"] = "corrected"
    groups.insert(
        group_index + 1,
        {
            "group_id": f"{groups[group_index].get('group_id')}_split",
            "status": "corrected",
            "auto_grouping_status": "manual",
            "expected_cards": 1,
            "jp_physical": False,
            "photos": new_photos,
            "notes": "Séparé manuellement",
            "recognition_validation": {},
        },
    )


def _render_validation_view(sample_key: str, sample: dict, result: dict):
    path_by_key = _photo_path_by_key(result)
    groups = sample.setdefault("groups", [])

    st.markdown("### Validation des groupes")
    v1, v2, v3, v4 = st.columns(4)
    total = len(groups)
    validated = sum(1 for group in groups if normalize_group_status(group.get("status")) in VALIDATED_GROUP_STATUSES)
    corrected = sum(1 for group in groups if normalize_group_status(group.get("status")) == "corrected")
    v1.metric("Groupes POC", total)
    v2.metric("Validés", f"{validated} / {total}")
    v3.metric("À corriger", max(0, total - validated))
    v4.metric("Progression", f"{round(validated / max(1, total) * 100, 1)} %")

    if st.button("✓ Marquer tous les groupes non corrigés comme corrects", type="secondary"):
        for group in groups:
            if group.get("status") == "unvalidated":
                group["status"] = "validated"
        _save_sample(sample_key, sample)
        _rerun()

    show_only_pending = st.checkbox("Afficher seulement les groupes non validés", value=False)
    next_pending = next(
        (idx + 1 for idx, group in enumerate(groups) if normalize_group_status(group.get("status")) not in VALIDATED_GROUP_STATUSES),
        None,
    )
    if next_pending:
        st.caption(f"Prochain groupe non validé : #{next_pending}")
    else:
        st.success("Tous les groupes de cet échantillon sont validés.")

    for group_index, group in enumerate(groups):
        status = normalize_group_status(group.get("status"))
        if show_only_pending and status in VALIDATED_GROUP_STATUSES:
            continue
        group_id = str(group.get("group_id") or group_index)
        badge_class = "poc-green" if status == "validated" else "poc-orange" if status == "corrected" else "poc-red"
        badge_text = "✓ Validé" if status == "validated" else "✓ Corrigé" if status == "corrected" else "unvalidated"
        st.markdown(
            f"""
            <div class="poc-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:center;flex-wrap:wrap;">
                <strong>Groupe #{group_index + 1}</strong>
                <span class="poc-chip {badge_class}">{badge_text}</span>
              </div>
              <div class="poc-mini">auto: {group.get('auto_grouping_status', 'n/a')} · cartes attendues: {group.get('expected_cards', 1)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_group_photos(group, path_by_key, compact=True)

        c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
        c1.button(
            "✓ Groupe correct",
            key=f"gt_correct_{group_id}",
            on_click=_set_group_status,
            args=(sample_key, group_id, "validated"),
            type="primary" if status not in VALIDATED_GROUP_STATUSES else "secondary",
        )
        if c2.button("Fusion précédent", key=f"gt_merge_prev_{group_index}", disabled=group_index == 0):
            _merge_group(sample, group_index, -1)
            _save_sample(sample_key, sample)
            _rerun()
        if c3.button("Fusion suivant", key=f"gt_merge_next_{group_index}", disabled=group_index >= len(groups) - 1):
            _merge_group(sample, group_index, 1)
            _save_sample(sample_key, sample)
            _rerun()

        with st.expander("Corriger", expanded=False):
            group["expected_cards"] = st.number_input(
                "Nombre de cartes dans l'annonce",
                min_value=1,
                max_value=8,
                value=max(1, int(group.get("expected_cards") or 1)),
                key=f"gt_expected_{group_index}",
            )
            group["jp_physical"] = st.checkbox("JP physique", value=bool(group.get("jp_physical")), key=f"gt_jp_{group_index}")
            group["notes"] = st.text_input("Notes POC", value=str(group.get("notes") or ""), key=f"gt_notes_{group_index}")

            photos = group.get("photos", [])
            for photo_index, photo_payload in enumerate(photos):
                cols = st.columns([1.5, 1.1, 0.9, 0.9])
                cols[0].caption(f"#{photo_payload.get('capture_index')} · {photo_payload.get('filename')}")
                photo_payload["role"] = cols[1].selectbox(
                    "Rôle",
                    PHOTO_ROLES,
                    index=list(PHOTO_ROLES).index(photo_payload.get("role")) if photo_payload.get("role") in PHOTO_ROLES else 0,
                    key=f"gt_role_{group_index}_{photo_index}",
                    label_visibility="collapsed",
                )
                if cols[2].button("← précédent", key=f"gt_move_prev_{group_index}_{photo_index}", disabled=group_index == 0):
                    _move_photo(sample, group_index, photo_index, -1)
                    _save_sample(sample_key, sample)
                    _rerun()
                if cols[3].button("suivant →", key=f"gt_move_next_{group_index}_{photo_index}", disabled=group_index >= len(groups) - 1):
                    _move_photo(sample, group_index, photo_index, 1)
                    _save_sample(sample_key, sample)
                    _rerun()

            split_options = [f"Après photo {idx}: #{photo.get('capture_index')}" for idx, photo in enumerate(photos, start=1)][:-1]
            split_choice = st.selectbox("Séparer le groupe", [""] + split_options, key=f"gt_split_choice_{group_index}")
            if st.button("Séparer ici", key=f"gt_split_{group_index}", disabled=not split_choice):
                split_at = split_options.index(split_choice) + 1
                _split_group(sample, group_index, split_at)
                _save_sample(sample_key, sample)
                _rerun()

            s1, s2 = st.columns(2)
            if s1.button("Enregistrer comme corrigé", key=f"gt_save_{group_index}", type="primary"):
                group["status"] = "corrected"
                _save_sample(sample_key, sample)
                _rerun()
            if s2.button("Remettre à valider", key=f"gt_reset_{group_index}"):
                group["status"] = "unvalidated"
                _save_sample(sample_key, sample)
                _rerun()


def _candidate_row(candidate_row: dict) -> dict:
    candidate = candidate_row.get("candidate") or {}
    variants = []
    if candidate.get("japanese"):
        variants.append("JAP")
    if candidate.get("reverse"):
        variants.append("REVERSE")
    if candidate.get("first_edition"):
        variants.append("1RE")
    if candidate.get("stamp"):
        variants.append("STAMP")
    return {
        "score": candidate_row.get("score"),
        "visuel": candidate_row.get("visual_score", ""),
        "methode": " · ".join(candidate_row.get("reasons") or []),
        "nom": candidate.get("name"),
        "numéro": candidate.get("number"),
        "set": candidate.get("set"),
        "lot": candidate.get("lot_name"),
        "variantes": " · ".join(variants) or "FR",
        "card_uid": candidate.get("card_uid"),
    }


def _variant_label(candidate: dict) -> str:
    variants = []
    if candidate.get("japanese"):
        variants.append("JAP")
    if candidate.get("reverse"):
        variants.append("REVERSE")
    if candidate.get("first_edition"):
        variants.append("1RE")
    if candidate.get("stamp"):
        variants.append("STAMP")
    if candidate.get("promo"):
        variants.append("PROMO")
    if candidate.get("master_ball"):
        variants.append("MASTER BALL")
    if candidate.get("poke_ball"):
        variants.append("POKÉ BALL")
    return " · ".join(variants) or "FR"


def _match_candidate(match: dict | None) -> dict:
    return ((((match or {}).get("candidates") or [{}])[0]).get("candidate") or {})


def _semantic_proposal(match: dict | None) -> dict:
    """Keep only the identity decisions that require a new human validation."""
    match = match or {}
    candidate = _match_candidate(match)
    # The V10 ground-truth overlay can visually downgrade an already-known false
    # green to review.  That is a safety presentation, not a new OCR proposal.
    status = str(match.get("v10_original_status") or match.get("status") or "fail").lower()
    not_in_drop = str(match.get("v13_not_in_drop_confidence") or "").lower()
    if not_in_drop in {"strong", "possible"} or status == "not_in_drop":
        proposal_status = "not_in_drop"
    elif status == "recognized":
        proposal_status = "recognized"
    elif status in {"review", "orange"}:
        proposal_status = "review"
    else:
        proposal_status = "fail"
    return {
        "candidate_card_uid": str(candidate.get("card_uid") or ""),
        "candidate_status": proposal_status,
        # These are identity discriminators, not rendering/debug metadata.
        "japanese": bool(candidate.get("japanese") or candidate.get("is_japanese") or candidate.get("lang") == "ja"),
        "variant": _variant_label(candidate),
    }


def _proposal_signature(match: dict | None) -> str:
    payload = _semantic_proposal(match)
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _current_proposal_snapshot(result: dict) -> dict:
    """Capture only semantic proposal state before a candidate refresh.

    Scores, OCR wording and run metadata intentionally do not belong here: a
    candidate needs revalidation only when its identity/status/variant or its
    physical multi-card structure actually changes.
    """
    subcards = {}
    group_counts = {}
    for group in result.get("groups", []) or []:
        group_id = _result_group_id(group)
        matches = group.get("matches", []) or []
        group_counts[group_id] = len(matches)
        for index, match in enumerate(matches):
            subcards[f"{group_id}:{_subcard_id(match, index)}"] = _semantic_proposal(match)
    return {"subcards": subcards, "group_counts": group_counts}


def _subcard_id(match: dict | None, match_index: int | None = None) -> str:
    match = match or {}
    photos = match.get("subcard_photos") or {}
    physical_group_id = str(match.get("physical_group_id") or "").strip()
    front_key = str(photos.get("front") or "").strip()
    back_key = str(photos.get("back") or "").strip()
    if physical_group_id and front_key:
        raw = f"group={physical_group_id}|front={front_key}|back={back_key}"
        return "subcard_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    stable_id = str(match.get("subcard_id") or "").strip()
    if stable_id:
        return stable_id
    photo = match.get("photo")
    if photo:
        raw = f"front={photo_key(photo)}"
        return "subcard_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"legacy_subcard_{int(match_index or 0)}"


def _legacy_front_subcard_id(match: dict | None) -> str:
    """Return the short-lived V14.4 id used before back/group were included."""
    match = match or {}
    front_key = str((match.get("subcard_photos") or {}).get("front") or "")
    if not front_key and match.get("photo"):
        front_key = photo_key(match["photo"])
    if not front_key:
        return ""
    return "subcard_" + hashlib.sha1(f"front={front_key}".encode("utf-8")).hexdigest()[:16]


def _same_physical_subcard(validation: dict, match: dict | None) -> bool:
    stored = (validation or {}).get("subcard_photos") or {}
    current = (match or {}).get("subcard_photos") or {}
    stored_front = str(stored.get("front") or "")
    current_front = str(current.get("front") or "")
    if not stored_front or not current_front or stored_front != current_front:
        return False
    stored_back = str(stored.get("back") or "")
    current_back = str(current.get("back") or "")
    return not stored_back or not current_back or stored_back == current_back


def _validation_payload(status: str, match: dict | None, **extra) -> dict:
    candidate = _match_candidate(match)
    payload = {
        "status": status,
        "subcard_id": _subcard_id(match),
        "subcard_photos": dict((match or {}).get("subcard_photos") or {}),
        "semantic_proposal_signature": _proposal_signature(match),
        "semantic_proposal": _semantic_proposal(match),
        "candidate_key": candidate_identity_key(candidate) if candidate else "",
        "candidate_snapshot": candidate_identity(candidate),
        "validated_at": datetime.now().isoformat(timespec="seconds"),
    }
    payload.update(extra)
    return payload


def _recognition_validation(sample: dict, group_id: str, match_index: int, match: dict | None = None) -> dict:
    for group in sample.get("groups", []):
        if str(group.get("group_id")) == str(group_id):
            validations = group.get("recognition_validation") or {}
            stable_key = _subcard_id(match, match_index)
            stable_validation = validations.get(stable_key)
            if isinstance(stable_validation, dict):
                return stable_validation
            legacy_front_validation = validations.get(_legacy_front_subcard_id(match))
            if isinstance(legacy_front_validation, dict):
                return legacy_front_validation
            physical_validation = next(
                (
                    validation
                    for validation in validations.values()
                    if isinstance(validation, dict) and _same_physical_subcard(validation, match)
                ),
                None,
            )
            if isinstance(physical_validation, dict):
                return physical_validation
            legacy_validation = validations.get(str(match_index)) or {}
            if not isinstance(legacy_validation, dict):
                return {}
            bound_subcard = str(legacy_validation.get("subcard_id") or "")
            if bound_subcard and bound_subcard != stable_key:
                return {}
            # A numeric child index is not a physical identity. On a multi-card
            # group it may move after a refresh, so only accept it when it carries
            # matching photo evidence (or has already been bound above).
            is_multi_group = int(group.get("expected_cards") or 1) > 1
            if not bound_subcard and is_multi_group:
                if not _same_physical_subcard(legacy_validation, match):
                    return {}
            return legacy_validation
    return {}


def _validation_state(validation: dict, match: dict | None) -> dict:
    status = str((validation or {}).get("status") or "")
    if not status:
        return {
            "state": "unvalidated",
            "status": "",
            "resolved_correct": False,
            "resolved_for_workflow": False,
        }
    # These booleans were once migrated from an unstable child index. A
    # LEGEND rematch can reorder the two halves, so that migration cannot be
    # treated as physical ground truth. Keep it for audit and request one
    # targeted recheck instead of attaching correct/wrong to the other half.
    if (
        str((match or {}).get("layout_type") or "") == "LEGEND_HALF"
        and validation.get("semantic_baseline_migrated")
        and not (
            validation.get("expected_candidate_key")
            or validation.get("selected_key")
            or validation.get("drop_card_key")
        )
    ):
        return {
            "state": "stale",
            "status": status,
            "resolved_correct": False,
            "resolved_for_workflow": False,
            "reason": "ancienne validation LÉGENDE issue d'un ordre de sous-cartes instable",
        }
    current_candidate = _match_candidate(match)
    current_key = candidate_identity_key(current_candidate) if current_candidate else ""
    current_keys = {
        current_key,
        str(current_candidate.get("card_uid") or ""),
        str(current_candidate.get("drop_card_key") or ""),
    }
    expected_key = str(
        validation.get("expected_candidate_key")
        or validation.get("selected_key")
        or validation.get("drop_card_key")
        or (validation.get("expected_candidate") or {}).get("card_uid")
        or ""
    )
    if expected_key:
        matches_truth = bool(expected_key and expected_key in current_keys)
        return {
            "state": "explicit_truth",
            "status": "correct" if matches_truth else "wrong",
            "resolved_correct": matches_truth,
            "resolved_for_workflow": True,
            "expected_candidate_key": expected_key,
        }
    stored_signature = str(validation.get("semantic_proposal_signature") or "")
    if not stored_signature:
        return {
            "state": "stale",
            "status": status,
            "resolved_correct": False,
            "resolved_for_workflow": False,
            "reason": "ancienne validation sans empreinte sémantique",
        }
    if stored_signature != _proposal_signature(match):
        return {
            "state": "stale",
            "status": status,
            "resolved_correct": False,
            "resolved_for_workflow": False,
            "reason": "la proposition sémantique a changé depuis cette validation",
        }
    return {
        "state": "compatible",
        "status": status,
        "resolved_correct": status in {"correct", "manual_choice"},
        "resolved_for_workflow": status in {"correct", "manual_choice"},
    }


def _migrate_semantic_validation_baseline(sample_key: str, sample: dict, result: dict) -> dict:
    """Bind legacy validations to the proposal currently displayed, once and locally.

    Older POC entries only contained ``correct`` / ``wrong``.  Treating those as
    stale forever requeued the entire dataset.  The migration intentionally stores
    only the semantic proposal, so later score/OCR/debug changes remain compatible.
    """
    changed = False
    groups_by_id = {_result_group_id(group): group for group in result.get("groups", []) or []}
    for source_group in sample.get("groups", []) or []:
        group_id = str(source_group.get("group_id") or "")
        result_group = groups_by_id.get(group_id)
        if not result_group:
            continue
        matches = result_group.get("matches", []) or []
        current_count = len(matches)
        if source_group.get("semantic_subcard_count") is None:
            source_group["semantic_subcard_count"] = current_count
            changed = True
        validations = source_group.get("recognition_validation") or {}
        stable_ids = [_subcard_id(match, index) for index, match in enumerate(matches)]
        previous_ids = source_group.get("semantic_subcard_ids")
        if previous_ids is None:
            source_group["semantic_subcard_ids"] = stable_ids
            changed = True
        for index, match in enumerate(matches):
            stable_id = stable_ids[index]
            validation = validations.get(stable_id)
            if not isinstance(validation, dict):
                validation = validations.get(_legacy_front_subcard_id(match))
            if not isinstance(validation, dict):
                validation = next(
                    (
                        candidate_validation
                        for candidate_validation in validations.values()
                        if isinstance(candidate_validation, dict)
                        and _same_physical_subcard(candidate_validation, match)
                    ),
                    None,
                )
            if not isinstance(validation, dict):
                numeric_validation = validations.get(str(index))
                if len(matches) == 1 or _same_physical_subcard(numeric_validation or {}, match):
                    validation = numeric_validation
            if not isinstance(validation, dict) or not validation.get("status"):
                continue
            if stable_id not in validations:
                validation = dict(validation)
                validation["subcard_id"] = stable_id
                validation["subcard_photos"] = dict(match.get("subcard_photos") or {})
                validation["legacy_match_index"] = index
                validations[stable_id] = validation
                changed = True
            elif not validation.get("subcard_photos") and match.get("subcard_photos"):
                validation["subcard_photos"] = dict(match.get("subcard_photos") or {})
                changed = True
            if validation.get("expected_candidate_key") or validation.get("selected_key") or validation.get("drop_card_key"):
                continue
            if validation.get("semantic_proposal_signature"):
                continue
            validation["semantic_proposal_signature"] = _proposal_signature(match)
            validation["semantic_proposal"] = _semantic_proposal(match)
            validation["semantic_baseline_migrated"] = True
            changed = True
        # V14.4 initially keyed children by their front capture only. Moving to
        # group+front+back is an identity migration, not a physical structure
        # change. Only rewrite that exact legacy id set; real photo changes stay
        # visible in the revalidation queue.
        legacy_front_ids = [_legacy_front_subcard_id(match) for match in matches]
        if (
            isinstance(previous_ids, list)
            and len(previous_ids) == len(stable_ids)
            and set(map(str, previous_ids)) == set(legacy_front_ids)
            and set(map(str, previous_ids)) != set(stable_ids)
        ):
            source_group["semantic_subcard_ids"] = stable_ids
            changed = True
    if changed:
        update_ground_truth_sample(sample_key, sample)
        st.session_state[f"photo_poc_sample_{sample_key}"] = sample
    return sample


def _proposal_change_reason(before: dict, after: dict, *, structure_changed=False) -> str:
    if structure_changed:
        return "structure"
    if before.get("candidate_status") == "not_in_drop" or after.get("candidate_status") == "not_in_drop":
        return "not_in_drop"
    if before.get("candidate_card_uid") != after.get("candidate_card_uid"):
        return "candidat"
    if before.get("japanese") != after.get("japanese") or before.get("variant") != after.get("variant"):
        return "variante"
    return "proposition"


def _proposal_change_rows(sample: dict, result: dict) -> list[dict]:
    rows = []
    refresh_snapshot = ((result.get("analysis_meta") or {}).get("proposal_snapshot_previous") or {})
    previous_subcards = refresh_snapshot.get("subcards") or {}
    previous_group_counts = refresh_snapshot.get("group_counts") or {}
    for group in result.get("groups", []) or []:
        group_id = _result_group_id(group)
        source = _source_group(sample, group_id)
        matches = group.get("matches", []) or []
        previous_count = source.get("semantic_subcard_count")
        current_ids = [_subcard_id(match, index) for index, match in enumerate(matches)]
        legacy_current_ids = [_legacy_front_subcard_id(match) for match in matches]
        previous_ids = source.get("semantic_subcard_ids")
        previous_id_set = set(map(str, previous_ids)) if isinstance(previous_ids, list) else set()
        refresh_structure_changed = (
            group_id in previous_group_counts
            and int(previous_group_counts[group_id]) != len(matches)
        )
        structure_changed = refresh_structure_changed or (
            previous_count is not None
            and int(previous_count) != len(matches)
        ) or (
            isinstance(previous_ids, list)
            and previous_id_set != set(current_ids)
            and previous_id_set != set(legacy_current_ids)
        )
        for index, match in enumerate(matches):
            validation = _recognition_validation(sample, group_id, index, match)
            state = _validation_state(validation, match)
            after = _semantic_proposal(match)
            snapshot_key = f"{group_id}:{_subcard_id(match, index)}"
            has_refresh_before = snapshot_key in previous_subcards
            before = previous_subcards.get(snapshot_key) if has_refresh_before else (validation.get("semantic_proposal") or {})
            semantic_changed = before != after
            if has_refresh_before:
                if not semantic_changed and not refresh_structure_changed:
                    # A second identical refresh must not enqueue compatible
                    # proposals, but it must keep a genuinely stale human
                    # validation visible until that exact proposal is checked.
                    if state.get("state") != "stale":
                        continue
                    before = validation.get("semantic_proposal") or before
                # Once the current proposal has been checked, it no longer
                # belongs in the targeted revalidation queue.
                if state.get("state") in {"compatible", "explicit_truth"} and not refresh_structure_changed:
                    continue
            elif state.get("state") != "stale" and not structure_changed:
                continue
            rows.append({
                "group": group,
                "group_id": group_id,
                "match_index": index,
                "before": before,
                "after": after,
                "reason": _proposal_change_reason(before, after, structure_changed=structure_changed),
            })
            # A multi-card structure change belongs to the group, not every child.
            if structure_changed:
                break
    return rows


def _ground_truth_state(sample: dict, result: dict) -> dict:
    counts = {"compatible": 0, "explicit_truth": 0, "stale": 0, "unvalidated": 0}
    stale_groups = []
    for group in result.get("groups", []) or []:
        group_id = _result_group_id(group)
        group_stale = False
        matches = group.get("matches", []) or [{}]
        for match_index, match in enumerate(matches):
            state = _validation_state(_recognition_validation(sample, group_id, match_index, match), match)
            key = state.get("state") or "unvalidated"
            counts[key] = counts.get(key, 0) + 1
            group_stale = group_stale or key == "stale"
        if group_stale:
            stale_groups.append(group)
    counts["stale_groups"] = stale_groups
    counts["remaining"] = counts.get("stale", 0) + counts.get("unvalidated", 0)
    return counts


def _set_recognition_validation(
    sample_key: str,
    group_id: str,
    match_index: int,
    payload: dict,
    *,
    sample: dict | None = None,
):
    started = time.perf_counter()
    sample = sample if isinstance(sample, dict) else _load_sample(sample_key)
    for group in sample.get("groups", []) or []:
        if str(group.get("group_id")) == str(group_id):
            validations = group.setdefault("recognition_validation", {})
            validation_key = str(payload.get("subcard_id") or f"legacy_subcard_{match_index}")
            validations[validation_key] = payload
            break
    st.session_state[f"photo_poc_sample_{sample_key}"] = sample
    update_ground_truth_sample(sample_key, sample)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    latencies = st.session_state.setdefault("photo_poc_validation_latencies_ms", [])
    latencies.append(elapsed_ms)
    del latencies[:-30]
    return elapsed_ms


def _prepare_drop_addition(
    sample_key: str,
    sample: dict,
    group_id: str,
    match_index: int,
    payload: dict,
):
    for group in sample.get("groups", []) or []:
        if str(group.get("group_id")) != str(group_id):
            continue
        additions = group.setdefault("prepared_drop_additions", {})
        additions[str(match_index)] = payload
        break
    st.session_state[f"photo_poc_sample_{sample_key}"] = sample
    update_ground_truth_sample(sample_key, sample)


def _full_check_validation_callback(
    sample_key: str,
    sample: dict,
    group_id: str,
    match_index: int,
    status: str,
    index_key: str,
    current_index: int,
    group_count: int,
    matches: list[dict],
    match: dict,
):
    _set_recognition_validation(
        sample_key,
        group_id,
        match_index,
        _validation_payload(status, match),
        sample=sample,
    )
    if _recognition_is_done(sample, group_id, matches):
        st.session_state[index_key] = min(current_index + 1, max(0, group_count - 1))


def _set_queue_index(index_key: str, value: int):
    st.session_state[index_key] = max(0, int(value))


def _candidate_options(candidates: list[dict]) -> dict[str, str]:
    return {
        f"{candidate.get('name')} · {candidate.get('number')} · {candidate.get('lot_name')} · {candidate.get('card_uid')}": candidate.get("drop_card_key")
        for candidate in candidates
    }


def _render_match_debug(match: dict, sample_key: str, sample: dict, group_id: str, match_index: int, candidates: list[dict]):
    ocr_payload = match.get("ocr") or {}
    orientation = int(match.get("orientation_degrees") or 0)
    st.markdown(
        f"**Zone carte {match_index + 1} · {match.get('method')} · {match.get('status')} · "
        f"score {match.get('score', 0)} · marge {match.get('margin', 0)}**"
    )
    st.caption("Raison : " + str(match.get("diagnostic_reason") or "—"))
    st.caption(
        "OCR nom : "
        + " / ".join(ocr_payload.get("name_texts") or ["—"])
        + " · OCR numéro : "
        + " / ".join(ocr_payload.get("number_texts") or ["—"])
    )
    if ocr_payload.get("all_number_texts"):
        st.caption("Numéros debug tous crops : " + " / ".join(ocr_payload.get("all_number_texts") or []))
    if ocr_payload.get("v_union_edge_numbers"):
        st.caption("Numéros V-UNION lus sur les bords : " + " / ".join(ocr_payload.get("v_union_edge_numbers") or []))
    if match.get("subcard_id"):
        st.caption(f"Sous-carte physique : {match.get('subcard_id')} · {match.get('subcard_photos') or {}}")

    rows = [_candidate_row(candidate_row) for candidate_row in (match.get("candidates") or [])[:3]]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
        cols = st.columns(min(3, len(match.get("candidates") or [])))
        for idx, candidate_row in enumerate((match.get("candidates") or [])[:3]):
            candidate = candidate_row.get("candidate") or {}
            with cols[idx]:
                if candidate.get("image_url"):
                    st.image(candidate.get("image_url"), use_container_width=True)
                st.caption(f"#{idx + 1} · {candidate.get('name')} · {candidate.get('number')}")

    photo = match.get("photo")
    if photo:
        with st.expander("Afficher le crop OCR", expanded=False):
            crop_cols = st.columns(3)
            name_crop = _image_crop(photo.path, "name", orientation)
            number_crop = _image_crop(photo.path, "number", orientation)
            card_crop = _image_crop(photo.path, "card", orientation)
            artwork_crop = _image_crop(photo.path, "artwork", orientation)
            if name_crop:
                crop_cols[0].image(name_crop, caption="crop nom", use_container_width=True)
            if number_crop:
                crop_cols[1].image(number_crop, caption="crop numéro", use_container_width=True)
            if card_crop:
                crop_cols[2].image(card_crop, caption="carte", use_container_width=True)
            if artwork_crop:
                st.image(artwork_crop, caption="crop artwork", width=320)

    validation = _recognition_validation(sample, group_id, match_index, match)
    validation_state = _validation_state(validation, match)
    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("✓ Correct", key=f"rec_ok_{group_id}_{match_index}"):
        _set_recognition_validation(sample_key, group_id, match_index, _validation_payload("correct", match))
        _rerun()
    if c2.button("✕ Mauvais", key=f"rec_bad_{group_id}_{match_index}"):
        _set_recognition_validation(sample_key, group_id, match_index, _validation_payload("wrong", match))
        _rerun()
    candidate_options = _candidate_options(candidates)
    selected = c3.selectbox(
        "Choisir une autre carte",
        [""] + list(candidate_options.keys()),
        key=f"rec_choose_{group_id}_{match_index}",
        label_visibility="collapsed",
    )
    if selected and st.button("Enregistrer ce choix", key=f"rec_choose_save_{group_id}_{match_index}"):
        selected_drop_key = candidate_options[selected]
        selected_candidate = next(
            (candidate for candidate in candidates if candidate.get("drop_card_key") == selected_drop_key),
            {},
        )
        _set_recognition_validation(
            sample_key,
            group_id,
            match_index,
            _validation_payload(
                "manual_choice",
                match,
                drop_card_key=selected_drop_key,
                expected_candidate_key=candidate_identity_key(selected_candidate),
                expected_candidate=candidate_identity(selected_candidate),
                label=selected,
            ),
        )
        _rerun()

    if validation_state.get("state") == "stale":
        st.warning("Non validé depuis cette nouvelle proposition")
    elif validation:
        st.caption("Validation POC : " + str(validation_state.get("status") or validation.get("status")))


def _render_match_readonly(match: dict, match_index: int):
    ocr_payload = match.get("ocr") or {}
    orientation = int(match.get("orientation_degrees") or 0)
    st.markdown(
        f"**Zone carte {match_index + 1} · {match.get('method')} · {match.get('status')} · "
        f"score {match.get('score', 0)} · marge {match.get('margin', 0)}**"
    )
    st.caption("Raison : " + str(match.get("diagnostic_reason") or "—"))
    st.caption(
        "OCR nom : "
        + " / ".join(ocr_payload.get("name_texts") or ["—"])
        + " · OCR numéro : "
        + " / ".join(ocr_payload.get("number_texts") or ["—"])
    )
    rows = [_candidate_row(candidate_row) for candidate_row in (match.get("candidates") or [])[:3]]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
        cols = st.columns(min(3, len(rows)))
        for idx, candidate_row in enumerate((match.get("candidates") or [])[:3]):
            candidate = candidate_row.get("candidate") or {}
            with cols[idx]:
                if candidate.get("image_url"):
                    st.image(candidate.get("image_url"), use_container_width=True)
                st.caption(f"#{idx + 1} · {candidate.get('name')} · {candidate.get('number')}")
    photo = match.get("photo")
    if photo:
        with st.expander("Afficher le crop OCR", expanded=False):
            crop_cols = st.columns(3)
            name_crop = _image_crop(photo.path, "name", orientation)
            number_crop = _image_crop(photo.path, "number", orientation)
            card_crop = _image_crop(photo.path, "card", orientation)
            artwork_crop = _image_crop(photo.path, "artwork", orientation)
            if name_crop:
                crop_cols[0].image(name_crop, caption="crop nom", use_container_width=True)
            if number_crop:
                crop_cols[1].image(number_crop, caption="crop numéro", use_container_width=True)
            if card_crop:
                crop_cols[2].image(card_crop, caption="carte", use_container_width=True)
            if artwork_crop:
                st.image(artwork_crop, caption="crop artwork", width=320)


def _render_full_check_match(
    match: dict,
    match_index: int,
    *,
    sample_key: str,
    sample: dict,
    group_id: str,
):
    ocr_payload = match.get("ocr") or {}
    candidate_rows = (match.get("candidates") or [])[:3]
    primary_row = candidate_rows[0] if candidate_rows else {}
    primary = primary_row.get("candidate") or {}

    st.markdown(
        f"**Zone carte {match_index + 1} · {match.get('method')} · {match.get('status')}**"
    )
    if primary:
        card_cols = st.columns([0.7, 1.7])
        with card_cols[0]:
            if primary.get("image_url"):
                st.image(primary.get("image_url"), width=190)
            else:
                st.info("Image référence indisponible")
        with card_cols[1]:
            st.markdown("#### Carte proposée")
            st.markdown(f"**{primary.get('name') or 'Carte inconnue'} · {primary.get('number') or '—'}**")
            st.caption(primary.get("set") or "Set non renseigné")
            st.caption(f"Variante : {_variant_label(primary)}")
            st.markdown(
                f"Score **{match.get('score', 0)}** · marge **{match.get('margin', 0)}**"
            )
            st.caption("Raison : " + str(match.get("diagnostic_reason") or "—"))
    else:
        st.warning("Aucun candidat proposé pour cette zone.")

    orientation = int(match.get("orientation_degrees") or 0)
    layout_type = str(match.get("layout_type") or "standard")
    if orientation or layout_type != "standard":
        st.caption(f"Orientation retenue : {orientation}° · layout : {layout_type}")

    not_in_drop = str(match.get("v13_not_in_drop_confidence") or "")
    if not_in_drop:
        st.warning(
            "Carte absente du Drop"
            + (" · forte confiance" if not_in_drop == "strong" else " · possible")
        )
        prepared = (_source_group(sample, group_id).get("prepared_drop_additions") or {}).get(str(match_index))
        if prepared:
            st.success(f"Ajout POC préparé : {prepared.get('name') or 'carte sans nom'} · {prepared.get('number') or '—'}")
        with st.popover("Ajouter cette carte au Drop"):
            st.caption("Préparation POC uniquement. Aucune donnée réelle ne sera modifiée.")
            default_name = ((ocr_payload.get("name_texts") or [""])[0])
            default_number = ((ocr_payload.get("collector_number_texts") or ocr_payload.get("number_texts") or [""])[0])
            with st.form(f"poc_prepare_add_{group_id}_{match_index}"):
                name = st.text_input("Nom", value=default_name)
                number = st.text_input("Numéro", value=default_number)
                set_name = st.text_input("Set", value="")
                flags = st.columns(4)
                japanese = flags[0].toggle("JAP", value=False)
                reverse = flags[1].toggle("Reverse", value=False)
                stamp = flags[2].toggle("Stamp", value=False)
                promo = flags[3].toggle("Promo", value=False)
                notes = st.text_area("Notes", value="")
                if st.form_submit_button("Préparer l'ajout", type="primary"):
                    photo = match.get("photo")
                    _prepare_drop_addition(
                        sample_key,
                        sample,
                        group_id,
                        match_index,
                        {
                            "name": name.strip(),
                            "number": number.strip(),
                            "set": set_name.strip(),
                            "japanese": japanese,
                            "reverse": reverse,
                            "stamp": stamp,
                            "promo": promo,
                            "notes": notes.strip(),
                            "source_photo": getattr(photo, "filename", ""),
                            "capture_index": getattr(photo, "capture_index", None),
                            "status": "prepared_only",
                        },
                    )
                    st.success("Ajout préparé localement.")

    show_debug = st.toggle(
        "Voir les autres candidats / debug",
        value=False,
        key=f"photo_poc_match_debug_{group_id}_{match.get('subcard_id') or match_index}",
    )
    if show_debug:
        st.caption(
            "OCR nom : "
            + " / ".join(ocr_payload.get("name_texts") or ["—"])
            + " · OCR numéro : "
            + " / ".join(ocr_payload.get("number_texts") or ["—"])
        )
        if ocr_payload.get("all_number_texts"):
            st.caption("Numéros debug tous crops : " + " / ".join(ocr_payload.get("all_number_texts") or []))
        if ocr_payload.get("v_union_edge_numbers"):
            st.caption("Numéros V-UNION lus sur les bords : " + " / ".join(ocr_payload.get("v_union_edge_numbers") or []))
        if match.get("v14_same_name_candidates"):
            st.caption("Même nom dans le Drop, versions exactes contrôlées :")
            st.dataframe(match.get("v14_same_name_candidates"), width="stretch", hide_index=True)
        if match.get("subcard_id"):
            st.caption(f"Sous-carte physique : {match.get('subcard_id')} · {match.get('subcard_photos') or {}}")
        rows = [_candidate_row(candidate_row) for candidate_row in candidate_rows]
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        other_rows = candidate_rows[1:3]
        if other_rows:
            cols = st.columns(len(other_rows))
            for idx, candidate_row in enumerate(other_rows, start=2):
                candidate = candidate_row.get("candidate") or {}
                with cols[idx - 2]:
                    if candidate.get("image_url"):
                        st.image(candidate.get("image_url"), width=120)
                    st.caption(f"#{idx} · {candidate.get('name')} · {candidate.get('number')}")
        photo = match.get("photo")
        show_crops = st.toggle(
            "Afficher les crops OCR",
            value=False,
            key=f"photo_poc_match_crops_{group_id}_{match.get('subcard_id') or match_index}",
        )
        if photo and show_crops:
            crop_cols = st.columns(3)
            name_crop = _image_crop(photo.path, "name", orientation)
            number_crop = _image_crop(photo.path, "number", orientation)
            card_crop = _image_crop(photo.path, "card", orientation)
            artwork_crop = _image_crop(photo.path, "artwork", orientation)
            if name_crop:
                crop_cols[0].image(name_crop, caption="crop nom", width=220)
            if number_crop:
                crop_cols[1].image(number_crop, caption="crop numéro", width=220)
            if card_crop:
                crop_cols[2].image(card_crop, caption="carte", width=220)
            if artwork_crop:
                st.image(artwork_crop, caption="crop artwork", width=260)


def _recognition_is_done(sample: dict, group_id: str, matches: list[dict]) -> bool:
    matches = matches or [{}]
    return all(
        _validation_state(_recognition_validation(sample, group_id, index, match), match).get("state")
        in {"compatible", "explicit_truth"}
        for index, match in enumerate(matches)
    )


def _recognition_is_resolved_correct(sample: dict, group_id: str, matches: list[dict]) -> bool:
    matches = matches or [{}]
    return all(
        _validation_state(_recognition_validation(sample, group_id, index, match), match).get("resolved_for_workflow")
        for index, match in enumerate(matches)
    )


def _pending_groups(result: dict, sample: dict, levels: set[str]) -> list[dict]:
    pending = []
    for group in result.get("groups", []) or []:
        if group.get("confidence_level") not in levels:
            continue
        group_id = _result_group_id(group)
        if _recognition_is_done(sample, group_id, group.get("matches", []) or []):
            continue
        pending.append(group)
    return pending


def _queue_candidate_selector(candidates: list[dict], key: str) -> tuple[str, str | None]:
    candidate_options = _candidate_options(candidates)
    selected = st.selectbox("Choisir une carte du Drop", [""] + list(candidate_options.keys()), key=key)
    return selected, candidate_options.get(selected)


def _render_queue_view(
    sample_key: str,
    sample: dict,
    result: dict,
    *,
    levels: set[str],
    title: str,
    queue_key: str,
    allow_good_card: bool,
):
    groups = _pending_groups(result, sample, levels)
    if not groups:
        st.success(f"{title} : aucune annonce restante dans cette file.")
        return

    index_key = f"photo_poc_queue_index_{queue_key}"
    st.session_state[index_key] = min(int(st.session_state.get(index_key, 0) or 0), len(groups) - 1)
    current_index = st.session_state[index_key]
    group = groups[current_index]
    group_id = _result_group_id(group)
    path_by_key = _photo_path_by_key(result)

    st.markdown(f"### {title} — {current_index + 1} / {len(groups)}")
    st.caption(
        f"Annonce #{group.get('announcement_index')} · grouping {group.get('grouping_status')} · "
        f"{group.get('expected_cards', 1)} carte(s)"
    )
    _render_group_photos({"photos": _group_photo_payloads(group)}, path_by_key, compact=True)
    if group.get("grouping_reasons"):
        st.caption("Grouping : " + " · ".join(group.get("grouping_reasons") or []))

    matches = group.get("matches", []) or []
    if not matches:
        st.warning("Aucune zone carte exploitable dans ce groupe.")
        c1, c2 = st.columns(2)
        if c1.button("Corriger le groupe", key=f"queue_group_fix_{queue_key}_{group_id}"):
            _request_view("Validation des groupes")
        if c2.button("Non reconnu confirmé", key=f"queue_unrecognized_empty_{queue_key}_{group_id}"):
            _set_recognition_validation(
                sample_key,
                group_id,
                0,
                _validation_payload("non_recognized", {}),
            )
            _rerun()
        return

    candidates = result.get("candidates", [])
    for match_index, match in enumerate(matches):
        validation = _recognition_validation(sample, group_id, match_index, match)
        validation_state = _validation_state(validation, match)
        if validation_state.get("state") in {"compatible", "explicit_truth"}:
            st.caption(f"Zone {match_index + 1} déjà traitée : {validation_state.get('status')}")
            continue
        if validation_state.get("state") == "stale":
            st.warning("Non validé depuis cette nouvelle proposition")
        _render_match_readonly(match, match_index)
        action_cols = st.columns([1, 1.15, 1.2, 1])
        if allow_good_card and action_cols[0].button("✓ Bonne carte", key=f"queue_ok_{queue_key}_{group_id}_{match_index}"):
            _set_recognition_validation(sample_key, group_id, match_index, _validation_payload("correct", match))
            _rerun()
        if action_cols[1].button("Non reconnu", key=f"queue_fail_{queue_key}_{group_id}_{match_index}"):
            _set_recognition_validation(sample_key, group_id, match_index, _validation_payload("non_recognized", match))
            _rerun()
        if action_cols[2].button("Corriger le groupe", key=f"queue_fix_{queue_key}_{group_id}_{match_index}"):
            _request_view("Validation des groupes")
        if action_cols[3].button("Passer", key=f"queue_skip_{queue_key}_{group_id}_{match_index}"):
            st.session_state[index_key] = (current_index + 1) % max(1, len(groups))
            _rerun()

        selected, drop_card_key = _queue_candidate_selector(candidates, f"queue_choose_{queue_key}_{group_id}_{match_index}")
        if selected and st.button("Valider ce choix", key=f"queue_choose_save_{queue_key}_{group_id}_{match_index}", type="primary"):
            selected_candidate = next(
                (candidate for candidate in candidates if candidate.get("drop_card_key") == drop_card_key),
                {},
            )
            _set_recognition_validation(
                sample_key,
                group_id,
                match_index,
                _validation_payload(
                    "manual_choice",
                    match,
                    drop_card_key=drop_card_key,
                    expected_candidate_key=candidate_identity_key(selected_candidate),
                    expected_candidate=candidate_identity(selected_candidate),
                    label=selected,
                ),
            )
            _rerun()


def _green_quality_groups(result: dict, sample: dict, target_count: int = 10) -> list[dict]:
    green_groups = [group for group in result.get("groups", []) or [] if group.get("confidence_level") == "green"]
    green_groups = [
        group
        for group in green_groups
        if not _recognition_is_done(sample, _result_group_id(group), group.get("matches", []) or [])
    ]
    priority_groups = [
        group
        for group in green_groups
        if any(match.get("v8_auto_reason") for match in group.get("matches", []) or [])
    ]
    edge_groups = sorted(
        [
            group
            for group in green_groups
            if group not in priority_groups
            and any(float(match.get("margin") or 0) <= 18 for match in group.get("matches", []) or [])
        ],
        key=lambda group: min(float(match.get("margin") or 999) for match in group.get("matches", []) or [{}]),
    )
    variant_groups = [
        group
        for group in green_groups
        if group not in priority_groups
        and group not in edge_groups
        and any(
            (((match.get("candidates") or [{}])[0]).get("candidate") or {}).get(flag)
            for match in group.get("matches", []) or []
            for flag in ("japanese", "reverse", "first_edition", "stamp", "promo", "pokeball", "masterball")
        )
    ]
    ordered_priority = []
    for group in priority_groups + edge_groups + variant_groups:
        if group not in ordered_priority:
            ordered_priority.append(group)
    if len(green_groups) <= target_count:
        return green_groups
    if len(ordered_priority) >= target_count:
        return ordered_priority[:target_count]
    picks = sorted({round(index * (len(green_groups) - 1) / max(1, target_count - 1)) for index in range(target_count)})
    sampled = ordered_priority[:]
    for index in picks:
        group = green_groups[index]
        if group not in sampled:
            sampled.append(group)
        if len(sampled) >= target_count:
            break
    return sampled


def _render_green_quality_view(sample_key: str, sample: dict, result: dict):
    groups = _green_quality_groups(result, sample)
    if not groups:
        st.success("Contrôle verts : aucun reconnu restant à contrôler dans l'échantillon automatique.")
        return
    index_key = "photo_poc_green_quality_index"
    st.session_state[index_key] = min(int(st.session_state.get(index_key, 0) or 0), len(groups) - 1)
    current_index = st.session_state[index_key]
    group = groups[current_index]
    group_id = _result_group_id(group)
    path_by_key = _photo_path_by_key(result)

    st.markdown(f"### Contrôle verts — {current_index + 1} / {len(groups)}")
    st.caption("Échantillon réparti dans le dataset : début, milieu, fin et scores variés.")
    _render_group_photos({"photos": _group_photo_payloads(group)}, path_by_key, compact=True)
    for match_index, match in enumerate(group.get("matches", []) or []):
        validation = _recognition_validation(sample, group_id, match_index, match)
        validation_state = _validation_state(validation, match)
        if validation_state.get("state") in {"compatible", "explicit_truth"}:
            st.caption(f"Zone {match_index + 1} déjà contrôlée : {validation_state.get('status')}")
            continue
        if validation_state.get("state") == "stale":
            st.warning("Non validé depuis cette nouvelle proposition")
        _render_match_readonly(match, match_index)
        c1, c2, c3 = st.columns(3)
        if c1.button("✓ Correct", key=f"green_ok_{group_id}_{match_index}", type="primary"):
            _set_recognition_validation(sample_key, group_id, match_index, _validation_payload("correct", match))
            _rerun()
        if c2.button("✕ Mauvais", key=f"green_bad_{group_id}_{match_index}"):
            _set_recognition_validation(sample_key, group_id, match_index, _validation_payload("wrong", match))
            _rerun()
        if c3.button("Passer", key=f"green_skip_{group_id}_{match_index}"):
            st.session_state[index_key] = (current_index + 1) % max(1, len(groups))
            _rerun()


@st.fragment
def _render_full_check_view(sample_key: str, sample: dict, result: dict):
    groups = result.get("groups", []) or []
    if not groups:
        st.info("Aucune annonce à vérifier.")
        return
    index_key = "photo_poc_full_check_index"
    completed = sum(
        1
        for candidate_group in groups
        if _recognition_is_done(
            sample,
            _result_group_id(candidate_group),
            candidate_group.get("matches", []) or [],
        )
    )
    st.caption(f"Annonces contrôlées : {completed} / {len(groups)}")
    if completed >= len(groups):
        st.success(f"🎉 Vérification terminée — {len(groups)} / {len(groups)}")
        latencies = st.session_state.get("photo_poc_validation_latencies_ms") or []
        if latencies:
            st.caption(f"Latence moyenne des {len(latencies)} derniers clics : {sum(latencies) / len(latencies):.1f} ms")
        c1, c2 = st.columns(2)
        if c1.button("Voir le bilan", type="primary", key="full_check_summary"):
            _request_view("Synthèse complète")
        if c2.button("Revoir les erreurs", key="full_check_errors"):
            _request_view("Erreurs uniquement")

    if index_key not in st.session_state:
        pending_indices = [
            index
            for index, candidate_group in enumerate(groups)
            if not _recognition_is_done(
                sample,
                _result_group_id(candidate_group),
                candidate_group.get("matches", []) or [],
            )
        ]
        st.session_state[index_key] = pending_indices[0] if pending_indices else 0
    st.session_state[index_key] = min(int(st.session_state.get(index_key, 0) or 0), len(groups) - 1)
    current_index = st.session_state[index_key]
    group = groups[current_index]
    group_id = _result_group_id(group)
    level = group.get("confidence_level", "red")
    path_by_key = _photo_path_by_key(result)

    st.markdown(f"### Annonce {current_index + 1} / {len(groups)}")
    st.caption(
        f"Annonce #{group.get('announcement_index')} · {STATUS_LABELS.get(level, level)} · "
        f"grouping {group.get('grouping_status')} · {group.get('expected_cards', 1)} carte(s)"
    )
    _render_group_photos({"photos": _group_photo_payloads(group)}, path_by_key, compact=True)
    matches = group.get("matches", []) or []
    if len(matches) > 1:
        st.markdown(f"**{len(matches)} sous-cartes physiques — validation indépendante**")
    for match_index, match in enumerate(matches):
        _render_full_check_match(
            match,
            match_index,
            sample_key=sample_key,
            sample=sample,
            group_id=group_id,
        )
        validation = _recognition_validation(sample, group_id, match_index, match)
        validation_state = _validation_state(validation, match)
        if validation_state.get("state") in {"compatible", "explicit_truth"}:
            if validation_state.get("resolved_correct"):
                st.success("Validation POC : correct")
            else:
                st.error("Validation POC : wrong")
            continue
        if validation_state.get("state") == "stale":
            st.warning("Non validé depuis cette nouvelle proposition")
        c1, c2 = st.columns(2)
        c1.button(
            "✓ Correct",
            key=f"full_ok_{group_id}_{match_index}",
            type="primary",
            on_click=_full_check_validation_callback,
            args=(sample_key, sample, group_id, match_index, "correct", index_key, current_index, len(groups), matches, match),
        )
        c2.button(
            "✕ Mauvais",
            key=f"full_bad_{group_id}_{match_index}",
            on_click=_full_check_validation_callback,
            args=(sample_key, sample, group_id, match_index, "wrong", index_key, current_index, len(groups), matches, match),
        )
    nav1, nav2 = st.columns(2)
    nav1.button(
        "← Précédente",
        key="full_prev",
        disabled=current_index == 0,
        on_click=_set_queue_index,
        args=(index_key, current_index - 1),
    )
    nav2.button(
        "Suivante →",
        key="full_next_bottom",
        disabled=current_index >= len(groups) - 1,
        on_click=_set_queue_index,
        args=(index_key, min(len(groups) - 1, current_index + 1)),
    )


SENSITIVE_FILTERS = ("Tous", "JAP", "Multi", "LÉGENDE", "Not in Drop", "Fails", "Grouping")


def _sensitive_reasons(group: dict) -> list[str]:
    matches = group.get("matches", []) or []
    is_multi = len(matches) > 1 or int(group.get("expected_cards") or 1) > 1
    has_japanese = (
        bool(group.get("jp_physical"))
        or bool(group.get("v13_japanese_candidate"))
        or str(group.get("v13_back_type") or "").startswith("back_japanese")
    )
    has_special_layout = any(
        str(match.get("layout_type") or "standard").upper() in {"LEGEND_HALF", "UNKNOWN_SPECIAL"}
        or (
            bool(match.get("special_layout"))
            and str(match.get("layout_type") or "standard").upper() != "V_UNION"
        )
        or (
            int(match.get("orientation_degrees") or 0) != 0
            and str(match.get("layout_type") or "standard").upper() != "V_UNION"
        )
        for match in matches
    )
    has_not_in_drop = any(bool(match.get("v13_not_in_drop_confidence")) for match in matches)
    has_fail = group.get("confidence_level") == "red" or any(
        match.get("status") in {"unrecognized", "fail"} for match in matches
    )
    has_grouping_review = group.get("grouping_status") == "review"
    has_multi_review = is_multi and any(
        match.get("status") in {"review", "unrecognized", "fail"} for match in matches
    )
    reasons = []
    if has_japanese:
        reasons.append("JAP")
    if is_multi:
        reasons.append("MULTI")
    if has_special_layout:
        reasons.append("LÉGENDE")
    if has_not_in_drop:
        reasons.append("NOT IN DROP")
    if has_fail:
        reasons.append("FAIL")
    if has_grouping_review:
        reasons.append("GROUPING")
    if has_multi_review:
        reasons.append("REVIEW")
    return reasons


def _group_has_stale_validation(sample: dict, group: dict) -> bool:
    group_id = _result_group_id(group)
    return any(
        _validation_state(_recognition_validation(sample, group_id, index, match), match).get("state") == "stale"
        for index, match in enumerate(group.get("matches", []) or [{}])
    )


def _format_semantic_proposal(proposal: dict) -> str:
    proposal = proposal or {}
    card_uid = str(proposal.get("candidate_card_uid") or "").strip()
    status = str(proposal.get("candidate_status") or "fail")
    # The candidate object is the current rendering source. A stale historical
    # not_in_drop status must never hide it as "Aucun candidat".
    if card_uid:
        return f"{card_uid} ({status})"
    if status == "not_in_drop":
        return "Aucun candidat dans le Drop"
    return f"Aucun candidat ({status})"


@st.fragment
def _render_changed_proposals_view(sample_key: str, sample: dict, result: dict):
    changes = _proposal_change_rows(sample, result)
    st.markdown(f"### Propositions réellement modifiées : {len(changes)}")
    if not changes:
        st.success("Aucune proposition n'a changé depuis sa validation.")
        return

    index_key = "photo_poc_changed_proposal_index"
    st.session_state[index_key] = min(int(st.session_state.get(index_key, 0) or 0), len(changes) - 1)
    current_index = st.session_state[index_key]
    change = changes[current_index]
    group = change["group"]
    group_id = change["group_id"]
    match_index = change["match_index"]
    match = (group.get("matches") or [{}])[match_index]
    # ``after`` and the large card below must come from the same current match.
    # This avoids displaying an old not-in-Drop label beside a new candidate.
    change = {**change, "after": _semantic_proposal(match)}
    st.caption(f"Annonce #{group.get('announcement_index')} · sous-carte {match_index + 1} · raison : {change['reason']}")
    before_col, after_col = st.columns(2)
    before_col.info("Avant : " + _format_semantic_proposal(change["before"]))
    after_col.warning("Après : " + _format_semantic_proposal(change["after"]))
    _render_group_photos({"photos": _group_photo_payloads(group)}, _photo_path_by_key(result), compact=True)
    _render_full_check_match(match, match_index, sample_key=sample_key, sample=sample, group_id=group_id)

    left, middle, right = st.columns(3)
    if left.button("✓ Correct", key=f"changed_ok_{group_id}_{match_index}"):
        _set_recognition_validation(sample_key, group_id, match_index, _validation_payload("correct", match))
        _rerun()
    if middle.button("✕ Mauvais", key=f"changed_wrong_{group_id}_{match_index}"):
        _set_recognition_validation(sample_key, group_id, match_index, _validation_payload("wrong", match))
        _rerun()
    if right.button("Suivant", key=f"changed_next_{group_id}_{match_index}"):
        st.session_state[index_key] = (current_index + 1) % len(changes)
        _rerun()


def _sensitive_groups(
    result: dict,
    sample: dict,
    filter_name: str = "Tous",
    *,
    include_resolved=False,
    stale_only=False,
) -> list[dict]:
    groups = []
    for group in result.get("groups", []) or []:
        reasons = _sensitive_reasons(group)
        is_stale = _group_has_stale_validation(sample, group)
        if stale_only:
            if not is_stale:
                continue
        elif not reasons and not is_stale:
            continue
        resolved_correct = _recognition_is_resolved_correct(
            sample,
            _result_group_id(group),
            group.get("matches", []) or [],
        )
        has_current_structural_issue = "GROUPING" in reasons
        if not include_resolved and resolved_correct and not has_current_structural_issue and not is_stale:
            continue
        if filter_name != "Tous":
            expected_reason = {
                "Multi": "MULTI",
                "LÉGENDE": "LÉGENDE",
                "Not in Drop": "NOT IN DROP",
                "Fails": "FAIL",
                "Grouping": "GROUPING",
            }.get(filter_name, filter_name.upper())
            if expected_reason not in reasons:
                continue
        groups.append(group)
    return groups


def _set_sensitive_filter(filter_name: str):
    st.session_state["photo_poc_sensitive_filter_override"] = filter_name
    st.session_state.pop(f"photo_poc_sensitive_index_{filter_name}", None)


@st.fragment
def _render_sensitive_cases_view(sample_key: str, sample: dict, result: dict, *, stale_only=False):
    include_resolved = st.toggle(
        "Afficher aussi les cas déjà validés",
        value=False,
        key="photo_poc_sensitive_include_resolved_stale" if stale_only else "photo_poc_sensitive_include_resolved",
        disabled=stale_only,
    )
    all_cases = _sensitive_groups(
        result,
        sample,
        include_resolved=include_resolved,
        stale_only=stale_only,
    )
    if not all_cases:
        st.success("Aucun cas sensible dans le résultat actuel.")
        return

    heading = "Propositions modifiées à revalider" if stale_only else "Cas sensibles"
    counters = {
        "JAP": sum("JAP" in _sensitive_reasons(group) for group in all_cases),
        "Multi": sum("MULTI" in _sensitive_reasons(group) for group in all_cases),
        "LÉGENDE": sum("LÉGENDE" in _sensitive_reasons(group) for group in all_cases),
        "Not in Drop": sum("NOT IN DROP" in _sensitive_reasons(group) for group in all_cases),
        "Fails": sum("FAIL" in _sensitive_reasons(group) for group in all_cases),
        "Grouping": sum("GROUPING" in _sensitive_reasons(group) for group in all_cases),
    }
    labels = {f"Tous · {len(all_cases)}": "Tous"}
    labels.update({f"{label} · {count}": label for label, count in counters.items()})
    pending_filter = st.session_state.pop("photo_poc_sensitive_filter_override", None)
    if pending_filter:
        st.session_state.pop("photo_poc_sensitive_filter", None)
    default_label = next((label for label, value in labels.items() if value == (pending_filter or "Tous")), next(iter(labels)))
    st.markdown(
        f"<div class='poc-surface-heading'><div><h2>{heading}</h2><p>{len(all_cases)} élément(s) à contrôler</p></div></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='poc-filter-label'>Filtrer les cas</div>", unsafe_allow_html=True)
    selected_label = st.pills(
        "Filtrer les cas sensibles", list(labels), selection_mode="single", default=default_label,
        key="photo_poc_sensitive_filter", label_visibility="collapsed",
    ) or default_label
    filter_name = labels.get(selected_label, "Tous")
    groups = _sensitive_groups(
        result,
        sample,
        filter_name,
        include_resolved=include_resolved,
        stale_only=stale_only,
    )
    if not groups:
        st.info(f"Aucun cas sensible pour le filtre {filter_name}.")
        return

    index_key = f"photo_poc_sensitive_index_{'stale_' if stale_only else ''}{filter_name}"
    if index_key not in st.session_state:
        pending_indices = [
            index
            for index, candidate_group in enumerate(groups)
            if not _recognition_is_done(
                sample,
                _result_group_id(candidate_group),
                candidate_group.get("matches", []) or [],
            )
        ]
        st.session_state[index_key] = pending_indices[0] if pending_indices else 0
    st.session_state[index_key] = min(int(st.session_state.get(index_key, 0) or 0), len(groups) - 1)
    current_index = st.session_state[index_key]
    group = groups[current_index]
    group_id = _result_group_id(group)
    matches = group.get("matches", []) or []
    completed = sum(
        1
        for candidate_group in groups
        if _recognition_is_done(
            sample,
            _result_group_id(candidate_group),
            candidate_group.get("matches", []) or [],
        )
    )
    if completed >= len(groups):
        st.success("Vérification des cas sensibles terminée")
        end_left, end_right = st.columns(2)
        if end_left.button("Voir le bilan", type="primary", key=f"sensitive_summary_{filter_name}"):
            _request_view("Vue d’ensemble")
        end_right.button(
            "Revoir les cas mauvais",
            key=f"sensitive_bad_{filter_name}",
            on_click=_set_sensitive_filter,
            args=("Fails",),
        )

    reasons = _sensitive_reasons(group)
    if _group_has_stale_validation(sample, group):
        reasons = [*reasons, "PROPOSITION MODIFIÉE"]
    chip_class = {
        "JAP": "poc-rose", "MULTI": "poc-violet", "LÉGENDE": "poc-amber",
        "NOT IN DROP": "poc-red", "FAIL": "poc-red", "GROUPING": "poc-orange",
        "REVIEW": "poc-orange", "PROPOSITION MODIFIÉE": "poc-orange",
    }
    badge_pairs = [(reason, chip_class.get(reason, "poc-violet")) for reason in reasons]
    _render_review_surface(
        sample_key, sample, result, group, index_key=index_key, current_index=current_index,
        group_count=len(groups), key_prefix=f"sensitive_{filter_name}", heading="Cas sensible",
        badges=badge_pairs,
    )


def _group_visible(group: dict, mode: str) -> bool:
    level = group.get("confidence_level", "red")
    if mode == "Tous":
        return True
    if mode == "🟢 Reconnus":
        return level == "green"
    if mode == "🟠 À vérifier":
        return level == "orange"
    if mode == "🔴 Non reconnus":
        return level == "red"
    if mode == "Grouping douteux":
        return group.get("grouping_status") == "review"
    if mode == "JP":
        return bool(group.get("jp_physical")) or bool(group.get("v13_japanese_candidate")) or str(group.get("v13_back_type") or "").startswith("back_japanese") or any(
            ((entry.get("classification") or {}).get("back_type") == "japanese") for entry in group.get("photos", [])
        )
    if mode == "Multi-cartes":
        return int(group.get("expected_cards") or 1) > 1 or len(group.get("matches", []) or []) > 1
    if mode == "Erreurs uniquement":
        return level != "green" or group.get("grouping_status") == "review"
    return True


def _render_results_view(sample_key: str, sample: dict, result: dict):
    st.markdown("### Résultats / debug reconnaissance")
    only_validated = st.checkbox("Afficher uniquement les groupes validés", value=True)
    if only_validated:
        if not any(normalize_group_status(group.get("status")) in VALIDATED_GROUP_STATUSES for group in sample.get("groups", [])):
            st.warning("Aucun groupe validé pour l'instant. Valide d'abord des groupes dans la vue dédiée.")
            return result

    metrics = result["metrics"]
    _render_metrics(metrics)
    if metrics.get("ground_truth_mode"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("GT groupes", metrics.get("ground_truth_groups", 0))
        c2.metric("GT validés", metrics.get("ground_truth_validated", 0))
        c3.metric("GT corrigés", metrics.get("ground_truth_corrected", 0))
        c4.metric("Annonces réelles", metrics.get("real_announcements", 0))

    validated_matches = 0
    wrong_auto = 0
    manual_choices = 0
    for group in result.get("groups", []):
        group_id = _result_group_id(group)
        for match_index, match in enumerate(group.get("matches", []) or []):
            validation = _recognition_validation(sample, group_id, match_index, match)
            state = _validation_state(validation, match)
            if state.get("state") in {"compatible", "explicit_truth"}:
                validated_matches += 1
            if (
                match.get("status") == "recognized"
                and state.get("state") in {"compatible", "explicit_truth"}
                and not state.get("resolved_correct")
            ):
                wrong_auto += 1
            if state.get("state") in {"compatible", "explicit_truth"} and validation.get("status") == "manual_choice":
                manual_choices += 1
    if validated_matches:
        r1, r2, r3 = st.columns(3)
        r1.metric("Reconnaissances validées", validated_matches)
        r2.metric("Auto faux", wrong_auto)
        r3.metric("Choix manuels", manual_choices)
        st.caption("silent wrong match = " + ("0 confirmé sur les validations saisies" if wrong_auto == 0 else str(wrong_auto)))

    diagnostic_causes = metrics.get("diagnostic_causes") or {}
    if diagnostic_causes:
        with st.expander("Résumé causes review/fail", expanded=True):
            st.dataframe(
                [{"cause": cause, "cas": count} for cause, count in sorted(diagnostic_causes.items(), key=lambda item: item[1], reverse=True)],
                width="stretch",
                hide_index=True,
            )

    filter_mode = st.selectbox(
        "Filtre debug",
        ["Tous", "🟢 Reconnus", "🟠 À vérifier", "🔴 Non reconnus", "Erreurs uniquement", "Grouping douteux", "JP", "Multi-cartes"],
    )

    path_by_key = _photo_path_by_key(result)
    for group in result.get("groups", []):
        if only_validated:
            source_group = _source_group(sample, _result_group_id(group))
            if normalize_group_status(source_group.get("status")) not in VALIDATED_GROUP_STATUSES:
                continue
        if not _group_visible(group, filter_mode):
            continue
        level = group.get("confidence_level", "red")
        chip_cls = {"green": "poc-green", "orange": "poc-orange", "red": "poc-red"}.get(level, "poc-red")
        st.markdown(
            f"""
            <div class="poc-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:center;flex-wrap:wrap;">
                <strong>Annonce #{group['announcement_index']}</strong>
                <span class="poc-chip {chip_cls}">{STATUS_LABELS.get(level, '🔴 Non reconnu')}</span>
              </div>
              <div class="poc-mini">grouping: {group.get('grouping_status')} · cartes: {group.get('expected_cards', 1)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_group_photos(
            {"photos": _group_photo_payloads(group)},
            path_by_key,
        )
        if group.get("grouping_reasons"):
            st.caption("Grouping : " + " · ".join(group.get("grouping_reasons") or []))
        group_id = _result_group_id(group)
        for match_index, match in enumerate(group.get("matches", []) or []):
            _render_match_debug(match, sample_key, sample, group_id, match_index, result.get("candidates", []))
    return result


def _render_errors_view(sample_key: str, sample: dict, result: dict):
    st.markdown("### Erreurs uniquement")
    path_by_key = _photo_path_by_key(result)
    candidates = result.get("candidates", [])
    count = 0
    for group in result.get("groups", []):
        if group.get("confidence_level") == "green" and group.get("grouping_status") != "review":
            continue
        count += 1
        st.markdown(f"#### Annonce #{group.get('announcement_index')} · {STATUS_LABELS.get(group.get('confidence_level'), '🔴 Non reconnu')}")
        _render_group_photos(
            {"photos": _group_photo_payloads(group)},
            path_by_key,
            compact=True,
        )
        group_id = _result_group_id(group)
        for match_index, match in enumerate(group.get("matches", []) or []):
            _render_match_debug(match, sample_key, sample, group_id, match_index, candidates)
    if count == 0:
        st.success("Aucune erreur/review dans la sélection actuelle.")


_apply_pending_view()

run = False
run_all = False
with st.sidebar:
    st.markdown("<div class='poc-nav-brand'><span>◉</span> PokéStock</div>", unsafe_allow_html=True)
    st.markdown("<div class='poc-nav-section'>WORKFLOW PHOTO</div>", unsafe_allow_html=True)
    active_view = st.session_state.get("photo_poc_view", "Vue d’ensemble")
    nav_items = [
        ("Vue d’ensemble", ":material/dashboard:"),
        ("À vérifier", ":material/fact_check:"),
        ("Cas sensibles", ":material/warning_amber:"),
        ("Validés", ":material/task_alt:"),
        ("Grouping", ":material/account_tree:"),
        ("Diagnostic", ":material/monitoring:"),
    ]
    nav_metrics = (st.session_state.get(CURRENT_RESULT_KEY) or {}).get("metrics") or {}
    nav_counts = {
        "À vérifier": int(nav_metrics.get("to_review") or 0),
        "Cas sensibles": int(nav_metrics.get("sensitive_cases_remaining") or nav_metrics.get("grouping_review") or 0),
        "Validés": int(nav_metrics.get("auto_recognized") or 0),
    }
    for nav_label, nav_icon in nav_items:
        count = nav_counts.get(nav_label)
        count_text = f" · {count}" if count else ""
        st.button(
            f"{nav_icon} {nav_label}{count_text}",
            key=f"photo_poc_nav_{nav_label}",
            type="primary" if active_view == nav_label else "secondary",
            use_container_width=True,
            on_click=_navigate_view_callback,
            args=(nav_label,),
        )
    st.markdown(
        "<div class='poc-nav-hint'>La source, le Drop et les paramètres d’analyse sont accessibles dans le panneau Paramètres.</div>",
        unsafe_allow_html=True,
    )

drops_data = load_vinted_drops()
drops = drops_data.get("drops", []) or []
(
    folder,
    photos,
    selected_drop_id,
    start_index,
    target_announcements,
    max_photos,
    force_rebuild,
    topbar_refresh_requested,
) = _render_workspace_topbar(drops)

if not photos:
    st.warning("Aucune photo compatible trouvée dans le dossier POC.")
    st.stop()

sample_key = sample_ground_truth_key(
    folder=folder,
    drop_id=selected_drop_id,
    start_index=start_index,
    max_photos=max_photos,
    target_announcements=target_announcements,
)

analysis_sample_key = sample_key
analysis_start_index = int(start_index)
analysis_max_photos = int(max_photos)
analysis_target_announcements = int(target_announcements)

if run_all:
    analysis_start_index = 1
    analysis_max_photos = len(photos)
    analysis_target_announcements = len(photos)
    analysis_sample_key = sample_ground_truth_key(
        folder=folder,
        drop_id=selected_drop_id,
        start_index=analysis_start_index,
        max_photos=analysis_max_photos,
        target_announcements=analysis_target_announcements,
    )

_selected_drop_snapshot, _selected_drop_candidates = active_drop_candidates(drop_id=selected_drop_id)
_selected_candidate_signature = candidate_set_signature(_selected_drop_candidates)

if bool(st.session_state.get("photo_poc_full_analysis")) and not run:
    expected_meta = _analysis_meta_for(
        folder=folder,
        photos=photos,
        drop_id=selected_drop_id,
        start_index=1,
        max_photos=len(photos),
        target_announcements=len(photos),
        candidate_signature=_selected_candidate_signature,
    )
else:
    expected_meta = _analysis_meta_for(
        folder=folder,
        photos=photos,
        drop_id=selected_drop_id,
        start_index=analysis_start_index,
        max_photos=analysis_max_photos,
        target_announcements=analysis_target_announcements,
        candidate_signature=_selected_candidate_signature,
    )

if CURRENT_RESULT_KEY not in st.session_state and "photo_poc_result" in st.session_state:
    st.session_state[CURRENT_RESULT_KEY] = st.session_state.pop("photo_poc_result")

restored_from_cache = False
if not (run or run_all) and CURRENT_RESULT_KEY not in st.session_state:
    cache_started = time.perf_counter()
    cached_result = load_cached_analysis_result(
        folder=folder,
        drop_id=selected_drop_id,
        start_index=analysis_start_index,
        target_announcements=analysis_target_announcements,
        max_photos=analysis_max_photos,
        ordered_photos=photos,
    )
    if cached_result is None:
        cached_result = load_latest_cached_analysis_result(
            folder=folder,
            drop_id=selected_drop_id,
            ordered_photos=photos,
        )
    if cached_result is not None:
        cached_meta = cached_result.get("analysis_meta") or {}
        cached_start = int(cached_meta.get("start_index") or 1)
        cached_max = int(cached_meta.get("max_photos") or len(cached_result.get("sample_photos", []) or []))
        cached_target = int(cached_meta.get("target_announcements") or cached_max)
        st.session_state[CURRENT_RESULT_KEY] = cached_result
        st.session_state["photo_poc_sample_key"] = sample_ground_truth_key(
            folder=folder,
            drop_id=selected_drop_id,
            start_index=cached_start,
            max_photos=cached_max,
            target_announcements=cached_target,
        )
        st.session_state["photo_poc_full_analysis"] = bool(
            cached_start == 1 and len(cached_result.get("sample_photos", []) or []) == len(photos)
        )
        restored_from_cache = True
        st.toast(
            "Résultat POC restauré en "
            f"{round((time.perf_counter() - cache_started) * 1000)} ms"
        )

if not (run or run_all) and CURRENT_RESULT_KEY in st.session_state and not restored_from_cache:
    if not _result_matches_analysis(st.session_state.get(CURRENT_RESULT_KEY), expected_meta):
        st.session_state.pop(CURRENT_RESULT_KEY, None)
        st.session_state.pop("photo_poc_sample_key", None)
        st.session_state.pop("photo_poc_full_analysis", None)
        st.info("Résultat d'analyse POC obsolète ignoré. Relance l'analyse pour utiliser le pipeline V9 actuel.")

if not (run or run_all) and CURRENT_RESULT_KEY not in st.session_state:
    selected_drop = next((drop for drop in drops if drop.get("id") == selected_drop_id), {})
    selected_drop_name = str(selected_drop.get("name") or "Drop non défini")
    selected_drop_card_count = len(selected_drop.get("cards", []) or [])
    st.markdown(
        '<div class="poc-workflow"><span class="poc-workflow-step active">Import</span>'
        '<span class="poc-workflow-arrow">→</span><span class="poc-workflow-step">Analyse</span>'
        '<span class="poc-workflow-arrow">→</span><span class="poc-workflow-step">Vérification</span>'
        '<span class="poc-workflow-arrow">→</span><span class="poc-workflow-step">Prêt</span></div>',
        unsafe_allow_html=True,
    )
    initial_view = st.session_state.get("photo_poc_view", "Vue d’ensemble")
    run, run_all = _render_empty_state(
        folder=folder,
        photo_count=len(photos),
        drop_name=selected_drop_name,
        drop_card_count=selected_drop_card_count,
        view=initial_view,
    )
    if run_all:
        analysis_start_index = 1
        analysis_max_photos = len(photos)
        analysis_target_announcements = len(photos)
        analysis_sample_key = sample_ground_truth_key(
            folder=folder,
            drop_id=selected_drop_id,
            start_index=analysis_start_index,
            max_photos=analysis_max_photos,
            target_announcements=analysis_target_announcements,
        )
    if not (run or run_all):
        st.stop()

if run or run_all:
    label = "Analyse complète des photos..." if run_all else "Analyse locale de l'échantillon..."
    progress = st.progress(0, text=f"Photos : 0 / {analysis_max_photos} · Annonces détectées : 0")
    with st.spinner(label):
        st.session_state[CURRENT_RESULT_KEY] = analyze_sample(
            folder=folder,
            drop_id=selected_drop_id,
            start_index=analysis_start_index,
            target_announcements=analysis_target_announcements,
            max_photos=analysis_max_photos,
            force_rebuild=force_rebuild,
        )
        st.session_state["photo_poc_sample_key"] = analysis_sample_key
        st.session_state["photo_poc_full_analysis"] = bool(run_all)
        done_metrics = st.session_state[CURRENT_RESULT_KEY].get("metrics") or {}
        progress.progress(
            1.0,
            text=f"Photos : {done_metrics.get('photos_analyzed', analysis_max_photos)} / {analysis_max_photos} · "
            f"Annonces détectées : {done_metrics.get('announcements_detected', 0)} · Reconnaissance terminée",
        )
    if run_all:
        done_metrics = st.session_state[CURRENT_RESULT_KEY].get("metrics") or {}
        if done_metrics.get("to_review", 0):
            st.session_state["photo_poc_pending_view"] = "À vérifier"
        elif done_metrics.get("unrecognized", 0):
            st.session_state["photo_poc_pending_view"] = "À vérifier"
        else:
            st.session_state["photo_poc_pending_view"] = "Vue d’ensemble"
        _rerun()

result = st.session_state[CURRENT_RESULT_KEY]
sample_key = st.session_state["photo_poc_sample_key"]
_live_drop, _live_candidates = _selected_drop_snapshot, _selected_drop_candidates
_live_candidate_signature = candidate_set_signature(_live_candidates)
_result_candidate_signature = str((result.get("analysis_meta") or {}).get("candidate_signature") or "")
_drop_candidates_changed = (
    _result_candidate_signature != _live_candidate_signature
    or str((result.get("analysis_meta") or {}).get("matching_refresh_version") or "")
    != POC_MATCHING_REFRESH_VERSION
)
ground_truth = ensure_ground_truth_sample(result, sample_key)
if sample_key in (ground_truth.get("samples") or {}):
    st.session_state[f"photo_poc_sample_{sample_key}"] = ground_truth["samples"][sample_key]
sample = _load_sample(sample_key)
sample = _migrate_semantic_validation_baseline(sample_key, sample, result)
_apply_v10_ground_truth_overlay(result, sample)
_sync_current_result_index(result)
metrics = result["metrics"]
drop = result.get("drop") or {}

_render_premium_header(result, sample, drop_candidates_changed=_drop_candidates_changed)

refresh_requested = topbar_refresh_requested
if _drop_candidates_changed:
    st.warning("Les cartes du Drop ont changé depuis l’analyse. Actualise-les depuis la barre supérieure.")

if refresh_requested:
    with st.spinner("Actualisation ciblée des propositions..."):
        previous_snapshot = _current_proposal_snapshot(result)
        result = refresh_result_candidates(result, drop_id=selected_drop_id)
        result.setdefault("analysis_meta", {})["proposal_snapshot_previous"] = previous_snapshot
        st.session_state[CURRENT_RESULT_KEY] = result
    st.toast(
        f"Drop actualisé · {(result.get('metrics') or {}).get('candidate_refresh_seconds', 0)} s · "
        f"{(result.get('metrics') or {}).get('candidate_groups_rematched', 0)} groupe(s) recalculé(s)"
    )
    _rerun()

view = st.session_state.get("photo_poc_view", "Vue d’ensemble")
if view not in VIEW_OPTIONS:
    view = "Vue d’ensemble"
    st.session_state["photo_poc_view"] = view

if view == "Vue d’ensemble":
    _render_overview(result, sample)
elif view == "À vérifier":
    _render_review_workspace(sample_key, sample, result)
elif view == "Cas sensibles":
    _render_sensitive_cases_view(sample_key, sample, result)
elif view == "Validés":
    _render_validated_view(sample, result)
elif view == "Grouping":
    _render_grouping_workspace(result)
else:
    _render_diagnostic_view(sample_key, sample, result)

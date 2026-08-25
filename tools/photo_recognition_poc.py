"""Streamlit POC for Vinted drop photo recognition.

Run with:
    streamlit run tools/photo_recognition_poc.py

This tool is isolated from the real Drop workflow. It reads photos and JSON
datasets, but never writes to Pokestock business data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from services.photo_recognition_poc_service import (
    POC_DIR,
    analyze_sample,
    list_ordered_photos,
    load_vinted_drops,
)


st.set_page_config(page_title="POC reconnaissance photos", layout="wide")

st.markdown(
    """
    <style>
    .poc-hero {
        background:#ffffff;border:1px solid #ddd6fe;border-left:5px solid #6d28d9;
        border-radius:14px;padding:1rem 1.15rem;margin-bottom:1rem;
        box-shadow:0 8px 20px rgba(15,23,42,0.06);
    }
    .poc-hero h1 {margin:0;color:#111827;font-size:1.35rem;}
    .poc-hero p {margin:0.25rem 0 0;color:#64748b;}
    .poc-chip {display:inline-flex;align-items:center;gap:0.25rem;border-radius:999px;
        padding:0.18rem 0.55rem;font-size:0.75rem;font-weight:800;border:1px solid #e5e7eb;}
    .poc-green {background:#dcfce7;color:#166534;border-color:#86efac;}
    .poc-orange {background:#ffedd5;color:#9a3412;border-color:#fdba74;}
    .poc-red {background:#fee2e2;color:#991b1b;border-color:#fca5a5;}
    .poc-card {background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:0.85rem;margin:0.55rem 0;}
    .poc-muted {color:#64748b;font-size:0.82rem;}
    .poc-grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:0.55rem;}
    .poc-photo img {width:100%;border-radius:9px;border:1px solid #e5e7eb;}
    .poc-photo div {font-size:0.72rem;color:#64748b;margin-top:0.2rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="poc-hero">
      <h1>POC reconnaissance automatique des photos</h1>
      <p>Lecture seule : aucune modification de data.json, vinted_drops.json ou des photos originales.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Échantillon")
    folder = st.text_input("Dossier photos", value=str(POC_DIR))
    photos = list_ordered_photos(folder)
    st.caption(f"{len(photos)} photo(s) détectée(s)")
    drops_data = load_vinted_drops()
    drops = drops_data.get("drops", []) or []
    drop_options = {f"{drop.get('name', 'Drop sans nom')} · {len(drop.get('cards', []) or [])} cartes": drop.get("id") for drop in drops}
    selected_drop_label = st.selectbox("Drop candidat", list(drop_options) or ["Aucun drop"], disabled=not bool(drop_options))
    start_index = st.number_input("capture_index de départ", min_value=1, max_value=max(1, len(photos)), value=1, step=1)
    target_announcements = st.number_input("annonces visées", min_value=5, max_value=35, value=30, step=1)
    max_photos = st.number_input("photos max à analyser", min_value=10, max_value=120, value=75, step=5)
    run = st.button("Analyser l'échantillon", type="primary")

if not photos:
    st.warning("Aucune photo compatible trouvée dans le dossier POC.")
    st.stop()

with st.expander("Ordre de capture détecté", expanded=False):
    st.dataframe(
        [
            {
                "capture_index": photo.capture_index,
                "filename": photo.filename,
                "capture_datetime": photo.capture_datetime,
                "source": photo.order_source,
                "taille Mo": round(photo.size_bytes / 1024 / 1024, 2),
            }
            for photo in photos[: min(len(photos), 160)]
        ],
        width="stretch",
        hide_index=True,
    )

if not run and "photo_poc_result" not in st.session_state:
    st.info("Choisis un bloc consécutif puis lance l'analyse. Par défaut, le POC ne traite pas tout le dossier.")
    st.stop()

if run:
    with st.spinner("Analyse locale de l'échantillon..."):
        st.session_state["photo_poc_result"] = analyze_sample(
            folder=folder,
            drop_id=drop_options.get(selected_drop_label),
            start_index=start_index,
            target_announcements=target_announcements,
            max_photos=max_photos,
        )

result = st.session_state["photo_poc_result"]
metrics = result["metrics"]
drop = result.get("drop") or {}

st.markdown(f"### Drop candidat : {drop.get('name', 'Non défini')}")
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Photos analysées", metrics["photos_analyzed"])
k2.metric("Annonces détectées", metrics["announcements_detected"])
k3.metric("Primary front", metrics["primary_front"])
k4.metric("Multi-cartes", metrics["multi_card_fronts"])
k5.metric("Cartes candidates", metrics["candidate_cards"])
k6.metric("Temps", f"{metrics['duration_seconds']} s")

st.caption(metrics["ocr_note"])

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

diagnostic_causes = metrics.get("diagnostic_causes") or {}
if diagnostic_causes:
    with st.expander("Diagnostic review/fail", expanded=False):
        st.dataframe(
            [{"cause": cause, "cas": count} for cause, count in sorted(diagnostic_causes.items(), key=lambda item: item[1], reverse=True)],
            width="stretch",
            hide_index=True,
        )

m1, m2, m3 = st.columns(3)
m1.metric("Reconnu", metrics["auto_recognized"])
m2.metric("À vérifier", metrics["to_review"])
m3.metric("Non reconnu", metrics["unrecognized"])

validation = {}
for group in result["groups"]:
    level = group.get("confidence_level", "red")
    chip_cls = {"green": "poc-green", "orange": "poc-orange", "red": "poc-red"}.get(level, "poc-red")
    label = {"green": "Reconnu", "orange": "À vérifier", "red": "Non reconnu"}.get(level, "Non reconnu")
    st.markdown(
        f"""
        <div class="poc-card">
          <div style="display:flex;justify-content:space-between;gap:1rem;align-items:center;flex-wrap:wrap;">
            <strong>Annonce #{group['announcement_index']}</strong>
            <span class="poc-chip {chip_cls}">{label}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    photo_entries = group.get("photos", [])
    if group.get("grouping_reasons"):
        st.caption("Grouping : " + " · ".join(group.get("grouping_reasons") or []))
    if photo_entries:
        cols = st.columns(min(4, len(photo_entries)))
        for idx, entry in enumerate(photo_entries):
            photo = entry["photo"]
            klass = entry["classification"]
            with cols[idx % len(cols)]:
                st.image(photo.path, use_container_width=True)
                st.caption(f"#{photo.capture_index} · {klass.get('class')} · {klass.get('confidence')}")
                st.caption(photo.filename)

    detail_cards = group.get("detail_cards") or []
    if detail_cards:
        st.markdown("**Sous-groupes cartes détectés**")
        for idx_detail, detail in enumerate(detail_cards, start=1):
            front = detail.get("front", {}).get("photo")
            back = detail.get("back", {}).get("photo")
            front_label = f"front #{front.capture_index}" if front else "front manquant"
            back_label = f"back #{back.capture_index}" if back else "back manquant"
            st.caption(f"Carte {idx_detail} : {front_label} · {back_label}")

    matches = group.get("matches") or []
    if matches:
        for idx, match in enumerate(matches, start=1):
            st.markdown(
                f"**Zone carte {idx} · méthode {match.get('method')} · {match.get('status')} · "
                f"score {match.get('score', 0)} · marge {match.get('margin', 0)}**"
            )
            ocr_payload = match.get("ocr") or {}
            if ocr_payload:
                st.caption(
                    "OCR nom : "
                    + " / ".join(ocr_payload.get("name_texts") or ["—"])
                    + " · OCR numéro : "
                    + " / ".join(ocr_payload.get("number_texts") or ["—"])
                )
            if match.get("diagnostic_reason"):
                st.caption("Raison : " + str(match.get("diagnostic_reason")))
            rows = []
            for candidate_row in match.get("candidates", []):
                candidate = candidate_row["candidate"]
                rows.append(
                    {
                        "score": candidate_row["score"],
                        "visuel": candidate_row.get("visual_score", ""),
                        "raisons": " · ".join(candidate_row.get("reasons") or []),
                        "nom": candidate["name"],
                        "numéro": candidate["number"],
                        "set": candidate["set"],
                        "lot": candidate["lot_name"],
                        "card_uid": candidate["card_uid"],
                        "JAP": "oui" if candidate.get("japanese") else "non",
                    }
                )
            st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.caption("Aucune correspondance proposée.")

    key = f"photo_poc_validation_{group['announcement_index']}"
    validation[group["announcement_index"]] = st.radio(
        "Validation POC",
        ["Non validé", "Correct", "Mauvais", "Choisir autre candidat"],
        key=key,
        horizontal=True,
    )

validated = [value for value in validation.values() if value != "Non validé"]
wrong_green = sum(
    1
    for group in result["groups"]
    if group.get("confidence_level") == "green" and validation.get(group["announcement_index"]) == "Mauvais"
)
if validated:
    st.markdown("### Mesure après validation manuelle")
    c1, c2, c3 = st.columns(3)
    c1.metric("Groupes validés", len(validated))
    c2.metric("Faux positifs silencieux", wrong_green)
    c3.metric("Objectif", "OK" if wrong_green == 0 else "À corriger")

"""Streamlit POC for Vinted drop photo recognition.

Run with:
    streamlit run tools/photo_recognition_poc.py

This tool is isolated from the real Drop workflow. It reads photos and JSON
datasets, but never writes to Pokestock business data.
"""

from __future__ import annotations

import sys
import hashlib
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from PIL import Image, ImageOps

from services.photo_recognition_poc_service import (
    PHOTO_ROLES,
    POC_ANALYSIS_PIPELINE_VERSION,
    POC_DIR,
    POC_GROUND_TRUTH_PATH,
    VALIDATED_GROUP_STATUSES,
    analyze_ground_truth_sample,
    analyze_sample,
    ensure_ground_truth_sample,
    list_ordered_photos,
    load_poc_ground_truth,
    load_vinted_drops,
    photo_key,
    sample_ground_truth_key,
    stable_group_id_from_photos,
    update_ground_truth_sample,
    normalize_group_status,
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
    "Synthèse complète",
    "Carte du grouping",
    "File à vérifier",
    "File non reconnus",
    "Contrôle verts",
    "Vérification complète",
    "Validation des groupes",
    "Résultats / debug reconnaissance",
    "Erreurs uniquement",
]


st.set_page_config(page_title="POC reconnaissance photos", layout="wide")

st.markdown(
    """
    <style>
    .poc-hero {
        background:#fff;border:1px solid #ddd6fe;border-left:5px solid #6d28d9;
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
    .poc-card {background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:0.7rem 0.85rem;margin:0.5rem 0;}
    .poc-muted {color:#64748b;font-size:0.82rem;}
    .poc-mini {font-size:0.76rem;color:#64748b;}
    .poc-section-title {font-size:1rem;font-weight:850;color:#111827;margin:1rem 0 0.35rem;}
    .poc-validated {color:#166534;font-weight:900;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _rerun():
    st.rerun()


def _request_view(view_name: str):
    if view_name in VIEW_OPTIONS:
        st.session_state["photo_poc_pending_view"] = view_name
    _rerun()


def _apply_pending_view():
    pending = st.session_state.pop("photo_poc_pending_view", None)
    if pending in VIEW_OPTIONS:
        st.session_state["photo_poc_view"] = pending


def _analysis_meta_for(
    *,
    folder: str,
    photos: list,
    drop_id: str | None,
    start_index: int,
    target_announcements: int,
    max_photos: int,
) -> dict:
    start_index = max(1, int(start_index or 1))
    max_photos = max(1, int(max_photos or 1))
    photo_window = photos[start_index - 1 : start_index - 1 + max_photos]
    photo_signature = hashlib.sha1(
        "|".join(
            f"{photo.capture_index}:{photo.filename}:{photo.size_bytes}"
            for photo in photo_window
        ).encode("utf-8")
    ).hexdigest()
    return {
        "pipeline_version": POC_ANALYSIS_PIPELINE_VERSION,
        "folder": str(Path(folder).resolve()),
        "drop_id": drop_id,
        "start_index": start_index,
        "target_announcements": int(target_announcements or 0),
        "max_photos": int(max_photos or 0),
        "photo_count": len(photo_window),
        "photo_signature": photo_signature,
    }


def _result_matches_analysis(result: dict | None, expected: dict) -> bool:
    if not isinstance(result, dict):
        return False
    meta = result.get("analysis_meta")
    if not isinstance(meta, dict):
        return False
    for key, value in expected.items():
        if meta.get(key) != value:
            return False
    return True


def _save_sample(sample_key: str, sample: dict):
    update_ground_truth_sample(sample_key, sample)
    st.session_state[f"photo_poc_sample_{sample_key}"] = sample
    st.toast("Ground truth POC sauvegardé")


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


def _image_crop(path: str, kind: str):
    try:
        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")
            img.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
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
    level_by_group = {}
    if result:
        for group in result.get("groups", []) or []:
            group_id = _result_group_id(group)
            level_by_group[group_id] = group.get("confidence_level")
    for group in sample.get("groups", []) or []:
        group_id = str(group.get("group_id") or "")
        level = level_by_group.get(group_id)
        for validation in (group.get("recognition_validation") or {}).values():
            status = validation.get("status")
            if not status:
                continue
            if level == "orange":
                review_fixed += 1
            elif level == "red":
                fail_fixed += 1
            elif level == "green":
                green_checked += 1
                if status == "wrong":
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


def _match_primary_candidate(match: dict) -> dict:
    return (((match.get("candidates") or [{}])[0]).get("candidate") or {})


def _ground_truth_error_rows(result: dict, sample: dict) -> list[dict]:
    rows = []
    for group in result.get("groups", []) or []:
        group_id = _result_group_id(group)
        source = _source_group(sample, group_id)
        validations = source.get("recognition_validation") or {}
        for match_index, match in enumerate(group.get("matches", []) or []):
            validation = validations.get(str(match_index)) or {}
            if validation.get("status") != "wrong":
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
    not_in_drop = 0
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
        group_not_in_drop = False
        for match_index, match in enumerate(group.get("matches", []) or []):
            match.setdefault("v10_original_status", match.get("status"))
            candidate = _match_primary_candidate(match)
            group_has_jp = group_has_jp or bool(candidate.get("japanese")) or bool(source.get("jp_physical"))
            group_has_special = group_has_special or bool(match.get("special_layout"))
            reason = str(match.get("diagnostic_reason") or "")
            if "incompatible" in reason or "absent des métadonnées" in reason or "absente" in reason:
                group_not_in_drop = True
            validation = validations.get(str(match_index)) or {}
            original_status = match.get("v10_original_status") or match.get("status")
            if original_status == "recognized" and validation.get("status"):
                checked_auto += 1
                if validation.get("status") == "correct":
                    correct_auto += 1
                elif validation.get("status") == "wrong":
                    wrong_auto += 1
            if validation.get("status") == "wrong" and original_status == "recognized":
                false_green_downgraded += 1
                match["status"] = "review"
                match["v10_safety_reason"] = "validation terrain: vert V9 faux, revue obligatoire"
                match["diagnostic_reason"] = match["v10_safety_reason"]
                group["confidence_level"] = "orange"
        if group_has_jp:
            jp_detected += 1
            if any((source.get("recognition_validation") or {}).get(str(idx), {}).get("status") == "wrong" for idx, _match in enumerate(group.get("matches", []) or [])):
                jp_wrong += 1
        if group_has_special:
            special_layout += 1
        if group_not_in_drop:
            not_in_drop += 1
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
    metrics["v10_not_in_drop_groups"] = not_in_drop
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

    vm1, vm2, vm3 = st.columns(3)
    vm1.metric("Cas visuels", metrics.get("visual_matching_cases", 0))
    vm2.metric("Visuel large", metrics.get("visual_matching_broad_cases", 0))
    vm3.metric("Temps visuel", f"{metrics.get('visual_matching_seconds', 0)} s")

    vt1, vt2, vt3, vt4 = st.columns(4)
    vt1.metric("Faux verts V9 corrigés", metrics.get("v10_false_green_downgraded", 0))
    vt2.metric("JP candidats", metrics.get("v10_jp_candidate_groups", 0))
    vt3.metric("Multi-cartes V10", metrics.get("v10_multi_card_groups", 0))
    vt4.metric("Spéciaux / LÉGENDE", metrics.get("v10_special_layout_groups", 0))

    vx1, vx2 = st.columns(2)
    vx1.metric("Recto manquant", metrics.get("v10_missing_front_groups", 0))
    vx2.metric("Probablement absent du Drop", metrics.get("v10_not_in_drop_groups", 0))

    causes = metrics.get("diagnostic_causes") or {}
    if causes:
        st.markdown("#### Causes orange/rouge")
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
            reason = match.get("v8_auto_reason")
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
        st.markdown("#### Nouveaux autos V8/V9")
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


def _render_grouping_map(result: dict):
    metrics = result.get("metrics") or {}
    st.markdown("### Carte du grouping")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Photos", metrics.get("photos_analyzed", 0))
    c2.metric("Annonces", metrics.get("announcements_detected", 0))
    c3.metric("Photos / annonce", metrics.get("photos_per_announcement", "—"))
    c4.metric("Écart ~90", metrics.get("expected_announcements_delta", "—"))
    c5.metric("Review", metrics.get("grouping_to_review", 0))

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("1 photo", metrics.get("one_photo_groups", 0))
    d2.metric("2 photos", metrics.get("two_photo_groups", 0))
    d3.metric("3 photos", metrics.get("three_photo_groups", 0))
    d4.metric("4+ photos", metrics.get("four_plus_photo_groups", 0))

    v1, v2 = st.columns(2)
    v1.metric("Fusions V11", metrics.get("v11_single_fusions", 0))
    v2.metric("Singles restants", metrics.get("one_photo_groups", 0))

    grouping_filter = st.selectbox(
        "Filtre grouping",
        ["Tous", "Groupes 1 photo", "Groupes modifiés V11", "Grouping review"],
        key="photo_poc_grouping_filter",
    )

    rows = []
    for group in result.get("groups", []) or []:
        photos = _group_photo_payloads(group)
        indexes = " ".join(f"[{photo.get('capture_index')}]" for photo in photos)
        size = len(photos)
        is_review = group.get("grouping_status") == "review"
        is_multi = int(group.get("expected_cards") or 1) > 1 or len(group.get("matches", []) or []) > 1
        is_v11 = bool(group.get("v11_single_fusion"))
        if grouping_filter == "Groupes 1 photo" and size != 1:
            continue
        if grouping_filter == "Groupes modifiés V11" and not is_v11:
            continue
        if grouping_filter == "Grouping review" and not is_review:
            continue
        if size == 1:
            state = "⚠ incomplet"
        elif is_multi:
            state = "MULTI"
        elif is_v11:
            state = "✓ fusion V11"
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
                "raison": " · ".join(group.get("grouping_reasons") or group.get("v11_single_unmerged_reason") or []),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)


def _role_caption(photo_payload: dict) -> str:
    return f"#{photo_payload.get('capture_index')} · {photo_payload.get('role', 'uncertain')}"


def _photo_path_by_key(result: dict) -> dict[str, str]:
    by_key = {}
    for photo in result.get("ordered_photos", []) or []:
        by_key[photo_key(photo)] = photo.path
    for photo in result.get("sample_photos", []) or []:
        by_key[photo_key(photo)] = photo.path
    return by_key


def _render_group_photos(group: dict, path_by_key: dict[str, str], *, compact=False):
    photos = group.get("photos", []) or []
    if not photos:
        st.caption("Aucune photo dans ce groupe.")
        return
    cols = st.columns(min(4 if compact else 5, len(photos)))
    for idx, photo_payload in enumerate(photos):
        with cols[idx % len(cols)]:
            path = path_by_key.get(photo_key(photo_payload))
            if path:
                try:
                    st.image(_thumbnail_bytes(path, 285 if compact else 320), width=190 if compact else 230)
                except Exception:
                    st.image(path, width=190 if compact else 230)
            st.caption(_role_caption(photo_payload))
            st.caption(photo_payload.get("filename", ""))


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
    return " · ".join(variants) or "FR"


def _recognition_validation(sample: dict, group_id: str, match_index: int) -> dict:
    for group in sample.get("groups", []):
        if str(group.get("group_id")) == str(group_id):
            validations = group.setdefault("recognition_validation", {})
            return validations.setdefault(str(match_index), {})
    return {}


def _set_recognition_validation(sample_key: str, group_id: str, match_index: int, payload: dict):
    sample = _load_sample(sample_key)
    for group in sample.get("groups", []) or []:
        if str(group.get("group_id")) == str(group_id):
            validations = group.setdefault("recognition_validation", {})
            validations[str(match_index)] = payload
            break
    update_ground_truth_sample(sample_key, sample)
    st.session_state[f"photo_poc_sample_{sample_key}"] = sample


def _candidate_options(candidates: list[dict]) -> dict[str, str]:
    return {
        f"{candidate.get('name')} · {candidate.get('number')} · {candidate.get('lot_name')} · {candidate.get('card_uid')}": candidate.get("drop_card_key")
        for candidate in candidates
    }


def _render_match_debug(match: dict, sample_key: str, sample: dict, group_id: str, match_index: int, candidates: list[dict]):
    ocr_payload = match.get("ocr") or {}
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
            name_crop = _image_crop(photo.path, "name")
            number_crop = _image_crop(photo.path, "number")
            card_crop = _image_crop(photo.path, "card")
            artwork_crop = _image_crop(photo.path, "artwork")
            if name_crop:
                crop_cols[0].image(name_crop, caption="crop nom", use_container_width=True)
            if number_crop:
                crop_cols[1].image(number_crop, caption="crop numéro", use_container_width=True)
            if card_crop:
                crop_cols[2].image(card_crop, caption="carte", use_container_width=True)
            if artwork_crop:
                st.image(artwork_crop, caption="crop artwork", width=320)

    validation = _recognition_validation(sample, group_id, match_index)
    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("✓ Correct", key=f"rec_ok_{group_id}_{match_index}"):
        _set_recognition_validation(sample_key, group_id, match_index, {"status": "correct"})
        _rerun()
    if c2.button("✕ Mauvais", key=f"rec_bad_{group_id}_{match_index}"):
        _set_recognition_validation(sample_key, group_id, match_index, {"status": "wrong"})
        _rerun()
    candidate_options = _candidate_options(candidates)
    selected = c3.selectbox(
        "Choisir une autre carte",
        [""] + list(candidate_options.keys()),
        key=f"rec_choose_{group_id}_{match_index}",
        label_visibility="collapsed",
    )
    if selected and st.button("Enregistrer ce choix", key=f"rec_choose_save_{group_id}_{match_index}"):
        _set_recognition_validation(
            sample_key,
            group_id,
            match_index,
            {"status": "manual_choice", "drop_card_key": candidate_options[selected], "label": selected},
        )
        _rerun()

    if validation:
        st.caption("Validation POC : " + str(validation))


def _render_match_readonly(match: dict, match_index: int):
    ocr_payload = match.get("ocr") or {}
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
            name_crop = _image_crop(photo.path, "name")
            number_crop = _image_crop(photo.path, "number")
            card_crop = _image_crop(photo.path, "card")
            artwork_crop = _image_crop(photo.path, "artwork")
            if name_crop:
                crop_cols[0].image(name_crop, caption="crop nom", use_container_width=True)
            if number_crop:
                crop_cols[1].image(number_crop, caption="crop numéro", use_container_width=True)
            if card_crop:
                crop_cols[2].image(card_crop, caption="carte", use_container_width=True)
            if artwork_crop:
                st.image(artwork_crop, caption="crop artwork", width=320)


def _render_full_check_match(match: dict, match_index: int):
    ocr_payload = match.get("ocr") or {}
    candidate_rows = (match.get("candidates") or [])[:3]
    primary_row = candidate_rows[0] if candidate_rows else {}
    primary = primary_row.get("candidate") or {}

    st.markdown(
        f"**Zone carte {match_index + 1} · {match.get('method')} · {match.get('status')}**"
    )
    if primary:
        card_cols = st.columns([0.9, 1.4])
        with card_cols[0]:
            if primary.get("image_url"):
                st.image(primary.get("image_url"), width=260)
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

    with st.expander("Voir les autres candidats / debug", expanded=False):
        st.caption(
            "OCR nom : "
            + " / ".join(ocr_payload.get("name_texts") or ["—"])
            + " · OCR numéro : "
            + " / ".join(ocr_payload.get("number_texts") or ["—"])
        )
        if ocr_payload.get("all_number_texts"):
            st.caption("Numéros debug tous crops : " + " / ".join(ocr_payload.get("all_number_texts") or []))
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
        if photo:
            crop_cols = st.columns(3)
            name_crop = _image_crop(photo.path, "name")
            number_crop = _image_crop(photo.path, "number")
            card_crop = _image_crop(photo.path, "card")
            artwork_crop = _image_crop(photo.path, "artwork")
            if name_crop:
                crop_cols[0].image(name_crop, caption="crop nom", width=220)
            if number_crop:
                crop_cols[1].image(number_crop, caption="crop numéro", width=220)
            if card_crop:
                crop_cols[2].image(card_crop, caption="carte", width=220)
            if artwork_crop:
                st.image(artwork_crop, caption="crop artwork", width=260)


def _recognition_is_done(sample: dict, group_id: str, match_count: int) -> bool:
    source = _source_group(sample, group_id)
    validations = source.get("recognition_validation") or {}
    total = max(1, match_count)
    done_statuses = {"correct", "wrong", "manual_choice", "non_recognized", "unrecognized_manual"}
    return all((validations.get(str(index)) or {}).get("status") in done_statuses for index in range(total))


def _pending_groups(result: dict, sample: dict, levels: set[str]) -> list[dict]:
    pending = []
    for group in result.get("groups", []) or []:
        if group.get("confidence_level") not in levels:
            continue
        group_id = _result_group_id(group)
        if _recognition_is_done(sample, group_id, len(group.get("matches", []) or [])):
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
            _set_recognition_validation(sample_key, group_id, 0, {"status": "non_recognized"})
            _rerun()
        return

    candidates = result.get("candidates", [])
    for match_index, match in enumerate(matches):
        validation = _recognition_validation(sample, group_id, match_index)
        if validation.get("status"):
            st.caption(f"Zone {match_index + 1} déjà traitée : {validation}")
            continue
        _render_match_readonly(match, match_index)
        action_cols = st.columns([1, 1.15, 1.2, 1])
        if allow_good_card and action_cols[0].button("✓ Bonne carte", key=f"queue_ok_{queue_key}_{group_id}_{match_index}"):
            _set_recognition_validation(sample_key, group_id, match_index, {"status": "correct"})
            _rerun()
        if action_cols[1].button("Non reconnu", key=f"queue_fail_{queue_key}_{group_id}_{match_index}"):
            _set_recognition_validation(sample_key, group_id, match_index, {"status": "non_recognized"})
            _rerun()
        if action_cols[2].button("Corriger le groupe", key=f"queue_fix_{queue_key}_{group_id}_{match_index}"):
            _request_view("Validation des groupes")
        if action_cols[3].button("Passer", key=f"queue_skip_{queue_key}_{group_id}_{match_index}"):
            st.session_state[index_key] = (current_index + 1) % max(1, len(groups))
            _rerun()

        selected, drop_card_key = _queue_candidate_selector(candidates, f"queue_choose_{queue_key}_{group_id}_{match_index}")
        if selected and st.button("Valider ce choix", key=f"queue_choose_save_{queue_key}_{group_id}_{match_index}", type="primary"):
            _set_recognition_validation(
                sample_key,
                group_id,
                match_index,
                {"status": "manual_choice", "drop_card_key": drop_card_key, "label": selected},
            )
            _rerun()


def _green_quality_groups(result: dict, sample: dict, target_count: int = 10) -> list[dict]:
    green_groups = [group for group in result.get("groups", []) or [] if group.get("confidence_level") == "green"]
    green_groups = [
        group
        for group in green_groups
        if not _recognition_is_done(sample, _result_group_id(group), len(group.get("matches", []) or []))
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
        validation = _recognition_validation(sample, group_id, match_index)
        if validation.get("status"):
            st.caption(f"Zone {match_index + 1} déjà contrôlée : {validation}")
            continue
        _render_match_readonly(match, match_index)
        c1, c2, c3 = st.columns(3)
        if c1.button("✓ Correct", key=f"green_ok_{group_id}_{match_index}", type="primary"):
            _set_recognition_validation(sample_key, group_id, match_index, {"status": "correct"})
            _rerun()
        if c2.button("✕ Mauvais", key=f"green_bad_{group_id}_{match_index}"):
            _set_recognition_validation(sample_key, group_id, match_index, {"status": "wrong"})
            _rerun()
        if c3.button("Passer", key=f"green_skip_{group_id}_{match_index}"):
            st.session_state[index_key] = (current_index + 1) % max(1, len(groups))
            _rerun()


def _render_full_check_view(sample_key: str, sample: dict, result: dict):
    groups = result.get("groups", []) or []
    if not groups:
        st.info("Aucune annonce à vérifier.")
        return
    index_key = "photo_poc_full_check_index"
    st.session_state[index_key] = min(int(st.session_state.get(index_key, 0) or 0), len(groups) - 1)
    current_index = st.session_state[index_key]
    group = groups[current_index]
    group_id = _result_group_id(group)
    level = group.get("confidence_level", "red")
    path_by_key = _photo_path_by_key(result)

    st.markdown(f"### Vérification complète — {current_index + 1} / {len(groups)}")
    st.caption(
        f"Annonce #{group.get('announcement_index')} · {STATUS_LABELS.get(level, level)} · "
        f"grouping {group.get('grouping_status')} · {group.get('expected_cards', 1)} carte(s)"
    )
    _render_group_photos({"photos": _group_photo_payloads(group)}, path_by_key, compact=True)
    for match_index, match in enumerate(group.get("matches", []) or []):
        _render_full_check_match(match, match_index)
        validation = _recognition_validation(sample, group_id, match_index)
        if validation.get("status"):
            st.caption("Validation POC : " + str(validation))
        c1, c2, c3 = st.columns(3)
        if c1.button("✓ Correct", key=f"full_ok_{group_id}_{match_index}", type="primary"):
            _set_recognition_validation(sample_key, group_id, match_index, {"status": "correct"})
            st.session_state[index_key] = min(current_index + 1, len(groups) - 1)
            _rerun()
        if c2.button("✕ Mauvais", key=f"full_bad_{group_id}_{match_index}"):
            _set_recognition_validation(sample_key, group_id, match_index, {"status": "wrong"})
            st.session_state[index_key] = min(current_index + 1, len(groups) - 1)
            _rerun()
        if c3.button("Suivant", key=f"full_next_{group_id}_{match_index}"):
            st.session_state[index_key] = min(current_index + 1, len(groups) - 1)
            _rerun()
    nav1, nav2 = st.columns(2)
    if nav1.button("← Précédente", key="full_prev", disabled=current_index == 0):
        st.session_state[index_key] = max(0, current_index - 1)
        _rerun()
    if nav2.button("Suivante →", key="full_next_bottom", disabled=current_index >= len(groups) - 1):
        st.session_state[index_key] = min(len(groups) - 1, current_index + 1)
        _rerun()


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
        return bool(group.get("jp_physical")) or any(
            ((entry.get("classification") or {}).get("back_type") == "japanese") for entry in group.get("photos", [])
        )
    if mode == "Multi-cartes":
        return int(group.get("expected_cards") or 1) > 1 or len(group.get("matches", []) or []) > 1
    if mode == "Erreurs uniquement":
        return level != "green" or group.get("grouping_status") == "review"
    return True


def _render_results_view(sample_key: str, sample: dict, auto_result: dict, drop_id: str | None, folder: str):
    st.markdown("### Résultats / debug reconnaissance")
    only_validated = st.checkbox("Reconnaître uniquement les groupes validés", value=True)
    if only_validated:
        if not any(normalize_group_status(group.get("status")) in VALIDATED_GROUP_STATUSES for group in sample.get("groups", [])):
            st.warning("Aucun groupe validé pour l'instant. Valide d'abord des groupes dans la vue dédiée.")
            return auto_result
        with st.spinner("Reconnaissance sur ground truth validé..."):
            result = analyze_ground_truth_sample(sample, folder=folder, drop_id=drop_id, only_validated=True)
    else:
        result = auto_result

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
        source_group = _source_group(sample, group_id)
        validations = source_group.get("recognition_validation") or {}
        for match_index, match in enumerate(group.get("matches", []) or []):
            validation = validations.get(str(match_index)) or {}
            if validation.get("status"):
                validated_matches += 1
            if match.get("status") == "recognized" and validation.get("status") == "wrong":
                wrong_auto += 1
            if validation.get("status") == "manual_choice":
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


def _render_errors_view(sample_key: str, sample: dict, auto_result: dict, drop_id: str | None, folder: str):
    st.markdown("### Erreurs uniquement")
    result = (
        analyze_ground_truth_sample(sample, folder=folder, drop_id=drop_id, only_validated=True)
        if any(normalize_group_status(group.get("status")) in VALIDATED_GROUP_STATUSES for group in sample.get("groups", []))
        else auto_result
    )
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


st.markdown(
    """
    <div class="poc-hero">
      <h1>POC reconnaissance automatique des photos</h1>
      <p>Lecture seule : aucune modification de data.json, vinted_drops.json ou des photos originales.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

_apply_pending_view()

with st.sidebar:
    st.subheader("Échantillon")
    folder = st.text_input("Dossier photos", value=str(POC_DIR))
    photos = list_ordered_photos(folder)
    st.caption(f"{len(photos)} photo(s) détectée(s)")
    drops_data = load_vinted_drops()
    drops = drops_data.get("drops", []) or []
    drop_options = {f"{drop.get('name', 'Drop sans nom')} · {len(drop.get('cards', []) or [])} cartes": drop.get("id") for drop in drops}
    selected_drop_label = st.selectbox("Drop candidat", list(drop_options) or ["Aucun drop"], disabled=not bool(drop_options))
    selected_drop_id = drop_options.get(selected_drop_label)
    start_index = st.number_input("capture_index de départ", min_value=1, max_value=max(1, len(photos)), value=1, step=1)
    target_announcements = st.number_input("annonces visées", min_value=5, max_value=35, value=30, step=1)
    max_photos = st.number_input("photos max à analyser", min_value=10, max_value=max(10, len(photos)), value=min(75, max(10, len(photos))), step=5)
    view_default = st.session_state.get("photo_poc_view", "Synthèse complète")
    view_radio_kwargs = {"key": "photo_poc_view"}
    if "photo_poc_view" not in st.session_state:
        view_radio_kwargs["index"] = VIEW_OPTIONS.index(view_default) if view_default in VIEW_OPTIONS else 0
    view = st.radio("Vue", VIEW_OPTIONS, **view_radio_kwargs)
    run = st.button("Analyser l'échantillon", type="primary")
    run_all = st.button("Analyser toutes les photos")

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
            for photo in photos[: min(len(photos), 188)]
        ],
        width="stretch",
        hide_index=True,
    )

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

if bool(st.session_state.get("photo_poc_full_analysis")) and not run:
    expected_meta = _analysis_meta_for(
        folder=folder,
        photos=photos,
        drop_id=selected_drop_id,
        start_index=1,
        max_photos=len(photos),
        target_announcements=len(photos),
    )
else:
    expected_meta = _analysis_meta_for(
        folder=folder,
        photos=photos,
        drop_id=selected_drop_id,
        start_index=analysis_start_index,
        max_photos=analysis_max_photos,
        target_announcements=analysis_target_announcements,
    )

if not (run or run_all) and "photo_poc_result" in st.session_state:
    if not _result_matches_analysis(st.session_state.get("photo_poc_result"), expected_meta):
        st.session_state.pop("photo_poc_result", None)
        st.session_state.pop("photo_poc_sample_key", None)
        st.session_state.pop("photo_poc_full_analysis", None)
        st.info("Résultat d'analyse POC obsolète ignoré. Relance l'analyse pour utiliser le pipeline V9 actuel.")

if not (run or run_all) and "photo_poc_result" not in st.session_state:
    st.info("Choisis un bloc consécutif puis lance l'analyse. Par défaut, le POC ne traite pas tout le dossier.")
    st.stop()

if run or run_all:
    label = "Analyse complète des photos..." if run_all else "Analyse locale de l'échantillon..."
    progress = st.progress(0, text=f"Photos : 0 / {analysis_max_photos} · Annonces détectées : 0")
    with st.spinner(label):
        st.session_state["photo_poc_result"] = analyze_sample(
            folder=folder,
            drop_id=selected_drop_id,
            start_index=analysis_start_index,
            target_announcements=analysis_target_announcements,
            max_photos=analysis_max_photos,
        )
        st.session_state["photo_poc_sample_key"] = analysis_sample_key
        st.session_state["photo_poc_full_analysis"] = bool(run_all)
        done_metrics = st.session_state["photo_poc_result"].get("metrics") or {}
        progress.progress(
            1.0,
            text=f"Photos : {done_metrics.get('photos_analyzed', analysis_max_photos)} / {analysis_max_photos} · "
            f"Annonces détectées : {done_metrics.get('announcements_detected', 0)} · Reconnaissance terminée",
        )
    if run_all:
        done_metrics = st.session_state["photo_poc_result"].get("metrics") or {}
        if done_metrics.get("to_review", 0):
            st.session_state["photo_poc_pending_view"] = "File à vérifier"
        elif done_metrics.get("unrecognized", 0):
            st.session_state["photo_poc_pending_view"] = "File non reconnus"
        else:
            st.session_state["photo_poc_pending_view"] = "Synthèse complète"
        _rerun()

result = st.session_state["photo_poc_result"]
sample_key = st.session_state["photo_poc_sample_key"]
ground_truth = ensure_ground_truth_sample(result, sample_key)
if sample_key in (ground_truth.get("samples") or {}):
    st.session_state[f"photo_poc_sample_{sample_key}"] = ground_truth["samples"][sample_key]
sample = _load_sample(sample_key)
_apply_v10_ground_truth_overlay(result, sample)
metrics = result["metrics"]
drop = result.get("drop") or {}

st.markdown(f"### Drop candidat : {drop.get('name', 'Non défini')}")
st.caption(f"Ground truth POC : {POC_GROUND_TRUTH_PATH}")
st.caption(metrics["ocr_note"])

if view == "Synthèse complète":
    _render_full_summary(result, sample)
elif view == "Carte du grouping":
    _render_grouping_map(result)
elif view == "File à vérifier":
    _render_queue_view(
        sample_key,
        sample,
        result,
        levels={"orange"},
        title="À vérifier",
        queue_key="review",
        allow_good_card=True,
    )
elif view == "File non reconnus":
    _render_queue_view(
        sample_key,
        sample,
        result,
        levels={"red"},
        title="Non reconnus",
        queue_key="fail",
        allow_good_card=False,
    )
elif view == "Contrôle verts":
    _render_green_quality_view(sample_key, sample, result)
elif view == "Vérification complète":
    _render_full_check_view(sample_key, sample, result)
elif view == "Validation des groupes":
    _render_metrics(metrics)
    _render_validation_view(sample_key, sample, result)
elif view == "Résultats / debug reconnaissance":
    _render_results_view(sample_key, sample, result, selected_drop_id, folder)
else:
    _render_errors_view(sample_key, sample, result, selected_drop_id, folder)

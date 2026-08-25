"""Streamlit POC for Vinted drop photo recognition.

Run with:
    streamlit run tools/photo_recognition_poc.py

This tool is isolated from the real Drop workflow. It reads photos and JSON
datasets, but never writes to Pokestock business data.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from PIL import Image, ImageOps

from services.photo_recognition_poc_service import (
    PHOTO_ROLES,
    POC_DIR,
    POC_GROUND_TRUTH_PATH,
    analyze_ground_truth_sample,
    analyze_sample,
    ensure_ground_truth_sample,
    list_ordered_photos,
    load_poc_ground_truth,
    load_vinted_drops,
    photo_key,
    sample_ground_truth_key,
    update_ground_truth_sample,
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
    .poc-card {background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:0.85rem;margin:0.55rem 0;}
    .poc-muted {color:#64748b;font-size:0.82rem;}
    .poc-mini {font-size:0.76rem;color:#64748b;}
    .poc-section-title {font-size:1rem;font-weight:850;color:#111827;margin:1rem 0 0.35rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _rerun():
    st.rerun()


def _save_sample(sample_key: str, sample: dict):
    update_ground_truth_sample(sample_key, sample)
    st.toast("Ground truth POC sauvegardé")


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
            return img
    except Exception:
        return None


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
    cols = st.columns(min(5 if compact else 6, len(photos)))
    for idx, photo_payload in enumerate(photos):
        with cols[idx % len(cols)]:
            path = path_by_key.get(photo_key(photo_payload))
            if path:
                st.image(path, use_container_width=True)
            st.caption(_role_caption(photo_payload))
            st.caption(photo_payload.get("filename", ""))


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
    validated = sum(1 for group in groups if group.get("status") in {"correct", "corrected"})
    corrected = sum(1 for group in groups if group.get("status") == "corrected")
    v1.metric("Groupes POC", total)
    v2.metric("Validés", validated)
    v3.metric("Corrigés", corrected)
    v4.metric("Progression", f"{round(validated / max(1, total) * 100, 1)} %")

    if st.button("✓ Marquer tous les groupes non corrigés comme corrects", type="secondary"):
        for group in groups:
            if group.get("status") == "unvalidated":
                group["status"] = "correct"
        _save_sample(sample_key, sample)
        _rerun()

    for group_index, group in enumerate(groups):
        status = group.get("status", "unvalidated")
        badge_class = "poc-green" if status == "correct" else "poc-orange" if status == "corrected" else "poc-red"
        st.markdown(
            f"""
            <div class="poc-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:center;flex-wrap:wrap;">
                <strong>Groupe #{group_index + 1}</strong>
                <span class="poc-chip {badge_class}">{status}</span>
              </div>
              <div class="poc-mini">auto: {group.get('auto_grouping_status', 'n/a')} · cartes attendues: {group.get('expected_cards', 1)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_group_photos(group, path_by_key, compact=True)

        c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
        if c1.button("✓ Groupe correct", key=f"gt_correct_{group_index}"):
            group["status"] = "correct"
            _save_sample(sample_key, sample)
            _rerun()
        if c2.button("Fusion précédent", key=f"gt_merge_prev_{group_index}", disabled=group_index == 0):
            _merge_group(sample, group_index, -1)
            _save_sample(sample_key, sample)
            _rerun()
        if c3.button("Fusion suivant", key=f"gt_merge_next_{group_index}", disabled=group_index >= len(groups) - 1):
            _merge_group(sample, group_index, 1)
            _save_sample(sample_key, sample)
            _rerun()

        with st.expander("Corriger", expanded=status != "correct"):
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

            group["status"] = st.selectbox(
                "Statut validation",
                ["unvalidated", "correct", "corrected"],
                index=["unvalidated", "correct", "corrected"].index(group.get("status", "unvalidated")),
                key=f"gt_status_{group_index}",
            )
            if st.button("Enregistrer corrections", key=f"gt_save_{group_index}", type="primary"):
                if group["status"] == "unvalidated":
                    group["status"] = "corrected"
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


def _recognition_validation(sample: dict, group_id: str, match_index: int) -> dict:
    for group in sample.get("groups", []):
        if str(group.get("group_id")) == str(group_id):
            validations = group.setdefault("recognition_validation", {})
            return validations.setdefault(str(match_index), {})
    return {}


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
            if name_crop:
                crop_cols[0].image(name_crop, caption="crop nom", use_container_width=True)
            if number_crop:
                crop_cols[1].image(number_crop, caption="crop numéro", use_container_width=True)
            if card_crop:
                crop_cols[2].image(card_crop, caption="carte", use_container_width=True)

    validation = _recognition_validation(sample, group_id, match_index)
    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("✓ Correct", key=f"rec_ok_{group_id}_{match_index}"):
        validation.update({"status": "correct"})
        _save_sample(sample_key, sample)
        _rerun()
    if c2.button("✕ Mauvais", key=f"rec_bad_{group_id}_{match_index}"):
        validation.update({"status": "wrong"})
        _save_sample(sample_key, sample)
        _rerun()
    candidate_options = {
        f"{candidate.get('name')} · {candidate.get('number')} · {candidate.get('lot_name')} · {candidate.get('card_uid')}": candidate.get("drop_card_key")
        for candidate in candidates
    }
    selected = c3.selectbox(
        "Choisir une autre carte",
        [""] + list(candidate_options.keys()),
        key=f"rec_choose_{group_id}_{match_index}",
        label_visibility="collapsed",
    )
    if selected and st.button("Enregistrer ce choix", key=f"rec_choose_save_{group_id}_{match_index}"):
        validation.update({"status": "manual_choice", "drop_card_key": candidate_options[selected], "label": selected})
        _save_sample(sample_key, sample)
        _rerun()

    if validation:
        st.caption("Validation POC : " + str(validation))


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
        if not any(group.get("status") in {"correct", "corrected"} for group in sample.get("groups", [])):
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
        group_id = str(group.get("ground_truth_group_id") or group.get("announcement_index"))
        source_group = next((item for item in sample.get("groups", []) if str(item.get("group_id")) == group_id), {})
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
            {
                "photos": [
                    {
                        "filename": entry["photo"].filename,
                        "capture_index": entry["photo"].capture_index,
                        "role": entry.get("ground_truth_role") or entry.get("classification", {}).get("class", "photo"),
                    }
                    for entry in group.get("photos", [])
                ]
            },
            path_by_key,
        )
        if group.get("grouping_reasons"):
            st.caption("Grouping : " + " · ".join(group.get("grouping_reasons") or []))
        group_id = str(group.get("ground_truth_group_id") or group.get("announcement_index"))
        for match_index, match in enumerate(group.get("matches", []) or []):
            _render_match_debug(match, sample_key, sample, group_id, match_index, result.get("candidates", []))
    return result


def _render_errors_view(sample_key: str, sample: dict, auto_result: dict, drop_id: str | None, folder: str):
    st.markdown("### Erreurs uniquement")
    result = analyze_ground_truth_sample(sample, folder=folder, drop_id=drop_id, only_validated=True) if any(
        group.get("status") in {"correct", "corrected"} for group in sample.get("groups", [])
    ) else auto_result
    path_by_key = _photo_path_by_key(result)
    candidates = result.get("candidates", [])
    count = 0
    for group in result.get("groups", []):
        if group.get("confidence_level") == "green" and group.get("grouping_status") != "review":
            continue
        count += 1
        st.markdown(f"#### Annonce #{group.get('announcement_index')} · {STATUS_LABELS.get(group.get('confidence_level'), '🔴 Non reconnu')}")
        _render_group_photos(
            {
                "photos": [
                    {
                        "filename": entry["photo"].filename,
                        "capture_index": entry["photo"].capture_index,
                        "role": entry.get("ground_truth_role") or entry.get("classification", {}).get("class", "photo"),
                    }
                    for entry in group.get("photos", [])
                ]
            },
            path_by_key,
            compact=True,
        )
        group_id = str(group.get("ground_truth_group_id") or group.get("announcement_index"))
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
    max_photos = st.number_input("photos max à analyser", min_value=10, max_value=188, value=75, step=5)
    view = st.radio("Vue", ["Validation des groupes", "Résultats / debug reconnaissance", "Erreurs uniquement"], index=0)
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

if not run and ("photo_poc_result" not in st.session_state or st.session_state.get("photo_poc_sample_key") != sample_key):
    st.info("Choisis un bloc consécutif puis lance l'analyse. Par défaut, le POC ne traite pas tout le dossier.")
    st.stop()

if run:
    with st.spinner("Analyse locale de l'échantillon..."):
        st.session_state["photo_poc_result"] = analyze_sample(
            folder=folder,
            drop_id=selected_drop_id,
            start_index=start_index,
            target_announcements=target_announcements,
            max_photos=max_photos,
        )
        st.session_state["photo_poc_sample_key"] = sample_key

result = st.session_state["photo_poc_result"]
ensure_ground_truth_sample(result, sample_key)
ground_truth = load_poc_ground_truth()
sample = ground_truth.get("samples", {}).get(sample_key, {"groups": []})
metrics = result["metrics"]
drop = result.get("drop") or {}

st.markdown(f"### Drop candidat : {drop.get('name', 'Non défini')}")
st.caption(f"Ground truth POC : {POC_GROUND_TRUTH_PATH}")
st.caption(metrics["ocr_note"])

if view == "Validation des groupes":
    _render_metrics(metrics)
    _render_validation_view(sample_key, sample, result)
elif view == "Résultats / debug reconnaissance":
    _render_results_view(sample_key, sample, result, selected_drop_id, folder)
else:
    _render_errors_view(sample_key, sample, result, selected_drop_id, folder)

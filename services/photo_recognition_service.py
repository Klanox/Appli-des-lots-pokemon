"""Production facade for the shared photo-recognition engine.

The recognition algorithms continue to live in the proven POC engine.  This
module adds the small, business-safe layer needed by the Drop workflow:
persistent review state, manual candidate corrections and the Step 4 payload.
Heavy results stay in the existing local pickle cache; business JSON files are
only mutated by explicit callers.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import unicodedata
from typing import Any, Iterable

from services import photo_recognition_poc_service as engine
from services.vinted_drops_service import drop_card_key, drop_item_status, find_drop


PRODUCTION_SESSION_VERSION = "v1"
PRODUCTION_CACHE_DIR = Path(".cache") / "photo_recognition" / "drop_sessions"
SUPPORTED_EXTENSIONS = engine.SUPPORTED_EXTENSIONS

# Public engine API shared by the POC and the production workflow.
PHOTO_ROLES = engine.PHOTO_ROLES
POC_ANALYSIS_PIPELINE_VERSION = engine.POC_ANALYSIS_PIPELINE_VERSION
POC_MATCHING_REFRESH_VERSION = engine.POC_MATCHING_REFRESH_VERSION
PROPOSAL_RELIABILITY_VERSION = engine.PROPOSAL_RELIABILITY_VERSION
LANGUAGE_COMPATIBILITY_VERSION = engine.LANGUAGE_COMPATIBILITY_VERSION
POC_DIR = engine.POC_DIR
POC_GROUND_TRUTH_PATH = engine.POC_GROUND_TRUTH_PATH
VALIDATED_GROUP_STATUSES = engine.VALIDATED_GROUP_STATUSES
PhotoInfo = engine.PhotoInfo
active_drop_candidates = engine.active_drop_candidates
analyze_sample = engine.analyze_sample
candidate_identity = engine.candidate_identity
candidate_identity_key = engine.candidate_identity_key
candidate_set_signature = engine.candidate_set_signature
ensure_ground_truth_sample = engine.ensure_ground_truth_sample
list_ordered_photos = engine.list_ordered_photos
load_cached_analysis_result = engine.load_cached_analysis_result
load_latest_cached_analysis_result = engine.load_latest_cached_analysis_result
load_poc_ground_truth = engine.load_poc_ground_truth
load_vinted_drops = engine.load_vinted_drops
normalize_group_status = engine.normalize_group_status
photo_identity = engine.photo_identity
normalize_photo_identity = engine.normalize_photo_identity
photo_key = engine.photo_key
photo_window_signature = engine.photo_window_signature
refresh_result_candidates = engine.refresh_result_candidates
proposed_candidate = engine.proposed_candidate
sample_ground_truth_key = engine.sample_ground_truth_key
stable_group_id_from_photos = engine.stable_group_id_from_photos
update_ground_truth_sample = engine.update_ground_truth_sample


def _safe_int(value: Any, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fold_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _session_path(drop_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(drop_id or "unknown"))
    return PRODUCTION_CACHE_DIR / f"{safe_id}.json"


def load_drop_photo_session(drop_id: str) -> dict[str, Any]:
    path = _session_path(drop_id)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        payload = {}
    if payload.get("version") != PRODUCTION_SESSION_VERSION:
        payload = {}
    return {
        "version": PRODUCTION_SESSION_VERSION,
        "drop_id": str(drop_id or ""),
        "folder": str(payload.get("folder") or ""),
        "photo_signature": str(payload.get("photo_signature") or ""),
        "pipeline_version": str(payload.get("pipeline_version") or ""),
        "candidate_signature": str(payload.get("candidate_signature") or ""),
        "proposal_reliability_version": str(payload.get("proposal_reliability_version") or ""),
        "language_compatibility_version": str(payload.get("language_compatibility_version") or ""),
        "updated_at": str(payload.get("updated_at") or ""),
        "validations": dict(payload.get("validations") or {}),
        "grouping_confirmations": dict(payload.get("grouping_confirmations") or {}),
        "poc_validation_reconciliation": dict(payload.get("poc_validation_reconciliation") or {}),
    }


def save_drop_photo_session(session: dict[str, Any]) -> dict[str, Any]:
    payload = dict(session or {})
    payload["version"] = PRODUCTION_SESSION_VERSION
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = _session_path(str(payload.get("drop_id") or ""))
    _atomic_json_write(path, payload)
    return payload


def _group_photo_payload(group: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for entry in group.get("photos", []) or []:
        photo = entry.get("photo") if isinstance(entry, dict) else entry
        if photo is not None:
            rows.append(normalize_photo_identity(photo))
    return rows


def stable_group_id(group: dict[str, Any]) -> str:
    ground_truth_id = str(group.get("ground_truth_group_id") or "").strip()
    if ground_truth_id:
        return ground_truth_id
    return stable_group_id_from_photos(_group_photo_payload(group))


def stable_subcard_id(match: dict[str, Any], match_index=0) -> str:
    current = str(match.get("subcard_id") or "").strip()
    if current:
        return current
    photos = match.get("subcard_photos") or {}
    physical = f"front={photos.get('front', '')}|back={photos.get('back', '')}"
    if physical != "front=|back=":
        return "subcard_" + hashlib.sha1(physical.encode("utf-8")).hexdigest()[:16]
    photo = match.get("photo")
    if photo is not None:
        return "subcard_" + hashlib.sha1(photo_key(photo).encode("utf-8")).hexdigest()[:16]
    return f"legacy_subcard_{int(match_index)}"


def current_candidate(match: dict[str, Any] | None) -> dict[str, Any] | None:
    return proposed_candidate(match)


def semantic_candidate_key(candidate: dict[str, Any] | None) -> str:
    return candidate_identity_key(candidate) if candidate else ""


def _current_status(match: dict[str, Any]) -> str:
    if match.get("v13_not_in_drop_confidence") in {"strong", "possible"}:
        return "not_in_drop"
    status = str(match.get("status") or "fail")
    return status if status in {"recognized", "review", "fail"} else "fail"


def proposal_signature(match: dict[str, Any], candidate: dict[str, Any] | None = None) -> str:
    candidate = current_candidate(match) if candidate is None else candidate
    payload = {
        "candidate_key": semantic_candidate_key(candidate),
        "status": _current_status(match),
        "variant": {
            "japanese": bool((candidate or {}).get("japanese")),
            "reverse": bool((candidate or {}).get("reverse")),
            "stamp": str((candidate or {}).get("stamp") or ""),
            "promo": bool((candidate or {}).get("promo")),
        },
    }
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def initialize_drop_photo_session(
    drop_id: str,
    folder: str | Path,
    result: dict[str, Any],
) -> dict[str, Any]:
    session = load_drop_photo_session(drop_id)
    meta = result.get("analysis_meta") or {}
    session.update(
        {
            "drop_id": str(drop_id or ""),
            "folder": str(Path(folder).resolve()),
            "photo_signature": str(meta.get("photo_signature") or ""),
            "pipeline_version": str(meta.get("pipeline_version") or POC_ANALYSIS_PIPELINE_VERSION),
            "candidate_signature": str(meta.get("candidate_signature") or ""),
            "proposal_reliability_version": str(
                meta.get("proposal_reliability_version") or PROPOSAL_RELIABILITY_VERSION
            ),
            "language_compatibility_version": str(
                meta.get("language_compatibility_version") or LANGUAGE_COMPATIBILITY_VERSION
            ),
        }
    )
    return save_drop_photo_session(session)


def _poc_variant_label(candidate: dict[str, Any]) -> str:
    variants = []
    if candidate.get("japanese") or candidate.get("is_japanese") or candidate.get("lang") == "ja":
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


def _poc_semantic_proposal(match: dict[str, Any]) -> dict[str, Any]:
    candidate = current_candidate(match) or {}
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
        "japanese": bool(candidate.get("japanese") or candidate.get("is_japanese") or candidate.get("lang") == "ja"),
        "variant": _poc_variant_label(candidate),
    }


def _same_physical_subcard(validation: dict[str, Any], match: dict[str, Any]) -> bool:
    stored = validation.get("subcard_photos") or {}
    current = match.get("subcard_photos") or {}
    stored_front = str(stored.get("front") or "")
    current_front = str(current.get("front") or "")
    if not stored_front or stored_front != current_front:
        return False
    stored_back = str(stored.get("back") or "")
    current_back = str(current.get("back") or "")
    return not stored_back or not current_back or stored_back == current_back


def _poc_validation_for_match(
    ground_group: dict[str, Any],
    match: dict[str, Any],
    match_index: int,
) -> dict[str, Any]:
    validations = ground_group.get("recognition_validation") or {}
    subcard_id = stable_subcard_id(match, match_index)
    direct = validations.get(subcard_id)
    if isinstance(direct, dict):
        return direct
    physical = next(
        (
            validation
            for validation in validations.values()
            if isinstance(validation, dict) and _same_physical_subcard(validation, match)
        ),
        None,
    )
    if isinstance(physical, dict):
        return physical
    legacy = validations.get(str(match_index))
    if not isinstance(legacy, dict):
        return {}
    if len(ground_group.get("semantic_subcard_ids") or []) > 1 and not _same_physical_subcard(legacy, match):
        return {}
    return legacy


def reconcile_poc_validations(
    result: dict[str, Any],
    session: dict[str, Any],
    *,
    folder: str | Path,
    drop_id: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Import only physically and semantically compatible POC judgements."""
    meta = result.get("analysis_meta") or {}
    sample_key = sample_ground_truth_key(
        folder=folder,
        drop_id=drop_id,
        start_index=_safe_int(meta.get("start_index"), 1),
        max_photos=_safe_int(meta.get("max_photos"), len(result.get("sample_photos") or [])),
        target_announcements=_safe_int(meta.get("target_announcements"), len(result.get("sample_photos") or [])),
    )
    sample = (load_poc_ground_truth().get("samples") or {}).get(sample_key) or {}
    ground_groups = {
        str(group.get("group_id") or ""): group
        for group in sample.get("groups", []) or []
    }
    metrics = {"compatible": 0, "imported": 0, "stale": 0, "already_present": 0}
    validations = session.setdefault("validations", {})
    changed = False
    for group in result.get("groups", []) or []:
        group_id = stable_group_id(group)
        ground_group = ground_groups.get(group_id)
        if not ground_group:
            continue
        for match_index, match in enumerate(group.get("matches", []) or []):
            key = _validation_key(group, match, match_index)
            if key in validations:
                metrics["already_present"] += 1
                continue
            validation = _poc_validation_for_match(ground_group, match, match_index)
            if not validation:
                continue
            status = str(validation.get("status") or "")
            candidate = current_candidate(match)
            candidate_key = semantic_candidate_key(candidate)
            expected_key = str(
                validation.get("expected_candidate_key")
                or validation.get("selected_key")
                or validation.get("drop_card_key")
                or (validation.get("expected_candidate") or {}).get("card_uid")
                or ""
            )
            explicit_compatible = bool(
                expected_key
                and expected_key in {
                    candidate_key,
                    str((candidate or {}).get("card_uid") or ""),
                    str((candidate or {}).get("drop_card_key") or ""),
                }
            )
            semantic_compatible = validation.get("semantic_proposal") == _poc_semantic_proposal(match)
            if str(match.get("layout_type") or "") == "LEGEND_HALF" and validation.get("semantic_baseline_migrated") and not expected_key:
                semantic_compatible = False
            if not (explicit_compatible or semantic_compatible):
                metrics["stale"] += 1
                continue
            if status not in {"correct", "wrong", "manual_choice"}:
                continue
            state = "manual" if status == "manual_choice" else status
            validations[key] = {
                "state": state,
                "group_id": group_id,
                "subcard_id": stable_subcard_id(match, match_index),
                "subcard_photos": dict(match.get("subcard_photos") or {}),
                "candidate_key": candidate_key,
                "selected_candidate": candidate_identity(candidate) if state == "manual" else None,
                "proposal_signature": proposal_signature(match, candidate),
                "source": "poc_ground_truth",
                "updated_at": str(validation.get("validated_at") or datetime.now().isoformat(timespec="seconds")),
            }
            metrics["compatible"] += 1
            metrics["imported"] += 1
            changed = True
    session["poc_validation_reconciliation"] = {
        **metrics,
        "sample_key": sample_key,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
    if changed:
        session = save_drop_photo_session(session)
    return session, metrics


def _validation_key(group: dict[str, Any], match: dict[str, Any], match_index=0) -> str:
    return f"{stable_group_id(group)}:{stable_subcard_id(match, match_index)}"


def validation_for_match(
    session: dict[str, Any],
    group: dict[str, Any],
    match: dict[str, Any],
    match_index=0,
) -> dict[str, Any]:
    validation = dict((session.get("validations") or {}).get(_validation_key(group, match, match_index)) or {})
    if not validation:
        return {"state": "unvalidated", "compatible": False}
    candidate = validation.get("selected_candidate") or current_candidate(match)
    compatible = str(validation.get("proposal_signature") or "") == proposal_signature(match, candidate)
    return {**validation, "state": validation.get("state") if compatible else "stale", "compatible": compatible}


def set_match_validation(
    session: dict[str, Any],
    group: dict[str, Any],
    match: dict[str, Any],
    match_index: int,
    state: str,
    *,
    selected_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if state not in {"correct", "wrong", "manual"}:
        raise ValueError("Unsupported recognition validation state")
    candidate = selected_candidate or current_candidate(match)
    key = _validation_key(group, match, match_index)
    session.setdefault("validations", {})[key] = {
        "state": state,
        "group_id": stable_group_id(group),
        "subcard_id": stable_subcard_id(match, match_index),
        "subcard_photos": dict(match.get("subcard_photos") or {}),
        "candidate_key": semantic_candidate_key(candidate),
        "selected_candidate": candidate_identity(candidate) if selected_candidate else None,
        "proposal_signature": proposal_signature(match, candidate),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return save_drop_photo_session(session)


def confirm_grouping(session: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    session.setdefault("grouping_confirmations", {})[stable_group_id(group)] = {
        "photo_signature": engine.group_photo_signature(_group_photo_payload(group)),
        "confirmed_at": datetime.now().isoformat(timespec="seconds"),
    }
    return save_drop_photo_session(session)


def grouping_is_confirmed(session: dict[str, Any], group: dict[str, Any]) -> bool:
    confirmation = (session.get("grouping_confirmations") or {}).get(stable_group_id(group)) or {}
    return str(confirmation.get("photo_signature") or "") == engine.group_photo_signature(_group_photo_payload(group))


def _group_photo_capture_key(entry: dict[str, Any]) -> str:
    photo = entry.get("photo") if isinstance(entry, dict) else entry
    identity = normalize_photo_identity(photo)
    return f"{identity.get('capture_index', 0)}:{identity.get('filename', '')}"


def grouping_is_structurally_evident(group: dict[str, Any]) -> bool:
    """Return whether a historical single-card review is structurally obvious.

    V12 kept some front/back pairs in review purely because their capture timing
    was unusual. They do not need a human grouping decision when the physical
    pair, roles and subcard mapping are otherwise exact.
    """
    if group.get("grouping_status") != "review":
        return False
    matches = group.get("matches") or []
    photos = group.get("photos") or []
    if len(matches) != 1 or len(photos) != 2 or _safe_int(group.get("expected_cards"), 1) != 1:
        return False

    roles = [str((entry.get("classification") or {}).get("class") or "") for entry in photos]
    allowed_roles = {"primary_front", "back_western", "back_japanese"}
    if any(role not in allowed_roles for role in roles):
        return False
    if any(_safe_int((entry.get("classification") or {}).get("card_count_hint"), 1) > 1 for entry in photos):
        return False

    match_photos = matches[0].get("subcard_photos") or {}
    if {
        "front": str(match_photos.get("front") or ""),
        "back": str(match_photos.get("back") or ""),
    } != {
        "front": _group_photo_capture_key(photos[0]),
        "back": _group_photo_capture_key(photos[1]),
    }:
        return False

    reason_text = " ".join(_fold_text(reason) for reason in group.get("grouping_reasons") or [])
    conflict_markers = (
        "orphelin",
        "ambig",
        "incoherent",
        "plusieurs",
        "multiple",
        "manquant",
        "incomplet",
    )
    if any(marker in reason_text for marker in conflict_markers):
        return False

    # The back classifier can call a holographic or brightly lit front a back.
    # Its label alone is not a user-facing grouping ambiguity when the sequence
    # still maps one physical front/back pair to the only subcard exactly.
    return True


def grouping_needs_confirmation(session: dict[str, Any], group: dict[str, Any]) -> bool:
    """Return whether a stable grouping review still blocks this listing."""
    return bool(
        group.get("grouping_status") == "review"
        and not grouping_is_confirmed(session, group)
        and not grouping_is_structurally_evident(group)
    )


def effective_candidate(
    session: dict[str, Any],
    group: dict[str, Any],
    match: dict[str, Any],
    match_index=0,
) -> tuple[dict[str, Any] | None, str]:
    validation = validation_for_match(session, group, match, match_index)
    if validation.get("compatible") and validation.get("selected_candidate"):
        key = str(validation.get("candidate_key") or "")
        candidate = next(
            (row for row in (match.get("candidates") or []) if semantic_candidate_key(row.get("candidate")) == key),
            None,
        )
        return ((candidate or {}).get("candidate") or validation.get("selected_candidate")), "manual"
    return current_candidate(match), "manual" if validation.get("compatible") and validation.get("state") == "correct" else "auto"


def _match_needs_manual_review(
    session: dict[str, Any],
    group: dict[str, Any],
    match: dict[str, Any],
    match_index: int,
) -> bool:
    validation = validation_for_match(session, group, match, match_index)
    if validation.get("compatible") and validation.get("state") in {"correct", "manual"}:
        return False
    if validation.get("compatible") and validation.get("state") == "wrong":
        return True
    return str(match.get("status") or "fail") != "recognized" or not current_candidate(match)


def match_needs_manual_review(
    session: dict[str, Any],
    group: dict[str, Any],
    match: dict[str, Any],
    match_index: int,
) -> bool:
    """Return whether one physical subcard still blocks review completion."""
    return _match_needs_manual_review(session, group, match, match_index)


def multi_subcard_is_resolved(
    session: dict[str, Any],
    group: dict[str, Any],
    match: dict[str, Any],
    match_index: int,
) -> bool:
    """Return whether this physical subcard has an explicit accepted correction."""
    validation = validation_for_match(session, group, match, match_index)
    physical_subcard_id = stable_subcard_id(match, match_index)
    return bool(
        validation.get("compatible")
        and validation.get("state") in {"correct", "manual"}
        and str(validation.get("subcard_id") or "") == physical_subcard_id
    )


def pending_review_subcard_indexes(session: dict[str, Any], group: dict[str, Any]) -> list[int]:
    """Return physical subcards that still need attention in the review workspace.

    A multi-card listing is one review unit. Even an automatically recognized
    subcard must be explicitly accepted before the group can advance: otherwise
    the queue may disappear after validating only the one orange subcard.
    """
    matches = group.get("matches") or []
    if len(matches) > 1:
        return [
            index
            for index, match in enumerate(matches)
            if not multi_subcard_is_resolved(session, group, match, index)
        ]
    return [
        index
        for index, match in enumerate(matches)
        if match_needs_manual_review(session, group, match, index)
    ]


def next_pending_subcard_index(
    session: dict[str, Any],
    group: dict[str, Any],
    current_index: int,
    visited_subcards: set[str],
) -> int | None:
    """Return the next unresolved physical subcard of one multi-card listing."""
    matches = group.get("matches") or []
    unresolved = pending_review_subcard_indexes(session, group)
    if not unresolved:
        return None

    for offset in range(1, len(matches) + 1):
        index = (current_index + offset) % len(matches)
        if index not in unresolved:
            continue
        token = f"{stable_group_id(group)}:{stable_subcard_id(matches[index], index)}"
        if token not in visited_subcards:
            return index

    return unresolved[0]


def group_review_reasons(session: dict[str, Any], group: dict[str, Any]) -> list[str]:
    reasons = []
    matches = group.get("matches") or []
    if grouping_needs_confirmation(session, group):
        reasons.append("grouping")
    if len(matches) > 1 and pending_review_subcard_indexes(session, group):
        reasons.append("multi")
    if any(match.get("v13_japanese_candidate") or match.get("v13_japanese_signal") for match in matches):
        if any(_match_needs_manual_review(session, group, match, index) for index, match in enumerate(matches)):
            reasons.append("japanese")
    if any(
        match.get("v13_not_in_drop_confidence") in {"strong", "possible"}
        and _match_needs_manual_review(session, group, match, index)
        for index, match in enumerate(matches)
    ):
        reasons.append("not_in_drop")
    if any(
        str(match.get("status") or "fail") in {"fail", "unrecognized"}
        and _match_needs_manual_review(session, group, match, index)
        for index, match in enumerate(matches)
    ):
        reasons.append("fail")
    if any(_match_needs_manual_review(session, group, match, index) for index, match in enumerate(matches)):
        reasons.append("recognition")
    return list(dict.fromkeys(reasons))


def unresolved_groups(result: dict[str, Any], session: dict[str, Any]) -> list[dict[str, Any]]:
    return [group for group in result.get("groups", []) or [] if group_review_reasons(session, group)]


def analysis_summary(result: dict[str, Any], session: dict[str, Any] | None = None) -> dict[str, int | float]:
    session = session or {"validations": {}, "grouping_confirmations": {}}
    groups = result.get("groups", []) or []
    unresolved = unresolved_groups(result, session)
    fail_groups = sum(
        1
        for group in unresolved
        if group.get("confidence_level") == "red"
        or any(str(match.get("status") or "fail") in {"fail", "unrecognized"} for match in group.get("matches", []) or [])
    )
    review_groups = max(0, len(unresolved) - fail_groups)
    return {
        "photos": len(result.get("sample_photos", []) or []),
        "announcements": len(groups),
        "auto": max(0, len(groups) - len(unresolved)),
        "review": review_groups,
        "fail": fail_groups,
        "unresolved": len(unresolved),
        "grouping_review": sum(1 for group in groups if grouping_needs_confirmation(session, group)),
        "multi": sum(1 for group in groups if len(group.get("matches", []) or []) > 1),
    }


def restore_drop_analysis(folder: str | Path, drop_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    ordered = list_ordered_photos(folder)
    result = load_cached_analysis_result(
        folder=folder,
        drop_id=drop_id,
        start_index=1,
        target_announcements=len(ordered),
        max_photos=max(1, len(ordered)),
        ordered_photos=ordered,
    ) if ordered else None
    if result is None and ordered:
        result = load_latest_cached_analysis_result(folder=folder, drop_id=drop_id, ordered_photos=ordered)
    session = load_drop_photo_session(drop_id)
    if result is not None:
        _drop, candidates = active_drop_candidates(drop_id=drop_id)
        current_signature = candidate_set_signature(candidates)
        cached_meta = result.get("analysis_meta") or {}
        cached_signature = str(cached_meta.get("candidate_signature") or "")
        proposal_version_stale = (
            str(cached_meta.get("proposal_reliability_version") or "")
            != PROPOSAL_RELIABILITY_VERSION
        )
        language_version_stale = (
            str(cached_meta.get("language_compatibility_version") or "")
            != LANGUAGE_COMPATIBILITY_VERSION
        )
        if cached_signature != current_signature or proposal_version_stale or language_version_stale:
            result = refresh_result_candidates(result, drop_id=drop_id)
        session = initialize_drop_photo_session(drop_id, folder, result)
        session, _metrics = reconcile_poc_validations(
            result,
            session,
            folder=folder,
            drop_id=drop_id,
        )
    return result, session


def analyze_drop_photos(
    folder: str | Path,
    drop_id: str,
    *,
    force_rebuild=False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    photos = list_ordered_photos(folder)
    if not photos:
        raise ValueError("Aucune photo compatible dans le dossier sélectionné")
    result = analyze_sample(
        folder=folder,
        drop_id=drop_id,
        start_index=1,
        target_announcements=len(photos),
        max_photos=len(photos),
        force_rebuild=force_rebuild,
    )
    session = initialize_drop_photo_session(drop_id, folder, result)
    session, _metrics = reconcile_poc_validations(result, session, folder=folder, drop_id=drop_id)
    return result, session


def refresh_drop_analysis_candidates(
    result: dict[str, Any],
    session: dict[str, Any],
    *,
    drop_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    refreshed = refresh_result_candidates(result, drop_id=drop_id)
    session["candidate_signature"] = str((refreshed.get("analysis_meta") or {}).get("candidate_signature") or "")
    session["proposal_reliability_version"] = str(
        (refreshed.get("analysis_meta") or {}).get("proposal_reliability_version")
        or PROPOSAL_RELIABILITY_VERSION
    )
    session["language_compatibility_version"] = str(
        (refreshed.get("analysis_meta") or {}).get("language_compatibility_version")
        or LANGUAGE_COMPATIBILITY_VERSION
    )
    session = save_drop_photo_session(session)
    folder = str(session.get("folder") or "")
    if folder:
        session, _metrics = reconcile_poc_validations(
            refreshed,
            session,
            folder=folder,
            drop_id=drop_id,
        )
    return refreshed, session


def search_drop_candidates(result: dict[str, Any], query: str, *, limit=30) -> list[dict[str, Any]]:
    terms = [term for term in _fold_text(query).split() if term]
    candidates = result.get("candidates", []) or []
    if not terms:
        return []
    rows = []
    for candidate in candidates:
        blob = _fold_text(
            " ".join(
                [
                    str(candidate.get("name") or ""),
                    str(candidate.get("number") or ""),
                    str(candidate.get("set") or ""),
                    str(candidate.get("lot_name") or ""),
                    str(candidate.get("card_uid") or ""),
                ]
            )
        )
        if all(term in blob for term in terms):
            rows.append(candidate)
        if len(rows) >= limit:
            break
    return rows


def _photo_role(group: dict[str, Any], entry: dict[str, Any]) -> str:
    photo = entry.get("photo") or {}
    key = photo_key(photo)
    primary = group.get("primary_front") or {}
    if primary and photo_key(primary.get("photo") or {}) == key:
        return "primary_front"
    back = group.get("group_back") or {}
    if back and photo_key(back.get("photo") or {}) == key:
        classification = back.get("classification") or {}
        return "back_japanese" if classification.get("class") == "back_japanese" else "back_western"
    for match in group.get("matches", []) or []:
        photos = match.get("subcard_photos") or {}
        if key == photos.get("front"):
            return "card_front"
        if key == photos.get("back"):
            return "card_back"
    return "extra"


def build_step4_payload(
    result: dict[str, Any],
    session: dict[str, Any],
    *,
    photo_capture_direction="start_to_end",
    require_ready=True,
) -> dict[str, Any]:
    listings = []
    errors = []
    seen_photos = set()
    for group in result.get("groups", []) or []:
        group_id = stable_group_id(group)
        reasons = group_review_reasons(session, group)
        cards = []
        for index, match in enumerate(group.get("matches", []) or []):
            candidate, source = effective_candidate(session, group, match, index)
            if not candidate:
                errors.append(f"{group_id}: sous-carte {index + 1} sans candidat")
                continue
            validation = validation_for_match(session, group, match, index)
            cards.append(
                {
                    **candidate_identity(candidate),
                    "candidate": dict(candidate),
                    "subcard_id": stable_subcard_id(match, index),
                    "subcard_photos": dict(match.get("subcard_photos") or {}),
                    "validation_source": "manual" if source == "manual" else "auto",
                    "confidence": float(match.get("score") or 0),
                    "validation_state": validation.get("state", "unvalidated"),
                }
            )
        photos = []
        for entry in group.get("photos", []) or []:
            photo = entry.get("photo") or {}
            identity = normalize_photo_identity(photo)
            key = photo_key(identity)
            if key in seen_photos:
                errors.append(f"Photo dupliquée dans le payload: {key}")
            seen_photos.add(key)
            photos.append({**identity, "role": _photo_role(group, entry)})
        if reasons:
            errors.append(f"{group_id}: " + ", ".join(reasons))
        primary = next((photo for photo in photos if photo.get("role") == "primary_front"), photos[0] if photos else {})
        listings.append(
            {
                "recognition_group_id": group_id,
                "announcement_index": _safe_int(group.get("announcement_index"), len(listings) + 1),
                "photo_order": _safe_int(group.get("announcement_index"), len(listings) + 1),
                "photos": photos,
                "primary_front": primary,
                "cards": cards,
                "card_uids": [card.get("card_uid") for card in cards if card.get("card_uid")],
                "validation_source": "manual" if any(card.get("validation_source") == "manual" for card in cards) else "auto",
                "confidence": min((card.get("confidence", 0) for card in cards), default=0),
                "ready": not reasons and len(cards) == max(1, len(group.get("matches", []) or [])),
            }
        )
    if photo_capture_direction == "end_to_start":
        listings.reverse()
    for index, listing in enumerate(listings, start=1):
        listing["creation_order"] = index
    expected_photos = len(result.get("sample_photos", []) or [])
    if len(seen_photos) != expected_photos:
        errors.append(f"Couverture photo incomplète: {len(seen_photos)} / {expected_photos}")
    return {
        "drop_id": str((result.get("analysis_meta") or {}).get("drop_id") or ""),
        "pipeline_version": str((result.get("analysis_meta") or {}).get("pipeline_version") or ""),
        "photo_signature": str((result.get("analysis_meta") or {}).get("photo_signature") or ""),
        "photo_capture_direction": photo_capture_direction,
        "listings": listings,
        "errors": errors if require_ready else [],
        "diagnostic_errors": errors,
        "ready": not errors,
        "photo_count": len(seen_photos),
    }


def apply_recognition_statuses(drops_data: dict[str, Any], drop_id: str, payload: dict[str, Any]) -> int:
    """Apply recognition states to eligible items only; online/sold are immutable."""
    drop = find_drop(drops_data, drop_id)
    if not drop:
        return 0
    if drop.get("drop_launched_at"):
        return 0
    ready_uids = {
        str(uid)
        for listing in payload.get("listings", []) or []
        if listing.get("ready")
        for uid in listing.get("card_uids", []) or []
        if uid
    }
    changed = 0
    for ref in drop.get("cards", []) or []:
        if drop_item_status(ref) in {"online", "sold", "draft_ready"}:
            continue
        uid = str(ref.get("card_uid") or "")
        desired = "sorted" if uid in ready_uids else "needs_review"
        if desired and ref.get("status") != desired:
            ref["status"] = desired
            changed += 1
    return changed


def persist_uploaded_photos(drop_id: str, uploaded_files: Iterable[Any]) -> Path:
    uploaded_files = list(uploaded_files or [])
    batch_signature = hashlib.sha1(
        "|".join(
            f"{getattr(uploaded, 'name', '')}:{getattr(uploaded, 'size', '')}"
            for uploaded in uploaded_files
        ).encode("utf-8")
    ).hexdigest()[:12]
    target = (
        PRODUCTION_CACHE_DIR
        / "uploads"
        / re.sub(r"[^a-zA-Z0-9_-]", "_", str(drop_id or "unknown"))
        / batch_signature
    )
    target.mkdir(parents=True, exist_ok=True)
    for index, uploaded in enumerate(uploaded_files, start=1):
        name = Path(str(getattr(uploaded, "name", "") or f"photo_{index}.jpg")).name
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            continue
        destination = target / name
        with destination.open("wb") as handle:
            shutil.copyfileobj(uploaded, handle)
    return target

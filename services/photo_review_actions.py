"""Actions de verification des photos du Drop (hors moteur de reconnaissance).

* messages precis et groupes « Deja publiee — ignoree » : calcul A L'AFFICHAGE sur toutes les
  references du Drop, sans jamais changer les candidats de reconnaissance ;
* carte « pas dans mon stock » : decision memorisee dans la session de verification ;
* regroupement : regle du verso orphelin + deplacement de photos, avec rematch limite des seuls
  groupes touches (OCR en cache reutilise).

Tout est memorise dans la session de verification (``.cache/photo_recognition/drop_sessions``),
jamais dans data.json / vinted_drops.json / lots_archives.json.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from services import photo_recognition_poc_service as engine
from services import photo_recognition_service as svc
from services.vinted_drops_service import drop_item_status

PUBLISHED_STATUSES = {"online", "sold"}
STATUS_LABELS = {
    "online": "en ligne",
    "sold": "vendue",
    "draft_ready": "brouillon créé",
    "to_photograph": "à photographier",
    "sorted": "triée",
    "needs_review": "à vérifier",
    "to_prepare": "à préparer",
}
NAME_THRESHOLD = 0.86
BACK_THRESHOLD = 0.60  # score verso a partir duquel un verso « orphelin » est rattache d'office
REGROUP_LOG_LIMIT = 50


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- references du Drop
def drop_references(drop: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Toutes les references du Drop (en ligne, vendues, a traiter...), pas seulement le perimetre."""
    rows = []
    for ref in (drop or {}).get("cards", []) or []:
        status = drop_item_status(ref)
        rows.append(
            {
                "item_id": str(ref.get("drop_item_id") or ""),
                "card_uid": str(ref.get("card_uid") or ""),
                "name": str(ref.get("name") or ""),
                "number": str(ref.get("display_number") or ref.get("number") or ""),
                "local_number": str(ref.get("number") or ref.get("display_number") or ""),
                "set": str(ref.get("set") or ""),
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
                "published": status in PUBLISHED_STATUSES,
            }
        )
    return rows


def scope_item_ids(result: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Identifiants (drop_item_id, card_uid) des cartes candidates de la reconnaissance."""
    items, uids = set(), set()
    for candidate in result.get("candidates", []) or []:
        if candidate.get("drop_item_id"):
            items.add(str(candidate["drop_item_id"]))
        elif candidate.get("card_uid"):
            uids.add(str(candidate["card_uid"]))
    return items, uids


def _in_scope(ref: dict[str, Any], scope: tuple[set[str], set[str]]) -> bool:
    items, uids = scope
    if ref["item_id"] and ref["item_id"] in items:
        return True
    return bool(ref["card_uid"] and ref["card_uid"] in uids)


def ocr_signals(match: dict[str, Any]) -> dict[str, list[str]]:
    ocr = match.get("ocr") or {}
    names = [
        str(value)
        for value in (ocr.get("name_texts") or [])
        if 3 <= len(engine._fold_text(value)) <= 32
    ]
    fulls = []
    for value in ocr.get("collector_number_texts") or []:
        normalized = engine._normalize_card_number(value)
        if "/" in normalized:
            fulls.append(normalized)
    return {"names": names, "fulls": fulls}


def _local(number: str) -> str:
    return str(engine._number_local(number) or "").lstrip("0") or ("0" if number else "")


def _reference_score(ref: dict[str, Any], signals: dict[str, list[str]]) -> float:
    """Correspondance FORTE : nom proche ET numero (partie locale) du numero complet lu identique.

    Le total du set n'est volontairement pas exige : les totaux enregistres dans le Drop sont parfois
    differents de ceux imprimes (108/198 enregistre pour une carte 108/091). Un total identique
    ne sert qu'a departager les candidats.
    """
    if not signals["names"] or not signals["fulls"] or not ref["name"]:
        return 0.0
    name_similarity = max(engine._similarity(text, ref["name"]) for text in signals["names"])
    if name_similarity < NAME_THRESHOLD:
        return 0.0
    ref_local = _local(engine._normalize_card_number(ref.get("local_number") or ref["number"]))
    if not ref_local:
        return 0.0
    ref_full = engine._normalize_card_number(ref["number"])
    for full in signals["fulls"]:
        if _local(full) != ref_local:
            continue
        same_total = "/" in ref_full and ref_full.split("/", 1)[1].lstrip("0") == full.split("/", 1)[1].lstrip("0")
        return name_similarity + (0.05 if same_total else 0.0)
    return 0.0


def strong_reference_matches(match: dict[str, Any], drop: dict[str, Any] | None, result: dict[str, Any]) -> list[dict[str, Any]]:
    signals = ocr_signals(match)
    scope = scope_item_ids(result)
    found = []
    for ref in drop_references(drop):
        score = _reference_score(ref, signals)
        if score:
            found.append({**ref, "in_scope": _in_scope(ref, scope), "score": round(score, 3)})
    found.sort(key=lambda row: (not row["published"], -row["score"]))
    return found


def _ref_text(ref: dict[str, Any]) -> str:
    bits = [ref["name"], ref["number"]]
    text = " ".join(bit for bit in bits if bit)
    if ref.get("set"):
        text += f" · {ref['set']}"
    return f"{text} ({ref['status_label']})"


def not_in_drop_hint(match: dict[str, Any], drop: dict[str, Any] | None, result: dict[str, Any]) -> dict[str, Any]:
    """Message precis a la place de « Carte peut-etre absente du Drop »."""
    found = strong_reference_matches(match, drop, result)
    published = [row for row in found if row["published"] and not row["in_scope"]]
    if published:
        ref = published[0]
        return {"kind": "published", "reference": ref, "message": f"Déjà publiée dans le Drop : {_ref_text(ref)}"}
    out_of_scope = [row for row in found if not row["in_scope"]]
    if out_of_scope:
        ref = out_of_scope[0]
        return {"kind": "out_of_scope", "reference": ref, "message": f"Absente des cartes à traiter : {_ref_text(ref)}"}
    in_scope = [row for row in found if row["in_scope"]]
    if in_scope:
        ref = in_scope[0]
        return {"kind": "in_scope", "reference": ref, "message": f"Plutôt dans les cartes à traiter : {_ref_text(ref)}"}
    return {"kind": "absent", "reference": None, "message": "Absente du Drop"}


def likely_reference_hint(match: dict[str, Any], drop: dict[str, Any] | None, result: dict[str, Any]) -> dict[str, Any] | None:
    """« Plus probable : ... » : meilleure reference du Drop (tous statuts) autre que la proposition."""
    proposed = svc.current_candidate(match) or {}
    proposed_item = str(proposed.get("drop_item_id") or "")
    proposed_uid = str(proposed.get("card_uid") or "")
    for ref in strong_reference_matches(match, drop, result):
        if proposed_item and ref["item_id"] == proposed_item:
            continue
        if not proposed_item and proposed_uid and ref["card_uid"] == proposed_uid:
            continue
        return {"reference": ref, "message": f"Plus probable : {_ref_text(ref)}"}
    return None


def match_hint_message(match: dict[str, Any], drop: dict[str, Any] | None, result: dict[str, Any]) -> str:
    """Message d'affichage complementaire pour un match « a verifier » (vide si rien a dire)."""
    if match.get("v13_not_in_drop_confidence") in {"strong", "possible"}:
        return not_in_drop_hint(match, drop, result)["message"]
    if svc.ocr_conflict_blocks_recognition(match):
        candidate = svc.current_candidate(match) or {}
        ocr_numbers = ", ".join((match.get("ocr") or {}).get("collector_number_texts") or [])
        head = f"Numéro lu {ocr_numbers} ≠ {candidate.get('number') or '?'} (proposition basée sur le nom seul)"
        likely = likely_reference_hint(match, drop, result)
        return f"{head} · {likely['message']}" if likely else head
    return ""


# --------------------------------------------------------------------------- dispositions
def _group_photos_payload(group: dict[str, Any]) -> list[dict[str, Any]]:
    return svc._group_photo_payload(group)


def _ocr_read(group: dict[str, Any]) -> dict[str, str]:
    for match in group.get("matches", []) or []:
        ocr = match.get("ocr") or {}
        names = ocr.get("name_texts") or []
        numbers = ocr.get("collector_number_texts") or ocr.get("number_texts") or []
        if names or numbers:
            return {
                "name": str(names[0]) if names else "",
                "number": str(numbers[0]) if numbers else "",
                "set": "",
            }
    return {"name": "", "number": "", "set": ""}


def _set_disposition(session: dict[str, Any], group: dict[str, Any], kind: str, *, source: str, reference=None) -> None:
    session.setdefault("review_dispositions", {})[svc.stable_group_id(group)] = {
        "kind": kind,
        "source": source,
        "photo_signature": engine.group_photo_signature(_group_photos_payload(group)),
        "decided_at": _now(),
        "announcement_index": group.get("announcement_index"),
        "photos": _group_photos_payload(group),
        "ocr": _ocr_read(group),
        "reference": reference or {},
    }


def sync_review_dispositions(
    result: dict[str, Any],
    session: dict[str, Any],
    drop: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Met a jour les groupes « Deja publiee — ignoree » (calcul automatique) et libere les groupes
    « pas dans mon stock » dont la carte a ete ajoutee au Drop. N'ecrit la session que si elle change.
    """
    dispositions = session.setdefault("review_dispositions", {})
    rejected = session.setdefault("published_rejected", {})
    groups = result.get("groups", []) or []
    present = {svc.stable_group_id(group): group for group in groups}
    report = {"ignored": 0, "released": 0, "dropped": 0}
    changed = False

    # decisions devenues sans objet (groupe disparu / photos changees)
    for group_id in list(dispositions):
        group = present.get(group_id)
        entry = dispositions[group_id]
        if group is None or str(entry.get("photo_signature") or "") != engine.group_photo_signature(_group_photos_payload(group)):
            del dispositions[group_id]
            report["dropped"] += 1
            changed = True

    for group in groups:
        group_id = svc.stable_group_id(group)
        signature = engine.group_photo_signature(_group_photos_payload(group))
        entry = dispositions.get(group_id)
        matches = group.get("matches", []) or []

        # carte « pas dans mon stock » ajoutee entre-temps au perimetre : le groupe repasse normalement
        if entry and entry.get("kind") == svc.REVIEW_DISPOSITION_NOT_IN_STOCK:
            if any(row["in_scope"] for match in matches for row in strong_reference_matches(match, drop, result)):
                del dispositions[group_id]
                report["released"] += 1
                changed = True
            continue
        if entry and entry.get("source") == "user":
            continue

        eligible = bool(matches)
        if eligible and rejected.get(group_id) == signature:
            eligible = False
        if eligible and svc._group_has_user_validation(session, group):
            eligible = False
        hints = []
        if eligible:
            for match in matches:
                if match.get("v13_not_in_drop_confidence") not in {"strong", "possible"}:
                    hints = []
                    break
                hint = not_in_drop_hint(match, drop, result)
                if hint["kind"] != "published":
                    hints = []
                    break
                hints.append(hint)
        if hints:
            reference = hints[0]["reference"]
            keep = {k: reference[k] for k in ("item_id", "name", "number", "set", "status", "status_label")}
            if not entry or entry.get("reference") != keep or entry.get("photo_signature") != signature:
                _set_disposition(session, group, svc.REVIEW_DISPOSITION_PUBLISHED, source="auto", reference=keep)
                changed = True
            report["ignored"] += 1
        elif entry:  # ancienne decision automatique qui ne tient plus
            del dispositions[group_id]
            report["dropped"] += 1
            changed = True
    if changed:
        session = svc.save_drop_photo_session(session)
    return session, report


def reject_published(session: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    """« Ce n'est pas la bonne carte » : le groupe retourne dans « A verifier » (et y reste)."""
    group_id = svc.stable_group_id(group)
    session.setdefault("review_dispositions", {}).pop(group_id, None)
    session.setdefault("published_rejected", {})[group_id] = engine.group_photo_signature(_group_photos_payload(group))
    return svc.save_drop_photo_session(session)


def mark_not_in_stock(session: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    """« Cette carte n'est pas dans mon stock » : sort de la verification, ne cree aucune annonce."""
    _set_disposition(session, group, svc.REVIEW_DISPOSITION_NOT_IN_STOCK, source="user")
    return svc.save_drop_photo_session(session)


def restore_to_review(session: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    """« Remettre dans la verification » : annule « pas dans mon stock »."""
    session.setdefault("review_dispositions", {}).pop(svc.stable_group_id(group), None)
    return svc.save_drop_photo_session(session)


def disposition_rows(result: dict[str, Any], session: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    rows = []
    for group in result.get("groups", []) or []:
        if svc.group_disposition(session, group) != kind:
            continue
        entry = (session.get("review_dispositions") or {}).get(svc.stable_group_id(group)) or {}
        rows.append({"group": group, "group_id": svc.stable_group_id(group), "entry": entry})
    return rows


def group_processed_label(group: dict[str, Any], session: dict[str, Any], drop: dict[str, Any] | None) -> str:
    """Etiquette « deja creee / publiee » d'une annonce (toggle « Consulter aussi... »)."""
    disposition = svc.group_disposition(session, group)
    if disposition == svc.REVIEW_DISPOSITION_PUBLISHED:
        return "Déjà publiée — ignorée"
    if disposition == svc.REVIEW_DISPOSITION_NOT_IN_STOCK:
        return "Carte hors stock — à enregistrer"
    refs = {ref["item_id"]: ref for ref in drop_references(drop) if ref["item_id"]}
    statuses = []
    for index, match in enumerate(group.get("matches", []) or []):
        candidate, _source = svc.effective_candidate(session, group, match, index)
        ref = refs.get(str((candidate or {}).get("drop_item_id") or ""))
        if not ref:
            return ""
        statuses.append(ref["status"])
    if not statuses:
        return ""
    if all(status == "sold" for status in statuses):
        return "Annonce déjà vendue"
    if all(status in PUBLISHED_STATUSES for status in statuses):
        return "Annonce déjà en ligne"
    if all(status in {"draft_ready", "online", "sold"} for status in statuses):
        return "Annonce déjà créée (brouillon)"
    return ""


# --------------------------------------------------------------------------- regroupement des photos
def _entry_key(entry: dict[str, Any]) -> str:
    return svc.photo_key(svc.normalize_photo_identity(entry.get("photo") or {}))


def _entry_index(entry: dict[str, Any]) -> int:
    return int(svc.normalize_photo_identity(entry.get("photo") or {}).get("capture_index") or 0)


def _is_detail(entry: dict[str, Any]) -> bool:
    return (entry.get("classification") or {}).get("review_role") == "detail"


def _as_detail(entry: dict[str, Any]) -> dict[str, Any]:
    return {**entry, "classification": {**(entry.get("classification") or {}), "review_role": "detail"}}


def _as_regular(entry: dict[str, Any]) -> dict[str, Any]:
    classification = {k: v for k, v in (entry.get("classification") or {}).items() if k != "review_role"}
    return {**entry, "classification": classification}


def _is_back_entry(entry: dict[str, Any], threshold: float = BACK_THRESHOLD) -> bool:
    classification = entry.get("classification") or {}
    if engine._is_back_class(classification):
        return True
    return engine._safe_float(classification.get("western_back_score"), 0.0) >= threshold


def _is_simple_group(group: dict[str, Any]) -> bool:
    return engine._safe_int(group.get("expected_cards"), 1) <= 1 and not (group.get("detail_cards") or [])


def build_review_group(entries: list[dict[str, Any]], *, index: int, reasons: list[str]) -> dict[str, Any]:
    """Reconstruit un groupe simple (1 carte) a partir de ses photos.

    La 1re photo « d'identification » est le recto, la 2e le verso ; les photos marquees « detail »
    (et toute photo au-dela de 2) restent dans l'annonce mais ne servent pas a l'identification.
    """
    ordered = sorted(entries, key=_entry_index)
    identification = [entry for entry in ordered if not _is_detail(entry)]
    replacements: dict[str, dict[str, Any]] = {}
    for extra in identification[2:]:
        replacements[_entry_key(extra)] = _as_detail(extra)
    identification = identification[:2]
    primary = identification[0] if identification else None
    back = identification[1] if len(identification) > 1 else None
    if primary is not None and engine._is_back_class(primary.get("classification") or {}) and back is not None:
        # recto lu comme verso : meme reinterpretation que la segmentation V12
        classification = {**(primary.get("classification") or {}), "class": "primary_front", "review_reinterpreted_front": True}
        primary = {**primary, "classification": classification}
    if back is not None and not engine._is_back_class(back.get("classification") or {}):
        back = engine._entry_as_sequence_back(back)
    if primary is not None:
        replacements[_entry_key(primary)] = primary
    if back is not None:
        replacements[_entry_key(back)] = back
    photos = [replacements.get(_entry_key(entry), entry) for entry in ordered]
    if primary is not None and back is not None:
        status, why = "ok", reasons
    elif primary is not None and not engine._is_back_class(primary.get("classification") or {}):
        status, why = "review", reasons + ["recto isolé : verso manquant probable"]
    else:
        status, why = "review", reasons + ["verso isolé : recto manquant ou séquence ambiguë"]
    return {
        "announcement_index": index,
        "photos": photos,
        "primary_front": primary,
        "group_back": back,
        "detail_cards": [],
        "expected_cards": 1,
        "grouping_status": status,
        "grouping_reasons": why,
    }


def plan_orphan_verso(groups: list[dict[str, Any]], session: dict[str, Any]) -> list[int]:
    """Indices de groupes dont la 1re photo est un verso a rattacher au recto isole precedent."""
    moves = (session or {}).get("photo_moves") or {}
    plan = []
    for index in range(1, len(groups)):
        previous, current = groups[index - 1], groups[index]
        if not (_is_simple_group(previous) and _is_simple_group(current)):
            continue
        previous_photos = previous.get("photos") or []
        current_photos = current.get("photos") or []
        if len(previous_photos) != 1 or not current_photos:
            continue
        if _is_back_entry(previous_photos[0]):
            continue  # le groupe precedent n'est pas un « recto seul »
        first = current_photos[0]
        if not _is_back_entry(first):
            continue
        if (moves.get(_entry_key(first)) or {}).get("source") == "user":
            continue  # decision de l'utilisateur : la regle ne revient pas dessus
        plan.append(index)
    return plan


def _blocked_counts(result, session, candidates, exclude_groups) -> dict[str, int]:
    status_by_key = {str(c.get("drop_card_key") or ""): str(c.get("drop_status") or "") for c in candidates}
    excluded = {id(group) for group in exclude_groups}
    counts: dict[str, int] = {}
    for group in result.get("groups", []) or []:
        if id(group) in excluded or svc.group_disposition(session, group):
            continue
        if not (svc._group_has_user_validation(session, group) or svc._group_is_published(session, group, status_by_key)):
            continue
        for index, match in enumerate(group.get("matches") or []):
            candidate, _source = svc.effective_candidate(session, group, match, index)
            key = str((candidate or {}).get("drop_card_key") or (candidate or {}).get("_drop_card_key") or "")
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def _rematch(result, session, drop_id, new_groups, cached_ocr, progress_callback=None):
    """Reconnaissance des seuls groupes reconstruits ; l'OCR deja lu est reutilise."""
    if not new_groups:
        return
    _drop, candidates = engine.active_drop_candidates(drop_id=drop_id)
    blocked = _blocked_counts(result, session, candidates, new_groups)
    engine._recognize_groups(
        new_groups,
        candidates,
        cached_ocr_by_path=cached_ocr,
        candidate_indexes=engine._candidate_indexes(candidates),
        initial_used_candidate_counts=dict(blocked),
        blocked_counts=blocked,
        progress_callback=progress_callback,
    )


def _invalidate(session: dict[str, Any], old_groups: list[dict[str, Any]]) -> list[str]:
    """Retire les validations / confirmations / decisions des groupes remplaces ; renvoie un resume."""
    notes = []
    for group in old_groups:
        group_id = svc.stable_group_id(group)
        label = f"annonce {group.get('announcement_index')}"
        removed = []
        validations = session.get("validations") or {}
        for key in [k for k, v in validations.items() if str((v or {}).get("group_id") or "") == group_id]:
            removed.append(str((validations.pop(key) or {}).get("state") or "?"))
        if (session.get("grouping_confirmations") or {}).pop(group_id, None):
            removed.append("regroupement confirmé")
        if (session.get("review_dispositions") or {}).pop(group_id, None):
            removed.append("décision (ignorée / hors stock)")
        (session.get("grouping_flagged") or {}).pop(group_id, None)
        if removed:
            notes.append(f"{label} : " + ", ".join(removed))
    return notes


def _commit_regroup(result, session, drop_id, old_groups, new_groups, replace_at, *, log, progress_callback=None):
    """Remplace ``old_groups`` par ``new_groups`` (meme place), rematche, invalide, enregistre."""
    cached = engine._cached_ocr_from_groups(result.get("groups", []) or [])
    groups = list(result.get("groups", []) or [])
    old_ids = {id(group) for group in old_groups}
    position = min(replace_at, len(groups))
    kept_before = [group for group in groups[:position] if id(group) not in old_ids]
    kept_after = [group for group in groups[position:] if id(group) not in old_ids]
    result["groups"] = kept_before + list(new_groups) + kept_after
    notes = _invalidate(session, old_groups)
    _rematch(result, session, drop_id, new_groups, cached, progress_callback)
    session.setdefault("regroup_log", []).append({**log, "at": _now(), "invalidated": notes})
    session["regroup_log"] = session["regroup_log"][-REGROUP_LOG_LIMIT:]
    engine.save_cached_analysis_result(result)
    session = svc.save_drop_photo_session(session)
    return result, session, notes


def apply_orphan_verso_rule(result, session, *, drop_id, progress_callback=None):
    """Regle A : un verso qui ouvre un groupe est rattache au recto isole precedent ; le reste se regroupe.

    Deterministe et idempotent : a rejouer apres chaque nouvelle analyse. Renvoie (result, session, rapport).
    """
    applied = []
    for _ in range(len(result.get("groups", []) or []) + 1):
        groups = result.get("groups", []) or []
        plan = plan_orphan_verso(groups, session)
        if not plan:
            break
        index = plan[0]
        previous, current = groups[index - 1], groups[index]
        moved = current["photos"][0]
        remainder = list(current["photos"][1:])
        following = groups[index + 1] if index + 1 < len(groups) else None
        merged_with_next = False
        new_groups, old_groups = [], [previous, current]
        reasons_prev = ["verso orphelin rattaché au recto précédent (règle automatique)"]
        new_previous = build_review_group(
            list(previous["photos"]) + [moved], index=previous.get("announcement_index", index), reasons=reasons_prev
        )
        new_groups.append(new_previous)
        if remainder:
            if len(remainder) == 1 and following is not None and _is_simple_group(following) and len(following["photos"]) == 1:
                new_groups.append(
                    build_review_group(
                        remainder + list(following["photos"]),
                        index=current.get("announcement_index", index + 1),
                        reasons=["regroupé après rattachement du verso précédent (règle automatique)"],
                    )
                )
                old_groups.append(following)
                merged_with_next = True
            else:
                new_groups.append(
                    build_review_group(remainder, index=current.get("announcement_index", index + 1), reasons=["reste du groupe après rattachement d'un verso (règle automatique)"])
                )
        log = {
            "kind": "orphan_verso",
            "photo": svc.normalize_photo_identity(moved["photo"]),
            "from_announcement": current.get("announcement_index"),
            "to_announcement": previous.get("announcement_index"),
            "merged_with_next": merged_with_next,
        }
        result, session, notes = _commit_regroup(
            result, session, drop_id, old_groups, new_groups, index - 1, log=log, progress_callback=progress_callback
        )
        applied.append({**log, "invalidated": notes})
    return result, session, {"applied": applied}


def locate_photo(groups: list[dict[str, Any]], key: str) -> tuple[int | None, dict[str, Any] | None]:
    for index, group in enumerate(groups):
        for entry in group.get("photos", []) or []:
            if _entry_key(entry) == key:
                return index, entry
    return None, None


def _target_role_is_detail(target: dict[str, Any], entry: dict[str, Any]) -> bool:
    """Une photo rattachee devient le verso si l'annonce n'a qu'un recto ; sinon c'est une photo de detail."""
    identification = [e for e in target.get("photos", []) or [] if not _is_detail(e)]
    if not identification:
        return False
    if len(identification) == 1:
        existing = identification[0]
        if _entry_index(entry) > _entry_index(existing):
            return False
        return not (_is_back_entry(existing, 0.5) and not _is_back_entry(entry, 0.5))
    return True


def move_photo(result, session, key, action, *, drop_id, progress_callback=None, source="user"):
    """Action utilisateur sur une photo : ``prev`` / ``next`` / ``detail``.

    Seuls les groupes touches sont reconstruits et rematches (OCR en cache) ; leurs validations sont
    invalidees et listees dans ``report['invalidated']``. Les autres annonces ne changent pas.
    """
    groups = result.get("groups", []) or []
    group_index, entry = locate_photo(groups, key)
    if entry is None:
        return result, session, {"ok": False, "message": "Photo introuvable dans l'analyse."}
    group = groups[group_index]
    others = [e for e in group.get("photos", []) or [] if _entry_key(e) != key]
    if action == "detail":
        target_index = group_index if any(not _is_detail(e) for e in others) else (group_index - 1 if group_index > 0 else group_index + 1)
    elif action == "prev":
        target_index = group_index - 1
    elif action == "next":
        target_index = group_index + 1
    else:
        return result, session, {"ok": False, "message": "Action inconnue."}
    if target_index < 0 or target_index >= len(groups):
        return result, session, {"ok": False, "message": "Pas d'annonce voisine de ce côté."}
    return _do_move(
        result, session, key, group_index, target_index,
        detail=True if action == "detail" else None,
        drop_id=drop_id, progress_callback=progress_callback, source=source, action=action,
    )


def _do_move(result, session, key, group_index, target_index, *, detail, drop_id, progress_callback, source, action):
    groups = result.get("groups", []) or []
    group = groups[group_index]
    target = groups[target_index]
    entry = next(e for e in group["photos"] if _entry_key(e) == key)
    if not (_is_simple_group(group) and _is_simple_group(target)):
        return result, session, {"ok": False, "message": "Annonce multi-cartes : déplacement indisponible."}
    reasons = ["regroupement manuel" if source == "user" else "regroupement automatique"]
    if target_index == group_index:
        flagged = _as_detail(entry)
        new_group = build_review_group(
            [flagged if _entry_key(e) == key else e for e in group["photos"]],
            index=group.get("announcement_index", group_index + 1), reasons=reasons,
        )
        old_groups, new_groups, replace_at = [group], [new_group], group_index
        anchor_group = new_group
    else:
        as_detail = detail if detail is not None else _target_role_is_detail(target, entry)
        moved = _as_detail(entry) if as_detail else _as_regular(entry)
        new_target = build_review_group(
            list(target["photos"]) + [moved],
            index=target.get("announcement_index", target_index + 1), reasons=reasons,
        )
        remaining = [e for e in group["photos"] if _entry_key(e) != key]
        new_source = (
            build_review_group(remaining, index=group.get("announcement_index", group_index + 1),
                               reasons=reasons + ["photo déplacée vers une annonce voisine"])
            if remaining else None
        )
        if target_index < group_index:
            old_groups, new_groups = [target, group], [new_target] + ([new_source] if new_source else [])
        else:
            old_groups, new_groups = [group, target], ([new_source] if new_source else []) + [new_target]
        replace_at = min(group_index, target_index)
        anchor_group = new_target
    session.setdefault("photo_moves", {})[key] = {
        "action": action,
        "anchor": _entry_key(anchor_group["primary_front"]) if anchor_group.get("primary_front") else "",
        "source": source,
        "at": _now(),
    }
    log = {
        "kind": "photo_move",
        "action": action,
        "photo": svc.normalize_photo_identity(entry["photo"]),
        "from_announcement": group.get("announcement_index"),
        "to_announcement": target.get("announcement_index"),
    }
    result, session, notes = _commit_regroup(
        result, session, drop_id, old_groups, new_groups, replace_at, log=log, progress_callback=progress_callback
    )
    return result, session, {
        "ok": True,
        "message": "Photo déplacée." if target_index != group_index else "Photo marquée « détail ».",
        "invalidated": notes,
        "new_group_ids": [svc.stable_group_id(g) for g in new_groups],
        "destination_group_id": svc.stable_group_id(anchor_group),
    }


def reapply_user_moves(result, session, *, drop_id, progress_callback=None):
    """Rejoue les deplacements memorises apres une nouvelle analyse (idempotent)."""
    applied = 0
    for key, move in list((session.get("photo_moves") or {}).items()):
        if (move or {}).get("source") != "user":
            continue
        groups = result.get("groups", []) or []
        group_index, entry = locate_photo(groups, key)
        anchor_index, _anchor = locate_photo(groups, str(move.get("anchor") or ""))
        if entry is None or anchor_index is None:
            continue
        wants_detail = move.get("action") == "detail"
        if anchor_index == group_index:
            if wants_detail and not _is_detail(entry):
                result, session, report = _do_move(
                    result, session, key, group_index, group_index, detail=True,
                    drop_id=drop_id, progress_callback=progress_callback, source="user", action="detail",
                )
                applied += 1 if report.get("ok") else 0
            continue
        result, session, report = _do_move(
            result, session, key, group_index, anchor_index,
            detail=True if wants_detail else None,
            drop_id=drop_id, progress_callback=progress_callback, source="user", action=str(move.get("action") or "prev"),
        )
        applied += 1 if report.get("ok") else 0
    return result, session, {"reapplied": applied}


def apply_review_layers(result, session, drop, *, drop_id, progress_callback=None):
    """Point d'entree unique apres chargement / analyse : deplacements memorises, regle du verso,
    puis groupes ignores. Idempotent ; ne fait rien (et n'ecrit rien) si tout est deja a jour.
    """
    result, session, moves = reapply_user_moves(result, session, drop_id=drop_id, progress_callback=progress_callback)
    result, session, rule = apply_orphan_verso_rule(result, session, drop_id=drop_id, progress_callback=progress_callback)
    session, sync = sync_review_dispositions(result, session, drop)
    return result, session, {"moves": moves, "rule": rule, "sync": sync}


def flag_grouping(session: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    """« Grouping incorrect » : memorise le signalement (le groupe reste a corriger)."""
    session.setdefault("grouping_flagged", {})[svc.stable_group_id(group)] = {
        "photo_signature": engine.group_photo_signature(_group_photos_payload(group)),
        "at": _now(),
    }
    return svc.save_drop_photo_session(session)


def is_grouping_flagged(session: dict[str, Any], group: dict[str, Any]) -> bool:
    entry = (session.get("grouping_flagged") or {}).get(svc.stable_group_id(group)) or {}
    return bool(entry) and entry.get("photo_signature") == engine.group_photo_signature(_group_photos_payload(group))

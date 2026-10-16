"""« 🔄 Actualiser l'analyse » : revérification des seules annonces non validées.

Fixtures en mémoire uniquement : aucun fichier métier réel lu/écrit, aucune sauvegarde Cloud.
Le moteur de reconnaissance (OCR, images) est remplacé par un faux qui applique la vraie
règle d'exclusion des cartes déjà attribuées.
"""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from services import photo_recognition_poc_service as engine
from services import photo_recognition_service as service
from tests.test_photo_recognition_service import _candidate, _photo, _session
from ui.pages import vinted_listings as VL


def _cand(uid, number, *, status="to_photograph", quantity=1):
    return {
        **_candidate(uid, number),
        "drop_card_key": f"lot-1::{uid}",
        "drop_status": status,
        "quantity": quantity,
    }


def _group(index, rows, *, status="review"):
    front = _photo(index * 2 - 1, f"front-{index}.jpg")
    back = _photo(index * 2, f"back-{index}.jpg")
    return {
        "announcement_index": index,
        "grouping_status": "ok",
        "confidence_level": "orange" if status != "recognized" else "green",
        "photos": [
            {"photo": front, "classification": {"class": "primary_front"}},
            {"photo": back, "classification": {"class": "back_western"}},
        ],
        "primary_front": {"photo": front},
        "group_back": {"photo": back, "classification": {"class": "back_western"}},
        "matches": [
            {
                "status": status,
                "score": rows[0][1] if rows else 0,
                "subcard_id": f"physical-{index}",
                "subcard_photos": {"front": f"{index * 2 - 1}:front-{index}.jpg", "back": f"{index * 2}:back-{index}.jpg"},
                "candidates": [{"candidate": candidate, "score": score} for candidate, score in rows],
            }
        ],
    }


A, B, C, D = (_cand("card-a", "1/10"), _cand("card-b", "2/10"),
              _cand("card-c", "3/10", status="online"), _cand("card-d", "4/10"))


def _build():
    """G1 validé sur A · G2 non validé (A puis B) · G3 publié (C en ligne) · G4 non validé (C puis D)."""
    groups = [
        _group(1, [(A, 99)], status="recognized"),
        _group(2, [(A, 90), (B, 80)]),
        _group(3, [(C, 99)], status="recognized"),
        _group(4, [(C, 70), (D, 60)]),
    ]
    result = {
        "analysis_meta": {"drop_id": "drop-1", "pipeline_version": "t", "photo_signature": "p", "candidate_signature": "old"},
        "sample_photos": [photo["photo"] for group in groups for photo in group["photos"]],
        "groups": groups,
        "candidates": [A, B, C, D],
    }
    return result


def fake_recognize(calls):
    def _fake(groups, candidates, **kwargs):
        calls.append({
            "groups": [service.stable_group_id(group) for group in groups],
            "blocked": dict(kwargs.get("blocked_counts") or {}),
            "callback": kwargs.get("progress_callback"),
        })
        cb = kwargs.get("progress_callback")
        total = sum(engine._group_photo_count(group) for group in groups)
        done = 0
        for group in groups:
            if cb:
                cb("reconnaissance", done, total)
            done += engine._group_photo_count(group)
            for match in group["matches"]:
                match["candidates"] = [row for row in match["candidates"]]
                if kwargs.get("blocked_counts"):
                    engine._exclude_exhausted_candidates(match, kwargs["blocked_counts"])
        if cb:
            cb("reconnaissance", total, total)
        return True, "", 0
    return _fake


class ExcludeExhaustedTests(unittest.TestCase):
    def _match(self, *cands):
        return {"status": "recognized", "score": 90, "candidates": [{"candidate": c, "score": 90 - i} for i, c in enumerate(cands)]}

    def test_exhausted_top_is_removed_and_no_longer_recognized(self):
        match = self._match(A, B)
        engine._exclude_exhausted_candidates(match, {A["drop_card_key"]: 1})
        self.assertEqual([r["candidate"]["card_uid"] for r in match["candidates"]], ["card-b"])
        self.assertEqual(match["status"], "review")
        self.assertEqual(match["reuse_excluded"], [A["drop_card_key"]])

    def test_card_with_several_copies_stays_proposed(self):
        twin = _cand("card-a", "1/10", quantity=2)
        match = self._match(twin, B)
        engine._exclude_exhausted_candidates(match, {twin["drop_card_key"]: 1})
        self.assertEqual(len(match["candidates"]), 2)
        self.assertEqual(match["status"], "recognized")
        self.assertNotIn("reuse_excluded", match)

    def test_only_candidate_removed_gives_empty_proposal(self):
        match = self._match(A)
        engine._exclude_exhausted_candidates(match, {A["drop_card_key"]: 1})
        self.assertEqual(match["candidates"], [])
        self.assertEqual(match["score"], 0.0)

    def test_second_ranked_removal_keeps_status(self):
        match = self._match(B, A)
        engine._exclude_exhausted_candidates(match, {A["drop_card_key"]: 1})
        self.assertEqual(match["status"], "recognized")
        self.assertEqual([r["candidate"]["card_uid"] for r in match["candidates"]], ["card-b"])


class ReverifyServiceTests(unittest.TestCase):
    def _run(self, result, session, calls=None, callback=None):
        calls = calls if calls is not None else []
        with patch.object(service.engine, "active_drop_candidates", return_value=({"id": "drop-1"}, result["candidates"])), \
             patch.object(service.engine, "_recognize_groups", side_effect=fake_recognize(calls)), \
             patch.object(service.engine, "_ocr_status", return_value=(True, "")), \
             patch.object(service.engine, "_clear_candidate_derived_group_state"), \
             patch.object(service.engine, "save_cached_analysis_result", return_value={"write_seconds": 0, "size_bytes": 0}), \
             patch.object(service, "save_drop_photo_session", side_effect=lambda value: value), \
             patch.object(service, "reconcile_poc_validations", side_effect=lambda r, s, **kw: (s, {})):
            return service.reverify_unvalidated_groups(result, session, drop_id="drop-1", progress_callback=callback), calls

    def _validated(self, result):
        session = _session()
        group = result["groups"][0]
        with patch.object(service, "save_drop_photo_session", side_effect=lambda value: value):
            service.set_match_validation(session, group, group["matches"][0], 0, "correct")
        return session

    def test_validated_and_published_groups_are_not_touched_and_not_reanalysed(self):
        result = _build()
        session = self._validated(result)
        before = deepcopy(result["groups"])
        before_session = deepcopy(session)
        ((new_result, new_session, report), calls) = self._run(result, session)

        self.assertEqual(report["kept_validated"], 1)
        self.assertEqual(report["kept_published"], 1)
        self.assertEqual(report["rechecked"], 2)
        analysed = {gid for call in calls for gid in call["groups"]}
        self.assertEqual(analysed, {service.stable_group_id(new_result["groups"][1]), service.stable_group_id(new_result["groups"][3])})
        self.assertEqual(new_result["groups"][0], before[0])  # validé : identique
        self.assertEqual(new_result["groups"][2], before[2])  # publié : identique
        self.assertEqual(new_session["validations"], before_session["validations"])
        self.assertEqual(new_session["grouping_confirmations"], before_session["grouping_confirmations"])

    def test_validated_card_is_no_longer_proposed_elsewhere(self):
        result = _build()
        session = self._validated(result)
        (new_result, new_session, report), _calls = self._run(result, session)

        g2 = new_result["groups"][1]["matches"][0]
        self.assertEqual([r["candidate"]["card_uid"] for r in g2["candidates"]], ["card-b"])
        self.assertEqual(g2["status"], "review")
        self.assertEqual(report["excluded"], 2)

    def test_published_card_does_not_block_nor_reenter_review(self):
        result = _build()
        session = self._validated(result)
        (new_result, new_session, report), _calls = self._run(result, session)

        g3 = new_result["groups"][2]
        self.assertEqual(g3["matches"][0]["candidates"][0]["candidate"]["card_uid"], "card-c")
        # la carte publiée est retirée des propositions de G4
        g4 = new_result["groups"][3]["matches"][0]
        self.assertEqual([r["candidate"]["card_uid"] for r in g4["candidates"]], ["card-d"])

    def test_report_text_and_counts(self):
        result = _build()
        session = self._validated(result)
        (new_result, new_session, report), _calls = self._run(result, session)
        self.assertEqual(report["rechecked"], 2)
        self.assertEqual(report["changed"], 2)
        self.assertEqual(
            service.reverify_report_text(report),
            f"2 annonces revérifiées · 2 propositions changées · {report['recognized']} passées en « Reconnu » · "
            f"{report['remaining']} restent à vérifier",
        )

    def test_progress_callback_counts_only_concerned_photos(self):
        result = _build()
        session = self._validated(result)
        seen = []
        self._run(result, session, callback=lambda phase, done, total: seen.append((phase, done, total)))
        self.assertTrue(seen)
        self.assertTrue(all(total == 4 for _p, _d, total in seen))  # 2 annonces x 2 photos
        self.assertEqual(seen[-1], ("reconnaissance", 4, 4))

    def test_nothing_to_recheck_when_everything_is_protected(self):
        result = _build()
        result["groups"] = result["groups"][:3:2]  # G1 validé + G3 publié
        result["candidates"] = [A, C]
        session = self._validated(result)
        (new_result, _s, report), calls = self._run(result, session)
        self.assertEqual(report["rechecked"], 0)
        self.assertEqual(calls, [])


class RebasePassTests(unittest.TestCase):
    def _env(self):
        result = _build()
        session = _session()
        return result, session

    def test_position_is_kept_on_same_group(self):
        result, session = self._env()
        ids = [service.stable_group_id(g) for g in result["groups"]]
        pass_state = {"mode": "review", "group_ids": ids, "position": 2, "visited_group_ids": ids[:2], "completed": False}
        # G1 (avant la position) devient reconnu : il quitte la file, la position suit le même groupe
        with patch.object(VL, "photo_unresolved_groups", return_value=result["groups"][1:]):
            rebased = VL._rebase_review_pass_after_refresh(pass_state, result, session, mode="review")
        self.assertEqual(rebased["group_ids"], ids[1:])
        self.assertEqual(rebased["group_ids"][rebased["position"]], ids[2])

    def test_current_group_leaves_queue_goes_to_next(self):
        result, session = self._env()
        ids = [service.stable_group_id(g) for g in result["groups"]]
        pass_state = {"mode": "review", "group_ids": ids, "position": 1, "visited_group_ids": [], "completed": False}
        with patch.object(VL, "photo_unresolved_groups", return_value=[result["groups"][0], result["groups"][2], result["groups"][3]]):
            rebased = VL._rebase_review_pass_after_refresh(pass_state, result, session, mode="review")
        self.assertEqual(rebased["group_ids"][rebased["position"]], ids[2])
        self.assertNotEqual(rebased["position"], 0)

    def test_newly_unresolved_groups_are_appended_and_reopen_a_completed_pass(self):
        result, session = self._env()
        ids = [service.stable_group_id(g) for g in result["groups"]]
        pass_state = {"mode": "review", "group_ids": ids[:2], "position": 2, "visited_group_ids": ids[:2], "completed": True}
        with patch.object(VL, "photo_unresolved_groups", return_value=[result["groups"][0], result["groups"][3]]):
            rebased = VL._rebase_review_pass_after_refresh(pass_state, result, session, mode="review")
        self.assertEqual(rebased["group_ids"], [ids[0], ids[3]])
        self.assertEqual(rebased["position"], 1)
        self.assertFalse(rebased["completed"])

    def test_all_mode_is_unchanged(self):
        result, session = self._env()
        pass_state = {"mode": "all", "group_ids": ["a", "b"], "position": 1, "completed": False}
        self.assertEqual(VL._rebase_review_pass_after_refresh(pass_state, result, session, mode="all"), pass_state)


class ReverifyHandlerTests(unittest.TestCase):
    """Le gestionnaire du bouton : stocke le résultat, garde la position, écrit le récapitulatif."""

    def test_handler_keeps_queue_position_and_stores_recap(self):
        from streamlit.testing.v1 import AppTest

        def app():
            import streamlit as st
            from unittest.mock import patch
            from tests import test_reverify_unvalidated as T
            from ui.pages import vinted_listings as VL

            result = T._build()
            session = T._session()
            ids = [T.service.stable_group_id(g) for g in result["groups"]]
            drop_id = "drop-1"
            st.session_state[VL._photo_review_pass_key(drop_id)] = {
                "mode": "review", "group_ids": ids, "position": 2, "visited_group_ids": [], "completed": False,
            }
            report = {"rechecked": 2, "changed": 1, "recognized": 1, "remaining": 3}
            with patch.object(VL, "reverify_unvalidated_groups", return_value=(result, session, report)), \
                 patch.object(VL, "photo_unresolved_groups", return_value=result["groups"][1:]):
                VL._run_reverify_unvalidated({}, {"id": drop_id}, result, session, mode="review")
            state = st.session_state[VL._photo_review_pass_key(drop_id)]
            st.session_state["check_position"] = state["group_ids"][state["position"]] == ids[2]
            st.session_state["check_message"] = st.session_state.get(VL._reverify_report_key(drop_id), "")
            st.session_state["check_stored"] = VL._photo_result_key(drop_id) in st.session_state

        at = AppTest.from_function(app).run(timeout=30)
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(at.session_state["check_position"])
        self.assertTrue(at.session_state["check_stored"])
        self.assertEqual(
            at.session_state["check_message"],
            "2 annonces revérifiées · 1 propositions changées · 1 passées en « Reconnu » · 3 restent à vérifier",
        )


if __name__ == "__main__":
    unittest.main()

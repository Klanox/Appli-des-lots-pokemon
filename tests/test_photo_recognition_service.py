from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services.photo_recognition_service import (
    analysis_summary,
    apply_recognition_statuses,
    build_step4_payload,
    current_candidate,
    set_match_validation,
    stable_group_id,
    unresolved_groups,
    validation_for_match,
)
from services.photo_recognition_poc_service import drop_candidate_membership


def _photo(index, name):
    return {
        "path": f"C:/photos/{name}",
        "filename": name,
        "capture_index": index,
        "capture_datetime": "",
        "order_source": "filename",
        "size_bytes": 10,
    }


def _candidate(uid, number):
    return {
        "card_uid": uid,
        "lot_uid": "lot-1",
        "drop_card_key": f"lot-1::{uid}",
        "name": "Carte test",
        "number": number,
        "set": "Set test",
        "japanese": False,
    }


def _result():
    front = _photo(1, "front.jpg")
    back = _photo(2, "back.jpg")
    candidate = _candidate("card-1", "1/10")
    return {
        "analysis_meta": {
            "drop_id": "drop-1",
            "pipeline_version": "test",
            "photo_signature": "photos",
        },
        "sample_photos": [front, back],
        "groups": [
            {
                "announcement_index": 1,
                "grouping_status": "ok",
                "confidence_level": "green",
                "photos": [
                    {"photo": front, "classification": {"class": "primary_front"}},
                    {"photo": back, "classification": {"class": "back_western"}},
                ],
                "primary_front": {"photo": front},
                "group_back": {"photo": back, "classification": {"class": "back_western"}},
                "matches": [
                    {
                        "status": "recognized",
                        "score": 99,
                        "subcard_id": "physical-1",
                        "subcard_photos": {"front": "1:front.jpg", "back": "2:back.jpg"},
                        "candidates": [{"candidate": candidate, "score": 99}],
                    }
                ],
            }
        ],
        "candidates": [candidate],
    }


def _session():
    return {
        "version": "v1",
        "drop_id": "drop-1",
        "validations": {},
        "grouping_confirmations": {},
    }


class PhotoRecognitionServiceTests(unittest.TestCase):
    def test_payload_preserves_physical_order_and_auto_candidate(self):
        result = _result()
        payload = build_step4_payload(result, _session())
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["photo_count"], 2)
        self.assertEqual(payload["listings"][0]["card_uids"], ["card-1"])
        self.assertEqual(
            [photo["role"] for photo in payload["listings"][0]["photos"]],
            ["primary_front", "back_western"],
        )

    def test_manual_candidate_is_bound_to_physical_subcard(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _result()
            group = result["groups"][0]
            match = group["matches"][0]
            replacement = _candidate("card-2", "2/10")
            session = set_match_validation(_session(), group, match, 0, "manual", selected_candidate=replacement)
            payload = build_step4_payload(result, session)
            self.assertEqual(payload["listings"][0]["card_uids"], ["card-2"])
            self.assertEqual(payload["listings"][0]["validation_source"], "manual")
            self.assertIn(stable_group_id(group), next(iter(session["validations"])))

    def test_manual_candidate_resolves_a_previous_fail(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _result()
            group = result["groups"][0]
            match = group["matches"][0]
            match["status"] = "unrecognized"
            match["v13_not_in_drop_confidence"] = "strong"
            replacement = _candidate("card-2", "2/10")
            session = set_match_validation(_session(), group, match, 0, "manual", selected_candidate=replacement)
            payload = build_step4_payload(result, session)
            self.assertTrue(payload["ready"])
            self.assertEqual(payload["listings"][0]["card_uids"], ["card-2"])

    def test_status_updates_never_touch_launched_online_or_sold_items(self):
        result = _result()
        payload = build_step4_payload(result, _session(), require_ready=False)
        drops = {
            "drops": [
                {
                    "id": "drop-1",
                    "drop_launched_at": "2026-01-01T10:00:00",
                    "cards": [
                        {"card_uid": "card-1", "lot_uid": "lot-1", "status": "online"},
                        {"card_uid": "card-2", "lot_uid": "lot-1", "status": "sold", "sold_at": "2026-01-02"},
                    ],
                }
            ]
        }
        before = deepcopy(drops)
        self.assertEqual(apply_recognition_statuses(drops, "drop-1", payload), 0)
        self.assertEqual(drops, before)

    def test_status_updates_sort_matches_and_review_unmatched_items(self):
        payload = build_step4_payload(_result(), _session(), require_ready=False)
        drops = {
            "drops": [
                {
                    "id": "drop-1",
                    "cards": [
                        {"card_uid": "card-1", "lot_uid": "lot-1", "status": "to_photograph"},
                        {"card_uid": "card-2", "lot_uid": "lot-1", "status": "to_photograph"},
                        {"card_uid": "card-3", "lot_uid": "lot-1", "status": "sold", "sold_at": "2026-01-02"},
                    ],
                }
            ]
        }
        self.assertEqual(apply_recognition_statuses(drops, "drop-1", payload), 2)
        statuses = {ref["card_uid"]: ref["status"] for ref in drops["drops"][0]["cards"]}
        self.assertEqual(statuses, {"card-1": "sorted", "card-2": "needs_review", "card-3": "sold"})

    def test_summary_uses_review_queue_without_changing_engine_result(self):
        result = _result()
        result["groups"][0]["matches"][0]["status"] = "review"
        result["groups"][0]["confidence_level"] = "orange"
        summary = analysis_summary(result, _session())
        self.assertEqual(summary["announcements"], 1)
        self.assertEqual(summary["auto"], 0)
        self.assertEqual(summary["review"], 1)
        self.assertEqual(summary["fail"], 0)

    def test_zero_evidence_debug_candidate_is_not_a_proposal(self):
        match = {
            "status": "review",
            "score": 0,
            "margin": 0,
            "candidates": [{"candidate": _candidate("card-jp", "197"), "score": 0}],
        }
        self.assertIsNone(current_candidate(match))
        self.assertEqual(match["candidates"][0]["candidate"]["card_uid"], "card-jp")

    def test_validation_becomes_stale_when_semantic_candidate_changes(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _result()
            group = result["groups"][0]
            match = group["matches"][0]
            session = set_match_validation(_session(), group, match, 0, "correct")
            match["candidates"][0] = {"candidate": _candidate("card-2", "2/10"), "score": 99}
            validation = validation_for_match(session, group, match, 0)
            self.assertEqual(validation["state"], "stale")
            self.assertFalse(validation["compatible"])

    def test_correct_review_leaves_the_review_queue(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _result()
            group = result["groups"][0]
            match = group["matches"][0]
            match["status"] = "review"
            group["confidence_level"] = "orange"
            session = set_match_validation(_session(), group, match, 0, "correct")
            self.assertEqual(unresolved_groups(result, session), [])

    def test_wrong_review_stays_in_the_review_queue(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _result()
            group = result["groups"][0]
            match = group["matches"][0]
            match["status"] = "review"
            group["confidence_level"] = "orange"
            session = set_match_validation(_session(), group, match, 0, "wrong")
            self.assertEqual(unresolved_groups(result, session), [group])

    def test_drop_membership_prefers_uid_then_strict_fingerprint(self):
        card = _candidate("card-1", "1/10")
        self.assertEqual(drop_candidate_membership(card, [card]), {"in_drop": True, "method": "card_uid"})

        legacy_card = {**card, "card_uid": "legacy-card"}
        self.assertEqual(
            drop_candidate_membership(legacy_card, [{**card, "card_uid": "card-2"}]),
            {"in_drop": True, "method": "identity_fingerprint"},
        )

        same_name_other_identity = {**card, "card_uid": "card-3", "number": "2/10"}
        self.assertEqual(
            drop_candidate_membership(same_name_other_identity, [card]),
            {"in_drop": False, "method": ""},
        )


if __name__ == "__main__":
    unittest.main()

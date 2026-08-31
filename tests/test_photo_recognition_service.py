from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services.photo_recognition_service import (
    analysis_summary,
    apply_recognition_statuses,
    build_step4_payload,
    confirm_grouping,
    current_candidate,
    grouping_is_confirmed,
    grouping_needs_confirmation,
    grouping_is_structurally_evident,
    group_review_reasons,
    next_pending_subcard_index,
    normalize_photo_identity,
    reconcile_poc_validations,
    set_match_validation,
    stable_group_id,
    stable_subcard_id,
    unresolved_groups,
    validation_for_match,
)
from services.photo_recognition_poc_service import drop_candidate_membership


@dataclass(frozen=True)
class LegacyPhotoInfo:
    """Shape retained by a cache created before a Streamlit module reload."""

    path: str
    filename: str
    capture_index: int
    capture_datetime: str = ""
    order_source: str = ""
    size_bytes: int = 0


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


def _multi_result(count=2):
    result = _result()
    group = result["groups"][0]
    group["confidence_level"] = "orange"
    group["matches"] = [
        {
            "status": "review",
            "score": 80,
            "subcard_id": f"physical-{index}",
            "subcard_photos": {
                "front": f"{index}:front-{index}.jpg",
                "back": f"{index}:back-{index}.jpg",
            },
            "candidates": [{"candidate": _candidate(f"card-{index}", f"{index}/90"), "score": 80}],
        }
        for index in range(1, count + 1)
    ]
    result["candidates"] = [row["candidates"][0]["candidate"] for row in group["matches"]]
    return result


def _legend_result():
    """Regression fixture copied from the physical Rayquaza & Deoxys listing."""
    result = _multi_result(2)
    group = result["groups"][0]
    group["announcement_index"] = 6
    group["ground_truth_group_id"] = "group_11_15_f2f7fabc9cfb"
    group["grouping_status"] = "review"
    group["layout_type"] = "LEGEND_HALF"
    group["matches"] = [
        {
            "status": "review",
            "score": 87,
            "subcard_id": "subcard_9f1d1a6816d0e16f",
            "subcard_photos": {"front": "12:rayquaza-89-front.jpg", "back": "13:rayquaza-89-back.jpg"},
            "layout_type": "LEGEND_HALF",
            "candidates": [{"candidate": {**_candidate("card-legend-89", "89/90"), "name": "Rayquaza & Deoxys LEGENDE"}, "score": 87}],
        },
        {
            "status": "recognized",
            "score": 90,
            "subcard_id": "subcard_12730b3d0b5ab101",
            "subcard_photos": {"front": "14:rayquaza-90-front.jpg", "back": "15:rayquaza-90-back.jpg"},
            "layout_type": "LEGEND_HALF",
            "candidates": [{"candidate": {**_candidate("card-legend-90", "90/90"), "name": "Rayquaza & Deoxys LEGENDE"}, "score": 90}],
        },
    ]
    result["candidates"] = [row["candidates"][0]["candidate"] for row in group["matches"]]
    return result


def _v_union_result():
    """Regression fixture copied from the first physical Morpeko V-UNION group."""
    result = _multi_result(4)
    group = result["groups"][0]
    group["announcement_index"] = 36
    group["ground_truth_group_id"] = "group_74_82_a4d828d7cfb8"
    group["grouping_status"] = "review"
    group["layout_type"] = "V_UNION"
    physical_ids = [
        "subcard_31411cb91075a46c",
        "subcard_48996d751e0e549e",
        "subcard_d2f7acd04c4f23b0",
        "subcard_6be0903a39adf606",
    ]
    for index, match in enumerate(group["matches"]):
        number = f"SWSH{287 + index}"
        match["subcard_id"] = physical_ids[index]
        match["status"] = "review" if index == 0 else "recognized"
        match["layout_type"] = "V_UNION"
        match["candidates"] = [{
            "candidate": {**_candidate(f"card-morpeko-{number}", number), "name": "Morpeko V-UNION"},
            "score": 92,
        }]
    result["candidates"] = [row["candidates"][0]["candidate"] for row in group["matches"]]
    return result


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

    def test_normalize_photo_identity_accepts_current_mapping_and_legacy_shapes(self):
        from services.photo_recognition_service import PhotoInfo

        current = PhotoInfo("C:/photos/current.jpg", "current.jpg", 1, "", "filename", 10)
        legacy = LegacyPhotoInfo("C:/photos/legacy.jpg", "legacy.jpg", 2)
        mapped = {"path": "C:/photos/mapped.jpg", "filename": "mapped.jpg", "capture_index": 3}

        self.assertEqual(normalize_photo_identity(current), {"filename": "current.jpg", "capture_index": 1})
        self.assertEqual(normalize_photo_identity(legacy), {"filename": "legacy.jpg", "capture_index": 2})
        self.assertEqual(normalize_photo_identity(mapped), mapped)
        with self.assertRaises(TypeError):
            dict(current)

    def test_payload_accepts_legacy_photo_info_without_dict_conversion(self):
        result = _result()
        group = result["groups"][0]
        front = LegacyPhotoInfo("C:/photos/front.jpg", "front.jpg", 1)
        back = LegacyPhotoInfo("C:/photos/back.jpg", "back.jpg", 2)
        group["photos"][0]["photo"] = front
        group["photos"][1]["photo"] = back
        group["primary_front"]["photo"] = front
        group["group_back"]["photo"] = back
        payload = build_step4_payload(result, _session())
        self.assertEqual(payload["photo_count"], 2)
        self.assertEqual([photo["filename"] for photo in payload["listings"][0]["photos"]], ["front.jpg", "back.jpg"])

    def test_payload_preserves_multiple_subcards(self):
        result = _result()
        group = result["groups"][0]
        group["matches"].append(
            {
                "status": "recognized",
                "score": 98,
                "subcard_id": "physical-2",
                "subcard_photos": {"front": "1:front.jpg", "back": "2:back.jpg"},
                "candidates": [{"candidate": _candidate("card-2", "2/10"), "score": 98}],
            }
        )
        self.assertFalse(build_step4_payload(result, _session())["ready"])
        session = _session()
        for index, match in enumerate(group["matches"]):
            session = set_match_validation(session, group, match, index, "correct")
        payload = build_step4_payload(result, session)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["listings"][0]["card_uids"], ["card-1", "card-2"])
        self.assertEqual(payload["photo_count"], 2)

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

    def test_multi_card_advances_to_the_next_physical_subcard_before_leaving_group(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _multi_result(2)
            group = result["groups"][0]
            first, second = group["matches"]
            session = set_match_validation(_session(), group, first, 0, "correct")
            seen = {f"{stable_group_id(group)}:physical-1"}

            self.assertEqual(next_pending_subcard_index(session, group, 0, seen), 1)
            self.assertEqual(unresolved_groups(result, session), [group])

            session = set_match_validation(session, group, second, 1, "correct")
            seen.add(f"{stable_group_id(group)}:physical-2")
            self.assertIsNone(next_pending_subcard_index(session, group, 1, seen))
            self.assertEqual(unresolved_groups(result, session), [])

    def test_multi_card_wrong_remains_unresolved_after_other_subcards_are_visited(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _multi_result(2)
            group = result["groups"][0]
            first, second = group["matches"]
            session = set_match_validation(_session(), group, first, 0, "correct")
            session = set_match_validation(session, group, second, 1, "wrong")
            seen = {f"{stable_group_id(group)}:physical-1", f"{stable_group_id(group)}:physical-2"}

            self.assertEqual(next_pending_subcard_index(session, group, 1, seen), 1)
            self.assertEqual(unresolved_groups(result, session), [group])

    def test_v_union_navigation_only_completes_after_four_physical_subcards(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _multi_result(4)
            group = result["groups"][0]
            session = _session()
            seen = set()
            for index, match in enumerate(group["matches"]):
                session = set_match_validation(session, group, match, index, "correct")
                seen.add(f"{stable_group_id(group)}:physical-{index + 1}")
                expected = index + 1 if index < 3 else None
                self.assertEqual(next_pending_subcard_index(session, group, index, seen), expected)

            self.assertEqual(unresolved_groups(result, session), [])

    def test_three_card_multi_requires_each_physical_subcard_before_advancing(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _multi_result(3)
            group = result["groups"][0]
            # This mirrors the real three-card listing: only the first card is
            # initially in review, while the other two were auto-recognized.
            group["matches"][1]["status"] = "recognized"
            group["matches"][2]["status"] = "recognized"
            session = _session()
            seen = set()

            for index, match in enumerate(group["matches"]):
                session = set_match_validation(session, group, match, index, "correct")
                seen.add(f"{stable_group_id(group)}:{stable_subcard_id(match, index)}")
                expected = index + 1 if index < 2 else None
                self.assertEqual(next_pending_subcard_index(session, group, index, seen), expected)

    def test_auto_recognized_multi_stays_in_review_until_every_subcard_is_accepted(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _multi_result(3)
            group = result["groups"][0]
            for match in group["matches"]:
                match["status"] = "recognized"
            session = _session()

            self.assertIn("multi", group_review_reasons(session, group))
            for index, match in enumerate(group["matches"]):
                session = set_match_validation(session, group, match, index, "correct")
            self.assertNotIn("multi", group_review_reasons(session, group))

    def test_three_card_multi_stays_open_when_one_physical_subcard_is_wrong(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _multi_result(3)
            group = result["groups"][0]
            first, second, third = group["matches"]
            session = set_match_validation(_session(), group, first, 0, "correct")
            session = set_match_validation(session, group, second, 1, "wrong")
            session = set_match_validation(session, group, third, 2, "correct")
            seen = {
                f"{stable_group_id(group)}:{stable_subcard_id(first, 0)}",
                f"{stable_group_id(group)}:{stable_subcard_id(second, 1)}",
                f"{stable_group_id(group)}:{stable_subcard_id(third, 2)}",
            }

            self.assertEqual(next_pending_subcard_index(session, group, 2, seen), 1)
            self.assertEqual(unresolved_groups(result, session), [group])

    def test_real_legend_halves_stay_on_the_same_group_until_both_are_validated(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _legend_result()
            group = result["groups"][0]
            half_89, half_90 = group["matches"]
            session = set_match_validation(_session(), group, half_89, 0, "correct")
            seen = {f"{stable_group_id(group)}:{stable_subcard_id(half_89, 0)}"}

            self.assertEqual(stable_subcard_id(half_89, 0), "subcard_9f1d1a6816d0e16f")
            self.assertEqual(stable_subcard_id(half_90, 1), "subcard_12730b3d0b5ab101")
            self.assertEqual(next_pending_subcard_index(session, group, 0, seen), 1)
            self.assertIn("multi", group_review_reasons(session, group))

            session = set_match_validation(session, group, half_90, 1, "correct")
            seen.add(f"{stable_group_id(group)}:{stable_subcard_id(half_90, 1)}")
            self.assertIsNone(next_pending_subcard_index(session, group, 1, seen))
            self.assertTrue(grouping_needs_confirmation(session, group))
            self.assertIn("grouping", group_review_reasons(session, group))

            session = confirm_grouping(session, group)
            self.assertTrue(grouping_is_confirmed(session, group))
            self.assertFalse(grouping_needs_confirmation(session, group))
            self.assertEqual(group_review_reasons(session, group), [])

    def test_grouping_review_blocks_a_three_card_multi_after_every_card_is_validated(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _multi_result(3)
            group = result["groups"][0]
            group["grouping_status"] = "review"
            session = _session()
            seen = set()
            for index, match in enumerate(group["matches"]):
                session = set_match_validation(session, group, match, index, "correct")
                seen.add(f"{stable_group_id(group)}:{stable_subcard_id(match, index)}")

            self.assertIsNone(next_pending_subcard_index(session, group, 2, seen))
            self.assertTrue(grouping_needs_confirmation(session, group))
            self.assertEqual(group_review_reasons(session, group), ["grouping"])

    def test_multi_without_grouping_review_advances_when_every_card_is_validated(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _multi_result(2)
            group = result["groups"][0]
            session = _session()
            seen = set()
            for index, match in enumerate(group["matches"]):
                session = set_match_validation(session, group, match, index, "correct")
                seen.add(f"{stable_group_id(group)}:{stable_subcard_id(match, index)}")

            self.assertIsNone(next_pending_subcard_index(session, group, 1, seen))
            self.assertFalse(grouping_needs_confirmation(session, group))
            self.assertEqual(group_review_reasons(session, group), [])

    def test_single_grouping_review_stays_unresolved_after_its_card_is_validated(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _result()
            group = result["groups"][0]
            group["grouping_status"] = "review"
            group["photos"][0]["classification"]["class"] = "unknown"
            group["grouping_reasons"] = ["segmentation ambigue"]
            match = group["matches"][0]
            session = set_match_validation(_session(), group, match, 0, "correct")

            self.assertTrue(grouping_needs_confirmation(session, group))
            self.assertEqual(group_review_reasons(session, group), ["grouping"])

    def test_grouping_confirmation_survives_a_result_rerun_with_the_same_group_id(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _legend_result()
            group = result["groups"][0]
            session = confirm_grouping(_session(), group)
            reloaded_group = deepcopy(group)

            self.assertEqual(stable_group_id(reloaded_group), stable_group_id(group))
            self.assertTrue(grouping_is_confirmed(session, reloaded_group))

    def test_clean_single_front_back_review_is_auto_confirmed_for_grouping(self):
        result = _result()
        group = result["groups"][0]
        group["grouping_status"] = "review"
        group["grouping_reasons"] = [
            "segmentation V12 front/back",
            "longue pause dans la paire (68s)",
            "paire suivante temporellement plus probable",
            "confiance de segmentation insuffisante pour validation automatique",
        ]

        self.assertTrue(grouping_is_structurally_evident(group))
        self.assertFalse(grouping_needs_confirmation(_session(), group))
        self.assertNotIn("grouping", group_review_reasons(_session(), group))

    def test_ambiguous_single_grouping_review_is_not_auto_confirmed(self):
        result = _result()
        group = result["groups"][0]
        group["grouping_status"] = "review"
        group["photos"][0]["classification"]["class"] = "unknown"
        group["grouping_reasons"] = ["segmentation ambigue"]

        self.assertFalse(grouping_is_structurally_evident(group))
        self.assertTrue(grouping_needs_confirmation(_session(), group))

    def test_single_pair_with_a_false_back_label_is_auto_confirmed(self):
        result = _result()
        group = result["groups"][0]
        group["grouping_status"] = "review"
        group["photos"][0]["classification"]["class"] = "back_western"
        group["grouping_reasons"] = [
            "premiere photo fortement back-like",
            "faux back probable sur le recto",
            "confiance de segmentation insuffisante pour validation automatique",
        ]

        self.assertTrue(grouping_is_structurally_evident(group))
        self.assertFalse(grouping_needs_confirmation(_session(), group))

    def test_legend_and_v_union_grouping_reviews_are_never_auto_confirmed(self):
        self.assertFalse(grouping_is_structurally_evident(_legend_result()["groups"][0]))
        self.assertFalse(grouping_is_structurally_evident(_v_union_result()["groups"][0]))

    def test_multi_validation_never_counts_a_record_from_another_physical_subcard(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _legend_result()
            group = result["groups"][0]
            half_89, half_90 = group["matches"]
            session = set_match_validation(_session(), group, half_89, 0, "correct")
            first_key = f"{stable_group_id(group)}:{stable_subcard_id(half_89, 0)}"
            second_key = f"{stable_group_id(group)}:{stable_subcard_id(half_90, 1)}"
            session["validations"][second_key] = {
                **session["validations"][first_key],
                "subcard_id": stable_subcard_id(half_89, 0),
                "proposal_signature": service.proposal_signature(
                    half_90,
                    service.current_candidate(half_90),
                ),
            }

            self.assertTrue(validation_for_match(session, group, half_90, 1)["compatible"])
            self.assertEqual(service.pending_review_subcard_indexes(session, group), [1])

    def test_real_v_union_stays_on_each_of_its_four_physical_subcards(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _v_union_result()
            group = result["groups"][0]
            session = _session()
            seen = set()

            for index, match in enumerate(group["matches"]):
                session = set_match_validation(session, group, match, index, "correct")
                seen.add(f"{stable_group_id(group)}:{stable_subcard_id(match, index)}")
                expected = index + 1 if index < 3 else None
                self.assertEqual(next_pending_subcard_index(session, group, index, seen), expected)

    def test_validation_stays_with_the_physical_subcard_when_multi_order_changes(self):
        from services import photo_recognition_service as service

        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            result = _multi_result(2)
            group = result["groups"][0]
            first, second = group["matches"]
            session = set_match_validation(_session(), group, first, 0, "correct")
            group["matches"] = [second, first]

            validation = validation_for_match(session, group, group["matches"][1], 1)
            self.assertEqual(validation["state"], "correct")
            self.assertTrue(validation["compatible"])

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

    def test_compatible_poc_validation_is_imported_by_physical_subcard(self):
        from services import photo_recognition_service as service

        result = _result()
        group = result["groups"][0]
        match = group["matches"][0]
        semantic = service._poc_semantic_proposal(match)
        ground_truth = {
            "samples": {
                "photos|drop=drop-1|start=1|photos=2|target=2": {
                    "groups": [
                        {
                            "group_id": stable_group_id(group),
                            "semantic_subcard_ids": ["physical-1"],
                            "recognition_validation": {
                                "physical-1": {
                                    "status": "correct",
                                    "subcard_photos": dict(match["subcard_photos"]),
                                    "semantic_proposal": semantic,
                                    "validated_at": "2026-01-01T10:00:00",
                                }
                            },
                        }
                    ]
                }
            }
        }
        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)), patch.object(
            service, "load_poc_ground_truth", return_value=ground_truth
        ):
            session, metrics = reconcile_poc_validations(
                result,
                _session(),
                folder="C:/photos",
                drop_id="drop-1",
            )
        validation = validation_for_match(session, group, match, 0)
        self.assertEqual(metrics["imported"], 1)
        self.assertEqual(validation["state"], "correct")
        self.assertEqual(validation["source"], "poc_ground_truth")

    def test_changed_poc_candidate_is_not_imported(self):
        from services import photo_recognition_service as service

        result = _result()
        group = result["groups"][0]
        match = group["matches"][0]
        stale_semantic = {**service._poc_semantic_proposal(match), "candidate_card_uid": "old-card"}
        ground_truth = {
            "samples": {
                "photos|drop=drop-1|start=1|photos=2|target=2": {
                    "groups": [
                        {
                            "group_id": stable_group_id(group),
                            "semantic_subcard_ids": ["physical-1"],
                            "recognition_validation": {
                                "physical-1": {
                                    "status": "wrong",
                                    "subcard_photos": dict(match["subcard_photos"]),
                                    "semantic_proposal": stale_semantic,
                                }
                            },
                        }
                    ]
                }
            }
        }
        with patch.object(service, "load_poc_ground_truth", return_value=ground_truth):
            session, metrics = reconcile_poc_validations(
                result,
                _session(),
                folder="C:/photos",
                drop_id="drop-1",
            )
        self.assertEqual(metrics["imported"], 0)
        self.assertEqual(metrics["stale"], 1)
        self.assertEqual(validation_for_match(session, group, match, 0)["state"], "unvalidated")


if __name__ == "__main__":
    unittest.main()

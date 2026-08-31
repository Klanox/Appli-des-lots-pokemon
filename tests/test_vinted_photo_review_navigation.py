from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services import photo_recognition_service as service
from services.photo_recognition_service import set_match_validation
from tests.test_photo_recognition_service import _result, _session
from ui.pages.vinted_listings import (
    _advanced_photo_review_pass,
    _new_photo_review_pass,
    _review_pass_remaining_group_ids,
)


def _review_groups(count=5):
    groups = []
    for index in range(count):
        group = deepcopy(_result()["groups"][0])
        group["ground_truth_group_id"] = f"review-group-{index + 1}"
        group["announcement_index"] = index + 1
        group["confidence_level"] = "orange"
        group["matches"][0]["status"] = "review"
        groups.append(group)
    return {"groups": groups}, groups


class VintedPhotoReviewNavigationTests(unittest.TestCase):
    def test_completed_pass_never_wraps_to_its_first_group(self):
        result, groups = _review_groups()
        state = _new_photo_review_pass(groups)

        for expected_position in range(1, 5):
            state = _advanced_photo_review_pass(state)
            self.assertEqual(state["position"], expected_position)
            self.assertFalse(state["completed"])

        state = _advanced_photo_review_pass(state)
        self.assertEqual(state["position"], 5)
        self.assertTrue(state["completed"])
        self.assertNotIn(state["position"], range(5))

    def test_five_correct_cases_finish_with_no_remaining_case(self):
        result, groups = _review_groups()
        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            session = _session()
            for group in groups:
                session = set_match_validation(session, group, group["matches"][0], 0, "correct")

            pass_state = _new_photo_review_pass(groups)
            for _ in groups:
                pass_state = _advanced_photo_review_pass(pass_state)

            self.assertTrue(pass_state["completed"])
            self.assertEqual(_review_pass_remaining_group_ids(pass_state, result, session), [])

    def test_completed_pass_reports_only_the_wrong_cases_as_remaining(self):
        result, groups = _review_groups()
        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            session = _session()
            for index, group in enumerate(groups):
                match = group["matches"][0]
                state = "wrong" if index in {1, 4} else "correct"
                session = set_match_validation(session, group, match, 0, state)

            pass_state = _new_photo_review_pass(groups)
            for _ in groups:
                pass_state = _advanced_photo_review_pass(pass_state)

            self.assertTrue(pass_state["completed"])
            self.assertEqual(
                _review_pass_remaining_group_ids(pass_state, result, session),
                ["review-group-2", "review-group-5"],
            )

    def test_retry_starts_a_new_pass_with_only_remaining_group_ids(self):
        result, groups = _review_groups()
        with TemporaryDirectory() as directory, patch.object(service, "PRODUCTION_CACHE_DIR", Path(directory)):
            session = _session()
            for index, group in enumerate(groups):
                match = group["matches"][0]
                session = set_match_validation(session, group, match, 0, "wrong" if index in {0, 3} else "correct")

            completed_state = {**_new_photo_review_pass(groups), "position": 5, "completed": True}
            remaining_ids = _review_pass_remaining_group_ids(completed_state, result, session)
            retry_groups = [group for group in groups if group["ground_truth_group_id"] in remaining_ids]
            retry_state = _new_photo_review_pass(retry_groups)

            self.assertEqual(retry_state["group_ids"], remaining_ids)
            self.assertEqual(retry_state["position"], 0)
            self.assertFalse(retry_state["completed"])


if __name__ == "__main__":
    unittest.main()

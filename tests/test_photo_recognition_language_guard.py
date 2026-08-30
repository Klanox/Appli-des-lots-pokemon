from __future__ import annotations

import unittest
from unittest.mock import patch

from services import photo_recognition_poc_service as engine


def _candidate(uid, name, number, japanese):
    return {
        "card_uid": uid,
        "lot_uid": "lot-1",
        "drop_card_key": f"lot-1::{uid}",
        "name": name,
        "number": number,
        "set": "Indomptable" if not japanese else "",
        "japanese": japanese,
        "quantity": 1,
    }


class PhotoRecognitionLanguageGuardTests(unittest.TestCase):
    def test_physical_japanese_card_rejects_french_number_collision(self):
        french_legend = _candidate("legend-fr", "Rayquaza & Deoxys LÉGENDE", "89/90", False)
        japanese_card = _candidate("roublenard-jp", "Roublenard", "092", True)
        ocr = {
            "raw_text": "ポケモンカードゲーム ソード シールド 089/081",
            "name_texts": [],
            "number_texts": ["089", "089/081"],
            "collector_number_texts": ["089/081"],
        }

        def visual_scores(_path, scored, **_kwargs):
            for row in scored:
                if row["candidate"]["card_uid"] == "roublenard-jp":
                    row["visual_artwork_score"] = 55.27
                    row["visual_artwork_details"] = {"orb_matches": 13}
                else:
                    row["visual_artwork_score"] = 57.23
                    row["visual_artwork_details"] = {"orb_matches": 2}
            return {"used": 2, "elapsed": 0.001, "broad": True}

        with patch.object(engine, "_apply_visual_shortlist_scores", side_effect=visual_scores):
            match = engine.match_front_photo_ocr(
                "unused.jpg",
                [french_legend, japanese_card],
                back_type="western",
                ocr_payload_override=ocr,
            )

        proposed = engine.proposed_candidate(match)
        self.assertEqual(proposed["card_uid"], "roublenard-jp")
        self.assertEqual(match["status"], "review")
        self.assertTrue(match["v16_physical_japanese_signal"]["strong"])
        legend_row = next(row for row in match["candidates"] if row["candidate"]["card_uid"] == "legend-fr")
        self.assertTrue(legend_row["language_conflict"])
        self.assertLess(legend_row["score"], 54)

    def test_language_bonus_alone_never_creates_a_proposal(self):
        japanese_card = _candidate("jp-only", "Charisme De Giovanni", "197", True)
        ocr = {
            "raw_text": "ポケモンカードゲーム テスト 089/081",
            "name_texts": [],
            "number_texts": ["089/081"],
            "collector_number_texts": ["089/081"],
        }
        match = engine.match_front_photo_ocr(
            "unused.jpg",
            [japanese_card],
            back_type="western",
            ocr_payload_override=ocr,
        )
        self.assertIsNone(engine.proposed_candidate(match))
        self.assertEqual(match["status"], "unrecognized")
        self.assertFalse(match["proposal_reliable"])


if __name__ == "__main__":
    unittest.main()

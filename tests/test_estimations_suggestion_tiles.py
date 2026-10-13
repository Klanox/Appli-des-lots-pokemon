"""Suggestions de la recherche de carte : une tuile par suggestion fournie (aucune limite d'affichage ajoutée par le design)."""
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

from test_estimations_japanese_mode import APP, FR_CARD
from ui.pages import estimations


def _suggestions(n):
    out = []
    for i in range(n):
        card = {**FR_CARD, "name": f"Carte {i}", "number": str(100 + i)}
        out.append({"card": card, "match": (card, FR_CARD["set"])})
    return out


class SuggestionTilesTest(unittest.TestCase):
    def _run(self, n, sections=None):
        fake = lambda *a, **k: _suggestions(n)
        patches = [
            mock.patch.object(estimations, "_card_suggestions", fake),
            mock.patch.object(estimations, "save_market_price_cache", mock.Mock()),
            mock.patch.object(estimations, "st_keyup", lambda label, value="", key=None, **k: __import__("streamlit").text_input(label, value=value, key=key)),
            mock.patch.object(estimations, "render_lot_image_upload_bridge", lambda key=None: None),
            mock.patch.object(estimations, "_manual_estimation_image_dir", lambda: "/nonexistent-never-written"),
        ]
        if sections:
            patches.append(mock.patch.object(estimations, "_strict_suggestion_sections", lambda q, s, n_: (s[:sections[0]], s[sections[0]:], ["ar"])))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        at = AppTest.from_string(APP, default_timeout=30)
        at.run()
        next(t for t in at.text_input if "Rechercher" in t.label).set_value("Carte").run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        return at

    def test_tile_count_equals_suggestion_count(self):
        at = self._run(12)
        picks = [b for b in at.button if b.key and b.key.startswith("est_suggestion_pick_e1_")]
        self.assertEqual(len(picks), 12)
        self.assertEqual(len({b.key for b in picks}), 12)

    def test_with_close_results_section_all_tiles_and_unique_keys(self):
        at = self._run(12, sections=(7,))
        picks = [b.key for b in at.button if b.key and b.key.startswith("est_suggestion_pick_e1_")]
        self.assertEqual(len(picks), 12)
        self.assertEqual(len(set(picks)), 12)
        self.assertIn("Résultats proches", " | ".join(c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()

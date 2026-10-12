"""Régression : grille « Cartes suivies » (Estimations) étirée selon le nombre de cartes.

Cause : les règles partagées de app.py étaient imbriquées dans un @media mobile, donc absentes
sur desktop (cartes en flex 1 1 128px). La grille a maintenant sa clé et son CSS dédiés.
Contrôle logique ; la mise en page réelle est validée à part dans Chromium.
"""
import inspect
import re
import unittest
from pathlib import Path

from ui.pages import estimations

ROOT = Path(__file__).resolve().parents[1]


class TrackedGridCssTest(unittest.TestCase):
    def test_css_is_balanced_and_fixed_width_wrapping_8_per_row(self):
        css = estimations._TRACKED_GRID_CSS
        # Accolades équilibrées : un @media non fermé avait avalé les règles de la grille partagée.
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn("flex-wrap:wrap", css)
        self.assertNotIn("auto-fit", css)
        self.assertNotIn("1fr", css)
        # Colonne = part fixe de la ligne (flex 0 0, jamais 1 1) : 8 par rangée par défaut.
        self.assertRegex(css, r"flex:0 0 calc\(\(100% - 7 \* [^)]+\) / 8\)")
        self.assertNotRegex(css, r"flex:\s*1\b")
        # Mobile : 2 par rangée.
        mobile = css[css.index("@media (max-width:768px)"):]
        self.assertIn("/ 2)", mobile)

    def test_only_tracked_grid_uses_the_dedicated_key(self):
        source = inspect.getsource(estimations)
        self.assertIn('key=f"est_tracked_grid_{uid}"', source)
        self.assertNotIn('key=f"search_results_grid_estimations_{uid}"', source)
        # Les grilles partagées gardent leur clé (aucun effet de bord ailleurs).
        self.assertIn('key=f"search_results_grid_estimations_choice_{uid}"', source)
        for page in ("home.py", "collection.py", "sales.py"):
            self.assertIn("search_results_grid_", (ROOT / "ui" / "pages" / page).read_text(encoding="utf-8"))
        self.assertNotIn("est_tracked_grid_", (ROOT / "app.py").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()

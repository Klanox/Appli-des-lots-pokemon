from pathlib import Path
import unittest

from ui.theme import inject_theme, render_app_header


class GlobalHeaderTests(unittest.TestCase):
    def test_header_keeps_the_brand_content_in_both_layouts(self):
        desktop = render_app_header("logo.png")
        mobile = render_app_header("logo.png", mobile=True)
        for markup in (desktop, mobile):
            self.assertIn('alt="PokéStock"', markup)
            self.assertIn('class="ps-app-title">PokéStock', markup)
            self.assertIn("Collection, lots et ventes sous contrôle", markup)
        self.assertNotIn("ps-app-header--compact", desktop)
        self.assertIn("ps-app-header--compact", mobile)

    def test_compact_header_spacing_is_defined_once_in_the_global_theme(self):
        css = inject_theme()
        self.assertIn('[data-testid="stMainBlockContainer"] {\n    padding-top: 2.5rem !important;', css)
        self.assertIn("padding-top: 2.5rem !important", css)
        self.assertIn("padding: 0.5rem 0.9rem !important", css)
        self.assertIn("margin-bottom: 0.9rem !important", css)
        self.assertIn("width: 44px !important", css)
        self.assertIn(".ps-app-header--compact", css)
        self.assertIn("width: 36px !important", css)

    def test_step4_focus_still_skips_the_global_header_and_uses_its_own_spacing(self):
        root = Path(__file__).resolve().parents[1]
        app_source = (root / "app.py").read_text(encoding="utf-8")
        focus_source = (root / "ui" / "pages" / "vinted_listings.py").read_text(encoding="utf-8")
        self.assertIn("and not step4_focus_active:", app_source)
        self.assertIn("render_app_header(logo_src", app_source)
        self.assertIn("[data-testid='stMainBlockContainer']{padding-top:.55rem !important;}", focus_source)


if __name__ == "__main__":
    unittest.main()

"""Badge « Extension manquante » dans l'ecran de creation et l'apercu des annonces (AppTest, fixtures)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def workspace_script():
    import os
    import sys

    sys.path.insert(0, os.environ["EXT_ROOT"])
    import streamlit as st
    from ui.pages import vinted_listings as vl
    import data as data_module
    from services import vinted_drops_service as drops_service

    # Jamais de donnees reelles ni de Cloud dans les tests : le raccourci lit/ecrit via ces fonctions factices.
    data_module.ld = lambda: {"lots": [{"nom": "Lot", "lot_uid": "lot_1", "cards": []}]}
    data_module.sd = lambda d: None
    drops_service.load_vinted_drops = lambda: {"drops": []}
    drops_service.save_vinted_drops = lambda d: None

    read_only = os.environ.get("EXT_READ_ONLY") == "1"
    ext_name = os.environ.get("EXT_SET", "")
    card = {"card_uid": "card_1", "lot_uid": "lot_1", "name": "Sorcilence VMAX", "number": "066", "set": ext_name, "id": "swsh12.5-066", "lang": "fr"}
    listing = {"recognition_group_id": "g1", "cards": [{"card_uid": "card_1", "candidate": card}], "photos": [], "primary_front": {}}
    payload = {"listings": [listing], "photo_signature": "s", "pipeline_version": "v"}
    active_drop = {"id": "drop1", "cards": []}
    vl._render_recognition_listing_workspace(
        active_drop, payload, listing, [card], lambda body, height=0: None, False, read_only=read_only, fp_func=lambda v: f"{v}€",
    )


class BadgeTests(unittest.TestCase):
    def run_ws(self, *, read_only, ext_name):
        os.environ.update({"EXT_ROOT": str(ROOT), "EXT_READ_ONLY": "1" if read_only else "0", "EXT_SET": ext_name})
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("EXT_ROOT", "EXT_READ_ONLY", "EXT_SET")])
        at = AppTest.from_function(workspace_script, default_timeout=30)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def html(self, at):
        return " ".join(m.value for m in at.markdown)

    def test_creation_screen_shows_red_badge_and_shortcut_when_extension_missing(self):
        at = self.run_ws(read_only=False, ext_name="")
        html = self.html(at)
        self.assertIn("ps-ext-missing-badge", html)
        self.assertIn("Extension manquante", html)
        self.assertNotIn("Extension N/A", html)
        popovers = at.get("popover")
        self.assertEqual(len(popovers), 1, "raccourci « Choisir l'extension » present")
        self.assertEqual(popovers[0].proto.popover.label, "Choisir l'extension")
        self.assertTrue(any(b.label == "Enregistrer l'extension" for b in at.button), "selecteur dans le raccourci")
        self.assertTrue(any("Carte Pokémon - Sorcilence VMAX 066/159 - FR" == t.value for t in at.text_input), [t.value for t in at.text_input])

    def test_preview_shows_badge_without_shortcut(self):
        at = self.run_ws(read_only=True, ext_name="")
        self.assertIn("Extension manquante", self.html(at))
        self.assertEqual(len(at.get("popover")), 0, "pas de raccourci dans l'apercu (lecture seule)")

    def test_no_badge_when_extension_present(self):
        at = self.run_ws(read_only=False, ext_name="Zénith Suprême")
        html = self.html(at)
        self.assertNotIn("Extension manquante", html)
        self.assertIn("Zénith Suprême", html)
        self.assertEqual(len(at.get("popover")), 0)


if __name__ == "__main__":
    unittest.main()

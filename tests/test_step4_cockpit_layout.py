"""Etape 4 « Creation des annonces » en une page (mise en page « cockpit »).

Mise en page uniquement : memes widgets, memes cles, memes comportements que l'affichage classique
(celui du mode mobile). Fixtures temporaires, aucun fichier metier, aucun envoi au Cloud.
"""

from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from ui.pages import vinted_listings as VL

LAUNCHED = "2026-08-27T17:27:35"


def _ref(item_id, status, *, draft=""):
    return {
        "drop_item_id": item_id, "card_uid": f"card-{item_id}", "lot_uid": "lot-1", "name": f"Carte {item_id}",
        "number": "1/10", "set": "Set test", "quantity": 1, "status": status, "added_at": "2026-10-11T10:00:00",
        "draft_ready_at": draft, "online_at": "", "sold_at": "", "listing_posted": False,
    }


def _listing(order, item_id, *, ext="Set test"):
    return {
        "recognition_group_id": f"group-{item_id}", "creation_order": order, "validation_source": "manual",
        "photos": [{"role": "primary_front", "filename": f"{item_id}-1.jpg"}, {"role": "back_western", "filename": f"{item_id}-2.jpg"}],
        "primary_front": {"filename": f"{item_id}-1.jpg"},
        "cards": [{"card_uid": f"card-{item_id}", "candidate": {
            "drop_item_id": item_id, "card_uid": f"card-{item_id}", "name": f"Carte {item_id}", "number": "1/10", "set": ext}}],
        "card_uids": [f"card-{item_id}"],
    }


def _payload(ext="Set test"):
    return {"ready": True, "listings": [_listing(1, "todo", ext=ext), _listing(2, "d1"), _listing(3, "d2")], "photo_folder": ""}


def _creation_script(drop_id, payload_json, mobile):
    import json as _json
    import ui.pages.vinted_listings as _VL
    from services.vinted_drops_service import find_drop as _find

    data = _json.load(open("vinted_drops.json", encoding="utf-8"))
    drop = _find(data, drop_id)
    _VL._render_recognition_creation_step(data, drop, [], None, str, None, mobile, _json.loads(payload_json))


def _preview_script(drop_id, payload_json, mobile):
    import json as _json
    import ui.pages.vinted_listings as _VL
    from services.vinted_drops_service import find_drop as _find

    data = _json.load(open("vinted_drops.json", encoding="utf-8"))
    drop = _find(data, drop_id)
    _VL._render_step4_focus_preview(drop, [], _json.loads(payload_json), None, mobile)



def _split_top_level(selector_list):
    """Coupe une liste de selecteurs sur les virgules hors parentheses (:is(a, b))."""
    parts, depth, current = [], 0, ""
    for char in selector_list:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return parts


class CockpitTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        self.write_drop(launched=True)

        def local_save(data, path="vinted_drops.json"):
            Path(path).write_text(json.dumps(data), encoding="utf-8")

        patcher = patch.object(VL, "save_vinted_drops", side_effect=local_save)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_drop(self, *, launched):
        drop = {
            "id": "drop-1", "name": "Drop test", "channel": "ChoppeTaCarte",
            "drop_launched_at": LAUNCHED if launched else "",
            "cards": [
                _ref("todo", "to_photograph"),
                _ref("d1", "draft_ready", draft="2026-10-12T10:00:00"),
                _ref("d2", "draft_ready", draft="2026-10-12T10:00:00"),
            ],
        }
        if not launched:
            for ref in drop["cards"]:
                ref["added_at"] = ""
        Path("vinted_drops.json").write_text(json.dumps({"drops": [drop]}), encoding="utf-8")

    def run_step(self, mobile, payload=None, script=_creation_script):
        at = AppTest.from_function(script, args=("drop-1", json.dumps(payload or _payload()), mobile))
        at.default_timeout = 60
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    @staticmethod
    def widgets(at):
        found = {("text_input", w.key) for w in at.text_input}
        found |= {("text_area", w.key) for w in at.text_area}
        found |= {("button", w.key) for w in at.button}
        return found

    @staticmethod
    def markdown_text(at):
        return "\n".join(m.value for m in at.markdown)

    # ---- le verrouillage n'existe que sur l'affichage large ----
    def test_marker_only_on_wide_layout(self):
        self.assertIn("ps-cockpit-marker", self.markdown_text(self.run_step(mobile=False)))
        self.assertNotIn("ps-cockpit-marker", self.markdown_text(self.run_step(mobile=True)))

    # ---- memes widgets, memes cles, memes expanders que l'affichage classique ----
    def test_same_widgets_and_keys_as_the_classic_layout(self):
        wide = self.run_step(mobile=False)
        classic = self.run_step(mobile=True)
        added = {("button", "step4_prev_drop-1"), ("button", "step4_next_drop-1"),
                 ("button", "regen_texts_open_drop-1")}  # ajouts du cockpit : navigation ‹ › et « Régénérer les textes » (menu Plus)
        self.assertEqual(self.widgets(wide) - added, self.widgets(classic))
        self.assertTrue(added <= self.widgets(wide))
        self.assertEqual(sorted(e.label for e in wide.expander), sorted(e.label for e in classic.expander))
        self.assertIn("Détails de l’ordre des photos", [e.label for e in wide.expander])
        self.assertTrue(any("Brouillons à publier" in m.value for m in wide.markdown))
        for key in ("vinted_listing_title", "vinted_listing_description", "vinted_listing_price"):
            self.assertIn(key, {k for _t, k in self.widgets(wide)})

    def test_same_texts_and_values_as_the_classic_layout(self):
        wide = self.run_step(mobile=False)
        classic = self.run_step(mobile=True)
        for key in ("vinted_listing_title", "vinted_listing_price"):
            self.assertEqual(wide.text_input(key=key).value, classic.text_input(key=key).value)
        self.assertEqual(wide.text_area(key="vinted_listing_description").value, classic.text_area(key="vinted_listing_description").value)
        text = self.markdown_text(wide)
        self.assertIn("Annonce 1 / 3", text)
        self.assertIn("2 photos · validation manuelle", text)
        self.assertIn("Annonces créées", text)

    def test_missing_extension_badge_and_shortcut_are_kept(self):
        at = self.run_step(mobile=False, payload=_payload(ext=""))
        self.assertIn("Extension manquante", self.markdown_text(at))
        self.assertTrue(at.get("popover"), "le raccourci « Choisir l'extension » reste accessible")

    # ---- comportement des boutons inchange ----
    def test_draft_button_and_mark_online_behave_like_before(self):
        for mobile in (False, True):
            self.write_drop(launched=True)
            at = self.run_step(mobile=mobile)
            at.button(key="draft_ready_recognition_group_drop-1_group-todo").click().run()
            self.assertFalse(at.exception)
            saved = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
            self.assertEqual({r["drop_item_id"]: r["status"] for r in saved["cards"]},
                             {"todo": "draft_ready", "d1": "draft_ready", "d2": "draft_ready"}, mobile)
            at.button(key="restock_mark_online_drop-1_d1").click().run()
            saved = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
            self.assertEqual({r["drop_item_id"]: r["status"] for r in saved["cards"]}["d1"], "online", mobile)

    def test_unlaunched_drop_keeps_the_launch_panel_reachable(self):
        self.write_drop(launched=False)
        wide = self.run_step(mobile=False)
        classic = self.run_step(mobile=True)
        self.assertTrue(wide.get("popover"), "panneau de lancement dans une fenetre")
        self.assertEqual(sorted(e.label for e in wide.expander), sorted(e.label for e in classic.expander) )

    # ---- apercu en lecture seule ----
    def test_preview_uses_the_cockpit_and_keeps_its_navigation(self):
        wide = self.run_step(mobile=False, script=_preview_script)
        classic = self.run_step(mobile=True, script=_preview_script)
        self.assertIn("ps-cockpit-marker", self.markdown_text(wide))
        self.assertNotIn("ps-cockpit-marker", self.markdown_text(classic))
        keys = {w.key for w in wide.button}
        self.assertTrue(any(k.startswith("previous_") for k in keys) and any(k.startswith("next_") for k in keys))

    # ---- CSS : limite a cet ecran, uniquement quand la fenetre est assez haute ----
    def test_css_is_scoped_and_only_active_above_the_minimum_height(self):
        scope = '[data-testid="stMain"]:has(.ps-cockpit-marker)'
        css = (VL._COCKPIT_CSS % {"minw": VL.COCKPIT_MIN_VIEWPORT_WIDTH_PX, "minh": VL.COCKPIT_MIN_VIEWPORT_HEIGHT_PX}).replace("@S", scope)
        head, media = css.split("@media", 1)
        head = re.sub(r"/\*.*?\*/", "", head, flags=re.S)
        self.assertIn(f"min-height: {VL.COCKPIT_MIN_VIEWPORT_HEIGHT_PX}px", media)
        self.assertNotIn("stMain", head, "le blocage du defilement ne doit jamais sortir du bloc @media")
        for block in head.split("}"):
            if "{" in block and not block.strip().startswith("/*"):
                for selector in block.split("{", 1)[0].split(","):
                    self.assertRegex(selector.strip(), r"^(\.(st-key-ps_cockpit_|ps-cockpit-)|body:has\(\.ps-cockpit-marker\) \[data-testid=\"stPopoverBody\"\])", selector)
        body = media[media.index("{") + 1: media.rindex("}")]
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        for block in body.split("}"):
            if "{" not in block:
                continue
            for selector in _split_top_level(block.split("{", 1)[0]):
                selector = selector.strip()
                if selector:
                    self.assertTrue(selector.startswith(scope), selector)
        self.assertEqual(VL.COCKPIT_MIN_VIEWPORT_HEIGHT_PX, 720)  # 156 px de cadre commun en plus depuis le 15/10/2026

    def test_validation_label_is_translated(self):
        self.assertEqual(VL._cockpit_validation_label("manual"), "manuelle")
        self.assertEqual(VL._cockpit_validation_label("auto"), "automatique")
        self.assertEqual(VL._cockpit_validation_label(None), "automatique")


if __name__ == "__main__":
    unittest.main()

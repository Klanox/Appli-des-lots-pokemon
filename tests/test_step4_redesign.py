"""Etape 4 « Creation des annonces » : refonte aeree (ligne du Drop, carte unique, menu « Plus », fleches ‹ ›).

Fixtures temporaires : aucun fichier metier reel, aucun envoi au Cloud.
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
from test_step4_cockpit_layout import LAUNCHED, _creation_script, _listing, _ref, _split_top_level

PREV, NEXT = "step4_prev_drop-1", "step4_next_drop-1"
DRAFT = "draft_ready_recognition_group_drop-1_group-{}"


def _three_todo_payload():
    return {"ready": True, "listings": [_listing(1, "t1"), _listing(2, "t2"), _listing(3, "t3")], "photo_folder": ""}


def _manager_script(mobile):
    import json as _json
    import streamlit as st
    import ui.pages.vinted_listings as _VL

    data = _json.load(open("vinted_drops.json", encoding="utf-8"))
    st.session_state["vinted_drop_step"] = "Création des annonces"
    _VL._render_drops_manager(data, [], [], None, lambda v: f"{v:.0f}€", mobile, "Création des annonces")


def _flagged_creation_script(drop_id, payload_json, mobile):
    import json as _json
    import ui.pages.vinted_listings as _VL
    from services.vinted_drops_service import find_drop as _find

    payload = _json.loads(payload_json)
    data = _json.load(open("vinted_drops.json", encoding="utf-8"))
    drop = _find(data, drop_id)
    _VL._render_recognition_creation_step(data, drop, [], None, str, None, mobile, payload)


def _popover_labels(at):
    return [str(p.proto.popover.label) for p in at.get("popover")]


class Step4RedesignTests(unittest.TestCase):
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

    def write_drop(self, *, launched, ids=("t1", "t2", "t3")):
        cards = [_ref(i, "to_photograph") for i in ids]
        drop = {"id": "drop-1", "name": "Drop test", "channel": "ChoppeTaCarte",
                "drop_launched_at": LAUNCHED if launched else "", "cards": cards}
        if not launched:
            for ref in drop["cards"]:
                ref["added_at"] = ""
        Path("vinted_drops.json").write_text(json.dumps({"drops": [drop]}), encoding="utf-8")

    def run_step(self, mobile=False, payload=None):
        body = dict(payload or _three_todo_payload())
        at = AppTest.from_function(_flagged_creation_script, args=("drop-1", json.dumps(body), mobile))
        at.default_timeout = 60
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    @staticmethod
    def text(at):
        return "\n".join(m.value for m in at.markdown)

    # ---- navigation ‹ › (ajout : l'ecran de creation n'avait aucune navigation entre annonces) ----
    def test_arrows_move_between_pending_listings_and_recompute_the_text(self):
        at = self.run_step()
        self.assertIn("Annonce 1 / 3", self.text(at))
        self.assertTrue(at.button(key=PREV).disabled)
        self.assertFalse(at.button(key=NEXT).disabled)
        first_title = at.text_input(key="vinted_listing_title").value
        at.button(key=NEXT).click().run()
        self.assertFalse(at.exception)
        self.assertIn("Annonce 2 / 3", self.text(at))
        second_title = at.text_input(key="vinted_listing_title").value
        self.assertIn("t2", second_title)
        self.assertNotEqual(first_title, second_title)
        self.assertTrue(second_title and at.text_area(key="vinted_listing_description").value)
        at.button(key=NEXT).click().run()
        self.assertIn("Annonce 3 / 3", self.text(at))
        self.assertTrue(at.button(key=NEXT).disabled)
        at.button(key=PREV).click().run()
        at.button(key=PREV).click().run()
        self.assertIn("Annonce 1 / 3", self.text(at))
        self.assertEqual(at.text_input(key="vinted_listing_title").value, first_title)

    def test_navigation_alone_never_writes_the_drop_file(self):
        before = Path("vinted_drops.json").read_bytes()
        at = self.run_step()
        at.button(key=NEXT).click().run()
        at.button(key=PREV).click().run()
        self.assertEqual(Path("vinted_drops.json").read_bytes(), before)

    def test_draft_created_acts_on_the_displayed_listing_then_returns_to_the_first(self):
        at = self.run_step()
        at.button(key=NEXT).click().run()
        at.button(key=DRAFT.format("t2")).click().run()
        self.assertFalse(at.exception)
        saved = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
        self.assertEqual({r["drop_item_id"]: r["status"] for r in saved["cards"]},
                         {"t1": "to_photograph", "t2": "draft_ready", "t3": "to_photograph"})
        self.assertIn("Annonce 1 / 3", self.text(at))  # la plus ancienne a traiter reste affichee en premier

    def test_single_pending_listing_has_both_arrows_disabled(self):
        at = self.run_step(payload={"ready": True, "listings": [_listing(1, "t1")], "photo_folder": ""})
        self.assertTrue(at.button(key=PREV).disabled and at.button(key=NEXT).disabled)

    # ---- menu « Plus » : rien du secondaire n'a disparu ----
    def test_plus_menu_holds_the_secondary_content(self):
        payload = _three_todo_payload()
        payload["listings"].append(_listing(4, "d1"))
        self.write_drop(launched=True, ids=("t1", "t2", "t3", "d1"))
        drops = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))
        for ref in drops["drops"][0]["cards"]:
            if ref["drop_item_id"] == "d1":
                ref.update(status="draft_ready", draft_ready_at="2026-10-12T10:00:00")
        Path("vinted_drops.json").write_text(json.dumps(drops), encoding="utf-8")
        at = self.run_step(payload=payload)
        self.assertTrue(any("Plus" in label for label in _popover_labels(at)), _popover_labels(at))
        labels = [e.label for e in at.expander]
        self.assertIn("Détails de l’ordre des photos", labels)
        self.assertTrue(any("Brouillons à publier" in m.value for m in at.markdown))
        captions = "\n".join(c.value for c in at.caption)
        self.assertIn("Ordre issu de la reconnaissance photo", captions)
        # le bandeau de reassort vit dans l'icone ⓘ de l'en-tete de la carte (plus dans le menu « Plus »)
        self.assertIn("ⓘ", " ".join(_popover_labels(at)))
        self.assertTrue(any("Réassort" in i.value for i in at.info))
        self.assertTrue(any("Marquer en ligne" in str(b.label) for b in at.button))

    def test_restock_info_icon_sits_next_to_plus_in_the_cockpit_head_only_when_launched(self):
        at = self.run_step()
        labels = _popover_labels(at)
        self.assertTrue(any("ⓘ" in label for label in labels), labels)
        self.assertTrue(any("Plus" in label for label in labels), labels)
        self.write_drop(launched=False)
        at = self.run_step()
        self.assertFalse(any("ⓘ" in label for label in _popover_labels(at)), "pas de reassort : pas d'icone")

    def test_plus_menu_has_the_launch_panel_when_the_drop_is_not_launched(self):
        self.write_drop(launched=False)
        at = self.run_step()
        self.assertIn("Lancement du Drop", self.text(at))
        self.assertFalse(any("Réassort" in i.value for i in at.info))

    # ---- boutons principaux ----
    def test_main_actions_and_copy_fields_are_present(self):
        at = self.run_step()
        keys = {w.key for w in at.button} | {w.key for w in at.text_input} | {w.key for w in at.text_area}
        for key in ("vinted_listing_title", "vinted_listing_description", "vinted_listing_price", DRAFT.format("t1")):
            self.assertIn(key, keys)
        self.assertTrue(any("Ouvrir Vinted" in str(getattr(link, "label", "") or link.proto.label) for link in at.get("link_button")))
        self.assertIn("Annonces créées", self.text(at))
        self.assertIn("Principale", self.text(at))

    def test_pills_show_extension_language_and_shiny_keyword(self):
        at = self.run_step()
        self.assertIn("Set test · FR", self.text(at))
        at = self.run_step(payload={"ready": True, "listings": [_listing(1, "t1", ext="")], "photo_folder": ""})
        self.assertIn("Extension manquante", self.text(at))

    # ---- cadre commun du Drop : plus de ligne compacte propre a l'etape 4 ----
    def test_drop_frame_has_the_same_components_on_every_wide_step(self):
        at = AppTest.from_function(_manager_script, args=(False,))
        at.default_timeout = 60
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertIn("vinted_drop_view", [w.key for w in at.selectbox])
        labels = _popover_labels(at)
        self.assertTrue(any("Nouveau Drop" in label for label in labels), labels)
        self.assertTrue(any("Gérer" in label for label in labels), labels)
        self.assertFalse(any("ⓘ" in label for label in labels), "le ⓘ n'est plus dans le cadre : il est dans le cockpit")
        self.assertIn("Drop test", self.text(at))
        self.assertIn("Valeur du drop", self.text(at))
        self.assertNotIn("ps-topbar-marker", self.text(at))

    def test_classic_drop_head_is_unchanged_on_mobile(self):
        at = AppTest.from_function(_manager_script, args=(True,))
        at.default_timeout = 60
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        labels = _popover_labels(at)
        self.assertTrue(any("Nouveau Drop" in label for label in labels), labels)

    def test_dropframe_css_is_scoped_to_its_marker_and_has_no_topbar_leftovers(self):
        self.assertFalse(hasattr(VL, "_TOPBAR_CSS"))
        self.assertFalse(hasattr(VL, "STEP4_TOPBAR_FLAG"))
        self.assertFalse(hasattr(VL, "_render_step4_topbar"))
        self.assertFalse(hasattr(VL, "_inject_vinted_analytics_compact_styles"))
        css = re.sub(r"/\*.*?\*/", "", VL._DROPFRAME_CSS, flags=re.S)
        for block in css.split("}"):
            if "{" in block:
                for selector in _split_top_level(block.split("{", 1)[0]):
                    selector = selector.strip()
                    if selector:
                        self.assertTrue(selector.startswith("@D"), selector)

    def test_the_page_renders_the_marker_and_the_same_header_on_all_steps(self):
        import inspect

        source = inspect.getsource(VL.render_vinted_listings_page)
        self.assertIn("_inject_vinted_dropframe_styles()", source)
        self.assertIn('render_page_header_func("Drop Vinted"', source)
        self.assertNotIn("topbar", source.lower())
        self.assertIn("ps-dropframe-marker", VL.DROPFRAME_MARKER_HTML)


if __name__ == "__main__":
    unittest.main()

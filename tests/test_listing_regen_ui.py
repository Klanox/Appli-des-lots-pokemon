"""Etape 4 : memo du texte au clic « Brouillon cree », temoin « Texte ancien format », boite de regeneration.

Fixtures temporaires uniquement (dossier de travail temporaire, aucun fichier metier, aucun Cloud).
"""

from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from services import listing_text_service as LTS
from ui.pages import vinted_listings as VL
from test_listing_text_persistence import DRAFT_BUTTON, _away_script, _payload_with
from test_step4_cockpit_layout import LAUNCHED, _ref

COURROUSINGE = {"id": "sv04.5-171", "name": "Courrousinge", "number": "171", "set": "Destinées de Paldea", "lang": "fr"}


class DraftTextMemoTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        shutil.copy(os.path.join(self._cwd, "sets_reference.json"), self._tmp.name)  # totaux imprimes (lus dans le dossier courant)
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        drop = {"id": "drop-1", "name": "Drop test", "channel": "ChoppeTaCarte", "drop_launched_at": LAUNCHED,
                "cards": [_ref("todo", "to_photograph"), _ref("d1", "draft_ready", draft="2026-10-12T10:00:00"),
                          _ref("d2", "draft_ready", draft="2026-10-12T10:00:00")]}
        Path("vinted_drops.json").write_text(json.dumps({"drops": [drop]}), encoding="utf-8")

        def local_save(data, path="vinted_drops.json"):
            Path(path).write_text(json.dumps(data), encoding="utf-8")

        patcher = patch.object(VL, "save_vinted_drops", side_effect=local_save)
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self):
        at = AppTest.from_function(_away_script, args=("drop-1", json.dumps(_payload_with([COURROUSINGE])), False))
        at.default_timeout = 60
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def record(self):
        drop = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
        return (drop.get(LTS.TEXTS_KEY) or {}).get("group-todo")

    def test_new_listing_title_is_courrousinge_shiny_171_091(self):
        at = self.start()
        title = at.text_input(key="vinted_listing_title").value
        self.assertEqual(title, "Carte Pokémon - Courrousinge Shiny 171/091 - Destinées de Paldea - FR")
        self.assertTrue(at.text_area(key="vinted_listing_description").value.startswith("Vends Courrousinge Shiny 171/091"))

    def test_draft_click_remembers_the_text_that_was_used(self):
        at = self.start()
        at.button(key=DRAFT_BUTTON).click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        record = self.record()
        self.assertIsNotNone(record)
        self.assertIn("171/091", record["title"])
        self.assertFalse(record["manual"])
        self.assertEqual(record["origin"], "auto")
        self.assertEqual(record["card_uids"], ["card-todo-0"])

    def test_draft_click_flags_a_hand_edited_text(self):
        at = self.start()
        at.text_input(key="vinted_listing_title").set_value("Mon titre à moi").run()
        at.button(key=DRAFT_BUTTON).click().run()
        record = self.record()
        self.assertEqual(record["title"], "Mon titre à moi")
        self.assertTrue(record["manual"])
        self.assertEqual(record["origin"], "manual")

    def test_witness_shows_in_the_plus_line_only_when_the_text_differs_from_the_current_rules(self):
        at = self.start()
        captions = [c.value for c in at.caption]
        self.assertFalse(any("Texte modifié à la main" in c or "Texte ancien format" in c for c in captions), captions)
        at.text_input(key="vinted_listing_title").set_value("Mon titre à moi").run()
        captions = [c.value for c in at.caption]
        self.assertTrue(any("✎ Texte modifié à la main" in c for c in captions), captions)


def _panel_script(payload_json):
    import json as _json
    import os as _os
    import streamlit as st
    import ui.pages.vinted_listings as _VL

    payload = _json.loads(payload_json)

    def load():
        return _json.load(open("vinted_drops.json", encoding="utf-8"))

    def save(data):
        _json.dump(data, open("vinted_drops.json", "w", encoding="utf-8"))

    drop = load()["drops"][0]
    _VL._render_regen_panel(drop, payload, [], "", load_drops=load, save_drops=save,
                            drops_path=_os.path.abspath("vinted_drops.json"), backup_dir=_os.path.abspath("backups"),
                            journal_path=_os.path.abspath("logs/journal.jsonl"))
    st.write("result=" + str(st.session_state.get(_VL.REGEN_RESULT_KEY)))


class RegenPanelTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        shutil.copy(os.path.join(self._cwd, "sets_reference.json"), self._tmp.name)  # totaux imprimes (lus dans le dossier courant)
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        drop = {"id": "drop-1", "name": "Drop test", "channel": "ChoppeTaCarte", "drop_launched_at": LAUNCHED,
                "cards": [_ref("todo", "to_photograph"), _ref("d1", "draft_ready", draft="2026-10-12T10:00:00"),
                          _ref("d2", "draft_ready", draft="2026-10-12T10:00:00")]}
        Path("vinted_drops.json").write_text(json.dumps({"drops": [drop]}), encoding="utf-8")
        self.before = Path("vinted_drops.json").read_bytes()

    def start(self):
        payload = _payload_with([COURROUSINGE])
        # les deux brouillons portent aussi la carte Courrousinge (ancien format suppose)
        for listing in payload["listings"][1:]:
            listing["cards"][0]["candidate"].update({k: COURROUSINGE[k] for k in ("name", "number", "set", "lang")})
        at = AppTest.from_function(_panel_script, args=(json.dumps(payload),))
        at.default_timeout = 60
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def test_preview_writes_nothing_and_confirmation_is_required(self):
        at = self.start()
        text = " ".join(m.value for m in at.markdown)
        self.assertIn("3 annonce(s)", text)
        self.assertIn("brouillon(s)", text)
        self.assertIn("171/198", text)  # exemple avant
        self.assertIn("171/091", text)  # exemple apres
        self.assertTrue(any("mettre à jour à la main" in w.value or "ne peut pas les modifier" in w.value for w in at.warning))
        self.assertEqual(Path("vinted_drops.json").read_bytes(), self.before)
        confirm = at.button(key="vinted_regen_confirm_drop-1")
        self.assertTrue(confirm.disabled)  # tant que la case « j'ai compris » n'est pas cochee
        self.assertEqual(Path("vinted_drops.json").read_bytes(), self.before)

    def test_confirm_writes_records_and_the_vinted_update_list_and_keeps_everything_else(self):
        at = self.start()
        at.checkbox(key="vinted_regen_understood_drop-1").check().run()
        at.button(key="vinted_regen_confirm_drop-1").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        before = json.loads(self.before)["drops"][0]
        drop = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
        self.assertEqual({k: v for k, v in drop.items() if k not in (LTS.TEXTS_KEY, LTS.UPDATES_KEY)}, before)
        self.assertEqual(set(drop[LTS.TEXTS_KEY]), {"group-d1", "group-d2"})
        labels = {u["label"] for u in drop[LTS.UPDATES_KEY]}
        self.assertEqual(labels, {"Brouillon Vinted à mettre à jour"})
        self.assertTrue(os.listdir("backups"))
        self.assertTrue(Path("logs/journal.jsonl").exists())
        self.assertIn("result=(True,", at.markdown[-1].value)

    def test_undo_from_the_panel_restores_the_previous_state(self):
        at = self.start()
        at.checkbox(key="vinted_regen_understood_drop-1").check().run()
        at.button(key="vinted_regen_confirm_drop-1").click().run()
        at = AppTest.from_function(_panel_script, args=(json.dumps(_payload_with([COURROUSINGE])),))
        at.default_timeout = 60
        at.run()
        batch = LTS.journal_batches(os.path.abspath("logs/journal.jsonl"))[0]["batch"]
        at.button(key=f"vinted_regen_undo_{batch}").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        drop = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
        self.assertEqual(drop.get(LTS.TEXTS_KEY), {})
        self.assertEqual(drop.get(LTS.UPDATES_KEY), [])


def _update_list_script():
    import json as _json
    import streamlit as st
    import ui.pages.extension_queue as _Q

    def load():
        return _json.load(open("vinted_drops.json", encoding="utf-8"))

    def save(data):
        _json.dump(data, open("vinted_drops.json", "w", encoding="utf-8"))

    _Q.render_listings_to_update(ld_func=lambda: {"lots": []}, load_drops_func=load, save_drops_func=save)
    st.write("count=" + str(_Q.extension_sections_count({"lots": []}, load())))


class UpdateListTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        updates = [
            {"id": "drop-1:g1", "batch": "b1", "group_id": "g1", "kind": "draft", "label": "Brouillon Vinted à mettre à jour",
             "cards": "Courrousinge 171/091", "title_before": "Ancien titre", "title_after": "Nouveau titre",
             "description_after": "Nouvelle description", "assumed_before": True, "created_at": "2026-10-15T20:00:00", "done_at": ""},
            {"id": "drop-1:g2", "batch": "b1", "group_id": "g2", "kind": "online", "label": "Annonce en ligne à mettre à jour",
             "cards": "Mimiqui 160/091", "title_before": "Ancien", "title_after": "Nouveau", "description_after": "Desc",
             "assumed_before": True, "created_at": "2026-10-15T20:00:01", "done_at": ""},
        ]
        Path("vinted_drops.json").write_text(json.dumps({"drops": [{"id": "drop-1", "name": "Drop Rentrée", "cards": [],
                                                                      LTS.UPDATES_KEY: updates}]}), encoding="utf-8")

    def test_list_shows_both_labels_and_can_mark_a_line_done(self):
        at = AppTest.from_function(_update_list_script)
        at.default_timeout = 30
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        text = " ".join(m.value for m in at.markdown)
        self.assertIn("Brouillon Vinted à mettre à jour", text)
        self.assertIn("Annonce en ligne à mettre à jour", text)
        self.assertIn("count=2", text)
        at.button(key="txtupd_done_drop-1_g1").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        drop = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
        done = {u["group_id"]: u["done_at"] for u in drop[LTS.UPDATES_KEY]}
        self.assertTrue(done["g1"])
        self.assertFalse(done["g2"])
        self.assertIn("count=1", " ".join(m.value for m in at.markdown))


if __name__ == "__main__":
    unittest.main()

"""Ecrans « Extensions manquantes » (Data Health) testes avec AppTest sur des fixtures temporaires (aucun reseau, aucun fichier reel)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_card_extension_source import SETS_REFERENCE, cards_index, make_world  # noqa: E402


def queue_script():
    import json
    import os
    import sys

    sys.path.insert(0, os.environ["EXT_ROOT"])
    import streamlit as st
    from services import card_extension_service as ext
    from ui.pages import extension_queue as q

    base = os.environ["EXT_BASE"]
    ext.APP_DIR = base
    ext.BACKUP_DIR = os.path.join(base, "backups")
    ext.JOURNAL_FILE = os.path.join(base, "journal.jsonl")

    def read(name):
        with open(os.path.join(base, name), encoding="utf-8") as handle:
            return json.load(handle)

    def write(name, payload):
        with open(os.path.join(base, name), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)

    forced = os.environ.get("EXT_FORCE_CHOICE")
    if forced:
        original_selectbox = st.selectbox

        def selectbox(label, options, *args, **kwargs):
            if str(kwargs.get("key", "")).endswith("_choice"):
                original_selectbox(label, options, *args, **kwargs)
                return forced
            return original_selectbox(label, options, *args, **kwargs)

        st.selectbox = selectbox

    page = os.environ.get("EXT_PAGE", "queue")
    if page == "queue":
        q.render_extension_queue(ld_func=lambda: read("data.json"), sd_func=lambda d: write("data.json", d),
                                 load_drops_func=lambda: read("vinted_drops.json"), save_drops_func=lambda d: write("vinted_drops.json", d))
    elif page == "listings":
        q.render_listings_to_update(ld_func=lambda: read("data.json"), load_drops_func=lambda: read("vinted_drops.json"))
    else:
        from ui.pages.data_health import render_data_health_page

        render_data_health_page(
            ld_func=lambda: read("data.json"), sd_func=lambda d: write("data.json", d),
            render_page_header_func=lambda t, s, i: f"<h3>{t}</h3>", navigate_func=lambda p: None,
            load_drops_func=lambda: read("vinted_drops.json"), save_drops_func=lambda d: write("vinted_drops.json", d),
            data_path=os.path.join(base, "data.json"), drops_path=os.path.join(base, "vinted_drops.json"),
            archives_path=os.path.join(base, "lots_archives.json"),
        )


class QueueUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        data, drops = make_world()
        (self.base / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (self.base / "vinted_drops.json").write_text(json.dumps(drops, ensure_ascii=False), encoding="utf-8")
        (self.base / "lots_archives.json").write_text("[]", encoding="utf-8")
        (self.base / "cards_cache.json").write_text(json.dumps({"version": 1, "created_at": 1, "cards_index": cards_index()}), encoding="utf-8")
        (self.base / "sets_reference.json").write_text(json.dumps(SETS_REFERENCE), encoding="utf-8")
        os.environ["EXT_ROOT"] = str(ROOT)
        os.environ["EXT_BASE"] = str(self.base)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("EXT_ROOT", "EXT_BASE", "EXT_PAGE")])

    def run_page(self, page="queue"):
        os.environ["EXT_PAGE"] = page
        at = AppTest.from_function(queue_script, default_timeout=30)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def data(self):
        return json.loads((self.base / "data.json").read_text(encoding="utf-8"))

    def drops(self):
        return json.loads((self.base / "vinted_drops.json").read_text(encoding="utf-8"))

    def set_of(self, name, number):
        for lot in self.data()["lots"]:
            for card in lot["cards"]:
                if card["name"] == name and card["number"] == number:
                    return card["set"]
        raise KeyError(name)

    def test_certain_view_previews_then_applies_after_confirmation(self):
        at = self.run_page()
        self.assertTrue(any("Appliquer les" in b.label for b in at.button))
        before = self.data()
        at.button(key="ext_certain_apply").click().run()
        self.assertEqual(self.data(), before, "rien n'est ecrit avant la confirmation")
        at.button(key="ext_certain_confirm").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(self.set_of("Sorcilence VMAX", "066"), "Zénith Suprême")
        self.assertEqual(self.set_of("Roue-de-Fer-ex", "073"), "SVP Black Star Promos")
        self.assertEqual(self.set_of("Mimantis", "085"), "Nuit Noire")
        self.assertEqual(self.set_of("Raichu", "50"), "", "les propositions non certaines ne sont pas ecrites")
        drop_sets = {c["name"]: c["set"] for c in self.drops()["drops"][0]["cards"]}
        self.assertEqual(drop_sets, {"Sorcilence VMAX": "Zénith Suprême", "Mimantis": "Nuit Noire"})
        self.assertEqual([c["status"] for c in self.drops()["drops"][0]["cards"]], ["online", "to_photograph"])
        self.assertTrue(os.listdir(self.base / "backups"))
        self.assertTrue((self.base / "journal.jsonl").exists())

    def test_cancel_confirmation_writes_nothing(self):
        at = self.run_page()
        before = self.data()
        at.button(key="ext_certain_apply").click().run()
        at.button(key="ext_certain_cancel").click().run()
        self.assertEqual(self.data(), before)

    def test_probable_rows_need_a_checked_box(self):
        data = self.data()
        data["lots"][0]["cards"].append({"name": "Pikachu", "number": "50", "set": "", "card_uid": "card_pika50", "quantity": 1, "sold_quantity": 0})
        (self.base / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        at = self.run_page()
        at.radio(key="extension_queue_view").set_value("Probables").run()
        self.assertTrue(at.button(key="ext_prob_apply").disabled, "bouton inactif tant qu'aucune case n'est cochee")
        at.checkbox(key="ext_prob_card_pika50").check().run()
        self.assertFalse(at.button(key="ext_prob_apply").disabled)
        at.button(key="ext_prob_apply").click().run()
        self.assertEqual(self.set_of("Pikachu", "50"), "Voltage Éclatant")
        self.assertEqual(self.set_of("Raichu", "50"), "", "les cartes non cochees ne sont pas touchees")

    def test_manual_view_accepts_free_text_and_saves(self):
        at = self.run_page()
        at.radio(key="extension_queue_view").set_value("À choisir").run()
        key = "ext_manual_card_Raichu_50"
        # AppTest ne sait pas representer une valeur « saisie libre » d'un selectbox : le script la renvoie pour les cles *_choice.
        os.environ["EXT_FORCE_CHOICE"] = "Extension libre 2026"
        self.addCleanup(lambda: os.environ.pop("EXT_FORCE_CHOICE", None))
        at = self.run_page()
        at.radio(key="extension_queue_view").set_value("À choisir").run()
        at.button(key=f"{key}_save").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(self.set_of("Raichu", "50"), "Extension libre 2026")

    def test_manual_view_lists_candidates_first(self):
        at = self.run_page()
        at.radio(key="extension_queue_view").set_value("À choisir").run()
        options = at.selectbox(key="ext_manual_card_Dracaufeu_066_choice").options
        self.assertGreater(len(options), 3)

    def test_undo_button_restores_values(self):
        at = self.run_page()
        at.button(key="ext_certain_apply").click().run()
        at.button(key="ext_certain_confirm").click().run()
        at = self.run_page()
        undo = [b for b in at.button if (b.key or "").startswith("ext_undo_")]
        self.assertEqual(len(undo), 1)
        undo[0].click().run()
        self.assertEqual(self.set_of("Sorcilence VMAX", "066"), "")

    def test_listings_to_update_after_correction(self):
        at = self.run_page("listings")
        self.assertTrue(any("Extension manquante" in m.value for m in at.markdown))
        # correction puis liste
        at = self.run_page()
        at.button(key="ext_certain_apply").click().run()
        at.button(key="ext_certain_confirm").click().run()
        at = self.run_page("listings")
        titles = [t.value for t in at.text_input]
        self.assertEqual(len(titles), 1)
        self.assertIn("Zénith Suprême", titles[0])
        done = [b for b in at.button if (b.key or "").startswith("extlist_done_")]
        self.assertEqual(len(done), 1)
        done[0].click().run()
        self.assertTrue(any("Aucune annonce en ligne" in s.value for s in at.success))
        self.assertEqual(self.drops()["drops"][0]["cards"][0]["status"], "online")

    def test_data_health_page_shows_permanent_counter_and_sections(self):
        at = self.run_page("health")
        labels = [m.label for m in at.metric]
        self.assertIn("Cartes sans extension — stock", labels)
        self.assertEqual(at.metric[0].value, "6")
        self.assertEqual(at.metric[1].value, "2")
        at.radio(key="extension_queue_section").set_value("extensions").run()
        self.assertFalse(at.exception)
        self.assertTrue(any("sans extension" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()

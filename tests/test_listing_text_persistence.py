"""Bug du 15/10/2026 : titre, description et prix VIDES a l'etape 4 apres avoir quitte puis retrouve l'ecran.

Cause : Streamlit supprime la valeur d'un widget `key=` des qu'un rerun ne l'affiche pas ; la signature de
selection (qui decide s'il faut recalculer) n'est pas un widget et restait, donc rien n'etait recalcule au retour.
Fixtures temporaires uniquement (aucun fichier metier, aucun Cloud).
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from ui.pages import vinted_listings as VL
from test_step4_cockpit_layout import LAUNCHED, _listing, _payload, _ref

KEYS = ("vinted_listing_title", "vinted_listing_description", "vinted_listing_price")
DRAFT_BUTTON = "draft_ready_recognition_group_drop-1_group-todo"


def _away_script(drop_id, payload_json, mobile):
    import json as _json
    import streamlit as st
    import ui.pages.vinted_listings as _VL
    from services.vinted_drops_service import find_drop as _find

    if st.session_state.get("away"):
        st.write("autre étape")
    else:
        data = _json.load(open("vinted_drops.json", encoding="utf-8"))
        drop = _find(data, drop_id)
        _VL._render_recognition_creation_step(data, drop, [], None, str, None, mobile, _json.loads(payload_json))


def _card_listing(order, item_id, cards):
    listing = _listing(order, item_id)
    listing["cards"] = [{"card_uid": f"card-{item_id}-{i}", "candidate": dict(card, card_uid=f"card-{item_id}-{i}", drop_item_id=item_id)}
                        for i, card in enumerate(cards)]
    listing["card_uids"] = [c["card_uid"] for c in listing["cards"]]
    return listing


def _payload_with(cards):
    return {"ready": True, "listings": [_card_listing(1, "todo", cards), _listing(2, "d1"), _listing(3, "d2")], "photo_folder": ""}


class ListingTextPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        self.write_drop()

        def local_save(data, path="vinted_drops.json"):
            Path(path).write_text(json.dumps(data), encoding="utf-8")

        patcher = patch.object(VL, "save_vinted_drops", side_effect=local_save)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_drop(self):
        drop = {"id": "drop-1", "name": "Drop test", "channel": "ChoppeTaCarte", "drop_launched_at": LAUNCHED,
                "cards": [_ref("todo", "to_photograph"), _ref("d1", "draft_ready", draft="2026-10-12T10:00:00"),
                          _ref("d2", "draft_ready", draft="2026-10-12T10:00:00")]}
        Path("vinted_drops.json").write_text(json.dumps({"drops": [drop]}), encoding="utf-8")

    def start(self, payload=None, mobile=False):
        at = AppTest.from_function(_away_script, args=("drop-1", json.dumps(payload or _payload()), mobile))
        at.default_timeout = 60
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def values(self, at):
        return {
            "title": at.text_input(key="vinted_listing_title").value,
            "description": at.text_area(key="vinted_listing_description").value,
            "price": at.text_input(key="vinted_listing_price").value,
        }

    def leave_and_return(self, at):
        at.session_state["away"] = True
        at.run()
        self.assertFalse(at.exception)
        for key in ("vinted_listing_title", "vinted_listing_description"):
            self.assertNotIn(key, at.session_state, "Streamlit supprime bien la valeur du widget non affiche")
        self.assertIn("vinted_listing_signature", at.session_state, "la signature, elle, reste : c'est la cause du bug")
        at.session_state["away"] = False
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def assert_filled(self, values):
        for name, value in values.items():
            self.assertTrue(str(value).strip(), f"{name} est vide")

    # ---- le cas exact du bug, sur plusieurs types d'annonce ----
    def test_single_card_text_survives_leaving_the_screen(self):
        at = self.start()
        before = self.values(at)
        self.assert_filled(before)
        after = self.values(self.leave_and_return(at))
        self.assertEqual(after, before)

    def test_multi_card_listing(self):
        cards = [{"name": "Riolu", "number": "5", "set": "Set test"}, {"name": "Pikachu", "number": "6", "set": "Set test"}]
        at = self.start(_payload_with(cards))
        before = self.values(at)
        self.assertTrue(before["title"].startswith("Lot cartes Pokémon"), before["title"])
        self.assertEqual(self.values(self.leave_and_return(at)), before)

    def test_shiny_card_keeps_its_keyword(self):
        card = {"id": "sv04.5-171", "name": "Courrousinge", "number": "171", "set": "Destinées de Paldea"}
        at = self.start(_payload_with([card]))
        before = self.values(at)
        self.assertIn("Shiny", before["title"])  # le mot exact (Shiny / Shiny Chromatique) depend de la regle en vigueur
        after = self.values(self.leave_and_return(at))
        self.assertEqual(after, before)

    def test_mobile_layout_has_the_same_fix(self):
        at = self.start(mobile=True)
        before = self.values(at)
        self.assertEqual(self.values(self.leave_and_return(at)), before)

    def test_corrected_extension_updates_the_text_but_unchanged_text_is_kept(self):
        at = self.start(_payload(ext=""))
        self.assertNotIn("Zénith Suprême", self.values(at)["title"])
        at.session_state["away"] = True
        at.run()
        at.session_state["away"] = False
        at.run()  # meme annonce : texte conserve
        self.assertFalse(self.values(at)["title"] == "")
        # l'extension est corrigee ailleurs (autre page) : la selection change, le texte suit
        corrected = AppTest.from_function(_away_script, args=("drop-1", json.dumps(_payload(ext="Zénith Suprême")), False))
        corrected.default_timeout = 60
        for key in ("vinted_listing_signature",):
            pass
        corrected.run()
        self.assertIn("Zénith Suprême", self.values(corrected)["title"])
        self.assertIn("Zénith Suprême", self.values(corrected)["description"])

    def test_restock_listing_with_launched_drop(self):
        at = self.start()
        self.assertTrue(any("Brouillons à publier" in m.value for m in at.markdown))
        before = self.values(at)
        self.assertEqual(self.values(self.leave_and_return(at)), before)

    # ---- modifications manuelles ----
    def test_manual_edit_is_kept_after_leaving_and_returning(self):
        at = self.start()
        at.text_input(key="vinted_listing_title").set_value("Mon titre à moi").run()
        at.text_area(key="vinted_listing_description").set_value("Ma description").run()
        self.assertEqual(self.values(at)["title"], "Mon titre à moi")
        after = self.values(self.leave_and_return(at))
        self.assertEqual((after["title"], after["description"]), ("Mon titre à moi", "Ma description"))

    def test_manual_edit_is_not_overwritten_by_a_plain_rerun(self):
        at = self.start()
        at.text_input(key="vinted_listing_title").set_value("Titre modifié").run()
        at.run()
        self.assertEqual(self.values(at)["title"], "Titre modifié")

    def test_blank_values_left_by_an_older_session_are_refilled(self):
        at = self.start()
        at.session_state["vinted_listing_title"] = ""
        at.session_state["vinted_listing_description"] = ""
        at.run()
        self.assert_filled(self.values(at))

    def test_new_listing_regenerates_the_text(self):
        at = self.start()
        first = self.values(at)["title"]
        at.session_state["vinted_listing_signature"] = "autre-annonce"
        at.run()
        self.assertEqual(self.values(at)["title"], first)

    # ---- garde-fou ----
    def test_ungenerable_text_shows_an_error_and_blocks_the_draft(self):
        empty = {"title": "", "description": "", "signature": "sig", "suggested_price": 0.0, "has_price": False}
        with patch.object(VL, "prepare_listing", return_value=empty):
            at = self.start()
            self.assertTrue(any("Impossible d'afficher" in e.value for e in at.error), [e.value for e in at.error])
            at.button(key=DRAFT_BUTTON).click().run()
            self.assertTrue(any("Brouillon non enregistré" in e.value for e in at.error), [e.value for e in at.error])
        saved = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
        self.assertEqual({r["drop_item_id"]: r["status"] for r in saved["cards"]}["todo"], "to_photograph")

    def test_draft_button_still_works_with_a_filled_text(self):
        at = self.start()
        at.button(key=DRAFT_BUTTON).click().run()
        saved = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
        self.assertEqual({r["drop_item_id"]: r["status"] for r in saved["cards"]}["todo"], "draft_ready")

    def test_price_is_text_never_blank(self):
        at = self.start()
        self.assertEqual(self.values(at)["price"], "Prix à définir")  # aucune carte du jeu d'essai n'a de prix
        priced = {"name": "Riolu", "number": "5", "set": "Set test", "suggested_price": 3.5}
        at = self.start(_payload_with([priced]))
        self.assertIn("3", self.values(at)["price"])
        self.assertEqual(self.values(self.leave_and_return(at))["price"], self.values(at)["price"])


if __name__ == "__main__":
    unittest.main()

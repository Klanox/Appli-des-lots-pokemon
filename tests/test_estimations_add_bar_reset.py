"""Barre « Ajouter une carte » : remise à zéro de tous les champs après un ajout réussi seulement (données temporaires)."""
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

from test_estimations_japanese_mode import APP, FR_CARD
from ui.pages import estimations


class AddBarResetTest(unittest.TestCase):
    def setUp(self):
        sugg = [{"card": dict(FR_CARD), "match": (dict(FR_CARD), FR_CARD["set"])}]
        patches = [
            mock.patch.object(estimations, "_card_suggestions", lambda query, *a, **k: sugg if str(query or "").strip() else []),
            mock.patch.object(estimations, "save_market_price_cache", mock.Mock()),
            mock.patch.object(estimations, "st_keyup", lambda label, value="", key=None, **k: __import__("streamlit").text_input(label, value=value, key=key)),
            mock.patch.object(estimations, "render_lot_image_upload_bridge", lambda key=None: None),
            mock.patch.object(estimations, "_manual_estimation_image_dir", lambda: "/nonexistent-never-written"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.at = AppTest.from_string(APP, default_timeout=30)
        self.at.run()

    def widgets(self):
        a = self.at
        return (next(t for t in a.text_input if "Rechercher" in t.label), next(t for t in a.text_input if t.label == "Numéro"),
                next(t for t in a.text_input if t.label == "Qté" and t.key and "add_qty" in t.key),
                next(t for t in a.text_input if t.label == "Note rapide"),
                next(m for m in a.multiselect if m.label == "Spécial"), next(c for c in a.checkbox if c.label == "Cartes japonaises"))

    def fill(self):
        name, number, qty, note, special, jp = self.widgets()
        name.set_value("Koraidon"); number.set_value("231"); qty.set_value("3"); note.set_value("coin abîmé")
        special.set_value(["Reverse"]); jp.check()
        self.at.run()

    def assert_initial(self):
        self.assertEqual(len(self.at.exception), 0, [e.value for e in self.at.exception])
        name, number, qty, note, special, jp = self.widgets()
        self.assertEqual((name.value, number.value, qty.value, note.value, list(special.value), jp.value), ("", "", "1", "", [], False))
        self.assertEqual(len([b for b in self.at.button if (b.key or "").startswith("est_suggestion_pick_")]), 0)

    def cards(self):
        return self.at.session_state["edata"]["estimations"][0]["cards"]

    def test_reset_after_successful_add_button_then_second_add(self):
        n0 = len(self.cards())
        self.fill()
        next(b for b in self.at.button if b.label == "+ Ajouter").click().run()
        self.assertEqual(len(self.cards()), n0 + 1)
        self.assert_initial()
        self.at.run()                                   # rerun : pas de double ajout
        self.assertEqual(len(self.cards()), n0 + 1)
        self.fill()
        next(b for b in self.at.button if b.label == "+ Ajouter").click().run()
        self.assertEqual(len(self.cards()), n0 + 2)
        self.assert_initial()

    def test_reset_after_successful_choose(self):
        n0 = len(self.cards())
        self.fill()
        next(b for b in self.at.button if b.label == "Choisir").click().run()
        self.assertEqual(len(self.cards()), n0 + 1)
        self.assert_initial()

    def test_no_reset_when_add_refused(self):
        n0 = len(self.cards())
        name, number, qty, note, special, jp = self.widgets()
        number.set_value("231"); note.set_value("coin abîmé"); special.set_value(["Reverse"]); jp.check()   # nom manquant
        self.at.run()
        next(b for b in self.at.button if b.label == "+ Ajouter").click().run()
        self.assertEqual(len(self.cards()), n0)
        name, number, qty, note, special, jp = self.widgets()
        self.assertEqual((number.value, note.value, list(special.value), jp.value), ("231", "coin abîmé", ["Reverse"], True))


if __name__ == "__main__":
    unittest.main()

"""Enregistrement automatique (on_change) des champs Qté et Cote d'une carte suivie — données temporaires.

Aucune donnée réelle, aucun réseau, aucun cloud : l'écriture du cache de prix est remplacée par un espion
pendant toute la durée du test (les callbacks s'exécutent avant le script), la sauvegarde des estimations est un espion.
"""
import inspect
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from ui.pages import estimations

ROOT = str(Path(__file__).resolve().parents[1])

APP = '''
import sys
sys.path.insert(0, %(root)r)
import streamlit as st
from services.estimations_service import default_estimations_data, normalize_estimations_data, estimation_totals
from ui.pages import estimations as E
from utils import fp, normalize_name

if "edata" not in st.session_state:
    edata = normalize_estimations_data(default_estimations_data())
    edata["estimations"] = [{"uid": "e1", "name": "Estimation A", "source": "Vinted", "seller_price": 40, "status": "À analyser",
        "cards": [{"uid": f"c{i}", "name": f"Carte {i}", "number": str(i), "set": "Set", "quantity": 2, "cote": 7.0,
                   "market_price_origin": "auto", "auto_price": 7.0, "lang": "fr"} for i in (1, 2)]
        + [{"uid": "c3", "name": "Carte 3", "number": "3", "set": "Set", "quantity": 1, "cote": 6.0,
            "market_price_origin": "manual", "manual_price": 6.0, "auto_price": 11.0, "lang": "fr"}]}]
    st.session_state["edata"] = edata
    st.session_state["calls"] = []
    st.session_state["market_price_cache"] = {"entries": {}}
edata = st.session_state["edata"]
est = edata["estimations"][0]
def save(_data=None):
    st.session_state["calls"].append("save")
E._render_open_estimation(
    estimate=est, totals=estimation_totals(est, edata["settings"]), settings=edata["settings"], edata=edata, uid="e1",
    save_estimations_func=save, add_estimation_card_func=lambda *a, **k: None, ld_func=lambda: {"lots": []}, sd_func=lambda *a, **k: None,
    fetch_listing_preview_image_func=lambda *a, **k: "", cardmarket_search_url_func=lambda *a, **k: "https://example.invalid",
    search_in_cache_func=lambda *a, **k: [], img_with_fallback_func=lambda *a, **k: "",
    fp_func=fp, normalize_name_func=normalize_name,
    parse_float_input_func=lambda t, d=0.0: float(str(t).replace(",", ".")) if str(t).strip() else d,
    new_uid_func=lambda p="x": p + "_t", is_mobile_mode_func=lambda: False, ecd_func=lambda c, s, l="fr": c,
    proxy_img_func=lambda u, *a, **k: u, cache_enrichment_func=None, market_cache=st.session_state["market_price_cache"],
)
''' % {"root": ROOT}


class CardAutosaveTest(unittest.TestCase):
    def setUp(self):
        self.cache_save = mock.Mock(return_value={"ok": True})
        patches = [
            mock.patch.object(estimations, "save_market_price_cache", self.cache_save),
            mock.patch.object(estimations, "st_keyup", lambda label, value="", key=None, **k: __import__("streamlit").text_input(label, value=value, key=key)),
            mock.patch.object(estimations, "render_lot_image_upload_bridge", lambda key=None: None),
            mock.patch.object(estimations, "_manual_estimation_image_dir", lambda: "/nonexistent-never-written"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.at = AppTest.from_string(APP, default_timeout=30)
        self.at.run()
        self.assertEqual(len(self.at.exception), 0, [e.value for e in self.at.exception])

    def card(self, uid):
        return next(c for c in self.at.session_state["edata"]["estimations"][0]["cards"] if c["uid"] == uid)

    def qty(self, uid):
        return next(n for n in self.at.number_input if n.key == f"est_card_qty_e1_{uid}")

    def cote(self, uid):
        return next(t for t in self.at.text_input if t.key == f"est_card_cote_e1_{uid}")

    def saves(self):
        return self.at.session_state["calls"].count("save")

    def test_no_submit_button_and_no_form_on_cards(self):
        self.assertNotIn("Enregistrer", [b.label for b in self.at.button])
        self.assertNotIn('st.form(f"est_card_values_', inspect.getsource(estimations._render_open_estimation))

    def test_quantity_change_saves_quantity_only_and_keeps_auto_cote(self):
        self.qty("c1").set_value(5).run()
        self.assertEqual(len(self.at.exception), 0)
        card = self.card("c1")
        self.assertEqual(card["quantity"], 5)
        self.assertEqual(card["market_price_origin"], "auto")
        self.assertNotIn("manual_price", card)
        self.assertEqual(card["cote"], 7.0)
        self.assertEqual(self.saves(), 1)
        self.cache_save.assert_not_called()
        self.assertEqual(self.at.session_state["market_price_cache"]["entries"], {})

    def test_quantity_changed_elsewhere_recreates_field_with_new_value(self):
        self.qty("c1").set_value(5).run()                                           # saisie utilisateur : le champ garde sa clé
        self.assertEqual(self.card("c1")["quantity"], 5)
        self.assertTrue(any(n.key == "est_card_qty_e1_c1" for n in self.at.number_input))
        self.card("c1")["quantity"] = 6                                             # modifiée ailleurs (ex. fusion d'un doublon)
        self.at.run()
        key = "est_card_qty_e1_c1_v1"
        self.assertTrue(any(n.key == key for n in self.at.number_input))            # champ recréé : plus d'ancienne valeur renvoyée par le navigateur
        self.assertEqual(next(n for n in self.at.number_input if n.key == key).value, 6)
        self.assertEqual(self.card("c1")["quantity"], 6)

    def test_cote_change_marks_manual_and_copies_to_price_cache(self):
        self.cote("c1").set_value("9,50").run()
        self.assertEqual(len(self.at.exception), 0)
        card = self.card("c1")
        self.assertAlmostEqual(card["cote"], 9.5)
        self.assertEqual(card["market_price_origin"], "manual")
        self.assertAlmostEqual(card["manual_price"], 9.5)
        self.assertEqual(card["quantity"], 2)
        self.assertEqual(self.saves(), 1)
        self.cache_save.assert_called_once()
        entries = self.at.session_state["market_price_cache"]["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(next(iter(entries.values()))["reference_price"], 9.5)

    def test_no_real_change_means_no_write(self):
        self.cote("c1").set_value("7,001").run()      # écart < 0,01 € : même cote
        self.qty("c1").set_value(2).run()              # même quantité
        self.assertEqual(self.saves(), 0)
        self.cache_save.assert_not_called()
        self.assertEqual(self.card("c1")["market_price_origin"], "auto")

    def test_several_cards_in_a_row_no_loss_no_double_save(self):
        self.cote("c1").set_value("9,50").run()
        self.qty("c2").set_value(4).run()
        self.assertAlmostEqual(self.card("c1")["cote"], 9.5)
        self.assertEqual(self.card("c2")["quantity"], 4)
        self.assertEqual(self.card("c2")["market_price_origin"], "auto")
        self.assertEqual(self.saves(), 2)
        self.at.run()                                    # simple rerun : rien de plus n'est écrit
        self.assertEqual(self.saves(), 2)
        self.assertEqual(self.cache_save.call_count, 1)
        # clés de widgets stables après les sauvegardes
        self.assertEqual(self.qty("c1").key, "est_card_qty_e1_c1")
        self.assertEqual(self.cote("c2").key, "est_card_cote_e1_c2")

    def test_image_buttons_do_not_write_widget_state_after_instantiation(self):
        src = inspect.getsource(estimations._render_open_estimation)
        block = src[src.index('"Utiliser la cote auto"'):src.index('foot_cols = st.columns')]
        self.assertNotIn("st.session_state[", block)


class StaleQuantityCallbackTest(unittest.TestCase):
    def test_old_field_value_is_ignored_after_quantity_changed_elsewhere(self):
        card = {"uid": "c1", "quantity": 4}
        saved = []
        state = {"qty_old": 3, "epoch": 1}                                          # le champ d'origine (époque 0) renvoie encore 3
        kwargs = dict(card=card, estimate={}, edata={}, market_cache={}, save_estimations_func=lambda d: saved.append(1),
                      parse_float_input_func=lambda t, d=0.0: d, qty_key="qty_old", cote_key="cote", qty_epoch_key="epoch", qty_rendered_key="rendered")
        with mock.patch.object(estimations.st, "session_state", state):
            estimations._autosave_estimation_card_field("qty", qty_epoch=0, **kwargs)
            self.assertEqual((card["quantity"], saved), (4, []))                    # ignoré : la fusion (4) n'est pas écrasée
            state.update(qty_old=5, epoch=0)
            estimations._autosave_estimation_card_field("qty", qty_epoch=0, **kwargs)
            self.assertEqual((card["quantity"], len(saved), state["rendered"]), (5, 1, 5))   # vraie saisie : enregistrée


if __name__ == "__main__":
    unittest.main()

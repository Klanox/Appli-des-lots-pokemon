"""Cartes suivies (Estimations) : affichage progressif au défilement, sans bouton « Afficher plus » — données temporaires.

Même sentinelle que Historique/Collection (ui/infinite_scroll.render_infinite_sentinel). Le clic du bouton caché avance le compteur DANS le
callback : la page n'est donc pas rendue deux fois par lot. Aucun réseau, aucune donnée réelle.
"""
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from ui.pages import estimations

ROOT = str(Path(__file__).resolve().parents[1])
TOTAL = 40

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
        "cards": [{"uid": f"c{i}", "name": f"Carte {i}", "number": str(i), "set": "Set", "quantity": 1, "cote": 7.0,
                   "market_price_origin": "auto", "auto_price": 7.0, "lang": "fr"} for i in range(1, %(total)d + 1)]}]
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
    run_html_func=lambda body, height=0: None,
)
''' % {"root": ROOT, "total": TOTAL}


class ProgressiveTrackedCardsTest(unittest.TestCase):
    def setUp(self):
        self.rendered = []
        real_render = estimations._render_tracked_card

        def counting_render(card, *a, **k):
            self.rendered.append(card.get("uid"))
            return real_render(card, *a, **k)

        patches = [
            mock.patch.object(estimations, "save_market_price_cache", mock.Mock(return_value={"ok": True})),
            mock.patch.object(estimations, "st_keyup", lambda label, value="", key=None, **k: __import__("streamlit").text_input(label, value=value, key=key)),
            mock.patch.object(estimations, "render_lot_image_upload_bridge", lambda key=None: None),
            mock.patch.object(estimations, "_manual_estimation_image_dir", lambda: "/nonexistent-never-written"),
            mock.patch.object(estimations, "_render_tracked_card", counting_render),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.at = AppTest.from_string(APP, default_timeout=60)
        self.at.run()
        self.assertEqual(len(self.at.exception), 0, [e.value for e in self.at.exception])

    def caption(self):
        return next(c.value for c in self.at.caption if "cartes affichées sur" in c.value)

    def autoload_buttons(self):
        return [b for b in self.at.button if b.key and b.key.startswith("autoload_button_est_tracked_e1_")]

    def card_widgets(self):
        return [n for n in self.at.number_input if n.key and n.key.startswith("est_card_qty_e1_")]

    def test_no_manual_show_more_button_and_first_batch_only(self):
        self.assertNotIn("est_show_more_cards_e1", [b.key for b in self.at.button])
        # Le seul bouton « Afficher plus » restant est celui de la sentinelle, masqué en CSS et cliqué par le défilement (comme Historique).
        self.assertEqual([b.key for b in self.at.button if "Afficher plus" in (b.label or "")], ["autoload_button_est_tracked_e1_16"])
        self.assertTrue(self.caption().startswith("16 cartes affichées sur 40"))
        self.assertEqual(len(self.card_widgets()), 16)
        self.assertEqual(len(self.autoload_buttons()), 1)

    def test_hidden_button_loads_next_batches_then_disappears(self):
        self.autoload_buttons()[0].click().run()
        self.assertTrue(self.caption().startswith("32 cartes affichées sur 40"))
        self.assertEqual(len(self.card_widgets()), 32)
        self.autoload_buttons()[0].click().run()
        self.assertTrue(self.caption().startswith("40 cartes affichées sur 40"))
        self.assertEqual(len(self.card_widgets()), 40)
        self.assertEqual(self.autoload_buttons(), [])
        self.assertEqual(len(self.at.exception), 0)

    def test_batch_click_renders_the_page_once_not_twice(self):
        self.rendered.clear()
        self.autoload_buttons()[0].click().run()
        self.assertEqual(len(self.rendered), 32)                 # 32 cartes rendues une seule fois (pas 16 puis 32)

    def test_quantity_edit_keeps_the_loaded_cards(self):
        self.autoload_buttons()[0].click().run()
        next(n for n in self.card_widgets() if n.key == "est_card_qty_e1_c40").set_value(3).run()
        self.assertEqual(self.at.session_state["edata"]["estimations"][0]["cards"][39]["quantity"], 3)
        self.assertTrue(self.caption().startswith("32 cartes affichées sur 40"))
        self.assertEqual(len(self.card_widgets()), 32)

    def test_adding_a_card_returns_to_first_batch_and_shows_it_first(self):
        self.autoload_buttons()[0].click().run()
        cards = self.at.session_state["edata"]["estimations"][0]["cards"]
        cards.append({"uid": "cnew", "name": "Nouvelle", "number": "99", "set": "Set", "quantity": 1, "cote": 5.0,
                      "market_price_origin": "auto", "auto_price": 5.0, "lang": "fr"})
        self.at.run()
        self.assertTrue(self.caption().startswith("16 cartes affichées sur 41"))
        self.assertEqual(len(self.card_widgets()), 16)
        self.assertEqual(self.card_widgets()[0].key, "est_card_qty_e1_cnew")

    def test_changing_the_filter_returns_to_first_batch(self):
        self.autoload_buttons()[0].click().run()
        flt = next(t for t in self.at.text_input if t.key == "est_internal_card_search_e1")
        flt.set_value("Carte 1").run()                           # « 1 » : 1, 10..19, 21, 31 = 13 résultats
        self.assertTrue(self.caption().startswith("13 cartes affichées sur 13"))
        flt = next(t for t in self.at.text_input if t.key == "est_internal_card_search_e1")
        flt.set_value("").run()
        self.assertTrue(self.caption().startswith("16 cartes affichées sur 40"))


if __name__ == "__main__":
    unittest.main()

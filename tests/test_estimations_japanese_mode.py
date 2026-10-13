"""Mode « Cartes japonaises » des Estimations : recherche dans le cache FR, carte marquée japonaise, jamais de cote auto.

Données temporaires uniquement : cache de cotes en mémoire, écritures disque / Cloud remplacées par des espions.
"""
import copy
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from services.market_price_cache_service import card_cache_key
from ui.pages import estimations

ROOT = str(Path(__file__).resolve().parents[1])

FR_CARD = {"name": "Koraidon-ex", "number": "231", "set": "Écarlate et Violet", "set_id": "sv01", "rarity": "Rare", "lang": "fr"}
FR_ENTRY = {"reference_price": 12.5, "price_source": "test", "confidence": "fiable", "origin": "api_auto", "updated_at": "2099-01-01T00:00:00+00:00"}


def _cache_for(card):
    return {"entries": {card_cache_key(card): dict(FR_ENTRY)}}


class JapaneseCoteAutoGuardsTest(unittest.TestCase):
    def test_add_time_suggestion_skips_japanese_and_keeps_french(self):
        fr = {**FR_CARD, "quantity": 1, "cote": 0.0}
        jp = {**FR_CARD, "quantity": 1, "cote": 0.0, "lang": "ja", "special": "Japonaise"}
        cache = _cache_for(FR_CARD)
        res_fr = estimations._apply_market_price_suggestion(fr, cache)
        res_jp = estimations._apply_market_price_suggestion(jp, cache)
        self.assertTrue(res_fr["applied"])
        self.assertEqual(fr["cote"], 12.5)
        self.assertFalse(res_jp["applied"])
        self.assertEqual(jp["cote"], 0.0)
        self.assertNotIn("auto_price", jp)
        self.assertNotEqual(jp.get("market_price_origin"), "auto")

    def test_quantity_change_auto_refresh_ignores_japanese(self):
        cache = _cache_for(FR_CARD)
        for lang, expected_cote in (("fr", 12.5), ("ja", 3.0)):
            card = {**FR_CARD, "lang": lang, "quantity": 1, "cote": 3.0, "market_price_origin": "auto"}
            if lang == "ja":
                card["special"] = "Japonaise"
            state = {}
            with mock.patch.object(estimations.st, "session_state", state):
                self.assertIsNone(estimations._auto_refresh_card_market_price(card, cache, "k"))   # 1re vue = référence
                card["quantity"] = 2
                estimations._auto_refresh_card_market_price(card, cache, "k")
            self.assertEqual(card["cote"], expected_cote, lang)

    def test_badge_never_uses_french_entry_for_japanese(self):
        jp = {**FR_CARD, "lang": "ja", "special": "Japonaise", "cote": 0.0}
        label, css = estimations._market_badge_info(jp, _cache_for(FR_CARD))
        self.assertEqual(css, "none")
        self.assertIn("Aucune cote automatique", label)

    def test_japanese_stamp_not_offered_in_special_options(self):
        self.assertNotIn("Japonaise", estimations._ESTIMATION_SPECIAL_OPTIONS)
        self.assertIn("Reverse", estimations._ESTIMATION_SPECIAL_OPTIONS)


APP = '''
import sys
sys.path.insert(0, %(root)r)
import copy
import streamlit as st
from services.estimations_service import default_estimations_data, normalize_estimations_data, estimation_totals
from services.market_price_cache_service import card_cache_key
from ui.pages import estimations as E
from utils import fp, normalize_name

FR = %(fr)r
ENTRY = %(entry)r
if "edata" not in st.session_state:
    edata = normalize_estimations_data(default_estimations_data())
    edata["estimations"] = [{"uid": "e1", "name": "Estimation A", "source": "Vinted", "seller_price": 40, "status": "À analyser", "cards": [
        {"uid": "old1", "name": "Vieille carte", "number": "1", "set": "S", "quantity": 1, "cote": 0.0, "lang": "ja", "special": "Japonaise, Stamp"}]}]
    st.session_state["edata"] = edata
    st.session_state["calls"] = []
    st.session_state["market_price_cache"] = {"entries": {card_cache_key(FR): dict(ENTRY)}}
edata = st.session_state["edata"]
est = edata["estimations"][0]
def save(_d=None):
    st.session_state["calls"].append("save")
def add_card(estimate, name, number, cote, qty, condition, specials, note, is_collection, match):
    estimate["cards"].append({"uid": "new_%%d" %% len(estimate["cards"]), "name": name, "number": number, "set": FR["set"], "set_id": FR["set_id"],
        "quantity": int(qty or 1), "cote": 0.0, "condition": condition, "special": ", ".join(specials), "lang": FR["lang"]})
E._render_open_estimation(
    estimate=est, totals=estimation_totals(est, edata["settings"]), settings=edata["settings"], edata=edata, uid="e1",
    save_estimations_func=save, add_estimation_card_func=add_card, ld_func=lambda: {"lots": []}, sd_func=lambda *a, **k: None,
    fetch_listing_preview_image_func=lambda *a, **k: "", cardmarket_search_url_func=lambda *a, **k: "https://example.invalid",
    search_in_cache_func=lambda *a, **k: [], img_with_fallback_func=lambda *a, **k: "",
    fp_func=fp, normalize_name_func=normalize_name,
    parse_float_input_func=lambda t, d=0.0: float(str(t).replace(",", ".")) if str(t).strip() else d,
    new_uid_func=lambda p="x": p + "_t", is_mobile_mode_func=lambda: False, ecd_func=lambda c, s, l="fr": c,
    proxy_img_func=lambda u, *a, **k: u, cache_enrichment_func=None, market_cache=st.session_state["market_price_cache"],
)
''' % {"root": ROOT, "fr": FR_CARD, "entry": FR_ENTRY}


class JapaneseModeSearchTest(unittest.TestCase):
    def setUp(self):
        self.search_calls = []
        outer = self

        def fake_suggestions(query, number, search_in_cache_func, ecd_func, normalize_name_func, limit=8, language="fr"):
            outer.search_calls.append(language)
            return [{"card": dict(FR_CARD), "match": (dict(FR_CARD), FR_CARD["set"])}]

        patches = [
            mock.patch.object(estimations, "_card_suggestions", fake_suggestions),
            mock.patch.object(estimations, "save_market_price_cache", mock.Mock()),
            mock.patch.object(estimations, "_ensure_japanese_cards_cache", mock.Mock(side_effect=AssertionError("cache JP ne doit plus être utilisé"))),
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

    def _search(self, jp):
        name = next(t for t in self.at.text_input if "Rechercher" in t.label)
        name.set_value("Koraidon").run()
        if jp:
            next(c for c in self.at.checkbox if c.label == "Cartes japonaises").check().run()
        self.assertEqual(len(self.at.exception), 0, [e.value for e in self.at.exception])

    def _captions(self):
        return " | ".join(c.value for c in self.at.caption)

    def test_japanese_checked_searches_french_cache_without_unavailable_message(self):
        self._search(jp=True)
        self.assertTrue(self.search_calls and set(self.search_calls) == {"fr"}, self.search_calls)
        caps = self._captions()
        self.assertIn("Recherche dans le cache FR (cartes japonaises : cote auto désactivée)", caps)
        self.assertNotIn("cache JP indisponible", caps)
        self.assertIn("Choisir", [b.label for b in self.at.button])           # des résultats FR sont affichés

    def test_picking_a_result_in_japanese_mode_adds_japanese_card_without_auto_cote(self):
        self._search(jp=True)
        next(b for b in self.at.button if b.label == "Choisir").click().run()
        self.assertEqual(len(self.at.exception), 0, [e.value for e in self.at.exception])
        cards = self.at.session_state["edata"]["estimations"][0]["cards"]
        new = cards[-1]
        self.assertEqual(new["name"], "Koraidon-ex")
        self.assertEqual(new["number"], "231")
        self.assertEqual(new.get("lang"), "ja")
        self.assertIn("Japonaise", str(new.get("special")))
        self.assertEqual(new["cote"], 0.0)
        self.assertNotIn("auto_price", new)
        self.assertNotEqual(new.get("market_price_origin"), "auto")

    def test_picking_a_result_in_french_mode_still_gets_auto_cote(self):
        self._search(jp=False)
        next(b for b in self.at.button if b.label == "Choisir").click().run()
        new = self.at.session_state["edata"]["estimations"][0]["cards"][-1]
        self.assertNotEqual(new.get("lang"), "ja")
        self.assertEqual(new["cote"], 12.5)
        self.assertEqual(new.get("market_price_origin"), "auto")

    def test_refresh_button_ignores_japanese_cards(self):
        est = self.at.session_state["edata"]["estimations"][0]
        est["cards"].append({"uid": "jp2", **FR_CARD, "lang": "ja", "special": "Japonaise", "quantity": 1, "cote": 0.0})
        before = copy.deepcopy(est["cards"])
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            next(b for b in self.at.button if b.label == "Actualiser les cotes de cette estimation").click().run()
        self.assertEqual(len(self.at.exception), 0, [e.value for e in self.at.exception])
        after = self.at.session_state["edata"]["estimations"][0]["cards"]
        jp = next(c for c in after if c["uid"] == "jp2")
        self.assertEqual(jp["cote"], 0.0)
        self.assertNotIn("auto_price", jp)
        self.assertIn("refreshed=0", out.getvalue())
        self.assertIn("unavailable=2", out.getvalue())    # les 2 cartes japonaises, comptées « sans cote fiable »

    def test_old_card_with_japanese_stamp_still_renders_and_no_auto_button(self):
        self.assertNotIn("use_auto_price_e1_old1", [b.key for b in self.at.button])
        ms = next(m for m in self.at.multiselect if m.label == "Spécial")
        self.assertNotIn("Japonaise", ms.options)


if __name__ == "__main__":
    unittest.main()

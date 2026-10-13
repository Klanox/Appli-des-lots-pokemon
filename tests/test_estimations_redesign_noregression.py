"""Non-régression de la refonte design de la vue détail Estimations (affichage uniquement).

Données 100 % temporaires, en mémoire : aucune donnée réelle, aucun réseau, aucun cloud.
Vérifie : la page se rend sans erreur, les éléments du nouveau design sont là, et les mêmes
fonctions métier sont appelées avec les mêmes arguments (ajout de carte, EX/V, retrait).
"""
import inspect
import re
import sys
import unittest
from unittest import mock
from pathlib import Path

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

E._manual_estimation_image_dir = lambda: "/nonexistent-never-written"
# Composants JS (non exécutables dans AppTest) remplacés par de simples champs : même clés, même valeurs.
E.st_keyup = lambda label, value="", key=None, **k: st.text_input(label, value=value, key=key)
E.render_lot_image_upload_bridge = lambda key=None: None
if "edata" not in st.session_state:
    edata = normalize_estimations_data(default_estimations_data())
    edata["estimations"] = [{"uid": "e1", "name": "Estimation temporaire", "source": "Vinted", "seller_price": 40,
        "status": "À analyser", "cards": [{"uid": "c1", "name": "Carte test", "number": "1", "set": "Set", "quantity": 2,
        "cote": 7.0, "market_price_origin": "manual", "lang": "fr", "image_url": ""}]}]
    st.session_state["edata"] = edata
    st.session_state["calls"] = []
    st.session_state["market_price_cache"] = {"entries": {}}
edata = st.session_state["edata"]
est = edata["estimations"][0]
def rec(name):
    def f(*a, **k):
        st.session_state["calls"].append(name)
    return f
E._render_open_estimation(
    estimate=est, totals=estimation_totals(est, edata["settings"]), settings=edata["settings"], edata=edata, uid="e1",
    save_estimations_func=rec("save"), add_estimation_card_func=rec("add"), ld_func=lambda: {"lots": []}, sd_func=rec("sd"),
    fetch_listing_preview_image_func=lambda *a, **k: "", cardmarket_search_url_func=lambda *a, **k: "https://example.invalid",
    search_in_cache_func=lambda *a, **k: [], img_with_fallback_func=lambda *a, **k: "",
    fp_func=fp, normalize_name_func=normalize_name, parse_float_input_func=lambda t, d=0.0: float(str(t).replace(",", ".")) if str(t).strip() else d,
    new_uid_func=lambda p="x": p + "_t", is_mobile_mode_func=lambda: False, ecd_func=lambda c, s, l="fr": c,
    proxy_img_func=lambda u, *a, **k: u, cache_enrichment_func=None, market_cache=st.session_state["market_price_cache"],
)
''' % {"root": ROOT}


_PATCHED = ("st_keyup", "render_lot_image_upload_bridge", "_manual_estimation_image_dir")


def _run():
    originals = {name: getattr(estimations, name) for name in _PATCHED}
    try:
        at = AppTest.from_string(APP, default_timeout=30)
        at.run()
    finally:
        for name, value in originals.items():
            setattr(estimations, name, value)
    return at


def _labels(at):
    return [b.label for b in at.button] + [t.label for t in at.text_input] + [s.label for s in at.selectbox]


class RedesignRenderTest(unittest.TestCase):
    def setUp(self):
        self._originals = {name: getattr(estimations, name) for name in _PATCHED}
        self._cache_save = mock.patch.object(estimations, "save_market_price_cache", mock.Mock(return_value={"ok": True}))
        self._cache_save.start()

    def tearDown(self):
        self._cache_save.stop()
        for name, value in self._originals.items():
            setattr(estimations, name, value)

    def test_page_renders_without_error_with_new_layout(self):
        at = _run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        labels = _labels(at)
        for expected in ("← Toutes les estimations", "Finir l’estimation", "+ Ajouter", "Numéro", "Qté", "Note rapide",
                         "Actualiser les cotes de cette estimation"):
            self.assertIn(expected, labels)
        self.assertEqual([m.value for m in at.multiselect if m.label == "Spécial"] is not None, True)
        self.assertIn("État", [s.label for s in at.selectbox])
        import html
        joined = html.unescape(" ".join(m.value for m in at.markdown))
        for kpi in ("Type d'achat", "Prix demandé", "Cote totale", "% cote", "Écart à la cote", "Rachat max", "Cartes"):
            self.assertIn(f"<span>{kpi}</span>", joined)
        self.assertEqual(joined.count('class="est-kpi '), 7)
        self.assertIn("EX / V basiques", joined)
        self.assertIn("Réglages", joined)
        expanders = [e.label for e in at.expander]
        for expected in ("Modifier la quantité", "Mémoire de cotes", "Réglages de rachat", "Collection", "Détails avancés et actions"):
            self.assertIn(expected, expanders)
        self.assertNotIn("Ajouter une carte dans cette estimation", expanders)

    def test_special_options_are_the_existing_list_without_japanese_stamp(self):
        at = _run()
        special = next(m for m in at.multiselect if m.label == "Spécial")
        self.assertEqual(
            list(special.options),
            ["Reverse", "1ère Éd", "Collection", "Scellé", "Stamp", "Promo", "Master Ball", "Poké Ball"],
        )

    def test_add_button_without_name_does_not_call_business_functions(self):
        at = _run()
        next(b for b in at.button if b.label == "+ Ajouter").click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertIn("Nom requis.", [e.value for e in at.error])
        self.assertEqual(at.session_state["calls"], [])

    def test_quick_bulk_same_business_flow(self):
        at = _run()
        next(n for n in at.number_input if n.key == "quick_bulk_ex_qty_e1").set_value(3).run()
        next(b for b in at.button if b.label == "Ajouter les EX / V basiques").click().run()
        self.assertEqual(len(at.exception), 0)
        cards = at.session_state["edata"]["estimations"][0]["cards"]
        bulk = [c for c in cards if c.get("entry_type") == "quick_bulk"]
        self.assertEqual([(c["bulk_type"], c["quantity"]) for c in bulk], [("ex", 3)])
        self.assertEqual(at.session_state["calls"], ["save"])

    def test_remove_card_same_business_flow(self):
        at = _run()
        next(b for b in at.button if b.label == "Retirer").click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.session_state["edata"]["estimations"][0]["cards"], [])
        self.assertEqual(at.session_state["calls"], ["save"])


class RedesignSourceTest(unittest.TestCase):
    def test_business_calls_are_still_in_the_detail_view(self):
        source = inspect.getsource(estimations._render_open_estimation)
        for needle in (
            "add_estimation_card_func(", "_apply_market_price_suggestion(", "refresh_estimation_prices(", "only_due=True",
            "_new_quick_bulk_entry(", "sd_func(cd_real)", 'new_uid_func("lot")', "_find_duplicate_card(",
            "_auto_refresh_card_market_price(", "save_estimations_func(edata)",
        ):
            self.assertIn(needle, source)

    def test_card_save_calls_are_the_same_in_the_autosave_callback(self):
        source = inspect.getsource(estimations._autosave_estimation_card_field)
        for needle in ("mark_manual_price(card, new_cote)", "upsert_market_price(", "save_market_price_cache(market_cache)",
                       "save_estimations_func(edata)", "_mark_estimation_needs_review(estimate)", 'origin="manual_estimation"'):
            self.assertIn(needle, source)

    def test_session_keys_unchanged(self):
        source = inspect.getsource(estimations._render_open_estimation)
        for key in ("est_add_name_keyup_{uid}", "est_add_number_box_{uid}", "est_add_qty_box_{uid}", "est_add_condition_box_{uid}",
                    "est_add_special_box_{uid}", "est_add_note_box_{uid}", "est_add_japanese_mode_{uid}", "est_pending_add_reset_{uid}",
                    "add_est_card_box_submit_{uid}", "est_workflow_status_{uid}", "quick_bulk_ex_qty_{uid}", "quick_bulk_v_qty_{uid}",
                    "refresh_market_prices_{uid}", "est_finish_open_{uid}", "del_est_card_box_{uid}_{card_uid}"):
            self.assertIn(key, source)

    def test_layout_css_is_balanced_and_scoped(self):
        css = estimations._DETAIL_LAYOUT_CSS
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn("#6D4AFF", css)
        self.assertIn("#E6E3F3", css)
        self.assertIn("290px", css)
        self.assertNotIn("__GAP__", css)


if __name__ == "__main__":
    unittest.main()

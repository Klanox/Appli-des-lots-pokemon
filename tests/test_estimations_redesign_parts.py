"""Non-régression design, parties A (cartes suivies), B (suggestions) et C (liste) — données temporaires.

Les composants JavaScript (st_keyup, pont d'upload) sont remplacés par de simples champs : mêmes clés, mêmes valeurs.
Aucune donnée réelle, aucun réseau, aucun cloud.
"""
import html
import inspect
import unittest
from unittest import mock
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui.pages import estimations

ROOT = str(Path(__file__).resolve().parents[1])

PRELUDE = '''
import sys
sys.path.insert(0, %(root)r)
import streamlit as st
from services.estimations_service import default_estimations_data, normalize_estimations_data, estimation_totals
from ui.pages import estimations as E
from utils import fp, normalize_name

E._manual_estimation_image_dir = lambda: "/nonexistent-never-written"
E.st_keyup = lambda label, value="", key=None, **k: st.text_input(label, value=value, key=key)
E.render_lot_image_upload_bridge = lambda key=None: None
if "edata" not in st.session_state:
    edata = normalize_estimations_data(default_estimations_data())
    def mk(uid, name, price, ncards):
        return {"uid": uid, "name": name, "source": "Vinted", "seller_price": price, "status": "À analyser",
                "cards": [{"uid": f"{uid}c{i}", "name": f"Carte {i}", "number": str(i), "set": "Set", "quantity": 2, "cote": 7.0,
                           "market_price_origin": "manual", "lang": "fr", "special": "GG" if i == 0 else ""} for i in range(ncards)]}
    edata["estimations"] = [mk("e1", "Estimation A", 40, 2), mk("e2", "Estimation B", 90, 1)]
    st.session_state["edata"] = edata
    st.session_state["calls"] = []
    st.session_state["market_price_cache"] = {"entries": {}}
edata = st.session_state["edata"]
def rec(name):
    def f(*a, **k):
        st.session_state["calls"].append((name, a))
    return f
noop = lambda *a, **k: None
parse = lambda t, d=0.0: float(str(t).replace(",", ".")) if str(t).strip() else d
''' % {"root": ROOT}

DETAIL = '''
est = edata["estimations"][0]
E._render_open_estimation(
    estimate=est, totals=estimation_totals(est, edata["settings"]), settings=edata["settings"], edata=edata, uid="e1",
    save_estimations_func=rec("save"), add_estimation_card_func=rec("add"), ld_func=lambda: {"lots": []}, sd_func=rec("sd"),
    fetch_listing_preview_image_func=lambda *a, **k: "", cardmarket_search_url_func=lambda *a, **k: "https://example.invalid",
    search_in_cache_func=lambda *a, **k: [], img_with_fallback_func=lambda *a, **k: "",
    fp_func=fp, normalize_name_func=normalize_name, parse_float_input_func=parse,
    new_uid_func=lambda p="x": p + "_t", is_mobile_mode_func=lambda: False, ecd_func=lambda c, s, l="fr": c,
    proxy_img_func=lambda u, *a, **k: u, cache_enrichment_func=None, market_cache=st.session_state["market_price_cache"],
)
'''

SUGGEST = '''
def _fake(*a, **k):
    out = []
    for i in range(3):
        c = {"name": f"Pondralugon {i}", "number": str(100 + i), "set": "Couronne", "rarity": "Rare", "lang": "fr", "image_url": "https://example.invalid/x.png"}
        out.append({"card": c, "match": (c, "Couronne")})
    return out
E._card_suggestions = _fake
'''

LIST_PAGE = '''
from ui.pages.estimations import render_estimations_page
render_estimations_page(
    load_estimations_func=lambda: edata, save_estimations_func=rec("save"), add_estimation_card_func=rec("add"),
    estimation_totals_func=estimation_totals, ld_func=lambda: {"lots": []}, sd_func=rec("sd"),
    fetch_listing_preview_image_func=lambda *a, **k: "", cardmarket_search_url_func=lambda *a, **k: "https://example.invalid",
    search_in_cache_func=lambda *a, **k: [], proxy_img_func=lambda u, *a, **k: u, img_with_fallback_func=lambda *a, **k: "",
    render_page_header_func=lambda t, s, i: f"<div>{t}</div>", fp_func=fp, normalize_name_func=normalize_name,
    parse_float_input_func=parse, new_uid_func=lambda p="x": p + "_t", is_mobile_mode_func=lambda: False,
    ecd_func=lambda c, s, l="fr": c, run_html_func=lambda *a, **k: None,
)
'''


_PATCHED = ("_card_suggestions", "st_keyup", "render_lot_image_upload_bridge", "_manual_estimation_image_dir")


def _restore(originals):
    for name, value in originals.items():
        setattr(estimations, name, value)


def _run(body):
    # Le script d'AppTest remplace des attributs du module : on les restaure pour ne pas polluer les autres tests.
    originals = {name: getattr(estimations, name) for name in _PATCHED}
    try:
        at = AppTest.from_string(PRELUDE + body, default_timeout=30)
        at.run()
    finally:
        _restore(originals)
    return at


def _md(at):
    return html.unescape(" ".join(m.value for m in at.markdown))


class _Restoring(unittest.TestCase):
    def setUp(self):
        self._originals = {name: getattr(estimations, name) for name in _PATCHED}
        # Les callbacks d'enregistrement s'exécutent avant le script : jamais d'écriture réelle du cache de prix.
        self._cache_save = mock.patch.object(estimations, "save_market_price_cache", mock.Mock(return_value={"ok": True}))
        self._cache_save.start()

    def tearDown(self):
        self._cache_save.stop()
        _restore(self._originals)


class PartACardsTest(_Restoring):
    def test_card_layout_and_same_business_flow(self):
        at = _run(DETAIL)
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        md = _md(at)
        # nom + icône image, puis "#numéro · xQté" avec pastille du spécial, sur une ligne
        self.assertIn('class="est-tracked-meta"', md)
        self.assertIn("#0 · x2", md)
        self.assertIn("est-pill", md)
        # bas de carte : lien Cardmarket + Retirer, et Qté et Cote toujours présents (enregistrement automatique)
        self.assertIn('class="est-cardmarket-link"', md)
        self.assertEqual([b.label for b in at.button].count("Retirer"), 2)
        self.assertIn("Cote (€)", [t.label for t in at.text_input])
        # même action : enregistrer une cote passe par la même logique (saisie manuelle + sauvegarde)
        cote_inputs = [x for x in at.text_input if (x.key or "").startswith("est_card_cote_e1_")]
        first_uid = cote_inputs[0].key.rsplit("_", 1)[-1]
        cote_inputs[0].set_value("9,50")
        at.run()
        self.assertEqual(len(at.exception), 0)
        card = next(c for c in at.session_state["edata"]["estimations"][0]["cards"] if c["uid"].endswith(first_uid))
        self.assertAlmostEqual(card["cote"], 9.5)
        self.assertIn(card.get("market_price_origin"), {"manual", "legacy_manual"})
        self.assertEqual([c[0] for c in at.session_state["calls"]], ["save"])

    def test_part_a_css_scoped(self):
        css = estimations._DETAIL_LAYOUT_CSS
        self.assertEqual(css.count("{"), css.count("}"))
        for needle in ("max-width", "est-tracked-meta", "#6D4AFF", "#E6E3F3", "stMarkdownContainer"):
            self.assertIn(needle, css)
        # le CSS de la vue est injecté en dernier pour gagner les égalités de priorité
        source = inspect.getsource(estimations._render_css)
        self.assertTrue(source.rstrip().endswith("st.markdown(_DETAIL_LAYOUT_CSS, unsafe_allow_html=True)"))


class PartBSuggestionsTest(_Restoring):
    def _typed(self):
        at = _run(SUGGEST + DETAIL)
        next(t for t in at.text_input if t.key == "est_add_name_keyup_e1").set_value("pondra").run()
        return at

    def test_thumbnail_tiles_without_blank_lines_and_same_choose_action(self):
        at = self._typed()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        blocks = [m.value for m in at.markdown if "est-suggestion-card" in m.value]
        self.assertEqual(len(blocks), 3)
        for block in blocks:
            self.assertIn('class="est-sugg-thumb"', block)
            self.assertNotIn("\n\n", block)
            self.assertNotIn("\n", block)
        buttons = [b for b in at.button if b.label == "Choisir"]
        self.assertEqual(len(buttons), 3)
        buttons[1].click().run()
        adds = [c for c in at.session_state["calls"] if c[0] == "add"]
        self.assertEqual(len(adds), 1)
        args = adds[0][1]
        self.assertEqual((args[1], args[2], args[3], args[4], args[5], args[6], args[7], args[8]),
                         ("Pondralugon 1", "101", "0,00", "1", "NM", [], "", False))
        self.assertIn("save", [c[0] for c in at.session_state["calls"]])

    def test_compact_suggestion_keeps_single_line_html_without_alias(self):
        source = inspect.getsource(estimations._render_compact_suggestion)
        self.assertIn("_suggestion_image_info(enriched)", source)
        self.assertNotIn('"""', source)


class PartCListTest(_Restoring):
    def test_list_grid_renders_same_values_and_navigation(self):
        at = _run(LIST_PAGE)
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        md = _md(at)
        self.assertEqual(md.count('class="est-list-card '), 2)
        self.assertIn("Estimation A", md)
        self.assertIn("Estimation B", md)
        self.assertNotIn("Créer une nouvelle estimation</strong>", md)
        self.assertIn("+ Nouvelle estimation", [b.label for b in at.button])
        self.assertIn("est_box_search", [t.key for t in at.text_input])
        # mêmes valeurs qu'avant : prix demandé / cote / écart / % issus des mêmes totaux
        from services.estimations_service import estimation_totals
        est = at.session_state["edata"]["estimations"][0]
        totals = estimation_totals(est, at.session_state["edata"]["settings"])
        self.assertIn(f"{totals['real_pct']:.1f}% de la cote", md)
        # ouvrir -> vue détail (mêmes fonctions), retour -> liste
        next(b for b in at.button if b.key == "toggle_est_box_e1").click().run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertEqual(at.session_state["active_estimation_uid"], "e1")
        self.assertIn("← Toutes les estimations", [b.label for b in at.button])
        next(b for b in at.button if b.label == "← Toutes les estimations").click().run()
        self.assertEqual(at.session_state["active_estimation_uid"], "")
        self.assertEqual(_md(at).count('class="est-list-card '), 2)

    def test_creation_form_moved_to_dialog_with_same_logic(self):
        source = inspect.getsource(estimations.render_estimations_page)
        self.assertIn('st.dialog("Créer une nouvelle estimation")', source)
        for needle in ('st.form("new_estimation_box")', 'new_uid_func("estimate")', 'edata["estimations"].append(estimate)',
                       'st.session_state["active_estimation_uid"] = estimate["uid"]'):
            self.assertIn(needle, source)


if __name__ == "__main__":
    unittest.main()

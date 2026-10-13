"""Composant front-end injecté (pause de frappe Qté/Cote, image cassée -> placeholder) et clé du champ Nom (données temporaires)."""
import inspect
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

from test_estimations_japanese_mode import APP, FR_CARD
from ui.pages import estimations


class FrontHelpersSourceTest(unittest.TestCase):
    def test_script_targets_only_card_qty_and_cote_fields(self):
        src = inspect.getsource(estimations._get_est_front_helpers_component)
        self.assertIn('st-key-est_card_qty_', src)
        self.assertIn('st-key-est_card_cote_', src)
        self.assertIn('st-key-est_tracked_grid_', src)
        for other in ("est_add_", "est_search", "number_box", "note_box"):
            self.assertNotIn(other, src)

    def test_thumbnail_html_has_fallback_handler_and_chain(self):
        html = estimations._estimation_image_html("https://exemple.invalid/a.png", "", fallbacks=["https://exemple.invalid/b.png"],
                                                  placeholder_class="est-sugg-thumb-ph")
        self.assertIn("onerror=", html)
        self.assertIn("data-ps-fallbacks=", html)
        self.assertIn("b.png", html)
        self.assertIn("est-sugg-thumb-ph", html)
        self.assertIn("display:none", html)                                         # placeholder prêt à être affiché
        no_url = estimations._estimation_image_html("", "", placeholder_class="est-sugg-thumb-ph")
        self.assertIn("est-sugg-thumb-ph", no_url)
        self.assertNotIn("<img", no_url)


class FrontHelpersImageSafetyTest(unittest.TestCase):
    """L'image qui se charge n'est jamais remplacée ; le placeholder exige un échec confirmé et se retire tout seul."""

    def setUp(self):
        self.src = inspect.getsource(estimations._get_est_front_helpers_component)

    def test_placeholder_only_after_confirmed_failure(self):
        self.assertIn("img.currentSrc", self.src)                                   # image différée / en cours de chargement : ignorée
        self.assertIn("naturalWidth === 0", self.src)
        self.assertIn("setTimeout(() => {", self.src)                               # confirmation différée avant de conclure
        self.assertIn('getAttribute("loading") === "lazy"', self.src)               # image lazy hors écran : ignorée
        self.assertNotIn("scanBrokenImages();\n", self.src)                         # plus de scan immédiat au montage

    def test_placeholder_is_removed_when_image_loads_or_source_changes(self):
        self.assertIn('addEventListener("load", onImgLoad, true)', self.src)
        self.assertIn("MutationObserver", self.src)
        self.assertIn("attributeFilter", self.src)
        self.assertIn("function showImage", self.src)
        self.assertIn("img.complete && img.naturalWidth > 0", self.src)

    def test_dispose_removes_every_listener(self):
        for needle in ('removeEventListener("error", onImgError, true)', 'removeEventListener("load", onImgLoad, true)', "observer.disconnect()"):
            self.assertIn(needle, self.src)


class NameFieldInPlaceResetTest(unittest.TestCase):
    """Le champ Nom garde sa clé (l'iframe st_keyup n'est jamais recréée) ; le composant front le vide en place après un ajout réussi."""

    def setUp(self):
        sugg = [{"card": dict(FR_CARD), "match": (dict(FR_CARD), FR_CARD["set"])}]
        self.helper_calls = []
        for p in [
            mock.patch.object(estimations, "_card_suggestions", lambda query, *a, **k: sugg if str(query or "").strip() else []),
            mock.patch.object(estimations, "save_market_price_cache", mock.Mock()),
            mock.patch.object(estimations, "st_keyup", lambda label, value="", key=None, **k: __import__("streamlit").text_input(label, value=value, key=key)),
            mock.patch.object(estimations, "render_lot_image_upload_bridge", lambda key=None: None),
            mock.patch.object(estimations, "_manual_estimation_image_dir", lambda: "/nonexistent-never-written"),
            mock.patch.object(estimations, "_render_estimations_front_helpers", lambda **kw: self.helper_calls.append(kw)),
        ]:
            p.start()
            self.addCleanup(p.stop)
        self.at = AppTest.from_string(APP, default_timeout=30)
        self.at.run()

    def name_widget(self):
        return next(t for t in self.at.text_input if "Rechercher" in t.label)

    def add(self):
        next(b for b in self.at.button if b.label == "+ Ajouter").click().run()

    def test_key_constant_and_front_token_changes_only_after_success(self):
        self.assertEqual(len(self.at.exception), 0)
        self.assertEqual(self.name_widget().key, "est_add_name_keyup_e1")
        self.assertEqual(self.helper_calls[-1]["name_epoch"], 0)
        self.assertEqual(self.helper_calls[-1]["name_uid"], "e1")
        self.add()                                                                  # nom vide : refusé
        self.assertEqual(self.helper_calls[-1]["name_epoch"], 0)
        self.name_widget().set_value("Koraidon").run()
        self.add()                                                                  # réussi
        self.assertEqual(len(self.at.exception), 0)
        self.assertEqual(self.name_widget().key, "est_add_name_keyup_e1")           # même clé : le composant n'est pas recréé
        self.assertEqual(self.name_widget().value, "")
        self.assertEqual(self.helper_calls[-1]["name_epoch"], 1)
        self.assertEqual(self.helper_calls[-1]["name_placeholder"], "Ex: Marisson AR, Groudon EX magma")
        self.name_widget().set_value("Autre").run()
        self.add()
        self.assertEqual(self.name_widget().key, "est_add_name_keyup_e1")
        self.assertEqual(self.helper_calls[-1]["name_epoch"], 2)
        self.at.run()                                                               # un simple rerun ne change plus le jeton
        self.assertEqual(self.helper_calls[-1]["name_epoch"], 2)

    def test_front_component_clears_name_field_in_place(self):
        src = inspect.getsource(estimations._get_est_front_helpers_component)
        self.assertIn("getElementById(\"input_box\")", src)                         # champ interne de st_keyup
        self.assertIn("dispatchEvent(new hit.frame.contentWindow.Event(\"keyup\"", src)  # remonte la valeur vide à Python
        self.assertIn("nameEpoch > before", src)                                    # uniquement quand le jeton augmente
        self.assertIn("hit.input.value === \"\"", src)                               # rien à faire si le champ est déjà vide


class DuplicateWarningKeepsNameFieldPlaceTest(unittest.TestCase):
    """L'avertissement doublon ne doit ni décaler ni recréer le champ Nom : sa position dans l'arbre d'éléments reste identique (sinon l'iframe st_keyup est recréée = bloc gris)."""

    def setUp(self):
        sugg = [{"card": dict(FR_CARD), "match": (dict(FR_CARD), FR_CARD["set"])}]
        for p in [
            mock.patch.object(estimations, "_card_suggestions", lambda query, *a, **k: sugg if str(query or "").strip() else []),
            mock.patch.object(estimations, "save_market_price_cache", mock.Mock()),
            mock.patch.object(estimations, "st_keyup", lambda label, value="", key=None, **k: __import__("streamlit").text_input(label, value=value, key=key)),
            mock.patch.object(estimations, "render_lot_image_upload_bridge", lambda key=None: None),
            mock.patch.object(estimations, "_manual_estimation_image_dir", lambda: "/nonexistent-never-written"),
            mock.patch.object(estimations, "_render_estimations_front_helpers", lambda **kw: None),
        ]:
            p.start()
            self.addCleanup(p.stop)
        self.at = AppTest.from_string(APP, default_timeout=30)
        self.at.run()

    def name_path(self):
        def walk(block, path):
            for index, child in sorted(block.children.items()):
                if getattr(child, "key", None) == "est_add_name_keyup_e1":
                    return path + [index]
                if hasattr(child, "children"):
                    found = walk(child, path + [index])
                    if found:
                        return found
            return None
        return walk(self.at.main, [])

    def pick(self):
        self.at.text_input[[t.key for t in self.at.text_input].index("est_add_name_keyup_e1")].set_value("Koraidon").run()
        next(b for b in self.at.button if b.label == "Choisir").click().run()

    def test_name_field_position_identical_with_and_without_duplicate_warning(self):
        before = self.name_path()
        self.assertIsNotNone(before)
        self.pick()                                                                 # ajout normal
        self.assertEqual(self.name_path(), before)
        self.pick()                                                                 # même carte : avertissement doublon
        self.assertEqual(len(self.at.exception), 0)
        self.assertTrue(any("déjà présente" in w.value for w in self.at.warning))
        self.assertEqual(self.name_path(), before)                                  # position inchangée AVEC l'avertissement
        next(b for b in self.at.button if b.label == "Annuler").click().run()       # doublon refusé
        self.assertFalse(any("déjà présente" in w.value for w in self.at.warning))
        self.assertEqual(self.name_path(), before)                                  # position inchangée APRÈS


if __name__ == "__main__":
    unittest.main()

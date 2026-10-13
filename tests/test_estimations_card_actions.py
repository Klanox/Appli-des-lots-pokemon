"""Section « Cartes suivies » : cote automatique, éléments retirés, bouton image compact.

Données temporaires uniquement : aucun fichier métier, aucun réseau, aucun Cloud.
"""
import base64
import inspect
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import estimations_service
from services.estimations_service import estimation_totals
from services.market_price_cache_service import card_cache_key
from ui import lot_image_upload_bridge
from ui.pages import estimations

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def make_card(**overrides):
    card = {"uid": "c1", "name": "Pikachu", "number": "58", "set": "Set de Base", "set_id": "BASE1",
            "lang": "fr", "quantity": 1, "condition": "NM", "cote": 10.0, "market_price_origin": "auto"}
    card.update(overrides)
    return card


def make_cache(card, price=12.5):
    return {"entries": {card_cache_key(card): {"reference_price": price, "price_source": "test",
                                               "confidence": "fiable", "updated_at": "2026-10-01T00:00:00+00:00"}}}


class TrackedCardsRemovedElementsTest(unittest.TestCase):
    def test_removed_elements_are_gone_and_kept_ones_remain(self):
        source = inspect.getsource(estimations._render_open_estimation)
        for removed in ('"Actualiser la cote"', "refresh_market_card_", "Payé estimé",
                        "est-card-mini-grid", "st.file_uploader"):
            self.assertNotIn(removed, source)
        self.assertIn("Écart à la cote", source)  # KPI du total de l'estimation : conservé
        for kept in ("Chercher la cote sur Cardmarket", "Actualiser les cotes de cette estimation", "ps-lot-inline-image-btn"):
            self.assertIn(kept, source)

    def test_totals_do_not_depend_on_the_removed_per_card_blocks(self):
        self.assertNotIn("_estimated_paid_for_card", inspect.getsource(estimations_service.estimation_totals))
        estimate = {"uid": "e1", "name": "Test", "source": "Vinted", "seller_price": 40,
                    "cards": [make_card(cote=10.0, quantity=2), make_card(uid="c2", number="4", cote=5.0)]}
        settings = estimations_service.normalize_estimations_data(estimations_service.default_estimations_data())["settings"]
        totals = estimation_totals(estimate, settings)
        self.assertAlmostEqual(totals["total_cote"], 25.0)
        self.assertIn("theoretical_margin", totals)
        self.assertIn("max_buy", totals)


class AutoRefreshCoteTest(unittest.TestCase):
    def run_refresh(self, card, cache, state, counter):
        real = estimations.apply_market_price_to_card

        def counting(*args, **kwargs):
            counter.append(1)
            return real(*args, **kwargs)

        fake_st = SimpleNamespace(session_state=state)
        with patch.object(estimations, "st", fake_st), patch.object(estimations, "apply_market_price_to_card", counting), \
                patch("socket.socket.connect", side_effect=AssertionError("appel réseau interdit")):
            return estimations._auto_refresh_card_market_price(card, cache, "memo")

    def test_refresh_only_when_the_card_really_changes(self):
        card, state, calls = make_card(), {}, []
        cache = make_cache(card)
        self.assertIsNone(self.run_refresh(card, cache, state, calls))  # première vue : simple référence
        for _ in range(3):
            self.assertIsNone(self.run_refresh(card, cache, state, calls))  # reruns sans changement
        self.assertEqual(calls, [])
        card["quantity"] = 3
        result = self.run_refresh(card, cache, state, calls)
        self.assertTrue(result["applied"] and result["changed"])
        self.assertEqual(card["cote"], 12.5)
        self.assertIsNone(self.run_refresh(card, cache, state, calls))  # pas de répétition
        self.assertEqual(len(calls), 1)
        card["condition"] = "EX"
        self.run_refresh(card, cache, state, calls)
        self.assertEqual(len(calls), 2)

    def test_manual_cote_is_never_overwritten(self):
        card = make_card(market_price_origin="manual", cote=7.0, manual_price=7.0)
        state, calls = {}, []
        cache = make_cache(card)
        self.run_refresh(card, cache, state, calls)
        card["quantity"] = 2
        result = self.run_refresh(card, cache, state, calls)
        self.assertFalse(result["applied"])
        self.assertEqual(card["cote"], 7.0)


class DirectImageUploadTest(unittest.TestCase):
    def test_bridge_is_the_one_used_by_the_lots(self):
        self.assertIs(estimations.render_lot_image_upload_bridge, lot_image_upload_bridge.render_lot_image_upload_bridge)

    def test_upload_is_saved_in_a_temporary_folder_only(self):
        card = make_card()
        registered = []
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(estimations, "_manual_estimation_image_dir", lambda: folder), \
                patch.object(estimations, "register_custom_card_image", lambda *a, **k: registered.append(a)):
            data_url = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
            ok, message, path = estimations._save_direct_card_image_upload(card, "ma carte.PNG", "image/png", data_url)
            self.assertTrue(ok, message)
            self.assertTrue(os.path.abspath(path).startswith(os.path.abspath(folder)))
            with open(path, "rb") as saved:
                self.assertEqual(saved.read(), PNG_1PX)
            self.assertEqual(len(registered), 1)
            self.assertEqual(estimations._save_direct_card_image_upload(card, "x.png", "image/png", "data:image/png;base64,@@")[:2],
                             (False, "Image illisible."))
            self.assertEqual(estimations._save_direct_card_image_upload(card, "x.png", "image/png", "data:image/png;base64,")[:2],
                             (False, "Image vide."))


if __name__ == "__main__":
    unittest.main()

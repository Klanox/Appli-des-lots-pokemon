import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.custom_card_image_service import (
    register_custom_card_image,
    remove_custom_card_image,
    resolve_custom_card_image,
)
from services.estimations_service import (
    DEFAULT_ESTIMATION_SOURCES,
    automatic_offer_amount,
    estimation_offer_is_sent,
    estimation_offer_mode,
    estimation_totals,
    price_to_cote_pct,
)
from ui.pages import estimations
from ui.pages.collection import _collection_card_image_url
from ui.pages.sales import _sale_image_candidates
from ui.pages.vinted_listings import _card_image
from utils import normalize_name


class EstimationsV2Tests(unittest.TestCase):
    def setUp(self):
        estimations._ESTIMATION_IMAGE_RESOLUTION_CACHE.clear()
        estimations._ESTIMATION_SUGGESTIONS_CACHE.clear()

    def test_canonical_price_to_cote_percentage(self):
        self.assertAlmostEqual(price_to_cote_pct(87, 160.50), 54.205607, places=5)
        self.assertIsNone(price_to_cote_pct(87, 0))
        self.assertIsNone(price_to_cote_pct(0, 160.50))
        self.assertIsNone(price_to_cote_pct("inconnu", 160.50))

    def test_quick_bulk_cost_never_inflates_seller_price_percentage(self):
        estimate = {
            "source": "Vinted",
            "seller_price": 87.0,
            "cards": [
                {"name": "Évoli", "cote": 150.50, "quantity": 1},
                {
                    "entry_type": "quick_bulk",
                    "bulk_type": "v",
                    "quantity": 5,
                    "purchase_unit_price": 0.50,
                    "resale_unit_price": 2.0,
                },
            ],
        }
        totals = estimation_totals(estimate, {"default_source": "Vinted", "sources": {"Vinted": 55.0}})
        self.assertEqual(totals["total_cote"], 160.50)
        self.assertEqual(totals["quick_bulk_cost"], 2.50)
        self.assertEqual(totals["seller_price"], 87.0)
        self.assertAlmostEqual(totals["real_pct"], 54.205607, places=5)

    def test_vinted_offer_defaults_to_55_percent_and_remains_configurable(self):
        estimate = {"source": "Vinted", "cards": []}
        self.assertEqual(DEFAULT_ESTIMATION_SOURCES["Vinted"], 55.0)
        self.assertEqual(automatic_offer_amount(estimate, {"sources": {}}, 200), 110.0)
        self.assertEqual(automatic_offer_amount(estimate, {"sources": {"Vinted": 52.5}}, 200), 105.0)

    def test_auto_offer_recalculates_but_custom_and_sent_offers_are_preserved(self):
        settings = {"default_source": "Vinted", "sources": {"Vinted": 55.0}}
        auto = {"source": "Vinted", "offer_mode": "auto", "offer_amount": 90.0, "cards": [{"cote": 200.0}]}
        custom = {"source": "Vinted", "offer_mode": "custom", "offer_amount": 90.0, "cards": [{"cote": 200.0}]}
        sent = {**auto, "offer_sent_at": "2026-09-08T10:00:00"}
        self.assertEqual(estimation_totals(auto, settings)["offer_amount"], 110.0)
        self.assertEqual(estimation_totals(custom, settings)["offer_amount"], 90.0)
        self.assertEqual(estimation_totals(sent, settings)["offer_amount"], 90.0)
        self.assertEqual(estimation_offer_mode({"offer_amount": 90.0}), "custom")
        self.assertTrue(estimation_offer_is_sent(sent))

    def test_advanced_search_keeps_rarity_and_partial_name_matching(self):
        cards_index = {
            "Évoli": [
                ({"id": "sv8a-224", "name": "Évoli", "localId": "224", "rarity": "Illustration Rare", "category": "Pokemon"}, "Évolutions Prismatiques", "sv8a"),
                ({"id": "base-51", "name": "Évoli", "localId": "51", "rarity": "Commune", "category": "Pokemon"}, "Jungle", "base"),
            ]
        }
        fake_st = SimpleNamespace(session_state={"cards_index": cards_index})
        with patch.object(estimations, "st", fake_st):
            estimations._reset_estimation_search_memory_cache()
            results = estimations._card_suggestions(
                "evoli ar",
                "",
                lambda *_args, **_kwargs: [],
                lambda card, *_args, **_kwargs: card,
                normalize_name,
                language="fr",
            )
            session_index = fake_st.session_state["estimation_search_index_cache"]["index"]
            estimations._ESTIMATION_SEARCH_INDEX = []
            estimations._ESTIMATION_SEARCH_INDEX_BY_LANG = {"fr": [], "ja": []}
            estimations._ESTIMATION_SEARCH_INDEX_SOURCE_ID = None
            restored = estimations._build_search_index(cards_index, normalize_name)
        self.assertTrue(results)
        self.assertEqual(results[0]["card"]["id"], "sv8a-224")
        self.assertIs(restored, session_index)

    def test_custom_image_can_override_official_and_be_reverted(self):
        card = {"id": "sv8a-224", "name": "Évoli", "number": "224", "image_url": "https://assets.tcgdex.net/fr/test/224/high.webp"}
        with tempfile.TemporaryDirectory() as folder:
            registry = str(Path(folder) / "custom.json")
            custom = "https://images.example.test/evoli-custom.webp"
            self.assertTrue(register_custom_card_image(card, custom, path=registry, override_official=True))
            self.assertEqual(resolve_custom_card_image(card, path=registry), custom)
            self.assertTrue(remove_custom_card_image(card, path=registry))
            self.assertEqual(resolve_custom_card_image(card, path=registry), "")

    def test_legacy_fallback_does_not_override_an_official_image(self):
        card = {"id": "sv8a-224", "name": "Évoli", "number": "224", "image_url": "https://assets.tcgdex.net/fr/test/224/high.webp"}
        with tempfile.TemporaryDirectory() as folder:
            registry = str(Path(folder) / "custom.json")
            register_custom_card_image(card, "https://images.example.test/legacy.webp", path=registry, override_official=False)
            self.assertEqual(resolve_custom_card_image(card, path=registry), "")

    def test_shared_renderers_prioritize_the_central_custom_image(self):
        card = {"id": "sv8a-224", "number": "224", "image_url": "https://official.example.test/evoli.webp"}
        custom = "https://custom.example.test/evoli.webp"
        with patch("ui.pages.estimations.resolve_custom_card_image", return_value=custom), patch(
            "ui.pages.collection.resolve_custom_card_image", return_value=custom
        ), patch("ui.pages.sales.resolve_custom_card_image", return_value=custom), patch(
            "ui.pages.vinted_listings.resolve_custom_card_image", return_value=custom
        ):
            self.assertEqual(estimations._resolve_estimation_card_image(card)["url"], custom)
            self.assertEqual(_collection_card_image_url(card), custom)
            self.assertEqual(_sale_image_candidates(card)[0], custom)
            self.assertEqual(_card_image(card), custom)

    def test_card_value_edits_are_deferred_to_an_explicit_form_submit(self):
        source = inspect.getsource(estimations._render_open_estimation)
        self.assertIn('with st.form(f"est_card_values_', source)
        self.assertIn('st.form_submit_button("Enregistrer"', source)
        self.assertNotIn("previous_qty_seen", source)
        self.assertNotIn("previous_cote_seen", source)

    def test_comparison_ui_was_removed_without_touching_transfer(self):
        module_source = inspect.getsource(estimations)
        self.assertNotIn("_render_estimations_comparison", module_source)
        self.assertNotIn("est_compare_", module_source)
        self.assertIn("Créer un vrai lot", module_source)
        self.assertIn("from_estimation_uid", module_source)


if __name__ == "__main__":
    unittest.main()

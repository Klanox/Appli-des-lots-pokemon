from __future__ import annotations

import unittest

from services.vinted_listing_service import prepare_listing


class VintedListingServiceTests(unittest.TestCase):
    def test_single_japanese_card_uses_jap_in_title_and_description(self):
        prepared = prepare_listing(
            [{"name": "Rototaupe", "number": "124", "set": "Foudre Noire", "japanese": True}],
            "Carte seule",
        )

        self.assertEqual(prepared["title"], "Carte Pokémon - Rototaupe Japonaise 124 - Foudre Noire - JAP")
        self.assertIn("- Foudre Noire - JAP", prepared["description"])

    def test_multi_listing_generates_one_title_and_one_description(self):
        prepared = prepare_listing(
            [
                {"name": "Morpeko V-UNION", "number": "SWSH287", "set": "Promo SWSH"},
                {"name": "Morpeko V-UNION", "number": "SWSH288", "set": "Promo SWSH"},
                {"name": "Morpeko V-UNION", "number": "SWSH289", "set": "Promo SWSH"},
                {"name": "Morpeko V-UNION", "number": "SWSH290", "set": "Promo SWSH"},
            ],
            "Plusieurs cartes",
        )

        self.assertTrue(prepared["title"].startswith("Lot cartes Pokémon - "))
        self.assertEqual(prepared["title"].count("Morpeko V-UNION"), 3)
        self.assertEqual(prepared["description"].count("Morpeko V-UNION"), 4)
        self.assertIn("- FR", prepared["description"].splitlines()[0])


if __name__ == "__main__":
    unittest.main()

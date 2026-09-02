from __future__ import annotations

import unittest

from services.vinted_listing_service import VINTED_TAGS, prepare_listing


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

    def test_all_listing_kinds_use_the_exact_central_tags_once(self):
        cases = [
            ([{"name": "Yanmega", "number": "98", "set": "Triomphant"}], "Carte seule"),
            ([{"name": "Pikachu", "number": "25", "set": "Promo", "japanese": True}], "Carte seule"),
            ([
                {"name": "Rayquaza & Deoxys LÉGENDE", "number": "89/90", "set": "Indomptable"},
                {"name": "Rayquaza & Deoxys LÉGENDE", "number": "90/90", "set": "Indomptable"},
            ], "Plusieurs cartes"),
            ([
                {"name": "Morpeko V-UNION", "number": number, "set": "Promo SWSH"}
                for number in ("SWSH215", "SWSH216", "SWSH217", "SWSH218")
            ], "Plusieurs cartes"),
            ([
                {"name": "Marisson", "number": "058", "set": "MEP"},
                {"name": "Feunnec", "number": "059", "set": "MEP"},
                {"name": "Grenousse", "number": "060", "set": "MEP"},
            ], "Plusieurs cartes"),
        ]

        for cards, listing_type in cases:
            with self.subTest(cards=cards):
                prepared = prepare_listing(cards, listing_type)
                self.assertEqual(prepared["description"].count(f"Tags : {VINTED_TAGS}"), 1)
                self.assertNotIn("Lumineux", prepared["description"])
                self.assertNotIn("tin box", prepared["description"])


if __name__ == "__main__":
    unittest.main()

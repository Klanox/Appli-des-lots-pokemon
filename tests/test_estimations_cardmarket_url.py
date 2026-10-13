"""Lien Cardmarket des cartes suivies : pas de tiret dans le terme de recherche (données temporaires, aucun réseau)."""
import unittest
from urllib.parse import parse_qs, urlparse

from ui.pages import estimations
from utils import cardmarket_search_url


def _search_string(url):
    return parse_qs(urlparse(url).query)["searchString"][0]


class CardmarketUrlTest(unittest.TestCase):
    def test_hyphen_replaced_by_space_in_search_term_only(self):
        card = {"uid": "c1", "name": "Koraidon-ex", "number": "231", "lang": "fr"}
        url = estimations._estimation_cardmarket_url(card, cardmarket_search_url)
        term = _search_string(url)
        self.assertEqual(term, "Koraidon ex 231")
        self.assertNotIn("-", term)
        self.assertEqual(card["name"], "Koraidon-ex")          # nom affiché / données intacts

    def test_japanese_card_search_is_name_and_number_only(self):
        card = {"uid": "j1", "name": "Paume de Fer ex", "number": "154/131", "set_id": "sv08.5", "set": "Étincelles Déferlantes",
                "lang": "ja", "special": "Japonaise"}
        term = _search_string(estimations._estimation_cardmarket_url(card, cardmarket_search_url))
        self.assertEqual(term, "Paume de Fer ex 154")
        card_hyphen = {**card, "name": "Koraidon-ex", "number": "231"}
        self.assertEqual(_search_string(estimations._estimation_cardmarket_url(card_hyphen, cardmarket_search_url)), "Koraidon ex 231")

    def test_french_card_query_unchanged(self):
        card = {"uid": "f1", "name": "Paume de Fer ex", "number": "154/131", "set_id": "sv08.5", "lang": "fr"}
        self.assertEqual(_search_string(estimations._estimation_cardmarket_url(card, cardmarket_search_url)), "Paume de Fer ex 154/131")

    def test_promo_prefix_removed_in_search_term_only(self):
        def term(number, lang="fr", name="Pikachu VMAX"):
            card = {"uid": "p", "name": name, "number": number, "set_id": "swsh", "lang": lang}
            if lang == "ja":
                card["special"] = "Japonaise"
            return _search_string(estimations._estimation_cardmarket_url(card, cardmarket_search_url))
        self.assertEqual(term("SWSH286"), "Pikachu VMAX 286")
        self.assertEqual(term("XY117", name="Dracaufeu"), "Dracaufeu 117")
        for number, expected in (("SVP208", "208"), ("SM199", "199"), ("BW45", "45"), ("swsh286", "286")):
            self.assertEqual(estimations._cardmarket_search_number(number), expected)
        for kept in ("GG30", "TG12", "RC5", "SV107", "154/131", "154", "", "S-P", "SWSH286/SWSH-P"):
            self.assertEqual(estimations._cardmarket_search_number(kept), kept)
        self.assertEqual(term("154/131"), "Pikachu VMAX 154/131")          # FR : inchangé
        self.assertEqual(term("GG30"), "Pikachu VMAX GG30")
        self.assertEqual(term("SWSH286", lang="ja"), "Pikachu VMAX 286")
        self.assertEqual(term("154/131", lang="ja"), "Pikachu VMAX 154")
        card = {"uid": "p", "name": "Pikachu VMAX", "number": "SWSH286", "lang": "fr"}
        estimations._estimation_cardmarket_url(card, cardmarket_search_url)
        self.assertEqual(card["number"], "SWSH286")                         # donnée affichée / enregistrée intacte

    def test_ho_oh_and_name_without_hyphen(self):
        self.assertEqual(estimations._cardmarket_search_term("Ho-Oh"), "Ho Oh")
        self.assertEqual(estimations._cardmarket_search_term("Pikachu"), "Pikachu")

    def test_suggestion_thumbnail_is_larger(self):
        self.assertIn(".est-sugg-thumb { width:68px; flex:0 0 68px;", open(estimations.__file__, encoding="utf-8-sig").read())


if __name__ == "__main__":
    unittest.main()

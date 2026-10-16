"""Etape 3 · Verification : prix des cartes (affichage uniquement, aucune ecriture).

Fixtures en memoire : aucun fichier metier, aucun envoi au Cloud.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from ui.pages import vinted_listings as VL


def _card(uid, name, number, price, **extra):
    card = {"card_uid": uid, "name": name, "number": number, "set": "Poing de Fusion", "suggested_price": price,
            "quantity": 1, "available_qty": 1, "lot_name": "Lot A"}
    card.update(extra)
    return card


class PriceHelpersTests(unittest.TestCase):
    def test_price_text_uses_the_french_format(self):
        self.assertEqual(VL._price_text(10), "10,00 €")
        self.assertEqual(VL._price_text(1234.5), "1234,50 €")

    def test_state_ok_missing_and_no_stock(self):
        stock = VL._stock_by_uid([_card("a", "Fulgudog V", "249", 10), _card("b", "Fulgudog V", "249", 0)])
        self.assertEqual(VL._candidate_stock_price({"card_uid": "a"}, stock), (10.0, "ok"))
        self.assertEqual(VL._candidate_stock_price({"card_uid": "b"}, stock), (0.0, "missing"))
        self.assertEqual(VL._candidate_stock_price({"card_uid": "zzz"}, stock, in_drop=False), (0.0, "no_stock"))
        # dans le Drop mais absent du stock : repli sur le prix du candidat, comme _recognition_listing_cards
        self.assertEqual(VL._candidate_stock_price({"card_uid": "zzz", "price": 7}, stock), (7.0, "ok"))
        self.assertEqual(VL._candidate_stock_price({"card_uid": "zzz", "price": 0}, stock), (0.0, "missing"))

    def test_price_is_the_one_used_for_the_listing(self):
        card = _card("a", "Fulgudog V", "249", 10)
        price, _state = VL._candidate_stock_price({"card_uid": "a"}, VL._stock_by_uid([card]))
        self.assertEqual(price, VL.suggested_price(card))
        self.assertEqual(VL.listing_price_text([card], None), "10.00€")

    def test_chip_html(self):
        self.assertIn("10,00 €", VL._price_chip_html(10, "ok"))
        self.assertNotIn("missing", VL._price_chip_html(10, "ok"))
        self.assertIn("missing", VL._price_chip_html(0, "missing"))
        self.assertIn("Prix manquant", VL._price_chip_html(0, "missing"))
        self.assertIn("Pas en stock", VL._price_chip_html(0, "no_stock"))
        self.assertEqual(VL._price_option_text(0, "no_stock"), "Pas en stock")


def _identity_script(uid, stock_json):
    import json as _json
    import ui.pages.vinted_listings as _VL

    stock = _VL._stock_by_uid(_json.loads(stock_json))
    candidate = {"card_uid": uid, "name": "Fulgudog V", "number": "249/264", "set": "Poing de Fusion"} if uid else None
    _VL._render_candidate_identity(candidate, {"score": 90, "margin": 20}, None, stock)


class IdentityTests(unittest.TestCase):
    def run_script(self, uid, cards):
        import json

        at = AppTest.from_function(_identity_script, args=(uid, json.dumps(cards)))
        at.default_timeout = 30
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return " ".join(m.value for m in at.markdown)

    def test_proposed_card_shows_the_price_chip(self):
        text = self.run_script("a", [_card("a", "Fulgudog V", "249", 10)])
        self.assertIn("10,00 €", text)
        self.assertIn("ps-price-chip", text)

    def test_missing_price_shows_the_alert(self):
        text = self.run_script("a", [_card("a", "Fulgudog V", "249", 0)])
        self.assertIn("Prix manquant", text)
        self.assertIn("missing", text)

    def test_no_candidate_shows_no_price(self):
        self.assertNotIn("ps-price-chip", self.run_script("", []))


def _total_script(stock_json):
    import json as _json
    import ui.pages.vinted_listings as _VL

    stock = _VL._stock_by_uid(_json.loads(stock_json))
    cands = [{"card_uid": "a", "name": "A"}, {"card_uid": "b", "name": "B"}]
    group = {"matches": [{"subcard_id": "s0"}, {"subcard_id": "s1"}]}
    with __import__("unittest.mock").mock.patch.object(_VL, "photo_effective_candidate", side_effect=lambda s, g, m, i: (cands[i], "auto")):
        _VL._render_group_price_total({}, group, stock)


class TotalTests(unittest.TestCase):
    def run_script(self, cards):
        import json

        at = AppTest.from_function(_total_script, args=(json.dumps(cards),))
        at.default_timeout = 30
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return " ".join(m.value for m in at.markdown)

    def test_total_is_the_sum_of_the_card_prices(self):
        text = self.run_script([_card("a", "A", "1", 10), _card("b", "B", "2", 2.5)])
        self.assertIn("Total annonce : 12,50 €", text)
        self.assertNotIn("manquant", text)

    def test_total_flags_missing_prices(self):
        text = self.run_script([_card("a", "A", "1", 10), _card("b", "B", "2", 0)])
        self.assertIn("Total annonce : 10,00 €", text)
        self.assertIn("1 prix manquant(s)", text)


def _correction_script(stock_json):
    import json as _json
    import unittest.mock as _mock
    import ui.pages.vinted_listings as _VL

    stock = _json.loads(stock_json)
    # trois exemplaires de la meme carte dans le Drop (uid, cle et prix distincts) + une carte du stock hors Drop
    historical = [
        dict(card, drop_status="to_photograph", historical_drop_member=True, price=card["suggested_price"], drop_card_key="k-" + card["card_uid"])
        for card in stock[:3]
    ]
    group = {"photos": [], "matches": [{"subcard_id": "s0"}], "ground_truth_group_id": "g1"}
    with _mock.patch.object(_VL, "active_drop_candidates", return_value=({}, historical)):
        _VL._render_candidate_correction({}, {}, {}, group, {"subcard_id": "s0"}, 0, {"id": "d"}, stock)


class CorrectionListTests(unittest.TestCase):
    def test_price_comes_before_the_technical_id_and_copies_are_listed_separately(self):
        import json

        cards = [
            _card("card_a51e405f251d", "Fulgudog V", "249/264", 10, drop_card_key="k-a"),
            _card("card_b77700000000", "Fulgudog V", "249/264", 6),
            _card("card_c00000000000", "Fulgudog V", "249/264", 0),
            _card("card_d00000000000", "Fulgudog VMAX", "250/264", 4.5),
        ]
        at = AppTest.from_function(_correction_script, args=(json.dumps(cards),))
        at.default_timeout = 30
        at.run()
        at.text_input[0].set_value("Fulgudog").run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        options = list(at.selectbox[0].options)
        joined = "\n".join(options)
        self.assertEqual(len(options), 4, options)
        for option in options:
            self.assertLess(option.index("€") if "€" in option else option.index("Prix manquant"), option.index("card_"), option)
        self.assertIn("10,00 €", joined)
        self.assertIn("6,00 €", joined)
        self.assertIn("Prix manquant", joined)
        self.assertTrue(any("Dans le Drop" in o and "10,00 €" in o for o in options), options)
        self.assertTrue(any("Dans le Drop" in o and "6,00 €" in o and "card_b777" in o for o in options), options)
        self.assertTrue(any("hors Drop" in o and "4,50 €" in o for o in options), options)


class NoWriteTests(unittest.TestCase):
    def test_the_new_code_never_writes_business_data(self):
        import inspect

        for name in ("_price_text", "_stock_by_uid", "_candidate_stock_price", "_price_chip_html", "_price_option_text", "_render_group_price_total"):
            source = inspect.getsource(getattr(VL, name))
            for forbidden in ("save_vinted_drops", "safe_write_json", "open(", "set_match_validation", ".write"):
                self.assertNotIn(forbidden, source, f"{name} contient {forbidden}")


if __name__ == "__main__":
    unittest.main()

from copy import deepcopy
from datetime import datetime
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from core import sales_actions
from core.sale_preview import historical_unit_cost_or_none, preview_sale
from core.trade_economics import trade_sale_stat_rows
from logic import calc_cout_lot, effective_purchase_price, card_available_qty, resolve_card_ref
from ui.lot_progress import lot_progress, lot_progress_html
from ui.pages.history import _off_stock_cost_for_history
from ui.pages.sales import _allocate_final_sale_price


def fixture():
    return {"lots": [{"lot_uid": "lot-test", "nom": "Test", "prix_achat": 12,
                      "cards": [{"card_uid": "card-test", "name": "Test", "set": "Set", "number": "1",
                                 "quantity": 4, "sold_quantity": 0, "suggested_price": 10, "sold_entries": []}],
                      "ventes": []}], "ventes_hors_stock": []}


def physical(quantity=1):
    return {"lot_idx": 0, "card_idx": 0, "quantity": quantity, "price_base": 10, "unit_price": 10}


def off_stock(**kwargs):
    return {"line_type": "off_stock", "category": "Autre", "quantity": 1, "price_base": 5,
            "unit_price": 5, "cost_basis_known": True, "cost_basis": 2, **kwargs}


class PreviewTests(unittest.TestCase):
    def preview(self, data, items):
        before = deepcopy(data)
        result = preview_sale(data, items, resolve_card=resolve_card_ref, calc_cost=calc_cout_lot,
                              effective_purchase_price=effective_purchase_price)
        self.assertEqual(data, before)
        return result

    def assert_final_matches(self, data, items):
        estimate = self.preview(data, items)
        final = deepcopy(data)
        saved = []
        with patch.multiple(sales_actions, ld=lambda: final, sd=lambda value: saved.append(deepcopy(value)),
                            resolve_card_ref=resolve_card_ref, card_available_qty=card_available_qty,
                            new_uid=lambda prefix: prefix + "-test", datetime=datetime, create=True), patch.object(
            sales_actions, "link_sale_to_vinted_drop_if_applicable", return_value=False
        ), patch("services.vinted_drops_service.link_sale_to_vinted_drop_if_applicable", return_value=False), patch.object(
            sales_actions, "_record_off_stock_brocante_order"
        ):
            ok, message = sales_actions.scu_many(deepcopy(items), "Main propre")
        self.assertTrue(ok, message)
        self.assertEqual(len(saved), 1)
        profit = 0
        for lot in final["lots"]:
            rows, basis = calc_cout_lot(lot)
            for card, sale, cost in rows:
                if not sale.get("sale_transaction_id"):
                    continue
                if card.get("received_by_exchange") and (card.get("trade_contributors") or card.get("exchange_repartition")):
                    profit += sum(row["benef"] for row in trade_sale_stat_rows(card, sale))
                else:
                    profit += sale["price"] - cost
            for sale in lot["ventes"]:
                if sale.get("is_off_stock"):
                    profit += sale["price"] - _off_stock_cost_for_history(sale, lot, basis, effective_purchase_price)
        for sale in final["ventes_hors_stock"]:
            profit += sale["price"] - _off_stock_cost_for_history(sale)
        self.assertAlmostEqual(estimate["profit"], profit, places=9)
        return estimate

    def test_single(self):
        self.assertEqual(self.assert_final_matches(fixture(), [physical()])["profit"], 7)

    def test_quantities_and_multiple_cards(self):
        data = fixture()
        other = deepcopy(data["lots"][0]["cards"][0])
        other.update(card_uid="other", suggested_price=20)
        data["lots"][0]["cards"].append(other)
        self.assert_final_matches(data, [physical(2), {**physical(), "card_idx": 1, "unit_price": 20}])

    def test_negotiation_changes_profit(self):
        cart = [physical(3), off_stock()]
        base = self.assert_final_matches(fixture(), cart)
        discounted = self.assert_final_matches(fixture(), _allocate_final_sale_price(cart, 20.31))
        self.assertAlmostEqual(base["profit"] - discounted["profit"], 14.69)

    def test_mixed(self):
        self.assertEqual(self.assert_final_matches(fixture(), [physical(), off_stock()])["profit"], 10)

    def test_lot_linked_off_stock_changes_common_basis(self):
        self.assert_final_matches(fixture(), [physical(2), off_stock(source_lot_id="lot-test", cost_basis_known=False)])

    def test_mixte(self):
        data = fixture()
        data["lots"][0].update(is_mixte=True, valeur_totale=100, prix_achat_reel=25)
        self.assert_final_matches(data, [physical(2), off_stock(source_lot_idx=0, cost_basis_known=False)])

    def test_divers(self):
        data = fixture()
        data["lots"][0]["is_divers"] = True
        data["lots"][0]["cards"][0]["purchase_price"] = 2.35
        self.assertAlmostEqual(self.assert_final_matches(data, [physical(2)])["profit"], 15.3)

    def test_trade(self):
        data = fixture()
        data["lots"][0]["cards"][0].update(received_by_exchange=True, trade_acquisition_unit_cost=2.35,
                                          exchange_repartition={"0": 9.4})
        self.assertAlmostEqual(self.assert_final_matches(data, [physical(2)])["profit"], 15.3)

    def test_off_stock_only(self):
        self.assertEqual(self.assert_final_matches(fixture(), [off_stock(), off_stock(quantity=3)])["profit"], 16)

    def test_unknown_is_partial(self):
        result = self.preview(fixture(), [physical(), off_stock(cost_basis_known=False)])
        self.assertIsNone(result["profit"])
        self.assertEqual(result["known_profit"], 7)
        self.assertEqual(result["unknown_lines"], 1)

    def test_unknown_physical_cost(self):
        data = fixture()
        del data["lots"][0]["prix_achat"]
        self.assertIsNone(self.preview(data, [physical()])["profit"])

    def test_linked_off_stock_without_purchase_cost_is_partial(self):
        data = fixture()
        del data["lots"][0]["prix_achat"]
        self.assertIsNone(self.preview(data, [off_stock(source_lot_idx=0, cost_basis_known=False)])["profit"])

    def test_documented_zero_cost(self):
        self.assertEqual(self.assert_final_matches(fixture(), [off_stock(cost_basis=0)])["profit"], 5)

    def test_quantity_deletion_and_price_changes(self):
        data = fixture()
        self.assertEqual(self.preview(data, [physical(2)])["profit"], 14)
        self.assertEqual(self.preview(data, [physical()])["profit"], 7)
        self.assertEqual(self.preview(data, [{**physical(), "unit_price": 2}])["profit"], -1)
        self.assertEqual(self.preview(data, [])["profit"], 0)

    def test_search_cost(self):
        lot = fixture()["lots"][0]
        card = lot["cards"][0]
        self.assertEqual(historical_unit_cost_or_none(lot, card), 3)
        card.update(received_by_exchange=True, trade_acquisition_unit_cost=2.35)
        self.assertEqual(historical_unit_cost_or_none(lot, card), 2.35)
        card["trade_acquisition_unit_cost"] = 0
        self.assertEqual(historical_unit_cost_or_none(lot, card), 0)
        del card["trade_acquisition_unit_cost"]
        self.assertIsNone(historical_unit_cost_or_none(lot, card))
        self.assertIsNone(historical_unit_cost_or_none({}, {"suggested_price": 8}))


class LotProgressTests(unittest.TestCase):
    def test_repayment(self):
        lot = fixture()["lots"][0]
        lot["ventes"] = [{"price": 6}]
        state = lot_progress(lot)
        self.assertEqual((state["phase"], state["progress"]), ("repayment", 50))

    def test_reimbursed_not_complete(self):
        lot = fixture()["lots"][0]
        lot["ventes"] = [{"price": 30}]
        lot["cards"][0]["sold_quantity"] = 3
        state = lot_progress(lot)
        self.assertEqual((state["phase"], state["progress"], state["sold"]), ("sales", 75, 3))

    def test_complete(self):
        lot = fixture()["lots"][0]
        lot["ventes"] = [{"price": 30}]
        lot["cards"][0]["sold_quantity"] = 4
        self.assertEqual(lot_progress(lot)["phase"], "complete")
        markup = lot_progress_html(lot, [], 0, str)
        self.assertIn("Lot terminé", markup)
        self.assertIn('aria-valuenow="100.0"', markup)
        self.assertNotIn("gradient", markup)

    def test_transfers_and_exchanges_are_not_sales(self):
        lot = fixture()["lots"][0]
        lot["ventes"] = [{"price": 30}]
        lot["cards"][0].update(stored_quantity=2, exchange_out_quantity=1)
        storage = {"is_storage": True, "cards": [{"stored_from_lot_uid": "lot-test", "quantity": 2, "sold_quantity": 1}]}
        state = lot_progress(lot, [lot, storage])
        self.assertEqual((state["sold"], state["total"], state["progress"]), (1, 4, 25))

    def test_system_lot_and_collection_not_falsely_reimbursed(self):
        lot = {"is_trade": True, "cards": [{"quantity": 3, "is_collection_keep": True}]}
        state = lot_progress(lot)
        self.assertFalse(state["reimbursed"])
        self.assertEqual(state["progress"], 0)


class CartRenderTests(unittest.TestCase):
    def test_actual_cart_markup_updates_estimate_when_final_price_changes(self):
        from streamlit.testing.v1 import AppTest

        source = (Path(__file__).resolve().parents[1] / "ui/pages/sales.py").read_text(encoding="utf-8")
        cart = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.If)
                    and ast.unparse(node.test) == "not st.session_state.bulk_cart")
        script = '''
import html
import streamlit as st
from core.sale_preview import preview_sale
from logic import calc_cout_lot, effective_purchase_price, resolve_card_ref, card_available_qty
from ui.pages.sales import _allocate_final_sale_price
def noop(*args): pass
bulk_cart_set_quantity = bulk_cart_increment = bulk_cart_pop = bulk_sale_prepare = bulk_cart_clear = save_activity_state = noop
def fp(value): return f"{value:.2f} EUR"
'''
        item = {**physical(), "card_name": "Test", "card_set": "Set", "lot_name": "Test"}
        script += f"\ncd = {fixture()!r}\nst.session_state.setdefault('bulk_cart', [{item!r}])\n"
        script += ast.unparse(cart)
        app = AppTest.from_string(script).run()
        self.assertFalse(app.exception)
        self.assertIn("Bénéfice estimé : 7.00 EUR", " ".join(node.value for node in app.markdown))
        app.number_input(key="negociated_price").set_value(8.5).run()
        self.assertFalse(app.exception)
        self.assertIn("Bénéfice estimé : 5.50 EUR", " ".join(node.value for node in app.markdown))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from core import sales_actions
from core.sales_cancellation import cancel_sale_by_id
from ui.pages.history import _group_history_transactions
from ui.pages.statistics import _aggregate_sales


class _SessionState(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def _available(card):
    return max(
        int(card.get("quantity", 0))
        - int(card.get("sold_quantity", 0))
        - int(card.get("exchange_out_quantity", 0))
        - int(card.get("stored_quantity", 0)),
        0,
    )


def _resolve(data, item):
    for lot_index, lot in enumerate(data.get("lots", [])):
        if item.get("lot_uid") and item.get("lot_uid") != lot.get("lot_uid"):
            continue
        for card_index, card in enumerate(lot.get("cards", [])):
            if item.get("card_uid") == card.get("card_uid"):
                return lot_index, card_index, lot, card
    return None, None, None, None


class MixedSaleTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "lots": [{
                "lot_uid": "lot-1",
                "nom": "Lot test",
                "cards": [{
                    "card_uid": "card-1",
                    "name": "Yanmega",
                    "set": "Triomphant",
                    "number": "98/102",
                    "quantity": 3,
                    "sold_quantity": 0,
                    "suggested_price": 10.0,
                    "sold_entries": [],
                }],
                "ventes": [],
            }],
            "ventes_hors_stock": [],
        }
        self.saved = []
        sales_actions.configure_sales_actions({
            "ld": lambda: self.data,
            "sd": lambda value: self.saved.append(deepcopy(value)),
            "card_available_qty": _available,
            "resolve_card_ref": _resolve,
            "new_uid": lambda prefix: f"{prefix}-new",
            "datetime": datetime,
        })

    def test_carting_off_stock_does_not_persist_sale(self):
        state = _SessionState()
        saves = []
        with patch.object(sales_actions, "st", SimpleNamespace(session_state=state), create=True), patch.object(
            sales_actions, "save_activity_state", lambda: saves.append(True), create=True
        ):
            sales_actions.bulk_cart_add_off_stock({
                "category": "Lot mixte",
                "description": "Co/unco/reverses",
                "quantity": 12,
                "amount": 5.4,
            })

        self.assertEqual(len(state["bulk_cart"]), 1)
        self.assertEqual(state["bulk_cart"][0]["line_type"], "off_stock")
        self.assertAlmostEqual(state["bulk_cart"][0]["price_base"], 0.45)
        self.assertEqual(self.data["ventes_hors_stock"], [])
        self.assertEqual(self.saved, [])
        self.assertEqual(len(saves), 1)

    def test_mixed_cart_persists_one_shared_transaction(self):
        items = [
            {"lot_uid": "lot-1", "card_uid": "card-1", "quantity": 1, "unit_price": 10.0},
            {
                "line_type": "off_stock",
                "category": "Lot mixte",
                "description": "Co/unco/reverses",
                "quantity": 12,
                "unit_price": 0.45,
                "cost_basis_known": True,
                "cost_basis": 1.5,
            },
        ]
        with patch.object(sales_actions, "link_sale_to_vinted_drop_if_applicable", lambda *_: False), patch(
            "services.vinted_drops_service.link_sale_to_vinted_drop_if_applicable", lambda *_: False
        ):
            ok, _message = sales_actions.scu_many(items, "ChoppeTaCarte")

        self.assertTrue(ok)
        self.assertEqual(len(self.saved), 1)
        card_sale = self.data["lots"][0]["cards"][0]["sold_entries"][0]
        off_stock_sale = self.data["ventes_hors_stock"][0]
        self.assertEqual(card_sale["sale_transaction_id"], off_stock_sale["sale_transaction_id"])
        self.assertEqual(card_sale["price"], 10.0)
        self.assertAlmostEqual(off_stock_sale["price"], 5.4)
        self.assertEqual(off_stock_sale["cost_basis"], 1.5)
        self.assertEqual(self.data["lots"][0]["cards"][0]["sold_quantity"], 1)

    def test_off_stock_only_cart_uses_one_transaction(self):
        items = [
            {"line_type": "off_stock", "category": "Lot mixte", "description": "Classeur", "quantity": 1, "unit_price": 7.0},
            {"line_type": "off_stock", "category": "Lot mixte", "description": "Tin", "quantity": 1, "unit_price": 2.0},
        ]
        with patch("services.vinted_drops_service.link_sale_to_vinted_drop_if_applicable", lambda *_: False):
            ok, _message = sales_actions.scu_many(items, "Main propre")

        self.assertTrue(ok)
        sales = self.data["ventes_hors_stock"]
        self.assertEqual(sum(sale["price"] for sale in sales), 9.0)
        self.assertEqual(len({sale["sale_transaction_id"] for sale in sales}), 1)

    def test_three_cards_and_two_off_stock_lines_still_make_one_transaction(self):
        items = [
            {"lot_uid": "lot-1", "card_uid": "card-1", "quantity": 3, "unit_price": 4.0},
            {"line_type": "off_stock", "category": "Lot mixte", "description": "Classeur", "quantity": 1, "unit_price": 7.0},
            {"line_type": "off_stock", "category": "Lot mixte", "description": "Tin", "quantity": 1, "unit_price": 2.0},
        ]
        with patch.object(sales_actions, "link_sale_to_vinted_drop_if_applicable", lambda *_: False), patch(
            "services.vinted_drops_service.link_sale_to_vinted_drop_if_applicable", lambda *_: False
        ):
            ok, _message = sales_actions.scu_many(items, "Main propre")

        self.assertTrue(ok)
        sales = [
            self.data["lots"][0]["cards"][0]["sold_entries"][0],
            *self.data["ventes_hors_stock"],
        ]
        self.assertEqual(len({sale["sale_transaction_id"] for sale in sales}), 1)
        self.assertEqual(sum(sale["price"] for sale in sales), 21.0)
        self.assertEqual(self.data["lots"][0]["cards"][0]["sold_quantity"], 3)

    def test_stock_failure_does_not_persist_earlier_off_stock_rows(self):
        items = [
            {"line_type": "off_stock", "category": "Lot mixte", "description": "Tin", "quantity": 1, "unit_price": 2.0},
            {"lot_uid": "lot-1", "card_uid": "card-1", "quantity": 4, "unit_price": 10.0},
        ]

        ok, _message = sales_actions.scu_many(items, "Main propre")

        self.assertFalse(ok)
        self.assertEqual(self.saved, [])
        self.assertEqual(self.data["ventes_hors_stock"], [])
        self.assertEqual(self.data["lots"][0]["cards"][0]["sold_quantity"], 0)

    def test_cancelling_mixed_sale_removes_every_line_and_restores_stock(self):
        items = [
            {"lot_uid": "lot-1", "card_uid": "card-1", "quantity": 1, "unit_price": 10.0},
            {"line_type": "off_stock", "category": "Lot mixte", "description": "Tin", "quantity": 1, "unit_price": 2.0},
        ]
        with patch.object(sales_actions, "link_sale_to_vinted_drop_if_applicable", lambda *_: False), patch(
            "services.vinted_drops_service.link_sale_to_vinted_drop_if_applicable", lambda *_: False
        ):
            sales_actions.scu_many(items, "Main propre")
        sale_id = self.data["lots"][0]["cards"][0]["sold_entries"][0]["sale_id"]

        with patch("core.sales_cancellation._restore_drop_items_for_sales", return_value=False), patch(
            "core.sales_cancellation._remove_brocante_transactions", return_value=0
        ):
            ok, _message, details = cancel_sale_by_id(self.data, sale_id)

        self.assertTrue(ok)
        self.assertEqual(details["card_sales_removed"], 1)
        self.assertEqual(details["off_stock_sales_removed"], 1)
        self.assertEqual(self.data["lots"][0]["cards"][0]["sold_quantity"], 0)
        self.assertEqual(self.data["lots"][0]["cards"][0]["sold_entries"], [])
        self.assertEqual(self.data["ventes_hors_stock"], [])

    def test_cancelling_from_off_stock_line_also_cancels_physical_lines(self):
        items = [
            {"lot_uid": "lot-1", "card_uid": "card-1", "quantity": 1, "unit_price": 10.0},
            {"line_type": "off_stock", "category": "Lot mixte", "description": "Tin", "quantity": 1, "unit_price": 2.0},
        ]
        with patch.object(sales_actions, "link_sale_to_vinted_drop_if_applicable", lambda *_: False), patch(
            "services.vinted_drops_service.link_sale_to_vinted_drop_if_applicable", lambda *_: False
        ):
            sales_actions.scu_many(items, "Main propre")
        sale_id = self.data["ventes_hors_stock"][0]["sale_id"]

        with patch("core.sales_cancellation._restore_drop_items_for_sales", return_value=False), patch(
            "core.sales_cancellation._remove_brocante_transactions", return_value=0
        ):
            ok, _message, details = cancel_sale_by_id(self.data, sale_id)

        self.assertTrue(ok)
        self.assertEqual(details["sales_removed"], 2)
        self.assertEqual(self.data["lots"][0]["cards"][0]["sold_quantity"], 0)
        self.assertEqual(self.data["ventes_hors_stock"], [])

    def test_history_collapses_mixed_lines_into_one_order(self):
        rows = [
            {"sale_id": "card-sale", "sale_transaction_id": "tx-1", "type": "card", "card_name": "Yanmega", "quantity": 1, "price": 10.0, "cout": 3.0, "benef": 7.0, "date": "2026-09-03", "canal": "Vinted"},
            {"sale_id": "off-sale", "sale_transaction_id": "tx-1", "type": "off_stock", "card_name": "Tin", "quantity": 1, "price": 2.0, "cout": 1.0, "benef": 1.0, "date": "2026-09-03", "canal": "Vinted"},
        ]

        grouped = _group_history_transactions(rows)

        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["type"], "transaction")
        self.assertEqual(grouped[0]["price"], 12.0)
        self.assertEqual(len(grouped[0]["transaction_items"]), 2)

    def test_legacy_off_stock_history_without_transaction_id_stays_readable(self):
        row = {"sale_id": "legacy-off", "type": "off_stock", "card_name": "Classeur", "quantity": 1, "price": 7.0}

        grouped = _group_history_transactions([row])

        self.assertEqual(grouped, [row])

    def test_general_analytics_keep_order_total_but_card_metrics_physical(self):
        rows = [
            {"sale": {"sale_id": "card", "sale_transaction_id": "tx-1"}, "price": 10.0, "quantity": 1, "benef": 7.0, "is_off_stock": False},
            {"sale": {"sale_id": "off", "sale_transaction_id": "tx-1"}, "price": 5.0, "quantity": 12, "benef": 4.0, "is_off_stock": True},
        ]

        metrics = _aggregate_sales(rows)

        self.assertEqual(metrics["ca"], 15.0)
        self.assertEqual(metrics["transactions"], 1)
        self.assertEqual(metrics["basket"], 15.0)
        self.assertEqual(metrics["qty"], 1.0)
        self.assertEqual(metrics["avg_card"], 10.0)


if __name__ == "__main__":
    unittest.main()

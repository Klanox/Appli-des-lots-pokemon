"""Brocante tests on synthetic, in-memory documents only."""
import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch

from core.brocante import (add_expense, brocante_stats, close_session, make_session,
                           record_exchange, record_transaction, start_session)
from core.sale_preview import historical_unit_cost_or_none
from core.trade_economics import allocate_received_cards, search_received_cards
from services.brocante_workflow import (commit_staged, deletion_audit, event_sales,
                                        finalize_brocante_purchase_costs, project_event,
                                        stage_delete, stage_purchase, tag_trade)
from core import sales_actions
from core.sales_cancellation import cancel_sale_by_id
from ui.pages.brocante import add_purchase_cart_line, go, purchase_card_identity


def fixtures(cash=50):
    event = make_session("Auray", "2026-09-06", initial_cash=cash)
    event["id"] = "event-1"
    events = {"sessions": [event]}
    start_session(events, event["id"], force=True)
    stock = {"lots": [{"nom": "Stock", "lot_uid": "lot-1", "prix_achat": 20, "cost_basis_method": "per_card",
                       "cards": [{"card_uid": "card-1", "name": "Pikachu", "number": "25", "set": "Base",
                                  "quantity": 5, "sold_quantity": 0, "purchase_price": 4,
                                  "suggested_price": 10, "sold_entries": []}], "ventes": []}]}
    return stock, events


def lines(n=1):
    return [{"card": {"name": f"Carte {i}", "set": "Test", "number": str(i), "lang": "ja" if i == 0 else "fr",
                       "image_url": f"https://example.test/{i}.jpg", "card_uid": "do-not-copy", "sold_entries": [{"bad": True}]},
             "quantity": 1, "value": (i+1)*10} for i in range(n)]


class BrocanteTests(unittest.TestCase):
    def test_purchase_cart_adds_directly_and_increments_exact_card(self):
        cart = []
        card = {"id": "base1-25", "set_id": "base1", "name": "Pikachu", "number": "25", "lang": "fr"}
        add_purchase_cart_line(cart, card, 2)
        add_purchase_cart_line(cart, deepcopy(card), 3)
        self.assertEqual(len(cart), 1)
        self.assertEqual(cart[0]["quantity"], 5)
        self.assertEqual(purchase_card_identity(cart[0]["card"]), purchase_card_identity(card))

    def test_purchase_cart_keeps_distinct_catalogue_cards_separate(self):
        cart = []
        first = {"id": "base1-25", "set_id": "base1", "name": "Pikachu", "number": "25", "lang": "fr"}
        second = {**first, "id": "base2-25", "set_id": "base2"}
        add_purchase_cart_line(cart, first, 1)
        add_purchase_cart_line(cart, second, 1)
        self.assertEqual(len(cart), 2)

    def test_legacy_missing_initial_cash_stays_unknown(self):
        event = make_session("Ancienne brocante", "2026-01-01", initial_cash=None)
        record_transaction(event, {"id": "sale-1", "payment_method": "Espèces", "amount": 12})
        self.assertIsNone(brocante_stats(event)["theoretical_cash"])

    def test_view_switch_preserves_existing_cart_state(self):
        class FakeStreamlit:
            session_state = {"bulk_cart": [{"card_uid": "card-1", "quantity": 1}]}

        fake = FakeStreamlit()
        go(fake, "Rachat")
        self.assertEqual(fake.session_state["brocante_view"], "Rachat")
        self.assertEqual(fake.session_state["bulk_cart"], [{"card_uid": "card-1", "quantity": 1}])

    def test_fund_required_including_force_and_zero_valid(self):
        for amount, expected in [(None, False), (-1, False), (float("nan"), False), (0, True), (50, True)]:
            _, data = fixtures(amount)
            self.assertEqual(start_session(data, "event-1", force=True)[0], expected)

    def test_checklist_unchanged(self):
        _, data = fixtures()
        data["sessions"][0]["status"] = "preparing"
        self.assertFalse(start_session(data, "event-1")[0])
        for task in data["sessions"][0]["checklist"]:
            task["done"] = True
        self.assertTrue(start_session(data, "event-1")[0])

    def test_purchase_reuses_one_lot_and_is_idempotent(self):
        stock, data = fixtures()
        original = deepcopy((stock, data))
        after, events = stage_purchase(stock, data, "event-1", lines(), 30, "Espèces", "p1")
        self.assertEqual((stock, data), original)
        again, events2 = stage_purchase(after, events, "event-1", lines(), 30, "Espèces", "p1")
        self.assertEqual((again, events2), (after, events))
        final, events = stage_purchase(after, events, "event-1", lines(2), 12, "PayPal", "p2")
        self.assertEqual(len(final["lots"]), 2)
        lot = final["lots"][1]
        self.assertEqual(lot["prix_achat"], 42)
        self.assertEqual(len(lot["cards"]), 3)
        self.assertEqual(len({c["card_uid"] for c in lot["cards"]}), 3)
        self.assertTrue(all(not c["sold_entries"] for c in lot["cards"]))
        self.assertTrue(all(c["image_url"] for c in lot["cards"]))
        self.assertEqual(lot["cards"][0]["lang"], "ja")
        stats = brocante_stats(events["sessions"][0])
        self.assertEqual(stats["ca"], 0)
        self.assertEqual(stats["purchased_amount"], 42)
        self.assertEqual(stats["theoretical_cash"], 20)
        self.assertEqual(stats["net_cash"], -42)

    def test_purchase_costs_wait_for_complete_sale_prices(self):
        stock, data = fixtures()
        after, _ = stage_purchase(stock, data, "event-1", lines(3), 100, "PayPal", "p1")
        lot = after["lots"][-1]
        self.assertTrue(all(card["purchase_total"] is None for card in lot["cards"]))
        self.assertTrue(all(card["cost_basis_pending"] for card in lot["cards"]))
        lot["cards"][0]["suggested_price"] = 120
        lot["cards"][1]["suggested_price"] = 50
        self.assertEqual(finalize_brocante_purchase_costs(lot)["pending"], 1)
        self.assertTrue(all(card["purchase_total"] is None for card in lot["cards"]))

        lot["cards"][2]["suggested_price"] = 30
        result = finalize_brocante_purchase_costs(lot, allocated_at="2026-09-06T18:00:00")
        self.assertTrue(result["changed"])
        self.assertEqual([card["purchase_total"] for card in lot["cards"]], [60, 25, 15])
        self.assertEqual(sum(card["purchase_total"] for card in lot["cards"]), 100)
        self.assertTrue(all(not card["cost_basis_pending"] for card in lot["cards"]))

        lot["cards"][0]["suggested_price"] = 240
        self.assertFalse(finalize_brocante_purchase_costs(lot)["changed"])
        self.assertEqual([card["purchase_total"] for card in lot["cards"]], [60, 25, 15])

    def test_purchase_allocation_absorbs_rounding_on_last_card(self):
        stock, data = fixtures()
        after, _ = stage_purchase(stock, data, "event-1", lines(3), 100, "Espèces", "p1")
        lot = after["lots"][-1]
        for card in lot["cards"]:
            card["suggested_price"] = 1
        finalize_brocante_purchase_costs(lot)
        self.assertEqual([card["purchase_total"] for card in lot["cards"]], [33.33, 33.33, 33.34])

    def test_purchase_allocation_waits_when_a_reference_is_missing(self):
        stock, data = fixtures()
        after, _ = stage_purchase(stock, data, "event-1", lines(2), 40, "Espèces", "p1")
        lot = after["lots"][-1]
        for card in lot["cards"]:
            card["suggested_price"] = 20
        lot["brocante_purchases"][0]["cards"].append({"card_uid": "missing", "quantity": 1})
        self.assertEqual(finalize_brocante_purchase_costs(lot)["pending"], 1)
        self.assertTrue(all(card["purchase_total"] is None for card in lot["cards"]))

    def test_legacy_allocated_purchase_is_never_rewritten(self):
        lot = {
            "brocante_purchase_lot": True,
            "cost_basis_method": "per_card",
            "cards": [{"card_uid": "c1", "quantity": 1, "suggested_price": 999,
                       "purchase_price": 12, "purchase_total": 12}],
            "brocante_purchases": [{"purchase_id": "legacy", "amount": 12,
                                     "cards": [{"card_uid": "c1", "quantity": 1, "cost": 12}]}],
        }
        finalize_brocante_purchase_costs(lot)
        self.assertEqual((lot["cards"][0]["purchase_price"], lot["cards"][0]["purchase_total"]), (12, 12))

    def test_zero_cost_purchase_can_allocate_without_prices(self):
        stock, data = fixtures()
        after, _ = stage_purchase(stock, data, "event-1", lines(2), 0, "Espèces", "p1")
        lot = after["lots"][-1]
        self.assertEqual([card["purchase_total"] for card in lot["cards"]], [0, 0])
        self.assertTrue(all(not card["cost_basis_pending"] for card in lot["cards"]))

    def test_pending_purchase_has_no_invented_historical_cost(self):
        stock, data = fixtures()
        after, _ = stage_purchase(stock, data, "event-1", lines(), 40, "Espèces", "p1")
        lot = after["lots"][-1]
        self.assertIsNone(historical_unit_cost_or_none(lot, lot["cards"][0]))

    def test_purchase_search_accepts_joined_name_and_number(self):
        card = {"id": "xy-199", "name": "Dracaufeu", "localId": "199"}
        index = {"Dracaufeu": [(card, "Étincelles", "xy")]}
        normalize = lambda value: str(value or "").casefold().replace("é", "e")
        for query in ("dracaufeu", "dracaufeu 199", "dracaufeu199", "199"):
            self.assertEqual(search_received_cards(query, index, normalize)[0][0]["id"], "xy-199")

    def test_received_trade_quantities_weight_value_and_unit_cost(self):
        cards = [
            {"name": "A", "value": 20, "quantity": 2},
            {"name": "B", "value": 10, "quantity": 1},
        ]
        allocated = allocate_received_cards(cards, 90, [])
        self.assertEqual([card["trade_acquisition_total_cost"] for card in allocated], [72, 18])
        self.assertEqual([card["trade_acquisition_unit_cost"] for card in allocated], [36, 18])

    def test_cash_closure_and_non_cash_expenses(self):
        _, data = fixtures()
        event = data["sessions"][0]
        record_transaction(event, dict(transaction_id="s1", amount=100, physical_quantity=1, cost_basis=20,
                                       cost_basis_known=True, payment_method="Espèces"))
        event["purchases"] = [{"amount": 30, "payment_method": "Espèces"}]
        add_expense(event, "Stand", 10, "Emplacement")
        self.assertEqual(brocante_stats(event)["theoretical_cash"], 110)
        closed = close_session(event, 108, "Deux euros d'écart")
        self.assertEqual(closed["cash_variance"], -2)
        add_expense(event, "Parking", 5, "Transport", payment_method="PayPal")
        self.assertEqual(brocante_stats(event)["theoretical_cash"], 110)
        self.assertEqual(brocante_stats(event)["calculable_profit"], 65)

    def test_exchange_context_projects_without_ca_or_new_economics(self):
        stock, data = fixtures()
        trade = {"exchange_id": "trade-1", "date": "2026-09-06", "trade_cash_paid": 3,
                 "trade_cash_received": 10, "trade_acquisition_total_cost": 25, "given_cards": [], "received_cards": []}
        stock["trade_history"] = [trade]
        tag_trade(stock, "event-1", "trade-1")
        event = project_event(data["sessions"][0], stock)
        project_event(event, stock)
        self.assertEqual(trade["trade_acquisition_total_cost"], 25)
        self.assertEqual(brocante_stats(event)["ca"], 0)
        self.assertEqual(brocante_stats(event)["theoretical_cash"], 57)
        self.assertEqual(brocante_stats(event)["exchanges_count"], 1)
        self.assertTrue(deletion_audit(stock, data, "event-1")["blockers"])

    def test_legacy_trade_metadata_is_not_projected_as_v2_exchange(self):
        stock, data = fixtures()
        stock["trade_history"] = [{
            "exchange_id": "legacy-trade", "date": "2026-09-06",
            "brocante_id": "event-1", "trade_cash_paid": 20,
            "trade_cash_received": 50,
        }]
        event = project_event(data["sessions"][0], stock)
        self.assertEqual(event["exchanges"], [])
        self.assertEqual(brocante_stats(event)["theoretical_cash"], 50)
        self.assertTrue(deletion_audit(stock, data, "event-1")["blockers"])

    def test_delete_empty_expenses_and_unused_purchase(self):
        for purchased in (False, True):
            stock, data = fixtures()
            baseline = deepcopy(stock)
            add_expense(data["sessions"][0], "Stand", 10, "Emplacement")
            if purchased:
                stock, data = stage_purchase(stock, data, "event-1", lines(), 30, "Espèces", "p1")
            after, events = stage_delete(stock, data, "event-1")
            self.assertEqual(after, baseline)
            self.assertEqual(events["sessions"], [])

    def test_delete_blocks_used_or_transferred_purchase_and_drop_reference(self):
        for field in ("sold_quantity", "exchange_out_quantity", "stored_quantity", "is_collection_keep"):
            stock, data = fixtures()
            stock, data = stage_purchase(stock, data, "event-1", lines(), 30, "Espèces", "p1")
            stock["lots"][-1]["cards"][0][field] = 1
            with self.assertRaises(ValueError):
                stage_delete(stock, data, "event-1")
        stock, data = fixtures()
        stock, data = stage_purchase(stock, data, "event-1", lines(), 30, "Espèces", "p1")
        uid = stock["lots"][-1]["cards"][0]["card_uid"]
        with self.assertRaises(ValueError):
            stage_delete(stock, data, "event-1", {"drops": [{"cards": [{"card_uid": uid}]}]})

    def test_delete_blocks_duplicated_purchase_identity(self):
        stock, data = fixtures()
        stock, data = stage_purchase(stock, data, "event-1", lines(), 30, "Espèces", "p1")
        duplicate = deepcopy(stock["lots"][-1]["cards"][0])
        stock["lots"][0]["cards"].append(duplicate)
        with self.assertRaises(ValueError):
            stage_delete(stock, data, "event-1")

    def test_delete_blocks_unreliable_historical_links(self):
        stock, data = fixtures()
        record_transaction(data["sessions"][0], {"transaction_id": "legacy-unlinked", "amount": 10})
        with self.assertRaises(ValueError):
            stage_delete(stock, data, "event-1")

    def test_split_write_failure_compensates(self):
        state = {"stock": {"a": 1}, "events": {"b": 2}}
        calls = []
        def write_events(value):
            calls.append(value)
            if len(calls) == 1:
                raise OSError("write failure")
            state["events"] = value
        with self.assertRaises(OSError):
            commit_staged(state["stock"], state["events"], {"a": 3}, {"b": 4},
                          lambda value: state.update(stock=value), write_events)
        self.assertEqual(state, {"stock": {"a": 1}, "events": {"b": 2}})


class BrocanteSaleTests(unittest.TestCase):
    def setUp(self):
        self.stock, self.events = fixtures()
        def resolve(data, item):
            for li, lot in enumerate(data["lots"]):
                for ci, card in enumerate(lot["cards"]):
                    if card["card_uid"] == item.get("card_uid"):
                        return li, ci, lot, card
            return None, None, None, None
        sales_actions.configure_sales_actions({"ld": lambda: deepcopy(self.stock),
            "sd": lambda value: setattr(self, "stock", deepcopy(value)), "resolve_card_ref": resolve,
            "card_available_qty": lambda c: c["quantity"]-c.get("sold_quantity", 0),
            "new_uid": lambda p: p+"-1", "datetime": datetime})
        for target, replacement in [
            ("core.sales_actions.load_brocantes", lambda: deepcopy(self.events)),
            ("core.sales_actions.save_brocantes", lambda value: setattr(self, "events", deepcopy(value))),
            ("core.sales_actions.link_sale_to_vinted_drop_if_applicable", lambda *a: None),
            ("services.vinted_drops_service.link_sale_to_vinted_drop_if_applicable", lambda *a: None),
        ]:
            p = patch(target, replacement)
            p.start()
            self.addCleanup(p.stop)

    def sell(self):
        return sales_actions.scu_many([
            {"card_uid": "card-1", "quantity": 1, "unit_price": 10},
            {"line_type": "off_stock", "quantity": 12, "unit_price": 0.5, "cost_basis_known": True, "cost_basis": 1},
        ], "incorrect-channel", brocante_id="event-1", payment_method="Espèces", transaction_id="order-1")

    def test_mixed_order_shared_engine_tags_cash_costs_and_retry(self):
        self.assertTrue(self.sell()[0])
        self.assertTrue(self.sell()[0])
        sales = event_sales(self.stock, "event-1")
        self.assertEqual(len(sales), 2)
        self.assertEqual({s["canal"] for s in sales}, {"Brocante"})
        self.assertEqual({s["sale_transaction_id"] for s in sales}, {"order-1"})
        s = brocante_stats(self.events["sessions"][0])
        self.assertEqual((s["ca"], s["cards_sold"], s["sales_count"], s["theoretical_cash"], s["ca_off_stock"]), (16, 1, 1, 66, 6))
        self.assertEqual(s["calculable_profit"], 11)

    def test_mixed_deletion_uses_shared_cancellation_and_no_orphans(self):
        self.sell()
        with patch("core.sales_cancellation._restore_drop_items_for_sales") as external:
            stock, events = stage_delete(self.stock, self.events, "event-1")
            external.assert_not_called()
        self.assertEqual(stock["lots"][0]["cards"][0]["sold_quantity"], 0)
        self.assertEqual(event_sales(stock, "event-1"), [])
        self.assertEqual(events["sessions"], [])

    def test_cancelled_order_not_resurrected_by_projection(self):
        self.sell()
        sale_id = event_sales(self.stock, "event-1")[0]["sale_id"]
        cancel_sale_by_id(self.stock, sale_id, sync_related=False)
        project_event(self.events["sessions"][0], self.stock)
        self.assertEqual(brocante_stats(self.events["sessions"][0])["ca"], 0)

    def test_closed_event_rejects_sale_and_purchase(self):
        self.events["sessions"][0]["status"] = "closed"
        self.assertFalse(self.sell()[0])
        with self.assertRaises(ValueError):
            stage_purchase(self.stock, self.events, "event-1", lines(), 1, "Espèces", "p1")


if __name__ == "__main__":
    unittest.main()

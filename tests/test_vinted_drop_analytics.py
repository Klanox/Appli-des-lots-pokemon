from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from ui.pages import vinted_listings as vinted_page
from ui.pages.vinted_listings import (
    _analytics_price_bands,
    _analytics_remaining_items,
    _analytics_snapshot_at,
    _analytics_time_series,
    _analytics_timing,
    _comparison_time_series,
    _drop_metrics,
    _group_drop_transactions,
    _physical_price_band_rows,
    _render_analytics_charts,
    _sales_scope_metrics,
)


def _sale_row(sale_id, card_uid, quantity, revenue, *, drop_item_id=None, off_stock=False, transaction_id=None):
    return {
        "sale": {"sale_id": sale_id, "drop_item_id": drop_item_id, "sale_transaction_id": transaction_id},
        "card": {"card_uid": card_uid},
        "quantity": quantity,
        "revenue": revenue,
        "profit": revenue / 2,
        "date": "2026-09-02",
        "card_name": card_uid or "Vente hors stock",
        "is_off_stock": off_stock,
    }


class VintedDropAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.drop = {
            "cards": [
                {"drop_item_id": "item-low", "card_uid": "card-low", "price_at_add": 1.5, "quantity": 2, "status": "sold"},
                {"drop_item_id": "item-mid", "card_uid": "card-mid", "price_at_add": 6.0, "quantity": 2, "status": "sold"},
            ]
        }
        self.rows = [
            _sale_row("sale-low", "card-low", 2, 3.0, drop_item_id="item-low"),
            _sale_row("sale-mid", "card-mid", 2, 10.0, drop_item_id="item-mid"),
            _sale_row("off-stock", None, 0, 19.0, off_stock=True),
        ]

    def test_scope_keeps_off_stock_out_of_physical_card_metrics(self):
        scope = _sales_scope_metrics(self.rows)
        metrics = _drop_metrics(self.drop, self.rows)

        self.assertEqual(scope["sold_cards"], 4)
        self.assertEqual(scope["card_transactions"], 2)
        self.assertEqual(scope["off_stock_transactions"], 1)
        self.assertEqual(metrics["ca_total"], 32.0)
        self.assertEqual(metrics["ca_cards"], 13.0)
        self.assertEqual(metrics["ca_off_stock"], 19.0)
        self.assertEqual(metrics["avg_cards_per_transaction"], 2.0)

    def test_price_bands_use_each_physical_item_published_price(self):
        paired = _physical_price_band_rows(self.drop, self.rows)

        self.assertEqual([(row["sale"]["sale_id"], price) for row, price in paired], [
            ("sale-low", 1.5),
            ("sale-mid", 6.0),
        ])
        self.assertNotIn("off-stock", [row["sale"]["sale_id"] for row, _ in paired])

    def test_multi_card_transaction_counts_once(self):
        rows = [
            _sale_row("bundle", "card-low", 1, 1.5, drop_item_id="item-low"),
            _sale_row("bundle", "card-mid", 1, 6.0, drop_item_id="item-mid"),
        ]

        scope = _sales_scope_metrics(rows)

        self.assertEqual(scope["sold_cards"], 2)
        self.assertEqual(scope["card_transactions"], 1)

    def test_mixed_transaction_counts_as_one_order_and_one_card_transaction(self):
        rows = [
            _sale_row("card-line", "card-low", 1, 10.0, transaction_id="order-1"),
            _sale_row("off-line", None, 0, 5.0, off_stock=True, transaction_id="order-1"),
        ]

        scope = _sales_scope_metrics(rows)

        self.assertEqual(scope["total_transactions"], 1)
        self.assertEqual(scope["card_transactions"], 1)
        self.assertEqual(scope["off_stock_transactions"], 0)
        self.assertEqual(scope["ca_total"], 15.0)
        self.assertEqual(scope["ca_cards"], 10.0)
        self.assertEqual(scope["ca_off_stock"], 5.0)

    def test_dashboard_helpers_keep_price_bands_and_checkpoints_deterministic(self):
        launched = datetime(2026, 8, 27, 12, 0)
        drop = {
            "drop_launched_at": launched.isoformat(),
            "cards": [
                {"drop_item_id": "item-low", "card_uid": "card-low", "price_at_add": 1.5, "quantity": 2, "status": "sold"},
                {"drop_item_id": "item-mid", "card_uid": "card-mid", "price_at_add": 6.0, "quantity": 1, "status": "online", "name": "Carte en ligne", "online_at": launched.isoformat()},
            ],
        }
        rows = [
            {**_sale_row("sale-low", "card-low", 2, 3.0, drop_item_id="item-low"), "date": launched + timedelta(minutes=31)},
            {**_sale_row("off-stock", None, 0, 19.0, off_stock=True), "date": launched + timedelta(hours=1)},
        ]

        bands = _analytics_price_bands([drop], {"": rows})
        timing = _analytics_timing(drop, rows, now=launched + timedelta(days=2))
        remaining = _analytics_remaining_items([drop], now=launched + timedelta(days=2))

        self.assertEqual(bands[0]["sold"], 2)
        self.assertEqual(bands[0]["ca"], 3.0)
        self.assertEqual(bands[2]["sold"], 0)
        self.assertEqual(timing["milestones"]["first_sale"], "31 min")
        self.assertEqual(timing["checkpoints"][0]["label"], "H+1")
        self.assertEqual(timing["checkpoints"][0]["sold"], 2)
        self.assertFalse(timing["checkpoints"][4]["upcoming"])
        self.assertTrue(timing["checkpoints"][5]["upcoming"])
        self.assertEqual(remaining["remaining_cards"], 1)
        self.assertEqual(remaining["top_online"][0]["name"], "Carte en ligne")

    def test_transaction_series_keeps_real_timestamps_and_groups_mixed_orders(self):
        launched = datetime(2026, 8, 27, 17, 27)
        drop = {"drop_launched_at": launched.isoformat(), "cards": [{"quantity": 10}]}
        rows = [
            {**_sale_row("card-line", "card-a", 2, 10.0, transaction_id="order-1"), "date": launched + timedelta(minutes=31)},
            {**_sale_row("off-line", None, 0, 5.0, off_stock=True, transaction_id="order-1"), "date": launched + timedelta(minutes=31)},
            {**_sale_row("card-line-2", "card-b", 1, 4.0, transaction_id="order-2"), "date": launched + timedelta(hours=2, minutes=5)},
        ]

        events = _group_drop_transactions(rows)
        series = _analytics_time_series(drop, rows, now=launched + timedelta(hours=24), range_hours=24)
        snapshot = _analytics_snapshot_at(drop, rows, launched + timedelta(hours=1))

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kind"], "mixed")
        self.assertEqual(events[0]["revenue"], 15.0)
        self.assertEqual(events[0]["sold_cards"], 2)
        self.assertEqual(series[0]["timestamp"], launched)
        self.assertEqual(series[1]["timestamp"], launched + timedelta(minutes=31))
        self.assertEqual(series[1]["event_label"], "Transaction mixte")
        self.assertEqual(series[-1]["timestamp"], launched + timedelta(hours=24))
        self.assertFalse(series[-1]["is_transaction"])
        self.assertEqual(snapshot["revenue"], 15.0)
        self.assertEqual(snapshot["sold"], 2)

    def test_comparison_series_aligns_drops_on_elapsed_time(self):
        primary_launch = datetime(2026, 9, 1, 18, 0)
        reference_launch = datetime(2026, 8, 1, 9, 30)
        primary = {"drop_launched_at": primary_launch.isoformat(), "cards": [{"quantity": 10}]}
        reference = {"drop_launched_at": reference_launch.isoformat(), "cards": [{"quantity": 10}]}
        primary_rows = [{**_sale_row("p", "p-card", 1, 10.0), "date": primary_launch + timedelta(hours=2)}]
        reference_rows = [{**_sale_row("r", "r-card", 1, 8.0), "date": reference_launch + timedelta(hours=2)}]

        series = _comparison_time_series(primary, primary_rows, reference, reference_rows, now=primary_launch + timedelta(hours=6))

        two_hours = next(point for point in series if point["elapsed_hours"] == 2.0)
        self.assertEqual(two_hours["primary"]["revenue"], 10.0)
        self.assertEqual(two_hours["reference"]["revenue"], 8.0)

    def test_j7_checkpoint_uses_exact_seven_times_twenty_four_hours(self):
        launched = datetime(2026, 8, 27, 17, 27)
        drop = {"drop_launched_at": launched.isoformat(), "cards": [{"quantity": 2}]}
        rows = [{**_sale_row("late", "card", 1, 12.0), "date": launched + timedelta(days=7, minutes=1)}]

        before = _analytics_timing(drop, rows, now=launched + timedelta(days=7))
        after = _analytics_timing(drop, rows, now=launched + timedelta(days=7, minutes=2))

        before_j7 = next(point for point in before["checkpoints"] if point["label"] == "J+7")
        after_j7 = next(point for point in after["checkpoints"] if point["label"] == "J+7")
        self.assertFalse(before_j7["upcoming"])
        self.assertEqual(before_j7["revenue"], 0.0)
        self.assertEqual(after_j7["revenue"], 0.0)

    def test_charts_render_one_precise_altair_spec(self):
        class ChartStreamlit:
            def __init__(self):
                self.charts = []

            def altair_chart(self, chart, **_kwargs):
                self.charts.append(chart)

            def caption(self, _value):
                raise AssertionError("A chart series should not use the empty fallback")

        streamlit = ChartStreamlit()
        series = [{
            "timestamp": datetime(2026, 8, 27, 17, 27),
            "revenue": 100.0,
            "profit": 60.0,
            "sold": 20,
            "sell_through": 25.0,
            "transaction_revenue": 100.0,
            "event_label": "Transaction cartes",
            "event_kind": "cartes",
            "is_transaction": True,
        }]

        with patch.object(vinted_page, "st", streamlit):
            _render_analytics_charts(series)

        self.assertEqual(len(streamlit.charts), 1)
        spec = streamlit.charts[0].to_dict(validate=True)
        self.assertEqual(spec["layer"][0]["encoding"]["x"]["field"], "timestamp")
        self.assertIn("event_label", str(spec))


if __name__ == "__main__":
    unittest.main()

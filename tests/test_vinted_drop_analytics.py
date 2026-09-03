from __future__ import annotations

import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import patch

from ui.pages import vinted_listings as vinted_page
from ui.pages.vinted_listings import (
    _analytics_price_bands,
    _analytics_remaining_items,
    _analytics_timing,
    _drop_metrics,
    _physical_price_band_rows,
    _render_analytics_charts,
    _sales_scope_metrics,
)


def _sale_row(sale_id, card_uid, quantity, revenue, *, drop_item_id=None, off_stock=False):
    return {
        "sale": {"sale_id": sale_id, "drop_item_id": drop_item_id},
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
        self.assertEqual(timing["checkpoints"][0]["sold"], 2)
        self.assertTrue(timing["checkpoints"][3]["upcoming"])
        self.assertEqual(remaining["remaining_cards"], 1)
        self.assertEqual(remaining["top_online"][0]["name"], "Carte en ligne")

    def test_charts_render_two_altair_specs_with_safe_data_fields(self):
        class ChartStreamlit:
            def __init__(self):
                self.charts = []

            def columns(self, count, **_kwargs):
                return [nullcontext() for _ in range(count)]

            def altair_chart(self, chart, **_kwargs):
                self.charts.append(chart)

            def caption(self, _value):
                raise AssertionError("A chart series should not use the empty fallback")

        streamlit = ChartStreamlit()
        series = [{
            "Jour": "J0",
            "CA cumulé": 100.0,
            "Bénéfice cumulé": 60.0,
            "Cartes vendues": 20,
            "Taux d'écoulement": 25.0,
        }]

        with patch.object(vinted_page, "st", streamlit):
            _render_analytics_charts(series)

        self.assertEqual(len(streamlit.charts), 2)
        for chart in streamlit.charts:
            spec = chart.to_dict(validate=True)
            self.assertEqual(spec["layer"][0]["encoding"]["x"]["field"], "day_label")
            self.assertNotIn("Taux d'écoulement:Q", str(spec))


if __name__ == "__main__":
    unittest.main()

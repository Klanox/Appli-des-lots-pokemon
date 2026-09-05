from copy import deepcopy
from datetime import datetime
import unittest

from services.monthly_profiles import PROFILE_METADATA, build_profile_stats, score_profile
from ui.pages.statistics import _aggregate_sales, _build_monthly_stats, _is_system_lot


def baseline():
    return dict(ca=1000, benef=200, qty=100, transactions=50, purchases=500, acquired=100,
                avg_card=10, margin=20, rotation=.02, efficiency=.4, discount_share=.1)


def sale(date, sale_id, *, quantity=1, price=10, tx=None, off_stock=False, reference=10):
    original = dict(date=date.isoformat(), sale_id=sale_id, quantity=quantity, price=price)
    if reference is not None:
        original["suggested_price_at_sale"] = reference
    if tx:
        original["sale_transaction_id"] = tx
    return dict(date=date, month=date.strftime("%Y-%m"), sale=original, price=price,
                quantity=quantity, benef=price / 2, is_off_stock=off_stock)


class ProfileScoringTests(unittest.TestCase):
    def test_twelve_distinct_profiles(self):
        changes = {
            "buyer": dict(acquired=1000, purchases=120),
            "investment": dict(acquired=5, purchases=7000),
            "volume": dict(qty=1000),
            "record": dict(ca=10000),
            "calm": dict(ca=10, qty=1, transactions=1),
            "premium": dict(avg_card=100),
            "profitable": dict(benef=2000),
            "margin": dict(margin=95),
            "dynamic": dict(transactions=500),
            "rotation": dict(rotation=.5),
            "efficient": dict(efficiency=4),
            "negotiated": dict(discount_share=.9),
        }
        self.assertEqual(set(changes), set(PROFILE_METADATA))
        for expected, change in changes.items():
            with self.subTest(expected=expected):
                result = score_profile({**baseline(), **change}, [baseline(), baseline()], record_allowed=expected == "record")
                self.assertEqual(result["id"], expected)

    def test_strongest_axis_not_first_condition(self):
        result = score_profile({**baseline(), "qty": 120, "benef": 420}, [baseline()] * 3)
        self.assertEqual(result["id"], "profitable")
        self.assertGreater(result["scores"]["profitable"], result["scores"]["volume"])

    def test_missing_metrics_and_flat_history_do_not_invent_calm(self):
        self.assertIsNone(score_profile(baseline(), [baseline()] * 2)["id"])
        result = score_profile({**baseline(), "discount_share": None, "rotation": None, "qty": 300}, [baseline()] * 2)
        self.assertEqual(result["id"], "volume")
        self.assertNotIn("negotiated", result["scores"])
        self.assertNotIn("rotation", result["scores"])
        self.assertIsNone(score_profile(baseline(), [baseline()])["id"])

    def test_zero_reference_and_negative_profit_are_finite(self):
        result = score_profile({**baseline(), "benef": -20}, [{**baseline(), "benef": -100}] * 2)
        self.assertNotIn("profitable", result["scores"])
        result = score_profile({"acquired": 100}, [{"acquired": 0}, {"acquired": 0}])
        self.assertEqual(result["id"], "buyer")

    def test_ties_are_independent_of_input_order(self):
        current = {**baseline(), "qty": 200, "transactions": 100}
        result = score_profile(current, [baseline()] * 2)
        self.assertEqual(result, score_profile(dict(reversed(list(current.items()))), [baseline()] * 2))


class ProfileDataTests(unittest.TestCase):
    def build(self, rows, purchases=(), lots=(), now=datetime(2026, 9, 5, 12)):
        before = deepcopy((rows, purchases, lots))
        monthly = _build_monthly_stats(rows, purchases)
        result = build_profile_stats(monthly, rows, purchases, lots, now,
                                     aggregate=_aggregate_sales, is_system=_is_system_lot)
        self.assertEqual(before, (rows, purchases, lots))
        return result

    def test_current_record_must_exceed_full_previous_months(self):
        rows = [sale(datetime(2026, m, day), f"{m}-{day}", price=amount)
                for m in (7, 8) for day, amount in ((1, 10), (20, 1000))]
        rows.append(sale(datetime(2026, 9, 2), "current", price=500))
        result = self.build(rows)["2026-09"]
        self.assertNotIn("record", result["_profile_result"]["scores"])
        rows[-1] = sale(datetime(2026, 9, 2), "current", price=1500)
        result = self.build(rows)["2026-09"]
        self.assertIn("record", result["_profile_result"]["scores"])

    def test_mtd_and_early_tracking_gap(self):
        rows = [sale(datetime(2026, m, day, 10), f"{m}-{day}") for m in (7, 8, 9) for day in (3, 6)]
        result = self.build(rows)
        self.assertEqual(result["2026-09"]["qty"], 1)
        self.assertEqual(result["2026-08"]["qty"], 2)
        self.assertNotIn("calm", result["2026-09"]["_profile_result"]["scores"])

    def test_mixed_transactions_are_single_orders_and_off_stock_not_volume(self):
        date = datetime(2026, 8, 3)
        rows = [sale(date, "a", tx="mixed", quantity=3), sale(date, "b", tx="mixed", off_stock=True)]
        result = self.build(rows)["2026-08"]
        self.assertEqual(result["transactions"], 1)
        self.assertEqual(result["qty"], 3)
        self.assertEqual(result["ca"], 20)
        self.assertAlmostEqual(result["avg_card"], 10 / 3)

    def test_rotation_and_discount_use_actual_dates_and_price_reference(self):
        rows = [sale(datetime(2026, 8, 3), str(i), price=8) for i in range(3)]
        cards = [{"card_uid": str(i), "added_at": "2026-08-01", "quantity": 1,
                  "sold_entries": [row["sale"]]} for i, row in enumerate(rows)]
        result = self.build(rows, lots=[{"cards": cards}])["2026-08"]
        self.assertEqual(result["rotation_days"], 2)
        self.assertEqual(result["discount_share"], 1)
        for row in rows:
            del row["sale"]["suggested_price_at_sale"]
        for card in cards:
            card["added_at"] = "2026-09-01"
        result = self.build(rows, lots=[{"cards": cards}])["2026-08"]
        self.assertIsNone(result["rotation"])
        self.assertIsNone(result["discount_share"])

    def test_acquisitions_ignore_storage_copies_and_trade_transfers(self):
        lot = {"lot_uid": "source", "created": "2026-08-01", "prix_achat": 120, "cards": [{"card_uid": "a", "quantity": 100}]}
        storage = {"is_storage": True, "cards": [{"card_uid": "b", "quantity": 100, "added_at": "2026-08-01"}]}
        p = [{"date": datetime(2026, 8, 1), "month": "2026-08", "cost": 120}]
        result = self.build([], p, [lot, storage])["2026-08"]
        self.assertEqual(result["acquired"], 100)
        self.assertEqual(result["purchases"], 120)

    def test_no_investment_does_not_produce_infinite_efficiency(self):
        result = self.build([sale(datetime(2026, 8, 1), "a")])["2026-08"]
        self.assertIsNone(result["efficiency"])

    def test_missing_acquisition_history_disables_incomplete_feature(self):
        rows = [sale(datetime(2026, 8, 1), "a")]
        lots = [{"cards": [{"quantity": 100}]}]
        result = self.build(rows, lots=lots)["2026-08"]
        self.assertIsNone(result["acquired"])

    def test_mtd_is_clamped_to_shorter_historical_month(self):
        rows = [sale(datetime(2026, 2, 28, 23), "feb"), sale(datetime(2026, 3, 30, 23), "mar")]
        result = self.build(rows, now=datetime(2026, 3, 31, 12))
        self.assertEqual(result["2026-03"]["qty"], 1)
        self.assertNotIn("calm", result["2026-03"]["_profile_result"]["scores"])


if __name__ == "__main__":
    unittest.main()

"""Barre latérale : chiffres de l'année civile (Vendues, CA, Bénéfice réalisé, Trésorerie nette) et totaux.

Jeux de données temporaires uniquement ; l'année est toujours passée en paramètre (jamais l'horloge).
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import logic
from services import sidebar_stats_service as sss
from ui import sidebar as sidebar_ui
from ui.pages import statistics as stats


def _card(uid, qty, sold_qty, entries, **extra):
    card = {"card_uid": uid, "name": uid, "quantity": qty, "sold_quantity": sold_qty, "suggested_price": 10.0, "sold_entries": entries}
    card.update(extra)
    return card


def _entry(date, price, qty=1, **extra):
    entry = {"date": date, "price": price, "quantity": qty, "canal": "Vinted", "suggested_price_at_sale": price}
    entry.update(extra)
    return entry


LOT_A = {
    "nom": "Lot A", "prix_achat": 100.0, "created": "2026-05-01T10:00:00",
    "cards": [
        _card("c1", 5, 3, [_entry("2026-06-01T10:00:00", 12.0), _entry("2026-12-30T10:00:00", 15.0), _entry("2027-01-10T10:00:00", 20.0)]),
        _card("c2", 2, 1, [_entry("2026-09-01T10:00:00", 0.0, is_exchange=True)]),  # donnée en échange : sortie du stock, pas vendue
    ],
    "ventes": [
        {"date": "2026-03-16T10:00:00", "price": 200.0, "quantity": 1, "is_lot_sale": True, "card_name": "Vente initiale"},
        {"date": "2026-07-01T10:00:00", "price": 5.0, "quantity": 1, "is_off_stock": True, "cost_basis_known": False},
        {"date": "2026-08-01T10:00:00", "price": 7.0, "is_exchange_benefit": True},
    ],
}
LOT_B = {"nom": "Lot B", "prix_achat": 50.0, "created": "2027-01-05T09:00:00", "cards": [_card("c3", 4, 0, [])], "ventes": []}
LOT_ARCHIVE = {"nom": "Lot C", "prix_achat": 30.0, "created": "2026-02-01T10:00:00",
               "cards": [_card("c4", 3, 2, [_entry("2026-02-10T10:00:00", 40.0, qty=2)])], "ventes": []}


class SidebarStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive_path = os.path.join(self.tmp.name, "lots_archives.json")
        with open(self.archive_path, "w", encoding="utf-8") as handle:
            json.dump([LOT_ARCHIVE], handle)
        self.lots = [json.loads(json.dumps(LOT_A)), json.loads(json.dumps(LOT_B))]
        self.ld_calls = 0
        owner = self

        def fake_ld():
            owner.ld_calls += 1
            return {"lots": owner.lots}

        patcher_ld = patch.object(logic, "ld", fake_ld)
        patcher_path = patch.object(logic, "LOTS_ARCHIVES_FILE", self.archive_path)
        patcher_ld.start(), patcher_path.start()
        self.addCleanup(patcher_ld.stop)
        self.addCleanup(patcher_path.stop)
        logic.gst.clear()
        self.addCleanup(logic.gst.clear)

    def test_year_change_resets_year_figures_but_not_totals_or_stock(self):
        y26, y27 = logic.gst(2026), logic.gst(2027)
        self.assertEqual((y26["year_sold_cards"], y26["year_revenue"]), (4, 272.0))   # 1+1 (Lot A) + 2 (archive)
        self.assertEqual((y27["year_sold_cards"], y27["year_revenue"]), (1, 20.0))
        # Totaux et stock : identiques quelle que soit l'année demandée.
        for key in ("sold_cards", "total_revenue", "total_profit", "remaining_cards", "stock_value", "total_cards"):
            self.assertEqual(y26[key], y27[key], key)
        self.assertEqual(y26["sold_cards"], 5)            # 3 + 0 (échange donné) + 2
        self.assertEqual(y26["total_revenue"], 292.0)     # bénéfice d'échange exclu
        self.assertEqual(y26["total_profit"], 292.0 - 180.0)
        self.assertEqual(y26["remaining_cards"], (5 - 3) + (2 - 1) + 4 + (3 - 2))
        # Les chiffres de l'année s'additionnent au total.
        self.assertEqual(y26["year_sold_cards"] + y27["year_sold_cards"], y26["sold_cards"])
        self.assertAlmostEqual(y26["year_revenue"] + y27["year_revenue"], y26["total_revenue"])

    def test_year_without_any_sale_is_zero_not_missing(self):
        data = logic.gst(2028)
        self.assertEqual((data["year_sold_cards"], data["year_revenue"], data["year_realized_profit"]), (0, 0.0, 0.0))
        self.assertEqual((data["year_purchases"], data["year_cash_profit"]), (0.0, 0.0))
        self.assertEqual(data["sold_cards"], 5)  # le total ne bouge pas
        self.assertIsNotNone(data["total_realized_profit"])

    def test_net_cash_of_the_year_is_revenue_minus_lots_created_that_year(self):
        y26, y27 = logic.gst(2026), logic.gst(2027)
        self.assertEqual(y26["year_purchases"], 130.0)    # Lot A + Lot C ; le lot B est de 2027
        self.assertEqual(y26["year_cash_profit"], 272.0 - 130.0)
        self.assertEqual(y27["year_purchases"], 50.0)
        self.assertEqual(y27["year_cash_profit"], 20.0 - 50.0)  # peut être négatif : achat récent pas encore vendu
        self.assertAlmostEqual(y26["year_cash_profit"] + y27["year_cash_profit"], y26["total_profit"])

    def test_bulk_march_lots_count_in_2026_and_undated_lots_only_in_total(self):
        self.lots.append({"nom": "Lot bloc", "prix_achat": 60.0, "created": "2026-03-16T12:00:00", "cards": [], "ventes": []})
        self.lots.append({"nom": "Lot sans date", "prix_achat": 10.0, "cards": [], "ventes": []})
        logic.gst.clear()
        data = logic.gst(2026)
        self.assertEqual(data["year_purchases"], 190.0)   # +60 (créé le 16/03/2026), le lot sans date n'entre dans aucune année
        self.assertEqual(logic.gst(2027)["year_purchases"], 50.0)
        self.assertEqual(data["total_profit"], 292.0 - 250.0)  # le total, lui, compte tous les lots

    def test_realized_profit_matches_statistics_definition(self):
        rows, _ = stats._collect_statistics_data({"lots": self.lots}, calc_cout_lot_func=logic.calc_cout_lot,
                                                 effective_purchase_price_func=logic.effective_purchase_price, lots_archives_path=self.archive_path)
        data = logic.gst(2026)
        by_year = {y: stats._aggregate_sales([r for r in rows if r["date"].year == y])["benef"] for y in (2026, 2027)}
        self.assertAlmostEqual(data["year_realized_profit"], by_year[2026])
        self.assertAlmostEqual(logic.gst(2027)["year_realized_profit"], by_year[2027])
        self.assertAlmostEqual(data["total_realized_profit"], stats._aggregate_sales(rows)["benef"])
        self.assertAlmostEqual(data["total_realized_profit"], by_year[2026] + by_year[2027])
        # La vente initiale (200 €) est bien incluse dans le bénéfice réalisé de 2026.
        self.assertGreater(data["year_realized_profit"], 150.0)

    def test_realized_profit_unavailable_is_none_not_zero(self):
        with patch.object(stats, "_collect_statistics_data", side_effect=RuntimeError("boom")):
            logic.gst.clear()
            data = logic.gst(2026)
        self.assertIsNone(data["year_realized_profit"])
        self.assertIsNone(data["total_realized_profit"])
        self.assertEqual(data["total_revenue"], 292.0)  # le reste de la barre latérale n'est pas touché

    def test_cache_is_shared_for_one_year_and_renewed_when_the_year_changes(self):
        logic.gst(2026)
        calls = self.ld_calls
        logic.gst(2026)
        self.assertEqual(self.ld_calls, calls)        # 2e appel : servi par le cache (ttl 30 s)
        logic.gst(2027)
        self.assertEqual(self.ld_calls, calls + 1)    # nouvelle année : nouveau calcul, sans attendre l'expiration

    def test_service_is_pure_and_ignores_unreadable_dates(self):
        lots = [{"ventes": [{"date": "pas une date", "price": 9.0}, {"date": "2027-02-01", "price": 3.0}], "cards": [], "prix_achat": 4.0}]
        self.assertEqual(sss.year_sales_figures(lots, 2027), (3.0, 0))
        self.assertIsNone(sss.lot_year(lots[0]))
        self.assertEqual(sss.realized_profit([]), 0.0)
        self.assertIsNone(sss.realized_profit([{"date": None, "benef": None}]))

    def test_period_card_html_has_light_violet_year_and_small_lines(self):
        html = sidebar_ui.render_sidebar_period_stat("CA", 2027, "0.00€", ["Total : 292.00€", "", "x <b>"])
        self.assertIn("CA", html)
        self.assertIn('ps-side-period-year">· 2027<', html)
        self.assertEqual(html.count("ps-side-period-sub"), 2)  # ligne vide ignorée
        self.assertNotIn("<b>", html)                           # échappé
        self.assertIn("#A78BFA", sidebar_ui.SIDEBAR_PERIOD_CSS)


if __name__ == "__main__":
    unittest.main()

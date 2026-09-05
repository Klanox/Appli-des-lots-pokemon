from datetime import datetime
import unittest
from unittest.mock import patch

from services.inventory_ordering import card_matches_inventory_query, sort_inventory_records
from services.vinted_channels import sale_channel_key
from ui.pages.counters import collect_channel_counter_totals, default_vinted_counter_state
from ui.pages.statistics import (
    MONTHLY_PROFILE_EXPLANATIONS, _comparable_month_metrics, _metric_delta_html,
    _profile_help_html, _chart_sentence, _build_monthly_stats, _comparable_profile_stats,
)
from ui.pages.sales import _sale_frontend_lot_groups


def _row(date_value, price, *, quantity=1, is_off_stock=False):
    return {
        "date": datetime.fromisoformat(date_value),
        "price": price,
        "quantity": quantity,
        "benef": price / 2,
        "is_off_stock": is_off_stock,
        "sale": {"sale_id": f"sale-{date_value}-{price}"},
    }


class InventoryStatisticsCountersTests(unittest.TestCase):
    def test_historical_renderer_groups_only_without_search(self):
        items = [(i, 0, {"card_uid": str(i), "name": "Pikachu", "added_at": date},
                  {"lot_uid": str(i), "nom": str(i)}, 1)
                 for i, date in [(0, "2026-09-01"), (1, "2026-03-01"), (2, "2026-06-01")]]
        with patch('ui.pages.sales._sale_image_preload_urls', return_value=[]):
            grouped = _sale_frontend_lot_groups(items, str, lambda *_: False)
            self.assertEqual([g['lot_name'] for g in grouped], ['0', '1', '2'])
            self.assertTrue(all(not g['hide_header'] for g in grouped))
            records = sort_inventory_records([dict(lot_idx=i, card_idx=c, card=card, lot=lot, stock=q) for i,c,card,lot,q in items])
            ordered = [(r['lot_idx'],r['card_idx'],r['card'],r['lot'],r['stock']) for r in records]
            search = _sale_frontend_lot_groups(ordered, str, lambda *_: False, continuous=True)
            self.assertEqual(len(search), 1)
            self.assertTrue(search[0]['hide_header'])
            self.assertEqual([c['card_uid'] for c in search[0]['cards']], ['1','2','0'])
            self.assertEqual(grouped, _sale_frontend_lot_groups(items, str, lambda *_: False))

    def test_tooltip_icon_has_the_specific_definition(self):
        for label, explanation in MONTHLY_PROFILE_EXPLANATIONS.items():
            markup = _profile_help_html(label, short=True)
            import html
            self.assertIn(html.escape(explanation), markup)
            self.assertIn('ps-stats-profile-tooltip', markup)
            self.assertNotIn('title="', markup)
            self.assertNotIn('Survolez', markup)

    def test_zero_reference_is_explicit_and_margin_uses_points(self):
        self.assertIn('+157,40 € · base 0', _metric_delta_html(157.4, 0, unit='€'))
        self.assertIn('+22 · base 0', _metric_delta_html(22, 0))
        self.assertIn('+0 · base 0', _metric_delta_html(0, 0))
        self.assertIn('+7,4 pts', _metric_delta_html(71.4, 64, unit='pts'))
        self.assertIn('+50,0%', _metric_delta_html(-5, -10))
        self.assertIn('Marge non comparable', _metric_delta_html(71.4, None, unit='pts'))

    def test_short_previous_month_is_clamped_and_boundaries_do_not_overlap(self):
        rows = [_row('2026-02-28T23:59:59', 10), _row('2026-03-01T00:00:00', 20), _row('2026-04-01T00:00:00', 500)]
        current, prev, _ = _comparable_month_metrics(rows, '2026-03', now=datetime(2026,3,31,12))
        self.assertEqual((current['ca'],prev['ca']), (20,10))
        current, prev, _ = _comparable_month_metrics(rows, '2026-03', now=datetime(2026,4,5))
        self.assertEqual((current['ca'],prev['ca']), (20,10))

    def test_date_only_rows_and_same_hour_cutoff(self):
        rows = [_row('2026-08-05',10), _row('2026-08-05T15:00:00',50), _row('2026-09-05',20)]
        current,prev,_ = _comparable_month_metrics(rows,'2026-09',now=datetime(2026,9,5,12))
        self.assertEqual((current['ca'],prev['ca']),(20,10))

    def test_evolution_sentence_and_profile_use_comparable_rows(self):
        rows = [_row('2026-08-02',10), _row('2026-08-20',500), _row('2026-09-02',20)]
        for row in rows:
            row['month'] = row['date'].strftime('%Y-%m')
        stats = _build_monthly_stats(rows, [])
        text = _chart_sentence('2026-09', stats, sorted(stats), all_sales=rows, now=datetime(2026,9,5))
        self.assertIn('+100,0 %', text)
        profiles = _comparable_profile_stats(rows, [], stats, datetime(2026,9,5))
        self.assertEqual(profiles['2026-08']['ca'], 10)

    def test_inventory_records_are_continuous_and_oldest_first(self):
        records = [
            {"lot_idx": 1, "card_idx": 0, "lot": {"created": "2026-05-01T10:00:00"}, "card": {"name": "Nouvelle", "added_at": "2026-06-01T10:00:00"}},
            {"lot_idx": 0, "card_idx": 1, "lot": {"created": "2026-05-02T10:00:00"}, "card": {"name": "Ancienne", "added_at": "2026-04-01T10:00:00"}},
            {"lot_idx": 0, "card_idx": 0, "lot": {"created": "2026-03-01T10:00:00"}, "card": {"name": "Repli lot"}},
        ]
        ordered = sort_inventory_records(records)
        self.assertEqual([record["card"]["name"] for record in ordered], ["Repli lot", "Ancienne", "Nouvelle"])

    def test_inventory_search_matches_accents_number_and_set(self):
        card = {"name": "Pikachu Éclatant", "number": "SWSH145", "set": "Évolution Céleste", "language": "FR"}
        self.assertTrue(card_matches_inventory_query(card, "pik"))
        self.assertTrue(card_matches_inventory_query(card, "eclatant"))
        self.assertTrue(card_matches_inventory_query(card, "swsh145"))
        self.assertTrue(card_matches_inventory_query(card, "évolution"))
        self.assertFalse(card_matches_inventory_query(card, "mewtwo"))

    def test_running_month_compares_only_the_same_elapsed_period(self):
        rows = [_row("2026-09-02T09:00:00", 20), _row("2026-08-02T09:00:00", 10), _row("2026-08-20T09:00:00", 90)]
        current, previous, is_mtd = _comparable_month_metrics(rows, "2026-09", now=datetime(2026, 9, 5, 12, 0))
        self.assertTrue(is_mtd)
        self.assertEqual(current["ca"], 20)
        self.assertEqual(previous["ca"], 10)

    def test_closed_month_compares_two_complete_months(self):
        rows = [_row("2026-08-02T09:00:00", 10), _row("2026-08-20T09:00:00", 90), _row("2026-07-31T18:00:00", 30)]
        current, previous, is_mtd = _comparable_month_metrics(rows, "2026-08", now=datetime(2026, 9, 5, 12, 0))
        self.assertFalse(is_mtd)
        self.assertEqual(current["ca"], 100)
        self.assertEqual(previous["ca"], 30)

    def test_month_profile_explanations_cover_existing_labels(self):
        expected = {"🏆 Mois record", "🌱 Mois d’investissement", "📦 Mois de volume", "💰 Mois rentable", "🌿 Mois calme", "🛒 Mois acheteur", "💎 Mois premium", "📈 Mois de marge", "⚡ Mois dynamique", "🔄 Mois de rotation", "🎯 Mois efficace", "🤝 Mois négocié"}
        self.assertEqual(expected, set(MONTHLY_PROFILE_EXPLANATIONS))
        self.assertTrue(all(MONTHLY_PROFILE_EXPLANATIONS[label] for label in expected))

    def test_choppetacarte_counter_uses_current_and_historical_aliases(self):
        states = {key: {"start_date": "2026-01-01", "start_datetime": "2026-01-01"} for key in ("dexify", "pokedeal", "choppetacarte")}
        lots = [{"ventes": [{"canal": "Choppe Ta Carte", "date": "2026-08-27T18:00:00", "price": 8.4, "quantity": 1}], "cards": [{"sold_entries": [{"canal": "ChoppeTaCarte", "date": "2026-08-28T18:00:00", "price": 2.0, "quantity": 2}]}]}]
        totals = collect_channel_counter_totals(lots, vinted_states=states, main_year="2026")
        self.assertEqual(sale_channel_key("Choppe Ta Carte"), "choppetacarte")
        self.assertEqual(totals["choppetacarte"], {"nb": 3, "ca": 10.4})

    def test_new_vinted_counter_starts_at_the_beginning_of_its_year(self):
        state = default_vinted_counter_state({"label": "ChoppeTaCarte"}, "2026")
        self.assertEqual(state["start_date"], "2026-01-01")

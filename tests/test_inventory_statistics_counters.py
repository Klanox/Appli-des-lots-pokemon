from datetime import datetime
import unittest

from services.inventory_ordering import card_matches_inventory_query, sort_inventory_records
from services.vinted_channels import sale_channel_key
from ui.pages.counters import collect_channel_counter_totals, default_vinted_counter_state
from ui.pages.statistics import MONTHLY_PROFILE_EXPLANATIONS, _comparable_month_metrics


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
        expected = {"🏆 Mois record", "🚀 Mois explosif", "🌱 Mois d'investissement", "📦 Mois de volume", "💎 Mois rentable", "🔥 Mois vendeur", "🌿 Mois calme", "📉 Mois en retrait", "⚖️ Mois équilibré", "🛒 Mois acheteur"}
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

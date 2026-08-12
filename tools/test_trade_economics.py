import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.trade_economics import (
    aggregate_contributors,
    allocate_received_cards,
    card_historical_unit_cost,
    compute_trade_summary,
    contributors_from_card,
    sale_allocation_for_trade_card,
    search_received_cards,
    trade_sale_stat_rows,
)
from utils import normalize_name


def assert_close(actual, expected, label, tolerance=0.01):
    if abs(float(actual) - float(expected)) > tolerance:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def test_cost_from_lot():
    lot = {"nom": "Lot A", "prix_achat": 60, "cards": [{"name": "A", "suggested_price": 100, "quantity": 1, "sold_entries": []}]}
    card = lot["cards"][0]
    assert_close(card_historical_unit_cost(lot, card), 60, "historical cost from lot")


def test_real_example_and_contributors():
    lot_a = {"nom": "Lot A", "prix_achat": 58, "cards": []}
    lot_b = {"nom": "Lot B", "prix_achat": 2, "cards": []}
    given = [
        {"reference_value": 30, "historical_cost": 16, "contributors": contributors_from_card(0, lot_a, {"suggested_price": 30}, 16)},
        {"reference_value": 85, "historical_cost": 42, "contributors": contributors_from_card(0, lot_a, {"suggested_price": 85}, 42)},
        {"reference_value": 3, "historical_cost": 2, "contributors": contributors_from_card(1, lot_b, {"suggested_price": 3}, 2)},
    ]
    contributors, before_cash, remaining = aggregate_contributors(given, cash_paid=0, cash_received=30)
    summary = compute_trade_summary(118, 101, cash_paid=0, cash_received=30, given_historical_cost=60)
    assert_close(summary["trade_economic_received_total"], 131, "economic received")
    assert_close(summary["trade_value_difference"], 13, "value difference")
    assert_close(summary["trade_acquisition_total_cost"], 30, "remaining trade cost")
    assert_close(before_cash, 60, "before cash")
    assert_close(remaining, 30, "remaining after cash")
    by_lot = {c.get("lot_name"): c for c in contributors if c.get("source_type") == "lot"}
    assert_close(by_lot["Lot A"]["ratio"], 58 / 60, "lot A ratio", tolerance=0.001)
    assert_close(by_lot["Lot B"]["ratio"], 2 / 60, "lot B ratio", tolerance=0.001)
    assert_close(by_lot["Lot A"]["remaining_cost"], 29, "lot A remaining")
    assert_close(by_lot["Lot B"]["remaining_cost"], 1, "lot B remaining")


def test_real_ui_case_cash_received_kpis():
    summary_without_cash = compute_trade_summary(113, 101, cash_paid=0, cash_received=0, given_historical_cost=60)
    summary_with_cash = compute_trade_summary(113, 101, cash_paid=0, cash_received=30, given_historical_cost=60)
    summary_cash_paid = compute_trade_summary(113, 101, cash_paid=30, cash_received=0, given_historical_cost=60)
    assert_close(summary_with_cash["trade_economic_given_total"], 113, "113/101/30 economic given")
    assert_close(summary_with_cash["trade_economic_received_total"], 131, "113/101/30 economic received")
    assert_close(summary_with_cash["trade_value_difference"], 18, "113/101/30 value difference")
    assert_close(summary_without_cash["trade_value_difference"], -12, "cash received 0 difference")
    assert_close(summary_cash_paid["trade_economic_given_total"], 143, "cash paid updates given side")
    assert_close(summary_cash_paid["trade_value_difference"], -42, "cash paid updates difference")


def test_cost_from_classic_lot_matches_exchange_cost_engine():
    lot = {
        "nom": "Lot classique",
        "prix_achat": 40,
        "cards": [
            {"name": "Carte A", "suggested_price": 30, "quantity": 1, "sold_entries": []},
            {"name": "Carte B", "suggested_price": 70, "quantity": 1, "sold_entries": []},
        ],
    }
    assert_close(card_historical_unit_cost(lot, lot["cards"][0]), 12, "classic lot card A cost")
    assert_close(card_historical_unit_cost(lot, lot["cards"][1]), 28, "classic lot card B cost")


def test_multi_lot_contributor_ratios_from_historical_costs():
    lot_a = {"nom": "Lot A", "prix_achat": 40, "cards": [{"name": "A", "suggested_price": 100, "quantity": 1, "sold_entries": []}]}
    lot_b = {"nom": "Lot B", "prix_achat": 10, "cards": [{"name": "B", "suggested_price": 100, "quantity": 1, "sold_entries": []}]}
    cost_a = card_historical_unit_cost(lot_a, lot_a["cards"][0])
    cost_b = card_historical_unit_cost(lot_b, lot_b["cards"][0])
    given = [
        {"historical_cost": cost_a, "contributors": contributors_from_card(0, lot_a, lot_a["cards"][0], cost_a)},
        {"historical_cost": cost_b, "contributors": contributors_from_card(1, lot_b, lot_b["cards"][0], cost_b)},
    ]
    contributors, before_cash, remaining = aggregate_contributors(given, cash_paid=0, cash_received=0)
    by_lot = {c.get("lot_name"): c for c in contributors}
    assert_close(before_cash, 50, "multi lot before cash")
    assert_close(remaining, 50, "multi lot remaining")
    assert_close(by_lot["Lot A"]["ratio"], 0.8, "Lot A 80 percent")
    assert_close(by_lot["Lot B"]["ratio"], 0.2, "Lot B 20 percent")
    assert_close(sum(c["ratio"] for c in contributors), 1.0, "ratio sum")


def test_cash_received_reduces_remaining_trade_cost():
    contributors, before_cash, remaining = aggregate_contributors(
        [{"historical_cost": 60, "contributors": [{"source_type": "lot", "lot_idx": 0, "lot_name": "Lot A", "historical_cost_contributed": 60, "remaining_cost": 60}]}],
        cash_paid=0,
        cash_received=30,
    )
    summary = compute_trade_summary(113, 101, cash_paid=0, cash_received=30, given_historical_cost=60)
    assert_close(before_cash, 60, "before cash received")
    assert_close(remaining, 30, "remaining after cash received")
    assert_close(summary["trade_acquisition_total_cost"], 30, "summary remaining after cash received")


def test_received_trade_image_fallback_html():
    import ui.pages.sales as sales_page

    sales_page.img_with_fallback = lambda url, url_en="", width="45px", style="": f'<img src="{url}" data-fallback="{url_en}" onerror="fallback">'
    html = sales_page._received_trade_image_html({"image_url": "https://assets.tcgdex.net/fr/sv/sv1/001/high.webp", "image_url_en": "https://assets.tcgdex.net/en/sv/sv1/001/high.webp"})
    assert "onerror" in html and "assets.tcgdex.net" in html, "image fallback should preserve source and fallback"
    placeholder = sales_page._received_trade_image_html({})
    assert "Image" in placeholder and "indispo" in placeholder, "missing image should render placeholder"


def test_received_allocation_and_trade_sale():
    contributors = [
        {"source_type": "lot", "lot_idx": 0, "lot_name": "Lot A", "remaining_cost": 29, "ratio": 58 / 60},
        {"source_type": "lot", "lot_idx": 1, "lot_name": "Lot B", "remaining_cost": 1, "ratio": 2 / 60},
    ]
    received = allocate_received_cards(
        [{"name": "A", "value": 60}, {"name": "B", "value": 30}, {"name": "C", "value": 11}],
        30,
        contributors,
    )
    assert_close(sum(c["trade_acquisition_total_cost"] for c in received), 30, "received total cost")
    card = {
        "received_by_exchange": True,
        "quantity": 1,
        "trade_acquisition_unit_cost": 12,
        "trade_contributors": contributors,
    }
    allocation = sale_allocation_for_trade_card(card, 50, 1)
    assert_close(allocation["cost"], 12, "trade sale cost")
    assert_close(allocation["profit"], 38, "trade sale profit")
    assert_close(sum(a["revenue"] for a in allocation["allocations"]), 50, "allocated revenue")
    assert_close(sum(a["profit"] for a in allocation["allocations"]), 38, "allocated profit")


def test_trade_sale_80_20_stats_allocation():
    card = {
        "name": "Carte Trade",
        "received_by_exchange": True,
        "quantity": 1,
        "trade_acquisition_unit_cost": 10,
        "trade_contributors": [
            {"source_type": "lot", "lot_idx": 0, "lot_name": "Lot A", "remaining_cost": 8, "ratio": 0.8},
            {"source_type": "lot", "lot_idx": 1, "lot_name": "Lot B", "remaining_cost": 2, "ratio": 0.2},
        ],
    }
    sale = {"quantity": 1, "price": 50, "date": "2026-01-01T12:00:00", "card_name": "Carte Trade"}
    allocation = sale_allocation_for_trade_card(card, 50, 1)
    assert_close(allocation["cost"], 10, "80/20 trade cost")
    assert_close(allocation["profit"], 40, "80/20 trade profit")
    rows = trade_sale_stat_rows(card, sale, "Trade")
    by_lot = {row["lot"]: row for row in rows}
    assert_close(by_lot["Lot A"]["price"], 40, "Lot A allocated CA")
    assert_close(by_lot["Lot A"]["benef"], 32, "Lot A allocated profit")
    assert_close(by_lot["Lot B"]["price"], 10, "Lot B allocated CA")
    assert_close(by_lot["Lot B"]["benef"], 8, "Lot B allocated profit")
    assert_close(sum(row["price"] for row in rows), 50, "allocated CA sum")
    assert_close(sum(row["benef"] for row in rows), 40, "allocated profit sum")
    stats_global_ca = sum(row["price"] for row in rows)
    stats_global_profit = sum(row["benef"] for row in rows)
    assert_close(stats_global_ca, 50, "no global CA double count")
    assert_close(stats_global_profit, 40, "no global profit double count")


def test_trade_sale_single_contributor_stats_allocation():
    card = {
        "name": "Carte Trade",
        "received_by_exchange": True,
        "quantity": 1,
        "trade_acquisition_unit_cost": 10,
        "trade_contributors": [
            {"source_type": "lot", "lot_idx": 0, "lot_name": "Lot A", "remaining_cost": 10, "ratio": 1.0},
        ],
    }
    sale = {"quantity": 1, "price": 50, "date": "2026-01-01T12:00:00", "card_name": "Carte Trade"}
    rows = trade_sale_stat_rows(card, sale, "Trade")
    assert_close(len(rows), 1, "single contributor row count", tolerance=0)
    assert_close(rows[0]["price"], 50, "single contributor CA")
    assert_close(rows[0]["benef"], 40, "single contributor profit")


def test_cash_over_cost_and_trade_generation():
    contributors, _, remaining = aggregate_contributors(
        [{"historical_cost": 20, "contributors": [{"source_type": "lot", "lot_idx": 0, "lot_name": "Lot A", "remaining_cost": 20}]}],
        cash_paid=0,
        cash_received=30,
    )
    assert_close(remaining, 0, "cash over cost floor")
    trade_card = {
        "suggested_price": 20,
        "received_by_exchange": True,
        "trade_acquisition_unit_cost": 20,
        "trade_contributors": [
            {"source_type": "lot", "lot_idx": 0, "lot_name": "Lot A", "remaining_cost": 15, "ratio": 0.75},
            {"source_type": "lot", "lot_idx": 1, "lot_name": "Lot B", "remaining_cost": 5, "ratio": 0.25},
        ],
    }
    inherited = contributors_from_card(9, {"nom": "Trade"}, trade_card, 20)
    assert_close(sum(c["remaining_cost"] for c in inherited), 20, "inherited trade cost")
    assert_close(inherited[0]["remaining_cost"], 15, "inherited lot A")
    assert_close(inherited[1]["remaining_cost"], 5, "inherited lot B")


def test_search_received_cards():
    cards_index = {
        normalize_name("Pikachu"): [({"id": "base1-58", "name": "Pikachu", "localId": "058"}, "Base", "base1")],
        normalize_name("Dracaufeu"): [({"id": "base1-4", "name": "Dracaufeu", "localId": "004"}, "Base", "base1")],
        normalize_name("Mew"): [({"id": "promo-104", "name": "Mew", "localId": "104"}, "Promo", "promo")],
        normalize_name("Feunnec"): [({"id": "xy-10", "name": "Feunnec", "localId": "010"}, "XY", "xy")],
        normalize_name("Zygarde"): [({"id": "xy-99", "name": "Zygarde", "localId": "099"}, "XY", "xy")],
    }
    for query in ("Pikachu", "Dracaufeu", "Mew", "Feunnec", "Zygarde", "pika", "104"):
        assert search_received_cards(query, cards_index, normalize_name), f"no result for {query}"


def main():
    test_cost_from_lot()
    test_real_example_and_contributors()
    test_real_ui_case_cash_received_kpis()
    test_cost_from_classic_lot_matches_exchange_cost_engine()
    test_multi_lot_contributor_ratios_from_historical_costs()
    test_cash_received_reduces_remaining_trade_cost()
    test_received_allocation_and_trade_sale()
    test_trade_sale_80_20_stats_allocation()
    test_trade_sale_single_contributor_stats_allocation()
    test_cash_over_cost_and_trade_generation()
    test_search_received_cards()
    test_received_trade_image_fallback_html()
    print("RESULT: OK")


if __name__ == "__main__":
    main()

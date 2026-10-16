"""Tests de la refonte Statistiques (Mensuel / Performance / Prévisions).

Aucune donnée réelle : tout est calculé sur des jeux temporaires.
"""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

import streamlit
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import ButtonGroup

from logic import calc_cout_lot, effective_purchase_price
from ui.pages import statistics as stats


def _group_indices(group):
    """Compatibilité du simulateur AppTest de Streamlit 1.54 avec st.segmented_control (valeur simple)."""
    values = group.value
    values = [values] if isinstance(values, str) else (values or [])
    contents = [getattr(option, "content", option) for option in group.options]
    return [contents.index(value) for value in values]


def _option_labels(group):
    return [str(getattr(option, "content", option)) for option in group.options]


_OLD_SIMULATOR = tuple(int(part) for part in streamlit.__version__.split(".")[:2]) < (1, 60)
if _OLD_SIMULATOR:
    ButtonGroup.indices = property(_group_indices)


def _m(ca, benef=None, qty=1):
    return {"ca": float(ca), "benef": float(ca if benef is None else benef), "qty": float(qty), "benef_known": True, "transactions": set(), "purchases": 0.0}


class RollingAverageTests(unittest.TestCase):
    NOW = datetime(2026, 10, 13, 12, 0)

    def test_missing_months_count_as_zero_and_current_month_is_excluded(self):
        data = {
            "2026-02": {"ca": 0.0, "benef": 0.0, "qty": 0.0, "purchases": 80.0},  # achat seul : ne démarre pas l'historique
            "2026-03": _m(100, 50), "2026-04": _m(200, 100), "2026-06": _m(300, 150), "2026-09": _m(400, 200),
            "2026-10": _m(999, 999),  # mois en cours
        }
        h = stats._rolling_average_history(data, self.NOW)
        self.assertEqual(h["months"], ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"])
        self.assertEqual(h["ca_values"], [100, 200, 0, 300, 0, 0, 400])
        self.assertEqual(h["window_sizes"], [1, 2, 3, 4, 5, 6, 7])  # moins de 12 mois : fenêtre = mois disponibles
        self.assertAlmostEqual(h["ca_avg"][-1], 1000 / 7)
        self.assertAlmostEqual(h["benef_avg"][-1], 500 / 7)
        self.assertAlmostEqual(h["ca_avg"][1], 150)
        self.assertNotIn("2026-10", h["months"])
        self.assertEqual(h["excluded_month"], "2026-10")

    def test_window_is_capped_at_twelve_months(self):
        data = {}
        for idx in range(14):  # 2025-03 .. 2026-04
            year, month = divmod(2025 * 12 + 2 + idx, 12)
            data[f"{year}-{month + 1:02}"] = _m(100 * (idx + 1))
        now = datetime(2026, 5, 20)
        h = stats._rolling_average_history(data, now)
        self.assertEqual(len(h["months"]), 14)
        self.assertEqual(h["window_sizes"][-1], 12)
        self.assertEqual(h["window_sizes"][11], 12)
        self.assertEqual(h["window_sizes"][10], 11)
        # 12 derniers mois = valeurs 3..14 -> moyenne (3+...+14)/12 * 100
        self.assertAlmostEqual(h["ca_avg"][-1], sum(range(3, 15)) / 12 * 100)

    def test_no_complete_month_gives_empty_history(self):
        h = stats._rolling_average_history({"2026-10": _m(50)}, self.NOW)
        self.assertEqual(h["months"], [])
        self.assertEqual(stats._rolling_average_history({}, self.NOW)["months"], [])

    def test_january_uses_december_of_previous_year_as_last_complete_month(self):
        data = {"2025-11": _m(100), "2025-12": _m(200), "2026-01": _m(50)}
        h = stats._rolling_average_history(data, datetime(2026, 1, 15))
        self.assertEqual(h["months"], ["2025-11", "2025-12"])


class YearProjectionTests(unittest.TestCase):
    NOW = datetime(2026, 10, 13)

    def test_projection_uses_complete_month_average_and_remaining_months(self):
        data = {"2026-03": _m(100, 50, 10), "2026-04": _m(200, 100, 20), "2026-06": _m(300, 150, 30), "2026-09": _m(400, 200, 40), "2026-10": _m(60, 30, 6)}
        p = stats._year_projection(data, 2026, self.NOW)
        self.assertEqual(p["status"], "projection")
        self.assertEqual(p["complete_months"], 7)  # mars..septembre, mois vides compris
        self.assertEqual(p["remaining_months"], 2)
        self.assertAlmostEqual(p["to_date"]["ca"], 1060)
        self.assertAlmostEqual(p["avg"]["ca"], 1000 / 7)
        self.assertAlmostEqual(p["projected"]["ca"], 1060 + 1000 / 7 * 2)
        self.assertAlmostEqual(p["projected"]["benef"], 530 + 500 / 7 * 2)
        self.assertAlmostEqual(p["projected"]["qty"], 106 + 100 / 7 * 2)
        self.assertFalse(p["indicative"])

    def test_few_months_is_flagged_as_indicative(self):
        data = {"2026-08": _m(100), "2026-09": _m(300)}
        p = stats._year_projection(data, 2026, self.NOW)
        self.assertEqual(p["complete_months"], 2)
        self.assertTrue(p["indicative"])
        self.assertAlmostEqual(p["projected"]["ca"], 400 + 200 * 2)

    def test_no_complete_month_keeps_total_to_date(self):
        p = stats._year_projection({"2026-10": _m(80)}, 2026, self.NOW)
        self.assertEqual(p["complete_months"], 0)
        self.assertAlmostEqual(p["projected"]["ca"], 80)

    def test_first_year_sales_before_january_start_the_year_in_january(self):
        data = {"2025-12": _m(500), "2026-01": _m(100), "2026-03": _m(200)}
        p = stats._year_projection(data, 2026, datetime(2026, 4, 5))
        self.assertEqual(p["complete_months"], 3)  # janvier, février (0), mars
        self.assertAlmostEqual(p["avg"]["ca"], 100)
        self.assertEqual(p["remaining_months"], 8)

    def test_past_year_is_complete_and_future_year_is_none(self):
        p = stats._year_projection({"2025-05": _m(10), "2025-06": _m(20), "2026-01": _m(5)}, 2025, self.NOW)
        self.assertEqual(p["status"], "complete")
        self.assertAlmostEqual(p["projected"]["ca"], 30)
        self.assertIsNone(stats._year_projection({}, 2027, self.NOW))


class GoalsStorageTests(unittest.TestCase):
    def _write(self, path, payload):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_new_keys_are_added_without_touching_existing_months(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "monthly_goals.json")
            original = {"2026-09": {"ca_target": 700.0, "qty_target": 50, "benef_target": 350.0, "auto_generated": False}}
            self._write(path, original)
            writes = []

            def fake_write(target, data, indent=None):
                writes.append((target, json.loads(json.dumps(data))))

            ok = stats._save_goal_updates(path, fake_write, annual=(2026, {"ca_target": 9000.0, "benef_target": 4000.0, "qty_target": 500}), long_term=1800)
            self.assertTrue(ok)
            (target, data), = writes
            self.assertEqual(target, path)
            self.assertEqual(data["2026-09"], original["2026-09"])
            self.assertEqual(data[stats.ANNUAL_GOALS_KEY]["2026"], {"ca_target": 9000.0, "benef_target": 4000.0, "qty_target": 500})
            self.assertEqual(data[stats.LONG_TERM_GOAL_KEY], {"monthly_benef_target": 1800.0})
            with open(path, encoding="utf-8") as handle:  # le test n'écrit pas lui-même : fake_write seul décide
                self.assertEqual(json.load(handle), original)

    def test_second_year_does_not_replace_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "monthly_goals.json")
            self._write(path, {"annual_goals": {"2026": {"ca_target": 1.0, "benef_target": 2.0, "qty_target": 3}}})
            captured = {}
            stats._save_goal_updates(path, lambda p, d, indent=None: captured.update(d), annual=(2027, {"ca_target": 5.0, "benef_target": 6.0, "qty_target": 7}))
            self.assertEqual(set(captured["annual_goals"]), {"2026", "2027"})

    def test_unreadable_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "monthly_goals.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{pas du json")
            calls = []
            self.assertFalse(stats._save_goal_updates(path, lambda *a, **k: calls.append(a), long_term=1500))
            self.assertEqual(calls, [])

    def test_missing_file_and_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "absent.json")
            data, ok = stats._read_goals_file(path)
            self.assertEqual((data, ok), ({}, True))
            self.assertEqual(stats._long_term_target(data), 1500.0)
            self.assertIsNone(stats._annual_goal_for_year(data, 2026))
            captured = {}
            self.assertTrue(stats._save_goal_updates(path, lambda p, d, indent=None: captured.update(d), long_term=2000))
            self.assertEqual(captured, {"long_term_goal": {"monthly_benef_target": 2000.0}})

    def test_month_goal_reader_ignores_new_keys(self):
        goals = {"2026-10": {"ca_target": 500.0, "qty_target": 50, "benef_target": 250.0, "auto_generated": False},
                 "annual_goals": {"2026": {"ca_target": 1, "benef_target": 1, "qty_target": 1}}, "long_term_goal": {"monthly_benef_target": 1500}}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "monthly_goals.json")
            self._write(path, goals)
            written = []
            data, current = stats._load_month_goals(path, "2026-10", "2026-09", {}, [], lambda *a, **k: written.append(a))
            self.assertEqual(current["ca_target"], 500.0)
            self.assertEqual(written, [])  # mois déjà présent : rien n'est réécrit
            self.assertIn("annual_goals", data)


class LongTermHelpersTests(unittest.TestCase):
    def test_status_levels(self):
        self.assertEqual(stats._long_term_status(1500, 1500)[0], "Objectif atteint")
        self.assertEqual(stats._long_term_status(1200, 1500)[0], "Presque atteint")
        self.assertEqual(stats._long_term_status(800, 1500)[0], "En bonne progression")
        self.assertEqual(stats._long_term_status(100, 1500)[0], "Encore loin de l'objectif")
        self.assertAlmostEqual(stats._long_term_status(750, 1500)[3], 50.0)

    def test_goal_chart_projection_stops_at_zero_with_a_label(self):
        data = {"2026-03": _m(100, 900), "2026-04": _m(100, 600), "2026-05": _m(100, 300), "2026-06": _m(100, 0)}
        now = datetime(2026, 7, 10)
        history = stats._rolling_average_history(data, now)
        trend = stats._current_trend_per_month(history["benef_avg"])
        self.assertLess(trend, 0)
        deadline = date(2028, 12, 31)
        months_left = stats._months_remaining(now, deadline)
        anchor = history["benef_avg"][-1]
        self.assertLess(anchor + trend * months_left, 0)  # sans plancher la projection passerait sous zéro
        fig = stats._build_goal_chart(history, 1500.0, trend, deadline, now, months_left)
        projection = next(t for t in fig.data if t.name == "Si la tendance actuelle continue")
        self.assertEqual(list(projection.y), [anchor, 0.0])
        self.assertLess(projection.x[1], datetime(2028, 12, 31))
        self.assertEqual(len(fig.layout.annotations), 1)
        self.assertTrue(fig.layout.annotations[0].text.startswith("0 € vers "))
        self.assertGreaterEqual(min(min(t.y) for t in fig.data if t.y[0] is not None and t.name != "Aujourd'hui"), 0.0 - 1e-9)
        self.assertIn("Si la tendance actuelle continue", [t.name for t in fig.data])  # légende complète

    def test_goal_chart_projection_without_zero_crossing_has_no_label(self):
        data = {"2026-03": _m(100, 400), "2026-04": _m(100, 600), "2026-05": _m(100, 800)}
        now = datetime(2026, 6, 10)
        history = stats._rolling_average_history(data, now)
        trend = stats._current_trend_per_month(history["benef_avg"])
        deadline = date(2027, 6, 30)
        fig = stats._build_goal_chart(history, 1500.0, trend, deadline, now, stats._months_remaining(now, deadline))
        self.assertEqual(len(fig.layout.annotations), 0)

    def test_goal_chart_has_all_required_lines(self):
        data = {"2026-03": _m(100, 400), "2026-04": _m(300, 600), "2026-05": _m(300, 800)}
        history = stats._rolling_average_history(data, datetime(2026, 6, 10))
        avg = history["benef_avg"][-1]
        trend = stats._current_trend_per_month(history["benef_avg"])
        deadline = date(2027, 6, 30)
        months_left = stats._months_remaining(datetime(2026, 6, 10), deadline)
        fig = stats._build_goal_chart(history, 1500.0, trend, deadline, datetime(2026, 6, 10), months_left)
        names = [trace.name for trace in fig.data]
        self.assertEqual(names[1:5], ["Objectif (1\u00a0500\u00a0€)", "Trajectoire requise", "Si la tendance actuelle continue", "Aujourd'hui"])
        self.assertEqual(names[5:], ["Mois estimés* (historique réparti)"])  # mars 2026 fait partie de l'historique réparti
        self.assertTrue(names[0].startswith("Moyenne glissante"))
        self.assertEqual(list(fig.data[1].y), [1500.0, 1500.0])  # ligne d'objectif horizontale
        self.assertEqual(list(fig.data[2].y), [avg, 1500.0])  # trajectoire requise : du point actuel à l'objectif
        self.assertAlmostEqual(fig.data[3].y[1], avg + trend * months_left)  # projection si la tendance continue
        self.assertEqual(fig.data[4].x[0], datetime(2026, 6, 10))  # repère « Aujourd'hui »


class LongTermPlanTests(unittest.TestCase):
    NOW = datetime(2026, 10, 13, 12, 0)

    def test_deadline_defaults_to_end_of_2028_and_ignores_invalid_values(self):
        self.assertEqual(stats._long_term_deadline({}), date(2028, 12, 31))
        self.assertEqual(stats._long_term_deadline({"long_term_goal": {"monthly_benef_target": 1500}}), date(2028, 12, 31))  # clé absente
        self.assertEqual(stats._long_term_deadline({"long_term_goal": {"deadline": "2027-06-30"}}), date(2027, 6, 30))
        self.assertEqual(stats._long_term_deadline({"long_term_goal": {"deadline": "pas une date"}}), date(2028, 12, 31))
        self.assertEqual(stats._long_term_deadline({"long_term_goal": "n'importe quoi"}), date(2028, 12, 31))

    def test_months_remaining(self):
        self.assertEqual(stats._months_remaining(self.NOW, date(2028, 12, 31)), 27)
        self.assertEqual(stats._months_remaining(self.NOW, date(2026, 11, 13)), 1)
        self.assertEqual(stats._months_remaining(self.NOW, date(2026, 1, 1)), 0)  # date passée : jamais négatif

    def test_required_trajectory(self):
        traj = stats._required_trajectory(701.0, 1500.0, 27)
        self.assertAlmostEqual(traj["needed_per_month"], (1500 - 701) / 27)
        self.assertFalse(traj["reached"])
        self.assertEqual(stats._required_trajectory(1600.0, 1500.0, 27)["needed_per_month"], 0.0)
        self.assertTrue(stats._required_trajectory(1600.0, 1500.0, 27)["reached"])
        self.assertIsNone(stats._required_trajectory(500.0, 1500.0, 0)["needed_per_month"])  # plus de mois restant

    def test_trend_uses_last_months_of_the_rolling_average(self):
        self.assertAlmostEqual(stats._current_trend_per_month([100, 200, 300, 500]), (500 - 100) / 3)
        self.assertAlmostEqual(stats._current_trend_per_month([100, 300]), 200.0)  # historique court
        self.assertEqual(stats._current_trend_per_month([100]), 0.0)
        self.assertEqual(stats._current_trend_per_month([]), 0.0)

    def test_pace_status_rule(self):
        # progression nécessaire : (1500 - 500) / 10 = 100 € par mois
        self.assertEqual(stats._pace_status(500, 1500, 100, 10), ("Sur la bonne voie", "good"))
        self.assertEqual(stats._pace_status(500, 1500, 60, 10), ("À accélérer", "warn"))
        self.assertEqual(stats._pace_status(500, 1500, 50, 10), ("À accélérer", "warn"))
        self.assertEqual(stats._pace_status(500, 1500, 40, 10), ("En retard", "bad"))
        self.assertEqual(stats._pace_status(500, 1500, -20, 10), ("En retard", "bad"))
        self.assertEqual(stats._pace_status(1600, 1500, -50, 10), ("Sur la bonne voie", "good"))  # objectif atteint
        self.assertEqual(stats._pace_status(500, 1500, 500, 0), ("En retard", "bad"))  # date limite dépassée

    def test_milestones_reached_month_and_estimated_month(self):
        benef = [300, 900, 1500, 600, 600, 600, 600, 600]  # janvier à août ; moyennes 300, 600, 900, 825, 780, 750, ...
        data = {f"2026-{i + 1:02d}": _m(100, value) for i, value in enumerate(benef)}
        now = datetime(2026, 9, 10)
        history = stats._rolling_average_history(data, now)
        avg_now = sum(benef) / 8
        self.assertAlmostEqual(history["benef_avg"][-1], avg_now)
        cards = stats._milestone_status(history, 50.0, now)
        by_value = {int(card["value"]): card for card in cards}
        # 500 € dépassé dès février (moyenne 600) mais sur 2 mois seulement : atteint au 1er mois où la fenêtre compte 6 mois
        self.assertTrue(by_value[500]["reached"])
        self.assertEqual(by_value[500]["reached_month"], "2026-06")
        self.assertFalse(by_value[1000]["reached"])
        self.assertAlmostEqual(by_value[1000]["remaining"], 1000 - avg_now)
        steps = int(-(-(1000 - avg_now) // 50))
        self.assertEqual(by_value[1000]["target_month"], stats._add_months(datetime(2026, 9, 1), steps - 1).strftime("%Y-%m"))
        self.assertEqual([c["is_next"] for c in cards], [False, True, False, False, False])  # un seul palier « prochain »
        self.assertAlmostEqual(by_value[1000]["progress"], avg_now / 10)
        # sans progression requise (objectif atteint ou date dépassée) : pas de date estimée
        self.assertTrue(all(card["target_month"] is None for card in stats._milestone_status(history, 0.0, now)))
        self.assertTrue(all(card["target_month"] is None for card in stats._milestone_status(history, None, now)))

    def test_milestone_is_not_reached_on_a_window_shorter_than_the_minimum(self):
        data = {"2026-03": _m(100, 300), "2026-04": _m(100, 900), "2026-05": _m(100, 1500)}  # moyennes 300, 600, 900 sur 1 à 3 mois
        now = datetime(2026, 6, 10)
        history = stats._rolling_average_history(data, now)
        self.assertLess(stats.PROJECTION_MIN_MONTHS, 7)
        self.assertEqual(history["window_sizes"], [1, 2, 3])
        cards = {int(card["value"]): card for card in stats._milestone_status(history, 50.0, now)}
        self.assertFalse(cards[500]["reached"])  # moyenne 900 >= 500 mais sur 3 mois seulement
        self.assertIsNone(cards[500]["reached_month"])
        self.assertTrue(cards[500]["provisional"])
        self.assertFalse(cards[1000]["provisional"])
        self.assertAlmostEqual(cards[1000]["progress"], 90.0)  # progression normale
        html_text = stats._milestones_html(list(cards.values()), None)
        self.assertNotIn("Atteint", html_text)
        self.assertIn("À confirmer", html_text)

    def test_milestones_without_history(self):
        cards = stats._milestone_status(stats._rolling_average_history({}, self.NOW), 10.0, self.NOW)
        self.assertEqual(len(cards), 5)
        self.assertFalse(any(card["reached"] for card in cards))

    def test_consecutive_months_above_monthly_goal(self):
        stat = {"2026-03": _m(0, 100), "2026-04": _m(0, 300), "2026-05": _m(0, 300), "2026-06": _m(0, 100), "2026-07": _m(0, 300), "2026-08": _m(0, 999)}
        goals = {m: {"benef_target": 250.0} for m in ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08")}  # pas d'objectif en mars
        self.assertEqual(stats._consecutive_months_above_goal(stat, goals, datetime(2026, 8, 10)), (1, 2))  # août (mois en cours) exclu
        self.assertEqual(stats._consecutive_months_above_goal(stat, goals, datetime(2026, 9, 10)), (2, 2))  # août compte une fois terminé
        self.assertEqual(stats._consecutive_months_above_goal(stat, {}, datetime(2026, 9, 10)), (0, 0))
        self.assertEqual(stats._consecutive_months_above_goal({}, goals, datetime(2026, 9, 10)), (0, 0))

    def test_cumulative_benefit(self):
        self.assertAlmostEqual(stats._cumulative_benefit({"a": _m(10, 4), "b": _m(5, -1)}), 3.0)


class DesignHelpersTests(unittest.TestCase):
    def test_euro_format_uses_non_breaking_spaces_and_no_decimals(self):
        self.assertEqual(stats._fmt_eur0(8966.47), "8\u00a0966\u00a0€")
        self.assertEqual(stats._fmt_eur0(-2615.6), "-2\u00a0616\u00a0€")
        self.assertEqual(stats._fmt_eur0(30.4, signed=True), "+30\u00a0€")
        self.assertEqual(stats._fmt_eur0(None), "N/A")
        self.assertEqual(stats._fmt_eur_smart(9.96), "9,96\u00a0€")
        self.assertEqual(stats._fmt_eur_smart(250.0), "250\u00a0€")
        self.assertEqual(stats._fmt_pct0(55.5), "56\u00a0%")

    def test_small_channels_are_grouped_in_others(self):
        rows = [{"canal": "Vinted", "price": 600.0}, {"canal": "Main propre", "price": 300.0}, {"canal": "Dexify", "price": 40.0}, {"canal": "Brocante", "price": 30.0}, {"canal": "Vinted", "price": 30.0}]
        shares = stats._channel_shares(rows)
        names = [item["channel"] for item in shares]
        self.assertEqual(names, ["Vinted", "Main propre", "Autres"])
        self.assertAlmostEqual(sum(item["pct"] for item in shares), 100.0)
        self.assertAlmostEqual(shares[-1]["ca"], 70.0)
        self.assertEqual(stats._channel_shares([]), [])

    def test_lot_summary_best_lots_and_lots_to_reimburse(self):
        def row(lot, price, benef):
            return {"lot": lot, "price": price, "quantity": 1, "benef": benef, "is_system_lot": False, "is_off_stock": False}
        rows = [row("A", 120.0, 40.0), row("B", 20.0, 5.0), row("C", 10.0, -10.0), row("D", 15.0, 3.0)]
        costs = {"A": 100.0, "B": 50.0, "C": 80.0}  # D : coût inconnu, ignoré pour le remboursement
        summary = stats._lot_summary(rows, rows, costs)
        self.assertEqual([r["lot"] for r in summary["best"]], ["A", "B", "D"])
        self.assertEqual(summary["total_with_cost"], 3)
        self.assertEqual(summary["pending_count"], 2)
        self.assertEqual(summary["pending"][0]["lot"], "C")
        self.assertAlmostEqual(summary["pending"][0]["reste"], 70.0)
        self.assertAlmostEqual(summary["reimbursed_pct"], 100 / 3)

    def test_lot_summary_counts_sales_of_other_years_for_reimbursement(self):
        year_rows = [{"lot": "A", "price": 30.0, "quantity": 1, "benef": 10.0, "is_system_lot": False, "is_off_stock": False}]
        lifetime = year_rows + [{"lot": "A", "price": 90.0, "quantity": 1, "benef": 50.0, "is_system_lot": False, "is_off_stock": False}]
        summary = stats._lot_summary(year_rows, lifetime, {"A": 100.0})
        self.assertEqual(summary["pending_count"], 0)  # 30 + 90 >= 100 : remboursé
        self.assertEqual(summary["reimbursed_pct"], 100.0)

    def test_year_chart_has_smoothed_curves_and_complete_legend(self):
        fig = stats._build_year_chart(["2026-04", "2026-05", "2026-06"], [100.0, 300.0, 200.0], [40.0, 120.0, 90.0])
        self.assertEqual([t.name for t in fig.data], ["Chiffre d'affaires", "Bénéfice réalisé"])
        self.assertEqual(fig.data[0].line.shape, "spline")
        self.assertEqual(fig.data[0].fill, "tozeroy")
        self.assertEqual(fig.data[0].fillcolor, "rgba(124,58,237,.15)")
        self.assertEqual(fig.layout.legend.orientation, "h")
        self.assertEqual(stats._chart_month_labels(["2026-11", "2026-12", "2027-01", "2027-02"]), ["Nov. 26", "Déc.", "Janv. 27", "Févr."])


class LotSaleInclusionTests(unittest.TestCase):
    """Les ventes initiales (« Vente initiale », is_lot_sale : cartes vendues avant l'enregistrement du lot) comptent dans les Statistiques."""

    @staticmethod
    def _card(price_sold=10.0):
        return {"name": "Carte test", "quantity": 2, "suggested_price": 10.0,
                "sold_entries": [{"date": "2026-04-05T10:00:00", "price": price_sold, "quantity": 1,
                                  "suggested_price_at_sale": 10.0, "canal": "Vinted"}]}

    def _collect(self, lots, archives=None, calc=calc_cout_lot):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lots_archives.json")
            if archives is not None:
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(archives, handle)
            return stats._collect_statistics_data({"lots": lots}, calc_cout_lot_func=calc,
                                                  effective_purchase_price_func=effective_purchase_price,
                                                  lots_archives_path=path)

    @staticmethod
    def _lot_sale(price=50.0, date="2026-03-16T19:00:00"):
        return {"date": date, "price": price, "card_name": "Vente initiale", "is_lot_sale": True}

    def test_lot_sale_is_included_without_double_counting_card_sales(self):
        lot = {"nom": "Lot A", "prix_achat": 100.0, "cards": [self._card()],
               "ventes": [self._lot_sale(50.0), {"date": "2026-05-11T10:00:00", "price": 3.0, "is_exchange_benefit": True}]}
        rows, _ = self._collect([lot])
        self.assertEqual(len(rows), 2)  # 1 vente initiale + 1 vente de carte ; le bénéfice d'échange reste exclu
        by_kind = {bool(r.get("is_lot_sale")): r for r in rows}
        # valeur du lot = stock 10 + carte vendue 10 + vente initiale 50 = 70
        self.assertAlmostEqual(by_kind[True]["cost"], 50 / 70 * 100)
        self.assertAlmostEqual(by_kind[False]["cost"], 10 / 70 * 100)
        self.assertAlmostEqual(by_kind[True]["benef"], 50 - 50 / 70 * 100)
        self.assertLessEqual(sum(r["cost"] for r in rows), 100.0 + 1e-9)  # jamais plus que le prix d'achat
        monthly = stats._build_monthly_stats(rows, [])
        self.assertAlmostEqual(monthly["2026-03"]["ca"], 50.0)
        self.assertAlmostEqual(monthly["2026-04"]["ca"], 10.0)

    def test_lot_without_card_sales_is_counted_once_in_current_and_archived_lots(self):
        current = {"nom": "Lot courant", "prix_achat": 40.0, "cards": [], "ventes": [self._lot_sale(60.0)]}
        archived = {"nom": "Lot archivé", "prix_achat": 210.0, "cards": [], "ventes": [self._lot_sale(357.0)]}
        rows, _ = self._collect([current], archives=[archived])
        self.assertEqual(sorted(r["price"] for r in rows), [60.0, 357.0])
        by_lot = {r["lot"]: r for r in rows}
        self.assertAlmostEqual(by_lot["Lot courant"]["cost"], 40.0)  # seule vente = tout le coût
        self.assertAlmostEqual(by_lot["Lot archivé"]["cost"], 210.0)

    def test_lot_sale_counts_in_revenue_but_not_in_cards_sold_or_best_card(self):
        lot = {"nom": "Lot A", "prix_achat": 100.0, "cards": [self._card(12.0)], "ventes": [self._lot_sale(50.0)]}
        rows, _ = self._collect([lot])
        lot_row = next(r for r in rows if r.get("is_lot_sale"))
        self.assertEqual(lot_row["quantity"], 0.0)
        agg = stats._aggregate_sales(rows)
        self.assertAlmostEqual(agg["ca"], 62.0)
        self.assertEqual(agg["qty"], 1.0)  # seule la vraie carte est comptée
        self.assertAlmostEqual(agg["avg_card"], 12.0)  # prix par carte non faussé par la vente initiale
        self.assertEqual(agg["transactions"], 1)  # la vente initiale n'est pas une transaction
        self.assertAlmostEqual(agg["basket"], 12.0)  # panier moyen : ventes initiales exclues (12 € / 1 transaction)
        best = stats._best_card_of_month(rows)
        self.assertAlmostEqual(best["price"], 12.0)
        self.assertNotEqual(best["name"], "Vente initiale")

    def test_mixte_lot_uses_existing_mixte_cost_formula(self):
        lot = {"nom": "Lot mixte", "is_mixte": True, "valeur_totale": 200.0, "prix_achat": 150.0,
               "prix_achat_reel": 100.0, "cards": [], "ventes": [self._lot_sale(50.0)]}
        rows, _ = self._collect([lot])
        self.assertAlmostEqual(rows[0]["cost"], 50 / 200 * 100)

    def test_failed_cost_calculation_gives_unknown_cost_not_absurd_cost(self):
        def broken(lot, lot_idx=None):
            raise RuntimeError("boom")
        lot = {"nom": "Lot A", "prix_achat": 100.0, "cards": [], "ventes": [self._lot_sale(50.0)]}
        rows, _ = self._collect([lot], calc=broken)
        self.assertIsNone(rows[0]["cost"])
        self.assertIsNone(rows[0]["benef"])
        self.assertFalse(stats._build_monthly_stats(rows, [])["2026-03"]["benef_known"])

    def test_lot_sale_counts_toward_lot_reimbursement(self):
        lot = {"nom": "Lot A", "prix_achat": 100.0, "cards": [], "ventes": [self._lot_sale(120.0)]}
        rows, _ = self._collect([lot])
        item = stats._lot_rows_for(rows, stats._lot_cost_map([lot]))["Lot A"]
        self.assertAlmostEqual(item["ca"], 120.0)
        self.assertAlmostEqual(item["benef"], 20.0)
        self.assertEqual(max(0.0, item["cost"] - item["ca"]), 0.0)  # lot remboursé : plus « non remboursé »


VIEW_SCRIPT = '''
import json, os
from datetime import datetime
import streamlit as st
from ui.pages.statistics import render_statistics_page

root = st.session_state["_tmp_root"]
goals_path = os.path.join(root, "monthly_goals.json")
archives_path = os.path.join(root, "lots_archives.json")

def shift(d, k):
    idx = d.year * 12 + d.month - 1 + k
    return d.replace(year=idx // 12, month=idx % 12 + 1, day=1)

now = datetime.now()
lots = []
for k in range(19, -1, -1):
    if k in (14, 6):
        continue  # mois sans vente
    d = shift(now, -k)
    lots.append({"nom": "Lot %d" % k, "prix_achat_reel": 40.0 + (k % 3) * 30, "date_achat": d.isoformat(), "cards": [],
                 "ventes": [{"date": d.isoformat(), "price": 30.0 + k, "quantity": 2, "canal": "Vinted" if k % 2 else "Main propre", "card_name": "Carte %d" % k}]})
if not os.path.exists(archives_path):
    with open(archives_path, "w", encoding="utf-8") as handle:
        json.dump([], handle)

def safe_write(path, data, indent=None):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)

render_statistics_page(
    ld_func=lambda: {"lots": lots},
    safe_write_json_func=safe_write,
    calc_cout_lot_func=lambda lot, lot_idx=None: ([], 100.0),
    effective_purchase_price_func=lambda lot: lot["prix_achat_reel"],
    proxy_img_func=lambda url: url,
    lots_archives_path=archives_path,
    monthly_goals_path=goals_path,
    stock_history_path=os.path.join(root, "stock_value_history.json"),
)
'''

NEW_FIRST_YEAR_SCRIPT = VIEW_SCRIPT.replace("for k in range(19, -1, -1):", "for k in range(3, -1, -1):")


def _texts(at):
    return " ".join(str(element.value) for element in at.markdown)


class StatisticsViewsAppTests(unittest.TestCase):
    def _run(self, view, script=VIEW_SCRIPT, root=None):
        at = AppTest.from_string(script, default_timeout=60)
        at.session_state["_tmp_root"] = root
        at.session_state[stats.STATS_VIEW_STATE_KEY] = view
        at.run()
        return at

    def test_each_view_renders_without_exception_and_only_computes_its_own_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            expectations = {
                "Mensuel": ("Bilan mensuel", "Objectifs", "Tes records"),
                "Performance": ("CA et bénéfice par mois", "Lots les plus rentables", "Canaux de vente"),
                "Prévisions": ("Objectif PokéStock", "avant 31/12/2028", "Moyenne actuelle", "Paliers de bénéfice moyen par mois", "estimée"),
            }
            for view, expected in expectations.items():
                with patch.object(stats, "build_profile_stats", wraps=stats.build_profile_stats) as profile_calls, \
                        patch.object(stats, "_year_projection", wraps=stats._year_projection) as projection_calls, \
                        patch.object(stats, "_rolling_average_history", wraps=stats._rolling_average_history) as rolling_calls:
                    at = self._run(view, root=tmp)
                    self.assertFalse(at.exception, f"{view}: {[e.value for e in at.exception]}")
                    text = _texts(at)
                    self.assertTrue(any("barre latérale" in str(c.value) for c in at.caption), f"{view}: mention bénéfice absente")
                    for needle in expected:
                        self.assertIn(needle, text, f"{view}: « {needle} » absent")
                    self.assertEqual(profile_calls.call_count, 1 if view == "Mensuel" else 0, view)
                    self.assertEqual(projection_calls.call_count, 1 if view == "Prévisions" else 0, view)
                    self.assertEqual(rolling_calls.call_count, 1 if view == "Prévisions" else 0, view)
                # les contenus des autres vues ne sont pas affichés
                others = [v for v in expectations if v != view]
                for other in others:
                    self.assertNotIn(expectations[other][0], text, f"{view} affiche aussi {other}")

    def test_default_view_is_monthly_and_choice_is_remembered(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = AppTest.from_string(VIEW_SCRIPT, default_timeout=60)
            at.session_state["_tmp_root"] = tmp
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state[stats.STATS_VIEW_STATE_KEY], "Mensuel")
            self.assertIn("Bilan mensuel", _texts(at))
            group = at.get("button_group")[0]
            group.set_value("Prévisions").run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state[stats.STATS_VIEW_STATE_KEY], "Prévisions")
            self.assertIn("Objectif PokéStock", _texts(at))
            at.run()  # nouveau rerun : la vue reste
            self.assertIn("Objectif PokéStock", _texts(at))

    def test_performance_year_selector_and_single_year_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = self._run("Performance", root=tmp)
            self.assertFalse(at.exception)
            groups = at.get("button_group")
            self.assertEqual(len(groups), 2)  # vues + années (plusieurs années de données)
            self.assertEqual(_option_labels(groups[1]), [str(datetime.now().year), str(datetime.now().year - 1)])
            groups[1].set_value(str(datetime.now().year - 1)).run()
            self.assertFalse(at.exception)
            self.assertIn(f"{datetime.now().year - 1}", _texts(at))
            self.assertNotIn("à ce jour", _texts(at))  # année passée : plus de « à ce jour »
        with tempfile.TemporaryDirectory() as tmp:
            at = self._run("Performance", script=NEW_FIRST_YEAR_SCRIPT, root=tmp)
            self.assertFalse(at.exception)
            self.assertEqual(len(at.get("button_group")), 1)  # une seule année : pas de sélecteur d'année

    def test_forecast_saves_new_keys_only_through_goal_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            goals = os.path.join(tmp, "monthly_goals.json")
            month = datetime.now().strftime("%Y-%m")
            seed = {month: {"ca_target": 500.0, "qty_target": 50, "benef_target": 250.0, "auto_generated": False}}
            with open(goals, "w", encoding="utf-8") as handle:
                json.dump(seed, handle)
            at = self._run("Prévisions", root=tmp)
            self.assertFalse(at.exception)
            with open(goals, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), seed)  # l'affichage seul n'écrit rien
            year = str(datetime.now().year)
            at.number_input(key="stats_annual_ca_input").set_value(12000.0)
            next(b for b in at.button if b.key == "stats_annual_ca_save").click().run()
            self.assertFalse(at.exception)
            at.number_input(key="stats_annual_benef_input").set_value(6000.0)
            next(b for b in at.button if b.key == "stats_annual_benef_save").click().run()
            at.number_input(key="stats_annual_qty_input").set_value(600)
            next(b for b in at.button if b.key == "stats_annual_qty_save").click().run()
            self.assertFalse(at.exception)
            with open(goals, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved[month], seed[month])
            self.assertEqual(saved["annual_goals"][year], {"ca_target": 12000.0, "benef_target": 6000.0, "qty_target": 600})  # chaque carte garde les autres valeurs
            self.assertNotIn("long_term_goal", saved)
            self.assertIn("12\u00a0000\u00a0€", _texts(at))
            # objectif long terme : montant proposé + date limite (clé facultative « deadline »)
            at.radio(key="stats_lt_choice").set_value("2\u00a0000\u00a0€")
            at.date_input(key="stats_lt_deadline").set_value(date(2028, 6, 30))
            next(b for b in at.button if b.key == "stats_lt_save").click().run()
            self.assertFalse(at.exception)
            with open(goals, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["long_term_goal"], {"monthly_benef_target": 2000.0, "deadline": "2028-06-30"})
            self.assertIn("annual_goals", saved)
            self.assertEqual(saved[month], seed[month])
            self.assertIn("avant 30/06/2028", _texts(at))

    def test_absent_deadline_uses_default_and_old_long_term_entry_stays_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            goals = os.path.join(tmp, "monthly_goals.json")
            with open(goals, "w", encoding="utf-8") as handle:
                json.dump({"long_term_goal": {"monthly_benef_target": 2000.0}}, handle)  # ancien format, sans « deadline »
            at = self._run("Prévisions", root=tmp)
            self.assertFalse(at.exception)
            text = _texts(at)
            self.assertIn("avant 31/12/2028", text)
            self.assertIn("2\u00a0000\u00a0€ de bénéfice moyen par mois", text)
            with open(goals, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"long_term_goal": {"monthly_benef_target": 2000.0}})  # rien n'est réécrit

    def test_forecast_without_complete_month_still_renders(self):
        script = VIEW_SCRIPT.replace("for k in range(19, -1, -1):", "for k in range(0, -1, -1):")  # ventes du mois en cours seulement
        with tempfile.TemporaryDirectory() as tmp:
            at = self._run("Prévisions", script=script, root=tmp)
            self.assertFalse(at.exception, [e.value for e in at.exception])
            text = _texts(at)
            self.assertIn("Pas encore de mois complet", text)
            self.assertIn("Paliers de bénéfice moyen par mois", text)
            self.assertNotIn("En retard", text)  # pas de statut sans historique
            self.assertEqual(len(at.get("plotly_chart")), 0)

    def test_no_empty_or_repeated_cards_in_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = self._run("Prévisions", root=tmp)
            self.assertFalse(at.exception)
            text = _texts(at)
            self.assertNotIn("Objectif non défini", text)
            for label in ("Fin d'année", "Mois restants", "Tendance actuelle", "Bénéfice cumulé depuis le début"):
                self.assertEqual(text.count(label), 1, label)

    def test_old_unused_lot_and_channel_views_still_run(self):
        script = '''
import streamlit as st
from datetime import datetime
from ui.pages import statistics as s
now = datetime(2026, 9, 10)
rows = [
    {"sale": {}, "date": now, "month": "2026-09", "price": 50.0, "quantity": 2, "card_name": "A", "lot": "Lot A", "lot_uid": "a", "cost": 20.0, "benef": 30.0, "canal": "Vinted", "is_off_stock": False, "is_system_lot": False},
    {"sale": {}, "date": now, "month": "2026-09", "price": 10.0, "quantity": 1, "card_name": "B", "lot": "Lot B", "lot_uid": "b", "cost": 40.0, "benef": -30.0, "canal": "Main propre", "is_off_stock": False, "is_system_lot": False},
]
s._render_lots_view(rows, {"lots": [{"nom": "Lot A", "prix_achat_reel": 100.0}, {"nom": "Lot B", "prix_achat_reel": 40.0}]})
s._render_channels_view(rows)
'''
        at = AppTest.from_string(script, default_timeout=60).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertGreaterEqual(len(at.dataframe), 4)


class HistorySpreadTests(unittest.TestCase):
    """L'historique saisi en mars 2026 est réparti à parts égales sur janvier, février et mars (Statistiques seulement)."""

    @staticmethod
    def _row(day, price, cost, qty=1.0, *, lot="Lot A", canal="Vinted", lot_sale=False, month="2026-03", tx=None, benef="auto", hour=19):
        d = datetime(2026, int(month[5:]), day, hour, 0)
        return {"sale": {"sale_transaction_id": tx} if tx else {}, "date": d, "month": month, "price": float(price), "quantity": 0.0 if lot_sale else float(qty),
                "card_name": "Vente initiale" if lot_sale else f"Carte {day}-{price}", "lot": lot, "lot_uid": lot, "cost": cost,
                "benef": (price - cost if cost is not None else None) if benef == "auto" else benef, "cote": float(price), "canal": canal,
                "is_off_stock": False, "is_lot_sale": lot_sale, "is_system_lot": False}

    def _fixture(self):
        rows = [self._row(16, 100.0 + i, 40.0, lot_sale=True, lot=f"Lot {i}", canal="Non renseigné", tx=f"ls{i}") for i in range(9)]
        rows += [self._row(16, 14.0, 5.0, tx="c1"), self._row(17, 14.0, 6.0, qty=3.0, tx="c2")]
        rows += [self._row(27, 23.0, 10.0, qty=1.0, tx="r1"), self._row(29, 89.0, 30.0, qty=5.0, tx="r2")]  # vraies ventes de mars
        rows += [self._row(5, 50.0, 20.0, qty=2.0, month="2026-04", tx="a1")]
        return rows

    def test_total_is_preserved_and_import_is_split_in_equal_thirds(self):
        rows = self._fixture()
        spread = stats._spread_history_import(rows)
        before, after = stats._build_monthly_stats(rows, []), stats._build_monthly_stats(spread, [])
        for field in ("ca", "benef", "qty"):
            self.assertAlmostEqual(sum(m[field] for m in before.values()), sum(m[field] for m in after.values()), places=9)
        self.assertEqual(sum(len(m["transactions"]) for m in before.values()), sum(len(m["transactions"]) for m in after.values()))
        imported_ca = sum(100.0 + i for i in range(9)) + 28.0
        self.assertAlmostEqual(after["2026-01"]["ca"], imported_ca / 3)
        self.assertAlmostEqual(after["2026-02"]["ca"], imported_ca / 3)
        self.assertAlmostEqual(after["2026-03"]["ca"], imported_ca / 3 + 23.0 + 89.0)  # + les vraies ventes de fin mars
        imported_benef = sum(100.0 + i - 40.0 for i in range(9)) + 9.0 + 8.0
        self.assertAlmostEqual(after["2026-01"]["benef"], imported_benef / 3)
        self.assertAlmostEqual(after["2026-04"]["ca"], 50.0)  # les autres mois ne bougent pas
        self.assertEqual(len(rows), len(self._fixture()))  # liste d'entrée non modifiée
        self.assertTrue(all(not r.get("history_estimated") for r in rows))

    def test_cost_is_split_too_and_lot_and_channel_attribution_is_kept(self):
        rows = self._fixture()
        spread = stats._spread_history_import(rows)
        self.assertAlmostEqual(sum(r["cost"] for r in rows), sum(r["cost"] for r in spread))
        by_lot = lambda data: {lot: round(sum(r["price"] for r in data if r["lot"] == lot), 9) for lot in {r["lot"] for r in data}}
        self.assertEqual(by_lot(rows), by_lot(spread))
        by_channel = lambda data: {c: round(sum(r["price"] for r in data if r["canal"] == c), 9) for c in {r["canal"] for r in data}}
        self.assertEqual(by_channel(rows), by_channel(spread))
        self.assertEqual({r["month"] for r in spread if r.get("history_estimated")}, {"2026-01", "2026-02", "2026-03"})

    def test_cards_and_transactions_are_integers_with_remainder_given_to_first_months(self):
        rows = [self._row(16, 10.0, 4.0, qty=1.0, tx=f"t{i}") for i in range(7)] + [self._row(16, 5.0, 2.0, lot_sale=True, tx=f"l{i}") for i in range(3)]
        after = stats._build_monthly_stats(stats._spread_history_import(rows), [])
        qty = [after[m]["qty"] for m in ("2026-01", "2026-02", "2026-03")]
        tx = [len(after[m]["transactions"]) for m in ("2026-01", "2026-02", "2026-03")]
        self.assertEqual(qty, [3.0, 2.0, 2.0])  # 7 cartes
        self.assertEqual(tx, [3, 2, 2])  # 7 transactions : les 3 ventes initiales n'en sont pas
        self.assertTrue(all(float(v).is_integer() for v in qty))

    def test_split_integer_and_allocation_helpers(self):
        self.assertEqual(stats._split_integer(11, 3), [4, 4, 3])
        self.assertEqual(stats._split_integer(2, 3), [1, 1, 0])
        self.assertEqual(stats._split_integer(0, 3), [0, 0, 0])
        matrix = stats._allocate_quantities([1.0, 3.0, 2.0], [2.0, 2.0, 2.0])
        self.assertEqual([sum(line) for line in matrix], [1.0, 3.0, 2.0])  # chaque ligne garde sa quantité
        self.assertEqual([sum(line[k] for line in matrix) for k in range(3)], [2.0, 2.0, 2.0])  # chaque mois reçoit sa cible

    def test_first_sales_month_rolling_average_and_projection_use_the_split(self):
        rows = self._fixture()
        before, after = stats._build_monthly_stats(rows, []), stats._build_monthly_stats(stats._spread_history_import(rows), [])
        now = datetime(2026, 5, 13, 12, 0)
        self.assertEqual(stats._first_sales_month(before), "2026-03")
        self.assertEqual(stats._first_sales_month(after), "2026-01")
        h_before, h_after = stats._rolling_average_history(before, now), stats._rolling_average_history(after, now)
        self.assertEqual(h_before["months"], ["2026-03", "2026-04"])
        self.assertEqual(h_after["months"], ["2026-01", "2026-02", "2026-03", "2026-04"])
        total_benef = sum(m["benef"] for m in after.values())
        self.assertAlmostEqual(h_after["benef_avg"][-1], total_benef / 4)  # 4 mois complets au lieu de 2
        self.assertAlmostEqual(h_before["benef_avg"][-1], total_benef / 2)
        proj_after = stats._year_projection(after, 2026, now)
        self.assertEqual(proj_after["complete_months"], 4)
        self.assertEqual(stats._year_projection(before, 2026, now)["complete_months"], 2)
        self.assertAlmostEqual(proj_after["avg"]["benef"], total_benef / 4)

    def test_sales_after_the_cutoff_day_are_never_split_and_cutoff_can_be_disabled(self):
        rows = self._fixture()
        spread = stats._spread_history_import(rows)
        late = [r for r in spread if r["date"].day in (27, 29)]
        self.assertEqual(len(late), 2)
        self.assertTrue(all(r["month"] == "2026-03" and not r.get("history_estimated") for r in late))
        with patch.object(stats, "HISTORY_IMPORT_LAST_DAY", None):
            whole = stats._spread_history_import(rows)
        self.assertEqual({r["month"] for r in whole if r["date"].day in (27, 29)} | {"2026-01"}, {"2026-01", "2026-02", "2026-03"})
        self.assertAlmostEqual(stats._build_monthly_stats(whole, [])["2026-01"]["ca"], sum(r["price"] for r in rows if r["month"] == "2026-03") / 3)

    def test_unknown_benefit_stays_unknown_and_nothing_to_split_returns_the_same_rows(self):
        rows = [self._row(16, 30.0, None, benef=None, tx="x1"), self._row(5, 10.0, 4.0, month="2026-04", tx="x2")]
        spread = stats._spread_history_import(rows)
        self.assertTrue(all(r["benef"] is None and r["cost"] is None for r in spread if r.get("history_estimated")))
        self.assertFalse(stats._build_monthly_stats(spread, [])["2026-01"]["benef_known"])
        other = [self._row(5, 10.0, 4.0, month="2026-04")]
        self.assertEqual(stats._spread_history_import(other), other)

    def test_initial_sales_are_not_transactions_nor_in_basket_but_stay_in_revenue(self):
        rows = [self._row(16, 90.0, 30.0, lot_sale=True, tx="i1"), self._row(16, 10.0, 4.0, tx="c1"), self._row(17, 20.0, 8.0, tx="c2")]
        agg = stats._aggregate_sales(rows)
        self.assertEqual(agg["transactions"], 2)
        self.assertAlmostEqual(agg["ca"], 120.0)
        self.assertAlmostEqual(agg["basket"], 15.0)  # (10 + 20) / 2
        self.assertAlmostEqual(agg["benef"], 60.0 + 6.0 + 12.0)
        monthly = stats._build_monthly_stats(rows, [])
        self.assertEqual(len(monthly["2026-03"]["transactions"]), 2)
        spread = stats._spread_history_import(rows)
        after = stats._build_monthly_stats(spread, [])
        self.assertEqual(sum(len(m["transactions"]) for m in after.values()), 2)  # total conservé, mois sans transaction possible
        self.assertAlmostEqual(sum(m["ca"] for m in after.values()), 120.0)
        self.assertEqual(stats._aggregate_sales(spread)["transactions"], 2)

    def test_initial_sales_form_their_own_channel_without_touching_the_data(self):
        rows = [self._row(16, 90.0, 30.0, lot_sale=True, canal="", tx="i1"), self._row(16, 60.0, 4.0, canal="Vinted", tx="c1")]
        before = [dict(r) for r in rows]
        shares = {item["channel"]: item["ca"] for item in stats._channel_shares(rows)}
        self.assertEqual(shares, {"Ventes initiales": 90.0, "Vinted": 60.0})
        self.assertEqual(rows, before)  # affichage seulement
        self.assertEqual(stats._row_channel(rows[0]), "Ventes initiales")
        self.assertEqual(stats._row_channel(rows[1]), stats._normalize_channel("Vinted"))

    def test_cards_sold_has_a_single_definition_across_views(self):
        rows = [self._row(5, 10.0, 4.0, qty=3.0, month="2026-04", tx="a"), self._row(6, 90.0, 30.0, lot_sale=True, month="2026-04", tx="b"),
                {**self._row(7, 5.0, 1.0, qty=2.0, month="2026-04", tx="c"), "is_off_stock": True}]
        expected = 3.0  # cartes du stock seulement : ni vente initiale, ni hors stock
        self.assertEqual(sum(stats._physical_sale_quantity(r) for r in rows), expected)
        self.assertEqual(stats._aggregate_sales(rows)["qty"], expected)
        self.assertEqual(stats._build_monthly_stats(rows, [])["2026-04"]["qty"], expected)
        self.assertEqual(sum(item["qty"] for item in stats._lot_rows_for(rows, {}).values()), expected)

    def test_collection_lots_are_excluded_from_pending_count_and_listed_separately(self):
        lots = [{"nom": "Mixte", "is_mixte": True, "prix_achat": 500.0, "prix_achat_reel": 1600.0, "cards": []},
                {"nom": "Classique", "prix_achat": 100.0, "cards": []},
                {"nom": "🧾 Collection", "is_collection_lot": True, "is_mixte": True, "prix_achat": 0.0, "cards": []}]
        self.assertEqual(stats._collection_lot_names(lots), {"Mixte"})  # lot système écarté, critère = is_mixte
        costs = stats._lot_cost_map(lots)
        rows = [{"lot": "Mixte", "price": 790.0, "quantity": 1, "benef": 200.0, "is_system_lot": False, "is_off_stock": False},
                {"lot": "Classique", "price": 30.0, "quantity": 1, "benef": 10.0, "is_system_lot": False, "is_off_stock": False}]
        summary = stats._lot_summary(rows, rows, costs, stats._collection_lot_names(lots))
        self.assertEqual(summary["total_with_cost"], 1)  # « X sur Y » sans le lot collection
        self.assertEqual([row["lot"] for row in summary["pending"]], ["Classique"])  # plus gros reste hors collection
        self.assertEqual(summary["pending_count"], 1)
        self.assertEqual(summary["collection"], [{"lot": "Mixte", "cost": 1600.0, "ca_total": 790.0}])
        text = stats._lots_unreimbursed_html(summary)
        self.assertIn("Lots collection conservés", text)
        self.assertIn("coût 1\u00a0600\u00a0€", text)
        self.assertIn("déjà récupéré en ventes 790\u00a0€", text)
        self.assertIn("Plus gros reste : <b>Classique</b>", text)
        # sans lot collection : comportement inchangé
        plain = stats._lot_summary(rows, rows, costs)
        self.assertEqual(plain["total_with_cost"], 2)
        self.assertNotIn("Lots collection conservés", stats._lots_unreimbursed_html(plain))

    def test_monthly_chart_has_room_for_legend_and_month_labels(self):
        script = '''
import streamlit as st
from ui.pages import statistics as s
monthly = {f"2026-{m:02d}": {"ca": 100.0 * m, "benef": 50.0 * m, "benef_known": True, "qty": float(m), "transactions": set(), "purchases": 0.0} for m in range(1, 11)}
months = sorted(monthly)
s._render_stats_v3_chart(monthly, months, "2026-10")
'''
        captured = {}
        import plotly.graph_objects as go
        real = go.Figure.update_layout
        def spy(self, *args, **kwargs):
            if kwargs.get("height") == 320:
                captured.update(kwargs)
            return real(self, *args, **kwargs)
        with patch.object(go.Figure, "update_layout", spy):
            at = AppTest.from_string(script, default_timeout=60).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertGreaterEqual(captured["margin"]["t"], 25)  # place pour la légende
        self.assertEqual(captured["legend"]["xanchor"], "left")  # légende alignée à gauche : jamais coupée à droite
        self.assertTrue(captured["xaxis"]["automargin"])  # libellés de mois jamais coupés en bas
        self.assertNotEqual(captured["xaxis"]["tickangle"], 0)

    def test_estimated_months_are_marked_and_monthly_goals_are_not_invented(self):
        self.assertEqual([stats._estimated_mark(m) for m in ("2026-01", "2026-02", "2026-03", "2026-04")], ["*", "*", "*", ""])
        self.assertEqual(stats._month_label_est("2026-02"), "Février 2026*")
        self.assertEqual(stats._chart_month_labels(["2026-01", "2026-02", "2026-03", "2026-04"]), ["Janv.*", "Févr.*", "Mars*", "Avr."])
        self.assertEqual(stats._estimated_note_html(["2026-04", "2026-05"]), "")
        self.assertIn("historique réparti", stats._estimated_note_html(["2026-03"]))
        months = ["2026-01", "2026-02", "2026-03"] + [f"2026-{m:02d}" for m in range(4, 10)]
        monthly = {m: _m(500, 250) for m in months}
        monthly["2026-10"] = _m(100, 50)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "monthly_goals.json")
            writes = []
            goals, _ = stats._load_month_goals(path, "2026-10", "2026-09", monthly, sorted(monthly), lambda target, data, **kw: writes.append(dict(data)))
        self.assertNotIn("2026-01", goals)
        self.assertNotIn("2026-02", goals)
        self.assertEqual(sorted(goals), ["2026-10"])

    def test_charts_show_the_estimated_months_legend_and_shading(self):
        months = ["2026-01", "2026-02", "2026-03", "2026-04"]
        fig = stats._build_year_chart(months, [700.0, 700.0, 900.0, 1400.0], [390.0, 390.0, 500.0, 850.0])
        self.assertIn("Mois estimés* (historique réparti)", [trace.name for trace in fig.data])
        self.assertEqual(len(fig.layout.shapes), 1)
        self.assertEqual(list(fig.data[0].x), ["Janv.*", "Févr.*", "Mars*", "Avr."])
        clean = stats._build_year_chart(["2026-04", "2026-05"], [1.0, 2.0], [1.0, 1.0])
        self.assertNotIn("Mois estimés* (historique réparti)", [trace.name for trace in clean.data])
        self.assertEqual(len(clean.layout.shapes), 0)


# -- Performance : rotation du stock et délai de remboursement ---------------------------------------------------------

def _pts(*items):
    return [{"captured_at": moment, "value": value, "provenance": "live"} for moment, value in items]


def _sale(lot, day, price, cost=None, **extra):
    row = {"lot": lot, "date": datetime.fromisoformat(day), "price": price, "quantity": 1, "cost": cost,
           "benef": None if cost is None else price - cost, "is_off_stock": False, "is_lot_sale": False, "is_system_lot": False}
    row.update(extra)
    return row


def _lot(name, created, cards=None, **extra):
    lot = {"nom": name, "created": created, "cards": cards or []}
    lot.update(extra)
    return lot


class StockRotationTests(unittest.TestCase):
    NOW = datetime(2026, 1, 11)

    def test_average_is_time_weighted_not_a_mean_of_points(self):
        series = stats._history_series(_pts(("2026-01-01T00:00:00", 100.0), ("2026-01-02T00:00:00", 300.0),
                                            ("2026-01-02T00:05:00", 300.0), ("2026-01-02T00:10:00", 300.0)))
        avg = stats._average_stock_value(series, datetime(2026, 1, 1), datetime(2026, 1, 4))
        self.assertAlmostEqual(avg, (100 * 1 + 300 * 2) / 3)  # 233,3 et non (100+3*300)/4 = 250

    def test_rotation_and_annualisation(self):
        points = _pts(("2026-01-01T00:00:00", 200.0), ("2026-01-06T00:00:00", 200.0))
        sales = [_sale("A", "2026-01-03T10:00:00", 80, cost=60), _sale("A", "2026-01-05T10:00:00", 70, cost=40),
                 _sale("A", "2025-12-20T10:00:00", 500, cost=400),   # avant l'historique : ignorée
                 _sale("A", "2026-01-04T10:00:00", 10, cost=None)]   # coût inconnu : compte quand même dans le CA
        r = stats.compute_stock_rotation(sales, points, self.NOW)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["days"], 10.0)
        self.assertAlmostEqual(r["avg_stock"], 200.0)
        self.assertAlmostEqual(r["ca_period"], 160.0)  # CA, pas coût : 80 + 70 + 10
        self.assertNotIn("cost_sold", r)
        self.assertAlmostEqual(r["rotation_period"], 0.8)
        self.assertAlmostEqual(r["rotation_annual"], 0.8 * 365 / 10)
        self.assertTrue(r["indicative"])  # moins de 30 jours

    def test_initial_sales_are_included_in_the_period_revenue(self):
        points = _pts(("2026-01-01T00:00:00", 100.0), ("2026-02-15T00:00:00", 100.0))
        sales = [_sale("A", "2026-01-10T00:00:00", 90, cost=30, is_lot_sale=True, quantity=0.0)]
        r = stats.compute_stock_rotation(sales, points, datetime(2026, 2, 15))
        self.assertAlmostEqual(r["ca_period"], 90.0)
        self.assertAlmostEqual(r["rotation_period"], 0.9)
        self.assertFalse(r["indicative"])  # 45 jours

    def test_not_enough_history_gives_insufficient(self):
        self.assertEqual(stats.compute_stock_rotation([], [], self.NOW)["status"], "insufficient")
        self.assertEqual(stats.compute_stock_rotation([], _pts(("2026-01-01T00:00:00", 5.0)), self.NOW)["status"], "insufficient")
        zero = _pts(("2026-01-01T00:00:00", 0.0), ("2026-01-06T00:00:00", 0.0))
        self.assertEqual(stats.compute_stock_rotation([], zero, self.NOW)["status"], "insufficient")
        bad = [{"captured_at": "n'importe quoi", "value": 3}, {"captured_at": "2026-01-01T00:00:00"}, "x"]
        self.assertEqual(stats.compute_stock_rotation([], bad, self.NOW)["status"], "insufficient")


class LotPaybackTests(unittest.TestCase):
    NOW = datetime(2026, 10, 13)

    def _lots(self):
        mk = lambda name, created, cost, **extra: _lot(name, created, prix_achat=cost, prix_achat_reel=cost, **extra)
        return [
            mk("A", "2026-05-01T10:00:00", 100.0), mk("B", "2026-06-01T10:00:00", 40.0), mk("C", "2026-07-01T10:00:00", 200.0),
            mk("D", "2026-03-20T10:00:00", 100.0), mk("E", "2026-04-01T10:00:00", 100.0),
            mk("F", "2026-06-01T10:00:00", 60.0), mk("G", "2026-08-01T10:00:00", 90.0), mk("H", "2026-09-01T10:00:00", 50.0),
        ]

    def _sales(self):
        return [
            _sale("A", "2026-05-11T10:00:00", 60), _sale("A", "2026-05-31T10:00:00", 50), _sale("A", "2026-06-15T10:00:00", 500),
            _sale("A", "2026-05-02T10:00:00", 999, is_lot_sale=True, quantity=0.0),   # vente initiale : jamais dans le cumul
            _sale("A", "2026-05-03T10:00:00", 999, is_off_stock=True),                 # hors stock : idem
            _sale("B", "2026-06-06T10:00:00", 80),                                     # remboursé dès la 1re vente
            _sale("C", "2026-09-30T10:00:00", 100), _sale("C", "2026-08-30T10:00:00", 150),   # ordre chronologique, pas d'insertion
            _sale("D", "2026-04-01T10:00:00", 30), _sale("E", "2026-04-10T10:00:00", 90), _sale("G", "2026-08-10T10:00:00", 20),
        ]

    def test_payback_date_is_where_the_cumulative_reaches_the_cost(self):
        r = stats.compute_lot_payback(self._sales(), self._lots(), self.NOW)
        self.assertEqual(r["status"], "ok")
        by_lot = {row["lot"]: row for row in r["paid"]}
        self.assertEqual(sorted(by_lot), ["A", "B", "C"])
        self.assertEqual(by_lot["A"]["paid_on"], datetime(2026, 5, 31, 10))  # 60 + 50 = 110 >= 100
        self.assertAlmostEqual(by_lot["A"]["days"], 30.0)
        self.assertAlmostEqual(by_lot["B"]["days"], 5.0)   # remboursé par sa première vente
        self.assertAlmostEqual(by_lot["C"]["days"], 91.0)  # 150 puis 100 : atteint le 30/09 seulement
        self.assertEqual(r["reimbursed_lots"], 3)
        self.assertAlmostEqual(r["mean_days"], (30 + 5 + 91) / 3)   # moyenne simple par lot
        self.assertAlmostEqual(r["median_days"], 30.0)

    def test_never_reimbursed_lots_are_pending_and_not_in_the_average(self):
        r = stats.compute_lot_payback(self._sales(), self._lots(), self.NOW)
        pending = {row["lot"]: row for row in r["pending"]}
        self.assertNotIn("A", pending)
        self.assertEqual([row["lot"] for row in r["pending"]], ["D", "F", "G"])  # plus anciens d'abord, limités à 3
        self.assertAlmostEqual(r["pending"][0]["reste"], 70.0)
        self.assertEqual(round(r["pending"][0]["days"]), 207)
        self.assertAlmostEqual(r["pending"][1]["reste"], 60.0)   # aucune vente : tout le coût reste
        self.assertEqual(r["pending_total"], 4)                  # D, F, G, H ; E (reste 10 €) est sous le seuil
        self.assertNotIn("E", [row["lot"] for row in r["pending"]])
        self.assertEqual(stats.SLOW_LOT_MIN_VALUE, 20.0)
        self.assertEqual([row["lot"] for row in stats.compute_lot_payback(self._sales(), self._lots(), self.NOW, pending_count=10)["pending"]],
                         ["D", "F", "G", "H"])
        low = stats.compute_lot_payback(self._sales(), self._lots(), self.NOW, pending_count=10, pending_min_value=0.01)
        self.assertEqual([row["lot"] for row in low["pending"]], ["D", "E", "F", "G", "H"])
        edge = [_lot("Pile", "2026-06-01T00:00:00", prix_achat=20.0)]
        self.assertEqual([row["lot"] for row in stats.compute_lot_payback([], edge, self.NOW)["pending"]], ["Pile"])  # 20 € : seuil inclus

    def test_each_exclusion_keeps_the_lot_out_of_both_lists(self):
        base = stats.compute_lot_payback(self._sales(), self._lots(), self.NOW)
        excluded = {
            "Bloc 16/03": dict(created="2026-03-16T10:00:00"), "Bloc 17/03": dict(created="2026-03-17T10:00:00"),
            "Bloc 18/03": dict(created="2026-03-18T09:00:00"),
            "Collection": dict(created="2026-05-01T10:00:00", is_mixte=True), "Divers": dict(created="2026-05-01T10:00:00", is_divers=True),
            "📈 Stockage": dict(created="2026-05-01T10:00:00", is_storage=True), "🔄 Trade": dict(created="2026-05-01T10:00:00", is_trade=True),
            "Sans date": dict(created=None), "Sans prix": dict(created="2026-05-01T10:00:00", prix_achat=0.0, prix_achat_reel=0.0),
        }
        for name, extra in excluded.items():
            lot = {"nom": name, "cards": [], "prix_achat": 50.0, "prix_achat_reel": 50.0, **extra}
            sales = self._sales() + [_sale(name, "2026-05-02T10:00:00", 500, is_system_lot=bool(extra.get("is_storage") or extra.get("is_trade")))]
            r = stats.compute_lot_payback(sales, self._lots() + [lot], self.NOW, pending_count=10)
            self.assertEqual([row["lot"] for row in r["paid"]], [row["lot"] for row in base["paid"]], name)
            self.assertNotIn(name, [row["lot"] for row in r["pending"]], name)
            self.assertAlmostEqual(r["mean_days"], base["mean_days"], msg=name)
        r = stats.compute_lot_payback(self._sales(), self._lots() + [_lot("Bloc", "2026-03-17T00:00:00", prix_achat=50.0), _lot("Bloc2", "2026-03-18T00:00:00", prix_achat=50.0)], self.NOW)
        self.assertEqual(r["bulk_excluded"], 2)
        self.assertEqual(stats.compute_lot_payback(self._sales(), self._lots() + [_lot("Sans date", None, prix_achat=9.0)], self.NOW)["undated"], 1)

    def test_less_than_three_reimbursed_lots_is_not_enough_data(self):
        lots = self._lots()[:2] + self._lots()[3:]   # A et B remboursés seulement
        r = stats.compute_lot_payback(self._sales(), lots, self.NOW)
        self.assertEqual(r["status"], "insufficient")
        self.assertEqual(r["reimbursed_lots"], 2)
        self.assertNotIn("mean_days", r)
        self.assertTrue(r["pending"])  # la liste des lots en cours reste disponible
        self.assertEqual(stats.compute_lot_payback([], [], self.NOW)["status"], "insufficient")

    def test_cost_function_is_used_and_sale_before_creation_gives_zero_days(self):
        r = stats.compute_lot_payback(self._sales(), self._lots(), self.NOW, cost_func=lambda lot: 1000.0)
        self.assertEqual(r["reimbursed_lots"], 0)
        early = [_lot("T", "2026-06-10T00:00:00", prix_achat=10.0)]
        sales = [_sale("T", "2026-06-01T00:00:00", 50)]
        self.assertAlmostEqual(stats.compute_lot_payback(sales, early, self.NOW, min_lots=1)["paid"][0]["days"], 0.0)


class PerformanceIndicatorsHtmlTests(unittest.TestCase):
    def test_rotation_html(self):
        ok = {"status": "ok", "start": datetime(2026, 6, 7), "end": datetime(2026, 10, 13), "days": 128.0, "ca_period": 2535.0,
              "avg_stock": 4950.0, "rotation_period": 0.512, "rotation_annual": 1.45, "indicative": False}
        html_text = stats._rotation_html(ok)
        for needle in ("Rotation du stock", "1,45×", "par an", "Ton stock se renouvelle environ <b>1,5 fois par an</b>", "ps-stats-scale",
                       "0×", "4×", "left:36.2%", "CA ÷ stock moyen, tous deux au prix du marché", "depuis le 07/06/2026", "0,51"):
            self.assertIn(needle, html_text)
        self.assertNotIn("coût", html_text)
        self.assertNotIn("indicatif", html_text)
        self.assertIn("indicatif", stats._rotation_html({**ok, "indicative": True}))
        self.assertIn("left:100.0%", stats._rotation_html({**ok, "rotation_annual": 7.0}))  # repère plafonné à l'échelle
        self.assertIn("Pas assez de données", stats._rotation_html({"status": "insufficient"}))

    def test_payback_html(self):
        ok = {"status": "ok", "mean_days": 41.6, "median_days": 30.4, "reimbursed_lots": 14, "bulk_excluded": 10,
              "pending": [{"lot": "Lot <A>", "days": 200.0, "reste": 120.0}, {"lot": "B", "days": 100.0, "reste": 45.0}]}
        html_text = stats._payback_html(ok)
        for needle in ("Délai de remboursement", f"42{stats.NBSP}jours", f"médiane 30{stats.NBSP}j", "en moyenne",
                       "Sur 14 lots remboursés (10 exclus : historique saisi en bloc)", "Lots en cours de remboursement",
                       f"200{stats.NBSP}jours · reste 120{stats.NBSP}€", "Lot &lt;A&gt;", "is-orange", "width:50.0%"):
            self.assertIn(needle, html_text)
        self.assertIn("(1 exclu : historique", stats._payback_html({**ok, "bulk_excluded": 1}))
        poor = stats._payback_html({"status": "insufficient", "bulk_excluded": 10, "pending": []})
        self.assertIn("Pas assez de données", poor)
        self.assertIn("10 lots exclus (historique saisi en bloc)", poor)
        self.assertNotIn("en moyenne", poor)

    def test_old_resale_delay_is_gone(self):
        for name in ("compute_resale_delay", "slowest_stock_lots", "_resale_delay_html", "_lot_remaining_value"):
            self.assertFalse(hasattr(stats, name), name)


PERF_SCRIPT = '''
import json, os
from datetime import datetime, timedelta
import streamlit as st
from ui.pages.statistics import render_statistics_page

root = st.session_state["_tmp_root"]
now = datetime.now()
def iso(days):
    return (now - timedelta(days=days)).isoformat()
lots = []
for idx, (age, sale_after) in enumerate([(60, 10), (50, 20), (40, 12), (30, 5)]):
    lots.append({"nom": "Lot %d" % idx, "created": iso(age), "prix_achat_reel": 50.0, "cards": [{"name": "C", "quantity": 2, "sold_quantity": 1, "suggested_price": 25.0}],
                 "ventes": [{"date": iso(age - sale_after), "price": 60.0, "quantity": 1, "canal": "Vinted", "card_name": "Carte %d" % idx}]})
lots.append({"nom": "Lot lent", "created": iso(100), "prix_achat_reel": 80.0, "cards": [], "ventes": []})
lots.append({"nom": "Ancien en bloc", "created": "2026-03-16T10:00:00", "prix_achat_reel": 20.0, "cards": [], "ventes": [{"date": iso(5), "price": 10.0, "quantity": 1, "card_name": "X"}]})
archives_path = os.path.join(root, "lots_archives.json")
with open(archives_path, "w", encoding="utf-8") as handle:
    json.dump([], handle)
render_statistics_page(
    ld_func=lambda: {"lots": lots},
    safe_write_json_func=lambda path, data, indent=None: None,
    calc_cout_lot_func=lambda lot, lot_idx=None: ([], 100.0),
    effective_purchase_price_func=lambda lot: lot["prix_achat_reel"],
    proxy_img_func=lambda url: url,
    lots_archives_path=archives_path,
    monthly_goals_path=os.path.join(root, "monthly_goals.json"),
    stock_history_path=os.path.join(root, "stock_value_history.json"),
)
'''


class PerformanceIndicatorsAppTests(unittest.TestCase):
    def _history(self, root, days_back):
        points = [{"captured_at": (datetime.now() - timedelta(days=d)).isoformat(timespec="seconds"), "value": 300.0, "provenance": "live"}
                  for d in (days_back, days_back // 2)]
        path = os.path.join(root, "stock_value_history.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "points": points, "annotations": []}, handle)
        return path

    def _run(self, root):
        at = AppTest.from_string(PERF_SCRIPT, default_timeout=60)
        at.session_state["_tmp_root"] = root
        at.session_state[stats.STATS_VIEW_STATE_KEY] = "Performance"
        at.run()
        return at

    def test_both_cards_render_below_the_lot_cards_and_history_file_is_not_written(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = self._history(tmp, 90)
            before = hashlib.md5(open(path, "rb").read()).hexdigest()
            at = self._run(tmp)
            self.assertFalse(at.exception, [e.value for e in at.exception])
            text = _texts(at)
            for needle in ("Lots les plus rentables", "Lots à rembourser", "Rotation du stock", "par an", "Ton stock se renouvelle environ",
                           "Délai de remboursement", "Sur 4 lots remboursés (1 exclu : historique saisi en bloc)",
                           "Lots en cours de remboursement", "Lot lent"):
                self.assertIn(needle, text)
            self.assertLess(text.index("Lots à rembourser"), text.index("Rotation du stock"))
            self.assertLess(text.index("Rotation du stock"), text.index("Délai de remboursement"))
            self.assertNotIn("indicatif", text.split("Rotation du stock")[1].split("Délai de remboursement")[0])
            self.assertNotIn("Délai moyen de revente", text)
            self.assertEqual(hashlib.md5(open(path, "rb").read()).hexdigest(), before)

    def test_short_history_is_flagged_indicative_and_missing_history_is_handled(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._history(tmp, 10)
            self.assertIn("indicatif", _texts(self._run(tmp)).split("Rotation du stock")[1].split("Délai de remboursement")[0])
        with tempfile.TemporaryDirectory() as tmp:  # aucun fichier d'historique
            at = self._run(tmp)
            self.assertFalse(at.exception)
            text = _texts(at)
            self.assertIn("Rotation du stock", text)
            self.assertIn("Pas assez de données", text.split("Rotation du stock")[1].split("Délai de remboursement")[0])
            self.assertIn("Délai de remboursement", text)


if __name__ == "__main__":
    unittest.main()

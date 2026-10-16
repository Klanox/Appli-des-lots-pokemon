"""Passage à une nouvelle année dans Statistiques (date simulée, jeux temporaires, aucun JSON réel).

La date du jour est toujours injectée (paramètre `now` de render_statistics_page) : jamais l'horloge.
"""
import hashlib
import html
import json
import os
import re
import tempfile
import unittest
from datetime import date, datetime

import streamlit
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import ButtonGroup

from ui.pages import statistics as stats


def _group_indices(group):
    values = group.value
    values = [values] if isinstance(values, str) else (values or [])
    contents = [getattr(option, "content", option) for option in group.options]
    return [contents.index(value) for value in values]


def _option_labels(group):
    return [str(getattr(option, "content", option)) for option in group.options]


if tuple(int(part) for part in streamlit.__version__.split(".")[:2]) < (1, 60):
    ButtonGroup.indices = property(_group_indices)


SCRIPT = '''
import json, os
from datetime import datetime
import streamlit as st
from logic import calc_cout_lot, effective_purchase_price
from ui.pages.statistics import render_statistics_page

root = st.session_state["_root"]
now = datetime.fromisoformat(st.session_state["_now"])
sales = st.session_state["_sales"]
lots = [{"nom": "Lot test", "prix_achat_reel": 100.0, "date_achat": "2026-01-02T10:00:00", "cards": [],
         "ventes": [{"date": d, "price": p, "quantity": 1, "canal": "Vinted", "card_name": "Carte %d" % i, "sale_id": "s%d" % i}
                    for i, (d, p) in enumerate(sales)]}]
for name in ("lots_archives.json", "counters.json"):
    path = os.path.join(root, name)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([] if name == "lots_archives.json" else {}, handle)

def safe_write(path, data, indent=None):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)

render_statistics_page(
    ld_func=lambda: {"lots": lots}, safe_write_json_func=safe_write, calc_cout_lot_func=lambda lot, lot_idx=None: ([], 100.0),
    effective_purchase_price_func=lambda lot: lot["prix_achat_reel"], proxy_img_func=lambda url: url,
    lots_archives_path=os.path.join(root, "lots_archives.json"), monthly_goals_path=os.path.join(root, "monthly_goals.json"),
    stock_history_path=os.path.join(root, "stock_value_history.json"), counters_path=os.path.join(root, "counters.json"), now=now,
)
'''

SALES_2026 = [("2026-%02d-%02d" % (m, 10) + "T10:00:00", 40.0 + m) for m in range(1, 13)]
SALES_FEB_2027 = SALES_2026 + [("2027-01-20T10:00:00", 30.0), ("2027-02-03T10:00:00", 12.0), ("2027-02-10T10:00:00", 25.0)]
GOALS_2026 = {
    "annual_goals": {"2026": {"ca_target": 10000.0, "benef_target": 6000.0, "qty_target": 950}},
    "long_term_goal": {"monthly_benef_target": 1500.0, "deadline": "2028-12-31"},
}


def _texts(at):
    raw = " ".join(str(element.value) for element in at.markdown) + " " + " ".join(str(e.value) for e in at.info)
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.S)
    raw = html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\u202f", " ").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", raw)


def _md5(path):
    with open(path, "rb") as handle:
        return hashlib.md5(handle.read()).hexdigest()


class YearRolloverTests(unittest.TestCase):
    def _run(self, root, now, view, sales):
        at = AppTest.from_string(SCRIPT, default_timeout=60)
        at.session_state["_root"] = root
        at.session_state["_now"] = now
        at.session_state["_sales"] = sales
        at.session_state[stats.STATS_VIEW_STATE_KEY] = view
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def test_performance_new_year_without_sales_has_clear_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = self._run(tmp, "2027-01-05T09:00:00", "Performance", SALES_2026)
            groups = at.get("button_group")
            self.assertEqual(_option_labels(groups[1]), ["2027", "2026"])  # 2027 proposée et choisie par défaut
            text = _texts(at)
            self.assertIn("Aucune vente enregistrée en 2027 pour le moment", text)
            self.assertIn("Choisis 2026", text)
            self.assertNotIn("N/A", text)
            self.assertNotIn("Coût d'achat inconnu", text)
            self.assertEqual(len(at.get("plotly_chart")), 0)  # pas de graphique vide
            self.assertIn("Années précédentes", [e.label for e in at.expander])
            groups[1].set_value("2026").run()
            self.assertFalse(at.exception)
            text = _texts(at)
            self.assertIn("Chiffre d'affaires 2026", text)
            self.assertNotIn("à ce jour", text)
            self.assertNotIn("Aucune vente enregistrée en", text)
            self.assertGreaterEqual(len(at.get("plotly_chart")), 1)

    def test_performance_with_few_sales_in_new_year_compares_same_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = self._run(tmp, "2027-02-15T09:00:00", "Performance", SALES_FEB_2027)
            text = _texts(at)
            self.assertIn("Chiffre d'affaires 2027 à ce jour", text)
            self.assertIn("vs 2026", text)
            self.assertNotIn("Aucune vente enregistrée en", text)

    def test_performance_current_year_with_sales_unchanged_when_only_one_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = self._run(tmp, "2026-12-31T20:00:00", "Performance", SALES_2026)
            self.assertEqual(len(at.get("button_group")), 1)  # une seule année : pas de sélecteur
            self.assertIn("Chiffre d'affaires 2026 à ce jour", _texts(at))

    def test_previous_years_expander_filled_after_simulated_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            counters = os.path.join(tmp, "counters.json")
            with open(counters, "w", encoding="utf-8") as handle:
                json.dump({"main_brocante": {"label": "Main propre & Brocante", "init_ca": 0.0, "start_date": "2026-01-01", "year": "2026"},
                           "_archive": {"last_reset_year": 2026, "years": {}}}, handle)
            self._run(tmp, "2027-01-05T09:00:00", "Performance", SALES_2026)
            with open(counters, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["_archive"]["last_reset_year"], 2027)
            self.assertIn("2026", saved["_archive"]["years"])

    def test_forecast_new_year_without_goals_or_sales(self):
        with tempfile.TemporaryDirectory() as tmp:
            goals = os.path.join(tmp, "monthly_goals.json")
            with open(goals, "w", encoding="utf-8") as handle:
                json.dump(GOALS_2026, handle)
            before = _md5(goals)
            at = self._run(tmp, "2027-01-05T09:00:00", "Prévisions", SALES_2026)
            text = _texts(at)
            self.assertIn("Objectifs 2027", text)
            self.assertIn("Aucun objectif annuel défini pour 2027", text)
            self.assertNotIn("6 000", text)  # l'objectif de bénéfice 2026 n'est pas réutilisé
            self.assertNotIn("950", text)
            self.assertIn("Indicatif", text)  # projection de fin d'année sans mois complet
            self.assertIn("Moyenne glissante sur 12 mois", text)
            self.assertIn("Janvier 2027", text)  # mois en cours exclu de la moyenne
            self.assertIn("Bénéfice cumulé depuis le début", text)
            self.assertEqual([e.label for e in at.expander].count("Définir"), 3)
            self.assertEqual(_md5(goals), before)  # l'affichage seul n'écrit pas les objectifs annuels

    def test_forecast_year_end_with_2027_goals_defined(self):
        with tempfile.TemporaryDirectory() as tmp:
            goals = os.path.join(tmp, "monthly_goals.json")
            payload = json.loads(json.dumps(GOALS_2026))
            payload["annual_goals"]["2027"] = {"ca_target": 12000.0, "benef_target": 7000.0, "qty_target": 1000}
            with open(goals, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            at = self._run(tmp, "2027-02-15T09:00:00", "Prévisions", SALES_FEB_2027)
            text = _texts(at)
            self.assertIn("12 000", text)
            self.assertNotIn("6 000", text)
            self.assertIn("Fin d'année 2027 estimée", text)

    def test_monthly_view_new_year_without_sales(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = self._run(tmp, "2027-01-05T09:00:00", "Mensuel", SALES_2026)
            text = _texts(at)
            self.assertIn("JANVIER 2027", text)
            self.assertIn("Aucune carte vendue", text)
            self.assertIn("Objectifs de janvier", text)
            self.assertIn("Tes records", text)
            with open(os.path.join(tmp, "monthly_goals.json"), encoding="utf-8") as handle:
                created = json.load(handle)
            self.assertIn("2027-01", created)  # objectif du nouveau mois créé à partir du mois précédent
            self.assertEqual(created["2027-01"]["based_on"], "2026-12")

    def test_consecutive_months_streak_continues_across_year_change(self):
        stat = lambda b: {"ca": b, "benef": b, "qty": 1.0}
        monthly = {"2026-10": stat(50.0), "2026-11": stat(60.0), "2026-12": stat(70.0), "2027-01": stat(80.0), "2027-02": stat(5.0)}
        goals = {m: {"benef_target": 40.0} for m in monthly}
        self.assertEqual(stats._consecutive_months_above_goal(monthly, goals, datetime(2027, 2, 15)), (4, 4))
        goals["2026-12"]["benef_target"] = 999.0  # mois raté : la série repart à zéro au passage d'année
        self.assertEqual(stats._consecutive_months_above_goal(monthly, goals, datetime(2027, 2, 15)), (1, 2))

    def test_adding_2027_goals_leaves_2026_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "monthly_goals.json")
            seed = dict(GOALS_2026)
            seed["2026-10"] = {"ca_target": 500.0, "qty_target": 50, "benef_target": 250.0, "auto_generated": False}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(seed, handle)

            def write(target, data, indent=None):
                with open(target, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)

            values = {"ca_target": 12000.0, "benef_target": 7000.0, "qty_target": 1000.0}
            self.assertTrue(stats._save_goal_updates(path, write, annual=(2027, values), long_term=2000.0, long_term_deadline=date(2029, 12, 31)))
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["annual_goals"]["2026"], seed["annual_goals"]["2026"])
            self.assertEqual(saved["annual_goals"]["2027"], values)
            self.assertEqual(saved["2026-10"], seed["2026-10"])
            self.assertEqual(saved["long_term_goal"]["monthly_benef_target"], 2000.0)
            self.assertEqual(stats._annual_goal_for_year(saved, 2026)["ca_target"], 10000.0)
            self.assertIsNone(stats._annual_goal_for_year(seed, 2027))


if __name__ == "__main__":
    unittest.main()

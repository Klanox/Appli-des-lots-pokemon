"""Tests du reset annuel des compteurs et de l'archive « Années précédentes ».

Aucune donnée réelle : tout est calculé sur des fixtures temporaires, avec une date du jour simulée.
Le counters.json réel de la racine n'est jamais écrit (le test vérifie son md5 avant/après).
"""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from services import counters_archive_service as archive_service
from services.counters_archive_service import (
    ARCHIVE_KEY,
    archived_years_summary,
    counters_need_reset,
    ensure_yearly_reset,
)
from ui.pages import statistics as stats
from ui.pages.counters import collect_channel_counter_totals
from utils import safe_write_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_JSON = ("counters.json", "data.json", "lots_archives.json", "monthly_goals.json")


def _md5(path):
    with open(path, "rb") as handle:
        return hashlib.md5(handle.read()).hexdigest()


def base_counters():
    """Même forme que le counters.json réel (copie anonyme)."""
    return {
        "main_brocante": {"start_date": "2026-05-16", "label": "Main propre & Brocante", "reset_mode": "manual", "init_ca": 1831.0,
                          "start_datetime": "2026-05-16T19:33:48.082474", "year": "2026"},
        "dexify": {"year": "2026", "label": "Dexify_TCG", "reset_mode": "yearly", "init_ca": 1230.5, "start_date": "2026-05-16",
                   "start_datetime": "2026-05-16T19:33:48.082474"},
        "pokedeal": {"year": "2026", "label": "Pokédeal", "reset_mode": "yearly", "init_ca": 1909.1, "start_date": "2026-05-16",
                     "start_datetime": "2026-05-16T19:33:48.082474"},
        "choppetacarte": {"year": "2026", "start_date": "2026-01-01", "label": "ChoppeTaCarte", "reset_mode": "manual"},
    }


def _sale(canal, day, price, quantity=1, **extra):
    row = {"canal": canal, "date": day, "price": price, "quantity": quantity, "card_name": "Carte"}
    row.update(extra)
    return row


def base_lots():
    return [
        {"nom": "Lot A", "ventes": [
            _sale("Main propre", "2025-12-31T10:00:00", 99.0),            # année précédente : ignorée
            _sale("Main propre", "2026-06-01T10:00:00", 10.0),
            _sale("Dexify", "2026-06-03T10:00:00", 1000.0, is_lot_sale=True),  # vente initiale : ignorée par les compteurs
            _sale("Dexify", "2026-06-04T10:00:00", 500.0, is_exchange_benefit=True),  # bénéfice d'échange : ignoré
            _sale("Main propre", "2027-01-05T10:00:00", 7.0),             # année suivante
        ], "cards": [
            {"name": "X", "sold_entries": [
                _sale("Brocante", "2026-09-10T10:00:00", 20.0, quantity=2),
                _sale("Dexify", "2026-05-10T10:00:00", 50.0),               # avant la date de départ du compteur
                _sale("Dexify", "2026-06-02T10:00:00", 30.0),
                _sale("Dexify", "2026-12-31T23:00:00", 15.0),               # dernier jour : inclus
                _sale("Dexify", "2027-01-02T09:00:00", 8.0),                # 2027
                _sale("Pokédeal", "2026-07-01T10:00:00", 40.0, quantity=2),
                _sale("Choppe Ta Carte", "2026-02-01T10:00:00", 5.0),       # le compteur démarre le 01/01
                _sale("Pokédeal", "2027-03-01T10:00:00", 12.0),
            ]},
        ]},
    ]


class Recorder:
    """write_func de test : mémorise chaque écriture."""

    def __init__(self):
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(copy.deepcopy(payload))


class YearlyResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = {name: _md5(os.path.join(ROOT, name)) for name in REAL_JSON if os.path.exists(os.path.join(ROOT, name))}

    @classmethod
    def tearDownClass(cls):
        after = {name: _md5(os.path.join(ROOT, name)) for name in cls.before}
        assert after == cls.before, "un JSON réel de la racine a été modifié par les tests"

    def test_first_pass_sets_marker_without_archiving(self):
        counters, writer = base_counters(), Recorder()
        result = ensure_yearly_reset(counters, base_lots(), date(2026, 10, 13), writer)
        self.assertTrue(result["initialized"])
        self.assertEqual(result["archived_years"], [])
        self.assertEqual(len(writer.payloads), 1)
        saved = writer.payloads[0]
        self.assertEqual(saved[ARCHIVE_KEY], {"last_reset_year": 2026, "years": {}})
        for key in ("main_brocante", "dexify", "pokedeal", "choppetacarte"):
            self.assertEqual(saved[key], base_counters()[key], key)  # compteurs inchangés
        self.assertNotIn(ARCHIVE_KEY, counters)  # l'entrée n'est pas modifiée

    def test_lots_are_not_loaded_when_nothing_is_archived(self):
        def boom():
            raise AssertionError("lots chargés pour rien")
        ensure_yearly_reset(base_counters(), boom, date(2026, 10, 13), Recorder())

    def test_nothing_happens_during_the_same_year(self):
        writer = Recorder()
        first = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), writer)
        again = ensure_yearly_reset(first["counters"], base_lots(), date(2026, 12, 31), writer)
        self.assertFalse(again["changed"])
        self.assertEqual(len(writer.payloads), 1)
        self.assertFalse(counters_need_reset(first["counters"], date(2026, 12, 31)))
        self.assertTrue(counters_need_reset(first["counters"], date(2027, 1, 1)))

    def test_rollover_2026_to_2027_archives_then_resets_in_one_write(self):
        writer = Recorder()
        start = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), writer)["counters"]
        writer.payloads.clear()
        result = ensure_yearly_reset(start, base_lots(), date(2027, 1, 1), writer)
        self.assertEqual(result["archived_years"], [2026])
        self.assertIsNone(result["error"])
        self.assertEqual(len(writer.payloads), 1, "archive + reset doivent partir dans une seule écriture")
        saved = writer.payloads[0]
        self.assertEqual(saved, result["counters"])

        entry = saved[ARCHIVE_KEY]["years"]["2026"]
        self.assertEqual(entry["reset_on"], "2027-01-01")
        ch = entry["channels"]
        # Main propre & Brocante : ventes de l'année civile 2026, sans CA de départ.
        self.assertEqual((ch["main_brocante"]["ca"], ch["main_brocante"]["nb"]), (30.0, 3))
        self.assertEqual(ch["main_brocante"]["init_ca"], 1831.0)
        # Dexify : ventes du 16/05 au 31/12 (30 + 15), hors vente initiale, bénéfice d'échange et 2027, + CA de départ.
        self.assertEqual((ch["dexify"]["ca_ventes"], ch["dexify"]["nb"]), (45.0, 2))
        self.assertEqual(ch["dexify"]["ca"], 1275.5)
        self.assertEqual((ch["dexify"]["init_ca"], ch["dexify"]["start_date"]), (1230.5, "2026-05-16"))
        self.assertEqual((ch["pokedeal"]["ca"], ch["pokedeal"]["nb"]), (1949.1, 2))
        # ChoppeTaCarte : alias « Choppe Ta Carte » reconnu, compteur depuis le 01/01.
        self.assertEqual((ch["choppetacarte"]["ca"], ch["choppetacarte"]["nb"]), (5.0, 1))

        # Reset : init_ca à 0, début au 01/01/2027, start_datetime sans « T », année à jour.
        for key in ("dexify", "pokedeal"):
            self.assertEqual(saved[key]["init_ca"], 0.0)
            self.assertEqual(saved[key]["start_date"], "2027-01-01")
            self.assertEqual(saved[key]["start_datetime"], "2027-01-01")
            self.assertNotIn("T", saved[key]["start_datetime"])
            self.assertEqual(saved[key]["year"], "2027")
        self.assertEqual(saved["choppetacarte"]["start_date"], "2027-01-01")
        self.assertNotIn("start_datetime", saved["choppetacarte"])  # jamais ajouté
        self.assertEqual(saved["main_brocante"]["year"], "2027")
        self.assertEqual(saved[ARCHIVE_KEY]["last_reset_year"], 2027)

    def test_reset_counters_really_restart_from_zero_in_the_new_year(self):
        """Le compteur 2027 ne reprend pas les ventes de 2026 (start_datetime ne doit plus primer)."""
        writer = Recorder()
        counters = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), writer)["counters"]
        counters = ensure_yearly_reset(counters, base_lots(), date(2027, 1, 1), writer)["counters"]
        states = {key: {"start_date": counters[key]["start_date"], "start_datetime": counters[key].get("start_datetime", counters[key]["start_date"])}
                  for key in ("dexify", "pokedeal", "choppetacarte")}
        totals = collect_channel_counter_totals(base_lots(), vinted_states=states, main_year=counters["main_brocante"]["year"])
        self.assertEqual(totals["dexify"], {"nb": 1, "ca": 8.0})      # seulement la vente du 02/01/2027
        self.assertEqual(totals["pokedeal"], {"nb": 1, "ca": 12.0})
        self.assertEqual(totals["choppetacarte"], {"nb": 0, "ca": 0.0})
        self.assertEqual(totals["main_brocante"], {"nb": 1, "ca": 7.0})

    def test_repeated_calls_are_idempotent(self):
        writer = Recorder()
        counters = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), writer)["counters"]
        first = ensure_yearly_reset(counters, base_lots(), date(2027, 1, 1), writer)
        writes_after_first = len(writer.payloads)
        for day in (date(2027, 1, 1), date(2027, 6, 1), date(2027, 12, 31)):
            again = ensure_yearly_reset(first["counters"], base_lots(), day, writer)
            self.assertFalse(again["changed"])
            self.assertEqual(again["counters"], first["counters"])
        self.assertEqual(len(writer.payloads), writes_after_first)

    def test_app_closed_for_two_years_archives_each_missed_year(self):
        writer = Recorder()
        counters = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), writer)["counters"]
        writer.payloads.clear()
        result = ensure_yearly_reset(counters, base_lots(), date(2028, 3, 2), writer)
        self.assertEqual(result["archived_years"], [2026, 2027])
        self.assertEqual(len(writer.payloads), 1)
        years = result["counters"][ARCHIVE_KEY]["years"]
        self.assertEqual(sorted(years), ["2026", "2027"])
        self.assertEqual(years["2026"]["channels"]["dexify"]["ca"], 1275.5)
        # 2027 : le CA de départ est reparti à 0 et la fenêtre commence le 01/01/2027.
        y27 = years["2027"]["channels"]
        self.assertEqual((y27["dexify"]["init_ca"], y27["dexify"]["start_date"]), (0.0, "2027-01-01"))
        self.assertEqual((y27["dexify"]["ca"], y27["dexify"]["nb"]), (8.0, 1))
        self.assertEqual((y27["pokedeal"]["ca"], y27["pokedeal"]["nb"]), (12.0, 1))
        self.assertEqual((y27["main_brocante"]["ca"], y27["main_brocante"]["nb"]), (7.0, 1))
        self.assertEqual(result["counters"][ARCHIVE_KEY]["last_reset_year"], 2028)
        self.assertEqual(result["counters"]["dexify"]["start_date"], "2028-01-01")
        self.assertEqual(result["counters"]["dexify"]["year"], "2028")

    def test_write_failure_means_no_reset(self):
        start = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), Recorder())["counters"]
        snapshot = copy.deepcopy(start)

        def failing_write(payload):
            raise OSError("disque plein")

        result = ensure_yearly_reset(start, base_lots(), date(2027, 1, 1), failing_write)
        self.assertIn("disque plein", result["error"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["counters"], snapshot)
        self.assertEqual(start, snapshot)  # entrée jamais modifiée
        self.assertNotIn("2026", start[ARCHIVE_KEY]["years"])
        self.assertEqual(start["dexify"]["init_ca"], 1230.5)

    def test_real_atomic_write_failure_leaves_the_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "counters.json")
            counters = base_counters()
            counters[ARCHIVE_KEY] = {"last_reset_year": 2026, "years": {}}
            safe_write_json(path, counters)
            before = _md5(path)
            with patch("utils.os.replace", side_effect=OSError("remplacement impossible")):
                result = ensure_yearly_reset(counters, base_lots(), date(2027, 1, 1), lambda payload: safe_write_json(path, payload))
            self.assertIsNotNone(result["error"])
            self.assertEqual(_md5(path), before)
            self.assertEqual(sorted(os.listdir(tmp)), ["counters.json"])  # pas de fichier temporaire oublié
            # Une fois l'écriture rétablie, le reset a bien lieu (rien n'a été perdu).
            ok = ensure_yearly_reset(counters, base_lots(), date(2027, 1, 1), lambda payload: safe_write_json(path, payload))
            self.assertEqual(ok["archived_years"], [2026])
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), ok["counters"])

    def test_computation_error_means_no_reset(self):
        counters = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), Recorder())["counters"]

        def broken_lots():
            raise RuntimeError("data.json illisible")

        writer = Recorder()
        result = ensure_yearly_reset(counters, broken_lots, date(2027, 1, 1), writer)
        self.assertIn("illisible", result["error"])
        self.assertEqual(writer.payloads, [])
        self.assertEqual(result["counters"], counters)

    def test_main_brocante_archive_uses_the_calendar_year_not_the_displayed_year(self):
        counters = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), Recorder())["counters"]
        counters["main_brocante"]["year"] = "2025"  # l'utilisateur regarde 2025 dans le sélecteur
        result = ensure_yearly_reset(counters, base_lots(), date(2027, 1, 1), Recorder())
        main = result["counters"][ARCHIVE_KEY]["years"]["2026"]["channels"]["main_brocante"]
        self.assertEqual((main["ca"], main["nb"]), (30.0, 3))
        self.assertEqual(result["counters"]["main_brocante"]["year"], "2027")

    def test_an_existing_archive_is_never_overwritten(self):
        counters = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), Recorder())["counters"]
        sentinel = {"reset_on": "2027-01-01", "channels": {"dexify": {"label": "Dexify_TCG", "ca": 1.0, "nb": 1}}}
        counters[ARCHIVE_KEY]["years"]["2026"] = sentinel
        result = ensure_yearly_reset(counters, base_lots(), date(2027, 1, 1), Recorder())
        self.assertEqual(result["counters"][ARCHIVE_KEY]["years"]["2026"], sentinel)
        self.assertEqual(result["counters"]["dexify"]["start_date"], "2027-01-01")  # le reset a quand même lieu

    def test_start_in_the_year_before_is_clamped_to_january_first(self):
        counters = base_counters()
        counters["pokedeal"].update({"start_date": "2025-03-01", "start_datetime": "2025-03-01T08:00:00", "init_ca": 0.0})
        counters[ARCHIVE_KEY] = {"last_reset_year": 2026, "years": {}}
        lots = [{"ventes": [_sale("Pokédeal", "2025-11-01T10:00:00", 99.0), _sale("Pokédeal", "2026-01-01T00:00:00", 3.0)]}]
        result = ensure_yearly_reset(counters, lots, date(2027, 1, 1), Recorder())
        self.assertEqual(result["counters"][ARCHIVE_KEY]["years"]["2026"]["channels"]["pokedeal"]["ca"], 3.0)

    def test_corrupted_marker_is_reinitialised_without_archiving(self):
        counters = base_counters()
        counters[ARCHIVE_KEY] = {"last_reset_year": "n'importe quoi", "years": "oups"}
        result = ensure_yearly_reset(counters, base_lots(), date(2027, 5, 1), Recorder())
        self.assertTrue(result["initialized"])
        self.assertEqual(result["counters"][ARCHIVE_KEY], {"last_reset_year": 2027, "years": {}})
        self.assertEqual(result["counters"]["dexify"]["init_ca"], 1230.5)

    def test_empty_counters_file_gets_a_marker_only(self):
        result = ensure_yearly_reset({}, [], date(2026, 10, 13), Recorder())
        self.assertEqual(result["counters"], {ARCHIVE_KEY: {"last_reset_year": 2026, "years": {}}})

    def test_archive_key_is_never_read_as_a_channel(self):
        """Aucun canal ne s'appelle _archive : le résumé et les compteurs l'ignorent."""
        self.assertNotIn(ARCHIVE_KEY, archive_service.vinted_counter_keys())
        self.assertEqual(archived_years_summary({ARCHIVE_KEY: {"years": {}}}), [])
        self.assertEqual(archived_years_summary({}), [])
        self.assertEqual(archived_years_summary(None), [])


class CollectTotalsSignatureTests(unittest.TestCase):
    STATES = {key: {"start_date": "2026-01-01", "start_datetime": "2026-01-01"} for key in ("dexify", "pokedeal", "choppetacarte")}

    def test_end_date_is_optional_and_inclusive(self):
        lots = [{"ventes": [_sale("Dexify", "2026-06-01T10:00:00", 10.0), _sale("Dexify", "2026-12-31T23:59:00", 5.0), _sale("Dexify", "2027-01-01T00:00:00", 100.0)]}]
        unbounded = collect_channel_counter_totals(lots, vinted_states=self.STATES, main_year="2026")
        bounded = collect_channel_counter_totals(lots, vinted_states=self.STATES, main_year="2026", end_date="2026-12-31")
        self.assertEqual(unbounded["dexify"], {"nb": 3, "ca": 115.0})
        self.assertEqual(bounded["dexify"], {"nb": 2, "ca": 15.0})


STATS_SCRIPT = '''
import json, os
from datetime import datetime
import streamlit as st
from ui.pages.statistics import render_statistics_page

root = st.session_state["_tmp_root"]
year = datetime.now().year
lots = [{"nom": "Lot %d" % y, "prix_achat_reel": 50.0, "date_achat": "%d-02-01T10:00:00" % y, "cards": [],
         "ventes": [{"date": "%d-03-05T10:00:00" % y, "price": 100.0 + y - 2000, "quantity": 3, "canal": "Dexify", "card_name": "Carte"}]}
        for y in (year - 1, year)]
archives_path = os.path.join(root, "lots_archives.json")
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
    monthly_goals_path=os.path.join(root, "monthly_goals.json"),
    stock_history_path=os.path.join(root, "stock_value_history.json"),
)
'''

COUNTERS_SCRIPT = '''
import json, os
import streamlit as st
from ui.pages.counters import render_counters_page

root = st.session_state["_tmp_root"]
os.chdir(root)  # la page lit counters.json / lots_archives.json dans le dossier courant

def safe_write(path, data, indent=None):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)

render_counters_page(
    ld_func=lambda: {"lots": [{"ventes": [{"canal": "Dexify", "date": "%d-06-01T10:00:00" % (datetime_year - 1), "price": 12.0, "quantity": 1}]}]},
    safe_write_json_func=safe_write,
    canal_key_func=lambda value: value,
)
'''


def _texts(at):
    return " ".join(str(element.value) for element in at.markdown)


class PreviousYearsViewTests(unittest.TestCase):
    NOW = datetime(2026, 10, 13, 12, 0)

    def _archive(self):
        counters = ensure_yearly_reset(base_counters(), base_lots(), date(2026, 10, 13), Recorder())["counters"]
        return ensure_yearly_reset(counters, base_lots(), date(2027, 1, 1), Recorder())["counters"]

    def test_empty_message_uses_the_current_year(self):
        html_2026 = stats._previous_years_html([], [], datetime(2026, 10, 13))
        self.assertIn("Aucune année archivée pour l'instant", html_2026)
        self.assertIn("Les compteurs de 2026 seront archivés au 1er janvier 2027", html_2026)
        self.assertIn("Les compteurs de 2027 seront archivés au 1er janvier 2028", stats._previous_years_html([], [], datetime(2027, 3, 1)))

    def test_filled_html_shows_year_sales_figures_and_archived_channels(self):
        rows = [
            {"month": "2026-03", "date": datetime(2026, 3, 5), "price": 100.0, "quantity": 3, "benef": 40.0, "cost": 60.0, "lot": "L"},
            {"month": "2025-03", "date": datetime(2025, 3, 5), "price": 7.0, "quantity": 1, "benef": 1.0, "cost": 6.0, "lot": "L"},
        ]
        page = stats._previous_years_html(archived_years_summary(self._archive()), rows, datetime(2027, 1, 1))
        self.assertIn(">2026<", page)
        self.assertIn("Compteurs archivés au 01/01/2027", page)
        self.assertIn("100 €", page.replace(" ", " ").replace("\xa0", " "))   # CA de l'année calculé depuis les ventes
        self.assertIn("Dexify_TCG", page)
        flat = page.replace("\u202f", " ").replace("\xa0", " ")
        self.assertIn("1 275,50 €", flat)
        self.assertIn("1 949,10 €", flat)
        self.assertIn("Pokédeal", page)
        self.assertIn("ChoppeTaCarte", page)
        self.assertIn("Main propre &amp; Brocante", page)
        self.assertNotIn("Aucune année archivée", page)

    def test_years_are_listed_from_the_most_recent(self):
        counters = ensure_yearly_reset(self._archive(), base_lots(), date(2028, 6, 1), Recorder())["counters"]
        self.assertEqual([item["year"] for item in archived_years_summary(counters)], [2027, 2026])

    def test_performance_view_shows_the_empty_message_when_nothing_is_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            at = AppTest.from_string(STATS_SCRIPT, default_timeout=60)
            at.session_state["_tmp_root"] = tmp
            at.session_state[stats.STATS_VIEW_STATE_KEY] = "Performance"
            at.run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            self.assertIn("Années précédentes", [e.label for e in at.expander])
            year = datetime.now().year
            self.assertIn(f"Les compteurs de {year} seront archivés au 1er janvier {year + 1}", _texts(at))
            self.assertFalse(os.path.exists(os.path.join(tmp, "counters.json")), "Statistiques ne crée jamais counters.json")

    def test_performance_view_runs_the_reset_and_lists_the_archived_year(self):
        year = datetime.now().year
        with tempfile.TemporaryDirectory() as tmp:
            counters = base_counters()
            for state in counters.values():
                state.update({"year": str(year - 1), "start_date": f"{year - 1}-01-01"})
                state.pop("start_datetime", None)
            counters[ARCHIVE_KEY] = {"last_reset_year": year - 1, "years": {}}
            path = os.path.join(tmp, "counters.json")
            safe_write_json(path, counters)
            at = AppTest.from_string(STATS_SCRIPT, default_timeout=60)
            at.session_state["_tmp_root"] = tmp
            at.session_state[stats.STATS_VIEW_STATE_KEY] = "Performance"
            at.run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved[ARCHIVE_KEY]["last_reset_year"], year)
            self.assertIn(str(year - 1), saved[ARCHIVE_KEY]["years"])
            self.assertEqual(saved["dexify"]["start_date"], f"{year}-01-01")
            page = _texts(at)
            self.assertIn(f">{year - 1}<", page)
            self.assertNotIn("Aucune année archivée", page)
            # Un second rendu ne réécrit rien (idempotent).
            before = _md5(path)
            at.run()
            self.assertEqual(_md5(path), before)

    def test_counters_page_runs_the_reset_and_keeps_the_archive_when_saving(self):
        year = datetime.now().year
        script = COUNTERS_SCRIPT.replace("datetime_year", str(year))
        with tempfile.TemporaryDirectory() as tmp:
            counters = base_counters()
            for state in counters.values():
                state.update({"year": str(year - 1), "start_date": f"{year - 1}-01-01"})
                state.pop("start_datetime", None)
            counters[ARCHIVE_KEY] = {"last_reset_year": year - 1, "years": {}}
            path = os.path.join(tmp, "counters.json")
            safe_write_json(path, counters)
            cwd = os.getcwd()
            try:
                at = AppTest.from_string(script, default_timeout=60)
                at.session_state["_tmp_root"] = tmp
                at.run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                with open(path, encoding="utf-8") as handle:
                    saved = json.load(handle)
                self.assertEqual(saved[ARCHIVE_KEY]["last_reset_year"], year)
                self.assertEqual(saved[ARCHIVE_KEY]["years"][str(year - 1)]["channels"]["dexify"]["nb"], 1)
                self.assertTrue(any("archivés" in str(info.value) for info in at.info))
                # « Sauvegarder les données de départ » réécrit counters.json : l'archive doit survivre.
                at.button(key="save_counter_inits").click().run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                with open(path, encoding="utf-8") as handle:
                    saved_again = json.load(handle)
                self.assertEqual(saved_again[ARCHIVE_KEY], saved[ARCHIVE_KEY])
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()

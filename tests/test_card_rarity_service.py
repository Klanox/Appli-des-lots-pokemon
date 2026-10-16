"""Recuperation de la rarete (TCGdex) : tests HORS LIGNE avec des reponses simulees et des fichiers temporaires.

Aucun reseau, aucun JSON metier reel : data/drops sont des dictionnaires fabriques, le cache et les sauvegardes
vivent dans un dossier temporaire.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest

from services import card_rarity_service as rarity


def stock(*cards):
    return {"lots": [{"lot_uid": "lot1", "cards": [dict(c) for c in cards]}]}


def drop(*uids):
    return {"drops": [{"id": "d1", "cards": [{"card_uid": uid, "name": uid} for uid in uids]}]}


CARDS = (
    {"card_uid": "u1", "id": "sv08-160", "name": "Pikachu", "number": "160", "rarity": ""},
    {"card_uid": "u2", "id": "sv08-190", "name": "Dracaufeu", "number": "190", "rarity": "Sans Rareté"},
    {"card_uid": "u3", "id": "sv04.5-171", "name": "Courrousinge", "number": "171", "rarity": ""},
    {"card_uid": "u4", "id": "swsh1-001", "name": "Stock seul", "number": "1", "rarity": ""},
    {"card_uid": "u5", "id": "", "name": "Sans id", "number": "5", "rarity": ""},
    {"card_uid": "u6", "id": "base1-4", "name": "Rarete connue", "number": "4", "rarity": "Rare Holo"},
)

TCGDEX = {
    "sv08-160": {"id": "sv08-160", "name": "Pikachu", "rarity": "Illustration rare", "category": "Pokémon"},
    "sv08-190": {"id": "sv08-190", "name": "Dracaufeu", "rarity": "Hyper rare", "category": "Pokémon"},
    "sv04.5-171": {"id": "sv04.5-171", "name": "Courrousinge", "rarity": "Shiny Rare", "category": "Pokémon"},
    "swsh1-001": {"id": "swsh1-001", "name": "Stock seul", "rarity": "Commune", "category": "Pokémon"},
}


class FakeTcgdex:
    def __init__(self, payloads=None, fail=(), not_found=()):
        self.payloads, self.fail, self.not_found = payloads or TCGDEX, set(fail), set(not_found)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        card_id = url.rsplit("/", 1)[1]
        if card_id in self.fail:
            return 0, None
        if card_id in self.not_found or card_id not in self.payloads:
            return 404, None
        return 200, self.payloads[card_id]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        self.cache = os.path.join(self.dir, ".cache", "cards_rarity_cache.json")
        self.backups = os.path.join(self.dir, "backups")
        self.journal = os.path.join(self.dir, "logs", "journal.jsonl")

    def run_batch(self, queue, http, **kwargs):
        return rarity.run_batch(queue, path=self.cache, backup_dir=self.backups, journal_path=self.journal,
                                http_get=http, sleep=lambda s: None, interval=0, max_seconds=60, **kwargs)

    def entries(self):
        return rarity.read_cache_file(self.cache)["cards"]


class QueueTests(Base):
    def test_drop_first_then_stock_and_exclusions(self):
        data, drops = stock(*CARDS), drop("u3", "u1", "u5")
        queue = rarity.build_queue(data, drops, {}, include_stock=True)
        self.assertEqual(queue["drop"], ["sv04.5-171", "sv08-160"])
        self.assertEqual(queue["stock"], ["sv08-190", "swsh1-001"])  # base1-4 a deja une rarete propre
        self.assertEqual(queue["without_id"], 1)
        self.assertEqual(queue["own_rarity"], 1)

    def test_stock_is_optional(self):
        queue = rarity.build_queue(stock(*CARDS), drop("u3"), {}, include_stock=False)
        self.assertEqual(queue["stock"], [])
        self.assertEqual(len(queue["stock_all"]), 3)

    def test_done_cards_are_not_requested_again(self):
        entries = {"sv04.5-171": {"status": "ok", "rarity": "Shiny Rare"}, "sv08-160": {"status": "not_found"},
                   "sv08-190": {"status": "error"}}
        queue = rarity.build_queue(stock(*CARDS), drop("u3", "u1", "u2"), entries)
        self.assertEqual(queue["drop"], ["sv08-190"])
        self.assertEqual(queue["already_done"], 2)

    def test_real_world_counts_are_distinct_ids(self):
        twins = [dict(CARDS[0], card_uid="u1b")]
        queue = rarity.build_queue(stock(CARDS[0], *twins), drop("u1", "u1b"), {})
        self.assertEqual(queue["drop"], ["sv08-160"])


class FetchTests(Base):
    def test_batch_writes_cache_with_backup_and_journal(self):
        os.makedirs(os.path.dirname(self.cache))
        rarity.save_cache({"cards": {"old-1": {"status": "ok", "rarity": "Rare"}}}, path=self.cache, backup=False)
        http = FakeTcgdex()
        stats = self.run_batch(["sv08-160", "sv08-190", "unknown-1"], http)
        self.assertEqual((stats["ok"], stats["not_found"], stats["errors"], stats["stopped"]), (2, 1, 0, "termine"))
        entries = self.entries()
        self.assertEqual(entries["sv08-160"]["rarity"], "Illustration rare")
        self.assertEqual(entries["sv08-190"]["rarity"], "Hyper rare")
        self.assertEqual(entries["unknown-1"]["status"], "not_found")
        self.assertEqual(entries["old-1"]["rarity"], "Rare", "les entrees existantes sont conservees")
        self.assertEqual(len(os.listdir(self.backups)), 1, "ancien cache sauvegarde avant ecriture")
        lines = [json.loads(line) for line in open(self.journal, encoding="utf-8")]
        self.assertEqual([line["event"] for line in lines], ["ok", "ok", "not_found"])
        self.assertTrue(all(url.startswith("https://api.tcgdex.net/v2/fr/cards/") for url in http.urls))

    def test_existing_rarity_is_never_replaced(self):
        rarity.save_cache({"cards": {"sv08-160": {"status": "ok", "rarity": "Rare Holo"}}}, path=self.cache, backup=False)
        stats = self.run_batch(["sv08-160"], FakeTcgdex())
        self.assertEqual(stats["written"], 0)
        self.assertEqual(self.entries()["sv08-160"]["rarity"], "Rare Holo")

    def test_resume_after_interruption_only_requests_the_rest(self):
        queue = ["sv08-160", "sv08-190", "sv04.5-171"]
        checks = iter([False, True, True])
        first = self.run_batch(queue, FakeTcgdex(), should_cancel=lambda: next(checks))
        # annulation apres la premiere carte : ce qui a ete fait est ecrit dans le cache avant de s'arreter
        self.assertEqual(first["stopped"], "annule")
        self.assertEqual(list(self.entries()), ["sv08-160"])
        http = FakeTcgdex()
        rest = rarity.build_queue(stock(*CARDS), drop("u1", "u2", "u3"), self.entries())["drop"]
        self.run_batch(rest, http)
        self.assertEqual(sorted(self.entries()), ["sv04.5-171", "sv08-160", "sv08-190"])
        self.assertEqual(len(http.urls), len(rest))

    def test_cancel_before_start_requests_nothing(self):
        http = FakeTcgdex()
        stats = self.run_batch(["sv08-160"], http, should_cancel=lambda: True)
        self.assertEqual((stats["stopped"], http.urls), ("annule", []))
        self.assertFalse(os.path.exists(self.cache))

    def test_batch_stops_on_time_budget_and_keeps_going_next_time(self):
        clock = iter(range(0, 1000))
        stats = rarity.run_batch(["sv08-160", "sv08-190", "sv04.5-171"], path=self.cache, backup_dir=self.backups,
                                 journal_path=self.journal, http_get=FakeTcgdex(), sleep=lambda s: None,
                                 interval=0, max_seconds=1.5, clock=lambda: next(clock))
        self.assertGreaterEqual(len(stats["processed"]), 1)
        self.assertLess(len(stats["processed"]), 3)
        self.assertEqual(stats["stopped"], "")

    def test_five_network_errors_in_a_row_stop_the_batch_and_are_not_cached(self):
        ids = [f"x-{i}" for i in range(8)]
        http = FakeTcgdex(fail=ids)
        stats = self.run_batch(ids, http)
        self.assertEqual(stats["stopped"], "erreurs")
        self.assertEqual(stats["errors"], rarity.MAX_CONSECUTIVE_ERRORS)
        self.assertEqual(self.entries(), {})
        self.assertEqual(len(http.urls), rarity.MAX_CONSECUTIVE_ERRORS * (rarity.MAX_RETRIES + 1))

    def test_isolated_error_is_retried_then_skipped_without_stopping(self):
        stats = self.run_batch(["sv08-160", "sv08-190"], FakeTcgdex(fail=["sv08-160"]))
        self.assertEqual((stats["ok"], stats["errors"], stats["stopped"]), (1, 1, "termine"))
        self.assertNotIn("sv08-160", self.entries())

    def test_rate_limit_sleeps_between_requests(self):
        sleeps = []
        rarity.run_batch(["sv08-160", "sv08-190"], path=self.cache, backup_dir=self.backups, journal_path=self.journal,
                         http_get=FakeTcgdex(), sleep=sleeps.append, interval=0.25, max_seconds=60)
        self.assertEqual(sleeps, [0.25, 0.25])
        self.assertGreaterEqual(rarity.MIN_INTERVAL_SECONDS, 0.2)

    def test_cache_write_is_atomic_and_leaves_no_temp_file(self):
        self.run_batch(["sv08-160"], FakeTcgdex())
        self.assertEqual(os.listdir(os.path.dirname(self.cache)), ["cards_rarity_cache.json"])

    def test_corrupt_cache_is_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache))
        with open(self.cache, "w", encoding="utf-8") as handle:
            handle.write("{pas du json")
        self.assertEqual(rarity.read_cache_file(self.cache)["cards"], {})


class BusinessFilesUntouchedTests(Base):
    def test_business_json_are_never_written(self):
        names = ("data.json", "vinted_drops.json", "lots_archives.json", "counters.json", "monthly_goals.json",
                 "cards_cache.json")
        digests = {}
        for name in names:
            path = os.path.join(self.dir, name)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"nom": name}, handle)
            digests[name] = hashlib.md5(open(path, "rb").read()).hexdigest()
        self.run_batch(["sv08-160", "sv08-190", "unknown-1"], FakeTcgdex())
        for name in names:
            self.assertEqual(hashlib.md5(open(os.path.join(self.dir, name), "rb").read()).hexdigest(), digests[name], name)


class ReportTests(Base):
    def test_report_counts_by_class_and_lists_fa_cases(self):
        entries = {
            "sv08-160": {"status": "ok", "rarity": "Illustration rare"},
            "sv08-190": {"status": "ok", "rarity": "Hyper rare"},
            "sv04.5-171": {"status": "ok", "rarity": "Shiny Rare"},
            "swsh1-001": {"status": "ok", "rarity": "Ultra Rare", "category": "Dresseur"},
        }
        report = rarity.rarity_report([c for c in CARDS if c["id"]], entries)
        self.assertEqual(report["counts"]["ar"], 1)
        self.assertEqual(report["counts"]["gold"], 1)
        self.assertEqual(report["counts"]["shiny"], 1)
        self.assertEqual(report["counts"]["fa"], 1)  # Dresseur « Ultra Rare » : FA automatique
        self.assertEqual(report["fa_cases"], [])
        self.assertEqual(report["listed_cases"], [], "une carte FA appliquée n'est ni a valider ni « Secrète / Alternative »")
        self.assertEqual([row["Décision"] for row in report["ultra_cases"]], ["FA appliqué"])

    def test_report_lists_every_ultra_rare_with_its_decision(self):
        entries = {
            "u-1": {"status": "ok", "rarity": "Ultra Rare", "category": "Pokémon", "name": "Chef-de-Fer-ex"},
            "u-2": {"status": "ok", "rarity": "Ultra Rare", "category": "Pokémon", "suffix": "V"},
            "u-3": {"status": "ok", "rarity": "Ultra Rare", "category": "Pokémon", "suffix": "GX"},
            "u-4": {"status": "ok", "rarity": "Ultra Rare", "category": "Dresseur"},
            "u-5": {"status": "ok", "rarity": "Ultra Rare", "category": "Pokémon", "suffix": "VMAX"},
            "u-6": {"status": "ok", "rarity": "Ultra Rare", "category": "Pokémon", "name": "Arceus VSTAR"},
            "u-7": {"status": "ok", "rarity": "Special illustration rare", "category": "Pokémon", "name": "Mew-ex"},
        }
        names = {"u-1": "Chef-de-Fer-ex", "u-2": "Pikachu", "u-3": "Dracaufeu", "u-4": "Larry", "u-5": "Dracaufeu",
                 "u-6": "Arceus VSTAR", "u-7": "Mew-ex"}
        cards = [{"id": cid, "card_uid": cid, "name": name, "number": "1", "rarity": ""} for cid, name in names.items()]
        report = rarity.rarity_report(cards, entries)
        decisions = {row["id"]: row["Décision"] for row in report["ultra_cases"]}
        self.assertEqual(decisions, {"u-1": "FA appliqué", "u-2": "FA appliqué", "u-3": "FA appliqué", "u-4": "FA appliqué",
                                     "u-5": "À valider (rien ajouté)", "u-6": "À valider (rien ajouté)"})
        self.assertEqual((report["counts"]["fa"], report["counts"]["fa_review"], report["counts"]["sir"]), (4, 2, 1))
        self.assertEqual(sorted(case["id"] for case in report["fa_cases"]), ["u-5", "u-6"])
        self.assertEqual(report["listed_cases"], [])

    def test_report_counts_alt_and_lists_secret_and_alternate_without_adding_anything(self):
        entries = {
            "a-1": {"status": "ok", "rarity": "Special illustration rare"},
            "a-2": {"status": "ok", "rarity": "Illustration spéciale rare"},
            "a-3": {"status": "ok", "rarity": "Secret Rare"},
            "a-4": {"status": "ok", "rarity": "Rare Alternative"},
            "a-5": {"status": "ok", "rarity": "Illustration speciale"},
        }
        cards = [{"id": f"a-{i}", "card_uid": f"u{i}", "name": f"C{i}", "number": str(i), "rarity": ""} for i in range(1, 6)]
        report = rarity.rarity_report(cards, entries)
        self.assertEqual(report["counts"]["sir"], 2)
        self.assertEqual(report["counts"]["secret"], 1)
        self.assertEqual(report["counts"]["alternate"], 1)
        self.assertEqual(sorted(case["id"] for case in report["listed_cases"]), ["a-3", "a-4"])
        self.assertEqual(report["fa_cases"], [])
        self.assertNotIn("a-5", [case["id"] for case in report["listed_cases"]])  # libelle incertain : rien
        self.assertEqual(rarity.classify_rarity("Illustration speciale"), "other")


if __name__ == "__main__":
    unittest.main()

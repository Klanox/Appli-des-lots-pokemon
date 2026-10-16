"""Section « Rareté des cartes » de Santé des données, testee avec AppTest : TCGdex simule, fichiers temporaires."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from services import card_rarity_service as rarity  # noqa: E402
from test_card_rarity_service import CARDS, FakeTcgdex, drop, stock  # noqa: E402


def rarity_script():
    import json
    import os
    import sys

    sys.path.insert(0, os.environ["RAR_ROOT"])
    from ui.pages import rarity_fetch

    base = os.environ["RAR_BASE"]

    def read(name):
        with open(os.path.join(base, name), encoding="utf-8") as handle:
            return json.load(handle)

    rarity_fetch.render_rarity_fetch(
        ld_func=lambda: read("data.json"), load_drops_func=lambda: read("vinted_drops.json"),
        interval=0, batch_seconds=0, sleep=lambda s: None,
    )


class RarityFetchUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / "data.json").write_text(json.dumps(stock(*CARDS)), encoding="utf-8")
        (self.base / "vinted_drops.json").write_text(json.dumps(drop("u1", "u2", "u3")), encoding="utf-8")
        os.environ["RAR_ROOT"], os.environ["RAR_BASE"] = str(ROOT), str(self.base)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("RAR_ROOT", "RAR_BASE")])
        self.cache = str(self.base / ".cache" / "cards_rarity_cache.json")
        for name, value in (("RARITY_CACHE_FILE", self.cache), ("BACKUP_DIR", str(self.base / "backups")),
                            ("JOURNAL_FILE", str(self.base / "logs" / "j.jsonl")), ("RETRY_BACKOFF_SECONDS", 0)):
            patcher = mock.patch.object(rarity, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.http = FakeTcgdex()
        patcher = mock.patch.object(rarity, "default_http_get", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.digests = {n: hashlib.md5((self.base / n).read_bytes()).hexdigest() for n in ("data.json", "vinted_drops.json")}

    def run_app(self):
        at = AppTest.from_function(rarity_script, default_timeout=30)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def test_button_runs_the_whole_drop_with_progress_and_report(self):
        at = self.run_app()
        button = at.button(key="rarity_fetch_start")
        self.assertEqual(button.label, "📥 Récupérer la rareté des cartes du Drop")
        self.assertEqual([m.value for m in at.metric][:1], ["3"])  # 3 cartes du Drop a recuperer
        button.click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        entries = rarity.read_cache_file(self.cache)["cards"]
        self.assertEqual(sorted(entries), ["sv04.5-171", "sv08-160", "sv08-190"])
        self.assertEqual(len(self.http.urls), 3)
        self.assertTrue(any("Terminé" in i.value for i in at.info), [i.value for i in at.info])
        self.assertTrue(any("Bilan" in m.value for m in at.markdown))
        for name, digest in self.digests.items():
            self.assertEqual(hashlib.md5((self.base / name).read_bytes()).hexdigest(), digest, name)

    def test_report_shows_the_number_of_alt_cards(self):
        self.http.payloads = dict(self.http.payloads)
        self.http.payloads["sv08-160"] = {"id": "sv08-160", "rarity": "Special illustration rare", "category": "Pokémon"}
        self.http.payloads["sv08-190"] = {"id": "sv08-190", "rarity": "Rare Alternative", "category": "Pokémon"}
        at = self.run_app()
        at.button(key="rarity_fetch_start").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        captions = [c.value for c in at.caption]
        self.assertTrue(any("1 carte(s)" in c and "« Alt »" in c for c in captions), captions)
        self.assertTrue(any("Secrètes / Alternatives" in e.label for e in at.expander), [e.label for e in at.expander])
        shown = " ".join(str(d.value) for d in at.dataframe)
        self.assertIn("Illustration spéciale rare (mot « Alt » ajouté)", shown)
        for name, digest in self.digests.items():
            self.assertEqual(hashlib.md5((self.base / name).read_bytes()).hexdigest(), digest, name)

    def test_report_shows_fa_counter_and_the_ultra_rare_table_with_decisions(self):
        self.http.payloads = dict(self.http.payloads)
        self.http.payloads["sv08-160"] = {"id": "sv08-160", "rarity": "Ultra Rare", "category": "Pokémon", "suffix": "ex"}
        self.http.payloads["sv08-190"] = {"id": "sv08-190", "rarity": "Ultra Rare", "category": "Pokémon", "suffix": "VMAX"}
        at = self.run_app()
        at.button(key="rarity_fetch_start").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        captions = [c.value for c in at.caption]
        self.assertTrue(any("1 carte(s)" in c and "« FA »" in c for c in captions), captions)
        labels = [e.label for e in at.expander]
        self.assertTrue(any("Ultra Rare" in label and "1 « FA » appliqué, 1 à valider" in label for label in labels), labels)
        self.assertTrue(any("VMAX / VSTAR" in label for label in labels), labels)
        self.assertFalse(any("Secrètes / Alternatives" in label for label in labels), labels)  # aucune Secrète ici
        shown = " ".join(str(d.value) for d in at.dataframe)
        self.assertIn("FA appliqué", shown)
        self.assertIn("À valider (rien ajouté)", shown)
        for name, digest in self.digests.items():
            self.assertEqual(hashlib.md5((self.base / name).read_bytes()).hexdigest(), digest, name)

    def test_rest_of_stock_is_optional(self):
        at = self.run_app()
        at.checkbox(key="rarity_fetch_include_stock").check().run()
        at.button(key="rarity_fetch_start").click().run()
        self.assertEqual(len(self.http.urls), 4)  # 3 du Drop + 1 du reste du stock (sans id et rarete propre exclus)
        self.assertIn("swsh1-001", rarity.read_cache_file(self.cache)["cards"])

    def test_second_click_has_nothing_left_to_fetch(self):
        at = self.run_app()
        at.button(key="rarity_fetch_start").click().run()
        at = self.run_app()
        self.assertTrue(at.button(key="rarity_fetch_start").disabled)
        self.assertTrue(any("Rien à récupérer" in s.value for s in at.success))

    def test_network_down_stops_cleanly_and_can_resume(self):
        self.http.fail = {"sv08-160", "sv08-190", "sv04.5-171"}
        at = self.run_app()
        at.button(key="rarity_fetch_start").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(rarity.read_cache_file(self.cache)["cards"], {})
        self.assertTrue(any("erreur" in i.value.lower() for i in at.info), [i.value for i in at.info])
        self.http.fail = set()
        at.button(key="rarity_fetch_start").click().run()
        self.assertEqual(len(rarity.read_cache_file(self.cache)["cards"]), 3)


if __name__ == "__main__":
    unittest.main()

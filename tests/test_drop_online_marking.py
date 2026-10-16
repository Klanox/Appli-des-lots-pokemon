"""Brouillons d'un Drop lance : liste complete, mise en ligne groupee horodatee, annulation, statistiques.

Tout se passe sur des fixtures en memoire / dossiers temporaires : aucun fichier metier reel n'est lu ni ecrit,
aucune sauvegarde ne part vers le Cloud (la sauvegarde du Drop est remplacee par une ecriture locale).
"""

from __future__ import annotations

import json
import os
import unittest
from copy import deepcopy
from datetime import date, datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from services import drop_online_marking_service as svc
from services.photo_recognition_service import apply_recognition_statuses
from services.vinted_drops_service import drop_item_status, find_drop
from ui.pages import vinted_listings as VL

LAUNCHED = "2026-08-27T17:27:35"
NOW = datetime(2026, 10, 16, 18, 0, 0)


def _ref(item_id, status, *, draft="", online="", sold="", price=10.0, name=None, uid=None, **extra):
    ref = {
        "drop_item_id": item_id, "card_uid": uid or f"card-{item_id}", "lot_uid": "lot-1",
        "name": name or f"Carte {item_id}", "number": "1/10", "display_number": "1/10", "set": "Set test",
        "quantity": 1, "status": status, "added_at": "2026-10-11T10:00:00", "draft_ready_at": draft,
        "online_at": online, "sold_at": sold, "listing_posted": bool(online), "listing_posted_at": online,
        "price_at_add": price,
    }
    ref.update(extra)
    return ref


def _drop(cards, **extra):
    drop = {"id": "drop-1", "name": "Drop test", "channel": "ChoppeTaCarte", "drop_launched_at": LAUNCHED, "cards": cards}
    drop.update(extra)
    return drop


def _cards():
    return [
        _ref("on", "online", online=LAUNCHED),
        _ref("sold", "sold", online=LAUNCHED, sold="2026-08-28T10:00:00"),
        _ref("todo", "to_prepare"),
        _ref("a1", "draft_ready", draft="2026-10-14T21:00:00", price=5.0),
        _ref("a2", "draft_ready", draft="2026-10-14T21:30:00", price=7.0),
        _ref("b1", "draft_ready", draft="2026-10-15T20:00:00", price=3.0),
        _ref("c1", "draft_ready", draft="2026-10-16T17:49:00", price=9.0),
    ]


class Workspace(unittest.TestCase):
    """Dossier temporaire avec un vinted_drops.json factice ; la sauvegarde 'cloud' est une ecriture locale."""

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        self.path = Path("vinted_drops.json")
        self.backup_dir = Path("backups")
        self.journal = Path("logs") / "drop_online_marking_journal.jsonl"
        self.saves = 0

    def write(self, drop):
        self.path.write_text(json.dumps({"drops": [drop]}), encoding="utf-8")

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["drops"][0]

    def load(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data):
        self.saves += 1
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def mark(self, ids, online_at=datetime(2026, 10, 16, 16, 0, 0), **kw):
        return svc.apply_mark_online(
            "drop-1", ids, online_at, load_drops=self.load, save_drops=self.save, drops_path=str(self.path),
            backup_dir=str(self.backup_dir), journal_path=str(self.journal), confirmed=kw.pop("confirmed", True),
            now=kw.pop("now", NOW), **kw,
        )

    def undo(self, batch):
        return svc.undo_marking_batch(
            batch, load_drops=self.load, save_drops=self.save, drops_path=str(self.path),
            backup_dir=str(self.backup_dir), journal_path=str(self.journal), now=NOW,
        )


class DraftListTests(unittest.TestCase):
    def test_all_drafts_of_the_drop_are_listed_whatever_the_series(self):
        listings = svc.draft_listings(_drop(_cards()))
        self.assertEqual([item["item_ids"] for item in listings], [["a1"], ["a2"], ["b1"], ["c1"]])
        self.assertEqual(sum(item["cards"] for item in listings), 4)

    def test_online_sold_posted_and_unprocessed_are_not_drafts(self):
        cards = _cards() + [_ref("posted", "draft_ready", draft="2026-10-15T10:00:00", listing_posted=True)]
        ids = [i for item in svc.draft_listings(_drop(cards)) for i in item["item_ids"]]
        self.assertNotIn("on", ids)
        self.assertNotIn("sold", ids)
        self.assertNotIn("todo", ids)
        self.assertNotIn("posted", ids)

    def test_series_are_numbered_by_creation_gap(self):
        by_id = {item["item_ids"][0]: item for item in svc.draft_listings(_drop(_cards()))}
        self.assertEqual([by_id[i]["series"] for i in ("a1", "a2", "b1", "c1")], [1, 1, 2, 3])
        self.assertEqual({item["series_count"] for item in by_id.values()}, {3})
        self.assertEqual(by_id["c1"]["created_at"], "2026-10-16T17:49:00")

    def test_multi_card_listing_is_one_line(self):
        drop = _drop(_cards(), listing_texts={"g": {"card_uids": ["card-a1", "card-a2"]}})
        listings = svc.draft_listings(drop)
        self.assertEqual(len(listings), 3)
        group = listings[0]
        self.assertEqual((group["item_ids"], group["cards"], group["value"]), (["a1", "a2"], 2, 12.0))
        self.assertIn("+", group["name"])

    def test_no_dependency_on_any_recognition_payload(self):
        self.assertEqual(svc.draft_listings(None), [])
        self.assertEqual(svc.draft_listings(_drop([])), [])


class MarkOnlineTests(Workspace):
    def setUp(self):
        super().setUp()
        self.write(_drop(_cards()))

    def test_confirmation_is_required(self):
        before = self.path.read_text(encoding="utf-8")
        result = self.mark(["a1"], confirmed=False)
        self.assertFalse(result["ok"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertEqual(self.saves, 0)

    def test_marks_only_selected_drafts_with_the_chosen_stamp(self):
        result = self.mark(["a1", "b1"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["marked"], 2)
        refs = {r["drop_item_id"]: r for r in self.read()["cards"]}
        for item_id in ("a1", "b1"):
            self.assertEqual(refs[item_id]["status"], "online")
            self.assertEqual(refs[item_id]["online_at"], "2026-10-16T16:00:00")
            self.assertEqual(refs[item_id]["listing_posted_at"], "2026-10-16T16:00:00")
            self.assertTrue(refs[item_id]["listing_posted"])
        self.assertEqual(refs["a2"]["status"], "draft_ready")  # non coche : intact
        self.assertEqual(refs["c1"]["online_at"], "")

    def test_already_online_sold_and_unprocessed_are_never_touched(self):
        before = {r["drop_item_id"]: deepcopy(r) for r in self.read()["cards"]}
        result = self.mark(["on", "sold", "todo", "a1"])
        self.assertEqual(result["marked"], 1)
        after = {r["drop_item_id"]: r for r in self.read()["cards"]}
        for item_id in ("on", "sold", "todo"):
            self.assertEqual(after[item_id], before[item_id], item_id)
        self.assertEqual(len(result["skipped"]), 3)

    def test_saves_through_the_normal_save_function_after_a_backup_and_journals(self):
        result = self.mark(["a1", "a2"])
        self.assertEqual(self.saves, 1)
        self.assertEqual(len(list(self.backup_dir.glob("vinted_drops.json.backup_*"))), 1)
        self.assertEqual(len(result["backups"]), 1)
        lines = [json.loads(line) for line in self.journal.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([entry["drop_item_id"] for entry in lines], ["a1", "a2"])
        self.assertEqual(lines[0]["before"]["status"], "draft_ready")

    def test_date_in_the_future_or_before_launch_is_refused(self):
        self.assertFalse(self.mark(["a1"], online_at=datetime(2026, 10, 17, 9, 0))["ok"])
        self.assertFalse(self.mark(["a1"], online_at=datetime(2026, 8, 1, 9, 0))["ok"])
        self.assertEqual(self.saves, 0)
        self.assertEqual(self.read()["cards"][3]["status"], "draft_ready")

    def test_nothing_to_write_means_no_save(self):
        result = self.mark(["on"])
        self.assertFalse(result["ok"])
        self.assertEqual(self.saves, 0)

    def test_unlaunched_drop_is_refused(self):
        self.write(_drop(_cards(), drop_launched_at=""))
        self.assertFalse(self.mark(["a1"])["ok"])


class UndoTests(Workspace):
    def setUp(self):
        super().setUp()
        self.write(_drop(_cards()))

    def test_undo_restores_drafts_and_removes_the_stamp(self):
        before = {r["drop_item_id"]: deepcopy(r) for r in self.read()["cards"]}
        batch = self.mark(["a1", "a2"])["batch"]
        last = svc.last_marking_batch("drop-1", str(self.journal))
        self.assertEqual((last["batch"], last["count"]), (batch, 2))
        result = self.undo(batch)
        self.assertTrue(result["ok"])
        after = {r["drop_item_id"]: r for r in self.read()["cards"]}
        self.assertEqual(after, before)
        self.assertIsNone(svc.last_marking_batch("drop-1", str(self.journal)))
        self.assertFalse(self.undo(batch)["ok"])  # deja annule

    def test_a_card_sold_since_is_left_alone(self):
        batch = self.mark(["a1", "a2"])["batch"]
        data = self.load()
        for ref in data["drops"][0]["cards"]:
            if ref["drop_item_id"] == "a1":
                ref.update(status="sold", sold_at="2026-10-16T17:00:00")
        self.path.write_text(json.dumps(data), encoding="utf-8")
        result = self.undo(batch)
        after = {r["drop_item_id"]: r for r in self.read()["cards"]}
        self.assertEqual(result["undone"], 1)
        self.assertEqual(after["a1"]["status"], "sold")
        self.assertEqual(after["a2"]["status"], "draft_ready")

    def test_only_the_last_batch_is_offered(self):
        first = self.mark(["a1"], online_at=datetime(2026, 10, 16, 10, 0), now=datetime(2026, 10, 16, 10, 5))["batch"]
        second = self.mark(["a2"], online_at=datetime(2026, 10, 16, 11, 0), now=datetime(2026, 10, 16, 11, 5))["batch"]
        self.assertEqual(svc.last_marking_batch("drop-1", str(self.journal))["batch"], second)
        self.undo(second)
        self.assertEqual(svc.last_marking_batch("drop-1", str(self.journal))["batch"], first)


class FirstOnlineAndStatsTests(unittest.TestCase):
    def _two_series(self):
        return _drop([
            _ref("s1a", "sold", online="2026-09-01T10:00:00", sold="2026-09-01T12:00:00"),
            _ref("s1b", "online", online="2026-09-01T10:00:00"),
            _ref("s2a", "online", online="2026-10-10T20:00:00"),
            _ref("s2b", "online", online="2026-10-10T20:00:00"),
            _ref("draft", "draft_ready", draft="2026-10-16T09:00:00"),
        ])

    def test_first_online_is_the_oldest_stamp_else_the_launch_date(self):
        self.assertEqual(svc.drop_first_online_at(self._two_series()), "2026-09-01T10:00:00")
        self.assertEqual(svc.drop_first_online_at(_drop([_ref("d", "draft_ready", draft="2026-10-16T09:00:00")])), LAUNCHED)
        self.assertEqual(svc.drop_first_online_at({"cards": []}), "")  # aucune date inventee

    def test_a_card_counts_from_its_own_online_date(self):
        drop = self._two_series()
        self.assertEqual(svc.drop_cards_online_by(drop, datetime(2026, 9, 5)), 2)
        self.assertEqual(svc.drop_cards_online_by(drop, datetime(2026, 10, 11)), 4)  # brouillon jamais compte

    def test_stats_origin_is_the_first_online_date_and_series_follow_at_their_own_date(self):
        drop = self._two_series()
        self.assertEqual(VL._analytics_origin(drop), datetime(2026, 9, 1, 10, 0))
        self.assertEqual(VL._analytics_total_cards_at(drop, datetime(2026, 9, 2)), 2)
        self.assertEqual(VL._analytics_total_cards_at(drop, datetime(2026, 10, 11)), 4)
        rows = [{
            "sale": {"sale_id": "s", "drop_item_id": "s1a"}, "card": {"card_uid": "card-s1a"}, "quantity": 1,
            "revenue": 10.0, "profit": 5.0, "date": datetime(2026, 9, 1, 12, 0), "card_name": "x", "is_off_stock": False,
        }]
        series = VL._analytics_time_series(drop, rows, now=datetime(2026, 10, 12))
        self.assertEqual(series[0]["timestamp"], datetime(2026, 9, 1, 10, 0))
        sale = next(point for point in series if point["is_transaction"])
        self.assertEqual(sale["sell_through"], 50.0)  # 1 vendue / 2 cartes en ligne a cette date (pas 5)

    def test_drop_without_any_online_date_keeps_the_historical_denominator(self):
        drop = _drop([_ref("x", "to_photograph"), _ref("y", "to_prepare"), _ref("z", "draft_ready", draft="2026-10-16T09:00:00")])
        self.assertEqual(VL._analytics_total_cards_at(drop, NOW), 3)
        self.assertEqual(VL._analytics_origin(drop), datetime.fromisoformat(LAUNCHED))

    def test_existing_drop_where_all_online_dates_equal_the_launch_keeps_its_origin(self):
        drop = _drop([_ref("a", "online", online=LAUNCHED), _ref("b", "sold", online=LAUNCHED, sold="2026-08-28T10:00:00")])
        self.assertEqual(VL._analytics_origin(drop), datetime.fromisoformat(LAUNCHED))


class AnalysisNeverDowngradesTests(unittest.TestCase):
    def _payload(self, ids):
        return {"listings": [{"ready": True, "card_uids": [f"card-{i}" for i in ids],
                              "cards": [{"candidate": {"drop_item_id": i}} for i in ids]}]}

    def test_recognition_statuses_never_touch_online_sold_or_drafts(self):
        for launched in (True, False):
            drop = _drop(_cards(), drop_launched_at=LAUNCHED if launched else "")
            data = {"drops": [drop]}
            before = {r["drop_item_id"]: (r["status"], r["online_at"], r["listing_posted"]) for r in drop["cards"]}
            apply_recognition_statuses(data, "drop-1", self._payload(["on", "sold", "a1", "b1"]))
            after = {r["drop_item_id"]: (r["status"], r["online_at"], r["listing_posted"]) for r in drop["cards"]}
            for item_id in ("on", "sold", "a1", "a2", "b1", "c1"):
                self.assertEqual(after[item_id], before[item_id], (launched, item_id))

    def test_back_to_prepare_is_refused_for_online_and_sold(self):
        data = {"drops": [_drop(_cards())]}
        for item_id in ("on", "sold"):
            self.assertFalse(VL._drop_mark_to_prepare(data, "drop-1", item_id))
        self.assertTrue(VL._drop_mark_to_prepare(data, "drop-1", "a1"))
        refs = {r["drop_item_id"]: r for r in data["drops"][0]["cards"]}
        self.assertEqual((refs["on"]["status"], refs["on"]["online_at"]), ("online", LAUNCHED))
        self.assertEqual(refs["sold"]["status"], "sold")

    def test_listing_status_setter_skips_online_and_sold(self):
        data = {"drops": [_drop(_cards())]}
        drop = data["drops"][0]
        listing = {"card_uids": ["card-on", "card-sold"], "cards": [{"candidate": {"drop_item_id": "on"}}, {"candidate": {"drop_item_id": "sold"}}]}
        for status in ("sorted", "needs_review", "draft_ready", "to_prepare"):
            VL._set_recognition_listing_status(data, drop, listing, status)
        refs = {r["drop_item_id"]: r for r in drop["cards"]}
        self.assertEqual((refs["on"]["status"], refs["sold"]["status"]), ("online", "sold"))


def _box_script(drop_id, payload_json):
    import json as _json
    import ui.pages.vinted_listings as _VL
    from services.vinted_drops_service import find_drop as _find

    data = _json.load(open("vinted_drops.json", encoding="utf-8"))
    drop = _find(data, drop_id)
    _VL._render_recognition_creation_step(data, drop, [], None, str, None, False, _json.loads(payload_json))


def _panel_script(drop_id, now_iso):
    from datetime import datetime as _dt
    import ui.pages.vinted_listings as _VL

    _VL._render_mark_online_panel(drop_id, [], now=_dt.fromisoformat(now_iso))


def _undo_script(drop_id):
    import ui.pages.vinted_listings as _VL

    _VL._render_undo_online_panel(drop_id)


class ScreenTests(Workspace):
    def setUp(self):
        super().setUp()
        self.write(_drop(_cards()))
        patcher = patch.object(VL, "save_vinted_drops", side_effect=lambda data, path="vinted_drops.json": self.save(data))
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def text(at):
        return "\n".join([m.value for m in at.markdown] + [c.value for c in at.caption])

    def run_box(self):
        # analyse en cours : UNE seule annonce (la serie c1) ; les autres brouillons n'y figurent pas
        payload = {"ready": False, "diagnostic_errors": ["x"], "listings": [{
            "recognition_group_id": "g-c1", "card_uids": ["card-c1"], "cards": [{"candidate": {"drop_item_id": "c1", "card_uid": "card-c1"}}]}]}
        at = AppTest.from_function(_box_script, args=("drop-1", json.dumps(payload)))
        at.default_timeout = 60
        return at.run()

    def test_box_lists_every_draft_with_the_right_total_and_a_visible_button(self):
        at = self.run_box()
        self.assertFalse(at.exception)
        self.assertIn("Brouillons à publier (4)", self.text(at))
        self.assertEqual(at.button(key="restock_mark_all_online_drop-1").label, "🟢 Marquer les 4 brouillons en ligne")
        self.assertEqual([e.label for e in at.expander], ["Afficher les 4 brouillons"])
        for item_id in ("a1", "a2", "b1", "c1"):
            self.assertEqual(at.button(key=f"restock_mark_online_drop-1_{item_id}").label, "🟢 Marquer en ligne")
        self.assertIn("série 1", self.text(at))
        self.assertIn("série 3", self.text(at))

    def test_individual_button_keeps_working_and_adds_the_stamp(self):
        at = self.run_box()
        at.button(key="restock_mark_online_drop-1_a1").click().run()
        self.assertFalse(at.exception)
        refs = {r["drop_item_id"]: r for r in self.read()["cards"]}
        self.assertEqual(refs["a1"]["status"], "online")
        self.assertTrue(refs["a1"]["online_at"])
        self.assertEqual(refs["a2"]["status"], "draft_ready")
        self.assertIn("Brouillons à publier (3)", self.text(self.run_box()))
        self.assertIn("restock_undo_online_drop-1", {b.key for b in self.run_box().button})

    def test_panel_defaults_to_all_checked_and_now_then_marks_the_selection(self):
        at = AppTest.from_function(_panel_script, args=("drop-1", NOW.isoformat()))
        at.default_timeout = 60
        at.run()
        self.assertFalse(at.exception)
        checks = {c.key: c.value for c in at.checkbox}
        self.assertEqual(len(checks), 4)
        self.assertTrue(all(checks.values()))
        self.assertEqual(at.date_input(key="vinted_markon_date_drop-1").value, NOW.date())
        self.assertEqual(at.time_input(key="vinted_markon_time_drop-1").value, time(18, 0))
        self.assertIn("4 annonce(s) sélectionnée(s) sur 4", self.text(at))
        self.assertIn("24,00 €", self.text(at))  # 5 + 7 + 3 + 9
        at.checkbox(key="vinted_markon_sel_drop-1_c1").uncheck().run()
        self.assertIn("3 annonce(s) sélectionnée(s) sur 4", self.text(at))
        at.date_input(key="vinted_markon_date_drop-1").set_value(date(2026, 10, 16)).run()
        at.time_input(key="vinted_markon_time_drop-1").set_value(time(16, 0)).run()
        at.button(key="vinted_markon_confirm_drop-1").click().run()
        self.assertFalse(at.exception)
        refs = {r["drop_item_id"]: r for r in self.read()["cards"]}
        for item_id in ("a1", "a2", "b1"):
            self.assertEqual((refs[item_id]["status"], refs[item_id]["online_at"]), ("online", "2026-10-16T16:00:00"))
        self.assertEqual(refs["c1"]["status"], "draft_ready")  # decoche
        self.assertEqual(refs["on"]["online_at"], LAUNCHED)    # deja en ligne : intact
        self.assertEqual(refs["sold"]["status"], "sold")

    def test_panel_all_none_toggles_and_future_date_blocks_confirmation(self):
        at = AppTest.from_function(_panel_script, args=("drop-1", NOW.isoformat()))
        at.default_timeout = 60
        at.run()
        at.button(key="vinted_markon_none_drop-1").click().run()
        self.assertFalse(any(c.value for c in at.checkbox))
        self.assertTrue(at.button(key="vinted_markon_confirm_drop-1").disabled)
        at.button(key="vinted_markon_all_drop-1").click().run()
        self.assertTrue(all(c.value for c in at.checkbox))
        at.time_input(key="vinted_markon_time_drop-1").set_value(time(23, 0)).run()
        self.assertTrue(at.button(key="vinted_markon_confirm_drop-1").disabled)
        self.assertTrue(any("futur" in e.value for e in at.error))

    def test_undo_panel_brings_back_the_drafts(self):
        before = {r["drop_item_id"]: deepcopy(r) for r in self.read()["cards"]}
        self.mark(["a1", "a2"])
        at = AppTest.from_function(_undo_script, args=("drop-1",))
        at.default_timeout = 60
        at.run()
        self.assertFalse(at.exception)
        self.assertIn("2 annonce(s)", self.text(at))
        at.button(key="vinted_markon_undo_ok_drop-1").click().run()
        self.assertFalse(at.exception)
        self.assertEqual({r["drop_item_id"]: r for r in self.read()["cards"]}, before)


class SourceGuardTests(unittest.TestCase):
    def test_mark_online_only_writes_through_the_service(self):
        source = Path(VL.__file__).read_text(encoding="utf-8")
        start = source.index("def _render_mark_online_panel")
        end = source.index("def _render_restock_publish_box")
        block = source[start:end]
        self.assertNotIn("set_drop_card_status(", block)
        self.assertNotIn('["status"] =', block)


if __name__ == "__main__":
    unittest.main()

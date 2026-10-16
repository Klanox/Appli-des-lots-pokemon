"""Tests : double comptage du stock, « cartes vendues » unique, courbe corrigee a l'affichage.

Aucune donnee reelle : jeux temporaires uniquement.
"""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import logic
from services import stock_history_service as svc

FIX_AT = "2026-10-13T20:00:00"


def _card(name, qty, price, **extra):
    card = {"name": name, "number": "1", "quantity": qty, "suggested_price": price, "sold_quantity": 0}
    card.update(extra)
    return card


def _lots():
    stored_src = _card("Ronflex", 3, 10.0, stored_quantity=2,
                       storage_entries=[{"date": "2026-05-12", "quantity": 1}, {"date": "2026-08-09", "quantity": 1}])
    plain = _card("Pikachu", 2, 5.0)
    sold = _card("Dracaufeu", 4, 20.0, sold_quantity=2, sold_entries=[{"quantity": 2, "price": 50.0}])
    given = _card("Evoli", 2, 8.0, sold_quantity=1, sold_entries=[{"quantity": 1, "price": 0.0, "is_exchange": True}])
    keep = _card("Mew", 1, 100.0, is_collection_keep=True, stored_quantity=0)
    storage = {"nom": "Stockage", "is_storage": True, "prix_achat": 0.0, "ventes": [],
               "cards": [_card("Ronflex", 2, 10.0)]}
    lot = {"nom": "Lot A", "prix_achat": 40.0, "ventes": [{"price": 7.0}], "cards": [stored_src, plain, sold, given, keep]}
    return [lot, storage]


class GstTests(unittest.TestCase):
    def _gst(self, lots, archives=None):
        with tempfile.TemporaryDirectory() as tmp:
            arch = Path(tmp) / "lots_archives.json"
            arch.write_text(json.dumps(archives or []), encoding="utf-8")
            with patch.object(logic, "ld", return_value={"lots": lots}), patch.object(logic, "LOTS_ARCHIVES_FILE", str(arch)):
                logic.gst.clear()
                result = logic.gst()
                logic.gst.clear()
        return result

    def test_stored_card_counts_once(self):
        r = self._gst(_lots())
        # Ronflex 3-2 = 1 (lot) + 2 (Stockage) ; Pikachu 2 ; Dracaufeu 4-2 = 2 ; Evoli 2-1 = 1 ; Mew exclu
        self.assertEqual(r["remaining_cards"], 1 + 2 + 2 + 2 + 1)
        self.assertAlmostEqual(r["stock_value"], 1 * 10 + 2 * 10 + 2 * 5 + 2 * 20 + 1 * 8)

    def test_revenue_profit_and_totals_unchanged(self):
        r = self._gst(_lots())
        self.assertAlmostEqual(r["total_revenue"], 7.0 + 50.0 + 0.0)
        self.assertAlmostEqual(r["total_profit"], 57.0 - 40.0)
        self.assertEqual(r["total_cards"], 3 + 2 + 4 + 2 + 1 + 2)

    def test_sold_cards_exclude_exchange_given(self):
        r = self._gst(_lots())
        self.assertEqual(r["sold_cards"], 2)  # Dracaufeu 2 ; l'Evoli donne en echange n'est pas vendu

    def test_archives_follow_same_rules(self):
        arch = [{"nom": "Archive", "prix_achat": 0.0, "ventes": [], "cards": [
            _card("A", 3, 4.0, stored_quantity=1, sold_quantity=1,
                  sold_entries=[{"quantity": 1, "price": 3.0}])]}]
        r = self._gst([], arch)
        self.assertEqual(r["remaining_cards"], 1)
        self.assertAlmostEqual(r["stock_value"], 4.0)
        self.assertEqual(r["sold_cards"], 1)

    def test_never_negative(self):
        r = self._gst([{"nom": "L", "prix_achat": 0.0, "ventes": [], "cards": [_card("X", 1, 9.0, stored_quantity=3)]}])
        self.assertEqual(r["remaining_cards"], 0)
        self.assertEqual(r["stock_value"], 0)


class CurveTests(unittest.TestCase):
    def test_stock_value_from_state_subtracts_stored(self):
        lots = _lots()
        # meme formule que gst : 1*10 (Ronflex) + 20 (Stockage) + 10 + 40 + 8
        self.assertAlmostEqual(svc._stock_value_from_state({"lots": lots}, []), 88.0)

    def test_stored_value_at_is_cumulative_and_capped(self):
        lots = _lots()
        self.assertEqual(svc.stored_value_at(lots, [], "2026-05-11T10:00:00"), 0.0)
        self.assertEqual(svc.stored_value_at(lots, [], "2026-05-12T09:00:00"), 10.0)
        self.assertEqual(svc.stored_value_at(lots, [], "2026-09-01T09:00:00"), 20.0)
        lots[0]["cards"][0]["stored_quantity"] = 1  # une carte revenue : plafond a stored_quantity
        self.assertEqual(svc.stored_value_at(lots, [], "2026-09-01T09:00:00"), 10.0)

    def test_corrected_points_display_only(self):
        lots = _lots()
        points = [
            {"captured_at": "2026-05-01T10:00:00", "value": 500.0, "provenance": "live"},
            {"captured_at": "2026-08-10T10:00:00", "value": 600.0, "provenance": "live"},
            {"captured_at": "2026-10-14T10:00:00", "value": 650.0, "provenance": "live"},
        ]
        before = copy.deepcopy(points)
        out, info = svc.corrected_stock_history_points(points, lots=lots, archives=[], fix_at=FIX_AT,
                                                       project_dir=tempfile.gettempdir(), desktop=tempfile.gettempdir())
        self.assertEqual(points, before)  # entree non modifiee
        self.assertEqual([p["value"] for p in out], [500.0, 580.0, 650.0])
        self.assertEqual(out[1]["value_original"], 600.0)
        self.assertEqual(out[1]["value_correction"], "estime")
        self.assertNotIn("value_correction", out[0])
        self.assertNotIn("value_correction", out[2])
        self.assertEqual(info, {"recalcule": 0, "estime": 1, "inchange": 2})

    def test_backup_point_recalculated_from_original_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data = {"lots": _lots()}
            backup = tmp_path / "data.json.backup_20260607_002955"
            backup.write_text(json.dumps(data), encoding="utf-8")
            digest = hashlib.sha256(backup.read_bytes()).hexdigest()[:12]
            points = [{"captured_at": "2026-06-07T00:29:55", "value": 123.0, "provenance": "backup",
                       "source_hash": digest, "source_kind": "file_backup"}]
            svc._recomputed_values_cached.cache_clear()
            empty_desktop = tmp_path / "desk"
            empty_desktop.mkdir()
            out, info = svc.corrected_stock_history_points(points, lots=[], archives=[], fix_at=FIX_AT,
                                                           project_dir=tmp_path, desktop=empty_desktop)
            self.assertEqual(out[0]["value"], 88.0)
            self.assertEqual(out[0]["value_correction"], "recalcule")
            self.assertEqual(info["recalcule"], 1)

    def test_backup_point_matched_by_name_when_archives_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            backup = tmp_path / "data.json.backup_20260607_002955"
            backup.write_text(json.dumps({"lots": _lots()}), encoding="utf-8")
            (tmp_path / "lots_archives.json").write_text("[]", encoding="utf-8")  # differe de celui de l'epoque
            points = [{"captured_at": "2026-06-07T00:29:55", "value": 123.0, "provenance": "backup",
                       "source_hash": "000000000000", "source_label": backup.name, "source_kind": "file_backup"}]
            svc._recomputed_values_cached.cache_clear()
            empty_desktop = tmp_path / "desk"
            empty_desktop.mkdir()
            out, info = svc.corrected_stock_history_points(points, lots=[], archives=[], fix_at=FIX_AT,
                                                           project_dir=tmp_path, desktop=empty_desktop)
            self.assertEqual(out[0]["value"], 88.0)
            self.assertEqual(info["recalcule"], 1)

    def test_history_file_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stock_value_history.json"
            path.write_text(json.dumps({"schema_version": 1, "points": [
                {"captured_at": "2026-08-10T10:00:00", "value": 600.0, "provenance": "live"}], "annotations": []}), encoding="utf-8")
            before = hashlib.md5(path.read_bytes()).hexdigest()
            payload = svc.load_stock_history(str(path))
            svc.corrected_stock_history_points(payload["points"], lots=_lots(), archives=[], fix_at=FIX_AT,
                                               project_dir=tmp, desktop=tmp)
            self.assertEqual(hashlib.md5(path.read_bytes()).hexdigest(), before)

    def test_annotation_is_in_memory_only(self):
        note = svc.stock_double_count_annotation()
        self.assertTrue(note["auto"])
        self.assertEqual(note["date"], svc.STOCK_DOUBLE_COUNT_FIX_AT[:10])
        self.assertLessEqual(len(note["comment"]), 180)


if __name__ == "__main__":
    unittest.main()

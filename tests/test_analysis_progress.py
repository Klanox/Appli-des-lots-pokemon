"""Progression de l'analyse des photos du Drop (callback + affichage).

Fixtures et dossiers temporaires uniquement : aucun fichier métier réel, aucun Cloud.
La vision (OCR, classification, matching) est remplacée par des fonctions factices ;
ce qui est vérifié ici, c'est le callback et le fait qu'il ne change pas le résultat.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from services import photo_recognition_poc_service as eng
from services.analysis_progress import AnalysisProgress, format_duration


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FormatDurationTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(format_duration(0), "0 s")
        self.assertEqual(format_duration(45.4), "45 s")
        self.assertEqual(format_duration(70), "1 min 10 s")
        self.assertEqual(format_duration(125), "2 min 05 s")
        self.assertEqual(format_duration(None), "")


class TrackerTests(unittest.TestCase):
    def _run(self, total=20, per_photo=2.0, **kwargs):
        clock = FakeClock()
        seen = []
        tracker = AnalysisProgress(seen.append, clock=clock, min_interval=0, **kwargs)
        tracker("lecture", 0, total)
        for done in range(1, total + 1):
            clock.advance(per_photo)
            tracker("lecture", done, total)
        return tracker, seen, clock

    def test_called_once_per_step_and_reaches_the_end(self):
        tracker, seen, _clock = self._run(total=20)
        self.assertEqual(tracker.calls, 21)
        self.assertEqual([s.done for s in seen], list(range(0, 21)))
        self.assertEqual(seen[-1].fraction, 1.0)

    def test_estimation_pending_during_the_first_three_photos(self):
        _tracker, seen, _clock = self._run(total=20)
        for snap in seen[:3]:  # 0, 1, 2 photos traitées
            self.assertTrue(snap.estimating)
            self.assertIsNone(snap.eta_seconds)
            self.assertIn("estimation en cours…", snap.text)
        self.assertFalse(seen[3].estimating)
        self.assertIn("reste environ", seen[3].text)

    def test_remaining_time_decreases_and_matches_the_rolling_average(self):
        _tracker, seen, _clock = self._run(total=20, per_photo=2.0)
        etas = [s.eta_seconds for s in seen if s.eta_seconds is not None]
        self.assertTrue(etas)
        self.assertEqual(etas, sorted(etas, reverse=True))
        self.assertAlmostEqual(seen[10].eta_seconds, 2.0 * 10)  # 10 photos restantes x 2 s
        self.assertEqual(seen[-1].eta_seconds, None)

    def test_rolling_average_follows_recent_speed(self):
        clock = FakeClock()
        seen = []
        tracker = AnalysisProgress(seen.append, clock=clock, min_interval=0, window=4)
        tracker("reconnaissance", 0, 40)
        for done in range(1, 21):          # 20 premières photos lentes : 5 s
            clock.advance(5.0)
            tracker("reconnaissance", done, 40)
        for done in range(21, 31):         # puis rapides : 1 s
            clock.advance(1.0)
            tracker("reconnaissance", done, 40)
        self.assertAlmostEqual(seen[-1].eta_seconds, 10 * 1.0)  # 10 restantes x 1 s (fenêtre de 4)

    def test_elapsed_and_text_shown(self):
        _tracker, seen, _clock = self._run(total=20, per_photo=3.0)
        snap = seen[10]
        self.assertAlmostEqual(snap.elapsed, 30.0)
        self.assertIn("Photo 10 / 20", snap.text)
        self.assertIn("écoulé 30 s", snap.text)
        self.assertIn("Lecture des photos", snap.text)

    def test_finish_reports_total_duration(self):
        tracker, _seen, _clock = self._run(total=20, per_photo=3.5)  # 70 s
        final = tracker.finish()
        self.assertTrue(final.finished)
        self.assertEqual(final.fraction, 1.0)
        self.assertEqual(final.text, "Analyse terminée en 1 min 10 s")

    def test_new_phase_restarts_the_estimation(self):
        clock = FakeClock()
        seen = []
        tracker = AnalysisProgress(seen.append, clock=clock, min_interval=0)
        tracker("lecture", 0, 5)
        for done in range(1, 6):
            clock.advance(1.0)
            tracker("lecture", done, 5)
        tracker("regroupement", 0, 1)
        self.assertIn("Regroupement", seen[-1].text)
        tracker("reconnaissance", 0, 10)
        self.assertTrue(seen[-1].estimating)
        self.assertEqual(seen[-1].done, 0)

    def test_display_updates_are_throttled_but_the_last_one_is_always_sent(self):
        clock = FakeClock()
        seen = []
        tracker = AnalysisProgress(seen.append, clock=clock, min_interval=1.0)
        tracker("lecture", 0, 100)
        for done in range(1, 101):
            clock.advance(0.01)
            tracker("lecture", done, 100)
        self.assertEqual(tracker.calls, 101)
        self.assertLess(len(seen), 10)
        self.assertEqual(seen[-1].done, 100)

    def test_no_callback_target_is_harmless(self):
        tracker = AnalysisProgress(None)
        tracker("lecture", 0, 3)
        tracker("lecture", 3, 3)
        self.assertEqual(tracker.finish().fraction, 1.0)


# ---------------------------------------------------------------------------- moteur
def _write_photos(folder: Path, count: int):
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        image = Image.new("RGB", (40, 56), (index * 20 % 256, 80, 120))
        image.save(folder / f"IMG_20261013_10{index:02d}00.jpg", format="JPEG", quality=70)


def _fake_vision(test: unittest.TestCase):
    def fake_classify(path):
        return {"class": "front", "regions": [], "card_count_hint": 1, "western_back_score": 0.0,
                "japanese_back_score": 0.0, "back_type": ""}

    def fake_build_groups(photos, classifications, *, target_announcements=30):
        groups = []
        for index, photo in enumerate(photos):
            entry = {"photo": photo, "classification": classifications.get(photo.filename, {})}
            groups.append(eng._new_group(index + 1, entry))
        # les deux dernières photos forment une annonce recto/verso (2 photos, 1 groupe)
        if len(groups) >= 2:
            last = groups.pop()
            groups[-1]["photos"].append(last["photos"][0])
        return groups

    def fake_match(path, candidates, used_counts, **kwargs):
        return {"method": "sim", "status": "unrecognized", "score": 0.0, "second_score": 0.0, "margin": 0.0,
                "candidates": [], "ocr": {"available": True, "rows": [], "name_texts": [], "number_texts": [], "raw_text": ""}}

    patches = [
        patch.object(eng, "_ocr_status", lambda: (True, "sim")),
        patch.object(eng, "classify_photo", fake_classify),
        patch.object(eng, "build_groups", fake_build_groups),
        patch.object(eng, "match_front_photo_orientation_aware", fake_match),
        patch.object(eng, "_legend_family_for_group", lambda *a, **k: ("", [], "")),
        patch.object(eng, "run_ocr_for_photo", lambda *a, **k: {}),
    ]
    for item in patches:
        item.start()
        test.addCleanup(item.stop)


def _summary(result):
    return {
        "groups": [
            ([e["photo"].filename for e in g["photos"]], [m.get("status") for m in g.get("matches", [])], g.get("confidence_level"))
            for g in result["groups"]
        ],
        "photo_count": result["analysis_meta"]["photo_count"],
        "candidate_signature": result["analysis_meta"]["candidate_signature"],
        "classifications": sorted(result["classifications"]),
    }


class EngineProgressTests(unittest.TestCase):
    PHOTOS = 7

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        _fake_vision(self)
        _write_photos(Path("photos"), self.PHOTOS)
        Path("data.json").write_text(json.dumps({"lots": [{"lot_uid": "lot-1", "nom": "Lot", "cards": [
            {"card_uid": "c1", "name": "Carte", "number": "1/10", "set": "S", "quantity": 1}]}]}), encoding="utf-8")
        Path("vinted_drops.json").write_text(json.dumps({"drops": [{"id": "drop-1", "name": "D", "cards": [
            {"drop_item_id": "i1", "card_uid": "c1", "lot_uid": "lot-1", "name": "Carte", "number": "1/10",
             "set": "S", "quantity": 1, "status": "to_photograph", "added_at": "2026-10-11T10:00:00"}]}]}), encoding="utf-8")

    def _analyze(self, callback=None, force=True):
        return eng.analyze_sample(
            folder="photos", drop_id="drop-1", start_index=1, target_announcements=self.PHOTOS,
            max_photos=self.PHOTOS, force_rebuild=force, progress_callback=callback,
        )

    def test_callback_is_called_for_each_phase_and_each_photo(self):
        events = []
        self._analyze(lambda phase, done, total: events.append((phase, done, total)))
        lecture = [e for e in events if e[0] == "lecture"]
        self.assertEqual([e[1] for e in lecture], list(range(0, self.PHOTOS + 1)))
        self.assertTrue(all(e[2] == self.PHOTOS for e in lecture))
        self.assertEqual([e for e in events if e[0] == "regroupement"], [("regroupement", 0, 1), ("regroupement", 1, 1)])
        recon = [e for e in events if e[0] == "reconnaissance"]
        self.assertEqual(recon[-1], ("reconnaissance", self.PHOTOS, self.PHOTOS))  # compte des photos, pas des groupes
        self.assertEqual([e[1] for e in recon], sorted(e[1] for e in recon))
        self.assertEqual(recon[0][1], 0)
        order = [e[0] for e in events]
        self.assertLess(order.index("regroupement"), order.index("reconnaissance"))

    def test_result_is_identical_with_and_without_callback(self):
        without = _summary(self._analyze(None))
        with_callback = _summary(self._analyze(AnalysisProgress(lambda snap: None)))
        self.assertEqual(without, with_callback)
        self.assertEqual(without["photo_count"], self.PHOTOS)

    def test_a_failing_callback_never_breaks_the_analysis(self):
        def boom(phase, done, total):
            raise RuntimeError("affichage cassé")

        baseline = _summary(self._analyze(None))
        self.assertEqual(_summary(self._analyze(boom)), baseline)

    def test_cached_result_returns_without_any_progress_event(self):
        self._analyze(None)  # remplit le cache
        events = []
        cached = self._analyze(lambda *a: events.append(a), force=False)
        self.assertEqual(events, [])
        self.assertEqual(_summary(cached)["photo_count"], self.PHOTOS)

    def test_refresh_reports_only_the_groups_that_are_rematched(self):
        result = self._analyze(None)
        # un candidat de plus dans le Drop : seuls les groupes concernés sont recalculés
        drops = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))
        drops["drops"][0]["cards"].append({"drop_item_id": "i2", "card_uid": "c1", "lot_uid": "lot-1", "name": "Carte",
                                           "number": "1/10", "set": "S", "quantity": 1, "status": "to_photograph",
                                           "added_at": "2026-10-12T10:00:00"})
        Path("vinted_drops.json").write_text(json.dumps(drops), encoding="utf-8")
        events = []
        before = _summary(result)
        refreshed = eng.refresh_result_candidates(result, drop_id="drop-1", progress_callback=lambda *a: events.append(a))
        self.assertEqual(events[0], ("candidats", 0, 1))  # lecture du stock annoncée avant tout calcul
        self.assertIn(("candidats", 1, 1), events)
        for phase, done, total in events:
            self.assertIn(phase, {"candidats", "reconnaissance"})
            self.assertLessEqual(done, total)
        recon = [e for e in events if e[0] == "reconnaissance"]
        if recon:
            self.assertEqual(recon[-1][1], recon[-1][2])
        no_callback = eng.refresh_result_candidates(self._analyze(None), drop_id="drop-1")
        self.assertEqual(_summary(refreshed)["groups"], _summary(no_callback)["groups"])
        self.assertEqual(before["photo_count"], _summary(refreshed)["photo_count"])


# ---------------------------------------------------------------------------- affichage
def _ui_script(mode):
    import time as _time
    import streamlit as st
    import ui.pages.vinted_listings as VL

    saved = (VL.st, VL.ANALYSIS_PROGRESS_MIN_SECONDS)  # restaure en fin de script : AppTest tourne dans le meme processus
    if mode == "instant":
        value = VL._run_with_analysis_progress("drop-1", lambda progress: "cache")
    else:
        VL.ANALYSIS_PROGRESS_MIN_SECONDS = 0
        st.session_state["bar_log"] = []
        real_empty = st.empty

        class _Recorder:
            def __init__(self, real):
                self._real = real

            def progress(self, value, text=None):
                st.session_state["bar_log"].append((round(value, 2), text))
                return self._real.progress(value, text=text)

            def empty(self):
                return self._real.empty()

        VL.st = type("S", (), {"__getattr__": lambda self, name: getattr(st, name), "empty": staticmethod(lambda: _Recorder(real_empty()))})()

        def runner(progress):
            progress("lecture", 0, 6)
            for done in range(1, 7):
                _time.sleep(0.01)
                progress("lecture", done, 6)
            return "analyse"

        value = VL._run_with_analysis_progress("drop-1", runner)
    VL.st, VL.ANALYSIS_PROGRESS_MIN_SECONDS = saved
    st.write(f"valeur={value}")


class StreamlitDisplayTests(unittest.TestCase):
    def test_instant_result_shows_nothing(self):
        at = AppTest.from_function(_ui_script, args=("instant",))
        at.default_timeout = 30
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.get("progress")), 0)
        self.assertNotIn("vinted_photo_analysis_done_drop-1", at.session_state)
        self.assertEqual(at.markdown[-1].value, "valeur=cache")

    def test_slow_result_keeps_the_final_message_for_after_the_rerun(self):
        at = AppTest.from_function(_ui_script, args=("slow",))
        at.default_timeout = 30
        at.run()
        self.assertFalse(at.exception)
        message = at.session_state["vinted_photo_analysis_done_drop-1"]
        self.assertTrue(message.startswith("Analyse terminée en "), message)
        self.assertEqual(at.markdown[-1].value, "valeur=analyse")
        self.assertEqual(len(at.get("progress")), 0)  # la barre est retirée à la fin
        log = at.session_state["bar_log"]
        self.assertGreaterEqual(len(log), 2)  # affichée pendant l analyse (mises à jour espacées de 0,15 s)
        self.assertEqual(log[-1][0], 1.0)
        self.assertTrue(all("Lecture des photos" in text for _v, text in log))
        self.assertIn("estimation en cours…", log[0][1])


# ---------------------------------------------------------------------------- « Actualiser les cartes du Drop »
class RefreshPhasesTests(unittest.TestCase):
    def test_phases_have_labels_and_ranges_covering_the_whole_bar(self):
        from services.analysis_progress import PHASE_LABELS, REFRESH_PHASE_LABELS, REFRESH_PHASE_RANGES, STEP_PHASES

        for phase in ("candidats", "enregistrement", "statuts"):
            self.assertIn(phase, PHASE_LABELS)
            self.assertIn(phase, STEP_PHASES)
        self.assertEqual(REFRESH_PHASE_RANGES["candidats"][0], 0.0)
        self.assertEqual(REFRESH_PHASE_RANGES["statuts"][1], 1.0)
        ordered = [REFRESH_PHASE_RANGES[k] for k in ("candidats", "reconnaissance", "enregistrement", "statuts")]
        for (_a, end), (start, _b) in zip(ordered, ordered[1:]):
            self.assertEqual(end, start)  # pas de trou ni de recul
        self.assertEqual(REFRESH_PHASE_LABELS["reconnaissance"], "Recalcul de l'analyse")

    def test_bar_moves_forward_across_the_phases(self):
        from services.analysis_progress import REFRESH_PHASE_LABELS, REFRESH_PHASE_RANGES

        clock = FakeClock()
        seen = []
        tracker = AnalysisProgress(
            seen.append, clock=clock, min_interval=0, phase_ranges=REFRESH_PHASE_RANGES, phase_labels=REFRESH_PHASE_LABELS
        )
        tracker("candidats", 0, 1)
        clock.advance(1)
        tracker("candidats", 1, 1)
        for done in range(0, 11):
            clock.advance(1)
            tracker("reconnaissance", done, 10)
        tracker("enregistrement", 0, 1)
        tracker("enregistrement", 1, 1)
        tracker("statuts", 0, 1)
        tracker("statuts", 1, 1)
        fractions = [snap.fraction for snap in seen]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[-1], 1.0)
        self.assertTrue(any("Recalcul de l'analyse" in snap.text for snap in seen))
        self.assertTrue(any("Lecture du stock" in snap.text for snap in seen))
        self.assertTrue(any("statuts du Drop" in snap.text for snap in seen))


class RefreshMessageTests(unittest.TestCase):
    def test_no_change_message_is_explicit_even_when_instant(self):
        import ui.pages.vinted_listings as VL

        result = {"candidates": [{}] * 133, "metrics": {"candidate_groups_rematched": 0, "candidate_changes": {}}}
        text = VL._refresh_done_message((result, {}), 0.2)
        self.assertIn("moins d'1 s", text)
        self.assertIn("133 carte(s)", text)
        self.assertIn("0 changement", text)

    def test_changes_message_counts_cards_and_listings(self):
        import ui.pages.vinted_listings as VL

        result = {
            "candidates": [{}] * 420,
            "metrics": {"candidate_groups_rematched": 3, "candidate_changes": {"added": 2, "removed": 1, "changed": 4}},
        }
        text = VL._refresh_done_message((result, {}), 12.0)
        self.assertIn("12 s", text)
        self.assertIn("420 carte(s)", text)
        self.assertIn("7 carte(s) modifiée(s)", text)
        self.assertIn("3 annonce(s) recalculée(s)", text)


def _refresh_ui_script(mode):
    import time as _time
    import streamlit as st
    import ui.pages.vinted_listings as VL

    saved_min = VL.ANALYSIS_PROGRESS_MIN_SECONDS
    VL.ANALYSIS_PROGRESS_MIN_SECONDS = 0
    st.session_state["bar_log"] = []
    slot = st.empty()
    st.write("sous le slot")
    real_slot = slot

    class _Slot:
        def progress(self, value, text=None):
            st.session_state["bar_log"].append((round(value, 2), text))
            return real_slot.progress(value, text=text)

        def empty(self):
            return real_slot.empty()

    def runner(progress):
        progress("candidats", 0, 1)
        progress("candidats", 1, 1)
        if mode == "slow":
            for done in range(1, 5):
                _time.sleep(0.01)
                progress("reconnaissance", done, 4)
        progress("statuts", 1, 1)
        return ({"candidates": [{}] * 5, "metrics": {"candidate_groups_rematched": 0, "candidate_changes": {}}}, {})

    VL._run_with_analysis_progress(
        "drop-1", runner, slot=_Slot(), always_show=True, start_text="Lecture du stock et des cartes du Drop…",
        phase_ranges=VL.REFRESH_PHASE_RANGES, phase_labels=VL.REFRESH_PHASE_LABELS, done_message=VL._refresh_done_message,
    )
    VL.ANALYSIS_PROGRESS_MIN_SECONDS = saved_min


class RefreshDisplayTests(unittest.TestCase):
    def test_start_text_is_drawn_immediately_and_end_message_kept_even_when_instant(self):
        at = AppTest.from_function(_refresh_ui_script, args=("instant",))
        at.default_timeout = 30
        at.run()
        self.assertFalse(at.exception)
        log = at.session_state["bar_log"]
        self.assertEqual(log[0], (0.0, "Lecture du stock et des cartes du Drop…"))
        self.assertEqual(len(at.get("progress")), 0)  # retirée à la fin
        message = at.session_state["vinted_photo_analysis_done_drop-1"]
        self.assertIn("5 carte(s)", message)
        self.assertIn("0 changement", message)

    def test_slow_refresh_shows_each_phase(self):
        at = AppTest.from_function(_refresh_ui_script, args=("slow",))
        at.default_timeout = 30
        at.run()
        self.assertFalse(at.exception)
        texts = " | ".join(text for _v, text in at.session_state["bar_log"])
        self.assertIn("Lecture du stock", texts)
        self.assertIn("Recalcul de l'analyse", texts)
        self.assertEqual(at.session_state["bar_log"][-1][0], 1.0)


if __name__ == "__main__":
    unittest.main()

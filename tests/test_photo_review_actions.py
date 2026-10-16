"""Verification des photos du Drop : messages precis, groupes ignores, garde-fou E1,
carte hors stock, regle du verso orphelin et deplacement de photos.

Fixtures en memoire / dossier temporaire uniquement : aucun fichier metier reel n'est lu ou ecrit
(la session de verification est redirigee vers un dossier temporaire) et rien ne part vers le Cloud.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services import photo_recognition_poc_service as engine
from services import photo_recognition_service as svc
from services import photo_review_actions as A
from tests.test_photo_recognition_service import _photo
from ui.pages import vinted_listings as VL


def _ref(item_id, name, number, set_name, status, *, display=None):
    return {
        "drop_item_id": item_id, "card_uid": f"uid-{item_id}", "lot_uid": "lot-1", "name": name, "number": number,
        "display_number": display or number, "set": set_name, "status": status, "quantity": 1,
    }


def _cand(ref):
    return {
        "card_uid": ref["card_uid"], "lot_uid": "lot-1", "drop_item_id": ref["drop_item_id"],
        "drop_card_key": f"lot-1::{ref['card_uid']}", "name": ref["name"], "number": ref["number"],
        "set": ref["set"], "drop_status": ref["status"], "quantity": 1,
    }


REFS = [
    _ref("i-lebou", "Léboulérou", "108", "Destinées de Paldea", "online", display="108/198"),
    _ref("i-balba", "Balbalèze", "5", "Collection McDonald's 2023", "sold"),
    _ref("i-zek10", "Zekrom", "10", "Célébrations", "sold", display="10/50"),
    _ref("i-zekTG", "Zekrom", "TG05", "Stars Étincelantes", "to_photograph"),
    _ref("i-pika", "Pikachu", "2", "Collection McDonald's 2024", "to_photograph"),
    _ref("i-other", "Rattata", "13", "Set test", "to_photograph"),
]
DROP = {"id": "drop-1", "name": "Drop test", "drop_launched_at": "2026-08-27T17:27:35", "cards": REFS}
SCOPE = [_cand(r) for r in REFS if r["status"] == "to_photograph"]


def _ocr(name, full):
    return {"available": True, "name_texts": [name], "number_texts": [full], "collector_number_texts": [full]}


def _group(index, front_no, back_no, *, top, status="review", ocr=None, not_in_drop="", conflict=False, row=None,
           front_back_score=0.05, back_back_score=0.7, front_class="primary_front", expected=1):
    front = _photo(front_no, f"p{front_no}.jpg")
    back = _photo(back_no, f"p{back_no}.jpg") if back_no else None
    photos = [{"photo": front, "classification": {"class": front_class, "western_back_score": front_back_score}}]
    if back:
        photos.append({"photo": back, "classification": {"class": "back_western", "western_back_score": back_back_score}})
    candidates = [{"candidate": top, "score": 88.0, **(row or {"number_match": False, "reasons": ["nom exact/proche"]})}] if top else []
    return {
        "announcement_index": index, "grouping_status": "ok", "confidence_level": "orange",
        "photos": photos, "primary_front": photos[0], "group_back": photos[1] if back else None,
        "detail_cards": [], "expected_cards": expected, "grouping_reasons": [],
        "matches": [{
            "status": status, "score": 88.0, "margin": 10.0, "subcard_id": f"sub-{index}",
            "subcard_photos": {"front": f"{front_no}:p{front_no}.jpg", "back": f"{back_no}:p{back_no}.jpg" if back_no else ""},
            "candidates": candidates, "ocr": ocr or {},
            "v13_not_in_drop_confidence": not_in_drop, "v15_ocr_identity_conflict": conflict,
        }],
    }


def _result(groups):
    return {
        "analysis_meta": {"drop_id": "drop-1", "pipeline_version": "t", "photo_signature": "p", "candidate_signature": "c"},
        "sample_photos": [e["photo"] for g in groups for e in g["photos"]],
        "groups": groups, "candidates": deepcopy(SCOPE),
    }


def _session():
    return {"version": "v1", "drop_id": "drop-1", "validations": {}, "grouping_confirmations": {}}


class _Isolated(unittest.TestCase):
    """Redirige la session de verification vers un dossier temporaire."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(svc, "PRODUCTION_CACHE_DIR", Path(self._tmp.name) / "sessions")
        patcher.start()
        self.addCleanup(patcher.stop)
        saver = patch.object(engine, "save_cached_analysis_result", return_value={"write_seconds": 0, "size_bytes": 0})
        saver.start()
        self.addCleanup(saver.stop)

    def reload_session(self):
        return svc.load_drop_photo_session("drop-1")


class MessagesTests(_Isolated):
    def setUp(self):
        super().setUp()
        self.leb = _group(36, 1, 2, top=SCOPE[0], not_in_drop="strong", ocr=_ocr("Leboulerou", "108/091"))
        self.result = _result([self.leb])

    def test_published_message_names_the_card_and_status(self):
        hint = A.not_in_drop_hint(self.leb["matches"][0], DROP, self.result)
        self.assertEqual(hint["kind"], "published")
        self.assertEqual(hint["message"], "Déjà publiée dans le Drop : Léboulérou 108/198 · Destinées de Paldea (en ligne)")

    def test_sold_card_says_vendue(self):
        group = _group(42, 3, 4, top=SCOPE[0], not_in_drop="possible", ocr=_ocr("Balbaleze", "5/015"))
        self.assertIn("(vendue)", A.not_in_drop_hint(group["matches"][0], DROP, self.result)["message"])

    def test_in_drop_but_not_published_reads_absente_des_cartes_a_traiter(self):
        refs = deepcopy(REFS)
        refs.append(_ref("i-draft0", "Tarsal", "30", "Set test", "needs_review"))
        drop = {**DROP, "cards": refs}
        result = _result([self.leb])  # Tarsal absent du perimetre
        group = _group(7, 5, 6, top=SCOPE[0], not_in_drop="possible", ocr=_ocr("Tarsal", "30/100"))
        hint = A.not_in_drop_hint(group["matches"][0], drop, result)
        self.assertEqual(hint["kind"], "out_of_scope")
        self.assertTrue(hint["message"].startswith("Absente des cartes à traiter"))

    def test_absente_du_drop_only_when_nowhere(self):
        group = _group(8, 5, 6, top=SCOPE[0], not_in_drop="strong", ocr=_ocr("Inconnu", "77/100"))
        self.assertEqual(A.not_in_drop_hint(group["matches"][0], DROP, self.result)["message"], "Absente du Drop")

    def test_ui_status_uses_the_precise_message(self):
        session = _session()
        status = VL._photo_match_semantic_status(session, self.leb, self.leb["matches"][0], 0, DROP, self.result)
        self.assertIn("Déjà publiée dans le Drop", status["message"])
        legacy = VL._photo_match_semantic_status(session, self.leb, self.leb["matches"][0], 0)
        self.assertEqual(legacy["message"], "Carte peut-être absente du Drop")  # sans Drop : comportement d'avant


class IgnoredGroupsTests(_Isolated):
    def setUp(self):
        super().setUp()
        self.leb = _group(36, 1, 2, top=SCOPE[0], not_in_drop="strong", ocr=_ocr("Leboulerou", "108/091"))
        self.new = _group(37, 3, 4, top=SCOPE[1], status="recognized", row={"number_match": True, "reasons": ["numéro exact"]})
        self.result = _result([self.leb, self.new])

    def test_published_group_is_ignored_and_stops_blocking(self):
        session = _session()
        self.assertTrue(svc.unresolved_groups(self.result, session))
        session, report = A.sync_review_dispositions(self.result, session, DROP)
        self.assertEqual(report["ignored"], 1)
        self.assertEqual(svc.group_disposition(session, self.leb), "published")
        self.assertEqual(svc.unresolved_groups(self.result, session), [])
        payload = svc.build_step4_payload(self.result, session)
        self.assertTrue(payload["ready"], payload["diagnostic_errors"])
        self.assertEqual(len(payload["listings"]), 1)  # l'annonce ignoree ne genere pas d'annonce
        summary = svc.analysis_summary(self.result, session)
        self.assertEqual((summary["ignored"], summary["auto"]), (1, 1))

    def test_rejecting_puts_the_group_back_and_it_stays_there(self):
        session, _ = A.sync_review_dispositions(self.result, _session(), DROP)
        session = A.reject_published(session, self.leb)
        self.assertEqual(svc.group_disposition(session, self.leb), "")
        self.assertEqual(len(svc.unresolved_groups(self.result, session)), 1)
        session, report = A.sync_review_dispositions(self.result, session, DROP)  # une resynchronisation ne le re-ignore pas
        self.assertEqual(report["ignored"], 0)
        self.assertEqual(len(svc.unresolved_groups(self.result, session)), 1)

    def test_a_validated_group_is_never_ignored(self):
        session = _session()
        svc.set_match_validation(session, self.leb, self.leb["matches"][0], 0, "correct")
        session, report = A.sync_review_dispositions(self.result, session, DROP)
        self.assertEqual(report["ignored"], 0)

    def test_published_cards_stay_out_of_the_recognition_candidates(self):
        before = deepcopy(self.result["candidates"])
        A.sync_review_dispositions(self.result, _session(), DROP)
        self.assertEqual(self.result["candidates"], before)
        self.assertNotIn("i-lebou", {c["drop_item_id"] for c in self.result["candidates"]})

    def test_decision_survives_reload_and_goes_stale_when_photos_change(self):
        session, _ = A.sync_review_dispositions(self.result, _session(), DROP)
        reloaded = self.reload_session()
        self.assertEqual(svc.group_disposition(reloaded, self.leb), "published")
        changed = deepcopy(self.leb)
        changed["photos"].append({"photo": _photo(9, "extra.jpg"), "classification": {}})
        self.assertEqual(svc.group_disposition(reloaded, changed), "")

    def test_toggle_labels_published_and_created_announcements(self):
        session, _ = A.sync_review_dispositions(self.result, _session(), DROP)
        self.assertEqual(A.group_processed_label(self.leb, session, DROP), "Déjà publiée — ignorée")
        self.assertEqual(A.group_processed_label(self.new, session, DROP), "")
        drop = deepcopy(DROP)
        next(r for r in drop["cards"] if r["drop_item_id"] == "i-balba")["status"] = "draft_ready"
        created = _group(50, 5, 6, top=_cand(_ref("i-balba", "Balbalèze", "5", "x", "draft_ready")), status="recognized")
        self.assertEqual(A.group_processed_label(created, session, drop), "Annonce déjà créée (brouillon)")


class OcrConflictGuardTests(_Isolated):
    def _zekrom(self, **kw):
        return _group(3, 5, 6, top=SCOPE[0] if False else _cand(REFS[3]), status="recognized", conflict=True,
                      ocr=_ocr("Zekrom", "10/025"), **kw)

    def test_name_only_proposal_with_conflicting_number_is_not_recognized(self):
        group = self._zekrom()
        session = _session()
        self.assertTrue(svc.ocr_conflict_blocks_recognition(group["matches"][0]))
        self.assertTrue(svc.group_review_reasons(session, group))
        self.assertIn(group, svc.unresolved_groups(_result([group]), session))

    def test_likely_reference_is_shown_with_its_status(self):
        group = self._zekrom()
        message = A.match_hint_message(group["matches"][0], DROP, _result([group]))
        self.assertIn("Plus probable : Zekrom 10/50 · Célébrations (vendue)", message)
        self.assertIn("Numéro lu 10/025 ≠ TG05", message)

    def test_good_recognitions_are_not_downgraded(self):
        ok = _group(4, 7, 8, top=_cand(REFS[4]), status="recognized", conflict=False, ocr=_ocr("Pikachu", "2/015"))
        self.assertFalse(svc.ocr_conflict_blocks_recognition(ok["matches"][0]))
        self.assertEqual(svc.group_review_reasons(_session(), ok), [])
        with_number = self._zekrom(row=None)
        with_number["matches"][0]["candidates"][0]["number_match"] = True
        self.assertFalse(svc.ocr_conflict_blocks_recognition(with_number["matches"][0]))
        with_visual = self._zekrom()
        with_visual["matches"][0]["candidates"][0]["visual_score"] = 75.0
        self.assertFalse(svc.ocr_conflict_blocks_recognition(with_visual["matches"][0]))

    def test_user_validation_still_wins(self):
        group = self._zekrom()
        session = _session()
        svc.set_match_validation(session, group, group["matches"][0], 0, "correct")
        self.assertEqual(svc.group_review_reasons(session, group), [])


class NotInStockTests(_Isolated):
    def setUp(self):
        super().setUp()
        self.zek = _group(3, 1, 2, top=_cand(REFS[3]), status="recognized", conflict=True, ocr=_ocr("Zekrom", "10/025"))
        self.good = _group(4, 3, 4, top=_cand(REFS[4]), status="recognized", row={"number_match": True, "reasons": []})
        self.result = _result([self.zek, self.good])

    def test_group_leaves_review_and_stops_blocking_creation(self):
        session = _session()
        self.assertFalse(svc.build_step4_payload(self.result, session)["ready"])
        session = A.mark_not_in_stock(session, self.zek)
        self.assertEqual(svc.group_review_reasons(session, self.zek), [])
        payload = svc.build_step4_payload(self.result, session)
        self.assertTrue(payload["ready"], payload["diagnostic_errors"])
        self.assertEqual([l["announcement_index"] for l in payload["listings"]], [4])  # aucune annonce pour la carte hors stock

    def test_read_ocr_and_photos_are_remembered_and_survive_reload(self):
        session = A.mark_not_in_stock(_session(), self.zek)
        entry = self.reload_session()["review_dispositions"][svc.stable_group_id(self.zek)]
        self.assertEqual(entry["kind"], "not_in_stock")
        self.assertEqual(entry["ocr"]["name"], "Zekrom")
        self.assertEqual(entry["ocr"]["number"], "10/025")
        self.assertEqual(len(entry["photos"]), 2)
        rows = A.disposition_rows(self.result, self.reload_session(), "not_in_stock")
        self.assertEqual(len(rows), 1)

    def test_restore_cancels_the_action(self):
        session = A.mark_not_in_stock(_session(), self.zek)
        session = A.restore_to_review(session, self.zek)
        self.assertTrue(svc.group_review_reasons(session, self.zek))
        self.assertEqual(A.disposition_rows(self.result, session, "not_in_stock"), [])

    def test_card_added_to_the_drop_releases_the_group(self):
        session = A.mark_not_in_stock(_session(), self.zek)
        drop = deepcopy(DROP)
        drop["cards"].append(_ref("i-zek25", "Zekrom", "10", "Célébrations", "to_photograph"))
        result = deepcopy(self.result)
        result["candidates"].append(_cand(drop["cards"][-1]))  # apres « Mettre a jour l'analyse »
        session, report = A.sync_review_dispositions(result, session, drop)
        self.assertEqual(report["released"], 1)
        self.assertEqual(svc.group_disposition(session, result["groups"][0]), "")

    def test_no_business_json_is_written(self):
        names = ("data.json", "lots_archives.json", "vinted_drops.json", "counters.json", "monthly_goals.json")
        with TemporaryDirectory() as cwd:
            import os
            old = os.getcwd()
            os.chdir(cwd)
            try:
                A.mark_not_in_stock(_session(), self.zek)
                A.sync_review_dispositions(self.result, _session(), DROP)
                created = {p.name for p in Path(cwd).iterdir()}
            finally:
                os.chdir(old)
        self.assertFalse(created & set(names))

    def test_reverify_never_touches_ignored_or_not_in_stock_groups(self):
        session = A.mark_not_in_stock(_session(), self.zek)
        with patch.object(svc.engine, "active_drop_candidates", return_value=(DROP, self.result["candidates"])), \
             patch.object(svc.engine, "_recognize_groups", return_value=(True, "", 0)) as recognize, \
             patch.object(svc.engine, "_ocr_status", return_value=(True, "")), \
             patch.object(svc.engine, "_clear_candidate_derived_group_state"), \
             patch.object(svc, "reconcile_poc_validations", side_effect=lambda r, s, **kw: (s, {})):
            _r, _s, report = svc.reverify_unvalidated_groups(self.result, session, drop_id="drop-1")
        self.assertEqual(report["kept_ignored"], 1)
        analysed = [svc.stable_group_id(g) for call in recognize.call_args_list for g in call.args[0]]
        self.assertNotIn(svc.stable_group_id(self.zek), analysed)


def _fake_recognize(groups, candidates, **kwargs):
    for group in groups:
        front = group.get("primary_front")
        group["matches"] = [{
            "status": "review", "score": 50.0, "margin": 5.0, "subcard_id": f"new-{group['announcement_index']}",
            "subcard_photos": {"front": "", "back": ""}, "candidates": [], "ocr": {},
        }] if front else []
        group["confidence_level"] = "orange"
    return True, "", 0


class RegroupingTests(_Isolated):
    def setUp(self):
        super().setUp()
        recognizer = patch.object(engine, "_recognize_groups", side_effect=_fake_recognize)
        recognizer.start()
        self.addCleanup(recognizer.stop)
        drop_patch = patch.object(engine, "active_drop_candidates", return_value=(DROP, deepcopy(SCOPE)))
        drop_patch.start()
        self.addCleanup(drop_patch.stop)
        # reproduction de #31..#34 : recto seul, [verso, recto lu verso], verso seul, paire normale
        self.g31 = _group(31, 60, None, top=SCOPE[0], status="recognized", front_back_score=0.14)
        self.g32 = _group(32, 61, 62, top=None, front_class="back_western", front_back_score=0.79, back_back_score=1.0)
        self.g33 = _group(33, 63, None, top=None, front_class="back_western", front_back_score=1.0)
        self.g34 = _group(34, 64, 65, top=SCOPE[1], status="recognized", front_back_score=0.06, back_back_score=1.0)
        self.g30 = _group(30, 58, 59, top=SCOPE[2], status="recognized", front_back_score=0.05, back_back_score=0.9)
        self.result = _result([self.g30, self.g31, self.g32, self.g33, self.g34])

    @staticmethod
    def layout(result):
        return [(g["announcement_index"], [svc.normalize_photo_identity(e["photo"])["capture_index"] for e in g["photos"]])
                for g in result["groups"]]

    def test_rule_fires_only_on_the_orphan_verso_case(self):
        result, session, report = A.apply_orphan_verso_rule(self.result, _session(), drop_id="drop-1")
        self.assertEqual(self.layout(result), [(30, [58, 59]), (31, [60, 61]), (32, [62, 63]), (34, [64, 65])])
        self.assertEqual(len(report["applied"]), 1)
        again = A.apply_orphan_verso_rule(result, session, drop_id="drop-1")[2]
        self.assertEqual(again["applied"], [])  # idempotente

    def test_rule_does_not_fire_on_correct_pairs_even_with_back_like_first_photo(self):
        pair = _group(40, 70, 71, top=SCOPE[0], status="recognized", front_class="back_western", front_back_score=0.9, back_back_score=1.0)
        lone = _group(39, 69, None, top=SCOPE[1], front_back_score=0.1)
        # recto seul suivi d'une PAIRE (verso lu comme recto) : la regle se declenche -> verifie qu'elle est limitee au recto seul
        self.assertEqual(A.plan_orphan_verso([self.g30, pair], _session()), [])  # precedent = paire complete
        self.assertEqual(A.plan_orphan_verso([lone, pair], _session()), [1])

    def test_lone_recto_or_verso_without_partner_stays_flagged(self):
        result = _result([self.g30, self.g31, self.g34])
        out = A.apply_orphan_verso_rule(result, _session(), drop_id="drop-1")[0]
        self.assertEqual(self.layout(out), self.layout(result))  # aucun pendant : la regle ne touche rien
        verso_only = A.build_review_group([self.g33["photos"][0]], index=33, reasons=[])
        self.assertEqual(verso_only["grouping_status"], "review")
        self.assertIn("verso isolé : recto manquant ou séquence ambiguë", verso_only["grouping_reasons"])

    def test_other_validations_are_never_touched_and_touched_ones_are_reported(self):
        session = _session()
        svc.set_match_validation(session, self.g30, self.g30["matches"][0], 0, "correct")
        svc.set_match_validation(session, self.g34, self.g34["matches"][0], 0, "correct")
        svc.set_match_validation(session, self.g31, self.g31["matches"][0], 0, "correct")
        kept = {k: v for k, v in session["validations"].items() if v["group_id"] in {svc.stable_group_id(self.g30), svc.stable_group_id(self.g34)}}
        result, session, report = A.apply_orphan_verso_rule(self.result, session, drop_id="drop-1")
        self.assertEqual({k: v for k, v in session["validations"].items() if k in kept}, kept)
        self.assertEqual(len(session["validations"]), 2)  # la validation de #31 est invalidee
        self.assertTrue(any("annonce 31 : correct" in note for note in report["applied"][0]["invalidated"]))

    def test_only_touched_groups_are_rematched(self):
        seen = []
        with patch.object(engine, "_recognize_groups", side_effect=lambda groups, *a, **k: (seen.append([g["announcement_index"] for g in groups]), _fake_recognize(groups, a))[1]):
            A.apply_orphan_verso_rule(self.result, _session(), drop_id="drop-1")
        self.assertEqual(seen, [[31, 32]])

    # ---- B : actions sous chaque photo
    def _key(self, no):
        return f"{no}:p{no}.jpg"

    def test_detail_on_a_lone_photo_attaches_it_to_the_previous_announcement(self):
        lone = _group(12, 23, None, top=None, front_back_score=0.19)
        previous = _group(11, 21, 22, top=SCOPE[0], status="recognized")
        result = _result([previous, lone])
        out, session, report = A.move_photo(result, _session(), self._key(23), "detail", drop_id="drop-1")
        self.assertTrue(report["ok"])
        self.assertEqual(self.layout(out), [(11, [21, 22, 23])])
        group = out["groups"][0]
        self.assertEqual([svc._photo_role(group, e) for e in group["photos"]], ["primary_front", "back_western", "extra"])
        self.assertEqual(session["photo_moves"][self._key(23)]["action"], "detail")

    def test_attach_next_and_previous_and_reversibility(self):
        a = _group(1, 1, 2, top=SCOPE[0], status="recognized")
        b = _group(2, 3, None, top=None)
        c = _group(3, 4, 5, top=SCOPE[1], status="recognized")
        result = _result([a, b, c])
        out, session, report = A.move_photo(result, _session(), self._key(3), "next", drop_id="drop-1")
        self.assertEqual(self.layout(out), [(1, [1, 2]), (3, [3, 4, 5])])
        out, session, report = A.move_photo(out, session, self._key(3), "prev", drop_id="drop-1")
        self.assertEqual(self.layout(out), [(1, [1, 2, 3]), (3, [4, 5])])

    def test_validations_of_both_groups_are_invalidated_and_listed_others_untouched(self):
        a = _group(1, 1, 2, top=SCOPE[0], status="recognized")
        b = _group(2, 3, None, top=SCOPE[1])
        c = _group(3, 4, 5, top=SCOPE[2], status="recognized")
        session = _session()
        for g in (a, b, c):
            svc.set_match_validation(session, g, g["matches"][0], 0, "correct")
        out, session, report = A.move_photo(_result([a, b, c]), session, self._key(3), "prev", drop_id="drop-1")
        self.assertEqual(len(report["invalidated"]), 2)
        self.assertEqual({v["group_id"] for v in session["validations"].values()}, {svc.stable_group_id(c)})
        self.assertEqual(out["groups"][-1], c)  # l'annonce voisine validee n'a pas ete reconstruite

    def test_multi_card_groups_refuse_the_move_without_changing_anything(self):
        multi = _group(2, 3, 4, top=SCOPE[0], expected=2)
        a = _group(1, 1, 2, top=SCOPE[1], status="recognized")
        result = _result([a, multi])
        before = self.layout(result)
        out, session, report = A.move_photo(result, _session(), self._key(3), "prev", drop_id="drop-1")
        self.assertFalse(report["ok"])
        self.assertEqual(self.layout(out), before)

    def test_moves_are_replayed_after_a_new_analysis(self):
        lone = _group(12, 23, None, top=None)
        previous = _group(11, 21, 22, top=SCOPE[0], status="recognized")
        _out, session, _r = A.move_photo(_result([previous, lone]), _session(), self._key(23), "detail", drop_id="drop-1")
        fresh = _result([_group(11, 21, 22, top=SCOPE[0], status="recognized"), _group(12, 23, None, top=None)])
        out, session, report = A.reapply_user_moves(fresh, session, drop_id="drop-1")
        self.assertEqual(report["reapplied"], 1)
        self.assertEqual(self.layout(out), [(11, [21, 22, 23])])
        self.assertEqual(A.reapply_user_moves(out, session, drop_id="drop-1")[2]["reapplied"], 0)

    def test_a_user_decision_prevents_the_automatic_rule_from_coming_back(self):
        session = _session()
        session["photo_moves"] = {self._key(61): {"action": "next", "anchor": self._key(62), "source": "user"}}
        self.assertEqual(A.plan_orphan_verso(self.result["groups"], session), [])

    def test_grouping_incorrect_records_something_and_persists(self):
        session = A.flag_grouping(_session(), self.g31)
        self.assertTrue(A.is_grouping_flagged(session, self.g31))
        self.assertTrue(A.is_grouping_flagged(self.reload_session(), self.g31))
        self.assertFalse(A.is_grouping_flagged(self.reload_session(), self.g34))

    def test_pass_state_is_repositioned_on_the_group_that_received_the_photo(self):
        a = _group(1, 1, 2, top=SCOPE[0], status="recognized")
        b = _group(2, 3, None, top=None)
        result = _result([a, b])
        out, session, report = A.move_photo(result, _session(), self._key(3), "prev", drop_id="drop-1")
        state = {"mode": "review", "group_ids": ["x", "y"], "position": 1, "visited_group_ids": ["x"], "completed": False}
        rebased = VL._rebase_review_pass_after_regroup(state, out, session, mode="review", destination_group_id=report["destination_group_id"])
        self.assertEqual(rebased["group_ids"][rebased["position"]], report["destination_group_id"])


class SessionCompatibilityTests(_Isolated):
    def test_old_session_without_new_keys_loads_with_defaults(self):
        path = svc._session_path("drop-1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": "v1", "drop_id": "drop-1", "validations": {"k": {"state": "correct"}}}), encoding="utf-8")
        session = svc.load_drop_photo_session("drop-1")
        self.assertEqual(session["validations"], {"k": {"state": "correct"}})
        for key in ("review_dispositions", "published_rejected", "photo_moves", "grouping_flagged"):
            self.assertEqual(session[key], {})
        self.assertEqual(session["regroup_log"], [])


if __name__ == "__main__":
    unittest.main()

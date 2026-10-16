"""Reassort d'un Drop lance : association manuelle (F1) et brouillons publies (F2 + F3).

Tout se passe sur des fixtures en memoire / dossiers temporaires : aucun fichier metier
reel n'est lu ni ecrit, et aucune sauvegarde ne part vers le Cloud (les fonctions de
sauvegarde du Drop sont remplacees par une ecriture locale dans le dossier temporaire).
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from services import photo_recognition_service as service
from services.photo_recognition_poc_service import active_drop_candidates, candidate_set_signature
from services.vinted_drops_service import (
    drop_has_restock,
    drop_has_restock_scope,
    drop_ref_is_restock_published,
    drop_restock_refs,
    drop_restock_scope_refs,
    find_drop,
    set_drop_card_status,
)
from tests.test_photo_recognition_service import _candidate, _result, _session
from ui.pages import vinted_listings as VL


LAUNCHED = "2026-08-27T17:27:35"


def _ref(item_id, status, *, added="2026-10-11T10:00:00", draft="", uid=None, **extra):
    ref = {
        "drop_item_id": item_id,
        "card_uid": uid or f"card-{item_id}",
        "lot_uid": "lot-1",
        "name": f"Carte {item_id}",
        "number": "1/10",
        "set": "Set test",
        "quantity": 1,
        "status": status,
        "added_at": added,
        "draft_ready_at": draft,
        "online_at": "",
        "sold_at": "",
        "listing_posted": False,
    }
    ref.update(extra)
    return ref


def _launched_drop(cards):
    return {"id": "drop-1", "name": "Drop test", "channel": "ChoppeTaCarte", "drop_launched_at": LAUNCHED, "cards": cards}


def _fingerprint(refs):
    return json.dumps(sorted(refs, key=lambda r: r["drop_item_id"]), sort_keys=True)


class ManualAssociationKeepsDropItemTests(unittest.TestCase):
    """F1 : un choix manuel conserve l'identifiant de la reference du Drop."""

    def _failed_group_result(self):
        result = _result()
        wanted = {**_candidate("card-9", "9/10"), "drop_item_id": "item-9", "drop_card_key": "lot-1::card-9"}
        other = {**_candidate("card-1", "1/10"), "drop_item_id": "item-1"}
        result["candidates"] = [other, wanted]
        match = result["groups"][0]["matches"][0]
        match.update(status="unrecognized", score=0, candidates=[])
        return result, wanted

    def _manual_payload(self, result, chosen):
        session = _session()
        group = result["groups"][0]
        with patch.object(service, "save_drop_photo_session", side_effect=lambda value: value):
            service.set_match_validation(
                session, group, group["matches"][0], 0, "manual",
                selected_candidate=chosen,
            )
        return service.build_step4_payload(result, session)

    def test_manual_choice_outside_proposals_keeps_drop_item_id(self):
        result, wanted = self._failed_group_result()
        payload = self._manual_payload(result, wanted)

        self.assertTrue(payload["ready"], payload["diagnostic_errors"])
        listing = payload["listings"][0]
        self.assertEqual(listing["cards"][0]["candidate"]["drop_item_id"], "item-9")
        self.assertEqual(VL._recognition_listing_item_ids(listing), ["item-9"])
        self.assertEqual(listing["card_uids"], ["card-9"])

    def test_manual_choice_picks_the_right_reference_when_the_card_uid_is_shared(self):
        result, wanted = self._failed_group_result()
        twin = {**wanted, "drop_item_id": "item-9b", "drop_card_key": "lot-1::card-9::b"}
        result["candidates"].append(twin)
        payload = self._manual_payload(result, {**wanted})

        self.assertEqual(VL._recognition_listing_item_ids(payload["listings"][0]), ["item-9"])

    def test_manual_choice_without_matching_candidate_is_left_unchanged(self):
        result, wanted = self._failed_group_result()
        result["candidates"] = []
        payload = self._manual_payload(result, wanted)

        self.assertTrue(payload["ready"])
        self.assertEqual(VL._recognition_listing_item_ids(payload["listings"][0]), [""])

    def test_automatic_proposal_is_untouched(self):
        result = _result()
        result["candidates"] = [{**_candidate("card-1", "1/10"), "drop_item_id": "item-1"}]
        result["groups"][0]["matches"][0]["candidates"][0]["candidate"]["drop_item_id"] = "item-1"
        payload = service.build_step4_payload(result, _session(), require_ready=False)

        self.assertEqual(VL._recognition_listing_item_ids(payload["listings"][0]), ["item-1"])

    def test_associated_card_leaves_to_photograph_and_listing_counts_as_drafted(self):
        result, wanted = self._failed_group_result()
        payload = self._manual_payload(result, wanted)
        drop = _launched_drop([
            _ref("item-1", "to_photograph", uid="card-1"),
            _ref("item-9", "to_photograph", uid="card-9"),
        ])
        service._apply_restock_recognition_statuses(drop, payload)

        self.assertEqual(find_status(drop, "item-9"), "sorted")
        self.assertEqual(find_status(drop, "item-1"), "to_photograph")  # non photographiee : inchangee

        listing = payload["listings"][0]
        data = {"drops": [drop]}
        self.assertTrue(VL._set_recognition_listing_status(data, drop, listing, "draft_ready"))
        self.assertEqual(find_status(drop, "item-9"), "draft_ready")
        self.assertEqual(VL._recognition_listing_statuses(drop, listing), ["draft_ready"])
        # la carte associee n'est plus comptee « sans photo reconnue »
        represented = {i for i in VL._recognition_listing_item_ids(listing) if i}
        without_photo = [r for r in drop_restock_refs(drop) if r["drop_item_id"] not in represented]
        self.assertEqual([r["drop_item_id"] for r in without_photo], ["item-1"])


def find_status(drop, item_id):
    return next(r for r in drop["cards"] if r["drop_item_id"] == item_id)["status"]


class RestockScopeKeepsPublishedDraftsTests(unittest.TestCase):
    """F3 : un brouillon passe en ligne reste dans le perimetre de reconnaissance."""

    def _drop(self):
        return _launched_drop([
            _ref("pre-online", "online", added="2026-08-20T10:00:00", draft="2026-08-26T10:00:00", online_at=LAUNCHED, listing_posted=True),
            _ref("pre-sold", "sold", added="2026-08-20T10:00:00", sold_at="2026-08-30T10:00:00"),
            _ref("manual-online", "online", added="2026-08-20T10:00:00", online_at=LAUNCHED, listing_posted=True),
            _ref("todo", "to_photograph"),
            _ref("draft", "draft_ready", draft="2026-10-12T10:00:00"),
            _ref("published", "online", draft="2026-10-12T10:00:00", online_at="2026-10-13T10:00:00", listing_posted=True),
            _ref("published-sold", "sold", draft="2026-10-12T10:00:00", sold_at="2026-10-14T10:00:00"),
            _ref("online-no-draft", "online", online_at="2026-10-13T10:00:00", listing_posted=True),
        ])

    def test_scope_contains_published_restock_but_never_pre_launch_refs(self):
        scope = {r["drop_item_id"] for r in drop_restock_scope_refs(self._drop())}
        self.assertEqual(scope, {"todo", "draft", "published", "published-sold"})

    def test_pre_launch_refs_are_never_published_restock(self):
        drop = self._drop()
        for item_id in ("pre-online", "pre-sold", "manual-online", "online-no-draft"):
            ref = next(r for r in drop["cards"] if r["drop_item_id"] == item_id)
            self.assertFalse(drop_ref_is_restock_published(ref, drop), item_id)

    def test_unparsable_or_missing_dates_are_not_published_restock(self):
        drop = self._drop()
        ref = _ref("x", "online", draft="2026-10-12T10:00:00", added="not-a-date")
        self.assertFalse(drop_ref_is_restock_published(ref, drop))
        self.assertFalse(drop_ref_is_restock_published(ref, {"cards": []}))
        self.assertFalse(drop_ref_is_restock_published(_ref("y", "online", draft="2026-10-12T10:00:00"), _launched_drop([]) | {"drop_launched_at": ""}))

    def test_upload_gating_still_depends_on_unprocessed_references_only(self):
        drop = self._drop()
        drop["cards"] = [r for r in drop["cards"] if r["drop_item_id"] in {"pre-online", "published"}]
        self.assertTrue(drop_has_restock_scope(drop))
        self.assertFalse(drop_has_restock(drop))  # donc import photo toujours protege

    def test_drop_without_restock_keeps_the_read_only_preview(self):
        drop = _launched_drop([_ref("pre-online", "online", added="2026-08-20T10:00:00", draft="2026-08-26T10:00:00")])
        self.assertFalse(drop_has_restock_scope(drop))

    def test_candidate_set_signature_is_stable_when_a_draft_goes_online(self):
        with TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "data.json"
            drops_path = Path(tmp) / "vinted_drops.json"
            data_path.write_text(json.dumps({"lots": [{"lot_uid": "lot-1", "nom": "Lot", "cards": [
                {"card_uid": "card-a", "name": "A", "number": "1", "set": "S"},
                {"card_uid": "card-b", "name": "B", "number": "2", "set": "S"},
            ]}]}), encoding="utf-8")
            drop = _launched_drop([
                _ref("a", "draft_ready", draft="2026-10-12T10:00:00", uid="card-a"),
                _ref("b", "to_photograph", uid="card-b"),
                _ref("old", "online", added="2026-08-20T10:00:00", uid="card-old"),
            ])
            drops_path.write_text(json.dumps({"drops": [drop]}), encoding="utf-8")
            _d, before = active_drop_candidates(str(data_path), str(drops_path), "drop-1")

            data = json.loads(drops_path.read_text(encoding="utf-8"))
            self.assertTrue(set_drop_card_status(data, "drop-1", "a", "online"))
            drops_path.write_text(json.dumps(data), encoding="utf-8")
            _d, after = active_drop_candidates(str(data_path), str(drops_path), "drop-1")

        self.assertEqual(candidate_set_signature(before), candidate_set_signature(after))
        self.assertEqual({c["drop_item_id"] for c in after}, {"a", "b"})  # « old » jamais candidat


class MarkRestockOnlineTests(unittest.TestCase):
    """F2 : action « Marquer en ligne » des brouillons de reassort."""

    def _listing(self, *item_ids):
        return {
            "recognition_group_id": "group-" + "-".join(item_ids),
            "cards": [
                {"card_uid": f"card-{i}", "candidate": {"drop_item_id": i, "card_uid": f"card-{i}", "name": f"Carte {i}", "number": "1/10"}}
                for i in item_ids
            ],
            "card_uids": [f"card-{i}" for i in item_ids],
        }

    def _drop(self):
        return _launched_drop([
            _ref("pre-online", "online", added="2026-08-20T10:00:00", draft="2026-08-26T10:00:00", online_at=LAUNCHED, listing_posted=True),
            _ref("pre-sold", "sold", added="2026-08-20T10:00:00"),
            _ref("d1", "draft_ready", draft="2026-10-12T10:00:00"),
            _ref("d2", "draft_ready", draft="2026-10-12T10:00:00"),
            _ref("sorted", "sorted"),
            _ref("todo", "to_photograph"),
        ])

    def test_only_drafts_of_the_listing_go_online(self):
        drop = self._drop()
        before = {r["drop_item_id"]: dict(r) for r in drop["cards"]}
        data = {"drops": [drop]}

        self.assertTrue(VL._mark_restock_listing_online(data, drop, self._listing("d1", "d2")))

        for item_id in ("d1", "d2"):
            ref = next(r for r in drop["cards"] if r["drop_item_id"] == item_id)
            self.assertEqual(ref["status"], "online")
            self.assertTrue(ref["online_at"] and ref["listing_posted"])
            self.assertEqual(ref["draft_ready_at"], before[item_id]["draft_ready_at"])
        for item_id in ("pre-online", "pre-sold", "sorted", "todo"):
            ref = next(r for r in drop["cards"] if r["drop_item_id"] == item_id)
            self.assertEqual(ref, before[item_id], item_id)

    def test_listing_with_a_non_draft_reference_only_touches_its_drafts(self):
        drop = self._drop()
        data = {"drops": [drop]}
        self.assertTrue(VL._mark_restock_listing_online(data, drop, self._listing("d1", "sorted")))
        self.assertEqual(find_status(drop, "d1"), "online")
        self.assertEqual(find_status(drop, "sorted"), "sorted")

    def test_nothing_happens_for_pre_launch_or_unprocessed_references(self):
        drop = self._drop()
        before = deepcopy(drop)
        data = {"drops": [drop]}
        self.assertFalse(VL._mark_restock_listing_online(data, drop, self._listing("pre-online", "pre-sold", "todo")))
        self.assertEqual(drop, before)

    def test_unlaunched_drop_is_never_modified(self):
        drop = self._drop()
        drop["drop_launched_at"] = ""
        before = deepcopy(drop)
        self.assertFalse(VL._mark_restock_listing_online({"drops": [drop]}, drop, self._listing("d1")))
        self.assertEqual(drop, before)

    def test_published_listing_leaves_the_drafts_to_publish_list_but_keeps_its_scope(self):
        drop = self._drop()
        payload = {"ready": True, "listings": [self._listing("d1"), self._listing("d2")]}
        self.assertEqual(len(VL._restock_draft_listings(drop, payload)), 2)
        VL._mark_restock_listing_online({"drops": [drop]}, drop, payload["listings"][0])
        self.assertEqual(
            [l["recognition_group_id"] for l in VL._restock_draft_listings(drop, payload)],
            ["group-d2"],
        )
        self.assertIn("d1", {r["drop_item_id"] for r in drop_restock_scope_refs(drop)})


def _creation_script(drop_id, payload_json):
    import json as _json
    import ui.pages.vinted_listings as _VL
    from services.vinted_drops_service import find_drop as _find

    data = _json.load(open("vinted_drops.json", encoding="utf-8"))
    drop = _find(data, drop_id)
    _VL._render_recognition_creation_step(data, drop, [], None, str, None, False, _json.loads(payload_json))


class CreationStepButtonTests(unittest.TestCase):
    """F2 : le bouton existe, marque le brouillon en ligne et sauvegarde (AppTest, sans cloud)."""

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        drop = _launched_drop([
            _ref("pre", "online", added="2026-08-20T10:00:00", online_at=LAUNCHED, listing_posted=True),
            _ref("d1", "draft_ready", draft="2026-10-12T10:00:00"),
            _ref("todo", "to_photograph"),
        ])
        Path("vinted_drops.json").write_text(json.dumps({"drops": [drop]}), encoding="utf-8")
        listing = MarkRestockOnlineTests()._listing("d1")
        # payload « non pret » : la page s'arrete apres l'avertissement, sans espace de travail annonce
        self.payload = json.dumps({"ready": False, "diagnostic_errors": ["x"], "listings": [listing]})

        def local_save(data, path="vinted_drops.json"):
            Path(path).write_text(json.dumps(data), encoding="utf-8")

        patcher = patch.object(VL, "save_vinted_drops", side_effect=local_save)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self):
        at = AppTest.from_function(_creation_script, args=("drop-1", self.payload))
        at.default_timeout = 60
        return at.run()

    def test_button_marks_the_draft_online_and_saves(self):
        at = self._run()
        self.assertFalse(at.exception)
        self.assertEqual([e.label for e in at.expander], ["Afficher le brouillon"])
        self.assertIn("Brouillons à publier (1)", "\n".join(m.value for m in at.markdown))
        button = at.button(key="restock_mark_online_drop-1_d1")
        self.assertEqual(button.label, "🟢 Marquer en ligne")

        at = button.click().run()

        self.assertFalse(at.exception)
        saved = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))["drops"][0]
        statuses = {r["drop_item_id"]: r["status"] for r in saved["cards"]}
        self.assertEqual(statuses, {"pre": "online", "d1": "online", "todo": "to_photograph"})
        self.assertEqual(len(at.expander), 0)  # plus aucun brouillon a publier

    def test_no_expander_without_draft(self):
        drop = json.loads(Path("vinted_drops.json").read_text(encoding="utf-8"))
        drop["drops"][0]["cards"] = [r for r in drop["drops"][0]["cards"] if r["drop_item_id"] != "d1"]
        Path("vinted_drops.json").write_text(json.dumps(drop), encoding="utf-8")
        at = self._run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.expander), 0)


if __name__ == "__main__":
    unittest.main()

"""Regeneration des titres / descriptions (15/10/2026) : ancien format, etat d'un texte, apercu, ecriture, annulation.

Fixtures temporaires uniquement : aucun fichier metier reel, aucun envoi au Cloud, journal et sauvegardes dans un
dossier temporaire.
"""

from __future__ import annotations

import copy
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from streamlit.testing.v1 import AppTest

from services import listing_text_service as LTS
from services.listing_legacy.generator import prepare_listing as legacy_prepare
from services.vinted_listing_service import prepare_listing as current_prepare

CARD = {"name": "Courrousinge", "number": "171", "set": "Destinées de Paldea", "lang": "fr", "quantity": 1,
        "card_uid": "c-1", "lot_uid": "lot-1"}
OTHER = {"name": "Pikachu", "number": "58", "set": "Évolutions à Paldea", "lang": "fr", "quantity": 1,
         "card_uid": "c-2", "lot_uid": "lot-1"}


def _entry(group, status, cards=None, label=None):
    cards = cards or [CARD]
    return {"group_id": group, "label": label or cards[0]["name"], "status_class": status, "cards": cards,
            "listing_type": "Carte seule", "card_uids": [c["card_uid"] for c in cards], "order": 1}


def _drop(**extra):
    drop = {"id": "drop-1", "name": "Drop test", "cards": [{"drop_item_id": "i1", "card_uid": "c-1", "status": "draft_ready",
                                                              "quantity": 1, "name": "Courrousinge"}],
            "drop_launched_at": "2026-08-27T17:27:35"}
    drop.update(extra)
    return drop


class GeneratorsTests(unittest.TestCase):
    def test_legacy_generator_reproduces_the_old_format_the_user_saw(self):
        old = legacy_prepare([CARD], "Carte seule")
        self.assertEqual(old["title"], "Carte Pokémon - Courrousinge 171/198 - Destinées de Paldea - Shiny Chromatique - FR")
        self.assertTrue(old["description"].startswith("Vends Courrousinge 171/198 - Destinées de Paldea - Shiny Chromatique - FR"))

    def test_current_rules_give_the_expected_courrousinge_171_091(self):
        new = current_prepare([CARD], "Carte seule")
        self.assertEqual(new["title"], "Carte Pokémon - Courrousinge Shiny 171/091 - Destinées de Paldea - FR")
        self.assertTrue(new["description"].startswith("Vends Courrousinge Shiny 171/091 - Destinées de Paldea - FR"))
        head = new["title"] + " " + new["description"].split("\n")[0]  # les Tags du bas gardent « Chromatique » (liste fixe)
        self.assertNotIn("Chromatique", head)
        self.assertNotIn("198", head)


class TextStateTests(unittest.TestCase):
    def setUp(self):
        self.cur = LTS.current_texts([CARD], "Carte seule")
        self.old = LTS.legacy_texts([CARD], "Carte seule")

    def test_states(self):
        self.assertEqual(LTS.text_state(self.cur["title"], self.cur["description"], self.cur, self.old), LTS.STATE_UP_TO_DATE)
        self.assertEqual(LTS.text_state(self.old["title"], self.old["description"], self.cur, self.old), LTS.STATE_LEGACY)
        self.assertEqual(LTS.text_state(self.cur["title"] + " lot", self.cur["description"], self.cur, self.old), LTS.STATE_MANUAL)
        # un seul champ modifie a la main suffit : on ne touche a rien
        self.assertEqual(LTS.text_state(self.old["title"], "ma description", self.cur, self.old), LTS.STATE_MANUAL)
        self.assertEqual(LTS.text_state(self.cur["title"], self.cur["description"], self.cur, self.old, manual=True), LTS.STATE_MANUAL)

    def test_line_endings_do_not_count_as_a_manual_edit(self):
        self.assertEqual(LTS.text_state(self.old["title"], self.old["description"].replace("\n", "\r\n"), self.cur, self.old),
                         LTS.STATE_LEGACY)

    def test_record_draft_text_flags_manual_edits(self):
        drop = _drop()
        state = LTS.record_draft_text(drop, "g1", self.cur["title"], self.cur["description"], [CARD], "Carte seule", ["c-1"])
        self.assertEqual(state, LTS.STATE_UP_TO_DATE)
        self.assertFalse(drop[LTS.TEXTS_KEY]["g1"]["manual"])
        state = LTS.record_draft_text(drop, "g1", self.cur["title"] + " (lot)", self.cur["description"], [CARD], "Carte seule", ["c-1"])
        self.assertEqual(state, LTS.STATE_MANUAL)
        self.assertTrue(drop[LTS.TEXTS_KEY]["g1"]["manual"])
        self.assertEqual(drop[LTS.TEXTS_KEY]["g1"]["origin"], "manual")


class PlanTests(unittest.TestCase):
    def plan(self, entries, drop=None):
        return LTS.build_plan(entries, drop or _drop())

    def test_each_status_gets_its_own_action(self):
        plan = self.plan([
            _entry("draft", LTS.STATUS_DRAFT),
            _entry("online", LTS.STATUS_ONLINE),
            _entry("todo", LTS.STATUS_TO_PREPARE),
            _entry("sold", LTS.STATUS_SOLD),
            _entry("mixed", LTS.STATUS_OTHER),
        ])
        actions = {row["group_id"]: row["action"] for row in plan["rows"]}
        self.assertEqual(actions, {"draft": LTS.ACTION_REGENERATE, "online": LTS.ACTION_UPDATE_ONLINE,
                                   "todo": LTS.ACTION_DISPLAY, "sold": LTS.ACTION_SKIP, "mixed": LTS.ACTION_SKIP})
        draft = next(r for r in plan["rows"] if r["group_id"] == "draft")
        self.assertEqual(draft["update_kind"], LTS.KIND_DRAFT)
        self.assertTrue(draft["assumed"])  # rien d'enregistre : ancien texte suppose
        self.assertIn("171/198", draft["before_title"])
        self.assertIn("171/091", draft["after_title"])
        self.assertEqual(plan["counts"]["regenerate"], 1)
        self.assertEqual(plan["counts"]["update_online"], 1)
        self.assertEqual(plan["counts"]["display"], 1)

    def test_up_to_date_texts_are_left_alone(self):
        cur = LTS.current_texts([OTHER], "Carte seule")
        legacy = LTS.legacy_texts([OTHER], "Carte seule")
        if legacy == cur:  # carte dont le texte n'a pas change entre les deux regles
            plan = self.plan([_entry("same", LTS.STATUS_DRAFT, [OTHER])])
            self.assertEqual(plan["rows"][0]["action"], LTS.ACTION_OK)
            self.assertEqual(plan["rows"][0]["update_kind"], "")

    def test_manual_record_is_never_overwritten_or_listed(self):
        drop = _drop()
        LTS.record_draft_text(drop, "draft", "Mon titre perso", "Ma description", [CARD], "Carte seule", ["c-1"])
        plan = self.plan([_entry("draft", LTS.STATUS_DRAFT)], drop)
        self.assertEqual(plan["rows"][0]["action"], LTS.ACTION_SKIP_MANUAL)
        self.assertEqual(plan["counts"]["manual"], 1)
        self.assertEqual(plan["to_write"], [])
        self.assertEqual(plan["to_list"], [])

    def test_unknown_text_differing_from_both_generators_is_treated_as_manual(self):
        drop = _drop(**{LTS.TEXTS_KEY: {"draft": LTS.make_record("Autre titre", "Autre description", state=LTS.STATE_UP_TO_DATE,
                                                                  card_uids=["c-1"], listing_type="Carte seule", origin="auto")}})
        plan = self.plan([_entry("draft", LTS.STATUS_DRAFT)], drop)
        self.assertEqual(plan["rows"][0]["action"], LTS.ACTION_SKIP_MANUAL)  # en cas de doute : on n'ecrase pas

    def test_record_for_other_cards_is_ignored(self):
        drop = _drop(**{LTS.TEXTS_KEY: {"draft": LTS.make_record("x", "y", state=LTS.STATE_MANUAL, card_uids=["autre"],
                                                                  listing_type="Carte seule", origin="manual")}})
        plan = self.plan([_entry("draft", LTS.STATUS_DRAFT)], drop)
        self.assertEqual(plan["rows"][0]["action"], LTS.ACTION_REGENERATE)

    def test_examples_are_limited_to_five_and_progress_is_reported(self):
        events = []
        entries = [_entry(f"g{i}", LTS.STATUS_DRAFT) for i in range(8)]
        plan = LTS.build_plan(entries, _drop(), progress=lambda *a: events.append(a))
        self.assertEqual(len(plan["examples"]), 5)
        self.assertEqual(events[0], ("textes", 0, 8))
        self.assertEqual(events[-1], ("textes", 8, 8))
        self.assertEqual(len(events), 9)


class ApplyUndoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.drops_path = str(root / "vinted_drops.json")
        self.backup_dir = str(root / "backups")
        self.journal = str(root / "logs" / "journal.jsonl")
        self.saved = 0
        self.drops = {"drops": [_drop()]}
        Path(self.drops_path).write_text(json.dumps(self.drops), encoding="utf-8")

    def load(self):
        return json.loads(Path(self.drops_path).read_text(encoding="utf-8"))

    def save(self, data):
        self.saved += 1
        Path(self.drops_path).write_text(json.dumps(data), encoding="utf-8")

    def apply(self, plan, confirmed=True):
        return LTS.apply_plan(plan, load_drops=self.load, save_drops=self.save, drops_path=self.drops_path,
                              backup_dir=self.backup_dir, journal_path=self.journal, confirmed=confirmed)

    def undo(self, batch):
        return LTS.undo_batch(batch, load_drops=self.load, save_drops=self.save, drops_path=self.drops_path,
                              backup_dir=self.backup_dir, journal_path=self.journal)

    def plan(self):
        return LTS.build_plan([_entry("draft", LTS.STATUS_DRAFT), _entry("online", LTS.STATUS_ONLINE, [OTHER], "Pikachu")],
                              self.load()["drops"][0])

    def test_nothing_is_written_without_confirmation(self):
        before = Path(self.drops_path).read_bytes()
        result = self.apply(self.plan(), confirmed=False)
        self.assertFalse(result["ok"])
        self.assertEqual(Path(self.drops_path).read_bytes(), before)
        self.assertEqual(self.saved, 0)
        self.assertFalse(os.path.exists(self.journal))

    def test_apply_writes_records_updates_backup_and_journal_without_touching_the_rest(self):
        before = self.load()
        plan = self.plan()
        online_row = next(r for r in plan["rows"] if r["group_id"] == "online")
        result = self.apply(plan)
        self.assertTrue(result["ok"], result)
        after = self.load()
        drop_before, drop = before["drops"][0], after["drops"][0]
        # rien d'autre que les deux nouvelles cles du Drop n'a bouge (cartes, statuts, prix, ordre, nom, canal...)
        self.assertEqual({k: v for k, v in drop.items() if k not in (LTS.TEXTS_KEY, LTS.UPDATES_KEY)}, drop_before)
        record = drop[LTS.TEXTS_KEY]["draft"]
        self.assertIn("171/091", record["title"])
        self.assertEqual(record["origin"], "regenerated")
        self.assertFalse(record["manual"])
        # l'annonce en ligne n'est jamais modifiee dans l'appli : listee seulement
        self.assertNotIn("online", drop[LTS.TEXTS_KEY])
        kinds = {u["group_id"]: (u["kind"], u["label"]) for u in drop[LTS.UPDATES_KEY]}
        self.assertEqual(kinds["draft"], (LTS.KIND_DRAFT, "Brouillon Vinted à mettre à jour"))
        if online_row["action"] == LTS.ACTION_UPDATE_ONLINE:
            self.assertEqual(kinds["online"], (LTS.KIND_ONLINE, "Annonce en ligne à mettre à jour"))
        self.assertEqual(self.saved, 1)
        self.assertEqual(len(os.listdir(self.backup_dir)), 1)
        self.assertTrue(os.listdir(self.backup_dir)[0].startswith("vinted_drops.json.backup_"))
        lines = [json.loads(line) for line in Path(self.journal).read_text(encoding="utf-8").splitlines()]
        self.assertTrue(lines and all(line["action"] == "regenerate" and line["batch"] == result["batch"] for line in lines))

    def test_undo_restores_the_previous_state_and_removes_the_pending_updates(self):
        before = self.load()
        batch = self.apply(self.plan())["batch"]
        self.assertEqual(len(LTS.journal_batches(self.journal)), 1)
        result = self.undo(batch)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.load(), {"drops": [{**before["drops"][0], LTS.TEXTS_KEY: {}, LTS.UPDATES_KEY: []}]})
        self.assertEqual(LTS.journal_batches(self.journal), [])
        self.assertFalse(self.undo(batch)["ok"])  # deja annule

    def test_undo_leaves_a_text_edited_since(self):
        batch = self.apply(self.plan())["batch"]
        data = self.load()
        data["drops"][0][LTS.TEXTS_KEY]["draft"]["title"] = "Titre retouche depuis"
        Path(self.drops_path).write_text(json.dumps(data), encoding="utf-8")
        result = self.undo(batch)
        self.assertEqual(self.load()["drops"][0][LTS.TEXTS_KEY]["draft"]["title"], "Titre retouche depuis")
        self.assertTrue(result["skipped"])

    def test_text_changed_between_preview_and_write_is_skipped(self):
        plan = self.plan()
        data = self.load()
        LTS.record_draft_text(data["drops"][0], "draft", "Titre à moi", "Description à moi", [CARD], "Carte seule", ["c-1"])
        Path(self.drops_path).write_text(json.dumps(data), encoding="utf-8")
        result = self.apply(plan)
        self.assertEqual(self.load()["drops"][0][LTS.TEXTS_KEY]["draft"]["title"], "Titre à moi")
        self.assertTrue(any(label == "Courrousinge" for label, _ in result["skipped"]))

    def test_update_list_can_be_marked_done(self):
        self.apply(self.plan())
        drops = self.load()
        pending = LTS.pending_updates(drops)
        self.assertTrue(pending)
        drop, update = pending[0]
        self.assertTrue(LTS.mark_update_done(drops, drop["id"], update["id"], save_drops=self.save))
        self.assertNotIn(update["id"], [u["id"] for _d, u in LTS.pending_updates(self.load())])
        self.assertEqual(LTS.pending_update_group_ids(self.load()["drops"][0]) & {update["group_id"]}, set())


# ---------------------------------------------------------------------------- session : texte « ancien format »
def _session_script(mode):
    import streamlit as st
    import ui.pages.vinted_listings as VL
    from services.listing_legacy.generator import prepare_listing as legacy

    card = {"name": "Courrousinge", "number": "171", "set": "Destinées de Paldea", "lang": "fr", "quantity": 1,
            "card_uid": "c-1", "lot_uid": "lot-1"}
    old = legacy([card], "Carte seule")
    from services.vinted_listing_service import prepare_listing as current

    new = current([card], "Carte seule")
    signature = new["signature"]
    if mode in ("stale_no_shadow", "stale_deleted_widgets", "manual_edit"):
        st.session_state["vinted_listing_signature"] = signature
        if mode != "stale_deleted_widgets":
            st.session_state["vinted_listing_title"] = old["title"] if mode == "stale_no_shadow" else old["title"] + " (lot)"
            st.session_state["vinted_listing_description"] = old["description"]
            st.session_state["vinted_listing_price"] = "1,00 €"
        st.session_state[VL.LISTING_TEXT_SHADOW_KEY] = (
            {} if mode != "stale_deleted_widgets" else
            {"signature": signature, "generated": {"title": old["title"], "description": old["description"], "price": "1,00 €"},
             "values": {"title": old["title"], "description": old["description"], "price": "1,00 €"}}
        )
        if mode == "manual_edit":
            st.session_state[VL.LISTING_TEXT_SHADOW_KEY] = {}
    VL._sync_listing_text([card], "Carte seule", lambda value: f"{value:.2f}€")
    st.write("title=" + st.session_state["vinted_listing_title"])
    st.write("state=" + st.session_state[VL.LISTING_TEXT_STATE_KEY])


class SessionRefreshTests(unittest.TestCase):
    def run_mode(self, mode):
        at = AppTest.from_function(_session_script, args=(mode,))
        at.default_timeout = 30
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return [m.value for m in at.markdown]

    def test_new_listing_always_gets_the_current_rules(self):
        out = self.run_mode("new")
        self.assertIn("title=Carte Pokémon - Courrousinge Shiny 171/091 - Destinées de Paldea - FR", out)
        self.assertIn("state=a_jour", out)

    def test_session_opened_before_the_rules_changed_is_refreshed(self):
        out = self.run_mode("stale_no_shadow")
        self.assertIn("title=Carte Pokémon - Courrousinge Shiny 171/091 - Destinées de Paldea - FR", out)
        self.assertIn("state=a_jour", out)

    def test_old_text_restored_after_leaving_the_screen_is_replaced(self):
        out = self.run_mode("stale_deleted_widgets")
        self.assertIn("title=Carte Pokémon - Courrousinge Shiny 171/091 - Destinées de Paldea - FR", out)

    def test_manual_edit_is_kept_and_flagged(self):
        out = self.run_mode("manual_edit")
        self.assertIn("title=Carte Pokémon - Courrousinge 171/198 - Destinées de Paldea - Shiny Chromatique - FR (lot)", out)
        self.assertIn("state=manuel", out)


class WitnessTests(unittest.TestCase):
    def test_witness_labels(self):
        import ui.pages.vinted_listings as VL

        drop = _drop(**{LTS.UPDATES_KEY: [{"id": "drop-1:g9", "group_id": "g9", "done_at": ""}]})
        self.assertEqual(VL._text_witness_label(LTS.STATE_LEGACY, "g1", drop), "⚠ Texte ancien format")
        self.assertEqual(VL._text_witness_label(LTS.STATE_MANUAL, "g1", drop), "✎ Texte modifié à la main")
        self.assertEqual(VL._text_witness_label(LTS.STATE_UP_TO_DATE, "g1", drop), "")
        self.assertEqual(VL._text_witness_label(LTS.STATE_UP_TO_DATE, "g9", drop), "⚠ Brouillon Vinted à mettre à jour")
        drop[LTS.UPDATES_KEY][0]["done_at"] = "2026-10-15T20:00:00"
        self.assertEqual(VL._text_witness_label(LTS.STATE_UP_TO_DATE, "g9", drop), "")


if __name__ == "__main__":
    unittest.main()

"""Cartes sans extension : source (reproduction hors ligne), garde-fou, generateur, file de correction, journal.

Aucun reseau, aucun fichier reel : tout tourne sur des fixtures temporaires.
"""

from __future__ import annotations

import ast
import copy
import glob
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import utils  # noqa: E402
from services import card_extension_service as ext  # noqa: E402
from services.card_cache_service import search_in_cache_index  # noqa: E402
from services.vinted_listing_service import (  # noqa: E402
    generate_description,
    generate_title,
    listing_missing_extension_cards,
    prepare_listing,
)

SORCILENCE = {"id": "swsh12.5-066", "localId": "066", "name": "Sorcilence VMAX", "image": "https://assets.tcgdex.net/fr/swsh/swsh12.5/066"}
ROUE = {"id": "svp-073", "localId": "073", "name": "Roue-de-Fer-ex", "image": "https://assets.tcgdex.net/fr/sv/svp/073"}
LATIAS = {"id": "me01-100", "localId": "100", "name": "Méga-Latias-ex", "image": "https://assets.tcgdex.net/fr/me/me01/100"}


def cards_index():
    """Cache au format REEL de cards_cache.json : cles SANS espaces ni tirets (+ une cle ajoutee plus tard, avec tirets)."""
    return {
        "sorcilencevmax": [[SORCILENCE, "Zénith Suprême", "swsh12.5"]],
        "rouedeferex": [[ROUE, "SVP Black Star Promos", "svp"]],
        "mega-latias-ex": [[LATIAS, "Méga-Évolution", "me01"]],
        "pikachu": [[{"id": "base1-58", "localId": "58", "name": "Pikachu"}, "Set de Base", "base1"],
                    [{"id": "swsh4-50", "localId": "50", "name": "Pikachu"}, "Voltage Éclatant", "swsh4"]],
    }


SETS_REFERENCE = {"sets": {"me": {"sets": [{"code": "ME02.5", "name": "Héros Transcendants", "total": 100}]}}}


def new_card(name, number, set_name="", card_id="", uid=None, **extra):
    card = {"name": name, "number": number, "set": set_name, "quantity": 1, "sold_quantity": 0,
            "card_uid": uid or f"card_{name}_{number}".replace(" ", "_")}
    if card_id:
        card["id"] = card_id
    card.update(extra)
    return card


def make_world():
    data = {"lots": [
        {"nom": "Lot A", "lot_uid": "lot_a", "cards": [
            new_card("Sorcilence VMAX", "066", "", "swsh12.5-066"),
            new_card("Sorcilence VMAX", "066", "Zénith Suprême", "swsh12.5-066", uid="card_twin"),
            new_card("Roue-de-Fer-ex", "073", "", "svp-073"),
            new_card("Pikachu", "58", "", "base1-58"),
        ]},
        {"nom": "🧾 Collection", "lot_uid": "lot_c", "cards": [
            new_card("Raichu", "50", ""),
            new_card("Mimantis", "085", "", "me05-085"),
            new_card("Dracaufeu", "066", "🇯🇵 ", "SV3-066"),
            new_card("Evoli", "74", "Évolutions Prismatiques", "sv08.5-074"),
        ]},
    ]}
    drops = {"drops": [{"id": "drop1", "name": "Drop Rentrée", "drop_launched_at": "2026-08-27T00:00:00", "cards": [
        {"drop_item_id": "it1", "card_uid": "card_Sorcilence_VMAX_066", "lot_uid": "lot_a", "name": "Sorcilence VMAX", "number": "066",
         "set": "", "status": "online", "added_at": "2026-08-22T10:00:00", "online_at": "2026-08-27T17:00:00", "image_url": "u"},
        {"drop_item_id": "it2", "card_uid": "card_Mimantis_085", "lot_uid": "lot_c", "name": "Mimantis", "number": "085",
         "set": "", "status": "to_photograph", "added_at": "2026-09-30T10:00:00", "image_url": "u"},
    ]}]}
    return data, drops


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.catalogue = ext.build_catalogue(cards_index(), SETS_REFERENCE)
        self.data, self.drops = make_world()
        self.data_path = self.dir / "data.json"
        self.drops_path = self.dir / "vinted_drops.json"
        self.journal = str(self.dir / "journal.jsonl")
        self.backups = str(self.dir / "backups")
        self.write_files()
        self.saved = []

    def write_files(self):
        self.data_path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        self.drops_path.write_text(json.dumps(self.drops, ensure_ascii=False), encoding="utf-8")

    def apply(self, changes, **kw):
        def save_data(d):
            self.saved.append("data")
            self.data_path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

        def save_drops(d):
            self.saved.append("drops")
            self.drops_path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

        return ext.apply_corrections(
            changes, load_data=lambda: self.data, save_data=save_data, load_drops=lambda: self.drops, save_drops=save_drops,
            data_path=str(self.data_path), drops_path=str(self.drops_path), backup_dir=self.backups, journal_path=self.journal, **kw)

    def undo(self, batch):
        def save_data(d):
            self.data_path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

        def save_drops(d):
            self.drops_path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

        return ext.undo_batch(batch, load_data=lambda: self.data, save_data=save_data, load_drops=lambda: self.drops,
                              save_drops=save_drops, data_path=str(self.data_path), drops_path=str(self.drops_path),
                              backup_dir=self.backups, journal_path=self.journal)


# =========================================================================== S : source


class SourceReproductionTests(Fixture):
    """Reproduction hors ligne du chemin Lots > Ajouter une carte avec le code REEL d'app.py (sgt/ecd/afi)."""

    def build_namespace(self, api_cards):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        wanted = {"afi", "sgt", "ecd", "search_in_cache"}
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
        self.assertEqual({f.name for f in funcs}, wanted)
        calls = []

        class Resp:
            def __init__(self, code, payload):
                self.status_code, self._payload = code, payload

            def json(self):
                return self._payload

        def fake_get(url, timeout=None, **_kw):
            calls.append(url)
            if "/cards?name=" in url:
                return Resp(200, copy.deepcopy(api_cards))  # fiches BREVES TCGdex : id, localId, name, image (pas d'objet `set`)
            return Resp(404, {})

        class St:
            session_state = {"cards_index": cards_index()}

        ns = {"st": St, "requests": types.SimpleNamespace(get=fake_get, RequestException=Exception), "json": json,
              "normalize_name": utils.normalize_name, "search_in_cache_index": search_in_cache_index,
              "new_uid": lambda p: f"{p}_x", "load_cards_cache": lambda *a, **k: cards_index()}
        exec(compile(ast.Module(body=funcs, type_ignores=[]), "app_extract", "exec"), ns)
        return ns, calls

    def test_full_name_with_spaces_now_found_in_local_cache(self):
        ns, calls = self.build_namespace([])
        for typed, number in (("Sorcilence Vmax", "066"), ("Sorcilence VMAX", "066"), ("Roue De Fer Ex", "073"), ("Roue-De-Fer-Ex", "073")):
            with self.subTest(typed=typed):
                results = ns["sgt"](typed, number)
                self.assertEqual(len(results), 1, typed)
                self.assertTrue(results[0][1], "l'extension doit venir du cache")
        self.assertEqual(calls, [], "aucun appel API quand le cache local suffit")

    def test_legacy_search_reproduces_the_bug_end_to_end(self):
        """Avant correction (comparaison sans compactage) : « Sorcilence Vmax » ne trouve rien dans le cache,
        l'appli retombe sur l'API TCGdex (liste par nom sans objet `set`) et la carte est creee avec set = ''."""
        ns, calls = self.build_namespace([dict(SORCILENCE)])
        with mock.patch("services.card_cache_service.compact_name_key", side_effect=lambda value: str(value)):
            self.assertEqual(search_in_cache_index("Sorcilence Vmax", cards_index(), num="066", normalize_func=utils.normalize_name), [])
            results = ns["sgt"]("Sorcilence Vmax", "066")
        self.assertEqual(len(calls), 1, "repli reseau declenche")
        card = ns["ecd"](results[0][0], results[0][1])
        self.assertEqual((card["id"], card["set"]), ("swsh12.5-066", ""))
        # meme saisie avec le correctif : trouvee dans le cache, avec son extension
        ns2, calls2 = self.build_namespace([dict(SORCILENCE)])
        fixed = ns2["sgt"]("Sorcilence Vmax", "066")
        self.assertEqual(([s for _c, s in fixed], calls2), (["Zénith Suprême"], []))

    def test_enrichment_keys_with_hyphens_still_found(self):
        ns, _ = self.build_namespace([])
        self.assertEqual(len(ns["sgt"]("Mega-Latias-Ex")), 1)
        self.assertEqual(len(ns["sgt"]("Méga Latias Ex")), 1)

    def test_api_fallback_without_set_object_gives_empty_extension(self):
        """Mecanisme de la cause : cache sans resultat -> liste TCGdex par nom SANS objet `set` -> set = ''."""
        ns, calls = self.build_namespace([dict(SORCILENCE)])
        results = ns["sgt"]("Carte inconnue du cache", "066")
        self.assertEqual(len(calls), 1)
        self.assertEqual([s for _c, s in results], [""])
        enriched = ns["ecd"](results[0][0], results[0][1])
        self.assertEqual(enriched["id"], "swsh12.5-066")
        self.assertEqual(enriched["set"], "")

    def test_guard_completes_the_fallback_card_through_sd(self):
        """Meme chemin que ci-dessus puis ecriture via sd() : le garde-fou renseigne « Zénith Suprême »."""
        ns, _ = self.build_namespace([dict(SORCILENCE)])
        results = ns["sgt"]("Carte inconnue du cache", "066")
        card = ns["ecd"](results[0][0], results[0][1])
        card["card_uid"] = "card_new"
        self.data["lots"][0]["cards"].append(card)
        changes = ext.complete_new_cards_extension(self.data, str(self.data_path), self.catalogue)
        self.assertEqual([c["new"] for c in changes], ["Zénith Suprême"])
        self.assertEqual(card["set"], "Zénith Suprême")


# =========================================================================== detection / normalisation


class DetectionTests(unittest.TestCase):
    def test_missing_values(self):
        for value in ("", None, "  ", "N/A", "n/a", "Pokémon", "pokemon", "🇯🇵", "🇯🇵 ", "-", "Inconnu"):
            with self.subTest(value=value):
                self.assertTrue(ext.is_missing_extension(value))

    def test_real_values_are_not_missing(self):
        for value in ("Zénith Suprême", "151", "MEP Black Star Promos", "🇯🇵 Mega Brave"):
            with self.subTest(value=value):
                self.assertFalse(ext.is_missing_extension(value))

    def test_extension_name_reads_set_then_extension(self):
        self.assertEqual(ext.card_extension_name({"set": "", "extension": "Nuit Noire"}), "Nuit Noire")
        self.assertEqual(ext.card_extension_name({"set": "N/A", "serie": "Épée et Bouclier"}), "")

    def test_compact_name_key_matches_cache_keys(self):
        self.assertEqual(ext.compact_name_key("Sorcilence VMAX"), "sorcilencevmax")
        self.assertEqual(ext.compact_name_key("Roue-de-Fer-ex"), "rouedeferex")
        self.assertEqual(ext.compact_name_key("Méga-Évolution"), "megaevolution")

    def test_search_with_number_and_short_name_still_works(self):
        found = search_in_cache_index("Sorcilence", cards_index(), num="066", normalize_func=utils.normalize_name)
        self.assertEqual([c["id"] for c, _s in found], ["swsh12.5-066"])


# =========================================================================== catalogue / garde-fou


class ResolveAndGuardTests(Fixture):
    def test_resolve_by_card_id(self):
        self.assertEqual(ext.resolve_by_id({"id": "swsh12.5-066"}, self.catalogue)[0], "Zénith Suprême")

    def test_resolve_by_set_prefix_when_card_unknown(self):
        self.assertEqual(ext.resolve_by_id({"id": "svp-999"}, self.catalogue)[0], "SVP Black Star Promos")
        self.assertEqual(ext.resolve_by_id({"id": "me02.5-001"}, self.catalogue)[0], "Héros Transcendants")
        self.assertEqual(ext.resolve_by_id({"id": "me05-085"}, self.catalogue)[0], "Nuit Noire")

    def test_no_id_or_unknown_set_is_not_resolved(self):
        self.assertEqual(ext.resolve_by_id({"name": "Raichu"}, self.catalogue), ("", ""))
        self.assertEqual(ext.resolve_by_id({"id": "zzz-001"}, self.catalogue), ("", ""))

    def test_guard_fills_new_empty_cards_only(self):
        self.data["lots"][0]["cards"] = [c for c in self.data["lots"][0]["cards"] if c["card_uid"] != "card_twin"]
        # 3 cartes de Lot A sont deja sur disque (donc « existantes ») ; on ajoute des cartes nouvelles
        self.write_files()
        new_with_id = new_card("Sorcilence VMAX", "066", "", "swsh12.5-066", uid="card_new1")
        new_no_id = new_card("Raichu", "20", "", uid="card_new2")
        new_filled = new_card("Pikachu", "58", "Set de Base", "base1-58", uid="card_new3")
        self.data["lots"][0]["cards"] += [new_with_id, new_no_id, new_filled]
        changes = ext.complete_new_cards_extension(self.data, str(self.data_path), self.catalogue)
        self.assertEqual([c["card_uid"] for c in changes], ["card_new1"])
        self.assertEqual(new_with_id["set"], "Zénith Suprême")
        self.assertEqual(new_no_id["set"], "")
        self.assertEqual(new_filled["set"], "Set de Base")
        existing = next(c for c in self.data["lots"][0]["cards"] if c["card_uid"] == "card_Sorcilence_VMAX_066")
        self.assertEqual(existing["set"], "", "une carte deja enregistree n'est jamais touchee par le garde-fou")

    def test_guard_never_replaces_an_existing_extension(self):
        card = new_card("Sorcilence VMAX", "066", "Mon extension", "swsh12.5-066", uid="card_new")
        self.data["lots"][0]["cards"].append(card)
        self.assertEqual(ext.complete_new_cards_extension(self.data, str(self.data_path), self.catalogue), [])
        self.assertEqual(card["set"], "Mon extension")

    def test_guard_noop_without_file_on_disk(self):
        os.remove(self.data_path)
        card = new_card("Sorcilence VMAX", "066", "", "swsh12.5-066", uid="card_new")
        self.data["lots"][0]["cards"].append(card)
        self.assertEqual(ext.complete_new_cards_extension(self.data, str(self.data_path), self.catalogue), [])

    def test_sd_calls_the_guard_before_writing(self):
        import data as data_module

        card = new_card("Sorcilence VMAX", "066", "", "swsh12.5-066", uid="card_new")
        self.data["lots"][0]["cards"].append(card)
        written = {}
        with mock.patch.object(data_module, "DATA", str(self.data_path)), \
                mock.patch.object(data_module, "_reconcile_with_other_sessions"), \
                mock.patch.object(data_module, "_sd_write", side_effect=lambda d: written.update(snapshot=copy.deepcopy(d))), \
                mock.patch.object(data_module, "remember_data_base"), \
                mock.patch.object(ext, "load_catalogue", return_value=self.catalogue):
            data_module.sd(self.data)
        saved = next(c for c in written["snapshot"]["lots"][0]["cards"] if c["card_uid"] == "card_new")
        self.assertEqual(saved["set"], "Zénith Suprême")

    def test_sd_still_saves_when_the_guard_fails(self):
        import data as data_module

        written = []
        with mock.patch.object(data_module, "_reconcile_with_other_sessions"), \
                mock.patch.object(data_module, "complete_new_cards_extension", side_effect=RuntimeError("boom")), \
                mock.patch.object(data_module, "_sd_write", side_effect=lambda d: written.append(d)), \
                mock.patch.object(data_module, "remember_data_base"):
            data_module.sd(self.data)
        self.assertEqual(len(written), 1)


class CreationPathsTests(Fixture):
    """Un test par chemin de creation identifie : ce que le garde-fou complete, ce qui reste dans la file."""

    def run_guard(self, card):
        self.data["lots"][0]["cards"].append(card)
        ext.complete_new_cards_extension(self.data, str(self.data_path), self.catalogue)
        return card["set"]

    def test_path_lots_add_card_search_fallback(self):
        self.assertEqual(self.run_guard(new_card("Sorcilence VMAX", "066", "", "swsh12.5-066", uid="n1")), "Zénith Suprême")

    def test_path_popup_choisir_with_empty_candidate_set(self):
        self.assertEqual(self.run_guard(new_card("Roue-de-Fer-ex", "073", "", "svp-073", uid="n2", lang="fr")), "SVP Black Star Promos")

    def test_path_storage_copy_of_empty_card_gets_completed(self):
        copy_card = new_card("Sorcilence VMAX", "066", "", "swsh12.5-066", uid="n3", stored_from_lot="Lot A")
        self.assertEqual(self.run_guard(copy_card), "Zénith Suprême")

    def test_path_exchange_manual_entry_without_id_stays_in_queue(self):
        card = new_card("Plumeline", "24", "", uid="n4", received_by_exchange=True)
        self.assertEqual(self.run_guard(card), "")
        queue = ext.build_queue(self.data, self.drops, [], self.catalogue)
        self.assertIn("card_uid", next(i for i in queue if i["card_uid"] == "n4"))

    def test_path_collection_batch_typed_without_id_stays_in_queue(self):
        card = new_card("Raichu", "50", "", uid="n5", collection_batch_id="b1")
        self.assertEqual(self.run_guard(card), "")
        item = next(i for i in ext.build_queue(self.data, self.drops, [], self.catalogue) if i["card_uid"] == "n5")
        self.assertIn(item["confidence"], (ext.CONF_AMBIGUOUS, ext.CONF_NONE, ext.CONF_PROBABLE))

    def test_path_japanese_flag_only_counts_as_missing(self):
        card = new_card("Lugia", "003", "🇯🇵 ", "web1-003", uid="n6", japanese=True)
        self.data["lots"][0]["cards"].append(card)
        item = next(i for i in ext.build_queue(self.data, self.drops, [], self.catalogue) if i["card_uid"] == "n6")
        self.assertTrue(item["flag_only"])

    def test_path_drop_add_copies_the_extension_after_correction(self):
        result = self.apply([{"card_uid": "card_Sorcilence_VMAX_066", "lot_uid": "lot_a", "new": "Zénith Suprême"}])
        self.assertTrue(result["ok"])
        ref = self.drops["drops"][0]["cards"][0]
        self.assertEqual(ref["set"], "Zénith Suprême")


# =========================================================================== A : generateur


class GeneratorTests(unittest.TestCase):
    def test_single_card_without_extension_omits_the_segment(self):
        card = {"name": "Sorcilence VMAX", "number": "066", "set": ""}
        self.assertEqual(generate_title([card]), "Carte Pokémon - Sorcilence VMAX 066 - FR")
        self.assertEqual(generate_description([card]).splitlines()[0], "Vends Sorcilence VMAX 066 - FR")

    def test_never_na_nor_doubled_pokemon(self):
        for bad in ("N/A", "Pokémon", "🇯🇵 ", None):
            card = {"name": "Ho-Oh", "number": "1", "set": bad}
            prepared = prepare_listing([card])
            self.assertNotIn("N/A", prepared["title"] + prepared["description"])
            self.assertEqual(prepared["title"].count("Pokémon"), 1)
            self.assertEqual(prepared["title"], "Carte Pokémon - Ho-Oh 1 - FR")

    def test_title_with_extension_is_unchanged(self):
        card = {"name": "Rototaupe", "number": "124", "set": "Foudre Noire", "japanese": True}
        self.assertEqual(generate_title([card]), "Carte Pokémon - Rototaupe Japonaise 124 - Foudre Noire - JAP")

    def test_multi_card_titles_are_unchanged_and_missing_cards_listed(self):
        cards = [{"name": "A", "number": "1", "set": "Promo"}, {"name": "B", "number": "2", "set": ""}]
        self.assertEqual(generate_title(cards, "Plusieurs cartes"), "Lot cartes Pokémon - A 1, B 2 - FR")
        self.assertEqual([c["name"] for c in listing_missing_extension_cards(cards)], ["B"])


# =========================================================================== C : propositions


class ProposalTests(Fixture):
    def proposal(self, card):
        ctx = ext.ProposalContext(self.data, [], self.catalogue)
        return ext.propose_extension(card, ctx)

    def test_certain_from_identical_copy_and_catalogue(self):
        p = self.proposal(self.data["lots"][0]["cards"][0])
        self.assertEqual((p["confidence"], p["value"]), (ext.CONF_CERTAIN, "Zénith Suprême"))

    def test_certain_from_catalogue_id(self):
        p = self.proposal(self.data["lots"][0]["cards"][2])
        self.assertEqual((p["confidence"], p["value"]), (ext.CONF_CERTAIN, "SVP Black Star Promos"))

    def test_me05_is_a_certain_proposal_named_like_other_mega_sets(self):
        p = self.proposal(self.data["lots"][1]["cards"][1])
        self.assertEqual((p["confidence"], p["value"]), (ext.CONF_CERTAIN, "Nuit Noire"))
        self.assertNotIn("Méga-Évolution Nuit Noire", ext.EXTRA_SET_NAMES.values())

    def test_ambiguous_lists_the_candidates(self):
        p = self.proposal(self.data["lots"][1]["cards"][0])  # Raichu 50 sans id
        self.assertEqual(p["confidence"], ext.CONF_NONE)  # aucun Raichu dans la fixture
        pika = new_card("Pikachu", "58", "", uid="p58")
        self.data["lots"][0]["cards"].append(new_card("Pikachu", "58", "Set de Base", "base1-58", uid="p58b"))
        p2 = self.proposal(pika)
        self.assertIn(p2["confidence"], (ext.CONF_PROBABLE, ext.CONF_AMBIGUOUS))

    def test_flag_only_cards_are_in_the_queue_as_flag(self):
        queue = ext.build_queue(self.data, self.drops, [], self.catalogue)
        flag = next(i for i in queue if i["name"] == "Dracaufeu")
        self.assertTrue(flag["flag_only"])

    def test_queue_contains_drop_status_and_restock(self):
        queue = ext.build_queue(self.data, self.drops, [], self.catalogue)
        sorc = next(i for i in queue if i["card_uid"] == "card_Sorcilence_VMAX_066")
        mimantis = next(i for i in queue if i["card_uid"] == "card_Mimantis_085")
        self.assertEqual((sorc["drop"]["status"], sorc["drop"]["restock"]), ("online", False))
        self.assertEqual((mimantis["drop"]["status"], mimantis["drop"]["restock"]), ("to_photograph", True))

    def test_counters(self):
        counts = ext.count_missing_extensions(self.data, self.drops, [])
        self.assertEqual(counts["stock"], 6)  # 3 Lot A + Raichu + Mimantis + Dracaufeu (drapeau)
        self.assertEqual(counts["drop"], 2)
        self.assertEqual(counts["drop_par_statut"], {"online": 1, "to_photograph": 1})


# =========================================================================== D/C : ecriture, journal, annulation


class ApplyTests(Fixture):
    def snapshot(self):
        return copy.deepcopy(self.data), copy.deepcopy(self.drops)

    def test_only_empty_set_fields_change_and_statuses_are_untouched(self):
        before_data, before_drops = self.snapshot()
        changes = [{"card_uid": "card_Sorcilence_VMAX_066", "lot_uid": "lot_a", "new": "Zénith Suprême", "source": "t", "confidence": "certaine"},
                   {"card_uid": "card_Mimantis_085", "lot_uid": "lot_c", "new": "Nuit Noire", "source": "t", "confidence": "certaine"}]
        result = self.apply(changes)
        self.assertTrue(result["ok"])
        self.assertEqual(result["applied"], 2)
        self.assertEqual(self.saved, ["data", "drops"])

        def flat_diff(a, b, path=""):
            diffs = []
            if isinstance(a, dict) and isinstance(b, dict):
                for key in set(a) | set(b):
                    diffs += flat_diff(a.get(key), b.get(key), f"{path}/{key}")
            elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                for index, (x, y) in enumerate(zip(a, b)):
                    diffs += flat_diff(x, y, f"{path}[{index}]")
            elif a != b:
                diffs.append(path)
            return diffs

        data_diffs = flat_diff(before_data, self.data)
        drop_diffs = flat_diff(before_drops, self.drops)
        self.assertTrue(all(p.endswith("/set") for p in data_diffs + drop_diffs), data_diffs + drop_diffs)
        self.assertEqual(len(data_diffs), 2)
        self.assertEqual(len(drop_diffs), 2)
        statuses_before = [c["status"] for c in before_drops["drops"][0]["cards"]]
        self.assertEqual(statuses_before, [c["status"] for c in self.drops["drops"][0]["cards"]])

    def test_backups_and_journal_written_before_and_after(self):
        result = self.apply([{"card_uid": "card_Sorcilence_VMAX_066", "lot_uid": "lot_a", "new": "Zénith Suprême", "source": "catalogue", "confidence": "certaine"}])
        names = sorted(os.listdir(self.backups))
        self.assertEqual(len(names), 2)
        self.assertTrue(any(n.startswith("data.json.backup_") for n in names))
        saved_backup = json.loads(Path(self.backups, next(n for n in names if n.startswith("data.json"))).read_text(encoding="utf-8"))
        self.assertEqual(saved_backup["lots"][0]["cards"][0]["set"], "", "la sauvegarde contient l'ANCIENNE valeur")
        entries = ext.read_journal(self.journal)
        self.assertEqual(len(entries), 1)
        for key in ("card_uid", "old", "new", "source", "confidence", "at", "batch", "card", "lot"):
            self.assertIn(key, entries[0])
        self.assertEqual((entries[0]["old"], entries[0]["new"]), ("", "Zénith Suprême"))
        self.assertTrue(result["batch"])

    def test_existing_extension_is_never_replaced_without_confirmation(self):
        result = self.apply([{"card_uid": "card_twin", "lot_uid": "lot_a", "new": "Extension B"}])
        self.assertFalse(result["ok"])
        self.assertEqual(self.data["lots"][0]["cards"][1]["set"], "Zénith Suprême")
        self.assertEqual(self.saved, [])
        result = self.apply([{"card_uid": "card_twin", "lot_uid": "lot_a", "new": "Extension B"}], allow_replace=True)
        self.assertTrue(result["ok"])
        self.assertEqual(self.data["lots"][0]["cards"][1]["set"], "Extension B")

    def test_free_text_extension_is_accepted(self):
        result = self.apply([{"card_uid": "card_Raichu_50", "lot_uid": "lot_c", "new": "Extension maison (texte libre)"}])
        self.assertTrue(result["ok"])
        self.assertEqual(self.data["lots"][1]["cards"][0]["set"], "Extension maison (texte libre)")

    def test_invalid_values_are_skipped(self):
        for bad in ("", "N/A", "🇯🇵 "):
            result = self.apply([{"card_uid": "card_Raichu_50", "lot_uid": "lot_c", "new": bad}])
            self.assertFalse(result["ok"])
        self.assertEqual(self.data["lots"][1]["cards"][0]["set"], "")

    def test_unknown_card_is_skipped_not_fatal(self):
        result = self.apply([{"card_uid": "nope", "lot_uid": "lot_a", "new": "X"},
                             {"card_uid": "card_Raichu_50", "lot_uid": "lot_c", "new": "Y"}])
        self.assertTrue(result["ok"])
        self.assertEqual(result["applied"], 1)
        self.assertEqual(len(result["skipped"]), 1)

    def test_flag_only_card_can_be_replaced_without_confirmation(self):
        result = self.apply([{"card_uid": "card_Dracaufeu_066", "lot_uid": "lot_c", "new": "Écarlate et Violet 3"}])
        self.assertTrue(result["ok"])

    def test_undo_restores_old_values_and_logs(self):
        result = self.apply([{"card_uid": "card_Sorcilence_VMAX_066", "lot_uid": "lot_a", "new": "Zénith Suprême"}])
        undone = self.undo(result["batch"])
        self.assertTrue(undone["ok"])
        self.assertEqual(self.data["lots"][0]["cards"][0]["set"], "")
        self.assertEqual(self.drops["drops"][0]["cards"][0]["set"], "")
        self.assertEqual(ext.journal_batches(self.journal), [])
        self.assertFalse(self.undo(result["batch"])["ok"])

    def test_undo_leaves_a_card_modified_since(self):
        result = self.apply([{"card_uid": "card_Sorcilence_VMAX_066", "lot_uid": "lot_a", "new": "Zénith Suprême"}])
        self.data["lots"][0]["cards"][0]["set"] = "Modifiée à la main"
        undone = self.undo(result["batch"])
        self.assertFalse(undone["ok"])
        self.assertEqual(self.data["lots"][0]["cards"][0]["set"], "Modifiée à la main")


class OnlineListingsTests(Fixture):
    def test_online_card_corrected_is_listed_with_new_title(self):
        self.apply([{"card_uid": "card_Sorcilence_VMAX_066", "lot_uid": "lot_a", "new": "Zénith Suprême"},
                    {"card_uid": "card_Mimantis_085", "lot_uid": "lot_c", "new": "Nuit Noire"}])
        entries = ext.online_listings_to_update(self.data, self.drops, self.journal)
        self.assertEqual([e["ref"]["drop_item_id"] for e in entries], ["it1"], "seules les annonces EN LIGNE sont listées")
        title = prepare_listing([entries[0]["card"]])["title"]
        self.assertIn("Zénith Suprême", title)

    def test_online_card_still_missing_is_listed_as_to_fix_first(self):
        entries = ext.online_listings_to_update(self.data, self.drops, self.journal)
        self.assertTrue(entries[0]["still_missing"])

    def test_marked_listing_is_remembered(self):
        ext.mark_listing_updated("it1", self.journal)
        self.assertEqual(ext.listings_marked_updated(self.journal), {"it1"})

    def test_listing_status_never_changes(self):
        before = self.drops["drops"][0]["cards"][0]["status"]
        self.apply([{"card_uid": "card_Sorcilence_VMAX_066", "lot_uid": "lot_a", "new": "Zénith Suprême"}])
        ext.mark_listing_updated("it1", self.journal)
        self.assertEqual(self.drops["drops"][0]["cards"][0]["status"], before)


# =========================================================================== trace desactivee par defaut


class TraceTests(unittest.TestCase):
    def test_trace_is_off_by_default_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag, log = os.path.join(tmp, "trace.on"), os.path.join(tmp, "trace.log")
            with mock.patch.object(ext, "TRACE_FLAG_FILE", flag), mock.patch.object(ext, "TRACE_LOG_FILE", log), \
                    mock.patch.object(ext, "LOG_DIR", tmp), mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(ext.TRACE_ENV, None)
                self.assertFalse(ext.trace_enabled())
                ext.trace("test", x=1)
                self.assertFalse(os.path.exists(log))
                Path(flag).write_text("", encoding="utf-8")
                self.assertTrue(ext.trace_enabled())
                ext.trace("test", x=1)
                self.assertEqual(json.loads(Path(log).read_text(encoding="utf-8").splitlines()[0])["event"], "test")


if __name__ == "__main__":
    unittest.main()

"""Mots-cles des annonces (abreviations avant le numero) et totaux de numeros imprimes.

Tests purs sur des cartes fabriquees : aucun JSON metier n'est lu ni ecrit. Les totaux sont lus dans le
vrai sets_reference.json du projet (fichier de reference, pas un JSON metier) ; la rarete vient d'un cache
simule dans un dossier temporaire.
"""
from __future__ import annotations

import builtins
import contextlib
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from services import card_rarity_service as rarity
from services import listing_keyword_rules as rules
from services import vinted_listing_service as vls
from services.vinted_listing_service import (
    card_listing_keywords,
    full_card_number,
    generate_description,
    generate_title,
    prepare_listing,
    set_total_for_card,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.contextmanager
def project_cwd():
    previous = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(previous)


def paldea(number, name="Courrousinge", **extra):
    card = {"id": f"sv04.5-{number}", "name": name, "number": str(number), "set": "Destinées de Paldea"}
    card.update(extra)
    return card


def card(card_id, name, number, set_name, **extra):
    base = {"id": card_id, "name": name, "number": str(number), "set": set_name}
    base.update(extra)
    return base


class _Base(unittest.TestCase):
    """Totaux = vrai sets_reference.json ; cache de rarete = fichier temporaire (vide par defaut)."""

    def setUp(self):
        self._cwd = project_cwd()
        self._cwd.__enter__()
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.tmp.name, "cards_rarity_cache.json")
        patcher = mock.patch.object(rarity, "RARITY_CACHE_FILE", self.cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._cwd.__exit__, None, None, None)

    def write_rarity(self, **by_id):
        cards = {cid: {"status": "ok", "rarity": value[0], "category": value[1] if len(value) > 1 else "",
                       "suffix": "", "stage": "", "name": "", "source": "test", "fetched_at": "2026-10-15T00:00:00"}
                 for cid, value in by_id.items()}
        rarity.save_cache({"cards": cards}, path=self.cache_path, backup=False)


class ShinyRuleBoundsTests(_Base):
    def test_courrousinge_example_from_the_drop(self):
        self.assertEqual(
            generate_title([paldea(171)]),
            "Carte Pokémon - Courrousinge Shiny 171/091 - Destinées de Paldea - FR",
        )
        self.assertEqual(
            generate_description([paldea(171)]).splitlines()[0],
            "Vends Courrousinge Shiny 171/091 - Destinées de Paldea - FR",
        )

    def test_bounds_91_92_223_224(self):
        expected = {91: False, 92: True, 223: True, 224: False}
        for number, shiny in expected.items():
            with self.subTest(number=number):
                title = generate_title([paldea(number)])
                description = generate_description([paldea(number)]).splitlines()[0]
                self.assertEqual("Shiny" in title, shiny)
                self.assertEqual("Shiny" in description, shiny)
                self.assertEqual(card_listing_keywords(paldea(number)) == ("Shiny",), shiny)

    def test_chromatique_is_never_written(self):
        for number in (92, 171, 223):
            self.assertNotIn("Chromatique", generate_title([paldea(number)]))
            self.assertNotIn("Chromatique", generate_description([paldea(number)]).split("Tags :")[0])
        shiny_rarity = paldea(171, rarity="Chromatique")
        self.assertNotIn("Chromatique", generate_title([shiny_rarity]))
        self.assertEqual(generate_title([shiny_rarity]).count("Shiny"), 1)
        self.assertEqual(card_listing_keywords(shiny_rarity), ("Shiny",))

    def test_zero_padded_number_and_missing_id_use_the_set_name(self):
        padded = paldea(171)
        padded["number"] = "0171"
        self.assertIn("Shiny", generate_title([padded]))
        no_id = {"name": "Riolu", "number": "173", "set": "Destinées de Paldea"}
        self.assertIn("Riolu Shiny 173/091", generate_title([no_id]))

    def test_other_sets_with_the_same_numbers_are_untouched(self):
        other = card("sv01-171", "X", 171, "Écarlate et Violet")
        self.assertEqual(card_listing_keywords(other), ())
        self.assertNotIn("Shiny", generate_title([other]))

    def test_secret_cards_after_the_shiny_range_get_no_shiny_word(self):
        for number, name in ((225, "Superdofin"), (237, "Mashynn")):
            title = generate_title([paldea(number, name)])
            self.assertNotIn("Shiny", title)
            self.assertIn(f"{name} {number}/091", title)

    def test_shiny_vault_sv_cards_only_get_shiny(self):
        lokhlass = card("swsh4.5-SV111", "Lokhlass VMAX", "SV111", "Destinées Radieuses")
        title = generate_title([lokhlass])
        self.assertEqual(title, "Carte Pokémon - Lokhlass VMAX Shiny SV111/SV122 - Destinées Radieuses - FR")
        self.assertEqual(card_listing_keywords(lokhlass), ("Shiny",))
        self.assertNotIn(" SV ", f" {title} ")

    def test_shiny_rarity_outside_the_range(self):
        other = card("sv01-050", "Pikachu", "050", "Écarlate et Violet", rarity="Shiny Rare")
        self.assertEqual(card_listing_keywords(other), ("Shiny",))
        self.assertIn("Pikachu Shiny 050/198", generate_title([other]))


class NoWordForGalleriesTests(_Base):
    CASES = (
        ("swsh9-TG11", "Morphéo", "TG11", "Stars Étincelantes", "Morphéo TG11/TG30"),
        ("swsh12-TG05", "Évoli", "TG05", "Tempête Argentée", "Évoli TG05/TG30"),
        ("swsh12.5-GG17", "Roublenard", "GG17", "Zénith Suprême", "Roublenard GG17/GG70"),
        ("g1-RC13", "Jirachi", "RC13", "Générations", "Jirachi RC13/RC32"),
    )

    def test_no_added_word_and_number_keeps_its_prefix(self):
        for card_id, name, number, set_name, expected in self.CASES:
            with self.subTest(card=expected):
                c = card(card_id, name, number, set_name)
                self.assertEqual(card_listing_keywords(c), ())
                self.assertEqual(generate_title([c]), f"Carte Pokémon - {expected} - {set_name} - FR")
                self.assertEqual(generate_description([c]).splitlines()[0], f"Vends {expected} - {set_name} - FR")
                for word in ("Trainer Gallery", "Galarian Gallery", "Radiant Collection", "Galerie"):
                    self.assertNotIn(word, generate_title([c]))

    def test_removed_rules_are_really_gone(self):
        ids = {rule["id"] for rule in rules.LISTING_KEYWORD_RULES}
        self.assertFalse({"trainer-gallery", "galarian-gallery", "generations-radiant-collection"} & ids)
        for rule in rules.LISTING_KEYWORD_RULES:
            self.assertEqual(rule["words"], ("Shiny",), rule["id"])


class RarityKeywordTests(_Base):
    def test_ar_and_gold_from_the_rarity_cache_go_before_the_number(self):
        self.write_rarity(**{"sv08-160": ("Illustration rare",), "sv08-190": ("Hyper rare",)})
        ar = card("sv08-160", "Pikachu", "160", "Étincelles Déferlantes")
        gold = card("sv08-190", "Dracaufeu", "190", "Étincelles Déferlantes")
        self.assertEqual(generate_title([ar]), "Carte Pokémon - Pikachu AR 160/191 - Étincelles Déferlantes - FR")
        self.assertEqual(generate_title([gold]), "Carte Pokémon - Dracaufeu Gold 190/191 - Étincelles Déferlantes - FR")
        self.assertEqual(
            generate_description([gold]).splitlines()[0], "Vends Dracaufeu Gold 190/191 - Étincelles Déferlantes - FR"
        )

    def test_own_rarity_field_is_used_and_never_duplicated(self):
        ar = card("sv08-160", "Pikachu", "160", "Étincelles Déferlantes", rarity="Illustration rare")
        title = generate_title([ar])
        self.assertEqual(len(re.findall(r"\bar\b", title, flags=re.I)), 1)
        gold = card("sv08-190", "Dracaufeu Gold", "190", "Étincelles Déferlantes", rarity="Hyper rare")
        self.assertEqual(generate_title([gold]).lower().count("gold"), 1)
        # memes abreviations que celles des regles : « AR » et « Gold », jamais « ar » / « hr »
        self.assertIn("Pikachu AR 160", generate_title([ar]))
        plain_gold = card("sv08-191", "Dracaufeu", "191", "Étincelles Déferlantes", rarity="Hyper rare")
        self.assertIn("Dracaufeu Gold 191", generate_title([plain_gold]))
        self.assertNotRegex(generate_title([plain_gold]), r"\bhr\b")

    def test_ambiguous_and_unhandled_cases_add_nothing_automatically(self):
        self.write_rarity(**{"swsh1-300": ("Rare Holo VMAX",), "sv01-002": ("Rare Secrète",),
                             "sv01-003": ("Rare Alternative",), "swsh1-301": ("Secret Rare",),
                             "sv01-004": ("Illustration speciale",)})
        for card_id in ("swsh1-300", "sv01-002", "sv01-003", "swsh1-301", "sv01-004"):
            with self.subTest(card_id=card_id):
                c = card(card_id, "Test", card_id.split("-")[1], "Écarlate et Violet")
                self.assertEqual(card_listing_keywords(c), ())
        self.assertNotIn("fa_review", rules.RARITY_AUTO_CLASSES)

    def test_classification_accepts_french_and_english_labels(self):
        expected = {
            "Illustration rare": "ar", "Illustration Rare": "ar", "Hyper rare": "gold", "Hyper Rare": "gold",
            "Shiny Rare": "shiny", "Shiny Ultra Rare": "shiny", "Chromatique": "shiny",
            "Special Illustration Rare": "sir", "Illustration spéciale rare": "sir",
            "Secret Rare": "secret", "Rare Secrète": "secret", "Ultra Rare": "fa_review", "Rare Holo VMAX": "ambiguous",
            "Rare Holo VSTAR": "ambiguous", "Commune": "other", "Double rare": "other", "": "unknown",
            "Sans Rareté": "unknown",
        }
        for label, klass in expected.items():
            with self.subTest(label=label):
                self.assertEqual(rarity.classify_rarity(label), klass)

    def test_shiny_word_is_never_duplicated_between_rule_and_rarity(self):
        c = paldea(171, rarity="Shiny Rare")
        self.assertEqual(card_listing_keywords(c), ("Shiny",))
        self.assertEqual(generate_title([c]).count("Shiny"), 1)
        named = paldea(171, name="Courrousinge Shiny")
        self.assertEqual(generate_title([named]).count("Shiny"), 1)


class SpecialIllustrationAltTests(_Base):
    """Illustration speciale rare -> « Alt » avant le numero (titre, description, lignes de lot)."""

    LABELS = ("Special illustration rare", "Illustration spéciale rare", "Special Illustration Rare",
              "illustration speciale rare", "Rare illustration spéciale")

    def test_example_title_and_description_first_line(self):
        self.write_rarity(**{"sv04.5-232": ("Special illustration rare",)})
        mew = paldea(232, "Mew-ex")
        self.assertEqual(generate_title([mew]), "Carte Pokémon - Mew-ex Alt 232/091 - Destinées de Paldea - FR")
        self.assertEqual(generate_description([mew]).splitlines()[0], "Vends Mew-ex Alt 232/091 - Destinées de Paldea - FR")
        self.assertEqual(card_listing_keywords(mew), ("Alt",))

    def test_every_certain_label_gives_alt_and_only_once(self):
        for label in self.LABELS:
            with self.subTest(label=label):
                self.write_rarity(**{"sv08-230": (label,)})
                c = card("sv08-230", "Pikachu-ex", "230", "Étincelles Déferlantes")
                title = generate_title([c])
                self.assertEqual(rarity.rarity_class_for_card(c), "sir")
                self.assertEqual(len(re.findall(r"\bAlt\b", title)), 1, title)
                self.assertIn("Pikachu-ex Alt 230/191", title)

    def test_own_rarity_field_gives_alt_never_sir_or_long_form(self):
        c = card("sv08-230", "Pikachu-ex", "230", "Étincelles Déferlantes", rarity="Special illustration rare")
        title = generate_title([c])
        self.assertIn("Pikachu-ex Alt 230/191", title)
        self.assertEqual(len(re.findall(r"\bAlt\b", title)), 1)
        self.assertNotRegex(title, r"(?i)\bsir\b|speciale|special")
        self.assertEqual(len(re.findall(r"\bAlt\b", generate_description([c]).split("Tags")[0])), 1)

    def test_no_duplicate_when_alt_is_already_in_the_name(self):
        self.write_rarity(**{"sv08-230": ("Special illustration rare",)})
        c = card("sv08-230", "Pikachu-ex Alt", "230", "Étincelles Déferlantes")
        self.assertEqual(generate_title([c]).count("Alt"), 1)
        self.assertEqual(generate_description([c]).splitlines()[0].count("Alt"), 1)

    def test_unknown_or_uncertain_rarity_adds_no_word(self):
        c = card("sv08-230", "Pikachu-ex", "230", "Étincelles Déferlantes")
        self.assertNotIn("Alt", generate_title([c]))  # aucune rareté connue : ni numéro ni nom ne suffisent
        for label in ("", "Sans Rareté", "Illustration speciale", "Rare", "Double rare", "Rare Holo"):
            with self.subTest(label=label):
                self.write_rarity(**{"sv08-230": (label,)})
                self.assertNotIn("Alt", generate_title([c]))
        # un numéro très élevé ou un nom en « ex » ne déclenchent jamais le mot sans rareté
        high = card("sv08-260", "Mew-ex", "260", "Étincelles Déferlantes")
        self.assertNotIn("Alt", generate_title([high]))

    def test_alt_is_in_the_automatic_classes_and_secret_alternate_are_not(self):
        self.assertEqual(rules.RARITY_CLASS_WORDS["sir"], "Alt")
        self.assertIn("sir", rules.RARITY_AUTO_CLASSES)
        self.assertEqual(rules.RARITY_AUTO_CLASSES, ("shiny", "ar", "gold", "sir", "fa"))
        self.assertEqual(rules.RARITY_NOT_HANDLED_CLASSES, ("secret", "alternate"))
        self.assertNotIn("fa_review", rules.RARITY_AUTO_CLASSES)

    def test_title_is_never_over_100_and_alt_is_kept_last(self):
        self.write_rarity(**{"sv08-230": ("Special illustration rare",)})
        kept_alt, stages = False, set()
        for length in range(15, 70):
            c = card("sv08-230", "A" * length, "230", "Étincelles Déferlantes")
            title = generate_title([c])
            base = f"Carte Pokémon - {'A' * length} 230/191 - Étincelles Déferlantes - FR"
            if len(base) > 100 and len(title) > 100:
                self.assertEqual(title, base)  # rien ne tient : jamais coupé
                stages.add("unchanged")
                continue
            self.assertLessEqual(len(title), 100)
            self.assertTrue(title.endswith(" - FR"))
            self.assertNotIn("A" * length + " Al -", title)
            stages.add("alt" if " Alt " in title else "no-alt")
            if " Alt " in title:
                kept_alt = True
                self.assertTrue(title.startswith("Carte Pokémon - ") or title.startswith("Pokémon - "))
            else:
                self.assertIn(title[:8], ("Carte Po", "Pokémon "))
        self.assertTrue(kept_alt)
        # ordre monotone : tant que « Alt » tient, il est garde ; il saute seulement en dernier
        seen_no_alt = False
        for length in range(15, 70):
            c = card("sv08-230", "A" * length, "230", "Étincelles Déferlantes")
            has_alt = " Alt " in generate_title([c])
            if not has_alt:
                seen_no_alt = True
            self.assertFalse(seen_no_alt and has_alt)

    def test_multi_card_lot_has_an_alt_group_line_and_unchanged_title(self):
        self.write_rarity(**{"sv04.5-232": ("Special illustration rare",), "sv08-230": ("Special illustration rare",)})
        cards = [paldea(232, "Mew-ex"), card("sv08-230", "Pikachu-ex", "230", "Étincelles Déferlantes"),
                 card("sv01-005", "Évoli", "005", "Écarlate et Violet")]
        title = generate_title(cards, "Plusieurs cartes")
        self.assertEqual(title, "Lot cartes Pokémon - Mew-ex 232/091, Pikachu-ex 230/191, Évoli 005/198 - FR")
        description = generate_description(cards, "Plusieurs cartes")
        self.assertIn("Cartes Alt dans ce lot : Mew-ex 232/091, Pikachu-ex 230/191", description)
        self.assertNotIn("Évoli 005/198, ", description.split("Cartes Alt dans ce lot : ")[1].splitlines()[0])


    def test_alt_generation_writes_no_file(self):
        self.write_rarity(**{"sv04.5-232": ("Special illustration rare",)})
        real_open = builtins.open

        def guard(file, mode="r", *args, **kwargs):
            if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
                raise AssertionError(f"ecriture interdite pendant la generation : {file}")
            return real_open(file, mode, *args, **kwargs)

        with mock.patch("builtins.open", guard):
            self.assertIn("Alt", generate_title([paldea(232, "Mew-ex")]))
            prepare_listing([paldea(232, "Mew-ex")], "Carte seule")


class FullArtFaTests(_Base):
    """« Ultra Rare » : FA automatique pour ex / EX / V / GX et Dresseur ; VMAX / VSTAR listes sans mot."""

    def ultra(self, card_id, name, category="Pokémon", suffix="", number="200", set_name="Écarlate et Violet"):
        rarity.save_cache({"cards": {card_id: {"status": "ok", "rarity": "Ultra Rare", "category": category,
                                               "suffix": suffix, "stage": "", "name": name, "source": "test",
                                               "fetched_at": "2026-10-15T00:00:00"}}},
                          path=self.cache_path, backup=False)
        return card(card_id, name, number, set_name)

    def test_fa_goes_before_the_number_for_ex_v_gx_and_trainers(self):
        cases = [("sv01-200", "Chef-de-Fer-ex", "Pokémon", "", "Chef-de-Fer-ex FA 200/198"),
                 ("swsh1-200", "Pikachu V", "Pokémon", "", "Pikachu V FA 200/"),
                 ("sm1-200", "Dracaufeu GX", "Pokémon", "", "Dracaufeu GX FA 200/"),
                 ("xy1-200", "Mewtwo-EX", "Pokémon", "", "Mewtwo-EX FA 200/"),
                 ("sv01-201", "Mystère", "Pokémon", "ex", "Mystère FA 201/"),
                 ("sv01-202", "Mystère", "Pokémon", "GX", "Mystère FA 202/"),
                 ("sv01-203", "Mystère", "Pokémon", "V", "Mystère FA 203/"),
                 ("sv01-204", "Larry", "Dresseur", "", "Larry FA 204/"),
                 ("sv01-205", "Super Ball", "Trainer", "", "Super Ball FA 205/")]
        for card_id, name, category, suffix, expected in cases:
            with self.subTest(card=name, suffix=suffix):
                c = self.ultra(card_id, name, category, suffix, number=card_id.split("-")[1])
                self.assertEqual(rarity.rarity_class_for_card(c), "fa")
                self.assertEqual(card_listing_keywords(c), ("FA",))
                title = generate_title([c])
                self.assertIn(expected, title)
                self.assertEqual(len(re.findall(r"\bFA\b", title)), 1, title)
                first = generate_description([c]).splitlines()[0]
                self.assertIn(" FA ", first)
                self.assertLessEqual(len(title), 100)

    def test_vmax_vstar_and_unknown_subtypes_add_nothing(self):
        cases = [("swsh1-300", "Dracaufeu VMAX", "Pokémon", ""), ("swsh1-301", "Arceus VSTAR", "Pokémon", ""),
                 ("swsh1-302", "Mystère", "Pokémon", "VMAX"), ("swsh1-303", "Mystère", "Pokémon", "VSTAR"),
                 ("swsh1-304", "Pikachu V-UNION", "Pokémon", ""), ("sv01-305", "Énergie Spéciale", "Énergie", ""),
                 ("sv01-306", "Inconnu", "Pokémon", "")]
        for card_id, name, category, suffix in cases:
            with self.subTest(card=name, suffix=suffix):
                c = self.ultra(card_id, name, category, suffix, number=card_id.split("-")[1])
                self.assertEqual(rarity.rarity_class_for_card(c), "fa_review")
                self.assertEqual(card_listing_keywords(c), ())
                title = generate_title([c])
                self.assertNotRegex(title, r"\bFA\b")
                self.assertNotRegex(generate_description([c]).splitlines()[0], r"\bFA\b")
                self.assertNotRegex(title, r"\bur\b")

    def test_a_v_name_is_never_mistaken_for_vmax(self):
        self.assertEqual(rarity.ultra_rare_subtype("Pokémon", "", "Dracaufeu VMAX"), "vmax")
        self.assertEqual(rarity.ultra_rare_subtype("Pokémon", "", "Dracaufeu V"), "v")
        self.assertEqual(rarity.ultra_rare_subtype("Pokémon", "", "Arceus VSTAR"), "vstar")
        self.assertEqual(rarity.ultra_rare_subtype("Pokémon", "V", "Dracaufeu VMAX"), "vmax")

    def test_special_illustration_rare_never_gets_fa(self):
        self.write_rarity(**{"sv01-250": ("Special illustration rare",)})
        c = card("sv01-250", "Chef-de-Fer-ex", "250", "Écarlate et Violet")
        self.assertEqual(card_listing_keywords(c), ("Alt",))
        self.assertNotRegex(generate_title([c]), r"\bFA\b")

    def test_only_the_ultra_rare_label_triggers_fa(self):
        for label in ("Double rare", "Rare Holo", "Illustration rare", "Hyper rare", "Commune", "Rare"):
            with self.subTest(label=label):
                self.write_rarity(**{"sv01-210": (label, "Pokémon")})
                c = card("sv01-210", "Chef-de-Fer-ex", "210", "Écarlate et Violet")
                self.assertNotIn("FA", card_listing_keywords(c))

    def test_one_rarity_word_only_with_priority_alt_gold_ar_fa_shiny(self):
        # Shiny de la table (Destinées de Paldea 92-223) + une rareté : seule la rareté reste
        for label, word in (("Special illustration rare", "Alt"), ("Hyper rare", "Gold"),
                            ("Illustration rare", "AR"), ("Ultra Rare", "FA")):
            with self.subTest(label=label):
                self.write_rarity(**{"sv04.5-171": (label, "Pokémon")})
                c = paldea(171, "Courrousinge-ex")
                self.assertEqual(card_listing_keywords(c), (word,))
                title = generate_title([c])
                self.assertNotIn("Shiny", title)
                self.assertEqual(len(re.findall(r"\b(Alt|Gold|AR|FA|Shiny)\b", title)), 1, title)
        self.write_rarity()
        self.assertEqual(card_listing_keywords(paldea(171)), ("Shiny",))  # aucune autre : Shiny seul
        # champ « rarity » propre + « Ultra Rare » : ni « ur » ni deux mots
        own = card("sv01-200", "Chef-de-Fer-ex", "200", "Écarlate et Violet", rarity="Ultra Rare")
        title = generate_title([own])
        self.assertIn("Chef-de-Fer-ex FA 200/198", title)
        self.assertNotRegex(title, r"\bur\b")

    def test_multi_card_lot_group_lines_for_fa(self):
        a = self.ultra("sv01-200", "Chef-de-Fer-ex")
        rarity.save_cache({"cards": {
            "sv01-200": {"status": "ok", "rarity": "Ultra Rare", "category": "Pokémon", "suffix": "", "name": "Chef-de-Fer-ex"},
            "swsh1-300": {"status": "ok", "rarity": "Ultra Rare", "category": "Pokémon", "suffix": "", "name": "Dracaufeu VMAX"},
        }}, path=self.cache_path, backup=False)
        vmax = card("swsh1-300", "Dracaufeu VMAX", "300", "Épée et Bouclier")
        description = generate_description([a, vmax], "Plusieurs cartes")
        self.assertIn("Cartes FA dans ce lot : Chef-de-Fer-ex 200/198", description)
        self.assertNotIn("Dracaufeu VMAX 300/", description.split("Cartes FA dans ce lot : ")[1].splitlines()[0])
        self.assertEqual(generate_title([a, vmax], "Plusieurs cartes").count("FA"), 0)

    def test_long_title_keeps_fa_last_and_never_exceeds_100(self):
        flags = []
        for length in range(15, 70):
            name = "A" * (length - 3) + "-ex"
            c = self.ultra("sv08-230", name, number="230", set_name="Étincelles Déferlantes")
            title = generate_title([c])
            base = f"Carte Pokémon - {name} 230/191 - Étincelles Déferlantes - FR"
            if len(title) > 100:
                self.assertEqual(title, base)  # rien ne tient : titre inchange, jamais coupe
                flags.append(False)
                continue
            self.assertTrue(title.endswith(" - FR"))
            flags.append(" FA " in title)
        seen_missing = False
        for flag in flags:
            seen_missing = seen_missing or not flag
            self.assertFalse(seen_missing and flag)
        self.assertTrue(flags[0])

    def test_fa_generation_writes_no_file(self):
        c = self.ultra("sv01-200", "Chef-de-Fer-ex")
        real_open = builtins.open

        def guard(file, mode="r", *args, **kwargs):
            if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
                raise AssertionError(f"ecriture interdite pendant la generation : {file}")
            return real_open(file, mode, *args, **kwargs)

        with mock.patch("builtins.open", guard):
            self.assertIn(" FA ", generate_title([c]))
            prepare_listing([c], "Carte seule")


class TitleLengthTests(_Base):
    def test_title_never_exceeds_100_and_reduction_order_is_documented(self):
        stages = []
        for length in range(20, 60):
            c = {"name": "A" * length, "number": "171", "set": "Destinées de Paldea", "id": "sv04.5-171"}
            title = generate_title([c])
            plain = f"Carte Pokémon - {'A' * length} 171/091 - Destinées de Paldea - FR"
            if len(title) > 100:
                self.assertEqual(title, plain)  # rien ne tient : titre inchange, jamais coupe
                stage = "unchanged"
            elif title.startswith("Carte Pokémon - ") and "Shiny" in title:
                stage = "carte+mot"
            elif title.startswith("Pokémon - ") and "Shiny" in title:
                stage = "pokemon+mot"
            else:
                stage = "sans mot"
            if stage != "unchanged":
                self.assertLessEqual(len(title), 100)
                self.assertTrue(title.endswith(" - FR"))
            stages.append(stage)
        # l'ordre des reductions est monotone : « Carte » saute avant les abreviations
        order = ["carte+mot", "pokemon+mot", "sans mot", "unchanged"]
        ranks = [order.index(stage) for stage in stages]
        self.assertEqual(ranks, sorted(ranks))
        self.assertIn("pokemon+mot", stages)
        self.assertIn("carte+mot", stages)

    def test_fallback_order_constant(self):
        self.assertEqual(
            rules.TITLE_FALLBACK_ORDER,
            (("Carte Pokémon", "all"), ("Pokémon", "all"), ("Carte Pokémon", "first"), ("Pokémon", "first"),
             ("Carte Pokémon", "none"), ("Pokémon", "none")),
        )
        self.assertEqual(rules.MAX_TITLE_LENGTH, 100)

    def test_over_long_base_drops_carte_before_anything_else(self):
        c = {"name": "A" * 41, "number": "050", "set": "Écarlate et Violet", "id": "sv01-050"}
        long_title = generate_title([c])
        self.assertLessEqual(len(long_title), 100)
        c["name"] = "A" * 47
        self.assertTrue(generate_title([c]).startswith("Pokémon - ") or len(generate_title([c])) <= 100)


class MultiCardTests(_Base):
    def test_title_is_unchanged_and_description_groups_use_short_words(self):
        cards = [paldea(171), paldea(180, "Riolu"), card("sv01-005", "Pikachu", "005", "Écarlate et Violet")]
        title = generate_title(cards, "Plusieurs cartes")
        self.assertEqual(title, "Lot cartes Pokémon - Courrousinge 171/091, Riolu 180/091, Pikachu 005/198 - FR")
        self.assertNotIn("Shiny", title)
        description = generate_description(cards, "Plusieurs cartes")
        self.assertIn("Cartes Shiny dans ce lot : Courrousinge 171/091, Riolu 180/091", description)
        self.assertNotIn("Chromatique", description.split("Tags :")[0])

    def test_no_group_line_without_keywords(self):
        cards = [card("sv01-005", "Pikachu", "005", "Écarlate et Violet"), card("sv01-006", "Évoli", "006", "Écarlate et Violet")]
        self.assertNotIn("dans ce lot", generate_description(cards, "Plusieurs cartes"))


class NumberTotalTests(_Base):
    def test_paldea_total_is_91_not_198(self):
        self.assertEqual(set_total_for_card(paldea(171)), 91)
        self.assertEqual(full_card_number(paldea(171)), "171/091")
        self.assertEqual(full_card_number(paldea(5)), "005/091")

    def test_zero_padding_only_for_modern_blocks(self):
        self.assertEqual(full_card_number(card("sv01-27", "X", 27, "Écarlate et Violet")), "027/198")
        self.assertEqual(full_card_number(card("swsh4-5", "X", 5, "Voltage Éclatant")), "005/185")
        self.assertEqual(full_card_number(card("base1-4", "Dracaufeu", 4, "Set de Base")), "4/102")
        self.assertEqual(full_card_number(card("xy1-9", "X", 9, "XY")), "9/146")

    def test_subset_totals_for_prefixed_numbers(self):
        self.assertEqual(full_card_number(card("swsh9-TG11", "X", "TG11", "Stars Étincelantes")), "TG11/TG30")
        self.assertEqual(full_card_number(card("swsh12.5-GG17", "X", "GG17", "Zénith Suprême")), "GG17/GG70")
        self.assertEqual(full_card_number(card("swsh4.5-SV111", "X", "SV111", "Destinées Radieuses")), "SV111/SV122")
        self.assertEqual(full_card_number(card("g1-RC13", "X", "RC13", "Générations")), "RC13/RC32")

    def test_no_total_is_invented(self):
        for c in (
            card("svp-045", "Promo", "045", "Promos EV"),
            card("swshp-SWSH285", "Promo", "SWSH285", "Promos EB"),
            card("mep-003", "Promo", "003", "Promos Méga"),
            card("inconnu-1", "X", "12", "Extension qui n'existe pas"),
        ):
            with self.subTest(card=c["id"]):
                self.assertEqual(full_card_number(c), c["number"])

    def test_japanese_cards_never_get_a_french_total(self):
        ja = card("sv04.5-171", "Courrousinge", 171, "Destinées de Paldea", lang="ja")
        self.assertEqual(full_card_number(ja), "171")
        self.assertEqual(full_card_number(dict(ja, lang="", japanese=True)), "171")

    def test_secret_numbers_above_the_total_are_kept(self):
        self.assertEqual(full_card_number(paldea(225, "Superdofin")), "225/091")

    def test_explicit_number_with_total_is_kept_as_is(self):
        self.assertEqual(full_card_number(card("sv01-5", "X", "5/198", "Écarlate et Violet")), "5/198")
        self.assertEqual(full_card_number(card("sv01-5", "X", 5, "Écarlate et Violet", display_number="005/198")), "005/198")

    def test_tcgdex_id_wins_over_french_code_collisions(self):
        # « dp4 » (Duels au Sommet, 106) et « DP04 » (Aube Majestueuse, tcgdex dp5, 100) ne doivent pas se melanger
        self.assertEqual(set_total_for_card(card("dp4-1", "X", 1, "Duels au Sommet")), 106)
        self.assertEqual(set_total_for_card(card("dp5-1", "X", 1, "Aube Majestueuse")), 100)

    def test_title_shows_the_total_when_the_extension_has_none_yet(self):
        c = card("sv01-005", "Pikachu", "005", "")
        self.assertEqual(generate_title([c]), "Carte Pokémon - Pikachu 005/198 - FR")


class SetsReferenceFileTests(_Base):
    """Totaux officiels verifies (Bulbapedia, page de chaque extension) : le fichier de reference doit les contenir."""

    VERIFIED = {
        "sv01": 198, "sv02": 193, "sv03": 197, "sv03.5": 165, "sv04": 182, "sv04.5": 91, "sv05": 162, "sv06": 167,
        "sv06.5": 64, "sv07": 142, "sv08": 191, "sv08.5": 131, "sv09": 159, "sv10": 182, "sv10.5b": 86,
        "sv10.5w": 86, "swsh1": 202, "swsh2": 192, "swsh3": 189, "swsh3.5": 73, "swsh4": 185, "swsh4.5": 72,
        "swsh5": 163, "swsh6": 198, "swsh7": 203, "cel25": 25, "swsh8": 264, "swsh9": 172, "swsh10": 189,
        "swsh10.5": 78, "swsh11": 196, "swsh12": 195, "swsh12.5": 159, "me01": 132, "me02": 94, "me02.5": 217,
        "me03": 88, "me04": 86, "me05": 84, "dp4": 106, "dp5": 100, "dp7": 100, "xy8": 162, "ex13": 110,
        "base5": 82, "pl1": 127, "hgss1": 123, "col1": 95, "sm3.5": 73, "sm115": 68,
    }

    def entries(self):
        with open(os.path.join(ROOT, "sets_reference.json"), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        for block in data["sets"].values():
            for entry in block.get("sets", []):
                yield entry

    def test_verified_totals_are_in_the_file(self):
        by_id = {e["tcgdex_id"]: e["total"] for e in self.entries() if e.get("tcgdex_id")}
        for set_id, total in self.VERIFIED.items():
            with self.subTest(set_id=set_id):
                self.assertEqual(by_id.get(set_id), total)

    def test_tcgdex_ids_are_unique_and_codes_too(self):
        ids = [e["tcgdex_id"] for e in self.entries() if e.get("tcgdex_id")]
        codes = [e["code"] for e in self.entries()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(codes), len(set(codes)))

    def test_file_keeps_crlf_line_endings(self):
        with open(os.path.join(ROOT, "sets_reference.json"), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))


class NoBusinessWriteTests(_Base):
    def test_generating_texts_writes_no_file(self):
        real_open = builtins.open

        def guard(file, mode="r", *args, **kwargs):
            if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
                raise AssertionError(f"ecriture interdite pendant la generation : {file}")
            return real_open(file, mode, *args, **kwargs)

        cards = [paldea(171), card("swsh9-TG11", "Morphéo", "TG11", "Stars Étincelantes")]
        with mock.patch("builtins.open", guard):
            for listing_type in ("Carte seule", "Plusieurs cartes"):
                prepare_listing(cards[:1] if listing_type == "Carte seule" else cards, listing_type)


if __name__ == "__main__":
    unittest.main()

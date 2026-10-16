"""Pure helpers for generating Vinted listing text from Pokestock cards."""

from __future__ import annotations

import json
import os
import re
import unicodedata

from services.card_extension_service import card_extension_name, card_is_missing_extension
from services import card_rarity_service
from services.listing_keyword_rules import (
    LISTING_KEYWORD_RULES,
    MAX_TITLE_LENGTH,
    RARITY_AUTO_CLASSES,
    RARITY_CLASS_WORDS,
    RARITY_WORD_PRIORITY,
    SUBSET_TOTALS,
    TITLE_FALLBACK_ORDER,
    ZERO_PAD_WIDTH,
    ZERO_PADDED_SET_ID_PATTERN,
)


VINTED_TAGS = (
    "Pokémon, carte Pokémon, cartes Pokémon, JCC Pokémon, collection Pokémon, carte rare, vintage, EX, Méga, GX, V, VMAX, VSTAR, Niveau X, Star, Brillant, Radieux, Espèces Delta, Chromatique, Holo, Reverse, Arc-en-ciel, Full Art, Alternative, Illustration Rare, Illustration Spéciale Rare, Ultra Rare, Hyper Rare, Secrète, Dorée, Promo, Wizards, Set de Base, Jungle, Fossile, Team Rocket, Neo, bloc EX, Diamant Perle, Platine, Noir Blanc, XY, Soleil Lune, Épée Bouclier, Écarlate Violet, Destinées Occultes, Destinées Radieuses, Évolutions, Voltage Éclatant, Règne de Glace, Évolution Céleste, Poing de Fusion, Célébrations, Stars Étincelantes, Origine Perdue, Zénith Suprême, Évolutions à Paldea, Flammes Obsidiennes, 151, Faille Paradoxe, Destinées de Paldea, Forces Temporelles, Mascarade Crépusculaire, Couronne Stellaire, Étincelles Déferlantes, Évolutions Prismatiques, Aventures Ensemble, Rivalités Destinées, coffret dresseur, display, booster, tripack, blister, pokébox, coffret, scellé, Dracaufeu, Florizarre, Tortank, Salamèche, Pikachu, Évoli, Voltali, Aquali, Pyroli, Noctali, Mentali, Nymphali, Mew, Mewtwo, Ectoplasma, Lugia, Groudon, Kyogre, Rayquaza, Dialga, Palkia, Giratina, Arceus, Lucario, Gardevoir, Dracolosse, Tyranocif"
)


def clean_text(value, fallback=""):
    return " ".join(str(value or fallback).strip().split())


_SET_TOTALS_CACHE = {"stamp": None, "by_id": {}, "by_key": {}, "name_ids": {}}


def _set_code_variants(value):
    raw = clean_text(value).lower()
    if not raw:
        return set()
    normalized = re.sub(r"[^a-z0-9.]", "", raw)
    variants = {raw, normalized}
    variants.add(re.sub(r"([a-z]+)0+(\d)", r"\1\2", normalized))
    m = re.match(r"^([a-z]+)(\d)$", normalized)
    if m:
        variants.add(f"{m.group(1)}0{m.group(2)}")
    return {variant for variant in variants if variant}


def _load_set_totals():
    """Totaux imprimes des extensions, lus dans sets_reference.json (dossier courant).

    Deux index :
      by_id  : identifiant TCGdex (champ « tcgdex_id » : « sv04.5 », « swsh4 »...) -> total. PRIORITAIRE, car
               les codes francais (« EB04 », « DP04 ») ne sont pas les identifiants TCGdex et peuvent
               collisionner avec eux (« DP04 » ~ « dp4 » alors que « dp4 » est une autre extension).
      by_key : codes et noms d'extension (variantes sans zeros/accents) -> total, SEULEMENT pour les entrees qui
               n'ont pas de « tcgdex_id » (les noms servent de repli quand la carte n'a pas d'id).
    Relu seulement quand le fichier change.
    """
    path = os.path.join(os.getcwd(), "sets_reference.json")
    try:
        stat = os.stat(path)
        stamp = (path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        _SET_TOTALS_CACHE.update(stamp=None, by_id={}, by_key={}, name_ids={})
        return _SET_TOTALS_CACHE
    if _SET_TOTALS_CACHE["stamp"] == stamp:
        return _SET_TOTALS_CACHE

    by_id, by_key, name_ids = {}, {}, {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    for block in (data.get("sets", {}) or {}).values():
        for set_info in block.get("sets", []) or []:
            try:
                total = int(set_info.get("total", 0) or 0)
            except Exception:
                total = 0
            if total <= 0:
                continue
            tcgdex_id = clean_text(set_info.get("tcgdex_id", "")).lower()
            if tcgdex_id:
                by_id[tcgdex_id] = total
            name = set_info.get("name", "")
            for variant in _set_code_variants(name):
                by_key.setdefault(variant, total)
                if tcgdex_id:
                    name_ids.setdefault(variant, tcgdex_id)
            if not tcgdex_id:
                for variant in _set_code_variants(set_info.get("code", "")):
                    by_key.setdefault(variant, total)
    _SET_TOTALS_CACHE.update(stamp=stamp, by_id=by_id, by_key=by_key, name_ids=name_ids)
    return _SET_TOTALS_CACHE


def card_set_id(card):
    """Identifiant d'extension TCGdex de la carte (« sv04.5 » pour « sv04.5-171 »), sinon « set_id » ; « » si inconnu."""
    card_id = clean_text(card.get("id", ""))
    if "-" in card_id:
        return card_id.rsplit("-", 1)[0].lower()
    return clean_text(card.get("set_id", "")).lower()


def resolved_set_id(card):
    """Identifiant TCGdex de l'extension : celui de la carte, sinon deduit du NOM d'extension via sets_reference."""
    set_id = card_set_id(card)
    if set_id:
        return set_id
    name_ids = _load_set_totals()["name_ids"]
    for key in ("set", "extension", "serie"):
        for variant in _set_code_variants(card.get(key, "")):
            if variant in name_ids:
                return name_ids[variant]
    return ""


def set_total_for_card(card):
    """Total IMPRIME de l'extension (celui ecrit apres le « / » sur la carte), 0 si inconnu. Jamais invente."""
    for key in ("set_total", "total_in_set", "printed_total", "number_total"):
        try:
            total = int(card.get(key, 0) or 0)
        except Exception:
            total = 0
        if total > 0:
            return total

    totals = _load_set_totals()
    set_id = card_set_id(card)
    if set_id and set_id in totals["by_id"]:
        return totals["by_id"][set_id]

    candidates = []
    if set_id:
        candidates.append(set_id)
    candidates.extend(
        [
            card.get("set_id", ""),
            card.get("set_code", ""),
            card.get("serie_id", ""),
            card.get("set", ""),
            card.get("serie", ""),
            card.get("extension", ""),
        ]
    )
    for candidate in candidates:
        for variant in _set_code_variants(candidate):
            if variant in totals["by_id"]:
                return totals["by_id"][variant]
            total = totals["by_key"].get(variant)
            if total:
                return total
    return 0


def card_is_japanese(card):
    return bool(card.get("lang") == "ja" or card.get("japanese") or card.get("is_japanese"))


def _subset_total(card, prefix):
    """Total du sous-ensemble a prefixe (TG30, GG70, SV122, RC32), 0 si la carte n'est pas dans la table."""
    card_variants = _card_set_variants(card)
    for rule in SUBSET_TOTALS:
        if rule["prefix"] != prefix:
            continue
        wanted = set()
        for code in rule["set_ids"]:
            wanted |= _set_code_variants(code)
        if wanted & card_variants:
            return rule["total"]
    return 0


def _is_zero_padded_set(card):
    return bool(re.match(ZERO_PADDED_SET_ID_PATTERN, resolved_set_id(card)))


def full_card_number(card):
    """Numero imprime tel qu'il doit figurer dans l'annonce : « 171/091 », « TG11/TG30 », ou le numero seul.

    - un numero deja complet (« 66/078 ») ou stocke explicitement est conserve tel quel ;
    - le total vient de sets_reference.json (total imprime officiel) ou de la table SUBSET_TOTALS pour les
      sous-ensembles a prefixe ; jamais invente : sans total connu, on garde le numero seul ;
    - cartes japonaises : pas de total (les totaux de la reference sont ceux des cartes francaises) ;
    - blocs EV / EB / ME : numero et total completes a 3 chiffres comme sur la carte (« 027/185 »).
    """
    for key in ("full_number", "display_number", "collector_number", "printed_number", "card_number"):
        value = clean_text(card.get(key, ""))
        if value:
            return value

    number = clean_text(card.get("number", "") or card.get("num", "") or card.get("localId", ""))
    if not number:
        return ""
    if "/" in number or card_is_japanese(card):
        return number

    match = re.match(r"^([A-Za-z]*)(\d+)$", number)
    if not match:
        return number
    prefix, digits = match.group(1).upper(), match.group(2)
    if int(digits) <= 0:
        return number

    if prefix:
        total = _subset_total(card, prefix)
        return f"{number}/{prefix}{total}" if total > 0 else number

    total = set_total_for_card(card)
    if total <= 0:
        return number
    if _is_zero_padded_set(card):
        return f"{digits.zfill(ZERO_PAD_WIDTH)}/{str(total).zfill(ZERO_PAD_WIDTH)}"
    return f"{number}/{total}"


def normalize_search_text(value):
    text = clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.replace("-", " ").replace("_", " ")


def _compact_status(value):
    raw = clean_text(value)
    key = raw.lower()
    replacements = {
        "illustration rare": "AR",   # memes abreviations que celles de listing_keyword_rules (RARITY_CLASS_WORDS)
        "rare illustration": "AR",
        "ultra rare": "",   # jamais « ur » : « FA » vient de la classe de rareté (carte ex / V / GX / Dresseur), sinon rien
        "rare ultra": "",
        "hyper rare": "Gold",
        "rare hyper": "Gold",
        "rare secrete": "secrete",
        "secret rare": "secrete",
        "promo": "Promo",
    }
    if raw and card_rarity_service.classify_rarity(raw) == "shiny":
        return "Shiny"  # jamais « Chromatique » ni « Shiny Rare » dans une annonce
    if raw and card_rarity_service.classify_rarity(raw) == "sir":
        return "Alt"  # Illustration spéciale rare : abréviation courte, jamais « sir » ni la forme longue
    return replacements.get(key, raw)


def card_status_text(card):
    parts = []
    rarity = _compact_status(card.get("rarity", ""))
    special = clean_text(card.get("special_tag", ""))
    if rarity:
        parts.append(rarity)
    if card.get("is_reverse"):
        parts.append("Reverse")
    if card.get("is_ed1"):
        parts.append("1ère édition")
    if card.get("lang") == "ja" or card.get("japanese") or card.get("is_japanese"):
        parts.append("Japonaise")
    if special:
        parts.append(special)

    seen = set()
    output = []
    for part in parts:
        key = part.lower()
        if key not in seen:
            seen.add(key)
            output.append(part)
    return " ".join(output)


def card_listing_name(card, extra_words=()):
    """« Nom statut [abreviations] numero » : les abreviations (Shiny, AR, Gold...) vont juste AVANT le numero."""
    name = clean_text(card.get("name", "Carte Pokémon"))
    status = card_status_text(card)
    if status and not _missing_keywords([status], name):
        status = ""  # le nom contient deja ce mot (ex. « Dracaufeu Gold ») : pas de doublon
    number = full_card_number(card)
    pieces = [name]
    if status:
        pieces.append(status)
    pieces.extend(word for word in extra_words if word)
    if number:
        pieces.append(number)
    return clean_text(" ".join(pieces))


def card_extension(card):
    """Nom de l'extension, ou chaine VIDE quand elle manque (jamais « Pokémon » ni « N/A » dans l'annonce)."""
    return clean_text(card_extension_name(card))


def listing_missing_extension_cards(cards):
    """Cartes de l'annonce dont l'extension manque (pour l'alerte « Extension manquante »)."""
    return [card for card in cards or [] if card_is_missing_extension(card)]


def _number_parts(card):
    """(prefixe en majuscules, valeur numerique) du numero imprime ; (None, None) si illisible."""
    raw = clean_text(card.get("number", "") or card.get("display_number", "") or card.get("localId", ""))
    raw = raw.split("/")[0].strip()
    match = re.match(r"^([A-Za-z]*)0*(\d+)$", raw)
    if not match:
        return None, None
    return match.group(1).upper(), int(match.group(2))


def _card_set_variants(card):
    variants = set()
    card_id = clean_text(card.get("id", ""))
    if "-" in card_id:
        variants |= _set_code_variants(card_id.rsplit("-", 1)[0])
    for key in ("set_id", "set_code"):
        variants |= _set_code_variants(card.get(key, ""))
    return variants


def _rule_matches_card(rule, card, prefix, value):
    if not rule.get("enabled", True) or value is None:
        return False
    wanted_prefix = (rule.get("number_prefix") or "").upper()
    if prefix != wanted_prefix:
        return False
    low, high = rule.get("number_min"), rule.get("number_max")
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    rule_sets = set()
    for code in rule.get("set_ids", ()) or ():
        rule_sets |= _set_code_variants(code)
    if rule_sets & _card_set_variants(card):
        return True
    names = {normalize_search_text(name) for name in rule.get("set_names", ()) or ()}
    return normalize_search_text(card.get("set", "") or card.get("extension", "")) in names


def card_listing_keywords(card):
    """Abreviations recherchees par les acheteurs a ajouter pour cette carte (sans doublon, ordre stable).

    Deux sources : la table services/listing_keyword_rules.py (extension + numero imprime) et la rarete de la
    carte (champ « rarity » ou cache TCGdex), seulement pour les classes de RARITY_AUTO_CLASSES. Ne regarde
    jamais le titre : voir _missing_keywords.
    """
    if not isinstance(card, dict):
        return ()
    words = []
    prefix, value = _number_parts(card)
    for rule in LISTING_KEYWORD_RULES:
        if _rule_matches_card(rule, card, prefix, value):
            words.extend(rule.get("words", ()))
    klass = card_rarity_service.rarity_class_for_card(card)
    if klass in RARITY_AUTO_CLASSES and klass in RARITY_CLASS_WORDS:
        words.append(RARITY_CLASS_WORDS[klass])
    # Jamais deux abreviations de rarete : Alt > Gold > AR > FA > Shiny (« Shiny » de la table n'est garde que seul).
    rank = {normalize_search_text(RARITY_CLASS_WORDS[c]): n for n, c in enumerate(RARITY_WORD_PRIORITY)}
    rarity_words = [w for w in words if normalize_search_text(w) in rank]
    if len(rarity_words) > 1:
        best = min(rarity_words, key=lambda w: rank[normalize_search_text(w)])
        words = [w for w in words if w not in rarity_words] + [best]
    seen = set()
    output = []
    for word in words:
        key = normalize_search_text(word)
        if key and key not in seen:
            seen.add(key)
            output.append(word)
    return tuple(output)


def _missing_keywords(words, text):
    """Mots de `words` qui ne figurent pas deja (mot entier, sans accents ni casse) dans `text`."""
    haystack = f" {normalize_search_text(text)} "
    return [word for word in words if f" {normalize_search_text(word)} " not in haystack]


def _single_card_segments(card, language, extra_words=()):
    extension = card_extension(card)
    segments = [card_listing_name(card, extra_words)] + ([extension] if extension else [])
    return segments + [language]


def _single_card_title(card, language):
    """Titre d'une carte seule : « Carte Pokémon - Nom [abreviations] numero - Extension - FR », 100 caracteres max.

    Les abreviations sont celles qui ne figurent pas deja dans le titre. Si le titre depasse la limite, on essaie
    dans l'ordre TITLE_FALLBACK_ORDER (« Pokémon » au lieu de « Carte Pokémon » d'abord, abreviations gardees en
    dernier) et on garde la premiere variante entiere qui tient. Rien n'est jamais coupe en plein mot.
    """
    plain = clean_text(" - ".join(["Carte Pokémon"] + _single_card_segments(card, language)))
    missing = _missing_keywords(card_listing_keywords(card), plain)
    for prefix, mode in TITLE_FALLBACK_ORDER:
        words = {"all": missing, "first": missing[:1], "none": []}[mode]
        if mode != "none" and not words:
            continue
        candidate = clean_text(" - ".join([prefix] + _single_card_segments(card, language, words)))
        if len(candidate) <= MAX_TITLE_LENGTH:
            return candidate
    return plain


def _single_card_first_line(card, language):
    plain = " - ".join(_single_card_segments(card, language))
    missing = _missing_keywords(card_listing_keywords(card), plain)
    return "Vends " + " - ".join(_single_card_segments(card, language, missing))


def _multi_card_keyword_lines(cards):
    """Une ligne par groupe d'abreviations : « Cartes Shiny dans ce lot : Courrousinge 171/091, ... »."""
    groups = {}
    for card in cards:
        name = card_listing_name(card)
        missing = tuple(_missing_keywords(card_listing_keywords(card), name))
        if missing:
            groups.setdefault(missing, []).append(name)
    return [f"Cartes {' '.join(words)} dans ce lot : {', '.join(names)}" for words, names in groups.items()]


def listing_language_label(cards):
    languages = {
        "JAP" if card.get("lang") == "ja" or card.get("japanese") or card.get("is_japanese") else "FR"
        for card in cards or []
    }
    if languages == {"JAP"}:
        return "JAP"
    if languages == {"FR", "JAP"}:
        return "FR/JAP"
    return "FR"


def suggested_price(card):
    for key in (
        "listing_price",
        "display_price",
        "selling_price",
        "price",
        "prix",
        "suggested_price",
        "sale_price",
        "collection_current_value",
        "current_value",
        "estimated_value",
        "value",
    ):
        try:
            value = float(card.get(key, 0) or 0)
        except Exception:
            value = 0.0
        if value > 0:
            return value
    return 0.0


def total_suggested_price(cards):
    return sum(suggested_price(card) for card in cards)


def card_search_blob(card):
    return normalize_search_text(
        " ".join(
            [
                clean_text(card.get("name", "")),
                clean_text(card.get("number", "")),
                full_card_number(card),
                clean_text(card.get("set", "")),
                clean_text(card.get("serie", "")),
                clean_text(card.get("extension", "")),
                clean_text(card.get("lot_name", "")),
                card_status_text(card),
            ]
        )
    )


def filter_cards_for_listing(cards, query, limit=24):
    cards = list(cards or [])
    q = normalize_search_text(query)
    if not q:
        return []

    terms = [term for term in q.split() if term]
    matches = []
    for card in cards:
        blob = card_search_blob(card)
        if all(term in blob for term in terms):
            matches.append(card)
        if len(matches) >= limit:
            break
    return matches


def generate_title(cards, listing_type="Carte seule"):
    cards = list(cards or [])
    if not cards:
        return ""
    language = listing_language_label(cards)
    if listing_type == "Plusieurs cartes" or len(cards) > 1:
        names = [card_listing_name(card) for card in cards[:3]]
        return clean_text(f"Lot cartes Pokémon - {', '.join(names)} - {language}")

    return _single_card_title(cards[0], language)


def generate_description(cards, listing_type="Carte seule"):
    cards = list(cards or [])
    if not cards:
        return ""
    language = listing_language_label(cards)
    if listing_type == "Plusieurs cartes" or len(cards) > 1:
        first_line = "Vends lot de cartes Pokémon comprenant : " + ", ".join(
            card_listing_name(card) for card in cards
        ) + f" - {language}"
        first_line = "\n".join([first_line] + _multi_card_keyword_lines(cards))
    else:
        first_line = _single_card_first_line(cards[0], language)

    return (
        f"{first_line}\n\n"
        "Envoi sous sleeve ➡️ top loader ➡️ enveloppe bullée\n\n"
        "N'hésitez à faire un tour sur mon compte, pas mal d'autres cartes sont dispo.\n"
        "N'hésitez pas, également, si vous avez besoin de plus de renseignement ou de photos notamment pour l'état des cartes.\n\n"
        "Remise en main propre préférée dans le Morbihan (56) ou envoi via Mondial Relay, Colissimo, Chronopost etc...\n\n"
        "Je fais des drops de cartes régulièrement. N'hésitez pas à vous abonner à mon compte Vinted pour ne pas manquer les prochains. 😁\n\n"
        f"Tags : {VINTED_TAGS}"
    )


def selection_signature(cards, listing_type):
    ids = []
    for card in cards or []:
        ids.append(
            "|".join(
                [
                    clean_text(card.get("lot_uid", "")),
                    clean_text(card.get("card_uid", "")),
                    clean_text(card.get("name", "")),
                    clean_text(card.get("number", "")),
                    clean_text(card.get("set", "")),
                ]
            )
        )
    return f"{listing_type}::" + "||".join(ids)


def prepare_listing(cards, listing_type="Carte seule"):
    cards = list(cards or [])
    total = total_suggested_price(cards)
    return {
        "title": generate_title(cards, listing_type),
        "description": generate_description(cards, listing_type),
        "suggested_price": total,
        "has_price": total > 0,
        "signature": selection_signature(cards, listing_type),
    }


def listing_price_text(cards, fp_func=None):
    total = total_suggested_price(cards)
    if total <= 0:
        return "Prix à définir"
    if fp_func:
        return fp_func(total)
    return f"{total:.2f}€"

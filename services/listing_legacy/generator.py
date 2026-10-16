"""ANCIEN generateur de titres / descriptions Vinted (etat du 15/10/2026 avant les nouvelles regles).

Copie FIGEE, utilisee uniquement par services/listing_text_service.py pour reconnaitre un texte « ancien
format » (ex. « Courrousinge 171/198 ... Shiny Chromatique »). Ne plus la modifier : les regles vivantes sont
dans services/vinted_listing_service.py et services/listing_keyword_rules.py. Les totaux d'extension d'epoque
sont dans sets_reference_legacy.json (a cote de ce fichier).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata

from services.card_extension_service import card_extension_name, card_is_missing_extension
from services.listing_legacy.keyword_rules import (
    LISTING_KEYWORD_RULES,
    MAX_TITLE_LENGTH,
    RARITY_SHINY_MARKERS,
    RARITY_SHINY_WORDS,
    TITLE_FALLBACK_ORDER,
)


VINTED_TAGS = (
    "Pokémon, carte Pokémon, cartes Pokémon, JCC Pokémon, collection Pokémon, carte rare, vintage, EX, Méga, GX, V, VMAX, VSTAR, Niveau X, Star, Brillant, Radieux, Espèces Delta, Chromatique, Holo, Reverse, Arc-en-ciel, Full Art, Alternative, Illustration Rare, Illustration Spéciale Rare, Ultra Rare, Hyper Rare, Secrète, Dorée, Promo, Wizards, Set de Base, Jungle, Fossile, Team Rocket, Neo, bloc EX, Diamant Perle, Platine, Noir Blanc, XY, Soleil Lune, Épée Bouclier, Écarlate Violet, Destinées Occultes, Destinées Radieuses, Évolutions, Voltage Éclatant, Règne de Glace, Évolution Céleste, Poing de Fusion, Célébrations, Stars Étincelantes, Origine Perdue, Zénith Suprême, Évolutions à Paldea, Flammes Obsidiennes, 151, Faille Paradoxe, Destinées de Paldea, Forces Temporelles, Mascarade Crépusculaire, Couronne Stellaire, Étincelles Déferlantes, Évolutions Prismatiques, Aventures Ensemble, Rivalités Destinées, coffret dresseur, display, booster, tripack, blister, pokébox, coffret, scellé, Dracaufeu, Florizarre, Tortank, Salamèche, Pikachu, Évoli, Voltali, Aquali, Pyroli, Noctali, Mentali, Nymphali, Mew, Mewtwo, Ectoplasma, Lugia, Groudon, Kyogre, Rayquaza, Dialga, Palkia, Giratina, Arceus, Lucario, Gardevoir, Dracolosse, Tyranocif"
)


def clean_text(value, fallback=""):
    return " ".join(str(value or fallback).strip().split())


_SET_TOTALS_CACHE = None


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
    global _SET_TOTALS_CACHE
    if _SET_TOTALS_CACHE is not None:
        return _SET_TOTALS_CACHE

    totals = {}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sets_reference_legacy.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        _SET_TOTALS_CACHE = totals
        return totals

    for block in (data.get("sets", {}) or {}).values():
        for set_info in block.get("sets", []) or []:
            try:
                total = int(set_info.get("total", 0) or 0)
            except Exception:
                total = 0
            if total <= 0:
                continue
            for candidate in (set_info.get("code", ""), set_info.get("name", "")):
                for variant in _set_code_variants(candidate):
                    totals[variant] = total
    _SET_TOTALS_CACHE = totals
    return totals


def set_total_for_card(card):
    for key in ("set_total", "total_in_set", "printed_total", "number_total"):
        try:
            total = int(card.get(key, 0) or 0)
        except Exception:
            total = 0
        if total > 0:
            return total

    totals = _load_set_totals()
    candidates = []
    card_id = clean_text(card.get("id", ""))
    if "-" in card_id:
        candidates.append(card_id.rsplit("-", 1)[0])
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
            total = totals.get(variant)
            if total:
                return total
    return 0


def full_card_number(card):
    for key in ("full_number", "display_number", "collector_number", "printed_number", "card_number"):
        value = clean_text(card.get(key, ""))
        if value:
            return value

    number = clean_text(card.get("number", "") or card.get("num", "") or card.get("localId", ""))
    if not number:
        return ""
    if "/" in number:
        return number

    total = set_total_for_card(card)
    if total <= 0:
        return number

    stripped = number.lstrip("0") or number
    try:
        number_int = int(stripped)
    except Exception:
        return number
    if number_int <= 0:
        return number
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
        "illustration rare": "ar",
        "rare illustration": "ar",
        "special illustration rare": "sir",
        "rare illustration speciale": "sir",
        "ultra rare": "ur",
        "hyper rare": "hr",
        "rare secrete": "secrete",
        "secret rare": "secrete",
        "promo": "Promo",
    }
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


def card_listing_name(card):
    name = clean_text(card.get("name", "Carte Pokémon"))
    status = card_status_text(card)
    number = full_card_number(card)
    pieces = [name]
    if status:
        pieces.append(status)
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
    """Mots recherches par les acheteurs a ajouter pour cette carte (sans doublon, ordre stable).

    Priorite a la rarete du catalogue quand elle indique shiny/chromatique, puis a la table de
    regles services/listing_keyword_rules.py. Ne regarde jamais le titre : voir _missing_keywords.
    """
    if not isinstance(card, dict):
        return ()
    words = []
    rarity = normalize_search_text(card.get("rarity", ""))
    if rarity and any(marker in rarity for marker in RARITY_SHINY_MARKERS):
        words.extend(RARITY_SHINY_WORDS)
    prefix, value = _number_parts(card)
    for rule in LISTING_KEYWORD_RULES:
        if _rule_matches_card(rule, card, prefix, value):
            words.extend(rule.get("words", ()))
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
    segments = [card_listing_name(card)] + ([extension] if extension else [])
    if extra_words:
        segments.append(" ".join(extra_words))
    return segments + [language]


def _single_card_title(card, language):
    base = clean_text(" - ".join(["Carte Pokémon"] + _single_card_segments(card, language)))
    missing = _missing_keywords(card_listing_keywords(card), base)
    if not missing or len(base) > MAX_TITLE_LENGTH:
        return base
    for prefix, mode in TITLE_FALLBACK_ORDER:
        words = missing if mode == "all" else missing[:1]
        candidate = clean_text(" - ".join([prefix] + _single_card_segments(card, language, words)))
        if len(candidate) <= MAX_TITLE_LENGTH:
            return candidate
    return base


def _single_card_first_line(card, language):
    base_segments = _single_card_segments(card, language)
    missing = _missing_keywords(card_listing_keywords(card), " - ".join(base_segments))
    return "Vends " + " - ".join(_single_card_segments(card, language, missing))


def _multi_card_keyword_lines(cards):
    """Une ligne par groupe de mots manquants : « Cartes Shiny Chromatique dans ce lot : A, B »."""
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

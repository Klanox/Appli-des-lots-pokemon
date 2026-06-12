"""Pure helpers for generating Vinted listing text from Pokestock cards."""

from __future__ import annotations

import json
import os
import re
import unicodedata


VINTED_TAGS = (
    "Ex, Mega, GX, V, Vmax, X, Star, Brillant, Lumineux, Obscur, radieux, "
    "Espèces delta, shiny, Holo, Reverse, Rainbow, ds, 3ds, Full art, alternative, "
    "Alt, Magnifique, Amazing, Secrete, gold, Wizards, set de base, Neo, jungle, "
    "fossile, rocket, aquapolis, expédition, bloc Ex, diamant perle, noir, blanc, "
    "XY, Soleil Lune, ecarlate, violet, SL, EB, EV, Rivalités Destinées, force "
    "temporelle, couronne stellaire, soleil et lune, étincelles déferlantes, "
    "Edition Jungle, Fossil, Team Rocket, Gym Heroes, Etb, coffret dresseur, "
    "display, tripack, booster, blister, tin box, whisper, jackmad, pokebox, "
    "loose, scellé, Destinees radieuses, occultes, Evolutions, Voltage éclatant, "
    "Styles de combat, Règne de glace, Evolution céleste, Poing de fusion, Mcdo, "
    "Dracaufeu, Florizarre, Tortank, Salameche, Reptincel, Carapuce, Carabaffe, "
    "Bulbizarre, Herbizarre, Mew, Mewtwo, Pikachu, Evoli, Voltali, Aquali, Pyroli, "
    "Noctali, Mentali, Phylalli, Givrali, Nymphali, Groudon, Kyogre, Rayquaza, "
    "Pingoleon, Brasegali, Dialga, Palkia, Giratina, Arceus, Lucario, Electhor, "
    "Artikodin, Rayquaza, 70 71 72 73 74 75 76 77 78 79 80 81 82 83 84 85 86 "
    "87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104 105 106 107 "
    "108 109 110 111 112 113 114 115 116 117 118 119 120 121 122 123 124 125 "
    "126 127 128 129 130 131 132 133 134 135 136 137 138 139 140 141 142"
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
    path = os.path.join(os.getcwd(), "sets_reference.json")
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
    if card.get("lang") == "ja" or card.get("is_japanese"):
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
    return clean_text(card.get("set", ""), "Pokémon")


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
    if listing_type == "Plusieurs cartes" or len(cards) > 1:
        names = [card_listing_name(card) for card in cards[:3]]
        return clean_text(f"Lot cartes Pokémon - {', '.join(names)} - FR")

    card = cards[0]
    listing_name = card_listing_name(card)
    extension = card_extension(card)
    return clean_text(f"Carte Pokémon - {listing_name} - {extension} - FR")


def generate_description(cards, listing_type="Carte seule"):
    cards = list(cards or [])
    if not cards:
        return ""
    if listing_type == "Plusieurs cartes" or len(cards) > 1:
        first_line = "Vends lot de cartes Pokémon comprenant : " + ", ".join(
            card_listing_name(card) for card in cards
        )
    else:
        card = cards[0]
        first_line = f"Vends {card_listing_name(card)} - {card_extension(card)} - FR"

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

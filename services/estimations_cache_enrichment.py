"""Targeted TCGDex cache enrichment for Estimations searches."""

from __future__ import annotations

import re

import requests

from services.card_cache_service import save_cards_cache_to_disk


SET_TAG_TO_SET_IDS = {
    "151": ["sv03.5"],
    "mew": ["sv03.5"],
    "pre": ["sv08.5"],
    "svp": ["svp"],
    "sm": ["smp"],
    "swsh": ["swshp"],
    "mep": ["mep"],
    "xy": ["xyp"],
    "ssp": ["sv08"],
    "twm": ["sv06"],
    "cri": ["sm4"],
    "obf": ["sv03"],
}


POCKET_SET_NAMES = {
    "puissance génétique",
    "puissance genetique",
    "ile fabuleuse",
    "île fabuleuse",
    "choc spatio-temporel",
    "choc spatio temporel",
    "lumière triomphale",
    "lumiere triomphale",
    "gardiens astraux",
    "crise extra-dimensionnelle",
    "crise extra dimensionnelle",
    "sagesse entre ciel et mer",
}


def is_pokemon_pocket_card(card, set_name="", set_id=""):
    card = card or {}
    set_name = str(set_name or card.get("set") or card.get("set_name") or "").strip().lower()
    set_id = str(set_id or card.get("set_id") or "").strip().lower()
    card_id = str(card.get("id") or card.get("card_id") or "").strip().lower()
    image_blob = " ".join(str(card.get(key) or "") for key in ("image", "image_url", "image_url_en", "imageUrl")).lower()
    metadata_blob = " ".join(str(card.get(key) or "") for key in ("game", "product", "source", "series", "category", "tcg", "tags")).lower()
    explicit_blob = f" {set_name} {set_id} {card_id} {image_blob} {metadata_blob} "
    pocket_id_match = bool(re.match(r"^(a|pa)\d+[a-z]?[-_]", card_id))
    return (
        "/tcgp/" in explicit_blob
        or "tcg pocket" in explicit_blob
        or "pokemon trading card game pocket" in explicit_blob
        or "pokémon trading card game pocket" in explicit_blob
        or "ptcgp" in explicit_blob
        or (pocket_id_match and set_name in POCKET_SET_NAMES)
    )


def _tcgdex_get_json(url):
    try:
        try:
            import truststore

            truststore.inject_into_ssl()
        except Exception:
            pass
        response = requests.get(url, timeout=8)
    except requests.exceptions.SSLError:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(url, timeout=8, verify=False)
    response.raise_for_status()
    return response.json()


def _candidate_set_ids(set_tags):
    seen = set()
    result = []
    for tag in set_tags or []:
        tag_norm = str(tag or "").strip().lower().replace(" ", "")
        if not tag_norm:
            continue
        candidates = SET_TAG_TO_SET_IDS.get(tag_norm, [tag_norm])
        for set_id in candidates:
            if set_id and set_id not in seen:
                seen.add(set_id)
                result.append(set_id)
    return result[:4]


def _normalize_tcgdex_image(url):
    url = str(url or "").strip()
    if url and "tcgdex.net" in url and not url.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return f"{url}/high.webp"
    return url


def _add_card_to_index(cards_index, card, set_name, set_id, normalize_func):
    if not isinstance(card, dict):
        return False
    if is_pokemon_pocket_card(card, set_name=set_name, set_id=set_id):
        return False
    name = str(card.get("name") or "").strip()
    if not name:
        return False
    name_key = normalize_func(name)
    if not name_key:
        return False
    cards_index.setdefault(name_key, [])
    card_id = str(card.get("id") or "").strip()
    normalized_card = dict(card)
    if normalized_card.get("image"):
        normalized_card["image"] = _normalize_tcgdex_image(normalized_card.get("image"))
    for index, existing in enumerate(cards_index[name_key]):
        try:
            existing_card = existing[0]
            existing_set_id = existing[2] if len(existing) > 2 else ""
        except Exception:
            continue
        if card_id and existing_card.get("id") == card_id:
            cards_index[name_key][index] = (normalized_card, set_name, set_id)
            return False
        if not card_id and existing_card.get("localId") == normalized_card.get("localId") and existing_set_id == set_id:
            cards_index[name_key][index] = (normalized_card, set_name, set_id)
            return False
    cards_index[name_key].append((normalized_card, set_name, set_id))
    return True


def enrich_estimations_card_cache(cards_index, set_tags, normalize_func):
    """Fetch only requested TCGDex sets and merge them into cards_index.

    This writes cards_cache.json, but never touches app business JSON files.
    """
    if not isinstance(cards_index, dict):
        cards_index = {}
    set_ids = _candidate_set_ids(set_tags)
    fetched = 0
    added = 0
    errors = []
    sources = []
    for set_id in set_ids:
        try:
            url = f"https://api.tcgdex.net/v2/fr/sets/{set_id}"
            set_data = _tcgdex_get_json(url)
            set_name = set_data.get("name", set_id)
            cards = set_data.get("cards", []) or []
            fetched += len(cards)
            sources.append(set_id)
            for card in cards:
                if _add_card_to_index(cards_index, card, set_name, set_id, normalize_func):
                    added += 1
        except Exception as exc:
            errors.append(f"{set_id}: {exc}")
    if sources:
        save_cards_cache_to_disk(cards_index)
    return {
        "cards_index": cards_index,
        "requested_sets": set_ids,
        "sources": sources,
        "fetched": fetched,
        "added": added,
        "errors": errors,
    }

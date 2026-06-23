"""Targeted TCGDex cache enrichment for Estimations searches."""

from __future__ import annotations

import re
import unicodedata

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


def _fold_text(value):
    text = str(value or "").strip().lower()
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def _flatten_metadata(value, depth=0):
    if depth > 3:
        return []
    if isinstance(value, dict):
        parts = []
        for key, nested in value.items():
            parts.append(str(key))
            parts.extend(_flatten_metadata(nested, depth + 1))
        return parts
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            parts.extend(_flatten_metadata(item, depth + 1))
        return parts
    return [str(value or "")]


def is_pokemon_pocket_card(card, set_name="", set_id=""):
    card = card or {}
    set_name = str(set_name or card.get("set") or card.get("set_name") or "").strip().lower()
    set_id = str(set_id or card.get("set_id") or "").strip().lower()
    card_id = str(card.get("id") or card.get("card_id") or "").strip().lower()
    image_blob = " ".join(str(card.get(key) or "") for key in ("image", "image_url", "image_url_en", "imageUrl"))
    metadata_blob = " ".join(_flatten_metadata({key: card.get(key) for key in ("game", "product", "source", "series", "category", "tcg", "tags", "metadata", "set", "set_id", "set_name", "format", "type")}))
    explicit_blob = f" {_fold_text(set_name)} {_fold_text(set_id)} {_fold_text(card_id)} {_fold_text(image_blob)} {_fold_text(metadata_blob)} "
    pocket_id_match = bool(re.match(r"^(a|pa)\d+[a-z]?[-_]", card_id) or re.match(r"^(a|pa)\d+[a-z]?$", set_id))
    return (
        "/tcgp/" in explicit_blob
        or "tcg pocket" in explicit_blob
        or "pokemon trading card game pocket" in explicit_blob
        or "ptcgp" in explicit_blob
        or " tcgp " in explicit_blob
        or (pocket_id_match and (_fold_text(set_name) in POCKET_SET_NAMES or set_id.startswith(("a", "pa"))))
    )


def is_physical_pokemon_tcg_card(card, set_name="", set_id=""):
    return not is_pokemon_pocket_card(card, set_name=set_name, set_id=set_id)

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


def _metadata_values_for_tags(card):
    card = card or {}
    values = []
    for key in ("name", "rarity", "category", "special", "special_tag", "variant"):
        values.append(card.get(key, ""))
    for key in ("tags", "card_tags", "subtypes", "types"):
        raw = card.get(key)
        if isinstance(raw, (list, tuple, set)):
            values.extend(raw)
        else:
            values.append(raw)
    variants = card.get("variants")
    if isinstance(variants, dict):
        values.extend(key for key, enabled in variants.items() if enabled)
    return values


def _normalized_metadata_tags(card, normalize_func):
    text = f" {normalize_func(' '.join(str(value or '') for value in _metadata_values_for_tags(card)))} "
    rules = {
        "AR": [" art rare ", " illustration rare ", " rare illustration "],
        "FA": [" full art ", " ultra rare ", " rare ultra "],
        "ALT": [" alternative art ", " alt art ", " special illustration ", " illustration speciale "],
        "SAR": [" special art rare ", " special illustration ", " illustration speciale "],
        "RAINBOW": [" rainbow rare ", " rainbow ", " hyper rare "],
        "HYPER_RARE": [" hyper rare "],
        "SECRET_RARE": [" secret rare ", " secrete ", " secrete rare "],
        "TG": [" trainer gallery ", " galerie des dresseurs "],
        "GG": [" galarian gallery ", " galerie de galar "],
        "PROMO": [" promo ", " promotional "],
        "GOLD": [" gold ", " gold rare ", " or "],
        "EX": [" ex ", "-ex"],
        "GX": [" gx ", "-gx"],
        "V": [" pokemon v ", " v "],
        "VMAX": [" vmax ", " v max "],
        "VSTAR": [" vstar ", " v star "],
    }
    tags = []
    for tag, needles in rules.items():
        if any(needle in text for needle in needles):
            tags.append(tag)
    number = str(card.get("localId") or card.get("number") or "").strip().upper().replace(" ", "")
    if number.startswith("TG"):
        tags.append("TG")
    if number.startswith("GG"):
        tags.append("GG")
    if number.startswith(("SWSH", "SM", "SVP", "MEP")):
        tags.append("PROMO")
    result = []
    seen = set()
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _merge_card_metadata(existing_card, incoming_card):
    merged = dict(existing_card or {})
    changed = False
    for key, value in (incoming_card or {}).items():
        if value in (None, "", [], {}):
            continue
        if not merged.get(key):
            merged[key] = value
            changed = True
    for key in ("tags", "card_tags", "metadata_tags", "subtypes", "types"):
        existing_values = merged.get(key) or []
        incoming_values = (incoming_card or {}).get(key) or []
        if not isinstance(existing_values, list):
            existing_values = [existing_values]
        if not isinstance(incoming_values, list):
            incoming_values = [incoming_values]
        combined = []
        seen = set()
        for item in [*existing_values, *incoming_values]:
            if item in (None, ""):
                continue
            token = str(item)
            if token not in seen:
                seen.add(token)
                combined.append(item)
        if combined and combined != existing_values:
            merged[key] = combined
            changed = True
    return merged, changed


def _tcgdex_card_detail(card_id):
    card_id = str(card_id or "").strip()
    if not card_id:
        return {}
    try:
        detail = _tcgdex_get_json(f"https://api.tcgdex.net/v2/fr/cards/{card_id}")
        return detail if isinstance(detail, dict) else {}
    except Exception:
        return {}


def _prepare_cache_card(card, set_name, set_id, normalize_func):
    normalized_card = dict(card or {})
    detail = {}
    if not normalized_card.get("rarity") or not normalized_card.get("category"):
        detail = _tcgdex_card_detail(normalized_card.get("id"))
        if detail:
            normalized_card, _ = _merge_card_metadata(normalized_card, detail)
    if normalized_card.get("image"):
        normalized_card["image"] = _normalize_tcgdex_image(normalized_card.get("image"))
    normalized_card.setdefault("set_id", set_id)
    normalized_card.setdefault("set", set_name)
    metadata_tags = _normalized_metadata_tags(normalized_card, normalize_func)
    if metadata_tags:
        normalized_card["metadata_tags"] = sorted(set((normalized_card.get("metadata_tags") or []) + metadata_tags))
    return normalized_card


def _add_card_to_index(cards_index, card, set_name, set_id, normalize_func):
    if not isinstance(card, dict):
        return "invalid"
    if not is_physical_pokemon_tcg_card(card, set_name=set_name, set_id=set_id):
        return "pocket"
    name = str(card.get("name") or "").strip()
    if not name:
        return "invalid"
    name_key = normalize_func(name)
    if not name_key:
        return "invalid"
    cards_index.setdefault(name_key, [])
    card_id = str(card.get("id") or "").strip()
    normalized_card = _prepare_cache_card(card, set_name, set_id, normalize_func)
    for index, existing in enumerate(cards_index[name_key]):
        try:
            existing_card = existing[0]
            existing_set_id = existing[2] if len(existing) > 2 else ""
        except Exception:
            continue
        if card_id and existing_card.get("id") == card_id:
            merged, changed = _merge_card_metadata(existing_card, normalized_card)
            if changed:
                cards_index[name_key][index] = (merged, set_name, set_id)
                return "updated"
            return "existing"
        if not card_id and existing_card.get("localId") == normalized_card.get("localId") and existing_set_id == set_id:
            merged, changed = _merge_card_metadata(existing_card, normalized_card)
            if changed:
                cards_index[name_key][index] = (merged, set_name, set_id)
                return "updated"
            return "existing"
    cards_index[name_key].append((normalized_card, set_name, set_id))
    return "added"


def enrich_estimations_card_cache(cards_index, set_tags, normalize_func):
    """Fetch only requested TCGDex sets and merge them into cards_index.

    This writes cards_cache.json, but never touches app business JSON files.
    """
    if not isinstance(cards_index, dict):
        cards_index = {}
    set_ids = _candidate_set_ids(set_tags)
    fetched = 0
    added = 0
    updated = 0
    existing = 0
    pocket_filtered = 0
    invalid = 0
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
                status = _add_card_to_index(cards_index, card, set_name, set_id, normalize_func)
                if status == "added":
                    added += 1
                elif status == "updated":
                    updated += 1
                elif status == "existing":
                    existing += 1
                elif status == "pocket":
                    pocket_filtered += 1
                else:
                    invalid += 1
        except Exception as exc:
            errors.append(f"{set_id}: {exc}")
    if sources:
        save_cards_cache_to_disk(cards_index)
    persisted = bool(sources)
    return {
        "cards_index": cards_index,
        "requested_sets": set_ids,
        "sources": sources,
        "fetched": fetched,
        "added": added,
        "updated": updated,
        "existing": existing,
        "pocket_filtered": pocket_filtered,
        "invalid": invalid,
        "persisted": persisted,
        "errors": errors,
    }

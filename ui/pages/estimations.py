"""Estimations page renderer for Pokestock."""

from __future__ import annotations

import base64
from datetime import datetime
import html
import json
import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import streamlit as st
from st_keyup import st_keyup


_ESTIMATION_LOG_SIGNATURES = set()
_ESTIMATION_SUGGESTIONS_CACHE = {}
_ESTIMATION_SUGGESTIONS_CACHE_MAX = 80
_ESTIMATION_SEARCH_INDEX = []
_ESTIMATION_SEARCH_INDEX_SOURCE_ID = None
_ESTIMATION_KEYUP_DEBOUNCE_MS = 80
ESTIMATIONS_DEBUG = str(os.environ.get("POKESTOCK_ESTIMATIONS_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on"}
_INVALID_IMAGE_VALUES = {"", "0", "none", "null", "false", "nan"}
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_RARITY_TAG_ALIASES = {
    "ar": ["art rare", "illustration rare", "rare illustration", "illustration", "ar"],
    "fa": ["full art", "ultra rare", "rare ultra", "fullart"],
    "alt": ["alternative", "alt art", "alternative art", "illustration speciale", "special illustration"],
    "sar": ["special art rare", "special illustration", "illustration speciale", "sar"],
    "rainbow": ["rainbow rare", "rainbow", "hyper rare"],
    "promo": ["promo", "promotional"],
    "etb": ["etb", "elite trainer box", "stamped promo", "promo box", "coffret dresseur"],
    "tg": ["trainer gallery", "galerie des dresseurs", "tg"],
    "gg": ["galarian gallery", "galerie de galar", "gg"],
    "ex": ["ex"],
    "gx": ["gx"],
    "v": [" v ", " pokemon v"],
    "vmax": ["vmax", "v max"],
    "vstar": ["vstar", "v star"],
    "gold": ["gold", "or", "gold rare"],
    "secret": ["secret rare", "secrete", "secrète"],
}
_STATIC_SET_TAG_ALIASES = {
    "151": ["151"],
    "mew": ["151"],
    "pre": ["prismatic", "prismatique", "evolutions prismatiques"],
    "svp": ["svp", "sv promo", "svp black star promos"],
    "sm": ["sm", "sun moon", "soleil lune"],
    "swsh": ["swsh", "sword shield", "epee bouclier"],
    "mep": ["mep"],
    "xy": ["xy"],
    "ssp": ["surging sparks", "etincelles deferlantes"],
    "twm": ["twilight masquerade", "mascarade crepusculaire"],
    "cri": ["crimson", "invasion carmin"],
    "obf": ["obsidian flames", "flammes obsidiennes"],
}


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=1):
    try:
        return max(int(value or default), 1)
    except (TypeError, ValueError):
        return default


def _card_weight(card):
    return _safe_float(card.get("cote")) * _safe_int(card.get("quantity"))


def _estimate_score(totals):
    total_cote = _safe_float(totals.get("total_cote"))
    seller_price = _safe_float(totals.get("seller_price"))
    margin = _safe_float(totals.get("theoretical_margin"))
    if total_cote <= 0 or seller_price <= 0:
        return -999999
    real_pct = seller_price / total_cote * 100
    return (100 - real_pct) * 100 + margin


def _opportunity_label(totals):
    total_cote = _safe_float(totals.get("total_cote"))
    seller_price = _safe_float(totals.get("seller_price"))
    if total_cote <= 0 or seller_price <= 0:
        return "À vérifier", "check"
    real_pct = seller_price / total_cote * 100
    if real_pct < 60:
        return "Très intéressant", "great"
    if real_pct < 70:
        return "Intéressant", "good"
    if real_pct < 80:
        return "Correct", "ok"
    return "Trop cher", "bad"


def _tone_for_status(label, status=""):
    status = str(status or "").lower()
    if "acheté" in status:
        return "done"
    return {
        "Très intéressant": "great",
        "Intéressant": "good",
        "Correct": "ok",
        "Trop cher": "bad",
        "À vérifier": "check",
    }.get(label, "check")


def _best_card(estimate):
    cards = estimate.get("cards", []) or []
    if not cards:
        return {}
    return max(cards, key=_card_weight)


def _card_title(card):
    if not card:
        return "Aucune carte"
    number = str(card.get("number") or "").strip()
    suffix = f" #{number}" if number else ""
    return f"{card.get('name', 'Carte')}{suffix}"


def _all_cards_value(estimate):
    return sum(_card_weight(card) for card in estimate.get("cards", []) or [])


def _estimated_paid_for_card(card, estimate):
    seller_price = _safe_float(estimate.get("seller_price"))
    total_value = _all_cards_value(estimate)
    if seller_price <= 0 or total_value <= 0:
        return 0.0, 0.0
    qty = _safe_int(card.get("quantity"))
    line_paid = seller_price * (_card_weight(card) / total_value)
    return line_paid, line_paid / qty if qty else line_paid


def _log_once(namespace, signature, message):
    if not ESTIMATIONS_DEBUG:
        return
    key = f"{namespace}|{signature}"
    if key in _ESTIMATION_LOG_SIGNATURES:
        return
    _ESTIMATION_LOG_SIGNATURES.add(key)
    print(message, flush=True)


def _event_log_once(namespace, signature, message):
    key = f"event|{namespace}|{signature}"
    if key in _ESTIMATION_LOG_SIGNATURES:
        return
    _ESTIMATION_LOG_SIGNATURES.add(key)
    print(message, flush=True)


def _st_keyup_component_state_key(key, *, debounce, placeholder, disabled=False, label_visibility="visible", input_type="default"):
    parts = [key, disabled, label_visibility, debounce, input_type, placeholder]
    return "st_keyup_" + "__".join(str(part) for part in parts if part is not None)


def _clean_image_value(value):
    text = str(value or "").strip()
    if text.lower() in _INVALID_IMAGE_VALUES:
        return ""
    return text


def _normalize_image_source(value):
    text = _clean_image_value(value)
    if not text:
        return ""
    lower = text.lower()
    if lower.startswith(("http://", "https://")):
        parsed = urlsplit(text)
        if not parsed.scheme or not parsed.netloc:
            return ""
        if "tcgdex.net" in lower and not lower.endswith(_IMAGE_EXTENSIONS):
            return f"{text.rstrip('/')}/high.webp"
        return text
    if lower.startswith("data:image/"):
        return text
    full_path = text if os.path.isabs(text) else os.path.join(os.getcwd(), text)
    if os.path.exists(full_path):
        return full_path
    return ""


def _is_local_image_source(value):
    text = _clean_image_value(value)
    if not text:
        return False
    return not text.lower().startswith(("http://", "https://", "data:image/"))


def _image_file_to_data_uri(path):
    path = _normalize_image_source(path)
    if not path or not os.path.exists(path):
        return ""
    ext = os.path.splitext(path)[1].lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext)
    if not mime:
        return ""
    try:
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except OSError:
        return ""


def _image_source_for_html(value):
    resolved = _normalize_image_source(value)
    if resolved and _is_local_image_source(resolved):
        return _image_file_to_data_uri(resolved)
    return resolved


def _estimation_card_specials(card):
    values = []
    raw_special = card.get("special", "")
    if isinstance(raw_special, list):
        values.extend(str(item or "").strip() for item in raw_special)
    else:
        values.extend(str(item or "").strip() for item in str(raw_special or "").split(","))
    for key in ("special_tag", "rarity", "category"):
        value = str(card.get(key) or "").strip()
        if value:
            values.append(value)
    return [value for value in values if value]


def _card_is_japanese(card):
    lang = str(card.get("lang") or card.get("language") or "").strip().lower()
    if lang in {"ja", "jp", "jpn", "japanese", "japonais", "japonaise"}:
        return True
    text = " ".join(_estimation_card_specials(card)).lower()
    return any(token in text for token in ("japonaise", "japonais", "japanese", " japan"))


def _estimation_card_badges(card, normalize_name_func):
    badge_defs = [
        ("Japonaise", ["japonaise", "japonais", "japanese", "ja", "jp"]),
        ("Promo", ["promo", "promotional"]),
        ("Stamp", ["stamp", "stamped"]),
        ("Reverse", ["reverse"]),
        ("1re édition", ["1ere ed", "1ere edition", "1re edition", "1ère éd", "1ère édition"]),
        ("Holo", ["holo", "holographique"]),
        ("Master Ball", ["master ball"]),
        ("Poké Ball", ["poke ball", "pokeball", "poké ball"]),
        ("Scellé", ["scelle", "scellé", "sealed"]),
        ("FA", ["full art", "fa"]),
        ("AR", ["art rare", "illustration rare", "rare illustration", "ar"]),
        ("Alt", ["alternative", "alt art", "alt"]),
        ("SAR", ["special art rare", "sar"]),
        ("TG", ["trainer gallery", "galerie des dresseurs", "tg"]),
        ("GG", ["galarian gallery", "galerie de galar", "gg"]),
    ]
    explicit_parts = _estimation_card_specials(card)
    if card.get("is_reverse"):
        explicit_parts.append("reverse")
    if card.get("is_ed1"):
        explicit_parts.append("1ere edition")
    if card.get("promo"):
        explicit_parts.append("promo")
    text = f" {' '.join(normalize_name_func(part) for part in explicit_parts)} "
    badges = []
    for label, aliases in badge_defs:
        matched = False
        for alias in aliases:
            alias_norm = normalize_name_func(alias)
            if not alias_norm:
                continue
            if len(alias_norm) <= 3 and alias_norm.isalnum():
                matched = f" {alias_norm} " in text
            else:
                matched = alias_norm in text
            if matched:
                break
        if matched:
            badges.append(label)
    seen = set()
    unique = []
    for badge in badges:
        if badge not in seen:
            seen.add(badge)
            unique.append(badge)
    if unique:
        _log_once(
            "estimation_badge",
            f'{card.get("uid","")}|{",".join(unique)}',
            f'[Estimations Badge] card="{card.get("name", "Carte")}" badges={unique}',
        )
    return unique[:8]


def _manual_estimation_image_dir():
    path = os.path.join("images", "manual_estimations")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_image_filename(card, uploaded_name):
    base = "_".join(
        str(part or "")
        for part in [card.get("uid"), card.get("name"), card.get("number"), uploaded_name]
        if part
    )
    base = re.sub(r"[^a-zA-Z0-9_.-]+", "_", base).strip("._")
    return base or f"estimation_card_{int(time.time())}.webp"


def is_pokemon_pocket_card(card):
    card = card or {}
    set_name = str(card.get("set") or card.get("set_name") or "").strip().lower()
    set_id = str(card.get("set_id") or "").strip().lower()
    card_id = str(card.get("id") or card.get("card_id") or "").strip().lower()
    image_blob = " ".join(
        str(card.get(key) or "")
        for key in ("image", "image_url", "image_url_en", "image_url_ja", "imageUrl")
    ).lower()
    metadata_blob = " ".join(
        str(card.get(key) or "")
        for key in ("game", "product", "source", "series", "category", "tcg", "tags")
    ).lower()
    explicit_blob = f" {set_name} {set_id} {card_id} {image_blob} {metadata_blob} "
    pocket_set_names = {
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
    pocket_id_match = bool(re.match(r"^(a|pa)\d+[a-z]?[-_]", card_id))
    return (
        "/tcgp/" in explicit_blob
        or "tcg pocket" in explicit_blob
        or "pokemon trading card game pocket" in explicit_blob
        or "pokémon trading card game pocket" in explicit_blob
        or "ptcgp" in explicit_blob
        or (pocket_id_match and set_name in pocket_set_names)
    )


def _cardmarket_min_condition(condition):
    condition_key = str(condition or "").strip().lower().replace(" ", "")
    # Confirmed from the user's Cardmarket URL example: NM -> minCondition=2.
    # Other Pokestock condition labels are left unmapped until confirmed.
    if condition_key in {"nm", "nearmint"}:
        return "2"
    return ""


def _append_cardmarket_filters(url, condition, language="2"):
    url = str(url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if language:
        query.setdefault("language", str(language))
    min_condition = _cardmarket_min_condition(condition)
    if min_condition:
        query.setdefault("minCondition", min_condition)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _exact_cardmarket_url(card):
    for key in ("cardmarket_url", "cardmarket_link", "market_url", "cardmarket_product_url", "product_url"):
        value = str((card or {}).get(key) or "").strip()
        if value.startswith(("http://", "https://")) and "cardmarket.com" in value:
            return value
    return ""


def _cardmarket_search_query(card):
    name = str((card or {}).get("name") or "").strip()
    number = str((card or {}).get("number") or "").strip()
    return " ".join(x for x in [name, number] if x).strip()


def _estimation_cardmarket_url(card, cardmarket_search_url_func):
    condition = str((card or {}).get("condition") or "NM").strip()
    is_japanese = _card_is_japanese(card)
    exact_url = _exact_cardmarket_url(card)
    if exact_url:
        final_url = _append_cardmarket_filters(exact_url, condition, language=None if is_japanese else "2")
        _log_once(
            "cardmarket_link",
            f"exact|{card.get('uid','')}|{final_url}",
            f'[Cardmarket Link] card="{card.get("name", "")}" lang="{"ja" if is_japanese else "fr"}" type={"japanese_exact" if is_japanese else "exact"} '
            f'name="{card.get("name", "")}" number="{card.get("number", "")}" '
            f'condition="{condition}" url="{final_url}"',
        )
        return final_url

    number = str((card or {}).get("number") or "").strip()
    set_hint = str((card or {}).get("set_id") or (card or {}).get("set") or "").strip()
    special_hint = ", ".join(_estimation_card_specials(card))
    if is_japanese:
        jp_context = " ".join(x for x in ["JP", set_hint, special_hint] if x).strip()
        query_name = " ".join(x for x in [card.get("name", ""), jp_context] if x).strip()
        search_url = cardmarket_search_url_func(query_name, number, "", "")
        final_url = _append_cardmarket_filters(search_url, condition, language=None)
        link_type = "japanese_search" if jp_context else "generic_fallback"
        reason = "" if jp_context else ' reason="insufficient_japanese_metadata"'
        _log_once(
            "cardmarket_link",
            f"jp_search|{card.get('uid','')}|{final_url}",
            f'[Cardmarket Link] card="{card.get("name", "")}" lang="ja" type={link_type} '
            f'set="{set_hint}" number="{number}" url="{final_url}"{reason}',
        )
        return final_url

    query = _cardmarket_search_query(card)
    search_url = cardmarket_search_url_func(card.get("name", ""), number, "", "")
    final_url = _append_cardmarket_filters(search_url, condition)
    _log_once(
        "cardmarket_link",
        f"search|{card.get('uid','')}|{final_url}",
        '[Cardmarket Link] type=search '
        f'query="{query}" extension_excluded=yes condition="{condition}" url="{final_url}"',
    )
    return final_url


def _selected_card_details(enriched):
    image_info = _resolve_estimation_card_image(enriched)
    details = {
        "name": enriched.get("name", ""),
        "number": enriched.get("number", ""),
        "set": enriched.get("set", ""),
        "set_id": enriched.get("set_id", ""),
        "set_tags": enriched.get("set_tags", []),
        "rarity": enriched.get("rarity", ""),
        "id": enriched.get("id", ""),
        "card_id": enriched.get("card_id") or enriched.get("id", ""),
        "image_url": image_info.get("url", ""),
        "image_url_en": image_info.get("url_en", ""),
    }
    for key in ("image_url_ja", "image_url_jp", "image_url_japanese", "lang", "language", "special_tag"):
        if enriched.get(key):
            details[key] = enriched.get(key)
    for key in ("cardmarket_url", "cardmarket_link", "market_url", "cardmarket_product_url", "product_url"):
        if enriched.get(key):
            details[key] = enriched.get(key)
    return details


def _apply_selected_card_details(estimate, details):
    if not details or not estimate.get("cards"):
        return
    card = estimate["cards"][-1]
    for key in (
        "name",
        "number",
        "set",
        "set_id",
        "set_tags",
        "rarity",
        "id",
        "card_id",
        "image_url",
        "image_url_en",
        "image_url_ja",
        "image_url_jp",
        "image_url_japanese",
        "lang",
        "language",
        "special_tag",
        "cardmarket_url",
        "cardmarket_link",
        "market_url",
        "cardmarket_product_url",
        "product_url",
    ):
        if details.get(key):
            card[key] = details[key]


def _estimation_image_html(url, url_en="", *, style="", placeholder_class="est-card-placeholder compact", fallbacks=None, proxy_img_func=None):
    raw_sources = [url, url_en, *(fallbacks or [])]
    sources = []
    proxy = proxy_img_func or (lambda value: value)
    for source in raw_sources:
        resolved = _image_source_for_html(source)
        if not resolved:
            continue
        if resolved.startswith(("http://", "https://")):
            resolved = proxy(resolved)
        if resolved and resolved not in sources:
            sources.append(resolved)
    placeholder_class = html.escape(str(placeholder_class or "est-card-placeholder compact"), quote=True)
    if not sources:
        return f'<div class="{placeholder_class}">Image indisponible</div>'
    src = html.escape(sources[0], quote=True)
    fallback_chain = [html.escape(source, quote=True) for source in sources[1:]]
    js_array = "[" + ",".join("'" + source.replace("'", "\\'") + "'" for source in fallback_chain) + "]"
    onerror = (
        "this.dataset.fallbackIndex=this.dataset.fallbackIndex||0;"
        f"const f={js_array};"
        "const i=parseInt(this.dataset.fallbackIndex,10);"
        "if(i<f.length){this.dataset.fallbackIndex=i+1;this.src=f[i];return;}"
        "this.style.display='none';"
        "const p=this.nextElementSibling;if(p){p.style.display='flex';}"
    )
    return (
        '<div class="est-img-safe-wrap">'
        f'<img src="{src}" onerror="{html.escape(onerror, quote=True)}" style="width:100%;{html.escape(style, quote=True)}">'
        f'<div class="{placeholder_class}" style="display:none;">Image indisponible</div>'
        "</div>"
    )


def _split_alpha_numeric_token(token):
    token = str(token or "").strip().lower()
    if not token:
        return "", ""
    letters = "".join(ch for ch in token if ch.isalpha())
    digits = "".join(ch for ch in token if ch.isdigit())
    if letters and digits and token == f"{letters}{digits}":
        return letters, digits
    return "", ""


def _known_set_tags(indexed_cards=None):
    tags = set(_STATIC_SET_TAG_ALIASES)
    for item in indexed_cards or []:
        tags.update(item.get("set_tags") or [])
    return tags


def _set_tag_matches_item(item, set_tags):
    if not set_tags:
        return False
    item_tags = set(item.get("set_tags") or [])
    return any(tag in item_tags for tag in set_tags)


def _card_set_match(enriched, set_tags):
    if not set_tags:
        return False
    card_tags = set((enriched or {}).get("set_tags") or [])
    return any(tag in card_tags for tag in set_tags)


def _number_matches(card_number, requested_number):
    requested = str(requested_number or "").strip().upper().replace(" ", "")
    if not requested:
        return True
    card_value = str(card_number or "").strip().upper().replace(" ", "")
    if not card_value:
        return False
    card_digits = "".join(ch for ch in card_value if ch.isdigit())
    req_digits = "".join(ch for ch in requested if ch.isdigit())
    return (
        card_value == requested
        or card_value.startswith(requested)
        or (req_digits and card_digits == req_digits)
        or (req_digits and card_digits.zfill(3) == req_digits.zfill(3))
    )


def _query_parts(query, normalize_name_func, known_set_tags=None):
    raw = str(query or "").strip()
    normalized = normalize_name_func(raw)
    tokens = [token for token in normalized.replace("/", " ").split() if token]
    known_set_tags = set(known_set_tags or [])
    number = ""
    keywords = []
    requested_types = []
    requested_set_tags = []
    searchable_tokens = []
    for token in tokens:
        tag_part, number_part = _split_alpha_numeric_token(token)
        if tag_part and tag_part in known_set_tags:
            requested_set_tags.append(tag_part)
            if number_part:
                number = number_part
            continue
        if token.isdigit():
            if token in known_set_tags and searchable_tokens:
                requested_set_tags.append(token)
            elif not number:
                number = token
            else:
                searchable_tokens.append(token)
            continue
        if token in _RARITY_TAG_ALIASES:
            keywords.extend(_RARITY_TAG_ALIASES[token])
            requested_types.append(token)
            continue
        if token in known_set_tags and searchable_tokens:
            requested_set_tags.append(token)
            continue
        searchable_tokens.append(token)
    base_query = " ".join(searchable_tokens).strip() or raw
    broad_query = searchable_tokens[0] if searchable_tokens else base_query
    return raw, base_query, broad_query, number, keywords, searchable_tokens, requested_types, requested_set_tags


def _contains_type(haystack, requested_type):
    padded = f" {haystack} "
    type_hits = {
        "fa": ["full art", "fullart", "ultra rare", "rare ultra", "secret rare", "hyper rare"],
        "ar": [" art rare ", " illustration rare ", " rare illustration ", " ar "],
        "alt": ["alternative", "alt art", "alternative art", "special illustration", "illustration speciale"],
        "sar": ["special art rare", "special illustration", "illustration speciale"],
        "rainbow": ["rainbow rare", "rainbow", "hyper rare"],
        "promo": [" promo ", " promotional "],
        "etb": [" etb ", "elite trainer box", "stamped promo", "promo box", "coffret dresseur"],
        "tg": [" tg ", "trainer gallery", "galerie des dresseurs"],
        "gg": [" gg ", "galarian gallery", "galerie de galar"],
        "swsh": [" swsh ", "sword shield", "sword & shield", "epee bouclier"],
        "sm": [" sm ", "sun moon", "sun & moon", "soleil lune"],
        "svp": [" svp ", "scarlet violet", "ecarlate violet"],
        "mep": [" mep "],
        "ex": [" ex ", "-ex", " ex-"],
        "gx": [" gx ", "-gx", " gx-"],
        "v": [" v ", " pokemon v "],
        "vmax": ["vmax", "v max"],
        "vstar": ["vstar", "v star"],
        "gold": [" gold ", " gold rare ", " or "],
        "secret": [" secret rare ", " secrete ", " secrète "],
    }
    return any(needle in padded for needle in type_hits.get(requested_type, []))


def _special_card_strength(enriched, normalize_name_func):
    text = normalize_name_func(
        " ".join(
            str(enriched.get(key, ""))
            for key in ("name", "number", "rarity", "category", "special", "special_tag")
        )
    )
    strength = 0
    weighted_terms = [
        (80, ["special art rare", "special illustration", "alternative art", "alt art", "rainbow rare", "hyper rare"]),
        (65, ["secret rare", "illustration rare", "rare illustration", "art rare", "full art", "ultra rare"]),
        (55, ["trainer gallery", "galarian gallery", "galerie des dresseurs", "galerie de galar"]),
        (45, ["promo", "gold", " or ", "shiny", "brillant", "lumineux"]),
        (35, [" ex ", "-ex", " gx ", "-gx", " vmax", "vstar", " pokemon v ", " holo", "reverse"]),
    ]
    padded = f" {text} "
    for weight, terms in weighted_terms:
        if any(term in padded for term in terms):
            strength = max(strength, weight)
    number = _normalized_card_number(enriched)
    if number.startswith(("TG", "GG", "SV", "SWSH", "SM", "SVP", "MEP", "XY")):
        strength = max(strength, 48)
    if _numeric_card_number(number) >= 150:
        strength = max(strength, 25)
    return strength


def _numeric_card_number(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return 0
    try:
        return int(digits[:4])
    except ValueError:
        return 0


def _card_prefix_text(enriched, normalize_name_func):
    return normalize_name_func(
        " ".join(
            str(enriched.get(key, ""))
            for key in ("name", "set", "number", "rarity", "category", "id")
        )
    )


def _normalized_card_number(enriched):
    return str((enriched or {}).get("number") or "").strip().upper().replace(" ", "")


def _requested_prefix_filters(requested_types):
    labels = {
        "ar": "AR",
        "fa": "FA",
        "alt": "ALT",
        "sar": "SAR",
        "rainbow": "RAINBOW",
        "ex": "EX",
        "gx": "GX",
        "v": "V",
        "vmax": "VMAX",
        "vstar": "VSTAR",
        "gold": "GOLD",
        "secret": "SECRET",
        "tg": "TG",
        "gg": "GG",
        "promo": "PROMO",
        "etb": "ETB",
        "swsh": "SWSH",
        "sm": "SM",
        "svp": "SVP",
        "mep": "MEP",
    }
    return [labels[item] for item in requested_types if item in labels]


def _matches_prefix_filter(enriched, requested_type, normalize_name_func):
    text = _card_prefix_text(enriched, normalize_name_func)
    number = _normalized_card_number(enriched)
    card_id = str((enriched or {}).get("id") or "").upper()
    if requested_type == "tg":
        return number.startswith("TG") or " trainer gallery " in f" {text} " or "galerie des dresseurs" in text
    if requested_type == "gg":
        return number.startswith("GG") or " galarian gallery " in f" {text} " or "galerie de galar" in text
    if requested_type == "promo":
        return "promo" in text or any(number.startswith(prefix) for prefix in ("SWSH", "SM", "SVP", "MEP")) or "PROMO" in card_id
    if requested_type == "etb":
        return any(word in text for word in [" etb ", "elite trainer box", "stamped promo", "promo box", "coffret dresseur"])
    if requested_type == "swsh":
        return number.startswith("SWSH") or " swsh " in f" {text} " or "sword shield" in text or "epee bouclier" in text
    if requested_type == "sm":
        return number.startswith("SM") or " sm " in f" {text} " or "sun moon" in text or "soleil lune" in text
    if requested_type == "svp":
        return number.startswith("SVP") or " svp " in f" {text} " or "scarlet violet" in text or "ecarlate violet" in text
    if requested_type == "mep":
        return number.startswith("MEP") or " mep " in f" {text} " or card_id.startswith("MEP")
    return False


def _prefix_match_labels(enriched, requested_types, normalize_name_func):
    labels = []
    label_map = {
        "ar": "AR",
        "fa": "FA",
        "alt": "ALT",
        "sar": "SAR",
        "rainbow": "RAINBOW",
        "ex": "EX",
        "gx": "GX",
        "v": "V",
        "vmax": "VMAX",
        "vstar": "VSTAR",
        "tg": "TG",
        "gg": "GG",
        "promo": "PROMO",
        "etb": "ETB",
        "swsh": "SWSH",
        "sm": "SM",
        "svp": "SVP",
        "mep": "MEP",
    }
    rarity_haystack = normalize_name_func(
        " ".join(str(enriched.get(key, "")) for key in ("name", "number", "rarity", "category", "special", "special_tag"))
    )
    for requested_type, label in label_map.items():
        if requested_type not in requested_types:
            continue
        if requested_type in {"ar", "fa", "alt", "sar", "rainbow", "ex", "gx", "v", "vmax", "vstar", "gold", "secret"}:
            if _contains_type(rarity_haystack, requested_type):
                labels.append(label)
            continue
        if _matches_prefix_filter(enriched, requested_type, normalize_name_func):
            labels.append(label)
    return labels


def _strict_rarity_requested_types(requested_types):
    return [item for item in requested_types if item in {"ar", "fa", "alt", "sar", "rainbow", "tg", "gg", "promo", "gold", "secret"}]


def _card_strict_rarity_text(enriched, normalize_name_func):
    tags = enriched.get("tags") or enriched.get("card_tags") or enriched.get("set_tags") or []
    if isinstance(tags, (list, tuple, set)):
        tags_text = " ".join(str(tag) for tag in tags)
    else:
        tags_text = str(tags or "")
    return normalize_name_func(
        " ".join(
            str(enriched.get(key, "") or "")
            for key in ("rarity", "special", "special_tag", "category", "variant")
        )
        + " "
        + tags_text
    )


def _card_matches_strict_rarity(enriched, requested_type, normalize_name_func):
    text = _card_strict_rarity_text(enriched, normalize_name_func)
    padded = f" {text} "
    number = _normalized_card_number(enriched)
    if requested_type == "ar":
        return any(term in text for term in ("art rare", "illustration rare", "rare illustration"))
    if requested_type == "fa":
        return any(term in text for term in ("full art", "ultra rare", "rare ultra"))
    if requested_type == "alt":
        return any(term in text for term in ("alternative art", "alt art", "alternative", "special illustration", "illustration speciale"))
    if requested_type == "sar":
        return any(term in text for term in ("special art rare", "special illustration", "illustration speciale"))
    if requested_type == "rainbow":
        return any(term in text for term in ("rainbow rare", "rainbow", "hyper rare"))
    if requested_type == "gold":
        return any(term in text for term in ("gold", "gold rare", " or "))
    if requested_type == "secret":
        return any(term in text for term in ("secret rare", "secrete", "secrète"))
    if requested_type == "tg":
        return number.startswith("TG") or "trainer gallery" in text or "galerie des dresseurs" in text
    if requested_type == "gg":
        return number.startswith("GG") or "galarian gallery" in text or "galerie de galar" in text
    if requested_type == "promo":
        return " promo " in padded or "promotional" in text or any(number.startswith(prefix) for prefix in ("SWSH", "SM", "SVP", "MEP"))
    return False


def _card_matches_all_strict_rarities(enriched, requested_types, normalize_name_func):
    strict_types = _strict_rarity_requested_types(requested_types)
    if not strict_types:
        return False
    return all(_card_matches_strict_rarity(enriched, requested_type, normalize_name_func) for requested_type in strict_types)


def _compact_search_text(value, normalize_name_func):
    return "".join(ch for ch in normalize_name_func(value) if ch.isalnum())


def _tcgdex_series_from_card_id(card_id):
    set_id = str(card_id or "").split("-", 1)[0].lower()
    if set_id.startswith(("xy", "xyp", "xya")):
        return "xy"
    if set_id.startswith(("sm", "smp", "sma")):
        return "sm"
    if set_id.startswith(("swsh", "swshp")):
        return "swsh"
    if set_id.startswith(("sv", "svp", "sva")):
        return "sv"
    if set_id.startswith("me"):
        return "me"
    if set_id.startswith("ex"):
        return "ex"
    if set_id.startswith("dp"):
        return "dp"
    if set_id.startswith("bw"):
        return "bw"
    return ""


def _tcgdex_image_from_id(card_id, number, lang="fr"):
    card_id = str(card_id or "").strip()
    number = str(number or "").strip()
    lang = str(lang or "fr").strip() or "fr"
    if "-" not in card_id or not number:
        return ""
    set_id = card_id.rsplit("-", 1)[0]
    series = _tcgdex_series_from_card_id(card_id)
    if series:
        return f"https://assets.tcgdex.net/{lang}/{series}/{set_id}/{number}/high.webp"
    return f"https://assets.tcgdex.net/{lang}/{set_id}/{number}/high.webp"


def _tcgdex_image_candidates_from_id(card_id, number, lang="fr"):
    card_id = str(card_id or "").strip()
    number = str(number or "").strip()
    lang = str(lang or "fr").strip() or "fr"
    if "-" not in card_id or not number:
        return []
    set_id = card_id.rsplit("-", 1)[0]
    series = _tcgdex_series_from_card_id(card_id)
    candidates = []

    def add(url):
        url = _normalize_image_source(url)
        if url and url not in candidates:
            candidates.append(url)

    if series:
        add(f"https://assets.tcgdex.net/{lang}/{series}/{set_id}/{number}/high.webp")
    add(f"https://assets.tcgdex.net/{lang}/{set_id}/{number}/high.webp")
    return candidates


def _resolve_estimation_card_image(card, *, log=True):
    card = card or {}
    is_japanese = _card_is_japanese(card)
    candidates = [
        ("manual_image_path", card.get("manual_image_path")),
        ("manual_image_url", card.get("manual_image_url")),
        ("local_image", card.get("local_image")),
        ("image_path", card.get("image_path")),
        ("photo_path", card.get("photo_path")),
        ("cached_image_path", card.get("cached_image_path")),
        ("resolved_collection_image_url", card.get("resolved_collection_image_url")),
    ]
    if is_japanese:
        candidates.extend(
            [
                ("image_url_ja", card.get("image_url_ja")),
                ("image_url_jp", card.get("image_url_jp")),
                ("image_url_japanese", card.get("image_url_japanese")),
                ("image_ja", card.get("image_ja")),
                ("image_jp", card.get("image_jp")),
            ]
        )
    candidates.extend(
        [
        ("image_url", card.get("image_url")),
        ("image_url_en", card.get("image_url_en")),
        ("image", card.get("image")),
        ("imageUrl", card.get("imageUrl")),
        ]
    )
    images = card.get("images", {})
    if isinstance(images, dict):
        candidates.extend(
            [
                ("images.large", images.get("large")),
                ("images.small", images.get("small")),
            ]
        )
    resolved_candidates = []
    for source, value in candidates:
        resolved = _normalize_image_source(value)
        if resolved:
            resolved_candidates.append((source, resolved))
    if resolved_candidates:
        source, resolved = resolved_candidates[0]
        fallbacks = [value for _, value in resolved_candidates[1:]]
        if log:
            _log_once(
                "estimation_image",
                f'{card.get("id","")}|{card.get("number","")}|{source}|{resolved}',
                f'[Estimations Image] card="{card.get("name", "Carte")}" '
                f'lang="{"ja" if is_japanese else "fr"}" source={source} valid=yes',
            )
        return {"url": resolved, "url_en": "", "fallbacks": fallbacks, "source": source}

    card_id = card.get("card_id") or card.get("id")
    number = card.get("number") or card.get("localId")
    rebuilt_candidates = []
    for lang in (["ja", "fr", "en"] if is_japanese else ["fr", "en"]):
        for candidate in _tcgdex_image_candidates_from_id(card_id, number, lang=lang):
            if candidate not in rebuilt_candidates:
                rebuilt_candidates.append(candidate)
    if rebuilt_candidates:
        if log:
            _log_once(
                "estimation_image",
                f'{card_id}|{number}|tcgdex_rebuilt',
                f'[Estimations Image] card="{card.get("name", "Carte")}" source=tcgdex_rebuilt valid=yes',
            )
        return {"url": rebuilt_candidates[0], "url_en": "", "fallbacks": rebuilt_candidates[1:], "source": "tcgdex_rebuilt"}

    if log:
        _log_once(
            "estimation_image",
            f'{card.get("name","Carte")}|{card.get("number","")}|placeholder',
            f'[Estimations Image] card="{card.get("name", "Carte")}" source=placeholder reason=no_valid_image',
        )
    return {"url": "", "url_en": "", "fallbacks": [], "source": "placeholder"}


def _raw_card_image_url(card):
    if not isinstance(card, dict):
        return ""
    direct = _normalize_image_source(card.get("image") or card.get("imageUrl") or card.get("image_url") or "")
    if direct:
        return direct
    images = card.get("images", {})
    if isinstance(images, dict):
        return _normalize_image_source(images.get("large") or images.get("small") or "")
    return ""


def _raw_card_number(card):
    if not isinstance(card, dict):
        return ""
    return str(card.get("localId") or card.get("number") or "").strip()


def _alias_matches_haystack(alias, haystack, normalize_name_func):
    alias_norm = normalize_name_func(alias)
    if not alias_norm:
        return False
    if len(alias_norm) <= 3 and alias_norm.isalnum():
        return f" {alias_norm} " in haystack
    return alias_norm in haystack


def _set_tags_for_card(enriched, set_id, normalize_name_func):
    set_id_raw = str(set_id or (enriched or {}).get("set_id") or "").strip()
    set_id_norm = normalize_name_func(set_id_raw)
    set_name_norm = normalize_name_func((enriched or {}).get("set", ""))
    number_norm = str((enriched or {}).get("number") or "").strip().upper().replace(" ", "")
    card_id_norm = normalize_name_func((enriched or {}).get("id", ""))
    tags = set()
    for value in (set_id_norm, set_id_norm.replace(".", ""), set_id_norm.replace("-", ""), card_id_norm.split("-")[0]):
        if value:
            tags.add(value)
    alpha_prefix = "".join(ch for ch in set_id_norm if ch.isalpha())
    if alpha_prefix:
        tags.add(alpha_prefix)
    number_prefix = "".join(ch for ch in number_norm if ch.isalpha()).lower()
    if number_prefix:
        tags.add(number_prefix)
    haystack = f" {set_id_norm} {set_name_norm} {card_id_norm} {number_norm.lower()} "
    for tag, aliases in _STATIC_SET_TAG_ALIASES.items():
        if tag in tags or any(_alias_matches_haystack(alias, haystack, normalize_name_func) for alias in aliases):
            tags.add(tag)
    if "151" in set_name_norm or "ecarlate violet 151" in set_name_norm:
        tags.update({"151", "mew"})
    if "prismatique" in set_name_norm or "prismatic" in set_name_norm:
        tags.add("pre")
    if "mascarade crepusculaire" in set_name_norm or "twilight masquerade" in set_name_norm:
        tags.add("twm")
    if "etincelles deferlantes" in set_name_norm or "surging sparks" in set_name_norm:
        tags.add("ssp")
    if "flammes obsidiennes" in set_name_norm or "obsidian flames" in set_name_norm:
        tags.add("obf")
    if "invasion carmin" in set_name_norm or "crimson" in set_name_norm:
        tags.add("cri")
    return sorted(tag for tag in tags if tag)


def _search_index_source_id(cards_index):
    if not isinstance(cards_index, dict):
        return None
    total = 0
    for cards in cards_index.values():
        if isinstance(cards, (list, tuple)):
            total += len(cards)
    return (id(cards_index), len(cards_index), total)


def _build_search_index(cards_index, normalize_name_func):
    global _ESTIMATION_SEARCH_INDEX, _ESTIMATION_SEARCH_INDEX_SOURCE_ID
    source_id = _search_index_source_id(cards_index)
    if source_id and source_id == _ESTIMATION_SEARCH_INDEX_SOURCE_ID:
        return _ESTIMATION_SEARCH_INDEX
    index = []
    pocket_hidden = 0
    if isinstance(cards_index, dict):
        seen = set()
        for idx_name, cards in cards_index.items():
            if not isinstance(cards, (list, tuple)):
                continue
            for item in cards or []:
                try:
                    card = item[0]
                    set_name = item[1] if len(item) > 1 else ""
                    set_id = item[2] if len(item) > 2 else card.get("set_id", "")
                except Exception:
                    continue
                if not isinstance(card, dict):
                    continue
                pocket_probe = {**card, "set": set_name, "set_id": set_id}
                if is_pokemon_pocket_card(pocket_probe):
                    pocket_hidden += 1
                    continue
                card_id = card.get("id") or "|".join([str(card.get("name", "")), _raw_card_number(card), str(set_name)])
                if card_id in seen:
                    continue
                seen.add(card_id)
                number = _raw_card_number(card)
                image_info = _resolve_estimation_card_image({**card, "number": number}, log=False)
                enriched = {
                    "id": card.get("id", ""),
                    "name": card.get("name", idx_name or ""),
                    "set": set_name,
                    "set_id": set_id,
                    "number": number,
                    "rarity": card.get("rarity", ""),
                    "category": card.get("category", ""),
                    "image_url": image_info.get("url", ""),
                    "image_url_en": image_info.get("url_en", ""),
                    "image_url_ja": card.get("image_url_ja") or card.get("image_url_jp") or card.get("image_url_japanese") or "",
                    "lang": card.get("lang", ""),
                    "language": card.get("language", ""),
                    "special_tag": card.get("special_tag", ""),
                }
                set_tags = _set_tags_for_card(enriched, set_id, normalize_name_func)
                enriched["set_tags"] = set_tags
                for cm_key in ("cardmarket_url", "cardmarket_link", "market_url", "cardmarket_product_url", "product_url"):
                    if card.get(cm_key):
                        enriched[cm_key] = card.get(cm_key)
                search_text = normalize_name_func(
                    " ".join(
                        str(value or "")
                        for value in [
                            enriched.get("name"),
                            enriched.get("number"),
                            enriched.get("set"),
                            enriched.get("rarity"),
                            enriched.get("category"),
                            enriched.get("id"),
                            enriched.get("set_id"),
                            " ".join(set_tags),
                        ]
                    )
                )
                index.append({
                    "match": (card, set_name),
                    "card": enriched,
                    "search_text": search_text,
                    "name_norm": normalize_name_func(enriched.get("name", "")),
                    "number_norm": normalize_name_func(enriched.get("number", "")),
                    "set_tags": set_tags,
                })
    if pocket_hidden:
        _event_log_once(
            "pocket_filter",
            f"{source_id}|{pocket_hidden}",
            f"[Estimations Pocket Filter] hidden={pocket_hidden}",
        )
    _ESTIMATION_SEARCH_INDEX = index
    _ESTIMATION_SEARCH_INDEX_SOURCE_ID = source_id
    return index


def _candidate_matches_index_item(item, terms, requested_types, raw_norm, requested_set_tags):
    if not raw_norm:
        return False
    search_text = item.get("search_text", "")
    name_norm = item.get("name_norm", "")
    number_norm = item.get("number_norm", "")
    if terms:
        return all(term in search_text for term in terms)
    if requested_set_tags:
        return _set_tag_matches_item(item, requested_set_tags)
    if requested_types:
        return any(tag in search_text or item.get("number_norm", "").startswith(tag) for tag in requested_types)
    if len(raw_norm) == 1:
        return name_norm.startswith(raw_norm) or raw_norm in name_norm
    return raw_norm in search_text or raw_norm in number_norm


def _suggestion_score(enriched, keywords, terms, number, requested_types, requested_set_tags, normalize_name_func):
    card_haystack = normalize_name_func(
        " ".join(
            str(enriched.get(key, ""))
            for key in ("name", "number", "rarity", "category", "special", "special_tag", "lang", "language")
        )
    )
    haystack = normalize_name_func(
        " ".join(
            str(enriched.get(key, ""))
            for key in ("name", "set", "number", "rarity", "category", "id")
        )
    )
    score = 0
    if number and str(enriched.get("number", "")).startswith(number):
        score += 45
    for term in terms:
        if term and term in haystack:
            score += 12
    for keyword in keywords:
        keyword_norm = normalize_name_func(keyword)
        if keyword_norm and keyword_norm in card_haystack:
            score += 22
    for requested_type in requested_types:
        if _contains_type(card_haystack, requested_type):
            score += 55
        else:
            score -= 18
    rarity = normalize_name_func(enriched.get("rarity", ""))
    name_norm = normalize_name_func(enriched.get("name", ""))
    set_norm = normalize_name_func(enriched.get("set", ""))
    card_number = _numeric_card_number(enriched.get("number", ""))
    wants_visual_special = any(tag in requested_types for tag in ["fa", "ar", "alt", "sar"])
    requested_prefixes = [tag for tag in requested_types if tag in {"tg", "gg", "promo", "etb", "swsh", "sm", "svp", "mep"}]
    matched_prefixes = _prefix_match_labels(enriched, requested_types, normalize_name_func)
    set_match = _card_set_match(enriched, requested_set_tags)
    if requested_set_tags:
        if set_match:
            score += 180
        else:
            score -= 95
        if number and _number_matches(enriched.get("number", ""), number):
            score += 135
        elif number:
            score -= 55
    for requested_prefix in requested_prefixes:
        if _matches_prefix_filter(enriched, requested_prefix, normalize_name_func):
            score += 120
            if _normalized_card_number(enriched).startswith(requested_prefix.upper()):
                score += 70
        else:
            score -= 65
    if any(word in rarity for word in ["rare", "ultra", "illustration", "secret", "promo"]):
        score += 10
    special_strength = _special_card_strength(enriched, normalize_name_func)
    if not number:
        score += special_strength
    if "rainbow" in requested_types:
        if _contains_type(card_haystack, "rainbow"):
            score += 170
        else:
            score -= 80
    if "ar" in requested_types:
        if any(word in card_haystack for word in ["illustration rare", "rare illustration", "art rare"]):
            score += 95
        elif "illustration" in card_haystack:
            score += 70
        elif card_number >= 150:
            score += 38
        elif card_number >= 100:
            score += 26
    for requested_type in ("ex", "v", "gx"):
        if requested_type in requested_types and _contains_type(card_haystack, requested_type):
            score += 45
        elif requested_type in requested_types:
            score -= 16
    if matched_prefixes and any(prefix in matched_prefixes for prefix in ["TG", "GG"]):
        if any(word in haystack for word in ["gallery", "galerie"]):
            score += 45
        if card_number >= 1:
            score += 10
    if "promo" in requested_types and "promo" not in haystack and not matched_prefixes:
        score -= 34
    if "etb" in requested_types:
        if _matches_prefix_filter(enriched, "etb", normalize_name_func):
            score += 120
        else:
            score -= 55
    if any(word in rarity for word in ["common", "commune", "uncommon", "peu commune"]):
        score -= 55 if requested_types or requested_prefixes else 24 if not number else 4
    if wants_visual_special:
        if card_number >= 150:
            score += 34
        elif card_number >= 100:
            score += 24
        elif card_number >= 70:
            score += 10
        if "fa" in requested_types and any(_contains_type(card_haystack, tag) for tag in ["ex", "gx", "v", "vmax", "vstar"]):
            score += 42
        if "promo" in set_norm and "promo" not in requested_types:
            score -= 16
    if enriched.get("image_url") or enriched.get("image_url_en"):
        score += 14 if requested_prefixes else 8
    else:
        score -= 8
    if terms and all(term in name_norm for term in terms):
        score += 26
    elif terms and terms[0] in name_norm:
        score += 12
    joined_terms = " ".join(terms).strip()
    if joined_terms:
        name_words = name_norm.split()
        if name_norm == joined_terms:
            score += 70
        elif name_words and name_words[0] == joined_terms:
            score += 56
        elif name_norm.startswith(joined_terms):
            score += 22
    return score


def _log_search_results(raw, requested_types, requested_set_tags, parsed_number, terms, result, normalize_name_func, started_at, cache_hit=False):
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    filters = _requested_prefix_filters(requested_types)
    exact_prefix_count = sum(1 for item in result if _prefix_match_labels(item["card"], requested_types, normalize_name_func))
    strict_types = _strict_rarity_requested_types(requested_types)
    strict_count = sum(1 for item in result if item.get("strict_match") or _card_matches_all_strict_rarities(item["card"], requested_types, normalize_name_func))
    fallback_count = max(len(result) - strict_count, 0) if strict_types else 0
    set_match_count = sum(1 for item in result if _card_set_match(item["card"], requested_set_tags))
    top_scores = []
    for item in result[:5]:
        card = item["card"]
        top_scores.append(f"{card.get('name', 'Carte')} {card.get('number', '')}:{item['score']}")
    query_norm = normalize_name_func(raw)
    _log_once(
        "live_search_time",
        f"{query_norm}|{cache_hit}|{elapsed_ms}|{len(result)}",
        f'[Estimations Live Search] query="{raw}" elapsed_ms={elapsed_ms}',
    )
    _log_once(
        "live_search_keyup",
        f"{query_norm}|{cache_hit}",
        f"[Estimations Live Search] keyup=yes debounce_ms={_ESTIMATION_KEYUP_DEBOUNCE_MS}",
    )
    _log_once(
        "live_search_results",
        f"{query_norm}|{cache_hit}|{len(result)}",
        f'[Estimations Live Search] results={len(result)} cache_hit={"yes" if cache_hit else "no"}',
    )
    _log_once(
        "search",
        f"{query_norm}|{cache_hit}|{[(item['card'].get('id'), item['score']) for item in result[:5]]}",
        f'[Estimations Search] query="{raw}" results={len(result)} elapsed_ms={elapsed_ms} '
        f'name="{" ".join(terms)}" set_tags={[tag.upper() for tag in requested_set_tags]} number="{parsed_number}" '
        f'filters={filters} cache_hit={"yes" if cache_hit else "no"} prefix_matches={exact_prefix_count} '
        f"strict_matches={strict_count} fallback_matches={fallback_count} set_matches={set_match_count} "
        f'top="{", ".join(top_scores)}"',
    )
    for idx, item in enumerate(result[:5], start=1):
        card = item["card"]
        prefix_match = bool(_prefix_match_labels(card, requested_types, normalize_name_func))
        set_match = _card_set_match(card, requested_set_tags)
        number_match = _number_matches(card.get("number", ""), parsed_number)
        _log_once(
            "search_result",
            f"{query_norm}|{cache_hit}|{idx}|{card.get('id') or card.get('name')}|{item['score']}",
            "[Estimations Search] "
            f"#{idx} {card.get('name', 'Carte')} {card.get('number', '')} | "
            f"{card.get('set', '')} | score={item['score']} | "
            f"set_match={'yes' if set_match else 'no'} | "
            f"number_match={'yes' if number_match else 'no'} | "
            f"prefix_match={'yes' if prefix_match else 'no'} | "
            f"image={'yes' if card.get('image_url') or card.get('image_url_en') else 'no'}",
        )
    if filters and exact_prefix_count == 0:
        _log_once(
            "search_no_prefix",
            f"{query_norm}|{filters}",
            f'[Estimations Search] query="{raw}" filters={filters} exact_prefix_match=no',
        )
    if not result:
        _log_once(
            "search_empty",
            query_norm,
            f'[Estimations Search] query="{raw}" no reliable local result elapsed_ms={elapsed_ms}',
        )
    if requested_set_tags and set_match_count == 0:
        _log_once(
            "search_no_set_tag",
            f"{query_norm}|{requested_set_tags}",
            f'[Estimations Search] query="{raw}" set_tags={[tag.upper() for tag in requested_set_tags]} exact_set_match=no',
        )


def _manual_add_exact_match(name, number, normalize_name_func):
    cards_index = st.session_state.get("cards_index", {})
    indexed_cards = _build_search_index(cards_index, normalize_name_func)
    name_norm = normalize_name_func(name)
    number_text = str(number or "").strip()
    if not name_norm:
        return "none", []
    candidates = []
    for item in indexed_cards:
        card = item["card"]
        card_number = str(card.get("number", "")).strip()
        number_matches = True
        if number_text:
            number_matches = _number_matches(card_number, number_text)
        if item.get("name_norm") == name_norm and number_matches:
            candidates.append(item)
    if len(candidates) == 1:
        return "exact", candidates
    if len(candidates) > 1:
        return "ambiguous", candidates
    return "none", []


def _card_suggestions(query, current_number, search_in_cache_func, ecd_func, normalize_name_func, limit=8):
    started_at = time.perf_counter()
    cards_index = st.session_state.get("cards_index", {})
    indexed_cards = _build_search_index(cards_index, normalize_name_func)
    known_tags = _known_set_tags(indexed_cards)
    raw, base_query, broad_query, parsed_number, keywords, terms, requested_types, requested_set_tags = _query_parts(query, normalize_name_func, known_tags)
    number = str(current_number or parsed_number or "").strip()
    raw_norm = normalize_name_func(raw)
    if not raw.strip():
        return []

    cache_key = f"{normalize_name_func(raw)}|{number}|{','.join(requested_set_tags)}"
    if cache_key in _ESTIMATION_SUGGESTIONS_CACHE:
        result = _ESTIMATION_SUGGESTIONS_CACHE[cache_key]
        _log_search_results(raw, requested_types, requested_set_tags, number, terms, result, normalize_name_func, started_at, cache_hit=True)
        return result

    suggestions = []
    strict_types = _strict_rarity_requested_types(requested_types)
    for item in indexed_cards:
        if not _candidate_matches_index_item(item, terms, requested_types, raw_norm, requested_set_tags):
            continue
        enriched = item["card"]
        if number:
            item_number = str(enriched.get("number", ""))
            if not _number_matches(item_number, number):
                continue
        score = _suggestion_score(enriched, keywords, terms, number, requested_types, requested_set_tags, normalize_name_func)
        strict_match = _card_matches_all_strict_rarities(enriched, requested_types, normalize_name_func) if strict_types else False
        if strict_match:
            score += 260
        elif strict_types:
            score -= 120
        suggestions.append({"match": item["match"], "card": enriched, "score": score, "strict_match": strict_match})

    if not suggestions and indexed_cards:
        for item in indexed_cards:
            search_text = item.get("search_text", "")
            name_norm = item.get("name_norm", "")
            if terms:
                fallback_match = all(term in search_text for term in terms)
            else:
                fallback_match = raw_norm in search_text or name_norm.startswith(raw_norm[:1])
            if fallback_match:
                enriched = item["card"]
                score = _suggestion_score(enriched, keywords, terms, number, requested_types, requested_set_tags, normalize_name_func) - 40
                strict_match = _card_matches_all_strict_rarities(enriched, requested_types, normalize_name_func) if strict_types else False
                if strict_match:
                    score += 260
                elif strict_types:
                    score -= 120
                suggestions.append({"match": item["match"], "card": enriched, "score": score, "strict_match": strict_match})

    suggestions.sort(key=lambda item: item["score"], reverse=True)
    if strict_types and any(item.get("strict_match") for item in suggestions):
        exact = [item for item in suggestions if item.get("strict_match")]
        fallback = [item for item in suggestions if not item.get("strict_match")]
        result = (exact[:limit] + fallback[: max(0, limit - len(exact[:limit]))])[:limit]
    else:
        result = suggestions[:limit]
    if len(_ESTIMATION_SUGGESTIONS_CACHE) >= _ESTIMATION_SUGGESTIONS_CACHE_MAX:
        _ESTIMATION_SUGGESTIONS_CACHE.pop(next(iter(_ESTIMATION_SUGGESTIONS_CACHE)))
    _ESTIMATION_SUGGESTIONS_CACHE[cache_key] = result
    _log_search_results(raw, requested_types, requested_set_tags, number, terms, result, normalize_name_func, started_at, cache_hit=False)
    return result


def _suggestions_missing_set_match(query, suggestions, normalize_name_func):
    cards_index = st.session_state.get("cards_index", {})
    indexed_cards = _build_search_index(cards_index, normalize_name_func)
    known_tags = _known_set_tags(indexed_cards)
    _, _, _, _, _, _, _, requested_set_tags = _query_parts(query, normalize_name_func, known_tags)
    if not requested_set_tags or not suggestions:
        return False
    return not any(_card_set_match(item.get("card", {}), requested_set_tags) for item in suggestions)


def _suggestions_missing_type_match(query, suggestions, requested_type, normalize_name_func):
    cards_index = st.session_state.get("cards_index", {})
    indexed_cards = _build_search_index(cards_index, normalize_name_func)
    known_tags = _known_set_tags(indexed_cards)
    _, _, _, _, _, _, requested_types, _ = _query_parts(query, normalize_name_func, known_tags)
    if requested_type not in requested_types or not suggestions:
        return False
    if requested_type in _strict_rarity_requested_types([requested_type]):
        return not any(_card_matches_strict_rarity(item.get("card", {}), requested_type, normalize_name_func) for item in suggestions)
    return not any(_prefix_match_labels(item.get("card", {}), [requested_type], normalize_name_func) for item in suggestions)


def _strict_suggestion_sections(query, suggestions, normalize_name_func):
    cards_index = st.session_state.get("cards_index", {})
    indexed_cards = _build_search_index(cards_index, normalize_name_func)
    known_tags = _known_set_tags(indexed_cards)
    _, _, _, _, _, _, requested_types, _ = _query_parts(query, normalize_name_func, known_tags)
    strict_types = _strict_rarity_requested_types(requested_types)
    if not strict_types:
        return [], list(suggestions or []), []
    exact = [item for item in suggestions or [] if item.get("strict_match") or _card_matches_all_strict_rarities(item.get("card", {}), requested_types, normalize_name_func)]
    close = [item for item in suggestions or [] if item not in exact]
    return exact, close, strict_types


def _search_context(query, normalize_name_func):
    cards_index = st.session_state.get("cards_index", {})
    indexed_cards = _build_search_index(cards_index, normalize_name_func)
    known_tags = _known_set_tags(indexed_cards)
    raw, _, _, number, _, terms, requested_types, requested_set_tags = _query_parts(query, normalize_name_func, known_tags)
    return {
        "raw": raw,
        "number": number,
        "terms": terms,
        "requested_types": requested_types,
        "requested_set_tags": requested_set_tags,
    }


def _has_exact_search_match(query, suggestions, normalize_name_func):
    context = _search_context(query, normalize_name_func)
    terms = context["terms"]
    set_tags = context["requested_set_tags"]
    number = context["number"]
    if not set_tags and not number:
        return True
    for item in suggestions or []:
        card = item.get("card", {})
        name_norm = normalize_name_func(card.get("name", ""))
        name_match = all(term in name_norm for term in terms) if terms else True
        set_match = _card_set_match(card, set_tags) if set_tags else True
        number_match = _number_matches(card.get("number", ""), number) if number else True
        if name_match and set_match and number_match:
            return True
    return False


def _reset_estimation_search_memory_cache():
    global _ESTIMATION_SEARCH_INDEX, _ESTIMATION_SEARCH_INDEX_SOURCE_ID
    _ESTIMATION_SUGGESTIONS_CACHE.clear()
    _ESTIMATION_SEARCH_INDEX = []
    _ESTIMATION_SEARCH_INDEX_SOURCE_ID = None


def _image_html(card, proxy_img_func, class_name="est-box-img"):
    image_info = _resolve_estimation_card_image(card or {}, log=False)
    image_url = image_info.get("url", "")
    image_en = image_info.get("url_en", "")
    return _estimation_image_html(
        image_url,
        image_en,
        style=f"height:100%;object-fit:contain;",
        placeholder_class="est-placeholder",
        fallbacks=image_info.get("fallbacks", []),
        proxy_img_func=proxy_img_func,
    ).replace("<img ", f'<img class="{html.escape(class_name, quote=True)}" ', 1)


def _kpi(label, value, tone="neutral", accent=None):
    accent_class = accent or tone
    return (
        f'<div class="est-kpi {accent_class}">'
        f"<span>{html.escape(str(label))}</span>"
        f"<strong>{html.escape(str(value))}</strong>"
        "</div>"
    )


def _card_unit_value(card):
    for key in ("cote", "current_value", "estimated_value", "value", "suggested_price"):
        value = _safe_float((card or {}).get(key))
        if value > 0:
            return value
    return 0.0


def _estimate_cover_card(estimate):
    candidates = [card for card in estimate.get("cards", []) or [] if _card_unit_value(card) > 0]
    if not candidates:
        return {}
    return max(candidates, key=_card_unit_value)


def _estimate_box_html(item, fp_func, proxy_img_func, active=False):
    estimate = item["estimate"]
    totals = item["totals"]
    label = item["label"]
    tone = _tone_for_status(label, estimate.get("status"))
    best = _estimate_cover_card(estimate) or _best_card(estimate)
    cover = _estimate_cover_card(estimate)
    title = html.escape(str(estimate.get("name") or "Estimation"))
    listing_url = str(estimate.get("listing_url") or "").strip()
    listing_link = (
        f'<a class="est-listing-link" href="{html.escape(listing_url, quote=True)}" target="_blank">Ouvrir l’annonce</a>'
        if listing_url
        else ""
    )
    source = html.escape(str(estimate.get("source") or "Vinted"))
    status = html.escape(str(estimate.get("status") or "En cours"))
    card_count = sum(_safe_int(card.get("quantity")) for card in estimate.get("cards", []) or [])
    seller_price = _safe_float(totals.get("seller_price"))
    total_cote = _safe_float(totals.get("total_cote"))
    real_pct = _safe_float(totals.get("real_pct"))
    margin = _safe_float(totals.get("theoretical_margin"))
    pct_label = f"{real_pct:.1f}%" if real_pct else "À vérifier"
    active_class = " active" if active else ""
    uid = html.escape(str(estimate.get("uid") or ""), quote=True)
    return f"""
    <div class="est-opportunity-card {tone}{active_class}" data-est-card-uid="{uid}" role="button" tabindex="0">
        <div class="est-card-ribbon"></div>
        <div class="est-card-main">
            <div class="est-img-frame">
                {_image_html(cover, proxy_img_func)}
            </div>
            <div class="est-card-content">
                <div class="est-card-topline">
                    <span class="est-badge {tone}">{html.escape(label)}</span>
                    <span class="est-chip">{source}</span>
                    <span class="est-chip">{status}</span>
                </div>
                <h3><span>{title}</span>{listing_link}</h3>
                <p>{html.escape(_card_title(best))}</p>
                <div class="est-metrics">
                    {_kpi("Prix demandé", fp_func(seller_price) if seller_price > 0 else "À saisir", tone)}
                    {_kpi("Cote", fp_func(total_cote), tone)}
                    {_kpi("% cote", pct_label, tone)}
                    {_kpi("Marge", fp_func(margin) if total_cote else "À vérifier", tone)}
                    {_kpi("Cartes", f"{card_count}", tone)}
                </div>
            </div>
        </div>
    </div>
    """


def _render_tracked_card(card, estimate, fp_func, img_with_fallback_func, cardmarket_search_url_func, normalize_name_func, proxy_img_func=None):
    qty = _safe_int(card.get("quantity"))
    cote = _safe_float(card.get("cote"))
    line_paid, unit_paid = _estimated_paid_for_card(card, estimate)
    line_margin = cote * qty - line_paid if line_paid else 0.0
    number = str(card.get("number") or "").strip()
    badges = _estimation_card_badges(card, normalize_name_func)
    image_info = _resolve_estimation_card_image(card)
    image = _estimation_image_html(
        image_info.get("url", ""),
        image_info.get("url_en", ""),
        style="height:156px;max-height:156px;object-fit:contain;border-radius:10px;",
        fallbacks=image_info.get("fallbacks", []),
        proxy_img_func=proxy_img_func,
    )
    tags = " · ".join(x for x in [f"#{number}" if number else "", f"x{qty}"] if x)
    paid_label = fp_func(unit_paid) if unit_paid else "À vérifier"
    margin_label = fp_func(line_margin) if line_paid else "À vérifier"
    margin_class = "good" if line_paid and line_margin >= 0 else "bad" if line_paid else "neutral"
    cm_url = html.escape(_estimation_cardmarket_url(card, cardmarket_search_url_func), quote=True)
    st.markdown(
        f"""
        <div class="est-tracked-card-shell">
            <div class="est-tracked-image">{image}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return {
        "tags": tags,
        "paid_label": paid_label,
        "margin_label": margin_label,
        "margin_class": margin_class,
        "cm_url": cm_url,
        "image_source": image_info.get("source", ""),
        "has_image": image_info.get("source") != "placeholder" and bool(image_info.get("url") or image_info.get("url_en") or image_info.get("fallbacks")),
        "has_manual_image": bool(_normalize_image_source(card.get("manual_image_path") or card.get("manual_image_url"))),
        "badges": badges,
    }


def _render_suggestion_card(enriched, proxy_img_func=None):
    image_info = _resolve_estimation_card_image(enriched)
    image = _estimation_image_html(
        image_info.get("url", ""),
        image_info.get("url_en", ""),
        style="height:100%;object-fit:contain;",
        placeholder_class="est-suggestion-placeholder",
        fallbacks=image_info.get("fallbacks", []),
        proxy_img_func=proxy_img_func,
    )
    number = str(enriched.get("number") or "").strip()
    set_name = str(enriched.get("set") or "").strip()
    rarity = str(enriched.get("rarity") or "").strip()
    details = " · ".join(x for x in [f"#{number}" if number else "", set_name] if x)
    st.markdown(
        f"""
        <div class="est-suggestion-card">
            <div class="est-suggestion-img">{image}</div>
            <div class="est-suggestion-copy">
                <strong>{html.escape(str(enriched.get('name') or 'Carte'))}</strong>
                <span>{html.escape(details)}</span>
                <em>{html.escape(rarity)}</em>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _estimation_card_filter_text(card, normalize_name_func):
    return normalize_name_func(
        " ".join(
            str(value or "")
            for value in [
                card.get("name"),
                card.get("number"),
                card.get("set"),
                card.get("set_id"),
                card.get("rarity"),
                card.get("special"),
                card.get("special_tag"),
                card.get("lang"),
                card.get("language"),
                " ".join(str(tag) for tag in card.get("set_tags", []) or []),
            ]
        )
    )


def _filtered_estimation_cards(cards, query, normalize_name_func):
    query_norm = normalize_name_func(query)
    display_cards = list(reversed(list(cards or [])))
    if not query_norm:
        return display_cards
    terms = [term for term in query_norm.split() if term]
    return [card for card in display_cards if all(term in _estimation_card_filter_text(card, normalize_name_func) for term in terms)]


def _refresh_estimation_card_image(card, normalize_name_func, cache_enrichment_func=None):
    if not card:
        return False
    status, candidates = _manual_add_exact_match(card.get("name", ""), card.get("number", ""), normalize_name_func)
    chosen = candidates[0]["card"] if status == "exact" and candidates else None
    if chosen:
        details = _selected_card_details(chosen)
        if details.get("image_url") or details.get("image_url_en") or details.get("image_url_ja"):
            _apply_selected_card_details({"cards": [card]}, details)
            print(
                f'[Estimations Image Refresh] card="{card.get("name", "Carte")}" found=yes source=local_cache',
                flush=True,
            )
            return True

    print(f'[Estimations Image Refresh] card="{card.get("name", "Carte")}" found=no', flush=True)
    return False


def _cards_missing_estimation_image(cards):
    missing = []
    for card in cards or []:
        image_info = _resolve_estimation_card_image(card, log=False)
        if image_info.get("source") == "placeholder":
            missing.append(card)
    return missing


def _repair_missing_estimation_images(estimate, normalize_name_func, cache_enrichment_func=None):
    missing = _cards_missing_estimation_image(estimate.get("cards", []) or [])
    repaired = 0
    for card in missing:
        if _refresh_estimation_card_image(card, normalize_name_func, cache_enrichment_func):
            repaired += 1
    unresolved = max(len(missing) - repaired, 0)
    print(
        f'[Estimations Image Repair] estimate="{estimate.get("name", "Estimation")}" '
        f"missing={len(missing)} repaired={repaired} unresolved={unresolved}",
        flush=True,
    )
    return {"missing": len(missing), "repaired": repaired, "unresolved": unresolved}


def _save_estimation_manual_image(card, uploaded_file):
    if not uploaded_file:
        return ""
    folder = _manual_estimation_image_dir()
    filename = _safe_image_filename(card, uploaded_file.name)
    path = os.path.join(folder, filename)
    with open(path, "wb") as target:
        target.write(uploaded_file.getbuffer())
    return path.replace("\\", "/")


def _render_css():
    st.markdown(
        """
        <style>
        .est-page-intro {
            margin:0.1rem 0 1rem 0;
            color:#64748b;
            font-weight:650;
        }
        .est-create-card {
            border:1px solid rgba(99,102,241,0.24);
            background:linear-gradient(135deg,#f5f3ff,#eef2ff 48%,#ecfeff);
            border-radius:16px;
            padding:0.95rem 1rem;
            margin:0.7rem 0 1rem 0;
            box-shadow:0 10px 24px rgba(79,70,229,0.10);
        }
        .est-opportunity-card {
            position:relative;
            overflow:hidden;
            border-radius:18px;
            border:1px solid #e2e8f0;
            background:#fff;
            margin:0.8rem 0 0.45rem 0;
            box-shadow:0 14px 34px rgba(15,23,42,0.08);
            cursor:pointer;
            transition:transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
        }
        .est-opportunity-card:hover {
            transform:translateY(-2px);
            box-shadow:0 20px 42px rgba(15,23,42,0.13);
        }
        .est-opportunity-card.active {
            box-shadow:0 18px 42px rgba(15,23,42,0.13);
        }
        .est-card-ribbon {
            position:absolute;
            inset:0 auto 0 0;
            width:7px;
        }
        .est-card-main {
            display:grid;
            grid-template-columns:minmax(86px, 122px) minmax(0,1fr);
            gap:1rem;
            padding:1rem;
            align-items:center;
            min-width:0;
            max-width:100%;
        }
        .est-opportunity-card.great { background:linear-gradient(135deg,#ecfdf5,#ffffff 54%,#f0fdf4); border-color:#a7f3d0; }
        .est-opportunity-card.good { background:linear-gradient(135deg,#ecfeff,#ffffff 54%,#eff6ff); border-color:#93c5fd; }
        .est-opportunity-card.ok { background:linear-gradient(135deg,#fffbeb,#ffffff 54%,#fff7ed); border-color:#fcd34d; }
        .est-opportunity-card.bad { background:linear-gradient(135deg,#fff1f2,#ffffff 54%,#fef2f2); border-color:#fda4af; }
        .est-opportunity-card.check { background:linear-gradient(135deg,#f5f3ff,#ffffff 54%,#f8fafc); border-color:#c4b5fd; }
        .est-opportunity-card.done { background:linear-gradient(135deg,#eef2ff,#ffffff 54%,#f1f5f9); border-color:#a5b4fc; }
        .est-opportunity-card.great .est-card-ribbon { background:#10b981; }
        .est-opportunity-card.good .est-card-ribbon { background:#06b6d4; }
        .est-opportunity-card.ok .est-card-ribbon { background:#f59e0b; }
        .est-opportunity-card.bad .est-card-ribbon { background:#f43f5e; }
        .est-opportunity-card.check .est-card-ribbon { background:#8b5cf6; }
        .est-opportunity-card.done .est-card-ribbon { background:#6366f1; }
        .est-img-frame {
            width:100%;
            aspect-ratio:0.72;
            border-radius:14px;
            background:rgba(255,255,255,0.7);
            border:1px solid rgba(148,163,184,0.35);
            display:flex;
            align-items:center;
            justify-content:center;
            overflow:hidden;
        }
        .est-img-frame.missing::before,
        .est-placeholder,
        .est-card-placeholder {
            content:"Image indisponible";
            color:#94a3b8;
            font-size:0.78rem;
            font-weight:850;
            text-align:center;
            padding:0.55rem;
        }
        .est-card-placeholder.compact {
            width:100%;
            height:100%;
            min-height:188px;
            border-radius:10px;
            border:1px solid #e2e8f0;
            background:#f8fafc;
            display:flex;
            align-items:center;
            justify-content:center;
            font-size:0.68rem;
        }
        .est-box-img {
            width:100%;
            height:100%;
            object-fit:contain;
            display:block;
        }
        .est-card-content h3 {
            display:flex;
            flex-wrap:wrap;
            gap:0.55rem;
            align-items:baseline;
            margin:0.4rem 0 0.15rem 0;
            color:#0f172a;
            font-size:clamp(1.05rem,2.2vw,1.45rem);
            line-height:1.12;
            overflow-wrap:anywhere;
            min-width:0;
        }
        .est-listing-link {
            display:inline-flex;
            align-items:center;
            border-radius:999px;
            padding:0.22rem 0.55rem;
            background:#dbeafe;
            color:#1d4ed8 !important;
            font-size:0.74rem;
            font-weight:900;
            text-decoration:none !important;
            white-space:normal;
            overflow-wrap:anywhere;
        }
        .est-listing-link:hover {
            background:#bfdbfe;
        }
        .est-card-content p {
            margin:0 0 0.72rem 0;
            color:#475569;
            font-weight:750;
            overflow-wrap:anywhere;
            min-width:0;
        }
        .est-card-topline,
        .est-card-tags {
            display:flex;
            flex-wrap:wrap;
            gap:0.42rem;
            align-items:center;
        }
        .est-badge,
        .est-chip,
        .est-card-tags span {
            display:inline-flex;
            align-items:center;
            border-radius:999px;
            padding:0.22rem 0.55rem;
            font-size:0.74rem;
            font-weight:900;
            line-height:1.2;
        }
        .est-chip,
        .est-card-tags span {
            color:#475569;
            background:rgba(255,255,255,0.72);
            border:1px solid rgba(148,163,184,0.25);
        }
        .est-badge.great { background:#d1fae5; color:#047857; }
        .est-badge.good { background:#cffafe; color:#0e7490; }
        .est-badge.ok { background:#fef3c7; color:#92400e; }
        .est-badge.bad { background:#ffe4e6; color:#be123c; }
        .est-badge.check { background:#ede9fe; color:#6d28d9; }
        .est-badge.done { background:#e0e7ff; color:#4338ca; }
        .est-metrics,
        .est-detail-kpis {
            display:grid;
            grid-template-columns:repeat(5,minmax(0,1fr));
            gap:0.5rem;
        }
        .est-detail-kpis {
            grid-template-columns:repeat(4,minmax(0,1fr));
            margin:0.6rem 0 1rem 0;
        }
        .est-kpi {
            border-radius:13px;
            background:rgba(255,255,255,0.74);
            border:1px solid rgba(148,163,184,0.22);
            padding:0.62rem;
            min-width:0;
        }
        .est-detail-kpis .est-kpi {
            padding:0.86rem;
            box-shadow:0 10px 22px rgba(15,23,42,0.06);
        }
        .est-kpi span {
            display:block;
            color:#64748b;
            font-size:0.72rem;
            font-weight:850;
        }
        .est-detail-kpis .est-kpi span {
            font-size:0.78rem;
        }
        .est-kpi strong {
            display:block;
            color:#0f172a;
            margin-top:0.12rem;
            font-size:0.96rem;
            line-height:1.15;
            overflow-wrap:anywhere;
        }
        .est-detail-kpis .est-kpi strong {
            font-size:clamp(1.08rem,2.2vw,1.38rem);
        }
        .est-kpi.price { background:#fff7ed; border-color:#fdba74; }
        .est-kpi.price strong { color:#c2410c; }
        .est-kpi.value { background:#eff6ff; border-color:#93c5fd; }
        .est-kpi.value strong { color:#1d4ed8; }
        .est-kpi.percent { background:#ecfeff; border-color:#67e8f9; }
        .est-kpi.percent strong { color:#0e7490; }
        .est-kpi.margin-good { background:#ecfdf5; border-color:#86efac; }
        .est-kpi.margin-good strong { color:#15803d; }
        .est-kpi.margin-bad { background:#fff1f2; border-color:#fda4af; }
        .est-kpi.margin-bad strong { color:#be123c; }
        .est-kpi.margin-neutral { background:#f8fafc; border-color:#cbd5e1; }
        .est-kpi.buy { background:#eef2ff; border-color:#a5b4fc; }
        .est-kpi.buy strong { color:#4338ca; }
        .est-kpi.count { background:#f8fafc; border-color:#cbd5e1; }
        .est-kpi.type { background:#f5f3ff; border-color:#c4b5fd; }
        .est-kpi.type strong { color:#6d28d9; }
        .est-detail-shell {
            border:0;
            border-radius:0;
            background:transparent;
            padding:0;
            margin:0.15rem 0 1.05rem 0;
        }
        .est-detail-title {
            display:flex;
            flex-wrap:wrap;
            justify-content:space-between;
            align-items:flex-start;
            gap:0.7rem;
            margin-bottom:0.6rem;
        }
        .est-detail-title h3 {
            margin:0;
            font-size:clamp(1.1rem,2.4vw,1.55rem);
            color:#0f172a;
        }
        .est-tracked-card-shell {
            border:0;
            border-radius:12px;
            background:transparent;
            padding:0;
            box-shadow:none;
            display:flex;
            flex-direction:column;
            gap:0;
        }
        .est-tracked-image {
            height:158px;
            border-radius:10px;
            background:transparent;
            display:flex;
            align-items:center;
            justify-content:center;
            overflow:visible;
            border:0;
            box-shadow:none;
            flex:0 0 auto;
        }
        .est-tracked-image img {
            width:100%;
            height:100%;
            object-fit:contain;
            display:block;
        }
        .est-img-safe-wrap {
            width:100%;
            height:100%;
            display:flex;
            align-items:center;
            justify-content:center;
        }
        [data-testid="stElementContainer"]:has(.est-tracked-bubble-marker) + div [data-testid="stVerticalBlockBorderWrapper"] {
            border:1px solid #e2e8f0 !important;
            border-radius:12px !important;
            background:#ffffff !important;
            box-shadow:0 8px 16px rgba(15,23,42,0.055) !important;
            padding:0 !important;
            margin-top:0.28rem !important;
        }
        [data-testid="stElementContainer"]:has(.est-tracked-bubble-marker) + div [data-testid="stVerticalBlock"] {
            gap:0.22rem !important;
            padding:0.42rem !important;
        }
        .est-tracked-body {
            display:flex;
            flex-direction:column;
            gap:0.3rem;
            min-width:0;
            flex:1 1 auto;
            border:1px solid #e2e8f0;
            border-radius:12px;
            background:#ffffff;
            padding:0.48rem;
            box-shadow:0 8px 16px rgba(15,23,42,0.055);
        }
        .est-tracked-heading h4 {
            margin:0;
            font-size:0.76rem;
            line-height:1.18;
            color:#0f172a;
            overflow-wrap:anywhere;
            word-break:normal;
            max-width:100%;
        }
        .est-tracked-tags {
            color:#64748b;
            font-size:0.63rem;
            line-height:1.15;
            font-weight:800;
            overflow-wrap:anywhere;
            margin-top:0.12rem;
        }
        .est-badge-row {
            display:flex;
            flex-wrap:wrap;
            gap:0.18rem;
            margin-top:0.28rem;
            max-width:100%;
        }
        .est-badge-row span {
            border-radius:999px;
            padding:0.13rem 0.32rem;
            background:#eef2ff;
            color:#4338ca;
            border:1px solid #dbe4ff;
            font-size:0.55rem;
            font-weight:850;
            line-height:1.05;
        }
        .est-suggestions-grid {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:0.55rem;
            margin:0.35rem 0 0.65rem 0;
        }
        .est-suggestion-card {
            display:grid;
            grid-template-columns:46px minmax(0,1fr);
            gap:0.5rem;
            align-items:center;
            max-width:100%;
            min-width:0;
            border:1px solid #e2e8f0;
            border-radius:13px;
            background:linear-gradient(135deg,#ffffff,#f8fafc);
            padding:0.45rem;
            min-height:68px;
            box-shadow:0 7px 16px rgba(15,23,42,0.05);
        }
        .est-suggestion-img {
            width:46px;
            aspect-ratio:0.72;
            border-radius:9px;
            background:#f1f5f9;
            overflow:hidden;
            display:flex;
            align-items:center;
            justify-content:center;
            border:1px solid #e2e8f0;
        }
        .est-suggestion-img img {
            width:100%;
            height:100%;
            object-fit:contain;
            display:block;
        }
        .est-suggestion-placeholder {
            width:100%;
            height:100%;
            display:flex;
            align-items:center;
            justify-content:center;
            text-align:center;
            color:#94a3b8;
            font-size:0.62rem;
            font-weight:850;
            line-height:1.05;
            padding:0.25rem;
        }
        .est-suggestion-copy {
            min-width:0;
        }
        .est-suggestion-copy strong,
        .est-suggestion-copy span,
        .est-suggestion-copy em {
            display:block;
            overflow-wrap:anywhere;
            white-space:normal;
        }
        .est-suggestion-copy strong {
            color:#0f172a;
            font-size:0.82rem;
            line-height:1.12;
        }
        .est-suggestion-copy span {
            color:#64748b;
            font-size:0.72rem;
            font-weight:760;
            margin-top:0.1rem;
        }
        .est-suggestion-copy em {
            color:#6d28d9;
            font-size:0.68rem;
            font-style:normal;
            font-weight:850;
            margin-top:0.08rem;
        }
        .est-card-mini-grid {
            display:grid;
            grid-template-columns:repeat(2,minmax(0,1fr));
            gap:0.22rem;
            margin-top:0.05rem;
        }
        .est-card-mini-grid div {
            border-radius:8px;
            background:#f8fafc;
            padding:0.28rem 0.3rem;
            border:1px solid #e2e8f0;
            min-width:0;
        }
        .est-card-mini-grid div.good {
            background:#ecfdf5;
            border-color:#bbf7d0;
        }
        .est-card-mini-grid div.bad {
            background:#fff1f2;
            border-color:#fecdd3;
        }
        .est-card-mini-grid span {
            display:block;
            color:#64748b;
            font-size:0.56rem;
            line-height:1.05;
            font-weight:850;
        }
        .est-card-mini-grid strong {
            display:block;
            color:#0f172a;
            font-size:0.66rem;
            line-height:1.15;
            margin-top:0.08rem;
        }
        .est-cardmarket-link {
            display:block;
            margin-top:auto;
            margin-bottom:0.42rem;
            border-radius:8px;
            padding:0.34rem 0.36rem;
            background:#eef2ff;
            color:#3730a3 !important;
            font-size:0.61rem;
            line-height:1.18;
            font-weight:900;
            text-align:center;
            text-decoration:none !important;
            white-space:normal;
            overflow-wrap:anywhere;
            min-height:1.95rem;
        }
        .est-cardmarket-link:hover {
            background:#ddd6fe;
        }
        [data-testid="stElementContainer"]:has(.est-retirer-marker) + div {
            margin-top:0.32rem !important;
            padding-top:0.1rem !important;
            border-top:1px solid #eef2f7 !important;
        }
        [data-testid="stElementContainer"]:has(.est-retirer-marker) + div button {
            width:100% !important;
            min-height:2.15rem !important;
        }
        [data-testid="stElementContainer"]:has(.est-card-cote-marker) + div label p {
            font-size:0.66rem !important;
            font-weight:850 !important;
            color:#475569 !important;
        }
        [data-testid="stElementContainer"]:has(.est-card-cote-marker) + div input {
            min-height:2rem !important;
            padding:0.25rem 0.35rem !important;
            font-size:0.78rem !important;
            border-radius:9px !important;
        }
        [data-testid="stElementContainer"]:has(.est-card-cote-marker) + div {
            margin-top:0 !important;
            margin-bottom:0.02rem !important;
        }
        .est-toggle-marker {
            display:block;
            height:0;
            overflow:hidden;
        }
        [data-testid="stElementContainer"]:has(.est-toggle-marker) + div {
            height:0 !important;
            min-height:0 !important;
            overflow:hidden !important;
            margin:0 !important;
            padding:0 !important;
        }
        [data-testid="stElementContainer"]:has(.est-toggle-marker) + div button {
            opacity:0 !important;
            height:0 !important;
            min-height:0 !important;
            padding:0 !important;
            margin:0 !important;
            border:0 !important;
            pointer-events:none !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-page-intro) [data-testid="stForm"] {
            padding:0.65rem 0.75rem !important;
            border-radius:14px !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-page-intro) [data-testid="stForm"] [data-testid="stVerticalBlock"] {
            gap:0.35rem !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-page-intro) input,
        [data-testid="stVerticalBlock"]:has(.est-page-intro) textarea {
            min-height:2.25rem !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-page-intro) label {
            margin-bottom:0.1rem !important;
        }
        @media(max-width:760px) {
            .est-card-main {
                grid-template-columns:72px minmax(0,1fr);
                gap:0.72rem;
                padding:0.78rem;
            }
            .est-metrics,
            .est-detail-kpis {
                grid-template-columns:repeat(2,minmax(0,1fr));
            }
            .est-kpi {
                padding:0.5rem;
            }
            .est-detail-shell {
                padding:0;
                border-radius:0;
            }
            .est-suggestions-grid {
                grid-template-columns:1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _build_opportunities(estimates, settings, estimation_totals_func):
    opportunities = []
    for estimate in estimates:
        totals = estimation_totals_func(estimate, settings)
        label, _ = _opportunity_label(totals)
        opportunities.append(
            {
                "estimate": estimate,
                "totals": totals,
                "label": label,
                "tone": _tone_for_status(label, estimate.get("status")),
                "score": _estimate_score(totals),
            }
        )
    opportunities.sort(key=lambda item: item["score"], reverse=True)
    return opportunities


def _bind_estimation_box_clicks(run_html_func):
    run_html_func(
        """
        <script>
        (function(){
            const doc = parent.document;
            function findToggleButton(uid){
                const marker = doc.querySelector('[data-est-toggle-marker="' + uid + '"]');
                if (!marker) return null;
                let node = marker.closest('[data-testid="stElementContainer"]');
                for (let i = 0; node && i < 8; i++) {
                    node = node.nextElementSibling;
                    const btn = node ? node.querySelector('button') : null;
                    if (btn) return btn;
                }
                return null;
            }
            function bind(){
                doc.querySelectorAll('[data-est-card-uid]').forEach(function(card){
                    if (card.dataset.estClickBound === '1') return;
                    card.dataset.estClickBound = '1';
                    card.addEventListener('click', function(event){
                        if (event.target.closest('a')) return;
                        const btn = findToggleButton(card.getAttribute('data-est-card-uid'));
                        if (btn) btn.click();
                    });
                    card.addEventListener('keydown', function(event){
                        if (event.key !== 'Enter' && event.key !== ' ') return;
                        event.preventDefault();
                        const btn = findToggleButton(card.getAttribute('data-est-card-uid'));
                        if (btn) btn.click();
                    });
                });
            }
            bind();
            setTimeout(bind, 250);
            setTimeout(bind, 900);
        })();
        </script>
        """,
        height=0,
    )


def render_estimations_page(
    *,
    load_estimations_func,
    save_estimations_func,
    add_estimation_card_func,
    estimation_totals_func,
    ld_func,
    sd_func,
    fetch_listing_preview_image_func,
    cardmarket_search_url_func,
    search_in_cache_func,
    proxy_img_func,
    img_with_fallback_func,
    render_page_header_func,
    fp_func,
    normalize_name_func,
    parse_float_input_func,
    new_uid_func,
    is_mobile_mode_func,
    ecd_func,
    run_html_func,
    cache_enrichment_func=None,
):
    st.markdown(
        render_page_header_func("Estimations", "Repérer vite les cartes à acheter", "📉"),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="est-page-intro">Des boîtes simples pour comparer une opportunité, regarder la cote, puis décider si ça vaut le coup.</p>',
        unsafe_allow_html=True,
    )
    _render_css()

    edata = load_estimations_func()
    settings = edata["settings"]
    estimates = edata["estimations"]

    st.markdown(
        '<div class="est-create-card"><strong>Créer une nouvelle estimation</strong><br><span>Ajoute un prix demandé, puis complète avec les cartes à comparer.</span></div>',
        unsafe_allow_html=True,
    )
    with st.expander("Créer une nouvelle estimation", expanded=not estimates):
        with st.form("new_estimation_box"):
            source_names = list(settings.get("sources", {}).keys()) or ["Vinted"]
            c1, c2, c3 = st.columns([2.2, 1, 1])
            new_est_name = c1.text_input("Nom de l'opportunité", placeholder="Ex: Dracaufeu 199/165")
            new_est_source = c2.selectbox(
                "Type d'achat",
                source_names,
                index=source_names.index(settings.get("default_source")) if settings.get("default_source") in source_names else 0,
            )
            new_est_price = c3.text_input("Prix demandé (€)", value="0,00")
            new_est_url = st.text_input("Lien annonce (optionnel)", placeholder="https://www.vinted.fr/items/...")
            if st.form_submit_button("Créer l'estimation"):
                if not new_est_name.strip():
                    st.error("Nom requis.")
                else:
                    estimate = {
                        "uid": new_uid_func("estimate"),
                        "name": new_est_name.strip(),
                        "source": new_est_source,
                        "fees": 0.0,
                        "safety_eur": 0.0,
                        "seller_price": parse_float_input_func(new_est_price, 0.0),
                        "listing_url": new_est_url.strip(),
                        "listing_image_url": fetch_listing_preview_image_func(new_est_url) if new_est_url.strip() else "",
                        "status": "En cours",
                        "created_at": datetime.now().isoformat()[:10],
                        "cards": [],
                    }
                    edata["estimations"].append(estimate)
                    save_estimations_func(edata)
                    st.session_state["active_estimation_uid"] = estimate["uid"]
                    st.rerun()

    if not estimates:
        st.info("Aucune estimation pour le moment. Crée ta première boîte au-dessus.")
        return

    opportunities = _build_opportunities(estimates, settings, estimation_totals_func)

    f1, f2, f3 = st.columns([2, 1, 1])
    search = f1.text_input("Rechercher une estimation", placeholder="Nom, carte, source...", key="est_box_search")
    status_filter = f2.selectbox("État", ["Tous", "Très intéressant", "Intéressant", "Correct", "Trop cher", "À vérifier"], key="est_box_status_filter")
    max_budget_raw = f3.text_input("Budget max (€)", value="", placeholder="Ex: 120", key="est_box_budget")
    max_budget = parse_float_input_func(max_budget_raw, 0.0) if max_budget_raw.strip() else 0.0

    filtered = []
    query = normalize_name_func(search) if search else ""
    for item in opportunities:
        estimate = item["estimate"]
        totals = item["totals"]
        searchable = " ".join(
            [
                str(estimate.get("name", "")),
                str(estimate.get("source", "")),
                str(estimate.get("status", "")),
                " ".join(str(card.get("name", "")) for card in estimate.get("cards", [])),
            ]
        )
        if query and query not in normalize_name_func(searchable):
            continue
        if status_filter != "Tous" and item["label"] != status_filter:
            continue
        if max_budget > 0 and _safe_float(totals.get("seller_price")) > max_budget:
            continue
        filtered.append(item)

    if not filtered:
        st.info("Aucune estimation ne correspond aux filtres.")
        return

    active_uid = st.session_state.get("active_estimation_uid", "")

    for item in filtered:
        estimate = item["estimate"]
        totals = item["totals"]
        uid = estimate.get("uid")
        is_active = active_uid == uid
        st.markdown(_estimate_box_html(item, fp_func, proxy_img_func, active=is_active), unsafe_allow_html=True)
        st.markdown(f'<span class="est-toggle-marker" data-est-toggle-marker="{html.escape(str(uid), quote=True)}"></span>', unsafe_allow_html=True)
        if st.button("\u200b", key=f"toggle_est_box_{uid}"):
            st.session_state["active_estimation_uid"] = "" if is_active else uid
            st.rerun()

        if is_active:
            _render_open_estimation(
                estimate=estimate,
                totals=totals,
                settings=settings,
                edata=edata,
                uid=uid,
                save_estimations_func=save_estimations_func,
                add_estimation_card_func=add_estimation_card_func,
                ld_func=ld_func,
                sd_func=sd_func,
                fetch_listing_preview_image_func=fetch_listing_preview_image_func,
                cardmarket_search_url_func=cardmarket_search_url_func,
                search_in_cache_func=search_in_cache_func,
                img_with_fallback_func=img_with_fallback_func,
                fp_func=fp_func,
                normalize_name_func=normalize_name_func,
                parse_float_input_func=parse_float_input_func,
                new_uid_func=new_uid_func,
                is_mobile_mode_func=is_mobile_mode_func,
                ecd_func=ecd_func,
                proxy_img_func=proxy_img_func,
                cache_enrichment_func=cache_enrichment_func,
            )

    _bind_estimation_box_clicks(run_html_func)

    with st.expander("Réglages de rachat", expanded=False):
        st.caption("Ces pourcentages servent à calculer le prix maximum conseillé.")
        with st.form("estimation_settings_form_box"):
            new_sources = {}
            cols = st.columns(3)
            for col, (source_name, pct) in zip(cols, settings.get("sources", {}).items()):
                raw = col.text_input(f"{source_name} (%)", value=f"{float(pct):.0f}".replace(".", ","), key=f"est_setting_box_{source_name}")
                new_sources[source_name] = min(max(parse_float_input_func(raw, pct), 0.0), 100.0)
            source_names = list(new_sources.keys()) or ["Vinted"]
            default_source = st.selectbox(
                "Type par défaut",
                source_names,
                index=source_names.index(settings.get("default_source")) if settings.get("default_source") in source_names else 0,
                key="est_default_source_box",
            )
            if st.form_submit_button("Sauvegarder les règles"):
                edata["settings"]["sources"] = new_sources
                edata["settings"]["default_source"] = default_source
                save_estimations_func(edata)
                st.rerun()


def _render_open_estimation(
    *,
    estimate,
    totals,
    settings,
    edata,
    uid,
    save_estimations_func,
    add_estimation_card_func,
    ld_func,
    sd_func,
    fetch_listing_preview_image_func,
    cardmarket_search_url_func,
    search_in_cache_func,
    img_with_fallback_func,
    fp_func,
    normalize_name_func,
    parse_float_input_func,
    new_uid_func,
    is_mobile_mode_func,
    ecd_func,
    proxy_img_func=None,
    cache_enrichment_func=None,
):
    label, _ = _opportunity_label(totals)
    tone = _tone_for_status(label, estimate.get("status"))
    seller_price = _safe_float(totals.get("seller_price"))
    total_cote = _safe_float(totals.get("total_cote"))
    real_pct = _safe_float(totals.get("real_pct"))
    margin = _safe_float(totals.get("theoretical_margin"))
    card_count = sum(_safe_int(card.get("quantity")) for card in estimate.get("cards", []) or [])
    margin_accent = "margin-good" if margin > 0 else "margin-bad" if margin < 0 else "margin-neutral"

    st.markdown(
        f"""
        <div class="est-detail-shell">
        <div class="est-detail-title">
            <div>
                <span class="est-badge {tone}">{html.escape(label)}</span>
                <h3>{html.escape(str(estimate.get("name") or "Estimation"))}</h3>
            </div>
        </div>
        <div class="est-detail-kpis">
            {_kpi("Type d'achat", estimate.get("source") or "Vinted", accent="type")}
            {_kpi("Prix demandé", fp_func(seller_price) if seller_price > 0 else "À saisir", accent="price")}
            {_kpi("Cote totale", fp_func(total_cote), accent="value")}
            {_kpi("% cote", f"{real_pct:.1f}%" if real_pct else "À vérifier", accent="percent")}
            {_kpi("Marge", fp_func(margin) if total_cote else "À vérifier", accent=margin_accent)}
            {_kpi("Cartes", card_count, accent="count")}
            {_kpi("Rachat max", fp_func(totals.get("max_buy", 0.0)), accent="buy")}
            {_kpi("Collection", totals.get("collection_cards", 0), accent="count")}
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Ajouter une carte dans cette estimation", expanded=not estimate.get("cards")):
        a1, a2, a4 = st.columns([2, 1, 0.7])
        name_key = f"est_add_name_keyup_{uid}"
        number_key = f"est_add_number_box_{uid}"
        qty_key = f"est_add_qty_box_{uid}"
        condition_key = f"est_add_condition_box_{uid}"
        special_key = f"est_add_special_box_{uid}"
        note_key = f"est_add_note_box_{uid}"
        pending_reset_key = f"est_pending_add_reset_{uid}"
        name_placeholder = "Ex: Marisson AR, Groudon EX magma"
        name_component_state_key = _st_keyup_component_state_key(
            name_key,
            debounce=_ESTIMATION_KEYUP_DEBOUNCE_MS,
            placeholder=name_placeholder,
        )
        if st.session_state.pop(pending_reset_key, False):
            old_dynamic_prefix = f"est_add_name_keyup_{uid}_"
            for stale_key in [key for key in st.session_state.keys() if str(key).startswith(old_dynamic_prefix)]:
                st.session_state.pop(stale_key, None)
            st.session_state.pop(name_key, None)
            st.session_state.pop(name_component_state_key, None)
            st.session_state[number_key] = ""
            st.session_state[qty_key] = "1"
            st.session_state[condition_key] = "NM"
            st.session_state[special_key] = []
            st.session_state[note_key] = ""
            st.session_state.pop(f"est_selected_match_{uid}", None)
            st.session_state.pop(f"est_selected_details_{uid}", None)
        if qty_key not in st.session_state:
            st.session_state[qty_key] = "1"
        with a1:
            try:
                card_name = st_keyup(
                    "Nom",
                    value=st.session_state.get(name_key, "") or "",
                    key=name_key,
                    placeholder=name_placeholder,
                    debounce=_ESTIMATION_KEYUP_DEBOUNCE_MS,
                ) or ""
            except Exception as exc:
                _log_once(
                    "add_form_name_field",
                    f"{uid}|{type(exc).__name__}",
                    f'[Estimations Add Form] name_field_rendered=no reason="{type(exc).__name__}: {exc}"',
                )
                card_name = st.text_input("Nom", value="", key=f"est_add_name_fallback_{uid}", placeholder=name_placeholder)
        card_number = a2.text_input("Numéro", placeholder="199/165", key=number_key)
        card_qty = a4.text_input("Qté", key=qty_key)

        suggestions = _card_suggestions(card_name, card_number, search_in_cache_func, ecd_func, normalize_name_func)
        enrichment_notice_key = f"est_cache_enrichment_notice_{uid}"
        if st.session_state.get(enrichment_notice_key):
            st.caption(st.session_state.pop(enrichment_notice_key))
        if suggestions:
            st.caption("Suggestions depuis le cache cartes PokéStock")
            if _suggestions_missing_set_match(card_name, suggestions, normalize_name_func):
                st.caption("Aucun match exact pour ce tag de sÃ©rie dans le cache. RÃ©sultats proches affichÃ©s.")
            if _suggestions_missing_type_match(card_name, suggestions, "ar", normalize_name_func):
                st.caption("Aucune AR exacte trouv?e dans le cache. R?sultats proches affich?s.")
            if _suggestions_missing_type_match(card_name, suggestions, "rainbow", normalize_name_func):
                st.caption("Aucune carte Rainbow exacte trouvée dans le cache. Résultats proches affichés.")
            exact_suggestions, close_suggestions, strict_types = _strict_suggestion_sections(card_name, suggestions[:8], normalize_name_func)
            suggestion_sections = []
            if strict_types and exact_suggestions:
                suggestion_sections.append(("", exact_suggestions))
                if close_suggestions:
                    suggestion_sections.append(("R?sultats proches", close_suggestions))
            else:
                suggestion_sections.append(("", suggestions[:8]))
            cols_per_row = 1 if is_mobile_mode_func() else 6
            suggestion_offset = 0
            for section_title, section_suggestions in suggestion_sections:
                if section_title:
                    st.caption(section_title)
                for row_start in range(0, len(section_suggestions), cols_per_row):
                    cols = st.columns(cols_per_row)
                    for cidx, suggestion in enumerate(section_suggestions[row_start : row_start + cols_per_row]):
                        enriched = suggestion["card"]
                        button_ix = suggestion_offset + row_start + cidx
                        with cols[cidx]:
                            _render_suggestion_card(enriched, proxy_img_func=proxy_img_func)
                            if st.button("Choisir", key=f"est_suggestion_pick_{uid}_{button_ix}", width="stretch"):
                                details = _selected_card_details(enriched)
                                direct_specials = st.session_state.get(special_key, [])
                                if not isinstance(direct_specials, list):
                                    direct_specials = []
                                direct_clean_specials = [tag for tag in direct_specials if tag != "Collection"]
                                before_count = len(estimate.get("cards", []) or [])
                                print(
                                    "[Estimations Pick] "
                                    f'selected="{details.get("name", "")}" number="{details.get("number", "")}" '
                                    f'set="{details.get("set", "")}" rarity="{details.get("rarity", "")}" '
                                    f'image={"yes" if details.get("image_url") or details.get("image_url_en") else "no"} '
                                    f'exact_cm={"yes" if _exact_cardmarket_url(details) else "no"}',
                                    flush=True,
                                )
                                add_estimation_card_func(
                                    estimate,
                                    details.get("name") or card_name,
                                    details.get("number") or card_number,
                                    "0,00",
                                    st.session_state.get(qty_key, "1"),
                                    st.session_state.get(condition_key, "NM") or "NM",
                                    direct_clean_specials,
                                    st.session_state.get(note_key, ""),
                                    "Collection" in direct_specials,
                                    suggestion["match"],
                                )
                                _apply_selected_card_details(estimate, details)
                                after_count = len(estimate.get("cards", []) or [])
                                if after_count > before_count and estimate.get("cards"):
                                    added_card = estimate["cards"][-1]
                                    print(
                                        "[Estimations Add] "
                                        f'added="{added_card.get("name", "")}" number="{added_card.get("number", "")}" '
                                        f'image={"yes" if added_card.get("image_url") or added_card.get("image_url_en") else "no"} '
                                        f'estimate="{estimate.get("name", "")}"',
                                        flush=True,
                                    )
                                else:
                                    print(
                                        "[Estimations Add] failed "
                                        f'reason="suggestion not appended" name="{details.get("name", "")}" '
                                        f'number="{details.get("number", "")}" estimate="{estimate.get("name", "")}"',
                                        flush=True,
                                    )
                                save_estimations_func(edata)
                                st.session_state.pop(f"pending_est_choice_{uid}", None)
                                st.session_state.pop(f"est_selected_match_{uid}", None)
                                st.session_state.pop(f"est_selected_details_{uid}", None)
                                st.session_state[pending_reset_key] = True
                                st.rerun()
                suggestion_offset += len(section_suggestions)
        elif len(str(card_name or "").strip()) >= 3:
            st.caption("Aucun résultat fiable dans le cache pour cette recherche.")

        search_context = _search_context(card_name, normalize_name_func)
        can_enrich_cache = (
            cache_enrichment_func
            and str(card_name or "").strip()
            and search_context.get("requested_set_tags")
            and not _has_exact_search_match(card_name, suggestions, normalize_name_func)
        )
        if can_enrich_cache:
            st.caption("Cette serie ou cette carte n'est pas encore dans le cache local.")
            if st.button("Mettre a jour le cache pour cette recherche", key=f"est_cache_enrich_{uid}", width="stretch"):
                requested_sets = search_context.get("requested_set_tags", [])
                print(
                    "[Estimations Cache Enrichment] "
                    f'query="{card_name}" requested_set="{",".join(tag.upper() for tag in requested_sets)}"',
                    flush=True,
                )
                result = cache_enrichment_func(st.session_state.get("cards_index", {}), requested_sets, normalize_name_func)
                st.session_state["cards_index"] = result.get("cards_index", st.session_state.get("cards_index", {}))
                _reset_estimation_search_memory_cache()
                refreshed = _card_suggestions(card_name, card_number, search_in_cache_func, ecd_func, normalize_name_func)
                exact_after = _has_exact_search_match(card_name, refreshed, normalize_name_func)
                print(
                    "[Estimations Cache Enrichment] "
                    f'source="{",".join(result.get("sources", []))}" fetched={result.get("fetched", 0)} '
                    f'added={result.get("added", 0)} exact_match_after_refresh={"yes" if exact_after else "no"}',
                    flush=True,
                )
                if result.get("errors"):
                    print(
                        "[Estimations Cache Enrichment] errors="
                        + " | ".join(str(err) for err in result.get("errors", [])),
                        flush=True,
                    )
                if exact_after:
                    st.session_state[enrichment_notice_key] = "Cache mis a jour : match exact trouve."
                elif result.get("sources"):
                    st.session_state[enrichment_notice_key] = "Cache mis a jour, mais aucun match exact pour cette recherche."
                else:
                    st.session_state[enrichment_notice_key] = "Mise a jour impossible pour cette recherche."
                st.rerun()

        b1, b2 = st.columns([1, 2])
        card_condition = b1.selectbox("État", ["NM", "EX", "GD", "LP", "PL", "POOR"], key=condition_key)
        card_specials = b2.multiselect(
            "Spécial",
            ["Reverse", "1ère Éd", "Japonaise", "Collection", "Scellé", "Stamp", "Promo", "Master Ball", "Poké Ball"],
            key=special_key,
        )
        card_note = st.text_input("Note rapide", placeholder="Photo floue, coin abîmé...", key=note_key)
        keep_collection = "Collection" in card_specials
        clean_specials = [tag for tag in card_specials if tag != "Collection"]
        if st.button("Ajouter la carte", key=f"add_est_card_box_submit_{uid}", width="stretch"):
            if not card_name.strip():
                st.error("Nom requis.")
            else:
                manual_match_status, manual_candidates = _manual_add_exact_match(card_name, card_number, normalize_name_func)
                if manual_match_status == "ambiguous":
                    print(
                        "[Estimations Manual Add] "
                        f'name="{card_name}" number="{card_number}" match=ambiguous candidates={len(manual_candidates)} image=no',
                        flush=True,
                    )
                    st.info("Plusieurs cartes correspondent : utilise Choisir pour sélectionner la bonne.")
                else:
                    matches = [manual_candidates[0]["match"]] if manual_match_status == "exact" else []
                    selected_details = _selected_card_details(manual_candidates[0]["card"]) if manual_match_status == "exact" else None
                    before_count = len(estimate.get("cards", []) or [])
                    add_estimation_card_func(
                        estimate,
                        selected_details.get("name", card_name) if selected_details else card_name,
                        selected_details.get("number", card_number) if selected_details else card_number,
                        "0,00",
                        card_qty,
                        card_condition,
                        clean_specials,
                        card_note,
                        keep_collection,
                        None,
                    )
                    _apply_selected_card_details(estimate, selected_details)
                    after_count = len(estimate.get("cards", []) or [])
                    image_status = "yes" if selected_details and (selected_details.get("image_url") or selected_details.get("image_url_en")) else "no"
                    print(
                        "[Estimations Manual Add] "
                        f'name="{card_name}" number="{card_number}" match={manual_match_status} image={image_status}',
                        flush=True,
                    )
                    if after_count > before_count and estimate.get("cards"):
                        added_card = estimate["cards"][-1]
                        print(
                            "[Estimations Add] "
                            f'added="{added_card.get("name", "")}" number="{added_card.get("number", "")}" '
                            f'image={"yes" if added_card.get("image_url") or added_card.get("image_url_en") else "no"} '
                            f'estimate="{estimate.get("name", "")}"',
                            flush=True,
                        )
                    else:
                        print(
                            "[Estimations Add] failed "
                            f'reason="card not appended" name="{card_name}" number="{card_number}" '
                            f'estimate="{estimate.get("name", "")}"',
                            flush=True,
                        )
                    st.session_state.pop(f"est_selected_match_{uid}", None)
                    st.session_state.pop(f"est_selected_details_{uid}", None)
                    st.session_state[pending_reset_key] = True
                    save_estimations_func(edata)
                    st.rerun()

    pending = st.session_state.get(f"pending_est_choice_{uid}")
    if pending:
        st.warning(f"{len(pending.get('matches', []))} cartes possibles trouvées. Choisis la bonne.")
        cols = st.columns(2 if is_mobile_mode_func() else 4)
        for pidx, match in enumerate(pending.get("matches", [])):
            card_dict, set_name = match
            enriched = ecd_func(card_dict, set_name, lang="fr")
            if not enriched.get("image_url"):
                enriched["image_url"] = _tcgdex_image_from_id(enriched.get("id"), enriched.get("number"))
            with cols[pidx % len(cols)]:
                if enriched.get("image_url"):
                    st.markdown(
                        img_with_fallback_func(enriched.get("image_url", ""), enriched.get("image_url_en", ""), width="100%", style="border-radius:10px;"),
                        unsafe_allow_html=True,
                    )
                st.caption(f"{enriched.get('name','Carte')} · {enriched.get('set','')} · #{enriched.get('number','')}")
                if st.button("Choisir", key=f"pick_est_box_{uid}_{pidx}"):
                    details = _selected_card_details(enriched)
                    print(
                        "[Estimations Pick] "
                        f'selected="{details.get("name", "")}" number="{details.get("number", "")}" '
                        f'set="{details.get("set", "")}" rarity="{details.get("rarity", "")}" '
                        f'image={"yes" if details.get("image_url") or details.get("image_url_en") else "no"} '
                        f'exact_cm={"yes" if _exact_cardmarket_url(details) else "no"}',
                        flush=True,
                    )
                    before_count = len(estimate.get("cards", []) or [])
                    add_estimation_card_func(
                        estimate,
                        pending["name"],
                        pending["number"],
                        pending["cote"],
                        pending["qty"],
                        pending["condition"],
                        pending["specials"],
                        pending["note"],
                        pending.get("is_collection", False),
                        match,
                    )
                    _apply_selected_card_details(estimate, details)
                    after_count = len(estimate.get("cards", []) or [])
                    if after_count > before_count and estimate.get("cards"):
                        added_card = estimate["cards"][-1]
                        print(
                            "[Estimations Add] "
                            f'added="{added_card.get("name", "")}" number="{added_card.get("number", "")}" '
                            f'image={"yes" if added_card.get("image_url") or added_card.get("image_url_en") else "no"} '
                            f'estimate="{estimate.get("name", "")}"',
                            flush=True,
                        )
                    else:
                        print(
                            "[Estimations Add] failed "
                            f'reason="card not appended from choice" name="{pending.get("name", "")}" '
                            f'number="{pending.get("number", "")}" estimate="{estimate.get("name", "")}"',
                            flush=True,
                        )
                    save_estimations_func(edata)
                    st.session_state.pop(f"pending_est_choice_{uid}", None)
                    st.session_state[pending_reset_key] = True
                    st.rerun()
        if st.button("Annuler le choix", key=f"cancel_est_choice_box_{uid}"):
            st.session_state.pop(f"pending_est_choice_{uid}", None)
            st.rerun()

    st.markdown("#### Cartes suivies")
    cards = estimate.get("cards", []) or []
    if not cards:
        st.info("Aucune carte dans cette estimation pour le moment.")
    else:
        filter_key = f"est_internal_card_search_{uid}"
        internal_query = st_keyup(
            "Rechercher dans cette estimation",
            value="",
            key=filter_key,
            placeholder="Rechercher une carte dans cette estimation...",
            debounce=_ESTIMATION_KEYUP_DEBOUNCE_MS,
        ) or ""
        visible_cards = _filtered_estimation_cards(cards, internal_query, normalize_name_func)
        _log_once(
            "estimation_display_order",
            f'{uid}|newest_first',
            f'[Estimations Display] order=newest_first estimate="{estimate.get("name", "")}"',
        )
        _log_once(
            "estimation_filter",
            f'{uid}|{normalize_name_func(internal_query)}|{len(visible_cards)}|{len(cards)}',
            f'[Estimations Filter] estimate="{estimate.get("name", "")}" query="{internal_query}" '
            f"shown={len(visible_cards)} total={len(cards)}",
        )
        st.caption(f"{len(visible_cards)} cartes sur {len(cards)} affichées")
        missing_image_cards = _cards_missing_estimation_image(cards)
        repair_notice_key = f"est_image_repair_notice_{uid}"
        if st.session_state.get(repair_notice_key):
            st.caption(st.session_state.pop(repair_notice_key))
        if missing_image_cards:
            if st.button("R?parer les images manquantes", key=f"est_repair_missing_images_{uid}", width="stretch"):
                repair_result = _repair_missing_estimation_images(estimate, normalize_name_func, cache_enrichment_func)
                if repair_result.get("repaired", 0) > 0:
                    save_estimations_func(edata)
                st.session_state[repair_notice_key] = (
                    f"Images r?par?es : {repair_result.get('repaired', 0)} / {repair_result.get('missing', 0)}."
                )
                st.rerun()
        cols_per_row = 1 if is_mobile_mode_func() else 6
        for row_start in range(0, len(visible_cards), cols_per_row):
            cols = st.columns(cols_per_row)
            for cidx, card in enumerate(visible_cards[row_start : row_start + cols_per_row]):
                with cols[cidx]:
                    card_meta = _render_tracked_card(card, estimate, fp_func, img_with_fallback_func, cardmarket_search_url_func, normalize_name_func, proxy_img_func=proxy_img_func)
                    card_uid = card.get("uid") or f"{row_start}_{cidx}"
                    cote_key = f"est_card_cote_{uid}_{card_uid}"
                    cote_seen_key = f"{cote_key}_seen"
                    qty_edit_key = f"est_card_qty_{uid}_{card_uid}"
                    qty_seen_key = f"{qty_edit_key}_seen"
                    current_cote = _safe_float(card.get("cote"))
                    if cote_key not in st.session_state:
                        st.session_state[cote_key] = f"{current_cote:.2f}".replace(".", ",") if current_cote > 0 else ""
                    st.markdown('<span class="est-tracked-bubble-marker"></span>', unsafe_allow_html=True)
                    with st.container(border=True):
                        badge_html = "".join(f'<span>{html.escape(badge)}</span>' for badge in card_meta.get("badges", []))
                        st.markdown(
                            f"""
                            <div class="est-tracked-heading">
                                <h4>{html.escape(str(card.get("name") or "Carte"))}</h4>
                                {f'<div class="est-tracked-tags">{html.escape(card_meta["tags"])}</div>' if card_meta["tags"] else ''}
                                {f'<div class="est-badge-row">{badge_html}</div>' if badge_html else ''}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        current_qty = _safe_int(card.get("quantity"))
                        edited_qty = st.number_input("Qté", min_value=1, value=current_qty, step=1, key=qty_edit_key)
                        previous_qty_seen = st.session_state.get(qty_seen_key)
                        st.session_state[qty_seen_key] = int(edited_qty)
                        if previous_qty_seen is not None and int(edited_qty) != previous_qty_seen and int(edited_qty) != current_qty:
                            print(
                                f'[Estimations Quantity] card="{card.get("name", "Carte")}" old={current_qty} new={int(edited_qty)}',
                                flush=True,
                            )
                            card["quantity"] = int(edited_qty)
                            save_estimations_func(edata)
                            st.rerun()
                        st.markdown('<span class="est-card-cote-marker"></span>', unsafe_allow_html=True)
                        cote_text = st.text_input("Cote (€)", key=cote_key, placeholder="0,00")
                        new_cote = 0.0 if not str(cote_text or "").strip() else max(parse_float_input_func(cote_text, current_cote), 0.0)
                        previous_cote_seen = st.session_state.get(cote_seen_key)
                        st.session_state[cote_seen_key] = str(cote_text or "")
                        if previous_cote_seen is not None and str(cote_text or "") != previous_cote_seen and abs(new_cote - current_cote) > 0.009:
                            card["cote"] = new_cote
                            save_estimations_func(edata)
                            st.rerun()
                        st.markdown(
                            f"""
                            <div class="est-card-mini-grid">
                                <div><span>Payé estimé</span><strong>{html.escape(card_meta["paid_label"])}</strong></div>
                                <div class="{html.escape(card_meta["margin_class"])}"><span>Marge</span><strong>{html.escape(card_meta["margin_label"])}</strong></div>
                            </div>
                            <a class="est-cardmarket-link" href="{card_meta["cm_url"]}" target="_blank">Chercher la cote sur Cardmarket</a>
                            """,
                            unsafe_allow_html=True,
                        )
                        if not card_meta.get("has_image"):
                            if st.button("Actualiser l'image", key=f"est_refresh_img_{uid}_{card_uid}", width="stretch"):
                                if _refresh_estimation_card_image(card, normalize_name_func, cache_enrichment_func):
                                    save_estimations_func(edata)
                                st.rerun()
                        upload_label = "Remplacer la photo" if card_meta.get("has_manual_image") else "Ajouter une photo"
                        if (not card_meta.get("has_image")) or card_meta.get("has_manual_image"):
                            with st.expander(upload_label, expanded=False):
                                uploaded = st.file_uploader(
                                    upload_label,
                                    type=["png", "jpg", "jpeg", "webp"],
                                    key=f"est_manual_img_upload_{uid}_{card_uid}",
                                )
                                if uploaded:
                                    st.image(uploaded, width=110)
                                    if st.button("Enregistrer la photo", key=f"est_manual_img_save_{uid}_{card_uid}", width="stretch"):
                                        saved_path = _save_estimation_manual_image(card, uploaded)
                                        if saved_path:
                                            card["manual_image_path"] = saved_path
                                            card.pop("manual_image_url", None)
                                            save_estimations_func(edata)
                                            print(
                                                f'[Estimations Manual Image] card="{card.get("name", "Carte")}" '
                                                f'action=upload saved=yes path="{saved_path}"',
                                                flush=True,
                                            )
                                            st.rerun()
                                if card_meta.get("has_manual_image"):
                                    if st.button("Supprimer la photo manuelle", key=f"est_manual_img_delete_{uid}_{card_uid}", width="stretch"):
                                        card.pop("manual_image_path", None)
                                        card.pop("manual_image_url", None)
                                        save_estimations_func(edata)
                                        print(
                                            f'[Estimations Manual Image] card="{card.get("name", "Carte")}" action=delete saved=yes',
                                            flush=True,
                                        )
                                        st.rerun()
                        st.markdown('<span class="est-retirer-marker"></span>', unsafe_allow_html=True)
                        if st.button("Retirer", key=f"del_est_card_box_{uid}_{card_uid}"):
                            estimate["cards"] = [c for c in estimate.get("cards", []) if c.get("uid") != card.get("uid")]
                            save_estimations_func(edata)
                            st.rerun()

    with st.expander("Détails avancés et actions", expanded=False):
        if estimate.get("listing_url"):
            safe_url = html.escape(estimate.get("listing_url", ""), quote=True)
            st.markdown(f'<a href="{safe_url}" target="_blank">Ouvrir l’annonce</a>', unsafe_allow_html=True)
        with st.form(f"estimate_meta_box_{uid}"):
            m1, m2, m3 = st.columns([2, 1, 1])
            edit_name = m1.text_input("Nom", value=estimate.get("name", ""), key=f"est_name_box_{uid}")
            source_names = list(settings.get("sources", {}).keys()) or ["Vinted"]
            edit_source = m2.selectbox("Type", source_names, index=source_names.index(estimate.get("source")) if estimate.get("source") in source_names else 0, key=f"est_source_box_{uid}")
            status_options = ["En cours", "À surveiller", "Achetée", "Refusée"]
            edit_status = m3.selectbox("Statut", status_options, index=status_options.index(estimate.get("status", "En cours")) if estimate.get("status", "En cours") in status_options else 0, key=f"est_status_box_{uid}")
            n1, n2, n3 = st.columns([1, 1, 2])
            edit_seller_price = n1.text_input("Prix demandé (€)", value=f"{float(estimate.get('seller_price', 0.0) or 0.0):.2f}".replace(".", ","), key=f"est_seller_box_{uid}")
            edit_safety = n2.text_input("Marge sécurité (€)", value=f"{float(estimate.get('safety_eur', 0.0) or 0.0):.2f}".replace(".", ","), key=f"est_safety_box_{uid}")
            edit_url = n3.text_input("URL annonce", value=estimate.get("listing_url", ""), key=f"est_url_box_{uid}")
            if st.form_submit_button("Sauvegarder les détails"):
                old_url = estimate.get("listing_url", "")
                estimate["name"] = edit_name.strip() or estimate.get("name", "Estimation")
                estimate["source"] = edit_source
                estimate["status"] = edit_status
                estimate["seller_price"] = parse_float_input_func(edit_seller_price, 0.0)
                estimate["fees"] = 0.0
                estimate["safety_eur"] = parse_float_input_func(edit_safety, 0.0)
                estimate["listing_url"] = edit_url.strip()
                if estimate["listing_url"] and (estimate["listing_url"] != old_url or not estimate.get("listing_image_url")):
                    estimate["listing_image_url"] = fetch_listing_preview_image_func(estimate["listing_url"])
                save_estimations_func(edata)
                st.rerun()

        st.write(
            {
                "cote_revente": fp_func(totals["total_cote"]),
                "cartes_collection": totals["collection_cards"],
                "rachat_max": fp_func(totals["max_buy"]),
                "source": estimate.get("source"),
                "date": estimate.get("created_at"),
            }
        )

        action_cols = st.columns(3)
        if action_cols[0].button("Créer un vrai lot", width="stretch", disabled=not estimate.get("cards") or bool(estimate.get("created_lot_uid")), key=f"create_real_lot_box_{uid}"):
            purchase_price = float(estimate.get("seller_price", 0.0) or 0.0) or totals["max_buy"]
            cd_real = ld_func()
            lot_uid = new_uid_func("lot")
            new_lot = {
                "lot_uid": lot_uid,
                "nom": estimate.get("name", "Lot estimé"),
                "prix_achat": purchase_price,
                "cards": [],
                "ventes": [],
                "created": datetime.now().isoformat(),
                "from_estimation_uid": estimate.get("uid"),
                "estimation_listing_url": estimate.get("listing_url", ""),
                "estimation_source": estimate.get("source"),
                "estimation_value": totals["total_cote"],
                "estimation_target_pct": totals["pct"],
            }
            for card in estimate.get("cards", []):
                specials = [s.strip() for s in str(card.get("special", "")).split(",") if s.strip()]
                special_tag = ", ".join([s for s in specials if s not in ("Reverse", "1ère Éd", "Japonaise")])
                new_lot["cards"].append(
                    {
                        "card_uid": new_uid_func("card"),
                        "id": "",
                        "name": card.get("name", "Carte"),
                        "set": card.get("set", ""),
                        "number": card.get("number", ""),
                        "rarity": card.get("rarity", ""),
                        "image_url": card.get("image_url", ""),
                        "image_url_en": card.get("image_url_en", ""),
                        "quantity": int(card.get("quantity", 1) or 1),
                        "sold_quantity": 0,
                        "condition": card.get("condition", "NM"),
                        "suggested_price": float(card.get("cote", 0.0) or 0.0),
                        "is_reverse": "Reverse" in specials,
                        "is_ed1": "1ère Éd" in specials,
                        "special_tag": special_tag,
                        "is_collection_keep": bool(card.get("is_collection")),
                        "sold_entries": [],
                    }
                )
            cd_real.setdefault("lots", []).append(new_lot)
            sd_func(cd_real)
            estimate["status"] = "Achetée"
            estimate["created_lot_uid"] = lot_uid
            save_estimations_func(edata)
            st.success("Lot créé dans le menu Lots.")
            st.rerun()
        if action_cols[1].button("Dupliquer", width="stretch", key=f"duplicate_est_box_{uid}"):
            copy_est = json.loads(json.dumps(estimate, ensure_ascii=False))
            copy_est["uid"] = new_uid_func("estimate")
            copy_est["name"] = f"Copie - {copy_est.get('name','Estimation')}"
            copy_est.pop("created_lot_uid", None)
            copy_est["created_at"] = datetime.now().isoformat()[:10]
            for card in copy_est.get("cards", []):
                card["uid"] = new_uid_func("estcard")
            edata["estimations"].append(copy_est)
            save_estimations_func(edata)
            st.session_state["active_estimation_uid"] = copy_est["uid"]
            st.rerun()
        if action_cols[2].button("Supprimer", width="stretch", key=f"delete_est_box_{uid}"):
            edata["estimations"] = [e for e in edata["estimations"] if e.get("uid") != uid]
            save_estimations_func(edata)
            st.session_state["active_estimation_uid"] = ""
            st.rerun()

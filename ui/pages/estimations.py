"""Estimations page renderer for Pokestock."""

from __future__ import annotations

import base64
from datetime import datetime
import html
import json
import os
import re
import time
import unicodedata
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import streamlit as st
from st_keyup import st_keyup

from services.estimations_service import (
    QUICK_BULK_PURCHASE_UNIT_PRICE,
    QUICK_BULK_RESALE_UNIT_PRICE,
)
from services.market_price_cache_service import (
    apply_market_price_to_card,
    build_market_alerts,
    import_estimations_history,
    load_market_price_cache,
    mark_manual_price,
    market_price_badge,
    refresh_estimation_prices,
    save_market_price_cache,
    upsert_market_price,
)


_ESTIMATION_LOG_SIGNATURES = set()
_ESTIMATION_SUGGESTIONS_CACHE = {}
_ESTIMATION_SUGGESTIONS_CACHE_MAX = 80
_ESTIMATION_SEARCH_INDEX = []
_ESTIMATION_SEARCH_INDEX_SOURCE_ID = None
_ESTIMATION_SEARCH_INDEX_BY_LANG = {"fr": [], "ja": []}
_ESTIMATION_IMAGE_RESOLUTION_CACHE = {}
_ESTIMATION_IMAGE_RESOLUTION_CACHE_MAX = 500
_ESTIMATION_SUGGESTION_IMAGE_CACHE = {}
_ESTIMATION_SUGGESTION_IMAGE_CACHE_MAX = 400
_ESTIMATION_IMAGE_BACKFILL_CACHE = {}
_ESTIMATION_IMAGE_BACKFILL_CACHE_MAX = 300
_ESTIMATION_NORMALIZER_CACHE = {}
_ESTIMATION_NORMALIZER_CACHE_MAX = 30000
_ESTIMATION_KEYUP_DEBOUNCE_MS = 80
ESTIMATIONS_DEBUG = str(os.environ.get("POKESTOCK_ESTIMATIONS_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on"}
ESTIMATIONS_PERF_DEBUG = str(os.environ.get("POKESTOCK_ESTIMATIONS_PERF", "")).strip().lower() in {"1", "true", "yes", "on"}
_KNOWN_ART_RARE_CARD_IDS = {"sv06.5-066"}
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
    "paf": ["paldean fates", "destinees de paldea", "destinées de paldea"],
    "shiny": [
        "paldean fates",
        "destinees de paldea",
        "destinées de paldea",
        "shining fates",
        "shiny fates",
        "destinees radieuses",
        "destinées radieuses",
    ],
}
_SHINY_QUERY_ALIASES = [
    "destinees de paldea",
    "destinées de paldea",
    "paldean fates",
    "destinees radieuses",
    "destinées radieuses",
    "shining fates",
    "shiny fates",
    "shiny",
    "paf",
]
_SHINY_FILTER_TAGS = {"paf", "shiny"}
_JP_CARDS_CACHE_URL = "https://api.tcgdex.net/v2/ja/cards"
_ESTIMATION_STATUS_OPTIONS = [
    "À analyser",
    "Prête pour offre",
    "Photos demandées",
    "En négociation",
    "Offre envoyée",
    "Acceptée",
    "Achetée",
    "Refusée",
    "Expirée",
    "À suivre",
]
_LEGACY_STATUS_MAP = {
    "En cours": "À analyser",
    "À surveiller": "À suivre",
    "Achetée": "Achetée",
    "Refusée": "Refusée",
}
_DEFAULT_CHECKLIST_ITEMS = [
    "Photos recto reçues",
    "Photos verso reçues",
    "Coins vérifiés",
    "Rayures vérifiées",
    "Cartes les plus chères confirmées",
    "État général confirmé",
    "Prix négocié",
    "Frais de port vérifiés",
    "Paiement sécurisé",
    "Lot acheté / refusé / en attente",
]
_SPECIAL_VALUE_TAGS = {
    "AR",
    "FA",
    "ALT",
    "SAR",
    "RAINBOW",
    "HYPER_RARE",
    "SECRET_RARE",
    "TG",
    "GG",
    "PROMO",
    "EX",
    "GX",
    "V",
    "VMAX",
    "VSTAR",
    "GOLD",
}
_CARDMARKET_LANGUAGE_FR = "2"
_CARDMARKET_LANGUAGE_JA = "7"
_SEARCH_PREFERENCE_MAX_BONUS = 18


def _card_language(card, default="fr"):
    lang = str((card or {}).get("lang") or (card or {}).get("language") or "").strip().lower()
    if lang in {"ja", "jp", "jpn", "japanese", "japonais", "japonaise"}:
        return "ja"
    if lang in {"fr", "fra", "french", "francais", "français"}:
        return "fr"
    if _card_is_japanese(card or {}):
        return "ja"
    return default


def _write_normalized_card_language(card, language):
    language = "ja" if str(language or "").lower() in {"ja", "jp", "jpn", "japanese", "japonais", "japonaise"} else "fr"
    changed = card.get("lang") != language or card.get("language") != language
    card["lang"] = language
    card["language"] = language
    if language == "ja" and "Japonaise" not in str(card.get("special") or ""):
        card["special"] = ", ".join(x for x in [card.get("special", ""), "Japonaise"] if str(x or "").strip())
        changed = True
    return changed


def _estimation_search_card_key(card, normalize_name_func):
    card = card or {}
    lang = _card_language(card)
    set_id = str(card.get("set_id") or card.get("set_code") or card.get("set") or "").strip().lower()
    number = str(card.get("number") or card.get("localId") or "").strip().upper().replace(" ", "")
    variant_bits = []
    for key in ("variant", "special", "special_tag", "rarity"):
        value = normalize_name_func(card.get(key, ""))
        if value:
            variant_bits.append(value)
    if card.get("promo"):
        variant_bits.append("promo")
    if card.get("is_reverse"):
        variant_bits.append("reverse")
    if card.get("is_ed1"):
        variant_bits.append("ed1")
    source_id = str(card.get("id") or card.get("card_id") or "").strip().lower()
    name = normalize_name_func(card.get("name", ""))
    return "|".join([lang, set_id, number, "|".join(variant_bits) or "normal", source_id or name])


def _estimation_search_preferences(edata, normalize_name_func):
    counts = {}
    for estimate in (edata or {}).get("estimations", []) or []:
        for card in estimate.get("cards", []) or []:
            if _is_quick_bulk_entry(card):
                continue
            key = _estimation_search_card_key(card, normalize_name_func)
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def _mark_estimation_needs_review(estimate):
    if not isinstance(estimate, dict):
        return
    estimate.pop("ready_for_offer", None)
    estimate.pop("ready_for_offer_at", None)
    if estimate.get("workflow_status") in {"Prête pour offre", "Offre envoyée"}:
        estimate["workflow_status"] = "À analyser"
    if estimate.get("status") in {"Prête pour offre", "Offre envoyée"}:
        estimate["status"] = "À analyser"


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _explicit_seller_price(estimate):
    return _safe_float((estimate or {}).get("seller_price"))


def _seller_price_label(estimate, fp_func):
    seller_price = _explicit_seller_price(estimate)
    return fp_func(seller_price) if seller_price > 0 else "Non renseigné"


def _safe_int(value, default=1):
    try:
        return max(int(value or default), 1)
    except (TypeError, ValueError):
        return default


def _safe_non_negative_int(value, default=0):
    try:
        return max(int(value or default), 0)
    except (TypeError, ValueError):
        return default


def _is_quick_bulk_entry(card):
    return isinstance(card, dict) and card.get("entry_type") == "quick_bulk"


def _quick_bulk_purchase_unit(card):
    return _safe_float(card.get("purchase_unit_price"), QUICK_BULK_PURCHASE_UNIT_PRICE)


def _quick_bulk_resale_unit(card):
    return _safe_float(card.get("resale_unit_price"), QUICK_BULK_RESALE_UNIT_PRICE)


def _quick_bulk_purchase_total(card):
    return _quick_bulk_purchase_unit(card) * _safe_int(card.get("quantity"))


def _quick_bulk_resale_total(card):
    return _quick_bulk_resale_unit(card) * _safe_int(card.get("quantity"))


def _card_weight(card):
    if _is_quick_bulk_entry(card):
        return _quick_bulk_resale_total(card)
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
    cards = [card for card in estimate.get("cards", []) or [] if not _is_quick_bulk_entry(card)]
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


def _regular_cards_value(estimate):
    return sum(_card_weight(card) for card in estimate.get("cards", []) or [] if not _is_quick_bulk_entry(card))


def _estimated_paid_for_card(card, estimate):
    if _is_quick_bulk_entry(card):
        qty = _safe_int(card.get("quantity"))
        total = _quick_bulk_purchase_total(card)
        return total, total / qty if qty else total
    seller_price = _safe_float(estimate.get("seller_price"))
    total_value = _regular_cards_value(estimate)
    if seller_price <= 0 or total_value <= 0:
        return 0.0, 0.0
    qty = _safe_int(card.get("quantity"))
    line_paid = seller_price * (_card_weight(card) / total_value)
    return line_paid, line_paid / qty if qty else line_paid


def _estimation_tracking_status(estimate):
    raw = str((estimate or {}).get("workflow_status") or (estimate or {}).get("status") or "").strip()
    return _LEGACY_STATUS_MAP.get(raw, raw) if raw else "À analyser"


def _card_metadata_tag_set(card, normalize_name_func):
    if _is_quick_bulk_entry(card):
        return set()
    tags = set(str(tag).upper() for tag in (card.get("metadata_tags") or []) if tag)
    text = _card_strict_rarity_text(card, normalize_name_func)
    name_text = f" {normalize_name_func(card.get('name', ''))} "
    for tag in _SPECIAL_VALUE_TAGS:
        requested = {
            "HYPER_RARE": "rainbow",
            "SECRET_RARE": "secret",
        }.get(tag, tag.lower())
        if tag == "AR" and str((card or {}).get("id") or "").strip().lower() in _KNOWN_ART_RARE_CARD_IDS:
            tags.add("AR")
            continue
        if _contains_type(text, requested):
            tags.add(tag)
    if " vmax " in name_text or "vmax" in name_text:
        tags.add("VMAX")
    if " vstar " in name_text or "vstar" in name_text:
        tags.add("VSTAR")
    if "-ex" in name_text or " ex " in name_text:
        tags.add("EX")
    if "-gx" in name_text or " gx " in name_text:
        tags.add("GX")
    if " pokemon v " in name_text or name_text.strip().endswith(" v"):
        tags.add("V")
    number = _normalized_card_number(card)
    if number.startswith("TG"):
        tags.add("TG")
    if number.startswith("GG"):
        tags.add("GG")
    if number.startswith(("SWSH", "SM", "SVP", "MEP")):
        tags.add("PROMO")
    return tags


def _card_is_special_for_analysis(card, normalize_name_func):
    return bool(_card_metadata_tag_set(card, normalize_name_func) & _SPECIAL_VALUE_TAGS)


def _card_is_recent_for_analysis(card):
    text = " ".join(
        str((card or {}).get(key) or "")
        for key in ("set_id", "id", "set", "number")
    ).lower()
    return any(token in text for token in ("sv", "ev", "swsh", "eb", "me", "mew", "svp", "twm", "ssp", "obf", "mep"))


def _card_is_old_for_analysis(card):
    text = " ".join(str((card or {}).get(key) or "") for key in ("set_id", "id", "set")).lower()
    return any(token in text for token in ("base", "jungle", "fossil", "rocket", "neo", "ex", "dp", "hgss", "platinum", "wizards"))


def _card_has_reliable_image(card):
    return _resolve_estimation_card_image(card, log=False).get("source") != "placeholder"


def _card_is_manual_estimation(card):
    return not (card.get("id") or card.get("card_id") or card.get("set_id") or card.get("image_url") or card.get("cached_image_path"))


def _card_condition_is_uncertain(card):
    condition = str((card or {}).get("condition") or "").strip().upper()
    note = str((card or {}).get("note") or "").lower()
    return (
        not condition
        or condition in {"?", "UNKNOWN", "INCERTAIN", "À VÉRIFIER", "A VERIFIER"}
        or any(token in note for token in ("etat", "état", "verifier", "vérifier", "flou", "abim", "abîm"))
    )


def _card_number_is_uncertain(card):
    number = str((card or {}).get("number") or "").strip()
    return not number or number in {"?", "??"} or len(number) <= 1


def _estimation_reliability(estimate, normalize_name_func):
    cards = [card for card in estimate.get("cards", []) or [] if not _is_quick_bulk_entry(card)]
    total_qty = sum(_safe_int(card.get("quantity")) for card in cards)
    if not cards or total_qty <= 0:
        return {
            "score": 0,
            "recognized": 0,
            "total": total_qty,
            "missing_cote": 0,
            "missing_image": 0,
            "manual": 0,
            "uncertain_number": 0,
            "uncertain_condition": 0,
            "missing_tags": 0,
            "lines": ["Aucune carte analysable pour le moment"],
        }
    recognized = sum(1 for card in cards if not _card_is_manual_estimation(card))
    missing_cote = sum(1 for card in cards if _safe_float(card.get("cote")) <= 0)
    missing_image = sum(1 for card in cards if not _card_has_reliable_image(card))
    manual = sum(1 for card in cards if _card_is_manual_estimation(card))
    uncertain_number = sum(1 for card in cards if _card_number_is_uncertain(card))
    uncertain_condition = sum(1 for card in cards if _card_condition_is_uncertain(card))
    missing_tags = sum(1 for card in cards if not _card_metadata_tag_set(card, normalize_name_func))
    line_count = max(len(cards), 1)
    score = 100
    score -= missing_cote / line_count * 25
    score -= missing_image / line_count * 15
    score -= manual / line_count * 18
    score -= uncertain_number / line_count * 14
    score -= uncertain_condition / line_count * 12
    score -= missing_tags / line_count * 8
    score = int(max(0, min(100, round(score))))
    lines = [
        f"{recognized} cartes reconnues sur {len(cards)}",
        f"{missing_cote} cartes sans cote",
        f"{missing_image} cartes sans image",
        f"{manual} cartes ajoutées manuellement",
        f"{uncertain_number} numéros à confirmer",
    ]
    return {
        "score": score,
        "recognized": recognized,
        "total": total_qty,
        "missing_cote": missing_cote,
        "missing_image": missing_image,
        "manual": manual,
        "uncertain_number": uncertain_number,
        "uncertain_condition": uncertain_condition,
        "missing_tags": missing_tags,
        "lines": lines,
    }


def _estimation_analysis(estimate, totals, normalize_name_func):
    cards = [card for card in estimate.get("cards", []) or [] if not _is_quick_bulk_entry(card)]
    line_count = max(len(cards), 1)
    total_value = _safe_float(totals.get("total_cote"))
    seller_price = _explicit_seller_price(estimate)
    margin = _safe_float(totals.get("theoretical_margin"))
    real_pct = _safe_float(totals.get("real_pct"))
    reliability = _estimation_reliability(estimate, normalize_name_func)
    special_count = sum(1 for card in cards if _card_is_special_for_analysis(card, normalize_name_func))
    recent_count = sum(1 for card in cards if _card_is_recent_for_analysis(card))
    old_count = sum(1 for card in cards if _card_is_old_for_analysis(card))
    risky_count = reliability["missing_cote"] + reliability["missing_image"] + reliability["manual"] + reliability["uncertain_condition"]
    top_cards = sorted(cards, key=_card_weight, reverse=True)[:5]
    top_value = sum(_card_weight(card) for card in top_cards[:2])
    concentration = (top_value / total_value * 100) if total_value > 0 else 0.0
    special_ratio = special_count / line_count
    recent_ratio = recent_count / line_count
    old_ratio = old_count / line_count

    score = 50
    factors = []
    if total_value > 0 and seller_price > 0:
        if real_pct <= 55:
            score += 22
            factors.append("+ Prix demandé bas")
        elif real_pct <= 65:
            score += 14
            factors.append("+ Prix demandé raisonnable")
        elif real_pct <= 80:
            score += 4
            factors.append("+ Prix encore comparable à la cote")
        else:
            score -= 18
            factors.append("- Prix demandé élevé")
    else:
        score -= 12
        factors.append("- Prix ou cote à compléter")
    if margin > 0:
        score += min(18, margin / max(total_value, 1) * 28)
        factors.append("+ Marge potentielle positive")
    else:
        score -= 18
        factors.append("- Marge potentielle faible ou négative")
    if reliability["score"] >= 75:
        score += 10
        factors.append("+ Informations plutôt fiables")
    elif reliability["score"] < 55:
        score -= 14
        factors.append(f"- Fiabilité limitée ({reliability['score']} %)")
    if special_ratio >= 0.45:
        score += 8
        factors.append("+ Beaucoup de cartes spéciales")
    if recent_ratio >= 0.55:
        score += 6
        factors.append("+ Lot plutôt récent")
    if old_ratio >= 0.35:
        score -= 8
        factors.append("- Cartes anciennes à contrôler")
    if risky_count:
        score -= min(18, risky_count * 3)
        factors.append(f"- {risky_count} points à vérifier")
    if concentration >= 65:
        score -= 8
        factors.append("- Valeur concentrée sur peu de cartes")
    score = int(max(0, min(100, round(score))))
    if score >= 82:
        verdict = "Très bonne affaire"
    elif score >= 70:
        verdict = "Bonne affaire"
    elif score >= 58:
        verdict = "À négocier"
    elif score >= 45:
        verdict = "Marge faible"
    elif score >= 32:
        verdict = "Trop cher"
    else:
        verdict = "À éviter"

    if recent_ratio >= 0.55 and special_ratio >= 0.35 and reliability["score"] >= 60:
        risk_profile = "récent / cartes spéciales"
        risk_message = "Achat prudent conseillé autour de 55 % de la cote."
        prudent_pct, good_pct, max_pct = 55, 63, 70
    elif old_ratio >= 0.30 or reliability["score"] < 55 or risky_count >= 5:
        risk_profile = "ancien / état variable"
        risk_message = "Attention : prix d'achat à sécuriser davantage."
        prudent_pct, good_pct, max_pct = 45, 52, 58
    else:
        risk_profile = "mixte / à confirmer"
        risk_message = "Analyse correcte, mais garde une marge de sécurité."
        prudent_pct, good_pct, max_pct = 50, 58, 65
    if concentration >= 65:
        prudent_pct -= 3
        good_pct -= 3
        max_pct -= 3
    if reliability["missing_cote"] > 0:
        prudent_pct -= 2
        good_pct -= 2
    prudent_pct = max(30, prudent_pct)
    good_pct = max(prudent_pct, good_pct)
    max_pct = max(good_pct, max_pct)
    prices = {
        "prudent_pct": prudent_pct,
        "good_pct": good_pct,
        "max_pct": max_pct,
        "prudent": total_value * prudent_pct / 100 if total_value else 0.0,
        "good": total_value * good_pct / 100 if total_value else 0.0,
        "max": total_value * max_pct / 100 if total_value else 0.0,
    }
    return {
        "score": score,
        "verdict": verdict,
        "factors": factors[:8],
        "reliability": reliability,
        "risk_profile": risk_profile,
        "risk_message": risk_message,
        "prices": prices,
        "special_ratio": special_ratio,
        "recent_ratio": recent_ratio,
        "old_ratio": old_ratio,
        "concentration": concentration,
        "top_cards": top_cards,
    }


def _card_warning_reasons(card, estimate, total_value, normalize_name_func):
    if _is_quick_bulk_entry(card):
        return []
    reasons = []
    if _safe_float(card.get("cote")) <= 0:
        reasons.append("cote manquante")
    if not _card_has_reliable_image(card):
        reasons.append("image manquante")
    if _card_is_manual_estimation(card):
        reasons.append("carte manuelle")
    if _card_number_is_uncertain(card):
        reasons.append("numéro à confirmer")
    if _card_condition_is_uncertain(card):
        reasons.append("état à confirmer")
    if _card_is_old_for_analysis(card):
        reasons.append("carte ancienne")
    if _card_is_japanese(card) and not _exact_cardmarket_url(card):
        reasons.append("japonaise sans lien exact")
    if total_value > 0 and _card_weight(card) / total_value >= 0.35:
        reasons.append("grosse part de la valeur")
    return reasons


def _cards_to_verify(estimate, normalize_name_func, limit=8):
    cards = [card for card in estimate.get("cards", []) or [] if not _is_quick_bulk_entry(card)]
    total_value = _all_cards_value(estimate)
    rows = []
    for card in cards:
        reasons = _card_warning_reasons(card, estimate, total_value, normalize_name_func)
        if reasons:
            rows.append((card, reasons))
    rows.sort(key=lambda item: (_card_weight(item[0]), len(item[1])), reverse=True)
    return rows[:limit]


def _priority_resale_cards(estimate, normalize_name_func, limit=5):
    cards = [card for card in estimate.get("cards", []) or [] if not _is_quick_bulk_entry(card)]
    scored = []
    for card in cards:
        score = _card_weight(card)
        if _card_is_special_for_analysis(card, normalize_name_func):
            score += 35
        if _card_is_recent_for_analysis(card):
            score += 15
        if _card_has_reliable_image(card):
            score += 8
        if card.get("set") and card.get("number") and _safe_float(card.get("cote")) > 0:
            score += 10
        scored.append((score, card))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [card for _, card in scored[:limit]]


def _duplicate_signature(card, normalize_name_func):
    special_text = " ".join(
        str(value or "")
        for value in [
            card.get("special"),
            card.get("special_tag"),
            card.get("rarity"),
            " ".join(str(tag) for tag in card.get("metadata_tags", []) or []),
            " ".join(str(tag) for tag in card.get("tags", []) or []),
        ]
    )
    number = str(card.get("number") or "").strip().upper().replace(" ", "")
    number = number.split("/", 1)[0].lstrip("0") or number
    return (
        normalize_name_func(card.get("name", "")),
        number,
        normalize_name_func(card.get("set") or card.get("set_id") or ""),
        normalize_name_func(card.get("lang") or card.get("language") or ""),
        normalize_name_func(special_text),
        bool(card.get("is_reverse")),
        bool(card.get("is_ed1")),
        bool(card.get("promo")),
        normalize_name_func(card.get("condition") or "NM"),
    )


def _find_duplicate_card(estimate, candidate, normalize_name_func):
    candidate_signature = _duplicate_signature(candidate, normalize_name_func)
    if not candidate_signature[0]:
        return None
    for card in estimate.get("cards", []) or []:
        if _duplicate_signature(card, normalize_name_func) == candidate_signature:
            return card
    return None


def _pending_duplicate_key(uid):
    return f"est_duplicate_pending_{uid}"


def _store_duplicate_pending(uid, duplicate, payload):
    payload["duplicate_uid"] = duplicate.get("uid")
    payload["duplicate_title"] = _card_title(duplicate)
    st.session_state[_pending_duplicate_key(uid)] = payload


def _mark_price_verified_manually(card):
    if _safe_float((card or {}).get("cote")) <= 0:
        return False
    card["market_price_origin"] = "verified_manually"
    card["price_status"] = "verified"
    card["price_source"] = card.get("market_price_source") or card.get("price_source") or "estimation_manual_check"
    card["price_value"] = _safe_float(card.get("cote"))
    card["price_last_verified_at"] = datetime.now().isoformat()
    card["price_verification_method"] = "manual_readd"
    return True


def _add_estimation_card_from_payload(estimate, payload, add_estimation_card_func):
    params = payload.get("params", {})
    before_count = len(estimate.get("cards", []) or [])
    add_estimation_card_func(
        estimate,
        params.get("name", ""),
        params.get("number", ""),
        params.get("cote", "0,00"),
        params.get("qty", "1"),
        params.get("condition", "NM"),
        params.get("specials", []),
        params.get("note", ""),
        params.get("is_collection", False),
        payload.get("match"),
    )
    _apply_selected_card_details(estimate, payload.get("details"))
    return len(estimate.get("cards", []) or []) > before_count


def _render_duplicate_pending(uid, estimate, edata, save_estimations_func, add_estimation_card_func, pending_reset_key):
    pending = st.session_state.get(_pending_duplicate_key(uid))
    if not pending:
        return
    st.warning(f"Cette carte est déjà présente dans cette estimation : {pending.get('duplicate_title', 'carte existante')}.")
    c1, c2, c3 = st.columns(3)
    qty_to_add = _safe_int((pending.get("params") or {}).get("qty"))
    if c1.button("Ajouter à la quantité existante", key=f"est_dup_merge_{uid}", width="stretch"):
        _mark_estimation_needs_review(estimate)
        for card in estimate.get("cards", []) or []:
            if card.get("uid") == pending.get("duplicate_uid"):
                old_qty = _safe_int(card.get("quantity"))
                card["quantity"] = old_qty + qty_to_add
                _mark_price_verified_manually(card)
                print(
                    f'[Estimations Duplicate] card="{card.get("name", "Carte")}" action=merge old_qty={old_qty} new_qty={card["quantity"]}',
                    flush=True,
                )
                break
        save_estimations_func(edata)
        st.session_state.pop(_pending_duplicate_key(uid), None)
        st.session_state[pending_reset_key] = True
        st.rerun()
    if c2.button("Créer une entrée séparée", key=f"est_dup_separate_{uid}", width="stretch"):
        _mark_estimation_needs_review(estimate)
        added = _add_estimation_card_from_payload(estimate, pending, add_estimation_card_func)
        save_estimations_func(edata)
        st.session_state.pop(_pending_duplicate_key(uid), None)
        if added:
            st.session_state[pending_reset_key] = True
        st.rerun()
    if c3.button("Annuler", key=f"est_dup_cancel_{uid}", width="stretch"):
        st.session_state.pop(_pending_duplicate_key(uid), None)
        st.rerun()


def _parse_bulk_line(line):
    raw = str(line or "").strip()
    if not raw:
        return None
    qty = 1
    qty_match = re.search(r"(?:^|\s)x\s*(\d+)\s*$", raw, re.IGNORECASE)
    if qty_match:
        qty = max(int(qty_match.group(1)), 1)
        raw = raw[: qty_match.start()].strip()
    else:
        trailing_qty = re.search(r"\s+(\d{1,2})\s*$", raw)
        if trailing_qty and len(raw[: trailing_qty.start()].strip().split()) >= 2:
            qty = max(int(trailing_qty.group(1)), 1)
            raw = raw[: trailing_qty.start()].strip()
    tokens = raw.split()
    number = ""
    if tokens:
        last = tokens[-1]
        if any(ch.isdigit() for ch in last) and len(tokens) > 1:
            number = last
            tokens = tokens[:-1]
    name = " ".join(tokens).strip() or raw
    return {"raw": line, "name": name, "number": number, "qty": qty}


def _bulk_preview_key(uid):
    return f"est_bulk_preview_{uid}"


def _render_checklist_section(uid, estimate, edata, save_estimations_func):
    current = estimate.get("purchase_checklist") or {}
    done = sum(1 for item in _DEFAULT_CHECKLIST_ITEMS if bool(current.get(item)))
    with st.expander(f"Checklist avant achat · {done} / {len(_DEFAULT_CHECKLIST_ITEMS)} terminée", expanded=False):
        with st.form(f"est_checklist_form_{uid}"):
            values = {}
            for item in _DEFAULT_CHECKLIST_ITEMS:
                values[item] = st.checkbox(item, value=bool(current.get(item)), key=f"est_check_{uid}_{_safe_image_filename({'uid': uid}, item)}")
            if st.form_submit_button("Sauvegarder la checklist", width="stretch"):
                estimate["purchase_checklist"] = values
                save_estimations_func(edata)
                print(f'[Estimations Checklist] estimate="{estimate.get("name", "Estimation")}" done={sum(1 for v in values.values() if v)}', flush=True)
                st.rerun()


def _render_negotiation_history_section(uid, estimate, edata, save_estimations_func, parse_float_input_func, fp_func):
    history = list(estimate.get("negotiation_history") or [])
    with st.expander(f"Historique de négociation · {len(history)} événement(s)", expanded=False):
        if history:
            for idx, event in enumerate(history):
                c1, c2 = st.columns([5, 1])
                amount = _safe_float(event.get("amount"))
                amount_text = f" — {fp_func(amount)}" if amount > 0 else ""
                c1.markdown(f"**{html.escape(str(event.get('date', '')))} — {html.escape(str(event.get('type', 'Note')))}{amount_text}**  \n{html.escape(str(event.get('note', '')))}")
                if c2.button("Supprimer", key=f"est_hist_delete_{uid}_{idx}", width="stretch"):
                    estimate["negotiation_history"] = [item for j, item in enumerate(history) if j != idx]
                    save_estimations_func(edata)
                    print(f'[Estimations Negotiation] estimate="{estimate.get("name", "Estimation")}" action=delete index={idx}', flush=True)
                    st.rerun()
        with st.form(f"est_history_form_{uid}"):
            h1, h2 = st.columns([1, 1])
            event_type = h1.selectbox(
                "Type",
                ["Prix demandé initial", "Offre envoyée", "Contre-offre", "Offre finale", "Réduction annoncée", "Message reçu", "Décision", "Note libre"],
                key=f"est_hist_type_{uid}",
            )
            amount_raw = h2.text_input("Montant optionnel (€)", value="", key=f"est_hist_amount_{uid}")
            note = st.text_input("Note optionnelle", key=f"est_hist_note_{uid}")
            if st.form_submit_button("Ajouter à l'historique", width="stretch"):
                event = {
                    "uid": uuid.uuid4().hex,
                    "date": datetime.now().isoformat()[:10],
                    "type": event_type,
                    "amount": parse_float_input_func(amount_raw, 0.0) if str(amount_raw or "").strip() else 0.0,
                    "note": note.strip(),
                }
                estimate.setdefault("negotiation_history", []).append(event)
                save_estimations_func(edata)
                print(f'[Estimations Negotiation] estimate="{estimate.get("name", "Estimation")}" action=add type="{event_type}"', flush=True)
                st.rerun()


def _render_bulk_add_section(
    uid,
    estimate,
    edata,
    save_estimations_func,
    add_estimation_card_func,
    search_in_cache_func,
    ecd_func,
    normalize_name_func,
    pending_reset_key,
):
    with st.expander("Ajout en masse", expanded=False):
        raw_list = st.text_area(
            "Liste à analyser",
            placeholder="Démolosse 066 x1\nPikachu TG05 x2\nDracaufeu 199 x1",
            key=f"est_bulk_text_{uid}",
            height=130,
        )
        if st.button("Analyser la liste", key=f"est_bulk_analyze_{uid}", width="stretch"):
            preview = []
            for line in raw_list.splitlines():
                parsed = _parse_bulk_line(line)
                if not parsed:
                    continue
                suggestions = _card_suggestions(parsed["name"], parsed["number"], search_in_cache_func, ecd_func, normalize_name_func, limit=5)
                preview.append({**parsed, "suggestions": suggestions})
            st.session_state[_bulk_preview_key(uid)] = preview
            _log_once("bulk_parse", f"{uid}|{len(preview)}", f'[Estimations Bulk] estimate="{estimate.get("name", "")}" parsed={len(preview)}')
            st.rerun()
        preview = st.session_state.get(_bulk_preview_key(uid)) or []
        if not preview:
            st.caption("Colle une liste puis lance l'analyse. Aucune donnée n'est ajoutée à cette étape.")
            return
        valid_count = 0
        selected_payloads = []
        for idx, item in enumerate(preview):
            suggestions = item.get("suggestions") or []
            st.markdown(f"**{html.escape(str(item.get('raw', '')))}**")
            if not suggestions:
                st.caption("Non reconnue")
                continue
            options = []
            for suggestion in suggestions:
                card = suggestion.get("card", {})
                options.append(f"{card.get('name', 'Carte')} #{card.get('number', '')} · {card.get('set', '')}")
            selected_label = st.selectbox("Suggestion", options, key=f"est_bulk_choice_{uid}_{idx}")
            selected_index = options.index(selected_label)
            chosen = suggestions[selected_index]
            details = _selected_card_details(chosen.get("card", {}))
            selected_payloads.append(
                {
                    "params": {
                        "name": details.get("name") or item.get("name"),
                        "number": details.get("number") or item.get("number"),
                        "cote": "0,00",
                        "qty": str(item.get("qty") or 1),
                        "condition": "NM",
                        "specials": [],
                        "note": f"Ajout en masse : {item.get('raw', '')}",
                        "is_collection": False,
                    },
                    "details": details,
                    "match": chosen.get("match"),
                }
            )
            valid_count += 1
        st.caption(f"{valid_count} ligne(s) prêtes à ajouter. Les lignes sans suggestion sont ignorées.")
        if st.button("Ajouter les cartes validées", key=f"est_bulk_add_{uid}", width="stretch"):
            added = 0
            merged = 0
            skipped = 0
            for payload in selected_payloads:
                candidate = {**(payload.get("details") or {}), "condition": "NM"}
                duplicate = _find_duplicate_card(estimate, candidate, normalize_name_func)
                if duplicate:
                    duplicate["quantity"] = _safe_int(duplicate.get("quantity")) + _safe_int((payload.get("params") or {}).get("qty"))
                    merged += 1
                    continue
                if _add_estimation_card_from_payload(estimate, payload, add_estimation_card_func):
                    added += 1
                else:
                    skipped += 1
            save_estimations_func(edata)
            st.session_state.pop(_bulk_preview_key(uid), None)
            if added or merged:
                st.session_state[pending_reset_key] = True
            print(
                f'[Estimations Bulk Add] estimate="{estimate.get("name", "Estimation")}" added={added} merged={merged} skipped={skipped}',
                flush=True,
            )
            st.rerun()


def _log_once(namespace, signature, message):
    if not ESTIMATIONS_DEBUG:
        return
    key = f"{namespace}|{signature}"
    if key in _ESTIMATION_LOG_SIGNATURES:
        return
    _ESTIMATION_LOG_SIGNATURES.add(key)
    print(message, flush=True)


def _perf_log_once(namespace, signature, message):
    if not ESTIMATIONS_PERF_DEBUG:
        return
    key = f"perf|{namespace}|{signature}"
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


def _is_streamlit_temp_image_source(value):
    text = _clean_image_value(value)
    if not text:
        return False
    lower = text.lower().replace("\\", "/")
    parsed = urlsplit(text)
    path = (parsed.path or lower).lower()
    host = (parsed.netloc or "").lower()
    return (
        "/_stcore/" in path
        or path.startswith("/media/")
        or "/media/" in path
        or "mediafilehandler" in lower
        or "streamlit" in host and "/media/" in path
        or host.startswith(("localhost", "127.0.0.1", "0.0.0.0")) and "/media/" in path
    )


def _normalize_image_source(value):
    text = _clean_image_value(value)
    if not text:
        return ""
    if _is_streamlit_temp_image_source(text):
        return ""
    lower = text.lower()
    if lower.startswith(("http://", "https://")):
        parsed = urlsplit(text)
        if not parsed.scheme or not parsed.netloc:
            return ""
        if "tcgdex.net" in lower and not lower.endswith(_IMAGE_EXTENSIONS):
            return f"{text.rstrip('/')}/high.webp"
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


def _estimation_image_cache_dir():
    folder = os.path.join(os.getcwd(), "images", "estimation_cache")
    os.makedirs(folder, exist_ok=True)
    return folder


def _cache_image_filename(card, url):
    seed = "_".join(
        str(card.get(key, "") or "")
        for key in ("id", "card_id", "name", "number", "set_id")
    )
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", seed).strip("_") or uuid.uuid4().hex
    ext = os.path.splitext(urlsplit(str(url or "")).path)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".webp"
    return f"{safe[:90]}{ext}"


def _download_estimation_image(card, sources):
    for source in sources or []:
        url = _normalize_image_source(source)
        if not url or not url.startswith(("http://", "https://")):
            continue
        try:
            import requests

            response = requests.get(url, timeout=8)
            response.raise_for_status()
            content_type = str(response.headers.get("content-type") or "").lower()
            if "image" not in content_type and not url.lower().endswith(_IMAGE_EXTENSIONS):
                continue
            if len(response.content or b"") < 512:
                continue
            folder = _estimation_image_cache_dir()
            path = os.path.join(folder, _cache_image_filename(card, url))
            with open(path, "wb") as image_file:
                image_file.write(response.content)
            return os.path.relpath(path, os.getcwd()).replace("\\", "/")
        except Exception:
            continue
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
    for key in ("metadata_tags", "tags", "card_tags", "subtypes", "types"):
        raw_tags = card.get(key) or []
        if isinstance(raw_tags, (list, tuple, set)):
            explicit_parts.extend(str(tag) for tag in raw_tags)
        elif raw_tags:
            explicit_parts.append(str(raw_tags))
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


def _fold_text(value):
    text = str(value or "").strip().lower()
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return text


def _cached_normalizer(normalize_name_func):
    key = id(normalize_name_func)
    cache = _ESTIMATION_NORMALIZER_CACHE.setdefault(key, {})

    def normalize(value):
        text = str(value or "")
        if text in cache:
            return cache[text]
        result = normalize_name_func(text)
        if len(cache) >= _ESTIMATION_NORMALIZER_CACHE_MAX:
            cache.clear()
        cache[text] = result
        return result

    return normalize


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


def is_pokemon_pocket_card(card):
    card = card or {}
    set_name = str(card.get("set") or card.get("set_name") or "").strip().lower()
    set_id = str(card.get("set_id") or "").strip().lower()
    card_id = str(card.get("id") or card.get("card_id") or "").strip().lower()
    image_blob = " ".join(str(card.get(key) or "") for key in ("image", "image_url", "image_url_en", "image_url_ja", "imageUrl"))
    metadata_blob = " ".join(_flatten_metadata({key: card.get(key) for key in ("game", "product", "source", "series", "category", "tcg", "tags", "metadata", "set", "set_id", "set_name", "format", "type")}))
    explicit_blob = f" {_fold_text(set_name)} {_fold_text(set_id)} {_fold_text(card_id)} {_fold_text(image_blob)} {_fold_text(metadata_blob)} "
    pocket_set_names = {
        "puissance genetique",
        "puissance genetique",
        "ile fabuleuse",
        "choc spatio-temporel",
        "choc spatio temporel",
        "lumiere triomphale",
        "gardiens astraux",
        "crise extra-dimensionnelle",
        "crise extra dimensionnelle",
        "sagesse entre ciel et mer",
    }
    folded_set_name = _fold_text(set_name)
    pocket_id_match = bool(re.match(r"^(a|pa)\d+[a-z]?[-_]", card_id) or re.match(r"^(a|pa)\d+[a-z]?$", set_id))
    return (
        "/tcgp/" in explicit_blob
        or "tcg pocket" in explicit_blob
        or "pokemon trading card game pocket" in explicit_blob
        or "ptcgp" in explicit_blob
        or " tcgp " in explicit_blob
        or (pocket_id_match and (folded_set_name in pocket_set_names or set_id.startswith(("a", "pa"))))
    )


def is_physical_pokemon_tcg_card(card):
    return not is_pokemon_pocket_card(card or {})


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


def _normalized_card_metadata_tags(card, normalize_name_func):
    text = f" {normalize_name_func(' '.join(str(value or '') for value in _metadata_values_for_tags(card)))} "
    tag_rules = {
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
    for tag, needles in tag_rules.items():
        if any(needle in text for needle in needles):
            tags.append(tag)
    number = _normalized_card_number(card)
    if number.startswith("TG"):
        tags.append("TG")
    if number.startswith("GG"):
        tags.append("GG")
    if number.startswith(("SWSH", "SM", "SVP", "MEP")):
        tags.append("PROMO")
    seen = set()
    result = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _cardmarket_min_condition(condition):
    condition_key = str(condition or "").strip().lower().replace(" ", "")
    # Confirmed from the user's Cardmarket URL example: NM -> minCondition=2.
    # Other Pokestock condition labels are left unmapped until confirmed.
    if condition_key in {"nm", "nearmint"}:
        return "2"
    return ""


def _append_cardmarket_filters(url, condition, language=_CARDMARKET_LANGUAGE_FR):
    url = str(url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if language:
        query["language"] = str(language)
    min_condition = _cardmarket_min_condition(condition)
    if min_condition:
        query["minCondition"] = min_condition
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
    language_code = _CARDMARKET_LANGUAGE_JA if is_japanese else _CARDMARKET_LANGUAGE_FR
    language_label = "ja" if is_japanese else "fr"
    nm_flag = "yes" if _cardmarket_min_condition(condition) else "no"
    exact_url = _exact_cardmarket_url(card)
    if exact_url:
        final_url = _append_cardmarket_filters(exact_url, condition, language=language_code)
        _log_once(
            "cardmarket_link",
            f"exact|{card.get('uid','')}|{final_url}",
            f'[Cardmarket Link] language={language_label} type=exact card="{card.get("name", "")}" '
            f'name="{card.get("name", "")}" number="{card.get("number", "")}" '
            f'nm={nm_flag} url="{final_url}"',
        )
        return final_url

    number = str((card or {}).get("number") or "").strip()
    set_hint = str((card or {}).get("set_id") or (card or {}).get("set") or "").strip()
    special_hint = ", ".join(_estimation_card_specials(card))
    if is_japanese:
        jp_context = " ".join(x for x in ["JP", set_hint, special_hint] if x).strip()
        query_name = " ".join(x for x in [card.get("name", ""), jp_context] if x).strip()
        search_url = cardmarket_search_url_func(query_name, number, "", "")
        final_url = _append_cardmarket_filters(search_url, condition, language=language_code)
        link_type = "japanese_search" if jp_context else "generic_fallback"
        reason = "" if jp_context else ' reason="insufficient_japanese_metadata"'
        _log_once(
            "cardmarket_link",
            f"jp_search|{card.get('uid','')}|{final_url}",
            f'[Cardmarket Link] language=ja type=search card="{card.get("name", "")}" '
            f'set="{set_hint}" number="{number}" nm={nm_flag} url="{final_url}"{reason}',
        )
        return final_url

    query = _cardmarket_search_query(card)
    search_url = cardmarket_search_url_func(card.get("name", ""), number, "", "")
    final_url = _append_cardmarket_filters(search_url, condition, language=language_code)
    _log_once(
        "cardmarket_link",
        f"search|{card.get('uid','')}|{final_url}",
        '[Cardmarket Link] language=fr type=search '
        f'card="{card.get("name", "")}" query="{query}" extension_excluded=yes nm={nm_flag} url="{final_url}"',
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
        "image_fallbacks": image_info.get("fallbacks", []),
    }
    for key in (
        "image_url_ja",
        "image_url_jp",
        "image_url_japanese",
        "lang",
        "language",
        "special",
        "special_tag",
        "tags",
        "card_tags",
        "subtypes",
        "types",
        "variants",
        "promo",
        "is_reverse",
        "is_ed1",
    ):
        if enriched.get(key):
            details[key] = enriched.get(key)
    metadata_tags = _normalized_card_metadata_tags(enriched, _fold_text)
    if metadata_tags:
        details["metadata_tags"] = metadata_tags
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
        "cached_image_path",
        "lang",
        "language",
        "special",
        "special_tag",
        "tags",
        "card_tags",
        "metadata_tags",
        "subtypes",
        "types",
        "variants",
        "promo",
        "is_reverse",
        "is_ed1",
        "cardmarket_url",
        "cardmarket_link",
        "market_url",
        "cardmarket_product_url",
        "product_url",
    ):
        if details.get(key):
            card[key] = details[key]
    if not card.get("manual_image_path") and not card.get("cached_image_path"):
        cached_path = _download_estimation_image(
            card,
            [
                details.get("image_url"),
                details.get("image_url_ja"),
                details.get("image_url_jp"),
                details.get("image_url_japanese"),
                details.get("image_url_en"),
                *(details.get("image_fallbacks") or []),
            ],
        )
        if cached_path:
            card["cached_image_path"] = cached_path


def _estimation_image_html(url, url_en="", *, style="", placeholder_class="est-card-placeholder compact", fallbacks=None, proxy_img_func=None):
    raw_sources = [url, url_en, *(fallbacks or [])]
    sources = []
    proxy = proxy_img_func if callable(proxy_img_func) else (lambda value: value)
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
        f'<img src="{src}" loading="lazy" decoding="async" onerror="{html.escape(onerror, quote=True)}" style="width:100%;{html.escape(style, quote=True)}">'
        f'<div class="{placeholder_class}" style="display:none;">Image indisponible</div>'
        "</div>"
    )


def _suggestion_thumbnail_url(url):
    resolved = _normalize_image_source(url)
    if not resolved:
        return ""
    if "assets.tcgdex.net" in resolved and resolved.endswith("/high.webp"):
        return resolved[:-9] + "low.webp"
    return resolved


def _suggestion_image_cache_key(card):
    card = card or {}
    return "|".join(
        [
            _card_language(card, default="fr"),
            str(card.get("id") or card.get("card_id") or ""),
            str(card.get("set_id") or ""),
            str(card.get("number") or card.get("localId") or ""),
            str(card.get("image_url") or ""),
            str(card.get("image_url_ja") or ""),
        ]
    )


def _suggestion_image_info(card):
    key = _suggestion_image_cache_key(card)
    if key in _ESTIMATION_SUGGESTION_IMAGE_CACHE:
        cached = dict(_ESTIMATION_SUGGESTION_IMAGE_CACHE[key])
        cached["cache_hit"] = True
        return cached

    lang = _card_language(card, default="fr")
    fields = _fast_index_image_fields(card, card.get("number") or card.get("localId"), lang)
    sources = []
    for value in (
        fields.get("image_url_ja") if lang == "ja" else "",
        fields.get("image_url"),
        fields.get("image_url_en"),
    ):
        thumb = _suggestion_thumbnail_url(value)
        if thumb and thumb not in sources:
            sources.append(thumb)
    result = {
        "url": sources[0] if sources else "",
        "fallbacks": sources[1:],
        "source": "thumbnail" if sources else "placeholder",
        "cache_hit": False,
    }
    if len(_ESTIMATION_SUGGESTION_IMAGE_CACHE) >= _ESTIMATION_SUGGESTION_IMAGE_CACHE_MAX:
        _ESTIMATION_SUGGESTION_IMAGE_CACHE.pop(next(iter(_ESTIMATION_SUGGESTION_IMAGE_CACHE)))
    _ESTIMATION_SUGGESTION_IMAGE_CACHE[key] = dict(result)
    return result


def _split_alpha_numeric_token(token):
    token = str(token or "").strip().lower()
    if not token:
        return "", ""
    letters = "".join(ch for ch in token if ch.isalpha())
    digits = "".join(ch for ch in token if ch.isdigit())
    if letters and digits and token == f"{letters}{digits}":
        return letters, digits
    return "", ""


def _extract_shiny_filter(normalized_query, normalize_name_func):
    query = f" {normalized_query} "
    found = False
    aliases = sorted(
        {normalize_name_func(alias) for alias in _SHINY_QUERY_ALIASES if str(alias or "").strip()},
        key=len,
        reverse=True,
    )
    for alias in aliases:
        if not alias:
            continue
        pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
        if re.search(pattern, query):
            found = True
            query = re.sub(pattern, " ", query)
    query = re.sub(r"\s+", " ", query).strip()
    return query, found


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


def _shiny_filter_requested(set_tags):
    return bool(set(set_tags or []) & _SHINY_FILTER_TAGS)


def _number_matches(card_number, requested_number):
    requested = str(requested_number or "").strip().upper().replace(" ", "")
    if not requested:
        return True
    card_value = str(card_number or "").strip().upper().replace(" ", "")
    if not card_value:
        return False
    card_primary = card_value.split("/", 1)[0]
    requested_primary = requested.split("/", 1)[0]
    card_digits = "".join(ch for ch in card_value if ch.isdigit())
    req_digits = "".join(ch for ch in requested if ch.isdigit())
    card_primary_digits = "".join(ch for ch in card_primary if ch.isdigit())
    req_primary_digits = "".join(ch for ch in requested_primary if ch.isdigit())
    return (
        card_value == requested
        or card_value.startswith(requested)
        or (req_primary_digits and card_primary_digits.lstrip("0") == req_primary_digits.lstrip("0"))
        or (req_primary_digits and card_primary_digits.zfill(3) == req_primary_digits.zfill(3))
        or (req_digits and card_digits == req_digits)
    )


def _query_parts(query, normalize_name_func, known_set_tags=None):
    raw = str(query or "").strip()
    normalized = normalize_name_func(raw)
    normalized, shiny_filter = _extract_shiny_filter(normalized, normalize_name_func)
    tokens = [token for token in normalized.replace("/", " ").split() if token]
    known_set_tags = set(known_set_tags or [])
    number = ""
    keywords = []
    requested_types = []
    requested_set_tags = ["shiny"] if shiny_filter else []
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
            elif "/" not in raw:
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
    if str((enriched or {}).get("id") or "").strip().lower() in _KNOWN_ART_RARE_CARD_IDS:
        strength = max(strength, 70)
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
    tag_values = []
    for key in ("tags", "card_tags", "metadata_tags", "subtypes", "types"):
        tags = enriched.get(key) or []
        if isinstance(tags, (list, tuple, set)):
            tag_values.extend(str(tag) for tag in tags)
        else:
            tag_values.append(str(tags or ""))
    variants = enriched.get("variants") or {}
    if isinstance(variants, dict):
        tag_values.extend(str(key) for key, enabled in variants.items() if enabled)
    tags_text = " ".join(tag_values)
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
    card_id = str((enriched or {}).get("id") or (enriched or {}).get("card_id") or "").strip().lower()
    if requested_type == "ar":
        if card_id in _KNOWN_ART_RARE_CARD_IDS:
            return True
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


def _fast_index_image_fields(card, number, lang):
    card = card or {}
    lang = "ja" if str(lang or "").lower() in {"ja", "jp", "jpn"} else "fr"

    def pick(*keys):
        for key in keys:
            value = _normalize_image_source(card.get(key))
            if value:
                return value
        return ""

    image_url_ja = ""
    if lang == "ja":
        image_url_ja = pick("image_url_ja", "image_url_jp", "image_url_japanese", "image_ja", "image_jp")

    image_url = pick(
        "manual_image_path",
        "cached_image_path",
        "local_image",
        "image_path",
        "photo_path",
        "image_url",
        "image",
        "imageUrl",
    )
    image_url_en = pick("image_url_en")

    images = card.get("images", {})
    if isinstance(images, dict):
        image_url = image_url or _normalize_image_source(images.get("large")) or _normalize_image_source(images.get("small"))

    card_id = card.get("card_id") or card.get("id")
    if lang == "ja" and not image_url_ja:
        image_url_ja = _tcgdex_image_from_id(card_id, number, lang="ja")
    if not image_url:
        image_url = image_url_ja if lang == "ja" else _tcgdex_image_from_id(card_id, number, lang="fr")
    if lang != "ja" and not image_url_en:
        image_url_en = _tcgdex_image_from_id(card_id, number, lang="en")

    return {"image_url": image_url, "image_url_en": image_url_en, "image_url_ja": image_url_ja}


def _estimation_image_cache_key(card):
    card = card or {}
    parts = [_card_language(card, default="fr"), str(card.get("id") or card.get("card_id") or ""), str(card.get("number") or card.get("localId") or "")]
    for key in _ESTIMATION_IMAGE_FIELDS:
        parts.append(str(card.get(key) or ""))
    return "|".join(parts)


def _resolve_estimation_card_image(card, *, log=True):
    card = card or {}
    cache_key = _estimation_image_cache_key(card)
    if cache_key in _ESTIMATION_IMAGE_RESOLUTION_CACHE:
        return dict(_ESTIMATION_IMAGE_RESOLUTION_CACHE[cache_key])
    started_at = time.perf_counter()
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
        result = {"url": resolved, "url_en": "", "fallbacks": fallbacks, "source": source}
        if len(_ESTIMATION_IMAGE_RESOLUTION_CACHE) >= _ESTIMATION_IMAGE_RESOLUTION_CACHE_MAX:
            _ESTIMATION_IMAGE_RESOLUTION_CACHE.pop(next(iter(_ESTIMATION_IMAGE_RESOLUTION_CACHE)))
        _ESTIMATION_IMAGE_RESOLUTION_CACHE[cache_key] = dict(result)
        if log:
            _log_once(
                "estimation_image",
                f'{card.get("id","")}|{card.get("number","")}|{source}|{resolved}',
                f'[Estimations Image] card="{card.get("name", "Carte")}" '
                f'lang="{"ja" if is_japanese else "fr"}" source={source} valid=yes',
            )
            _perf_log_once(
                "image",
                f'{card.get("id","")}|{card.get("number","")}|{source}',
                f'[Estimations Perf] image card="{card.get("name", "Carte")}" source={source} elapsed_ms={int((time.perf_counter() - started_at) * 1000)}',
            )
        return result

    card_id = card.get("card_id") or card.get("id")
    number = card.get("number") or card.get("localId")
    rebuilt_candidates = []
    for lang in (["ja", "fr", "en"] if is_japanese else ["fr", "en"]):
        for candidate in _tcgdex_image_candidates_from_id(card_id, number, lang=lang):
            if candidate not in rebuilt_candidates:
                rebuilt_candidates.append(candidate)
    if rebuilt_candidates:
        result = {"url": rebuilt_candidates[0], "url_en": "", "fallbacks": rebuilt_candidates[1:], "source": "tcgdex_rebuilt"}
        if len(_ESTIMATION_IMAGE_RESOLUTION_CACHE) >= _ESTIMATION_IMAGE_RESOLUTION_CACHE_MAX:
            _ESTIMATION_IMAGE_RESOLUTION_CACHE.pop(next(iter(_ESTIMATION_IMAGE_RESOLUTION_CACHE)))
        _ESTIMATION_IMAGE_RESOLUTION_CACHE[cache_key] = dict(result)
        if log:
            _log_once(
                "estimation_image",
                f'{card_id}|{number}|tcgdex_rebuilt',
                f'[Estimations Image] card="{card.get("name", "Carte")}" source=tcgdex_rebuilt valid=yes',
            )
            _perf_log_once(
                "image",
                f'{card_id}|{number}|tcgdex_rebuilt',
                f'[Estimations Perf] image card="{card.get("name", "Carte")}" source=tcgdex_rebuilt elapsed_ms={int((time.perf_counter() - started_at) * 1000)}',
            )
        return result

    result = {"url": "", "url_en": "", "fallbacks": [], "source": "placeholder"}
    if len(_ESTIMATION_IMAGE_RESOLUTION_CACHE) >= _ESTIMATION_IMAGE_RESOLUTION_CACHE_MAX:
        _ESTIMATION_IMAGE_RESOLUTION_CACHE.pop(next(iter(_ESTIMATION_IMAGE_RESOLUTION_CACHE)))
    _ESTIMATION_IMAGE_RESOLUTION_CACHE[cache_key] = dict(result)
    if log:
        _log_once(
            "estimation_image",
            f'{card.get("name","Carte")}|{card.get("number","")}|placeholder',
            f'[Estimations Image] card="{card.get("name", "Carte")}" source=placeholder reason=no_valid_image',
        )
        _perf_log_once(
            "image",
            f'{card.get("name","Carte")}|{card.get("number","")}|placeholder',
            f'[Estimations Perf] image card="{card.get("name", "Carte")}" source=placeholder elapsed_ms={int((time.perf_counter() - started_at) * 1000)}',
        )
    return result


_ESTIMATION_IMAGE_FIELDS = (
    "manual_image_path",
    "manual_image_url",
    "local_image",
    "image_path",
    "photo_path",
    "cached_image_path",
    "resolved_collection_image_url",
    "image_url_ja",
    "image_url_jp",
    "image_url_japanese",
    "image_ja",
    "image_jp",
    "image_url",
    "image_url_en",
    "image",
    "imageUrl",
)


def _invalid_estimation_image_refs(card):
    invalid = []
    for key in _ESTIMATION_IMAGE_FIELDS:
        value = (card or {}).get(key)
        if not _clean_image_value(value):
            continue
        if _is_streamlit_temp_image_source(value) or not _normalize_image_source(value):
            invalid.append(key)
    return invalid


def _drop_invalid_estimation_image_refs(card):
    invalid = _invalid_estimation_image_refs(card)
    for key in invalid:
        card.pop(key, None)
    return invalid


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
    if "paldean fates" in set_name_norm or "destinees de paldea" in set_name_norm:
        tags.update({"paf", "shiny"})
    if "shining fates" in set_name_norm or "shiny fates" in set_name_norm or "destinees radieuses" in set_name_norm:
        tags.add("shiny")
    return sorted(tag for tag in tags if tag)


def _search_index_source_id(cards_index):
    if not isinstance(cards_index, dict):
        return None
    total = 0
    for cards in cards_index.values():
        if isinstance(cards, (list, tuple)):
            total += len(cards)
    return (id(cards_index), len(cards_index), total)


def _jp_aliases_from_summary(card):
    aliases = []
    if not isinstance(card, dict):
        return aliases
    for key in (
        "name_en",
        "name_fr",
        "english_name",
        "french_name",
        "nameEn",
        "nameFr",
        "en_name",
        "fr_name",
    ):
        value = str(card.get(key) or "").strip()
        if value and value not in aliases:
            aliases.append(value)
    translations = card.get("translations") or card.get("names") or {}
    if isinstance(translations, dict):
        for key in ("en", "fr", "us", "intl"):
            value = str(translations.get(key) or "").strip()
            if value and value not in aliases:
                aliases.append(value)
    return aliases


def _jp_alias_maps_from_tcgdex(normalize_name_func):
    cached = st.session_state.get("est_jp_alias_maps")
    if isinstance(cached, dict):
        return cached
    alias_maps = {"en": {}, "fr": {}}
    for lang in ("en", "fr"):
        try:
            response = requests.get(f"https://api.tcgdex.net/v2/{lang}/cards", timeout=12)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            _log_once(
                "jp_alias_cache",
                f"{lang}|{type(exc).__name__}",
                f'[Estimations JP] alias_source={lang} loaded=no error="{type(exc).__name__}"',
            )
            continue
        if not isinstance(payload, list):
            continue
        for source_card in payload:
            if not isinstance(source_card, dict):
                continue
            card_id = str(source_card.get("id") or "").strip()
            name = str(source_card.get("name") or "").strip()
            if not card_id or not name:
                continue
            alias_maps[lang][card_id] = name
    st.session_state["est_jp_alias_maps"] = alias_maps
    _perf_log_once(
        "jp_alias_index",
        f'{len(alias_maps["en"])}|{len(alias_maps["fr"])}',
        f'[Estimations Perf] jp_alias_index en={len(alias_maps["en"])} fr={len(alias_maps["fr"])}',
    )
    return alias_maps


def _build_search_index(cards_index, normalize_name_func):
    global _ESTIMATION_SEARCH_INDEX, _ESTIMATION_SEARCH_INDEX_SOURCE_ID, _ESTIMATION_SEARCH_INDEX_BY_LANG
    started_at = time.perf_counter()
    source_id = _search_index_source_id(cards_index)
    if source_id and source_id == _ESTIMATION_SEARCH_INDEX_SOURCE_ID:
        return _ESTIMATION_SEARCH_INDEX
    index = []
    by_lang = {"fr": [], "ja": []}
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
                lang = _card_language(card, default="fr")
                image_fields = _fast_index_image_fields(card, number, lang)
                enriched = {
                    "id": card.get("id", ""),
                    "name": card.get("name", idx_name or ""),
                    "name_en": card.get("name_en", "") or card.get("english_name", "") or card.get("nameEn", ""),
                    "name_fr": card.get("name_fr", "") or card.get("french_name", "") or card.get("nameFr", ""),
                    "aliases": card.get("aliases") or [],
                    "set": set_name,
                    "set_id": set_id,
                    "number": number,
                    "rarity": card.get("rarity", ""),
                    "category": card.get("category", ""),
                    "special": card.get("special", ""),
                    "special_tag": card.get("special_tag", ""),
                    "tags": card.get("tags") or card.get("card_tags") or [],
                    "card_tags": card.get("card_tags") or [],
                    "metadata_tags": card.get("metadata_tags") or [],
                    "subtypes": card.get("subtypes") or [],
                    "types": card.get("types") or [],
                    "variants": card.get("variants") or {},
                    "promo": card.get("promo", ""),
                    "is_reverse": card.get("is_reverse", False),
                    "is_ed1": card.get("is_ed1", False),
                    "image_url": image_fields.get("image_url", ""),
                    "image_url_en": image_fields.get("image_url_en", ""),
                    "image_url_ja": image_fields.get("image_url_ja", ""),
                    "lang": lang,
                    "language": lang,
                }
                metadata_tags = _normalized_card_metadata_tags(enriched, normalize_name_func)
                if metadata_tags:
                    enriched["metadata_tags"] = sorted(set((enriched.get("metadata_tags") or []) + metadata_tags))
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
                            enriched.get("name_en"),
                            enriched.get("name_fr"),
                            " ".join(str(alias) for alias in enriched.get("aliases", []) or []),
                            enriched.get("number"),
                            enriched.get("set"),
                            enriched.get("rarity"),
                            enriched.get("category"),
                            enriched.get("special"),
                            enriched.get("special_tag"),
                            " ".join(str(tag) for tag in enriched.get("tags", []) or []),
                            " ".join(str(tag) for tag in enriched.get("metadata_tags", []) or []),
                            " ".join(str(tag) for tag in enriched.get("subtypes", []) or []),
                            " ".join(str(tag) for tag in enriched.get("types", []) or []),
                            enriched.get("id"),
                            enriched.get("set_id"),
                            enriched.get("lang"),
                            enriched.get("language"),
                            " ".join(set_tags),
                        ]
                    )
                )
                index_item = {
                    "match": (card, set_name),
                    "card": enriched,
                    "search_text": search_text,
                    "name_norm": normalize_name_func(enriched.get("name", "")),
                    "alias_norm": normalize_name_func(
                        " ".join(
                            str(value or "")
                            for value in [
                                enriched.get("name_en"),
                                enriched.get("name_fr"),
                                " ".join(str(alias) for alias in enriched.get("aliases", []) or []),
                            ]
                        )
                    ),
                    "number_norm": normalize_name_func(enriched.get("number", "")),
                    "set_tags": set_tags,
                }
                index.append(index_item)
                by_lang.setdefault(lang, []).append(index_item)
    if pocket_hidden:
        _log_once(
            "pocket_filter",
            f"{source_id}|{pocket_hidden}",
            f"[Estimations Pocket Filter] hidden={pocket_hidden}",
        )
    _ESTIMATION_SEARCH_INDEX = index
    _ESTIMATION_SEARCH_INDEX_SOURCE_ID = source_id
    _ESTIMATION_SEARCH_INDEX_BY_LANG = by_lang
    _perf_log_once(
        "build_index",
        f"{source_id}|{len(index)}",
        f'[Estimations Perf] index build total={len(index)} fr={len(by_lang.get("fr", []))} ja={len(by_lang.get("ja", []))} elapsed_ms={int((time.perf_counter() - started_at) * 1000)}',
    )
    return index


def _search_index_for_language(cards_index, normalize_name_func, language):
    language = "ja" if str(language or "").lower() in {"ja", "jp", "jpn"} else "fr"
    _build_search_index(cards_index, normalize_name_func)
    return _ESTIMATION_SEARCH_INDEX_BY_LANG.get(language, [])


def _jp_card_from_tcgdex_summary(card):
    if not isinstance(card, dict):
        return None
    name = str(card.get("name") or "").strip()
    card_id = str(card.get("id") or "").strip()
    number = str(card.get("localId") or card.get("number") or "").strip()
    if not name or not card_id:
        return None
    set_id = card_id.rsplit("-", 1)[0] if "-" in card_id else str(card.get("set_id") or "").strip()
    image_url = _tcgdex_image_from_id(card_id, number, lang="ja")
    return {
        "id": card_id,
        "card_id": card_id,
        "name": name,
        "name_en": str(card.get("name_en") or card.get("english_name") or card.get("nameEn") or "").strip(),
        "name_fr": str(card.get("name_fr") or card.get("french_name") or card.get("nameFr") or "").strip(),
        "aliases": _jp_aliases_from_summary(card),
        "number": number,
        "localId": number,
        "set_id": set_id,
        "set": str(card.get("set") or set_id).strip(),
        "rarity": str(card.get("rarity") or "").strip(),
        "image_url_ja": image_url,
        "image_url": "",
        "image_url_en": "",
        "lang": "ja",
        "language": "ja",
        "special": "Japonaise",
        "source": "tcgdex_ja",
    }


def _ensure_japanese_cards_cache(normalize_name_func):
    cards_index = st.session_state.get("cards_index", {})
    existing_jp = _search_index_for_language(cards_index, normalize_name_func, "ja")
    if existing_jp:
        return {"loaded": True, "count": len(existing_jp), "source": "existing"}
    if st.session_state.get("est_jp_cache_attempted"):
        return {
            "loaded": False,
            "count": 0,
            "source": st.session_state.get("est_jp_cache_source", "unavailable"),
            "error": st.session_state.get("est_jp_cache_error", ""),
        }

    st.session_state["est_jp_cache_attempted"] = True
    started_at = time.perf_counter()
    try:
        response = requests.get(_JP_CARDS_CACHE_URL, timeout=12)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        st.session_state["est_jp_cache_error"] = str(exc)
        st.session_state["est_jp_cache_source"] = "tcgdex_ja_failed"
        _log_once(
            "jp_cache",
            f"error|{type(exc).__name__}",
            f'[Estimations JP] source=tcgdex_ja loaded=no error="{type(exc).__name__}"',
        )
        return {"loaded": False, "count": 0, "source": "tcgdex_ja_failed", "error": str(exc)}

    if not isinstance(payload, list):
        st.session_state["est_jp_cache_error"] = "invalid_payload"
        st.session_state["est_jp_cache_source"] = "tcgdex_ja_invalid"
        return {"loaded": False, "count": 0, "source": "tcgdex_ja_invalid", "error": "invalid_payload"}

    if not isinstance(cards_index, dict):
        cards_index = {}
    alias_maps = _jp_alias_maps_from_tcgdex(normalize_name_func)
    seen = {
        str((item[0] if isinstance(item, (list, tuple)) and item else {}).get("id") or "")
        for values in cards_index.values()
        if isinstance(values, (list, tuple))
        for item in values
        if isinstance(item, (list, tuple)) and item and isinstance(item[0], dict)
    }
    added = 0
    for source_card in payload:
        card = _jp_card_from_tcgdex_summary(source_card)
        if not card or card["id"] in seen:
            continue
        card_id = str(card.get("id") or "")
        for lang_key, field_key in (("en", "name_en"), ("fr", "name_fr")):
            alias = str((alias_maps.get(lang_key) or {}).get(card_id) or "").strip()
            if alias:
                card[field_key] = alias
                aliases = list(card.get("aliases") or [])
                if alias not in aliases:
                    aliases.append(alias)
                card["aliases"] = aliases
        seen.add(card["id"])
        key = normalize_name_func(card["name"])
        cards_index.setdefault(key, []).append((card, card.get("set", ""), card.get("set_id", "")))
        added += 1
    st.session_state["cards_index"] = cards_index
    st.session_state["est_jp_cache_source"] = "tcgdex_ja"
    _reset_estimation_search_memory_cache()
    indexed = _search_index_for_language(cards_index, normalize_name_func, "ja")
    _log_once(
        "jp_cache",
        f"loaded|{added}|{len(indexed)}",
        f'[Estimations JP] source=tcgdex_ja fetched={len(payload)} added={added} index_cards={len(indexed)} elapsed_ms={int((time.perf_counter() - started_at) * 1000)}',
    )
    return {"loaded": bool(indexed), "count": len(indexed), "source": "tcgdex_ja", "added": added}


def _candidate_matches_index_item(item, terms, requested_types, raw_norm, requested_set_tags):
    if not raw_norm:
        return False
    search_text = item.get("search_text", "")
    name_norm = item.get("name_norm", "")
    number_norm = item.get("number_norm", "")
    if terms:
        terms_match = all(term in search_text for term in terms)
        if requested_set_tags and _shiny_filter_requested(requested_set_tags):
            return terms_match and _set_tag_matches_item(item, requested_set_tags)
        return terms_match
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


def _log_search_results(raw, requested_types, requested_set_tags, parsed_number, terms, result, normalize_name_func, started_at, cache_hit=False, language="fr"):
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
        f"{language}|{query_norm}|{cache_hit}|{elapsed_ms}|{len(result)}",
        f'[Estimations Live Search] language={language} query="{raw}" elapsed_ms={elapsed_ms}',
    )
    _log_once(
        "live_search_keyup",
        f"{language}|{query_norm}|{cache_hit}",
        f"[Estimations Live Search] language={language} keyup=yes debounce_ms={_ESTIMATION_KEYUP_DEBOUNCE_MS}",
    )
    _log_once(
        "live_search_results",
        f"{language}|{query_norm}|{cache_hit}|{len(result)}",
        f'[Estimations Live Search] language={language} results={len(result)} cache_hit={"yes" if cache_hit else "no"}',
    )
    _log_once(
        "search",
        f"{language}|{query_norm}|{cache_hit}|{[(item['card'].get('id'), item['score']) for item in result[:5]]}",
        f'[Estimations Search] language={language} query="{raw}" results={len(result)} elapsed_ms={elapsed_ms} '
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


def _manual_add_exact_match(name, number, normalize_name_func, language="fr"):
    cards_index = st.session_state.get("cards_index", {})
    language = "ja" if str(language or "").lower() in {"ja", "jp", "jpn"} else "fr"
    indexed_cards = _search_index_for_language(cards_index, normalize_name_func, language)
    name_norm = normalize_name_func(name)
    number_text = str(number or "").strip()
    if not name_norm:
        return "none", []
    candidates = []
    for item in indexed_cards:
        card = item["card"]
        if _card_language(card, default="fr") != language:
            continue
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


def _card_suggestions(query, current_number, search_in_cache_func, ecd_func, normalize_name_func, limit=8, language="fr"):
    started_at = time.perf_counter()
    cards_index = st.session_state.get("cards_index", {})
    language = "ja" if str(language or "").lower() in {"ja", "jp", "jpn"} else "fr"
    index_started = time.perf_counter()
    indexed_cards = _search_index_for_language(cards_index, normalize_name_func, language)
    index_ms = int((time.perf_counter() - index_started) * 1000)
    known_tags = _known_set_tags(indexed_cards)
    raw, base_query, broad_query, parsed_number, keywords, terms, requested_types, requested_set_tags = _query_parts(query, normalize_name_func, known_tags)
    number = str(current_number or parsed_number or "").strip()
    raw_norm = normalize_name_func(raw)
    if not raw.strip():
        return []

    cache_key = f"{language}|{normalize_name_func(raw)}|{number}|filters={','.join(requested_types)}|sets={','.join(requested_set_tags)}"
    if cache_key in _ESTIMATION_SUGGESTIONS_CACHE:
        result = _ESTIMATION_SUGGESTIONS_CACHE[cache_key]
        _log_search_results(raw, requested_types, requested_set_tags, number, terms, result, normalize_name_func, started_at, cache_hit=True, language=language)
        _perf_log_once(
            "search",
            f"{cache_key}|hit",
            f'[Estimations Perf] search query="{raw}" lang={language} index_ms={index_ms} search_ms=0 text_ready_ms={int((time.perf_counter() - started_at) * 1000)} render_ms=0 total_ms={int((time.perf_counter() - started_at) * 1000)} cache_hit=yes',
        )
        return result

    search_started = time.perf_counter()
    suggestions = []
    strict_types = _strict_rarity_requested_types(requested_types)
    strict_shiny_set = _shiny_filter_requested(requested_set_tags)
    preferences = st.session_state.get("estimation_search_preferences") or {}
    for item in indexed_cards:
        if _card_language(item.get("card"), default="fr") != language:
            continue
        if not _candidate_matches_index_item(item, terms, requested_types, raw_norm, requested_set_tags):
            continue
        enriched = item["card"]
        if not is_physical_pokemon_tcg_card(enriched):
            continue
        if strict_shiny_set and not _card_set_match(enriched, requested_set_tags):
            continue
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
        preference_count = int(preferences.get(_estimation_search_card_key(enriched, normalize_name_func), 0) or 0)
        if preference_count:
            score += min(preference_count * 4, _SEARCH_PREFERENCE_MAX_BONUS)
        suggestions.append({"match": item["match"], "card": enriched, "score": score, "strict_match": strict_match})

    if not suggestions and indexed_cards and not strict_shiny_set:
        for item in indexed_cards:
            if _card_language(item.get("card"), default="fr") != language:
                continue
            search_text = item.get("search_text", "")
            name_norm = item.get("name_norm", "")
            if terms:
                fallback_match = all(term in search_text for term in terms)
            else:
                fallback_match = raw_norm in search_text or name_norm.startswith(raw_norm[:1])
            if fallback_match:
                enriched = item["card"]
                if not is_physical_pokemon_tcg_card(enriched):
                    continue
                score = _suggestion_score(enriched, keywords, terms, number, requested_types, requested_set_tags, normalize_name_func) - 40
                strict_match = _card_matches_all_strict_rarities(enriched, requested_types, normalize_name_func) if strict_types else False
                if strict_match:
                    score += 260
                elif strict_types:
                    score -= 120
                preference_count = int(preferences.get(_estimation_search_card_key(enriched, normalize_name_func), 0) or 0)
                if preference_count:
                    score += min(preference_count * 4, _SEARCH_PREFERENCE_MAX_BONUS)
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
    _log_search_results(raw, requested_types, requested_set_tags, number, terms, result, normalize_name_func, started_at, cache_hit=False, language=language)
    _perf_log_once(
        "search",
        f"{cache_key}|miss|{[(item['card'].get('id'), item['score']) for item in result[:3]]}",
        f'[Estimations Perf] search query="{raw}" lang={language} index_ms={index_ms} search_ms={int((time.perf_counter() - search_started) * 1000)} text_ready_ms={int((time.perf_counter() - started_at) * 1000)} render_ms=0 total_ms={int((time.perf_counter() - started_at) * 1000)} cache_hit=no',
    )
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
    global _ESTIMATION_SEARCH_INDEX, _ESTIMATION_SEARCH_INDEX_SOURCE_ID, _ESTIMATION_SEARCH_INDEX_BY_LANG
    _ESTIMATION_SUGGESTIONS_CACHE.clear()
    _ESTIMATION_IMAGE_RESOLUTION_CACHE.clear()
    _ESTIMATION_SEARCH_INDEX = []
    _ESTIMATION_SEARCH_INDEX_BY_LANG = {"fr": [], "ja": []}
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
    if _is_quick_bulk_entry(card):
        return 0.0
    for key in ("cote", "current_value", "estimated_value", "value", "suggested_price"):
        value = _safe_float((card or {}).get(key))
        if value > 0:
            return value
    return 0.0


def _estimate_cover_card(estimate):
    candidates = [card for card in estimate.get("cards", []) or [] if not _is_quick_bulk_entry(card) and _card_unit_value(card) > 0]
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
                    {_kpi("Prix demandé", _seller_price_label(estimate, fp_func), tone)}
                    {_kpi("Cote", fp_func(total_cote), tone)}
                    {_kpi("% cote", pct_label, tone)}
                    {_kpi("Marge", fp_func(margin) if total_cote else "À vérifier", tone)}
                    {_kpi("Cartes", f"{card_count}", tone)}
                </div>
            </div>
        </div>
    </div>
    """


def _render_tracked_card(card, estimate, fp_func, img_with_fallback_func, cardmarket_search_url_func, normalize_name_func, proxy_img_func=None, market_cache=None):
    qty = _safe_int(card.get("quantity"))
    cote = _safe_float(card.get("cote"))
    line_paid, unit_paid = _estimated_paid_for_card(card, estimate)
    line_margin = cote * qty - line_paid if line_paid else 0.0
    number = str(card.get("number") or "").strip()
    badges = _estimation_card_badges(card, normalize_name_func)
    image_info = _resolve_estimation_card_image(card)
    if image_info.get("source") == "placeholder":
        backfill_key = "|".join(
            [
                _card_language(card, default="fr"),
                str(card.get("id") or card.get("card_id") or ""),
                str(card.get("name") or ""),
                str(card.get("number") or ""),
            ]
        )
        cached_backfill = _ESTIMATION_IMAGE_BACKFILL_CACHE.get(backfill_key)
        if isinstance(cached_backfill, dict):
            image_info = dict(cached_backfill)
        elif cached_backfill != "missing":
            status, candidates = _manual_add_exact_match(
                card.get("name", ""),
                card.get("number", ""),
                normalize_name_func,
                language=_card_language(card, default="fr"),
            )
            if status == "exact" and candidates:
                candidate_info = _resolve_estimation_card_image(candidates[0].get("card", {}), log=False)
                if candidate_info.get("source") != "placeholder":
                    image_info = candidate_info
                    _ESTIMATION_IMAGE_BACKFILL_CACHE[backfill_key] = dict(candidate_info)
                else:
                    _ESTIMATION_IMAGE_BACKFILL_CACHE[backfill_key] = "missing"
            else:
                _ESTIMATION_IMAGE_BACKFILL_CACHE[backfill_key] = "missing"
            if len(_ESTIMATION_IMAGE_BACKFILL_CACHE) >= _ESTIMATION_IMAGE_BACKFILL_CACHE_MAX:
                _ESTIMATION_IMAGE_BACKFILL_CACHE.pop(next(iter(_ESTIMATION_IMAGE_BACKFILL_CACHE)))
    image = _estimation_image_html(
        image_info.get("url", ""),
        image_info.get("url_en", ""),
        style="height:100%;object-fit:contain;border-radius:10px;",
        fallbacks=image_info.get("fallbacks", []),
        proxy_img_func=proxy_img_func,
    )
    tags = " · ".join(x for x in [f"#{number}" if number else "", f"x{qty}"] if x)
    paid_label = fp_func(unit_paid) if unit_paid else "À vérifier"
    margin_label = fp_func(line_margin) if line_paid else "À vérifier"
    margin_class = "good" if line_paid and line_margin >= 0 else "bad" if line_paid else "neutral"
    cm_url = html.escape(_estimation_cardmarket_url(card, cardmarket_search_url_func), quote=True)
    market_badge_label, market_badge_css = _market_badge_info(card, market_cache or {})
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
        "market_badge_label": market_badge_label,
        "market_badge_css": market_badge_css,
    }


def _quick_bulk_label(card):
    bulk_type = str((card or {}).get("bulk_type") or "ex").upper()
    return "EX" if bulk_type == "EX" else "V"


def _new_quick_bulk_entry(bulk_type, quantity, new_uid_func):
    bulk = "v" if str(bulk_type).lower() == "v" else "ex"
    label = bulk.upper()
    return {
        "uid": new_uid_func("estbulk"),
        "entry_type": "quick_bulk",
        "bulk_type": bulk,
        "name": f"Lot {label} basiques",
        "quantity": max(int(quantity or 0), 0),
        "purchase_unit_price": QUICK_BULK_PURCHASE_UNIT_PRICE,
        "resale_unit_price": QUICK_BULK_RESALE_UNIT_PRICE,
        "cote": QUICK_BULK_RESALE_UNIT_PRICE,
        "condition": "",
        "special": "Lot rapide",
        "note": "Revente prévue personnalisée",
        "is_collection": False,
    }


def _render_quick_bulk_card(card, fp_func):
    qty = _safe_int(card.get("quantity"))
    bulk_label = _quick_bulk_label(card)
    purchase_unit = _quick_bulk_purchase_unit(card)
    resale_unit = _quick_bulk_resale_unit(card)
    purchase_total = _quick_bulk_purchase_total(card)
    resale_total = _quick_bulk_resale_total(card)
    margin = resale_total - purchase_total
    st.markdown(
        f"""
        <div class="est-quick-bulk-card">
            <div class="est-quick-bulk-head">
                <span>Lot rapide</span>
                <span>{html.escape(bulk_label)}</span>
            </div>
            <h4>Lot {html.escape(bulk_label)} basiques · x{qty}</h4>
            <p>Revente prévue personnalisée</p>
            <div class="est-quick-bulk-grid">
                <div><span>Achat unité</span><strong>{html.escape(fp_func(purchase_unit))}</strong></div>
                <div><span>Revente unité</span><strong>{html.escape(fp_func(resale_unit))}</strong></div>
                <div><span>Coût estimé</span><strong>{html.escape(fp_func(purchase_total))}</strong></div>
                <div><span>Valeur prévue</span><strong>{html.escape(fp_func(resale_total))}</strong></div>
                <div class="good"><span>Marge estimée</span><strong>{html.escape(fp_func(margin))}</strong></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _apply_market_price_suggestion(card, market_cache):
    if not card:
        return {"applied": False, "reason": "missing_card", "entry": None}
    if _safe_float(card.get("cote")) > 0 and not card.get("market_price_origin"):
        card["manual_price"] = _safe_float(card.get("cote"))
        card["market_price_origin"] = "legacy_manual"
        return {"applied": False, "reason": "legacy_manual_preserved", "entry": None}
    if _safe_float(card.get("cote")) <= 0:
        return apply_market_price_to_card(card, market_cache)
    return {"applied": False, "reason": "manual_or_existing_preserved", "entry": None}


def _market_badge_info(card, market_cache):
    entry = None
    try:
        from services.market_price_cache_service import lookup_market_price

        entry = lookup_market_price(market_cache, card)
    except Exception:
        entry = None
    label = market_price_badge(card, entry)
    cote = _safe_float((card or {}).get("cote"))
    if cote <= 0:
        return label, "none"
    origin = str((card or {}).get("market_price_origin") or "")
    price_status = str((card or {}).get("price_status") or (card or {}).get("market_price_status") or "").lower()
    if origin == "verified_manually" and price_status in {"", "verified"}:
        return "Vérifiée manuellement", "auto"
    label_lower = str(label or "").lower()
    label_fold = _fold_text(label)
    if origin in {"review", "stale", "unavailable"} or price_status in {"review", "stale", "unavailable", "needs_review", "uncertain"}:
        css = "review"
    elif "manuelle" in label_lower:
        css = "manual"
    elif "rifier" in label_lower or "verifier" in label_fold or "ancienne" in label_lower or "historique" in label_lower:
        css = "review"
    elif "auto" in label_lower and entry and _safe_float(entry.get("reference_price")) > 0:
        css = "auto"
    else:
        css = "none"
    return label, css


def _market_badge_html(card, market_cache):
    label, css = _market_badge_info(card, market_cache)
    return f'<span class="est-market-badge {css}">{html.escape(label)}</span>'


def _render_market_alerts(market_cache, edata, fp_func):
    alerts = build_market_alerts(market_cache, edata, st.session_state.get("data_cache"))
    if not alerts:
        return
    with st.expander("Alertes de marché", expanded=True):
        for alert in alerts[:8]:
            scope_note = (
                f'Vérifier dans l’estimation « {alert["context"]} »'
                if alert.get("scope") == "estimation"
                else "Ton prix d’étiquette reste inchangé."
            )
            st.markdown(
                f"""
                <div class="est-market-alert">
                    <strong>{html.escape(str(alert.get("card") or "Carte"))} {html.escape(str(alert.get("number") or ""))}</strong>
                    <span>Référence marché : {html.escape(fp_func(alert.get("previous", 0)))} → {html.escape(fp_func(alert.get("current", 0)))}</span>
                    <em>Variation : {alert.get("pct", 0):+.1f}% · {scope_note}</em>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_market_cache_tools(market_cache, edata):
    with st.expander("Mémoire de cotes", expanded=False):
        st.caption(
            "Cette mémoire est séparée du stock. Elle sert seulement aux Estimations et aux alertes informatives."
        )
        settings = market_cache.setdefault("settings", {})
        c1, c2, c3 = st.columns([1, 1, 1])
        min_pct = c1.text_input("Alerte variation (%)", value=str(settings.get("alert_min_pct", 15.0)).replace(".", ","), key="market_alert_min_pct")
        min_eur = c2.text_input("Alerte écart (€)", value=str(settings.get("alert_min_eur", 3.0)).replace(".", ","), key="market_alert_min_eur")
        if c3.button("Sauvegarder les seuils", key="market_alert_save_settings", width="stretch"):
            settings["alert_min_pct"] = _safe_float(min_pct, 15.0)
            settings["alert_min_eur"] = _safe_float(min_eur, 3.0)
            save_market_price_cache(market_cache)
            st.session_state["market_price_cache"] = market_cache
            st.success("Seuils d’alerte sauvegardés.")
            st.rerun()
        if st.button("Initialiser la mémoire de cotes depuis mes estimations", key="market_cache_import_history", width="stretch"):
            updated_cache, result = import_estimations_history(market_cache, edata)
            save_result = save_market_price_cache(updated_cache)
            st.session_state["market_price_cache"] = updated_cache
            st.success(
                "Historique importé : "
                f"{result.get('imported', 0)} · Cartes ambiguës : {result.get('ambiguous', 0)} · "
                f"Entrées plus fiables conservées : {result.get('preserved', 0)} · "
                "Aucune carte de stock modifiée"
            )
            print(
                "[Market Price Cache] "
                f"history_imported={result.get('imported', 0)} ambiguous={result.get('ambiguous', 0)} "
                f"preserved={result.get('preserved', 0)} storage={save_result.get('storage')}",
                flush=True,
            )
            st.rerun()


def _render_suggestion_card(enriched, proxy_img_func=None):
    image_info = _suggestion_image_info(enriched)
    image = _estimation_image_html(
        image_info.get("url", ""),
        "",
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
    return bool(image_info.get("cache_hit"))


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
    regular_cards = [card for card in cards or [] if not _is_quick_bulk_entry(card)]
    quick_cards = [card for card in cards or [] if _is_quick_bulk_entry(card)]
    display_cards = list(reversed(regular_cards))
    if not query_norm:
        return display_cards + quick_cards
    terms = [term for term in query_norm.split() if term]
    return [card for card in display_cards if all(term in _estimation_card_filter_text(card, normalize_name_func) for term in terms)]


def _refresh_estimation_card_image(card, normalize_name_func, cache_enrichment_func=None):
    if not card or _is_quick_bulk_entry(card):
        return False
    language = _card_language(card, default="fr")
    status, candidates = _manual_add_exact_match(card.get("name", ""), card.get("number", ""), normalize_name_func, language=language)
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
        if _is_quick_bulk_entry(card):
            continue
        image_info = _resolve_estimation_card_image(card, log=False)
        if image_info.get("source") == "placeholder" or _invalid_estimation_image_refs(card):
            missing.append(card)
    return missing


def _repair_missing_estimation_images(estimate, normalize_name_func, cache_enrichment_func=None):
    missing = _cards_missing_estimation_image(estimate.get("cards", []) or [])
    repaired = 0
    invalid_refs = 0
    for card in missing:
        invalid_refs += len(_drop_invalid_estimation_image_refs(card))
        if _refresh_estimation_card_image(card, normalize_name_func, cache_enrichment_func):
            repaired += 1
    unresolved = max(len(missing) - repaired, 0)
    print(
        f'[Estimations Image Repair] estimate="{estimate.get("name", "Estimation")}" '
        f"missing={len(missing)} invalid_refs={invalid_refs} repaired={repaired} unresolved={unresolved}",
        flush=True,
    )
    return {"missing": len(missing), "invalid_refs": invalid_refs, "repaired": repaired, "unresolved": unresolved}


def _card_belongs_to_ex_group(card, normalize_name_func):
    if _is_quick_bulk_entry(card):
        return str(card.get("bulk_type") or "").strip().lower() == "ex"
    text = normalize_name_func(
        " ".join(
            str(value or "")
            for value in [
                card.get("name"),
                card.get("number"),
                card.get("rarity"),
                card.get("category"),
                card.get("special"),
                card.get("special_tag"),
                " ".join(str(tag) for tag in card.get("tags", []) or []),
                " ".join(str(tag) for tag in card.get("metadata_tags", []) or []),
                " ".join(str(tag) for tag in card.get("types", []) or []),
                " ".join(str(tag) for tag in card.get("subtypes", []) or []),
            ]
        )
    )
    padded = f" {text.replace('-', ' ')} "
    return " ex " in padded


def _estimation_group_stats(estimate, totals, normalize_name_func):
    pct = _safe_float(totals.get("pct"))
    fees_and_safety = _safe_float(totals.get("fees")) + _safe_float(totals.get("safety_eur"))
    groups = {
        "ex": {"label": "EX", "cards": 0, "value": 0.0, "raw_max_buy": 0.0, "paid": 0.0},
        "other": {"label": "Autres cartes", "cards": 0, "value": 0.0, "raw_max_buy": 0.0, "paid": 0.0},
    }
    for card in estimate.get("cards", []) or []:
        key = "ex" if _card_belongs_to_ex_group(card, normalize_name_func) else "other"
        qty = max(_safe_int(card.get("quantity")), 0)
        groups[key]["cards"] += qty
        if _is_quick_bulk_entry(card):
            value = _quick_bulk_resale_total(card)
            raw_max_buy = _quick_bulk_purchase_total(card)
        else:
            value = _safe_float(card.get("cote")) * qty
            raw_max_buy = value * pct / 100.0 if pct > 0 else 0.0
        paid, _ = _estimated_paid_for_card(card, estimate)
        groups[key]["value"] += value
        groups[key]["raw_max_buy"] += raw_max_buy
        groups[key]["paid"] += paid

    raw_total = sum(group["raw_max_buy"] for group in groups.values())
    total_value = _safe_float(totals.get("total_cote"))
    for group in groups.values():
        deduction = fees_and_safety * (group["raw_max_buy"] / raw_total) if raw_total > 0 and fees_and_safety > 0 else 0.0
        group["max_buy"] = max(group["raw_max_buy"] - deduction, 0.0)
        group["margin"] = group["value"] - group["paid"] if group["paid"] else 0.0
        group["share"] = (group["value"] / total_value * 100.0) if total_value > 0 else 0.0
    return groups


def _finish_estimation_report(estimate, totals):
    cards = estimate.get("cards", []) or []
    blockers = []
    warnings = []
    language_unknown_cards = []
    normalized_languages = 0
    cardmarket = {
        "fr_exact": 0,
        "fr_search": 0,
        "ja_exact": 0,
        "ja_search": 0,
        "details": [],
    }
    real_cards = [card for card in cards if not _is_quick_bulk_entry(card)]
    total_cards = sum(max(_safe_int(card.get("quantity")), 0) for card in cards)
    cards_with_cote = 0
    cards_without_cote = 0
    cards_without_image = 0
    cards_to_review = 0
    unknown_language = 0

    if not cards:
        blockers.append("Cette estimation ne contient encore aucune carte.")
    if total_cards <= 0 and cards:
        blockers.append("La quantité totale est invalide.")
    if _explicit_seller_price(estimate) <= 0:
        warnings.append("Le prix demandé n’est pas renseigné.")

    for card in cards:
        qty = _safe_int(card.get("quantity"))
        if qty <= 0:
            blockers.append(f"{card.get('name', 'Carte')} a une quantité invalide.")
        if _is_quick_bulk_entry(card):
            if _quick_bulk_purchase_unit(card) <= 0 or _quick_bulk_resale_unit(card) <= 0:
                blockers.append(f"{card.get('name', 'Lot rapide')} a un prix rapide invalide.")
            continue

        if _safe_float(card.get("cote")) > 0:
            cards_with_cote += 1
        else:
            cards_without_cote += 1
            warnings.append(f"{card.get('name', 'Carte')} n’a pas encore de cote.")

        if card.get("market_price_origin") in {"review", "stale", "unavailable"} or card.get("market_price_status") in {"review", "stale", "unavailable"}:
            cards_to_review += 1
            warnings.append(f"{card.get('name', 'Carte')} a une cote à vérifier.")

        image_info = _resolve_estimation_card_image(card, log=False)
        if image_info.get("source") == "placeholder":
            cards_without_image += 1
            warnings.append(f"{card.get('name', 'Carte')} n’a pas d’image fiable.")
        if not str(card.get("number") or "").strip():
            warnings.append(f"{card.get('name', 'Carte')} n’a pas de numéro.")

        lang = _card_language(card, default="")
        if lang in {"fr", "ja"}:
            if _write_normalized_card_language(card, lang):
                normalized_languages += 1
        if lang not in {"fr", "ja"}:
            unknown_language += 1
            language_unknown_cards.append(card.get("name", "Carte"))
        exact_cardmarket = bool(_exact_cardmarket_url(card))
        if lang == "ja":
            key = "ja_exact" if exact_cardmarket else "ja_search"
            cardmarket[key] += 1
            cardmarket["details"].append({"name": card.get("name", "Carte"), "lang": "JP", "type": "fiche exacte" if exact_cardmarket else "recherche JP NM"})
        elif lang == "fr":
            key = "fr_exact" if exact_cardmarket else "fr_search"
            cardmarket[key] += 1
            cardmarket["details"].append({"name": card.get("name", "Carte"), "lang": "FR", "type": "fiche exacte" if exact_cardmarket else "recherche FR NM"})

    if cardmarket["fr_search"] or cardmarket["ja_search"]:
        warnings.append("Certains liens Cardmarket utilisent une recherche NM, pas une fiche exacte.")
    if language_unknown_cards:
        preview = ", ".join(str(name) for name in language_unknown_cards[:6])
        extra = f" (+{len(language_unknown_cards) - 6})" if len(language_unknown_cards) > 6 else ""
        warnings.append(f"Langue à vérifier pour {len(language_unknown_cards)} carte(s) : {preview}{extra}.")

    return {
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "cardmarket": cardmarket,
        "total_cards": total_cards,
        "real_cards": len(real_cards),
        "cards_with_cote": cards_with_cote,
        "cards_without_cote": cards_without_cote,
        "cards_to_review": cards_to_review,
        "cards_without_image": cards_without_image,
        "unknown_language": unknown_language,
        "normalized_languages": normalized_languages,
    }


def _render_finish_estimation_panel(estimate, totals, uid, edata, save_estimations_func, fp_func, normalize_name_func, parse_float_input_func):
    finish_key = f"est_finish_panel_{uid}"
    c1, c2 = st.columns([1, 1])
    if c1.button("Finir l’estimation", key=f"est_finish_open_{uid}", width="stretch"):
        st.session_state[finish_key] = True
    if estimate.get("ready_for_offer"):
        c2.success("Prête pour offre")

    if not st.session_state.get(finish_key):
        return

    finish_started = time.perf_counter()
    report = _finish_estimation_report(estimate, totals)
    if report.get("normalized_languages"):
        save_estimations_func(edata)
    blockers = report["blockers"]
    warnings = report["warnings"]
    group_stats = _estimation_group_stats(estimate, totals, normalize_name_func)
    cardmarket = report.get("cardmarket", {})
    _perf_log_once(
        "finish",
        f'{uid}|{report["total_cards"]}|{len(blockers)}|{len(warnings)}',
        f'[Estimations Perf] finish cards={report["total_cards"]} blockers={len(blockers)} warnings={len(warnings)} total_ms={int((time.perf_counter() - finish_started) * 1000)}',
    )
    with st.container(border=True):
        st.markdown("#### Estimation prête à vérifier")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Cartes", report["total_cards"])
        s2.metric("Avec cote", report["cards_with_cote"])
        s3.metric("Sans cote", report["cards_without_cote"])
        s4.metric("Sans image", report["cards_without_image"])
        st.caption(
            " · ".join(
                [
                    f"Valeur estimée : {fp_func(totals.get('total_cote', 0.0))}",
                    f"Prix demandé : {_seller_price_label(estimate, fp_func)}",
                    f"Cartes à vérifier : {report['cards_to_review']}",
                ]
            )
        )
        g1, g2 = st.columns(2)
        for container, group_key in ((g1, "ex"), (g2, "other")):
            group = group_stats[group_key]
            with container:
                st.markdown(f"**{group['label']}**")
                st.caption(
                    " · ".join(
                        [
                            f"Cartes : {group['cards']}",
                            f"Vente estimée : {fp_func(group['value'])}",
                            f"Rachat max : {fp_func(group['max_buy'])}",
                            f"Part : {group['share']:.1f}%",
                        ]
                    )
                )
        if cardmarket:
            st.markdown("**Liens Cardmarket**")
            st.caption(
                " · ".join(
                    [
                        f"{cardmarket.get('fr_search', 0)} recherche(s) FR NM",
                        f"{cardmarket.get('fr_exact', 0)} fiche(s) FR exacte(s)",
                        f"{cardmarket.get('ja_search', 0)} recherche(s) JP NM",
                        f"{cardmarket.get('ja_exact', 0)} fiche(s) JP exacte(s)",
                    ]
                )
            )
            fallback_details = [detail for detail in cardmarket.get("details", []) if "recherche" in str(detail.get("type", ""))]
            if fallback_details:
                with st.expander("Voir les détails des liens", expanded=False):
                    for detail in fallback_details[:40]:
                        st.caption(f"- {detail.get('name', 'Carte')} · {detail.get('lang', '')} · {detail.get('type', '')}")
                    if len(fallback_details) > 40:
                        st.caption(f"- {len(fallback_details) - 40} autre(s) carte(s).")
        if blockers:
            st.error("À corriger avant une offre")
            for item in blockers[:8]:
                st.caption(f"- {item}")
        if warnings:
            st.warning("Points à vérifier avant une offre")
            for item in warnings[:10]:
                st.caption(f"- {item}")
            if len(warnings) > 10:
                st.caption(f"- {len(warnings) - 10} autre(s) point(s) à vérifier.")
        if not blockers and not warnings:
            st.success("Tout semble prêt pour une vérification finale.")

        a1, a2, a3 = st.columns([1, 1, 1])
        if a1.button("Retourner à l’estimation", key=f"est_finish_close_{uid}", width="stretch"):
            st.session_state[finish_key] = False
            st.rerun()
        ready_disabled = bool(blockers)
        if a2.button("Marquer comme prête", key=f"est_finish_ready_{uid}", disabled=ready_disabled, width="stretch"):
            estimate["ready_for_offer"] = True
            estimate["ready_for_offer_at"] = datetime.now().isoformat()
            estimate["workflow_status"] = "Prête pour offre"
            estimate["status"] = "Prête pour offre"
            save_estimations_func(edata)
            st.session_state[finish_key] = False
            st.rerun()
        if a3.button("Continuer malgré les avertissements", key=f"est_finish_warn_{uid}", disabled=ready_disabled, width="stretch"):
            estimate["ready_for_offer"] = True
            estimate["ready_for_offer_at"] = datetime.now().isoformat()
            estimate["workflow_status"] = "Prête pour offre"
            estimate["status"] = "Prête pour offre"
            save_estimations_func(edata)
            st.session_state[finish_key] = False
            st.rerun()

        offer_key = f"est_offer_amount_{uid}"
        existing_offer = _safe_float(estimate.get("offer_amount") or estimate.get("sent_offer_amount"))
        if offer_key not in st.session_state:
            st.session_state[offer_key] = f"{existing_offer:.2f}".replace(".", ",") if existing_offer > 0 else ""
        st.markdown("**Offre vendeur**")
        if existing_offer > 0:
            st.caption(
                " · ".join(
                    [
                        f"Dernière offre enregistrée : {fp_func(existing_offer)}",
                        f"Date : {str(estimate.get('offer_sent_at') or estimate.get('sent_offer_at') or 'non renseignée')[:19]}",
                    ]
                )
            )
        offer_cols = st.columns([2, 1])
        offer_raw = offer_cols[0].text_input("Montant de l’offre à envoyer (€)", key=offer_key, placeholder="Ex: 120")
        offer_disabled = bool(blockers)
        offer_label = "Modifier l’offre" if existing_offer > 0 else "Enregistrer l’offre envoyée"
        if offer_cols[1].button(offer_label, key=f"est_offer_save_{uid}", disabled=offer_disabled, width="stretch"):
            amount = parse_float_input_func(offer_raw, 0.0)
            if amount <= 0:
                st.error("Saisis un montant d’offre valide.")
            else:
                estimate["offer_amount"] = amount
                estimate["offer_sent_at"] = datetime.now().isoformat()
                estimate["workflow_status"] = "Offre envoyée"
                estimate["status"] = "Offre envoyée"
                save_estimations_func(edata)
                st.success(f"Offre enregistrée : {fp_func(amount)}. Aucun message externe n’a été envoyé.")
                st.rerun()


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
            width:100%;
            max-width:100%;
            min-width:0;
        }
        .est-tracked-image {
            width:100%;
            height:clamp(220px,20vw,292px);
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
            width:100% !important;
            max-width:100% !important;
            border:1px solid #e2e8f0 !important;
            border-radius:12px !important;
            background:#ffffff !important;
            box-shadow:0 8px 16px rgba(15,23,42,0.055) !important;
            padding:0 !important;
            margin-top:0.28rem !important;
        }
        [data-testid="stElementContainer"]:has(.est-tracked-bubble-marker) + div [data-testid="stVerticalBlock"] {
            width:100% !important;
            max-width:100% !important;
            min-width:0 !important;
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
        .est-market-badge-row {
            display:flex;
            margin-top:0.24rem;
            max-width:100%;
        }
        .est-market-badge {
            display:inline-flex;
            align-items:center;
            max-width:100%;
            border-radius:999px;
            padding:0.14rem 0.38rem;
            font-size:0.56rem;
            line-height:1.1;
            font-weight:850;
            overflow-wrap:anywhere;
            white-space:normal;
        }
        .est-market-badge.auto {
            color:#047857;
            background:#ecfdf5;
            border:1px solid #bbf7d0;
        }
        .est-market-badge.review {
            color:#92400e;
            background:#fffbeb;
            border:1px solid #fde68a;
        }
        .est-market-badge.manual {
            color:#4338ca;
            background:#eef2ff;
            border:1px solid #c7d2fe;
        }
        .est-market-badge.none {
            color:#64748b;
            background:#f8fafc;
            border:1px solid #e2e8f0;
        }
        .est-market-alert {
            border:1px solid #dbe4ff;
            border-radius:12px;
            background:linear-gradient(135deg,#f8fafc,#eef2ff);
            padding:0.65rem 0.8rem;
            margin:0.45rem 0;
            display:flex;
            flex-direction:column;
            gap:0.16rem;
        }
        .est-market-alert strong {
            color:#111827;
            font-size:0.95rem;
        }
        .est-market-alert span {
            color:#334155;
            font-weight:800;
        }
        .est-market-alert em {
            color:#6d28d9;
            font-style:normal;
            font-size:0.82rem;
            font-weight:800;
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
        .est-quick-bulk-card {
            border:1px solid #c7d2fe;
            border-radius:12px;
            background:linear-gradient(135deg,#f8fafc,#eef2ff);
            padding:0.62rem;
            box-shadow:0 8px 16px rgba(49,46,129,0.08);
            max-width:100%;
            min-width:0;
        }
        .est-quick-bulk-head {
            display:flex;
            flex-wrap:wrap;
            gap:0.25rem;
            margin-bottom:0.35rem;
        }
        .est-quick-bulk-head span {
            border-radius:999px;
            padding:0.15rem 0.42rem;
            background:#312e81;
            color:#ffffff;
            font-size:0.58rem;
            font-weight:900;
            letter-spacing:0;
        }
        .est-quick-bulk-card h4 {
            margin:0;
            color:#111827;
            font-size:0.82rem;
            line-height:1.16;
            overflow-wrap:anywhere;
        }
        .est-quick-bulk-card p {
            margin:0.16rem 0 0.45rem 0;
            color:#6d28d9;
            font-size:0.66rem;
            font-weight:850;
        }
        .est-quick-bulk-grid {
            display:grid;
            grid-template-columns:repeat(2,minmax(0,1fr));
            gap:0.24rem;
        }
        .est-quick-bulk-grid div {
            border:1px solid #dbe4ff;
            border-radius:8px;
            background:#ffffff;
            padding:0.3rem;
            min-width:0;
        }
        .est-quick-bulk-grid div.good {
            grid-column:1 / -1;
            background:#ecfdf5;
            border-color:#bbf7d0;
        }
        .est-quick-bulk-grid span {
            display:block;
            color:#64748b;
            font-size:0.58rem;
            font-weight:850;
        }
        .est-quick-bulk-grid strong {
            display:block;
            color:#0f172a;
            font-size:0.76rem;
            line-height:1.1;
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
        [data-testid="stElementContainer"]:has(.est-card-cote-marker.cote-auto) + div input {
            border:2px solid #22c55e !important;
            box-shadow:0 0 0 1px rgba(34,197,94,0.10) !important;
            background:#f0fdf4 !important;
        }
        [data-testid="stElementContainer"]:has(.est-card-cote-marker.cote-review) + div input {
            border:2px solid #f59e0b !important;
            box-shadow:0 0 0 1px rgba(245,158,11,0.11) !important;
            background:#fffbeb !important;
        }
        [data-testid="stElementContainer"]:has(.est-card-cote-marker.cote-manual) + div input,
        [data-testid="stElementContainer"]:has(.est-card-cote-marker.cote-none) + div input {
            border:1px solid #cbd5e1 !important;
            background:#ffffff !important;
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
        /* Refonte visuelle Estimations - couche collector premium, UI seulement. */
        .est-create-card {
            border-color:rgba(124,58,237,0.20) !important;
            background:linear-gradient(135deg,#ffffff,#f3e8ff 58%,#ecfeff) !important;
            box-shadow:0 16px 32px rgba(76,29,149,0.10) !important;
        }
        .est-opportunity-card {
            border-color:rgba(124,58,237,0.15) !important;
            background:#ffffff !important;
            box-shadow:0 14px 34px rgba(76,29,149,0.09) !important;
        }
        .est-opportunity-card:hover,
        .est-opportunity-card.active {
            border-color:rgba(124,58,237,0.26) !important;
            box-shadow:0 20px 42px rgba(76,29,149,0.15) !important;
        }
        .est-opportunity-card.great { background:linear-gradient(135deg,#ecfdf5,#ffffff 52%,#f4f0ff) !important; }
        .est-opportunity-card.good { background:linear-gradient(135deg,#ecfeff,#ffffff 52%,#f3e8ff) !important; }
        .est-opportunity-card.ok { background:linear-gradient(135deg,#fffbeb,#ffffff 52%,#faf5ff) !important; }
        .est-opportunity-card.bad { background:linear-gradient(135deg,#fff1f2,#ffffff 52%,#fdf2f8) !important; }
        .est-opportunity-card.check { background:linear-gradient(135deg,#f5f3ff,#ffffff 52%,#eef0ff) !important; }
        .est-opportunity-card.done { background:linear-gradient(135deg,#eef2ff,#ffffff 52%,#f3e8ff) !important; }
        .est-img-frame,
        .est-suggestion-img,
        .est-card-placeholder.compact {
            border-color:rgba(124,58,237,0.14) !important;
            background:#fbfaff !important;
        }
        .est-card-content h3,
        .est-detail-title h3,
        .est-tracked-heading h4,
        .est-suggestion-copy strong,
        .est-card-mini-grid strong,
        .est-quick-bulk-card h4,
        .est-quick-bulk-grid strong {
            color:#171423 !important;
        }
        .est-card-content p,
        .est-chip,
        .est-card-tags span,
        .est-kpi span,
        .est-tracked-tags,
        .est-suggestion-copy span,
        .est-card-mini-grid span,
        .est-quick-bulk-grid span {
            color:#6b6678 !important;
        }
        .est-listing-link,
        .est-cardmarket-link {
            background:#f3e8ff !important;
            color:#6d28d9 !important;
            border:1px solid #e9d5ff !important;
        }
        .est-listing-link:hover,
        .est-cardmarket-link:hover {
            background:#e9d5ff !important;
        }
        .est-chip,
        .est-card-tags span,
        .est-kpi,
        .est-card-mini-grid div,
        .est-quick-bulk-grid div {
            border-color:rgba(124,58,237,0.13) !important;
        }
        .est-detail-kpis .est-kpi {
            box-shadow:0 10px 22px rgba(76,29,149,0.06) !important;
        }
        [data-testid="stElementContainer"]:has(.est-tracked-bubble-marker) + div [data-testid="stVerticalBlockBorderWrapper"] {
            border-color:rgba(124,58,237,0.14) !important;
            border-radius:14px !important;
            box-shadow:0 8px 18px rgba(76,29,149,0.065) !important;
        }
        .est-tracked-body {
            border-color:rgba(124,58,237,0.14) !important;
            border-radius:14px !important;
            background:linear-gradient(180deg,#ffffff,#fbfaff) !important;
            box-shadow:0 8px 18px rgba(76,29,149,0.065) !important;
        }
        .est-badge-row span,
        .est-market-badge.manual {
            background:#f3e8ff !important;
            color:#6d28d9 !important;
            border-color:#e9d5ff !important;
        }
        .est-market-alert,
        .est-quick-bulk-card {
            border-color:#e9d5ff !important;
            background:linear-gradient(135deg,#fbfaff,#f3e8ff) !important;
            box-shadow:0 8px 18px rgba(76,29,149,0.08) !important;
        }
        .est-quick-bulk-head span {
            background:#4c1d95 !important;
        }
        .est-suggestions-grid {
            grid-template-columns:repeat(6,minmax(0,1fr)) !important;
            gap:0.55rem !important;
        }
        .est-suggestion-card {
            grid-template-columns:44px minmax(0,1fr) !important;
            border-color:rgba(124,58,237,0.14) !important;
            background:linear-gradient(135deg,#ffffff,#fbfaff) !important;
            box-shadow:0 7px 16px rgba(76,29,149,0.055) !important;
        }
        .est-tracked-image {
            height:clamp(220px,20vw,292px) !important;
        }
        .est-card-mini-grid {
            gap:0.18rem !important;
        }
        .est-card-mini-grid div {
            background:#fbfaff !important;
            padding:0.24rem 0.28rem !important;
        }
        .est-cardmarket-link {
            margin-top:0.34rem !important;
            margin-bottom:0.46rem !important;
            min-height:2.05rem !important;
            display:flex !important;
            align-items:center !important;
            justify-content:center !important;
        }
        [data-testid="stElementContainer"]:has(.est-retirer-marker) + div {
            border-top:1px solid #f0e9ff !important;
        }
        [data-testid="stElementContainer"]:has(.est-card-cote-marker) + div input {
            border-color:rgba(124,58,237,0.20) !important;
        }
        [data-testid="stElementContainer"]:has(.est-card-cote-marker.cote-auto) + div input {
            border:2px solid #22c55e !important;
            background:#f0fdf4 !important;
        }
        [data-testid="stElementContainer"]:has(.est-card-cote-marker.cote-review) + div input {
            border:2px solid #f59e0b !important;
            background:#fffbeb !important;
        }
        [data-testid="stElementContainer"]:has(.est-card-cote-marker.cote-manual) + div input,
        [data-testid="stElementContainer"]:has(.est-card-cote-marker.cote-none) + div input {
            border:1px solid #cbd5e1 !important;
            background:#ffffff !important;
        }
        @media(min-width:1180px) {
            .est-suggestions-grid {
                grid-template-columns:repeat(6,minmax(0,1fr)) !important;
            }
        }
        @media(max-width:1179px) and (min-width:860px) {
            .est-suggestions-grid {
                grid-template-columns:repeat(4,minmax(0,1fr)) !important;
            }
        }
        @media(max-width:859px) and (min-width:620px) {
            .est-suggestions-grid {
                grid-template-columns:repeat(2,minmax(0,1fr)) !important;
            }
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
            .est-tracked-image {
                height:clamp(230px,70vw,330px);
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


def _render_estimations_comparison(opportunities, fp_func, normalize_name_func):
    if len(opportunities) < 2:
        return
    with st.expander("Comparer les estimations", expanded=False):
        labels = [
            f"{item['estimate'].get('name', 'Estimation')} · {_estimation_tracking_status(item['estimate'])}"
            for item in opportunities
        ]
        selected = st.multiselect(
            "Estimations à comparer",
            labels,
            default=labels[: min(3, len(labels))],
            key="est_compare_selection",
        )
        selected_set = set(selected)
        sort_by = st.selectbox(
            "Trier par",
            ["Marge", "% cote", "Cote totale", "Prix demandé"],
            key="est_compare_sort",
        )
        rows = []
        label_to_uid = {}
        for label, item in zip(labels, opportunities):
            if label not in selected_set:
                continue
            estimate = item["estimate"]
            totals = item["totals"]
            label_to_uid[label] = estimate.get("uid")
            rows.append(
                {
                    "Estimation": estimate.get("name", "Estimation"),
                    "Statut": _estimation_tracking_status(estimate),
                    "Prix demandé": _seller_price_label(estimate, fp_func),
                    "Cote totale": fp_func(_safe_float(totals.get("total_cote"))),
                    "% cote": f"{_safe_float(totals.get('real_pct')):.1f}%" if _safe_float(totals.get("real_pct")) else "À vérifier",
                    "Marge": fp_func(_safe_float(totals.get("theoretical_margin"))),
                    "_sort_margin": _safe_float(totals.get("theoretical_margin")),
                    "_sort_pct": _safe_float(totals.get("real_pct")) or 999,
                    "_sort_total": _safe_float(totals.get("total_cote")),
                    "_sort_seller": _explicit_seller_price(estimate),
                }
            )
        sort_key = {
            "Marge": "_sort_margin",
            "% cote": "_sort_pct",
            "Cote totale": "_sort_total",
            "Prix demandé": "_sort_seller",
        }[sort_by]
        reverse = sort_by not in {"% cote", "Prix demandé"}
        rows.sort(key=lambda row: row.get(sort_key, 0), reverse=reverse)
        display_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]
        if display_rows:
            st.dataframe(display_rows, hide_index=True, use_container_width=True)
            open_label = st.selectbox("Ouvrir depuis la comparaison", [""] + selected, key="est_compare_open")
            if open_label and st.button("Ouvrir cette estimation", key="est_compare_open_btn", width="stretch"):
                st.session_state["active_estimation_uid"] = label_to_uid.get(open_label, "")
                st.rerun()
        else:
            st.caption("Sélectionne au moins une estimation à comparer.")


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
    normalize_name_func = _cached_normalizer(normalize_name_func)
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
    st.session_state["estimation_search_preferences"] = _estimation_search_preferences(edata, normalize_name_func)
    market_cache = st.session_state.get("market_price_cache")
    if not isinstance(market_cache, dict):
        market_cache = load_market_price_cache()
        st.session_state["market_price_cache"] = market_cache

    _render_market_alerts(market_cache, edata, fp_func)
    _render_market_cache_tools(market_cache, edata)

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
            new_est_price = c3.text_input("Prix demandé (€)", value="", placeholder="Non renseigné")
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
                    "seller_price": parse_float_input_func(new_est_price, 0.0) if str(new_est_price or "").strip() else 0.0,
                        "listing_url": new_est_url.strip(),
                        "listing_image_url": fetch_listing_preview_image_func(new_est_url) if new_est_url.strip() else "",
                        "status": "À analyser",
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
    status_counts = {status: 0 for status in _ESTIMATION_STATUS_OPTIONS}
    for estimate in estimates:
        status_counts[_estimation_tracking_status(estimate)] = status_counts.get(_estimation_tracking_status(estimate), 0) + 1
    st.caption(
        " · ".join(
            part
            for part in [
                f"{status_counts.get('En négociation', 0)} négociations en cours",
                f"{status_counts.get('Offre envoyée', 0)} offres envoyées",
                f"{status_counts.get('À analyser', 0)} lots à analyser",
            ]
            if not part.startswith("0 ")
        )
        or "Aucun statut actif à signaler"
    )
    _render_estimations_comparison(opportunities, fp_func, normalize_name_func)

    f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
    search = f1.text_input("Rechercher une estimation", placeholder="Nom, carte, source...", key="est_box_search")
    status_filter = f2.selectbox("Intérêt", ["Tous", "Très intéressant", "Intéressant", "Correct", "Trop cher", "À vérifier"], key="est_box_status_filter")
    workflow_filter = f3.selectbox("Statut", ["Tous", *_ESTIMATION_STATUS_OPTIONS], key="est_box_workflow_filter")
    max_budget_raw = f4.text_input("Budget max (€)", value="", placeholder="Ex: 120", key="est_box_budget")
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
        if workflow_filter != "Tous" and _estimation_tracking_status(estimate) != workflow_filter:
            continue
        if max_budget > 0 and _explicit_seller_price(estimate) > max_budget:
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
                market_cache=market_cache,
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
    market_cache=None,
):
    label, _ = _opportunity_label(totals)
    market_cache = market_cache or {}
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
            {_kpi("Prix demandé", _seller_price_label(estimate, fp_func), accent="price")}
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

    with st.form(f"est_workflow_status_form_{uid}"):
        s1, s2 = st.columns([2, 1])
        current_status = _estimation_tracking_status(estimate)
        new_status = s1.selectbox(
            "Statut de suivi",
            _ESTIMATION_STATUS_OPTIONS,
            index=_ESTIMATION_STATUS_OPTIONS.index(current_status) if current_status in _ESTIMATION_STATUS_OPTIONS else 0,
            key=f"est_workflow_status_{uid}",
        )
        saved = s2.form_submit_button("Mettre à jour le statut", width="stretch")
        if saved and new_status != current_status:
            estimate["workflow_status"] = new_status
            estimate["status"] = new_status
            save_estimations_func(edata)
            print(f'[Estimations Status] estimate="{estimate.get("name", "Estimation")}" status="{new_status}"', flush=True)
            st.rerun()

    if st.button("Actualiser les cotes de cette estimation", key=f"refresh_market_prices_{uid}", width="stretch"):
        updated_cache, refresh_summary = refresh_estimation_prices(market_cache, estimate, only_due=True)
        save_market_price_cache(updated_cache)
        st.session_state["market_price_cache"] = updated_cache
        save_estimations_func(edata)
        print(
            "[Market Price Cache] "
            f'refresh requested estimate="{estimate.get("name", "Estimation")}" '
            f"refreshed={refresh_summary.get('refreshed', 0)} "
            f"recent_kept={refresh_summary.get('recent_kept', 0)} "
            f"review={refresh_summary.get('review', 0)} "
            f"unavailable={refresh_summary.get('unavailable', 0)} "
            f"manual_preserved={refresh_summary.get('manual_preserved', 0)}",
            flush=True,
        )
        st.success(
            "Cotes actualisées : "
            f"{refresh_summary.get('refreshed', 0)} · "
            f"récentes conservées : {refresh_summary.get('recent_kept', 0)} · "
            f"à vérifier : {refresh_summary.get('review', 0)} · "
            f"sans cote fiable : {refresh_summary.get('unavailable', 0)} · "
            f"manuelles conservées : {refresh_summary.get('manual_preserved', 0)}"
        )
        st.rerun()

    with st.expander("Ajouter une carte dans cette estimation", expanded=not estimate.get("cards")):
        name_key = f"est_add_name_keyup_{uid}"
        number_key = f"est_add_number_box_{uid}"
        qty_key = f"est_add_qty_box_{uid}"
        condition_key = f"est_add_condition_box_{uid}"
        special_key = f"est_add_special_box_{uid}"
        note_key = f"est_add_note_box_{uid}"
        lang_key = f"est_add_japanese_mode_{uid}"
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
            previous_values = st.session_state.get("__previous_values__")
            if isinstance(previous_values, dict):
                previous_values.pop(name_key, None)
                previous_values.pop(name_component_state_key, None)
            st.session_state.pop(f"est_add_name_fallback_{uid}", None)
            st.session_state[number_key] = ""
            st.session_state[qty_key] = "1"
            st.session_state[condition_key] = "NM"
            st.session_state[special_key] = []
            st.session_state[note_key] = ""
            st.session_state.pop(f"est_selected_match_{uid}", None)
            st.session_state.pop(f"est_selected_details_{uid}", None)
            _log_once(
                "form_reset",
                f'{uid}|{estimate.get("name", "Estimation")}',
                f'[Estimations Form Reset] estimate="{estimate.get("name", "Estimation")}" applied=yes',
            )
        if qty_key not in st.session_state:
            st.session_state[qty_key] = "1"
        if lang_key not in st.session_state:
            st.session_state[lang_key] = False
        _render_duplicate_pending(uid, estimate, edata, save_estimations_func, add_estimation_card_func, pending_reset_key)
        try:
            card_name = st_keyup(
                "Nom / Rechercher une carte",
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
            card_name = st.text_input("Nom / Rechercher une carte", value="", key=f"est_add_name_fallback_{uid}", placeholder=name_placeholder)
        jp_mode = st.checkbox(
            "Cartes japonaises",
            key=lang_key,
            help="Cherche dans les cartes japonaises du cache, avec images et liens Cardmarket japonais quand les données existent.",
        )
        search_language = "ja" if jp_mode else "fr"
        if jp_mode:
            jp_cache = _ensure_japanese_cards_cache(normalize_name_func)
            if jp_cache.get("loaded"):
                st.caption(f"Mode japonais : {jp_cache.get('count', 0)} cartes JP indexées, sans mélange avec les résultats FR.")
            else:
                st.caption("Mode japonais : cache JP indisponible pour le moment, aucune bascule automatique vers les cartes FR.")
        a2, a4 = st.columns([1, 0.7])
        card_number = a2.text_input("Numéro", placeholder="199/165", key=number_key)
        card_qty = a4.text_input("Qté", key=qty_key)

        search_context = _search_context(card_name, normalize_name_func)
        suggestions = _card_suggestions(card_name, card_number, search_in_cache_func, ecd_func, normalize_name_func, language=search_language)
        enrichment_notice_key = f"est_cache_enrichment_notice_{uid}"
        if st.session_state.get(enrichment_notice_key):
            st.caption(st.session_state.pop(enrichment_notice_key))
        if suggestions:
            st.caption("Suggestions depuis le cache cartes PokéStock · " + ("Japonais" if search_language == "ja" else "Français"))
            suggestion_render_started = time.perf_counter()
            if _suggestions_missing_set_match(card_name, suggestions, normalize_name_func):
                st.caption("Aucun match exact pour ce tag de série dans le cache. Résultats proches affichés.")
            if _suggestions_missing_type_match(card_name, suggestions, "ar", normalize_name_func):
                st.caption("Aucune AR exacte trouvée dans le cache. Résultats proches affichés.")
            if _suggestions_missing_type_match(card_name, suggestions, "rainbow", normalize_name_func):
                st.caption("Aucune carte Rainbow exacte trouvée dans le cache. Résultats proches affichés.")
            exact_suggestions, close_suggestions, strict_types = _strict_suggestion_sections(card_name, suggestions[:8], normalize_name_func)
            suggestion_sections = []
            if strict_types and exact_suggestions:
                suggestion_sections.append(("", exact_suggestions))
                if close_suggestions:
                    suggestion_sections.append(("Résultats proches", close_suggestions))
            else:
                suggestion_sections.append(("", suggestions[:8]))
            cols_per_row = 1 if is_mobile_mode_func() else 6
            suggestion_offset = 0
            suggestion_image_hits = 0
            suggestion_image_misses = 0
            for section_title, section_suggestions in suggestion_sections:
                if section_title:
                    st.caption(section_title)
                for row_start in range(0, len(section_suggestions), cols_per_row):
                    cols = st.columns(cols_per_row)
                    for cidx, suggestion in enumerate(section_suggestions[row_start : row_start + cols_per_row]):
                        enriched = suggestion["card"]
                        button_ix = suggestion_offset + row_start + cidx
                        with cols[cidx]:
                            if _render_suggestion_card(enriched, proxy_img_func=proxy_img_func):
                                suggestion_image_hits += 1
                            else:
                                suggestion_image_misses += 1
                            if st.button("Choisir", key=f"est_suggestion_pick_{uid}_{button_ix}", width="stretch"):
                                action_started = time.perf_counter()
                                details = _selected_card_details(enriched)
                                _perf_log_once(
                                    "choose",
                                    f'{uid}|{details.get("id","")}|{details.get("number","")}',
                                    f'[Estimations Perf] choose card="{details.get("name", "")}" image_ready={"yes" if details.get("image_url") or details.get("image_url_en") or details.get("image_url_ja") else "no"} total_ms={int((time.perf_counter() - action_started) * 1000)}',
                                )
                                details["lang"] = search_language
                                details["language"] = search_language
                                if search_language == "ja" and "Japonaise" not in str(details.get("special") or ""):
                                    details["special"] = ", ".join(x for x in [details.get("special", ""), "Japonaise"] if str(x or "").strip())
                                direct_specials = st.session_state.get(special_key, [])
                                if not isinstance(direct_specials, list):
                                    direct_specials = []
                                direct_clean_specials = [tag for tag in direct_specials if tag != "Collection"]
                                if search_language == "ja" and "Japonaise" not in direct_clean_specials:
                                    direct_clean_specials.append("Japonaise")
                                add_params = {
                                    "name": details.get("name") or card_name,
                                    "number": details.get("number") or card_number,
                                    "cote": "0,00",
                                    "qty": st.session_state.get(qty_key, "1"),
                                    "condition": st.session_state.get(condition_key, "NM") or "NM",
                                    "specials": direct_clean_specials,
                                    "note": st.session_state.get(note_key, ""),
                                    "is_collection": "Collection" in direct_specials,
                                }
                                candidate = {
                                    **details,
                                    "condition": add_params["condition"],
                                    "special": ", ".join(direct_clean_specials),
                                }
                                duplicate = _find_duplicate_card(estimate, candidate, normalize_name_func)
                                if duplicate:
                                    _store_duplicate_pending(uid, duplicate, {"params": add_params, "details": details, "match": suggestion["match"]})
                                    st.rerun()
                                before_count = len(estimate.get("cards", []) or [])
                                _mark_estimation_needs_review(estimate)
                                _log_once(
                                    "estimation_pick",
                                    f'{uid}|{details.get("id","")}|{details.get("number","")}',
                                    "[Estimations Pick] "
                                    f'selected="{details.get("name", "")}" number="{details.get("number", "")}" '
                                    f'set="{details.get("set", "")}" rarity="{details.get("rarity", "")}" '
                                    f'image={"yes" if details.get("image_url") or details.get("image_url_en") or details.get("image_url_ja") else "no"} '
                                    f'language="{search_language}" '
                                    f'exact_cm={"yes" if _exact_cardmarket_url(details) else "no"}',
                                )
                                add_estimation_card_func(
                                    estimate,
                                    add_params["name"],
                                    add_params["number"],
                                    add_params["cote"],
                                    add_params["qty"],
                                    add_params["condition"],
                                    add_params["specials"],
                                    add_params["note"],
                                    add_params["is_collection"],
                                    suggestion["match"],
                                )
                                _apply_selected_card_details(estimate, details)
                                after_count = len(estimate.get("cards", []) or [])
                                if after_count > before_count and estimate.get("cards"):
                                    added_card = estimate["cards"][-1]
                                    _apply_market_price_suggestion(added_card, market_cache)
                                    _log_once(
                                        "estimation_add",
                                        f'{uid}|{added_card.get("uid","")}|suggestion',
                                        "[Estimations Add] "
                                        f'added="{added_card.get("name", "")}" number="{added_card.get("number", "")}" '
                                        f'image={"yes" if added_card.get("image_url") or added_card.get("image_url_en") or added_card.get("image_url_ja") else "no"} '
                                        f'language="{_card_language(added_card)}" '
                                        f'estimate="{estimate.get("name", "")}"',
                                    )
                                else:
                                    _log_once(
                                        "estimation_add_failed",
                                        f'{uid}|suggestion|{details.get("name","")}|{details.get("number","")}',
                                        "[Estimations Add] failed "
                                        f'reason="suggestion not appended" name="{details.get("name", "")}" '
                                        f'number="{details.get("number", "")}" estimate="{estimate.get("name", "")}"',
                                    )
                                save_started = time.perf_counter()
                                save_estimations_func(edata)
                                save_ms = int((time.perf_counter() - save_started) * 1000)
                                _perf_log_once(
                                    "add",
                                    f'{uid}|suggestion|{details.get("id","")}|{details.get("number","")}',
                                    f'[Estimations Perf] add card="{details.get("name", "")}" lang={search_language} local_save_ms={save_ms} cloud_ms=unknown total_ms={int((time.perf_counter() - action_started) * 1000)}',
                                )
                                st.session_state.pop(f"pending_est_choice_{uid}", None)
                                st.session_state.pop(f"est_selected_match_{uid}", None)
                                st.session_state.pop(f"est_selected_details_{uid}", None)
                                if after_count > before_count:
                                    st.session_state[pending_reset_key] = True
                                st.rerun()
                suggestion_offset += len(section_suggestions)
            _perf_log_once(
                "suggestions_render",
                f'{search_language}|{normalize_name_func(card_name)}|{len(suggestions)}',
                f'[Estimations Perf] suggestions_render query="{card_name}" lang={search_language} count={min(len(suggestions), 8)} render_ms={int((time.perf_counter() - suggestion_render_started) * 1000)}',
            )
            _perf_log_once(
                "suggestion_images",
                f'{search_language}|{normalize_name_func(card_name)}|{suggestion_image_hits}|{suggestion_image_misses}',
                f'[Estimations Perf] suggestion_images visible={suggestion_image_hits + suggestion_image_misses} cache_hits={suggestion_image_hits} cache_misses={suggestion_image_misses} images_ready_ms={int((time.perf_counter() - suggestion_render_started) * 1000)} elapsed_ms={int((time.perf_counter() - suggestion_render_started) * 1000)}',
            )
        elif str(card_name or "").strip():
            if _shiny_filter_requested(search_context.get("requested_set_tags")):
                st.caption("Aucune carte Shiny / PAF correspondante trouvée dans le cache.")
            elif len(str(card_name or "").strip()) >= 3:
                st.caption("Aucun résultat fiable dans le cache pour cette recherche.")
        can_enrich_cache = (
            cache_enrichment_func
            and search_language == "fr"
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
                refreshed = _card_suggestions(card_name, card_number, search_in_cache_func, ecd_func, normalize_name_func, language=search_language)
                exact_after = _has_exact_search_match(card_name, refreshed, normalize_name_func)
                print(
                    "[Estimations Cache Enrichment] "
                    f'source="{",".join(result.get("sources", []))}" fetched={result.get("fetched", 0)} '
                    f'existing={result.get("existing", 0)} pocket_filtered={result.get("pocket_filtered", 0)} '
                    f'invalid={result.get("invalid", 0)} added={result.get("added", 0)} '
                    f'updated={result.get("updated", 0)} persisted={"yes" if result.get("persisted") else "no"} '
                    f'exact_match_after_refresh={"yes" if exact_after else "no"}',
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
            action_started = time.perf_counter()
            if not card_name.strip():
                st.error("Nom requis.")
            else:
                manual_match_status, manual_candidates = _manual_add_exact_match(card_name, card_number, normalize_name_func, language=search_language)
                if manual_match_status == "ambiguous":
                    _log_once(
                        "manual_add",
                        f'{uid}|ambiguous|{card_name}|{card_number}|{len(manual_candidates)}',
                        "[Estimations Manual Add] "
                        f'name="{card_name}" number="{card_number}" match=ambiguous candidates={len(manual_candidates)} image=no',
                    )
                    st.info("Plusieurs cartes correspondent : utilise Choisir pour sélectionner la bonne.")
                else:
                    matches = [manual_candidates[0]["match"]] if manual_match_status == "exact" else []
                    selected_details = _selected_card_details(manual_candidates[0]["card"]) if manual_match_status == "exact" else None
                    if selected_details:
                        selected_details["lang"] = search_language
                        selected_details["language"] = search_language
                        if search_language == "ja" and "Japonaise" not in str(selected_details.get("special") or ""):
                            selected_details["special"] = ", ".join(x for x in [selected_details.get("special", ""), "Japonaise"] if str(x or "").strip())
                    elif search_language == "ja":
                        selected_details = {"lang": "ja", "language": "ja", "special": "Japonaise"}
                    manual_specials = list(clean_specials)
                    if search_language == "ja" and "Japonaise" not in manual_specials:
                        manual_specials.append("Japonaise")
                    add_params = {
                        "name": selected_details.get("name", card_name) if selected_details else card_name,
                        "number": selected_details.get("number", card_number) if selected_details else card_number,
                        "cote": "0,00",
                        "qty": card_qty,
                        "condition": card_condition,
                        "specials": manual_specials,
                        "note": card_note,
                        "is_collection": keep_collection,
                    }
                    candidate = {
                        **(selected_details or {}),
                        "name": add_params["name"],
                        "number": add_params["number"],
                        "condition": card_condition,
                        "special": ", ".join(manual_specials),
                    }
                    duplicate = _find_duplicate_card(estimate, candidate, normalize_name_func)
                    if duplicate:
                        _store_duplicate_pending(uid, duplicate, {"params": add_params, "details": selected_details, "match": matches[0] if matches else None})
                        st.rerun()
                    before_count = len(estimate.get("cards", []) or [])
                    _mark_estimation_needs_review(estimate)
                    add_estimation_card_func(
                        estimate,
                        add_params["name"],
                        add_params["number"],
                        add_params["cote"],
                        add_params["qty"],
                        add_params["condition"],
                        add_params["specials"],
                        add_params["note"],
                        add_params["is_collection"],
                        None,
                    )
                    _apply_selected_card_details(estimate, selected_details)
                    after_count = len(estimate.get("cards", []) or [])
                    image_status = "yes" if selected_details and (selected_details.get("image_url") or selected_details.get("image_url_en") or selected_details.get("image_url_ja")) else "no"
                    _log_once(
                        "manual_add",
                        f'{uid}|{manual_match_status}|{card_name}|{card_number}|{image_status}',
                        "[Estimations Manual Add] "
                        f'name="{card_name}" number="{card_number}" match={manual_match_status} language="{search_language}" image={image_status}',
                    )
                    if after_count > before_count and estimate.get("cards"):
                        added_card = estimate["cards"][-1]
                        _apply_market_price_suggestion(added_card, market_cache)
                        _log_once(
                            "estimation_add",
                            f'{uid}|{added_card.get("uid","")}|manual',
                            "[Estimations Add] "
                            f'added="{added_card.get("name", "")}" number="{added_card.get("number", "")}" '
                            f'image={"yes" if added_card.get("image_url") or added_card.get("image_url_en") or added_card.get("image_url_ja") else "no"} '
                            f'language="{_card_language(added_card)}" '
                            f'estimate="{estimate.get("name", "")}"',
                        )
                    else:
                        _log_once(
                            "estimation_add_failed",
                            f'{uid}|manual|{card_name}|{card_number}',
                            "[Estimations Add] failed "
                            f'reason="card not appended" name="{card_name}" number="{card_number}" '
                            f'estimate="{estimate.get("name", "")}"',
                        )
                    st.session_state.pop(f"est_selected_match_{uid}", None)
                    st.session_state.pop(f"est_selected_details_{uid}", None)
                    if after_count > before_count:
                        st.session_state[pending_reset_key] = True
                    save_started = time.perf_counter()
                    save_estimations_func(edata)
                    save_ms = int((time.perf_counter() - save_started) * 1000)
                    _perf_log_once(
                        "add",
                        f'{uid}|manual|{card_name}|{card_number}|{manual_match_status}',
                        f'[Estimations Perf] add card="{card_name}" lang={search_language} local_save_ms={save_ms} cloud_ms=unknown total_ms={int((time.perf_counter() - action_started) * 1000)}',
                    )
                    st.rerun()

    with st.expander("EX / V basiques", expanded=False):
        st.caption("Prix fixes : achat 0,50 € / carte · revente prévue 2,00 € / carte.")
        ex_key = f"quick_bulk_ex_qty_{uid}"
        v_key = f"quick_bulk_v_qty_{uid}"
        reset_key = f"quick_bulk_reset_{uid}"
        if st.session_state.pop(reset_key, False):
            st.session_state[ex_key] = 0
            st.session_state[v_key] = 0
        if ex_key not in st.session_state:
            st.session_state[ex_key] = 0
        if v_key not in st.session_state:
            st.session_state[v_key] = 0
        c1, c2 = st.columns(2)
        ex_qty = c1.number_input("Nombre d’EX basiques", min_value=0, step=1, key=ex_key)
        v_qty = c2.number_input("Nombre de V basiques", min_value=0, step=1, key=v_key)
        if st.button("Ajouter les EX / V basiques", key=f"quick_bulk_add_{uid}", width="stretch"):
            added = 0
            if int(ex_qty or 0) > 0:
                _mark_estimation_needs_review(estimate)
                estimate.setdefault("cards", []).append(_new_quick_bulk_entry("ex", int(ex_qty), new_uid_func))
                added += 1
            if int(v_qty or 0) > 0:
                _mark_estimation_needs_review(estimate)
                estimate.setdefault("cards", []).append(_new_quick_bulk_entry("v", int(v_qty), new_uid_func))
                added += 1
            if added:
                save_estimations_func(edata)
                st.session_state[reset_key] = True
                st.success("Lignes EX / V basiques ajoutées.")
                st.rerun()
            else:
                st.info("Aucune ligne créée : les deux quantités sont à 0.")

    pending = st.session_state.get(f"pending_est_choice_{uid}")
    if pending:
        pending_language = "ja" if str(pending.get("language") or pending.get("lang") or "fr").lower() in {"ja", "jp", "jpn"} else "fr"
        st.warning(f"{len(pending.get('matches', []))} cartes possibles trouvées. Choisis la bonne.")
        cols = st.columns(2 if is_mobile_mode_func() else 4)
        for pidx, match in enumerate(pending.get("matches", [])):
            card_dict, set_name = match
            enriched = ecd_func(card_dict, set_name, lang=pending_language)
            enriched["lang"] = pending_language
            enriched["language"] = pending_language
            if not enriched.get("image_url"):
                rebuilt = _tcgdex_image_from_id(enriched.get("id"), enriched.get("number"), lang=pending_language)
                if pending_language == "ja":
                    enriched["image_url_ja"] = rebuilt
                else:
                    enriched["image_url"] = rebuilt
            with cols[pidx % len(cols)]:
                pending_image = enriched.get("image_url_ja") or enriched.get("image_url") or ""
                if pending_image:
                    st.markdown(
                        img_with_fallback_func(pending_image, enriched.get("image_url_en", ""), width="100%", style="border-radius:10px;"),
                        unsafe_allow_html=True,
                    )
                st.caption(f"{enriched.get('name','Carte')} · {enriched.get('set','')} · #{enriched.get('number','')}")
                if st.button("Choisir", key=f"pick_est_box_{uid}_{pidx}"):
                    details = _selected_card_details(enriched)
                    details["lang"] = pending_language
                    details["language"] = pending_language
                    if pending_language == "ja" and "Japonaise" not in str(details.get("special") or ""):
                        details["special"] = ", ".join(x for x in [details.get("special", ""), "Japonaise"] if str(x or "").strip())
                    _log_once(
                        "estimation_pick",
                        f'{uid}|pending|{details.get("id","")}|{details.get("number","")}',
                        "[Estimations Pick] "
                        f'selected="{details.get("name", "")}" number="{details.get("number", "")}" '
                        f'set="{details.get("set", "")}" rarity="{details.get("rarity", "")}" '
                        f'image={"yes" if details.get("image_url") or details.get("image_url_en") or details.get("image_url_ja") else "no"} '
                        f'language="{pending_language}" '
                        f'exact_cm={"yes" if _exact_cardmarket_url(details) else "no"}',
                    )
                    before_count = len(estimate.get("cards", []) or [])
                    _mark_estimation_needs_review(estimate)
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
                        _apply_market_price_suggestion(added_card, market_cache)
                        _log_once(
                            "estimation_add",
                            f'{uid}|{added_card.get("uid","")}|pending',
                            "[Estimations Add] "
                            f'added="{added_card.get("name", "")}" number="{added_card.get("number", "")}" '
                            f'image={"yes" if added_card.get("image_url") or added_card.get("image_url_en") else "no"} '
                            f'estimate="{estimate.get("name", "")}"',
                        )
                    else:
                        _log_once(
                            "estimation_add_failed",
                            f'{uid}|pending|{pending.get("name","")}|{pending.get("number","")}',
                            "[Estimations Add] failed "
                            f'reason="card not appended from choice" name="{pending.get("name", "")}" '
                            f'number="{pending.get("number", "")}" estimate="{estimate.get("name", "")}"',
                        )
                    save_estimations_func(edata)
                    st.session_state.pop(f"pending_est_choice_{uid}", None)
                    if after_count > before_count:
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
        mobile_mode = is_mobile_mode_func()
        display_limit_key = f"est_visible_card_limit_{uid}"
        default_limit = 24 if mobile_mode else 48
        if display_limit_key not in st.session_state:
            st.session_state[display_limit_key] = default_limit
        if internal_query:
            render_cards = visible_cards[: max(st.session_state.get(display_limit_key, default_limit), default_limit)]
        else:
            render_cards = visible_cards[: max(st.session_state.get(display_limit_key, default_limit), default_limit)]
        st.caption(f"{len(render_cards)} cartes affichées sur {len(visible_cards)} résultat(s) · {len(cards)} carte(s) dans l’estimation")
        missing_image_cards = _cards_missing_estimation_image(cards)
        repair_notice_key = f"est_image_repair_notice_{uid}"
        if st.session_state.get(repair_notice_key):
            st.caption(st.session_state.pop(repair_notice_key))
        if missing_image_cards:
            if st.button("Réparer les images manquantes", key=f"est_repair_missing_images_{uid}", width="stretch"):
                repair_result = _repair_missing_estimation_images(estimate, normalize_name_func, cache_enrichment_func)
                if repair_result.get("repaired", 0) > 0 or repair_result.get("invalid_refs", 0) > 0:
                    save_estimations_func(edata)
                st.session_state[repair_notice_key] = (
                    f"Images réparées : {repair_result.get('repaired', 0)} / {repair_result.get('missing', 0)}."
                )
                st.rerun()
        cols_per_row = 1 if mobile_mode else 6
        tracked_render_started = time.perf_counter()
        for row_start in range(0, len(render_cards), cols_per_row):
            cols = st.columns(cols_per_row)
            for cidx, card in enumerate(render_cards[row_start : row_start + cols_per_row]):
                with cols[cidx]:
                    if _is_quick_bulk_entry(card):
                        card_uid = card.get("uid") or f"bulk_{row_start}_{cidx}"
                        _render_quick_bulk_card(card, fp_func)
                        if st.button("Retirer", key=f"del_est_quick_bulk_{uid}_{card_uid}", width="stretch"):
                            _mark_estimation_needs_review(estimate)
                            estimate["cards"] = [c for c in estimate.get("cards", []) if c.get("uid") != card.get("uid")]
                            save_estimations_func(edata)
                            st.rerun()
                        continue
                    card_meta = _render_tracked_card(
                        card,
                        estimate,
                        fp_func,
                        img_with_fallback_func,
                        cardmarket_search_url_func,
                        normalize_name_func,
                        proxy_img_func=proxy_img_func,
                        market_cache=market_cache,
                    )
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
                        st.markdown(f"**{str(card.get('name') or 'Carte')}**")
                        if card_meta.get("tags"):
                            st.caption(card_meta["tags"])
                        badge_parts = list(card_meta.get("badges", []) or [])
                        if card_meta.get("market_badge_label"):
                            badge_parts.append(card_meta["market_badge_label"])
                        if badge_parts:
                            st.caption(" · ".join(str(part) for part in badge_parts if part))
                        current_qty = _safe_int(card.get("quantity"))
                        edited_qty = st.number_input("Qté", min_value=1, value=current_qty, step=1, key=qty_edit_key)
                        previous_qty_seen = st.session_state.get(qty_seen_key)
                        st.session_state[qty_seen_key] = int(edited_qty)
                        if previous_qty_seen is not None and int(edited_qty) != previous_qty_seen and int(edited_qty) != current_qty:
                            print(
                                f'[Estimations Quantity] card="{card.get("name", "Carte")}" old={current_qty} new={int(edited_qty)}',
                                flush=True,
                            )
                            _mark_estimation_needs_review(estimate)
                            card["quantity"] = int(edited_qty)
                            save_estimations_func(edata)
                            st.rerun()
                        cote_state_class = html.escape(str(card_meta.get("market_badge_css") or "none"), quote=True)
                        st.markdown(f'<span class="est-card-cote-marker cote-{cote_state_class}"></span>', unsafe_allow_html=True)
                        cote_text = st.text_input("Cote (€)", key=cote_key, placeholder="0,00")
                        new_cote = 0.0 if not str(cote_text or "").strip() else max(parse_float_input_func(cote_text, current_cote), 0.0)
                        previous_cote_seen = st.session_state.get(cote_seen_key)
                        st.session_state[cote_seen_key] = str(cote_text or "")
                        if previous_cote_seen is not None and str(cote_text or "") != previous_cote_seen and abs(new_cote - current_cote) > 0.009:
                            _mark_estimation_needs_review(estimate)
                            card["cote"] = new_cote
                            mark_manual_price(card, new_cote)
                            if new_cote > 0:
                                upsert_market_price(
                                    market_cache,
                                    card,
                                    new_cote,
                                    origin="manual_estimation",
                                    source=f"Estimation · {estimate.get('name', 'sans nom')}",
                                    confidence="saisie manuelle",
                                )
                                save_market_price_cache(market_cache)
                                st.session_state["market_price_cache"] = market_cache
                            save_estimations_func(edata)
                            st.rerun()
                        auto_price = _safe_float(card.get("auto_price"))
                        if auto_price > 0 and card.get("market_price_origin") in {"manual", "legacy_manual"}:
                            if st.button("Utiliser la cote auto", key=f"use_auto_price_{uid}_{card_uid}", width="stretch"):
                                _mark_estimation_needs_review(estimate)
                                card["cote"] = auto_price
                                card["market_price_origin"] = "auto"
                                card.pop("manual_price", None)
                                st.session_state[cote_key] = f"{auto_price:.2f}".replace(".", ",")
                                save_estimations_func(edata)
                                st.rerun()
                        if st.button("Actualiser la cote", key=f"refresh_market_card_{uid}_{card_uid}", width="stretch"):
                            result = apply_market_price_to_card(card, market_cache)
                            if result.get("applied"):
                                st.session_state[cote_key] = f"{_safe_float(card.get('cote')):.2f}".replace(".", ",")
                                save_estimations_func(edata)
                                st.success("Cote actualisée depuis la mémoire.")
                            elif result.get("reason") == "manual_preserved":
                                save_estimations_func(edata)
                                st.info("Cote manuelle conservée. Utilise le bouton dédié pour appliquer la cote auto.")
                            else:
                                st.info("Aucune cote automatique suffisamment fiable.")
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
                                    _mark_estimation_needs_review(estimate)
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
                                            _mark_estimation_needs_review(estimate)
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
                                        _mark_estimation_needs_review(estimate)
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
                            _mark_estimation_needs_review(estimate)
                            estimate["cards"] = [c for c in estimate.get("cards", []) if c.get("uid") != card.get("uid")]
                            save_estimations_func(edata)
                            st.rerun()
        _perf_log_once(
            "tracked_cards",
            f'{uid}|{len(render_cards)}|{len(visible_cards)}|{normalize_name_func(internal_query)}',
            f'[Estimations Perf] tracked_cards count={len(render_cards)} total={len(visible_cards)} render_ms={int((time.perf_counter() - tracked_render_started) * 1000)}',
        )
        if len(render_cards) < len(visible_cards):
            more_step = 24 if mobile_mode else 48
            if st.button(
                f"Afficher plus ({len(visible_cards) - len(render_cards)} restantes)",
                key=f"est_show_more_cards_{uid}",
                width="stretch",
            ):
                st.session_state[display_limit_key] = len(render_cards) + more_step
                st.rerun()

    _render_finish_estimation_panel(
        estimate,
        totals,
        uid,
        edata,
        save_estimations_func,
        fp_func,
        normalize_name_func,
        parse_float_input_func,
    )

    with st.expander("Détails avancés et actions", expanded=False):
        if estimate.get("listing_url"):
            safe_url = html.escape(estimate.get("listing_url", ""), quote=True)
            st.markdown(f'<a href="{safe_url}" target="_blank">Ouvrir l’annonce</a>', unsafe_allow_html=True)
        with st.form(f"estimate_meta_box_{uid}"):
            m1, m2, m3 = st.columns([2, 1, 1])
            edit_name = m1.text_input("Nom", value=estimate.get("name", ""), key=f"est_name_box_{uid}")
            source_names = list(settings.get("sources", {}).keys()) or ["Vinted"]
            edit_source = m2.selectbox("Type", source_names, index=source_names.index(estimate.get("source")) if estimate.get("source") in source_names else 0, key=f"est_source_box_{uid}")
            status_options = _ESTIMATION_STATUS_OPTIONS
            current_edit_status = _estimation_tracking_status(estimate)
            edit_status = m3.selectbox("Statut", status_options, index=status_options.index(current_edit_status) if current_edit_status in status_options else 0, key=f"est_status_box_{uid}")
            n1, n2, n3 = st.columns([1, 1, 2])
            current_seller_price = _explicit_seller_price(estimate)
            edit_seller_price = n1.text_input(
                "Prix demandé (€)",
                value=f"{current_seller_price:.2f}".replace(".", ",") if current_seller_price > 0 else "",
                placeholder="Non renseigné",
                key=f"est_seller_box_{uid}",
            )
            edit_safety = n2.text_input("Marge sécurité (€)", value=f"{float(estimate.get('safety_eur', 0.0) or 0.0):.2f}".replace(".", ","), key=f"est_safety_box_{uid}")
            edit_url = n3.text_input("URL annonce", value=estimate.get("listing_url", ""), key=f"est_url_box_{uid}")
            if st.form_submit_button("Sauvegarder les détails"):
                old_url = estimate.get("listing_url", "")
                estimate["name"] = edit_name.strip() or estimate.get("name", "Estimation")
                estimate["source"] = edit_source
                estimate["status"] = edit_status
                estimate["workflow_status"] = edit_status
                parsed_seller_price = parse_float_input_func(edit_seller_price, 0.0) if str(edit_seller_price or "").strip() else 0.0
                estimate["seller_price"] = parsed_seller_price if parsed_seller_price > 0 else 0.0
                estimate["fees"] = 0.0
                estimate["safety_eur"] = parse_float_input_func(edit_safety, 0.0)
                estimate["listing_url"] = edit_url.strip()
                if estimate["listing_url"] and (estimate["listing_url"] != old_url or not estimate.get("listing_image_url")):
                    estimate["listing_image_url"] = fetch_listing_preview_image_func(estimate["listing_url"])
                save_estimations_func(edata)
                st.rerun()
            if current_seller_price > 0:
                clear_seller_price = st.checkbox("Confirmer l’effacement du prix demandé", key=f"est_clear_seller_confirm_{uid}")
                if st.form_submit_button("Effacer le prix demandé", disabled=not clear_seller_price):
                    estimate["seller_price"] = 0.0
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
        real_lot_cards = [card for card in estimate.get("cards", []) or [] if not _is_quick_bulk_entry(card)]
        if action_cols[0].button("Créer un vrai lot", width="stretch", disabled=not real_lot_cards or bool(estimate.get("created_lot_uid")), key=f"create_real_lot_box_{uid}"):
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
            for card in real_lot_cards:
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
            estimate["workflow_status"] = "Achetée"
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


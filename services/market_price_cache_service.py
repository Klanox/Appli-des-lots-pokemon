"""Separate market reference cache for estimation cards.

This module never updates stock prices. It stores reference values outside
business JSON files and only writes after an explicit user action.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import unicodedata

from cloud import (
    SUPABASE_MARKET_PRICE_CACHE_KEY,
    cloud_sync_enabled,
    load_cloud_json,
    save_cloud_json,
)
from utils import APP_DIR, safe_write_json


MARKET_PRICE_CACHE_FILE = os.path.join(APP_DIR, "estimation_market_price_cache.json")
MARKET_ALERT_DEFAULT_MIN_PCT = 15.0
MARKET_ALERT_DEFAULT_MIN_EUR = 3.0


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _fold(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace(",", ".").strip()
            if not value:
                return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def empty_market_cache():
    return {
        "version": 1,
        "entries": {},
        "settings": {
            "alert_min_pct": MARKET_ALERT_DEFAULT_MIN_PCT,
            "alert_min_eur": MARKET_ALERT_DEFAULT_MIN_EUR,
        },
        "last_import_at": "",
        "last_refresh_at": "",
    }


def normalize_market_cache(data):
    if not isinstance(data, dict):
        data = empty_market_cache()
    data.setdefault("version", 1)
    data.setdefault("entries", {})
    if not isinstance(data["entries"], dict):
        data["entries"] = {}
    data.setdefault("settings", {})
    data["settings"].setdefault("alert_min_pct", MARKET_ALERT_DEFAULT_MIN_PCT)
    data["settings"].setdefault("alert_min_eur", MARKET_ALERT_DEFAULT_MIN_EUR)
    data.setdefault("last_import_at", "")
    data.setdefault("last_refresh_at", "")
    return data


def load_market_price_cache():
    cloud_data = load_cloud_json(SUPABASE_MARKET_PRICE_CACHE_KEY) if cloud_sync_enabled() else None
    if isinstance(cloud_data, dict):
        return normalize_market_cache(cloud_data)
    if os.path.exists(MARKET_PRICE_CACHE_FILE):
        try:
            with open(MARKET_PRICE_CACHE_FILE, "r", encoding="utf-8") as f:
                return normalize_market_cache(json.load(f))
        except (OSError, json.JSONDecodeError):
            return empty_market_cache()
    return empty_market_cache()


def save_market_price_cache(cache):
    cache = normalize_market_cache(cache)
    cache["updated_at"] = _now_iso()
    if cloud_sync_enabled() and save_cloud_json(SUPABASE_MARKET_PRICE_CACHE_KEY, cache):
        return {"ok": True, "storage": "cloud"}
    safe_write_json(MARKET_PRICE_CACHE_FILE, cache, indent=2)
    return {"ok": True, "storage": "local"}


def card_identity(card):
    card = card or {}
    specials = " ".join(
        str(card.get(key) or "")
        for key in (
            "special",
            "special_tag",
            "variant",
            "rarity",
        )
    )
    tags = " ".join(str(tag) for key in ("tags", "metadata_tags", "card_tags") for tag in (card.get(key) or []) if tag)
    return {
        "source_card_id": str(card.get("id") or card.get("card_id") or "").strip(),
        "name": str(card.get("name") or "").strip(),
        "number": str(card.get("number") or card.get("localId") or "").strip().upper().replace(" ", ""),
        "set_id": str(card.get("set_id") or card.get("set_code") or "").strip().upper(),
        "set": str(card.get("set") or card.get("extension") or "").strip(),
        "lang": str(card.get("lang") or card.get("language") or "").strip().lower(),
        "specials": specials.strip(),
        "tags": tags.strip(),
        "is_reverse": bool(card.get("is_reverse") or "reverse" in _fold(specials)),
        "is_holo": bool(card.get("is_holo") or "holo" in _fold(specials)),
        "is_promo": bool(card.get("promo") or "promo" in _fold(f"{specials} {tags}")),
        "is_stamp": bool(card.get("stamp") or "stamp" in _fold(f"{specials} {tags}")),
        "is_ed1": bool(card.get("is_ed1") or "1ere" in _fold(specials) or "1re" in _fold(specials)),
    }


def card_cache_key(card):
    identity = card_identity(card)
    if not identity["name"] or not identity["number"]:
        return ""
    parts = [
        _fold(identity["name"]),
        identity["number"],
        identity["set_id"] or _fold(identity["set"]),
        identity["lang"] or "fr",
        _fold(identity["specials"]),
        "reverse" if identity["is_reverse"] else "normal",
        "holo" if identity["is_holo"] else "nonholo",
        "promo" if identity["is_promo"] else "standard",
        "stamp" if identity["is_stamp"] else "nostamp",
        "ed1" if identity["is_ed1"] else "regular",
    ]
    return "|".join(parts)


def identity_is_sufficient(card):
    identity = card_identity(card)
    return bool(identity["name"] and identity["number"] and (identity["set_id"] or identity["set"] or identity["source_card_id"]))


def _entry_reliability_rank(entry):
    origin = str(entry.get("origin") or "")
    confidence = str(entry.get("confidence") or "")
    if origin == "api_auto" and "fiable" in confidence.lower():
        return 4
    if origin == "api_auto":
        return 3
    if origin in {"manual_estimation", "personal_history"}:
        return 2
    return 1


def _price_history_item(price, source, at=None):
    return {"price": round(float(price), 2), "source": source, "at": at or _now_iso()}


def upsert_market_price(cache, card, price, *, origin, source, confidence, updated_at=None):
    cache = normalize_market_cache(cache)
    price = _safe_float(price)
    key = card_cache_key(card)
    if not key or price <= 0 or not identity_is_sufficient(card):
        return "ignored"
    now = _now_iso()
    identity = card_identity(card)
    existing = cache["entries"].get(key)
    new_entry = {
        **identity,
        "key": key,
        "reference_price": round(price, 2),
        "previous_price": _safe_float(existing.get("reference_price")) if isinstance(existing, dict) else 0.0,
        "origin": origin,
        "price_source": source,
        "confidence": confidence,
        "updated_at": updated_at or now,
        "last_used_at": "",
        "history": [],
    }
    if isinstance(existing, dict):
        if _entry_reliability_rank(existing) > _entry_reliability_rank(new_entry):
            return "preserved"
        history = list(existing.get("history") or [])[-8:]
        old_price = _safe_float(existing.get("reference_price"))
        if old_price > 0:
            history.append(_price_history_item(old_price, existing.get("price_source", "unknown"), existing.get("updated_at") or now))
        new_entry["history"] = history[-10:]
    cache["entries"][key] = new_entry
    return "imported" if existing is None else "updated"


def lookup_market_price(cache, card):
    key = card_cache_key(card)
    if not key:
        return None
    entry = normalize_market_cache(cache).get("entries", {}).get(key)
    if isinstance(entry, dict):
        entry["last_used_at"] = _now_iso()
        return entry
    return None


def _entry_age_days(entry):
    raw = str((entry or {}).get("updated_at") or "")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - dt).days, 0)
    except ValueError:
        return None


def card_is_old_or_condition_sensitive(card):
    blob = _fold(" ".join(str((card or {}).get(key) or "") for key in ("set", "set_id", "special", "rarity", "note")))
    condition = str((card or {}).get("condition") or "").strip().upper()
    return (
        any(token in blob for token in ("wizards", "neo", "jungle", "fossile", "fossil", "rocket", "base set", "set de base", "ex ", "xy"))
        or condition not in {"", "NM", "NEAR MINT"}
    )


def market_price_badge(card, entry=None):
    origin = str((card or {}).get("market_price_origin") or "")
    if origin in {"manual", "legacy_manual"}:
        return "Manuelle" if origin == "manual" else "Manuelle · historique"
    if not entry:
        return "Aucune cote automatique suffisamment fiable."
    if card_is_old_or_condition_sensitive(card):
        return "Référence marché · état à vérifier"
    age = _entry_age_days(entry)
    if age is None:
        return "Historique · non datée"
    if age <= 14:
        return "Auto · récente"
    if age <= 60:
        return "Auto · à vérifier"
    return "Historique · ancienne"


def apply_market_price_to_card(card, cache, *, overwrite_manual=False):
    entry = lookup_market_price(cache, card)
    if not entry:
        return {"applied": False, "reason": "no_reliable_entry", "entry": None}
    origin = str(card.get("market_price_origin") or "")
    if not origin and _safe_float(card.get("cote")) > 0 and not overwrite_manual:
        card["manual_price"] = _safe_float(card.get("cote"))
        card["market_price_origin"] = "legacy_manual"
        card["auto_price"] = _safe_float(entry.get("reference_price"))
        card["market_price_source"] = entry.get("price_source", "")
        card["market_price_confidence"] = entry.get("confidence", "")
        card["auto_price_updated_at"] = entry.get("updated_at", "")
        return {"applied": False, "reason": "manual_preserved", "entry": entry}
    if origin in {"manual", "legacy_manual"} and not overwrite_manual:
        card["auto_price"] = _safe_float(entry.get("reference_price"))
        card["market_price_source"] = entry.get("price_source", "")
        card["market_price_confidence"] = entry.get("confidence", "")
        card["auto_price_updated_at"] = entry.get("updated_at", "")
        return {"applied": False, "reason": "manual_preserved", "entry": entry}
    price = _safe_float(entry.get("reference_price"))
    if price <= 0:
        return {"applied": False, "reason": "invalid_price", "entry": entry}
    card["auto_price"] = price
    card["market_price_source"] = entry.get("price_source", "")
    card["market_price_confidence"] = entry.get("confidence", "")
    card["auto_price_updated_at"] = entry.get("updated_at", "")
    card["market_price_origin"] = "auto"
    card["cote"] = price
    return {"applied": True, "reason": "applied", "entry": entry}


def mark_manual_price(card, price):
    price = _safe_float(price)
    card["manual_price"] = price
    card["market_price_origin"] = "manual" if price > 0 else "none"


def import_estimations_history(cache, estimations_data):
    cache = normalize_market_cache(cache)
    imported = ambiguous = preserved = ignored = 0
    for estimate in (estimations_data or {}).get("estimations", []) or []:
        for card in estimate.get("cards", []) or []:
            price = _safe_float(card.get("cote"))
            if price <= 0:
                ignored += 1
                continue
            if not identity_is_sufficient(card):
                ambiguous += 1
                continue
            result = upsert_market_price(
                cache,
                card,
                price,
                origin="personal_history",
                source=f"Estimation · {estimate.get('name', 'sans nom')}",
                confidence="historique personnel",
                updated_at=card.get("auto_price_updated_at") or estimate.get("created_at") or "",
            )
            if result in {"imported", "updated"}:
                imported += 1
            elif result == "preserved":
                preserved += 1
            else:
                ignored += 1
    cache["last_import_at"] = _now_iso()
    return cache, {
        "imported": imported,
        "ambiguous": ambiguous,
        "preserved": preserved,
        "ignored": ignored,
    }


def refresh_estimation_prices(cache, estimate, *, only_due=True):
    cache = normalize_market_cache(cache)
    summary = {"refreshed": 0, "recent_kept": 0, "review": 0, "unavailable": 0, "manual_preserved": 0}
    for card in estimate.get("cards", []) or []:
        origin = str(card.get("market_price_origin") or "")
        if (not origin and _safe_float(card.get("cote")) > 0) or origin in {"manual", "legacy_manual"}:
            if not origin and _safe_float(card.get("cote")) > 0:
                card["manual_price"] = _safe_float(card.get("cote"))
                card["market_price_origin"] = "legacy_manual"
            summary["manual_preserved"] += 1
            continue
        entry = lookup_market_price(cache, card)
        if not entry:
            summary["unavailable"] += 1
            continue
        age = _entry_age_days(entry)
        if only_due and age is not None and age <= 14 and card.get("auto_price"):
            summary["recent_kept"] += 1
            continue
        result = apply_market_price_to_card(card, cache)
        if result["applied"]:
            if age is not None and age <= 14:
                summary["refreshed"] += 1
            else:
                summary["review"] += 1
        else:
            summary["unavailable"] += 1
    cache["last_refresh_at"] = _now_iso()
    return cache, summary


def build_market_alerts(cache, estimations_data, stock_data=None):
    cache = normalize_market_cache(cache)
    settings = cache.get("settings", {})
    min_pct = _safe_float(settings.get("alert_min_pct"), MARKET_ALERT_DEFAULT_MIN_PCT)
    min_eur = _safe_float(settings.get("alert_min_eur"), MARKET_ALERT_DEFAULT_MIN_EUR)
    alerts = []

    def add_alert(scope, card, context):
        entry = lookup_market_price(cache, card)
        if not entry:
            return
        current = _safe_float(entry.get("reference_price"))
        previous = _safe_float(entry.get("previous_price"))
        if current <= 0 or previous <= 0:
            return
        diff = current - previous
        pct = diff / previous * 100 if previous else 0
        if abs(pct) < min_pct or abs(diff) < min_eur:
            return
        alerts.append({
            "scope": scope,
            "card": card.get("name", "Carte"),
            "number": card.get("number", ""),
            "previous": previous,
            "current": current,
            "diff": diff,
            "pct": pct,
            "context": context,
        })

    for estimate in (estimations_data or {}).get("estimations", []) or []:
        for card in estimate.get("cards", []) or []:
            add_alert("estimation", card, estimate.get("name", "Estimation"))

    for lot in (stock_data or {}).get("lots", []) or []:
        if lot.get("is_collection_system") or lot.get("is_collection_lot"):
            continue
        for card in lot.get("cards", []) or []:
            add_alert("stock", card, lot.get("nom", "Lot"))
    return alerts

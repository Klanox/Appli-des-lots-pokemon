"""Read-only market dashboard helpers for Pokestock.

The market module uses its own datasets and never reads or writes stock data
or data.json. Writes happen only through explicit market actions.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
import re
import unicodedata

from services.card_cache_service import load_cards_cache_from_disk
from utils import APP_DIR, safe_write_json


MARKET_SERIES_CONFIG_FILE = os.path.join(APP_DIR, "market_series_config.json")
MARKET_PULL_RATES_FILE = os.path.join(APP_DIR, "market_pull_rates.json")
MARKET_PRICE_SNAPSHOTS_FILE = os.path.join(APP_DIR, "market_price_snapshots.json")
MARKET_WATCHLIST_FILE = os.path.join(APP_DIR, "market_watchlist.json")
MARKET_SOURCE_STATUS_FILE = os.path.join(APP_DIR, "market_source_status.json")
MARKET_CARD_REGISTRY_FILE = os.path.join(APP_DIR, "market_card_registry.json")

MARKET_DATASETS = {
    "market_series_config": MARKET_SERIES_CONFIG_FILE,
    "market_pull_rates": MARKET_PULL_RATES_FILE,
    "market_price_snapshots": MARKET_PRICE_SNAPSHOTS_FILE,
    "market_watchlist": MARKET_WATCHLIST_FILE,
    "market_source_status": MARKET_SOURCE_STATUS_FILE,
    "market_card_registry": MARKET_CARD_REGISTRY_FILE,
}

SPECIAL_MARKET_CATEGORIES = ("AR", "FA", "Alt", "SAR", "TG", "GG", "Gold")
PULL_RATE_RARITIES = ("AR", "FA", "ALT", "SAR", "TG", "GG", "GOLD")
SUPPORTED_DYNAMIC_PULL_RATE_CATEGORIES = (
    "Double Rare",
    "Ultra Rare",
    "Hyper Rare",
    "Mega Hyper Rare",
    "Mega Attack Rare",
    "Illustration Rare",
    "Special Illustration Rare",
    "ACE SPEC",
    "Master Ball Foil",
    "Poké Ball Foil",
    "Black White Rare",
    "Shiny Rare",
    "Shiny Ultra Rare",
    "Foil Energy",
    "Gold Rare",
    "Rainbow Rare",
    "Full Art",
    "Full Art Trainer",
    "Texture Energy",
    "Trainer Gallery",
    "Galarian Gallery",
    "Alt-Art V",
    "Alt-Art VMAX",
)
PULL_RATE_SLOT_KEYS = ("common", "reverse_probability", "holo_probability")
PULL_RATE_STATUS_LABELS = {
    "non_renseigne": "Non renseigné",
    "missing": "Non renseigné",
    "incomplete": "Incomplet",
    "review": "À vérifier",
    "ready": "Prêt à calculer",
}
FIXED_VMC_VALUES = {
    "common": 0.02,
    "reverse": 0.30,
    "holo": 0.50,
}

SERIES_PALETTE = (
    "#2dd4bf",
    "#f59e0b",
    "#f472b6",
    "#60a5fa",
    "#a78bfa",
    "#22c55e",
    "#fb7185",
    "#eab308",
    "#38bdf8",
    "#c084fc",
    "#f97316",
    "#34d399",
)

VMC_SERIES_WHITELIST = (
    {"set_id": "me04", "display_name": "Chaos Ascendant", "release_rank": 1},
    {"set_id": "me03", "display_name": "Équilibre Parfait", "release_rank": 2},
    {"set_id": "me02.5", "display_name": "Héros Transcendants", "release_rank": 3},
    {"set_id": "me02", "display_name": "Flammes Fantasmagoriques", "release_rank": 4},
    {"set_id": "me01", "display_name": "Méga-Évolution", "release_rank": 5},
    {"set_id": "sv10.5b", "display_name": "Foudre Noire", "release_rank": 6},
    {"set_id": "sv10.5w", "display_name": "Flamme Blanche", "release_rank": 7},
    {"set_id": "sv10", "display_name": "Rivalités Destinées", "release_rank": 8},
    {"set_id": "sv09", "display_name": "Aventures Ensemble", "release_rank": 9},
    {"set_id": "sv08.5", "display_name": "Évolutions Prismatiques", "release_rank": 10},
    {"set_id": "sv08", "display_name": "Étincelles Déferlantes", "release_rank": 11},
    {"set_id": "sv07", "display_name": "Couronne Stellaire", "release_rank": 12},
    {"set_id": "sv06.5", "display_name": "Fable Nébuleuse", "release_rank": 13},
    {"set_id": "sv06", "display_name": "Mascarade Crépusculaire", "release_rank": 14},
    {"set_id": "sv05", "display_name": "Forces Temporelles", "release_rank": 15},
    {"set_id": "sv04.5", "display_name": "Destinées de Paldea", "release_rank": 16},
    {"set_id": "sv04", "display_name": "Faille Paradoxe", "release_rank": 17},
    {"set_id": "sv03.5", "display_name": "151", "release_rank": 18},
    {"set_id": "sv03", "display_name": "Flammes Obsidiennes", "release_rank": 19},
    {"set_id": "sv02", "display_name": "Évolutions à Paldea", "release_rank": 20},
    {"set_id": "sv01", "display_name": "Écarlate et Violet", "release_rank": 21},
    {"set_id": "swsh12.5", "display_name": "Zénith Suprême", "release_rank": 22},
    {"set_id": "swsh12", "display_name": "Tempête Argentée", "release_rank": 23},
    {"set_id": "swsh11", "display_name": "Origine Perdue", "release_rank": 24},
    {"set_id": "swsh10.5", "display_name": "Pokémon GO", "release_rank": 25},
    {"set_id": "swsh10", "display_name": "Astres Radieux", "release_rank": 26},
    {"set_id": "swsh9", "display_name": "Stars Étincelantes", "release_rank": 27},
    {"set_id": "swsh8", "display_name": "Poing de Fusion", "release_rank": 28},
    {"set_id": "cel25", "display_name": "Célébrations", "release_rank": 29},
    {"set_id": "swsh7", "display_name": "Évolution Céleste", "release_rank": 30},
    {"set_id": "swsh6", "display_name": "Règne de Glace", "release_rank": 31},
    {"set_id": "swsh5", "display_name": "Styles de Combat", "release_rank": 32},
    {"set_id": "swsh4.5", "display_name": "Destinées Radieuses", "release_rank": 33},
    {"set_id": "swsh4", "display_name": "Voltage Éclatant", "release_rank": 34},
    {"set_id": "swsh3.5", "display_name": "La Voie du Maître", "release_rank": 35},
    {"set_id": "swsh3", "display_name": "Ténèbres Embrasées", "release_rank": 36},
    {"set_id": "swsh2", "display_name": "Clash des Rebelles", "release_rank": 37},
    {"set_id": "swsh1", "display_name": "Épée et Bouclier", "release_rank": 38},
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fold(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _default_series_config() -> dict:
    return {
        "version": 1,
        "vmc_series_whitelist": [
            {
                **item,
                "vmc_enabled": True,
                "dashboard_enabled": True,
                "default_visible": True,
                "is_main_set": True,
                "status": "configured",
            }
            for item in VMC_SERIES_WHITELIST
        ],
        "series_overrides": {},
        "fixed_card_values": deepcopy(FIXED_VMC_VALUES),
        "special_categories": list(SPECIAL_MARKET_CATEGORIES),
        "notes": "VMC dashboard uses the explicit French main-set whitelist only.",
    }


def _default_pull_rates() -> dict:
    return {
        "version": 1,
        "sets": {},
        "default_fixed_values": deepcopy(FIXED_VMC_VALUES),
        "categories": list(SUPPORTED_DYNAMIC_PULL_RATE_CATEGORIES),
        "notes": "Pull rates are manual and required before a VMC can be considered calculable.",
    }


def _default_snapshots() -> dict:
    return {
        "version": 1,
        "snapshots": [],
        "rules": {
            "max_one_snapshot_per_card_per_day": True,
            "zero_prices_allowed": False,
        },
    }


def _default_watchlist() -> dict:
    return {
        "version": 1,
        "cards": [],
    }


def _default_source_status() -> dict:
    return {
        "version": 1,
        "last_audit_at": "",
        "exact_cardmarket_fr_nm_available": False,
        "notes": "Computed audit is displayed live without exposing secrets.",
    }


def _default_card_registry() -> dict:
    return {
        "version": 1,
        "cards": [],
        "notes": "Optional manual registry. Card cache metadata is also used at render time.",
    }


DEFAULT_DATASETS = {
    MARKET_SERIES_CONFIG_FILE: _default_series_config,
    MARKET_PULL_RATES_FILE: _default_pull_rates,
    MARKET_PRICE_SNAPSHOTS_FILE: _default_snapshots,
    MARKET_WATCHLIST_FILE: _default_watchlist,
    MARKET_SOURCE_STATUS_FILE: _default_source_status,
    MARKET_CARD_REGISTRY_FILE: _default_card_registry,
}


def _read_json(path: str, default_factory) -> dict:
    if not os.path.exists(path):
        return default_factory()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return default_factory()


def ensure_market_dataset_files() -> None:
    """Create empty market dataset files when explicitly called by setup code."""
    for path, factory in DEFAULT_DATASETS.items():
        if not os.path.exists(path):
            safe_write_json(path, factory(), indent=2)


def load_market_datasets() -> dict:
    return {
        "series_config": _read_json(MARKET_SERIES_CONFIG_FILE, _default_series_config),
        "pull_rates": _read_json(MARKET_PULL_RATES_FILE, _default_pull_rates),
        "price_snapshots": _read_json(MARKET_PRICE_SNAPSHOTS_FILE, _default_snapshots),
        "watchlist": _read_json(MARKET_WATCHLIST_FILE, _default_watchlist),
        "source_status": _read_json(MARKET_SOURCE_STATUS_FILE, _default_source_status),
        "card_registry": _read_json(MARKET_CARD_REGISTRY_FILE, _default_card_registry),
    }


def save_market_watchlist(watchlist: dict) -> None:
    payload = deepcopy(watchlist) if isinstance(watchlist, dict) else _default_watchlist()
    payload.setdefault("version", 1)
    payload.setdefault("cards", [])
    payload["updated_at"] = _now_iso()
    safe_write_json(MARKET_WATCHLIST_FILE, payload, indent=2)


def save_market_series_config(config: dict) -> None:
    payload = deepcopy(config) if isinstance(config, dict) else _default_series_config()
    payload.setdefault("version", 1)
    payload.setdefault("series_overrides", {})
    payload.setdefault("fixed_card_values", deepcopy(FIXED_VMC_VALUES))
    payload.setdefault("special_categories", list(SPECIAL_MARKET_CATEGORIES))
    payload["updated_at"] = _now_iso()
    safe_write_json(MARKET_SERIES_CONFIG_FILE, payload, indent=2)


def save_market_pull_rates(pull_rates: dict) -> None:
    payload = deepcopy(pull_rates) if isinstance(pull_rates, dict) else _default_pull_rates()
    payload.setdefault("version", 1)
    payload.setdefault("sets", {})
    payload.setdefault("default_fixed_values", deepcopy(FIXED_VMC_VALUES))
    payload.setdefault("categories", list(SUPPORTED_DYNAMIC_PULL_RATE_CATEGORIES))
    payload["updated_at"] = _now_iso()
    safe_write_json(MARKET_PULL_RATES_FILE, payload, indent=2)


def _series_lookup(series: list[dict] | None = None) -> dict[str, dict]:
    rows = series if isinstance(series, list) else infer_market_series(_default_series_config())
    lookup = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        set_id = str(item.get("set_id") or "").strip()
        if set_id:
            lookup[set_id.upper()] = item
    return lookup


def _empty_pull_rate_entry(series: dict) -> dict:
    set_id = str(series.get("set_id") or "").strip()
    set_name = str(series.get("display_name") or series.get("name_fr") or set_id)
    return {
        "set_id": set_id,
        "set_name": set_name,
        "booster_type": "standard",
        "updated_at": "",
        "source_note": "",
        "validated_at": "",
        "validated_by_user": False,
        "status": "missing",
        "slots": {
            "common": None,
            "reverse_probability": None,
            "holo_probability": None,
        },
        "rarities": {},
        "category_rates": [],
        "rare_rates_status": "missing",
        "booster_slots_status": "missing",
        "special_categories_status": "missing",
        "overall_status": "missing",
        "distribution_mode": "category_average",
        "notes": "",
        "errors": [],
    }


def normalise_market_pull_rates(pull_rates: dict | None, series: list[dict] | None = None) -> dict:
    payload = deepcopy(pull_rates) if isinstance(pull_rates, dict) else _default_pull_rates()
    payload.setdefault("version", 1)
    payload.setdefault("default_fixed_values", deepcopy(FIXED_VMC_VALUES))
    payload.setdefault("categories", list(SUPPORTED_DYNAMIC_PULL_RATE_CATEGORIES))
    sets = payload.setdefault("sets", {})
    if not isinstance(sets, dict):
        sets = {}
        payload["sets"] = sets
    for set_key, series_row in _series_lookup(series).items():
        existing = sets.get(set_key) or sets.get(str(series_row.get("set_id") or ""))
        entry = _empty_pull_rate_entry(series_row)
        if isinstance(existing, dict):
            entry.update(
                {
                    key: value
                    for key, value in existing.items()
                    if key not in ("set_id", "set_name", "slots", "rarities")
                }
            )
            slots = existing.get("slots") if isinstance(existing.get("slots"), dict) else {}
            for slot_key in PULL_RATE_SLOT_KEYS:
                entry["slots"][slot_key] = slots.get(slot_key, existing.get(slot_key, entry["slots"][slot_key]))
            raw_rarities = existing.get("rarities") if isinstance(existing.get("rarities"), dict) else {}
            if isinstance(existing.get("category_rates"), list):
                entry["category_rates"] = deepcopy(existing["category_rates"])
            for rarity in PULL_RATE_RARITIES:
                raw = raw_rarities.get(rarity) or raw_rarities.get(rarity.title()) or existing.get(rarity)
                if isinstance(raw, dict):
                    entry["rarities"].setdefault(rarity, {"probability": None, "not_applicable": False})
                    entry["rarities"][rarity]["probability"] = raw.get("probability")
                    entry["rarities"][rarity]["not_applicable"] = bool(raw.get("not_applicable"))
                elif raw is not None:
                    entry["rarities"].setdefault(rarity, {"probability": None, "not_applicable": False})
                    entry["rarities"][rarity]["probability"] = raw
        validation = validate_pull_rate_entry(entry)
        entry["status"] = validation["status"]
        entry["overall_status"] = validation["status"]
        entry["rare_rates_status"] = validation["rare_rates_status"]
        entry["booster_slots_status"] = validation["booster_slots_status"]
        entry["special_categories_status"] = validation["special_categories_status"]
        entry["errors"] = validation["errors"]
        sets[set_key] = entry
    return payload


def parse_pull_rate_value(raw) -> tuple[float | None, str]:
    if raw is None:
        return None, ""
    text = str(raw).strip()
    if not text:
        return None, ""
    text = text.split("·", 1)[0].split("≈", 1)[0].strip()
    text_norm = _fold(text).replace(",", ".")
    text_norm = re.sub(r"\s+", " ", text_norm)
    fraction_match = re.fullmatch(r"1\s*(:/|sur)\s*(\d+(:\.\d+))", text_norm)
    if fraction_match:
        denominator = float(fraction_match.group(1))
        if denominator <= 0:
            return None, "Le denominateur doit etre superieur a 0."
        return 1.0 / denominator, ""
    percent_match = re.fullmatch(r"(\d+(:\.\d+))\s*%", text_norm)
    if percent_match:
        value = float(percent_match.group(1)) / 100.0
    else:
        try:
            value = float(text_norm)
        except ValueError:
            return None, "Format non reconnu. Utilise 1/12, 1 sur 12, 8,33 % ou 0,0833."
    if value < 0:
        return None, "La probabilite ne peut pas etre negative."
    if value > 1:
        return None, "La probabilite ne peut pas depasser 1."
    return value, ""


def format_pull_rate(value) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return ""
    if parsed <= 0:
        return ""
    reciprocal = 1 / parsed
    if abs(reciprocal - round(reciprocal)) < 0.01:
        ratio = f"1 sur {int(round(reciprocal))}"
    else:
        ratio = f"1 sur {reciprocal:.2f}".replace(".", ",")
    percent = f"{parsed * 100:.2f}".replace(".", ",")
    return f"{ratio} · ≈ {percent} %"


def _entry_has_any_value(entry: dict) -> bool:
    slots = entry.get("slots") if isinstance(entry.get("slots"), dict) else {}
    rarities = entry.get("rarities") if isinstance(entry.get("rarities"), dict) else {}
    categories = entry.get("category_rates") if isinstance(entry.get("category_rates"), list) else []
    if any(slots.get(key) not in (None, "") for key in PULL_RATE_SLOT_KEYS):
        return True
    if categories:
        return True
    for raw in rarities.values():
        if isinstance(raw, dict) and (raw.get("probability") not in (None, "") or raw.get("not_applicable")):
            return True
        if not isinstance(raw, dict) and raw not in (None, "", {}):
            return True
    return bool(str(entry.get("source_note") or entry.get("notes") or "").strip())


def validate_pull_rate_entry(entry: dict, *, explicit_validation: bool | None = None) -> dict:
    errors = []
    missing = []
    payload = entry if isinstance(entry, dict) else {}
    slots = payload.get("slots") if isinstance(payload.get("slots"), dict) else {}
    category_rates = payload.get("category_rates") if isinstance(payload.get("category_rates"), list) else []
    for slot_key in PULL_RATE_SLOT_KEYS:
        value = slots.get(slot_key)
        if value in (None, ""):
            missing.append(slot_key)
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            errors.append(f"{slot_key}: valeur invalide")
            continue
        if numeric < 0 or numeric > 1:
            errors.append(f"{slot_key}: doit etre compris entre 0 et 1")
        if slot_key == "common" and numeric <= 0:
            errors.append("common: doit etre superieur a 0")
    if category_rates:
        for index, category in enumerate(category_rates, start=1):
            if not isinstance(category, dict):
                errors.append(f"categorie {index}: entree invalide")
                continue
            label = category.get("source_label") or category.get("display_name") or f"categorie {index}"
            any_probability = category.get("any_probability")
            specific_probability = category.get("specific_probability")
            if any_probability not in (None, ""):
                try:
                    numeric = float(any_probability)
                except (TypeError, ValueError):
                    errors.append(f"{label}: Any invalide")
                else:
                    if numeric < 0 or numeric > 1:
                        errors.append(f"{label}: Any doit etre compris entre 0 et 1")
            if specific_probability not in (None, ""):
                try:
                    numeric = float(specific_probability)
                except (TypeError, ValueError):
                    errors.append(f"{label}: Specific invalide")
                else:
                    if numeric < 0 or numeric > 1:
                        errors.append(f"{label}: Specific doit etre compris entre 0 et 1")
    else:
        rarities = payload.get("rarities") if isinstance(payload.get("rarities"), dict) else {}
        for rarity, raw_value in rarities.items():
            raw = raw_value if isinstance(raw_value, dict) else {}
            not_applicable = bool(raw.get("not_applicable"))
            value = raw.get("probability")
            if not_applicable and value not in (None, ""):
                errors.append(f"{rarity}: ne doit pas avoir de valeur si non applicable")
                continue
            if not not_applicable and value in (None, ""):
                missing.append(rarity)
                continue
            if value not in (None, ""):
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    errors.append(f"{rarity}: valeur invalide")
                    continue
                if numeric < 0 or numeric > 1:
                    errors.append(f"{rarity}: doit etre compris entre 0 et 1")
    note = str(payload.get("source_note") or payload.get("notes") or "").strip()
    if not note:
        missing.append("source_note")
    validated = bool(payload.get("validated_by_user"))
    if explicit_validation is not None:
        validated = bool(explicit_validation)
    rare_rates_status = "imported" if category_rates else ("missing" if not _entry_has_any_value(payload) else "manual")
    booster_slots_status = "configured" if all(slots.get(key) not in (None, "") for key in PULL_RATE_SLOT_KEYS) else "missing"
    if category_rates:
        special_categories_status = "to_decide"
    else:
        special_categories_status = "missing" if not _entry_has_any_value(payload) else "manual"
    if payload.get("overall_status") == "non_renseigne" and not _entry_has_any_value(payload):
        status = "non_renseigne"
    elif errors:
        status = "review"
    elif not _entry_has_any_value(payload):
        status = "missing"
    elif missing:
        status = "incomplete"
    elif not validated:
        status = "review"
    else:
        status = "ready"
    return {
        "status": status,
        "status_label": PULL_RATE_STATUS_LABELS.get(status, status),
        "errors": errors,
        "missing": missing,
        "rare_rates_status": rare_rates_status,
        "booster_slots_status": booster_slots_status,
        "special_categories_status": special_categories_status,
        "ready": status == "ready",
    }


def build_pull_rate_entry_from_values(series: dict, values: dict, *, validate_now: bool = False) -> tuple[dict, dict]:
    entry = _empty_pull_rate_entry(series)
    slots_input = values.get("slots", {}) if isinstance(values.get("slots"), dict) else {}
    for slot_key in PULL_RATE_SLOT_KEYS:
        parsed, error = parse_pull_rate_value(slots_input.get(slot_key))
        if error:
            entry["errors"].append(f"{slot_key}: {error}")
        entry["slots"][slot_key] = parsed
    rarity_input = values.get("rarities", {}) if isinstance(values.get("rarities"), dict) else {}
    for rarity in PULL_RATE_RARITIES:
        raw = rarity_input.get(rarity, {})
        if not isinstance(raw, dict):
            raw = {"probability": raw, "not_applicable": False}
        entry["rarities"][rarity]["not_applicable"] = bool(raw.get("not_applicable"))
        parsed, error = parse_pull_rate_value(raw.get("probability"))
        if error:
            entry["errors"].append(f"{rarity}: {error}")
        entry["rarities"][rarity]["probability"] = parsed
    entry["source_note"] = str(values.get("source_note") or "").strip()
    entry["notes"] = str(values.get("notes") or "").strip()
    entry["validated_by_user"] = bool(validate_now)
    if validate_now:
        entry["validated_at"] = _now_iso()
    entry["updated_at"] = _now_iso()
    validation = validate_pull_rate_entry(entry, explicit_validation=validate_now)
    entry["errors"] = sorted(set(entry.get("errors", []) + validation["errors"]))
    if entry["errors"]:
        validation["status"] = "review"
        validation["status_label"] = PULL_RATE_STATUS_LABELS["review"]
        validation["ready"] = False
    entry["status"] = validation["status"]
    return entry, validation


def update_pull_rate_entry(
    pull_rates: dict,
    series: list[dict],
    set_id: str,
    values: dict,
    *,
    validate_now: bool = False,
) -> tuple[dict, dict, dict]:
    payload = normalise_market_pull_rates(pull_rates, series)
    lookup = _series_lookup(series)
    key = str(set_id or "").upper()
    if key not in lookup:
        raise ValueError("Serie hors whitelist VMC.")
    entry, validation = build_pull_rate_entry_from_values(lookup[key], values, validate_now=validate_now)
    payload.setdefault("sets", {})[key] = entry
    payload["updated_at"] = _now_iso()
    return payload, entry, validation


def preview_pull_rates_import(raw_text: str, current_pull_rates: dict, series: list[dict]) -> dict:
    del current_pull_rates
    try:
        parsed = json.loads(raw_text or "")
    except json.JSONDecodeError as exc:
        return {"valid": [], "errors": [f"JSON invalide: {exc.msg}"], "warnings": []}
    rows = parsed.get("sets", parsed) if isinstance(parsed, dict) else parsed
    if isinstance(rows, dict):
        iterable = []
        for key, value in rows.items():
            if isinstance(value, dict):
                row = deepcopy(value)
                row.setdefault("set_id", key)
                iterable.append(row)
    elif isinstance(rows, list):
        iterable = rows
    else:
        return {"valid": [], "errors": ["Format attendu: objet sets ou liste d'entrees."], "warnings": []}
    lookup = _series_lookup(series)
    valid = []
    errors = []
    warnings = []
    for index, row in enumerate(iterable, start=1):
        if not isinstance(row, dict):
            errors.append(f"Ligne {index}: entree invalide")
            continue
        set_id = str(row.get("set_id") or "").upper()
        if set_id not in lookup:
            errors.append(f"{set_id or 'sans set_id'}: serie hors whitelist refusee")
            continue
        values = {
            "slots": row.get("slots", {}),
            "rarities": row.get("rarities", {}),
            "source_note": row.get("source_note") or row.get("source") or "",
            "notes": row.get("notes") or "",
        }
        entry, validation = build_pull_rate_entry_from_values(
            lookup[set_id],
            values,
            validate_now=bool(row.get("validated_by_user")),
        )
        valid.append({"set_id": set_id, "set_name": lookup[set_id].get("name_fr"), "entry": entry, "validation": validation})
        if validation["status"] != "ready":
            warnings.append(f"{set_id}: {validation['status_label']}")
    return {"valid": valid, "errors": errors, "warnings": warnings}


def apply_pull_rates_import(pull_rates: dict, series: list[dict], preview: dict) -> dict:
    payload = normalise_market_pull_rates(pull_rates, series)
    for item in preview.get("valid", []):
        if not isinstance(item, dict) or not isinstance(item.get("entry"), dict):
            continue
        set_id = str(item.get("set_id") or item["entry"].get("set_id") or "").upper()
        if set_id in _series_lookup(series):
            payload.setdefault("sets", {})[set_id] = deepcopy(item["entry"])
    payload["updated_at"] = _now_iso()
    return payload


def export_pull_rates_json(pull_rates: dict, series: list[dict]) -> str:
    payload = normalise_market_pull_rates(pull_rates, series)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def attach_pull_rate_status_to_series(series: list[dict], pull_rates: dict) -> list[dict]:
    normalised = normalise_market_pull_rates(pull_rates, series)
    sets = normalised.get("sets", {})
    enriched = []
    for item in series:
        row = deepcopy(item)
        entry = sets.get(str(row.get("set_id") or "").upper(), {})
        validation = validate_pull_rate_entry(entry)
        row["pull_rate_status"] = validation["status"]
        row["pull_rate_label"] = (
            "Taux rares importés"
            if validation.get("rare_rates_status") == "imported"
            else validation["status_label"]
        )
        row["pull_rate_updated_at"] = entry.get("updated_at") or ""
        row["rare_rates_status"] = validation.get("rare_rates_status")
        row["booster_slots_status"] = validation.get("booster_slots_status")
        row["special_categories_status"] = validation.get("special_categories_status")
        row["pull_rate_ready"] = validation["ready"]
        enriched.append(row)
    return enriched


def calculate_vmc_for_booster(series: dict, pull_rate_entry: dict, price_index: dict | None = None) -> dict:
    del series, pull_rate_entry, price_index
    return {
        "available": False,
        "vmc_eur": None,
        "reason": "VMC indisponible : prix exacts Cardmarket FR NM manquants.",
    }


def stable_series_color(set_id: str, override: str = "") -> str:
    if override:
        return str(override)
    key = str(set_id or "").encode("utf-8", errors="ignore")
    digest = hashlib.sha1(key).hexdigest()
    return SERIES_PALETTE[int(digest[:2], 16) % len(SERIES_PALETTE)]


def _card_set_id(card: dict, fallback: str = "") -> str:
    set_value = card.get("set") if isinstance(card, dict) else {}
    if isinstance(set_value, dict):
        return str(set_value.get("id") or set_value.get("tcgDexId") or fallback or "").strip()
    return str(card.get("set_id") or card.get("setCode") or card.get("set_code") or fallback or "").strip()


def _card_set_name(card: dict, fallback: str = "") -> str:
    set_value = card.get("set") if isinstance(card, dict) else {}
    if isinstance(set_value, dict):
        return str(
            set_value.get("name")
            or set_value.get("name_fr")
            or set_value.get("name_en")
            or fallback
            or ""
        ).strip()
    return str(card.get("set_name") or card.get("extension") or fallback or "").strip()


def _card_release_date(card: dict) -> str:
    set_value = card.get("set") if isinstance(card, dict) else {}
    if isinstance(set_value, dict):
        return str(set_value.get("releaseDate") or set_value.get("release_date") or "").strip()
    return str(card.get("releaseDate") or card.get("release_date") or "").strip()


def _iter_cache_cards():
    cards_index = load_cards_cache_from_disk(allow_stale=True) or {}
    seen = set()
    for cache_name, rows in cards_index.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            card = {}
            set_name = ""
            set_id = ""
            if isinstance(row, (list, tuple)) and row:
                card = row[0] if isinstance(row[0], dict) else {}
                set_name = str(row[1] if len(row) > 1 else "")
                set_id = str(row[2] if len(row) > 2 else "")
            elif isinstance(row, dict):
                card = row
            if not isinstance(card, dict):
                continue
            card_id = str(card.get("id") or card.get("card_id") or cache_name or "")
            key = card_id or f"{card.get('name')}|{_card_set_id(card, set_id)}|{card.get('localId') or card.get('number')}"
            if key in seen:
                continue
            seen.add(key)
            yield card, set_name, set_id


def _cache_series_by_id() -> dict[str, dict]:
    series = {}
    for card, set_name_fallback, set_id_fallback in _iter_cache_cards():
        set_id = _card_set_id(card, set_id_fallback)
        if not set_id:
            continue
        set_key = set_id.upper()
        entry = series.setdefault(
            set_key,
            {
                "set_id": set_id,
                "name_fr": _card_set_name(card, set_name_fallback) or set_id,
                "name_en": "",
                "release_date": _card_release_date(card),
                "block": "",
                "cards_count": 0,
            },
        )
        entry["cards_count"] += 1
        if not entry.get("release_date"):
            entry["release_date"] = _card_release_date(card)
    return series


def infer_market_series(series_config: dict | None = None) -> list[dict]:
    overrides = (series_config or {}).get("series_overrides", {}) if isinstance(series_config, dict) else {}
    configured = (series_config or {}).get("vmc_series_whitelist", []) if isinstance(series_config, dict) else []
    whitelist = configured if isinstance(configured, list) and configured else list(VMC_SERIES_WHITELIST)
    cache = _cache_series_by_id()
    series = []
    for base in whitelist:
        if not isinstance(base, dict):
            continue
        set_id = str(base.get("set_id") or "").strip()
        if not set_id:
            continue
        set_key = set_id.upper()
        cached = cache.get(set_key, {})
        override = overrides.get(set_key) or overrides.get(set_id) or {}
        if not isinstance(override, dict):
            override = {}
        display_name = str(base.get("display_name") or cached.get("name_fr") or set_id)
        status = str(base.get("status") or ("configured" if cached else "unresolved"))
        entry = {
            "set_id": set_id,
            "name_fr": display_name,
            "display_name": display_name,
            "name_en": str(cached.get("name_en") or base.get("name_en") or ""),
            "release_date": str(cached.get("release_date") or base.get("release_date") or ""),
            "block": str(cached.get("block") or base.get("block") or ""),
            "color": stable_series_color(set_id, str(base.get("color") or "")),
            "active_market": bool(base.get("dashboard_enabled", True)),
            "active_vmc": bool(base.get("vmc_enabled", True)),
            "dashboard_enabled": bool(base.get("dashboard_enabled", True)),
            "vmc_enabled": bool(base.get("vmc_enabled", True)),
            "default_visible": bool(base.get("default_visible", True)),
            "is_main_set": bool(base.get("is_main_set", True)),
            "is_promo_set": False,
            "release_rank": int(base.get("release_rank") or 999),
            "status": status,
            "cards_count": int(cached.get("cards_count") or 0),
        }
        entry.update({k: v for k, v in override.items() if v is not None})
        entry["color"] = stable_series_color(entry.get("set_id"), entry.get("color"))
        series.append(entry)
    return sorted(series, key=lambda item: int(item.get("release_rank") or 999))


def _snapshot_date(snapshot: dict) -> datetime | None:
    raw = str(snapshot.get("captured_at") or snapshot.get("date") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def filter_snapshots_for_period(snapshots: list[dict], period: str) -> list[dict]:
    if period == "all":
        return snapshots
    days = {"1m": 31, "3m": 92, "6m": 183, "1y": 366}.get(period)
    if not days:
        return snapshots
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    filtered = []
    for snapshot in snapshots:
        dt = _snapshot_date(snapshot)
        if dt and dt >= cutoff:
            filtered.append(snapshot)
    return filtered


def vmc_can_be_calculated(series: dict, pull_rates: dict, source_exact_available: bool) -> tuple[bool, str]:
    if not source_exact_available:
        return False, "Source de prix exacte indisponible."
    normalised = normalise_market_pull_rates(pull_rates, [series])
    set_id = str(series.get("set_id") or "").upper()
    configured = normalised.get("sets", {}).get(set_id)
    if not configured or validate_pull_rate_entry(configured)["status"] in ("missing", "non_renseigne"):
        return False, "Pull rates manquants."
    validation = validate_pull_rate_entry(configured)
    if validation["status"] != "ready":
        return False, f"Pull rates {validation['status_label'].lower()}."
    return True, ""


def eligible_market_card(card: dict) -> bool:
    text = _fold(
        " ".join(
            str(card.get(key) or "")
            for key in ("rarity", "special", "special_tag", "category", "variant", "name")
        )
    )
    tags = _fold(" ".join(str(tag) for key in ("tags", "metadata_tags", "card_tags") for tag in (card.get(key) or []) if tag))
    haystack = f"{text} {tags}"
    excluded = ("common", "uncommon", "commune", "peu commune", "reverse", "holo rare")
    included = (
        "illustration rare",
        "art rare",
        "full art",
        "alternative",
        "special art",
        "secret",
        "gold",
        "trainer gallery",
        "galarian gallery",
        "promo",
        "hyper rare",
        "rainbow",
        "sar",
        "tg",
        "gg",
    )
    if any(token in haystack for token in included):
        return True
    if any(token in haystack for token in excluded):
        return False
    name = _fold(card.get("name"))
    return bool(re.search(r"(^|[-\s])(ex|gx|vmax|vstar|v)([-\s]|$)", name))


def infer_market_cards(limit: int = 500) -> list[dict]:
    cards = []
    for card, set_name_fallback, set_id_fallback in _iter_cache_cards():
        if not eligible_market_card(card):
            continue
        set_id = _card_set_id(card, set_id_fallback)
        name = str(card.get("name") or "").strip()
        number = str(card.get("localId") or card.get("number") or "").strip()
        if not name:
            continue
        language = str(card.get("lang") or card.get("language") or "fr").lower()
        card_key = "|".join(
            [
                language,
                set_id.upper(),
                number.upper(),
                _fold(str(card.get("variant") or card.get("special") or "normal")),
                str(card.get("id") or card.get("card_id") or ""),
            ]
        )
        cards.append(
            {
                "card_key": card_key,
                "source_card_id": str(card.get("id") or card.get("card_id") or ""),
                "name": name,
                "number": number,
                "set_id": set_id,
                "set_name": _card_set_name(card, set_name_fallback),
                "language": language,
                "variant": str(card.get("variant") or card.get("special") or "").strip(),
                "rarity": str(card.get("rarity") or card.get("special_tag") or card.get("special") or "").strip(),
                "is_promo": bool("promo" in _fold(f"{card.get('rarity')} {card.get('special')} {_card_set_name(card, set_name_fallback)} {set_id}")),
                "image_url": str(card.get("image_url") or card.get("image") or card.get("image_url_en") or "").strip(),
                "cardmarket_url": str(card.get("cardmarket_url") or card.get("cardmarket_link") or "").strip(),
            }
        )
        if len(cards) >= limit:
            break
    return cards


def search_market_cards(query: str, cards: list[dict], language: str = "fr", limit: int = 20) -> list[dict]:
    query_norm = _fold(query)
    if not query_norm:
        return []
    terms = [term for term in query_norm.split(" ") if term]
    scored = []
    for card in cards:
        if language and str(card.get("language") or "fr").lower() != language:
            continue
        haystack = _fold(
            " ".join(
                str(card.get(key) or "")
                for key in ("name", "number", "set_id", "set_name", "rarity", "variant")
            )
        )
        if not all(term in haystack for term in terms):
            continue
        score = 0
        name_norm = _fold(card.get("name"))
        if name_norm == query_norm:
            score += 100
        if name_norm.startswith(query_norm):
            score += 60
        score += sum(20 for term in terms if term in name_norm)
        score += 15 if card.get("image_url") else 0
        score += 10 if card.get("is_promo") else 0
        scored.append((score, card))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [card for _, card in scored[:limit]]


def add_card_to_watchlist(watchlist: dict, card: dict) -> tuple[dict, bool]:
    payload = deepcopy(watchlist) if isinstance(watchlist, dict) else _default_watchlist()
    payload.setdefault("version", 1)
    payload.setdefault("cards", [])
    existing = {str(item.get("card_key")) for item in payload["cards"] if isinstance(item, dict)}
    card_key = str(card.get("card_key") or "")
    if not card_key or card_key in existing:
        return payload, False
    payload["cards"].append(
        {
            "card_key": card_key,
            "nom": card.get("name", ""),
            "numero": card.get("number", ""),
            "set_id": card.get("set_id", ""),
            "langue": card.get("language", "fr"),
            "variante": card.get("variant", ""),
            "is_promo": bool(card.get("is_promo")),
            "date_ajout": _now_iso(),
            "note": "",
            "alert_price_below": None,
            "alert_price_above": None,
            "alert_change_up_pct": None,
            "alert_change_down_pct": None,
            "active": True,
        }
    )
    return payload, True


def audit_price_source() -> dict:
    env_names = sorted(
        name
        for name in os.environ
        if any(token in name.upper() for token in ("CARDMARKET", "CMKT", "MARKET_API"))
    )
    cardmarket_module = importlib.util.find_spec("cardmarket_api") is not None
    requests_available = importlib.util.find_spec("requests") is not None
    capabilities = {
        "configuration_detected": bool(env_names or cardmarket_module),
        "cardmarket_client_module": cardmarket_module,
        "http_client_available": requests_available,
        "product_exact_search": False,
        "language_filter_fr": False,
        "condition_near_mint": False,
        "available_listing_price": False,
        "variant_disambiguation": False,
    }
    exact = all(
        capabilities[key]
        for key in (
            "product_exact_search",
            "language_filter_fr",
            "condition_near_mint",
            "available_listing_price",
            "variant_disambiguation",
        )
    )
    return {
        "audited_at": _now_iso(),
        "exact_cardmarket_fr_nm_available": exact,
        "safe_config_signals": env_names,
        "capabilities": capabilities,
        "status_label": (
            "Premier prix Cardmarket FR NM exact : disponible"
            if exact
            else "Premier prix Cardmarket FR NM exact : indisponible"
        ),
        "explanation": (
            "Aucun client autorise ne prouve la recuperation d'un produit exact, francais, Near Mint, "
            "variante exacte, annonce disponible et prix hors livraison."
            if not exact
            else "Source exacte detectee."
        ),
    }

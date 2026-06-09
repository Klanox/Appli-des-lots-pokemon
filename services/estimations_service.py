"""Helpers for lot estimations."""

from datetime import datetime
import json
import os
import uuid

from cloud import cloud_sync_enabled, load_cloud_json, save_cloud_json, SUPABASE_ESTIMATIONS_KEY
from data import maybe_create_prewrite_backup
from utils import safe_write_json


DEFAULT_ESTIMATION_SOURCES = {
    "Vinted": 60.0,
    "Main propre": 65.0,
    "Brocante": 55.0,
}


def _new_uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def default_estimations_data():
    return {
        "settings": {
            "sources": dict(DEFAULT_ESTIMATION_SOURCES),
            "default_source": "Vinted",
        },
        "estimations": [],
    }


def normalize_estimations_data(data):
    if not isinstance(data, dict):
        data = default_estimations_data()
    data.setdefault("settings", {})
    existing_sources = data["settings"].get("sources", {}) if isinstance(data["settings"].get("sources", {}), dict) else {}
    data["settings"]["sources"] = {
        source: float(existing_sources.get(source, default_pct) or default_pct)
        for source, default_pct in DEFAULT_ESTIMATION_SOURCES.items()
    }
    for source, pct in DEFAULT_ESTIMATION_SOURCES.items():
        data["settings"]["sources"].setdefault(source, pct)
    data["settings"].setdefault("default_source", "Vinted")
    if data["settings"].get("default_source") not in data["settings"]["sources"]:
        data["settings"]["default_source"] = "Vinted"
    data.setdefault("estimations", [])
    for estimation in data["estimations"]:
        estimation.setdefault("uid", _new_uid("estimate"))
        estimation.setdefault("name", "Estimation sans nom")
        estimation.setdefault("source", data["settings"].get("default_source", "Vinted"))
        estimation.setdefault("fees", 0.0)
        estimation.setdefault("safety_eur", 0.0)
        estimation.setdefault("seller_price", 0.0)
        estimation.setdefault("listing_url", "")
        estimation.setdefault("listing_image_url", "")
        estimation.setdefault("status", "En cours")
        if estimation.get("source") not in data["settings"]["sources"]:
            estimation["source"] = data["settings"].get("default_source", "Vinted")
        estimation.setdefault("created_at", datetime.now().isoformat()[:10])
        estimation.setdefault("cards", [])
        for card in estimation["cards"]:
            card.setdefault("uid", _new_uid("estcard"))
            card.setdefault("name", "Carte")
            card.setdefault("number", "")
            card.setdefault("set", "")
            card.setdefault("quantity", 1)
            card.setdefault("cote", 0.0)
            card.setdefault("condition", "NM")
            card.setdefault("special", "")
            card.setdefault("note", "")
            card.setdefault("image_url", "")
            card.setdefault("image_url_en", "")
            card.setdefault("is_collection", False)
    return data


def load_estimations(estimations_file="lot_estimations.json"):
    cloud_data = load_cloud_json(SUPABASE_ESTIMATIONS_KEY) if cloud_sync_enabled() else None
    if isinstance(cloud_data, dict):
        data = cloud_data
    elif os.path.exists(estimations_file):
        try:
            with open(estimations_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load estimations file: {e}")
            data = default_estimations_data()
    else:
        data = default_estimations_data()
    data = normalize_estimations_data(data)
    safe_write_json(estimations_file, data, indent=2)
    return data


def save_estimations(data, estimations_file="lot_estimations.json"):
    data = normalize_estimations_data(data)
    maybe_create_prewrite_backup()
    safe_write_json(estimations_file, data, indent=2)
    if cloud_sync_enabled():
        save_cloud_json(SUPABASE_ESTIMATIONS_KEY, data)
    return data


def estimation_totals(estimation, settings):
    resale_cards = [c for c in estimation.get("cards", []) if not c.get("is_collection")]
    collection_cards = [c for c in estimation.get("cards", []) if c.get("is_collection")]
    total_cote = sum(float(c.get("cote", 0.) or 0.) * int(c.get("quantity", 1) or 1) for c in resale_cards)
    collection_cote = sum(float(c.get("cote", 0.) or 0.) * int(c.get("quantity", 1) or 1) for c in collection_cards)
    source = estimation.get("source", settings.get("default_source", "Vinted"))
    pct = float(settings.get("sources", {}).get(source, 60.0) or 60.0)
    fees = 0.0
    safety = float(estimation.get("safety_eur", 0.) or 0.)
    max_buy = max(total_cote * pct / 100 - fees - safety, 0.)
    seller_price = float(estimation.get("seller_price", 0.) or 0.)
    real_pct = (seller_price / total_cote * 100) if total_cote > 0 and seller_price > 0 else 0.
    theoretical_margin = total_cote - seller_price - fees if seller_price > 0 else total_cote - max_buy - fees
    return {
        "total_cote": total_cote,
        "pct": pct,
        "max_buy": max_buy,
        "seller_price": seller_price,
        "real_pct": real_pct,
        "theoretical_margin": theoretical_margin,
        "fees": fees,
        "safety": safety,
        "collection_cote": collection_cote,
        "total_all_cote": total_cote + collection_cote,
        "resale_cards": sum(int(c.get("quantity", 1) or 1) for c in resale_cards),
        "collection_cards": sum(int(c.get("quantity", 1) or 1) for c in collection_cards),
    }

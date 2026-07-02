"""Helpers for lot estimations."""

from datetime import datetime
import json
import os
import uuid

from data import maybe_create_prewrite_backup
from services.cloud_sync_service import save_synced_dataset
from utils import safe_write_json


DEFAULT_ESTIMATION_SOURCES = {
    "Vinted": 60.0,
    "Main propre": 65.0,
    "Brocante": 55.0,
}

QUICK_BULK_PURCHASE_UNIT_PRICE = 0.50
QUICK_BULK_RESALE_UNIT_PRICE = 2.00


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
            if card.get("entry_type") == "quick_bulk":
                bulk_type = str(card.get("bulk_type") or "").lower()
                card["bulk_type"] = "v" if bulk_type == "v" else "ex"
                card.setdefault("name", f"Lot {card['bulk_type'].upper()} basiques")
                card.setdefault("quantity", 1)
                card.setdefault("purchase_unit_price", QUICK_BULK_PURCHASE_UNIT_PRICE)
                card.setdefault("resale_unit_price", QUICK_BULK_RESALE_UNIT_PRICE)
                card.setdefault("cote", float(card.get("resale_unit_price") or QUICK_BULK_RESALE_UNIT_PRICE))
                card.setdefault("is_collection", False)
                continue
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


def is_quick_bulk_entry(card):
    return isinstance(card, dict) and card.get("entry_type") == "quick_bulk"


def quick_bulk_purchase_total(card):
    return float(card.get("purchase_unit_price", QUICK_BULK_PURCHASE_UNIT_PRICE) or 0.0) * int(card.get("quantity", 1) or 1)


def quick_bulk_resale_total(card):
    return float(card.get("resale_unit_price", QUICK_BULK_RESALE_UNIT_PRICE) or 0.0) * int(card.get("quantity", 1) or 1)


def load_estimations(estimations_file="lot_estimations.json"):
    should_write_default = False
    if os.path.exists(estimations_file):
        try:
            with open(estimations_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load estimations file: {e}")
            data = default_estimations_data()
            should_write_default = True
    else:
        data = default_estimations_data()
        should_write_default = True
    data = normalize_estimations_data(data)
    if should_write_default:
        safe_write_json(estimations_file, data, indent=2)
    return data


def save_estimations(data, estimations_file="lot_estimations.json"):
    data = normalize_estimations_data(data)
    maybe_create_prewrite_backup()
    save_synced_dataset("lot_estimations", data, indent=2)
    return data


def estimation_totals(estimation, settings):
    resale_cards = [c for c in estimation.get("cards", []) if not c.get("is_collection")]
    collection_cards = [c for c in estimation.get("cards", []) if c.get("is_collection")]
    quick_bulk_cards = [c for c in resale_cards if is_quick_bulk_entry(c)]
    regular_resale_cards = [c for c in resale_cards if not is_quick_bulk_entry(c)]
    quick_bulk_cost = sum(quick_bulk_purchase_total(c) for c in quick_bulk_cards)
    quick_bulk_value = sum(quick_bulk_resale_total(c) for c in quick_bulk_cards)
    regular_resale_cote = sum(float(c.get("cote", 0.) or 0.) * int(c.get("quantity", 1) or 1) for c in regular_resale_cards)
    total_cote = (
        regular_resale_cote
        + quick_bulk_value
    )
    collection_cote = sum(float(c.get("cote", 0.) or 0.) * int(c.get("quantity", 1) or 1) for c in collection_cards)
    source = estimation.get("source", settings.get("default_source", "Vinted"))
    pct = float(settings.get("sources", {}).get(source, 60.0) or 60.0)
    fees = 0.0
    safety = float(estimation.get("safety_eur", 0.) or 0.)
    max_buy = max(quick_bulk_cost + (regular_resale_cote * pct / 100) - fees - safety, 0.)
    seller_price = float(estimation.get("seller_price", 0.) or 0.) + quick_bulk_cost
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
        "quick_bulk_cost": quick_bulk_cost,
        "quick_bulk_value": quick_bulk_value,
    }

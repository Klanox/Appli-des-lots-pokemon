"""Official Cardmarket public download helpers for the Market module.

This service is deliberately read-only from Cardmarket's point of view. It
downloads public JSON files only after an explicit user action and stores them
in a local cache outside business datasets.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.request import Request, urlopen

from utils import APP_DIR, safe_write_json


CATALOG_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_6.json"
PRICE_GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"

CACHE_DIR = os.path.join(APP_DIR, "cache", "market_cardmarket")
STATE_FILE = os.path.join(APP_DIR, "market_cardmarket_source_state.json")
AUDIT_FILE = os.path.join(APP_DIR, "market_price_source_audit.json")
MAPPINGS_FILE = os.path.join(APP_DIR, "market_cardmarket_mappings.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict:
    return {
        "source_name": "Cardmarket Official Public Downloads",
        "source_status": "not_downloaded",
        "last_refresh_at": None,
        "catalog_file": None,
        "price_guide_file": None,
        "catalog_sha256": None,
        "price_guide_sha256": None,
        "catalog_row_count": 0,
        "price_row_count": 0,
        "mapping_status": "not_started",
        "price_policy_status": "price_policy_not_verified",
        "notes": [],
    }


def _default_mappings() -> dict:
    return {
        "version": 1,
        "mappings": [],
        "allowed_statuses": ["unmapped", "candidate", "needs_review", "confirmed", "rejected"],
        "rules": [
            "No mapping by name only.",
            "Set, number, language and variant ambiguity must remain needs_review.",
            "No price can be written without a confirmed mapping.",
        ],
    }


def _read_json(path: str, default: dict) -> dict:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def ensure_cardmarket_files() -> None:
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    if not os.path.exists(STATE_FILE):
        safe_write_json(STATE_FILE, _default_state(), indent=2)
    if not os.path.exists(MAPPINGS_FILE):
        safe_write_json(MAPPINGS_FILE, _default_mappings(), indent=2)


def load_cardmarket_source_state() -> dict:
    ensure_cardmarket_files()
    state = _read_json(STATE_FILE, _default_state())
    state.setdefault("source_name", "Cardmarket Official Public Downloads")
    state.setdefault("source_status", "not_downloaded")
    state.setdefault("price_policy_status", "price_policy_not_verified")
    return state


def load_cardmarket_mappings() -> dict:
    ensure_cardmarket_files()
    return _read_json(MAPPINGS_FILE, _default_mappings())


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_json_with_curl(url: str) -> bytes:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl is unavailable for the Windows TLS fallback")
    fd, tmp_path = tempfile.mkstemp(prefix="cardmarket_download_", suffix=".json")
    os.close(fd)
    try:
        subprocess.run(
            [
                curl,
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--ssl-no-revoke",
                "--max-time",
                "90",
                url,
                "--output",
                tmp_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        with open(tmp_path, "rb") as handle:
            return handle.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _download_json(url: str, target_path: str) -> tuple[int, str]:
    try:
        import requests
        import certifi
    except ImportError:
        request = Request(url, headers={"User-Agent": "PokeStock-Market/1.0"})
        with urlopen(request, timeout=90) as response:
            raw = response.read()
    else:
        try:
            response = requests.get(
                url,
                timeout=90,
                headers={"User-Agent": "PokeStock-Market/1.0"},
                verify=certifi.where(),
            )
            response.raise_for_status()
            raw = response.content
        except requests.exceptions.SSLError:
            raw = _download_json_with_curl(url)
    json.loads(raw.decode("utf-8"))
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="download_", suffix=".json", dir=str(Path(target_path).parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        os.replace(tmp_path, target_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return len(raw), _sha256(target_path)


def _rows_from_json(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("products", "priceGuides", "price_guide", "prices", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return [data]
    return []


def _load_rows(path: str | None) -> tuple[list, list[str], int]:
    if not path or not os.path.exists(path):
        return [], [], 0
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    rows = _rows_from_json(data)
    fields = sorted({str(key) for row in rows[:500] if isinstance(row, dict) for key in row.keys()})
    return rows, fields, os.path.getsize(path)


def _find_field(fields: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {field.lower(): field for field in fields}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def audit_official_cardmarket_source(state: dict | None = None, persist: bool = False) -> dict:
    state = state or load_cardmarket_source_state()
    catalog_rows, catalog_fields, catalog_size = _load_rows(state.get("catalog_file"))
    price_rows, price_fields, price_size = _load_rows(state.get("price_guide_file"))
    catalog_product_id = _find_field(catalog_fields, ("idProduct", "id_product", "productId", "product_id", "id"))
    price_product_id = _find_field(price_fields, ("idProduct", "id_product", "productId", "product_id", "id"))
    catalog_ids = {
        str(row.get(catalog_product_id))
        for row in catalog_rows
        if isinstance(row, dict) and catalog_product_id and row.get(catalog_product_id) is not None
    }
    price_ids = {
        str(row.get(price_product_id))
        for row in price_rows
        if isinstance(row, dict) and price_product_id and row.get(price_product_id) is not None
    }
    joined = len(catalog_ids & price_ids) if catalog_ids and price_ids else 0
    join_rate = joined / max(1, len(price_ids)) if price_ids else 0
    all_fields = set(catalog_fields) | set(price_fields)
    field_blob = " ".join(field.lower() for field in all_fields)
    has_language = any(token in field_blob for token in ("language", "lang", "idlanguage"))
    has_variant = any(token in field_blob for token in ("variant", "version", "foil", "reverse", "signed", "altered"))
    has_condition = any(token in field_blob for token in ("condition", "near", "mint", "idcondition"))
    has_low_price = any(field.lower() in {"lowprice", "low_price", "lowest", "minprice"} for field in all_fields)
    has_nm_exact = any("near" in field.lower() and "mint" in field.lower() for field in all_fields)
    has_shipping = any(token in field_blob for token in ("shipping", "shipment", "porto", "frais"))
    fr_nm_exact_supported = bool(has_language and has_variant and has_condition and has_nm_exact and has_shipping)
    audit = {
        "generated_at": _now_iso(),
        "source_name": "Cardmarket Official Public Downloads",
        "downloaded_at": state.get("last_refresh_at"),
        "catalog": {
            "file": state.get("catalog_file"),
            "size_bytes": catalog_size,
            "sha256": state.get("catalog_sha256"),
            "row_count": len(catalog_rows),
            "fields": catalog_fields,
            "product_id_field": catalog_product_id,
        },
        "price_guide": {
            "file": state.get("price_guide_file"),
            "size_bytes": price_size,
            "sha256": state.get("price_guide_sha256"),
            "row_count": len(price_rows),
            "fields": price_fields,
            "product_id_field": price_product_id,
        },
        "join": {
            "joined_product_ids": joined,
            "price_product_id_count": len(price_ids),
            "catalog_product_id_count": len(catalog_ids),
            "join_rate": join_rate,
        },
        "capabilities": {
            "product_id_present": bool(catalog_product_id and price_product_id),
            "explicit_language_present": has_language,
            "explicit_variant_present": has_variant,
            "explicit_condition_present": has_condition,
            "low_price_present": has_low_price,
            "near_mint_exact_present": has_nm_exact,
            "french_exact_present": has_language,
            "shipping_excluded_distinguishable": has_shipping,
        },
        "fr_nm_exact_policy": {
            "supported": fr_nm_exact_supported,
            "status": "price_policy_supported" if fr_nm_exact_supported else "price_policy_not_verified",
            "message": (
                "Les champs disponibles semblent permettre une politique FR NM exacte."
                if fr_nm_exact_supported
                else "Source officielle disponible ; politique exacte FR NM non vérifiée par les champs présents."
            ),
        },
    }
    if persist:
        safe_write_json(AUDIT_FILE, audit, indent=2)
    return audit


def refresh_official_cardmarket_data() -> dict:
    ensure_cardmarket_files()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    catalog_file = os.path.join(CACHE_DIR, f"products_singles_6_{stamp}.json")
    price_file = os.path.join(CACHE_DIR, f"price_guide_6_{stamp}.json")
    catalog_size, catalog_hash = _download_json(CATALOG_URL, catalog_file)
    price_size, price_hash = _download_json(PRICE_GUIDE_URL, price_file)
    state = _default_state()
    state.update(
        {
            "source_status": "downloaded",
            "last_refresh_at": _now_iso(),
            "catalog_file": catalog_file,
            "price_guide_file": price_file,
            "catalog_sha256": catalog_hash,
            "price_guide_sha256": price_hash,
            "notes": [
                f"Downloaded official catalog ({catalog_size} bytes).",
                f"Downloaded official price guide ({price_size} bytes).",
            ],
        }
    )
    audit = audit_official_cardmarket_source(state, persist=True)
    state["source_status"] = "schema_valid" if audit["catalog"]["row_count"] and audit["price_guide"]["row_count"] else "schema_invalid"
    state["catalog_row_count"] = audit["catalog"]["row_count"]
    state["price_row_count"] = audit["price_guide"]["row_count"]
    state["price_policy_status"] = audit["fr_nm_exact_policy"]["status"]
    state["mapping_status"] = "mapping_pending"
    safe_write_json(STATE_FILE, state, indent=2)
    if not os.path.exists(MAPPINGS_FILE):
        safe_write_json(MAPPINGS_FILE, _default_mappings(), indent=2)
    audit = audit_official_cardmarket_source(state, persist=True)
    return {"state": state, "audit": audit}

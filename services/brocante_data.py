"""Brocante dataset access.

This service owns brocantes.json only. It never reads or writes Market files and
never modifies stock data by itself.
"""

from __future__ import annotations

import json
import os

from core.brocante import default_brocantes_data, normalize_brocantes_data
from services.cloud_sync_service import safe_write_json_synced
from utils import APP_DIR


BROCANTES_FILE = os.path.join(APP_DIR, "brocantes.json")


def load_brocantes() -> dict:
    if not os.path.exists(BROCANTES_FILE):
        return default_brocantes_data()
    try:
        with open(BROCANTES_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return default_brocantes_data()
    return normalize_brocantes_data(payload)


def save_brocantes(data: dict) -> dict:
    payload = normalize_brocantes_data(data)
    safe_write_json_synced(BROCANTES_FILE, payload, indent=2)
    return payload

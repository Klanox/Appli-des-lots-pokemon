"""Read-only helpers for the official CardTrader Full API audit.

The service is intentionally narrow: only GET requests are allowed, and no
CardTrader response containing sensitive authentication data is persisted.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlencode
from typing import Any

import requests
import certifi

from utils import APP_DIR, safe_write_json


BASE_URL = "https://api.cardtrader.com/api/v2"
STATE_FILE = Path(APP_DIR) / "market_cardtrader_source_state.json"
AUDIT_FILE = Path(APP_DIR) / "market_cardtrader_price_audit.json"
ENV_FILE = Path(APP_DIR) / ".env"
ALLOWED_METHOD = "GET"
FORBIDDEN_PATH_PARTS = ("/cart/add", "/cart/remove", "/cart/purchase")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict:
    return {
        "source_status": "not_tested",
        "last_test_at": None,
        "auth_status": "not_tested",
        "read_only_test_completed": False,
        "mapping_status": "not_tested",
        "pricing_policy_status": "not_tested",
        "notes": ["read_only_test_only", "not_integrated_into_vmc"],
    }


def default_audit() -> dict:
    return {
        "source_name": "CardTrader Full API",
        "source_type": "official_marketplace_api",
        "tested_at": None,
        "auth_status": "not_tested",
        "request_count": 0,
        "overall_status": "not_ready_for_integration",
        "cards": [],
        "summary": {
            "pass": 0,
            "warn": 0,
            "fail": 0,
            "inconclusive": 0,
            "validated_blueprints": 0,
            "fr_nm_prices_found": 0,
        },
        "notes": [],
    }


def ensure_cardtrader_state_files() -> None:
    if not STATE_FILE.exists():
        safe_write_json(str(STATE_FILE), default_state(), indent=2)
    if not AUDIT_FILE.exists():
        safe_write_json(str(AUDIT_FILE), default_audit(), indent=2)


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def load_cardtrader_source_state() -> dict:
    ensure_cardtrader_state_files()
    state = read_json(STATE_FILE, default_state())
    for key, value in default_state().items():
        state.setdefault(key, value)
    return state


def load_cardtrader_price_audit() -> dict:
    ensure_cardtrader_state_files()
    audit = read_json(AUDIT_FILE, default_audit())
    for key, value in default_audit().items():
        audit.setdefault(key, value)
    return audit


def save_cardtrader_source_state(state: dict) -> None:
    safe_write_json(str(STATE_FILE), state, indent=2)


def save_cardtrader_price_audit(audit: dict) -> None:
    safe_write_json(str(AUDIT_FILE), audit, indent=2)


def load_cardtrader_token() -> str | None:
    if not ENV_FILE.exists():
        return None
    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "CARDTRADER_API_TOKEN":
            token = value.strip().strip('"').strip("'")
            return token or None
    return None


class CardTraderReadOnlyClient:
    def __init__(self, token: str):
        self.token = token
        self.request_count = 0

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if any(part in path for part in FORBIDDEN_PATH_PARTS):
            raise ValueError("Forbidden CardTrader path for read-only audit")
        url = BASE_URL + path
        headers = {"Authorization": f"Bearer {self.token}"}
        self.request_count += 1
        try:
            response = requests.request(
                ALLOWED_METHOD,
                url,
                headers=headers,
                params=params or {},
                timeout=45,
                verify=certifi.where(),
            )
            if response.status_code in (401, 403):
                raise PermissionError("CardTrader authentication rejected")
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()
        except requests.exceptions.SSLError:
            return self._get_with_curl(url, params or {})

    def _get_with_curl(self, url: str, params: dict[str, Any]) -> Any:
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if not curl:
            raise RuntimeError("curl is unavailable for the Windows TLS fallback")
        full_url = url + (("?" + urlencode(params, doseq=True)) if params else "")
        command = [
            curl,
            "--silent",
            "--show-error",
            "--location",
            "--ssl-no-revoke",
            "--max-time",
            "45",
            "-H",
            f"Authorization: Bearer {self.token}",
            "--write-out",
            "\n%{http_code}",
            full_url,
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        output = result.stdout
        if not output.strip():
            return {}
        body, _, status_text = output.rpartition("\n")
        status_code = int(status_text) if status_text.isdigit() else 0
        if status_code in (401, 403):
            raise PermissionError("CardTrader authentication rejected")
        if status_code >= 400:
            raise requests.HTTPError(f"CardTrader GET failed with HTTP {status_code}")
        if not body.strip():
            return {}
        return json.loads(body)


def auth_check() -> tuple[str, int]:
    token = load_cardtrader_token()
    if not token:
        return "auth_missing", 0
    client = CardTraderReadOnlyClient(token)
    try:
        client.get("/info")
    except PermissionError:
        return "auth_rejected", client.request_count
    except requests.RequestException:
        return "network_error", client.request_count
    return "auth_ok", client.request_count

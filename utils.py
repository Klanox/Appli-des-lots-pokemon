"""
Utility functions for PokéStock application.
"""

import json
import os
import unicodedata
import time
import requests
import tempfile
from services.vinted_service import fetch_listing_preview_image as _fetch_vinted_listing_preview_image

# Constants
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(APP_DIR, "data.json")
CARDS_CACHE_FILE = os.path.join(APP_DIR, "cards_cache.json")
CARDS_CACHE_TTL_SECONDS = 14 * 24 * 60 * 60
BACKUP_DIR = os.path.join(APP_DIR, "backups")
BACKUP_STATE_FILE = os.path.join(BACKUP_DIR, "backup_state.json")
ESTIMATIONS_FILE = os.path.join(APP_DIR, "estimations.json")
LOTS_ARCHIVES_FILE = os.path.join(APP_DIR, "lots_archives.json")


def normalize_name(name):
    """Normalize card names for search comparison."""
    if not name:
        return ""
    # Remove accents and convert to lowercase
    normalized = unicodedata.normalize('NFKD', str(name))
    return ''.join(c for c in normalized if not unicodedata.combining(c)).lower()


def parse_float_input(value, default=0.0):
    try:
        text = str(value).replace("€", "").replace(" ", "").replace(",", ".").strip()
        return float(text) if text else float(default)
    except (ValueError, TypeError) as e:
        return float(default)


def parse_int_input(value, default=1):
    try:
        text = str(value).replace(" ", "").strip()
        return max(int(float(text.replace(",", "."))), 0)
    except (ValueError, TypeError) as e:
        return int(default)


def fp(v):
    """Format float as price string."""
    return f"{v:.2f}€"


def safe_write_json(path, data, indent=None):
    """Write JSON atomically using temporary file."""
    folder = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(folder, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder, delete=False, suffix=".tmp") as tmp:
            tmp_path = tmp.name
            json.dump(data, tmp, ensure_ascii=False, indent=indent)
            tmp.flush()
            os.fsync(tmp.fileno())
        with open(tmp_path, "r", encoding="utf-8") as check:
            json.load(check)
        os.replace(tmp_path, path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception as e:
                print(f"Warning: Could not remove temporary file {tmp_path}: {e}")
                pass


def load_app_settings():
    path = "app_settings.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load app settings: {e}")
    return {}


def save_app_settings(settings):
    safe_write_json("app_settings.json", settings, indent=2)


def canal_key(canal):
    """Normalize canal name to a standard key."""
    raw = normalize_name(str(canal or "")).lower()
    if "dexify" in raw:
        return "dexify"
    if "pokedeal" in raw or ("poke" in raw and "deal" in raw):
        return "pokedeal"
    if "brocante" in raw or "broc" in raw:
        return "brocante"
    if "main propre" in raw or "main" in raw:
        return "main_propre"
    return "main_propre"


def cardmarket_search_url(name, number="", condition="", special=""):
    """Generate Cardmarket search URL."""
    query = " ".join(str(x or "").strip() for x in [name, number, condition, special] if str(x or "").strip())
    return "https://www.cardmarket.com/fr/Pokemon/Products/Search?searchString=" + requests.utils.quote(query)


def fetch_listing_preview_image(url):
    """Fetch listing preview image from a listing URL."""
    return _fetch_vinted_listing_preview_image(url)


def new_uid(prefix=""):
    """Generate unique ID."""
    return f"{prefix}{int(time.time() * 1000)}_{os.urandom(4).hex()}"

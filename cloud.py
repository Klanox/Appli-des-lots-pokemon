"""
Cloud sync functions for PokéStock application using Supabase.
"""

import streamlit as st
import tomllib
import os
import json
import hashlib
from datetime import datetime, timezone
from utils import safe_write_json

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

# Constants
APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_SECRETS_FILE = os.path.join(APP_DIR, ".streamlit", "secrets.toml")
SUPABASE_STATE_TABLE = "app_state"
SUPABASE_DATA_KEY = "data"
SUPABASE_ESTIMATIONS_KEY = "lot_estimations"
SUPABASE_MARKET_PRICE_CACHE_KEY = "estimation_market_price_cache"
CLOUD_SYNC_STATE_FILE = os.path.join(APP_DIR, "cloud_sync_state.json")


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def json_fingerprint(data):
    """Stable fingerprint for sync comparisons without logging content."""
    try:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        payload = str(type(data))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_cloud_sync_state():
    if not os.path.exists(CLOUD_SYNC_STATE_FILE):
        return {"files": {}}
    try:
        with open(CLOUD_SYNC_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("files", {})
            return data
    except Exception as e:
        try:
            st.session_state["cloud_sync_error"] = f"Etat cloud local illisible: {e}"
        except Exception:
            pass
    return {"files": {}}


def save_cloud_sync_state(state):
    if not isinstance(state, dict):
        state = {"files": {}}
    state.setdefault("files", {})
    safe_write_json(CLOUD_SYNC_STATE_FILE, state, indent=2)


def update_cloud_sync_state(key, *, data=None, source="", dirty=None, last_read=None, last_save=None):
    state = load_cloud_sync_state()
    entry = state.setdefault("files", {}).setdefault(key, {})
    if data is not None:
        entry["fingerprint"] = json_fingerprint(data)
    if source:
        entry["source"] = source
    if dirty is not None:
        entry["local_dirty"] = bool(dirty)
    if last_read:
        entry["last_read_at"] = last_read
    if last_save:
        entry["last_save_at"] = last_save
    save_cloud_sync_state(state)
    return entry


def cloud_sync_entry(key):
    return load_cloud_sync_state().get("files", {}).get(key, {})


@st.cache_resource(show_spinner=False)
def get_supabase_client():
    """Get Supabase client with caching."""
    if not cloud_sync_enabled():
        return None
    try:
        from supabase import create_client
        url = _secret_value("SUPABASE_URL", "supabase_url")
        key = _secret_value("SUPABASE_KEY", "supabase_anon_key")
        if url and key:
            return create_client(url, key)
    except Exception as e:
        st.session_state["cloud_sync_error"] = f"Supabase client error: {e}"
        return None


def _local_secrets():
    """Load secrets from local secrets.toml file."""
    try:
        if os.path.exists(LOCAL_SECRETS_FILE):
            with open(LOCAL_SECRETS_FILE, "r", encoding="utf-8-sig") as f:
                return tomllib.loads(f.read())
    except Exception as e:
        try:
            st.session_state["local_secrets_error"] = str(e)
        except Exception:
            pass
    return {}


def _secret_value(*names):
    """Get secret value from multiple sources in priority order."""
    local = _local_secrets()
    for name in names:
        try:
            if name in st.secrets:
                return st.secrets[name]
        except Exception:
            pass
        try:
            if name in local:
                return local[name]
        except Exception:
            pass
        try:
            value = os.environ.get(name)
            if value:
                return value
        except Exception:
            pass
    return None


def cloud_sync_enabled():
    """Check if cloud sync is enabled."""
    return bool(_secret_value("SUPABASE_URL", "supabase_url"))


def test_cloud_connection():
    """Test cloud connection."""
    if not cloud_sync_enabled():
        return False, "Cloud sync not configured"
    try:
        client = get_supabase_client()
        if client is None:
            return False, "Could not create Supabase client"
        res = client.table(SUPABASE_STATE_TABLE).select("key").limit(1).execute()
        return True, "Connection successful"
    except Exception as e:
        st.session_state["cloud_sync_error"] = f"Test cloud impossible: {e}"
        return False, st.session_state["cloud_sync_error"]


def load_cloud_json(key):
    """Load JSON data from cloud."""
    client = get_supabase_client()
    if client is None:
        return None
    try:
        res = client.table(SUPABASE_STATE_TABLE).select("data").eq("key", key).limit(1).execute()
        rows = getattr(res, "data", None) or []
        if rows:
            return rows[0].get("data")
    except Exception as e:
        st.session_state["cloud_sync_error"] = f"Lecture cloud impossible: {e}"
    return None


def load_cloud_json_meta(key):
    """Load lightweight cloud metadata for status display without saving anything."""
    client = get_supabase_client()
    if client is None:
        return {"available": False, "lots_count": None, "updated_at": "", "error": st.session_state.get("cloud_sync_error", "")}
    try:
        res = client.table(SUPABASE_STATE_TABLE).select("data, updated_at").eq("key", key).limit(1).execute()
        rows = getattr(res, "data", None) or []
        if not rows:
            return {"available": True, "lots_count": 0, "updated_at": "", "error": ""}
        data = rows[0].get("data")
        lots_count = len(data.get("lots", [])) if isinstance(data, dict) and isinstance(data.get("lots"), list) else None
        return {
            "available": True,
            "lots_count": lots_count,
            "updated_at": rows[0].get("updated_at", "") or "",
            "error": "",
        }
    except Exception as e:
        st.session_state["cloud_sync_error"] = f"Lecture statut cloud impossible: {e}"
        return {"available": False, "lots_count": None, "updated_at": "", "error": st.session_state["cloud_sync_error"]}


def save_cloud_json(key, data):
    """Save JSON data to cloud."""
    client = get_supabase_client()
    if client is None:
        return False
    try:
        client.table(SUPABASE_STATE_TABLE).upsert({
            "key": key,
            "data": data,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        st.session_state["cloud_sync_error"] = ""
        return True
    except Exception as e:
        st.session_state["cloud_sync_error"] = f"Écriture cloud impossible: {e}"
        return False

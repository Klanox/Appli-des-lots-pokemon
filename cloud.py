"""
Cloud sync functions for PokéStock application using Supabase.
"""

import streamlit as st
import tomllib
import os
from datetime import datetime, timezone

# Constants
APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_SECRETS_FILE = os.path.join(APP_DIR, ".streamlit", "secrets.toml")
SUPABASE_STATE_TABLE = "app_state"
SUPABASE_DATA_KEY = "data"
SUPABASE_ESTIMATIONS_KEY = "lot_estimations"


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

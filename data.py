"""
Data access functions for PokéStock application.
"""

import json
import os
import time
import shutil
from datetime import datetime
import streamlit as st
from utils import safe_write_json, DATA, BACKUP_DIR, BACKUP_STATE_FILE
from cloud import cloud_sync_enabled, load_cloud_json, save_cloud_json, SUPABASE_DATA_KEY
from services.perf_service import perf_count, perf_log

# Constants
APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOTS_ARCHIVES_FILE = os.path.join(APP_DIR, "lots_archives.json")


def ld():
    """Load data with caching and cloud sync support."""
    perf_count("ld")
    perf_start = time.perf_counter()
    perf_source = "unknown"
    local_data = None
    if os.path.exists(DATA):
        with open(DATA, "r", encoding="utf-8") as f:
            local_data = json.load(f)
        perf_source = "file"
    local_lots_count = len(local_data.get("lots", [])) if isinstance(local_data, dict) else 0

    # Streamlit garde parfois un cache vide apres un rerun.
    # Si le fichier local contient des lots, on ignore ce cache vide.
    if "data_cache" in st.session_state and not st.session_state.get("data_dirty", False):
        cached = st.session_state["data_cache"]
        cached_lots_count = len(cached.get("lots", [])) if isinstance(cached, dict) else 0
        if cached_lots_count == 0 and local_lots_count > 0:
            st.session_state.pop("data_cache", None)
        else:
            if not cloud_sync_enabled():
                perf_log("ld()", time.perf_counter() - perf_start, "cache")
                return cached
            last_cloud_load = float(st.session_state.get("data_cloud_loaded_at", 0) or 0)
            if time.time() - last_cloud_load < 10:
                perf_log("ld()", time.perf_counter() - perf_start, "cache/cloud_recent")
                return cached

    cloud_data = load_cloud_json(SUPABASE_DATA_KEY) if cloud_sync_enabled() else None
    cloud_lots_count = len(cloud_data.get("lots", [])) if isinstance(cloud_data, dict) else 0

    # Protection anti-perte : un cloud vide ou plus petit ne doit pas remplacer un local rempli.
    if (
        isinstance(cloud_data, dict)
        and cloud_data.get("lots") is not None
        and cloud_lots_count > 0
        and not (local_lots_count > 0 and cloud_lots_count < local_lots_count)
    ):
        d = cloud_data
        perf_source = "cloud"
        st.session_state["cloud_sync_active"] = True
        st.session_state["data_cloud_loaded_at"] = time.time()
    elif isinstance(cloud_data, dict) and cloud_data.get("lots") is not None and cloud_lots_count == 0 and local_lots_count > 0:
        d = local_data
        perf_source = "local/cloud_empty_ignored"
        try:
            st.warning("Cloud vide ignore : les donnees locales ont ete conservees.")
        except Exception:
            pass
    elif isinstance(cloud_data, dict) and cloud_data.get("lots") is not None and cloud_lots_count < local_lots_count and local_lots_count > 0:
        d = local_data
        perf_source = "local/cloud_smaller_ignored"
        try:
            st.warning("Cloud ignore : il contient moins de lots que le fichier local. Les donnees locales ont ete conservees.")
        except Exception:
            pass
    elif local_data is not None:
        d = local_data
        perf_source = "local"
    else:
        d = {"lots": []}
        perf_source = "empty"

    data_changed = False
    if ensure_card_ids(d):
        data_changed = True
    if sync_mixte_purchase_prices(d):
        data_changed = True
    if consolidate_storage_cards(d):
        data_changed = True
    if data_changed:
        maybe_create_prewrite_backup()
        safe_write_json(DATA, d)
        # Ne pas pousser automatiquement vers le cloud pendant le chargement :
        # cela evite qu'une correction locale au demarrage ecrase une version distante par accident.
    st.session_state["data_cache"] = d
    st.session_state["data_dirty"] = False
    perf_log("ld()", time.perf_counter() - perf_start, perf_source)
    return d


def sd(d):
    """Save data with cloud sync support."""
    if not isinstance(d, dict) or not isinstance(d.get("lots"), list):
        raise ValueError("Refus de sauvegarde : donnees invalides, cle 'lots' manquante.")
    if os.path.exists(DATA):
        try:
            with open(DATA, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing_lots_count = len(existing.get("lots", [])) if isinstance(existing, dict) else 0
        except Exception:
            existing_lots_count = 0
        new_lots_count = len(d.get("lots", []))
        if existing_lots_count > 0 and new_lots_count == 0:
            raise ValueError("Refus de sauvegarde : tentative d'ecraser un data.json rempli par 0 lot.")
    # Écriture sans indentation = 3x plus rapide
    maybe_create_prewrite_backup()
    safe_write_json(DATA, d)
    if cloud_sync_enabled():
        if save_cloud_json(SUPABASE_DATA_KEY, d):
            st.session_state["data_cloud_loaded_at"] = time.time()
    # Mettre à jour le cache et marquer comme propre
    st.session_state["data_cache"] = d
    st.session_state["data_dirty"] = False


def ensure_card_ids(d):
    """Ensure all cards have unique IDs."""
    changed = False
    for lot in d.get("lots", []):
        for card in lot.get("cards", []):
            if "card_uid" not in card:
                card["card_uid"] = f"{int(time.time() * 1000)}_{os.urandom(4).hex()}"
                changed = True
    return changed


def sync_mixte_purchase_prices(d):
    """Sync purchase prices for mixte lots."""
    changed = False
    for lot in d.get("lots", []):
        if lot.get("is_mixte") and lot.get("prix_achat_reel") is None:
            lot["prix_achat_reel"] = lot.get("prix_achat", 0)
            changed = True
    return changed


def consolidate_storage_cards(d):
    """Consolidate cards in storage lot."""
    changed = False
    storage_idx = None
    for i, lot in enumerate(d.get("lots", [])):
        if lot.get("nom") == "Stockage" or lot.get("is_storage"):
            storage_idx = i
            break
    
    if storage_idx is not None:
        storage_lot = d["lots"][storage_idx]
        card_map = {}
        for card in storage_lot.get("cards", []):
            key = (card.get("name", ""), card.get("number", ""), card.get("set", ""))
            if key not in card_map:
                card_map[key] = card
            else:
                # Merge quantities
                existing = card_map[key]
                existing["quantity"] = int(existing.get("quantity", 0)) + int(card.get("quantity", 0))
                existing["stored_quantity"] = int(existing.get("stored_quantity", 0)) + int(card.get("stored_quantity", 0))
                changed = True
        if changed:
            storage_lot["cards"] = list(card_map.values())
    
    return changed


def ensure_trade_lot(d):
    """Ensure trade lot exists."""
    for lot in d.get("lots", []):
        if lot.get("nom") in ("Trade", "🔄 Trade") or lot.get("is_trade"):
            return
    d.setdefault("lots", []).append({
        "nom": "🔄 Trade",
        "is_trade": True,
        "prix_achat": 0,
        "cards": []
    })


def ensure_storage_lot(d):
    """Ensure storage lot exists."""
    for lot in d.get("lots", []):
        if lot.get("nom") == "Stockage" or lot.get("is_storage"):
            return len(d["lots"]) - 1
    d.setdefault("lots", []).append({
        "nom": "Stockage",
        "is_storage": True,
        "prix_achat": 0,
        "cards": []
    })
    return len(d["lots"]) - 1


def ensure_system_lots(d):
    """Ensure all system lots exist."""
    changed = False
    if ensure_card_ids(d):
        changed = True
    ensure_trade_lot(d)
    ensure_storage_lot(d)
    return changed


def maybe_create_prewrite_backup():
    """Create backup before write if needed."""
    if os.path.exists(DATA):
        state = _load_backup_state()
        last = float(state.get("last_prewrite_backup_at", 0) or 0)
        if time.time() - last >= 3600:  # 1 hour
            path, _ = create_local_backup("prewrite", include_images=False)
            state["last_prewrite_backup_at"] = time.time()
            _save_backup_state(state)


def _load_backup_state():
    """Load backup state."""
    if not os.path.exists(BACKUP_STATE_FILE):
        return {}
    try:
        with open(BACKUP_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load backup state: {e}")
        return {}


def _save_backup_state(state):
    """Save backup state."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    safe_write_json(BACKUP_STATE_FILE, state, indent=2)


def create_local_backup(name, include_images=True):
    """Create local backup."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = os.path.join(BACKUP_DIR, f"{name}_{timestamp}")
    os.makedirs(target_dir, exist_ok=True)
    
    copied = 0
    if os.path.exists(DATA):
        shutil.copy2(DATA, os.path.join(target_dir, "data.json"))
        copied += 1
    
    if os.path.exists(LOTS_ARCHIVES_FILE):
        shutil.copy2(LOTS_ARCHIVES_FILE, os.path.join(target_dir, "lots_archives.json"))
        copied += 1
    
    if include_images:
        images_dir = os.path.join(APP_DIR, "images")
        if os.path.isdir(images_dir):
            target_images = os.path.join(target_dir, "images")
            shutil.copytree(images_dir, target_images, dirs_exist_ok=True)
            copied += len([f for f in os.listdir(images_dir) if os.path.isfile(os.path.join(images_dir, f))])
    
    manifest = {
        "timestamp": timestamp,
        "files_copied": copied,
        "includes_images": include_images
    }
    safe_write_json(os.path.join(target_dir, "backup_manifest.json"), manifest, indent=2)
    return target_dir, copied


def cleanup_old_backups(keep=60):
    """Clean up old backups, keeping only the most recent ones."""
    if not os.path.isdir(BACKUP_DIR):
        return
    entries = []
    for name in os.listdir(BACKUP_DIR):
        path = os.path.join(BACKUP_DIR, name)
        if os.path.isdir(path):
            entries.append((os.path.getmtime(path), path))
    entries.sort(reverse=True)
    for _, path in entries[keep:]:
        try:
            shutil.rmtree(path)
        except (IOError, OSError) as e:
            print(f"Warning: Could not remove backup directory {path}: {e}")
            pass


def maybe_create_weekly_backup():
    """Create weekly backup if needed."""
    state = _load_backup_state()
    last = float(state.get("last_weekly_backup_at", 0) or 0)
    if time.time() - last >= 7 * 24 * 60 * 60:
        path, copied = create_local_backup("weekly", include_images=False)
        state["last_weekly_backup_at"] = time.time()
        state["last_weekly_backup_path"] = path
        state["last_weekly_backup_files"] = copied
        _save_backup_state(state)

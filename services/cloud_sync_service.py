"""Unified cloud synchronization for Pokestock business JSON datasets."""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import json
import os
import time
from typing import Any

import streamlit as st

from cloud import (
    cloud_sync_enabled,
    cloud_sync_entry,
    get_supabase_client,
    json_fingerprint,
    load_cloud_json,
    remember_cloud_status,
    save_cloud_json,
    update_cloud_sync_state,
    utc_now_iso,
)
from utils import APP_DIR, safe_write_json

try:
    from cloud import load_cloud_json_with_client
except ImportError:
    def load_cloud_json_with_client(client, key):
        if client is None:
            return None
        res = client.table("app_state").select("data").eq("key", key).limit(1).execute()
        rows = getattr(res, "data", None) or []
        if rows:
            return rows[0].get("data")
        return None


@dataclass(frozen=True)
class SyncDataset:
    key: str
    filename: str
    label: str
    default: Any
    required_type: type = dict
    allow_empty: bool = True

    @property
    def path(self) -> str:
        return os.path.join(APP_DIR, self.filename)


SYNCED_DATASETS = {
    "data": SyncDataset("data", "data.json", "Stock/lots/ventes", {"lots": []}, dict, False),
    "lot_estimations": SyncDataset("lot_estimations", "lot_estimations.json", "Estimations", {"settings": {}, "estimations": []}, dict, True),
    "lots_archives": SyncDataset("lots_archives", "lots_archives.json", "Archives", [], list, True),
    "activity_state": SyncDataset("activity_state", "activity_state.json", "Activité", {}, dict, True),
    "monthly_goals": SyncDataset("monthly_goals", "monthly_goals.json", "Objectifs mensuels", {}, dict, True),
    "counters": SyncDataset("counters", "counters.json", "Compteurs", {}, dict, True),
    "vinted_drops": SyncDataset("vinted_drops", "vinted_drops.json", "Drops Vinted", {"drops": []}, dict, True),
    "brocantes": SyncDataset(
        "brocantes",
        "brocantes.json",
        "Brocantes",
        {"schema_version": 1, "sessions": [], "checklist_template": []},
        dict,
        True,
    ),
    "estimation_market_price_cache": SyncDataset(
        "estimation_market_price_cache",
        "estimation_market_price_cache.json",
        "Mémoire de cotes",
        {"version": 1, "entries": {}, "settings": {}},
        dict,
        True,
    ),
    "custom_card_images": SyncDataset(
        "custom_card_images",
        "custom_card_images.json",
        "Images personnalisées",
        {"schema_version": 1, "images": {}},
        dict,
        True,
    ),
}

_AUTO_PULL_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pokestock-cloud-sync")
_AUTO_PULL_FUTURE = None
_AUTO_PULL_STARTED_AT = 0.0


def _short_hash(value: str | None) -> str:
    return (value or "")[:10] or "-"


def _log_sync(dataset: SyncDataset, *, action: str, result: str, source: str = "", local_hash: str = "", cloud_hash: str = "", conflict: bool = False):
    event = {
        "dataset": dataset.filename,
        "action": action,
        "source": source,
        "result": result,
        "local_version": _short_hash(local_hash),
        "cloud_version": _short_hash(cloud_hash),
        "conflict": bool(conflict),
        "at": utc_now_iso(),
    }
    try:
        st.session_state.setdefault("cloud_sync_log", []).append(event)
        st.session_state["cloud_sync_log"] = st.session_state["cloud_sync_log"][-80:]
    except Exception:
        pass
    print(
        "[Cloud Sync] "
        f"dataset={dataset.filename} action={action} source={source or '-'} "
        f"result={result} local={event['local_version']} cloud={event['cloud_version']} "
        f"conflict={'yes' if conflict else 'no'} at={event['at']}",
        flush=True,
    )


def dataset_for_path(path: str) -> SyncDataset | None:
    try:
        full = os.path.abspath(path)
    except TypeError:
        return None
    for dataset in SYNCED_DATASETS.values():
        if os.path.abspath(dataset.path) == full or os.path.abspath(dataset.filename) == full:
            return dataset
    return None


def read_local_dataset(dataset: SyncDataset):
    if not os.path.exists(dataset.path):
        return None
    try:
        with open(dataset.path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def valid_dataset_payload(dataset: SyncDataset, payload) -> bool:
    if not isinstance(payload, dataset.required_type):
        return False
    if dataset.key == "data":
        return isinstance(payload.get("lots"), list) and (dataset.allow_empty or len(payload.get("lots", [])) > 0)
    return True


def write_local_dataset_from_cloud(dataset: SyncDataset, payload):
    safe_write_json(dataset.path, payload, indent=2 if dataset.key != "data" else None)
    update_cloud_sync_state(dataset.key, data=payload, source="cloud", dirty=False, last_read=utc_now_iso())
    if dataset.key == "data":
        st.session_state["data_cache"] = payload
        st.session_state["data_dirty"] = False
        st.session_state["data_cloud_loaded_at"] = time.time()


def save_synced_dataset(dataset_key: str, payload, *, indent=2):
    dataset = SYNCED_DATASETS[dataset_key]
    if not valid_dataset_payload(dataset, payload):
        raise ValueError(f"Dataset invalide: {dataset.filename}")
    local_payload = read_local_dataset(dataset)
    local_hash = json_fingerprint(local_payload) if valid_dataset_payload(dataset, local_payload) else ""
    new_hash = json_fingerprint(payload)
    if valid_dataset_payload(dataset, local_payload) and json_fingerprint(local_payload) == json_fingerprint(payload):
        _log_sync(dataset, action="save", source="local", result="identical", local_hash=local_hash, cloud_hash=new_hash)
        return {"local": False, "cloud": False, "skipped": True}
    safe_write_json(dataset.path, payload, indent=indent)
    if cloud_sync_enabled():
        if save_cloud_json(dataset.key, payload):
            update_cloud_sync_state(dataset.key, data=payload, source="local", dirty=False, last_save=utc_now_iso())
            _log_sync(dataset, action="push", source="local", result="saved", local_hash=new_hash, cloud_hash=new_hash)
            return {"local": True, "cloud": True}
        update_cloud_sync_state(dataset.key, data=payload, source="local", dirty=True)
        _log_sync(dataset, action="push", source="local", result="cloud_failed", local_hash=new_hash)
        return {"local": True, "cloud": False}
    update_cloud_sync_state(dataset.key, data=payload, source="local", dirty=True)
    _log_sync(dataset, action="push", source="local", result="cloud_disabled", local_hash=new_hash)
    return {"local": True, "cloud": False}


def safe_write_json_synced(path, data, indent=None):
    dataset = dataset_for_path(path)
    if dataset:
        return save_synced_dataset(dataset.key, data, indent=indent)
    safe_write_json(path, data, indent=indent)
    return {"local": True, "cloud": None}


def apply_cloud_dataset_payload(dataset: SyncDataset, cloud_payload, *, force=False):
    local_payload = read_local_dataset(dataset)
    if not valid_dataset_payload(dataset, cloud_payload):
        _log_sync(dataset, action="pull", source="local", result="fallback_local")
        return {"dataset": dataset.key, "filename": dataset.filename, "status": "fallback_local"}
    local_hash = json_fingerprint(local_payload) if local_payload is not None else ""
    cloud_hash = json_fingerprint(cloud_payload)
    entry = cloud_sync_entry(dataset.key)
    if not force and entry.get("local_dirty") and local_hash and local_hash != cloud_hash:
        st.session_state.setdefault("cloud_sync_conflicts", {})[dataset.key] = {
            "dataset": dataset.key,
            "filename": dataset.filename,
            "label": dataset.label,
            "local": entry,
            "cloud_fingerprint": cloud_hash,
            "at": utc_now_iso(),
        }
        _log_sync(dataset, action="pull", source="cloud", result="conflict", local_hash=local_hash, cloud_hash=cloud_hash, conflict=True)
        return {"dataset": dataset.key, "filename": dataset.filename, "status": "conflict", "changed": False}
    changed = local_hash != cloud_hash
    if local_hash != cloud_hash:
        write_local_dataset_from_cloud(dataset, cloud_payload)
    else:
        update_cloud_sync_state(dataset.key, data=cloud_payload, source="cloud", dirty=False, last_read=utc_now_iso())
        if dataset.key == "data":
            st.session_state["data_cache"] = cloud_payload
            st.session_state["data_dirty"] = False
            st.session_state["data_cloud_loaded_at"] = time.time()
    _log_sync(dataset, action="pull", source="cloud", result="loaded" if changed else "identical", local_hash=local_hash, cloud_hash=cloud_hash)
    return {"dataset": dataset.key, "filename": dataset.filename, "status": "loaded", "changed": changed}


def pull_dataset_from_cloud(dataset: SyncDataset, *, force=False):
    cloud_payload = load_cloud_json(dataset.key) if cloud_sync_enabled() else None
    return apply_cloud_dataset_payload(dataset, cloud_payload, force=force)


def pull_all_cloud_datasets(*, force=False):
    if not cloud_sync_enabled():
        return {"enabled": False, "loaded": [], "fallback_local": list(SYNCED_DATASETS), "conflicts": []}
    loaded = []
    changed = []
    fallback = []
    conflicts = []
    for dataset in SYNCED_DATASETS.values():
        result = pull_dataset_from_cloud(dataset, force=force)
        if result["status"] == "loaded":
            loaded.append(dataset.key)
            if result.get("changed"):
                changed.append(dataset.key)
        elif result["status"] == "conflict":
            conflicts.append(dataset.key)
        else:
            fallback.append(dataset.key)
    st.session_state["cloud_sync_last_pull"] = {"loaded": loaded, "changed": changed, "fallback_local": fallback, "conflicts": conflicts, "at": utc_now_iso()}
    print(
        f"[Cloud Sync] pull_all datasets={len(SYNCED_DATASETS)} loaded={len(loaded)} changed={len(changed)} "
        f"fallback_local={len(fallback)} conflicts={len(conflicts)}",
        flush=True,
    )
    return {"enabled": True, "loaded": loaded, "changed": changed, "fallback_local": fallback, "conflicts": conflicts}


def _fetch_all_cloud_payloads(client):
    payloads = {}
    errors = {}
    read_count = 0
    started_at = time.time()
    for dataset in SYNCED_DATASETS.values():
        try:
            payloads[dataset.key] = load_cloud_json_with_client(client, dataset.key)
            read_count += 1
        except Exception as exc:
            payloads[dataset.key] = None
            errors[dataset.key] = str(exc)
    return {
        "enabled": True,
        "payloads": payloads,
        "errors": errors,
        "read_count": read_count,
        "started_at": started_at,
        "finished_at": time.time(),
    }


def schedule_auto_pull_cloud_datasets(*, interval_seconds=60, debounce_seconds=5):
    """Schedule the periodic cloud pull without blocking the current rerun."""
    global _AUTO_PULL_FUTURE, _AUTO_PULL_STARTED_AT
    now = time.time()
    if not cloud_sync_enabled():
        return {"enabled": False, "skipped": True, "reason": "disabled", "changed": []}

    if _AUTO_PULL_FUTURE is not None and not _AUTO_PULL_FUTURE.done():
        return {"enabled": True, "skipped": True, "reason": "worker_running", "changed": []}

    previous_check = float(st.session_state.get("cloud_sync_last_maybe_pull_check_ts", 0) or 0)
    st.session_state["cloud_sync_last_maybe_pull_check_ts"] = now
    if previous_check and now - previous_check < debounce_seconds:
        return {"enabled": True, "skipped": True, "reason": "debounce", "changed": []}

    last = float(st.session_state.get("cloud_sync_last_auto_pull_ts", 0) or 0)
    if now - last < interval_seconds:
        return {"enabled": True, "skipped": True, "reason": "ttl", "changed": []}

    pending_since = float(st.session_state.get("cloud_sync_auto_pull_pending_since", 0) or 0)
    if not pending_since:
        st.session_state["cloud_sync_auto_pull_pending_since"] = now
        return {"enabled": True, "skipped": True, "reason": "pending", "changed": []}
    if now - pending_since < debounce_seconds:
        return {"enabled": True, "skipped": True, "reason": "pending_debounce", "changed": []}

    client = get_supabase_client()
    if client is None:
        return {"enabled": False, "skipped": True, "reason": "client_unavailable", "changed": []}

    st.session_state.pop("cloud_sync_auto_pull_pending_since", None)
    st.session_state["cloud_sync_last_auto_pull_ts"] = now
    _AUTO_PULL_STARTED_AT = now
    _AUTO_PULL_FUTURE = _AUTO_PULL_EXECUTOR.submit(_fetch_all_cloud_payloads, client)
    return {"enabled": True, "skipped": True, "reason": "scheduled_background", "changed": []}


def apply_finished_auto_pull_cloud_datasets(*, force=False):
    """Apply a completed background pull on the main Streamlit thread."""
    global _AUTO_PULL_FUTURE, _AUTO_PULL_STARTED_AT
    if _AUTO_PULL_FUTURE is None:
        return {"enabled": cloud_sync_enabled(), "skipped": True, "reason": "no_background_result", "changed": []}
    if not _AUTO_PULL_FUTURE.done():
        return {"enabled": cloud_sync_enabled(), "skipped": True, "reason": "worker_running", "changed": []}

    future = _AUTO_PULL_FUTURE
    started_at = _AUTO_PULL_STARTED_AT
    _AUTO_PULL_FUTURE = None
    _AUTO_PULL_STARTED_AT = 0.0
    try:
        fetched = future.result()
    except Exception as exc:
        st.session_state["full_cloud_pull_error"] = str(exc)
        remember_cloud_status(False, f"Lecture cloud impossible: {exc}")
        return {"enabled": True, "skipped": True, "reason": "worker_error", "error": str(exc), "changed": []}

    loaded = []
    changed = []
    fallback = []
    conflicts = []
    for dataset in SYNCED_DATASETS.values():
        result = apply_cloud_dataset_payload(dataset, fetched.get("payloads", {}).get(dataset.key), force=force)
        if result["status"] == "loaded":
            loaded.append(dataset.key)
            if result.get("changed"):
                changed.append(dataset.key)
        elif result["status"] == "conflict":
            conflicts.append(dataset.key)
        else:
            fallback.append(dataset.key)
    st.session_state["cloud_sync_last_pull"] = {"loaded": loaded, "changed": changed, "fallback_local": fallback, "conflicts": conflicts, "at": utc_now_iso()}
    if fetched.get("errors"):
        st.session_state["full_cloud_pull_error"] = "; ".join(f"{key}: {err}" for key, err in fetched["errors"].items())
        remember_cloud_status(False, st.session_state["full_cloud_pull_error"])
    else:
        st.session_state["full_cloud_pull_error"] = ""
        remember_cloud_status(True, "Synchronisation cloud prête")
    print(
        f"[Cloud Sync] background_pull_apply datasets={len(SYNCED_DATASETS)} loaded={len(loaded)} changed={len(changed)} "
        f"fallback_local={len(fallback)} conflicts={len(conflicts)} "
        f"worker_seconds={float(fetched.get('finished_at', 0) or 0) - float(fetched.get('started_at', started_at) or started_at):.3f}",
        flush=True,
    )
    return {
        "enabled": True,
        "background": True,
        "loaded": loaded,
        "changed": changed,
        "fallback_local": fallback,
        "conflicts": conflicts,
        "cloud_read": fetched.get("read_count", 0),
        "worker_seconds": float(fetched.get("finished_at", 0) or 0) - float(fetched.get("started_at", started_at) or started_at),
    }


def maybe_pull_all_cloud_datasets(*, interval_seconds=60, debounce_seconds=5):
    """Refresh local datasets from cloud without running a full pull in hot rerun bursts."""
    now = time.time()
    previous_check = float(st.session_state.get("cloud_sync_last_maybe_pull_check_ts", 0) or 0)
    st.session_state["cloud_sync_last_maybe_pull_check_ts"] = now
    if previous_check and now - previous_check < debounce_seconds:
        return {"enabled": cloud_sync_enabled(), "skipped": True, "reason": "debounce", "changed": []}
    last = float(st.session_state.get("cloud_sync_last_auto_pull_ts", 0) or 0)
    if now - last < interval_seconds:
        return {"enabled": cloud_sync_enabled(), "skipped": True, "reason": "ttl", "changed": []}
    pending_since = float(st.session_state.get("cloud_sync_auto_pull_pending_since", 0) or 0)
    if not pending_since:
        st.session_state["cloud_sync_auto_pull_pending_since"] = now
        return {"enabled": cloud_sync_enabled(), "skipped": True, "reason": "pending", "changed": []}
    if now - pending_since < debounce_seconds:
        return {"enabled": cloud_sync_enabled(), "skipped": True, "reason": "pending_debounce", "changed": []}
    st.session_state.pop("cloud_sync_auto_pull_pending_since", None)
    st.session_state["cloud_sync_last_auto_pull_ts"] = now
    result = pull_all_cloud_datasets(force=False)
    for dataset_key in result.get("changed", []):
        if dataset_key == "data":
            st.session_state.pop("data_cache", None)
            st.session_state["data_dirty"] = False
            st.session_state["data_cloud_loaded_at"] = now
    return result


def cloud_sync_status_summary():
    unsynced = []
    synced = 0
    last_read = ""
    last_save = ""
    for dataset in SYNCED_DATASETS.values():
        entry = cloud_sync_entry(dataset.key)
        if entry.get("local_dirty"):
            unsynced.append(dataset.filename)
        if entry.get("fingerprint"):
            synced += 1
        last_read = max(last_read, str(entry.get("last_read_at") or ""))
        last_save = max(last_save, str(entry.get("last_save_at") or ""))
    return {
        "total": len(SYNCED_DATASETS),
        "synced": synced,
        "unsynced": unsynced,
        "last_read": last_read,
        "last_save": last_save,
    }

"""Unified cloud synchronization for Pokestock business JSON datasets."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

import streamlit as st

from cloud import (
    cloud_sync_enabled,
    cloud_sync_entry,
    json_fingerprint,
    load_cloud_json,
    save_cloud_json,
    update_cloud_sync_state,
    utc_now_iso,
)
from utils import APP_DIR, safe_write_json


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
    "estimation_market_price_cache": SyncDataset(
        "estimation_market_price_cache",
        "estimation_market_price_cache.json",
        "Mémoire de cotes",
        {"version": 1, "entries": {}, "settings": {}},
        dict,
        True,
    ),
}


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


def save_synced_dataset(dataset_key: str, payload, *, indent=2):
    dataset = SYNCED_DATASETS[dataset_key]
    if not valid_dataset_payload(dataset, payload):
        raise ValueError(f"Dataset invalide: {dataset.filename}")
    safe_write_json(dataset.path, payload, indent=indent)
    if cloud_sync_enabled():
        if save_cloud_json(dataset.key, payload):
            update_cloud_sync_state(dataset.key, data=payload, source="local", dirty=False, last_save=utc_now_iso())
            print(f'[Cloud Sync] save dataset="{dataset.filename}" local=ok cloud=ok', flush=True)
            return {"local": True, "cloud": True}
        update_cloud_sync_state(dataset.key, data=payload, source="local", dirty=True)
        print(f'[Cloud Sync] save dataset="{dataset.filename}" local=ok cloud=failed', flush=True)
        return {"local": True, "cloud": False}
    update_cloud_sync_state(dataset.key, data=payload, source="local", dirty=True)
    print(f'[Cloud Sync] save dataset="{dataset.filename}" local=ok cloud=disabled', flush=True)
    return {"local": True, "cloud": False}


def safe_write_json_synced(path, data, indent=None):
    dataset = dataset_for_path(path)
    if dataset:
        return save_synced_dataset(dataset.key, data, indent=indent)
    safe_write_json(path, data, indent=indent)
    return {"local": True, "cloud": None}


def pull_dataset_from_cloud(dataset: SyncDataset, *, force=False):
    cloud_payload = load_cloud_json(dataset.key) if cloud_sync_enabled() else None
    local_payload = read_local_dataset(dataset)
    if not valid_dataset_payload(dataset, cloud_payload):
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
        print(f'[Cloud Sync] conflict dataset="{dataset.filename}" local_dirty=yes remote_changed=yes', flush=True)
        return {"dataset": dataset.key, "filename": dataset.filename, "status": "conflict"}
    if local_hash != cloud_hash:
        write_local_dataset_from_cloud(dataset, cloud_payload)
    else:
        update_cloud_sync_state(dataset.key, data=cloud_payload, source="cloud", dirty=False, last_read=utc_now_iso())
    return {"dataset": dataset.key, "filename": dataset.filename, "status": "loaded"}


def pull_all_cloud_datasets(*, force=False):
    if not cloud_sync_enabled():
        return {"enabled": False, "loaded": [], "fallback_local": list(SYNCED_DATASETS), "conflicts": []}
    loaded = []
    fallback = []
    conflicts = []
    for dataset in SYNCED_DATASETS.values():
        result = pull_dataset_from_cloud(dataset, force=force)
        if result["status"] == "loaded":
            loaded.append(dataset.key)
        elif result["status"] == "conflict":
            conflicts.append(dataset.key)
        else:
            fallback.append(dataset.key)
    st.session_state["cloud_sync_last_pull"] = {"loaded": loaded, "fallback_local": fallback, "conflicts": conflicts, "at": utc_now_iso()}
    print(
        f"[Cloud Sync] startup pull datasets={len(SYNCED_DATASETS)} loaded={len(loaded)} "
        f"fallback_local={len(fallback)} conflicts={len(conflicts)}",
        flush=True,
    )
    return {"enabled": True, "loaded": loaded, "fallback_local": fallback, "conflicts": conflicts}


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

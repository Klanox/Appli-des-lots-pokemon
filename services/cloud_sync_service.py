"""Unified cloud synchronization for Pokestock business JSON datasets."""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import os
import threading
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
    save_cloud_json_with_client,
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
    # Le local est remplace par le cloud : un envoi en attente ecraserait cette version.
    discard_pending_cloud_push(dataset.key)
    with DATA_WRITE_LOCK:
        safe_write_json(dataset.path, payload, indent=2 if dataset.key != "data" else None)
    update_cloud_sync_state(dataset.key, data=payload, source="cloud", dirty=False, last_read=utc_now_iso())
    if dataset.key == "data":
        st.session_state["data_cache"] = payload
        st.session_state["data_dirty"] = False
        st.session_state["data_cloud_loaded_at"] = time.time()
        remember_data_base(payload)


# --------------------------------------------------------------------------
# Version de data.json vue par la session (protection entre sessions)
#
# Chaque session garde sa copie en memoire (st.session_state["data_cache"]). On memorise
# aussi le contenu du fichier tel que cette session l'a vu pour la derniere fois
# ("base") : au moment de sauvegarder, data.sd() compare le fichier a cette base et
# fusionne (services/data_merge_service.py) si une autre session a ecrit entre-temps.
# --------------------------------------------------------------------------
DATA_WRITE_LOCK = threading.RLock()


def data_file_signature():
    """(mtime_ns, taille) de data.json, ou None s'il n'existe pas."""
    try:
        stat = os.stat(SYNCED_DATASETS["data"].path)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def remember_data_base(payload):
    """A appeler quand la copie de session == contenu du fichier data.json."""
    try:
        st.session_state["data_base_json"] = json.dumps(payload, ensure_ascii=False)
        st.session_state["data_base_stat"] = data_file_signature()
    except Exception:
        st.session_state.pop("data_base_json", None)
        st.session_state.pop("data_base_stat", None)


# --------------------------------------------------------------------------
# Envoi cloud en arriere-plan (write-behind)
#
# - Le fichier local est ecrit de facon synchrone par save_synced_dataset.
# - L'envoi Supabase est mis en file (un seul element par jeu de donnees : la
#   derniere version remplace la precedente) puis envoye par un fil unique apres
#   un court delai de regroupement.
# - Le fil n'ecrit JAMAIS dans st.session_state ni dans cloud_sync_state.json :
#   il depose son resultat dans _PUSH_RESULTS, applique par le main thread
#   (apply_finished_cloud_pushes) au rechargement suivant.
# - Tant que l'envoi n'est pas confirme, cloud_sync_state.json garde
#   local_dirty=True et push_pending=True ; au demarrage suivant,
#   flush_pending_cloud_pushes renvoie ces jeux de donnees.
# --------------------------------------------------------------------------
_PUSH_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pokestock-cloud-push")
_PUSH_LOCK = threading.Lock()
_PUSH_PENDING: dict = {}
_PUSH_INFLIGHT: dict = {}
_PUSH_RESULTS: list = []
_PUSH_SEQ = itertools.count(1)
_PUSH_WORKER_RUNNING = False
_PUSH_STATS = {"queued": 0, "coalesced": 0, "sent": 0, "failed": 0}
_PUSH_LAST = {"ok_at": 0.0, "error": "", "error_at": 0.0}
_LAST_LOCAL_CHANGE: dict = {}
# Heure (fin de requete) a laquelle un envoi reussi a mis le cloud a jour avec la derniere version locale.
_CLOUD_CONFIRMED_AT: dict = {}
_PUSH_DEBOUNCE_SECONDS = 2.0   # attente apres la derniere modification avant l'envoi
_PUSH_MAX_WAIT_SECONDS = 10.0  # delai maximal avant envoi meme si les modifications continuent
_PUSH_RETRY_SECONDS = 30.0     # nouvel essai automatique apres un echec


def _background_push_enabled() -> bool:
    return os.environ.get("POKESTOCK_CLOUD_PUSH_ASYNC", "1").strip().lower() not in {"0", "false", "no", "off"}


def _enqueue_cloud_push(dataset: SyncDataset, body: str, fingerprint: str, client):
    global _PUSH_WORKER_RUNNING
    now = time.time()
    with _PUSH_LOCK:
        previous = _PUSH_PENDING.get(dataset.key)
        _PUSH_STATS["queued"] += 1
        if previous is not None:
            _PUSH_STATS["coalesced"] += 1
        _PUSH_PENDING[dataset.key] = {
            "body": body,
            "fingerprint": fingerprint,
            "client": client,
            "queued_at": now,
            "first_queued_at": previous["first_queued_at"] if previous else now,
            "seq": next(_PUSH_SEQ),
        }
        if not _PUSH_WORKER_RUNNING:
            _PUSH_WORKER_RUNNING = True
            _PUSH_EXECUTOR.submit(_push_worker)


def _push_worker():
    """Fil d'arriere-plan : vide la file d'envoi. Ne touche pas a Streamlit."""
    global _PUSH_WORKER_RUNNING
    try:
        while True:
            key = None
            item = None
            wait = 0.25
            with _PUSH_LOCK:
                if not _PUSH_PENDING:
                    _PUSH_WORKER_RUNNING = False
                    return
                now = time.time()
                for candidate, entry in _PUSH_PENDING.items():
                    due = min(
                        entry["queued_at"] + _PUSH_DEBOUNCE_SECONDS,
                        entry["first_queued_at"] + _PUSH_MAX_WAIT_SECONDS,
                    )
                    if now >= due:
                        key, item = candidate, entry
                        break
                    wait = min(wait, max(0.02, due - now))
                if key is not None:
                    _PUSH_PENDING.pop(key, None)
                    _PUSH_INFLIGHT[key] = item
            if key is None:
                time.sleep(wait)
                continue
            started = time.time()
            ok, error = False, ""
            try:
                save_cloud_json_with_client(item["client"], key, json.loads(item["body"]))
                ok = True
            except BaseException as exc:  # noqa: BLE001 - le resultat est remonte au main thread
                error = f"{type(exc).__name__}: {exc}"[:300]
            finished = time.time()
            with _PUSH_LOCK:
                _PUSH_INFLIGHT.pop(key, None)
                _PUSH_RESULTS.append({
                    "key": key,
                    "ok": ok,
                    "error": error,
                    "fingerprint": item["fingerprint"],
                    "seq": item["seq"],
                    "started_at": started,
                    "finished_at": finished,
                    "bytes": len(item["body"]),
                })
                if ok:
                    _CLOUD_CONFIRMED_AT[key] = finished
                    _PUSH_STATS["sent"] += 1
                    _PUSH_LAST["ok_at"] = finished
                    _PUSH_LAST["error"] = ""
                else:
                    _PUSH_STATS["failed"] += 1
                    _PUSH_LAST["error"] = error
                    _PUSH_LAST["error_at"] = finished
            print(
                f"[Cloud Sync] background_push dataset={key} ok={'yes' if ok else 'no'} "
                f"seconds={finished - started:.3f} kb={len(item['body']) // 1024}"
                + (f" error={error}" if error else ""),
                flush=True,
            )
    finally:
        with _PUSH_LOCK:
            _PUSH_WORKER_RUNNING = False
            leftover = bool(_PUSH_PENDING)
            if leftover:
                _PUSH_WORKER_RUNNING = True
                _PUSH_EXECUTOR.submit(_push_worker)


def is_cloud_push_pending(dataset_key: str) -> bool:
    """Vrai si un envoi cloud est en file ou en cours pour ce jeu de donnees."""
    with _PUSH_LOCK:
        return dataset_key in _PUSH_PENDING or dataset_key in _PUSH_INFLIGHT


def discard_pending_cloud_push(dataset_key: str):
    """Abandonne l'envoi en file (ex. version cloud explicitement recuperee)."""
    with _PUSH_LOCK:
        _PUSH_PENDING.pop(dataset_key, None)


def cloud_read_may_be_stale(dataset_key: str, read_started: float) -> bool:
    """Vrai si une lecture cloud demarree a `read_started` peut etre plus ancienne que le local.

    Une lecture ne reflete la derniere version locale que si elle a commence APRES la fin de
    l'envoi qui l'a mise dans le cloud. Donc elle est suspecte si, depuis son demarrage :
      - le local a ete modifie (l'envoi n'est pas encore parti) ; ou
      - un envoi vient de se terminer (la lecture a pu photographier le cloud avant lui) ; ou
      - un envoi est en file / en cours.
    Le marqueur "en attente" ne suffit pas : il est leve par le thread principal, apres coup.
    """
    if not read_started:
        return False
    with _PUSH_LOCK:
        busy = dataset_key in _PUSH_PENDING or dataset_key in _PUSH_INFLIGHT
        confirmed = _CLOUD_CONFIRMED_AT.get(dataset_key, 0.0)
    if busy:
        return True
    return max(_LAST_LOCAL_CHANGE.get(dataset_key, 0.0), confirmed) >= read_started


def apply_finished_cloud_pushes():
    """Main thread : applique les resultats d'envoi (etat disque + statut session)."""
    with _PUSH_LOCK:
        results = list(_PUSH_RESULTS)
        _PUSH_RESULTS.clear()
    for result in results:
        key = result["key"]
        dataset = SYNCED_DATASETS.get(key)
        if dataset is None:
            continue
        if result["ok"]:
            if is_cloud_push_pending(key):
                # Une version plus recente attend encore : le jeu reste "a envoyer".
                update_cloud_sync_state(key, last_save=utc_now_iso(), push_error="")
            else:
                update_cloud_sync_state(key, fingerprint=result["fingerprint"], source="local", dirty=False, push_pending=False, last_save=utc_now_iso(), push_error="")
            remember_cloud_status(True, "Synchronisation cloud prête")
            try:
                st.session_state["cloud_sync_error"] = ""
                if key == "data":
                    st.session_state["data_cloud_loaded_at"] = time.time()
            except Exception:
                pass
            _log_sync(dataset, action="push", source="local", result="saved_background", cloud_hash=result["fingerprint"])
        else:
            update_cloud_sync_state(key, dirty=True, push_pending=True, push_error=result["error"])
            message = f"Écriture cloud impossible ({dataset.filename}) : {result['error']}"
            remember_cloud_status(False, message)
            try:
                st.session_state["cloud_sync_error"] = message
            except Exception:
                pass
            _log_sync(dataset, action="push", source="local", result="cloud_failed_background", cloud_hash=result["fingerprint"])
    return results


def flush_pending_cloud_pushes(*, retry_after_seconds: float = 0.0):
    """Renvoie les jeux marques push_pending qui ne sont ni en file ni en cours.

    - Au demarrage (retry_after_seconds=0) : reprend les envois interrompus.
    - Ensuite (retry_after_seconds=_PUSH_RETRY_SECONDS) : nouvel essai apres un echec.
    Retourne la liste des jeux remis en file.
    """
    if not cloud_sync_enabled() or not _background_push_enabled():
        return []
    requeued = []
    now = time.time()
    for dataset in SYNCED_DATASETS.values():
        entry = cloud_sync_entry(dataset.key)
        if not entry.get("push_pending"):
            continue
        if is_cloud_push_pending(dataset.key):
            continue
        if retry_after_seconds and entry.get("push_error"):
            last_error_ts = _parse_iso_ts(entry.get("push_error_at"))
            if last_error_ts and now - last_error_ts < retry_after_seconds:
                continue
        elif retry_after_seconds and not entry.get("push_error"):
            # Envoi interrompu sans erreur memorisee : repris au prochain demarrage.
            continue
        payload = read_local_dataset(dataset)
        if not valid_dataset_payload(dataset, payload):
            continue
        client = get_supabase_client()
        if client is None:
            continue
        body = json.dumps(payload, ensure_ascii=False)
        _LAST_LOCAL_CHANGE[dataset.key] = now
        _enqueue_cloud_push(dataset, body, json_fingerprint(payload), client)
        update_cloud_sync_state(dataset.key, push_pending=True)
        _log_sync(dataset, action="push", source="local", result="requeued")
        requeued.append(dataset.key)
    return requeued


def _parse_iso_ts(value):
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return 0.0


def cloud_push_status():
    """Etat de l'envoi pour l'indicateur : idle / sending / error (aucun acces Streamlit)."""
    if not cloud_sync_enabled():
        return {"enabled": False, "state": "idle", "sending": [], "pending": [], "error": "", "last_ok_at": 0.0, "stats": dict(_PUSH_STATS)}
    with _PUSH_LOCK:
        sending = sorted(set(_PUSH_PENDING) | set(_PUSH_INFLIGHT))
        error = _PUSH_LAST["error"]
        stats = dict(_PUSH_STATS)
        ok_at = _PUSH_LAST["ok_at"]
    pending_state = [k for k in SYNCED_DATASETS if cloud_sync_entry(k).get("push_pending")]
    errors = {k: cloud_sync_entry(k).get("push_error") for k in pending_state if cloud_sync_entry(k).get("push_error")}
    if sending:
        state = "sending"
    elif errors:
        state = "error"
    elif pending_state:
        state = "sending"  # envoi a reprendre (demarrage) : considere en cours
    else:
        state = "idle"
    return {
        "enabled": True,
        "state": state,
        "sending": sending,
        "pending": pending_state,
        "error": next(iter(errors.values()), error if state == "error" else ""),
        "last_ok_at": ok_at,
        "stats": stats,
    }


def wait_for_cloud_pushes(timeout: float = 15.0) -> bool:
    """Attend la fin des envois en file (tests / fermeture propre)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _PUSH_LOCK:
            busy = bool(_PUSH_PENDING or _PUSH_INFLIGHT)
        if not busy:
            return True
        time.sleep(0.05)
    return False


def save_synced_dataset(dataset_key: str, payload, *, indent=2):
    """Ecrit le fichier local tout de suite ; l'envoi cloud part en arriere-plan.

    Retourne {"local": True, "cloud": False, "queued": True} quand l'envoi est
    differe (confirmation via apply_finished_cloud_pushes / cloud_push_status).
    """
    dataset = SYNCED_DATASETS[dataset_key]
    if not valid_dataset_payload(dataset, payload):
        raise ValueError(f"Dataset invalide: {dataset.filename}")
    local_payload = read_local_dataset(dataset)
    new_hash = json_fingerprint(payload)
    local_valid = valid_dataset_payload(dataset, local_payload)
    local_hash = json_fingerprint(local_payload) if local_valid else ""
    if local_valid and local_hash == new_hash:
        _log_sync(dataset, action="save", source="local", result="identical", local_hash=local_hash, cloud_hash=new_hash)
        return {"local": False, "cloud": False, "skipped": True}
    safe_write_json(dataset.path, payload, indent=indent)
    _LAST_LOCAL_CHANGE[dataset.key] = time.time()
    if cloud_sync_enabled():
        client = get_supabase_client() if _background_push_enabled() else None
        if client is not None:
            # Contenu fige (copie serialisee) au moment de la demande.
            body = json.dumps(payload, ensure_ascii=False)
            update_cloud_sync_state(dataset.key, fingerprint=new_hash, source="local", dirty=True, push_pending=True)
            _enqueue_cloud_push(dataset, body, new_hash, client)
            _log_sync(dataset, action="push", source="local", result="queued", local_hash=new_hash)
            return {"local": True, "cloud": False, "queued": True}
        # Repli synchrone (arriere-plan desactive ou client indisponible) : comportement historique.
        if save_cloud_json(dataset.key, payload):
            update_cloud_sync_state(dataset.key, fingerprint=new_hash, source="local", dirty=False, last_save=utc_now_iso())
            _log_sync(dataset, action="push", source="local", result="saved", local_hash=new_hash, cloud_hash=new_hash)
            return {"local": True, "cloud": True}
        update_cloud_sync_state(dataset.key, fingerprint=new_hash, source="local", dirty=True)
        _log_sync(dataset, action="push", source="local", result="cloud_failed", local_hash=new_hash)
        return {"local": True, "cloud": False}
    update_cloud_sync_state(dataset.key, fingerprint=new_hash, source="local", dirty=True)
    _log_sync(dataset, action="push", source="local", result="cloud_disabled", local_hash=new_hash)
    return {"local": True, "cloud": False}


def safe_write_json_synced(path, data, indent=None):
    dataset = dataset_for_path(path)
    if dataset:
        return save_synced_dataset(dataset.key, data, indent=indent)
    safe_write_json(path, data, indent=indent)
    return {"local": True, "cloud": None}


def apply_cloud_dataset_payload(dataset: SyncDataset, cloud_payload, *, force=False, read_started=None):
    local_payload = read_local_dataset(dataset)
    if not valid_dataset_payload(dataset, cloud_payload):
        _log_sync(dataset, action="pull", source="local", result="fallback_local")
        return {"dataset": dataset.key, "filename": dataset.filename, "status": "fallback_local"}
    entry = cloud_sync_entry(dataset.key)
    if not force and (is_cloud_push_pending(dataset.key) or entry.get("push_pending")):
        # Modification locale pas encore confirmee cote cloud : ne jamais l'ecraser.
        _log_sync(dataset, action="pull", source="cloud", result="skipped_push_pending")
        return {"dataset": dataset.key, "filename": dataset.filename, "status": "push_pending", "changed": False}
    if not force and read_started and cloud_read_may_be_stale(dataset.key, read_started):
        # La lecture a commence avant la fin de l'envoi (ou avant la derniere modif locale) :
        # elle peut contenir une version plus ancienne que le local. Prochaine lecture dans <= 60 s.
        _log_sync(dataset, action="pull", source="cloud", result="skipped_stale_read")
        return {"dataset": dataset.key, "filename": dataset.filename, "status": "stale_read", "changed": False}
    local_hash = json_fingerprint(local_payload) if local_payload is not None else ""
    cloud_hash = json_fingerprint(cloud_payload)
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
            remember_data_base(cloud_payload)
    _log_sync(dataset, action="pull", source="cloud", result="loaded" if changed else "identical", local_hash=local_hash, cloud_hash=cloud_hash)
    return {"dataset": dataset.key, "filename": dataset.filename, "status": "loaded", "changed": changed}


def pull_dataset_from_cloud(dataset: SyncDataset, *, force=False):
    read_started = time.time()
    cloud_payload = load_cloud_json(dataset.key) if cloud_sync_enabled() else None
    return apply_cloud_dataset_payload(dataset, cloud_payload, force=force, read_started=read_started)


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
    fetch_started = float(fetched.get("started_at", started_at) or started_at or 0)
    for dataset in SYNCED_DATASETS.values():
        if not force and cloud_read_may_be_stale(dataset.key, fetch_started):
            # Ecriture locale OU fin d'envoi posterieure au debut de cette lecture : la copie
            # cloud peut etre plus ancienne que le local, on ne la reapplique jamais.
            _log_sync(dataset, action="pull", source="cloud", result="skipped_local_newer")
            fallback.append(dataset.key)
            continue
        result = apply_cloud_dataset_payload(dataset, fetched.get("payloads", {}).get(dataset.key), force=force, read_started=fetch_started)
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
    sending = []
    synced = 0
    last_read = ""
    last_save = ""
    for dataset in SYNCED_DATASETS.values():
        entry = cloud_sync_entry(dataset.key)
        if entry.get("push_pending"):
            sending.append(dataset.filename)
        elif entry.get("local_dirty"):
            unsynced.append(dataset.filename)
        if entry.get("fingerprint"):
            synced += 1
        last_read = max(last_read, str(entry.get("last_read_at") or ""))
        last_save = max(last_save, str(entry.get("last_save_at") or ""))
    return {
        "total": len(SYNCED_DATASETS),
        "synced": synced,
        "unsynced": unsynced,
        "sending": sending,
        "last_read": last_read,
        "last_save": last_save,
    }

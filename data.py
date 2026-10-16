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
from cloud import (
    cloud_sync_enabled,
    load_cloud_json,
    save_cloud_json,
    SUPABASE_DATA_KEY,
    cloud_sync_entry,
    json_fingerprint,
    update_cloud_sync_state,
    utc_now_iso,
)
from services.cloud_sync_service import (
    DATA_WRITE_LOCK,
    SYNCED_DATASETS,
    cloud_read_may_be_stale,
    data_file_signature,
    is_cloud_push_pending,
    pull_dataset_from_cloud,
    remember_data_base,
    save_synced_dataset,
)
from services.data_merge_service import merge3
from services.card_extension_service import complete_new_cards_extension
from services.perf_service import perf_count, perf_log

# Constants
APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOTS_ARCHIVES_FILE = os.path.join(APP_DIR, "lots_archives.json")


def _read_local_data_file():
    if not os.path.exists(DATA):
        return None
    with open(DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def _valid_data_snapshot(data):
    return isinstance(data, dict) and isinstance(data.get("lots"), list)


def _data_summary(data):
    lots = data.get("lots", []) if isinstance(data, dict) else []
    collection_lots = sum(1 for lot in lots if lot.get("is_collection_system") or lot.get("is_collection_lot") or lot.get("nom") == "Collection")
    return {"lots": len(lots), "collection_lots": collection_lots}


def _set_cloud_status(*, source, status, message="", cloud_data=None, local_data=None):
    st.session_state["cloud_sync_status"] = {
        "source": source,
        "status": status,
        "message": message,
        "cloud": _data_summary(cloud_data) if cloud_data is not None else None,
        "local": _data_summary(local_data) if local_data is not None else None,
        "at": utc_now_iso(),
    }


def _write_local_cloud_snapshot(data):
    safe_write_json(DATA, data)
    update_cloud_sync_state(SUPABASE_DATA_KEY, data=data, source="cloud", dirty=False, last_read=utc_now_iso())
    st.session_state["data_cloud_loaded_at"] = time.time()
    st.session_state["data_cache"] = data
    st.session_state["data_dirty"] = False


def pull_data_from_cloud():
    """Explicit user action: replace local data.json with latest valid cloud data."""
    if not cloud_sync_enabled():
        return {"ok": False, "message": "Synchronisation cloud désactivée.", "summary": None}
    cloud_data = load_cloud_json(SUPABASE_DATA_KEY)
    if not _valid_data_snapshot(cloud_data) or len(cloud_data.get("lots", [])) == 0:
        _set_cloud_status(source="local", status="pull_failed", message="Cloud vide ou invalide.", cloud_data=cloud_data)
        return {"ok": False, "message": "Cloud vide ou invalide.", "summary": _data_summary(cloud_data) if isinstance(cloud_data, dict) else None}
    pull_dataset_from_cloud(SYNCED_DATASETS["data"], force=True)
    _set_cloud_status(source="cloud", status="manual_pull_success", message="Dernière version cloud récupérée.", cloud_data=cloud_data)
    print(f"[Cloud Sync] pull status=success files=data lots={len(cloud_data.get('lots', []))}", flush=True)
    return {"ok": True, "message": "Dernière version cloud récupérée.", "summary": _data_summary(cloud_data)}


def ld():
    """Load data with caching and cloud sync support."""
    perf_count("ld")
    perf_start = time.perf_counter()
    perf_source = "unknown"

    if "data_cache" in st.session_state and not st.session_state.get("data_dirty", False):
        cached = st.session_state["data_cache"]
        if _valid_data_snapshot(cached) and len(cached.get("lots", [])) > 0:
            perf_log("ld()", time.perf_counter() - perf_start, "cache/session_first")
            return cached

    local_data = _read_local_data_file()
    if local_data is not None:
        perf_source = "file"
    local_lots_count = len(local_data.get("lots", [])) if isinstance(local_data, dict) else 0

    # Streamlit garde parfois un cache vide apres un rerun.
    # Si le fichier local contient des lots, on ignore ce cache vide.
    if "data_cache" in st.session_state and not st.session_state.get("data_dirty", False):
        cached = st.session_state["data_cache"]
        cached_lots_count = len(cached.get("lots", [])) if isinstance(cached, dict) else 0
        if cached_lots_count == 0 and local_lots_count > 0:
            st.session_state.pop("data_cache", None)
        elif _valid_data_snapshot(cached):
            perf_log("ld()", time.perf_counter() - perf_start, "cache/after_empty_guard")
            return cached

    cloud_read_started = time.time()
    cloud_data = load_cloud_json(SUPABASE_DATA_KEY) if cloud_sync_enabled() else None
    cloud_valid = _valid_data_snapshot(cloud_data)
    cloud_lots_count = len(cloud_data.get("lots", [])) if cloud_valid else 0

    if cloud_valid and cloud_lots_count > 0:
        local_hash = json_fingerprint(local_data) if _valid_data_snapshot(local_data) else ""
        cloud_hash = json_fingerprint(cloud_data)
        sync_entry = cloud_sync_entry(SUPABASE_DATA_KEY)
        local_dirty = bool(sync_entry.get("local_dirty"))
        push_pending = (
            bool(sync_entry.get("push_pending"))
            or is_cloud_push_pending(SUPABASE_DATA_KEY)
            # lecture commencee avant la fin d'un envoi / une modif locale : peut etre perimee
            or cloud_read_may_be_stale(SUPABASE_DATA_KEY, cloud_read_started)
        )
        if push_pending and local_hash and local_hash != cloud_hash:
            # Envoi cloud en arriere-plan interrompu ou en cours : le local est la reference,
            # il sera (re)envoye par flush_pending_cloud_pushes. Ce n'est pas un conflit.
            d = local_data
            perf_source = "local/push_pending"
            st.session_state.pop("cloud_sync_conflict", None)
            _set_cloud_status(
                source="local",
                status="cloud_pending",
                message="Modifications locales en cours d'envoi vers le cloud.",
                cloud_data=cloud_data,
                local_data=local_data,
            )
        elif local_dirty and local_hash and local_hash != cloud_hash:
            d = local_data
            perf_source = "local/cloud_conflict"
            st.session_state["cloud_sync_conflict"] = {
                "message": "Des modifications locales non envoyées existent. Le cloud n'a pas remplacé automatiquement le local.",
                "local": _data_summary(local_data),
                "cloud": _data_summary(cloud_data),
                "at": utc_now_iso(),
            }
            _set_cloud_status(
                source="local",
                status="conflict",
                message="Cloud disponible, mais modifications locales non envoyées détectées.",
                cloud_data=cloud_data,
                local_data=local_data,
            )
            print(
                f"[Cloud Sync] startup source=local status=conflict local_lots={local_lots_count} cloud_lots={cloud_lots_count}",
                flush=True,
            )
        else:
            d = cloud_data
            perf_source = "cloud"
            st.session_state["cloud_sync_active"] = True
            st.session_state.pop("cloud_sync_conflict", None)
            if local_hash != cloud_hash:
                _write_local_cloud_snapshot(cloud_data)
            else:
                st.session_state["data_cloud_loaded_at"] = time.time()
            _set_cloud_status(
                source="cloud",
                status="loaded",
                message="Dernière version cloud chargée.",
                cloud_data=cloud_data,
                local_data=local_data,
            )
            print(
                f"[Cloud Sync] startup source=cloud status=loaded local_lots={local_lots_count} cloud_lots={cloud_lots_count}",
                flush=True,
            )
    elif cloud_valid and cloud_lots_count == 0 and local_lots_count > 0:
        d = local_data
        perf_source = "local/cloud_empty"
        _set_cloud_status(source="local", status="cloud_empty", message="Cloud vide : données locales conservées.", cloud_data=cloud_data, local_data=local_data)
        st.session_state["cloud_sync_notice"] = "Cloud vide : les données locales ont été conservées."
    elif local_data is not None:
        d = local_data
        perf_source = "local/cloud_unavailable" if cloud_sync_enabled() else "local/cloud_disabled"
        _set_cloud_status(
            source="local",
            status="cloud_unavailable" if cloud_sync_enabled() else "cloud_disabled",
            message="Cloud indisponible : données locales utilisées." if cloud_sync_enabled() else "Cloud désactivé : données locales utilisées.",
            cloud_data=cloud_data if isinstance(cloud_data, dict) else None,
            local_data=local_data,
        )
    else:
        d = {"lots": []}
        perf_source = "empty"
        _set_cloud_status(source="empty", status="empty", message="Aucune donnée locale ou cloud disponible.")

    # Version du fichier vue par cette session (avant les corrections automatiques ci-dessous) :
    # sert a detecter, au moment de sd(), qu'une autre session a ecrit entre-temps.
    remember_data_base(d)
    data_changed = False
    if ensure_card_ids(d):
        data_changed = True
    if sync_mixte_purchase_prices(d):
        data_changed = True
    if consolidate_storage_cards(d):
        data_changed = True
    if data_changed:
        st.session_state["data_autofix_pending"] = True
        # Important: ld() ne doit jamais ecrire data.json au simple affichage.
        # Les corrections restent en memoire et seront sauvegardees uniquement
        # lors d'une vraie action utilisateur qui appelle sd().
    st.session_state["data_cache"] = d
    st.session_state["data_dirty"] = False
    perf_log("ld()", time.perf_counter() - perf_start, perf_source)
    return d


def _sd_write(d):
    """Ecrit data.json (+ envoi cloud). Appele par sd() sous verrou, apres reconciliation."""
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
    sync_result = save_synced_dataset("data", d, indent=None)
    if sync_result.get("cloud"):
        st.session_state["data_cloud_loaded_at"] = time.time()
        st.session_state["cloud_sync_notice"] = "Données locales sauvegardées et cloud mis à jour."
        _set_cloud_status(source="local", status="saved_to_cloud", message="Sauvegarde locale et cloud OK.", local_data=d, cloud_data=d)
    elif sync_result.get("queued"):
        st.session_state["cloud_sync_notice"] = "Sauvegarde locale OK · envoi cloud en cours."
        _set_cloud_status(source="local", status="cloud_pending", message="Sauvegarde locale OK, envoi cloud en cours.", local_data=d)
    else:
        st.session_state["cloud_sync_notice"] = (
            "Sauvegarde locale OK, mais la synchro cloud a échoué ou est désactivée. "
            f"{st.session_state.get('cloud_sync_error', '')}"
        )
        _set_cloud_status(source="local", status="cloud_save_failed", message="Sauvegarde locale OK, cloud non mis à jour.", local_data=d)
    # Mettre à jour le cache et marquer comme propre
    st.session_state["data_cache"] = d
    st.session_state["data_dirty"] = False


def _reconcile_with_other_sessions(d):
    """Evite d'ecraser la modification d'une autre session (PC + telephone, 2 onglets...).

    Chaque session garde sa copie en memoire ; si data.json a change depuis que CETTE session
    l'a lu/ecrit pour la derniere fois, on fusionne a 3 voies (base = ce que la session avait vu,
    mine = sa copie modifiee, theirs = le fichier actuel) au lieu de reecrire sa copie perimee.
    La copie `d` est mise a jour sur place. Un conflit reel (meme valeur modifiee des deux cotes)
    garde la valeur de la sauvegarde en cours et est signale a l'utilisateur.
    """
    base_json = st.session_state.get("data_base_json")
    if not base_json or not _valid_data_snapshot(d):
        return
    current_sig = data_file_signature()
    if current_sig == st.session_state.get("data_base_stat"):
        return  # fichier inchange depuis la derniere lecture/ecriture de cette session
    try:
        disk = _read_local_data_file()
    except Exception:
        return
    if not _valid_data_snapshot(disk):
        return
    disk_fp = json_fingerprint(disk)
    try:
        base = json.loads(base_json)
    except Exception:
        return
    if disk_fp == json_fingerprint(base):
        st.session_state["data_base_stat"] = current_sig  # simple changement d'horodatage
        return
    if disk_fp == json_fingerprint(d):
        return  # le fichier contient deja exactement notre version
    merged, conflicts = merge3(base, d, disk)
    if not _valid_data_snapshot(merged):
        return
    d.clear()
    d.update(merged)
    st.session_state["data_merge_notice"] = {
        "conflicts": conflicts[:8],
        "n_conflicts": len(conflicts),
        "at": utc_now_iso(),
    }
    print(
        f"[Cloud Sync] data.json modifie par une autre session : fusion a 3 voies "
        f"conflits={len(conflicts)} {conflicts[:3]}",
        flush=True,
    )


def sd(d):
    """Save data with cloud sync support (protege contre l'ecrasement entre sessions)."""
    with DATA_WRITE_LOCK:
        if isinstance(d, dict) and isinstance(d.get("lots"), list):
            _reconcile_with_other_sessions(d)
            try:
                # Garde-fou central : une carte NOUVELLE sans extension est completee depuis le catalogue local (id connu).
                complete_new_cards_extension(d, DATA)
            except Exception as exc:  # ne doit jamais empecher une sauvegarde
                print(f"[Extension] garde-fou ignore : {exc}", flush=True)
        _sd_write(d)
        remember_data_base(d)


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


_STORAGE_MERGE_VARIANT_FIELDS = (
    "is_reverse", "is_ed1", "condition", "japanese", "lang", "language", "special_tag",
    "stamp", "promo", "master_ball", "poke_ball", "first_edition", "is_collection_keep", "is_collection",
)


def _storage_price(card):
    try:
        return round(float(card.get("suggested_price") or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _storage_merge_signature(card):
    """Deux entrees ne sont fusionnables que si prix ET variante sont identiques."""
    return (_storage_price(card), tuple(repr(card.get(field)) for field in _STORAGE_MERGE_VARIANT_FIELDS))


def _storage_card_is_plain(card):
    """Entree sans vente / echange : la fusionner ne fait perdre aucun historique de vente."""
    for field in ("sold_quantity", "exchange_out_quantity"):
        try:
            if int(card.get(field) or 0) > 0:
                return False
        except (TypeError, ValueError):
            return False
    return not card.get("sold_entries")


def consolidate_storage_cards(d):
    """Fusionne les entrees STRICTEMENT identiques du lot Stockage (meme carte, meme prix, meme variante).

    Avant, toutes les entrees de meme (nom, numero, set) etaient fusionnees et le prix de la
    premiere gagnait : les prix des autres entrees disparaissaient silencieusement. Maintenant :
      - une entree dont le prix (ou la variante) differe reste une entree distincte ;
      - une entree avec des ventes / echanges n'est jamais absorbee ;
      - quand une fusion a lieu, une trace (storage_merged_entries) garde l'entree absorbee.
    """
    changed = False
    storage_idx = None
    for i, lot in enumerate(d.get("lots", [])):
        if lot.get("nom") == "Stockage" or lot.get("is_storage"):
            storage_idx = i
            break

    if storage_idx is not None:
        storage_lot = d["lots"][storage_idx]
        kept = []
        buckets = {}  # (nom, numero, set) -> [(signature, carte conservee)]
        for card in storage_lot.get("cards", []):
            key = (card.get("name", ""), card.get("number", ""), card.get("set", ""))
            signature = _storage_merge_signature(card)
            target = None
            if _storage_card_is_plain(card):
                for known_signature, known_card in buckets.get(key, []):
                    if known_signature == signature:
                        target = known_card
                        break
            if target is None:
                buckets.setdefault(key, []).append((signature, card))
                kept.append(card)
                continue
            # Fusion d'une entree identique : on garde une trace de ce qui est absorbe.
            target.setdefault("storage_merged_entries", []).append({
                "card_uid": card.get("card_uid"),
                "quantity": int(card.get("quantity", 0) or 0),
                "stored_quantity": int(card.get("stored_quantity", 0) or 0),
                "suggested_price": card.get("suggested_price"),
                "storage_cote_at_add": card.get("storage_cote_at_add"),
                "stored_date": card.get("stored_date"),
                "price_history": list(card.get("price_history") or []),
                "merged_at": datetime.now().isoformat(timespec="seconds"),
            })
            target["quantity"] = int(target.get("quantity", 0)) + int(card.get("quantity", 0))
            target["stored_quantity"] = int(target.get("stored_quantity", 0)) + int(card.get("stored_quantity", 0))
            changed = True
        if changed:
            storage_lot["cards"] = kept

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

"""Browser photo-upload staging for the Vinted Drop workflow.

The browser owns compression and its resumable queue.  This module only
validates bounded upload batches, persists their bytes outside business data,
and exposes the manifest order to the recognition facade.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Iterable

from PIL import Image, UnidentifiedImageError


UPLOAD_MANIFEST_VERSION = 1
UPLOAD_MANIFEST_NAME = "upload_manifest.json"
MAX_UPLOAD_IMAGE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BATCH_BYTES = 24 * 1024 * 1024
MAX_UPLOAD_BATCH_ENTRIES = 16
MAX_UPLOAD_DIMENSION = 2048
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _safe_id(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID.fullmatch(text):
        raise ValueError(f"{field} invalide")
    return text


def _safe_filename(value: Any, fallback: str) -> str:
    name = Path(str(value or "")).name.strip()
    return name or fallback


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def upload_session_dir(root: str | Path, drop_id: str, upload_session_id: str) -> Path:
    safe_drop_id = _safe_id(drop_id, "drop_id")
    safe_session_id = _safe_id(upload_session_id, "upload_session_id")
    base = Path(root).resolve()
    target = (base / safe_drop_id / safe_session_id).resolve()
    if base != target and base not in target.parents:
        raise ValueError("Chemin de session d'import invalide")
    return target


def _empty_manifest(drop_id: str, upload_session_id: str) -> dict[str, Any]:
    return {
        "version": UPLOAD_MANIFEST_VERSION,
        "drop_id": drop_id,
        "upload_session_id": upload_session_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": "",
        "photos": [],
    }


def load_upload_manifest(
    root: str | Path,
    drop_id: str,
    upload_session_id: str,
) -> dict[str, Any]:
    session_dir = upload_session_dir(root, drop_id, upload_session_id)
    path = session_dir / UPLOAD_MANIFEST_NAME
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        payload = _empty_manifest(drop_id, upload_session_id)
    if (
        payload.get("version") != UPLOAD_MANIFEST_VERSION
        or str(payload.get("drop_id") or "") != drop_id
        or str(payload.get("upload_session_id") or "") != upload_session_id
    ):
        payload = _empty_manifest(drop_id, upload_session_id)
    payload["photos"] = ordered_manifest_entries(payload)
    return payload


def ordered_manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in manifest.get("photos", []) or [] if isinstance(row, dict)]
    return sorted(rows, key=lambda row: (int(row.get("original_index", 0)), str(row.get("hash") or "")))


def manifest_summary(manifest: dict[str, Any], session_dir: str | Path | None = None) -> dict[str, Any]:
    rows = ordered_manifest_entries(manifest)
    if session_dir is not None:
        photos_dir = Path(session_dir) / "photos"
        rows = [row for row in rows if (photos_dir / str(row.get("stored_filename") or "")).is_file()]
    return {
        "count": len(rows),
        "received_hashes": [str(row.get("hash") or "") for row in rows if row.get("hash")],
        "first": rows[0] if rows else None,
        "last": rows[-1] if rows else None,
        "total_bytes": sum(int(row.get("compressed_size") or 0) for row in rows),
    }


def _decode_entry(entry: dict[str, Any]) -> tuple[bytes, str, int, int]:
    data = str(entry.get("data_base64") or "")
    if not data:
        raise ValueError("Image vide")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Image encodée invalide") from exc
    if not raw or len(raw) > MAX_UPLOAD_IMAGE_BYTES:
        raise ValueError("Image compressée trop volumineuse")
    expected_hash = str(entry.get("hash") or "").lower().strip()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", expected_hash) or actual_hash != expected_hash:
        raise ValueError("Empreinte de l'image invalide")
    try:
        from io import BytesIO

        with Image.open(BytesIO(raw)) as image:
            image.load()
            width, height = image.size
            image_format = str(image.format or "").upper()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("Format d'image non décodable") from exc
    if image_format != "JPEG":
        raise ValueError("Le navigateur doit envoyer une image JPEG compressée")
    if width <= 0 or height <= 0 or max(width, height) > MAX_UPLOAD_DIMENSION:
        raise ValueError("Dimensions compressées invalides")
    return raw, actual_hash, width, height


def receive_upload_batch(
    root: str | Path,
    *,
    drop_id: str,
    upload_session_id: str,
    batch_id: str,
    entries: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Persist one bounded batch and acknowledge each entry independently."""
    drop_id = _safe_id(drop_id, "drop_id")
    upload_session_id = _safe_id(upload_session_id, "upload_session_id")
    batch_id = _safe_id(batch_id, "batch_id")
    session_dir = upload_session_dir(root, drop_id, upload_session_id)
    photos_dir = session_dir / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_upload_manifest(root, drop_id, upload_session_id)
    rows = ordered_manifest_entries(manifest)
    by_hash = {str(row.get("hash") or ""): row for row in rows}
    by_index = {int(row.get("original_index", -1)): row for row in rows}
    acknowledgements = []
    decoded_total = 0

    entries = list(entries or [])
    if len(entries) > MAX_UPLOAD_BATCH_ENTRIES:
        raise ValueError("Lot d'envoi trop volumineux")
    for position, raw_entry in enumerate(entries):
        entry = dict(raw_entry or {})
        client_id = str(entry.get("client_id") or f"{batch_id}-{position}")
        expected_hash = str(entry.get("hash") or "").lower().strip()
        try:
            if expected_hash in by_hash:
                acknowledgements.append({"client_id": client_id, "hash": expected_hash, "status": "already_received"})
                continue
            original_index = int(entry.get("original_index"))
            batch_index = int(entry.get("batch_index", 0))
            if original_index < 0 or batch_index < 0:
                raise ValueError("Index d'image invalide")
            if original_index in by_index and str(by_index[original_index].get("hash") or "") != expected_hash:
                raise ValueError("Position d'image déjà occupée")
            image_bytes, actual_hash, width, height = _decode_entry(entry)
            decoded_total += len(image_bytes)
            if decoded_total > MAX_UPLOAD_BATCH_BYTES:
                raise ValueError("Lot d'envoi trop volumineux")
            stored_filename = f"{original_index:06d}_{actual_hash[:16]}.jpg"
            destination = photos_dir / stored_filename
            temporary = destination.with_suffix(f".{os.getpid()}.tmp")
            with temporary.open("wb") as handle:
                handle.write(image_bytes)
            os.replace(temporary, destination)
            row = {
                "original_index": original_index,
                "original_filename": _safe_filename(entry.get("original_filename"), f"photo_{original_index + 1}.jpg"),
                "batch_index": batch_index,
                "selected_at": str(entry.get("selected_at") or ""),
                "stored_filename": stored_filename,
                "stored_path": str(destination.resolve()),
                "hash": actual_hash,
                "compressed_size": len(image_bytes),
                "width": width,
                "height": height,
                "upload_status": "received",
            }
            rows.append(row)
            by_hash[actual_hash] = row
            by_index[original_index] = row
            acknowledgements.append({"client_id": client_id, "hash": actual_hash, "status": "received"})
        except (TypeError, ValueError, OSError) as exc:
            acknowledgements.append(
                {
                    "client_id": client_id,
                    "hash": expected_hash,
                    "status": "error",
                    "message": str(exc),
                }
            )

    manifest["photos"] = ordered_manifest_entries({"photos": rows})
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _atomic_json_write(session_dir / UPLOAD_MANIFEST_NAME, manifest)
    summary = manifest_summary(manifest, session_dir)
    return {
        "batch_id": batch_id,
        "upload_session_id": upload_session_id,
        "acknowledgements": acknowledgements,
        "manifest": summary,
        "folder": str(session_dir),
    }


def manifest_from_folder(folder: str | Path) -> dict[str, Any] | None:
    folder = Path(folder)
    path = folder / UPLOAD_MANIFEST_NAME
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    if payload.get("version") != UPLOAD_MANIFEST_VERSION:
        return None
    payload["photos"] = ordered_manifest_entries(payload)
    return payload


def cancel_upload_session(root: str | Path, drop_id: str, upload_session_id: str) -> None:
    session_dir = upload_session_dir(root, drop_id, upload_session_id)
    base = Path(root).resolve()
    if session_dir == base or base not in session_dir.parents:
        raise ValueError("Session d'import invalide")
    if session_dir.exists():
        shutil.rmtree(session_dir)


def upload_allowed_for_drop(drop: dict[str, Any] | None) -> bool:
    return bool(drop) and not bool(str((drop or {}).get("drop_launched_at") or "").strip())

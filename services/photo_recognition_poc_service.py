"""Isolated photo-recognition POC helpers.

The helpers in this module are intentionally read-only for Pokestock data:
they inspect photos and drop/card references, but never write to data.json or
vinted_drops.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import os
import pickle
import re
import time
import unicodedata
from typing import Any
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import requests
except Exception:  # pragma: no cover - optional at runtime
    requests = None

try:
    import cv2
except Exception:  # pragma: no cover - optional at runtime
    cv2 = None

from services.card_identity import card_identity_fingerprint
from services.card_identity import card_language_key
from services.custom_card_image_service import resolve_custom_card_image
from services.vinted_drops_service import (
    drop_card_key,
    drop_item_status,
    load_vinted_drops,
    resolve_drop_item_card_identity,
)


POC_DIR = Path("photo_recognition_poc")
POC_CACHE_DIR = POC_DIR / ".cache"
POC_GROUND_TRUTH_PATH = POC_DIR / ".poc_ground_truth.json"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
EXIF_DATETIME_TAGS = (36867, 36868, 306)
FILENAME_DATETIME_PATTERNS = (
    re.compile(r"(?P<date>20\d{6})[_-]?(?P<time>\d{6})"),
    re.compile(r"(?P<date>20\d{2}[-_]\d{2}[-_]\d{2})[_\s-]+(?P<time>\d{2}[-_]\d{2}[-_]\d{2})"),
)

_OCR_ENGINE = None
OCR_CACHE_VERSION = "v8c"
CLASSIFICATION_CACHE_VERSION = "v11b-western-back-blue-anchor"
POC_ANALYSIS_PIPELINE_VERSION = "v14-structural-ground-truth-2"
POC_MATCHING_REFRESH_VERSION = "v14.7-historical-drop-legend-jp-1"
DROP_MEMBERSHIP_RECONCILIATION_VERSION = "v3"
PROPOSAL_RELIABILITY_VERSION = "v1-zero-evidence-guard"
POC_RESULT_CACHE_VERSION = "v1-persistent-result"
PHOTO_ROLES = (
    "primary_front",
    "back_western",
    "back_japanese",
    "card_front",
    "card_back",
    "extra",
    "uncertain",
)
VALIDATED_GROUP_STATUSES = {"validated", "correct", "corrected"}


@dataclass(frozen=True)
class PhotoInfo:
    path: str
    filename: str
    capture_index: int
    capture_datetime: str
    order_source: str
    size_bytes: int


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_exif_datetime(path: Path) -> tuple[datetime | None, str]:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            for tag in EXIF_DATETIME_TAGS:
                raw = str(exif.get(tag) or "").strip()
                if not raw:
                    continue
                for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(raw, fmt), "exif"
                    except ValueError:
                        pass
    except (OSError, UnidentifiedImageError):
        return None, ""
    return None, ""


def _parse_filename_datetime(path: Path) -> tuple[datetime | None, str]:
    stem = path.stem
    for pattern in FILENAME_DATETIME_PATTERNS:
        match = pattern.search(stem)
        if not match:
            continue
        date = match.group("date").replace("_", "").replace("-", "")
        clock = match.group("time").replace("_", "").replace("-", "")
        try:
            return datetime.strptime(date + clock, "%Y%m%d%H%M%S"), "filename"
        except ValueError:
            pass
    return None, ""


def _photo_sort_key(path: Path):
    exif_dt, source = _parse_exif_datetime(path)
    if exif_dt:
        return exif_dt, source
    name_dt, source = _parse_filename_datetime(path)
    if name_dt:
        return name_dt, source
    try:
        return datetime.fromtimestamp(path.stat().st_ctime), "created_at_fallback"
    except OSError:
        return datetime.min, "filename_fallback"


def list_ordered_photos(folder: str | Path = POC_DIR) -> list[PhotoInfo]:
    folder = Path(folder)
    if not folder.exists():
        return []
    rows = []
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        capture_dt, source = _photo_sort_key(path)
        rows.append((capture_dt, source, path.name.lower(), path))
    rows.sort(key=lambda item: (item[0], item[2]))
    ordered = []
    for index, (capture_dt, source, _name_key, path) in enumerate(rows, start=1):
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
        ordered.append(
            PhotoInfo(
                path=str(path),
                filename=path.name,
                capture_index=index,
                capture_datetime=capture_dt.isoformat(sep=" ", timespec="seconds") if capture_dt != datetime.min else "",
                order_source=source,
                size_bytes=size_bytes,
            )
        )
    return ordered


def photo_window_signature(photos: list[PhotoInfo]) -> str:
    """Fingerprint the physical inputs without reading their image pixels."""
    rows = []
    for photo in photos:
        try:
            mtime_ns = Path(photo.path).stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        rows.append(
            f"{photo.capture_index}:{photo.filename}:{photo.size_bytes}:{mtime_ns}"
        )
    return hashlib.sha1("|".join(rows).encode("utf-8")).hexdigest()


def load_json_file(path: str | Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def active_drop_candidates(data_path="data.json", drops_path="vinted_drops.json", drop_id: str | None = None):
    data = load_json_file(data_path, {"lots": []})
    drops_data = load_vinted_drops(drops_path)
    drops = drops_data.get("drops", []) or []
    if not drops:
        return None, []
    drop = next((item for item in drops if item.get("id") == drop_id), None) if drop_id else None
    drop = drop or drops[0]

    card_by_uid = {}
    card_by_ref = {}
    for lot_idx, lot in enumerate(data.get("lots", []) or []):
        for card_idx, card in enumerate(lot.get("cards", []) or []):
            merged = dict(card)
            merged.update(
                {
                    "lot_idx": lot_idx,
                    "card_idx": card_idx,
                    "lot_uid": lot.get("lot_uid", ""),
                    "lot_name": lot.get("nom", ""),
                }
            )
            if merged.get("card_uid"):
                card_by_uid[str(merged["card_uid"])] = merged
            card_by_ref[(str(lot.get("lot_uid", "")), int(card_idx))] = merged

    candidates = []
    seen_keys = set()
    for ref in drop.get("cards", []) or []:
        card = None
        if ref.get("card_uid"):
            card = card_by_uid.get(str(ref.get("card_uid")))
        if card is None:
            card = card_by_ref.get((str(ref.get("lot_uid", "")), _safe_int(ref.get("card_idx"), -1)))
        merged = dict(card or {})
        merged.update(resolve_drop_item_card_identity(ref, card))
        merged.setdefault("lot_name", (card or {}).get("lot_name", ""))
        merged["identity_fingerprint"] = card_identity_fingerprint(merged)
        merged["_drop_card_key"] = drop_card_key(merged)
        key = merged.get("_drop_card_key")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(
            {
                "card_uid": merged.get("card_uid", ""),
                "lot_uid": merged.get("lot_uid", ""),
                "drop_item_id": merged.get("drop_item_id", ""),
                "drop_card_key": key,
                "name": str(merged.get("name") or "Carte"),
                "number": str(merged.get("display_number") or merged.get("number") or ""),
                "set": str(merged.get("set") or ""),
                "lot_name": str(merged.get("lot_name") or ""),
                "lang": str(merged.get("lang") or merged.get("language") or ""),
                "japanese": card_language_key(merged) == "ja",
                "reverse": bool(merged.get("reverse") or merged.get("is_reverse")),
                "first_edition": bool(merged.get("first_edition") or merged.get("is_ed1")),
                "stamp": str(merged.get("stamp") or merged.get("stamp_label") or ""),
                "promo": bool(merged.get("promo") or merged.get("is_promo")),
                "master_ball": bool(merged.get("master_ball") or merged.get("is_master_ball")),
                "poke_ball": bool(merged.get("poke_ball") or merged.get("is_poke_ball")),
                # Recognition concerns the historical contents of this Drop,
                # not today's stock availability. A sold item remains one of
                # the physical cards photographed before publication.
                "quantity": max(1, _safe_int(ref.get("quantity"), 1)),
                "historical_drop_member": True,
                "drop_status": drop_item_status(ref),
                "sold_at": str(ref.get("sold_at") or ""),
                "price": _safe_float(merged.get("suggested_price", merged.get("price_at_add", 0))),
                "image_url": _candidate_image_url(merged),
                "identity_fingerprint": merged.get("identity_fingerprint") or card_identity_fingerprint(merged),
            }
        )
    return drop, candidates


def candidate_identity(candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Return the candidate fields that can change matching or validation."""
    candidate = candidate or {}
    return {
        "drop_card_key": str(candidate.get("drop_card_key") or candidate.get("_drop_card_key") or ""),
        "card_uid": str(candidate.get("card_uid") or ""),
        "lot_uid": str(candidate.get("lot_uid") or ""),
        "name": str(candidate.get("name") or ""),
        "number": str(candidate.get("number") or ""),
        "set": str(candidate.get("set") or ""),
        "japanese": bool(candidate.get("japanese")),
        "reverse": bool(candidate.get("reverse")),
        "first_edition": bool(candidate.get("first_edition")),
        "stamp": str(candidate.get("stamp") or ""),
        "promo": bool(candidate.get("promo")),
        "master_ball": bool(candidate.get("master_ball")),
        "poke_ball": bool(candidate.get("poke_ball")),
    }


def candidate_identity_key(candidate: dict[str, Any] | None) -> str:
    identity = candidate_identity(candidate)
    return identity["card_uid"] or identity["drop_card_key"] or hashlib.sha1(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def proposed_candidate(match: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the identity proposed to users, excluding debug-only rows."""
    match = match or {}
    rows = match.get("candidates") or []
    candidate = (rows[0] or {}).get("candidate") if rows else None
    if not isinstance(candidate, dict):
        return None
    if match.get("proposal_reliable") is False:
        return None
    top_score = _safe_float((rows[0] or {}).get("score"), 0.0)
    match_score = _safe_float(match.get("score"), 0.0)
    if max(top_score, match_score) <= 0.0:
        return None
    return candidate


def drop_candidate_membership(
    candidate: dict[str, Any] | None,
    drop_candidates: list[dict[str, Any]],
) -> dict[str, str | bool]:
    """Resolve a proposed card against the current historical Drop candidates.

    A card UID is the strongest identity. Older Drop entries may not retain a
    usable UID, so the shared semantic fingerprint is the strict fallback.
    Name-only matching is intentionally not allowed here.
    """
    candidate = candidate or {}
    card_uid = str(candidate.get("card_uid") or "").strip()
    if card_uid and any(str(item.get("card_uid") or "").strip() == card_uid for item in drop_candidates):
        return {"in_drop": True, "method": "card_uid"}

    fingerprint = str(candidate.get("identity_fingerprint") or card_identity_fingerprint(candidate) or "").strip()
    if fingerprint and any(
        str(item.get("identity_fingerprint") or card_identity_fingerprint(item) or "").strip() == fingerprint
        for item in drop_candidates
    ):
        return {"in_drop": True, "method": "identity_fingerprint"}
    return {"in_drop": False, "method": ""}


def candidate_set_signature(candidates: list[dict[str, Any]]) -> str:
    payload = sorted(
        (
            {
                **candidate_identity(candidate),
                "quantity": max(1, _safe_int(candidate.get("quantity"), 1)),
                "image_url": str(candidate.get("image_url") or ""),
            }
            for candidate in candidates
        ),
        key=lambda item: (item["card_uid"], item["drop_card_key"], item["name"], item["number"]),
    )
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _analysis_cache_descriptor(
    *,
    folder: str | Path,
    drop_id: str | None,
    start_index: int,
    target_announcements: int,
    max_photos: int,
    photo_signature: str,
) -> dict[str, Any]:
    return {
        "cache_version": POC_RESULT_CACHE_VERSION,
        "pipeline_version": POC_ANALYSIS_PIPELINE_VERSION,
        "matching_refresh_version": POC_MATCHING_REFRESH_VERSION,
        "folder": str(Path(folder).resolve()),
        "drop_id": str(drop_id or ""),
        "start_index": int(start_index),
        "target_announcements": int(target_announcements),
        "max_photos": int(max_photos),
        "photo_signature": str(photo_signature),
    }


def _analysis_result_cache_path(descriptor: dict[str, Any]) -> Path:
    digest = hashlib.sha1(
        json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return POC_CACHE_DIR / "results" / f"{digest}.pickle"


def save_cached_analysis_result(result: dict[str, Any]) -> dict[str, Any]:
    """Persist one local POC result atomically for fast server restarts."""
    meta = result.get("analysis_meta") or {}
    descriptor = meta.get("result_cache_descriptor")
    if not isinstance(descriptor, dict):
        descriptor = _analysis_cache_descriptor(
            folder=meta.get("folder") or POC_DIR,
            drop_id=meta.get("drop_id"),
            start_index=_safe_int(meta.get("start_index"), 1),
            target_announcements=_safe_int(meta.get("target_announcements"), 0),
            max_photos=_safe_int(meta.get("max_photos"), 0),
            photo_signature=str(meta.get("photo_signature") or ""),
        )
        meta["result_cache_descriptor"] = descriptor
    path = _analysis_result_cache_path(descriptor)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    started = time.perf_counter()
    payload = {
        "cache_version": POC_RESULT_CACHE_VERSION,
        "descriptor": descriptor,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "result": result,
    }
    try:
        with temporary.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "write_seconds": time.perf_counter() - started,
    }


def load_cached_analysis_result(
    *,
    folder: str | Path = POC_DIR,
    drop_id: str | None = None,
    start_index=1,
    target_announcements=30,
    max_photos=90,
    ordered_photos: list[PhotoInfo] | None = None,
) -> dict[str, Any] | None:
    """Restore a compatible local result without running recognition again."""
    started = time.perf_counter()
    ordered = ordered_photos if ordered_photos is not None else list_ordered_photos(folder)
    start_index = max(1, int(start_index or 1))
    max_photos = max(1, int(max_photos or 1))
    photo_window = ordered[start_index - 1 : start_index - 1 + max_photos]
    descriptor = _analysis_cache_descriptor(
        folder=folder,
        drop_id=drop_id,
        start_index=start_index,
        target_announcements=int(target_announcements or 0),
        max_photos=max_photos,
        photo_signature=photo_window_signature(photo_window),
    )
    path = _analysis_result_cache_path(descriptor)
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            payload = pickle.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("cache_version") != POC_RESULT_CACHE_VERSION:
        return None
    if payload.get("descriptor") != descriptor:
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    meta = result.get("analysis_meta") or {}
    if meta.get("pipeline_version") != POC_ANALYSIS_PIPELINE_VERSION:
        return None
    if meta.get("matching_refresh_version") != POC_MATCHING_REFRESH_VERSION:
        return None
    result.setdefault("metrics", {})["persistent_cache_restore_seconds"] = round(
        time.perf_counter() - started,
        4,
    )
    result["metrics"]["persistent_cache_hit"] = True
    result["metrics"]["persistent_cache_size_bytes"] = path.stat().st_size
    return result


def load_latest_cached_analysis_result(
    *,
    folder: str | Path = POC_DIR,
    drop_id: str | None = None,
    ordered_photos: list[PhotoInfo] | None = None,
) -> dict[str, Any] | None:
    """Restore the newest valid block for a folder/drop after a server restart."""
    ordered = ordered_photos if ordered_photos is not None else list_ordered_photos(folder)
    expected_folder = str(Path(folder).resolve())
    expected_drop = str(drop_id or "")
    cache_dir = POC_CACHE_DIR / "results"
    if not cache_dir.exists():
        return None
    for path in sorted(cache_dir.glob("*.pickle"), key=lambda item: item.stat().st_mtime_ns, reverse=True):
        started = time.perf_counter()
        try:
            with path.open("rb") as handle:
                payload = pickle.load(handle)
        except Exception:
            continue
        descriptor = payload.get("descriptor") if isinstance(payload, dict) else None
        if not isinstance(descriptor, dict):
            continue
        if descriptor.get("cache_version") != POC_RESULT_CACHE_VERSION:
            continue
        if descriptor.get("pipeline_version") != POC_ANALYSIS_PIPELINE_VERSION:
            continue
        if descriptor.get("matching_refresh_version") != POC_MATCHING_REFRESH_VERSION:
            continue
        if descriptor.get("folder") != expected_folder or str(descriptor.get("drop_id") or "") != expected_drop:
            continue
        start_index = max(1, _safe_int(descriptor.get("start_index"), 1))
        max_photos = max(1, _safe_int(descriptor.get("max_photos"), 1))
        photo_window = ordered[start_index - 1 : start_index - 1 + max_photos]
        if descriptor.get("photo_signature") != photo_window_signature(photo_window):
            continue
        result = payload.get("result")
        if not isinstance(result, dict):
            continue
        result.setdefault("metrics", {})["persistent_cache_restore_seconds"] = round(
            time.perf_counter() - started,
            4,
        )
        result["metrics"]["persistent_cache_hit"] = True
        result["metrics"]["persistent_cache_size_bytes"] = path.stat().st_size
        return result
    return None


def _candidate_image_url(card: dict) -> str:
    for key in (
        "manual_image_path",
        "manual_image_url",
        "local_image",
        "local_image_path",
        "image_path",
        "photo_path",
        "cached_image_path",
        "resolved_collection_image_url",
        "image_url_ja",
        "image_url_jp",
        "image_url_japanese",
        "image_ja",
        "image_jp",
        "image_url",
        "image_url_en",
        "image_en",
        "image",
        "imageUrl",
    ):
        value = str(card.get(key) or "").strip()
        if not value or value == "__placeholder__":
            continue
        if value.startswith(("card_images/", "card_images\\")) and not os.path.exists(value):
            continue
        return value
    try:
        return resolve_custom_card_image(card)
    except Exception:
        return ""


def _load_image(path_or_url: str, *, max_side: int = 1024) -> Image.Image | None:
    if not path_or_url:
        return None
    source = str(path_or_url)
    local_path = _reference_cache_path(source) if source.startswith(("http://", "https://")) else Path(source)
    if source.startswith(("http://", "https://")) and not local_path.exists():
        if requests is None:
            return None
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            response = requests.get(source, timeout=8)
            if response.status_code >= 400:
                return None
            local_path.write_bytes(response.content)
        except Exception:
            return None
    try:
        with Image.open(local_path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            return img.copy()
    except Exception:
        return None


def _reference_cache_path(url: str) -> Path:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower() or ".img"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return POC_CACHE_DIR / "references" / f"{digest}{suffix}"


def _feature_cache_path(source: str) -> Path:
    digest = hashlib.sha1(str(source or "").encode("utf-8")).hexdigest()
    return POC_CACHE_DIR / "features" / f"{digest}.json"


def _artwork_feature_cache_path(source: str) -> Path:
    digest = hashlib.sha1(f"artwork-v9|{source or ''}".encode("utf-8")).hexdigest()
    return POC_CACHE_DIR / "features" / f"{digest}.json"


def _ocr_cache_path(source: str) -> Path:
    try:
        path = Path(source)
        stat = path.stat()
        cache_key = f"{OCR_CACHE_VERSION}|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except Exception:
        cache_key = f"{OCR_CACHE_VERSION}|{source or ''}"
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
    return POC_CACHE_DIR / "ocr" / f"{digest}.json"


def _classification_cache_path(source: str) -> Path:
    try:
        path = Path(source)
        stat = path.stat()
        cache_key = f"{CLASSIFICATION_CACHE_VERSION}|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except Exception:
        cache_key = f"{CLASSIFICATION_CACHE_VERSION}|{source or ''}"
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
    return POC_CACHE_DIR / "classifications" / f"{digest}.json"


def _feature_to_json(feature: dict[str, Any]) -> dict[str, Any]:
    bits = "".join("1" if value else "0" for value in feature["hash"].reshape(-1))
    return {"hash_bits": bits, "hash_size": int(feature["hash"].shape[0]), "hist": feature["hist"].astype(float).tolist()}


def _feature_from_json(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        size = int(payload.get("hash_size") or 16)
        bits = str(payload.get("hash_bits") or "")
        if len(bits) != size * size:
            return None
        return {
            "hash": np.array([char == "1" for char in bits], dtype=bool).reshape((size, size)),
            "hist": np.asarray(payload.get("hist") or [], dtype=np.float32),
        }
    except Exception:
        return None


def _image_array(image: Image.Image, max_side=768) -> np.ndarray:
    img = image.copy()
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return np.asarray(img.convert("RGB"), dtype=np.uint8)


def _rgb_to_hsv_like(arr: np.ndarray):
    rgb = arr.astype(np.float32) / 255.0
    maxc = rgb.max(axis=2)
    minc = rgb.min(axis=2)
    sat = np.where(maxc == 0, 0, (maxc - minc) / np.maximum(maxc, 1e-6))
    return maxc, sat


def _pokemon_back_score(arr: np.ndarray) -> tuple[float, list[str]]:
    r = arr[:, :, 0].astype(np.int16)
    g = arr[:, :, 1].astype(np.int16)
    b = arr[:, :, 2].astype(np.int16)
    maxc, sat = _rgb_to_hsv_like(arr)
    blue = (b > 85) & (b > r + 18) & (b >= g - 8) & (sat > 0.25)
    yellow = (r > 135) & (g > 95) & (b < 125) & (sat > 0.25)
    dark_blue = (b > 70) & (r < 80) & (g < 120) & (sat > 0.35)
    blue_frac = float(np.mean(blue | dark_blue))
    yellow_frac = float(np.mean(yellow))
    vivid_frac = float(np.mean(sat > 0.28))
    yellow_logo_bonus = yellow_frac * 1.8 if blue_frac >= 0.14 else 0.0
    vivid_bonus = max(0.0, vivid_frac - 0.32) * 0.45 if blue_frac >= 0.12 else 0.0
    score = min(1.0, blue_frac * 2.35 + yellow_logo_bonus + vivid_bonus)
    reasons = []
    if blue_frac > 0.22:
        reasons.append(f"bleu verso {blue_frac:.0%}")
    if yellow_frac > 0.05 and blue_frac >= 0.14:
        reasons.append(f"jaune/orange {yellow_frac:.0%}")
    if vivid_frac > 0.45:
        reasons.append(f"couleurs saturées {vivid_frac:.0%}")
    return score, reasons


def _japanese_back_score(arr: np.ndarray) -> tuple[float, list[str]]:
    r = arr[:, :, 0].astype(np.int16)
    g = arr[:, :, 1].astype(np.int16)
    b = arr[:, :, 2].astype(np.int16)
    _maxc, sat = _rgb_to_hsv_like(arr)
    warm = (r > 105) & (g > 70) & (b < 95) & (r > b + 28) & (sat > 0.18)
    cream = (r > 145) & (g > 120) & (b > 75) & (r > b + 20) & (sat > 0.12)
    dark_blue = (b > 70) & (b > r + 16) & (sat > 0.25)
    warm_frac = float(np.mean(warm | cream))
    blue_frac = float(np.mean(dark_blue))
    score = min(1.0, warm_frac * 1.9 + max(0.0, 0.18 - blue_frac) * 0.8)
    reasons = []
    if warm_frac > 0.22:
        reasons.append(f"dos JP chaud {warm_frac:.0%}")
    if blue_frac < 0.12:
        reasons.append("peu de bleu occidental")
    return score, reasons


def _split_internal_card_grid(image: Image.Image) -> list[dict[str, Any]]:
    gray_img = image.convert("L")
    gray_img.thumbnail((768, 768), Image.Resampling.LANCZOS)
    gray = np.asarray(gray_img, dtype=np.uint8)
    h, w = gray.shape
    if h < 120 or w < 120:
        return []

    col_profile = gray.mean(axis=0)
    row_profile = gray.mean(axis=1)
    center_cols = range(int(w * 0.36), int(w * 0.64))
    center_rows = range(int(h * 0.34), int(h * 0.66))
    min_col_value, min_col_idx = min((float(col_profile[i]), int(i)) for i in center_cols)
    min_row_value, min_row_idx = min((float(row_profile[i]), int(i)) for i in center_rows)
    side_col_value = max(
        float(np.mean(col_profile[int(w * 0.22) : int(w * 0.34)])),
        float(np.mean(col_profile[int(w * 0.66) : int(w * 0.78)])),
    )
    side_row_value = max(
        float(np.mean(row_profile[int(h * 0.22) : int(h * 0.34)])),
        float(np.mean(row_profile[int(h * 0.66) : int(h * 0.78)])),
    )
    has_vertical_split = min_col_value < 62 and side_col_value - min_col_value > 42
    has_horizontal_split = min_row_value < 70 and side_row_value - min_row_value > 34
    if not has_vertical_split:
        return []

    x_cuts = [0.03, min_col_idx / max(1, w), 0.97] if has_vertical_split else [0.08, 0.92]
    y_cuts = [0.03, min_row_idx / max(1, h), 0.97] if has_horizontal_split else [0.08, 0.92]
    regions = []
    for row in range(len(y_cuts) - 1):
        for col in range(len(x_cuts) - 1):
            x1, x2 = x_cuts[col], x_cuts[col + 1]
            y1, y2 = y_cuts[row], y_cuts[row + 1]
            if x2 - x1 < 0.18 or y2 - y1 < 0.18:
                continue
            regions.append(
                {
                    "box": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                    "area_ratio": round((x2 - x1) * (y2 - y1), 4),
                    "aspect": round((x2 - x1) / max(1e-6, y2 - y1), 3),
                    "source": "internal_grid",
                }
            )
    return regions


def _edge_map(gray: np.ndarray) -> np.ndarray:
    gx = np.abs(np.diff(gray.astype(np.int16), axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray.astype(np.int16), axis=0, prepend=gray[:1, :]))
    return np.maximum(gx, gy)


def detect_card_regions(image: Image.Image, *, max_regions=4) -> list[dict[str, Any]]:
    arr = _image_array(image, max_side=640)
    h, w = arr.shape[:2]
    gray = np.asarray(Image.fromarray(arr).convert("L"), dtype=np.uint8)
    edges = _edge_map(gray)
    _value, sat = _rgb_to_hsv_like(arr)
    mask = (edges > 24) | (sat > 0.18)
    # Keep the useful central area, where cards usually are.
    yy, xx = np.mgrid[0:h, 0:w]
    border = (xx < w * 0.03) | (xx > w * 0.97) | (yy < h * 0.03) | (yy > h * 0.97)
    mask[border] = False
    # Cheap dilation.
    for _ in range(2):
        padded = np.pad(mask, 1, mode="constant")
        mask = (
            padded[1:-1, 1:-1]
            | padded[:-2, 1:-1]
            | padded[2:, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
        )

    visited = np.zeros(mask.shape, dtype=bool)
    regions = []
    for y in range(0, h, 3):
        xs = np.where(mask[y] & ~visited[y])[0]
        for x0 in xs[::3]:
            if visited[y, x0] or not mask[y, x0]:
                continue
            stack = [(int(x0), int(y))]
            visited[y, x0] = True
            minx = maxx = int(x0)
            miny = maxy = int(y)
            count = 0
            while stack:
                x, yy0 = stack.pop()
                count += 1
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, yy0), max(maxy, yy0)
                for nx, ny in ((x + 1, yy0), (x - 1, yy0), (x, yy0 + 1), (x, yy0 - 1)):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h:
                        continue
                    if visited[ny, nx] or not mask[ny, nx]:
                        continue
                    visited[ny, nx] = True
                    stack.append((nx, ny))
            box_w = maxx - minx + 1
            box_h = maxy - miny + 1
            area_ratio = (box_w * box_h) / max(1, w * h)
            aspect = box_w / max(1, box_h)
            if area_ratio < 0.035:
                continue
            card_like = 0.48 <= aspect <= 1.15 or 0.42 <= (1 / max(aspect, 1e-6)) <= 1.15
            if not card_like:
                continue
            regions.append(
                {
                    "box": [minx / w, miny / h, maxx / w, maxy / h],
                    "area_ratio": round(area_ratio, 4),
                    "aspect": round(aspect, 3),
                }
            )
    regions.sort(key=lambda item: item["area_ratio"], reverse=True)
    # Suppress boxes almost included in a larger box.
    kept = []
    for region in regions:
        x1, y1, x2, y2 = region["box"]
        duplicate = False
        for other in kept:
            ox1, oy1, ox2, oy2 = other["box"]
            ix1, iy1 = max(x1, ox1), max(y1, oy1)
            ix2, iy2 = min(x2, ox2), min(y2, oy2)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            area = max(1e-6, (x2 - x1) * (y2 - y1))
            if inter / area > 0.72:
                duplicate = True
                break
        if not duplicate:
            kept.append(region)
        if len(kept) >= max_regions:
            break
    if len(kept) <= 1:
        grid_regions = _split_internal_card_grid(image)
        if len(grid_regions) > len(kept):
            return grid_regions[:max_regions]
    return kept


def _classify_photo_uncached(path: str) -> dict[str, Any]:
    image = _load_image(path, max_side=1024)
    if image is None:
        return {"class": "uncertain", "confidence": 0.0, "reasons": ["image illisible"], "regions": []}
    arr = _image_array(image, max_side=768)
    western_back_score, western_back_reasons = _pokemon_back_score(arr)
    japanese_back_score, japanese_back_reasons = _japanese_back_score(arr)
    regions = detect_card_regions(image)
    largest = max((region["area_ratio"] for region in regions), default=0.0)
    base = {
        "western_back_score": round(western_back_score, 3),
        "japanese_back_score": round(japanese_back_score, 3),
        "regions": regions,
        "card_count_hint": max(1, len(regions)),
    }
    if western_back_score >= 0.56:
        return {**base, "class": "back_western", "back_type": "western", "confidence": round(western_back_score, 2), "reasons": western_back_reasons or ["signature verso Pokémon occidental"]}
    if japanese_back_score >= 0.84 and western_back_score < 0.52:
        return {**base, "class": "back_japanese", "back_type": "japanese", "confidence": round(japanese_back_score, 2), "reasons": japanese_back_reasons or ["signature verso Pokémon japonais"]}
    if len(regions) >= 1 and largest >= 0.18:
        confidence = min(0.92, 0.48 + largest + min(len(regions), 4) * 0.08)
        reasons = [f"{len(regions)} zone(s) carte", f"zone principale {largest:.0%}"]
        return {**base, "class": "primary_front", "confidence": round(confidence, 2), "reasons": reasons}
    if largest >= 0.06:
        return {**base, "class": "extra", "confidence": round(min(0.75, 0.45 + largest), 2), "reasons": ["détail/zone partielle"]}
    return {**base, "class": "uncertain", "confidence": 0.25, "reasons": ["pas de carte complète détectée"]}


def classify_photo(path: str) -> dict[str, Any]:
    cache_path = _classification_cache_path(path)
    if cache_path.exists():
        cached = load_json_file(cache_path, None)
        if isinstance(cached, dict) and cached.get("cache_version") == CLASSIFICATION_CACHE_VERSION:
            payload = cached.get("classification")
            if isinstance(payload, dict):
                return payload
    payload = _classify_photo_uncached(path)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"cache_version": CLASSIFICATION_CACHE_VERSION, "classification": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
    return payload


def _crop_region(image: Image.Image, region: dict[str, Any]) -> Image.Image:
    w, h = image.size
    x1, y1, x2, y2 = region.get("box", [0, 0, 1, 1])
    pad_x = (x2 - x1) * 0.03
    pad_y = (y2 - y1) * 0.03
    box = (
        max(0, int((x1 - pad_x) * w)),
        max(0, int((y1 - pad_y) * h)),
        min(w, int((x2 + pad_x) * w)),
        min(h, int((y2 + pad_y) * h)),
    )
    return image.crop(box)


def _average_hash(image: Image.Image, size=16) -> np.ndarray:
    gray = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    arr = np.asarray(gray, dtype=np.float32)
    return arr > arr.mean()


def _color_hist(image: Image.Image, bins=6) -> np.ndarray:
    arr = np.asarray(image.convert("RGB").resize((96, 96), Image.Resampling.LANCZOS), dtype=np.float32) / 255.0
    hist_parts = []
    for channel in range(3):
        hist, _edges = np.histogram(arr[:, :, channel], bins=bins, range=(0, 1), density=True)
        hist_parts.append(hist)
    hist = np.concatenate(hist_parts).astype(np.float32)
    norm = np.linalg.norm(hist)
    return hist / norm if norm else hist


def _feature(image: Image.Image) -> dict[str, Any]:
    return {"hash": _average_hash(image), "hist": _color_hist(image)}


def _feature_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    hash_distance = float(np.mean(a["hash"] != b["hash"]))
    hist_distance = float(np.linalg.norm(a["hist"] - b["hist"]) / math.sqrt(2))
    return 0.62 * hash_distance + 0.38 * hist_distance


def _artwork_crop(image: Image.Image) -> Image.Image:
    regions = detect_card_regions(image)
    if regions:
        image = _crop_region(image, regions[0])
    w, h = image.size
    if h <= 0 or w <= 0:
        return image
    # The illustration is usually central/top-middle. For full-art cards this
    # still keeps enough composition while dropping most border/text noise.
    left = int(w * 0.09)
    right = int(w * 0.91)
    top = int(h * 0.16)
    bottom = int(h * 0.64)
    if bottom <= top or right <= left:
        return image
    return image.crop((left, top, right, bottom))


def _orb_descriptors(image: Image.Image) -> np.ndarray | None:
    if cv2 is None:
        return None
    try:
        gray = np.asarray(image.convert("L").resize((420, 300), Image.Resampling.LANCZOS), dtype=np.uint8)
        gray = cv2.equalizeHist(gray)
        orb = cv2.ORB_create(nfeatures=260, fastThreshold=7)
        _keypoints, descriptors = orb.detectAndCompute(gray, None)
        if descriptors is None or len(descriptors) == 0:
            return None
        return descriptors[:260]
    except Exception:
        return None


def _artwork_feature(image: Image.Image) -> dict[str, Any]:
    artwork = _artwork_crop(image)
    return {"base": _feature(artwork), "orb": _orb_descriptors(artwork)}


def _artwork_feature_to_json(feature: dict[str, Any]) -> dict[str, Any]:
    payload = _feature_to_json(feature["base"])
    orb = feature.get("orb")
    payload["orb"] = orb.astype(int).tolist() if isinstance(orb, np.ndarray) and len(orb) else []
    return payload


def _artwork_feature_from_json(payload: dict[str, Any]) -> dict[str, Any] | None:
    base = _feature_from_json(payload)
    if base is None:
        return None
    orb_rows = payload.get("orb") or []
    orb = np.asarray(orb_rows, dtype=np.uint8) if orb_rows else None
    return {"base": base, "orb": orb}


def _artwork_feature_distance(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    base_distance = _feature_distance(a["base"], b["base"])
    base_score = max(0.0, 100.0 * (1.0 - min(1.0, base_distance)))
    orb_score = None
    good_matches = 0
    a_orb = a.get("orb")
    b_orb = b.get("orb")
    if cv2 is not None and isinstance(a_orb, np.ndarray) and isinstance(b_orb, np.ndarray) and len(a_orb) >= 4 and len(b_orb) >= 4:
        try:
            matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
            pairs = matcher.knnMatch(a_orb, b_orb, k=2)
            for pair in pairs:
                if len(pair) < 2:
                    continue
                first, second = pair
                if first.distance < 0.78 * second.distance:
                    good_matches += 1
            orb_score = min(100.0, good_matches * 4.6)
        except Exception:
            orb_score = None
    if orb_score is None:
        final_score = base_score
    else:
        final_score = max(base_score, base_score * 0.45 + orb_score * 0.55)
    distance = max(0.0, 1.0 - final_score / 100.0)
    return distance, {"artwork_score": round(final_score, 2), "hash_score": round(base_score, 2), "orb_score": round(orb_score, 2) if orb_score is not None else None, "orb_matches": good_matches}


def build_reference_features(candidates: list[dict[str, Any]], *, max_candidates=450) -> dict[str, dict[str, Any]]:
    features = {}
    for candidate in candidates[:max_candidates]:
        source = str(candidate.get("image_url", "") or "")
        if not source:
            continue
        cache_path = _feature_cache_path(source)
        if cache_path.exists():
            cached = _feature_from_json(load_json_file(cache_path, {}))
            if cached is not None and cached.get("hist") is not None and len(cached["hist"]):
                features[candidate["drop_card_key"]] = cached
                continue
        image = _load_image(source, max_side=512)
        if image is None:
            continue
        feature = _feature(image)
        features[candidate["drop_card_key"]] = feature
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(_feature_to_json(feature), separators=(",", ":")), encoding="utf-8")
        except Exception:
            pass
    return features


def _reference_feature_for_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    source = str(candidate.get("image_url", "") or "")
    if not source:
        return None
    cache_path = _feature_cache_path(source)
    if cache_path.exists():
        cached = _feature_from_json(load_json_file(cache_path, {}))
        if cached is not None and cached.get("hist") is not None and len(cached["hist"]):
            return cached
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.scheme not in {"", "file"}:
        return None
    if not Path(source).exists():
        return None
    image = _load_image(source, max_side=512)
    if image is None:
        return None
    feature = _feature(image)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(_feature_to_json(feature), separators=(",", ":")), encoding="utf-8")
    except Exception:
        pass
    return feature


def _reference_artwork_feature_for_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    source = str(candidate.get("image_url", "") or "")
    if not source:
        return None
    cache_path = _artwork_feature_cache_path(source)
    if cache_path.exists():
        cached = _artwork_feature_from_json(load_json_file(cache_path, {}))
        if cached is not None:
            return cached
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        # Network references are intentionally not fetched in the tight
        # fallback path unless already cached by _load_image.
        pass
    image = _load_image(source, max_side=768)
    if image is None:
        return None
    feature = _artwork_feature(image)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(_artwork_feature_to_json(feature), separators=(",", ":")), encoding="utf-8")
    except Exception:
        pass
    return feature


def _photo_visual_feature(path: str) -> dict[str, Any] | None:
    image = _load_image(path, max_side=1024)
    if image is None:
        return None
    regions = detect_card_regions(image)
    if regions:
        image = _crop_region(image, regions[0])
    return _feature(image)


def _photo_artwork_feature(path: str) -> dict[str, Any] | None:
    image = _load_image(path, max_side=1400)
    if image is None:
        return None
    return _artwork_feature(image)


def _apply_visual_shortlist_scores(path: str, scored: list[dict[str, Any]], *, limit=5, broad=False) -> dict[str, Any]:
    started = time.perf_counter()
    if not scored:
        return {"used": 0, "elapsed": 0.0, "broad": broad}
    refs = []
    candidate_pool = scored[:limit]
    if broad:
        high_signal = [item for item in scored if float(item.get("score") or 0.0) >= 30 or (item.get("candidate") or {}).get("japanese")]
        candidate_pool = (high_signal or scored)[: min(40, len(scored))]
    for item in candidate_pool:
        candidate = item.get("candidate") or {}
        ref_feature = _reference_feature_for_candidate(candidate)
        artwork_feature = _reference_artwork_feature_for_candidate(candidate)
        if ref_feature is not None or artwork_feature is not None:
            refs.append((item, ref_feature, artwork_feature))
    if not refs:
        return {"used": 0, "elapsed": round(time.perf_counter() - started, 3), "broad": broad}
    photo_feature = _photo_visual_feature(path)
    photo_artwork_feature = _photo_artwork_feature(path)
    if photo_feature is None and photo_artwork_feature is None:
        return {"used": 0, "elapsed": round(time.perf_counter() - started, 3), "broad": broad}
    visual_rows = []
    for item, ref_feature, artwork_feature in refs:
        scores = []
        if photo_feature is not None and ref_feature is not None:
            distance = _feature_distance(photo_feature, ref_feature)
            scores.append(("carte", max(0.0, 100.0 * (1.0 - min(1.0, distance))), {}))
        if photo_artwork_feature is not None and artwork_feature is not None:
            _distance, details = _artwork_feature_distance(photo_artwork_feature, artwork_feature)
            scores.append(("artwork", float(details.get("artwork_score") or 0.0), details))
        if not scores:
            continue
        mode, visual_score, details = max(scores, key=lambda row: row[1])
        item["visual_score"] = round(visual_score, 2)
        if mode == "artwork":
            item["visual_artwork_score"] = round(visual_score, 2)
            item["visual_artwork_details"] = details
        visual_rows.append((visual_score, item, mode))
    if not visual_rows:
        return {"used": 0, "elapsed": round(time.perf_counter() - started, 3), "broad": broad}
    visual_rows.sort(key=lambda row: row[0], reverse=True)
    best_visual_score, best_visual_item, best_mode = visual_rows[0]
    second_visual_score = visual_rows[1][0] if len(visual_rows) > 1 else 0.0
    for score, item, mode in visual_rows:
        label = "artwork" if mode == "artwork" else "carte"
        item.setdefault("reasons", []).append(f"visuel {label} {score:.0f}")
        item["visual_margin"] = round(score - second_visual_score if item is best_visual_item else best_visual_score - score, 2)
    current_score = float(best_visual_item.get("score") or 0.0)
    if current_score >= 54 and best_visual_score >= 70:
        best_visual_item["score"] = round(min(100.0, current_score + 6.0), 2)
        best_visual_item.setdefault("reasons", []).append("bonus visuel prudent")
    return {
        "used": len(visual_rows),
        "elapsed": round(time.perf_counter() - started, 3),
        "broad": broad,
        "best_visual_score": round(best_visual_score, 2),
        "second_visual_score": round(second_visual_score, 2),
        "best_mode": best_mode,
    }


def _ocr_status() -> tuple[bool, str]:
    if importlib.util.find_spec("rapidocr_onnxruntime") is not None:
        return True, "RapidOCR ONNXRuntime disponible; OCR local ciblé nom/numéro actif."
    return False, "Aucun OCR local disponible dans l'environnement; matching FR limité au visuel/heuristiques."


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    if importlib.util.find_spec("rapidocr_onnxruntime") is None:
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
        return _OCR_ENGINE
    except Exception:
        return None


def _ocr_image_array(engine, image: Image.Image, region_name: str) -> list[dict[str, Any]]:
    arr = np.asarray(image.convert("RGB"), dtype=np.uint8)
    try:
        rows = engine(arr)[0] or []
    except Exception:
        return []
    parsed = []
    for row in rows:
        if len(row) < 3:
            continue
        box, text, score = row[:3]
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            confidence = 0.0
        text = str(text or "").strip()
        if not text:
            continue
        parsed.append({"region": region_name, "text": text, "confidence": round(confidence, 3), "box": box})
    return parsed


def _ocr_signals_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    name_regions = {"top_name", "top_name_wide", "top_name_low"}
    generic_name_noise = {
        "base",
        "basb",
        "niveau",
        "niveaut",
        "niveaui",
        "pv",
        "hp",
        "talent",
        "faiblesse",
        "resistance",
        "retraite",
        "dresseur",
        "supporter",
        "trainer",
        "stagei",
        "staget",
        "evolvesfrom",
        "evolutionde",
        "energie",
        "energy",
    }
    name_texts = []
    seen_names = set()
    for row in rows:
        text = row["text"]
        folded = _fold_text(text)
        if row["region"] not in name_regions or not re.search(r"[A-Za-zÀ-ÿ]", text):
            continue
        if folded in generic_name_noise or len(folded) < 3:
            continue
        if folded in seen_names:
            continue
        seen_names.add(folded)
        name_texts.append(text)

    number_texts = []
    collector_number_texts = []
    all_number_texts = []
    collector_regions = {
        "bottom_collector",
        "bottom_edge",
        "v_union_top",
        "v_union_bottom",
        "v_union_left",
        "v_union_right",
    }
    for row in rows:
        text = row["text"]
        tokens = _extract_number_tokens(text) if re.search(r"\d", text) else []
        all_number_texts.extend(tokens)
        if row["region"] == "bottom_number":
            number_texts.extend(tokens)
        if row["region"] in collector_regions or str(row["region"]).startswith("v_union_") or any("/" in _normalize_card_number(token) for token in tokens):
            collector_number_texts.extend(tokens)
    return {
        "name_texts": name_texts,
        "number_texts": sorted(set(number_texts)),
        "collector_number_texts": sorted(set(collector_number_texts)),
        "all_number_texts": sorted(set(all_number_texts)),
    }


def run_ocr_for_photo(path: str, *, orientation_degrees: int = 0) -> dict[str, Any]:
    orientation_degrees = int(orientation_degrees or 0) % 360
    cache_source = path if orientation_degrees == 0 else f"{Path(path).resolve()}|orientation={orientation_degrees}"
    cache_path = _ocr_cache_path(cache_source)
    if cache_path.exists():
        cached = load_json_file(cache_path, None)
        if isinstance(cached, dict):
            return cached
    engine = _get_ocr_engine()
    if engine is None:
        return {"available": False, "rows": [], "name_texts": [], "number_texts": [], "raw_text": ""}
    image = _load_image(path, max_side=1800)
    if image is None:
        return {"available": False, "rows": [], "name_texts": [], "number_texts": [], "raw_text": ""}
    if orientation_degrees:
        image = image.rotate(-orientation_degrees, expand=True)
    w, h = image.size
    base_crops = {
        "top_name": image.crop((0, 0, w, int(h * 0.24))).resize((w * 2, int(h * 0.24) * 2), Image.Resampling.LANCZOS),
        "top_name_wide": image.crop((0, 0, w, int(h * 0.36))).resize((w * 2, int(h * 0.36) * 2), Image.Resampling.LANCZOS),
        "bottom_number": image.crop((0, int(h * 0.68), w, h)).resize((w * 2, int(h * 0.32) * 2), Image.Resampling.LANCZOS),
    }
    rows = []
    for region_name, crop in base_crops.items():
        rows.extend(_ocr_image_array(engine, crop, region_name))
    signals = _ocr_signals_from_rows(rows)
    if not signals["name_texts"]:
        fallback = image.crop((0, int(h * 0.06), w, int(h * 0.42))).resize((w * 2, int(h * 0.36) * 2), Image.Resampling.LANCZOS)
        rows.extend(_ocr_image_array(engine, fallback, "top_name_low"))
        signals = _ocr_signals_from_rows(rows)
    if not signals["collector_number_texts"]:
        fallback_crops = {
            "bottom_collector": image.crop((int(w * 0.42), int(h * 0.72), w, h)).resize((int(w * 0.58) * 2, int(h * 0.28) * 2), Image.Resampling.LANCZOS),
            "bottom_edge": image.crop((int(w * 0.32), int(h * 0.82), w, h)).resize((int(w * 0.68) * 2, int(h * 0.18) * 2), Image.Resampling.LANCZOS),
        }
        for region_name, crop in fallback_crops.items():
            rows.extend(_ocr_image_array(engine, crop, region_name))
        signals = _ocr_signals_from_rows(rows)
    payload = {
        "available": True,
        "engine": "rapidocr_onnxruntime",
        "rows": rows,
        "name_texts": signals["name_texts"],
        "number_texts": signals["number_texts"],
        "collector_number_texts": signals["collector_number_texts"],
        "all_number_texts": signals["all_number_texts"],
        "raw_text": " | ".join(row["text"] for row in rows),
        "orientation_degrees": orientation_degrees,
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return payload


def run_v_union_edge_ocr(path: str, *, base_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read collector numbers from every edge of a V-UNION physical card."""
    cache_source = f"{Path(path).resolve()}|v_union_edges=4"
    cache_path = _ocr_cache_path(cache_source)
    if cache_path.exists():
        cached = load_json_file(cache_path, None)
        if isinstance(cached, dict):
            return cached
    engine = _get_ocr_engine()
    image = _load_image(path, max_side=1800)
    if engine is None or image is None:
        return base_payload or {
            "available": False,
            "rows": [],
            "name_texts": [],
            "number_texts": [],
            "collector_number_texts": [],
            "all_number_texts": [],
            "raw_text": "",
        }

    regions = detect_card_regions(image, max_regions=1)
    card_image = _crop_region(image, regions[0]) if regions else image
    w, h = card_image.size
    edge_crops = {
        "v_union_top": card_image.crop((0, 0, w, max(1, int(h * 0.22)))),
        "v_union_bottom": card_image.crop((0, int(h * 0.78), w, h)),
        "v_union_left": card_image.crop((0, 0, max(1, int(w * 0.24)), h)).rotate(90, expand=True),
        "v_union_right": card_image.crop((int(w * 0.76), 0, w, h)).rotate(270, expand=True),
        "v_union_left_narrow": card_image.crop((0, 0, max(1, int(w * 0.16)), h)).rotate(90, expand=True),
        "v_union_right_narrow": card_image.crop((int(w * 0.84), 0, w, h)).rotate(270, expand=True),
    }
    rows = list((base_payload or {}).get("rows") or [])
    for region_name, crop in edge_crops.items():
        scaled = crop.resize((max(1, crop.width * 3), max(1, crop.height * 3)), Image.Resampling.LANCZOS)
        rows.extend(_ocr_image_array(engine, scaled, region_name))
        if region_name.endswith("_narrow"):
            contrasted = ImageOps.autocontrast(ImageOps.grayscale(scaled))
            rows.extend(_ocr_image_array(engine, contrasted, region_name + "_contrast"))
    for degrees in (90, 270):
        rotated_payload = run_ocr_for_photo(path, orientation_degrees=degrees)
        for row in rotated_payload.get("rows") or []:
            rows.append({**row, "region": f"v_union_rot{degrees}_{row.get('region') or 'full'}"})
    signals = _ocr_signals_from_rows(rows)
    edge_numbers = set()
    for row in rows:
        if not str(row.get("region") or "").startswith("v_union_"):
            continue
        compact = re.sub(r"[^A-Z0-9]", "", str(row.get("text") or "").upper().replace("O", "0"))
        match = re.search(r"(?:S?WSH)\d{3}", compact)
        if match:
            value = match.group(0)
            edge_numbers.add(value if value.startswith("SWSH") else "S" + value)
            continue
        partial = re.search(r"(?:[S5]?H)(\d{3})", compact)
        if partial:
            edge_numbers.add("SWSH" + partial.group(1))
    normalized_edge_numbers = {_normalize_card_number(value) for value in edge_numbers}
    signals["collector_number_texts"] = sorted(set(signals["collector_number_texts"]) | normalized_edge_numbers)
    signals["all_number_texts"] = sorted(set(signals["all_number_texts"]) | normalized_edge_numbers)
    payload = {
        **(base_payload or {}),
        "available": True,
        "engine": "rapidocr_onnxruntime",
        "rows": rows,
        "name_texts": signals["name_texts"],
        "number_texts": signals["number_texts"],
        "collector_number_texts": signals["collector_number_texts"],
        "all_number_texts": signals["all_number_texts"],
        "raw_text": " | ".join(row["text"] for row in rows),
        "v_union_edge_ocr": True,
        "v_union_edge_numbers": sorted(edge_numbers),
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return payload


def _fold_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("0", "o").replace("1", "i")
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _normalize_card_number(value: str) -> str:
    text = str(value or "").strip().upper()
    text = text.replace("＃", "#").replace("／", "/").replace("O", "0")
    text = re.sub(r"\s+", "", text)
    text = text.strip("#:;,.")
    if "/" in text:
        left, right = text.split("/", 1)
        left = left.lstrip("0") or "0"
        right = re.sub(r"[^A-Z0-9]", "", right)
        return f"{left}/{right}" if right else left
    match = re.search(r"[A-Z]{0,3}\d+[A-Z]*", text)
    return (match.group(0).lstrip("0") or "0") if match else ""


def _number_local(value: str) -> str:
    normalized = _normalize_card_number(value)
    return normalized.split("/", 1)[0] if normalized else ""


def _special_layout_signals(ocr_payload: dict[str, Any], candidate: dict[str, Any] | None = None) -> list[str]:
    # Body text regularly contains words such as "legendaire". Only the card
    # title and the candidate name are reliable layout signals.
    title_tokens = [_fold_text(value) for value in (ocr_payload.get("name_texts") or [])]
    candidate_name = _fold_text((candidate or {}).get("name") or "")
    signals = []
    legend_tokens = {"legende", "legend", "pokemonlegende", "pokemonlegend"}
    if (
        candidate_name in legend_tokens
        or candidate_name.endswith("legende")
        or any(token in legend_tokens or (len(token) <= 48 and token.endswith(("legende", "legend"))) for token in title_tokens)
    ):
        signals.append("layout spécial / LÉGENDE détecté")
    if "vunion" in candidate_name or any(token in {"vunion", "pokemonvunion"} for token in title_tokens):
        signals.append("layout spécial / V-UNION détecté")
    return signals


def _ocr_name_variants(ocr_payload: dict[str, Any]) -> list[str]:
    names = [str(value or "").strip() for value in (ocr_payload.get("name_texts") or []) if str(value or "").strip()]
    variants = list(names)
    suffixes = {"ex", "gx", "v", "vmax", "vstar", "vunion", "break", "legende", "legend"}
    for left in names:
        for right in names:
            if left == right:
                continue
            folded_right = _fold_text(right)
            folded_left = _fold_text(left)
            if folded_right in suffixes or folded_left in suffixes:
                variants.append(f"{left} {right}")
    unique = []
    seen = set()
    for value in variants:
        folded = _fold_text(value)
        if not folded or folded in seen:
            continue
        seen.add(folded)
        unique.append(value)
    return unique


def _full_number_mismatch_reason(ocr_payload: dict[str, Any], best: dict[str, Any] | None) -> str:
    if not best:
        return ""
    candidate = best.get("candidate") or {}
    candidate_number = _normalize_card_number(candidate.get("number") or "")
    candidate_local = _number_local(candidate_number)
    if not candidate_local or best.get("number_kind") not in {"local_collector", "plain_collector", "noisy_number"}:
        return ""
    full_ocr_numbers = [
        _normalize_card_number(token)
        for token in (ocr_payload.get("collector_number_texts") or [])
        if "/" in _normalize_card_number(token)
    ]
    if not full_ocr_numbers:
        return ""
    if candidate_number and "/" in candidate_number and candidate_number in full_ocr_numbers:
        return ""
    same_local = [number for number in full_ocr_numbers if _number_local(number) == candidate_local]
    if not same_local:
        return ""
    if candidate_number and "/" in candidate_number:
        return f"numéro OCR {same_local[0]} incompatible avec candidat {candidate_number}"
    return f"numéro OCR complet {same_local[0]} absent des métadonnées candidat"


def _expand_compact_number_token(token: str) -> list[str]:
    digits = re.sub(r"\D", "", str(token or ""))
    expanded = []
    if len(digits) == 6:
        expanded.append(f"{digits[:3]}/{digits[3:]}")
    if len(digits) == 7 and digits[3] == "0":
        expanded.append(f"{digits[:3]}/{digits[4:]}")
    if len(digits) == 7 and digits[-4] == "0":
        expanded.append(f"{digits[:-4]}/{digits[-3:]}")
    return [_normalize_card_number(item) for item in expanded if _normalize_card_number(item)]


def _extract_number_tokens(text: str) -> list[str]:
    raw = str(text or "").upper().replace("O", "0")
    tokens = []
    for match in re.finditer(r"[A-Z]{0,3}\d{1,4}\s*/\s*[A-Z]?\d{1,4}|\d{6,7}|[A-Z]{1,4}\d{1,4}[A-Z]?|\d{1,4}", raw):
        normalized = _normalize_card_number(match.group(0))
        if normalized:
            tokens.append(normalized)
            tokens.extend(_expand_compact_number_token(match.group(0)))
    return tokens


def _similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    fa = _fold_text(a)
    fb = _fold_text(b)
    if not fa or not fb:
        return 0.0
    return SequenceMatcher(None, fa, fb).ratio()


def _candidate_score_from_ocr(
    ocr_payload: dict[str, Any],
    candidate: dict[str, Any],
    *,
    back_type: str = "",
    family_hint: str = "",
) -> dict[str, Any]:
    candidate_number = str(candidate.get("number") or "")
    cand_num_full = _normalize_card_number(candidate_number)
    cand_num_local = _number_local(candidate_number)
    ocr_numbers = [_normalize_card_number(token) for token in ocr_payload.get("number_texts", [])]
    collector_numbers = [_normalize_card_number(token) for token in ocr_payload.get("collector_number_texts", [])]
    collector_numbers = [token for token in collector_numbers if token]
    collector_locals_from_full = [_number_local(token) for token in collector_numbers if "/" in token]
    all_ocr_locals = [_number_local(token) for token in ocr_numbers]
    number_score = 0.0
    number_reason = ""
    number_kind = ""
    number_conflict = False
    if cand_num_full and "/" in cand_num_full and cand_num_full in collector_numbers:
        number_score = 80.0
        number_reason = f"numéro exact {cand_num_full}"
        number_kind = "full_collector"
    elif cand_num_local and cand_num_local in collector_locals_from_full and len(cand_num_local) >= 2:
        same_local_numbers = [value for value in collector_numbers if _number_local(value) == cand_num_local]
        if cand_num_full and "/" in cand_num_full and all(value != cand_num_full for value in same_local_numbers):
            # Pokestock sometimes keeps the FR reference for a physical JP
            # card. Preserve the local-number signal, but require name or
            # artwork corroboration before an automatic match.
            number_score = 66.0
            number_reason = f"numéro local {cand_num_local}, total de set incompatible"
            number_kind = "conflicting_collector"
            number_conflict = True
        else:
            number_score = 66.0
            number_reason = f"numéro local {cand_num_local}"
            number_kind = "local_collector"
    elif cand_num_full and "/" not in cand_num_full and cand_num_full in collector_numbers and len(cand_num_local) >= 2:
        number_score = 58.0
        number_reason = f"numéro simple collector {cand_num_full}"
        number_kind = "plain_collector"
    elif cand_num_full and cand_num_full in ocr_numbers and len(cand_num_local) >= 2:
        number_score = 38.0
        number_reason = f"numéro simple bruité {cand_num_full}"
        number_kind = "noisy_number"
    elif cand_num_local and cand_num_local in all_ocr_locals and len(cand_num_local) >= 2:
        number_score = 30.0
        number_reason = f"numéro local bruité {cand_num_local}"
        number_kind = "noisy_number"

    original_name_scores = [
        (_similarity(text, str(candidate.get("name") or "")), text)
        for text in (ocr_payload.get("name_texts") or [])
    ]
    original_name_similarity = max((score for score, _text in original_name_scores), default=0.0)
    name_scores = [(_similarity(text, str(candidate.get("name") or "")), text) for text in _ocr_name_variants(ocr_payload)]
    best_name_score, best_name_text = max(name_scores, default=(0.0, ""))
    original_name_folds = {_fold_text(value) for value in (ocr_payload.get("name_texts") or [])}
    name_points = 0.0
    name_reason = ""
    if best_name_score >= 0.96:
        name_points = 56.0
        name_reason = f"nom exact/proche {best_name_text}"
    elif best_name_score >= 0.86:
        name_points = 42.0
        name_reason = f"nom probable {best_name_text}"
    elif best_name_score >= 0.74:
        name_points = 24.0
        name_reason = f"nom partiel {best_name_text}"

    language_points = 0.0
    if back_type == "japanese":
        language_points = 10.0 if candidate.get("japanese") else 2.0

    family_points = 0.0
    if family_hint and _fold_text(candidate.get("name") or "") == _fold_text(family_hint):
        family_points = 14.0
    total = number_score + name_points + language_points + family_points
    reasons = [
        reason
        for reason in (
            number_reason,
            name_reason,
            "signal verso JP" if language_points else "",
            f"famille V-UNION du groupe : {family_hint}" if family_points else "",
        )
        if reason
    ]
    return {
        "candidate": candidate,
        "score": round(min(total, 100.0), 2),
        "number_match": bool(number_score),
        "number_kind": number_kind,
        "number_conflict": number_conflict,
        "candidate_number_full": cand_num_full,
        "candidate_number_local": cand_num_local,
        "name_similarity": round(best_name_score, 3),
        "original_name_similarity": round(original_name_similarity, 3),
        "ocr_name": best_name_text,
        "name_joined": bool(best_name_text and _fold_text(best_name_text) not in original_name_folds),
        "ocr_numbers": ocr_numbers,
        "collector_numbers": collector_numbers,
        "reasons": reasons,
    }


def match_front_photo_ocr(
    path: str,
    candidates: list[dict[str, Any]],
    used_counts: dict[str, int] | None = None,
    *,
    back_type: str = "",
    ocr_payload_override: dict[str, Any] | None = None,
    family_hint: str = "",
):
    used_counts = used_counts or {}
    ocr_payload = ocr_payload_override or run_ocr_for_photo(path)
    available_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("historical_drop_member")
        or used_counts.get(candidate.get("drop_card_key", ""), 0) < max(1, _safe_int(candidate.get("quantity"), 1))
    ]
    scored = [
        _candidate_score_from_ocr(
            ocr_payload,
            candidate,
            back_type=back_type,
            family_hint=family_hint,
        )
        for candidate in available_candidates
    ]
    exact_name_count = sum(1 for item in scored if item.get("name_similarity", 0.0) >= 0.96)
    full_number_counts = {}
    local_number_counts = {}
    for item in scored:
        if item.get("number_kind") == "full_collector":
            full_number_counts[item.get("candidate_number_full", "")] = full_number_counts.get(item.get("candidate_number_full", ""), 0) + 1
        if item.get("number_kind") == "local_collector":
            local_number_counts[item.get("candidate_number_local", "")] = local_number_counts.get(item.get("candidate_number_local", ""), 0) + 1
    for item in scored:
        current_score = float(item.get("score") or 0.0)
        full_key = item.get("candidate_number_full", "")
        local_key = item.get("candidate_number_local", "")
        if item.get("number_kind") == "full_collector" and full_number_counts.get(full_key, 0) == 1:
            item["score"] = max(current_score, 92.0)
            item.setdefault("reasons", []).append("numéro complet unique dans le drop")
        elif item.get("number_kind") == "local_collector" and local_number_counts.get(local_key, 0) == 1:
            item["score"] = max(current_score, 86.0)
            item.setdefault("reasons", []).append("numéro local unique dans le drop")
    if exact_name_count == 1:
        for item in scored:
            if item.get("name_similarity", 0.0) >= 0.96 and not item.get("number_match"):
                item["score"] = max(float(item.get("score") or 0.0), 88.0)
                item.setdefault("reasons", []).append("nom OCR unique dans le drop")
    for item in scored:
        candidate = item.get("candidate") or {}
        key = candidate.get("drop_card_key", "")
        quantity = max(1, _safe_int(candidate.get("quantity"), 1))
        if candidate.get("historical_drop_member") and used_counts.get(key, 0) >= quantity:
            # This is an assignment hint only. It must never make a sold card
            # disappear from the historical candidate set or create a false
            # not_in_drop diagnosis.
            item["score"] = max(0.0, float(item.get("score") or 0.0) - 12.0)
            item["historical_reuse_penalty"] = 12.0
            item.setdefault("reasons", []).append("occurrence historique déjà proposée ailleurs (-12)")
    scored.sort(key=lambda item: item["score"], reverse=True)
    visual_info = {"used": 0, "elapsed": 0.0, "broad": False}
    if scored and (ocr_payload.get("name_texts") or ocr_payload.get("number_texts")):
        pre_best = scored[0] if scored else None
        pre_second = scored[1] if len(scored) > 1 else None
        pre_margin = (float(pre_best.get("score") or 0.0) - float(pre_second.get("score") or 0.0)) if pre_best and pre_second else 100.0
        no_name = not bool(ocr_payload.get("name_texts"))
        no_usable_name = float(pre_best.get("name_similarity") or 0.0) < 0.74
        has_cjk = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", str(ocr_payload.get("raw_text") or "")))
        number_needs_visual = pre_best.get("number_kind") in {"conflicting_collector", "local_collector", "plain_collector"}
        broad_visual = (
            (no_name or no_usable_name)
            and (float(pre_best.get("score") or 0.0) < 54 or number_needs_visual)
            and (bool(ocr_payload.get("collector_number_texts")) or has_cjk)
        )
        needs_visual = (
            broad_visual
            or pre_margin < 14
            or float(pre_best.get("score") or 0.0) < 86
            or (pre_best and pre_best.get("number_kind") in {"plain_collector", "noisy_number"})
        )
        if needs_visual:
            visual_info = _apply_visual_shortlist_scores(path, scored, limit=5, broad=broad_visual)
            if broad_visual:
                visual_candidates = [
                    item
                    for item in scored
                    if (item.get("candidate") or {}).get("japanese")
                    and float(item.get("visual_artwork_score") or 0.0) >= 72
                ]
                visual_candidates.sort(key=lambda item: float(item.get("visual_artwork_score") or 0.0), reverse=True)
                if visual_candidates:
                    visual_best = visual_candidates[0]
                    visual_second = float(visual_candidates[1].get("visual_artwork_score") or 0.0) if len(visual_candidates) > 1 else 0.0
                    visual_margin = float(visual_best.get("visual_artwork_score") or 0.0) - visual_second
                    if visual_margin >= 8:
                        visual_best["score"] = max(float(visual_best.get("score") or 0.0), 87.0)
                        visual_best["v13_visual_jp_override"] = True
                        visual_best.setdefault("reasons", []).append("V13: artwork JP nettement distinctif sur shortlist élargie")
                # A physical Japanese card can keep French metadata in
                # PokéStock. In that case the color histogram may prefer a
                # merely similar card, while a cluster of ORB keypoints still
                # identifies the shared artwork. This only changes the orange
                # proposal and can never create a green automatic match.
                jp_orb_candidates = [
                    item
                    for item in scored
                    if (item.get("candidate") or {}).get("japanese")
                    and float(item.get("visual_artwork_score") or 0.0) >= 60.0
                    and int((item.get("visual_artwork_details") or {}).get("orb_matches") or 0) >= 10
                ]
                jp_orb_candidates.sort(
                    key=lambda item: int((item.get("visual_artwork_details") or {}).get("orb_matches") or 0),
                    reverse=True,
                )
                if jp_orb_candidates:
                    orb_best = jp_orb_candidates[0]
                    orb_best_matches = int((orb_best.get("visual_artwork_details") or {}).get("orb_matches") or 0)
                    orb_second_matches = max(
                        (
                            int((item.get("visual_artwork_details") or {}).get("orb_matches") or 0)
                            for item in scored
                            if item is not orb_best and (item.get("candidate") or {}).get("japanese")
                        ),
                        default=0,
                    )
                    if orb_best_matches - orb_second_matches >= 5:
                        current_max = max((float(item.get("score") or 0.0) for item in scored), default=0.0)
                        orb_best["score"] = round(min(95.0, max(87.0, current_max + 1.0)), 2)
                        orb_best["v14_7_jp_orb_override"] = True
                        orb_best["v14_7_jp_orb_margin"] = orb_best_matches - orb_second_matches
                        orb_best.setdefault("reasons", []).append(
                            f"V14.7: artwork JP confirmé par ORB ({orb_best_matches} points, marge {orb_best_matches - orb_second_matches})"
                        )
            scored.sort(key=lambda item: (float(item.get("score") or 0.0), float(item.get("visual_score") or 0.0)), reverse=True)
    top = scored[:3]
    best = top[0] if top else None
    second = top[1] if len(top) > 1 else None
    margin = (best["score"] - second["score"]) if best and second else (best["score"] if best else 0.0)
    status = "unrecognized"
    v8_auto_reason = ""
    v9_auto_reason = ""
    v10_safety_reason = ""
    special_layout = False
    if best:
        strong_name = best["name_similarity"] >= 0.96
        probable_name = best["name_similarity"] >= 0.86
        second_name = float(second.get("name_similarity") or 0.0) if second else 0.0
        reliable_number = best.get("number_kind") in {"full_collector", "local_collector"}
        weak_number_without_name = best.get("number_kind") in {"local_collector", "plain_collector", "noisy_number"} and best.get("name_similarity", 0.0) < 0.74
        artwork_score = float(best.get("visual_artwork_score") or 0.0)
        visual_margin = float(best.get("visual_margin") or 0.0)
        special_signals = _special_layout_signals(ocr_payload, best.get("candidate") or {})
        special_layout = bool(special_signals)
        number_conflict = bool(best.get("number_conflict"))
        v13_visual_jp_override = bool(best.get("v13_visual_jp_override"))
        v14_7_jp_orb_override = bool(best.get("v14_7_jp_orb_override"))
        conflict_supported_by_name = number_conflict and probable_name
        if v14_7_jp_orb_override:
            status = "review"
        elif v13_visual_jp_override:
            status = "review"
        elif best["score"] >= 86 and margin >= 12 and best["number_match"] and not weak_number_without_name and (not number_conflict or conflict_supported_by_name):
            status = "recognized"
        elif reliable_number and probable_name and best["score"] >= 92 and margin >= 6 and second_name < 0.74:
            status = "recognized"
            v8_auto_reason = "V8: numéro fiable + nom probable malgré marge courte"
            best.setdefault("reasons", []).append(v8_auto_reason)
        elif not ocr_payload.get("name_texts") and reliable_number and best["score"] >= 86 and artwork_score >= 64 and visual_margin >= 10:
            status = "recognized"
            v9_auto_reason = "V9: numéro fiable + artwork distinctif"
            best.setdefault("reasons", []).append(v9_auto_reason)
        elif not (ocr_payload.get("name_texts") or ocr_payload.get("collector_number_texts")) and artwork_score >= 84 and visual_margin >= 18:
            status = "recognized"
            v9_auto_reason = "V9: artwork seul très distinctif"
            best["score"] = max(float(best.get("score") or 0.0), min(94.0, artwork_score))
            best.setdefault("reasons", []).append(v9_auto_reason)
        elif strong_name and best["score"] >= 88 and margin >= 30:
            status = "recognized"
        elif best["score"] >= 54:
            status = "review"
        if special_layout and status == "recognized":
            status = "review"
            v10_safety_reason = " · ".join(special_signals)
            best.setdefault("reasons", []).append(v10_safety_reason)
        number_mismatch_reason = _full_number_mismatch_reason(ocr_payload, best)
        if number_mismatch_reason and not ocr_payload.get("name_texts"):
            if status == "recognized":
                status = "review"
            elif status == "review" and float(best.get("visual_artwork_score") or 0.0) < 72:
                status = "unrecognized"
            v10_safety_reason = number_mismatch_reason
            best.setdefault("reasons", []).append(number_mismatch_reason)
    if status == "recognized" and not v8_auto_reason and second and second.get("number_kind") == "noisy_number":
        v8_auto_reason = "V8: numéro parasite déclassé chez le candidat concurrent"
        best.setdefault("reasons", []).append(v8_auto_reason)
    if status != "recognized" and best and (best.get("visual_artwork_score") or 0):
        if float(best.get("score") or 0.0) < 54 and float(best.get("visual_artwork_score") or 0.0) >= 58:
            status = "review"
    v13_auto_reason = ""
    if status == "recognized" and best:
        if (
            best.get("name_joined")
            and float(best.get("original_name_similarity") or 0.0) < 0.86
            and float(best.get("score") or 0.0) >= 92
        ):
            v13_auto_reason = "V13: nom OCR reconstitué avec son suffixe"
        elif "legend" in _fold_text(ocr_payload.get("raw_text") or "") and not special_layout:
            v13_auto_reason = "V13: faux layout spécial écarté (texte d'attaque)"
        elif best.get("number_kind") == "full_collector":
            conflicting_scores = [float(item.get("score") or 0.0) for item in scored[1:] if item.get("number_conflict")]
            legacy_second = max(conflicting_scores + [float(second.get("score") or 0.0) if second else 0.0, 86.0 if conflicting_scores else 0.0])
            if float(best.get("score") or 0.0) - legacy_second < 12 <= margin:
                v13_auto_reason = "V13: candidat concurrent déclassé par total de set incompatible"
        if v13_auto_reason:
            best.setdefault("reasons", []).append(v13_auto_reason)
    japanese_candidate = bool(best and (best.get("candidate") or {}).get("japanese"))
    japanese_artwork_score = float(best.get("visual_artwork_score") or 0.0) if best else 0.0
    japanese_signal = ""
    japanese_number_signal = bool(
        best
        and japanese_candidate
        and best.get("number_kind") in {"local_collector", "plain_collector", "conflicting_collector"}
    )
    if back_type == "japanese" and japanese_candidate:
        japanese_signal = "verso JP + candidat JAP"
    elif japanese_candidate and bool(best.get("v14_7_jp_orb_override")):
        japanese_signal = "artwork JP confirmé par points de structure"
    elif japanese_candidate and bool(best.get("v13_visual_jp_override")):
        japanese_signal = "artwork distinctif + candidat JAP"
    elif japanese_candidate and japanese_artwork_score >= 72:
        japanese_signal = "candidat JAP + artwork compatible"
    elif japanese_number_signal:
        japanese_signal = "numéro local compatible + candidat JAP"
    elif back_type == "japanese":
        japanese_signal = "verso JP mais candidat FR"
    if status == "unrecognized" and japanese_number_signal:
        status = "review"

    full_ocr_numbers = [
        _normalize_card_number(value)
        for value in (ocr_payload.get("collector_number_texts") or [])
        if "/" in _normalize_card_number(value)
    ]
    exact_full_available = any(
        _normalize_card_number(candidate.get("number") or "") in full_ocr_numbers
        for candidate in candidates
        if "/" in _normalize_card_number(candidate.get("number") or "")
    )
    full_ocr_locals = {value.split("/", 1)[0] for value in full_ocr_numbers if value}
    membership_scores = [
        _candidate_score_from_ocr(ocr_payload, candidate, back_type=back_type, family_hint=family_hint)
        for candidate in candidates
    ]
    compatible_local_name_available = any(
        item.get("candidate_number_local") in full_ocr_locals
        and float(item.get("name_similarity") or 0.0) >= 0.86
        for item in membership_scores
    )
    not_in_drop_confidence = ""
    best_name_similarity = float(best.get("name_similarity") or 0.0) if best else 0.0
    plausible_name_texts = [
        value for value in (ocr_payload.get("name_texts") or [])
        if 3 <= len(_fold_text(value)) <= 32
    ]
    same_name_ocr_conflict = bool(
        best
        and full_ocr_numbers
        and not exact_full_available
        and not compatible_local_name_available
        and best_name_similarity >= 0.86
        and not best.get("number_match")
        and bool(best.get("candidate_number_full"))
    )
    best_membership = drop_candidate_membership((best or {}).get("candidate"), candidates)
    strong_drop_candidate = bool(
        best_membership.get("in_drop")
        and best
        and (
            bool(best.get("number_match"))
            or (
                float(best.get("name_similarity") or 0.0) >= 0.86
                and float(best.get("score") or 0.0) >= 54.0
                and margin >= 12.0
            )
        )
    )
    # A stray OCR number alone cannot make a strong current Drop candidate
    # disappear. It may still be shown in diagnostic details, but
    # not_in_drop is reserved for a proposal with no compatible historical
    # Drop member.
    same_name_version_absent = bool(same_name_ocr_conflict and not strong_drop_candidate)
    if special_layout:
        not_in_drop_confidence = ""
    elif same_name_version_absent:
        not_in_drop_confidence = "strong" if best_name_similarity >= 0.96 else "possible"
    elif full_ocr_numbers and not exact_full_available and not compatible_local_name_available and plausible_name_texts and best_name_similarity < 0.55 and japanese_artwork_score < 60:
        not_in_drop_confidence = "strong"
    elif full_ocr_numbers and not exact_full_available and not compatible_local_name_available and plausible_name_texts and best_name_similarity < 0.68 and japanese_artwork_score < 70:
        not_in_drop_confidence = "possible"
    if same_name_version_absent and status == "recognized":
        status = "review"

    same_name_debug = []
    if not_in_drop_confidence and plausible_name_texts:
        for candidate in candidates:
            name_similarity = max(
                (_similarity(text, str(candidate.get("name") or "")) for text in plausible_name_texts),
                default=0.0,
            )
            if name_similarity < 0.86:
                continue
            candidate_number = _normalize_card_number(candidate.get("number") or "")
            number_compatible = bool(
                candidate_number
                and (
                    candidate_number in full_ocr_numbers
                    or _number_local(candidate_number) in full_ocr_locals
                )
            )
            same_name_debug.append(
                {
                    "card_uid": candidate.get("card_uid"),
                    "name": candidate.get("name"),
                    "number": candidate.get("number"),
                    "set": candidate.get("set"),
                    "name_similarity": round(name_similarity, 3),
                    "number_compatible": number_compatible,
                    "rejection_reason": "numéro/set incompatible" if not number_compatible else "score global insuffisant",
                }
            )

    diagnostic_reason = "aucun signal OCR exploitable"
    if ocr_payload.get("number_texts") and not ocr_payload.get("name_texts"):
        diagnostic_reason = "nom OCR absent"
    elif ocr_payload.get("name_texts") and not ocr_payload.get("number_texts"):
        diagnostic_reason = "numéro OCR absent"
    elif best and status == "review" and margin < 12:
        diagnostic_reason = "scores candidats trop proches"
    elif best and status == "review":
        diagnostic_reason = "score insuffisant pour auto"
    elif best and status == "unrecognized":
        diagnostic_reason = "aucun candidat fiable"
    if v10_safety_reason:
        diagnostic_reason = v10_safety_reason
    if status != "recognized" and japanese_signal:
        diagnostic_reason = f"JP : {japanese_signal} — vérification requise"
    if status != "recognized" and not_in_drop_confidence:
        label = "forte confiance" if not_in_drop_confidence == "strong" else "possible"
        if same_name_version_absent:
            diagnostic_reason = f"même nom présent, version exacte absente du Drop ({label})"
        else:
            diagnostic_reason = f"carte absente du Drop {label}"
    elif same_name_ocr_conflict and strong_drop_candidate:
        diagnostic_reason = "numéro OCR incompatible avec la carte proposée"

    # Visual shortlists are also useful when every candidate has zero identity
    # evidence. Keep those rows for diagnostics, but never expose their first
    # row as a real proposal or infer a language/not-in-Drop state from it.
    proposal_reliable = bool(best and _safe_float(best.get("score"), 0.0) > 0.0)
    if not proposal_reliable:
        status = "unrecognized"
        diagnostic_reason = "aucun candidat fiable"
        japanese_signal = ""
        japanese_candidate = False
        not_in_drop_confidence = ""
        same_name_version_absent = False
        same_name_debug = []
        best_membership = {"in_drop": False, "method": ""}
        same_name_ocr_conflict = False
    return {
        "region": {"box": [0, 0, 1, 1], "source": "ocr"},
        "status": status,
        "method": "ocr_fr+visual_shortlist" if any(item.get("visual_score") is not None for item in top) else "ocr_fr",
        "score": best["score"] if best else 0.0,
        "second_score": second["score"] if second else 0.0,
        "margin": round(margin, 2),
        "diagnostic_reason": diagnostic_reason,
        "v8_auto_reason": v8_auto_reason,
        "v9_auto_reason": v9_auto_reason,
        "v10_safety_reason": v10_safety_reason,
        "v13_auto_reason": v13_auto_reason,
        "special_layout": special_layout,
        "v13_japanese_signal": japanese_signal,
        "v13_japanese_candidate": japanese_candidate,
        "v13_visual_jp_override": bool(best and best.get("v13_visual_jp_override")),
        "v14_7_jp_orb_override": bool(best and best.get("v14_7_jp_orb_override")),
        "v14_7_jp_orb_margin": int((best or {}).get("v14_7_jp_orb_margin") or 0),
        "v13_not_in_drop_confidence": not_in_drop_confidence,
        "v14_same_name_version_absent": same_name_version_absent,
        "v14_same_name_candidates": same_name_debug[:8],
        "v15_drop_membership": dict(best_membership),
        "v15_ocr_identity_conflict": same_name_ocr_conflict,
        "proposal_reliable": proposal_reliable,
        "proposal_reliability_version": PROPOSAL_RELIABILITY_VERSION,
        "visual_matching_used": visual_info.get("used", 0),
        "visual_matching_elapsed": visual_info.get("elapsed", 0.0),
        "visual_matching_broad": visual_info.get("broad", False),
        "ocr": ocr_payload,
        "candidates": top,
    }


def _orientation_match_rank(match: dict[str, Any]) -> tuple[float, float, float, float]:
    candidate_row = (match.get("candidates") or [{}])[0]
    exact_number = 1.0 if candidate_row.get("number_kind") == "full_collector" else 0.0
    name_similarity = _safe_float(candidate_row.get("name_similarity"), 0.0)
    return (
        exact_number,
        name_similarity,
        _safe_float(match.get("score"), 0.0),
        _safe_float(match.get("margin"), 0.0),
    )


def _layout_geometry(path: str) -> dict[str, Any]:
    image = _load_image(path, max_side=900)
    if image is None:
        return {"horizontal": False, "aspect": 0.0, "area_ratio": 0.0}
    regions = detect_card_regions(image, max_regions=1)
    region = regions[0] if regions else {}
    aspect = _safe_float(region.get("aspect"), 0.0)
    area_ratio = _safe_float(region.get("area_ratio"), 0.0)
    return {
        "horizontal": bool(aspect >= 1.18 and area_ratio >= 0.12),
        "aspect": round(aspect, 3),
        "area_ratio": round(area_ratio, 4),
    }


def match_front_photo_orientation_aware(
    path: str,
    candidates: list[dict[str, Any]],
    used_counts: dict[str, int] | None = None,
    *,
    back_type: str = "",
    ocr_payload_override: dict[str, Any] | None = None,
    layout_hint: str = "",
    family_hint: str = "",
) -> dict[str, Any]:
    """Try horizontal card orientations only for demonstrated special layouts."""
    if layout_hint == "V_UNION":
        base_ocr = ocr_payload_override or run_ocr_for_photo(path)
        ocr_payload_override = run_v_union_edge_ocr(path, base_payload=base_ocr)
    base = match_front_photo_ocr(
        path,
        candidates,
        used_counts,
        back_type=back_type,
        ocr_payload_override=ocr_payload_override,
        family_hint=family_hint,
    )
    title_text = _fold_text(" ".join((base.get("ocr") or {}).get("name_texts") or []))
    top_candidate = (((base.get("candidates") or [{}])[0]).get("candidate") or {})
    candidate_name = _fold_text(top_candidate.get("name") or "")
    geometry = _layout_geometry(path)
    text_legend = "legende" in title_text or "legend" in title_text
    candidate_legend = "legende" in candidate_name or "legend" in candidate_name
    is_v_union = layout_hint == "V_UNION" or "vunion" in candidate_name or "v union" in candidate_name
    # A weak OCR/candidate guess must never rotate a normal vertical card into a
    # LEGEND layout. Require compatible geometry and a second independent cue.
    forced_legend = layout_hint == "LEGEND_HALF"
    is_legend = bool(forced_legend or (geometry["horizontal"] and (text_legend or candidate_legend)))
    if not is_legend:
        base.setdefault("orientation_degrees", 0)
        if is_v_union:
            # V-UNION is a known multi-card layout, not a LEGEND/special-layout
            # warning. Keeping the types exclusive prevents stale LEGEND badges.
            base["layout_type"] = "V_UNION"
            base["special_layout"] = False
            base["v_union_layout"] = True
            edge_numbers = (base.get("ocr") or {}).get("v_union_edge_numbers") or []
            if edge_numbers:
                base["v_union_edge_numbers"] = edge_numbers
                base["v_union_ocr_reason"] = "numéro V-UNION lu sur un bord : " + ", ".join(edge_numbers)
        elif (text_legend or candidate_legend) and not geometry["horizontal"]:
            base.setdefault("layout_type", "standard")
            base["layout_review_reason"] = (
                "signal LEGEND écarté : rectangle de carte vertical "
                f"(ratio {geometry['aspect']:.2f})"
            )
            base["special_layout"] = False
        else:
            base.setdefault("layout_type", "standard")
        base["layout_geometry"] = geometry
        return base

    attempts = [(0, base)]
    for degrees in (90, 270):
        rotated_ocr = run_ocr_for_photo(path, orientation_degrees=degrees)
        attempt = match_front_photo_ocr(
            path,
            candidates,
            used_counts,
            back_type=back_type,
            ocr_payload_override=rotated_ocr,
            family_hint=family_hint,
        )
        attempts.append((degrees, attempt))
    degrees, selected = max(attempts, key=lambda item: _orientation_match_rank(item[1]))
    selected["orientation_degrees"] = degrees
    selected["layout_type"] = "LEGEND_HALF"
    selected["special_layout"] = True
    selected["layout_geometry"] = geometry
    selected["orientation_attempts"] = [
        {
            "orientation": orientation,
            "score": attempt.get("score", 0.0),
            "margin": attempt.get("margin", 0.0),
            "candidate": ((((attempt.get("candidates") or [{}])[0]).get("candidate") or {}).get("name") or ""),
        }
        for orientation, attempt in attempts
    ]
    selected["diagnostic_reason"] = (
        f"layout LEGEND_HALF · orientation retenue {degrees}° · "
        + str(selected.get("diagnostic_reason") or "vérification requise")
    )
    return selected


def _is_v_union_candidate(candidate: dict[str, Any]) -> bool:
    name = _fold_text(candidate.get("name") or "")
    return "vunion" in name or "v union" in name


def _is_legend_candidate(candidate: dict[str, Any]) -> bool:
    name = _fold_text(candidate.get("name") or "")
    return "legende" in name or "legend" in name


def _candidate_number_index(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        number = _normalize_card_number(candidate.get("number") or "")
        if number:
            index.setdefault(number, []).append(candidate)
    return index


def _v_union_series_index(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group V-UNION candidates by their real contiguous number series.

    A Pokémon can have several V-UNION releases with the same name.  The
    number series is therefore part of the family identity, not just its name.
    """
    buckets: dict[tuple[str, str, bool, str], list[tuple[int, dict[str, Any]]]] = {}
    unnumbered: dict[tuple[str, str, bool], list[dict[str, Any]]] = {}
    for candidate in candidates:
        if not _is_v_union_candidate(candidate):
            continue
        base = (
            _fold_text(candidate.get("name") or ""),
            _fold_text(candidate.get("set") or ""),
            bool(candidate.get("japanese")),
        )
        number = _normalize_card_number(candidate.get("number") or "")
        match = re.fullmatch(r"([A-Z]*)(\d+)", number)
        if not match:
            unnumbered.setdefault(base, []).append(candidate)
            continue
        prefix, value = match.groups()
        buckets.setdefault((*base, prefix), []).append((int(value), candidate))

    families = []
    for (*base, prefix), numbered in buckets.items():
        by_number: dict[int, list[dict[str, Any]]] = {}
        for value, candidate in numbered:
            by_number.setdefault(value, []).append(candidate)
        series: list[list[int]] = []
        for value in sorted(by_number):
            if not series or value - series[-1][-1] > 4:
                series.append([value])
            else:
                series[-1].append(value)
        for values in series:
            family_candidates = [
                candidate
                for value in values
                for candidate in by_number[value]
            ]
            numbers = sorted(
                {
                    _normalize_card_number(candidate.get("number") or "")
                    for candidate in family_candidates
                    if _normalize_card_number(candidate.get("number") or "")
                }
            )
            first = f"{prefix}{values[0]}"
            last = f"{prefix}{values[-1]}"
            label = str(family_candidates[0].get("name") or "V-UNION")
            families.append(
                {
                    "key": "|".join([*map(str, base), prefix, str(values[0]), str(values[-1])]),
                    "label": f"{label} · {first}–{last}",
                    "name_key": base[0],
                    "candidates": family_candidates,
                    "numbers": numbers,
                }
            )

    for base, family_candidates in unnumbered.items():
        matching = [family for family in families if family.get("name_key") == base[0]]
        if len(matching) == 1:
            matching[0]["candidates"].extend(family_candidates)
            matching[0]["numbers"] = sorted(
                {
                    _normalize_card_number(candidate.get("number") or "")
                    for candidate in matching[0]["candidates"]
                    if _normalize_card_number(candidate.get("number") or "")
                }
            )
        else:
            families.append(
                {
                    "key": "|".join([*map(str, base), "unnumbered"]),
                    "label": str(family_candidates[0].get("name") or "V-UNION"),
                    "name_key": base[0],
                    "candidates": family_candidates,
                    "numbers": [],
                }
            )
    return families


def _candidate_indexes(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "by_card_uid": {
            str(candidate.get("card_uid") or ""): candidate
            for candidate in candidates
            if str(candidate.get("card_uid") or "")
        },
        "by_number": _candidate_number_index(candidates),
        "v_union_families": _v_union_series_index(candidates),
    }


def _legend_family_for_group(
    matches: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    primary_ocr: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    """Select one LEGEND family without mixing ordinary cards into its halves."""
    families: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        if not _is_legend_candidate(candidate):
            continue
        key = (_fold_text(candidate.get("name") or ""), _fold_text(candidate.get("set") or ""))
        if key[0]:
            families.setdefault(key, []).append(candidate)
    if not families:
        return "", [], "aucune famille LÉGENDE dans le Drop"

    ocr_payloads = [match.get("ocr") or {} for match in matches]
    if primary_ocr:
        ocr_payloads.append(primary_ocr)
    observed_numbers = {
        _normalize_card_number(number)
        for ocr in ocr_payloads
        for number in (ocr.get("collector_number_texts") or [])
        if _normalize_card_number(number)
    }
    observed_names = [
        str(value)
        for ocr in ocr_payloads
        for value in ([*(ocr.get("name_texts") or []), str(ocr.get("raw_text") or "")])
        if str(value).strip()
    ]
    ranked = []
    for key, family_candidates in families.items():
        family_numbers = {
            _normalize_card_number(candidate.get("number") or "")
            for candidate in family_candidates
            if _normalize_card_number(candidate.get("number") or "")
        }
        exact_numbers = len(observed_numbers & family_numbers)
        label = str(family_candidates[0].get("name") or "LÉGENDE")
        name_score = max((_similarity(value, label) for value in observed_names), default=0.0)
        ranked.append((exact_numbers, name_score, key, family_candidates))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else (0, 0.0, ("", ""), [])
    if best[0] > second[0] and best[0] >= 1:
        reason = f"famille LÉGENDE confirmée par {best[0]} numéro(s) exact(s)"
    elif best[1] >= 0.78 and best[1] >= second[1] + 0.08:
        reason = f"famille LÉGENDE confirmée par le nom ({best[1]:.0%})"
    else:
        return "", [], "famille LÉGENDE ambiguë"
    return str(best[3][0].get("name") or "LÉGENDE"), list(best[3]), reason


def _candidate_index_debug(indexes: dict[str, Any]) -> dict[str, Any]:
    return {
        "numbers": {
            number: [
                {
                    "card_uid": candidate.get("card_uid", ""),
                    "name": candidate.get("name", ""),
                    "number": candidate.get("number", ""),
                    "set": candidate.get("set", ""),
                    "drop_card_key": candidate.get("drop_card_key", ""),
                    "identity_fingerprint": candidate.get("identity_fingerprint", ""),
                }
                for candidate in rows
            ]
            for number, rows in (indexes.get("by_number") or {}).items()
        },
        "v_union_families": [
            {
                "key": family.get("key", ""),
                "label": family.get("label", ""),
                "numbers": list(family.get("numbers") or []),
                "candidates": [
                    {
                        "card_uid": candidate.get("card_uid", ""),
                        "number": candidate.get("number", ""),
                        "set": candidate.get("set", ""),
                        "drop_card_key": candidate.get("drop_card_key", ""),
                    }
                    for candidate in family.get("candidates", [])
                ],
            }
            for family in indexes.get("v_union_families", [])
        ],
    }


def _ocr_with_v_union_edge_numbers(ocr: dict[str, Any] | None) -> dict[str, Any]:
    """Promote V-UNION edge numbers to the normal collector-number signal.

    V-UNION pieces put their reference on different borders.  OCR already
    discovers those values, but the generic scorer only reads the collector
    number fields.  Keeping the raw edge values and adding them to those
    fields lets the existing scorer prefer SWSH287 over another Morpeko
    V-UNION series without special-case card names.
    """
    payload = dict(ocr or {})
    edge_numbers = [
        str(value)
        for value in (payload.get("v_union_edge_numbers") or [])
        if _normalize_card_number(value)
    ]
    if not edge_numbers:
        return payload
    for field in ("number_texts", "collector_number_texts", "all_number_texts"):
        payload[field] = sorted({*map(str, payload.get(field) or []), *edge_numbers})
    return payload


def _v_union_family_for_group(
    matches: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    primary_ocr: dict[str, Any] | None = None,
    *,
    candidate_indexes: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    """Select a V-UNION family from group-level evidence, conservatively."""
    indexes = candidate_indexes or _candidate_indexes(candidates)
    families = list(indexes.get("v_union_families") or [])
    if not families:
        return "", [], "aucune famille V-UNION dans le Drop"
    observed_numbers = {
        _normalize_card_number(number)
        for match in matches
        for number in ((match.get("ocr") or {}).get("v_union_edge_numbers") or [])
        if _normalize_card_number(number)
    }
    primary_names = list((primary_ocr or {}).get("name_texts") or [])
    primary_raw = str((primary_ocr or {}).get("raw_text") or "")
    ranked = []
    for family in families:
        family_candidates = family.get("candidates") or []
        family_numbers = set(family.get("numbers") or [])
        exact_numbers = len(observed_numbers & family_numbers)
        top_votes = 0
        best_score = 0.0
        for match in matches:
            top = (((match.get("candidates") or [{}])[0]).get("candidate") or {})
            if any(
                str(top.get("card_uid") or "") == str(candidate.get("card_uid") or "")
                for candidate in family_candidates
            ):
                top_votes += 1
                best_score = max(best_score, _safe_float(match.get("score"), 0.0))
        label = str(family.get("label") or "")
        primary_name_score = max(
            [_similarity(value, label) for value in primary_names]
            + ([_similarity(primary_raw, label)] if primary_raw else [])
            + [0.0]
        )
        ranked.append((exact_numbers, primary_name_score, top_votes, best_score, str(family.get("key") or ""), family))
    ranked.sort(reverse=True)
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else (0, 0.0, 0, 0.0, "", {})
    if best[0] > second[0] and best[0] >= 1:
        reason = f"famille confirmée par {best[0]} numéro(s) de bord"
    elif len(families) == 1 and best[1] >= 0.72:
        reason = f"famille lue sur le recto commun ({best[1]:.0%})"
    elif best[2] >= 2 and best[2] > second[2]:
        reason = f"famille confirmée par {best[2]} sous-cartes"
    else:
        return "", [], "famille V-UNION ambiguë"
    family = best[5]
    return str(family.get("label") or ""), list(family.get("candidates") or []), reason


def _preserve_physical_match_identity(
    target: dict[str, Any],
    source: dict[str, Any],
    *,
    layout_type: str = "V_UNION",
) -> None:
    target["photo"] = source.get("photo")
    target["subcard_id"] = source.get("subcard_id")
    target["subcard_photos"] = source.get("subcard_photos") or {}
    target["physical_group_id"] = source.get("physical_group_id")
    target["physical_back_type"] = source.get("physical_back_type") or ""
    target["layout_type"] = layout_type
    target["special_layout"] = layout_type == "LEGEND_HALF"
    target["v_union_layout"] = layout_type == "V_UNION"


def _apply_v13_group_language_diagnostic(group: dict[str, Any]) -> None:
    back = group.get("group_back") or {}
    classification = back.get("classification") or {}
    raw_class = str(classification.get("class") or "")
    western_score = _safe_float(classification.get("western_back_score"), 0.0)
    japanese_score = _safe_float(classification.get("japanese_back_score"), 0.0)
    matches = group.get("matches") or []
    top_candidates = [proposed_candidate(match) or {} for match in matches]
    has_japanese_top_candidate = any(candidate.get("japanese") for candidate in top_candidates)
    has_japanese_signal = any(match.get("v13_japanese_signal") for match in matches)

    back_type = "back_unknown"
    reason = "signal verso insuffisant"
    if raw_class == "back_japanese" and has_japanese_top_candidate:
        back_type = "back_japanese"
        reason = "structure verso JP + candidat JAP cohérent"
    elif raw_class == "back_japanese":
        reason = "détecteur verso JP contredit par le candidat FR"
    elif has_japanese_signal:
        back_type = "back_japanese_candidate"
        reason = "candidat JAP soutenu par numéro/artwork; verso non conclusif"
    elif raw_class == "back_western" or western_score >= 0.50:
        back_type = "back_western"
        reason = "structure verso occidental"

    group["v13_back_type"] = back_type
    group["v13_back_reason"] = reason
    group["v13_back_scores"] = {"western": round(western_score, 3), "japanese": round(japanese_score, 3)}
    group["v13_japanese_candidate"] = has_japanese_signal or back_type == "back_japanese"
    group["v13_japanese_top_candidate"] = has_japanese_top_candidate
    group["v13_language_conflict"] = (
        "back JP + candidat FR"
        if raw_class == "back_japanese" and not has_japanese_top_candidate
        else "back western + candidat JAP"
        if (raw_class == "back_western" or western_score >= 0.56) and has_japanese_signal
        else ""
    )


def match_front_photo(path: str, regions: list[dict[str, Any]], candidates: list[dict[str, Any]], reference_features: dict[str, dict[str, Any]]):
    image = _load_image(path, max_side=1024)
    if image is None or not reference_features:
        return []
    usable_regions = regions[:4] or [{"box": [0.12, 0.08, 0.88, 0.92], "area_ratio": 0.65, "aspect": 0.7}]
    candidate_by_key = {candidate["drop_card_key"]: candidate for candidate in candidates}
    matched_regions = []
    for region in usable_regions:
        crop = _crop_region(image, region)
        photo_feature = _feature(crop)
        scored = []
        for key, ref_feature in reference_features.items():
            distance = _feature_distance(photo_feature, ref_feature)
            scored.append((distance, key))
        scored.sort(key=lambda item: item[0])
        top = []
        for distance, key in scored[:3]:
            candidate = candidate_by_key.get(key)
            if not candidate:
                continue
            confidence = max(0.0, min(1.0, 1.0 - distance * 1.8))
            top.append({"candidate": candidate, "score": round(confidence, 3), "distance": round(distance, 4)})
        if not top:
            status = "unrecognized"
        elif top[0]["score"] >= 0.72 and (len(top) == 1 or top[0]["score"] - top[1]["score"] >= 0.08):
            status = "recognized"
        elif top[0]["score"] >= 0.52:
            status = "review"
        else:
            status = "unrecognized"
        matched_regions.append({"region": region, "status": status, "method": "visual", "candidates": top})
    return matched_regions


def _is_back_class(classification: dict[str, Any]) -> bool:
    return str(classification.get("class") or "").startswith("back")


def _is_backish_for_grouping(classification: dict[str, Any]) -> bool:
    if _is_back_class(classification):
        return True
    return _safe_float(classification.get("western_back_score"), 0.0) >= 0.50


def _is_sequence_back_candidate(classification: dict[str, Any]) -> bool:
    if _is_backish_for_grouping(classification):
        return True
    western_score = _safe_float(classification.get("western_back_score"), 0.0)
    japanese_score = _safe_float(classification.get("japanese_back_score"), 0.0)
    return western_score >= 0.42 or japanese_score >= 0.72


def _entry_for_photo(photo: PhotoInfo, classifications: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"photo": photo, "classification": classifications.get(photo.filename, {})}


def _entry_as_sequence_back(entry: dict[str, Any]) -> dict[str, Any]:
    classification = dict(entry.get("classification") or {})
    if _is_back_class(classification):
        return entry
    back_type = "japanese" if _safe_float(classification.get("japanese_back_score"), 0.0) >= 0.72 else "western"
    classification["back_type"] = back_type
    classification["sequence_inferred_back"] = True
    return {**entry, "classification": classification}


def _new_group(index: int, entry: dict[str, Any]) -> dict[str, Any]:
    classification = entry.get("classification") or {}
    expected_cards = max(1, min(12, _safe_int(classification.get("card_count_hint"), 1)))
    return {
        "announcement_index": index,
        "photos": [entry],
        "primary_front": entry,
        "group_back": None,
        "detail_cards": [],
        "expected_cards": expected_cards,
        "grouping_status": "ok" if expected_cards == 1 else "review",
        "grouping_reasons": [] if expected_cards == 1 else [f"photo principale multi-cartes probable x{expected_cards}"],
    }


def _group_capture_indices(group: dict[str, Any]) -> list[int]:
    indices = []
    for entry in group.get("photos", []) or []:
        photo = entry.get("photo")
        if photo is not None:
            indices.append(_safe_int(getattr(photo, "capture_index", 0), 0))
    return [idx for idx in indices if idx > 0]


def _single_group_entry(group: dict[str, Any]) -> dict[str, Any] | None:
    photos = group.get("photos", []) or []
    if len(photos) != 1:
        return None
    return photos[0]


def _largest_region_ratio(classification: dict[str, Any]) -> float:
    regions = classification.get("regions") or []
    return max((_safe_float(region.get("area_ratio"), 0.0) for region in regions), default=0.0)


def _is_probable_single_front(classification: dict[str, Any]) -> bool:
    if _is_back_class(classification):
        return False
    klass = str(classification.get("class") or "")
    largest = _largest_region_ratio(classification)
    if klass == "primary_front":
        return True
    return largest >= 0.12 and _safe_float(classification.get("western_back_score"), 0.0) < 0.50


def _v11_single_back_signal(classification: dict[str, Any]) -> tuple[bool, str, bool]:
    if _is_back_class(classification):
        return True, "verso détecté V10", False
    if _is_sequence_back_candidate(classification):
        return True, "verso inféré V10 par séquence", True
    western_score = _safe_float(classification.get("western_back_score"), 0.0)
    japanese_score = _safe_float(classification.get("japanese_back_score"), 0.0)
    if western_score >= 0.30:
        return True, f"verso occidental sous-seuil V11 ({western_score:.2f})", True
    if japanese_score >= 0.62:
        return True, f"verso japonais sous-seuil V11 ({japanese_score:.2f})", True
    return False, f"score verso insuffisant (west {western_score:.2f}, jp {japanese_score:.2f})", False


def _reindex_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, group in enumerate(groups, start=1):
        group["announcement_index"] = index
    return groups


def _reconcile_consecutive_single_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reconciled = []
    index = 0
    while index < len(groups):
        group = groups[index]
        entry = _single_group_entry(group)
        next_group = groups[index + 1] if index + 1 < len(groups) else None
        next_entry = _single_group_entry(next_group) if next_group is not None else None
        if entry is None or next_entry is None:
            reconciled.append(group)
            index += 1
            continue

        photo = entry.get("photo")
        next_photo = next_entry.get("photo")
        current_idx = _safe_int(getattr(photo, "capture_index", 0), 0)
        next_idx = _safe_int(getattr(next_photo, "capture_index", 0), 0)
        front_classification = entry.get("classification") or {}
        back_classification = next_entry.get("classification") or {}
        is_consecutive = current_idx > 0 and next_idx == current_idx + 1
        front_ok = _is_probable_single_front(front_classification)
        back_ok, back_reason, inferred = _v11_single_back_signal(back_classification)

        if is_consecutive and front_ok and back_ok:
            back_entry = _entry_as_sequence_back(next_entry) if inferred else next_entry
            grouping_status = "ok"
            grouping_reasons = [
                "fusion V11 de deux groupes single consécutifs",
                back_reason,
            ]
            if inferred:
                grouping_status = "review"
                grouping_reasons.append("verso accepté par cohérence de séquence")
            merged = {
                "announcement_index": len(reconciled) + 1,
                "photos": [entry, back_entry],
                "primary_front": entry,
                "group_back": back_entry,
                "detail_cards": [],
                "expected_cards": 1,
                "grouping_status": grouping_status,
                "grouping_reasons": grouping_reasons,
                "v11_single_fusion": True,
                "v11_fusion_from": [_group_capture_indices(group), _group_capture_indices(next_group)],
                "v11_fusion_reason": back_reason,
            }
            reconciled.append(merged)
            index += 2
            continue

        if entry is not None:
            group.setdefault("v11_single_unmerged_reason", []).append(
                "single non fusionné: "
                + (
                    "non consécutif"
                    if not is_consecutive
                    else "première photo pas assez front-like"
                    if not front_ok
                    else back_reason
                )
            )
        reconciled.append(group)
        index += 1

    return _reindex_groups(reconciled)


def _capture_gap_seconds(left: PhotoInfo | None, right: PhotoInfo | None) -> float | None:
    if left is None or right is None:
        return None
    try:
        return max(
            0.0,
            (datetime.fromisoformat(right.capture_datetime) - datetime.fromisoformat(left.capture_datetime)).total_seconds(),
        )
    except (TypeError, ValueError):
        return None


def _v12_raw_back_score(classification: dict[str, Any]) -> float:
    return max(
        _safe_float(classification.get("western_back_score"), 0.0),
        _safe_float(classification.get("japanese_back_score"), 0.0),
    )


def _v12_single_role(classification: dict[str, Any]) -> str:
    klass = str(classification.get("class") or "")
    if klass == "back_japanese":
        return "back_japanese"
    if klass == "back_western":
        return "back_western"
    if _safe_float(classification.get("japanese_back_score"), 0.0) >= 0.62:
        return "back_japanese_candidate"
    if _safe_float(classification.get("western_back_score"), 0.0) >= 0.50:
        return "back_western_candidate"
    if klass == "primary_front":
        return "front"
    return "unknown"


def _v12_pair_score(
    entries: list[dict[str, Any]],
    index: int,
) -> tuple[float, list[str]]:
    front_entry = entries[index]
    back_entry = entries[index + 1]
    front_photo = front_entry.get("photo")
    back_photo = back_entry.get("photo")
    front_classification = front_entry.get("classification") or {}
    back_classification = back_entry.get("classification") or {}
    gap = _capture_gap_seconds(front_photo, back_photo)
    score = 0.0
    reasons = []

    if gap is None:
        score -= 0.5
        reasons.append("gap temporel indisponible")
    elif gap <= 12:
        score += 3.2
        reasons.append(f"captures rapprochées ({gap:.0f}s)")
    elif gap <= 20:
        score += 2.0
        reasons.append(f"captures proches ({gap:.0f}s)")
    elif gap <= 35:
        score += 0.8
        reasons.append(f"captures compatibles ({gap:.0f}s)")
    elif gap <= 60:
        score -= 1.0
        reasons.append(f"pause dans la paire ({gap:.0f}s)")
    else:
        score -= 3.0
        reasons.append(f"longue pause dans la paire ({gap:.0f}s)")

    back_is_detected = _is_back_class(back_classification)
    back_score = _v12_raw_back_score(back_classification)
    if back_is_detected:
        score += 3.2
        reasons.append("verso détecté")
    elif back_score >= 0.25:
        score += 1.0
        reasons.append(f"verso sous-seuil plausible ({back_score:.2f})")
    elif back_score >= 0.12:
        score += 0.3
        reasons.append(f"verso faible mais compatible ({back_score:.2f})")
    else:
        score -= 1.5
        reasons.append(f"peu de signal verso ({back_score:.2f})")

    front_is_detected_back = _is_back_class(front_classification)
    front_back_score = _v12_raw_back_score(front_classification)
    if not front_is_detected_back:
        score += 1.3
        reasons.append("première photo front-like")
    elif back_score >= front_back_score + 0.02:
        score += 0.4
        reasons.append("première photo réinterprétée comme recto")
    else:
        score -= 3.0
        reasons.append("première photo fortement back-like")

    previous_photo = entries[index - 1].get("photo") if index > 0 else None
    next_photo = entries[index + 2].get("photo") if index + 2 < len(entries) else None
    previous_gap = _capture_gap_seconds(previous_photo, front_photo)
    next_gap = _capture_gap_seconds(back_photo, next_photo)
    if gap is not None and next_gap is not None:
        if next_gap >= gap + 5:
            score += 0.8
            reasons.append("rupture temporelle après la paire")
        elif next_gap + 5 < gap:
            score -= 0.8
            reasons.append("paire suivante temporellement plus probable")
    if gap is not None and previous_gap is not None and previous_gap >= gap + 5:
        score += 0.4
        reasons.append("rupture temporelle avant la paire")
    return score, reasons


def _v12_optimize_simple_entries(entries: list[dict[str, Any]]) -> list[tuple[int, int, float, list[str]]]:
    if not entries:
        return []
    single_penalty = 2.4
    count = len(entries)
    scores = [-math.inf] * (count + 1)
    paths: list[tuple[int, int, float, list[str]] | None] = [None] * (count + 1)
    scores[0] = 0.0
    for index in range(count):
        single_score = scores[index] - single_penalty
        if single_score > scores[index + 1]:
            scores[index + 1] = single_score
            paths[index + 1] = (index, 1, -single_penalty, ["groupe incomplet pénalisé"])
        if index + 1 >= count:
            continue
        pair_score, pair_reasons = _v12_pair_score(entries, index)
        if scores[index] + pair_score > scores[index + 2]:
            scores[index + 2] = scores[index] + pair_score
            paths[index + 2] = (index, 2, pair_score, pair_reasons)

    segments = []
    cursor = count
    while cursor > 0:
        choice = paths[cursor]
        if choice is None:
            choice = (cursor - 1, 1, -single_penalty, ["séquence non résolue"])
        start, size, segment_score, reasons = choice
        segments.append((start, size, segment_score, reasons))
        cursor = start
    return list(reversed(segments))


def _v12_baseline_single_patterns(groups: list[dict[str, Any]]) -> dict[str, int]:
    patterns: dict[str, int] = {}
    for index, group in enumerate(groups):
        entry = _single_group_entry(group)
        if entry is None:
            continue
        previous = groups[index - 1] if index > 0 else None
        following = groups[index + 1] if index + 1 < len(groups) else None
        previous_single = _single_group_entry(previous) if previous else None
        following_single = _single_group_entry(following) if following else None
        role = _v12_single_role(entry.get("classification") or {})
        if previous_single and following_single:
            label = "chaîne de singles"
        elif following_single and role == "front":
            label = "front single → single suivant"
        elif following_single and role.startswith("back"):
            label = "back single → single suivant"
        elif previous_single and role == "front":
            label = "single précédent → front single"
        elif previous_single and role.startswith("back"):
            label = "single précédent → back single"
        elif previous is not None and following is not None:
            label = "single isolé entre groupes normaux"
        elif role.startswith("back"):
            label = "verso isolé en bord de séquence"
        else:
            label = "recto isolé en bord de séquence"
        patterns[label] = patterns.get(label, 0) + 1
    return patterns


def _v12_baseline_single_map(
    baseline_groups: list[dict[str, Any]],
    reconciled_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    final_group_by_capture = {
        capture_index: group
        for group in reconciled_groups
        for capture_index in _group_capture_indices(group)
    }
    rows = []
    for group_index, group in enumerate(baseline_groups):
        entry = _single_group_entry(group)
        if entry is None:
            continue
        photo = entry.get("photo")
        classification = entry.get("classification") or {}
        capture_index = _safe_int(getattr(photo, "capture_index", 0), 0)
        previous = baseline_groups[group_index - 1] if group_index > 0 else None
        following = baseline_groups[group_index + 1] if group_index + 1 < len(baseline_groups) else None
        previous_indices = _group_capture_indices(previous) if previous else []
        following_indices = _group_capture_indices(following) if following else []
        previous_photo = (previous.get("photos") or [{}])[-1].get("photo") if previous else None
        following_photo = (following.get("photos") or [{}])[0].get("photo") if following else None
        final_group = final_group_by_capture.get(capture_index) or {}
        final_size = len(final_group.get("photos", []) or [])
        if final_group.get("v12_recovered_multi"):
            attachment = "multi-cartes récupéré"
        elif final_size == 2:
            final_indices = _group_capture_indices(final_group)
            attachment = "suivant" if final_indices and final_indices[0] == capture_index else "précédent"
        elif final_size == 1:
            attachment = "aucune"
        else:
            attachment = "séquence restructurée"
        rows.append(
            {
                "capture_index": capture_index,
                "estimated_role": _v12_single_role(classification),
                "western_back_score": round(_safe_float(classification.get("western_back_score"), 0.0), 3),
                "japanese_back_score": round(_safe_float(classification.get("japanese_back_score"), 0.0), 3),
                "previous_group": previous_indices,
                "next_group": following_indices,
                "gap_previous_seconds": _capture_gap_seconds(previous_photo, photo),
                "gap_next_seconds": _capture_gap_seconds(photo, following_photo),
                "v11_reason": " · ".join(group.get("grouping_reasons") or group.get("v11_single_unmerged_reason") or []),
                "v12_attachment": attachment,
                "v12_group": _group_capture_indices(final_group),
            }
        )
    return rows


def _v12_previous_layout(groups: list[dict[str, Any]], capture_indices: set[int]) -> list[list[int]]:
    layout = []
    for group in groups:
        indices = _group_capture_indices(group)
        if capture_indices.intersection(indices):
            layout.append(indices)
    return layout


def _v12_pair_group(
    entries: list[dict[str, Any]],
    start: int,
    score: float,
    reasons: list[str],
    baseline_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    front_entry = entries[start]
    raw_back_entry = entries[start + 1]
    raw_back_classification = raw_back_entry.get("classification") or {}
    inferred = not _is_back_class(raw_back_classification)
    back_entry = _entry_as_sequence_back(raw_back_entry) if inferred else raw_back_entry
    front_photo = front_entry.get("photo")
    back_photo = back_entry.get("photo")
    indices = {
        _safe_int(getattr(front_photo, "capture_index", 0), 0),
        _safe_int(getattr(back_photo, "capture_index", 0), 0),
    }
    previous_layout = _v12_previous_layout(baseline_groups, indices)
    changed = previous_layout != [sorted(indices)]
    grouping_status = "ok" if score >= 4.0 else "review"
    grouping_reasons = ["segmentation V12 front/back", *reasons]
    if inferred:
        japanese_score = _safe_float(raw_back_classification.get("japanese_back_score"), 0.0)
        western_score = _safe_float(raw_back_classification.get("western_back_score"), 0.0)
        back_entry["classification"]["v12_back_role"] = (
            "back_japanese_candidate" if japanese_score >= 0.55 and western_score < 0.50 else "back_candidate"
        )
        grouping_reasons.append("verso rattaché par cohérence séquentielle")
    if _is_back_class(front_entry.get("classification") or {}):
        grouping_reasons.append("faux back probable sur le recto")
    if grouping_status == "review":
        grouping_reasons.append("confiance de segmentation insuffisante pour validation automatique")
    return {
        "announcement_index": 0,
        "photos": [front_entry, back_entry],
        "primary_front": front_entry,
        "group_back": back_entry,
        "detail_cards": [],
        "expected_cards": 1,
        "grouping_status": grouping_status,
        "grouping_reasons": grouping_reasons,
        "v12_sequence_pair": True,
        "v12_changed": changed,
        "v12_pair_score": round(score, 3),
        "v12_previous_layout": previous_layout,
    }


def _v12_single_group(entry: dict[str, Any], baseline_groups: list[dict[str, Any]]) -> dict[str, Any]:
    photo = entry.get("photo")
    classification = entry.get("classification") or {}
    role = _v12_single_role(classification)
    index = _safe_int(getattr(photo, "capture_index", 0), 0)
    if role.startswith("back"):
        reason_code = "missing_front"
        reason = "verso isolé : recto manquant ou séquence ambiguë"
        primary_front = None
        group_back = entry
    elif role == "front":
        reason_code = "missing_back"
        reason = "recto isolé : verso manquant probable"
        primary_front = entry
        group_back = None
    else:
        reason_code = "ambiguous_sequence"
        reason = "photo isolée : rôle front/back indéterminé"
        primary_front = entry
        group_back = None
    return {
        "announcement_index": 0,
        "photos": [entry],
        "primary_front": primary_front,
        "group_back": group_back,
        "detail_cards": [],
        "expected_cards": 1,
        "grouping_status": "review",
        "grouping_reasons": [reason],
        "v12_single_reason": reason_code,
        "v12_single_role": role,
        "v12_changed": True,
        "v12_previous_layout": _v12_previous_layout(baseline_groups, {index}),
    }


def _v12_combined_primary_signal(entry: dict[str, Any]) -> tuple[bool, float]:
    """Detect a central card boundary only for a pending multi-card pattern."""
    photo = entry.get("photo")
    if photo is None:
        return False, 0.0
    image = _load_image(photo.path, max_side=768)
    if image is None:
        return False, 0.0
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    height, width = gray.shape
    if height < 160 or width < 120:
        return False, 0.0
    inner = gray[:, int(width * 0.10) : int(width * 0.90)]
    vertical_edges = np.abs(np.diff(inner.astype(np.int16), axis=0))
    best_fraction = 0.0
    for row in range(int(height * 0.42), int(height * 0.58)):
        edge_row = vertical_edges[row]
        strong_fraction = float(np.mean(edge_row >= 24))
        mean_edge = float(np.mean(edge_row))
        if mean_edge >= 16.0:
            best_fraction = max(best_fraction, strong_fraction)
    return best_fraction >= 0.34, best_fraction


def _v14_primary_card_count(entry: dict[str, Any]) -> tuple[int, str]:
    """Estimate N for a `primary + N x (front/back)` sequence.

    The normal detector remains authoritative when it finds several regions.
    A narrow dark gutter projection covers the real three-card horizontal case
    where two adjacent cards were previously merged into one region.
    """
    classification = entry.get("classification") or {}
    detected = max(1, _safe_int(classification.get("card_count_hint"), 1))
    photo = entry.get("photo")
    if photo is None:
        return detected, "détecteur de zones"
    image = _load_image(photo.path, max_side=768)
    if image is None:
        return detected, "détecteur de zones"

    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    height, width = gray.shape
    central = gray[int(height * 0.10) : int(height * 0.90)]
    column_profile = np.mean(central, axis=0)
    gutters = []
    min_distance = max(18, int(width * 0.12))
    for column in range(int(width * 0.14), int(width * 0.86)):
        left = max(0, column - max(3, int(width * 0.012)))
        right = min(width, column + max(4, int(width * 0.012)) + 1)
        if column_profile[column] > 58 or column_profile[column] != np.min(column_profile[left:right]):
            continue
        if gutters and column - gutters[-1] < min_distance:
            if column_profile[column] < column_profile[gutters[-1]]:
                gutters[-1] = column
            continue
        gutters.append(column)
    projected = len(gutters) + 1 if gutters else 1
    if projected >= 2:
        detected = max(detected, min(12, projected))
        return detected, f"projection des séparations ({projected} cartes)"

    has_horizontal_boundary, _score = _v12_combined_primary_signal(entry)
    if has_horizontal_boundary:
        return max(detected, 2), "séparation horizontale de deux demi-cartes"
    return detected, "détecteur de zones"


def _recover_v12_multi_groups(
    groups: list[dict[str, Any]],
    baseline_groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Recover generic `primary + N x (front/back)` blocks."""
    recovered = []
    recovered_count = 0
    index = 0
    while index < len(groups):
        current = groups[index]
        current_photos = current.get("photos", []) or []
        existing_cards = max(0, len(current.get("detail_cards") or []))
        existing_is_multi = existing_cards > 0 and len(current_photos) == 1 + existing_cards * 2
        if len(current_photos) != 1 and not existing_is_multi:
            recovered.append(current)
            index += 1
            continue
        primary_entry = current.get("primary_front") or (current_photos[0] if current_photos else None)
        detected_cards, count_reason = _v14_primary_card_count(primary_entry) if primary_entry else (1, "")
        cards_to_attach = detected_cards - existing_cards if existing_is_multi else detected_cards
        following = groups[index + 1 : index + 1 + max(0, cards_to_attach)]
        can_test = (
            detected_cards > 1
            and cards_to_attach > 0
            and (len(current_photos) == 1 or existing_is_multi)
            and current.get("primary_front") is not None
            and len(following) == cards_to_attach
            and all(len(group.get("photos", []) or []) == 2 for group in following)
            and all(not group.get("v12_anchor") for group in following)
            and all(group.get("primary_front") is not None and group.get("group_back") is not None for group in following)
            and all(_safe_float(group.get("v12_pair_score"), 0.0) >= 4.0 for group in following)
        )
        if can_test:
            combined_entries = [entry for group in [current, *following] for entry in group.get("photos", []) or []]
            capture_indices = [entry["photo"].capture_index for entry in combined_entries]
            expected_photo_count = 1 + detected_cards * 2
            consecutive = capture_indices == list(range(capture_indices[0], capture_indices[0] + expected_photo_count))
            gap = _capture_gap_seconds(current_photos[-1].get("photo"), following[0]["photos"][0].get("photo"))
            has_boundary, boundary_score = _v12_combined_primary_signal(current_photos[0])
            primary_is_multi = detected_cards > 2 or has_boundary or _safe_int((current_photos[0].get("classification") or {}).get("card_count_hint"), 1) > 1
            if consecutive and (gap is None or gap <= 75) and primary_is_multi:
                previous_layout = _v12_previous_layout(baseline_groups, set(capture_indices))
                existing_details = list(current.get("detail_cards") or [])
                recovered.append(
                    {
                        "announcement_index": 0,
                        "photos": combined_entries,
                        "primary_front": current_photos[0],
                        "group_back": None,
                        "detail_cards": existing_details + [
                            {"front": group["primary_front"], "back": group["group_back"]}
                            for group in following
                        ],
                        "expected_cards": detected_cards,
                        "grouping_status": "review",
                        "grouping_reasons": [
                            f"multi-cartes V14 récupéré : primary + {detected_cards}×(front/back)",
                            count_reason,
                            f"signal de séparation du recto commun ({boundary_score:.0%})",
                            "validation prudente requise pour le bloc multi-cartes",
                        ],
                        "v12_recovered_multi": True,
                        "v14_generic_multi": True,
                        "v12_changed": True,
                        "v12_previous_layout": previous_layout,
                    }
                )
                recovered_count += 1
                index += 1 + cards_to_attach
                continue
        recovered.append(current)
        index += 1
    return recovered, recovered_count


def _reconcile_v12_sequence(
    baseline_groups: list[dict[str, Any]],
    classifications: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline_summary = {
        "groups": len(baseline_groups),
        "singles": sum(1 for group in baseline_groups if len(group.get("photos", []) or []) == 1),
        "reviews": sum(1 for group in baseline_groups if group.get("grouping_status") == "review"),
        "single_patterns": _v12_baseline_single_patterns(baseline_groups),
    }
    ordered_photos = sorted(
        {
            entry["photo"].capture_index: entry["photo"]
            for group in baseline_groups
            for entry in group.get("photos", []) or []
            if entry.get("photo") is not None
        }.values(),
        key=lambda photo: photo.capture_index,
    )
    ordered_entries = [_entry_for_photo(photo, classifications) for photo in ordered_photos]
    entry_by_index = {entry["photo"].capture_index: entry for entry in ordered_entries}
    anchors = {}
    for group in baseline_groups:
        indices = _group_capture_indices(group)
        expected_cards = max(1, _safe_int(group.get("expected_cards"), 1))
        if expected_cards > 1 and len(indices) == 1 + expected_cards * 2:
            anchors[indices[0]] = (indices[-1], group)

    reconciled = []
    interval_entries = []

    def flush_interval():
        if not interval_entries:
            return
        for start, size, score, reasons in _v12_optimize_simple_entries(interval_entries):
            if size == 2:
                reconciled.append(_v12_pair_group(interval_entries, start, score, reasons, baseline_groups))
            else:
                reconciled.append(_v12_single_group(interval_entries[start], baseline_groups))
        interval_entries.clear()

    cursor = ordered_photos[0].capture_index if ordered_photos else 1
    last_capture = ordered_photos[-1].capture_index if ordered_photos else 0
    while cursor <= last_capture:
        anchor = anchors.get(cursor)
        if anchor:
            flush_interval()
            anchor_end, anchor_group = anchor
            preserved = dict(anchor_group)
            preserved["v12_anchor"] = True
            preserved["v12_changed"] = False
            preserved["v12_previous_layout"] = [_group_capture_indices(anchor_group)]
            reconciled.append(preserved)
            cursor = anchor_end + 1
            continue
        entry = entry_by_index.get(cursor)
        if entry is not None:
            interval_entries.append(entry)
        cursor += 1
    flush_interval()
    reconciled, recovered_multi_groups = _recover_v12_multi_groups(reconciled, baseline_groups)
    _reindex_groups(reconciled)

    final_indices = [
        _safe_int(getattr(entry.get("photo"), "capture_index", 0), 0)
        for group in reconciled
        for entry in group.get("photos", []) or []
    ]
    baseline_single_indices = {
        _group_capture_indices(group)[0]
        for group in baseline_groups
        if len(_group_capture_indices(group)) == 1
    }
    repaired_single_indices = {
        index
        for group in reconciled
        if len(group.get("photos", []) or []) > 1
        for index in _group_capture_indices(group)
        if index in baseline_single_indices
    }
    summary = {
        **baseline_summary,
        "repaired_single_photos": len(repaired_single_indices),
        "recovered_multi_groups": recovered_multi_groups,
        "single_map": _v12_baseline_single_map(baseline_groups, reconciled),
        "photos_lost": max(0, len(ordered_photos) - len(set(final_indices))),
        "photos_duplicated": max(0, len(final_indices) - len(set(final_indices))),
    }
    if reconciled:
        reconciled[0]["_v12_summary"] = summary
    return reconciled


def _close_group(groups: list[dict[str, Any]], current: dict[str, Any] | None):
    if current is None:
        return
    if current.get("group_back") is not None and not current.get("detail_cards") and _safe_int(current.get("expected_cards"), 1) > 1:
        current["grouping_status"] = "review"
        current.setdefault("grouping_reasons", []).append("multi-cartes sans rectos individuels à reconnaître")
    if current.get("group_back") is None and not current.get("detail_cards"):
        current["grouping_status"] = "review"
        current.setdefault("grouping_reasons", []).append("aucun verso rattaché")
    groups.append(current)


def build_groups(photos: list[PhotoInfo], classifications: dict[str, dict[str, Any]], *, target_announcements=30):
    groups = []
    current = None
    for photo in photos:
        entry = _entry_for_photo(photo, classifications)
        result = entry["classification"]
        backish = _is_backish_for_grouping(result)
        if current is None:
            if _is_back_class(result):
                current = {
                    "announcement_index": len(groups) + 1,
                    "photos": [entry],
                    "primary_front": None,
                    "group_back": entry,
                    "detail_cards": [],
                    "expected_cards": 1,
                    "grouping_status": "review",
                    "grouping_reasons": ["verso orphelin en début de séquence"],
                }
                _close_group(groups, current)
                current = None
                continue
            current = _new_group(len(groups) + 1, entry)
            continue

        expected_cards = max(1, _safe_int(current.get("expected_cards"), 1))
        detail_cards = current.setdefault("detail_cards", [])
        sequence_inferred_back = False
        if not backish and not detail_cards and _is_sequence_back_candidate(result):
            entry = _entry_as_sequence_back(entry)
            result = entry["classification"]
            backish = True
            sequence_inferred_back = True
            current["grouping_status"] = "review"
            current.setdefault("grouping_reasons", []).append("verso inféré par cohérence front/back")
        elif not backish and detail_cards:
            open_detail = next((detail for detail in reversed(detail_cards) if not detail.get("back")), None)
            if open_detail is not None and _is_sequence_back_candidate(result):
                entry = _entry_as_sequence_back(entry)
                result = entry["classification"]
                backish = True
                sequence_inferred_back = True
                current["grouping_status"] = "review"
                current.setdefault("grouping_reasons", []).append("verso de détail inféré par cohérence front/back")
        if backish:
            current["photos"].append(entry)
            if sequence_inferred_back:
                entry["classification"]["sequence_inferred_back"] = True
            if detail_cards:
                open_detail = next((detail for detail in reversed(detail_cards) if not detail.get("back")), None)
                if open_detail is not None:
                    open_detail["back"] = entry
                else:
                    detail_cards.append({"front": None, "back": entry})
                    current["grouping_status"] = "review"
                    current.setdefault("grouping_reasons", []).append("verso de détail sans recto individuel")
                completed = sum(1 for detail in detail_cards if detail.get("front") and detail.get("back"))
                if completed >= expected_cards:
                    _close_group(groups, current)
                    current = None
            else:
                current["group_back"] = entry
                _close_group(groups, current)
                current = None
            if len(groups) >= target_announcements:
                break
            continue

        if expected_cards > 1:
            current["photos"].append(entry)
            detail_cards.append({"front": entry, "back": None})
            current["grouping_status"] = "review"
            current.setdefault("grouping_reasons", []).append("recto individuel rattaché au multi-cartes")
            continue

        current["grouping_status"] = "review"
        current.setdefault("grouping_reasons", []).append("nouveau recto avant verso attendu")
        _close_group(groups, current)
        if len(groups) >= target_announcements:
            current = None
            break
        current = _new_group(len(groups) + 1, entry)
    if current is not None and len(groups) < target_announcements:
        _close_group(groups, current)
    v11_groups = _reconcile_consecutive_single_groups(groups[:target_announcements])
    return _reconcile_v12_sequence(v11_groups, classifications)


def _recognize_groups(
    groups: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    force_grouping_trust=False,
    cached_ocr_by_path: dict[str, dict[str, Any]] | None = None,
    candidate_indexes: dict[str, Any] | None = None,
    initial_used_candidate_counts: dict[str, int] | None = None,
) -> tuple[bool, str, int]:
    ocr_available, ocr_note = _ocr_status()
    reference_features = {} if ocr_available else build_reference_features(candidates)
    candidate_indexes = candidate_indexes or _candidate_indexes(candidates)
    candidate_numbers = set((candidate_indexes.get("by_number") or {}).keys())
    used_candidate_counts = dict(initial_used_candidate_counts or {})
    for group in groups:
        front = group.get("primary_front")
        if not front:
            group["matches"] = []
            group["confidence_level"] = "red"
            continue
        group_back = group.get("group_back") or {}
        back_type = ((group_back.get("classification") or {}).get("back_type") or "")
        match_entries = []
        detail_cards = group.get("detail_cards") or []
        if detail_cards:
            for detail in detail_cards:
                if detail.get("front"):
                    match_entries.append(detail["front"])
        elif _safe_int(group.get("expected_cards"), 1) > 1:
            group["matches"] = [
                {
                    "region": {"box": [0, 0, 1, 1], "source": "multi_card_group"},
                    "status": "review",
                    "method": "multi_card_group",
                    "score": 0.0,
                    "second_score": 0.0,
                    "margin": 0.0,
                    "diagnostic_reason": "multi-cartes: sous-cartes à vérifier",
                    "v10_safety_reason": "recto commun multi-cartes non auto-validé",
                    "ocr": {"available": False, "rows": [], "name_texts": [], "number_texts": [], "raw_text": ""},
                    "candidates": [],
                    "photo": front["photo"],
                }
            ]
            group["confidence_level"] = "orange"
            continue
        else:
            match_entries.append(front)
        group["matches"] = []
        group_expected_cards = max(1, _safe_int(group.get("expected_cards"), 1))
        group_layout_hint = "V_UNION" if group_expected_cards == 4 and len(detail_cards) == 4 else ""
        group_photo_payloads = [
            photo_identity(entry["photo"])
            for entry in group.get("photos", []) or []
            if entry.get("photo") is not None
        ]
        physical_group_id = str(group.get("ground_truth_group_id") or stable_group_id_from_photos(group_photo_payloads))
        for match_index, match_entry in enumerate(match_entries):
            detail = detail_cards[match_index] if match_index < len(detail_cards) else {}
            back_entry = detail.get("back") if detail else group.get("group_back")
            match_back_type = (
                ((back_entry or {}).get("classification") or {}).get("back_type")
                or back_type
            )
            klass = match_entry.get("classification", {})
            if ocr_available:
                match = match_front_photo_orientation_aware(
                    match_entry["photo"].path,
                    candidates,
                    used_candidate_counts,
                    back_type=match_back_type,
                    ocr_payload_override=(cached_ocr_by_path or {}).get(match_entry["photo"].path),
                    layout_hint=group_layout_hint,
                )
            else:
                visual_matches = match_front_photo(
                    match_entry["photo"].path,
                    klass.get("regions", []),
                    candidates,
                    reference_features,
                )
                match = visual_matches[0] if visual_matches else {"status": "unrecognized", "method": "visual", "candidates": []}
            ocr_payload = match.get("ocr") or {}
            if (
                group.get("v14_generic_multi")
                and not (ocr_payload.get("name_texts") or [])
                and not (ocr_payload.get("collector_number_texts") or [])
            ):
                if match.get("status") == "recognized":
                    match["status"] = "review"
                match["v13_not_in_drop_confidence"] = match.get("v13_not_in_drop_confidence") or "possible"
                match["v10_safety_reason"] = "multi-cartes: artwork plausible mais nom/numéro non confirmés dans le Drop"
                match["diagnostic_reason"] = "carte absente du Drop possible — validation de la sous-carte requise"
            match["photo"] = match_entry["photo"]
            front_key = photo_key(match_entry["photo"])
            back_key = photo_key(back_entry["photo"]) if back_entry and back_entry.get("photo") else ""
            # A subcard is a physical front/back pair inside a stable photo group.
            # Candidate order can change freely without moving its validation.
            physical_payload = f"group={physical_group_id}|front={front_key}|back={back_key}"
            match["subcard_id"] = "subcard_" + hashlib.sha1(physical_payload.encode("utf-8")).hexdigest()[:16]
            match["subcard_photos"] = {"front": front_key, "back": back_key}
            match["physical_group_id"] = physical_group_id
            match["physical_back_type"] = match_back_type
            group["matches"].append(match)
            if not group_layout_hint and match.get("status") == "recognized" and match.get("candidates"):
                key = ((match["candidates"][0].get("candidate") or {}).get("drop_card_key") or "")
                if key:
                    used_candidate_counts[key] = used_candidate_counts.get(key, 0) + 1
        if group_layout_hint == "V_UNION":
            primary_ocr = (cached_ocr_by_path or {}).get(front["photo"].path) or run_ocr_for_photo(
                front["photo"].path
            )
            v_union_family_hint, family_candidates, family_reason = _v_union_family_for_group(
                group["matches"],
                candidates,
                primary_ocr,
                candidate_indexes=candidate_indexes,
            )
            group["v_union_primary_ocr"] = primary_ocr
            group["v_union_family"] = v_union_family_hint
            group["v_union_family_reason"] = family_reason
            group["v_union_family_candidates"] = [
                {
                    "card_uid": candidate.get("card_uid", ""),
                    "number": candidate.get("number", ""),
                    "set": candidate.get("set", ""),
                    "drop_card_key": candidate.get("drop_card_key", ""),
                }
                for candidate in family_candidates
            ]
            if family_candidates:
                rematched_children = []
                for previous_match in group["matches"]:
                    rematched = match_front_photo_ocr(
                        previous_match["photo"].path,
                        family_candidates,
                        used_candidate_counts,
                        back_type=back_type,
                        ocr_payload_override=_ocr_with_v_union_edge_numbers(previous_match.get("ocr")),
                        family_hint=v_union_family_hint,
                    )
                    _preserve_physical_match_identity(rematched, previous_match)
                    rematched["v_union_family_reason"] = family_reason
                    family_numbers = {
                        _normalize_card_number(candidate.get("number") or "")
                        for candidate in family_candidates
                        if _normalize_card_number(candidate.get("number") or "")
                    }
                    edge_number_values = list(
                        (previous_match.get("ocr") or {}).get("v_union_edge_numbers") or []
                    )
                    edge_numbers = {
                        _normalize_card_number(number)
                        for number in edge_number_values
                        if _normalize_card_number(number)
                    }
                    current_number_exists = bool(edge_numbers & candidate_numbers)
                    if current_number_exists:
                        rematched.pop("v13_not_in_drop_confidence", None)
                        rematched.pop("v14_same_name_version_absent", None)
                        rematched.pop("v14_not_in_drop_diagnostic", None)
                        rematched["v14_candidate_number_guard"] = "numéro V-UNION présent dans l'index candidat courant"
                    elif edge_numbers and not (edge_numbers & family_numbers):
                        observed = ", ".join(sorted(set(map(str, edge_number_values))))
                        rematched["status"] = "review"
                        rematched["v13_not_in_drop_confidence"] = "strong"
                        rematched["v14_same_name_version_absent"] = True
                        rematched["v14_not_in_drop_diagnostic"] = "version_exacte_absente"
                        rematched["diagnostic_reason"] = (
                            f"même famille V-UNION, mais numéro {observed} absent du Drop"
                        )
                    rematched_children.append(rematched)
                group["matches"] = rematched_children

            family_numbers = {
                _normalize_card_number(candidate.get("number") or "")
                for candidate in family_candidates
                if _normalize_card_number(candidate.get("number") or "")
            }
            observed_numbers = {
                _normalize_card_number(number)
                for current_match in group["matches"]
                for number in ((current_match.get("ocr") or {}).get("v_union_edge_numbers") or [])
                if _normalize_card_number(number) in family_numbers
            }
            missing_numbers = family_numbers - observed_numbers
            missing_matches = [
                (index, current_match)
                for index, current_match in enumerate(group["matches"])
                if not ((current_match.get("ocr") or {}).get("v_union_edge_numbers") or [])
            ]
            if len(missing_numbers) == 1 and len(missing_matches) == 1:
                missing_number = next(iter(missing_numbers))
                display_number = "S" + missing_number if re.fullmatch(r"WSH\d{3}", missing_number) else missing_number
                match_index, previous_match = missing_matches[0]
                augmented_ocr = dict(previous_match.get("ocr") or {})
                augmented_ocr["collector_number_texts"] = sorted(
                    set(augmented_ocr.get("collector_number_texts") or []) | {display_number}
                )
                augmented_ocr["all_number_texts"] = sorted(
                    set(augmented_ocr.get("all_number_texts") or []) | {display_number}
                )
                augmented_ocr["v_union_inferred_number"] = display_number
                rematched = match_front_photo_ocr(
                    previous_match["photo"].path,
                    family_candidates,
                    used_candidate_counts,
                    back_type=back_type,
                    ocr_payload_override=augmented_ocr,
                    family_hint=v_union_family_hint,
                )
                _preserve_physical_match_identity(rematched, previous_match)
                rematched["v_union_inferred_number"] = display_number
                if rematched.get("status") == "recognized":
                    rematched["status"] = "review"
                rematched["diagnostic_reason"] = (
                    f"V-UNION : numéro {display_number} déduit des trois autres morceaux; validation requise"
                )
                group["matches"][match_index] = rematched
            for match in group["matches"]:
                if match.get("status") == "recognized" and match.get("candidates"):
                    key = ((match["candidates"][0].get("candidate") or {}).get("drop_card_key") or "")
                    if key:
                        used_candidate_counts[key] = used_candidate_counts.get(key, 0) + 1
        elif group_expected_cards == 2 and len(detail_cards) == 2:
            primary_ocr = (cached_ocr_by_path or {}).get(front["photo"].path) or run_ocr_for_photo(
                front["photo"].path
            )
            legend_family, legend_candidates, legend_reason = _legend_family_for_group(
                group["matches"],
                candidates,
                primary_ocr,
            )
            if legend_candidates:
                group["legend_primary_ocr"] = primary_ocr
                group["legend_family"] = legend_family
                group["legend_family_reason"] = legend_reason
                group["legend_family_candidates"] = [
                    {
                        "card_uid": candidate.get("card_uid", ""),
                        "number": candidate.get("number", ""),
                        "set": candidate.get("set", ""),
                        "drop_card_key": candidate.get("drop_card_key", ""),
                    }
                    for candidate in legend_candidates
                ]
                rematched_children = []
                for previous_match in group["matches"]:
                    rematched = match_front_photo_orientation_aware(
                        previous_match["photo"].path,
                        legend_candidates,
                        used_candidate_counts,
                        back_type=str(previous_match.get("physical_back_type") or ""),
                        ocr_payload_override=previous_match.get("ocr") or {},
                        layout_hint="LEGEND_HALF",
                        family_hint=legend_family,
                    )
                    _preserve_physical_match_identity(
                        rematched,
                        previous_match,
                        layout_type="LEGEND_HALF",
                    )
                    rematched["physical_back_type"] = previous_match.get("physical_back_type") or ""
                    rematched["legend_family_reason"] = legend_reason
                    if rematched.get("status") == "recognized":
                        rematched["status"] = "review"
                    rematched["diagnostic_reason"] = (
                        f"LÉGENDE : {legend_reason} · "
                        + str(rematched.get("diagnostic_reason") or "validation de la moitié requise")
                    )
                    rematched_children.append(rematched)
                group["matches"] = rematched_children
        statuses = [match.get("status") for match in group["matches"]]
        recognized_cards = []
        for match_index, match in enumerate(group["matches"]):
            detail = detail_cards[match_index] if match_index < len(detail_cards) else {}
            candidate = proposed_candidate(match) or {}
            back_entry = detail.get("back") if detail else group.get("group_back")
            back_classification = (back_entry or {}).get("classification") or {}
            physical_japanese = (
                back_classification.get("back_type") == "japanese"
                or bool(candidate.get("japanese"))
                or bool(group.get("jp_physical"))
            )
            recognized_cards.append(
                {
                    "front": detail.get("front") if detail else front,
                    "back": back_entry,
                    "candidate": candidate or None,
                    "status": "not_in_drop"
                    if match.get("v13_not_in_drop_confidence")
                    else match.get("status"),
                    "language": "JP" if physical_japanese else "FR",
                    "variant": {
                        key: bool(candidate.get(key))
                        for key in ("japanese", "reverse", "stamp", "promo", "first_edition", "master_ball", "poke_ball")
                        if candidate.get(key)
                    },
                    "score": match.get("score", 0.0),
                    "margin": match.get("margin", 0.0),
                    "not_in_drop_confidence": match.get("v13_not_in_drop_confidence") or "",
                    "subcard_id": match.get("subcard_id"),
                    "subcard_photos": match.get("subcard_photos") or {},
                }
            )
        group["recognized_cards"] = recognized_cards
        grouping_review = group.get("grouping_status") == "review" and not force_grouping_trust
        if grouping_review:
            if statuses and any(status in ("recognized", "review") for status in statuses):
                group["confidence_level"] = "orange"
            else:
                group["confidence_level"] = "red"
        elif len(group["matches"]) > 1:
            group["confidence_level"] = "orange"
        elif statuses and all(status == "recognized" for status in statuses):
            group["confidence_level"] = "green"
        elif statuses and any(status in ("recognized", "review") for status in statuses):
            group["confidence_level"] = "orange"
        else:
            group["confidence_level"] = "red"
    for group in groups:
        _apply_v13_group_language_diagnostic(group)
    return ocr_available, ocr_note, len(reference_features)


def _metrics_for_groups(
    *,
    ordered: list[PhotoInfo],
    photo_window: list[PhotoInfo],
    candidates: list[dict[str, Any]],
    classifications: dict[str, dict[str, Any]],
    groups: list[dict[str, Any]],
    duration: float,
    ocr_available: bool,
    ocr_note: str,
    reference_images_loaded: int,
    ground_truth_mode=False,
) -> dict[str, Any]:
    front_photos = [group["primary_front"]["photo"] for group in groups if group.get("primary_front")]
    western_backs = sum(1 for item in classifications.values() if item.get("class") == "back_western")
    japanese_backs = sum(1 for item in classifications.values() if item.get("class") == "back_japanese")
    inferred_backs = sum(
        1
        for group in groups
        for entry in group.get("photos", [])
        if (entry.get("classification") or {}).get("sequence_inferred_back")
    )
    diagnostic_causes: dict[str, int] = {}
    for group in groups:
        for match in group.get("matches", []):
            if match.get("status") == "recognized":
                continue
            reason = str(match.get("diagnostic_reason") or "non diagnostiqué")
            if group.get("grouping_status") == "review":
                reason = f"grouping à vérifier + {reason}"
            diagnostic_causes[reason] = diagnostic_causes.get(reason, 0) + 1
    v13_non_auto_causes: dict[str, int] = {}
    for group in groups:
        if group.get("confidence_level") == "green":
            continue
        matches = group.get("matches") or []
        if len(matches) > 1 or _safe_int(group.get("expected_cards"), 1) > 1:
            category = "multi-cartes prudent"
        elif group.get("grouping_status") == "review":
            category = "grouping review"
        elif group.get("v13_japanese_candidate") or str(group.get("v13_back_type") or "").startswith("back_japanese"):
            category = "JP probable"
        elif any(match.get("v13_not_in_drop_confidence") == "strong" for match in matches):
            category = "not_in_drop forte confiance"
        elif any(match.get("v13_not_in_drop_confidence") == "possible" for match in matches):
            category = "not_in_drop possible"
        elif any(match.get("special_layout") for match in matches):
            category = "layout spécial / LÉGENDE"
        elif matches and all(not (match.get("ocr") or {}).get("name_texts") for match in matches):
            category = "nom OCR absent"
        elif matches and all(not (match.get("ocr") or {}).get("number_texts") for match in matches):
            category = "numéro OCR absent"
        elif any("proches" in str(match.get("diagnostic_reason") or "") for match in matches):
            category = "scores candidats proches"
        elif any(match.get("status") == "unrecognized" for match in matches):
            category = "aucun candidat fiable"
        else:
            category = "score insuffisant"
        v13_non_auto_causes[category] = v13_non_auto_causes.get(category, 0) + 1
    group_sizes = [len(group.get("photos", []) or []) for group in groups]
    single_reasons: dict[str, int] = {}
    for group in groups:
        if len(group.get("photos", []) or []) != 1:
            continue
        reasons = group.get("v11_single_unmerged_reason") or group.get("grouping_reasons") or ["single sans diagnostic V11"]
        for reason in reasons:
            key = str(reason or "single sans diagnostic V11")
            single_reasons[key] = single_reasons.get(key, 0) + 1
    v12_summary = next(
        (group.get("_v12_summary") for group in groups if isinstance(group.get("_v12_summary"), dict)),
        {},
    )
    v12_single_reasons: dict[str, int] = {}
    v12_review_reasons: dict[str, int] = {}
    for group in groups:
        if len(group.get("photos", []) or []) == 1:
            reason = str(group.get("v12_single_reason") or "ambiguous_sequence")
            v12_single_reasons[reason] = v12_single_reasons.get(reason, 0) + 1
        if group.get("grouping_status") != "review":
            continue
        if group.get("v12_anchor") or group.get("v12_recovered_multi"):
            category = "multi-cartes prudent"
        elif len(group.get("photos", []) or []) == 1:
            category = str(group.get("v12_single_reason") or "single/incomplet")
        elif str(((group.get("group_back") or {}).get("classification") or {}).get("v12_back_role") or "").startswith("back_japanese"):
            category = "JP candidat"
        else:
            category = "paire séquentielle à confirmer"
        v12_review_reasons[category] = v12_review_reasons.get(category, 0) + 1
    metrics = {
        "photos_total_folder": len(ordered),
        "photos_analyzed": len(photo_window),
        "candidate_cards": len(candidates),
        "reference_images_loaded": reference_images_loaded,
        "primary_front": len(front_photos),
        "raw_front_like_photos": sum(1 for item in classifications.values() if item.get("class") == "primary_front"),
        "back": western_backs + japanese_backs,
        "back_western": western_backs,
        "back_japanese": japanese_backs,
        "back_inferred_by_sequence": inferred_backs,
        "extra": sum(1 for item in classifications.values() if item.get("class") == "extra"),
        "uncertain": sum(1 for item in classifications.values() if item.get("class") == "uncertain"),
        "announcements_detected": len(groups),
        "photos_per_announcement": round(len(photo_window) / max(1, len(groups)), 2),
        "expected_announcements_hint": 90,
        "expected_announcements_delta": len(groups) - 90,
        "one_photo_groups": sum(1 for size in group_sizes if size == 1),
        "two_photo_groups": sum(1 for size in group_sizes if size == 2),
        "three_photo_groups": sum(1 for size in group_sizes if size == 3),
        "four_plus_photo_groups": sum(1 for size in group_sizes if size >= 4),
        "primary_without_back": sum(
            1
            for group in groups
            if group.get("primary_front") and group.get("group_back") is None and not group.get("detail_cards")
        ),
        "back_without_front": sum(1 for group in groups if group.get("primary_front") is None and group.get("group_back") is not None),
        "front_photos_in_groups": len(front_photos),
        "multi_card_fronts": sum(
            1
            for group in groups
            if group.get("expected_cards", 1) > 1
            or (group.get("primary_front") and len((group["primary_front"].get("classification") or {}).get("regions", []) or []) > 1)
        ),
        "v11_single_fusions": sum(1 for group in groups if group.get("v11_single_fusion")),
        "v11_single_unmerged_reasons": single_reasons,
        "v12_baseline_groups": _safe_int(v12_summary.get("groups"), len(groups)),
        "v12_baseline_singles": _safe_int(v12_summary.get("singles"), 0),
        "v12_baseline_reviews": _safe_int(v12_summary.get("reviews"), 0),
        "v12_single_patterns_before": v12_summary.get("single_patterns") or {},
        "v12_single_map_before": v12_summary.get("single_map") or [],
        "v12_repaired_single_photos": _safe_int(v12_summary.get("repaired_single_photos"), 0),
        "v12_recovered_multi_groups": _safe_int(v12_summary.get("recovered_multi_groups"), 0),
        "v12_single_reasons": v12_single_reasons,
        "v12_review_reasons": v12_review_reasons,
        "v12_changed_groups": sum(1 for group in groups if group.get("v12_changed")),
        "v12_photos_lost": _safe_int(v12_summary.get("photos_lost"), 0),
        "v12_photos_duplicated": _safe_int(v12_summary.get("photos_duplicated"), 0),
        "grouping_to_review": sum(1 for group in groups if group.get("grouping_status") == "review"),
        "grouping_silent_errors": 0,
        "auto_recognized": sum(1 for group in groups if group.get("confidence_level") == "green"),
        "to_review": sum(1 for group in groups if group.get("confidence_level") == "orange"),
        "unrecognized": sum(1 for group in groups if group.get("confidence_level") == "red"),
        "ocr_name_detected": sum(
            1 for group in groups for match in group.get("matches", []) if (match.get("ocr") or {}).get("name_texts")
        ),
        "ocr_number_detected": sum(
            1 for group in groups for match in group.get("matches", []) if (match.get("ocr") or {}).get("number_texts")
        ),
        "ocr_both_detected": sum(
            1
            for group in groups
            for match in group.get("matches", [])
            if (match.get("ocr") or {}).get("name_texts") and (match.get("ocr") or {}).get("number_texts")
        ),
        "ocr_unusable": sum(
            1
            for group in groups
            for match in group.get("matches", [])
            if match.get("method") == "ocr_fr" and not ((match.get("ocr") or {}).get("name_texts") or (match.get("ocr") or {}).get("number_texts"))
        ),
        "visual_matching_cases": sum(
            1 for group in groups for match in group.get("matches", []) if _safe_int(match.get("visual_matching_used"), 0) > 0
        ),
        "visual_matching_broad_cases": sum(
            1 for group in groups for match in group.get("matches", []) if bool(match.get("visual_matching_broad"))
        ),
        "visual_matching_seconds": round(
            sum(_safe_float(match.get("visual_matching_elapsed"), 0.0) for group in groups for match in group.get("matches", [])),
            3,
        ),
        "v13_back_japanese": sum(1 for group in groups if group.get("v13_back_type") == "back_japanese"),
        "v13_back_japanese_candidates": sum(1 for group in groups if group.get("v13_back_type") == "back_japanese_candidate"),
        "v13_japanese_candidate_groups": sum(1 for group in groups if group.get("v13_japanese_candidate")),
        "v13_japanese_auto": sum(
            1 for group in groups if group.get("v13_japanese_candidate") and group.get("confidence_level") == "green"
        ),
        "v13_japanese_review": sum(
            1 for group in groups if group.get("v13_japanese_candidate") and group.get("confidence_level") == "orange"
        ),
        "v13_japanese_fail": sum(
            1 for group in groups if group.get("v13_japanese_candidate") and group.get("confidence_level") == "red"
        ),
        "v13_japanese_conflicts": sum(1 for group in groups if group.get("v13_language_conflict")),
        "v13_not_in_drop_strong": sum(
            1
            for group in groups
            if any(match.get("v13_not_in_drop_confidence") == "strong" for match in group.get("matches", []))
        ),
        "v13_not_in_drop_possible": sum(
            1
            for group in groups
            if any(match.get("v13_not_in_drop_confidence") == "possible" for match in group.get("matches", []))
        ),
        "v13_new_auto_signals": sum(
            1 for group in groups for match in group.get("matches", []) if match.get("v13_auto_reason")
        ),
        "duration_seconds": round(duration, 2),
        "avg_seconds_per_announcement": round(duration / max(1, len(groups)), 2),
        "ocr_available": ocr_available,
        "ocr_note": ocr_note,
        "diagnostic_causes": diagnostic_causes,
        "v13_non_auto_causes": v13_non_auto_causes,
        "ground_truth_mode": ground_truth_mode,
    }
    return metrics


def analyze_sample(
    *,
    folder: str | Path = POC_DIR,
    data_path="data.json",
    drops_path="vinted_drops.json",
    drop_id: str | None = None,
    start_index=1,
    target_announcements=30,
    max_photos=90,
    force_rebuild=False,
):
    started = time.perf_counter()
    discovery_started = time.perf_counter()
    ordered = list_ordered_photos(folder)
    start_index = max(1, int(start_index or 1))
    photo_window = ordered[start_index - 1 : start_index - 1 + max(1, int(max_photos or 1))]
    photo_signature = photo_window_signature(photo_window)
    discovery_duration = time.perf_counter() - discovery_started
    candidate_load_started = time.perf_counter()
    drop, candidates = active_drop_candidates(data_path=data_path, drops_path=drops_path, drop_id=drop_id)
    candidates_signature = candidate_set_signature(candidates)
    candidate_load_duration = time.perf_counter() - candidate_load_started
    resolved_drop_id = drop_id or (drop.get("id") if isinstance(drop, dict) else None)
    if not force_rebuild:
        cached_result = load_cached_analysis_result(
            folder=folder,
            drop_id=resolved_drop_id,
            start_index=start_index,
            target_announcements=target_announcements,
            max_photos=max_photos,
            ordered_photos=ordered,
        )
        if cached_result is not None:
            cached_meta = cached_result.get("analysis_meta") or {}
            cached_signature = str(cached_meta.get("candidate_signature") or "")
            proposal_version_stale = (
                str(cached_meta.get("proposal_reliability_version") or "")
                != PROPOSAL_RELIABILITY_VERSION
            )
            if cached_signature != candidates_signature or proposal_version_stale:
                cached_result = refresh_result_candidates(
                    cached_result,
                    data_path=data_path,
                    drops_path=drops_path,
                    drop_id=resolved_drop_id,
                )
            metrics = cached_result.setdefault("metrics", {})
            metrics["photo_discovery_seconds"] = round(discovery_duration, 4)
            metrics["candidate_load_seconds"] = round(candidate_load_duration, 4)
            metrics["analysis_entry_seconds"] = round(time.perf_counter() - started, 4)
            return cached_result

    classification_started = time.perf_counter()
    classifications = {}
    for photo in photo_window:
        classifications[photo.filename] = classify_photo(photo.path)
    classification_duration = time.perf_counter() - classification_started
    grouping_started = time.perf_counter()
    groups = build_groups(photo_window, classifications, target_announcements=target_announcements)
    grouping_duration = time.perf_counter() - grouping_started
    candidate_indexes = _candidate_indexes(candidates)
    recognition_started = time.perf_counter()
    ocr_available, ocr_note, reference_images_loaded = _recognize_groups(
        groups,
        candidates,
        candidate_indexes=candidate_indexes,
    )
    recognition_duration = time.perf_counter() - recognition_started
    duration = time.perf_counter() - started
    metrics = _metrics_for_groups(
        ordered=ordered,
        photo_window=photo_window,
        candidates=candidates,
        classifications=classifications,
        groups=groups,
        duration=duration,
        ocr_available=ocr_available,
        ocr_note=ocr_note,
        reference_images_loaded=reference_images_loaded,
    )
    metrics["v12_grouping_seconds"] = round(grouping_duration, 3)
    metrics["photo_discovery_seconds"] = round(discovery_duration, 4)
    metrics["candidate_load_seconds"] = round(candidate_load_duration, 4)
    metrics["classification_seconds"] = round(classification_duration, 4)
    metrics["recognition_seconds"] = round(recognition_duration, 4)
    descriptor = _analysis_cache_descriptor(
        folder=folder,
        drop_id=resolved_drop_id,
        start_index=start_index,
        target_announcements=int(target_announcements or 0),
        max_photos=int(max_photos or 0),
        photo_signature=photo_signature,
    )
    result = {
        "analysis_meta": {
            "pipeline_version": POC_ANALYSIS_PIPELINE_VERSION,
            "folder": str(Path(folder).resolve()),
            "drop_id": resolved_drop_id,
            "start_index": start_index,
            "target_announcements": int(target_announcements or 0),
            "max_photos": int(max_photos or 0),
            "photo_count": len(photo_window),
            "photo_signature": photo_signature,
            "candidate_signature": candidates_signature,
            "matching_refresh_version": POC_MATCHING_REFRESH_VERSION,
            "proposal_reliability_version": PROPOSAL_RELIABILITY_VERSION,
            "drop_membership_reconciliation_version": DROP_MEMBERSHIP_RECONCILIATION_VERSION,
            "result_cache_descriptor": descriptor,
        },
        "drop": drop,
        "ordered_photos": ordered,
        "sample_photos": photo_window,
        "candidates": candidates,
        "candidate_indexes": _candidate_index_debug(candidate_indexes),
        "groups": groups,
        "classifications": classifications,
        "metrics": metrics,
    }
    cache_info = save_cached_analysis_result(result)
    metrics["persistent_cache_write_seconds"] = round(cache_info["write_seconds"], 4)
    metrics["persistent_cache_size_bytes"] = cache_info["size_bytes"]
    metrics["persistent_cache_hit"] = False
    return result


_CANDIDATE_DERIVED_GROUP_FIELDS = (
    "matches",
    "recognized_cards",
    "confidence_level",
    "v_union_primary_ocr",
    "v_union_family",
    "v_union_family_reason",
    "v_union_family_candidates",
    "legend_primary_ocr",
    "legend_family",
    "legend_family_reason",
    "legend_family_candidates",
    "v13_back_type",
    "v13_back_reason",
    "v13_back_scores",
    "v13_japanese_candidate",
    "v13_japanese_top_candidate",
    "v13_language_conflict",
)


def _clear_candidate_derived_group_state(groups: list[dict[str, Any]]) -> None:
    """Clear only match data; grouping, photos and cached OCR remain intact."""
    for group in groups:
        for field in _CANDIDATE_DERIVED_GROUP_FIELDS:
            group.pop(field, None)


def _candidate_matching_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        **candidate_identity(candidate),
        "quantity": max(1, _safe_int(candidate.get("quantity"), 1)),
        "image_url": str(candidate.get("image_url") or ""),
    }


def _candidate_payload_map(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        candidate_identity_key(candidate): _candidate_matching_payload(candidate)
        for candidate in candidates
    }


def _match_candidate_keys(group: dict[str, Any]) -> set[str]:
    keys = set()
    for match in group.get("matches", []) or []:
        for row in match.get("candidates", []) or []:
            candidate = row.get("candidate") or {}
            if candidate:
                keys.add(candidate_identity_key(candidate))
    return keys


def _group_matching_signals(group: dict[str, Any]) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    numbers: set[str] = set()
    for match in group.get("matches", []) or []:
        ocr = match.get("ocr") or {}
        for value in (
            list(ocr.get("name_texts") or [])
            + list(ocr.get("name_fallback_texts") or [])
        ):
            folded = _fold_text(value)
            if folded:
                names.add(folded)
        for value in (
            list(ocr.get("collector_number_texts") or [])
            + list(ocr.get("number_texts") or [])
            + list(ocr.get("all_number_texts") or [])
            + list(ocr.get("v_union_edge_numbers") or [])
        ):
            normalized = _normalize_card_number(value)
            if normalized:
                numbers.add(normalized)
                local = _number_local(normalized)
                if local:
                    numbers.add(local)
    return names, numbers


def _candidate_matches_group_signals(candidate: dict[str, Any], group: dict[str, Any]) -> bool:
    names, numbers = _group_matching_signals(group)
    candidate_number = _normalize_card_number(candidate.get("number") or "")
    candidate_local = _number_local(candidate_number)
    if candidate_number and candidate_number in numbers:
        return True
    if candidate_local and candidate_local in numbers:
        return True
    candidate_name = _fold_text(candidate.get("name") or "")
    if candidate_name and any(
        candidate_name == name
        or candidate_name in name
        or name in candidate_name
        or _similarity(candidate_name, name) >= 0.84
        for name in names
    ):
        return True
    layout = str(group.get("v_union_family") or group.get("legend_family") or "")
    return bool(layout and candidate_name and _similarity(_fold_text(layout), candidate_name) >= 0.72)


def _groups_affected_by_candidate_changes(
    groups: list[dict[str, Any]],
    old_candidates: list[dict[str, Any]],
    new_candidates: list[dict[str, Any]],
) -> tuple[list[int], dict[str, int]]:
    old_map = _candidate_payload_map(old_candidates)
    new_map = _candidate_payload_map(new_candidates)
    changed_keys = {
        key
        for key in set(old_map) | set(new_map)
        if old_map.get(key) != new_map.get(key)
    }
    changed_candidates = [
        candidate
        for candidate in [*old_candidates, *new_candidates]
        if candidate_identity_key(candidate) in changed_keys
    ]
    affected = []
    for index, group in enumerate(groups):
        if _match_candidate_keys(group) & changed_keys:
            affected.append(index)
            continue
        if any(_candidate_matches_group_signals(candidate, group) for candidate in changed_candidates):
            affected.append(index)
    return affected, {
        "added": len(set(new_map) - set(old_map)),
        "removed": len(set(old_map) - set(new_map)),
        "changed": len(set(old_map) & set(new_map) & changed_keys),
    }


def _cached_ocr_from_groups(groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    cached_ocr_by_path = {}
    for group in groups:
        primary = group.get("primary_front") or {}
        primary_photo = primary.get("photo")
        primary_ocr = group.get("v_union_primary_ocr") or group.get("legend_primary_ocr")
        if primary_photo and isinstance(primary_ocr, dict):
            cached_ocr_by_path[str(primary_photo.path)] = primary_ocr
        for match in group.get("matches", []) or []:
            photo = match.get("photo")
            if photo and isinstance(match.get("ocr"), dict):
                cached_ocr_by_path[str(photo.path)] = match["ocr"]
    return cached_ocr_by_path


def _used_candidate_counts_before(groups: list[dict[str, Any]], stop_index: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for group in groups[:stop_index]:
        for match in group.get("matches", []) or []:
            status = str(match.get("v10_original_status") or match.get("status") or "")
            candidates = match.get("candidates") or []
            if status != "recognized" or not candidates:
                continue
            candidate = candidates[0].get("candidate") or {}
            key = str(candidate.get("drop_card_key") or candidate.get("_drop_card_key") or "")
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def refresh_result_candidates(
    result: dict[str, Any],
    *,
    data_path="data.json",
    drops_path="vinted_drops.json",
    drop_id: str | None = None,
) -> dict[str, Any]:
    """Rematch an existing POC result after the Drop candidate set changes.

    Grouping, classifications, thumbnails and OCR crops stay untouched. Existing
    OCR payloads are reused directly; only candidate-dependent scoring runs.
    """
    started = time.perf_counter()
    resolved_drop_id = drop_id or (result.get("analysis_meta") or {}).get("drop_id")
    drop, candidates = active_drop_candidates(
        data_path=data_path,
        drops_path=drops_path,
        drop_id=resolved_drop_id,
    )
    previous_signature = str((result.get("analysis_meta") or {}).get("candidate_signature") or "")
    current_signature = candidate_set_signature(candidates)
    groups = result.get("groups", []) or []
    old_candidates = result.get("candidates", []) or []
    meta = result.setdefault("analysis_meta", {})
    previous_matching_version = str(meta.get("matching_refresh_version") or "")
    matching_version_changed = previous_matching_version != POC_MATCHING_REFRESH_VERSION
    membership_version_changed = (
        str(meta.get("drop_membership_reconciliation_version") or "")
        != DROP_MEMBERSHIP_RECONCILIATION_VERSION
    )
    membership_affected_indexes = [
        index
        for index, group in enumerate(groups)
        if any(
            match.get("v13_not_in_drop_confidence") in {"strong", "possible"}
            or match.get("v15_ocr_identity_conflict")
            for match in group.get("matches", [])
        )
    ] if membership_version_changed else []
    proposal_version_changed = (
        str(meta.get("proposal_reliability_version") or "")
        != PROPOSAL_RELIABILITY_VERSION
    )
    proposal_affected_indexes = [
        index
        for index, group in enumerate(groups)
        if any(
            proposed_candidate(match) is None
            and bool((((match.get("candidates") or [{}])[0]).get("candidate") or {}))
            for match in group.get("matches", []) or []
        )
    ] if proposal_version_changed else []
    if (
        previous_signature == current_signature
        and not matching_version_changed
        and not membership_affected_indexes
        and not proposal_affected_indexes
    ):
        duration = time.perf_counter() - started
        result["drop"] = drop
        result["candidates"] = candidates
        meta["candidate_refreshed_at"] = datetime.now().isoformat(timespec="seconds")
        meta["matching_refresh_version"] = POC_MATCHING_REFRESH_VERSION
        meta["drop_membership_reconciliation_version"] = DROP_MEMBERSHIP_RECONCILIATION_VERSION
        meta["proposal_reliability_version"] = PROPOSAL_RELIABILITY_VERSION
        metrics = result.setdefault("metrics", {})
        metrics["candidate_refresh_seconds"] = round(duration, 4)
        metrics["candidate_signature_changed"] = False
        metrics["candidate_groups_rematched"] = 0
        metrics["proposal_groups_rematched"] = 0
        metrics["candidate_refresh_mode"] = "noop"
        if membership_version_changed or proposal_version_changed:
            cache_info = save_cached_analysis_result(result)
            metrics["persistent_cache_write_seconds"] = round(cache_info["write_seconds"], 4)
            metrics["persistent_cache_size_bytes"] = cache_info["size_bytes"]
        return result

    cached_ocr_by_path = _cached_ocr_from_groups(groups)
    affected_indexes, change_counts = _groups_affected_by_candidate_changes(
        groups,
        old_candidates,
        candidates,
    )
    if matching_version_changed:
        affected_indexes = list(range(len(groups)))
    else:
        affected_indexes = sorted(
            set(affected_indexes)
            | set(membership_affected_indexes)
            | set(proposal_affected_indexes)
        )

    candidate_indexes = _candidate_indexes(candidates)
    ocr_available, ocr_note = _ocr_status()
    reference_images_loaded = 0
    for group_index in affected_indexes:
        group = groups[group_index]
        initial_counts = _used_candidate_counts_before(groups, group_index)
        _clear_candidate_derived_group_state([group])
        ocr_available, ocr_note, loaded = _recognize_groups(
            [group],
            candidates,
            cached_ocr_by_path=cached_ocr_by_path,
            candidate_indexes=candidate_indexes,
            initial_used_candidate_counts=initial_counts,
        )
        reference_images_loaded += loaded
    duration = time.perf_counter() - started
    result["drop"] = drop
    result["candidates"] = candidates
    result["candidate_indexes"] = _candidate_index_debug(candidate_indexes)
    meta["candidate_signature_previous"] = previous_signature
    meta["candidate_signature"] = current_signature
    meta["candidate_refreshed_at"] = datetime.now().isoformat(timespec="seconds")
    meta["matching_refresh_version"] = POC_MATCHING_REFRESH_VERSION
    meta["drop_membership_reconciliation_version"] = DROP_MEMBERSHIP_RECONCILIATION_VERSION
    meta["proposal_reliability_version"] = PROPOSAL_RELIABILITY_VERSION
    metrics = _metrics_for_groups(
        ordered=result.get("ordered_photos", []) or [],
        photo_window=result.get("sample_photos", []) or [],
        candidates=candidates,
        classifications=result.get("classifications", {}) or {},
        groups=result.get("groups", []) or [],
        duration=duration,
        ocr_available=ocr_available,
        ocr_note=ocr_note,
        reference_images_loaded=reference_images_loaded,
    )
    metrics["candidate_refresh_seconds"] = round(duration, 3)
    metrics["candidate_signature_changed"] = previous_signature != current_signature
    metrics["candidate_groups_rematched"] = len(affected_indexes)
    metrics["proposal_groups_rematched"] = len(set(proposal_affected_indexes) & set(affected_indexes))
    metrics["candidate_refresh_mode"] = (
        "full_version_upgrade"
        if matching_version_changed
        else "proposal_reconciliation"
        if proposal_affected_indexes and previous_signature == current_signature and not membership_affected_indexes
        else "membership_reconciliation"
        if membership_affected_indexes and previous_signature == current_signature
        else "incremental"
    )
    metrics["candidate_changes"] = change_counts
    result["metrics"] = metrics
    cache_info = save_cached_analysis_result(result)
    metrics["persistent_cache_write_seconds"] = round(cache_info["write_seconds"], 4)
    metrics["persistent_cache_size_bytes"] = cache_info["size_bytes"]
    return result


def photo_identity(photo: PhotoInfo) -> dict[str, Any]:
    return {"filename": photo.filename, "capture_index": photo.capture_index}


def photo_key(photo_or_payload: PhotoInfo | dict[str, Any]) -> str:
    if isinstance(photo_or_payload, PhotoInfo):
        return f"{photo_or_payload.capture_index}:{photo_or_payload.filename}"
    return f"{photo_or_payload.get('capture_index')}:{photo_or_payload.get('filename')}"


def group_photo_signature(photos: list[dict[str, Any]]) -> str:
    keys = [photo_key(photo) for photo in photos if photo.get("filename")]
    return "|".join(keys)


def stable_group_id_from_photos(photos: list[dict[str, Any]]) -> str:
    signature = group_photo_signature(photos)
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    first = photos[0].get("capture_index") if photos else "x"
    last = photos[-1].get("capture_index") if photos else "x"
    return f"group_{first}_{last}_{digest}"


def normalize_group_status(status: str | None) -> str:
    value = str(status or "unvalidated")
    if value == "correct":
        return "validated"
    if value in {"validated", "corrected", "unvalidated"}:
        return value
    return "unvalidated"


def _role_for_entry(group: dict[str, Any], entry: dict[str, Any]) -> str:
    photo = entry.get("photo")
    if group.get("primary_front") and photo_key(group["primary_front"]["photo"]) == photo_key(photo):
        return "primary_front"
    if group.get("group_back") and photo_key(group["group_back"]["photo"]) == photo_key(photo):
        klass = group["group_back"].get("classification") or {}
        return "back_japanese" if klass.get("back_type") == "japanese" else "back_western"
    for detail in group.get("detail_cards") or []:
        if detail.get("front") and photo_key(detail["front"]["photo"]) == photo_key(photo):
            return "card_front"
        if detail.get("back") and photo_key(detail["back"]["photo"]) == photo_key(photo):
            klass = detail["back"].get("classification") or {}
            return "back_japanese" if klass.get("back_type") == "japanese" else "card_back"
    klass_name = str((entry.get("classification") or {}).get("class") or "")
    if klass_name in PHOTO_ROLES:
        return klass_name
    if klass_name.startswith("back"):
        return "back_japanese" if klass_name == "back_japanese" else "back_western"
    return "extra" if klass_name == "extra" else "uncertain"


def group_to_ground_truth(group: dict[str, Any]) -> dict[str, Any]:
    photos = []
    for entry in group.get("photos", []) or []:
        photo = entry.get("photo")
        if not photo:
            continue
        photos.append({**photo_identity(photo), "role": _role_for_entry(group, entry)})
    return {
        "group_id": stable_group_id_from_photos(photos),
        "photo_signature": group_photo_signature(photos),
        "status": "unvalidated",
        "auto_grouping_status": group.get("grouping_status", "review"),
        "expected_cards": max(1, _safe_int(group.get("expected_cards"), 1)),
        "jp_physical": False,
        "photos": photos,
        "notes": "",
        "recognition_validation": {},
    }


def sample_ground_truth_key(*, folder: str | Path, start_index: int, max_photos: int, target_announcements: int, drop_id: str | None = None) -> str:
    folder_name = Path(folder).name or str(folder)
    drop_part = drop_id or "active"
    return f"{folder_name}|drop={drop_part}|start={int(start_index)}|photos={int(max_photos)}|target={int(target_announcements)}"


def load_poc_ground_truth(path: str | Path = POC_GROUND_TRUTH_PATH) -> dict[str, Any]:
    payload = load_json_file(path, {"version": 1, "samples": {}})
    if not isinstance(payload, dict):
        return {"version": 1, "samples": {}}
    payload.setdefault("version", 1)
    payload.setdefault("samples", {})
    return payload


def save_poc_ground_truth(payload: dict[str, Any], path: str | Path = POC_GROUND_TRUTH_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _ground_truth_match_front_indices(group: dict[str, Any]) -> list[int]:
    photos = group.get("photos", []) or []
    detail_fronts = [
        _safe_int(photo.get("capture_index"), 0)
        for photo in photos
        if photo.get("role") == "card_front"
    ]
    if detail_fronts:
        return [index for index in detail_fronts if index > 0]
    primary = next(
        (_safe_int(photo.get("capture_index"), 0) for photo in photos if photo.get("role") == "primary_front"),
        0,
    )
    return [primary] if primary > 0 else []


def _merge_overlapping_ground_truth_groups(
    detected: dict[str, Any],
    overlapping: list[dict[str, Any]],
) -> dict[str, Any]:
    """Carry manual recognition truth across a corrected group boundary."""
    validation_by_front = {}
    prepared_by_front = {}
    for source in overlapping:
        front_indices = _ground_truth_match_front_indices(source)
        validations = source.get("recognition_validation") or {}
        for match_index, front_index in enumerate(front_indices):
            validation = validations.get(str(match_index))
            if isinstance(validation, dict):
                validation_by_front[front_index] = dict(validation)
        for match_index, prepared in (source.get("prepared_drop_additions") or {}).items():
            index = _safe_int(match_index, -1)
            if 0 <= index < len(front_indices):
                prepared_by_front[front_indices[index]] = prepared

    merged_validations = {}
    merged_prepared = {}
    for match_index, front_index in enumerate(_ground_truth_match_front_indices(detected)):
        if front_index in validation_by_front:
            merged_validations[str(match_index)] = validation_by_front[front_index]
        if front_index in prepared_by_front:
            merged_prepared[str(match_index)] = prepared_by_front[front_index]

    notes = [str(group.get("notes") or "").strip() for group in overlapping]
    merged = {
        **detected,
        "status": "corrected" if all(normalize_group_status(group.get("status")) in VALIDATED_GROUP_STATUSES for group in overlapping) else "unvalidated",
        "jp_physical": any(bool(group.get("jp_physical")) for group in overlapping),
        "notes": " · ".join(note for note in notes if note),
        "recognition_validation": merged_validations,
        "migrated_from_group_ids": [group.get("group_id") for group in overlapping if group.get("group_id")],
    }
    if merged_prepared:
        merged["prepared_drop_additions"] = merged_prepared
    return merged


def ensure_ground_truth_sample(result: dict[str, Any], sample_key: str, *, path: str | Path = POC_GROUND_TRUTH_PATH) -> dict[str, Any]:
    payload = load_poc_ground_truth(path)
    samples = payload.setdefault("samples", {})
    detected_groups = [group_to_ground_truth(group) for group in result.get("groups", [])]
    if sample_key not in samples:
        samples[sample_key] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "groups": detected_groups,
        }
        save_poc_ground_truth(payload, path)
        return payload

    sample = samples[sample_key]
    existing_groups = sample.get("groups", []) or []
    by_id = {str(group.get("group_id")): group for group in existing_groups if group.get("group_id")}
    by_signature = {
        str(group.get("photo_signature") or group_photo_signature(group.get("photos", []) or [])): group
        for group in existing_groups
        if group.get("photos")
    }
    merged = []
    matched_existing_ids: set[int] = set()
    changed = False
    for detected in detected_groups:
        existing = by_id.get(str(detected.get("group_id"))) or by_signature.get(str(detected.get("photo_signature")))
        if existing:
            matched_existing_ids.add(id(existing))
            preserved = {
                **detected,
                **existing,
                "group_id": detected.get("group_id"),
                "photo_signature": detected.get("photo_signature"),
                "photos": existing.get("photos") or detected.get("photos"),
                "status": normalize_group_status(existing.get("status")),
            }
            merged.append(preserved)
            if preserved.get("status") != existing.get("status") or preserved.get("group_id") != existing.get("group_id"):
                changed = True
        else:
            detected_keys = {photo_key(photo) for photo in detected.get("photos", []) or []}
            overlapping = [
                group
                for group in existing_groups
                if detected_keys.intersection({photo_key(photo) for photo in group.get("photos", []) or []})
            ]
            overlapping_keys = {
                photo_key(photo)
                for group in overlapping
                for photo in group.get("photos", []) or []
            }
            if overlapping and overlapping_keys == detected_keys:
                merged.append(_merge_overlapping_ground_truth_groups(detected, overlapping))
                matched_existing_ids.update(id(group) for group in overlapping)
            else:
                merged.append(detected)
            changed = True

    # Manual truth wins over a newly detected segmentation that overlaps it.
    unmatched_manual = [
        group
        for group in existing_groups
        if id(group) not in matched_existing_ids
        and normalize_group_status(group.get("status")) in VALIDATED_GROUP_STATUSES
        and group.get("photos")
    ]
    for manual_group in unmatched_manual:
        manual_keys = {photo_key(photo) for photo in manual_group.get("photos", []) or []}
        if not manual_keys:
            continue
        without_overlap = []
        for group in merged:
            group_photos = group.get("photos", []) or []
            remaining_photos = [photo for photo in group_photos if photo_key(photo) not in manual_keys]
            if not remaining_photos:
                continue
            if len(remaining_photos) != len(group_photos):
                remaining_group = {
                    **group,
                    "photos": remaining_photos,
                    "status": "unvalidated",
                    "notes": "Reliquat automatique après priorité au ground truth manuel",
                }
                remaining_group["photo_signature"] = group_photo_signature(remaining_photos)
                remaining_group["group_id"] = stable_group_id_from_photos(remaining_photos)
                without_overlap.append(remaining_group)
            else:
                without_overlap.append(group)
        merged = without_overlap
        merged.append(manual_group)
        changed = True
    merged.sort(
        key=lambda group: min(
            (_safe_int(photo.get("capture_index"), 10**9) for photo in group.get("photos", []) or []),
            default=10**9,
        )
    )
    if len(merged) != len(existing_groups):
        changed = True
    if changed:
        sample["groups"] = merged
        sample["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_poc_ground_truth(payload, path)
    return payload


def update_ground_truth_sample(sample_key: str, sample: dict[str, Any], *, path: str | Path = POC_GROUND_TRUTH_PATH) -> dict[str, Any]:
    payload = load_poc_ground_truth(path)
    for group in sample.get("groups", []) or []:
        group["status"] = normalize_group_status(group.get("status"))
        group["photo_signature"] = group.get("photo_signature") or group_photo_signature(group.get("photos", []) or [])
        group["group_id"] = group.get("group_id") or stable_group_id_from_photos(group.get("photos", []) or [])
    payload.setdefault("samples", {})[sample_key] = {**sample, "updated_at": datetime.now().isoformat(timespec="seconds")}
    save_poc_ground_truth(payload, path)
    return payload


def _entry_from_ground_truth_photo(photo_payload: dict[str, Any], by_key: dict[str, PhotoInfo], classifications: dict[str, dict[str, Any]]):
    photo = by_key.get(photo_key(photo_payload))
    if not photo:
        return None
    classification = dict(classifications.get(photo.filename, {}))
    role = str(photo_payload.get("role") or "uncertain")
    if role in {"back_western", "back_japanese"}:
        classification["class"] = role
        classification["back_type"] = "japanese" if role == "back_japanese" else "western"
    elif role in {"primary_front", "card_front"}:
        classification["class"] = "primary_front"
    elif role == "extra":
        classification["class"] = "extra"
    return {"photo": photo, "classification": classification, "ground_truth_role": role}


def groups_from_ground_truth(sample: dict[str, Any], photos: list[PhotoInfo], classifications: dict[str, dict[str, Any]], *, only_validated=True):
    by_key = {photo_key(photo): photo for photo in photos}
    groups = []
    for raw_idx, raw_group in enumerate(sample.get("groups", []) or [], start=1):
        status = str(raw_group.get("status") or "unvalidated")
        status = normalize_group_status(status)
        if only_validated and status not in VALIDATED_GROUP_STATUSES:
            continue
        entries = []
        for photo_payload in raw_group.get("photos", []) or []:
            entry = _entry_from_ground_truth_photo(photo_payload, by_key, classifications)
            if entry:
                entries.append(entry)
        if not entries:
            continue
        primary = next((entry for entry in entries if entry.get("ground_truth_role") == "primary_front"), entries[0])
        group_back = next((entry for entry in entries if entry.get("ground_truth_role") in {"back_western", "back_japanese"}), None)
        detail_cards = []
        current_detail = None
        for entry in entries:
            role = entry.get("ground_truth_role")
            if role == "card_front":
                current_detail = {"front": entry, "back": None}
                detail_cards.append(current_detail)
            elif role == "card_back":
                if current_detail is None or current_detail.get("back"):
                    current_detail = {"front": None, "back": entry}
                    detail_cards.append(current_detail)
                else:
                    current_detail["back"] = entry
        groups.append(
            {
                "announcement_index": len(groups) + 1,
                "ground_truth_group_id": raw_group.get("group_id") or str(raw_idx),
                "photos": entries,
                "primary_front": primary,
                "group_back": group_back,
                "detail_cards": detail_cards,
                "expected_cards": max(1, _safe_int(raw_group.get("expected_cards"), 1)),
                "grouping_status": "ok",
                "grouping_reasons": ["ground truth validé"],
                "jp_physical": bool(raw_group.get("jp_physical")),
                "ground_truth_status": status,
                "recognition_validation": raw_group.get("recognition_validation") or {},
            }
        )
    return groups


def analyze_ground_truth_sample(
    sample: dict[str, Any],
    *,
    folder: str | Path = POC_DIR,
    data_path="data.json",
    drops_path="vinted_drops.json",
    drop_id: str | None = None,
    only_validated=True,
):
    started = time.perf_counter()
    ordered = list_ordered_photos(folder)
    filenames = {
        str(photo.get("filename") or "")
        for group in sample.get("groups", []) or []
        for photo in group.get("photos", []) or []
    }
    photo_window = [photo for photo in ordered if photo.filename in filenames]
    classifications = {photo.filename: classify_photo(photo.path) for photo in photo_window}
    drop, candidates = active_drop_candidates(data_path=data_path, drops_path=drops_path, drop_id=drop_id)
    groups = groups_from_ground_truth(sample, ordered, classifications, only_validated=only_validated)
    ocr_available, ocr_note, reference_images_loaded = _recognize_groups(groups, candidates, force_grouping_trust=True)
    duration = time.perf_counter() - started
    metrics = _metrics_for_groups(
        ordered=ordered,
        photo_window=photo_window,
        candidates=candidates,
        classifications=classifications,
        groups=groups,
        duration=duration,
        ocr_available=ocr_available,
        ocr_note=ocr_note,
        reference_images_loaded=reference_images_loaded,
        ground_truth_mode=True,
    )
    total_groups = len(sample.get("groups", []) or [])
    validated = sum(1 for group in sample.get("groups", []) or [] if normalize_group_status(group.get("status")) in VALIDATED_GROUP_STATUSES)
    corrected = sum(1 for group in sample.get("groups", []) or [] if group.get("status") == "corrected")
    metrics.update(
        {
            "ground_truth_groups": total_groups,
            "ground_truth_validated": validated,
            "ground_truth_corrected": corrected,
            "ground_truth_accuracy": round(validated / max(1, total_groups) * 100, 1),
            "real_announcements": len(groups),
            "real_multi_card_groups": sum(1 for group in groups if _safe_int(group.get("expected_cards"), 1) > 1),
        }
    )
    return {
        "drop": drop,
        "ordered_photos": ordered,
        "sample_photos": photo_window,
        "candidates": candidates,
        "groups": groups,
        "classifications": classifications,
        "metrics": metrics,
    }

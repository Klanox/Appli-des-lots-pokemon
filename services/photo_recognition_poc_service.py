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
from services.vinted_drops_service import drop_card_key, load_vinted_drops


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
POC_ANALYSIS_PIPELINE_VERSION = "v12-sequence-dp"
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
        merged.update({key: value for key, value in ref.items() if value not in (None, "")})
        merged.setdefault("lot_name", (card or {}).get("lot_name", ""))
        merged.setdefault("identity_fingerprint", card_identity_fingerprint(merged))
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
                "quantity": max(1, _safe_int(merged.get("quantity"), 1)),
                "price": _safe_float(merged.get("suggested_price", merged.get("price_at_add", 0))),
                "image_url": _candidate_image_url(merged),
                "identity_fingerprint": merged.get("identity_fingerprint") or card_identity_fingerprint(merged),
            }
        )
    return drop, candidates


def _candidate_image_url(card: dict) -> str:
    for key in ("manual_image_path", "manual_image_url", "resolved_collection_image_url", "image_url", "image_url_en", "image"):
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
    collector_regions = {"bottom_collector", "bottom_edge"}
    for row in rows:
        text = row["text"]
        tokens = _extract_number_tokens(text) if re.search(r"\d", text) else []
        all_number_texts.extend(tokens)
        if row["region"] == "bottom_number":
            number_texts.extend(tokens)
        if row["region"] in collector_regions or any("/" in _normalize_card_number(token) for token in tokens):
            collector_number_texts.extend(tokens)
    return {
        "name_texts": name_texts,
        "number_texts": sorted(set(number_texts)),
        "collector_number_texts": sorted(set(collector_number_texts)),
        "all_number_texts": sorted(set(all_number_texts)),
    }


def run_ocr_for_photo(path: str) -> dict[str, Any]:
    cache_path = _ocr_cache_path(path)
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
    text_bits = []
    text_bits.extend(ocr_payload.get("name_texts") or [])
    text_bits.extend(ocr_payload.get("number_texts") or [])
    text_bits.append(str(ocr_payload.get("raw_text") or ""))
    if candidate:
        text_bits.append(str(candidate.get("name") or ""))
    folded = _fold_text(" ".join(text_bits))
    signals = []
    if "legende" in folded or "legend" in folded:
        signals.append("layout spécial / LÉGENDE détecté")
    if "vunion" in folded or ("union" in folded and "pokemon" in folded):
        signals.append("layout spécial / V-UNION détecté")
    return signals


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


def _candidate_score_from_ocr(ocr_payload: dict[str, Any], candidate: dict[str, Any], *, back_type: str = "") -> dict[str, Any]:
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
    if cand_num_full and "/" in cand_num_full and cand_num_full in collector_numbers:
        number_score = 80.0
        number_reason = f"numéro exact {cand_num_full}"
        number_kind = "full_collector"
    elif cand_num_local and cand_num_local in collector_locals_from_full and len(cand_num_local) >= 2:
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

    name_scores = [(_similarity(text, str(candidate.get("name") or "")), text) for text in ocr_payload.get("name_texts", [])]
    best_name_score, best_name_text = max(name_scores, default=(0.0, ""))
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

    total = number_score + name_points + language_points
    reasons = [reason for reason in (number_reason, name_reason, "signal verso JP" if language_points else "") if reason]
    return {
        "candidate": candidate,
        "score": round(min(total, 100.0), 2),
        "number_match": bool(number_score),
        "number_kind": number_kind,
        "candidate_number_full": cand_num_full,
        "candidate_number_local": cand_num_local,
        "name_similarity": round(best_name_score, 3),
        "ocr_name": best_name_text,
        "ocr_numbers": ocr_numbers,
        "collector_numbers": collector_numbers,
        "reasons": reasons,
    }


def match_front_photo_ocr(path: str, candidates: list[dict[str, Any]], used_counts: dict[str, int] | None = None, *, back_type: str = ""):
    used_counts = used_counts or {}
    ocr_payload = run_ocr_for_photo(path)
    available_candidates = [
        candidate
        for candidate in candidates
        if used_counts.get(candidate.get("drop_card_key", ""), 0) < max(1, _safe_int(candidate.get("quantity"), 1))
    ]
    scored = [_candidate_score_from_ocr(ocr_payload, candidate, back_type=back_type) for candidate in available_candidates]
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
    scored.sort(key=lambda item: item["score"], reverse=True)
    visual_info = {"used": 0, "elapsed": 0.0, "broad": False}
    if scored and (ocr_payload.get("name_texts") or ocr_payload.get("number_texts")):
        pre_best = scored[0] if scored else None
        pre_second = scored[1] if len(scored) > 1 else None
        pre_margin = (float(pre_best.get("score") or 0.0) - float(pre_second.get("score") or 0.0)) if pre_best and pre_second else 100.0
        no_name = not bool(ocr_payload.get("name_texts"))
        has_cjk = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", str(ocr_payload.get("raw_text") or "")))
        broad_visual = no_name and (bool(ocr_payload.get("collector_number_texts")) or has_cjk)
        needs_visual = (
            broad_visual
            or pre_margin < 14
            or float(pre_best.get("score") or 0.0) < 86
            or (pre_best and pre_best.get("number_kind") in {"plain_collector", "noisy_number"})
        )
        if needs_visual:
            visual_info = _apply_visual_shortlist_scores(path, scored, limit=5, broad=broad_visual)
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
        if best["score"] >= 86 and margin >= 12 and best["number_match"] and not weak_number_without_name:
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
        "special_layout": special_layout,
        "visual_matching_used": visual_info.get("used", 0),
        "visual_matching_elapsed": visual_info.get("elapsed", 0.0),
        "visual_matching_broad": visual_info.get("broad", False),
        "ocr": ocr_payload,
        "candidates": top,
    }


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
    expected_cards = max(1, min(4, _safe_int(classification.get("card_count_hint"), 1)))
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


def _recover_v12_multi_groups(
    groups: list[dict[str, Any]],
    baseline_groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Recover `primary + 2 x (front/back)` blocks without touching known anchors."""
    recovered = []
    recovered_count = 0
    index = 0
    while index < len(groups):
        current = groups[index]
        following = groups[index + 1 : index + 3]
        current_photos = current.get("photos", []) or []
        can_test = (
            len(current_photos) == 1
            and current.get("primary_front") is not None
            and len(following) == 2
            and all(len(group.get("photos", []) or []) == 2 for group in following)
            and all(not group.get("v12_anchor") for group in following)
            and all(group.get("primary_front") is not None and group.get("group_back") is not None for group in following)
            and all(_safe_float(group.get("v12_pair_score"), 0.0) >= 4.0 for group in following)
        )
        if can_test:
            combined_entries = [entry for group in [current, *following] for entry in group.get("photos", []) or []]
            capture_indices = [entry["photo"].capture_index for entry in combined_entries]
            consecutive = capture_indices == list(range(capture_indices[0], capture_indices[0] + 5))
            gap = _capture_gap_seconds(current_photos[0].get("photo"), following[0]["photos"][0].get("photo"))
            has_boundary, boundary_score = _v12_combined_primary_signal(current_photos[0])
            if consecutive and (gap is None or gap <= 75) and has_boundary:
                previous_layout = _v12_previous_layout(baseline_groups, set(capture_indices))
                recovered.append(
                    {
                        "announcement_index": 0,
                        "photos": combined_entries,
                        "primary_front": current_photos[0],
                        "group_back": None,
                        "detail_cards": [
                            {"front": following[0]["primary_front"], "back": following[0]["group_back"]},
                            {"front": following[1]["primary_front"], "back": following[1]["group_back"]},
                        ],
                        "expected_cards": 2,
                        "grouping_status": "review",
                        "grouping_reasons": [
                            "multi-cartes V12 récupéré : primary + 2×(front/back)",
                            f"frontière horizontale du recto commun ({boundary_score:.0%})",
                            "validation prudente requise pour le bloc multi-cartes",
                        ],
                        "v12_recovered_multi": True,
                        "v12_changed": True,
                        "v12_previous_layout": previous_layout,
                    }
                )
                recovered_count += 1
                index += 3
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


def _recognize_groups(groups: list[dict[str, Any]], candidates: list[dict[str, Any]], *, force_grouping_trust=False) -> tuple[bool, str, int]:
    ocr_available, ocr_note = _ocr_status()
    reference_features = {} if ocr_available else build_reference_features(candidates)
    used_candidate_counts = {}
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
        for match_entry in match_entries:
            klass = match_entry.get("classification", {})
            if ocr_available:
                match = match_front_photo_ocr(
                    match_entry["photo"].path,
                    candidates,
                    used_candidate_counts,
                    back_type=back_type,
                )
            else:
                visual_matches = match_front_photo(
                    match_entry["photo"].path,
                    klass.get("regions", []),
                    candidates,
                    reference_features,
                )
                match = visual_matches[0] if visual_matches else {"status": "unrecognized", "method": "visual", "candidates": []}
            match["photo"] = match_entry["photo"]
            group["matches"].append(match)
            if match.get("status") == "recognized" and match.get("candidates"):
                key = ((match["candidates"][0].get("candidate") or {}).get("drop_card_key") or "")
                if key:
                    used_candidate_counts[key] = used_candidate_counts.get(key, 0) + 1
        statuses = [match.get("status") for match in group["matches"]]
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
        "duration_seconds": round(duration, 2),
        "avg_seconds_per_announcement": round(duration / max(1, len(groups)), 2),
        "ocr_available": ocr_available,
        "ocr_note": ocr_note,
        "diagnostic_causes": diagnostic_causes,
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
):
    started = time.perf_counter()
    ordered = list_ordered_photos(folder)
    start_index = max(1, int(start_index or 1))
    photo_window = ordered[start_index - 1 : start_index - 1 + max(1, int(max_photos or 1))]
    photo_signature = hashlib.sha1(
        "|".join(
            f"{photo.capture_index}:{photo.filename}:{photo.size_bytes}"
            for photo in photo_window
        ).encode("utf-8")
    ).hexdigest()
    drop, candidates = active_drop_candidates(data_path=data_path, drops_path=drops_path, drop_id=drop_id)
    classifications = {}
    for photo in photo_window:
        classifications[photo.filename] = classify_photo(photo.path)
    grouping_started = time.perf_counter()
    groups = build_groups(photo_window, classifications, target_announcements=target_announcements)
    grouping_duration = time.perf_counter() - grouping_started
    ocr_available, ocr_note, reference_images_loaded = _recognize_groups(groups, candidates)
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
    return {
        "analysis_meta": {
            "pipeline_version": POC_ANALYSIS_PIPELINE_VERSION,
            "folder": str(Path(folder).resolve()),
            "drop_id": drop_id or (drop.get("id") if isinstance(drop, dict) else None),
            "start_index": start_index,
            "target_announcements": int(target_announcements or 0),
            "max_photos": int(max_photos or 0),
            "photo_count": len(photo_window),
            "photo_signature": photo_signature,
        },
        "drop": drop,
        "ordered_photos": ordered,
        "sample_photos": photo_window,
        "candidates": candidates,
        "groups": groups,
        "classifications": classifications,
        "metrics": metrics,
    }


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

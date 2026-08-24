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
import json
import math
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import requests
except Exception:  # pragma: no cover - optional at runtime
    requests = None

from services.card_identity import card_identity_fingerprint
from services.custom_card_image_service import resolve_custom_card_image
from services.vinted_drops_service import drop_card_key, load_vinted_drops


POC_DIR = Path("photo_recognition_poc")
POC_CACHE_DIR = POC_DIR / ".cache"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
EXIF_DATETIME_TAGS = (36867, 36868, 306)
FILENAME_DATETIME_PATTERNS = (
    re.compile(r"(?P<date>20\d{6})[_-]?(?P<time>\d{6})"),
    re.compile(r"(?P<date>20\d{2}[-_]\d{2}[-_]\d{2})[_\s-]+(?P<time>\d{2}[-_]\d{2}[-_]\d{2})"),
)


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
    score = min(1.0, blue_frac * 2.15 + yellow_frac * 2.4 + max(0.0, vivid_frac - 0.32) * 0.8)
    reasons = []
    if blue_frac > 0.22:
        reasons.append(f"bleu verso {blue_frac:.0%}")
    if yellow_frac > 0.05:
        reasons.append(f"jaune/orange {yellow_frac:.0%}")
    if vivid_frac > 0.45:
        reasons.append(f"couleurs saturées {vivid_frac:.0%}")
    return score, reasons


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
    return kept


def classify_photo(path: str) -> dict[str, Any]:
    image = _load_image(path, max_side=1024)
    if image is None:
        return {"class": "uncertain", "confidence": 0.0, "reasons": ["image illisible"], "regions": []}
    arr = _image_array(image, max_side=768)
    back_score, back_reasons = _pokemon_back_score(arr)
    regions = detect_card_regions(image)
    largest = max((region["area_ratio"] for region in regions), default=0.0)
    if back_score >= 0.62:
        return {"class": "back", "confidence": round(back_score, 2), "reasons": back_reasons or ["signature verso Pokémon"], "regions": regions}
    if len(regions) >= 1 and largest >= 0.18:
        confidence = min(0.92, 0.48 + largest + min(len(regions), 4) * 0.08)
        reasons = [f"{len(regions)} zone(s) carte", f"zone principale {largest:.0%}"]
        return {"class": "primary_front", "confidence": round(confidence, 2), "reasons": reasons, "regions": regions}
    if largest >= 0.06:
        return {"class": "extra", "confidence": round(min(0.75, 0.45 + largest), 2), "reasons": ["détail/zone partielle"], "regions": regions}
    return {"class": "uncertain", "confidence": 0.25, "reasons": ["pas de carte complète détectée"], "regions": regions}


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


def build_groups(photos: list[PhotoInfo], classifications: dict[str, dict[str, Any]], *, target_announcements=30):
    groups = []
    current = None
    for photo in photos:
        result = classifications.get(photo.filename, {})
        klass = result.get("class", "uncertain")
        if klass == "primary_front" or current is None:
            if current is not None:
                groups.append(current)
                if len(groups) >= target_announcements:
                    break
            current = {"announcement_index": len(groups) + 1, "photos": [], "primary_front": None}
        entry = {"photo": photo, "classification": result}
        if current is None:
            current = {"announcement_index": len(groups) + 1, "photos": [], "primary_front": None}
        current["photos"].append(entry)
        if klass == "primary_front" and current.get("primary_front") is None:
            current["primary_front"] = entry
    if current is not None and len(groups) < target_announcements:
        groups.append(current)
    return groups[:target_announcements]


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
    drop, candidates = active_drop_candidates(data_path=data_path, drops_path=drops_path, drop_id=drop_id)
    classifications = {}
    for photo in photo_window:
        classifications[photo.filename] = classify_photo(photo.path)
    groups = build_groups(photo_window, classifications, target_announcements=target_announcements)
    front_photos = [group["primary_front"]["photo"] for group in groups if group.get("primary_front")]
    reference_features = build_reference_features(candidates)
    for group in groups:
        front = group.get("primary_front")
        if not front:
            group["matches"] = []
            continue
        klass = front.get("classification", {})
        group["matches"] = match_front_photo(
            front["photo"].path,
            klass.get("regions", []),
            candidates,
            reference_features,
        )
        statuses = [match.get("status") for match in group["matches"]]
        if len(group["matches"]) > 1:
            group["confidence_level"] = "orange"
        elif statuses and all(status == "recognized" for status in statuses):
            group["confidence_level"] = "green"
        elif statuses and any(status in ("recognized", "review") for status in statuses):
            group["confidence_level"] = "orange"
        else:
            group["confidence_level"] = "red"
    duration = time.perf_counter() - started
    metrics = {
        "photos_total_folder": len(ordered),
        "photos_analyzed": len(photo_window),
        "candidate_cards": len(candidates),
        "reference_images_loaded": len(reference_features),
        "primary_front": sum(1 for item in classifications.values() if item.get("class") == "primary_front"),
        "back": sum(1 for item in classifications.values() if item.get("class") == "back"),
        "extra": sum(1 for item in classifications.values() if item.get("class") == "extra"),
        "uncertain": sum(1 for item in classifications.values() if item.get("class") == "uncertain"),
        "announcements_detected": len(groups),
        "front_photos_in_groups": len(front_photos),
        "multi_card_fronts": sum(
            1
            for group in groups
            if group.get("primary_front") and len((group["primary_front"].get("classification") or {}).get("regions", []) or []) > 1
        ),
        "auto_recognized": sum(1 for group in groups if group.get("confidence_level") == "green"),
        "to_review": sum(1 for group in groups if group.get("confidence_level") == "orange"),
        "unrecognized": sum(1 for group in groups if group.get("confidence_level") == "red"),
        "duration_seconds": round(duration, 2),
        "avg_seconds_per_announcement": round(duration / max(1, len(groups)), 2),
        "ocr_available": False,
        "ocr_note": "Aucun OCR local disponible dans l'environnement; POC limité au visuel/heuristiques.",
    }
    return {
        "drop": drop,
        "ordered_photos": ordered,
        "sample_photos": photo_window,
        "candidates": candidates,
        "groups": groups,
        "classifications": classifications,
        "metrics": metrics,
    }

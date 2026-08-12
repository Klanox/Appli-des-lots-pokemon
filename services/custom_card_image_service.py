"""Persistent fallback library for user-provided card images."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from functools import lru_cache


CUSTOM_CARD_IMAGES_FILE = "custom_card_images.json"


def default_custom_card_images() -> dict:
    return {"schema_version": 1, "images": {}}


def load_custom_card_images(path: str = CUSTOM_CARD_IMAGES_FILE) -> dict:
    return deepcopy(_load_custom_card_images_cached(path, os.path.getmtime(path) if os.path.exists(path) else 0))


@lru_cache(maxsize=4)
def _load_custom_card_images_cached(path: str, _mtime: float) -> dict:
    if not os.path.exists(path):
        return default_custom_card_images()
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return default_custom_card_images()
    if not isinstance(payload, dict):
        return default_custom_card_images()
    payload.setdefault("schema_version", 1)
    payload.setdefault("images", {})
    if not isinstance(payload["images"], dict):
        payload["images"] = {}
    return payload


def save_custom_card_images(payload: dict, path: str = CUSTOM_CARD_IMAGES_FILE) -> bool:
    normalized = {
        "schema_version": 1,
        "images": dict(payload.get("images") or {}),
    }
    existing = load_custom_card_images(path)
    if normalized == existing:
        return False
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".custom_card_images_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
        _load_custom_card_images_cached.cache_clear()
        return True
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def is_official_image_ref(value: str) -> bool:
    value = str(value or "").strip().lower()
    return "tcgdex.net" in value or "assets.pokemon" in value or "images.pokemontcg.io" in value


def is_custom_image_ref(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    if is_official_image_ref(value):
        return False
    return (
        value.startswith(("card_images/", "card_images\\"))
        or value.startswith(("http://", "https://"))
        or os.path.exists(value)
    )


def has_official_image(card: dict) -> bool:
    for key in ("image_url", "image_url_en", "image_url_ja", "image", "imageUrl", "resolved_collection_image_url"):
        if is_official_image_ref(str(card.get(key) or "")):
            return True
    return False


def card_image_identity(card: dict) -> str:
    identities = card_image_identities(card)
    return identities[0] if identities else ""


def _nested_set_id(card: dict) -> str:
    set_info = card.get("set")
    if isinstance(set_info, dict):
        return str(set_info.get("id") or "").strip().lower()
    return ""


def _number_variants(value) -> list[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return []
    variants = [raw]
    stripped = raw.lstrip("0")
    if stripped and stripped not in variants:
        variants.append(stripped)
    return variants


def card_image_identities(card: dict) -> list[str]:
    if not isinstance(card, dict):
        return []
    identities = []

    card_id = str(card.get("card_id") or card.get("id") or "").strip().lower()
    if card_id:
        identities.append(f"id:{card_id}")

    raw_card = card.get("raw_cache_card") if isinstance(card.get("raw_cache_card"), dict) else {}
    raw_card_id = str(raw_card.get("card_id") or raw_card.get("id") or "").strip().lower()
    if raw_card_id:
        identities.append(f"id:{raw_card_id}")

    set_id = str(card.get("set_id") or card.get("card_set_id") or "").strip().lower()
    set_id = set_id or _nested_set_id(card)
    if not set_id and raw_card:
        set_id = str(raw_card.get("set_id") or raw_card.get("card_set_id") or "").strip().lower()
        set_id = set_id or _nested_set_id(raw_card)

    number_values = [
        card.get("number"),
        card.get("card_number"),
        card.get("localId"),
        raw_card.get("number") if raw_card else "",
        raw_card.get("card_number") if raw_card else "",
        raw_card.get("localId") if raw_card else "",
    ]
    number_variants = []
    for value in number_values:
        for variant in _number_variants(value):
            if variant not in number_variants:
                number_variants.append(variant)

    if set_id:
        for number in number_variants:
            identities.append(f"id:{set_id}-{number}")
            identities.append(f"set:{set_id}|num:{number}")

    deduped = []
    for identity in identities:
        if identity and identity not in deduped:
            deduped.append(identity)
    return deduped


def register_custom_card_image(card: dict, image_ref: str, *, source: str = "manual", path: str = CUSTOM_CARD_IMAGES_FILE) -> bool:
    image_ref = str(image_ref or "").strip().replace("\\", "/")
    if not image_ref or has_official_image(card):
        return False
    if not is_custom_image_ref(image_ref):
        return False
    identity = card_image_identity(card)
    if not identity:
        return False
    payload = load_custom_card_images(path)
    payload.setdefault("images", {})[identity] = {
        "image_ref": image_ref,
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "card_name": str(card.get("name") or card.get("card_name") or ""),
        "number": str(card.get("number") or card.get("card_number") or ""),
        "set": str(card.get("set") or card.get("card_set") or ""),
    }
    return save_custom_card_images(payload, path)


def resolve_custom_card_image(card: dict, *, path: str = CUSTOM_CARD_IMAGES_FILE) -> str:
    if has_official_image(card):
        return ""
    identities = card_image_identities(card)
    if not identities:
        return ""
    images = load_custom_card_images(path).get("images", {})
    entry = {}
    for identity in identities:
        entry = images.get(identity, {})
        if entry:
            break
    image_ref = str(entry.get("image_ref") or "").strip()
    if not image_ref:
        return ""
    if image_ref.startswith(("card_images/", "card_images\\")) and not os.path.exists(image_ref):
        return ""
    return image_ref


def apply_custom_image_fallback(card: dict, *, path: str = CUSTOM_CARD_IMAGES_FILE) -> bool:
    if any(str(card.get(key) or "").strip() for key in ("image_url", "image_url_en", "image_url_ja", "image", "imageUrl")):
        return False
    custom = resolve_custom_card_image(card, path=path)
    if not custom:
        return False
    card["image_url"] = custom
    return True


def migrate_existing_custom_images(data: dict) -> dict:
    imported = official_ignored = ambiguous = 0
    payload = load_custom_card_images()
    images = payload.setdefault("images", {})
    for lot in data.get("lots", []) or []:
        for card in lot.get("cards", []) or []:
            refs = [
                ("manual_image_path", card.get("manual_image_path")),
                ("manual_image_url", card.get("manual_image_url")),
                ("image_url", card.get("image_url")),
            ]
            for source, ref in refs:
                ref = str(ref or "").strip()
                if not ref:
                    continue
                if is_official_image_ref(ref):
                    official_ignored += 1
                    continue
                if not is_custom_image_ref(ref):
                    ambiguous += 1
                    continue
                if source == "image_url" and not ref.startswith(("card_images/", "card_images\\")):
                    ambiguous += 1
                    continue
                if has_official_image({**card, source: ""}):
                    official_ignored += 1
                    continue
                identity = card_image_identity(card)
                if not identity:
                    ambiguous += 1
                    continue
                if identity not in images:
                    imported += 1
                images[identity] = {
                    "image_ref": ref.replace("\\", "/"),
                    "source": f"migration:{source}",
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "card_name": str(card.get("name") or ""),
                    "number": str(card.get("number") or ""),
                    "set": str(card.get("set") or ""),
                }
                break
    saved = save_custom_card_images(payload)
    return {
        "imported": imported,
        "official_ignored": official_ignored,
        "ambiguous": ambiguous,
        "saved": saved,
        "total_entries": len(payload.get("images", {})),
    }

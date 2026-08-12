"""Local stock value history for the home dashboard.

This file stores display-only chart points and annotations. It does not alter
lot, card, sale, trade or cloud business data.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import date, datetime


STOCK_HISTORY_FILE = "stock_value_history.json"


def _default_payload() -> dict:
    return {"schema_version": 1, "points": [], "annotations": []}


def load_stock_history(path: str = STOCK_HISTORY_FILE) -> dict:
    if not os.path.exists(path):
        return _default_payload()
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return _default_payload()
    if not isinstance(payload, dict):
        return _default_payload()
    payload.setdefault("schema_version", 1)
    payload.setdefault("points", [])
    payload.setdefault("annotations", [])
    if not isinstance(payload["points"], list):
        payload["points"] = []
    if not isinstance(payload["annotations"], list):
        payload["annotations"] = []
    return payload


def save_stock_history(payload: dict, path: str = STOCK_HISTORY_FILE) -> bool:
    try:
        existing = load_stock_history(path)
        normalized = {
            "schema_version": 1,
            "points": list(payload.get("points") or []),
            "annotations": list(payload.get("annotations") or []),
        }
        if normalized == existing:
            return False
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".stock_history_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(normalized, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            return True
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    except OSError:
        return False


def record_stock_value(value: float, *, at: datetime | None = None, path: str = STOCK_HISTORY_FILE) -> tuple[dict, bool]:
    payload = load_stock_history(path)
    now = at or datetime.now()
    value = round(float(value or 0.0), 2)
    points = payload.setdefault("points", [])
    last = points[-1] if points else None
    if last and round(float(last.get("value", 0.0) or 0.0), 2) == value:
        return payload, False
    points.append({"captured_at": now.isoformat(timespec="seconds"), "value": value})
    saved = save_stock_history(payload, path)
    return payload, saved


def add_stock_annotation(note_date: date | datetime | str, comment: str, *, path: str = STOCK_HISTORY_FILE) -> dict:
    payload = load_stock_history(path)
    if isinstance(note_date, datetime):
        date_value = note_date.date().isoformat()
    elif isinstance(note_date, date):
        date_value = note_date.isoformat()
    else:
        date_value = str(note_date or "").strip()
    annotation = {
        "id": uuid.uuid4().hex,
        "date": date_value,
        "comment": str(comment or "").strip()[:180],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    payload.setdefault("annotations", []).append(annotation)
    save_stock_history(payload, path)
    return annotation


def delete_stock_annotation(annotation_id: str, *, path: str = STOCK_HISTORY_FILE) -> bool:
    payload = load_stock_history(path)
    before = len(payload.get("annotations", []) or [])
    payload["annotations"] = [
        item for item in payload.get("annotations", []) or []
        if str(item.get("id")) != str(annotation_id)
    ]
    if len(payload["annotations"]) == before:
        return False
    return save_stock_history(payload, path)

"""Local stock value history for the home dashboard.

This file stores display-only chart points and annotations. It does not alter
lot, card, sale, trade or cloud business data.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path


STOCK_HISTORY_FILE = "stock_value_history.json"
BACKUP_PREFIX = "Appli des lots pokemon - BACKUP"
# Instant de la correction du double comptage des cartes stockees (gst + _stock_value_from_state).
# Les points enregistres AVANT cet instant ont ete calcules avec l'ancienne formule : ils sont
# corriges uniquement a l'affichage (jamais reecrits dans stock_value_history.json).
STOCK_DOUBLE_COUNT_FIX_AT = "2026-10-13T20:21:30"
STOCK_DOUBLE_COUNT_NOTE_ID = "auto_double_count_fix"
STOCK_DOUBLE_COUNT_NOTE = "Correction du double comptage des cartes stockees (courbe recalculee)"
EXCLUDED_HISTORY_IMPORT_BACKUPS = {
    "Appli des lots pokemon - BACKUP BEFORE REAL STOCK HISTORY IMPORT",
}


def _default_payload() -> dict:
    return {"schema_version": 1, "points": [], "annotations": []}


def _float_value(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _read_json_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _stock_value_from_state(data: dict, archives: list[dict] | None = None) -> float:
    lots = list(data.get("lots") or [])
    lots.extend(archives or [])
    value = 0.0
    for lot in lots:
        for card in lot.get("cards", []) or []:
            if card.get("is_collection_keep"):
                continue
            quantity = int(card.get("quantity", 0) or 0)
            sold = int(card.get("sold_quantity", 0) or 0) if "sold_quantity" in card else 0
            exchange_out = int(card.get("exchange_out_quantity", 0) or 0) if "exchange_out_quantity" in card else 0
            # Une carte stockee compte une seule fois (dans le lot Stockage) : meme definition que gst().
            stored = int(card.get("stored_quantity", 0) or 0) if "stored_quantity" in card else 0
            remaining = max(quantity - sold - exchange_out - stored, 0)
            value += remaining * _float_value(card.get("suggested_price"))
    return round(value, 2)


def _count_cards(data: dict) -> int:
    return sum(
        int(card.get("quantity", 0) or 0)
        for lot in data.get("lots", []) or []
        for card in lot.get("cards", []) or []
    )


def _state_hash(data_path: Path, archives_path: Path | None = None) -> str:
    digest = hashlib.sha256()
    digest.update(data_path.read_bytes())
    if archives_path and archives_path.exists():
        digest.update(b"\n--lots_archives--\n")
        digest.update(archives_path.read_bytes())
    return digest.hexdigest()


def _parse_history_datetime(raw: str | None) -> tuple[datetime | None, str]:
    text = str(raw or "").strip()
    if not text:
        return None, ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None), "iso"
    except ValueError:
        return None, ""


def _backup_datetime_from_manifest(folder: Path) -> tuple[datetime | None, str]:
    manifest = _read_json_file(folder / "backup_manifest.json")
    if not isinstance(manifest, dict):
        return None, ""
    for key in ("created_at", "timestamp", "date"):
        parsed, _ = _parse_history_datetime(manifest.get(key))
        if parsed:
            return parsed, "manifest"
    return None, ""


def _backup_datetime_from_name(path: Path) -> tuple[datetime | None, str]:
    text = f"{path.parent.name} {path.name}"
    for pattern in (r"backup_(20\d{6})_(\d{6})", r"(20\d{6})[_-](\d{6})"):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S"), "name"
        except ValueError:
            pass
    return None, ""


def _official_backup_folder_datetime(folder: Path) -> tuple[datetime | None, str]:
    if folder.name in EXCLUDED_HISTORY_IMPORT_BACKUPS:
        return None, ""
    if not folder.name.startswith(BACKUP_PREFIX):
        return None, ""
    try:
        return datetime.fromtimestamp(folder.stat().st_mtime), "backup_folder_mtime"
    except OSError:
        return None, ""


def _source_datetime(data_path: Path, source_kind: str) -> tuple[datetime | None, str]:
    parsed, source = _backup_datetime_from_manifest(data_path.parent)
    if parsed:
        return parsed, source
    parsed, source = _backup_datetime_from_name(data_path)
    if parsed:
        return parsed, source
    if source_kind == "desktop_backup":
        return _official_backup_folder_datetime(data_path.parent)
    return None, ""


def _stock_history_sources(project_dir: Path | None = None, desktop: Path | None = None) -> list[tuple[str, Path]]:
    project_dir = (project_dir or Path.cwd()).resolve()
    desktop = (desktop or Path.home() / "Desktop").resolve()
    sources: list[tuple[str, Path]] = []

    for path in sorted(project_dir.glob("data.json.backup_*")):
        sources.append(("file_backup", path.resolve()))

    backups_dir = project_dir / "backups"
    if backups_dir.exists():
        for path in sorted(backups_dir.rglob("data.json")):
            sources.append(("project_backup", path.resolve()))

    if desktop.exists():
        for folder in sorted(desktop.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0):
            if not folder.is_dir() or not folder.name.startswith(BACKUP_PREFIX):
                continue
            if folder.name in EXCLUDED_HISTORY_IMPORT_BACKUPS:
                continue
            data_path = folder / "data.json"
            if data_path.exists():
                sources.append(("desktop_backup", data_path.resolve()))

    return sources


def collect_real_stock_history_points(
    *,
    project_dir: str | Path | None = None,
    desktop: str | Path | None = None,
) -> tuple[list[dict], list[dict]]:
    project_path = Path(project_dir).resolve() if project_dir else Path.cwd().resolve()
    desktop_path = Path(desktop).resolve() if desktop else (Path.home() / "Desktop").resolve()
    points_by_hash: dict[str, dict] = {}
    excluded: list[dict] = []

    for source_kind, data_path in _stock_history_sources(project_path, desktop_path):
        data = _read_json_file(data_path)
        if not isinstance(data, dict):
            excluded.append({"source": str(data_path), "reason": "data.json illisible"})
            continue
        captured_at, date_source = _source_datetime(data_path, source_kind)
        if not captured_at:
            excluded.append({"source": str(data_path), "reason": "date de backup ambiguë"})
            continue
        archives_path = data_path.parent / "lots_archives.json"
        archives = _read_json_file(archives_path) if archives_path.exists() else []
        if not isinstance(archives, list):
            archives = []
        source_hash = _state_hash(data_path, archives_path if archives_path.exists() else None)
        point = {
            "captured_at": captured_at.isoformat(timespec="seconds"),
            "value": _stock_value_from_state(data, archives),
            "provenance": "backup",
            "source_label": data_path.parent.name if data_path.name == "data.json" else data_path.name,
            "source_kind": source_kind,
            "date_source": date_source,
            "source_hash": source_hash[:12],
            "lots": len(data.get("lots", []) or []),
            "cards": _count_cards(data),
        }
        current = points_by_hash.get(source_hash)
        if not current or point["date_source"] == "manifest" and current.get("date_source") != "manifest":
            points_by_hash[source_hash] = point

    return sorted(points_by_hash.values(), key=lambda item: item["captured_at"]), excluded


def import_real_stock_history_points(
    *,
    path: str = STOCK_HISTORY_FILE,
    project_dir: str | Path | None = None,
    desktop: str | Path | None = None,
) -> dict:
    payload = load_stock_history(path)
    existing_points = []
    seen_keys = set()

    for point in payload.get("points", []) or []:
        if not isinstance(point, dict):
            continue
        normalized = dict(point)
        normalized["value"] = round(_float_value(normalized.get("value")), 2)
        normalized.setdefault("provenance", "snapshot")
        key = (
            normalized.get("provenance"),
            normalized.get("source_hash") or "",
            normalized.get("captured_at"),
            normalized.get("value"),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        existing_points.append(normalized)

    imported_points, excluded = collect_real_stock_history_points(project_dir=project_dir, desktop=desktop)
    imported_count = 0
    for point in imported_points:
        key = (point.get("provenance"), point.get("source_hash") or "", point.get("captured_at"), point.get("value"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        existing_points.append(point)
        imported_count += 1

    existing_points.sort(key=lambda item: str(item.get("captured_at") or ""))
    payload["points"] = existing_points
    saved = save_stock_history(payload, path)
    return {
        "found": len(imported_points),
        "imported": imported_count,
        "existing_snapshots": sum(1 for point in existing_points if point.get("provenance") == "snapshot"),
        "total_points": len(existing_points),
        "excluded": excluded,
        "saved": saved,
    }


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
    points.append({"captured_at": now.isoformat(timespec="seconds"), "value": value, "provenance": "live"})
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


def stock_double_count_annotation() -> dict:
    """Note affichee sur la courbe (en memoire seulement, jamais ecrite dans le JSON)."""
    return {
        "id": STOCK_DOUBLE_COUNT_NOTE_ID,
        "date": STOCK_DOUBLE_COUNT_FIX_AT[:10],
        "comment": STOCK_DOUBLE_COUNT_NOTE,
        "auto": True,
    }


def _entry_day(raw) -> str:
    return str(raw or "")[:10]


def stored_value_at(lots: list[dict] | None, archives: list[dict] | None, captured_at: str) -> float:
    """Valeur (au prix actuel) des cartes deja mises de cote a `captured_at`.

    Estimation fondee sur `storage_entries` : c'est ce que l'ancienne formule comptait en double.
    Les entrees sont plafonnees a `stored_quantity` (cartes revenues du stockage ignorees).
    """
    day = _entry_day(captured_at)
    total = 0.0
    for lot in list(lots or []) + list(archives or []):
        if lot.get("is_storage") or lot.get("nom") == "Stockage":
            continue
        for card in lot.get("cards", []) or []:
            if card.get("is_collection_keep"):
                continue
            try:
                cap = max(int(card.get("stored_quantity", 0) or 0), 0)
            except (TypeError, ValueError):
                cap = 0
            if cap <= 0:
                continue
            price = _float_value(card.get("suggested_price"))
            taken = 0
            entries = sorted(
                (e for e in (card.get("storage_entries") or []) if isinstance(e, dict)),
                key=lambda e: _entry_day(e.get("date")),
            )
            for entry in entries:
                if taken >= cap:
                    break
                try:
                    qty = max(int(entry.get("quantity", 0) or 0), 0)
                except (TypeError, ValueError):
                    qty = 0
                qty = min(qty, cap - taken)
                taken += qty
                entry_day = _entry_day(entry.get("date"))
                if entry_day and entry_day <= day:
                    total += qty * price
    return round(total, 2)


@functools.lru_cache(maxsize=4)
def _recomputed_values_cached(signature: tuple, wanted: frozenset) -> dict:
    """Valeur corrigee des data.json encore presents, indexee par empreinte ou par `label:<nom du backup>`.

    L'empreinte peut ne plus correspondre (lots_archives.json a change depuis) : le nom du backup sert alors de repli.
    """
    values: dict[str, float] = {}
    for _kind, path_str in signature:
        data_path = Path(path_str)
        try:
            label = "label:" + (data_path.parent.name if data_path.name == "data.json" else data_path.name)
            archives_path = data_path.parent / "lots_archives.json"
            digest = _state_hash(data_path, archives_path if archives_path.exists() else None)[:12]
            if digest not in wanted and label not in wanted:
                continue
            data = _read_json_file(data_path)
            if not isinstance(data, dict):
                continue
            archives = _read_json_file(archives_path) if archives_path.exists() else []
            value = _stock_value_from_state(data, archives if isinstance(archives, list) else [])
            if digest in wanted:
                values[digest] = value
            if label in wanted:
                values.setdefault(label, value)
        except OSError:
            continue
    return values


def _recomputed_values_by_hash(project_dir, desktop, wanted: set) -> dict:
    if not wanted:
        return {}
    try:
        sources = _stock_history_sources(
            Path(project_dir).resolve() if project_dir else None,
            Path(desktop).resolve() if desktop else None,
        )
        signature = tuple((kind, str(path)) for kind, path in sources)
    except OSError:
        return {}
    return _recomputed_values_cached(signature, frozenset(wanted))


def corrected_stock_history_points(
    points: list[dict] | None,
    *,
    lots: list[dict] | None,
    archives: list[dict] | None = None,
    project_dir: str | Path | None = None,
    desktop: str | Path | None = None,
    fix_at: str | None = None,
) -> tuple[list[dict], dict]:
    """Copie des points de la courbe avec le double comptage des cartes stockees retire.

    AFFICHAGE UNIQUEMENT : la liste d'entree et le fichier JSON ne sont jamais modifies.
    - points posterieurs a `fix_at` : deja calcules avec la formule corrigee, inchanges ;
    - points « backup » dont le data.json d'origine existe encore : recalcules avec la formule corrigee ;
    - autres points : valeur moins la valeur stockee cumulee estimee (`stored_value_at`).
    Chaque point corrige porte `value_correction` = "recalcule" ou "estime" et `value_original`.
    """
    fix_at = fix_at or STOCK_DOUBLE_COUNT_FIX_AT
    source = [dict(point) for point in (points or []) if isinstance(point, dict)]
    wanted = set()
    for point in source:
        if point.get("provenance") == "backup" and str(point.get("captured_at") or "") < fix_at:
            if point.get("source_hash"):
                wanted.add(str(point.get("source_hash")))
            if point.get("source_label"):
                wanted.add("label:" + str(point.get("source_label")))
    recomputed = _recomputed_values_by_hash(project_dir, desktop, wanted)
    info = {"recalcule": 0, "estime": 0, "inchange": 0}
    corrected: list[dict] = []
    for point in source:
        captured = str(point.get("captured_at") or "")
        if not captured or captured >= fix_at:
            info["inchange"] += 1
            corrected.append(point)
            continue
        original = round(_float_value(point.get("value")), 2)
        new_value = None
        mode = ""
        digest = str(point.get("source_hash") or "")
        label_key = "label:" + str(point.get("source_label") or "")
        if point.get("provenance") == "backup" and (digest in recomputed or label_key in recomputed):
            new_value = recomputed[digest] if digest in recomputed else recomputed[label_key]
            mode = "recalcule"
        else:
            delta = stored_value_at(lots, archives, captured)
            if delta > 0:
                new_value, mode = round(max(original - delta, 0.0), 2), "estime"
        if new_value is None or new_value == original:
            info["inchange"] += 1
            corrected.append(point)
            continue
        point["value"] = new_value
        point["value_original"] = original
        point["value_correction"] = mode
        info[mode] += 1
        corrected.append(point)
    return corrected, info

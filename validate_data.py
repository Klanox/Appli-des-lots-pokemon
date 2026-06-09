"""Non-destructive data validator for Pokestock.

This script only reads data.json and referenced local image files.
It never writes, repairs, deletes, or syncs data.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "data.json"
EXPECTED_LOTS = 19

SYSTEM_LOTS = {
    "collection": ("is_collection_lot", {"Collection", "🧾 Collection"}),
    "trade": ("is_trade", {"Trade", "🔄 Trade"}),
    "storage": ("is_storage", {"Stockage", "📈 Stockage"}),
    "divers": ("is_divers", {"Divers", "🗂️ Divers"}),
}

NUMERIC_CARD_FIELDS = {
    "quantity",
    "sold_quantity",
    "stored_quantity",
    "suggested_price",
    "purchase_price",
    "collection_purchase_price",
    "collection_current_value",
    "current_value",
    "real_value",
}

NUMERIC_LOT_FIELDS = {
    "prix_achat",
    "prix_achat_reel",
    "valeur_totale",
    "valeur_a_vendre",
}


def is_number(value) -> bool:
    if value in (None, ""):
        return True
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def local_path_exists(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    path = Path(text)
    if not path.is_absolute():
        path = APP_DIR / path
    return path.exists()


def system_lot_kind(lot: dict) -> str | None:
    name = str(lot.get("nom", "") or "").strip()
    for kind, (flag, names) in SYSTEM_LOTS.items():
        if lot.get(flag) or name in names:
            return kind
    return None


def validate() -> tuple[list[str], list[str], dict]:
    errors: list[str] = []
    warnings: list[str] = []
    summary = {
        "lots": 0,
        "cards": 0,
        "collection_lots": 0,
    }

    if not DATA_FILE.exists():
        return [f"data.json introuvable: {DATA_FILE}"], warnings, summary

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return [f"data.json invalide: {exc}"], warnings, summary

    if not isinstance(data, dict):
        return ["data.json doit contenir un objet JSON a la racine."], warnings, summary

    lots = data.get("lots")
    if "lots" not in data:
        errors.append("Cle 'lots' manquante.")
        lots = []
    elif not isinstance(lots, list):
        errors.append("La cle 'lots' doit etre une liste.")
        lots = []

    summary["lots"] = len(lots)
    if len(lots) != EXPECTED_LOTS:
        errors.append(f"Nombre de lots inattendu: {len(lots)} au lieu de {EXPECTED_LOTS}.")

    system_counts = {kind: 0 for kind in SYSTEM_LOTS}

    for lot_idx, lot in enumerate(lots):
        if not isinstance(lot, dict):
            errors.append(f"Lot #{lot_idx}: doit etre un objet.")
            continue

        lot_name = str(lot.get("nom", "") or "").strip()
        if not lot_name:
            errors.append(f"Lot #{lot_idx}: nom vide.")

        kind = system_lot_kind(lot)
        if kind:
            system_counts[kind] += 1

        for field in NUMERIC_LOT_FIELDS:
            if field in lot and not is_number(lot.get(field)):
                errors.append(f"Lot '{lot_name}' #{lot_idx}: champ numerique invalide '{field}'.")

        cards = lot.get("cards")
        if cards is None:
            warnings.append(f"Lot '{lot_name}' #{lot_idx}: cle cards absente, consideree vide par l'app.")
            cards = []
        elif not isinstance(cards, list):
            errors.append(f"Lot '{lot_name}' #{lot_idx}: cards doit etre une liste.")
            cards = []

        for card_idx, card in enumerate(cards):
            summary["cards"] += 1
            if not isinstance(card, dict):
                errors.append(f"Lot '{lot_name}' carte #{card_idx}: doit etre un objet.")
                continue

            card_name = str(card.get("name", "") or "").strip()
            if not card_name:
                errors.append(f"Lot '{lot_name}' carte #{card_idx}: name manquant.")

            for field in NUMERIC_CARD_FIELDS:
                if field in card and not is_number(card.get(field)):
                    errors.append(f"Carte '{card_name}' ({lot_name}): champ numerique invalide '{field}'.")

            for qty_field in ("quantity", "sold_quantity", "stored_quantity"):
                if qty_field in card and as_int(card.get(qty_field), 0) < 0:
                    errors.append(f"Carte '{card_name}' ({lot_name}): quantite negative '{qty_field}'.")

            if card.get("is_collection_keep"):
                if "collection_purchase_price" in card and not is_number(card.get("collection_purchase_price")):
                    errors.append(f"Carte Collection '{card_name}': collection_purchase_price invalide.")
                if "collection_current_value" in card and not is_number(card.get("collection_current_value")):
                    errors.append(f"Carte Collection '{card_name}': collection_current_value invalide.")
                if card.get("manual_image_path") and not local_path_exists(card.get("manual_image_path")):
                    errors.append(f"Carte Collection '{card_name}': manual_image_path introuvable: {card.get('manual_image_path')}")

    summary["collection_lots"] = system_counts["collection"]
    for kind, count in system_counts.items():
        if count == 0:
            warnings.append(f"Lot systeme absent: {kind}.")
        elif count > 1:
            errors.append(f"Lot systeme duplique: {kind} ({count}).")

    return errors, warnings, summary


def main() -> int:
    errors, warnings, summary = validate()
    print("=== Pokestock data validator ===")
    print(f"File: {DATA_FILE}")
    print(f"Lots: {summary['lots']}")
    print(f"Cards: {summary['cards']}")
    print(f"System Collection lots: {summary['collection_lots']}")

    if warnings:
        print("\nWARNINGS:")
        for item in warnings:
            print(f"- {item}")

    if errors:
        print("\nERRORS:")
        for item in errors:
            print(f"- {item}")
        print("\nRESULT: FAILED")
        return 1

    print("\nRESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

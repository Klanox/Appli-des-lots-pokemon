"""Collection actions extracted from app.py.

These functions preserve the existing Collection behavior while receiving
data-writing dependencies as parameters.
"""

from datetime import datetime
import os
import re
import uuid

import requests

from core.collection import (
    collection_current_value,
    collection_purchase_price,
    is_collection_system_lot,
    same_collection_card,
)


def add_or_merge_collection_card(cd, lot_idx, new_card):
    lot = cd["lots"][lot_idx]
    if not is_collection_system_lot(lot) or not new_card.get("is_collection_keep"):
        lot.setdefault("cards", []).append(new_card)
        return "added"

    for existing in lot.setdefault("cards", []):
        if existing.get("is_collection_keep") and same_collection_card(existing, new_card):
            old_qty = max(int(existing.get("quantity", 0) or 0), 1)
            new_qty = max(int(new_card.get("quantity", 1) or 1), 1)
            merged_qty = old_qty + new_qty
            old_paid_total = collection_purchase_price(existing) * old_qty
            new_paid_total = collection_purchase_price(new_card) * new_qty
            old_value_total = collection_current_value(existing) * old_qty
            new_value_total = collection_current_value(new_card) * new_qty
            existing["quantity"] = merged_qty
            if not existing.get("image_url") and new_card.get("image_url"):
                existing["image_url"] = new_card.get("image_url")
            if not existing.get("image_url_en") and new_card.get("image_url_en"):
                existing["image_url_en"] = new_card.get("image_url_en")
            for list_key in ("sold_entries", "price_history"):
                merged_list = []
                merged_list.extend(existing.get(list_key, []) or [])
                merged_list.extend(new_card.get(list_key, []) or [])
                existing[list_key] = merged_list
            existing["collection_current_value"] = (old_value_total + new_value_total) / merged_qty if merged_qty else 0.
            existing["collection_purchase_price"] = (old_paid_total + new_paid_total) / merged_qty if merged_qty else 0.
            existing["purchase_price"] = existing["collection_purchase_price"]
            existing["suggested_price"] = existing["collection_current_value"]
            return "merged"

    lot["cards"].append(new_card)
    return "added"


def get_or_create_collection_lot(cd):
    for lot_idx, lot in enumerate(cd.get("lots", [])):
        if is_collection_system_lot(lot):
            return lot_idx
    cd.setdefault("lots", []).append({
        "nom": "🧾 Collection",
        "prix_achat": 0.,
        "cards": [],
        "ventes": [],
        "created": datetime.now().isoformat(),
        "is_collection_lot": True,
    })
    return len(cd["lots"]) - 1


def add_direct_collection_card(
    *,
    collection_name,
    collection_number,
    collection_qty,
    collection_value,
    collection_paid,
    collection_reverse,
    collection_ed1,
    collection_jp,
    collection_special_tag,
    ld_func,
    sd_func,
    acm_func,
):
    cd_add_collection = ld_func()
    before_lots = len(cd_add_collection.get("lots", []))
    collection_lot_ix = get_or_create_collection_lot(cd_add_collection)
    if len(cd_add_collection.get("lots", [])) != before_lots:
        sd_func(cd_add_collection)

    return acm_func(
        collection_lot_ix,
        collection_name,
        "",
        collection_number,
        collection_qty,
        "NM",
        collection_value,
        collection_reverse,
        collection_ed1,
        lang="ja" if collection_jp else "fr",
        purchase_price=collection_paid,
        special_tag=collection_special_tag,
        collection_keep=True,
    )


def delete_collection_card_from_system(lot_idx, card_idx, card_uid, *, ld_func, sd_func, backup_func):
    backup_dir, _ = backup_func("before_collection_card_delete")
    cd_delete = ld_func()
    if lot_idx < len(cd_delete.get("lots", [])):
        target_lot = cd_delete["lots"][lot_idx]
        if is_collection_system_lot(target_lot) and card_idx < len(target_lot.get("cards", [])):
            target_card = target_lot["cards"][card_idx]
            target_uid = str(target_card.get("card_uid") or target_card.get("id") or f"{lot_idx}_{card_idx}")
            if target_uid == str(card_uid):
                target_lot["cards"].pop(card_idx)
                sd_func(cd_delete)
                return True, f"Carte supprimée. Sauvegarde : {backup_dir}"
            return False, "La carte a changé d'emplacement. Recharge la page puis réessaie."
    return False, "Carte introuvable."


def remove_collection_status_from_lot(lot_idx, card_idx, card_uid, *, ld_func, sd_func, backup_func):
    backup_dir, _ = backup_func("before_collection_status_remove")
    cd_unkeep = ld_func()
    if lot_idx < len(cd_unkeep.get("lots", [])):
        target_lot = cd_unkeep["lots"][lot_idx]
        if (not is_collection_system_lot(target_lot)) and card_idx < len(target_lot.get("cards", [])):
            target_card = target_lot["cards"][card_idx]
            target_uid = str(target_card.get("card_uid") or target_card.get("id") or f"{lot_idx}_{card_idx}")
            if target_uid == str(card_uid):
                target_card["is_collection_keep"] = False
                sd_func(cd_unkeep)
                return True, f"Statut Collection retiré. Sauvegarde : {backup_dir}"
            return False, "La carte a changé d'emplacement. Recharge la page puis réessaie."
    return False, "Carte introuvable."


def manual_image_url_is_valid(url):
    url = str(url or "").strip()
    if not url:
        return False
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        return False
    try:
        response = requests.head(url, timeout=4, allow_redirects=True)
        content_type = response.headers.get("content-type", "").lower()
        if response.status_code == 200 and content_type.startswith("image/"):
            return True
    except Exception:
        pass
    try:
        response = requests.get(url, timeout=5, stream=True, allow_redirects=True)
        content_type = response.headers.get("content-type", "").lower()
        return response.status_code == 200 and content_type.startswith("image/")
    except Exception:
        return False


def save_collection_manual_image(
    lot_idx,
    card_idx,
    card_uid,
    *,
    ld_func,
    sd_func,
    backup_func,
    manual_url="",
    uploaded_file=None,
    clear_manual=False,
):
    cd_manual = ld_func()
    if lot_idx >= len(cd_manual.get("lots", [])):
        return False, "Lot introuvable."
    lot = cd_manual["lots"][lot_idx]
    if card_idx >= len(lot.get("cards", [])):
        return False, "Carte introuvable."

    card = lot["cards"][card_idx]
    target_uid = str(card.get("card_uid") or card.get("id") or f"{lot_idx}_{card_idx}")
    if target_uid != str(card_uid):
        return False, "La carte a changé d'emplacement. Recharge la page puis réessaie."

    backup_dir, _ = backup_func("before_collection_manual_image")

    if clear_manual:
        card.pop("manual_image_path", None)
        card.pop("manual_image_url", None)
        sd_func(cd_manual)
        return True, f"Image manuelle supprimée. Sauvegarde : {backup_dir}"

    manual_url = str(manual_url or "").strip()
    if manual_url:
        if not manual_image_url_is_valid(manual_url):
            return False, "Cette URL ne semble pas pointer vers une image valide."
        card["manual_image_url"] = manual_url
        card.pop("manual_image_path", None)
        sd_func(cd_manual)
        return True, f"Image URL enregistrée. Sauvegarde : {backup_dir}"

    if uploaded_file is not None:
        ext = os.path.splitext(uploaded_file.name or "")[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = ".png"
        safe_uid = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(card_uid or uuid.uuid4().hex))
        image_dir = os.path.join("card_images", "collection")
        os.makedirs(image_dir, exist_ok=True)
        target_path = os.path.join(image_dir, f"{safe_uid}{ext}")
        with open(target_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        card["manual_image_path"] = target_path.replace("\\", "/")
        card.pop("manual_image_url", None)
        sd_func(cd_manual)
        return True, f"Image uploadée. Sauvegarde : {backup_dir}"

    return False, "Choisis une image ou colle une URL."

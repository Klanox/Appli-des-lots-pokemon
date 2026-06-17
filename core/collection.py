"""Pure Collection helpers.

These helpers only inspect card/lot dictionaries and return calculated values.
They do not read or write files, call Streamlit, or perform network requests.
"""

from utils import normalize_name


import os

COLLECTION_IMAGE_PLACEHOLDER = "__placeholder__"


def is_collection_system_lot(lot):
    return lot.get("is_collection_lot") or lot.get("nom") in ("Collection", "🧾 Collection")


def collection_current_value(card):
    return float(
        card.get(
            "collection_current_value",
            card.get(
                "current_value",
                card.get(
                    "real_value",
                    card.get("suggested_price", 0.),
                ),
            ),
        ) or 0.
    )


def collection_purchase_price(card):
    qty = max(int(card.get("quantity", 1) or 1), 1)
    if card.get("collection_purchase_total") not in (None, ""):
        return float(card.get("collection_purchase_total") or 0.) / qty
    return float(
        card.get(
            "collection_purchase_price",
            card.get(
                "purchase_price",
                card.get("pa_carte", 0.),
            ),
        ) or 0.
    )


def collection_paid_total(card, lot, *, calc_cout_lot_func=None, effective_purchase_price_func=None):
    """Total paid price for a Collection card, direct or estimated from its lot."""
    qty = max(int(card.get("quantity", 1) or 1), 1)
    if card.get("collection_purchase_total") not in (None, ""):
        return float(card.get("collection_purchase_total") or 0.)
    explicit = collection_purchase_price(card)

    if is_collection_system_lot(lot):
        return explicit * qty

    if lot.get("is_divers") and explicit > 0:
        return explicit * qty

    card_value_unit = collection_current_value(card) or float(card.get("suggested_price", 0.) or 0.)
    card_value_total = card_value_unit * qty
    if card_value_total <= 0:
        return explicit * qty if explicit > 0 else 0.

    try:
        if lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
            real_price = float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
            return (card_value_total / float(lot.get("valeur_totale", 1.) or 1.)) * real_price

        if calc_cout_lot_func is not None and effective_purchase_price_func is not None:
            _, valeur_estimee = calc_cout_lot_func(lot)
            prix_lot = effective_purchase_price_func(lot)
            if valeur_estimee and prix_lot > 0:
                return (card_value_total / valeur_estimee) * prix_lot
    except Exception:
        pass

    return explicit * qty if explicit > 0 else 0.


def same_collection_card(a, b):
    keys = ("name", "number", "set", "condition", "special_tag")
    for key in keys:
        if normalize_name(a.get(key, "")) != normalize_name(b.get(key, "")):
            return False
    return (
        bool(a.get("is_reverse")) == bool(b.get("is_reverse"))
        and bool(a.get("is_ed1")) == bool(b.get("is_ed1"))
        and str(a.get("lang", "fr")) == str(b.get("lang", "fr"))
    )


def collection_card_exact_match(target_card, candidate_card, candidate_set=""):
    target_name = normalize_name(target_card.get("name", ""))
    candidate_name = normalize_name(candidate_card.get("name", ""))
    if not target_name or candidate_name != target_name:
        return False

    target_num = str(target_card.get("number", "") or "").strip()
    candidate_num = str(candidate_card.get("localId", "") or candidate_card.get("number", "") or "").strip()
    if target_num:
        if not candidate_num:
            return False
        if not (
            candidate_num == target_num
            or candidate_num.zfill(3) == target_num.zfill(3)
            or target_num.zfill(3) == candidate_num.zfill(3)
        ):
            return False

    target_id = str(target_card.get("id", "") or "").strip()
    candidate_id = str(candidate_card.get("id", "") or "").strip()
    if target_id and candidate_id and target_id == candidate_id:
        return True

    target_set = normalize_name(target_card.get("set", ""))
    candidate_set_norm = normalize_name(candidate_set)
    if target_set and candidate_set_norm:
        return target_set == candidate_set_norm or target_set in candidate_set_norm or candidate_set_norm in target_set

    return not target_set


def collection_has_manual_image(card):
    manual_path = str(card.get("manual_image_path", "") or "").strip()
    manual_url = str(card.get("manual_image_url", "") or "").strip()
    return bool((manual_path and os.path.exists(manual_path)) or manual_url)


def collection_uses_placeholder(card):
    return str(card.get("resolved_collection_image_url", "") or "").strip() == COLLECTION_IMAGE_PLACEHOLDER


def collection_image_needs_manual(card):
    manual_path = str(card.get("manual_image_path", "") or "").strip()
    if manual_path and not os.path.exists(manual_path):
        return True
    if collection_has_manual_image(card):
        return False
    if collection_uses_placeholder(card):
        return True
    for key in ("resolved_collection_image_url", "image_url", "image_url_en", "local_image", "image_path", "photo_path"):
        if str(card.get(key, "") or "").strip():
            return False
    return True

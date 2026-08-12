"""Supplier tracking logic for AR / CHR sourcing.

This module is local-only business logic. It does not call external services and
does not read or write application datasets.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from difflib import SequenceMatcher
import hashlib
import re
import unicodedata
import uuid


SUPPLIER_STATUSES = [
    "À contacter",
    "en attente",
    "actif",
    "testé",
    "top fournisseur",
    "À éviter",
    "archivé",
]

SUPPLIER_TYPES = ["Japon", "France", "Europe", "Autre"]
SUPPLIER_CURRENCIES = ["EUR", "JPY", "USD", "Autre"]
PAYPAL_STATES = ["oui", "non", "inconnu"]
CARD_STATES = ["inconnu", "Near Mint", "Excellent", "Mixed", "? v?rifier"]
DUPLICATE_STATES = ["inconnu", "peu", "moyen", "beaucoup"]
MEDIA_STATES = ["oui", "non", "partiel", "inconnu"]
TRACKING_STATES = ["oui", "non", "inconnu"]
SUPPLIER_SPECIALTIES = [
    "AR mid",
    "AR high",
    "CHR",
    "Lots mixtes",
    "Grosses quantit?s",
    "Promos",
    "Cartes japonaises",
    "Cartes fran?aises",
    "Autre",
]
BIG_QUANTITY_STATES = ["oui", "non", "inconnu"]
NEGOTIATION_ACTORS = ["supplier", "me", "system", "unknown"]
NEGOTIATION_EVENT_TYPES = ["supplier_offer", "my_offer", "agreement", "refusal", "negotiation_note"]
MESSAGE_AUTHORS = ["me", "supplier", "note", "unknown"]
CONVERSATION_TAGS = [
    "prix",
    "paiement",
    "PayPal",
    "photos",
    "vid?o",
    "tracking",
    "?tat",
    "qualit?",
    "doublons",
    "retard",
    "livraison",
    "accord",
    "probl?me",
    "autre",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str = "supplier") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return text


def normalize_supplier_identity(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^\w\s]+", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "", text)
    return text


def supplier_identity_similarity(left: str, right: str) -> float:
    left_key = normalize_supplier_identity(left)
    right_key = normalize_supplier_identity(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    left_tokens = set(normalize_text(left).replace(".", " ").replace("-", " ").split())
    right_tokens = set(normalize_text(right).replace(".", " ").replace("-", " ").split())
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens) if left_tokens and right_tokens else 0.0
    return max(token_score, SequenceMatcher(None, left_key, right_key).ratio())


def import_hash(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def infer_supplier_family(name: str) -> tuple[str, str]:
    display = str(name or "").strip()
    low = normalize_text(display)
    if "prime tcg wholesale" in low or "tcg wholesale" == low:
        return "Prime TCG Wholesale", "primetcgwholesale"
    return display, normalize_supplier_identity(display)


def infer_offer_variant(name: str) -> str:
    low = normalize_text(name)
    if "random bulk" in low or ("tcg wholesale" == low):
        return "random bulk"
    if "cartes choisies" in low or "chosen" in low or "selected" in low:
        return "cartes choisies"
    return ""


def parse_number(value, default=None):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    text = text.replace("\u202f", " ").replace("\xa0", " ")
    text = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", text)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    text = text.replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def default_suppliers_data() -> dict:
    return {
        "schema_version": 1,
        "settings": {
            "conversion_rates": {
                "JPY": {"rate_to_eur": 0.0062, "updated_at": ""},
                "USD": {"rate_to_eur": 0.92, "updated_at": ""},
            },
            "resale_scenario": "reference",
            "custom_resale_per_card_eur": 3.0,
        },
        "suppliers": [],
        "review_history": [],
        "ignored_duplicate_pairs": [],
    }


def default_supplier() -> dict:
    created = now_iso()
    return {
        "id": new_id(),
        "created_at": created,
        "updated_at": created,
        "nom": "",
        "pays": "",
        "contact_link": "",
        "type": "Autre",
        "supplier_family_name": "",
        "supplier_family_key": "",
        "offer_variant": "",
        "preferred_offer_variant": "",
        "supplier_aliases": [],
        "follow_status": "À contacter",
        "last_interaction_at": "",
        "follow_up_date": "",
        "follow_up_note": "",
        "review_history": [],
        "last_review_summary": "",
        "last_review_at": "",
        "last_review_type": "",
        "last_review_result": "",
        "test_order_checklist": [],
        "prix_100": None,
        "prix_200": None,
        "price_status": "",
        "quantity_reference": 200,
        "cards_price_source": None,
        "cards_price_source_currency": "",
        "shipping_price_source": None,
        "shipping_price_source_currency": "",
        "shipping_status": "",
        "paypal_fee_source": None,
        "paypal_fee_source_currency": "",
        "paypal_fee_percent": None,
        "supplier_total_source": None,
        "supplier_total_source_currency": "",
        "landed_cost_estimated_source": None,
        "landed_cost_estimated_currency": "",
        "conversion_rate_date": "",
        "cards_price_eur": None,
        "shipping_price_eur": None,
        "paypal_fee_eur": None,
        "supplier_total_eur": None,
        "import_tax_eur": None,
        "customs_fee_eur": None,
        "file_fee_eur": None,
        "landed_cost_estimated_min_eur": None,
        "landed_cost_estimated_max_eur": None,
        "landed_cost_estimated_eur": None,
        "landed_cost_per_card_min_eur": None,
        "landed_cost_per_card_max_eur": None,
        "landed_cost_per_card_eur": None,
        "estimated_resale_total_eur": None,
        "estimated_resale_per_card_eur": None,
        "purchase_percentage_of_resale": None,
        "purchase_percentage_of_resale_min": None,
        "purchase_percentage_of_resale_max": None,
        "estimated_margin_eur": None,
        "estimated_margin_min_eur": None,
        "estimated_margin_max_eur": None,
        "estimated_margin_percent": None,
        "estimated_margin_percent_min": None,
        "estimated_margin_percent_max": None,
        "cost_notes": "",
        "latest_offer": None,
        "latest_offer_amount": None,
        "latest_offer_currency": "",
        "latest_offer_quantity": None,
        "latest_offer_shipping_included": False,
        "latest_offer_quantity_inferred": False,
        "devise": "EUR",
        "port": 0.0,
        "paiement": "",
        "paypal_gs": "inconnu",
        "frais_paypal": 0.0,
        "frais_paypal_fixed": None,
        "frais_paypal_percent": None,
        "tva_import_active": False,
        "tva_import_rate": 0.0,
        "frais_import": 0.0,
        "frais_dossier": 0.0,
        "etat": "inconnu",
        "doublons": "inconnu",
        "photos_video": "inconnu",
        "tracking": "inconnu",
        "valeur_lot_estimee": None,
        "prix_final_estime": None,
        "prix_unitaire_estime": None,
        "conversion_rate_to_eur": 1.0,
        "prix_final_eur": None,
        "prix_unitaire_eur": None,
        "confiance_note": None,
        "service_note": None,
        "contenu_note": None,
        "potentiel_negociation_note": None,
        "negotiation_note": "",
        "pros": [],
        "cons": [],
        "derniere_analyse": "",
        "action_recommandee": "",
        "analysis_updated_at": "",
        "market_position": "",
        "market_position_rank": None,
        "best_for": "",
        "best_for_tags": [],
        "risk_level": "unknown",
        "recommended_first_order": "",
        "recommended_first_order_quantity": None,
        "review_last_updated": "",
        "notes": "",
        "statut": "À contacter",
        "offers_history": [],
        "price_history": [],
        "import_history": [],
        "specialites": [],
        "grosses_quantites_confirmees": "inconnu",
        "quantite_minimum": None,
        "negotiation_history": [],
        "conversation_history": [],
    }


def normalize_tags(values) -> list[str]:
    if not isinstance(values, list):
        if not values:
            return []
        values = [values]
    result = []
    allowed_normalized = {normalize_text(tag): tag for tag in CONVERSATION_TAGS}
    for value in values:
        text = str(value or "").strip()
        key = normalize_text(text)
        if key in allowed_normalized:
            tag = allowed_normalized[key]
        elif text:
            tag = "autre"
        else:
            continue
        if tag not in result:
            result.append(tag)
    return result


def normalize_negotiation_event(raw: dict | None) -> dict:
    raw = raw or {}
    created = str(raw.get("created_at") or now_iso())
    quantity = parse_number(raw.get("quantity"), None)
    amount = parse_number(raw.get("amount"), None)
    conversion = parse_number(raw.get("conversion_rate_to_eur"), None)
    currency = raw.get("currency") if raw.get("currency") in SUPPLIER_CURRENCIES else "EUR"
    amount_eur = parse_number(raw.get("amount_eur"), None)
    unit_price_eur = parse_number(raw.get("unit_price_eur"), None)
    if amount is not None and currency == "EUR":
        amount_eur = amount
    elif amount is not None and conversion and conversion > 0:
        amount_eur = amount * conversion
    if amount_eur is not None and quantity and quantity > 0:
        unit_price_eur = amount_eur / quantity
    return {
        "id": str(raw.get("id") or new_id("neg_event")),
        "negotiation_id": str(raw.get("negotiation_id") or new_id("neg")),
        "event_date": str(raw.get("event_date") or now_iso()[:10]),
        "created_at": created,
        "updated_at": str(raw.get("updated_at") or created),
        "actor": raw.get("actor") if raw.get("actor") in NEGOTIATION_ACTORS else "unknown",
        "event_type": raw.get("event_type") if raw.get("event_type") in NEGOTIATION_EVENT_TYPES else "negotiation_note",
        "quantity": quantity,
        "amount": amount,
        "currency": currency,
        "conversion_rate_to_eur": conversion,
        "amount_eur": amount_eur,
        "unit_price_eur": unit_price_eur,
        "offer_history_id": str(raw.get("offer_history_id") or ""),
        "payment_terms": str(raw.get("payment_terms") or ""),
        "notes": str(raw.get("notes") or ""),
        "tags": normalize_tags(raw.get("tags") or []),
    }


def normalize_conversation_message(raw: dict | None) -> dict:
    raw = raw or {}
    created = str(raw.get("created_at") or now_iso())
    return {
        "id": str(raw.get("id") or new_id("msg")),
        "message_date": str(raw.get("message_date") or now_iso()[:10]),
        "created_at": created,
        "updated_at": str(raw.get("updated_at") or created),
        "author": raw.get("author") if raw.get("author") in MESSAGE_AUTHORS else "unknown",
        "content": str(raw.get("content") or ""),
        "tags": normalize_tags(raw.get("tags") or []),
        "linked_negotiation_id": str(raw.get("linked_negotiation_id") or ""),
        "linked_offer_history_id": str(raw.get("linked_offer_history_id") or ""),
        "source_type": str(raw.get("source_type") or "manual"),
        "source_text": str(raw.get("source_text") or ""),
    }


def normalize_supplier(raw: dict | None) -> dict:
    supplier = default_supplier()
    if isinstance(raw, dict):
        supplier.update(raw)
    supplier["id"] = str(supplier.get("id") or new_id())
    supplier["created_at"] = str(supplier.get("created_at") or now_iso())
    supplier["updated_at"] = str(supplier.get("updated_at") or supplier["created_at"])
    supplier["type"] = supplier.get("type") if supplier.get("type") in SUPPLIER_TYPES else "Autre"
    supplier["devise"] = supplier.get("devise") if supplier.get("devise") in SUPPLIER_CURRENCIES else "Autre"
    supplier["paypal_gs"] = supplier.get("paypal_gs") if supplier.get("paypal_gs") in PAYPAL_STATES else "inconnu"
    supplier["etat"] = supplier.get("etat") if supplier.get("etat") in CARD_STATES else "inconnu"
    supplier["doublons"] = supplier.get("doublons") if supplier.get("doublons") in DUPLICATE_STATES else "inconnu"
    supplier["photos_video"] = supplier.get("photos_video") if supplier.get("photos_video") in MEDIA_STATES else "inconnu"
    supplier["tracking"] = supplier.get("tracking") if supplier.get("tracking") in TRACKING_STATES else "inconnu"
    supplier["statut"] = supplier.get("statut") if supplier.get("statut") in SUPPLIER_STATUSES else "À contacter"
    supplier["specialites"] = [
        item for item in (supplier.get("specialites") or [])
        if item in SUPPLIER_SPECIALTIES
    ] if isinstance(supplier.get("specialites"), list) else []
    supplier["grosses_quantites_confirmees"] = (
        supplier.get("grosses_quantites_confirmees")
        if supplier.get("grosses_quantites_confirmees") in BIG_QUANTITY_STATES
        else "inconnu"
    )
    for field in [
        "prix_100",
        "prix_200",
        "latest_offer",
        "latest_offer_amount",
        "latest_offer_quantity",
        "quantity_reference",
        "cards_price_source",
        "shipping_price_source",
        "paypal_fee_source",
        "paypal_fee_percent",
        "supplier_total_source",
        "landed_cost_estimated_source",
        "cards_price_eur",
        "shipping_price_eur",
        "paypal_fee_eur",
        "supplier_total_eur",
        "import_tax_eur",
        "customs_fee_eur",
        "file_fee_eur",
        "landed_cost_estimated_min_eur",
        "landed_cost_estimated_max_eur",
        "landed_cost_estimated_eur",
        "landed_cost_per_card_min_eur",
        "landed_cost_per_card_max_eur",
        "landed_cost_per_card_eur",
        "estimated_resale_total_eur",
        "estimated_resale_per_card_eur",
        "purchase_percentage_of_resale",
        "purchase_percentage_of_resale_min",
        "purchase_percentage_of_resale_max",
        "estimated_margin_eur",
        "estimated_margin_min_eur",
        "estimated_margin_max_eur",
        "estimated_margin_percent",
        "estimated_margin_percent_min",
        "estimated_margin_percent_max",
        "port",
        "frais_paypal",
        "frais_paypal_fixed",
        "frais_paypal_percent",
        "tva_import_rate",
        "frais_import",
        "frais_dossier",
        "valeur_lot_estimee",
        "conversion_rate_to_eur",
        "confiance_note",
        "service_note",
        "contenu_note",
        "potentiel_negociation_note",
        "quantite_minimum",
        "market_position_rank",
        "recommended_first_order_quantity",
    ]:
        supplier[field] = parse_number(supplier.get(field), None)
    for note_field in [
        "notes",
        "negotiation_note",
        "derniere_analyse",
        "action_recommandee",
        "analysis_updated_at",
        "market_position",
        "best_for",
        "recommended_first_order",
        "review_last_updated",
        "supplier_family_name",
        "supplier_family_key",
        "offer_variant",
        "preferred_offer_variant",
        "follow_status",
        "last_interaction_at",
        "follow_up_date",
        "follow_up_note",
        "last_review_summary",
        "last_review_at",
        "last_review_type",
        "last_review_result",
        "price_status",
        "cards_price_source_currency",
        "shipping_price_source_currency",
        "shipping_status",
        "paypal_fee_source_currency",
        "supplier_total_source_currency",
        "landed_cost_estimated_currency",
        "conversion_rate_date",
        "cost_notes",
    ]:
        supplier[note_field] = str(supplier.get(note_field) or "")
    risk_level = normalize_text(supplier.get("risk_level", "unknown"))
    supplier["risk_level"] = risk_level if risk_level in {"low", "medium", "high", "unknown"} else "unknown"
    for list_field in ["pros", "cons", "best_for_tags", "supplier_aliases"]:
        value = supplier.get(list_field)
        if isinstance(value, list):
            supplier[list_field] = [str(item).strip() for item in value if str(item).strip()]
        elif value:
            supplier[list_field] = [str(value).strip()]
        else:
            supplier[list_field] = []
    source_currency_hint = (
        supplier.get("supplier_total_source_currency")
        or supplier.get("cards_price_source_currency")
        or supplier.get("devise")
    )
    if supplier["devise"] == "EUR" and source_currency_hint in {"", "EUR", None}:
        supplier["conversion_rate_to_eur"] = 1.0
    supplier["tva_import_active"] = bool(supplier.get("tva_import_active"))
    supplier["latest_offer_shipping_included"] = bool(supplier.get("latest_offer_shipping_included"))
    supplier["latest_offer_quantity_inferred"] = bool(supplier.get("latest_offer_quantity_inferred"))
    supplier["latest_offer_currency"] = supplier.get("latest_offer_currency") if supplier.get("latest_offer_currency") in SUPPLIER_CURRENCIES else ""
    family_name, family_key = infer_supplier_family(supplier.get("supplier_family_name") or supplier.get("nom", ""))
    supplier["supplier_family_name"] = supplier.get("supplier_family_name") or family_name
    supplier["supplier_family_key"] = supplier.get("supplier_family_key") or family_key
    supplier["offer_variant"] = supplier.get("offer_variant") or infer_offer_variant(supplier.get("nom", ""))
    supplier["offers_history"] = supplier.get("offers_history") if isinstance(supplier.get("offers_history"), list) else []
    supplier["price_history"] = supplier.get("price_history") if isinstance(supplier.get("price_history"), list) else []
    supplier["import_history"] = supplier.get("import_history") if isinstance(supplier.get("import_history"), list) else []
    supplier["review_history"] = supplier.get("review_history") if isinstance(supplier.get("review_history"), list) else []
    supplier["test_order_checklist"] = supplier.get("test_order_checklist") if isinstance(supplier.get("test_order_checklist"), list) else []
    supplier["negotiation_history"] = [
        normalize_negotiation_event(item)
        for item in supplier.get("negotiation_history", [])
        if isinstance(item, dict)
    ] if isinstance(supplier.get("negotiation_history"), list) else []
    supplier["conversation_history"] = [
        normalize_conversation_message(item)
        for item in supplier.get("conversation_history", [])
        if isinstance(item, dict)
    ] if isinstance(supplier.get("conversation_history"), list) else []
    recalculate_supplier(supplier)
    return supplier


def normalize_suppliers_data(data) -> dict:
    if not isinstance(data, dict):
        data = default_suppliers_data()
    data.setdefault("schema_version", 1)
    defaults = default_suppliers_data()
    settings = data.setdefault("settings", {})
    default_settings = defaults["settings"]
    settings.setdefault("conversion_rates", default_settings["conversion_rates"])
    settings["conversion_rates"].setdefault("JPY", default_settings["conversion_rates"]["JPY"])
    settings["conversion_rates"].setdefault("USD", default_settings["conversion_rates"]["USD"])
    settings.setdefault("resale_scenario", "reference")
    settings.setdefault("custom_resale_per_card_eur", 3.0)
    data.setdefault("review_history", [])
    data.setdefault("ignored_duplicate_pairs", [])
    if not isinstance(data.get("suppliers"), list):
        data["suppliers"] = []
    data["suppliers"] = [normalize_supplier(item) for item in data["suppliers"] if isinstance(item, dict)]
    return data


def calculate_offer(supplier: dict, quantity: int = 200) -> dict:
    quantity = 100 if int(quantity or 200) == 100 else 200
    price_field = "prix_100" if quantity == 100 else "prix_200"
    base_price = parse_number(supplier.get(price_field), None)
    actual_quantity = quantity
    source_label = f"Offre {quantity} cartes"
    latest_amount = parse_number(supplier.get("latest_offer_amount") or supplier.get("latest_offer"), None)
    latest_quantity = parse_number(supplier.get("latest_offer_quantity"), None)
    if quantity == 200 and latest_amount is not None and latest_amount > 0 and latest_quantity == 200:
        base_price = latest_amount
        actual_quantity = 200
        source_label = "Dernière offre finale"
    elif base_price is None or base_price <= 0:
        fallback_100 = parse_number(supplier.get("prix_100"), None)
        if quantity == 200 and fallback_100 is not None and fallback_100 > 0:
            base_price = fallback_100
            actual_quantity = 100
            source_label = "Offre 100 cartes"
    if base_price is None or base_price <= 0:
        return {
            "available": False,
            "reason": f"Prix {quantity} non renseigné — calcul indisponible",
            "quantity": quantity,
        }
    port = 0.0 if source_label.startswith("Dernière offre") and supplier.get("latest_offer_shipping_included") else (parse_number(supplier.get("port"), 0.0) or 0.0)
    paypal_fixed = parse_number(supplier.get("frais_paypal_fixed"), None)
    if paypal_fixed is None:
        paypal_fixed = parse_number(supplier.get("frais_paypal"), 0.0) or 0.0
    paypal_percent = parse_number(supplier.get("frais_paypal_percent"), 0.0) or 0.0
    paypal_percent_amount = (base_price + port) * (paypal_percent / 100.0) if paypal_percent > 0 else 0.0
    paypal = paypal_fixed + paypal_percent_amount
    import_rate = (parse_number(supplier.get("tva_import_rate"), 0.0) or 0.0) if supplier.get("tva_import_active") else 0.0
    frais_import = parse_number(supplier.get("frais_import"), 0.0) or 0.0
    frais_dossier = parse_number(supplier.get("frais_dossier"), 0.0) or 0.0
    base_import = base_price + port + paypal
    import_amount = base_import * import_rate
    final = base_import + import_amount + frais_import + frais_dossier
    unit = final / actual_quantity if actual_quantity > 0 else None
    currency = supplier.get("latest_offer_currency") if source_label.startswith("Dernière offre") and supplier.get("latest_offer_currency") else (supplier.get("devise") or "EUR")
    conversion_rate = parse_number(supplier.get("conversion_rate_to_eur"), None)
    final_eur = None
    unit_eur = None
    conversion_needed = currency != "EUR" and not conversion_rate
    if currency == "EUR":
        final_eur = final
        unit_eur = unit
    elif conversion_rate and conversion_rate > 0:
        final_eur = final * conversion_rate
        unit_eur = unit * conversion_rate if unit is not None else None
    return {
        "available": True,
        "quantity": actual_quantity,
        "requested_quantity": quantity,
        "source_label": source_label,
        "base_price": base_price,
        "port": port,
        "frais_paypal": paypal,
        "frais_paypal_fixed": paypal_fixed,
        "frais_paypal_percent": paypal_percent,
        "frais_paypal_percent_amount": paypal_percent_amount,
        "base_import": base_import,
        "import_rate": import_rate,
        "import_amount": import_amount,
        "frais_import": frais_import,
        "frais_dossier": frais_dossier,
        "final": final,
        "unit": unit,
        "currency": currency,
        "conversion_rate": conversion_rate,
        "conversion_needed": conversion_needed,
        "final_eur": final_eur,
        "unit_eur": unit_eur,
    }


def recalculate_supplier(supplier: dict) -> dict:
    offer_200 = calculate_offer(supplier, 200)
    supplier["prix_final_estime"] = offer_200.get("final") if offer_200.get("available") else None
    supplier["prix_unitaire_estime"] = offer_200.get("unit") if offer_200.get("available") else None
    supplier["prix_final_eur"] = offer_200.get("final_eur")
    supplier["prix_unitaire_eur"] = offer_200.get("unit_eur")
    quantity = int(parse_number(supplier.get("quantity_reference"), 200) or 200)
    if quantity <= 0:
        quantity = 200
    supplier["quantity_reference"] = quantity
    supplier_total = parse_number(supplier.get("supplier_total_source"), None)
    source_currency = (
        (supplier.get("supplier_total_source_currency") if supplier_total is not None else "")
        or supplier.get("cards_price_source_currency")
        or supplier.get("devise")
        or "EUR"
    )
    source_currency = str(source_currency or "EUR").upper()
    shipping_status = supplier.get("shipping_status")
    cards_price = parse_number(supplier.get("cards_price_source"), None)
    if cards_price is None and supplier_total is None:
        if quantity == 100:
            cards_price = parse_number(supplier.get("prix_100"), None)
        else:
            cards_price = parse_number(supplier.get("prix_200"), None)
    shipping = parse_number(supplier.get("shipping_price_source"), None)
    if shipping is None and shipping_status not in {"unknown", "about_20_usd", "included"}:
        shipping = parse_number(supplier.get("port"), None)
    paypal_fixed = parse_number(supplier.get("paypal_fee_source"), None)
    paypal_percent = parse_number(supplier.get("paypal_fee_percent"), None)
    if paypal_percent is None:
        paypal_percent = parse_number(supplier.get("frais_paypal_percent"), None)
    subtotal_before_paypal = (cards_price or 0.0) + (shipping or 0.0)
    if (
        paypal_fixed is None
        and supplier_total is not None
        and cards_price is not None
        and shipping is not None
    ):
        inferred_paypal = supplier_total - cards_price - shipping
        paypal_fixed = inferred_paypal if inferred_paypal >= 0 else None
    if paypal_fixed is None and paypal_percent is not None and subtotal_before_paypal > 0:
        paypal_fixed = subtotal_before_paypal * (paypal_percent / 100.0)
    if supplier_total is None and cards_price is not None and shipping_status not in {"unknown", "about_20_usd"}:
        supplier_total = cards_price + (shipping or 0.0) + (paypal_fixed or 0.0)
    supplier["cards_price_source"] = cards_price
    supplier["shipping_price_source"] = shipping
    supplier["paypal_fee_source"] = paypal_fixed
    supplier["paypal_fee_percent"] = paypal_percent
    supplier["supplier_total_source"] = supplier_total
    currency_sources = {
        "cards_price_source_currency": cards_price,
        "shipping_price_source_currency": shipping,
        "paypal_fee_source_currency": paypal_fixed,
        "supplier_total_source_currency": supplier_total,
    }
    for currency_field, amount in currency_sources.items():
        if amount is not None and not supplier.get(currency_field):
            supplier[currency_field] = source_currency
        if amount is None:
            supplier[currency_field] = ""
    conversion_rate = parse_number(supplier.get("conversion_rate_to_eur"), None)
    if source_currency == "EUR":
        conversion_rate = 1.0
        supplier["conversion_rate_to_eur"] = 1.0
    elif conversion_rate == 1.0 and source_currency in {"JPY", "USD"}:
        conversion_rate = None
        supplier["conversion_rate_to_eur"] = None
    def to_eur(value):
        if value is None or conversion_rate is None or conversion_rate <= 0:
            return None
        return value * conversion_rate
    supplier["cards_price_eur"] = to_eur(cards_price)
    supplier["shipping_price_eur"] = to_eur(shipping)
    supplier["paypal_fee_eur"] = to_eur(paypal_fixed)
    supplier["supplier_total_eur"] = to_eur(supplier_total)
    min_landed = parse_number(supplier.get("landed_cost_estimated_min_eur"), None)
    max_landed = parse_number(supplier.get("landed_cost_estimated_max_eur"), None)
    landed = parse_number(supplier.get("landed_cost_estimated_eur"), None)
    if landed is None and min_landed is not None and max_landed is not None:
        landed = (min_landed + max_landed) / 2.0
    if landed is None and supplier.get("supplier_total_eur") is not None:
        landed = (
            (supplier.get("supplier_total_eur") or 0.0)
            + (parse_number(supplier.get("import_tax_eur"), 0.0) or 0.0)
            + (parse_number(supplier.get("customs_fee_eur"), 0.0) or 0.0)
            + (parse_number(supplier.get("file_fee_eur"), 0.0) or 0.0)
        )
    supplier["landed_cost_estimated_eur"] = landed
    supplier["landed_cost_per_card_eur"] = landed / quantity if landed is not None and quantity > 0 else None
    supplier["landed_cost_per_card_min_eur"] = min_landed / quantity if min_landed is not None and quantity > 0 else None
    supplier["landed_cost_per_card_max_eur"] = max_landed / quantity if max_landed is not None and quantity > 0 else None
    identity = normalize_supplier_identity(supplier.get("nom", ""))
    resale_total = parse_number(supplier.get("estimated_resale_total_eur"), None)
    if resale_total is None:
        resale_total = 655.0 if identity == "kkexportjapan" else quantity * 3.0
    supplier["estimated_resale_total_eur"] = resale_total
    supplier["estimated_resale_per_card_eur"] = resale_total / quantity if quantity > 0 else None
    if landed is not None and resale_total and resale_total > 0:
        supplier["purchase_percentage_of_resale"] = landed / resale_total * 100.0
        supplier["estimated_margin_eur"] = resale_total - landed
        supplier["estimated_margin_percent"] = (resale_total - landed) / resale_total * 100.0
    else:
        supplier["purchase_percentage_of_resale"] = None
        supplier["estimated_margin_eur"] = None
        supplier["estimated_margin_percent"] = None
    if min_landed is not None and resale_total and resale_total > 0:
        supplier["purchase_percentage_of_resale_min"] = min_landed / resale_total * 100.0
        supplier["estimated_margin_max_eur"] = resale_total - min_landed
        supplier["estimated_margin_percent_max"] = (resale_total - min_landed) / resale_total * 100.0
    if max_landed is not None and resale_total and resale_total > 0:
        supplier["purchase_percentage_of_resale_max"] = max_landed / resale_total * 100.0
        supplier["estimated_margin_min_eur"] = resale_total - max_landed
        supplier["estimated_margin_percent_min"] = (resale_total - max_landed) / resale_total * 100.0
    return supplier


def make_offer_history_entry(supplier: dict, *, source_type: str = "manual", source_text: str = "", notes: str = "") -> dict:
    active = normalize_supplier(deepcopy(supplier))
    offer_100 = calculate_offer(active, 100)
    offer_200 = calculate_offer(active, 200)
    return {
        "id": new_id("offer"),
        "date": now_iso(),
        "source_type": source_type,
        "source_text": source_text if source_type != "manual" else "",
        "prix_100": active.get("prix_100"),
        "prix_200": active.get("prix_200"),
        "devise": active.get("devise"),
        "port": active.get("port"),
        "frais_paypal": active.get("frais_paypal"),
        "tva_import_active": active.get("tva_import_active"),
        "tva_import_rate": active.get("tva_import_rate"),
        "frais_import": active.get("frais_import"),
        "frais_dossier": active.get("frais_dossier"),
        "prix_final_estime": offer_200.get("final") if offer_200.get("available") else None,
        "prix_unitaire_estime": offer_200.get("unit") if offer_200.get("available") else None,
        "prix_final_100": offer_100.get("final") if offer_100.get("available") else None,
        "prix_unitaire_100": offer_100.get("unit") if offer_100.get("available") else None,
        "prix_final_eur": offer_200.get("final_eur"),
        "prix_unitaire_eur": offer_200.get("unit_eur"),
        "notes": notes,
    }


def confidence_score(supplier: dict):
    values = {
        "confiance_note": supplier.get("confiance_note"),
        "service_note": supplier.get("service_note"),
        "contenu_note": supplier.get("contenu_note"),
    }
    if all(v is None for v in values.values()):
        return None
    return (
        (float(values["confiance_note"] or 0) * 0.60)
        + (float(values["service_note"] or 0) * 0.25)
        + (float(values["contenu_note"] or 0) * 0.15)
    )


def eligible_for_price(supplier: dict) -> bool:
    return (
        supplier.get("statut") not in {"archivé", "À éviter"}
        and supplier.get("landed_cost_per_card_eur") is not None
        and supplier.get("landed_cost_per_card_eur") > 0
    )


def supplier_rankings(suppliers: list[dict]) -> dict:
    normalized = [normalize_supplier(item) for item in suppliers]
    price_candidates = [item for item in normalized if eligible_for_price(item)]
    best_price = sorted(price_candidates, key=lambda item: item.get("landed_cost_per_card_eur") or 999999)
    confidence_candidates = []
    for item in normalized:
        if item.get("statut") in {"archivé", "À éviter"}:
            continue
        score = confidence_score(item)
        if score is not None:
            confidence_candidates.append((score, item))
    best_confidence = [item for _score, item in sorted(confidence_candidates, key=lambda pair: pair[0], reverse=True)]
    equilibrium = []
    prices = [item["landed_cost_per_card_eur"] for item in price_candidates]
    min_price = min(prices) if prices else None
    max_price = max(prices) if prices else None
    for item in price_candidates:
        score_conf = confidence_score(item)
        if score_conf is None:
            continue
        if max_price and min_price is not None and max_price > min_price:
            score_price = 5.0 * (1.0 - ((item["landed_cost_per_card_eur"] - min_price) / (max_price - min_price)))
        else:
            score_price = 5.0
        equilibrium.append(((score_price * 0.55) + (score_conf * 0.45), item))
    return {
        "best_price": best_price,
        "best_confidence": best_confidence,
        "best_balance": [item for _score, item in sorted(equilibrium, key=lambda pair: pair[0], reverse=True)],
    }


def _score_part(value, max_points):
    if value is None:
        return None
    try:
        return max(0.0, min(float(value), 5.0)) / 5.0 * max_points
    except (TypeError, ValueError):
        return None


def pokestock_score(supplier: dict, suppliers: list[dict]) -> dict:
    supplier = normalize_supplier(supplier)
    normalized = [normalize_supplier(item) for item in suppliers]
    eligible_prices = [
        item.get("landed_cost_per_card_eur")
        for item in normalized
        if eligible_for_price(item)
    ]
    eligible_prices = [price for price in eligible_prices if price and price > 0]
    parts = {}
    missing = []
    points_obtenus = 0.0
    points_disponibles = 0.0

    if supplier.get("prix_unitaire_eur") and supplier.get("statut") not in {"archivé", "À éviter"} and len(eligible_prices) >= 2:
        min_price = min(eligible_prices)
        score = max(0.0, min((min_price / supplier["prix_unitaire_eur"]) * 30.0, 30.0))
        parts["prix"] = {"points": score, "max": 30, "label": "Prix"}
        points_obtenus += score
        points_disponibles += 30
    else:
        parts["prix"] = {"points": None, "max": 30, "label": "Prix", "reason": "Prix non comparable — données insuffisantes."}
        missing.append("prix comparable")

    conf = _score_part(supplier.get("confiance_note"), 25)
    if conf is None:
        parts["confiance"] = {"points": None, "max": 25, "label": "Confiance", "reason": "Confiance non renseignée"}
        missing.append("note de confiance")
    else:
        parts["confiance"] = {"points": conf, "max": 25, "label": "Confiance"}
        points_obtenus += conf
        points_disponibles += 25

    quality_points = 0.0
    quality_available = 0.0
    content = _score_part(supplier.get("contenu_note"), 12)
    if content is None:
        missing.append("note contenu")
    else:
        quality_points += content
        quality_available += 12
    state_map = {"Near Mint": 4, "Excellent": 3, "Mixed": 1, "? v?rifier": 0}
    if supplier.get("etat") in state_map:
        quality_points += state_map[supplier.get("etat")]
        quality_available += 4
    else:
        missing.append("?tat")
    duplicate_map = {"peu": 2, "moyen": 1, "beaucoup": 0}
    if supplier.get("doublons") in duplicate_map:
        quality_points += duplicate_map[supplier.get("doublons")]
        quality_available += 2
    else:
        missing.append("doublons")
    media_map = {"oui": 2, "partiel": 1, "non": 0}
    if supplier.get("photos_video") in media_map:
        quality_points += media_map[supplier.get("photos_video")]
        quality_available += 2
    else:
        missing.append("photos / vid?o")
    parts["qualite"] = {"points": quality_points if quality_available else None, "max": 20, "available": quality_available, "label": "Qualit?"}
    points_obtenus += quality_points
    points_disponibles += quality_available

    payment_points = 0.0
    payment_available = 0.0
    if supplier.get("paypal_gs") == "oui":
        payment_points += 8
        payment_available += 8
    elif supplier.get("paypal_gs") == "non":
        payment_available += 8
    else:
        missing.append("PayPal G&S")
    if supplier.get("paiement"):
        payment_points += 3
        payment_available += 3
    else:
        missing.append("mode de paiement")
    if supplier.get("frais_paypal") is not None:
        payment_points += 2
        payment_available += 2
    else:
        missing.append("frais paiement")
    payment_terms_known = any((event.get("payment_terms") or "").strip() for event in supplier.get("negotiation_history", []))
    if payment_terms_known:
        payment_points += 2
        payment_available += 2
    elif supplier.get("paiement"):
        payment_available += 2
    else:
        missing.append("conditions paiement")
    parts["paiement"] = {"points": payment_points if payment_available else None, "max": 15, "available": payment_available, "label": "Paiement"}
    points_obtenus += payment_points
    points_disponibles += payment_available

    service_points = 0.0
    service_available = 0.0
    service = _score_part(supplier.get("service_note"), 7)
    if service is None:
        missing.append("note service")
    else:
        service_points += service
        service_available += 7
    if supplier.get("tracking") == "oui":
        service_points += 3
        service_available += 3
    elif supplier.get("tracking") == "non":
        service_available += 3
    else:
        missing.append("tracking")
    parts["service"] = {"points": service_points if service_available else None, "max": 10, "available": service_available, "label": "Service"}
    points_obtenus += service_points
    points_disponibles += service_available

    coverage = points_disponibles / 100.0
    complete = coverage >= 0.70
    score = (points_obtenus / points_disponibles * 100.0) if points_disponibles and complete else None
    return {
        "score": score,
        "complete": complete,
        "coverage": coverage,
        "points_obtenus": points_obtenus,
        "points_disponibles": points_disponibles,
        "parts": parts,
        "missing": sorted(set(missing)),
    }


def negotiation_stats(supplier: dict) -> dict:
    supplier = normalize_supplier(supplier)
    by_neg = {}
    for event in supplier.get("negotiation_history", []):
        by_neg.setdefault(event.get("negotiation_id"), []).append(event)
    comparable = []
    for neg_id, events in by_neg.items():
        supplier_events = [
            event for event in events
            if event.get("actor") == "supplier"
            and event.get("event_type") in {"supplier_offer", "agreement"}
            and event.get("amount") is not None
        ]
        supplier_events.sort(key=lambda event: (event.get("event_date") or "", event.get("created_at") or ""))
        if len(supplier_events) < 2:
            continue
        first = supplier_events[0]
        last = supplier_events[-1]
        if first.get("quantity") == last.get("quantity") and first.get("currency") == last.get("currency"):
            start = first.get("amount")
            end = last.get("amount")
        elif first.get("unit_price_eur") is not None and last.get("unit_price_eur") is not None:
            start = first.get("unit_price_eur")
            end = last.get("unit_price_eur")
        else:
            continue
        if not start or start <= 0 or end is None:
            continue
        change = end - start
        pct = change / start * 100.0
        comparable.append({"negotiation_id": neg_id, "start": start, "end": end, "change": change, "pct": pct})
    reductions = [item for item in comparable if item["pct"] < 0]
    avg_reduction = sum(item["pct"] for item in reductions) / len(reductions) if reductions else None
    best_reduction = min((item["pct"] for item in reductions), default=None)
    return {
        "comparable_count": len(comparable),
        "average_reduction_pct": avg_reduction,
        "best_reduction_pct": best_reduction,
        "items": comparable,
    }


def negotiation_chart_series(supplier: dict) -> dict:
    supplier = normalize_supplier(supplier)
    events = [
        event for event in supplier.get("negotiation_history", [])
        if event.get("event_type") in {"supplier_offer", "my_offer", "agreement"}
        and event.get("amount") is not None
    ]
    if len(events) < 2:
        return {"available": False, "reason": "Historique enregistr?, mais offres non comparables pour un graphique fiable."}
    eur_ready = [event for event in events if event.get("unit_price_eur") is not None]
    if len(eur_ready) >= 2:
        return {"available": True, "mode": "unit_price_eur", "events": eur_ready}
    currencies = {event.get("currency") for event in events}
    if len(currencies) == 1:
        return {"available": True, "mode": "amount", "events": events}
    return {"available": False, "reason": "Historique enregistr?, mais offres non comparables pour un graphique fiable."}


def smart_rankings(suppliers: list[dict]) -> dict:
    normalized = [normalize_supplier(item) for item in suppliers]
    scores = {item["id"]: pokestock_score(item, normalized) for item in normalized}
    eligible = [item for item in normalized if item.get("statut") not in {"archivé", "À éviter"}]
    best_value = sorted(
        [item for item in eligible if scores[item["id"]]["complete"]],
        key=lambda item: scores[item["id"]]["score"] or 0,
        reverse=True,
    )
    reliability = []
    for item in eligible:
        score = scores[item["id"]]
        conf = score["parts"].get("confiance", {}).get("points")
        service = score["parts"].get("service", {}).get("points")
        payment = score["parts"].get("paiement", {}).get("points")
        if conf is None and service is None and payment is None:
            continue
        reliability.append((((conf or 0) / 25 * 100 * 0.60) + ((service or 0) / 10 * 100 * 0.20) + ((payment or 0) / 15 * 100 * 0.20), item))
    neg = [(abs(stats["average_reduction_pct"]), item) for item in eligible if (stats := negotiation_stats(item)).get("average_reduction_pct") is not None and stats.get("comparable_count", 0) > 0]
    ar = [
        item for item in eligible
        if ("AR mid" in item.get("specialites", []) or "AR high" in item.get("specialites", []))
        and (item.get("contenu_note") is not None or item.get("etat") != "inconnu")
    ]
    ar.sort(key=lambda item: ((item.get("contenu_note") or 0), (item.get("confiance_note") or 0), item.get("valeur_lot_estimee") or 0), reverse=True)
    beginner = [
        item for item in eligible
        if item.get("statut") in {"actif", "testé", "top fournisseur"}
        and item.get("paypal_gs") == "oui"
        and item.get("tracking") == "oui"
        and item.get("prix_unitaire_eur") is not None
    ]
    beginner.sort(key=lambda item: (item.get("confiance_note") or 0, item.get("service_note") or 0), reverse=True)
    big = [
        item for item in eligible
        if item.get("grosses_quantites_confirmees") == "oui"
        and item.get("prix_unitaire_eur") is not None
        and calculate_offer(item, 200).get("available")
    ]
    big.sort(key=lambda item: (item.get("prix_unitaire_eur") or 999999, -(item.get("confiance_note") or 0)))
    return {
        "best_price": supplier_rankings(normalized).get("best_price", []),
        "best_value": best_value,
        "most_reliable": [item for _score, item in sorted(reliability, key=lambda pair: pair[0], reverse=True)],
        "negotiable": [item for _score, item in sorted(neg, key=lambda pair: pair[0], reverse=True)],
        "ar_mid_high": ar,
        "beginner": beginner,
        "big_quantity": big,
        "scores": scores,
    }


def find_duplicate_supplier(suppliers: list[dict], candidate: dict) -> dict | None:
    cand_name = normalize_supplier_identity(candidate.get("nom", ""))
    cand_contact = normalize_supplier_identity(candidate.get("contact_link", ""))
    if not cand_name and not cand_contact:
        return None
    for supplier in suppliers:
        if cand_contact and normalize_supplier_identity(supplier.get("contact_link", "")) == cand_contact:
            return supplier
    for supplier in suppliers:
        if cand_name and normalize_supplier_identity(supplier.get("nom", "")) == cand_name:
            return supplier
    return None


def supplier_name_matches(suppliers: list[dict], name: str) -> list[dict]:
    target = normalize_supplier_identity(name)
    if not target:
        return []
    exact_matches = []
    for supplier in suppliers:
        current = normalize_supplier_identity(supplier.get("nom", ""))
        if current and current == target:
            exact_matches.append(supplier)
    if exact_matches:
        return exact_matches
    close_matches = [
        supplier for supplier in suppliers
        if supplier_identity_similarity(name, supplier.get("nom", "")) >= 0.90
    ]
    return close_matches if len(close_matches) == 1 else close_matches


def _detect_import_format(raw: str) -> str:
    text = normalize_text(raw)
    if re.search(r"={2,}\s*supplier\s+review\s+v1\s*={2,}", text):
        return "supplier_review_v1"
    if re.search(r"={2,}\s*supplier\s+update\s*={2,}", text):
        return "supplier_update"
    return "free_text"


def _parse_currency(text: str, default: str = "EUR") -> str:
    low = normalize_text(text)
    raw = str(text)
    if "jpy" in low or "yen" in low or "yens" in low or "?" in raw or "?" in raw or "?" in raw or "?" in raw or "?" in raw:
        return "JPY"
    if "usd" in low or "$" in str(text):
        return "USD"
    broken_euro = "\u00e2\u201a\u00ac"
    double_broken_euro = "\u00c3\u00a2\u00e2\u20ac\u0161\u00c2\u00ac"
    if "eur" in low or "€" in raw or broken_euro in raw or double_broken_euro in raw:
        return "EUR"
    return default


def _canonical_money_text(text: str) -> str:
    return (
        str(text or "")
        .replace("\u00c3\u201a?", "¥")
        .replace("Ä½", "¥")
        .replace("ï¿¥", "¥")
        .replace("\u00c3\u00a2\u00e2\u20ac\u0161\u00c2\u00ac", "€")
        .replace("\u00e2\u201a\u00ac", "€")
        .replace("\u202f", " ")
        .replace("\xa0", " ")
    )


def _price_regex():
    amount = r"(?:\d{1,3}(?:[,.]\d{3})+(?:[,.]\d+)?|\d{1,3}(?:\s\d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?)"
    return rf"(?P<prefix>[\u00a5$\u20ac])?\s*(?P<amount>{amount})\s*(?P<suffix>JPY|USD|EUR|yen|yens|dollars?|euros?)?"


def _parse_amount_currency(fragment: str, default_currency: str = "EUR") -> tuple[float | None, str]:
    text = _canonical_money_text(fragment)
    match = re.search(_price_regex(), text, flags=re.IGNORECASE)
    if not match:
        return None, default_currency
    currency_hint = " ".join(part for part in [match.group("prefix"), match.group("suffix")] if part)
    return parse_number(match.group("amount"), None), _parse_currency(currency_hint or text, default_currency)


def _parse_last_amount_currency(fragment: str, default_currency: str = "EUR") -> tuple[float | None, str]:
    text = _canonical_money_text(fragment)
    matches = list(re.finditer(_price_regex(), text, flags=re.IGNORECASE))
    if not matches:
        return None, default_currency
    match = matches[-1]
    currency_hint = " ".join(part for part in [match.group("prefix"), match.group("suffix")] if part)
    return parse_number(match.group("amount"), None), _parse_currency(currency_hint or text, default_currency)


def _parse_price_details(text: str) -> dict:
    raw = _canonical_money_text(text)
    low = normalize_text(raw)
    result = {
        "prix_100": None,
        "prix_200": None,
        "devise": _parse_currency(raw, "EUR"),
        "latest_offer_amount": None,
        "latest_offer_currency": "",
        "latest_offer_quantity": None,
        "latest_offer_shipping_included": False,
        "latest_offer_quantity_inferred": False,
        "frais_paypal_percent": None,
        "frais_paypal_fixed": None,
        "port": None,
        "paiement": "",
        "price_status": "",
    }
    amount_pattern = _price_regex()
    label_pattern = r"\b(?P<qty>100|200)[-\s]*(?:cards?|cartes?)(?:[ \t]+[^:\n]{0,60})?:[ \t]*"
    label_matches = list(re.finditer(label_pattern, raw, flags=re.IGNORECASE))
    for index, label_match in enumerate(label_matches):
        prefix_context = raw[max(0, label_match.start() - 35):label_match.start()]
        if re.search(r"shipping|port|livraison", prefix_context, flags=re.IGNORECASE):
            continue
        quantity = int(label_match.group("qty"))
        next_start = label_matches[index + 1].start() if index + 1 < len(label_matches) else len(raw)
        stop_match = re.search(r"\b(?:latest\s+offer|derni[e?]re\s+offre|shipping|port|livraison|paypal)\b|\n", raw[label_match.end():next_start], flags=re.IGNORECASE)
        segment_end = label_match.end() + stop_match.start() if stop_match else next_start
        amount, currency = _parse_amount_currency(raw[label_match.end():segment_end], result["devise"])
        if amount is not None and amount > 0 and result.get(f"prix_{quantity}") is None:
            result[f"prix_{quantity}"] = amount
            result["devise"] = currency
    boundary = r"(?=\s*(?:100|200)[-\s]*(?:cards?|cartes?)|latest\s+offer|derni[e?]re\s+offre|shipping|port|livraison|paypal|$|\n)"
    quantity_patterns = [
        (100, rf"(?:100[-\s]*(?:cards?|cartes?)(?:\s+[^:\n]{{0,40}})?\s*:?\s*{amount_pattern}{boundary})"),
        (200, rf"(?:200[-\s]*(?:cards?|cartes?)(?:\s+[^:\n]{{0,40}})?\s*:?\s*{amount_pattern}{boundary})"),
        (100, rf"(?:{amount_pattern}(?=\s*(?:for|pour)?\s*100[-\s]*(?:cards?|cartes?))\s*(?:for|pour)?\s*100[-\s]*(?:cards?|cartes?))"),
        (200, rf"(?:{amount_pattern}(?=\s*(?:for|pour)?\s*200[-\s]*(?:cards?|cartes?))\s*(?:for|pour)?\s*200[-\s]*(?:cards?|cartes?))"),
    ]
    for quantity, pattern in quantity_patterns:
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            prefix_context = raw[max(0, match.start() - 35):match.start()]
            if re.search(r"shipping|port|livraison", prefix_context, flags=re.IGNORECASE):
                continue
            amount = parse_number(match.group("amount"), None)
            currency_hint = " ".join(part for part in [match.group("prefix"), match.group("suffix")] if part)
            currency = _parse_currency(currency_hint or match.group(0), result["devise"])
            if amount is not None and amount > 0:
                if result.get(f"prix_{quantity}") is not None:
                    continue
                result[f"prix_{quantity}"] = amount
                result["devise"] = currency
                break
    latest_match = re.search(
        rf"(?:latest\s+offer|latest\s+(?:wise|paypal)\s+total|derni[e?]re\s+offre|seller\s+total)[^\n:]*:?\s*(?P<body>.{{0,140}}?{amount_pattern}.{{0,80}})",
        raw,
        flags=re.IGNORECASE,
    )
    if latest_match:
        body = latest_match.group("body")
        amount, currency = _parse_amount_currency(body, result["devise"])
        if amount is not None and amount > 0:
            result["latest_offer_amount"] = amount
            result["latest_offer_currency"] = currency
            result["latest_offer_shipping_included"] = bool(re.search(r"\bshipped\b|shipping\s+included|port\s+inclus|livraison\s+incluse|\btotal\b", latest_match.group(0), flags=re.IGNORECASE))
            quantity_match = re.search(r"\b(100|200)[-\s]*(?:cards?|cartes?)\b", body, flags=re.IGNORECASE)
            if quantity_match:
                result["latest_offer_quantity"] = int(quantity_match.group(1))
            else:
                available_quantities = [q for q in (100, 200) if result.get(f"prix_{q}") is not None]
                if len(available_quantities) == 1:
                    result["latest_offer_quantity"] = available_quantities[0]
                    result["latest_offer_quantity_inferred"] = True
                elif result.get("prix_200") is not None:
                    result["latest_offer_quantity"] = 200
                    result["latest_offer_quantity_inferred"] = True
    paypal_percent = re.search(r"paypal[^\n%]{0,40}\+?\s*(\d+(?:[,.]\d+)?)\s*%", raw, flags=re.IGNORECASE)
    if paypal_percent:
        result["frais_paypal_percent"] = parse_number(paypal_percent.group(1), None)
        result["paiement"] = "PayPal"
    paypal_fixed = re.search(r"(?:paypal|frais\s*paypal)[^\n\d]{0,30}([?$â‚¬]?\s*\d[\d\s.,]*\s*(?:JPY|USD|EUR)?)", raw, flags=re.IGNORECASE)
    if paypal_fixed and result.get("frais_paypal_percent") is None and "%" not in paypal_fixed.group(0):
        fixed, _currency = _parse_amount_currency(paypal_fixed.group(1), result["devise"])
        result["frais_paypal_fixed"] = fixed
        result["paiement"] = "PayPal"
    shipping_match = re.search(r"(?:shipping|port|livraison)[^\n?$â‚¬]*([?$â‚¬]?\s*\d[\d\s.,]*\s*(?:JPY|USD|EUR)?)", raw, flags=re.IGNORECASE)
    if shipping_match and not re.search(r"included|inclus|incluse", shipping_match.group(0), flags=re.IGNORECASE):
        amount, _currency = _parse_last_amount_currency(shipping_match.group(0), result["devise"])
        result["port"] = amount
    if result["prix_100"] is None and result["prix_200"] is None and result["latest_offer_amount"] is None:
        if re.search(r"\b(?:pending|awaiting|en\s+attente|devis\s+en\s+attente)\b", low):
            result["price_status"] = "devis_en_attente"
        elif re.search(r"\b(?:to\s+confirm|a\s+confirmer|prix\s+a\s+confirmer)\b", low):
            result["price_status"] = "prix_a_confirmer"
        elif re.search(r"\b(?:not\s+communicated|not\s+provided|non\s+communique|aucun\s+prix)\b", low):
            result["price_status"] = "non_communique"
    if "wise" in low:
        result["paiement"] = "Wise" if not result["paiement"] else result["paiement"] + " / Wise"
    elif "paypal" in low:
        result["paiement"] = "PayPal"
    return result


def _money_amount_near(text: str, pattern: str):
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
    if not match:
        return None
    if match.lastindex:
        return parse_number(match.group(match.lastindex), None)
    numbers = re.findall(r"\d[\d\s.,]*", match.group(0))
    if not numbers:
        return None
    return parse_number(numbers[-1], None)


def _parse_offer_line(text: str) -> dict:
    raw = _canonical_money_text(text)
    low = normalize_text(raw)
    quantity = 200 if ("200" in low and ("card" in low or "carte" in low)) else None
    if quantity is None and "100" in low and ("card" in low or "carte" in low):
        quantity = 100
    details = _parse_price_details(raw)
    return {
        "amount": parse_number(raw, None),
        "quantity": quantity,
        "currency": _parse_currency(raw, "EUR"),
        "prix_100": details.get("prix_100"),
        "prix_200": details.get("prix_200"),
        "latest_offer": details.get("latest_offer_amount"),
        "details": details,
    }


def _parse_yes_no(value: str, unknown: str = "inconnu") -> str:
    low = normalize_text(value)
    if low.startswith(("yes", "oui")) or low in {"y", "true", "vrai"}:
        return "oui"
    if low.startswith(("no", "non")) or low in {"false", "faux"}:
        return "non"
    return unknown


def _parse_media_value(value: str) -> str:
    low = normalize_text(value)
    if "partial" in low or "partiel" in low:
        return "partiel"
    return _parse_yes_no(value, "inconnu")


def _parse_duplicates_value(value: str) -> str:
    low = normalize_text(value)
    if any(token in low for token in ["low", "peu", "few"]):
        return "peu"
    if any(token in low for token in ["medium", "moyen"]):
        return "moyen"
    if any(token in low for token in ["high", "many", "beaucoup"]):
        return "beaucoup"
    return "inconnu"


def _parse_rating(value: str):
    number = parse_number(value, None)
    if number is None:
        return None
    return max(0.0, min(5.0, number))


def _parse_market_position_rank(value: str):
    match = re.search(r"\btop\s*(\d+)\b", normalize_text(value))
    if not match:
        match = re.search(r"#\s*(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def _parse_best_for_tags(value: str) -> list[str]:
    low = normalize_text(value)
    tags = []
    for token, tag in [
        ("ar mid", "AR mid"),
        ("ar high", "AR high"),
        ("ar/chr", "AR / CHR"),
        ("chr", "CHR"),
        ("first order", "Premi?re commande"),
        ("premiere commande", "Premi?re commande"),
        ("large quantit", "Grosses quantit?s"),
        ("grosses quantit", "Grosses quantit?s"),
        ("japanese", "Cartes japonaises"),
        ("japonaises", "Cartes japonaises"),
        ("french", "Cartes fran?aises"),
        ("francaises", "Cartes fran?aises"),
        ("low budget", "Petit budget"),
        ("budget", "Petit budget"),
        ("high-quality", "Qualit? élevée"),
        ("haute qualite", "Qualit? élevée"),
    ]:
        if token in low and tag not in tags:
            tags.append(tag)
    return tags


def _parse_risk_level(value: str) -> str:
    low = normalize_text(value)
    if low in {"low", "faible"} or low.startswith(("low", "faible")):
        return "low"
    if low in {"medium", "moyen"} or low.startswith(("medium", "moyen")):
        return "medium"
    if low in {"high", "eleve", "elev?"} or low.startswith(("high", "eleve", "elev?")):
        return "high"
    return "unknown"


def _parse_first_order_quantity(value: str):
    low = normalize_text(value)
    if not any(token in low for token in ["card", "carte", "order", "commande"]):
        return None
    number = parse_number(value, None)
    return int(number) if number and number > 0 else None


def _parse_iso_date(value: str):
    text = str(value or "").strip()
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if not match:
        return None
    try:
        datetime.strptime(match.group(1), "%Y-%m-%d")
    except ValueError:
        return None
    return match.group(1)


def _parse_structured_sections(raw: str) -> dict:
    fields = {}
    blocks = {"pros": [], "cons": [], "derniere_analyse": [], "action_recommandee": []}
    active_block = None
    aliases = {
        "supplier": "nom", "fournisseur": "nom",
        "country": "pays", "pays": "pays",
        "type": "type", "status": "statut", "statut": "statut",
        "offer": "offer", "offre": "offer", "new offer": "offer", "nouvelle offre": "offer",
        "latest offer": "latest_offer", "derniere offre": "latest_offer", "derni?re offre": "latest_offer",
        "offer variant": "offer_variant", "variante offre": "offer_variant", "variante": "offer_variant",
        "shipping": "port", "port": "port", "livraison": "port",
        "payment": "paiement", "paiement": "paiement",
        "paypal g&s": "paypal_gs", "paypal goods & services": "paypal_gs", "paypal gs": "paypal_gs",
        "paypal fees": "frais_paypal", "frais paypal": "frais_paypal", "paypal": "frais_paypal",
        "tracking": "tracking", "suivi": "tracking",
        "photos": "photos", "photo": "photos", "video": "video", "vid?o": "video",
        "condition": "etat", "?tat": "etat", "etat": "etat",
        "duplicates": "doublons", "doublons": "doublons",
        "trust rating": "confiance_note", "trust": "confiance_note", "confiance": "confiance_note", "note confiance": "confiance_note",
        "service rating": "service_note", "service": "service_note", "note service": "service_note",
        "content rating": "contenu_note", "content": "contenu_note", "contenu": "contenu_note", "note contenu": "contenu_note",
        "negotiation potential": "potentiel_negociation_note",
        "potentiel de n?gociation": "potentiel_negociation_note",
        "potentiel de negociation": "potentiel_negociation_note",
        "current analysis": "derniere_analyse", "analyse actuelle": "derniere_analyse",
        "recommended action": "action_recommandee", "action recommand?e": "action_recommandee", "action recommandee": "action_recommandee",
        "market position": "market_position", "position marche": "market_position", "position march?": "market_position",
        "best for": "best_for", "ideal pour": "best_for", "id?al pour": "best_for",
        "risk level": "risk_level", "risk": "risk_level", "niveau de risque": "risk_level",
        "recommended first order": "recommended_first_order",
        "first order": "recommended_first_order",
        "premiere commande recommandee": "recommended_first_order",
        "premi?re commande recommand?e": "recommended_first_order",
        "last updated": "review_last_updated",
        "derniere mise a jour": "review_last_updated",
        "derni?re mise ? jour": "review_last_updated",
        "notes": "notes",
    }
    prepared = str(raw or "").replace(";", "\n")
    label_pattern = "|".join(re.escape(label) for label in sorted(aliases, key=len, reverse=True))
    prepared = re.sub(rf"(?<!^)(?<!\n)\b({label_pattern})\s*:", r"\n\1:", prepared, flags=re.IGNORECASE)
    for line in prepared.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("==="):
            continue
        header = normalize_text(stripped.rstrip(":"))
        if header == "pros":
            active_block = "pros"
            continue
        if header == "cons":
            active_block = "cons"
            continue
        if header in {"current analysis", "analyse actuelle"}:
            active_block = "derniere_analyse"
            continue
        if header in {"recommended action", "action recommandee"}:
            active_block = "action_recommandee"
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            field = aliases.get(normalize_text(key))
            if field:
                value = value.strip()
                if field in {"derniere_analyse", "action_recommandee"}:
                    blocks[field].append(value)
                    active_block = field
                else:
                    fields[field] = value
                    active_block = None
                continue
        if active_block in {"pros", "cons"} and stripped.startswith("-"):
            blocks[active_block].append(stripped.lstrip("-").strip())
        elif active_block in {"derniere_analyse", "action_recommandee"}:
            blocks[active_block].append(stripped)
    for key, values in blocks.items():
        if key in {"pros", "cons"}:
            fields[key] = [value for value in values if value]
        elif values:
            fields[key] = "\n".join(value for value in values if value).strip()
    return fields


def _apply_detected_field(supplier: dict, field: str, value, detected_fields: set[str]) -> None:
    if value is None or value == "":
        return
    if field in {"nom", "pays", "paiement", "notes", "derniere_analyse", "action_recommandee", "offer_variant"}:
        supplier[field] = str(value).strip()
    elif field == "market_position":
        supplier[field] = str(value).strip()
        supplier["market_position_rank"] = _parse_market_position_rank(value)
        detected_fields.add("market_position_rank")
    elif field == "best_for":
        supplier[field] = str(value).strip()
        tags = _parse_best_for_tags(value)
        if tags:
            supplier["best_for_tags"] = tags
            detected_fields.add("best_for_tags")
    elif field == "risk_level":
        supplier[field] = _parse_risk_level(value)
    elif field == "recommended_first_order":
        supplier[field] = str(value).strip()
        quantity = _parse_first_order_quantity(value)
        if quantity is not None:
            supplier["recommended_first_order_quantity"] = quantity
            detected_fields.add("recommended_first_order_quantity")
    elif field == "review_last_updated":
        parsed_date = _parse_iso_date(value)
        if not parsed_date:
            supplier.setdefault("_import_warnings", []).append(f"Date Last Updated invalide : {value}")
            return
        supplier[field] = parsed_date
    elif field == "type":
        supplier[field] = "Japon" if "jap" in normalize_text(value) else ("France" if "france" in normalize_text(value) else ("Europe" if "europe" in normalize_text(value) else "Autre"))
    elif field == "statut":
        status_map = {"tested": "testé", "active": "actif", "top supplier": "top fournisseur", "avoid": "À éviter", "archived": "archivé", "waiting": "en attente", "to contact": "À contacter"}
        mapped = status_map.get(normalize_text(value), value if value in SUPPLIER_STATUSES else "")
        if mapped:
            supplier[field] = mapped
        else:
            supplier["derniere_analyse"] = str(value).strip()
            detected_fields.add("derniere_analyse")
            return
    elif field == "port":
        parsed, _currency = _parse_last_amount_currency(value, supplier.get("devise") or "EUR")
        if parsed is None:
            return
        supplier[field] = parsed
    elif field in {"prix_100", "prix_200", "latest_offer", "frais_paypal"}:
        parsed = parse_number(value, None)
        if parsed is None:
            return
        supplier[field] = parsed
    elif field in {"paypal_gs", "tracking"}:
        supplier[field] = _parse_yes_no(value)
    elif field == "photos_video":
        supplier[field] = _parse_media_value(value)
    elif field == "etat":
        low = normalize_text(value)
        supplier[field] = "Near Mint" if ("near mint" in low or re.search(r"\bnm\b", low)) else ("Excellent" if "excellent" in low else ("Mixed" if "mixed" in low else ("? v?rifier" if "verifier" in low else "inconnu")))
    elif field == "doublons":
        supplier[field] = _parse_duplicates_value(value)
    elif field in {"confiance_note", "service_note", "contenu_note", "potentiel_negociation_note"}:
        rating = _parse_rating(value)
        if rating is None:
            return
        supplier[field] = rating
    elif field in {"pros", "cons"} and isinstance(value, list):
        supplier[field] = [str(item).strip() for item in value if str(item).strip()]
    else:
        return
    detected_fields.add(field)


def _apply_price_details(supplier: dict, details: dict, detected_fields: set[str]) -> None:
    for field in [
        "prix_100",
        "prix_200",
        "latest_offer_amount",
        "latest_offer_quantity",
        "frais_paypal_percent",
        "frais_paypal_fixed",
        "port",
    ]:
        value = details.get(field)
        if value is not None and value != "":
            supplier[field] = value
            detected_fields.add(field)
    if details.get("latest_offer_amount") is not None:
        supplier["latest_offer"] = details.get("latest_offer_amount")
        detected_fields.add("latest_offer")
    for field in ["latest_offer_currency", "devise", "paiement"]:
        value = details.get(field)
        if value not in (None, ""):
            supplier[field] = value
            detected_fields.add(field)
    if details.get("price_status"):
        supplier["price_status"] = details.get("price_status")
        detected_fields.add("price_status")
    for field in ["latest_offer_shipping_included", "latest_offer_quantity_inferred"]:
        if details.get(field):
            supplier[field] = True
            detected_fields.add(field)


def make_price_history_entry(existing: dict | None, candidate: dict, *, source_type: str, source_text: str = "") -> dict | None:
    quantity = 200 if candidate.get("prix_200") else (100 if candidate.get("prix_100") else None)
    if not quantity:
        return None
    field = "prix_200" if quantity == 200 else "prix_100"
    new_price = parse_number(candidate.get(field), None)
    if new_price is None or new_price <= 0:
        return None
    currency = candidate.get("devise") or (existing or {}).get("devise") or "EUR"
    old_price = parse_number((existing or {}).get(field), None)
    comparable = old_price is not None and old_price > 0 and (existing or {}).get("devise", currency) == currency
    return {
        "id": new_id("price"),
        "date": now_iso(),
        "source_type": source_type,
        "ancien_prix": old_price if comparable else None,
        "nouveau_prix": new_price,
        "devise": currency,
        "quantite": quantity,
        "ancien_prix_unitaire": (old_price / quantity) if comparable else None,
        "nouveau_prix_unitaire": new_price / quantity,
        "analyse": candidate.get("derniere_analyse") or "",
        "action_recommandee": candidate.get("action_recommandee") or "",
        "source_text": source_text,
    }


def extract_offer_from_text(text: str) -> dict:
    raw = str(text or "")
    import_format = _detect_import_format(raw)
    if import_format in {"supplier_review_v1", "supplier_update"}:
        fields = _parse_structured_sections(raw)
        detected = default_supplier()
        detected["id"] = ""
        detected["created_at"] = ""
        detected["updated_at"] = ""
        detected["notes"] = raw.strip()
        detected_fields = {"notes"}
        _apply_price_details(detected, _parse_price_details(raw), detected_fields)
        if "offer" in fields and str(fields.get("offer") or "").strip():
            offer = _parse_offer_line(fields["offer"])
            _apply_price_details(detected, offer.get("details") or {}, detected_fields)
            if offer.get("prix_100") is not None:
                detected["prix_100"] = offer.get("prix_100")
                detected_fields.add("prix_100")
            if offer.get("prix_200") is not None:
                detected["prix_200"] = offer.get("prix_200")
                detected_fields.add("prix_200")
            if offer.get("latest_offer") is not None:
                detected["latest_offer"] = offer.get("latest_offer")
                detected["latest_offer_amount"] = offer.get("latest_offer")
                detected_fields.add("latest_offer")
                detected_fields.add("latest_offer_amount")
            if offer.get("quantity") == 100 and detected.get("prix_100") is None:
                detected["prix_100"] = offer.get("amount")
                detected_fields.add("prix_100")
            elif offer.get("quantity") == 200 and detected.get("prix_200") is None:
                detected["prix_200"] = offer.get("amount")
                detected_fields.add("prix_200")
            if any(offer.get(key) is not None for key in ["prix_100", "prix_200", "latest_offer"]):
                detected["devise"] = offer.get("currency") or detected.get("devise") or "EUR"
                detected_fields.add("devise")
        for field, value in fields.items():
            if field == "offer":
                continue
            if field == "latest_offer":
                offer = _parse_offer_line(value)
                _apply_price_details(detected, offer.get("details") or {}, detected_fields)
                if offer.get("amount") is not None:
                    detected["latest_offer"] = offer.get("amount")
                    detected["latest_offer_amount"] = offer.get("amount")
                    detected_fields.add("latest_offer")
                    detected_fields.add("latest_offer_amount")
                detected["devise"] = offer.get("currency") or detected.get("devise") or "EUR"
                detected_fields.add("devise")
                continue
            if field == "photos":
                _apply_detected_field(detected, "photos_video", value, detected_fields)
            elif field == "video":
                video_state = _parse_media_value(value)
                if video_state == "partiel" or detected.get("photos_video") == "inconnu":
                    detected["photos_video"] = video_state
                    detected_fields.add("photos_video")
            else:
                _apply_detected_field(detected, field, value, detected_fields)
        if detected.get("devise") != "EUR":
            detected["conversion_rate_to_eur"] = None
        if detected.get("derniere_analyse") or detected.get("action_recommandee"):
            detected["analysis_updated_at"] = now_iso()
            detected_fields.add("analysis_updated_at")
        uncertainty = []
        if not detected.get("nom"):
            uncertainty.append("nom")
        if detected.get("devise") != "EUR":
            uncertainty.append("conversion_rate_to_eur")
        recalculate_supplier(detected)
        return {
            "supplier": normalize_supplier(detected),
            "uncertain_fields": uncertainty,
            "warnings": detected.get("_import_warnings", []),
            "detected_fields": sorted(detected_fields),
            "import_format": import_format,
            "import_hash": import_hash(raw),
            "source_text": raw,
            "price_history_candidate": make_price_history_entry(None, detected, source_type=import_format, source_text=raw),
        }
    low = normalize_text(raw)
    detected = default_supplier()
    detected["id"] = ""
    detected["created_at"] = ""
    detected["updated_at"] = ""
    detected["notes"] = raw.strip()
    uncertainty = []
    detected_fields = {"notes"}
    _apply_price_details(detected, _parse_price_details(raw), detected_fields)
    loose_fields = _parse_structured_sections(raw)
    if loose_fields:
        if "offer" in loose_fields and str(loose_fields.get("offer") or "").strip():
            offer = _parse_offer_line(loose_fields["offer"])
            _apply_price_details(detected, offer.get("details") or {}, detected_fields)
            if offer.get("prix_100") is not None:
                detected["prix_100"] = offer.get("prix_100")
                detected_fields.add("prix_100")
            if offer.get("prix_200") is not None:
                detected["prix_200"] = offer.get("prix_200")
                detected_fields.add("prix_200")
            if any(offer.get(key) is not None for key in ["prix_100", "prix_200", "latest_offer"]):
                detected["devise"] = offer.get("currency") or detected.get("devise") or "EUR"
                detected_fields.add("devise")
        for field, value in loose_fields.items():
            if field == "offer":
                continue
            if field == "photos":
                _apply_detected_field(detected, "photos_video", value, detected_fields)
            else:
                _apply_detected_field(detected, field, value, detected_fields)
    if "japon" in low or "japan" in low:
        detected["type"] = "Japon"
        detected_fields.add("type")
    elif "france" in low:
        detected["type"] = "France"
        detected_fields.add("type")
    elif "europe" in low or "eu " in low:
        detected["type"] = "Europe"
        detected_fields.add("type")

    if "jpy" in low or "yen" in low or "yens" in low or "?" in raw or "?" in raw or "?" in raw or "?" in raw or "?" in raw:
        detected["devise"] = "JPY"
        detected["conversion_rate_to_eur"] = None
    elif "usd" in low or "$" in raw:
        detected["devise"] = "USD"
        detected["conversion_rate_to_eur"] = None
    elif "eur" in low or "â‚¬" in raw:
        detected["devise"] = "EUR"

    def rate_near(label_patterns, reject_shipping_context=False):
        for pattern in label_patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE)
            if match:
                context = raw[max(0, match.start() - 35):match.end()]
                if reject_shipping_context and re.search(r"shipping|port|livraison", context, flags=re.IGNORECASE):
                    continue
                return parse_number(match.group(1), None)
        return None

    if detected.get("prix_100") is None:
        detected["prix_100"] = rate_near([
            r"(\d[\d\s.,]*)\s*(?:€|â‚¬|eur|jpy|¥|?|usd|\$)\s*(?:pour\s*)?100\s*cartes",
        ], True)
    if detected.get("prix_200") is None:
        detected["prix_200"] = rate_near([
            r"(\d[\d\s.,]*)\s*(?:€|â‚¬|eur|jpy|¥|?|usd|\$)\s*(?:pour\s*)?200\s*cartes",
        ], True)
    if detected.get("port") is None:
        detected["port"] = rate_near([
            r"(?:port|livraison|shipping)[^\d]{0,20}(\d[\d\s.,]*)",
            r"(\d[\d\s.,]*)\s*(?:â‚¬|eur|jpy|?|usd|\$)?\s*(?:de\s*)?(?:port|livraison|shipping)",
        ])
    if detected.get("frais_paypal") in (None, 0, 0.0) and detected.get("frais_paypal_percent") is None:
        detected["frais_paypal"] = rate_near([r"(?:frais\s*)?paypal[^\d%]{0,30}(\d[\d\s.,]*)"])
    if detected["prix_100"] is None:
        detected["prix_100"] = rate_near([
            r"(\d[\d\s.,]*)\s*(?:€|â‚¬|eur|jpy|¥|?|usd|\$)\s*(?:for\s*)?100\s*cards?",
        ], True)
    if detected["prix_200"] is None:
        detected["prix_200"] = rate_near([
            r"(\d[\d\s.,]*)\s*(?:€|â‚¬|eur|jpy|¥|?|usd|\$)\s*(?:for\s*)?200\s*cards?",
        ], True)
    if "paypal" in low:
        detected["paiement"] = "PayPal"
        detected["paypal_gs"] = "oui" if ("g&s" in low or "goods" in low or "service" in low) else "inconnu"
    if "friends" in low or "f&f" in low:
        detected["paypal_gs"] = "non"
    if "tracking" in low or "suivi" in low:
        detected["tracking"] = "oui"
    if "sans suivi" in low or "no tracking" in low:
        detected["tracking"] = "non"
    if "video" in low or "vid?o" in low or "photo" in low:
        detected["photos_video"] = "partiel"
    if "near mint" in low or re.search(r"\bnm\b", low):
        detected["etat"] = "Near Mint"
    elif "excellent" in low:
        detected["etat"] = "Excellent"
    elif "mixed" in low:
        detected["etat"] = "Mixed"
    if "doublon" in low or "double" in low:
        detected["doublons"] = "moyen"
    if detected["prix_100"] is None:
        uncertainty.append("prix_100")
    if detected["prix_200"] is None:
        uncertainty.append("prix_200")
    if detected["devise"] != "EUR":
        uncertainty.append("conversion_rate_to_eur")
    recalculate_supplier(detected)
    heuristic_fields = []
    for field in ["prix_100", "prix_200", "port", "frais_paypal", "paiement", "paypal_gs", "tracking", "photos_video", "etat", "doublons", "type", "devise", "notes"]:
        if detected.get(field) not in (None, "", "inconnu", []):
            heuristic_fields.append(field)
    return {
        "supplier": normalize_supplier(detected),
        "uncertain_fields": uncertainty,
        "detected_fields": sorted(set(detected_fields) | set(heuristic_fields)),
        "import_format": "free_text",
        "import_hash": import_hash(raw),
        "source_text": raw,
        "price_history_candidate": make_price_history_entry(None, detected, source_type="free_text", source_text=raw),
    }


def extract_conversation_from_text(text: str) -> dict:
    raw = str(text or "")
    messages = []
    offers = []
    for line in raw.splitlines():
        content = line.strip()
        if not content:
            continue
        low = normalize_text(content)
        author = "unknown"
        if low.startswith(("me:", "moi:", "toi:", "you:")):
            author = "me"
            content = content.split(":", 1)[1].strip()
        elif low.startswith(("supplier:", "fournisseur:", "seller:", "vendeur:")):
            author = "supplier"
            content = content.split(":", 1)[1].strip()
        elif low.startswith(("note:",)):
            author = "note"
            content = content.split(":", 1)[1].strip()
        tags = []
        for token, tag in [
            ("paypal", "PayPal"),
            ("g&s", "PayPal"),
            ("tracking", "tracking"),
            ("suivi", "tracking"),
            ("photo", "photos"),
            ("video", "vid?o"),
            ("vid?o", "vid?o"),
            ("nm", "?tat"),
            ("near mint", "?tat"),
            ("doublon", "doublons"),
            ("shipping", "livraison"),
            ("livraison", "livraison"),
            ("accord", "accord"),
            ("ok", "accord"),
        ]:
            if token in low and tag not in tags:
                tags.append(tag)
        if re.search(r"\d", content) and any(symbol in low for symbol in ["â‚¬", "eur", "$", "usd", "jpy", "?"]):
            tags.append("prix")
            currency = "EUR" if ("â‚¬" in content or "eur" in low) else ("USD" if ("$" in content or "usd" in low) else "JPY")
            amount = parse_number(content, None)
            if amount is not None:
                offers.append(
                    normalize_negotiation_event(
                        {
                            "actor": author,
                            "event_type": "supplier_offer" if author == "supplier" else ("my_offer" if author == "me" else "negotiation_note"),
                            "amount": amount,
                            "currency": currency,
                            "notes": content,
                            "tags": tags,
                        }
                    )
                )
        messages.append(
            normalize_conversation_message(
                {
                    "author": author,
                    "content": content,
                    "tags": tags,
                    "source_type": "message_import",
                    "source_text": raw,
                }
            )
        )
    return {"messages": messages, "negotiation_events": offers}

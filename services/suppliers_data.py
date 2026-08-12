"""Local-only suppliers dataset access.

fournisseurs.json is intentionally not synchronized through the cloud service.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os

from core.suppliers import (
    default_suppliers_data,
    extract_offer_from_text,
    find_duplicate_supplier,
    import_hash,
    make_price_history_entry,
    make_offer_history_entry,
    normalize_supplier_identity,
    infer_supplier_family,
    infer_offer_variant,
    normalize_conversation_message,
    normalize_negotiation_event,
    normalize_supplier,
    normalize_suppliers_data,
    now_iso,
    parse_number,
    supplier_name_matches,
)
from utils import APP_DIR, safe_write_json


SUPPLIERS_FILE = os.path.join(APP_DIR, "fournisseurs.json")
REVIEW_REPARSE_VERSION = 12
LANDED_COST_MIGRATION_VERSION = 5
SUPPLIER_FAMILY_MIGRATION_VERSION = 2
SUPPLIERS_DECISION_CENTER_VERSION = 2


def load_suppliers(*, create_if_missing: bool = True) -> dict:
    if not os.path.exists(SUPPLIERS_FILE):
        data = default_suppliers_data()
        if create_if_missing:
            save_suppliers(data)
        return data
    try:
        with open(SUPPLIERS_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return default_suppliers_data()
    payload = normalize_suppliers_data(payload)
    payload = apply_landed_cost_manual_migration(payload)
    payload = apply_supplier_family_migration(payload)
    payload = apply_decision_center_migration(payload)
    return apply_local_conversion_rates(payload)


def _conversion_rate(settings: dict, currency: str):
    rates = (settings or {}).get("conversion_rates", {})
    item = rates.get(str(currency or "").upper(), {})
    return parse_number(item.get("rate_to_eur"), None)


def apply_local_conversion_rates(data: dict) -> dict:
    payload = normalize_suppliers_data(data)
    settings = payload.get("settings", {})
    changed = False
    for supplier in payload.get("suppliers", []):
        supplier_total = parse_number(supplier.get("supplier_total_source"), None)
        source_currency = (
            (supplier.get("supplier_total_source_currency") if supplier_total is not None else "")
            or supplier.get("cards_price_source_currency")
            or supplier.get("devise")
            or "EUR"
        )
        source_currency = str(source_currency or "EUR").upper()
        if source_currency == "EUR":
            continue
        rate = _conversion_rate(settings, source_currency)
        if rate and rate > 0 and supplier.get("conversion_rate_to_eur") != rate:
            supplier["conversion_rate_to_eur"] = rate
            supplier["conversion_rate_date"] = settings.get("conversion_rates", {}).get(source_currency, {}).get("updated_at", "")
            changed = True
    if changed:
        return save_suppliers(payload)
    return payload


def apply_decision_center_migration(data: dict) -> dict:
    payload = normalize_suppliers_data(data)
    maintenance = payload.setdefault("maintenance", {})
    if maintenance.get("decision_center_migration_version") == SUPPLIERS_DECISION_CENTER_VERSION:
        return payload
    updated = 0
    for supplier in payload.get("suppliers", []):
        if not supplier.get("follow_status"):
            supplier["follow_status"] = "À contacter"
        if not supplier.get("last_interaction_at"):
            supplier["last_interaction_at"] = supplier.get("last_review_at") or supplier.get("updated_at", "")
        if not supplier.get("supplier_aliases"):
            supplier["supplier_aliases"] = []
        if supplier.get("nom") and supplier.get("nom") not in supplier["supplier_aliases"]:
            supplier["supplier_aliases"].append(supplier.get("nom"))
        if supplier.get("supplier_family_key") == "primetcgwholesale" and not supplier.get("preferred_offer_variant"):
            supplier["preferred_offer_variant"] = "random bulk"
        if not supplier.get("test_order_checklist"):
            supplier["test_order_checklist"] = [
                {"label": "PayPal G&S confirmé", "done": supplier.get("paypal_gs") == "oui"},
                {"label": "Tracking confirmé", "done": supplier.get("tracking") == "oui"},
                {"label": "Photos ou vidéo reçues", "done": supplier.get("photos_video") in {"oui", "partiel"}},
                {"label": "État confirmé", "done": supplier.get("etat") not in {"inconnu", "à vérifier"}},
                {"label": "Doublons confirmés", "done": supplier.get("doublons") != "inconnu"},
                {"label": "Prix final confirmé", "done": supplier.get("landed_cost_estimated_eur") is not None},
                {"label": "Port confirmé", "done": supplier.get("shipping_price_source") is not None or supplier.get("shipping_status") == "included"},
            ]
        updated += 1
        for entry in supplier.get("import_history", []) or []:
            if not entry.get("source_text"):
                continue
            review = {
                "id": f"review_migrated_{entry.get('import_hash', '')[:12]}_{supplier.get('id')}",
                "created_at": entry.get("date") or supplier.get("updated_at") or now_iso(),
                "supplier_name": supplier.get("nom") or "",
                "format": entry.get("source_type") or "import",
                "result": "migrated",
                "linked_count": 1,
                "summary": supplier.get("last_review_summary") or supplier.get("action_recommandee") or "Ancienne review importée",
                "source_text": entry.get("source_text", ""),
            }
            history = payload.setdefault("review_history", [])
            if not any(item.get("id") == review["id"] or item.get("source_text") == review["source_text"] for item in history):
                history.append(review)
    maintenance["decision_center_migration_version"] = SUPPLIERS_DECISION_CENTER_VERSION
    maintenance["decision_center_migration_summary"] = {"suppliers_updated": updated}
    return save_suppliers(payload)


def apply_supplier_family_migration(data: dict) -> dict:
    payload = normalize_suppliers_data(data)
    maintenance = payload.setdefault("maintenance", {})
    if maintenance.get("supplier_family_migration_version") == SUPPLIER_FAMILY_MIGRATION_VERSION:
        return payload
    updated = 0
    linked_variants = 0
    for supplier in payload.get("suppliers", []):
        previous_key = supplier.get("supplier_family_key")
        family_name, family_key = infer_supplier_family(supplier.get("nom", ""))
        variant = infer_offer_variant(supplier.get("nom", ""))
        if not supplier.get("supplier_family_name"):
            supplier["supplier_family_name"] = family_name
        if not supplier.get("supplier_family_key"):
            supplier["supplier_family_key"] = family_key
        if not supplier.get("offer_variant"):
            supplier["offer_variant"] = variant
        if supplier.get("supplier_family_key") == "primetcgwholesale" and not supplier.get("offer_variant"):
            cards_price = parse_number(supplier.get("cards_price_source"), None)
            landed_min = parse_number(supplier.get("landed_cost_estimated_min_eur"), None)
            if cards_price == 50000 or landed_min == 361:
                supplier["offer_variant"] = "cartes choisies"
        if supplier.get("supplier_family_key") != previous_key:
            updated += 1
        if supplier.get("supplier_family_key") == "primetcgwholesale" and supplier.get("offer_variant"):
            linked_variants += 1
    maintenance["supplier_family_migration_version"] = SUPPLIER_FAMILY_MIGRATION_VERSION
    maintenance["supplier_family_migration_summary"] = {
        "families_updated": updated,
        "linked_variants": linked_variants,
    }
    return save_suppliers(payload)


def _manual_cost_entry(
    name: str,
    *,
    cards_price=None,
    currency="JPY",
    shipping_price=None,
    paypal_percent=None,
    paypal_fee=None,
    supplier_total=None,
    landed_min=None,
    landed_max=None,
    quantity=200,
    resale_total=None,
    payment="",
    shipping_status="",
    note="",
    risk_level=None,
    paypal_gs=None,
):
    if paypal_fee is None and supplier_total is not None and cards_price is not None and shipping_price is not None:
        paypal_fee = supplier_total - cards_price - shipping_price
    return {
        "nom": name,
        "quantity_reference": quantity,
        "cards_price_source": cards_price,
        "cards_price_source_currency": currency if cards_price is not None else "",
        "shipping_price_source": shipping_price,
        "shipping_price_source_currency": currency if shipping_price is not None and currency != "MIXED" else "",
        "shipping_status": shipping_status,
        "paypal_fee_source": paypal_fee,
        "paypal_fee_source_currency": currency if paypal_fee is not None and currency != "MIXED" else "",
        "paypal_fee_percent": paypal_percent,
        "supplier_total_source": supplier_total,
        "supplier_total_source_currency": currency if supplier_total is not None and currency != "MIXED" else "",
        "landed_cost_estimated_min_eur": landed_min,
        "landed_cost_estimated_max_eur": landed_max,
        "landed_cost_estimated_eur": ((landed_min + landed_max) / 2.0) if landed_min is not None and landed_max is not None else None,
        "estimated_resale_total_eur": resale_total,
        "paiement": payment,
        "cost_notes": note,
        "risk_level": risk_level,
        "paypal_gs": paypal_gs,
    }


def _manual_landed_costs() -> list[dict]:
    return [
        _manual_cost_entry("Japan TCG Exchange", cards_price=42800, shipping_price=6000, paypal_percent=5, supplier_total=51240, landed_min=346, landed_max=356, note="Reference utilisateur : cartes seules 42800 JPY, port 48800 JPY, PayPal 51240 JPY."),
        _manual_cost_entry("KK Export Japan", cards_price=53500, shipping_price=4800, paypal_percent=5, supplier_total=61215, landed_min=410, landed_max=420, resale_total=655, note="Reference utilisateur speciale : revente estimee 655 EUR."),
        _manual_cost_entry("K.K. Export Japan", cards_price=53500, shipping_price=4800, paypal_percent=5, supplier_total=61215, landed_min=410, landed_max=420, resale_total=655, note="Reference utilisateur speciale : variante doublon KK, revente estimee 655 EUR."),
        _manual_cost_entry("Conatsu", cards_price=53000, shipping_price=5000, paypal_percent=5, supplier_total=60900, landed_min=408, landed_max=418),
        _manual_cost_entry("H.TCG Japan", cards_price=53000, shipping_price=5800, paypal_percent=5, supplier_total=61740, landed_min=414, landed_max=424, note="Scenario avec doublons."),
        _manual_cost_entry("Kenji Araki", cards_price=54000, shipping_price=4500, paypal_percent=5, supplier_total=61425, landed_min=412, landed_max=422, note="Scenario non sleeved, port minimum."),
        _manual_cost_entry("Kenji Araki - sleeved port minimum", cards_price=57000, shipping_price=4500, paypal_percent=5, supplier_total=64575, landed_min=432, landed_max=442),
        _manual_cost_entry("Shunsuke Yoshinaga", cards_price=55000, shipping_price=6000, paypal_percent=5, supplier_total=64050, landed_min=428, landed_max=438, note="Scenario avec doublons."),
        _manual_cost_entry("Shunsuke Yoshinaga - sans doublons", cards_price=57000, shipping_price=6000, paypal_percent=5, supplier_total=66150, landed_min=442, landed_max=452),
        _manual_cost_entry("Yusuke Matsumoto", cards_price=56000, shipping_price=4700, paypal_percent=5, supplier_total=63735, landed_min=426, landed_max=436),
        _manual_cost_entry("TCG Wholesale", cards_price=40000, currency="JPY", shipping_status="about_20_usd", landed_min=296, landed_max=306, payment="Revolut / virement", risk_level="high", paypal_gs="non", note="Prime TCG Wholesale random bulk : tres peu cher, paiement non protege et bulk aleatoire."),
        _manual_cost_entry("Prime TCG Wholesale - cartes choisies", cards_price=50000, currency="JPY", shipping_status="about_20_usd", landed_min=361, landed_max=371, payment="Revolut / virement", risk_level="high", paypal_gs="non", note="Interessant pour composer un lot fort, risque paiement."),
        _manual_cost_entry("Rare Pulls Japan", currency="USD", supplier_total=310, shipping_status="included", landed_min=340, landed_max=350, note="310 USD annonce livre ; contenu faible selon video."),
        _manual_cost_entry("Shingo Hashimoto", cards_price=55000, shipping_status="unknown", note="Cartes seules 275 JPY/carte ; attendre offre finale port et PayPal."),
        _manual_cost_entry("Vallex TCG Shop", cards_price=56000, shipping_status="unknown", payment="Wise", paypal_gs="non", note="Bulk standard 280 JPY/carte ; trop cher face a Japan TCG Exchange si contenu standard."),
        _manual_cost_entry("Koki Yamashita", cards_price=54000, shipping_status="unknown", note="Correction : 270 JPY/carte, pas 2 JPY/carte."),
        _manual_cost_entry("Japan TCG Export Shop", cards_price=52000, shipping_status="unknown", paypal_gs="non", note="Prix bulk potentiel, risque paiement + condition."),
        _manual_cost_entry("Samurai TCG Japan", shipping_status="unknown", paypal_gs="inconnu", note="Prix inconnu, devis PayPal en attente ; prometteur NM+, max 2 exemplaires, singles ajoutables."),
        _manual_cost_entry("TCG Shop Kasumi Japan", shipping_status="unknown", note="Prix inconnu, en attente, condition LP ; peu adapte meme si prix bas."),
        _manual_cost_entry("Vallex premium", cards_price=78000, shipping_status="unknown", payment="Wise", paypal_gs="non", note="Premium 390 JPY/carte ; rendu France probablement trop eleve, pas rentable comme bulk classique."),
    ]


def _find_supplier_by_identity(suppliers: list[dict], name: str) -> dict | None:
    key = normalize_supplier_identity(name)
    for supplier in suppliers:
        if normalize_supplier_identity(supplier.get("nom", "")) == key:
            return supplier
    return None


def apply_landed_cost_manual_migration(data: dict) -> dict:
    payload = normalize_suppliers_data(data)
    maintenance = payload.setdefault("maintenance", {})
    if maintenance.get("landed_cost_migration_version") == LANDED_COST_MIGRATION_VERSION:
        return payload
    changed = False
    updated = 0
    created = 0
    for entry in _manual_landed_costs():
        target = _find_supplier_by_identity(payload["suppliers"], entry["nom"])
        if target is None:
            target = normalize_supplier({"nom": entry["nom"], "type": "Japon", "statut": "à contacter"})
            payload["suppliers"].append(target)
            created += 1
        for field, value in entry.items():
            if field == "nom" or value in (None, ""):
                continue
            target[field] = value
        source_currency = (
            entry.get("supplier_total_source_currency")
            or entry.get("cards_price_source_currency")
            or entry.get("devise")
            or target.get("devise")
        )
        if source_currency and source_currency != "EUR":
            target["conversion_rate_to_eur"] = None
        if entry.get("shipping_status") in {"unknown", "about_20_usd", "included"} and entry.get("shipping_price_source") is None:
            target["shipping_price_source"] = None
            target["shipping_price_source_currency"] = ""
            target["port"] = None
        if entry.get("supplier_total_source") is None and entry.get("shipping_status") in {"unknown", "about_20_usd"}:
            target["supplier_total_source"] = None
            target["supplier_total_source_currency"] = ""
        if entry.get("landed_cost_estimated_min_eur") is None and entry.get("landed_cost_estimated_max_eur") is None:
            for landed_field in [
                "landed_cost_estimated_source",
                "landed_cost_estimated_currency",
                "landed_cost_estimated_eur",
                "landed_cost_estimated_min_eur",
                "landed_cost_estimated_max_eur",
                "landed_cost_per_card_eur",
                "landed_cost_per_card_min_eur",
                "landed_cost_per_card_max_eur",
                "purchase_percentage_of_resale",
                "purchase_percentage_of_resale_min",
                "purchase_percentage_of_resale_max",
                "estimated_margin_eur",
                "estimated_margin_min_eur",
                "estimated_margin_max_eur",
                "estimated_margin_percent",
                "estimated_margin_percent_min",
                "estimated_margin_percent_max",
            ]:
                target[landed_field] = None
        if entry.get("paypal_fee_source") is None and entry.get("paypal_fee_percent") is None:
            target["paypal_fee_source"] = None
            target["paypal_fee_source_currency"] = ""
        if entry.get("cards_price_source") is None and entry.get("supplier_total_source") is not None:
            target["cards_price_source"] = None
            target["cards_price_source_currency"] = ""
            target["prix_100"] = None
            target["prix_200"] = None
        if entry.get("cards_price_source") is not None:
            target["prix_200"] = entry["cards_price_source"] if entry.get("quantity_reference", 200) == 200 else target.get("prix_200")
            target["devise"] = entry.get("cards_price_source_currency") or target.get("devise") or "JPY"
        if entry.get("shipping_price_source") is not None:
            target["port"] = entry["shipping_price_source"]
        if entry.get("paypal_fee_percent") is not None:
            target["frais_paypal_percent"] = entry["paypal_fee_percent"]
        if target.get("nom") == "Koki Yamashita" and parse_number(target.get("prix_unitaire_estime"), None) is not None and target.get("prix_unitaire_estime") <= 10:
            target["prix_unitaire_estime"] = None
        target["updated_at"] = now_iso()
        updated += 1
        changed = True
    maintenance["landed_cost_migration_version"] = LANDED_COST_MIGRATION_VERSION
    maintenance["landed_cost_migration_summary"] = {"updated": updated, "created": created}
    if changed:
        return save_suppliers(payload)
    return payload


def save_suppliers(data: dict) -> dict:
    payload = normalize_suppliers_data(data)
    safe_write_json(SUPPLIERS_FILE, payload, indent=2)
    return payload


def _supplier_source_texts(supplier: dict) -> list[str]:
    texts = []
    for value in [supplier.get("notes"), supplier.get("source_text")]:
        if value:
            texts.append(str(value))
    for list_name in ["import_history", "offers_history", "price_history"]:
        for item in supplier.get(list_name, []) if isinstance(supplier.get(list_name), list) else []:
            source = item.get("source_text") if isinstance(item, dict) else ""
            if source:
                texts.append(str(source))
    seen = set()
    unique = []
    for text in texts:
        key = import_hash(text)
        if key not in seen:
            seen.add(key)
            unique.append(text)
    return unique


def _missing_or_invalid(value) -> bool:
    parsed = parse_number(value, None)
    return parsed is None or parsed <= 0


def repair_existing_supplier_reviews(data: dict) -> tuple[dict, dict]:
    payload = normalize_suppliers_data(data)
    maintenance = payload.setdefault("maintenance", {})
    previous_version = maintenance.get("review_reparse_version") or 0
    correcting_previous_auto = previous_version and previous_version < REVIEW_REPARSE_VERSION
    if maintenance.get("review_reparse_version") == REVIEW_REPARSE_VERSION:
        return payload, maintenance.get("review_reparse_summary", {"already_done": True})
    summary = {
        "already_done": False,
        "suppliers_reanalyzed": 0,
        "suppliers_completed": 0,
        "prix_100_added": 0,
        "prix_200_added": 0,
        "devise_added": 0,
        "latest_offer_added": 0,
        "paypal_percent_added": 0,
    }
    fields = [
        "prix_100",
        "prix_200",
        "price_status",
        "latest_offer",
        "latest_offer_amount",
        "latest_offer_currency",
        "latest_offer_quantity",
        "latest_offer_shipping_included",
        "latest_offer_quantity_inferred",
        "frais_paypal_percent",
        "frais_paypal_fixed",
        "port",
        "paiement",
        "paypal_gs",
        "tracking",
        "photos_video",
        "etat",
        "doublons",
        "risk_level",
        "confiance_note",
        "service_note",
        "contenu_note",
        "potentiel_negociation_note",
        "action_recommandee",
        "derniere_analyse",
    ]
    for supplier in payload.get("suppliers", []):
        source_texts = _supplier_source_texts(supplier)
        if not source_texts:
            continue
        summary["suppliers_reanalyzed"] += 1
        changed = False
        for source in source_texts:
            parsed = extract_offer_from_text(source)
            candidate = normalize_supplier(parsed.get("supplier"))
            if correcting_previous_auto and candidate.get("price_status") and candidate.get("prix_100") is None and not _missing_or_invalid(supplier.get("prix_100")):
                supplier["prix_100"] = None
                supplier["prix_final_estime"] = None
                supplier["prix_unitaire_estime"] = None
                changed = True
            if correcting_previous_auto and candidate.get("price_status") and candidate.get("prix_200") is None and not _missing_or_invalid(supplier.get("prix_200")):
                supplier["prix_200"] = None
                supplier["prix_final_estime"] = None
                supplier["prix_unitaire_estime"] = None
                changed = True
            if correcting_previous_auto and candidate.get("prix_200") is None and candidate.get("port") is not None:
                current_200 = parse_number(supplier.get("prix_200"), None)
                candidate_port = parse_number(candidate.get("port"), None)
                if current_200 is not None and candidate_port is not None and abs(current_200 - candidate_port) < 0.0001:
                    supplier["prix_200"] = None
                    supplier["prix_final_estime"] = None
                    supplier["prix_unitaire_estime"] = None
                    changed = True
            for field in fields:
                value = candidate.get(field)
                if value in (None, "", [], "unknown"):
                    continue
                if field in {"latest_offer", "latest_offer_amount", "latest_offer_quantity"}:
                    if supplier.get("latest_offer_quantity") == 200 and candidate.get("latest_offer_quantity") != 200:
                        continue
                    if not correcting_previous_auto and not _missing_or_invalid(supplier.get(field)):
                        continue
                elif field in {"prix_100", "prix_200", "frais_paypal_percent", "frais_paypal_fixed", "port"}:
                    if not correcting_previous_auto and not _missing_or_invalid(supplier.get(field)):
                        continue
                elif field == "devise":
                    if supplier.get("devise") and supplier.get("devise") != "EUR":
                        continue
                elif field in {"latest_offer_shipping_included", "latest_offer_quantity_inferred"}:
                    if not value:
                        continue
                elif supplier.get(field) not in (None, "", [], "unknown", "inconnu"):
                    continue
                supplier[field] = value
                changed = True
                if field == "prix_100":
                    summary["prix_100_added"] += 1
                elif field == "prix_200":
                    summary["prix_200_added"] += 1
                elif field == "latest_offer_amount":
                    summary["latest_offer_added"] += 1
                elif field == "frais_paypal_percent":
                    summary["paypal_percent_added"] += 1
            candidate_currency = candidate.get("devise")
            if candidate_currency and candidate_currency != "EUR" and (supplier.get("devise") in (None, "", "EUR", "Autre") or correcting_previous_auto):
                supplier["devise"] = candidate_currency
                supplier["conversion_rate_to_eur"] = None
                summary["devise_added"] += 1
                changed = True
        if changed:
            supplier["updated_at"] = now_iso()
            summary["suppliers_completed"] += 1
    maintenance["review_reparse_version"] = REVIEW_REPARSE_VERSION
    maintenance["review_reparse_summary"] = summary
    if summary["suppliers_completed"]:
        return save_suppliers(payload), summary
    save_suppliers(payload)
    return payload, summary


def _import_trace(import_hash_value: str, source_type: str, source_text: str) -> dict:
    return {
        "id": f"import_{import_hash_value[:12]}",
        "date": now_iso(),
        "import_hash": import_hash_value,
        "source_type": source_type,
        "source_text": source_text,
    }


def _review_entry(parsed: dict, status: str, supplier_name: str = "", linked_count: int = 0) -> dict:
    supplier = parsed.get("supplier", {}) if isinstance(parsed, dict) else {}
    summary_bits = []
    for field in ["derniere_analyse", "action_recommandee", "price_status"]:
        if supplier.get(field):
            summary_bits.append(str(supplier.get(field)).strip())
    if supplier.get("prix_200"):
        summary_bits.append(f"Prix 200: {supplier.get('prix_200')} {supplier.get('devise') or ''}".strip())
    return {
        "id": f"review_{now_iso().replace(':', '').replace('-', '')}_{(parsed.get('import_hash') or '')[:8]}",
        "created_at": now_iso(),
        "supplier_name": supplier_name or supplier.get("nom") or "",
        "format": parsed.get("import_format"),
        "result": status,
        "linked_count": linked_count,
        "summary": " · ".join(summary_bits[:2]) or "Review importée",
        "source_text": parsed.get("source_text", ""),
    }


def _append_review_history(payload: dict, parsed: dict, status: str, supplier_name: str = "", linked_count: int = 0) -> None:
    entry = _review_entry(parsed, status, supplier_name, linked_count)
    history = payload.setdefault("review_history", [])
    if not any(item.get("id") == entry["id"] or item.get("source_text") == entry["source_text"] for item in history):
        history.insert(0, entry)
        del history[25:]


def _touch_supplier_review_fields(supplier: dict, parsed: dict, result: str, source_text: str) -> dict:
    entry = _review_entry(parsed, result, supplier.get("nom") or "")
    supplier["last_review_at"] = entry["created_at"]
    supplier["last_review_type"] = parsed.get("import_format") or ""
    supplier["last_review_result"] = result
    supplier["last_review_summary"] = entry["summary"]
    supplier["last_interaction_at"] = entry["created_at"]
    supplier.setdefault("review_history", list(supplier.get("review_history", []))).insert(0, entry)
    supplier["review_history"] = supplier.get("review_history", [])[:10]
    supplier.setdefault("import_history", list(supplier.get("import_history", []))).append(_import_trace(parsed.get("import_hash") or import_hash(source_text), parsed.get("import_format"), source_text))
    return supplier


def _merge_detected_fields(existing: dict, candidate: dict, detected_fields: list[str]) -> dict:
    merged = dict(existing)
    for field in detected_fields:
        if field in {"id", "created_at", "updated_at", "notes"}:
            continue
        value = candidate.get(field)
        if value in (None, "", [], "unknown"):
            continue
        merged[field] = value
    merged["id"] = existing.get("id")
    merged["created_at"] = existing.get("created_at")
    return normalize_supplier(merged)


def _has_imported(supplier: dict, import_hash_value: str) -> bool:
    return any(item.get("import_hash") == import_hash_value for item in supplier.get("import_history", []))


GENERAL_UPDATE_FIELDS = {
    "statut", "contact_link", "pays", "type", "paiement", "paypal_gs",
    "tracking", "photos_video", "risk_level", "market_position", "best_for",
    "derniere_analyse", "action_recommandee", "pros", "cons", "notes",
    "analysis_updated_at", "review_last_updated",
}
SPECIFIC_UPDATE_FIELDS = {
    "prix_100", "prix_200", "latest_offer", "latest_offer_amount",
    "latest_offer_quantity", "port", "frais_paypal", "frais_paypal_fixed",
    "frais_paypal_percent", "cards_price_source", "shipping_price_source",
    "paypal_fee_source", "paypal_fee_percent", "supplier_total_source",
    "landed_cost_estimated_eur", "landed_cost_estimated_min_eur",
    "landed_cost_estimated_max_eur", "offer_variant",
}


def _is_specific_supplier_update(parsed: dict) -> bool:
    detected = set(parsed.get("detected_fields") or [])
    if detected & SPECIFIC_UPDATE_FIELDS:
        return True
    low = normalize_supplier_identity(parsed.get("source_text", ""))
    return any(token in low for token in [
        "offervariant", "randombulk", "carteschoisies", "chosen", "selected",
        "sleeved", "nonsleeved", "avecdoublons", "sansdoublons",
    ])


def _family_matches(suppliers: list[dict], family_key: str) -> list[dict]:
    if not family_key:
        return []
    return [supplier for supplier in suppliers if supplier.get("supplier_family_key") == family_key]


def _matching_variant(family_matches: list[dict], variant: str) -> list[dict]:
    key = normalize_supplier_identity(variant)
    if not key:
        return []
    return [
        supplier for supplier in family_matches
        if normalize_supplier_identity(supplier.get("offer_variant", "")) == key
        or key in normalize_supplier_identity(supplier.get("nom", ""))
    ]


def _add_pending_import(payload: dict, parsed: dict, reason: str) -> dict:
    pending = payload.setdefault("pending_imports", [])
    hash_value = parsed.get("import_hash") or import_hash(parsed.get("source_text", ""))
    if any(item.get("import_hash") == hash_value for item in pending):
        return payload
    supplier = parsed.get("supplier", {})
    pending.append({
        "id": f"pending_{hash_value[:12]}",
        "created_at": now_iso(),
        "import_hash": hash_value,
        "format": parsed.get("import_format"),
        "reason": reason,
        "supplier_name": supplier.get("nom"),
        "summary": {
            "prix_100": supplier.get("prix_100"),
            "prix_200": supplier.get("prix_200"),
            "latest_offer": supplier.get("latest_offer"),
            "devise": supplier.get("devise"),
            "risk_level": supplier.get("risk_level"),
        },
        "source_text": parsed.get("source_text", ""),
        "parsed_supplier": supplier,
        "detected_fields": parsed.get("detected_fields", []),
        "warnings": parsed.get("warnings", []),
    })
    return payload


def apply_supplier_import(data: dict, source_text: str, *, automatic: bool = True) -> tuple[dict, dict]:
    payload = apply_supplier_family_migration(normalize_suppliers_data(data))
    payload.setdefault("pending_imports", [])
    parsed = extract_offer_from_text(source_text)
    candidate = normalize_supplier(parsed.get("supplier"))
    detected_fields = parsed.get("detected_fields", [])
    hash_value = parsed.get("import_hash") or import_hash(source_text)
    matches = supplier_name_matches(payload.get("suppliers", []), candidate.get("nom", ""))
    exact = find_duplicate_supplier(payload.get("suppliers", []), candidate)
    if exact and all(item.get("id") != exact.get("id") for item in matches):
        matches.insert(0, exact)
    has_price = bool(candidate.get("prix_100") or candidate.get("prix_200") or candidate.get("latest_offer"))
    import_format = parsed.get("import_format")
    structured = import_format in {"supplier_review_v1", "supplier_update"}
    is_update = import_format == "supplier_update"
    family_key = candidate.get("supplier_family_key") or infer_supplier_family(candidate.get("nom", ""))[1]
    family_matches = _family_matches(payload.get("suppliers", []), family_key)
    specific_update = _is_specific_supplier_update(parsed)
    variant_matches = _matching_variant(family_matches, candidate.get("offer_variant", ""))

    reasons = []
    if not candidate.get("nom"):
        reasons.append("nom fournisseur absent")
    if parsed.get("warnings"):
        reasons.extend(parsed.get("warnings"))
    if len(matches) > 1 and not (is_update and family_matches and not specific_update):
        reasons.append("plusieurs fournisseurs proches")
    if is_update and not matches and not family_matches:
        reasons.append("mise a jour sans fournisseur correspondant fiable")
    if is_update and specific_update and len(family_matches) > 1 and not variant_matches:
        preferred = next((item for item in family_matches if item.get("offer_variant") and item.get("offer_variant") == item.get("preferred_offer_variant")), None)
        if preferred is None:
            preferred = next((item for item in family_matches if item.get("preferred_offer_variant") and normalize_supplier_identity(item.get("preferred_offer_variant")) in normalize_supplier_identity(item.get("offer_variant", ""))), None)
        if preferred is not None:
            variant_matches = [preferred]
        else:
            reasons.append("mise a jour d'offre precise sans variante identifiable")
    if candidate.get("devise") == "Autre":
        reasons.append("devise inconnue")
    if not structured and len(detected_fields) < 5:
        reasons.append("texte libre trop incomplet")
    if structured and not is_update and not has_price and len(detected_fields) < 8:
        reasons.append("review trop incomplete")
    if reasons:
        payload = _add_pending_import(payload, parsed, "; ".join(reasons))
        return save_suppliers(payload), {"status": "pending", "parsed": parsed, "reason": "; ".join(reasons)}

    if is_update and family_matches and not specific_update:
        general_fields = [field for field in detected_fields if field in GENERAL_UPDATE_FIELDS]
        if not general_fields:
            general_fields = [field for field in detected_fields if field not in SPECIFIC_UPDATE_FIELDS]
        updated_suppliers = []
        for existing in family_matches:
            if _has_imported(existing, hash_value):
                continue
            updated = _merge_detected_fields(existing, candidate, general_fields)
            updated["supplier_family_name"] = existing.get("supplier_family_name")
            updated["supplier_family_key"] = existing.get("supplier_family_key")
            updated["offer_variant"] = existing.get("offer_variant")
            updated = _touch_supplier_review_fields(updated, parsed, "family_updated", source_text)
            updated["updated_at"] = now_iso()
            for idx, supplier in enumerate(payload["suppliers"]):
                if supplier.get("id") == existing.get("id"):
                    payload["suppliers"][idx] = normalize_supplier(updated)
                    break
            updated_suppliers.append(updated)
        if updated_suppliers:
            _append_review_history(payload, parsed, "family_updated", candidate.get("supplier_family_name") or family_matches[0].get("supplier_family_name"), len(updated_suppliers))
            return save_suppliers(payload), {
                "status": "family_updated",
                "supplier_family_name": candidate.get("supplier_family_name") or family_matches[0].get("supplier_family_name"),
                "linked_count": len(updated_suppliers),
                "parsed": parsed,
            }
        return payload, {"status": "duplicate", "supplier": family_matches[0], "parsed": parsed}

    if is_update and specific_update and variant_matches:
        matches = variant_matches

    if len(matches) == 1:
        existing = matches[0]
        if _has_imported(existing, hash_value):
            return payload, {"status": "duplicate", "supplier": existing, "parsed": parsed}
        updated = _merge_detected_fields(existing, candidate, detected_fields)
        if is_update:
            updated["nom"] = existing.get("nom")
            updated["supplier_family_name"] = existing.get("supplier_family_name")
            updated["supplier_family_key"] = existing.get("supplier_family_key")
            updated["offer_variant"] = existing.get("offer_variant")
        price_entry = make_price_history_entry(existing, updated, source_type=parsed.get("import_format") or "message_import", source_text=source_text)
        if price_entry and price_entry.get("ancien_prix") == price_entry.get("nouveau_prix"):
            price_entry = None
        if price_entry:
            updated.setdefault("price_history", list(existing.get("price_history", []))).append(price_entry)
        updated = _touch_supplier_review_fields(updated, parsed, "updated", source_text)
        updated["updated_at"] = now_iso()
        for idx, supplier in enumerate(payload["suppliers"]):
            if supplier.get("id") == existing.get("id"):
                payload["suppliers"][idx] = normalize_supplier(updated)
                break
        _append_review_history(payload, parsed, "updated", updated.get("nom") or "")
        return save_suppliers(payload), {"status": "updated", "supplier": updated, "parsed": parsed, "price_history_added": bool(price_entry)}

    if is_update:
        payload = _add_pending_import(payload, parsed, "mise a jour fournisseur a verifier")
        return save_suppliers(payload), {"status": "pending", "parsed": parsed, "reason": "mise a jour fournisseur a verifier"}

    if candidate.get("nom") and import_format == "supplier_review_v1" and (structured or has_price):
        if any(_has_imported(item, hash_value) for item in payload.get("suppliers", [])):
            return payload, {"status": "duplicate_other", "parsed": parsed}
        candidate = _touch_supplier_review_fields(candidate, parsed, "created", source_text)
        price_entry = make_price_history_entry(None, candidate, source_type=parsed.get("import_format") or "message_import", source_text=source_text)
        if price_entry:
            candidate.setdefault("price_history", []).append(price_entry)
        payload["suppliers"].append(normalize_supplier(candidate))
        _append_review_history(payload, parsed, "created", candidate.get("nom") or "")
        return save_suppliers(payload), {"status": "created", "supplier": candidate, "parsed": parsed, "price_history_added": bool(price_entry)}

    payload = _add_pending_import(payload, parsed, "import ambigu")
    return save_suppliers(payload), {"status": "pending", "parsed": parsed, "reason": "import ambigu"}


def duplicate_supplier_groups(data: dict) -> list[dict]:
    payload = normalize_suppliers_data(data)
    ignored = {tuple(sorted(pair)) for pair in payload.get("ignored_duplicate_pairs", []) if isinstance(pair, list) and len(pair) == 2}
    groups: dict[str, list[dict]] = {}
    for supplier in payload.get("suppliers", []):
        if supplier.get("statut") == "archivé":
            continue
        key = normalize_supplier_identity(supplier.get("nom", ""))
        if not key:
            continue
        groups.setdefault(key, []).append(supplier)
        for alias in supplier.get("supplier_aliases", []) or []:
            alias_key = normalize_supplier_identity(alias)
            if alias_key:
                groups.setdefault(alias_key, []).append(supplier)
        contact_key = normalize_supplier_identity(supplier.get("contact_link", ""))
        if contact_key:
            groups.setdefault(f"contact_{contact_key}", []).append(supplier)
    result = []
    seen_group_keys = set()
    for key, values in groups.items():
        unique = []
        seen_ids = set()
        for item in values:
            if item.get("id") not in seen_ids:
                unique.append(item)
                seen_ids.add(item.get("id"))
        if len(unique) <= 1:
            continue
        pair_ids = sorted(item.get("id") for item in unique)
        if any(tuple(sorted([left, right])) in ignored for left in pair_ids for right in pair_ids if left != right):
            continue
        group_key = "|".join(pair_ids)
        if group_key in seen_group_keys:
            continue
        seen_group_keys.add(group_key)
        result.append({"identity": key, "suppliers": unique})
    return result


def merge_suppliers(data: dict, keep_id: str, merge_id: str) -> dict:
    payload = normalize_suppliers_data(data)
    if keep_id == merge_id:
        return payload
    suppliers = payload.get("suppliers", [])
    keep = next((item for item in suppliers if item.get("id") == keep_id), None)
    merge = next((item for item in suppliers if item.get("id") == merge_id), None)
    if not keep or not merge:
        return payload
    merged = dict(keep)
    for field, value in merge.items():
        if field in {"id", "created_at", "updated_at"}:
            continue
        if field in {"offers_history", "price_history", "import_history", "negotiation_history", "conversation_history", "pros", "cons", "best_for_tags", "specialites", "supplier_aliases", "review_history"}:
            combined = list(merged.get(field) or [])
            seen = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in combined if isinstance(item, (dict, list))}
            seen.update(str(item) for item in combined if not isinstance(item, (dict, list)))
            for entry in value or []:
                key = json.dumps(entry, sort_keys=True, ensure_ascii=False) if isinstance(entry, (dict, list)) else str(entry)
                if key not in seen:
                    combined.append(entry)
                    seen.add(key)
            merged[field] = combined
            continue
        current = merged.get(field)
        if current in (None, "", [], "unknown", "inconnu") and value not in (None, "", [], "unknown", "inconnu"):
            merged[field] = value
    aliases = list(merged.get("supplier_aliases") or [])
    for alias in [merge.get("nom"), *(merge.get("supplier_aliases") or [])]:
        if alias and alias not in aliases:
            aliases.append(alias)
    merged["supplier_aliases"] = aliases
    merged["updated_at"] = now_iso()
    archived = dict(merge)
    archived["statut"] = "archivé"
    archived["archived_by_merge_into"] = keep_id
    archived["updated_at"] = now_iso()
    payload["suppliers"] = [
        normalize_supplier(merged) if item.get("id") == keep_id
        else normalize_supplier(archived) if item.get("id") == merge_id
        else item
        for item in suppliers
    ]
    return save_suppliers(payload)


def ignore_duplicate_pair(data: dict, left_id: str, right_id: str) -> dict:
    payload = normalize_suppliers_data(data)
    if left_id == right_id:
        return payload
    pair = sorted([left_id, right_id])
    ignored = payload.setdefault("ignored_duplicate_pairs", [])
    if pair not in ignored:
        ignored.append(pair)
    return save_suppliers(payload)


def delete_pending_import(data: dict, pending_id: str) -> dict:
    payload = normalize_suppliers_data(data)
    payload["pending_imports"] = [item for item in payload.get("pending_imports", []) if item.get("id") != pending_id]
    return save_suppliers(payload)


def upsert_supplier(data: dict, supplier: dict, *, add_history: bool = False, source_type: str = "manual", source_text: str = "") -> dict:
    payload = normalize_suppliers_data(data)
    supplier = normalize_supplier(deepcopy(supplier))
    supplier["updated_at"] = now_iso()
    if add_history:
        supplier.setdefault("offers_history", []).append(
            make_offer_history_entry(supplier, source_type=source_type, source_text=source_text)
        )
    replaced = False
    for index, current in enumerate(payload["suppliers"]):
        if current.get("id") == supplier.get("id"):
            existing_history = current.get("offers_history", [])
            existing_price_history = current.get("price_history", [])
            if not add_history:
                supplier["offers_history"] = existing_history
            if not supplier.get("price_history"):
                supplier["price_history"] = existing_price_history
            payload["suppliers"][index] = supplier
            replaced = True
            break
    if not replaced:
        if not supplier.get("offers_history"):
            supplier["offers_history"] = [make_offer_history_entry(supplier, source_type=source_type, source_text=source_text)]
        payload["suppliers"].append(supplier)
    return save_suppliers(payload)


def delete_supplier(data: dict, supplier_id: str) -> dict:
    payload = normalize_suppliers_data(data)
    payload["suppliers"] = [item for item in payload["suppliers"] if item.get("id") != supplier_id]
    return save_suppliers(payload)


def duplicate_offer(data: dict, supplier_id: str) -> dict:
    payload = normalize_suppliers_data(data)
    for supplier in payload["suppliers"]:
        if supplier.get("id") == supplier_id:
            supplier.setdefault("offers_history", []).append(make_offer_history_entry(supplier, source_type="manual"))
            supplier["updated_at"] = now_iso()
            break
    return save_suppliers(payload)


def detect_duplicate(data: dict, candidate: dict) -> dict | None:
    payload = normalize_suppliers_data(data)
    return find_duplicate_supplier(payload["suppliers"], candidate)


def _find_supplier(payload: dict, supplier_id: str) -> dict | None:
    for supplier in payload.get("suppliers", []):
        if supplier.get("id") == supplier_id:
            return supplier
    return None


def save_negotiation_event(data: dict, supplier_id: str, event: dict) -> dict:
    payload = normalize_suppliers_data(data)
    supplier = _find_supplier(payload, supplier_id)
    if not supplier:
        return payload
    event = normalize_negotiation_event(event)
    events = supplier.setdefault("negotiation_history", [])
    for idx, current in enumerate(events):
        if current.get("id") == event.get("id"):
            event["created_at"] = current.get("created_at") or event["created_at"]
            event["updated_at"] = now_iso()
            events[idx] = event
            break
    else:
        events.append(event)
    supplier["updated_at"] = now_iso()
    return save_suppliers(payload)


def delete_negotiation_event(data: dict, supplier_id: str, event_id: str) -> dict:
    payload = normalize_suppliers_data(data)
    supplier = _find_supplier(payload, supplier_id)
    if supplier:
        supplier["negotiation_history"] = [
            item for item in supplier.get("negotiation_history", [])
            if item.get("id") != event_id
        ]
        supplier["updated_at"] = now_iso()
    return save_suppliers(payload)


def save_conversation_message(data: dict, supplier_id: str, message: dict) -> dict:
    payload = normalize_suppliers_data(data)
    supplier = _find_supplier(payload, supplier_id)
    if not supplier:
        return payload
    message = normalize_conversation_message(message)
    messages = supplier.setdefault("conversation_history", [])
    for idx, current in enumerate(messages):
        if current.get("id") == message.get("id"):
            message["created_at"] = current.get("created_at") or message["created_at"]
            message["updated_at"] = now_iso()
            messages[idx] = message
            break
    else:
        messages.append(message)
    supplier["updated_at"] = now_iso()
    return save_suppliers(payload)


def delete_conversation_message(data: dict, supplier_id: str, message_id: str) -> dict:
    payload = normalize_suppliers_data(data)
    supplier = _find_supplier(payload, supplier_id)
    if supplier:
        supplier["conversation_history"] = [
            item for item in supplier.get("conversation_history", [])
            if item.get("id") != message_id
        ]
        supplier["updated_at"] = now_iso()
    return save_suppliers(payload)

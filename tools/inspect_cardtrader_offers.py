from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRICE_AUDIT = ROOT / "market_cardtrader_price_audit.json"
OUTPUT = ROOT / "market_cardtrader_offers_inspection.json"
SNAPSHOTS = ROOT / "market_price_snapshots.json"

sys.path.insert(0, str(ROOT))

from services.cardtrader_api import CardTraderReadOnlyClient, load_cardtrader_token  # noqa: E402
from tools.test_cardtrader_fr_nm import as_list, first_present, norm  # noqa: E402


CONDITION_MAP = {
    "nearmint": "Near Mint",
    "nm": "Near Mint",
    "excellent": "Excellent",
    "ex": "Excellent",
    "good": "Good",
    "gd": "Good",
    "lightplayed": "Light Played",
    "lp": "Light Played",
    "played": "Played",
    "pl": "Played",
    "poor": "Poor",
    "po": "Poor",
}

LANGUAGE_KEYS = ("pokemon_language", "language")
CONDITION_KEYS = ("condition", "pokemon_condition")
FOIL_KEYS = ("pokemon_reverse", "foil", "reverse", "holo")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def price_eur(offer: dict) -> float | None:
    price = offer.get("price") if isinstance(offer.get("price"), dict) else {}
    if str(price.get("currency") or "").upper() != "EUR":
        return None
    cents = price.get("cents")
    if cents is None:
        return None
    try:
        return float(cents) / 100
    except (TypeError, ValueError):
        return None


def prop_value(props: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in props and props.get(key) not in (None, ""):
            return props.get(key)
    return "unknown"


def normalize_language(value: Any) -> str:
    value_norm = norm(value)
    if value_norm in {"fr", "french", "francais"}:
        return "fr"
    if value in (None, "", "unknown"):
        return "unknown"
    return value_norm or "unknown"


def normalize_condition(value: Any) -> str:
    value_norm = norm(value)
    if not value_norm:
        return "unknown"
    return CONDITION_MAP.get(value_norm, "unknown")


def seller_country(offer: dict) -> Any:
    seller = offer.get("seller") if isinstance(offer.get("seller"), dict) else {}
    return seller.get("country_code") or "unknown"


def seller_on_vacation(offer: dict) -> bool:
    seller = offer.get("seller") if isinstance(offer.get("seller"), dict) else {}
    return bool(seller.get("on_vacation") or offer.get("on_vacation"))


def inspect_offer(rank: int, offer: dict) -> dict:
    props = offer.get("properties_hash") if isinstance(offer.get("properties_hash"), dict) else {}
    price = offer.get("price") if isinstance(offer.get("price"), dict) else {}
    language_raw = prop_value(props, LANGUAGE_KEYS)
    condition_raw = prop_value(props, CONDITION_KEYS)
    language_normalized = normalize_language(language_raw)
    condition_normalized = normalize_condition(condition_raw)
    foil_raw = prop_value(props, FOIL_KEYS)
    graded = bool(offer.get("graded"))
    on_vacation = seller_on_vacation(offer)
    currency = str(price.get("currency") or "unknown").upper()
    is_french = language_normalized == "fr"
    is_near_mint = condition_normalized == "Near Mint"
    eligible = bool(is_french and is_near_mint and currency == "EUR" and not graded and not on_vacation)
    reasons = []
    if not is_french:
        reasons.append("language_not_fr")
    if condition_normalized == "unknown":
        reasons.append("condition_unknown")
    elif not is_near_mint:
        reasons.append("condition_not_near_mint")
    if currency != "EUR":
        reasons.append("currency_not_eur")
    if graded:
        reasons.append("graded")
    if on_vacation:
        reasons.append("seller_on_vacation")
    return {
        "rank": rank,
        "price_eur": price_eur(offer),
        "currency": currency,
        "language_raw": language_raw,
        "language_normalized": language_normalized,
        "condition_raw": condition_raw,
        "condition_normalized": condition_normalized,
        "foil_raw": foil_raw,
        "graded": graded,
        "on_vacation": on_vacation,
        "seller_country_code": seller_country(offer),
        "is_french": is_french,
        "is_near_mint": is_near_mint,
        "is_eligible_fr_nm": eligible,
        "exclusion_reason": ", ".join(reasons) if reasons else "",
    }


def validated_cards_from_audit() -> list[dict]:
    audit = read_json(PRICE_AUDIT, {})
    cards = audit.get("cards") if isinstance(audit.get("cards"), list) else []
    selected = []
    for card in cards:
        blueprint = card.get("selected_blueprint") if isinstance(card.get("selected_blueprint"), dict) else {}
        blueprint_id = blueprint.get("id")
        if card.get("mapping_status") == "validated" and blueprint_id:
            selected.append(
                {
                    "label": card.get("label") or "",
                    "blueprint_id": blueprint_id,
                    "blueprint_name": blueprint.get("name"),
                    "blueprint_version": blueprint.get("version"),
                }
            )
    return selected


def render_table(card_report: dict) -> None:
    print("\n" + card_report["label"])
    print(f"Blueprint {card_report['blueprint_id']} | language=fr | offres={card_report['offers_returned_count']}")
    headers = ["#", "Prix EUR", "Langue", "Condition brute", "Condition normalisée", "Foil", "Gradée", "Vacances", "Éligible FR/NM", "Raison d'exclusion"]
    print(" | ".join(headers))
    print("-" * 140)
    for offer in card_report["offers"]:
        row = [
            str(offer["rank"]),
            "" if offer["price_eur"] is None else f"{offer['price_eur']:.2f}",
            str(offer["language_raw"]),
            str(offer["condition_raw"]),
            str(offer["condition_normalized"]),
            str(offer["foil_raw"]),
            "oui" if offer["graded"] else "non",
            "oui" if offer["on_vacation"] else "non",
            "oui" if offer["is_eligible_fr_nm"] else "non",
            str(offer["exclusion_reason"]),
        ]
        print(" | ".join(row))
    print("Synthèse :")
    print(f"- offres marquées françaises : {card_report['offers_marked_french_count']}")
    print(f"- langues vues : {', '.join(map(str, card_report['different_languages_seen'])) or '-'}")
    print(f"- conditions brutes : {', '.join(map(str, card_report['conditions_raw_detected'])) or '-'}")
    print(f"- Near Mint détectées : {card_report['near_mint_detected_count']}")
    print(f"- conditions inconnues : {card_report['unknown_condition_count']}")
    if card_report.get("language_filter_anomaly"):
        print("- anomalie : offres non françaises présentes malgré language=fr")


def inspect() -> tuple[dict, int]:
    token = load_cardtrader_token()
    if not token:
        report = {
            "source_name": "CardTrader Full API",
            "read_only": True,
            "tested_at": now_iso(),
            "request_count": 0,
            "cards": [],
            "notes": ["CARDTRADER_API_TOKEN absent : aucun appel réseau effectué."],
        }
        write_json(OUTPUT, report)
        print("CARDTRADER_API_TOKEN absent : aucun appel réseau effectué.")
        return report, 2

    cards = validated_cards_from_audit()
    client = CardTraderReadOnlyClient(token)
    report = {
        "source_name": "CardTrader Full API",
        "read_only": True,
        "tested_at": now_iso(),
        "request_count": 0,
        "cards": [],
    }
    for card in cards:
        payload = client.get(
            "/marketplace/products",
            {"blueprint_id": card["blueprint_id"], "language": "fr"},
        )
        raw_offers = as_list(payload)[:25]
        offers = [inspect_offer(index + 1, offer) for index, offer in enumerate(raw_offers)]
        languages = sorted({offer["language_normalized"] for offer in offers})
        raw_conditions = sorted({str(offer["condition_raw"]) for offer in offers})
        normalized_counts = Counter(offer["condition_normalized"] for offer in offers)
        card_report = {
            "label": card["label"],
            "blueprint_id": card["blueprint_id"],
            "blueprint_name": card.get("blueprint_name"),
            "blueprint_version": card.get("blueprint_version"),
            "request_language_filter": "fr",
            "offers_returned_count": len(offers),
            "offers_marked_french_count": sum(1 for offer in offers if offer["is_french"]),
            "different_languages_seen": languages,
            "language_filter_anomaly": any(language not in {"fr", "unknown"} for language in languages),
            "conditions_raw_detected": raw_conditions,
            "conditions_normalized_counts": dict(normalized_counts),
            "near_mint_detected_count": sum(1 for offer in offers if offer["is_near_mint"]),
            "unknown_condition_count": sum(1 for offer in offers if offer["condition_normalized"] == "unknown"),
            "offers": offers,
        }
        report["cards"].append(card_report)
    report["request_count"] = client.request_count
    if SNAPSHOTS.exists():
        snapshots = read_json(SNAPSHOTS, {"snapshots": []}).get("snapshots", [])
        report["snapshot_count_after_inspection"] = len(snapshots) if isinstance(snapshots, list) else None
    write_json(OUTPUT, report)
    for card_report in report["cards"]:
        render_table(card_report)
    print(f"\nRequêtes GET marketplace : {report['request_count']}")
    print(f"Export : {OUTPUT}")
    return report, 0


if __name__ == "__main__":
    _, code = inspect()
    raise SystemExit(code)

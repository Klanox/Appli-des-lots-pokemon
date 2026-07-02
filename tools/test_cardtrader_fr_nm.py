from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any
import unicodedata

import requests

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_CARDS = ROOT / "tests" / "fixtures" / "cardtrader_reference_cards.json"
SNAPSHOTS_FILE = ROOT / "market_price_snapshots.json"

sys.path.insert(0, str(ROOT))

from services.cardtrader_api import (  # noqa: E402
    CardTraderReadOnlyClient,
    auth_check,
    default_audit,
    default_state,
    load_cardtrader_token,
    save_cardtrader_price_audit,
    save_cardtrader_source_state,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def norm(value: Any) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", text)


def flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten_text(item) for item in value)
    return str(value or "")


def as_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("array", "data", "results", "blueprints", "products", "objects"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if payload and all(isinstance(value, list) for value in payload.values()):
            rows: list[dict] = []
            for value in payload.values():
                rows.extend(item for item in value if isinstance(item, dict))
            return rows
        return [payload]
    return []


def first_present(data: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        current: Any = data
        ok = True
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                ok = False
                break
        if ok and current not in (None, ""):
            return current
    return None


def compact_fields(rows: list[dict]) -> list[str]:
    fields = set()
    for row in rows[:100]:
        fields.update(str(key) for key in row.keys())
    return sorted(fields)


def cardtrader_name(row: dict) -> str:
    return str(first_present(row, ("name", "name_en", "localized_name", "blueprint.name")) or "")


def find_pokemon_game(games: list[dict]) -> dict | None:
    return next((item for item in games if any(token in norm(flatten_text(item)) for token in ("pokemon", "pokmon", "pokamon"))), None)


def filter_for_game(rows: list[dict], game_id: Any) -> list[dict]:
    if game_id in (None, ""):
        return rows
    return [
        row
        for row in rows
        if str(first_present(row, ("game_id", "game.id", "id_game")) or "") == str(game_id)
        or any(token in norm(flatten_text(row)) for token in ("pokemon", "pokmon", "pokamon"))
    ]


def expansion_candidates(expansions: list[dict], card: dict) -> list[dict]:
    set_code = norm(card.get("set_code"))
    candidates = []
    aliases = {
        "svp": ("promosv", "svblackstarpromos", "scarletvioletpromos"),
        "mew": ("mew", "151"),
        "blk": ("blk", "blackbolt", "foudrenoire"),
    }.get(set_code, (set_code,))
    for row in expansions:
        code = norm(first_present(row, ("code", "abbreviation")))
        name = norm(first_present(row, ("name", "translated_name")))
        if any(alias and (alias == code or alias == name or alias in name) for alias in aliases):
            candidates.append(row)
    return candidates[:8]


def blueprint_number(blueprint: dict) -> str:
    return str(
        first_present(
            blueprint,
            (
                "collector_number",
                "number",
                "card_number",
                "properties_hash.collector_number",
                "properties_hash.number",
                "fixed_properties.collector_number",
                "fixed_properties.number",
            ),
        )
        or ""
    )


def blueprint_matches(card: dict, blueprint: dict) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    name_blob = norm(cardtrader_name(blueprint))
    expected_names = {norm(card.get("name_en")), norm(card.get("name_fr"))}
    if not any(expected and (expected in name_blob or name_blob in expected) for expected in expected_names):
        return False, ["nom incompatible"]
    evidence.append("nom compatible")
    number = norm(blueprint_number(blueprint))
    if number:
        if number != norm(card.get("collector_number")):
            return False, ["numéro de collection différent"]
        evidence.append("numéro exact")
    else:
        evidence.append("numéro absent dans le blueprint")
    variant_blob = norm(flatten_text(blueprint))
    expected_variant = norm(card.get("variant_expected"))
    if expected_variant and any(token in expected_variant for token in ("sir", "speciale", "promo")):
        evidence.append("variante à confirmer dans les champs CardTrader")
    if "image" in blueprint or "image_url" in blueprint:
        evidence.append("image disponible")
    return True, evidence


def sanitize_blueprint(blueprint: dict | None) -> dict | None:
    if not blueprint:
        return None
    keep = ("id", "name", "category_id", "expansion_id", "collector_number", "number", "version", "image", "cardmarket_id")
    out = {key: blueprint.get(key) for key in keep if key in blueprint}
    for key in ("properties_hash", "fixed_properties"):
        if isinstance(blueprint.get(key), dict):
            out[key] = blueprint[key]
    return out


def sanitize_expansion(expansion: dict) -> dict:
    keep = ("id", "name", "code", "abbreviation", "game_id", "category_id")
    return {key: expansion.get(key) for key in keep if key in expansion}


def discover_language_condition(products: list[dict]) -> tuple[str | None, str | None]:
    language_key = None
    condition_key = None
    for product in products:
        props = product.get("properties_hash")
        if not isinstance(props, dict):
            continue
        for key, value in props.items():
            key_norm = norm(key)
            value_norm = norm(value)
            if language_key is None and ("language" in key_norm or value_norm in {"fr", "french", "francais"}):
                language_key = str(key)
            if condition_key is None and ("condition" in key_norm or value_norm in {"nearmint", "nm"}):
                condition_key = str(key)
    return language_key, condition_key


def is_french_nm_offer(product: dict, language_key: str | None, condition_key: str | None) -> bool:
    props = product.get("properties_hash") if isinstance(product.get("properties_hash"), dict) else {}
    language_value = norm(props.get(language_key)) if language_key else ""
    condition_value = norm(props.get(condition_key)) if condition_key else ""
    if language_value not in {"fr", "french", "francais"}:
        return False
    if condition_value not in {"nearmint", "nm"}:
        return False
    if bool(product.get("graded")):
        return False
    seller = product.get("seller") if isinstance(product.get("seller"), dict) else {}
    if bool(seller.get("on_vacation") or product.get("on_vacation")):
        return False
    price = product.get("price") if isinstance(product.get("price"), dict) else {}
    if str(price.get("currency") or "").upper() != "EUR":
        return False
    return price.get("cents") is not None


def sanitize_offer(product: dict) -> dict:
    seller = product.get("seller") if isinstance(product.get("seller"), dict) else {}
    price = product.get("price") if isinstance(product.get("price"), dict) else {}
    return {
        "product_id": product.get("id"),
        "blueprint_id": product.get("blueprint_id"),
        "price": {"cents": price.get("cents"), "currency": price.get("currency")},
        "properties_hash": product.get("properties_hash") if isinstance(product.get("properties_hash"), dict) else {},
        "expansion": product.get("expansion"),
        "seller": {
            "country_code": seller.get("country_code"),
            "user_type": seller.get("user_type"),
        },
        "graded": product.get("graded"),
        "on_vacation": seller.get("on_vacation") or product.get("on_vacation"),
    }


def price_result(mapping_status: str, price: float | None, ref: float | None, fr_nm_count: int, notes: list[str]) -> tuple[str, float | None, float | None]:
    if mapping_status != "validated":
        return ("FAIL" if mapping_status in {"ambiguous", "rejected"} else "INCONCLUSIVE"), None, None
    if price is None:
        notes.append("aucune offre FR Near Mint dans les 25 résultats")
        return "INCONCLUSIVE", None, None
    diff = price - ref if ref else None
    diff_pct = diff / ref * 100 if ref else None
    if diff_pct is not None and abs(diff_pct) > 30:
        return "FAIL", diff, diff_pct
    if diff_pct is not None and abs(diff_pct) > 15:
        return "WARN", diff, diff_pct
    if fr_nm_count <= 1:
        return "WARN", diff, diff_pct
    if any("variante à confirmer" in note for note in notes):
        return "WARN", diff, diff_pct
    return "PASS", diff, diff_pct


def run() -> tuple[dict, int]:
    cards = read_json(REFERENCE_CARDS, [])
    audit = default_audit()
    state = default_state()
    audit["tested_at"] = now_iso()
    state["last_test_at"] = audit["tested_at"]

    auth_status, auth_requests = auth_check()
    audit["auth_status"] = auth_status
    audit["request_count"] = auth_requests
    state["auth_status"] = auth_status
    if auth_status != "auth_ok":
        audit["notes"].append("Arrêt après test d'authentification.")
        state["source_status"] = auth_status
        save_cardtrader_price_audit(audit)
        save_cardtrader_source_state(state)
        print("auth_status", auth_status)
        print("request_count", auth_requests)
        return audit, 2 if auth_status == "auth_missing" else 1

    token = load_cardtrader_token()
    client = CardTraderReadOnlyClient(token or "")
    client.request_count = auth_requests
    try:
        games = as_list(client.get("/games"))
        categories = as_list(client.get("/categories"))
        expansions = as_list(client.get("/expansions"))
    except requests.RequestException as exc:
        audit["notes"].append(f"Erreur réseau pendant la découverte: {type(exc).__name__}")
        audit["request_count"] = client.request_count
        state["source_status"] = "network_error"
        save_cardtrader_price_audit(audit)
        save_cardtrader_source_state(state)
        return audit, 1

    game = find_pokemon_game(games)
    game_id = first_present(game or {}, ("id", "game_id"))
    pokemon_categories = filter_for_game(categories, game_id)
    pokemon_expansions = filter_for_game(expansions, game_id)
    audit["discovery"] = {
        "games_fields": compact_fields(games),
        "categories_fields": compact_fields(categories),
        "expansions_fields": compact_fields(expansions),
        "pokemon_game": game,
        "pokemon_categories_sample": pokemon_categories[:10],
    }

    for card in cards:
        candidate_expansions = expansion_candidates(pokemon_expansions, card)
        candidate_blueprints: list[dict] = []
        selected_blueprint = None
        mapping_evidence: list[str] = []
        mapping_status = "needs_review"
        notes: list[str] = []
        for expansion in candidate_expansions:
            expansion_id = first_present(expansion, ("id", "expansion_id"))
            if expansion_id in (None, ""):
                continue
            try:
                blueprints = as_list(client.get("/blueprints/export", {"expansion_id": expansion_id}))
            except requests.RequestException as exc:
                notes.append(f"blueprints expansion {expansion_id}: {type(exc).__name__}")
                continue
            matches = []
            for blueprint in blueprints:
                ok, evidence = blueprint_matches(card, blueprint)
                if ok:
                    blueprint["_mapping_evidence"] = evidence
                    matches.append(blueprint)
            candidate_blueprints.extend(matches)
        if len(candidate_blueprints) == 1:
            selected_blueprint = candidate_blueprints[0]
            mapping_status = "validated"
            mapping_evidence = list(selected_blueprint.get("_mapping_evidence") or [])
        elif len(candidate_blueprints) > 1:
            mapping_status = "ambiguous"
            mapping_evidence = [f"{len(candidate_blueprints)} blueprints plausibles"]
        else:
            mapping_status = "rejected"
            mapping_evidence = ["aucun blueprint compatible"]

        offers = []
        fr_nm_offers = []
        retained_price = None
        if mapping_status == "validated" and selected_blueprint:
            blueprint_id = first_present(selected_blueprint, ("id", "blueprint_id"))
            try:
                offer_payload = client.get("/marketplace/products", {"blueprint_id": blueprint_id, "language": "fr"})
                offers = as_list(offer_payload)[:25]
                language_key, condition_key = discover_language_condition(offers)
                if not language_key or not condition_key:
                    notes.append("langue ou condition non identifiable dans properties_hash")
                fr_nm_offers = [
                    offer
                    for offer in offers
                    if is_french_nm_offer(offer, language_key, condition_key)
                ]
                if fr_nm_offers:
                    retained_price = min(offer["price"]["cents"] for offer in fr_nm_offers) / 100
            except requests.RequestException as exc:
                notes.append(f"marketplace products: {type(exc).__name__}")

        if mapping_status == "validated":
            mapping_evidence.extend(note for note in notes if "variante" in note)
        result, diff, diff_pct = price_result(
            mapping_status,
            retained_price,
            card.get("reference_cardmarket_fr_nm_excl_shipping_eur"),
            len(fr_nm_offers),
            notes,
        )
        audit["cards"].append(
            {
                "label": card.get("label"),
                "reference_cardmarket_fr_nm_excl_shipping_eur": card.get("reference_cardmarket_fr_nm_excl_shipping_eur"),
                "candidate_expansions": [sanitize_expansion(item) for item in candidate_expansions],
                "candidate_blueprints": [sanitize_blueprint(item) for item in candidate_blueprints[:12]],
                "selected_blueprint": sanitize_blueprint(selected_blueprint),
                "mapping_status": mapping_status,
                "mapping_evidence": mapping_evidence,
                "offers_returned_count": len(offers),
                "offers_sample": [sanitize_offer(item) for item in offers[:25]],
                "fr_nm_offers_found_count": len(fr_nm_offers),
                "lowest_cardtrader_fr_nm_excl_shipping_eur": retained_price,
                "difference_eur": diff,
                "difference_pct": diff_pct,
                "result": result,
                "notes": notes,
            }
        )

    summary = {
        "pass": sum(1 for item in audit["cards"] if item["result"] == "PASS"),
        "warn": sum(1 for item in audit["cards"] if item["result"] == "WARN"),
        "fail": sum(1 for item in audit["cards"] if item["result"] == "FAIL"),
        "inconclusive": sum(1 for item in audit["cards"] if item["result"] == "INCONCLUSIVE"),
        "validated_blueprints": sum(1 for item in audit["cards"] if item["mapping_status"] == "validated"),
        "fr_nm_prices_found": sum(1 for item in audit["cards"] if item["lowest_cardtrader_fr_nm_excl_shipping_eur"] is not None),
    }
    no_bad_mapping_fail = all(not (item["result"] == "FAIL" and item["mapping_status"] in {"ambiguous", "rejected"}) for item in audit["cards"])
    audit["summary"] = summary
    audit["request_count"] = client.request_count
    audit["overall_status"] = (
        "candidate_for_limited_integration"
        if summary["validated_blueprints"] == 4
        and summary["pass"] >= 3
        and no_bad_mapping_fail
        else "not_ready_for_integration"
    )
    state.update(
        {
            "source_status": "tested",
            "read_only_test_completed": True,
            "mapping_status": "validated" if summary["validated_blueprints"] == 4 else "partial_or_failed",
            "pricing_policy_status": audit["overall_status"],
        }
    )
    if SNAPSHOTS_FILE.exists():
        snapshots = read_json(SNAPSHOTS_FILE, {"snapshots": []}).get("snapshots", [])
        audit["snapshot_count_after_test"] = len(snapshots) if isinstance(snapshots, list) else None
    save_cardtrader_price_audit(audit)
    save_cardtrader_source_state(state)
    print("auth_status", auth_status)
    print("request_count", audit["request_count"])
    print("overall_status", audit["overall_status"])
    print("summary", summary)
    return audit, 0


if __name__ == "__main__":
    _, code = run()
    raise SystemExit(code)

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
REFERENCE_CARDS = ROOT / "tests" / "fixtures" / "external_price_api_reference_cards.json"
REPORT_FILE = ROOT / "market_external_price_api_audit.json"

SOURCE_NAME = "CM API / CardMarket API via RapidAPI"
REQUIRED_ENV = (
    "EXTERNAL_TCG_PRICE_API_KEY",
    "EXTERNAL_TCG_PRICE_API_HOST",
    "EXTERNAL_TCG_PRICE_API_BASE_URL",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        env[key.strip()] = value
    return env


def _blank_report(cards: list[dict], notes: list[str] | None = None) -> dict:
    return {
        "source_name": SOURCE_NAME,
        "source_type": "third_party",
        "official_cardmarket_source": False,
        "tested_at": _now_iso(),
        "request_count": 0,
        "overall_status": "not_ready_for_integration",
        "cards": [
            {
                "label": card.get("label"),
                "reference_price_fr_nm_excl_shipping": card.get("reference_price_fr_nm_excl_shipping"),
                "api_candidate_count": 0,
                "selected_candidate": None,
                "identity_status": "not_tested",
                "identity_evidence": [],
                "lowest_near_mint_FR": None,
                "lowest_near_mint": None,
                "7d_average": None,
                "30d_average": None,
                "currency": None,
                "last_updated": None,
                "difference_eur": None,
                "difference_pct": None,
                "result": "NOT_RUN",
                "notes": notes or [],
            }
            for card in cards
        ],
        "summary": {
            "pass": 0,
            "warn": 0,
            "fail": 0,
            "identity_validated": 0,
            "lowest_near_mint_fr_available": 0,
        },
        "notes": notes or [],
    }


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _first_present(data: dict, keys: tuple[str, ...]) -> Any:
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


def _as_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "data", "cards", "items", "products"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _redacted_candidate(candidate: dict) -> dict:
    keep = (
        "id",
        "product_id",
        "cardmarket_id",
        "name",
        "name_fr",
        "name_en",
        "set",
        "set_code",
        "set_name",
        "number",
        "card_number",
        "rarity",
        "variant",
        "image",
        "image_url",
        "prices",
    )
    return {key: candidate.get(key) for key in keep if key in candidate}


def _identity_status(card: dict, candidates: list[dict]) -> tuple[str, dict | None, list[str]]:
    plausible: list[tuple[dict, list[str]]] = []
    expected_number = _normalise(card.get("card_number"))
    expected_set = _normalise(card.get("set_code"))
    expected_names = {_normalise(card.get("name_en")), _normalise(card.get("name_fr"))}
    for candidate in candidates:
        number = _normalise(
            _first_present(candidate, ("number", "card_number", "collector_number", "num", "localId"))
        )
        set_code = _normalise(
            _first_present(candidate, ("set_code", "set.code", "set.id", "expansion", "expansion_code", "set"))
        )
        name = _normalise(_first_present(candidate, ("name", "name_en", "name_fr", "card.name")))
        evidence: list[str] = []
        if number != expected_number:
            continue
        evidence.append("numéro exact")
        if expected_set and expected_set not in set_code and set_code not in expected_set:
            continue
        evidence.append("set compatible")
        if name not in expected_names and not any(expected in name or name in expected for expected in expected_names if expected):
            continue
        evidence.append("nom compatible")
        variant = _first_present(candidate, ("variant", "rarity", "subtype", "description"))
        if variant:
            evidence.append(f"variante documentée: {variant}")
        else:
            evidence.append("variante non documentée par l'API")
        plausible.append((candidate, evidence))
    if not plausible:
        return "rejected", None, ["aucun candidat avec set + numéro + nom compatibles"]
    if len(plausible) > 1:
        return "ambiguous", None, [f"{len(plausible)} candidats plausibles"]
    return "validated", plausible[0][0], plausible[0][1]


def _extract_prices(candidate: dict) -> dict:
    prices = candidate.get("prices") if isinstance(candidate.get("prices"), dict) else {}
    cardmarket = prices.get("cardmarket") if isinstance(prices.get("cardmarket"), dict) else {}
    source = {**candidate, **prices, **cardmarket}
    return {
        "lowest_near_mint_FR": _first_present(source, ("lowest_near_mint_FR", "lowestNearMintFR")),
        "lowest_near_mint": _first_present(source, ("lowest_near_mint", "lowestNearMint")),
        "7d_average": _first_present(source, ("7d_average", "avg7", "average7d")),
        "30d_average": _first_present(source, ("30d_average", "avg30", "average30d")),
        "currency": _first_present(source, ("currency", "price_currency")),
        "last_updated": _first_present(source, ("last_updated", "updated_at", "lastUpdate")),
    }


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _result_for_card(identity_status: str, prices: dict, card: dict, evidence: list[str]) -> tuple[str, float | None, float | None, list[str]]:
    notes: list[str] = []
    if identity_status != "validated":
        return "FAIL", None, None, [f"identity_status={identity_status}"]
    api_price = _to_float(prices.get("lowest_near_mint_FR"))
    reference = _to_float(card.get("reference_price_fr_nm_excl_shipping"))
    if api_price is None:
        return "FAIL", None, None, ["lowest_near_mint_FR absent"]
    currency = str(prices.get("currency") or "").upper()
    if currency and currency != "EUR":
        return "FAIL", None, None, [f"devise non EUR: {currency}"]
    if not currency:
        notes.append("devise absente")
    diff_eur = api_price - reference if reference is not None else None
    diff_pct = (diff_eur / reference * 100) if reference else None
    if diff_pct is not None and abs(diff_pct) > 20:
        return "FAIL", diff_eur, diff_pct, notes + ["écart supérieur à 20 %"]
    if diff_pct is not None and abs(diff_pct) > 10:
        return "WARN", diff_eur, diff_pct, notes + ["écart entre 10 % et 20 %"]
    if not prices.get("last_updated"):
        return "WARN", diff_eur, diff_pct, notes + ["date de mise à jour absente"]
    if any("variante non documentée" in item for item in evidence):
        return "WARN", diff_eur, diff_pct, notes + ["variante non complètement documentée"]
    return "PASS", diff_eur, diff_pct, notes


def _build_url(template: str, card: dict, name: str) -> str:
    replacements = {
        "name": quote(str(name)),
        "name_en": quote(str(card.get("name_en") or "")),
        "name_fr": quote(str(card.get("name_fr") or "")),
        "number": quote(str(card.get("card_number") or "")),
        "card_number": quote(str(card.get("card_number") or "")),
        "set_code": quote(str(card.get("set_code") or "")),
    }
    url = template
    for key, value in replacements.items():
        url = url.replace("{" + key + "}", value)
    return url


def _fetch_candidates(base_url: str, host: str, api_key: str, card: dict, name: str) -> tuple[list[dict], int]:
    import requests

    url = _build_url(base_url, card, name)
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": host,
    }
    response = requests.get(url, headers=headers, timeout=45)
    response.raise_for_status()
    return _as_list(response.json()), 1


def _candidate_identity_key(candidate: dict) -> str:
    value = _first_present(candidate, ("id", "product_id", "cardmarket_id", "idProduct"))
    if value not in (None, ""):
        return f"id:{value}"
    return json.dumps(_redacted_candidate(candidate), ensure_ascii=False, sort_keys=True)


def _merge_candidates(existing: list[dict], new_candidates: list[dict]) -> list[dict]:
    seen = {_candidate_identity_key(item) for item in existing}
    for candidate in new_candidates:
        key = _candidate_identity_key(candidate)
        if key in seen:
            continue
        existing.append(candidate)
        seen.add(key)
    return existing


def run() -> tuple[dict, int]:
    cards = _read_json(REFERENCE_CARDS, [])
    if not isinstance(cards, list):
        cards = []
    env = _load_env()
    missing = [key for key in REQUIRED_ENV if not env.get(key)]
    if missing:
        notes = [
            "Configuration RapidAPI absente ou incomplète.",
            "Aucun appel réseau effectué.",
            "Renseigner EXTERNAL_TCG_PRICE_API_KEY, EXTERNAL_TCG_PRICE_API_HOST et EXTERNAL_TCG_PRICE_API_BASE_URL dans .env.",
        ]
        report = _blank_report(cards, notes)
        _write_json(REPORT_FILE, report)
        print("Configuration API externe absente : aucun appel réseau effectué.")
        print("Champs à renseigner dans .env : " + ", ".join(missing))
        return report, 2

    report = _blank_report(cards, [])
    report["cards"] = []
    request_count = 0
    for card in cards:
        all_candidates: list[dict] = []
        errors: list[str] = []
        identity_status = "not_tested"
        selected: dict | None = None
        evidence: list[str] = []
        search_plan = [card.get("name_en"), card.get("name_fr")]
        for index, name in enumerate(search_plan):
            if not name or (index > 0 and identity_status == "validated"):
                continue
            try:
                candidates, calls = _fetch_candidates(
                    env["EXTERNAL_TCG_PRICE_API_BASE_URL"],
                    env["EXTERNAL_TCG_PRICE_API_HOST"],
                    env["EXTERNAL_TCG_PRICE_API_KEY"],
                    card,
                    str(name),
                )
                request_count += calls
                all_candidates = _merge_candidates(all_candidates, candidates)
            except Exception as exc:
                errors.append(f"recherche {name}: {type(exc).__name__}")
            identity_status, selected, evidence = _identity_status(card, all_candidates)
        prices = _extract_prices(selected or {}) if selected else {}
        result, diff_eur, diff_pct, notes = _result_for_card(identity_status, prices, card, evidence)
        notes.extend(errors)
        report["cards"].append(
            {
                "label": card.get("label"),
                "reference_price_fr_nm_excl_shipping": card.get("reference_price_fr_nm_excl_shipping"),
                "api_candidate_count": len(all_candidates),
                "candidates": [_redacted_candidate(item) for item in all_candidates],
                "selected_candidate": _redacted_candidate(selected) if selected else None,
                "identity_status": identity_status,
                "identity_evidence": evidence,
                "lowest_near_mint_FR": prices.get("lowest_near_mint_FR"),
                "lowest_near_mint": prices.get("lowest_near_mint"),
                "7d_average": prices.get("7d_average"),
                "30d_average": prices.get("30d_average"),
                "currency": prices.get("currency"),
                "last_updated": prices.get("last_updated"),
                "difference_eur": diff_eur,
                "difference_pct": diff_pct,
                "result": result,
                "notes": notes,
            }
        )
    summary = {
        "pass": sum(1 for item in report["cards"] if item["result"] == "PASS"),
        "warn": sum(1 for item in report["cards"] if item["result"] == "WARN"),
        "fail": sum(1 for item in report["cards"] if item["result"] == "FAIL"),
        "identity_validated": sum(1 for item in report["cards"] if item["identity_status"] == "validated"),
        "lowest_near_mint_fr_available": sum(1 for item in report["cards"] if item.get("lowest_near_mint_FR") is not None),
    }
    report["summary"] = summary
    report["request_count"] = request_count
    no_mapping_fail = all(not (item["result"] == "FAIL" and item["identity_status"] in {"rejected", "ambiguous"}) for item in report["cards"])
    report["overall_status"] = (
        "candidate_for_future_integration"
        if summary["identity_validated"] == 4
        and summary["pass"] >= 3
        and no_mapping_fail
        and summary["lowest_near_mint_fr_available"] == 4
        else "not_ready_for_integration"
    )
    _write_json(REPORT_FILE, report)
    print("request_count", request_count)
    print("overall_status", report["overall_status"])
    print("pass", summary["pass"], "warn", summary["warn"], "fail", summary["fail"])
    return report, 0


if __name__ == "__main__":
    _, exit_code = run()
    raise SystemExit(exit_code)

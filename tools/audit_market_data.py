from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_PULL_RATES = ROOT / "market_pull_rates.json"
ACTIVE_SNAPSHOTS = ROOT / "market_price_snapshots.json"
REFERENCE = ROOT / "tests" / "fixtures" / "market_pull_rates_eb_reference.json"
AUDIT_OUTPUT = ROOT / "market_pull_rates_audit.json"


def issue(severity: str, series_id: str, field: str, expected, actual, message: str) -> dict:
    return {
        "severity": severity,
        "series_id": series_id,
        "field": field,
        "expected": expected,
        "actual": actual,
        "message": message,
    }


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def category_by_name(entry: dict) -> dict[str, dict]:
    return {
        str(item.get("display_name_fr") or item.get("display_name") or item.get("source_label")): item
        for item in entry.get("category_rates") or entry.get("categories") or []
        if isinstance(item, dict)
    }


def run_audit() -> tuple[dict, int]:
    issues: list[dict] = []
    warnings: list[dict] = []
    pull_rates = load_json(ACTIVE_PULL_RATES)
    snapshots = load_json(ACTIVE_SNAPSHOTS) if ACTIVE_SNAPSHOTS.exists() else {"snapshots": []}

    if not REFERENCE.exists():
        issues.append(
            issue(
                "error",
                "",
                "reference",
                str(REFERENCE),
                "missing",
                "Référence indépendante manquante",
            )
        )
        reference = {}
    else:
        reference = load_json(REFERENCE)

    sets = pull_rates.get("sets", {})
    if not isinstance(sets, dict):
        sets = {}
        issues.append(issue("error", "", "sets", "dict", type(sets).__name__, "market_pull_rates.json invalide"))

    expected_imported = set(reference.get("expected_imported_eb_series", []))
    expected_estimated = set(reference.get("expected_estimated_series", []))
    active_imported = {key for key, entry in sets.items() if entry.get("rare_rates_status") == "imported"}
    active_non = {key for key, entry in sets.items() if entry.get("overall_status") == "non_renseigne"}

    audit_structurel = {
        "status": "OK",
        "series_total": len(sets),
        "imported_eb_series": len(active_imported),
        "non_renseigne_series": len(active_non),
        "expected_imported_eb_series": sorted(expected_imported),
        "active_imported_eb_series": sorted(active_imported),
        "expected_estimated_series": sorted(expected_estimated),
    }
    if len(sets) != reference.get("expected_series_total", 38):
        issues.append(issue("error", "", "series_total", reference.get("expected_series_total", 38), len(sets), "Nombre de séries incorrect"))
    if active_imported != expected_imported:
        issues.append(issue("error", "", "imported_eb_series", sorted(expected_imported), sorted(active_imported), "Séries EB importées incorrectes"))
    if len(active_non) != 21:
        issues.append(issue("error", "", "non_renseigne_series", 21, len(active_non), "Nombre de séries Non renseigné incorrect"))
    for key, entry in sets.items():
        source_name = str(entry.get("source", {}).get("source_name") if isinstance(entry.get("source"), dict) else "")
        if "TCGplayer" in json.dumps(entry, ensure_ascii=False):
            issues.append(issue("error", key, "source", "no TCGplayer active", "TCGplayer", "Ancienne source TCGplayer active détectée"))
        if key in expected_imported and source_name != reference.get("source_name"):
            issues.append(issue("error", key, "source_name", reference.get("source_name"), source_name, "Source active EB incorrecte"))
        if key not in expected_imported and (entry.get("category_rates") or entry.get("categories")):
            issues.append(issue("error", key, "categories", [], "not empty", "Taux actif hors EB détecté"))

    audit_valeurs = {
        "status": "OK" if reference else "Référence indépendante manquante",
        "reference_file": str(REFERENCE),
        "checked_series": sorted(expected_imported),
    }
    if not reference:
        audit_valeurs["status"] = "Référence indépendante manquante"
    for set_id, expected in (reference.get("series") or {}).items():
        entry = sets.get(set_id)
        if not entry:
            issues.append(issue("error", set_id, "entry", "present", "missing", "Série de référence absente"))
            continue
        categories = category_by_name(entry)
        if entry.get("source", {}).get("source_confidence") != expected.get("confidence"):
            issues.append(issue("error", set_id, "source_confidence", expected.get("confidence"), entry.get("source", {}).get("source_confidence"), "Confiance source incorrecte"))
        for label, expected_rate in (expected.get("categories") or {}).items():
            actual = categories.get(label)
            if not actual:
                issues.append(issue("error", set_id, f"category.{label}", expected_rate, "missing", "Catégorie attendue absente"))
                continue
            if actual.get("any_rate_text") != expected_rate:
                issues.append(issue("error", set_id, f"category.{label}.any_rate_text", expected_rate, actual.get("any_rate_text"), "Taux Any incorrect"))
            if label in (expected.get("specific") or {}) and actual.get("specific_rate_text") != expected["specific"][label]:
                issues.append(issue("error", set_id, f"category.{label}.specific_rate_text", expected["specific"][label], actual.get("specific_rate_text"), "Taux Specific incorrect"))
        for label, examples in (expected.get("specific_examples") or {}).items():
            actual = categories.get(label)
            actual_examples = {item.get("card_name"): item.get("rate_text") for item in (actual or {}).get("specific_examples", [])}
            for card_name, expected_rate in examples.items():
                if actual_examples.get(card_name) != expected_rate:
                    issues.append(issue("error", set_id, f"specific_examples.{card_name}", expected_rate, actual_examples.get(card_name), "Exemple Specific incorrect ou absent"))
                if card_name in categories:
                    issues.append(issue("error", set_id, f"category.{card_name}", "not a category", "category", "Carte nommée utilisée comme rareté"))

    audit_slots = {"status": "OK"}
    for set_id, label in (("SWSH10", "Radiant Rare"), ("SWSH10.5", "Radiant Pokémon"), ("SWSH12", "Radiant Rare")):
        category = category_by_name(sets.get(set_id, {})).get(label)
        if not category or category.get("slot_behavior") != "replace_reverse_slot":
            issues.append(issue("error", set_id, f"{label}.slot_behavior", "replace_reverse_slot", (category or {}).get("slot_behavior"), "Règle Radieuses incorrecte"))
    cel = sets.get("CEL25", {})
    if cel.get("booster_type") != "celebrations_4_card":
        issues.append(issue("error", "CEL25", "booster_type", "celebrations_4_card", cel.get("booster_type"), "Profil Célébrations incorrect"))
    cel_categories = category_by_name(cel)
    for label in ("Classic Collection", "Classic Collection Ultra Rare"):
        if cel_categories.get(label, {}).get("slot_behavior") != "replace_holo_slot":
            issues.append(issue("error", "CEL25", f"{label}.slot_behavior", "replace_holo_slot", cel_categories.get(label, {}).get("slot_behavior"), "Classic Collection ne remplace pas une holo"))
    if not cel.get("booster_profile", {}).get("classic_collection_can_coexist"):
        issues.append(issue("error", "CEL25", "classic_collection_can_coexist", True, False, "Coexistence Classic Collection non déclarée"))

    audit_vmc = {
        "status": "OK",
        "numeric_vmc_created": False,
        "snapshot_count": len(snapshots.get("snapshots", [])) if isinstance(snapshots.get("snapshots"), list) else 0,
        "card_auto_mapping_created": any((entry.get("card_category_mappings") or []) for entry in sets.values()),
    }
    if audit_vmc["snapshot_count"] != 0:
        issues.append(issue("error", "", "snapshots", 0, audit_vmc["snapshot_count"], "Snapshots créés alors qu'ils doivent rester vides"))
    if audit_vmc["card_auto_mapping_created"]:
        issues.append(issue("error", "", "card_category_mappings", [], "not empty", "Cartes classées automatiquement"))
    if "vmc_eur" in json.dumps(pull_rates):
        issues.append(issue("error", "", "vmc_eur", "absent", "present", "VMC chiffrée détectée"))

    for section in (audit_structurel, audit_valeurs, audit_slots, audit_vmc):
        if issues and section.get("status") == "OK":
            section["status"] = "CHECK_ISSUES"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 2,
        "audit_structurel": audit_structurel,
        "audit_valeurs_pull_rates": audit_valeurs,
        "audit_regles_slots": audit_slots,
        "audit_vmc": audit_vmc,
        "issues": issues,
        "warnings": warnings,
        "checked_series": sorted(expected_imported),
        "result": "OK" if not issues else "CHECK_FAILED",
    }
    AUDIT_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report, 0 if not issues else 1


def main() -> int:
    report, code = run_audit()
    print("audit_structurel:", report["audit_structurel"]["status"])
    print("audit_valeurs_pull_rates:", report["audit_valeurs_pull_rates"]["status"])
    print("audit_regles_slots:", report["audit_regles_slots"]["status"])
    print("audit_vmc:", report["audit_vmc"]["status"])
    print("issues:", len(report["issues"]))
    print("warnings:", len(report["warnings"]))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

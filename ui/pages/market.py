"""Market page adapter for the custom React dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from components.market_dashboard import market_dashboard
from services.cardmarket_official_data import (
    audit_official_cardmarket_source,
    ensure_cardmarket_files,
    load_cardmarket_mappings,
    load_cardmarket_source_state,
    refresh_official_cardmarket_data,
)
from services.cardtrader_api import load_cardtrader_source_state


EXTERNAL_PRICE_API_AUDIT_FILE = Path("market_external_price_api_audit.json")
from services.market_service import (
    MARKET_DATASETS,
    PULL_RATE_RARITIES,
    PULL_RATE_SLOT_KEYS,
    add_card_to_watchlist,
    apply_pull_rates_import,
    attach_pull_rate_status_to_series,
    audit_price_source,
    export_pull_rates_json,
    format_pull_rate,
    infer_market_cards,
    infer_market_series,
    load_market_datasets,
    normalise_market_pull_rates,
    preview_pull_rates_import,
    save_market_pull_rates,
    save_market_series_config,
    save_market_watchlist,
    stable_series_color,
    update_pull_rate_entry,
    validate_pull_rate_entry,
)


def _market_page_css() -> None:
    st.markdown(
        """
<style>
.ps-app-header {
  display: none !important;
}
.block-container:has(.market-component-anchor) {
  max-width: none !important;
  padding: .75rem 1rem 1rem !important;
}
.market-component-anchor {
  margin: 0;
}
.market-technical-panel {
  margin-top: .7rem;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _payload_from_datasets(datasets: dict) -> dict:
    series = infer_market_series(datasets.get("series_config"))
    pull_rates = normalise_market_pull_rates(datasets.get("pull_rates"), series)
    series = attach_pull_rate_status_to_series(series, pull_rates)
    cards = infer_market_cards(limit=700)
    snapshots = datasets.get("price_snapshots", {}).get("snapshots", [])
    if not isinstance(snapshots, list):
        snapshots = []
    watchlist_cards = datasets.get("watchlist", {}).get("cards", [])
    watchlist_keys = [
        str(item.get("card_key"))
        for item in watchlist_cards
        if isinstance(item, dict) and item.get("active", True) and item.get("card_key")
    ]
    return {
        "series": series,
        "snapshots": snapshots,
        "cards": cards,
        "watchlist_keys": watchlist_keys,
        "source_audit": audit_price_source(),
        "initial_state": st.session_state.get("market_dashboard_state", {}),
    }


def _handle_dashboard_event(event: dict, datasets: dict, cards: list[dict]) -> None:
    if not isinstance(event, dict) or not event:
        return
    state_to_keep = dict(event)
    action = state_to_keep.pop("watchlist_action", None)
    st.session_state["market_dashboard_state"] = state_to_keep
    if not isinstance(action, dict):
        return
    action_id = str(action.get("id") or "")
    if not action_id or st.session_state.get("market_last_watchlist_action") == action_id:
        return
    if action.get("action") != "add":
        return
    card_key = str(action.get("card_key") or "")
    card = next((item for item in cards if str(item.get("card_key") or "") == card_key), None)
    if not card:
        return
    updated_watchlist, added = add_card_to_watchlist(datasets.get("watchlist", {}), card)
    st.session_state["market_last_watchlist_action"] = action_id
    if added:
        save_market_watchlist(updated_watchlist)
        st.toast("Carte ajoutée à la watchlist Marché.")
        st.rerun()


def _status_badge(status: str) -> str:
    labels = {
        "missing": "Non renseigné",
        "incomplete": "Incomplet",
        "review": "À vérifier",
        "ready": "Prêt à calculer",
    }
    return labels.get(status, status or "Non renseigné")


def _raw_value(value) -> str:
    return format_pull_rate(value) if value not in (None, "") else ""


def _entry_to_table_row(series_row: dict, pull_rates: dict) -> dict:
    entry = pull_rates.get("sets", {}).get(str(series_row.get("set_id") or "").upper(), {})
    validation = validate_pull_rate_entry(entry)
    return {
        "Rang": int(series_row.get("release_rank") or 999),
        "Série": series_row.get("name_fr") or series_row.get("set_id"),
        "Set": series_row.get("set_id"),
        "Taux rares": (
            "Taux rares importés"
            if validation.get("rare_rates_status") == "imported"
            else "Non renseigné"
        ),
        "Slots booster": "OK" if validation.get("booster_slots_status") == "configured" else "Manquants",
        "Catégories spéciales": (
            "À décider"
            if validation.get("special_categories_status") == "to_decide"
            else "Non renseigné"
        ),
        "Statut global": validation["status_label"],
        "Avertissements": ", ".join(entry.get("warnings") or []) or "-",
        "Dernière mise à jour": entry.get("updated_at") or "-",
    }


def _render_pull_rate_form(series: list[dict], pull_rates: dict) -> None:
    selected_id = st.session_state.get("market_pull_rate_selected_set")
    if not selected_id:
        return
    series_row = next(
        (item for item in series if str(item.get("set_id") or "").upper() == str(selected_id).upper()),
        None,
    )
    if not series_row:
        return
    set_key = str(series_row.get("set_id") or "").upper()
    entry = pull_rates.get("sets", {}).get(set_key, {})
    st.markdown(f"##### Configurer {series_row.get('name_fr')} ({series_row.get('set_id')})")
    validation = validate_pull_rate_entry(entry)
    st.caption(f"Statut actuel : {_status_badge(validation['status'])}")

    with st.form(f"market_pull_rate_form_{set_key}"):
        st.markdown("**Booster standard**")
        slot_cols = st.columns(3)
        slot_labels = {
            "common": "Communes par booster",
            "reverse_probability": "Probabilité reverse",
            "holo_probability": "Probabilité holo",
        }
        slot_values = {}
        slots = entry.get("slots", {}) if isinstance(entry.get("slots"), dict) else {}
        for index, slot_key in enumerate(PULL_RATE_SLOT_KEYS):
            slot_values[slot_key] = slot_cols[index].text_input(
                slot_labels[slot_key],
                value=_raw_value(slots.get(slot_key)),
                placeholder="1/12, 8,33 % ou 0,0833",
                key=f"market_pull_slot_{set_key}_{slot_key}",
            )

        st.markdown("**Grosses cartes**")
        rarity_values = {}
        rarities = entry.get("rarities", {}) if isinstance(entry.get("rarities"), dict) else {}
        for rarity in PULL_RATE_RARITIES:
            raw = rarities.get(rarity) if isinstance(rarities.get(rarity), dict) else {}
            col_rate, col_na = st.columns([3, 1])
            not_applicable = col_na.checkbox(
                "Non applicable",
                value=bool(raw.get("not_applicable")),
                key=f"market_pull_na_{set_key}_{rarity}",
            )
            rarity_values[rarity] = {
                "probability": col_rate.text_input(
                    rarity,
                    value="" if not_applicable else _raw_value(raw.get("probability")),
                    placeholder="1/24, 4,17 % ou 0,0417",
                    disabled=not_applicable,
                    key=f"market_pull_rarity_{set_key}_{rarity}",
                ),
                "not_applicable": not_applicable,
            }

        source_note = st.text_area(
            "Source / note obligatoire",
            value=str(entry.get("source_note") or ""),
            placeholder="Ex. pull rates relevés manuellement depuis ...",
            key=f"market_pull_source_{set_key}",
        )
        notes = st.text_area(
            "Note interne",
            value=str(entry.get("notes") or ""),
            key=f"market_pull_notes_{set_key}",
        )
        save_col, validate_col = st.columns(2)
        save_clicked = save_col.form_submit_button("Enregistrer")
        validate_clicked = validate_col.form_submit_button("Valider explicitement et enregistrer")

    if save_clicked or validate_clicked:
        values = {
            "slots": slot_values,
            "rarities": rarity_values,
            "source_note": source_note,
            "notes": notes,
        }
        try:
            updated, _entry, result = update_pull_rate_entry(
                pull_rates,
                series,
                set_key,
                values,
                validate_now=validate_clicked,
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        save_market_pull_rates(updated)
        if result["errors"]:
            st.warning("Configuration enregistrée, mais à vérifier : " + " ; ".join(result["errors"]))
        elif result["status"] == "ready":
            st.success("Pull rates validés : la série est prête côté pull rates.")
        else:
            st.info(f"Configuration enregistrée : {result['status_label']}.")
        st.rerun()


def _render_pull_rates_section(datasets: dict) -> None:
    st.markdown("##### Pull rates VMC")
    series = infer_market_series(datasets.get("series_config"))
    pull_rates = normalise_market_pull_rates(datasets.get("pull_rates"), series)
    table = [_entry_to_table_row(item, pull_rates) for item in series]
    st.dataframe(table, hide_index=True, use_container_width=True)

    options = {f"{item['release_rank']:02d} · {item['name_fr']} ({item['set_id']})": item for item in series}
    selected_label = st.selectbox(
        "Série à configurer",
        list(options.keys()),
        key="market_pull_rate_select",
    )
    if st.button("Configurer cette série", key="market_pull_rate_open_config"):
        st.session_state["market_pull_rate_selected_set"] = options[selected_label]["set_id"]
        st.rerun()

    _render_pull_rate_form(series, pull_rates)

    st.markdown("##### Import / export Pull rates")
    st.download_button(
        "Exporter les pull rates JSON",
        data=export_pull_rates_json(pull_rates, series),
        file_name="market_pull_rates.json",
        mime="application/json",
        key="market_pull_rate_export",
    )
    raw_import = st.text_area(
        "Importer un JSON de pull rates",
        placeholder='{"sets": {"sv04.5": {"slots": {...}, "rarities": {...}}}}',
        key="market_pull_rate_import_text",
    )
    if st.button("Prévisualiser l'import", key="market_pull_rate_preview"):
        preview = preview_pull_rates_import(raw_import, pull_rates, series)
        st.session_state["market_pull_rate_import_preview"] = preview
    preview = st.session_state.get("market_pull_rate_import_preview")
    if isinstance(preview, dict):
        st.caption(f"{len(preview.get('valid', []))} série(s) modifiable(s) détectée(s).")
        for error in preview.get("errors", []):
            st.error(error)
        for warning in preview.get("warnings", []):
            st.warning(warning)
        if preview.get("valid") and not preview.get("errors"):
            names = ", ".join(item.get("set_name") or item.get("set_id") for item in preview["valid"])
            st.info(f"Prévisualisation : {names}")
            if st.button("Confirmer l'import", key="market_pull_rate_apply_import"):
                updated = apply_pull_rates_import(pull_rates, series, preview)
                save_market_pull_rates(updated)
                st.session_state.pop("market_pull_rate_import_preview", None)
                st.success("Import appliqué aux séries présentes dans le JSON.")
                st.rerun()


def _render_cardmarket_official_source_section() -> None:
    ensure_cardmarket_files()
    state = load_cardmarket_source_state()
    audit = audit_official_cardmarket_source(state)
    mappings = load_cardmarket_mappings()
    rows = mappings.get("mappings", []) if isinstance(mappings.get("mappings"), list) else []
    confirmed = sum(1 for item in rows if isinstance(item, dict) and item.get("mapping_status") == "confirmed")
    review = sum(1 for item in rows if isinstance(item, dict) and item.get("mapping_status") in {"candidate", "needs_review"})
    unmapped = sum(1 for item in rows if isinstance(item, dict) and item.get("mapping_status") in {"unmapped", None, ""})

    st.markdown("##### Source de prix officielle Cardmarket")
    st.caption("Source officielle publique, lecture seule. Aucun prix n'est écrit dans le stock, les lots ou les estimations.")
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Téléchargement", state.get("source_status") or "not_downloaded")
    col_b.metric("Produits", int(state.get("catalog_row_count") or 0))
    col_c.metric("Prix", int(state.get("price_row_count") or 0))
    st.caption(f"Dernière actualisation : {state.get('last_refresh_at') or 'Jamais'}")
    st.caption(
        "Politique FR NM exacte : "
        + ("vérifiée" if state.get("price_policy_status") == "price_policy_supported" else "non vérifiée")
    )
    st.caption(f"Mappings : {confirmed} confirmé(s), {review} à vérifier, {unmapped} non mappé(s)")
    message = audit.get("fr_nm_exact_policy", {}).get("message")
    if message:
        st.info(message)
    if st.button("Actualiser les données officielles Cardmarket", key="market_refresh_official_cardmarket"):
        try:
            result = refresh_official_cardmarket_data()
        except Exception as exc:
            st.error(f"Actualisation Cardmarket impossible : {exc}")
        else:
            new_state = result["state"]
            st.success(
                "Données officielles téléchargées : "
                f"{new_state.get('catalog_row_count', 0)} produits, "
                f"{new_state.get('price_row_count', 0)} prix."
            )
            st.rerun()


def _render_external_price_api_test_section() -> None:
    st.markdown("##### Test API externe FR NM")
    if not EXTERNAL_PRICE_API_AUDIT_FILE.exists():
        st.caption("Non testé")
        return
    try:
        with EXTERNAL_PRICE_API_AUDIT_FILE.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError):
        st.caption("Non testé")
        return
    status = report.get("overall_status") or "not_ready_for_integration"
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if status == "candidate_for_future_integration":
        st.success("Test terminé — candidat à vérifier")
    elif report.get("tested_at"):
        st.warning("Test terminé — intégration refusée")
    else:
        st.caption("Non testé")
    st.caption(
        "Résultat : "
        f"{summary.get('pass', 0)} PASS, "
        f"{summary.get('warn', 0)} WARN, "
        f"{summary.get('fail', 0)} FAIL · "
        f"{report.get('request_count', 0)} requête(s)"
    )


def _render_cardtrader_test_section() -> None:
    state = load_cardtrader_source_state()
    status = state.get("source_status") or "not_tested"
    if status == "not_tested":
        label = "Non testé"
    elif state.get("read_only_test_completed"):
        label = "Résultat disponible"
    else:
        label = "En cours"
    st.markdown("##### CardTrader FR/NM — test lecture seule")
    st.caption(label)


def _render_technical_panel(datasets: dict) -> None:
    st.markdown('<div class="market-technical-panel">', unsafe_allow_html=True)
    with st.expander("Paramètres et sources", expanded=False):
        audit = audit_price_source()
        if audit.get("exact_cardmarket_fr_nm_available"):
            st.success(audit.get("status_label", "Source exacte disponible"))
        else:
            st.warning(audit.get("status_label", "Premier prix Cardmarket FR NM exact : indisponible"))
            st.caption(audit.get("explanation", "Aucune source exacte autorisée détectée."))
        caps = audit.get("capabilities", {})
        st.caption(
            "Capacités : "
            + ", ".join(
                f"{label}={'OK' if caps.get(key) else 'Non'}"
                for label, key in (
                    ("produit exact", "product_exact_search"),
                    ("français", "language_filter_fr"),
                    ("Near Mint", "condition_near_mint"),
                    ("annonce disponible", "available_listing_price"),
                    ("variante exacte", "variant_disambiguation"),
                )
            )
        )
        _render_cardmarket_official_source_section()
        _render_external_price_api_test_section()
        _render_cardtrader_test_section()
        _render_pull_rates_section(datasets)

        st.markdown("##### Couleur des séries")
        series = infer_market_series(datasets.get("series_config"))
        if series:
            selected = st.selectbox(
                "Série",
                series,
                format_func=lambda item: item.get("name_fr") or item.get("set_id"),
                key="market_technical_series_color",
            )
            current = selected.get("color") or stable_series_color(selected.get("set_id"))
            color = st.color_picker("Couleur stable", current, key="market_technical_color_picker")
            if st.button("Enregistrer la couleur", key="market_technical_save_color"):
                config = datasets.get("series_config", {})
                overrides = config.setdefault("series_overrides", {})
                key = str(selected.get("set_id") or "").upper()
                overrides.setdefault(key, {})
                overrides[key]["color"] = color
                overrides[key]["set_id"] = selected.get("set_id")
                overrides[key]["name_fr"] = selected.get("name_fr")
                save_market_series_config(config)
                st.success("Couleur enregistrée.")
                st.rerun()
        st.markdown("##### Datasets Marché séparés")
        for key, path in MARKET_DATASETS.items():
            st.caption(f"{key} : {path}")
        st.caption("Ces fichiers sont séparés de data.json et réservés au module Marché.")
    st.markdown("</div>", unsafe_allow_html=True)


def render_market_page(*, render_page_header_func=None, fp_func=None, is_mobile_mode_func=None):
    del render_page_header_func, fp_func, is_mobile_mode_func
    _market_page_css()
    datasets = load_market_datasets()
    payload = _payload_from_datasets(datasets)
    st.markdown('<div class="market-component-anchor"></div>', unsafe_allow_html=True)
    event = market_dashboard(payload, key="market_dashboard_component")
    _handle_dashboard_event(event, datasets, payload["cards"])
    _render_technical_panel(datasets)

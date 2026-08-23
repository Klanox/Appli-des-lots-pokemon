"""Statistics page renderer for Pokestock."""

from __future__ import annotations

from collections import defaultdict
import datetime as dt_module
import html
import json
import os
from datetime import datetime
from statistics import median

import plotly.graph_objects as go
import streamlit as st

from core.trade_economics import trade_sale_stat_rows
from services.perf_service import perf_log, perf_timer
from services.vinted_channels import SALE_CHANNELS, normalize_vinted_channel


MOIS_FR = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}
STATS_SECTIONS = ("Vue globale", "Records & objectifs")


def _safe_float(value, default=0.0):
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return int(default)


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _month_label(month_key: str) -> str:
    try:
        dt = datetime.strptime(str(month_key), "%Y-%m")
        return f"{MOIS_FR[dt.month]} {dt.year}"
    except Exception:
        return str(month_key or "N/A")


def _month_start(month_key: str) -> datetime | None:
    try:
        return datetime.strptime(str(month_key), "%Y-%m")
    except Exception:
        return None


def _add_months(date_value: datetime, months: int) -> datetime:
    month = date_value.month - 1 + months
    year = date_value.year + month // 12
    month = month % 12 + 1
    return date_value.replace(year=year, month=month, day=1)


def _period_months(months_sorted, current_month, period):
    if period == "Tout":
        return list(months_sorted)
    count = {"Ce mois": 1, "3 mois": 3, "6 mois": 6, "1 an": 12}.get(period, 1)
    current_start = _month_start(current_month) or datetime.now().replace(day=1)
    start = _add_months(current_start, -(count - 1))
    return [m for m in months_sorted if (dt := _month_start(m)) and start <= dt <= current_start]


def _previous_period(months, months_sorted):
    if not months:
        return []
    starts = [_month_start(m) for m in months if _month_start(m)]
    if not starts:
        return []
    first = min(starts)
    count = len(months)
    prev_end = _add_months(first, -1)
    prev_start = _add_months(prev_end, -(count - 1))
    return [m for m in months_sorted if (dt := _month_start(m)) and prev_start <= dt <= prev_end]


def _fmt_eur(value):
    if value is None:
        return "N/A"
    return f"{float(value):,.2f}€".replace(",", " ").replace(".", ",")


def _fmt_pct(value):
    if value is None:
        return "N/A"
    return f"{float(value):.1f}%".replace(".", ",")


def _pct_change(new, old):
    if old in (None, 0):
        return None
    return ((new - old) / old) * 100


def _delta_text(new, old):
    pct = _pct_change(new, old)
    if pct is None:
        return None
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}% vs période préc.".replace(".", ",")


def _is_system_lot(lot):
    name = str(lot.get("nom") or "").lower()
    return bool(lot.get("is_trade") or lot.get("is_storage") or lot.get("is_collection_lot") or "trade" in name or "stockage" in name or "collection" in name)


def _normalize_channel(value):
    raw = str(normalize_vinted_channel(value) or value or "").strip()
    aliases = {"": "Non renseigné", "Vente": "Main propre", "Dexify_TCG": "Dexify", "Main": "Main propre"}
    return aliases.get(raw, raw)


def _transaction_key(row, fallback_idx=0):
    sale = row.get("sale") or {}
    return sale.get("sale_transaction_id") or sale.get("transaction_id") or sale.get("sale_id") or f"{row.get('date')}-{row.get('card_name')}-{fallback_idx}"


def _collect_statistics_data(cd, *, calc_cout_lot_func, effective_purchase_price_func, lots_archives_path):
    all_sales = []
    purchase_rows = []
    all_lots = list(cd.get("lots", []))
    archives_list = []
    if os.path.exists(lots_archives_path):
        with open(lots_archives_path, "r", encoding="utf-8") as f:
            archives_list = json.load(f)

    stats_collect_start = dt_module.datetime.now()
    for lot_idx_s, lot in enumerate(all_lots + archives_list):
        real_lot_idx = lot_idx_s if lot_idx_s < len(all_lots) else None
        lot_name = lot.get("nom", "?")
        lot_uid = lot.get("lot_uid") or f"lot_{lot_idx_s}"
        is_system = _is_system_lot(lot)
        purchase_date = _parse_dt(lot.get("created") or lot.get("created_at") or lot.get("date_achat") or lot.get("date"))
        purchase_cost = _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat", 0)))
        if purchase_date and purchase_cost > 0 and not is_system:
            purchase_rows.append({"date": purchase_date, "month": purchase_date.strftime("%Y-%m"), "lot": lot_name, "cost": purchase_cost})

        try:
            ventes_avec_cout, valeur_est = calc_cout_lot_func(lot, lot_idx=real_lot_idx)
        except Exception:
            ventes_avec_cout, valeur_est = [], 0.0

        for v in lot.get("ventes", []) or []:
            if v.get("is_lot_sale") or v.get("is_exchange_benefit"):
                continue
            d = _parse_dt(v.get("date"))
            if not d:
                continue
            price = _safe_float(v.get("price"))
            qty = max(1, _safe_int(v.get("quantity"), 1))
            if v.get("is_off_stock") and v.get("cost_basis_known"):
                cost = _safe_float(v.get("cost_basis"))
            elif lot.get("is_mixte") and _safe_float(lot.get("valeur_totale")) > 0:
                cost = (price / (_safe_float(lot.get("valeur_totale")) or 1.0)) * _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat", 0)))
            else:
                cost = (price / (_safe_float(valeur_est) or 1.0)) * effective_purchase_price_func(lot)
            all_sales.append({
                "sale": v, "date": d, "month": d.strftime("%Y-%m"), "price": price, "quantity": qty,
                "card_name": v.get("card_name") or v.get("description") or "Vente lot",
                "card_image": v.get("card_image", ""), "lot": lot_name, "lot_uid": lot_uid,
                "unit_price": price / max(qty, 1), "cost": cost, "benef": price - cost,
                "cote": _safe_float(v.get("suggested_price_at_sale"), price), "canal": _normalize_channel(v.get("canal")),
                "is_off_stock": bool(v.get("is_off_stock")), "is_system_lot": is_system,
            })

        for card, se, cout_total in ventes_avec_cout:
            if se.get("is_exchange"):
                continue
            d = _parse_dt(se.get("date"))
            if not d:
                continue
            qty = max(1, _safe_int(se.get("quantity"), 1))
            price = _safe_float(se.get("price"))
            card_img = card.get("image_url", "") or card.get("image", "")
            suggested_unit = _safe_float(se.get("suggested_price_at_sale"), _safe_float(card.get("suggested_price")))
            cote_total = suggested_unit * qty if suggested_unit > 0 else price
            base_row = {
                "sale": se, "date": d, "month": d.strftime("%Y-%m"),
                "card_name": se.get("card_name", card.get("name", "?")), "card_image": card_img,
                "unit_price": price / max(qty, 1), "canal": _normalize_channel(se.get("canal")),
                "is_off_stock": False, "is_system_lot": is_system,
            }
            if card.get("received_by_exchange") and (card.get("trade_contributors") or card.get("exchange_repartition")):
                for row in trade_sale_stat_rows(card, se, lot_name):
                    ratio = _safe_float(row.get("ratio"), 1.0)
                    all_sales.append({
                        **base_row, "price": _safe_float(row.get("price")), "quantity": qty * ratio,
                        "lot": row.get("lot", lot_name), "lot_uid": lot_uid, "cost": _safe_float(row.get("cost")),
                        "benef": _safe_float(row.get("benef")), "cote": cote_total * ratio,
                        "is_system_lot": _is_system_lot({"nom": row.get("lot", lot_name)}),
                        "is_trade_allocation": bool(row.get("allocation")),
                    })
                continue
            all_sales.append({
                **base_row, "price": price, "quantity": qty, "lot": lot_name, "lot_uid": lot_uid,
                "cost": cout_total, "benef": price - cout_total, "cote": cote_total,
            })

    for sale in cd.get("ventes_hors_stock", []) or []:
        d = _parse_dt(sale.get("date"))
        if not d:
            continue
        price = _safe_float(sale.get("price"))
        qty = max(1, _safe_int(sale.get("quantity"), 1))
        cost = _safe_float(sale.get("cost_basis")) if sale.get("cost_basis_known") else None
        all_sales.append({
            "sale": sale, "date": d, "month": d.strftime("%Y-%m"), "price": price, "quantity": qty,
            "card_name": sale.get("card_name") or sale.get("description") or sale.get("category") or "Vente hors stock",
            "card_image": "", "lot": sale.get("source_lot_name") or "Hors stock", "lot_uid": sale.get("source_lot_id") or "off_stock",
            "unit_price": price / max(qty, 1), "cost": cost, "benef": (price - cost) if cost is not None else None,
            "cote": _safe_float(sale.get("suggested_price_at_sale"), price), "canal": _normalize_channel(sale.get("canal")),
            "is_off_stock": True, "is_system_lot": True,
        })

    perf_log("stats collect sales", (dt_module.datetime.now() - stats_collect_start).total_seconds(), f"sales={len(all_sales)} purchases={len(purchase_rows)}")
    return all_sales, purchase_rows


def _build_monthly_stats(all_sales, purchases):
    stats = defaultdict(lambda: {"ca": 0.0, "benef": 0.0, "benef_known": True, "qty": 0.0, "transactions": set(), "purchases": 0.0})
    for idx, row in enumerate(all_sales):
        item = stats[row["month"]]
        item["ca"] += _safe_float(row.get("price"))
        if row.get("benef") is None:
            item["benef_known"] = False
        else:
            item["benef"] += _safe_float(row.get("benef"))
        item["qty"] += _safe_float(row.get("quantity"))
        item["transactions"].add(_transaction_key(row, idx))
    for row in purchases:
        stats[row["month"]]["purchases"] += _safe_float(row.get("cost"))
    return stats


def _aggregate_sales(rows):
    transactions = {_transaction_key(row, idx) for idx, row in enumerate(rows)}
    ca = sum(_safe_float(row.get("price")) for row in rows)
    known_benef = [row.get("benef") for row in rows if row.get("benef") is not None]
    benef = sum(_safe_float(value) for value in known_benef) if known_benef else None
    qty = sum(_safe_float(row.get("quantity")) for row in rows)
    return {
        "ca": ca,
        "benef": benef,
        "qty": qty,
        "transactions": len(transactions),
        "basket": ca / len(transactions) if transactions else 0.0,
        "avg_card": ca / qty if qty else 0.0,
        "margin": (benef / ca * 100.0) if benef is not None and ca else None,
    }


def _month_profile(month, monthly_stats, months_sorted):
    current = monthly_stats.get(month)
    if not current:
        return None
    historic = [monthly_stats[m] for m in months_sorted if m != month and monthly_stats[m].get("ca", 0) > 0]
    if len(historic) < 2:
        return None
    ca_values = [item["ca"] for item in historic]
    benef_values = [item["benef"] for item in historic]
    qty_values = [item["qty"] for item in historic]
    purchase_values = [item["purchases"] for item in historic]
    avg_ca = sum(ca_values) / len(ca_values)
    med_ca = median(ca_values)
    avg_benef = sum(benef_values) / len(benef_values)
    avg_qty = sum(qty_values) / len(qty_values)
    avg_purchases = sum(purchase_values) / len(purchase_values) if purchase_values else 0.0
    idx = months_sorted.index(month)
    prev = monthly_stats.get(months_sorted[idx - 1]) if idx > 0 else None
    ca = current["ca"]
    benef = current["benef"]
    qty = current["qty"]
    purchases = current["purchases"]
    margin = (benef / ca * 100.0) if ca else 0.0
    if ca >= max(ca_values + [ca]) and ca > avg_ca * 1.25:
        return "🏆 Mois record", "CA au plus haut de l'historique"
    if ca > max(avg_ca * 1.8, med_ca * 1.7):
        return "🚀 Mois explosif", "CA nettement au-dessus de la tendance"
    if purchases > max(avg_purchases * 1.8, ca * 0.9) and purchases > 0:
        return "🌱 Mois d'investissement", "Achats nettement supérieurs à la moyenne"
    if qty > avg_qty * 1.5 and ca >= avg_ca * 0.8:
        return "📦 Mois de volume", "Beaucoup plus de cartes vendues que d'habitude"
    if benef >= max(benef_values + [benef]) or (benef > avg_benef * 1.35 and margin >= 35):
        return "💎 Mois rentable", "Bénéfice et marge solides"
    if prev and ca > prev.get("ca", 0) * 1.35 and ca > avg_ca:
        return "🔥 Mois vendeur", "Forte progression par rapport au mois précédent"
    if ca < avg_ca * 0.45 and qty < avg_qty * 0.6:
        return "🌿 Mois calme", "Activité inférieure à la moyenne"
    if ca < avg_ca * 0.7 and prev and ca < prev.get("ca", 0) * 0.75:
        return "📉 Mois en retrait", "Recul par rapport à la tendance récente"
    if margin >= 25 and qty >= avg_qty * 0.8:
        return "⚖️ Mois équilibré", "CA, marge et volume restent cohérents"
    if ca > avg_ca and qty < avg_qty * 0.8:
        return "🛒 Mois acheteur", "Moins de volume mais panier moyen plus élevé"
    return "⚖️ Mois équilibré", "Activité proche de la tendance historique"


def _short_profile_label(profile_label):
    if not profile_label:
        return "N/A"
    parts = str(profile_label).split(maxsplit=1)
    if len(parts) == 1:
        return parts[0]
    label = parts[1].replace("Mois ", "").strip()
    return f"{parts[0]} {label}".strip()


def _blank_month_stats():
    return {"ca": 0.0, "benef": 0.0, "benef_known": True, "qty": 0.0, "transactions": set(), "purchases": 0.0}


def _inject_stats_css():
    st.markdown(
        """
        <style>
        .ps-stats-hero{background:linear-gradient(135deg,rgba(109,93,252,.14),rgba(14,165,233,.08));border:1px solid rgba(109,93,252,.18);border-radius:18px;padding:1rem 1.15rem;margin-bottom:.9rem}
        .ps-stats-hero h2{margin:0;color:#111827;font-size:1.45rem;font-weight:850}.ps-stats-hero p{margin:.2rem 0 0;color:#64748b;font-size:.92rem}
        .ps-stats-month-summary{background:linear-gradient(135deg,#f7f5ff,#ffffff);border:1px solid #ded8ff;border-radius:16px;padding:.9rem 1rem;margin-bottom:.85rem;box-shadow:0 8px 24px rgba(109,93,252,.08)}
        .ps-stats-month-summary .month{font-size:1.15rem;color:#111827;font-weight:900}.ps-stats-month-summary .profile{font-size:1rem;color:#4c1d95;font-weight:850;margin-top:.1rem}.ps-stats-month-summary .why{font-size:.84rem;color:#64748b;margin-top:.2rem}
        .ps-stats-kpi{background:#fff;border:1px solid #e8e5ff;border-radius:16px;padding:.95rem 1rem;box-shadow:0 6px 20px rgba(15,23,42,.06);min-height:112px}
        .ps-stats-kpi .label{color:#64748b;font-size:.78rem;font-weight:750;text-transform:uppercase;letter-spacing:.02em}.ps-stats-kpi .value{color:#111827;font-size:1.45rem;font-weight:900;margin-top:.2rem}.ps-stats-kpi .delta{color:#6d5dfc;font-size:.78rem;font-weight:750;margin-top:.35rem}
        .ps-stats-card{background:#fff;border:1px solid #ece9ff;border-radius:16px;padding:.9rem 1rem;box-shadow:0 6px 18px rgba(15,23,42,.045);margin-bottom:.65rem}
        .ps-stats-month-strip{display:flex;flex-wrap:wrap;gap:.45rem;margin:.35rem 0 .8rem}.ps-stats-month-chip{background:#fff;border:1px solid #ece9ff;border-radius:999px;padding:.42rem .62rem;color:#1e1b4b;font-size:.8rem;font-weight:850;box-shadow:0 4px 12px rgba(15,23,42,.04)}.ps-stats-month-chip small{color:#64748b;font-weight:750;margin-left:.25rem}
        .ps-stats-secondary-line{display:flex;flex-wrap:wrap;gap:.55rem;margin:.1rem 0 .9rem}.ps-stats-secondary-pill{background:#f8f7ff;border:1px solid #e5ddff;border-radius:999px;padding:.5rem .75rem;color:#4338ca;font-size:.82rem;font-weight:850}
        .ps-stats-note{border-left:4px solid #6d5dfc;background:#f8f7ff;border-radius:12px;padding:.8rem 1rem;color:#4338ca;font-weight:700;margin:.5rem 0}
        div[data-testid="stPills"] button[aria-checked="true"],div[data-testid="stSegmentedControl"] button[aria-checked="true"]{background:#6d5dfc!important;color:#fff!important;border-color:#6d5dfc!important;box-shadow:0 8px 18px rgba(109,93,252,.22)}
        div[data-testid="stPills"] button,div[data-testid="stSegmentedControl"] button{border-radius:999px!important;font-weight:800!important}
        @media (max-width:768px){.ps-stats-kpi{min-height:auto;padding:.85rem}.ps-stats-kpi .value{font-size:1.2rem}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_kpi_cards(items):
    columns = st.columns(len(items))
    for col, item in zip(columns, items):
        with col:
            st.markdown(
                f'<div class="ps-stats-kpi"><div class="label">{html.escape(item["label"])}</div><div class="value">{html.escape(str(item["value"]))}</div><div class="delta">{html.escape(item.get("delta") or " ")}</div></div>',
                unsafe_allow_html=True,
            )


def _render_horizontal_bar(rows, x_key, y_key, title, key, color="#6d5dfc", suffix="€"):
    if not rows:
        st.info("Pas assez de données pour ce graphique.")
        return
    rows = list(reversed(rows))
    x_vals = [row[x_key] for row in rows]
    y_vals = [row[y_key] for row in rows]
    text = [(_fmt_eur(v) if suffix == "€" else _fmt_pct(v) if suffix == "%" else f"{v:.1f}") for v in x_vals]
    fig = go.Figure(go.Bar(x=x_vals, y=y_vals, orientation="h", marker_color=color, text=text, textposition="outside", hovertemplate="%{y}<br>%{x:.2f}<extra></extra>"))
    fig.update_layout(title=title, height=max(280, 34 * len(rows) + 80), margin=dict(t=42, b=8, l=8, r=70), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor="#f1f5f9", zeroline=False), yaxis=dict(showgrid=False), showlegend=False)
    st.plotly_chart(fig, width="stretch", key=key)


def _render_global_view(all_sales, monthly_stats, months_sorted, current_month):
    current_start = _month_start(current_month) or datetime.now().replace(day=1)
    prev_month = _add_months(current_start, -1).strftime("%Y-%m")
    current_metrics = monthly_stats.get(current_month, _blank_month_stats())
    prev_metrics = monthly_stats.get(prev_month)
    current_rows = [row for row in all_sales if row["month"] == current_month]
    prev_rows = [row for row in all_sales if row["month"] == prev_month]
    metrics = _aggregate_sales(current_rows) if current_rows else {
        "ca": _safe_float(current_metrics.get("ca")),
        "benef": _safe_float(current_metrics.get("benef")),
        "qty": _safe_float(current_metrics.get("qty")),
        "transactions": 0,
        "basket": 0.0,
        "avg_card": 0.0,
        "margin": (_safe_float(current_metrics.get("benef")) / _safe_float(current_metrics.get("ca")) * 100.0) if _safe_float(current_metrics.get("ca")) else None,
    }
    prev = _aggregate_sales(prev_rows) if prev_rows else ({
        "ca": _safe_float(prev_metrics.get("ca")),
        "benef": _safe_float(prev_metrics.get("benef")),
        "qty": _safe_float(prev_metrics.get("qty")),
        "margin": (_safe_float(prev_metrics.get("benef")) / _safe_float(prev_metrics.get("ca")) * 100.0) if _safe_float(prev_metrics.get("ca")) else None,
    } if prev_metrics else None)
    current_profile = _month_profile(current_month, monthly_stats, months_sorted)
    if current_profile is None:
        if metrics["ca"] <= 0 and metrics["qty"] <= 0:
            current_profile = ("🌿 Mois calme", "Aucune vente enregistrée ce mois-ci pour l'instant.")
        else:
            current_profile = ("⚖️ Mois équilibré", "Activité en cours, historique encore trop court pour une qualification fine.")
    st.markdown(
        '<div class="ps-stats-month-summary">'
        f'<div class="month">{html.escape(_month_label(current_month))}</div>'
        f'<div class="profile">{html.escape(current_profile[0])}</div>'
        f'<div class="why">{html.escape(current_profile[1])}</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    _render_kpi_cards([
        {"label": "CA", "value": _fmt_eur(metrics["ca"]), "delta": _delta_text(metrics["ca"], prev["ca"]) if prev else None},
        {"label": "Bénéfice", "value": _fmt_eur(metrics["benef"]), "delta": _delta_text(metrics["benef"], prev["benef"]) if prev and metrics["benef"] is not None and prev["benef"] is not None else None},
        {"label": "Marge", "value": _fmt_pct(metrics["margin"]), "delta": _delta_text(metrics["margin"], prev["margin"]) if prev and metrics["margin"] is not None and prev["margin"] is not None else None},
        {"label": "Cartes vendues", "value": f"{metrics['qty']:.0f}", "delta": _delta_text(metrics["qty"], prev["qty"]) if prev else None},
    ])

    months = sorted(set(months_sorted + [current_month]))
    months = months[-12:]
    labels = [_month_label(m) for m in months]
    ca_values = [_safe_float(monthly_stats.get(m, _blank_month_stats()).get("ca")) for m in months]
    benef_values = [_safe_float(monthly_stats.get(m, _blank_month_stats()).get("benef")) for m in months]
    qty_values = [_safe_float(monthly_stats.get(m, _blank_month_stats()).get("qty")) for m in months]
    profiles = [_month_profile(m, monthly_stats, months_sorted) for m in months]
    custom = [[ca_values[idx], benef_values[idx], (benef_values[idx] / ca_values[idx] * 100.0) if ca_values[idx] else 0.0, qty_values[idx], profiles[idx][0] if profiles[idx] else "N/A"] for idx in range(len(months))]
    st.markdown("### Évolution CA & bénéfice")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=labels, y=ca_values, mode="lines+markers", name="CA", line=dict(color="#6d5dfc", width=3), marker=dict(size=9), customdata=custom, hovertemplate="%{x}<br>CA : %{y:.2f}€<br>Bénéfice : %{customdata[1]:.2f}€<br>Marge : %{customdata[2]:.1f}%<br>Cartes : %{customdata[3]:.0f}<br>%{customdata[4]}<extra></extra>"))
    fig.add_trace(go.Scatter(x=labels, y=benef_values, mode="lines+markers", name="Bénéfice", line=dict(color="#16a34a", width=3), marker=dict(size=9), customdata=custom, hovertemplate="%{x}<br>Bénéfice : %{y:.2f}€<br>CA : %{customdata[0]:.2f}€<br>Marge : %{customdata[2]:.1f}%<br>Cartes : %{customdata[3]:.0f}<br>%{customdata[4]}<extra></extra>"))
    fig.update_layout(height=330, margin=dict(t=12, b=8, l=8, r=8), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", yaxis=dict(title="€", gridcolor="#f1f5f9"), xaxis=dict(showgrid=False), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, width="stretch", key="stats_v2_global_ca_benef")

    st.markdown("### Profil des mois")
    month_chips = []
    for m in months[-8:]:
        profile = _month_profile(m, monthly_stats, months_sorted)
        if not profile:
            continue
        stat = monthly_stats.get(m, _blank_month_stats())
        month_name = _month_label(m).split()[0][:4].rstrip(".")
        month_chips.append(
            f'<span class="ps-stats-month-chip">{html.escape(month_name)} · {html.escape(_short_profile_label(profile[0]))}'
            f'<small>{_fmt_eur(stat["ca"])} · {_fmt_eur(stat["benef"])}</small></span>'
        )
    if month_chips:
        st.markdown(f'<div class="ps-stats-month-strip">{"".join(month_chips)}</div>', unsafe_allow_html=True)
    else:
        st.info("Pas encore assez d'historique pour qualifier les mois proprement.")


def _render_lots_view(all_sales, cd):
    lot_meta = {}
    for idx, lot in enumerate(cd.get("lots", []) or []):
        if _is_system_lot(lot):
            continue
        lot_meta[lot.get("nom", f"Lot {idx + 1}")] = {"cost": _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat", 0)))}
    lot_rows = {}
    for row in all_sales:
        if row.get("is_system_lot") or row.get("is_off_stock"):
            continue
        name = row.get("lot") or "Lot inconnu"
        item = lot_rows.setdefault(name, {"lot": name, "ca": 0.0, "benef": 0.0, "qty": 0.0, "cost": lot_meta.get(name, {}).get("cost", 0.0)})
        item["ca"] += _safe_float(row.get("price"))
        item["qty"] += _safe_float(row.get("quantity"))
        if row.get("benef") is not None:
            item["benef"] += _safe_float(row.get("benef"))
    for item in lot_rows.values():
        cost = item.get("cost", 0.0)
        item["roi"] = (item["benef"] / cost * 100.0) if cost > 0 else None
        item["remboursement"] = (item["ca"] / cost * 100.0) if cost > 0 else None
        item["reste"] = max(0.0, cost - item["ca"]) if cost > 0 else 0.0

    sort_metric = st.segmented_control("Tri", ["CA", "Bénéfice", "ROI"], default="CA", key="stats_lots_sort", width="content")
    metric_key, suffix = {"CA": ("ca", "€"), "Bénéfice": ("benef", "€"), "ROI": ("roi", "%")}.get(sort_metric or "CA", ("ca", "€"))
    top = sorted([row for row in lot_rows.values() if row.get(metric_key) is not None], key=lambda row: row.get(metric_key) or 0, reverse=True)[:10]
    _render_horizontal_bar(top, metric_key, "lot", f"Top lots par {sort_metric}", "stats_v2_lots_top", color="#6d5dfc", suffix=suffix)

    left, right = st.columns(2)
    with left:
        st.markdown("### Lots encore non remboursés")
        pending = sorted([row for row in lot_rows.values() if row.get("reste", 0) > 0 and row.get("cost", 0) > 0], key=lambda row: row["reste"], reverse=True)[:10]
        st.dataframe([{"Lot": row["lot"], "Coût": round(row["cost"], 2), "CA généré": round(row["ca"], 2), "Reste": round(row["reste"], 2), "Remb.": _fmt_pct(row.get("remboursement"))} for row in pending], width="stretch", hide_index=True, key="stats_v2_lots_unreimbursed")
    with right:
        st.markdown("### Lots les plus performants")
        best = sorted([row for row in lot_rows.values() if row.get("benef", 0) != 0], key=lambda row: row["benef"], reverse=True)[:10]
        st.dataframe([{"Lot": row["lot"], "CA": round(row["ca"], 2), "Bénéfice": round(row["benef"], 2), "ROI": _fmt_pct(row.get("roi")), "Cartes": round(row["qty"], 1)} for row in best], width="stretch", hide_index=True, key="stats_v2_lots_best")
    st.markdown("### Lots à surveiller")
    worst = sorted([row for row in lot_rows.values() if row.get("benef", 0) < 0], key=lambda row: row["benef"])[:8]
    if worst:
        st.dataframe([{"Lot": row["lot"], "Bénéfice": round(row["benef"], 2), "CA": round(row["ca"], 2), "Coût": round(row["cost"], 2)} for row in worst], width="stretch", hide_index=True, key="stats_v2_lots_worst")
    else:
        st.markdown('<div class="ps-stats-note">Aucun lot en perte nette dans les données calculables.</div>', unsafe_allow_html=True)


def _render_channels_view(all_sales):
    channel_rows = {}
    for row in all_sales:
        channel = _normalize_channel(row.get("canal"))
        item = channel_rows.setdefault(channel, {"channel": channel, "ca": 0.0, "benef": 0.0, "benef_known": True, "qty": 0.0, "transactions": set()})
        item["ca"] += _safe_float(row.get("price"))
        item["qty"] += _safe_float(row.get("quantity"))
        item["transactions"].add(_transaction_key(row, len(item["transactions"])))
        if row.get("benef") is None:
            item["benef_known"] = False
        else:
            item["benef"] += _safe_float(row.get("benef"))
    for item in channel_rows.values():
        item["sales"] = len(item["transactions"])
        item["margin"] = (item["benef"] / item["ca"] * 100.0) if item["ca"] and item["benef_known"] else None
        item["basket"] = item["ca"] / item["sales"] if item["sales"] else 0.0
        item["avg_card"] = item["ca"] / item["qty"] if item["qty"] else 0.0
    ordered_names = [*SALE_CHANNELS, *sorted(name for name in channel_rows if name not in SALE_CHANNELS)]
    rows = [channel_rows[name] for name in ordered_names if name in channel_rows]
    metric = st.selectbox("Meilleur canal selon", ["CA", "Bénéfice", "Marge", "Panier moyen", "Prix / carte"], key="stats_channel_metric")
    metric_key, suffix = {"CA": ("ca", "€"), "Bénéfice": ("benef", "€"), "Marge": ("margin", "%"), "Panier moyen": ("basket", "€"), "Prix / carte": ("avg_card", "€")}[metric]
    valid = [row for row in rows if row.get(metric_key) is not None]
    best = max(valid, key=lambda row: row.get(metric_key) or 0) if valid else None
    if best:
        value = _fmt_eur(best[metric_key]) if suffix == "€" else _fmt_pct(best[metric_key])
        st.markdown(f'<div class="ps-stats-note">Meilleur canal : {html.escape(best["channel"])} · {value}</div>', unsafe_allow_html=True)
    _render_horizontal_bar(sorted(valid, key=lambda row: row.get(metric_key) or 0, reverse=True), metric_key, "channel", f"Comparatif canaux · {metric}", "stats_v2_channels_chart", color="#0ea5e9", suffix=suffix)
    st.dataframe([{"Canal": row["channel"], "CA": round(row["ca"], 2), "Bénéfice": round(row["benef"], 2) if row["benef_known"] else "N/A", "Marge": _fmt_pct(row.get("margin")), "Ventes": row["sales"], "Cartes": round(row["qty"], 1), "Panier moyen": round(row["basket"], 2), "Prix / carte": round(row["avg_card"], 2)} for row in rows], width="stretch", hide_index=True, key="stats_v2_channels_table")


def _load_month_goals(monthly_goals_path, current_month, prev_month, monthly_stats, months_sorted, safe_write_json_func):
    if os.path.exists(monthly_goals_path):
        with open(monthly_goals_path, "r", encoding="utf-8") as f:
            goals_data = json.load(f)
    else:
        goals_data = {}
    progression_rate = 0.15
    if current_month not in goals_data:
        prev = monthly_stats.get(prev_month, {})
        prev_ca_real = _safe_float(prev.get("ca"))
        prev_qty_real = _safe_float(prev.get("qty"))
        if prev_ca_real > 0:
            goals_data[current_month] = {"ca_target": round(prev_ca_real * (1 + progression_rate), 2), "qty_target": max(1, round(prev_qty_real * (1 + progression_rate))), "benef_target": round(_safe_float(prev.get("benef")) * (1 + progression_rate), 2), "auto_generated": True, "based_on": prev_month}
        else:
            ref_months = [m for m in months_sorted if m < current_month and monthly_stats.get(m, {}).get("ca", 0) > 0]
            ref = monthly_stats.get(ref_months[-1], {}) if ref_months else {}
            goals_data[current_month] = {"ca_target": round(_safe_float(ref.get("ca"), 100) * (1 + progression_rate), 2), "qty_target": max(1, round(_safe_float(ref.get("qty"), 20) * (1 + progression_rate))), "benef_target": round(_safe_float(ref.get("benef"), 30) * (1 + progression_rate), 2), "auto_generated": bool(ref_months), "based_on": ref_months[-1] if ref_months else ""}
        safe_write_json_func(monthly_goals_path, goals_data)
    return goals_data, goals_data[current_month]


def _render_challenge(label, current, target, unit="€", icon="🎯", color="#6d5dfc", motivation=""):
    pct = min((current / target * 100) if target > 0 else 0, 100)
    done = pct >= 100
    bar_color = "#10b981" if done else color
    status = "ACCOMPLI !" if done else f"{current:.0f}{unit} / {target:.0f}{unit}"
    remaining = max(0, target - current)
    msg = "Objectif atteint, bravo !" if done else motivation.format(remaining=f"{remaining:.1f}{unit}")
    st.markdown(f'<div class="ps-stats-card"><div style="display:flex;justify-content:space-between;gap:.7rem;align-items:center;"><span style="font-weight:850;color:#1e293b;">{icon} {html.escape(label)}</span><span style="font-weight:900;color:{bar_color};">{html.escape(status)}</span></div><div style="background:#f1f5f9;border-radius:99px;height:12px;overflow:hidden;margin-top:.65rem;"><div style="height:100%;width:{pct:.1f}%;background:linear-gradient(90deg,{bar_color},{bar_color}bb);border-radius:99px;"></div></div><div style="margin-top:.45rem;font-size:.8rem;color:#64748b;">{html.escape(msg)}</div></div>', unsafe_allow_html=True)


def _render_records_view(all_sales, monthly_stats, months_sorted, current_month, monthly_goals_path, safe_write_json_func):
    total = _aggregate_sales(all_sales)
    best_ca = max(months_sorted, key=lambda m: monthly_stats[m]["ca"]) if months_sorted else None
    best_benef = max(months_sorted, key=lambda m: monthly_stats[m]["benef"]) if months_sorted else None
    best_qty = max(months_sorted, key=lambda m: monthly_stats[m]["qty"]) if months_sorted else None
    transactions = defaultdict(lambda: {"price": 0.0, "date": None, "label": ""})
    for idx, row in enumerate(all_sales):
        key = _transaction_key(row, idx)
        transactions[key]["price"] += _safe_float(row.get("price"))
        transactions[key]["date"] = row.get("date")
        label = row.get("card_name") or "Vente"
        transactions[key]["label"] = label if not transactions[key]["label"] else transactions[key]["label"] + ", " + label
    biggest_tx = max(transactions.values(), key=lambda row: row["price"]) if transactions else None
    records = [
        ("Meilleur mois CA", _month_label(best_ca) if best_ca else "N/A", _fmt_eur(monthly_stats[best_ca]["ca"]) if best_ca else ""),
        ("Meilleur mois bénéfice", _month_label(best_benef) if best_benef else "N/A", _fmt_eur(monthly_stats[best_benef]["benef"]) if best_benef else ""),
        ("Record de cartes vendues", _month_label(best_qty) if best_qty else "N/A", f"{monthly_stats[best_qty]['qty']:.0f} cartes" if best_qty else ""),
        ("Plus grosse transaction", _fmt_eur(biggest_tx["price"]) if biggest_tx else "N/A", biggest_tx["label"][:70] if biggest_tx else ""),
    ]
    cols = st.columns(4)
    for idx, (label, value, detail) in enumerate(records):
        with cols[idx % 4]:
            st.markdown(f'<div class="ps-stats-card"><div style="font-size:.75rem;color:#64748b;font-weight:800;text-transform:uppercase;">{html.escape(label)}</div><div style="font-size:1.15rem;color:#111827;font-weight:900;margin-top:.25rem;">{html.escape(str(value))}</div><div style="font-size:.78rem;color:#64748b;margin-top:.25rem;">{html.escape(str(detail or " "))}</div></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ps-stats-secondary-line">'
        f'<span class="ps-stats-secondary-pill">CA historique · {_fmt_eur(total["ca"])}</span>'
        f'<span class="ps-stats-secondary-pill">Bénéfice historique · {_fmt_eur(total["benef"])}</span>'
        f'<span class="ps-stats-secondary-pill">Panier moyen · {_fmt_eur(total["basket"])}</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown("### Défis du mois")
    current_start = _month_start(current_month) or datetime.now().replace(day=1)
    prev_month = _add_months(current_start, -1).strftime("%Y-%m")
    goals_data, month_goals = _load_month_goals(monthly_goals_path, current_month, prev_month, monthly_stats, months_sorted, safe_write_json_func)
    current = monthly_stats.get(current_month, {})
    if month_goals.get("auto_generated"):
        st.info(f"Objectifs générés automatiquement à partir de {_month_label(month_goals.get('based_on', ''))}.")
    with st.expander("Modifier mes objectifs du mois", expanded=False):
        gc1, gc2, gc3 = st.columns(3)
        new_ca_t = gc1.number_input("Objectif CA (€)", 0.0, 99999.0, value=float(month_goals.get("ca_target", 100.0)), step=10.0, key="stats_goal_ca")
        new_qty_t = gc2.number_input("Cartes à vendre", 0, 9999, value=int(month_goals.get("qty_target", 20)), step=5, key="stats_goal_qty")
        new_benef_t = gc3.number_input("Objectif bénéfice (€)", 0.0, 99999.0, value=float(month_goals.get("benef_target", 30.0)), step=10.0, key="stats_goal_benef")
        if st.button("Sauvegarder les objectifs", key="stats_save_goals"):
            goals_data[current_month] = {"ca_target": new_ca_t, "qty_target": new_qty_t, "benef_target": new_benef_t, "auto_generated": False}
            safe_write_json_func(monthly_goals_path, goals_data)
            st.success("Objectifs mis à jour.")
            st.rerun()
    c1, c2, c3 = st.columns(3)
    with c1:
        _render_challenge("Chiffre d'affaires", _safe_float(current.get("ca")), _safe_float(month_goals.get("ca_target"), 100), "€", "💰", "#6d5dfc", "Plus que {remaining} à réaliser.")
    with c2:
        _render_challenge("Cartes vendues", _safe_float(current.get("qty")), _safe_float(month_goals.get("qty_target"), 20), "", "🃏", "#8b5cf6", "Encore {remaining} cartes à vendre.")
    with c3:
        _render_challenge("Bénéfice", _safe_float(current.get("benef")), _safe_float(month_goals.get("benef_target"), 30), "€", "💎", "#16a34a", "Plus que {remaining} de bénéfice.")


def render_statistics_page(
    *,
    ld_func,
    safe_write_json_func,
    calc_cout_lot_func,
    effective_purchase_price_func,
    proxy_img_func,
    lots_archives_path="lots_archives.json",
    monthly_goals_path="monthly_goals.json",
):
    _inject_stats_css()
    st.markdown('<div class="ps-stats-hero"><h2>Statistiques</h2><p>Vue quotidienne légère : activité du mois, évolution CA/bénéfice, records et objectifs.</p></div>', unsafe_allow_html=True)

    with perf_timer("stats ld"):
        cd = ld_func()

    now = datetime.now()
    current_month = now.strftime("%Y-%m")
    with perf_timer("stats collect"):
        all_sales, purchases = _collect_statistics_data(cd, calc_cout_lot_func=calc_cout_lot_func, effective_purchase_price_func=effective_purchase_price_func, lots_archives_path=lots_archives_path)
        monthly_stats = _build_monthly_stats(all_sales, purchases)
        months_sorted = sorted(monthly_stats.keys())

    if not months_sorted:
        st.info("Aucune vente enregistrée pour le moment.")
        return

    active_default = st.session_state.get("stats_active_section", "Vue globale")
    if active_default not in STATS_SECTIONS:
        active_default = "Vue globale"
        st.session_state["stats_active_section"] = active_default
    active = st.pills("Section", STATS_SECTIONS, default=active_default, key="stats_active_section", label_visibility="collapsed", width="stretch") or "Vue globale"
    if active == "Vue globale":
        _render_global_view(all_sales, monthly_stats, months_sorted, current_month)
    else:
        _render_records_view(all_sales, monthly_stats, months_sorted, current_month, monthly_goals_path, safe_write_json_func)

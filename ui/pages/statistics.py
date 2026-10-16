"""Statistics page renderer for Pokestock."""

from __future__ import annotations

from collections import defaultdict
import datetime as dt_module
import html
import json
import os
from datetime import datetime
from statistics import median
from uuid import uuid4

import plotly.graph_objects as go
import streamlit as st

from core.trade_economics import trade_sale_stat_rows
from services.counters_archive_service import archived_years_summary, ensure_yearly_reset, make_lots_loader
from services.perf_service import perf_log, perf_timer
from services.vinted_channels import SALE_CHANNELS, normalize_vinted_channel
from services.monthly_profiles import (
    PROFILE_METADATA, PROFILE_EXPLANATIONS, annual_record_months, build_profile_stats, profile_tuple, score_profile,
)


MOIS_FR = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}

MONTHLY_PROFILE_EXPLANATIONS = PROFILE_EXPLANATIONS

# -- Historique saisi d'un seul coup (mise en service) --------------------------------------------------------
# Tout l'historique antérieur à l'application a été saisi en mars 2026 : il représente en réalité janvier,
# février et mars. Les statistiques mensuelles le répartissent à parts égales (les JSON ne sont jamais modifiés).
HISTORY_IMPORT_MONTH = "2026-03"        # mois pendant lequel l'historique a été saisi
HISTORY_IMPORT_SPREAD_MONTHS = 3        # nombre de mois sur lesquels il est réparti (janvier, février, mars)
HISTORY_IMPORT_LAST_DAY = "2026-03-17"  # dernier jour de saisie (inclus) ; les ventes suivantes sont de vraies ventes de mars. None = tout le mois
# -- Indicateurs de Performance : rotation du stock et délai de remboursement ------------------------------------
HISTORY_BULK_LOT_DAYS = ("2026-03-16", "2026-03-17", "2026-03-18")  # lots créés pendant la saisie en bloc : vraie date d'achat inconnue
ROTATION_MIN_DAYS = 30        # en dessous, la rotation annualisée est « indicative »
PAYBACK_MIN_LOTS = 3          # lots remboursés minimum ; en dessous, « Pas assez de données »
PAYBACK_PENDING_COUNT = 3     # lots en cours de remboursement affichés (les plus anciens)
SLOW_LOT_MIN_VALUE = 20.0     # € : reste à rembourser minimal pour figurer parmi les lots en cours
DAYS_PER_YEAR = 365.0
HISTORY_ESTIMATED_MARK = "*"
HISTORY_ESTIMATED_NOTE = "* Mois estimés (historique réparti) : l'historique saisi les 16 et 17 mars 2026 est réparti à parts égales entre janvier, février et mars 2026."


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


def _month_label_est(month_key: str) -> str:
    """Libellé du mois, suivi de « * » si le mois est estimé (historique réparti)."""
    return _month_label(month_key) + _estimated_mark(month_key)


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
    return ((new - old) / abs(old)) * 100


def _delta_text(new, old):
    pct = _pct_change(new, old)
    if pct is None:
        return None
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}% vs période préc.".replace(".", ",")


def _rows_between(all_sales, start, end):
    return [row for row in all_sales if isinstance(row.get("date"), datetime) and start <= row["date"] <= end]


def _comparable_month_metrics(all_sales, month_key, *, now=None):
    """Return a month and its previous period on the same elapsed duration.

    A running month compares H+elapsed with the same elapsed span in the prior
    month. Closed months continue to compare complete calendar months.
    """
    now = now or datetime.now()
    month_start = _month_start(month_key)
    if month_start is None:
        return _blank_month_stats(), None, False
    previous_start = _add_months(month_start, -1)
    is_running_month = (month_start.year, month_start.month) == (now.year, now.month)
    if is_running_month:
        current_end = max(month_start, now)
        previous_end = min(previous_start + (current_end - month_start), month_start - dt_module.timedelta(microseconds=1))
    else:
        current_end = _add_months(month_start, 1) - dt_module.timedelta(microseconds=1)
        previous_end = month_start - dt_module.timedelta(microseconds=1)
    current_rows = _rows_between(all_sales, month_start, current_end)
    previous_rows = _rows_between(all_sales, previous_start, previous_end)
    current = _aggregate_sales(current_rows)
    previous = _aggregate_sales(previous_rows)
    if not current_rows:
        current["benef"] = 0.0
    if not previous_rows:
        previous["benef"] = 0.0
    return current, previous, is_running_month


def _comparable_profile_stats(all_sales, purchases, monthly_stats, now):
    """Compare the running month's profile with equally observed historical months."""
    elapsed = now - now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def observed(row):
        date = row.get("date")
        if not isinstance(date, datetime) or date > now:
            return False
        start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = min(start + elapsed, _add_months(start, 1) - dt_module.timedelta(microseconds=1))
        return date <= end

    result = _build_monthly_stats([r for r in all_sales if observed(r)], [r for r in purchases if observed(r)])
    for month in monthly_stats:
        result.setdefault(month, _blank_month_stats())
    return result


def _profile_help_html(profile_label, *, short=False, explanation=None):
    explanation = explanation or MONTHLY_PROFILE_EXPLANATIONS[profile_label]
    tooltip_id = f"profile-help-{uuid4().hex}"
    return (
        f'<span class="ps-stats-profile-label">'
        f'{html.escape(_short_profile_label(profile_label) if short else profile_label)}</span>'
        '<span class="ps-stats-profile-help"><details>'
        f'<summary aria-describedby="{tooltip_id}" aria-label="À propos de {html.escape(profile_label, quote=True)}">?</summary></details>'
        f'<span class="ps-stats-profile-tooltip" id="{tooltip_id}" role="tooltip"><strong>{html.escape(profile_label)}</strong>'
        f'<span>{html.escape(explanation)}</span></span></span>'
    )


def _is_system_lot(lot):
    name = str(lot.get("nom") or "").lower()
    return bool(lot.get("is_trade") or lot.get("is_storage") or lot.get("is_collection_lot") or "trade" in name or "stockage" in name or "collection" in name)


def _normalize_channel(value):
    raw = str(normalize_vinted_channel(value) or value or "").strip()
    aliases = {"": "Non renseigné", "Vente": "Main propre", "Dexify_TCG": "Dexify", "Main": "Main propre"}
    return aliases.get(raw, raw)


def _transaction_key(row, fallback_idx=0):
    if row.get("_tx_key"):
        return row["_tx_key"]
    sale = row.get("sale") or {}
    return sale.get("sale_transaction_id") or sale.get("transaction_id") or sale.get("sale_id") or f"{row.get('date')}-{row.get('card_name')}-{fallback_idx}"


INITIAL_SALES_CHANNEL = "Ventes initiales"


def _physical_sale_quantity(row):
    """DÉFINITION UNIQUE de « cartes vendues » dans Statistiques (mensuel, année, canaux, lots, paliers, objectifs).

    Somme des quantités des ventes de cartes du stock, quantité répartie au prorata pour les cartes reçues par échange.
    Ne comptent pas : les ventes hors stock (pas une carte du stock) et les ventes initiales (montant de cartes vendues
    avant l'enregistrement du lot, dont le nombre est inconnu) ; elles restent dans le CA et le bénéfice.
    Le compteur de la barre latérale (gst) a sa propre définition et peut différer.
    """
    if row.get("is_off_stock") or row.get("is_lot_sale"):
        return 0.0
    return _safe_float(row.get("quantity"))


def _is_card_sale(row):
    """Vente d'une carte du stock (ni hors stock, ni vente initiale)."""
    return not row.get("is_off_stock") and not row.get("is_lot_sale")


def _is_transaction_row(row):
    """Une vente initiale n'est pas une transaction : elle compte dans CA, bénéfice, ROI mais ni dans le nombre
    de transactions ni dans le panier moyen. `_no_transaction` marque une part d'historique réparti sans transaction."""
    return not row.get("is_lot_sale") and not row.get("_no_transaction")


def _row_channel(row):
    """Canal affiché : les ventes initiales forment leur propre canal (affichage seulement, les données ne changent pas)."""
    return INITIAL_SALES_CHANNEL if row.get("is_lot_sale") else _normalize_channel(row.get("canal"))


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
            if v.get("is_exchange_benefit"):
                continue
            d = _parse_dt(v.get("date"))
            if not d:
                continue
            is_lot_sale = bool(v.get("is_lot_sale"))
            price = _safe_float(v.get("price"))
            qty = 0.0 if is_lot_sale else max(1, _safe_int(v.get("quantity"), 1))
            if is_lot_sale and _safe_float(valeur_est) <= 0:
                # Calcul du coût du lot indisponible : coût inconnu plutôt qu'un coût absurde.
                cost = None
            elif v.get("is_off_stock") and v.get("cost_basis_known"):
                cost = _safe_float(v.get("cost_basis"))
            elif lot.get("is_mixte") and _safe_float(lot.get("valeur_totale")) > 0:
                cost = (price / (_safe_float(lot.get("valeur_totale")) or 1.0)) * _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat", 0)))
            else:
                cost = (price / (_safe_float(valeur_est) or 1.0)) * effective_purchase_price_func(lot)
            all_sales.append({
                "sale": v, "date": d, "month": d.strftime("%Y-%m"), "price": price, "quantity": qty,
                "card_name": v.get("card_name") or v.get("description") or "Vente lot",
                "card_number": v.get("card_number") or v.get("number") or v.get("display_number") or "",
                "card_image": v.get("card_image", ""), "lot": lot_name, "lot_uid": lot_uid,
                "unit_price": price / max(qty, 1), "cost": cost, "benef": (price - cost) if cost is not None else None,
                "cote": _safe_float(v.get("suggested_price_at_sale"), price), "canal": _normalize_channel(v.get("canal")),
                "is_off_stock": bool(v.get("is_off_stock")), "is_lot_sale": is_lot_sale, "is_system_lot": is_system,
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
                "card_number": se.get("card_number") or se.get("number") or card.get("display_number") or card.get("number") or "",
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
            "card_number": sale.get("card_number") or sale.get("number") or "",
            "card_image": "", "lot": sale.get("source_lot_name") or "Hors stock", "lot_uid": sale.get("source_lot_id") or "off_stock",
            "unit_price": price / max(qty, 1), "cost": cost, "benef": (price - cost) if cost is not None else None,
            "cote": _safe_float(sale.get("suggested_price_at_sale"), price), "canal": _normalize_channel(sale.get("canal")),
            "is_off_stock": True, "is_system_lot": True,
        })

    perf_log("stats collect sales", (dt_module.datetime.now() - stats_collect_start).total_seconds(), f"sales={len(all_sales)} purchases={len(purchase_rows)}")
    return all_sales, purchase_rows


def _history_spread_months():
    """Mois couverts par l'historique réparti, du plus ancien au mois de saisie (ex. 2026-01, 2026-02, 2026-03)."""
    start = _month_start(HISTORY_IMPORT_MONTH)
    count = max(int(HISTORY_IMPORT_SPREAD_MONTHS or 1), 1)
    if start is None:
        return []
    return [_add_months(start, -offset).strftime("%Y-%m") for offset in range(count - 1, -1, -1)]


def _is_estimated_month(month_key):
    return len(_history_spread_months()) > 1 and str(month_key) in _history_spread_months()


def _estimated_mark(month_key):
    return HISTORY_ESTIMATED_MARK if _is_estimated_month(month_key) else ""


def _any_estimated(months):
    return any(_is_estimated_month(m) for m in months)


def _estimated_note_html(months):
    """Légende « * mois estimés » si au moins un des mois affichés est issu de l'historique réparti."""
    if not _any_estimated(months):
        return ""
    return f'<div class="ps-stats-est-note">{html.escape(HISTORY_ESTIMATED_NOTE)}</div>'


def _split_integer(total, parts):
    """Répartit un entier en `parts` entiers (reste distribué un par un en commençant par le premier mois) ; la somme est exacte."""
    total = int(total)
    base, rest = divmod(total, parts)
    return [base + (1 if idx < rest else 0) for idx in range(parts)]


def _allocate_quantities(quantities, targets):
    """Répartit les quantités de chaque ligne sur les mois pour que chaque mois reçoive exactement sa cible.

    `sum(targets)` doit égaler `sum(quantities)` ; l'allocation est déterministe (lignes dans l'ordre, mois dans l'ordre)
    et conserve la quantité de chaque ligne. Retourne une matrice [ligne][mois].
    """
    matrix = [[0.0] * len(targets) for _ in quantities]
    remaining = list(quantities)
    month = 0
    need = float(targets[0]) if targets else 0.0
    for idx in range(len(quantities)):
        while remaining[idx] > 1e-9:
            while month < len(targets) - 1 and need <= 1e-9:
                month += 1
                need = float(targets[month])
            take = remaining[idx] if month == len(targets) - 1 else min(remaining[idx], need)
            matrix[idx][month] += take
            remaining[idx] -= take
            need -= take
    return matrix


def _shift_to_month(date_value, month_key):
    """Même jour et même heure dans le mois `month_key` (jour ramené à la fin du mois si nécessaire)."""
    start = _month_start(month_key)
    if start is None or not isinstance(date_value, datetime):
        return date_value
    last_day = (_add_months(start, 1) - dt_module.timedelta(days=1)).day
    return date_value.replace(year=start.year, month=start.month, day=min(date_value.day, last_day))


def _is_history_import_row(row):
    date_value = row.get("date")
    if not isinstance(date_value, datetime) or str(row.get("month")) != HISTORY_IMPORT_MONTH:
        return False
    return not HISTORY_IMPORT_LAST_DAY or date_value.strftime("%Y-%m-%d") <= HISTORY_IMPORT_LAST_DAY


def _spread_history_import(all_sales):
    """Répartit les ventes de l'historique saisi en mars sur janvier, février et mars (parts égales).

    - CA, coût, bénéfice : 1/n par mois (le dernier mois reçoit le solde, la somme reste exacte) ;
    - cartes vendues et nombre de transactions : entiers, reste distribué en commençant par le premier mois ;
    - chaque ligne garde son lot, son canal et ses autres attributs : seuls le mois, la date et les montants changent ;
    - les ventes postérieures à HISTORY_IMPORT_LAST_DAY (vraies ventes de mars) ne sont pas touchées.
    Les totaux de l'année sont inchangés. Retourne une nouvelle liste, `all_sales` n'est pas modifiée.
    """
    months = _history_spread_months()
    count = len(months)
    if count < 2:
        return list(all_sales)
    import_idx = [idx for idx, row in enumerate(all_sales) if _is_history_import_row(row)]
    if not import_idx:
        return list(all_sales)
    rows = [all_sales[idx] for idx in import_idx]

    # Quantités entières : une réserve pour les cartes physiques, une pour le reste (hors stock, ventes initiales).
    allocation = {}
    for physical in (True, False):
        pool = [pos for pos, row in enumerate(rows) if (_physical_sale_quantity(row) > 0) == physical]
        quantities = [_safe_float(rows[pos].get("quantity")) for pos in pool]
        total = sum(quantities)
        whole = int(total + 1e-9)
        targets = _split_integer(whole, count)
        targets[-1] += total - whole
        for pos, line in zip(pool, _allocate_quantities(quantities, targets)):
            allocation[pos] = line

    # Transactions : T_k clés distinctes par mois, somme = T.
    keys = []
    for idx in import_idx:
        if not _is_transaction_row(all_sales[idx]):
            continue  # une vente initiale n'est pas une transaction
        key = _transaction_key(all_sales[idx], idx)
        if key not in keys:
            keys.append(key)
    tx_targets = _split_integer(len(keys), count)  # peut valoir 0 pour un mois s'il y a moins de transactions que de mois
    key_position = {key: pos for pos, key in enumerate(keys)}

    def shares(value):
        if value is None:
            return [None] * count
        part = value / count
        return [part] * (count - 1) + [value - part * (count - 1)]

    spread_by_index = {}
    for pos, idx in enumerate(import_idx):
        row = all_sales[idx]
        money = {name: shares(row.get(name)) for name in ("price", "cost", "benef", "cote")}
        copies = []
        for k, month in enumerate(months):
            copy = dict(row)
            copy.update({
                "month": month, "date": _shift_to_month(row["date"], month), "quantity": allocation[pos][k],
                "price": money["price"][k], "cost": money["cost"][k], "benef": money["benef"][k], "cote": money["cote"][k],
                "history_estimated": True,
            })
            if _is_transaction_row(row):
                if tx_targets[k] > 0:
                    copy["_tx_key"] = f"history-import-{month}-{key_position[_transaction_key(row, idx)] % tx_targets[k]}"
                else:
                    copy["_no_transaction"] = True
            copies.append(copy)
        spread_by_index[idx] = copies

    result = []
    for idx, row in enumerate(all_sales):
        result.extend(spread_by_index.get(idx, [row]))
    return result


def _build_monthly_stats(all_sales, purchases):
    stats = defaultdict(lambda: {"ca": 0.0, "benef": 0.0, "benef_known": True, "qty": 0.0, "transactions": set(), "purchases": 0.0})
    for idx, row in enumerate(all_sales):
        item = stats[row["month"]]
        item["ca"] += _safe_float(row.get("price"))
        if row.get("benef") is None:
            item["benef_known"] = False
        else:
            item["benef"] += _safe_float(row.get("benef"))
        item["qty"] += _physical_sale_quantity(row)
        if _is_transaction_row(row):
            item["transactions"].add(_transaction_key(row, idx))
    for row in purchases:
        stats[row["month"]]["purchases"] += _safe_float(row.get("cost"))
    return stats


def _aggregate_sales(rows):
    transactions = {_transaction_key(row, idx) for idx, row in enumerate(rows) if _is_transaction_row(row)}
    ca = sum(_safe_float(row.get("price")) for row in rows)
    basket_ca = sum(_safe_float(row.get("price")) for row in rows if not row.get("is_lot_sale"))  # CA hors ventes initiales
    known_benef = [row.get("benef") for row in rows if row.get("benef") is not None]
    benef = sum(_safe_float(value) for value in known_benef) if known_benef else None
    qty = sum(_physical_sale_quantity(row) for row in rows)
    card_ca = sum(_safe_float(row.get("price")) for row in rows if _is_card_sale(row))
    return {
        "ca": ca,
        "benef": benef,
        "qty": qty,
        "transactions": len(transactions),
        "basket": basket_ca / len(transactions) if transactions else 0.0,  # ventes initiales exclues (pas des transactions)
        "avg_card": card_ca / qty if qty else 0.0,
        "margin": (benef / ca * 100.0) if benef is not None and ca else None,
    }


def _month_profile(month, monthly_stats, months_sorted):
    current = monthly_stats.get(month)
    if not current:
        return None
    if "_profile_result" in current:
        return profile_tuple(current["_profile_result"])
    current_month = max(months_sorted) if months_sorted else None
    if month in annual_record_months(monthly_stats, current_month):
        return profile_tuple({"id": "record"})
    historic = [monthly_stats[m] for m in months_sorted if m != month]
    return profile_tuple(score_profile(current, historic))


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
        .ps-stats-v3{font-family:"Plus Jakarta Sans",sans-serif;color:#111827}
        .ps-stats-v3 *{box-sizing:border-box}
        .ps-stats-hero-v3{position:relative;display:grid;grid-template-columns:minmax(0,1.45fr) minmax(300px,.85fr);gap:1rem;overflow:hidden;border:1px solid #2E1573;border-radius:24px;padding:1.05rem;background:#3B1D8F;box-shadow:0 16px 36px rgba(17,24,39,.18);margin:.05rem 0 .78rem;color:#fff}
        .ps-stats-hero-v3>div{position:relative;z-index:1}
        .ps-stats-month-eyebrow{color:#FFFFFF;font-size:.72rem;font-weight:950;letter-spacing:.14em;text-transform:uppercase}
        .ps-stats-month-title{font-size:clamp(2.25rem,5vw,4.7rem);line-height:.88;font-weight:950;letter-spacing:0;margin:.16rem 0 .35rem;color:#FFFFFF}
        .ps-stats-profile-label{font:inherit}
        .ps-stats-profile-help{position:relative;display:inline-block;margin-left:.35rem;color:#64748b;font-weight:400}
        .ps-stats-profile-help summary{display:flex;align-items:center;justify-content:center;list-style:none;border:1px solid currentColor;border-radius:50%;width:22px;height:22px;font-size:12px;cursor:pointer}
        .ps-stats-profile-help summary::-webkit-details-marker{display:none}
        .ps-stats-profile-help summary:focus-visible{outline:2px solid #7c3aed;outline-offset:3px}
        .ps-stats-profile-tooltip{display:none;position:absolute;z-index:20;right:-8px;top:100%;width:260px;max-width:calc(100vw - 64px);padding:14px;background:#fff;color:#111827;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 4px 12px #11182715;font-size:13px;line-height:1.5;white-space:normal}
        .ps-stats-profile-tooltip strong,.ps-stats-profile-tooltip>span{display:block}
        .ps-stats-profile-tooltip strong{margin-bottom:6px}
        .ps-stats-profile-help details[open]+.ps-stats-profile-tooltip,.ps-stats-profile-help:has(summary:focus-visible)>.ps-stats-profile-tooltip{display:block}
        @media(hover:hover){.ps-stats-profile-help:hover>.ps-stats-profile-tooltip{display:block}}
        .ps-stats-profile{display:inline-flex;align-items:center;gap:.38rem;background:#6D28D9;border:1px solid #FFFFFF;border-radius:999px;padding:.44rem .78rem;color:#FFFFFF;font-weight:950}
        .ps-stats-why{margin:.52rem 0 .78rem;color:#E5E7EB;font-size:.9rem;font-weight:780}
        .ps-stats-hero-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;margin-top:.65rem;border:1px solid rgba(255,255,255,.28);border-radius:18px;background:#2E1573;overflow:hidden}
        .ps-stats-hero-metric{padding:.74rem .78rem;min-width:0;border-right:1px solid rgba(255,255,255,.18)}
        .ps-stats-hero-metric:last-child{border-right:0}
        .ps-stats-hero-metric .label{color:#cbd5e1;font-size:.62rem;font-weight:950;text-transform:uppercase;letter-spacing:.08em}
        .ps-stats-hero-metric .value{color:#fff;font-size:clamp(1.05rem,2.2vw,1.45rem);font-weight:950;line-height:1.04;margin-top:.16rem}
        .ps-stats-hero-metric .delta{font-size:.72rem;font-weight:950;margin-top:.22rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .ps-stats-delta-up{color:#22C55E}
        .ps-stats-delta-down{color:#F97316}
        .ps-stats-delta-na{color:#CBD5E1}
        .ps-stats-card-month{position:relative;background:#FFFFFF;border:1px solid #F59E0B;border-top:5px solid #F59E0B;border-radius:22px;padding:.95rem;box-shadow:0 14px 28px rgba(17,24,39,.14);overflow:hidden;color:#111827}
        .ps-stats-card-month .tag{font-size:.7rem;font-weight:950;color:#D97706;text-transform:uppercase;letter-spacing:.09em}
        .ps-stats-card-month .sub{font-size:.76rem;color:#4B5563;font-weight:850;margin:.14rem 0 .68rem}
        .ps-stats-card-month .body{display:grid;grid-template-columns:122px minmax(0,1fr);gap:.78rem;align-items:center}
        .ps-stats-card-month .img{width:122px;aspect-ratio:.72;border-radius:16px;background:#F8FAFC;border:1px solid #D1D5DB;display:flex;align-items:center;justify-content:center;overflow:hidden;color:#64748b;font-size:.72rem;text-align:center;font-weight:850;box-shadow:0 10px 20px rgba(17,24,39,.14)}
        .ps-stats-card-month img{width:100%;height:100%;object-fit:cover;display:block}
        .ps-stats-card-month .name{font-size:1.08rem;font-weight:950;line-height:1.13;color:#111827}
        .ps-stats-card-month .number{font-size:.78rem;color:#64748b;font-weight:850;margin-top:.2rem}
        .ps-stats-card-month .price{font-size:1.65rem;color:#15803d;font-weight:950;margin-top:.48rem}
        .ps-stats-section-title{display:flex;align-items:flex-end;justify-content:space-between;gap:.75rem;margin:.82rem 0 .38rem;color:#111827;font-size:1rem;font-weight:950}
        .ps-stats-section-title span{display:inline-flex;align-items:center;gap:.45rem}
        .ps-stats-section-title span:before{content:"";width:4px;height:18px;border-radius:999px;background:#6D28D9}
        .ps-stats-chart-note{color:#475569;font-size:.82rem;font-weight:800;margin:-.1rem 0 .2rem}
        .ps-stats-timeline{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:12px 0 24px}
        .ps-stats-month-node{--profile-accent:#6D28D9;display:flex;flex-direction:column;min-width:0;background:#FFFFFF;border:1px solid #E5E7EB;border-top:3px solid var(--profile-accent);border-radius:8px;padding:20px;transition:border-color .16s ease}
        .ps-stats-month-node:hover{border-color:var(--profile-accent)}
        .ps-stats-month-node.is-current{border-color:var(--profile-accent);border-top-width:4px}
        .ps-stats-month-node .month{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;font-size:12px;color:#64748b;font-weight:700;letter-spacing:0;text-transform:uppercase}
        .ps-stats-month-node .current-label{font-size:11px;text-transform:none;color:#475569;font-weight:500}
        .ps-stats-month-node .profile{display:flex;align-items:center;gap:8px;margin:16px 0 12px;min-width:0}
        .ps-stats-month-node .ps-stats-profile-label{display:inline-block;padding:6px 9px;border:1px solid var(--profile-accent);border-left-width:3px;border-radius:6px;font-size:14px;font-weight:700;color:#111827;line-height:1.4;overflow-wrap:anywhere}
        .ps-stats-month-node .ps-stats-profile-help{flex-shrink:0;margin:0;color:#64748b}
        .ps-stats-month-node .profile{position:relative}
        .ps-stats-month-node .ps-stats-profile-help{position:static}
        .ps-stats-month-node .ps-stats-profile-tooltip{left:0;right:auto;max-width:100%;box-sizing:border-box}
        .ps-stats-month-node .money{display:grid;gap:6px;margin-top:auto;padding-top:14px;border-top:1px solid #F1F5F9;font-size:13px;color:#64748b;line-height:1.4}
        .ps-stats-month-node .money strong{color:#334155;font-weight:600;font-variant-numeric:tabular-nums}
        .ps-stats-goals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.55rem}
        .ps-stats-goal-card{--goal-accent:#6D28D9;background:#FFFFFF;border:1px solid #D1D5DB;border-top:5px solid var(--goal-accent);border-radius:17px;padding:.78rem .76rem;box-shadow:0 10px 22px rgba(17,24,39,.06);transition:transform .16s ease,box-shadow .16s ease}
        .ps-stats-goal-card:hover{transform:translateY(-2px);box-shadow:0 14px 26px rgba(17,24,39,.10)}
        .ps-stats-goal-top{display:flex;align-items:center;justify-content:space-between;gap:.5rem;margin-bottom:.42rem}
        .ps-stats-goal-name{font-size:.78rem;font-weight:950;color:#1e293b;text-transform:uppercase;letter-spacing:.04em}
        .ps-stats-goal-icon{width:32px;height:32px;border-radius:12px;display:flex;align-items:center;justify-content:center;background:var(--goal-accent);color:#FFFFFF;font-size:1rem}
        .ps-stats-goal-value{font-size:1rem;font-weight:950;color:#111827}
        .ps-stats-goal-pct{font-size:.78rem;font-weight:950;color:var(--goal-accent);margin:.16rem 0 .4rem}
        .ps-stats-progress{height:10px;border-radius:999px;background:#e2e8f0;overflow:hidden}
        .ps-stats-progress span{display:block;height:100%;border-radius:999px;background:var(--goal-accent)}
        .ps-stats-progress.done span{background:#16A34A}
        .ps-stats-goal-done{font-size:.73rem;font-weight:950;color:#15803d;margin-top:.36rem}
        .ps-stats-record-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.55rem}
        .ps-stats-record{--record-accent:#F59E0B;background:#FFFFFF;border:1px solid #D1D5DB;border-top:5px solid var(--record-accent);border-radius:17px;padding:.76rem .78rem;box-shadow:0 10px 22px rgba(17,24,39,.06);transition:transform .16s ease,box-shadow .16s ease}
        .ps-stats-record:hover{transform:translateY(-2px);box-shadow:0 14px 26px rgba(17,24,39,.10)}
        .ps-stats-record .icon{font-size:1.15rem;margin-bottom:.28rem;color:var(--record-accent)}
        .ps-stats-record .label{font-size:.66rem;color:#64748b;font-weight:950;text-transform:uppercase;letter-spacing:.055em}
        .ps-stats-record .value{font-size:1.05rem;color:#111827;font-weight:950;margin-top:.28rem;line-height:1.12}
        .ps-stats-record .detail{font-size:.74rem;color:#64748b;font-weight:790;margin-top:.22rem;line-height:1.18}
        .ps-stats-history-line{margin:.5rem 0 0;color:#475569;font-weight:850;font-size:.84rem}
        div[class*="st-key-stats_goal_edit_toggle"] button,div[class*="st-key-stats_save_goals"] button{border-radius:999px!important;font-weight:900!important;padding:.36rem .72rem!important;min-height:2rem!important}
        @media (max-width:980px){.ps-stats-hero-v3{grid-template-columns:1fr}.ps-stats-hero-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.ps-stats-hero-metric:nth-child(2){border-right:0}.ps-stats-timeline{grid-template-columns:repeat(2,minmax(0,1fr))}.ps-stats-goals{grid-template-columns:repeat(3,minmax(0,1fr))}.ps-stats-record-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media (max-width:768px){.ps-stats-hero-v3{padding:.85rem;border-radius:18px}.ps-stats-hero-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.ps-stats-hero-metric{padding:.66rem}.ps-stats-hero-metric:nth-child(odd){border-right:1px solid rgba(255,255,255,.12)}.ps-stats-hero-metric:nth-child(even){border-right:0}.ps-stats-card-month .body{grid-template-columns:96px minmax(0,1fr)}.ps-stats-card-month .img{width:96px}.ps-stats-timeline{grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.ps-stats-goals{grid-template-columns:1fr}.ps-stats-record-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.ps-stats-history-line{width:100%;line-height:1.35}}
        @media (max-width:540px){.ps-stats-timeline{grid-template-columns:minmax(0,1fr)}.ps-stats-month-node{padding:18px}}
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
        current_profile = _fallback_current_profile(metrics)
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
    labels = [_month_label_est(m) for m in months]
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
        item["qty"] += _physical_sale_quantity(row)
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
        channel = _row_channel(row)
        item = channel_rows.setdefault(channel, {"channel": channel, "ca": 0.0, "basket_ca": 0.0, "card_ca": 0.0, "benef": 0.0, "benef_known": True, "qty": 0.0, "transactions": set()})
        item["ca"] += _safe_float(row.get("price"))
        item["qty"] += _physical_sale_quantity(row)
        if _is_card_sale(row):
            item["card_ca"] += _safe_float(row.get("price"))
        if not row.get("is_lot_sale"):
            item["basket_ca"] += _safe_float(row.get("price"))
        if _is_transaction_row(row):
            item["transactions"].add(_transaction_key(row, len(item["transactions"])))
        if row.get("benef") is None:
            item["benef_known"] = False
        else:
            item["benef"] += _safe_float(row.get("benef"))
    for item in channel_rows.values():
        item["sales"] = len(item["transactions"])
        item["margin"] = (item["benef"] / item["ca"] * 100.0) if item["ca"] and item["benef_known"] else None
        item["basket"] = item["basket_ca"] / item["sales"] if item["sales"] else 0.0
        item["avg_card"] = item["card_ca"] / item["qty"] if item["qty"] else 0.0
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
    st.markdown(f'<div class="ps-stats-card"><div style="display:flex;justify-content:space-between;gap:.7rem;align-items:center;"><span style="font-weight:850;color:#1e293b;">{icon} {html.escape(label)}</span><span style="font-weight:900;color:{bar_color};">{html.escape(status)}</span></div><div style="background:#f1f5f9;border-radius:99px;height:12px;overflow:hidden;margin-top:.65rem;"><div style="height:100%;width:{pct:.1f}%;background:{bar_color};border-radius:99px;"></div></div><div style="margin-top:.45rem;font-size:.8rem;color:#64748b;">{html.escape(msg)}</div></div>', unsafe_allow_html=True)


def _render_records_view(all_sales, monthly_stats, months_sorted, current_month, monthly_goals_path, safe_write_json_func):
    total = _aggregate_sales(all_sales)
    best_ca = max(months_sorted, key=lambda m: monthly_stats[m]["ca"]) if months_sorted else None
    best_benef = max(months_sorted, key=lambda m: monthly_stats[m]["benef"]) if months_sorted else None
    best_qty = max(months_sorted, key=lambda m: monthly_stats[m]["qty"]) if months_sorted else None
    transactions = defaultdict(lambda: {"price": 0.0, "date": None, "label": ""})
    for idx, row in enumerate(all_sales):
        if not _is_transaction_row(row) or row.get("history_estimated"):
            continue  # ni vente initiale ni part estimée d'historique réparti
        key = _transaction_key(row, idx)
        transactions[key]["price"] += _safe_float(row.get("price"))
        transactions[key]["date"] = row.get("date")
        label = row.get("card_name") or "Vente"
        transactions[key]["label"] = label if not transactions[key]["label"] else transactions[key]["label"] + ", " + label
    biggest_tx = max(transactions.values(), key=lambda row: row["price"]) if transactions else None
    records = [
        ("Meilleur mois CA", _month_label_est(best_ca) if best_ca else "N/A", _fmt_eur(monthly_stats[best_ca]["ca"]) if best_ca else ""),
        ("Meilleur mois bénéfice", _month_label_est(best_benef) if best_benef else "N/A", _fmt_eur(monthly_stats[best_benef]["benef"]) if best_benef else ""),
        ("Record de cartes vendues", _month_label_est(best_qty) if best_qty else "N/A", f"{monthly_stats[best_qty]['qty']:.0f} cartes" if best_qty else ""),
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


def _month_metrics(all_sales, monthly_stats, month):
    rows = [row for row in all_sales if row.get("month") == month]
    if rows:
        return _aggregate_sales(rows)
    stat = monthly_stats.get(month, _blank_month_stats())
    ca = _safe_float(stat.get("ca"))
    benef = _safe_float(stat.get("benef")) if stat.get("benef_known", True) else None
    return {
        "ca": ca,
        "benef": benef,
        "qty": _safe_float(stat.get("qty")),
        "transactions": len(stat.get("transactions", set()) or []),
        "basket": 0.0,
        "avg_card": 0.0,
        "margin": (benef / ca * 100.0) if benef is not None and ca else None,
    }


def _fallback_current_profile(metrics):
    return "Profil non établi", "L’historique comparable ne permet pas encore de dégager une tendance distinctive."


def _metric_delta_html(current, previous, *, unit=""):
    if current is None or previous is None:
        return '<span class="ps-stats-delta-na">Marge non comparable</span>' if unit == "pts" else '<span class="ps-stats-delta-na">N/A</span>'
    difference = current - previous
    css_class = "ps-stats-delta-up" if difference > 0 else "ps-stats-delta-down" if difference < 0 else "ps-stats-delta-na"
    if unit == "pts":
        return f'<span class="{css_class}">{difference:+.1f} pts</span>'.replace(".", ",")
    if previous == 0:
        value = f"{difference:+.2f} €" if unit == "€" else f"{difference:+g}"
        return f'<span class="{css_class}">{value} · base 0</span>'.replace(".", ",")
    pct = _pct_change(current, previous)
    if pct is None:
        return '<span class="ps-stats-delta-na">N/A</span>'
    sign = "+" if pct >= 0 else ""
    return f'<span class="{css_class}">{sign}{pct:.1f}%</span>'.replace(".", ",")


def _hero_metric(label, value, delta):
    return (
        '<div class="ps-stats-hero-metric">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(str(value))}</div>'
        f'<div class="delta">{delta or "N/A"}</div>'
        '</div>'
    )


def _best_card_of_month(rows):
    candidates = []
    for row in rows:
        if not _is_card_sale(row):
            continue
        name = str(row.get("card_name") or "").strip()
        if not name or name.lower() in {"vente lot", "vente"}:
            continue
        qty = max(_safe_float(row.get("quantity"), 1), 1.0)
        unit_price = _safe_float(row.get("unit_price")) or (_safe_float(row.get("price")) / qty if qty else 0.0)
        if unit_price <= 0:
            continue
        candidates.append((unit_price, row))
    if not candidates:
        return None
    price, row = max(candidates, key=lambda item: item[0])
    return {
        "price": price,
        "name": row.get("card_name") or "Carte",
        "number": row.get("card_number") or "",
        "image": row.get("card_image") or "",
    }


def _card_month_html(card, current_month, proxy_img_func):
    if not card:
        img_html = '<div class="img">Image<br>absente</div>'
        name = "Aucune carte vendue"
        number = "Pas encore de vente individuelle ce mois-ci"
        price = "N/A"
    else:
        raw_img = str(card.get("image") or "").strip()
        if raw_img and raw_img != "__placeholder__":
            try:
                raw_img = proxy_img_func(raw_img)
            except Exception:
                pass
            img_html = f'<div class="img"><img src="{html.escape(raw_img, quote=True)}" loading="lazy" decoding="async" alt=""></div>'
        else:
            img_html = '<div class="img">Image<br>absente</div>'
        name = str(card.get("name") or "Carte")
        number = f"#{card.get('number')}" if card.get("number") else "Numéro N/A"
        price = _fmt_eur(card.get("price"))
    return (
        '<div class="ps-stats-card-month">'
        '<div class="tag">⭐ Carte du mois</div>'
        '<div class="sub">Plus grosse carte vendue ce mois</div>'
        '<div class="body">'
        f'{img_html}'
        '<div>'
        f'<div class="name">{html.escape(name)}</div>'
        f'<div class="number">{html.escape(str(number))}</div>'
        f'<div class="price">{html.escape(price)}</div>'
        '</div></div></div>'
    )


def _profile_accent(label):
    return next((meta["color"] for meta in PROFILE_METADATA.values()
                 if label == f'{meta["emoji"]} {meta["name"]}'), "#64748b")


def _render_stats_v3_hero(all_sales, monthly_stats, months_sorted, current_month, proxy_img_func, *, now=None, profile_stats=None):
    now = now or datetime.now()
    current_rows = [row for row in all_sales if row.get("month") == current_month]
    metrics, prev, is_mtd = _comparable_month_metrics(all_sales, current_month, now=now)
    profile = _month_profile(current_month, profile_stats if profile_stats is not None else monthly_stats, months_sorted) or _fallback_current_profile(metrics)
    best_card = _best_card_of_month(current_rows)
    comparison_suffix = " vs même période le mois dernier" if is_mtd else " vs mois précédent"
    hero_metrics = [
        _hero_metric("CA", _fmt_eur(metrics["ca"]), _metric_delta_html(metrics["ca"], prev["ca"], unit="€") if prev else None),
        _hero_metric("Bénéfice", _fmt_eur(metrics["benef"]), _metric_delta_html(metrics["benef"], prev["benef"], unit="€") if prev and metrics["benef"] is not None and prev["benef"] is not None else None),
        _hero_metric("Marge", _fmt_pct(metrics["margin"]), _metric_delta_html(metrics["margin"], prev["margin"], unit="pts") if prev else None),
        _hero_metric("Cartes vendues", f"{metrics['qty']:.0f}", _metric_delta_html(metrics["qty"], prev["qty"]) if prev else None),
    ]
    st.markdown(
        '<div class="ps-stats-v3">'
        '<div class="ps-stats-hero-v3">'
        '<div>'
        '<div class="ps-stats-month-eyebrow">Bilan mensuel</div>'
        f'<div class="ps-stats-month-title">{html.escape(_month_label(current_month).upper())}</div>'
        f'<div class="ps-stats-profile">{_profile_help_html(profile[0], explanation=profile[1])}</div>'
        f'<div class="ps-stats-why">{comparison_suffix}</div>'
        f'<div class="ps-stats-hero-metrics">{"".join(hero_metrics)}</div>'
        '</div>'
        f'{_card_month_html(best_card, current_month, proxy_img_func)}'
        '</div></div>',
        unsafe_allow_html=True,
    )
    return metrics


def _chart_sentence(current_month, monthly_stats, months, *, all_sales=None, now=None):
    if current_month not in monthly_stats or len(months) < 2:
        return ""
    current = monthly_stats.get(current_month, _blank_month_stats())
    current_start = _month_start(current_month) or datetime.now().replace(day=1)
    prev_month = _add_months(current_start, -1).strftime("%Y-%m")
    if prev_month not in monthly_stats:
        return ""
    prev = monthly_stats[prev_month]
    best_month = max(months, key=lambda m: monthly_stats.get(m, _blank_month_stats()).get("ca", 0))
    if all_sales is not None:
        current, prev, is_mtd = _comparable_month_metrics(all_sales, current_month, now=now)
    else:
        is_mtd = False
    ca = _safe_float(current.get("ca"))
    prev_ca = _safe_float(prev.get("ca"))
    if is_mtd:
        label = _month_label(current_month).split()[0]
        if prev_ca == 0:
            return f"{label} : {_fmt_eur(ca)} contre 0 € à la même date le mois précédent." if ca else ""
        change = _pct_change(ca, prev_ca)
        return f"{label} : {change:+.1f} % de CA à période équivalente.".replace(".", ",")
    if ca <= 0 or prev_ca <= 0:
        return ""
    current_label = _month_label(current_month).split()[0]
    prev_label = _month_label(prev_month).split()[0].lower()
    if ca > prev_ca and best_month != current_month:
        return f"{current_label} repart après {prev_label}, mais reste sous le record de {_month_label(best_month).split()[0].lower()}."
    if ca > prev_ca:
        return f"{current_label} progresse par rapport à {prev_label}."
    if ca < prev_ca:
        return f"{current_label} ralentit par rapport à {prev_label}."
    return ""


def _render_stats_v3_chart(monthly_stats, months_sorted, current_month, *, all_sales=None, now=None, profile_stats=None):
    months = sorted(set(months_sorted + [current_month]))[-12:]
    labels = [_month_label_est(m) for m in months]
    ca_values = [_safe_float(monthly_stats.get(m, _blank_month_stats()).get("ca")) for m in months]
    benef_values = [_safe_float(monthly_stats.get(m, _blank_month_stats()).get("benef")) for m in months]
    qty_values = [_safe_float(monthly_stats.get(m, _blank_month_stats()).get("qty")) for m in months]
    profiles = [_month_profile(m, monthly_stats, months_sorted) for m in months]
    if profile_stats is not None:
        profiles = [_month_profile(m, profile_stats, months_sorted) for m in months]
    custom = [[ca_values[idx], benef_values[idx], (benef_values[idx] / ca_values[idx] * 100.0) if ca_values[idx] else 0.0, qty_values[idx], profiles[idx][0] if profiles[idx] else "N/A"] for idx in range(len(months))]
    note = _chart_sentence(current_month, monthly_stats, months, all_sales=all_sales, now=now)
    note_html = f'<div class="ps-stats-chart-note">{html.escape(note)}</div>' if note else ""
    st.markdown(f'<div class="ps-stats-section-title"><span>Évolution</span></div>{note_html}', unsafe_allow_html=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=labels, y=ca_values, mode="lines+markers", name="CA", line=dict(color="#6d5dfc", width=3), marker=dict(size=7), customdata=custom, hovertemplate="%{x}<br>CA : %{y:.2f}€<br>Bénéfice : %{customdata[1]:.2f}€<br>Marge : %{customdata[2]:.1f}%<br>Cartes : %{customdata[3]:.0f}<br>%{customdata[4]}<extra></extra>"))
    fig.add_trace(go.Scatter(x=labels, y=benef_values, mode="lines+markers", name="Bénéfice", line=dict(color="#16a34a", width=3), marker=dict(size=7), customdata=custom, hovertemplate="%{x}<br>Bénéfice : %{y:.2f}€<br>CA : %{customdata[0]:.2f}€<br>Marge : %{customdata[2]:.1f}%<br>Cartes : %{customdata[3]:.0f}<br>%{customdata[4]}<extra></extra>"))
    # Marge haute pour la légende (alignée à gauche : jamais tronquée) et marge basse + angle pour les libellés de mois.
    fig.update_layout(height=320, margin=dict(t=30, b=90, l=2, r=8), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(family="Plus Jakarta Sans", color="#0f172a", size=10), yaxis=dict(title="", gridcolor="rgba(148,163,184,.18)", zerolinecolor="rgba(148,163,184,.24)", ticksuffix="€"), xaxis=dict(showgrid=False, tickangle=-35, automargin=True), legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=10)))
    st.plotly_chart(fig, width="stretch", key="stats_v3_ca_benef_chart", config={"displayModeBar": False, "responsive": True})
    if _any_estimated(months):
        st.markdown(_estimated_note_html(months), unsafe_allow_html=True)


def _render_stats_v3_timeline(monthly_stats, months_sorted, current_month, *, profile_stats=None):
    months = sorted(set(months_sorted + [current_month]))[-12:]
    nodes = []
    for month in months:
        profile = _month_profile(month, profile_stats if profile_stats is not None else monthly_stats, months_sorted)
        if not profile:
            profile = _fallback_current_profile(_month_metrics([], monthly_stats, month))
        stat = monthly_stats.get(month, _blank_month_stats())
        month_label = _month_label_est(month)
        accent = _profile_accent(profile[0])
        current_class = " is-current" if month == current_month else ""
        current_label = '<span class="current-label">En cours</span>' if month == current_month else ""
        nodes.append(
            f'<div class="ps-stats-month-node{current_class}" style="--profile-accent:{accent};">'
            f'<div class="month"><span>{html.escape(month_label)}</span>{current_label}</div>'
            f'<div class="profile">{_profile_help_html(profile[0], explanation=profile[1])}</div>'
            f'<div class="money"><div><strong>{_fmt_eur(stat["ca"])}</strong> CA</div>'
            f'<div><strong>{_fmt_eur(stat["benef"])}</strong> bénéfice</div></div>'
            '</div>'
        )
    if nodes:
        st.markdown('<div class="ps-stats-section-title"><span>Profil des mois</span></div><div class="ps-stats-timeline">' + "".join(nodes) + "</div>" + _estimated_note_html(months), unsafe_allow_html=True)


def _goal_row(label, current, target, unit="€", icon="🎯", accent="#6d28d9"):
    current = _safe_float(current)
    target = _safe_float(target)
    pct = min((current / target * 100.0) if target > 0 else 0.0, 100.0)
    done = pct >= 100
    current_label = _fmt_eur(current) if unit == "€" else f"{current:.0f}"
    target_label = _fmt_eur(target) if unit == "€" else f"{target:.0f}"
    status = '<div class="ps-stats-goal-done">✓ Atteint</div>' if done else ""
    return (
        f'<div class="ps-stats-goal-card" style="--goal-accent:{accent};">'
        '<div class="ps-stats-goal-top">'
        f'<div class="ps-stats-goal-icon">{html.escape(icon)}</div>'
        f'<div class="ps-stats-goal-name">{html.escape(label)}</div>'
        '</div>'
        f'<div class="ps-stats-goal-value">{html.escape(current_label)} / {html.escape(target_label)}</div>'
        f'<div class="ps-stats-goal-pct">{pct:.0f}%</div>'
        f'<div class="ps-stats-progress {"done" if done else ""}"><span style="width:{pct:.1f}%"></span></div>'
        f'{status}'
        '</div>'
    )


def _render_stats_v3_goals(monthly_stats, months_sorted, current_month, monthly_goals_path, safe_write_json_func):
    current_start = _month_start(current_month) or datetime.now().replace(day=1)
    prev_month = _add_months(current_start, -1).strftime("%Y-%m")
    goals_data, month_goals = _load_month_goals(monthly_goals_path, current_month, prev_month, monthly_stats, months_sorted, safe_write_json_func)
    current = monthly_stats.get(current_month, _blank_month_stats())
    month_name = _month_label(current_month).split()[0].lower()
    month_prefix = "d'" if month_name[:1] in "aeiouyàâéèêëîïôùûü" else "de "
    title_col, action_col = st.columns([1, 0.18], vertical_alignment="center")
    title_col.markdown(f'<div class="ps-stats-section-title"><span>Objectifs {month_prefix}{html.escape(month_name)}</span></div>', unsafe_allow_html=True)
    if action_col.button("Modifier", key="stats_goal_edit_toggle", width="stretch"):
        st.session_state["stats_goal_edit_open"] = not st.session_state.get("stats_goal_edit_open", False)
        st.rerun()
    st.markdown(
        '<div class="ps-stats-goals">'
        + _goal_row("CA", current.get("ca"), month_goals.get("ca_target"), "€", "💰", "#6d28d9")
        + _goal_row("Cartes vendues", current.get("qty"), month_goals.get("qty_target"), "", "🃏", "#0ea5e9")
        + _goal_row("Bénéfice", current.get("benef"), month_goals.get("benef_target"), "€", "💎", "#16a34a")
        + '</div>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("stats_goal_edit_open", False):
        gc1, gc2, gc3 = st.columns(3)
        new_ca_t = gc1.number_input("Objectif CA (€)", 0.0, 99999.0, value=float(month_goals.get("ca_target", 100.0)), step=10.0, key="stats_goal_ca")
        new_qty_t = gc2.number_input("Cartes à vendre", 0, 9999, value=int(month_goals.get("qty_target", 20)), step=5, key="stats_goal_qty")
        new_benef_t = gc3.number_input("Objectif bénéfice (€)", 0.0, 99999.0, value=float(month_goals.get("benef_target", 30.0)), step=10.0, key="stats_goal_benef")
        if st.button("Sauvegarder les objectifs", key="stats_save_goals"):
            goals_data[current_month] = {"ca_target": new_ca_t, "qty_target": new_qty_t, "benef_target": new_benef_t, "auto_generated": False}
            safe_write_json_func(monthly_goals_path, goals_data)
            st.session_state["stats_goal_edit_open"] = False
            st.success("Objectifs mis à jour.")
            st.rerun()


def _record_values(all_sales, monthly_stats, months_sorted):
    total = _aggregate_sales(all_sales)
    best_ca = max(months_sorted, key=lambda m: monthly_stats[m]["ca"]) if months_sorted else None
    best_benef = max(months_sorted, key=lambda m: monthly_stats[m]["benef"]) if months_sorted else None
    best_qty = max(months_sorted, key=lambda m: monthly_stats[m]["qty"]) if months_sorted else None
    transactions = defaultdict(lambda: {"price": 0.0, "label": ""})
    for idx, row in enumerate(all_sales):
        if not _is_transaction_row(row) or row.get("history_estimated"):
            continue  # ni vente initiale ni part estimée d'historique réparti
        key = _transaction_key(row, idx)
        transactions[key]["price"] += _safe_float(row.get("price"))
        label = row.get("card_name") or "Vente"
        transactions[key]["label"] = label if not transactions[key]["label"] else transactions[key]["label"] + ", " + label
    biggest_tx = max(transactions.values(), key=lambda row: row["price"]) if transactions else None
    records = [
        ("Meilleur mois CA", _month_label_est(best_ca) if best_ca else "N/A", _fmt_eur(monthly_stats[best_ca]["ca"]) if best_ca else ""),
        ("Meilleur mois bénéfice", _month_label_est(best_benef) if best_benef else "N/A", _fmt_eur(monthly_stats[best_benef]["benef"]) if best_benef else ""),
        ("Record cartes vendues", _month_label_est(best_qty) if best_qty else "N/A", f"{monthly_stats[best_qty]['qty']:.0f} cartes" if best_qty else ""),
        ("Plus grosse transaction", _fmt_eur(biggest_tx["price"]) if biggest_tx else "N/A", biggest_tx["label"][:80] if biggest_tx else ""),
    ]
    return records, total


def _render_stats_v3_records(all_sales, monthly_stats, months_sorted):
    records, total = _record_values(all_sales, monthly_stats, months_sorted)
    record_visuals = [
        ("🏆", "#f59e0b"),
        ("💎", "#16a34a"),
        ("📦", "#06b6d4"),
        ("🔥", "#ef4444"),
    ]
    cards = []
    for idx, (label, value, detail) in enumerate(records):
        icon, accent = record_visuals[idx] if idx < len(record_visuals) else ("🏆", "#f59e0b")
        cards.append(
            f'<div class="ps-stats-record" style="--record-accent:{accent};">'
            f'<div class="icon">{html.escape(icon)}</div>'
            f'<div class="label">{html.escape(label)}</div>'
            f'<div class="value">{html.escape(str(value))}</div>'
            f'<div class="detail">{html.escape(str(detail or " "))}</div>'
            '</div>'
        )
    st.markdown(
        '<div class="ps-stats-section-title"><span>🏆 Tes records</span></div>'
        f'<div class="ps-stats-record-grid">{"".join(cards)}</div>'
        '<div class="ps-stats-history-line">'
        f'{_fmt_eur(total["ca"])} de CA • {_fmt_eur(total["benef"])} de bénéfice • panier moyen {_fmt_eur(total["basket"])}'
        '</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Refonte en 3 vues : Mensuel / Performance / Prévisions
# Les fonctions de calcul ci-dessus ne sont pas modifiées : on les réutilise.
# ---------------------------------------------------------------------------

STATS_VIEWS = ("Mensuel", "Performance", "Prévisions")
STATS_VIEW_STATE_KEY = "stats_active_view"
STATS_VIEW_WIDGET_KEY = "stats_view_selector"
STATS_YEAR_STATE_KEY = "stats_perf_year_active"
STATS_YEAR_WIDGET_KEY = "stats_perf_year_selector"

STATS_SIDEBAR_DIFF_CAPTION = (
    "ℹ️ Le « Bénéfice » de la barre latérale est une trésorerie nette (CA − prix d'achat de tous les lots, "
    "stock invendu inclus). Ici, le bénéfice est réalisé : seules les ventes comptent, avec leur part du coût d'achat."
)
ANNUAL_GOALS_KEY = "annual_goals"
LONG_TERM_GOAL_KEY = "long_term_goal"
DEFAULT_LONG_TERM_MONTHLY_BENEF = 1500.0
ROLLING_WINDOW_MONTHS = 12
PROJECTION_MIN_MONTHS = 6

MONTH_SHORT_FR = {1: "Janv.", 2: "Févr.", 3: "Mars", 4: "Avr.", 5: "Mai", 6: "Juin", 7: "Juil.", 8: "Août", 9: "Sept.", 10: "Oct.", 11: "Nov.", 12: "Déc."}


def _month_short_label(month_key: str) -> str:
    start = _month_start(month_key)
    if not start:
        return str(month_key)
    return f"{MONTH_SHORT_FR[start.month]} {str(start.year)[2:]}"


def _month_key_range(start_key, end_key):
    """Liste des mois 'YYYY-MM' de start_key à end_key inclus (vide si l'ordre est inversé)."""
    start = _month_start(start_key) if start_key else None
    end = _month_start(end_key) if end_key else None
    if not start or not end or start > end:
        return []
    months = []
    cursor = start
    while cursor <= end:
        months.append(cursor.strftime("%Y-%m"))
        cursor = _add_months(cursor, 1)
    return months


def _previous_month_key(now) -> str:
    return _add_months(now.replace(day=1), -1).strftime("%Y-%m")


def _first_sales_month(monthly_stats):
    """Premier mois contenant une vente (les mois d'achats seuls ne comptent pas)."""
    months = [m for m, stat in monthly_stats.items() if _safe_float(stat.get("ca")) != 0 or _safe_float(stat.get("qty")) > 0]
    return min(months) if months else None


def _rolling_average_history(monthly_stats, now, *, window=ROLLING_WINDOW_MONTHS):
    """Moyenne glissante du CA et du bénéfice, mois par mois, sur tout l'historique.

    - fenêtre de `window` mois, ou des mois disponibles tant qu'il y en a moins ;
    - les mois sans vente entre la première vente et le dernier mois complet comptent pour 0 ;
    - le mois en cours est exclu (il n'est pas terminé).
    """
    first = _first_sales_month(monthly_stats)
    last_complete = _previous_month_key(now)
    months = _month_key_range(first, last_complete) if first else []
    ca_values = [_safe_float((monthly_stats.get(m) or {}).get("ca")) for m in months]
    benef_values = [_safe_float((monthly_stats.get(m) or {}).get("benef")) for m in months]
    ca_avg, benef_avg, sizes = [], [], []
    for idx in range(len(months)):
        low = max(0, idx + 1 - window)
        size = idx + 1 - low
        ca_avg.append(sum(ca_values[low:idx + 1]) / size)
        benef_avg.append(sum(benef_values[low:idx + 1]) / size)
        sizes.append(size)
    return {
        "months": months, "ca_values": ca_values, "benef_values": benef_values,
        "ca_avg": ca_avg, "benef_avg": benef_avg, "window_sizes": sizes,
        "window": window, "excluded_month": now.strftime("%Y-%m"),
    }


def _year_projection(monthly_stats, year, now):
    """Projection de fin d'année : total à ce jour + moyenne des mois complets × mois restants."""
    year = int(year)
    fields = ("ca", "benef", "qty")
    prefix = f"{year}-"
    current_key = now.strftime("%Y-%m")
    if year > now.year:
        return None
    if year < now.year:
        totals = {f: sum(_safe_float(s.get(f)) for m, s in monthly_stats.items() if m.startswith(prefix)) for f in fields}
        return {"status": "complete", "year": year, "to_date": totals, "projected": dict(totals), "avg": {}, "complete_months": 12, "remaining_months": 0, "indicative": False}
    to_date = {f: sum(_safe_float(s.get(f)) for m, s in monthly_stats.items() if m.startswith(prefix) and m <= current_key) for f in fields}
    first = _first_sales_month(monthly_stats)
    start = max(f"{year}-01", first) if first else None
    complete = [m for m in _month_key_range(start, _previous_month_key(now)) if m.startswith(prefix)] if start else []
    avg = {f: (sum(_safe_float((monthly_stats.get(m) or {}).get(f)) for m in complete) / len(complete)) if complete else 0.0 for f in fields}
    remaining = 12 - now.month
    projected = {f: to_date[f] + avg[f] * remaining for f in fields}
    return {
        "status": "projection", "year": year, "to_date": to_date, "projected": projected, "avg": avg,
        "complete_months": len(complete), "remaining_months": remaining,
        "indicative": len(complete) < PROJECTION_MIN_MONTHS,
    }


def _long_term_status(avg_benef, target):
    """(libellé, couleur, icône, pourcentage) pour l'objectif long terme."""
    pct = (avg_benef / target * 100.0) if target and target > 0 else 0.0
    if pct >= 100:
        return "Objectif atteint", "#16a34a", "✅", pct
    if pct >= 75:
        return "Presque atteint", "#65a30d", "🟢", pct
    if pct >= 50:
        return "En bonne progression", "#d97706", "🟡", pct
    if pct >= 25:
        return "Encore du chemin", "#ea580c", "🟠", pct
    return "Encore loin de l'objectif", "#dc2626", "🔴", pct


# -- Objectif long terme : fonctions pures (trajectoire requise, paliers, séries) ------------------------------

LONG_TERM_DEFAULT_DEADLINE = dt_module.date(2028, 12, 31)
LONG_TERM_MILESTONES = (500.0, 1000.0, 1500.0, 2000.0, 3000.0)
CUMULATIVE_BENEF_MILESTONE = 10000.0
TREND_LOOKBACK_MONTHS = 3
AVG_MONTH_DAYS = 30.4375


def _long_term_deadline(goals_data):
    """Date limite de l'objectif long terme ; clé facultative « deadline » (ISO), 31/12/2028 si absente ou invalide."""
    entry = goals_data.get(LONG_TERM_GOAL_KEY) if isinstance(goals_data, dict) else None
    raw = entry.get("deadline") if isinstance(entry, dict) else None
    if not raw:
        return LONG_TERM_DEFAULT_DEADLINE
    try:
        return dt_module.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return LONG_TERM_DEFAULT_DEADLINE


def _months_remaining(now, deadline):
    """Mois restants jusqu'à la date limite (arrondi au mois le plus proche, jamais négatif)."""
    days = (deadline - now.date()).days
    return max(0, int(round(days / AVG_MONTH_DAYS)))


def _current_trend_per_month(avg_series, lookback=TREND_LOOKBACK_MONTHS):
    """Tendance actuelle : variation moyenne par mois de la moyenne glissante sur les `lookback` derniers mois."""
    count = len(avg_series)
    if count < 2:
        return 0.0
    span = min(lookback, count - 1)
    return (avg_series[-1] - avg_series[-1 - span]) / span


def _required_trajectory(avg_now, target, months_left):
    """Progression nécessaire par mois = (objectif - moyenne actuelle) / mois restants.

    `needed_per_month` vaut 0.0 si l'objectif est déjà atteint et None s'il ne reste plus de mois.
    """
    reached = avg_now >= target
    if reached:
        needed = 0.0
    elif months_left > 0:
        needed = (target - avg_now) / months_left
    else:
        needed = None
    return {"months_left": months_left, "needed_per_month": needed, "gap": max(0.0, target - avg_now), "reached": reached}


def _pace_status(avg_now, target, trend, months_left):
    """Statut de l'objectif long terme : (libellé, ton) avec ton in {"good", "warn", "bad"}.

    Règle simple : on compare la tendance actuelle (€/mois) à la progression nécessaire (€/mois).
    - objectif déjà atteint, ou tendance >= progression nécessaire  -> « Sur la bonne voie » ;
    - tendance positive et au moins la moitié de la progression nécessaire -> « À accélérer » ;
    - sinon (ou plus aucun mois restant) -> « En retard ».
    """
    needed = _required_trajectory(avg_now, target, months_left)["needed_per_month"]
    if avg_now >= target:
        return "Sur la bonne voie", "good"
    if needed is None:
        return "En retard", "bad"
    if trend >= needed:
        return "Sur la bonne voie", "good"
    if trend > 0 and trend >= needed / 2:
        return "À accélérer", "warn"
    return "En retard", "bad"


def _milestone_status(history, needed_per_month, now, milestones=LONG_TERM_MILESTONES):
    """Paliers de bénéfice moyen par mois : atteint (mois d'atteinte) ou reste à gagner (+ mois visé estimé).

    Le mois visé suppose la progression nécessaire par mois (celle de la trajectoire requise) à partir d'aujourd'hui.
    Un palier n'est « atteint » que si la moyenne glissante porte sur au moins PROJECTION_MIN_MONTHS mois complets :
    le mois d'atteinte est le premier mois où cette condition ET « moyenne >= palier » sont réunies. Avec une fenêtre
    plus courte, la carte affiche la progression normale (`provisional` si la moyenne dépasse déjà le palier).
    """
    months = history.get("months") or []
    averages = history.get("benef_avg") or []
    sizes = history.get("window_sizes") or [PROJECTION_MIN_MONTHS] * len(averages)
    avg_now = averages[-1] if averages else 0.0
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cards, next_found = [], False
    for value in milestones:
        reached_month = next((m for m, avg, size in zip(months, averages, sizes) if size >= PROJECTION_MIN_MONTHS and avg >= value), None)
        card = {"value": float(value), "reached": reached_month is not None, "reached_month": reached_month,
                "provisional": reached_month is None and avg_now >= value,
                "remaining": max(0.0, value - avg_now), "target_month": None, "is_next": False,
                "progress": max(0.0, min(avg_now / value * 100.0, 100.0)) if value > 0 else 0.0}
        if reached_month is None:
            if not next_found:
                card["is_next"], next_found = True, True
            if needed_per_month and needed_per_month > 0 and avg_now < value:
                steps = int(-(-(value - avg_now) // needed_per_month))  # arrondi au mois supérieur
                if 0 < steps <= 600:
                    card["target_month"] = _add_months(start, steps - 1).strftime("%Y-%m")  # moyenne de fin du mois visé
        cards.append(card)
    return cards


def _cumulative_benefit(monthly_stats):
    """Bénéfice réalisé cumulé depuis le début (tous les mois avec ventes)."""
    return sum(_safe_float(stat.get("benef")) for stat in monthly_stats.values())


def _consecutive_months_above_goal(monthly_stats, goals_data, now):
    """(série en cours, meilleure série) de mois complets avec bénéfice >= objectif de bénéfice du mois.

    Les mois sans objectif défini ou sans vente interrompent la série ; le mois en cours est exclu.
    """
    first = _first_sales_month(monthly_stats)
    months = _month_key_range(first, _previous_month_key(now)) if first else []
    best = current = 0
    for month in months:
        goal = goals_data.get(month) if isinstance(goals_data, dict) else None
        target = _safe_float(goal.get("benef_target")) if isinstance(goal, dict) else 0.0
        benef = _safe_float((monthly_stats.get(month) or {}).get("benef"))
        if target > 0 and benef >= target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return current, best


# -- Objectifs annuels / long terme : mêmes fichier et mécanisme d'écriture que les objectifs du mois ------------

def _read_goals_file(path):
    """(données, lisible). Un fichier absent est un fichier vide ; un fichier illisible n'est jamais écrasé."""
    if not os.path.exists(path):
        return {}, True
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}, False
    if not isinstance(data, dict):
        return {}, False
    return data, True


def _annual_goal_for_year(goals_data, year):
    block = goals_data.get(ANNUAL_GOALS_KEY)
    entry = block.get(str(year)) if isinstance(block, dict) else None
    if not isinstance(entry, dict):
        return None
    return {key: _safe_float(entry.get(key)) for key in ("ca_target", "benef_target", "qty_target")}


def _long_term_target(goals_data):
    entry = goals_data.get(LONG_TERM_GOAL_KEY)
    value = _safe_float(entry.get("monthly_benef_target"), DEFAULT_LONG_TERM_MONTHLY_BENEF) if isinstance(entry, dict) else DEFAULT_LONG_TERM_MONTHLY_BENEF
    return value if value > 0 else DEFAULT_LONG_TERM_MONTHLY_BENEF


def _save_goal_updates(path, safe_write_json_func, *, annual=None, long_term=None, long_term_deadline=None):
    """Ajoute/met à jour uniquement les clés annual_goals et long_term_goal ; le reste du fichier est conservé.

    long_term_goal garde ses autres clés ; « deadline » (ISO, facultative) n'est écrite que si elle est fournie.
    """
    data, readable = _read_goals_file(path)
    if not readable:
        return False
    if annual is not None:
        year, values = annual
        block = data.get(ANNUAL_GOALS_KEY)
        block = dict(block) if isinstance(block, dict) else {}
        block[str(year)] = {key: values[key] for key in ("ca_target", "benef_target", "qty_target")}
        data[ANNUAL_GOALS_KEY] = block
    if long_term is not None or long_term_deadline is not None:
        entry = data.get(LONG_TERM_GOAL_KEY)
        entry = dict(entry) if isinstance(entry, dict) else {}
        if long_term is not None:
            entry["monthly_benef_target"] = float(long_term)
        if long_term_deadline is not None:
            entry["deadline"] = long_term_deadline.isoformat()
        data[LONG_TERM_GOAL_KEY] = entry
    safe_write_json_func(path, data)
    return True


# -- Style des vues Performance / Prévisions (classes ps-stats-* ; widgets ciblés par clé) ------------------------

STATS_VIEWS_CSS = """
<style>
.ps-stats-title{font-size:1.55rem;font-weight:800;color:#171423;letter-spacing:-.01em;line-height:1.1;margin:-.55rem 0 .55rem}
div[class*="st-key-stats_view_selector"] [data-testid="stButtonGroup"]{gap:0!important;border-bottom:1px solid #E4E2EE}
div[class*="st-key-stats_view_selector"] button{background:transparent!important;border:0!important;border-bottom:3px solid transparent!important;border-radius:0!important;box-shadow:none!important;color:#6B6880!important;font-weight:600!important;font-size:.98rem!important;padding:.55rem .4rem!important;margin-bottom:-1px!important;flex:1 1 0!important}
div[class*="st-key-stats_view_selector"] button:hover{color:#7C3AED!important;background:transparent!important}
div[class*="st-key-stats_view_selector"] button[aria-checked="true"],div[class*="st-key-stats_view_selector"] button[kind="segmented_controlActive"],div[class*="st-key-stats_view_selector"] button[data-testid="stBaseButton-segmented_controlActive"]{color:#7C3AED!important;border-bottom-color:#7C3AED!important;font-weight:800!important}
div[class*="st-key-stats_perf_year_selector"] button{border-radius:999px!important;font-weight:700!important;font-size:.85rem!important;padding:.2rem .85rem!important;min-height:2rem!important}
.ps-stats-cap{font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#6B6880}
.ps-stats-sec{font-size:.74rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#6B6880;margin:1.25rem 0 .5rem}
.ps-stats-tile{background:#FFFFFF;border-radius:18px;border:1px solid rgba(23,20,35,.05);box-shadow:0 1px 3px rgba(23,20,35,.05),0 10px 26px rgba(23,20,35,.05);padding:1rem 1.1rem;min-width:0}
.ps-stats-big{font-size:clamp(2.25rem,4.2vw,2.75rem);font-weight:800;line-height:1.05;color:#171423;letter-spacing:-.02em;margin:.3rem 0 .2rem;overflow-wrap:anywhere}
.ps-stats-big.is-accent{color:#7C3AED}
.ps-stats-big.is-green{color:#12B886}
.ps-stats-sub{font-size:.82rem;color:#6B6880;font-weight:500;line-height:1.35}
.ps-stats-sub b{color:#171423;font-weight:700}
.ps-stats-pf-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}
.ps-stats-pf-kpis+.ps-stats-line{margin-bottom:1rem}
.ps-stats-line{color:#6B6880;font-size:.84rem;margin:.65rem .1rem 0}
.ps-stats-line b{color:#171423}
div[class*="st-key-ps_stats_chart_card"],div[class*="st-key-ps_stats_donut_card"]{background:#FFFFFF;border-radius:18px;border:1px solid rgba(23,20,35,.05);box-shadow:0 1px 3px rgba(23,20,35,.05),0 10px 26px rgba(23,20,35,.05);padding:1rem 1.1rem .4rem}
.ps-stats-card-head{display:flex;justify-content:space-between;align-items:baseline;gap:.6rem;flex-wrap:wrap}
.ps-stats-best{font-size:.8rem;color:#6B6880}
.ps-stats-best b{color:#7C3AED;font-weight:700}
.ps-stats-pf-bottom{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem;margin-top:1rem}
.ps-stats-toplot{margin-top:.65rem}
.ps-stats-toplot .row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.15rem .6rem;margin-bottom:.7rem}
.ps-stats-toplot .name{font-size:.88rem;font-weight:600;color:#171423;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ps-stats-toplot .val{font-size:.88rem;font-weight:700;color:#12B886}
.ps-stats-toplot .val.is-neutral{color:#171423}
.ps-stats-big small{font-size:.95rem;font-weight:700;color:#6B6880;letter-spacing:0}
.ps-stats-rotation,.ps-stats-payback{display:flex;flex-direction:column}
.ps-stats-detail{margin-top:auto;padding-top:.9rem}
.ps-stats-scale{margin:1.1rem .3rem .3rem}
.ps-stats-scale .track{position:relative;height:8px;border-radius:999px;background:#EEEDF5}
.ps-stats-scale .track i{position:absolute;top:-6px;width:4px;height:20px;margin-left:-2px;border-radius:2px;background:#7C3AED}
.ps-stats-scale .ticks{display:flex;justify-content:space-between;margin-top:.5rem;font-size:.72rem;font-weight:600;color:#6B6880}
.ps-stats-toplot .bar{grid-column:1/-1}
.ps-stats-bar{position:relative;height:8px;border-radius:999px;background:#EEEDF5;overflow:hidden}
.ps-stats-bar>span{position:absolute;left:0;top:0;bottom:0;border-radius:999px;background:#7C3AED}
.ps-stats-bar>span.ghost{background:#DDD3FB}
.ps-stats-bar.is-green>span{background:#12B886}
.ps-stats-bar.is-orange>span{background:#F5A524}
.ps-stats-reimb .fig{font-size:2.1rem;font-weight:800;color:#171423;line-height:1.1;margin:.3rem 0 .5rem}
.ps-stats-reimb .fig small{font-size:.95rem;color:#6B6880;font-weight:600}
.ps-stats-reimb .foot{margin-top:.65rem;font-size:.84rem;color:#6B6880}
.ps-stats-reimb .foot b{color:#171423}
.ps-stats-empty{color:#6B6880;font-size:.88rem;padding:.6rem 0}
div[class*="st-key-ps_stats_banner"]{background:linear-gradient(135deg,#1B1038 0%,#3B1D8F 55%,#7C3AED 100%);border-radius:22px;padding:1.3rem 1.4rem .9rem;color:#FFFFFF;box-shadow:0 18px 40px rgba(59,29,143,.28)}
.ps-stats-bn-head{display:flex;justify-content:space-between;align-items:flex-start;gap:.8rem;flex-wrap:wrap}
.ps-stats-bn-cap{font-size:.74rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:rgba(255,255,255,.72)}
.ps-stats-bn-title{font-size:clamp(1.55rem,3.2vw,2.3rem);font-weight:800;line-height:1.1;margin-top:.3rem;color:#FFFFFF;letter-spacing:-.015em}
.ps-stats-pill{display:inline-flex;align-items:center;gap:.45rem;border-radius:999px;padding:.4rem .95rem;font-size:.86rem;font-weight:700;border:1px solid transparent;white-space:nowrap}
.ps-stats-pill:before{content:"";width:9px;height:9px;border-radius:50%;background:currentColor}
.ps-stats-pill.is-good{background:rgba(18,184,134,.2);color:#5EEAC0;border-color:rgba(18,184,134,.5)}
.ps-stats-pill.is-warn{background:rgba(245,165,36,.2);color:#FFC766;border-color:rgba(245,165,36,.5)}
.ps-stats-pill.is-bad{background:rgba(239,68,68,.2);color:#FF9A9A;border-color:rgba(239,68,68,.5)}
.ps-stats-bn-figs{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.8rem 1rem;margin:1.1rem 0 .4rem}
.ps-stats-bn-fig .l{font-size:.68rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:rgba(255,255,255,.66)}
.ps-stats-bn-fig .v{font-size:clamp(1.25rem,2.2vw,1.65rem);font-weight:800;color:#FFFFFF;margin-top:.2rem;line-height:1.1;overflow-wrap:anywhere}
.ps-stats-bn-fig .s{font-size:.74rem;color:rgba(255,255,255,.62);margin-top:.15rem}
.ps-stats-bn-note{font-size:.76rem;color:rgba(255,255,255,.66);margin:.2rem 0 .3rem;line-height:1.4}
.ps-stats-est-note{font-size:.76rem;color:#6B6880;margin:.35rem 0 .2rem;line-height:1.4}
.ps-stats-mile-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr)) minmax(0,1.7fr);gap:.8rem}
.ps-stats-mile{padding:.85rem .9rem}
.ps-stats-mile.is-next{border:1.5px solid #7C3AED;box-shadow:0 10px 26px rgba(124,58,237,.14)}
.ps-stats-mile .main{font-size:1.15rem;font-weight:800;color:#171423;margin:.35rem 0 .1rem;line-height:1.15}
.ps-stats-mile.is-reached .main{color:#12B886}
.ps-stats-mile .bar{margin-top:.6rem}
.ps-stats-yearend .vals{display:flex;gap:1.1rem;flex-wrap:wrap;margin-top:.35rem}
.ps-stats-yearend .vals .v{font-size:1.5rem;font-weight:800;color:#171423;line-height:1.1}
.ps-stats-yearend .vals .l{font-size:.72rem;color:#6B6880;font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.ps-stats-flag{display:inline-block;margin-top:.5rem;font-size:.72rem;font-weight:700;color:#B45309;background:#FEF3C7;border-radius:999px;padding:.12rem .6rem}
.ps-stats-goal .top{display:flex;justify-content:space-between;align-items:baseline;gap:.5rem}
.ps-stats-goal .pct{font-size:.95rem;font-weight:800;color:#7C3AED}
.ps-stats-goal .pct.is-done{color:#12B886}
.ps-stats-goal .fig{font-size:1.45rem;font-weight:800;color:#171423;margin:.3rem 0 .55rem;line-height:1.1}
.ps-stats-goal .fig small{font-size:.85rem;color:#6B6880;font-weight:600}
.ps-stats-goal .bar{margin-bottom:.5rem}
.ps-stats-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem;margin:.2rem 0 1.1rem}
div[class*="st-key-stats_annual_"] button,div[class*="st-key-stats_lt_save"] button{border-radius:999px!important;font-weight:700!important}
div[class*="st-key-ps_stats_banner"] [data-testid="stPlotlyChart"],div[class*="st-key-ps_stats_chart_card"] [data-testid="stPlotlyChart"],div[class*="st-key-ps_stats_donut_card"] [data-testid="stPlotlyChart"]{background:transparent!important;border:0!important;box-shadow:none!important;padding:0!important}
div[class*="st-key-ps_stats_exp_link"] [data-testid="stExpander"]{background:transparent!important;border:0!important;border-left:0!important;box-shadow:none!important;margin:.15rem 0 0!important}
div[class*="st-key-ps_stats_exp_link"] [data-testid="stExpander"] details{border:0!important;background:transparent!important;box-shadow:none!important}
div[class*="st-key-ps_stats_exp_link"] [data-testid="stExpander"] summary{background:transparent!important;padding:.3rem .15rem!important;color:#7C3AED!important;font-size:.84rem!important;font-weight:700!important}
div[class*="st-key-ps_stats_exp_link"] [data-testid="stExpander"] summary:hover{background:transparent!important;color:#5B21B6!important}
div[class*="st-key-ps_stats_exp_card"] [data-testid="stExpander"]{background:#FFFFFF!important;border:1px solid rgba(23,20,35,.08)!important;border-left:1px solid rgba(23,20,35,.08)!important;border-radius:14px!important;box-shadow:none!important;margin:.7rem 0 .2rem!important}
div[class*="st-key-ps_stats_exp_card"] [data-testid="stExpander"] summary{background:transparent!important;padding:.6rem .95rem!important;font-size:.9rem!important;font-weight:700!important;color:#171423!important}
.ps-stats-note{color:#6B6880;font-size:.84rem;font-weight:600;margin:.25rem 0 .5rem}
.ps-stats-kpi{background:#FFFFFF;border:1px solid #D1D5DB;border-top:4px solid #7C3AED;border-radius:14px;padding:.62rem .72rem;min-width:0;margin-bottom:.45rem}
.ps-stats-kpi .label{font-size:.66rem;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.ps-stats-kpi .value{font-size:1.28rem;color:#171423;font-weight:800;line-height:1.1;margin-top:.2rem}
.ps-stats-kpi .delta{font-size:.74rem;color:#475569;font-weight:600;margin-top:.2rem}
@media (max-width:980px){.ps-stats-bn-figs{grid-template-columns:repeat(3,minmax(0,1fr))}.ps-stats-mile-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.ps-stats-yearend{grid-column:1/-1}}
@media (max-width:640px){
.ps-stats-title{font-size:1.35rem;margin-top:-.3rem}
.ps-stats-pf-kpis,.ps-stats-pf-bottom,.ps-stats-two{grid-template-columns:minmax(0,1fr)}
.ps-stats-bn-figs{grid-template-columns:repeat(2,minmax(0,1fr))}
.ps-stats-mile-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
div[class*="st-key-ps_stats_banner"]{padding:1.05rem 1rem .7rem;border-radius:18px}
div[class*="st-key-stats_view_selector"] button{font-size:.9rem!important}
}
.ps-stats-prev-year{background:#FFFFFF;border:1px solid #D1D5DB;border-left:5px solid #7C3AED;border-radius:16px;padding:.8rem .95rem;margin:.1rem 0 .75rem;box-shadow:0 6px 16px rgba(17,24,39,.06)}
.ps-stats-prev-head{display:flex;align-items:baseline;justify-content:space-between;gap:.6rem;flex-wrap:wrap;margin-bottom:.55rem}
.ps-stats-prev-year-label{font-size:1.25rem;font-weight:800;color:#171423}
.ps-stats-prev-sub{font-size:.76rem;color:#6B6880;font-weight:600}
.ps-stats-prev-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.6rem;margin-bottom:.7rem}
.ps-stats-prev-kpi{background:#F8FAFC;border:1px solid #E5E7EB;border-radius:12px;padding:.5rem .65rem;min-width:0}
.ps-stats-prev-kpi .v{font-size:1.15rem;font-weight:800;color:#171423;line-height:1.15;overflow-wrap:anywhere}
.ps-stats-prev-kpi .v.is-accent{color:#7C3AED}
.ps-stats-prev-row{display:flex;justify-content:space-between;align-items:baseline;gap:.6rem;padding:.42rem 0;border-top:1px solid #EEF0F3;font-size:.86rem}
.ps-stats-prev-row .n{font-weight:700;color:#171423;min-width:0}
.ps-stats-prev-row .v{font-weight:800;color:#171423;white-space:nowrap}
.ps-stats-prev-row .s{display:block;font-size:.72rem;color:#6B6880;font-weight:600}
@media (max-width:640px){.ps-stats-prev-kpis{grid-template-columns:minmax(0,1fr)}}
</style>
"""


def _inject_stats_views_css():
    st.markdown(STATS_VIEWS_CSS, unsafe_allow_html=True)


# -- Sélecteurs mémorisés dans st.session_state ---------------------------------------------------------------

def _sticky_segmented(label, options, *, widget_key, state_key, default):
    """Sélecteur segmenté qui garde le dernier choix (jamais « aucun ») dans st.session_state."""
    options = list(options)
    active = st.session_state.get(state_key)
    if active not in options:
        active = default if default in options else options[0]
        st.session_state[state_key] = active
    if st.session_state.get(widget_key) not in options:
        st.session_state[widget_key] = active

    def _remember():
        picked = st.session_state.get(widget_key)
        if picked in options:
            st.session_state[state_key] = picked
        else:
            st.session_state[widget_key] = st.session_state.get(state_key, active)

    st.segmented_control(label, options, key=widget_key, on_change=_remember, label_visibility="collapsed", width="stretch")
    picked = st.session_state.get(widget_key)
    if picked in options:
        st.session_state[state_key] = picked
    return st.session_state.get(state_key, active)


# -- Vue Performance ------------------------------------------------------------------------------------------

def _sales_years(all_sales):
    return sorted({int(str(row["month"])[:4]) for row in all_sales if str(row.get("month") or "")[:4].isdigit()}, reverse=True)


def _year_rows(all_sales, year):
    prefix = f"{int(year)}-"
    return [row for row in all_sales if str(row.get("month") or "").startswith(prefix)]


def _same_period_previous_year_rows(all_sales, year, now):
    """Ventes de l'année précédente (jusqu'à la même date si `year` est l'année en cours)."""
    rows = _year_rows(all_sales, year - 1)
    if year != now.year:
        return rows
    try:
        cutoff = now.replace(year=year - 1)
    except ValueError:  # 29 février
        cutoff = now.replace(year=year - 1, day=28)
    cutoff = cutoff.replace(hour=23, minute=59, second=59)
    return [row for row in rows if isinstance(row.get("date"), datetime) and row["date"] <= cutoff]


def _year_totals(rows):
    totals = _aggregate_sales(rows)
    cost_known = sum(_safe_float(row.get("cost")) for row in rows if row.get("benef") is not None and row.get("cost") is not None)
    totals["roi"] = (totals["benef"] / cost_known * 100.0) if totals["benef"] is not None and cost_known > 0 else None
    return totals


def _year_delta_text(new, old, year_label, *, points=False):
    if new is None or old is None:
        return None
    if points:
        return f"{new - old:+.1f} pts vs {year_label}".replace(".", ",")
    pct = _pct_change(new, old)
    if pct is None:
        return None
    return f"{pct:+.0f} % vs {year_label}"


def _year_monthly_series(monthly_stats, year, now):
    prefix = f"{int(year)}-"
    with_data = sorted(m for m, stat in monthly_stats.items() if m.startswith(prefix) and (_safe_float(stat.get("ca")) != 0 or _safe_float(stat.get("qty")) > 0))
    if not with_data:
        return [], [], []
    end = now.strftime("%Y-%m") if int(year) == now.year else with_data[-1]
    months = _month_key_range(with_data[0], end)
    ca = [_safe_float((monthly_stats.get(m) or {}).get("ca")) for m in months]
    benef = [_safe_float((monthly_stats.get(m) or {}).get("benef")) for m in months]
    return months, ca, benef


def _lot_cost_map(lots):
    costs = {}
    for idx, lot in enumerate(lots):
        if _is_system_lot(lot):
            continue
        name = lot.get("nom", f"Lot {idx + 1}")
        costs[name] = costs.get(name, 0.0) + _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat", 0)))
    return costs


def _lot_rows_for(rows, lot_costs):
    result = {}
    for row in rows:
        if row.get("is_system_lot") or row.get("is_off_stock"):
            continue
        name = row.get("lot") or "Lot inconnu"
        item = result.setdefault(name, {"lot": name, "ca": 0.0, "benef": 0.0, "qty": 0.0, "cost": lot_costs.get(name, 0.0)})
        item["ca"] += _safe_float(row.get("price"))
        item["qty"] += _physical_sale_quantity(row)
        if row.get("benef") is not None:
            item["benef"] += _safe_float(row.get("benef"))
    return result


# -- Rotation du stock et délai de revente (calculs purs, sans rendu) -----------------------------------------

def _history_series(points):
    """Points valides (date, valeur) de l'historique du stock, triés par date."""
    series = []
    for point in points or []:
        if not isinstance(point, dict):
            continue
        moment = _parse_dt(point.get("captured_at"))
        value = point.get("value")
        if moment is None or value is None:
            continue
        try:
            series.append((moment, float(value)))
        except (TypeError, ValueError):
            continue
    return sorted(series, key=lambda item: item[0])


def _average_stock_value(series, start, end):
    """Valeur moyenne du stock sur [start, end], pondérée par le temps : chaque point vaut jusqu'au suivant
    (plusieurs points le même jour ne pèsent pas plus qu'un seul). None si la durée est nulle."""
    total_seconds = (end - start).total_seconds()
    if total_seconds <= 0:
        return None
    weighted = 0.0
    for index, (moment, value) in enumerate(series):
        if moment >= end:
            break
        segment_start = max(moment, start)
        segment_end = series[index + 1][0] if index + 1 < len(series) else end
        segment_end = min(segment_end, end)
        if segment_end > segment_start:
            weighted += value * (segment_end - segment_start).total_seconds()
    return weighted / total_seconds


def compute_stock_rotation(all_sales, points, now, *, min_days=ROTATION_MIN_DAYS):
    """Rotation du stock « en CA » = CA de la période ÷ valeur moyenne du stock sur la même période.

    - CA : celui des statistiques (ventes initiales et hors stock incluses, comme le CA affiché) des ventes datées
      dans la période ; période = de la première donnée de l'historique du stock à maintenant ;
    - valeur moyenne : moyenne dans le temps des points de l'historique (déjà corrigés du double comptage) ;
      CA et stock sont donc tous deux au prix du marché ;
    - annualisée : rotation de la période × 365 ÷ nombre de jours ; « indicative » sous `min_days` jours.
    Retourne {"status": "ok" | "insufficient", ...}.
    """
    series = _history_series(points)
    if len(series) < 2:
        return {"status": "insufficient", "reason": "historique du stock trop court"}
    start = series[0][0]
    end = max(now, series[-1][0])
    days = (end - start).total_seconds() / 86400.0
    avg_stock = _average_stock_value(series, start, end)
    if days < 1 or not avg_stock or avg_stock <= 0:
        return {"status": "insufficient", "reason": "historique du stock trop court"}
    ca_period = 0.0
    for row in all_sales:
        moment = row.get("date")
        if isinstance(moment, datetime) and start <= moment <= end:
            ca_period += _safe_float(row.get("price"))
    rotation_period = ca_period / avg_stock
    return {
        "status": "ok", "start": start, "end": end, "days": days, "ca_period": ca_period, "avg_stock": avg_stock,
        "rotation_period": rotation_period, "rotation_annual": rotation_period * DAYS_PER_YEAR / days,
        "indicative": days < min_days,
    }


def _lot_created(lot):
    return _parse_dt(lot.get("created") or lot.get("created_at"))


def _is_bulk_created(created):
    return created is not None and created.strftime("%Y-%m-%d") in HISTORY_BULK_LOT_DAYS


def _is_payback_eligible_lot(lot):
    """Lot qui se rembourse par ses ventes : ni système (Stockage, Trade, Collection), ni collection partielle
    (is_mixte), ni fourre-tout (is_divers)."""
    return not _is_system_lot(lot) and not lot.get("is_mixte") and not lot.get("is_divers")


def _lot_purchase_cost(lot):
    """Prix d'achat du lot, mêmes règles que l'indicateur « Lots à rembourser » (`_lot_cost_map`)."""
    return _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat", 0)))


def compute_lot_payback(all_sales, lots, now, *, cost_func=None, min_lots=PAYBACK_MIN_LOTS,
                        pending_count=PAYBACK_PENDING_COUNT, pending_min_value=SLOW_LOT_MIN_VALUE):
    """Délai de remboursement des lots.

    Pour chaque lot : date de remboursement = date de la vente où le CUMUL des ventes de cartes du lot (ordre
    chronologique) atteint son prix d'achat effectif ; délai = jours entre la création du lot et cette date
    (0 si une vente est datée avant la création). Moyenne simple et médiane sur les lots REMBOURSÉS seulement.
    Exclus : ventes initiales et hors stock (jamais comptées dans le cumul), lots système, collection (is_mixte),
    fourre-tout (is_divers), lots créés pendant la saisie en bloc (HISTORY_BULK_LOT_DAYS), lots sans date de création
    ou sans prix d'achat.
    En cours : lots non remboursés, du plus ancien au plus récent, avec l'âge et le reste à rembourser ; seuls ceux
    dont le reste atteint `pending_min_value` € sont listés.
    """
    cost_func = cost_func or _lot_purchase_cost
    sales_by_lot = {}
    for row in all_sales:
        if _is_card_sale(row) and not row.get("is_system_lot") and isinstance(row.get("date"), datetime):
            sales_by_lot.setdefault(row.get("lot"), []).append(row)
    bulk_excluded = undated = no_cost = 0
    paid, pending = [], []
    for lot in lots:
        if not _is_payback_eligible_lot(lot):
            continue
        created = _lot_created(lot)
        if created is None:
            undated += 1
            continue
        if _is_bulk_created(created):
            bulk_excluded += 1
            continue
        try:
            cost = float(cost_func(lot) or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        if cost <= 0:
            no_cost += 1
            continue
        name = lot.get("nom", "?")
        cumulative = 0.0
        paid_on = None
        for row in sorted(sales_by_lot.get(name, []), key=lambda item: item["date"]):
            cumulative += _safe_float(row.get("price"))
            if cumulative >= cost - 1e-9:
                paid_on = row["date"]
                break
        if paid_on is not None:
            paid.append({"lot": name, "created": created, "paid_on": paid_on, "cost": cost,
                         "days": max((paid_on - created).total_seconds() / 86400.0, 0.0)})
        else:
            total_sold = sum(_safe_float(row.get("price")) for row in sales_by_lot.get(name, []))
            pending.append({"lot": name, "created": created, "cost": cost, "reste": cost - total_sold,
                            "days": max((now - created).total_seconds() / 86400.0, 0.0)})
    pending = sorted((row for row in pending if row["reste"] >= pending_min_value), key=lambda row: row["days"], reverse=True)
    result = {"bulk_excluded": bulk_excluded, "undated": undated, "no_cost": no_cost,
              "paid": sorted(paid, key=lambda row: row["days"]), "pending": pending[:pending_count], "pending_total": len(pending),
              "reimbursed_lots": len(paid)}
    if len(paid) < min_lots:
        return {**result, "status": "insufficient"}
    days = [row["days"] for row in paid]
    return {**result, "status": "ok", "mean_days": sum(days) / len(days), "median_days": median(days)}


# -- Formats d'affichage (espaces insécables, pas de décimales inutiles) --------------------------------------

NBSP = " "


def _fmt_eur0(value, *, signed=False):
    """« 8 966 € » : espace insécable, jamais de décimales."""
    if value is None:
        return "N/A"
    amount = int(round(float(value)))
    sign = "-" if amount < 0 else ("+" if signed and amount > 0 else "")
    return f"{sign}{abs(amount):,}".replace(",", NBSP) + f"{NBSP}€"


def _fmt_eur_smart(value):
    """Euros sans décimales sauf pour les petits montants non entiers (prix d'une carte, par exemple)."""
    if value is None:
        return "N/A"
    value = float(value)
    if abs(value) >= 100 or abs(value - round(value)) < 0.005:
        return _fmt_eur0(value)
    return f"{value:.2f}".replace(".", ",") + f"{NBSP}€"


def _fmt_eur2(value):
    """« 1 275,50 € » : comme les cartes de la page Compteurs (centimes toujours affichés)."""
    if value is None:
        return "N/A"
    return f"{float(value):,.2f}".replace(",", NBSP).replace(".", ",") + f"{NBSP}€"


def _fmt_pct0(value, *, signed=False):
    if value is None:
        return "N/A"
    number = int(round(float(value)))
    sign = "+" if signed and number > 0 else ""
    return f"{sign}{number}{NBSP}%"


def _fmt_date_fr(value):
    return value.strftime("%d/%m/%Y")


# -- Vue Performance ------------------------------------------------------------------------------------------

def _collection_lot_names(lots):
    """Noms des lots « Collection » : une partie conservée pour la collection, une partie à vendre.

    Critère existant dans l'application : la case « 🏠 Lot Collection » de la création d'un lot enregistre `is_mixte`
    (avec `valeur_totale` et `prix_achat_reel`) ; la page Lots l'appelle elle-même `is_collection`. Les lots système
    (Collection, Trade, Stockage) sont déjà écartés par `_is_system_lot`.
    """
    return {lot.get("nom", f"Lot {idx + 1}") for idx, lot in enumerate(lots) if lot.get("is_mixte") and not _is_system_lot(lot)}


def _lot_summary(year_rows, lifetime_rows, lot_costs, collection_lots=()):
    """Lots vendus sur l'année : top 3 des plus rentables et lots encore à rembourser (toutes ventes depuis le début).

    Les lots collection (une grande partie est conservée, donc jamais « remboursés » par les ventes) sont exclus du
    compteur « X sur Y » et du « plus gros reste » ; ils sont listés à part dans `collection` (coût, déjà récupéré).
    """
    in_year = _lot_rows_for(year_rows, lot_costs)
    lifetime = _lot_rows_for(lifetime_rows, lot_costs)
    collection_lots = set(collection_lots or ())
    with_cost, collection = [], []
    for name, item in in_year.items():
        cost = item.get("cost", 0.0)
        if cost <= 0:
            continue
        total_ca = lifetime.get(name, item)["ca"]
        if name in collection_lots:
            collection.append({"lot": name, "cost": cost, "ca_total": total_ca})
            continue
        with_cost.append({"lot": name, "cost": cost, "ca_total": total_ca, "reste": max(0.0, cost - total_ca)})
    pending = sorted([row for row in with_cost if row["reste"] > 0], key=lambda row: row["reste"], reverse=True)
    best = sorted([row for row in in_year.values() if row.get("benef", 0) > 0], key=lambda row: row["benef"], reverse=True)[:3]
    total = len(with_cost)
    return {
        "best": best,
        "collection": sorted(collection, key=lambda row: row["cost"], reverse=True),
        "pending": pending,
        "pending_count": len(pending),
        "total_with_cost": total,
        "reimbursed_pct": ((total - len(pending)) / total * 100.0) if total else None,
    }


def _channel_shares(rows, *, small_pct=5.0):
    """Part du CA par canal ; les canaux sous `small_pct` % sont regroupés en « Autres »."""
    totals = {}
    for row in rows:
        channel = _row_channel(row)
        totals[channel] = totals.get(channel, 0.0) + _safe_float(row.get("price"))
    positive = {name: value for name, value in totals.items() if value > 0}
    grand = sum(positive.values())
    if grand <= 0:
        return []
    ordered = sorted(positive.items(), key=lambda item: item[1], reverse=True)
    small = [(name, value) for name, value in ordered if value / grand * 100.0 < small_pct]
    if small:
        big = [(name, value) for name, value in ordered if (name, value) not in small]
        ordered = big + [("Autres", sum(value for _name, value in small))]
    return [{"channel": name, "ca": value, "pct": value / grand * 100.0} for name, value in ordered]


DONUT_COLORS = ["#7C3AED", "#A78BFA", "#5B21B6", "#C4B5FD", "#4C1D95", "#DDD6FE"]
CHART_FONT = dict(family="Plus Jakarta Sans, sans-serif", color="#171423", size=12)


def _chart_month_labels(months):
    """Libellés courts des mois ; l'année n'apparaît qu'au premier mois et à chaque janvier si l'historique couvre plusieurs années."""
    multi_year = len({m[:4] for m in months}) > 1
    labels = []
    for idx, month in enumerate(months):
        start = _month_start(month)
        name = MONTH_SHORT_FR[start.month] if start else str(month)
        labels.append((f"{name} {str(start.year)[2:]}" if start and multi_year and (idx == 0 or start.month == 1) else name) + _estimated_mark(month))
    return labels


def _best_month(months, ca):
    if not months:
        return None
    idx = max(range(len(months)), key=lambda i: ca[i])
    return idx, months[idx], ca[idx]


def _build_year_chart(months, ca, benef):
    """CA (violet, aire à 15 %) et bénéfice (vert) par mois : deux courbes lissées, légende complète sous le graphique."""
    labels = _chart_month_labels(months)
    best = _best_month(months, ca)
    sizes = [11 if best and i == best[0] else 6 for i in range(len(months))]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=ca, name="Chiffre d'affaires", mode="lines+markers", line=dict(color="#7C3AED", width=3, shape="spline", smoothing=0.7),
        marker=dict(size=sizes, color="#7C3AED", line=dict(color="#FFFFFF", width=2)), fill="tozeroy", fillcolor="rgba(124,58,237,.15)",
        hovertemplate="%{x}<br>CA : %{y:,.0f} €<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=labels, y=benef, name="Bénéfice réalisé", mode="lines+markers", line=dict(color="#12B886", width=3, shape="spline", smoothing=0.7),
        marker=dict(size=6, color="#12B886", line=dict(color="#FFFFFF", width=2)),
        hovertemplate="%{x}<br>Bénéfice : %{y:,.0f} €<extra></extra>"))
    estimated = [i for i, month in enumerate(months) if _is_estimated_month(month)]
    if estimated:
        fig.add_vrect(x0=min(estimated) - 0.5, x1=max(estimated) + 0.5, fillcolor="rgba(124,58,237,.07)", line_width=0, layer="below")
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=f"Mois estimés{HISTORY_ESTIMATED_MARK} (historique réparti)",
                                 marker=dict(symbol="square", size=11, color="rgba(124,58,237,.22)"), hoverinfo="skip"))
    fig.update_layout(
        height=360, margin=dict(t=10, b=70, l=8, r=14), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=CHART_FONT, hovermode="x unified",
        yaxis=dict(title="", gridcolor="rgba(23,20,35,.07)", tickformat=",.0f", ticksuffix=" €", zerolinecolor="rgba(23,20,35,.18)", fixedrange=True),
        xaxis=dict(showgrid=False, type="category", fixedrange=True, tickangle=0, nticks=8, tickfont=dict(size=11)),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, font=dict(size=12)),
    )
    return fig


def _build_channel_donut(shares, total_ca):
    labels = [f"{item['channel']} · " + (f"{item['pct']:.0f}{NBSP}%" if item["pct"] >= 1 else f"<1{NBSP}%") for item in shares]
    colors = [("#CBD5E1" if item["channel"] == "Autres" else DONUT_COLORS[i % len(DONUT_COLORS)]) for i, item in enumerate(shares)]
    fig = go.Figure(go.Pie(
        labels=labels, values=[item["ca"] for item in shares], hole=0.64, sort=False, direction="clockwise", textinfo="none",
        marker=dict(colors=colors, line=dict(color="#FFFFFF", width=2)), hovertemplate="%{label}<br>%{value:,.0f} €<extra></extra>"))
    fig.update_layout(
        height=340, margin=dict(t=10, b=8, l=8, r=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=CHART_FONT,
        legend=dict(orientation="h", yanchor="top", y=-0.02, xanchor="center", x=0.5, font=dict(size=12)),
        annotations=[dict(text=f"<b>{_fmt_eur0(total_ca)}</b><br><span style='font-size:11px;color:#6B6880'>de CA</span>", x=0.5, y=0.5, showarrow=False, font=dict(size=20, color="#171423"))],
    )
    return fig


def _kpi_tile(label, value, sub_html, *, tone=""):
    return (
        '<div class="ps-stats-tile">'
        f'<div class="ps-stats-cap">{html.escape(label)}</div>'
        f'<div class="ps-stats-big {tone}">{html.escape(value)}</div>'
        f'<div class="ps-stats-sub">{sub_html}</div>'
        '</div>'
    )


def _lots_top_html(best):
    if not best:
        body = '<div class="ps-stats-empty">Pas encore de lot rentable sur cette année.</div>'
    else:
        top = max(row["benef"] for row in best) or 1.0
        body = '<div class="ps-stats-toplot">' + "".join(
            '<div class="row">'
            f'<div class="name" title="{html.escape(row["lot"], quote=True)}">{html.escape(row["lot"])}</div>'
            f'<div class="val">{_fmt_eur0(row["benef"], signed=True)}</div>'
            f'<div class="bar"><div class="ps-stats-bar is-green"><span style="width:{max(row["benef"] / top * 100.0, 4):.1f}%"></span></div></div>'
            '</div>'
            for row in best
        ) + '</div>'
    return f'<div class="ps-stats-tile"><div class="ps-stats-cap">Lots les plus rentables</div>{body}</div>'


def _lots_unreimbursed_html(summary):
    total = summary["total_with_cost"]
    if not total:
        body = '<div class="ps-stats-empty">Coût d\'achat inconnu pour les lots vendus cette année.</div>'
    else:
        pending = summary["pending_count"]
        pct = summary["reimbursed_pct"] or 0.0
        biggest = summary["pending"][0] if summary["pending"] else None
        foot = (f'Plus gros reste : <b>{html.escape(biggest["lot"])}</b> · {_fmt_eur0(biggest["reste"])}' if biggest else "Tous les lots vendus sont remboursés.")
        body = (
            f'<div class="fig">{pending} <small>sur {total} lots</small></div>'
            f'<div class="ps-stats-bar is-green"><span style="width:{pct:.1f}%"></span></div>'
            f'<div class="ps-stats-sub" style="margin-top:.4rem"><b>{_fmt_pct0(pct)}</b> des lots déjà remboursés</div>'
            f'<div class="foot">{foot}</div>'
        )
    collection = summary.get("collection") or []
    if collection:
        lines = "".join(
            f'<div>{html.escape(row["lot"])} · coût {_fmt_eur0(row["cost"])} · déjà récupéré en ventes {_fmt_eur0(row["ca_total"])}</div>'
            for row in collection
        )
        body += f'<div class="ps-stats-sub ps-stats-collection" style="margin-top:.6rem"><b>Lots collection conservés</b>{lines}</div>'
    return f'<div class="ps-stats-tile ps-stats-reimb"><div class="ps-stats-cap">Lots à rembourser</div>{body}</div>'


def _fmt_times(value):
    """« 1,45 » : deux décimales, virgule française."""
    return f"{value:.2f}".replace(".", ",")


def _fmt_one(value):
    """« 1,5 » : une décimale (arrondi « classique » à partir de la valeur à deux décimales), virgule française."""
    from decimal import ROUND_HALF_UP, Decimal
    return str(Decimal(f"{value:.2f}").quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)).replace(".", ",")


def _fmt_days(value):
    days = int(round(value))
    return f"{days}{NBSP}jour" + ("s" if days > 1 else "")


ROTATION_SCALE_MAX = 4  # l'échelle va de 0× à 4×


def _rotation_html(rotation):
    cap = '<div class="ps-stats-cap">Rotation du stock</div>'
    if not rotation or rotation.get("status") != "ok":
        return f'<div class="ps-stats-tile ps-stats-rotation">{cap}<div class="ps-stats-empty">Pas assez de données</div></div>'
    annual = rotation["rotation_annual"]
    since = _fmt_date_fr(rotation["start"])
    days = int(round(rotation["days"]))
    flag = ' <span class="ps-stats-flag">indicatif</span>' if rotation.get("indicative") else ""
    position = min(max(annual / ROTATION_SCALE_MAX, 0.0), 1.0) * 100.0
    ticks = "".join(f"<span>{n}×</span>" for n in range(ROTATION_SCALE_MAX + 1))
    return (
        f'<div class="ps-stats-tile ps-stats-rotation">{cap}'
        f'<div class="ps-stats-big is-accent">{_fmt_times(annual)}× <small>par an</small></div>'
        f'<div class="ps-stats-sub">Ton stock se renouvelle environ <b>{_fmt_one(annual)} fois par an</b>{flag}</div>'
        f'<div class="ps-stats-scale"><div class="track"><i style="left:{position:.1f}%"></i></div><div class="ticks">{ticks}</div></div>'
        f'<div class="ps-stats-sub ps-stats-detail">CA ÷ stock moyen, tous deux au prix du marché : {_fmt_eur0(rotation["ca_period"])} ÷ {_fmt_eur0(rotation["avg_stock"])} '
        f'= {_fmt_times(rotation["rotation_period"])} sur la période (depuis le {since}, {days}{NBSP}jours), annualisé.</div>'
        '</div>'
    )


def _payback_html(payback):
    cap = '<div class="ps-stats-cap">Délai de remboursement</div>'
    n_bulk = (payback or {}).get("bulk_excluded", 0)
    bulk = f' ({n_bulk} exclu{"s" if n_bulk > 1 else ""} : historique saisi en bloc)' if n_bulk else ""
    if not payback or payback.get("status") != "ok":
        body = '<div class="ps-stats-empty">Pas assez de données</div>'
        if n_bulk:
            body += f'<div class="ps-stats-sub">{n_bulk} lot{"s" if n_bulk > 1 else ""} exclu{"s" if n_bulk > 1 else ""} (historique saisi en bloc)</div>'
    else:
        n = payback["reimbursed_lots"]
        body = (
            f'<div class="ps-stats-big is-accent">{_fmt_days(payback["mean_days"])} <small>en moyenne · médiane {int(round(payback["median_days"]))}{NBSP}j</small></div>'
            f'<div class="ps-stats-sub">Sur {n} lot{"s" if n > 1 else ""} remboursé{"s" if n > 1 else ""}{bulk}</div>'
        )
    pending = (payback or {}).get("pending") or []
    if pending:
        top = max(row["days"] for row in pending) or 1.0
        body += '<div class="ps-stats-sub" style="margin-top:.8rem"><b>Lots en cours de remboursement</b></div><div class="ps-stats-toplot">' + "".join(
            '<div class="row">'
            f'<div class="name" title="{html.escape(row["lot"], quote=True)}">{html.escape(row["lot"])}</div>'
            f'<div class="val is-neutral">{_fmt_days(row["days"])} · reste {_fmt_eur0(row["reste"])}</div>'
            f'<div class="bar"><div class="ps-stats-bar is-orange"><span style="width:{max(row["days"] / top * 100.0, 4):.1f}%"></span></div></div>'
            '</div>'
            for row in pending
        ) + '</div>'
    return f'<div class="ps-stats-tile ps-stats-payback">{cap}{body}</div>'


def _render_empty_year(year, years, now, all_sales, stock_points, all_lots, effective_purchase_price_func):
    """Performance d'une année sans vente : message clair + blocs calculés sur tout l'historique (rotation, remboursement)."""
    earlier = [y for y in years if y < year]
    hint = f" Choisis {earlier[0]} ci-dessus pour consulter l'année passée." if earlier and len(years) > 1 else ""
    when = "pour le moment" if year == now.year else "sur cette année"
    st.info(
        f"Aucune vente enregistrée en {year} {when}. "
        f"Le chiffre d'affaires, le bénéfice et les graphiques de {year} apparaîtront dès la première vente.{hint}"
    )
    payback = compute_lot_payback(all_sales, all_lots or [], now, cost_func=effective_purchase_price_func)
    st.markdown(
        '<div class="ps-stats-pf-bottom">'
        + _rotation_html(compute_stock_rotation(all_sales, stock_points or [], now))
        + _payback_html(payback)
        + '</div>',
        unsafe_allow_html=True,
    )


def _render_performance_view(all_sales, monthly_stats, now, lot_costs, collection_lots=(), *, stock_points=None, all_lots=None, effective_purchase_price_func=None, counters_archive=None):
    years = _sales_years(all_sales)
    if not years:
        st.info("Aucune vente enregistrée pour le moment.")
        return
    if now.year > years[0]:
        years = [now.year] + years  # nouvelle année sans vente : elle reste proposée (et choisie par défaut)
    default_year = str(now.year) if now.year in years else str(years[0])
    if len(years) > 1:
        picked = _sticky_segmented("Année", [str(y) for y in years], widget_key=STATS_YEAR_WIDGET_KEY, state_key=STATS_YEAR_STATE_KEY, default=default_year)
    else:
        picked = str(years[0])
    year = int(picked)
    rows = _year_rows(all_sales, year)
    if not rows:
        # Année choisie sans aucune vente (ex. début janvier) : un message clair plutôt que des « N/A » et des graphiques vides.
        _render_empty_year(year, years, now, all_sales, stock_points, all_lots, effective_purchase_price_func)
        _render_previous_years(counters_archive, all_sales, now)
        return
    totals = _year_totals(rows)
    prev_rows = _same_period_previous_year_rows(all_sales, year, now) if (year - 1) in years else []
    prev = _year_totals(prev_rows) if prev_rows else None
    prev_label = str(year - 1)
    suffix = " à ce jour" if year == now.year else ""

    def vs(key):
        text = _year_delta_text(totals.get(key), prev.get(key), prev_label) if prev else None
        return f' · {html.escape(text.replace(".", ","))}' if text else ""

    margin = totals.get("margin")
    benef_sub = (f"Marge <b>{_fmt_pct0(margin)}</b>" if margin is not None else "Marge inconnue") + vs("benef")
    st.markdown(
        '<div class="ps-stats-pf-kpis">'
        + _kpi_tile(f"Chiffre d'affaires {year}{suffix}", _fmt_eur0(totals["ca"]), "Ventes de l'année" + vs("ca"))
        + _kpi_tile("Bénéfice réalisé", _fmt_eur0(totals["benef"]), benef_sub, tone="is-accent")
        + _kpi_tile("ROI", _fmt_pct0(totals.get("roi")), "Bénéfice ÷ coût d'achat des cartes vendues")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="ps-stats-line"><b>{totals["qty"]:.0f}</b> cartes vendues · panier moyen <b>{_fmt_eur_smart(totals["basket"])}</b> · prix moyen par carte <b>{_fmt_eur_smart(totals["avg_card"])}</b></div>',
        unsafe_allow_html=True,
    )

    months, ca, benef = _year_monthly_series(monthly_stats, year, now)
    left, right = st.columns([2.2, 1], gap="medium")
    with left:
        with st.container(key="ps_stats_chart_card"):
            best = _best_month(months, ca)
            best_html = f'<div class="ps-stats-best">Meilleur mois : <b>{html.escape(_month_label_est(best[1]))}</b> · {_fmt_eur0(best[2])} de CA</div>' if best else ""
            st.markdown(f'<div class="ps-stats-card-head"><div class="ps-stats-cap">CA et bénéfice par mois</div>{best_html}</div>', unsafe_allow_html=True)
            if months:
                st.plotly_chart(_build_year_chart(months, ca, benef), width="stretch", key="stats_perf_year_chart", config={"displayModeBar": False, "responsive": True})
                if _any_estimated(months):
                    st.markdown(_estimated_note_html(months), unsafe_allow_html=True)
            else:
                st.markdown('<div class="ps-stats-empty">Pas encore de ventes sur cette année.</div>', unsafe_allow_html=True)
    with right:
        with st.container(key="ps_stats_donut_card"):
            st.markdown('<div class="ps-stats-cap">Canaux de vente · part du CA</div>', unsafe_allow_html=True)
            shares = _channel_shares(rows)
            if shares:
                st.plotly_chart(_build_channel_donut(shares, sum(item["ca"] for item in shares)), width="stretch", key="stats_perf_channel_donut", config={"displayModeBar": False, "responsive": True})
            else:
                st.markdown('<div class="ps-stats-empty">Aucune vente avec un canal sur cette année.</div>', unsafe_allow_html=True)

    summary = _lot_summary(rows, all_sales, lot_costs, collection_lots)
    st.markdown('<div class="ps-stats-pf-bottom">' + _lots_top_html(summary["best"]) + _lots_unreimbursed_html(summary) + '</div>', unsafe_allow_html=True)
    # Rotation du stock et délai de remboursement : calculés sur tout l'historique, indépendamment de l'année choisie.
    payback = compute_lot_payback(all_sales, all_lots or [], now, cost_func=effective_purchase_price_func)
    st.markdown(
        '<div class="ps-stats-pf-bottom">'
        + _rotation_html(compute_stock_rotation(all_sales, stock_points or [], now))
        + _payback_html(payback)
        + '</div>',
        unsafe_allow_html=True,
    )
    with st.container(key="ps_stats_exp_card_channels"):
        with st.expander("Détail par canal (marge, panier moyen, prix par carte)"):
            _render_channels_view(rows)
    _render_previous_years(counters_archive, all_sales, now)


def _fmt_short_date(value):
    try:
        return dt_module.date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


def _previous_year_card_html(item, all_sales):
    """Carte d'une année archivée : chiffres de l'année calculés depuis les ventes + totaux archivés des compteurs."""
    year = item["year"]
    totals = _year_totals(_year_rows(all_sales, year))
    reset_on = _fmt_short_date(item.get("reset_on"))
    sub = f"Compteurs archivés au {reset_on}" if reset_on else "Compteurs archivés"
    kpis = (
        '<div class="ps-stats-prev-kpis">'
        f'<div class="ps-stats-prev-kpi"><div class="ps-stats-cap">Chiffre d\'affaires</div><div class="v">{html.escape(_fmt_eur0(totals["ca"]))}</div></div>'
        f'<div class="ps-stats-prev-kpi"><div class="ps-stats-cap">Bénéfice réalisé</div><div class="v is-accent">{html.escape(_fmt_eur0(totals["benef"]))}</div></div>'
        f'<div class="ps-stats-prev-kpi"><div class="ps-stats-cap">Cartes vendues</div><div class="v">{totals["qty"]:.0f}</div></div>'
        '</div>'
    )
    rows = ""
    for channel in item["channels"]:
        rows += (
            '<div class="ps-stats-prev-row">'
            f'<div class="n">{html.escape(str(channel["label"]))}<span class="s">{channel["nb"]} vente(s)</span></div>'
            f'<div class="v">{html.escape(_fmt_eur2(channel["ca"]))}</div>'
            '</div>'
        )
    channels_html = (
        '<div class="ps-stats-cap" style="margin-bottom:.15rem">Compteurs par canal (total archivé)</div>' + rows
        if rows else '<div class="ps-stats-empty">Aucun compteur archivé pour cette année.</div>'
    )
    return (
        '<div class="ps-stats-prev-year">'
        f'<div class="ps-stats-prev-head"><span class="ps-stats-prev-year-label">{year}</span><span class="ps-stats-prev-sub">{html.escape(sub)}</span></div>'
        + kpis + channels_html + '</div>'
    )


def _previous_years_html(summary, all_sales, now):
    """Contenu de l'expander « Années précédentes » (message simple si rien n'est archivé)."""
    if not summary:
        return (
            f'<div class="ps-stats-empty">Aucune année archivée pour l\'instant. '
            f'Les compteurs de {now.year} seront archivés au 1er janvier {now.year + 1}.</div>'
        )
    return "".join(_previous_year_card_html(item, all_sales) for item in summary)


def _render_previous_years(counters_archive, all_sales, now):
    with st.container(key="ps_stats_exp_card_previous_years"):
        with st.expander("Années précédentes"):
            st.markdown(_previous_years_html(archived_years_summary(counters_archive), all_sales, now), unsafe_allow_html=True)


def _load_counters_with_yearly_reset(cd, *, counters_path, lots_archives_path, safe_write_json_func, now):
    """Lit counters.json et déclenche le reset annuel s'il est dû (même logique que la page Compteurs).

    Ne fait rien (retourne {}) si le fichier n'existe pas : la page Compteurs le crée. N'interrompt jamais la page.
    """
    if not counters_path or not os.path.exists(counters_path):
        return {}
    try:
        with open(counters_path, "r", encoding="utf-8") as source:
            counters = json.load(source)
        if not isinstance(counters, dict):
            return {}
        result = ensure_yearly_reset(
            counters,
            make_lots_loader(lambda: cd, lots_archives_path),
            now.date(),
            lambda payload: safe_write_json_func(counters_path, payload),
        )
        if result["error"]:
            st.warning(f"Archivage annuel des compteurs impossible pour l'instant : {result['error']}")
        return result["counters"]
    except Exception as exc:  # noqa: BLE001 - un souci de compteurs ne doit jamais bloquer Statistiques
        perf_log(f"counters yearly reset ignoré: {type(exc).__name__}: {exc}")
        return {}


# -- Vue Prévisions -------------------------------------------------------------------------------------------

def _month_axis(start, end, max_ticks=8):
    """Repères de l'axe du temps : (valeurs, libellés) tous les k mois, au plus `max_ticks`."""
    first = start.replace(day=1)
    total = (end.year - first.year) * 12 + end.month - first.month + 1
    step = max(1, -(-total // max_ticks))
    values, labels = [], []
    cursor = first
    for _ in range(0, total + 1, step):
        values.append(cursor)
        labels.append(_month_short_label(cursor.strftime("%Y-%m")) + _estimated_mark(cursor.strftime("%Y-%m")))
        for _i in range(step):
            cursor = _add_months(cursor, 1)
    return values, labels


def _month_end_date(month_key):
    start = _month_start(month_key)
    return _add_months(start, 1) if start else None


def _build_goal_chart(history, target, trend, deadline, now, months_left):
    """Graphique sur fond sombre : moyenne glissante, repère « Aujourd'hui », objectif, trajectoire requise, projection."""
    avg = history["benef_avg"]
    xs = [_month_end_date(m) for m in history["months"]]
    anchor_x, anchor_y = xs[-1], avg[-1]
    end_x = datetime(deadline.year, deadline.month, deadline.day)
    if end_x <= anchor_x:
        end_x = _add_months(anchor_x, 1)
    needed_end = target
    projection_end = anchor_y + trend * months_left
    # La projection « si la tendance continue » ne descend jamais sous 0 € : arrêtée à 0 €, avec un libellé « 0 € vers <mois> ».
    zero_x = None
    if trend < 0 and anchor_y > 0 and projection_end < 0:
        months_to_zero = anchor_y / -trend
        zero_x = _add_months(anchor_x, int(months_to_zero)) + dt_module.timedelta(days=(months_to_zero - int(months_to_zero)) * 30.4375)
        if zero_x > end_x:
            zero_x = None
    projection_x = [anchor_x, zero_x if zero_x is not None else end_x]
    projection_y = [anchor_y, 0.0 if zero_x is not None else max(projection_end, 0.0)]
    top = max(target, max(avg), 1.0)
    # Axe vertical limité à l'historique et à l'objectif : une tendance très négative sort simplement du cadre.
    y_max = min(max(top, projection_end), target * 2.5) * 1.1
    y_min = min(0.0, min(avg)) - 0.1 * target
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=avg, name=f"Moyenne glissante ({history['window']} mois)" if history["window_sizes"][-1] >= history["window"] else "Moyenne glissante (mois disponibles)",
                             mode="lines", line=dict(color="#FFFFFF", width=4, shape="spline", smoothing=0.5),
                             hovertemplate="%{x|%m/%Y}<br>Moyenne : %{y:,.0f} €<extra></extra>"))
    fig.add_trace(go.Scatter(x=[xs[0], end_x], y=[target, target], name=f"Objectif ({_fmt_eur0(target)})", mode="lines",
                             line=dict(color="#F5A524", width=2.5, dash="dash"), hovertemplate="Objectif : %{y:,.0f} €<extra></extra>"))
    fig.add_trace(go.Scatter(x=[anchor_x, end_x], y=[anchor_y, needed_end], name="Trajectoire requise", mode="lines",
                             line=dict(color="#34D399", width=1.6, dash="dot"), hovertemplate="Trajectoire requise : %{y:,.0f} €<extra></extra>"))
    fig.add_trace(go.Scatter(x=projection_x, y=projection_y, name="Si la tendance actuelle continue", mode="lines",
                             line=dict(color="#FCA5A5", width=2, dash="dash"), hovertemplate="Tendance : %{y:,.0f} €<extra></extra>"))
    if zero_x is not None:
        fig.add_annotation(x=zero_x, y=0.0, text=f"0 € vers {_month_label(zero_x.strftime('%Y-%m'))}", showarrow=True, arrowhead=2, arrowcolor="#FCA5A5",
                           ax=0, ay=-36, font=dict(size=12, color="#FCA5A5"), bgcolor="rgba(27,16,56,.6)", borderpad=3)
    fig.add_trace(go.Scatter(x=[now, now], y=[y_min, y_max], name="Aujourd'hui", mode="lines", line=dict(color="rgba(255,255,255,.55)", width=1.2, dash="dot"), hoverinfo="skip"))
    estimated = [m for m in history["months"] if _is_estimated_month(m)]
    if estimated:
        shade_from = max(_month_start(estimated[0]), xs[0])
        shade_to = min(_month_end_date(estimated[-1]), end_x)
        if shade_from < shade_to:
            fig.add_vrect(x0=shade_from, x1=shade_to, fillcolor="rgba(255,255,255,.08)", line_width=0, layer="below")
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=f"Mois estimés{HISTORY_ESTIMATED_MARK} (historique réparti)",
                                 marker=dict(symbol="square", size=11, color="rgba(255,255,255,.22)"), hoverinfo="skip"))
    tick_values, tick_labels = _month_axis(xs[0], end_x, max_ticks=6)
    fig.update_layout(
        height=390, margin=dict(t=8, b=96, l=8, r=14), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Plus Jakarta Sans, sans-serif", color="#E9E3FF", size=12), hovermode="closest",
        yaxis=dict(title="", gridcolor="rgba(255,255,255,.12)", zerolinecolor="rgba(255,255,255,.3)", tickformat=",.0f", ticksuffix=" €", range=[y_min, y_max], fixedrange=True, tickfont=dict(color="rgba(255,255,255,.85)")),
        xaxis=dict(showgrid=False, type="date", tickvals=tick_values, ticktext=tick_labels, range=[xs[0], end_x], fixedrange=True, linecolor="rgba(255,255,255,.2)", tickangle=0, tickfont=dict(size=11, color="rgba(255,255,255,.85)")),
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="center", x=0.5, font=dict(size=12, color="#F3EEFF")),
    )
    return fig


def _banner_figures_html(avg, window_used, window, pct, months_left, deadline, traj, trend):
    needed = traj["needed_per_month"]
    if traj["reached"]:
        needed_text, needed_sub = "Atteint", "objectif déjà atteint"
    elif needed is None:
        needed_text, needed_sub = "—", "date limite dépassée"
    else:
        needed_text, needed_sub = f"{_fmt_eur0(needed, signed=True)}/mois", "pour tenir la date limite"
    window_text = f"{window_used} mois glissants" if window_used >= window else f"{window_used} mois disponibles"
    figures = (
        ("Moyenne actuelle", _fmt_eur0(avg), window_text),
        ("Objectif atteint", _fmt_pct0(pct), "du bénéfice moyen visé"),
        ("Mois restants", str(months_left), f"jusqu'au {_fmt_date_fr(deadline)}"),
        ("Progression nécessaire", needed_text, needed_sub),
        ("Tendance actuelle", f"{_fmt_eur0(trend, signed=True)}/mois", f"sur {TREND_LOOKBACK_MONTHS} mois"),
    )
    return '<div class="ps-stats-bn-figs">' + "".join(
        f'<div class="ps-stats-bn-fig"><div class="l">{html.escape(l)}</div><div class="v">{html.escape(v)}</div><div class="s">{html.escape(s)}</div></div>'
        for l, v, s in figures
    ) + '</div>'


def _render_goal_banner(monthly_stats, now, target, deadline):
    """Bandeau principal : objectif long terme, statut, 5 chiffres, graphique. Retourne (history, needed_per_month)."""
    history = _rolling_average_history(monthly_stats, now)
    months_left = _months_remaining(now, deadline)
    excluded_label = _month_label(history["excluded_month"])
    avg = history["benef_avg"][-1] if history["months"] else 0.0
    trend = _current_trend_per_month(history["benef_avg"])
    traj = _required_trajectory(avg, target, months_left)
    status, tone = _pace_status(avg, target, trend, months_left)
    pct = _long_term_status(avg, target)[3]
    with st.container(key="ps_stats_banner"):
        pill = f'<span class="ps-stats-pill is-{tone}">{html.escape(status)}</span>' if history["months"] else ""
        st.markdown(
            '<div class="ps-stats-bn-head"><div>'
            f'<div class="ps-stats-bn-cap">Objectif PokéStock · avant {_fmt_date_fr(deadline)}</div>'
            f'<div class="ps-stats-bn-title">{_fmt_eur0(target)} de bénéfice moyen par mois</div>'
            f'</div>{pill}</div>',
            unsafe_allow_html=True,
        )
        if not history["months"]:
            st.markdown(f'<div class="ps-stats-bn-note">Pas encore de mois complet : {html.escape(excluded_label)} est exclu tant qu\'il n\'est pas terminé.</div>', unsafe_allow_html=True)
            return history, traj["needed_per_month"]
        window_used = history["window_sizes"][-1]
        st.markdown(_banner_figures_html(avg, window_used, history["window"], pct, months_left, deadline, traj, trend), unsafe_allow_html=True)
        st.plotly_chart(_build_goal_chart(history, target, trend, deadline, now, months_left), width="stretch", key="stats_lt_chart", config={"displayModeBar": False, "responsive": True})
        window_note = (
            f"Moyenne glissante sur {history['window']} mois" if window_used >= history["window"]
            else f"Moyenne sur les {window_used} mois disponibles (fenêtre de {history['window']} mois dès que l'historique le permet)"
        )
        estimated_note = f'<div class="ps-stats-bn-note">{html.escape(HISTORY_ESTIMATED_NOTE)}</div>' if _any_estimated(history["months"]) else ""
        st.markdown(
            f'<div class="ps-stats-bn-note">{html.escape(window_note)} · les mois sans vente comptent pour 0 € · '
            f'le mois en cours ({html.escape(excluded_label)}) est exclu tant qu\'il n\'est pas terminé.</div>' + estimated_note,
            unsafe_allow_html=True,
        )
    return history, traj["needed_per_month"]


PRESET_TARGETS = (1500, 2000, 3000)


def _render_goal_settings(target, deadline, now, goals_path, safe_write_json_func, goals_readable):
    """Expander « Modifier les objectifs » : montant du bénéfice moyen visé et date limite (clé facultative « deadline »)."""
    with st.container(key="ps_stats_exp_card_goals"), st.expander("Modifier les objectifs"):
        labels = [f"{value:,}".replace(",", NBSP) + f"{NBSP}€" for value in PRESET_TARGETS] + ["Autre montant"]
        preset = int(target) if float(target).is_integer() and int(target) in PRESET_TARGETS else None
        index = PRESET_TARGETS.index(preset) if preset is not None else len(PRESET_TARGETS)
        choice = st.radio("Bénéfice moyen visé par mois", labels, index=index, horizontal=True, key="stats_lt_choice")
        if choice == labels[-1]:
            amount = st.number_input("Montant libre (€ de bénéfice moyen par mois)", 1.0, 999999.0, value=float(target), step=100.0, key="stats_lt_target")
        else:
            amount = float(PRESET_TARGETS[labels.index(choice)])
        picked = st.date_input("Date limite", value=deadline, min_value=min(deadline, now.date()), max_value=dt_module.date(2045, 12, 31), format="DD/MM/YYYY", key="stats_lt_deadline")
        if st.button("Enregistrer l'objectif long terme", key="stats_lt_save"):
            if goals_readable and _save_goal_updates(goals_path, safe_write_json_func, long_term=amount, long_term_deadline=picked):
                st.toast("Objectif long terme enregistré.")
                st.rerun()
            else:
                st.error("monthly_goals.json est illisible : rien n'a été écrit.")


def _milestones_html(cards, proj):
    tiles = []
    for card in cards:
        classes = "ps-stats-tile ps-stats-mile" + (" is-reached" if card["reached"] else "") + (" is-next" if card["is_next"] else "")
        if card["reached"]:
            main, sub, bar_class = "Atteint", f"en {html.escape(_month_short_label(card['reached_month']) + _estimated_mark(card['reached_month']))}", "is-green"
        elif card.get("provisional"):
            main, sub, bar_class = "À confirmer", f"moyenne sur moins de {PROJECTION_MIN_MONTHS} mois", ""
        else:
            main = f"Reste {_fmt_eur0(card['remaining'])}"
            sub = f"Visé : {html.escape(_month_short_label(card['target_month']))}" if card["target_month"] else "Date non estimable"
            bar_class = ""
        tiles.append(
            f'<div class="{classes}"><div class="ps-stats-cap">{_fmt_eur0(card["value"])} / mois</div>'
            f'<div class="main">{main}</div><div class="ps-stats-sub">{sub}</div>'
            f'<div class="bar"><div class="ps-stats-bar {bar_class}"><span style="width:{card["progress"]:.1f}%"></span></div></div></div>'
        )
    tiles.append(_yearend_html(proj))
    note = _estimated_note_html([card["reached_month"] for card in cards if card.get("reached_month")])
    return '<div class="ps-stats-mile-grid">' + "".join(tiles) + '</div>' + note


def _yearend_html(proj):
    if not proj or proj["status"] != "projection":
        return '<div class="ps-stats-tile ps-stats-yearend"><div class="ps-stats-cap">Fin d\'année estimée</div><div class="ps-stats-empty">Disponible pour l\'année en cours.</div></div>'
    n, k = proj["complete_months"], proj["remaining_months"]
    method = (f"Total à ce jour + moyenne des {n} mois complets × {k} mois restants." if n else "Aucun mois complet cette année : total à ce jour seulement.")
    flag = f'<div class="ps-stats-flag">Indicatif : {n} mois complet{"s" if n > 1 else ""} seulement</div>' if proj["indicative"] else ""
    return (
        '<div class="ps-stats-tile ps-stats-yearend">'
        f'<div class="ps-stats-cap">Fin d\'année {proj["year"]} estimée</div>'
        '<div class="vals">'
        f'<div><div class="v">{_fmt_eur0(proj["projected"]["benef"])}</div><div class="l">Bénéfice</div></div>'
        f'<div><div class="v">{_fmt_eur0(proj["projected"]["ca"])}</div><div class="l">CA</div></div>'
        '</div>'
        f'<div class="ps-stats-sub" style="margin-top:.5rem">{html.escape(method)}</div>{flag}'
        '</div>'
    )


ANNUAL_GOAL_FIELDS = (
    ("ca", "ca_target", "CA annuel", "€"),
    ("benef", "benef_target", "Bénéfice annuel", "€"),
    ("qty", "qty_target", "Cartes vendues", ""),
)


def _annual_goal_tile(label, unit, to_date, projected, target, indicative):
    value = _fmt_eur0(to_date) if unit == "€" else f"{to_date:.0f}"
    if not target or target <= 0:
        return (
            '<div class="ps-stats-tile ps-stats-goal">'
            f'<div class="top"><div class="ps-stats-cap">{html.escape(label)}</div></div>'
            f'<div class="fig">{html.escape(value)} <small>à ce jour</small></div></div>'
        )
    pct = to_date / target * 100.0
    proj_pct = projected / target * 100.0
    target_text = _fmt_eur0(target) if unit == "€" else f"{target:.0f}"
    proj_text = f"Projection fin d'année : <b>{_fmt_pct0(proj_pct)}</b>" + (f" (≈ {projected:.0f} cartes)" if unit != "€" else "") + (" · indicatif" if indicative else "")
    return (
        '<div class="ps-stats-tile ps-stats-goal">'
        f'<div class="top"><div class="ps-stats-cap">{html.escape(label)}</div><div class="pct {"is-done" if pct >= 100 else ""}">{_fmt_pct0(pct)}</div></div>'
        f'<div class="fig">{html.escape(value)} <small>/ {html.escape(target_text)}</small></div>'
        f'<div class="bar"><div class="ps-stats-bar {"is-green" if pct >= 100 else ""}"><span class="ghost" style="width:{min(proj_pct, 100):.1f}%"></span><span style="width:{min(pct, 100):.1f}%"></span></div></div>'
        f'<div class="ps-stats-sub">{proj_text}</div></div>'
    )


def _render_annual_goal_cards(year, proj, annual, goals_path, safe_write_json_func, goals_readable):
    st.markdown(f'<div class="ps-stats-sec">Objectifs {year}</div>', unsafe_allow_html=True)
    columns = st.columns(len(ANNUAL_GOAL_FIELDS), gap="medium")
    to_date = proj["to_date"] if proj else {"ca": 0.0, "benef": 0.0, "qty": 0.0}
    projected = proj["projected"] if proj else to_date
    indicative = bool(proj and proj.get("indicative"))
    if not any((annual or {}).get(key) for _f, key, _l, _u in ANNUAL_GOAL_FIELDS):
        st.markdown(f'<div class="ps-stats-note">Aucun objectif annuel défini pour {year} : utilisez « Définir » sous chaque carte.</div>', unsafe_allow_html=True)
    for column, (field, target_key, label, unit) in zip(columns, ANNUAL_GOAL_FIELDS):
        target = (annual or {}).get(target_key) or 0.0
        with column:
            st.markdown(_annual_goal_tile(label, unit, to_date[field], projected[field], target, indicative), unsafe_allow_html=True)
            with st.container(key=f"ps_stats_exp_link_{field}"), st.expander("Modifier" if target > 0 else "Définir"):
                if unit == "€":
                    new_value = st.number_input(f"{label} (€)", 0.0, 9999999.0, value=float(target), step=100.0, key=f"stats_annual_{field}_input")
                else:
                    new_value = st.number_input(f"{label} (cartes)", 0, 999999, value=int(target), step=10, key=f"stats_annual_{field}_input")
                if st.button("Enregistrer", key=f"stats_annual_{field}_save"):
                    values = {key: float((annual or {}).get(key) or 0.0) for _f, key, _l, _u in ANNUAL_GOAL_FIELDS}
                    values[target_key] = float(new_value)
                    if goals_readable and _save_goal_updates(goals_path, safe_write_json_func, annual=(year, values)):
                        st.toast(f"{label} : objectif enregistré.")
                        st.rerun()
                    else:
                        st.error("monthly_goals.json est illisible : rien n'a été écrit.")


def _render_other_goals(monthly_stats, goals_data, now):
    total = _cumulative_benefit(monthly_stats)
    pct = total / CUMULATIVE_BENEF_MILESTONE * 100.0
    reached = pct >= 100
    streak, best = _consecutive_months_above_goal(monthly_stats, goals_data, now)
    plural = "s" if streak > 1 else ""
    best_text = f"Record : {best} mois" if best else "Aucun mois au-dessus de l'objectif pour l'instant"
    cumul = (
        '<div class="ps-stats-tile ps-stats-goal">'
        f'<div class="top"><div class="ps-stats-cap">Bénéfice cumulé depuis le début</div><div class="pct {"is-done" if reached else ""}">{_fmt_pct0(pct)}</div></div>'
        f'<div class="fig">{_fmt_eur0(total)} <small>/ {_fmt_eur0(CUMULATIVE_BENEF_MILESTONE)}</small></div>'
        f'<div class="bar"><div class="ps-stats-bar {"is-green" if reached else ""}"><span style="width:{max(0.0, min(pct, 100)):.1f}%"></span></div></div>'
        f'<div class="ps-stats-sub">{"Palier atteint" if reached else f"Reste {_fmt_eur0(CUMULATIVE_BENEF_MILESTONE - total)} pour le palier"}</div></div>'
    )
    series = (
        '<div class="ps-stats-tile ps-stats-goal">'
        '<div class="top"><div class="ps-stats-cap">Mois consécutifs au-dessus de l\'objectif mensuel</div></div>'
        f'<div class="fig">{streak} <small>mois{plural} d\'affilée</small></div>'
        f'<div class="ps-stats-sub">{html.escape(best_text)} · objectif de bénéfice du mois, mois en cours exclu.</div></div>'
    )
    st.markdown('<div class="ps-stats-two">' + cumul + series + '</div>', unsafe_allow_html=True)


def _render_forecast_view(all_sales, monthly_stats, now, goals_path, safe_write_json_func):
    year = now.year
    goals_data, readable = _read_goals_file(goals_path)
    annual = _annual_goal_for_year(goals_data, year)
    proj = _year_projection(monthly_stats, year, now)
    target = _long_term_target(goals_data)
    deadline = _long_term_deadline(goals_data)

    history, needed = _render_goal_banner(monthly_stats, now, target, deadline)
    _render_goal_settings(target, deadline, now, goals_path, safe_write_json_func, readable)

    st.markdown('<div class="ps-stats-sec">Paliers de bénéfice moyen par mois</div>', unsafe_allow_html=True)
    st.markdown(_milestones_html(_milestone_status(history, needed, now), proj), unsafe_allow_html=True)

    _render_annual_goal_cards(year, proj, annual, goals_path, safe_write_json_func, readable)
    st.markdown('<div class="ps-stats-sec">Autres objectifs</div>', unsafe_allow_html=True)
    _render_other_goals(monthly_stats, goals_data, now)


# -- Vue Mensuel : contenu actuel, simplement déplacé ---------------------------------------------------------

def _load_corrected_stock_points(lots, archives, history_path):
    """Points de la courbe du stock, corrigés du double comptage À L'AFFICHAGE (lecture seule : le JSON n'est jamais écrit)."""
    try:
        from services.stock_history_service import corrected_stock_history_points, load_stock_history
        payload = load_stock_history(history_path)
        points, _info = corrected_stock_history_points(
            payload.get("points") or [], lots=lots, archives=archives,
            project_dir=os.path.dirname(os.path.abspath(history_path)),
        )
        return points
    except Exception:
        return []


def _read_archives(lots_archives_path):
    if not os.path.exists(lots_archives_path):
        return []
    try:
        with open(lots_archives_path, encoding="utf-8") as source:
            data = json.load(source)
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _render_monthly_view(cd, all_sales, purchases, monthly_stats, months_sorted, current_month, now, proxy_img_func, lots_archives_path, monthly_goals_path, safe_write_json_func):
    profile_lots = list(cd.get("lots", []))
    if os.path.exists(lots_archives_path):
        with open(lots_archives_path, encoding="utf-8") as source:
            profile_lots.extend(json.load(source))
    profile_stats = build_profile_stats(monthly_stats, all_sales, purchases, profile_lots, now,
                                       aggregate=_aggregate_sales, is_system=_is_system_lot)
    _render_stats_v3_hero(all_sales, monthly_stats, months_sorted, current_month, proxy_img_func, now=now, profile_stats=profile_stats)
    _render_stats_v3_chart(monthly_stats, months_sorted, current_month, all_sales=all_sales, now=now, profile_stats=profile_stats)
    _render_stats_v3_timeline(monthly_stats, months_sorted, current_month, profile_stats=profile_stats)
    _render_stats_v3_goals(monthly_stats, months_sorted, current_month, monthly_goals_path, safe_write_json_func)
    _render_stats_v3_records(all_sales, monthly_stats, months_sorted)


def render_statistics_page(
    *,
    ld_func,
    safe_write_json_func,
    calc_cout_lot_func,
    effective_purchase_price_func,
    proxy_img_func,
    lots_archives_path="lots_archives.json",
    monthly_goals_path="monthly_goals.json",
    stock_history_path="stock_value_history.json",
    counters_path=None,
    now=None,
):
    _inject_stats_css()
    _inject_stats_views_css()

    with perf_timer("stats ld"):
        cd = ld_func()

    now = now or datetime.now()  # `now` n'est fourni que par les tests (date simulée)
    current_month = now.strftime("%Y-%m")
    # Reset annuel des compteurs (idempotent). Par défaut counters.json est cherché à côté de lots_archives.json.
    if counters_path is None:
        counters_path = os.path.join(os.path.dirname(lots_archives_path) or ".", "counters.json")
    counters_state = _load_counters_with_yearly_reset(cd, counters_path=counters_path, lots_archives_path=lots_archives_path, safe_write_json_func=safe_write_json_func, now=now)
    with perf_timer("stats collect"):
        all_sales, purchases = _collect_statistics_data(cd, calc_cout_lot_func=calc_cout_lot_func, effective_purchase_price_func=effective_purchase_price_func, lots_archives_path=lots_archives_path)
        all_sales = _spread_history_import(all_sales)
        monthly_stats = _build_monthly_stats(all_sales, purchases)
        months_sorted = sorted(monthly_stats.keys())

    if not months_sorted:
        st.info("Aucune vente enregistrée pour le moment.")
        return

    st.markdown('<div class="ps-stats-title">Statistiques</div>', unsafe_allow_html=True)
    view = _sticky_segmented("Vue", STATS_VIEWS, widget_key=STATS_VIEW_WIDGET_KEY, state_key=STATS_VIEW_STATE_KEY, default="Mensuel")
    # Seule la vue choisie est calculée et affichée.
    with perf_timer(f"stats vue {view}"):
        if view == "Performance":
            archives = _read_archives(lots_archives_path)
            all_lots = list(cd.get("lots", [])) + archives
            _render_performance_view(
                all_sales, monthly_stats, now, _lot_cost_map(all_lots), _collection_lot_names(all_lots),
                stock_points=_load_corrected_stock_points(cd.get("lots", []), archives, stock_history_path), all_lots=all_lots,
                effective_purchase_price_func=effective_purchase_price_func,
                counters_archive=counters_state,
            )
        elif view == "Prévisions":
            _render_forecast_view(all_sales, monthly_stats, now, monthly_goals_path, safe_write_json_func)
        else:
            _render_monthly_view(cd, all_sales, purchases, monthly_stats, months_sorted, current_month, now, proxy_img_func, lots_archives_path, monthly_goals_path, safe_write_json_func)
    st.caption(STATS_SIDEBAR_DIFF_CAPTION)

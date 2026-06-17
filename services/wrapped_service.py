"""Read-only yearly statistics for the PokéStock Wrapped page."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import os


UNAVAILABLE = "Donnée indisponible"


def _safe_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _naive_datetime(value):
    if not value:
        return None
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _lot_created_date(lot):
    for key in ("created", "created_at", "date_achat", "purchase_date", "date"):
        parsed = _parse_date(lot.get(key))
        if parsed:
            return parsed
    return None


def _is_system_lot(lot):
    name = str(lot.get("nom", "")).lower()
    if lot.get("is_collection_lot") or lot.get("is_trade_lot") or lot.get("is_storage_lot"):
        return True
    return any(marker in name for marker in ("collection", "trade", "stockage"))


def _card_label(card):
    name = str(card.get("name") or card.get("card_name") or "?").strip() or "?"
    number = str(card.get("number") or card.get("card_number") or "").strip()
    return f"{name} #{number}" if number else name


def _card_image(card):
    for key in (
        "manual_image_url",
        "resolved_collection_image_url",
        "image_url",
        "image_url_en",
    ):
        value = str(card.get(key) or "").strip()
        if value and value != "__placeholder__":
            return value
    return ""


def _lot_image(lot):
    for card in lot.get("cards", []):
        image = _card_image(card)
        if image:
            return image
    return ""


def _available_qty(card):
    qty = _safe_int(card.get("quantity"), 0)
    sold = _safe_int(card.get("sold_quantity"), 0)
    stored = _safe_int(card.get("stored_quantity"), 0)
    return max(qty - sold - stored, 0)


def _read_archives(path):
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _collect_sales(data, archives, calc_cout_lot_func, effective_purchase_price_func):
    active_lots = list(data.get("lots", []))
    all_sales = []

    for lot_idx, lot in enumerate(active_lots + archives):
        real_lot_idx = lot_idx if lot_idx < len(active_lots) else None
        lot_name = lot.get("nom", "?")
        ventes_avec_cout, valeur_est = calc_cout_lot_func(lot, lot_idx=real_lot_idx)

        for sale in lot.get("ventes", []):
            if sale.get("is_lot_sale") or sale.get("is_exchange_benefit"):
                continue
            sale_date = _parse_date(sale.get("date"))
            if not sale_date:
                continue
            price = _safe_float(sale.get("price"))
            qty = max(_safe_int(sale.get("quantity"), 1), 1)
            if lot.get("is_mixte") and _safe_float(lot.get("valeur_totale")) > 0:
                total_value = _safe_float(lot.get("valeur_totale"), 1.0) or 1.0
                paid = _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat")))
                cost = (price / total_value) * paid
            else:
                cost = (price / (valeur_est or 1.0)) * effective_purchase_price_func(lot)
            all_sales.append(
                {
                    "date": sale_date,
                    "month": sale_date.strftime("%Y-%m"),
                    "price": price,
                    "quantity": qty,
                    "card_name": sale.get("card_name", "Vente lot"),
                    "lot": lot_name,
                    "cost": cost,
                    "benef": price - cost,
                    "cote": _safe_float(sale.get("suggested_price_at_sale"), price) * qty,
                    "image_url": "",
                }
            )

        for card, sale, cost in ventes_avec_cout:
            if sale.get("is_exchange"):
                continue
            sale_date = _parse_date(sale.get("date"))
            if not sale_date:
                continue
            qty = max(_safe_int(sale.get("quantity"), 1), 1)
            price = _safe_float(sale.get("price"))
            cote_total = _safe_float(sale.get("suggested_price_at_sale") or card.get("suggested_price")) * qty
            if cote_total <= 0:
                cote_total = price
            all_sales.append(
                {
                    "date": sale_date,
                    "month": sale_date.strftime("%Y-%m"),
                    "price": price,
                    "quantity": qty,
                    "card_name": sale.get("card_name", card.get("name", "?")),
                    "lot": lot_name,
                    "cost": cost,
                    "benef": price - cost,
                    "cote": cote_total,
                    "image_url": _card_image(card),
                }
            )

    return all_sales


def _group_top_cards(sales, limit=5):
    grouped = defaultdict(lambda: {"name": "", "quantity": 0, "ca": 0.0, "benef": 0.0, "image_url": ""})
    for sale in sales:
        name = str(sale.get("card_name") or "?")
        grouped[name]["name"] = name
        grouped[name]["quantity"] += _safe_int(sale.get("quantity"), 1)
        grouped[name]["ca"] += _safe_float(sale.get("price"))
        grouped[name]["benef"] += _safe_float(sale.get("benef"))
        if not grouped[name]["image_url"] and sale.get("image_url"):
            grouped[name]["image_url"] = sale.get("image_url", "")
    return sorted(grouped.values(), key=lambda x: (x["ca"], x["quantity"]), reverse=True)[:limit]


def _best_deal(year_sales):
    candidates = []
    for sale in year_sales:
        price = _safe_float(sale.get("price"))
        cost = _safe_float(sale.get("cost"))
        benef = _safe_float(sale.get("benef"))
        if price <= 0 or benef <= 0:
            continue
        multiplier = (price / cost) if cost > 0 else None
        candidates.append(
            {
                "name": sale.get("card_name") or "?",
                "lot": sale.get("lot") or "?",
                "price": price,
                "cost": cost,
                "benef": benef,
                "multiplier": multiplier,
                "image_url": sale.get("image_url", ""),
                "date": sale.get("date"),
            }
        )
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x["benef"], x["multiplier"] or 0, x["price"]), reverse=True)[0]


def _lots_bought_in_year(lots, year):
    selected = []
    for lot in lots:
        if _is_system_lot(lot):
            continue
        created = _lot_created_date(lot)
        if created and created.year == year:
            selected.append(lot)
    return selected


def _stock_snapshot(lots):
    total_qty = 0
    total_value = 0.0
    patient_cards = []
    for lot in lots:
        if _is_system_lot(lot):
            continue
        lot_name = lot.get("nom", "?")
        created = _lot_created_date(lot)
        for card in lot.get("cards", []):
            if card.get("is_collection_keep"):
                continue
            available = _available_qty(card)
            if available <= 0:
                continue
            value = _safe_float(card.get("suggested_price")) * available
            total_qty += available
            total_value += value
            patient_days = None
            if created:
                patient_days = max((datetime.now() - _naive_datetime(created)).days, 0)
            patient_cards.append(
                {
                    "name": _card_label(card),
                    "lot": lot_name,
                    "quantity": available,
                    "value": value,
                    "days": patient_days,
                    "image_url": _card_image(card),
                }
            )
    patient_cards = sorted(
        patient_cards,
        key=lambda x: ((x["days"] if x["days"] is not None else -1), x["value"]),
        reverse=True,
    )
    return {
        "quantity": total_qty,
        "value": total_value,
        "most_patient": patient_cards[0] if patient_cards else None,
    }


def _top_recovered_cards(lots, limit=5):
    grouped = defaultdict(lambda: {"name": "", "quantity": 0, "value": 0.0, "image_url": ""})
    for lot in lots:
        for card in lot.get("cards", []):
            if card.get("is_collection_keep") and _is_system_lot(lot):
                continue
            qty = max(_safe_int(card.get("quantity"), 1), 1)
            label = _card_label(card)
            grouped[label]["name"] = label
            grouped[label]["quantity"] += qty
            grouped[label]["value"] += _safe_float(card.get("suggested_price")) * qty
            if not grouped[label]["image_url"]:
                grouped[label]["image_url"] = _card_image(card)
    return sorted(grouped.values(), key=lambda x: (x["value"], x["quantity"]), reverse=True)[:limit]


def _top_lots(year_sales, lots, limit=3):
    lot_images = {str(lot.get("nom") or "?"): _lot_image(lot) for lot in lots}
    grouped = defaultdict(lambda: {"lot": "", "ca": 0.0, "benef": 0.0, "quantity": 0, "image_url": ""})
    for sale in year_sales:
        lot = str(sale.get("lot") or "?")
        grouped[lot]["lot"] = lot
        grouped[lot]["ca"] += _safe_float(sale.get("price"))
        grouped[lot]["benef"] += _safe_float(sale.get("benef"))
        grouped[lot]["quantity"] += _safe_int(sale.get("quantity"), 1)
        if not grouped[lot]["image_url"]:
            grouped[lot]["image_url"] = lot_images.get(lot, "")
    return sorted(grouped.values(), key=lambda x: (x["benef"], x["ca"]), reverse=True)[:limit]


def _month_stats(year_sales):
    by_month = defaultdict(lambda: {"month": "", "ca": 0.0, "benef": 0.0, "quantity": 0})
    for sale in year_sales:
        month = sale["month"]
        by_month[month]["month"] = month
        by_month[month]["ca"] += _safe_float(sale.get("price"))
        by_month[month]["benef"] += _safe_float(sale.get("benef"))
        by_month[month]["quantity"] += _safe_int(sale.get("quantity"), 1)
    months = sorted(by_month.values(), key=lambda x: x["month"])
    top = sorted(months, key=lambda x: (x["ca"], x["quantity"]), reverse=True)
    return months, (top[0] if top else None), top[:3]


def _avg_purchase_percent(lots):
    total_paid = 0.0
    total_cote = 0.0
    for lot in lots:
        paid = _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat")))
        cote = _safe_float(lot.get("valeur_totale"))
        if cote <= 0:
            for card in lot.get("cards", []):
                cote += _safe_float(card.get("suggested_price")) * max(_safe_int(card.get("quantity"), 1), 1)
        if paid > 0 and cote > 0:
            total_paid += paid
            total_cote += cote
    if total_cote <= 0:
        return None
    return (total_paid / total_cote) * 100


def _fastest_reimbursed_lot(lots, all_sales):
    sales_by_lot = defaultdict(list)
    for sale in all_sales:
        sales_by_lot[str(sale.get("lot") or "?")].append(sale)

    best = None
    for lot in lots:
        if _is_system_lot(lot):
            continue
        created = _lot_created_date(lot)
        paid = _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat")))
        if not created or paid <= 0:
            continue
        cumulative = 0.0
        for sale in sorted(sales_by_lot.get(str(lot.get("nom") or "?"), []), key=lambda x: x["date"]):
            cumulative += _safe_float(sale.get("price"))
            if cumulative >= paid:
                days = max((sale["date"] - created).days, 0)
                candidate = {"lot": lot.get("nom", "?"), "days": days, "paid": paid, "ca": cumulative}
                if best is None or days < best["days"]:
                    best = candidate
                break
    return best


def _average_days_to_sell(year_sales, lots):
    created_by_lot = {str(lot.get("nom") or "?"): _lot_created_date(lot) for lot in lots}
    total_days = 0
    total_qty = 0
    for sale in year_sales:
        created = created_by_lot.get(str(sale.get("lot") or "?"))
        if not created:
            continue
        days = max((sale["date"] - created).days, 0)
        qty = max(_safe_int(sale.get("quantity"), 1), 1)
        total_days += days * qty
        total_qty += qty
    if total_qty <= 0:
        return None
    return total_days / total_qty


def _average_days_to_empty_lot(lots):
    values = []
    for lot in lots:
        if _is_system_lot(lot):
            continue
        created = _lot_created_date(lot)
        if not created:
            continue
        total_qty = 0
        sold_qty = 0
        sale_dates = []
        for card in lot.get("cards", []):
            total_qty += max(_safe_int(card.get("quantity"), 1), 1)
            sold_qty += _safe_int(card.get("sold_quantity"), 0)
            for sale in card.get("sold_entries", []):
                parsed = _parse_date(sale.get("date"))
                if parsed:
                    sale_dates.append(parsed)
        if total_qty > 0 and sold_qty >= total_qty and sale_dates:
            values.append(max((max(sale_dates) - created).days, 0))
    if not values:
        return None
    return sum(values) / len(values)


def _timeline(stats, year_sales, bought_lots):
    moments = []
    first_lot = None
    dated_lots = []
    for lot in bought_lots:
        created = _naive_datetime(_lot_created_date(lot))
        if created:
            dated_lots.append((created, lot))
    for created, lot in sorted(dated_lots, key=lambda item: item[0]):
            first_lot = {
                "label": "Premier gros départ",
                "title": lot.get("nom", "?"),
                "detail": created.strftime("%d/%m"),
            }
            break
    if first_lot:
        moments.append(first_lot)

    best_month = stats.get("best_month") or {}
    if best_month:
        moments.append(
            {
                "label": "Mois chaud",
                "title": best_month.get("month", "?"),
                "detail": f"CA {_safe_float(best_month.get('ca')):.2f}€",
            }
        )

    best_deal = stats.get("best_deal") or {}
    if best_deal:
        moments.append(
            {
                "label": "Meilleur coup",
                "title": best_deal.get("name", "?"),
                "detail": f"+{_safe_float(best_deal.get('benef')):.2f}€",
            }
        )

    top_sold = (stats.get("top_sold_cards") or [{}])[0]
    if top_sold:
        moments.append(
            {
                "label": "Carte MVP",
                "title": top_sold.get("name", "?"),
                "detail": f"CA {_safe_float(top_sold.get('ca')):.2f}€",
            }
        )
    return moments[:4]


def collect_wrapped_stats(
    data,
    year,
    *,
    calc_cout_lot_func,
    effective_purchase_price_func,
    lots_archives_path="lots_archives.json",
):
    """Build all Wrapped stats without writing any project data."""

    active_lots = list(data.get("lots", []))
    archives = _read_archives(lots_archives_path)
    all_lots = active_lots + archives
    all_sales = _collect_sales(data, archives, calc_cout_lot_func, effective_purchase_price_func)
    year_sales = [sale for sale in all_sales if sale["date"].year == year]
    bought_lots = _lots_bought_in_year(all_lots, year)

    months, best_month, top_months = _month_stats(year_sales)
    top_sold = _group_top_cards(year_sales)
    top_recovered = _top_recovered_cards(bought_lots)
    best_lots = _top_lots(year_sales, all_lots)
    stock_snapshot = _stock_snapshot(active_lots)
    purchase_total = sum(
        _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat")))
        for lot in bought_lots
    )
    avg_purchase = None
    paid_values = [_safe_float(lot.get("prix_achat_reel", lot.get("prix_achat"))) for lot in bought_lots]
    paid_values = [value for value in paid_values if value > 0]
    if paid_values:
        avg_purchase = sum(paid_values) / len(paid_values)

    total_cote_sales = sum(_safe_float(sale.get("cote")) for sale in year_sales)
    total_ca = sum(_safe_float(sale.get("price")) for sale in year_sales)
    avg_negotiation_pct = None
    if total_cote_sales > 0:
        avg_negotiation_pct = max((1 - (total_ca / total_cote_sales)) * 100, 0)

    available_years = sorted(
        {
            sale["date"].year
            for sale in all_sales
        }
        | {
            created.year
            for created in (_lot_created_date(lot) for lot in all_lots)
            if created
        }
    )

    stats = {
        "ca_total": total_ca,
        "profit_total": sum(_safe_float(sale.get("benef")) for sale in year_sales),
        "cards_sold": sum(_safe_int(sale.get("quantity"), 1) for sale in year_sales),
        "lots_bought": len(bought_lots) if bought_lots else None,
        "top_sold_cards": top_sold,
        "top_recovered_cards": top_recovered,
        "top_lots": best_lots,
        "best_month": best_month,
        "top_months": top_months,
        "best_deal": _best_deal(year_sales),
        "purchase_total": purchase_total if bought_lots else None,
        "stock_snapshot": stock_snapshot,
        "avg_lot_purchase": avg_purchase,
        "avg_purchase_percent": _avg_purchase_percent(bought_lots),
        "avg_negotiation_pct": avg_negotiation_pct,
        "fastest_reimbursed_lot": _fastest_reimbursed_lot(all_lots, all_sales),
        "avg_days_to_sell_card": _average_days_to_sell(year_sales, all_lots),
        "avg_days_to_empty_lot": _average_days_to_empty_lot(all_lots),
        "months": months,
    }
    stats["timeline"] = _timeline(stats, year_sales, bought_lots)
    debug_sources = {
        "ca_total": {
            "label": "CA annuel",
            "source": "Somme des prix de vente des entrees vendues sur l'annee.",
            "entries": len(year_sales),
            "value": stats["ca_total"],
        },
        "profit_total": {
            "label": "Benefice annuel",
            "source": "Somme des benefices calcules vente par vente avec la formule existante.",
            "entries": len(year_sales),
            "value": stats["profit_total"],
        },
        "cards_sold": {
            "label": "Cartes vendues",
            "source": "Somme des quantites vendues sur les ventes de l'annee.",
            "entries": len(year_sales),
            "value": stats["cards_sold"],
        },
        "best_month": {
            "label": "Meilleur mois",
            "source": "Mois avec le plus grand CA, puis quantite vendue en departage.",
            "entries": len(months),
            "value": best_month,
        },
        "best_sale": {
            "label": "Meilleure vente",
            "source": "Carte vendue avec le CA groupe le plus eleve sur l'annee.",
            "entries": len(top_sold),
            "value": top_sold[0] if top_sold else None,
        },
        "best_lot": {
            "label": "Meilleur lot",
            "source": "Lot classe par benefice annuel, puis CA annuel en departage.",
            "entries": len(best_lots),
            "value": best_lots[0] if best_lots else None,
        },
        "best_deal": {
            "label": "Meilleur coup",
            "source": "Vente de l'annee classee par benefice, puis multiplicateur.",
            "entries": len(year_sales),
            "value": stats["best_deal"],
        },
        "stock_snapshot": {
            "label": "Stock restant",
            "source": "Cartes encore disponibles dans les lots non systeme.",
            "entries": len(active_lots),
            "value": stock_snapshot,
        },
    }

    unavailable = [
        key
        for key, value in stats.items()
        if value is None or value == [] or value == {}
    ]

    return {
        "year": year,
        "available_years": available_years,
        "sales_count": len(year_sales),
        "stats": stats,
        "debug_sources": debug_sources,
        "unavailable": unavailable,
    }

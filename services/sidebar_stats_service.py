"""Chiffres de la barre latérale par année civile (Vendues, CA, Bénéfice réalisé, Trésorerie nette).

Principe : aucun reset, aucune archive. Les chiffres « de l'année » sont recalculés à chaque fois depuis les ventes,
par fenêtre de dates du 01/01 au 31/12 de l'année demandée ; en janvier l'année change et les chiffres repartent
donc seuls de zéro. Les totaux « depuis le début » sont ceux de gst() et ne changent pas.

Définitions (identiques à celles du total, seule la fenêtre de dates s'ajoute) :
- Vendues : cartes physiques sorties du stock par vente (ni échanges donnés, ni ventes hors stock, ni ventes initiales),
  somme des quantités des sold_entries (hors is_exchange) datées de l'année ;
- CA : prix des lignes de ventes (hors bénéfices d'échange) et des sold_entries datées de l'année ;
- Bénéfice réalisé : même calcul que Statistiques (chaque vente moins sa part du coût d'achat du lot), lignes datées de l'année ;
- Trésorerie nette de l'année : CA de l'année moins le prix d'achat (champ prix_achat, comme gst) des lots CRÉÉS dans l'année.
  La date d'un lot est lue comme dans Statistiques (created, created_at, date_achat, date). Un lot sans date lisible
  n'entre dans aucune année (il reste dans le total). Les lots saisis en bloc les 16-18 mars 2026 comptent en 2026.

La date du jour est toujours passée en paramètre : ce module ne lit jamais l'horloge.
"""

from __future__ import annotations

from datetime import datetime

LOT_DATE_KEYS = ("created", "created_at", "date_achat", "date")


def _year_of(value):
    """Année d'une date ISO (même lecture que Statistiques) ; None si la date est absente ou illisible."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).year
    except (TypeError, ValueError):
        return None


def lot_year(lot):
    """Année de création d'un lot (None si aucune date lisible)."""
    for key in LOT_DATE_KEYS:
        if lot.get(key):
            return _year_of(lot.get(key))
    return None


def _num(value, default=0.0):
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def year_sales_figures(lots, year):
    """(CA, cartes vendues) des ventes datées de `year`, depuis la liste des lots (courants + archivés)."""
    revenue = 0.0
    sold_cards = 0
    for lot in lots:
        for sale in lot.get("ventes", []) or []:
            if sale.get("is_exchange_benefit") or _year_of(sale.get("date")) != year:
                continue
            revenue += _num(sale.get("price"))
        for card in lot.get("cards", []) or []:
            for entry in card.get("sold_entries", []) or []:
                if _year_of(entry.get("date")) != year:
                    continue
                revenue += _num(entry.get("price"))
                if not entry.get("is_exchange"):
                    try:
                        sold_cards += int(entry.get("quantity", 1) or 1)
                    except (TypeError, ValueError):
                        sold_cards += 1
    return revenue, sold_cards


def year_purchases(lots, year):
    """Somme des prix d'achat (prix_achat) des lots créés pendant `year`."""
    return sum(_num(lot.get("prix_achat")) for lot in lots if lot_year(lot) == year)


def realized_profit(rows, year=None):
    """Bénéfice réalisé (définition Statistiques) des lignes de ventes ; `year` limite aux lignes datées de cette année.

    Retourne 0.0 sans ligne et None si aucune ligne n'a de bénéfice connu.
    """
    selected = [row for row in rows if year is None or getattr(row.get("date"), "year", None) == year]
    if not selected:
        return 0.0
    known = [row.get("benef") for row in selected if row.get("benef") is not None]
    return sum(_num(value) for value in known) if known else None


def build_period_stats(lots, rows, year):
    """Tous les chiffres « année » de la barre latérale.

    `lots` : lots courants + archivés ; `rows` : lignes de ventes de Statistiques (_collect_statistics_data),
    ou None si elles n'ont pas pu être calculées (le bénéfice réalisé vaut alors None : affiché « — », jamais 0 trompeur).
    """
    revenue, sold = year_sales_figures(lots, year)
    purchases = year_purchases(lots, year)
    return {
        "year": int(year),
        "year_sold_cards": int(sold),
        "year_revenue": revenue,
        "year_realized_profit": realized_profit(rows, year) if rows is not None else None,
        "total_realized_profit": realized_profit(rows) if rows is not None else None,
        "year_purchases": purchases,
        "year_cash_profit": revenue - purchases,
    }

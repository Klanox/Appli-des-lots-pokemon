"""Pure Brocante helpers.

The Brocante module keeps its own session metadata, but sales that should affect
business totals are written in the existing data.json structures.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import uuid


BRO_CATEGORIES = ("Co / Unco", "Reverse / Holo", "Boîte / classeur vide", "Lot mixte")
PAYMENT_METHODS = ("Espèces", "PayPal", "Autre", "Non renseigné")


DEFAULT_CHECKLIST_TEMPLATE = [
    {"title": "Cartes ajoutées ou vérifiées", "category": "Stock et cartes", "required": True},
    {"title": "Cartes rangées dans les bons classeurs / boîtes", "category": "Stock et cartes", "required": True},
    {"title": "Prix vérifiés sur les cartes importantes", "category": "Stock et cartes", "required": False},
    {"title": "Étiquettes prêtes", "category": "Stock et cartes", "required": False},
    {"title": "Monnaie préparée", "category": "Paiements", "required": True},
    {"title": "QR code PayPal prêt", "category": "Paiements", "required": False},
    {"title": "Téléphone chargé", "category": "Téléphone", "required": True},
    {"title": "Batterie externe prise", "category": "Téléphone", "required": False},
    {"title": "Connexion vérifiée", "category": "Téléphone", "required": False},
    {"title": "Table / nappe prête", "category": "Stand", "required": False},
    {"title": "Sleeves / toploaders pris", "category": "Matériel", "required": False},
    {"title": "Stylo pris", "category": "Matériel", "required": False},
    {"title": "Eau / nourriture prise", "category": "Divers", "required": False},
]


def now_iso() -> str:
    return datetime.now().isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def default_brocantes_data() -> dict:
    return {
        "schema_version": 1,
        "sessions": [],
        "checklist_template": [
            {**item, "id": f"tpl_{index+1}", "order": index + 1, "done": False}
            for index, item in enumerate(DEFAULT_CHECKLIST_TEMPLATE)
        ],
    }


def normalize_brocantes_data(data) -> dict:
    if not isinstance(data, dict):
        data = default_brocantes_data()
    data.setdefault("schema_version", 1)
    data.setdefault("sessions", [])
    data.setdefault("checklist_template", default_brocantes_data()["checklist_template"])
    if not isinstance(data["sessions"], list):
        data["sessions"] = []
    for session in data["sessions"]:
        if not isinstance(session, dict):
            continue
        session.setdefault("id", new_id("brocante"))
        session.setdefault("status", "draft")
        session.setdefault("checklist", [])
        session.setdefault("goals", {})
        session.setdefault("custom_goals", [])
        session.setdefault("expenses", [])
        session.setdefault("transactions", [])
        session.setdefault("exchanges", [])
        session.setdefault("notes", "")
    return data


def make_session(name: str, event_date=None, location: str = "", notes: str = "", goals=None, template=None) -> dict:
    event_date = event_date or date.today()
    template = template or default_brocantes_data()["checklist_template"]
    checklist = []
    for index, item in enumerate(template):
        checklist.append(
            {
                "id": new_id("task"),
                "title": str(item.get("title") or "").strip(),
                "category": str(item.get("category") or "Divers").strip(),
                "done": bool(item.get("done", False)),
                "required": bool(item.get("required", False)),
                "order": int(item.get("order", index + 1) or index + 1),
            }
        )
    return {
        "id": new_id("brocante"),
        "name": str(name or "").strip() or f"Brocante {event_date}",
        "date": str(event_date),
        "location": str(location or "").strip(),
        "status": "preparing",
        "created_at": now_iso(),
        "started_at": None,
        "closed_at": None,
        "notes": str(notes or "").strip(),
        "goals": goals or {},
        "custom_goals": [],
        "checklist": checklist,
        "expenses": [],
        "transactions": [],
        "exchanges": [],
        "closure": {},
    }


def active_session(data: dict) -> dict | None:
    for session in (data or {}).get("sessions", []):
        if session.get("status") == "active":
            return session
    return None


def preparing_session(data: dict) -> dict | None:
    for session in (data or {}).get("sessions", []):
        if session.get("status") in {"draft", "preparing"}:
            return session
    return None


def session_by_id(data: dict, session_id: str) -> dict | None:
    for session in (data or {}).get("sessions", []):
        if str(session.get("id")) == str(session_id):
            return session
    return None


def checklist_summary(session: dict) -> dict:
    tasks = session.get("checklist", []) or []
    total = len(tasks)
    done = sum(1 for item in tasks if item.get("done"))
    required_missing = [item for item in tasks if item.get("required") and not item.get("done")]
    return {"total": total, "done": done, "required_missing": required_missing}


def start_session(data: dict, session_id: str, *, force=False) -> tuple[bool, str]:
    existing = active_session(data)
    if existing and existing.get("id") != session_id:
        return False, "Une autre brocante est déjà active."
    session = session_by_id(data, session_id)
    if not session:
        return False, "Brocante introuvable."
    missing = checklist_summary(session)["required_missing"]
    if missing and not force:
        return False, f"{len(missing)} tâche(s) obligatoire(s) restent à confirmer."
    session["status"] = "active"
    session["started_at"] = session.get("started_at") or now_iso()
    return True, "Brocante démarrée."


def reopen_session(data: dict, session_id: str) -> tuple[bool, str]:
    if active_session(data):
        return False, "Ferme la brocante active avant de réouvrir celle-ci."
    session = session_by_id(data, session_id)
    if not session:
        return False, "Brocante introuvable."
    session["status"] = "active"
    session["reopened_at"] = now_iso()
    return True, "Brocante réouverte."


def lot_uid(lot: dict, fallback_index=None) -> str:
    return str(lot.get("lot_uid") or lot.get("id") or lot.get("uid") or fallback_index or "")


def sale_amount(sale: dict) -> float:
    try:
        return max(float(sale.get("price", 0) or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def append_off_stock_sale(
    cd: dict,
    *,
    category: str,
    quantity: int,
    amount: float,
    payment_method: str = "Non renseigné",
    canal: str | None = None,
    description: str = "",
    source_lot_idx=None,
    cost_basis=None,
    notes: str = "",
    brocante_id: str | None = None,
    transaction_id: str | None = None,
) -> dict:
    quantity = max(int(quantity or 1), 1)
    amount = max(float(amount or 0), 0.0)
    cost_known = cost_basis is not None
    try:
        normalized_cost = max(float(cost_basis or 0), 0.0) if cost_known else None
    except (TypeError, ValueError):
        normalized_cost = None
        cost_known = False
    sale = {
        "sale_id": new_id("off_stock"),
        "date": now_iso(),
        "card_name": str(description or category or "Vente hors stock").strip(),
        "category": str(category or "Autre").strip(),
        "quantity": quantity,
        "price": amount,
        "payment_method": str(payment_method or "Non renseigné").strip(),
        "canal": str(canal or ("Brocante" if brocante_id else "Vente")).strip(),
        "sale_origin": "off_stock",
        "inventory_impact": "none",
        "cost_basis_known": cost_known,
        "cost_basis": normalized_cost,
        "source_lot_id": None,
        "source_lot_name": None,
        "brocante_id": brocante_id,
        "notes": str(notes or "").strip(),
        "is_off_stock": True,
    }
    if transaction_id:
        sale["sale_transaction_id"] = str(transaction_id)
    sale["sold_at"] = sale["date"]
    try:
        from services.vinted_drops_service import link_sale_to_vinted_drop_if_applicable

        link_sale_to_vinted_drop_if_applicable(sale, sale.get("canal", ""))
    except Exception:
        pass
    lots = cd.setdefault("lots", [])
    if source_lot_idx is not None:
        try:
            lot_idx = int(source_lot_idx)
        except (TypeError, ValueError):
            lot_idx = None
        if lot_idx is not None and 0 <= lot_idx < len(lots):
            lot = lots[lot_idx]
            sale["source_lot_id"] = lot_uid(lot, lot_idx)
            sale["source_lot_name"] = lot.get("nom", f"Lot {lot_idx + 1}")
            lot.setdefault("ventes", []).append(deepcopy(sale))
            return sale
    cd.setdefault("ventes_hors_stock", []).append(deepcopy(sale))
    return sale


def lot_reimbursement(lot: dict, lot_index=None) -> dict:
    try:
        cost = max(float(lot.get("prix_achat", 0) or 0), 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    recovered = 0.0
    for sale in lot.get("ventes", []) or []:
        if sale.get("is_exchange_benefit"):
            continue
        recovered += sale_amount(sale)
    for card in lot.get("cards", []) or []:
        for sale in card.get("sold_entries", []) or []:
            if sale.get("is_exchange"):
                continue
            recovered += sale_amount(sale)
    pct = (recovered / cost * 100.0) if cost > 0 else None
    return {
        "lot_uid": lot_uid(lot, lot_index),
        "cost": cost,
        "recovered": recovered,
        "remaining": max(cost - recovered, 0.0) if cost > 0 else None,
        "pct": pct,
        "profit_after_reimbursement": max(recovered - cost, 0.0) if cost > 0 else 0.0,
        "available": cost > 0,
    }


def payment_key(payment_method: str) -> str:
    text = str(payment_method or "").lower()
    if "paypal" in text:
        return "paypal"
    if "esp" in text or "cash" in text:
        return "cash"
    if not text or "non" in text:
        return "unknown"
    return "other"


def record_transaction(session: dict, transaction: dict) -> str:
    transaction = deepcopy(transaction)
    transaction.setdefault("transaction_id", new_id("bro_sale"))
    transaction.setdefault("created_at", now_iso())
    existing_ids = {str(item.get("transaction_id")) for item in session.setdefault("transactions", [])}
    if transaction["transaction_id"] not in existing_ids:
        session["transactions"].append(transaction)
    return transaction["transaction_id"]


def record_exchange(session: dict, exchange: dict) -> str:
    exchange = deepcopy(exchange)
    exchange.setdefault("exchange_id", new_id("bro_exchange"))
    exchange.setdefault("created_at", now_iso())
    existing_ids = {str(item.get("exchange_id")) for item in session.setdefault("exchanges", [])}
    if exchange["exchange_id"] not in existing_ids:
        session["exchanges"].append(exchange)
    return exchange["exchange_id"]


def add_expense(session: dict, label: str, amount: float, category: str, note: str = ""):
    session.setdefault("expenses", []).append(
        {
            "expense_id": new_id("expense"),
            "label": str(label or "").strip() or "Frais",
            "amount": max(float(amount or 0), 0.0),
            "category": str(category or "Autre").strip(),
            "note": str(note or "").strip(),
            "created_at": now_iso(),
        }
    )


def brocante_stats(session: dict) -> dict:
    transactions = session.get("transactions", []) or []
    exchanges = session.get("exchanges", []) or []
    expenses = session.get("expenses", []) or []
    ca = sum(float(tx.get("amount", 0) or 0) for tx in transactions)
    cards_sold = sum(int(tx.get("quantity", 1) or 1) for tx in transactions)
    payments = {"cash": 0.0, "paypal": 0.0, "other": 0.0, "unknown": 0.0}
    off_stock_sales = 0
    unknown_cost_sales = 0
    calculable_profit = 0.0
    for tx in transactions:
        payments[payment_key(tx.get("payment_method"))] += float(tx.get("amount", 0) or 0)
        if tx.get("inventory_impact") == "none":
            off_stock_sales += 1
        if tx.get("cost_basis_known"):
            calculable_profit += float(tx.get("amount", 0) or 0) - float(tx.get("cost_basis", 0) or 0)
        elif tx.get("inventory_impact") == "none":
            unknown_cost_sales += 1
    exchange_cash_received = sum(float(ex.get("cash_received", 0) or 0) for ex in exchanges)
    exchange_cash_given = sum(float(ex.get("cash_given", 0) or 0) for ex in exchanges)
    fees = sum(float(exp.get("amount", 0) or 0) for exp in expenses)
    net_cash = ca + exchange_cash_received - exchange_cash_given - fees
    avg_cart = ca / len(transactions) if transactions else 0.0
    best_sale = max(transactions, key=lambda tx: float(tx.get("amount", 0) or 0), default=None)
    return {
        "ca": ca,
        "net_cash": net_cash,
        "calculable_profit": calculable_profit - fees,
        "fees": fees,
        "sales_count": len(transactions),
        "cards_sold": cards_sold,
        "off_stock_sales": off_stock_sales,
        "unknown_cost_sales": unknown_cost_sales,
        "exchanges_count": len(exchanges),
        "exchange_cash_received": exchange_cash_received,
        "exchange_cash_given": exchange_cash_given,
        "payments": payments,
        "avg_cart": avg_cart,
        "best_sale": best_sale,
    }


def close_session(session: dict, counted_cash: float | None = None, variance_note: str = "") -> dict:
    stats = brocante_stats(session)
    theoretical_cash = stats["payments"]["cash"] + stats["exchange_cash_received"] - stats["exchange_cash_given"] - stats["fees"]
    counted = None if counted_cash is None else float(counted_cash)
    variance = None if counted is None else counted - theoretical_cash
    session["status"] = "closed"
    session["closed_at"] = now_iso()
    session["closure"] = {
        "closed_at": session["closed_at"],
        "stats": stats,
        "theoretical_cash": theoretical_cash,
        "counted_cash": counted,
        "cash_variance": variance,
        "variance_note": str(variance_note or "").strip(),
    }
    return session["closure"]

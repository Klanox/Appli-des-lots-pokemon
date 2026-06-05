"""
Business logic functions for PokéStock application.
"""

import streamlit as st
import json
import os
import time
from utils import fp, normalize_name, parse_float_input, parse_int_input, LOTS_ARCHIVES_FILE
from data import ld, sd

# Constants
APP_DIR = os.path.dirname(os.path.abspath(__file__))


def cr(l):
    """Calculate total revenue for a lot."""
    if l.get("is_trade") or l.get("nom") in ("Trade", "🔄 Trade"):
        return 0.
    r = 0.
    for v in l.get("ventes", []):
        r += v.get("price", 0.)
    for c in l.get("cards", []):
        for s in c.get("sold_entries", []):
            r += s.get("price", 0.)
    return r


def cp(l):
    """Calculate net profit for a lot."""
    return cr(l) - l.get("prix_achat", 0.)


def crp(l):
    """Calculate profit percentage for a lot."""
    c = l.get("prix_achat", 0.)
    return 100. if c == 0 else (cr(l) / c) * 100


def effective_purchase_price(lot):
    """Get effective purchase price, handling mixte lots."""
    if lot.get("is_mixte"):
        return float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
    return float(lot.get("prix_achat", 0.) or 0.)


def card_sold_cote(card):
    """Calculate total sold value and quantity for a card."""
    sold_value = 0.
    sold_qty = 0
    for se in card.get("sold_entries", []):
        qty = int(se.get("quantity", 1))
        price = float(se.get("suggested_price_at_sale", 0.) or card.get("suggested_price", 0.) or 0.)
        sold_value += price * qty
        sold_qty += qty
    return sold_value, sold_qty


def calc_cout_lot(lot, valeur_estimee=None, lot_idx=None):
    """
    Calculate cost of sales for a lot.
    
    coût_vente = (cote_de_la_carte / valeur_estimee_lot) × prix_achat_lot
    valeur_estimee_lot = stock actuel à la cote + cartes vendues à leur cote au moment de la vente
    """
    prix_lot = effective_purchase_price(lot)
    cards = lot.get("cards", [])

    if valeur_estimee is None or valeur_estimee <= 0:
        stock_val = 0.
        sold_cote = 0.
        for c in cards:
            sold_value, sold_qty = card_sold_cote(c)
            unsold_qty = max(int(c.get("quantity", 0)) - sold_qty, 0)
            stock_val += float(c.get("suggested_price", 0.)) * unsold_qty
            sold_cote += sold_value
        ventes_cote = sum(float(v.get("price", 0.)) for v in lot.get("ventes", []) if not v.get("is_exchange_benefit"))
        valeur_estimee = stock_val + sold_cote + ventes_cote

    valeur_estimee = valeur_estimee or 1.0

    result = []
    for card in cards:
        for se in card.get("sold_entries", []):
            price = float(se.get("price", 0.))
            qty = int(se.get("quantity", 1))
            cote_unit = float(se.get("suggested_price_at_sale", 0.) or card.get("suggested_price", 0.) or 0.)
            if cote_unit <= 0:
                cote_unit = price / max(qty, 1)
            cote_total = cote_unit * qty
            # Lot Divers : coût = purchase_price individuel de la carte
            if lot.get("is_divers") and card.get("purchase_price"):
                cout = float(card["purchase_price"]) * qty
            # Carte reçue par échange avec repartition connue
            elif card.get("received_by_exchange") and card.get("exchange_repartition") and lot_idx is not None:
                cout = float(card["exchange_repartition"].get(str(lot_idx), 0.))
            elif lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
                real_price = float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
                cout = (cote_total / float(lot.get("valeur_totale", 1.) or 1.)) * real_price
            else:
                cout = (cote_total / valeur_estimee) * prix_lot
            result.append((card, se, cout))

    return result, valeur_estimee


@st.cache_data(ttl=30, show_spinner=False)
def gst():
    """Calculate global statistics for the application."""
    d = ld()
    tc = sc = rc = 0
    sv = tr = total_cost = 0.
    
    for l in d.get("lots", []):
        total_cost += l.get("prix_achat", 0.)
        for v in l.get("ventes", []):
            if v.get("is_exchange_benefit"):
                continue
            tr += v.get("price", 0.)
        for c in l.get("cards", []):
            cq = c.get("quantity", 0)
            csq = c.get("sold_quantity", 0)
            tc += cq
            sc += csq
            rc += cq - csq
            sv += (cq - csq) * c.get("suggested_price", 0.)
            for s in c.get("sold_entries", []):
                tr += s.get("price", 0.)
    
    archive_file = LOTS_ARCHIVES_FILE
    if os.path.exists(archive_file):
        try:
            with open(archive_file, "r", encoding="utf-8") as f:
                archives = json.load(f)
            for l in archives:
                total_cost += l.get("prix_achat", 0.)
                for v in l.get("ventes", []):
                    if v.get("is_exchange_benefit"):
                        continue
                    tr += v.get("price", 0.)
                for c in l.get("cards", []):
                    cq = c.get("quantity", 0)
                    csq = c.get("sold_quantity", 0)
                    tc += cq
                    sc += csq
                    rc += cq - csq
                    sv += (cq - csq) * c.get("suggested_price", 0.)
                    for s in c.get("sold_entries", []):
                        tr += s.get("price", 0.)
        except Exception as e:
            st.warning(f"Erreur lors de la lecture des archives dans gst(): {e}")
            pass
    
    return {
        "total_cards": int(tc),
        "sold_cards": int(sc),
        "remaining_cards": int(rc),
        "stock_value": sv,
        "total_revenue": tr,
        "total_profit": tr - total_cost,
        "total_revenue_gross": tr
    }


def gsh():
    """Get sales history."""
    d = ld()
    h = []
    for l in d.get("lots", []):
        for v in l.get("ventes", []):
            h.append({**v, "lot_name": l["nom"]})
        for c in l.get("cards", []):
            for s in c.get("sold_entries", []):
                h.append({**s, "lot_name": l["nom"]})
    return sorted(h, key=lambda x: x.get("date", ""), reverse=True)


def is_trade_lot(lot):
    """Check if lot is a trade lot."""
    return lot.get("is_trade") or lot.get("nom") in ("Trade", "🔄 Trade")


def is_storage_lot(lot):
    """Check if lot is a storage lot."""
    return lot.get("is_storage") or lot.get("nom") == "Stockage"


def card_available_qty(card):
    """Get available quantity for a card."""
    return max(int(card.get("quantity", 0)) - int(card.get("sold_quantity", 0)), 0)


def resolve_card_ref(cd, item):
    """Resolve card reference from various formats."""
    if isinstance(item, dict):
        lot_idx = item.get("lot_idx")
        card_idx = item.get("card_idx")
    else:
        lot_idx, card_idx = item
    
    if lot_idx is None or card_idx is None:
        return None, None, None, None
    
    try:
        lot_idx = int(lot_idx)
        card_idx = int(card_idx)
    except (ValueError, TypeError):
        return None, None, None, None
    
    if lot_idx >= len(cd.get("lots", [])):
        return None, None, None, None
    
    lot = cd["lots"][lot_idx]
    if card_idx >= len(lot.get("cards", [])):
        return None, None, None, None
    
    return lot_idx, card_idx, lot, lot["cards"][card_idx]


def migrate_open_trade_cards(cd):
    """Migrate cards with received_by_exchange to trade lot."""
    moved = False
    trade_idx = None
    for i, lot in enumerate(cd.get("lots", [])):
        if is_trade_lot(lot):
            trade_idx = i
            break
    
    if trade_idx is None:
        return False
    
    for lot in cd.get("lots", []):
        if is_trade_lot(lot):
            continue
        kept_cards = []
        for card in lot.get("cards", []):
            remaining = int(card.get("quantity", 0)) - int(card.get("sold_quantity", 0))
            if (card.get("received_by_exchange") and card.get("exchange_repartition")
                    and remaining > 0 and not card.get("sold_entries")):
                cd["lots"][trade_idx].setdefault("cards", []).append(card)
                moved = True
            else:
                kept_cards.append(card)
        lot["cards"] = kept_cards
    return moved

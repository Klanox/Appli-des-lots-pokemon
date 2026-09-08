"""Financial reimbursement and acquisition-cote display helpers for Lots."""

from html import escape
from math import isclose

from core.brocante import lot_reimbursement
from logic import lot_tracked_cote_value


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def format_percentage(value):
    """Format a compact percentage with at most one decimal place."""
    if value is None:
        return ""
    rounded = round(float(value), 1)
    if isclose(rounded, round(rounded), abs_tol=0.0001):
        return str(int(round(rounded)))
    return f"{rounded:.1f}".replace(".", ",")


def lot_reference_value(lot):
    """Return the stable reference value used to evaluate a lot purchase."""
    for field, source in (("valeur_totale", "historique"), ("estimation_value", "estimation")):
        value = _positive_number(lot.get(field))
        if value is not None:
            return {"value": value, "source": source}

    value = _positive_number(lot_tracked_cote_value(lot))
    if value is not None:
        return {"value": value, "source": "suivie"}
    return None


def lot_purchase_cote_ratio(lot):
    """Return the historical acquisition cost as a share of the lot cote."""
    reference = lot_reference_value(lot)
    cost_field = "prix_achat_reel" if lot.get("is_mixte") else "prix_achat"
    cost = _positive_number(lot.get(cost_field))
    if not reference or cost is None:
        return None
    return {**reference, "cost": cost, "pct": cost / reference["value"] * 100}


def lot_purchase_summary(lot, money):
    """Build the compact historical purchase/cote summary for a lot header."""
    ratio = lot_purchase_cote_ratio(lot)
    if ratio:
        return f"{money(ratio['cost'])} · {format_percentage(ratio['pct'])} % cote"
    cost_field = "prix_achat_reel" if lot.get("is_mixte") else "prix_achat"
    return money(lot.get(cost_field, lot.get("prix_achat", 0)) or 0)


def lot_progress(lot, all_lots=(), lot_index=None):
    """Keep financial reimbursement independent from inventory completion."""
    gauge = lot_reimbursement(lot, lot_index)
    cards = lot.get("cards", [])
    total = sum(max(int(card.get("quantity", 0) or 0), 0) for card in cards)
    sold = sum(
        min(
            max(int(card.get("sold_quantity", 0) or 0), 0),
            max(int(card.get("quantity", 0) or 0), 0),
        )
        for card in cards
    )
    # Storage copies retain the source lot UID; transfers themselves are not sales.
    uid = lot.get("lot_uid")
    transferred = sum(max(int(card.get("stored_quantity", 0) or 0), 0) for card in cards)
    if uid and transferred:
        storage_sales = sum(
            max(int(card.get("sold_quantity", 0) or 0), 0)
            for other in all_lots
            if other is not lot
            for card in other.get("cards", [])
            if card.get("stored_from_lot_uid") == uid
        )
        sold += min(storage_sales, transferred)
    sold = min(sold, total)

    reimbursement_pct = gauge.get("pct") if gauge["available"] else None
    visual_progress = min(max(float(reimbursement_pct or 0), 0), 100)
    reimbursed = gauge["available"] and gauge["recovered"] >= gauge["cost"]
    completed = total > 0 and sold == total
    phase = "complete" if completed else ("reimbursed" if reimbursed else "repayment")
    return {
        **gauge,
        "phase": phase,
        "sold": sold,
        "total": total,
        "completed": completed,
        "reimbursed": reimbursed,
        "reimbursement_pct": reimbursement_pct,
        "progress": visual_progress,
    }


def _progress_color(reimbursement_pct):
    if reimbursement_pct is None or reimbursement_pct < 70:
        return "#dc2626"
    if reimbursement_pct < 100:
        return "#f97316"
    return "#15803d"


def lot_progress_html(lot, all_lots, lot_index, money):
    state = lot_progress(lot, all_lots, lot_index)
    if not state["available"]:
        return (
            '<div class="lot-detail-reimbursement-row lot-reimbursement-unavailable">'
            "<span>Coût historique non renseigné</span></div>"
        )

    pct = state["reimbursement_pct"]
    pct_text = format_percentage(pct)
    if state["completed"]:
        label = f"✓ Lot terminé · {pct_text} % remboursé"
    elif state["reimbursed"]:
        label = f"✓ Remboursé · {pct_text} %"
    else:
        label = (
            f"{pct_text} % remboursé · {money(state['recovered'])} / "
            f"{money(state['cost'])}"
        )

    color = _progress_color(pct)
    return (
        '<div class="lot-detail-reimbursement-row">'
        f'<span>{escape(label)}</span>'
        f'<div class="lot-detail-reimbursement-track" role="progressbar" aria-label="{escape(label, quote=True)}" '
        f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{state["progress"]:.1f}">'
        f'<span style="width:{state["progress"]:.1f}%;background:{color}"></span></div></div>'
    )


def lot_summary_card_css():
    """Styles for the single-surface, clickable lot summary card."""
    return """
    [class*="st-key-lot_summary_card_"] {
        box-sizing: border-box;
        width: 100%;
        margin: 0 0 0.55rem;
        padding: 0.78rem 1rem 0.82rem;
        border: 1px solid #e2e8f0;
        border-left: 6px solid #22c55e;
        border-radius: 8px;
        background: #ffffff;
        box-shadow: 0 2px 7px rgba(15, 23, 42, 0.05);
        gap: 0 !important;
    }
    [class*="st-key-lot_summary_card_not-profitable_"] { border-left-color: #dc2626; }
    [class*="st-key-lot_summary_card_brocante_"] { border-left-color: #f97316; }
    [class*="st-key-lot_summary_card_collection_"] { border-left-color: #3b4cca; }
    [class*="st-key-lot_summary_card_trade_"] { border-left-color: #0891b2; }
    [class*="st-key-lot_summary_card_storage_"] { border-left-color: #7c3aed; }
    [class*="st-key-lot_summary_card_"] [data-testid="stButton"] {
        margin: 0 !important;
    }
    [class*="st-key-lot_summary_card_"] [data-testid="stButton"] button {
        min-height: 0 !important;
        padding: 0 !important;
        border: 0 !important;
        border-radius: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        color: #111827 !important;
        font-size: 0.95rem !important;
        font-weight: 700 !important;
        line-height: 1.3 !important;
        justify-content: flex-start !important;
        text-align: left !important;
        white-space: normal !important;
    }
    [class*="st-key-lot_summary_card_"] [data-testid="stButton"] button > div,
    [class*="st-key-lot_summary_card_"] [data-testid="stButton"] button p {
        width: 100% !important;
        justify-content: flex-start !important;
        text-align: left !important;
    }
    [class*="st-key-lot_summary_card_"] [data-testid="stButton"] button:hover,
    [class*="st-key-lot_summary_card_"] [data-testid="stButton"] button:focus-visible {
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        color: #5b21b6 !important;
    }
    [class*="st-key-lot_summary_card_"] .lot-detail-reimbursement-row {
        margin-top: 0.68rem;
    }
    @media (max-width: 768px) {
        [class*="st-key-lot_summary_card_"] {
            padding: 0.72rem 0.78rem 0.76rem;
        }
    }
    """


def render_lot_summary_card(st, *, lot, all_lots, lot_index, status, title, active, money):
    """Render one visual card containing its clickable header and reimbursement."""
    prefix = "▼" if active else "›"
    with st.container(key=f"lot_summary_card_{status}_{lot_index}"):
        clicked = st.button(
            f"{prefix} {title}",
            key=f"lot_row_{lot_index}",
            width="stretch",
            type="secondary",
        )
        st.markdown(lot_progress_html(lot, all_lots, lot_index, money), unsafe_allow_html=True)
    return clicked

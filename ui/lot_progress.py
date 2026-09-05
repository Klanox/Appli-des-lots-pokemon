"""Compact two-phase lot progress, without mutating inventory."""

from html import escape

from core.brocante import lot_reimbursement


def lot_progress(lot, all_lots=(), lot_index=None):
    gauge = lot_reimbursement(lot, lot_index)
    cards = lot.get("cards", [])
    total = sum(max(int(card.get("quantity", 0) or 0), 0) for card in cards)
    sold = sum(min(max(int(card.get("sold_quantity", 0) or 0), 0),
                   max(int(card.get("quantity", 0) or 0), 0)) for card in cards)
    # Storage copies retain the source lot UID; transfers themselves are not sales.
    uid = lot.get("lot_uid")
    transferred = sum(max(int(card.get("stored_quantity", 0) or 0), 0) for card in cards)
    if uid and transferred:
        storage_sales = sum(max(int(card.get("sold_quantity", 0) or 0), 0)
                            for other in all_lots if other is not lot
                            for card in other.get("cards", [])
                            if card.get("stored_from_lot_uid") == uid)
        sold += min(storage_sales, transferred)
    sold = min(sold, total)
    reimbursed = gauge["available"] and gauge["recovered"] >= gauge["cost"]
    phase = "complete" if total > 0 and sold == total else (
        "repayment" if gauge["available"] and not reimbursed else "sales")
    pct = min(max(float(gauge.get("pct") or 0), 0), 100) if phase == "repayment" else (
        sold / total * 100 if total else 0)
    return {**gauge, "phase": phase, "sold": sold, "total": total,
            "progress": pct, "reimbursed": reimbursed}


def lot_progress_html(lot, all_lots, lot_index, money):
    state = lot_progress(lot, all_lots, lot_index)
    sold, total = state["sold"], state["total"]
    if state["phase"] == "repayment":
        label = f'{money(state["recovered"])} / {money(state["cost"])} · {state["progress"]:.0f} % remboursé'
        color = "#7c3aed"
    elif state["phase"] == "complete":
        label = f"✓ Lot terminé · {sold} / {total} vendues"
        if state["available"] and not state["reimbursed"]:
            label += f' · {money(state["remaining"])} non remboursés'
        color = "#15803d"
    else:
        prefix = "✓ Remboursé · " if state["reimbursed"] else ""
        label = f"{prefix}{sold} / {total} cartes vendues" if total else f"{prefix}Aucune carte suivie"
        if not state["available"]:
            label += " · Coût non renseigné"
        color = "#2563eb"
    if total == 0 and state["phase"] != "repayment":
        return f'<div class="lot-detail-reimbursement-row"><span>{escape(label)}</span></div>'
    return (
        '<div class="lot-detail-reimbursement-row">'
        f'<span>{escape(label)}</span>'
        f'<div class="lot-detail-reimbursement-track" role="progressbar" aria-label="{escape(label, quote=True)}" '
        f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{state["progress"]:.1f}">'
        f'<span style="width:{state["progress"]:.1f}%;background:{color}"></span></div></div>'
    )

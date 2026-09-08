"""Isolated visual fixture for the real Lots summary-card renderer."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui.lot_progress import lot_purchase_summary, lot_summary_card_css, render_lot_summary_card


def money(value):
    return f"{float(value):,.2f} €".replace(",", " ").replace(".", ",")


st.set_page_config(page_title="Lots fixture", layout="wide")
st.markdown(
    f"""
    <style>
    {lot_summary_card_css()}
    .block-container {{max-width: 1180px; padding-top: 1.5rem;}}
    .lot-detail-reimbursement-row {{
        display:grid; gap:0.32rem; width:min(100%,420px); font-size:0.85rem;
        font-weight:650; overflow-wrap:anywhere;
    }}
    .lot-detail-reimbursement-track {{
        box-sizing:border-box; height:8px; padding:1px; overflow:hidden;
        border-radius:6px; border:1px solid #cbd5e1; background:#e5e7eb;
    }}
    .lot-detail-reimbursement-track span {{display:block;height:100%;border-radius:inherit;}}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Lots")
lots = []
for index, pct in enumerate((50, 85, 126, 220)):
    cost = 100.0
    lots.append(
        {
            "lot_uid": f"fixture-{pct}",
            "nom": f"Lot test {pct} %",
            "prix_achat": cost,
            "valeur_totale": 136.05,
            "ventes": [{"price": pct}],
            "cards": [{"quantity": 2, "sold_quantity": 0, "sold_entries": []}],
        }
    )

for index, lot in enumerate(lots):
    pct = int(lot["ventes"][0]["price"])
    active = st.session_state.get("fixture_active_lot") == index
    title = f"{'🟢' if pct >= 100 else '🔴'} {lot['nom']} - {lot_purchase_summary(lot, money)}"
    if render_lot_summary_card(
        st,
        lot=lot,
        all_lots=lots,
        lot_index=index,
        status="profitable" if pct >= 100 else "not-profitable",
        title=title,
        active=active,
        money=money,
    ):
        st.session_state["fixture_active_lot"] = None if active else index
        st.rerun()
    if active:
        st.caption("Détail du lot ouvert")

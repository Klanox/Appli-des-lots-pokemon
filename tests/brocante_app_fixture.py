"""Isolated Streamlit smoke fixture: all persistence is session-memory only.

Run: python -m streamlit run tests/brocante_app_fixture.py
"""
import ast
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import streamlit as st
from core import sales_actions
from core.brocante import make_session, start_session, close_session, record_transaction
from logic import calc_cout_lot, effective_purchase_price, cp
from services import brocante_data, vinted_drops_service
from ui.pages import brocante, sales
from ui.theme import inject_theme, inject_functional_css, inject_mobile_overrides, render_page_header
from ui.card_display import img_with_fallback
from utils import fp, normalize_name

st.set_page_config(layout="wide")
mobile = st.query_params.get("mobile") == "1"
st.markdown(inject_theme(mobile=mobile) + inject_functional_css() + inject_mobile_overrides(), unsafe_allow_html=True)

# Load only pure application helper definitions, never execute application startup.
names = {"new_uid", "card_available_qty", "resolve_lot_idx", "resolve_card_ref", "is_trade_lot", "is_storage_lot", "ensure_trade_lot"}
tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), "fixture_helpers", "exec"))

if "fixture_stock" not in st.session_state:
    cards = [{"card_uid": f"c{i}", "name": name, "number": str(i), "set": "Set de Base", "id": f"base1-{i}",
              "quantity": 5, "sold_quantity": 0, "suggested_price": 10, "purchase_price": 4,
              "image_url": "https://assets.tcgdex.net/fr/base/base1/58/high.webp", "lang": "fr", "sold_entries": []}
             for i, name in enumerate(["Pikachu", "Pichu", "Rayquaza", "Mewtwo"], 1)]
    st.session_state["fixture_stock"] = {"lots": [{"lot_uid": "l1", "nom": "Cartes de test", "cards": cards,
                                                  "prix_achat": 80, "cost_basis_method": "per_card", "ventes": []}]}
    event = make_session("Brocante Auray", "2026-09-06", "Place du marché", initial_cash=50, goals={"ca": 200, "cards": 20})
    event["id"] = "smoke-event"
    old = make_session("Brocante précédente", "2026-08-30", "Centre-ville", initial_cash=50)
    record_transaction(old, {"transaction_id": "legacy", "amount": 120, "physical_quantity": 12, "payment_method": "Espèces", "cost_basis_known": True, "cost_basis": 40})
    close_session(old, 170)
    st.session_state["fixture_events"] = {"sessions": [event, old]}
    if st.query_params.get("preparing") != "1":
        start_session(st.session_state["fixture_events"], event["id"], force=True)
    st.session_state["cards_index"] = {normalize_name(c["name"]): [(c, c["set"], "base1")] for c in cards}


def ld():
    return deepcopy(st.session_state["fixture_stock"])


def sd(value):
    st.session_state["fixture_stock"] = deepcopy(value)


def load_events():
    return deepcopy(st.session_state["fixture_events"])


def save_events(value):
    st.session_state["fixture_events"] = deepcopy(value)


def ecd(card, set_name, lang="fr"):
    return {**deepcopy(card), "set": set_name, "lang": lang}


def noop(*args, **kwargs):
    return None


brocante.load_brocantes = brocante_data.load_brocantes = sales.load_brocantes = sales_actions.load_brocantes = load_events
brocante.save_brocantes = brocante_data.save_brocantes = sales_actions.save_brocantes = save_events
if st.query_params.get("apptest") == "1":
    # AppTest does not mount v2 browser components; real-browser smoke uses them.
    def test_search(label, *, key, placeholder="", **kwargs):
        return st.text_input(label, key=key, placeholder=placeholder)
    brocante.inventory_live_search = sales.inventory_live_search = test_search
vinted_drops_service.load_vinted_drops = lambda: {"drops": []}
vinted_drops_service.link_sale_to_vinted_drop_if_applicable = sales_actions.link_sale_to_vinted_drop_if_applicable = noop
context = {**globals(), "save_activity_state": noop, "run_html": noop, "proxy_img": lambda value: value,
           "is_mobile_mode": lambda: mobile, "migrate_open_trade_cards": noop}
sales_actions.configure_sales_actions(context)
for name in ("scu_many", "bulk_cart_add", "bulk_cart_remove", "bulk_cart_clear", "bulk_cart_increment", "bulk_cart_pop",
             "bulk_cart_set_quantity", "bulk_sale_prepare", "scroll_to_cart_prepare", "bulk_cart_add_off_stock"):
    context[name] = getattr(sales_actions, name)
with st.sidebar:
    st.markdown("## PokéStock")
    st.caption("Données de démonstration isolées")
brocante.render_brocante_page(context)

from __future__ import annotations

import json
import os
import re
from collections import Counter, OrderedDict
from datetime import datetime, timedelta

import streamlit as st

from services.vinted_drops_service import (
    DROP_ITEM_STATUSES,
    add_card_to_drop,
    add_cards_to_drop,
    card_is_in_drop,
    create_drop,
    delete_drop,
    drop_item_status,
    drop_item_status_label,
    drop_card_key,
    filter_drop_cards,
    find_drop,
    launch_drop,
    load_vinted_drops,
    remove_card_from_drop,
    rename_drop,
    resolve_drop_cards_from_data,
    save_vinted_drops,
    set_drop_card_status,
    toggle_drop_card_posted,
    update_drop_channel,
)
from services.vinted_channels import VINTED_CHANNELS, normalize_vinted_channel
from services.vinted_listing_service import (
    filter_cards_for_listing,
    full_card_number,
    listing_price_text,
    prepare_listing,
    suggested_price,
)
from services.custom_card_image_service import resolve_custom_card_image
from services.card_identity import card_identity_fingerprint
from ui.badges import card_stamp_label
from ui.vinted_drop_virtual_grid import render_vinted_drop_virtual_grid


def _ui_text(value, fallback=""):
    text = str(value or fallback).strip()
    text = text.replace("\ufffd", "")
    text = re.sub(r"^\?+\s*", "", text)
    text = re.sub(r"\s+\?+\s*", " ", text)
    return " ".join(text.split())


def _card_image(card, proxy_img_func=None):
    candidates = []

    def add_candidate(value):
        value = str(value or "").strip()
        if not value or value == "__placeholder__":
            return
        if value.startswith(("card_images/", "card_images\\")) or os.path.exists(value):
            if not os.path.exists(value):
                return
        if value not in candidates:
            candidates.append(value)

    for key in ("manual_image_path", "manual_image_url", "resolved_collection_image_url"):
        add_candidate(card.get(key))
    for key in ("image_path", "local_image_path"):
        add_candidate(card.get(key))
    for key in ("image_url", "image_url_en"):
        add_candidate(card.get(key))

    try:
        add_candidate(resolve_custom_card_image(card))
    except Exception:
        pass

    if not candidates:
        return ""
    image = candidates[0]
    if proxy_img_func:
        try:
            return proxy_img_func(image)
        except Exception:
            return image
    return image


def _lot_name(lot):
    return _ui_text(lot.get("name") or lot.get("nom"), "Lot sans nom")


def _card_number(card):
    return full_card_number(card)


def _card_set(card):
    return _ui_text(card.get("set") or card.get("serie") or card.get("extension"), "")


def _card_condition(card):
    return _ui_text(card.get("condition") or card.get("etat"), "")


def _card_display_title(card):
    number = _card_number(card)
    name = _ui_text(card.get("name"), "Carte Pokémon")
    return f"{name} {number}".strip()


def _card_key(card):
    return "::".join(
        [
            str(card.get("lot_uid") or ""),
            str(card.get("card_uid") or ""),
            str(card.get("lot_idx") or 0),
            str(card.get("card_idx") or 0),
            str(card.get("name") or ""),
            str(card.get("number") or ""),
        ]
    )


def _card_uid(card, lot_idx, card_idx):
    return str(card.get("uid") or card.get("card_uid") or f"{lot_idx}:{card_idx}")


def _inject_vinted_styles():
    st.markdown(
        """
<style>
.ps-vinted-subtitle {
    color:#64748b;
    font-size:.86rem;
    margin:-.2rem 0 .75rem;
}
.ps-vinted-step-nav {
    display:flex;
    flex-wrap:wrap;
    gap:.48rem;
    margin:.15rem 0 .9rem;
}
.ps-vinted-pill {
    display:inline-flex;
    align-items:center;
    gap:.35rem;
    padding:.26rem .58rem;
    border-radius:999px;
    background:#eef2ff;
    color:#3730a3;
    font-weight:800;
    font-size:.76rem;
}
.ps-vinted-muted-panel {
    border:1px solid rgba(129,140,248,.22);
    border-radius:12px;
    background:linear-gradient(135deg, rgba(248,250,252,.96), rgba(238,242,255,.62));
    padding:1rem;
    color:#475569;
    font-weight:700;
}
.ps-vinted-kpi-grid {
    display:grid;
    grid-template-columns:repeat(4, minmax(0, 1fr));
    gap:.65rem;
    margin:.65rem 0 .9rem;
}
.ps-vinted-kpi {
    border:1px solid rgba(129,140,248,.22);
    border-radius:12px;
    background:#fff;
    padding:.75rem;
}
.ps-vinted-kpi span {
    display:block;
    color:#64748b;
    font-size:.72rem;
    font-weight:800;
}
.ps-vinted-kpi strong {
    display:block;
    color:#0f172a;
    font-size:1.05rem;
    margin-top:.2rem;
}
.ps-vinted-drop-head {
    padding:.86rem 1rem;
    border:1px solid rgba(99,102,241,.32);
    border-radius:12px;
    background:linear-gradient(135deg, rgba(238,242,255,.98), rgba(255,255,255,.96));
    margin:.2rem 0 .85rem;
    box-shadow:0 10px 24px rgba(79,70,229,.08);
}
.ps-vinted-drop-head strong {
    display:block;
    color:#0f172a;
    font-size:1.02rem;
    line-height:1.2;
}
.ps-vinted-drop-head span {
    color:#64748b;
    font-size:.82rem;
    font-weight:700;
}
.ps-vinted-drop-meta {
    display:flex;
    align-items:center;
    flex-wrap:wrap;
    gap:.42rem;
    margin-top:.34rem;
}
.ps-vinted-channel {
    display:inline-flex;
    align-items:center;
    border-radius:999px;
    padding:.16rem .52rem;
    border:1px solid #c7d2fe;
    background:#eef2ff;
    color:#3730a3 !important;
    font-size:.72rem !important;
    font-weight:900 !important;
}
.ps-vinted-channel-dexify {
    border-color:#bfdbfe;
    background:#eff6ff;
    color:#1d4ed8 !important;
}
.ps-vinted-channel-pokedeal {
    border-color:#ddd6fe;
    background:#f5f3ff;
    color:#6d28d9 !important;
}
.ps-vinted-channel-choppetacarte {
    border-color:#fed7aa;
    background:#fff7ed;
    color:#c2410c !important;
}
.ps-vinted-section-title {
    display:flex;
    align-items:center;
    gap:.42rem;
    margin:.85rem 0 .45rem;
    color:#0f172a;
    font-size:.98rem;
    font-weight:900;
}
.ps-vinted-section-title::before,
.ps-vinted-lot-title::before {
    content:"";
    width:.38rem;
    height:.38rem;
    border-radius:999px;
    background:#7c3aed;
    box-shadow:0 0 0 4px rgba(124,58,237,.12);
}
.ps-vinted-lot-title {
    display:flex;
    align-items:center;
    gap:.42rem;
    margin:1rem 0 .45rem;
    color:#0f172a;
    font-size:.92rem;
    font-weight:900;
}
.ps-vinted-card {
    min-height:100%;
    display:flex;
    flex-direction:column;
    gap:.42rem;
    border:1px solid rgba(148,163,184,.26);
    border-radius:10px;
    background:#fff;
    padding:.5rem;
    box-shadow:0 3px 12px rgba(15,23,42,.06);
}
.ps-vinted-img {
    width:100%;
    aspect-ratio:.72;
    border-radius:9px;
    background:#f8fafc;
    border:1px solid rgba(203,213,225,.9);
    overflow:hidden;
    display:flex;
    align-items:center;
    justify-content:center;
    color:#64748b;
    font-size:.72rem;
    font-weight:800;
    text-align:center;
}
.ps-vinted-img img {
    width:100%;
    height:100%;
    display:block;
    object-fit:cover;
}
.ps-vinted-name {
    min-height:2.25rem;
    color:#0f172a;
    font-size:.82rem;
    font-weight:900;
    line-height:1.22;
    display:-webkit-box;
    -webkit-line-clamp:2;
    -webkit-box-orient:vertical;
    overflow:hidden;
}
.ps-vinted-meta {
    color:#64748b;
    font-size:.7rem;
    line-height:1.18;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}
.ps-vinted-price {
    color:#334155;
    font-size:.74rem;
    font-weight:800;
}
.ps-vinted-badge {
    display:inline-flex;
    width:max-content;
    max-width:100%;
    border-radius:999px;
    padding:.18rem .45rem;
    background:#eef2ff;
    color:#3730a3;
    font-size:.65rem;
    font-weight:900;
}
.ps-vinted-badge.ok {
    background:#dcfce7;
    color:#166534;
}
.ps-vinted-badge.warn {
    background:#fee2e2;
    color:#991b1b;
}
.ps-vinted-badge.duplicate {
    background:#ffedd5;
    color:#c2410c;
    border:1px solid #fed7aa;
}
.ps-vinted-badge.stamp {
    background:#fdf2f8;
    color:#db2777;
    border:1px solid #fbcfe8;
}
.ps-vinted-badge.status-to-photograph {
    background:#e0f2fe;
    color:#0369a1;
    border:1px solid #bae6fd;
}
.ps-vinted-badge.status-needs-review {
    background:#ffedd5;
    color:#c2410c;
    border:1px solid #fed7aa;
}
.ps-vinted-badge.status-sorted {
    background:#ede9fe;
    color:#6d28d9;
    border:1px solid #ddd6fe;
}
.ps-vinted-badge.status-to-prepare {
    background:#f3e8ff;
    color:#7e22ce;
    border:1px solid #e9d5ff;
}
.ps-vinted-badge.status-draft-ready {
    background:#e0e7ff;
    color:#4338ca;
    border:1px solid #c7d2fe;
}
.ps-vinted-badge.status-online {
    background:#dcfce7;
    color:#15803d;
    border:1px solid #bbf7d0;
}
.ps-vinted-badge.status-sold {
    background:#bbf7d0;
    color:#166534;
    border:1px solid #86efac;
}
.ps-vinted-actions {
    margin-top:auto;
}
.ps-vinted-qty-line {
    display:flex;
    align-items:center;
    justify-content:center;
    gap:.28rem;
    color:#475569;
    font-size:.72rem;
    font-weight:800;
}
[data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_"] {
    gap:10px !important;
    align-items:stretch !important;
}
[data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_"] > [data-testid="stLayoutWrapper"] {
    flex:0 0 calc((100% - 50px) / 6) !important;
    max-width:calc((100% - 50px) / 6) !important;
    min-width:0 !important;
}
[data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_drop_cards_"] > [data-testid="stLayoutWrapper"] {
    flex:0 0 calc((100% - 70px) / 8) !important;
    max-width:calc((100% - 70px) / 8) !important;
}
div[class*="st-key-vinted_grid_"] button {
    min-height:30px !important;
    padding:.2rem .4rem !important;
}
div[class*="st-key-vinted_drop_step_"] button {
    min-height:42px !important;
    padding:.48rem .7rem !important;
    border-radius:999px !important;
    border:1px solid rgba(129,140,248,.34) !important;
    background:linear-gradient(135deg, rgba(255,255,255,.98), rgba(248,250,255,.92)) !important;
    color:#1e293b !important;
    font-weight:850 !important;
    box-shadow:0 2px 8px rgba(15,23,42,.035) !important;
}
div[class*="st-key-vinted_drop_step_"] button:hover {
    border-color:rgba(124,58,237,.52) !important;
    background:linear-gradient(135deg, rgba(245,243,255,1), rgba(238,242,255,.95)) !important;
    color:#4c1d95 !important;
}
div[class*="st-key-vinted_drop_step_"] button p {
    white-space:normal !important;
    line-height:1.12 !important;
}
div[class*="st-key-create_vinted_drop"] button,
div[class*="st-key-vinted_add"] button,
div[class*="st-key-draft_ready_drop_card"] button,
div[class*="st-key-launch_drop"] button {
    background:#6d5dfc !important;
    border-color:#6d5dfc !important;
    color:#fff !important;
}
div[class*="st-key-create_vinted_drop"] button:hover,
div[class*="st-key-vinted_add"] button:hover,
div[class*="st-key-draft_ready_drop_card"] button:hover,
div[class*="st-key-launch_drop"] button:hover {
    background:#5b4bea !important;
    border-color:#5b4bea !important;
    color:#fff !important;
}
div[class*="st-key-vinted_drop_drawer_header_"] button {
    display:flex !important;
    align-items:center !important;
    justify-content:flex-start !important;
    text-align:left !important;
    min-height:48px !important;
    padding:.55rem .82rem !important;
    border:1px solid rgba(129,140,248,.28) !important;
    border-radius:12px !important;
    background:linear-gradient(135deg, rgba(255,255,255,.98), rgba(248,250,255,.96)) !important;
    color:#0f172a !important;
    font-weight:800 !important;
    box-shadow:0 2px 8px rgba(15,23,42,.035) !important;
}
div[class*="st-key-vinted_drop_drawer_header_"] button:hover {
    border-color:rgba(99,102,241,.42) !important;
    background:linear-gradient(135deg, rgba(255,255,255,1), rgba(238,242,255,.72)) !important;
}
div[class*="st-key-vinted_drop_drawer_header_"] {
    margin:.35rem 0 .28rem !important;
}
.ps-vinted-progress-panel {
    border:1px solid rgba(129,140,248,.24);
    border-radius:14px;
    background:linear-gradient(135deg, rgba(255,255,255,.98), rgba(245,243,255,.78));
    padding:.82rem .95rem;
    margin:.45rem 0 .75rem;
    box-shadow:0 8px 24px rgba(79,70,229,.07);
}
.ps-vinted-progress-main {
    color:#0f172a;
    font-size:1.05rem;
    font-weight:950;
    line-height:1.2;
}
.ps-vinted-progress-sub {
    color:#64748b;
    font-size:.82rem;
    font-weight:800;
    margin-top:.18rem;
}
.ps-vinted-current-card {
    border:1px solid rgba(129,140,248,.22);
    border-radius:14px;
    background:#fff;
    padding:.8rem;
    box-shadow:0 8px 22px rgba(15,23,42,.055);
}
.ps-vinted-current-title {
    color:#0f172a;
    font-size:1.05rem;
    font-weight:950;
    line-height:1.2;
}
.ps-vinted-current-meta {
    color:#64748b;
    font-size:.84rem;
    font-weight:760;
    margin-top:.2rem;
}
@media (max-width:768px) {
    .ps-vinted-drop-head {
        padding:.7rem .78rem;
        border-radius:10px;
    }
    .ps-vinted-card {
        padding:.42rem;
        border-radius:9px;
    }
    .ps-vinted-name {
        font-size:.76rem;
        min-height:2.05rem;
    }
    .ps-vinted-meta,
    .ps-vinted-price {
        font-size:.66rem;
    }
    .ps-vinted-kpi-grid {
        grid-template-columns:repeat(2, minmax(0, 1fr));
    }
    [data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_"] {
        gap:8px !important;
    }
    [data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_"] > [data-testid="stLayoutWrapper"] {
        flex:0 0 calc((100% - 8px) / 2) !important;
        max-width:calc((100% - 8px) / 2) !important;
    }
}
</style>
""",
        unsafe_allow_html=True,
    )


def _html_escape(value):
    import html

    return html.escape(str(value or ""), quote=True)


def _grid_columns(mobile):
    return 2 if mobile else 6


def _drop_cards_grid_columns(mobile):
    return 2 if mobile else 8


DROP_WORKFLOW_STEPS = (
    "Choix des cartes",
    "Tri des photos",
    "Vérification",
    "Création des annonces",
    "Analyse des drops",
)


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except Exception:
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(value or default)
    except Exception:
        return int(default)


def _parse_dt(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _duration_label(delta):
    if delta is None:
        return "N/A"
    total_seconds = max(0, int(delta.total_seconds()))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"J+{days}" + (f" {hours}h" if hours else "")
    if hours:
        return f"{hours}h{minutes:02d}"
    return f"{minutes} min"


def _drop_step_label(index, step):
    return f"Étape {index + 1} · {step}"


def _render_drop_step_nav(mobile):
    if st.session_state.get("vinted_drop_step") not in DROP_WORKFLOW_STEPS:
        st.session_state["vinted_drop_step"] = DROP_WORKFLOW_STEPS[0]
    active_step = st.session_state.get("vinted_drop_step", DROP_WORKFLOW_STEPS[0])
    active_index = DROP_WORKFLOW_STEPS.index(active_step)
    st.markdown(
        f"""
<style>
div[class*="st-key-vinted_drop_step_{active_index}"] button {{
    background:linear-gradient(135deg, #6d5dfc, #7c3aed) !important;
    border-color:#6d5dfc !important;
    color:#fff !important;
    box-shadow:0 10px 22px rgba(109,93,252,.26) !important;
}}
div[class*="st-key-vinted_drop_step_{active_index}"] button:hover {{
    background:linear-gradient(135deg, #5b4bea, #6d28d9) !important;
    border-color:#5b4bea !important;
    color:#fff !important;
}}
</style>
""",
        unsafe_allow_html=True,
    )
    indexed_steps = list(enumerate(DROP_WORKFLOW_STEPS))
    rows = [indexed_steps[i : i + 2] for i in range(0, len(indexed_steps), 2)] if mobile else [indexed_steps]
    for row in rows:
        cols = st.columns(len(row))
        for col, (idx, step) in zip(cols, row):
            with col:
                if st.button(_drop_step_label(idx, step), key=f"vinted_drop_step_{idx}", width="stretch"):
                    if st.session_state.get("vinted_drop_step") != step:
                        st.session_state["vinted_drop_step"] = step
                        st.rerun()
    return st.session_state.get("vinted_drop_step", DROP_WORKFLOW_STEPS[0])


def _drop_channel_class(channel):
    channel = normalize_vinted_channel(channel)
    if channel == "Dexify":
        return "ps-vinted-channel-dexify"
    if channel == "Pokédeal":
        return "ps-vinted-channel-pokedeal"
    if channel == "ChoppeTaCarte":
        return "ps-vinted-channel-choppetacarte"
    return ""


def _drop_status_badge_class(status):
    return "status-" + str(status or "").replace("_", "-")


def _drawer_open_key(scope):
    return f"vinted_drop_drawer_open_{scope}"


def _render_drop_drawer_header(scope, label, default_open=True):
    state_key = _drawer_open_key(scope)
    if state_key not in st.session_state:
        st.session_state[state_key] = bool(default_open)
    is_open = bool(st.session_state.get(state_key))
    chevron = "▾" if is_open else "▸"
    badge_css = ""
    badge_match = re.search(r"\(([^()]*)\)\s*$", str(label or ""))
    if badge_match:
        badge = _html_escape(badge_match.group(1))
        label = str(label or "")[: badge_match.start()].strip()
        badge_css = (
            f'div[class*="st-key-vinted_drop_drawer_toggle_{scope}"] button p::after {{'
            f'content:"{badge}";display:inline-flex;align-items:center;margin-left:.55rem;'
            f'padding:.12rem .48rem;border-radius:999px;background:#eef2ff;color:#3730a3;'
            f'border:1px solid #c7d2fe;font-size:.72rem;font-weight:900;'
            f'}}'
        )
    st.markdown(
        f"""
<style>
div[class*="st-key-vinted_drop_drawer_toggle_{scope}"] button::after {{
    content:"{chevron}";
    margin-left:auto;
    color:#4f46e5;
    font-size:1rem;
    font-weight:900;
}}
div[class*="st-key-vinted_drop_drawer_toggle_{scope}"] button p {{
    display:flex;
    align-items:center;
    flex:1;
    margin:0;
}}
{badge_css}
</style>
""",
        unsafe_allow_html=True,
    )
    with st.container(key=f"vinted_drop_drawer_header_{scope}"):
        if st.button(str(label or ""), key=f"vinted_drop_drawer_toggle_{scope}", width="stretch"):
            is_open = not is_open
            st.session_state[state_key] = is_open
    return is_open


def _chunked(items, size):
    items = list(items or [])
    for idx in range(0, len(items), max(1, size)):
        yield idx // max(1, size), items[idx : idx + max(1, size)]


def _group_cards_by_lot(cards):
    grouped = OrderedDict()
    for card in cards or []:
        key = str(card.get("lot_uid") or card.get("lot_idx") or card.get("lot_name") or "lot")
        if key not in grouped:
            grouped[key] = {"name": card.get("lot_name", "Lot"), "cards": []}
        grouped[key]["cards"].append(card)
    return grouped.values()


def _limit_key(scope):
    return f"vinted_{scope}_limit"


def _query_sig_key(scope):
    return f"vinted_{scope}_query_sig"


def _visible_limit(scope, query, mobile, total):
    key = _limit_key(scope)
    sig_key = _query_sig_key(scope)
    signature = str(query or "")
    initial = 12 if mobile else 24
    if st.session_state.get(sig_key) != signature:
        st.session_state[sig_key] = signature
        st.session_state[key] = min(initial, total)
    current = int(st.session_state.get(key, initial) or initial)
    current = min(max(initial, current), total)
    st.session_state[key] = current
    return current


def _show_more(scope, mobile, total, label="Afficher plus"):
    key = _limit_key(scope)
    current = int(st.session_state.get(key, 0) or 0)
    if current >= total:
        return
    step = 12 if mobile else 24
    if st.button(label, key=f"vinted_show_more_{scope}", width="stretch"):
        st.session_state[key] = min(total, current + step)
        st.rerun()


def _qty_state_key(scope, card):
    return f"vinted_qty_{scope}_{_safe_js_id(card.get('_listing_key') or drop_card_key(card))}"


def _selected_quantity(scope, card):
    key = _qty_state_key(scope, card)
    max_qty = max(1, int(card.get("available_qty", 1) or 1))
    current = int(st.session_state.get(key, 1) or 1)
    current = min(max(1, current), max_qty)
    st.session_state[key] = current
    return current, max_qty, key


def _adjust_quantity(scope, card, delta):
    current, max_qty, key = _selected_quantity(scope, card)
    st.session_state[key] = min(max(1, current + delta), max_qty)


def _card_static_html(
    card,
    proxy_img_func,
    fp_func,
    *,
    badge="",
    badge_class="",
    duplicate_badge="",
    unavailable=False,
    drop_card=False,
):
    img = _card_image(card, proxy_img_func)
    if img:
        img_html = f'<img src="{_html_escape(img)}" loading="lazy" decoding="async" alt="">'
    else:
        img_html = "Image<br>absente"
    meta_bits = []
    if _card_set(card):
        meta_bits.append(_card_set(card))
    if _card_number(card):
        meta_bits.append(f"#{_card_number(card)}")
    if drop_card and card.get("lot_name"):
        meta_bits.append(str(card.get("lot_name")))
    meta = " · ".join(meta_bits)
    price = suggested_price(card)
    price_label = fp_func(price) if price else "Prix à définir"
    stock_label = f"Stock x{int(card.get('available_qty', 0) or 0)}"
    if drop_card:
        qty = max(1, int(card.get("drop_quantity", card.get("quantity", 1)) or 1))
        added_price = float(card.get("price_at_add", 0) or 0)
        price_label = f"Ajout {fp_func(added_price)} × {qty}"
        current = suggested_price(card)
        if current and abs(current - added_price) >= 0.01:
            price_label += f" · Actuel {fp_func(current)}"
        stock_label = "Disponible" if not unavailable else "Indisponible"
    badge_html = ""
    if badge:
        cls = badge_class or ("warn" if unavailable else ("ok" if "POST" in badge.upper() else ""))
        badge_html = f'<span class="ps-vinted-badge {cls}">{_html_escape(badge)}</span>'
    duplicate_html = (
        f'<span class="ps-vinted-badge duplicate">{_html_escape(duplicate_badge)}</span>'
        if duplicate_badge
        else ""
    )
    stamp_label = card_stamp_label(card)
    stamp_html = f'<span class="ps-vinted-badge stamp">{_html_escape(stamp_label)}</span>' if stamp_label else ""
    return f"""
<div class="ps-vinted-card">
  <div class="ps-vinted-img">{img_html}</div>
  <div class="ps-vinted-name">{_html_escape(_card_display_title(card))}</div>
  <div class="ps-vinted-meta">{_html_escape(meta)}</div>
  <div class="ps-vinted-price">{_html_escape(price_label)} · {_html_escape(stock_label)}</div>
  {stamp_html}
  {badge_html}
  {duplicate_html}
</div>
"""


def _available_cards(d, card_available_qty_func, is_collection_system_lot_func):
    options = []
    for lot_idx, lot in enumerate(d.get("lots", [])):
        if is_collection_system_lot_func(lot):
            continue
        lot_name = _lot_name(lot)
        lot_uid = str(lot.get("uid") or lot.get("lot_uid") or f"lot-{lot_idx}")
        for card_idx, card in enumerate(lot.get("cards", [])):
            try:
                available_qty = int(card_available_qty_func(card))
            except Exception:
                available_qty = int(card.get("quantity", 0) or 0)
            if available_qty <= 0:
                continue

            item = dict(card)
            item["available_qty"] = available_qty
            item["lot_name"] = lot_name
            item["lot_idx"] = lot_idx
            item["card_idx"] = card_idx
            item["lot_uid"] = lot_uid
            item["card_uid"] = _card_uid(card, lot_idx, card_idx)
            item["_listing_key"] = _card_key(item)
            item["_drop_card_key"] = drop_card_key(item)
            item["identity_fingerprint"] = card_identity_fingerprint(item)
            options.append(item)
    return options


def _sync_listing_text(selected_cards, listing_type, fp_func):
    prepared = prepare_listing(selected_cards, listing_type)
    signature = prepared["signature"]
    if signature != st.session_state.get("vinted_listing_signature"):
        st.session_state["vinted_listing_title"] = prepared["title"]
        st.session_state["vinted_listing_description"] = prepared["description"]
        st.session_state["vinted_listing_price"] = listing_price_text(selected_cards, fp_func)
        st.session_state["vinted_listing_signature"] = signature
    return prepared


def _reset_vinted_form():
    for key in (
        "vinted_search_query",
        "vinted_drop_add_query",
        "vinted_drop_filter_query",
        "vinted_selected_keys",
        "vinted_listing_title",
        "vinted_listing_description",
        "vinted_listing_price",
        "vinted_listing_signature",
        "vinted_copy_buffer",
    ):
        st.session_state.pop(key, None)
    for key in list(st.session_state.keys()):
        if str(key).startswith("vinted_multi_pick_"):
            st.session_state.pop(key, None)
    st.rerun()


def _select_cards(cards):
    st.session_state["vinted_selected_keys"] = [card["_listing_key"] for card in cards]
    st.session_state.pop("vinted_listing_signature", None)


def _active_drop_id(drops_data):
    drops = drops_data.get("drops", [])
    current = st.session_state.get("vinted_active_drop_id")
    if current and any(drop.get("id") == current for drop in drops):
        return current
    if drops:
        st.session_state["vinted_active_drop_id"] = drops[0].get("id")
        return drops[0].get("id")
    return ""


def _render_thumb(card, proxy_img_func, width=92):
    img = _card_image(card, proxy_img_func)
    if img:
        st.image(img, width=width)
    else:
        st.markdown(
            f"<div style='width:{width}px;height:{int(width*1.38)}px;border:1px solid #d8e2ef;"
            "border-radius:8px;display:flex;align-items:center;justify-content:center;"
            "color:#64748b;background:#f8fafc;font-size:.75rem;text-align:center;'>Image<br>absente</div>",
            unsafe_allow_html=True,
        )


def _card_details_text(card, fp_func):
    lines = []
    meta = []
    if _card_number(card):
        meta.append(f"#{_card_number(card)}")
    if _card_set(card):
        meta.append(_card_set(card))
    if _card_condition(card):
        meta.append(_card_condition(card))
    if meta:
        lines.append(" - ".join(meta))
    lines.append(f"Prix PokéStock : {fp_func(suggested_price(card)) if suggested_price(card) else 'à définir'}")
    lines.append(f"Lot : {card.get('lot_name', 'Lot')}")
    lines.append(f"Disponible : x{int(card.get('available_qty', 0) or 0)}")
    return lines


def _drop_choice_options(drops_data):
    return {drop.get("name", "Drop sans nom"): drop.get("id") for drop in drops_data.get("drops", [])}


def _card_with_drop_quantity(card, quantity):
    item = dict(card)
    item["drop_quantity"] = max(1, int(quantity or 1))
    return item


def _card_identity(card):
    return str(card.get("identity_fingerprint") or card_identity_fingerprint(card) or "")


def _drop_identity_counts(drop):
    counts = Counter()
    for ref in (drop or {}).get("cards", []) or []:
        fingerprint = _card_identity(ref)
        if fingerprint:
            counts[fingerprint] += 1
    return counts


def _drop_duplicate_extra_count(drop):
    return sum(count - 1 for count in _drop_identity_counts(drop).values() if count > 1)


def _candidate_duplicate_count(drop, card):
    fingerprint = _card_identity(card)
    if not fingerprint:
        return 0
    count = _drop_identity_counts(drop).get(fingerprint, 0)
    if card_is_in_drop(drop, card):
        count -= 1
    return max(0, count)


def _add_card_to_drop_action(drops_data, drop_id, card, quantity=1):
    added, duplicate = add_card_to_drop(drops_data, drop_id, _card_with_drop_quantity(card, quantity))
    if added:
        save_vinted_drops(drops_data)
        st.success("Carte ajoutée au drop.")
        st.rerun()
    if duplicate:
        st.warning("Cette carte est déjà dans ce drop.")


def _component_batch(result):
    if result is None:
        return {}
    batch = result.get("batch") if isinstance(result, dict) else getattr(result, "batch", None)
    return batch if isinstance(batch, dict) else {}


def _drop_grid_processed_batches_key(drop_id):
    return f"vinted_drop_processed_batches_{drop_id}"


def _drop_grid_committed_selection_token_key(drop_id):
    return f"vinted_drop_committed_selection_token_{drop_id}"


def _drop_grid_committed_selection_token(drop_id):
    return int(st.session_state.get(_drop_grid_committed_selection_token_key(drop_id), 0) or 0)


def _mark_drop_grid_batch_committed(drop_id, batch_id):
    key = _drop_grid_processed_batches_key(drop_id)
    batches = [str(value) for value in st.session_state.get(key, []) if value]
    batch_id = str(batch_id or "")
    if batch_id and batch_id not in batches:
        batches.append(batch_id)
    st.session_state[key] = batches[-100:]
    token_key = _drop_grid_committed_selection_token_key(drop_id)
    st.session_state[token_key] = _drop_grid_committed_selection_token(drop_id) + 1
    st.session_state["vinted_drop_grid_scroll_token"] = int(st.session_state.get("vinted_drop_grid_scroll_token", 0) or 0) + 1


def _process_drop_selection_batch(drops_data, active_drop, available_cards, batch):
    drop_id = active_drop.get("id") if active_drop else ""
    selections = batch.get("selections") if isinstance(batch, dict) else []
    batch_id = str(batch.get("id") or "") if isinstance(batch, dict) else ""
    if not drop_id or not batch_id or not isinstance(selections, list) or not selections:
        return 0, 0, 0
    processed_batches = {str(value) for value in st.session_state.get(_drop_grid_processed_batches_key(drop_id), [])}
    if batch_id in processed_batches:
        return 0, 0, 0
    card_by_key = {
        card.get("_drop_card_key") or drop_card_key(card): card
        for card in available_cards or []
    }
    added_count = 0
    duplicate_count = 0
    skipped_count = 0
    cards_to_add = []

    seen_keys = set()
    for selection in selections:
        if not isinstance(selection, dict):
            continue
        card_key = str(selection.get("card_key") or "")
        if not card_key or card_key in seen_keys:
            continue
        seen_keys.add(card_key)
        card = card_by_key.get(card_key)
        if not card:
            skipped_count += 1
            continue
        if card_is_in_drop(active_drop, card):
            duplicate_count += 1
            continue
        try:
            quantity = int(selection.get("quantity", 1) or 1)
        except Exception:
            quantity = 1
        max_qty = max(1, int(card.get("available_qty", 1) or 1))
        quantity = min(max(1, quantity), max_qty)
        cards_to_add.append(_card_with_drop_quantity(card, quantity))

    if cards_to_add:
        added_count, duplicate_count_from_service = add_cards_to_drop(drops_data, drop_id, cards_to_add)
        duplicate_count += duplicate_count_from_service
    _mark_drop_grid_batch_committed(drop_id, batch_id)
    if added_count:
        save_vinted_drops(drops_data)
    return len(seen_keys), added_count, duplicate_count + skipped_count


def _render_quantity_stepper(scope, card):
    current, max_qty, _ = _selected_quantity(scope, card)
    if max_qty <= 1:
        return current
    with st.container(horizontal=True, key=f"vinted_qty_line_{scope}_{_safe_js_id(card.get('_listing_key'))}"):
        st.markdown('<span class="ps-vinted-qty-line">Qté</span>', unsafe_allow_html=True)
        st.button(
            "−",
            key=f"vinted_qty_minus_{scope}_{_safe_js_id(card.get('_listing_key'))}",
            disabled=current <= 1,
            on_click=_adjust_quantity,
            args=(scope, card, -1),
        )
        st.markdown(f'<span class="ps-vinted-qty-line">{current}</span>', unsafe_allow_html=True)
        st.button(
            "＋",
            key=f"vinted_qty_plus_{scope}_{_safe_js_id(card.get('_listing_key'))}",
            disabled=current >= max_qty,
            on_click=_adjust_quantity,
            args=(scope, card, 1),
        )
    return current


def _render_available_card(
    card,
    *,
    scope,
    listing_type,
    selected_keys,
    drops_data,
    active_drop_id,
    proxy_img_func,
    fp_func,
    mode,
):
    key = card["_listing_key"]
    active_drop = find_drop(drops_data, active_drop_id) if active_drop_id else None
    already = bool(active_drop and card_is_in_drop(active_drop, card))
    duplicate_count = _candidate_duplicate_count(active_drop, card) if active_drop else 0
    duplicate_badge = ""
    if duplicate_count:
        duplicate_badge = f"⚠ Déjà présent ×{duplicate_count}" if duplicate_count > 1 else "⚠ Déjà présent dans le drop"
    st.markdown(
        _card_static_html(card, proxy_img_func, fp_func, duplicate_badge=duplicate_badge),
        unsafe_allow_html=True,
    )
    quantity = _render_quantity_stepper(scope, card)

    if mode == "classic":
        if listing_type == "Carte seule":
            if st.button("Sélectionner", key=f"vinted_pick_single_{scope}_{key}", width="stretch"):
                _select_cards([card])
                st.rerun()
        else:
            checkbox_key = f"vinted_multi_pick_{scope}_{key}"
            checked = st.checkbox("Sélectionner", key=checkbox_key, value=key in selected_keys)
            if checked and key not in selected_keys:
                selected_keys.append(key)
                st.session_state["vinted_selected_keys"] = selected_keys
                st.session_state.pop("vinted_listing_signature", None)
            elif not checked and key in selected_keys:
                selected_keys.remove(key)
                st.session_state["vinted_selected_keys"] = selected_keys
                st.session_state.pop("vinted_listing_signature", None)

    if active_drop_id:
        if st.button(
            "Déjà dans le drop" if already else "Ajouter au drop",
            key=f"vinted_add_to_drop_{scope}_{active_drop_id}_{key}",
            width="stretch",
            disabled=already,
        ):
            _add_card_to_drop_action(drops_data, active_drop_id, card, quantity)


def _render_grouped_available_grid(
    cards,
    *,
    scope,
    listing_type,
    selected_keys,
    drops_data,
    active_drop_id,
    proxy_img_func,
    fp_func,
    mobile,
    mode,
):
    cols_count = _grid_columns(mobile)
    for group_index, group in enumerate(_group_cards_by_lot(cards)):
        group_cards = group["cards"]
        if not group_cards:
            continue
        st.markdown(
            f'<div class="ps-vinted-lot-title">{_html_escape(group["name"])} · {len(group_cards)} carte(s)</div>',
            unsafe_allow_html=True,
        )
        for row_index, row in _chunked(group_cards, cols_count):
            with st.container(horizontal=True, key=f"vinted_grid_{scope}_{group_index}_{row_index}"):
                for card in row:
                    with st.container(key=f"vinted_card_{scope}_{_safe_js_id(card.get('_listing_key'))}"):
                        _render_available_card(
                            card,
                            scope=scope,
                            listing_type=listing_type,
                            selected_keys=selected_keys,
                            drops_data=drops_data,
                            active_drop_id=active_drop_id,
                            proxy_img_func=proxy_img_func,
                            fp_func=fp_func,
                            mode=mode,
                        )


def _filter_cards_for_display(cards, query):
    if not str(query or "").strip():
        return list(cards or [])
    return filter_cards_for_listing(cards, query, limit=len(cards or []))


def _drop_total_value(drop):
    total = 0.0
    for ref in drop.get("cards", []) or []:
        try:
            price = float(ref.get("price_at_add", 0) or 0)
        except Exception:
            price = 0.0
        try:
            quantity = int(ref.get("quantity", 1) or 1)
        except Exception:
            quantity = 1
        total += price * max(1, quantity)
    return total


def _drop_grid_groups(cards, proxy_img_func, fp_func):
    groups = []
    for group in _group_cards_by_lot(cards):
        payload_cards = []
        for card in group.get("cards", []) or []:
            img = _card_image(card, proxy_img_func)
            price = suggested_price(card)
            payload_cards.append(
                {
                    "card_key": card.get("_drop_card_key") or drop_card_key(card),
                    "card_uid": card.get("card_uid", ""),
                    "lot_uid": card.get("lot_uid", ""),
                    "lot_idx": card.get("lot_idx", 0),
                    "card_idx": card.get("card_idx", 0),
                    "name": _ui_text(card.get("name"), "Carte"),
                    "set": _card_set(card),
                    "number": _card_number(card),
                    "price": price,
                    "price_label": fp_func(price) if price else "Prix à définir",
                    "stock": int(card.get("available_qty", 0) or 0),
                    "image_url": img,
                    "stamp_label": card_stamp_label(card),
                    "duplicate_fingerprint": _card_identity(card),
                }
            )
        if payload_cards:
            first = payload_cards[0]
            groups.append(
                {
                    "lot_uid": first.get("lot_uid") or group.get("name"),
                    "lot_idx": first.get("lot_idx", 0),
                    "lot_name": group.get("name", "Lot"),
                    "cards": payload_cards,
                }
            )
    return groups


def _drop_scroll_top_token(active_drop_id, query):
    signature = f"{active_drop_id or ''}::{str(query or '')}"
    if st.session_state.get("vinted_drop_grid_signature") != signature:
        st.session_state["vinted_drop_grid_signature"] = signature
        st.session_state["vinted_drop_grid_scroll_token"] = int(st.session_state.get("vinted_drop_grid_scroll_token", 0) or 0) + 1
    return st.session_state.get("vinted_drop_grid_scroll_token", 0)


def _render_search_result(card, listing_type, selected_keys, proxy_img_func, fp_func, drops_data, active_drop_id, mobile=False):
    key = card["_listing_key"]
    with st.container(border=True):
        if mobile:
            img_col, info_col = st.columns([0.75, 2.25])
            action_col = st.container()
        else:
            img_col, info_col, action_col = st.columns([0.75, 2.5, 1.25])
        with img_col:
            _render_thumb(card, proxy_img_func, width=76 if mobile else 86)
        with info_col:
            st.markdown(f"**{_card_display_title(card)}**")
            for line in _card_details_text(card, fp_func):
                st.caption(line)
        with action_col:
            if listing_type == "Carte seule":
                if st.button("Sélectionner", key=f"vinted_pick_single_{key}", width="stretch"):
                    _select_cards([card])
                    st.rerun()
            else:
                checkbox_key = f"vinted_multi_pick_{key}"
                checked = st.checkbox("Sélectionner", key=checkbox_key, value=key in selected_keys)
                if checked and key not in selected_keys:
                    selected_keys.append(key)
                    st.session_state["vinted_selected_keys"] = selected_keys
                    st.session_state.pop("vinted_listing_signature", None)
                elif not checked and key in selected_keys:
                    selected_keys.remove(key)
                    st.session_state["vinted_selected_keys"] = selected_keys
                    st.session_state.pop("vinted_listing_signature", None)

            if active_drop_id:
                active_drop = find_drop(drops_data, active_drop_id)
                already = bool(active_drop and card_is_in_drop(active_drop, card))
                if st.button(
                    "Déjà dans le drop" if already else "Ajouter au drop",
                    key=f"vinted_add_result_to_drop_{active_drop_id}_{key}",
                    width="stretch",
                    disabled=already,
                ):
                    _add_card_to_drop_action(drops_data, active_drop_id, card)


def _safe_js_id(key):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(key))


def _copy_button(label, value, key, run_html_func=None, field_labels=None):
    field_labels = field_labels or []
    if run_html_func:
        button_id = f"copy_{_safe_js_id(key)}"
        js_labels = json.dumps(field_labels, ensure_ascii=False)
        js_fallback = json.dumps(value or "", ensure_ascii=False)
        run_html_func(
            f"""
<button id="{button_id}" type="button" style="
width:100%;min-height:38px;border:1px solid #d8e2ef;border-radius:8px;
background:#ffffff;color:#0f1f36;font-weight:700;cursor:pointer;">
{label}
</button>
<script>
(function() {{
  const btn = document.getElementById({json.dumps(button_id)});
  const labels = {js_labels};
  const fallback = {js_fallback};
  function currentText() {{
    const root = window.parent && window.parent.document ? window.parent.document : document;
    if (!labels.length) return fallback;
    const values = labels.map(label => {{
      const fields = Array.from(root.querySelectorAll('input, textarea'));
      const field = fields.find(el => el.getAttribute('aria-label') === label);
      return field ? field.value : '';
    }}).filter(Boolean);
    return values.length ? values.join('\\n\\n') : fallback;
  }}
  async function copyText(text) {{
    if (navigator.clipboard && window.isSecureContext) {{
      await navigator.clipboard.writeText(text);
      return true;
    }}
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  }}
  btn.addEventListener('click', async () => {{
    const original = btn.textContent;
    try {{
      await copyText(currentText());
      btn.textContent = 'Copié !';
    }} catch (e) {{
      btn.textContent = 'Copie manuelle';
    }}
    setTimeout(() => {{ btn.textContent = original; }}, 1400);
  }});
}})();
</script>
""",
            height=45,
        )
        return

    if st.button(label, key=key, disabled=not bool(value), width="stretch"):
        st.session_state["vinted_copy_buffer"] = value
        st.toast("Texte prêt à copier juste en dessous.")


def _render_listing_preview(selected_cards, proxy_img_func, run_html_func=None, mobile=False):
    st.subheader("Aperçu de l'annonce")
    if not selected_cards:
        st.caption("Sélectionne une carte ou prépare une carte depuis un drop pour générer l'aperçu.")
        return

    with st.container(border=True):
        if mobile:
            _render_thumb(selected_cards[0], proxy_img_func, width=145)
            if len(selected_cards) > 1:
                st.caption(f"+ {len(selected_cards) - 1} autre(s) carte(s)")
            st.link_button("Ouvrir Vinted", "https://www.vinted.fr/items/new", width="stretch")
            st.text_input("Titre", key="vinted_listing_title")
            _copy_button("Copier titre", st.session_state.get("vinted_listing_title", ""), "copy_vinted_title", run_html_func, ["Titre"])
            st.text_input("Prix", key="vinted_listing_price")
            _copy_button("Copier prix", st.session_state.get("vinted_listing_price", ""), "copy_vinted_price", run_html_func, ["Prix"])
            st.text_area("Description", key="vinted_listing_description", height=240)
            _copy_button("Copier description", st.session_state.get("vinted_listing_description", ""), "copy_vinted_description", run_html_func, ["Description"])
            _copy_button(
                "Copier titre + description",
                (
                    f"{st.session_state.get('vinted_listing_title', '')}\n\n"
                    f"{st.session_state.get('vinted_listing_description', '')}"
                ),
                "copy_vinted_all",
                run_html_func,
                ["Titre", "Description"],
            )
            if st.session_state.get("vinted_copy_buffer"):
                st.text_area("Copie manuelle", value=st.session_state["vinted_copy_buffer"], height=160)
            return

        img_col, text_col = st.columns([1, 2])
        with img_col:
            _render_thumb(selected_cards[0], proxy_img_func, width=210)
            if len(selected_cards) > 1:
                st.caption(f"+ {len(selected_cards) - 1} autre(s) carte(s)")
            st.link_button("Ouvrir Vinted", "https://www.vinted.fr/items/new", width="stretch")
        with text_col:
            title_col, title_btn_col = st.columns([3, 1])
            with title_col:
                st.text_input("Titre", key="vinted_listing_title")
            with title_btn_col:
                _copy_button(
                    "Copier titre",
                    st.session_state.get("vinted_listing_title", ""),
                    "copy_vinted_title",
                    run_html_func,
                    ["Titre"],
                )

            price_col, price_btn_col = st.columns([3, 1])
            with price_col:
                st.text_input("Prix", key="vinted_listing_price")
            with price_btn_col:
                _copy_button(
                    "Copier prix",
                    st.session_state.get("vinted_listing_price", ""),
                    "copy_vinted_price",
                    run_html_func,
                    ["Prix"],
                )

            desc_col, desc_btn_col = st.columns([3, 1])
            with desc_col:
                st.text_area("Description", key="vinted_listing_description", height=300)
            with desc_btn_col:
                _copy_button(
                    "Copier description",
                    st.session_state.get("vinted_listing_description", ""),
                    "copy_vinted_description",
                    run_html_func,
                    ["Description"],
                )

            _copy_button(
                "Copier titre + description",
                (
                    f"{st.session_state.get('vinted_listing_title', '')}\n\n"
                    f"{st.session_state.get('vinted_listing_description', '')}"
                ),
                "copy_vinted_all",
                run_html_func,
                ["Titre", "Description"],
            )

            if st.session_state.get("vinted_copy_buffer"):
                st.text_area("Copie manuelle", value=st.session_state["vinted_copy_buffer"], height=160)


def _render_selected_add_to_drop(drops_data, selected_cards, scope="classic"):
    if not selected_cards or not drops_data.get("drops"):
        return
    options = _drop_choice_options(drops_data)
    if not options:
        return
    name = st.selectbox("Ajouter la sélection au drop", list(options.keys()), key="vinted_drop_destination")
    drop_id = options.get(name)
    if st.button("Ajouter la sélection au drop", disabled=not selected_cards, width="stretch"):
        cards_to_add = [
            _card_with_drop_quantity(card, _selected_quantity(scope, card)[0])
            for card in selected_cards
        ]
        added, duplicates = add_cards_to_drop(drops_data, drop_id, cards_to_add)
        if added:
            save_vinted_drops(drops_data)
            st.success(f"{added} carte(s) ajoutée(s) au drop.")
        if duplicates:
            st.warning("Cette carte est déjà dans ce drop." if duplicates == 1 else f"{duplicates} cartes sont déjà dans ce drop.")
        st.rerun()


def _render_drop_add_result(card, drops_data, active_drop, proxy_img_func, fp_func, mobile=False):
    key = card["_listing_key"]
    already = card_is_in_drop(active_drop, card)
    with st.container(border=True):
        if mobile:
            img_col, info_col = st.columns([0.75, 2.25])
            action_col = st.container()
        else:
            img_col, info_col, action_col = st.columns([0.7, 2.4, 1.0])
        with img_col:
            _render_thumb(card, proxy_img_func, width=74 if mobile else 82)
        with info_col:
            st.markdown(f"**{_card_display_title(card)}**")
            for line in _card_details_text(card, fp_func):
                st.caption(line)
        with action_col:
            if st.button(
                "Déjà ajouté" if already else "Ajouter au drop",
                key=f"vinted_drop_add_card_{active_drop.get('id')}_{key}",
                disabled=already,
                width="stretch",
            ):
                _add_card_to_drop_action(drops_data, active_drop.get("id"), card)


def _render_drop_add_search(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile=False):
    query = st.text_input(
        "Rechercher une carte à ajouter au drop",
        key="vinted_drop_add_query",
        placeholder="Ex : Dracaufeu, Rayquaza 89/90, Pohmarmotte...",
    )
    candidates_all = _filter_cards_for_display(available_cards, query)
    candidates_all = [card for card in candidates_all if not card_is_in_drop(active_drop, card)]
    if not candidates_all:
        st.caption("Aucune carte disponible trouvée.")
        return

    st.caption(f"{len(candidates_all)} carte(s) disponible(s).")
    groups = _drop_grid_groups(candidates_all, proxy_img_func, fp_func)
    duplicate_counts = dict(_drop_identity_counts(active_drop))
    result = render_vinted_drop_virtual_grid(
        groups,
        set(),
        duplicate_counts=duplicate_counts,
        key=f"drop_add_{active_drop.get('id')}",
        mobile=mobile,
        scroll_top_token=_drop_scroll_top_token(active_drop.get("id"), query),
        committed_selection_token=_drop_grid_committed_selection_token(active_drop.get("id")),
    )
    batch = _component_batch(result)
    if batch:
        selected_count, added_count, skipped_count = _process_drop_selection_batch(
            drops_data,
            active_drop,
            available_cards,
            batch,
        )
        if selected_count:
            if added_count:
                st.success(f"✓ {added_count} carte(s) ajoutée(s) au drop.")
            if skipped_count:
                st.warning(f"{skipped_count} sélection(s) déjà présente(s) ou indisponible(s).")
            st.rerun()
    if result is None:
        st.caption("Affichage simplifié utilisé pour cette session.")
        _render_grouped_available_grid(
            candidates_all[:24 if mobile else 48],
            scope="drop_add_fallback",
            listing_type="Carte seule",
            selected_keys=[],
            drops_data=drops_data,
            active_drop_id=active_drop.get("id"),
            proxy_img_func=proxy_img_func,
            fp_func=fp_func,
            mobile=mobile,
            mode="drop",
        )


def _render_drop_grid(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile):
    resolved_cards, missing_cards = resolve_drop_cards_from_data(active_drop, available_cards)
    drop_query = st.text_input(
        "Rechercher dans ce drop",
        key="vinted_drop_filter_query",
        placeholder="Nom, numéro complet, extension, lot...",
    )
    filtered_cards = filter_drop_cards(resolved_cards, drop_query)
    filtered_missing = filter_drop_cards(missing_cards, drop_query)
    if not filtered_cards and not filtered_missing:
        st.caption("Aucune carte dans ce drop." if not resolved_cards and not missing_cards else "Aucune carte ne correspond à cette recherche.")
        return

    if missing_cards:
        st.warning(f"{len(missing_cards)} carte(s) du drop ne sont plus disponibles à la vente.")

    duplicate_counts = _drop_identity_counts(active_drop)
    duplicate_extra = _drop_duplicate_extra_count(active_drop)
    if duplicate_extra:
        st.markdown(
            f'<span class="ps-vinted-badge duplicate">⚠ {duplicate_extra} doublon(s) potentiel(s)</span>',
            unsafe_allow_html=True,
        )

    cols_count = _drop_cards_grid_columns(mobile)
    all_cards = []
    for card in list(filtered_cards) + list(filtered_missing):
        item = dict(card)
        item["_drop_duplicate_total"] = duplicate_counts.get(_card_identity(item), 0)
        all_cards.append(item)
    for row_index, row in _chunked(all_cards, cols_count):
        with st.container(horizontal=True, key=f"vinted_grid_drop_cards_{active_drop.get('id')}_{row_index}"):
            for card in row:
                _render_drop_card(active_drop, drops_data, card, proxy_img_func, fp_func)


def _render_drop_card(active_drop, drops_data, card, proxy_img_func, fp_func):
    unavailable = not bool(card.get("_drop_available", True))
    card_ref_key = card.get("_drop_ref_key") or drop_card_key(
        {
            "lot_uid": card.get("lot_uid", ""),
            "card_uid": card.get("card_uid", ""),
            "lot_idx": card.get("lot_idx", 0),
            "card_idx": card.get("card_idx", 0),
            "name": card.get("name", ""),
            "number": card.get("number", ""),
            "set": card.get("set", ""),
        }
    )
    posted = bool(card.get("listing_posted", False))
    status = str(card.get("status") or ("online" if posted else "to_prepare"))
    badge = "INDISPONIBLE" if unavailable else drop_item_status_label(status)
    badge_class = "warn" if unavailable else _drop_status_badge_class(status)
    duplicate_total = int(card.get("_drop_duplicate_total", 0) or 0)
    duplicate_badge = ""
    if duplicate_total > 1:
        duplicate_badge = f"⚠ {duplicate_total} exemplaires" if duplicate_total > 2 else "⚠ Doublon"
    with st.container(key=f"vinted_card_drop_{active_drop.get('id')}_{_safe_js_id(card_ref_key)}"):
        st.markdown(
            _card_static_html(
                card,
                proxy_img_func,
                fp_func,
                badge=badge,
                badge_class=badge_class,
                duplicate_badge=duplicate_badge,
                unavailable=unavailable,
                drop_card=True,
            ),
            unsafe_allow_html=True,
        )
        if not unavailable:
            st.caption(f"Statut : {drop_item_status_label(status)}")
        if st.button("Retirer du drop", key=f"remove_drop_card_{active_drop.get('id')}_{card_ref_key}", width="stretch"):
            if remove_card_from_drop(drops_data, active_drop.get("id"), card_ref_key):
                save_vinted_drops(drops_data)
                st.success("Carte retirée du drop.")
                st.rerun()


def _drop_status_counts(drop):
    counts = {status: 0 for status in DROP_ITEM_STATUSES}
    for ref in drop.get("cards", []) or []:
        counts[drop_item_status(ref)] = counts.get(drop_item_status(ref), 0) + max(1, _safe_int(ref.get("quantity"), 1))
    return counts


def _render_drop_placeholder(title, body):
    st.markdown(
        f"""
<div class="ps-vinted-muted-panel">
  <div class="ps-vinted-section-title">{_html_escape(title)}</div>
  {_html_escape(body)}
</div>
""",
        unsafe_allow_html=True,
    )


def _render_launch_drop_panel(drops_data, active_drop, fp_func):
    counts = _drop_status_counts(active_drop)
    total_cards = sum(max(1, _safe_int(ref.get("quantity"), 1)) for ref in active_drop.get("cards", []) or [])
    ready = counts.get("draft_ready", 0)
    online = counts.get("online", 0)
    st.markdown(f"**{ready} / {total_cards} brouillons prêts**")
    if active_drop.get("drop_launched_at"):
        st.success(f"Drop lancé le {active_drop.get('drop_launched_at')}")
        return
    if ready <= 0:
        st.caption("Prépare au moins un brouillon avant de lancer le drop.")
        return
    with st.expander("🚀 Le drop est maintenant en ligne", expanded=False):
        channel = normalize_vinted_channel(active_drop.get("channel", "")) or "Non défini"
        st.write(f"Drop : **{active_drop.get('name', 'Drop sans nom')}**")
        st.write(f"Canal : **{channel}**")
        st.write(f"Brouillons prêts : **{ready}**")
        confirm_key = f"confirm_launch_drop_{active_drop.get('id')}"
        confirm = st.checkbox("Je confirme que ces brouillons sont en ligne", key=confirm_key)
        if st.button("Confirmer le lancement", key=f"launch_drop_{active_drop.get('id')}", disabled=not confirm, width="stretch"):
            if launch_drop(drops_data, active_drop.get("id")):
                save_vinted_drops(drops_data)
                st.success("Drop lancé.")
                st.rerun()


_DROP_PREPARATION_STATUSES = {"to_photograph", "needs_review", "sorted", "to_prepare"}
_DROP_PHOTO_DIRECTIONS = {
    "start_to_end": {
        "label": "📖 Photos : début des classeurs",
        "choice": "📖 J’ai commencé par le début des classeurs",
        "caption": "La file suit l’ordre des photos.",
    },
    "end_to_start": {
        "label": "🔄 Photos : fin des classeurs",
        "choice": "🔄 J’ai commencé par la fin des classeurs",
        "caption": "La file inverse les cartes photographiées, sans inverser les photos internes d’une carte.",
    },
}


def _drop_queue_skip_key(drop_id):
    return f"vinted_drop_creation_skipped_{drop_id}"


def _drop_card_ref_key(card):
    return card.get("_drop_ref_key") or drop_card_key(
        {
            "lot_uid": card.get("lot_uid", ""),
            "card_uid": card.get("card_uid", ""),
            "lot_idx": card.get("lot_idx", 0),
            "card_idx": card.get("card_idx", 0),
            "name": card.get("name", ""),
            "number": card.get("number", ""),
            "set": card.get("set", ""),
        }
    )


def _drop_workflow_quantity(card):
    return max(1, _safe_int(card.get("drop_quantity", card.get("quantity", 1)), 1))


def _drop_photo_order_value(card):
    value = card.get("photo_order")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _drop_photo_direction(drop):
    value = str((drop or {}).get("photo_capture_direction") or "").strip()
    return value if value in _DROP_PHOTO_DIRECTIONS else ""


def _set_drop_photo_direction(drops_data, drop_id, direction):
    if direction not in _DROP_PHOTO_DIRECTIONS:
        return False
    drop = find_drop(drops_data, drop_id)
    if not drop:
        return False
    drop["photo_capture_direction"] = direction
    return True


def _drop_creation_sort_key(item, direction="start_to_end"):
    position, card = item
    photo_order = _drop_photo_order_value(card)
    reverse = direction == "end_to_start"
    if photo_order is not None:
        return (0, -photo_order if reverse else photo_order, position)
    return (1, -position if reverse else position)


def _drop_creation_cards(active_drop, available_cards):
    resolved_cards, missing_cards = resolve_drop_cards_from_data(active_drop, available_cards)
    cards = list(resolved_cards) + list(missing_cards)
    direction = _drop_photo_direction(active_drop) or "start_to_end"
    ordered = [card for _pos, card in sorted(enumerate(cards), key=lambda item: _drop_creation_sort_key(item, direction))]
    workflow_cards = [
        card
        for card in ordered
        if str(card.get("status") or drop_item_status(card)) in _DROP_PREPARATION_STATUSES | {"draft_ready"}
    ]
    ready_cards = [card for card in workflow_cards if str(card.get("status") or drop_item_status(card)) == "draft_ready"]
    pending_cards = [card for card in workflow_cards if str(card.get("status") or drop_item_status(card)) in _DROP_PREPARATION_STATUSES]
    return workflow_cards, pending_cards, ready_cards


def _drop_mark_to_prepare(drops_data, drop_id, card_key):
    drop = find_drop(drops_data, drop_id)
    if not drop:
        return False
    for ref in drop.get("cards", []) or []:
        if drop_card_key(ref) != card_key:
            continue
        ref["status"] = "to_prepare"
        ref["draft_ready_at"] = ""
        ref["listing_posted"] = False
        ref["listing_posted_at"] = ""
        return True
    return False


def _drop_direction_edit_key(drop_id):
    return f"vinted_drop_photo_direction_edit_{drop_id}"


def _drop_direction_confirm_key(drop_id):
    return f"vinted_drop_photo_direction_confirm_{drop_id}"


def _apply_drop_photo_direction(drops_data, active_drop, direction):
    drop_id = active_drop.get("id")
    if not _set_drop_photo_direction(drops_data, drop_id, direction):
        return False
    st.session_state.pop(_drop_direction_edit_key(drop_id), None)
    st.session_state.pop(_drop_direction_confirm_key(drop_id), None)
    st.session_state[_drop_queue_skip_key(drop_id)] = []
    save_vinted_drops(drops_data)
    return True


def _render_drop_photo_direction_choice(drops_data, active_drop, ready_qty):
    drop_id = active_drop.get("id")
    direction = _drop_photo_direction(active_drop)
    edit_key = _drop_direction_edit_key(drop_id)
    confirm_key = _drop_direction_confirm_key(drop_id)

    if direction and not st.session_state.get(edit_key):
        info = _DROP_PHOTO_DIRECTIONS[direction]
        col_label, col_action = st.columns([4, 1])
        col_label.caption(info["label"])
        if col_action.button("Modifier", key=f"edit_photo_direction_{drop_id}", width="stretch"):
            st.session_state[edit_key] = True
            st.rerun()
        return True

    if not direction:
        st.markdown("**Dans quel sens as-tu pris les photos ?**")
        if ready_qty > 0:
            st.caption("Ce choix sera appliqué aux cartes restantes à préparer.")
    else:
        st.markdown("**Modifier le sens de prise de vue**")
        if ready_qty > 0:
            st.warning("Des brouillons existent déjà. Le changement ne modifiera pas les cartes déjà prêtes, seulement l’ordre des cartes restantes.")
            st.checkbox("Je confirme le changement de sens pour les cartes restantes", key=confirm_key)

    can_change = ready_qty <= 0 or bool(st.session_state.get(confirm_key))
    c_start, c_end = st.columns(2)
    with c_start:
        if st.button(
            _DROP_PHOTO_DIRECTIONS["start_to_end"]["choice"],
            key=f"set_photo_direction_start_{drop_id}",
            disabled=direction == "start_to_end" or not can_change,
            width="stretch",
        ):
            if _apply_drop_photo_direction(drops_data, active_drop, "start_to_end"):
                st.rerun()
        st.caption(_DROP_PHOTO_DIRECTIONS["start_to_end"]["caption"])
    with c_end:
        if st.button(
            _DROP_PHOTO_DIRECTIONS["end_to_start"]["choice"],
            key=f"set_photo_direction_end_{drop_id}",
            disabled=direction == "end_to_start" or not can_change,
            width="stretch",
        ):
            if _apply_drop_photo_direction(drops_data, active_drop, "end_to_start"):
                st.rerun()
        st.caption(_DROP_PHOTO_DIRECTIONS["end_to_start"]["caption"])

    if direction:
        if st.button("Annuler la modification", key=f"cancel_photo_direction_{drop_id}", width="stretch"):
            st.session_state.pop(edit_key, None)
            st.session_state.pop(confirm_key, None)
            st.rerun()
        return True
    return False


def _render_created_drafts_drawer(drops_data, active_drop, ready_cards, proxy_img_func, fp_func, mobile):
    ready_qty = sum(_drop_workflow_quantity(card) for card in ready_cards)
    if not _render_drop_drawer_header("created_drafts", f"Brouillons créés ({ready_qty})", default_open=False):
        return
    if not ready_cards:
        st.caption("Aucun brouillon créé pour l'instant.")
        return
    cols_count = 2 if mobile else 4
    for row_index, row in _chunked(ready_cards, cols_count):
        with st.container(horizontal=True, key=f"vinted_created_drafts_{active_drop.get('id')}_{row_index}"):
            for card in row:
                card_key = _drop_card_ref_key(card)
                with st.container(key=f"vinted_created_draft_{active_drop.get('id')}_{_safe_js_id(card_key)}"):
                    st.markdown(
                        _card_static_html(
                            card,
                            proxy_img_func,
                            fp_func,
                            badge=drop_item_status_label("draft_ready"),
                            badge_class=_drop_status_badge_class("draft_ready"),
                            drop_card=True,
                        ),
                        unsafe_allow_html=True,
                    )
                    photo_order = _drop_photo_order_value(card)
                    if photo_order is not None:
                        st.caption(f"Ordre photo : {photo_order}")
                    if st.button("Remettre à préparer", key=f"reopen_draft_drop_card_{active_drop.get('id')}_{card_key}", width="stretch"):
                        if _drop_mark_to_prepare(drops_data, active_drop.get("id"), card_key):
                            skipped = st.session_state.get(_drop_queue_skip_key(active_drop.get("id")), [])
                            st.session_state[_drop_queue_skip_key(active_drop.get("id"))] = [
                                key for key in skipped if key != card_key
                            ]
                            save_vinted_drops(drops_data)
                            st.rerun()


def _drop_card_total(drop):
    return sum(max(1, _safe_int(ref.get("quantity"), 1)) for ref in drop.get("cards", []) or [])


def _drop_value_total(drop):
    return sum(_safe_float(ref.get("price_at_add")) * max(1, _safe_int(ref.get("quantity"), 1)) for ref in drop.get("cards", []) or [])


def _off_stock_cost_for_drop(sale, lot=None, valeur_est=None, effective_purchase_price_func=None):
    if (sale or {}).get("cost_basis_known"):
        return _safe_float((sale or {}).get("cost_basis"))
    if not lot or not callable(effective_purchase_price_func):
        return None
    price = _safe_float((sale or {}).get("price"))
    if price <= 0:
        return 0.0
    try:
        if lot.get("is_mixte") and _safe_float(lot.get("valeur_totale")) > 0:
            return (price / _safe_float(lot.get("valeur_totale"), 1.0)) * _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat", 0)))
        return (price / (_safe_float(valeur_est) or 1.0)) * effective_purchase_price_func(lot)
    except Exception:
        return None


def _off_stock_sale_row(sale, *, lot=None, lot_name="", cost=None):
    quantity = 0
    revenue = _safe_float((sale or {}).get("price"))
    return {
        "sale": sale,
        "card": {},
        "lot": lot or {},
        "quantity": quantity,
        "revenue": revenue,
        "displayed_total": 0.0,
        "profit": (revenue - cost) if cost is not None else None,
        "date": _parse_dt((sale or {}).get("date")),
        "card_name": (sale or {}).get("card_name") or (sale or {}).get("description") or (sale or {}).get("category") or "Vente hors stock",
        "lot_name": lot_name or (sale or {}).get("source_lot_name") or "Non attribuée",
        "is_off_stock": True,
    }


def _sale_rows_for_drop(stock_data, drop_id, calc_cout_lot_func=None, effective_purchase_price_func=None):
    rows = []
    for lot_idx, lot in enumerate((stock_data or {}).get("lots", []) or []):
        costs_by_sale_id = {}
        valeur_estimee = None
        if callable(calc_cout_lot_func):
            try:
                cost_rows, valeur_estimee = calc_cout_lot_func(lot, lot_idx=lot_idx)
                costs_by_sale_id = {se.get("sale_id"): cost for _, se, cost in cost_rows if se.get("sale_id")}
            except Exception:
                costs_by_sale_id = {}
        for sale in lot.get("ventes", []) or []:
            if not sale.get("is_off_stock") or str(sale.get("drop_id") or "") != str(drop_id or ""):
                continue
            cost = _off_stock_cost_for_drop(
                sale,
                lot=lot,
                valeur_est=valeur_estimee,
                effective_purchase_price_func=effective_purchase_price_func,
            )
            rows.append(_off_stock_sale_row(sale, lot=lot, lot_name=lot.get("nom", ""), cost=cost))
        for card in lot.get("cards", []) or []:
            for sale in card.get("sold_entries", []) or []:
                if str(sale.get("drop_id") or "") != str(drop_id or ""):
                    continue
                quantity = max(1, _safe_int(sale.get("quantity"), 1))
                revenue = _safe_float(sale.get("price"))
                suggested_unit = _safe_float(sale.get("suggested_price_at_sale"))
                displayed_total = suggested_unit * quantity
                cost = costs_by_sale_id.get(sale.get("sale_id"))
                rows.append({
                    "sale": sale,
                    "card": card,
                    "lot": lot,
                    "quantity": quantity,
                    "revenue": revenue,
                    "displayed_total": displayed_total,
                    "profit": (revenue - cost) if cost is not None else None,
                    "date": _parse_dt(sale.get("date")),
                    "card_name": sale.get("card_name") or card.get("name", ""),
                    "lot_name": lot.get("nom", ""),
                })
    for sale in (stock_data or {}).get("ventes_hors_stock", []) or []:
        if str(sale.get("drop_id") or "") != str(drop_id or ""):
            continue
        rows.append(_off_stock_sale_row(sale, cost=_off_stock_cost_for_drop(sale)))
    return rows


def _drop_metrics(drop, sales_rows):
    counts = _drop_status_counts(drop)
    total_cards = _drop_card_total(drop)
    revenue = sum(row["revenue"] for row in sales_rows)
    known_profits = [row["profit"] for row in sales_rows if row.get("profit") is not None]
    sold_cards = sum(row["quantity"] for row in sales_rows) or counts.get("sold", 0)
    sold_card_revenue = sum(row["revenue"] for row in sales_rows if row.get("quantity", 0) > 0)
    transactions = {row["sale"].get("sale_id") or f"{row['date']}-{idx}" for idx, row in enumerate(sales_rows)}
    return {
        "cards": total_cards,
        "draft_ready": counts.get("draft_ready", 0),
        "online": counts.get("online", 0),
        "sold": sold_cards,
        "published_value": _drop_value_total(drop),
        "revenue": revenue,
        "profit": sum(known_profits) if known_profits else None,
        "sell_through": (sold_cards / total_cards * 100.0) if total_cards else None,
        "avg_sold_price": (sold_card_revenue / sold_cards) if sold_cards else None,
        "avg_basket": (revenue / len(transactions)) if transactions else None,
        "avg_cards_per_transaction": (sold_cards / len(transactions)) if transactions else None,
    }


def _render_kpis(metrics, fp_func):
    items = [
        ("Cartes sélectionnées", str(metrics.get("cards", 0))),
        ("Brouillons prêts", str(metrics.get("draft_ready", 0))),
        ("En ligne", str(metrics.get("online", 0))),
        ("Vendues", str(metrics.get("sold", 0))),
        ("Valeur publiée", fp_func(metrics.get("published_value", 0))),
        ("CA", fp_func(metrics.get("revenue", 0))),
        ("Bénéfice", fp_func(metrics["profit"]) if metrics.get("profit") is not None else "N/A"),
        ("Marge", f"{(metrics['profit'] / metrics['revenue'] * 100):.1f}%" if metrics.get("profit") is not None and metrics.get("revenue") else "N/A"),
        ("Taux d'écoulement", f"{metrics['sell_through']:.1f}%" if metrics.get("sell_through") is not None else "N/A"),
        ("Prix moyen vendu", fp_func(metrics["avg_sold_price"]) if metrics.get("avg_sold_price") is not None else "N/A"),
        ("Panier moyen", fp_func(metrics["avg_basket"]) if metrics.get("avg_basket") is not None else "N/A"),
        ("Cartes / transaction", f"{metrics['avg_cards_per_transaction']:.2f}" if metrics.get("avg_cards_per_transaction") is not None else "N/A"),
    ]
    html = '<div class="ps-vinted-kpi-grid">' + "".join(
        f'<div class="ps-vinted-kpi"><span>{_html_escape(label)}</span><strong>{_html_escape(value)}</strong></div>'
        for label, value in items
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _negotiation_stats(rows):
    diffs = []
    pct = []
    under = equal = above = 0
    for row in rows:
        displayed = row.get("displayed_total", 0)
        if displayed <= 0:
            continue
        diff = row.get("revenue", 0) - displayed
        diffs.append(diff)
        pct.append(diff / displayed * 100.0)
        if abs(diff) < 0.01:
            equal += 1
        elif diff < 0:
            under += 1
        else:
            above += 1
    pct_sorted = sorted(pct)
    median = pct_sorted[len(pct_sorted) // 2] if pct_sorted else None
    if pct_sorted and len(pct_sorted) % 2 == 0:
        median = (pct_sorted[len(pct_sorted) // 2 - 1] + pct_sorted[len(pct_sorted) // 2]) / 2
    total = len(pct)
    return {
        "avg_pct": (sum(pct) / total) if total else None,
        "median_pct": median,
        "equal_pct": equal / total * 100.0 if total else None,
        "under_pct": under / total * 100.0 if total else None,
        "above_pct": above / total * 100.0 if total else None,
        "total_diff": sum(diffs),
    }


def _render_drop_timing(drop, rows, fp_func):
    launched = _parse_dt(drop.get("drop_launched_at"))
    if not launched:
        st.caption("Temporalité : N/A, drop non lancé.")
        return
    rows = sorted([row for row in rows if row.get("date")], key=lambda row: row["date"])
    if not rows:
        st.caption("Aucune vente liée après lancement.")
        return
    first = rows[0]["date"] - launched
    st.markdown(f"**Première vente :** {_duration_label(first)}")
    thresholds = [50, 100, 200, 500, 1000, 2000]
    cumulative = 0.0
    reached = {}
    for row in rows:
        cumulative += row["revenue"]
        for threshold in thresholds:
            if threshold not in reached and cumulative >= threshold:
                reached[threshold] = _duration_label(row["date"] - launched)
    if reached:
        st.caption("Seuils CA atteints : " + " · ".join(f"{fp_func(k)} : {v}" for k, v in reached.items()))
    total_cards = _drop_card_total(drop)
    if total_cards:
        sold = 0
        reached_cards = {}
        for row in rows:
            sold += row["quantity"]
            for threshold in (10, 25, 50, 75):
                if threshold not in reached_cards and sold / total_cards * 100.0 >= threshold:
                    reached_cards[threshold] = _duration_label(row["date"] - launched)
        if reached_cards:
            st.caption("Écoulement atteint : " + " · ".join(f"{k}% : {v}" for k, v in reached_cards.items()))
    for days in (0, 1, 3, 7, 30):
        cutoff = launched + timedelta(days=days + 1)
        ca = sum(row["revenue"] for row in rows if row["date"] < cutoff)
        cards = sum(row["quantity"] for row in rows if row["date"] < cutoff)
        st.caption(f"J{days} : {fp_func(ca)} · {cards} carte(s)")


def _render_drop_charts(drop, rows):
    launched = _parse_dt(drop.get("drop_launched_at"))
    if not launched or not rows:
        return
    try:
        import pandas as pd
    except Exception:
        return
    ordered = sorted([row for row in rows if row.get("date")], key=lambda row: row["date"])
    cumulative_ca = cumulative_profit = cumulative_cards = 0.0
    chart_rows = []
    total_cards = max(1, _drop_card_total(drop))
    for row in ordered:
        cumulative_ca += row["revenue"]
        cumulative_cards += row["quantity"]
        if row.get("profit") is not None:
            cumulative_profit += row["profit"]
        chart_rows.append({
            "J+": max(0, (row["date"] - launched).days),
            "CA cumulé": cumulative_ca,
            "Bénéfice cumulé": cumulative_profit,
            "Cartes vendues": cumulative_cards,
            "Taux écoulement": cumulative_cards / total_cards * 100.0,
        })
    if chart_rows:
        df = pd.DataFrame(chart_rows).groupby("J+", as_index=True).max()
        st.line_chart(df[["CA cumulé", "Bénéfice cumulé"]])
        st.line_chart(df[["Cartes vendues", "Taux écoulement"]])


def _render_drop_analytics(drops_data, stock_data, fp_func, calc_cout_lot_func=None, effective_purchase_price_func=None):
    drops = drops_data.get("drops", []) or []
    if not drops:
        st.caption("Aucun drop à analyser.")
        return
    channel_options = ["Tous", *VINTED_CHANNELS]
    channel_filter = st.selectbox("Canal", channel_options, key="vinted_analysis_channel")
    filtered = [
        drop for drop in drops
        if channel_filter == "Tous" or normalize_vinted_channel(drop.get("channel", "")) == channel_filter
    ]
    if not filtered:
        st.caption("Aucun drop pour ce canal.")
        return
    drop_names = ["Tous les drops"] + [drop.get("name", "Drop sans nom") for drop in filtered]
    selected_name = st.selectbox("Drop", drop_names, key="vinted_analysis_drop")
    selected = filtered if selected_name == "Tous les drops" else [drop for drop in filtered if drop.get("name", "Drop sans nom") == selected_name]
    all_rows = []
    aggregate = {
        "cards": 0,
        "draft_ready": 0,
        "online": 0,
        "sold": 0,
        "published_value": 0.0,
        "revenue": 0.0,
        "profit": 0.0,
        "known_profit": False,
    }
    for drop in selected:
        rows = _sale_rows_for_drop(stock_data, drop.get("id"), calc_cout_lot_func, effective_purchase_price_func)
        all_rows.extend(rows)
        metrics = _drop_metrics(drop, rows)
        for key in ("cards", "draft_ready", "online", "sold", "published_value", "revenue"):
            aggregate[key] += metrics.get(key, 0) or 0
        if metrics.get("profit") is not None:
            aggregate["profit"] += metrics["profit"]
            aggregate["known_profit"] = True
    aggregate["profit"] = aggregate["profit"] if aggregate.pop("known_profit") else None
    aggregate["sell_through"] = aggregate["sold"] / aggregate["cards"] * 100.0 if aggregate["cards"] else None
    tx_count = len({row["sale"].get("sale_id") for row in all_rows if row["sale"].get("sale_id")})
    card_revenue = sum(row["revenue"] for row in all_rows if row.get("quantity", 0) > 0)
    aggregate["avg_sold_price"] = card_revenue / aggregate["sold"] if aggregate["sold"] else None
    aggregate["avg_basket"] = aggregate["revenue"] / tx_count if tx_count else None
    aggregate["avg_cards_per_transaction"] = aggregate["sold"] / tx_count if tx_count else None
    _render_kpis(aggregate, fp_func)

    neg = _negotiation_stats(all_rows)
    st.markdown("**Négociation**")
    st.caption(
        " · ".join([
            f"Moyenne {neg['avg_pct']:.1f}%" if neg.get("avg_pct") is not None else "Moyenne N/A",
            f"Médiane {neg['median_pct']:.1f}%" if neg.get("median_pct") is not None else "Médiane N/A",
            f"Au prix {neg['equal_pct']:.0f}%" if neg.get("equal_pct") is not None else "Au prix N/A",
            f"Sous prix {neg['under_pct']:.0f}%" if neg.get("under_pct") is not None else "Sous prix N/A",
            f"Au-dessus {neg['above_pct']:.0f}%" if neg.get("above_pct") is not None else "Au-dessus N/A",
            f"Total {fp_func(neg['total_diff'])}",
        ])
    )

    if len(selected) == 1:
        st.markdown("**Temporalité**")
        _render_drop_timing(selected[0], all_rows, fp_func)
        _render_drop_charts(selected[0], all_rows)

    if all_rows:
        st.markdown("**Transactions marquantes**")
        top_rows = sorted(all_rows, key=lambda row: row["revenue"], reverse=True)[:5]
        for row in top_rows:
            st.caption(f"{row['card_name']} · {fp_func(row['revenue'])} · {row.get('lot_name', '')}")

    st.markdown("**Tranches de prix**")
    bands = [("<2 €", 0, 2), ("2–5 €", 2, 5), ("5–10 €", 5, 10), ("10–20 €", 10, 20), (">20 €", 20, float("inf"))]
    for label, low, high in bands:
        published = 0
        sold = ca = 0
        for drop in selected:
            for ref in drop.get("cards", []) or []:
                price = _safe_float(ref.get("price_at_add"))
                qty = max(1, _safe_int(ref.get("quantity"), 1))
                if low <= price < high:
                    published += qty
        for row in all_rows:
            unit = row["revenue"] / max(1, row["quantity"])
            if low <= unit < high:
                sold += row["quantity"]
                ca += row["revenue"]
        rate = sold / published * 100.0 if published else None
        st.caption(f"{label} : {published} publiée(s) · {sold} vendue(s) · {f'{rate:.0f}%' if rate is not None else 'N/A'} · {fp_func(ca)}")


def _render_drop_creation_step(drops_data, active_drop, available_cards, proxy_img_func, fp_func, run_html_func, mobile):
    workflow_cards, pending_cards, ready_cards = _drop_creation_cards(active_drop, available_cards)
    total_qty = sum(_drop_workflow_quantity(card) for card in workflow_cards)
    ready_qty = sum(_drop_workflow_quantity(card) for card in ready_cards)
    pct = (ready_qty / total_qty) if total_qty else 0.0
    st.markdown(
        f"""
<div class="ps-vinted-progress-panel">
  <div class="ps-vinted-progress-main">{ready_qty} / {total_qty} brouillons créés</div>
  <div class="ps-vinted-progress-sub">{pct * 100:.0f} % · Création des annonces</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.progress(pct)

    if not workflow_cards:
        st.caption("Aucune carte à préparer dans ce drop.")
        _render_launch_drop_panel(drops_data, active_drop, fp_func)
        return

    if not _render_drop_photo_direction_choice(drops_data, active_drop, ready_qty):
        return

    skip_key = _drop_queue_skip_key(active_drop.get("id"))
    skipped_keys = list(st.session_state.get(skip_key, []) or [])
    pending_unskipped = [card for card in pending_cards if _drop_card_ref_key(card) not in skipped_keys]
    if not pending_unskipped and pending_cards:
        skipped_keys = []
        st.session_state[skip_key] = []
        pending_unskipped = list(pending_cards)

    if pending_unskipped:
        current_card = pending_unskipped[0]
        current_key = _drop_card_ref_key(current_card)
        current_qty = _drop_workflow_quantity(current_card)
        listing_card = _card_with_drop_quantity(current_card, current_qty)
        listing_type = "Carte seule"
        _sync_listing_text([listing_card], listing_type, fp_func)
        current_number = min(total_qty, ready_qty + 1)
        st.markdown(f"**Carte #{current_number} sur {total_qty}**")
        with st.container():
            left, right = st.columns([1, 2]) if not mobile else [st.container(), st.container()]
            with left:
                _render_thumb(current_card, proxy_img_func, width=180 if mobile else 210)
            with right:
                st.markdown(
                    f"""
<div class="ps-vinted-current-card">
  <div class="ps-vinted-current-title">{_html_escape(_card_display_title(current_card))}</div>
  <div class="ps-vinted-current-meta">
    {_html_escape(_card_number(current_card) or "Numéro N/A")} ·
    {_html_escape(_card_set(current_card) or "Extension N/A")} ·
    Prix : {_html_escape(fp_func(suggested_price(current_card)) if suggested_price(current_card) else "à définir")} ·
    Quantité : x{current_qty}
  </div>
</div>
""",
                    unsafe_allow_html=True,
                )

        st.text_input("Titre généré", key="vinted_listing_title")
        _copy_button("Copier titre", st.session_state.get("vinted_listing_title", ""), "copy_vinted_queue_title", run_html_func, ["Titre généré"])
        st.text_input("Prix", key="vinted_listing_price")
        _copy_button("Copier prix", st.session_state.get("vinted_listing_price", ""), "copy_vinted_queue_price", run_html_func, ["Prix"])
        st.text_area("Description générée", key="vinted_listing_description", height=220 if mobile else 260)
        _copy_button("Copier description", st.session_state.get("vinted_listing_description", ""), "copy_vinted_queue_description", run_html_func, ["Description générée"])
        st.link_button("Ouvrir Vinted", "https://www.vinted.fr/items/new", width="stretch")

        done_col, skip_col = st.columns([2, 1]) if not mobile else (st.container(), st.container())
        with done_col:
            if st.button("✓ Brouillon créé", key=f"draft_ready_drop_card_{active_drop.get('id')}_{current_key}", type="primary", width="stretch"):
                if set_drop_card_status(drops_data, active_drop.get("id"), current_key, "draft_ready"):
                    st.session_state[skip_key] = [key for key in skipped_keys if key != current_key]
                    save_vinted_drops(drops_data)
                    st.rerun()
        with skip_col:
            if st.button("Passer pour l'instant", key=f"skip_drop_card_{active_drop.get('id')}_{current_key}", width="stretch"):
                if current_key not in skipped_keys:
                    skipped_keys.append(current_key)
                st.session_state[skip_key] = skipped_keys
                st.rerun()
    else:
        st.success("✅ Tous les brouillons sont prêts")

    _render_created_drafts_drawer(drops_data, active_drop, ready_cards, proxy_img_func, fp_func, mobile)
    _render_launch_drop_panel(drops_data, active_drop, fp_func)


def _render_drops_manager(drops_data, available_cards, proxy_img_func, fp_func, mobile, step, run_html_func=None, ld_func=None, calc_cout_lot_func=None, effective_purchase_price_func=None):
    with st.expander("+ Nouveau drop", expanded=not bool(drops_data.get("drops"))):
        new_name = st.text_input("Nom du nouveau drop", key="new_vinted_drop_name", placeholder="Ex : Drop Vinted juin")
        new_channel = st.selectbox("Canal Vinted", list(VINTED_CHANNELS), key="new_vinted_drop_channel")
        if st.button("Créer le drop", key="create_vinted_drop", width="stretch"):
            if not str(new_name or "").strip():
                st.warning("Indique un nom de drop.")
                return
            create_drop(drops_data, new_name, new_channel)
            save_vinted_drops(drops_data)
            st.session_state.pop("new_vinted_drop_name", None)
            st.success("Drop créé.")
            st.rerun()

    drops = drops_data.get("drops", [])
    if not drops:
        st.caption("Aucun drop pour le moment.")
        return

    active_id = _active_drop_id(drops_data)
    drop_names = [drop.get("name", "Drop sans nom") for drop in drops]
    id_by_name = {drop.get("name", "Drop sans nom"): drop.get("id") for drop in drops}
    current_name = next((drop.get("name", "Drop sans nom") for drop in drops if drop.get("id") == active_id), drop_names[0])
    chosen_name = st.selectbox("Drop à afficher", drop_names, index=drop_names.index(current_name), key="vinted_drop_view")
    active_id = id_by_name[chosen_name]
    st.session_state["vinted_active_drop_id"] = active_id
    active_drop = find_drop(drops_data, active_id)
    if not active_drop:
        return

    total_cards = sum(max(1, int(ref.get("quantity", 1) or 1)) for ref in active_drop.get("cards", []))
    total_value = _drop_total_value(active_drop)
    channel_label = normalize_vinted_channel(active_drop.get("channel", "")) or "Non défini"
    channel_class = _drop_channel_class(channel_label)
    st.markdown(
        f"""
<div class="ps-vinted-drop-head">
  <strong>{_html_escape(active_drop.get('name', 'Drop sans nom'))}</strong>
  <div class="ps-vinted-drop-meta">
    <span>{total_cards} carte(s) · {fp_func(total_value) if total_value else 'Valeur à définir'}</span>
    <span class="ps-vinted-channel {channel_class}">{_html_escape(channel_label)}</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    with st.expander("⚙️ Gérer le drop", expanded=False):
        renamed = st.text_input("Renommer le drop", value=active_drop.get("name", ""), key=f"rename_drop_{active_id}")
        current_channel = normalize_vinted_channel(active_drop.get("channel", ""))
        channel_options = ["Non défini", *VINTED_CHANNELS]
        channel_index = channel_options.index(current_channel) if current_channel in channel_options else 0
        chosen_channel = st.selectbox("Canal Vinted", channel_options, index=channel_index, key=f"drop_channel_{active_id}")
        if st.button("Enregistrer le nom", key=f"save_drop_name_{active_id}", width="stretch"):
            changed = rename_drop(drops_data, active_id, renamed)
            changed = update_drop_channel(drops_data, active_id, "" if chosen_channel == "Non défini" else chosen_channel) or changed
            if changed:
                save_vinted_drops(drops_data)
                st.success("Drop mis à jour.")
                st.rerun()
        st.divider()
        confirm = st.checkbox("Confirmer suppression", key=f"confirm_delete_drop_{active_id}")
        if st.button("Supprimer le drop", key=f"delete_drop_{active_id}", disabled=not confirm, width="stretch"):
            if delete_drop(drops_data, active_id):
                save_vinted_drops(drops_data)
                st.session_state.pop("vinted_active_drop_id", None)
                st.success("Drop supprimé.")
                st.rerun()

    if step == "Choix des cartes":
        if _render_drop_drawer_header("add_cards", "Ajouter des cartes au drop", default_open=True):
            _render_drop_add_search(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile)

        if _render_drop_drawer_header("drop_cards", f"Cartes du drop ({total_cards})", default_open=True):
            _render_drop_grid(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile)
    elif step == "Tri des photos":
        _render_drop_placeholder(
            "Tri des photos",
            "Le tri photo sera ajouté ensuite. Aucun upload, OCR ou reconnaissance n'est actif pour l'instant.",
        )
    elif step == "Vérification":
        _render_drop_placeholder(
            "Vérification",
            "La vérification automatique des photos sera ajoutée ensuite. Les cartes et annonces existantes restent inchangées.",
        )
    elif step == "Création des annonces":
        _render_drop_creation_step(drops_data, active_drop, available_cards, proxy_img_func, fp_func, run_html_func, mobile)
    elif step == "Analyse des drops":
        _render_drop_analytics(
            drops_data,
            ld_func() if callable(ld_func) else {},
            fp_func,
            calc_cout_lot_func,
            effective_purchase_price_func,
        )


def _render_classic_listing_section(cards, drops_data, proxy_img_func, fp_func, run_html_func, mobile, *, allow_drop_add=False):
    card_by_key = {card["_listing_key"]: card for card in cards}
    selected_keys = st.session_state.setdefault("vinted_selected_keys", [])
    active_drop_id = _active_drop_id(drops_data) if allow_drop_add else ""
    st.subheader("Créer une annonce")
    listing_type = st.radio(
        "Mode d'annonce",
        ["Carte seule", "Plusieurs cartes"],
        horizontal=not mobile,
        key="vinted_listing_type",
    )
    if listing_type == "Carte seule" and len(selected_keys) > 1:
        selected_keys = selected_keys[:1]
        st.session_state["vinted_selected_keys"] = selected_keys

    query = st.text_input(
        "Rechercher une carte disponible",
        key="vinted_search_query",
        placeholder="Ex : Meganium, Dracaufeu 199/165, Rayquaza 89/90...",
    )
    results_all = _filter_cards_for_display(cards, query)
    limit = _visible_limit("classic", query, mobile, len(results_all))
    results = results_all[:limit]
    st.caption(f"{len(results)} / {len(results_all)} carte(s) affichée(s).")
    _render_grouped_available_grid(
        results,
        scope="classic",
        listing_type=listing_type,
        selected_keys=selected_keys,
        drops_data=drops_data,
        active_drop_id=active_drop_id,
        proxy_img_func=proxy_img_func,
        fp_func=fp_func,
        mobile=mobile,
        mode="classic",
    )
    _show_more("classic", mobile, len(results_all))

    selected_cards = [card_by_key[key] for key in selected_keys if key in card_by_key]
    prepared = _sync_listing_text(selected_cards, listing_type, fp_func)
    if listing_type == "Plusieurs cartes":
        st.markdown(f'<span class="ps-vinted-pill">{len(selected_cards)} sélectionnée(s)</span>', unsafe_allow_html=True)
        if allow_drop_add:
            _render_selected_add_to_drop(drops_data, selected_cards, scope="classic")

    if selected_cards:
        left, right = st.columns([1, 1])
        with left:
            if st.button("Régénérer le titre et la description", width="stretch"):
                st.session_state["vinted_listing_title"] = prepared["title"]
                st.session_state["vinted_listing_description"] = prepared["description"]
                st.rerun()
        with right:
            if st.button("Réinitialiser", width="stretch"):
                _reset_vinted_form()

    _render_listing_preview(selected_cards, proxy_img_func, run_html_func, mobile)


def render_vinted_listings_page(
    *,
    ld_func,
    card_available_qty_func,
    is_collection_system_lot_func,
    proxy_img_func,
    render_page_header_func,
    fp_func,
    is_mobile_mode_func=None,
    perf_count_func=None,
    run_html_func=None,
    page_mode="drop",
    calc_cout_lot_func=None,
    effective_purchase_price_func=None,
):
    if page_mode == "individual":
        st.markdown(
            render_page_header_func("Annonces individuelles", "Créer une annonce ponctuelle hors drop", "📝"),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            render_page_header_func("Drop Vinted", "Préparer, suivre et analyser tes drops Vinted", "🛍️"),
            unsafe_allow_html=True,
        )
    _inject_vinted_styles()

    d = ld_func()
    cards = _available_cards(d, card_available_qty_func, is_collection_system_lot_func)
    if perf_count_func:
        perf_count_func("vinted_cards_available", len(cards))

    if not cards:
        st.info("Aucune carte disponible à la vente pour le moment.")
        return

    mobile = bool(is_mobile_mode_func and is_mobile_mode_func())
    drops_data = load_vinted_drops()
    if page_mode == "individual":
        _render_classic_listing_section(cards, drops_data, proxy_img_func, fp_func, run_html_func, mobile, allow_drop_add=False)
        return

    step = _render_drop_step_nav(mobile)
    _render_drops_manager(
        drops_data,
        cards,
        proxy_img_func,
        fp_func,
        mobile,
        step,
        run_html_func=run_html_func,
        ld_func=ld_func,
        calc_cout_lot_func=calc_cout_lot_func,
        effective_purchase_price_func=effective_purchase_price_func,
    )

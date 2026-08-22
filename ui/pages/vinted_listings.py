from __future__ import annotations

import json
import os
import re
from collections import OrderedDict

import streamlit as st

from services.vinted_drops_service import (
    add_card_to_drop,
    add_cards_to_drop,
    card_is_in_drop,
    create_drop,
    delete_drop,
    drop_card_key,
    filter_drop_cards,
    find_drop,
    load_vinted_drops,
    remove_card_from_drop,
    rename_drop,
    resolve_drop_cards_from_data,
    save_vinted_drops,
    toggle_drop_card_posted,
)
from services.vinted_listing_service import (
    filter_cards_for_listing,
    full_card_number,
    listing_price_text,
    prepare_listing,
    suggested_price,
)
from ui.vinted_drop_virtual_grid import render_vinted_drop_virtual_grid


def _ui_text(value, fallback=""):
    text = str(value or fallback).strip()
    text = text.replace("\ufffd", "")
    text = re.sub(r"^\?+\s*", "", text)
    text = re.sub(r"\s+\?+\s*", " ", text)
    return " ".join(text.split())


def _card_image(card):
    for key in ("image_url", "image_url_en", "resolved_collection_image_url", "manual_image_url"):
        value = str(card.get(key, "") or "").strip()
        if value:
            return value
    for key in ("manual_image_path", "image_path", "local_image_path"):
        value = str(card.get(key, "") or "").strip()
        if value and os.path.exists(value):
            return value
    return ""


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
.ps-vinted-drop-head {
    padding:.82rem .95rem;
    border:1px solid rgba(129,140,248,.24);
    border-radius:12px;
    background:linear-gradient(135deg, rgba(238,242,255,.95), rgba(255,255,255,.96));
    margin:.2rem 0 .85rem;
}
.ps-vinted-drop-head strong {
    display:block;
    color:#0f172a;
    font-size:1.02rem;
    line-height:1.2;
}
.ps-vinted-drop-head span {
    display:block;
    color:#64748b;
    font-size:.82rem;
    font-weight:700;
    margin-top:.22rem;
}
.ps-vinted-lot-title {
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
div[class*="st-key-vinted_grid_"] button {
    min-height:30px !important;
    padding:.2rem .4rem !important;
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


def _card_static_html(card, proxy_img_func, fp_func, *, badge="", unavailable=False, drop_card=False):
    img = _card_image(card)
    if img:
        try:
            img = proxy_img_func(img)
        except Exception:
            pass
        img_html = f'<img src="{_html_escape(img)}" loading="lazy" decoding="async" alt="">'
    else:
        img_html = "Image<br>absente"
    meta_bits = []
    if _card_set(card):
        meta_bits.append(_card_set(card))
    if _card_number(card):
        meta_bits.append(f"#{_card_number(card)}")
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
        cls = "warn" if unavailable else ("ok" if "POST" in badge.upper() else "")
        badge_html = f'<span class="ps-vinted-badge {cls}">{_html_escape(badge)}</span>'
    return f"""
<div class="ps-vinted-card">
  <div class="ps-vinted-img">{img_html}</div>
  <div class="ps-vinted-name">{_html_escape(_card_display_title(card))}</div>
  <div class="ps-vinted-meta">{_html_escape(meta)}</div>
  <div class="ps-vinted-price">{_html_escape(price_label)} · {_html_escape(stock_label)}</div>
  {badge_html}
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


def _open_classic_submenu():
    st.session_state["_vinted_submenu_target"] = "Annonces classiques"


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
    img = _card_image(card)
    if img:
        try:
            img = proxy_img_func(img)
        except Exception:
            pass
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


def _add_card_to_drop_action(drops_data, drop_id, card, quantity=1):
    added, duplicate = add_card_to_drop(drops_data, drop_id, _card_with_drop_quantity(card, quantity))
    if added:
        save_vinted_drops(drops_data)
        st.success("Carte ajoutée au drop.")
        st.rerun()
    if duplicate:
        st.warning("Cette carte est déjà dans ce drop.")


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
    st.markdown(_card_static_html(card, proxy_img_func, fp_func), unsafe_allow_html=True)
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


def _drop_added_keys(drop):
    return {
        drop_card_key(ref)
        for ref in (drop.get("cards", []) or [])
    }


def _drop_grid_groups(cards, proxy_img_func, fp_func):
    groups = []
    for group in _group_cards_by_lot(cards):
        payload_cards = []
        for card in group.get("cards", []) or []:
            img = _card_image(card)
            if img:
                try:
                    img = proxy_img_func(img)
                except Exception:
                    pass
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
    st.markdown("**Ajouter des cartes au drop**")
    query = st.text_input(
        "Rechercher une carte à ajouter au drop",
        key="vinted_drop_add_query",
        placeholder="Ex : Dracaufeu, Rayquaza 89/90, Pohmarmotte...",
    )
    candidates_all = _filter_cards_for_display(available_cards, query)
    if not candidates_all:
        st.caption("Aucune carte disponible trouvée.")
        return

    st.caption(f"{len(candidates_all)} carte(s) disponible(s).")
    groups = _drop_grid_groups(candidates_all, proxy_img_func, fp_func)
    added_keys = _drop_added_keys(active_drop)
    card_by_key = {
        card.get("_drop_card_key") or drop_card_key(card): card
        for card in candidates_all
    }
    result = render_vinted_drop_virtual_grid(
        groups,
        added_keys,
        key=f"drop_add_{active_drop.get('id')}",
        mobile=mobile,
        scroll_top_token=_drop_scroll_top_token(active_drop.get("id"), query),
    )
    action = getattr(result, "action", None) if result is not None else None
    if isinstance(action, dict) and action.get("type") == "add":
        action_id = str(action.get("id") or "")
        if action_id and st.session_state.get("vinted_drop_last_action") != action_id:
            st.session_state["vinted_drop_last_action"] = action_id
            card_key = str(action.get("card_key") or "")
            card = card_by_key.get(card_key)
            if card:
                try:
                    quantity = int(action.get("quantity", 1) or 1)
                except Exception:
                    quantity = 1
                _add_card_to_drop_action(drops_data, active_drop.get("id"), card, quantity)
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
    total_cards = sum(max(1, int(ref.get("quantity", 1) or 1)) for ref in active_drop.get("cards", []))
    st.subheader(f"Cartes du drop ({total_cards})")
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

    cols_count = _grid_columns(mobile)
    all_cards = list(filtered_cards) + list(filtered_missing)
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
    badge = "INDISPONIBLE" if unavailable else ("POSTÉE" if posted else "À PRÉPARER")
    with st.container(key=f"vinted_card_drop_{active_drop.get('id')}_{_safe_js_id(card_ref_key)}"):
        st.markdown(
            _card_static_html(card, proxy_img_func, fp_func, badge=badge, unavailable=unavailable, drop_card=True),
            unsafe_allow_html=True,
        )
        if not unavailable:
            if st.button("Préparer", key=f"prepare_drop_card_{active_drop.get('id')}_{card_ref_key}", width="stretch"):
                drop_qty = max(1, int(card.get("drop_quantity", card.get("quantity", 1)) or 1))
                selected = [_card_with_drop_quantity(card, drop_qty)]
                _select_cards(selected)
                _open_classic_submenu()
                st.rerun()
            posted_label = "Annuler postée" if posted else "Annonce postée"
            if st.button(posted_label, key=f"posted_drop_card_{active_drop.get('id')}_{card_ref_key}", width="stretch"):
                if toggle_drop_card_posted(drops_data, active_drop.get("id"), card_ref_key, not posted):
                    save_vinted_drops(drops_data)
                    st.rerun()
        if st.button("Retirer du drop", key=f"remove_drop_card_{active_drop.get('id')}_{card_ref_key}", width="stretch"):
            if remove_card_from_drop(drops_data, active_drop.get("id"), card_ref_key):
                save_vinted_drops(drops_data)
                st.success("Carte retirée du drop.")
                st.rerun()


def _render_drops_manager(drops_data, available_cards, proxy_img_func, fp_func, mobile):
    with st.expander("+ Nouveau drop", expanded=not bool(drops_data.get("drops"))):
        new_name = st.text_input("Nom du nouveau drop", key="new_vinted_drop_name", placeholder="Ex : Drop Vinted juin")
        if st.button("Créer le drop", key="create_vinted_drop", width="stretch"):
            create_drop(drops_data, new_name)
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
    st.markdown(
        f"""
<div class="ps-vinted-drop-head">
  <strong>{_html_escape(active_drop.get('name', 'Drop sans nom'))}</strong>
  <span>{total_cards} carte(s) · {fp_func(total_value) if total_value else 'Valeur à définir'}</span>
</div>
""",
        unsafe_allow_html=True,
    )

    with st.expander("⚙️ Gérer le drop", expanded=False):
        renamed = st.text_input("Renommer le drop", value=active_drop.get("name", ""), key=f"rename_drop_{active_id}")
        if st.button("Enregistrer le nom", key=f"save_drop_name_{active_id}", width="stretch"):
            if rename_drop(drops_data, active_id, renamed):
                save_vinted_drops(drops_data)
                st.success("Drop renommé.")
                st.rerun()
        st.divider()
        confirm = st.checkbox("Confirmer suppression", key=f"confirm_delete_drop_{active_id}")
        if st.button("Supprimer le drop", key=f"delete_drop_{active_id}", disabled=not confirm, width="stretch"):
            if delete_drop(drops_data, active_id):
                save_vinted_drops(drops_data)
                st.session_state.pop("vinted_active_drop_id", None)
                st.success("Drop supprimé.")
                st.rerun()

    _render_drop_add_search(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile)
    st.divider()
    _render_drop_grid(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile)


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
):
    render_page_header_func("Annonces Vinted", "Assistant de création d'annonces prêtes à copier-coller")
    _inject_vinted_styles()

    d = ld_func()
    cards = _available_cards(d, card_available_qty_func, is_collection_system_lot_func)
    card_by_key = {card["_listing_key"]: card for card in cards}
    if perf_count_func:
        perf_count_func("vinted_cards_available", len(cards))

    if not cards:
        st.info("Aucune carte disponible à la vente pour le moment.")
        return

    mobile = bool(is_mobile_mode_func and is_mobile_mode_func())
    selected_keys = st.session_state.setdefault("vinted_selected_keys", [])
    drops_data = load_vinted_drops()
    active_drop_id = _active_drop_id(drops_data)

    target_submenu = st.session_state.pop("_vinted_submenu_target", None)
    if target_submenu in ("Annonces classiques", "Drops Vinted"):
        st.session_state["vinted_submenu"] = target_submenu

    submenu = st.radio(
        "Sous-menu",
        ["Annonces classiques", "Drops Vinted"],
        horizontal=not mobile,
        key="vinted_submenu",
        label_visibility="collapsed",
    )

    if submenu == "Annonces classiques":
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
    else:
        _render_drops_manager(drops_data, cards, proxy_img_func, fp_func, mobile)

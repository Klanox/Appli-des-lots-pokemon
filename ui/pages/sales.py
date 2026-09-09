"""Vente / Echange page renderer for Pokestock.

This module contains the existing sales/exchange page body. It receives app.py
globals as context to preserve behavior while moving the large page out of app.py.
"""

import html
import os
from copy import deepcopy

from ui.inventory_live_search import inventory_live_search
from core.sale_preview import preview_sale

from core.brocante import BRO_CATEGORIES
from services.brocante_data import load_brocantes
from core.brocante import active_session
from core.trade_economics import (
    aggregate_contributors,
    allocate_received_cards,
    build_trade_id,
    card_historical_unit_cost,
    compute_trade_summary,
    contributors_from_card,
    search_received_cards,
    safe_float,
    safe_int,
)
from services.custom_card_image_service import resolve_custom_card_image
from services.vinted_channels import SALE_CHANNELS
from services.vinted_drops_service import find_drop, link_sale_entry_to_drop, load_vinted_drops
from services.inventory_ordering import card_matches_inventory_query, sort_inventory_records
from ui.badges import card_stamp_label
from ui.infinite_scroll import (
    render_virtual_scroll_sensor,
    stable_list_signature,
)
from ui.sale_virtual_grid import component_v2_available, render_sale_virtual_lot_grid


BRO_CARD_IMAGE_SIZE = "6rem"


def _normalize_image_url(url):
    url = str(url or "").strip()
    if url and "tcgdex.net" in url and not url.split("?", 1)[0].lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return f"{url.rstrip('/')}/high.webp"
    return url


def _sale_image_candidates(card):
    """Resolve every supported card shape through the shared Sale image path."""
    if not isinstance(card, dict):
        return []

    raw_card = card.get("raw_cache_card") if isinstance(card.get("raw_cache_card"), dict) else {}
    candidates = []

    def add(url):
        url = _normalize_image_url(url)
        if not url or url == "__placeholder__":
            return
        if (url.startswith(("card_images/", "card_images\\")) or os.path.exists(url)) and not os.path.exists(url):
            return
        if url not in candidates:
            candidates.append(url)

    try:
        add(resolve_custom_card_image(card))
    except Exception:
        pass

    for source in (card, raw_card):
        for key in (
            "manual_image_path", "manual_image_url", "resolved_collection_image_url",
            "image_url_ja", "image_url_jp", "image_url_japanese", "image_url",
            "image_url_en", "image", "imageUrl",
        ):
            add(source.get(key))
        images = source.get("images") if isinstance(source.get("images"), dict) else {}
        add(images.get("large"))
        add(images.get("small"))

    set_id = card.get("set_id") or raw_card.get("set_id") or ""
    if not set_id:
        card_id = str(card.get("card_id") or card.get("id") or raw_card.get("id") or "")
        if "-" in card_id:
            set_id = card_id.rsplit("-", 1)[0]
    number = card.get("number") or card.get("localId") or raw_card.get("localId") or raw_card.get("number") or ""
    lang = str(card.get("lang") or raw_card.get("lang") or "fr").strip().lower()
    preferred_lang = "ja" if lang in {"ja", "jp", "jap", "japanese"} else "fr"
    add(_tcgdex_image_url(preferred_lang, set_id, number))
    if preferred_lang != "fr":
        add(_tcgdex_image_url("fr", set_id, number))
    add(_tcgdex_image_url("en", set_id, number))
    return candidates


def _sale_image_html(card, *, in_cart=False, width="100%", square_size=None):
    """Render a sale card image with a clean fallback instead of a broken icon."""
    proxy = globals().get("proxy_img", lambda value, *_: value)
    candidates = _sale_image_candidates(card)
    square_style = ""
    image_style = "width:100%;border-radius:12px;"
    placeholder_shape = "aspect-ratio:0.72;width:100%;"
    if square_size:
        safe_size = html.escape(str(square_size), quote=True)
        square_style = (
            f"width:{safe_size};max-width:100%;aspect-ratio:1 / 1;overflow:hidden;"
            "display:flex;align-items:center;justify-content:center;background:#f8fafc;"
            "border:1px solid #e2e8f0;border-radius:8px;"
        )
        image_style = "width:100%;height:100%;object-fit:contain;border-radius:7px;"
        placeholder_shape = "width:100%;height:100%;"
    placeholder = (
        '<div class="sale-img-placeholder" '
        f'style="display:flex;align-items:center;justify-content:center;{placeholder_shape}'
        'border-radius:8px;background:#f8fafc;border:1px dashed #cbd5e1;'
        'color:#64748b;font-weight:800;text-align:center;padding:0.4rem;">'
        'Image indisponible</div>'
    )
    if not candidates:
        return placeholder

    proxied = [html.escape(proxy(url), quote=True) for url in candidates]
    fallback_chain = proxied[1:]
    onerror_parts = []
    if fallback_chain:
        js_array = "[" + ",".join("'" + url.replace("'", "\\'") + "'" for url in fallback_chain) + "]"
        onerror_parts.append(
            "this.dataset.fallbackIndex=this.dataset.fallbackIndex||0;"
            f"const f={js_array};"
            "const i=parseInt(this.dataset.fallbackIndex,10);"
            "if(i<f.length){this.dataset.fallbackIndex=i+1;this.src=f[i];return;}"
        )
    safe_placeholder_js = placeholder.replace("\\", "\\\\").replace("'", "\\'")
    onerror_parts.append(f"this.style.display='none';this.parentElement.innerHTML='{safe_placeholder_js}';")
    onerror = html.escape("".join(onerror_parts), quote=True)
    border = "border:4px solid #22c55e;" if in_cart else ""
    badge = (
        '<div style="position:absolute;top:5px;right:5px;background:#22c55e;color:white;'
        'border-radius:50%;width:24px;height:24px;display:flex;align-items:center;'
        'justify-content:center;font-weight:900;font-size:0.75rem;">OK</div>'
        if in_cart
        else ""
    )
    return (
        f'<div style="position:relative;width:{html.escape(str(width), quote=True)};{square_style}">'
        f'<img src="{proxied[0]}" onerror="{onerror}" style="{image_style}{border}">'
        f'{badge}</div>'
    )


def _sale_image_preload_urls(card, *, limit=1):
    """Return the same first useful image URL as the sale card renderer, without rendering a widget."""
    proxy = globals().get("proxy_img", lambda value, *_: value)
    urls = []
    for url in _sale_image_candidates(card):
        if url in urls:
            continue
        try:
            urls.append(str(proxy(url)))
        except Exception:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _sale_frontend_lot_groups(source_items, fp_func, lot_profitable_func, *, continuous=False):
    groups_by_lot = {}
    lot_order = []
    for li, ci, card, lot, stock in source_items:
        lot_key = "search" if continuous else (lot.get("lot_uid") or li)
        if lot_key not in groups_by_lot:
            groups_by_lot[lot_key] = {
                "lot_idx": li,
                "lot_uid": lot.get("lot_uid"),
                "lot_name": "" if continuous else str(lot.get("nom", "")),
                "hide_header": continuous,
                "cards": [],
            }
            lot_order.append(lot_key)
        card_uid = card.get("card_uid") or f"{lot.get('lot_uid') or li}_{ci}"
        price = safe_float(card.get("suggested_price"), 0.0)
        image_urls = _sale_image_preload_urls(card, limit=1)
        groups_by_lot[lot_key]["cards"].append({
            "card_key": str(card_uid),
            "card_uid": card.get("card_uid"),
            "lot_uid": lot.get("lot_uid"),
            "lot_idx": li,
            "card_idx": ci,
            "name": str(card.get("name", "")),
            "set": str(card.get("set", "")),
            "number": str(card.get("number", "")),
            "price": price,
            "price_label": fp_func(price),
            "stock": int(stock or 0),
            "image_url": image_urls[0] if image_urls else "",
            "stamp_label": card_stamp_label(card),
            "lot_profitable": bool(lot_profitable_func(li, lot)),
        })
    return [groups_by_lot[lot_key] for lot_key in lot_order]


def _received_trade_image_html(card, *, width="45px", square_size=None):
    """Render a received-trade preview image without leaving a broken icon."""
    _normalize_received_trade_image_fields(card)
    return _sale_image_html(card, width=width, square_size=square_size)


def _tcgdex_series_from_set_id(set_id):
    set_id = str(set_id or "").strip()
    prefix = []
    for char in set_id:
        if char.isalpha():
            prefix.append(char)
        else:
            break
    return "".join(prefix)


def _tcgdex_image_url(lang, set_id, number):
    set_id = str(set_id or "").strip()
    number = str(number or "").strip()
    series = _tcgdex_series_from_set_id(set_id)
    if not (lang and series and set_id and number):
        return ""
    return f"https://assets.tcgdex.net/{lang}/{series}/{set_id}/{number}/high.webp"


def _normalize_received_trade_image_fields(card):
    """Preserve TCGDex image fields under the names used by the UI and Trade lot."""
    if not isinstance(card, dict):
        return card

    raw_card = card.get("raw_cache_card") if isinstance(card.get("raw_cache_card"), dict) else {}
    if not raw_card and not (card.get("image_url") or card.get("image")):
        st_obj = globals().get("st")
        normalize_func = globals().get("normalize_name")
        cards_index = getattr(getattr(st_obj, "session_state", {}), "get", lambda *_: {})("cards_index", {}) if st_obj is not None else {}
        if callable(normalize_func) and isinstance(cards_index, dict) and card.get("name"):
            wanted_number = str(card.get("number") or "").strip().lstrip("0")
            for found_card, found_set_name, found_set_id in search_received_cards(card.get("name"), cards_index, normalize_func, limit=24):
                found_number = str(found_card.get("localId") or found_card.get("number") or "").strip().lstrip("0")
                if wanted_number and found_number != wanted_number:
                    continue
                raw_card = found_card
                card.setdefault("set", found_set_name)
                card.setdefault("set_id", found_set_id)
                break

    images = raw_card.get("images") if isinstance(raw_card.get("images"), dict) else {}

    image_url = (
        card.get("image_url")
        or card.get("image")
        or card.get("imageUrl")
        or raw_card.get("image_url")
        or raw_card.get("image")
        or raw_card.get("imageUrl")
        or images.get("large")
        or images.get("small")
        or ""
    )
    if image_url and "tcgdex.net" in str(image_url) and not str(image_url).endswith((".jpg", ".jpeg", ".png", ".webp")):
        image_url = f"{image_url}/high.webp"

    set_id = card.get("set_id") or raw_card.get("set_id") or ""
    if not set_id:
        card_id = str(card.get("card_id") or card.get("id") or raw_card.get("id") or "")
        if "-" in card_id:
            set_id = card_id.rsplit("-", 1)[0]
    number = card.get("number") or raw_card.get("localId") or raw_card.get("number") or ""

    if not image_url:
        custom_image_url = resolve_custom_card_image(
            {
                **card,
                "card_id": card.get("card_id") or card.get("id") or raw_card.get("id"),
                "id": card.get("id") or raw_card.get("id"),
                "set_id": set_id,
                "number": number,
            }
        )
        if custom_image_url:
            image_url = custom_image_url

    if not image_url:
        image_url = _tcgdex_image_url("fr", set_id, number)
    image_url_en = card.get("image_url_en") or _tcgdex_image_url("en", set_id, number)
    image_url_ja = card.get("image_url_ja") or _tcgdex_image_url("ja", set_id, number)

    if image_url:
        card["image_url"] = str(image_url)
    if image_url_en:
        card["image_url_en"] = str(image_url_en)
    if image_url_ja:
        card["image_url_ja"] = str(image_url_ja)
    if set_id and not card.get("set_id"):
        card["set_id"] = str(set_id)
    return card


def _selected_trade_given_records(cd, selected_cards):
    """Resolve selected UI cards back to stock cards and compute real costs."""
    records = []
    for selected in selected_cards:
        li, ci, lot, card = resolve_card_ref(cd, selected)
        if li is None or card is None:
            continue
        available_qty = card_available_qty(card)
        quantity = max(safe_int(selected.get("quantity"), 1), 1)
        unit_reference_value = safe_float(selected.get("value"), safe_float(card.get("suggested_price")))
        unit_historical_cost = card_historical_unit_cost(lot, card)
        reference_value = unit_reference_value * quantity
        historical_cost = unit_historical_cost * quantity
        contributors = contributors_from_card(li, lot, card, historical_cost)
        selected["lot_idx"], selected["card_idx"] = li, ci
        selected["quantity"] = quantity
        selected["historical_cost"] = historical_cost
        selected["lot_uid"] = lot.get("lot_uid")
        selected["lot_name"] = lot.get("nom", selected.get("lot_name", ""))
        records.append({
            "lot_idx": li,
            "card_idx": ci,
            "lot": lot,
            "card": card,
            "reference_value": reference_value,
            "unit_reference_value": unit_reference_value,
            "historical_cost": historical_cost,
            "unit_historical_cost": unit_historical_cost,
            "quantity": quantity,
            "available_qty": available_qty,
            "contributors": contributors,
            "ui": selected,
        })
    return records


def _request_sale_scroll_top():
    st.session_state["sale_scroll_top_token"] = int(st.session_state.get("sale_scroll_top_token", 0) or 0) + 1


def _off_stock_drop_preview(canal):
    try:
        drops_data = deepcopy(load_vinted_drops())
        preview_sale = {"sale_id": "preview_off_stock", "date": "", "price": 0.0, "quantity": 0}
        if not link_sale_entry_to_drop(drops_data, preview_sale, canal):
            return None
        return find_drop(drops_data, preview_sale.get("drop_id"))
    except Exception:
        return None


def _queue_classic_off_stock(lot_choices, stock_data):
    amount = float(st.session_state.get("classic_offstock_amount", 0) or 0)
    if amount <= 0:
        st.session_state["classic_offstock_flash"] = ("error", "Saisis un prix encaissé supérieur à 0 €.")
        return

    quantity = max(int(st.session_state.get("classic_offstock_quantity", 1) or 1), 1)
    lot_label = st.session_state.get("classic_offstock_lot")
    source_lot_idx = next((value for label, value in lot_choices if label == lot_label), None)
    source_lot = None
    if source_lot_idx is not None and 0 <= int(source_lot_idx) < len(stock_data.get("lots", []) or []):
        source_lot = stock_data["lots"][int(source_lot_idx)]

    cart_was_empty = not st.session_state.get("bulk_cart")
    preferred_channel = st.session_state.get("classic_offstock_channel") or SALE_CHANNELS[0]
    brocante_data = load_brocantes()
    active_bro = active_session(brocante_data)
    bulk_cart_add_off_stock({
        "category": st.session_state.get("classic_offstock_category") or BRO_CATEGORIES[0],
        "description": st.session_state.get("classic_offstock_desc") or "",
        "quantity": quantity,
        "amount": amount,
        "payment_method": "Non renseigné",
        "preferred_channel": preferred_channel,
        "source_lot_idx": source_lot_idx,
        "source_lot_id": (source_lot or {}).get("lot_uid"),
        "source_lot_name": (source_lot or {}).get("nom") or "Non attribuée",
        "cost_basis_known": False,
        "cost_basis": None,
        "notes": "",
        "brocante_id": active_bro.get("id") if active_bro else None,
    })
    st.session_state["classic_offstock_amount"] = 0.0
    st.session_state["classic_offstock_quantity"] = 1
    st.session_state["classic_offstock_desc"] = ""
    if cart_was_empty:
        st.session_state["canal_bulk_sel"] = preferred_channel
    st.session_state["classic_offstock_flash"] = ("success", "Article hors stock ajouté au panier.")


def _allocate_final_sale_price(cart_items, final_price):
    """Return cart items with unit prices that sum exactly to the buyer-paid total."""
    rows = list(cart_items or [])
    final_price = round(max(float(final_price or 0.0), 0.0), 2)
    base_totals = [
        max(float(item.get("quantity", 1) or 1), 0.0) * max(float(item.get("price_base", 0.0) or 0.0), 0.0)
        for item in rows
    ]
    total_base = sum(base_totals)
    if not rows:
        return []
    if total_base <= 0:
        equal = round(final_price / len(rows), 2)
        line_totals = [equal for _ in rows]
        line_totals[-1] = round(final_price - sum(line_totals[:-1]), 2)
    else:
        line_totals = []
        allocated = 0.0
        for index, base_total in enumerate(base_totals):
            if index == len(rows) - 1:
                line_total = round(final_price - allocated, 2)
            else:
                line_total = round(final_price * (base_total / total_base), 2)
                allocated = round(allocated + line_total, 2)
            line_totals.append(max(line_total, 0.0))

    sale_items = []
    for item, line_total in zip(rows, line_totals):
        qty = max(int(item.get("quantity", 1) or 1), 1)
        sale_items.append({**item, "unit_price": line_total / qty})
    return sale_items


def render_sales_page(context):
    globals().update(context)
    brocante = context.get("brocante_session")
    if st.session_state.pop("sale_scroll_top_pending", False):
        _request_sale_scroll_top()
    if not brocante:
        st.markdown(
            render_page_header("Vente / Échange", "Vendre, négocier et gérer les échanges", "💰"),
            unsafe_allow_html=True,
        )
    
    try:
        query_section = str(st.query_params.get("page", "")).lower()
    except Exception:
        query_section = ""
    default_sales_section = "Échange" if query_section in ("echange", "échange") else "Vente"
    if "sales_active_section" not in st.session_state:
        st.session_state["sales_active_section"] = default_sales_section
    active_sales_section = context.get("brocante_section", "Vente") if brocante else st.segmented_control(
        "Section",
        ["Vente", "Échange"],
        key="sales_active_section",
        format_func=lambda value: "💰 Vente" if value == "Vente" else "🔄 Échange",
        label_visibility="collapsed",
        width="stretch",
    ) or default_sales_section
    previous_sales_section = st.session_state.get("_previous_sales_active_section")
    if active_sales_section == "Vente" and previous_sales_section == "Échange":
        _request_sale_scroll_top()
    st.session_state["_previous_sales_active_section"] = active_sales_section

    if active_sales_section == "Vente":
        st.markdown('<span data-sale-mobile-marker="1"></span>', unsafe_allow_html=True)
        st.subheader("Vente")
        
        cd=ld()
        if not cd.get("lots"):
            st.warning("Créez d'abord un lot")
        else:
            if "bulk_cart" not in st.session_state:
                st.session_state.bulk_cart = []
            if brocante and st.session_state.bulk_cart:
                st.caption("Panier courant · la commande sera enregistrée pour cette brocante.")

            flash = st.session_state.pop("classic_offstock_flash", None)
            if flash:
                getattr(st, flash[0])(flash[1])

            if not brocante:
                with st.expander("Vente hors stock", expanded=False):
                    st.caption("Pour petites cartes, accessoires ou lots non suivis. Le stock n'est pas diminué.")
                    if st.session_state.get("classic_offstock_category") not in BRO_CATEGORIES:
                        st.session_state["classic_offstock_category"] = BRO_CATEGORIES[0]
                    if st.session_state.get("classic_offstock_channel") not in SALE_CHANNELS:
                        st.session_state["classic_offstock_channel"] = SALE_CHANNELS[0]
                    hs1, hs2 = st.columns(2)
                    hs_category = hs1.selectbox("Catégorie", list(BRO_CATEGORIES), key="classic_offstock_category")
                    hs_channel = hs2.selectbox("Canal de vente", list(SALE_CHANNELS), key="classic_offstock_channel")
                    lot_choices = [("Non attribuée", None)] + [
                        (f"{idx + 1}. {lot.get('nom', f'Lot {idx + 1}')}", idx)
                        for idx, lot in enumerate(cd.get("lots", []) or [])
                    ]
                    hs3, hs4, hs5 = st.columns([2, 0.7, 1])
                    hs_lot_label = hs3.selectbox("Lot source", [label for label, _ in lot_choices], key="classic_offstock_lot")
                    hs_source_lot_idx = next(value for label, value in lot_choices if label == hs_lot_label)
                    hs4.number_input("Quantité", 1, 9999, 1, 1, key="classic_offstock_quantity")
                    hs_amount = hs5.number_input("Prix total (€)", 0.0, 99999.0, 0.0, 0.5, key="classic_offstock_amount")
                    hs_desc = st.text_input(
                        "Description facultative",
                        key="classic_offstock_desc",
                        placeholder="Ex : Petit lot de promos + holo",
                    )
                    linked_drop = _off_stock_drop_preview(hs_channel)
                    if linked_drop:
                        st.caption(f"🔗 Drop associé automatiquement : {linked_drop.get('name', 'Drop sans nom')}")
                    else:
                        st.caption("Aucun drop actif associé")
                    st.button(
                        "Ajouter au panier",
                        type="primary",
                        width="stretch",
                        key="classic_offstock_save",
                        on_click=_queue_classic_off_stock,
                        args=(lot_choices, cd),
                    )

            # ── Recherche live, filtre secondaire et accès panier ──
            vente_lots_with_idx = sorted(
                list(enumerate(cd.get("lots", []))),
                key=lambda item: (1 if (is_trade_lot(item[1]) or is_storage_lot(item[1])) else 0, item[0]),
            )
            lot_options = [("Tous les lots", None)] + [
                (f"{i+1}. {lot.get('nom', f'Lot {i+1}')}", i)
                for i, lot in vente_lots_with_idx
            ]
            lot_labels = [name for name, _ in lot_options]
            brocante_mobile = bool(brocante and is_mobile_mode())
            if brocante_mobile:
                search_vente = inventory_live_search(
                    "🔍 Rechercher une carte", key="search_vente_live",
                    placeholder="Nom, numéro, extension...",
                )
                with st.expander("Filtrer le lot", expanded=False):
                    selected_lot_label = st.selectbox("Lot affiché", lot_labels, key="bulk_lot_filter_v2")
                nb_panier = sum(item["quantity"] for item in st.session_state.bulk_cart)
                total_panier = sum(item["quantity"] * item["price_base"] for item in st.session_state.bulk_cart)
                st.button(
                    f"🛒 Panier · {nb_panier} · {fp(total_panier)}" if nb_panier else "🛒 Panier vide",
                    key="btn_panier",
                    width="stretch",
                    type="primary" if nb_panier else "secondary",
                    on_click=scroll_to_cart_prepare if nb_panier else None,
                )
            else:
                col_search, col_lot_filter, col_cart = st.columns([3, 2, 1])
                with col_search:
                    search_vente = inventory_live_search(
                        "🔍 Rechercher une carte", key="search_vente_live",
                        placeholder="Nom de la carte...",
                    )
                with col_lot_filter:
                    selected_lot_label = st.selectbox("Lot affiché", lot_labels, key="bulk_lot_filter_v2", label_visibility="collapsed")
                with col_cart:
                    nb_panier = sum(item["quantity"] for item in st.session_state.bulk_cart)
                    total_panier = sum(item["quantity"] * item["price_base"] for item in st.session_state.bulk_cart)
                    if nb_panier > 0:
                        st.button(f"🛒 {nb_panier} · {fp(total_panier)}", key="btn_panier", width="stretch", type="primary", on_click=scroll_to_cart_prepare)
                    else:
                        st.markdown('<div style="background:#e2e8f0;color:#64748b;padding:0.5rem 1rem;border-radius:12px;font-weight:700;text-align:center;">🛒 Vide</div>', unsafe_allow_html=True)
            selected_lot_idx = next(idx for name, idx in lot_options if name == selected_lot_label)
            st.markdown(f'<a class="codex-floating-cart" href="#cart-anchor" aria-label="Aller au panier">🛒<span>{nb_panier}</span></a>', unsafe_allow_html=True)
            run_html(f"""
            <script>
            (function(){{
                const win = parent.window;
                const doc = parent.document;
                let btn = doc.getElementById('codex-floating-cart-button');
                if (!btn) {{
                    btn = doc.createElement('button');
                    btn.id = 'codex-floating-cart-button';
                    btn.type = 'button';
                    doc.body.appendChild(btn);
                }}
                const shouldShow = win.matchMedia('(max-width: 760px), (pointer: coarse) and (max-width: 900px)').matches;
                btn.innerHTML = '🛒<span>{nb_panier}</span>';
                btn.setAttribute('aria-label', 'Aller au panier');
                Object.assign(btn.style, {{
                    position: 'fixed',
                    right: '14px',
                    bottom: 'calc(96px + env(safe-area-inset-bottom, 0px))',
                    width: '56px',
                    height: '56px',
                    borderRadius: '999px',
                    border: '3px solid #ffffff',
                    background: '#22c55e',
                    color: '#ffffff',
                    display: shouldShow ? 'flex' : 'none',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '25px',
                    fontWeight: '900',
                    zIndex: '2147483000',
                    boxShadow: '0 8px 22px rgba(15, 23, 42, 0.32)',
                    cursor: 'pointer',
                    padding: '0',
                    lineHeight: '1'
                }});
                const badge = btn.querySelector('span');
                Object.assign(badge.style, {{
                    position: 'absolute',
                    top: '-8px',
                    right: '-8px',
                    minWidth: '22px',
                    height: '22px',
                    padding: '0 4px',
                    borderRadius: '999px',
                    background: '#ef4444',
                    color: '#ffffff',
                    border: '2px solid #ffffff',
                    fontSize: '12px',
                    lineHeight: '18px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                }});
                btn.onclick = function(e) {{
                    e.preventDefault();
                    win.sessionStorage.setItem('codexSkipSaleTopOnce', '1');
                    const el = doc.getElementById('cart-anchor');
                    if (el) el.scrollIntoView({{behavior:'smooth', block:'start'}});
                }};
            }})();
            </script>
            """, height=0)

            # Scroll vers le panier si demandé
            if st.session_state.get("scroll_to_cart"):
                st.session_state["scroll_to_cart"] = False
                run_html('<script>setTimeout(()=>{const el=parent.document.getElementById("cart-anchor");if(el)el.scrollIntoView({behavior:"smooth"});},200);</script>', height=0)

            # Construire liste panier pour verification rapide
            cart_keys = {item.get("card_uid") for item in st.session_state.bulk_cart if item.get("card_uid")}
            mobile_search_text = str(search_vente or "").strip()
            sale_records = []
            if not brocante_mobile or mobile_search_text:
                for li, lot in vente_lots_with_idx:
                    if selected_lot_idx is not None and li != selected_lot_idx:
                        continue
                    for ci, card in enumerate(lot.get("cards", [])):
                        stock = card_available_qty(card)
                        if stock <= 0 or card.get("cost_basis_pending"):
                            continue
                        if brocante_mobile and not card_matches_inventory_query(card, mobile_search_text):
                            continue
                        sale_records.append({
                            "lot_idx": li,
                            "card_idx": ci,
                            "card": card,
                            "lot": lot,
                            "stock": stock,
                        })
            all_sale_items = [
                (record["lot_idx"], record["card_idx"], record["card"], record["lot"], record["stock"])
                for record in (sort_inventory_records(sale_records) if search_vente.strip() else sale_records)
            ]
            if brocante_mobile:
                search_scope = f"{mobile_search_text}|{selected_lot_idx}"
                if st.session_state.get("brocante_sale_search_scope") != search_scope:
                    st.session_state["brocante_sale_search_scope"] = search_scope
                    st.session_state["brocante_sale_result_limit"] = 24
                result_limit = max(int(st.session_state.get("brocante_sale_result_limit", 24) or 24), 24)
                sale_items = all_sale_items[:result_limit]
            else:
                sale_items = all_sale_items

            lot_profitable_cache = {}

            def sale_lot_profitable(li, lot):
                if li not in lot_profitable_cache:
                    lot_profitable_cache[li] = cp(lot) >= 0
                return lot_profitable_cache[li]

            @st.fragment
            def render_sales_progressive_grid(search_text, selected_lot, items, cart_card_uids):
                def render_sale_card(li, ci, card, lot, stock, *, include_lot_caption=False):
                    in_cart = card.get("card_uid") in cart_card_uids
                    with st.container(key=f"search_result_card_sales_{'search' if include_lot_caption else 'lot'}_{li}_{ci}"):
                        st.markdown(_sale_image_html(card, in_cart=in_cart), unsafe_allow_html=True)
                        st.markdown(f"**{card['name']}**")
                        st.caption(f"#{card.get('number','')}" if is_mobile_mode() else f"{card.get('set','')} - #{card.get('number','')}")
                        st.caption(f"Prix {fp(card.get('suggested_price', 0))} - Stock {stock}")
                        if include_lot_caption and not is_mobile_mode():
                            st.caption(f"Lot {lot['nom']}")
                        q_key = card.get("card_uid") or f"{li}_{ci}"
                        q_add = st.number_input("Qté", 1, stock, 1, key=f"bulk_q_{q_key}")
                        if in_cart:
                            if st.button(
                                "Dans le panier",
                                key=f"add_{li}_{ci}",
                                width="stretch",
                            ):
                                bulk_cart_remove(card_uid=card.get("card_uid"))
                                st.rerun()
                        else:
                            if st.button(
                                "Ajouter",
                                key=f"add_{li}_{ci}",
                                width="stretch",
                                type="primary",
                            ):
                                bulk_cart_add({
                                    "lot_idx": li,
                                    "card_idx": ci,
                                    "lot_uid": lot.get("lot_uid"),
                                    "card_uid": card.get("card_uid"),
                                    "lot_name": lot["nom"],
                                    "card_name": card["name"],
                                    "card_set": card.get("set", ""),
                                    "quantity": q_add,
                                    "price_base": card.get("suggested_price", 0),
                                    "lot_profitable": sale_lot_profitable(li, lot),
                                })
                                st.rerun()

                def render_sale_grid_rows(scope, row_items, *, include_lot_caption=False, row_index_offset=0):
                    slots_per_row = 2 if is_mobile_mode() else 6
                    for row_start in range(0, len(row_items), slots_per_row):
                        row_index = (int(row_index_offset) + row_start) // slots_per_row
                        row = row_items[row_start:row_start + slots_per_row]
                        with st.container(
                            key=f"search_results_grid_sales_{scope}_row_{row_index}",
                            horizontal=True,
                            gap="small",
                        ):
                            for li, ci, card, lot, stock in row:
                                render_sale_card(
                                    li,
                                    ci,
                                    card,
                                    lot,
                                    stock,
                                    include_lot_caption=include_lot_caption,
                                )
                            for spacer_index in range(slots_per_row - len(row)):
                                with st.container(
                                    key=(
                                        f"search_result_card_sales_spacer_"
                                        f"{scope}_{row_index}_{spacer_index}"
                                    )
                                ):
                                    st.empty()

                def render_continuous_sale_items(scope_prefix, source_items, *, row_index_offset=0):
                    render_sale_grid_rows(
                        scope_prefix,
                        source_items,
                        include_lot_caption=True,
                        row_index_offset=row_index_offset,
                    )

                def preload_urls_for(source_items, start, end):
                    urls = []
                    for _, _, card, _, _ in list(source_items or [])[max(0, start):max(0, end)]:
                        urls.extend(_sale_image_preload_urls(card))
                        if len(urls) >= 32:
                            break
                    return urls[:32]

                def current_progressive_count(key_prefix, fallback_initial, total):
                    count = int(st.session_state.get(f"{key_prefix}_visible_count", fallback_initial) or fallback_initial)
                    return max(0, min(count, total))

                def progressive_sale_slice(key_prefix, source_items, signature, *, initial_count, step_count, event=None):
                    source_items = list(source_items or [])
                    total = len(source_items)
                    signature_key = f"{key_prefix}_progressive_signature"
                    count_key = f"{key_prefix}_visible_count"
                    event_key = f"{key_prefix}_progressive_last_event"
                    if st.session_state.get(signature_key) != signature:
                        st.session_state[signature_key] = signature
                        st.session_state[count_key] = min(int(initial_count), total)
                        st.session_state.pop(event_key, None)

                    visible_count = current_progressive_count(key_prefix, initial_count, total)
                    if isinstance(event, dict):
                        event_id = str(event.get("id") or "")
                        direction = str(event.get("direction") or "")
                        if event_id and direction == "down" and st.session_state.get(event_key) != event_id:
                            st.session_state[event_key] = event_id
                            visible_count = min(total, visible_count + max(1, int(step_count)))
                            st.session_state[count_key] = visible_count

                    return source_items[:visible_count], visible_count, total

                def render_progressive_group(key_prefix, scope_prefix, source_items, signature):
                    source_items = list(source_items or [])
                    signature_changed = st.session_state.get(f"{key_prefix}_progressive_signature") != signature
                    previous_count = (
                        min(sale_initial, len(source_items))
                        if signature_changed
                        else current_progressive_count(key_prefix, sale_initial, len(source_items))
                    )
                    bottom_anchor_id = f"sale-progressive-bottom-{key_prefix}"
                    event = None
                    if previous_count < len(source_items):
                        event = render_virtual_scroll_sensor(
                            key_prefix,
                            top_anchor_id=f"sale-progressive-top-{key_prefix}",
                            bottom_anchor_id=bottom_anchor_id,
                            row_selector=(
                                f'[class*="st-key-search_results_grid_sales_{scope_prefix}_"]'
                                '[data-testid="stHorizontalBlock"]'
                            ),
                            root_margin_px=1800,
                            top_margin_px=900,
                            preload_urls=preload_urls_for(
                                source_items,
                                previous_count,
                                previous_count + sale_step * 2,
                            ),
                            default_row_height=sale_row_height_default,
                        )
                    if signature_changed:
                        event = None
                    visible_items, visible_count, total_count = progressive_sale_slice(
                        key_prefix,
                        source_items,
                        signature,
                        initial_count=sale_initial,
                        step_count=sale_step,
                        event=event,
                    )
                    if "perf_count" in globals():
                        perf_count("cards_sales_available", total_count)
                        perf_count("cards_sales_rendered", len(visible_items))
                    if search_text:
                        render_continuous_sale_items(scope_prefix, visible_items)
                    else:
                        by_lot = {}
                        for item in visible_items:
                            by_lot.setdefault(item[0], []).append(item)
                        for li, lot_items in by_lot.items():
                            st.markdown(f"### Lot {lot_items[0][3]['nom']}")
                            render_sale_grid_rows(f"{scope_prefix}_lot_{li}", lot_items)
                            st.markdown("---")
                    if visible_count < total_count:
                        st.markdown(
                            f'<div id="{bottom_anchor_id}" style="height:1px;"></div>',
                            unsafe_allow_html=True,
                        )

                search_text = str(search_text or "").strip()
                sale_initial = 24 if is_mobile_mode() else 48
                sale_step = 12 if is_mobile_mode() else 24
                sale_row_height_default = 520 if is_mobile_mode() else 560
                st.markdown(
                    """
                    <style>
                    [class*="st-key-search_results_grid_sales_"],
                    [class*="st-key-search_result_card_sales_"] {
                        overflow-anchor: none !important;
                    }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )

                # Une seule grille continue, dans l'ordre réel d'acquisition.
                if search_text:
                    filtered_items = [
                        item for item in items
                        if card_matches_inventory_query(item[2], search_text)
                    ]
                    sale_signature = stable_list_signature(
                        "sales_search",
                        search_text,
                        selected_lot,
                        [(li, ci, card.get("card_uid") or card.get("name")) for li, ci, card, _, _ in filtered_items],
                    )
                    render_progressive_group("sales_search", "search", filtered_items, sale_signature)
                else:
                    sale_signature = stable_list_signature(
                        "sales_all",
                        selected_lot,
                        [(li, ci, card.get("card_uid") or card.get("name")) for li, ci, card, _, _ in items],
                    )
                    render_progressive_group("sales_all", "all", items, sale_signature)

            def render_sales_frontend_lot_grid(search_text, selected_lot, items, cart_card_uids):
                search_text = str(search_text or "").strip()
                if search_text:
                    filtered_items = [
                        item for item in items
                        if card_matches_inventory_query(item[2], search_text)
                    ]
                    grid_key = "sales_search"
                else:
                    filtered_items = list(items or [])
                    grid_key = "sales_all"

                groups = _sale_frontend_lot_groups(filtered_items, fp, sale_lot_profitable, continuous=bool(search_text))
                try:
                    result = render_sale_virtual_lot_grid(
                        groups,
                        cart_card_uids,
                        key=grid_key,
                        mobile=is_mobile_mode(),
                        scroll_top_token=st.session_state.get("sale_scroll_top_token", 0),
                    )
                except Exception as exc:
                    st.session_state["sale_frontend_lot_grid_error"] = str(exc)
                    return False

                action = getattr(result, "action", None) if result is not None else None
                if isinstance(action, dict) and action.get("type") in ("add", "remove"):
                    action_id = str(action.get("id") or "")
                    if action_id and st.session_state.get("sale_frontend_lot_last_action") != action_id:
                        st.session_state["sale_frontend_lot_last_action"] = action_id
                        if action.get("type") == "remove":
                            bulk_cart_remove(
                                lot_idx=safe_int(action.get("lot_idx"), None),
                                card_idx=safe_int(action.get("card_idx"), None),
                                card_uid=action.get("card_uid"),
                            )
                        else:
                            bulk_cart_add({
                                "lot_idx": safe_int(action.get("lot_idx"), 0),
                                "card_idx": safe_int(action.get("card_idx"), 0),
                                "lot_uid": action.get("lot_uid"),
                                "card_uid": action.get("card_uid"),
                                "quantity": max(safe_int(action.get("quantity"), 1), 1),
                                "lot_profitable": bool(action.get("lot_profitable")),
                            })
                        st.rerun()
                if "perf_count" in globals():
                    perf_count("cards_sales_available", sum(len(group.get("cards", [])) for group in groups))
                    perf_count("cards_sales_rendered", 0)
                return True

            frontend_lot_grid_ok = False
            if brocante_mobile and not mobile_search_text:
                st.caption("Recherche une carte pour commencer.")
                frontend_lot_grid_ok = True
            elif component_v2_available() and not st.session_state.get("sale_frontend_lot_grid_disabled", False):
                frontend_lot_grid_ok = render_sales_frontend_lot_grid(search_vente, selected_lot_idx, sale_items, cart_keys)
            if not frontend_lot_grid_ok:
                render_sales_progressive_grid(search_vente, selected_lot_idx, sale_items, cart_keys)
            if brocante_mobile and len(all_sale_items) > len(sale_items):
                st.caption(f"{len(sale_items)} résultats affichés sur {len(all_sale_items)}")
                if st.button("Afficher 24 résultats de plus", key="brocante_sale_more", width="stretch"):
                    st.session_state["brocante_sale_result_limit"] = len(sale_items) + 24
                    st.rerun()

            # Panier
            st.markdown('<div id="cart-anchor"></div>', unsafe_allow_html=True)
            if not st.session_state.bulk_cart:
                st.info("📭 Panier vide - Cliquez sur 🛒 Ajouter pour ajouter des cartes")
            else:
                cart_brocante = locals().get("brocante")
                st.markdown("### 🛒 Panier")
                
                for idx, item in enumerate(st.session_state.bulk_cart):
                    is_off_stock = bool(item.get("is_off_stock") or item.get("line_type") == "off_stock")
                    cart_card = None
                    if not is_off_stock:
                        _, _, _, cart_card = resolve_card_ref(cd, item)
                    max_cart_qty = 9999 if is_off_stock else (max(card_available_qty(cart_card), 1) if cart_card else int(item["quantity"]))
                    if int(item["quantity"]) > max_cart_qty:
                        item["quantity"] = max_cart_qty
                        save_activity_state()
                    line_badge = " · Hors stock" if is_off_stock else ""
                    if cart_brocante and is_mobile_mode():
                        cols = st.columns([3, 1, 1])
                        cols[0].write(f"{item['card_name']}{line_badge}")
                        cols[0].caption(f"{fp(item['price_base'])}/u · {fp(item['quantity'] * item['price_base'])}")
                        cols[1].number_input("Qté", 1, max_cart_qty, int(item["quantity"]), key=f"cart_qty_{idx}", on_change=bulk_cart_set_quantity, args=(idx,), label_visibility="collapsed")
                        cols[2].button("Retirer", key=f"remove_{idx}", on_click=bulk_cart_pop, args=(idx,), width="stretch")
                    else:
                        cols = st.columns([3, 1, 1, 1, 1, 1])
                        cols[0].write(f"{item['card_name']} ({item['card_set']}) - {item['lot_name']}{line_badge}")
                        cols[1].number_input("Qté", 1, max_cart_qty, int(item["quantity"]), key=f"cart_qty_{idx}", on_change=bulk_cart_set_quantity, args=(idx,), label_visibility="collapsed")
                        cols[2].write(f"{fp(item['price_base'])}/u")
                        cols[3].write(f"= {fp(item['quantity'] * item['price_base'])}")
                        cols[4].button("➕", key=f"plus_{idx}", on_click=bulk_cart_increment, args=(idx,))
                        cols[5].button("🗑️", key=f"remove_{idx}", on_click=bulk_cart_pop, args=(idx,))
                
                total_base = sum(item["quantity"] * item["price_base"] for item in st.session_state.bulk_cart)
                st.markdown("---")
                st.markdown(f"**Prix total de base : {fp(total_base)}**")
                if cart_brocante:
                    physical_count = sum(int(item["quantity"]) for item in st.session_state.bulk_cart
                                         if not (item.get("is_off_stock") or item.get("line_type") == "off_stock"))
                    st.caption(f"{physical_count} carte(s) physique(s) · une commande Brocante")
                
                vente_col1, vente_col2 = st.columns(2)
                
                with vente_col1:
                    st.button("✅ Vendre au prix de base", type="primary", width="stretch", on_click=bulk_sale_prepare, args=("base", total_base))
                
                    total_base_ref = round(float(total_base), 2)
                    if st.session_state.get("negociated_price_base_ref") != total_base_ref:
                        st.session_state["negociated_price"] = total_base_ref
                        st.session_state["negociated_price_base_ref"] = total_base_ref
                    negociated_price = st.number_input(
                        "💰 Prix final",
                        min_value=0.0,
                        step=0.5,
                        key="negociated_price",
                    )
                    st.button("🤝 Vendre au prix final", width="stretch", on_click=bulk_sale_prepare, args=("negociated", negociated_price))

                with vente_col2:
                    for label, preview_items in (
                        ("Au prix de base", [{**item, "unit_price": item["price_base"]} for item in st.session_state.bulk_cart]),
                        ("Au prix final", _allocate_final_sale_price(st.session_state.bulk_cart, negociated_price)),
                    ):
                        estimate = preview_sale(cd, preview_items, resolve_card=resolve_card_ref,
                                                calc_cost=calc_cout_lot, effective_purchase_price=effective_purchase_price)
                        st.caption(label)
                        if cart_brocante and estimate["profit"] is not None:
                            st.caption(f"Coût historique : {fp(estimate['total'] - estimate['profit'])}")
                        if estimate["profit"] is None:
                            st.markdown(f"**Bénéfice estimé partiel : {fp(estimate['known_profit'])}**")
                            st.caption(f"{estimate['unknown_lines']} ligne(s) sans coût fiable, exclue(s) de l'estimation.")
                        else:
                            tone = "#15803d" if estimate["profit"] >= 0 else "#be123c"
                            st.markdown(f'<p style="color:{tone};font-weight:600">Bénéfice estimé : {html.escape(fp(estimate["profit"]))}</p>', unsafe_allow_html=True)

                # Dialog canal pour vente en lot
                if st.session_state.get("show_canal_dialog_bulk"):
                    st.session_state["show_canal_dialog_bulk"] = False
                    pending = st.session_state.get("pending_bulk_sale", {})

                    @st.dialog("📡 Canal de vente")
                    def ask_canal_bulk():
                        st.markdown(f"**Vente — {fp(pending.get('price', 0))}**")
                        CANAUX = list(SALE_CHANNELS)
                        event_args = {}
                        cash_missing = False
                        if cart_brocante:
                            from core.brocante import PAYMENT_METHODS, payment_key
                            st.caption(f"Brocante · {cart_brocante['name']}")
                            payment = st.selectbox("Paiement", PAYMENT_METHODS, key="bro_sale_payment")
                            if payment_key(payment) == "cash":
                                tendered = st.number_input("Montant donné", min_value=0.0, value=float(pending.get("price", 0)), step=0.5)
                                change = tendered - float(pending.get("price", 0))
                                cash_missing = change < -0.005
                                st.caption(f"Monnaie à rendre : {fp(max(change, 0))}")
                            attempt_key = f"bro_sale_attempt_{cart_brocante['id']}"
                            st.session_state.setdefault(attempt_key, new_uid("sale_tx"))
                            event_args = dict(brocante_id=cart_brocante["id"], payment_method=payment,
                                              transaction_id=st.session_state[attempt_key])
                            canal_b = "Brocante"
                        else:
                            canal_b = st.selectbox("Via quel canal ?", CANAUX, key="canal_bulk_sel")
                        c1, c2 = st.columns(2)
                        if c1.button("✅ Confirmer", type="primary", width="stretch", disabled=cash_missing):
                            if pending.get("type") == "base":
                                sale_items = [
                                    {**item, "unit_price": item["price_base"]}
                                    for item in st.session_state.bulk_cart
                                ]
                            else:
                                sale_items = _allocate_final_sale_price(
                                    st.session_state.bulk_cart,
                                    pending["price"],
                                )
                            ok, msg = scu_many(sale_items, canal_b, **event_args)
                            if ok:
                                if cart_brocante:
                                    st.session_state.pop(attempt_key, None)
                                st.session_state.bulk_cart = []
                                st.session_state["pending_bulk_sale"] = {}
                                st.session_state["show_canal_dialog_bulk"] = False
                                save_activity_state()
                            else:
                                st.error(msg)
                            st.rerun()
                        if c2.button("❌ Annuler", width="stretch"):
                            st.rerun()

                    ask_canal_bulk()
                
                st.button("🗑️ Vider le panier", on_click=bulk_cart_clear)

    if active_sales_section == "Échange":
        st.subheader("🔄 Échange de cartes")
        st.caption("Échange un ou plusieurs cartes de tes lots contre d'autres cartes.")
        cd_sw = ld()
        trade_snapshot = json.dumps(cd_sw.get("lots", []), ensure_ascii=False, sort_keys=True)
        if not brocante:
            ensure_trade_lot(cd_sw)
            migrate_open_trade_cards(cd_sw)
        if json.dumps(cd_sw.get("lots", []), ensure_ascii=False, sort_keys=True) != trade_snapshot:
            sd(cd_sw)
            # No need to reload - sd() updates the cache

        if st.session_state.pop("swap_reset_pending", False):
            for key in (
                "swap_cart_give", "swap_cart_receive", "swap_cash_give", "swap_cash_receive",
                "search_swap", "recv_name", "recv_num", "recv_val", "recv_qty", "recv_collection_keep",
                "recv_query", "recv_selected_card", "brocante_trade_cash_mode", "brocante_trade_cash_amount",
            ):
                st.session_state.pop(key, None)
            st.session_state["swap_cart_give"] = []
            st.session_state["swap_cart_receive"] = []
            st.session_state["swap_cash_give"] = 0.0
            st.session_state["swap_cash_receive"] = 0.0
            st.session_state["recv_name_val"] = ""
            st.session_state["recv_num_val"] = ""

        # ── Panier d'échange (cartes à donner) ──
        if "swap_cart_give" not in st.session_state:
            st.session_state.swap_cart_give = []  # liste de {lot_idx, card_idx, card_name, set, number, value}
        if "swap_cart_receive" not in st.session_state:
            st.session_state.swap_cart_receive = []  # liste de {name, set, number, value, lot_target_idx}
        st.session_state.setdefault("swap_cash_give", 0.0)
        st.session_state.setdefault("swap_cash_receive", 0.0)

        trade_mobile = bool(brocante and is_mobile_mode())
        trade_square_size = BRO_CARD_IMAGE_SIZE if brocante else None
        col_give, col_receive = (st.container(), st.container()) if trade_mobile else st.columns(2)

        # ── Colonne DONNER ──
        with col_give:
            st.markdown("### 📤 Cartes à donner")
            search_input = inventory_live_search if brocante else st.text_input
            search_sw = search_input("Chercher une carte à donner", placeholder="Nom, numéro, extension...", key="search_swap")

            all_stock_sw = []
            if not (brocante and not search_sw):
                for li, lot in enumerate(cd_sw.get("lots", [])):
                    for ci, card in enumerate(lot.get("cards", [])):
                        stock = card_available_qty(card)
                        if stock > 0 and not card.get("cost_basis_pending"):
                            if not search_sw or (card_matches_inventory_query(card, search_sw) if brocante else normalize_name(search_sw) in normalize_name(card.get("name", ""))):
                                all_stock_sw.append((li, ci, card, lot, stock))
            elif brocante:
                st.caption("Recherche une carte pour afficher le stock disponible.")

            give_keys = {g.get("card_uid") for g in st.session_state.swap_cart_give if g.get("card_uid")}

            for li, ci, card, lot, stock in all_stock_sw[:24]:
                in_give = card.get("card_uid") in give_keys
                c_img, c_info, c_btn = st.columns([1, 3, 1])
                with c_img:
                    st.markdown(
                        _sale_image_html(
                            card,
                            in_cart=in_give,
                            width=BRO_CARD_IMAGE_SIZE if brocante else "60px",
                            square_size=trade_square_size,
                        ),
                        unsafe_allow_html=True,
                    )
                with c_info:
                    st.markdown(f"**{card['name']}**")
                    st.caption(f"{lot['nom']} · {fp(card.get('suggested_price',0))}")
                with c_btn:
                    if in_give:
                        if st.button("❌", key=f"sw_rm_{li}_{ci}"):
                            st.session_state.swap_cart_give = [g for g in st.session_state.swap_cart_give if not (g.get("card_uid")==card.get("card_uid") or (g["lot_idx"]==li and g["card_idx"]==ci))]
                            save_activity_state()
                            st.rerun()
                    else:
                        if st.button("➕", key=f"sw_add_{li}_{ci}"):
                            unit_cost = card_historical_unit_cost(lot, card)
                            st.session_state.swap_cart_give.append({"lot_idx":li,"card_idx":ci,"lot_uid":lot.get("lot_uid"),"card_uid":card.get("card_uid"),"card_name":card["name"],"set":card.get("set",""),"number":card.get("number",""),"value":float(card.get("suggested_price",0)),"quantity":1,"historical_cost":unit_cost,"lot_name":lot["nom"]})
                            save_activity_state()
                            st.rerun()

            if st.session_state.swap_cart_give:
                st.markdown("---")
                st.markdown("**Cartes à donner :**")
                st.markdown(
                    """
                    <style>
                    [class*="st-key-swap_give_qty_row_"] {
                        margin: 0.08rem 0 0.18rem;
                    }
                    [class*="st-key-swap_give_qty_row_"] [data-testid="stHorizontalBlock"] {
                        align-items: center !important;
                        gap: 0.22rem !important;
                        flex-wrap: nowrap !important;
                    }
                    [class*="st-key-swap_give_qty_text_"] {
                        flex: 1 1 auto !important;
                        min-width: 10rem !important;
                    }
                    [class*="st-key-swap_give_qty_label_"],
                    [class*="st-key-swap_give_qty_value_"] {
                        flex: 0 0 auto !important;
                    }
                    [class*="st-key-swap_give_qty_dec_wrap_"],
                    [class*="st-key-swap_give_qty_inc_wrap_"] {
                        flex: 0 0 1.75rem !important;
                        width: 1.75rem !important;
                        min-width: 1.75rem !important;
                    }
                    [class*="st-key-swap_give_qty_dec_wrap_"] button,
                    [class*="st-key-swap_give_qty_inc_wrap_"] button {
                        min-height: 1.65rem !important;
                        height: 1.65rem !important;
                        width: 1.65rem !important;
                        min-width: 1.65rem !important;
                        padding: 0 !important;
                        border-radius: 999px !important;
                        line-height: 1 !important;
                        font-size: 0.86rem !important;
                        font-weight: 900 !important;
                    }
                    @media (max-width: 768px) {
                        [class*="st-key-swap_give_qty_row_"] [data-testid="stHorizontalBlock"] {
                            display: flex !important;
                            flex-direction: row !important;
                            flex-wrap: wrap !important;
                            align-items: center !important;
                        }
                        [class*="st-key-swap_give_qty_text_"] {
                            min-width: 13rem !important;
                        }
                    }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                given_preview_records = _selected_trade_given_records(cd_sw, st.session_state.swap_cart_give)
                total_give = 0.
                total_given_cost_preview = 0.

                def update_given_quantity(record, new_quantity):
                    g = record["ui"]
                    available_qty = max(int(record.get("available_qty", 1) or 1), 1)
                    quantity = max(1, min(int(new_quantity or 1), available_qty))
                    g["quantity"] = quantity
                    record["quantity"] = quantity
                    record["reference_value"] = record["unit_reference_value"] * quantity
                    record["historical_cost"] = record["unit_historical_cost"] * quantity
                    record["contributors"] = contributors_from_card(
                        record["lot_idx"], record["lot"], record["card"], record["historical_cost"]
                    )
                    return quantity

                def adjust_given_quantity(target_uid, target_lot_idx, target_card_idx, delta, available_qty):
                    available_qty = max(int(available_qty or 1), 1)
                    for selected in st.session_state.swap_cart_give:
                        same_uid = target_uid and selected.get("card_uid") == target_uid
                        same_position = selected.get("lot_idx") == target_lot_idx and selected.get("card_idx") == target_card_idx
                        if same_uid or same_position:
                            current = max(safe_int(selected.get("quantity"), 1), 1)
                            selected["quantity"] = max(1, min(available_qty, current + int(delta or 0)))
                            save_activity_state()
                            break

                for record in given_preview_records:
                    g = record["ui"]
                    available_qty = max(int(record.get("available_qty", 0) or 0), 0)
                    quantity = max(int(record.get("quantity", 1) or 1), 1)
                    preview_image_col, preview_detail_col = (
                        st.columns([1, 4]) if brocante else (None, st.container())
                    )
                    if preview_image_col is not None:
                        preview_image_col.markdown(
                            _sale_image_html(
                                record["card"],
                                in_cart=True,
                                width=BRO_CARD_IMAGE_SIZE,
                                square_size=BRO_CARD_IMAGE_SIZE,
                            ),
                            unsafe_allow_html=True,
                        )
                    with preview_detail_col:
                        if available_qty > 1:
                            quantity = update_given_quantity(record, min(quantity, available_qty))
                            qty_key_raw = f"{g.get('card_uid') or record['lot_idx']}_{record['card_idx']}"
                            qty_key = "".join(ch if ch.isalnum() else "_" for ch in str(qty_key_raw))
                            with st.container(key=f"swap_give_qty_row_{qty_key}", horizontal=True, gap="small"):
                                with st.container(key=f"swap_give_qty_text_{qty_key}"):
                                    st.markdown(
                                        f"• **{g['card_name']}** · {fp(record['unit_reference_value'])} × {quantity} = **{fp(record['reference_value'])}**"
                                    )
                                with st.container(key=f"swap_give_qty_label_{qty_key}"):
                                    st.markdown(
                                        "<span style='color:#64748b;font-size:0.78rem;font-weight:800;white-space:nowrap;'>Qté :</span>",
                                        unsafe_allow_html=True,
                                    )
                                with st.container(key=f"swap_give_qty_dec_wrap_{qty_key}"):
                                    st.button(
                                        "−",
                                        key=f"swap_give_qty_dec_{qty_key}",
                                        disabled=quantity <= 1,
                                        on_click=adjust_given_quantity,
                                        args=(g.get("card_uid"), record["lot_idx"], record["card_idx"], -1, available_qty),
                                    )
                                with st.container(key=f"swap_give_qty_value_{qty_key}"):
                                    st.markdown(
                                        f"<span style='display:inline-block;min-width:1.1rem;text-align:center;font-size:0.86rem;font-weight:900;'>{quantity}</span>",
                                        unsafe_allow_html=True,
                                    )
                                with st.container(key=f"swap_give_qty_inc_wrap_{qty_key}"):
                                    st.button(
                                        "+",
                                        key=f"swap_give_qty_inc_{qty_key}",
                                        disabled=quantity >= available_qty,
                                        on_click=adjust_given_quantity,
                                        args=(g.get("card_uid"), record["lot_idx"], record["card_idx"], 1, available_qty),
                                    )
                        else:
                            g["quantity"] = 1
                            st.markdown(f"• **{g['card_name']}** · **{fp(record['unit_reference_value'])}**")
                    total_give += record["reference_value"]
                    total_given_cost_preview += safe_float(record.get("historical_cost"))
                cash_give = (
                    float(st.session_state.get("swap_cash_give", 0.0) or 0.0)
                    if brocante
                    else st.number_input("Argent ajouté par moi (€)", 0., 99999., step=0.5, key="swap_cash_give")
                )
                st.metric("Total donné", fp(total_give + cash_give))
                st.caption(f"Coût historique estimé des cartes données : {fp(total_given_cost_preview)}")

        # ── Colonne RECEVOIR ──
        with col_receive:
            st.markdown("### 📥 Cartes à recevoir")
            st.caption("Les cartes reçues seront rangées dans le lot Trade. Leur valeur de stock et leur future vente seront attribuées aux lots contributeurs selon leur part.")

            # Ajouter une carte à recevoir
            with st.expander("➕ Ajouter une carte reçue", expanded=len(st.session_state.swap_cart_receive)==0):
                # Initialiser les clés si absentes
                if st.session_state.pop("clear_recv_fields", False):
                    for key in ("recv_name", "recv_num", "recv_val", "recv_qty", "recv_collection_keep", "recv_query", "recv_selected_card"):
                        st.session_state.pop(key, None)
                    st.session_state.recv_name_val = ""
                    st.session_state.recv_num_val = ""
                if "recv_name_val" not in st.session_state:
                    st.session_state.recv_name_val = ""
                if "recv_num_val" not in st.session_state:
                    st.session_state.recv_num_val = ""
                pending_recv = st.session_state.pop("recv_selected_pending", None)
                if pending_recv:
                    for key in ("recv_name", "recv_num"):
                        st.session_state.pop(key, None)
                    st.session_state.recv_name_val = pending_recv.get("name", "")
                    st.session_state.recv_num_val = pending_recv.get("number", "")
                    st.session_state["recv_selected_card"] = pending_recv

                r1, r2 = st.columns(2)
                recv_name = r1.text_input("Nom de la carte", key="recv_name",
                    placeholder="Ex: Lugia",
                    value=st.session_state.recv_name_val)
                recv_num = r2.text_input("Numéro", key="recv_num",
                    placeholder="Ex: 042",
                    value=st.session_state.recv_num_val)
                recv_val = st.number_input("Valeur estimée (€)", 0., 9999., 0., 0.5, key="recv_val")
                recv_qty = st.number_input("Quantité", 1, 9999, 1, 1, key="recv_qty")
                recv_collection_keep = st.checkbox("Carte collection / à garder", key="recv_collection_keep")

                # Mettre à jour les valeurs en session
                st.session_state.recv_name_val = recv_name
                st.session_state.recv_num_val = recv_num

                search_input = inventory_live_search if brocante else st.text_input
                recv_query = search_input("Rechercher une carte reçue", key="recv_query", placeholder="Pikachu, Dracaufeu, 104...")
                cards_index = st.session_state.get("cards_index", {})
                selected_card = st.session_state.get("recv_selected_card") or {}
                if recv_query and len(recv_query.strip()) >= 2:
                    candidates = search_received_cards(recv_query, cards_index, normalize_name, limit=10)
                    if candidates:
                        st.caption(f"{len(candidates)} résultat(s) dans le cache local")
                        for idx, (card_sw, set_name_sw, set_id_sw) in enumerate(candidates):
                            local_id = str(card_sw.get("localId", "") or card_sw.get("number", ""))
                            label = f"{card_sw.get('name','?')} ? {local_id or 'n? ?'} ? {set_name_sw or set_id_sw or 'extension ?'}"
                            if brocante:
                                candidate_preview = dict(card_sw)
                                candidate_preview.setdefault("set_id", set_id_sw)
                                candidate_preview.setdefault("number", local_id)
                                _normalize_received_trade_image_fields(candidate_preview)
                                st.markdown(
                                    _sale_image_html(
                                        candidate_preview,
                                        width=BRO_CARD_IMAGE_SIZE if brocante else "80px",
                                        square_size=trade_square_size,
                                    ),
                                    unsafe_allow_html=True,
                                )
                            if st.button(label, key=f"recv_pick_{idx}_{card_sw.get('id','')}_{local_id}", width="stretch"):
                                enriched_sw = ecd(card_sw, set_name_sw, lang=card_sw.get("lang", "fr") if brocante else "fr")
                                enriched_sw["set_id"] = set_id_sw
                                enriched_sw["raw_cache_card"] = card_sw
                                if set_id_sw:
                                    number_sw = str(enriched_sw.get("number") or card_sw.get("localId") or card_sw.get("number") or "").strip()
                                    if number_sw:
                                        if not enriched_sw.get("image_url"):
                                            enriched_sw["image_url"] = f"https://assets.tcgdex.net/fr/{set_id_sw}/{number_sw}/high.webp"
                                        if not enriched_sw.get("image_url_en"):
                                            enriched_sw["image_url_en"] = f"https://assets.tcgdex.net/en/{set_id_sw}/{number_sw}/high.webp"
                                st.session_state["recv_selected_pending"] = enriched_sw
                                st.rerun()
                    else:
                        st.caption("Aucun résultat dans le cache local pour cette recherche.")
                elif recv_query:
                    st.caption("Saisis au moins 2 caractères pour chercher dans le cache local.")

                # Mettre a jour les valeurs en session
                st.session_state.recv_name_val = recv_name
                st.session_state.recv_num_val = recv_num

                recv_image_url = str(selected_card.get("image_url") or "")
                recv_image_url_en = str(selected_card.get("image_url_en") or "")
                recv_image_url_ja = str(selected_card.get("image_url_ja") or "")
                recv_set_name = str(selected_card.get("set") or "")
                recv_rarity = str(selected_card.get("rarity") or "")
                recv_lang = str(selected_card.get("lang") or "fr")
                if selected_card and (not recv_name or recv_name == selected_card.get("name")):
                    recv_name = selected_card.get("name", recv_name)
                    recv_num = selected_card.get("number", recv_num)

                recv_name = recv_name.strip().title() if recv_name else recv_name

                if selected_card and recv_name and recv_num:
                    st.markdown(
                        _sale_image_html(
                            selected_card,
                            width=BRO_CARD_IMAGE_SIZE if brocante else "80px",
                            square_size=trade_square_size,
                        ),
                        unsafe_allow_html=True,
                    )
                elif recv_name and recv_num:
                    st.warning("Carte sans image locale. Tu pourras ajouter la photo manuellement une fois la carte ajoutée au lot.")
                elif recv_name and not recv_num:
                    st.caption("Ajoute le numéro ou sélectionne un résultat du cache pour afficher la bonne carte.")

                if st.button("➕ Ajouter cette carte", key="add_recv"):
                    if recv_name:
                        received_card = {
                            "name": recv_name,
                            "set": recv_set_name,
                            "number": recv_num,
                            "value": recv_val,
                            "quantity": int(recv_qty),
                            "image_url": recv_image_url,
                            "image_url_en": recv_image_url_en,
                            "image_url_ja": recv_image_url_ja,
                            "rarity": recv_rarity,
                            "lang": recv_lang,
                            "card_id": selected_card.get("id", ""),
                            "set_id": selected_card.get("set_id", ""),
                            "is_collection_keep": recv_collection_keep,
                        }
                        _normalize_received_trade_image_fields(received_card)
                        st.session_state.swap_cart_receive.append(received_card)
                        # Vider vraiment les champs du formulaire au prochain affichage.
                        st.session_state.recv_name_val = ""
                        st.session_state.recv_num_val = ""
                        st.session_state["clear_recv_fields"] = True
                        save_activity_state()
                        st.rerun()

            if st.session_state.swap_cart_receive:
                st.markdown("**Cartes à recevoir :**")
                total_receive = 0.
                for i, r in enumerate(st.session_state.swap_cart_receive):
                    rc1, rc2, rc3 = st.columns([1, 4, 1])
                    rc1.markdown(
                        _received_trade_image_html(
                            r,
                            width=BRO_CARD_IMAGE_SIZE if brocante else "45px",
                            square_size=trade_square_size,
                        ),
                        unsafe_allow_html=True,
                    )
                    recv_quantity = max(int(r.get("quantity", 1) or 1), 1)
                    rc2.markdown(f"**{r['name']}** · {recv_quantity} × {fp(r['value'])}")
                    if r.get("is_collection_keep"):
                        rc2.caption("Collection / à garder")
                    if rc3.button("❌", key=f"rm_recv_{i}"):
                        st.session_state.swap_cart_receive.pop(i)
                        save_activity_state()
                        st.rerun()
                    total_receive += float(r["value"]) * recv_quantity
                cash_receive = (
                    float(st.session_state.get("swap_cash_receive", 0.0) or 0.0)
                    if brocante
                    else st.number_input("Argent reçu en plus (€)", 0., 99999., step=0.5, key="swap_cash_receive")
                )
                st.metric("Total reçu", fp(total_receive + cash_receive))

                # Afficher la repartition prevue
                if st.session_state.swap_cart_give and not brocante:
                    preview_records = _selected_trade_given_records(cd_sw, st.session_state.swap_cart_give)
                    total_give_val = sum(item["reference_value"] for item in preview_records)
                    total_given_cost_preview = sum(item["historical_cost"] for item in preview_records)
                    cash_give = float(st.session_state.get("swap_cash_give", 0.0) or 0.0)
                    cash_receive = float(cash_receive or 0.0)
                    preview = compute_trade_summary(
                        total_give_val,
                        total_receive,
                        cash_paid=cash_give,
                        cash_received=cash_receive,
                        given_historical_cost=total_given_cost_preview,
                    )
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Valeur économique donnée", fp(preview["trade_economic_given_total"]))
                    m2.metric("Valeur économique reçue", fp(preview["trade_economic_received_total"]))
                    m3.metric("Différence de valeur", fp(preview["trade_value_difference"]))
                    st.caption(
                        f"Coût historique donné : {fp(total_given_cost_preview)} · "
                        f"coût transmis au Trade après cash : {fp(preview['trade_acquisition_total_cost'])}"
                    )

                    contributors_preview, _, _ = aggregate_contributors(
                        preview_records,
                        cash_paid=cash_give,
                        cash_received=cash_receive,
                    )
                    lot_contributors = [c for c in contributors_preview if c.get("source_type") == "lot"]
                    ratio_total = sum(safe_float(c.get("ratio")) for c in lot_contributors)
                    for contributor in lot_contributors:
                        pct = safe_float(contributor.get("ratio")) * 100
                        st.caption(
                            f"{contributor.get('lot_name') or 'Lot'} · "
                            f"coût contribué {fp(contributor.get('historical_cost_contributed'))} · "
                            f"capital restant {fp(contributor.get('remaining_cost'))} · "
                            f"contribution {pct:.1f} %"
                        )
                    if lot_contributors:
                        st.caption(f"Somme des contributions lots : {ratio_total * 100:.1f} %")

        if brocante:
            st.markdown("### Complément espèces")
            current_cash_mode = (
                "Tu ajoutes" if float(st.session_state.get("swap_cash_give", 0.0) or 0.0) > 0
                else "Tu reçois" if float(st.session_state.get("swap_cash_receive", 0.0) or 0.0) > 0
                else "Aucun"
            )
            cash_mode = st.segmented_control(
                "Sens du complément",
                ["Aucun", "Tu reçois", "Tu ajoutes"],
                default=current_cash_mode,
                key="brocante_trade_cash_mode",
                label_visibility="collapsed",
            ) or "Aucun"
            cash_amount = 0.0
            if cash_mode != "Aucun":
                cash_amount = st.number_input(
                    "Montant du complément (€)", 0.0, 99999.0, step=0.5,
                    key="brocante_trade_cash_amount",
                )
            st.session_state["swap_cash_give"] = float(cash_amount if cash_mode == "Tu ajoutes" else 0.0)
            st.session_state["swap_cash_receive"] = float(cash_amount if cash_mode == "Tu reçois" else 0.0)

            if st.session_state.swap_cart_give and st.session_state.swap_cart_receive:
                mobile_given = _selected_trade_given_records(cd_sw, st.session_state.swap_cart_give)
                mobile_given_value = sum(item["reference_value"] for item in mobile_given)
                mobile_received_value = sum(
                    float(item.get("value", 0.0) or 0.0) * max(int(item.get("quantity", 1) or 1), 1)
                    for item in st.session_state.swap_cart_receive
                )
                mobile_summary = compute_trade_summary(
                    mobile_given_value,
                    mobile_received_value,
                    cash_paid=st.session_state["swap_cash_give"],
                    cash_received=st.session_state["swap_cash_receive"],
                    given_historical_cost=sum(item["historical_cost"] for item in mobile_given),
                )
                st.markdown("### Résumé")
                m1, m2 = st.columns(2)
                m1.metric("Tu donnes", fp(mobile_summary["trade_economic_given_total"]))
                m2.metric("Tu reçois", fp(mobile_summary["trade_economic_received_total"]))
                st.caption(f"Écart de valeur · {fp(mobile_summary['trade_value_difference'])}")

        # ── Bouton confirmer l'échange ──
        if st.session_state.swap_cart_give and st.session_state.swap_cart_receive:
            st.markdown("---")
            if st.button("Confirmer l'échange", type="primary", width="stretch"):
                cdd = ld()
                if brocante:
                    from services.brocante_workflow import require_active, project_event, tag_trade
                    from services.brocante_data import save_brocantes
                    event_data = load_brocantes()
                    try:
                        event = require_active(event_data, brocante["id"])
                    except ValueError as error:
                        st.error(str(error))
                        st.stop()
                    attempt_key = f"bro_trade_attempt_{brocante['id']}"
                    st.session_state.setdefault(attempt_key, build_trade_id())
                    if any(t.get("exchange_id") == st.session_state[attempt_key] for t in cdd.get("trade_history", [])):
                        project_event(event, cdd)
                        save_brocantes(event_data)
                        st.session_state.pop(attempt_key, None)
                        st.session_state["swap_reset_pending"] = True
                        st.rerun()
                cash_give = float(st.session_state.get("swap_cash_give", 0.0) or 0.0)
                cash_receive = float(st.session_state.get("swap_cash_receive", 0.0) or 0.0)
                trade_id = st.session_state[attempt_key] if brocante else build_trade_id()
                trade_date = datetime.now().isoformat()
                given_records = _selected_trade_given_records(cdd, st.session_state.swap_cart_give)
                if len(given_records) != len(st.session_state.swap_cart_give):
                    st.error("Une carte de l'échange est introuvable dans le stock actuel.")
                    st.stop()
                for record in given_records:
                    required_qty = max(int(record.get("quantity", 1) or 1), 1)
                    if card_available_qty(record["card"]) < required_qty:
                        st.error(f"Stock insuffisant pour {record['card'].get('name', 'cette carte')}.")
                        st.stop()

                total_given_value = sum(item["reference_value"] for item in given_records)
                total_received_value = sum(
                    float(r.get("value", 0.0) or 0.0) * max(int(r.get("quantity", 1) or 1), 1)
                    for r in st.session_state.swap_cart_receive
                )
                total_given_historical_cost = sum(item["historical_cost"] for item in given_records)
                contributors, historical_before_cash, historical_remaining = aggregate_contributors(
                    given_records, cash_paid=cash_give, cash_received=cash_receive
                )
                summary = compute_trade_summary(
                    total_given_value,
                    total_received_value,
                    cash_paid=cash_give,
                    cash_received=cash_receive,
                    given_historical_cost=total_given_historical_cost,
                )

                received_allocated = allocate_received_cards(
                    st.session_state.swap_cart_receive,
                    historical_remaining,
                    contributors,
                )

                received_names = ", ".join(r.get("name", "") for r in st.session_state.swap_cart_receive)
                for record in given_records:
                    card_g = record["card"]
                    lot_g = record["lot"]
                    given_qty = max(int(record.get("quantity", 1) or 1), 1)
                    card_g.setdefault("card_uid", new_uid("card"))
                    card_g["exchange_out_quantity"] = int(card_g.get("exchange_out_quantity", 0) or 0) + given_qty
                    card_g.setdefault("exchange_out_entries", []).append({
                        "exchange_id": trade_id,
                        "date": trade_date,
                        "quantity": given_qty,
                        "card_uid": card_g.get("card_uid"),
                        "card_name": card_g.get("name", ""),
                        "card_set": card_g.get("set", ""),
                        "card_number": card_g.get("number", ""),
                        "image_url": card_g.get("image_url", ""),
                        "image_url_en": card_g.get("image_url_en", ""),
                        "reference_value": record["reference_value"],
                        "historical_cost": round(record["historical_cost"], 2),
                        "lot_idx": record["lot_idx"],
                        "lot_uid": lot_g.get("lot_uid"),
                        "lot_name": lot_g.get("nom", ""),
                        "contributors": record["contributors"],
                        "exchanged_for": received_names,
                    })

                trade_lot_idx = ensure_trade_lot(cdd)
                for r in received_allocated:
                    _normalize_received_trade_image_fields(r)
                    new_card = {
                        "card_uid": new_uid("card"),
                        "id": r.get("card_id") or r.get("id", ""),
                        "name": r.get("name", ""),
                        "set": r.get("set", ""),
                        "set_id": r.get("set_id", ""),
                        "number": r.get("number", ""),
                        "rarity": r.get("rarity", ""),
                        "lang": r.get("lang", "fr"),
                        "suggested_price": float(r.get("value", 0.0) or 0.0),
                        "quantity": max(int(r.get("quantity", 1) or 1), 1),
                        "sold_quantity": 0,
                        "condition": "NM",
                        "is_reverse": False,
                        "is_ed1": False,
                        "image_url": r.get("image_url", ""),
                        "image_url_en": r.get("image_url_en", ""),
                        "image_url_ja": r.get("image_url_ja", ""),
                        "sold_entries": [],
                        "received_by_exchange": True,
                        "exchange_id": trade_id,
                        "exchange_date": trade_date[:10],
                        "exchange_cash_paid": cash_give,
                        "exchange_cash_received": cash_receive,
                        "exchanged_from": ", ".join(item["card"].get("name", "") for item in given_records),
                        "trade_reference_value": float(r.get("value", 0.0) or 0.0),
                        "trade_acquisition_cost": r.get("trade_acquisition_total_cost", 0.0),
                        "trade_acquisition_unit_cost": r.get("trade_acquisition_unit_cost", 0.0),
                        "trade_acquisition_total_cost": r.get("trade_acquisition_total_cost", 0.0),
                        "trade_contributors": r.get("trade_contributors", []),
                        "exchange_repartition": r.get("exchange_repartition", {}),
                        "trade_received_cards_value": summary["trade_received_cards_value"],
                        "trade_given_cards_value": summary["trade_given_cards_value"],
                        "trade_cash_paid": summary["trade_cash_paid"],
                        "trade_cash_received": summary["trade_cash_received"],
                        "trade_economic_received_total": summary["trade_economic_received_total"],
                        "trade_economic_given_total": summary["trade_economic_given_total"],
                        "trade_value_difference": summary["trade_value_difference"],
                        "trade_cost_method": summary["trade_cost_method"],
                        "is_collection_keep": bool(r.get("is_collection_keep")),
                    }
                    cdd["lots"][trade_lot_idx].setdefault("cards", []).append(new_card)

                cdd.setdefault("trade_history", []).append({
                    "exchange_id": trade_id,
                    "date": trade_date,
                    **summary,
                    "trade_historical_cost_before_cash": historical_before_cash,
                    "trade_acquisition_total_cost": historical_remaining,
                    "contributors": contributors,
                    "given_cards": [
                        {
                            "name": item["card"].get("name", ""),
                            "number": item["card"].get("number", ""),
                            "set": item["card"].get("set", ""),
                            "lot_idx": item["lot_idx"],
                            "lot_uid": item["lot"].get("lot_uid"),
                            "lot_name": item["lot"].get("nom", ""),
                            "quantity": item.get("quantity", 1),
                            "reference_value": item["reference_value"],
                            "unit_reference_value": item.get("unit_reference_value", item["reference_value"]),
                            "historical_cost": round(item["historical_cost"], 2),
                            "unit_historical_cost": round(item.get("unit_historical_cost", item["historical_cost"]), 2),
                            "contributors": item["contributors"],
                        }
                        for item in given_records
                    ],
                    "received_cards": [
                        {
                            "name": r.get("name", ""),
                            "number": r.get("number", ""),
                            "set": r.get("set", ""),
                            "quantity": max(int(r.get("quantity", 1) or 1), 1),
                            "reference_value": float(r.get("value", 0.0) or 0.0) * max(int(r.get("quantity", 1) or 1), 1),
                            "historical_cost": r.get("trade_acquisition_total_cost", 0.0),
                            "contributors": r.get("trade_contributors", []),
                        }
                        for r in received_allocated
                    ],
                })

                if brocante:
                    tag_trade(cdd, brocante["id"], trade_id)
                sd(cdd)
                if brocante:
                    project_event(event, cdd)
                    save_brocantes(event_data)
                    st.session_state.pop(attempt_key, None)
                nb_give = sum(max(int(item.get("quantity", 1) or 1), 1) for item in st.session_state.swap_cart_give)
                nb_recv = sum(max(int(item.get("quantity", 1) or 1), 1) for item in st.session_state.swap_cart_receive)
                st.session_state.swap_cart_give = []
                st.session_state.swap_cart_receive = []
                st.session_state["swap_reset_pending"] = True
                save_activity_state()
                st.success(f"Échange confirmé : {nb_give} carte(s) donnée(s) contre {nb_recv} carte(s) reçue(s).")
                st.rerun()





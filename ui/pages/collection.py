"""Collection page renderer for Pokestock.

The page receives write actions as parameters and keeps data-writing logic in app.py.
"""

import html
import time

import streamlit as st


def render_collection_page(
    *,
    ld_func,
    add_collection_card_func,
    delete_collection_card_func,
    remove_collection_status_func,
    save_collection_manual_image_func,
    render_card_choice_popups_func,
    run_html_func,
    render_page_header_func,
    is_collection_system_lot_func,
    collection_current_value_func,
    collection_paid_total_func,
    collection_has_manual_image_func,
    collection_image_needs_manual_func,
    collection_image_html_func,
    card_status_badges_func,
    normalize_name_func,
    fp_func,
    is_mobile_mode_func,
    perf_count_func=None,
):
    st.markdown(
        render_page_header_func("Collection", "Cartes conservées et pièces de collection", "🧾"),
        unsafe_allow_html=True,
    )
    st.caption("Cartes marquées comme Collection dans les lots ou créées depuis une estimation.")

    with st.expander("➕ Ajouter une carte à la Collection", expanded=False):
        if "collection_add_ts" not in st.session_state:
            st.session_state["collection_add_ts"] = time.time()
        cts = st.session_state["collection_add_ts"]

        ca1, ca2 = st.columns(2)
        collection_name = ca1.text_input("Nom", placeholder="Dracaufeu", key=f"collection_name_{cts}")
        collection_number = ca2.text_input("Numéro", placeholder="004", key=f"collection_number_{cts}")

        cb1, cb2, cb3 = st.columns(3)
        collection_paid_raw = cb1.text_input("Prix payé (€)", placeholder="0.00", key=f"collection_paid_{cts}")
        collection_value_raw = cb2.text_input("Valeur actuelle (€)", placeholder="0.00", key=f"collection_value_{cts}")
        collection_qty_raw = cb3.text_input("Qté", placeholder="1", key=f"collection_qty_{cts}")

        collection_specials = st.multiselect(
            "Spécial",
            ["Reverse", "1ère Éd", "Japonaise", "Scellé", "Stamp", "Promo", "Master Ball", "Poké Ball"],
            key=f"collection_specials_{cts}",
            placeholder="Reverse, Stamp, Promo...",
        )
        collection_reverse = "Reverse" in collection_specials
        collection_ed1 = "1ère Éd" in collection_specials
        collection_jp = "Japonaise" in collection_specials
        collection_special_tag = ", ".join(
            [tag for tag in collection_specials if tag not in ("Reverse", "1ère Éd", "Japonaise")]
        )

        try:
            collection_paid = float(collection_paid_raw.replace(",", ".")) if collection_paid_raw.strip() else 0.
        except Exception:
            collection_paid = 0.
        try:
            collection_value = float(collection_value_raw.replace(",", ".")) if collection_value_raw.strip() else 0.
        except Exception:
            collection_value = 0.
        try:
            collection_qty = max(1, int(collection_qty_raw)) if collection_qty_raw.strip() else 1
        except Exception:
            collection_qty = 1

        if st.button("Ajouter à la Collection", key=f"collection_add_btn_{cts}", type="primary"):
            if not collection_name.strip():
                st.error("Nom requis")
                st.stop()

            ok, msg = add_collection_card_func(
                collection_name=collection_name,
                collection_number=collection_number,
                collection_qty=collection_qty,
                collection_value=collection_value,
                collection_paid=collection_paid,
                collection_reverse=collection_reverse,
                collection_ed1=collection_ed1,
                collection_jp=collection_jp,
                collection_special_tag=collection_special_tag,
            )
            if ok:
                st.session_state["collection_add_ts"] = time.time()
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    cd_popup_collection = ld_func()
    for collection_popup_ix, collection_popup_lot in enumerate(cd_popup_collection.get("lots", [])):
        if is_collection_system_lot_func(collection_popup_lot):
            render_card_choice_popups_func(
                collection_popup_ix,
                form_ts_key="collection_add_ts",
                run_html_func=run_html_func,
            )

    cd_collection = ld_func()
    collection_cards = []
    for lot_idx, lot in enumerate(cd_collection.get("lots", [])):
        for card_idx, card in enumerate(lot.get("cards", [])):
            if card.get("is_collection_keep"):
                collection_cards.append((lot_idx, card_idx, lot, card))

    if not collection_cards:
        st.info("Aucune carte marquée Collection pour le moment. Dans un lot ou une estimation, coche l'option Collection au moment de l'ajout.")
        return

    total_collection_value = sum(
        collection_current_value_func(card) * int(card.get("quantity", 1) or 1)
        for _, _, _, card in collection_cards
    )
    total_collection_paid = sum(collection_paid_total_func(card, lot) for _, _, lot, card in collection_cards)
    total_collection_qty = sum(int(card.get("quantity", 1) or 1) for _, _, _, card in collection_cards)
    c1, c2, c3 = st.columns(3)
    c1.metric("Cartes collection", total_collection_qty)
    c2.metric("Valeur actuelle", fp_func(total_collection_value))
    c3.metric("Prix payé", fp_func(total_collection_paid))

    search_collection = st.text_input("🔍 Rechercher dans la collection", placeholder="Nom de carte...", key="collection_search")
    if search_collection:
        collection_cards = [
            item for item in collection_cards
            if normalize_name_func(search_collection) in normalize_name_func(item[3].get("name", ""))
        ]
    if perf_count_func is not None:
        perf_count_func("cards_collection_rendered", len(collection_cards))

    cols_per_row = 3 if is_mobile_mode_func() else 8
    for row_start in range(0, len(collection_cards), cols_per_row):
        cols = st.columns(cols_per_row)
        for col_idx, (lot_idx, card_idx, lot, card) in enumerate(collection_cards[row_start:row_start + cols_per_row]):
            with cols[col_idx]:
                st.markdown(collection_image_html_func(card), unsafe_allow_html=True)
                card_name_html = html.escape(str(card.get("name", "Carte") or "Carte"))
                st.markdown(
                    f'<div style="font-weight:800;font-size:0.92rem;line-height:1.25;">'
                    f'{card_name_html} {card_status_badges_func(card)}</div>',
                    unsafe_allow_html=True,
                )
                meta = " · ".join(x for x in [card.get("set", ""), f"#{card.get('number','')}" if card.get("number") else ""] if x)
                if meta:
                    st.caption(meta)
                st.caption(
                    f"📦 {lot.get('nom','Lot')} · x{int(card.get('quantity',1) or 1)}"
                    f" · Valeur {fp_func(collection_current_value_func(card))}"
                    f" · Payé {fp_func(collection_paid_total_func(card, lot))}"
                )
                card_uid = str(card.get("card_uid") or card.get("id") or f"{lot_idx}_{card_idx}")
                action_key = f"collection_action_{lot_idx}_{card_idx}_{card_uid}"
                confirm_key = f"confirm_{action_key}"
                image_panel_key = f"image_panel_{action_key}"

                if collection_image_needs_manual_func(card) or collection_has_manual_image_func(card):
                    image_button_label = "🖼️ Modifier l'image" if collection_has_manual_image_func(card) else "🖼️ Ajouter une image"
                    if st.button(image_button_label, key=f"toggle_image_{action_key}", width="stretch"):
                        st.session_state[image_panel_key] = not st.session_state.get(image_panel_key, False)

                if st.session_state.get(image_panel_key, False):
                    st.markdown(
                        '<div style="padding:0.55rem;margin:0.35rem 0;border:1px dashed #94a3b8;'
                        'border-radius:10px;background:#f8fafc;">',
                        unsafe_allow_html=True,
                    )
                    uploaded_manual = st.file_uploader(
                        "Image depuis le PC",
                        type=["png", "jpg", "jpeg", "webp"],
                        key=f"manual_upload_{action_key}",
                        label_visibility="collapsed",
                    )
                    manual_url_value = st.text_input(
                        "URL image",
                        value=str(card.get("manual_image_url", "") or ""),
                        placeholder="https://...",
                        key=f"manual_url_{action_key}",
                        label_visibility="collapsed",
                    )
                    img_cols = st.columns(2)
                    if img_cols[0].button("Enregistrer", key=f"save_manual_image_{action_key}", width="stretch"):
                        ok, msg = save_collection_manual_image_func(
                            lot_idx,
                            card_idx,
                            card_uid,
                            manual_url=manual_url_value,
                            uploaded_file=uploaded_manual,
                        )
                        if ok:
                            st.success(msg)
                            st.session_state.pop(image_panel_key, None)
                            st.rerun()
                        else:
                            st.error(msg)
                    if collection_has_manual_image_func(card) and img_cols[1].button("Retirer", key=f"clear_manual_image_{action_key}", width="stretch"):
                        ok, msg = save_collection_manual_image_func(
                            lot_idx,
                            card_idx,
                            card_uid,
                            clear_manual=True,
                        )
                        if ok:
                            st.success(msg)
                            st.session_state.pop(image_panel_key, None)
                            st.rerun()
                        else:
                            st.error(msg)
                    st.markdown("</div>", unsafe_allow_html=True)

                if is_collection_system_lot_func(lot):
                    if st.button("🗑️ Supprimer", key=f"delete_{action_key}", width="stretch"):
                        st.session_state[confirm_key] = "delete"
                    if st.session_state.get(confirm_key) == "delete":
                        st.warning("Supprimer définitivement cette carte de la Collection ?")
                        yes_col, no_col = st.columns(2)
                        if yes_col.button("Oui", key=f"yes_delete_{action_key}", type="primary"):
                            ok, msg = delete_collection_card_func(lot_idx, card_idx, card_uid)
                            if ok:
                                st.session_state.pop(confirm_key, None)
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                        if no_col.button("Non", key=f"no_delete_{action_key}"):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                else:
                    if st.button("↩️ Retirer Collection", key=f"unkeep_{action_key}", width="stretch"):
                        st.session_state[confirm_key] = "unkeep"
                    if st.session_state.get(confirm_key) == "unkeep":
                        st.warning("Retirer le statut Collection ? La carte restera dans son lot d'origine.")
                        yes_col, no_col = st.columns(2)
                        if yes_col.button("Oui", key=f"yes_unkeep_{action_key}", type="primary"):
                            ok, msg = remove_collection_status_func(lot_idx, card_idx, card_uid)
                            if ok:
                                st.session_state.pop(confirm_key, None)
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                        if no_col.button("Non", key=f"no_unkeep_{action_key}"):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()

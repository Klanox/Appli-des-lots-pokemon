from __future__ import annotations

import json
import os
import re

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


def _add_card_to_drop_action(drops_data, drop_id, card):
    added, duplicate = add_card_to_drop(drops_data, drop_id, card)
    if added:
        save_vinted_drops(drops_data)
        st.success("Carte ajoutée au drop.")
        st.rerun()
    if duplicate:
        st.warning("Cette carte est déjà dans ce drop.")


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
    st.subheader("3. Aperçu de l'annonce")
    if not selected_cards:
        st.info("Sélectionne une carte ou prépare une carte depuis un drop pour générer l'aperçu.")
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


def _render_selected_add_to_drop(drops_data, selected_cards):
    if not selected_cards or not drops_data.get("drops"):
        return
    options = _drop_choice_options(drops_data)
    if not options:
        return
    name = st.selectbox("Ajouter la sélection au drop", list(options.keys()), key="vinted_drop_destination")
    drop_id = options.get(name)
    if st.button("Ajouter la sélection au drop", disabled=not selected_cards, width="stretch"):
        added, duplicates = add_cards_to_drop(drops_data, drop_id, selected_cards)
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
    controls = st.columns([1, 1])
    with controls[0]:
        if st.button("Afficher toutes les cartes disponibles", key="vinted_show_all_available", width="stretch"):
            st.session_state["vinted_drop_show_all"] = True
            st.session_state["vinted_drop_show_limit"] = 12 if mobile else 30
            st.rerun()
    with controls[1]:
        if st.button("Masquer la liste", key="vinted_hide_all_available", width="stretch"):
            st.session_state["vinted_drop_show_all"] = False
            st.session_state["vinted_drop_show_limit"] = 12 if mobile else 30
            st.rerun()

    if query:
        candidates = filter_cards_for_listing(available_cards, query, limit=24 if mobile else 60)
    elif st.session_state.get("vinted_drop_show_all"):
        default_limit = 12 if mobile else 30
        limit = int(st.session_state.get("vinted_drop_show_limit", default_limit) or default_limit)
        candidates = list(available_cards[:limit])
    else:
        st.info("Recherchez une carte ou affichez toutes les cartes disponibles pour alimenter ce drop.")
        return

    if not candidates:
        st.caption("Aucune carte disponible trouvée.")
        return

    st.caption(f"{len(candidates)} carte(s) affichée(s).")
    for card in candidates:
        _render_drop_add_result(card, drops_data, active_drop, proxy_img_func, fp_func, mobile)

    if st.session_state.get("vinted_drop_show_all") and not query:
        default_limit = 12 if mobile else 30
        step = 12 if mobile else 30
        limit = int(st.session_state.get("vinted_drop_show_limit", default_limit) or default_limit)
        if len(available_cards) > limit:
            if st.button("Afficher plus", key="vinted_drop_show_more", width="stretch"):
                st.session_state["vinted_drop_show_limit"] = limit + step
                st.rerun()


def _render_drop_grid(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile):
    resolved_cards, missing_cards = resolve_drop_cards_from_data(active_drop, available_cards)
    st.markdown(f"**{active_drop.get('name', 'Drop sans nom')}** · {len(active_drop.get('cards', []))} carte(s)")
    if missing_cards:
        st.warning(f"{len(missing_cards)} carte(s) du drop ne sont plus disponibles à la vente.")

    drop_query = st.text_input(
        "Rechercher dans ce drop",
        key="vinted_drop_filter_query",
        placeholder="Nom, numéro complet, extension, lot...",
    )
    filtered_cards = filter_drop_cards(resolved_cards, drop_query)
    if not filtered_cards:
        st.caption("Aucune carte dans ce drop." if not resolved_cards else "Aucune carte ne correspond à cette recherche.")
        return

    cols_count = 2 if mobile else 5
    cols = st.columns(cols_count)
    for idx, card in enumerate(filtered_cards):
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
        with cols[idx % cols_count]:
            with st.container(border=True):
                _render_thumb(card, proxy_img_func, width=105)
                st.markdown(f"**{_card_display_title(card)}**")
                if posted:
                    st.success("Annonce postée")
                st.caption(fp_func(suggested_price(card)) if suggested_price(card) else "Prix à définir")
                if _card_set(card):
                    st.caption(_card_set(card))
                if st.button("Préparer", key=f"prepare_drop_card_{active_drop.get('id')}_{card_ref_key}", width="stretch"):
                    _select_cards([card])
                    _open_classic_submenu()
                    st.rerun()
                posted_label = "Annuler postée" if posted else "Annonce postée"
                if st.button(posted_label, key=f"posted_drop_card_{active_drop.get('id')}_{card_ref_key}", width="stretch"):
                    if toggle_drop_card_posted(drops_data, active_drop.get("id"), card_ref_key, not posted):
                        save_vinted_drops(drops_data)
                        st.rerun()
                if st.button("Retirer", key=f"remove_drop_card_{active_drop.get('id')}_{card_ref_key}", width="stretch"):
                    if remove_card_from_drop(drops_data, active_drop.get("id"), card_ref_key):
                        save_vinted_drops(drops_data)
                        st.success("Carte retirée du drop.")
                        st.rerun()


def _render_drops_manager(drops_data, available_cards, proxy_img_func, fp_func, mobile):
    st.subheader("2. Drops Vinted")

    with st.expander("Créer un drop", expanded=not bool(drops_data.get("drops"))):
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

    rename_col, delete_col = st.columns([2, 1])
    with rename_col:
        renamed = st.text_input("Renommer le drop", value=active_drop.get("name", ""), key=f"rename_drop_{active_id}")
        if st.button("Enregistrer le nom", key=f"save_drop_name_{active_id}", width="stretch"):
            if rename_drop(drops_data, active_id, renamed):
                save_vinted_drops(drops_data)
                st.success("Drop renommé.")
                st.rerun()
    with delete_col:
        confirm = st.checkbox("Confirmer suppression", key=f"confirm_delete_drop_{active_id}")
        if st.button("Supprimer le drop", key=f"delete_drop_{active_id}", disabled=not confirm, width="stretch"):
            if delete_drop(drops_data, active_id):
                save_vinted_drops(drops_data)
                st.session_state.pop("vinted_active_drop_id", None)
                st.success("Drop supprimé.")
                st.rerun()

    _render_drop_add_search(drops_data, active_drop, available_cards, proxy_img_func, fp_func)
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
    )

    if submenu == "Annonces classiques":
        st.subheader("1. Recherche carte")
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
        results = filter_cards_for_listing(cards, query, limit=24)
        if not query:
            st.info("Recherchez une carte pour commencer.")
        else:
            st.caption(f"{len(results)} résultat(s) affiché(s).")
            for card in results:
                _render_search_result(card, listing_type, selected_keys, proxy_img_func, fp_func, drops_data, active_drop_id)

        selected_cards = [card_by_key[key] for key in selected_keys if key in card_by_key]
        prepared = _sync_listing_text(selected_cards, listing_type, fp_func)

        left, right = st.columns([1, 1])
        with left:
            if st.button("Régénérer le titre et la description", width="stretch", disabled=not selected_cards):
                st.session_state["vinted_listing_title"] = prepared["title"]
                st.session_state["vinted_listing_description"] = prepared["description"]
                st.rerun()
        with right:
            if st.button("Réinitialiser", width="stretch"):
                _reset_vinted_form()

        _render_listing_preview(selected_cards, proxy_img_func, run_html_func)
    else:
        _render_drops_manager(drops_data, cards, proxy_img_func, fp_func, mobile)

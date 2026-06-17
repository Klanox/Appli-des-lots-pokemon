"""Collection page renderer for Pokestock.

The page receives write actions as parameters and keeps data-writing logic in app.py.
"""

import html
import re
import time

import streamlit as st


def _collection_parse_float(value):
    try:
        return float(str(value or "").replace(",", ".").strip() or 0.)
    except Exception:
        return 0.


def _collection_parse_int(value, default=1):
    try:
        return max(1, int(str(value or "").strip() or default))
    except Exception:
        return default


def _proper_collection_card_name(value):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""

    force_upper = {
        "EX", "GX", "V", "VMAX", "VSTAR", "AR", "SAR", "CHR", "CSR",
        "SSR", "SR", "UR", "HR", "FA", "TAG", "TEAM",
    }
    keep_lower = {"de", "du", "des", "d", "l", "la", "le", "les", "et", "en", "au", "aux"}

    def fix_word(match):
        word = match.group(0)
        normalized = word.replace("’", "'")
        bare = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ0-9]", "", normalized).upper()
        if bare in force_upper:
            return word.upper()
        lowered = word.lower()
        if lowered in keep_lower:
            return lowered
        return word[:1].upper() + word[1:].lower()

    text = re.sub(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", fix_word, text)
    text = re.sub(r"\b(?:ex|gx|vmax|vstar|ar|sar|chr|csr|ssr|sr|ur|hr|fa)\b", lambda m: m.group(0).upper(), text, flags=re.I)
    return text


def _normalize_collection_batch_name(row_id):
    key = f"collection_batch_name_{row_id}"
    st.session_state[key] = _proper_collection_card_name(st.session_state.get(key, ""))


def _collection_card_number(card):
    return str(card.get("number") or card.get("localId") or "").strip()


def _collection_card_image_url(card):
    url = str(card.get("image") or card.get("image_url") or card.get("image_url_en") or "").strip()
    if url and not url.endswith((".webp", ".png", ".jpg", ".jpeg")):
        url = url.rstrip("/") + "/high.webp"
    return url


def _apply_collection_batch_match(row_id, card, set_name):
    st.session_state[f"collection_batch_name_{row_id}"] = _proper_collection_card_name(card.get("name", ""))
    st.session_state[f"collection_batch_number_{row_id}"] = _collection_card_number(card)
    st.session_state[f"collection_batch_set_{row_id}"] = str(set_name or "").strip()
    st.session_state[f"collection_batch_card_id_{row_id}"] = str(card.get("id", "") or "").strip()
    st.session_state[f"collection_batch_image_{row_id}"] = _collection_card_image_url(card)
    if card.get("image_en") or card.get("image_url_en"):
        st.session_state[f"collection_batch_image_en_{row_id}"] = str(card.get("image_en") or card.get("image_url_en") or "").strip()
    for price_key in ("suggested_price", "price", "market_price", "cote"):
        if card.get(price_key) not in (None, ""):
            try:
                st.session_state[f"collection_batch_value_{row_id}"] = str(float(card.get(price_key) or 0.)).replace(".", ",")
            except Exception:
                pass
            break


def _collection_batch_match_key(row_id):
    name = st.session_state.get(f"collection_batch_name_{row_id}", "")
    number = st.session_state.get(f"collection_batch_number_{row_id}", "")
    return f"{name}|{number}".strip().lower()


def _collection_special_score(card):
    name = str(card.get("name", "") or "")
    special = str(card.get("special_tag", "") or "")
    rarity = str(card.get("rarity", "") or "")
    flags = " ".join([name, special, rarity]).lower()
    score = 0
    ultra_tokens = [
        " vmax", "vmax", "vstar", " ex", " gx", "mega", "tag team", "full art",
        "alternative", "alt", "secret", "secrète", "rainbow", "gold", "sar", "ar",
        "chr", "csr", "shiny", "brillant", "radieux", "légende", "legend",
    ]
    if any(token in flags for token in ultra_tokens):
        score += 100
    if card.get("is_reverse") or "reverse" in special.lower():
        score += 10
    if card.get("is_ed1"):
        score += 15
    if card.get("lang") == "ja" or "japonaise" in special.lower():
        score += 8
    if special.strip():
        score += 5
    return score


def _collection_set_recency_score(card):
    for key in ("release_date", "releaseDate", "set_release_date", "date"):
        value = str(card.get(key, "") or "").strip()
        match = re.search(r"(20\d{2}|19\d{2})", value)
        if match:
            return int(match.group(1)) * 100

    card_id = str(card.get("id", "") or "").lower()
    set_name = str(card.get("set", "") or "").lower()
    if card_id.startswith(("me", "mep")) or "méga" in set_name or "mega" in set_name:
        return 2026 * 100
    if card_id.startswith("sv") or "écarlate" in set_name or "ecarlate" in set_name or "violet" in set_name:
        return 2023 * 100
    if card_id.startswith("swsh") or "épée" in set_name or "epee" in set_name or "bouclier" in set_name:
        return 2020 * 100
    if card_id.startswith("sm") or "soleil" in set_name or "lune" in set_name:
        return 2017 * 100
    if card_id.startswith("xy"):
        return 2014 * 100
    if card_id.startswith("bw") or "noir" in set_name or "blanc" in set_name:
        return 2011 * 100
    if card_id.startswith(("dp", "pl")) or "diamant" in set_name or "perle" in set_name:
        return 2007 * 100
    if card_id.startswith("ex"):
        return 2003 * 100
    if card_id.startswith(("ecard", "neo")):
        return 2001 * 100
    if card_id.startswith(("base", "gym", "fossil", "jungle")):
        return 1999 * 100

    added = str(card.get("collection_added_at", "") or card.get("created", "") or "").strip()
    match = re.search(r"(20\d{2}|19\d{2})", added)
    if match:
        return int(match.group(1)) * 100
    return 0


def _collection_sort_key(item):
    _, _, _, card = item
    number = str(card.get("number", "") or "")
    number_match = re.search(r"\d+", number)
    number_score = int(number_match.group(0)) if number_match else 0
    return (
        _collection_special_score(card),
        _collection_set_recency_score(card),
        number_score,
        str(card.get("name", "") or "").lower(),
    )


def render_collection_page(
    *,
    ld_func,
    add_collection_card_func,
    add_collection_batch_func,
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
    search_in_cache_func=None,
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

    with st.expander("Ajouter un lot Collection", expanded=False):
        st.caption(
            "Ajoute plusieurs cartes gardées en Collection. Le prix payé est réparti automatiquement "
            "selon la cote de chaque carte."
        )
        batch_cols = st.columns([2, 1, 1])
        batch_name = batch_cols[0].text_input(
            "Nom du lot",
            placeholder="Ex : Lot Collection Vinted",
            key="collection_batch_name",
        )
        batch_paid_raw = batch_cols[1].text_input(
            "Prix total payé (€)",
            placeholder="50.00",
            key="collection_batch_paid",
        )
        batch_date = batch_cols[2].text_input(
            "Date",
            placeholder="2026-06-14",
            key="collection_batch_date",
        )
        batch_note = st.text_input(
            "Note",
            placeholder="Optionnel : vendeur, état global, rappel...",
            key="collection_batch_note",
        )

        if "collection_batch_row_ids" not in st.session_state:
            legacy_count = int(st.session_state.get("collection_batch_row_count", 3) or 3)
            st.session_state["collection_batch_row_ids"] = list(range(max(legacy_count, 1)))
            st.session_state["collection_batch_next_row_id"] = max(st.session_state["collection_batch_row_ids"]) + 1

        def clear_batch_row(row_id):
            for suffix in ("name", "number", "set", "qty", "value", "condition", "specials", "card_id", "image", "image_en", "match_key"):
                st.session_state.pop(f"collection_batch_{suffix}_{row_id}", None)

        action_cols = st.columns(2)
        if action_cols[0].button("Ajouter une carte", key="collection_batch_add_row"):
            next_row_id = int(st.session_state.get("collection_batch_next_row_id", 0) or 0)
            st.session_state.setdefault("collection_batch_row_ids", []).append(next_row_id)
            st.session_state["collection_batch_next_row_id"] = next_row_id + 1
            st.rerun()
        if action_cols[1].button("Réinitialiser le lot", key="collection_batch_reset"):
            for row_id in list(st.session_state.get("collection_batch_row_ids", [])):
                clear_batch_row(row_id)
            st.session_state["collection_batch_row_ids"] = [0, 1, 2]
            st.session_state["collection_batch_next_row_id"] = 3
            st.rerun()

        rows = []
        row_ids = list(st.session_state.get("collection_batch_row_ids", [0, 1, 2]))
        if not row_ids:
            row_ids = [0]
            st.session_state["collection_batch_row_ids"] = row_ids
        mobile_batch = bool(is_mobile_mode_func())
        special_options = [
            "Reverse",
            "1ère édition",
            "Japonaise",
            "Holo",
            "Scellé",
            "Stamp",
            "Promo",
            "Master Ball",
            "Poké Ball",
        ]
        for position, row_id in enumerate(row_ids):
            header_cols = st.columns([4, 1])
            header_cols[0].markdown(f"**Carte {position + 1}**")
            if len(row_ids) > 1 and header_cols[1].button("Retirer", key=f"collection_batch_remove_{row_id}"):
                clear_batch_row(row_id)
                st.session_state["collection_batch_row_ids"] = [rid for rid in row_ids if rid != row_id]
                st.rerun()
            if mobile_batch:
                name = st.text_input(
                    "Nom",
                    key=f"collection_batch_name_{row_id}",
                    placeholder="Dracaufeu",
                    on_change=_normalize_collection_batch_name,
                    args=(row_id,),
                )
                number = st.text_input("Numéro", key=f"collection_batch_number_{row_id}", placeholder="004")
                value_raw = st.text_input("Cote / valeur actuelle (€)", key=f"collection_batch_value_{row_id}", placeholder="0.00")
                specials = st.multiselect(
                    "Spécial",
                    special_options,
                    key=f"collection_batch_specials_{row_id}",
                    placeholder="Aucun, Reverse, Holo...",
                )
            else:
                r1, r2, r3, r4 = st.columns([2, 1, 1, 2])
                name = r1.text_input(
                    "Nom",
                    key=f"collection_batch_name_{row_id}",
                    placeholder="Dracaufeu",
                    on_change=_normalize_collection_batch_name,
                    args=(row_id,),
                )
                number = r2.text_input("Numéro", key=f"collection_batch_number_{row_id}", placeholder="004")
                value_raw = r3.text_input("Cote (€)", key=f"collection_batch_value_{row_id}", placeholder="0.00")
                specials = r4.multiselect(
                    "Spécial",
                    special_options,
                    key=f"collection_batch_specials_{row_id}",
                    placeholder="Aucun, Reverse, Holo...",
                )

            if search_in_cache_func and str(name or "").strip() and str(number or "").strip():
                current_match_key = _collection_batch_match_key(row_id)
                if st.session_state.get(f"collection_batch_match_key_{row_id}") != current_match_key:
                    matches = search_in_cache_func(name, number) or []
                    if len(matches) > 1:
                        st.warning(f"{len(matches)} cartes possibles trouvées pour cette ligne : choisis la bonne carte.")
                        choice_cols = st.columns(min(len(matches), 4))
                        for match_idx, (match_card, match_set) in enumerate(matches[:8]):
                            with choice_cols[match_idx % len(choice_cols)]:
                                img_url = _collection_card_image_url(match_card)
                                if img_url:
                                    st.image(img_url, width=110)
                                st.caption(
                                    f"{match_card.get('name', name)} "
                                    f"#{_collection_card_number(match_card)}"
                                )
                                st.caption(str(match_set or ""))
                                if st.button("Choisir", key=f"collection_batch_choose_{row_id}_{match_idx}"):
                                    _apply_collection_batch_match(row_id, match_card, match_set)
                                    st.session_state[f"collection_batch_match_key_{row_id}"] = _collection_batch_match_key(row_id)
                                    st.rerun()
                    elif len(matches) == 1:
                        match_card, match_set = matches[0]
                        if not st.session_state.get(f"collection_batch_set_{row_id}") and not st.session_state.get(f"collection_batch_card_id_{row_id}"):
                            _apply_collection_batch_match(row_id, match_card, match_set)
                            st.session_state[f"collection_batch_match_key_{row_id}"] = _collection_batch_match_key(row_id)
                            st.rerun()
            if str(name or "").strip():
                rows.append(
                    {
                        "name": _proper_collection_card_name(name),
                        "number": number,
                        "set": str(st.session_state.get(f"collection_batch_set_{row_id}", "") or "").strip(),
                        "id": str(st.session_state.get(f"collection_batch_card_id_{row_id}", "") or "").strip(),
                        "image_url": str(st.session_state.get(f"collection_batch_image_{row_id}", "") or "").strip(),
                        "image_url_en": str(st.session_state.get(f"collection_batch_image_en_{row_id}", "") or "").strip(),
                        "quantity": 1,
                        "current_value": _collection_parse_float(value_raw),
                        "condition": "NM",
                        "specials": specials,
                    }
                )

        total_paid = _collection_parse_float(batch_paid_raw)
        weighted_total = sum(float(row.get("current_value", 0.) or 0.) * int(row.get("quantity", 1) or 1) for row in rows)
        if rows:
            if any(float(row.get("current_value", 0.) or 0.) <= 0 for row in rows):
                st.warning("Certaines cartes ont une cote à 0 : elles ne recevront pas de part du prix payé.")
            if weighted_total <= 0:
                st.error("Toutes les cotes sont à 0. Renseigne au moins une cote pour calculer la répartition.")
            else:
                allocations = []
                allocated = 0.
                for idx, row in enumerate(rows):
                    if idx == len(rows) - 1:
                        line_paid_total = round(total_paid - allocated, 2)
                    else:
                        line_paid_total = round((float(row.get("current_value", 0.) or 0.) * int(row.get("quantity", 1) or 1) / weighted_total) * total_paid, 2)
                        allocated = round(allocated + line_paid_total, 2)
                    allocations.append((row, line_paid_total))
                st.markdown("**Récapitulatif avant validation**")
                st.caption(
                    f"Somme des cotes : {fp_func(weighted_total)} · Prix payé : {fp_func(total_paid)} · "
                    f"Valeur actuelle totale : {fp_func(weighted_total)} · Différence : {fp_func(weighted_total - total_paid)}"
                )
                for row, line_paid_total in allocations:
                    st.caption(
                        f"{row['name']} x{row['quantity']} - cote {fp_func(row['current_value'])}/u "
                        f"-> payé calculé {fp_func(line_paid_total)}"
                    )

        if st.button("Enregistrer le lot Collection", key="collection_batch_save", type="primary"):
            if not rows:
                st.error("Ajoute au moins une carte.")
            elif weighted_total <= 0:
                st.error("Impossible d'enregistrer : toutes les cotes sont à 0.")
            else:
                ok, msg = add_collection_batch_func(
                    batch_name=batch_name,
                    total_paid=total_paid,
                    note=batch_note,
                    batch_date=batch_date,
                    rows=rows,
                )
                if ok:
                    st.success(msg)
                    for row_id in list(st.session_state.get("collection_batch_row_ids", [])):
                        clear_batch_row(row_id)
                    st.session_state["collection_batch_row_ids"] = [0, 1, 2]
                    st.session_state["collection_batch_next_row_id"] = 3
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
    collection_cards = sorted(collection_cards, key=_collection_sort_key, reverse=True)

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

    missing_image_cards = [
        (lot_idx, card_idx, lot, card)
        for lot_idx, card_idx, lot, card in collection_cards
        if collection_image_needs_manual_func(card)
    ]
    if missing_image_cards:
        with st.expander(f"Images manquantes ({len(missing_image_cards)})", expanded=False):
            st.caption(
                "Cartes sans image fiable ou avec un chemin local introuvable. "
                "Utilise le bouton Ajouter une image / Modifier l'image sur la carte concernée."
            )
            visible_missing = missing_image_cards[:40]
            for _, _, lot, card in visible_missing:
                name = str(card.get("name", "Carte") or "Carte")
                number = str(card.get("number", "") or "").strip()
                set_name = str(card.get("set", "") or "").strip()
                source = str(lot.get("nom", "Lot") or "Lot")
                meta = " · ".join(x for x in [f"#{number}" if number else "", set_name, source] if x)
                st.caption(f"- {name}{' — ' + meta if meta else ''}")
            if len(missing_image_cards) > len(visible_missing):
                st.caption(f"{len(missing_image_cards) - len(visible_missing)} autre(s) carte(s) masquée(s) pour garder la page légère.")

    search_collection = st.text_input("🔍 Rechercher dans la collection", placeholder="Nom de carte...", key="collection_search")
    if search_collection:
        collection_cards = [
            item for item in collection_cards
            if normalize_name_func(search_collection) in normalize_name_func(item[3].get("name", ""))
        ]
    total_collection_matches = len(collection_cards)
    mobile = bool(is_mobile_mode_func())
    if mobile and not search_collection:
        collection_limit = int(st.session_state.get("collection_mobile_visible_limit", 24) or 24)
        if len(collection_cards) > collection_limit:
            collection_cards = collection_cards[:collection_limit]
            st.caption(
                f"Affichage mobile : {collection_limit} carte(s) sur {total_collection_matches}. "
                "Utilise la recherche ou affiche la suite."
            )
    if perf_count_func is not None:
        perf_count_func("cards_collection_available", total_collection_matches)
        perf_count_func("cards_collection_rendered", len(collection_cards))

    cols_per_row = 3 if mobile else 8
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

    if mobile and not search_collection and total_collection_matches > len(collection_cards):
        if st.button("Afficher plus de cartes Collection", key="collection_mobile_show_more", width="stretch"):
            st.session_state["collection_mobile_visible_limit"] = int(
                st.session_state.get("collection_mobile_visible_limit", 24) or 24
            ) + 24
            st.rerun()

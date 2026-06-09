"""Estimations page renderer for Pokestock.

This module contains the existing Streamlit UI rendering for the Estimations page.
It receives sensitive operations as parameters and preserves the current behavior.
"""

import html
import json
import time
from datetime import datetime

import streamlit as st


def render_estimations_page(
    *,
    load_estimations_func,
    save_estimations_func,
    add_estimation_card_func,
    estimation_totals_func,
    ld_func,
    sd_func,
    fetch_listing_preview_image_func,
    cardmarket_search_url_func,
    search_in_cache_func,
    proxy_img_func,
    img_with_fallback_func,
    render_page_header_func,
    fp_func,
    normalize_name_func,
    parse_float_input_func,
    new_uid_func,
    is_mobile_mode_func,
    ecd_func,
    run_html_func,
):
    st.markdown(
        render_page_header_func("Estimations de lots", "Calcul d'offre d'achat et conversion en lot", "📉"),
        unsafe_allow_html=True,
    )
    st.caption("Prépare un rachat avant d'acheter : ajoute les cartes, choisis le type d'achat, puis regarde le prix maximum conseillé.")
    
    edata = load_estimations_func()
    settings = edata["settings"]
    estimates = edata["estimations"]
    
    st.markdown("""
    <style>
    .estimate-card-row {
        background:white;
        border:2px solid #e2e8f0;
        border-left:6px solid #22c55e;
        border-radius:8px;
        padding:0.75rem 0.9rem;
        margin:0.55rem 0;
        box-shadow:0 3px 10px rgba(15,23,42,0.08);
    }
    .estimate-thumb {
        width:112px;
        height:138px;
        object-fit:cover;
        border-radius:8px;
        border:2px solid #e2e8f0;
        background:#f8fafc;
    }
    .estimate-thumb-pair {
        display:flex;
        gap:0.55rem;
        align-items:center;
        margin:0.35rem 0 0.8rem 2rem;
    }
    .estimate-thumb-pair .estimate-thumb {
        width:112px;
        height:138px;
    }
    .estimate-card-tile {
        margin-bottom:1rem;
    }
    .estimate-card-tile img {
        width:100%;
        border-radius:12px;
        box-shadow:0 4px 12px rgba(15,23,42,0.18);
    }
    .estimate-badge {
        display:inline-block;
        padding:0.18rem 0.45rem;
        border-radius:999px;
        font-size:0.7rem;
        font-weight:800;
        margin-top:0.2rem;
        background:#dbeafe;
        color:#1e3a8a;
    }
    .estimate-badge.collection {
        background:#fef3c7;
        color:#92400e;
    }
    [data-estimation-page-marker] ~ div button,
    [data-testid="stElementContainer"]:has([data-estimation-page-marker]) ~ div button {
        min-height:2.35rem !important;
        height:auto !important;
        padding:0.45rem 0.75rem !important;
        border-radius:8px !important;
        font-size:0.9rem !important;
        box-shadow:none !important;
        background-image:none !important;
    }
    main .stForm button,
    main .stButton > button,
    main button[kind="primary"],
    main button[type="submit"] {
        min-height:2.35rem !important;
        height:auto !important;
        padding:0.45rem 0.8rem !important;
        border-radius:8px !important;
        border-width:2px !important;
        box-shadow:none !important;
        background-image:none !important;
        text-transform:none !important;
    }
    main .stForm button *,
    main .stButton > button *,
    main button[kind="primary"] *,
    main button[type="submit"] * {
        background:transparent !important;
        background-color:transparent !important;
        border:none !important;
        box-shadow:none !important;
        padding:0 !important;
        color:inherit !important;
    }
    .stApp [data-testid="stForm"] button,
    .stApp [data-testid="stForm"] button *,
    .stApp [data-testid="stButton"] button,
    .stApp [data-testid="stButton"] button * {
        box-shadow:none !important;
        background-image:none !important;
    }
    .stApp [data-testid="stForm"] button *,
    .stApp [data-testid="stButton"] button * {
        border:none !important;
        outline:none !important;
        padding:0 !important;
    }
    [data-testid="stElementContainer"]:has([data-estimation-page-marker]) ~ div [data-testid="stForm"] button {
        max-width:22rem !important;
    }
    @media (max-width:760px) {
        .estimate-thumb { width:68px;height:82px; }
        .estimate-thumb-pair { margin:0 0 0.6rem 0.6rem; gap:0.35rem; }
        .estimate-thumb-pair .estimate-thumb { width:68px;height:82px; }
        .estimate-card-row { padding:0.55rem 0.6rem; }
        .estimate-card-tile img { max-height:155px; object-fit:contain; }
    }
    </style>
    """, unsafe_allow_html=True)
    st.markdown('<div data-estimation-page-marker="1"></div>', unsafe_allow_html=True)
    
    run_html_func("""
    <script>
    (function(){
        const doc = parent.document;
        const markerSelector = '[data-est-add-card-form-marker]';
        function compactEstimateButtons(){
            if (!doc.querySelector('[data-estimation-page-marker]')) return;
            doc.querySelectorAll('main button').forEach(function(btn){
                const txt = (btn.innerText || '').trim();
                if (!txt) return;
                btn.style.setProperty('min-height', '2.35rem', 'important');
                btn.style.setProperty('height', 'auto', 'important');
                btn.style.setProperty('padding', '0.45rem 0.75rem', 'important');
                btn.style.setProperty('border-radius', '8px', 'important');
                btn.style.setProperty('font-size', '0.9rem', 'important');
                btn.style.setProperty('box-shadow', 'none', 'important');
                btn.style.setProperty('background-image', 'none', 'important');
                btn.style.setProperty('text-transform', 'none', 'important');
                btn.querySelectorAll('*').forEach(function(child){
                    child.style.setProperty('background', 'transparent', 'important');
                    child.style.setProperty('background-color', 'transparent', 'important');
                    child.style.setProperty('border', 'none', 'important');
                    child.style.setProperty('box-shadow', 'none', 'important');
                    child.style.setProperty('padding', '0', 'important');
                    child.style.setProperty('color', 'inherit', 'important');
                });
                if (txt.includes('Sauvegarder') || txt.includes('Ajouter') || txt.includes('Créer')) {
                    btn.style.setProperty('max-width', '22rem', 'important');
                }
            });
        }
        function syncEstSticky(){
            const markers = Array.from(doc.querySelectorAll(markerSelector));
            markers.forEach(function(marker){
                const uid = marker.getAttribute('data-est-add-card-form-marker');
                const end = doc.querySelector('[data-est-add-card-form-end-marker="' + uid + '"]');
                if (!end) return;
                const parts = [];
                let node = marker.parentElement ? marker.parentElement.nextElementSibling : null;
                while (node && node !== end.parentElement) {
                    parts.push(node);
                    node = node.nextElementSibling;
                }
                parts.forEach(function(part, i){
                    part.setAttribute('data-est-sticky-part', '1');
                    part.style.setProperty('position', 'sticky', 'important');
                    part.style.setProperty('top', (56 + i * 42) + 'px', 'important');
                    part.style.setProperty('z-index', String(900 - i), 'important');
                    part.style.setProperty('background', '#dbeafe', 'important');
                    part.style.setProperty('padding-left', '0.7rem', 'important');
                    part.style.setProperty('padding-right', '0.7rem', 'important');
                    part.style.setProperty('box-shadow', '0 2px 0 #dbeafe', 'important');
                });
            });
            compactEstimateButtons();
        }
        [100,300,700,1300,2500].forEach(function(delay){ setTimeout(syncEstSticky, delay); });
        if (!window.codexEstStickyObserver) {
            window.codexEstStickyObserver = new MutationObserver(function(){
                clearTimeout(window.codexEstStickyTimer);
                window.codexEstStickyTimer = setTimeout(syncEstSticky, 120);
            });
            window.codexEstStickyObserver.observe(doc.body, {childList:true, subtree:true});
        }
    })();
    </script>
    """, height=0)
    
    with st.expander("⚙️ Règles globales de rachat", expanded=False):
        st.caption("Ces pourcentages servent à calculer ton prix max. Exemple : 60% veut dire que 100€ de cote donne 60€ de rachat max.")
        with st.form("estimation_settings_form_fast"):
            new_sources = {}
            cols = st.columns(3)
            for col, (source_name, pct) in zip(cols, settings.get("sources", {}).items()):
                raw = col.text_input(f"{source_name} (%)", value=f"{float(pct):.0f}".replace(".", ","), key=f"est_setting_txt_{source_name}")
                new_sources[source_name] = min(max(parse_float_input_func(raw, pct), 0.0), 100.0)
            source_names = list(new_sources.keys()) or ["Vinted"]
            default_source = st.selectbox(
                "Type par défaut",
                source_names,
                index=source_names.index(settings.get("default_source")) if settings.get("default_source") in source_names else 0,
                key="est_default_source_fast",
            )
            if st.form_submit_button("💾 Sauvegarder les règles"):
                edata["settings"]["sources"] = new_sources
                edata["settings"]["default_source"] = default_source
                save_estimations_func(edata)
                st.success("Règles sauvegardées.")
                st.rerun()
    
    with st.expander("➕ Créer une estimation", expanded=not estimates):
        with st.form("new_estimation_fast"):
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            new_est_name = c1.text_input("Nom", placeholder="Ex: Gros lot de cartes")
            source_names = list(settings.get("sources", {}).keys()) or ["Vinted"]
            new_est_source = c2.selectbox(
                "Type",
                source_names,
                index=source_names.index(settings.get("default_source")) if settings.get("default_source") in source_names else 0,
            )
            new_est_status = c3.selectbox("Statut", ["En cours", "À surveiller", "Achetée", "Refusée"])
            new_est_price = c4.text_input("Prix demandé (€)", value="0,00")
            new_est_url = st.text_input("URL annonce", placeholder="https://www.vinted.fr/items/...")
            if st.form_submit_button("Créer l'estimation"):
                if not new_est_name.strip():
                    st.error("Nom requis.")
                else:
                    estimate = {
                        "uid": new_uid_func("estimate"),
                        "name": new_est_name.strip(),
                        "source": new_est_source,
                        "fees": 0.0,
                        "safety_eur": 0.0,
                        "seller_price": parse_float_input_func(new_est_price, 0.0),
                        "listing_url": new_est_url.strip(),
                        "listing_image_url": fetch_listing_preview_image_func(new_est_url),
                        "status": new_est_status,
                        "created_at": datetime.now().isoformat()[:10],
                        "cards": [],
                    }
                    edata["estimations"].append(estimate)
                    save_estimations_func(edata)
                    st.session_state["active_estimation_uid"] = estimate["uid"]
                    st.rerun()
    
    if not estimates:
        st.info("Aucune estimation pour le moment. Crée ta première estimation au-dessus.")
        st.stop()
    
    if not st.session_state.get("active_estimation_uid") or not any(e.get("uid") == st.session_state.get("active_estimation_uid") for e in estimates):
        st.session_state["active_estimation_uid"] = ""
    
    for estimate in sorted(estimates, key=lambda e: e.get("created_at", ""), reverse=True):
        uid = estimate.get("uid")
        active_open = st.session_state.get("active_estimation_uid") == uid
        totals = estimation_totals_func(estimate, settings)
        listing_thumb = estimate.get("listing_image_url", "")
        if not listing_thumb and estimate.get("listing_url"):
            listing_thumb = fetch_listing_preview_image_func(estimate.get("listing_url", ""))
            if listing_thumb:
                estimate["listing_image_url"] = listing_thumb
                save_estimations_func(edata)
        top_card_thumb = ""
        top_card = None
        for card in estimate.get("cards", []):
            if not card.get("image_url"):
                continue
            if top_card is None or float(card.get("cote", 0.) or 0.) > float(top_card.get("cote", 0.) or 0.):
                top_card = card
                top_card_thumb = card.get("image_url", "")
    
        row_prefix = "▼" if active_open else "›"
        row_label = (
            f"{row_prefix} {estimate.get('name','Estimation')} - "
            f"{estimate.get('source','Vinted')} · {estimate.get('status','En cours')} · "
            f"Cote {fp_func(totals['total_cote'])} · Rachat max {fp_func(totals['max_buy'])}"
        )
        if st.button(row_label, key=f"open_est_{uid}", width="stretch"):
            if active_open:
                st.session_state["active_estimation_uid"] = ""
            else:
                st.session_state["active_estimation_uid"] = uid
            st.rerun()
    
        thumbs_html = ""
        if listing_thumb:
            thumbs_html += f'<img class="estimate-thumb" title="Annonce" src="{html.escape(proxy_img_func(listing_thumb), quote=True)}">'
        if top_card_thumb:
            thumbs_html += f'<img class="estimate-thumb" title="Carte la plus chère" src="{html.escape(proxy_img_func(top_card_thumb), quote=True)}">'
        if thumbs_html:
            st.markdown(f'<div class="estimate-thumb-pair">{thumbs_html}</div>', unsafe_allow_html=True)
    
        if not active_open:
            continue
    
        with st.container():
            if estimate.get("listing_url"):
                safe_url = html.escape(estimate.get("listing_url", ""), quote=True)
                st.markdown(f'<a href="{safe_url}" target="_blank" style="display:inline-block;margin:0.2rem 0 0.7rem 0;padding:0.5rem 0.8rem;border-radius:8px;background:#1e293b;color:white;text-decoration:none;font-weight:800;">🔗 Ouvrir l’annonce</a>', unsafe_allow_html=True)
    
            with st.form(f"estimate_meta_fast_{uid}"):
                m1, m2, m3, m4 = st.columns([2, 1, 1, 1])
                edit_name = m1.text_input("Nom", value=estimate.get("name", ""), key=f"est_name_fast_{uid}")
                source_names = list(settings.get("sources", {}).keys()) or ["Vinted"]
                edit_source = m2.selectbox("Type", source_names, index=source_names.index(estimate.get("source")) if estimate.get("source") in source_names else 0, key=f"est_source_fast_{uid}")
                status_options = ["En cours", "À surveiller", "Achetée", "Refusée"]
                edit_status = m3.selectbox("Statut", status_options, index=status_options.index(estimate.get("status", "En cours")) if estimate.get("status", "En cours") in status_options else 0, key=f"est_status_fast_{uid}")
                edit_seller_price = m4.text_input("Prix vendeur (€)", value=f"{float(estimate.get('seller_price', 0.0) or 0.0):.2f}".replace(".", ","), key=f"est_seller_fast_{uid}")
                eurl1, eurl2 = st.columns([3, 1])
                edit_url = eurl1.text_input("URL annonce", value=estimate.get("listing_url", ""), key=f"est_url_fast_{uid}")
                edit_safety = eurl2.text_input("Marge sécurité (€)", value=f"{float(estimate.get('safety_eur', 0.0) or 0.0):.2f}".replace(".", ","), key=f"est_safety_fast_{uid}")
                if st.form_submit_button("💾 Sauvegarder"):
                    old_url = estimate.get("listing_url", "")
                    estimate["name"] = edit_name.strip() or estimate.get("name", "Estimation")
                    estimate["source"] = edit_source
                    estimate["status"] = edit_status
                    estimate["seller_price"] = parse_float_input_func(edit_seller_price, 0.0)
                    estimate["fees"] = 0.0
                    estimate["safety_eur"] = parse_float_input_func(edit_safety, 0.0)
                    estimate["listing_url"] = edit_url.strip()
                    if estimate["listing_url"] and (estimate["listing_url"] != old_url or not estimate.get("listing_image_url")):
                        estimate["listing_image_url"] = fetch_listing_preview_image_func(estimate["listing_url"])
                    save_estimations_func(edata)
                    st.success("Estimation sauvegardée.")
                    st.rerun()
    
            totals = estimation_totals_func(estimate, settings)
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Cote revente", fp_func(totals["total_cote"]))
            k2.metric("Collection", fp_func(totals["collection_cote"]), f"{totals['collection_cards']} carte(s)")
            k3.metric("Rachat max", fp_func(totals["max_buy"]), f"{totals['pct']:.0f}%")
            k4.metric("Prix vendeur", fp_func(totals["seller_price"]) if totals["seller_price"] > 0 else "—", f"{totals['real_pct']:.1f}%" if totals["real_pct"] else None)
            delta = totals["max_buy"] - totals["seller_price"] if totals["seller_price"] > 0 else 0
            k5.metric("Écart", fp_func(delta) if totals["seller_price"] > 0 else "—")
    
            if totals["seller_price"] > 0:
                if totals["seller_price"] <= totals["max_buy"]:
                    st.success(f"Prix vendeur OK : tu es sous ton prix max de {fp_func(totals['max_buy'] - totals['seller_price'])}.")
                else:
                    st.warning(f"Prix vendeur trop haut : il dépasse ton prix max de {fp_func(totals['seller_price'] - totals['max_buy'])}.")
    
            st.markdown(f'<div data-est-add-card-form-marker="{uid}"></div>', unsafe_allow_html=True)
            st.markdown("**➕ Ajouter une carte**")
            ts_key = f"est_add_ts_{uid}"
            if ts_key not in st.session_state:
                st.session_state[ts_key] = time.time()
            add_ts = st.session_state[ts_key]
            with st.form(f"add_est_card_fast_{uid}_{add_ts}"):
                a1, a2, a3, a4 = st.columns([2, 1, 1, 0.7])
                card_name = a1.text_input("Nom", placeholder="Ex: Dracaufeu")
                card_number = a2.text_input("Numéro", placeholder="004")
                card_cote = a3.text_input("Cote (€)", value="0,00")
                card_qty = a4.text_input("Qté", value="1")
                b1, b2, b3 = st.columns([1, 2, 2])
                card_condition = b1.selectbox("État", ["NM", "EX", "GD", "LP", "PL", "POOR"])
                card_specials = b2.multiselect("Spécial", ["Reverse", "1ère Éd", "Japonaise", "Collection", "Scellé", "Stamp", "Promo", "Master Ball", "Poké Ball"])
                card_note = b3.text_input("Note", placeholder="Photo floue, coin abîmé...")
                keep_collection = "Collection" in card_specials
                clean_specials = [tag for tag in card_specials if tag != "Collection"]
                if keep_collection:
                    st.caption("Collection : cette carte sera affichée dans le menu Collection et exclue du calcul du prix max.")
                if card_name.strip():
                    cm_url = html.escape(cardmarket_search_url_func(card_name, card_number, card_condition, ", ".join(clean_specials)), quote=True)
                    st.markdown(f'<a href="{cm_url}" target="_blank" style="font-size:0.85rem;font-weight:800;color:#1d4ed8;text-decoration:none;">🔎 Chercher la cote sur Cardmarket</a>', unsafe_allow_html=True)
                if st.form_submit_button("➕ Ajouter la carte"):
                    if not card_name.strip():
                        st.error("Nom requis.")
                    else:
                        matches = search_in_cache_func(card_name, card_number)
                        if len(matches) > 1:
                            st.session_state[f"pending_est_choice_{uid}"] = {
                                "name": card_name,
                                "number": card_number,
                                "cote": card_cote,
                                "qty": card_qty,
                                "condition": card_condition,
                                "specials": clean_specials,
                                "note": card_note,
                                "is_collection": keep_collection,
                                "matches": matches[:12],
                            }
                            st.rerun()
                        else:
                            add_estimation_card_func(estimate, card_name, card_number, card_cote, card_qty, card_condition, clean_specials, card_note, keep_collection, matches[0] if matches else None)
                            save_estimations_func(edata)
                            st.session_state[ts_key] = time.time()
                            st.rerun()
            st.markdown(f'<div data-est-add-card-form-end-marker="{uid}"></div>', unsafe_allow_html=True)
    
            pending = st.session_state.get(f"pending_est_choice_{uid}")
            if pending:
                st.warning(f"{len(pending.get('matches', []))} cartes possibles trouvées. Choisis la bonne image.")
                cols = st.columns(4)
                for pidx, match in enumerate(pending.get("matches", [])):
                    card_dict, set_name = match
                    enriched = ecd_func(card_dict, set_name, lang="fr")
                    with cols[pidx % 4]:
                        if enriched.get("image_url"):
                            st.markdown(img_with_fallback_func(enriched.get("image_url", ""), enriched.get("image_url_en", ""), width="100%", style="border-radius:8px;"), unsafe_allow_html=True)
                        st.caption(f"{enriched.get('name','Carte')} · {enriched.get('set','')} · #{enriched.get('number','')}")
                        if st.button("Choisir", key=f"pick_est_{uid}_{pidx}"):
                            add_estimation_card_func(
                                estimate,
                                pending["name"], pending["number"], pending["cote"], pending["qty"],
                                pending["condition"], pending["specials"], pending["note"],
                                pending.get("is_collection", False),
                                match,
                            )
                            save_estimations_func(edata)
                            st.session_state.pop(f"pending_est_choice_{uid}", None)
                            st.session_state[ts_key] = time.time()
                            st.rerun()
                if st.button("Annuler le choix", key=f"cancel_est_choice_{uid}"):
                    st.session_state.pop(f"pending_est_choice_{uid}", None)
                    st.rerun()
    
            st.markdown("### Cartes de l'estimation")
            est_search = st.text_input("🔍 Rechercher dans cette estimation", placeholder="Nom de carte...", key=f"est_card_search_{uid}")
            cards_to_show = estimate.get("cards", [])
            if est_search:
                cards_to_show = [c for c in cards_to_show if normalize_name_func(est_search) in normalize_name_func(c.get("name", ""))]
    
            if not cards_to_show:
                st.info("Aucune carte dans cette estimation pour le moment.")
            else:
                cols_per_row = 3 if is_mobile_mode_func() else 8
                for row_start in range(0, len(cards_to_show), cols_per_row):
                    cols = st.columns(cols_per_row)
                    for cidx, card in enumerate(cards_to_show[row_start:row_start + cols_per_row]):
                        with cols[cidx]:
                            st.markdown('<div class="estimate-card-tile">', unsafe_allow_html=True)
                            if card.get("image_url"):
                                st.markdown(img_with_fallback_func(card.get("image_url", ""), card.get("image_url_en", ""), width="100%", style=""), unsafe_allow_html=True)
                            else:
                                st.markdown('<div style="height:130px;border-radius:12px;background:#f8fafc;display:flex;align-items:center;justify-content:center;border:2px solid #e2e8f0;">🃏</div>', unsafe_allow_html=True)
                            badge_cls = "collection" if card.get("is_collection") else ""
                            badge_text = "Collection" if card.get("is_collection") else "Revente"
                            st.markdown(f"**{card.get('name','Carte')}**")
                            meta = " · ".join(x for x in [f"#{card.get('number','')}" if card.get("number") else "", card.get("condition", ""), card.get("special", "")] if x)
                            if meta:
                                st.caption(meta)
                            st.markdown(f'<span class="estimate-badge {badge_cls}">{badge_text}</span>', unsafe_allow_html=True)
                            st.caption(f"{fp_func(float(card.get('cote',0) or 0))} · x{int(card.get('quantity',1) or 1)}")
                            cm_card_url = html.escape(cardmarket_search_url_func(
                                card.get("name", ""),
                                card.get("number", ""),
                                card.get("condition", ""),
                                card.get("special", ""),
                            ), quote=True)
                            st.markdown(
                                f'<a href="{cm_card_url}" target="_blank" style="display:inline-block;margin:0.12rem 0 0.35rem 0;font-size:0.76rem;font-weight:800;color:#1d4ed8;text-decoration:none;">🔎 Cardmarket</a>',
                                unsafe_allow_html=True,
                            )
                            if st.button("🗑️", key=f"del_est_card_fast_{uid}_{card.get('uid')}"):
                                estimate["cards"] = [c for c in estimate.get("cards", []) if c.get("uid") != card.get("uid")]
                                save_estimations_func(edata)
                                st.rerun()
                            st.markdown("</div>", unsafe_allow_html=True)
    
            st.markdown("---")
            action_cols = st.columns(3)
            if action_cols[0].button("📦 Créer un vrai lot", width="stretch", disabled=not estimate.get("cards") or bool(estimate.get("created_lot_uid")), key=f"create_real_lot_fast_{uid}"):
                purchase_price = float(estimate.get("seller_price", 0.0) or 0.0) or totals["max_buy"]
                cd_real = ld_func()
                lot_uid = new_uid_func("lot")
                new_lot = {
                    "lot_uid": lot_uid,
                    "nom": estimate.get("name", "Lot estimé"),
                    "prix_achat": purchase_price,
                    "cards": [],
                    "ventes": [],
                    "created": datetime.now().isoformat(),
                    "from_estimation_uid": estimate.get("uid"),
                    "estimation_listing_url": estimate.get("listing_url", ""),
                    "estimation_source": estimate.get("source"),
                    "estimation_value": totals["total_cote"],
                    "estimation_target_pct": totals["pct"],
                }
                for card in estimate.get("cards", []):
                    specials = [s.strip() for s in str(card.get("special", "")).split(",") if s.strip()]
                    special_tag = ", ".join([s for s in specials if s not in ("Reverse", "1ère Éd", "Japonaise")])
                    new_lot["cards"].append({
                        "card_uid": new_uid_func("card"),
                        "id": "",
                        "name": card.get("name", "Carte"),
                        "set": card.get("set", ""),
                        "number": card.get("number", ""),
                        "rarity": card.get("rarity", ""),
                        "image_url": card.get("image_url", ""),
                        "image_url_en": card.get("image_url_en", ""),
                        "quantity": int(card.get("quantity", 1) or 1),
                        "sold_quantity": 0,
                        "condition": card.get("condition", "NM"),
                        "suggested_price": float(card.get("cote", 0.0) or 0.0),
                        "is_reverse": "Reverse" in specials,
                        "is_ed1": "1ère Éd" in specials,
                        "special_tag": special_tag,
                        "is_collection_keep": bool(card.get("is_collection")),
                        "sold_entries": [],
                    })
                cd_real.setdefault("lots", []).append(new_lot)
                sd_func(cd_real)
                estimate["status"] = "Achetée"
                estimate["created_lot_uid"] = lot_uid
                save_estimations_func(edata)
                st.success("Lot créé dans le menu Lots.")
                st.rerun()
            if action_cols[1].button("Dupliquer", width="stretch", key=f"duplicate_est_fast_{uid}"):
                copy_est = json.loads(json.dumps(estimate, ensure_ascii=False))
                copy_est["uid"] = new_uid_func("estimate")
                copy_est["name"] = f"Copie - {copy_est.get('name','Estimation')}"
                copy_est.pop("created_lot_uid", None)
                copy_est["created_at"] = datetime.now().isoformat()[:10]
                for card in copy_est.get("cards", []):
                    card["uid"] = new_uid_func("estcard")
                edata["estimations"].append(copy_est)
                save_estimations_func(edata)
                st.session_state["active_estimation_uid"] = copy_est["uid"]
                st.rerun()
            if action_cols[2].button("Supprimer", width="stretch", key=f"delete_est_fast_{uid}"):
                edata["estimations"] = [e for e in edata["estimations"] if e.get("uid") != uid]
                save_estimations_func(edata)
                st.session_state["active_estimation_uid"] = ""
                st.rerun()
    
    st.stop()

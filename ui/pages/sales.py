"""Vente / Echange page renderer for Pokestock.

This module contains the existing sales/exchange page body. It receives app.py
globals as context to preserve behavior while moving the large page out of app.py.
"""


def render_sales_page(context):
    globals().update(context)
    if st.session_state.pop("sale_scroll_top_pending", False):
        run_html("""
        <script>
        (function(){
            const win = parent.window;
            const doc = parent.document;
            if ('scrollRestoration' in win.history) win.history.scrollRestoration = 'manual';
            const scrollTop = () => win.scrollTo({top:0,left:0,behavior:'instant'});
            [0, 80, 220, 520, 1100, 1800].forEach(delay => setTimeout(scrollTop, delay));
            const waitForImagesThenScroll = () => {
                const imgs = Array.from(doc.querySelectorAll('img'));
                if (!imgs.length) { scrollTop(); return; }
                let pending = imgs.filter(img => !img.complete).length;
                if (pending === 0) { scrollTop(); return; }
                const done = () => { pending -= 1; if (pending <= 0) scrollTop(); };
                imgs.forEach(img => {
                    if (img.complete) return;
                    img.addEventListener('load', done, {once:true});
                    img.addEventListener('error', done, {once:true});
                });
                setTimeout(scrollTop, 3500);
            };
            setTimeout(waitForImagesThenScroll, 250);
        })();
        </script>
        """, height=0)
    st.markdown(
        render_page_header("Vente / Échange", "Vendre, négocier et gérer les échanges", "💰"),
        unsafe_allow_html=True,
    )
    
    tab2, tab3 = st.tabs(["💰 Vente", "🔄 Échange"])

    with tab2:
        st.markdown('<span data-sale-mobile-marker="1"></span>', unsafe_allow_html=True)
        st.subheader("Vente")
        
        cd=ld()
        if not cd.get("lots"):
            st.warning("Créez d'abord un lot")
        else:
            if "bulk_cart" not in st.session_state:
                st.session_state.bulk_cart = []

            # ── Barre de recherche + filtre lot + compteur panier ──
            col_search, col_lot_filter, col_cart = st.columns([3, 2, 1])
            with col_search:
                search_vente = st.text_input("🔍 Rechercher une carte", placeholder="Nom de la carte...", key="search_vente", label_visibility="collapsed")
            with col_lot_filter:
                vente_lots_with_idx = sorted(
                    list(enumerate(cd.get("lots", []))),
                    key=lambda item: (1 if (is_trade_lot(item[1]) or is_storage_lot(item[1])) else 0, item[0])
                )
                lot_options = [("Tous les lots", None)] + [(f"{i+1}. {lot.get('nom', f'Lot {i+1}')}", i) for i, lot in vente_lots_with_idx]
                lot_labels = [name for name, _ in lot_options]
                selected_lot_label = st.selectbox("Lot affiché", lot_labels, key="bulk_lot_filter_v2", label_visibility="collapsed")
                selected_lot_idx = next(idx for name, idx in lot_options if name == selected_lot_label)
            with col_cart:
                nb_panier = sum(item["quantity"] for item in st.session_state.bulk_cart)
                total_panier = sum(item["quantity"] * item["price_base"] for item in st.session_state.bulk_cart)
                if nb_panier > 0:
                    st.button(f"🛒 {nb_panier} · {fp(total_panier)}", key="btn_panier", width="stretch", type="primary", on_click=scroll_to_cart_prepare)
                else:
                    st.markdown('<div style="background:#e2e8f0;color:#64748b;padding:0.5rem 1rem;border-radius:12px;font-weight:700;text-align:center;">🛒 Vide</div>', unsafe_allow_html=True)
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

            # Construire liste panier pour vérification rapide
            cart_keys = {item.get("card_uid") for item in st.session_state.bulk_cart if item.get("card_uid")}

            # ── Grille par lot ou grille globale si recherche ──
            if search_vente:
                # Recherche active → toutes les cartes trouvées en une seule grille
                all_found = []
                rendered_sale_cards_count = 0
                for li, lot in vente_lots_with_idx:
                    if selected_lot_idx is not None and li != selected_lot_idx:
                        continue
                    for ci, card in enumerate(lot.get("cards", [])):
                        if card_available_qty(card) > 0 and normalize_name(search_vente) in normalize_name(card.get("name","")):
                            all_found.append((li, ci, card, lot))

                if "perf_count" in globals():
                    perf_count("cards_sales_rendered", len(all_found))
                COLS_PER_ROW = 3 if is_mobile_mode() else 8
                for row_start in range(0, len(all_found), COLS_PER_ROW):
                    cols = st.columns(COLS_PER_ROW, gap=None if is_mobile_mode() else "small")
                    for col_idx, (li, ci, card, lot) in enumerate(all_found[row_start:row_start + COLS_PER_ROW]):
                        stock = card_available_qty(card)
                        in_cart = card.get("card_uid") in cart_keys
                        with cols[col_idx]:
                            if card.get("image_url"):
                                if in_cart:
                                    st.markdown(f'<div style="position:relative"><img src="{proxy_img(card["image_url"])}" style="width:100%;border-radius:12px;border:4px solid #22c55e;"><div style="position:absolute;top:5px;right:5px;background:#22c55e;color:white;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:0.8rem;">✓</div></div>', unsafe_allow_html=True)
                                else:
                                    st.image(proxy_img(card["image_url"]), width="stretch")
                            else:
                                st.markdown("🃏")
                            st.markdown(f"**{card['name']}**")
                            st.caption(f"#{card.get('number','')}" if is_mobile_mode() else f"{card.get('set','')} · #{card.get('number','')}")
                            st.caption(f"💰 {fp(card.get('suggested_price', 0))} · 📦 {stock}")
                            if not is_mobile_mode():
                                st.caption(f"🗂️ {lot['nom']}")
                            q_key = card.get("card_uid") or f"{li}_{ci}"
                            q_add = st.number_input("Qté", 1, stock, 1, key=f"bulk_q_{q_key}")
                            if in_cart:
                                st.button("✅ Dans le panier", key=f"add_{li}_{ci}", width="stretch", on_click=bulk_cart_remove, kwargs={"card_uid": card.get("card_uid")})
                            else:
                                st.button("🛒 Ajouter", key=f"add_{li}_{ci}", width="stretch", type="primary", on_click=bulk_cart_add, args=({"lot_idx":li,"card_idx":ci,"lot_uid":lot.get("lot_uid"),"card_uid":card.get("card_uid"),"lot_name":lot['nom'],"card_name":card['name'],"card_set":card.get('set',''),"quantity":q_add,"price_base":card.get("suggested_price",0),"lot_profitable":cp(lot)>=0},))
            else:
                # Pas de recherche → groupé par lot avec titre
                for li, lot in vente_lots_with_idx:
                    if selected_lot_idx is not None and li != selected_lot_idx:
                        continue
                    cards_in_stock = [(ci, c) for ci, c in enumerate(lot.get("cards", [])) if card_available_qty(c) > 0]
                    rendered_sale_cards_count += len(cards_in_stock)
                    if cards_in_stock:
                        st.markdown(f"### 📦 {lot['nom']}")
                        COLS_PER_ROW = 3 if is_mobile_mode() else 8
                        for row_start in range(0, len(cards_in_stock), COLS_PER_ROW):
                            cols = st.columns(COLS_PER_ROW, gap=None if is_mobile_mode() else "small")
                            for col_idx, (ci, card) in enumerate(cards_in_stock[row_start:row_start + COLS_PER_ROW]):
                                stock = card_available_qty(card)
                                in_cart = card.get("card_uid") in cart_keys
                                with cols[col_idx]:
                                    if card.get("image_url"):
                                        if in_cart:
                                            st.markdown(f'<div style="position:relative"><img src="{proxy_img(card["image_url"])}" style="width:100%;border-radius:12px;border:4px solid #22c55e;"><div style="position:absolute;top:5px;right:5px;background:#22c55e;color:white;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:0.8rem;">✓</div></div>', unsafe_allow_html=True)
                                        else:
                                            st.image(proxy_img(card["image_url"]), width="stretch")
                                    else:
                                        st.markdown("🃏")
                                    st.markdown(f"**{card['name']}**")
                                    st.caption(f"#{card.get('number','')}" if is_mobile_mode() else f"{card.get('set','')} · #{card.get('number','')}")
                                    st.caption(f"💰 {fp(card.get('suggested_price', 0))} · 📦 {stock}")
                                    q_key = card.get("card_uid") or f"{li}_{ci}"
                                    q_add = st.number_input("Qté", 1, stock, 1, key=f"bulk_q_{q_key}")
                                    if in_cart:
                                        st.button("✅ Dans le panier", key=f"add_{li}_{ci}", width="stretch", on_click=bulk_cart_remove, kwargs={"card_uid": card.get("card_uid")})
                                    else:
                                        st.button("🛒 Ajouter", key=f"add_{li}_{ci}", width="stretch", type="primary", on_click=bulk_cart_add, args=({"lot_idx":li,"card_idx":ci,"lot_uid":lot.get("lot_uid"),"card_uid":card.get("card_uid"),"lot_name":lot['nom'],"card_name":card['name'],"card_set":card['set'],"quantity":q_add,"price_base":card.get("suggested_price",0),"lot_profitable":cp(lot)>=0},))
                        st.markdown("---")
            
                if "perf_count" in globals():
                    perf_count("cards_sales_rendered", rendered_sale_cards_count)

            # ── Panier ──
            st.markdown('<div id="cart-anchor"></div>', unsafe_allow_html=True)
            if not st.session_state.bulk_cart:
                st.info("📭 Panier vide - Cliquez sur 🛒 Ajouter pour ajouter des cartes")
            else:
                st.markdown("### 🛒 Panier")
                total_base = sum(item["quantity"] * item["price_base"] for item in st.session_state.bulk_cart)
                
                for idx, item in enumerate(st.session_state.bulk_cart):
                    _, _, _, cart_card = resolve_card_ref(cd, item)
                    max_cart_qty = max(card_available_qty(cart_card), 1) if cart_card else int(item["quantity"])
                    if int(item["quantity"]) > max_cart_qty:
                        item["quantity"] = max_cart_qty
                        save_activity_state()
                    cols = st.columns([3, 1, 1, 1, 1, 1])
                    cols[0].write(f"{item['card_name']} ({item['card_set']}) - {item['lot_name']}")
                    cols[1].number_input("Qté", 1, max_cart_qty, int(item["quantity"]), key=f"cart_qty_{idx}", on_change=bulk_cart_set_quantity, args=(idx,), label_visibility="collapsed")
                    cols[2].write(f"{fp(item['price_base'])}/u")
                    cols[3].write(f"= {fp(item['quantity'] * item['price_base'])}")
                    cols[4].button("➕", key=f"plus_{idx}", on_click=bulk_cart_increment, args=(idx,))
                    cols[5].button("🗑️", key=f"remove_{idx}", on_click=bulk_cart_pop, args=(idx,))
                
                st.markdown("---")
                st.markdown(f"**Prix total de base : {fp(total_base)}**")
                
                vente_col1, vente_col2 = st.columns(2)
                
                with vente_col1:
                    st.button("✅ Vendre au prix de base", type="primary", width="stretch", on_click=bulk_sale_prepare, args=("base", total_base))
                
                    total_base_ref = round(float(total_base), 2)
                    if st.session_state.get("negociated_price_base_ref") != total_base_ref:
                        st.session_state["negociated_price"] = total_base_ref
                        st.session_state["negociated_price_base_ref"] = total_base_ref
                    negociated_price = st.number_input("💰 Prix négocié", 0., float(total_base)*2, float(st.session_state.get("negociated_price", total_base)), 0.5, key="negociated_price")
                    st.button("🤝 Vendre au prix négocié", width="stretch", on_click=bulk_sale_prepare, args=("negociated", negociated_price))

                # Dialog canal pour vente en lot
                if st.session_state.get("show_canal_dialog_bulk"):
                    st.session_state["show_canal_dialog_bulk"] = False
                    pending = st.session_state.get("pending_bulk_sale", {})

                    @st.dialog("📡 Canal de vente")
                    def ask_canal_bulk():
                        st.markdown(f"**Vente — {fp(pending.get('price', 0))}**")
                        CANAUX = ["Main propre", "Brocante", "Dexify_TCG", "Pokédeal"]
                        canal_b = st.selectbox("Via quel canal ?", CANAUX, key="canal_bulk_sel")
                        c1, c2 = st.columns(2)
                        if c1.button("✅ Confirmer", type="primary", width="stretch"):
                            if pending.get("type") == "base":
                                sale_items = [
                                    {**item, "unit_price": item["price_base"]}
                                    for item in st.session_state.bulk_cart
                                ]
                            else:
                                cd_bulk = ld()
                                def get_lot_score(lot_idx):
                                    lot_data = cd_bulk["lots"][lot_idx]
                                    pa = lot_data.get("prix_achat", 0.)
                                    ca = cr(lot_data)
                                    stock_val = sum(card_available_qty(c)*c.get("suggested_price",0.) for c in lot_data.get("cards",[]))
                                    taux_remb = (ca / pa) if pa > 0 else 1.0
                                    return max(taux_remb * (ca + stock_val), 0.01)
                                reduction = total_base - pending["price"]
                                MAX_REDUCTION_RATE = 0.30
                                scores = [get_lot_score(item["lot_idx"]) * item["quantity"] * item["price_base"] for item in st.session_state.bulk_cart]
                                total_score = sum(scores) or 1.
                                reductions = [min(reduction * (s/total_score), item["quantity"]*item["price_base"]*MAX_REDUCTION_RATE) for s, item in zip(scores, st.session_state.bulk_cart)]
                                sale_items = []
                                for i, item in enumerate(st.session_state.bulk_cart):
                                    item_price = max(0, (item["quantity"]*item["price_base"] - reductions[i]) / item["quantity"])
                                    sale_items.append({**item, "unit_price": item_price})
                            ok, msg = scu_many(sale_items, canal_b)
                            if ok:
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

    with tab3:
        st.subheader("🔄 Échange de cartes")
        st.caption("Échange un ou plusieurs cartes de tes lots contre d'autres cartes.")
        cd_sw = ld()
        trade_snapshot = json.dumps(cd_sw.get("lots", []), ensure_ascii=False, sort_keys=True)
        ensure_trade_lot(cd_sw)
        migrate_open_trade_cards(cd_sw)
        if json.dumps(cd_sw.get("lots", []), ensure_ascii=False, sort_keys=True) != trade_snapshot:
            sd(cd_sw)
            # No need to reload - sd() updates the cache

        # ── Panier d'échange (cartes à donner) ──
        if "swap_cart_give" not in st.session_state:
            st.session_state.swap_cart_give = []  # liste de {lot_idx, card_idx, card_name, set, number, value}
        if "swap_cart_receive" not in st.session_state:
            st.session_state.swap_cart_receive = []  # liste de {name, set, number, value, lot_target_idx}
        st.session_state.setdefault("swap_cash_give", 0.0)
        st.session_state.setdefault("swap_cash_receive", 0.0)

        col_give, col_receive = st.columns(2)

        # ── Colonne DONNER ──
        with col_give:
            st.markdown("### 📤 Cartes à donner")
            search_sw = st.text_input("🔍 Chercher une carte à donner", placeholder="Nom...", key="search_swap")

            all_stock_sw = []
            for li, lot in enumerate(cd_sw.get("lots", [])):
                for ci, card in enumerate(lot.get("cards", [])):
                    stock = card.get("quantity", 0) - card.get("sold_quantity", 0)
                    if stock > 0:
                        if not search_sw or normalize_name(search_sw) in normalize_name(card.get("name", "")):
                            all_stock_sw.append((li, ci, card, lot, stock))

            give_keys = {g.get("card_uid") for g in st.session_state.swap_cart_give if g.get("card_uid")}

            for li, ci, card, lot, stock in all_stock_sw[:24]:
                in_give = card.get("card_uid") in give_keys
                c_img, c_info, c_btn = st.columns([1, 3, 1])
                with c_img:
                    # image_url est déjà l'URL complète stockée dans la carte
                    img_sw = card.get("image_url","") or card.get("image","")
                    if img_sw:
                        border = "border:3px solid #ef4444;" if in_give else ""
                        st.markdown(f'<img src="{proxy_img(img_sw)}" style="width:60px;border-radius:8px;{border}">', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="width:60px;height:84px;background:#f1f5f9;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1.5rem;">🃏</div>', unsafe_allow_html=True)
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
                            st.session_state.swap_cart_give.append({"lot_idx":li,"card_idx":ci,"lot_uid":lot.get("lot_uid"),"card_uid":card.get("card_uid"),"card_name":card["name"],"set":card.get("set",""),"number":card.get("number",""),"value":float(card.get("suggested_price",0)),"lot_name":lot["nom"]})
                            save_activity_state()
                            st.rerun()

            if st.session_state.swap_cart_give:
                st.markdown("---")
                st.markdown("**Cartes à donner :**")
                total_give = 0.
                for g in st.session_state.swap_cart_give:
                    st.markdown(f"• {g['card_name']} ({fp(g['value'])})")
                    total_give += g["value"]
                cash_give = st.number_input("Argent ajouté par moi (€)", 0., 99999., float(st.session_state.get("swap_cash_give", 0.0)), 0.5, key="swap_cash_give")
                st.metric("Total donné", fp(total_give + cash_give))

        # ── Colonne RECEVOIR ──
        with col_receive:
            st.markdown("### 📥 Cartes à recevoir")
            st.caption("Les cartes reçues seront rangées dans le lot Trade. Leur valeur de stock et leur future vente seront attribuées aux lots contributeurs selon leur part.")

            # Ajouter une carte à recevoir
            with st.expander("➕ Ajouter une carte reçue", expanded=len(st.session_state.swap_cart_receive)==0):
                # Initialiser les clés si absentes
                if st.session_state.pop("clear_recv_fields", False):
                    for key in ("recv_name", "recv_num", "recv_val", "recv_collection_keep"):
                        st.session_state.pop(key, None)
                    st.session_state.recv_name_val = ""
                    st.session_state.recv_num_val = ""
                if "recv_name_val" not in st.session_state:
                    st.session_state.recv_name_val = ""
                if "recv_num_val" not in st.session_state:
                    st.session_state.recv_num_val = ""

                def on_recv_change():
                    st.rerun()

                r1, r2 = st.columns(2)
                recv_name = r1.text_input("Nom de la carte", key="recv_name",
                    placeholder="Ex: Lugia",
                    value=st.session_state.recv_name_val)
                recv_num = r2.text_input("Numéro", key="recv_num",
                    placeholder="Ex: 042",
                    value=st.session_state.recv_num_val)
                recv_val = st.number_input("Valeur estimée (€)", 0., 9999., 0., 0.5, key="recv_val")
                recv_collection_keep = st.checkbox("Carte collection / à garder", key="recv_collection_keep")

                # Mettre à jour les valeurs en session
                st.session_state.recv_name_val = recv_name
                st.session_state.recv_num_val = recv_num

                # Recherche image via le cache - utilise ecd comme acm
                recv_image_url = ""
                recv_set_name = ""
                set_id_sw_prev = ""
                local_id_sw_prev = ""
                if recv_name and recv_num:
                    try:
                        cards_index = st.session_state.get("cards_index", {})
                        name_norm_sw = normalize_name(recv_name.lower())
                        candidates = []
                        if name_norm_sw in cards_index:
                            candidates = list(cards_index[name_norm_sw])
                        if not candidates:
                            for k, v in cards_index.items():
                                if name_norm_sw in k:
                                    candidates.extend(v)

                        st.caption(f"🔍 {len(candidates)} carte(s) trouvée(s) pour « {recv_name} » dans le cache")

                        if candidates:
                            num_filtered = [
                                (c,sn,sid) for c,sn,sid in candidates
                                if str(c.get("localId","")).lstrip("0") == recv_num.lstrip("0")
                                or str(c.get("number","")).lstrip("0") == recv_num.lstrip("0")
                            ]
                            st.caption(f"🔢 Après filtrage numéro {recv_num} : {len(num_filtered)} résultat(s)")
                            if num_filtered:
                                card_sw, set_name_sw, set_id_sw = num_filtered[0]
                                local_id_sw_prev = str(card_sw.get("localId","") or card_sw.get("number",""))
                                set_id_sw_prev = set_id_sw
                                st.caption(f"✅ Carte sélectionnée : {card_sw.get('name','')} — set={set_id_sw} n°{local_id_sw_prev}")
                                enriched_sw = ecd(card_sw, set_name_sw, lang="fr")
                                recv_image_url = enriched_sw.get("image_url", "")
                                recv_set_name = set_name_sw
                                st.caption(f"🖼️ URL image : {recv_image_url[:60] if recv_image_url else 'VIDE'}")
                            else:
                                st.caption(f"⚠️ Aucune carte avec le numéro {recv_num} dans le cache")
                        else:
                            st.caption(f"⚠️ Nom « {recv_name} » introuvable dans le cache")
                    except Exception as e:
                        st.caption(f"❌ Erreur : {e}")

                recv_name = recv_name.strip().title() if recv_name else recv_name

                if recv_image_url and recv_name and recv_num:
                    url_en_prev = f"https://assets.tcgdex.net/en/{set_id_sw_prev}/{local_id_sw_prev}/high.webp" if set_id_sw_prev else ""
                    st.markdown(img_with_fallback(recv_image_url, url_en_prev, width="80px", style="border-radius:8px;margin:0.3rem 0;"), unsafe_allow_html=True)
                elif recv_name and recv_num:
                    st.warning("📷 Carte non trouvée dans la base. Tu pourras ajouter la photo manuellement via 🖼️ une fois la carte ajoutée au lot.")
                elif recv_name and not recv_num:
                    st.caption("💡 Ajoute le numéro pour afficher la bonne carte")

                if st.button("➕ Ajouter cette carte", key="add_recv"):
                    if recv_name:
                        st.session_state.swap_cart_receive.append({
                            "name": recv_name,
                            "set": recv_set_name,
                            "number": recv_num,
                            "value": recv_val,
                            "image_url": recv_image_url,
                            "is_collection_keep": recv_collection_keep,
                        })
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
                    if r.get("image_url"):
                        rc1.markdown(f'<img src="{proxy_img(r["image_url"])}" style="width:45px;border-radius:6px;">', unsafe_allow_html=True)
                    else:
                        rc1.markdown("🃏")
                    rc2.markdown(f"**{r['name']}** ({fp(r['value'])})")
                    if r.get("is_collection_keep"):
                        rc2.caption("Collection / à garder")
                    if rc3.button("❌", key=f"rm_recv_{i}"):
                        st.session_state.swap_cart_receive.pop(i)
                        save_activity_state()
                        st.rerun()
                    total_receive += r["value"]
                cash_receive = st.number_input("Argent reçu en plus (€)", 0., 99999., float(st.session_state.get("swap_cash_receive", 0.0)), 0.5, key="swap_cash_receive")
                st.metric("Total reçu", fp(total_receive + cash_receive))

                # Afficher la répartition prévue
                if st.session_state.swap_cart_give:
                    total_give_val = sum(g["value"] for g in st.session_state.swap_cart_give)
                    cash_give = float(st.session_state.get("swap_cash_give", 0.0) or 0.0)
                    cash_receive = float(st.session_state.get("swap_cash_receive", 0.0) or 0.0)
                    diff = (total_receive + cash_receive) - (total_give_val + cash_give)
                    diff_color = "#10b981" if diff >= 0 else "#ef4444"
                    st.markdown(f'<div style="font-size:0.9rem;font-weight:700;color:{diff_color};">{"📈" if diff>=0 else "📉"} Différence : {diff:+.2f}€</div>', unsafe_allow_html=True)

                    # Prévisualiser la répartition par lot
                    st.markdown("---")
                    st.markdown("**📊 Répartition automatique du bénéfice par lot :**")
                    st.caption("Les cartes reçues iront dans le lot Trade. Ici, on affiche seulement la part de valeur attribuée à chaque lot contributeur : la carte n'est pas dupliquée.")
                    valeur_par_lot = {}
                    for g in st.session_state.swap_cart_give:
                        li, _, _, _ = resolve_card_ref(cd_sw, g)
                        if li is None:
                            continue
                        valeur_par_lot[li] = valeur_par_lot.get(li, 0.) + g["value"]
                    total_contrib = sum(valeur_par_lot.values()) or 1.
                    for li, val in valeur_par_lot.items():
                        lot_nom = cd_sw["lots"][li]["nom"]
                        pct = val / total_contrib * 100
                        valeur_estimee_trade = sum(r["value"] for r in st.session_state.swap_cart_receive) * pct / 100
                        st.markdown(f'<div style="font-size:0.82rem;color:#64748b;">🗂️ <b>{lot_nom}</b> — contribution {pct:.0f}% → {valeur_estimee_trade:.2f}€ de valeur Trade attribuée</div>', unsafe_allow_html=True)

        # ── Bouton confirmer l'échange ──
        if st.session_state.swap_cart_give and st.session_state.swap_cart_receive:
            st.markdown("---")
            if st.button("✅ Confirmer l'échange", type="primary", width="stretch"):
                cdd = ld()
                cash_give = float(st.session_state.get("swap_cash_give", 0.0) or 0.0)
                cash_receive = float(st.session_state.get("swap_cash_receive", 0.0) or 0.0)
                # Calculer la valeur totale donnée par lot
                valeur_par_lot_donne = {}
                for g in st.session_state.swap_cart_give:
                    li, ci, lot_g, card_g_ref = resolve_card_ref(cdd, g)
                    if card_g_ref is None:
                        st.error(f"Carte introuvable dans l'échange : {g.get('card_name', 'carte inconnue')}")
                        st.stop()
                    g["lot_idx"], g["card_idx"] = li, ci
                    valeur_par_lot_donne[li] = valeur_par_lot_donne.get(li, 0.) + g["value"]
                total_valeur_donnee = sum(valeur_par_lot_donne.values()) or 1.
                total_cards_given_value = sum(float(g.get("value", 0.) or 0.) for g in st.session_state.swap_cart_give) or 1.

                # Marquer les cartes données comme échangées
                for g in st.session_state.swap_cart_give:
                    _, _, _, card_g = resolve_card_ref(cdd, g)
                    if card_g is None:
                        continue
                    cash_part = cash_receive * (float(g.get("value", 0.) or 0.) / total_cards_given_value) if cash_receive > 0 else 0.
                    card_g["sold_quantity"] = card_g.get("sold_quantity", 0) + 1
                    card_g.setdefault("sold_entries", []).append({
                        "date": datetime.now().isoformat(),
                        "quantity": 1, "price": cash_part,
                        "card_name": card_g["name"],
                        "card_set": card_g.get("set",""),
                        "card_number": card_g.get("number",""),
                        "suggested_price_at_sale": float(card_g.get("suggested_price",0)),
                        "canal": "Échange", "is_exchange": True,
                        "exchange_cash_received": cash_receive,
                        "exchange_cash_part": cash_part,
                        "exchanged_for": ", ".join(r["name"] for r in st.session_state.swap_cart_receive),
                    })

                # Ajouter les cartes reçues dans le lot Trade unique.
                trade_lot_idx = ensure_trade_lot(cdd)

                for r in st.session_state.swap_cart_receive:
                    new_card = {
                        "name": r["name"], "set": r.get("set",""), "number": r.get("number",""),
                        "suggested_price": r["value"], "quantity": 1, "sold_quantity": 0,
                        "condition": "NM", "is_reverse": False, "is_ed1": False,
                        "image_url": r.get("image_url",""), "sold_entries": [],
                        "received_by_exchange": True,
                        "exchange_cash_paid": cash_give,
                        "exchange_cash_received": cash_receive,
                        "exchanged_from": ", ".join(g["card_name"] for g in st.session_state.swap_cart_give),
                        "exchange_repartition": {
                            str(li_donne): (valeur_par_lot_donne[li_donne] / total_valeur_donnee) * r["value"]
                            for li_donne in valeur_par_lot_donne
                        },
                        "is_collection_keep": bool(r.get("is_collection_keep")),
                        "exchange_date": datetime.now().isoformat()[:10],
                    }
                    cdd["lots"][trade_lot_idx]["cards"].append(new_card)
                sd(cdd)
                nb_give = len(st.session_state.swap_cart_give)
                nb_recv = len(st.session_state.swap_cart_receive)
                st.session_state.swap_cart_give = []
                st.session_state.swap_cart_receive = []
                st.session_state.swap_cash_give = 0.0
                st.session_state.swap_cash_receive = 0.0
                save_activity_state()
                st.success(f"✅ Échange confirmé : {nb_give} carte(s) donnée(s) contre {nb_recv} carte(s) reçue(s) !")
                st.rerun()




"""Lots page renderer for Pokestock.

This module contains the existing Lots page body. It receives app.py globals
as context to preserve behavior while moving the large page out of app.py.
"""


def render_lots_page(context):
    globals().update(context)
    st.markdown(
        render_page_header("Gestion des lots", "Inventaire, ajout de cartes et suivi par lot", "📦"),
        unsafe_allow_html=True,
    )

    cd = ld()  # Charger les données en premier
    lots_snapshot = json.dumps(cd.get("lots", []), ensure_ascii=False, sort_keys=True)
    ensure_system_lots(cd)
    migrate_open_trade_cards(cd)
    if json.dumps(cd.get("lots", []), ensure_ascii=False, sort_keys=True) != lots_snapshot:
        sd(cd)
        # No need to reload - sd() updates the cache

    # Bordures et ouverture rapide des lots sans charger tous les détails d'un coup.
    run_html("""<script>
    (function(){
        const doc = parent.document;
        function syncLotHeaders() {
            const markers = doc.querySelectorAll('[data-lot-index]');
            const allExpanders = doc.querySelectorAll('[data-testid="stExpander"]');
            const lotButtons = Array.from(doc.querySelectorAll('button')).filter(function(btn) {
                const label = (btn.innerText || '').trim();
                return label.startsWith('› ') || label.startsWith('▼ ');
            });
            markers.forEach(function(marker, idx) {
                let color = '#22c55e';
                const status = marker.getAttribute('data-lot-status');
                if (status === 'not-profitable') color = '#ee1515';
                if (status === 'brocante') color = '#f97316';
                if (status === 'collection') color = '#3b4cca';
                if (status === 'trade') color = '#0891b2';
                if (status === 'storage') color = '#7c3aed';
                const target = lotButtons[idx] || allExpanders[idx + 1];
                if (!target) return;
                const isOpen = (target.innerText || '').trim().startsWith('▼ ');
                target.style.setProperty('background', isOpen ? '#f8fafc' : '#ffffff', 'important');
                target.style.setProperty('color', '#0f172a', 'important');
                target.style.setProperty('border-left', '8px solid ' + color, 'important');
                target.style.setProperty('border-radius', '8px', 'important');
                target.style.setProperty('border-top', '1px solid #e2e8f0', 'important');
                target.style.setProperty('border-right', '1px solid #e2e8f0', 'important');
                target.style.setProperty('border-bottom', '1px solid #e2e8f0', 'important');
                target.style.setProperty('justify-content', 'flex-start', 'important');
                target.style.setProperty('text-align', 'left', 'important');
                target.style.setProperty('align-items', 'center', 'important');
                target.style.setProperty('text-transform', 'none', 'important');
                target.style.setProperty('font-weight', '500', 'important');
                target.style.setProperty('font-size', '0.95rem', 'important');
                target.style.setProperty('min-height', '68px', 'important');
                target.style.setProperty('padding', '1rem 1.25rem', 'important');
                target.style.setProperty('box-shadow', '0 4px 12px rgba(15, 23, 42, 0.08)', 'important');
                target.style.setProperty('transform', 'none', 'important');
                target.style.setProperty('margin-bottom', '0.35rem', 'important');
                target.querySelectorAll('div, p, span').forEach(function(child) {
                    child.style.setProperty('text-align', 'left', 'important');
                    child.style.setProperty('justify-content', 'flex-start', 'important');
                    child.style.setProperty('text-transform', 'none', 'important');
                });
            });

            const addMarker = doc.querySelector('[data-add-card-form-marker]');
            if (addMarker) {
                const lotBlock = addMarker.closest('[data-testid="stVerticalBlock"]');
                const markerChild = addMarker.closest('[data-testid="stElementContainer"]');
                if (lotBlock && markerChild) {
                    const children = Array.from(lotBlock.children);
                    const markerIndex = children.indexOf(markerChild);
                    const markerId = addMarker.getAttribute('data-add-card-form-marker');
                    const endMarker = doc.querySelector('[data-add-card-form-end-marker="' + markerId + '"]');
                    const endChild = endMarker ? endMarker.closest('[data-testid="stElementContainer"]') : null;
                    const endIndex = endChild ? children.indexOf(endChild) : -1;
                    const formParts = endIndex > markerIndex
                        ? children.slice(markerIndex + 1, endIndex)
                        : children.slice(markerIndex + 1, markerIndex + 6);
                    const isMobile = doc.body.classList.contains('codex-mobile-mode') || parent.window.matchMedia('(max-width: 760px)').matches;
                    const stickyTop = isMobile ? 0 : 64;
                    let topOffset = stickyTop;
                    const formBg = isMobile ? '#d8e7ff' : '#bed3fa';
                    const overlap = isMobile ? 4 : 0;
                    let shield = doc.getElementById('codex-add-card-shield');
                    if (shield) shield.remove();
                    markerChild.style.setProperty('margin-bottom', '0', 'important');
                    formParts.forEach(function(part, partIndex) {
                        part.setAttribute('data-codex-add-sticky', '1');
                        part.style.setProperty('position', isMobile ? 'static' : 'sticky', 'important');
                        if (isMobile) {
                            part.style.removeProperty('top');
                            part.style.setProperty('z-index', '1', 'important');
                        } else {
                            part.style.setProperty('top', topOffset + 'px', 'important');
                            part.style.setProperty('z-index', String(7000 - partIndex), 'important');
                        }
                        part.style.setProperty('background', formBg, 'important');
                        part.style.setProperty('background-color', formBg, 'important');
                        part.style.setProperty('width', '100%', 'important');
                        part.style.setProperty('max-width', '100%', 'important');
                        part.style.setProperty('box-shadow', isMobile ? 'none' : ('0 -14px 0 ' + formBg + ', 0 14px 0 ' + formBg), 'important');
                        part.style.setProperty('padding', isMobile ? '0.12rem 0.35rem' : '0.62rem 1.05rem', 'important');
                        part.style.setProperty('margin', isMobile ? '0' : (partIndex === 0 || overlap === 0 ? '0' : '-' + overlap + 'px 0 0 0'), 'important');
                        part.style.setProperty('border-left', 'none', 'important');
                        part.style.setProperty('border-right', 'none', 'important');
                        part.style.setProperty('border-top', 'none', 'important');
                        part.style.setProperty('border-bottom', 'none', 'important');
                        part.style.setProperty('outline', 'none', 'important');
                        part.querySelectorAll('[data-testid="stVerticalBlock"], [data-testid="stHorizontalBlock"], [data-testid="stElementContainer"]').forEach(function(inner) {
                            inner.style.setProperty('background', formBg, 'important');
                            inner.style.setProperty('background-color', formBg, 'important');
                            inner.style.setProperty('gap', isMobile ? '0.04rem' : '0.85rem', 'important');
                            inner.style.setProperty('box-shadow', 'none', 'important');
                            inner.style.setProperty('border', 'none', 'important');
                        });
                        part.querySelectorAll('[data-testid="stHorizontalBlock"]').forEach(function(row) {
                            row.style.setProperty('gap', isMobile ? '0.14rem' : '1rem', 'important');
                            if (isMobile) row.style.setProperty('flex-wrap', 'wrap', 'important');
                        });
                        if (isMobile) {
                            part.querySelectorAll('[data-testid="column"]').forEach(function(col) {
                                col.style.setProperty('flex', '1 1 calc(50% - 0.12rem)', 'important');
                                col.style.setProperty('min-width', '0', 'important');
                                col.style.setProperty('width', 'calc(50% - 0.12rem)', 'important');
                            });
                            if (partIndex === 0) {
                                part.style.setProperty('padding-top', '0.18rem', 'important');
                                part.style.setProperty('padding-bottom', '0', 'important');
                            }
                        }
                        part.querySelectorAll('button').forEach(function(btn) {
                            btn.style.setProperty('width', '100%', 'important');
                            if (isMobile) {
                                btn.style.setProperty('min-height', '1.55rem', 'important');
                                btn.style.setProperty('padding', '0.12rem 0.35rem', 'important');
                                btn.style.setProperty('font-size', '0.68rem', 'important');
                                btn.style.setProperty('border-width', '1px', 'important');
                            }
                        });
                        part.querySelectorAll('input, [data-baseweb="select"]').forEach(function(input) {
                            if (isMobile) {
                                input.style.setProperty('min-height', '1.55rem', 'important');
                                input.style.setProperty('font-size', '0.68rem', 'important');
                                input.style.setProperty('padding', '0.08rem 0.3rem', 'important');
                                input.style.setProperty('border-width', '2px', 'important');
                            }
                        });
                        part.querySelectorAll('label, p, span').forEach(function(txt) {
                            if (isMobile) {
                                txt.style.setProperty('font-size', '0.62rem', 'important');
                                txt.style.setProperty('line-height', '0.95', 'important');
                                txt.style.setProperty('margin', '0', 'important');
                            }
                        });
                        if (part === formParts[0]) {
                            part.style.setProperty('border-top', 'none', 'important');
                            part.style.setProperty('border-radius', '18px 18px 0 0', 'important');
                            part.style.setProperty('padding-top', isMobile ? '0.18rem' : '1.25rem', 'important');
                            part.querySelectorAll('[data-testid="stVerticalBlock"], [data-testid="stHorizontalBlock"], [data-testid="stElementContainer"]').forEach(function(inner) {
                                inner.style.setProperty('border-radius', '16px 16px 0 0', 'important');
                            });
                        }
                        if (part === formParts[formParts.length - 1]) {
                            part.style.setProperty('border-bottom', 'none', 'important');
                            part.style.setProperty('border-radius', '0 0 18px 18px', 'important');
                            part.style.setProperty('padding-bottom', isMobile ? '0.2rem' : '1.25rem', 'important');
                            part.querySelectorAll('[data-testid="stVerticalBlock"], [data-testid="stHorizontalBlock"], [data-testid="stElementContainer"]').forEach(function(inner) {
                                inner.style.setProperty('border-radius', '0 0 16px 16px', 'important');
                            });
                        }
                        if (!isMobile) topOffset += Math.max(part.getBoundingClientRect().height - overlap, 1);
                    });
                }
            }
        }
        syncLotHeaders();
        [100, 250, 600, 1200, 2500, 5000, 9000].forEach(function(delay) {
            setTimeout(syncLotHeaders, delay);
        });
        const observer = new MutationObserver(function() {
            clearTimeout(window.codexLotStyleTimer);
            window.codexLotStyleTimer = setTimeout(syncLotHeaders, 150);
        });
        observer.observe(doc.body, {childList: true, subtree: true});
        const intervalId = setInterval(syncLotHeaders, 5000);
        setTimeout(function(){ clearInterval(intervalId); }, 120000);
    })();
    </script>""", height=0)

    # ── Tabs : Lot normal / Lot Brocante ──
    with st.expander("➕ Créer un nouveau lot", expanded=False):
        st.subheader("Nouveau lot")
        c1,c2,c3=st.columns(3)
        nm=c1.text_input("Nom du lot",placeholder="Ex: Lot EV 4.5",key="new_lot_name")
        pa=c2.number_input("Prix d'achat (€)",0.,99999.,0.,0.5,key="new_lot_price")
        va=c3.number_input("Déjà vendu (€)",0.,99999.,0.,0.5,key="new_lot_sold")

        # Options du lot
        opt1, opt2 = st.columns(2)
        is_brocante_new = opt1.checkbox("🎪 Lot Brocante", key="new_lot_brocante",
                                         help="Lot acheté en brocante / vide-grenier")
        is_collection_new = opt2.checkbox("🏠 Lot Collection", key="new_lot_collection",
                                           help="Une partie pour ta collection, une partie à vendre")

        valeur_totale_mixte = 0.
        if is_collection_new:
            st.info("💡 La valeur des cartes à vendre sera calculée automatiquement depuis leurs prix suggérés une fois ajoutées. Saisis juste la valeur totale du lot.")
            valeur_totale_mixte = st.number_input("Valeur totale du lot (€)", 0., 99999., 0., 1., key="new_lot_valeur_totale",
                                                   help="Valeur marchande totale de toutes les cartes du lot (vendues + collection)")

        if st.button("✨ Créer le lot", type="primary"):
            if not nm:
                st.error("Nom requis")
            else:
                cd=ld()
                nl={
                    "nom": nm,
                    "prix_achat": pa,
                    "cards": [], "ventes": [],
                    "created": datetime.now().isoformat(),
                }
                if is_brocante_new:
                    nl["is_brocante"] = True
                if is_collection_new and valeur_totale_mixte > 0:
                    nl["is_mixte"] = True
                    nl["prix_achat_reel"] = pa
                    nl["valeur_totale"] = valeur_totale_mixte
                if va > 0:
                    nl["ventes"].append({"date":datetime.now().isoformat(),"price":float(va),"card_name":"Vente initiale","is_lot_sale":True})
                cd["lots"].append(nl)
                sd(cd)
                badges = []
                if is_brocante_new: badges.append("🎪 Brocante")
                if is_collection_new: badges.append("🏠 Collection")
                st.success(f"Lot créé ! {' · '.join(badges)}" if badges else "Lot créé !")
                st.rerun()

    st.markdown("---")
    cd=ld()
    if not cd.get("lots"):
        st.info("Aucun lot")
    else:
        def lot_default_sort_key(item):
            ix, lot = item
            if is_trade_lot(lot) or is_storage_lot(lot):
                category = 3
            elif lot.get("is_brocante", False):
                category = 2
            elif lot.get("is_mixte", False):
                category = 1
            else:
                category = 0
            created = lot.get("created") or f"{ix:06d}"
            return (category, created, ix)

        lots_with_idx = sorted(
            [(i, lot) for i, lot in enumerate(cd["lots"]) if not is_collection_system_lot(lot)],
            key=lot_default_sort_key,
        )
        completed_lots = [
            lot.get("nom", f"Lot {i+1}")
            for i, lot in lots_with_idx
            if not is_trade_lot(lot)
            and not is_storage_lot(lot)
            and lot.get("cards")
            and lot_remaining_including_storage(cd.get("lots", []), lot) == 0
        ]
        if completed_lots:
            st.success("Lots entièrement vendus, stockage inclus : " + " · ".join(completed_lots) + ". Tu peux les archiver.")

        filter_defs = [
            ("Tous", lambda item: True),
            ("Brocantes", lambda item: item[1].get("is_brocante", False)),
            ("Mixtes", lambda item: item[1].get("is_mixte", False)),
            ("Non remboursés", lambda item: (not is_trade_lot(item[1])) and (not is_storage_lot(item[1])) and cp(item[1]) < 0),
            ("Remboursés", lambda item: (not is_trade_lot(item[1])) and (not is_storage_lot(item[1])) and cp(item[1]) >= 0),
            ("Classiques", lambda item: not item[1].get("is_brocante", False) and not item[1].get("is_mixte", False) and not is_trade_lot(item[1]) and not is_storage_lot(item[1])),
            ("Spécial", lambda item: is_trade_lot(item[1]) or is_storage_lot(item[1])),
        ]

        filter_counts = {name: sum(1 for item in lots_with_idx if predicate(item)) for name, predicate in filter_defs}
        filter_labels = [f"{name} ({filter_counts[name]})" for name, _ in filter_defs]
        selected_filter_label = st.radio(
            "Afficher",
            filter_labels,
            horizontal=True,
            label_visibility="collapsed",
            key="lots_filter_v2",
        )
        selected_filter = selected_filter_label.split(" (", 1)[0]
        selected_predicate = next(predicate for name, predicate in filter_defs if name == selected_filter)
        visible_lots = [item for item in lots_with_idx if selected_predicate(item)]

        if not visible_lots:
            st.info("Aucun lot dans cette catégorie.")

        for display_ix,(ix,lt) in enumerate(visible_lots):
            is_brocante = lt.get("is_brocante", False)
            is_collection = lt.get("is_mixte", False)
            is_trade = is_trade_lot(lt)
            is_storage = is_storage_lot(lt)

            rv=cr(lt)
            pf=cp(lt)
            rp=crp(lt)

            is_profitable = pf >= 0

            if is_storage:
                lot_status = "storage"
            elif is_trade:
                lot_status = "trade"
            elif is_brocante:
                lot_status = "brocante"
            elif is_collection:
                lot_status = "collection"
            elif is_profitable:
                lot_status = "profitable"
            else:
                lot_status = "not-profitable"

            st.session_state[f"lot_status_{ix}"] = lot_status
            color_dot = {"storage":"📈","trade":"🔄","brocante":"🟠","collection":"🔵","profitable":"🟢","not-profitable":"🔴"}.get(lot_status,"🟢")
            # Marker pour colorLotBorders - display_ix suit l'ordre des lots visibles apres filtre.
            st.markdown(f'<div data-lot-index="{ix}" data-display-index="{display_ix}" data-lot-status="{lot_status}" style="display:none"></div>', unsafe_allow_html=True)

            # Badge 🎉 si lot vient d'atteindre 100%
            just_reached_100 = rp >= 100 and is_profitable and not is_brocante and not is_trade
            badge_100 = " 🎉" if just_reached_100 else ""
            badge_mixte = " 🗂️" if lt.get("is_mixte") else ""
            expander_title = f"{color_dot} {'🎪 ' if is_brocante else ''}{lt['nom']} - {fp(lt.get('prix_achat',0))}{badge_mixte}{badge_100}"
            is_active_lot = st.session_state.get("active_lot_ix") == ix
            row_prefix = "▼" if is_active_lot else "›"
            if st.button(
                f"{row_prefix} {expander_title}",
                key=f"lot_row_{ix}",
                width="stretch",
                type="secondary",
            ):
                if is_active_lot:
                    st.session_state.pop("active_lot_ix", None)
                else:
                    st.session_state["active_lot_ix"] = ix
                st.rerun()

            if not is_active_lot:
                continue

            with st.container():

                if is_storage:
                    st.markdown('<b style="color:#7c3aed;font-size:1.2rem">📈 LOT STOCKAGE — Cartes mises de côté</b>', unsafe_allow_html=True)
                elif is_trade:
                    st.markdown('<b style="color:#0891b2;font-size:1.2rem">🔄 LOT TRADE — Cartes reçues par échange</b>', unsafe_allow_html=True)
                elif is_brocante:
                    st.markdown('<b style="color:#f97316;font-size:1.2rem">🎪 LOT BROCANTE</b>', unsafe_allow_html=True)
                elif just_reached_100:
                    st.markdown(f'''
                    <div style="background:linear-gradient(135deg,#22c55e,#16a34a);color:white;padding:1rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-size:1.1rem;font-weight:800;text-align:center;">
                        🎉 LOT REMBOURSÉ À {rp:.1f}% — BÉNÉFICE : {fp(pf)}
                    </div>
                    ''', unsafe_allow_html=True)
                else:
                    status_text = "✅ REMBOURSÉ" if is_profitable else "❌ NON REMBOURSÉ"
                    border_color = "#22c55e" if is_profitable else "#ee1515"
                    st.markdown(f'<b style="color:{border_color};font-size:1.2rem">{status_text}</b>',unsafe_allow_html=True)

                # Pour un lot mixte : recalculer le prix_achat effectif dynamiquement
                if lt.get("is_mixte") and lt.get("valeur_totale", 0) > 0:
                    valeur_vente_auto = lot_tracked_cote_value(lt)
                    pa_effectif_auto = (valeur_vente_auto / lt["valeur_totale"]) * lt.get("prix_achat_reel", lt.get("prix_achat", 0.))
                    # Mettre à jour prix_achat si différent
                    if abs(pa_effectif_auto - float(lt.get("prix_achat", 0.))) > 0.01 and pa_effectif_auto > 0:
                        cdd = ld()
                        cdd["lots"][ix]["prix_achat"] = pa_effectif_auto
                        cdd["lots"][ix]["valeur_vente"] = valeur_vente_auto
                        sd(cdd)
                        lt = cdd["lots"][ix]  # recharger le lot mis à jour
                        rv = cr(lt)
                        pf = cp(lt)  # recalculer le bénéfice correctement

                # Calculs corrects — pf recalculé après éventuelle mise à jour mixte
                pf = cp(lt)  # toujours recalculer ici avec le lt à jour
                total_qty = sum(c.get("quantity", 0) for c in lt.get("cards", []))
                stock_qty = sum(card_available_qty(c) for c in lt.get("cards", []))
                stock_val = sum(card_available_qty(c) * c.get("suggested_price", 0.) for c in lt.get("cards", []))
                trade_stock_val = 0. if is_trade else trade_stock_value_for_lot(cd.get("lots", []), ix)
                stock_val += trade_stock_val

                # Valeur estimée = stock actuel (suggested_price corrects) + CA réel
                ca_reel_lot = rv
                valeur_estimee_lot = stock_val + ca_reel_lot

                # % estimé si tout le stock est vendu
                pa = lt.get("prix_achat", 0.)
                rp_estime = ((rv + stock_val) / pa * 100) if pa > 0 else 100.
                rp_estime_color = "#22c55e" if rv + stock_val >= pa else "#ee1515"

                c1,c2,c3,c4,c5=st.columns(5)
                c1.metric("Stock", f"{stock_qty} · {fp(stock_val)}")
                if trade_stock_val > 0:
                    c1.caption(f"part Trade : {fp(trade_stock_val)}")
                c2.metric("Valeur estimée", fp(valeur_estimee_lot))
                c3.metric("CA", fp(rv))
                with c4:
                    rp_color = "#22c55e" if rv + stock_val >= pa else "#ee1515"
                    st.metric("%", f"{rp:.1f}%", delta=f"Si tout vendu : {rp_estime:.0f}%", delta_color="normal" if rv + stock_val >= pa else "inverse")
                    run_html(f'<script>setTimeout(()=>{{const d=parent.document.querySelectorAll(\'[data-testid="stMetricDelta"]\');if(d.length)d[d.length-1].style.backgroundColor="{rp_color}";}},100);</script>', height=0)
                c5.metric("Bénéfice", fp(pf))

                # Info lot mixte
                if lt.get("is_mixte"):
                    valeur_vente_aff = lt.get("valeur_vente", 0.)
                    valeur_totale_aff = lt.get("valeur_totale", 0.)
                    pa_reel_aff = lt.get("prix_achat_reel", lt.get("prix_achat", 0.))
                    pa_eff_aff = lt.get("prix_achat", 0.)
                    pct_vente = (valeur_vente_aff / valeur_totale_aff * 100) if valeur_totale_aff > 0 else 0
                    st.markdown(f"""
                    <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:0.5rem 1rem;margin-bottom:0.5rem;font-size:0.82rem;color:#166534;">
                      🗂️ <b>Lot mixte</b> — Prix réel payé : <b>{fp(pa_reel_aff)}</b> · 
                      Valeur à vendre : <b>{fp(valeur_vente_aff)}</b> / <b>{fp(valeur_totale_aff)}</b> ({pct_vente:.0f}%) · 
                      Coût attribué vente : <b>{fp(pa_eff_aff)}</b>
                      <span style="color:#86efac;font-size:0.75rem;"> ← mis à jour automatiquement</span>
                    </div>
                    """, unsafe_allow_html=True)

                st.markdown("---")

                # ── Formulaire ajout carte ──
                st.markdown(f'<div data-add-card-form-marker="{ix}"></div>', unsafe_allow_html=True)
                st.markdown("**➕ Ajouter une carte**")

                if f"form_ts_{ix}"not in st.session_state:
                    st.session_state[f"form_ts_{ix}"]=time.time()
                ts=st.session_state[f"form_ts_{ix}"]

                is_divers_lot = lt.get("is_divers", False)

                if is_divers_lot:
                    co1,co2,co3,co4,co5=st.columns(5)
                    nm=co1.text_input("Nom",key=f"n{ix}{ts}",placeholder="Dracaufeu")
                    nu=co2.text_input("Numéro",key=f"nu{ix}{ts}",placeholder="004")
                    qt_raw=co3.text_input("Qté",key=f"q{ix}{ts}",placeholder="1")
                    pa_divers_raw=co4.text_input("Prix achat (€)",key=f"pad{ix}{ts}",placeholder="0.00")
                    pi_raw=co5.text_input("Valeur actuelle (€)",key=f"p{ix}{ts}",placeholder="0.00")
                    try: pa_divers = float(pa_divers_raw.replace(",",".")) if pa_divers_raw.strip() else 0.
                    except: pa_divers = 0.
                else:
                    co1,co2,co3,co4=st.columns(4)
                    nm=co1.text_input("Nom",key=f"n{ix}{ts}",placeholder="Dracaufeu")
                    nu=co2.text_input("Numéro",key=f"nu{ix}{ts}",placeholder="004")
                    qt_raw=co3.text_input("Qté",key=f"q{ix}{ts}",placeholder="1")
                    pi_raw=co4.text_input("Prix (€)",key=f"p{ix}{ts}",placeholder="0.00")
                    pa_divers = 0.

                sn=""
                pa_broc=None

                # Conversion sécurisée
                try:
                    qt = int(qt_raw) if qt_raw.strip() else 1
                    qt = max(1, qt)
                except:
                    qt = 1
                try:
                    pi = float(pi_raw.replace(",",".")) if pi_raw.strip() else 0.
                except:
                    pi = 0.

                special_choices = ["Reverse", "1ère Éd", "Japonaise", "Collection", "Scellé", "Stamp", "Promo", "Master Ball", "Poké Ball"]
                if is_divers_lot:
                    special_choices = [tag for tag in special_choices if tag != "Collection"]
                    st.caption("Pour garder une carte en Collection, ajoute-la directement depuis le menu Collection.")

                special_options = st.multiselect(
                    "Spécial",
                    special_choices,
                    key=f"sp{ix}{ts}",
                    placeholder="Reverse, Collection, Stamp..."
                )
                rv_check = "Reverse" in special_options
                ed = "1ère Éd" in special_options
                is_jp = "Japonaise" in special_options
                collection_keep = (not is_divers_lot) and "Collection" in special_options
                special_tag = ", ".join([tag for tag in special_options if tag not in ("Reverse", "1ère Éd", "Japonaise", "Collection")])
                cn="NM"
                if st.button("Ajouter",key=f"ad{ix}",disabled=st.session_state.get("searching",False)):
                    st.session_state["searching"]=True
                    final_qt=qt
                    final_pi=pi
                    ok,mg=acm(ix,nm,sn,nu,final_qt,cn,final_pi,rv_check,ed,lang="ja" if is_jp else "fr",purchase_price=pa_divers if is_divers_lot else 0.,special_tag=special_tag,collection_keep=collection_keep)
                    st.session_state["searching"]=False
                    if ok:
                        st.session_state[f"form_ts_{ix}"]=time.time()
                        st.session_state[f"lot_expanded_{ix}"]=True
                        st.success(mg)
                        st.rerun()
                    else:
                        st.error(mg)
                
                st.markdown(f'<div data-add-card-form-end-marker="{ix}"></div>', unsafe_allow_html=True)
                st.markdown("---")
                render_card_choice_popups(ix, form_ts_key=f"form_ts_{ix}", run_html_func=run_html)
                if glob.glob(f"popup_{ix}_*.json"):
                    st.markdown("---")
                st.markdown("**📦 Cartes du lot**")
                
                # ── Séparer en stock / vendues (ordre d'ajout conservé) ──
                cards_all = lt.get("cards", [])
                lot_card_search = st.text_input(
                    "🔍 Rechercher dans ce lot",
                    placeholder="Nom de carte...",
                    key=f"lot_card_search_{ix}",
                )
                if lot_card_search:
                    cards_all = [
                        c for c in cards_all
                        if normalize_name(lot_card_search) in normalize_name(c.get("name", ""))
                    ]
                # Attacher l'index original à chaque carte pour éviter le bug de mélange
                cards_with_idx = [(i, c) for i, c in enumerate(lt.get("cards", [])) if c in cards_all]
                cards_collection_lot = [(i, c) for i, c in cards_with_idx if c.get("is_collection_keep") and not lt.get("is_divers")]
                cards_in_stock_lot = [(i, c) for i, c in cards_with_idx if not c.get("is_collection_keep") and card_available_qty(c) > 0]
                cards_stored_lot = [(i, c) for i, c in cards_with_idx if not c.get("is_collection_keep") and card_available_qty(c) <= 0 and int(c.get("stored_quantity", 0)) > 0]
                cards_sold_lot = [(i, c) for i, c in cards_with_idx if not c.get("is_collection_keep") and card_available_qty(c) <= 0 and int(c.get("stored_quantity", 0)) <= 0]
                show_all_cards = st.checkbox(
                    "Afficher toutes les cartes du lot",
                    key=f"show_all_cards_{ix}",
                    value=False,
                    help="Désactivé par défaut pour accélérer l'ajout quand le lot contient beaucoup de cartes."
                )
                if not show_all_cards:
                    stock_quick_limit = 24 if is_mobile_mode() else 48
                    secondary_quick_limit = 12 if is_mobile_mode() else 24
                    visible_stock_lot = cards_in_stock_lot[-stock_quick_limit:]
                    visible_sold_lot = cards_sold_lot[-secondary_quick_limit:]
                    visible_stored_lot = cards_stored_lot[-secondary_quick_limit:]
                    visible_collection_lot = cards_collection_lot[-secondary_quick_limit:]
                    hidden_cards_count = (
                        max(len(cards_in_stock_lot) - len(visible_stock_lot), 0)
                        + max(len(cards_sold_lot) - len(visible_sold_lot), 0)
                        + max(len(cards_stored_lot) - len(visible_stored_lot), 0)
                        + max(len(cards_collection_lot) - len(visible_collection_lot), 0)
                    )
                    if hidden_cards_count > 0:
                        st.caption(f"Affichage rapide : {hidden_cards_count} ancienne(s) carte(s) masquée(s). Coche la case pour tout afficher.")
                else:
                    visible_stock_lot = cards_in_stock_lot
                    visible_stored_lot = cards_stored_lot
                    visible_collection_lot = cards_collection_lot
                    visible_sold_lot = cards_sold_lot
                if "perf_count" in globals():
                    perf_count(
                        "cards_lots_rendered",
                        len(visible_stock_lot) + len(visible_stored_lot) + len(visible_collection_lot) + len(visible_sold_lot),
                    )
                
                def render_card_grid(card_list_with_idx, sold=False, collection=False):
                    if is_mobile_mode():
                        tiles = []
                        for real_cix, crd in card_list_with_idx:
                            stock = card_available_qty(crd)
                            name = html.escape(str(crd.get("name", "Carte")))
                            price = float(crd.get("suggested_price", 0.) or 0.)
                            img_url = crd.get("image_url", "")
                            if img_url:
                                src = html.escape(proxy_img(img_url), quote=True)
                                img_html = f'<img src="{src}" alt="{name}">'
                            else:
                                img_html = '<div class="mobile-card-placeholder">?</div>'
                            past_note_html = ""
                            if not sold and not collection:
                                past_notes = recent_sale_notes_for_card(crd.get("name", ""), crd.get("number", ""), limit=1)
                                if past_notes:
                                    past_note_html = f'<div class="mobile-card-meta" style="color:#0f766e;font-weight:800;">Dernière vente {past_notes[0]["price"]:.2f}€</div>'
                            stock_txt = "collection" if collection else ("vendue" if sold else f"{stock}/{int(crd.get('quantity', 0) or 0)}")
                            if crd.get("stored_quantity", 0):
                                stock_txt += f" · stock {int(crd.get('stored_quantity', 0))}"
                            meta = html.escape(f"{price:.2f}€ · {stock_txt}")
                            badges = card_status_badges(crd)
                            sold_cls = " sold" if sold else (" collection" if collection else "")
                            collection_style = ' style="border:2px solid #f59e0b;background:#fffbeb;"' if collection else ""
                            tiles.append(
                                f'<div class="mobile-card-tile{sold_cls}"{collection_style}>'
                                f'<div class="mobile-card-imgbox">{img_html}</div>'
                                f'{past_note_html}'
                                f'<div class="mobile-card-name">{name} {badges}</div>'
                                f'<div class="mobile-card-meta">{meta}</div>'
                                f'</div>'
                            )
                        st.markdown('<div class="mobile-card-grid">' + "".join(tiles) + '</div>', unsafe_allow_html=True)
                        return
                    COLS_PER_ROW = 5 if is_mobile_mode() else 8
                    for row_start in range(0, len(card_list_with_idx), COLS_PER_ROW):
                        cols = st.columns(COLS_PER_ROW)
                        for col_idx, (real_cix, crd) in enumerate(card_list_with_idx[row_start:row_start + COLS_PER_ROW]):
                            stock = card_available_qty(crd)

                            with cols[col_idx]:
                                # Image
                                img_url = crd.get("image_url","")
                                if img_url:
                                    if sold:
                                        st.markdown(f'<div style="opacity:0.35;filter:grayscale(100%)"><img src="{proxy_img(img_url)}" style="width:100%;border-radius:12px;border:3px solid #e2e8f0;"></div>', unsafe_allow_html=True)
                                    elif collection:
                                        st.markdown(f'<div style="background:#fffbeb;border:3px solid #f59e0b;border-radius:14px;padding:0.2rem;"><img src="{proxy_img(img_url)}" style="width:100%;border-radius:10px;"></div>', unsafe_allow_html=True)
                                    else:
                                        st.markdown(f'<img src="{proxy_img(img_url)}" style="width:100%;border-radius:12px;">', unsafe_allow_html=True)
                                        past_notes = recent_sale_notes_for_card(crd.get("name", ""), crd.get("number", ""), limit=1)
                                        if past_notes:
                                            st.markdown(f'<div style="font-size:0.78rem;font-weight:800;color:#0f766e;margin:0.15rem 0 0.05rem 0;">Dernière vente : {past_notes[0]["price"]:.2f}€</div>', unsafe_allow_html=True)
                                else:
                                    # Pas d'image — bouton upload
                                    st.markdown("🃏 *Pas d'image*")
                                    uploaded = st.file_uploader(
                                        "📷 Uploader",
                                        type=["jpg","jpeg","png","webp"],
                                        key=f"upload_{ix}_{real_cix}",
                                        label_visibility="collapsed"
                                    )
                                    if uploaded:
                                        # Sauvegarder dans card_images/
                                        img_dir = os.path.join(os.getcwd(), "card_images")
                                        os.makedirs(img_dir, exist_ok=True)
                                        card_id = crd.get("id","") or f"{ix}_{real_cix}"
                                        safe_id = card_id.replace("/","_").replace(" ","_")
                                        ext = uploaded.name.split(".")[-1]
                                        img_path = os.path.join(img_dir, f"{safe_id}.{ext}")
                                        with open(img_path, "wb") as f:
                                            f.write(uploaded.read())
                                        # Mettre à jour data.json
                                        cdd = ld()
                                        cdd["lots"][ix]["cards"][real_cix]["image_url"] = f"card_images/{safe_id}.{ext}"
                                        sd(cdd)
                                        st.success("✅ Photo ajoutée !")
                                        st.rerun()

                                # Nom + badges + stock sur une ligne
                                badges = card_status_badges(crd)
                                stock_txt = "🧾 Collection" if collection else ("✅" if sold else f"{stock}/{crd['quantity']}")
                                if crd.get("stored_quantity", 0):
                                    stock_txt += f" · 📈 {int(crd.get('stored_quantity', 0))}"
                                st.markdown(f'<div style="font-size:0.85rem;font-weight:700;margin:0.2rem 0;">{crd["name"]}{badges} <span style="color:#64748b;font-weight:500;">· {stock_txt}</span></div>', unsafe_allow_html=True)

                                # Prix : pour les cartes vendues, afficher le prix de vente réel
                                if sold and crd.get("sold_entries"):
                                    last_sale = crd["sold_entries"][-1]
                                    prix_reel = float(last_sale.get("price", 0)) / max(int(last_sale.get("quantity",1)), 1)
                                    st.markdown(f'<div style="font-size:0.9rem;font-weight:700;color:#64748b;">Vendu : <span style="color:#10b981;">{prix_reel:.2f}€</span></div>', unsafe_allow_html=True)
                                    # Mettre à jour silencieusement le suggested_price si différent (correction données corrompues)
                                    if abs(float(crd.get("suggested_price", 0)) - prix_reel) > 0.01:
                                        pass  # sera corrigé par le bouton global
                                else:
                                    # Prix modifiable - sauvegarde sur perte de focus (Enter)
                                    def save_price(ix=ix, real_cix=real_cix):
                                        cdd = ld()
                                        new_price = st.session_state[f"ep{ix}_{real_cix}"]
                                        old_price = cdd["lots"][ix]["cards"][real_cix].get("suggested_price", 0.)
                                        cdd["lots"][ix]["cards"][real_cix]["suggested_price"] = new_price
                                        if cdd["lots"][ix]["cards"][real_cix].get("is_collection_keep"):
                                            cdd["lots"][ix]["cards"][real_cix]["collection_current_value"] = new_price
                                        if new_price != old_price:
                                            cdd["lots"][ix]["cards"][real_cix].setdefault("price_history", []).append({
                                                "date": datetime.now().isoformat()[:10],
                                                "price": new_price
                                            })
                                        sd(cdd)

                                    st.number_input("Valeur actuelle (€)" if collection else "Prix (€)", 0., 9999., value=float(crd.get("suggested_price") or 0), step=0.5, key=f"ep{ix}_{real_cix}", on_change=save_price)

                                    # Historique prix mini
                                    ph = crd.get("price_history", [])
                                    if ph and len(ph) >= 2:
                                        diff = ph[-1]["price"] - ph[-2]["price"]
                                        col_h = "#22c55e" if diff > 0 else "#ee1515"
                                        st.markdown(f'<span style="color:{col_h};font-size:0.72rem;font-weight:700;">{"↑" if diff>0 else "↓"} {fp(abs(diff))}</span>', unsafe_allow_html=True)

                                if not sold and not collection:
                                    st.number_input(
                                        "Qté totale",
                                        min_value=int(crd.get("sold_quantity", 0)),
                                        max_value=9999,
                                        value=int(crd.get("quantity", 1)),
                                        step=1,
                                        key=f"qty_edit_{ix}_{real_cix}",
                                        on_change=update_card_quantity,
                                        args=(ix, real_cix),
                                    )
                                    if (not is_storage) and stock > 0:
                                        store_panel_key = f"show_store_{ix}_{real_cix}"
                                        if st.button("📈 Stocker", key=f"store_btn_{ix}_{real_cix}", width="stretch"):
                                            st.session_state[store_panel_key] = True

                                        if st.session_state.get(store_panel_key, False):
                                            transfer_qty = st.number_input(
                                                "Qté à stocker",
                                                min_value=1,
                                                max_value=int(stock),
                                                value=1,
                                                step=1,
                                                key=f"store_qty_{ix}_{real_cix}",
                                            )
                                            storage_cote = st.number_input(
                                                "Cote stockage (€)",
                                                min_value=0.0,
                                                max_value=99999.0,
                                                value=float(crd.get("suggested_price", 0.) or 0.),
                                                step=0.5,
                                                key=f"store_cote_{ix}_{real_cix}",
                                            )
                                            col_store_ok, col_store_cancel = st.columns(2)
                                            if col_store_ok.button("Valider", key=f"store_confirm_{ix}_{real_cix}", width="stretch"):
                                                ok, msg = transfer_card_to_storage(ix, real_cix, transfer_qty, storage_cote)
                                                if ok:
                                                    st.session_state[store_panel_key] = False
                                                    st.success(msg)
                                                    st.rerun()
                                                else:
                                                    st.error(msg)
                                            if col_store_cancel.button("Annuler", key=f"store_cancel_{ix}_{real_cix}", width="stretch"):
                                                st.session_state[store_panel_key] = False
                                                st.rerun()

                                # Checkboxes Reverse / 1ère Éd + bouton modifier image
                                def save_badges(ix=ix, real_cix=real_cix):
                                    cdd = ld()
                                    cdd["lots"][ix]["cards"][real_cix]["is_reverse"] = st.session_state.get(f"erv{ix}_{real_cix}", False)
                                    cdd["lots"][ix]["cards"][real_cix]["is_ed1"] = st.session_state.get(f"eed{ix}_{real_cix}", False)
                                    sd(cdd)

                                col_rv, col_ed, col_img = st.columns([2, 2, 1])
                                col_rv.checkbox("Reverse", value=crd.get("is_reverse", False), key=f"erv{ix}_{real_cix}", on_change=save_badges)
                                col_ed.checkbox("1ère Éd", value=crd.get("is_ed1", False), key=f"eed{ix}_{real_cix}", on_change=save_badges)
                                if col_img.button("🖼️", key=f"edit_img_{ix}_{real_cix}", help="Modifier l'image"):
                                    st.session_state[f"show_upload_{ix}_{real_cix}"] = True

                                if st.session_state.get(f"show_upload_{ix}_{real_cix}", False):
                                    uploaded = st.file_uploader(
                                        "Nouvelle image",
                                        type=["jpg","jpeg","png","webp"],
                                        key=f"reupload_{ix}_{real_cix}",
                                    )
                                    if uploaded:
                                        img_dir = os.path.join(os.getcwd(), "card_images")
                                        os.makedirs(img_dir, exist_ok=True)
                                        card_id = crd.get("id","") or f"{ix}_{real_cix}"
                                        safe_id = card_id.replace("/","_").replace(" ","_")
                                        ext = uploaded.name.split(".")[-1]
                                        img_path = os.path.join(img_dir, f"{safe_id}.{ext}")
                                        with open(img_path, "wb") as f:
                                            f.write(uploaded.read())
                                        cdd = ld()
                                        cdd["lots"][ix]["cards"][real_cix]["image_url"] = f"card_images/{safe_id}.{ext}"
                                        sd(cdd)
                                        st.session_state[f"show_upload_{ix}_{real_cix}"] = False
                                        st.rerun()

                                # Restaurer (cartes vendues)
                                if sold:
                                    if st.button("↩️ Restaurer", key=f"restore_card_{ix}_{real_cix}", width="stretch"):
                                        cdd = ld()
                                        card_data = cdd["lots"][ix]["cards"][real_cix]
                                        # Retirer la dernière vente
                                        if card_data.get("sold_entries"):
                                            last_entry = card_data["sold_entries"].pop()
                                            qty_restored = last_entry.get("quantity", 1)
                                            card_data["sold_quantity"] = max(0, card_data.get("sold_quantity", 0) - qty_restored)
                                            sale_id = last_entry.get("sale_id")
                                            if sale_id:
                                                for lot_restore in cdd.get("lots", []):
                                                    lot_restore["ventes"] = [
                                                        v for v in lot_restore.get("ventes", [])
                                                        if v.get("source_sale_id") != sale_id
                                                    ]
                                        else:
                                            card_data["sold_quantity"] = max(0, card_data.get("sold_quantity", 0) - 1)
                                        sd(cdd)
                                        st.success("↩️ Vente annulée !")
                                        st.rerun()

                                # Supprimer
                                if st.button("🗑️", key=f"dc{ix}_{real_cix}", width="stretch"):
                                    ok, er = dc(ix, real_cix)
                                    if ok:
                                        st.rerun()

                        st.markdown("---")
                
                if not cards_all:
                    st.info("Aucune carte dans ce lot")
                else:
                    # ── En stock ──
                    if visible_stock_lot:
                        st.markdown(f"**🟢 En stock ({len(cards_in_stock_lot)})**")
                        render_card_grid(visible_stock_lot, sold=False)

                    if visible_stored_lot:
                        st.markdown(f"**📈 En stockage ({len(cards_stored_lot)})**")
                        render_card_grid(visible_stored_lot, sold=False)

                    if visible_collection_lot:
                        st.markdown(f'<div style="margin-top:1.5rem;padding:1rem;background:#fffbeb;border-radius:12px;border:2px dashed #f59e0b;"><span style="font-weight:800;color:#92400e;font-size:0.9rem;">🧾 COLLECTION ({len(cards_collection_lot)})</span></div>', unsafe_allow_html=True)
                        render_card_grid(visible_collection_lot, sold=False, collection=True)
                    
                    # ── Vendues ──
                    if visible_sold_lot:
                        st.markdown(f'<div style="margin-top:1.5rem;padding:1rem;background:#f8fafc;border-radius:12px;border:2px dashed #cbd5e1;"><span style="font-weight:800;color:#64748b;font-size:0.9rem;">✅ VENDUES ({len(cards_sold_lot)})</span></div>', unsafe_allow_html=True)
                        render_card_grid(visible_sold_lot, sold=True)
                
                # Actions lot
                st.markdown("### Actions")

                # ── Bouton correction des prix corrompus ──
                nb_correctable = sum(
                    1 for c in lt.get("cards", [])
                    if c.get("sold_entries") and c.get("sold_quantity", 0) >= c.get("quantity", 1)
                    and c.get("sold_entries")
                    and abs(float(c.get("suggested_price", 0)) - float(c["sold_entries"][-1].get("price", 0)) / max(int(c["sold_entries"][-1].get("quantity", 1)), 1)) > 0.01
                )
                if nb_correctable > 0:
                    st.warning(f"⚠️ {nb_correctable} carte(s) ont un prix suggéré qui ne correspond pas à leur prix de vente réel (données possiblement corrompues par un ancien bug).")
                    if st.button(f"🔄 Corriger les prix ({nb_correctable} cartes)", key=f"fix_prices_{ix}", type="primary"):
                        cdd = ld()
                        nb_fixed = 0
                        for ci, card in enumerate(cdd["lots"][ix]["cards"]):
                            if card.get("sold_entries") and card.get("sold_quantity", 0) >= card.get("quantity", 1):
                                last = card["sold_entries"][-1]
                                prix_reel = float(last.get("price", 0)) / max(int(last.get("quantity", 1)), 1)
                                if abs(float(card.get("suggested_price", 0)) - prix_reel) > 0.01:
                                    cdd["lots"][ix]["cards"][ci]["suggested_price"] = prix_reel
                                    cdd["lots"][ix]["cards"][ci]["suggested_price_at_sale"] = prix_reel
                                    nb_fixed += 1
                        sd(cdd)
                        st.success(f"✅ {nb_fixed} prix corrigés !")
                        st.rerun()

                # Renommage (déclenché par clic sur ✏️ dans le titre)
                if is_trade or is_storage:
                    st.caption("Nom réservé au système.")
                elif st.session_state.get(f"renaming_{ix}", False):
                    new_name = st.text_input("Nouveau nom", value=lt['nom'], key=f"rename_input_{ix}")
                    col_ok, col_cancel = st.columns(2)
                    if col_ok.button("✅ Valider", key=f"rename_ok_{ix}"):
                        cdd = ld()
                        cdd["lots"][ix]["nom"] = new_name
                        sd(cdd)
                        st.session_state[f"renaming_{ix}"] = False
                        st.rerun()
                    if col_cancel.button("❌ Annuler", key=f"rename_cancel_{ix}"):
                        st.session_state[f"renaming_{ix}"] = False
                else:
                    if st.button("✏️", key=f"rename_{ix}", help="Renommer ce lot"):
                        st.session_state[f"renaming_{ix}"] = True
                
                st.markdown("---")
                st.markdown("**Actions**")
                if is_trade:
                    st.info("Le lot Trade est permanent : il sert de coffre central pour les cartes reçues par échange.")
                elif is_storage:
                    st.info("Le lot Stockage est permanent : il sert à mettre de côté les cartes que tu veux garder.")
                else:
                    col_a, col_b = st.columns(2)

                    if col_a.button(f"📦 Archiver", key=f"arch_{ix}", width="stretch"):
                        st.session_state[f"confirm_arch_{ix}"] = True

                    if col_b.button(f"🗑️ Supprimer", key=f"dl_{ix}", type="secondary", width="stretch"):
                        st.session_state[f"cd_{ix}"] = True

                if (not is_trade) and st.session_state.get(f"confirm_arch_{ix}", False):
                    st.warning("⚠️ Archiver ce lot ?")
                    ca1, ca2 = st.columns(2)
                    if ca1.button("✅ Oui", key=f"arch_yes_{ix}"):
                        archive_file = "lots_archives.json"
                        archives = []
                        if os.path.exists(archive_file):
                            with open(archive_file, "r", encoding="utf-8") as f:
                                archives = json.load(f)
                        lot_to_archive = cd["lots"][ix].copy()
                        lot_to_archive["archived_date"] = datetime.now().isoformat()
                        archives.append(lot_to_archive)
                        safe_write_json(archive_file, archives, indent=2)
                        cd["lots"].pop(ix)
                        sd(cd)
                        st.session_state[f"confirm_arch_{ix}"] = False
                        st.rerun()
                    if ca2.button("❌ Non", key=f"arch_no_{ix}"):
                        st.session_state[f"confirm_arch_{ix}"] = False

                if (not is_trade) and st.session_state.get(f"cd_{ix}", False):
                    st.warning(f"⚠️ Supprimer définitivement '{lt['nom']}' ? Cette action est irréversible.")
                    cy, cn_btn = st.columns(2)
                    if cy.button("✅ Oui, supprimer", key=f"y_{ix}", type="primary"):
                        cd["lots"].pop(ix)
                        sd(cd)
                        st.session_state[f"cd_{ix}"] = False
                        st.rerun()
                    if cn_btn.button("❌ Non", key=f"n_{ix}"):
                        st.session_state[f"cd_{ix}"] = False

                st.markdown("---")
                if st.button("Fermer ce lot", key=f"close_lot_bottom_{ix}", width="stretch"):
                    st.session_state.pop("active_lot_ix", None)
                    st.rerun()
            
            st.markdown('</div>', unsafe_allow_html=True)




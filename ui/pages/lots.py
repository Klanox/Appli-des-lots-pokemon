"""Lots page renderer for Pokestock.

This module contains the existing Lots page body. It receives app.py globals
as context to preserve behavior while moving the large page out of app.py.
"""

import base64
import html
import json
import os
import re

from core.brocante import lot_reimbursement
from services.custom_card_image_service import register_custom_card_image, resolve_custom_card_image
from ui.badges import status_badge
from ui.lot_image_upload_bridge import render_lot_image_upload_bridge
from ui.mobile_scan import render_assisted_scan


def render_lots_page(context):
    globals().update(context)
    def lot_card_order_key(item):
        original_index, card = item
        try:
            sequence = int(card.get("added_sequence", 0) or 0)
        except (TypeError, ValueError):
            sequence = 0
        return (sequence, original_index)

    def compact_lot_reimbursement_html(lot, lot_index):
        gauge = lot_reimbursement(lot, lot_index)
        if not gauge["available"]:
            return (
                f'<div class="lot-reimbursement-row lot-reimbursement-unavailable" data-lot-gauge-for="{lot_index}">'
                "Coût non renseigné — jauge indisponible"
                "</div>"
            )
        pct = max(float(gauge.get("pct") or 0), 0.0)
        clamped = min(pct, 100.0)
        slots = 14
        filled = int(round(clamped / 100 * slots))
        bar = "█" * filled + "░" * (slots - filled)
        if pct >= 100:
            label = f"{bar} 100 % · Remboursé"
        else:
            recovered = fp(gauge.get("recovered", 0.0))
            label = f"{bar} {pct:.0f} % · {recovered} récupérés"
        return (
            f'<div class="lot-reimbursement-row" data-lot-gauge-for="{lot_index}" aria-label="Jauge de remboursement du lot">'
            f'<span class="lot-reimbursement-bar">{html.escape(label)}</span>'
            "</div>"
        )

    def lot_detail_reimbursement_html(lot, lot_index):
        gauge = lot_reimbursement(lot, lot_index)
        if not gauge["available"]:
            return (
                '<div class="lot-detail-reimbursement-row lot-reimbursement-unavailable">'
                "Coût non renseigné — jauge indisponible"
                "</div>"
            )
        pct = max(float(gauge.get("pct") or 0), 0.0)
        clamped = min(pct, 100.0)
        recovered = fp(gauge.get("recovered", 0.0))
        remaining = fp(gauge.get("remaining", 0.0))
        label = "Remboursé" if pct >= 100 else f"{pct:.0f} % remboursé · {recovered} récupérés · reste {remaining}"
        return (
            '<div class="lot-detail-reimbursement-row">'
            '<div class="lot-detail-reimbursement-track">'
            f'<span style="width:{clamped:.1f}%"></span>'
            "</div>"
            f'<strong>{html.escape(label)}</strong>'
            "</div>"
        )

    def editable_lot_purchase_price(lot, lot_index):
        price_field = "prix_achat_reel" if lot.get("is_mixte") else "prix_achat"
        current_price = float(lot.get(price_field, lot.get("prix_achat", 0.)) or 0.0)
        edit_key = f"edit_lot_purchase_price_{lot_index}"
        input_key = f"lot_purchase_price_input_{lot_index}"

        if not st.session_state.get(edit_key, False):
            label = "Prix d'achat réel" if lot.get("is_mixte") else "Prix d'achat"
            display_col, action_col = st.columns([4, 1])
            display_col.markdown(
                f"""
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;
                            padding:0.75rem 0.9rem;margin:0.35rem 0 0.7rem 0;">
                  <span style="color:#64748b;font-size:0.82rem;font-weight:800;">{label}</span><br>
                  <span style="color:#0f172a;font-size:1.2rem;font-weight:950;">{fp(current_price)}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if action_col.button("Modifier", key=f"edit_lot_purchase_price_btn_{lot_index}", width="stretch"):
                st.session_state[edit_key] = True
                st.session_state[input_key] = current_price
                st.rerun()
            return

        edit_col, save_col, cancel_col = st.columns([3, 1, 1])
        new_price = edit_col.number_input(
            "Prix d'achat (€)",
            min_value=0.0,
            max_value=999999.0,
            value=float(st.session_state.get(input_key, current_price)),
            step=0.5,
            key=input_key,
        )
        if save_col.button("Enregistrer", key=f"save_lot_purchase_price_{lot_index}", width="stretch", type="primary"):
            cdd = ld()
            if 0 <= lot_index < len(cdd.get("lots", [])):
                cdd["lots"][lot_index][price_field] = float(new_price)
                if not cdd["lots"][lot_index].get("is_mixte"):
                    cdd["lots"][lot_index]["prix_achat"] = float(new_price)
                sd(cdd)
            st.session_state[edit_key] = False
            st.rerun()
        if cancel_col.button("Annuler", key=f"cancel_lot_purchase_price_{lot_index}", width="stretch"):
            st.session_state[edit_key] = False
            st.rerun()

    def card_is_collection_status(card):
        return bool(
            card.get("is_collection_keep")
            or card.get("is_collection")
            or str(card.get("trade_transfer_destination", "")).strip().lower() == "collection"
        )

    def card_is_storage_status(card, lot=None):
        return bool(
            int(card.get("stored_quantity", 0) or 0) > 0
            or str(card.get("trade_transfer_destination", "")).strip().lower() in ("stockage", "storage")
            or (lot is not None and is_storage_lot(lot))
        )

    def card_is_sold_status(card):
        try:
            total_qty = int(card.get("quantity", 0) or 0)
            sold_or_exchanged = int(card.get("sold_quantity", 0) or 0) + int(card.get("exchange_out_quantity", 0) or 0)
        except (TypeError, ValueError):
            return False
        return total_qty > 0 and sold_or_exchanged >= total_qty

    def card_lot_display_status(card, lot=None):
        if card_is_collection_status(card):
            return "collection"
        if card_is_sold_status(card):
            return "sold"
        if card_is_storage_status(card, lot):
            return "stored"
        return "stock"

    def lot_card_status_badges(card, display_status):
        badges = card_status_badges(card, include_storage=False)
        badge_text = badges.upper()
        if display_status == "collection" and "COLLECTION" not in badge_text:
            badges += " " + status_badge("Collection")
        elif display_status == "stored" and "STOCKAGE" not in badge_text:
            badges += " " + status_badge("Stockage")
        return badges

    st.markdown(
        render_page_header("Gestion des lots", "Inventaire, ajout de cartes et suivi par lot", "📦"),
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <style>
        .lot-reimbursement-row {
            margin: 0.45rem 0 0 0;
            padding: 0.38rem 0.55rem;
            max-width: 100%;
            color: #14532d;
            font-size: 0.82rem;
            font-weight: 800;
            line-height: 1.25;
            word-break: break-word;
            background: rgba(34,197,94,0.08);
            border: 1px solid rgba(34,197,94,0.18);
            border-radius: 8px;
        }
        .lot-reimbursement-unavailable {
            color: #64748b;
            font-weight: 700;
            background: rgba(148,163,184,0.10);
            border-color: rgba(148,163,184,0.22);
        }
        .lot-reimbursement-bar {
            display: inline-block;
            max-width: 100%;
            white-space: normal;
        }
        .lot-detail-reimbursement-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            align-items: center;
            gap: 0.75rem;
            margin: 0.65rem 0 1rem;
            padding: 0.75rem 0.85rem;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            box-shadow: 0 8px 20px rgba(15,23,42,0.06);
        }
        .lot-detail-reimbursement-track {
            height: 0.72rem;
            overflow: hidden;
            border-radius: 999px;
            background: #e2e8f0;
        }
        .lot-detail-reimbursement-track span {
            display: block;
            height: 100%;
            border-radius: inherit;
            background: linear-gradient(90deg, #7c3aed, #22c55e);
        }
        [class*="st-key-lot_cards_grid_"][data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: wrap !important;
            gap: 0.46rem !important;
            align-items: flex-start !important;
            width: 100% !important;
            max-width: 100% !important;
            overflow-x: hidden !important;
        }
        [class*="st-key-lot_cards_grid_"] > [data-testid="stLayoutWrapper"] {
            flex: 0 0 calc((100% - 2.3rem) / 6) !important;
            max-width: calc((100% - 2.3rem) / 6) !important;
            min-width: 0 !important;
            box-sizing: border-box !important;
        }
        [class*="st-key-lot_card_item_"] {
            width: 100% !important;
            max-width: 100% !important;
            min-width: 0 !important;
            box-sizing: border-box !important;
            border-radius: 14px !important;
            border: 1px solid transparent !important;
            padding: 0.35rem !important;
        }
        [class*="st-key-lot_card_item_"][class*="_scope-stored_"] {
            background: #f0f9ff !important;
            border-color: #7dd3fc !important;
            box-shadow: 0 8px 20px rgba(3,105,161,0.08) !important;
        }
        [class*="st-key-lot_card_item_"][class*="_scope-collection_"] {
            background: #fffbeb !important;
            border-color: #f59e0b !important;
            box-shadow: 0 8px 20px rgba(146,64,14,0.08) !important;
        }
        [class*="st-key-lot_card_item_"] img {
            width: 100% !important;
            max-width: 100% !important;
            height: auto !important;
        }
        .ps-lot-name-row {
            display: flex;
            align-items: center;
            gap: 0.22rem;
            min-width: 0;
            margin: 0.2rem 0;
            font-size: 0.85rem;
            font-weight: 700;
            line-height: 1.25;
        }
        .ps-lot-name-text {
            min-width: 0;
            overflow-wrap: anywhere;
        }
        .ps-lot-inline-image-btn {
            flex: 0 0 auto;
            appearance: none;
            border: 1px solid rgba(124,58,237,0.18);
            background: rgba(124,58,237,0.06);
            color: #4c1d95;
            border-radius: 8px;
            width: 1.55rem;
            height: 1.55rem;
            line-height: 1;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0;
            margin: 0;
            cursor: pointer;
            font-size: 0.8rem;
        }
        .ps-lot-inline-image-btn:hover {
            background: rgba(124,58,237,0.12);
            border-color: rgba(124,58,237,0.32);
        }
        @media (max-width: 768px) {
            .lot-reimbursement-row {
                margin-left: 0.2rem;
                font-size: 0.78rem;
            }
            .lot-detail-reimbursement-row {
                grid-template-columns: 1fr;
                gap: 0.45rem;
            }
            [class*="st-key-lot_cards_grid_"][data-testid="stHorizontalBlock"] {
                gap: 0.3rem !important;
            }
            [class*="st-key-lot_cards_grid_"] > [data-testid="stLayoutWrapper"] {
                flex: 0 0 calc((100% - 0.3rem) / 2) !important;
                max-width: calc((100% - 0.3rem) / 2) !important;
                min-width: 0 !important;
            }
            .ps-lot-name-row {
                gap: 0.16rem;
                font-size: 0.78rem;
            }
            .ps-lot-inline-image-btn {
                width: 1.42rem;
                height: 1.42rem;
                font-size: 0.72rem;
            }
        }
        @media (max-width: 340px) {
            [class*="st-key-lot_cards_grid_"][data-testid="stHorizontalBlock"] {
                gap: 0.22rem !important;
            }
            [class*="st-key-lot_cards_grid_"] > [data-testid="stLayoutWrapper"] {
                flex-basis: calc((100% - 0.22rem) / 2) !important;
                max-width: calc((100% - 0.22rem) / 2) !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    cd = ld()  # Charger les données en premier
    lots_snapshot = json.dumps(cd.get("lots", []), ensure_ascii=False, sort_keys=True)
    ensure_system_lots(cd)
    migrate_open_trade_cards(cd)
    if json.dumps(cd.get("lots", []), ensure_ascii=False, sort_keys=True) != lots_snapshot:
        sd(cd)
        # No need to reload - sd() updates the cache

    # Bordures des en-têtes de lots. Le script ne déplace aucun nœud Streamlit :
    # reparent un élément React peut provoquer des NotFoundError removeChild au rerun.
    run_html("""<script>
    (function(){
        const win = parent.window || window;
        const doc = parent.document;
        const runId = Date.now() + '-' + Math.random().toString(36).slice(2);
        win.__pokestockLotHeaderStyleRun = runId;
        function syncLotHeaders() {
            if (win.__pokestockLotHeaderStyleRun !== runId) return;
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
                target.style.setProperty('white-space', 'normal', 'important');
                target.style.setProperty('align-items', 'flex-start', 'important');
                target.style.setProperty('flex-direction', 'column', 'important');
                target.style.setProperty('gap', '0.2rem', 'important');
                target.style.setProperty('text-transform', 'none', 'important');
                target.style.setProperty('font-weight', '700', 'important');
                target.style.setProperty('font-size', '0.95rem', 'important');
                target.style.setProperty('min-height', '86px', 'important');
                target.style.setProperty('padding', '1rem 1.25rem', 'important');
                target.style.setProperty('box-shadow', '0 4px 12px rgba(15, 23, 42, 0.08)', 'important');
                target.style.setProperty('transform', 'none', 'important');
                target.style.setProperty('margin-bottom', '0.35rem', 'important');
                target.setAttribute('data-pokestock-lot-header', '1');
                target.setAttribute('data-pokestock-lot-status', status || 'default');
            });
        }
        syncLotHeaders();
        [100, 250, 600, 1200, 2500].forEach(function(delay) {
            setTimeout(syncLotHeaders, delay);
        });
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
            st.markdown(compact_lot_reimbursement_html(lt, ix), unsafe_allow_html=True)

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

                st.markdown(lot_detail_reimbursement_html(lt, ix), unsafe_allow_html=True)

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

                editable_lot_purchase_price(lt, ix)

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

                with st.expander("Scan bêta", expanded=False):
                    def on_lot_scan_confirm(candidate):
                        card_dict = candidate["card"]
                        ok, mg = acm(
                            ix,
                            card_dict.get("name", ""),
                            str(candidate.get("set_name") or ""),
                            str(card_dict.get("localId") or card_dict.get("number") or candidate.get("number") or ""),
                            qt,
                            cn,
                            pi,
                            rv_check,
                            ed,
                            lang="ja" if candidate.get("language") == "ja" else "fr",
                            purchase_price=pa_divers if is_divers_lot else 0.,
                            special_tag=special_tag,
                            collection_keep=collection_keep,
                        )
                        if ok:
                            st.session_state[f"form_ts_{ix}"] = time.time()
                            st.success(mg)
                        else:
                            st.error(mg)

                    render_assisted_scan(
                        key_prefix=f"lot_scan_{ix}_{ts}",
                        cards_index=st.session_state.get("cards_index", {}) or {},
                        normalize_name_func=normalize_name,
                        proxy_img_func=proxy_img,
                        on_confirm=on_lot_scan_confirm,
                        button_label="Confirmer",
                    )
                 
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
                cards_with_idx = sorted(
                    [(i, c) for i, c in enumerate(lt.get("cards", [])) if c in cards_all],
                    key=lot_card_order_key,
                    reverse=True,
                )
                cards_collection_lot = [
                    (i, c)
                    for i, c in cards_with_idx
                    if card_lot_display_status(c, lt) == "collection"
                ]
                cards_stored_lot = [
                    (i, c)
                    for i, c in cards_with_idx
                    if card_lot_display_status(c, lt) == "stored"
                ]
                cards_in_stock_lot = [
                    (i, c)
                    for i, c in cards_with_idx
                    if card_lot_display_status(c, lt) == "stock"
                ]
                cards_sold_lot = [
                    (i, c)
                    for i, c in cards_with_idx
                    if card_lot_display_status(c, lt) == "sold"
                ]
                rendered_lot_card_count = 0

                def build_recent_sale_note_index():
                    def note_keys(name, num):
                        normalized = normalize_name(name)
                        raw_num = str(num or "").strip()
                        if not normalized:
                            return []
                        if not raw_num:
                            return [(normalized, "")]
                        return list({
                            (normalized, raw_num),
                            (normalized, raw_num.zfill(3)),
                            (normalized, raw_num.lstrip("0")),
                        })

                    notes_by_key = {}
                    archives = []
                    try:
                        if os.path.exists("lots_archives.json"):
                            with open("lots_archives.json", "r", encoding="utf-8") as f:
                                archives = json.load(f)
                    except Exception:
                        archives = []

                    for source_lot in cd.get("lots", []) + archives:
                        for source_card in source_lot.get("cards", []):
                            sale_entries = source_card.get("sold_entries", [])
                            if not sale_entries:
                                continue
                            keys = note_keys(source_card.get("name", ""), source_card.get("number", ""))
                            keys.append((normalize_name(source_card.get("name", "")), ""))
                            keys = [key for key in set(keys) if key[0]]
                            for sale in sale_entries:
                                q = max(int(sale.get("quantity", 1) or 1), 1)
                                price = float(sale.get("price", 0) or 0) / q
                                if price <= 0:
                                    continue
                                note = {
                                    "date": str(sale.get("date", ""))[:10],
                                    "price": price,
                                    "lot": source_lot.get("nom", ""),
                                }
                                for key in keys:
                                    notes_by_key.setdefault(key, []).append(note)

                    latest_by_key = {}
                    for key, notes in notes_by_key.items():
                        notes.sort(key=lambda x: x.get("date", ""), reverse=True)
                        latest_by_key[key] = notes[0]
                    return latest_by_key

                recent_sale_note_index = build_recent_sale_note_index()

                def recent_sale_note_for_render(card):
                    normalized = normalize_name(card.get("name", ""))
                    raw_num = str(card.get("number", "") or "").strip()
                    if not normalized:
                        return None
                    keys = []
                    if raw_num:
                        keys.extend([
                            (normalized, raw_num),
                            (normalized, raw_num.zfill(3)),
                            (normalized, raw_num.lstrip("0")),
                        ])
                    else:
                        keys.append((normalized, ""))
                    for key in keys:
                        if key in recent_sale_note_index:
                            return recent_sale_note_index[key]
                    return None

                def save_direct_uploaded_card_image(real_cix, filename, mime, data_url):
                    if real_cix < 0 or real_cix >= len(lt.get("cards", [])):
                        return False, "Carte introuvable."
                    raw_data_url = str(data_url or "")
                    if "," not in raw_data_url:
                        return False, "Image illisible."
                    _, encoded = raw_data_url.split(",", 1)
                    try:
                        payload = base64.b64decode(encoded, validate=True)
                    except Exception:
                        return False, "Image illisible."
                    if not payload:
                        return False, "Image vide."

                    ext = os.path.splitext(str(filename or "").split("?", 1)[0])[1].lower()
                    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                        ext = {
                            "image/jpeg": ".jpg",
                            "image/png": ".png",
                            "image/webp": ".webp",
                        }.get(str(mime or "").lower(), ".jpg")

                    img_dir = os.path.join(os.getcwd(), "card_images")
                    os.makedirs(img_dir, exist_ok=True)
                    upload_card = lt["cards"][real_cix]
                    card_id = upload_card.get("id", "") or upload_card.get("card_uid", "") or f"{ix}_{real_cix}"
                    safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(card_id)).strip("_") or f"{ix}_{real_cix}"
                    image_ref = f"card_images/{safe_id}{ext}"
                    img_path = os.path.join(os.getcwd(), image_ref)
                    with open(img_path, "wb") as f:
                        f.write(payload)

                    cdd = ld()
                    if ix >= len(cdd.get("lots", [])) or real_cix >= len(cdd["lots"][ix].get("cards", [])):
                        return False, "Carte introuvable."
                    cdd["lots"][ix]["cards"][real_cix]["image_url"] = image_ref
                    register_custom_card_image(cdd["lots"][ix]["cards"][real_cix], image_ref, source="lots_upload")
                    sd(cdd)
                    return True, "Image mise à jour."
                
                def render_card_grid(card_list_with_idx, sold=False, collection=False, storage=False, grid_scope="active", row_index_offset=0):
                    safe_lot_key = str(lt.get("lot_uid") or ix).replace(" ", "_").replace("/", "_")
                    safe_scope = str(grid_scope or ("sold" if sold else "collection" if collection else "active")).replace(" ", "_").replace("/", "_")

                    def lot_image_markup(img_url, img_url_en="", *, img_style="", wrapper_style=""):
                        candidates = []
                        for raw_url in (img_url, img_url_en):
                            raw_url = str(raw_url or "").strip()
                            if not raw_url or raw_url == "__placeholder__":
                                continue
                            if (raw_url.startswith(("card_images/", "card_images\\")) or os.path.exists(raw_url)) and not os.path.exists(raw_url):
                                continue
                            if raw_url and raw_url not in candidates:
                                candidates.append(raw_url)
                        placeholder = (
                            '<div class="mobile-card-placeholder" '
                            'style="display:flex;align-items:center;justify-content:center;aspect-ratio:0.72;'
                            'width:100%;border-radius:12px;background:#f8fafc;border:2px dashed #cbd5e1;'
                            'color:#64748b;font-weight:800;text-align:center;padding:0.4rem;">'
                            'Image indisponible</div>'
                        )
                        if not candidates:
                            return placeholder
                        proxied = [html.escape(proxy_img(url), quote=True) for url in candidates]
                        src = proxied[0]
                        fallback_chain = proxied[1:]
                        fallback_js = ""
                        if fallback_chain:
                            js_array = "[" + ",".join("'" + url.replace("'", "\\'") + "'" for url in fallback_chain) + "]"
                            fallback_js = (
                                "this.dataset.fallbackIndex=this.dataset.fallbackIndex||0;"
                                f"const f={js_array};"
                                "const i=parseInt(this.dataset.fallbackIndex,10);"
                                "if(i<f.length){this.dataset.fallbackIndex=i+1;this.src=f[i];return;}"
                            )
                        onerror = html.escape(
                            fallback_js + "this.style.display='none';this.parentElement.innerHTML='" + placeholder.replace("\\", "\\\\").replace("'", "\\'") + "';",
                            quote=True,
                        )
                        return (
                            f'<div style="{wrapper_style}">'
                            f'<img src="{src}" onerror="{onerror}" loading="lazy" decoding="async" style="{img_style}">'
                            f'</div>'
                        )

                    COLS_PER_ROW = 6
                    for row_start in range(0, len(card_list_with_idx), COLS_PER_ROW):
                        with st.container(
                            key=f"lot_cards_grid_{safe_lot_key}_{safe_scope}_{row_index_offset + row_start}",
                            horizontal=True,
                            gap="small",
                        ):
                            for col_idx, (real_cix, crd) in enumerate(card_list_with_idx[row_start:row_start + COLS_PER_ROW]):
                                stock = card_available_qty(crd)
                                display_status = card_lot_display_status(crd, lt)
                                is_collection_card = display_status == "collection"
                                is_storage_card = display_status == "stored"
                                is_sold_card = display_status == "sold"
                                card_key_part = str(crd.get("card_uid") or real_cix).replace(" ", "_").replace("/", "_")
                                widget_key = f"{ix}_{safe_scope}_{real_cix}"

                                with st.container(key=f"lot_card_item_{safe_lot_key}_scope-{safe_scope}_{card_key_part}_{col_idx}"):
                                    # Image + informations statiques.
                                    img_url = crd.get("image_url","") or resolve_custom_card_image(crd)
                                    img_url_en = crd.get("image_url_en", "")
                                    static_parts = []
                                    if img_url or img_url_en:
                                        if is_sold_card:
                                            static_parts.append(lot_image_markup(img_url, img_url_en, img_style="width:100%;border-radius:12px;border:3px solid #e2e8f0;", wrapper_style="opacity:0.35;filter:grayscale(100%)"))
                                        elif is_collection_card:
                                            static_parts.append(lot_image_markup(img_url, img_url_en, img_style="width:100%;border-radius:10px;", wrapper_style="background:#fffbeb;border:3px solid #f59e0b;border-radius:14px;padding:0.2rem;"))
                                        elif is_storage_card:
                                            static_parts.append(lot_image_markup(img_url, img_url_en, img_style="width:100%;border-radius:10px;", wrapper_style="background:#f0f9ff;border:3px solid #7dd3fc;border-radius:14px;padding:0.2rem;"))
                                        else:
                                            static_parts.append(lot_image_markup(img_url, img_url_en, img_style="width:100%;border-radius:12px;"))
                                            past_note = recent_sale_note_for_render(crd)
                                            if past_note:
                                                static_parts.append(f'<div style="font-size:0.78rem;font-weight:800;color:#0f766e;margin:0.15rem 0 0.05rem 0;">Dernière vente : {past_note["price"]:.2f}€</div>')
                                    else:
                                        static_parts.append(
                                            '<div class="ps-lot-image-placeholder">'
                                            '<strong>Image indisponible</strong>'
                                            '<span>Ajoute une photo si tu veux illustrer cette carte.</span>'
                                            '</div>'
                                        )

                                    badges = lot_card_status_badges(crd, display_status)
                                    stock_txt = "🧾 Collection" if is_collection_card else ("📈 Stockage" if is_storage_card else ("✅" if is_sold_card else f"{stock}/{crd['quantity']}"))
                                    image_button = (
                                        '<button type="button" class="ps-lot-inline-image-btn" '
                                        f'data-lot-idx="{ix}" data-card-idx="{real_cix}" '
                                        'title="Modifier l’image" aria-label="Modifier l’image">🖼️</button>'
                                    )
                                    static_parts.append(
                                        '<div class="ps-lot-name-row">'
                                        f'<span class="ps-lot-name-text">{html.escape(str(crd.get("name", "")))}{badges} '
                                        f'<span style="color:#64748b;font-weight:500;">· {stock_txt}</span></span>'
                                        f'{image_button}'
                                        '</div>'
                                    )
                                    ph = crd.get("price_history", [])
                                    if is_sold_card and crd.get("sold_entries"):
                                        last_sale = crd["sold_entries"][-1]
                                        prix_reel = float(last_sale.get("price", 0)) / max(int(last_sale.get("quantity", 1)), 1)
                                        static_parts.append(f'<div style="font-size:0.82rem;font-weight:700;color:#64748b;">Vendu : <span style="color:#10b981;">{prix_reel:.2f}€</span></div>')
                                    else:
                                        price_label = "Valeur" if is_collection_card else "Prix"
                                        static_parts.append(f'<div style="font-size:0.82rem;font-weight:700;color:#64748b;">{price_label} : <span style="color:#0f172a;">{fp(float(crd.get("suggested_price") or 0))}</span></div>')
                                        if ph and len(ph) >= 2:
                                            diff = ph[-1]["price"] - ph[-2]["price"]
                                            col_h = "#22c55e" if diff > 0 else "#ee1515"
                                            static_parts.append(f'<span style="color:{col_h};font-size:0.72rem;font-weight:700;">{"↑" if diff>0 else "↓"} {fp(abs(diff))}</span>')
                                    st.markdown("".join(static_parts), unsafe_allow_html=True)

                                    edit_state_key = "lot_card_editing_key"
                                    edit_key = f"{safe_lot_key}:{safe_scope}:{real_cix}:{card_key_part}"
                                    is_editing = st.session_state.get(edit_state_key) == edit_key
                                    if not is_editing:
                                        if st.button("Modifier", key=f"edit_card_{widget_key}", width="stretch"):
                                            st.session_state[edit_state_key] = edit_key
                                            st.rerun()
                                        continue

                                    if st.button("Fermer", key=f"close_edit_card_{widget_key}", width="stretch"):
                                        st.session_state.pop(f"show_store_{widget_key}", None)
                                        st.session_state.pop(f"show_trade_move_{widget_key}", None)
                                        st.session_state[edit_state_key] = None
                                        st.rerun()

                                    if not is_sold_card:
                                        def save_price(ix=ix, real_cix=real_cix, widget_key=widget_key):
                                            cdd = ld()
                                            new_price = st.session_state[f"ep{widget_key}"]
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

                                        st.number_input("Valeur actuelle (€)" if is_collection_card else "Prix (€)", 0., 9999., value=float(crd.get("suggested_price") or 0), step=0.5, key=f"ep{widget_key}", on_change=save_price)

                                    if not is_sold_card and not is_collection_card:
                                        min_total_quantity = max(
                                            1,
                                            int(crd.get("sold_quantity", 0) or 0)
                                            + int(crd.get("exchange_out_quantity", 0) or 0)
                                            + int(crd.get("stored_quantity", 0) or 0),
                                        )
                                        current_total_quantity = max(
                                            int(crd.get("quantity", 1) or 1),
                                            min_total_quantity,
                                        )
                                        st.markdown(
                                            "<div style='font-size:0.8rem;font-weight:800;color:#475569;margin-top:0.35rem;'>Qté totale</div>",
                                            unsafe_allow_html=True,
                                        )
                                        qty_cols = st.columns([0.8, 1.2, 0.8])
                                        qty_cols[0].button(
                                            "−",
                                            key=f"qty_dec_{widget_key}",
                                            help="Diminuer la quantité totale",
                                            disabled=current_total_quantity <= min_total_quantity,
                                            on_click=adjust_card_quantity,
                                            args=(ix, real_cix, -1),
                                            width="stretch",
                                        )
                                        qty_cols[1].markdown(
                                            f"<div style='height:2.35rem;display:flex;align-items:center;justify-content:center;font-weight:900;color:#0f172a;border:1px solid #e2e8f0;border-radius:10px;background:#ffffff;'>{current_total_quantity}</div>",
                                            unsafe_allow_html=True,
                                        )
                                        qty_cols[2].button(
                                            "＋",
                                            key=f"qty_inc_{widget_key}",
                                            help="Augmenter la quantité totale",
                                            disabled=current_total_quantity >= 9999,
                                            on_click=adjust_card_quantity,
                                            args=(ix, real_cix, 1),
                                            width="stretch",
                                        )
                                        if is_trade and stock > 0:
                                            move_panel_key = f"show_trade_move_{widget_key}"
                                            if st.button("Déplacer vers", key=f"trade_move_btn_{widget_key}", width="stretch"):
                                                st.session_state[move_panel_key] = True

                                            if st.session_state.get(move_panel_key, False):
                                                move_qty = 1
                                                if int(stock) > 1:
                                                    move_qty = st.number_input(
                                                        "Qté à déplacer",
                                                        min_value=1,
                                                        max_value=int(stock),
                                                        value=1,
                                                        step=1,
                                                        key=f"trade_move_qty_{widget_key}",
                                                    )
                                                col_move_collection, col_move_storage = st.columns(2)
                                                if col_move_collection.button("Collection", key=f"trade_move_collection_{widget_key}", width="stretch"):
                                                    ok, msg = transfer_trade_card_to_system_lot(ix, real_cix, "collection", move_qty)
                                                    if ok:
                                                        st.session_state[move_panel_key] = False
                                                        st.success(msg)
                                                        st.rerun()
                                                    else:
                                                        st.error(msg)
                                                if col_move_storage.button("Stockage", key=f"trade_move_storage_{widget_key}", width="stretch"):
                                                    ok, msg = transfer_trade_card_to_system_lot(ix, real_cix, "stockage", move_qty)
                                                    if ok:
                                                        st.session_state[move_panel_key] = False
                                                        st.success(msg)
                                                        st.rerun()
                                                    else:
                                                        st.error(msg)
                                                if st.button("Annuler", key=f"trade_move_cancel_{widget_key}", width="stretch"):
                                                    st.session_state[move_panel_key] = False
                                                    st.rerun()

                                        elif (not is_storage) and stock > 0:
                                            store_panel_key = f"show_store_{widget_key}"
                                            if st.button("📈 Stocker", key=f"store_btn_{widget_key}", width="stretch"):
                                                st.session_state[store_panel_key] = True

                                            if st.session_state.get(store_panel_key, False):
                                                transfer_qty = st.number_input(
                                                    "Qté à stocker",
                                                    min_value=1,
                                                    max_value=int(stock),
                                                    value=1,
                                                    step=1,
                                                    key=f"store_qty_{widget_key}",
                                                )
                                                storage_cote = st.number_input(
                                                    "Cote stockage (€)",
                                                    min_value=0.0,
                                                    max_value=99999.0,
                                                    value=float(crd.get("suggested_price", 0.) or 0.),
                                                    step=0.5,
                                                    key=f"store_cote_{widget_key}",
                                                )
                                                col_store_ok, col_store_cancel = st.columns(2)
                                                if col_store_ok.button("Valider", key=f"store_confirm_{widget_key}", width="stretch"):
                                                    ok, msg = transfer_card_to_storage(ix, real_cix, transfer_qty, storage_cote)
                                                    if ok:
                                                        st.session_state[store_panel_key] = False
                                                        st.success(msg)
                                                        st.rerun()
                                                    else:
                                                        st.error(msg)
                                                if col_store_cancel.button("Annuler", key=f"store_cancel_{widget_key}", width="stretch"):
                                                    st.session_state[store_panel_key] = False
                                                    st.rerun()

                                    # Restaurer (cartes vendues)
                                    if sold:
                                        if st.button("↩️ Restaurer", key=f"restore_card_{widget_key}", width="stretch"):
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
                                    if st.button("🗑️", key=f"dc{widget_key}", width="stretch"):
                                        ok, er = dc(ix, real_cix)
                                        if ok:
                                            st.rerun()

                        st.markdown("---")

                def lot_card_image_url(card):
                    candidates = []
                    for raw_url in (card.get("image_url", "") or resolve_custom_card_image(card), card.get("image_url_en", "")):
                        raw_url = str(raw_url or "").strip()
                        if not raw_url or raw_url == "__placeholder__":
                            continue
                        if (raw_url.startswith(("card_images/", "card_images\\")) or os.path.exists(raw_url)) and not os.path.exists(raw_url):
                            continue
                        if raw_url not in candidates:
                            candidates.append(raw_url)
                    return proxy_img(candidates[0]) if candidates else ""

                def lot_virtual_card_payload(real_cix, card, grid_scope):
                    display_status = card_lot_display_status(card, lt)
                    is_collection_card = display_status == "collection"
                    is_storage_card = display_status == "stored"
                    is_sold_card = display_status == "sold"
                    stock = card_available_qty(card)
                    badges = lot_card_status_badges(card, display_status)
                    stock_txt = "Collection" if is_collection_card else ("Stockage" if is_storage_card else ("Vendu" if is_sold_card else f"{stock}/{card.get('quantity', 0)}"))
                    sold_label = ""
                    if is_sold_card and card.get("sold_entries"):
                        last_sale = card["sold_entries"][-1]
                        prix_reel = float(last_sale.get("price", 0)) / max(int(last_sale.get("quantity", 1)), 1)
                        sold_label = f"Vendu : {prix_reel:.2f}€"
                    price_delta_label = ""
                    ph = card.get("price_history", [])
                    if ph and len(ph) >= 2:
                        diff = float(ph[-1].get("price", 0) or 0) - float(ph[-2].get("price", 0) or 0)
                        arrow = "↑" if diff > 0 else "↓"
                        price_delta_label = f"{arrow} {fp(abs(diff))}"
                    sale_note = ""
                    if not is_sold_card and not is_collection_card and not is_storage_card:
                        past_note = recent_sale_note_for_render(card)
                        if past_note:
                            sale_note = f"Dernière vente : {past_note['price']:.2f}€"
                    return {
                        "lot_idx": ix,
                        "card_idx": real_cix,
                        "card_uid": card.get("card_uid") or "",
                        "card_key": f"{ix}_{grid_scope}_{real_cix}",
                        "section": grid_scope,
                        "status": display_status,
                        "sold": is_sold_card,
                        "collection": is_collection_card,
                        "stored": is_storage_card,
                        "name": card.get("name", "Carte"),
                        "badges_html": badges,
                        "stock_text": stock_txt,
                        "sale_note": sale_note,
                        "sold_label": sold_label,
                        "price_delta_label": price_delta_label,
                        "image_url": lot_card_image_url(card),
                        "price": float(card.get("suggested_price") or 0),
                        "quantity": int(card.get("quantity", 1) or 1),
                        "sold_quantity": int(card.get("sold_quantity", 0) or 0),
                        "stored_quantity": int(card.get("stored_quantity", 0) or 0),
                        "exchange_out_quantity": int(card.get("exchange_out_quantity", 0) or 0),
                        "available": int(stock),
                        "trade_move": bool(is_trade and stock > 0 and not is_sold_card and not is_collection_card),
                        "can_store": bool((not is_storage) and stock > 0 and not is_sold_card and not is_collection_card and not is_trade),
                    }

                def build_lot_virtual_sections():
                    return [
                        {
                            "key": "stock",
                            "title": f"🟢 En stock ({len(cards_in_stock_lot)})",
                            "cards": [lot_virtual_card_payload(real_cix, card, "stock") for real_cix, card in cards_in_stock_lot],
                        },
                        {
                            "key": "stored",
                            "title": f"🔵 En stockage ({len(cards_stored_lot)})",
                            "cards": [lot_virtual_card_payload(real_cix, card, "stored") for real_cix, card in cards_stored_lot],
                        },
                        {
                            "key": "collection",
                            "title": f"🟡 Collection ({len(cards_collection_lot)})",
                            "boxed": True,
                            "cards": [lot_virtual_card_payload(real_cix, card, "collection") for real_cix, card in cards_collection_lot],
                        },
                        {
                            "key": "sold",
                            "title": f"✅ VENDUES ({len(cards_sold_lot)})",
                            "boxed": True,
                            "cards": [lot_virtual_card_payload(real_cix, card, "sold") for real_cix, card in cards_sold_lot],
                        },
                    ]

                def render_lot_sections_fallback():
                    nonlocal rendered_lot_card_count
                    rendered_lot_card_count += (
                        len(cards_in_stock_lot)
                        + len(cards_stored_lot)
                        + len(cards_collection_lot)
                        + len(cards_sold_lot)
                    )
                    if cards_in_stock_lot:
                        st.markdown(f"**🟢 En stock ({len(cards_in_stock_lot)})**")
                        render_card_grid(cards_in_stock_lot, sold=False, grid_scope="stock")
                    if cards_stored_lot:
                        st.markdown(f"**🔵 En stockage ({len(cards_stored_lot)})**")
                        render_card_grid(cards_stored_lot, sold=False, storage=True, grid_scope="stored")
                    if cards_collection_lot:
                        st.markdown(f'<div style="margin-top:1.5rem;padding:1rem;background:#fffbeb;border-radius:12px;border:2px dashed #f59e0b;"><span style="font-weight:800;color:#92400e;font-size:0.9rem;">🟡 Collection ({len(cards_collection_lot)})</span></div>', unsafe_allow_html=True)
                        render_card_grid(cards_collection_lot, sold=False, collection=True, grid_scope="collection")
                    if cards_sold_lot:
                        st.markdown(f'<div style="margin-top:1.5rem;padding:1rem;background:#f8fafc;border-radius:12px;border:2px dashed #cbd5e1;"><span style="font-weight:800;color:#64748b;font-size:0.9rem;">✅ VENDUES ({len(cards_sold_lot)})</span></div>', unsafe_allow_html=True)
                        render_card_grid(cards_sold_lot, sold=True, grid_scope="sold")

                def restore_sold_card(real_cix):
                    cdd = ld()
                    if ix >= len(cdd.get("lots", [])) or real_cix >= len(cdd["lots"][ix].get("cards", [])):
                        return False, "Carte introuvable."
                    card_data = cdd["lots"][ix]["cards"][real_cix]
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
                    return True, "Vente annulée."

                def process_lot_virtual_action(action):
                    try:
                        action_lot_idx = int(action.get("lot_idx"))
                        real_cix = int(action.get("card_idx"))
                    except Exception:
                        return
                    if action_lot_idx != ix:
                        return
                    action_type = str(action.get("type") or "")
                    if action_type == "set_price":
                        cdd = ld()
                        if ix < len(cdd.get("lots", [])) and real_cix < len(cdd["lots"][ix].get("cards", [])):
                            card_data = cdd["lots"][ix]["cards"][real_cix]
                            new_price = float(action.get("value") or 0)
                            old_price = float(card_data.get("suggested_price", 0) or 0)
                            card_data["suggested_price"] = new_price
                            if card_data.get("is_collection_keep"):
                                card_data["collection_current_value"] = new_price
                            if new_price != old_price:
                                card_data.setdefault("price_history", []).append({
                                    "date": datetime.now().isoformat()[:10],
                                    "price": new_price,
                                })
                            sd(cdd)
                            st.rerun()
                    elif action_type == "set_quantity":
                        cdd = ld()
                        if ix < len(cdd.get("lots", [])) and real_cix < len(cdd["lots"][ix].get("cards", [])):
                            card_data = cdd["lots"][ix]["cards"][real_cix]
                            new_q = int(action.get("value") or card_data.get("quantity", 1))
                            min_q = (
                                int(card_data.get("sold_quantity", 0) or 0)
                                + int(card_data.get("exchange_out_quantity", 0) or 0)
                                + int(card_data.get("stored_quantity", 0) or 0)
                            )
                            card_data["quantity"] = max(new_q, min_q)
                            sd(cdd)
                            st.rerun()
                    elif action_type == "delete":
                        ok, _ = dc(ix, real_cix)
                        if ok:
                            st.rerun()
                    elif action_type == "restore":
                        ok, msg = restore_sold_card(real_cix)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                    elif action_type == "store":
                        ok, msg = transfer_card_to_storage(
                            ix,
                            real_cix,
                            int(action.get("quantity") or 1),
                            float(action.get("storage_cote") or 0),
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                    elif action_type == "trade_transfer":
                        ok, msg = transfer_trade_card_to_system_lot(
                            ix,
                            real_cix,
                            str(action.get("destination") or "stockage"),
                            int(action.get("quantity") or 1),
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

                st.session_state.pop("lot_virtual_pending_action", None)
                
                if not cards_all:
                    st.info("Aucune carte dans ce lot")
                else:
                    render_lot_sections_fallback()
                    upload_event = render_lot_image_upload_bridge(
                        key=str(lt.get("lot_uid") or ix).replace(" ", "_").replace("/", "_")
                    )
                    if isinstance(upload_event, dict):
                        upload_id = str(upload_event.get("id") or "")
                        if upload_id and st.session_state.get("lot_direct_image_upload_last_id") != upload_id:
                            st.session_state["lot_direct_image_upload_last_id"] = upload_id
                            try:
                                event_lot_idx = int(upload_event.get("lot_idx"))
                                event_card_idx = int(upload_event.get("card_idx"))
                            except Exception:
                                event_lot_idx = -1
                                event_card_idx = -1
                            if event_lot_idx == ix:
                                ok, msg = save_direct_uploaded_card_image(
                                    event_card_idx,
                                    upload_event.get("filename", ""),
                                    upload_event.get("mime", ""),
                                    upload_event.get("data_url", ""),
                                )
                                if ok:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)

                    if "perf_count" in globals():
                        perf_count("cards_lots_rendered", rendered_lot_card_count)
                
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
            

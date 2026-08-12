"""History page renderer for Pokestock.

This module contains the existing Streamlit UI rendering for the Historique page.
It keeps the same filters, sorting, progressive display and calculations.
"""

import json
import os
from html import escape
from datetime import datetime

import streamlit as st
from core.trade_economics import trade_sale_stat_rows


def _money(value):
    try:
        return f"{float(value or 0):.2f}€"
    except (TypeError, ValueError):
        return "0.00€"


def _trade_card_label(card):
    name = card.get("name") or card.get("card_name") or "Carte"
    number = card.get("number") or card.get("card_number") or ""
    set_name = card.get("set") or card.get("card_set") or ""
    details = " · ".join(part for part in (set_name, f"#{number}" if number else "") if part)
    return f"{name} · {details}" if details else name


def _trade_card_image(card):
    return card.get("image_url") or card.get("image_url_en") or card.get("image_url_ja") or card.get("image") or ""


def _trade_card_match_key(card):
    name = str(card.get("name") or card.get("card_name") or "").strip().lower()
    number = str(card.get("number") or card.get("card_number") or "").strip().lower()
    set_id = str(card.get("set_id") or card.get("card_set_id") or "").strip().lower()
    exchange_id = str(card.get("exchange_id") or card.get("source_exchange_id") or "").strip().lower()
    return name, number, set_id, exchange_id


def _build_trade_image_lookup(cd_hist):
    lookup = {}
    for lot in cd_hist.get("lots", []) or []:
        if not lot.get("is_trade"):
            continue
        for card in lot.get("cards", []) or []:
            img = _trade_card_image(card)
            if not img:
                continue
            name, number, set_id, exchange_id = _trade_card_match_key(card)
            for key in (
                (name, number, set_id, exchange_id),
                (name, number, "", exchange_id),
                (name, number, set_id, ""),
                (name, number, "", ""),
            ):
                if key[0] and key[1]:
                    lookup.setdefault(key, img)
    return lookup


def _resolve_trade_card_image(card, image_lookup=None):
    img = _trade_card_image(card)
    if img or not image_lookup:
        return img
    name, number, set_id, exchange_id = _trade_card_match_key(card)
    for key in (
        (name, number, set_id, exchange_id),
        (name, number, "", exchange_id),
        (name, number, set_id, ""),
        (name, number, "", ""),
    ):
        if key in image_lookup:
            return image_lookup[key]
    return ""


def _trade_card_value(card):
    try:
        return float(card.get("reference_value", card.get("value", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _trade_cards_total(cards):
    return sum(_trade_card_value(card) * int(card.get("quantity") or 1) for card in cards or [])


def _collect_exchange_out_entries(cd_hist):
    by_exchange = {}
    for lot_idx, lot in enumerate(cd_hist.get("lots", []) or []):
        for card in lot.get("cards", []) or []:
            for entry in card.get("exchange_out_entries", []) or []:
                exchange_id = entry.get("exchange_id") or ""
                if not exchange_id:
                    continue
                copied = dict(entry)
                copied.setdefault("name", entry.get("card_name", card.get("name", "")))
                copied.setdefault("number", entry.get("card_number", card.get("number", "")))
                copied.setdefault("set", entry.get("card_set", card.get("set", "")))
                copied.setdefault("quantity", entry.get("quantity", 1))
                copied.setdefault("reference_value", entry.get("reference_value", card.get("suggested_price", 0)))
                copied.setdefault("image_url", entry.get("image_url", card.get("image_url", "")))
                copied.setdefault("image_url_en", entry.get("image_url_en", card.get("image_url_en", "")))
                copied.setdefault("lot_idx", entry.get("lot_idx", lot_idx))
                copied.setdefault("lot_name", entry.get("lot_name", lot.get("nom", "")))
                by_exchange.setdefault(exchange_id, []).append(copied)
    return by_exchange


def _render_trade_card_list(cards, *, proxy_img_func):
    if not cards:
        st.caption("Aucune carte détaillée disponible.")
        return
    for card in cards:
        img_col, info_col = st.columns([1, 5])
        with img_col:
            img = _trade_card_image(card)
            if img:
                st.markdown(
                    f'<img loading="lazy" src="{proxy_img_func(img)}" style="width:54px;border-radius:6px;box-shadow:0 2px 6px rgba(0,0,0,0.12);">',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div style="width:54px;height:74px;background:#f8fafc;border:1px dashed #cbd5e1;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#64748b;font-size:0.7rem;font-weight:700;text-align:center;">Image<br>indispo.</div>',
                    unsafe_allow_html=True,
                )
        with info_col:
            qty = int(card.get("quantity") or 1)
            value = card.get("reference_value", card.get("value", 0))
            lot_name = card.get("lot_name", "")
            lot_line = f" · {lot_name}" if lot_name else ""
            st.markdown(f"**{_trade_card_label(card)}**")
            st.caption(f"Quantité : x{qty} · valeur échange : {_money(value)}{lot_line}")


def _render_trade_side(cards, *, proxy_img_func, image_lookup, tone, total_label):
    if not cards:
        st.caption("Aucune carte détaillée disponible.")
        return

    color = "#dc2626" if tone == "given" else "#15803d"
    soft_bg = "#fff7f7" if tone == "given" else "#f6fff9"
    border = "#fee2e2" if tone == "given" else "#dcfce7"
    rows = []
    for card in cards:
        img = _resolve_trade_card_image(card, image_lookup)
        if img:
            img_html = (
                f'<img loading="lazy" src="{escape(proxy_img_func(img))}" '
                'style="width:48px;height:66px;object-fit:cover;border-radius:7px;'
                'box-shadow:0 2px 7px rgba(15,23,42,0.16);">'
            )
        else:
            img_html = (
                '<div style="width:48px;height:66px;background:#f8fafc;border:1px dashed #cbd5e1;'
                'border-radius:7px;display:flex;align-items:center;justify-content:center;'
                'color:#64748b;font-size:0.66rem;font-weight:800;text-align:center;">Image<br>indispo.</div>'
            )
        qty = int(card.get("quantity") or 1)
        name = escape(str(card.get("name") or card.get("card_name") or "Carte"))
        number = str(card.get("number") or card.get("card_number") or "")
        set_name = str(card.get("set") or card.get("card_set") or "")
        detail = " · ".join(escape(part) for part in (set_name, f"#{number}" if number else "") if part)
        lot_name = escape(str(card.get("lot_name") or ""))
        lot_html = f'<div style="font-size:0.76rem;color:#64748b;margin-top:2px;">{lot_name}</div>' if lot_name else ""
        rows.append(
            f"""
            <div style="display:grid;grid-template-columns:56px 1fr auto;gap:0.7rem;align-items:center;
                        padding:0.65rem 0;border-bottom:1px solid #eef2f7;">
              <div>{img_html}</div>
              <div>
                <div style="font-weight:800;color:#0f172a;font-size:0.92rem;">{name}</div>
                <div style="font-size:0.78rem;color:#64748b;margin-top:2px;">{detail or "—"} · Quantité : x{qty}</div>
                {lot_html}
              </div>
              <div style="font-weight:900;color:{color};white-space:nowrap;">{_money(_trade_card_value(card))}</div>
            </div>
            """
        )

    st.markdown(
        f"""
        <div style="border:1px solid {border};border-radius:10px;background:#fff;overflow:hidden;">
          <div style="padding:0.75rem 0.85rem;">
            {''.join(rows)}
          </div>
          <div style="background:{soft_bg};padding:0.75rem 0.85rem;text-align:right;
                      font-weight:900;color:{color};">
            {escape(total_label)} : {_money(_trade_cards_total(cards))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_trade_cash_panel(cash_paid, cash_received, diff):
    diff_value = float(diff or 0)
    diff_color = "#15803d" if diff_value >= 0 else "#dc2626"
    diff_bg = "#f0fdf4" if diff_value >= 0 else "#fff7f7"
    st.markdown(
        f"""
        <div style="display:flex;flex-direction:column;gap:0.7rem;align-items:stretch;">
          <div style="border:1px solid #fee2e2;background:#fff7f7;border-radius:10px;padding:0.8rem;text-align:center;">
            <div style="font-size:0.72rem;color:#64748b;font-weight:900;text-transform:uppercase;">Cash payé</div>
            <div style="font-size:1.05rem;color:#0f172a;font-weight:900;margin-top:0.2rem;">{_money(cash_paid)}</div>
          </div>
          <div style="border:1px solid #dcfce7;background:#f6fff9;border-radius:10px;padding:0.8rem;text-align:center;">
            <div style="font-size:0.72rem;color:#64748b;font-weight:900;text-transform:uppercase;">Cash reçu</div>
            <div style="font-size:1.05rem;color:#0f172a;font-weight:900;margin-top:0.2rem;">{_money(cash_received)}</div>
          </div>
          <div style="display:flex;justify-content:center;padding:0.25rem 0;">
            <div style="width:72px;height:72px;border-radius:999px;border:1px solid #ddd6fe;background:#f5f3ff;
                        display:flex;align-items:center;justify-content:center;color:#7c3aed;font-size:2.1rem;font-weight:900;">
              ⇄
            </div>
          </div>
          <div style="border:1px solid #e2e8f0;background:{diff_bg};border-radius:10px;padding:0.8rem;text-align:center;">
            <div style="font-size:0.72rem;color:#64748b;font-weight:900;text-transform:uppercase;">Différence de valeur</div>
            <div style="font-size:1.1rem;color:{diff_color};font-weight:950;margin-top:0.2rem;">{_money(diff_value)}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_trade_history(cd_hist, *, proxy_img_func):
    trades = cd_hist.get("trade_history", []) or []
    exchange_out_by_id = _collect_exchange_out_entries(cd_hist)
    if not trades and not exchange_out_by_id:
        return

    trades_by_id = {trade.get("exchange_id"): trade for trade in trades if trade.get("exchange_id")}
    for exchange_id, given_cards in exchange_out_by_id.items():
        if exchange_id not in trades_by_id:
            trades.append({
                "exchange_id": exchange_id,
                "date": given_cards[0].get("date", "") if given_cards else "",
                "given_cards": given_cards,
                "received_cards": [],
            })
            trades_by_id[exchange_id] = trades[-1]

    st.markdown("### 🔄 Échanges")
    for trade in sorted(trades, key=lambda item: item.get("date", ""), reverse=True):
        exchange_id = trade.get("exchange_id") or ""
        given_cards = exchange_out_by_id.get(exchange_id) or trade.get("given_cards", []) or []
        received_cards = trade.get("received_cards", []) or []
        date_str = str(trade.get("date") or "")[:10] or "Date inconnue"
        cash_paid = trade.get("trade_cash_paid", trade.get("cash_paid", 0))
        cash_received = trade.get("trade_cash_received", trade.get("cash_received", 0))
        diff = trade.get("trade_value_difference", trade.get("value_difference", 0))
        title = f"{date_str} · échange"
        if exchange_id:
            title += f" · {exchange_id}"
        with st.expander(title, expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.metric("Cash payé", _money(cash_paid))
            c2.metric("Cash reçu", _money(cash_received))
            c3.metric("Différence de valeur", _money(diff))
            left, right = st.columns(2)
            with left:
                st.markdown("**Cartes données / sorties par échange**")
                _render_trade_card_list(given_cards, proxy_img_func=proxy_img_func)
            with right:
                st.markdown("**Cartes reçues**")
                _render_trade_card_list(received_cards, proxy_img_func=proxy_img_func)


def _build_trade_history_items(cd_hist):
    trades = list(cd_hist.get("trade_history", []) or [])
    exchange_out_by_id = _collect_exchange_out_entries(cd_hist)
    trades_by_id = {trade.get("exchange_id"): trade for trade in trades if trade.get("exchange_id")}
    for exchange_id, given_cards in exchange_out_by_id.items():
        if exchange_id not in trades_by_id:
            trades.append({
                "exchange_id": exchange_id,
                "date": given_cards[0].get("date", "") if given_cards else "",
                "given_cards": given_cards,
                "received_cards": [],
            })

    items = []
    for trade in trades:
        exchange_id = trade.get("exchange_id") or ""
        given_cards = exchange_out_by_id.get(exchange_id) or trade.get("given_cards", []) or []
        received_cards = trade.get("received_cards", []) or []
        all_card_names = " ".join(
            str(card.get("name") or card.get("card_name") or "")
            for card in list(given_cards) + list(received_cards)
        )
        items.append({
            "date": trade.get("date", ""),
            "card_name": all_card_names or "Échange",
            "card_set": "",
            "card_number": "",
            "lot_name": "Échange",
            "price": 0.0,
            "cout": 0.0,
            "benef": 0.0,
            "image_url": "",
            "type": "exchange",
            "quantity": 0,
            "exchange": trade,
            "given_cards": given_cards,
            "received_cards": received_cards,
        })
    return items


def render_history_page(
    *,
    ld_func,
    calc_cout_lot_func,
    effective_purchase_price_func,
    normalize_name_func,
    proxy_img_func,
    render_page_header_func,
    run_html_func,
    lots_archives_path="lots_archives.json",
):
    st.markdown(
        render_page_header_func("Historique des ventes", "Toutes vos transactions et leur rentabilité", "📋"),
        unsafe_allow_html=True,
    )
    
    cd_hist = ld_func()
    trade_image_lookup = _build_trade_image_lookup(cd_hist)
    
    # ── Construire l'historique enrichi avec coût d'achat par carte ──
    hist_enriched = []
    
    archives_hist = []
    if os.path.exists(lots_archives_path):
        with open(lots_archives_path,"r",encoding="utf-8") as f:
            archives_hist = json.load(f)
    
    all_lots_hist = cd_hist.get("lots",[])
    for lot_idx_h, lot in enumerate(all_lots_hist + archives_hist):
        prix_lot = float(lot.get("prix_achat", 0.))
        real_idx = lot_idx_h if lot_idx_h < len(all_lots_hist) else None
        ventes_avec_cout, valeur_est_hist = calc_cout_lot_func(lot, lot_idx=real_idx)
    
        # Ventes en lot (ventes[])
        for v in lot.get("ventes",[]):
            if v.get("is_lot_sale") or v.get("is_exchange_benefit"):
                continue
            price_v = float(v.get("price",0))
            if lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
                cout_v = (price_v / float(lot.get("valeur_totale", 1.) or 1.)) * float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
            else:
                cout_v = (price_v / (valeur_est_hist or 1.0)) * effective_purchase_price_func(lot)
            hist_enriched.append({
                "date": v.get("date",""),
                "card_name": v.get("card_name","Vente lot"),
                "card_set": "", "card_number": "",
                "lot_name": lot.get("nom","?"),
                "price": price_v,
                "cout": cout_v,
                "benef": price_v - cout_v,
                "image_url": "",
                "type": "lot",
            })
    
        # Ventes rapides — coût calculé par calc_cout_lot
        for card, se, cout_total in ventes_avec_cout:
            if se.get("is_exchange"):
                continue
            img = card.get("image_url","") or card.get("image","")
            price = float(se.get("price",0))
            if card.get("received_by_exchange") and (card.get("trade_contributors") or card.get("exchange_repartition")):
                for row in trade_sale_stat_rows(card, se, lot.get("nom", "?")):
                    hist_enriched.append({
                        "date": se.get("date",""),
                        "card_name": se.get("card_name", card.get("name","?")),
                        "card_set": se.get("card_set", card.get("set","")),
                        "card_number": se.get("card_number", card.get("number","")),
                        "lot_name": row["lot"],
                        "price": row["price"],
                        "cout": row["cost"],
                        "benef": row["benef"],
                        "image_url": img,
                        "type": "trade_allocation" if row.get("allocation") else "card",
                        "quantity": int(se.get("quantity",1)),
                        "canal": se.get("canal",""),
                    })
                continue
            hist_enriched.append({
                "date": se.get("date",""),
                "card_name": se.get("card_name", card.get("name","?")),
                "card_set": se.get("card_set", card.get("set","")),
                "card_number": se.get("card_number", card.get("number","")),
                "lot_name": lot.get("nom","?"),
                "price": price,
                "cout": cout_total,
                "benef": price - cout_total,
                "image_url": img,
                "type": "card",
                "quantity": int(se.get("quantity",1)),
                "canal": se.get("canal",""),
            })
    
    hist_enriched.extend(_build_trade_history_items(cd_hist))
    hist_enriched = sorted(hist_enriched, key=lambda x: x.get("date",""), reverse=True)
    
    if not hist_enriched:
        st.info("Aucune vente enregistrée.")
    else:
        # ── Filtres ──
        col_search, col_filter, col_sort = st.columns([3, 1, 1])
        search_hist = col_search.text_input("🔍 Rechercher une carte", placeholder="Nom de carte...", key="search_historique")
    
        # Mois en FR
        MOIS_FR_HIST = {1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
                        7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"}
        def mois_fr_label(m_str):
            try:
                d = datetime.strptime(m_str, "%Y-%m")
                return f"{MOIS_FR_HIST[d.month]} {d.year}"
            except:
                return m_str
    
        mois_disponibles = sorted({h["date"][:7] for h in hist_enriched if h.get("date")}, reverse=True)
        mois_labels = ["Tous"] + [mois_fr_label(m) for m in mois_disponibles]
        mois_map = {mois_fr_label(m): m for m in mois_disponibles}
    
        filter_month_label = col_filter.selectbox("Mois", mois_labels)
        filter_month = mois_map.get(filter_month_label, None)
    
        sort_opt = col_sort.selectbox("Trier par", ["Date (récent)", "Date (ancien)", "Prix (↓)", "Prix (↑)", "Bénéf (↓)", "Bénéf (↑)"])
    
        filtered = hist_enriched
        if search_hist:
            search_hist_norm = normalize_name_func(search_hist)
            filtered = [
                h for h in filtered
                if search_hist_norm in normalize_name_func(str(h.get("card_name", "")))
            ]
        if filter_month:
            filtered = [h for h in filtered if h.get("date","").startswith(filter_month)]
    
        # Tri
        if sort_opt == "Date (récent)":
            filtered = sorted(filtered, key=lambda h: h.get("date",""), reverse=True)
        elif sort_opt == "Date (ancien)":
            filtered = sorted(filtered, key=lambda h: h.get("date",""))
        elif sort_opt == "Prix (↓)":
            filtered = sorted(filtered, key=lambda h: h.get("price", 0), reverse=True)
        elif sort_opt == "Prix (↑)":
            filtered = sorted(filtered, key=lambda h: h.get("price", 0))
        elif sort_opt == "Bénéf (↓)":
            filtered = sorted(filtered, key=lambda h: h.get("benef", 0), reverse=True)
        elif sort_opt == "Bénéf (↑)":
            filtered = sorted(filtered, key=lambda h: h.get("benef", 0))
    
        # ── Résumé ──
        filtered_sales = [h for h in filtered if h.get("type") != "exchange"]
        total_ca_h = sum(h["price"] for h in filtered_sales)
        total_benef_h = sum(h.get("benef", h["price"]) for h in filtered_sales)
        total_nb_h = sum(int(h.get("quantity", 1)) for h in filtered_sales)
    
        s1,s2,s3 = st.columns(3)
        s1.metric("🧾 Ventes", str(total_nb_h))
        s2.metric("💰 CA", f"{total_ca_h:.2f}€")
        s3.metric("💎 Bénéfice estimé", f"{total_benef_h:.2f}€")
    
        current_hist_signature = f"{search_hist}|{filter_month or ''}|{sort_opt}|{len(filtered)}"
        if st.session_state.get("history_signature") != current_hist_signature:
            st.session_state["history_signature"] = current_hist_signature
            st.session_state["history_visible_count"] = 40
        history_visible_count = int(st.session_state.get("history_visible_count", 40))
        visible_history = filtered[:history_visible_count]
        if len(visible_history) < len(filtered):
            st.caption(f"Affichage progressif : {len(visible_history)} vente(s) sur {len(filtered)}.")
        st.markdown("---")
    
        # ── Lignes de l'historique ──
        for h in visible_history:
            if h.get("type") == "exchange":
                trade = h.get("exchange", {}) or {}
                given_cards = h.get("given_cards", []) or []
                received_cards = h.get("received_cards", []) or []
                date_str = h.get("date", "")[:10] if h.get("date") else "?"
                detailed_date = str(h.get("date") or "").replace("T", " ")[:16]
                cash_paid = trade.get("trade_cash_paid", trade.get("cash_paid", 0))
                cash_received = trade.get("trade_cash_received", trade.get("cash_received", 0))
                diff = trade.get("trade_value_difference", trade.get("value_difference", 0))
                diff_value = float(diff or 0)
                diff_color = "#15803d" if diff_value >= 0 else "#dc2626"
                diff_text = f"{diff_value:+.2f}€"
                exchange_id = trade.get("exchange_id") or ""
                st.markdown(
                    f"""
                    <div style="border:1px solid #e2e8f0;background:#ffffff;border-radius:12px;
                                padding:0.9rem 1rem;margin:0.45rem 0 0.25rem 0;
                                box-shadow:0 1px 3px rgba(15,23,42,0.04);">
                      <div style="display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;">
                        <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;">
                          <span style="background:#ede9fe;color:#6d28d9;border-radius:999px;
                                       padding:0.28rem 0.65rem;font-size:0.74rem;font-weight:950;">ÉCHANGE</span>
                          <span style="font-weight:850;color:#0f172a;">{escape(date_str)}</span>
                          <span style="color:#64748b;font-size:0.88rem;">
                            {len(given_cards)} cartes données ↔ {len(received_cards)} cartes reçues
                          </span>
                        </div>
                        <div style="text-align:right;">
                          <div style="font-weight:950;color:{diff_color};font-size:1rem;">{diff_text}</div>
                          <div style="font-size:0.72rem;color:#64748b;">Différence de valeur</div>
                        </div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                with st.expander("Voir le détail de l'échange", expanded=False):
                    left, middle, right = st.columns([2.3, 1.05, 2.3])
                    with left:
                        st.markdown("**Cartes données / sorties**")
                        _render_trade_side(
                            given_cards,
                            proxy_img_func=proxy_img_func,
                            image_lookup=trade_image_lookup,
                            tone="given",
                            total_label="Total donné",
                        )
                    with middle:
                        st.markdown("**Données échange**")
                        _render_trade_cash_panel(cash_paid, cash_received, diff_value)
                    with right:
                        st.markdown("**Cartes reçues / entrées**")
                        _render_trade_side(
                            received_cards,
                            proxy_img_func=proxy_img_func,
                            image_lookup=trade_image_lookup,
                            tone="received",
                            total_label="Total reçu (cartes)",
                        )
                    st.caption(f"ID échange : {exchange_id or '—'} · {detailed_date or '—'}")
                st.markdown('<hr style="margin:0.4rem 0;border:none;border-top:1px solid #f1f5f9;">', unsafe_allow_html=True)
                continue

            benef = h.get("benef", h["price"])
            cout = h.get("cout", 0.)
            benef_color = "#10b981" if benef >= 0 else "#ef4444"
            date_str = h.get("date","")[:10] if h.get("date") else "—"
    
            img_col, info_col, prix_col = st.columns([1, 4, 2])
    
            with img_col:
                img = h.get("image_url","")
                if img:
                    st.markdown(f'<img loading="lazy" src="{proxy_img_func(img)}" style="width:60px;border-radius:6px;box-shadow:0 2px 6px rgba(0,0,0,0.12);">', unsafe_allow_html=True)
                else:
                    st.markdown('<div style="width:60px;height:84px;background:#f1f5f9;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:1.4rem;">🃏</div>', unsafe_allow_html=True)
    
            with info_col:
                set_num = f" · {h['card_set']} #{h['card_number']}" if h.get("card_set") else ""
                qty_h = int(h.get("quantity", 1))
                qty_badge = f' <span style="background:#dbeafe;color:#1d4ed8;border-radius:999px;padding:1px 7px;font-size:0.72rem;font-weight:800;">x{qty_h}</span>' if qty_h > 1 else ""
                canal_h = h.get("canal", "")
                canal_icons = {"Main propre":"🤝","Brocante":"🎪","Dexify_TCG":"⚡","Pokédeal":"🎴","Échange":"🔄"}
                canal_badge = f' <span style="background:#f1f5f9;border-radius:6px;padding:1px 6px;font-size:0.72rem;color:#64748b;">{canal_icons.get(canal_h,"📦")} {canal_h}</span>' if canal_h else ""
                st.markdown(f"""
                <div style="padding:0.2rem 0;">
                  <div style="font-weight:700;font-size:0.98rem;color:#1e293b;">{h['card_name']}{qty_badge}{canal_badge}</div>
                  <div style="font-size:0.8rem;color:#64748b;margin-top:2px;">{h['lot_name']}{set_num}</div>
                  <div style="font-size:0.78rem;color:#94a3b8;margin-top:2px;">📅 {date_str}</div>
                </div>
                """, unsafe_allow_html=True)
    
            with prix_col:
                st.markdown(f"""
                <div style="text-align:right;padding:0.2rem 0;">
                  <div style="font-size:1.1rem;font-weight:800;color:#1e293b;">{h['price']:.2f}€</div>
                  <div style="font-size:0.78rem;color:#94a3b8;">Acheté ~{cout:.2f}€</div>
                  <div style="font-size:0.85rem;font-weight:700;color:{benef_color};">Bénéf : {benef:+.2f}€</div>
                </div>
                """, unsafe_allow_html=True)
    
            st.markdown('<hr style="margin:0.4rem 0;border:none;border-top:1px solid #f1f5f9;">', unsafe_allow_html=True)
    
        if len(visible_history) < len(filtered):
            st.markdown('<div id="history-load-more-anchor"></div>', unsafe_allow_html=True)
            if st.button("Charger plus d'historique", key="history_load_more", width="stretch"):
                st.session_state["history_visible_count"] = history_visible_count + 40
                st.rerun()
            run_html_func("""
            <script>
            (function() {
                const win = parent.window;
                const doc = parent.document;
                if (win.codexHistoryAutoLoadAttached) return;
                win.codexHistoryAutoLoadAttached = true;
                win.addEventListener('scroll', function() {
                    clearTimeout(win.codexHistoryAutoLoadTimer);
                    win.codexHistoryAutoLoadTimer = setTimeout(function() {
                        const anchor = doc.getElementById('history-load-more-anchor');
                        if (!anchor) return;
                        const rect = anchor.getBoundingClientRect();
                        if (rect.top > win.innerHeight + 300) return;
                        const buttons = Array.from(doc.querySelectorAll('button'));
                        const btn = buttons.find(function(b) {
                            return (b.innerText || '').trim() === "Charger plus d'historique";
                        });
                        if (btn && !btn.disabled) btn.click();
                    }, 200);
                }, {passive: true});
            })();
            </script>
            """, height=0)

"""Archived lots and drops page renderer for Pokestock.

The Lots tab keeps the existing archive behaviour and file format
(lots_archives.json). The Drops tab lists the drops flagged ``archived`` in
vinted_drops.json and can restore them (``archived=False``).
"""

import json
import os

import streamlit as st

from services.vinted_drops_service import (
    archived_drops,
    drop_item_status,
    load_vinted_drops,
    restore_drop,
    save_vinted_drops,
)


def _render_archived_lots(
    *,
    ld_func,
    sd_func,
    safe_write_json_func,
    cr_func,
    cp_func,
    crp_func,
    fp_func,
    archive_file_path="lots_archives.json",
):
    archive_file=archive_file_path
    if os.path.exists(archive_file):
        with open(archive_file,"r",encoding="utf-8")as f:
            archives=json.load(f)
        
        if archives:
            st.info(f"📦 {len(archives)} lot(s) archivé(s)")
            
            for ix,lot in enumerate(archives):
                rp_arch = crp_func(lot)
                pf_arch = cp_func(lot)
                color = "#22c55e" if pf_arch >= 0 else "#ee1515"
                with st.expander(f"{lot['nom']} - Archivé le {lot.get('archived_date','N/A')[:10]}"):
                    c1,c2,c3,c4=st.columns(4)
                    c1.metric("Prix achat",fp_func(lot.get("prix_achat",0)))
                    c2.metric("CA",fp_func(cr_func(lot)))
                    c3.metric("%",f"{rp_arch:.1f}%")
                    c4.metric("Bénéfice",fp_func(pf_arch))
                    
                    if st.button(f"Restaurer",key=f"restore_{ix}",type="primary"):
                        restored_lot=archives.pop(ix)
                        del restored_lot["archived_date"]
                        cd=ld_func()
                        cd["lots"].append(restored_lot)
                        sd_func(cd)
                        safe_write_json_func(archive_file, archives, indent=2)
                        st.success("✅ Lot restauré!")
                        st.rerun()
        else:
            st.info("Aucun lot archivé")
    else:
        st.info("Aucun lot archivé")


def _drop_revenue(drop, stock_data):
    """Drop revenue computed like the Drop analytics, or None if unavailable."""
    try:
        from ui.pages.vinted_listings import _sale_rows_for_drop, _sales_scope_metrics

        rows = _sale_rows_for_drop(stock_data, drop.get("id"))
        if not rows:
            return None
        return float(_sales_scope_metrics(rows).get("ca_total", 0) or 0)
    except Exception:
        return None


def _render_archived_drops(*, ld_func, fp_func):
    drops_data = load_vinted_drops()
    archived = archived_drops(drops_data)
    if not archived:
        st.info("Aucun drop archivé")
        return
    st.info(f"🛍️ {len(archived)} drop(s) archivé(s)")
    try:
        stock_data = ld_func()
    except Exception:
        stock_data = {}
    for drop in sorted(archived, key=lambda item: str(item.get("archived_at") or ""), reverse=True):
        drop_id = str(drop.get("id") or "")
        refs = drop.get("cards", []) or []
        total_cards = sum(max(1, int(ref.get("quantity", 1) or 1)) for ref in refs)
        sold_cards = sum(max(1, int(ref.get("quantity", 1) or 1)) for ref in refs if drop_item_status(ref) == "sold")
        revenue = _drop_revenue(drop, stock_data)
        archived_on = str(drop.get("archived_at") or "N/A")[:10]
        with st.expander(f"{drop.get('name', 'Drop sans nom')} - Archivé le {archived_on}"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Cartes", total_cards)
            c2.metric("Vendues", sold_cards)
            c3.metric("CA", fp_func(revenue) if revenue is not None else "N/A")
            c4.metric("Canal", drop.get("channel") or "N/A")
            launched = str(drop.get("drop_launched_at") or "")[:10]
            st.caption(f"Lancé le {launched}" if launched else "Drop non lancé")
            if st.button("Restaurer", key=f"restore_drop_{drop_id}", type="primary"):
                fresh = load_vinted_drops()
                if restore_drop(fresh, drop_id):
                    save_vinted_drops(fresh)
                    st.session_state.pop("vinted_drop_view", None)
                    st.success("✅ Drop restauré !")
                    st.rerun()


def render_archives_page(
    *,
    ld_func,
    sd_func,
    safe_write_json_func,
    render_page_header_func,
    cr_func,
    cp_func,
    crp_func,
    fp_func,
    archive_file_path="lots_archives.json",
):
    st.markdown(
        render_page_header_func("Archivés", "Lots et drops clôturés, données historiques", "🗄️"),
        unsafe_allow_html=True,
    )
    lots_tab, drops_tab = st.tabs(["📦 Lots", "🛍️ Drops"])
    with lots_tab:
        _render_archived_lots(
            ld_func=ld_func,
            sd_func=sd_func,
            safe_write_json_func=safe_write_json_func,
            cr_func=cr_func,
            cp_func=cp_func,
            crp_func=crp_func,
            fp_func=fp_func,
            archive_file_path=archive_file_path,
        )
    with drops_tab:
        _render_archived_drops(ld_func=ld_func, fp_func=fp_func)

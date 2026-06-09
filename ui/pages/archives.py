"""Archived lots page renderer for Pokestock.

This module contains the existing Streamlit UI rendering for the Archivés page.
It preserves the same restore behavior and archive file format.
"""

import json
import os

import streamlit as st


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
        render_page_header_func("Lots archivés", "Lots clôturés et données historiques", "🗄️"),
        unsafe_allow_html=True,
    )
    
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

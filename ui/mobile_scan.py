"""Reusable local assisted scan UI.

The scan never uploads images to an external service. It only uses Streamlit's
camera/file widgets and searches the already loaded local card index.
"""

from __future__ import annotations

import html

import streamlit as st


def _candidate_key(card, set_name, number):
    return str(card.get("id") or card.get("card_id") or f"{card.get('name')}|{set_name}|{number}")


def local_card_candidates(cards_index, normalize_name_func, *, name="", number="", set_query="", limit=5):
    q_name = normalize_name_func(name)
    q_num = str(number or "").strip()
    q_set = normalize_name_func(set_query)
    if not q_name and not q_num and not q_set:
        return []
    seen = set()
    results = []
    for indexed_name, rows in (cards_index or {}).items():
        if q_name and q_name not in normalize_name_func(indexed_name):
            continue
        for row in rows or []:
            try:
                card, set_name, set_id = row[0], row[1], row[2] if len(row) > 2 else ""
            except Exception:
                continue
            if not isinstance(card, dict):
                continue
            card_number = str(card.get("localId") or card.get("number") or "").strip()
            if q_num and card_number.lstrip("0") != q_num.lstrip("0"):
                continue
            set_blob = normalize_name_func(" ".join([str(set_name or ""), str(set_id or ""), str(card.get("set") or "")]))
            if q_set and q_set not in set_blob:
                continue
            key = _candidate_key(card, set_name, card_number)
            if key in seen:
                continue
            seen.add(key)
            score = 40
            if q_name:
                score += 25
            if q_num:
                score += 25
            if q_set:
                score += 10
            results.append(
                {
                    "score": min(score, 98),
                    "card": card,
                    "set_name": set_name,
                    "set_id": set_id,
                    "number": card_number,
                    "language": str(card.get("lang") or card.get("language") or "fr").lower(),
                }
            )
            if len(results) >= limit:
                return results
    return results


def render_assisted_scan(
    *,
    key_prefix,
    cards_index,
    normalize_name_func,
    proxy_img_func=None,
    on_confirm=None,
    button_label="Ajouter",
    allow_next=True,
):
    proxy = proxy_img_func if callable(proxy_img_func) else (lambda value: value)
    if st.session_state.pop(f"{key_prefix}_clear_inputs", False):
        for suffix in ("name", "number", "set"):
            st.session_state.pop(f"{key_prefix}_{suffix}", None)
    st.caption("Scan local assisté : aucune image n'est envoyée à un service externe.")
    st.markdown(
        """
        <div style="border:2px dashed #a78bfa;border-radius:14px;padding:0.75rem;text-align:center;
        background:#faf5ff;color:#4c1d95;font-weight:800;margin-bottom:0.4rem;">
        Cadre la carte, puis renseigne rapidement le nom, le numéro ou la série visibles.
        </div>
        """,
        unsafe_allow_html=True,
    )
    source = st.radio("Source", ["Caméra", "Galerie"], horizontal=True, key=f"{key_prefix}_source")
    if source == "Caméra":
        st.camera_input("Scanner une carte", key=f"{key_prefix}_camera")
    else:
        st.file_uploader("Importer depuis la galerie", type=["jpg", "jpeg", "png", "webp"], key=f"{key_prefix}_gallery")
    c1, c2, c3 = st.columns([2, 1, 1])
    scan_name = c1.text_input("Nom", key=f"{key_prefix}_name", placeholder="Dracaufeu, Eevee...")
    scan_number = c2.text_input("Numéro", key=f"{key_prefix}_number", placeholder="199")
    scan_set = c3.text_input("Série", key=f"{key_prefix}_set", placeholder="MEW, SVP...")
    candidates = local_card_candidates(
        cards_index,
        normalize_name_func,
        name=scan_name,
        number=scan_number,
        set_query=scan_set,
        limit=5,
    )
    if scan_name or scan_number or scan_set:
        if not candidates:
            st.info("Aucun candidat local fiable. Précise le numéro ou la série, ou utilise l'ajout classique.")
        else:
            st.caption("Candidats à confirmer")
            for idx, candidate in enumerate(candidates):
                card = candidate["card"]
                image = str(card.get("image_url") or card.get("image") or "").strip()
                cols = st.columns([1, 3, 1])
                with cols[0]:
                    if image:
                        safe_src = html.escape(proxy(image), quote=True)
                        st.markdown(f'<img src="{safe_src}" style="width:64px;border-radius:8px;">', unsafe_allow_html=True)
                    else:
                        st.markdown("Carte")
                with cols[1]:
                    st.markdown(f"**{card.get('name', 'Carte')}**")
                    st.caption(
                        f"{candidate.get('set_name') or candidate.get('set_id') or 'Série ?'} · "
                        f"#{candidate.get('number') or '?'} · {candidate.get('language', 'fr').upper()} · "
                        f"confiance {candidate.get('score')}%"
                    )
                with cols[2]:
                    if st.button(button_label, key=f"{key_prefix}_confirm_{idx}", width="stretch"):
                        if callable(on_confirm):
                            on_confirm(candidate)
                        if allow_next:
                            st.session_state[f"{key_prefix}_clear_inputs"] = True
                        st.rerun()
    return candidates

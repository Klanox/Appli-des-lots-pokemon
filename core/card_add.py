"""Card add and choice popup actions for Pokestock.

Extracted conservatively from app.py. Dependencies are injected from app.py
to preserve existing behavior while reducing app.py size.
"""

import glob
import json
import os
import time

from services.card_identity import card_identity_fingerprint
from services.custom_card_image_service import apply_custom_image_fallback, resolve_custom_card_image


def configure_card_add(context):
    globals().update(context)


def _compact_number(value):
    value = str(value or "").strip().upper().replace(" ", "")
    if value.isdigit():
        return value.lstrip("0") or "0"
    return value


def _parse_japanese_number_query(value):
    value = str(value or "").strip().replace(" ", "")
    if "/" not in value:
        return value, ""
    local, total = value.split("/", 1)
    return local.strip(), total.strip()


def _number_matches(actual, expected):
    expected = _compact_number(expected)
    if not expected:
        return True
    return _compact_number(actual) == expected


def _collect_total_values(value):
    totals = []
    if isinstance(value, dict):
        for key in ("cardCount", "total", "printedTotal", "official", "cards", "set_total", "total_in_set", "printed_total", "number_total"):
            if key in value:
                totals.extend(_collect_total_values(value.get(key)))
        return totals
    if isinstance(value, (list, tuple)):
        for item in value:
            totals.extend(_collect_total_values(item))
        return totals
    text = str(value or "").strip()
    if text and text.isdigit():
        totals.append(text)
    return totals


def _japanese_candidate_total_values(card):
    values = []
    raw_card = card.get("raw_cache_card") if isinstance(card.get("raw_cache_card"), dict) else {}
    for source in (card, raw_card):
        if not isinstance(source, dict):
            continue
        values.extend(_collect_total_values(source))
        set_info = source.get("set") if isinstance(source.get("set"), dict) else {}
        values.extend(_collect_total_values(set_info))
        for number_key in ("number", "card_number", "localId"):
            raw_number = str(source.get(number_key) or "")
            if "/" in raw_number:
                _, total = _parse_japanese_number_query(raw_number)
                if total:
                    values.append(total)

    deduped = []
    for value in values:
        normalized = _compact_number(value)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _japanese_candidate_matches_total(card, expected_total):
    expected_total = _compact_number(expected_total)
    if not expected_total:
        return True
    return expected_total in _japanese_candidate_total_values(card)


def _is_japanese_metadata_flag(lang):
    return str(lang or "").strip().casefold() in {"ja", "jp", "jpn", "japanese", "japonais", "japonaise"}


def _card_search_lang_for_metadata(lang):
    return "fr" if _is_japanese_metadata_flag(lang) else (lang if lang in ("fr", "en") else "fr")


def _apply_japanese_metadata(card, lang):
    if _is_japanese_metadata_flag(lang):
        card["japanese"] = True
    return card


def _popup_candidate_set_id(card_dict):
    set_info = card_dict.get("set")
    if isinstance(set_info, dict):
        return str(set_info.get("id") or "").strip()
    return str(card_dict.get("set_id") or card_dict.get("card_set_id") or "").strip()


def _popup_candidate_number(card_dict):
    raw_card = card_dict.get("raw_cache_card") if isinstance(card_dict.get("raw_cache_card"), dict) else {}
    return str(
        card_dict.get("localId")
        or card_dict.get("number")
        or card_dict.get("card_number")
        or raw_card.get("localId")
        or raw_card.get("number")
        or raw_card.get("card_number")
        or ""
    ).strip()


def _popup_candidate_set_name(card_dict, set_name=""):
    raw_card = card_dict.get("raw_cache_card") if isinstance(card_dict.get("raw_cache_card"), dict) else {}
    for source in (card_dict, raw_card):
        set_info = source.get("set") if isinstance(source.get("set"), dict) else {}
        value = str(set_info.get("name") or source.get("set_name") or source.get("card_set") or "").strip()
        if value:
            return value
    value = str(set_name or "").replace("ðŸ‡¯ðŸ‡µ ", "").replace("🇯🇵 ", "").strip()
    if value:
        return value
    return _popup_candidate_set_id(card_dict)


def _popup_candidate_details_caption(card_dict, set_name=""):
    set_caption = _popup_candidate_set_name(card_dict, set_name)
    number_caption = _popup_candidate_number(card_dict)
    return " · ".join(x for x in [set_caption, f"#{number_caption}" if number_caption else ""] if x)


def _render_popup_candidate_details(card_dict, set_name=""):
    details_caption = _popup_candidate_details_caption(card_dict, set_name)
    if not details_caption:
        return
    st.markdown(
        '<div style="font-size:0.78rem;color:#64748b;text-align:center;'
        f'line-height:1.25;margin-top:-0.25rem;">{html.escape(details_caption)}</div>',
        unsafe_allow_html=True,
    )


def _popup_candidate_image(card_dict):
    images = card_dict.get("images") if isinstance(card_dict.get("images"), dict) else {}
    for value in (
        card_dict.get("image"),
        card_dict.get("imageUrl"),
        card_dict.get("image_url"),
        card_dict.get("image_url_en"),
        images.get("large"),
        images.get("small"),
    ):
        img = str(value or "").strip()
        if not img:
            continue
        if "tcgdex.net" in img and not any(img.endswith(ext) for ext in [".jpg", ".png", ".jpeg", ".webp"]):
            img = f"{img}/high.webp"
        return img

    return resolve_custom_card_image(
        {
            **card_dict,
            "card_id": card_dict.get("card_id") or card_dict.get("id") or "",
            "set_id": _popup_candidate_set_id(card_dict),
            "number": _popup_candidate_number(card_dict),
            "raw_cache_card": card_dict,
        }
    )


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _divers_purchase_total(card):
    return max(_safe_float(card.get("purchase_price"), 0.0), 0.0) * max(_safe_int(card.get("quantity"), 1), 1)


def _refresh_divers_lot_purchase_price(lot):
    if lot.get("is_divers"):
        lot["prix_achat"] = sum(_divers_purchase_total(card) for card in lot.get("cards", []))


def _find_duplicate_card_in_lot(lot, new_card):
    new_fingerprint = card_identity_fingerprint(new_card)
    if not new_fingerprint:
        return None, None, ""
    for idx, existing in enumerate(lot.get("cards", []) or []):
        if card_identity_fingerprint(existing) == new_fingerprint:
            return idx, existing, new_fingerprint
    return None, None, new_fingerprint


def _queue_duplicate_confirmation(li, new_card, existing_card, fingerprint):
    existing_popups = glob.glob(f"popup_{li}_*.json")
    if existing_popups:
        return True, "Cette carte existe déjà dans ce lot. Choisis l'action à appliquer ci-dessous."
    payload = {
        "type": "duplicate_confirmation",
        "new_card": new_card,
        "existing_card_uid": existing_card.get("card_uid", ""),
        "existing_card_name": existing_card.get("name", ""),
        "existing_card_number": existing_card.get("number", ""),
        "existing_card_set": existing_card.get("set", ""),
        "fingerprint": fingerprint,
        "search_id": f"dup_{li}_{int(time.time() * 1000)}",
    }
    popup_file = f"popup_{li}_dup_{int(time.time() * 1000)}.json"
    with open(popup_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return True, "Cette carte existe déjà dans ce lot."


def _merge_duplicate_card_into_existing(lot, new_card, *, existing_card_uid="", fingerprint=""):
    target = None
    for card in lot.get("cards", []) or []:
        uid_matches = existing_card_uid and card.get("card_uid") == existing_card_uid
        fingerprint_matches = fingerprint and card_identity_fingerprint(card) == fingerprint
        if uid_matches or fingerprint_matches:
            target = card
            break
    if target is None:
        lot.setdefault("cards", []).append(new_card)
        return "added"

    old_qty = max(_safe_int(target.get("quantity"), 1), 1)
    add_qty = max(_safe_int(new_card.get("quantity"), 1), 1)
    merged_qty = old_qty + add_qty
    old_purchase_total = _divers_purchase_total(target)
    new_purchase_total = _divers_purchase_total(new_card)
    target["quantity"] = merged_qty
    if old_purchase_total or new_purchase_total:
        target["purchase_price"] = (old_purchase_total + new_purchase_total) / merged_qty
    if not target.get("image_url") and new_card.get("image_url"):
        target["image_url"] = new_card.get("image_url")
    if not target.get("image_url_en") and new_card.get("image_url_en"):
        target["image_url_en"] = new_card.get("image_url_en")
    for list_key in ("price_history",):
        merged = []
        merged.extend(target.get(list_key, []) or [])
        merged.extend(new_card.get(list_key, []) or [])
        if merged:
            target[list_key] = merged
    return "merged"


def _add_card_to_lot_or_confirm_duplicate(cd, li, new_card, *, force_new=False):
    lot = cd["lots"][li]
    if lot.get("is_divers"):
        if not force_new:
            _idx, existing, fingerprint = _find_duplicate_card_in_lot(lot, new_card)
            if existing is not None:
                ok, msg = _queue_duplicate_confirmation(li, new_card, existing, fingerprint)
                return ok, msg, False
        lot.setdefault("cards", []).append(new_card)
        _refresh_divers_lot_purchase_price(lot)
        return True, "Ajoutée!", True

    add_or_merge_collection_card(cd, li, new_card)
    return True, "Ajoutée!", True


def _apply_divers_duplicate_confirmation(cd, li, new_card, mode, *, existing_card_uid="", fingerprint=""):
    if li >= len(cd.get("lots", [])):
        return False, "Lot introuvable pendant l'ajout."
    lot = cd["lots"][li]
    if not lot.get("is_divers"):
        add_or_merge_collection_card(cd, li, new_card)
        return True, "Ajoutée!"
    if mode == "merge":
        result = _merge_duplicate_card_into_existing(
            lot,
            new_card,
            existing_card_uid=existing_card_uid,
            fingerprint=fingerprint,
        )
        _refresh_divers_lot_purchase_price(lot)
        return True, "Quantité mise à jour." if result == "merged" else "Ajoutée!"
    lot.setdefault("cards", []).append(new_card)
    _refresh_divers_lot_purchase_price(lot)
    return True, "Nouvelle entrée créée."


def acm_japanese(li, n, sn, num, q, co, p, ir, ie, purchase_price=0., special_tag="", collection_keep=False):
    """Compatibilite : le flag japonais est une metadonnee, la recherche reste standard."""
    return acm(
        li,
        n,
        sn,
        num,
        q,
        co,
        p,
        ir,
        ie,
        lang="ja",
        purchase_price=purchase_price,
        special_tag=special_tag,
        collection_keep=collection_keep,
    )


def acm(li,n,sn,num,q,co,p,ir,ie,lang="fr",purchase_price=0., special_tag="", collection_keep=False):
    """Ajouter carte au lot"""
    card_lang = _card_search_lang_for_metadata(lang)
    japanese_metadata = _is_japanese_metadata_flag(lang)
    n=n.strip().title()
    sn=sn.strip()
    num=num.strip()
    
    if not n:
        return False,"Nom requis"

    try:
        cd_rule = ld()
        if collection_keep and li < len(cd_rule.get("lots", [])) and cd_rule["lots"][li].get("is_divers"):
            return False, "Les cartes Collection doivent être ajoutées depuis le menu Collection, pas depuis Divers."
    except Exception:
        pass

    multi=[x.strip().title() for x in n.split(",")]
    
    if len(multi)>1:
        ok_count=0
        for nm in multi:
            if nm:
                lok,lmg=acm(li,nm,sn,num,q,co,p,ir,ie,lang=lang,purchase_price=purchase_price,special_tag=special_tag,collection_keep=collection_keep)
                if lok:
                    ok_count+=1
        return ok_count>0,f"{ok_count} carte(s) ajoutée(s)"
    
    ci,si=afi(n,sn,num)
    
    if not ci:
        ai=sgt(n,num)
        if not ai:
            return False,f"'{n}' introuvable"
        
        
        if len(ai)==1:
            # Chercher les variantes directement dans le cache — sans appeler sgt()
            # pour éviter les appels réseau inutiles
            cards_index = st.session_state.get("cards_index", {})
            suffixes = ["vmax", "v", "ex", "gx", "mega", "tag team", "prime", "lv.x", "break", "legendaire", "légendaire"]
            base_name = normalize_name(n)
            
            seen_ids = set()
            for c,s in ai:
                seen_ids.add(c.get("id",""))
            variantes_uniq = []

            for suffix in suffixes:
                if base_name.endswith(normalize_name(suffix)):
                    continue
                for sep in [" ", "-"]:
                    key = normalize_name(f"{n}{sep}{suffix}".strip())
                    if key in cards_index:
                        for card, set_name, set_id in cards_index[key]:
                            card_num = str(card.get("localId","") or card.get("number",""))
                            matches_num = not num or card_num == num or card_num.zfill(3) == num.zfill(3)
                            if matches_num and card.get("id","") not in seen_ids:
                                seen_ids.add(card.get("id",""))
                                variantes_uniq.append((card, set_name))

            if variantes_uniq:
                # Il y a de vraies variantes différentes — afficher le popup
                all_results = ai + variantes_uniq
                existing_popups = glob.glob(f"popup_{li}_*.json")
                if existing_popups:
                    return True, f"{len(all_results)} résultats"
                sid = f"{li}_{int(time.time()*1000)}"
                pd = {"matches": [[c,s] for c,s in all_results], "pending": [n,sn,num,q,co,p,ir,ie,special_tag,collection_keep], "search_id": sid, "pa_carte": purchase_price, "lang": card_lang, "japanese": japanese_metadata}
                pf = f"popup_{li}_{int(time.time()*1000)}.json"
                with open(pf, "w") as f:
                    json.dump(pd, f)
                return True, f"{len(all_results)} résultats"

            # Aucune variante — ajout direct sans popup
            ci,si=ai[0]
        else:
            existing_popups = glob.glob(f"popup_{li}_*.json")
            if existing_popups:
                return True,f"{len(ai)} résultats"
            
            sid=f"{li}_{int(time.time()*1000)}"
            pd={"matches":[[c,s]for c,s in ai],"pending":[n,sn,num,q,co,p,ir,ie,special_tag,collection_keep],"search_id":sid,"pa_carte":purchase_price,"lang":card_lang,"japanese":japanese_metadata}
            pf=f"popup_{li}_{int(time.time()*1000)}.json"
            with open(pf,"w")as f:
                json.dump(pd,f)
            return True,f"{len(ai)} résultats"
    
    cd=ld()
    nc=ecd(ci,si,lang=card_lang)
    _apply_japanese_metadata(nc, lang)
    apply_custom_image_fallback(nc)
    nc["card_uid"] = new_uid("card")
    nc["quantity"]=q if q else 1
    nc["condition"]=co
    nc["suggested_price"]=p if p else 0.
    nc["is_reverse"]=ir
    nc["is_ed1"]=ie
    if purchase_price > 0:
        nc["purchase_price"] = purchase_price
    if special_tag:
        nc["special_tag"] = special_tag
    if collection_keep:
        nc["is_collection_keep"] = True
        nc["collection_current_value"] = float(p or 0.)
        nc["collection_purchase_price"] = float(purchase_price or 0.)
    ok_add, msg_add, changed = _add_card_to_lot_or_confirm_duplicate(cd, li, nc)
    if changed:
        sd(cd)

    return ok_add, msg_add

def render_card_choice_popups(li, form_ts_key=None, run_html_func=None):
    popup_files = glob.glob(f"popup_{li}_*.json")
    if not popup_files:
        return

    st.markdown('<div id="card-choice-popup"></div>', unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .choice-card-imgbox {
            height: 170px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #f8fafc;
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            padding: 0.35rem;
            overflow: hidden;
        }
        .choice-card-imgbox img {
            max-width: 100%;
            max-height: 100%;
            width: auto;
            height: auto;
            object-fit: contain;
            border-radius: 9px;
        }
        @media (max-width: 700px) {
            .choice-card-imgbox { height: 130px; padding: 0.25rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if run_html_func is not None:
        run_html_func("""
        <script>
        setTimeout(function() {
            const el = parent.document.getElementById('card-choice-popup');
            if (el) el.scrollIntoView({behavior:'smooth', block:'start'});
        }, 250);
        </script>
        """, height=0)

    for popup_file in popup_files:
        try:
            with open(popup_file, "r", encoding="utf-8") as f:
                popup_data = json.load(f)

            popup_key = os.path.basename(popup_file).replace(".", "_").replace("\\", "_").replace("/", "_")
            if popup_data.get("type") == "duplicate_confirmation":
                new_card = popup_data.get("new_card") or {}
                existing_label = " · ".join(
                    x
                    for x in (
                        popup_data.get("existing_card_name"),
                        popup_data.get("existing_card_set"),
                        f"#{popup_data.get('existing_card_number')}" if popup_data.get("existing_card_number") else "",
                    )
                    if x
                )
                st.warning("Cette carte existe déjà dans ce lot.")
                if existing_label:
                    st.caption(f"Entrée existante : {existing_label}")
                c_merge, c_new = st.columns(2)
                with c_merge:
                    if st.button("Ajouter à la quantité existante", key=f"merge_duplicate_{li}_{popup_key}", type="primary", width="stretch"):
                        os.remove(popup_file)
                        cd_add = ld()
                        ok_apply, msg_apply = _apply_divers_duplicate_confirmation(
                            cd_add,
                            li,
                            new_card,
                            "merge",
                            existing_card_uid=popup_data.get("existing_card_uid", ""),
                            fingerprint=popup_data.get("fingerprint", ""),
                        )
                        if ok_apply:
                            sd(cd_add)
                            if form_ts_key:
                                st.session_state[form_ts_key] = time.time()
                            st.session_state[f"lot_expanded_{li}"] = True
                            st.success(msg_apply)
                            st.rerun()
                        st.error(msg_apply)
                with c_new:
                    if st.button("Créer une nouvelle entrée", key=f"new_duplicate_{li}_{popup_key}", width="stretch"):
                        os.remove(popup_file)
                        cd_add = ld()
                        ok_apply, msg_apply = _apply_divers_duplicate_confirmation(cd_add, li, new_card, "new")
                        if ok_apply:
                            sd(cd_add)
                            if form_ts_key:
                                st.session_state[form_ts_key] = time.time()
                            st.session_state[f"lot_expanded_{li}"] = True
                            st.success(msg_apply)
                            st.rerun()
                        st.error(msg_apply)
                continue

            st.warning(f"⚠️ {len(popup_data['matches'])} résultats trouvés — choisissez la bonne carte :")
            popup_lang = popup_data.get("lang", "fr")
            popup_japanese = bool(popup_data.get("japanese")) or _is_japanese_metadata_flag(popup_lang)
            enrich_lang = _card_search_lang_for_metadata(popup_lang)
            with st.container(key=f"search_results_grid_popup_{li}_{popup_key}", horizontal=True, gap="small"):
                for idx_p, (card_dict, set_name) in enumerate(popup_data["matches"]):
                    with st.container(key=f"search_result_card_popup_{li}_{popup_key}_{idx_p}"):
                        img = _popup_candidate_image(card_dict)
                        if img:
                            safe_src = html.escape(proxy_img(img), quote=True)
                            safe_name = html.escape(card_dict.get("name", "Carte"), quote=True)
                            st.markdown(f'<div class="choice-card-imgbox"><img src="{safe_src}" alt="{safe_name}"></div>', unsafe_allow_html=True)
                        else:
                            st.markdown('<div class="choice-card-imgbox">🃏</div>', unsafe_allow_html=True)
                            if popup_lang == "ja":
                                cm_url = html.escape(cardmarket_search_url(card_dict.get("name", "")), quote=True)
                                st.markdown(f'<a href="{cm_url}" target="_blank" style="font-size:0.75rem;color:#3b4cca;text-decoration:none;">🔍 Voir sur Cardmarket</a>', unsafe_allow_html=True)

                        display_name = set_name.replace("🇯🇵 ", "") if popup_lang == "ja" else card_dict.get("name", "")
                        st.caption(f"{display_name}")
                        _render_popup_candidate_details(card_dict, set_name)
                        set_caption = str(set_name or "").replace("ðŸ‡¯ðŸ‡µ ", "").strip()
                        number_caption = _popup_candidate_number(card_dict)
                        details_caption = " · ".join(x for x in [set_caption, f"#{number_caption}" if number_caption else ""] if x)
                        if details_caption:
                            pass

                        if st.button("Choisir", key=f"choose_{popup_file}_{idx_p}"):
                            os.remove(popup_file)
                            pending_vals = list(popup_data.get("pending", []))
                            pending_vals += [""] * (10 - len(pending_vals))
                            n, sn, num, q, co, p, ir, ie, special_tag, collection_keep_pending = pending_vals[:10]
                            name_override = popup_data.get("name_override", "")
                            pa_carte_popup = popup_data.get("pa_carte", 0.)
                            cd_add = ld()
                            if li >= len(cd_add.get("lots", [])):
                                st.error("Lot introuvable pendant l'ajout.")
                                st.rerun()
                            lot_now = cd_add["lots"][li]
                            if lot_now.get("is_divers") and collection_keep_pending:
                                st.error("Les cartes Collection doivent être ajoutées depuis le menu Collection, pas depuis Divers.")
                                st.rerun()

                            nc = ecd(card_dict, set_name, lang=enrich_lang)
                            if popup_japanese:
                                nc["japanese"] = True
                            nc["card_uid"] = new_uid("card")
                            nc["quantity"] = q if q else 1
                            nc["condition"] = co
                            nc["suggested_price"] = p if p else 0.
                            nc["is_reverse"] = ir
                            nc["is_ed1"] = ie
                            if name_override:
                                nc["name"] = name_override
                            if lot_now.get("is_divers") and pa_carte_popup > 0:
                                nc["purchase_price"] = pa_carte_popup
                            if special_tag:
                                nc["special_tag"] = special_tag
                            if collection_keep_pending:
                                nc["is_collection_keep"] = True
                                nc["collection_current_value"] = float(p or 0.)
                                nc["collection_purchase_price"] = float(pa_carte_popup or 0.)
                            apply_custom_image_fallback(nc)
                            ok_add, msg_add, changed = _add_card_to_lot_or_confirm_duplicate(cd_add, li, nc)
                            if changed:
                                sd(cd_add)
                            if form_ts_key:
                                st.session_state[form_ts_key] = time.time()
                            st.session_state[f"lot_expanded_{li}"] = True
                            if ok_add:
                                st.success(msg_add)
                            else:
                                st.error(msg_add)
                            st.rerun()
        except Exception:
            try:
                os.remove(popup_file)
            except Exception:
                pass


"""Estimations page renderer for Pokestock."""

from __future__ import annotations

from datetime import datetime
import html
import json

import streamlit as st


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=1):
    try:
        return max(int(value or default), 1)
    except (TypeError, ValueError):
        return default


def _card_weight(card):
    return _safe_float(card.get("cote")) * _safe_int(card.get("quantity"))


def _estimate_score(totals):
    total_cote = _safe_float(totals.get("total_cote"))
    seller_price = _safe_float(totals.get("seller_price"))
    margin = _safe_float(totals.get("theoretical_margin"))
    if total_cote <= 0 or seller_price <= 0:
        return -999999
    real_pct = seller_price / total_cote * 100
    return (100 - real_pct) * 100 + margin


def _opportunity_label(totals):
    total_cote = _safe_float(totals.get("total_cote"))
    seller_price = _safe_float(totals.get("seller_price"))
    if total_cote <= 0 or seller_price <= 0:
        return "À vérifier", "check"
    real_pct = seller_price / total_cote * 100
    if real_pct < 60:
        return "Très intéressant", "great"
    if real_pct < 70:
        return "Intéressant", "good"
    if real_pct < 80:
        return "Correct", "ok"
    return "Trop cher", "bad"


def _tone_for_status(label, status=""):
    status = str(status or "").lower()
    if "acheté" in status:
        return "done"
    return {
        "Très intéressant": "great",
        "Intéressant": "good",
        "Correct": "ok",
        "Trop cher": "bad",
        "À vérifier": "check",
    }.get(label, "check")


def _best_card(estimate):
    cards = estimate.get("cards", []) or []
    if not cards:
        return {}
    return max(cards, key=_card_weight)


def _card_title(card):
    if not card:
        return "Aucune carte"
    number = str(card.get("number") or "").strip()
    suffix = f" #{number}" if number else ""
    return f"{card.get('name', 'Carte')}{suffix}"


def _all_cards_value(estimate):
    return sum(_card_weight(card) for card in estimate.get("cards", []) or [])


def _estimated_paid_for_card(card, estimate):
    seller_price = _safe_float(estimate.get("seller_price"))
    total_value = _all_cards_value(estimate)
    if seller_price <= 0 or total_value <= 0:
        return 0.0, 0.0
    qty = _safe_int(card.get("quantity"))
    line_paid = seller_price * (_card_weight(card) / total_value)
    return line_paid, line_paid / qty if qty else line_paid


def _query_parts(query, normalize_name_func):
    raw = str(query or "").strip()
    normalized = normalize_name_func(raw)
    tokens = [token for token in normalized.replace("/", " ").split() if token]
    number = next((token for token in tokens if token.isdigit()), "")
    aliases = {
        "ar": ["art rare", "illustration rare", "rare illustration", "illustration"],
        "fa": ["full art", "ultra rare", "rare ultra", "fullart"],
        "alt": ["alternative", "alt art", "alternative art", "illustration speciale", "special illustration"],
        "sar": ["special art rare", "special illustration", "illustration speciale", "sar"],
        "promo": ["promo", "promotional"],
        "ex": ["ex"],
        "gx": ["gx"],
        "v": [" v ", " pokemon v"],
        "vmax": ["vmax", "v max"],
        "vstar": ["vstar", "v star"],
    }
    keywords = []
    requested_types = []
    searchable_tokens = []
    for token in tokens:
        if token == number:
            continue
        if token in aliases:
            keywords.extend(aliases[token])
            requested_types.append(token)
            continue
        searchable_tokens.append(token)
    base_query = " ".join(searchable_tokens).strip() or raw
    broad_query = searchable_tokens[0] if searchable_tokens else base_query
    return raw, base_query, broad_query, number, keywords, searchable_tokens, requested_types


def _contains_type(haystack, requested_type):
    padded = f" {haystack} "
    type_hits = {
        "fa": ["full art", "fullart", "ultra rare", "rare ultra", "secret rare", "hyper rare"],
        "ar": ["art rare", "illustration rare", "rare illustration"],
        "alt": ["alternative", "alt art", "alternative art", "special illustration", "illustration speciale"],
        "sar": ["special art rare", "special illustration", "illustration speciale"],
        "promo": [" promo ", " promotional "],
        "ex": [" ex ", "-ex", " ex-"],
        "gx": [" gx ", "-gx", " gx-"],
        "v": [" v ", " pokemon v "],
        "vmax": ["vmax", "v max"],
        "vstar": ["vstar", "v star"],
    }
    return any(needle in padded for needle in type_hits.get(requested_type, []))


def _suggestion_score(enriched, keywords, terms, number, requested_types, normalize_name_func):
    haystack = normalize_name_func(
        " ".join(
            str(enriched.get(key, ""))
            for key in ("name", "set", "number", "rarity", "category", "id")
        )
    )
    score = 0
    if number and str(enriched.get("number", "")).startswith(number):
        score += 45
    for term in terms:
        if term and term in haystack:
            score += 12
    for keyword in keywords:
        keyword_norm = normalize_name_func(keyword)
        if keyword_norm and keyword_norm in haystack:
            score += 22
    for requested_type in requested_types:
        if _contains_type(haystack, requested_type):
            score += 55
        else:
            score -= 18
    rarity = normalize_name_func(enriched.get("rarity", ""))
    name_norm = normalize_name_func(enriched.get("name", ""))
    if any(word in rarity for word in ["rare", "ultra", "illustration", "secret", "promo"]):
        score += 10
    if any(word in rarity for word in ["common", "commune", "uncommon", "peu commune"]):
        score -= 18 if requested_types else 3
    if enriched.get("image_url") or enriched.get("image_url_en"):
        score += 8
    else:
        score -= 8
    if terms and all(term in name_norm for term in terms):
        score += 26
    elif terms and terms[0] in name_norm:
        score += 12
    return score


def _card_suggestions(query, current_number, search_in_cache_func, ecd_func, normalize_name_func, limit=8):
    raw, base_query, broad_query, parsed_number, keywords, terms, requested_types = _query_parts(query, normalize_name_func)
    number = str(current_number or parsed_number or "").strip()
    if len(raw.strip()) < 3:
        return []

    candidates = []
    for q in [base_query, broad_query, raw]:
        if not q:
            continue
        try:
            candidates.extend(search_in_cache_func(q, number))
        except Exception:
            continue

    seen = set()
    suggestions = []
    for match in candidates:
        try:
            card_dict, set_name = match
            enriched = ecd_func(card_dict, set_name, lang="fr")
        except Exception:
            continue
        key = enriched.get("id") or "|".join(
            [
                str(enriched.get("name", "")),
                str(enriched.get("number", "")),
                str(enriched.get("set", "")),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        score = _suggestion_score(enriched, keywords, terms, number, requested_types, normalize_name_func)
        suggestions.append({"match": match, "card": enriched, "score": score})

    suggestions.sort(key=lambda item: item["score"], reverse=True)
    return suggestions[:limit]


def _image_html(card, proxy_img_func, class_name="est-box-img"):
    url = str((card or {}).get("image_url") or "").strip()
    if url:
        safe_url = html.escape(proxy_img_func(url), quote=True)
        alt = html.escape(str((card or {}).get("name") or "Carte"), quote=True)
        return (
            f'<img class="{class_name}" src="{safe_url}" alt="{alt}" '
            "onerror=\"this.closest('.est-img-frame').classList.add('missing');this.remove();\">"
        )
    return '<div class="est-placeholder">Image indisponible</div>'


def _kpi(label, value, tone="neutral", accent=None):
    accent_class = accent or tone
    return (
        f'<div class="est-kpi {accent_class}">'
        f"<span>{html.escape(str(label))}</span>"
        f"<strong>{html.escape(str(value))}</strong>"
        "</div>"
    )


def _estimate_cover_card(estimate):
    listing_image = str(estimate.get("listing_image_url") or "").strip()
    if listing_image:
        return {
            "name": "Photo annonce",
            "number": "",
            "image_url": listing_image,
        }
    return _best_card(estimate)


def _estimate_box_html(item, fp_func, proxy_img_func, active=False):
    estimate = item["estimate"]
    totals = item["totals"]
    label = item["label"]
    tone = _tone_for_status(label, estimate.get("status"))
    best = _best_card(estimate)
    cover = _estimate_cover_card(estimate)
    title = html.escape(str(estimate.get("name") or "Estimation"))
    listing_url = str(estimate.get("listing_url") or "").strip()
    listing_link = (
        f'<a class="est-listing-link" href="{html.escape(listing_url, quote=True)}" target="_blank">Ouvrir l’annonce</a>'
        if listing_url
        else ""
    )
    source = html.escape(str(estimate.get("source") or "Vinted"))
    status = html.escape(str(estimate.get("status") or "En cours"))
    card_count = sum(_safe_int(card.get("quantity")) for card in estimate.get("cards", []) or [])
    seller_price = _safe_float(totals.get("seller_price"))
    total_cote = _safe_float(totals.get("total_cote"))
    real_pct = _safe_float(totals.get("real_pct"))
    margin = _safe_float(totals.get("theoretical_margin"))
    pct_label = f"{real_pct:.1f}%" if real_pct else "À vérifier"
    active_class = " active" if active else ""
    uid = html.escape(str(estimate.get("uid") or ""), quote=True)
    return f"""
    <div class="est-opportunity-card {tone}{active_class}" data-est-card-uid="{uid}" role="button" tabindex="0">
        <div class="est-card-ribbon"></div>
        <div class="est-card-main">
            <div class="est-img-frame">
                {_image_html(cover, proxy_img_func)}
            </div>
            <div class="est-card-content">
                <div class="est-card-topline">
                    <span class="est-badge {tone}">{html.escape(label)}</span>
                    <span class="est-chip">{source}</span>
                    <span class="est-chip">{status}</span>
                </div>
                <h3><span>{title}</span>{listing_link}</h3>
                <p>{html.escape(_card_title(best))}</p>
                <div class="est-metrics">
                    {_kpi("Prix demandé", fp_func(seller_price) if seller_price > 0 else "À saisir", tone)}
                    {_kpi("Cote", fp_func(total_cote), tone)}
                    {_kpi("% cote", pct_label, tone)}
                    {_kpi("Marge", fp_func(margin) if total_cote else "À vérifier", tone)}
                    {_kpi("Cartes", f"{card_count}", tone)}
                </div>
            </div>
        </div>
    </div>
    """


def _render_tracked_card(card, estimate, fp_func, img_with_fallback_func):
    qty = _safe_int(card.get("quantity"))
    cote = _safe_float(card.get("cote"))
    line_paid, unit_paid = _estimated_paid_for_card(card, estimate)
    line_margin = cote * qty - line_paid if line_paid else 0.0
    number = str(card.get("number") or "").strip()
    special = str(card.get("special") or "").strip()
    st.markdown('<div class="est-tracked-mini-marker"></div>', unsafe_allow_html=True)
    if card.get("image_url") or card.get("image_url_en"):
        st.markdown(
            img_with_fallback_func(
                card.get("image_url", ""),
                card.get("image_url_en", ""),
                width="100%",
                style="max-height:118px;object-fit:contain;border-radius:10px;background:#f8fafc;",
            ),
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="est-card-placeholder compact">Image indisponible</div>', unsafe_allow_html=True)
    st.markdown(f"**{card.get('name') or 'Carte'}**")
    tags = " · ".join(x for x in [f"#{number}" if number else "", special, f"x{qty}"] if x)
    if tags:
        st.caption(tags)
    paid_label = fp_func(unit_paid) if unit_paid else "À vérifier"
    margin_label = fp_func(line_margin) if line_paid else "À vérifier"
    st.caption(f"Cote: {fp_func(cote)}")
    st.caption(f"Payé estimé: {paid_label}")
    st.caption(f"Marge ligne: {margin_label}")


def _suggestion_html(enriched, img_with_fallback_func):
    image = (
        img_with_fallback_func(enriched.get("image_url", ""), enriched.get("image_url_en", ""), width="100%", style="")
        if enriched.get("image_url") or enriched.get("image_url_en")
        else '<div class="est-suggestion-placeholder">Image</div>'
    )
    number = str(enriched.get("number") or "").strip()
    set_name = str(enriched.get("set") or "").strip()
    rarity = str(enriched.get("rarity") or "").strip()
    return f"""
    <div class="est-suggestion-card">
        <div class="est-suggestion-img">{image}</div>
        <div class="est-suggestion-copy">
            <strong>{html.escape(str(enriched.get("name") or "Carte"))}</strong>
            <span>{html.escape(" · ".join(x for x in [f"#{number}" if number else "", set_name] if x))}</span>
            {f'<em>{html.escape(rarity)}</em>' if rarity else ''}
        </div>
    </div>
    """


def _render_css():
    st.markdown(
        """
        <style>
        .est-page-intro {
            margin:0.1rem 0 1rem 0;
            color:#64748b;
            font-weight:650;
        }
        .est-create-card {
            border:1px solid rgba(99,102,241,0.24);
            background:linear-gradient(135deg,#f5f3ff,#eef2ff 48%,#ecfeff);
            border-radius:16px;
            padding:0.95rem 1rem;
            margin:0.7rem 0 1rem 0;
            box-shadow:0 10px 24px rgba(79,70,229,0.10);
        }
        .est-opportunity-card {
            position:relative;
            overflow:hidden;
            border-radius:18px;
            border:1px solid #e2e8f0;
            background:#fff;
            margin:0.8rem 0 0.45rem 0;
            box-shadow:0 14px 34px rgba(15,23,42,0.08);
            cursor:pointer;
            transition:transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
        }
        .est-opportunity-card:hover {
            transform:translateY(-2px);
            box-shadow:0 20px 42px rgba(15,23,42,0.13);
        }
        .est-opportunity-card.active {
            box-shadow:0 18px 42px rgba(15,23,42,0.13);
        }
        .est-card-ribbon {
            position:absolute;
            inset:0 auto 0 0;
            width:7px;
        }
        .est-card-main {
            display:grid;
            grid-template-columns:minmax(86px, 122px) minmax(0,1fr);
            gap:1rem;
            padding:1rem;
            align-items:center;
        }
        .est-opportunity-card.great { background:linear-gradient(135deg,#ecfdf5,#ffffff 54%,#f0fdf4); border-color:#a7f3d0; }
        .est-opportunity-card.good { background:linear-gradient(135deg,#ecfeff,#ffffff 54%,#eff6ff); border-color:#93c5fd; }
        .est-opportunity-card.ok { background:linear-gradient(135deg,#fffbeb,#ffffff 54%,#fff7ed); border-color:#fcd34d; }
        .est-opportunity-card.bad { background:linear-gradient(135deg,#fff1f2,#ffffff 54%,#fef2f2); border-color:#fda4af; }
        .est-opportunity-card.check { background:linear-gradient(135deg,#f5f3ff,#ffffff 54%,#f8fafc); border-color:#c4b5fd; }
        .est-opportunity-card.done { background:linear-gradient(135deg,#eef2ff,#ffffff 54%,#f1f5f9); border-color:#a5b4fc; }
        .est-opportunity-card.great .est-card-ribbon { background:#10b981; }
        .est-opportunity-card.good .est-card-ribbon { background:#06b6d4; }
        .est-opportunity-card.ok .est-card-ribbon { background:#f59e0b; }
        .est-opportunity-card.bad .est-card-ribbon { background:#f43f5e; }
        .est-opportunity-card.check .est-card-ribbon { background:#8b5cf6; }
        .est-opportunity-card.done .est-card-ribbon { background:#6366f1; }
        .est-img-frame {
            width:100%;
            aspect-ratio:0.72;
            border-radius:14px;
            background:rgba(255,255,255,0.7);
            border:1px solid rgba(148,163,184,0.35);
            display:flex;
            align-items:center;
            justify-content:center;
            overflow:hidden;
        }
        .est-img-frame.missing::before,
        .est-placeholder,
        .est-card-placeholder {
            content:"Image indisponible";
            color:#94a3b8;
            font-size:0.78rem;
            font-weight:850;
            text-align:center;
            padding:0.55rem;
        }
        .est-card-placeholder.compact {
            min-height:118px;
            border-radius:10px;
            border:1px solid #e2e8f0;
            background:#f8fafc;
            display:flex;
            align-items:center;
            justify-content:center;
            font-size:0.68rem;
        }
        .est-box-img {
            width:100%;
            height:100%;
            object-fit:contain;
            display:block;
        }
        .est-card-content h3 {
            display:flex;
            flex-wrap:wrap;
            gap:0.55rem;
            align-items:baseline;
            margin:0.4rem 0 0.15rem 0;
            color:#0f172a;
            font-size:clamp(1.05rem,2.2vw,1.45rem);
            line-height:1.12;
            overflow-wrap:anywhere;
        }
        .est-listing-link {
            display:inline-flex;
            align-items:center;
            border-radius:999px;
            padding:0.22rem 0.55rem;
            background:#dbeafe;
            color:#1d4ed8 !important;
            font-size:0.74rem;
            font-weight:900;
            text-decoration:none !important;
            white-space:nowrap;
        }
        .est-listing-link:hover {
            background:#bfdbfe;
        }
        .est-card-content p {
            margin:0 0 0.72rem 0;
            color:#475569;
            font-weight:750;
            overflow-wrap:anywhere;
        }
        .est-card-topline,
        .est-card-tags {
            display:flex;
            flex-wrap:wrap;
            gap:0.42rem;
            align-items:center;
        }
        .est-badge,
        .est-chip,
        .est-card-tags span {
            display:inline-flex;
            align-items:center;
            border-radius:999px;
            padding:0.22rem 0.55rem;
            font-size:0.74rem;
            font-weight:900;
            line-height:1.2;
        }
        .est-chip,
        .est-card-tags span {
            color:#475569;
            background:rgba(255,255,255,0.72);
            border:1px solid rgba(148,163,184,0.25);
        }
        .est-badge.great { background:#d1fae5; color:#047857; }
        .est-badge.good { background:#cffafe; color:#0e7490; }
        .est-badge.ok { background:#fef3c7; color:#92400e; }
        .est-badge.bad { background:#ffe4e6; color:#be123c; }
        .est-badge.check { background:#ede9fe; color:#6d28d9; }
        .est-badge.done { background:#e0e7ff; color:#4338ca; }
        .est-metrics,
        .est-detail-kpis {
            display:grid;
            grid-template-columns:repeat(5,minmax(0,1fr));
            gap:0.5rem;
        }
        .est-detail-kpis {
            grid-template-columns:repeat(4,minmax(0,1fr));
            margin:0.6rem 0 1rem 0;
        }
        .est-kpi {
            border-radius:13px;
            background:rgba(255,255,255,0.74);
            border:1px solid rgba(148,163,184,0.22);
            padding:0.62rem;
            min-width:0;
        }
        .est-detail-kpis .est-kpi {
            padding:0.86rem;
            box-shadow:0 10px 22px rgba(15,23,42,0.06);
        }
        .est-kpi span {
            display:block;
            color:#64748b;
            font-size:0.72rem;
            font-weight:850;
        }
        .est-detail-kpis .est-kpi span {
            font-size:0.78rem;
        }
        .est-kpi strong {
            display:block;
            color:#0f172a;
            margin-top:0.12rem;
            font-size:0.96rem;
            line-height:1.15;
            overflow-wrap:anywhere;
        }
        .est-detail-kpis .est-kpi strong {
            font-size:clamp(1.08rem,2.2vw,1.38rem);
        }
        .est-kpi.price { background:#fff7ed; border-color:#fdba74; }
        .est-kpi.price strong { color:#c2410c; }
        .est-kpi.value { background:#eff6ff; border-color:#93c5fd; }
        .est-kpi.value strong { color:#1d4ed8; }
        .est-kpi.percent { background:#ecfeff; border-color:#67e8f9; }
        .est-kpi.percent strong { color:#0e7490; }
        .est-kpi.margin-good { background:#ecfdf5; border-color:#86efac; }
        .est-kpi.margin-good strong { color:#15803d; }
        .est-kpi.margin-bad { background:#fff1f2; border-color:#fda4af; }
        .est-kpi.margin-bad strong { color:#be123c; }
        .est-kpi.margin-neutral { background:#f8fafc; border-color:#cbd5e1; }
        .est-kpi.buy { background:#eef2ff; border-color:#a5b4fc; }
        .est-kpi.buy strong { color:#4338ca; }
        .est-kpi.count { background:#f8fafc; border-color:#cbd5e1; }
        .est-kpi.type { background:#f5f3ff; border-color:#c4b5fd; }
        .est-kpi.type strong { color:#6d28d9; }
        .est-detail-shell {
            border:0;
            border-radius:0;
            background:transparent;
            padding:0;
            margin:0.15rem 0 1.05rem 0;
        }
        .est-detail-title {
            display:flex;
            flex-wrap:wrap;
            justify-content:space-between;
            align-items:flex-start;
            gap:0.7rem;
            margin-bottom:0.6rem;
        }
        .est-detail-title h3 {
            margin:0;
            font-size:clamp(1.1rem,2.4vw,1.55rem);
            color:#0f172a;
        }
        .est-tracked-card {
            height:100%;
            border:1px solid #e2e8f0;
            border-radius:16px;
            background:#fff;
            padding:0.75rem;
            box-shadow:0 10px 20px rgba(15,23,42,0.06);
        }
        .est-tracked-image {
            aspect-ratio:0.72;
            border-radius:12px;
            background:#f8fafc;
            display:flex;
            align-items:center;
            justify-content:center;
            overflow:hidden;
            border:1px solid #e2e8f0;
        }
        .est-tracked-image img {
            width:100%;
            height:100%;
            object-fit:contain;
            display:block;
        }
        .est-tracked-card h4 {
            margin:0.55rem 0 0.35rem 0;
            font-size:0.95rem;
            line-height:1.15;
            color:#0f172a;
            overflow-wrap:anywhere;
        }
        .est-suggestions-grid {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:0.55rem;
            margin:0.35rem 0 0.65rem 0;
        }
        .est-suggestion-card {
            display:grid;
            grid-template-columns:46px minmax(0,1fr);
            gap:0.5rem;
            align-items:center;
            border:1px solid #e2e8f0;
            border-radius:13px;
            background:linear-gradient(135deg,#ffffff,#f8fafc);
            padding:0.45rem;
            min-height:68px;
            box-shadow:0 7px 16px rgba(15,23,42,0.05);
        }
        .est-suggestion-img {
            width:46px;
            aspect-ratio:0.72;
            border-radius:9px;
            background:#f1f5f9;
            overflow:hidden;
            display:flex;
            align-items:center;
            justify-content:center;
            border:1px solid #e2e8f0;
        }
        .est-suggestion-img img {
            width:100%;
            height:100%;
            object-fit:contain;
            display:block;
        }
        .est-suggestion-placeholder {
            color:#94a3b8;
            font-size:0.62rem;
            font-weight:850;
        }
        .est-suggestion-copy {
            min-width:0;
        }
        .est-suggestion-copy strong,
        .est-suggestion-copy span,
        .est-suggestion-copy em {
            display:block;
            overflow:hidden;
            text-overflow:ellipsis;
            white-space:nowrap;
        }
        .est-suggestion-copy strong {
            color:#0f172a;
            font-size:0.82rem;
            line-height:1.12;
        }
        .est-suggestion-copy span {
            color:#64748b;
            font-size:0.72rem;
            font-weight:760;
            margin-top:0.1rem;
        }
        .est-suggestion-copy em {
            color:#6d28d9;
            font-size:0.68rem;
            font-style:normal;
            font-weight:850;
            margin-top:0.08rem;
        }
        .est-card-mini-grid {
            display:grid;
            grid-template-columns:1fr;
            gap:0.35rem;
            margin-top:0.55rem;
        }
        .est-card-mini-grid div {
            border-radius:10px;
            background:#f8fafc;
            padding:0.45rem;
        }
        .est-card-mini-grid span {
            display:block;
            color:#64748b;
            font-size:0.68rem;
            font-weight:850;
        }
        .est-card-mini-grid strong {
            display:block;
            color:#0f172a;
            font-size:0.86rem;
            line-height:1.15;
        }
        [data-testid="stElementContainer"]:has(.est-tracked-mini-marker) + div img,
        [data-testid="stElementContainer"]:has(.est-tracked-mini-marker) ~ div img {
            max-height:118px !important;
            object-fit:contain !important;
            border-radius:10px !important;
            background:#f8fafc !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-tracked-mini-marker) {
            gap:0.22rem !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-tracked-mini-marker) p {
            margin-bottom:0.08rem !important;
            font-size:0.72rem !important;
            line-height:1.12 !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-tracked-mini-marker) strong {
            font-size:0.78rem !important;
            line-height:1.12 !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-tracked-mini-marker) button {
            min-height:1.8rem !important;
            padding:0.18rem 0.35rem !important;
            font-size:0.72rem !important;
        }
        .est-toggle-marker {
            display:block;
            height:0;
            overflow:hidden;
        }
        [data-testid="stElementContainer"]:has(.est-toggle-marker) + div {
            height:0 !important;
            min-height:0 !important;
            overflow:hidden !important;
            margin:0 !important;
            padding:0 !important;
        }
        [data-testid="stElementContainer"]:has(.est-toggle-marker) + div button {
            opacity:0 !important;
            height:0 !important;
            min-height:0 !important;
            padding:0 !important;
            margin:0 !important;
            border:0 !important;
            pointer-events:none !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-page-intro) [data-testid="stForm"] {
            padding:0.65rem 0.75rem !important;
            border-radius:14px !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-page-intro) [data-testid="stForm"] [data-testid="stVerticalBlock"] {
            gap:0.35rem !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-page-intro) input,
        [data-testid="stVerticalBlock"]:has(.est-page-intro) textarea {
            min-height:2.25rem !important;
        }
        [data-testid="stVerticalBlock"]:has(.est-page-intro) label {
            margin-bottom:0.1rem !important;
        }
        @media(max-width:760px) {
            .est-card-main {
                grid-template-columns:72px minmax(0,1fr);
                gap:0.72rem;
                padding:0.78rem;
            }
            .est-metrics,
            .est-detail-kpis {
                grid-template-columns:repeat(2,minmax(0,1fr));
            }
            .est-kpi {
                padding:0.5rem;
            }
            .est-detail-shell {
                padding:0;
                border-radius:0;
            }
            .est-suggestions-grid {
                grid-template-columns:1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _build_opportunities(estimates, settings, estimation_totals_func):
    opportunities = []
    for estimate in estimates:
        totals = estimation_totals_func(estimate, settings)
        label, _ = _opportunity_label(totals)
        opportunities.append(
            {
                "estimate": estimate,
                "totals": totals,
                "label": label,
                "tone": _tone_for_status(label, estimate.get("status")),
                "score": _estimate_score(totals),
            }
        )
    opportunities.sort(key=lambda item: item["score"], reverse=True)
    return opportunities


def _bind_estimation_box_clicks(run_html_func):
    run_html_func(
        """
        <script>
        (function(){
            const doc = parent.document;
            function findToggleButton(uid){
                const marker = doc.querySelector('[data-est-toggle-marker="' + uid + '"]');
                if (!marker) return null;
                let node = marker.closest('[data-testid="stElementContainer"]');
                for (let i = 0; node && i < 8; i++) {
                    node = node.nextElementSibling;
                    const btn = node ? node.querySelector('button') : null;
                    if (btn) return btn;
                }
                return null;
            }
            function bind(){
                doc.querySelectorAll('[data-est-card-uid]').forEach(function(card){
                    if (card.dataset.estClickBound === '1') return;
                    card.dataset.estClickBound = '1';
                    card.addEventListener('click', function(event){
                        if (event.target.closest('a')) return;
                        const btn = findToggleButton(card.getAttribute('data-est-card-uid'));
                        if (btn) btn.click();
                    });
                    card.addEventListener('keydown', function(event){
                        if (event.key !== 'Enter' && event.key !== ' ') return;
                        event.preventDefault();
                        const btn = findToggleButton(card.getAttribute('data-est-card-uid'));
                        if (btn) btn.click();
                    });
                });
            }
            bind();
            setTimeout(bind, 250);
            setTimeout(bind, 900);
        })();
        </script>
        """,
        height=0,
    )


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
        render_page_header_func("Estimations", "Repérer vite les cartes à acheter", "📉"),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="est-page-intro">Des boîtes simples pour comparer une opportunité, regarder la cote, puis décider si ça vaut le coup.</p>',
        unsafe_allow_html=True,
    )
    _render_css()

    edata = load_estimations_func()
    settings = edata["settings"]
    estimates = edata["estimations"]

    st.markdown(
        '<div class="est-create-card"><strong>Créer une nouvelle estimation</strong><br><span>Ajoute un prix demandé, puis complète avec les cartes à comparer.</span></div>',
        unsafe_allow_html=True,
    )
    with st.expander("Créer une nouvelle estimation", expanded=not estimates):
        with st.form("new_estimation_box"):
            source_names = list(settings.get("sources", {}).keys()) or ["Vinted"]
            c1, c2, c3 = st.columns([2.2, 1, 1])
            new_est_name = c1.text_input("Nom de l'opportunité", placeholder="Ex: Dracaufeu 199/165")
            new_est_source = c2.selectbox(
                "Type d'achat",
                source_names,
                index=source_names.index(settings.get("default_source")) if settings.get("default_source") in source_names else 0,
            )
            new_est_price = c3.text_input("Prix demandé (€)", value="0,00")
            new_est_url = st.text_input("Lien annonce (optionnel)", placeholder="https://www.vinted.fr/items/...")
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
                        "listing_image_url": fetch_listing_preview_image_func(new_est_url) if new_est_url.strip() else "",
                        "status": "En cours",
                        "created_at": datetime.now().isoformat()[:10],
                        "cards": [],
                    }
                    edata["estimations"].append(estimate)
                    save_estimations_func(edata)
                    st.session_state["active_estimation_uid"] = estimate["uid"]
                    st.rerun()

    if not estimates:
        st.info("Aucune estimation pour le moment. Crée ta première boîte au-dessus.")
        return

    opportunities = _build_opportunities(estimates, settings, estimation_totals_func)

    f1, f2, f3 = st.columns([2, 1, 1])
    search = f1.text_input("Rechercher une estimation", placeholder="Nom, carte, source...", key="est_box_search")
    status_filter = f2.selectbox("État", ["Tous", "Très intéressant", "Intéressant", "Correct", "Trop cher", "À vérifier"], key="est_box_status_filter")
    max_budget_raw = f3.text_input("Budget max (€)", value="", placeholder="Ex: 120", key="est_box_budget")
    max_budget = parse_float_input_func(max_budget_raw, 0.0) if max_budget_raw.strip() else 0.0

    filtered = []
    query = normalize_name_func(search) if search else ""
    for item in opportunities:
        estimate = item["estimate"]
        totals = item["totals"]
        searchable = " ".join(
            [
                str(estimate.get("name", "")),
                str(estimate.get("source", "")),
                str(estimate.get("status", "")),
                " ".join(str(card.get("name", "")) for card in estimate.get("cards", [])),
            ]
        )
        if query and query not in normalize_name_func(searchable):
            continue
        if status_filter != "Tous" and item["label"] != status_filter:
            continue
        if max_budget > 0 and _safe_float(totals.get("seller_price")) > max_budget:
            continue
        filtered.append(item)

    if not filtered:
        st.info("Aucune estimation ne correspond aux filtres.")
        return

    active_uid = st.session_state.get("active_estimation_uid", "")

    for item in filtered:
        estimate = item["estimate"]
        totals = item["totals"]
        uid = estimate.get("uid")
        is_active = active_uid == uid
        st.markdown(_estimate_box_html(item, fp_func, proxy_img_func, active=is_active), unsafe_allow_html=True)
        st.markdown(f'<span class="est-toggle-marker" data-est-toggle-marker="{html.escape(str(uid), quote=True)}"></span>', unsafe_allow_html=True)
        if st.button("\u200b", key=f"toggle_est_box_{uid}"):
            st.session_state["active_estimation_uid"] = "" if is_active else uid
            st.rerun()

        if is_active:
            _render_open_estimation(
                estimate=estimate,
                totals=totals,
                settings=settings,
                edata=edata,
                uid=uid,
                save_estimations_func=save_estimations_func,
                add_estimation_card_func=add_estimation_card_func,
                ld_func=ld_func,
                sd_func=sd_func,
                fetch_listing_preview_image_func=fetch_listing_preview_image_func,
                cardmarket_search_url_func=cardmarket_search_url_func,
                search_in_cache_func=search_in_cache_func,
                img_with_fallback_func=img_with_fallback_func,
                fp_func=fp_func,
                normalize_name_func=normalize_name_func,
                parse_float_input_func=parse_float_input_func,
                new_uid_func=new_uid_func,
                is_mobile_mode_func=is_mobile_mode_func,
                ecd_func=ecd_func,
            )

    _bind_estimation_box_clicks(run_html_func)

    with st.expander("Réglages de rachat", expanded=False):
        st.caption("Ces pourcentages servent à calculer le prix maximum conseillé.")
        with st.form("estimation_settings_form_box"):
            new_sources = {}
            cols = st.columns(3)
            for col, (source_name, pct) in zip(cols, settings.get("sources", {}).items()):
                raw = col.text_input(f"{source_name} (%)", value=f"{float(pct):.0f}".replace(".", ","), key=f"est_setting_box_{source_name}")
                new_sources[source_name] = min(max(parse_float_input_func(raw, pct), 0.0), 100.0)
            source_names = list(new_sources.keys()) or ["Vinted"]
            default_source = st.selectbox(
                "Type par défaut",
                source_names,
                index=source_names.index(settings.get("default_source")) if settings.get("default_source") in source_names else 0,
                key="est_default_source_box",
            )
            if st.form_submit_button("Sauvegarder les règles"):
                edata["settings"]["sources"] = new_sources
                edata["settings"]["default_source"] = default_source
                save_estimations_func(edata)
                st.rerun()


def _render_open_estimation(
    *,
    estimate,
    totals,
    settings,
    edata,
    uid,
    save_estimations_func,
    add_estimation_card_func,
    ld_func,
    sd_func,
    fetch_listing_preview_image_func,
    cardmarket_search_url_func,
    search_in_cache_func,
    img_with_fallback_func,
    fp_func,
    normalize_name_func,
    parse_float_input_func,
    new_uid_func,
    is_mobile_mode_func,
    ecd_func,
):
    label, _ = _opportunity_label(totals)
    tone = _tone_for_status(label, estimate.get("status"))
    seller_price = _safe_float(totals.get("seller_price"))
    total_cote = _safe_float(totals.get("total_cote"))
    real_pct = _safe_float(totals.get("real_pct"))
    margin = _safe_float(totals.get("theoretical_margin"))
    card_count = sum(_safe_int(card.get("quantity")) for card in estimate.get("cards", []) or [])
    margin_accent = "margin-good" if margin > 0 else "margin-bad" if margin < 0 else "margin-neutral"

    st.markdown(
        f"""
        <div class="est-detail-shell">
        <div class="est-detail-title">
            <div>
                <span class="est-badge {tone}">{html.escape(label)}</span>
                <h3>{html.escape(str(estimate.get("name") or "Estimation"))}</h3>
            </div>
        </div>
        <div class="est-detail-kpis">
            {_kpi("Type d'achat", estimate.get("source") or "Vinted", accent="type")}
            {_kpi("Prix demandé", fp_func(seller_price) if seller_price > 0 else "À saisir", accent="price")}
            {_kpi("Cote totale", fp_func(total_cote), accent="value")}
            {_kpi("% cote", f"{real_pct:.1f}%" if real_pct else "À vérifier", accent="percent")}
            {_kpi("Marge", fp_func(margin) if total_cote else "À vérifier", accent=margin_accent)}
            {_kpi("Cartes", card_count, accent="count")}
            {_kpi("Rachat max", fp_func(totals.get("max_buy", 0.0)), accent="buy")}
            {_kpi("Collection", totals.get("collection_cards", 0), accent="count")}
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Ajouter une carte dans cette estimation", expanded=not estimate.get("cards")):
        a1, a2, a3, a4 = st.columns([2, 1, 1, 0.7])
        name_key = f"est_add_name_box_{uid}"
        number_key = f"est_add_number_box_{uid}"
        card_name = a1.text_input("Nom", placeholder="Ex: Marisson AR, Groudon EX magma", key=name_key)
        card_number = a2.text_input("Numéro", placeholder="199/165", key=number_key)
        card_cote = a3.text_input("Cote (€)", value="0,00", key=f"est_add_cote_box_{uid}")
        card_qty = a4.text_input("Qté", value="1", key=f"est_add_qty_box_{uid}")

        suggestions = _card_suggestions(card_name, card_number, search_in_cache_func, ecd_func, normalize_name_func)
        selected_match = st.session_state.get(f"est_selected_match_{uid}")
        if suggestions:
            st.caption("Suggestions depuis le cache cartes PokéStock")
            cols_per_row = 1 if is_mobile_mode_func() else 4
            for row_start in range(0, len(suggestions[:8]), cols_per_row):
                cols = st.columns(cols_per_row)
                for cidx, suggestion in enumerate(suggestions[row_start : row_start + cols_per_row]):
                    enriched = suggestion["card"]
                    with cols[cidx]:
                        st.markdown(_suggestion_html(enriched, img_with_fallback_func), unsafe_allow_html=True)
                        if st.button("Choisir", key=f"est_suggestion_pick_{uid}_{row_start + cidx}", width="stretch"):
                            st.session_state[name_key] = enriched.get("name", card_name) or card_name
                            st.session_state[number_key] = enriched.get("number", card_number) or card_number
                            st.session_state[f"est_selected_match_{uid}"] = suggestion["match"]
                            st.rerun()
        elif len(str(card_name or "").strip()) >= 3:
            st.caption("Aucun résultat fiable dans le cache pour cette recherche.")

        if selected_match:
            try:
                enriched_selected = ecd_func(selected_match[0], selected_match[1], lang="fr")
                st.success(
                    "Suggestion sélectionnée : "
                    f"{enriched_selected.get('name', card_name)}"
                    f"{' #' + str(enriched_selected.get('number')) if enriched_selected.get('number') else ''}"
                )
            except Exception:
                pass

        b1, b2 = st.columns([1, 2])
        card_condition = b1.selectbox("État", ["NM", "EX", "GD", "LP", "PL", "POOR"], key=f"est_add_condition_box_{uid}")
        card_specials = b2.multiselect(
            "Spécial",
            ["Reverse", "1ère Éd", "Japonaise", "Collection", "Scellé", "Stamp", "Promo", "Master Ball", "Poké Ball"],
            key=f"est_add_special_box_{uid}",
        )
        card_note = st.text_input("Note rapide", placeholder="Photo floue, coin abîmé...", key=f"est_add_note_box_{uid}")
        keep_collection = "Collection" in card_specials
        clean_specials = [tag for tag in card_specials if tag != "Collection"]
        if card_name.strip():
            cm_url = html.escape(cardmarket_search_url_func(card_name, card_number, card_condition, ", ".join(clean_specials)), quote=True)
            st.markdown(f'<a href="{cm_url}" target="_blank">Chercher la cote sur Cardmarket</a>', unsafe_allow_html=True)
        if st.button("Ajouter la carte", key=f"add_est_card_box_submit_{uid}", width="stretch"):
            if not card_name.strip():
                st.error("Nom requis.")
            else:
                matches = search_in_cache_func(card_name, card_number)
                chosen_match = selected_match
                if chosen_match:
                    matches = [chosen_match]
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
                    add_estimation_card_func(
                        estimate,
                        card_name,
                        card_number,
                        card_cote,
                        card_qty,
                        card_condition,
                        clean_specials,
                        card_note,
                        keep_collection,
                        matches[0] if matches else None,
                    )
                    st.session_state.pop(f"est_selected_match_{uid}", None)
                    save_estimations_func(edata)
                    st.rerun()

    pending = st.session_state.get(f"pending_est_choice_{uid}")
    if pending:
        st.warning(f"{len(pending.get('matches', []))} cartes possibles trouvées. Choisis la bonne.")
        cols = st.columns(2 if is_mobile_mode_func() else 4)
        for pidx, match in enumerate(pending.get("matches", [])):
            card_dict, set_name = match
            enriched = ecd_func(card_dict, set_name, lang="fr")
            with cols[pidx % len(cols)]:
                if enriched.get("image_url"):
                    st.markdown(
                        img_with_fallback_func(enriched.get("image_url", ""), enriched.get("image_url_en", ""), width="100%", style="border-radius:10px;"),
                        unsafe_allow_html=True,
                    )
                st.caption(f"{enriched.get('name','Carte')} · {enriched.get('set','')} · #{enriched.get('number','')}")
                if st.button("Choisir", key=f"pick_est_box_{uid}_{pidx}"):
                    add_estimation_card_func(
                        estimate,
                        pending["name"],
                        pending["number"],
                        pending["cote"],
                        pending["qty"],
                        pending["condition"],
                        pending["specials"],
                        pending["note"],
                        pending.get("is_collection", False),
                        match,
                    )
                    save_estimations_func(edata)
                    st.session_state.pop(f"pending_est_choice_{uid}", None)
                    st.rerun()
        if st.button("Annuler le choix", key=f"cancel_est_choice_box_{uid}"):
            st.session_state.pop(f"pending_est_choice_{uid}", None)
            st.rerun()

    st.markdown("#### Cartes suivies")
    cards = estimate.get("cards", []) or []
    if not cards:
        st.info("Aucune carte dans cette estimation pour le moment.")
    else:
        cols_per_row = 2 if is_mobile_mode_func() else 8
        for row_start in range(0, len(cards), cols_per_row):
            cols = st.columns(cols_per_row)
            for cidx, card in enumerate(cards[row_start : row_start + cols_per_row]):
                with cols[cidx]:
                    with st.container(border=True):
                        _render_tracked_card(card, estimate, fp_func, img_with_fallback_func)
                    if st.button("Retirer", key=f"del_est_card_box_{uid}_{card.get('uid')}"):
                        estimate["cards"] = [c for c in estimate.get("cards", []) if c.get("uid") != card.get("uid")]
                        save_estimations_func(edata)
                        st.rerun()

    with st.expander("Détails avancés et actions", expanded=False):
        if estimate.get("listing_url"):
            safe_url = html.escape(estimate.get("listing_url", ""), quote=True)
            st.markdown(f'<a href="{safe_url}" target="_blank">Ouvrir l’annonce</a>', unsafe_allow_html=True)
        with st.form(f"estimate_meta_box_{uid}"):
            m1, m2, m3 = st.columns([2, 1, 1])
            edit_name = m1.text_input("Nom", value=estimate.get("name", ""), key=f"est_name_box_{uid}")
            source_names = list(settings.get("sources", {}).keys()) or ["Vinted"]
            edit_source = m2.selectbox("Type", source_names, index=source_names.index(estimate.get("source")) if estimate.get("source") in source_names else 0, key=f"est_source_box_{uid}")
            status_options = ["En cours", "À surveiller", "Achetée", "Refusée"]
            edit_status = m3.selectbox("Statut", status_options, index=status_options.index(estimate.get("status", "En cours")) if estimate.get("status", "En cours") in status_options else 0, key=f"est_status_box_{uid}")
            n1, n2, n3 = st.columns([1, 1, 2])
            edit_seller_price = n1.text_input("Prix demandé (€)", value=f"{float(estimate.get('seller_price', 0.0) or 0.0):.2f}".replace(".", ","), key=f"est_seller_box_{uid}")
            edit_safety = n2.text_input("Marge sécurité (€)", value=f"{float(estimate.get('safety_eur', 0.0) or 0.0):.2f}".replace(".", ","), key=f"est_safety_box_{uid}")
            edit_url = n3.text_input("URL annonce", value=estimate.get("listing_url", ""), key=f"est_url_box_{uid}")
            if st.form_submit_button("Sauvegarder les détails"):
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
                st.rerun()

        st.write(
            {
                "cote_revente": fp_func(totals["total_cote"]),
                "cartes_collection": totals["collection_cards"],
                "rachat_max": fp_func(totals["max_buy"]),
                "source": estimate.get("source"),
                "date": estimate.get("created_at"),
            }
        )

        action_cols = st.columns(3)
        if action_cols[0].button("Créer un vrai lot", width="stretch", disabled=not estimate.get("cards") or bool(estimate.get("created_lot_uid")), key=f"create_real_lot_box_{uid}"):
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
                new_lot["cards"].append(
                    {
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
                    }
                )
            cd_real.setdefault("lots", []).append(new_lot)
            sd_func(cd_real)
            estimate["status"] = "Achetée"
            estimate["created_lot_uid"] = lot_uid
            save_estimations_func(edata)
            st.success("Lot créé dans le menu Lots.")
            st.rerun()
        if action_cols[1].button("Dupliquer", width="stretch", key=f"duplicate_est_box_{uid}"):
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
        if action_cols[2].button("Supprimer", width="stretch", key=f"delete_est_box_{uid}"):
            edata["estimations"] = [e for e in edata["estimations"] if e.get("uid") != uid]
            save_estimations_func(edata)
            st.session_state["active_estimation_uid"] = ""
            st.rerun()

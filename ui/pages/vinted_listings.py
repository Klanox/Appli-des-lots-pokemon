from __future__ import annotations

import json
import hashlib
import os
import re
from collections import Counter, OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps

from services.vinted_drops_service import (
    DROP_ITEM_STATUSES,
    add_card_to_drop,
    add_cards_to_drop,
    card_is_in_drop,
    create_drop,
    delete_drop,
    drop_item_status,
    drop_item_status_label,
    drop_card_key,
    filter_drop_cards,
    find_drop,
    launch_drop,
    load_vinted_drops,
    remove_card_from_drop,
    rename_drop,
    resolve_drop_cards_from_data,
    save_vinted_drops,
    set_drop_card_status,
    toggle_drop_card_posted,
    update_drop_channel,
)
from services.vinted_channels import VINTED_CHANNELS, normalize_vinted_channel
from services.vinted_listing_service import (
    filter_cards_for_listing,
    full_card_number,
    listing_price_text,
    normalize_search_text,
    prepare_listing,
    suggested_price,
)
from services.custom_card_image_service import resolve_custom_card_image
from services.card_identity import card_identity_fingerprint
from services.photo_recognition_service import (
    LANGUAGE_COMPATIBILITY_VERSION as PHOTO_LANGUAGE_COMPATIBILITY_VERSION,
    PROPOSAL_RELIABILITY_VERSION as PHOTO_PROPOSAL_RELIABILITY_VERSION,
    active_drop_candidates,
    analysis_summary as photo_analysis_summary,
    analyze_drop_photos,
    apply_recognition_statuses,
    browser_photo_upload_allowed,
    browser_upload_state,
    build_step4_payload,
    cancel_browser_upload,
    candidate_set_signature,
    confirm_grouping,
    effective_candidate as photo_effective_candidate,
    grouping_needs_confirmation as photo_grouping_needs_confirmation,
    group_review_reasons,
    list_ordered_photos,
    load_drop_photo_session,
    next_pending_subcard_index as photo_next_pending_subcard_index,
    pending_review_subcard_indexes as photo_pending_review_subcard_indexes,
    photo_window_signature,
    receive_browser_upload_batch,
    refresh_drop_analysis_candidates,
    resolve_historical_drop_candidate,
    restore_drop_analysis,
    search_drop_candidates,
    set_match_validation,
    stable_group_id as photo_stable_group_id,
    stable_subcard_id as photo_stable_subcard_id,
    unresolved_groups as photo_unresolved_groups,
    validation_for_match,
)
from ui.badges import card_stamp_label
from ui.photo_browser_upload import component_available as browser_upload_component_available
from ui.photo_browser_upload import render_browser_photo_upload
from ui.vinted_drop_virtual_grid import render_vinted_drop_virtual_grid


def _ui_text(value, fallback=""):
    text = str(value or fallback).strip()
    text = text.replace("\ufffd", "")
    text = re.sub(r"^\?+\s*", "", text)
    text = re.sub(r"\s+\?+\s*", " ", text)
    return " ".join(text.split())


def _card_image(card, proxy_img_func=None):
    candidates = []

    def add_candidate(value):
        value = str(value or "").strip()
        if not value or value == "__placeholder__":
            return
        if value.startswith(("card_images/", "card_images\\")) or os.path.exists(value):
            if not os.path.exists(value):
                return
        if value not in candidates:
            candidates.append(value)

    for key in ("manual_image_path", "manual_image_url", "resolved_collection_image_url"):
        add_candidate(card.get(key))
    for key in ("image_path", "local_image_path"):
        add_candidate(card.get(key))
    for key in ("image_url", "image_url_en"):
        add_candidate(card.get(key))

    try:
        add_candidate(resolve_custom_card_image(card))
    except Exception:
        pass

    if not candidates:
        return ""
    image = candidates[0]
    if proxy_img_func:
        try:
            return proxy_img_func(image)
        except Exception:
            return image
    return image


def _lot_name(lot):
    return _ui_text(lot.get("name") or lot.get("nom"), "Lot sans nom")


def _card_number(card):
    return full_card_number(card)


def _card_set(card):
    return _ui_text(card.get("set") or card.get("serie") or card.get("extension"), "")


def _card_condition(card):
    return _ui_text(card.get("condition") or card.get("etat"), "")


def _card_display_title(card):
    number = _card_number(card)
    name = _ui_text(card.get("name"), "Carte Pokémon")
    return f"{name} {number}".strip()


def _card_key(card):
    return "::".join(
        [
            str(card.get("lot_uid") or ""),
            str(card.get("card_uid") or ""),
            str(card.get("lot_idx") or 0),
            str(card.get("card_idx") or 0),
            str(card.get("name") or ""),
            str(card.get("number") or ""),
        ]
    )


def _card_uid(card, lot_idx, card_idx):
    return str(card.get("uid") or card.get("card_uid") or f"{lot_idx}:{card_idx}")


def _inject_vinted_styles():
    st.markdown(
        """
<style>
.ps-vinted-subtitle {
    color:#64748b;
    font-size:.86rem;
    margin:-.2rem 0 .75rem;
}
.ps-vinted-step-nav {
    display:flex;
    flex-wrap:wrap;
    gap:.48rem;
    margin:.15rem 0 .9rem;
}
.ps-vinted-pill {
    display:inline-flex;
    align-items:center;
    gap:.35rem;
    padding:.26rem .58rem;
    border-radius:999px;
    background:#eef2ff;
    color:#3730a3;
    font-weight:800;
    font-size:.76rem;
}
.ps-vinted-muted-panel {
    border:1px solid rgba(129,140,248,.22);
    border-radius:12px;
    background:linear-gradient(135deg, rgba(248,250,252,.96), rgba(238,242,255,.62));
    padding:1rem;
    color:#475569;
    font-weight:700;
}
.ps-vinted-kpi-grid {
    display:grid;
    grid-template-columns:repeat(4, minmax(0, 1fr));
    gap:.65rem;
    margin:.65rem 0 .9rem;
}
.ps-vinted-kpi {
    border:1px solid rgba(129,140,248,.22);
    border-radius:12px;
    background:#fff;
    padding:.75rem;
}
.ps-vinted-kpi span {
    display:block;
    color:#64748b;
    font-size:.72rem;
    font-weight:800;
}
.ps-vinted-kpi strong {
    display:block;
    color:#0f172a;
    font-size:1.05rem;
    margin-top:.2rem;
}
.ps-recognition-identity-title {
    color:#111827;
    font-size:1.06rem;
    font-weight:850;
    line-height:1.25;
    margin:.05rem 0;
}
.ps-recognition-identity-meta {
    color:#64748b;
    font-size:.82rem;
    font-weight:650;
    margin:0 0 .32rem;
}
.ps-recognition-photo-caption {
    color:#64748b;
    font-size:.69rem;
    line-height:1.2;
    text-align:center;
    margin-top:.1rem;
}
.ps-recognition-toolbar-label {
    color:#111827;
    font-size:.88rem;
    font-weight:820;
    text-align:center;
    padding:.45rem 0;
    white-space:nowrap;
}
.ps-recognition-focus-header {
    color:#111827;
    font-size:1rem;
    font-weight:850;
    line-height:2.4rem;
    white-space:nowrap;
}
@media (max-width: 640px) {
    .ps-recognition-toolbar-label { font-size:.8rem; }
    .ps-recognition-identity-title { font-size:1rem; }
    .ps-recognition-focus-header { font-size:.92rem; line-height:1.4; margin-bottom:.45rem; }
}
.ps-photo-state {
    border:1px solid #e2e8f0;
    border-radius:10px;
    background:#fff;
    padding:1rem 1.05rem .85rem;
    margin:.35rem 0 .7rem;
}
.ps-photo-state-head {
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    gap:1rem;
    margin-bottom:.25rem;
}
.ps-photo-state-title {
    color:#111827;
    font-size:1.03rem;
    font-weight:850;
    line-height:1.3;
}
.ps-photo-state-copy {
    color:#64748b;
    font-size:.82rem;
    line-height:1.45;
    margin-top:.16rem;
}
.ps-photo-state-badge {
    flex:0 0 auto;
    display:inline-flex;
    align-items:center;
    gap:.3rem;
    border:1px solid #bbf7d0;
    border-radius:999px;
    background:#f0fdf4;
    color:#15803d;
    padding:.24rem .58rem;
    font-size:.74rem;
    font-weight:800;
    white-space:nowrap;
}
.ps-photo-state-badge.stale {
    border-color:#fed7aa;
    background:#fff7ed;
    color:#c2410c;
}
.ps-photo-summary-line {
    display:flex;
    align-items:center;
    flex-wrap:wrap;
    gap:.42rem 1rem;
    margin:.72rem 0 .08rem;
    color:#475569;
    font-size:.82rem;
}
.ps-photo-summary-line span {
    display:inline-flex;
    align-items:baseline;
    gap:.24rem;
    white-space:nowrap;
}
.ps-photo-summary-line strong {
    color:#111827;
    font-size:1rem;
    font-weight:850;
}
.ps-photo-summary-line .auto strong { color:#15803d; }
.ps-photo-summary-line .review strong { color:#c2410c; }
.ps-photo-summary-line .fail strong { color:#be123c; }
.ps-photo-review-header {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:.75rem;
    margin:.7rem 0 .18rem;
}
.ps-photo-review-title {
    color:#111827;
    font-size:1.05rem;
    font-weight:850;
    line-height:1.25;
}
.ps-photo-status-badge {
    display:inline-flex;
    align-items:center;
    flex:0 0 auto;
    gap:.28rem;
    border:1px solid transparent;
    border-radius:999px;
    padding:.24rem .55rem;
    font-size:.73rem;
    font-weight:850;
    line-height:1.1;
    white-space:nowrap;
}
.ps-photo-status-badge.success {
    border-color:#bbf7d0;
    background:#f0fdf4;
    color:#15803d;
}
.ps-photo-status-badge.warning {
    border-color:#fed7aa;
    background:#fff7ed;
    color:#c2410c;
}
.ps-photo-status-badge.danger {
    border-color:#fecaca;
    background:#fef2f2;
    color:#be123c;
}
.ps-photo-status-callout {
    margin:.58rem 0 .7rem;
    border:1px solid transparent;
    border-radius:8px;
    padding:.48rem .62rem;
    font-size:.78rem;
    font-weight:760;
    line-height:1.35;
}
.ps-photo-status-callout.success {
    border-color:#bbf7d0;
    background:#f0fdf4;
    color:#166534;
}
.ps-photo-status-callout.warning {
    border-color:#fed7aa;
    background:#fff7ed;
    color:#9a3412;
}
.ps-photo-status-callout.danger {
    border-color:#fecaca;
    background:#fef2f2;
    color:#991b1b;
}
.ps-photo-review-marker,
.ps-photo-review-action-marker { display:none; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.ps-photo-review-marker.success) {
    border-left:3px solid #16a34a !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.ps-photo-review-marker.warning) {
    border-left:3px solid #f97316 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.ps-photo-review-marker.danger) {
    border-left:3px solid #dc2626 !important;
}
[data-testid="stHorizontalBlock"]:has(.ps-photo-review-action-marker) [data-testid="stButton"] > button {
    min-height:2.5rem !important;
}
@media (max-width: 640px) {
    .ps-photo-state { padding:.85rem; }
    .ps-photo-state-head { flex-direction:column; gap:.5rem; }
    .ps-photo-summary-line { gap:.42rem .72rem; }
    .ps-photo-review-header { align-items:flex-start; }
    .ps-photo-status-badge { margin-top:.08rem; }
}
.ps-vinted-drop-head {
    padding:.1rem .08rem;
    margin:0;
}
.ps-vinted-drop-head strong {
    display:block;
    color:#0f172a;
    font-size:1.02rem;
    line-height:1.2;
}
.ps-vinted-drop-head span {
    color:#64748b;
    font-size:.82rem;
    font-weight:700;
}
.ps-vinted-drop-meta {
    display:flex;
    align-items:center;
    flex-wrap:wrap;
    gap:.42rem;
    margin-top:.34rem;
}
.ps-vinted-channel {
    display:inline-flex;
    align-items:center;
    border-radius:999px;
    padding:.16rem .52rem;
    border:1px solid #c7d2fe;
    background:#eef2ff;
    color:#3730a3 !important;
    font-size:.72rem !important;
    font-weight:900 !important;
}
.ps-vinted-channel-dexify {
    border-color:#bfdbfe;
    background:#eff6ff;
    color:#1d4ed8 !important;
}
.ps-vinted-channel-pokedeal {
    border-color:#ddd6fe;
    background:#f5f3ff;
    color:#6d28d9 !important;
}
.ps-vinted-channel-choppetacarte {
    border-color:#fed7aa;
    background:#fff7ed;
    color:#c2410c !important;
}
.ps-vinted-section-title {
    display:flex;
    align-items:center;
    gap:.42rem;
    margin:.85rem 0 .45rem;
    color:#0f172a;
    font-size:.98rem;
    font-weight:900;
}
.ps-vinted-section-title::before,
.ps-vinted-lot-title::before {
    content:"";
    width:.38rem;
    height:.38rem;
    border-radius:999px;
    background:#7c3aed;
    box-shadow:0 0 0 4px rgba(124,58,237,.12);
}
.ps-vinted-lot-title {
    display:flex;
    align-items:center;
    gap:.42rem;
    margin:1rem 0 .45rem;
    color:#0f172a;
    font-size:.92rem;
    font-weight:900;
}
.ps-vinted-card {
    min-height:100%;
    display:flex;
    flex-direction:column;
    gap:.42rem;
    border:1px solid rgba(148,163,184,.26);
    border-radius:10px;
    background:#fff;
    padding:.5rem;
    box-shadow:0 3px 12px rgba(15,23,42,.06);
}
.ps-vinted-img {
    width:100%;
    aspect-ratio:.72;
    border-radius:9px;
    background:#f8fafc;
    border:1px solid rgba(203,213,225,.9);
    overflow:hidden;
    display:flex;
    align-items:center;
    justify-content:center;
    color:#64748b;
    font-size:.72rem;
    font-weight:800;
    text-align:center;
}
.ps-vinted-img img {
    width:100%;
    height:100%;
    display:block;
    object-fit:cover;
}
.ps-vinted-name {
    min-height:2.25rem;
    color:#0f172a;
    font-size:.82rem;
    font-weight:900;
    line-height:1.22;
    display:-webkit-box;
    -webkit-line-clamp:2;
    -webkit-box-orient:vertical;
    overflow:hidden;
}
.ps-vinted-meta {
    color:#64748b;
    font-size:.7rem;
    line-height:1.18;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}
.ps-vinted-price {
    color:#334155;
    font-size:.74rem;
    font-weight:800;
}
.ps-vinted-badge {
    display:inline-flex;
    width:max-content;
    max-width:100%;
    border-radius:999px;
    padding:.18rem .45rem;
    background:#eef2ff;
    color:#3730a3;
    font-size:.65rem;
    font-weight:900;
}
.ps-vinted-badge.ok {
    background:#dcfce7;
    color:#166534;
}
.ps-vinted-badge.warn {
    background:#fee2e2;
    color:#991b1b;
}
.ps-vinted-badge.duplicate {
    background:#ffedd5;
    color:#c2410c;
    border:1px solid #fed7aa;
}
.ps-vinted-badge.stamp {
    background:#fdf2f8;
    color:#db2777;
    border:1px solid #fbcfe8;
}
.ps-vinted-badge.status-to-photograph {
    background:#e0f2fe;
    color:#0369a1;
    border:1px solid #bae6fd;
}
.ps-vinted-badge.status-needs-review {
    background:#ffedd5;
    color:#c2410c;
    border:1px solid #fed7aa;
}
.ps-vinted-badge.status-sorted {
    background:#ede9fe;
    color:#6d28d9;
    border:1px solid #ddd6fe;
}
.ps-vinted-badge.status-to-prepare {
    background:#f3e8ff;
    color:#7e22ce;
    border:1px solid #e9d5ff;
}
.ps-vinted-badge.status-draft-ready {
    background:#e0e7ff;
    color:#4338ca;
    border:1px solid #c7d2fe;
}
.ps-vinted-badge.status-online {
    background:#dcfce7;
    color:#15803d;
    border:1px solid #bbf7d0;
}
.ps-vinted-badge.status-sold {
    background:#bbf7d0;
    color:#166534;
    border:1px solid #86efac;
}
.ps-vinted-actions {
    margin-top:auto;
}
.ps-vinted-qty-line {
    display:flex;
    align-items:center;
    justify-content:center;
    gap:.28rem;
    color:#475569;
    font-size:.72rem;
    font-weight:800;
}
[data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_"] {
    gap:10px !important;
    align-items:stretch !important;
}
[data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_"] > [data-testid="stLayoutWrapper"] {
    flex:0 0 calc((100% - 50px) / 6) !important;
    max-width:calc((100% - 50px) / 6) !important;
    min-width:0 !important;
}
[data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_drop_cards_"] > [data-testid="stLayoutWrapper"] {
    flex:0 0 calc((100% - 70px) / 8) !important;
    max-width:calc((100% - 70px) / 8) !important;
}
div[class*="st-key-vinted_grid_"] button {
    min-height:30px !important;
    padding:.2rem .4rem !important;
}
div[class*="st-key-vinted_drop_step_"] button {
    min-height:42px !important;
    padding:.48rem .7rem !important;
    border-radius:999px !important;
    border:1px solid rgba(129,140,248,.34) !important;
    background:linear-gradient(135deg, rgba(255,255,255,.98), rgba(248,250,255,.92)) !important;
    color:#1e293b !important;
    font-weight:850 !important;
    box-shadow:0 2px 8px rgba(15,23,42,.035) !important;
}
div[class*="st-key-vinted_drop_step_"] button:hover {
    border-color:rgba(124,58,237,.52) !important;
    background:linear-gradient(135deg, rgba(245,243,255,1), rgba(238,242,255,.95)) !important;
    color:#4c1d95 !important;
}
div[class*="st-key-vinted_drop_step_"] button p {
    white-space:normal !important;
    line-height:1.12 !important;
}
div[class*="st-key-create_vinted_drop"] button,
div[class*="st-key-vinted_add"] button,
div[class*="st-key-draft_ready_drop_card"] button,
div[class*="st-key-launch_drop"] button {
    background:#6d5dfc !important;
    border-color:#6d5dfc !important;
    color:#fff !important;
}
div[class*="st-key-create_vinted_drop"] button:hover,
div[class*="st-key-vinted_add"] button:hover,
div[class*="st-key-draft_ready_drop_card"] button:hover,
div[class*="st-key-launch_drop"] button:hover {
    background:#5b4bea !important;
    border-color:#5b4bea !important;
    color:#fff !important;
}
div[class*="st-key-vinted_drop_drawer_header_"] button {
    display:flex !important;
    align-items:center !important;
    justify-content:flex-start !important;
    text-align:left !important;
    min-height:48px !important;
    padding:.55rem .82rem !important;
    border:1px solid rgba(129,140,248,.28) !important;
    border-radius:12px !important;
    background:linear-gradient(135deg, rgba(255,255,255,.98), rgba(248,250,255,.96)) !important;
    color:#0f172a !important;
    font-weight:800 !important;
    box-shadow:0 2px 8px rgba(15,23,42,.035) !important;
}
div[class*="st-key-vinted_drop_drawer_header_"] button:hover {
    border-color:rgba(99,102,241,.42) !important;
    background:linear-gradient(135deg, rgba(255,255,255,1), rgba(238,242,255,.72)) !important;
}
div[class*="st-key-vinted_drop_drawer_header_"] {
    margin:.35rem 0 .28rem !important;
}
.ps-vinted-progress-panel {
    border:1px solid rgba(129,140,248,.24);
    border-radius:14px;
    background:linear-gradient(135deg, rgba(255,255,255,.98), rgba(245,243,255,.78));
    padding:.82rem .95rem;
    margin:.45rem 0 .75rem;
    box-shadow:0 8px 24px rgba(79,70,229,.07);
}
.ps-vinted-progress-main {
    color:#0f172a;
    font-size:1.05rem;
    font-weight:950;
    line-height:1.2;
}
.ps-vinted-progress-sub {
    color:#64748b;
    font-size:.82rem;
    font-weight:800;
    margin-top:.18rem;
}
.ps-vinted-current-card {
    border:1px solid rgba(129,140,248,.22);
    border-radius:14px;
    background:#fff;
    padding:.8rem;
    box-shadow:0 8px 22px rgba(15,23,42,.055);
}
.ps-vinted-current-title {
    color:#0f172a;
    font-size:1.05rem;
    font-weight:950;
    line-height:1.2;
}
.ps-vinted-current-meta {
    color:#64748b;
    font-size:.84rem;
    font-weight:760;
    margin-top:.2rem;
}
.ps-analytics-title {
    padding:.08rem 0 .18rem;
}
.ps-analytics-title strong {
    display:block;
    color:#111827;
    font-size:1.28rem;
    font-weight:850;
    letter-spacing:0;
}
.ps-analytics-title span,
.ps-analytics-section-heading p {
    display:block;
    margin:.16rem 0 0;
    color:#6b7280;
    font-size:.78rem;
    font-weight:650;
}
.ps-analytics-kpi-grid {
    display:grid;
    grid-template-columns:repeat(4,minmax(0,1fr));
    gap:.7rem;
    margin:.58rem 0 .4rem;
}
.ps-analytics-kpi,
.ps-analytics-stat,
.ps-analytics-surface,
.ps-analytics-section {
    border:1px solid #e5e7eb;
    border-radius:9px;
    background:#fff;
}
.ps-analytics-kpi {
    min-height:82px;
    padding:.68rem .8rem;
    border-top:3px solid #d1d5db;
}
.ps-analytics-kpi--violet { border-top-color:#6d28d9; }
.ps-analytics-kpi--success { border-top-color:#16a34a; }
.ps-analytics-kpi--blue { border-top-color:#2563eb; }
.ps-analytics-kpi--orange { border-top-color:#f97316; }
.ps-analytics-kpi--violet { background:#fbf9ff; }
.ps-analytics-kpi--success { background:#f7fcf8; }
.ps-analytics-kpi--blue { background:#f8fbff; }
.ps-analytics-kpi--orange { background:#fffaf5; }
.ps-analytics-kpi--violet strong { color:#5b21b6; }
.ps-analytics-kpi--success strong { color:#15803d; }
.ps-analytics-kpi--blue strong { color:#1d4ed8; }
.ps-analytics-kpi--orange strong { color:#c2410c; }
[class*="st-key-drop_analytics_chart_mode"] [data-testid="stSegmentedControl"] button,
[class*="st-key-drop_analytics_range"] [data-testid="stSegmentedControl"] button {
    border-color:#e5e7eb !important;
    background:#fff !important;
    color:#4b5563 !important;
    font-weight:700 !important;
}
[class*="st-key-drop_analytics_chart_mode"] [data-testid="stSegmentedControl"] button[aria-checked="true"],
[class*="st-key-drop_analytics_chart_mode"] [data-testid="stSegmentedControl"] button[aria-pressed="true"],
[class*="st-key-drop_analytics_range"] [data-testid="stSegmentedControl"] button[aria-checked="true"],
[class*="st-key-drop_analytics_range"] [data-testid="stSegmentedControl"] button[aria-pressed="true"] {
    border-color:#8b5cf6 !important;
    background:#f5f3ff !important;
    color:#6d28d9 !important;
    font-weight:850 !important;
    box-shadow:inset 0 0 0 1px rgba(109,40,217,.08) !important;
}
.ps-analytics-kpi span,
.ps-analytics-stat span {
    display:block;
    color:#6b7280;
    font-size:.73rem;
    font-weight:750;
}
.ps-analytics-kpi strong {
    display:block;
    margin-top:.24rem;
    color:#111827;
    font-size:1.48rem;
    font-weight:850;
    letter-spacing:0;
}
.ps-analytics-stat-grid {
    display:grid;
    grid-template-columns:repeat(5,minmax(0,1fr));
    gap:.55rem;
    margin:0 0 .68rem;
}
.ps-analytics-stat {
    padding:.46rem .6rem;
}
.ps-analytics-stat strong {
    display:block;
    margin-top:.14rem;
    color:#1f2937;
    font-size:.94rem;
    font-weight:800;
}
.ps-analytics-stat-grid--stacked {
    grid-template-columns:repeat(2,minmax(0,1fr));
    margin:0;
}
.ps-analytics-surface,
.ps-analytics-section {
    padding:.76rem .84rem;
    margin:.12rem 0 .68rem;
}
.ps-analytics-section-heading {
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    gap:.75rem;
    margin-bottom:.52rem;
}
.ps-analytics-section-heading h3 {
    margin:0;
    color:#111827;
    font-size:1rem;
    font-weight:850;
    line-height:1.2;
}
.ps-analytics-revenue-total {
    display:flex;
    align-items:baseline;
    justify-content:space-between;
    padding:.2rem 0 .6rem;
}
.ps-analytics-revenue-total span { color:#374151; font-size:.84rem; font-weight:750; }
.ps-analytics-revenue-total strong { color:#111827; font-size:1.38rem; font-weight:850; }
.ps-analytics-breakdown {
    display:grid;
    grid-template-columns:1fr auto;
    gap:.36rem .8rem;
    border-top:1px solid #eef0f3;
    padding-top:.68rem;
    color:#6b7280;
    font-size:.78rem;
}
.ps-analytics-breakdown strong { color:#374151; font-weight:800; }
.ps-analytics-revenue-bar { display:flex; height:7px; margin-top:.62rem; overflow:hidden; border-radius:999px; background:#eef0f3; }
.ps-analytics-revenue-bar i { display:block; height:100%; background:#6d28d9; }
.ps-analytics-revenue-bar b { display:block; height:100%; background:#f59e0b; }
.ps-analytics-stock-counts {
    display:flex;
    gap:.78rem;
    flex-wrap:wrap;
    color:#6b7280;
    font-size:.77rem;
    margin:.42rem 0 .82rem;
}
.ps-analytics-stock-counts strong { color:#111827; font-size:1.02rem; }
.ps-analytics-progress {
    height:8px;
    overflow:hidden;
    border-radius:999px;
    background:#eceff3;
}
.ps-analytics-progress i {
    display:block;
    height:100%;
    border-radius:inherit;
    background:#16a34a;
}
.ps-analytics-progress-label { margin-top:.42rem; color:#166534; font-size:.76rem; font-weight:800; }
.ps-analytics-timeline {
    display:grid;
    grid-template-columns:repeat(5,minmax(0,1fr));
    gap:.22rem;
}
.ps-analytics-timeline--compact { grid-template-columns:repeat(5,minmax(0,1fr)); }
.ps-analytics-timeline-item {
    position:relative;
    min-width:0;
    padding:.08rem .28rem .08rem .48rem;
    border-left:2px solid #d8b4fe;
}
.ps-analytics-timeline-item:first-child { border-left-color:#6d28d9; }
.ps-analytics-timeline-item span,
.ps-analytics-timeline-item strong { display:block; }
.ps-analytics-timeline-item span { color:#6b7280; font-size:.65rem; font-weight:700; }
.ps-analytics-timeline-item strong { color:#111827; font-size:.73rem; font-weight:850; line-height:1.2; margin-top:.08rem; }
.ps-analytics-charts-heading { margin:.2rem 0 .35rem; }
.ps-analytics-charts-heading .ps-analytics-section-heading { margin-bottom:0; }
.ps-analytics-checkpoints { position:relative; display:grid; grid-template-columns:repeat(8,minmax(0,1fr)); gap:.34rem; padding:.18rem 0; }
.ps-analytics-checkpoints:before { position:absolute; top:.45rem; right:3%; left:3%; height:1px; background:#e5e7eb; content:""; }
.ps-analytics-checkpoint { position:relative; min-width:0; padding:.7rem .38rem .36rem; border:0; background:#fff; }
.ps-analytics-checkpoint:before { position:absolute; top:.15rem; left:.38rem; width:.58rem; height:.58rem; border:2px solid #c4b5fd; border-radius:50%; background:#fff; content:""; }
.ps-analytics-checkpoint span { display:block; color:#6b7280; font-size:.66rem; font-weight:800; }
.ps-analytics-checkpoint strong { display:block; overflow:hidden; color:#111827; font-size:.84rem; font-weight:850; margin-top:.1rem; text-overflow:ellipsis; white-space:nowrap; }
.ps-analytics-checkpoint small { display:block; color:#6b7280; font-size:.64rem; font-weight:650; margin-top:.04rem; }
.ps-analytics-table-note { flex:0 0 auto; color:#6d28d9; font-size:.7rem; font-weight:800; }
.ps-analytics-bands { display:grid; gap:.42rem; }
.ps-analytics-band-header { display:grid; grid-template-columns:58px 1fr minmax(80px,1.2fr) 42px 68px; gap:.55rem; margin-bottom:.08rem; color:#6b7280; font-size:.65rem; font-weight:800; }
.ps-analytics-band-header span:nth-child(3),.ps-analytics-band-header span:nth-child(4) { text-align:right; }
.ps-analytics-band { display:grid; grid-template-columns:58px 1fr minmax(80px,1.2fr) 42px 68px; align-items:center; gap:.55rem; color:#4b5563; font-size:.72rem; }
.ps-analytics-band > strong { color:#111827; font-size:.75rem; }
.ps-analytics-band > span { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ps-analytics-band > div { height:6px; overflow:hidden; border-radius:999px; background:#eceff3; }
.ps-analytics-band > div i { display:block; height:100%; border-radius:inherit; background:#f59e0b; }
.ps-analytics-band > div i.good { background:#16a34a; }
.ps-analytics-band b { color:#374151; font-size:.72rem; text-align:right; }
.ps-analytics-band em { color:#111827; font-size:.73rem; font-style:normal; font-weight:800; text-align:right; }
.ps-analytics-remaining-list { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.48rem; }
.ps-analytics-remaining-row { display:flex; align-items:flex-start; justify-content:space-between; gap:.48rem; min-width:0; padding:.45rem .54rem; border:1px solid #eef0f3; border-radius:8px; }
.ps-analytics-remaining-row span { min-width:0; }
.ps-analytics-remaining-row strong { display:block; overflow:hidden; color:#111827; font-size:.76rem; font-weight:800; text-overflow:ellipsis; white-space:nowrap; }
.ps-analytics-remaining-row small { display:block; margin-top:.13rem; color:#6b7280; font-size:.65rem; font-weight:650; white-space:nowrap; }
.ps-analytics-remaining-row b { color:#111827; font-size:.88rem; font-weight:850; white-space:nowrap; }
.ps-analytics-highlights { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0; overflow:hidden; border:1px solid #e5e7eb; border-radius:8px; }
.ps-analytics-highlight { min-width:0; padding:.48rem .6rem; border-right:1px solid #e5e7eb; background:#fff; }
.ps-analytics-highlight:last-child { border-right:0; }
.ps-analytics-highlight span,.ps-analytics-highlight strong,.ps-analytics-highlight b { display:block; }
.ps-analytics-highlight span { color:#6b7280; font-size:.68rem; font-weight:750; }
.ps-analytics-highlight strong { min-height:0; margin:.12rem 0; overflow:hidden; color:#111827; font-size:.76rem; font-weight:850; line-height:1.25; text-overflow:ellipsis; white-space:nowrap; }
.ps-analytics-highlight b { color:#6d28d9; font-size:.78rem; font-weight:850; }
.ps-analytics-insights { border-left:3px solid #6d28d9; }
.ps-analytics-insights ul { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.55rem; margin:0; padding:0; color:#374151; font-size:.74rem; line-height:1.35; list-style:none; }
.ps-analytics-insights li { min-width:0; }
.ps-analytics-negotiation { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:0; overflow:hidden; border:1px solid #e5e7eb; border-radius:8px; }
.ps-analytics-negotiation-item { min-width:0; padding:.45rem .5rem; border-right:1px solid #e5e7eb; }
.ps-analytics-negotiation-item:last-child { border-right:0; }
.ps-analytics-negotiation-item span,.ps-analytics-negotiation-item strong { display:block; }
.ps-analytics-negotiation-item span { color:#6b7280; font-size:.65rem; font-weight:750; }
.ps-analytics-negotiation-item strong { overflow:hidden; margin-top:.12rem; color:#111827; font-size:.8rem; font-weight:850; text-overflow:ellipsis; white-space:nowrap; }
.ps-analytics-negotiation-bar { display:flex; height:5px; margin-top:.52rem; overflow:hidden; border-radius:999px; background:#f1f3f5; }
.ps-analytics-negotiation-bar i { display:block; height:100%; background:#16a34a; }
.ps-analytics-negotiation-bar b { display:block; height:100%; background:#f59e0b; }
.ps-analytics-note { display:flex; align-items:center; gap:.55rem; color:#6b7280; font-size:.8rem; }
.ps-analytics-note strong { color:#374151; }
.ps-analytics-empty { color:#6b7280; font-size:.78rem; padding:.5rem 0; }
.ps-analytics-empty-state { padding:1.2rem; text-align:center; }
.ps-analytics-empty-state h3 { margin:0; color:#111827; font-size:1rem; }
.ps-analytics-empty-state p { margin:.35rem 0 0; color:#6b7280; font-size:.8rem; }
.ps-analytics-compare-head,
.ps-analytics-compare-row {
    display:grid;
    grid-template-columns:1.15fr repeat(3,minmax(0,1fr));
    gap:.55rem;
    align-items:center;
}
.ps-analytics-compare-head { padding:.1rem .45rem .36rem; color:#6b7280; font-size:.66rem; font-weight:800; }
.ps-analytics-compare-row { padding:.5rem .45rem; border-top:1px solid #eef0f3; color:#4b5563; font-size:.76rem; }
.ps-analytics-compare-row strong { color:#111827; font-weight:800; }
.ps-analytics-compare-row b { color:#6d28d9; font-weight:800; }
@media (max-width:768px) {
    .ps-vinted-drop-head {
        padding:.08rem;
    }
    .ps-vinted-card {
        padding:.42rem;
        border-radius:9px;
    }
    .ps-vinted-name {
        font-size:.76rem;
        min-height:2.05rem;
    }
    .ps-vinted-meta,
    .ps-vinted-price {
        font-size:.66rem;
    }
    .ps-vinted-kpi-grid {
        grid-template-columns:repeat(2, minmax(0, 1fr));
    }
    .ps-analytics-kpi-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .ps-analytics-stat-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .ps-analytics-timeline { grid-template-columns:repeat(3,minmax(0,1fr)); }
    .ps-analytics-checkpoints { grid-template-columns:repeat(4,minmax(0,1fr)); }
    .ps-analytics-remaining-list { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .ps-analytics-highlights { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .ps-analytics-highlight:nth-child(2) { border-right:0; }
    .ps-analytics-highlight:nth-child(n+3) { border-top:1px solid #e5e7eb; }
    .ps-analytics-insights ul { grid-template-columns:1fr; }
    .ps-analytics-negotiation { grid-template-columns:repeat(3,minmax(0,1fr)); }
    .ps-analytics-negotiation-item:nth-child(3) { border-right:0; }
    .ps-analytics-negotiation-item:nth-child(n+4) { border-top:1px solid #e5e7eb; }
    .ps-analytics-compare-head,
    .ps-analytics-compare-row { grid-template-columns:1.05fr repeat(3,minmax(0,1fr)); gap:.35rem; font-size:.7rem; }
    [data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_"] {
        gap:8px !important;
    }
    [data-testid="stHorizontalBlock"][class*="st-key-vinted_grid_"] > [data-testid="stLayoutWrapper"] {
        flex:0 0 calc((100% - 8px) / 2) !important;
        max-width:calc((100% - 8px) / 2) !important;
    }
}
@media (max-width:480px) {
    .ps-analytics-title strong { font-size:1.12rem; }
    .ps-analytics-kpi { min-height:82px; padding:.7rem; }
    .ps-analytics-kpi strong { font-size:1.22rem; }
    .ps-analytics-surface,.ps-analytics-section { padding:.8rem; }
    .ps-analytics-timeline { grid-template-columns:1fr; }
    .ps-analytics-checkpoints { grid-template-columns:1fr; gap:0; padding:0; }
    .ps-analytics-checkpoints:before { top:.42rem; bottom:.42rem; left:.42rem; width:1px; height:auto; }
    .ps-analytics-checkpoint { padding:.1rem .25rem .58rem 1.15rem; }
    .ps-analytics-checkpoint:before { top:.14rem; left:.15rem; }
    .ps-analytics-band { grid-template-columns:52px 1fr 62px; gap:.4rem; }
    .ps-analytics-band-header { grid-template-columns:52px 1fr 62px; gap:.4rem; }
    .ps-analytics-band > span,.ps-analytics-band > b { display:none; }
    .ps-analytics-band-header span:nth-child(2),.ps-analytics-band-header span:nth-child(3) { display:none; }
    .ps-analytics-band-header span:nth-child(4) { grid-column:2; text-align:right; }
    .ps-analytics-band-header span:nth-child(5) { grid-column:3; text-align:right; }
    .ps-analytics-remaining-list { grid-template-columns:1fr; }
    .ps-analytics-negotiation { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .ps-analytics-negotiation-item:nth-child(2) { border-right:0; }
    .ps-analytics-negotiation-item:nth-child(3) { border-top:1px solid #e5e7eb; border-right:1px solid #e5e7eb; }
    .ps-analytics-negotiation-item:nth-child(n+4) { border-top:1px solid #e5e7eb; }
    .ps-analytics-compare-head,
    .ps-analytics-compare-row { grid-template-columns:1fr repeat(3,minmax(0,1fr)); font-size:.66rem; }
}
</style>
""",
        unsafe_allow_html=True,
    )


def _inject_vinted_analytics_compact_styles():
    """Tighten only the analytics step without changing the shared workflow shell."""
    st.markdown(
        """
<style>
.main .block-container { padding-top:.65rem !important; }
.ps-app-header { padding:.45rem 0 !important; margin-bottom:.35rem !important; }
.ps-app-title { font-size:1.15rem !important; }
.ps-app-tagline { font-size:.72rem !important; margin-top:.04rem !important; }
.ps-page-header { padding:.46rem .72rem !important; margin-bottom:.38rem !important; }
.ps-page-icon { width:2rem !important; height:2rem !important; font-size:.96rem !important; }
.ps-page-title, h2.ps-page-title { font-size:1.18rem !important; }
.ps-page-subtitle { font-size:.76rem !important; margin-top:.08rem !important; }
div[class*="st-key-vinted_drop_step_"] button { min-height:36px !important; padding:.34rem .56rem !important; }
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ps-vinted-drop-head) { margin-top:-.16rem; margin-bottom:-.16rem; }
</style>
""",
        unsafe_allow_html=True,
    )

def _html_escape(value):
    import html

    return html.escape(str(value or ""), quote=True)


def _grid_columns(mobile):
    return 2 if mobile else 6


def _drop_cards_grid_columns(mobile):
    return 2 if mobile else 8


DROP_WORKFLOW_STEPS = (
    "Choix des cartes",
    "Tri des photos",
    "Vérification",
    "Création des annonces",
    "Analyse des drops",
)


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except Exception:
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(value or default)
    except Exception:
        return int(default)


def _parse_dt(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _duration_label(delta):
    if delta is None:
        return "N/A"
    total_seconds = max(0, int(delta.total_seconds()))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"J+{days}" + (f" {hours}h" if hours else "")
    if hours:
        return f"{hours}h{minutes:02d}"
    return f"{minutes} min"


def _duration_delta_label(delta):
    if delta is None:
        return "N/A"
    sign = "-" if delta.total_seconds() < 0 else "+"
    return f"{sign}{_duration_label(abs(delta))}"


def _drop_step_label(index, step):
    return f"Étape {index + 1} · {step}"


def _render_drop_step_nav(mobile):
    if st.session_state.get("vinted_drop_step") not in DROP_WORKFLOW_STEPS:
        st.session_state["vinted_drop_step"] = DROP_WORKFLOW_STEPS[0]
    active_step = st.session_state.get("vinted_drop_step", DROP_WORKFLOW_STEPS[0])
    active_index = DROP_WORKFLOW_STEPS.index(active_step)
    st.markdown(
        f"""
<style>
div[class*="st-key-vinted_drop_step_{active_index}"] button {{
    background:linear-gradient(135deg, #6d5dfc, #7c3aed) !important;
    border-color:#6d5dfc !important;
    color:#fff !important;
    box-shadow:0 10px 22px rgba(109,93,252,.26) !important;
}}
div[class*="st-key-vinted_drop_step_{active_index}"] button:hover {{
    background:linear-gradient(135deg, #5b4bea, #6d28d9) !important;
    border-color:#5b4bea !important;
    color:#fff !important;
}}
</style>
""",
        unsafe_allow_html=True,
    )
    indexed_steps = list(enumerate(DROP_WORKFLOW_STEPS))
    rows = [indexed_steps[i : i + 2] for i in range(0, len(indexed_steps), 2)] if mobile else [indexed_steps]
    for row in rows:
        cols = st.columns(len(row))
        for col, (idx, step) in zip(cols, row):
            with col:
                if st.button(_drop_step_label(idx, step), key=f"vinted_drop_step_{idx}", width="stretch"):
                    if st.session_state.get("vinted_drop_step") != step:
                        st.session_state["vinted_drop_step"] = step
                        st.rerun()
    return st.session_state.get("vinted_drop_step", DROP_WORKFLOW_STEPS[0])


def _drop_channel_class(channel):
    channel = normalize_vinted_channel(channel)
    if channel == "Dexify":
        return "ps-vinted-channel-dexify"
    if channel == "Pokédeal":
        return "ps-vinted-channel-pokedeal"
    if channel == "ChoppeTaCarte":
        return "ps-vinted-channel-choppetacarte"
    return ""


def _drop_status_badge_class(status):
    return "status-" + str(status or "").replace("_", "-")


def _drawer_open_key(scope):
    return f"vinted_drop_drawer_open_{scope}"


def _render_drop_drawer_header(scope, label, default_open=True):
    state_key = _drawer_open_key(scope)
    if state_key not in st.session_state:
        st.session_state[state_key] = bool(default_open)
    is_open = bool(st.session_state.get(state_key))
    chevron = "▾" if is_open else "▸"
    badge_css = ""
    badge_match = re.search(r"\(([^()]*)\)\s*$", str(label or ""))
    if badge_match:
        badge = _html_escape(badge_match.group(1))
        label = str(label or "")[: badge_match.start()].strip()
        badge_css = (
            f'div[class*="st-key-vinted_drop_drawer_toggle_{scope}"] button p::after {{'
            f'content:"{badge}";display:inline-flex;align-items:center;margin-left:.55rem;'
            f'padding:.12rem .48rem;border-radius:999px;background:#eef2ff;color:#3730a3;'
            f'border:1px solid #c7d2fe;font-size:.72rem;font-weight:900;'
            f'}}'
        )
    st.markdown(
        f"""
<style>
div[class*="st-key-vinted_drop_drawer_toggle_{scope}"] button::after {{
    content:"{chevron}";
    margin-left:auto;
    color:#4f46e5;
    font-size:1rem;
    font-weight:900;
}}
div[class*="st-key-vinted_drop_drawer_toggle_{scope}"] button p {{
    display:flex;
    align-items:center;
    flex:1;
    margin:0;
}}
{badge_css}
</style>
""",
        unsafe_allow_html=True,
    )
    with st.container(key=f"vinted_drop_drawer_header_{scope}"):
        if st.button(str(label or ""), key=f"vinted_drop_drawer_toggle_{scope}", width="stretch"):
            is_open = not is_open
            st.session_state[state_key] = is_open
    return is_open


def _chunked(items, size):
    items = list(items or [])
    for idx in range(0, len(items), max(1, size)):
        yield idx // max(1, size), items[idx : idx + max(1, size)]


def _group_cards_by_lot(cards):
    grouped = OrderedDict()
    for card in cards or []:
        key = str(card.get("lot_uid") or card.get("lot_idx") or card.get("lot_name") or "lot")
        if key not in grouped:
            grouped[key] = {"name": card.get("lot_name", "Lot"), "cards": []}
        grouped[key]["cards"].append(card)
    return grouped.values()


def _limit_key(scope):
    return f"vinted_{scope}_limit"


def _query_sig_key(scope):
    return f"vinted_{scope}_query_sig"


def _visible_limit(scope, query, mobile, total):
    key = _limit_key(scope)
    sig_key = _query_sig_key(scope)
    signature = str(query or "")
    initial = 12 if mobile else 24
    if st.session_state.get(sig_key) != signature:
        st.session_state[sig_key] = signature
        st.session_state[key] = min(initial, total)
    current = int(st.session_state.get(key, initial) or initial)
    current = min(max(initial, current), total)
    st.session_state[key] = current
    return current


def _show_more(scope, mobile, total, label="Afficher plus"):
    key = _limit_key(scope)
    current = int(st.session_state.get(key, 0) or 0)
    if current >= total:
        return
    step = 12 if mobile else 24
    if st.button(label, key=f"vinted_show_more_{scope}", width="stretch"):
        st.session_state[key] = min(total, current + step)
        st.rerun()


def _qty_state_key(scope, card):
    return f"vinted_qty_{scope}_{_safe_js_id(card.get('_listing_key') or drop_card_key(card))}"


def _selected_quantity(scope, card):
    key = _qty_state_key(scope, card)
    max_qty = max(1, int(card.get("available_qty", 1) or 1))
    current = int(st.session_state.get(key, 1) or 1)
    current = min(max(1, current), max_qty)
    st.session_state[key] = current
    return current, max_qty, key


def _adjust_quantity(scope, card, delta):
    current, max_qty, key = _selected_quantity(scope, card)
    st.session_state[key] = min(max(1, current + delta), max_qty)


def _card_static_html(
    card,
    proxy_img_func,
    fp_func,
    *,
    badge="",
    badge_class="",
    duplicate_badge="",
    unavailable=False,
    drop_card=False,
    drop_price_display="added",
):
    img = _card_image(card, proxy_img_func)
    if img:
        img_html = f'<img src="{_html_escape(img)}" loading="lazy" decoding="async" alt="">'
    else:
        img_html = "Image<br>absente"
    meta_bits = []
    if _card_set(card):
        meta_bits.append(_card_set(card))
    if _card_number(card):
        meta_bits.append(f"#{_card_number(card)}")
    if drop_card and card.get("lot_name"):
        meta_bits.append(str(card.get("lot_name")))
    meta = " · ".join(meta_bits)
    price = suggested_price(card)
    price_label = fp_func(price) if price else "Prix à définir"
    stock_label = f"Stock x{int(card.get('available_qty', 0) or 0)}"
    if drop_card:
        qty = max(1, int(card.get("drop_quantity", card.get("quantity", 1)) or 1))
        added_price = float(card.get("price_at_add", 0) or 0)
        current = suggested_price(card)
        if drop_price_display == "current":
            display_price = current if current else added_price
            price_label = f"{fp_func(display_price)} × {qty}"
        else:
            price_label = f"Ajout {fp_func(added_price)} × {qty}"
            if current and abs(current - added_price) >= 0.01:
                price_label += f" · Actuel {fp_func(current)}"
        stock_label = "Disponible" if not unavailable else "Indisponible"
    badge_html = ""
    if badge:
        cls = badge_class or ("warn" if unavailable else ("ok" if "POST" in badge.upper() else ""))
        badge_html = f'<span class="ps-vinted-badge {cls}">{_html_escape(badge)}</span>'
    duplicate_html = (
        f'<span class="ps-vinted-badge duplicate">{_html_escape(duplicate_badge)}</span>'
        if duplicate_badge
        else ""
    )
    stamp_label = card_stamp_label(card)
    stamp_html = f'<span class="ps-vinted-badge stamp">{_html_escape(stamp_label)}</span>' if stamp_label else ""
    return f"""
<div class="ps-vinted-card">
  <div class="ps-vinted-img">{img_html}</div>
  <div class="ps-vinted-name">{_html_escape(_card_display_title(card))}</div>
  <div class="ps-vinted-meta">{_html_escape(meta)}</div>
  <div class="ps-vinted-price">{_html_escape(price_label)} · {_html_escape(stock_label)}</div>
  {stamp_html}
  {badge_html}
  {duplicate_html}
</div>
"""


def _available_cards(d, card_available_qty_func, is_collection_system_lot_func, *, include_unavailable=False):
    options = []
    for lot_idx, lot in enumerate(d.get("lots", [])):
        if is_collection_system_lot_func(lot):
            continue
        lot_name = _lot_name(lot)
        lot_uid = str(lot.get("uid") or lot.get("lot_uid") or f"lot-{lot_idx}")
        for card_idx, card in enumerate(lot.get("cards", [])):
            try:
                available_qty = int(card_available_qty_func(card))
            except Exception:
                available_qty = int(card.get("quantity", 0) or 0)
            if available_qty <= 0 and not include_unavailable:
                continue

            item = dict(card)
            item["available_qty"] = available_qty
            item["lot_name"] = lot_name
            item["lot_idx"] = lot_idx
            item["card_idx"] = card_idx
            item["lot_uid"] = lot_uid
            item["card_uid"] = _card_uid(card, lot_idx, card_idx)
            item["_listing_key"] = _card_key(item)
            item["_drop_card_key"] = drop_card_key(item)
            item["identity_fingerprint"] = card_identity_fingerprint(item)
            options.append(item)
    return options


def _sync_listing_text(selected_cards, listing_type, fp_func):
    prepared = prepare_listing(selected_cards, listing_type)
    signature = prepared["signature"]
    if signature != st.session_state.get("vinted_listing_signature"):
        st.session_state["vinted_listing_title"] = prepared["title"]
        st.session_state["vinted_listing_description"] = prepared["description"]
        st.session_state["vinted_listing_price"] = listing_price_text(selected_cards, fp_func)
        st.session_state["vinted_listing_signature"] = signature
    return prepared


def _reset_vinted_form():
    for key in (
        "vinted_search_query",
        "vinted_drop_add_query",
        "vinted_drop_filter_query",
        "vinted_selected_keys",
        "vinted_listing_title",
        "vinted_listing_description",
        "vinted_listing_price",
        "vinted_listing_signature",
        "vinted_copy_buffer",
    ):
        st.session_state.pop(key, None)
    for key in list(st.session_state.keys()):
        if str(key).startswith("vinted_multi_pick_"):
            st.session_state.pop(key, None)
    st.rerun()


def _select_cards(cards):
    st.session_state["vinted_selected_keys"] = [card["_listing_key"] for card in cards]
    st.session_state.pop("vinted_listing_signature", None)


def _active_drop_id(drops_data):
    drops = drops_data.get("drops", [])
    current = st.session_state.get("vinted_active_drop_id")
    if current and any(drop.get("id") == current for drop in drops):
        return current
    if drops:
        st.session_state["vinted_active_drop_id"] = drops[0].get("id")
        return drops[0].get("id")
    return ""


def _render_thumb(card, proxy_img_func, width=92):
    img = _card_image(card, proxy_img_func)
    if img:
        st.image(img, width=width)
    else:
        st.markdown(
            f"<div style='width:{width}px;height:{int(width*1.38)}px;border:1px solid #d8e2ef;"
            "border-radius:8px;display:flex;align-items:center;justify-content:center;"
            "color:#64748b;background:#f8fafc;font-size:.75rem;text-align:center;'>Image<br>absente</div>",
            unsafe_allow_html=True,
        )


def _card_details_text(card, fp_func):
    lines = []
    meta = []
    if _card_number(card):
        meta.append(f"#{_card_number(card)}")
    if _card_set(card):
        meta.append(_card_set(card))
    if _card_condition(card):
        meta.append(_card_condition(card))
    if meta:
        lines.append(" - ".join(meta))
    lines.append(f"Prix PokéStock : {fp_func(suggested_price(card)) if suggested_price(card) else 'à définir'}")
    lines.append(f"Lot : {card.get('lot_name', 'Lot')}")
    lines.append(f"Disponible : x{int(card.get('available_qty', 0) or 0)}")
    return lines


def _drop_choice_options(drops_data):
    return {drop.get("name", "Drop sans nom"): drop.get("id") for drop in drops_data.get("drops", [])}


def _card_with_drop_quantity(card, quantity):
    item = dict(card)
    item["drop_quantity"] = max(1, int(quantity or 1))
    return item


def _card_identity(card):
    return str(card.get("identity_fingerprint") or card_identity_fingerprint(card) or "")


def _drop_identity_counts(drop):
    counts = Counter()
    for ref in (drop or {}).get("cards", []) or []:
        fingerprint = _card_identity(ref)
        if fingerprint:
            counts[fingerprint] += 1
    return counts


def _drop_duplicate_extra_count(drop):
    return sum(count - 1 for count in _drop_identity_counts(drop).values() if count > 1)


def _candidate_duplicate_count(drop, card):
    fingerprint = _card_identity(card)
    if not fingerprint:
        return 0
    count = _drop_identity_counts(drop).get(fingerprint, 0)
    if card_is_in_drop(drop, card):
        count -= 1
    return max(0, count)


def _add_card_to_drop_action(drops_data, drop_id, card, quantity=1):
    added, duplicate = add_card_to_drop(drops_data, drop_id, _card_with_drop_quantity(card, quantity))
    if added:
        save_vinted_drops(drops_data)
        st.success("Carte ajoutée au drop.")
        st.rerun()
    if duplicate:
        st.warning("Cette carte est déjà dans ce drop.")


def _component_batch(result):
    if result is None:
        return {}
    batch = result.get("batch") if isinstance(result, dict) else getattr(result, "batch", None)
    return batch if isinstance(batch, dict) else {}


def _drop_grid_processed_batches_key(drop_id):
    return f"vinted_drop_processed_batches_{drop_id}"


def _drop_grid_committed_selection_token_key(drop_id):
    return f"vinted_drop_committed_selection_token_{drop_id}"


def _drop_grid_committed_selection_token(drop_id):
    return int(st.session_state.get(_drop_grid_committed_selection_token_key(drop_id), 0) or 0)


def _mark_drop_grid_batch_committed(drop_id, batch_id):
    key = _drop_grid_processed_batches_key(drop_id)
    batches = [str(value) for value in st.session_state.get(key, []) if value]
    batch_id = str(batch_id or "")
    if batch_id and batch_id not in batches:
        batches.append(batch_id)
    st.session_state[key] = batches[-100:]
    token_key = _drop_grid_committed_selection_token_key(drop_id)
    st.session_state[token_key] = _drop_grid_committed_selection_token(drop_id) + 1
    st.session_state["vinted_drop_grid_scroll_token"] = int(st.session_state.get("vinted_drop_grid_scroll_token", 0) or 0) + 1


def _process_drop_selection_batch(drops_data, active_drop, available_cards, batch):
    drop_id = active_drop.get("id") if active_drop else ""
    selections = batch.get("selections") if isinstance(batch, dict) else []
    batch_id = str(batch.get("id") or "") if isinstance(batch, dict) else ""
    if not drop_id or not batch_id or not isinstance(selections, list) or not selections:
        return 0, 0, 0
    processed_batches = {str(value) for value in st.session_state.get(_drop_grid_processed_batches_key(drop_id), [])}
    if batch_id in processed_batches:
        return 0, 0, 0
    card_by_key = {
        card.get("_drop_card_key") or drop_card_key(card): card
        for card in available_cards or []
    }
    added_count = 0
    duplicate_count = 0
    skipped_count = 0
    cards_to_add = []

    seen_keys = set()
    for selection in selections:
        if not isinstance(selection, dict):
            continue
        card_key = str(selection.get("card_key") or "")
        if not card_key or card_key in seen_keys:
            continue
        seen_keys.add(card_key)
        card = card_by_key.get(card_key)
        if not card:
            skipped_count += 1
            continue
        if card_is_in_drop(active_drop, card):
            duplicate_count += 1
            continue
        try:
            quantity = int(selection.get("quantity", 1) or 1)
        except Exception:
            quantity = 1
        max_qty = max(1, int(card.get("available_qty", 1) or 1))
        quantity = min(max(1, quantity), max_qty)
        cards_to_add.append(_card_with_drop_quantity(card, quantity))

    if cards_to_add:
        added_count, duplicate_count_from_service = add_cards_to_drop(drops_data, drop_id, cards_to_add)
        duplicate_count += duplicate_count_from_service
    _mark_drop_grid_batch_committed(drop_id, batch_id)
    if added_count:
        save_vinted_drops(drops_data)
    return len(seen_keys), added_count, duplicate_count + skipped_count


def _render_quantity_stepper(scope, card):
    current, max_qty, _ = _selected_quantity(scope, card)
    if max_qty <= 1:
        return current
    with st.container(horizontal=True, key=f"vinted_qty_line_{scope}_{_safe_js_id(card.get('_listing_key'))}"):
        st.markdown('<span class="ps-vinted-qty-line">Qté</span>', unsafe_allow_html=True)
        st.button(
            "−",
            key=f"vinted_qty_minus_{scope}_{_safe_js_id(card.get('_listing_key'))}",
            disabled=current <= 1,
            on_click=_adjust_quantity,
            args=(scope, card, -1),
        )
        st.markdown(f'<span class="ps-vinted-qty-line">{current}</span>', unsafe_allow_html=True)
        st.button(
            "＋",
            key=f"vinted_qty_plus_{scope}_{_safe_js_id(card.get('_listing_key'))}",
            disabled=current >= max_qty,
            on_click=_adjust_quantity,
            args=(scope, card, 1),
        )
    return current


def _render_available_card(
    card,
    *,
    scope,
    listing_type,
    selected_keys,
    drops_data,
    active_drop_id,
    proxy_img_func,
    fp_func,
    mode,
):
    key = card["_listing_key"]
    active_drop = find_drop(drops_data, active_drop_id) if active_drop_id else None
    already = bool(active_drop and card_is_in_drop(active_drop, card))
    duplicate_count = _candidate_duplicate_count(active_drop, card) if active_drop else 0
    duplicate_badge = ""
    if duplicate_count:
        duplicate_badge = f"⚠ Déjà présent ×{duplicate_count}" if duplicate_count > 1 else "⚠ Déjà présent dans le drop"
    st.markdown(
        _card_static_html(card, proxy_img_func, fp_func, duplicate_badge=duplicate_badge),
        unsafe_allow_html=True,
    )
    quantity = _render_quantity_stepper(scope, card)

    if mode == "classic":
        if listing_type == "Carte seule":
            if st.button("Sélectionner", key=f"vinted_pick_single_{scope}_{key}", width="stretch"):
                _select_cards([card])
                st.rerun()
        else:
            checkbox_key = f"vinted_multi_pick_{scope}_{key}"
            checked = st.checkbox("Sélectionner", key=checkbox_key, value=key in selected_keys)
            if checked and key not in selected_keys:
                selected_keys.append(key)
                st.session_state["vinted_selected_keys"] = selected_keys
                st.session_state.pop("vinted_listing_signature", None)
            elif not checked and key in selected_keys:
                selected_keys.remove(key)
                st.session_state["vinted_selected_keys"] = selected_keys
                st.session_state.pop("vinted_listing_signature", None)

    if active_drop_id:
        if st.button(
            "Déjà dans le drop" if already else "Ajouter au drop",
            key=f"vinted_add_to_drop_{scope}_{active_drop_id}_{key}",
            width="stretch",
            disabled=already,
        ):
            _add_card_to_drop_action(drops_data, active_drop_id, card, quantity)


def _render_grouped_available_grid(
    cards,
    *,
    scope,
    listing_type,
    selected_keys,
    drops_data,
    active_drop_id,
    proxy_img_func,
    fp_func,
    mobile,
    mode,
):
    cols_count = _grid_columns(mobile)
    for group_index, group in enumerate(_group_cards_by_lot(cards)):
        group_cards = group["cards"]
        if not group_cards:
            continue
        st.markdown(
            f'<div class="ps-vinted-lot-title">{_html_escape(group["name"])} · {len(group_cards)} carte(s)</div>',
            unsafe_allow_html=True,
        )
        for row_index, row in _chunked(group_cards, cols_count):
            with st.container(horizontal=True, key=f"vinted_grid_{scope}_{group_index}_{row_index}"):
                for card in row:
                    with st.container(key=f"vinted_card_{scope}_{_safe_js_id(card.get('_listing_key'))}"):
                        _render_available_card(
                            card,
                            scope=scope,
                            listing_type=listing_type,
                            selected_keys=selected_keys,
                            drops_data=drops_data,
                            active_drop_id=active_drop_id,
                            proxy_img_func=proxy_img_func,
                            fp_func=fp_func,
                            mode=mode,
                        )


def _filter_cards_for_display(cards, query):
    if not str(query or "").strip():
        return list(cards or [])
    return filter_cards_for_listing(cards, query, limit=len(cards or []))


def _drop_total_value(drop, available_cards=None):
    if available_cards is not None:
        resolved_cards, missing_cards = resolve_drop_cards_from_data(drop, available_cards)
        total = 0.0
        for card in resolved_cards:
            price = suggested_price(card)
            quantity = max(1, _safe_int(card.get("drop_quantity", card.get("quantity", 1)), 1))
            total += _safe_float(price) * quantity
        for ref in missing_cards:
            total += _safe_float(ref.get("price_at_add")) * max(1, _safe_int(ref.get("quantity"), 1))
        return total

    total = 0.0
    for ref in drop.get("cards", []) or []:
        try:
            price = float(ref.get("price_at_add", 0) or 0)
        except Exception:
            price = 0.0
        try:
            quantity = int(ref.get("quantity", 1) or 1)
        except Exception:
            quantity = 1
        total += price * max(1, quantity)
    return total


def _drop_grid_groups(cards, proxy_img_func, fp_func):
    groups = []
    for group in _group_cards_by_lot(cards):
        payload_cards = []
        for card in group.get("cards", []) or []:
            img = _card_image(card, proxy_img_func)
            price = suggested_price(card)
            payload_cards.append(
                {
                    "card_key": card.get("_drop_card_key") or drop_card_key(card),
                    "card_uid": card.get("card_uid", ""),
                    "lot_uid": card.get("lot_uid", ""),
                    "lot_idx": card.get("lot_idx", 0),
                    "card_idx": card.get("card_idx", 0),
                    "name": _ui_text(card.get("name"), "Carte"),
                    "set": _card_set(card),
                    "number": _card_number(card),
                    "price": price,
                    "price_label": fp_func(price) if price else "Prix à définir",
                    "stock": int(card.get("available_qty", 0) or 0),
                    "image_url": img,
                    "stamp_label": card_stamp_label(card),
                    "duplicate_fingerprint": _card_identity(card),
                }
            )
        if payload_cards:
            first = payload_cards[0]
            groups.append(
                {
                    "lot_uid": first.get("lot_uid") or group.get("name"),
                    "lot_idx": first.get("lot_idx", 0),
                    "lot_name": group.get("name", "Lot"),
                    "cards": payload_cards,
                }
            )
    return groups


def _drop_scroll_top_token(active_drop_id, query):
    signature = f"{active_drop_id or ''}::{str(query or '')}"
    if st.session_state.get("vinted_drop_grid_signature") != signature:
        st.session_state["vinted_drop_grid_signature"] = signature
        st.session_state["vinted_drop_grid_scroll_token"] = int(st.session_state.get("vinted_drop_grid_scroll_token", 0) or 0) + 1
    return st.session_state.get("vinted_drop_grid_scroll_token", 0)


def _render_search_result(card, listing_type, selected_keys, proxy_img_func, fp_func, drops_data, active_drop_id, mobile=False):
    key = card["_listing_key"]
    with st.container(border=True):
        if mobile:
            img_col, info_col = st.columns([0.75, 2.25])
            action_col = st.container()
        else:
            img_col, info_col, action_col = st.columns([0.75, 2.5, 1.25])
        with img_col:
            _render_thumb(card, proxy_img_func, width=76 if mobile else 86)
        with info_col:
            st.markdown(f"**{_card_display_title(card)}**")
            for line in _card_details_text(card, fp_func):
                st.caption(line)
        with action_col:
            if listing_type == "Carte seule":
                if st.button("Sélectionner", key=f"vinted_pick_single_{key}", width="stretch"):
                    _select_cards([card])
                    st.rerun()
            else:
                checkbox_key = f"vinted_multi_pick_{key}"
                checked = st.checkbox("Sélectionner", key=checkbox_key, value=key in selected_keys)
                if checked and key not in selected_keys:
                    selected_keys.append(key)
                    st.session_state["vinted_selected_keys"] = selected_keys
                    st.session_state.pop("vinted_listing_signature", None)
                elif not checked and key in selected_keys:
                    selected_keys.remove(key)
                    st.session_state["vinted_selected_keys"] = selected_keys
                    st.session_state.pop("vinted_listing_signature", None)

            if active_drop_id:
                active_drop = find_drop(drops_data, active_drop_id)
                already = bool(active_drop and card_is_in_drop(active_drop, card))
                if st.button(
                    "Déjà dans le drop" if already else "Ajouter au drop",
                    key=f"vinted_add_result_to_drop_{active_drop_id}_{key}",
                    width="stretch",
                    disabled=already,
                ):
                    _add_card_to_drop_action(drops_data, active_drop_id, card)


def _safe_js_id(key):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(key))


def _copy_button(label, value, key, run_html_func=None, field_labels=None, *, compact=False):
    field_labels = field_labels or []
    if run_html_func:
        button_id = f"copy_{_safe_js_id(key)}"
        js_labels = json.dumps(field_labels, ensure_ascii=False)
        js_fallback = json.dumps(value or "", ensure_ascii=False)
        width = "auto;min-width:104px;padding:0 .7rem;" if compact else "width:100%;"
        run_html_func(
            f"""
<button id="{button_id}" type="button" style="
{width}min-height:34px;border:1px solid #d8e2ef;border-radius:8px;
background:#ffffff;color:#0f1f36;font-weight:700;cursor:pointer;">
{label}
</button>
<script>
(function() {{
  const btn = document.getElementById({json.dumps(button_id)});
  const labels = {js_labels};
  const fallback = {js_fallback};
  function currentText() {{
    const root = window.parent && window.parent.document ? window.parent.document : document;
    if (!labels.length) return fallback;
    const values = labels.map(label => {{
      const fields = Array.from(root.querySelectorAll('input, textarea'));
      const field = fields.find(el => el.getAttribute('aria-label') === label);
      return field ? field.value : '';
    }}).filter(Boolean);
    return values.length ? values.join('\\n\\n') : fallback;
  }}
  async function copyText(text) {{
    if (navigator.clipboard && window.isSecureContext) {{
      await navigator.clipboard.writeText(text);
      return true;
    }}
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  }}
  btn.addEventListener('click', async () => {{
    const original = btn.textContent;
    try {{
      await copyText(currentText());
      btn.textContent = 'Copié !';
    }} catch (e) {{
      btn.textContent = 'Copie manuelle';
    }}
    setTimeout(() => {{ btn.textContent = original; }}, 1400);
  }});
}})();
</script>
""",
            height=40 if compact else 45,
        )
        return

    button_args = {"key": key, "disabled": not bool(value)}
    if not compact:
        button_args["width"] = "stretch"
    if st.button(label, **button_args):
        st.session_state["vinted_copy_buffer"] = value
        st.toast("Texte prêt à copier juste en dessous.")


def _render_listing_preview(selected_cards, proxy_img_func, run_html_func=None, mobile=False):
    st.subheader("Aperçu de l'annonce")
    if not selected_cards:
        st.caption("Sélectionne une carte ou prépare une carte depuis un drop pour générer l'aperçu.")
        return

    with st.container(border=True):
        if mobile:
            _render_thumb(selected_cards[0], proxy_img_func, width=145)
            if len(selected_cards) > 1:
                st.caption(f"+ {len(selected_cards) - 1} autre(s) carte(s)")
            st.link_button("Ouvrir Vinted", "https://www.vinted.fr/items/new", width="stretch")
            st.text_input("Titre", key="vinted_listing_title")
            _copy_button("Copier titre", st.session_state.get("vinted_listing_title", ""), "copy_vinted_title", run_html_func, ["Titre"])
            st.text_input("Prix", key="vinted_listing_price")
            _copy_button("Copier prix", st.session_state.get("vinted_listing_price", ""), "copy_vinted_price", run_html_func, ["Prix"])
            st.text_area("Description", key="vinted_listing_description", height=240)
            _copy_button("Copier description", st.session_state.get("vinted_listing_description", ""), "copy_vinted_description", run_html_func, ["Description"])
            _copy_button(
                "Copier titre + description",
                (
                    f"{st.session_state.get('vinted_listing_title', '')}\n\n"
                    f"{st.session_state.get('vinted_listing_description', '')}"
                ),
                "copy_vinted_all",
                run_html_func,
                ["Titre", "Description"],
            )
            if st.session_state.get("vinted_copy_buffer"):
                st.text_area("Copie manuelle", value=st.session_state["vinted_copy_buffer"], height=160)
            return

        img_col, text_col = st.columns([1, 2])
        with img_col:
            _render_thumb(selected_cards[0], proxy_img_func, width=210)
            if len(selected_cards) > 1:
                st.caption(f"+ {len(selected_cards) - 1} autre(s) carte(s)")
            st.link_button("Ouvrir Vinted", "https://www.vinted.fr/items/new", width="stretch")
        with text_col:
            title_col, title_btn_col = st.columns([3, 1])
            with title_col:
                st.text_input("Titre", key="vinted_listing_title")
            with title_btn_col:
                _copy_button(
                    "Copier titre",
                    st.session_state.get("vinted_listing_title", ""),
                    "copy_vinted_title",
                    run_html_func,
                    ["Titre"],
                )

            price_col, price_btn_col = st.columns([3, 1])
            with price_col:
                st.text_input("Prix", key="vinted_listing_price")
            with price_btn_col:
                _copy_button(
                    "Copier prix",
                    st.session_state.get("vinted_listing_price", ""),
                    "copy_vinted_price",
                    run_html_func,
                    ["Prix"],
                )

            desc_col, desc_btn_col = st.columns([3, 1])
            with desc_col:
                st.text_area("Description", key="vinted_listing_description", height=300)
            with desc_btn_col:
                _copy_button(
                    "Copier description",
                    st.session_state.get("vinted_listing_description", ""),
                    "copy_vinted_description",
                    run_html_func,
                    ["Description"],
                )

            _copy_button(
                "Copier titre + description",
                (
                    f"{st.session_state.get('vinted_listing_title', '')}\n\n"
                    f"{st.session_state.get('vinted_listing_description', '')}"
                ),
                "copy_vinted_all",
                run_html_func,
                ["Titre", "Description"],
            )

            if st.session_state.get("vinted_copy_buffer"):
                st.text_area("Copie manuelle", value=st.session_state["vinted_copy_buffer"], height=160)


def _render_selected_add_to_drop(drops_data, selected_cards, scope="classic"):
    if not selected_cards or not drops_data.get("drops"):
        return
    options = _drop_choice_options(drops_data)
    if not options:
        return
    name = st.selectbox("Ajouter la sélection au drop", list(options.keys()), key="vinted_drop_destination")
    drop_id = options.get(name)
    if st.button("Ajouter la sélection au drop", disabled=not selected_cards, width="stretch"):
        cards_to_add = [
            _card_with_drop_quantity(card, _selected_quantity(scope, card)[0])
            for card in selected_cards
        ]
        added, duplicates = add_cards_to_drop(drops_data, drop_id, cards_to_add)
        if added:
            save_vinted_drops(drops_data)
            st.success(f"{added} carte(s) ajoutée(s) au drop.")
        if duplicates:
            st.warning("Cette carte est déjà dans ce drop." if duplicates == 1 else f"{duplicates} cartes sont déjà dans ce drop.")
        st.rerun()


def _render_drop_add_result(card, drops_data, active_drop, proxy_img_func, fp_func, mobile=False):
    key = card["_listing_key"]
    already = card_is_in_drop(active_drop, card)
    with st.container(border=True):
        if mobile:
            img_col, info_col = st.columns([0.75, 2.25])
            action_col = st.container()
        else:
            img_col, info_col, action_col = st.columns([0.7, 2.4, 1.0])
        with img_col:
            _render_thumb(card, proxy_img_func, width=74 if mobile else 82)
        with info_col:
            st.markdown(f"**{_card_display_title(card)}**")
            for line in _card_details_text(card, fp_func):
                st.caption(line)
        with action_col:
            if st.button(
                "Déjà ajouté" if already else "Ajouter au drop",
                key=f"vinted_drop_add_card_{active_drop.get('id')}_{key}",
                disabled=already,
                width="stretch",
            ):
                _add_card_to_drop_action(drops_data, active_drop.get("id"), card)


def _render_drop_add_search(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile=False):
    query = st.text_input(
        "Rechercher une carte à ajouter au drop",
        key="vinted_drop_add_query",
        placeholder="Ex : Dracaufeu, Rayquaza 89/90, Pohmarmotte...",
    )
    candidates_all = _filter_cards_for_display(available_cards, query)
    candidates_all = [card for card in candidates_all if not card_is_in_drop(active_drop, card)]
    if not candidates_all:
        st.caption("Aucune carte disponible trouvée.")
        return

    st.caption(f"{len(candidates_all)} carte(s) disponible(s).")
    groups = _drop_grid_groups(candidates_all, proxy_img_func, fp_func)
    duplicate_counts = dict(_drop_identity_counts(active_drop))
    result = render_vinted_drop_virtual_grid(
        groups,
        set(),
        duplicate_counts=duplicate_counts,
        key=f"drop_add_{active_drop.get('id')}",
        mobile=mobile,
        scroll_top_token=_drop_scroll_top_token(active_drop.get("id"), query),
        committed_selection_token=_drop_grid_committed_selection_token(active_drop.get("id")),
    )
    batch = _component_batch(result)
    if batch:
        selected_count, added_count, skipped_count = _process_drop_selection_batch(
            drops_data,
            active_drop,
            available_cards,
            batch,
        )
        if selected_count:
            if added_count:
                st.success(f"✓ {added_count} carte(s) ajoutée(s) au drop.")
            if skipped_count:
                st.warning(f"{skipped_count} sélection(s) déjà présente(s) ou indisponible(s).")
            st.rerun()
    if result is None:
        st.caption("Affichage simplifié utilisé pour cette session.")
        _render_grouped_available_grid(
            candidates_all[:24 if mobile else 48],
            scope="drop_add_fallback",
            listing_type="Carte seule",
            selected_keys=[],
            drops_data=drops_data,
            active_drop_id=active_drop.get("id"),
            proxy_img_func=proxy_img_func,
            fp_func=fp_func,
            mobile=mobile,
            mode="drop",
        )


def _render_drop_grid(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile):
    resolved_cards, missing_cards = resolve_drop_cards_from_data(active_drop, available_cards)
    drop_query = st.text_input(
        "Rechercher dans ce drop",
        key="vinted_drop_filter_query",
        placeholder="Nom, numéro complet, extension, lot...",
    )
    filtered_cards = filter_drop_cards(resolved_cards, drop_query)
    filtered_missing = filter_drop_cards(missing_cards, drop_query)
    if not filtered_cards and not filtered_missing:
        st.caption("Aucune carte dans ce drop." if not resolved_cards and not missing_cards else "Aucune carte ne correspond à cette recherche.")
        return

    if missing_cards:
        st.warning(f"{len(missing_cards)} carte(s) du drop ne sont plus disponibles à la vente.")

    duplicate_counts = _drop_identity_counts(active_drop)
    duplicate_extra = _drop_duplicate_extra_count(active_drop)
    if duplicate_extra:
        st.markdown(
            f'<span class="ps-vinted-badge duplicate">⚠ {duplicate_extra} doublon(s) potentiel(s)</span>',
            unsafe_allow_html=True,
        )

    cols_count = _drop_cards_grid_columns(mobile)
    all_cards = []
    for card in list(filtered_cards) + list(filtered_missing):
        item = dict(card)
        item["_drop_duplicate_total"] = duplicate_counts.get(_card_identity(item), 0)
        all_cards.append(item)
    for row_index, row in _chunked(all_cards, cols_count):
        with st.container(horizontal=True, key=f"vinted_grid_drop_cards_{active_drop.get('id')}_{row_index}"):
            for card in row:
                _render_drop_card(active_drop, drops_data, card, proxy_img_func, fp_func)


def _render_drop_card(active_drop, drops_data, card, proxy_img_func, fp_func):
    unavailable = not bool(card.get("_drop_available", True))
    card_ref_key = card.get("_drop_ref_key") or drop_card_key(
        {
            "lot_uid": card.get("lot_uid", ""),
            "card_uid": card.get("card_uid", ""),
            "lot_idx": card.get("lot_idx", 0),
            "card_idx": card.get("card_idx", 0),
            "name": card.get("name", ""),
            "number": card.get("number", ""),
            "set": card.get("set", ""),
        }
    )
    posted = bool(card.get("listing_posted", False))
    status = str(card.get("status") or ("online" if posted else "to_prepare"))
    badge = "INDISPONIBLE" if unavailable else drop_item_status_label(status)
    badge_class = "warn" if unavailable else _drop_status_badge_class(status)
    duplicate_total = int(card.get("_drop_duplicate_total", 0) or 0)
    duplicate_badge = ""
    if duplicate_total > 1:
        duplicate_badge = f"⚠ {duplicate_total} exemplaires" if duplicate_total > 2 else "⚠ Doublon"
    with st.container(key=f"vinted_card_drop_{active_drop.get('id')}_{_safe_js_id(card_ref_key)}"):
        st.markdown(
            _card_static_html(
                card,
                proxy_img_func,
                fp_func,
                badge=badge,
                badge_class=badge_class,
                duplicate_badge=duplicate_badge,
                unavailable=unavailable,
                drop_card=True,
                drop_price_display="current",
            ),
            unsafe_allow_html=True,
        )
        if not unavailable:
            st.caption(f"Statut : {drop_item_status_label(status)}")
        if st.button("Retirer du drop", key=f"remove_drop_card_{active_drop.get('id')}_{card_ref_key}", width="stretch"):
            if remove_card_from_drop(drops_data, active_drop.get("id"), card_ref_key):
                save_vinted_drops(drops_data)
                st.success("Carte retirée du drop.")
                st.rerun()


def _drop_status_counts(drop):
    counts = {status: 0 for status in DROP_ITEM_STATUSES}
    for ref in drop.get("cards", []) or []:
        counts[drop_item_status(ref)] = counts.get(drop_item_status(ref), 0) + max(1, _safe_int(ref.get("quantity"), 1))
    return counts


def _render_drop_placeholder(title, body):
    st.markdown(
        f"""
<div class="ps-vinted-muted-panel">
  <div class="ps-vinted-section-title">{_html_escape(title)}</div>
  {_html_escape(body)}
</div>
""",
        unsafe_allow_html=True,
    )


def _photo_result_key(drop_id):
    return f"vinted_photo_recognition_result_{drop_id}"


def _photo_session_key(drop_id):
    return f"vinted_photo_recognition_session_{drop_id}"


def _photo_folder_key(drop_id):
    return f"vinted_photo_recognition_folder_{drop_id}"


def _photo_source_key(drop_id):
    return f"vinted_photo_recognition_source_{drop_id}"


def _photo_upload_session_key(drop_id):
    return f"vinted_photo_upload_session_{drop_id}"


def _photo_upload_ack_key(drop_id):
    return f"vinted_photo_upload_ack_{drop_id}"


def _photo_upload_batch_key(drop_id):
    return f"vinted_photo_upload_last_batch_{drop_id}"


def _photo_upload_cancel_key(drop_id):
    return f"vinted_photo_upload_cancel_{drop_id}"


def _photo_queue_index_key(drop_id):
    return f"vinted_photo_recognition_queue_index_{drop_id}"


def _photo_queue_next_group_key(drop_id):
    return f"vinted_photo_recognition_queue_next_group_{drop_id}"


def _photo_queue_feedback_key(drop_id):
    return f"vinted_photo_recognition_queue_feedback_{drop_id}"


def _photo_queue_focus_key(drop_id):
    return f"vinted_photo_recognition_queue_focus_{drop_id}"


def _photo_queue_seen_subcards_key(drop_id):
    return f"vinted_photo_recognition_queue_seen_subcards_{drop_id}"


def _photo_review_pass_key(drop_id):
    return f"vinted_photo_recognition_review_pass_{drop_id}"


def _new_photo_review_pass(groups, *, mode="review"):
    return {
        "mode": mode,
        "group_ids": [photo_stable_group_id(group) for group in groups],
        "position": 0,
        "visited_group_ids": [],
        "completed": False,
    }


def _advanced_photo_review_pass(pass_state):
    """Return the next stable pass state without rebuilding its source queue."""
    state = dict(pass_state or {})
    group_ids = list(state.get("group_ids") or [])
    position = _safe_int(state.get("position"), 0)
    if position + 1 >= len(group_ids):
        state["position"] = len(group_ids)
        state["completed"] = True
    else:
        state["position"] = position + 1
    return state


def _review_pass_remaining_group_ids(pass_state, result, session):
    unresolved_ids = {
        photo_stable_group_id(group)
        for group in photo_unresolved_groups(result, session)
    }
    return [group_id for group_id in pass_state.get("group_ids", []) if group_id in unresolved_ids]


def _mark_photo_review_pass_group_visited(drop_id, group_id):
    state = st.session_state.get(_photo_review_pass_key(drop_id)) or {}
    visited = list(state.get("visited_group_ids") or [])
    if group_id not in visited:
        visited.append(group_id)
    state["visited_group_ids"] = visited
    st.session_state[_photo_review_pass_key(drop_id)] = state


def _advance_photo_review_pass(drop_id, feedback):
    """Advance one fixed review pass without wrapping back to its first group."""
    state = st.session_state.get(_photo_review_pass_key(drop_id)) or {}
    st.session_state[_photo_review_pass_key(drop_id)] = _advanced_photo_review_pass(state)
    st.session_state.pop(_photo_queue_next_group_key(drop_id), None)
    st.session_state.pop(_photo_queue_focus_key(drop_id), None)
    st.session_state[_photo_queue_feedback_key(drop_id)] = feedback


def _photo_subcard_queue_token(group, match, match_index):
    return f"{photo_stable_group_id(group)}:{photo_stable_subcard_id(match, match_index)}"


def _schedule_photo_review_subcard(drop_id, group, match, match_index, feedback):
    """Keep a multi-card review on its physical group and focus its next card."""
    group_id = photo_stable_group_id(group)
    st.session_state[_photo_queue_focus_key(drop_id)] = {
        "group_id": group_id,
        "subcard_id": photo_stable_subcard_id(match, match_index),
    }
    st.session_state[_photo_queue_feedback_key(drop_id)] = feedback


def _photo_from_entry(entry):
    return entry.get("photo") if isinstance(entry, dict) else entry


def _photo_path(photo):
    if isinstance(photo, dict):
        return str(photo.get("path") or "")
    return str(getattr(photo, "path", "") or "")


def _photo_filename(photo):
    if isinstance(photo, dict):
        return str(photo.get("filename") or Path(_photo_path(photo)).name)
    return str(getattr(photo, "filename", "") or Path(_photo_path(photo)).name)


def _photo_capture_index(photo):
    if isinstance(photo, dict):
        return _safe_int(photo.get("capture_index"), 0)
    return _safe_int(getattr(photo, "capture_index", 0), 0)


def _load_photo_workflow_state(active_drop):
    drop_id = str(active_drop.get("id") or "")
    session_key = _photo_session_key(drop_id)
    folder_key = _photo_folder_key(drop_id)
    result_key = _photo_result_key(drop_id)
    if session_key not in st.session_state:
        st.session_state[session_key] = load_drop_photo_session(drop_id)
    session = st.session_state[session_key]
    if folder_key not in st.session_state:
        stored_folder = str(session.get("folder") or "")
        default_folder = stored_folder if stored_folder else str(Path("photo_recognition_poc"))
        st.session_state[folder_key] = default_folder
    folder = str(st.session_state.get(folder_key) or "").strip()
    if result_key not in st.session_state and folder and Path(folder).exists():
        result, restored_session = restore_drop_analysis(folder, drop_id)
        if result is not None:
            st.session_state[result_key] = result
            st.session_state[session_key] = restored_session
    current_result = st.session_state.get(result_key)
    current_session = st.session_state.get(session_key) or session
    if current_result is not None and (
        str((current_result.get("analysis_meta") or {}).get("proposal_reliability_version") or "")
        != PHOTO_PROPOSAL_RELIABILITY_VERSION
        or str((current_result.get("analysis_meta") or {}).get("language_compatibility_version") or "")
        != PHOTO_LANGUAGE_COMPATIBILITY_VERSION
    ):
        current_result, current_session = refresh_drop_analysis_candidates(
            current_result,
            current_session,
            drop_id=drop_id,
        )
        st.session_state[result_key] = current_result
        st.session_state[session_key] = current_session
    return current_result, current_session, folder


def _store_photo_workflow_state(active_drop, result, session):
    drop_id = str(active_drop.get("id") or "")
    st.session_state[_photo_result_key(drop_id)] = result
    st.session_state[_photo_session_key(drop_id)] = session


def _apply_photo_workflow_statuses(drops_data, active_drop, result, session):
    payload = build_step4_payload(
        result,
        session,
        photo_capture_direction=_drop_photo_direction(active_drop) or "start_to_end",
        require_ready=False,
    )
    changed = apply_recognition_statuses(drops_data, active_drop.get("id"), payload)
    if changed:
        save_vinted_drops(drops_data)
    return payload, changed


def _photo_match_semantic_status(session, group, match, match_index):
    """Return the display-only status for one physical card proposal."""
    validation = validation_for_match(session, group, match, match_index)
    candidate, source = photo_effective_candidate(session, group, match, match_index)
    raw_status = str(match.get("status") or "fail")

    if validation.get("compatible") and validation.get("state") in {"correct", "manual"}:
        return {
            "tone": "success",
            "label": "✓ Reconnu",
            "message": "Correspondance validée" if source == "manual" else "Correspondance fiable",
        }
    if raw_status in {"fail", "unrecognized"} or not candidate:
        return {
            "tone": "danger",
            "label": "× Non reconnu",
            "message": "Aucune correspondance fiable",
        }
    if match.get("v13_not_in_drop_confidence") in {"strong", "possible"}:
        return {
            "tone": "warning",
            "label": "! À vérifier",
            "message": "Carte peut-être absente du Drop",
        }
    if validation.get("state") in {"wrong", "stale"}:
        return {
            "tone": "warning",
            "label": "! À vérifier",
            "message": "Vérification recommandée",
        }
    if raw_status == "review" or match.get("v13_japanese_candidate") or match.get("v13_japanese_signal"):
        return {
            "tone": "warning",
            "label": "! À vérifier",
            "message": "Vérification recommandée",
        }
    return {
        "tone": "success",
        "label": "✓ Reconnu",
        "message": "Correspondance fiable",
    }


def _photo_group_semantic_status(session, group, reasons):
    match_statuses = [
        _photo_match_semantic_status(session, group, match, index)
        for index, match in enumerate(group.get("matches", []) or [])
    ]
    if any(item["tone"] == "danger" for item in match_statuses):
        return {"tone": "danger", "label": "× Non reconnu"}
    if reasons or any(item["tone"] == "warning" for item in match_statuses):
        return {"tone": "warning", "label": "! À vérifier"}
    return {"tone": "success", "label": "✓ Reconnu"}


def _photo_status_badge(status):
    return (
        f'<span class="ps-photo-status-badge {status["tone"]}">'
        f'{_html_escape(status["label"])}</span>'
    )


def _render_photo_status_message(status):
    st.markdown(
        f'<div class="ps-photo-status-callout {status["tone"]}">{_html_escape(status["message"])}</div>',
        unsafe_allow_html=True,
    )


def _render_photo_analysis_summary(result, session):
    summary = photo_analysis_summary(result, session)
    st.markdown(
        f"""
<div class="ps-photo-summary-line">
  <span><strong>{summary['photos']}</strong> photos</span>
  <span><strong>{summary['announcements']}</strong> annonces</span>
  <span class="auto"><strong>{summary['auto']}</strong> reconnues</span>
  <span class="review"><strong>{summary['review']}</strong> à vérifier</span>
  <span class="fail"><strong>{summary['fail']}</strong> non reconnues</span>
</div>
""",
        unsafe_allow_html=True,
    )
    return summary


def _photo_analysis_staleness(result, folder, drop_id):
    if not result:
        return {"photos": False, "candidates": False, "stale": False}
    meta = result.get("analysis_meta") or {}
    photos = list_ordered_photos(folder) if folder and Path(folder).exists() else []
    current_photo_signature = photo_window_signature(photos) if photos else ""
    cached_photo_signature = str(meta.get("photo_signature") or "")
    _drop, candidates = active_drop_candidates(drop_id=drop_id)
    current_candidate_signature = candidate_set_signature(candidates)
    cached_candidate_signature = str(meta.get("candidate_signature") or "")
    photo_changed = not photos or current_photo_signature != cached_photo_signature
    candidate_changed = bool(cached_candidate_signature and current_candidate_signature != cached_candidate_signature)
    return {
        "photos": photo_changed,
        "candidates": candidate_changed,
        "stale": photo_changed or candidate_changed,
        "photo_count": len(photos),
    }


def _render_photo_source_controls(active_drop, folder, *, show_analysis_action, analysis_label="Analyser les photos"):
    drop_id = str(active_drop.get("id") or "")
    source_key = _photo_source_key(drop_id)
    if source_key not in st.session_state:
        current_manifest = Path(folder) / "upload_manifest.json" if folder else None
        st.session_state[source_key] = (
            "Import navigateur / téléphone"
            if current_manifest and current_manifest.is_file()
            else "Dossier local"
        )
    source = st.segmented_control(
        "Source des photos",
        ["Import navigateur / téléphone", "Dossier local"],
        key=source_key,
        width="stretch",
    )
    clicked = False

    if source == "Import navigateur / téléphone":
        upload_session_id = str(st.session_state.get(_photo_upload_session_key(drop_id)) or "")
        upload_state = {"count": 0, "received_hashes": [], "folder": ""}
        if upload_session_id:
            try:
                upload_state = browser_upload_state(drop_id, upload_session_id)
            except ValueError:
                upload_session_id = ""
                st.session_state.pop(_photo_upload_session_key(drop_id), None)
        allowed = browser_photo_upload_allowed(active_drop)
        if not allowed:
            st.info(
                "Ce Drop est déjà lancé. Son import photo est protégé ; les photos existantes restent consultables."
            )
        elif not browser_upload_component_available():
            st.error("L’import navigateur n’est pas disponible dans cette version de PokéStock.")
        component_result = render_browser_photo_upload(
            key=f"vinted_browser_photo_upload_{drop_id}",
            drop_id=drop_id,
            upload_session_id=upload_session_id,
            received_hashes=upload_state.get("received_hashes") or [],
            ack=st.session_state.get(_photo_upload_ack_key(drop_id)) or {},
            cancel_token=str(st.session_state.get(_photo_upload_cancel_key(drop_id)) or ""),
            disabled=not allowed,
            show_analyze_action=show_analysis_action,
        ) if browser_upload_component_available() else {}

        upload_batch = component_result.get("upload_batch") if isinstance(component_result, dict) else None
        if isinstance(upload_batch, dict) and allowed:
            event_session_id = str(upload_batch.get("upload_session_id") or "")
            batch_id = str(upload_batch.get("batch_id") or "")
            if batch_id and batch_id != st.session_state.get(_photo_upload_batch_key(drop_id)):
                ack = receive_browser_upload_batch(
                    drop_id=drop_id,
                    upload_session_id=event_session_id,
                    batch_id=batch_id,
                    entries=upload_batch.get("entries") or [],
                )
                st.session_state[_photo_upload_session_key(drop_id)] = event_session_id
                st.session_state[_photo_upload_batch_key(drop_id)] = batch_id
                st.session_state[_photo_upload_ack_key(drop_id)] = ack
                st.session_state[_photo_folder_key(drop_id)] = str(ack.get("folder") or "")
                st.rerun()

        cancel_event = component_result.get("cancel") if isinstance(component_result, dict) else None
        if isinstance(cancel_event, dict) and allowed:
            event_session_id = str(cancel_event.get("upload_session_id") or "")
            cancel_token = str(cancel_event.get("token") or "")
            if event_session_id and cancel_token != st.session_state.get(_photo_upload_cancel_key(drop_id)):
                cancel_browser_upload(drop_id, event_session_id)
                st.session_state[_photo_upload_session_key(drop_id)] = event_session_id
                st.session_state[_photo_upload_cancel_key(drop_id)] = cancel_token
                st.session_state.pop(_photo_upload_ack_key(drop_id), None)
                if str(st.session_state.get(_photo_folder_key(drop_id)) or "") == str(upload_state.get("folder") or ""):
                    st.session_state[_photo_folder_key(drop_id)] = ""
                st.rerun()

        analyze_event = component_result.get("analyze") if isinstance(component_result, dict) else None
        if isinstance(analyze_event, dict) and allowed:
            event_session_id = str(analyze_event.get("upload_session_id") or upload_session_id)
            upload_state = browser_upload_state(drop_id, event_session_id)
            if upload_state.get("count"):
                st.session_state[_photo_upload_session_key(drop_id)] = event_session_id
                st.session_state[_photo_folder_key(drop_id)] = str(upload_state.get("folder") or "")
                folder = str(upload_state.get("folder") or "")
                clicked = show_analysis_action

        folder = str(st.session_state.get(_photo_folder_key(drop_id)) or folder or "").strip()
        photos = list_ordered_photos(folder) if folder and Path(folder).exists() else []
        if photos:
            first_name = getattr(photos[0], "original_filename", "") or photos[0].filename
            last_name = getattr(photos[-1], "original_filename", "") or photos[-1].filename
            st.caption(f"{len(photos)} photos prêtes · ordre conservé · {first_name} → {last_name}")
        return clicked, folder, photos

    st.markdown("**Utiliser un dossier local**")
    st.caption("Pour PokéStock sur PC ou un dossier déjà présent sur cet appareil.")
    st.text_input(
        "Dossier des photos",
        key=_photo_folder_key(drop_id),
        placeholder=r"C:\Photos\Mon drop",
    )
    folder = str(st.session_state.get(_photo_folder_key(drop_id)) or "").strip()
    photos = list_ordered_photos(folder) if folder and Path(folder).exists() else []
    if photos:
        st.success(f"{len(photos)} photos détectées")
    else:
        st.caption("Aucune photo compatible détectée dans ce dossier.")
    if show_analysis_action:
        clicked = st.button(
            analysis_label,
            key=f"vinted_photo_analyze_{drop_id}",
            type="primary",
            disabled=not photos,
            width="stretch",
        )
    return clicked, folder, photos


def _render_photo_analysis_step(drops_data, active_drop, mobile):
    result, session, folder = _load_photo_workflow_state(active_drop)
    drop_id = str(active_drop.get("id") or "")
    st.markdown('<div class="ps-vinted-section-title">Photos et analyse</div>', unsafe_allow_html=True)
    analyze_clicked = False
    refresh_clicked = False
    force_clicked = False

    if result is None:
        st.markdown(
            """
<div class="ps-photo-state">
  <div class="ps-photo-state-head">
    <div>
      <div class="ps-photo-state-title">Ajouter les photos du Drop</div>
      <div class="ps-photo-state-copy">Choisis une source, puis lance l’analyse. L’ordre original des photos sera conservé.</div>
    </div>
    <span class="ps-photo-state-badge stale">Analyse requise</span>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            analyze_clicked, folder, photos = _render_photo_source_controls(
                active_drop,
                folder,
                show_analysis_action=True,
            )
    else:
        staleness = _photo_analysis_staleness(result, folder, drop_id)
        if staleness["stale"]:
            changed_parts = []
            if staleness["photos"]:
                changed_parts.append("la source photo")
            if staleness["candidates"]:
                changed_parts.append("les cartes du Drop")
            changed_label = " et ".join(changed_parts) or "le Drop"
            st.markdown(
                f"""
<div class="ps-photo-state">
  <div class="ps-photo-state-head">
    <div>
      <div class="ps-photo-state-title">L’analyse doit être mise à jour</div>
      <div class="ps-photo-state-copy">Un changement a été détecté dans {_html_escape(changed_label)}. Seuls les éléments concernés seront recalculés lorsque c’est possible.</div>
    </div>
    <span class="ps-photo-state-badge stale">Mise à jour requise</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            _render_photo_analysis_summary(result, session)
            photos = list_ordered_photos(folder) if folder and Path(folder).exists() else []
            analyze_clicked = st.button(
                "Mettre à jour l’analyse",
                key=f"vinted_photo_update_{drop_id}",
                type="primary",
                disabled=bool(staleness["photos"] and not photos),
                width="stretch",
            )
        else:
            st.markdown(
                """
<div class="ps-photo-state">
  <div class="ps-photo-state-head">
    <div>
      <div class="ps-photo-state-title">Analyse prête</div>
      <div class="ps-photo-state-copy">Les photos sont classées et les résultats sont prêts à être contrôlés.</div>
    </div>
    <span class="ps-photo-state-badge">✓ Analyse à jour</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            _render_photo_analysis_summary(result, session)
            if st.button(
                "Continuer vers la vérification",
                key=f"vinted_photo_continue_review_{drop_id}",
                type="primary",
                width="stretch",
            ):
                st.session_state["vinted_drop_step"] = "Vérification"
                st.session_state[_photo_queue_index_key(drop_id)] = 0
                st.rerun()

        with st.expander("Options de l’analyse", expanded=False):
            _unused_clicked, folder, photos = _render_photo_source_controls(
                active_drop,
                folder,
                show_analysis_action=False,
            )
            option_cols = st.columns(2) if not mobile else [st.container(), st.container()]
            with option_cols[0]:
                refresh_clicked = st.button(
                    "Actualiser les cartes du Drop",
                    key=f"vinted_photo_refresh_candidates_{drop_id}",
                    width="stretch",
                )
            with option_cols[1]:
                force_clicked = st.button(
                    "Relancer l’analyse",
                    key=f"vinted_photo_force_analysis_{drop_id}",
                    disabled=not photos,
                    width="stretch",
                )

    if analyze_clicked:
        current_staleness = _photo_analysis_staleness(result, folder, drop_id) if result is not None else {"photos": True}
        if result is not None and not current_staleness.get("photos"):
            with st.spinner("Mise à jour des cartes du Drop..."):
                result, session = refresh_drop_analysis_candidates(result, session, drop_id=drop_id)
                _store_photo_workflow_state(active_drop, result, session)
                _apply_photo_workflow_statuses(drops_data, active_drop, result, session)
        else:
            progress = st.progress(0, text=f"Préparation de {len(photos)} photos...")
            with st.spinner("Analyse en cours. Le résultat sera conservé pour la prochaine ouverture."):
                result, session = analyze_drop_photos(folder, drop_id)
                _store_photo_workflow_state(active_drop, result, session)
                _apply_photo_workflow_statuses(drops_data, active_drop, result, session)
            progress.progress(1.0, text="Analyse terminée")
        st.rerun()

    if refresh_clicked and result is not None:
        with st.spinner("Actualisation des cartes du Drop..."):
            result, session = refresh_drop_analysis_candidates(result, session, drop_id=drop_id)
            _store_photo_workflow_state(active_drop, result, session)
            _apply_photo_workflow_statuses(drops_data, active_drop, result, session)
        st.rerun()

    if force_clicked:
        progress = st.progress(0, text=f"Préparation de {len(photos)} photos...")
        with st.spinner("Nouvelle analyse en cours..."):
            result, session = analyze_drop_photos(folder, drop_id, force_rebuild=True)
            _store_photo_workflow_state(active_drop, result, session)
            _apply_photo_workflow_statuses(drops_data, active_drop, result, session)
        progress.progress(1.0, text="Analyse terminée")
        st.rerun()


def _candidate_label(candidate):
    if not candidate:
        return "Aucun candidat"
    bits = [str(candidate.get("name") or "Carte"), str(candidate.get("number") or "")]
    if candidate.get("set"):
        bits.append(str(candidate.get("set")))
    return " · ".join(bit for bit in bits if bit)


def _review_photo_thumbnail(path, *, max_width=900, max_height=560):
    """Return a persistent, lightweight preview without touching recognition caches."""
    source = Path(path)
    try:
        stat = source.stat()
    except OSError:
        return str(source)
    signature = f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{max_width}x{max_height}"
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()
    cache_dir = Path(".cache") / "photo_recognition" / "review_thumbnails"
    target = cache_dir / f"{digest}.jpg"
    if target.exists():
        return str(target)
    temporary = None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".{os.getpid()}.tmp.jpg")
        with Image.open(source) as raw_image:
            image = ImageOps.exif_transpose(raw_image)
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(temporary, format="JPEG", quality=84, optimize=True)
        os.replace(temporary, target)
        return str(target)
    except Exception:
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        except Exception:
            pass
        return str(source)


def _render_physical_group_photos(group, mobile):
    entries = group.get("photos", []) or []
    if not entries:
        st.caption("Aucune photo disponible.")
        return
    columns = 2 if mobile or len(entries) <= 2 else min(3, len(entries))
    for offset in range(0, len(entries), columns):
        cols = st.columns(columns)
        for col, entry in zip(cols, entries[offset : offset + columns]):
            photo = _photo_from_entry(entry)
            path = _photo_path(photo)
            with col:
                if path and Path(path).exists():
                    st.image(_review_photo_thumbnail(path), width="stretch")
                st.caption(f"#{_photo_capture_index(photo)} · {_photo_filename(photo)}")


def _render_candidate_identity(candidate, match, proxy_img_func):
    image = _card_image(candidate or {}, proxy_img_func)
    image_col, text_col = st.columns([1, 2.2])
    with image_col:
        if image:
            st.image(image, width="stretch")
    with text_col:
        st.markdown(f"**{_ui_text((candidate or {}).get('name'), 'Aucun candidat')}**")
        st.write(f"{_ui_text((candidate or {}).get('number'), 'Numéro inconnu')} · {_ui_text((candidate or {}).get('set'), 'Extension inconnue')}")
        score = _safe_float(match.get("score"))
        margin = _safe_float(match.get("margin"))
        st.caption(f"Confiance {score:.0f} · marge {margin:.0f}")


def _render_candidate_correction(
    drops_data,
    result,
    session,
    group,
    match,
    match_index,
    active_drop,
    available_cards,
    on_completed=None,
):
    group_id = photo_stable_group_id(group)
    subcard_id = photo_stable_subcard_id(match, match_index)
    query_key = f"vinted_photo_candidate_query_{group_id}_{subcard_id}"
    query = st.text_input("Rechercher par nom, numéro ou UID", key=query_key)
    _current_drop, historical_candidates = active_drop_candidates(drop_id=str(active_drop.get("id") or ""))
    candidates = search_drop_candidates({"candidates": historical_candidates}, query) if query else []
    if query:
        for card in filter_cards_for_listing(available_cards, query, limit=30):
            uid = str(card.get("card_uid") or "")
            if uid and uid not in {str(candidate.get("card_uid") or "") for candidate in candidates}:
                candidates.append(card)
    if not candidates:
        if query:
            st.caption("Aucune carte exacte trouvée dans ce Drop.")
        return session
    labels = {}
    for candidate in candidates:
        resolved_candidate, membership = resolve_historical_drop_candidate(candidate, historical_candidates)
        in_drop = bool(membership.get("in_drop"))
        status = str(resolved_candidate.get("drop_status") or "")
        suffix = " · Dans le Drop"
        if status == "sold":
            suffix += " · Vendue"
        if not in_drop:
            suffix = " · hors Drop"
        label = _candidate_label(resolved_candidate) + suffix + f" · {resolved_candidate.get('card_uid', '')}"
        labels[label] = (resolved_candidate, in_drop)
    selected_label = st.selectbox("Carte exacte", list(labels), key=f"vinted_photo_candidate_select_{group_id}_{subcard_id}")
    selected_candidate, is_in_drop = labels[selected_label]
    selected_uid = str(selected_candidate.get("card_uid") or "")
    action_label = "Utiliser cette carte" if is_in_drop else "Ajouter cette carte au Drop et l’utiliser"
    if st.button(action_label, key=f"vinted_photo_candidate_apply_{group_id}_{subcard_id}", type="primary"):
        if not is_in_drop:
            added, duplicate = add_card_to_drop(drops_data, active_drop.get("id"), selected_candidate)
            if not (added or duplicate):
                st.error("Cette carte n’a pas pu être ajoutée au Drop.")
                return session
            save_vinted_drops(drops_data)
            result, session = refresh_drop_analysis_candidates(
                result,
                session,
                drop_id=str(active_drop.get("id") or ""),
            )
            selected_candidate = next(
                (
                    candidate
                    for candidate in result.get("candidates", []) or []
                    if str(candidate.get("card_uid") or "") == selected_uid
                ),
                selected_candidate,
            )
        session = set_match_validation(
            session,
            group,
            match,
            match_index,
            "manual",
            selected_candidate=selected_candidate,
        )
        _store_photo_workflow_state(active_drop, result, session)
        st.session_state.pop(f"vinted_photo_candidate_correction_open_{group_id}_{subcard_id}", None)
        if on_completed:
            on_completed(session, "✓ Identification associée")
        st.rerun(scope="fragment")
    return session


def _render_photo_match_review(
    drops_data,
    active_drop,
    result,
    session,
    group,
    match,
    match_index,
    proxy_img_func,
    available_cards,
    on_advance,
    is_focused=False,
):
    candidate, source = photo_effective_candidate(session, group, match, match_index)
    validation = validation_for_match(session, group, match, match_index)
    semantic_status = _photo_match_semantic_status(session, group, match, match_index)
    subcard_id = photo_stable_subcard_id(match, match_index)
    group_id = photo_stable_group_id(group)
    with st.container(border=True):
        st.markdown(
            f'<span class="ps-photo-review-marker {semantic_status["tone"]}"></span>',
            unsafe_allow_html=True,
        )
        label = f"Carte {match_index + 1}" if len(group.get("matches", []) or []) > 1 else "Carte proposée"
        st.markdown(f"**{label}**")
        if len(group.get("matches", []) or []) > 1:
            validation_state = str(validation.get("state") or "unvalidated")
            if validation.get("compatible") and validation_state in {"correct", "manual"}:
                progress_label = "Validée ✓"
            elif validation.get("compatible") and validation_state == "wrong":
                progress_label = "À corriger"
            else:
                progress_label = "À vérifier"
            if is_focused:
                progress_label += " · Prochaine carte"
            st.caption(progress_label)
        _render_candidate_identity(candidate, match, proxy_img_func)
        _render_photo_status_message(semantic_status)
        correction_open_key = f"vinted_photo_candidate_correction_open_{group_id}_{subcard_id}"
        if candidate:
            action_cols = st.columns(2)
            if action_cols[0].button("Mauvais", key=f"vinted_photo_wrong_{group_id}_{subcard_id}", width="stretch"):
                session = set_match_validation(session, group, match, match_index, "wrong")
                _store_photo_workflow_state(active_drop, result, session)
                on_advance(session, match_index, "Identification à corriger — cas conservé")
                st.rerun(scope="fragment")
            if action_cols[1].button(
                "Correct",
                key=f"vinted_photo_correct_{group_id}_{subcard_id}",
                type="primary",
                width="stretch",
            ):
                session = set_match_validation(session, group, match, match_index, "correct")
                _store_photo_workflow_state(active_drop, result, session)
                on_advance(session, match_index, "✓ Validation enregistrée")
                st.rerun(scope="fragment")
            if st.button(
                "Corriger l’identification",
                key=f"vinted_photo_correction_toggle_{group_id}_{subcard_id}",
                width="stretch",
            ):
                st.session_state[correction_open_key] = True
        else:
            action_cols = st.columns(2)
            if action_cols[0].button(
                "Associer une carte",
                key=f"vinted_photo_associate_{group_id}_{subcard_id}",
                type="primary",
                width="stretch",
            ):
                st.session_state[correction_open_key] = True
            if action_cols[1].button(
                "Passer pour l’instant",
                key=f"vinted_photo_skip_{group_id}_{subcard_id}",
                width="stretch",
            ):
                on_advance(session, match_index, "Cas conservé pour plus tard")
                st.rerun(scope="fragment")
        if st.session_state.get(correction_open_key, False):
            session = _render_candidate_correction(
                drops_data,
                result,
                session,
                group,
                match,
                match_index,
                active_drop,
                available_cards,
                on_completed=lambda updated_session, feedback: on_advance(updated_session, match_index, feedback),
            )
        with st.expander("Détails de reconnaissance", expanded=False):
            top = (match.get("candidates") or [])[:3]
            st.caption(f"Statut : {match.get('status', 'fail')} · méthode : {match.get('method', 'n/a')}")
            for rank, row in enumerate(top, start=1):
                st.write(f"#{rank} {_candidate_label(row.get('candidate'))} · score {_safe_float(row.get('score')):.0f}")
    return session


@st.fragment
def _render_photo_review_step(drops_data, active_drop, proxy_img_func, mobile, available_cards):
    result, session, folder = _load_photo_workflow_state(active_drop)
    drop_id = str(active_drop.get("id") or "")
    if result is None:
        _render_drop_placeholder("Aucune analyse disponible", "Lance d’abord l’analyse des photos à l’étape 2.")
        if st.button("Aller à l’analyse", key=f"vinted_photo_go_analysis_{drop_id}"):
            st.session_state["vinted_drop_step"] = "Tri des photos"
            st.rerun()
        return

    summary = _render_photo_analysis_summary(result, session)
    show_all = st.toggle("Consulter aussi les reconnaissances automatiques", key=f"vinted_photo_show_all_{drop_id}")
    mode = "all" if show_all else "review"
    initial_queue = list(result.get("groups", []) or []) if show_all else photo_unresolved_groups(result, session)
    pass_key = _photo_review_pass_key(drop_id)
    pass_state = st.session_state.get(pass_key)
    if not isinstance(pass_state, dict) or pass_state.get("mode") != mode:
        pass_state = _new_photo_review_pass(initial_queue, mode=mode)
        st.session_state[pass_key] = pass_state
        st.session_state.pop(_photo_queue_next_group_key(drop_id), None)
        st.session_state.pop(_photo_queue_focus_key(drop_id), None)
    feedback = st.session_state.pop(_photo_queue_feedback_key(drop_id), "")
    if feedback:
        st.toast(feedback)

    pass_group_ids = list(pass_state.get("group_ids") or [])
    current_unresolved_ids = _review_pass_remaining_group_ids(pass_state, result, session)
    if pass_state.get("completed") or not pass_group_ids:
        total = len(pass_group_ids)
        remaining = len(current_unresolved_ids)
        resolved = max(0, total - remaining)
        with st.container(border=True):
            st.markdown("### Vérification terminée")
            st.caption(f"{total} cas parcourus · {resolved} résolus · {remaining} encore à corriger")
            if remaining:
                primary_col, secondary_col = st.columns(2) if not mobile else [st.container(), st.container()]
                if primary_col.button(
                    f"Revoir les {remaining} cas non résolus",
                    key=f"vinted_photo_review_retry_{drop_id}",
                    type="primary",
                    width="stretch",
                ):
                    remaining_groups = [
                        group
                        for group in result.get("groups", []) or []
                        if photo_stable_group_id(group) in set(current_unresolved_ids)
                    ]
                    st.session_state[pass_key] = _new_photo_review_pass(remaining_groups, mode="review")
                    st.session_state.pop(_photo_queue_focus_key(drop_id), None)
                    st.rerun(scope="fragment")
                if secondary_col.button(
                    "Retour à l'étape 3",
                    key=f"vinted_photo_review_return_{drop_id}",
                    width="stretch",
                ):
                    st.session_state[pass_key] = _new_photo_review_pass(initial_queue, mode=mode)
                    st.session_state.pop(_photo_queue_focus_key(drop_id), None)
                    st.rerun(scope="fragment")
            else:
                st.success("Tous les cas sont traités.")
                payload = build_step4_payload(
                    result,
                    session,
                    photo_capture_direction=_drop_photo_direction(active_drop) or "start_to_end",
                )
                if payload.get("ready") and st.button(
                    "Continuer",
                    key=f"vinted_photo_go_creation_{drop_id}",
                    type="primary",
                ):
                    _apply_photo_workflow_statuses(drops_data, active_drop, result, session)
                    st.session_state["vinted_drop_step"] = "Création des annonces"
                    st.rerun()
        return

    group_by_id = {
        photo_stable_group_id(group): group
        for group in result.get("groups", []) or []
    }
    position = min(max(0, _safe_int(pass_state.get("position"), 0)), len(pass_group_ids) - 1)
    group = group_by_id.get(pass_group_ids[position])
    if group is None:
        st.session_state[pass_key] = _advanced_photo_review_pass(pass_state)
        st.rerun(scope="fragment")
        return
    index = position
    queue = [group_by_id[group_id] for group_id in pass_group_ids if group_id in group_by_id]
    st.session_state[_photo_queue_index_key(drop_id)] = index

    if not queue:
        st.session_state[pass_key] = _advanced_photo_review_pass(pass_state)
        st.rerun(scope="fragment")
        return
    reasons = group_review_reasons(session, group)
    group_status = _photo_group_semantic_status(session, group, reasons)
    st.markdown(
        f"""
<div class="ps-photo-review-header">
  <div class="ps-photo-review-title">À vérifier · {index + 1} / {len(pass_group_ids)}</div>
  {_photo_status_badge(group_status)}
</div>
""",
        unsafe_allow_html=True,
    )
    st.caption(f"Annonce #{group.get('announcement_index')} · " + (" · ".join(reasons) if reasons else "reconnaissance automatique"))

    def advance_to_next_group(feedback_message):
        _mark_photo_review_pass_group_visited(drop_id, photo_stable_group_id(group))
        _advance_photo_review_pass(drop_id, feedback_message)

    def advance_after_subcard(updated_session, match_index, feedback_message):
        matches = group.get("matches") or []
        if len(matches) <= 1:
            if photo_grouping_needs_confirmation(updated_session, group):
                st.session_state[_photo_queue_focus_key(drop_id)] = {
                    "group_id": photo_stable_group_id(group),
                    "kind": "grouping",
                }
                st.session_state[_photo_queue_feedback_key(drop_id)] = "✓ Carte identifiée — grouping à confirmer"
                return
            advance_to_next_group(feedback_message)
            return

        seen_key = _photo_queue_seen_subcards_key(drop_id)
        seen_subcards = set(st.session_state.get(seen_key, []) or [])
        seen_subcards.add(_photo_subcard_queue_token(group, matches[match_index], match_index))
        st.session_state[seen_key] = sorted(seen_subcards)
        next_match_index = photo_next_pending_subcard_index(
            updated_session,
            group,
            match_index,
            seen_subcards,
        )
        if next_match_index is None:
            group_token_prefix = f"{photo_stable_group_id(group)}:"
            st.session_state[seen_key] = sorted(
                token for token in seen_subcards if not token.startswith(group_token_prefix)
            )
            if photo_grouping_needs_confirmation(updated_session, group):
                st.session_state[_photo_queue_focus_key(drop_id)] = {
                    "group_id": photo_stable_group_id(group),
                    "kind": "grouping",
                }
                st.session_state[_photo_queue_feedback_key(drop_id)] = "✓ Cartes identifiées — grouping à confirmer"
                return
            advance_to_next_group(feedback_message)
            return
        _schedule_photo_review_subcard(
            drop_id,
            group,
            matches[next_match_index],
            next_match_index,
            feedback_message,
        )

    with st.container(border=True):
        st.markdown(
            f'<span class="ps-photo-review-marker {group_status["tone"]}"></span>',
            unsafe_allow_html=True,
        )
        photo_col, match_col = st.columns([1.1, 1], gap="large") if not mobile else [st.container(), st.container()]
        with photo_col:
            st.markdown("**Photos physiques**")
            _render_physical_group_photos(group, mobile)
        with match_col:
            st.markdown("**Identification**")
            focus = st.session_state.get(_photo_queue_focus_key(drop_id), {}) or {}
            focus_subcard_id = (
                str(focus.get("subcard_id") or "")
                if str(focus.get("group_id") or "") == photo_stable_group_id(group)
                else ""
            )
            match_items = list(enumerate(group.get("matches", []) or []))
            if focus_subcard_id:
                match_items.sort(
                    key=lambda item: photo_stable_subcard_id(item[1], item[0]) != focus_subcard_id
                )
            for match_index, match in match_items:
                session = _render_photo_match_review(
                    drops_data,
                    active_drop,
                    result,
                    session,
                    group,
                    match,
                    match_index,
                    proxy_img_func,
                    available_cards,
                    advance_after_subcard,
                    is_focused=photo_stable_subcard_id(match, match_index) == focus_subcard_id,
                )
            grouping_needs_confirmation = photo_grouping_needs_confirmation(session, group)
            subcards_pending = photo_pending_review_subcard_indexes(session, group)
            if grouping_needs_confirmation and not subcards_pending:
                _render_photo_status_message(
                    {"tone": "warning", "message": f"✓ {len(group.get('matches', []) or [])} cartes identifiées · Grouping à confirmer"}
                )
                st.caption("Ces photos correspondent-elles bien à une seule annonce ?")
                grouping_actions = st.columns(2)
                if grouping_actions[0].button(
                    "Grouping incorrect",
                    key=f"vinted_photo_group_incorrect_{photo_stable_group_id(group)}",
                    width="stretch",
                ):
                    advance_to_next_group("Grouping à corriger — cas conservé")
                    st.rerun(scope="fragment")
                if grouping_actions[1].button(
                    "Confirmer le grouping",
                    key=f"vinted_photo_group_confirm_{photo_stable_group_id(group)}",
                    type="primary",
                    width="stretch",
                ):
                    session = confirm_grouping(session, group)
                    _store_photo_workflow_state(active_drop, result, session)
                    advance_to_next_group("✓ Grouping confirmé")
                    st.rerun(scope="fragment")
            elif grouping_needs_confirmation:
                _render_photo_status_message(
                    {"tone": "warning", "message": "Grouping à confirmer après validation des cartes"}
                )

    previous_col, spacer, next_col = st.columns([1, 2, 1])
    if previous_col.button("Précédent", key=f"vinted_photo_previous_{drop_id}", disabled=index <= 0, width="stretch"):
        st.session_state.pop(_photo_queue_next_group_key(drop_id), None)
        st.session_state.pop(_photo_queue_focus_key(drop_id), None)
        pass_state["position"] = index - 1
        st.session_state[pass_key] = pass_state
        st.rerun(scope="fragment")
    if next_col.button("Suivant", key=f"vinted_photo_next_{drop_id}", width="stretch"):
        advance_to_next_group("Cas parcouru")
        st.rerun(scope="fragment")



def _drop_launch_value_summary(drop, available_cards):
    resolved_cards, missing_cards = resolve_drop_cards_from_data(drop, available_cards)
    total = 0.0
    without_price = 0
    for card in resolved_cards:
        quantity = max(1, _safe_int(card.get("drop_quantity", card.get("quantity", 1)), 1))
        price = _safe_float(suggested_price(card))
        total += price * quantity
        if price <= 0:
            without_price += quantity
    for ref in missing_cards:
        quantity = max(1, _safe_int(ref.get("quantity"), 1))
        price = _safe_float(ref.get("price_at_add"))
        total += price * quantity
        if price <= 0:
            without_price += quantity
    return total, without_price


def _render_launch_drop_panel(drops_data, active_drop, available_cards, fp_func):
    counts = _drop_status_counts(active_drop)
    total_cards = sum(max(1, _safe_int(ref.get("quantity"), 1)) for ref in active_drop.get("cards", []) or [])
    ready = counts.get("draft_ready", 0)
    st.markdown(f"**{ready} / {total_cards} brouillons prêts**")
    if active_drop.get("drop_launched_at"):
        launch_mode = " · Publication manuelle" if active_drop.get("launch_mode") == "manual" else ""
        st.success(f"🟢 Drop en ligne depuis le {active_drop.get('drop_launched_at')}{launch_mode}")
        return

    channel = normalize_vinted_channel(active_drop.get("channel", "")) or "Non défini"
    if ready > 0:
        with st.expander("🚀 Le drop est maintenant en ligne", expanded=False):
            st.write(f"Drop : **{active_drop.get('name', 'Drop sans nom')}**")
            st.write(f"Canal : **{channel}**")
            st.write(f"Brouillons prêts : **{ready}**")
            confirm_key = f"confirm_launch_drop_{active_drop.get('id')}"
            confirm = st.checkbox("Je confirme que ces brouillons sont en ligne", key=confirm_key)
            if st.button("Confirmer le lancement", key=f"launch_drop_{active_drop.get('id')}", disabled=not confirm, width="stretch"):
                if launch_drop(drops_data, active_drop.get("id"), mode="workflow"):
                    save_vinted_drops(drops_data)
                    st.success("Drop lancé.")
                    st.rerun()
    else:
        st.caption("Aucun brouillon prêt pour le lancement classique.")

    with st.expander("Publication manuelle", expanded=False):
        st.caption("Les annonces ont été créées directement sur Vinted ? Marque le Drop comme publié pour démarrer son suivi.")
        value, without_price = _drop_launch_value_summary(active_drop, available_cards)
        st.write(f"Drop : **{active_drop.get('name', 'Drop sans nom')}**")
        st.write(f"Canal : **{channel}**")
        st.write(f"Cartes concernées : **{total_cards}**")
        st.write(f"Valeur publiée : **{fp_func(value) if value else 'à définir'}**")
        if without_price:
            st.caption(f"{without_price} carte(s) sans prix exploitable : elles seront publiées, mais exclues de la valeur calculée.")

        can_launch = total_cards > 0 and channel != "Non défini"
        if not can_launch:
            st.warning("Renseigne un canal Vinted et ajoute au moins une carte au Drop avant de le publier.")
        request_key = f"request_manual_launch_drop_{active_drop.get('id')}"
        if st.button(
            "🚀 Marquer le Drop comme publié",
            key=f"manual_launch_drop_request_{active_drop.get('id')}",
            disabled=not can_launch,
            width="stretch",
        ):
            st.session_state[request_key] = True

        if st.session_state.get(request_key):
            st.info("Heure de lancement : maintenant. Les cartes non vendues passeront en ligne sans créer de brouillon.")
            confirm_key = f"confirm_manual_launch_drop_{active_drop.get('id')}"
            confirm = st.checkbox("Je confirme la mise en ligne manuelle de ce Drop", key=confirm_key)
            if st.button(
                "Confirmer la mise en ligne du Drop",
                key=f"manual_launch_drop_confirm_{active_drop.get('id')}",
                disabled=not confirm,
                type="primary",
                width="stretch",
            ):
                if launch_drop(drops_data, active_drop.get("id"), mode="manual"):
                    save_vinted_drops(drops_data)
                    st.session_state.pop(request_key, None)
                    st.session_state.pop(confirm_key, None)
                    st.success("Drop marqué comme publié.")
                    st.rerun()
                else:
                    st.error("Le Drop ne peut pas être publié : vérifie son canal, ses cartes ou son état de lancement.")


_DROP_PREPARATION_STATUSES = {"to_photograph", "needs_review", "sorted", "to_prepare"}
_DROP_PHOTO_DIRECTIONS = {
    "start_to_end": {
        "label": "📖 Photos : début des classeurs",
        "choice": "📖 J’ai commencé par le début des classeurs",
        "caption": "La file suit l’ordre des photos.",
    },
    "end_to_start": {
        "label": "🔄 Photos : fin des classeurs",
        "choice": "🔄 J’ai commencé par la fin des classeurs",
        "caption": "La file inverse les cartes photographiées, sans inverser les photos internes d’une carte.",
    },
}


def _drop_queue_skip_key(drop_id):
    return f"vinted_drop_creation_skipped_{drop_id}"


def _drop_card_ref_key(card):
    return card.get("_drop_ref_key") or drop_card_key(
        {
            "lot_uid": card.get("lot_uid", ""),
            "card_uid": card.get("card_uid", ""),
            "lot_idx": card.get("lot_idx", 0),
            "card_idx": card.get("card_idx", 0),
            "name": card.get("name", ""),
            "number": card.get("number", ""),
            "set": card.get("set", ""),
        }
    )


def _drop_workflow_quantity(card):
    return max(1, _safe_int(card.get("drop_quantity", card.get("quantity", 1)), 1))


def _drop_photo_order_value(card):
    value = card.get("photo_order")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _drop_photo_direction(drop):
    value = str((drop or {}).get("photo_capture_direction") or "").strip()
    return value if value in _DROP_PHOTO_DIRECTIONS else ""


def _set_drop_photo_direction(drops_data, drop_id, direction):
    if direction not in _DROP_PHOTO_DIRECTIONS:
        return False
    drop = find_drop(drops_data, drop_id)
    if not drop:
        return False
    drop["photo_capture_direction"] = direction
    return True


def _drop_creation_sort_key(item, direction="start_to_end"):
    position, card = item
    photo_order = _drop_photo_order_value(card)
    reverse = direction == "end_to_start"
    if photo_order is not None:
        return (0, -photo_order if reverse else photo_order, position)
    return (1, -position if reverse else position)


def _drop_creation_cards(active_drop, available_cards):
    resolved_cards, missing_cards = resolve_drop_cards_from_data(active_drop, available_cards)
    cards = list(resolved_cards) + list(missing_cards)
    direction = _drop_photo_direction(active_drop) or "start_to_end"
    ordered = [card for _pos, card in sorted(enumerate(cards), key=lambda item: _drop_creation_sort_key(item, direction))]
    workflow_cards = [
        card
        for card in ordered
        if str(card.get("status") or drop_item_status(card)) in _DROP_PREPARATION_STATUSES | {"draft_ready"}
    ]
    ready_cards = [card for card in workflow_cards if str(card.get("status") or drop_item_status(card)) == "draft_ready"]
    pending_cards = [card for card in workflow_cards if str(card.get("status") or drop_item_status(card)) in _DROP_PREPARATION_STATUSES]
    return workflow_cards, pending_cards, ready_cards


def _drop_mark_to_prepare(drops_data, drop_id, card_key):
    drop = find_drop(drops_data, drop_id)
    if not drop:
        return False
    for ref in drop.get("cards", []) or []:
        if drop_card_key(ref) != card_key:
            continue
        ref["status"] = "to_prepare"
        ref["draft_ready_at"] = ""
        ref["listing_posted"] = False
        ref["listing_posted_at"] = ""
        return True
    return False


def _drop_direction_edit_key(drop_id):
    return f"vinted_drop_photo_direction_edit_{drop_id}"


def _drop_direction_confirm_key(drop_id):
    return f"vinted_drop_photo_direction_confirm_{drop_id}"


def _apply_drop_photo_direction(drops_data, active_drop, direction):
    drop_id = active_drop.get("id")
    if not _set_drop_photo_direction(drops_data, drop_id, direction):
        return False
    st.session_state.pop(_drop_direction_edit_key(drop_id), None)
    st.session_state.pop(_drop_direction_confirm_key(drop_id), None)
    st.session_state[_drop_queue_skip_key(drop_id)] = []
    save_vinted_drops(drops_data)
    return True


def _render_drop_photo_direction_choice(drops_data, active_drop, ready_qty):
    drop_id = active_drop.get("id")
    direction = _drop_photo_direction(active_drop)
    edit_key = _drop_direction_edit_key(drop_id)
    confirm_key = _drop_direction_confirm_key(drop_id)

    if direction and not st.session_state.get(edit_key):
        info = _DROP_PHOTO_DIRECTIONS[direction]
        col_label, col_action = st.columns([4, 1])
        col_label.caption(info["label"])
        if col_action.button("Modifier", key=f"edit_photo_direction_{drop_id}", width="stretch"):
            st.session_state[edit_key] = True
            st.rerun()
        return True

    if not direction:
        st.markdown("**Dans quel sens as-tu pris les photos ?**")
        if ready_qty > 0:
            st.caption("Ce choix sera appliqué aux cartes restantes à préparer.")
    else:
        st.markdown("**Modifier le sens de prise de vue**")
        if ready_qty > 0:
            st.warning("Des brouillons existent déjà. Le changement ne modifiera pas les cartes déjà prêtes, seulement l’ordre des cartes restantes.")
            st.checkbox("Je confirme le changement de sens pour les cartes restantes", key=confirm_key)

    can_change = ready_qty <= 0 or bool(st.session_state.get(confirm_key))
    c_start, c_end = st.columns(2)
    with c_start:
        if st.button(
            _DROP_PHOTO_DIRECTIONS["start_to_end"]["choice"],
            key=f"set_photo_direction_start_{drop_id}",
            disabled=direction == "start_to_end" or not can_change,
            width="stretch",
        ):
            if _apply_drop_photo_direction(drops_data, active_drop, "start_to_end"):
                st.rerun()
        st.caption(_DROP_PHOTO_DIRECTIONS["start_to_end"]["caption"])
    with c_end:
        if st.button(
            _DROP_PHOTO_DIRECTIONS["end_to_start"]["choice"],
            key=f"set_photo_direction_end_{drop_id}",
            disabled=direction == "end_to_start" or not can_change,
            width="stretch",
        ):
            if _apply_drop_photo_direction(drops_data, active_drop, "end_to_start"):
                st.rerun()
        st.caption(_DROP_PHOTO_DIRECTIONS["end_to_start"]["caption"])

    if direction:
        if st.button("Annuler la modification", key=f"cancel_photo_direction_{drop_id}", width="stretch"):
            st.session_state.pop(edit_key, None)
            st.session_state.pop(confirm_key, None)
            st.rerun()
        return True
    return False


def _render_created_drafts_drawer(drops_data, active_drop, ready_cards, proxy_img_func, fp_func, mobile):
    ready_qty = sum(_drop_workflow_quantity(card) for card in ready_cards)
    if not _render_drop_drawer_header("created_drafts", f"Brouillons créés ({ready_qty})", default_open=False):
        return
    if not ready_cards:
        st.caption("Aucun brouillon créé pour l'instant.")
        return
    cols_count = 2 if mobile else 4
    for row_index, row in _chunked(ready_cards, cols_count):
        with st.container(horizontal=True, key=f"vinted_created_drafts_{active_drop.get('id')}_{row_index}"):
            for card in row:
                card_key = _drop_card_ref_key(card)
                with st.container(key=f"vinted_created_draft_{active_drop.get('id')}_{_safe_js_id(card_key)}"):
                    st.markdown(
                        _card_static_html(
                            card,
                            proxy_img_func,
                            fp_func,
                            badge=drop_item_status_label("draft_ready"),
                            badge_class=_drop_status_badge_class("draft_ready"),
                            drop_card=True,
                        ),
                        unsafe_allow_html=True,
                    )
                    photo_order = _drop_photo_order_value(card)
                    if photo_order is not None:
                        st.caption(f"Ordre photo : {photo_order}")
                    if st.button("Remettre à préparer", key=f"reopen_draft_drop_card_{active_drop.get('id')}_{card_key}", width="stretch"):
                        if _drop_mark_to_prepare(drops_data, active_drop.get("id"), card_key):
                            skipped = st.session_state.get(_drop_queue_skip_key(active_drop.get("id")), [])
                            st.session_state[_drop_queue_skip_key(active_drop.get("id"))] = [
                                key for key in skipped if key != card_key
                            ]
                            save_vinted_drops(drops_data)
                            st.rerun()


def _drop_card_total(drop):
    return sum(max(1, _safe_int(ref.get("quantity"), 1)) for ref in drop.get("cards", []) or [])


def _drop_value_total(drop):
    return sum(_safe_float(ref.get("price_at_add")) * max(1, _safe_int(ref.get("quantity"), 1)) for ref in drop.get("cards", []) or [])


def _off_stock_cost_for_drop(sale, lot=None, valeur_est=None, effective_purchase_price_func=None):
    if (sale or {}).get("cost_basis_known"):
        return _safe_float((sale or {}).get("cost_basis"))
    if not lot or not callable(effective_purchase_price_func):
        return None
    price = _safe_float((sale or {}).get("price"))
    if price <= 0:
        return 0.0
    try:
        if lot.get("is_mixte") and _safe_float(lot.get("valeur_totale")) > 0:
            return (price / _safe_float(lot.get("valeur_totale"), 1.0)) * _safe_float(lot.get("prix_achat_reel", lot.get("prix_achat", 0)))
        return (price / (_safe_float(valeur_est) or 1.0)) * effective_purchase_price_func(lot)
    except Exception:
        return None


def _off_stock_sale_row(sale, *, lot=None, lot_name="", cost=None):
    quantity = 0
    revenue = _safe_float((sale or {}).get("price"))
    return {
        "sale": sale,
        "card": {},
        "lot": lot or {},
        "quantity": quantity,
        "revenue": revenue,
        "displayed_total": 0.0,
        "profit": (revenue - cost) if cost is not None else None,
        "date": _parse_dt((sale or {}).get("date")),
        "card_name": (sale or {}).get("card_name") or (sale or {}).get("description") or (sale or {}).get("category") or "Vente hors stock",
        "lot_name": lot_name or (sale or {}).get("source_lot_name") or "Non attribuée",
        "is_off_stock": True,
    }


def _sale_rows_for_drop(stock_data, drop_id, calc_cout_lot_func=None, effective_purchase_price_func=None):
    rows = []
    for lot_idx, lot in enumerate((stock_data or {}).get("lots", []) or []):
        costs_by_sale_id = {}
        valeur_estimee = None
        if callable(calc_cout_lot_func):
            try:
                cost_rows, valeur_estimee = calc_cout_lot_func(lot, lot_idx=lot_idx)
                costs_by_sale_id = {se.get("sale_id"): cost for _, se, cost in cost_rows if se.get("sale_id")}
            except Exception:
                costs_by_sale_id = {}
        for sale in lot.get("ventes", []) or []:
            if not sale.get("is_off_stock") or str(sale.get("drop_id") or "") != str(drop_id or ""):
                continue
            cost = _off_stock_cost_for_drop(
                sale,
                lot=lot,
                valeur_est=valeur_estimee,
                effective_purchase_price_func=effective_purchase_price_func,
            )
            rows.append(_off_stock_sale_row(sale, lot=lot, lot_name=lot.get("nom", ""), cost=cost))
        for card in lot.get("cards", []) or []:
            for sale in card.get("sold_entries", []) or []:
                if str(sale.get("drop_id") or "") != str(drop_id or ""):
                    continue
                quantity = max(1, _safe_int(sale.get("quantity"), 1))
                revenue = _safe_float(sale.get("price"))
                suggested_unit = _safe_float(sale.get("suggested_price_at_sale"))
                displayed_total = suggested_unit * quantity
                cost = costs_by_sale_id.get(sale.get("sale_id"))
                rows.append({
                    "sale": sale,
                    "card": card,
                    "lot": lot,
                    "quantity": quantity,
                    "revenue": revenue,
                    "displayed_total": displayed_total,
                    "profit": (revenue - cost) if cost is not None else None,
                    "date": _parse_dt(sale.get("date")),
                    "card_name": sale.get("card_name") or card.get("name", ""),
                    "lot_name": lot.get("nom", ""),
                })
    for sale in (stock_data or {}).get("ventes_hors_stock", []) or []:
        if str(sale.get("drop_id") or "") != str(drop_id or ""):
            continue
        rows.append(_off_stock_sale_row(sale, cost=_off_stock_cost_for_drop(sale)))
    return rows


def _analytics_transaction_key(row, index):
    sale = row.get("sale") or {}
    transaction_id = str(sale.get("sale_transaction_id") or sale.get("transaction_id") or "").strip()
    if transaction_id:
        return transaction_id
    sale_id = str(sale.get("sale_id") or "").strip()
    if sale_id:
        return sale_id
    return f"{row.get('date')}:{row.get('card_name', '')}:{index}"


def _sales_scope_metrics(rows):
    """Keep card-only and total Drop-sale metrics on explicit, compatible scopes."""
    rows = list(rows or [])
    physical_rows = [row for row in rows if _safe_int(row.get("quantity"), 0) > 0]
    off_stock_rows = [row for row in rows if row.get("is_off_stock")]
    all_transaction_keys = {_analytics_transaction_key(row, index) for index, row in enumerate(rows)}
    card_transaction_keys = {_analytics_transaction_key(row, index) for index, row in enumerate(physical_rows)}
    off_stock_transaction_keys = {
        _analytics_transaction_key(row, index)
        for index, row in enumerate(rows)
        if row.get("is_off_stock") and _analytics_transaction_key(row, index) not in card_transaction_keys
    }
    sold_cards = sum(_safe_int(row.get("quantity"), 0) for row in physical_rows)
    ca_cards = sum(_safe_float(row.get("revenue")) for row in physical_rows)
    ca_off_stock = sum(_safe_float(row.get("revenue")) for row in off_stock_rows)
    return {
        "physical_rows": physical_rows,
        "off_stock_rows": off_stock_rows,
        "sold_cards": sold_cards,
        "ca_total": sum(_safe_float(row.get("revenue")) for row in rows),
        "ca_cards": ca_cards,
        "ca_off_stock": ca_off_stock,
        "total_transactions": len(all_transaction_keys),
        "card_transactions": len(card_transaction_keys),
        "off_stock_transactions": len(off_stock_transaction_keys),
    }


def _physical_price_band_rows(drop, rows):
    """Return physical sales paired with their published Drop price, never off-stock sales."""
    refs_by_item_id = {
        str(ref.get("drop_item_id") or ""): ref
        for ref in drop.get("cards", []) or []
        if str(ref.get("drop_item_id") or "")
    }
    refs_by_uid = {}
    for ref in drop.get("cards", []) or []:
        uid = str(ref.get("card_uid") or "")
        if uid:
            refs_by_uid.setdefault(uid, []).append(ref)

    paired = []
    for row in _sales_scope_metrics(rows)["physical_rows"]:
        sale = row.get("sale") or {}
        ref = refs_by_item_id.get(str(sale.get("drop_item_id") or ""))
        if ref is None:
            options = refs_by_uid.get(str((row.get("card") or {}).get("card_uid") or ""), [])
            ref = options[0] if len(options) == 1 else None
        if ref is None:
            continue
        published_price = _safe_float(ref.get("price_at_add"))
        if published_price > 0:
            paired.append((row, published_price))
    return paired


def _drop_metrics(drop, sales_rows):
    counts = _drop_status_counts(drop)
    total_cards = _drop_card_total(drop)
    scope = _sales_scope_metrics(sales_rows)
    revenue = scope["ca_total"]
    known_profits = [row["profit"] for row in sales_rows if row.get("profit") is not None]
    sold_cards = scope["sold_cards"] or counts.get("sold", 0)
    return {
        "cards": total_cards,
        "to_photograph": counts.get("to_photograph", 0),
        "draft_ready": counts.get("draft_ready", 0),
        "online": counts.get("online", 0),
        "sold": sold_cards,
        "published_value": _drop_value_total(drop),
        "revenue": revenue,
        "ca_total": revenue,
        "ca_cards": scope["ca_cards"],
        "ca_off_stock": scope["ca_off_stock"],
        "profit": sum(known_profits) if known_profits else None,
        "profit_total": sum(known_profits) if known_profits else None,
        "sell_through": (sold_cards / total_cards * 100.0) if total_cards else None,
        "avg_sold_price": (scope["ca_cards"] / sold_cards) if sold_cards else None,
        "avg_basket": (revenue / scope["total_transactions"]) if scope["total_transactions"] else None,
        "card_transactions": scope["card_transactions"],
        "off_stock_transactions": scope["off_stock_transactions"],
        "avg_cards_per_transaction": (sold_cards / scope["card_transactions"]) if scope["card_transactions"] else None,
    }


def _render_kpis(metrics, fp_func):
    items = [
        ("Cartes sélectionnées", str(metrics.get("cards", 0))),
        ("Brouillons prêts", str(metrics.get("draft_ready", 0))),
        ("En ligne", str(metrics.get("online", 0))),
        ("Vendues", str(metrics.get("sold", 0))),
        ("Valeur publiée", fp_func(metrics.get("published_value", 0))),
        ("CA", fp_func(metrics.get("revenue", 0))),
        ("Bénéfice", fp_func(metrics["profit"]) if metrics.get("profit") is not None else "N/A"),
        ("Marge", f"{(metrics['profit'] / metrics['revenue'] * 100):.1f}%" if metrics.get("profit") is not None and metrics.get("revenue") else "N/A"),
        ("Taux d'écoulement", f"{metrics['sell_through']:.1f}%" if metrics.get("sell_through") is not None else "N/A"),
        ("Prix moyen vendu", fp_func(metrics["avg_sold_price"]) if metrics.get("avg_sold_price") is not None else "N/A"),
        ("Panier moyen", fp_func(metrics["avg_basket"]) if metrics.get("avg_basket") is not None else "N/A"),
        ("Cartes / transaction", f"{metrics['avg_cards_per_transaction']:.2f}" if metrics.get("avg_cards_per_transaction") is not None else "N/A"),
    ]
    html = '<div class="ps-vinted-kpi-grid">' + "".join(
        f'<div class="ps-vinted-kpi"><span>{_html_escape(label)}</span><strong>{_html_escape(value)}</strong></div>'
        for label, value in items
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _negotiation_stats(rows):
    diffs = []
    pct = []
    under = equal = above = 0
    for row in rows:
        displayed = row.get("displayed_total", 0)
        if displayed <= 0:
            continue
        diff = row.get("revenue", 0) - displayed
        diffs.append(diff)
        pct.append(diff / displayed * 100.0)
        if abs(diff) < 0.01:
            equal += 1
        elif diff < 0:
            under += 1
        else:
            above += 1
    pct_sorted = sorted(pct)
    median = pct_sorted[len(pct_sorted) // 2] if pct_sorted else None
    if pct_sorted and len(pct_sorted) % 2 == 0:
        median = (pct_sorted[len(pct_sorted) // 2 - 1] + pct_sorted[len(pct_sorted) // 2]) / 2
    total = len(pct)
    return {
        "avg_pct": (sum(pct) / total) if total else None,
        "median_pct": median,
        "equal_pct": equal / total * 100.0 if total else None,
        "under_pct": under / total * 100.0 if total else None,
        "above_pct": above / total * 100.0 if total else None,
        "total_diff": sum(diffs),
    }


def _render_drop_timing(drop, rows, fp_func):
    launched = _parse_dt(drop.get("drop_launched_at"))
    if not launched:
        st.caption("Temporalité : N/A, drop non lancé.")
        return
    rows = sorted([row for row in rows if row.get("date")], key=lambda row: row["date"])
    if not rows:
        st.caption("Aucune vente liée après lancement.")
        return
    first = rows[0]["date"] - launched
    st.markdown(f"**Première vente :** {_duration_label(first)}")
    thresholds = [50, 100, 200, 500, 1000, 2000]
    cumulative = 0.0
    reached = {}
    for row in rows:
        cumulative += row["revenue"]
        for threshold in thresholds:
            if threshold not in reached and cumulative >= threshold:
                reached[threshold] = _duration_label(row["date"] - launched)
    if reached:
        st.caption("Seuils CA atteints : " + " · ".join(f"{fp_func(k)} : {v}" for k, v in reached.items()))
    total_cards = _drop_card_total(drop)
    if total_cards:
        sold = 0
        reached_cards = {}
        for row in rows:
            sold += row["quantity"]
            for threshold in (10, 25, 50, 75):
                if threshold not in reached_cards and sold / total_cards * 100.0 >= threshold:
                    reached_cards[threshold] = _duration_label(row["date"] - launched)
        if reached_cards:
            st.caption("Écoulement atteint : " + " · ".join(f"{k}% : {v}" for k, v in reached_cards.items()))
    for days in (0, 1, 3, 7, 30):
        cutoff = launched + timedelta(days=days + 1)
        ca = sum(row["revenue"] for row in rows if row["date"] < cutoff)
        cards = sum(row["quantity"] for row in rows if row["date"] < cutoff)
        st.caption(f"J{days} : {fp_func(ca)} · {cards} carte(s)")


def _render_drop_charts(drop, rows):
    launched = _parse_dt(drop.get("drop_launched_at"))
    if not launched or not rows:
        return
    try:
        import pandas as pd
    except Exception:
        return
    ordered = sorted([row for row in rows if row.get("date")], key=lambda row: row["date"])
    cumulative_ca = cumulative_profit = cumulative_cards = 0.0
    chart_rows = []
    total_cards = max(1, _drop_card_total(drop))
    for row in ordered:
        cumulative_ca += row["revenue"]
        cumulative_cards += row["quantity"]
        if row.get("profit") is not None:
            cumulative_profit += row["profit"]
        chart_rows.append({
            "J+": max(0, (row["date"] - launched).days),
            "CA cumulé": cumulative_ca,
            "Bénéfice cumulé": cumulative_profit,
            "Cartes vendues": cumulative_cards,
            "Taux écoulement": cumulative_cards / total_cards * 100.0,
        })
    if chart_rows:
        df = pd.DataFrame(chart_rows).groupby("J+", as_index=True).max()
        st.line_chart(df[["CA cumulé", "Bénéfice cumulé"]])
        st.line_chart(df[["Cartes vendues", "Taux écoulement"]])


def _analytics_price_bands(selected, rows_by_drop_id):
    bands = [("< 2 €", 0, 2), ("2–5 €", 2, 5), ("5–10 €", 5, 10), ("10–20 €", 10, 20), ("20 €+", 20, float("inf"))]
    results = []
    for label, low, high in bands:
        published = sold = 0
        ca = 0.0
        for drop in selected:
            for ref in drop.get("cards", []) or []:
                price = _safe_float(ref.get("price_at_add"))
                if low <= price < high:
                    published += max(1, _safe_int(ref.get("quantity"), 1))
            rows = rows_by_drop_id.get(str(drop.get("id") or ""), [])
            for row, published_price in _physical_price_band_rows(drop, rows):
                if low <= published_price < high:
                    sold += _safe_int(row.get("quantity"), 0)
                    ca += _safe_float(row.get("revenue"))
        results.append({
            "label": label,
            "published": published,
            "sold": sold,
            "sell_through": sold / published * 100.0 if published else None,
            "ca": ca,
        })
    return results


_ANALYTICS_CHECKPOINTS = (
    ("H+1", 1), ("H+6", 6), ("H+12", 12), ("H+24", 24),
    ("H+48", 48), ("J+3", 72), ("J+7", 168), ("J+30", 720),
)
_ANALYTICS_CHART_INTERPOLATION = "monotone"


def _group_drop_transactions(rows):
    """Turn sale lines into one chronological event per logical order."""
    grouped = {}
    for index, row in enumerate(rows or []):
        if not row.get("date"):
            continue
        key = _analytics_transaction_key(row, index)
        grouped.setdefault(key, []).append(row)

    events = []
    for transaction_id, lines in grouped.items():
        dated_lines = sorted(lines, key=lambda line: line["date"])
        physical_lines = [line for line in lines if _safe_int(line.get("quantity"), 0) > 0]
        off_stock_lines = [line for line in lines if line.get("is_off_stock")]
        known_profits = [line.get("profit") for line in lines if line.get("profit") is not None]
        has_unknown_profit = any(line.get("profit") is None for line in lines)
        kind = "mixed" if physical_lines and off_stock_lines else ("hors stock" if off_stock_lines else "cartes")
        events.append({
            "transaction_id": transaction_id,
            "timestamp": dated_lines[0]["date"],
            "revenue": sum(_safe_float(line.get("revenue")) for line in lines),
            "profit": None if has_unknown_profit else sum(_safe_float(value) for value in known_profits),
            "sold_cards": sum(_safe_int(line.get("quantity"), 0) for line in physical_lines),
            "kind": kind,
            "line_count": len(lines),
            "is_off_stock": bool(off_stock_lines) and not bool(physical_lines),
            "is_mixed": bool(off_stock_lines) and bool(physical_lines),
        })
    return sorted(events, key=lambda event: event["timestamp"])


def _analytics_snapshot_at(drop, rows, cutoff):
    """Return cumulative metrics at an exact elapsed-time cutoff."""
    launched = _parse_dt(drop.get("drop_launched_at"))
    if not launched or cutoff is None:
        return {"revenue": 0.0, "profit": None, "sold": 0, "sell_through": None, "transactions": 0}
    events = [event for event in _group_drop_transactions(rows) if launched <= event["timestamp"] <= cutoff]
    known_profits = [event["profit"] for event in events if event.get("profit") is not None]
    has_unknown_profit = any(event.get("profit") is None for event in events)
    sold = sum(event["sold_cards"] for event in events)
    total_cards = _drop_card_total(drop)
    return {
        "revenue": sum(event["revenue"] for event in events),
        "profit": None if has_unknown_profit else sum(_safe_float(value) for value in known_profits),
        "sold": sold,
        "sell_through": sold / total_cards * 100.0 if total_cards else None,
        "transactions": len(events),
    }


def _analytics_time_series(drop, rows, *, now=None, range_hours=None):
    """Precise cumulative series with a launch point and optional flat visual end."""
    launched = _parse_dt(drop.get("drop_launched_at"))
    if not launched:
        return []
    reference_now = now or datetime.now()
    end = reference_now
    if range_hours is not None:
        end = min(reference_now, launched + timedelta(hours=range_hours))
    if end < launched:
        end = launched

    total_cards = _drop_card_total(drop)
    series = [{
        "timestamp": launched,
        "elapsed_hours": 0.0,
        "revenue": 0.0,
        "profit": 0.0,
        "sold": 0,
        "sell_through": 0.0,
        "transaction_revenue": None,
        "event_label": "Lancement du Drop",
        "event_kind": "initial",
        "transaction_type": "Lancement",
        "is_transaction": False,
    }]
    cumulative_revenue = cumulative_profit = 0.0
    cumulative_sold = 0
    for event in _group_drop_transactions(rows):
        if event["timestamp"] < launched or event["timestamp"] > end:
            continue
        cumulative_revenue += event["revenue"]
        cumulative_sold += event["sold_cards"]
        if event.get("profit") is not None:
            cumulative_profit += _safe_float(event["profit"])
        event_label = {"mixed": "Transaction mixte", "hors stock": "Transaction hors stock", "cartes": "Transaction cartes"}[event["kind"]]
        transaction_type = {"mixed": "Mixte", "hors stock": "Hors stock", "cartes": "Cartes"}[event["kind"]]
        series.append({
            "timestamp": event["timestamp"],
            "elapsed_hours": max(0.0, (event["timestamp"] - launched).total_seconds() / 3600.0),
            "revenue": cumulative_revenue,
            "profit": cumulative_profit,
            "sold": cumulative_sold,
            "sell_through": cumulative_sold / total_cards * 100.0 if total_cards else 0.0,
            "transaction_revenue": event["revenue"],
            "event_label": event_label,
            "event_kind": event["kind"],
            "transaction_type": transaction_type,
            "is_transaction": True,
            "transaction_id": event["transaction_id"],
        })
    if end > series[-1]["timestamp"]:
        series.append({
            **{key: value for key, value in series[-1].items() if key not in {"timestamp", "elapsed_hours", "event_label", "event_kind", "is_transaction", "transaction_revenue", "transaction_id"}},
            "timestamp": end,
            "elapsed_hours": max(0.0, (end - launched).total_seconds() / 3600.0),
            "transaction_revenue": None,
            "event_label": "Fin de période (sans transaction)",
            "event_kind": "terminal",
            "transaction_type": "Fin de période",
            "is_transaction": False,
        })
    return series


def _analytics_milestones(drop, rows):
    launched = _parse_dt(drop.get("drop_launched_at"))
    if not launched:
        return {}
    total_cards = _drop_card_total(drop)
    cumulative_revenue = cumulative_sold = 0.0
    milestones = {}
    for event in _group_drop_transactions(rows):
        if event["timestamp"] < launched:
            continue
        cumulative_revenue += event["revenue"]
        cumulative_sold += event["sold_cards"]
        elapsed = event["timestamp"] - launched
        if "first_sale" not in milestones:
            milestones["first_sale"] = elapsed
        for amount in (50, 100, 200, 500, 1000):
            key = f"ca_{amount}"
            if key not in milestones and cumulative_revenue >= amount:
                milestones[key] = elapsed
        for percent in (10, 25, 50, 75):
            key = f"sold_{percent}"
            if total_cards and key not in milestones and cumulative_sold / total_cards * 100.0 >= percent:
                milestones[key] = elapsed
    return milestones


def _analytics_timing(drop, rows, *, now=None):
    launched = _parse_dt(drop.get("drop_launched_at"))
    reference_now = now or datetime.now()
    checkpoints = []
    for label, hours in _ANALYTICS_CHECKPOINTS:
        cutoff = launched + timedelta(hours=hours) if launched else None
        if cutoff is None or cutoff > reference_now:
            checkpoints.append({"label": label, "hours": hours, "upcoming": True})
            continue
        checkpoints.append({"label": label, "hours": hours, "upcoming": False, **_analytics_snapshot_at(drop, rows, cutoff)})
    milestones_raw = _analytics_milestones(drop, rows)
    return {
        "launched": launched,
        "milestone_deltas": milestones_raw,
        "milestones": {key: _duration_label(value) for key, value in milestones_raw.items()},
        "checkpoints": checkpoints,
        "series": _analytics_time_series(drop, rows, now=reference_now),
    }


def _analytics_metrics_at(drop, rows, cutoff):
    """Compute the established metrics from transactions known at one timestamp."""
    dated_rows = [row for row in rows or [] if row.get("date") and row["date"] <= cutoff]
    scope = _sales_scope_metrics(dated_rows)
    known_profits = [row["profit"] for row in dated_rows if row.get("profit") is not None]
    total_cards = _drop_card_total(drop)
    revenue = scope["ca_total"]
    profit = sum(known_profits) if known_profits else None
    sold = scope["sold_cards"]
    return {
        "revenue": revenue,
        "profit": profit,
        "sold": sold,
        "sell_through": sold / total_cards * 100.0 if total_cards else None,
        "avg_sold_price": scope["ca_cards"] / sold if sold else None,
        "avg_basket": revenue / scope["total_transactions"] if scope["total_transactions"] else None,
        "avg_cards_per_transaction": sold / scope["card_transactions"] if scope["card_transactions"] else None,
        "margin": profit / revenue * 100.0 if profit is not None and revenue else None,
        "published_value": _drop_value_total(drop),
        "cards": total_cards,
        "transactions": scope["total_transactions"],
    }


def _comparison_horizon_hours(primary_drop, primary_rows, reference_drop, reference_rows, *, now=None, full_history=False):
    reference_now = now or datetime.now()

    def observable_hours(drop, rows):
        launched = _parse_dt(drop.get("drop_launched_at"))
        if not launched:
            return 0.0
        event_times = [event["timestamp"] for event in _group_drop_transactions(rows) if event["timestamp"] >= launched]
        endpoint = max(event_times) if full_history and event_times else reference_now
        return max(0.0, (endpoint - launched).total_seconds() / 3600.0)

    primary_hours = observable_hours(primary_drop, primary_rows)
    reference_hours = observable_hours(reference_drop, reference_rows)
    return max(primary_hours, reference_hours) if full_history else min(primary_hours, reference_hours)


def _comparison_time_series(primary_drop, primary_rows, reference_drop, reference_rows, *, now=None, full_history=False):
    primary_launch = _parse_dt(primary_drop.get("drop_launched_at"))
    reference_launch = _parse_dt(reference_drop.get("drop_launched_at"))
    if not primary_launch or not reference_launch:
        return []
    horizon = _comparison_horizon_hours(
        primary_drop, primary_rows, reference_drop, reference_rows, now=now, full_history=full_history,
    )
    elapsed_points = {0.0, horizon}
    event_hours = {}
    for key, rows, launched in (("primary", primary_rows, primary_launch), ("reference", reference_rows, reference_launch)):
        event_hours[key] = set()
        for event in _group_drop_transactions(rows):
            elapsed = (event["timestamp"] - launched).total_seconds() / 3600.0
            if 0.0 <= elapsed <= horizon:
                elapsed_points.add(elapsed)
                event_hours[key].add(elapsed)
    series = []
    for elapsed in sorted(elapsed_points):
        primary = _analytics_metrics_at(primary_drop, primary_rows, primary_launch + timedelta(hours=elapsed))
        reference = _analytics_metrics_at(reference_drop, reference_rows, reference_launch + timedelta(hours=elapsed))
        series.append({
            "elapsed_hours": elapsed,
            "elapsed_label": f"H+{_duration_label(timedelta(hours=elapsed))}",
            "primary": primary,
            "reference": reference,
            "primary_is_transaction": elapsed in event_hours["primary"],
            "reference_is_transaction": elapsed in event_hours["reference"],
        })
    return series


def _analytics_remaining_items(selected, *, now=None, limit=5):
    reference_now = now or datetime.now()
    items = []
    total_value = remaining_value = 0.0
    remaining_cards = 0
    for drop in selected:
        for ref in drop.get("cards", []) or []:
            quantity = max(1, _safe_int(ref.get("quantity"), 1))
            value = _safe_float(ref.get("price_at_add")) * quantity
            total_value += value
            if drop_item_status(ref) == "sold":
                continue
            remaining_cards += quantity
            remaining_value += value
            if drop_item_status(ref) != "online":
                continue
            online_at = _parse_dt(ref.get("online_at"))
            days_online = max(0, (reference_now - online_at).days) if online_at else None
            price = _safe_float(ref.get("price_at_add"))
            band = next((label for label, low, high in [("< 2 €", 0, 2), ("2–5 €", 2, 5), ("5–10 €", 5, 10), ("10–20 €", 10, 20), ("20 €+", 20, float("inf"))] if low <= price < high), "Sans prix")
            items.append({
                "name": _ui_text(ref.get("name"), "Carte sans nom"),
                "number": _card_number(ref),
                "price": price,
                "days_online": days_online,
                "band": band,
                "status": drop_item_status_label(ref),
                "online_label": (
                    f"{days_online} j en ligne"
                    if days_online is not None
                    else "En ligne"
                ),
            })
    items.sort(key=lambda item: item["price"], reverse=True)
    return {
        "remaining_cards": remaining_cards,
        "remaining_value": remaining_value,
        "remaining_value_pct": remaining_value / total_value * 100.0 if total_value else None,
        "top_online": items[:limit],
    }


def _analytics_highlights(rows, drop):
    physical_rows = _sales_scope_metrics(rows)["physical_rows"]
    dated_rows = [row for row in physical_rows if row.get("date")]
    launched = _parse_dt(drop.get("drop_launched_at"))
    best_margin = max((row for row in physical_rows if row.get("profit") is not None), key=lambda row: row["profit"], default=None)
    best_margin_pct = max(
        (row for row in physical_rows if row.get("profit") is not None and _safe_float(row.get("revenue")) > 0),
        key=lambda row: _safe_float(row.get("profit")) / _safe_float(row.get("revenue")),
        default=None,
    )
    fastest = min(dated_rows, key=lambda row: row["date"], default=None)
    return {
        "largest_sale": max(physical_rows, key=lambda row: _safe_float(row.get("revenue")), default=None),
        "best_margin": best_margin,
        "best_margin_pct": best_margin_pct,
        "fastest": fastest,
        "launched": launched,
    }


def _analytics_insights(price_bands, negotiation):
    insights = []
    eligible = [band for band in price_bands if band["published"]]
    if eligible:
        strongest = max(eligible, key=lambda band: band["sell_through"] or 0)
        weakest = min(eligible, key=lambda band: band["sell_through"] or 0)
        insights.append(f"Les cartes {strongest['label']} affichent un sell-through de {strongest['sell_through']:.0f} %.")
        if weakest["label"] != strongest["label"]:
            insights.append(f"Les cartes {weakest['label']} tournent le moins vite : {weakest['sell_through']:.0f} %.")
    if negotiation.get("equal_pct") is not None:
        insights.append(f"{negotiation['equal_pct']:.1f} % des ventes avec prix de référence sont réalisées au prix affiché.")
    return insights


def _analytics_header_date(value):
    date = _parse_dt(value)
    if not date:
        return "date de lancement non renseignée"
    months = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
    return f"lancé le {date.day} {months[date.month - 1]} {date.year}"


def _analytics_chart_style(chart):
    return (
        chart.configure_view(stroke=None)
        .configure_axis(domain=False, gridColor="#eef0f3", gridOpacity=1, labelColor="#6b7280", tickColor="#d1d5db", titleColor="#4b5563")
        .configure_title(color="#111827", fontSize=13, fontWeight=700, anchor="start", offset=8)
        .configure_legend(orient="top", direction="horizontal", labelColor="#4b5563", title=None)
    )


def _analytics_time_axis(series, alt):
    timestamps = [point.get("timestamp") for point in series if point.get("timestamp")]
    if len(timestamps) < 2:
        return alt.Axis(format="%H:%M", tickCount=5, labelAngle=0, labelPadding=8)
    span_hours = max(0.0, (max(timestamps) - min(timestamps)).total_seconds() / 3600.0)
    if span_hours <= 24:
        return alt.Axis(format="%H:%M", tickCount=7, labelAngle=0, labelPadding=8)
    if span_hours <= 72:
        return alt.Axis(format="%d %b\n%Hh", tickCount=7, labelAngle=0, labelPadding=8)
    if span_hours <= 168:
        return alt.Axis(format="%d %b\n%Hh", tickCount=7, labelAngle=0, labelPadding=8)
    return alt.Axis(format="%d %b", tickCount=7, labelAngle=0, labelPadding=8)


def _analytics_elapsed_axis(horizon_hours, alt):
    if horizon_hours <= 24:
        return alt.Axis(title="Temps depuis le lancement", tickCount=7, labelExpr="datum.value + ' h'")
    if horizon_hours <= 168:
        return alt.Axis(title="Temps depuis le lancement", tickCount=7, labelExpr="datum.value < 24 ? datum.value + ' h' : 'J+' + format(datum.value / 24, '.0f')")
    return alt.Axis(title="Temps depuis le lancement", tickCount=7, labelExpr="'J+' + format(datum.value / 24, '.0f')")


def _render_analytics_charts(series, *, mode="CA & bénéfice", key="vinted_analytics_chart"):
    if not series:
        st.caption("Les courbes apparaîtront dès les premières ventes liées au Drop.")
        return
    try:
        import altair as alt
        import pandas as pd
    except Exception:
        fields = ("revenue", "profit") if mode == "CA & bénéfice" else ("sold", "sell_through")
        st.line_chart({field: [point.get(field, 0) for point in series] for field in fields})
        return

    frame = pd.DataFrame(series)
    launch = next((point for point in series if point.get("event_kind") == "initial"), None)
    tooltip = [
        alt.Tooltip("timestamp:T", title="Date", format="%d %b %Y · %H:%M"),
        alt.Tooltip("event_label:N", title="Événement"),
        alt.Tooltip("transaction_type:N", title="Type"),
        alt.Tooltip("transaction_revenue:Q", title="Transaction", format="+.2f"),
        alt.Tooltip("revenue:Q", title="CA cumulé", format=".2f"),
        alt.Tooltip("profit:Q", title="Bénéfice cumulé", format=".2f"),
        alt.Tooltip("sold:Q", title="Cartes vendues", format=".0f"),
        alt.Tooltip("sell_through:Q", title="Taux d'écoulement", format=".1f"),
    ]
    base = alt.Chart(frame).encode(
        x=alt.X("timestamp:T", title=None, axis=_analytics_time_axis(series, alt)),
        tooltip=tooltip,
    )
    transaction_hover = alt.selection_point(on="pointerover", fields=["timestamp"], nearest=True, empty=False)
    if mode == "CA & bénéfice":
        chart = alt.layer(
            base.mark_line(color="#6d28d9", strokeWidth=2.6, interpolate=_ANALYTICS_CHART_INTERPOLATION).encode(y=alt.Y("revenue:Q", title="Montant (€)"), color=alt.value("#6d28d9")),
            base.mark_line(color="#16a34a", strokeWidth=2.6, interpolate=_ANALYTICS_CHART_INTERPOLATION).encode(y=alt.Y("profit:Q", title="Montant (€)"), color=alt.value("#16a34a")),
            base.transform_filter("datum.is_transaction").mark_point(color="#6d28d9", stroke="#ffffff", strokeWidth=1.2, filled=True).encode(y=alt.Y("revenue:Q"), size=alt.condition(transaction_hover, alt.value(92), alt.value(40))).add_params(transaction_hover),
        ).properties(height=285, title="CA cumulé · Bénéfice cumulé")
    else:
        chart = alt.layer(
            base.mark_line(color="#2563eb", strokeWidth=2.6, interpolate=_ANALYTICS_CHART_INTERPOLATION).encode(y=alt.Y("sold:Q", title="Cartes")),
            base.mark_line(color="#f97316", strokeWidth=2.4, interpolate=_ANALYTICS_CHART_INTERPOLATION, strokeDash=[5, 3]).encode(y=alt.Y("sell_through:Q", title="Taux d’écoulement (%)")),
            base.transform_filter("datum.is_transaction").mark_point(color="#2563eb", stroke="#ffffff", strokeWidth=1.2, filled=True).encode(y=alt.Y("sold:Q"), size=alt.condition(transaction_hover, alt.value(92), alt.value(40))).add_params(transaction_hover),
        ).resolve_scale(y="independent").properties(height=285, title="Cartes vendues · Taux d’écoulement")
    if launch:
        launch_rule = alt.Chart(pd.DataFrame([launch])).mark_rule(color="#7c3aed", strokeDash=[4, 3], strokeWidth=1.4).encode(x="timestamp:T")
        launch_label = alt.Chart(pd.DataFrame([launch])).mark_text(align="left", baseline="top", dx=5, dy=4, color="#6d28d9", fontSize=11, fontWeight=700).encode(x="timestamp:T", text=alt.value(f"Lancement · {launch['timestamp'].strftime('%d %b %H:%M')}"))
        chart = alt.layer(chart, launch_rule, launch_label)
    st.altair_chart(_analytics_chart_style(chart), width="stretch", key=key)


def _analytics_view_control():
    options = ("Vue d’ensemble", "Analyse détaillée", "Comparaison")
    if "drop_analytics_view" not in st.session_state:
        st.session_state["drop_analytics_view"] = options[0]
    if hasattr(st, "segmented_control"):
        return st.segmented_control("Vue analytics", options, key="drop_analytics_view", label_visibility="collapsed") or options[0]
    return st.pills("Vue analytics", options, key="drop_analytics_view", selection_mode="single", label_visibility="collapsed") or options[0]


def _analytics_kpis_html(metrics, fp_func, *, include_cards_per_transaction=False):
    margin = metrics["profit"] / metrics["revenue"] * 100.0 if metrics.get("profit") is not None and metrics.get("revenue") else None
    primary = [
        ("CA total", fp_func(metrics["ca_total"]), "violet"),
        ("Bénéfice", fp_func(metrics["profit"]) if metrics.get("profit") is not None else "N/A", "success"),
        ("Taux d’écoulement", f"{metrics['sell_through']:.1f} %" if metrics.get("sell_through") is not None else "N/A", "orange"),
        ("Vendues", f"{metrics['sold']} / {metrics['cards']}", "blue"),
    ]
    secondary = [
        ("Valeur publiée", fp_func(metrics["published_value"])),
        ("Marge", f"{margin:.1f} %" if margin is not None else "N/A"),
        ("Prix moyen carte", fp_func(metrics["avg_sold_price"]) if metrics.get("avg_sold_price") is not None else "N/A"),
        ("Panier moyen", fp_func(metrics["avg_basket"]) if metrics.get("avg_basket") is not None else "N/A"),
    ]
    if include_cards_per_transaction:
        secondary.append(("Cartes / transaction", f"{metrics['avg_cards_per_transaction']:.2f}" if metrics.get("avg_cards_per_transaction") is not None else "N/A"))
    primary_html = "".join(
        f'<div class="ps-analytics-kpi ps-analytics-kpi--{tone}"><span>{_html_escape(label)}</span><strong>{_html_escape(value)}</strong></div>'
        for label, value, tone in primary
    )
    secondary_html = "".join(
        f'<div class="ps-analytics-stat"><span>{_html_escape(label)}</span><strong>{_html_escape(value)}</strong></div>'
        for label, value in secondary
    )
    return f'<div class="ps-analytics-kpi-grid">{primary_html}</div><div class="ps-analytics-stat-grid">{secondary_html}</div>'


def _analytics_revenue_breakdown_html(metrics, fp_func, *, compact=False):
    total = _safe_float(metrics.get("ca_total"))
    cards = _safe_float(metrics.get("ca_cards"))
    off_stock = _safe_float(metrics.get("ca_off_stock"))
    cards_pct = max(0.0, min(100.0, cards / total * 100.0)) if total else 0.0
    off_stock_pct = max(0.0, min(100.0, off_stock / total * 100.0)) if total else 0.0
    title = "CA" if compact else "Décomposition du CA"
    subtitle = "Cartes et hors stock, sur le même périmètre." if compact else "Le total inclut les ventes hors stock liées au Drop."
    return (
        f'<section class="ps-analytics-surface"><div class="ps-analytics-section-heading"><div><h3>{title}</h3><p>{subtitle}</p></div></div>'
        f'<div class="ps-analytics-revenue-total"><span>CA total</span><strong>{_html_escape(fp_func(total))}</strong></div>'
        f'<div class="ps-analytics-revenue-bar" title="Cartes : {cards_pct:.1f} % · Hors stock : {off_stock_pct:.1f} %"><i style="width:{cards_pct:.2f}%"></i><b style="width:{off_stock_pct:.2f}%"></b></div>'
        f'<div class="ps-analytics-breakdown"><span>Cartes physiques</span><strong>{_html_escape(fp_func(cards))}</strong><span>Hors stock</span><strong>{_html_escape(fp_func(off_stock))}</strong></div></section>'
    )


def _analytics_milestone_html(timing, *, compact=False):
    milestones = timing["milestones"]
    rows = [
        ("Lancement", "Point de départ"), ("Première vente", milestones.get("first_sale", "Non atteint")),
        ("50 €", milestones.get("ca_50", "Non atteint")), ("100 €", milestones.get("ca_100", "Non atteint")),
        ("200 €", milestones.get("ca_200", "Non atteint")), ("500 €", milestones.get("ca_500", "Non atteint")),
        ("10 % vendu", milestones.get("sold_10", "Non atteint")), ("25 % vendu", milestones.get("sold_25", "Non atteint")),
        ("50 % vendu", milestones.get("sold_50", "Non atteint")), ("75 % vendu", milestones.get("sold_75", "Non atteint")),
    ]
    class_name = "ps-analytics-timeline ps-analytics-timeline--compact" if compact else "ps-analytics-timeline"
    return f'<div class="{class_name}">' + "".join(
        f'<div class="ps-analytics-timeline-item"><span>{_html_escape(label)}</span><strong>{_html_escape(value)}</strong></div>'
        for label, value in rows
    ) + "</div>"


def _analytics_price_bands_html(price_bands, fp_func):
    rows = "".join(
        f'<div class="ps-analytics-band"><strong>{_html_escape(band["label"])}</strong><span>{band["published"]} publiées · {band["sold"]} vendues</span><div><i class="{"good" if (band["sell_through"] or 0) >= 40 else "watch"}" style="width:{band["sell_through"] or 0:.2f}%"></i></div><b>{"N/A" if band["sell_through"] is None else f"{band["sell_through"]:.0f} %"}</b><em>{_html_escape(fp_func(band["ca"]))}</em></div>'
        for band in price_bands
    )
    header = '<div class="ps-analytics-band-header"><span>Tranche</span><span>Publiées / vendues</span><span></span><span>Sell-through</span><span>CA cartes</span></div>'
    return f'<div class="ps-analytics-bands">{header}{rows}</div>'


def _render_analytics_comparison(drops, stock_data, fp_func, calc_cout_lot_func, effective_purchase_price_func, *, active_drop, channel_filter):
    candidates = [
        drop for drop in drops
        if _parse_dt(drop.get("drop_launched_at"))
        and (channel_filter == "Tous" or normalize_vinted_channel(drop.get("channel", "")) == channel_filter)
    ]
    if len(candidates) < 2:
        st.markdown('<section class="ps-analytics-section ps-analytics-empty-state"><h3>La comparaison sera disponible dès qu’un second Drop aura été lancé.</h3><p>Les données actuelles restent disponibles dans la vue d’ensemble et l’analyse détaillée.</p></section>', unsafe_allow_html=True)
        return
    candidates.sort(key=lambda drop: _parse_dt(drop.get("drop_launched_at")), reverse=True)
    names = [drop.get("name", "Drop sans nom") for drop in candidates]
    active_name = str((active_drop or {}).get("name") or "")
    primary_default = active_name if active_name in names else names[0]
    primary_col, reference_col, horizon_col = st.columns([1, 1, .85], vertical_alignment="bottom")
    with primary_col:
        primary_name = st.selectbox("Drop principal", names, index=names.index(primary_default), key="drop_analytics_compare_primary")
    primary_drop = next(drop for drop in candidates if drop.get("name", "Drop sans nom") == primary_name)
    reference_names = [name for name in names if name != primary_name]
    primary_launch = _parse_dt(primary_drop.get("drop_launched_at"))
    previous_drop = next((drop for drop in candidates if _parse_dt(drop.get("drop_launched_at")) < primary_launch), None)
    reference_default = previous_drop.get("name", "Drop sans nom") if previous_drop else reference_names[0]
    if st.session_state.get("drop_analytics_compare_reference") not in reference_names:
        st.session_state["drop_analytics_compare_reference"] = reference_default
    with reference_col:
        reference_name = st.selectbox("Comparer à", reference_names, index=reference_names.index(reference_default), key="drop_analytics_compare_reference")
    with horizon_col:
        history_mode = st.selectbox("Horizon", ("Même durée", "Historique complet"), key="drop_analytics_compare_horizon", label_visibility="collapsed")
    reference_drop = next(drop for drop in candidates if drop.get("name", "Drop sans nom") == reference_name)
    primary_rows = _sale_rows_for_drop(stock_data, primary_drop.get("id"), calc_cout_lot_func, effective_purchase_price_func)
    reference_rows = _sale_rows_for_drop(stock_data, reference_drop.get("id"), calc_cout_lot_func, effective_purchase_price_func)
    full_history = history_mode == "Historique complet"
    horizon_hours = _comparison_horizon_hours(primary_drop, primary_rows, reference_drop, reference_rows, full_history=full_history)
    if horizon_hours <= 0:
        st.caption("La comparaison apparaîtra dès que les deux Drops auront une période observable.")
        return
    primary_metrics = _analytics_metrics_at(primary_drop, primary_rows, _parse_dt(primary_drop.get("drop_launched_at")) + timedelta(hours=horizon_hours))
    reference_metrics = _analytics_metrics_at(reference_drop, reference_rows, _parse_dt(reference_drop.get("drop_launched_at")) + timedelta(hours=horizon_hours))
    comparison_metrics = [
        ("CA", "revenue", "€"), ("Bénéfice", "profit", "€"), ("Sell-through", "sell_through", "pts"),
        ("Cartes vendues", "sold", ""), ("Prix moyen", "avg_sold_price", "€"), ("Panier moyen", "avg_basket", "€"), ("Marge", "margin", "pts"),
    ]
    rows_html = []
    for label, field, unit in comparison_metrics:
        left = primary_metrics.get(field)
        right = reference_metrics.get(field)
        if left is None or right is None:
            delta = "N/A"
        elif unit == "pts":
            delta = f"{left - right:+.1f} pts"
        elif unit == "€":
            delta = fp_func(left - right)
        else:
            delta = f"{left - right:+.0f}"
        format_value = (lambda value: fp_func(value)) if unit == "€" else (lambda value: f"{value:.1f} %" if field in {"sell_through", "margin"} else f"{value:.0f}")
        rows_html.append(f'<div class="ps-analytics-compare-row"><span>{_html_escape(label)}</span><strong>{_html_escape(format_value(left) if left is not None else "N/A")}</strong><strong>{_html_escape(format_value(right) if right is not None else "N/A")}</strong><b>{_html_escape(delta)}</b></div>')
    st.markdown(
        f'<section class="ps-analytics-section"><div class="ps-analytics-section-heading"><div><h3>Comparaison à temps écoulé égal</h3><p>H+0 à H+{_duration_label(timedelta(hours=horizon_hours))} · cartes publiées : {primary_metrics["cards"]} vs {reference_metrics["cards"]} · valeur publiée : {fp_func(primary_metrics["published_value"])} vs {fp_func(reference_metrics["published_value"])}</p></div></div><div class="ps-analytics-compare-head"><span>Métrique</span><span>{_html_escape(primary_name)}</span><span>{_html_escape(reference_name)}</span><span>Écart</span></div><div class="ps-analytics-compare-table">{"".join(rows_html)}</div></section>',
        unsafe_allow_html=True,
    )
    mode = st.segmented_control("Métrique comparée", ("CA", "Bénéfice", "Sell-through", "Cartes vendues"), key="drop_analytics_comparison_metric", label_visibility="collapsed") or "CA"
    series = _comparison_time_series(primary_drop, primary_rows, reference_drop, reference_rows, full_history=full_history)
    try:
        import altair as alt
        import pandas as pd
        field = {"CA": "revenue", "Bénéfice": "profit", "Sell-through": "sell_through", "Cartes vendues": "sold"}[mode]
        chart_rows = []
        for point in series:
            for label, value in ((primary_name, point["primary"].get(field)), (reference_name, point["reference"].get(field))):
                is_primary = label == primary_name
                chart_rows.append({
                    "elapsed_hours": point["elapsed_hours"], "elapsed_label": point["elapsed_label"], "drop": label,
                    "value": value or 0.0, "primary_value": point["primary"].get(field), "reference_value": point["reference"].get(field),
                    "difference": (point["primary"].get(field) or 0.0) - (point["reference"].get(field) or 0.0),
                    "is_transaction": point["primary_is_transaction"] if is_primary else point["reference_is_transaction"],
                })
        frame = pd.DataFrame(chart_rows)
        comparison_hover = alt.selection_point(on="pointerover", fields=["elapsed_hours", "drop"], nearest=True, empty=False)
        base = alt.Chart(frame).encode(
            x=alt.X("elapsed_hours:Q", axis=_analytics_elapsed_axis(horizon_hours, alt)),
            y=alt.Y("value:Q", title=mode),
            color=alt.Color("drop:N", scale=alt.Scale(range=["#6d28d9", "#2563eb"])),
            tooltip=[
                alt.Tooltip("elapsed_label:N", title="Temps écoulé"), alt.Tooltip("drop:N", title="Drop"),
                alt.Tooltip("value:Q", title=mode, format=".2f"),
                alt.Tooltip("primary_value:Q", title=primary_name, format=".2f"),
                alt.Tooltip("reference_value:Q", title=reference_name, format=".2f"),
                alt.Tooltip("difference:Q", title="Écart", format="+.2f"),
            ],
        )
        chart = alt.layer(
            base.mark_line(interpolate=_ANALYTICS_CHART_INTERPOLATION, strokeWidth=2.6),
            base.transform_filter("datum.is_transaction").mark_point(stroke="#ffffff", strokeWidth=1.2, filled=True).encode(size=alt.condition(comparison_hover, alt.value(88), alt.value(38))).add_params(comparison_hover),
        ).properties(height=285, title=f"{mode} · {primary_name} vs {reference_name}")
        st.altair_chart(_analytics_chart_style(chart), width="stretch", key="drop_analytics_comparison_chart")
    except Exception:
        st.caption("Le graphique de comparaison est indisponible dans cet environnement.")
    primary_milestones = _analytics_milestones(primary_drop, primary_rows)
    reference_milestones = _analytics_milestones(reference_drop, reference_rows)
    milestone_labels = (("Première vente", "first_sale"), ("50 €", "ca_50"), ("100 €", "ca_100"), ("10 % vendu", "sold_10"), ("25 % vendu", "sold_25"))
    milestone_html = "".join(
        f'<div class="ps-analytics-compare-row"><span>{label}</span><strong>{_html_escape(_duration_label(primary_milestones[key]) if key in primary_milestones else "Non atteint")}</strong><strong>{_html_escape(_duration_label(reference_milestones[key]) if key in reference_milestones else "Non atteint")}</strong><b>{_html_escape(_duration_delta_label(primary_milestones[key] - reference_milestones[key]) if key in primary_milestones and key in reference_milestones else "—")}</b></div>'
        for label, key in milestone_labels
    )
    st.markdown(f'<section class="ps-analytics-section"><div class="ps-analytics-section-heading"><div><h3>Milestones</h3><p>Durées exactes depuis chaque lancement.</p></div></div><div class="ps-analytics-compare-head"><span>Milestone</span><span>{_html_escape(primary_name)}</span><span>{_html_escape(reference_name)}</span><span>Écart</span></div><div class="ps-analytics-compare-table">{milestone_html}</div></section>', unsafe_allow_html=True)
    cutoff_primary = _parse_dt(primary_drop.get("drop_launched_at")) + timedelta(hours=horizon_hours)
    cutoff_reference = _parse_dt(reference_drop.get("drop_launched_at")) + timedelta(hours=horizon_hours)
    primary_bands = {band["label"]: band for band in _analytics_price_bands([primary_drop], {str(primary_drop.get("id") or ""): [row for row in primary_rows if row.get("date") and row["date"] <= cutoff_primary]})}
    reference_bands = {band["label"]: band for band in _analytics_price_bands([reference_drop], {str(reference_drop.get("id") or ""): [row for row in reference_rows if row.get("date") and row["date"] <= cutoff_reference]})}
    band_rows = []
    for label in ("< 2 €", "2–5 €", "5–10 €", "10–20 €", "20 €+"):
        left = primary_bands[label].get("sell_through")
        right = reference_bands[label].get("sell_through")
        delta = f"{left - right:+.1f} pts" if left is not None and right is not None else "N/A"
        band_rows.append(f'<div class="ps-analytics-compare-row"><span>{label}</span><strong>{"N/A" if left is None else f"{left:.1f} %"}</strong><strong>{"N/A" if right is None else f"{right:.1f} %"}</strong><b>{_html_escape(delta)}</b></div>')
    st.markdown(f'<section class="ps-analytics-section"><div class="ps-analytics-section-heading"><div><h3>Tranches de prix</h3><p>Sell-through des cartes physiques au même horizon.</p></div></div><div class="ps-analytics-compare-head"><span>Tranche</span><span>{_html_escape(primary_name)}</span><span>{_html_escape(reference_name)}</span><span>Delta</span></div><div class="ps-analytics-compare-table">{"".join(band_rows)}</div></section>', unsafe_allow_html=True)


def _render_drop_analytics(drops_data, stock_data, fp_func, calc_cout_lot_func=None, effective_purchase_price_func=None, *, active_drop=None):
    drops = drops_data.get("drops", []) or []
    if not drops:
        st.caption("Aucun drop à analyser.")
        return
    active_name = str((active_drop or {}).get("name") or "").strip()
    active_id = str((active_drop or {}).get("id") or "").strip()
    active_channel = normalize_vinted_channel((active_drop or {}).get("channel", ""))
    channel_options = ["Tous", *VINTED_CHANNELS]
    if st.session_state.get("vinted_analytics_defaults_version") != "v3" or (active_id and st.session_state.get("vinted_analytics_active_drop_id") != active_id):
        st.session_state["vinted_analysis_channel"] = active_channel if active_channel in channel_options else "Tous"
        st.session_state["vinted_analysis_drop"] = active_name or "Tous les drops"
        st.session_state["vinted_analytics_defaults_version"] = "v3"
        st.session_state["vinted_analytics_active_drop_id"] = active_id
    header_col, channel_col, drop_col = st.columns([2.4, 1, 1.5], vertical_alignment="bottom")
    with channel_col:
        channel_filter = st.selectbox("Canal", channel_options, key="vinted_analysis_channel", label_visibility="collapsed")
    filtered = [drop for drop in drops if channel_filter == "Tous" or normalize_vinted_channel(drop.get("channel", "")) == channel_filter]
    if not filtered:
        st.caption("Aucun drop pour ce canal.")
        return
    drop_names = ["Tous les drops"] + [drop.get("name", "Drop sans nom") for drop in filtered]
    if st.session_state.get("vinted_analysis_drop") not in drop_names:
        st.session_state["vinted_analysis_drop"] = active_name if active_name in drop_names else "Tous les drops"
    with drop_col:
        selected_name = st.selectbox("Drop", drop_names, key="vinted_analysis_drop", label_visibility="collapsed")
    selected = filtered if selected_name == "Tous les drops" else [drop for drop in filtered if drop.get("name", "Drop sans nom") == selected_name]
    is_single_drop = len(selected) == 1
    with header_col:
        if is_single_drop:
            drop = selected[0]
            st.markdown(f'<div class="ps-analytics-title"><strong>{_html_escape(drop.get("name", "Drop sans nom"))}</strong><span>{_html_escape(normalize_vinted_channel(drop.get("channel", "")) or "Canal non renseigné")} · {_html_escape(_analytics_header_date(drop.get("drop_launched_at")))}</span></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="ps-analytics-title"><strong>Tous les drops</strong><span>Vue agrégée · périmètre sélectionné</span></div>', unsafe_allow_html=True)
    view = _analytics_view_control()
    if view == "Comparaison":
        _render_analytics_comparison(drops, stock_data, fp_func, calc_cout_lot_func, effective_purchase_price_func, active_drop=active_drop, channel_filter=channel_filter)
        return

    all_rows, rows_by_drop_id = [], {}
    aggregate = {"cards": 0, "to_photograph": 0, "draft_ready": 0, "online": 0, "sold": 0, "published_value": 0.0, "revenue": 0.0, "profit": 0.0, "known_profit": False}
    for drop in selected:
        rows = _sale_rows_for_drop(stock_data, drop.get("id"), calc_cout_lot_func, effective_purchase_price_func)
        rows_by_drop_id[str(drop.get("id") or "")] = rows
        all_rows.extend(rows)
        metrics = _drop_metrics(drop, rows)
        for field in ("cards", "to_photograph", "draft_ready", "online", "sold", "published_value", "revenue"):
            aggregate[field] += metrics.get(field, 0) or 0
        if metrics.get("profit") is not None:
            aggregate["profit"] += metrics["profit"]
            aggregate["known_profit"] = True
    aggregate["profit"] = aggregate["profit"] if aggregate.pop("known_profit") else None
    aggregate["sell_through"] = aggregate["sold"] / aggregate["cards"] * 100.0 if aggregate["cards"] else None
    scope = _sales_scope_metrics(all_rows)
    aggregate.update({"ca_total": aggregate["revenue"], "ca_cards": scope["ca_cards"], "ca_off_stock": scope["ca_off_stock"], "avg_sold_price": scope["ca_cards"] / aggregate["sold"] if aggregate["sold"] else None, "avg_basket": aggregate["revenue"] / scope["total_transactions"] if scope["total_transactions"] else None, "avg_cards_per_transaction": aggregate["sold"] / scope["card_transactions"] if scope["card_transactions"] else None})
    neg = _negotiation_stats(all_rows)
    price_bands = _analytics_price_bands(selected, rows_by_drop_id)
    remaining = _analytics_remaining_items(selected)

    if view == "Vue d’ensemble":
        st.markdown(_analytics_kpis_html(aggregate, fp_func), unsafe_allow_html=True)
        stock_col, chart_col = st.columns([.75, 1.25], gap="large")
        with stock_col:
            stock_label = f"{aggregate['sold']} vendues · {aggregate['sell_through']:.1f} %" if aggregate.get("sell_through") is not None else f"{aggregate['sold']} vendues"
            st.markdown(f'<section class="ps-analytics-surface"><div class="ps-analytics-section-heading"><div><h3>Progression du stock</h3><p>{aggregate["cards"]} cartes sélectionnées · {aggregate["online"]} en ligne · {aggregate["to_photograph"]} à photographier</p></div></div><div class="ps-analytics-progress"><i style="width:{aggregate["sell_through"] or 0:.2f}%"></i></div><div class="ps-analytics-progress-label">{_html_escape(stock_label)}</div></section>', unsafe_allow_html=True)
            st.markdown(_analytics_revenue_breakdown_html(aggregate, fp_func, compact=True), unsafe_allow_html=True)
        with chart_col:
            if is_single_drop:
                chart_mode = st.segmented_control("Courbe", ("CA & bénéfice", "Ventes & écoulement"), key="drop_analytics_chart_mode", label_visibility="collapsed") or "CA & bénéfice"
                range_label = st.segmented_control("Période", ("24 h", "72 h", "7 j", "Tout"), key="drop_analytics_range", label_visibility="collapsed") or "Tout"
                hours = {"24 h": 24, "72 h": 72, "7 j": 168, "Tout": None}[range_label]
                series = _analytics_time_series(selected[0], all_rows, range_hours=hours)
                _render_analytics_charts(series, mode=chart_mode, key="drop_analytics_main_chart")
            else:
                st.markdown('<section class="ps-analytics-surface ps-analytics-note"><strong>Temporalité par Drop</strong><span>Sélectionnez un Drop précis pour suivre ses événements transaction par transaction.</span></section>', unsafe_allow_html=True)
        if is_single_drop:
            timing = _analytics_timing(selected[0], all_rows)
            st.markdown(f'<section class="ps-analytics-section"><div class="ps-analytics-section-heading"><div><h3>Vitesse du Drop</h3><p>Milestones atteints depuis le lancement officiel.</p></div></div>{_analytics_milestone_html(timing, compact=True)}</section>', unsafe_allow_html=True)
        insights = _analytics_insights(price_bands, neg)[:3]
        if insights:
            st.markdown(f'<section class="ps-analytics-section ps-analytics-insights"><div class="ps-analytics-section-heading"><div><h3>Enseignements</h3><p>Constats calculés à partir des données du Drop.</p></div></div><ul>{"".join(f"<li>{_html_escape(insight)}</li>" for insight in insights)}</ul></section>', unsafe_allow_html=True)
        return

    st.markdown(_analytics_kpis_html(aggregate, fp_func, include_cards_per_transaction=True), unsafe_allow_html=True)
    st.markdown(_analytics_revenue_breakdown_html(aggregate, fp_func), unsafe_allow_html=True)
    if is_single_drop:
        timing = _analytics_timing(selected[0], all_rows)
        checkpoint_html = "".join(f'<div class="ps-analytics-checkpoint"><span>{checkpoint["label"]}</span><strong>{"À venir" if checkpoint.get("upcoming") else _html_escape(fp_func(checkpoint.get("revenue", 0)))}</strong><small>{"" if checkpoint.get("upcoming") else f"{checkpoint.get("sold", 0)} vendue(s)"}</small></div>' for checkpoint in timing["checkpoints"])
        st.markdown(f'<section class="ps-analytics-section"><div class="ps-analytics-section-heading"><div><h3>Checkpoints exacts</h3><p>Lecture au timestamp précis H+1, H+6, H+12, H+24, H+48, J+3, J+7 et J+30.</p></div></div><div class="ps-analytics-checkpoints">{checkpoint_html}</div></section>', unsafe_allow_html=True)
    neg_items = [("Moyenne", f"{neg['avg_pct']:.2f} %" if neg.get("avg_pct") is not None else "N/A"), ("Médiane", f"{neg['median_pct']:.1f} %" if neg.get("median_pct") is not None else "N/A"), ("Au prix", f"{neg['equal_pct']:.1f} %" if neg.get("equal_pct") is not None else "N/A"), ("Sous prix", f"{neg['under_pct']:.1f} %" if neg.get("under_pct") is not None else "N/A"), ("Impact total", fp_func(neg["total_diff"]))]
    neg_html = "".join(f'<div class="ps-analytics-negotiation-item"><span>{_html_escape(label)}</span><strong>{_html_escape(value)}</strong></div>' for label, value in neg_items)
    equal_pct, under_pct = max(0.0, min(100.0, _safe_float(neg.get("equal_pct")))), max(0.0, min(100.0, _safe_float(neg.get("under_pct"))))
    remaining_html = "".join(f'<div class="ps-analytics-remaining-row"><span><strong>{_html_escape(item["name"])} {_html_escape(item["number"])}</strong><small>{_html_escape(item["band"])} · {_html_escape(item["online_label"])}</small></span><b>{_html_escape(fp_func(item["price"]))}</b></div>' for item in remaining["top_online"]) or '<div class="ps-analytics-empty">Aucune carte en ligne.</div>'
    left, right = st.columns([.9, 1.3], gap="large")
    with left:
        st.markdown(f'<section class="ps-analytics-section"><div class="ps-analytics-section-heading"><div><h3>Négociation</h3><p>Cartes avec prix de référence.</p></div></div><div class="ps-analytics-negotiation">{neg_html}</div><div class="ps-analytics-negotiation-bar"><i style="width:{equal_pct:.2f}%"></i><b style="width:{under_pct:.2f}%"></b></div></section>', unsafe_allow_html=True)
    with right:
        st.markdown(f'<section class="ps-analytics-section"><div class="ps-analytics-section-heading"><div><h3>Tranches de prix</h3><p>Cartes physiques uniquement.</p></div></div>{_analytics_price_bands_html(price_bands, fp_func)}</section>', unsafe_allow_html=True)
    st.markdown(f'<section class="ps-analytics-section"><div class="ps-analytics-section-heading"><div><h3>Ce qu’il reste à vendre</h3><p>{remaining["remaining_cards"]} carte(s) · {fp_func(remaining["remaining_value"])} · {remaining["remaining_value_pct"]:.1f} % de valeur immobilisée</p></div></div><div class="ps-analytics-remaining-list">{remaining_html}</div></section>', unsafe_allow_html=True)
    if is_single_drop:
        highlights = _analytics_highlights(all_rows, selected[0])
        highlight_rows = []
        for label, row, value in (("Plus grosse vente", highlights["largest_sale"], lambda item: fp_func(item["revenue"])), ("Meilleure marge €", highlights["best_margin"], lambda item: fp_func(item["profit"])), ("Meilleure marge %", highlights["best_margin_pct"], lambda item: f"{_safe_float(item['profit']) / _safe_float(item['revenue']) * 100:.1f} %")):
            if row:
                highlight_rows.append((label, row["card_name"], value(row)))
        if highlights["fastest"] and highlights["launched"]:
            highlight_rows.append(("Vente la plus rapide", highlights["fastest"]["card_name"], _duration_label(highlights["fastest"]["date"] - highlights["launched"])))
        content = "".join(f'<div class="ps-analytics-highlight"><span>{_html_escape(label)}</span><strong>{_html_escape(name)}</strong><b>{_html_escape(value)}</b></div>' for label, name, value in highlight_rows) or '<div class="ps-analytics-empty">Aucune transaction disponible.</div>'
        st.markdown(f'<section class="ps-analytics-section"><div class="ps-analytics-section-heading"><div><h3>Transactions marquantes</h3><p>Lecture sur les cartes physiques du Drop.</p></div></div><div class="ps-analytics-highlights">{content}</div></section>', unsafe_allow_html=True)


def _recognition_listing_cards(listing, available_cards):
    by_uid = {str(card.get("card_uid") or ""): card for card in available_cards or [] if card.get("card_uid")}
    cards = []
    for recognized in listing.get("cards", []) or []:
        uid = str(recognized.get("card_uid") or "")
        candidate = recognized.get("candidate") or recognized
        cards.append(dict(by_uid.get(uid) or candidate))
    return cards


def _recognition_listing_statuses(active_drop, listing):
    by_uid = {str(ref.get("card_uid") or ""): drop_item_status(ref) for ref in active_drop.get("cards", []) or []}
    return [by_uid.get(str(uid), "needs_review") for uid in listing.get("card_uids", []) or []]


def _recognition_payload_summary(active_drop, recognition_payload):
    listings = recognition_payload.get("listings", []) or []
    photos = [photo for listing in listings for photo in listing.get("photos", []) or []]
    cards = [card for listing in listings for card in listing.get("cards", []) or []]
    payload_uids = {
        str(card.get("card_uid") or "").strip()
        for card in cards
        if str(card.get("card_uid") or "").strip()
    }
    drop_refs = active_drop.get("cards", []) or []
    drop_uids = {
        str(ref.get("card_uid") or "").strip()
        for ref in drop_refs
        if str(ref.get("card_uid") or "").strip()
    }
    return {
        "announcements": len(listings),
        "photos": len(photos),
        "cards": len(cards),
        "multi": sum(1 for listing in listings if len(listing.get("cards", []) or []) > 1),
        "anomalies": len(recognition_payload.get("diagnostic_errors", []) or []),
        "drop_items": sum(max(1, _safe_int(ref.get("quantity"), 1)) for ref in drop_refs),
        "missing_card_uids": sum(1 for card in cards if not str(card.get("card_uid") or "").strip()),
        "missing_primary_fronts": sum(1 for listing in listings if not listing.get("primary_front")),
        "unrepresented_drop_uids": sorted(drop_uids - payload_uids),
    }


def _current_step4_payload(active_drop, recognition_result, recognition_session):
    """Keep the already-built Step 4 payload available through lightweight UI reruns."""
    drop_id = str(active_drop.get("id") or "")
    meta = recognition_result.get("analysis_meta") or {}
    signature_source = {
        "photo_signature": meta.get("photo_signature"),
        "candidate_signature": meta.get("candidate_signature"),
        "pipeline_version": meta.get("pipeline_version"),
        "direction": _drop_photo_direction(active_drop) or "start_to_end",
        "validations": recognition_session.get("validations") or {},
        "grouping": recognition_session.get("grouping_confirmations") or {},
    }
    signature = hashlib.sha1(json.dumps(signature_source, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    cache_key = f"vinted_step4_payload_{drop_id}"
    cached = st.session_state.get(cache_key)
    if isinstance(cached, dict) and cached.get("signature") == signature:
        return cached["payload"]

    payload = build_step4_payload(
        recognition_result,
        recognition_session,
        photo_capture_direction=signature_source["direction"],
    )
    st.session_state[cache_key] = {"signature": signature, "payload": payload}
    return payload


def _recognition_photo_path(recognition_payload, photo):
    direct = str((photo or {}).get("path") or "").strip()
    if direct:
        return Path(direct)
    folder = str(recognition_payload.get("photo_folder") or "").strip()
    filename = str((photo or {}).get("filename") or "").strip()
    return Path(folder) / filename if folder and filename else Path()


def _recognition_listing_content(listing, available_cards):
    cards = _recognition_listing_cards(listing, available_cards)
    listing_type = "Plusieurs cartes" if len(cards) > 1 else "Carte seule"
    listing_cards = [_card_with_drop_quantity(card, 1) for card in cards]
    return cards, listing_cards, listing_type, prepare_listing(listing_cards, listing_type)


def _recognition_photo_role_label(photo, *, multi=False):
    role = str((photo or {}).get("role") or "")
    if role == "primary_front":
        return "Groupe" if multi else "Principale"
    return {
        "card_front": "Recto",
        "card_back": "Verso",
        "back_western": "Verso",
        "back_japanese": "Verso",
    }.get(role, "Photo")


def _step4_preview_mode_key(drop_id):
    return f"step4_preview_mode_{drop_id}"


def _recognition_preview_index_key(drop_id):
    return f"vinted_recognition_preview_index_{drop_id}"


def _recognition_payload_search_signature(recognition_payload):
    return ":".join(
        (
            str(id(recognition_payload)),
            str(recognition_payload.get("photo_signature") or ""),
            str(recognition_payload.get("pipeline_version") or ""),
            str(len(recognition_payload.get("listings", []) or [])),
        )
    )


def _recognition_listing_search_index(active_drop, recognition_payload, available_cards):
    """Build a tiny payload-only card index once per current recognition result."""
    drop_id = str(active_drop.get("id") or "")
    signature = _recognition_payload_search_signature(recognition_payload)
    state_key = f"vinted_recognition_preview_search_{drop_id}"
    cached = st.session_state.get(state_key)
    if isinstance(cached, dict) and cached.get("signature") == signature:
        return cached.get("entries", [])

    entries = []
    for listing_index, listing in enumerate(recognition_payload.get("listings", []) or [], start=1):
        for card in _recognition_listing_cards(listing, available_cards):
            name = _card_display_title(card)
            number = _card_number(card)
            extension = _card_set(card)
            entries.append(
                {
                    "listing_index": listing_index,
                    "label": " · ".join(part for part in (name, number, extension) if part),
                    "search_text": normalize_search_text(" ".join(str(part or "") for part in (name, number, extension))),
                }
            )
    st.session_state[state_key] = {"signature": signature, "entries": entries}
    return entries


def _recognition_listing_search_results(entries, query, *, limit=12):
    terms = [term for term in normalize_search_text(query).split() if term]
    if not terms:
        return []
    return [entry for entry in entries if all(term in entry["search_text"] for term in terms)][:limit]


def _render_recognition_listing_workspace(
    active_drop,
    recognition_payload,
    listing,
    available_cards,
    run_html_func,
    mobile,
    *,
    read_only,
    fp_func=None,
):
    cards, listing_cards, listing_type, prepared = _recognition_listing_content(listing, available_cards)
    if not read_only:
        prepared = _sync_listing_text(listing_cards, listing_type, fp_func)
    listing_key = str(listing.get("recognition_group_id") or listing.get("creation_order") or "listing")
    photo_col, content_col = st.columns([1, 1.85]) if not mobile else (st.container(), st.container())
    with photo_col:
        st.markdown("**Photo principale**")
        primary_path = _recognition_photo_path(recognition_payload, listing.get("primary_front") or {})
        if primary_path.is_file():
            st.image(str(primary_path), width="stretch" if mobile else 260)
        else:
            st.caption("Photo principale indisponible dans l’aperçu.")
        photos = listing.get("photos", []) or []
        if photos:
            st.caption(f"Photos · {len(photos)}")
        for start in range(0, len(photos), 4):
            row = photos[start : start + 4]
            columns = st.columns(len(row))
            for offset, photo in enumerate(row):
                with columns[offset]:
                    photo_path = _recognition_photo_path(recognition_payload, photo)
                    if photo_path.is_file():
                        st.image(str(photo_path), width=78 if mobile else 72)
                    st.markdown(
                        f'<div class="ps-recognition-photo-caption">{_recognition_photo_role_label(photo, multi=len(cards) > 1)}</div>',
                        unsafe_allow_html=True,
                    )
    with content_col:
        st.markdown(f"**{len(cards)} carte(s)**" if len(cards) > 1 else "**Carte**")
        for card in cards:
            language = "JAP" if card.get("japanese") or card.get("is_japanese") or card.get("lang") == "ja" else "FR"
            st.markdown(
                f'<div class="ps-recognition-identity-title">{_html_escape(_card_display_title(card))}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="ps-recognition-identity-meta">{_html_escape(_card_set(card) or "Extension N/A")} · {language}</div>',
                unsafe_allow_html=True,
            )

        title_col, title_copy_col = st.columns([4, 1])
        with title_col:
            if read_only:
                st.text_input(
                    "Titre Vinted",
                    value=prepared["title"],
                    disabled=True,
                    key=f"vinted_recognition_preview_title_{active_drop.get('id')}_{listing_key}",
                )
            else:
                st.text_input("Titre Vinted", key="vinted_listing_title")
        with title_copy_col:
            _copy_button(
                "📋 Copier",
                prepared["title"] if read_only else st.session_state.get("vinted_listing_title", ""),
                f"copy_vinted_recognition_preview_title_{active_drop.get('id')}_{listing_key}",
                run_html_func,
                ["Titre Vinted"] if not read_only else None,
                compact=True,
            )

        description_col, description_copy_col = st.columns([4, 1])
        with description_col:
            if read_only:
                st.text_area(
                    "Description",
                    value=prepared["description"],
                    height=180 if mobile else 205,
                    disabled=True,
                    key=f"vinted_recognition_preview_description_{active_drop.get('id')}_{listing_key}",
                )
            else:
                st.text_area("Description", key="vinted_listing_description", height=180 if mobile else 205)
        with description_copy_col:
            _copy_button(
                "📋 Copier",
                prepared["description"] if read_only else st.session_state.get("vinted_listing_description", ""),
                f"copy_vinted_recognition_preview_description_{active_drop.get('id')}_{listing_key}",
                run_html_func,
                ["Description"] if not read_only else None,
                compact=True,
            )
    with st.expander("Détails de l’ordre des photos", expanded=False):
        for position, photo in enumerate(listing.get("photos", []) or [], start=1):
            filename = str(photo.get("filename") or photo.get("name") or Path(str(photo.get("path") or "")).name)
            st.caption(f"{position}. {photo.get('role', 'photo')} · {filename or 'Photo'}")


def _render_recognition_preview_workspace(
    active_drop,
    available_cards,
    recognition_payload,
    run_html_func,
    mobile,
    *,
    focus_mode=False,
):
    listings = recognition_payload.get("listings", []) or []
    if not listings:
        st.caption("Aucune annonce à prévisualiser.")
        return

    drop_id = str(active_drop.get("id") or "")
    preview_key = _step4_preview_mode_key(drop_id)
    index_key = _recognition_preview_index_key(drop_id)
    selected = max(1, min(len(listings), int(st.session_state.get(index_key, 1) or 1)))

    if mobile:
        previous_col, label_col, next_col, quit_col = st.columns([0.55, 1.35, 0.55, 1.05])
        search_col = st.container()
        jump_col = None
        header_col = None
    elif focus_mode:
        header_col, previous_col, label_col, next_col, search_col, jump_col, quit_col = st.columns(
            [1.65, 0.35, 1.35, 0.35, 2.75, 0.78, 0.95]
        )
    else:
        previous_col, label_col, next_col, search_col, jump_col = st.columns([0.38, 1.45, 0.38, 2.7, 0.75])
        header_col = quit_col = None
    if header_col is not None:
        with header_col:
            st.markdown(
                f'<div class="ps-recognition-focus-header">{_html_escape(active_drop.get("name") or "Drop")} · Aperçu</div>',
                unsafe_allow_html=True,
            )
    with previous_col:
        if st.button("←", key=f"previous_{preview_key}", disabled=selected <= 1, width="stretch"):
            st.session_state[index_key] = selected - 1
            st.rerun()
    with label_col:
        st.markdown(
            f'<div class="ps-recognition-toolbar-label">Annonce {selected} / {len(listings)}</div>',
            unsafe_allow_html=True,
        )
    with next_col:
        if st.button("→", key=f"next_{preview_key}", disabled=selected >= len(listings), width="stretch"):
            st.session_state[index_key] = selected + 1
            st.rerun()

    with search_col:
        search_query = st.text_input(
            "Rechercher une carte",
            key=f"{preview_key}_search",
            placeholder="🔎 Rechercher une carte…",
            label_visibility="collapsed",
        )
    if jump_col is not None:
        with jump_col:
            with st.popover("Aller à…", use_container_width=True):
                jump_to = st.number_input(
                    "Numéro d’annonce",
                    min_value=1,
                    max_value=len(listings),
                    value=selected,
                    step=1,
                    key=f"{preview_key}_jump",
                )
                if st.button("Afficher", key=f"jump_{preview_key}", width="stretch"):
                    st.session_state[index_key] = int(jump_to)
                    st.rerun()
    if quit_col is not None:
        with quit_col:
            if st.button("Quitter", key=f"close_{preview_key}", width="stretch"):
                st.session_state.pop(preview_key, None)
                st.rerun()

    search_results = _recognition_listing_search_results(
        _recognition_listing_search_index(active_drop, recognition_payload, available_cards),
        search_query,
    )
    if search_query.strip():
        if search_results:
            st.caption(f"{len(search_results)} annonce(s) trouvée(s)")
            for result_number, result in enumerate(search_results, start=1):
                if st.button(
                    f"{result['label']} · Annonce {result['listing_index']}",
                    key=f"{preview_key}_search_result_{result_number}_{result['listing_index']}",
                    width="stretch",
                ):
                    st.session_state[index_key] = result["listing_index"]
                    st.rerun()
        else:
            st.caption("Aucune carte de ces annonces ne correspond à cette recherche.")

    with st.container(border=True):
        _render_recognition_listing_workspace(
            active_drop,
            recognition_payload,
            listings[selected - 1],
            available_cards,
            run_html_func,
            mobile,
            read_only=True,
        )


def _render_launched_recognition_preview(active_drop, available_cards, recognition_payload, run_html_func, mobile):
    summary = _recognition_payload_summary(active_drop, recognition_payload)
    launched_at = str(active_drop.get("drop_launched_at") or "")
    launch_mode = " · Publication manuelle" if active_drop.get("launch_mode") == "manual" else ""
    st.success(f"Drop en ligne depuis le {launched_at}{launch_mode}")
    st.markdown("**Aperçu / contrôle du payload**")
    st.caption("Ce Drop est déjà lancé. Cette étape est en lecture seule et ne peut créer aucun brouillon.")
    st.markdown(
        f"**{summary['announcements']} annonces prêtes** · {summary['photos']} photos · "
        f"{summary['cards']} cartes photographiées · {summary['multi']} multi · "
        f"{summary['anomalies']} anomalie"
    )
    st.caption(f"{summary['drop_items']} items appartiennent actuellement au Drop.")

    if summary["unrepresented_drop_uids"]:
        by_uid = {
            str(card.get("card_uid") or "").strip(): card
            for card in available_cards or []
            if str(card.get("card_uid") or "").strip()
        }
        labels = []
        for uid in summary["unrepresented_drop_uids"]:
            card = by_uid.get(uid) or next(
                (
                    ref
                    for ref in active_drop.get("cards", []) or []
                    if str(ref.get("card_uid") or "").strip() == uid
                ),
                {},
            )
            labels.append(_card_display_title(card) or uid)
        st.warning(
            f"{len(labels)} item(s) du Drop ne figurent pas dans cette série de photos : "
            + ", ".join(labels)
            + "."
        )

    preview_key = _step4_preview_mode_key(active_drop.get("id"))
    if st.button("Prévisualiser les annonces", key=f"open_{preview_key}"):
        st.session_state[preview_key] = True
        st.rerun()
    return True


def _render_step4_focus_preview(active_drop, available_cards, recognition_payload, run_html_func, mobile):
    """Render the read-only preview without the regular Drop workflow chrome."""
    st.markdown(
        "<style>[data-testid='stMainBlockContainer']{padding-top:.55rem !important;}</style>",
        unsafe_allow_html=True,
    )
    _render_recognition_preview_workspace(
        active_drop,
        available_cards,
        recognition_payload,
        run_html_func,
        mobile,
        focus_mode=True,
    )


def _set_recognition_listing_status(drops_data, active_drop, listing, status):
    changed = False
    wanted = {str(uid) for uid in listing.get("card_uids", []) or [] if uid}
    for ref in active_drop.get("cards", []) or []:
        if str(ref.get("card_uid") or "") not in wanted:
            continue
        if drop_item_status(ref) in {"online", "sold"}:
            continue
        changed = set_drop_card_status(drops_data, active_drop.get("id"), drop_card_key(ref), status) or changed
    return changed


def _render_recognition_creation_step(
    drops_data,
    active_drop,
    available_cards,
    proxy_img_func,
    fp_func,
    run_html_func,
    mobile,
    recognition_payload,
):
    if active_drop.get("drop_launched_at"):
        return _render_launched_recognition_preview(
            active_drop,
            available_cards,
            recognition_payload,
            run_html_func,
            mobile,
        )

    if not recognition_payload.get("ready"):
        st.warning("La vérification photo doit être terminée avant de créer les annonces.")
        unresolved = recognition_payload.get("diagnostic_errors", []) or []
        st.caption(f"{len(unresolved)} point(s) restent à résoudre dans l’étape Vérification.")
        if st.button("Retourner à la vérification", key=f"recognition_back_to_review_{active_drop.get('id')}"):
            st.session_state["vinted_drop_step"] = "Vérification"
            st.rerun()
        return True

    listings = recognition_payload.get("listings", []) or []
    workflow = []
    ready = []
    pending = []
    for listing in listings:
        statuses = _recognition_listing_statuses(active_drop, listing)
        if not statuses or all(status in {"online", "sold"} for status in statuses):
            continue
        workflow.append(listing)
        if statuses and all(status == "draft_ready" for status in statuses):
            ready.append(listing)
        else:
            pending.append(listing)

    total = len(workflow)
    ready_count = len(ready)
    pct = ready_count / total if total else 0.0
    st.markdown(
        f"""
<div class="ps-vinted-progress-panel">
  <div class="ps-vinted-progress-main">{ready_count} / {total} annonces créées</div>
  <div class="ps-vinted-progress-sub">{pct * 100:.0f} % · Ordre issu de la reconnaissance photo</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.progress(pct)
    _render_launch_drop_panel(drops_data, active_drop, available_cards, fp_func)
    if not workflow:
        st.caption("Aucune annonce reconnue restant à préparer dans ce Drop.")
        return True
    if not pending:
        st.success("Toutes les annonces reconnues sont prêtes.")
        return True

    listing = pending[0]
    with st.container(border=True):
        st.markdown(
            f"**Annonce {listing.get('creation_order', 1)} / {total}**  \n"
            f"{len(listing.get('photos', []) or [])} photos · validation {listing.get('validation_source', 'auto')}"
        )
        _render_recognition_listing_workspace(
            active_drop,
            recognition_payload,
            listing,
            available_cards,
            run_html_func,
            mobile,
            read_only=False,
            fp_func=fp_func,
        )
        price_col, price_copy_col = st.columns([4, 1])
        with price_col:
            st.text_input("Prix", key="vinted_listing_price")
        with price_copy_col:
            _copy_button(
                "📋 Copier",
                st.session_state.get("vinted_listing_price", ""),
                "copy_vinted_recognition_price",
                run_html_func,
                ["Prix"],
                compact=True,
            )
        action_col, draft_col = st.columns(2) if not mobile else (st.container(), st.container())
        with action_col:
            st.link_button("Ouvrir Vinted", "https://www.vinted.fr/items/new", width="stretch")
        with draft_col:
            if st.button(
                "✓ Brouillon créé",
                key=f"draft_ready_recognition_group_{active_drop.get('id')}_{listing.get('recognition_group_id')}",
                type="primary",
                width="stretch",
            ):
                if _set_recognition_listing_status(drops_data, active_drop, listing, "draft_ready"):
                    save_vinted_drops(drops_data)
                    st.rerun()
    return True


def _render_drop_creation_step(
    drops_data,
    active_drop,
    available_cards,
    proxy_img_func,
    fp_func,
    run_html_func,
    mobile,
    *,
    recognition_payload=None,
):
    if recognition_payload is not None:
        if _render_recognition_creation_step(
            drops_data,
            active_drop,
            available_cards,
            proxy_img_func,
            fp_func,
            run_html_func,
            mobile,
            recognition_payload,
        ):
            return
    workflow_cards, pending_cards, ready_cards = _drop_creation_cards(active_drop, available_cards)
    total_qty = sum(_drop_workflow_quantity(card) for card in workflow_cards)
    ready_qty = sum(_drop_workflow_quantity(card) for card in ready_cards)
    pct = (ready_qty / total_qty) if total_qty else 0.0
    st.markdown(
        f"""
<div class="ps-vinted-progress-panel">
  <div class="ps-vinted-progress-main">{ready_qty} / {total_qty} brouillons créés</div>
  <div class="ps-vinted-progress-sub">{pct * 100:.0f} % · Création des annonces</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.progress(pct)

    if not workflow_cards:
        st.caption("Aucune carte à préparer dans ce drop.")
        _render_launch_drop_panel(drops_data, active_drop, available_cards, fp_func)
        return

    _render_launch_drop_panel(drops_data, active_drop, available_cards, fp_func)

    if not _render_drop_photo_direction_choice(drops_data, active_drop, ready_qty):
        return

    skip_key = _drop_queue_skip_key(active_drop.get("id"))
    skipped_keys = list(st.session_state.get(skip_key, []) or [])
    pending_unskipped = [card for card in pending_cards if _drop_card_ref_key(card) not in skipped_keys]
    if not pending_unskipped and pending_cards:
        skipped_keys = []
        st.session_state[skip_key] = []
        pending_unskipped = list(pending_cards)

    if pending_unskipped:
        current_card = pending_unskipped[0]
        current_key = _drop_card_ref_key(current_card)
        current_qty = _drop_workflow_quantity(current_card)
        listing_card = _card_with_drop_quantity(current_card, current_qty)
        listing_type = "Carte seule"
        _sync_listing_text([listing_card], listing_type, fp_func)
        current_number = min(total_qty, ready_qty + 1)
        st.markdown(f"**Carte #{current_number} sur {total_qty}**")
        with st.container():
            left, right = st.columns([1, 2]) if not mobile else [st.container(), st.container()]
            with left:
                _render_thumb(current_card, proxy_img_func, width=180 if mobile else 210)
            with right:
                st.markdown(
                    f"""
<div class="ps-vinted-current-card">
  <div class="ps-vinted-current-title">{_html_escape(_card_display_title(current_card))}</div>
  <div class="ps-vinted-current-meta">
    {_html_escape(_card_number(current_card) or "Numéro N/A")} ·
    {_html_escape(_card_set(current_card) or "Extension N/A")} ·
    Prix : {_html_escape(fp_func(suggested_price(current_card)) if suggested_price(current_card) else "à définir")} ·
    Quantité : x{current_qty}
  </div>
</div>
""",
                    unsafe_allow_html=True,
                )

        st.text_input("Titre généré", key="vinted_listing_title")
        _copy_button("Copier titre", st.session_state.get("vinted_listing_title", ""), "copy_vinted_queue_title", run_html_func, ["Titre généré"])
        st.text_input("Prix", key="vinted_listing_price")
        _copy_button("Copier prix", st.session_state.get("vinted_listing_price", ""), "copy_vinted_queue_price", run_html_func, ["Prix"])
        st.text_area("Description générée", key="vinted_listing_description", height=220 if mobile else 260)
        _copy_button("Copier description", st.session_state.get("vinted_listing_description", ""), "copy_vinted_queue_description", run_html_func, ["Description générée"])
        st.link_button("Ouvrir Vinted", "https://www.vinted.fr/items/new", width="stretch")

        done_col, skip_col = st.columns([2, 1]) if not mobile else (st.container(), st.container())
        with done_col:
            if st.button("✓ Brouillon créé", key=f"draft_ready_drop_card_{active_drop.get('id')}_{current_key}", type="primary", width="stretch"):
                if set_drop_card_status(drops_data, active_drop.get("id"), current_key, "draft_ready"):
                    st.session_state[skip_key] = [key for key in skipped_keys if key != current_key]
                    save_vinted_drops(drops_data)
                    st.rerun()
        with skip_col:
            if st.button("Passer pour l'instant", key=f"skip_drop_card_{active_drop.get('id')}_{current_key}", width="stretch"):
                if current_key not in skipped_keys:
                    skipped_keys.append(current_key)
                st.session_state[skip_key] = skipped_keys
                st.rerun()
    else:
        st.success("✅ Tous les brouillons sont prêts")

    _render_created_drafts_drawer(drops_data, active_drop, ready_cards, proxy_img_func, fp_func, mobile)


def _render_new_drop_form(drops_data):
    new_name = st.text_input("Nom du nouveau drop", key="new_vinted_drop_name", placeholder="Ex : Drop Vinted juin")
    new_channel = st.selectbox("Canal Vinted", list(VINTED_CHANNELS), key="new_vinted_drop_channel")
    if st.button("Créer le drop", key="create_vinted_drop", width="stretch"):
        if not str(new_name or "").strip():
            st.warning("Indique un nom de drop.")
            return
        create_drop(drops_data, new_name, new_channel)
        save_vinted_drops(drops_data)
        st.session_state.pop("new_vinted_drop_name", None)
        st.success("Drop créé.")
        st.rerun()


def _render_drop_management_actions(drops_data, active_id, active_drop):
    renamed = st.text_input("Renommer le drop", value=active_drop.get("name", ""), key=f"rename_drop_{active_id}")
    current_channel = normalize_vinted_channel(active_drop.get("channel", ""))
    channel_options = ["Non défini", *VINTED_CHANNELS]
    channel_index = channel_options.index(current_channel) if current_channel in channel_options else 0
    chosen_channel = st.selectbox("Canal Vinted", channel_options, index=channel_index, key=f"drop_channel_{active_id}")
    if st.button("Enregistrer", key=f"save_drop_name_{active_id}", width="stretch"):
        changed = rename_drop(drops_data, active_id, renamed)
        changed = update_drop_channel(drops_data, active_id, "" if chosen_channel == "Non défini" else chosen_channel) or changed
        if changed:
            save_vinted_drops(drops_data)
            st.success("Drop mis à jour.")
            st.rerun()
    st.divider()
    confirm = st.checkbox("Confirmer suppression", key=f"confirm_delete_drop_{active_id}")
    if st.button("Supprimer le drop", key=f"delete_drop_{active_id}", disabled=not confirm, width="stretch"):
        if delete_drop(drops_data, active_id):
            save_vinted_drops(drops_data)
            st.session_state.pop("vinted_active_drop_id", None)
            st.success("Drop supprimé.")
            st.rerun()


def _render_drops_manager(drops_data, available_cards, source_cards, proxy_img_func, fp_func, mobile, step, run_html_func=None, ld_func=None, calc_cout_lot_func=None, effective_purchase_price_func=None):
    drops = drops_data.get("drops", [])
    if not drops:
        st.markdown('<div class="ps-vinted-section-title">Créer un Drop</div>', unsafe_allow_html=True)
        with st.container(border=True):
            _render_new_drop_form(drops_data)
        st.caption("Aucun drop pour le moment.")
        return

    active_id = _active_drop_id(drops_data)
    drop_names = [drop.get("name", "Drop sans nom") for drop in drops]
    id_by_name = {drop.get("name", "Drop sans nom"): drop.get("id") for drop in drops}
    current_name = next((drop.get("name", "Drop sans nom") for drop in drops if drop.get("id") == active_id), drop_names[0])
    select_col, create_col = st.columns([4, 1]) if not mobile else [st.container(), st.container()]
    with select_col:
        chosen_name = st.selectbox("Drop à afficher", drop_names, index=drop_names.index(current_name), key="vinted_drop_view")
    with create_col:
        with st.popover("+ Nouveau Drop", use_container_width=True):
            _render_new_drop_form(drops_data)
    active_id = id_by_name[chosen_name]
    st.session_state["vinted_active_drop_id"] = active_id
    active_drop = find_drop(drops_data, active_id)
    if not active_drop:
        return

    total_cards = sum(max(1, int(ref.get("quantity", 1) or 1)) for ref in active_drop.get("cards", []))
    total_value = _drop_total_value(active_drop, source_cards)
    channel_label = normalize_vinted_channel(active_drop.get("channel", "")) or "Non défini"
    channel_class = _drop_channel_class(channel_label)
    with st.container(border=True):
        if mobile:
            st.markdown(
                f"""
<div class="ps-vinted-drop-head">
  <strong>{_html_escape(active_drop.get('name', 'Drop sans nom'))}</strong>
  <div class="ps-vinted-drop-meta">
    <span>{total_cards} carte(s) · Valeur du drop : {fp_func(total_value) if total_value else 'à définir'}</span>
    <span class="ps-vinted-channel {channel_class}">{_html_escape(channel_label)}</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            with st.popover("⚙ Gérer", use_container_width=True):
                _render_drop_management_actions(drops_data, active_id, active_drop)
        else:
            summary_col, action_col = st.columns([5, 1])
            with summary_col:
                st.markdown(
                    f"""
<div class="ps-vinted-drop-head">
  <strong>{_html_escape(active_drop.get('name', 'Drop sans nom'))}</strong>
  <div class="ps-vinted-drop-meta">
    <span>{total_cards} carte(s) · Valeur du drop : {fp_func(total_value) if total_value else 'à définir'}</span>
    <span class="ps-vinted-channel {channel_class}">{_html_escape(channel_label)}</span>
  </div>
</div>
""",
                    unsafe_allow_html=True,
                )
            with action_col:
                with st.popover("⚙ Gérer", use_container_width=True):
                    _render_drop_management_actions(drops_data, active_id, active_drop)

    if step == "Choix des cartes":
        if _render_drop_drawer_header("add_cards", "Ajouter des cartes au drop", default_open=True):
            _render_drop_add_search(drops_data, active_drop, available_cards, proxy_img_func, fp_func, mobile)

        if _render_drop_drawer_header("drop_cards", f"Cartes du drop ({total_cards})", default_open=True):
            _render_drop_grid(drops_data, active_drop, source_cards, proxy_img_func, fp_func, mobile)
    elif step == "Tri des photos":
        _render_photo_analysis_step(drops_data, active_drop, mobile)
    elif step == "Vérification":
        _render_photo_review_step(drops_data, active_drop, proxy_img_func, mobile, source_cards)
    elif step == "Création des annonces":
        recognition_result, recognition_session, _folder = _load_photo_workflow_state(active_drop)
        recognition_payload = None
        if recognition_result is not None:
            recognition_payload = _current_step4_payload(active_drop, recognition_result, recognition_session)
        _render_drop_creation_step(
            drops_data,
            active_drop,
            source_cards,
            proxy_img_func,
            fp_func,
            run_html_func,
            mobile,
            recognition_payload=recognition_payload,
        )
    elif step == "Analyse des drops":
        _render_drop_analytics(
            drops_data,
            ld_func() if callable(ld_func) else {},
            fp_func,
            calc_cout_lot_func,
            effective_purchase_price_func,
            active_drop=active_drop,
        )


def _render_classic_listing_section(cards, drops_data, proxy_img_func, fp_func, run_html_func, mobile, *, allow_drop_add=False):
    card_by_key = {card["_listing_key"]: card for card in cards}
    selected_keys = st.session_state.setdefault("vinted_selected_keys", [])
    active_drop_id = _active_drop_id(drops_data) if allow_drop_add else ""
    st.subheader("Créer une annonce")
    listing_type = st.radio(
        "Mode d'annonce",
        ["Carte seule", "Plusieurs cartes"],
        horizontal=not mobile,
        key="vinted_listing_type",
    )
    if listing_type == "Carte seule" and len(selected_keys) > 1:
        selected_keys = selected_keys[:1]
        st.session_state["vinted_selected_keys"] = selected_keys

    query = st.text_input(
        "Rechercher une carte disponible",
        key="vinted_search_query",
        placeholder="Ex : Meganium, Dracaufeu 199/165, Rayquaza 89/90...",
    )
    results_all = _filter_cards_for_display(cards, query)
    limit = _visible_limit("classic", query, mobile, len(results_all))
    results = results_all[:limit]
    st.caption(f"{len(results)} / {len(results_all)} carte(s) affichée(s).")
    _render_grouped_available_grid(
        results,
        scope="classic",
        listing_type=listing_type,
        selected_keys=selected_keys,
        drops_data=drops_data,
        active_drop_id=active_drop_id,
        proxy_img_func=proxy_img_func,
        fp_func=fp_func,
        mobile=mobile,
        mode="classic",
    )
    _show_more("classic", mobile, len(results_all))

    selected_cards = [card_by_key[key] for key in selected_keys if key in card_by_key]
    prepared = _sync_listing_text(selected_cards, listing_type, fp_func)
    if listing_type == "Plusieurs cartes":
        st.markdown(f'<span class="ps-vinted-pill">{len(selected_cards)} sélectionnée(s)</span>', unsafe_allow_html=True)
        if allow_drop_add:
            _render_selected_add_to_drop(drops_data, selected_cards, scope="classic")

    if selected_cards:
        left, right = st.columns([1, 1])
        with left:
            if st.button("Régénérer le titre et la description", width="stretch"):
                st.session_state["vinted_listing_title"] = prepared["title"]
                st.session_state["vinted_listing_description"] = prepared["description"]
                st.rerun()
        with right:
            if st.button("Réinitialiser", width="stretch"):
                _reset_vinted_form()

    _render_listing_preview(selected_cards, proxy_img_func, run_html_func, mobile)


def render_vinted_listings_page(
    *,
    ld_func,
    card_available_qty_func,
    is_collection_system_lot_func,
    proxy_img_func,
    render_page_header_func,
    fp_func,
    is_mobile_mode_func=None,
    perf_count_func=None,
    run_html_func=None,
    page_mode="drop",
    calc_cout_lot_func=None,
    effective_purchase_price_func=None,
):
    _inject_vinted_styles()

    d = ld_func()
    cards = _available_cards(d, card_available_qty_func, is_collection_system_lot_func)
    source_cards = _available_cards(
        d,
        card_available_qty_func,
        is_collection_system_lot_func,
        include_unavailable=True,
    )
    if perf_count_func:
        perf_count_func("vinted_cards_available", len(cards))

    drops_data = load_vinted_drops()
    mobile = bool(is_mobile_mode_func and is_mobile_mode_func())

    if page_mode == "individual" and not cards:
        st.markdown(
            render_page_header_func("Annonces individuelles", "Créer une annonce ponctuelle hors drop", "📝"),
            unsafe_allow_html=True,
        )
        st.info("Aucune carte disponible à la vente pour le moment.")
        return

    if page_mode == "individual":
        st.markdown(
            render_page_header_func("Annonces individuelles", "Créer une annonce ponctuelle hors drop", "📝"),
            unsafe_allow_html=True,
        )
        _render_classic_listing_section(cards, drops_data, proxy_img_func, fp_func, run_html_func, mobile, allow_drop_add=False)
        return

    active_drop = find_drop(drops_data, _active_drop_id(drops_data))
    if active_drop and st.session_state.get(_step4_preview_mode_key(active_drop.get("id"))):
        recognition_result, recognition_session, _folder = _load_photo_workflow_state(active_drop)
        if recognition_result is not None:
            recognition_payload = _current_step4_payload(active_drop, recognition_result, recognition_session)
            _render_step4_focus_preview(
                active_drop,
                source_cards,
                recognition_payload,
                run_html_func,
                mobile,
            )
            return
        st.session_state.pop(_step4_preview_mode_key(active_drop.get("id")), None)

    if st.session_state.get("vinted_drop_step") == "Analyse des drops":
        _inject_vinted_analytics_compact_styles()

    st.markdown(
        render_page_header_func("Drop Vinted", "Préparer, suivre et analyser tes drops Vinted", "🛍️"),
        unsafe_allow_html=True,
    )

    step = _render_drop_step_nav(mobile)
    _render_drops_manager(
        drops_data,
        cards,
        source_cards,
        proxy_img_func,
        fp_func,
        mobile,
        step,
        run_html_func=run_html_func,
        ld_func=ld_func,
        calc_cout_lot_func=calc_cout_lot_func,
        effective_purchase_price_func=effective_purchase_price_func,
    )

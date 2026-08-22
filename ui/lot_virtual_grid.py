"""Frontend-virtualized lot card grid."""

from __future__ import annotations

import hashlib
import json
import math

import streamlit as st

try:
    import streamlit.components.v2 as components_v2
except Exception:  # pragma: no cover - runtime capability
    components_v2 = None


_lot_grid_component = None


def component_v2_available() -> bool:
    return components_v2 is not None


def _get_lot_grid_component():
    global _lot_grid_component
    if components_v2 is None:
        return None
    if _lot_grid_component is not None:
        return _lot_grid_component

    css = """
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

    :host {
        display: block;
        width: 100%;
        font-family: "Plus Jakarta Sans", sans-serif;
    }
    .ps-lot-v-root,
    .ps-lot-v-root * {
        box-sizing: border-box;
        font-family: "Plus Jakarta Sans", sans-serif !important;
    }
    .ps-lot-v-root {
        position: relative;
        width: 100%;
        min-height: 1px;
        overflow: visible;
    }
    .ps-lot-v-stage {
        position: relative;
        width: 100%;
        min-height: 1px;
        overflow: visible;
    }
    .ps-lot-v-section {
        position: absolute;
        width: 100%;
        color: #0f172a;
        font-size: 0.92rem;
        font-weight: 900;
        line-height: 1.2;
        padding: 8px 0 10px;
    }
    .ps-lot-v-section.boxed {
        padding: 12px 14px;
        border-radius: 12px;
        border: 2px dashed #cbd5e1;
        background: #f8fafc;
    }
    .ps-lot-v-section.collection {
        color: #92400e;
        border-color: #f59e0b;
        background: #fffbeb;
    }
    .ps-lot-v-row {
        position: absolute;
        width: 100%;
        contain: layout paint;
    }
    .ps-lot-v-card {
        position: absolute;
        padding: 6px;
        border-radius: 14px;
        border: 1px solid transparent;
        background: transparent;
        overflow: visible;
    }
    .ps-lot-v-card.stored {
        background: #f0f9ff;
        border-color: #7dd3fc;
        box-shadow: 0 8px 20px rgba(3,105,161,0.08);
    }
    .ps-lot-v-card.collection {
        background: #fffbeb;
        border-color: #f59e0b;
        box-shadow: 0 8px 20px rgba(146,64,14,0.08);
    }
    .ps-lot-v-img-wrap {
        width: 100%;
        aspect-ratio: 0.72;
        border-radius: 12px;
        background: #f8fafc;
        border: 2px dashed #cbd5e1;
        color: #64748b;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
        font-size: 0.72rem;
        font-weight: 800;
        padding: 8px;
    }
    .ps-lot-v-img-wrap.has-img {
        padding: 0;
        border: 0;
        background: transparent;
    }
    .ps-lot-v-card.sold .ps-lot-v-img-wrap {
        opacity: 0.35;
        filter: grayscale(100%);
        border: 3px solid #e2e8f0;
    }
    .ps-lot-v-card.stored .ps-lot-v-img-wrap,
    .ps-lot-v-card.collection .ps-lot-v-img-wrap {
        border-radius: 10px;
    }
    .ps-lot-v-img-wrap img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
        border-radius: inherit;
    }
    .ps-lot-v-name {
        margin: 5px 0 3px;
        color: #0f172a;
        font-size: 0.84rem;
        font-weight: 800;
        line-height: 1.18;
        min-height: 34px;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .ps-lot-v-badges {
        display: inline;
        margin-left: 4px;
    }
    .ps-lot-v-stock,
    .ps-lot-v-note {
        color: #64748b;
        font-size: 0.7rem;
        font-weight: 700;
        line-height: 1.2;
    }
    .ps-lot-v-note.sale-note {
        color: #0f766e;
        font-weight: 900;
    }
    .ps-lot-v-input-row,
    .ps-lot-v-button-row {
        display: flex;
        align-items: center;
        gap: 5px;
        margin-top: 6px;
        min-width: 0;
    }
    .ps-lot-v-field {
        flex: 1;
        min-width: 0;
    }
    .ps-lot-v-field label {
        display: block;
        color: #64748b;
        font-size: 0.62rem;
        font-weight: 800;
        line-height: 1.1;
        margin-bottom: 2px;
    }
    .ps-lot-v-field input,
    .ps-lot-v-field select {
        width: 100%;
        min-width: 0;
        height: 28px;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        background: #fff;
        color: #0f172a;
        font-size: 0.72rem;
        font-weight: 800;
        padding: 0 6px;
    }
    .ps-lot-v-btn {
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        background: #ffffff;
        color: #334155;
        min-height: 28px;
        padding: 4px 7px;
        font-size: 0.68rem;
        font-weight: 900;
        cursor: pointer;
        white-space: nowrap;
    }
    .ps-lot-v-btn.primary {
        border-color: #8b5cf6;
        background: #ede9fe;
        color: #5b21b6;
    }
    .ps-lot-v-btn.danger {
        border-color: #fecaca;
        background: #fef2f2;
        color: #b91c1c;
    }
    .ps-lot-v-btn.good {
        border-color: #bbf7d0;
        background: #f0fdf4;
        color: #15803d;
    }
    @media (max-width: 768px) {
        .ps-lot-v-card {
            padding: 5px;
            border-radius: 12px;
        }
        .ps-lot-v-name {
            font-size: 0.76rem;
            min-height: 32px;
        }
        .ps-lot-v-stock,
        .ps-lot-v-note {
            font-size: 0.65rem;
        }
        .ps-lot-v-field input,
        .ps-lot-v-field select {
            height: 27px;
            font-size: 0.68rem;
        }
        .ps-lot-v-btn {
            min-height: 27px;
            padding: 4px 5px;
            font-size: 0.63rem;
        }
    }
    """

    js = r"""
    export default function(component) {
        const { data, parentElement, setTriggerValue } = component;
        const doc = parentElement.ownerDocument;
        const win = doc.defaultView || window;
        const root = parentElement.querySelector(".ps-lot-v-root");
        const stage = root.querySelector(".ps-lot-v-stage");
        const key = data.key || "lots";
        const stateKey = "__pokestockLotVirtualGrid_" + key;
        const sections = Array.isArray(data.sections) ? data.sections : [];
        const signature = String(data.signature || "");
        const gap = 10;
        const sectionGap = 14;
        const headerHeight = 44;
        const boxedHeaderHeight = 62;
        const state = win[stateKey] || {
            signature,
            layout: null,
            mounted: new Map(),
            lastRange: "",
            preloaded: new Map(),
            fields: {}
        };
        if (state.mounted && state.mounted.size) {
            const staleMountedNodes = Array.from(state.mounted.values()).some((node) => !stage.contains(node));
            if (staleMountedNodes) {
                state.mounted = new Map();
                state.lastRange = "";
            }
        }

        function findScrollTarget(el) {
            let node = el && el.parentElement;
            while (node && node !== doc.body && node !== doc.documentElement) {
                const style = win.getComputedStyle(node);
                const overflow = (style.overflowY || style.overflow || "").toLowerCase();
                if ((overflow.includes("auto") || overflow.includes("scroll")) && node.scrollHeight > node.clientHeight) {
                    return node;
                }
                node = node.parentElement;
            }
            return win;
        }
        const scrollTarget = findScrollTarget(parentElement);

        if (state.signature !== signature) {
            state.signature = signature;
            state.layout = null;
            state.mounted = new Map();
            state.lastRange = "";
            state.preloaded = new Map();
            state.fields = {};
            stage.replaceChildren();
        }
        win[stateKey] = state;

        function columns() {
            return win.matchMedia("(max-width: 768px)").matches ? 2 : 6;
        }

        function cardHeight() {
            return win.matchMedia("(max-width: 768px)").matches ? 545 : 510;
        }

        function overscanRows() {
            return win.matchMedia("(max-width: 768px)").matches ? { before: 4, after: 9 } : { before: 3, after: 6 };
        }

        function itemKey(item) {
            return String(item.card_uid || item.card_key || item.lot_idx + "_" + item.card_idx);
        }

        function emit(type, item, extra) {
            setTriggerValue("action", Object.assign({
                id: type + "-" + itemKey(item) + "-" + Date.now() + "-" + Math.random().toString(36).slice(2),
                type,
                lot_idx: item.lot_idx,
                card_idx: item.card_idx,
                card_uid: item.card_uid,
                section: item.section
            }, extra || {}));
        }

        function valueFor(key, fallback) {
            if (Object.prototype.hasOwnProperty.call(state.fields, key)) return state.fields[key];
            return fallback;
        }

        function setField(key, value) {
            state.fields[key] = value;
        }

        function makeInput(label, type, value, onCommit, attrs) {
            const wrap = doc.createElement("div");
            wrap.className = "ps-lot-v-field";
            const lab = doc.createElement("label");
            lab.textContent = label;
            const input = doc.createElement("input");
            input.type = type || "text";
            input.value = value == null ? "" : String(value);
            Object.entries(attrs || {}).forEach(([k, v]) => input.setAttribute(k, String(v)));
            input.addEventListener("change", () => onCommit(input.value));
            lab.appendChild(input);
            wrap.appendChild(lab);
            return { wrap, input };
        }

        function makeButton(label, cls, onClick) {
            const btn = doc.createElement("button");
            btn.type = "button";
            btn.className = "ps-lot-v-btn " + (cls || "");
            btn.textContent = label;
            btn.onclick = (event) => {
                event.preventDefault();
                onClick();
            };
            return btn;
        }

        function buildRows(colCount, rowHeight) {
            const rows = [];
            let top = 0;
            sections.forEach((section, sectionIndex) => {
                const cards = Array.isArray(section.cards) ? section.cards : [];
                if (!cards.length) return;
                const h = section.boxed ? boxedHeaderHeight : headerHeight;
                rows.push({
                    type: "header",
                    key: "h-" + section.key,
                    top,
                    height: h,
                    section,
                    sectionIndex
                });
                top += h;
                for (let start = 0; start < cards.length; start += colCount) {
                    rows.push({
                        type: "cards",
                        key: "r-" + section.key + "-c" + colCount + "-" + start,
                        top,
                        height: rowHeight,
                        section,
                        cards: cards.slice(start, start + colCount)
                    });
                    top += rowHeight + gap;
                }
                top += sectionGap;
            });
            return { rows, totalHeight: Math.max(1, top) };
        }

        function layoutFor(colCount, rowHeight) {
            if (
                state.layout &&
                state.layout.signature === signature &&
                state.layout.colCount === colCount &&
                state.layout.rowHeight === rowHeight
            ) {
                return state.layout;
            }
            const built = buildRows(colCount, rowHeight);
            state.layout = {
                signature,
                colCount,
                rowHeight,
                rows: built.rows,
                totalHeight: built.totalHeight
            };
            state.lastRange = "";
            return state.layout;
        }

        function makeHeader(row) {
            const el = doc.createElement("div");
            el.className = "ps-lot-v-section" + (row.section.boxed ? " boxed" : "") + (row.section.key === "collection" ? " collection" : "");
            el.textContent = row.section.title || "";
            return el;
        }

        function makeImage(item, card) {
            const wrap = doc.createElement("div");
            wrap.className = "ps-lot-v-img-wrap" + (item.image_url ? " has-img" : "");
            if (item.image_url) {
                const img = doc.createElement("img");
                img.alt = item.name || "Carte";
                img.loading = "eager";
                img.decoding = "async";
                img.src = item.image_url;
                img.onerror = () => {
                    wrap.className = "ps-lot-v-img-wrap";
                    wrap.textContent = "Image indisponible";
                };
                wrap.appendChild(img);
            } else {
                wrap.textContent = "Image indisponible";
                wrap.onclick = () => emit("upload_image", item);
            }
            card.appendChild(wrap);
        }

        function makeCard(item, width, height) {
            const key = itemKey(item);
            const card = doc.createElement("div");
            card.className = "ps-lot-v-card " + (item.status || "");
            card.style.width = width + "px";
            card.style.height = height + "px";
            makeImage(item, card);

            const name = doc.createElement("div");
            name.className = "ps-lot-v-name";
            const nameText = doc.createElement("span");
            nameText.textContent = item.name || "Carte";
            name.appendChild(nameText);
            if (item.badges_html) {
                const badges = doc.createElement("span");
                badges.className = "ps-lot-v-badges";
                badges.innerHTML = item.badges_html;
                name.appendChild(badges);
            }
            card.appendChild(name);

            const stock = doc.createElement("div");
            stock.className = "ps-lot-v-stock";
            stock.textContent = item.stock_text || "";
            card.appendChild(stock);
            if (item.sale_note) {
                const note = doc.createElement("div");
                note.className = "ps-lot-v-note sale-note";
                note.textContent = item.sale_note;
                card.appendChild(note);
            }

            if (item.sold) {
                const sold = doc.createElement("div");
                sold.className = "ps-lot-v-note";
                sold.textContent = item.sold_label || "";
                card.appendChild(sold);
                const row = doc.createElement("div");
                row.className = "ps-lot-v-button-row";
                row.appendChild(makeButton("Restaurer", "good", () => emit("restore", item)));
                row.appendChild(makeButton("Supprimer", "danger", () => emit("delete", item)));
                card.appendChild(row);
                return card;
            }

            const priceRow = doc.createElement("div");
            priceRow.className = "ps-lot-v-input-row";
            const priceKey = "price_" + key;
            const price = makeInput(
                item.collection ? "Valeur actuelle (€)" : "Prix (€)",
                "number",
                valueFor(priceKey, item.price),
                (value) => {
                    setField(priceKey, value);
                    emit("set_price", item, { value: Number(value || 0) });
                },
                { min: 0, max: 9999, step: 0.5 }
            );
            priceRow.appendChild(price.wrap);
            card.appendChild(priceRow);

            if (item.price_delta_label) {
                const delta = doc.createElement("div");
                delta.className = "ps-lot-v-note";
                delta.textContent = item.price_delta_label;
                card.appendChild(delta);
            }

            if (!item.collection) {
                const qtyRow = doc.createElement("div");
                qtyRow.className = "ps-lot-v-input-row";
                const qtyKey = "qty_" + key;
                const qty = makeInput(
                    "Qté totale",
                    "number",
                    valueFor(qtyKey, item.quantity),
                    (value) => {
                        setField(qtyKey, value);
                        emit("set_quantity", item, { value: Number(value || 0) });
                    },
                    { min: item.sold_quantity || 0, max: 9999, step: 1 }
                );
                qtyRow.appendChild(qty.wrap);
                card.appendChild(qtyRow);
            }

            if (item.trade_move) {
                const row = doc.createElement("div");
                row.className = "ps-lot-v-input-row";
                const qtyKey = "move_qty_" + key;
                const qty = makeInput(
                    "Qté",
                    "number",
                    valueFor(qtyKey, 1),
                    (value) => setField(qtyKey, value),
                    { min: 1, max: Math.max(1, Number(item.available || 1)), step: 1 }
                );
                row.appendChild(qty.wrap);
                row.appendChild(makeButton("Collection", "primary", () => emit("trade_transfer", item, { destination: "collection", quantity: Number(valueFor(qtyKey, 1) || 1) })));
                row.appendChild(makeButton("Stockage", "primary", () => emit("trade_transfer", item, { destination: "stockage", quantity: Number(valueFor(qtyKey, 1) || 1) })));
                card.appendChild(row);
            } else if (item.can_store) {
                const row = doc.createElement("div");
                row.className = "ps-lot-v-input-row";
                const qtyKey = "store_qty_" + key;
                const coteKey = "store_cote_" + key;
                const qty = makeInput(
                    "Qté",
                    "number",
                    valueFor(qtyKey, 1),
                    (value) => setField(qtyKey, value),
                    { min: 1, max: Math.max(1, Number(item.available || 1)), step: 1 }
                );
                const cote = makeInput(
                    "Cote",
                    "number",
                    valueFor(coteKey, item.price),
                    (value) => setField(coteKey, value),
                    { min: 0, max: 99999, step: 0.5 }
                );
                row.appendChild(qty.wrap);
                row.appendChild(cote.wrap);
                row.appendChild(makeButton("Stocker", "primary", () => emit("store", item, { quantity: Number(valueFor(qtyKey, 1) || 1), storage_cote: Number(valueFor(coteKey, item.price) || 0) })));
                card.appendChild(row);
            }

            const actions = doc.createElement("div");
            actions.className = "ps-lot-v-button-row";
            actions.appendChild(makeButton("Image", "", () => emit("upload_image", item)));
            actions.appendChild(makeButton("Suppr.", "danger", () => emit("delete", item)));
            card.appendChild(actions);
            return card;
        }

        function makeCardRow(row, cardWidth, rowHeight) {
            const el = doc.createElement("div");
            el.className = "ps-lot-v-row";
            el.style.height = rowHeight + "px";
            row.cards.forEach((item, index) => {
                const card = makeCard(item, cardWidth, rowHeight);
                card.style.transform = "translate3d(" + (index * (cardWidth + gap)) + "px,0,0)";
                el.appendChild(card);
            });
            return el;
        }

        function preload(rows, start, end) {
            let loaded = 0;
            const now = Date.now();
            for (let i = Math.max(0, start); i < Math.min(rows.length, end); i++) {
                const row = rows[i];
                if (!row || row.type !== "cards") continue;
                row.cards.forEach((item) => {
                    if (!item.image_url || loaded >= 48) return;
                    if (state.preloaded.has(item.image_url)) {
                        const cached = state.preloaded.get(item.image_url);
                        if (cached) cached.time = now;
                        return;
                    }
                    try {
                        const img = new Image();
                        img.decoding = "async";
                        img.loading = "eager";
                        img.src = item.image_url;
                        state.preloaded.set(item.image_url, { time: now, img });
                        loaded += 1;
                    } catch (e) {}
                });
            }
            if (state.preloaded.size > 96) {
                const stale = Array.from(state.preloaded.entries())
                    .sort((a, b) => (a[1].time || 0) - (b[1].time || 0))
                    .slice(0, state.preloaded.size - 96);
                stale.forEach(([url]) => state.preloaded.delete(url));
            }
        }

        function viewportHeight() {
            return scrollTarget === win ? (win.innerHeight || doc.documentElement.clientHeight || 800) : scrollTarget.clientHeight;
        }

        function visibleTop() {
            const rect = root.getBoundingClientRect();
            const targetRect = scrollTarget === win ? { top: 0 } : scrollTarget.getBoundingClientRect();
            return Math.max(0, targetRect.top - rect.top);
        }

        function lowerBound(rows, y) {
            let lo = 0;
            let hi = rows.length;
            while (lo < hi) {
                const mid = (lo + hi) >> 1;
                if (rows[mid].top + rows[mid].height < y) lo = mid + 1;
                else hi = mid;
            }
            return lo;
        }

        function render() {
            const colCount = columns();
            const rowHeight = cardHeight();
            const rootWidth = Math.max(240, root.clientWidth || parentElement.clientWidth || 390);
            const cardWidth = Math.floor((rootWidth - gap * (colCount - 1)) / colCount);
            const layout = layoutFor(colCount, rowHeight);
            const rows = layout.rows;
            const totalHeight = layout.totalHeight;
            stage.style.height = totalHeight + "px";
            parentElement.style.height = totalHeight + "px";
            parentElement.style.minHeight = totalHeight + "px";

            const startY = visibleTop();
            const endY = startY + viewportHeight();
            const overscan = overscanRows();
            const start = Math.max(0, lowerBound(rows, startY - overscan.before * rowHeight));
            const end = Math.min(rows.length, lowerBound(rows, endY + overscan.after * rowHeight) + 1);
            const rangeKey = start + ":" + end + ":" + colCount + ":" + cardWidth + ":" + totalHeight;
            if (rangeKey === state.lastRange && stage.childElementCount) {
                preload(rows, end, end + overscan.after);
                return;
            }
            state.lastRange = rangeKey;

            const keep = new Set();
            for (let index = start; index < end; index++) {
                const row = rows[index];
                if (!row) continue;
                keep.add(row.key);
                let node = state.mounted.get(row.key);
                if (!node) {
                    node = row.type === "header" ? makeHeader(row) : makeCardRow(row, cardWidth, rowHeight);
                    state.mounted.set(row.key, node);
                    stage.appendChild(node);
                }
                node.style.transform = "translate3d(0," + row.top + "px,0)";
                if (row.type === "cards") {
                    node.style.height = rowHeight + "px";
                    Array.from(node.children).forEach((card, cardIndex) => {
                        card.style.width = cardWidth + "px";
                        card.style.height = rowHeight + "px";
                        card.style.transform = "translate3d(" + (cardIndex * (cardWidth + gap)) + "px,0,0)";
                    });
                }
            }

            for (const [rowKey, node] of Array.from(state.mounted.entries())) {
                if (!keep.has(rowKey)) {
                    node.remove();
                    state.mounted.delete(rowKey);
                }
            }
            preload(rows, end, end + overscan.after);
        }

        let raf = 0;
        function schedule() {
            if (raf) return;
            raf = win.requestAnimationFrame(() => {
                raf = 0;
                render();
            });
        }

        if (state.scrollListener && state.scrollTarget) {
            try { state.scrollTarget.removeEventListener("scroll", state.scrollListener); } catch (e) {}
        }
        if (state.resizeListener) {
            try { win.removeEventListener("resize", state.resizeListener); } catch (e) {}
        }
        scrollTarget.addEventListener("scroll", schedule, { passive: true });
        win.addEventListener("resize", schedule, { passive: true });
        state.scrollTarget = scrollTarget;
        state.scrollListener = schedule;
        state.resizeListener = schedule;
        if (doc.fonts && doc.fonts.load) {
            doc.fonts.load('400 14px "Plus Jakarta Sans"').then(schedule).catch(() => {});
            doc.fonts.load('700 14px "Plus Jakarta Sans"').then(schedule).catch(() => {});
        }
        schedule();

        return () => {
            scrollTarget.removeEventListener("scroll", schedule);
            win.removeEventListener("resize", schedule);
        };
    }
    """

    _lot_grid_component = components_v2.component(
        "pokestock_lot_virtual_grid",
        html=(
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap">'
            '<div class="ps-lot-v-root"><div class="ps-lot-v-stage"></div></div>'
        ),
        css=css,
        js=js,
        isolate_styles=False,
    )
    return _lot_grid_component


def lot_payload_signature(sections) -> str:
    compact = []
    for section in sections or []:
        compact.append(
            (
                section.get("key"),
                [
                    (
                        item.get("lot_idx"),
                        item.get("card_idx"),
                        item.get("card_uid"),
                        item.get("status"),
                        item.get("quantity"),
                        item.get("sold_quantity"),
                        item.get("stored_quantity"),
                        item.get("price"),
                        item.get("image_url"),
                    )
                    for item in section.get("cards", []) or []
                ],
            )
        )
    raw = json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def estimated_lot_virtual_height(sections, *, mobile=False) -> int:
    cols = 2 if mobile else 6
    row_height = 545 if mobile else 510
    gap = 10
    total = 0
    for section in sections or []:
        cards = section.get("cards", []) or []
        if not cards:
            continue
        total += 62 if section.get("boxed") else 44
        total += max(1, math.ceil(len(cards) / cols)) * (row_height + gap)
        total += 14
    return max(1, total)


def render_lot_virtual_grid(sections, *, key="lots", height=None, mobile=False):
    component = _get_lot_grid_component()
    if component is None:
        return None

    def _noop():
        return None

    result = component(
        key=f"lot_virtual_grid_{key}",
        data={
            "key": key,
            "signature": lot_payload_signature(sections),
            "sections": list(sections or []),
        },
        default={"action": None},
        width="stretch",
        height=height or estimated_lot_virtual_height(sections, mobile=mobile),
        on_action_change=_noop,
    )
    return getattr(result, "action", None)

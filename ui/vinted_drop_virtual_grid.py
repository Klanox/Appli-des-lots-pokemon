"""Frontend-virtualized Vinted drop add grid."""

from __future__ import annotations

import hashlib
import json
import math

try:
    import streamlit.components.v2 as components_v2
except Exception:  # pragma: no cover - runtime capability
    components_v2 = None


_vinted_drop_grid_component = None


def _get_vinted_drop_grid_component():
    global _vinted_drop_grid_component
    if components_v2 is None:
        return None
    if _vinted_drop_grid_component is not None:
        return _vinted_drop_grid_component

    css = """
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

    :host {
        display: block;
        width: 100%;
        font-family: "Plus Jakarta Sans", sans-serif;
    }
    .ps-sale-lot-root {
        position: relative;
        width: 100%;
        min-height: 1px;
        overflow: visible;
        font-family: "Plus Jakarta Sans", sans-serif;
    }
    .ps-sale-lot-root,
    .ps-sale-lot-root * {
        font-family: "Plus Jakarta Sans", sans-serif !important;
    }
    .ps-sale-lot-stage {
        position: relative;
        width: 100%;
        min-height: 1px;
        overflow: visible;
    }
    .ps-sale-lot-header {
        position: absolute;
        box-sizing: border-box;
        width: 100%;
        color: #0f172a;
        font-size: 1.08rem;
        font-weight: 900;
        line-height: 1.2;
        padding: 6px 0 8px 0;
    }
    .ps-sale-lot-row {
        position: absolute;
        box-sizing: border-box;
        width: 100%;
        contain: layout;
    }
    .ps-sale-lot-card {
        position: absolute;
        box-sizing: border-box;
        overflow: visible;
        padding: 0;
        background: transparent;
        border: 0;
        box-shadow: none;
    }
    .ps-sale-img-wrap {
        position: relative;
        width: 100%;
        aspect-ratio: 0.72;
        border-radius: 12px;
        background: #f8fafc;
        border: 0;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #64748b;
        font-size: 0.72rem;
        font-weight: 800;
        text-align: center;
    }
    .ps-sale-img-wrap img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
        border: 0;
    }
    .ps-sale-lot-card.in-cart .ps-sale-img-wrap {
        box-shadow: 0 0 0 4px #22c55e;
    }
    .ps-sale-ok {
        position: absolute;
        top: 5px;
        right: 5px;
        width: 24px;
        height: 24px;
        border-radius: 999px;
        background: #22c55e;
        color: #fff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.68rem;
        font-weight: 900;
    }
    .ps-sale-stamp {
        position: absolute;
        left: 5px;
        top: 5px;
        border-radius: 999px;
        background: #fdf2f8;
        color: #db2777;
        border: 1px solid #fbcfe8;
        font-size: 0.62rem;
        font-weight: 900;
        padding: 3px 7px;
        max-width: calc(100% - 10px);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .ps-sale-name {
        min-height: 38px;
        margin-top: 8px;
        color: #0f172a;
        font-size: 0.86rem;
        font-weight: 800;
        line-height: 1.22;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .ps-sale-meta,
    .ps-sale-price {
        color: #64748b;
        font-size: 0.72rem;
        line-height: 1.2;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .ps-sale-price {
        margin-top: 5px;
        color: #334155;
        font-weight: 700;
    }
    .ps-sale-duplicate {
        display: none;
        width: max-content;
        max-width: 100%;
        margin-top: 5px;
        border-radius: 999px;
        padding: 3px 7px;
        border: 1px solid #fed7aa;
        background: #ffedd5;
        color: #c2410c;
        font-size: 0.66rem;
        font-weight: 900;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .ps-sale-duplicate.visible {
        display: inline-flex;
    }
    .ps-sale-actions {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-top: 8px;
    }
    .ps-sale-stepper {
        display: flex;
        align-items: center;
        min-width: 74px;
        border: 1px solid #cbd5e1;
        border-radius: 999px;
        overflow: hidden;
        background: #f8fafc;
    }
    .ps-sale-stepper button {
        width: 24px;
        height: 28px;
        border: 0;
        background: transparent;
        color: #334155;
        font-weight: 900;
        font-size: 0.86rem;
        cursor: pointer;
        padding: 0;
    }
    .ps-sale-stepper span {
        min-width: 24px;
        text-align: center;
        color: #0f172a;
        font-size: 0.78rem;
        font-weight: 800;
    }
    .ps-sale-add {
        flex: 1;
        height: 30px;
        border: 0;
        border-radius: 999px;
        background: #2563eb;
        color: #fff;
        font-size: 0.76rem;
        font-weight: 900;
        cursor: pointer;
        padding: 0 8px;
    }
    .ps-sale-lot-card.in-cart .ps-sale-add {
        background: #22c55e;
    }
    .ps-sale-selection-footer {
        box-sizing: border-box;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        min-height: 56px;
        margin-top: 12px;
        padding: 10px 12px;
        border: 1px solid #c7d2fe;
        border-radius: 14px;
        background: linear-gradient(135deg, #ffffff, #eef2ff);
        color: #334155;
        font-weight: 800;
        box-shadow: 0 8px 22px rgba(79, 70, 229, 0.08);
    }
    .ps-sale-selection-footer button {
        min-height: 34px;
        border: 0;
        border-radius: 999px;
        background: #6d5dfc;
        color: #fff;
        font-size: 0.78rem;
        font-weight: 900;
        padding: 0 14px;
        cursor: pointer;
    }
    .ps-sale-selection-footer button:disabled {
        cursor: default;
        opacity: 0.48;
    }
    @media (max-width: 768px) {
        .ps-sale-lot-header {
            font-size: 1rem;
            padding: 5px 0 7px 0;
        }
        .ps-sale-name {
            font-size: 0.78rem;
            min-height: 36px;
        }
        .ps-sale-meta,
        .ps-sale-price {
            font-size: 0.68rem;
        }
        .ps-sale-actions {
            gap: 4px;
        }
        .ps-sale-stepper {
            min-width: 66px;
        }
        .ps-sale-stepper button {
            width: 21px;
        }
        .ps-sale-add {
            height: 29px;
            font-size: 0.7rem;
        }
        .ps-sale-selection-footer {
            align-items: stretch;
            flex-direction: column;
            gap: 8px;
        }
    }
    """

    js = r"""
    export default function(component) {
        const { data, parentElement, setTriggerValue } = component;
        const saleFont = '"Plus Jakarta Sans", sans-serif';
        parentElement.style.width = "100%";
        parentElement.style.overflow = "visible";
        parentElement.style.fontFamily = saleFont;

        const doc = parentElement.ownerDocument;
        const win = doc.defaultView || window;
        const root = parentElement.querySelector(".ps-sale-lot-root");
        const stage = root.querySelector(".ps-sale-lot-stage");
        const footer = root.querySelector(".ps-sale-selection-footer");
        root.style.fontFamily = saleFont;
        stage.style.fontFamily = saleFont;
        footer.style.fontFamily = saleFont;
        const key = data.key || "vinted_drop";
        const stateKey = "__pokestockVintedDropGrid_" + key;
        const groups = Array.isArray(data.groups) ? data.groups : [];
        const baseDuplicateCounts = data.duplicateCounts && typeof data.duplicateCounts === "object" ? data.duplicateCounts : {};
        const signature = String(data.signature || "");
        const scrollTopToken = String(data.scrollTopToken || "");
        const committedSelectionToken = String(data.committedSelectionToken || "");
        const gap = 10;
        const lotGap = 14;
        const headerHeight = 42;
        const state = win[stateKey] || {
            signature,
            qty: {},
            selected: {},
            mounted: new Map(),
            lastRange: "",
            layout: null,
            preloaded: new Map(),
            committedSelectionToken: ""
        };
        state.selected = state.selected && typeof state.selected === "object" ? state.selected : {};
        if (committedSelectionToken && state.committedSelectionToken !== committedSelectionToken) {
            state.selected = {};
            state.qty = {};
            state.batchSubmitting = false;
            state.committedSelectionToken = committedSelectionToken;
            state.lastRange = "";
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

        if (state.mounted && state.mounted.size) {
            const staleMountedNodes = Array.from(state.mounted.values()).some((node) => !stage.contains(node));
            if (staleMountedNodes) {
                state.mounted = new Map();
                state.lastRange = "";
            }
        }
        if (state.signature !== signature) {
            state.signature = signature;
            state.qty = {};
            state.mounted = new Map();
            state.lastRange = "";
            state.layout = null;
            state.preloaded = new Map();
            stage.replaceChildren();
        }
        win[stateKey] = state;

        function columns() {
            return win.matchMedia("(max-width: 768px)").matches ? 2 : 6;
        }

        function cardHeight() {
            return win.matchMedia("(max-width: 768px)").matches ? 410 : 470;
        }

        function overscanRows() {
            return win.matchMedia("(max-width: 768px)").matches ? { before: 4, after: 8 } : { before: 3, after: 5 };
        }

        function itemKey(item) {
            return String(item.card_key || item.card_uid || item.lot_uid + "_" + item.card_idx);
        }

        function effectiveAdded(key) {
            return Boolean(state.selected[key]);
        }

        function effectiveDuplicateInfo(item) {
            const fingerprint = String(item.duplicate_fingerprint || "");
            if (!fingerprint) return { base: 0, selected: 0 };
            const base = Math.max(0, Number(baseDuplicateCounts[fingerprint] || 0));
            let selected = 0;
            Object.values(state.selected).forEach((selection) => {
                if (!selection || String(selection.duplicate_fingerprint || "") !== fingerprint) return;
                selected += 1;
            });
            if (effectiveAdded(itemKey(item))) selected -= 1;
            return { base, selected: Math.max(0, selected) };
        }

        function pendingSignature() {
            return JSON.stringify(Object.values(state.selected).map((selection) => [
                String(selection.card_key || ""),
                String(selection.quantity || 1),
                String(selection.duplicate_fingerprint || "")
            ]).sort());
        }

        function selectedCount() {
            return Object.keys(state.selected).length;
        }

        function updateFooter() {
            const count = selectedCount();
            footer.replaceChildren();
            const label = doc.createElement("div");
            label.textContent = count + " carte" + (count > 1 ? "s" : "") + " sélectionnée" + (count > 1 ? "s" : "");
            const button = doc.createElement("button");
            button.type = "button";
            button.disabled = count <= 0 || Boolean(state.batchSubmitting);
            button.textContent = state.batchSubmitting
                ? "Validation..."
                : (count > 0 ? "✓ Valider les " + count + " carte" + (count > 1 ? "s" : "") + " sélectionnée" + (count > 1 ? "s" : "") : "✓ Valider la sélection");
            button.onclick = (event) => {
                event.preventDefault();
                if (selectedCount() <= 0 || state.batchSubmitting) return;
                state.batchSubmitting = true;
                updateFooter();
                setTriggerValue("batch", {
                    id: "vinted-drop-batch-" + Date.now() + "-" + Math.random().toString(36).slice(2),
                    selections: Object.values(state.selected)
                });
            };
            footer.appendChild(label);
            footer.appendChild(button);
        }

        function applyCardVisual(card, key) {
            const itemJson = card.dataset.item || "";
            let item = {};
            try { item = JSON.parse(itemJson); } catch (e) {}
            const isAdded = effectiveAdded(key);
            card.className = "ps-sale-lot-card" + (isAdded ? " in-cart" : "");
            const imageWrap = card.querySelector(".ps-sale-img-wrap");
            if (imageWrap) {
                let ok = imageWrap.querySelector(".ps-sale-ok");
                if (isAdded && !ok) {
                    ok = doc.createElement("span");
                    ok.className = "ps-sale-ok";
                    ok.textContent = "OK";
                    imageWrap.appendChild(ok);
                } else if (!isAdded && ok) {
                    ok.remove();
                }
            }
            const button = card.querySelector(".ps-sale-add");
            if (button) {
                button.textContent = isAdded ? "✓ Sélectionnée" : "Sélectionner";
            }
            const duplicate = card.querySelector(".ps-sale-duplicate");
            if (duplicate) {
                const duplicateInfo = effectiveDuplicateInfo(item);
                if (duplicateInfo.base > 0) {
                    duplicate.textContent = duplicateInfo.base > 1 ? "⚠ Déjà présent ×" + duplicateInfo.base : "⚠ Déjà présent dans le drop";
                    duplicate.classList.add("visible");
                } else if (duplicateInfo.selected > 0) {
                    duplicate.textContent = duplicateInfo.selected > 1 ? "⚠ Déjà sélectionné ×" + duplicateInfo.selected : "⚠ Déjà sélectionné";
                    duplicate.classList.add("visible");
                } else {
                    duplicate.textContent = "";
                    duplicate.classList.remove("visible");
                }
            }
        }

        function refreshMountedCardVisuals(key) {
            stage.querySelectorAll(".ps-sale-lot-card").forEach((card) => {
                if (String(card.dataset.cardKey || "") === key) {
                    applyCardVisual(card, key);
                }
            });
        }

        function clampQty(key, maxQty) {
            const current = Number((state.selected[key] && state.selected[key].quantity) || state.qty[key] || 1);
            return Math.max(1, Math.min(Math.max(1, Number(maxQty || 1)), current || 1));
        }

        function text(parent, cls, value) {
            const el = doc.createElement("div");
            el.className = cls;
            el.textContent = value || "";
            parent.appendChild(el);
            return el;
        }

        function buildRows(colCount, rowHeight) {
            const rows = [];
            let top = 0;
            groups.forEach((group, groupIndex) => {
                const cards = Array.isArray(group.cards) ? group.cards : [];
                if (!cards.length) return;
                rows.push({
                    type: "header",
                    key: "h-" + (group.lot_uid || group.lot_idx || groupIndex),
                    top,
                    height: headerHeight,
                    group,
                    groupIndex
                });
                top += headerHeight;
                for (let start = 0; start < cards.length; start += colCount) {
                    rows.push({
                        type: "cards",
                        key: "r-" + (group.lot_uid || group.lot_idx || groupIndex) + "-c" + colCount + "-" + start,
                        top,
                        height: rowHeight,
                        group,
                        groupIndex,
                        cards: cards.slice(start, start + colCount),
                        rowStart: start
                    });
                    top += rowHeight + gap;
                }
                top += lotGap;
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
            el.className = "ps-sale-lot-header";
            el.style.fontFamily = saleFont;
            const lotName = String(row.group.lot_name || "").trim();
            el.textContent = lotName.toLowerCase().startsWith("lot ") ? lotName : "Lot " + lotName;
            return el;
        }

        function makeCard(item, width, height) {
            const key = itemKey(item);
            const isAdded = effectiveAdded(key);
            const card = doc.createElement("div");
            card.className = "ps-sale-lot-card" + (isAdded ? " in-cart" : "");
            card.dataset.cardKey = key;
            card.dataset.item = JSON.stringify({
                card_key: key,
                duplicate_fingerprint: item.duplicate_fingerprint || ""
            });
            card.style.width = width + "px";
            card.style.height = height + "px";
            card.style.fontFamily = saleFont;

            const imageWrap = doc.createElement("div");
            imageWrap.className = "ps-sale-img-wrap";
            if (item.image_url) {
                const img = doc.createElement("img");
                img.alt = item.name || "Carte";
                img.loading = "eager";
                img.decoding = "async";
                img.src = item.image_url;
                img.onerror = () => {
                    imageWrap.textContent = "Image indisponible";
                };
                imageWrap.appendChild(img);
            } else {
                imageWrap.textContent = "Image indisponible";
            }
            if (isAdded) {
                const ok = doc.createElement("span");
                ok.className = "ps-sale-ok";
                ok.textContent = "OK";
                imageWrap.appendChild(ok);
            }
            if (item.stamp_label) {
                const stamp = doc.createElement("span");
                stamp.className = "ps-sale-stamp";
                stamp.textContent = String(item.stamp_label);
                imageWrap.appendChild(stamp);
            }
            card.appendChild(imageWrap);
            text(card, "ps-sale-name", item.name || "Carte");
            text(card, "ps-sale-meta", (item.set || "") + (item.number ? " · #" + item.number : ""));
            text(card, "ps-sale-price", (item.price_label || "") + " · Stock " + String(item.stock || 0));
            const duplicate = doc.createElement("div");
            duplicate.className = "ps-sale-duplicate";
            card.appendChild(duplicate);
            applyCardVisual(card, key);

            const actions = doc.createElement("div");
            actions.className = "ps-sale-actions";
            const stepper = doc.createElement("div");
            stepper.className = "ps-sale-stepper";
            const minus = doc.createElement("button");
            minus.type = "button";
            minus.textContent = "−";
            const qty = doc.createElement("span");
            qty.textContent = String(clampQty(key, item.stock));
            const plus = doc.createElement("button");
            plus.type = "button";
            plus.textContent = "+";
            minus.onclick = (event) => {
                event.preventDefault();
                const next = Math.max(1, clampQty(key, item.stock) - 1);
                state.qty[key] = next;
                qty.textContent = String(next);
                if (state.selected[key]) state.selected[key].quantity = next;
            };
            plus.onclick = (event) => {
                event.preventDefault();
                const next = Math.min(Number(item.stock || 1), clampQty(key, item.stock) + 1);
                state.qty[key] = next;
                qty.textContent = String(next);
                if (state.selected[key]) state.selected[key].quantity = next;
            };
            stepper.appendChild(minus);
            stepper.appendChild(qty);
            stepper.appendChild(plus);
            actions.appendChild(stepper);

            const action = doc.createElement("button");
            action.type = "button";
            action.className = "ps-sale-add";
            action.textContent = isAdded ? "✓ Sélectionnée" : "Sélectionner";
            action.onclick = (event) => {
                event.preventDefault();
                const currentlyAdded = effectiveAdded(key);
                if (currentlyAdded) {
                    delete state.selected[key];
                } else {
                    state.selected[key] = {
                        card_key: key,
                        card_uid: item.card_uid,
                        lot_uid: item.lot_uid,
                        lot_idx: item.lot_idx,
                        card_idx: item.card_idx,
                        duplicate_fingerprint: item.duplicate_fingerprint || "",
                        quantity: clampQty(key, item.stock),
                        ts: Date.now()
                    };
                }
                updateFooter();
                refreshMountedCardVisuals(key);
                state.lastRange = "";
                schedule();
            };
            actions.appendChild(action);
            card.appendChild(actions);
            return card;
        }

        function makeCardRow(row, cardWidth, rowHeight) {
            const el = doc.createElement("div");
            el.className = "ps-sale-lot-row";
            el.style.height = rowHeight + "px";
            el.style.fontFamily = saleFont;
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

        function runScrollTopAfterLayout() {
            const consumedTokenKey = "__pokestockVintedDropScrollTopConsumedToken";
            if (!scrollTopToken || win[consumedTokenKey] === scrollTopToken) return;
            win[consumedTokenKey] = scrollTopToken;
            win.requestAnimationFrame(() => {
                win.requestAnimationFrame(() => {
                    const top = Math.max(0, root.getBoundingClientRect().top + (scrollTarget === win ? win.scrollY : scrollTarget.scrollTop) - 12);
                    if (scrollTarget === win) {
                        win.scrollTo({ top, left: 0, behavior: "instant" });
                    } else {
                        scrollTarget.scrollTo({ top, left: 0, behavior: "instant" });
                    }
                });
            });
        }

        function render() {
            const colCount = columns();
            const rowHeight = cardHeight();
            const rootWidth = Math.max(240, root.clientWidth || parentElement.clientWidth || 390);
            const cardWidth = Math.floor((rootWidth - gap * (colCount - 1)) / colCount);
            const layout = layoutFor(colCount, rowHeight);
            const rows = layout.rows;
            const totalHeight = layout.totalHeight;
            const footerHeight = 82;
            stage.style.height = totalHeight + "px";
            parentElement.style.height = (totalHeight + footerHeight) + "px";
            parentElement.style.minHeight = (totalHeight + footerHeight) + "px";
            updateFooter();

            const startY = visibleTop();
            const endY = startY + viewportHeight();
            const overscan = overscanRows();
            const start = Math.max(0, lowerBound(rows, startY - overscan.before * rowHeight));
            const end = Math.min(rows.length, lowerBound(rows, endY + overscan.after * rowHeight) + 1);
            const rangeKey = start + ":" + end + ":" + colCount + ":" + cardWidth + ":" + totalHeight + ":" + pendingSignature();
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
                        applyCardVisual(card, String(card.dataset.cardKey || ""));
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
            runScrollTopAfterLayout();
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

    _vinted_drop_grid_component = components_v2.component(
        "pokestock_vinted_drop_virtual_grid",
        html=(
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap">'
            '<div class="ps-sale-lot-root" style="font-family:&quot;Plus Jakarta Sans&quot;, sans-serif;">'
            '<div class="ps-sale-lot-stage" style="font-family:&quot;Plus Jakarta Sans&quot;, sans-serif;"></div>'
            '<div class="ps-sale-selection-footer" style="font-family:&quot;Plus Jakarta Sans&quot;, sans-serif;"></div>'
            '</div>'
        ),
        css=css,
        js=js,
        isolate_styles=False,
    )
    return _vinted_drop_grid_component


def grouped_payload_signature(groups, added_keys=None, duplicate_counts=None):
    compact = []
    for group in groups or []:
        compact.append(
            (
                group.get("lot_uid"),
                group.get("lot_idx"),
                [
                    (
                        item.get("card_key"),
                        item.get("card_uid"),
                        item.get("card_idx"),
                        item.get("stock"),
                        item.get("price"),
                        item.get("duplicate_fingerprint"),
                    )
                    for item in group.get("cards", []) or []
                ],
            )
        )
    compact.append(("duplicates", sorted((duplicate_counts or {}).items())))
    raw = json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _estimated_grid_height(groups, *, mobile=False):
    cols = 2 if mobile else 6
    card_height = 410 if mobile else 470
    gap = 10
    header_height = 42
    lot_gap = 14
    total = 0
    for group in groups or []:
        card_count = len(group.get("cards", []) or [])
        if not card_count:
            continue
        total += header_height
        total += max(1, math.ceil(card_count / cols)) * (card_height + gap)
        total += lot_gap
    return max(1, total + 82)


def render_vinted_drop_virtual_grid(
    groups,
    added_keys,
    *,
    duplicate_counts=None,
    key="vinted_drop",
    mobile=False,
    scroll_top_token=0,
    committed_selection_token=0,
):
    component = _get_vinted_drop_grid_component()
    if component is None:
        return None

    def _noop():
        return None

    result = component(
        key=f"vinted_drop_virtual_grid_{key}",
        data={
            "key": key,
            "signature": grouped_payload_signature(groups, added_keys, duplicate_counts),
            "groups": list(groups or []),
            "addedKeys": list(added_keys or []),
            "duplicateCounts": dict(duplicate_counts or {}),
            "committedSelectionToken": str(committed_selection_token or ""),
            "scrollTopToken": str(scroll_top_token or ""),
        },
        default={},
        width="stretch",
        height=_estimated_grid_height(groups, mobile=mobile),
        on_batch_change=_noop,
    )
    return result

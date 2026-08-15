"""Frontend-virtualized sale results grid."""

from __future__ import annotations

import hashlib
import json
import math

import streamlit as st

try:
    import streamlit.components.v2 as components_v2
except Exception:  # pragma: no cover - runtime capability
    components_v2 = None


_sale_grid_component = None


def _get_sale_grid_component():
    global _sale_grid_component
    if components_v2 is None:
        return None
    if _sale_grid_component is not None:
        return _sale_grid_component

    css = """
    :host {
        display: block;
        width: 100%;
    }
    .ps-sale-grid-root {
        position: relative;
        width: 100%;
        min-height: 1px;
        overflow: visible;
        font-family: "Plus Jakarta Sans", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .ps-sale-stage {
        position: relative;
        width: 100%;
        min-height: 1px;
    }
    .ps-sale-card {
        position: absolute;
        box-sizing: border-box;
        border: 1px solid rgba(148, 163, 184, 0.35);
        border-radius: 12px;
        background: #ffffff;
        box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
        padding: 10px;
        overflow: hidden;
        contain: layout paint;
    }
    .ps-sale-card.in-cart {
        border-color: rgba(34, 197, 94, 0.75);
        box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.15);
    }
    .ps-sale-img-wrap {
        position: relative;
        width: 100%;
        aspect-ratio: 0.72;
        border-radius: 10px;
        background: #f8fafc;
        border: 1px dashed #cbd5e1;
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
    .ps-sale-ok {
        position: absolute;
        top: 5px;
        right: 5px;
        border-radius: 999px;
        background: #22c55e;
        color: #fff;
        font-size: 0.68rem;
        font-weight: 900;
        padding: 3px 6px;
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
    .ps-sale-lot {
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
        font-size: 0.76rem;
        font-weight: 700;
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
    }
    .ps-sale-card.in-cart .ps-sale-add {
        background: #22c55e;
    }
    @media (max-width: 768px) {
        .ps-sale-card {
            padding: 8px;
            border-radius: 10px;
        }
        .ps-sale-name {
            font-size: 0.78rem;
            min-height: 36px;
        }
        .ps-sale-meta,
        .ps-sale-lot,
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
    }
    """

    js = r"""
    export default function(component) {
        const { data, parentElement, setTriggerValue } = component;
        parentElement.style.width = "100%";
        parentElement.style.overflow = "visible";

        const doc = parentElement.ownerDocument;
        const win = doc.defaultView || window;
        const root = parentElement.querySelector(".ps-sale-grid-root");
        const stage = root.querySelector(".ps-sale-stage");
        const key = data.key || "sale";
        const stateKey = "__pokestockSaleGrid_" + key;
        const items = Array.isArray(data.items) ? data.items : [];
        const cart = new Set(Array.isArray(data.cartUids) ? data.cartUids : []);
        const signature = String(data.signature || "");
        const gap = 10;
        const qtyState = win[stateKey] || { signature: signature, qty: {}, mounted: new Map(), lastRange: "" };
        if (qtyState.mounted && qtyState.mounted.size) {
            const staleMountedNodes = Array.from(qtyState.mounted.values()).some((node) => !stage.contains(node));
            if (staleMountedNodes) {
                qtyState.mounted = new Map();
                qtyState.lastRange = "";
            }
        }
        let scrollTarget = null;
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
        scrollTarget = findScrollTarget(parentElement);
        if (qtyState.signature !== signature) {
            qtyState.signature = signature;
            qtyState.qty = {};
            qtyState.mounted = new Map();
            qtyState.lastRange = "";
            try {
                if (scrollTarget === win) {
                    win.scrollTo({ top: root.getBoundingClientRect().top + win.scrollY - 8, behavior: "instant" });
                } else {
                    const targetRect = scrollTarget.getBoundingClientRect();
                    scrollTarget.scrollTo({ top: scrollTarget.scrollTop + root.getBoundingClientRect().top - targetRect.top - 8, behavior: "instant" });
                }
            } catch (e) {}
        }
        win[stateKey] = qtyState;

        function columns() {
            return win.matchMedia("(max-width: 768px)").matches ? 2 : 6;
        }

        function cardHeight() {
            return win.matchMedia("(max-width: 768px)").matches ? 366 : 420;
        }

        function overscanRows() {
            return win.matchMedia("(max-width: 768px)").matches ? { before: 5, after: 10 } : { before: 3, after: 6 };
        }

        function itemKey(item) {
            return String(item.card_uid || item.card_key || item.lot_uid + "_" + item.card_idx);
        }

        function clampQty(key, maxQty) {
            const current = Number(qtyState.qty[key] || 1);
            return Math.max(1, Math.min(Math.max(1, Number(maxQty || 1)), current || 1));
        }

        function setText(parent, cls, value) {
            const el = doc.createElement("div");
            el.className = cls;
            el.textContent = value || "";
            parent.appendChild(el);
            return el;
        }

        function makeCard(item, index, width, height, colCount) {
            const key = itemKey(item);
            const card = doc.createElement("div");
            card.className = "ps-sale-card" + (cart.has(key) ? " in-cart" : "");
            card.dataset.cardKey = key;
            card.dataset.index = String(index);
            card.style.width = width + "px";
            card.style.height = height + "px";

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
            if (cart.has(key)) {
                const ok = doc.createElement("span");
                ok.className = "ps-sale-ok";
                ok.textContent = "OK";
                imageWrap.appendChild(ok);
            }
            card.appendChild(imageWrap);
            setText(card, "ps-sale-name", item.name || "Carte");
            setText(card, "ps-sale-meta", (item.set || "") + (item.number ? " · #" + item.number : ""));
            setText(card, "ps-sale-lot", item.lot_name || "");
            setText(card, "ps-sale-price", (item.price_label || "") + " · Stock " + String(item.stock || 0));

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
                qtyState.qty[key] = next;
                qty.textContent = String(next);
            };
            plus.onclick = (event) => {
                event.preventDefault();
                const next = Math.min(Number(item.stock || 1), clampQty(key, item.stock) + 1);
                qtyState.qty[key] = next;
                qty.textContent = String(next);
            };
            stepper.appendChild(minus);
            stepper.appendChild(qty);
            stepper.appendChild(plus);
            actions.appendChild(stepper);

            const add = doc.createElement("button");
            add.type = "button";
            add.className = "ps-sale-add";
            add.textContent = cart.has(key) ? "Dans panier" : "Ajouter";
            add.onclick = (event) => {
                event.preventDefault();
                setTriggerValue("add", {
                    id: "add-" + key + "-" + Date.now() + "-" + Math.random().toString(36).slice(2),
                    type: "add",
                    card_uid: item.card_uid,
                    lot_uid: item.lot_uid,
                    lot_idx: item.lot_idx,
                    card_idx: item.card_idx,
                    quantity: clampQty(key, item.stock)
                });
            };
            actions.appendChild(add);
            card.appendChild(actions);
            return card;
        }

        function preload(start, end) {
            for (let i = Math.max(0, start); i < Math.min(items.length, end); i++) {
                const url = items[i] && items[i].image_url;
                if (!url) continue;
                try {
                    const img = new Image();
                    img.decoding = "async";
                    img.loading = "eager";
                    img.src = url;
                } catch (e) {}
            }
        }

        function viewportHeight() {
            return scrollTarget === win ? (win.innerHeight || doc.documentElement.clientHeight || 800) : scrollTarget.clientHeight;
        }

        function render() {
            const colCount = columns();
            const height = cardHeight();
            const rowPitch = height + gap;
            const rootWidth = Math.max(240, root.clientWidth || parentElement.clientWidth || 390);
            const cardWidth = Math.floor((rootWidth - gap * (colCount - 1)) / colCount);
            const totalRows = Math.ceil(items.length / colCount);
            const totalHeight = Math.max(1, totalRows * rowPitch);
            stage.style.height = totalHeight + "px";
            parentElement.style.height = totalHeight + "px";
            parentElement.style.minHeight = totalHeight + "px";

            const rect = root.getBoundingClientRect();
            const targetRect = scrollTarget === win ? { top: 0 } : scrollTarget.getBoundingClientRect();
            const visibleStart = Math.max(0, targetRect.top - rect.top);
            const visibleEnd = visibleStart + viewportHeight();
            const overscan = overscanRows();
            const startRow = Math.max(0, Math.floor((visibleStart - overscan.before * rowPitch) / rowPitch));
            const endRow = Math.min(totalRows - 1, Math.ceil((visibleEnd + overscan.after * rowPitch) / rowPitch));
            const start = Math.max(0, startRow * colCount);
            const end = Math.min(items.length, (endRow + 1) * colCount);
            const rangeKey = start + ":" + end + ":" + colCount + ":" + cardWidth;

            if (rangeKey === qtyState.lastRange && stage.querySelector(".ps-sale-card")) {
                preload(end, end + colCount * overscan.after);
                return;
            }
            qtyState.lastRange = rangeKey;

            const keep = new Set();
            for (let index = start; index < end; index++) {
                const item = items[index];
                if (!item) continue;
                const key = itemKey(item);
                keep.add(key);
                let card = qtyState.mounted.get(key);
                if (!card) {
                    card = makeCard(item, index, cardWidth, height, colCount);
                    qtyState.mounted.set(key, card);
                    stage.appendChild(card);
                }
                const row = Math.floor(index / colCount);
                const col = index % colCount;
                card.style.transform = "translate3d(" + (col * (cardWidth + gap)) + "px," + (row * rowPitch) + "px,0)";
                card.style.width = cardWidth + "px";
                card.style.height = height + "px";
            }

            for (const [key, card] of Array.from(qtyState.mounted.entries())) {
                if (!keep.has(key)) {
                    card.remove();
                    qtyState.mounted.delete(key);
                }
            }
            preload(end, end + colCount * overscan.after);
        }

        let raf = 0;
        function schedule() {
            if (raf) return;
            raf = win.requestAnimationFrame(() => {
                raf = 0;
                render();
            });
        }

        scrollTarget.addEventListener("scroll", schedule, { passive: true });
        win.addEventListener("resize", schedule, { passive: true });
        schedule();

        return () => {
            scrollTarget.removeEventListener("scroll", schedule);
            win.removeEventListener("resize", schedule);
        };
    }
    """

    _sale_grid_component = components_v2.component(
        "pokestock_sale_virtual_grid",
        html='<div class="ps-sale-grid-root"><div class="ps-sale-stage"></div></div>',
        css=css,
        js=js,
        isolate_styles=False,
    )
    return _sale_grid_component


def component_v2_available():
    return components_v2 is not None


def payload_signature(items):
    compact = [
        (item.get("lot_uid"), item.get("card_uid"), item.get("stock"), item.get("price"))
        for item in items
    ]
    raw = json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _estimated_grid_height(item_count, *, mobile=False):
    cols = 2 if mobile else 6
    card_height = 366 if mobile else 420
    gap = 10
    rows = max(1, math.ceil(max(0, int(item_count or 0)) / cols))
    return max(1, rows * (card_height + gap))


def render_sale_virtual_grid(items, cart_uids, *, key="sales", height=None, mobile=False):
    component = _get_sale_grid_component()
    if component is None:
        return None

    def _noop():
        return None

    result = component(
        key=f"sale_virtual_grid_{key}",
        data={
            "key": key,
            "signature": payload_signature(items),
            "items": items,
            "cartUids": list(cart_uids or []),
        },
        default={},
        width="stretch",
        height=height or _estimated_grid_height(len(items or []), mobile=mobile),
        on_add_change=_noop,
    )
    return result

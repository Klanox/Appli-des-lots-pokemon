import hashlib
import json

import streamlit as st
import streamlit.components.v1 as components

try:
    import streamlit.components.v2 as components_v2
except Exception:  # pragma: no cover - depends on Streamlit runtime version
    components_v2 = None


def stable_list_signature(*parts) -> str:
    try:
        raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        raw = repr(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def progressive_slice(
    key_prefix: str,
    items,
    signature: str,
    *,
    initial_count: int,
):
    items = list(items or [])
    signature_key = f"{key_prefix}_signature"
    count_key = f"{key_prefix}_visible_count"
    if st.session_state.get(signature_key) != signature:
        st.session_state[signature_key] = signature
        st.session_state[count_key] = min(int(initial_count), len(items))
    visible_count = min(int(st.session_state.get(count_key, initial_count) or initial_count), len(items))
    st.session_state[count_key] = visible_count
    return items[:visible_count], visible_count, len(items), count_key


def virtual_window_slice(
    key_prefix: str,
    items,
    signature: str,
    *,
    initial_count: int,
    window_count: int,
    step_count: int,
    event=None,
    row_height_default: int = 540,
    slots_per_row: int = 1,
):
    items = list(items or [])
    total_count = len(items)
    signature_key = f"{key_prefix}_virtual_signature"
    start_key = f"{key_prefix}_window_start"
    end_key = f"{key_prefix}_window_end"
    event_key = f"{key_prefix}_virtual_last_event"
    row_height_key = f"{key_prefix}_virtual_row_height"

    if st.session_state.get(signature_key) != signature:
        st.session_state[signature_key] = signature
        st.session_state[start_key] = 0
        st.session_state[end_key] = min(int(initial_count), total_count)
        st.session_state.pop(event_key, None)
        st.session_state[row_height_key] = int(row_height_default)

    row_height = int(st.session_state.get(row_height_key, row_height_default) or row_height_default)
    if isinstance(event, dict):
        event_id = str(event.get("id") or "")
        if event_id and st.session_state.get(event_key) != event_id:
            st.session_state[event_key] = event_id
            try:
                measured_row_height = int(float(event.get("rowHeight") or 0))
            except Exception:
                measured_row_height = 0
            if measured_row_height > 80:
                row_height = measured_row_height
                st.session_state[row_height_key] = row_height
            direction = str(event.get("direction") or "")
            start = int(st.session_state.get(start_key, 0) or 0)
            end = int(st.session_state.get(end_key, initial_count) or initial_count)
            window_count = max(int(window_count), int(initial_count))
            step_count = max(1, int(step_count))
            slots_per_row = max(1, int(slots_per_row or 1))
            try:
                scroll_top = max(0, int(float(event.get("scrollTop") or 0)))
            except Exception:
                scroll_top = 0
            if scroll_top > 0:
                lead_rows = max(4, int(window_count / slots_per_row / 3))
                viewport_row = max(0, int(max(0, scroll_top + (row_height * lead_rows)) / max(1, row_height)))
                back_rows = 3
                desired_start = max(0, (viewport_row - back_rows) * slots_per_row)
                desired_start = min(max(0, total_count - window_count), desired_start)
                start = desired_start
                end = min(total_count, start + window_count)
            elif direction == "down":
                if end - start < window_count:
                    end = min(total_count, end + step_count)
                else:
                    start = min(max(0, total_count - window_count), start + step_count)
                    end = min(total_count, start + window_count)
            elif direction == "up":
                start = max(0, start - step_count)
                end = min(total_count, start + window_count)

            st.session_state[start_key] = start
            st.session_state[end_key] = end

    start = max(0, min(int(st.session_state.get(start_key, 0) or 0), total_count))
    end = max(start, min(int(st.session_state.get(end_key, initial_count) or initial_count), total_count))
    if end <= start and total_count:
        end = min(total_count, start + int(initial_count))
    return items[start:end], start, end, total_count, row_height


_virtual_scroll_component = None


def _get_virtual_scroll_component():
    global _virtual_scroll_component
    if components_v2 is None:
        return None
    if _virtual_scroll_component is not None:
        return _virtual_scroll_component

    js = r"""
    export default function(component) {
        const { data, setTriggerValue, parentElement } = component;
        parentElement.style.height = "0px";
        parentElement.style.minHeight = "0px";
        parentElement.style.overflow = "hidden";
        parentElement.style.pointerEvents = "none";

        const doc = parentElement.ownerDocument;
        const win = doc.defaultView || window;
        const key = data.key || "virtual";
        const observerKey = "__pokestockVirtualScroll_" + key;
        const scrollKey = "__pokestockVirtualScrollScrolled_" + key;
        const throttleKey = "__pokestockVirtualScrollLast_" + key;
        const listenerKey = "__pokestockVirtualScrollListener_" + key;
        const root = doc.querySelector('[data-testid="stMain"]') || null;
        const scrollTarget = root || win;

        function preload(urls) {
            (urls || []).slice(0, 32).forEach((url) => {
                if (!url || typeof url !== "string") return;
                try {
                    const img = new Image();
                    img.decoding = "async";
                    img.loading = "eager";
                    img.src = url;
                } catch (e) {}
            });
        }

        function rowHeight() {
            const rows = Array.from(doc.querySelectorAll(data.rowSelector || ""));
            if (!rows.length) return data.defaultRowHeight || 540;
            const tops = rows
                .map((row) => row.getBoundingClientRect().top)
                .filter((value) => Number.isFinite(value))
                .sort((a, b) => a - b);
            const deltas = [];
            for (let i = 1; i < tops.length; i++) {
                const d = tops[i] - tops[i - 1];
                if (d > 80) deltas.push(d);
            }
            if (deltas.length) {
                deltas.sort((a, b) => a - b);
                return Math.round(deltas[Math.floor(deltas.length / 2)]);
            }
            const rect = rows[0].getBoundingClientRect();
            return Math.max(260, Math.round(rect.height + 16));
        }

        function scrolledEnough() {
            if (win[scrollKey]) return true;
            const current = root ? root.scrollTop : win.scrollY;
            if (current > 24) {
                win[scrollKey] = true;
                return true;
            }
            return false;
        }

        function trigger(direction) {
            if (!scrolledEnough()) return;
            const now = Date.now();
            if (now - (win[throttleKey] || 0) < 450) return;
            win[throttleKey] = now;
            component.setStateValue("scroll_request", {
                id: direction + "-" + now + "-" + Math.random().toString(36).slice(2),
                direction,
                rowHeight: rowHeight(),
                scrollTop: root ? root.scrollTop : win.scrollY
            });
        }

        function rootRect() {
            return root ? root.getBoundingClientRect() : { top: 0, bottom: win.innerHeight };
        }

        function checkNearAnchors() {
            if (!scrolledEnough()) return;
            const top = doc.getElementById(data.topAnchorId);
            const bottom = doc.getElementById(data.bottomAnchorId);
            const rr = rootRect();
            const rootMargin = Number(data.rootMargin || 1800);
            const topMargin = Number(data.topMargin || 700);
            if (bottom) {
                const br = bottom.getBoundingClientRect();
                if (br.top <= rr.bottom + rootMargin) {
                    trigger("down");
                    return;
                }
            }
            if (top) {
                const tr = top.getBoundingClientRect();
                if (tr.top <= rr.bottom + topMargin && tr.bottom >= rr.top - topMargin) {
                    trigger("up");
                }
            }
        }

        function connect() {
            const top = doc.getElementById(data.topAnchorId);
            const bottom = doc.getElementById(data.bottomAnchorId);
            if (!top && !bottom) return false;
            if (win[observerKey]) {
                try { win[observerKey].forEach((obs) => obs.disconnect()); } catch (e) {}
            }
            const observers = [];
            const rootMargin = String(data.rootMargin || 1800) + "px 0px";
            const topMargin = String(data.topMargin || 700) + "px 0px";
            if (bottom) {
                const bottomObserver = new IntersectionObserver((entries) => {
                    if (entries.some((entry) => entry.isIntersecting)) trigger("down");
                }, { root, rootMargin, threshold: 0 });
                bottomObserver.observe(bottom);
                observers.push(bottomObserver);
            }
            if (top) {
                const topObserver = new IntersectionObserver((entries) => {
                    if (entries.some((entry) => entry.isIntersecting)) trigger("up");
                }, { root, rootMargin: topMargin, threshold: 0 });
                topObserver.observe(top);
                observers.push(topObserver);
            }
            win[observerKey] = observers;
            return true;
        }

        if (win[listenerKey]) {
            try { scrollTarget.removeEventListener("scroll", win[listenerKey]); } catch (e) {}
        }
        win[listenerKey] = () => {
            win[scrollKey] = true;
            checkNearAnchors();
        };
        scrollTarget.addEventListener("scroll", win[listenerKey], { passive: true });

        if (!win[scrollKey]) {
            scrollTarget.addEventListener("scroll", () => { win[scrollKey] = true; }, { once: true, passive: true });
        }
        preload(data.preloadUrls || []);
        if (!connect()) {
            setTimeout(connect, 80);
            setTimeout(connect, 240);
            setTimeout(connect, 600);
        }
        setTimeout(checkNearAnchors, 120);

        return () => {
            if (win[observerKey]) {
                try { win[observerKey].forEach((obs) => obs.disconnect()); } catch (e) {}
            }
            if (win[listenerKey]) {
                try { scrollTarget.removeEventListener("scroll", win[listenerKey]); } catch (e) {}
            }
        };
    }
    """
    _virtual_scroll_component = components_v2.component(
        "pokestock_virtual_scroll_sensor",
        html='<div aria-hidden="true" style="height:0;width:0;overflow:hidden"></div>',
        css=":host{display:block;height:0;min-height:0;overflow:hidden;pointer-events:none}",
        js=js,
        isolate_styles=False,
    )
    return _virtual_scroll_component


def render_virtual_scroll_sensor(
    key_prefix: str,
    *,
    top_anchor_id: str,
    bottom_anchor_id: str,
    row_selector: str,
    root_margin_px: int = 1800,
    top_margin_px: int = 700,
    preload_urls=None,
    default_row_height: int = 540,
):
    component = _get_virtual_scroll_component()
    if component is None:
        return None
    safe_key = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in key_prefix)

    def _request_fragment_rerun():
        try:
            st.rerun(scope="fragment")
        except Exception:
            st.rerun()

    result = component(
        key=f"virtual_scroll_sensor_{safe_key}",
        data={
            "key": safe_key,
            "topAnchorId": top_anchor_id,
            "bottomAnchorId": bottom_anchor_id,
            "rowSelector": row_selector,
            "rootMargin": int(root_margin_px),
            "topMargin": int(top_margin_px),
            "preloadUrls": list(preload_urls or [])[:32],
            "defaultRowHeight": int(default_row_height),
        },
        default={"scroll_request": None},
        width="stretch",
        height=0,
        on_scroll_request_change=_request_fragment_rerun,
    )
    return getattr(result, "scroll_request", None)


AUTOLOAD_BUILD = "2026-10-13-r3"

_AUTOLOAD_SCRIPT = r"""
<script>
(function() {
    const TAG = "[PokéStock] chargement auto";
    const BUILD = "__BUILD__";
    const KEY = "__KEY__";
    const ANCHOR_ID = "__ANCHOR_ID__";
    const CONTROL_SEL = ".st-key-__CONTROL_KEY__";
    const BATCH = "__ANCHOR_ID__:__VISIBLE__";
    const MARGIN = __MARGIN__;
    const win = parent.window;
    const doc = parent.document;
    const instKey = "__pokestockAutoloadInst_" + KEY;
    const scrolledKey = "__pokestockAutoloadScrolled_" + KEY;
    const observerKey = "__pokestockAutoload_" + KEY;
    const listenerKey = "__pokestockAutoloadListeners_" + KEY;
    const token = {};
    win[instKey] = token;
    function alive() { return win[instKey] === token; }
    function log(msg, extra) {
        try {
            if (extra === undefined) console.log(TAG + " [" + KEY + "] " + msg);
            else console.log(TAG + " [" + KEY + "] " + msg, extra);
        } catch (e) {}
    }

    let anchor = null;
    let observer = null;
    let requested = false;
    let failed = false;
    let retryPending = false;
    let tries = 0;
    let missing = 0;
    let lastRun = 0;
    const startedAt = Date.now();
    const root = doc.querySelector('[data-testid="stMain"]') || null;
    const scrollTarget = root || win;

    function control() { return doc.querySelector(CONTROL_SEL); }
    function showFallback(reason) {
        if (failed) return;
        failed = true;
        const c = control();
        if (c) c.setAttribute("data-autoload-fallback", "1");
        log("ÉCHEC confirmé, bouton manuel affiché : " + reason, {build: BUILD, lot: BATCH});
    }
    function scrolledNow() {
        if (win[scrolledKey]) return true;
        const top = Math.max(root ? root.scrollTop : 0, win.scrollY || 0, doc.scrollingElement ? doc.scrollingElement.scrollTop : 0);
        if (top > 24) { win[scrolledKey] = true; return true; }
        return false;
    }
    function notScrollable() {
        // Page trop courte pour defiler (grand ecran, peu de cartes) : sans cela, aucun defilement ne pourrait jamais declencher la suite.
        if (Date.now() - startedAt < 1500) return false;
        if (root) return root.scrollHeight - root.clientHeight <= 24;
        return doc.documentElement.scrollHeight - win.innerHeight <= 24;
    }
    function isNear() {
        if (!anchor) return false;
        const rect = anchor.getBoundingClientRect();
        const rr = root ? root.getBoundingClientRect() : { top: 0, bottom: win.innerHeight };
        return rect.top <= rr.bottom + MARGIN && rect.bottom >= rr.top - MARGIN;
    }
    function verify() {
        if (!alive()) { log("lot suivant affiché, vérification terminée"); return; }
        if (!doc.getElementById(ANCHOR_ID)) { log("fin de liste (ancre retirée), vérification terminée"); return; }
        showFallback("aucun nouveau rendu 15 s après le clic");
    }
    function requestNextBatch(reason) {
        if (!alive() || requested) return;
        if (anchor && anchor.dataset.requested === BATCH) { requested = true; return; }
        const c = control();
        const btn = c ? c.querySelector("button") : null;
        if (btn && !btn.disabled) {
            requested = true;
            if (anchor) anchor.dataset.requested = BATCH;
            try { if (observer) observer.disconnect(); } catch (e) {}
            log("clic sur le bouton caché (" + reason + ")", {lot: BATCH, scrollTop: root ? Math.round(root.scrollTop) : null, restantes: __REMAIN__});
            btn.click();
            setTimeout(verify, 15000);
        } else if (!retryPending) {
            // Le bouton cache n'est pas encore dans la page (rendu en cours) : on reessaie brievement au lieu de renoncer.
            tries += 1;
            if (tries > 40) {
                showFallback("bouton caché introuvable après 40 essais (6 s)");
                return;
            }
            if (tries === 1) log("bouton caché pas encore présent, nouvel essai (" + reason + ")");
            retryPending = true;
            setTimeout(function() { retryPending = false; maybeRequest("essai " + tries); }, 150);
        }
    }
    function maybeRequest(reason) {
        if (!alive() || requested || failed) return;
        if (!(scrolledNow() || notScrollable())) return;
        if (!isNear()) return;
        requestNextBatch(reason);
    }
    function watchAnchor() {
        if (!("IntersectionObserver" in win)) return;
        try { if (observer) observer.disconnect(); } catch (e) {}
        observer = new win.IntersectionObserver(function(entries) {
            if (!entries.some(function(entry) { return entry.isIntersecting; })) return;
            maybeRequest("observateur");
        }, { root: root, rootMargin: MARGIN + "px 0px", threshold: 0 });
        observer.observe(anchor);
        win[observerKey] = observer;
    }

    // Ecouteurs scroll + resize (un seul jeu par liste : on retire celui du lot precedent).
    const previous = win[listenerKey];
    if (previous) {
        try { previous.target.removeEventListener("scroll", previous.onScroll); } catch (e) {}
        try { win.removeEventListener("resize", previous.onResize); } catch (e) {}
    }
    function onScroll() {
        win[scrolledKey] = true;
        const now = Date.now();
        if (now - lastRun < 100) return;
        lastRun = now;
        maybeRequest("défilement");
    }
    function onResize() { maybeRequest("redimensionnement"); }
    scrollTarget.addEventListener("scroll", onScroll, { passive: true });
    win.addEventListener("resize", onResize, { passive: true });
    win[listenerKey] = { target: scrollTarget, onScroll: onScroll, onResize: onResize };

    function boot(attempt) {
        if (!alive()) return;
        anchor = doc.getElementById(ANCHOR_ID);
        if (!anchor) {
            if (attempt < 30) { setTimeout(function() { boot(attempt + 1); }, 100); return; }
            showFallback("ancre introuvable dans la page");
            return;
        }
        anchor.dataset.build = BUILD;
        log("armé", {build: BUILD, lot: BATCH, restantes: __REMAIN__, marge: MARGIN, observateur: ("IntersectionObserver" in win), zoneDefilante: root ? "stMain" : "fenêtre"});
        watchAnchor();
        maybeRequest("initial");
        // Sonde de securite : couvre les cas ou ni l'observateur ni le defilement ne remontent rien (noeud remplace, conteneur different...).
        const probe = setInterval(function() {
            if (!alive() || requested || failed) { clearInterval(probe); return; }
            const current = doc.getElementById(ANCHOR_ID);
            if (!current) {
                missing += 1;
                if (missing >= 4) clearInterval(probe);
                return;
            }
            missing = 0;
            if (current !== anchor) { anchor = current; watchAnchor(); }
            maybeRequest("sonde");
        }, 700);
    }
    boot(0);
})();
</script>
"""


def render_infinite_sentinel(
    key_prefix: str,
    *,
    count_key: str,
    visible_count: int,
    total_count: int,
    batch_size: int,
    root_margin_px: int = 1800,
    run_html_func=None,
    button_label: str = "Afficher plus",
    rerun_scope: str | None = None,
    advance_in_callback: bool = False,
    stable_key: str | None = None,
):
    if visible_count >= total_count:
        return

    safe_key = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in key_prefix)
    stable_safe_key = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in (stable_key or key_prefix))
    control_key = f"autoload_control_{safe_key}"
    button_key = f"autoload_button_{safe_key}"
    anchor_id = f"autoload-anchor-{safe_key}"

    st.markdown(
        f"""
        <style>
        .st-key-{control_key},
        .st-key-{control_key} > div,
        .st-key-{control_key} [data-testid="stVerticalBlock"],
        .st-key-{control_key} [data-testid="stElementContainer"],
        .st-key-{control_key} [data-testid="stButton"],
        .st-key-{control_key} button {{
            position: absolute !important;
            width: 1px !important;
            height: 1px !important;
            min-height: 0 !important;
            max-height: 1px !important;
            overflow: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
            margin: 0 !important;
            padding: 0 !important;
            line-height: 0 !important;
        }}
        .st-key-{control_key} {{
            display: block !important;
            height: 0 !important;
            min-height: 0 !important;
            max-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }}
        /* Secours : le script d'auto-chargement a constate qu'il ne fonctionnait pas, le bouton redevient visible et utilisable. */
        .st-key-{control_key}[data-autoload-fallback="1"],
        .st-key-{control_key}[data-autoload-fallback="1"] > div,
        .st-key-{control_key}[data-autoload-fallback="1"] [data-testid="stVerticalBlock"],
        .st-key-{control_key}[data-autoload-fallback="1"] [data-testid="stElementContainer"],
        .st-key-{control_key}[data-autoload-fallback="1"] [data-testid="stButton"],
        .st-key-{control_key}[data-autoload-fallback="1"] button {{
            position: static !important;
            width: auto !important;
            height: auto !important;
            min-height: 0 !important;
            max-height: none !important;
            overflow: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            line-height: normal !important;
        }}
        .st-key-{control_key}[data-autoload-fallback="1"] {{
            margin: 0.5rem 0 !important;
        }}
        .st-key-{control_key}[data-autoload-fallback="1"]::after {{
            content: "Chargement automatique indisponible : utilisez ce bouton.";
            display: block;
            font-size: 0.75rem;
            opacity: 0.65;
            text-align: center;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key=control_key):
        if advance_in_callback:
            # Variante sans rerun supplementaire : le compteur est avance AVANT le rerun provoque par le clic (callback),
            # donc le rendu courant n'est pas execute deux fois (utile quand chaque element affiche coute cher).
            def _advance_count():
                current = int(st.session_state.get(count_key, visible_count) or visible_count)
                st.session_state[count_key] = min(int(total_count), max(current, int(visible_count)) + int(batch_size))

            st.button(str(button_label or "​"), key=button_key, on_click=_advance_count)
        elif st.button(str(button_label or "​"), key=button_key):
            st.session_state[count_key] = min(total_count, visible_count + int(batch_size))
            if rerun_scope == "fragment":
                try:
                    st.rerun(scope="fragment")
                except Exception:
                    st.rerun()
            else:
                st.rerun()

    st.markdown(f'<div id="{anchor_id}" style="height:1px;"></div>', unsafe_allow_html=True)
    script = (
        _AUTOLOAD_SCRIPT
        .replace("__BUILD__", AUTOLOAD_BUILD)
        .replace("__KEY__", stable_safe_key)
        .replace("__ANCHOR_ID__", anchor_id)
        .replace("__CONTROL_KEY__", control_key)
        .replace("__VISIBLE__", str(int(visible_count)))
        .replace("__REMAIN__", str(max(0, int(total_count) - int(visible_count))))
        .replace("__MARGIN__", str(int(root_margin_px)))
    )
    if callable(run_html_func):
        run_html_func(script, height=0)
    else:
        components.html(script, height=0)

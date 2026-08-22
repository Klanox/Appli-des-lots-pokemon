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
            try:
                section_top = max(0, int(float(event.get("sectionTop") or 0)))
            except Exception:
                section_top = 0
            relative_scroll_top = max(0, scroll_top - section_top)

            if scroll_top > 0:
                lead_rows = max(4, int(window_count / slots_per_row / 3))
                viewport_row = max(0, int(max(0, relative_scroll_top + (row_height * lead_rows)) / max(1, row_height)))
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
                scrollTop: root ? root.scrollTop : win.scrollY,
                sectionTop: sectionTop()
            });
        }

        function sectionTop() {
            const top = doc.getElementById(data.topAnchorId);
            if (!top) return 0;
            const current = root ? root.scrollTop : win.scrollY;
            const rr = rootRect();
            return Math.max(0, Math.round(top.getBoundingClientRect().top - rr.top + current));
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
):
    if visible_count >= total_count:
        return

    safe_key = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in key_prefix)
    control_key = f"autoload_control_{safe_key}"
    button_key = f"autoload_button_{safe_key}"
    anchor_id = f"autoload-anchor-{safe_key}"
    observer_key = f"__pokestockAutoload_{safe_key}"
    scrolled_key = f"__pokestockAutoloadScrolled_{safe_key}"

    st.markdown(
        f"""
        <style>
        .st-key-{control_key},
        .st-key-{control_key} [data-testid="stButton"],
        .st-key-{control_key} button {{
            position: absolute !important;
            width: 1px !important;
            height: 1px !important;
            overflow: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
            margin: 0 !important;
            padding: 0 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key=control_key):
        if st.button(str(button_label or "\u200b"), key=button_key):
            st.session_state[count_key] = min(total_count, visible_count + int(batch_size))
            if rerun_scope == "fragment":
                try:
                    st.rerun(scope="fragment")
                except Exception:
                    st.rerun()
            else:
                st.rerun()

    st.markdown(f'<div id="{anchor_id}" style="height:1px;"></div>', unsafe_allow_html=True)
    script = f"""
    <script>
    (function() {{
        const win = parent.window;
        const doc = parent.document;
        const anchor = doc.getElementById("{anchor_id}");
        if (!anchor || !("IntersectionObserver" in win)) return;
        const scrollRoot = doc.querySelector('[data-testid="stMain"]') || null;

        const observerKey = "{observer_key}";
        const scrolledKey = "{scrolled_key}";
        if (win[observerKey]) {{
            try {{ win[observerKey].disconnect(); }} catch (e) {{}}
        }}

        let observer = null;
        function requestNextBatch() {{
            if (!win[scrolledKey]) return;
            if (anchor.dataset.requested === "1") return;
            anchor.dataset.requested = "1";
            const root = doc.querySelector(".st-key-{control_key}");
            const btn = root ? root.querySelector("button") : null;
            if (btn && !btn.disabled) {{
                try {{ if (observer) observer.disconnect(); }} catch (e) {{}}
                btn.click();
            }}
        }}

        function requestIfNear() {{
            const rect = anchor.getBoundingClientRect();
            const rootRect = scrollRoot ? scrollRoot.getBoundingClientRect() : {{ top: 0, bottom: win.innerHeight }};
            if (rect.top <= rootRect.bottom + {int(root_margin_px)} && rect.bottom >= rootRect.top - {int(root_margin_px)}) {{
                requestNextBatch();
            }}
        }}

        if (!win[scrolledKey] && ((scrollRoot && scrollRoot.scrollTop > 24) || win.scrollY > 24)) win[scrolledKey] = true;
        const scrollTarget = scrollRoot || win;
        if (!win[scrolledKey]) {{
            scrollTarget.addEventListener("scroll", function markScrolled() {{
                win[scrolledKey] = true;
                requestIfNear();
            }}, {{ once: true, passive: true }});
        }} else {{
            requestIfNear();
        }}

        observer = new win.IntersectionObserver(function(entries) {{
            if (!entries.some(function(entry) {{ return entry.isIntersecting; }})) return;
            requestNextBatch();
        }}, {{
            root: scrollRoot,
            rootMargin: "{int(root_margin_px)}px 0px",
            threshold: 0
        }});
        observer.observe(anchor);
        win[observerKey] = observer;
    }})();
    </script>
    """
    if callable(run_html_func):
        run_html_func(script, height=0)
    else:
        components.html(script, height=0)


def virtual_scroll_available() -> bool:
    return components_v2 is not None

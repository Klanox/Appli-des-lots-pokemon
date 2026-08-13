import hashlib
import json

import streamlit as st
import streamlit.components.v1 as components


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

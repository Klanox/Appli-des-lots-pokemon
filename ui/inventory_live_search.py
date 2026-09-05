"""Keystroke search styled like the application's historical text inputs."""

import streamlit as st
import streamlit.components.v2 as components


_input = components.component(
    "pokestock_inventory_search",
    html='<div class="ps-inventory-search stTextInput"><label></label><input type="text" autocomplete="off"></div>',
    css='''
    .ps-inventory-search{font-family:"Plus Jakarta Sans",sans-serif;width:100%;box-sizing:border-box}
    .ps-inventory-search label{display:block;font-size:14px;margin-bottom:6px;color:#111827}
    .ps-inventory-search input{box-sizing:border-box;width:100%;min-width:0;height:2.65rem;
        padding:8px 12px;border:1px solid #d1d5db;border-radius:10px;background:#fff;
        color:#111827;font-family:inherit;font-size:.95rem;outline:none}
    .ps-inventory-search input:focus{border-color:#7c3aed;box-shadow:0 0 0 2px rgba(124,58,237,.15)}
    .ps-inventory-search input::placeholder{color:#64748b}
    ''',
    js='''export default function({parentElement,data,setStateValue}) {
        const input = parentElement.querySelector('input');
        const label = parentElement.querySelector('label');
        label.textContent = data.label;
        label.hidden = data.collapsed;
        label.style.display = data.collapsed ? 'none' : 'block';
        input.setAttribute('aria-label', data.label);
        input.placeholder = data.placeholder;
        if (input.ownerDocument.activeElement !== input) input.value = data.value || '';
        const changed = () => setStateValue('query', input.value);
        input.addEventListener('input', changed);
        return () => input.removeEventListener('input', changed);
    }''',
    isolate_styles=False,
)


def inventory_live_search(label, *, key, placeholder, collapsed=True):
    value = st.session_state.get(key, "") or ""
    result = _input(
        key=f"inventory_live_{key}",
        data={"label": label, "placeholder": placeholder, "collapsed": collapsed, "value": value},
        default={"query": value},
        on_query_change=lambda: None,
        width="stretch",
        height="content",
    )
    query = result.query if result.query is not None else value
    st.session_state[key] = query
    return query

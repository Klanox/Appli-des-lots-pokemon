"""Sidebar presentation helpers for Pokestock.

These functions are pure UI helpers: app.py computes the values and passes them in.
"""

import html as html_lib

from .theme import render_sidebar_brand, render_sidebar_stat

__all__ = ["render_sidebar_brand", "render_sidebar_stat", "render_sidebar_period_stat", "SIDEBAR_PERIOD_CSS"]

# Carte « année civile » : même fond sombre arrondi que les cartes st.metric de la barre latérale, en plus compact.
SIDEBAR_PERIOD_CSS = """
[data-testid="stSidebar"] .ps-side-period{background:rgba(255,255,255,0.055);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:.6rem .7rem;line-height:1.2;margin-bottom:1rem}
[data-testid="stSidebar"] .ps-side-period-label{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#f8fafc}
[data-testid="stSidebar"] .ps-side-period-year{color:#A78BFA;font-weight:700;margin-left:.3rem}
[data-testid="stSidebar"] .ps-side-period-value{font-size:1.45rem;font-weight:800;color:#f8fafc;letter-spacing:-.02em;margin-top:.15rem}
[data-testid="stSidebar"] .ps-side-period-sub{font-size:.72rem;font-weight:500;color:#A8A3C7;margin-top:.1rem}
"""


def render_sidebar_period_stat(label: str, year, value: str, lines=()) -> str:
    """Carte de la barre latérale pour un chiffre de l'année civile : libellé, année en violet clair, valeur, petites lignes."""
    sub = "".join(f'<div class="ps-side-period-sub">{html_lib.escape(str(line))}</div>' for line in lines if line)
    return (
        '<div class="ps-side-period">'
        f'<div class="ps-side-period-label">{html_lib.escape(label)}'
        f'<span class="ps-side-period-year">· {html_lib.escape(str(year))}</span></div>'
        f'<div class="ps-side-period-value">{html_lib.escape(str(value))}</div>'
        f'{sub}</div>'
    )

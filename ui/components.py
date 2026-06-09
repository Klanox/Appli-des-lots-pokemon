"""Small visual UI components for Pokestock.

These helpers are intentionally data-free: they only return HTML/CSS strings
from values already computed by app.py.
"""

from .theme import (
    KPI_ACCENTS,
    render_app_header,
    render_kpi_card,
    render_page_header,
)

__all__ = [
    "KPI_ACCENTS",
    "render_app_header",
    "render_kpi_card",
    "render_page_header",
]

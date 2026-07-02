"""Streamlit bridge for the custom MarketDashboard frontend."""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components


_COMPONENT_DIR = Path(__file__).parent
_BUILD_DIR = _COMPONENT_DIR / "frontend" / "build"

_market_dashboard = components.declare_component(
    "market_dashboard",
    path=str(_BUILD_DIR),
)


def market_dashboard(data: dict, *, key: str = "market_dashboard") -> dict:
    """Render the fullscreen market dashboard and return its latest UI event."""
    result = _market_dashboard(data=data, key=key, default={})
    return result if isinstance(result, dict) else {}


__all__ = ["market_dashboard"]

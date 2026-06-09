"""Sidebar presentation helpers for Pokestock.

These functions are pure UI helpers: app.py computes the values and passes them in.
"""

from .theme import render_sidebar_brand, render_sidebar_stat

__all__ = ["render_sidebar_brand", "render_sidebar_stat"]

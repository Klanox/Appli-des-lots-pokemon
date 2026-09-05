"""Shared Vinted channel labels and normalization helpers."""

from __future__ import annotations

import unicodedata


VINTED_CHANNELS = ("Dexify", "Pokédeal", "ChoppeTaCarte")
SALE_CHANNELS = ("Main propre", "Brocante", *VINTED_CHANNELS)


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "".join(char.lower() for char in text if char.isalnum())


_VINTED_CHANNEL_BY_KEY = {
    "dexify": "Dexify",
    "dexifytcg": "Dexify",
    "pokedeal": "Pokédeal",
    "pokdeal": "Pokédeal",  # Legacy data written with a replacement character.
    "choppetacarte": "ChoppeTaCarte",
}

_SALE_CHANNEL_KEYS = {
    "main": "main",
    "mainpropre": "main",
    "brocante": "brocante",
}


def normalize_vinted_channel(value: str) -> str:
    return _VINTED_CHANNEL_BY_KEY.get(_fold(value), str(value or "").strip())


def vinted_channel_key(value: str) -> str:
    return _fold(normalize_vinted_channel(value))


def sale_channel_key(value: str) -> str:
    """Return one stable key for current and historical sale channel labels."""
    normalized = normalize_vinted_channel(value)
    if normalized in VINTED_CHANNELS:
        return vinted_channel_key(normalized)
    return _SALE_CHANNEL_KEYS.get(_fold(value))


def is_vinted_channel(value: str) -> bool:
    return normalize_vinted_channel(value) in VINTED_CHANNELS

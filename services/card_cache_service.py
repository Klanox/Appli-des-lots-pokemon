"""Disk cache helpers for the TCGDex card index.

These functions only read/write cards_cache.json. They do not use Streamlit,
do not call external APIs, and do not touch application data files.
"""

from __future__ import annotations

import json
import os
import time

from utils import CARDS_CACHE_FILE, CARDS_CACHE_TTL_SECONDS, safe_write_json


def load_cards_cache_from_disk(allow_stale=False):
    if not os.path.exists(CARDS_CACHE_FILE):
        return None
    try:
        with open(CARDS_CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("version") != 1:
            return None
        age = time.time() - float(cached.get("created_at", 0))
        if not allow_stale and age > CARDS_CACHE_TTL_SECONDS:
            return None
        cards_index = cached.get("cards_index", {})
        if isinstance(cards_index, dict) and cards_index:
            return cards_index
    except Exception as e:
        print(f"Cache disque cartes illisible: {e}")
    return None


def save_cards_cache_to_disk(cards_index):
    safe_write_json(CARDS_CACHE_FILE, {
        "version": 1,
        "created_at": time.time(),
        "cards_index": cards_index,
    })


def search_in_cache_index(query, cards_index, num=None, limit=None, normalize_func=None):
    """Pure search in an already-loaded card index.

    No Streamlit, no disk access, no network access.
    Returns the same kind of list as app.search_in_cache: [(card, set_name), ...].
    """
    if not cards_index:
        return []

    if normalize_func is None:
        normalize_func = lambda value: str(value or "").strip().lower()

    name_norm = normalize_func(query)
    matches = []
    seen = set()

    def maybe_stop():
        return limit is not None and len(matches) >= int(limit)

    def add_match(card, set_name):
        if maybe_stop():
            return
        cid = card.get("id", "") or card.get("name", "")
        if cid not in seen:
            seen.add(cid)
            matches.append((card, set_name))

    def card_matches_num(card):
        card_num = str(card.get("localId", "") or card.get("number", ""))
        if not num:
            return True
        num_text = str(num)
        return (
            card_num == num_text
            or card_num.zfill(3) == num_text.zfill(3)
            or (num_text.isdigit() and card_num.endswith(num_text) and not card_num[:-len(num_text)].isdigit())
        )

    def iter_cache_items():
        for idx_name, cards in cards_index.items():
            yield idx_name, normalize_func(idx_name), cards

    if name_norm in cards_index:
        for card, set_name, set_id in cards_index[name_norm]:
            if card_matches_num(card):
                add_match(card, set_name)
            if maybe_stop():
                return matches

    if not matches:
        for idx_name, idx_norm, cards in iter_cache_items():
            if idx_norm == name_norm:
                for card, set_name, set_id in cards:
                    if card_matches_num(card):
                        add_match(card, set_name)
                    if maybe_stop():
                        return matches

    if num:
        for idx_name, idx_norm, cards in iter_cache_items():
            if idx_norm == name_norm:
                continue
            if idx_norm.startswith(name_norm) or name_norm in idx_norm:
                for card, set_name, set_id in cards:
                    if card_matches_num(card):
                        add_match(card, set_name)
                    if maybe_stop():
                        return matches

    if not matches:
        for idx_name, idx_norm, cards in iter_cache_items():
            if name_norm in idx_norm:
                for card, set_name, set_id in cards:
                    if card_matches_num(card):
                        add_match(card, set_name)
                    if maybe_stop():
                        return matches

    return matches

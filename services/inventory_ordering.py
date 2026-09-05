"""Pure helpers for the stock card lists used by sales and global search."""

from __future__ import annotations

from datetime import datetime
import unicodedata


CARD_ACQUISITION_FIELDS = (
    "acquired_at",
    "acquisition_date",
    "date_acquisition",
    "date_achat",
    "purchase_date",
    "added_at",
    "created_at",
    "created",
    "date",
)
LOT_ACQUISITION_FIELDS = (
    "acquired_at",
    "acquisition_date",
    "date_acquisition",
    "date_achat",
    "purchase_date",
    "created_at",
    "created",
    "date",
)


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _first_timestamp(source, fields):
    for field in fields:
        parsed = _parse_datetime((source or {}).get(field))
        if parsed is not None:
            return parsed
    return None


def card_acquisition_sort_key(card, lot, *, lot_index=0, card_index=0):
    """Sort oldest acquisitions first, with a deterministic fallback."""
    acquired_at = _first_timestamp(card, CARD_ACQUISITION_FIELDS)
    if acquired_at is None:
        acquired_at = _first_timestamp(lot, LOT_ACQUISITION_FIELDS)
    stable_id = str((card or {}).get("card_uid") or (card or {}).get("uid") or (card or {}).get("id") or "")
    return (
        acquired_at is None,
        acquired_at or datetime.max,
        int(lot_index or 0),
        int(card_index or 0),
        stable_id,
    )


def sort_inventory_records(records):
    """Return inventory records in the shared acquisition order.

    A record carries ``card``, ``lot``, ``lot_idx`` and ``card_idx``.  Keeping
    this helper data-only makes the ordering identical in both Streamlit views.
    """
    return sorted(
        list(records or []),
        key=lambda record: card_acquisition_sort_key(
            record.get("card") or {},
            record.get("lot") or {},
            lot_index=record.get("lot_idx", 0),
            card_index=record.get("card_idx", 0),
        ),
    )


def normalize_inventory_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().split())


def card_matches_inventory_query(card, query):
    """Match names, number and set without making search casing/accent sensitive."""
    needle = normalize_inventory_text(query)
    if not needle:
        return True
    haystack = " ".join(
        normalize_inventory_text((card or {}).get(field))
        for field in ("name", "number", "display_number", "set", "set_name", "language")
    )
    return needle in haystack

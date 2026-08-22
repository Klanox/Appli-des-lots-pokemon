"""Canonical identity helpers for comparing card variants."""

from __future__ import annotations

import re
import unicodedata


def _fold(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _normalize_number(value):
    text = str(value or "").strip().casefold()
    text = text.replace("／", "/").replace(" ", "")
    text = re.sub(r"^0+(\d)", r"\1", text)
    return text


def card_language_key(card):
    if not isinstance(card, dict):
        return "fr"
    raw = str(card.get("lang") or card.get("language") or "").strip().casefold()
    special = str(card.get("special") or card.get("special_tag") or "").casefold()
    if raw in {"ja", "jp", "jpn", "japanese"} or card.get("is_japanese") or "japon" in special or "japan" in special:
        return "ja"
    return raw or "fr"


def card_stamp_key(card):
    if not isinstance(card, dict):
        return ""
    raw_stamp = card.get("stamp")
    if raw_stamp:
        return "stamp" if isinstance(raw_stamp, bool) else _fold(raw_stamp)
    if card.get("is_stamp"):
        return "stamp"
    values = []
    for key in ("special_tag", "special", "variant", "rarity", "category"):
        value = card.get(key)
        if value:
            values.extend(str(part).strip() for part in str(value).split(",") if str(part).strip())
    for key in ("tags", "metadata_tags", "card_tags", "subtypes", "types"):
        value = card.get(key) or []
        if isinstance(value, (list, tuple, set)):
            values.extend(str(part).strip() for part in value if str(part).strip())
        elif value:
            values.extend(str(part).strip() for part in str(value).split(",") if str(part).strip())
    for value in values:
        folded = value.casefold()
        if folded in {"stamp", "stamped"} or " stamp" in f" {folded} " or "stamped" in folded:
            return "stamp"
    return ""


def _truthy_flag(card, *keys):
    for key in keys:
        value = card.get(key)
        if isinstance(value, bool):
            if value:
                return True
        elif str(value or "").strip().casefold() in {"1", "true", "yes", "oui", "reverse", "revers"}:
            return True
    return False


def _variant_key(card):
    ignored = {
        "collection",
        "stockage",
        "storage",
        "trade",
        "reverse",
        "revers",
        "stamp",
        "stamped",
        "japonaise",
        "japanese",
    }
    values = []
    for key in ("variant", "version", "finish", "foil", "special_tag", "special"):
        value = card.get(key)
        if value:
            values.extend(str(part).strip() for part in str(value).split(",") if str(part).strip())
    clean = []
    for value in values:
        folded = _fold(value)
        if folded and folded not in ignored:
            clean.append(folded)
    return "+".join(sorted(set(clean)))


def card_identity_fingerprint(card):
    """Return a stable key for the exact visible card variant, not its stock UID."""

    if not isinstance(card, dict):
        return ""
    set_key = _fold(card.get("set") or card.get("serie") or card.get("extension") or card.get("set_name"))
    number_key = _normalize_number(card.get("display_number") or card.get("number") or card.get("localId"))
    name_key = _fold(card.get("name"))
    language = card_language_key(card)
    reverse = "reverse" if _truthy_flag(card, "is_reverse", "reverse") else "normal"
    first = "ed1" if _truthy_flag(card, "is_ed1", "first_edition", "firstEdition") else "unlimited"
    stamp = card_stamp_key(card) or "nostamp"
    variant = _variant_key(card)
    primary = f"{set_key}|{number_key}" if set_key or number_key else name_key
    return "|".join([primary, name_key, language, reverse, first, stamp, variant])

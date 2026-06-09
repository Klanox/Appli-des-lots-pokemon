"""Pure TCGDex URL helpers.

These helpers do not call the network, do not use Streamlit, and do not read or
write files. They only transform strings.
"""

from __future__ import annotations


def tcgdex_series_from_set_id(set_id):
    set_id = str(set_id or "").lower()
    if set_id.startswith("swsh"):
        return "swsh"
    if set_id.startswith("sm"):
        return "sm"
    if set_id.startswith("xy"):
        return "xy"
    if set_id.startswith("sv"):
        return "sv"
    if set_id.startswith("bw"):
        return "bw"
    return ""


def normalized_tcgdex_image_url(url):
    url = str(url or "").strip()
    if url and "tcgdex.net" in url and not url.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return f"{url}/high.webp"
    return url

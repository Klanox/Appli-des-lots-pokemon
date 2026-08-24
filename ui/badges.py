"""Pure badge/stamp helpers for card display."""

import html


STATUS_BADGE_STYLES = {
    "Reverse": ("#f5f3ff", "#7c3aed", "#ddd6fe"),
    "1ère Éd": ("#fef2f2", "#dc2626", "#fecaca"),
    "Japonaise": ("#fff7ed", "#ea580c", "#fed7aa"),
    "Promo": ("#ecfeff", "#0891b2", "#a5f3fc"),
    "Spécial": ("#f0fdf4", "#15803d", "#bbf7d0"),
    "Scellé": ("#eff6ff", "#2563eb", "#bfdbfe"),
    "Stamp": ("#fdf2f8", "#db2777", "#fbcfe8"),
    "Master Ball": ("#f5f3ff", "#6d28d9", "#c4b5fd"),
    "Poké Ball": ("#fef2f2", "#b91c1c", "#fecaca"),
    "Collection": ("#fffbeb", "#92400e", "#fcd34d"),
    "Stockage": ("#f0f9ff", "#0369a1", "#bae6fd"),
    "Trade": ("#ecfeff", "#0e7490", "#67e8f9"),
}

VARIANT_BADGE_STYLES = {
    "JAP": ("#ffffff", "#E11D48", "#E11D48"),
    "PROMO": ("#ffffff", "#6D28D9", "#6D28D9"),
    "REVERSE": ("#ffffff", "#06B6D4", "#06B6D4"),
    "1RE ÉD.": ("#ffffff", "#D97706", "#D97706"),
    "STAMP": ("#ffffff", "#F97316", "#F97316"),
    "SCELLÉ": ("#ffffff", "#2563EB", "#2563EB"),
    "MASTER BALL": ("#ffffff", "#7C3AED", "#7C3AED"),
    "POKÉ BALL": ("#ffffff", "#E11D48", "#E11D48"),
}


def status_badge(label):
    style_label = {"COLLECTION": "Collection", "STOCKAGE": "Stockage"}.get(str(label), str(label))
    display_label = {"Collection": "COLLECTION", "Stockage": "STOCKAGE"}.get(str(label), str(label))
    bg, color, border = STATUS_BADGE_STYLES.get(style_label, STATUS_BADGE_STYLES["Spécial"])
    safe_label = html.escape(display_label)
    return (
        f'<span class="badge" style="background:{bg};color:{color};border:1px solid {border};'
        f'font-size:0.6rem;padding:0.2rem 0.45rem;border-radius:999px;font-weight:800;">'
        f'{safe_label}</span>'
    )


def variant_badge(label):
    display_label = str(label or "").strip().upper()
    if not display_label:
        return ""
    bg, color, border = VARIANT_BADGE_STYLES.get(display_label, ("#ffffff", "#111827", "#94a3b8"))
    safe_label = html.escape(display_label)
    return (
        f'<span class="variant-badge" style="background:{bg};color:{color};border:1px solid {border};'
        f'font-size:0.56rem;padding:0.13rem 0.34rem;border-radius:999px;font-weight:900;'
        f'line-height:1;display:inline-flex;align-items:center;white-space:nowrap;">'
        f'{safe_label}</span>'
    )


def card_is_japanese(card):
    if not isinstance(card, dict):
        return False
    if "japanese" in card:
        return bool(card.get("japanese"))
    raw = str(card.get("lang") or card.get("language") or "").strip().casefold()
    special = str(card.get("special") or card.get("special_tag") or "").casefold()
    return raw in {"ja", "jp", "jpn", "japanese"} or bool(card.get("is_japanese")) or "japon" in special or "japan" in special


def card_stamp_label(card):
    if not isinstance(card, dict):
        return ""
    raw_stamp = card.get("stamp")
    if raw_stamp:
        if isinstance(raw_stamp, bool):
            return "Stamp"
        stamp_text = str(raw_stamp or "").strip()
        return stamp_text or "Stamp"
    if card.get("is_stamp"):
        return "Stamp"

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
            return "Stamp"
    return ""


def _append_unique(labels, label):
    if label and label not in labels:
        labels.append(label)


def card_variant_badges(card):
    if not isinstance(card, dict):
        return ""

    labels = []
    if card_is_japanese(card):
        _append_unique(labels, "JAP")
    if card.get("is_reverse") or str(card.get("reverse") or "").strip().casefold() in {"1", "true", "yes", "oui", "reverse"}:
        _append_unique(labels, "REVERSE")
    if card.get("is_ed1") or str(card.get("first_edition") or card.get("firstEdition") or "").strip().casefold() in {"1", "true", "yes", "oui"}:
        _append_unique(labels, "1RE ÉD.")
    if card_stamp_label(card):
        _append_unique(labels, "STAMP")

    special_tag = card.get("special_tag", "")
    if special_tag:
        aliases = {
            "japonaise": "JAP",
            "japonais": "JAP",
            "japanese": "JAP",
            "reverse": "REVERSE",
            "1ère éd": "1RE ÉD.",
            "1ere ed": "1RE ÉD.",
            "1ère éd.": "1RE ÉD.",
            "1re éd.": "1RE ÉD.",
            "stamp": "STAMP",
            "stamped": "STAMP",
            "promo": "PROMO",
            "scellé": "SCELLÉ",
            "scelle": "SCELLÉ",
            "master ball": "MASTER BALL",
            "poké ball": "POKÉ BALL",
            "poke ball": "POKÉ BALL",
        }
        ignored = {"collection", "stockage", "storage", "trade"}
        for raw_tag in [t.strip() for t in str(special_tag).split(",") if t.strip()]:
            folded = raw_tag.casefold()
            if folded in ignored:
                continue
            label = aliases.get(folded, raw_tag.upper())
            _append_unique(labels, label)

    return " ".join(variant_badge(label) for label in labels)


def card_status_badges(card, include_storage=True):
    badges = []
    transfer_destination = str(card.get("trade_transfer_destination", "") or "").strip().lower()
    if card.get("is_reverse"):
        badges.append(status_badge("Reverse"))
    if card.get("is_ed1"):
        badges.append(status_badge("1ère Éd"))
    if card_is_japanese(card):
        badges.append(status_badge("Japonaise"))
    special_tag = card.get("special_tag", "")
    if special_tag:
        for tag in [t.strip() for t in str(special_tag).split(",") if t.strip()]:
            if tag.casefold() == "stockage" and not include_storage:
                continue
            if tag not in ("Collection", "Stockage") or (
                tag == "Collection" and not (card.get("is_collection_keep") or card.get("is_collection") or transfer_destination == "collection")
            ) or (
                tag == "Stockage" and not (include_storage and (int(card.get("stored_quantity", 0) or 0) > 0 or transfer_destination in ("stockage", "storage")))
            ):
                badges.append(status_badge(tag))
    if card.get("is_collection_keep") or card.get("is_collection") or transfer_destination == "collection":
        badges.append(status_badge("Collection"))
    if include_storage and (int(card.get("stored_quantity", 0) or 0) > 0 or transfer_destination in ("stockage", "storage")):
        badges.append(status_badge("Stockage"))
    if card.get("is_trade_card"):
        badges.append(status_badge("Trade"))
    return " ".join(badges)

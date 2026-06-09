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


def status_badge(label):
    bg, color, border = STATUS_BADGE_STYLES.get(label, STATUS_BADGE_STYLES["Spécial"])
    safe_label = html.escape(str(label))
    return (
        f'<span class="badge" style="background:{bg};color:{color};border:1px solid {border};'
        f'font-size:0.6rem;padding:0.2rem 0.45rem;border-radius:999px;font-weight:800;">'
        f'{safe_label}</span>'
    )


def card_status_badges(card, include_storage=True):
    badges = []
    if card.get("is_reverse"):
        badges.append(status_badge("Reverse"))
    if card.get("is_ed1"):
        badges.append(status_badge("1ère Éd"))
    if card.get("lang") == "ja" or card.get("is_japanese"):
        badges.append(status_badge("Japonaise"))
    special_tag = card.get("special_tag", "")
    if special_tag:
        for tag in [t.strip() for t in str(special_tag).split(",") if t.strip()]:
            badges.append(status_badge(tag))
    if card.get("is_collection_keep"):
        badges.append(status_badge("Collection"))
    if include_storage and int(card.get("stored_quantity", 0) or 0) > 0:
        badges.append(status_badge("Stockage"))
    if card.get("is_trade_card"):
        badges.append(status_badge("Trade"))
    return " ".join(badges)

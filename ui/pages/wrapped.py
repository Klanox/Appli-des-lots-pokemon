"""Premium PokéStock Wrapped page."""

from __future__ import annotations

from datetime import datetime
import html
import streamlit as st

from services.wrapped_service import UNAVAILABLE, collect_wrapped_stats
from ui.theme import wrapped_css


MONTHS_FR = {
    "01": "Janvier",
    "02": "Février",
    "03": "Mars",
    "04": "Avril",
    "05": "Mai",
    "06": "Juin",
    "07": "Juillet",
    "08": "Août",
    "09": "Septembre",
    "10": "Octobre",
    "11": "Novembre",
    "12": "Décembre",
}


def _money(value, fp_func):
    if value is None:
        return UNAVAILABLE
    return fp_func(value)


def _number(value):
    if value is None:
        return UNAVAILABLE
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _pct(value):
    if value is None:
        return UNAVAILABLE
    return f"{value:.1f}%"


def _days(value):
    if value is None:
        return UNAVAILABLE
    return f"{value:.0f} jours"


def _month_label(month_key):
    if not month_key:
        return UNAVAILABLE
    try:
        year, month = str(month_key).split("-")
        return f"{MONTHS_FR.get(month, month)} {year}"
    except ValueError:
        return str(month_key)


def _escape(value):
    return html.escape(str(value))


def _image_card(item, proxy_img_func=None, label="Image indisponible"):
    url = str((item or {}).get("image_url") or "").strip()
    if url and proxy_img_func:
        url = proxy_img_func(url)
    if not url:
        return f"""
        <div class="ps-wrapped-card-visual ps-wrapped-card-placeholder">
            <span>{_escape(label)}</span>
        </div>
        """
    escaped_url = html.escape(url, quote=True)
    return f"""
    <div class="ps-wrapped-card-visual">
        <img src="{escaped_url}" alt="{_escape((item or {}).get('name') or (item or {}).get('lot') or label)}"
             onerror="this.style.display='none';this.parentElement.classList.add('ps-wrapped-card-placeholder');this.parentElement.innerHTML='<span>Image indisponible</span>';">
    </div>
    """


def _feature_card(item, title, subtitle, proxy_img_func=None):
    return f"""
    <div class="ps-wrapped-feature">
        {_image_card(item, proxy_img_func)}
        <div>
            <span>{_escape(title)}</span>
            <strong>{_escape((item or {}).get("name") or (item or {}).get("lot") or UNAVAILABLE)}</strong>
            <em>{_escape(subtitle)}</em>
        </div>
    </div>
    """


def _list_rows(items, primary_key, secondary_builder):
    if not items:
        return f'<div class="ps-wrapped-empty">{UNAVAILABLE}</div>'
    rows = []
    for idx, item in enumerate(items, start=1):
        rows.append(
            f"""
            <div class="ps-wrapped-row">
                <span class="ps-wrapped-rank">#{idx}</span>
                <div>
                    <strong>{_escape(item.get(primary_key, "?"))}</strong>
                    <span>{_escape(secondary_builder(item))}</span>
                </div>
            </div>
            """
        )
    return "\n".join(rows)


def _metric(label, value, hint=""):
    hint_html = f"<span>{_escape(hint)}</span>" if hint else ""
    return f"""
    <div class="ps-wrapped-metric">
        <span>{_escape(label)}</span>
        <strong>{_escape(value)}</strong>
        {hint_html.replace("<span>", "<em>").replace("</span>", "</em>")}
    </div>
    """


def _mini_stat(label, value):
    return f"""
    <div class="ps-wrapped-mini-stat">
        <span>{_escape(label)}</span>
        <strong>{_escape(value)}</strong>
    </div>
    """


def _story_chips(items):
    return (
        '<div class="ps-wrapped-chip-row">'
        + "".join(
            f'<div class="ps-wrapped-chip"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>'
            for label, value in items
        )
        + "</div>"
    )


def _profile_from_stats(stats):
    cards_sold = stats.get("cards_sold") or 0
    ca_total = stats.get("ca_total") or 0
    profit_total = stats.get("profit_total") or 0
    lots_bought = stats.get("lots_bought") or 0
    avg_purchase_percent = stats.get("avg_purchase_percent")
    avg_days_to_sell = stats.get("avg_days_to_sell_card")
    top_sold = stats.get("top_sold_cards") or []
    top_recovered = stats.get("top_recovered_cards") or []
    best_deal = stats.get("best_deal") or {}

    top_names = " ".join(str(card.get("name") or "") for card in top_sold + top_recovered).lower()
    ultra_markers = (" ex", " gx", " v", " vmax", " vstar", "secret", "secrète", "alt", "full art", "rainbow")

    if best_deal and (best_deal.get("multiplier") or 0) >= 3:
        return {
            "name": "Sniper Vinted",
            "line": "Tu as repéré le bon prix, puis laissé la marge parler.",
            "reason": f"Meilleur multiplicateur : x{best_deal.get('multiplier'):.1f}.",
        }
    if avg_purchase_percent is not None and avg_purchase_percent <= 45:
        return {
            "name": "Sniper de bonnes affaires",
            "line": "Tu as surtout gagné l'année sur la qualité des achats.",
            "reason": f"Achat moyen à {_pct(avg_purchase_percent)} de la cote.",
        }
    if cards_sold >= 80 or (avg_days_to_sell is not None and avg_days_to_sell <= 10 and cards_sold > 0):
        return {
            "name": "Flipper express",
            "line": "Tu n'as pas laissé les cartes dormir trop longtemps.",
            "reason": f"{_number(cards_sold)} cartes vendues sur l'année.",
        }
    if lots_bought >= 8:
        return {
            "name": "Roi de la brocante",
            "line": "Ton terrain de jeu, c'était clairement les lots.",
            "reason": f"{_number(lots_bought)} lots achetés dans l'année.",
        }
    if any(marker in f" {top_names}" for marker in ultra_markers):
        return {
            "name": "Maître des ultras",
            "line": "Les cartes qui brillent ont bien porté ton année.",
            "reason": "Profil basé sur tes meilleures cartes vendues ou récupérées.",
        }
    if (stats.get("stock_snapshot") or {}).get("value", 0) >= max(ca_total * 0.5, 100):
        return {
            "name": "Collectionneur premium",
            "line": "Ton stock garde encore une belle réserve de valeur.",
            "reason": "Profil basé sur la valeur restante disponible.",
        }
    if profit_total > 0 and ca_total > 0:
        return {
            "name": "Chasseur de pépites",
            "line": "Tu as transformé les bons coups en vraie valeur.",
            "reason": f"{_money(profit_total, lambda value: f'{value:.2f}€')} de bénéfice calculé.",
        }
    return {
        "name": "Collectionneur patient",
        "line": "L'année a posé les bases. Le prochain drop peut tout changer.",
        "reason": "Pas assez de données fortes pour un profil plus précis.",
    }


def _scene_visual(item, proxy_img_func=None, label="Image indisponible"):
    return f"""
    <div class="ps-wrapped-scene-visual">
        {_image_card(item, proxy_img_func, label)}
    </div>
    """


def _profile_panel(profile):
    return f"""
    <div class="ps-wrapped-profile-card">
        <span>Ton profil</span>
        <strong>{_escape(profile["name"])}</strong>
        <em>{_escape(profile["line"])}</em>
        <small>{_escape(profile["reason"])}</small>
    </div>
    """


def _deal_panel(deal, fp_func, proxy_img_func=None):
    if not deal:
        return f'<div class="ps-wrapped-empty">{UNAVAILABLE}</div>'
    multiplier = deal.get("multiplier")
    multiplier_text = f"x{multiplier:.1f}" if multiplier else UNAVAILABLE
    return f"""
    <div class="ps-wrapped-deal-card">
        {_scene_visual(deal, proxy_img_func, "Meilleur coup indisponible")}
        <div class="ps-wrapped-deal-copy">
            <span>Ton meilleur coup</span>
            <strong>{_escape(deal.get("name") or UNAVAILABLE)}</strong>
            <em>Achetée {_escape(_money(deal.get("cost"), fp_func))} · vendue {_escape(_money(deal.get("price"), fp_func))}</em>
            <small>+{_escape(_money(deal.get("benef"), fp_func))} · {multiplier_text}</small>
        </div>
    </div>
    """


def _timeline_panel(items):
    if not items:
        return f'<div class="ps-wrapped-empty">{UNAVAILABLE}</div>'
    rows = []
    for idx, item in enumerate(items, start=1):
        rows.append(
            f"""
            <div class="ps-wrapped-timeline-item">
                <span>{idx}</span>
                <div>
                    <strong>{_escape(item.get("label") or "")}</strong>
                    <em>{_escape(item.get("title") or UNAVAILABLE)}</em>
                    <small>{_escape(item.get("detail") or "")}</small>
                </div>
            </div>
            """
        )
    return '<div class="ps-wrapped-timeline">' + "".join(rows) + "</div>"


def _stock_panel(stock, fp_func, proxy_img_func=None):
    if not stock:
        return f'<div class="ps-wrapped-empty">{UNAVAILABLE}</div>'
    patient = stock.get("most_patient") or {}
    return f"""
    <div class="ps-wrapped-stock-card">
        {_scene_visual(patient, proxy_img_func, "Carte patiente indisponible")}
        <div>
            <span>Encore en réserve</span>
            <strong>{_escape(_number(stock.get("quantity")))} cartes</strong>
            <em>{_escape(_money(stock.get("value"), fp_func))} de stock restant</em>
            <small>{_escape(patient.get("name") or "Aucune carte patiente détectée")}</small>
        </div>
    </div>
    """


def _share_card_preview(stats, stats_data, fp_func, profile, best_lot):
    return f"""
    <div class="ps-wrapped-share-preview">
        <div class="ps-wrapped-share-shine"></div>
        <div class="ps-wrapped-share-top">
            <span>Dexify</span>
            <strong>Carte souvenir {stats_data["year"]}</strong>
        </div>
        <div class="ps-wrapped-share-profile">
            <span>Profil</span>
            <strong>{_escape(profile["name"])}</strong>
        </div>
        <div class="ps-wrapped-share-grid">
            <div><span>Cartes vendues</span><strong>{_escape(_number(stats.get("cards_sold")))}</strong></div>
            <div><span>CA</span><strong>{_escape(_money(stats.get("ca_total"), fp_func))}</strong></div>
            <div><span>Bénéfice</span><strong>{_escape(_money(stats.get("profit_total"), fp_func))}</strong></div>
            <div><span>Meilleur lot</span><strong>{_escape((best_lot or {}).get("lot") or UNAVAILABLE)}</strong></div>
        </div>
    </div>
    """


def _share_card_svg(stats, stats_data, fp_func, profile, best_lot):
    year = _escape(stats_data["year"])
    cards = _escape(_number(stats.get("cards_sold")))
    ca = _escape(_money(stats.get("ca_total"), fp_func))
    profit = _escape(_money(stats.get("profit_total"), fp_func))
    lot_name = _escape((best_lot or {}).get("lot") or UNAVAILABLE)
    profile_name = _escape(profile["name"])
    profile_line = _escape(profile["line"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#02050d"/>
    <stop offset="52%" stop-color="#101426"/>
    <stop offset="100%" stop-color="#1b122f"/>
  </linearGradient>
  <linearGradient id="foil" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#ffffff" stop-opacity="0"/>
    <stop offset="42%" stop-color="#facc15" stop-opacity="0.20"/>
    <stop offset="58%" stop-color="#7dd3fc" stop-opacity="0.16"/>
    <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
  </linearGradient>
  <radialGradient id="glow1" cx="18%" cy="12%" r="55%">
    <stop offset="0%" stop-color="#facc15" stop-opacity="0.28"/>
    <stop offset="100%" stop-color="#facc15" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="glow2" cx="80%" cy="90%" r="55%">
    <stop offset="0%" stop-color="#22d3ee" stop-opacity="0.24"/>
    <stop offset="100%" stop-color="#22d3ee" stop-opacity="0"/>
  </radialGradient>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
    <feDropShadow dx="0" dy="28" stdDeviation="32" flood-color="#000000" flood-opacity="0.45"/>
  </filter>
</defs>
<rect width="1080" height="1920" fill="url(#bg)"/>
<rect width="1080" height="1920" fill="url(#glow1)"/>
<rect width="1080" height="1920" fill="url(#glow2)"/>
<rect x="-120" y="240" width="1320" height="360" transform="rotate(-12 540 420)" fill="url(#foil)" opacity="0.85"/>
<rect x="54" y="54" width="972" height="1812" rx="72" fill="none" stroke="#ffffff" stroke-opacity="0.18" stroke-width="3"/>
<rect x="82" y="82" width="916" height="1756" rx="54" fill="none" stroke="#facc15" stroke-opacity="0.16" stroke-width="2"/>
<text x="90" y="122" fill="#ffffff" opacity="0.72" font-family="Arial, sans-serif" font-size="34" font-weight="800" letter-spacing="7">DEXIFY</text>
<text x="90" y="230" fill="#ffffff" font-family="Arial, sans-serif" font-size="76" font-weight="900">Ma saison</text>
<text x="90" y="322" fill="#facc15" font-family="Arial, sans-serif" font-size="92" font-weight="900">PokéStock {year}</text>
<g filter="url(#shadow)">
  <rect x="82" y="430" width="916" height="930" rx="62" fill="#ffffff" opacity="0.105" stroke="#ffffff" stroke-opacity="0.24"/>
  <text x="140" y="560" fill="#ffffff" opacity="0.68" font-family="Arial, sans-serif" font-size="32" font-weight="800">CARTES PARTIES</text>
  <text x="140" y="690" fill="#ffffff" font-family="Arial, sans-serif" font-size="150" font-weight="900">{cards}</text>
  <text x="140" y="850" fill="#ffffff" opacity="0.68" font-family="Arial, sans-serif" font-size="32" font-weight="800">CE QUE TU AS RAMENÉ</text>
  <text x="140" y="966" fill="#facc15" font-family="Arial, sans-serif" font-size="96" font-weight="900">{ca}</text>
  <text x="140" y="1114" fill="#ffffff" opacity="0.68" font-family="Arial, sans-serif" font-size="32" font-weight="800">CE QU'IL RESTE</text>
  <text x="140" y="1218" fill="#7dd3fc" font-family="Arial, sans-serif" font-size="88" font-weight="900">{profit}</text>
</g>
<text x="90" y="1470" fill="#ffffff" opacity="0.7" font-family="Arial, sans-serif" font-size="34" font-weight="800">MEILLEUR LOT</text>
<text x="90" y="1540" fill="#ffffff" font-family="Arial, sans-serif" font-size="44" font-weight="850">{lot_name}</text>
<rect x="80" y="1630" width="920" height="170" rx="42" fill="#ffffff" opacity="0.10" stroke="#bbf7d0" stroke-opacity="0.36"/>
<text x="130" y="1702" fill="#bbf7d0" font-family="Arial, sans-serif" font-size="34" font-weight="800">PROFIL</text>
<text x="130" y="1765" fill="#ffffff" font-family="Arial, sans-serif" font-size="58" font-weight="900">{profile_name}</text>
<text x="130" y="1830" fill="#ffffff" opacity="0.72" font-family="Arial, sans-serif" font-size="30" font-weight="700">{profile_line}</text>
</svg>"""


def _short_svg_text(value, max_len=36):
    text = str(value or UNAVAILABLE)
    if len(text) <= max_len:
        return _escape(text)
    return _escape(text[: max_len - 3].rstrip() + "...")


def _share_card_svg_premium(stats, stats_data, fp_func, profile, best_lot):
    year = _escape(stats_data["year"])
    cards = _escape(_number(stats.get("cards_sold")))
    ca = _escape(_money(stats.get("ca_total"), fp_func))
    profit = _escape(_money(stats.get("profit_total"), fp_func))
    lot_name = _short_svg_text((best_lot or {}).get("lot") or UNAVAILABLE, 34)
    profile_name = _short_svg_text(profile["name"], 28)
    profile_line = _short_svg_text(profile["line"], 58)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#04030a"/>
    <stop offset="48%" stop-color="#101225"/>
    <stop offset="100%" stop-color="#211236"/>
  </linearGradient>
  <linearGradient id="foil" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#ffffff" stop-opacity="0"/>
    <stop offset="34%" stop-color="#f7d56d" stop-opacity="0.35"/>
    <stop offset="55%" stop-color="#8be9ff" stop-opacity="0.25"/>
    <stop offset="74%" stop-color="#c4b5fd" stop-opacity="0.22"/>
    <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
  </linearGradient>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
    <feDropShadow dx="0" dy="24" stdDeviation="24" flood-color="#000000" flood-opacity="0.46"/>
  </filter>
</defs>
<rect width="1080" height="1920" fill="url(#bg)"/>
<rect x="-190" y="175" width="1440" height="420" transform="rotate(-11 540 385)" fill="url(#foil)" opacity="0.72"/>
<rect x="-140" y="1340" width="1320" height="330" transform="rotate(9 540 1505)" fill="url(#foil)" opacity="0.42"/>
<rect x="48" y="48" width="984" height="1824" rx="78" fill="none" stroke="#ffffff" stroke-opacity="0.22" stroke-width="3"/>
<rect x="82" y="82" width="916" height="1756" rx="56" fill="none" stroke="#f7d56d" stroke-opacity="0.24" stroke-width="2"/>
<circle cx="892" cy="172" r="64" fill="#f7d56d" opacity="0.94"/>
<text x="892" y="188" text-anchor="middle" fill="#111827" font-family="Arial, sans-serif" font-size="34" font-weight="900">DX</text>
<text x="90" y="145" fill="#ffffff" opacity="0.76" font-family="Arial, sans-serif" font-size="31" font-weight="900" letter-spacing="8">DEXIFY</text>
<text x="90" y="245" fill="#ffffff" font-family="Arial, sans-serif" font-size="68" font-weight="900">Carte souvenir</text>
<text x="90" y="340" fill="#f7d56d" font-family="Arial, sans-serif" font-size="92" font-weight="900">PokéStock {year}</text>
<g filter="url(#shadow)">
  <rect x="92" y="430" width="896" height="710" rx="58" fill="#ffffff" opacity="0.12" stroke="#ffffff" stroke-opacity="0.28"/>
  <text x="150" y="560" fill="#ffffff" opacity="0.70" font-family="Arial, sans-serif" font-size="30" font-weight="900" letter-spacing="4">TON PROFIL</text>
  <text x="150" y="660" fill="#ffffff" font-family="Arial, sans-serif" font-size="78" font-weight="900">{profile_name}</text>
  <text x="150" y="735" fill="#ffffff" opacity="0.74" font-family="Arial, sans-serif" font-size="30" font-weight="700">{profile_line}</text>
  <rect x="150" y="830" width="780" height="2" fill="#ffffff" opacity="0.18"/>
  <text x="150" y="935" fill="#f7d56d" font-family="Arial, sans-serif" font-size="132" font-weight="900">{cards}</text>
  <text x="390" y="932" fill="#ffffff" opacity="0.72" font-family="Arial, sans-serif" font-size="34" font-weight="800">cartes parties</text>
</g>
<g>
  <rect x="92" y="1215" width="424" height="210" rx="42" fill="#ffffff" opacity="0.10" stroke="#ffffff" stroke-opacity="0.20"/>
  <text x="135" y="1290" fill="#ffffff" opacity="0.68" font-family="Arial, sans-serif" font-size="28" font-weight="900">CA</text>
  <text x="135" y="1375" fill="#8be9ff" font-family="Arial, sans-serif" font-size="58" font-weight="900">{ca}</text>
  <rect x="564" y="1215" width="424" height="210" rx="42" fill="#ffffff" opacity="0.10" stroke="#ffffff" stroke-opacity="0.20"/>
  <text x="607" y="1290" fill="#ffffff" opacity="0.68" font-family="Arial, sans-serif" font-size="28" font-weight="900">BÉNÉFICE</text>
  <text x="607" y="1375" fill="#f7d56d" font-family="Arial, sans-serif" font-size="58" font-weight="900">{profit}</text>
</g>
<rect x="92" y="1515" width="896" height="190" rx="42" fill="#ffffff" opacity="0.09" stroke="#f7d56d" stroke-opacity="0.30"/>
<text x="140" y="1592" fill="#ffffff" opacity="0.68" font-family="Arial, sans-serif" font-size="28" font-weight="900">MEILLEUR LOT</text>
<text x="140" y="1670" fill="#ffffff" font-family="Arial, sans-serif" font-size="46" font-weight="900">{lot_name}</text>
<text x="90" y="1812" fill="#ffffff" opacity="0.62" font-family="Arial, sans-serif" font-size="30" font-weight="800">Une vraie carte. Tes vraies données.</text>
</svg>"""


def _debug_value(value, fp_func):
    if value is None:
        return UNAVAILABLE
    if isinstance(value, (int, float)):
        return fp_func(value) if isinstance(value, float) else str(value)
    if isinstance(value, dict):
        name = value.get("name") or value.get("lot") or value.get("label") or value.get("month")
        if value.get("ca") is not None:
            return f"{name or '?'} — CA {fp_func(value.get('ca', 0))}"
        if value.get("benef") is not None:
            return f"{name or '?'} — bénéfice {fp_func(value.get('benef', 0))}"
        return str(name or value)
    return str(value)


def _inject_css():
    st.markdown(wrapped_css(), unsafe_allow_html=True)


def _build_slides(stats_data, fp_func, proxy_img_func=None):
    stats = stats_data["stats"]
    year = stats_data["year"]

    best_month = stats.get("best_month") or {}
    best_deal = stats.get("best_deal") or {}
    top_sold_cards = stats.get("top_sold_cards") or []
    mvp_card = top_sold_cards[0] if top_sold_cards else {}
    top_recovered_cards = stats.get("top_recovered_cards") or []
    best_lots = stats.get("top_lots") or []
    top_recovered = top_recovered_cards[0] if top_recovered_cards else {}
    best_lot = best_lots[0] if best_lots else {}
    stock = stats.get("stock_snapshot") or {}
    timeline = stats.get("timeline") or []
    profile = _profile_from_stats(stats)
    best_month_label = _month_label(best_month.get("month"))

    slides = [
        {
            "scene": "intro",
            "layout": "hero",
            "artifact": "booster",
            "kicker": "Dexify ouvre le classeur",
            "title": f"{year}, c'était ton chapitre.",
            "big": "PokéStock Wrapped",
            "subtitle": "Les chiffres sont là. Mais ce qu'on va garder, ce sont les moments.",
            "body": _story_chips(
                [
                    ("Cartes parties", _number(stats.get("cards_sold"))),
                    ("Profil", profile["name"]),
                ]
            ),
        },
        {
            "scene": "revenue",
            "layout": "number",
            "artifact": "stack",
            "kicker": "La pile qui monte",
            "title": "Cette année, tes cartes ont ramené",
            "big": _money(stats.get("ca_total"), fp_func),
            "subtitle": "Une vente après l'autre. Rien de magique, juste ton œil qui s'affine.",
            "body": _story_chips(
                [
                    ("Dans la poche", _money(stats.get("profit_total"), fp_func)),
                ]
            ),
        },
        {
            "scene": "profit",
            "layout": "number",
            "artifact": "coin",
            "kicker": "Le vrai sourire",
            "title": "Au final, tu gardes",
            "big": _money(stats.get("profit_total"), fp_func),
            "subtitle": "C'est le petit bruit satisfaisant d'un lot bien joué.",
            "body": _story_chips(
                [
                    ("Négo moyenne", _pct(stats.get("avg_negotiation_pct"))),
                ]
            ),
        },
        {
            "scene": "sold",
            "layout": "number",
            "artifact": "parcel",
            "kicker": "Les cartes ont voyagé",
            "title": "Tu as laissé partir",
            "big": _number(stats.get("cards_sold")),
            "subtitle": "cartes. Elles ont quitté tes boîtes pour commencer ailleurs.",
            "body": _story_chips(
                [
                    ("Ventes conclues", _number(stats_data.get("sales_count"))),
                ]
            ),
        },
        {
            "scene": "month",
            "layout": "spotlight",
            "artifact": "calendar",
            "kicker": "Le mois qui claque",
            "title": "Celui-là, tu l'as senti passer",
            "big": best_month_label,
            "subtitle": "Le mois où PokéStock avait clairement envie de tourner.",
            "body": _story_chips(
                [
                    ("CA", _money(best_month.get("ca"), fp_func)),
                    ("Cartes", _number(best_month.get("quantity"))),
                ]
            ),
        },
        {
            "scene": "mvp",
            "layout": "card",
            "artifact": "trophy",
            "kicker": "Hall of Fame",
            "title": mvp_card.get("name", UNAVAILABLE),
            "big": fp_func(mvp_card.get("ca", 0)) if mvp_card else UNAVAILABLE,
            "subtitle": "Ta carte MVP. Celle qui mérite sa petite vitrine.",
            "body": _scene_visual(mvp_card, proxy_img_func, "Carte MVP indisponible")
            + _story_chips(
                [
                    ("Bénéfice", fp_func(mvp_card.get("benef", 0)) if mvp_card else UNAVAILABLE),
                ]
            ),
        },
        {
            "scene": "deal",
            "layout": "duo",
            "artifact": "scope",
            "kicker": "Le coup propre",
            "title": "Celle-là, tu l'as bien lue.",
            "big": _money(best_deal.get("benef"), fp_func) if best_deal else UNAVAILABLE,
            "subtitle": "Le genre de coup qui donne envie de rouvrir une annonce juste pour sourire.",
            "body": _deal_panel(best_deal, fp_func, proxy_img_func),
        },
        {
            "scene": "pull",
            "layout": "card",
            "artifact": "spark",
            "kicker": "La trouvaille",
            "title": top_recovered.get("name", "La carte qui ressort") if top_recovered else "La carte qui ressort",
            "big": fp_func(top_recovered.get("value", 0)) if top_recovered else UNAVAILABLE,
            "subtitle": "Ce moment discret où le lot commence à raconter quelque chose.",
            "body": _scene_visual(top_recovered, proxy_img_func, "Top récupération indisponible")
            + _story_chips(
                [
                    ("Lots achetés", _number(stats.get("lots_bought"))),
                ]
            ),
        },
        {
            "scene": "lot",
            "layout": "card",
            "artifact": "binder",
            "kicker": "Le lot solide",
            "title": best_lot.get("lot", UNAVAILABLE) if best_lot else UNAVAILABLE,
            "big": fp_func(best_lot.get("benef", 0)) if best_lot else UNAVAILABLE,
            "subtitle": "Pas besoin de faire du bruit quand les chiffres parlent tranquille.",
            "body": _scene_visual(best_lot, proxy_img_func, "Image du lot indisponible")
            + _story_chips(
                [
                    ("Cartes", _number(best_lot.get("quantity")) if best_lot else UNAVAILABLE),
                ]
            ),
        },
        {
            "scene": "risk",
            "layout": "number",
            "artifact": "table",
            "kicker": "Le pari",
            "title": "Tu as mis sur la table",
            "big": _money(stats.get("purchase_total"), fp_func),
            "subtitle": "Puis tu as trié, choisi, tenté, corrigé. C'est là que tout se joue.",
            "body": _story_chips(
                [
                    ("Vendu", _money(stats.get("ca_total"), fp_func)),
                    ("Achat / cote", _pct(stats.get("avg_purchase_percent"))),
                ]
            ),
        },
        {
            "scene": "timeline",
            "layout": "timeline",
            "artifact": "notebook",
            "kicker": "Le carnet",
            "title": "Les traces qui restent",
            "subtitle": "Trois petits repères. Assez pour revoir l'année d'un coup.",
            "body": _timeline_panel(timeline),
        },
        {
            "scene": "stock",
            "layout": "duo",
            "artifact": "vault",
            "kicker": "Le prochain booster",
            "title": "La suite est déjà dans les boîtes",
            "big": _money(stock.get("value"), fp_func) if stock else UNAVAILABLE,
            "subtitle": "Des cartes qui attendent leur moment. Le prochain chapitre n'est pas vide.",
            "body": _stock_panel(stock, fp_func, proxy_img_func),
        },
        {
            "scene": "profile",
            "layout": "profile",
            "artifact": "badge",
            "kicker": "Ton style",
            "title": "Si ton année avait un badge, ce serait",
            "big": profile["name"],
            "subtitle": profile["line"],
            "body": _profile_panel(profile),
        },
        {
            "scene": "final",
            "layout": "final",
            "artifact": "trainer",
            "kicker": "À garder dans le classeur",
            "title": "Voilà ta carte collector.",
            "subtitle": "Un souvenir Dexify, tiré de tes vraies données. Pas inventé. Juste à toi.",
            "body": _share_card_preview(stats, stats_data, fp_func, profile, best_lot),
            "is_final": True,
        },
    ]
    refined_copy = {
        "intro": {
            "kicker": "Le classeur s'ouvre",
            "title": f"{year}, on le garde.",
            "big": "Ton Wrapped",
            "subtitle": "Pas juste des chiffres. Les petits coups, les cartes parties, les lots qui ont raconté quelque chose.",
        },
        "revenue": {
            "kicker": "Ticket de caisse",
            "title": "Cette année, tes cartes ont fait entrer",
            "subtitle": "Chaque vente a ajouté une ligne au ticket. Certaines petites, d'autres très propres.",
        },
        "profit": {
            "kicker": "Marge nette",
            "title": "Et quand la poussière retombe, il reste",
            "subtitle": "C'est là que ton œil fait la différence.",
        },
        "sold": {
            "kicker": "Colis prêts",
            "title": "Tu as fait partir",
            "subtitle": "Des cartes qui dormaient chez toi ont trouvé une autre histoire.",
        },
        "month": {
            "kicker": "Mois chaud",
            "title": "Ce mois-là, tout s'est accéléré",
            "subtitle": "Le genre de période où tu rafraîchis PokéStock avec un petit sourire.",
        },
        "mvp": {
            "kicker": "Hall of Fame",
            "subtitle": "Ta carte MVP. Celle qu'on met sous lumière, juste une seconde de plus.",
        },
        "deal": {
            "kicker": "Flip propre",
            "title": "Ton meilleur coup avait du flair",
            "subtitle": "Un achat bien lu. Une vente qui confirme. Le genre de moment qui donne envie de recommencer.",
        },
        "pull": {
            "kicker": "Ouverture de booster",
            "title": "La trouvaille qui ressort",
            "subtitle": "Dans un lot, il y a toujours une carte qui attire l'œil avant les autres.",
        },
        "lot": {
            "kicker": "Page de binder",
            "title": "Ton lot le plus solide",
            "subtitle": "Pas forcément le plus bruyant. Juste celui qui a tenu sa promesse.",
        },
        "risk": {
            "kicker": "Sur le tapis",
            "title": "Tu as engagé",
            "subtitle": "Acheter, trier, patienter, vendre : c'est rarement instantané, mais c'est là que se construit l'année.",
        },
        "timeline": {
            "kicker": "Carnet d'année",
            "title": "Trois traces à garder",
            "subtitle": "Des repères simples, comme des onglets dans ton classeur.",
        },
        "stock": {
            "kicker": "Sous la lampe",
            "title": "La suite attend déjà",
            "subtitle": "Ton stock n'est pas juste du stock. C'est le prochain chapitre.",
        },
        "profile": {
            "kicker": "Carte de dresseur",
            "title": "Ton style, cette année",
            "subtitle": profile["line"],
        },
        "final": {
            "kicker": "À glisser dans le binder",
            "title": "Ta carte souvenir est prête.",
            "subtitle": "Une petite trace de ton année, tirée de tes vraies données.",
        },
    }
    for slide in slides:
        slide.update(refined_copy.get(slide.get("scene"), {}))
    return slides


def render_wrapped_page(
    *,
    ld_func,
    calc_cout_lot_func,
    effective_purchase_price_func,
    fp_func,
    proxy_img_func=None,
    lots_archives_path="lots_archives.json",
    set_current_page_func=None,
):
    _inject_css()

    now = datetime.now()
    if "wrapped_open" not in st.session_state:
        st.session_state["wrapped_open"] = False

    if not st.session_state["wrapped_open"]:
        st.markdown(
            """
            <section class="ps-wrapped-entry">
                <div class="ps-wrapped-entry-card">
                    <span>Dexify présente</span>
                    <strong>PokéStock Wrapped</strong>
                    <em>Ta saison en cartes, racontée comme une petite capsule souvenir.</em>
                </div>
            </section>
            """,
            unsafe_allow_html=True,
        )
        year = st.number_input("Année", min_value=2000, max_value=now.year + 1, value=now.year, step=1)
        if st.button("Ouvrir le Wrapped", width="stretch", type="primary", key="wrapped_open_button"):
            st.session_state["wrapped_year"] = int(year)
            st.session_state["wrapped_slide_ix"] = 0
            st.session_state["wrapped_open"] = True
            st.rerun()
        return

    year = int(st.session_state.get("wrapped_year", now.year))
    data = ld_func()
    stats_data = collect_wrapped_stats(
        data,
        year,
        calc_cout_lot_func=calc_cout_lot_func,
        effective_purchase_price_func=effective_purchase_price_func,
        lots_archives_path=lots_archives_path,
    )
    stats = stats_data["stats"]
    best_lots = stats.get("top_lots") or []
    best_lot = best_lots[0] if best_lots else {}
    profile = _profile_from_stats(stats)

    slides = _build_slides(stats_data, fp_func, proxy_img_func)
    total = len(slides)
    if "wrapped_slide_ix" not in st.session_state:
        st.session_state["wrapped_slide_ix"] = 0
    st.session_state["wrapped_slide_ix"] = max(0, min(st.session_state["wrapped_slide_ix"], total - 1))

    current = st.session_state["wrapped_slide_ix"]
    slide = slides[current]
    progress = int(((current + 1) / total) * 100)
    scene = "".join(ch for ch in str(slide.get("scene") or "default").lower() if ch.isalnum() or ch == "-")
    layout = "".join(ch for ch in str(slide.get("layout") or "story").lower() if ch.isalnum() or ch == "-")
    artifact = "".join(ch for ch in str(slide.get("artifact") or "card").lower() if ch.isalnum() or ch == "-")

    slide_body = slide.get("body", "")
    big_number = (
        f'<div class="ps-wrapped-big-number">{_escape(slide.get("big"))}</div>'
        if slide.get("big")
        else ""
    )
    subtitle = (
        f'<div class="ps-wrapped-subtitle">{_escape(slide.get("subtitle"))}</div>'
        if slide.get("subtitle")
        else ""
    )

    st.html(
        """
        <script>
        (function() {
            const doc = parent.document;
            const root = doc.documentElement;
            if (!doc.fullscreenElement && root && root.requestFullscreen) {
                root.requestFullscreen().catch(function() {});
            }
        })();
        </script>
        """,
    )

    st.html(
        f"""
        <section class="ps-wrapped-shell ps-wrapped-scene-{scene}">
            <div class="ps-wrapped-grain"></div>
            <div class="ps-wrapped-card-back"></div>
            <div class="ps-wrapped-foil-band"></div>
            <div class="ps-wrapped-holo-ring"></div>
            <div class="ps-wrapped-artifact ps-wrapped-artifact-{artifact}"><span></span></div>
            <div class="ps-wrapped-hero">
                <div class="ps-wrapped-top">
                    <div>
                        <div class="ps-wrapped-brand">PokéStock Wrapped</div>
                    </div>
                    <div class="ps-wrapped-count">Slide {current + 1} / {total}</div>
                    <div class="ps-wrapped-progress"><span style="width:{progress}%"></span></div>
                </div>
                <div class="ps-wrapped-story ps-wrapped-layout-{layout}">
                    <div class="ps-wrapped-kicker">{_escape(slide.get("kicker", "PokéStock Wrapped"))}</div>
                    <div class="ps-wrapped-title">{_escape(slide.get("title", ""))}</div>
                    {big_number}
                    {subtitle}
                    {slide_body}
                </div>
            </div>
            <div class="ps-wrapped-bottom-hint">Tape à gauche ou à droite pour naviguer.</div>
        </section>
        """,
    )

    st.markdown('<div class="ps-wrapped-story-click-layer"></div>', unsafe_allow_html=True)
    tap_left, tap_right = st.columns(2, gap="small")
    with tap_left:
        if st.button("Zone precedente", width="stretch", disabled=current <= 0, key="wrapped_tap_prev"):
            st.session_state["wrapped_slide_ix"] = max(current - 1, 0)
            st.rerun()
    with tap_right:
        if st.button("Zone suivante", width="stretch", disabled=current >= total - 1, key="wrapped_tap_next"):
            st.session_state["wrapped_slide_ix"] = min(current + 1, total - 1)
            st.rerun()

    if current >= total - 1:
        share_svg = _share_card_svg_premium(stats, stats_data, fp_func, profile, best_lot)
        st.markdown('<div class="ps-wrapped-download-zone"></div>', unsafe_allow_html=True)
        st.download_button(
            "Télécharger ma carte",
            data=share_svg.encode("utf-8"),
            file_name=f"pokestock_wrapped_{year}.svg",
            mime="image/svg+xml",
            width="stretch",
            type="secondary",
            key="wrapped_download_card",
        )
        st.markdown('<div class="ps-wrapped-close-zone"></div>', unsafe_allow_html=True)
        if st.button("Fermer le Wrapped", width="stretch", type="primary", key="wrapped_close"):
            st.session_state["wrapped_open"] = False
            st.session_state["wrapped_slide_ix"] = 0
            st.rerun()

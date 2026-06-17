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
        <div class="ps-wrapped-share-top">
            <span>Dexify</span>
            <strong>Mon PokéStock Wrapped {stats_data["year"]}</strong>
        </div>
        <div class="ps-wrapped-share-grid">
            <div><span>Cartes vendues</span><strong>{_escape(_number(stats.get("cards_sold")))}</strong></div>
            <div><span>CA</span><strong>{_escape(_money(stats.get("ca_total"), fp_func))}</strong></div>
            <div><span>Bénéfice</span><strong>{_escape(_money(stats.get("profit_total"), fp_func))}</strong></div>
            <div><span>Meilleur lot</span><strong>{_escape((best_lot or {}).get("lot") or UNAVAILABLE)}</strong></div>
        </div>
        <div class="ps-wrapped-share-profile">
            <span>Profil</span>
            <strong>{_escape(profile["name"])}</strong>
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
    <stop offset="0%" stop-color="#050816"/>
    <stop offset="45%" stop-color="#24104f"/>
    <stop offset="100%" stop-color="#075985"/>
  </linearGradient>
  <radialGradient id="glow1" cx="20%" cy="10%" r="55%">
    <stop offset="0%" stop-color="#8b5cf6" stop-opacity="0.95"/>
    <stop offset="100%" stop-color="#8b5cf6" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="glow2" cx="80%" cy="90%" r="55%">
    <stop offset="0%" stop-color="#22d3ee" stop-opacity="0.7"/>
    <stop offset="100%" stop-color="#22d3ee" stop-opacity="0"/>
  </radialGradient>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
    <feDropShadow dx="0" dy="28" stdDeviation="32" flood-color="#000000" flood-opacity="0.45"/>
  </filter>
</defs>
<rect width="1080" height="1920" fill="url(#bg)"/>
<rect width="1080" height="1920" fill="url(#glow1)"/>
<rect width="1080" height="1920" fill="url(#glow2)"/>
<circle cx="170" cy="1530" r="230" fill="#facc15" opacity="0.16"/>
<circle cx="910" cy="240" r="190" fill="#38bdf8" opacity="0.18"/>
<text x="90" y="120" fill="#ffffff" opacity="0.76" font-family="Arial, sans-serif" font-size="36" font-weight="800" letter-spacing="6">DEXIFY</text>
<text x="90" y="235" fill="#ffffff" font-family="Arial, sans-serif" font-size="74" font-weight="900">Mon PokéStock</text>
<text x="90" y="320" fill="#facc15" font-family="Arial, sans-serif" font-size="92" font-weight="900">Wrapped {year}</text>
<g filter="url(#shadow)">
  <rect x="80" y="430" width="920" height="940" rx="58" fill="#ffffff" opacity="0.13" stroke="#ffffff" stroke-opacity="0.25"/>
  <text x="140" y="560" fill="#ffffff" opacity="0.68" font-family="Arial, sans-serif" font-size="34" font-weight="800">CARTES VENDUES</text>
  <text x="140" y="690" fill="#ffffff" font-family="Arial, sans-serif" font-size="142" font-weight="900">{cards}</text>
  <text x="140" y="850" fill="#ffffff" opacity="0.68" font-family="Arial, sans-serif" font-size="34" font-weight="800">CHIFFRE D'AFFAIRES</text>
  <text x="140" y="960" fill="#facc15" font-family="Arial, sans-serif" font-size="96" font-weight="900">{ca}</text>
  <text x="140" y="1110" fill="#ffffff" opacity="0.68" font-family="Arial, sans-serif" font-size="34" font-weight="800">BÉNÉFICE</text>
  <text x="140" y="1215" fill="#7dd3fc" font-family="Arial, sans-serif" font-size="90" font-weight="900">{profit}</text>
</g>
<text x="90" y="1470" fill="#ffffff" opacity="0.7" font-family="Arial, sans-serif" font-size="34" font-weight="800">MEILLEUR LOT</text>
<text x="90" y="1540" fill="#ffffff" font-family="Arial, sans-serif" font-size="44" font-weight="850">{lot_name}</text>
<rect x="80" y="1630" width="920" height="170" rx="42" fill="#22c55e" opacity="0.18" stroke="#bbf7d0" stroke-opacity="0.45"/>
<text x="130" y="1702" fill="#bbf7d0" font-family="Arial, sans-serif" font-size="34" font-weight="800">PROFIL</text>
<text x="130" y="1765" fill="#ffffff" font-family="Arial, sans-serif" font-size="58" font-weight="900">{profile_name}</text>
<text x="130" y="1830" fill="#ffffff" opacity="0.72" font-family="Arial, sans-serif" font-size="30" font-weight="700">{profile_line}</text>
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
            "kicker": "Dexify présente",
            "title": f"Ton année {year} en cartes",
            "big": "PokéStock Wrapped",
            "subtitle": "Installe-toi. On rembobine les lots, les ventes et les cartes qui ont fait ton année.",
            "body": _story_chips(
                [
                    ("Ventes", _number(stats_data.get("sales_count"))),
                    ("Cartes", _number(stats.get("cards_sold"))),
                    ("Profil", profile["name"]),
                ]
            ),
        },
        {
            "kicker": "Chiffre d'affaires",
            "title": "Tes cartes ont généré",
            "big": _money(stats.get("ca_total"), fp_func),
            "subtitle": "C'est le chiffre qui raconte le mieux le volume de ton année.",
            "body": _story_chips(
                [
                    ("Bénéfice", _money(stats.get("profit_total"), fp_func)),
                    ("Mois fort", best_month_label),
                ]
            ),
        },
        {
            "kicker": "Bénéfice",
            "title": "Ce qu'il reste vraiment",
            "big": _money(stats.get("profit_total"), fp_func),
            "subtitle": "La partie qui compte quand la poussière retombe.",
            "body": _story_chips(
                [
                    ("CA", _money(stats.get("ca_total"), fp_func)),
                    ("Négociation", _pct(stats.get("avg_negotiation_pct"))),
                ]
            ),
        },
        {
            "kicker": "Cartes vendues",
            "title": "Tu as fait partir",
            "big": _number(stats.get("cards_sold")),
            "subtitle": "cartes. Une par une, elles ont alimenté la machine.",
            "body": _story_chips(
                [
                    ("Ventes", _number(stats_data.get("sales_count"))),
                    ("Mois chaud", best_month_label),
                ]
            ),
        },
        {
            "kicker": "Mois chaud",
            "title": "Le mois qui a explosé",
            "big": best_month_label,
            "subtitle": "Celui où les ventes ont vraiment pris de la vitesse.",
            "body": _story_chips(
                [
                    ("CA", _money(best_month.get("ca"), fp_func)),
                    ("Cartes", _number(best_month.get("quantity"))),
                ]
            ),
        },
        {
            "kicker": "Carte MVP",
            "title": mvp_card.get("name", UNAVAILABLE),
            "big": fp_func(mvp_card.get("ca", 0)) if mvp_card else UNAVAILABLE,
            "subtitle": "Elle a pris la lumière. Ta carte MVP de l'année.",
            "body": _scene_visual(mvp_card, proxy_img_func, "Carte MVP indisponible")
            + _story_chips(
                [
                    ("Quantité", _number(mvp_card.get("quantity")) if mvp_card else UNAVAILABLE),
                    ("Bénéfice", fp_func(mvp_card.get("benef", 0)) if mvp_card else UNAVAILABLE),
                ]
            ),
        },
        {
            "kicker": "Meilleur coup",
            "title": "Celle-là t'a régalé",
            "big": _money(best_deal.get("benef"), fp_func) if best_deal else UNAVAILABLE,
            "subtitle": "Le plus beau différentiel achat / vente détecté cette année.",
            "body": _deal_panel(best_deal, fp_func, proxy_img_func),
        },
        {
            "kicker": "Trouvaille",
            "title": top_recovered.get("name", "Ta plus belle trouvaille") if top_recovered else "Ta plus belle trouvaille",
            "big": fp_func(top_recovered.get("value", 0)) if top_recovered else UNAVAILABLE,
            "subtitle": "La récupération qui ressort le plus fort dans les données.",
            "body": _scene_visual(top_recovered, proxy_img_func, "Top récupération indisponible")
            + _story_chips(
                [
                    ("Quantité", _number(top_recovered.get("quantity")) if top_recovered else UNAVAILABLE),
                    ("Lots achetés", _number(stats.get("lots_bought"))),
                ]
            ),
        },
        {
            "kicker": "Meilleur lot",
            "title": best_lot.get("lot", UNAVAILABLE) if best_lot else UNAVAILABLE,
            "big": fp_func(best_lot.get("benef", 0)) if best_lot else UNAVAILABLE,
            "subtitle": "Le lot qui a le mieux travaillé pour toi, sans faire de bruit.",
            "body": _scene_visual(best_lot, proxy_img_func, "Image du lot indisponible")
            + _story_chips(
                [
                    ("CA", fp_func(best_lot.get("ca", 0)) if best_lot else UNAVAILABLE),
                    ("Cartes", _number(best_lot.get("quantity")) if best_lot else UNAVAILABLE),
                ]
            ),
        },
        {
            "kicker": "Achat vs vente",
            "title": "Tu as mis en jeu",
            "big": _money(stats.get("purchase_total"), fp_func),
            "subtitle": "Et tu as transformé ça en ventes enregistrées sur l'année.",
            "body": _story_chips(
                [
                    ("Vendu", _money(stats.get("ca_total"), fp_func)),
                    ("Bénéfice", _money(stats.get("profit_total"), fp_func)),
                    ("Achat / cote", _pct(stats.get("avg_purchase_percent"))),
                ]
            ),
        },
        {
            "kicker": "Timeline",
            "title": "Quelques moments clés",
            "subtitle": "Pas un tableau. Juste les repères qui racontent l'année.",
            "body": _timeline_panel(timeline),
        },
        {
            "kicker": "Stock dormant",
            "title": "Tout n'est pas encore sorti",
            "big": _money(stock.get("value"), fp_func) if stock else UNAVAILABLE,
            "subtitle": "Il reste encore de la matière pour les prochains drops.",
            "body": _stock_panel(stock, fp_func, proxy_img_func),
        },
        {
            "kicker": "Profil",
            "title": "Ton profil PokéStock",
            "big": profile["name"],
            "subtitle": profile["line"],
            "body": _profile_panel(profile),
        },
        {
            "kicker": "Carte finale",
            "title": "À partager comme un vrai Wrapped",
            "subtitle": "Une carte verticale générée depuis tes données, prête à télécharger.",
            "body": _share_card_preview(stats, stats_data, fp_func, profile, best_lot),
            "is_final": True,
        },
    ]
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
                    <span>PokéStock présente</span>
                    <strong>PokéStock Wrapped</strong>
                    <em>Une story de ton année en cartes, ventes et lots marquants.</em>
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
        <section class="ps-wrapped-shell">
            <div class="ps-wrapped-orb"></div>
            <div class="ps-wrapped-hero">
                <div class="ps-wrapped-top">
                    <div>
                        <div class="ps-wrapped-brand">PokéStock Wrapped</div>
                    </div>
                    <div class="ps-wrapped-count">Slide {current + 1} / {total}</div>
                    <div class="ps-wrapped-progress"><span style="width:{progress}%"></span></div>
                </div>
                <div class="ps-wrapped-story">
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
        share_svg = _share_card_svg(stats, stats_data, fp_func, profile, best_lot)
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

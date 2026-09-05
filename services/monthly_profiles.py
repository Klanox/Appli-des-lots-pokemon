"""Deterministic monthly character scores. No changes to accounting aggregates."""

from calendar import monthrange
from datetime import datetime, timedelta
from math import log2, isfinite
from statistics import median

from services.inventory_ordering import card_acquisition_sort_key


PROFILES = {
    "investment": ("🌱", "Mois d’investissement", "#7c3aed", "Tu as consacré beaucoup plus d’argent que d’habitude au développement de ton stock.", "purchases"),
    "buyer": ("🛒", "Mois acheteur", "#0284c7", "Tu as acquis beaucoup plus de cartes que d’habitude ce mois-ci.", "acquired"),
    "volume": ("📦", "Mois de volume", "#0891b2", "Tu as vendu nettement plus de cartes que d’habitude ce mois-ci.", "qty"),
    "record": ("🏆", "Mois record", "#b45309", "Tu as réalisé ton meilleur chiffre d’affaires mensuel depuis le début du suivi.", "ca"),
    "calm": ("🌿", "Mois calme", "#64748b", "Ton activité de vente a été plus calme que d’habitude ce mois-ci.", "activity"),
    "premium": ("💎", "Mois premium", "#9333ea", "Les cartes que tu as vendues avaient une valeur moyenne particulièrement élevée.", "avg_card"),
    "profitable": ("💰", "Mois rentable", "#15803d", "Tu as généré un bénéfice particulièrement important ce mois-ci.", "benef"),
    "margin": ("📈", "Mois de marge", "#059669", "Tes ventes ont dégagé une marge particulièrement élevée ce mois-ci.", "margin"),
    "dynamic": ("⚡", "Mois dynamique", "#2563eb", "Tu as réalisé beaucoup plus de commandes que d’habitude ce mois-ci.", "transactions"),
    "rotation": ("🔄", "Mois de rotation", "#0d9488", "Les cartes vendues ce mois-ci ont trouvé preneur particulièrement vite après leur acquisition.", "rotation"),
    "efficient": ("🎯", "Mois efficace", "#16a34a", "Tu as généré beaucoup de bénéfice par rapport à l’argent investi.", "efficiency"),
    "negotiated": ("🤝", "Mois négocié", "#c2410c", "Une part importante de tes ventes s’est conclue après négociation.", "discount_share"),
}
PROFILE_METADATA = {key: dict(id=key, emoji=row[0], name=row[1], color=row[2], explanation=row[3], metric=row[4])
                    for key, row in PROFILES.items()}
PROFILE_EXPLANATIONS = {f'{row[0]} {row[1]}': row[3] for row in PROFILES.values()}


def _number(value):
    if isinstance(value, (set, list, tuple)):
        return float(len(value))
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def score_profile(current, history, *, record_allowed=False):
    """Log-ratio to the personal median; equal scores break by stable profile ID.

    Missing measurements never become zero. Two reference periods are needed
    (one is sufficient to establish a revenue record).
    Calm requires three jointly weak activity measures, not a fallback. Floors
    regularize zero medians (one unit/euro, one margin point, 5% for ratios).
    """
    scores = {}
    for key, meta in PROFILE_METADATA.items():
        if key == "calm" or (key == "record" and not record_allowed):
            continue
        metric = meta["metric"]
        value = _number(current.get(metric))
        refs = [_number(row.get(metric)) for row in history]
        refs = [v for v in refs if v is not None]
        if value is None or value <= 0 or len(refs) < (1 if key == "record" else 2):
            continue
        baseline = median(refs)
        floor = .05 if metric in ("efficiency", "discount_share", "rotation") else 1.0
        scale = max(abs(baseline), floor)
        excess = (value - baseline) / scale
        if excess > 0:
            scores[key] = log2(1 + excess)
    quiet = []
    for metric in ("ca", "qty", "transactions"):
        refs = [_number(row.get(metric)) for row in history]
        refs = [v for v in refs if v is not None]
        value = _number(current.get(metric))
        if len(refs) >= 2 and median(refs) > 0 and value is not None:
            quiet.append(value / median(refs))
    if len(quiet) == 3 and max(quiet) < .75:
        scores["calm"] = -log2(max(sum(quiet) / 3, .05))
    winner = max(scores, key=lambda key: (scores[key], key)) if scores else None
    return {"id": winner, "scores": scores, "metric": PROFILE_METADATA[winner]["metric"] if winner else None}


def profile_tuple(result):
    if not result or not result.get("id"):
        return None
    meta = PROFILE_METADATA[result["id"]]
    return f'{meta["emoji"]} {meta["name"]}', meta["explanation"]


def _window(month, now, comparable):
    start = datetime.strptime(month, "%Y-%m")
    end = start + timedelta(days=monthrange(start.year, start.month)[1]) - timedelta(microseconds=1)
    if comparable:
        elapsed = now - now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = min(end, start + elapsed)
    return start, min(end, now)


def build_profile_stats(monthly_stats, sales, purchases, lots, now, *, aggregate, is_system):
    """Derive only profile features; reuse the page's monetary/transaction totals.

    Rotation is inverse (1 + median acquisition-to-sale days), not sales volume.
    Price negotiation requires a captured suggested_price_at_sale, never today's
    card price. Physical sale IDs deduplicate Trade allocation rows.
    """
    acquisitions = []
    acquisition_by_sale = {}
    seen_cards = set()
    acquisitions_complete = True
    investment_complete = True
    for lot in lots:
        if not is_system(lot):
            missing_date, *_ = card_acquisition_sort_key({}, lot)
            if missing_date or _number(lot.get("prix_achat_reel", lot.get("prix_achat"))) is None:
                investment_complete = False
        for card in lot.get("cards", []):
            missing, acquired, *_ = card_acquisition_sort_key(card, lot)
            if missing:
                if not is_system(lot) and not card.get("received_by_exchange") and not card.get("stored_from_lot_uid"):
                    acquisitions_complete = False
                continue
            for sale in card.get("sold_entries", []):
                key = sale.get("sale_id") or id(sale)
                acquisition_by_sale[key] = acquired
            uid = card.get("card_uid") or id(card)
            if uid in seen_cards or is_system(lot) or card.get("received_by_exchange") or card.get("stored_from_lot_uid"):
                continue
            seen_cards.add(uid)
            acquisitions.append((acquired, max(int(card.get("quantity", 0) or 0), 0)))

    def features(month, comparable):
        start, end = _window(month, now, comparable)
        rows = [row for row in sales if start <= row["date"] <= end]
        result = aggregate(rows)
        if not rows:
            result["benef"] = 0.0
        if any(row.get("benef") is None for row in rows):
            result["benef"] = result["margin"] = None
        result["purchases"] = sum(row["cost"] for row in purchases if start <= row["date"] <= end) if purchases and investment_complete else None
        result["acquired"] = sum(qty for date, qty in acquisitions if start <= date <= end) if acquisitions and acquisitions_complete else None
        invested = result["purchases"]
        result["efficiency"] = result["benef"] / invested if invested and invested > 0 and result["benef"] is not None else None
        physical = {}
        for row in rows:
            if row.get("is_off_stock"):
                continue
            sale = row["sale"]
            physical.setdefault(sale.get("sale_id") or id(sale), row)
        delays, discounted, referenced = [], 0, 0
        for key, row in physical.items():
            acquired = acquisition_by_sale.get(key)
            if acquired and acquired <= row["date"]:
                delays.append((row["date"] - acquired).total_seconds() / 86400)
            sale = row["sale"]
            reference = _number(sale.get("suggested_price_at_sale"))
            if reference is not None and reference > 0:
                referenced += 1
                discounted += float(sale.get("price", 0)) < reference * max(int(sale.get("quantity", 1)), 1) - .01
        result["discount_share"] = discounted / referenced if referenced >= 3 else None
        result["rotation_days"] = median(delays) if len(delays) >= 3 and len(delays) >= .8 * len(physical) else None
        result["rotation"] = 1 / (1 + result["rotation_days"]) if result["rotation_days"] is not None else None
        if result["qty"] <= 0:
            result["avg_card"] = None
        return result

    current_month = now.strftime("%Y-%m")
    months = sorted(set(monthly_stats) | {current_month})
    full = {month: features(month, False) for month in months if month <= current_month}
    observed = {month: features(month, True) for month in full}
    result = {}
    first_observation = min((row["date"] for row in [*sales, *purchases]), default=now)
    for month in full:
        running = month == current_month
        reference = observed if running else full
        history = [row for key, row in reference.items() if key != month and key != current_month
                   and _window(key, now, running)[1] >= first_observation]
        previous_ca = [row["ca"] for key, row in full.items() if key != month and key != current_month]
        record = bool(previous_ca) and full[month]["ca"] > max(previous_ca) and full[month]["ca"] > 0
        selected = score_profile(reference[month], history, record_allowed=record)
        # Record always compares full realised CA, even when other axes are MTD.
        if running and record:
            full_history = [row for key, row in full.items() if key != current_month]
            record_score = score_profile(full[month], full_history, record_allowed=True)["scores"].get("record")
            if record_score is not None:
                selected["scores"]["record"] = record_score
                selected["id"] = max(selected["scores"], key=lambda key: (selected["scores"][key], key))
                selected["metric"] = PROFILE_METADATA[selected["id"]]["metric"]
        result[month] = {**reference[month], "_profile_result": selected}
    return result

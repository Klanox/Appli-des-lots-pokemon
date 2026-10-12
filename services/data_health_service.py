"""Data Health : detection d'anomalies dans les donnees PokeStock.

Ce module est LECTURE SEULE pour le scan (`scan_data_health`) : il ne modifie jamais les
donnees qu'on lui passe et n'ecrit aucun fichier. Les seules ecritures sont les corrections
explicites (`apply_fix`), declenchees un par un par l'utilisateur, toujours precedees d'une
sauvegarde du fichier concerne dans `backups/`.

Chaque anomalie est un dict :
  id          identifiant stable (sert de cle de bouton Streamlit)
  check       groupe : duplicates | drop_status | orphans | lots | sales
  kind        sous-type precis
  severity    error | warning | info
  title       titre court
  explanation texte clair : ce qui est suspect et pourquoi
  target      ou aller verifier : {"page", "lot_uid", "card_uid", "card_name", "drop_id", ...}
  fix         None, ou {"action", "label", "params"} quand une correction simple et sure existe
              (jamais pour une anomalie ambigue : plusieurs resolutions possibles)

Verifications :
  1. doublons de cartes a prix differents dans un meme lot (Stockage inclus)
  2. statut d'une carte du Drop incoherent avec ses champs (online_at, sold_at...)
  3. references orphelines (Drop, echanges, liens de vente) vers un lot / une carte absents
  4. lots sans carte, ou montant vendu disproportionne par rapport au prix paye
  5. ventes sans identifiant de transaction (hors historique ancien), lignes de transaction orphelines
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from datetime import datetime

from services.card_identity import card_identity_fingerprint
from services.vinted_drops_service import (
    DROP_ITEM_STATUSES,
    DROP_UNPROCESSED_STATUSES,
    drop_item_status,
    drop_is_archived,
    find_drop,
    find_drop_ref,
    remove_card_from_drop,
    set_drop_card_status,
)

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(APP_DIR, "backups")

# Un lot dont le montant vendu depasse RATIO_THRESHOLD x le prix paye (et au moins
# MIN_REVENUE_FOR_RATIO euros) est signale. Seuil volontairement large : seules les
# vraies disproportions (lot paye quelques euros, revendu 5 fois plus) ressortent.
RATIO_THRESHOLD = 5.0
MIN_REVENUE_FOR_RATIO = 20.0

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
CHECK_LABELS = {
    "duplicates": "Doublons à prix différents",
    "drop_status": "Statuts Drop incohérents",
    "orphans": "Références orphelines",
    "lots": "Lots suspects",
    "sales": "Ventes et transactions",
}


# --------------------------------------------------------------------------- utilitaires

def _s(value) -> str:
    return str(value or "").strip()


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _money(value) -> str:
    return f"{_num(value):.2f}".rstrip("0").rstrip(".").replace(".", ",") + " €"


def _make_id(*parts) -> str:
    raw = "|".join(_s(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _lots(data):
    return [lot for lot in (data or {}).get("lots", []) or [] if isinstance(lot, dict)]


def _cards(lot):
    return [card for card in (lot or {}).get("cards", []) or [] if isinstance(card, dict)]


def _is_storage(lot) -> bool:
    return bool(lot.get("is_storage") or lot.get("nom") == "Stockage")


def _is_trade(lot) -> bool:
    return bool(lot.get("is_trade") or lot.get("nom") in ("Trade", "🔄 Trade"))


def _is_collection_system(lot) -> bool:
    return bool(lot.get("is_collection_lot") or lot.get("nom") in ("Collection", "🧾 Collection"))


def _lot_name(lot) -> str:
    return _s(lot.get("nom")) or "Lot sans nom"


def _card_label(card) -> str:
    parts = [_s(card.get("name")) or "Carte sans nom"]
    number = _s(card.get("number"))
    if number:
        parts.append(f"#{number}")
    set_name = _s(card.get("set"))
    if set_name:
        parts.append(f"({set_name})")
    return " ".join(parts)


def _remaining_qty(card) -> int:
    return (
        _int(card.get("quantity"))
        - _int(card.get("sold_quantity"))
        - _int(card.get("exchange_out_quantity"))
    )


def _lot_revenue(lot) -> float:
    """Meme calcul que logic.cr (le CA affiche dans l'app)."""
    if _is_trade(lot):
        return 0.0
    total = 0.0
    for sale in lot.get("ventes", []) or []:
        total += _num((sale or {}).get("price"))
    for card in _cards(lot):
        for sale in card.get("sold_entries", []) or []:
            total += _num((sale or {}).get("price"))
    return total


def _lot_paid(lot) -> float:
    """Meme logique que logic.effective_purchase_price (lot mixte : prix reel paye)."""
    if lot.get("is_mixte"):
        return _num(lot.get("prix_achat_reel", lot.get("prix_achat")))
    return _num(lot.get("prix_achat"))


def _archive_index(archives):
    """lot_uid -> nom des lots archives, et noms de lots archives sans uid."""
    by_uid = {}
    names = set()
    for lot in archives or []:
        if not isinstance(lot, dict):
            continue
        uid = _s(lot.get("lot_uid"))
        if uid:
            by_uid[uid] = _lot_name(lot)
        names.add(_lot_name(lot))
    return by_uid, names


def _anomaly(check, kind, severity, title, explanation, target, fix=None, key_parts=()):
    return {
        "id": _make_id(check, kind, *key_parts),
        "check": check,
        "kind": kind,
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "target": target,
        "fix": fix,
    }


# --------------------------------------------------------------------------- 1. doublons

def _duplicate_key(card):
    return (card_identity_fingerprint(card), _s(card.get("condition")).casefold())


def check_duplicate_prices(data):
    """Meme carte (identite + variante + etat) presente plusieurs fois dans un lot avec des prix differents.

    - cle : empreinte d'identite (set, numero, nom, langue, reverse, 1ere edition, stamp, variante) + etat ;
    - prix : `suggested_price` (le prix que l'on modifie sur la carte) ;
    - seules les entrees encore en stock sont comparees (une entree entierement vendue n'a plus de prix a corriger) ;
    - les doublons AU MEME prix ne sont pas signales : ce sont ceux que `consolidate_storage_cards` fusionne.
    Ambigu par nature (quel prix garder ?) -> navigation seule, aucune correction automatique.
    """
    out = []
    for lot in _lots(data):
        if _is_trade(lot) or _is_collection_system(lot):
            continue
        groups = {}
        for card in _cards(lot):
            if _remaining_qty(card) <= 0 or card.get("is_collection_keep"):
                continue
            groups.setdefault(_duplicate_key(card), []).append(card)
        for (fingerprint, _condition), cards in groups.items():
            if len(cards) < 2:
                continue
            prices = sorted({round(_num(c.get("suggested_price")), 2) for c in cards})
            if len(prices) < 2:
                continue
            first = cards[0]
            lot_name = _lot_name(lot)
            detail = " / ".join(
                f"{_money(c.get('suggested_price'))} (x{max(_remaining_qty(c), 0)})" for c in cards
            )
            out.append(_anomaly(
                "duplicates", "duplicate_price", "warning",
                f"{_card_label(first)} : {len(cards)} entrées à prix différents",
                f"La même carte (même set, numéro, variante et état) apparaît {len(cards)} fois dans « {lot_name} » "
                f"avec des prix différents : {detail}. Une seule valeur devrait faire foi ; "
                f"le choix du bon prix est le tien, rien n'est corrigé automatiquement.",
                {
                    "page": "Lots",
                    "lot_uid": _s(lot.get("lot_uid")),
                    "lot_name": lot_name,
                    "card_uid": _s(first.get("card_uid")),
                    "card_name": _s(first.get("name")),
                    "message": f"{_card_label(first)} : {len(cards)} entrées à prix différents ({detail}).",
                },
                key_parts=(_s(lot.get("lot_uid")) or lot_name, fingerprint, _condition),
            ))
    return out


# --------------------------------------------------------------------------- 2. statuts Drop

def check_drop_status(drops):
    """Statut d'une reference de Drop en contradiction avec ses champs de date.

    Le statut affiche est `ref["status"]` ; les champs `online_at`, `listing_posted` et `sold_at`
    disent ce qui s'est reellement passe. Cas signales :
      - sold_at rempli mais statut non vendu -> statut attendu : sold ;
      - online_at / listing_posted rempli mais statut "pas encore traite" -> statut attendu : online.
    Correction proposee (sure) : aligner le statut sur les champs, sans toucher aux dates.
    Cas inverses (statut sold/online sans date) : navigation seule, la bonne date n'est pas devinable.
    """
    out = []
    for drop in (drops or {}).get("drops", []) or []:
        drop_id = _s(drop.get("id"))
        drop_name = _s(drop.get("name")) or "Drop sans nom"
        archived = " (archivé)" if drop_is_archived(drop) else ""
        for ref in drop.get("cards", []) or []:
            status = _s(ref.get("status"))
            if status not in DROP_ITEM_STATUSES:
                continue
            sold_at = _s(ref.get("sold_at"))
            online_at = _s(ref.get("online_at"))
            posted = bool(ref.get("listing_posted"))
            expected = None
            reason = ""
            if sold_at and status != "sold":
                expected = "sold"
                reason = f"`sold_at` est rempli ({sold_at[:10]}) alors que le statut est « {DROP_ITEM_STATUSES[status]} »"
            elif (online_at or posted) and status in (DROP_UNPROCESSED_STATUSES | {"draft_ready"}) and not sold_at:
                expected = "online"
                what = f"`online_at` est rempli ({online_at[:10]})" if online_at else "l'annonce est marquée publiée"
                reason = f"{what} alors que le statut est « {DROP_ITEM_STATUSES[status]} »"
            item_id = _s(ref.get("drop_item_id"))
            label = _card_label(ref)
            target = {
                "page": "Archivés" if drop_is_archived(drop) else "Annonces Vinted",
                "drop_id": drop_id,
                "drop_item_id": item_id,
                "card_uid": _s(ref.get("card_uid")),
                "card_name": _s(ref.get("name")),
                "message": f"{label} dans « {drop_name} » : statut incohérent.",
            }
            if expected:
                fix = None
                if item_id:
                    fix = {
                        "action": "drop_set_status",
                        "label": f"Passer le statut à « {DROP_ITEM_STATUSES[expected]} »",
                        "params": {"drop_id": drop_id, "drop_item_id": item_id, "from_status": status, "to_status": expected},
                    }
                out.append(_anomaly(
                    "drop_status", "status_vs_dates", "warning",
                    f"{label} : statut Drop incohérent",
                    f"Dans « {drop_name} »{archived}, {reason}. La carte est donc comptée comme non traitée "
                    f"alors que ses dates montrent le contraire. Statut attendu : « {DROP_ITEM_STATUSES[expected]} ».",
                    target, fix, key_parts=(drop_id, item_id or label, status),
                ))
            elif status == "sold" and not sold_at:
                out.append(_anomaly(
                    "drop_status", "sold_without_date", "warning",
                    f"{label} : vendue sans date de vente",
                    f"Dans « {drop_name} »{archived}, le statut est « Vendue » mais `sold_at` est vide : "
                    f"la date de vente n'est pas devinable automatiquement, à vérifier dans l'historique des ventes.",
                    target, None, key_parts=(drop_id, item_id or label, "sold_without_date"),
                ))
            elif status == "online" and not online_at and not posted:
                out.append(_anomaly(
                    "drop_status", "online_without_date", "warning",
                    f"{label} : en ligne sans date de publication",
                    f"Dans « {drop_name} »{archived}, le statut est « En ligne » mais ni `online_at` ni "
                    f"`listing_posted` ne sont renseignés. À vérifier sur Vinted avant de corriger.",
                    target, None, key_parts=(drop_id, item_id or label, "online_without_date"),
                ))
    return out


# --------------------------------------------------------------------------- 3. orphelins

def check_orphans(data, drops, archives):
    """References vers un `lot_uid` / `card_uid` qui n'existe plus dans data.json.

    - references de Drop : (lot_uid, card_uid) cherches dans data.json. Si le lot est dans
      lots_archives.json, ce n'est PAS une erreur (carte d'un lot archive) : signalement "info",
      navigation vers Archivés. Sinon : orpheline reelle ;
    - historique d'echanges (trade_history) et contributeurs de cartes recues par echange :
      `lot_uid` introuvable ni dans data.json ni dans les archives ;
    - ventes liees a un Drop (`drop_id` / `drop_item_id`) vers un Drop ou une reference disparus.
    Correction sure uniquement pour une reference de Drop NON vendue (retrait de la reference).
    """
    out = []
    lots = _lots(data)
    lot_uids = {_s(l.get("lot_uid")) for l in lots if _s(l.get("lot_uid"))}
    cards_by_lot = {_s(l.get("lot_uid")): {_s(c.get("card_uid")) for c in _cards(l) if _s(c.get("card_uid"))}
                    for l in lots if _s(l.get("lot_uid"))}
    all_card_uids = set().union(*cards_by_lot.values()) if cards_by_lot else set()
    archived_uids, _archived_names = _archive_index(archives)
    archived_card_uids = {_s(c.get("card_uid")) for l in archives or [] if isinstance(l, dict) for c in _cards(l)
                          if _s(c.get("card_uid"))}

    drop_ids = set()
    drop_item_ids = set()
    for drop in (drops or {}).get("drops", []) or []:
        drop_ids.add(_s(drop.get("id")))
        for ref in drop.get("cards", []) or []:
            if _s(ref.get("drop_item_id")):
                drop_item_ids.add(_s(ref.get("drop_item_id")))

    # --- references de Drop
    for drop in (drops or {}).get("drops", []) or []:
        drop_id = _s(drop.get("id"))
        drop_name = _s(drop.get("name")) or "Drop sans nom"
        archived_drop = " (archivé)" if drop_is_archived(drop) else ""
        for ref in drop.get("cards", []) or []:
            card_uid = _s(ref.get("card_uid"))
            lot_uid = _s(ref.get("lot_uid"))
            if not card_uid:
                continue  # ancienne reference sans identifiant : non verifiable par uid
            if lot_uid in cards_by_lot and card_uid in cards_by_lot[lot_uid]:
                continue
            if not lot_uid and card_uid in all_card_uids:
                continue
            item_id = _s(ref.get("drop_item_id"))
            label = _card_label(ref)
            status = drop_item_status(ref)
            in_archive = lot_uid in archived_uids or (not lot_uid and card_uid in archived_card_uids)
            base_target = {
                "drop_id": drop_id, "drop_item_id": item_id, "card_uid": card_uid,
                "card_name": _s(ref.get("name")), "lot_uid": lot_uid,
            }
            if in_archive:
                lot_label = archived_uids.get(lot_uid, "lot archivé")
                out.append(_anomaly(
                    "orphans", "drop_ref_archived_lot", "info",
                    f"{label} : carte d'un lot archivé",
                    f"La référence du Drop « {drop_name} »{archived_drop} (statut « {DROP_ITEM_STATUSES.get(status, status)} ») "
                    f"pointe vers une carte qui n'est plus dans data.json parce que son lot « {lot_label} » a été archivé "
                    f"(lots_archives.json). Ce n'est pas une erreur : la référence garde l'historique du Drop. "
                    f"Rien à corriger ; la carte est consultable dans Archivés.",
                    {**base_target, "page": "Archivés", "message": f"{label} : carte du lot archivé « {lot_label} »."},
                    None, key_parts=(drop_id, item_id or card_uid),
                ))
                continue
            lot_exists = lot_uid in lot_uids
            if lot_exists:
                why = (f"le lot existe encore mais la carte (`card_uid` {card_uid[:14]}…) n'y figure plus")
            else:
                why = f"ni le lot (`lot_uid` {lot_uid[:14] or 'vide'}…) ni la carte n'existent dans data.json ou les archives"
            fix = None
            if status != "sold" and item_id:
                fix = {
                    "action": "drop_remove_ref",
                    "label": "Retirer cette référence du Drop",
                    "params": {"drop_id": drop_id, "drop_item_id": item_id, "card_uid": card_uid},
                }
            sold_note = ""
            if status == "sold":
                sold_note = " La référence est « Vendue » : la retirer effacerait la trace de la vente dans les stats du Drop, donc aucune correction automatique."
            out.append(_anomaly(
                "orphans", "drop_ref_orphan", "error",
                f"{label} : référence Drop orpheline",
                f"La référence du Drop « {drop_name} »{archived_drop} (statut « {DROP_ITEM_STATUSES.get(status, status)} ») "
                f"est orpheline : {why}.{sold_note}",
                {**base_target, "page": "Archivés" if drop_is_archived(drop) else "Annonces Vinted",
                 "message": f"{label} : référence orpheline dans « {drop_name} »."},
                fix, key_parts=(drop_id, item_id or card_uid),
            ))

    # --- historique d'echanges
    known_lot_uids = lot_uids | set(archived_uids)
    for trade in (data or {}).get("trade_history", []) or []:
        if not isinstance(trade, dict):
            continue
        missing = set()
        for group in ("given_cards", "received_cards"):
            for card in trade.get(group, []) or []:
                if not isinstance(card, dict):
                    continue
                for uid in [_s(card.get("lot_uid"))] + [_s(c.get("lot_uid")) for c in card.get("contributors", []) or []
                                                          if isinstance(c, dict)]:
                    if uid and uid not in known_lot_uids:
                        missing.add(uid)
        if missing:
            exchange_id = _s(trade.get("exchange_id")) or _s(trade.get("date"))
            out.append(_anomaly(
                "orphans", "trade_orphan_lot", "warning",
                f"Échange {exchange_id[:24]} : lot introuvable",
                f"L'échange du {_s(trade.get('date'))[:10]} référence {len(missing)} lot(s) absent(s) de data.json et des archives "
                f"({', '.join(sorted(u[:14] + '…' for u in missing))}). Les calculs de coût de cet échange peuvent être faussés.",
                {"page": "Historique", "message": f"Échange {exchange_id} : lot introuvable."},
                None, key_parts=(exchange_id,),
            ))

    # --- ventes liees a un Drop disparu
    for lot in lots:
        for card in _cards(lot):
            for sale in card.get("sold_entries", []) or []:
                drop_id = _s((sale or {}).get("drop_id"))
                item_id = _s((sale or {}).get("drop_item_id"))
                if not drop_id and not item_id:
                    continue
                if drop_id and drop_id not in drop_ids:
                    reason = f"le Drop « {_s(sale.get('drop_name')) or drop_id[:10]} » n'existe plus"
                elif item_id and item_id not in drop_item_ids:
                    reason = "la référence de carte du Drop n'existe plus"
                else:
                    continue
                label = _card_label(card)
                out.append(_anomaly(
                    "orphans", "sale_drop_link_orphan", "warning",
                    f"{label} : vente liée à un Drop disparu",
                    f"La vente du {_s(sale.get('date'))[:10]} ({_money(sale.get('price'))}) de « {_lot_name(lot)} » est liée à un Drop, "
                    f"mais {reason}. Les stats du Drop ne la comptent plus.",
                    {"page": "Lots", "lot_uid": _s(lot.get("lot_uid")), "lot_name": _lot_name(lot),
                     "card_uid": _s(card.get("card_uid")), "card_name": _s(card.get("name")),
                     "message": f"{label} : vente liée à un Drop disparu."},
                    None, key_parts=(_s(sale.get("sale_id")) or _s(sale.get("date")), _s(card.get("card_uid"))),
                ))
    return out


# --------------------------------------------------------------------------- 4. lots

def check_lots(data):
    """Lots sans aucune carte, ou montant vendu disproportionne par rapport au prix paye.

    - lot vide : `cards` vide, hors lots systeme (Stockage, Trade, Collection) ;
    - disproportion : CA (meme calcul que l'app, `logic.cr`) > RATIO_THRESHOLD x prix paye, prix paye > 0
      et CA >= MIN_REVENUE_FOR_RATIO. Peut etre legitime (lot tres rentable) ou signaler un prix
      d'achat oublie / une vente mal saisie : navigation seule.
    """
    out = []
    for lot in _lots(data):
        if _is_trade(lot) or _is_storage(lot) or _is_collection_system(lot):
            continue
        name = _lot_name(lot)
        uid = _s(lot.get("lot_uid"))
        target = {"page": "Lots", "lot_uid": uid, "lot_name": name}
        if not _cards(lot):
            out.append(_anomaly(
                "lots", "lot_empty", "warning", f"{name} : lot sans carte",
                f"Le lot « {name} » ne contient aucune carte (prix payé {_money(_lot_paid(lot))}, "
                f"{_money(_lot_revenue(lot))} de ventes enregistrées). Lot créé sans cartes, cartes supprimées par erreur, "
                f"ou lot à archiver ?",
                {**target, "message": f"{name} : lot sans carte."}, None, key_parts=(uid or name, "empty"),
            ))
        paid = _lot_paid(lot)
        revenue = _lot_revenue(lot)
        if paid > 0 and revenue >= MIN_REVENUE_FOR_RATIO and revenue > RATIO_THRESHOLD * paid:
            ratio = revenue / paid
            out.append(_anomaly(
                "lots", "lot_revenue_ratio", "warning", f"{name} : ventes très supérieures au prix payé",
                f"Le lot « {name} » a rapporté {_money(revenue)} pour {_money(paid)} payés (×{ratio:.1f}, seuil d'alerte ×{RATIO_THRESHOLD:g}). "
                f"C'est possible pour un très bon lot, mais cela signale souvent un prix d'achat oublié ou incomplet, "
                f"ou une vente saisie avec le mauvais montant.",
                {**target, "message": f"{name} : {_money(revenue)} vendus pour {_money(paid)} payés (×{ratio:.1f})."},
                None, key_parts=(uid or name, "ratio"),
            ))
    return out


# --------------------------------------------------------------------------- 5. ventes / transactions

def _iter_sale_lines(data):
    """Toutes les lignes de vente : (kind, lot, card|None, sale)."""
    for lot in _lots(data):
        for card in _cards(lot):
            for sale in card.get("sold_entries", []) or []:
                if isinstance(sale, dict):
                    yield "card_sale", lot, card, sale
        for sale in lot.get("ventes", []) or []:
            # Les lignes "[Echange] Allocation CA ..." sont de la comptabilite derivee d'un echange,
            # pas des ventes de panier : elles n'ont jamais de sale_transaction_id.
            if (isinstance(sale, dict) and not sale.get("is_lot_sale") and _s(sale.get("card_name")) != "Vente initiale"
                    and not sale.get("is_exchange_benefit") and not sale.get("is_exchange_allocation")):
                yield "off_stock_sale", lot, None, sale
    for sale in (data or {}).get("ventes_hors_stock", []) or []:
        if isinstance(sale, dict):
            yield "off_stock_sale", None, None, sale


def transaction_cutoffs(data):
    """Date (AAAA-MM-JJ) a partir de laquelle chaque type de vente recoit un `sale_transaction_id`.

    `sale_transaction_id` n'existe que sur les ventes recentes (ajoute apres coup). Les ventes plus
    anciennes n'ont jamais eu d'identifiant : les signaler serait du bruit. Le seuil est donc, par type de
    vente, la date de la PLUS ANCIENNE vente qui en possede un.
    """
    cutoffs = {}
    for kind, _lot, _card, sale in _iter_sale_lines(data):
        if _s(sale.get("sale_transaction_id")):
            day = _s(sale.get("date"))[:10]
            if day and (kind not in cutoffs or day < cutoffs[kind]):
                cutoffs[kind] = day
    return cutoffs


def check_sales(data, brocantes=None, archives=None):
    """Ventes sans transaction, lignes de transaction orphelines.

    - une "transaction" est le groupe de ventes d'un meme panier, relie par `sale_transaction_id` ;
    - vente sans `sale_transaction_id` datee APRES le seuil de `transaction_cutoffs` -> anomalie
      (l'annulation de vente ne pourra plus retrouver le reste du panier). Correction sure : attribuer un
      identifiant propre a la vente (comportement historique : une vente = une transaction) ;
    - ligne orpheline : `card_uid` / `lot_uid` de la vente different de la carte / du lot qui la porte, ou
      vente hors stock dont `source_lot_id` ne correspond a aucun lot (data.json + archives) ;
    - vente de brocante dont `brocante_id` n'existe plus dans brocantes.json.
    """
    out = []
    cutoffs = transaction_cutoffs(data)
    lots = _lots(data)
    known_lot_uids = {_s(l.get("lot_uid")) for l in lots if _s(l.get("lot_uid"))}
    archived_uids, _names = _archive_index(archives)
    known_lot_uids |= set(archived_uids)
    session_ids = {_s(s.get("id")) for s in (brocantes or {}).get("sessions", []) or [] if isinstance(s, dict)}
    kind_label = {"card_sale": "vente de carte", "off_stock_sale": "vente hors stock"}
    kind_plural = {"card_sale": "ventes de cartes", "off_stock_sale": "ventes hors stock"}
    missing_groups = {}

    for kind, lot, card, sale in _iter_sale_lines(data):
        day = _s(sale.get("date"))[:10]
        sale_id = _s(sale.get("sale_id"))
        name = _s(sale.get("card_name")) or (_card_label(card) if card else "Vente")
        lot_name = _lot_name(lot) if lot else "hors lot"
        lot_uid = _s(lot.get("lot_uid")) if lot else ""
        if card is not None:
            target = {"page": "Lots", "lot_uid": lot_uid, "lot_name": lot_name,
                      "card_uid": _s(card.get("card_uid")), "card_name": _s(card.get("name"))}
        else:
            target = {"page": "Historique", "lot_uid": lot_uid, "lot_name": lot_name}
        sale_key = sale_id or f"{day}|{name}|{sale.get('price')}"

        # --- vente recente sans identifiant de transaction (regroupee par panier plus bas)
        if (not _s(sale.get("sale_transaction_id")) and not sale.get("is_exchange") and kind in cutoffs
                and day and day >= cutoffs[kind]):
            group_key = (kind, _s(sale.get("canal")), _s(sale.get("date"))[:19])
            missing_groups.setdefault(group_key, []).append((lot, card, sale, name, target))

        # --- lignes de transaction orphelines / incoherentes
        if card is not None:
            line_issues = []
            sale_card_uid = _s(sale.get("card_uid"))
            sale_lot_uid = _s(sale.get("lot_uid"))
            if sale_card_uid and sale_card_uid != _s(card.get("card_uid")):
                line_issues.append(f"`card_uid` de la vente ({sale_card_uid[:14]}…) ≠ celui de la carte qui la porte")
            if sale_lot_uid and lot_uid and sale_lot_uid != lot_uid:
                line_issues.append(f"`lot_uid` de la vente ({sale_lot_uid[:14]}…) ≠ celui du lot qui la porte")
            if line_issues:
                out.append(_anomaly(
                    "sales", "sale_line_mismatch", "warning",
                    f"{name} : ligne de vente incohérente",
                    f"Dans « {lot_name} », la vente du {day} ({_money(sale.get('price'))}) est incohérente : "
                    f"{' ; '.join(line_issues)}. Une annulation ou un regroupement par transaction pourrait viser la mauvaise ligne.",
                    {**target, "message": f"{name} : ligne de vente incohérente."}, None, key_parts=(sale_key, "mismatch"),
                ))
        else:
            source = _s(sale.get("source_lot_id"))
            if source and source not in known_lot_uids:
                out.append(_anomaly(
                    "sales", "offstock_source_orphan", "warning",
                    f"{name} : vente hors stock liée à un lot introuvable",
                    f"La vente hors stock du {day} ({_money(sale.get('price'))}) est rattachée au lot `{source[:14]}…` "
                    f"(« {_s(sale.get('source_lot_name')) or 'nom inconnu'} »), absent de data.json et des archives.",
                    {**target, "message": f"{name} : lot source introuvable."}, None, key_parts=(sale_key, "source"),
                ))
        brocante_id = _s(sale.get("brocante_id"))
        if brocante_id and brocantes is not None and brocante_id not in session_ids:
            out.append(_anomaly(
                "sales", "sale_brocante_orphan", "warning",
                f"{name} : vente liée à une brocante introuvable",
                f"La vente du {day} ({_money(sale.get('price'))}) est rattachée à la brocante `{brocante_id[:14]}…` qui n'existe plus "
                f"dans brocantes.json : elle n'apparaîtra dans aucun bilan de brocante.",
                {"page": "Brocante", "lot_uid": lot_uid, "lot_name": lot_name, "message": f"{name} : brocante introuvable."},
                None, key_parts=(sale_key, "brocante"),
            ))

    # --- ventes sans transaction : un panier = les ventes de meme canal enregistrees a la meme seconde
    for (kind, _canal, stamp), lines in missing_groups.items():
        names = ", ".join(line[3] for line in lines)
        total = sum(_num(line[2].get("price")) for line in lines)
        sale_ids = [_s(line[2].get("sale_id")) for line in lines]
        lot_names = sorted({_lot_name(line[0]) if line[0] else "hors lot" for line in lines})
        fix = None
        if all(sale_ids) and len(set(sale_ids)) == len(sale_ids):
            fix = {
                "action": "sale_assign_transaction",
                "label": ("Regrouper ces %d ventes sous un même identifiant de transaction" % len(lines))
                         if len(lines) > 1 else "Attribuer un identifiant de transaction à cette vente",
                "params": {"sale_ids": sale_ids},
            }
        many = len(lines) > 1
        out.append(_anomaly(
            "sales", "sale_without_transaction", "warning",
            f"{names} : {len(lines)} {kind_plural[kind] if many else kind_label[kind]} sans transaction",
            f"{'Ces ' + str(len(lines)) + ' ' + kind_plural[kind] + ' (' + names + ')' if many else 'La ' + kind_label[kind] + ' « ' + names + ' »'} "
            f"du {stamp[:10]} ({_money(total)}, lot « {' / '.join(lot_names)} ») "
            f"{'n' + chr(39) + 'ont' if many else 'n' + chr(39) + 'a'} pas de `sale_transaction_id`, alors que toutes les {kind_plural[kind]} "
            f"depuis le {cutoffs[kind]} en ont un. Sans lui, l'annulation ou l'historique ne peut pas retrouver "
            f"le panier d'origine. Correction proposée : "
            f"{'les regrouper sous un identifiant commun (même seconde, même canal : c' + chr(39) + 'est un seul panier)' if many else 'lui attribuer un identifiant propre'}.",
            {**lines[0][4], "message": f"{names} : {'ventes' if many else 'vente'} du {stamp[:10]} sans transaction."},
            fix, key_parts=(kind, stamp, *sale_ids),
        ))
    return out


# --------------------------------------------------------------------------- scan global

def scan_data_health(data, drops, archives=None, brocantes=None):
    """Lance les 5 verifications. Ne modifie rien. Retourne {"anomalies", "counts", "scanned_at", "cutoffs"}."""
    data = data or {}
    drops = drops or {"drops": []}
    archives = archives or []
    anomalies = []
    anomalies += check_duplicate_prices(data)
    anomalies += check_drop_status(drops)
    anomalies += check_orphans(data, drops, archives)
    anomalies += check_lots(data)
    anomalies += check_sales(data, brocantes, archives)
    anomalies.sort(key=lambda a: (SEVERITY_ORDER.get(a["severity"], 9), list(CHECK_LABELS).index(a["check"])))
    counts = {check: 0 for check in CHECK_LABELS}
    for item in anomalies:
        counts[item["check"]] += 1
    return {
        "anomalies": anomalies,
        "counts": counts,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "cutoffs": transaction_cutoffs(data),
    }


def load_archives(path=None):
    path = path or os.path.join(APP_DIR, "lots_archives.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    return payload if isinstance(payload, list) else []


# --------------------------------------------------------------------------- corrections

def backup_file(path, backup_dir=None, tag="datahealth"):
    """Copie `path` dans backups/ AVANT toute modification. Retourne le chemin de la sauvegarde."""
    backup_dir = backup_dir or BACKUP_DIR
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = os.path.join(backup_dir, f"{os.path.basename(path)}.backup_{stamp}_{tag}")
    counter = 1
    while os.path.exists(target):
        counter += 1
        target = os.path.join(backup_dir, f"{os.path.basename(path)}.backup_{stamp}_{tag}{counter}")
    shutil.copy2(path, target)
    return target


def _fix_drop_set_status(params, *, load_drops, save_drops, drops_path, backup_dir):
    drops = load_drops()
    drop = find_drop(drops, params["drop_id"])
    ref = find_drop_ref(drop, params["drop_item_id"]) if drop else None
    if ref is None:
        return False, "Référence introuvable : la carte a changé depuis le scan, relance un scan."
    if _s(ref.get("status")) != params["from_status"]:
        return False, "Le statut a déjà changé depuis le scan, relance un scan."
    backup = backup_file(drops_path, backup_dir)
    to_status = params["to_status"]
    # Aligne le statut sans ecraser aucune date existante (set_drop_card_status ne remplit que les dates vides).
    # Si seule la case "annonce publiee" etait cochee, on reprend sa date plutot que l'heure actuelle.
    if to_status == "online" and not _s(ref.get("online_at")) and _s(ref.get("listing_posted_at")):
        ref["online_at"] = ref["listing_posted_at"]
    set_drop_card_status(drops, params["drop_id"], params["drop_item_id"], to_status)
    save_drops(drops)
    return True, f"Statut passé à « {DROP_ITEM_STATUSES[to_status]} ». Sauvegarde : {os.path.basename(backup)}"


def _fix_drop_remove_ref(params, *, load_drops, save_drops, drops_path, backup_dir):
    drops = load_drops()
    drop = find_drop(drops, params["drop_id"])
    ref = find_drop_ref(drop, params["drop_item_id"]) if drop else None
    if ref is None:
        return False, "Référence introuvable : déjà retirée ou modifiée, relance un scan."
    if drop_item_status(ref) == "sold":
        return False, "Référence vendue : retrait refusé."
    if _s(ref.get("card_uid")) != params["card_uid"]:
        return False, "La référence ne correspond plus à celle du scan, relance un scan."
    backup = backup_file(drops_path, backup_dir)
    remove_card_from_drop(drops, params["drop_id"], params["drop_item_id"])
    save_drops(drops)
    return True, f"Référence retirée du Drop. Sauvegarde : {os.path.basename(backup)}"


def _fix_sale_assign_transaction(params, *, load_data, save_data, data_path, backup_dir):
    data = load_data()
    wanted = list(params["sale_ids"])
    found = []
    for _kind, _lot, _card, sale in _iter_sale_lines(data):
        if _s(sale.get("sale_id")) in wanted:
            found.append(sale)
    if len(found) != len(wanted):
        return False, "Vente introuvable ou ambiguë : relance un scan."
    if any(_s(sale.get("sale_transaction_id")) for sale in found):
        return False, "Une de ces ventes a déjà un identifiant de transaction, relance un scan."
    backup = backup_file(data_path, backup_dir)
    tx_id = f"sale_tx_{hashlib.sha1('|'.join(sorted(wanted)).encode()).hexdigest()[:32]}"
    for sale in found:
        sale["sale_transaction_id"] = tx_id
    save_data(data)
    return True, f"Identifiant de transaction attribué à {len(found)} vente(s). Sauvegarde : {os.path.basename(backup)}"


def apply_fix(fix, *, load_data, save_data, load_drops, save_drops, data_path, drops_path, backup_dir=None):
    """Applique UNE correction. Retourne (ok, message).

    Chaque correction recharge les donnees fraiches, reverifie que l'anomalie existe toujours (sinon
    abandon), sauvegarde le fichier concerne dans backups/, puis ecrit via les fonctions de sauvegarde
    normales de l'application (donc avec leurs protections et la synchro cloud).
    """
    action = (fix or {}).get("action")
    params = copy.deepcopy((fix or {}).get("params") or {})
    try:
        if action == "drop_set_status":
            return _fix_drop_set_status(params, load_drops=load_drops, save_drops=save_drops,
                                        drops_path=drops_path, backup_dir=backup_dir)
        if action == "drop_remove_ref":
            return _fix_drop_remove_ref(params, load_drops=load_drops, save_drops=save_drops,
                                        drops_path=drops_path, backup_dir=backup_dir)
        if action == "sale_assign_transaction":
            return _fix_sale_assign_transaction(params, load_data=load_data, save_data=save_data,
                                                data_path=data_path, backup_dir=backup_dir)
    except Exception as exc:  # une correction ne doit jamais faire planter la page
        return False, f"Correction impossible : {exc}"
    return False, "Correction inconnue."

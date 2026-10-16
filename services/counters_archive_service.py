"""Reset annuel automatique des compteurs, avec archivage de l'année écoulée.

Les archives sont rangées dans counters.json, sous la clé réservée ``_archive`` :

    "_archive": {
        "last_reset_year": 2027,            # année pour laquelle les compteurs sont actuellement en cours
        "years": {
            "2026": {
                "reset_on": "2027-01-01",   # date théorique du reset (pas d'heure : même contenu sur tous les appareils)
                "channels": {
                    "main_brocante": {"label", "ca", "ca_ventes", "nb", "init_ca", "start_date"},
                    "dexify": {...}, "pokedeal": {...}, "choppetacarte": {...},
                },
            },
        },
    }

Principe :
- le reset est déclenché paresseusement (début des pages Compteurs et Statistiques) et reste idempotent :
  il ne fait rien tant que ``last_reset_year`` vaut l'année en cours ;
- les totaux de l'année écoulée sont recalculés depuis les ventes, par fenêtre de dates du 01/01 au 31/12,
  avec les mêmes règles de comptage que les cartes de la page Compteurs ;
- l'archive et le reset partent dans UNE SEULE écriture (``write_func``) : si elle échoue, rien ne change ;
- si l'appli n'a pas été ouverte pendant plusieurs années, chaque année manquée est archivée.

La date du jour est toujours passée en paramètre (aucun appel à l'horloge ici).
"""

from __future__ import annotations

import copy
import json
import os

from services.vinted_channels import VINTED_CHANNELS, vinted_channel_key


ARCHIVE_KEY = "_archive"
MAIN_COUNTER_KEY = "main_brocante"
MAIN_COUNTER_LABEL = "Main propre & Brocante"


def vinted_counter_keys():
    return [vinted_channel_key(channel) for channel in VINTED_CHANNELS]


def _parse_year(value):
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 9999 else None


def _round2(value):
    return round(float(value or 0.0), 2)


def _float(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _archive_block(counters):
    block = counters.get(ARCHIVE_KEY) if isinstance(counters, dict) else None
    return block if isinstance(block, dict) else {}


def counters_need_reset(counters, today):
    """Vrai s'il faut initialiser le marqueur ou archiver au moins une année (test peu coûteux)."""
    if not isinstance(counters, dict):
        return False
    marker = _parse_year(_archive_block(counters).get("last_reset_year"))
    return marker is None or marker < today.year


def read_json_list(path):
    """Lit une liste JSON (lots_archives.json) ; liste vide si le fichier est absent ou illisible."""
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def make_lots_loader(ld_func, archives_path="lots_archives.json"):
    """Retourne une fonction paresseuse : lots courants + lots archivés (comme la page Compteurs)."""
    def load():
        return list((ld_func() or {}).get("lots", [])) + read_json_list(archives_path)
    return load


def _window_state(state, year):
    """Début de fenêtre d'un canal Vinted pour ``year``, avec les règles de la page Compteurs.

    Si start_datetime contient un « T », il prime sur start_date (comme à l'affichage). La fenêtre ne
    remonte jamais avant le 1er janvier de ``year``.
    """
    jan1 = f"{year}-01-01"
    start_date = str(state.get("start_date") or jan1)
    start_dt = str(state.get("start_datetime") or start_date)
    if "T" in start_dt:
        effective = start_dt if start_dt[:10] >= jan1 else jan1
    else:
        effective = start_date[:10] if start_date[:10] >= jan1 else jan1
    return {"start_date": effective[:10], "start_datetime": effective}


def _archive_year(counters, lots, year):
    """Entrée d'archive de ``year`` : totaux par canal, calculés par fenêtre de dates."""
    from ui.pages.counters import collect_channel_counter_totals  # import tardif : évite un import circulaire

    vinted_keys = [key for key in vinted_counter_keys() if isinstance(counters.get(key), dict)]
    states = {key: _window_state(counters[key], year) for key in vinted_keys}
    totals = collect_channel_counter_totals(
        lots,
        vinted_states=states,
        main_year=str(year),
        end_date=f"{year}-12-31",
    )
    channels = {}
    main_state = counters.get(MAIN_COUNTER_KEY)
    if isinstance(main_state, dict):
        main_total = totals[MAIN_COUNTER_KEY]
        channels[MAIN_COUNTER_KEY] = {
            "label": main_state.get("label") or MAIN_COUNTER_LABEL,
            # Comme la carte : Main propre & Brocante n'ajoute jamais de CA de départ.
            "ca": _round2(main_total["ca"]),
            "ca_ventes": _round2(main_total["ca"]),
            "nb": int(main_total["nb"]),
            "init_ca": _round2(_float(main_state.get("init_ca"))),
            "start_date": main_state.get("start_date"),
        }
    for key in vinted_keys:
        state = counters[key]
        init_ca = _float(state.get("init_ca"))
        sales_ca = totals[key]["ca"]
        channels[key] = {
            "label": state.get("label") or key,
            "ca": _round2(sales_ca + init_ca),  # total affiché sur la carte : ventes + CA de départ
            "ca_ventes": _round2(sales_ca),
            "nb": int(totals[key]["nb"]),
            "init_ca": _round2(init_ca),
            "start_date": state.get("start_date"),
        }
    return {"reset_on": f"{year + 1}-01-01", "channels": channels}


def _reset_counters(counters, new_year):
    """Remet les compteurs à zéro pour ``new_year`` : init_ca à 0, début au 1er janvier, année affichée."""
    first_day = f"{new_year}-01-01"
    for key in [MAIN_COUNTER_KEY, *vinted_counter_keys()]:
        state = counters.get(key)
        if not isinstance(state, dict):
            continue
        if key != MAIN_COUNTER_KEY or "init_ca" in state:
            state["init_ca"] = 0.0
        state["start_date"] = first_day
        if "start_datetime" in state:
            # Date seule, sans « T » : sinon l'ancien horodatage continuerait de primer sur start_date.
            state["start_datetime"] = first_day
        state["year"] = str(new_year)


def _result(counters, *, archived_years=(), initialized=False, error=None):
    return {
        "counters": counters,
        "archived_years": list(archived_years),
        "initialized": bool(initialized),
        "changed": bool(archived_years) or bool(initialized),
        "error": error,
    }


def ensure_yearly_reset(counters, lots, today, write_func):
    """Archive les années écoulées puis remet les compteurs à zéro, en une seule écriture.

    - ``counters`` : contenu de counters.json (non modifié ; une copie est retournée).
    - ``lots`` : liste des lots (courants + archivés) ou fonction sans argument qui la retourne
      (appelée seulement si une année doit réellement être archivée).
    - ``today`` : date du jour (``date`` ou ``datetime``), jamais lue depuis l'horloge ici.
    - ``write_func(payload)`` : écrit le nouveau counters.json complet (atomique) ; si elle lève une
      exception, aucun reset n'a lieu et les compteurs d'origine sont retournés.

    Retourne un dict : counters, archived_years, initialized, changed, error.
    """
    if not isinstance(counters, dict) or not counters_need_reset(counters, today):
        return _result(counters)
    try:
        updated = copy.deepcopy(counters)
        archive = updated.get(ARCHIVE_KEY)
        if not isinstance(archive, dict):
            archive = {}
            updated[ARCHIVE_KEY] = archive
        years = archive.get("years")
        if not isinstance(years, dict):
            years = {}
            archive["years"] = years
        marker = _parse_year(archive.get("last_reset_year"))
        archived = []
        if marker is None:
            # Premier passage : on note l'année en cours, il n'y a encore rien à archiver.
            archive["last_reset_year"] = today.year
        else:
            all_lots = lots() if callable(lots) else (lots or [])
            for year in range(marker, today.year):
                if str(year) not in years:  # jamais d'écrasement d'une archive existante
                    years[str(year)] = _archive_year(updated, all_lots, year)
                    archived.append(year)
                _reset_counters(updated, year + 1)
                archive["last_reset_year"] = year + 1
        write_func(updated)
    except Exception as exc:  # noqa: BLE001 - l'échec est remonté, les compteurs d'origine restent intacts
        return _result(counters, error=f"{type(exc).__name__}: {exc}"[:300])
    return _result(updated, archived_years=archived, initialized=marker is None)


def archived_years_summary(counters):
    """Années archivées, de la plus récente à la plus ancienne, prêtes à afficher.

    Retourne [{"year": 2026, "reset_on": "2027-01-01", "channels": [{"key", "label", "ca", "nb", ...}]}].
    """
    years = _archive_block(counters).get("years")
    if not isinstance(years, dict):
        return []
    order = [MAIN_COUNTER_KEY, *vinted_counter_keys()]
    summary = []
    for raw_year, entry in years.items():
        year = _parse_year(raw_year)
        if year is None or not isinstance(entry, dict):
            continue
        channels = entry.get("channels")
        channels = channels if isinstance(channels, dict) else {}
        rows = []
        for key in sorted(channels, key=lambda k: (order.index(k) if k in order else len(order), str(k))):
            data = channels[key]
            if not isinstance(data, dict):
                continue
            rows.append({
                "key": key,
                "label": data.get("label") or key,
                "ca": _float(data.get("ca")),
                "nb": int(_float(data.get("nb"))),
                "init_ca": _float(data.get("init_ca")),
                "start_date": data.get("start_date"),
            })
        summary.append({"year": year, "reset_on": entry.get("reset_on"), "channels": rows})
    return sorted(summary, key=lambda item: item["year"], reverse=True)

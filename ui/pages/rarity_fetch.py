"""Section « Rareté des cartes » de Santé des données : recuperation de la rarete depuis TCGdex.

Le travail est fait PAR L'APPLICATION sur l'ordinateur de l'utilisateur (voir services/card_rarity_service.py) :
cartes du Drop d'abord, puis, en option, le reste du stock. Par lots de quelques secondes avec une barre de
progression, un bouton Annuler et une reprise (les cartes deja traitees ne sont pas redemandees).
Rien n'est ecrit dans data.json ni vinted_drops.json : seulement le cache `.cache/cards_rarity_cache.json`.
"""

from __future__ import annotations

import time

import streamlit as st

from services import card_rarity_service as rarity

STATE_KEY = "rarity_fetch_state"
INCLUDE_STOCK_KEY = "rarity_fetch_include_stock"
STALE_AFTER_SECONDS = 30  # une recuperation « en cours » abandonnee (page quittee) n'est pas reprise toute seule

CLASS_LABELS = {
    "ar": "Illustration rare (mot « AR » ajouté)",
    "gold": "Hyper rare (mot « Gold » ajouté)",
    "shiny": "Shiny (mot « Shiny » ajouté)",
    "fa": "Ultra rare ex / EX / V / GX / Dresseur (mot « FA » ajouté)",
    "fa_review": "Ultra rare VMAX / VSTAR / autre (rien ajouté, accord demandé)",
    "ambiguous": "Cas ambigus : VMAX, VSTAR, régional, promo… (rien ajouté)",
    "sir": "Illustration spéciale rare (mot « Alt » ajouté)",
    "secret": "Secrète (listée, rien ajouté)",
    "alternate": "Alternative (listée, rien ajouté)",
    "other": "Autres raretés (rien à ajouter)",
    "unknown": "Rareté inconnue ou non récupérée",
}


def _new_state():
    return {"running": False, "queue": [], "total": 0, "done": 0, "ok": 0, "not_found": 0, "errors": 0,
            "consecutive_errors": 0, "last_render": 0.0, "message": "", "scope": "drop", "rarities": {}}


def _state():
    state = st.session_state.get(STATE_KEY)
    if not isinstance(state, dict):
        state = _new_state()
        st.session_state[STATE_KEY] = state
    return state


def _stop(state, message):
    state["running"] = False
    state["message"] = message


def _summary_message(state):
    parts = [f"{state['ok']} rareté(s) récupérée(s)"]
    if state["not_found"]:
        parts.append(f"{state['not_found']} carte(s) introuvable(s) chez TCGdex")
    if state["errors"]:
        parts.append(f"{state['errors']} erreur(s) réseau (elles seront redemandées à la reprise)")
    return ", ".join(parts) + "."


def render_rarity_fetch(*, ld_func, load_drops_func, http_get=None, cache_path=None, backup_dir=None,
                        journal_path=None, sleep=time.sleep, interval=rarity.MIN_INTERVAL_SECONDS,
                        batch_seconds=rarity.BATCH_SECONDS):
    """Affiche la section. Les parametres sauf ld_func / load_drops_func servent aux tests (reseau et fichiers simules)."""
    data, drops = ld_func(), load_drops_func()
    entries = rarity.read_cache_file(cache_path).get("cards", {})
    state = _state()

    if state["running"] and time.time() - state["last_render"] > STALE_AFTER_SECONDS:
        _stop(state, "Récupération interrompue (page quittée). Clique sur « Reprendre » pour continuer là où elle s'est arrêtée.")

    st.markdown("#### 🏷️ Rareté des cartes")
    st.caption(
        "La rareté sert aux mots **AR** (Illustration rare), **Gold** (Hyper rare), **Alt** (Illustration spéciale rare) et **FA** (Ultra rare ex, EX, V, GX ou Dresseur) "
        "dans les titres et descriptions. "
        "Elle est demandée à TCGdex par l'application, puis gardée dans `.cache/cards_rarity_cache.json` "
        "(ni data.json ni vinted_drops.json ne sont modifiés)."
    )

    include_stock = st.checkbox("Inclure aussi le reste du stock (plus long)", key=INCLUDE_STOCK_KEY)
    queue_info = rarity.build_queue(data, drops, entries, include_stock=include_stock)
    wanted = queue_info["drop"] + queue_info["stock"]

    cols = st.columns(4)
    cols[0].metric("Drop : à récupérer", len(queue_info["drop"]))
    cols[1].metric("Reste du stock : à récupérer", len(queue_info["stock_all"]))
    cols[2].metric("Déjà dans le cache", queue_info["already_done"])
    cols[3].metric("Sans identifiant TCGdex", queue_info["without_id"])
    seconds = len(wanted) * (rarity.MIN_INTERVAL_SECONDS + 0.4)
    st.caption(
        f"Cette récupération représente **{len(wanted)} requête(s)** TCGdex (une par carte, ≈ {max(1, round(seconds / 60))} min). "
        "Les cartes sans identifiant TCGdex ne peuvent pas être demandées."
    )

    if state["running"]:
        _run_one_batch(state, wanted, http_get=http_get, cache_path=cache_path, backup_dir=backup_dir,
                       journal_path=journal_path, sleep=sleep, interval=interval, batch_seconds=batch_seconds)
    else:
        label = "▶️ Reprendre la récupération" if state["done"] and state["done"] < state["total"] else \
            "📥 Récupérer la rareté des cartes du Drop"
        if st.button(label, type="primary", key="rarity_fetch_start", disabled=not wanted):
            state.update(_new_state())
            state.update(running=True, queue=list(wanted), total=len(wanted), last_render=time.time(),
                         scope="stock" if include_stock else "drop")
            st.rerun()
        if state["message"]:
            st.info(state["message"])
        if not wanted:
            st.success("✅ Rien à récupérer : toutes les cartes demandées sont déjà dans le cache.")

    _render_report(data, drops, cache_path)


def _run_one_batch(state, wanted, *, http_get, cache_path, backup_dir, journal_path, sleep, interval, batch_seconds):
    state["last_render"] = time.time()
    progress = st.progress(0.0 if not state["total"] else min(1.0, state["done"] / state["total"]),
                           text=f"{state['done']} / {state['total']} cartes traitées")
    if st.button("⏹️ Annuler", key="rarity_fetch_cancel"):
        _stop(state, f"Récupération annulée. {_summary_message(state)} Le cache est conservé : « Reprendre » continue.")
        st.rerun()

    wanted_set = set(wanted)
    pending = [card_id for card_id in state["queue"] if card_id in wanted_set]
    if not pending:
        _stop(state, f"Terminé. {_summary_message(state)}")
        st.rerun()
    stats = rarity.run_batch(
        pending, path=cache_path, backup_dir=backup_dir, journal_path=journal_path, http_get=http_get,
        sleep=sleep, interval=interval, max_seconds=batch_seconds,
        consecutive_errors=state["consecutive_errors"], batch_label=state["scope"],
    )
    done_ids = set(stats["processed"])
    errored = stats["errors"]
    # Les cartes en erreur restent dans la file de la prochaine reprise, pas de celle-ci.
    state["queue"] = [i for i in state["queue"] if i not in done_ids]
    state["done"] += len(done_ids)
    state["ok"] += stats["ok"]
    state["not_found"] += stats["not_found"]
    state["errors"] += errored
    state["consecutive_errors"] = stats["consecutive_errors"]
    for label, count in stats["rarities"].items():
        state["rarities"][label] = state["rarities"].get(label, 0) + count
    progress.progress(min(1.0, state["done"] / max(1, state["total"])), text=f"{state['done']} / {state['total']} cartes traitées")
    if stats["stopped"] == "erreurs":
        _stop(state, f"Arrêt après {rarity.MAX_CONSECUTIVE_ERRORS} erreurs réseau de suite (connexion ? TCGdex indisponible ?). "
                     f"{_summary_message(state)} Relance quand la connexion est revenue : « Reprendre » continue.")
    elif stats["stopped"] == "termine" or not state["queue"]:
        _stop(state, f"Terminé. {_summary_message(state)}")
    st.rerun()


def _render_report(data, drops, cache_path):
    entries = rarity.read_cache_file(cache_path).get("cards", {})
    if not entries:
        return
    drop_cards = rarity.drop_cards(drops, data)
    report = rarity.rarity_report(drop_cards, entries)
    st.markdown("##### Bilan des cartes du Drop")
    rows = [{"Rareté": CLASS_LABELS.get(klass, klass), "Cartes": count}
            for klass, count in sorted(report["counts"].items(), key=lambda item: -item[1])]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    alt_count = report["counts"].get("sir", 0)
    st.caption(f"**{alt_count} carte(s)** du Drop reçoivent automatiquement « Alt » (Illustration spéciale rare).")
    if report["listed_cases"]:
        with st.expander(f"Secrètes / Alternatives (rien ajouté) — {len(report['listed_cases'])} carte(s)"):
            st.caption("Ces raretés sont listées pour information : aucun mot n'est ajouté au titre.")
            st.dataframe(report["listed_cases"], hide_index=True, use_container_width=True)
    fa_count = report["counts"].get("fa", 0)
    st.caption(f"**{fa_count} carte(s)** du Drop reçoivent automatiquement « FA » (Ultra rare ex, EX, V, GX ou Dresseur).")
    if report["ultra_cases"]:
        with st.expander(f"Cartes « Ultra Rare » du Drop — {len(report['ultra_cases'])} carte(s) : {fa_count} « FA » appliqué, "
                         f"{len(report['ultra_cases']) - fa_count} à valider", expanded=True):
            st.dataframe([{k: v for k, v in row.items() if k != "id"} for row in report["ultra_cases"]],
                         hide_index=True, use_container_width=True)
    if report["fa_cases"]:
        with st.expander(f"Cas à valider (VMAX / VSTAR / ambigus) — {len(report['fa_cases'])} carte(s)"):
            st.caption("Aucun mot n'est ajouté automatiquement pour ces cartes (VMAX et VSTAR notamment) : donne ton accord pour activer « FA ».")
            st.dataframe(report["fa_cases"], hide_index=True, use_container_width=True)

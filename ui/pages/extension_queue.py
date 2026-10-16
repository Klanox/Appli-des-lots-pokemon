"""« Extensions manquantes » : compteur, file de correction, selecteur d'extension et annonces a remettre a jour.

Place dans la page « Santé des données » (Data Health) : c'est la page des controles permanents de qualite des
donnees, deja dotee d'un mecanisme de correction « apres sauvegarde, une carte a la fois ». Le selecteur est aussi
accessible depuis l'ecran de creation des annonces (bouton « Choisir l'extension »).

Toute ecriture passe par `services.card_extension_service.apply_corrections` qui : sauvegarde dans backups/,
n'ecrit que des extensions VIDES (sauf confirmation explicite), ecrit via les fonctions de sauvegarde normales
de l'appli (`sd`, `save_vinted_drops` : synchro Cloud comprise) et journalise chaque changement hors JSON metier.
Aucun statut de carte / de Drop n'est jamais modifie.
"""

from __future__ import annotations

import html
import os

import streamlit as st

from services import card_extension_service as ext
from services import listing_text_service as listing_texts
from services.vinted_listing_service import prepare_listing

FLASH_KEY = "extension_queue_flash"
CONFIRM_KEY = "extension_certain_confirm"
DONE_LISTINGS_KEY = "extension_listings_done"
SECTION_KEY = "extension_queue_section"

CONF_ICON = {ext.CONF_CERTAIN: "🟢", ext.CONF_PROBABLE: "🟡", ext.CONF_AMBIGUOUS: "🟠", ext.CONF_NONE: "🔴"}
CONF_LABEL = {ext.CONF_CERTAIN: "certaine", ext.CONF_PROBABLE: "probable", ext.CONF_AMBIGUOUS: "ambiguë", ext.CONF_NONE: "aucune"}

BADGE_CSS = """
<style>
.ps-ext-missing-badge{display:inline-block;background:#fee2e2;color:#b91c1c;border:1px solid #fca5a5;border-radius:999px;
padding:.05rem .55rem;font-size:.74rem;font-weight:800;line-height:1.5;white-space:nowrap}
.ps-ext-row-meta{color:#64748b;font-size:.8rem}
</style>
"""


# --------------------------------------------------------------------------- petits utilitaires

def extension_badge_html():
    """Pastille rouge « Extension manquante » (HTML sur, aucune donnee variable)."""
    return '<span class="ps-ext-missing-badge">⚠ Extension manquante</span>'


def _image_source(item_or_card):
    manual = str(item_or_card.get("manual_image_path") or "")
    candidates = [manual, str(item_or_card.get("image_url") or "")]
    for value in candidates:
        if not value:
            continue
        if value.startswith("http"):
            return value
        path = value if os.path.isabs(value) else os.path.join(ext.APP_DIR, value)
        if os.path.isfile(path):
            return path
    return ""


def _show_image(item, width=56):
    source = _image_source(item)
    if source:
        try:
            st.image(source, width=width)
            return
        except Exception:
            pass
    st.caption("🖼️ —")


def _paths():
    return {
        "data_path": os.path.join(ext.APP_DIR, "data.json"),
        "drops_path": os.path.join(ext.APP_DIR, "vinted_drops.json"),
        "archives_path": os.path.join(ext.APP_DIR, "lots_archives.json"),
        "backup_dir": ext.BACKUP_DIR,
        "journal_path": ext.JOURNAL_FILE,
    }


def _load_archives(path):
    from services.data_health_service import load_archives

    return load_archives(path)


def _flash(ok, message):
    st.session_state[FLASH_KEY] = (ok, message)


def _show_flash():
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        (st.success if flash[0] else st.warning)(flash[1])


def _apply(changes, *, ld_func, sd_func, load_drops_func, save_drops_func, allow_replace=False, label=""):
    paths = _paths()
    with st.spinner(f"Écriture de {len(changes)} correction(s) : sauvegarde, application, synchronisation…"):
        return ext.apply_corrections(
            changes,
            load_data=ld_func, save_data=sd_func, load_drops=load_drops_func, save_drops=save_drops_func,
            data_path=paths["data_path"], drops_path=paths["drops_path"], backup_dir=paths["backup_dir"],
            journal_path=paths["journal_path"], allow_replace=allow_replace, batch_label=label,
        )


def _result_message(result):
    message = result.get("message", "")
    if result.get("backups"):
        message += " Sauvegarde : " + ", ".join(os.path.basename(b) for b in result["backups"]) + "."
    skipped = result.get("skipped") or []
    if skipped:
        message += f" {len(skipped)} carte(s) ignorée(s) : " + " ; ".join(f"{name} ({why})" for name, why in skipped[:5])
    return message


# --------------------------------------------------------------------------- compteur permanent

def render_extension_counters(data, drops, archives):
    """Compteur « Cartes sans extension » (stock et Drop), calcule a chaque affichage (aucun scan a lancer)."""
    counts = ext.count_missing_extensions(data, drops, archives)
    cols = st.columns(3)
    cols[0].metric("Cartes sans extension — stock", counts["stock"],
                   help=f"dont {counts['stock_en_quantite']} avec une quantité restante en stock")
    cols[1].metric("Cartes sans extension — Drop", counts["drop"])
    if counts["drop_par_statut"]:
        from services.card_extension_service import DROP_STATUS_LABELS

        cols[2].caption("Drop par statut : " + " · ".join(
            f"{DROP_STATUS_LABELS.get(status, status)} {number}" for status, number in sorted(counts["drop_par_statut"].items())))
    if counts["stock"] or counts["drop"]:
        st.markdown(extension_badge_html() + " &nbsp;<span class='ps-ext-row-meta'>Ces annonces sortent sans nom d'extension "
                    "tant que la carte n'est pas corrigée (section « Extensions manquantes » ci-dessous).</span>",
                    unsafe_allow_html=True)
    else:
        st.success("✅ Toutes les cartes ont une extension.")
    return counts


# --------------------------------------------------------------------------- selecteur d'extension

def _selector_options(candidates, catalogue):
    ordered = list(candidates)
    ordered += [name for name in catalogue.search_set_names("", limit=100000) if name not in ordered]
    return ordered


def render_extension_selector(item, *, key, ld_func, sd_func, load_drops_func, save_drops_func, default=""):
    """Selecteur d'extension pour UNE carte : liste (candidats d'abord) + saisie libre acceptee. Ecrit apres clic."""
    catalogue = ext.load_catalogue()
    candidates = list(item.get("candidates") or [])
    options = _selector_options(candidates, catalogue)
    default = default or (candidates[0] if len(candidates) == 1 else "")
    index = options.index(default) if default in options else None
    choice = st.selectbox(
        "Extension", options, index=index, accept_new_options=True, key=f"{key}_choice",
        placeholder="Chercher une extension ou saisir un nom…",
        help="Les extensions possibles pour cette carte sont en tête de liste. Un nom absent du catalogue est accepté tel quel.",
    )
    choice = str(choice or "").strip()
    if candidates:
        st.caption("Candidates : " + " · ".join(candidates[:6]))
    if choice and choice not in catalogue.all_set_names:
        st.caption("⚠️ Extension absente du catalogue : elle sera enregistrée telle que saisie.")
    current = ext.card_extension_name({"set": item.get("set_raw")})
    replace_ok = True
    if current:
        replace_ok = st.checkbox(f"Remplacer l'extension actuelle « {current} »", key=f"{key}_replace")
    if st.button("Enregistrer l'extension", key=f"{key}_save", disabled=not choice or ext.is_missing_extension(choice) or not replace_ok):
        result = _apply(
            [ext.queue_change(item, new_value=choice, confidence="manuelle", source="choix de l'utilisateur")],
            ld_func=ld_func, sd_func=sd_func, load_drops_func=load_drops_func, save_drops_func=save_drops_func,
            allow_replace=bool(current), label="sélecteur",
        )
        _flash(result["ok"], _result_message(result))
        st.rerun()


def render_extension_shortcut(card, *, key):
    """Raccourci « Choisir l'extension » depuis l'ecran de creation d'annonce (meme selecteur que la file)."""
    from data import sd as sd_func, ld as ld_func
    from services.vinted_drops_service import load_vinted_drops, save_vinted_drops

    with st.popover("Choisir l'extension", icon="🧩"):
        data = ld_func()
        catalogue = ext.load_catalogue()
        ctx = ext.ProposalContext(data, _load_archives(_paths()["archives_path"]), catalogue)
        proposal = ext.propose_extension(card, ctx)
        item = {
            "card_uid": str(card.get("card_uid") or ""), "lot_uid": str(card.get("lot_uid") or ""),
            "name": str(card.get("name") or ""), "number": str(card.get("number") or ""),
            "set_raw": str(card.get("set") or ""), "candidates": proposal["candidates"], "value": proposal["value"],
            "source": proposal["source"], "confidence": proposal["confidence"],
        }
        if not item["card_uid"]:
            st.caption("Cette carte n'a pas d'identifiant de stock : correction impossible depuis ici.")
            return
        st.caption(f"{item['name']} {item['number']} — proposition {CONF_ICON[proposal['confidence']]} {CONF_LABEL[proposal['confidence']]}"
                   + (f" : {proposal['value']}" if proposal["value"] else ""))
        render_extension_selector(item, key=f"extpick_{key}", ld_func=ld_func, sd_func=sd_func,
                                  load_drops_func=load_vinted_drops, save_drops_func=save_vinted_drops, default=proposal["value"])


# --------------------------------------------------------------------------- file de correction

def _drop_label(item):
    drop = item.get("drop")
    if not drop:
        return "Hors Drop"
    return drop["status_label"] + (" · réassort" if drop["restock"] else "")


def _row_header(item):
    """Ligne compacte : photo · carte (+ id) · lot et statut Drop. Retourne les colonnes (la 4e est libre pour l'appelant)."""
    cols = st.columns([0.6, 2.4, 2.4, 3.2])
    with cols[0]:
        _show_image(item, width=48)
    cols[1].markdown(f"**{html.escape(item['name'])} {html.escape(item['number'])}**  \n:gray[{html.escape(item['id'] or 'sans identifiant')}]")
    cols[2].markdown(f"📦 {html.escape(item['lot_name'])}  \n:gray[🏷️ {html.escape(_drop_label(item))}]")
    return cols


def _proposal_markdown(item):
    return f"➡️ **{html.escape(item['value'])}**  \n:gray[{html.escape(item['source'])}]"


def _filter_items(items, key):
    lots = sorted({i["lot_name"] for i in items})
    left, right = st.columns(2)
    lot_choice = left.selectbox("Lot", ["Tous les lots"] + lots, key=f"{key}_lot")
    drop_choice = right.selectbox(
        "Statut Drop", ["Tous", "Hors Drop", "Dans le Drop", "Réassort à traiter", "En ligne", "Vendue", "À photographier", "Triée"],
        key=f"{key}_drop",
    )

    def keep(item):
        if lot_choice != "Tous les lots" and item["lot_name"] != lot_choice:
            return False
        drop = item.get("drop")
        if drop_choice == "Hors Drop":
            return drop is None
        if drop_choice == "Dans le Drop":
            return drop is not None
        if drop_choice == "Réassort à traiter":
            return bool(drop and drop["restock"] and drop["status"] in ("to_photograph", "sorted"))
        wanted = {"En ligne": "online", "Vendue": "sold", "À photographier": "to_photograph", "Triée": "sorted"}.get(drop_choice)
        return True if wanted is None else bool(drop and drop["status"] == wanted)

    return [i for i in items if keep(i)]


def render_extension_queue(*, ld_func, sd_func, load_drops_func, save_drops_func):
    paths = _paths()
    data = ld_func()
    drops = load_drops_func()
    archives = _load_archives(paths["archives_path"])
    catalogue = ext.load_catalogue()
    items = ext.build_queue(data, drops, archives, catalogue)
    _show_flash()
    if not items:
        st.success("✅ Aucune carte sans extension.")
        _render_undo(ld_func, sd_func, load_drops_func, save_drops_func)
        return

    by_level = {level: [i for i in items if i["confidence"] == level and not i["flag_only"]] for level in ext.CONF_ORDER}
    manual = [i for i in items if i["flag_only"] or i["confidence"] in (ext.CONF_AMBIGUOUS, ext.CONF_NONE)]
    st.caption(
        f"{len(items)} carte(s) sans extension · 🟢 {len(by_level[ext.CONF_CERTAIN])} certaines · "
        f"🟡 {len(by_level[ext.CONF_PROBABLE])} probables · 🧩 {len(manual)} à choisir (ambiguës, sans proposition, drapeau 🇯🇵). "
        "Aucun statut de carte ne change : seule l'extension est renseignée."
    )
    view = st.radio(
        "Vue", ["Certaines", "Probables", "À choisir"], horizontal=True, key="extension_queue_view",
        format_func=lambda v: {"Certaines": f"🟢 Certaines ({len(by_level[ext.CONF_CERTAIN])})",
                               "Probables": f"🟡 Probables ({len(by_level[ext.CONF_PROBABLE])})",
                               "À choisir": f"🧩 À choisir ({len(manual)})"}[v],
    )
    if view == "Certaines":
        _render_certain(by_level[ext.CONF_CERTAIN], ld_func, sd_func, load_drops_func, save_drops_func)
    elif view == "Probables":
        _render_probable(by_level[ext.CONF_PROBABLE], ld_func, sd_func, load_drops_func, save_drops_func)
    else:
        _render_manual(manual, ld_func, sd_func, load_drops_func, save_drops_func)
    _render_undo(ld_func, sd_func, load_drops_func, save_drops_func)


def _render_certain(items, ld_func, sd_func, load_drops_func, save_drops_func):
    st.markdown("**Propositions certaines** — exemplaire identique du stock, identifiant retrouvé dans le catalogue local, "
                "ou nom donné par toi. Aperçu complet ci-dessous, puis application en bloc.")
    shown = _filter_items(items, "ext_certain")
    for item in shown:
        with st.container(border=True):
            cols = _row_header(item)
            cols[3].markdown(_proposal_markdown(item))
    if not items:
        st.info("Aucune proposition certaine.")
        return
    in_drop = sum(1 for i in items if i["drop"])
    online = sum(1 for i in items if i["drop"] and i["drop"]["status"] == "online")
    st.info(f"{len(items)} carte(s) seront renseignées ({in_drop} présentes dans le Drop, dont {online} déjà en ligne). "
            "Leur copie dans le Drop reçoit la même extension. Statuts, dates, photos et groupes ne changent pas.")
    if not st.session_state.get(CONFIRM_KEY):
        if st.button(f"Appliquer les {len(items)} propositions certaines", type="primary", key="ext_certain_apply"):
            st.session_state[CONFIRM_KEY] = True
            st.rerun()
        return
    st.warning("Confirme l'écriture : data.json et vinted_drops.json seront sauvegardés dans backups/ puis modifiés.")
    left, right = st.columns(2)
    if left.button("✅ Confirmer l'écriture", type="primary", key="ext_certain_confirm"):
        result = _apply([ext.queue_change(i) for i in items], ld_func=ld_func, sd_func=sd_func,
                        load_drops_func=load_drops_func, save_drops_func=save_drops_func, label="certaines")
        st.session_state.pop(CONFIRM_KEY, None)
        _flash(result["ok"], _result_message(result) + (" Pense à faire « Mettre à jour l'analyse » dans l'étape Drop." if result["ok"] else ""))
        st.rerun()
    if right.button("Annuler", key="ext_certain_cancel"):
        st.session_state.pop(CONFIRM_KEY, None)
        st.rerun()


def _render_probable(items, ld_func, sd_func, load_drops_func, save_drops_func):
    st.markdown("**Propositions probables** — une seule extension plausible, à confirmer. Coche celles à appliquer.")
    if not items:
        st.info("Aucune proposition probable.")
        return
    shown = _filter_items(items, "ext_prob")
    for item in shown:
        with st.container(border=True):
            cols = _row_header(item)
            cols[3].markdown(_proposal_markdown(item))
            cols[3].checkbox("Appliquer", key=f"ext_prob_{item['card_uid']}")
    checked = [i for i in items if st.session_state.get(f"ext_prob_{i['card_uid']}")]
    if st.button(f"Appliquer les cases cochées ({len(checked)})", type="primary", disabled=not checked, key="ext_prob_apply"):
        result = _apply([ext.queue_change(i) for i in checked], ld_func=ld_func, sd_func=sd_func,
                        load_drops_func=load_drops_func, save_drops_func=save_drops_func, label="probables")
        for i in checked:
            st.session_state.pop(f"ext_prob_{i['card_uid']}", None)
        _flash(result["ok"], _result_message(result))
        st.rerun()


def _render_manual(items, ld_func, sd_func, load_drops_func, save_drops_func):
    st.markdown("**À choisir** — ambiguës, sans proposition, ou extension réduite à un drapeau 🇯🇵. "
                "Choisis dans la liste (les candidates sont en tête) ou saisis un nom libre.")
    if not items:
        st.info("Rien à choisir.")
        return
    for item in _filter_items(items, "ext_manual"):
        with st.container(border=True):
            _row_header(item)
            st.caption(f"{CONF_ICON[item['confidence']]} Proposition {CONF_LABEL[item['confidence']]}"
                       + (f" : {item['value']}" if item["value"] else "")
                       + (" · extension actuelle : 🇯🇵 seul" if item["flag_only"] else ""))
            render_extension_selector(item, key=f"ext_manual_{item['card_uid']}", ld_func=ld_func, sd_func=sd_func,
                                      load_drops_func=load_drops_func, save_drops_func=save_drops_func, default=item["value"])


def _render_undo(ld_func, sd_func, load_drops_func, save_drops_func):
    batches = ext.journal_batches(_paths()["journal_path"])
    with st.expander(f"Journal et annulation ({len(batches)} lot(s) annulable(s))", expanded=False):
        if not batches:
            st.caption("Aucune correction enregistrée dans le journal.")
        for batch in batches[:10]:
            cols = st.columns([4, 1.4])
            names = ", ".join(f"{e['card']} {e['number']} → {e['new']}" for e in batch["entries"][:3])
            cols[0].caption(f"{batch['at']} · {batch['count']} carte(s) · {names}{'…' if batch['count'] > 3 else ''}")
            if cols[1].button("↩️ Annuler", key=f"ext_undo_{batch['batch']}"):
                paths = _paths()
                result = ext.undo_batch(
                    batch["batch"], load_data=ld_func, save_data=sd_func, load_drops=load_drops_func, save_drops=save_drops_func,
                    data_path=paths["data_path"], drops_path=paths["drops_path"], backup_dir=paths["backup_dir"],
                    journal_path=paths["journal_path"],
                )
                _flash(result["ok"], _result_message({"message": result["message"], "backups": result.get("backups"), "skipped": result.get("skipped")}))
                st.rerun()


# --------------------------------------------------------------------------- annonces en ligne a mettre a jour

def _render_text_updates(load_drops_func, save_drops_func, run_html):
    """Annonces et brouillons Vinted dont le texte a ete regenere (etape 4 « ⋯ Plus ») : a recopier a la main sur Vinted."""
    from ui.pages.vinted_listings import _copy_button

    pending = listing_texts.pending_updates(load_drops_func())
    st.markdown("**Textes régénérés avec les règles actuelles**")
    st.caption("L'application ne modifie jamais une annonce ou un brouillon déjà créé sur Vinted : copie le nouveau titre et la "
               "nouvelle description dans Vinted, puis marque la ligne comme mise à jour.")
    if not pending:
        st.success("✅ Aucun texte régénéré à reporter sur Vinted.")
        return
    for drop, update in pending:
        key = str(update.get("id") or "").replace(":", "_")
        with st.container(border=True):
            st.markdown(f"**{html.escape(str(update.get('cards') or ''))}** · {html.escape(str(update.get('label') or ''))} "
                        f"<span class='ps-ext-row-meta'>({html.escape(str(drop.get('name') or ''))})</span>", unsafe_allow_html=True)
            before = str(update.get("title_before") or "")
            note = " (ancien texte supposé : il n'était pas enregistré)" if update.get("assumed_before") else ""
            st.caption(f"Avant{note} : {before}")
            st.text_input("Nouveau titre Vinted", value=update.get("title_after") or "", disabled=True, key=f"txtupd_title_{key}")
            _copy_button("Copier le titre", update.get("title_after") or "", f"txtupd_copy_title_{key}", run_html, [], compact=True)
            st.text_area("Nouvelle description", value=update.get("description_after") or "", height=150, disabled=True,
                         key=f"txtupd_desc_{key}")
            _copy_button("Copier la description", update.get("description_after") or "", f"txtupd_copy_desc_{key}", run_html, [], compact=True)
            if save_drops_func and st.button("✔️ Marquer comme mis à jour", key=f"txtupd_done_{key}"):
                drops = load_drops_func()
                listing_texts.mark_update_done(drops, drop.get("id"), update.get("id"), save_drops=save_drops_func)
                st.rerun()


def render_listings_to_update(*, ld_func, load_drops_func, save_drops_func=None):
    """Annonces EN LIGNE dont le titre a ete genere sans extension : titre + description corriges, a copier-coller."""
    from ui.pages.vinted_listings import _copy_button

    def run_html(body, height=0):
        st.html(body, unsafe_allow_javascript=True)

    _render_text_updates(load_drops_func, save_drops_func, run_html)
    st.divider()
    st.markdown("**Annonces en ligne dont l'extension vient d'être corrigée**")
    paths = _paths()
    data, drops = ld_func(), load_drops_func()
    done = set(st.session_state.get(DONE_LISTINGS_KEY, set())) | ext.listings_marked_updated(paths["journal_path"])
    entries = [e for e in ext.online_listings_to_update(data, drops, paths["journal_path"])
               if str(e["ref"].get("drop_item_id") or "") not in done]
    st.caption("Ces annonces sont déjà en ligne sur Vinted avec un titre généré sans extension. Après correction de l'extension, "
               "copie le titre et la description ci-dessous dans l'annonce Vinted, puis marque-la comme mise à jour. "
               "Les statuts « en ligne » / « vendue » ne changent jamais.")
    if not entries:
        st.success("✅ Aucune annonce en ligne à mettre à jour.")
        return
    for entry in entries:
        ref, card = entry["ref"], entry["card"]
        item_id = str(ref.get("drop_item_id") or ref.get("card_uid"))
        with st.container(border=True):
            st.markdown(f"**{html.escape(str(card.get('name') or ''))} {html.escape(str(card.get('number') or ''))}**",
                        unsafe_allow_html=True)
            if entry["still_missing"]:
                st.markdown(extension_badge_html() + " &nbsp;Corrige d'abord l'extension (vue « Extensions manquantes »).",
                            unsafe_allow_html=True)
                continue
            prepared = prepare_listing([card], "Carte seule")
            st.caption(f"Extension : {ext.card_extension_name(card)}"
                       + (f" (avant : {entry['correction'].get('old') or 'vide'})" if entry.get("correction") else ""))
            st.text_input("Titre Vinted", value=prepared["title"], disabled=True, key=f"extlist_title_{item_id}")
            _copy_button("Copier le titre", prepared["title"], f"extlist_copy_title_{item_id}", run_html, [], compact=True)
            st.text_area("Description", value=prepared["description"], height=150, disabled=True, key=f"extlist_desc_{item_id}")
            _copy_button("Copier la description", prepared["description"], f"extlist_copy_desc_{item_id}", run_html, [], compact=True)
            if st.button("✔️ Marquer comme mis à jour", key=f"extlist_done_{item_id}"):
                st.session_state.setdefault(DONE_LISTINGS_KEY, set()).add(item_id)
                ext.mark_listing_updated(item_id, paths["journal_path"])
                st.rerun()


def extension_sections_count(data, drops):
    paths = _paths()
    pending = [e for e in ext.online_listings_to_update(data, drops, paths["journal_path"])
               if str(e["ref"].get("drop_item_id") or "") not in (set(st.session_state.get(DONE_LISTINGS_KEY, set())) | ext.listings_marked_updated(paths["journal_path"]))]
    return len(pending) + len(listing_texts.pending_updates(drops))

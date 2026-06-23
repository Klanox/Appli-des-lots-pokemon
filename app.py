# Pokestock - Version FINALE avec toutes les modifications
# Gestion de lots de cartes Pokemon

import streamlit as st
import json,os,requests,time,glob,uuid,shutil,re
import html
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import unicodedata
import hashlib

# Import from modular structure
from utils import (
    normalize_name,
    parse_float_input,
    parse_int_input,
    fp,
    safe_write_json,
    canal_key,
    cardmarket_search_url,
    fetch_listing_preview_image,
    new_uid,
    APP_DIR,
    DATA,
    CARDS_CACHE_FILE,
    CARDS_CACHE_TTL_SECONDS,
    BACKUP_DIR,
    BACKUP_STATE_FILE,
    ESTIMATIONS_FILE,
)
from cloud import (
    get_supabase_client,
    cloud_sync_entry,
    load_cloud_json_meta,
    save_cloud_json,
    update_cloud_sync_state,
    utc_now_iso,
    SUPABASE_DATA_KEY,
    SUPABASE_ESTIMATIONS_KEY,
)
from data import (
    ld,
    sd,
    pull_data_from_cloud,
    ensure_card_ids,
    ensure_trade_lot,
    ensure_storage_lot,
    ensure_system_lots,
    create_local_backup,
    cleanup_old_backups,
    maybe_create_weekly_backup,
)
from logic import (
    cr,
    cp,
    crp,
    effective_purchase_price,
    card_sold_cote,
    calc_cout_lot,
    gst,
    is_trade_lot,
    is_storage_lot,
    card_available_qty,
    resolve_card_ref,
    migrate_open_trade_cards,
    recent_sale_notes_for_card,
    lot_tracked_cote_value,
    storage_remaining_for_lot,
    lot_remaining_including_storage,
    trade_stock_value_for_lot,
)
from core.collection import (
    COLLECTION_IMAGE_PLACEHOLDER,
    collection_card_exact_match,
    collection_current_value,
    collection_has_manual_image,
    collection_image_needs_manual,
    collection_paid_total,
    is_collection_system_lot,
)
from core.collection_actions import (
    add_collection_batch_cards,
    add_direct_collection_card,
    add_or_merge_collection_card,
    delete_collection_card_from_system,
    remove_collection_status_from_lot,
    save_collection_manual_image,
)
from core.card_add import (
    configure_card_add,
    acm_japanese,
    acm,
    render_card_choice_popups,
)
from core.sales_actions import (
    configure_sales_actions,
    _scu_in_data,
    scu,
    scu_many,
    bulk_cart_add,
    bulk_cart_remove,
    bulk_cart_set_quantity,
    bulk_cart_increment,
    bulk_cart_pop,
    bulk_cart_clear,
    bulk_sale_prepare,
    scroll_to_cart_prepare,
)

from ui.components import (
    KPI_ACCENTS,
    render_app_header,
    render_kpi_card,
    render_page_header,
)
from ui.badges import card_status_badges
from ui.card_display import (
    collection_image_html as render_collection_image_html,
    img_with_fallback as img_with_fallback_html,
)
from ui.navigation import NAV_SECTIONS
from ui.sidebar import (
    render_sidebar_brand,
)
from ui.theme import (
    inject_functional_css,
    inject_mobile_overrides,
    inject_theme,
)
from ui.pages.home import render_home_page
from ui.pages.counters import render_counters_page
from ui.pages.statistics import render_statistics_page
from ui.pages.estimations import render_estimations_page
from ui.pages.history import render_history_page
from ui.pages.archives import render_archives_page
from ui.pages.collection import render_collection_page
from ui.pages.lots import render_lots_page
from ui.pages.sales import render_sales_page
from ui.pages.vinted_listings import render_vinted_listings_page
from ui.pages.wrapped import render_wrapped_page
from services.tcgdex_service import (
    normalized_tcgdex_image_url,
    tcgdex_series_from_set_id,
)
from services.card_cache_service import (
    load_cards_cache_from_disk,
    save_cards_cache_to_disk,
    search_in_cache_index,
)
from services.perf_service import (
    perf_count,
    perf_enabled,
    perf_log,
    perf_reset_rerun,
    perf_summary,
    perf_timer,
)
from services.estimations_service import (
    estimation_totals,
    load_estimations,
    save_estimations,
)
from services.estimations_cache_enrichment import enrich_estimations_card_cache

APP_BUILD = "Codex 2026-06-12 drops search"

SUPABASE_STATE_TABLE = "app_state"
SUPABASE_DATA_KEY = "data"
SUPABASE_ESTIMATIONS_KEY = "lot_estimations"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_SECRETS_FILE = os.path.join(APP_DIR, ".streamlit", "secrets.toml")

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

# ============================================================
# CACHE GLOBAL ULTRA-RAPIDE
# ============================================================

CARDS_CACHE_FILE = "cards_cache.json"
CARDS_CACHE_TTL_SECONDS = 14 * 24 * 60 * 60

def cloud_sync_status():
    from cloud import _secret_value
    has_url = bool(_secret_value("SUPABASE_URL"))
    has_key = bool(_secret_value("SUPABASE_KEY", "SUPABASE_ANON_KEY"))
    if not has_url and not has_key:
        return False, "Secrets Supabase absents."
    if not has_url:
        return False, "SUPABASE_URL absent."
    if not has_key:
        return False, "SUPABASE_KEY absent."
    client = get_supabase_client()
    if client is None:
        return False, st.session_state.get("cloud_sync_error", "Client Supabase indisponible.")
    try:
        client.table(SUPABASE_STATE_TABLE).select("key").limit(1).execute()
        return True, "Synchronisation cloud prête"
    except Exception as e:
        st.session_state["cloud_sync_error"] = f"Test cloud impossible: {e}"
        return False, st.session_state["cloud_sync_error"]


def load_local_data_file_for_cloud_push():
    """Read the local data.json for an explicit manual cloud push."""
    try:
        with open(DATA, "r", encoding="utf-8") as f:
            local_data = json.load(f)
        if isinstance(local_data, dict) and isinstance(local_data.get("lots"), list):
            return local_data
    except Exception as e:
        st.session_state["cloud_sync_error"] = f"Lecture locale impossible: {e}"
    return None

def load_cards_cache(allow_network=True):
    """Charger toutes les cartes en mémoire (1 fois au démarrage)"""
    if "cards_index" in st.session_state:
        return st.session_state["cards_index"]

    print("Chargement cache cartes...")
    start = time.time()
    cards_index = {}

    cached_cards = load_cards_cache_from_disk(allow_stale=True)
    if cached_cards:
        st.session_state["cards_index"] = cached_cards
        print(f"Cache disque: {len(cached_cards)} noms, {time.time()-start:.1f}s")
        return cached_cards
    if not allow_network:
        print("Cache disque absent: chargement réseau différé jusqu'à une recherche.")
        return {}
    
    try:
        r = requests.get("https://api.tcgdex.net/v2/fr/sets", timeout=5)
        if r.status_code != 200:
            stale_cards = load_cards_cache_from_disk(allow_stale=True)
            if stale_cards:
                st.session_state["cards_index"] = stale_cards
                return stale_cards
            return {}
        sets = r.json()
        
        def fetch_set(s):
            try:
                sid = s.get("id")
                resp = requests.get(f"https://api.tcgdex.net/v2/fr/sets/{sid}", timeout=3)
                if resp.status_code == 200:
                    return resp.json()
            except (requests.RequestException, json.JSONDecodeError) as e:
                print(f"Warning: Could not fetch set {sid}: {e}")
                pass
            return None
        
        with ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(fetch_set, sets))
        
        for set_data in results:
            if not set_data:
                continue
            set_name = set_data.get("name", "")
            set_id = set_data.get("id", "")
            for card in set_data.get("cards", []):
                name_norm = normalize_name(card.get("name", ""))
                if name_norm not in cards_index:
                    cards_index[name_norm] = []
                cards_index[name_norm].append((card, set_name, set_id))
        
        print(f"✅ Cache: {len(cards_index)} noms, {time.time()-start:.1f}s")
        st.session_state["cards_index"] = cards_index
        save_cards_cache_to_disk(cards_index)
    except Exception as e:
        print(f"Cache error: {e}")
        stale_cards = load_cards_cache_from_disk(allow_stale=True)
        if stale_cards:
            st.session_state["cards_index"] = stale_cards
            return stale_cards
    
    return cards_index

def search_in_cache(name, num=None):
    """Recherche INSTANTANÉE dans le cache"""
    if "cards_index" not in st.session_state:
        load_cards_cache()
    cards_index = st.session_state.get("cards_index", {})
    return search_in_cache_index(name, cards_index, num=num, normalize_func=normalize_name)

# ============================================================
# DONNÉES
# ============================================================
DATA = "data.json"
ESTIMATIONS_FILE = "lot_estimations.json"
ACTIVITY_STATE_FILE = "activity_state.json"
BACKUP_DIR = "backups"
BACKUP_STATE_FILE = os.path.join(BACKUP_DIR, "backup_state.json")
BACKUP_JSON_FILES = [
    "data.json",
    "lot_estimations.json",
    "lots_archives.json",
    "counters.json",
    "monthly_goals.json",
    "activity_state.json",
    "config.json",
]

def _safe_backup_name(reason):
    clean = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(reason or "backup"))
    return clean.strip("_") or "backup"

def create_local_backup(reason="manual", include_images=False):
    """Copie les fichiers de donnees dans backups/ sans les envoyer sur GitHub."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = os.path.join(BACKUP_DIR, f"{stamp}_{_safe_backup_name(reason)}")
    os.makedirs(target_dir, exist_ok=True)

    copied = []
    for filename in BACKUP_JSON_FILES:
        if os.path.exists(filename):
            shutil.copy2(filename, os.path.join(target_dir, filename))
            copied.append(filename)

    if include_images and os.path.isdir("card_images"):
        shutil.copytree("card_images", os.path.join(target_dir, "card_images"), dirs_exist_ok=True)
        copied.append("card_images/")

    manifest = {
        "created_at": datetime.now().isoformat(),
        "reason": reason,
        "files": copied,
        "app_build": APP_BUILD,
    }
    safe_write_json(os.path.join(target_dir, "backup_manifest.json"), manifest, indent=2)
    return target_dir, copied

def _load_backup_state():
    if not os.path.exists(BACKUP_STATE_FILE):
        return {}
    try:
        with open(BACKUP_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load backup state: {e}")
        return {}

def _save_backup_state(state):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    safe_write_json(BACKUP_STATE_FILE, state, indent=2)

def cleanup_old_backups(keep=60):
    if not os.path.isdir(BACKUP_DIR):
        return
    entries = []
    for name in os.listdir(BACKUP_DIR):
        path = os.path.join(BACKUP_DIR, name)
        if os.path.isdir(path):
            entries.append((os.path.getmtime(path), path))
    entries.sort(reverse=True)
    for _, path in entries[keep:]:
        try:
            shutil.rmtree(path)
        except (IOError, OSError) as e:
            print(f"Warning: Could not remove backup directory {path}: {e}")
            pass

def maybe_create_weekly_backup():
    state = _load_backup_state()
    last = float(state.get("last_weekly_backup_at", 0) or 0)
    if time.time() - last >= 7 * 24 * 60 * 60:
        path, copied = create_local_backup("weekly", include_images=False)
        state["last_weekly_backup_at"] = time.time()
        state["last_weekly_backup_path"] = path
        state["last_weekly_backup_files"] = copied
        _save_backup_state(state)
        cleanup_old_backups()
        return path
    return ""

def maybe_create_prewrite_backup():
    state = _load_backup_state()
    last = float(state.get("last_prewrite_backup_at", 0) or 0)
    # Protection anti-catastrophe : pas plus d'une sauvegarde de securite toutes les 30 min.
    if time.time() - last >= 30 * 60:
        path, copied = create_local_backup("before_write", include_images=False)
        state["last_prewrite_backup_at"] = time.time()
        state["last_prewrite_backup_path"] = path
        state["last_prewrite_backup_files"] = copied
        _save_backup_state(state)
        cleanup_old_backups()
        return path
    return ""

def add_estimation_card(active, card_name, card_number, card_cote, card_qty, card_condition, card_specials, card_note, is_collection=False, chosen_match=None):
    image_url = ""
    image_url_en = ""
    set_name = ""
    rarity = ""
    final_name = str(card_name or "").strip()
    final_number = str(card_number or "").strip()

    if chosen_match:
        try:
            matched_card, matched_set = chosen_match
            enriched = ecd(matched_card, matched_set, lang="fr")
            image_url = enriched.get("image_url", "")
            image_url_en = enriched.get("image_url_en", "")
            set_name = enriched.get("set", "")
            rarity = enriched.get("rarity", "")
            final_name = enriched.get("name", final_name) or final_name
            final_number = enriched.get("number", final_number) or final_number
        except:
            pass
    else:
        try:
            matches = search_in_cache(final_name, final_number)
            if len(matches) == 1:
                enriched = ecd(matches[0][0], matches[0][1], lang="fr")
                image_url = enriched.get("image_url", "")
                image_url_en = enriched.get("image_url_en", "")
                set_name = enriched.get("set", "")
                rarity = enriched.get("rarity", "")
                final_name = enriched.get("name", final_name) or final_name
                final_number = enriched.get("number", final_number) or final_number
        except:
            pass

    active.setdefault("cards", []).append({
        "uid": new_uid("estcard"),
        "name": final_name.title() if final_name else "Carte",
        "number": final_number,
        "set": set_name,
        "quantity": max(parse_int_input(card_qty, 1), 1),
        "cote": max(parse_float_input(card_cote, 0.0), 0.0),
        "condition": card_condition or "NM",
        "special": ", ".join(card_specials) if isinstance(card_specials, list) else str(card_specials or ""),
        "note": str(card_note or "").strip(),
        "image_url": image_url,
        "image_url_en": image_url_en,
        "rarity": rarity,
        "is_collection": bool(is_collection),
    })

def new_uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"

def is_storage_lot(lot):
    return lot.get("is_storage") or lot.get("nom") in ("Stockage", "📈 Stockage")

def card_available_qty(card):
    if card.get("is_collection_keep"):
        return 0
    return max(
        int(card.get("quantity", 0))
        - int(card.get("sold_quantity", 0))
        - int(card.get("stored_quantity", 0)),
        0,
    )
def collection_image_candidate_is_valid(url):
    url = str(url or "").strip()
    if not url:
        return False
    if url.startswith("card_images/"):
        return os.path.exists(url)
    if "tcgdex.net" not in url:
        return True
    # Skip network validation for TCGDex URLs - assume they're valid to avoid slow checks
    # The fallback mechanism in collection_image_html will handle broken images
    return True

def collection_paid_total_for_app(card, lot):
    return collection_paid_total(
        card,
        lot,
        calc_cout_lot_func=calc_cout_lot,
        effective_purchase_price_func=effective_purchase_price,
    )

def render_collection_image_for_app(card, width="100%", style="border-radius:12px;box-shadow:0 4px 12px rgba(15,23,42,0.18);"):
    with perf_timer("images Collection", counter="images_collection"):
        return render_collection_image_html(
            card,
            width=width,
            style=style,
            proxy_img_func=proxy_img,
            cached_image_candidates_func=collection_cached_image_candidates,
            session_state=st.session_state,
            placeholder_token=COLLECTION_IMAGE_PLACEHOLDER,
        )

def lot_remaining_including_storage(lots, lot):
    return sum(card_available_qty(c) for c in lot.get("cards", [])) + storage_remaining_for_lot(lots, lot)

def ensure_card_ids(d):
    """Ajoute des identifiants internes stables aux lots et aux cartes."""
    changed = False
    seen_lots = set()
    seen_cards = set()
    for lot in d.get("lots", []):
        if not lot.get("lot_uid") or lot.get("lot_uid") in seen_lots:
            lot["lot_uid"] = new_uid("lot")
            changed = True
        seen_lots.add(lot["lot_uid"])
        for card in lot.get("cards", []):
            if not card.get("card_uid") or card.get("card_uid") in seen_cards:
                card["card_uid"] = new_uid("card")
                changed = True
            seen_cards.add(card["card_uid"])
    return changed

def ensure_storage_lot(d):
    """Garantit un lot permanent pour les cartes gardees en speculation."""
    for i, lot in enumerate(d.get("lots", [])):
        if is_storage_lot(lot):
            lot["is_storage"] = True
            lot["nom"] = "📈 Stockage"
            lot.setdefault("prix_achat", 0.)
            lot.setdefault("cards", [])
            lot.setdefault("ventes", [])
            return i
    d.setdefault("lots", []).append({
        "nom": "📈 Stockage",
        "prix_achat": 0.,
        "cards": [],
        "ventes": [],
        "created": datetime.now().isoformat(),
        "is_storage": True,
    })
    return len(d["lots"]) - 1

def resolve_lot_idx(cd, lot_uid=None, fallback_idx=None):
    if lot_uid:
        for idx, lot in enumerate(cd.get("lots", [])):
            if lot.get("lot_uid") == lot_uid:
                return idx
    if fallback_idx is not None and 0 <= fallback_idx < len(cd.get("lots", [])):
        return fallback_idx
    return None

def resolve_card_ref(cd, item):
    lot_idx = resolve_lot_idx(cd, item.get("lot_uid"), item.get("lot_idx"))
    if lot_idx is None:
        return None, None, None, None
    lot = cd["lots"][lot_idx]
    card_uid = item.get("card_uid")
    if card_uid:
        for card_idx, card in enumerate(lot.get("cards", [])):
            if card.get("card_uid") == card_uid:
                return lot_idx, card_idx, lot, card
    fallback_idx = item.get("card_idx")
    if fallback_idx is not None and 0 <= fallback_idx < len(lot.get("cards", [])):
        return lot_idx, fallback_idx, lot, lot["cards"][fallback_idx]
    return lot_idx, None, lot, None

def save_activity_state():
    data = {
        "bulk_cart": st.session_state.get("bulk_cart", []),
        "swap_cart_give": st.session_state.get("swap_cart_give", []),
        "swap_cart_receive": st.session_state.get("swap_cart_receive", []),
    }
    safe_write_json(ACTIVITY_STATE_FILE, data, indent=2)

def load_activity_state():
    if not os.path.exists(ACTIVITY_STATE_FILE):
        return
    try:
        with open(ACTIVITY_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in ("bulk_cart", "swap_cart_give", "swap_cart_receive"):
            if key not in st.session_state and isinstance(data.get(key), list):
                st.session_state[key] = data[key]
    except Exception as e:
        print(f"Activite sauvegardee illisible: {e}")

def cr(l):
    if l.get("is_trade") or l.get("nom") in ("Trade", "🔄 Trade"):
        return 0.
    r=0.
    for v in l.get("ventes",[]):
        r+=v.get("price",0.)
    for c in l.get("cards",[]):
        for s in c.get("sold_entries",[]):
            r+=s.get("price",0.)
    return r

def cp(l):
    return cr(l)-l.get("prix_achat",0.)

def crp(l):
    c=l.get("prix_achat",0.)
    return 100. if c==0 else (cr(l)/c)*100

def ilp(l):
    return cp(l)>=0

def is_trade_lot(lot):
    return lot.get("is_trade") or lot.get("nom") in ("Trade", "🔄 Trade")

def ensure_trade_lot(d):
    """Garantit un lot unique pour les cartes recues en echange."""
    for i, lot in enumerate(d.get("lots", [])):
        if is_trade_lot(lot):
            lot["is_trade"] = True
            lot["nom"] = "🔄 Trade"
            lot.setdefault("prix_achat", 0.)
            lot.setdefault("cards", [])
            lot.setdefault("ventes", [])
            return i
    d.setdefault("lots", []).append({
        "nom": "🔄 Trade",
        "prix_achat": 0.,
        "cards": [],
        "ventes": [],
        "created": datetime.now().isoformat(),
        "is_trade": True,
    })
    return len(d["lots"]) - 1

def ensure_system_lots(d):
    changed_before = json.dumps(d.get("lots", []), ensure_ascii=False, sort_keys=True)
    ensure_trade_lot(d)
    ensure_storage_lot(d)
    ensure_card_ids(d)
    return json.dumps(d.get("lots", []), ensure_ascii=False, sort_keys=True) != changed_before

def trade_stock_value_for_lot(lots, lot_idx):
    """Part de valeur du stock Trade attribuee a un lot contributeur."""
    value = 0.
    for trade_lot in lots:
        if not is_trade_lot(trade_lot):
            continue
        for card in trade_lot.get("cards", []):
            repartition = card.get("exchange_repartition", {})
            if not repartition:
                continue
            remaining = max(int(card.get("quantity", 0)) - int(card.get("sold_quantity", 0)), 0)
            if remaining <= 0:
                continue
            total_repartition = sum(float(v) for v in repartition.values()) or 1.
            part = float(repartition.get(str(lot_idx), 0.)) / total_repartition
            value += remaining * float(card.get("suggested_price", 0.)) * part
    return value

def migrate_open_trade_cards(d):
    """Deplace les cartes d'echange encore en stock vers le lot Trade."""
    trade_idx = ensure_trade_lot(d)
    moved = False
    for li, lot in enumerate(d.get("lots", [])):
        if li == trade_idx or is_trade_lot(lot):
            continue
        kept_cards = []
        for card in lot.get("cards", []):
            remaining = int(card.get("quantity", 0)) - int(card.get("sold_quantity", 0))
            if (card.get("received_by_exchange") and card.get("exchange_repartition")
                    and remaining > 0 and not card.get("sold_entries")):
                d["lots"][trade_idx].setdefault("cards", []).append(card)
                moved = True
            else:
                kept_cards.append(card)
        lot["cards"] = kept_cards
    return moved

@st.dialog("📡 Canal de vente")
def ask_canal(lot_idx, card_idx, qty, price):
    st.markdown(f"**Vente de {qty} carte(s) — {fp(price * qty)}**")
    CANAUX = ["Main propre", "Brocante", "Dexify_TCG", "Pokédeal"]
    canal = st.selectbox("Via quel canal ?", CANAUX)
    c1, c2 = st.columns(2)
    if c1.button("✅ Confirmer", type="primary", width="stretch"):
        scu(lot_idx, card_idx, qty, price, canal)
        st.session_state["last_sale_ok"] = True
        st.rerun()
    if c2.button("❌ Annuler", width="stretch"):
        st.rerun()

def load_app_settings():
    path = "app_settings.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load app settings: {e}")
    return {}

def save_app_settings(settings):
    safe_write_json("app_settings.json", settings, indent=2)

def canal_key(canal):
    raw = normalize_name(str(canal or "")).lower()
    if "dexify" in raw:
        return "dexify"
    if "pokedeal" in raw or ("poke" in raw and "deal" in raw):
        return "pokedeal"
    if "brocante" in raw:
        return "brocante"
    if "main" in raw:
        return "main"
    if "echange" in raw:
        return "echange"
    return raw

def calc_cout_lot(lot, valeur_estimee=None, lot_idx=None):
    """
    coût_vente = (cote_de_la_carte / valeur_estimee_lot) × prix_achat_lot
    valeur_estimee_lot = stock actuel à la cote + cartes vendues à leur cote au moment de la vente
    Le prix de vente réel, négociation incluse, sert ensuite à calculer le bénéfice.
    Pour les cartes reçues par échange, le coût est défini par exchange_repartition[lot_idx].
    """
    prix_lot = effective_purchase_price(lot)
    cards = lot.get("cards", [])

    if valeur_estimee is None or valeur_estimee <= 0:
        stock_val = 0.
        sold_cote = 0.
        for c in cards:
            sold_value, sold_qty = card_sold_cote(c)
            unsold_qty = max(int(c.get("quantity", 0)) - sold_qty, 0)
            stock_val += float(c.get("suggested_price", 0.)) * unsold_qty
            sold_cote += sold_value
        ventes_cote = sum(float(v.get("price", 0.)) for v in lot.get("ventes", []) if not v.get("is_exchange_benefit"))
        valeur_estimee = stock_val + sold_cote + ventes_cote

    valeur_estimee = valeur_estimee or 1.0

    result = []
    for card in cards:
        for se in card.get("sold_entries", []):
            price = float(se.get("price", 0.))
            qty = int(se.get("quantity", 1))
            cote_unit = float(se.get("suggested_price_at_sale", 0.) or card.get("suggested_price", 0.) or 0.)
            if cote_unit <= 0:
                cote_unit = price / max(qty, 1)
            cote_total = cote_unit * qty
            # Lot Divers : coût = purchase_price individuel de la carte
            if lot.get("is_divers") and card.get("purchase_price"):
                cout = float(card["purchase_price"]) * qty
            # Carte reçue par échange avec repartition connue
            elif card.get("received_by_exchange") and card.get("exchange_repartition") and lot_idx is not None:
                cout = float(card["exchange_repartition"].get(str(lot_idx), 0.))
            elif lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
                real_price = float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
                cout = (cote_total / float(lot.get("valeur_totale", 1.) or 1.)) * real_price
            else:
                cout = (cote_total / valeur_estimee) * prix_lot
            result.append((card, se, cout))

    return result, valeur_estimee

def fix_missing_images():
    """Réparer les cartes sans image au démarrage"""
    cd = ld()
    changed = False
    for li, lot in enumerate(cd.get("lots", [])):
        for ci, card in enumerate(lot.get("cards", [])):
            if not card.get("image_url") and card.get("id"):
                try:
                    r = requests.get(f"https://api.tcgdex.net/v2/fr/cards/{card['id']}", timeout=2)
                    if r.status_code == 200:
                        full = r.json()
                        img = full.get("image", "")
                        if not img:
                            set_info = full.get("set", {})
                            set_id = set_info.get("id", "") if isinstance(set_info, dict) else ""
                            local_id = full.get("localId", "")
                            if set_id and local_id:
                                img = f"https://assets.tcgdex.net/fr/{set_id}/{local_id}/high.webp"
                        if img and not any(img.endswith(e) for e in ['.jpg','.png','.webp']):
                            img = f"{img}/high.webp"
                        # Dernier recours pokemontcg.io
                        if not img:
                            img = get_image_fallback(card.get("name",""), card.get("number",""), card.get("set",""))
                        if img:
                            cd["lots"][li]["cards"][ci]["image_url"] = img
                            changed = True
                except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
                    print(f"Warning: Could not fix image for card {card.get('name', 'unknown')}: {e}")
                    pass
    if changed:
        sd(cd)

# ============================================================
# RECHERCHE API
# ============================================================

def check_url_exists(url):
    """Vérifier si une URL existe avec cache pour éviter les appels répétés"""
    cache_key = f"url_check_{url}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    perf_count("network_image_checks")
    try:
        check = requests.head(url, timeout=1)
        result = check.status_code == 200
    except:
        result = False
    st.session_state[cache_key] = result
    return result

def proxy_img(url, url_en=""):
    """Passer les images TCGDex via un proxy pour uniformiser la taille"""
    if not url:
        return url

    url = str(url)
    if url.startswith("card_images/") or url.startswith("card_images\\"):
        try:
            cache_key = ("local", url, os.path.getmtime(url) if os.path.exists(url) else "missing")
        except Exception:
            cache_key = ("local", url, "unknown")
    else:
        cache_key = ("remote", url)

    cache = st.session_state.setdefault("_proxy_img_cache", {})
    if cache_key in cache:
        perf_count("images_proxy_cache_hit")
        return cache[cache_key]

    perf_count("images_proxy")
    if url.startswith("card_images/") or url.startswith("card_images\\"):
        try:
            import base64
            with open(url, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            ext = url.split(".")[-1].lower()
            mime = "image/jpeg" if ext in ["jpg", "jpeg"] else f"image/{ext}"
            result = f"data:{mime};base64,{data}"
        except Exception:
            result = ""
    elif "tcgdex.net" in url:
        if "/ja/" in url:
            result = url
        else:
            result = f"https://wsrv.nl/?url={url}&w=400&fit=inside"
    else:
        result = url

    cache[cache_key] = result
    return result

def img_with_fallback(url, url_en="", width="100%", style="border-radius:12px;"):
    """Afficher une image avec fallback EN si FR échoue"""
    return img_with_fallback_html(url, url_en, width, style, proxy_img_func=proxy_img)

def is_reliable_image_url(url, allow_network=False):
    """Evite les icones cassees : une URL Collection doit vraiment pointer vers une image."""
    url = str(url or "").strip()
    if not url:
        return False
    if url.startswith("data:image/"):
        return True
    if url.startswith("card_images/") or url.startswith("card_images\\"):
        return os.path.exists(url)
    if os.path.exists(url):
        return True

    # En rendu normal, on ne teste pas les URLs distantes : le HTML onerror
    # bascule deja vers le fallback/placeholder sans ralentir la page.
    if not allow_network:
        return url.startswith(("http://", "https://"))

    cache_key = f"image_ok::{url}"
    cache = st.session_state.setdefault("_image_reliability_cache", {})
    if cache_key in cache:
        return cache[cache_key]

    ok = False
    perf_count("network_image_checks")
    try:
        response = requests.head(url, timeout=2, allow_redirects=True)
        content_type = response.headers.get("content-type", "").lower()
        ok = response.status_code == 200 and content_type.startswith("image/")
    except Exception:
        try:
            response = requests.get(url, timeout=2, stream=True, allow_redirects=True)
            content_type = response.headers.get("content-type", "").lower()
            ok = response.status_code == 200 and content_type.startswith("image/")
        except Exception:
            ok = False
    cache[cache_key] = ok
    return ok

def tcgdex_card_image_candidates(card_id, lang):
    """Construit quelques URL TCGDex possibles depuis l'id de carte."""
    card_id = str(card_id or "").strip()
    lang = lang if lang in ("fr", "en", "ja") else "fr"
    if not card_id:
        return []

    candidates = []
    try:
        perf_count("network_tcgdex_image")
        response = requests.get(f"https://api.tcgdex.net/v2/{lang}/cards/{card_id}", timeout=2)
        if response.status_code == 200:
            payload = response.json()
            image = str(payload.get("image", "") or "").strip()
            if image:
                if "tcgdex.net" in image and not image.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    image = f"{image}/high.webp"
                candidates.append(image)
            set_info = payload.get("set", {})
            set_id = set_info.get("id", "") if isinstance(set_info, dict) else ""
            local_id = str(payload.get("localId", "") or "").strip()
            series = tcgdex_series_from_set_id(set_id)
            if set_id and local_id:
                candidates.append(f"https://assets.tcgdex.net/{lang}/{set_id}/{local_id}/high.webp")
                if series:
                    candidates.append(f"https://assets.tcgdex.net/{lang}/{series}/{set_id}/{local_id}/high.webp")
    except Exception:
        pass

    if "-" in card_id:
        set_id, local_id = card_id.rsplit("-", 1)
        series = tcgdex_series_from_set_id(set_id)
        candidates.append(f"https://assets.tcgdex.net/{lang}/{set_id}/{local_id}/high.webp")
        if series:
            candidates.append(f"https://assets.tcgdex.net/{lang}/{series}/{set_id}/{local_id}/high.webp")

    cleaned = []
    for url in candidates:
        if url and url not in cleaned:
            cleaned.append(url)
    return cleaned

@st.cache_data(ttl=3600, show_spinner=False)
def resolve_collection_image_candidates(card_id, card_name, card_num, card_set, lang, allow_network=False):
    """Resolve image candidates for a Collection card with caching to avoid repeated API calls."""
    candidates = []
    
    def add_candidate(url):
        url = str(url or "").strip()
        if url and url not in candidates and is_reliable_image_url(url, allow_network=allow_network):
            candidates.append(url)
    
    if allow_network:
        # Try TCGDex candidates only during an explicit resolution action.
        for candidate_lang in [lang, "fr", "en"]:
            for url in tcgdex_card_image_candidates(card_id, candidate_lang):
                add_candidate(url)
    
    # Try direct URL construction
    if "-" in card_id:
        set_id, local_id = card_id.rsplit("-", 1)
        local_id = card_num or local_id
        series = tcgdex_series_from_set_id(set_id)
        for candidate_lang in [lang, "fr", "en"]:
            add_candidate(f"https://assets.tcgdex.net/{candidate_lang}/{set_id}/{local_id}/high.webp")
            if series:
                add_candidate(f"https://assets.tcgdex.net/{candidate_lang}/{series}/{set_id}/{local_id}/high.webp")
    
    if allow_network:
        # Try fallback lookup only during an explicit resolution action.
        try:
            fallback = get_image_fallback(card_name, card_num, card_set)
            add_candidate(fallback)
        except Exception:
            pass
    
    # Try cache search
    try:
        matches = search_in_cache(card_name, card_num)
        if matches:
            preferred = matches[0]
            target_set = normalize_name(card_set)
            target_id = card_id
            for match_card, match_set in matches:
                if target_id and str(match_card.get("id", "") or "") == target_id:
                    preferred = (match_card, match_set)
                    break
                if target_set and target_set in normalize_name(match_set):
                    preferred = (match_card, match_set)
            enriched = ecd(preferred[0], preferred[1], lang=lang if lang in ("fr", "en", "ja") else "fr")
            for key in ("image_url", "image_url_en"):
                add_candidate(enriched.get(key, ""))
    except Exception:
        pass
    
    return candidates

def collection_cached_image_candidates(card):
    """Recherche locale stricte uniquement : jamais de Raichu normal pour Raichu GX."""
    cache_key = "|".join([
        normalize_name(card.get("name", "")),
        str(card.get("number", "") or "").strip(),
        normalize_name(card.get("set", "")),
        str(card.get("id", "") or "").strip(),
    ])
    local_cache = st.session_state.setdefault("_collection_cached_image_candidates", {})
    if cache_key in local_cache:
        perf_count("collection_image_candidate_cache_hit")
        return list(local_cache[cache_key])

    candidates = []

    def add(url):
        url = normalized_tcgdex_image_url(url)
        if url and url not in candidates:
            candidates.append(url)

    try:
        matches = search_in_cache(card.get("name", ""), str(card.get("number", "") or "").strip())
        for match_card, match_set in matches:
            if not collection_card_exact_match(card, match_card, match_set):
                continue
            for key in ("image", "imageUrl", "image_url", "image_url_en"):
                add(match_card.get(key, ""))
    except Exception:
        pass

    local_cache[cache_key] = list(candidates)
    return candidates

def get_image_fallback(card_name, card_number, set_name):
    """Chercher l'image sur TCGDex EN si FR n'a pas l'image"""
    try:
        # Chercher via l'API TCGDex EN avec le même card id
        # On construit des variantes d'URL EN à tester
        name_clean = normalize_name(card_name)
        
        # Chercher dans le cache pour trouver l'id de la carte
        cards_index = st.session_state.get("cards_index", {})
        card_id = ""
        for idx_name, cards in cards_index.items():
            if name_clean in idx_name or idx_name in name_clean:
                for card, sname, sid in cards:
                    cn = str(card.get("localId","") or card.get("number",""))
                    if cn == str(card_number):
                        card_id = card.get("id","")
                        break
            if card_id:
                break
        
        if card_id:
            # Essai EN
            r = requests.get(f"https://api.tcgdex.net/v2/en/cards/{card_id}", timeout=2)
            if r.status_code == 200:
                full = r.json()
                img = full.get("image","")
                if not img:
                    set_info = full.get("set", {})
                    set_id = set_info.get("id","") if isinstance(set_info, dict) else ""
                    local_id = full.get("localId","")
                    if set_id and local_id:
                        candidate = f"https://assets.tcgdex.net/en/{set_id}/{local_id}/high.webp"
                        check = requests.head(candidate, timeout=1)
                        if check.status_code == 200:
                            img = candidate
                if img:
                    if "tcgdex.net" in img and not any(img.endswith(e) for e in ['.jpg','.png','.webp']):
                        img = f"{img}/high.webp"
                    return img
    except Exception as e:
        pass
    return ""

def afi(n,sn,num):
    """Find card info (M1: set spécifique, M2: retourne None pour popup)"""
    n=n.strip().title()
    sn=sn.strip()
    num=num.strip()
    
    if sn:
        try:
            r=requests.get(f"https://api.tcgdex.net/v2/fr/sets/{sn}",timeout=2)
            if r.status_code==200:
                sd=r.json()
                for c in sd.get("cards",[]):
                    cn=c.get("name","")
                    cnu=str(c.get("localId","")or c.get("number",""))
                    if cn.lower()==n.lower():
                        if not num or cnu==num or cnu.zfill(3)==num.zfill(3):
                            return c,sd.get("name","")
        except:
            pass
    
    return None,None

def sgt(n,num=None,lang="fr"):
    """Search global (via cache + fallback API si peu de résultats)"""
    results = search_in_cache(n, num)
    
    if not results:
        try:
            api_lang = lang if lang in ["fr","en","ja"] else "fr"
            r = requests.get(f"https://api.tcgdex.net/v2/{api_lang}/cards?name={n}", timeout=3)
            if r.status_code == 200:
                cards = r.json()
                for card in cards[:20]:
                    cnum = str(card.get("localId","") or card.get("number",""))
                    if num and cnum != num and cnum.zfill(3) != num.zfill(3):
                        continue
                    results.append((card, card.get("set",{}).get("name","") if isinstance(card.get("set"),dict) else ""))
        except:
            pass
    
    return results

def ecd(c, s, lang="fr"):
    """Enrichir données carte"""
    cache_key = f"ecd_{lang}_{c.get('id','')}_{s}_{c.get('localId') or c.get('number') or ''}"
    if cache_key in st.session_state:
        return json.loads(json.dumps(st.session_state[cache_key], ensure_ascii=False))

    img_url = c.get("image") or c.get("imageUrl") or c.get("image_url") or ""
    if not img_url and "images" in c:
        imgs = c.get("images", {})
        img_url = imgs.get("large") or imgs.get("small") or ""

    set_id = c.get("set", {}).get("id", "") if isinstance(c.get("set"), dict) else ""
    local_id = c.get("localId") or c.get("number") or ""
    card_id = c.get("id", "")

    # Construction URL directe depuis les données du cache
    if not img_url and set_id and local_id:
        img_url = f"https://assets.tcgdex.net/{lang}/{set_id}/{local_id}/high.webp"

    # Fallback EN si la langue demandée n'a pas d'image (plumeline, etc.)
    if img_url and lang == "fr" and set_id and local_id:
        # On stocke aussi l'URL EN comme fallback dans le proxy
        img_url_en = f"https://assets.tcgdex.net/en/{set_id}/{local_id}/high.webp"
    else:
        img_url_en = ""

    # Si toujours vide (pas de set_id dans le cache), appel API une seule fois
    if not img_url and card_id:
        try:
            for try_lang in ([lang, "en"] if lang != "ja" else ["ja", "en"]):
                r = requests.get(f"https://api.tcgdex.net/v2/{try_lang}/cards/{card_id}", timeout=3)
                if r.status_code == 200:
                    img = r.json().get("image","")
                    if img:
                        if not any(img.endswith(e) for e in ['.jpg','.png','.webp']):
                            img = f"{img}/high.webp"
                        img_url = img
                        break
        except:
            pass

    if img_url and "tcgdex.net" in img_url and not any(img_url.endswith(e) for e in ['.jpg','.png','.webp']):
        img_url = f"{img_url}/high.webp"

    enriched = {
        "card_uid": new_uid("card"),
        "id": card_id,
        "name": c.get("name",""),
        "set": s,
        "number": str(local_id),
        "rarity": c.get("rarity",""),
        "image_url": img_url,
        "image_url_en": img_url_en,
        "lang": lang,
        "quantity": 0,
        "sold_quantity": 0,
        "condition": "NM",
        "suggested_price": 0.,
        "is_reverse": False,
        "is_ed1": False,
        "sold_entries": []
    }
    st.session_state[cache_key] = json.loads(json.dumps(enriched, ensure_ascii=False))
    return json.loads(json.dumps(enriched, ensure_ascii=False))

def set_current_page(page):
    st.session_state.current_page = page
    st.session_state["scroll_top_once"] = True

def render_with_perf(label, render_func, *args, **kwargs):
    with perf_timer(label):
        return render_func(*args, **kwargs)
    if page == "Vente":
        st.session_state["sale_scroll_top_pending"] = True
    if page != "Lots":
        st.session_state.pop("active_lot_ix", None)
        for key in list(st.session_state.keys()):
            if str(key).startswith("lot_expanded_"):
                st.session_state.pop(key, None)
    if page != "Historique":
        st.session_state["history_visible_count"] = 40

def dc(li,ci):
    """Delete card"""
    cd=ld()
    cd["lots"][li]["cards"].pop(ci)
    sd(cd)
    return True,""

def update_card_quantity(li, ci):
    cd = ld()
    if li >= len(cd.get("lots", [])) or ci >= len(cd["lots"][li].get("cards", [])):
        return
    card = cd["lots"][li]["cards"][ci]
    new_q = int(st.session_state.get(f"qty_edit_{li}_{ci}", card.get("quantity", 1)))
    sold_q = int(card.get("sold_quantity", 0))
    card["quantity"] = max(new_q, sold_q)
    sd(cd)

def transfer_card_to_storage(li, ci, qty, storage_cote=None):
    cd = ld()
    storage_idx = ensure_storage_lot(cd)
    if li == storage_idx:
        return False, "Cette carte est deja dans le lot Stockage."
    if li >= len(cd.get("lots", [])) or ci >= len(cd["lots"][li].get("cards", [])):
        return False, "Carte introuvable."
    source_card = cd["lots"][li]["cards"][ci]
    available = card_available_qty(source_card)
    qty = min(max(int(qty), 1), available)
    if qty <= 0:
        return False, "Stock insuffisant."

    moved_card = dict(source_card)
    moved_card["card_uid"] = new_uid("card")
    moved_card["quantity"] = qty
    moved_card["sold_quantity"] = 0
    moved_card["sold_entries"] = []
    moved_card["stored_from_lot"] = cd["lots"][li].get("nom", "")
    moved_card["stored_from_lot_uid"] = cd["lots"][li].get("lot_uid")
    moved_card["stored_date"] = datetime.now().isoformat()[:10]
    try:
        storage_cote = float(storage_cote) if storage_cote is not None else float(source_card.get("suggested_price", 0.) or 0.)
    except:
        storage_cote = float(source_card.get("suggested_price", 0.) or 0.)
    moved_card["storage_cote_at_add"] = storage_cote

    source_card["stored_quantity"] = int(source_card.get("stored_quantity", 0)) + qty
    source_card.setdefault("storage_entries", []).append({
        "date": datetime.now().isoformat()[:10],
        "quantity": qty,
        "storage_lot_uid": cd["lots"][storage_idx].get("lot_uid"),
        "cote_at_storage": storage_cote,
    })

    cd["lots"][storage_idx].setdefault("cards", []).append(moved_card)
    sd(cd)
    return True, "Carte transferee vers Stockage."


configure_card_add(globals())
configure_sales_actions(globals())


# ============================================================
# UI
# ============================================================

st.set_page_config(layout="wide",page_title="Pokestock",page_icon="🎴")

try:
    query_mobile = str(st.query_params.get("mobile", "")).lower() in ("1", "true", "yes", "oui")
except Exception:
    query_mobile = False
try:
    query_perf = str(st.query_params.get("perf", "")).lower() in ("1", "true", "yes", "oui")
except Exception:
    query_perf = False
if "mobile_mode" not in st.session_state:
    st.session_state["mobile_mode"] = query_mobile
elif query_mobile:
    st.session_state["mobile_mode"] = True
if query_perf:
    st.session_state["perf_debug_enabled"] = True

def is_mobile_mode():
    return bool(st.session_state.get("mobile_mode", False))

def run_html(body, height=0):
    """Injecte les petits scripts d'interface avec l'API Streamlit actuelle."""
    st.html(body, unsafe_allow_javascript=True)

run_html("""
<script>
(function() {
    const win = window.parent && window.parent !== window ? window.parent : window;
    const doc = win.document;
    const url = new URL(win.location.href);
    const alreadySet = ["1", "true", "yes", "oui"].includes((url.searchParams.get("mobile") || "").toLowerCase());
    const looksMobile = win.matchMedia("(max-width: 760px), (pointer: coarse) and (max-width: 900px)").matches;
    if (doc && doc.body) doc.body.classList.toggle("codex-mobile-mode", alreadySet || looksMobile);
    if (looksMobile && !alreadySet) {
        url.searchParams.set("mobile", "1");
        if (!url.searchParams.get("page")) url.searchParams.set("page", "vente");
        win.location.replace(url.toString());
    }
    if (doc && doc.body && (alreadySet || looksMobile)) {
        setInterval(function() {
            doc.querySelectorAll('img').forEach(function(img) {
                const src = img.getAttribute('src') || '';
                const style = win.getComputedStyle(img);
                const isFixed = style.position === 'fixed' || style.position === 'absolute';
                if (isFixed && (src.includes('/pokemon/other/official-artwork/25') || src.includes('/pokemon/other/official-artwork/133'))) {
                    img.style.setProperty('display', 'none', 'important');
                    img.style.setProperty('opacity', '0', 'important');
                }
            });
        }, 1000);
    }
})();
</script>
""")

def require_app_password():
    from cloud import _secret_value
    expected_password = _secret_value("APP_PASSWORD")
    auth_token = hashlib.sha256(f"pokestock:{expected_password}".encode("utf-8")).hexdigest()[:24] if expected_password else ""
    try:
        query_auth = str(st.query_params.get("auth", ""))
    except Exception:
        query_auth = ""
    if query_auth and auth_token and query_auth == auth_token:
        st.session_state["app_authenticated"] = True
    if not expected_password or st.session_state.get("app_authenticated"):
        return
    st.title("Pokestock")
    with st.form("password_form"):
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Entrer", type="primary")
    if submitted:
        if password == expected_password:
            st.session_state["app_authenticated"] = True
            try:
                st.query_params["auth"] = auth_token
            except Exception:
                pass
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")
    st.stop()

require_app_password()

if "cards_index" not in st.session_state:
    with st.spinner("Chargement des données..."):
        load_cards_cache(allow_network=False)

load_activity_state()

if "weekly_backup_checked" not in st.session_state:
    st.session_state["weekly_backup_checked"] = True
    try:
        weekly_backup_path = maybe_create_weekly_backup()
        if weekly_backup_path:
            st.session_state["last_auto_backup_message"] = f"Sauvegarde hebdo créée : {os.path.basename(weekly_backup_path)}"
    except Exception as e:
        st.session_state["last_auto_backup_message"] = f"Sauvegarde hebdo impossible : {e}"

if st.session_state.get("current_page") != "Lots":
    st.session_state.pop("active_lot_ix", None)
    run_html("""
    <script>
    (function() {
        const doc = parent.document;
        const shield = doc.getElementById('codex-add-card-shield');
        if (shield) shield.remove();
        doc.querySelectorAll('[data-codex-add-sticky="1"]').forEach(function(part) {
            part.removeAttribute('data-codex-add-sticky');
            [
                'position','top','z-index','background','box-shadow','padding',
                'margin','border','border-radius','width','max-width','left','right','outline'
            ].forEach(function(prop) { part.style.removeProperty(prop); });
            part.querySelectorAll('button').forEach(function(btn) {
                btn.style.removeProperty('width');
            });
        });
    })();
    </script>
    """, height=0)

if "system_lots_ready" not in st.session_state:
    cd_boot = ld()
    if ensure_system_lots(cd_boot):
        st.session_state["system_lots_autofix_pending"] = True
    st.session_state["system_lots_ready"] = True

if st.session_state.pop("scroll_top_once", False):
    run_html("<script>requestAnimationFrame(()=>parent.window.scrollTo({top:0,left:0,behavior:'instant'}));</script>", height=0)

# Réparer les images manquantes une seule fois (pas à chaque démarrage)
if "images_fixed" not in st.session_state:
    st.session_state["images_fixed"] = True
    # Ne pas reparer/sauvegarder automatiquement au demarrage : cela ecrivait
    # data.json au simple affichage. Les corrections d'images doivent rester
    # declenchees par une vraie action utilisateur.

# JS : soumettre les champs de recherche à chaque frappe
run_html("""
<script>
function autoSubmitSearch() {
    const inputs = parent.document.querySelectorAll(
        '[data-testid="stTextInput"] input[type="text"]'
    );
    inputs.forEach(input => {
        if (input.dataset.autoSearch) return;
        // Cibler uniquement les barres de recherche par leur placeholder
        const searchPlaceholders = [
            "chercher une carte",
            "nom de la carte",
            "nom de carte",
            "chercher une carte dans tous les lots"
        ];
        const placeholder = (input.placeholder || "").toLowerCase();
        const isSearch = searchPlaceholders.some(p => placeholder.includes(p));
        if (!isSearch) return;
        
        input.dataset.autoSearch = "true";
        input.addEventListener('input', function() {
            clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(() => {
                this.dispatchEvent(new KeyboardEvent('keypress', {
                    key: 'Enter', code: 'Enter', keyCode: 13,
                    which: 13, bubbles: true
                }));
            }, 300);
        });
    });
}
// setInterval limité aux barres de recherche uniquement - ne cause pas de rerender Streamlit
setInterval(autoSubmitSearch, 1000);
</script>
""", height=0)

if is_mobile_mode():
    st.markdown(
        '<style>.ps-app-header { display: none !important; }</style>',
        unsafe_allow_html=True,
    )

try:
    import os
    import base64
    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    logo_path = os.path.join(script_dir, "logo_optimized.png")
    if not os.path.exists(logo_path):
        logo_path = os.path.join(script_dir, "logo_pikachu_transparent.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        logo_src = f"data:image/png;base64,{logo_b64}"
    else:
        logo_src = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/25.png"
except:
    logo_src = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/25.png"

try:
    _early_query_page = str(st.query_params.get("page", "")).lower()
except Exception:
    _early_query_page = ""
wrapped_story_active = (
    st.session_state.get("wrapped_open", False)
    and (st.session_state.get("current_page") == "Wrapped" or _early_query_page in {"wrapped", "pokestock-wrapped"})
)

if not wrapped_story_active:
    st.markdown(
        render_app_header(logo_src, mobile=is_mobile_mode()),
        unsafe_allow_html=True,
    )

st.markdown(inject_theme(mobile=is_mobile_mode()), unsafe_allow_html=True)
if is_mobile_mode():
    st.markdown(inject_mobile_overrides(), unsafe_allow_html=True)

st.markdown(inject_functional_css(), unsafe_allow_html=True)

st.markdown("""
<style>
.mobile-card-grid {
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
    gap: 0.18rem !important;
    width: 100% !important;
    margin: 0.35rem 0 0.7rem 0 !important;
}
.mobile-card-tile {
    min-width: 0 !important;
    overflow: hidden !important;
    background: rgba(255,255,255,0.78) !important;
    border: 1px solid #dbe4f0 !important;
    border-radius: 7px !important;
    padding: 0.08rem !important;
}
.mobile-card-tile.sold {
    opacity: 0.42 !important;
    filter: grayscale(100%) !important;
}
.mobile-card-imgbox {
    width: 100% !important;
    height: auto !important;
    min-height: 0 !important;
    display: block !important;
    overflow: visible !important;
    border-radius: 6px !important;
    background: transparent !important;
}
.mobile-card-imgbox img {
    width: 100% !important;
    height: auto !important;
    max-height: none !important;
    max-width: 100% !important;
    object-fit: contain !important;
    display: block !important;
    border-radius: 6px !important;
}
.mobile-card-placeholder {
    width: 100% !important;
    height: 100% !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    color: #94a3b8 !important;
    font-size: 0.75rem !important;
    background: #f8fafc !important;
}
.mobile-card-name {
    margin-top: 0.08rem !important;
    font-size: 0.68rem !important;
    line-height: 1.05 !important;
    min-height: 0.72rem !important;
    font-weight: 800 !important;
    color: #0f172a !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}
.mobile-card-meta {
    font-size: 0.62rem !important;
    line-height: 1.05 !important;
    min-height: 0.66rem !important;
    color: #64748b !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}
@media (max-width: 760px), (pointer: coarse) and (max-width: 900px) {
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div,
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div,
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div,
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div + div {
        width: 100% !important;
        max-width: 100% !important;
        left: 0 !important;
        right: 0 !important;
        overflow: hidden !important;
        box-sizing: border-box !important;
        position: static !important;
        top: auto !important;
        margin: 0 !important;
        padding: 0.12rem 0.35rem !important;
    }
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div [data-testid="stHorizontalBlock"],
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div [data-testid="stHorizontalBlock"],
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div [data-testid="stHorizontalBlock"],
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div + div [data-testid="stHorizontalBlock"] {
        display: grid !important;
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        gap: 0.12rem !important;
        width: 100% !important;
        max-width: 100% !important;
    }
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div [data-testid="column"],
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div [data-testid="column"],
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div [data-testid="column"],
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div + div [data-testid="column"] {
        min-width: 0 !important;
        width: auto !important;
        max-width: 100% !important;
        padding: 0 !important;
    }
    img[src*="wsrv.nl"],
    img[src*="tcgdex.net"] {
        width: 100% !important;
        height: auto !important;
        max-height: none !important;
        max-width: 100% !important;
        object-fit: contain !important;
    }
    .codex-floating-cart {
        position: fixed !important;
        right: 0.85rem !important;
        bottom: calc(5.8rem + env(safe-area-inset-bottom, 0px)) !important;
        width: 3.2rem !important;
        height: 3.2rem !important;
        border-radius: 999px !important;
        background: #22c55e !important;
        color: #ffffff !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-decoration: none !important;
        font-size: 1.35rem !important;
        font-weight: 900 !important;
        z-index: 9500 !important;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.28) !important;
        border: 3px solid #ffffff !important;
    }
    .codex-floating-cart span {
        position: absolute !important;
        top: -0.35rem !important;
        right: -0.35rem !important;
        min-width: 1.25rem !important;
        height: 1.25rem !important;
        padding: 0 0.22rem !important;
        border-radius: 999px !important;
        background: #ef4444 !important;
        color: #ffffff !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 0.68rem !important;
        line-height: 1 !important;
        border: 2px solid #ffffff !important;
    }
}
.codex-floating-cart {
    display: none;
}
@media (max-width: 760px), (pointer: coarse) and (max-width: 900px) {
    .codex-floating-cart {
        position: fixed !important;
        right: 0.85rem !important;
        bottom: calc(5.8rem + env(safe-area-inset-bottom, 0px)) !important;
        width: 3.35rem !important;
        height: 3.35rem !important;
        border-radius: 999px !important;
        background: #22c55e !important;
        color: #ffffff !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-decoration: none !important;
        font-size: 1.45rem !important;
        font-weight: 900 !important;
        z-index: 2147483000 !important;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.32) !important;
        border: 3px solid #ffffff !important;
    }
    .codex-floating-cart span {
        position: absolute !important;
        top: -0.45rem !important;
        right: -0.45rem !important;
        min-width: 1.35rem !important;
        height: 1.35rem !important;
        padding: 0 0.25rem !important;
        border-radius: 999px !important;
        background: #ef4444 !important;
        color: #ffffff !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 0.72rem !important;
        line-height: 1 !important;
        border: 2px solid #ffffff !important;
    }
}
</style>
""", unsafe_allow_html=True)

if "current_page" not in st.session_state:
    try:
        query_page = str(st.query_params.get("page", "")).lower()
    except Exception:
        query_page = ""
    page_map = {
        "vente": "Vente",
        "echange": "Vente",
        "échange": "Vente",
        "lots": "Lots",
        "collection": "Collection",
        "estimations": "Estimations",
        "estimation": "Estimations",
        "annonces": "Annonces Vinted",
        "annonces-vinted": "Annonces Vinted",
        "vinted": "Annonces Vinted",
        "historique": "Historique",
        "stats": "Statistiques",
        "statistiques": "Statistiques",
        "wrapped": "Wrapped",
        "pokestock-wrapped": "Wrapped",
        "compteurs": "Compteurs",
        "archives": "Archivés",
    }
    st.session_state.current_page = page_map.get(query_page, "Vente" if is_mobile_mode() else "Accueil")

perf_reset_rerun()

if not wrapped_story_active:
    with st.sidebar:
        st.markdown(render_sidebar_brand(logo_src, APP_BUILD), unsafe_allow_html=True)
        with perf_timer("gst() call", counter="gst_call"):
            sts = gst()
        sidebar_stats = [
            ("Vendues", str(sts["sold_cards"])),
            ("En stock", str(sts["remaining_cards"])),
            ("Valeur stock", fp(sts["stock_value"])),
            ("CA", fp(sts["total_revenue"])),
            ("Bénéfice", fp(sts["total_profit"])),
        ]
        with st.container():
            for label, value in sidebar_stats:
                st.metric(label, value)
        for section in NAV_SECTIONS:
            st.markdown(
                f'<div class="ps-nav-section-label">{section["label"]}</div>',
                unsafe_allow_html=True,
            )
            for page, label, icon in section["items"]:
                btn_type = "primary" if st.session_state.current_page == page else "secondary"
                st.button(
                    f"{icon}  {label}",
                    width="stretch",
                    key=f"nav_{page.lower()}",
                    type=btn_type,
                    on_click=set_current_page,
                    args=(page,),
                )
        st.markdown("---")
        with st.expander("⚙️ Paramètres", expanded=False):
            st.toggle("📱 Mode mobile", key="mobile_mode", help="Affichage compact pour vendre depuis le téléphone.")
            st.toggle(
                "Logs performance console",
                key="perf_debug_enabled",
                help="Affiche des mesures [PERF] dans la console. Desactive par defaut.",
            )
            cloud_notice = st.session_state.get("cloud_sync_notice")
            if cloud_notice and not st.session_state.get("cloud_sync_notice_seen", False):
                st.caption(f"Cloud protégé : {cloud_notice}")
                st.session_state["cloud_sync_notice_seen"] = True
            cloud_ready, cloud_message = cloud_sync_status()
            if cloud_ready:
                local_lots_count = len((st.session_state.get("data_cache") or {}).get("lots", []))
                cloud_meta = load_cloud_json_meta(SUPABASE_DATA_KEY)
                cloud_lots = cloud_meta.get("lots_count")
                cloud_lots_label = "?" if cloud_lots is None else str(cloud_lots)
                updated_at = cloud_meta.get("updated_at") or "date inconnue"
                st.caption(f"☁️ {cloud_message} · local {local_lots_count} lot(s) · cloud {cloud_lots_label} lot(s)")
                st.caption(f"Dernière synchro cloud : {updated_at}")
                sync_status = st.session_state.get("cloud_sync_status") or {}
                sync_entry = cloud_sync_entry(SUPABASE_DATA_KEY)
                if sync_status.get("message"):
                    st.caption(f"Statut : {sync_status.get('message')}")
                if sync_entry.get("last_read_at") or sync_entry.get("last_save_at"):
                    st.caption(
                        "Dernière lecture cloud : "
                        f"{sync_entry.get('last_read_at', 'jamais')} · "
                        f"dernier envoi : {sync_entry.get('last_save_at', 'jamais')}"
                    )
                conflict = st.session_state.get("cloud_sync_conflict")
                if conflict:
                    st.warning(conflict.get("message", "Conflit local/cloud détecté."))
                    if st.button("Récupérer la version cloud", width="stretch", key="resolve_cloud_conflict_pull"):
                        result = pull_data_from_cloud()
                        if result.get("ok"):
                            st.success(result.get("message", "Version cloud récupérée."))
                            st.session_state.pop("cloud_sync_conflict", None)
                            st.rerun()
                        else:
                            st.error(result.get("message", "Récupération cloud impossible."))
                    if st.button("Conserver la version locale", width="stretch", key="resolve_cloud_conflict_keep_local"):
                        update_cloud_sync_state(SUPABASE_DATA_KEY, data=st.session_state.get("data_cache"), source="local", dirty=True)
                        st.session_state.pop("cloud_sync_conflict", None)
                        st.info("Version locale conservée. Aucun envoi cloud automatique n'a été fait.")
                        st.rerun()
                if st.button("Récupérer la dernière version cloud", width="stretch", key="pull_data_from_cloud"):
                    result = pull_data_from_cloud()
                    if result.get("ok"):
                        summary = result.get("summary") or {}
                        st.success(f"{result.get('message')} ({summary.get('lots', '?')} lot(s))")
                        st.session_state.pop("cloud_sync_conflict", None)
                        st.rerun()
                    else:
                        st.error(result.get("message", "Récupération cloud impossible."))
                confirm_cloud_push = st.checkbox(
                    "Confirmer l'envoi des données locales vers le cloud",
                    key="confirm_push_data_to_cloud",
                    help="Utilise ce bouton seulement quand le PC contient la version complète à envoyer au téléphone.",
                )
                if st.button("☁️ Envoyer les données locales vers le cloud", width="stretch", key="push_data_to_cloud", disabled=not confirm_cloud_push):
                    local_data_for_cloud = load_local_data_file_for_cloud_push()
                    if local_data_for_cloud and save_cloud_json(SUPABASE_DATA_KEY, local_data_for_cloud):
                        update_cloud_sync_state(SUPABASE_DATA_KEY, data=local_data_for_cloud, source="local", dirty=False, last_save=utc_now_iso())
                        st.success("Données envoyées dans le cloud.")
                    else:
                        st.error(st.session_state.get("cloud_sync_error", "Synchronisation impossible."))
            else:
                st.caption(f"☁️ Cloud non prêt : {cloud_message}")
                if st.button("Tester le cloud", width="stretch", key="test_cloud_connection"):
                    st.session_state.pop("cloud_sync_error", None)
                    if hasattr(get_supabase_client, "clear"):
                        get_supabase_client.clear()
                    st.rerun()
            backup_state = _load_backup_state()
            last_weekly_path = backup_state.get("last_weekly_backup_path", "")
            if st.session_state.get("last_auto_backup_message"):
                st.caption(f"🛡️ {st.session_state['last_auto_backup_message']}")
            elif last_weekly_path:
                st.caption(f"🛡️ Dernière sauvegarde : {os.path.basename(last_weekly_path)}")
            else:
                st.caption("🛡️ Sauvegarde locale prête")
            if st.button("🛡️ Sauvegarde maintenant", width="stretch", key="manual_local_backup"):
                try:
                    path, copied = create_local_backup("manual", include_images=True)
                    cleanup_old_backups()
                    st.success(f"Sauvegarde créée : {os.path.basename(path)}")
                except Exception as e:
                    st.error(f"Sauvegarde impossible : {e}")

if st.session_state.get("current_page") != "Vente":
    run_html("""
    <script>
    (function(){
        const btn = parent.document.getElementById('codex-floating-cart-button');
        if (btn) btn.remove();
    })();
    </script>
    """, height=0)


# ============================================================
# PAGE ACCUEIL
# ============================================================
if st.session_state.current_page=="Accueil":
    render_with_perf(
        "page Accueil",
        render_home_page,
        sts=sts,
        ld_func=ld,
        fp_func=fp,
        normalize_name_func=normalize_name,
        proxy_img_func=proxy_img,
        render_page_header_func=render_page_header,
        render_kpi_card_func=render_kpi_card,
        kpi_accents=KPI_ACCENTS,
        set_current_page_func=set_current_page,
    )


# ============================================================
# PAGE VENTE
# ============================================================
elif st.session_state.current_page=="Vente":
    render_with_perf("page Vente / Echange", render_sales_page, globals())

# ============================================================
# PAGE LOTS
# ============================================================
elif st.session_state.current_page=="Lots":
    render_with_perf("page Lots", render_lots_page, globals())

# ============================================================
# PAGE HISTORIQUE
# ============================================================
elif st.session_state.current_page=="Collection":
    render_with_perf(
        "page Collection",
        render_collection_page,
        ld_func=ld,
        add_collection_card_func=lambda **kwargs: add_direct_collection_card(
            **kwargs,
            ld_func=ld,
            sd_func=sd,
            acm_func=acm,
        ),
        add_collection_batch_func=lambda **kwargs: add_collection_batch_cards(
            **kwargs,
            ld_func=ld,
            sd_func=sd,
        ),
        delete_collection_card_func=lambda lot_idx, card_idx, card_uid: delete_collection_card_from_system(
            lot_idx,
            card_idx,
            card_uid,
            ld_func=ld,
            sd_func=sd,
            backup_func=create_local_backup,
        ),
        remove_collection_status_func=lambda lot_idx, card_idx, card_uid: remove_collection_status_from_lot(
            lot_idx,
            card_idx,
            card_uid,
            ld_func=ld,
            sd_func=sd,
            backup_func=create_local_backup,
        ),
        save_collection_manual_image_func=lambda lot_idx, card_idx, card_uid, **kwargs: save_collection_manual_image(
            lot_idx,
            card_idx,
            card_uid,
            ld_func=ld,
            sd_func=sd,
            backup_func=create_local_backup,
            **kwargs,
        ),
        render_card_choice_popups_func=render_card_choice_popups,
        run_html_func=run_html,
        render_page_header_func=render_page_header,
        is_collection_system_lot_func=is_collection_system_lot,
        collection_current_value_func=collection_current_value,
        collection_paid_total_func=collection_paid_total_for_app,
        collection_has_manual_image_func=collection_has_manual_image,
        collection_image_needs_manual_func=collection_image_needs_manual,
        collection_image_html_func=render_collection_image_for_app,
        card_status_badges_func=card_status_badges,
        normalize_name_func=normalize_name,
        fp_func=fp,
        is_mobile_mode_func=is_mobile_mode,
        perf_count_func=perf_count,
        search_in_cache_func=search_in_cache,
    )

elif st.session_state.current_page=="Estimations":
    render_with_perf(
        "page Estimations",
        render_estimations_page,
        load_estimations_func=load_estimations,
        save_estimations_func=save_estimations,
        add_estimation_card_func=add_estimation_card,
        estimation_totals_func=estimation_totals,
        ld_func=ld,
        sd_func=sd,
        fetch_listing_preview_image_func=fetch_listing_preview_image,
        cardmarket_search_url_func=cardmarket_search_url,
        search_in_cache_func=search_in_cache,
        proxy_img_func=proxy_img,
        img_with_fallback_func=img_with_fallback,
        render_page_header_func=render_page_header,
        fp_func=fp,
        normalize_name_func=normalize_name,
        parse_float_input_func=parse_float_input,
        new_uid_func=new_uid,
        is_mobile_mode_func=is_mobile_mode,
        ecd_func=ecd,
        run_html_func=run_html,
        cache_enrichment_func=enrich_estimations_card_cache,
    )
elif st.session_state.current_page=="Annonces Vinted":
    render_with_perf(
        "page Annonces Vinted",
        render_vinted_listings_page,
        ld_func=ld,
        card_available_qty_func=card_available_qty,
        is_collection_system_lot_func=is_collection_system_lot,
        proxy_img_func=proxy_img,
        render_page_header_func=render_page_header,
        fp_func=fp,
        is_mobile_mode_func=is_mobile_mode,
        perf_count_func=perf_count,
        run_html_func=run_html,
    )
elif st.session_state.current_page=="Historique":
    render_with_perf(
        "page Historique",
        render_history_page,
        ld_func=ld,
        calc_cout_lot_func=calc_cout_lot,
        effective_purchase_price_func=effective_purchase_price,
        normalize_name_func=normalize_name,
        proxy_img_func=proxy_img,
        render_page_header_func=render_page_header,
        run_html_func=run_html,
        lots_archives_path="lots_archives.json",
    )


# ============================================================
# PAGE ARCHIVÉS
# ============================================================
elif st.session_state.current_page=="Archivés":
    render_with_perf(
        "page Archives",
        render_archives_page,
        ld_func=ld,
        sd_func=sd,
        safe_write_json_func=safe_write_json,
        render_page_header_func=render_page_header,
        cr_func=cr,
        cp_func=cp,
        crp_func=crp,
        fp_func=fp,
        archive_file_path="lots_archives.json",
    )


# ============================================================
# PAGE BROCANTE
# ============================================================
elif st.session_state.current_page=="Brocante":
    # Legacy route: Brocante lots are now handled inside the Lots page.
    st.session_state.current_page = "Lots"
    st.rerun()

# ============================================================
# PAGE STATISTIQUES
# ============================================================
elif st.session_state.current_page == "Statistiques":
    render_with_perf(
        "page Statistiques",
        render_statistics_page,
        ld_func=ld,
        safe_write_json_func=safe_write_json,
        calc_cout_lot_func=calc_cout_lot,
        effective_purchase_price_func=effective_purchase_price,
        proxy_img_func=proxy_img,
        lots_archives_path="lots_archives.json",
        monthly_goals_path="monthly_goals.json",
    )


# ============================================================
# PAGE WRAPPED
# ============================================================
elif st.session_state.current_page == "Wrapped":
    render_with_perf(
        "page Wrapped",
        render_wrapped_page,
        ld_func=ld,
        calc_cout_lot_func=calc_cout_lot,
        effective_purchase_price_func=effective_purchase_price,
        fp_func=fp,
        proxy_img_func=proxy_img,
        lots_archives_path="lots_archives.json",
        set_current_page_func=set_current_page,
    )


# ============================================================
# PAGE COMPTEURS
# ============================================================
elif st.session_state.current_page == "Compteurs":
    render_with_perf(
        "page Compteurs",
        render_counters_page,
        ld_func=ld,
        safe_write_json_func=safe_write_json,
        canal_key_func=canal_key,
    )

perf_summary()

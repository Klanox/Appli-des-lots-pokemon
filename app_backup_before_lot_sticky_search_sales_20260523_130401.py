# Pokemon Lot Manager - Version FINALE avec toutes les modifications
# Gestion de lots de cartes Pokemon

import streamlit as st
import streamlit.components.v1 as components
import json,os,requests,time,sys,glob,tempfile,uuid
from datetime import datetime,timezone
from PIL import Image,ImageDraw,ImageFont
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor,as_completed
import unicodedata

APP_BUILD = "Codex 2026-05-19 history incremental"

# ============================================================
# CACHE GLOBAL ULTRA-RAPIDE
# ============================================================

CARDS_CACHE_FILE = "cards_cache.json"
CARDS_CACHE_TTL_SECONDS = 14 * 24 * 60 * 60

def safe_write_json(path, data, indent=None):
    """Ecrit un JSON via un fichier temporaire, puis remplacement atomique."""
    folder = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(folder, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder, delete=False, suffix=".tmp") as tmp:
            tmp_path = tmp.name
            json.dump(data, tmp, ensure_ascii=False, indent=indent)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass

def load_cards_cache_from_disk(allow_stale=False):
    if not os.path.exists(CARDS_CACHE_FILE):
        return None
    try:
        with open(CARDS_CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("version") != 1:
            return None
        age = time.time() - float(cached.get("created_at", 0))
        if not allow_stale and age > CARDS_CACHE_TTL_SECONDS:
            return None
        cards_index = cached.get("cards_index", {})
        if isinstance(cards_index, dict) and cards_index:
            return cards_index
    except Exception as e:
        print(f"Cache disque cartes illisible: {e}")
    return None

def save_cards_cache_to_disk(cards_index):
    safe_write_json(CARDS_CACHE_FILE, {
        "version": 1,
        "created_at": time.time(),
        "cards_index": cards_index,
    })

def load_cards_cache():
    """Charger toutes les cartes en mémoire (1 fois au démarrage)"""
    if "cards_index" in st.session_state:
        return st.session_state["cards_index"]
    
    print("🚀 Chargement cache cartes...")
    start = time.time()
    cards_index = {}

    cached_cards = load_cards_cache_from_disk()
    if cached_cards:
        st.session_state["cards_index"] = cached_cards
        print(f"✅ Cache disque: {len(cached_cards)} noms, {time.time()-start:.1f}s")
        return cached_cards
    
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
            except:
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
        print(f"❌ Cache error: {e}")
        stale_cards = load_cards_cache_from_disk(allow_stale=True)
        if stale_cards:
            st.session_state["cards_index"] = stale_cards
            return stale_cards
    
    return cards_index

def normalize_name(n):
    cleaned = ''.join(c for c in unicodedata.normalize('NFD', str(n).lower()) if unicodedata.category(c) != 'Mn')
    for ch in ["-", "‐", "‑", "–", "—", "_", "'", "’", ".", ":", " "]:
        cleaned = cleaned.replace(ch, "")
    return cleaned

def search_in_cache(name, num=None):
    """Recherche INSTANTANÉE dans le cache"""
    if "cards_index" not in st.session_state:
        load_cards_cache()
    cards_index = st.session_state.get("cards_index", {})
    if not cards_index:
        return []
    
    name_norm = normalize_name(name)
    matches = []
    seen = set()
    
    def add_match(card, set_name):
        cid = card.get("id","") or card.get("name","")
        if cid not in seen:
            seen.add(cid)
            matches.append((card, set_name))
    
    def card_matches_num(card):
        card_num = str(card.get("localId","") or card.get("number",""))
        if not num:
            return True
        return (
            card_num == num
            or card_num.zfill(3) == num.zfill(3)
            or (num.isdigit() and card_num.endswith(num) and not card_num[:-len(num)].isdigit())
        )

    def iter_cache_items():
        for idx_name, cards in cards_index.items():
            yield idx_name, normalize_name(idx_name), cards

    # 1. Correspondance exacte
    if name_norm in cards_index:
        for card, set_name, set_id in cards_index[name_norm]:
            card_num = str(card.get("localId","") or card.get("number",""))
            if num:
                if (card_num == num or card_num.zfill(3) == num.zfill(3) or
                    (num.isdigit() and card_num.endswith(num) and not card_num[:-len(num)].isdigit())):
                    add_match(card, set_name)
            else:
                add_match(card, set_name)

    # 1b. Cache ancien : certaines clés gardent les tirets/espaces.
    if not matches:
        for idx_name, idx_norm, cards in iter_cache_items():
            if idx_norm == name_norm:
                for card, set_name, set_id in cards:
                    if card_matches_num(card):
                        add_match(card, set_name)
    
    # 2. Recherche partielle — cherche name_norm dans chaque nom indexé
    if not matches:
        for idx_name, idx_norm, cards in iter_cache_items():
            if name_norm in idx_norm:
                for card, set_name, set_id in cards:
                    if card_matches_num(card):
                        add_match(card, set_name)
    
    return matches

# ============================================================
# DONNÉES
# ============================================================
DATA = "data.json"
ACTIVITY_STATE_FILE = "activity_state.json"

def new_uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"

def is_storage_lot(lot):
    return lot.get("is_storage") or lot.get("nom") in ("Stockage", "📈 Stockage")

def card_available_qty(card):
    return max(
        int(card.get("quantity", 0))
        - int(card.get("sold_quantity", 0))
        - int(card.get("stored_quantity", 0)),
        0,
    )

def card_sold_cote(card):
    value = 0.
    qty = 0
    for se in card.get("sold_entries", []):
        se_qty = int(se.get("quantity", 1))
        cote_unit = float(se.get("suggested_price_at_sale", 0.) or card.get("suggested_price", 0.) or 0.)
        if cote_unit <= 0:
            cote_unit = float(se.get("price", 0.)) / max(se_qty, 1)
        value += cote_unit * se_qty
        qty += se_qty
    return value, qty

def lot_tracked_cote_value(lot):
    """Valeur cotee des cartes suivies dans le lot, sans double compter les vendues."""
    value = 0.
    for card in lot.get("cards", []):
        sold_value, sold_qty = card_sold_cote(card)
        unsold_qty = max(int(card.get("quantity", 0)) - sold_qty, 0)
        value += sold_value + unsold_qty * float(card.get("suggested_price", 0.))
    for v in lot.get("ventes", []):
        if not v.get("is_exchange_benefit"):
            value += float(v.get("price", 0.))
    return value

def effective_purchase_price(lot):
    """Prix d'achat utilise pour les cartes suivies, specialement fiable pour les lots mixtes."""
    if lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
        tracked_value = lot_tracked_cote_value(lot)
        real_price = float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
        return (tracked_value / float(lot.get("valeur_totale", 1.) or 1.)) * real_price
    return float(lot.get("prix_achat", 0.) or 0.)

def sync_mixte_purchase_prices(d):
    """Corrige les prix d'achat effectifs des lots mixtes sans double compter les cartes vendues."""
    changed = False
    for lot in d.get("lots", []):
        if lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
            tracked_value = lot_tracked_cote_value(lot)
            new_price = effective_purchase_price(lot)
            if abs(float(lot.get("prix_achat", 0.) or 0.) - new_price) > 0.01:
                lot["prix_achat"] = new_price
                changed = True
            if abs(float(lot.get("valeur_vente", 0.) or 0.) - tracked_value) > 0.01:
                lot["valeur_vente"] = tracked_value
                changed = True
    return changed

def consolidate_storage_cards(d):
    """Fusionne les doublons identiques du lot Stockage pour eviter les cartes affichees deux fois."""
    changed = False
    for lot in d.get("lots", []):
        if not is_storage_lot(lot):
            continue
        merged = []
        by_key = {}
        for card in lot.get("cards", []):
            key = (
                str(card.get("id", "")), normalize_name(card.get("name", "")),
                str(card.get("set", "")), str(card.get("number", "")),
                round(float(card.get("suggested_price", 0.) or 0.), 2),
                str(card.get("stored_from_lot_uid", "")),
            )
            if key in by_key and not card.get("sold_entries"):
                target = by_key[key]
                target["quantity"] = int(target.get("quantity", 0)) + int(card.get("quantity", 0))
                target["sold_quantity"] = int(target.get("sold_quantity", 0)) + int(card.get("sold_quantity", 0))
                target.setdefault("storage_entries", []).extend(card.get("storage_entries", []))
                changed = True
            else:
                by_key[key] = card
                merged.append(card)
        lot["cards"] = merged
    return changed

def storage_remaining_for_lot(lots, lot):
    lot_uid = lot.get("lot_uid")
    if not lot_uid:
        return 0
    remaining = 0
    for storage_lot in lots:
        if not is_storage_lot(storage_lot):
            continue
        for card in storage_lot.get("cards", []):
            if card.get("stored_from_lot_uid") == lot_uid:
                remaining += card_available_qty(card)
    return remaining

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

def ld():
    # Cache en session_state pour éviter les relectures inutiles
    if "data_cache" in st.session_state and not st.session_state.get("data_dirty", False):
        return st.session_state["data_cache"]
    if os.path.exists(DATA):
        with open(DATA,"r",encoding="utf-8") as f:
            d = json.load(f)
    else:
        d = {"lots":[]}
    data_changed = False
    if ensure_card_ids(d):
        data_changed = True
    if sync_mixte_purchase_prices(d):
        data_changed = True
    if consolidate_storage_cards(d):
        data_changed = True
    if data_changed:
        safe_write_json(DATA, d)
    st.session_state["data_cache"] = d
    st.session_state["data_dirty"] = False
    return d

def sd(d):
    # Écriture sans indentation = 3x plus rapide
    safe_write_json(DATA, d)
    # Mettre à jour le cache et marquer comme propre
    st.session_state["data_cache"] = d
    st.session_state["data_dirty"] = False

def gsh():
    d=ld()
    h=[]
    for l in d.get("lots",[]):
        for v in l.get("ventes",[]):
            h.append({**v,"lot_name":l["nom"]})
        for c in l.get("cards",[]):
            for s in c.get("sold_entries",[]):
                h.append({**s,"lot_name":l["nom"]})
    return sorted(h,key=lambda x:x.get("date",""),reverse=True)

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

def gst():
    d=ld()
    tc=sc=rc=0
    sv=tr=total_cost=0.
    
    for l in d.get("lots",[]):
        total_cost+=l.get("prix_achat",0.)
        for v in l.get("ventes",[]):
            if v.get("is_exchange_benefit"):
                continue
            tr+=v.get("price",0.)
        for c in l.get("cards",[]):
            cq=c.get("quantity",0)
            csq=c.get("sold_quantity",0)
            tc+=cq
            sc+=csq
            rc+=cq-csq
            sv+=(cq-csq)*c.get("suggested_price",0.)
            for s in c.get("sold_entries",[]):
                tr+=s.get("price",0.)
    
    archive_file="lots_archives.json"
    if os.path.exists(archive_file):
        try:
            with open(archive_file,"r",encoding="utf-8") as f:
                archives=json.load(f)
            for l in archives:
                total_cost+=l.get("prix_achat",0.)
                for v in l.get("ventes",[]):
                    if v.get("is_exchange_benefit"):
                        continue
                    tr+=v.get("price",0.)
                for c in l.get("cards",[]):
                    for s in c.get("sold_entries",[]):
                        tr+=s.get("price",0.)
        except:
            pass
    
    return {"total_cards":int(tc),"sold_cards":int(sc),"remaining_cards":int(rc),"stock_value":sv,"total_revenue":tr,"total_profit":tr-total_cost,"total_revenue_gross":tr}

@st.dialog("📡 Canal de vente")
def ask_canal(lot_idx, card_idx, qty, price):
    st.markdown(f"**Vente de {qty} carte(s) — {fp(price * qty)}**")
    CANAUX = ["Main propre", "Brocante", "Dexify_TCG", "Pokédeal"]
    canal = st.selectbox("Via quel canal ?", CANAUX)
    c1, c2 = st.columns(2)
    if c1.button("✅ Confirmer", type="primary", use_container_width=True):
        scu(lot_idx, card_idx, qty, price, canal)
        st.session_state["last_sale_ok"] = True
        st.rerun()
    if c2.button("❌ Annuler", use_container_width=True):
        st.rerun()


def fp(v):
    return f"{v:.2f}€"

def load_app_settings():
    path = "app_settings.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
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
                except:
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
    # Image locale uploadée
    if url.startswith("card_images/"):
        try:
            import base64
            with open(url, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            ext = url.split(".")[-1]
            mime = "image/jpeg" if ext in ["jpg","jpeg"] else f"image/{ext}"
            return f"data:{mime};base64,{data}"
        except:
            return ""
    if "tcgdex.net" in url:
        if "/ja/" in url:
            return url  # Images JA : URL directe
        return f"https://wsrv.nl/?url={url}&w=400&fit=inside"
    return url

def img_with_fallback(url, url_en="", width="100%", style="border-radius:12px;"):
    """Afficher une image avec fallback EN si FR échoue"""
    proxied_fr = proxy_img(url)
    if url_en:
        proxied_en = proxy_img(url_en)
        return f'<img src="{proxied_fr}" onerror="this.onerror=null;this.src=\'{proxied_en}\';" style="width:{width};{style}">'
    return f'<img src="{proxied_fr}" style="width:{width};{style}">'

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

def acm_japanese(li, n, sn, num, q, co, p, ir, ie, purchase_price=0., special_tag=""):
    """Ajouter une carte japonaise — cherche via API JA par nom EN + numéro"""
    if not num:
        return False, "Numéro requis pour les cartes japonaises"

    # Table de correspondance FR → EN (noms de base des Pokémon)
    FR_TO_EN = {
        "bulbizarre":"bulbasaur","herbizarre":"ivysaur","florizarre":"venusaur",
        "salameche":"charmander","reptincel":"charmeleon","dracaufeu":"charizard",
        "carapuce":"squirtle","carabaffe":"wartortle","tortank":"blastoise",
        "chenipan":"caterpie","chrysacier":"metapod","papilusion":"butterfree",
        "aspicot":"weedle","coconfort":"kakuna","dardargnan":"beedrill",
        "roucool":"pidgey","roucoups":"pidgeotto","roucarnage":"pidgeot",
        "rattata":"rattata","rattatac":"raticate","piafabec":"spearow","rapasdepic":"fearow",
        "abo":"ekans","arbok":"arbok","pikachu":"pikachu","raichu":"raichu",
        "sabelette":"sandshrew","sablaireau":"sandslash","nidoran":"nidoran",
        "nidorina":"nidorina","nidoqueen":"nidoqueen","nidorino":"nidorino",
        "nidoking":"nidoking","melofee":"clefairy","melodelfe":"clefable",
        "goupix":"vulpix","feunard":"ninetales","rondoudou":"jigglypuff",
        "grodoudou":"wigglytuff","nosferapti":"zubat","nosferalto":"golbat",
        "mystherbe":"oddish","ortide":"gloom","rafflesia":"vileplume",
        "paras":"paras","parasect":"parasect","mimitoss":"venonat","aeromite":"venomoth",
        "taupiqueur":"diglett","triopikeur":"dugtrio","miaouss":"meowth",
        "persian":"persian","psyduck":"psyduck","akwakwak":"golduck",
        "machoc":"machop","machopeur":"machoke","mackogneur":"machamp",
        "chetiflor":"bellsprout","boustiflor":"weepinbell","empiflor":"victreebel",
        "tentacool":"tentacool","tentacruel":"tentacruel","racaillou":"geodude",
        "gravalanch":"graveler","grolem":"golem","ponyta":"ponyta","galopa":"rapidash",
        "ramoloss":"slowpoke","flagadoss":"slowbro","magneti":"magnemite",
        "magneton":"magneton","canarticho":"farfetch'd","doduo":"doduo","dodrio":"dodrio",
        "otaria":"seel","lamantine":"dewgong","tadmorv":"grimer","grotadmorv":"muk",
        "kokiyas":"shellder","crustabri":"cloyster","fantominus":"gastly",
        "spectrum":"haunter","ectoplasma":"gengar","onix":"onix","soporifik":"drowzee",
        "hypnomade":"hypno","krabby":"krabby","krabboss":"kingler",
        "voltorbe":"voltorb","electrode":"electrode","noeunoeuf":"exeggcute",
        "noadkoko":"exeggutor","osselait":"cubone","ossatueur":"marowak",
        "kicklee":"hitmonlee","tygnon":"hitmonchan","excelangue":"lickitung",
        "smogo":"koffing","weezing":"weezing","rhinocorne":"rhyhorn",
        "rhinoferor":"rhydon","leveinard":"chansey","saquedeneu":"tangela",
        "kangourex":"kangaskhan","hypotrempe":"horsea","hypocean":"seadra",
        "poissirene":"goldeen","poissoroy":"seaking","stari":"staryu",
        "staross":"starmie","m. mime":"mr. mime","insecateur":"scyther",
        "lippoutou":"jynx","electabuzz":"electabuzz","magmar":"magmar",
        "scarabrute":"pinsir","tauros":"tauros","magicarpe":"magikarp",
        "leviator":"gyarados","lokhlass":"lapras","metamorph":"ditto",
        "evoli":"eevee","aquali":"vaporeon","voltali":"jolteon","pyroli":"flareon",
        "porygon":"porygon","amonita":"omanyte","amonistar":"omastar",
        "kabuto":"kabuto","kabutops":"kabutops","pterapic":"aerodactyl",
        "ronflex":"snorlax","artikodin":"articuno","electhor":"zapdos",
        "sulfura":"moltres","minidraco":"dratini","draco":"dragonair",
        "dracolosse":"dragonite","mewtwo":"mewtwo","mew":"mew",
        # Gen 2
        "germignon":"chikorita","macronium":"bayleef","meganium":"meganium",
        "hericendre":"cyndaquil","feurisson":"quilava","typhlosion":"typhlosion",
        "kaiminus":"totodile","crocrodil":"croconaw","aligatueur":"feraligatr",
        "fouinette":"sentret","fouinar":"furret","hoothoot":"hoothoot",
        "noctowl":"noctowl","ledbiba":"ledyba","ledian":"ledian",
        "arachnie":"spinarak","arigomite":"ariados","nostenfer":"crobat",
        "loupio":"chinchou","lanturn":"lanturn","pichu":"pichu","melopimpin":"cleffa",
        "toudoudou":"igglybuff","togepy":"togepi","togetic":"togetic",
        "natu":"natu","xatu":"xatu","faamelant":"mareep","lainergie":"flaaffy",
        "pharamp":"ampharos","floravol":"bellossom","marill":"marill",
        "azumarill":"azumarill","simularbre":"sudowoodo","ptitard":"politoed",
        "granivol":"hoppip","floravol":"skiploom","cotovol":"jumpluff",
        "granivol":"aipom","motigron":"sunkern","heligon":"sunflora",
        "yanma":"yanma","wattouat":"wooper","maraiste":"quagsire",
        "mentali":"espeon","noctali":"umbreon","laineux":"murkrow",
        "roigada":"slowking","zarbi":"unown","noctunoir":"wobbuffet",
        "girafarig":"girafarig","pomdepik":"pineco","foretress":"forretress",
        "dunsparce":"dunsparce","linoone":"gligar","steelix":"steelix",
        "granbull":"snubbull","hyporoi":"granbull","qwilfish":"qwilfish",
        "cizayox":"scizor","caratroc":"shuckle","heracross":"heracross",
        "snubbull":"snubbull","ursaring":"ursaring","teddiursa":"teddiursa",
        "magmar":"magmar","manta":"mantine","avaltout":"swinub",
        "piloswin":"piloswine","corayon":"corsola","remoraide":"remoraid",
        "octillery":"octillery","cadoizo":"delibird","mantine":"mantine",
        "magnezone":"skarmory","hyporoi":"houndour","demolosse":"houndoom",
        "ymphali":"kingdra","phanpy":"phanpy","donphan":"donphan",
        "porygon2":"porygon2","cerfrousse":"stantler","cadoizo":"smeargle",
        "tygnon":"tyrogue","kicklee":"hitmontop","lippoutou":"smoochum",
        "magby":"magby","minidraco":"miltank","levelard":"blissey",
        "raikou":"raikou","entei":"entei","suicune":"suicune",
        "embrylex":"larvitar","ymphali":"pupitar","tyranocif":"tyranitar",
        "lugia":"lugia","ho-oh":"ho-oh","celebi":"celebi",
        # Gen 3+
        "poussifeu":"torchic","galifeu":"combusken","brasegali":"blaziken",
        "gobou":"mudkip","flobio":"marshtomp","laggron":"swampert",
        "arcko":"treecko","massko":"grovyle","jungko":"sceptile",
        "zigzaton":"zigzagoon","linoone":"linoone","chenipotte":"wurmple",
        "blindalys":"silcoon","armulys":"beautifly","coocyte":"cascoon",
        "papinox":"dustox","lotad":"lotad","lombre":"lombre","ludicolo":"ludicolo",
        "grainipiot":"seedot","pifeuil":"nuzleaf","tengalice":"shiftry",
        "nirondelle":"taillow","hurricane":"swellow","wattouat":"wingull",
        "goelise":"pelipper","chuckfey":"ralts","kirlia":"kirlia",
        "gardevoir":"gardevoir","nincada":"nincada","ninjask":"ninjask",
        "munja":"shedinja","loudred":"loudred","exploud":"exploud","fouinette":"whismur",
        "nounourson":"makuhita","hariyama":"hariyama","azurill":"azurill",
        "tarinor":"nosepass","skitty":"skitty","delcatty":"delcatty",
        "atcham":"sableye","mysdibule":"mawile","aron":"aron","toran":"lairon",
        "galeking":"aggron","meditite":"meditite","medicham":"medicham",
        "dynavolt":"electrike","manectric":"manectric","plusle":"plusle",
        "minun":"minun","illumise":"illumise","volbeat":"volbeat",
        "rosélia":"roselia","boufffant":"gulpin","avaltout":"swalot",
        "carvanha":"carvanha","sharpedo":"sharpedo","wailmer":"wailmer",
        "wailord":"wailord","numel":"numel","chamallot":"camerupt",
        "chartor":"torkoal","spoink":"spoink","groret":"grumpig",
        "kecleon":"kecleon","shuppet":"shuppet","banette":"banette",
        "duskull":"duskull","dusclops":"dusclops","tropius":"tropius",
        "chuchmur":"chimecho","absol":"absol","wynaut":"wynaut",
        "snorunt":"snorunt","glalie":"glalie","spheal":"spheal",
        "phelin":"sealeo","rorqual":"walrein","coquiperl":"clamperl",
        "huntail":"huntail","gorebyss":"gorebyss","relicanth":"relicanth",
        "lovdisc":"luvdisc","draby":"bagon","shelgon":"shelgon",
        "drattak":"salamence","beldepth":"beldum","metang":"metang",
        "metagross":"metagross","regirock":"regirock","regice":"regice",
        "registeel":"registeel","latias":"latias","latios":"latios",
        "kyogre":"kyogre","groudon":"groudon","rayquaza":"rayquaza",
        "jirachi":"jirachi","deoxys":"deoxys",
        # Quelques Gen 4+
        "tortipouss":"turtwig","gauvar":"grotle","torterra":"torterra",
        "ouisticram":"chimchar","chimpenfeu":"monferno","infernape":"infernape",
        "tiplouf":"piplup","empoleon":"empoleon","starly":"starly",
        "étourmi":"staravia","étourvol":"staraptor","kricketot":"kricketot",
        "kricketune":"kricketune","shinx":"shinx","luxio":"luxio","luxray":"luxray",
        "rozbouton":"budew","roserade":"roserade","cranidos":"cranidos",
        "ramboum":"rampardos","dinoclier":"shieldon","bastiodon":"bastiodon",
        "cheniti":"burmy","papinox":"wormadam","papilord":"mothim",
        "apitrini":"combee","apireine":"vespiquen","pachirisu":"pachirisu",
        "phione":"phione","manaphy":"manaphy","darkrai":"darkrai",
        "shaymin":"shaymin","arceus":"arceus","victini":"victini",
        "rhinastoc":"rhyperior","tangrowth":"tangrowth","porygon-z":"porygon-z",
        "togekiss":"togekiss","yanmega":"yanmega","feuforeve":"leafeon",
        "givrali":"glaceon","nostenfer":"gliscor","mammochon":"mamoswine",
        "magnezone":"magnezone","lucario":"lucario","riolu":"riolu",
        "hippopotas":"hippopotas","hippodocus":"hippowdon","scorplane":"skorupi",
        "drascore":"drapion","skorupion":"croagunk","toxicroak":"toxicroak",
        "cradopaud":"carnivine","poissojade":"finneon","lumineon":"lumineon",
        "ninjask":"snover","blizzaroi":"abomasnow","greunoble":"weavile",
        "giratina":"giratina","cresselia":"cresselia","heatran":"heatran",
        "regigigas":"regigigas","dialga":"dialga","palkia":"palkia",
        "giratina":"giratina","uxie":"uxie","mesprit":"mesprit","azelf":"azelf",
        # cartes Trainers/objets courants dans TCG
        "nymphali":"sylveon","mentali":"espeon","noctali":"umbreon",
        "aquali":"vaporeon","pyroli":"flareon","voltali":"jolteon",
        "phyllali":"leafeon","givrali":"glaceon","mucuscule":"goomy",
        "muplodocus":"sliggoo","muplodocus":"goodra","spiritomb":"spiritomb",
        "nidoran♀":"nidoran-f","nidoran♂":"nidoran-m",
        "qulbutoke":"wobbuffet","qulbutoké":"wobbuffet",
    }

    # Trouver le nom EN depuis le nom FR
    # Table de correspondance noms de sets → set_id TCGDex JA
    SET_NAME_TO_ID = {
        "shining darkness": "DP3", "darkness": "DP3",
        "mysterious treasures": "DP2", "space-time creation": "DP1",
        "great encounters": "DP4", "majestic dawn": "DP5",
        "legends awakened": "DP6", "stormfront": "DP7",
        "platinum": "DPt1", "rising rivals": "DPt2",
        "supreme victors": "DPt3", "arceus": "DPt4",
        "heartgold soulsilver": "HGSS1", "unleashed": "HGSS2",
        "undaunted": "HGSS3", "triumphant": "HGSS4",
        "neo genesis": "neo1", "neo discovery": "neo2",
        "neo revelation": "neo3", "neo destiny": "neo4",
        "base set": "base1", "jungle": "base2", "fossil": "base3",
        "team rocket": "base4", "gym heroes": "PMCG1",
        "black white": "BW1", "emerging powers": "BW2",
        "noble victories": "BW3", "next destinies": "BW4",
        "dark explorers": "BW5", "dragons exalted": "BW6",
        "xy": "XY1", "flashfire": "XY2", "furious fists": "XY3",
        "phantom forces": "XY4", "primal clash": "XY5",
        "roaring skies": "XY6", "ancient origins": "XY7",
        "breakthrough": "XY8", "breakpoint": "XY9",
        "fates collide": "XY10", "steam siege": "XY11",
        "evolutions": "XY12", "sun moon": "SM1",
        "guardians rising": "SM2", "burning shadows": "SM3",
        "crimson invasion": "SM4", "ultra prism": "SM5",
        "forbidden light": "SM6", "celestial storm": "SM7",
        "lost thunder": "SM8", "team up": "SM9",
        "unbroken bonds": "SM10", "unified minds": "SM11",
        "cosmic eclipse": "SM12", "sword shield": "S1",
        "rebel clash": "S2", "darkness ablaze": "S3",
        "vivid voltage": "S4", "battle styles": "S5",
        "chilling reign": "S6", "evolving skies": "S7",
        "fusion strike": "S8", "brilliant stars": "S9",
        "astral radiance": "S10", "lost origin": "S11",
        "silver tempest": "S12", "scarlet violet": "SV1",
        "paldea evolved": "SV2", "obsidian flames": "SV3",
        "paradox rift": "SV4", "temporal forces": "SV5",
        "twilight masquerade": "SV6", "stellar crown": "SV7",
        "surging sparks": "SV8", "prismatic evolutions": "SV8a",
        "shiny treasure": "SV4a", "151": "SV2a",
    }
    
    # Convertir sn en set_id si possible
    sn_norm = normalize_name(sn.lower()) if sn else ""
    set_id_filter = None
    if sn_norm:
        for set_name_key, sid in SET_NAME_TO_ID.items():
            if sn_norm in normalize_name(set_name_key) or normalize_name(set_name_key) in sn_norm:
                set_id_filter = sid
                break
        if not set_id_filter:
            set_id_filter = sn  # Utiliser directement si ressemble à un ID

    name_norm = normalize_name(n.lower())
    # Chercher correspondance exacte puis partielle
    name_en = None
    for fr_key, en_val in FR_TO_EN.items():
        if normalize_name(fr_key) == name_norm:
            name_en = en_val
            break
    if not name_en:
        # Recherche partielle
        for fr_key, en_val in FR_TO_EN.items():
            if normalize_name(fr_key) in name_norm or name_norm in normalize_name(fr_key):
                name_en = en_val
                break
    if not name_en:
        name_en = n  # Fallback: utiliser le nom FR tel quel

    try:
        # Chercher par numéro, filtrer par set si fourni
        api_url = f"https://api.tcgdex.net/v2/ja/cards?localId={num}"
        if set_id_filter:
            api_url = f"https://api.tcgdex.net/v2/ja/sets/{set_id_filter}/cards"
        r = requests.get(api_url, timeout=5)
        candidates = []
        if r.status_code == 200:
            for card in r.json():
                card_num = str(card.get("localId","") or card.get("number",""))
                if card_num != num and card_num.lstrip("0") != num.lstrip("0"):
                    continue
                # Filtrer par nom JA si on a une correspondance FR→JA
                # On compare le nom JA de la carte avec le nom anglais trouvé
                card_name_ja = card.get("name","").lower()
                if name_en and name_en != n:
                    # Vérifier si le nom anglais apparaît dans le nom JA (translittération) ou skip si trop différent
                    # Pour l'instant on garde toutes les cartes avec ce numéro
                    pass
                set_info = card.get("set", {})
                set_id = set_info.get("id","") if isinstance(set_info, dict) else ""
                set_name = set_info.get("name","") if isinstance(set_info, dict) else ""
                if sn and sn.lower() not in set_name.lower() and sn.lower() not in set_id.lower():
                    continue
                img = card.get("image","")
                if not img and set_id and card_num:
                    img = f"https://assets.tcgdex.net/ja/{set_id}/{card_num}/high.webp"
                card["image"] = img
                label = f"🇯🇵 {set_id}" + (f" — {set_name}" if set_name else "")
                candidates.append((card, label))

        if not candidates:
            return False, f"Carte JA '{name_en}' #{num} introuvable"

        if len(candidates) == 1:
            ci, si = candidates[0]
            cd = ld()
            nc = ecd(ci, si, lang="ja")
            nc["card_uid"] = new_uid("card")
            nc["quantity"] = q if q else 1
            nc["condition"] = co
            nc["suggested_price"] = p if p else 0.
            nc["is_reverse"] = ir
            nc["is_ed1"] = ie
            nc["name"] = n
            if purchase_price > 0:
                nc["purchase_price"] = purchase_price
            if special_tag:
                nc["special_tag"] = special_tag
            cd["lots"][li]["cards"].append(nc)
            if cd["lots"][li].get("is_divers"):
                cd["lots"][li]["prix_achat"] = sum(c.get("purchase_price",0.) for c in cd["lots"][li]["cards"])
            sd(cd)
            return True, "Carte japonaise ajoutée !"

        existing = glob.glob(f"popup_{li}_*.json")
        if existing:
            return True, f"{len(candidates)} résultats JA"
        pd = {
            "matches": [[c, s] for c,s in candidates],
            "pending": [n, sn, num, q, co, p, ir, ie, special_tag],
            "search_id": f"{li}_{int(time.time()*1000)}",
            "lang": "ja",
            "name_override": n,
            "pa_carte": purchase_price,
        }
        pf = f"popup_{li}_{int(time.time()*1000)}.json"
        with open(pf, "w") as f:
            json.dump(pd, f)
        return True, f"{len(candidates)} résultats — choisissez le bon set"

    except Exception as e:
        return False, f"Erreur JA: {e}"
        
        if not candidates:
            return False, f"Aucune carte JA avec le numéro {num}"
        
        if len(candidates) == 1:
            ci, si = candidates[0]
            cd = ld()
            nc = ecd(ci, si, lang="ja")
            nc["quantity"] = q if q else 1
            nc["condition"] = co
            nc["suggested_price"] = p if p else 0.
            nc["is_reverse"] = ir
            nc["is_ed1"] = ie
            nc["name"] = n
            if special_tag:
                nc["special_tag"] = special_tag
            cd["lots"][li]["cards"].append(nc)
            sd(cd)
            return True, "Carte japonaise ajoutée !"
        
        existing = glob.glob(f"popup_{li}_*.json")
        if existing:
            return True, f"{len(candidates)} résultats JA"
        pd = {
            "matches": [[c, s] for c,s in candidates],
            "pending": [n, sn, num, q, co, p, ir, ie, special_tag],
            "search_id": f"{li}_{int(time.time()*1000)}",
            "lang": "ja",
            "name_override": n
        }
        pf = f"popup_{li}_{int(time.time()*1000)}.json"
        with open(pf, "w") as f:
            json.dump(pd, f)
        return True, f"{len(candidates)} sets trouvés — choisissez le bon"
    
    except Exception as e:
        return False, f"Erreur JA: {e}"

def acm(li,n,sn,num,q,co,p,ir,ie,lang="fr",purchase_price=0., special_tag=""):
    """Ajouter carte au lot"""
    n=n.strip().title()
    sn=sn.strip()
    num=num.strip()
    
    if not n:
        return False,"Nom requis"

    # Mode japonais — chercher via API JA avec le set et numéro
    if lang == "ja":
        return acm_japanese(li, n, sn, num, q, co, p, ir, ie, purchase_price=purchase_price, special_tag=special_tag)

    multi=[x.strip().title() for x in n.split(",")]
    
    if len(multi)>1:
        ok_count=0
        for nm in multi:
            if nm:
                lok,lmg=acm(li,nm,sn,num,q,co,p,ir,ie,lang=lang,purchase_price=purchase_price,special_tag=special_tag)
                if lok:
                    ok_count+=1
        return ok_count>0,f"{ok_count} carte(s) ajoutée(s)"
    
    ci,si=afi(n,sn,num)
    
    if not ci:
        ai=sgt(n,num)
        if not ai:
            return False,f"'{n}' introuvable"
        
        
        if len(ai)==1:
            # Chercher les variantes directement dans le cache — sans appeler sgt()
            # pour éviter les appels réseau inutiles
            cards_index = st.session_state.get("cards_index", {})
            suffixes = ["vmax", "v", "ex", "gx", "mega", "tag team", "prime", "lv.x", "break", "legendaire", "légendaire"]
            base_name = normalize_name(n)
            
            seen_ids = set()
            for c,s in ai:
                seen_ids.add(c.get("id",""))
            variantes_uniq = []

            for suffix in suffixes:
                if base_name.endswith(normalize_name(suffix)):
                    continue
                for sep in [" ", "-"]:
                    key = normalize_name(f"{n}{sep}{suffix}".strip())
                    if key in cards_index:
                        for card, set_name, set_id in cards_index[key]:
                            card_num = str(card.get("localId","") or card.get("number",""))
                            matches_num = not num or card_num == num or card_num.zfill(3) == num.zfill(3)
                            if matches_num and card.get("id","") not in seen_ids:
                                seen_ids.add(card.get("id",""))
                                variantes_uniq.append((card, set_name))

            if variantes_uniq:
                # Il y a de vraies variantes différentes — afficher le popup
                all_results = ai + variantes_uniq
                existing_popups = glob.glob(f"popup_{li}_*.json")
                if existing_popups:
                    return True, f"{len(all_results)} résultats"
                sid = f"{li}_{int(time.time()*1000)}"
                pd = {"matches": [[c,s] for c,s in all_results], "pending": [n,sn,num,q,co,p,ir,ie], "search_id": sid, "pa_carte": purchase_price}
                pf = f"popup_{li}_{int(time.time()*1000)}.json"
                with open(pf, "w") as f:
                    json.dump(pd, f)
                return True, f"{len(all_results)} résultats"

            # Aucune variante — ajout direct sans popup
            ci,si=ai[0]
        else:
            existing_popups = glob.glob(f"popup_{li}_*.json")
            if existing_popups:
                return True,f"{len(ai)} résultats"
            
            sid=f"{li}_{int(time.time()*1000)}"
            pd={"matches":[[c,s]for c,s in ai],"pending":[n,sn,num,q,co,p,ir,ie],"search_id":sid,"pa_carte":purchase_price}
            pf=f"popup_{li}_{int(time.time()*1000)}.json"
            with open(pf,"w")as f:
                json.dump(pd,f)
            return True,f"{len(ai)} résultats"
    
    cd=ld()
    nc=ecd(ci,si,lang=lang)
    nc["card_uid"] = new_uid("card")
    nc["quantity"]=q if q else 1
    nc["condition"]=co
    nc["suggested_price"]=p if p else 0.
    nc["is_reverse"]=ir
    nc["is_ed1"]=ie
    if purchase_price > 0:
        nc["purchase_price"] = purchase_price
    if special_tag:
        nc["special_tag"] = special_tag
    cd["lots"][li]["cards"].append(nc)
    if cd["lots"][li].get("is_divers"):
        cd["lots"][li]["prix_achat"] = sum(c.get("purchase_price",0.) for c in cd["lots"][li]["cards"])
    sd(cd)
    
    return True,"Ajoutée!"

def _scu_in_data(cd, li, ci, q, p, canal="Main propre"):
    """Vend une carte dans un data.json deja charge, sans sauvegarder tout de suite."""
    crd=cd["lots"][li]["cards"][ci]
    if card_available_qty(crd) < q:
        return False,"Stock insuffisant"
    crd.setdefault("card_uid", new_uid("card"))
    crd["sold_quantity"]=crd.get("sold_quantity",0)+q
    prix_total = p*q
    sale_id = f"{crd.get('card_uid')}_{int(time.time()*1000)}"
    crd.setdefault("sold_entries",[]).append({
        "sale_id": sale_id,
        "date":datetime.now().isoformat(),
        "quantity":q,
        "price":prix_total,
        "card_name":crd["name"],
        "card_set":crd["set"],
        "card_number":crd["number"],
        "card_uid": crd.get("card_uid"),
        "lot_uid": cd["lots"][li].get("lot_uid"),
        "suggested_price_at_sale": float(crd.get("suggested_price", p)),
        "canal": canal,
    })

    # ── Redistribution du bénéfice aux lots contributeurs ──
    # Si cette carte a été reçue par échange avec contribution de plusieurs lots,
    # on ajoute une vente virtuelle dans chaque lot contributeur proportionnelle à leur part
    repartition = crd.get("exchange_repartition", {})
    if repartition:
        # valeur totale des contributions
        total_contrib = sum(float(v) for v in repartition.values()) or 1.
        for lot_idx_str, valeur_contrib in repartition.items():
            lot_idx_contrib = int(lot_idx_str)
            if lot_idx_contrib == li:
                continue  # le lot hôte garde son bénéfice normalement
            if lot_idx_contrib >= len(cd.get("lots", [])):
                continue
            # Part de bénéfice pour ce lot = (sa contribution / total) × prix de vente
            part = float(valeur_contrib) / total_contrib
            benefice_part = prix_total * part
            # Vente virtuelle dans ce lot pour matérialiser sa part du bénéfice
            cd["lots"][lot_idx_contrib].setdefault("ventes", []).append({
                "date": datetime.now().isoformat(),
                "price": benefice_part,
                "card_name": f"[Échange] Part bénéf. {crd['name']}",
                "is_exchange_benefit": True,
                "from_lot": cd["lots"][li]["nom"],
                "from_card": crd["name"],
                "source_sale_id": sale_id,
                "part_pct": round(part * 100, 1),
            })

    return True,"Vendu!"

def scu(li,ci,q,p,canal="Main propre"):
    """Sell card units. Si la carte vient d'un échange, redistribue le bénéfice
    proportionnellement aux lots contributeurs via des ventes virtuelles."""
    cd=ld()
    ok, msg = _scu_in_data(cd, li, ci, q, p, canal)
    if not ok:
        return ok, msg
    sd(cd)
    return True,"Vendu!"

def scu_many(items, canal="Main propre"):
    """Vend plusieurs cartes avec une seule lecture et une seule sauvegarde."""
    cd = ld()
    requested = {}
    for item in items:
        lot_idx, card_idx, lot, crd = resolve_card_ref(cd, item)
        if crd is None:
            return False, f"Carte introuvable dans le panier: {item.get('card_name', 'carte inconnue')}"
        item["lot_idx"] = lot_idx
        item["card_idx"] = card_idx
        item["lot_uid"] = lot.get("lot_uid")
        item["card_uid"] = crd.get("card_uid")
        key = (lot_idx, card_idx)
        requested[key] = requested.get(key, 0) + item["quantity"]
    for (lot_idx, card_idx), qty in requested.items():
        crd = cd["lots"][lot_idx]["cards"][card_idx]
        if card_available_qty(crd) < qty:
            return False, f"Stock insuffisant pour {crd.get('name', 'cette carte')}"
    for item in items:
        ok, msg = _scu_in_data(
            cd,
            item["lot_idx"],
            item["card_idx"],
            item["quantity"],
            item["unit_price"],
            canal,
        )
        if not ok:
            return False, msg
    sd(cd)
    return True, "Vendu!"

def bulk_cart_add(item):
    st.session_state.setdefault("bulk_cart", [])
    cd = ld()
    lot_idx, card_idx, lot, card = resolve_card_ref(cd, item)
    if card is None:
        return
    item.update({
        "lot_idx": lot_idx,
        "card_idx": card_idx,
        "lot_uid": lot.get("lot_uid"),
        "card_uid": card.get("card_uid"),
        "lot_name": lot.get("nom", item.get("lot_name", "")),
        "card_name": card.get("name", item.get("card_name", "")),
        "card_set": card.get("set", item.get("card_set", "")),
        "price_base": float(card.get("suggested_price", item.get("price_base", 0))),
    })
    stock = card_available_qty(card)
    item["quantity"] = min(max(int(item.get("quantity", 1)), 1), max(stock, 1))
    exists = any(
        it.get("card_uid") == item.get("card_uid")
        for it in st.session_state.bulk_cart
    )
    if not exists:
        st.session_state.bulk_cart.append(item)
        save_activity_state()

def bulk_cart_remove(lot_idx=None, card_idx=None, card_uid=None):
    st.session_state.bulk_cart = [
        it for it in st.session_state.get("bulk_cart", [])
        if not ((card_uid and it.get("card_uid") == card_uid) or (it.get("lot_idx") == lot_idx and it.get("card_idx") == card_idx))
    ]
    save_activity_state()

def bulk_cart_set_quantity(index):
    cd = ld()
    cart = st.session_state.get("bulk_cart", [])
    if 0 <= index < len(cart):
        lot_idx, card_idx, lot, card = resolve_card_ref(cd, cart[index])
        if card is None:
            cart.pop(index)
        else:
            stock = card_available_qty(card)
            key = f"cart_qty_{index}"
            cart[index]["quantity"] = min(max(int(st.session_state.get(key, 1)), 1), max(stock, 1))
    save_activity_state()

def bulk_cart_increment(index):
    cd = ld()
    cart = st.session_state.get("bulk_cart", [])
    if 0 <= index < len(cart):
        lot_idx, card_idx, lot, card = resolve_card_ref(cd, cart[index])
        if card is None:
            cart.pop(index)
        else:
            stock = card_available_qty(card)
            cart[index]["quantity"] = min(cart[index]["quantity"] + 1, stock)
    save_activity_state()

def bulk_cart_pop(index):
    cart = st.session_state.get("bulk_cart", [])
    if 0 <= index < len(cart):
        cart.pop(index)
    save_activity_state()

def bulk_cart_clear():
    st.session_state.bulk_cart = []
    save_activity_state()

def bulk_sale_prepare(sale_type, price):
    st.session_state["pending_bulk_sale"] = {"type": sale_type, "price": price}
    st.session_state["show_canal_dialog_bulk"] = True

def scroll_to_cart_prepare():
    st.session_state["scroll_to_cart"] = True

def set_current_page(page):
    st.session_state.current_page = page
    st.session_state["scroll_top_once"] = True
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


# ============================================================
# UI
# ============================================================

st.set_page_config(layout="wide",page_title="Pokemon Lot Manager",page_icon="🎴")

if "cards_index" not in st.session_state:
    with st.spinner("Chargement des données..."):
        load_cards_cache()

load_activity_state()

if st.session_state.get("current_page") != "Lots":
    components.html("""
    <script>
    (function() {
        const doc = parent.document;
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
        sd(cd_boot)
    st.session_state["system_lots_ready"] = True

if st.session_state.pop("scroll_top_once", False):
    components.html("<script>requestAnimationFrame(()=>parent.window.scrollTo({top:0,left:0,behavior:'instant'}));</script>", height=0)

# Réparer les images manquantes une seule fois (pas à chaque démarrage)
if "images_fixed" not in st.session_state:
    st.session_state["images_fixed"] = True
    fix_missing_images()
    st.rerun()

# JS : soumettre les champs de recherche à chaque frappe
components.html("""
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

st.markdown("""
<style>
.logo-header {
    background: white;
    border-radius: 20px;
    padding: 2rem;
    margin-bottom: 2rem;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    text-align: center;
}
.logo-header img {
    display: block;
    margin: 0 auto 1rem auto;
    width: 200px;
    height: auto;
}
.logo-header h1 {
    display: block !important;
    color: #ee1515;
    font-size: 2.5rem;
    font-weight: 900;
    margin: 0 0 0.5rem 0;
}
.logo-header p {
    color: #64748b;
    margin: 0;
    font-weight: 600;
}
</style>

<script>
console.log('[SCRIPT] JavaScript chargé !');

function styleDeltas() {
    document.querySelectorAll('[data-testid="stMetricDelta"]').forEach(delta => {
        delta.style.setProperty('background-color', '#22c55e', 'important');
        delta.style.setProperty('color', 'white', 'important');
        delta.style.setProperty('border-radius', '12px', 'important');
        delta.style.setProperty('padding', '0.5rem 1rem', 'important');
        delta.querySelectorAll('svg, path').forEach(svg => {
            svg.style.setProperty('fill', 'white', 'important');
        });
        delta.querySelectorAll('*').forEach(el => {
            if (el.tagName !== 'svg' && el.tagName !== 'SVG' && el.tagName !== 'path' && el.tagName !== 'PATH') {
                el.style.setProperty('color', 'white', 'important');
            }
        });
    });
}
styleDeltas();

styleDeltas();

const _obs = new MutationObserver(function(muts) { 
    styleDeltas();
});
_obs.observe(document.body, { childList: true, subtree: false });
</script>

""", unsafe_allow_html=True)

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

st.markdown(f"""
<div class="logo-header">
    <img src="{logo_src}" alt="Pokemon Lot Manager">
    <h1>POKEMON LOT MANAGER</h1>
    <p>Gérez vos collections comme un Dresseur Pro</p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
    h1 {display: none;}
    :root {
        --pokemon-red: #ee1515;
        --pokemon-blue: #3b4cca;
        --pokemon-yellow: #ffde00;
        --pokemon-green: #22c55e;
        --text-primary: #1e293b;
        --text-secondary: #64748b;
        --border: #e2e8f0;
    }
    .stApp {
        background: #f0f4f8;
        font-family: 'Inter', sans-serif;
    }
    div[style*="display: flex"][style*="justify-content: center"] img {
        margin: 0 auto !important;
        display: block !important;
    }
    .stApp::before {
        content: '';
        position: fixed;
        bottom: 20px;
        right: 20px;
        width: 120px;
        height: 120px;
        background-image: url('https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/25.png');
        background-size: contain;
        background-repeat: no-repeat;
        animation: bounce 2s infinite;
        pointer-events: none;
        z-index: 1000;
        opacity: 0.8;
    }
    .stApp::after {
        content: '';
        position: fixed;
        top: 100px;
        right: 120px;
        width: 100px;
        height: 100px;
        background-image: url('https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/133.png');
        background-size: contain;
        background-repeat: no-repeat;
        animation: float 3s ease-in-out infinite;
        pointer-events: none;
        z-index: 1000;
        opacity: 0.7;
    }
    @keyframes bounce {
        0%, 100% { transform: translateY(0px); }
        50% { transform: translateY(-20px); }
    }
    @keyframes float {
        0%, 100% { transform: translate(0, 0) rotate(0deg); }
        33% { transform: translate(10px, -10px) rotate(5deg); }
        66% { transform: translate(-10px, 10px) rotate(-5deg); }
    }
    [data-testid="stSidebar"] {
        background: white;
        border-right: 4px solid var(--pokemon-red);
        overflow-y: auto !important;
        max-height: 100vh !important;
    }
    [data-testid="stSidebar"] > div {
        overflow-y: auto !important;
        max-height: calc(100vh - 2rem) !important;
    }
    [data-testid="stSidebar"]::before {
        content: '';
        display: block;
        width: 100%;
        height: 180px;
        background-image: url('https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/6.png');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        margin-bottom: 1rem;
        opacity: 0.12;
    }
    [data-testid="stSidebar"] h2 {
        font-size: 0.75rem;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--pokemon-red);
        margin-bottom: 1.5rem;
        padding: 0.75rem;
        background: #fee2e2;
        border-radius: 8px;
        text-align: center;
    }
    [data-testid="stMetric"] {
        background: white;
        border: 3px solid var(--border);
        border-radius: 16px;
        padding: 1.5rem;
        padding-top: 2rem;
        transition: all 0.2s ease;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        position: relative;
        overflow: visible;
    }
    [data-testid="column"]:has([data-testid="stMetric"]) img {
        position: absolute !important;
        top: -15px !important;
        right: 15px !important;
        width: 50px !important;
        height: 50px !important;
        background: white !important;
        border: 3px solid #e2e8f0 !important;
        border-radius: 50% !important;
        padding: 5px !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
        z-index: 10 !important;
        margin: 0 !important;
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.12);
        border-color: var(--pokemon-yellow);
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.875rem;
        font-weight: 700;
        color: var(--text-primary) !important;
        text-transform: uppercase;
    }
    [data-testid="stMetricValue"] {
        font-size: 2.25rem;
        font-weight: 900;
        color: var(--text-primary) !important;
    }
    [data-testid="stMetricDelta"] {
        border-radius: 12px !important;
        padding: 0.4rem 0.8rem !important;
        margin-top: 0.5rem !important;
        display: inline-block !important;
    }
    [data-testid="stMetricDelta"] > div,
    [data-testid="stMetricDelta"] > div > div {
        background: transparent !important;
        background-color: transparent !important;
    }
    [data-testid="stMetricDelta"],
    [data-testid="stMetricDelta"] *:not(svg):not(path) {
        color: #000000 !important;
        font-weight: 700 !important;
    }
    /* Cacher l'icône SVG (flèche/carré) */
    [data-testid="stMetricDelta"] svg {
        display: none !important;
    }
    .stMarkdown, .stMarkdown p, .stMarkdown span,
    [data-testid="stCaptionContainer"],
    [data-testid="stText"],
    .element-container,
    div[data-testid="column"] > div,
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4,
    label, .stSelectbox label, .stTextInput label, .stNumberInput label {
        color: var(--text-primary) !important;
    }
    .stButton > button {
        background: white;
        color: var(--text-primary);
        border: 3px solid var(--border);
        border-radius: 12px;
        padding: 0.875rem 1.5rem;
        font-weight: 700;
        font-size: 0.875rem;
        transition: all 0.2s ease;
        text-transform: uppercase;
    }
    .stButton > button:hover {
        background: #fef3c7;
        border-color: var(--pokemon-yellow);
        transform: translateY(-2px);
    }
    .stButton > button[kind="primary"] {
        background: #22c55e !important;
        color: white !important;
        border-color: #16a34a !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: #16a34a !important;
    }
    .stForm button,
    .stForm button *,
    .stForm button[kind="primary"],
    .stForm button[type="submit"],
    button[kind="primary"],
    button[type="submit"] {
        background: #1e293b !important;
        background-color: #1e293b !important;
        color: #ffffff !important;
        border: 3px solid #475569 !important;
        border-radius: 12px !important;
        padding: 0.75rem 1.5rem !important;
        font-weight: 700 !important;
        transition: background 0.2s ease !important;
    }
    .stForm button:hover,
    .stForm button:hover *,
    .stForm button:focus,
    .stForm button:focus *,
    .stForm button:active,
    .stForm button:active *,
    .stForm button[kind="primary"]:hover,
    .stForm button[kind="primary"]:hover *,
    .stForm button[type="submit"]:hover,
    .stForm button[type="submit"]:hover *,
    button[kind="primary"]:hover,
    button[kind="primary"]:hover *,
    button[type="submit"]:hover,
    button[type="submit"]:hover * {
        background: #334155 !important;
        background-color: #334155 !important;
        color: #ffffff !important;
        border-color: #64748b !important;
    }
    .stForm button span,
    .stForm button div,
    .stForm button p,
    .stForm button:hover span,
    .stForm button:hover div,
    .stForm button:hover p,
    .stForm button:focus span,
    .stForm button:active span {
        color: #ffffff !important;
    }
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input,
    .stSelectbox > div > div > select {
        background: #1e293b !important;
        background-color: #1e293b !important;
        border: 3px solid var(--border);
        border-radius: 12px;
        padding: 0.75rem 1rem;
        font-weight: 600;
        transition: all 0.2s ease;
        color: white !important;
    }
    .stSelectbox > div > div > div {
        background: #1e293b !important;
        color: #ffffff !important;
    }
    /* Texte sélectionné visible dans le selectbox */
    .stSelectbox [data-baseweb="select"] span,
    .stSelectbox [data-baseweb="select"] div,
    .stSelectbox [data-baseweb="select"] p,
    .stSelectbox [data-baseweb="select"] [data-testid="stMarkdownContainer"],
    .stSelectbox svg {
        color: #ffffff !important;
        fill: #ffffff !important;
    }
    /* Dropdown ouvert - options lisibles */
    [data-baseweb="menu"],
    [data-baseweb="menu"] *,
    [data-baseweb="menu"] li,
    [data-baseweb="menu"] ul,
    [role="listbox"],
    [role="listbox"] *,
    [role="option"],
    [role="option"] * {
        background-color: #334155 !important;
        color: #ffffff !important;
    }
    [role="option"]:hover,
    [role="option"]:hover * {
        background-color: #475569 !important;
        color: #ffffff !important;
    }
    .stTextInput > div > div > input::placeholder,
    .stNumberInput > div > div > input::placeholder {
        color: #94a3b8 !important;
    }
    .stSelectbox option,
    .stSelectbox option * {
        background: #64748b !important;
        background-color: #64748b !important;
        color: #ffffff !important;
        padding: 0.5rem !important;
        font-weight: 600 !important;
    }
    .stSelectbox [data-baseweb="popover"],
    .stSelectbox [data-baseweb="popover"] * {
        background: #64748b !important;
        background-color: #64748b !important;
        color: #ffffff !important;
    }
    .stSelectbox [role="option"],
    .stSelectbox [role="option"] * {
        background: #64748b !important;
        background-color: #64748b !important;
        color: #ffffff !important;
        padding: 0.75rem !important;
        font-weight: 600 !important;
    }
    .stSelectbox [role="option"]:hover {
        background: #94a3b8 !important;
        background-color: #94a3b8 !important;
        color: #ffffff !important;
    }
    .stSelectbox div[data-baseweb="select"] > div {
        background: #1e293b !important;
        color: #ffffff !important;
    }
    .stSelectbox ul,
    .stSelectbox ul li {
        background: #64748b !important;
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    .stSelectbox [role="listbox"] * {
        color: #ffffff !important;
    }
    .stRadio > div {
        display: flex;
        gap: 0.5rem;
        flex-wrap: wrap;
    }
    .stRadio label {
        background: #1e293b !important;
        color: white !important;
        padding: 0.5rem 1rem !important;
        border-radius: 8px !important;
        border: 2px solid #475569 !important;
        cursor: pointer !important;
        font-weight: 600 !important;
        transition: all 0.2s ease !important;
    }
    .stRadio label:hover {
        background: #334155 !important;
        border-color: #64748b !important;
    }
    .stRadio input:checked + div,
    .stRadio label:has(input:checked),
    div[data-testid="stRadio"] [aria-checked="true"],
    div[data-testid="stRadio"] label:focus,
    div[data-testid="stRadio"] label:focus-within {
        background: #1e293b !important;
        border-color: #ffffff !important;
        color: white !important;
        box-shadow: none !important;
        outline: none !important;
    }
    input:-webkit-autofill,
    input:-webkit-autofill:hover,
    input:-webkit-autofill:focus,
    input:-webkit-autofill:active {
        -webkit-box-shadow: 0 0 0 30px #1e293b inset !important;
        -webkit-text-fill-color: white !important;
        box-shadow: 0 0 0 30px #1e293b inset !important;
    }
    .stTextInput > div > div > input:focus,
    .stNumberInput > div > div > input:focus {
        border-color: var(--pokemon-blue);
        box-shadow: 0 0 0 4px rgba(59, 76, 202, 0.1);
    }
    [data-testid="stExpander"] {
        background: white;
        border: 3px solid var(--border);
        border-left: 8px solid;
        border-radius: 12px;
        margin: 1rem 0;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        position: relative;
    }
    [data-testid="stExpander"].lot-profitable {
        border-left-color: #22c55e !important;
    }
    [data-testid="stExpander"].lot-not-profitable {
        border-left-color: #ee1515 !important;
    }
    [data-testid="stExpander"]::before {
        content: '';
        position: absolute;
        top: 12px;
        right: 50px;
        width: 35px;
        height: 35px;
        background-image: url('https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/poke-ball.png');
        background-size: contain;
        opacity: 0.2;
    }
    [data-testid="stExpander"]:hover {
        transform: translateX(4px);
    }
    [data-testid="stExpander"] summary {
        font-weight: 800;
        padding: 1.25rem 1.5rem;
        background: #fafafa;
        color: var(--text-primary);
    }
    .badge {
        display: inline-block;
        padding: 0.5rem 1rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 800;
        margin: 0.25rem;
        text-transform: uppercase;
        border: 2px solid;
    }
    .badge-reverse {
        background: #f3e8ff;
        color: #7c3aed;
        border-color: #7c3aed;
    }
    .badge-ed1 {
        background: #fee2e2;
        color: var(--pokemon-red);
        border-color: var(--pokemon-red);
    }
    .badge-profitable {
        background: #dcfce7;
        color: var(--pokemon-green);
        border-color: var(--pokemon-green);
    }

    /* ── Alignement grille cartes ── */
    [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"] {
        height: 100%;
    }
    /* Forcer même hauteur sur toutes les colonnes de la grille */
    [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] {
        display: flex !important;
        flex-direction: column !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] > div {
        flex: 1 !important;
        display: flex !important;
        flex-direction: column !important;
    }
    /* Images dans la grille cartes - taille uniforme sans rogner */
    [data-testid="stExpander"] [data-testid="stImage"] img,
    .card-grid-col [data-testid="stImage"] img,
    [data-testid="stHorizontalBlock"] [data-testid="stImage"] img {
        border-radius: 12px;
        border: 3px solid var(--border);
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
        transition: all 0.3s ease;
        width: 100% !important;
        max-height: 340px !important;
        height: auto !important;
        object-fit: contain !important;
        display: block !important;
        background: transparent;
    }
    /* Supprimer le fond blanc du conteneur stImage */
    [data-testid="stExpander"] [data-testid="stImage"],
    [data-testid="stHorizontalBlock"] [data-testid="stImage"],
    [data-testid="stImage"] {
        background: transparent !important;
        padding: 0 !important;
    }
    [data-testid="stImage"] > div,
    [data-testid="stImage"] > div > div {
        background: transparent !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    [data-testid="stExpander"] [data-testid="stImage"] img:hover,
    .card-grid-col [data-testid="stImage"] img:hover,
    [data-testid="stHorizontalBlock"] [data-testid="stImage"] img:hover {
        transform: scale(1.05) rotate(2deg);
        border-color: var(--pokemon-yellow);
        box-shadow: 0 12px 32px rgba(238, 21, 21, 0.3);
    }

    hr {
        border: none;
        height: 4px;
        background: var(--pokemon-yellow);
        margin: 2rem 0;
        border-radius: 2px;
    }
    .stSuccess {
        background: #dcfce7;
        border: 3px solid var(--pokemon-green);
        border-radius: 12px;
        padding: 1rem;
        font-weight: 600;
        color: var(--text-primary);
    }
    .stWarning {
        background: #fed7aa;
        border: 3px solid #ff7518;
        border-radius: 12px;
        padding: 1rem;
        font-weight: 600;
        color: var(--text-primary);
    }
    h2 {
        font-size: 1.75rem;
        font-weight: 900;
        color: var(--pokemon-blue);
        text-transform: uppercase;
        margin-bottom: 2rem;
        padding-bottom: 0.5rem;
        border-bottom: 4px solid var(--pokemon-yellow);
    }
    .price-lg {
        font-size: 1.5rem;
        font-weight: 900;
        color: var(--pokemon-green);
    }
    p, span, div, label, .stMarkdown, 
    [data-testid="stCaptionContainer"],
    [data-testid="stText"] {
        color: var(--text-primary) !important;
    }
    .stTextInput label, 
    .stNumberInput label,
    .stSelectbox label,
    .stCheckbox label {
        color: var(--text-primary) !important;
    }
    div[data-testid="stRadio"] label p,
    div[data-testid="stRadio"] label span {
        color: #ffffff !important;
    }
</style>
""", unsafe_allow_html=True)

if "current_page" not in st.session_state:
    st.session_state.current_page="Accueil"

with st.sidebar:
    st.header("STATISTIQUES")
    st.caption(f"Version : {APP_BUILD}")
    sts=gst()
    
    pokeballs = [
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/poke-ball.png",
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/great-ball.png",
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/ultra-ball.png",
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/master-ball.png",
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/luxury-ball.png",
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/premier-ball.png"
    ]
    
    metrics_data = [
        ("Vendues", sts["sold_cards"], None),
        ("En stock", sts["remaining_cards"], None),
        ("Valeur stock", fp(sts["stock_value"]), None),
        ("Chiffre d'affaires", fp(sts["total_revenue"]), None),
        ("Bénéfice net", fp(sts["total_profit"]), fp(sts["total_profit"]) if sts["total_profit"] != 0 else None),
    ]
    
    for idx, (label, value, delta) in enumerate(metrics_data):
        if delta and delta != "0.00€":
            delta_val = float(delta.replace("€", "").replace(",", "."))
            if delta_val > 0:
                delta_bg = "#22c55e"
                delta_arrow = "↑"
            else:
                delta_bg = "#ef4444"
                delta_arrow = "↓"
            delta_html = f'<div style="display: inline-block; background: {delta_bg}; color: white; font-size: 0.875rem; font-weight: 700; padding: 0.35rem 0.75rem; border-radius: 12px; margin-top: 0.5rem;">{delta_arrow} {delta}</div>'
        else:
            delta_html = ''
        
        st.markdown(f"""
        <div style="position: relative; background: white; border: 3px solid #e2e8f0; border-radius: 16px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 4px 12px rgba(0,0,0,0.08);">
            <img src="{pokeballs[idx]}" style="position: absolute; top: -15px; right: 15px; width: 45px; height: 45px; background: white; border: 3px solid #e2e8f0; border-radius: 50%; padding: 5px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
            <div style="font-size: 0.75rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem;">{label}</div>
            <div style="font-size: 2rem; font-weight: 900; color: #1e293b; margin-bottom: 0.25rem;">{value}</div>
            {delta_html}
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    st.header("NAVIGATION")
    st.button("Accueil", use_container_width=True, key="nav_accueil", on_click=set_current_page, args=("Accueil",))
    st.button("Vente/Échange", use_container_width=True, key="nav_vente", on_click=set_current_page, args=("Vente",))
    st.button("Lots", use_container_width=True, key="nav_lots", on_click=set_current_page, args=("Lots",))
    st.button("Historique", use_container_width=True, key="nav_historique", on_click=set_current_page, args=("Historique",))
    st.button("📊 Statistiques", use_container_width=True, key="nav_statistiques", on_click=set_current_page, args=("Statistiques",))
    st.button("🎰 Compteurs", use_container_width=True, key="nav_compteurs", on_click=set_current_page, args=("Compteurs",))
    st.button("Archivés", use_container_width=True, key="nav_archives", on_click=set_current_page, args=("Archivés",))


# ============================================================
# PAGE ACCUEIL
# ============================================================
if st.session_state.current_page=="Accueil":
    st.markdown('<h2>Tableau de bord</h2>', unsafe_allow_html=True)
    
    pokeballs_main = [
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/quick-ball.png",
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/timer-ball.png",
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/repeat-ball.png",
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/net-ball.png",
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/dusk-ball.png"
    ]
    
    metrics_main = [
        ("VENDUES", str(sts["sold_cards"]), None),
        ("EN STOCK", str(sts["remaining_cards"]), None),
        ("VALEUR STOCK", fp(sts["stock_value"]), None),
        ("CA", fp(sts["total_revenue"]), None),
        ("BÉNÉFICE NET", fp(sts["total_profit"]), fp(sts["total_profit"]) if sts["total_profit"] != 0 else None)
    ]
    
    c1, c2, c3, c4, c5 = st.columns(5)
    cols = [c1, c2, c3, c4, c5]
    
    for idx, (col, (label, value, delta)) in enumerate(zip(cols, metrics_main)):
        with col:
            if delta and delta != "0.00€":
                delta_val = float(delta.replace("€", "").replace(",", "."))
                if delta_val > 0:
                    delta_bg = "#22c55e"
                    delta_arrow = "↑"
                else:
                    delta_bg = "#ef4444"
                    delta_arrow = "↓"
                delta_html = f'<div style="display: inline-block; background: {delta_bg}; color: white; font-size: 0.875rem; font-weight: 700; padding: 0.35rem 0.75rem; border-radius: 12px; margin-top: 0.5rem;">{delta_arrow} {delta}</div>'
            else:
                delta_html = ''
                
            st.markdown(f'''
            <div style="position: relative; background: white; border: 3px solid #e2e8f0; border-radius: 16px; padding: 1.5rem; padding-top: 2rem; box-shadow: 0 4px 12px rgba(0,0,0,0.08);">
                <img src="{pokeballs_main[idx]}" style="position: absolute; top: -15px; right: 15px; width: 50px; height: 50px; background: white; border: 3px solid #e2e8f0; border-radius: 50%; padding: 5px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                <div style="font-size: 0.75rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem;">{label}</div>
                <div style="font-size: 2rem; font-weight: 900; color: #1e293b; margin-bottom: 0.25rem;">{value}</div>
                {delta_html}
            </div>
            ''', unsafe_allow_html=True)
    
    st.markdown("---")
    c1,c2=st.columns(2)
    c1.button("Nouvelle vente",use_container_width=True,on_click=set_current_page,args=("Vente",))
    c2.button("Gérer les lots",use_container_width=True,on_click=set_current_page,args=("Lots",))

    # ── Graphiques d'évolution CA + Bénéfice ──
    st.markdown("---")
    st.markdown('<h2>📈 Évolution</h2>', unsafe_allow_html=True)

    # Collecter toutes les ventes avec date
    all_sales = []
    cd_graph = ld()
    total_cost_graph = sum(l.get("prix_achat",0.) for l in cd_graph.get("lots",[]))

    # Lots archivés aussi
    archive_file = "lots_archives.json"
    all_lots_graph = list(cd_graph.get("lots",[]))
    if os.path.exists(archive_file):
        try:
            with open(archive_file,"r",encoding="utf-8") as f:
                all_lots_graph += json.load(f)
            total_cost_graph += sum(l.get("prix_achat",0.) for l in json.load(open(archive_file,"r",encoding="utf-8")))
        except:
            pass

    for lot_g in all_lots_graph:
        for v in lot_g.get("ventes",[]):
            if v.get("date"):
                all_sales.append({"date": v["date"][:10], "amount": v.get("price",0.)})
        for c in lot_g.get("cards",[]):
            for s in c.get("sold_entries",[]):
                if s.get("date"):
                    all_sales.append({"date": s["date"][:10], "amount": s.get("price",0.)})

    if all_sales:
        # Agréger par jour
        from collections import defaultdict
        daily = defaultdict(float)
        for s in all_sales:
            daily[s["date"]] += s["amount"]

        dates_sorted = sorted(daily.keys())
        ca_cumul = []
        running = 0.
        for d in dates_sorted:
            running += daily[d]
            ca_cumul.append(running)

        benef_cumul = [ca - total_cost_graph for ca in ca_cumul]

        # Graphique avec plotly
        try:
            import plotly.graph_objects as go
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates_sorted, y=ca_cumul,
                mode='lines+markers', name='CA cumulé',
                line=dict(color='#3b4cca', width=3),
                marker=dict(size=6),
                fill='tozeroy', fillcolor='rgba(59,76,202,0.1)'
            ))
            fig.add_trace(go.Scatter(
                x=dates_sorted, y=benef_cumul,
                mode='lines+markers', name='Bénéfice cumulé',
                line=dict(color='#22c55e', width=3),
                marker=dict(size=6),
                fill='tozeroy', fillcolor='rgba(34,197,94,0.1)'
            ))
            # Ligne 0
            fig.add_hline(y=0, line_dash="dash", line_color="#ee1515", line_width=1, opacity=0.5)
            fig.update_layout(
                paper_bgcolor='white', plot_bgcolor='white',
                font=dict(family='Inter', color='#1e293b'),
                legend=dict(orientation='h', y=1.1),
                margin=dict(l=20, r=20, t=20, b=20),
                xaxis=dict(gridcolor='#f1f5f9', showgrid=True),
                yaxis=dict(gridcolor='#f1f5f9', showgrid=True, ticksuffix='€'),
                height=350
            )
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            # Fallback sans plotly
            col_g1, col_g2 = st.columns(2)
            col_g1.metric("CA cumulé", fp(ca_cumul[-1]) if ca_cumul else "0.00€")
            col_g2.metric("Bénéfice cumulé", fp(benef_cumul[-1]) if benef_cumul else "0.00€")
    else:
        st.info("Aucune vente enregistrée pour afficher le graphique.")

    # ── Recherche globale ──
    st.markdown("---")
    st.markdown('<h2>🔍 Recherche globale</h2>', unsafe_allow_html=True)
    search_global = st.text_input("🔍 Recherche", placeholder="Chercher une carte dans tous les lots...", key="global_search")

    if search_global and len(search_global) >= 2:
        cd_search = ld()
        results_found = []

        all_lots_search = [(l, "actif") for l in cd_search.get("lots",[])]
        if os.path.exists("lots_archives.json"):
            try:
                with open("lots_archives.json","r",encoding="utf-8") as f:
                    for l in json.load(f):
                        all_lots_search.append((l, "archivé"))
            except:
                pass

        for lot_s, lot_type in all_lots_search:
            for ci, card in enumerate(lot_s.get("cards",[])):
                if normalize_name(search_global) in normalize_name(card.get("name","")):
                    results_found.append({
                        "card": card,
                        "lot_name": lot_s["nom"],
                        "lot_type": lot_type,
                        "stock": card["quantity"] - card.get("sold_quantity", 0)
                    })

        if results_found:
            st.caption(f"{len(results_found)} résultat(s) pour « {search_global} »")
            COLS_S = 6
            for row_start in range(0, len(results_found), COLS_S):
                cols_s = st.columns(COLS_S)
                for col_idx, res in enumerate(results_found[row_start:row_start+COLS_S]):
                    with cols_s[col_idx]:
                        if res["card"].get("image_url"):
                            st.image(proxy_img(res["card"]["image_url"]), width="stretch")
                        st.markdown(f"**{res['card']['name']}**")
                        st.caption(f"{res['card']['set']} · #{res['card']['number']}")
                        st.caption(f"📦 {res['lot_name']} ({res['lot_type']})")
                        stock_color = "#22c55e" if res["stock"] > 0 else "#94a3b8"
                        st.markdown(f'<span style="color:{stock_color};font-weight:700;font-size:0.85rem;">{"✅ Stock : "+str(res["stock"]) if res["stock"] > 0 else "❌ Épuisé"}</span>', unsafe_allow_html=True)
                        st.caption(f"💰 {fp(res['card'].get('suggested_price',0))}")
        else:
            st.info(f"Aucune carte trouvée pour « {search_global} »")


# ============================================================
# PAGE VENTE
# ============================================================
elif st.session_state.current_page=="Vente":
    components.html("""
    <script>
    (function(){
        const scrollTop = () => parent.window.scrollTo({top:0,left:0,behavior:'instant'});
        scrollTop();
        const waitForImagesThenScroll = () => {
            const imgs = Array.from(parent.document.querySelectorAll('img'));
            if (!imgs.length) { scrollTop(); return; }
            let pending = imgs.filter(img => !img.complete).length;
            if (pending === 0) { scrollTop(); return; }
            const done = () => { pending -= 1; if (pending <= 0) scrollTop(); };
            imgs.forEach(img => {
                if (img.complete) return;
                img.addEventListener('load', done, {once:true});
                img.addEventListener('error', done, {once:true});
            });
            setTimeout(scrollTop, 6000);
        };
        setTimeout(waitForImagesThenScroll, 250);
    })();
    </script>
    """, height=0)
    st.markdown('<h2>💰 Vente / Échange</h2>', unsafe_allow_html=True)
    
    tab2, tab3 = st.tabs(["💰 Vente", "🔄 Échange"])

    with tab2:
        st.subheader("Vente")
        
        cd=ld()
        if not cd.get("lots"):
            st.warning("Créez d'abord un lot")
        else:
            if "bulk_cart" not in st.session_state:
                st.session_state.bulk_cart = []

            # ── Barre de recherche + filtre lot + compteur panier ──
            col_search, col_lot_filter, col_cart = st.columns([3, 2, 1])
            with col_search:
                search_vente = st.text_input("🔍 Rechercher une carte", placeholder="Nom de la carte...", key="search_vente", label_visibility="collapsed")
            with col_lot_filter:
                vente_lots_with_idx = sorted(
                    list(enumerate(cd.get("lots", []))),
                    key=lambda item: (0 if (is_trade_lot(item[1]) or is_storage_lot(item[1])) else 1, item[0])
                )
                lot_options = [("Tous les lots", None)] + [(f"{i+1}. {lot.get('nom', f'Lot {i+1}')}", i) for i, lot in vente_lots_with_idx]
                lot_labels = [name for name, _ in lot_options]
                selected_lot_label = st.selectbox("Lot affiché", lot_labels, key="bulk_lot_filter_v2", label_visibility="collapsed")
                selected_lot_idx = next(idx for name, idx in lot_options if name == selected_lot_label)
            with col_cart:
                nb_panier = sum(item["quantity"] for item in st.session_state.bulk_cart)
                total_panier = sum(item["quantity"] * item["price_base"] for item in st.session_state.bulk_cart)
                if nb_panier > 0:
                    st.button(f"🛒 {nb_panier} · {fp(total_panier)}", key="btn_panier", use_container_width=True, type="primary", on_click=scroll_to_cart_prepare)
                else:
                    st.markdown('<div style="background:#e2e8f0;color:#64748b;padding:0.5rem 1rem;border-radius:12px;font-weight:700;text-align:center;">🛒 Vide</div>', unsafe_allow_html=True)

            # Scroll vers le panier si demandé
            if st.session_state.get("scroll_to_cart"):
                st.session_state["scroll_to_cart"] = False
                components.html('<script>setTimeout(()=>{const el=parent.document.getElementById("cart-anchor");if(el)el.scrollIntoView({behavior:"smooth"});},200);</script>', height=0)

            # Construire liste panier pour vérification rapide
            cart_keys = {item.get("card_uid") for item in st.session_state.bulk_cart if item.get("card_uid")}

            # ── Grille par lot ou grille globale si recherche ──
            if search_vente:
                # Recherche active → toutes les cartes trouvées en une seule grille
                all_found = []
                for li, lot in vente_lots_with_idx:
                    if selected_lot_idx is not None and li != selected_lot_idx:
                        continue
                    for ci, card in enumerate(lot.get("cards", [])):
                        if card_available_qty(card) > 0 and normalize_name(search_vente) in normalize_name(card.get("name","")):
                            all_found.append((li, ci, card, lot))

                COLS_PER_ROW = 6
                for row_start in range(0, len(all_found), COLS_PER_ROW):
                    cols = st.columns(COLS_PER_ROW)
                    for col_idx, (li, ci, card, lot) in enumerate(all_found[row_start:row_start + COLS_PER_ROW]):
                        stock = card_available_qty(card)
                        in_cart = card.get("card_uid") in cart_keys
                        with cols[col_idx]:
                            if card.get("image_url"):
                                if in_cart:
                                    st.markdown(f'<div style="position:relative"><img src="{proxy_img(card["image_url"])}" style="width:100%;border-radius:12px;border:4px solid #22c55e;"><div style="position:absolute;top:5px;right:5px;background:#22c55e;color:white;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:0.8rem;">✓</div></div>', unsafe_allow_html=True)
                                else:
                                    st.image(proxy_img(card["image_url"]), width="stretch")
                            else:
                                st.markdown("🃏")
                            st.markdown(f"**{card['name']}**")
                            st.caption(f"{card.get('set','')} · #{card.get('number','')}")
                            st.caption(f"💰 {fp(card.get('suggested_price', 0))} · 📦 {stock}")
                            st.caption(f"🗂️ {lot['nom']}")
                            q_key = card.get("card_uid") or f"{li}_{ci}"
                            q_add = st.number_input("Qté", 1, stock, 1, key=f"bulk_q_{q_key}")
                            if in_cart:
                                st.button("✅ Dans le panier", key=f"add_{li}_{ci}", use_container_width=True, on_click=bulk_cart_remove, kwargs={"card_uid": card.get("card_uid")})
                            else:
                                st.button("🛒 Ajouter", key=f"add_{li}_{ci}", use_container_width=True, type="primary", on_click=bulk_cart_add, args=({"lot_idx":li,"card_idx":ci,"lot_uid":lot.get("lot_uid"),"card_uid":card.get("card_uid"),"lot_name":lot['nom'],"card_name":card['name'],"card_set":card.get('set',''),"quantity":q_add,"price_base":card.get("suggested_price",0),"lot_profitable":cp(lot)>=0},))
            else:
                # Pas de recherche → groupé par lot avec titre
                for li, lot in vente_lots_with_idx:
                    if selected_lot_idx is not None and li != selected_lot_idx:
                        continue
                    cards_in_stock = [(ci, c) for ci, c in enumerate(lot.get("cards", [])) if card_available_qty(c) > 0]
                    if cards_in_stock:
                        st.markdown(f"### 📦 {lot['nom']}")
                        COLS_PER_ROW = 6
                        for row_start in range(0, len(cards_in_stock), COLS_PER_ROW):
                            cols = st.columns(COLS_PER_ROW)
                            for col_idx, (ci, card) in enumerate(cards_in_stock[row_start:row_start + COLS_PER_ROW]):
                                stock = card_available_qty(card)
                                in_cart = card.get("card_uid") in cart_keys
                                with cols[col_idx]:
                                    if card.get("image_url"):
                                        if in_cart:
                                            st.markdown(f'<div style="position:relative"><img src="{proxy_img(card["image_url"])}" style="width:100%;border-radius:12px;border:4px solid #22c55e;"><div style="position:absolute;top:5px;right:5px;background:#22c55e;color:white;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:0.8rem;">✓</div></div>', unsafe_allow_html=True)
                                        else:
                                            st.image(proxy_img(card["image_url"]), width="stretch")
                                    else:
                                        st.markdown("🃏")
                                    st.markdown(f"**{card['name']}**")
                                    st.caption(f"{card['set']} · #{card['number']}")
                                    st.caption(f"💰 {fp(card.get('suggested_price', 0))} · 📦 {stock}")
                                    q_key = card.get("card_uid") or f"{li}_{ci}"
                                    q_add = st.number_input("Qté", 1, stock, 1, key=f"bulk_q_{q_key}")
                                    if in_cart:
                                        st.button("✅ Dans le panier", key=f"add_{li}_{ci}", use_container_width=True, on_click=bulk_cart_remove, kwargs={"card_uid": card.get("card_uid")})
                                    else:
                                        st.button("🛒 Ajouter", key=f"add_{li}_{ci}", use_container_width=True, type="primary", on_click=bulk_cart_add, args=({"lot_idx":li,"card_idx":ci,"lot_uid":lot.get("lot_uid"),"card_uid":card.get("card_uid"),"lot_name":lot['nom'],"card_name":card['name'],"card_set":card['set'],"quantity":q_add,"price_base":card.get("suggested_price",0),"lot_profitable":cp(lot)>=0},))
                        st.markdown("---")
            
            # ── Panier ──
            st.markdown('<div id="cart-anchor"></div>', unsafe_allow_html=True)
            if not st.session_state.bulk_cart:
                st.info("📭 Panier vide - Cliquez sur 🛒 Ajouter pour ajouter des cartes")
            else:
                st.markdown("### 🛒 Panier")
                total_base = sum(item["quantity"] * item["price_base"] for item in st.session_state.bulk_cart)
                
                for idx, item in enumerate(st.session_state.bulk_cart):
                    _, _, _, cart_card = resolve_card_ref(cd, item)
                    max_cart_qty = max(card_available_qty(cart_card), 1) if cart_card else int(item["quantity"])
                    if int(item["quantity"]) > max_cart_qty:
                        item["quantity"] = max_cart_qty
                        save_activity_state()
                    cols = st.columns([3, 1, 1, 1, 1, 1])
                    cols[0].write(f"{item['card_name']} ({item['card_set']}) - {item['lot_name']}")
                    cols[1].number_input("Qté", 1, max_cart_qty, int(item["quantity"]), key=f"cart_qty_{idx}", on_change=bulk_cart_set_quantity, args=(idx,), label_visibility="collapsed")
                    cols[2].write(f"{fp(item['price_base'])}/u")
                    cols[3].write(f"= {fp(item['quantity'] * item['price_base'])}")
                    cols[4].button("➕", key=f"plus_{idx}", on_click=bulk_cart_increment, args=(idx,))
                    cols[5].button("🗑️", key=f"remove_{idx}", on_click=bulk_cart_pop, args=(idx,))
                
                st.markdown("---")
                st.markdown(f"**Prix total de base : {fp(total_base)}**")
                
                vente_col1, vente_col2 = st.columns(2)
                
                with vente_col1:
                    st.button("✅ Vendre au prix de base", type="primary", use_container_width=True, on_click=bulk_sale_prepare, args=("base", total_base))
                
                    negociated_price = st.number_input("💰 Prix négocié", 0., float(total_base)*2, float(total_base), 0.5, key="negociated_price")
                    st.button("🤝 Vendre au prix négocié", use_container_width=True, on_click=bulk_sale_prepare, args=("negociated", negociated_price))

                # Dialog canal pour vente en lot
                if st.session_state.get("show_canal_dialog_bulk"):
                    st.session_state["show_canal_dialog_bulk"] = False
                    pending = st.session_state.get("pending_bulk_sale", {})

                    @st.dialog("📡 Canal de vente")
                    def ask_canal_bulk():
                        st.markdown(f"**Vente — {fp(pending.get('price', 0))}**")
                        CANAUX = ["Main propre", "Brocante", "Dexify_TCG", "Pokédeal"]
                        canal_b = st.selectbox("Via quel canal ?", CANAUX, key="canal_bulk_sel")
                        c1, c2 = st.columns(2)
                        if c1.button("✅ Confirmer", type="primary", use_container_width=True):
                            if pending.get("type") == "base":
                                sale_items = [
                                    {**item, "unit_price": item["price_base"]}
                                    for item in st.session_state.bulk_cart
                                ]
                            else:
                                cd_bulk = ld()
                                def get_lot_score(lot_idx):
                                    lot_data = cd_bulk["lots"][lot_idx]
                                    pa = lot_data.get("prix_achat", 0.)
                                    ca = cr(lot_data)
                                    stock_val = sum(card_available_qty(c)*c.get("suggested_price",0.) for c in lot_data.get("cards",[]))
                                    taux_remb = (ca / pa) if pa > 0 else 1.0
                                    return max(taux_remb * (ca + stock_val), 0.01)
                                reduction = total_base - pending["price"]
                                MAX_REDUCTION_RATE = 0.30
                                scores = [get_lot_score(item["lot_idx"]) * item["quantity"] * item["price_base"] for item in st.session_state.bulk_cart]
                                total_score = sum(scores) or 1.
                                reductions = [min(reduction * (s/total_score), item["quantity"]*item["price_base"]*MAX_REDUCTION_RATE) for s, item in zip(scores, st.session_state.bulk_cart)]
                                sale_items = []
                                for i, item in enumerate(st.session_state.bulk_cart):
                                    item_price = max(0, (item["quantity"]*item["price_base"] - reductions[i]) / item["quantity"])
                                    sale_items.append({**item, "unit_price": item_price})
                            ok, msg = scu_many(sale_items, canal_b)
                            if ok:
                                st.session_state.bulk_cart = []
                                st.session_state["pending_bulk_sale"] = {}
                                st.session_state["show_canal_dialog_bulk"] = False
                                save_activity_state()
                            else:
                                st.error(msg)
                            st.rerun()
                        if c2.button("❌ Annuler", use_container_width=True):
                            st.rerun()

                    ask_canal_bulk()
                
                st.button("🗑️ Vider le panier", on_click=bulk_cart_clear)

    with tab3:
        st.subheader("🔄 Échange de cartes")
        st.caption("Échange un ou plusieurs cartes de tes lots contre d'autres cartes.")
        cd_sw = ld()
        trade_snapshot = json.dumps(cd_sw.get("lots", []), ensure_ascii=False, sort_keys=True)
        ensure_trade_lot(cd_sw)
        migrate_open_trade_cards(cd_sw)
        if json.dumps(cd_sw.get("lots", []), ensure_ascii=False, sort_keys=True) != trade_snapshot:
            sd(cd_sw)
            cd_sw = ld()

        # ── Panier d'échange (cartes à donner) ──
        if "swap_cart_give" not in st.session_state:
            st.session_state.swap_cart_give = []  # liste de {lot_idx, card_idx, card_name, set, number, value}
        if "swap_cart_receive" not in st.session_state:
            st.session_state.swap_cart_receive = []  # liste de {name, set, number, value, lot_target_idx}

        col_give, col_receive = st.columns(2)

        # ── Colonne DONNER ──
        with col_give:
            st.markdown("### 📤 Cartes à donner")
            search_sw = st.text_input("🔍 Chercher une carte à donner", placeholder="Nom...", key="search_swap")

            all_stock_sw = []
            for li, lot in enumerate(cd_sw.get("lots", [])):
                for ci, card in enumerate(lot.get("cards", [])):
                    stock = card.get("quantity", 0) - card.get("sold_quantity", 0)
                    if stock > 0:
                        if not search_sw or normalize_name(search_sw) in normalize_name(card.get("name", "")):
                            all_stock_sw.append((li, ci, card, lot, stock))

            give_keys = {g.get("card_uid") for g in st.session_state.swap_cart_give if g.get("card_uid")}

            for li, ci, card, lot, stock in all_stock_sw[:24]:
                in_give = card.get("card_uid") in give_keys
                c_img, c_info, c_btn = st.columns([1, 3, 1])
                with c_img:
                    # image_url est déjà l'URL complète stockée dans la carte
                    img_sw = card.get("image_url","") or card.get("image","")
                    if img_sw:
                        border = "border:3px solid #ef4444;" if in_give else ""
                        st.markdown(f'<img src="{proxy_img(img_sw)}" style="width:60px;border-radius:8px;{border}">', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="width:60px;height:84px;background:#f1f5f9;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1.5rem;">🃏</div>', unsafe_allow_html=True)
                with c_info:
                    st.markdown(f"**{card['name']}**")
                    st.caption(f"{lot['nom']} · {fp(card.get('suggested_price',0))}")
                with c_btn:
                    if in_give:
                        if st.button("❌", key=f"sw_rm_{li}_{ci}"):
                            st.session_state.swap_cart_give = [g for g in st.session_state.swap_cart_give if not (g.get("card_uid")==card.get("card_uid") or (g["lot_idx"]==li and g["card_idx"]==ci))]
                            save_activity_state()
                            st.rerun()
                    else:
                        if st.button("➕", key=f"sw_add_{li}_{ci}"):
                            st.session_state.swap_cart_give.append({"lot_idx":li,"card_idx":ci,"lot_uid":lot.get("lot_uid"),"card_uid":card.get("card_uid"),"card_name":card["name"],"set":card.get("set",""),"number":card.get("number",""),"value":float(card.get("suggested_price",0)),"lot_name":lot["nom"]})
                            save_activity_state()
                            st.rerun()

            if st.session_state.swap_cart_give:
                st.markdown("---")
                st.markdown("**Cartes à donner :**")
                total_give = 0.
                for g in st.session_state.swap_cart_give:
                    st.markdown(f"• {g['card_name']} ({fp(g['value'])})")
                    total_give += g["value"]
                st.metric("Total donné", fp(total_give))

        # ── Colonne RECEVOIR ──
        with col_receive:
            st.markdown("### 📥 Cartes à recevoir")
            st.caption("Les cartes reçues seront rangées dans le lot Trade. Leur valeur de stock et leur future vente seront attribuées aux lots contributeurs selon leur part.")

            # Ajouter une carte à recevoir
            with st.expander("➕ Ajouter une carte reçue", expanded=len(st.session_state.swap_cart_receive)==0):
                # Initialiser les clés si absentes
                if st.session_state.pop("clear_recv_fields", False):
                    for key in ("recv_name", "recv_num", "recv_val"):
                        st.session_state.pop(key, None)
                    st.session_state.recv_name_val = ""
                    st.session_state.recv_num_val = ""
                if "recv_name_val" not in st.session_state:
                    st.session_state.recv_name_val = ""
                if "recv_num_val" not in st.session_state:
                    st.session_state.recv_num_val = ""

                def on_recv_change():
                    st.rerun()

                r1, r2 = st.columns(2)
                recv_name = r1.text_input("Nom de la carte", key="recv_name",
                    placeholder="Ex: Lugia",
                    value=st.session_state.recv_name_val)
                recv_num = r2.text_input("Numéro", key="recv_num",
                    placeholder="Ex: 042",
                    value=st.session_state.recv_num_val)
                recv_val = st.number_input("Valeur estimée (€)", 0., 9999., 0., 0.5, key="recv_val")

                # Mettre à jour les valeurs en session
                st.session_state.recv_name_val = recv_name
                st.session_state.recv_num_val = recv_num

                # Recherche image via le cache - utilise ecd comme acm
                recv_image_url = ""
                recv_set_name = ""
                set_id_sw_prev = ""
                local_id_sw_prev = ""
                if recv_name and recv_num:
                    try:
                        cards_index = st.session_state.get("cards_index", {})
                        name_norm_sw = normalize_name(recv_name.lower())
                        candidates = []
                        if name_norm_sw in cards_index:
                            candidates = list(cards_index[name_norm_sw])
                        if not candidates:
                            for k, v in cards_index.items():
                                if name_norm_sw in k:
                                    candidates.extend(v)

                        st.caption(f"🔍 {len(candidates)} carte(s) trouvée(s) pour « {recv_name} » dans le cache")

                        if candidates:
                            num_filtered = [
                                (c,sn,sid) for c,sn,sid in candidates
                                if str(c.get("localId","")).lstrip("0") == recv_num.lstrip("0")
                                or str(c.get("number","")).lstrip("0") == recv_num.lstrip("0")
                            ]
                            st.caption(f"🔢 Après filtrage numéro {recv_num} : {len(num_filtered)} résultat(s)")
                            if num_filtered:
                                card_sw, set_name_sw, set_id_sw = num_filtered[0]
                                local_id_sw_prev = str(card_sw.get("localId","") or card_sw.get("number",""))
                                set_id_sw_prev = set_id_sw
                                st.caption(f"✅ Carte sélectionnée : {card_sw.get('name','')} — set={set_id_sw} n°{local_id_sw_prev}")
                                enriched_sw = ecd(card_sw, set_name_sw, lang="fr")
                                recv_image_url = enriched_sw.get("image_url", "")
                                recv_set_name = set_name_sw
                                st.caption(f"🖼️ URL image : {recv_image_url[:60] if recv_image_url else 'VIDE'}")
                            else:
                                st.caption(f"⚠️ Aucune carte avec le numéro {recv_num} dans le cache")
                        else:
                            st.caption(f"⚠️ Nom « {recv_name} » introuvable dans le cache")
                    except Exception as e:
                        st.caption(f"❌ Erreur : {e}")

                recv_name = recv_name.strip().title() if recv_name else recv_name

                if recv_image_url and recv_name and recv_num:
                    url_en_prev = f"https://assets.tcgdex.net/en/{set_id_sw_prev}/{local_id_sw_prev}/high.webp" if set_id_sw_prev else ""
                    st.markdown(img_with_fallback(recv_image_url, url_en_prev, width="80px", style="border-radius:8px;margin:0.3rem 0;"), unsafe_allow_html=True)
                elif recv_name and recv_num:
                    st.warning("📷 Carte non trouvée dans la base. Tu pourras ajouter la photo manuellement via 🖼️ une fois la carte ajoutée au lot.")
                elif recv_name and not recv_num:
                    st.caption("💡 Ajoute le numéro pour afficher la bonne carte")

                if st.button("➕ Ajouter cette carte", key="add_recv"):
                    if recv_name:
                        st.session_state.swap_cart_receive.append({
                            "name": recv_name,
                            "set": recv_set_name,
                            "number": recv_num,
                            "value": recv_val,
                            "image_url": recv_image_url,
                        })
                        # Vider vraiment les champs du formulaire au prochain affichage.
                        st.session_state.recv_name_val = ""
                        st.session_state.recv_num_val = ""
                        st.session_state["clear_recv_fields"] = True
                        save_activity_state()
                        st.rerun()

            if st.session_state.swap_cart_receive:
                st.markdown("**Cartes à recevoir :**")
                total_receive = 0.
                for i, r in enumerate(st.session_state.swap_cart_receive):
                    rc1, rc2, rc3 = st.columns([1, 4, 1])
                    if r.get("image_url"):
                        rc1.markdown(f'<img src="{proxy_img(r["image_url"])}" style="width:45px;border-radius:6px;">', unsafe_allow_html=True)
                    else:
                        rc1.markdown("🃏")
                    rc2.markdown(f"**{r['name']}** ({fp(r['value'])})")
                    if rc3.button("❌", key=f"rm_recv_{i}"):
                        st.session_state.swap_cart_receive.pop(i)
                        save_activity_state()
                        st.rerun()
                    total_receive += r["value"]
                st.metric("Total reçu", fp(total_receive))

                # Afficher la répartition prévue
                if st.session_state.swap_cart_give:
                    total_give_val = sum(g["value"] for g in st.session_state.swap_cart_give)
                    diff = total_receive - total_give_val
                    diff_color = "#10b981" if diff >= 0 else "#ef4444"
                    st.markdown(f'<div style="font-size:0.9rem;font-weight:700;color:{diff_color};">{"📈" if diff>=0 else "📉"} Différence : {diff:+.2f}€</div>', unsafe_allow_html=True)

                    # Prévisualiser la répartition par lot
                    st.markdown("---")
                    st.markdown("**📊 Répartition automatique du bénéfice par lot :**")
                    st.caption("Les cartes reçues iront dans le lot Trade. Ici, on affiche seulement la part de valeur attribuée à chaque lot contributeur : la carte n'est pas dupliquée.")
                    valeur_par_lot = {}
                    for g in st.session_state.swap_cart_give:
                        li, _, _, _ = resolve_card_ref(cd_sw, g)
                        if li is None:
                            continue
                        valeur_par_lot[li] = valeur_par_lot.get(li, 0.) + g["value"]
                    total_contrib = sum(valeur_par_lot.values()) or 1.
                    for li, val in valeur_par_lot.items():
                        lot_nom = cd_sw["lots"][li]["nom"]
                        pct = val / total_contrib * 100
                        valeur_estimee_trade = sum(r["value"] for r in st.session_state.swap_cart_receive) * pct / 100
                        st.markdown(f'<div style="font-size:0.82rem;color:#64748b;">🗂️ <b>{lot_nom}</b> — contribution {pct:.0f}% → {valeur_estimee_trade:.2f}€ de valeur Trade attribuée</div>', unsafe_allow_html=True)

        # ── Bouton confirmer l'échange ──
        if st.session_state.swap_cart_give and st.session_state.swap_cart_receive:
            st.markdown("---")
            if st.button("✅ Confirmer l'échange", type="primary", use_container_width=True):
                cdd = ld()
                # Calculer la valeur totale donnée par lot
                valeur_par_lot_donne = {}
                for g in st.session_state.swap_cart_give:
                    li, ci, lot_g, card_g_ref = resolve_card_ref(cdd, g)
                    if card_g_ref is None:
                        st.error(f"Carte introuvable dans l'échange : {g.get('card_name', 'carte inconnue')}")
                        st.stop()
                    g["lot_idx"], g["card_idx"] = li, ci
                    valeur_par_lot_donne[li] = valeur_par_lot_donne.get(li, 0.) + g["value"]
                total_valeur_donnee = sum(valeur_par_lot_donne.values()) or 1.

                # Marquer les cartes données comme échangées
                for g in st.session_state.swap_cart_give:
                    _, _, _, card_g = resolve_card_ref(cdd, g)
                    if card_g is None:
                        continue
                    card_g["sold_quantity"] = card_g.get("sold_quantity", 0) + 1
                    card_g.setdefault("sold_entries", []).append({
                        "date": datetime.now().isoformat(),
                        "quantity": 1, "price": 0.,
                        "card_name": card_g["name"],
                        "card_set": card_g.get("set",""),
                        "card_number": card_g.get("number",""),
                        "suggested_price_at_sale": float(card_g.get("suggested_price",0)),
                        "canal": "Échange", "is_exchange": True,
                        "exchanged_for": ", ".join(r["name"] for r in st.session_state.swap_cart_receive),
                    })

                # Ajouter les cartes reçues dans le lot Trade unique.
                trade_lot_idx = ensure_trade_lot(cdd)

                for r in st.session_state.swap_cart_receive:
                    new_card = {
                        "name": r["name"], "set": r.get("set",""), "number": r.get("number",""),
                        "suggested_price": r["value"], "quantity": 1, "sold_quantity": 0,
                        "condition": "NM", "is_reverse": False, "is_ed1": False,
                        "image_url": r.get("image_url",""), "sold_entries": [],
                        "received_by_exchange": True,
                        "exchanged_from": ", ".join(g["card_name"] for g in st.session_state.swap_cart_give),
                        "exchange_repartition": {
                            str(li_donne): (valeur_par_lot_donne[li_donne] / total_valeur_donnee) * r["value"]
                            for li_donne in valeur_par_lot_donne
                        },
                        "exchange_date": datetime.now().isoformat()[:10],
                    }
                    cdd["lots"][trade_lot_idx]["cards"].append(new_card)
                sd(cdd)
                nb_give = len(st.session_state.swap_cart_give)
                nb_recv = len(st.session_state.swap_cart_receive)
                st.session_state.swap_cart_give = []
                st.session_state.swap_cart_receive = []
                save_activity_state()
                st.success(f"✅ Échange confirmé : {nb_give} carte(s) donnée(s) contre {nb_recv} carte(s) reçue(s) !")
                st.rerun()


# ============================================================
# PAGE LOTS
# ============================================================
elif st.session_state.current_page=="Lots":
    st.markdown('<h2>Gestion des lots</h2>', unsafe_allow_html=True)

    cd = ld()  # Charger les données en premier
    lots_snapshot = json.dumps(cd.get("lots", []), ensure_ascii=False, sort_keys=True)
    ensure_system_lots(cd)
    migrate_open_trade_cards(cd)
    if json.dumps(cd.get("lots", []), ensure_ascii=False, sort_keys=True) != lots_snapshot:
        sd(cd)
        cd = ld()

    # Bordures et ouverture rapide des lots sans charger tous les détails d'un coup.
    components.html("""<script>
    (function(){
        const doc = parent.document;
        function syncLotHeaders() {
            const markers = doc.querySelectorAll('[data-lot-index]');
            const allExpanders = doc.querySelectorAll('[data-testid="stExpander"]');
            const lotButtons = Array.from(doc.querySelectorAll('button')).filter(function(btn) {
                const label = (btn.innerText || '').trim();
                return label.startsWith('› ') || label.startsWith('▼ ');
            });
            markers.forEach(function(marker, idx) {
                let color = '#22c55e';
                const status = marker.getAttribute('data-lot-status');
                if (status === 'not-profitable') color = '#ee1515';
                if (status === 'brocante') color = '#f97316';
                if (status === 'collection') color = '#3b4cca';
                if (status === 'trade') color = '#0891b2';
                if (status === 'storage') color = '#7c3aed';
                const target = lotButtons[idx] || allExpanders[idx + 1];
                if (!target) return;
                const isOpen = (target.innerText || '').trim().startsWith('▼ ');
                target.style.setProperty('background', isOpen ? '#f8fafc' : '#ffffff', 'important');
                target.style.setProperty('color', '#0f172a', 'important');
                target.style.setProperty('border-left', '8px solid ' + color, 'important');
                target.style.setProperty('border-radius', '8px', 'important');
                target.style.setProperty('border-top', '1px solid #e2e8f0', 'important');
                target.style.setProperty('border-right', '1px solid #e2e8f0', 'important');
                target.style.setProperty('border-bottom', '1px solid #e2e8f0', 'important');
                target.style.setProperty('justify-content', 'flex-start', 'important');
                target.style.setProperty('text-align', 'left', 'important');
                target.style.setProperty('align-items', 'center', 'important');
                target.style.setProperty('text-transform', 'none', 'important');
                target.style.setProperty('font-weight', '500', 'important');
                target.style.setProperty('font-size', '0.95rem', 'important');
                target.style.setProperty('min-height', '68px', 'important');
                target.style.setProperty('padding', '1rem 1.25rem', 'important');
                target.style.setProperty('box-shadow', '0 4px 12px rgba(15, 23, 42, 0.08)', 'important');
                target.style.setProperty('transform', 'none', 'important');
                target.style.setProperty('margin-bottom', '0.35rem', 'important');
                target.querySelectorAll('div, p, span').forEach(function(child) {
                    child.style.setProperty('text-align', 'left', 'important');
                    child.style.setProperty('justify-content', 'flex-start', 'important');
                    child.style.setProperty('text-transform', 'none', 'important');
                });
            });

            const addMarker = doc.querySelector('[data-add-card-form-marker]');
            if (addMarker) {
                const lotBlock = addMarker.closest('[data-testid="stVerticalBlock"]');
                const markerChild = addMarker.closest('[data-testid="stElementContainer"]');
                if (lotBlock && markerChild) {
                    const children = Array.from(lotBlock.children);
                    const markerIndex = children.indexOf(markerChild);
                    const formParts = children.slice(markerIndex + 1, markerIndex + 5);
                    let topOffset = 54;
                    formParts.forEach(function(part) {
                        part.setAttribute('data-codex-add-sticky', '1');
                        part.style.setProperty('position', 'sticky', 'important');
                        part.style.setProperty('top', topOffset + 'px', 'important');
                        part.style.setProperty('z-index', '900', 'important');
                        part.style.setProperty('background', '#eef3f8', 'important');
                        part.style.setProperty('width', 'calc(100% - 2rem)', 'important');
                        part.style.setProperty('max-width', 'calc(100% - 2rem)', 'important');
                        part.style.setProperty('box-shadow', '0 0 0 rgba(15, 23, 42, 0)', 'important');
                        part.style.setProperty('padding', '0.25rem 1.25rem', 'important');
                        part.style.setProperty('margin', '0 1rem', 'important');
                        part.style.setProperty('border-left', '1px solid #111827', 'important');
                        part.style.setProperty('border-right', '1px solid #111827', 'important');
                        part.style.setProperty('outline', 'none', 'important');
                        part.querySelectorAll('button').forEach(function(btn) {
                            btn.style.setProperty('width', '100%', 'important');
                        });
                        if (part === formParts[0]) {
                            part.style.setProperty('border-top', '1px solid #111827', 'important');
                            part.style.setProperty('border-radius', '12px 12px 0 0', 'important');
                            part.style.setProperty('padding-top', '0.45rem', 'important');
                        }
                        if (part === formParts[formParts.length - 1]) {
                            part.style.setProperty('border-bottom', '1px solid #111827', 'important');
                            part.style.setProperty('border-radius', '0 0 12px 12px', 'important');
                            part.style.setProperty('padding-bottom', '0.75rem', 'important');
                        }
                        topOffset += Math.max(part.getBoundingClientRect().height, 1);
                    });
                }
            }
        }
        syncLotHeaders();
        [100, 250, 600, 1200, 2500, 5000].forEach(function(delay) {
            setTimeout(syncLotHeaders, delay);
        });
        const observer = new MutationObserver(function() {
            clearTimeout(window.codexLotStyleTimer);
            window.codexLotStyleTimer = setTimeout(syncLotHeaders, 150);
        });
        observer.observe(doc.body, {childList: true, subtree: true});
        const intervalId = setInterval(syncLotHeaders, 5000);
        setTimeout(function(){ clearInterval(intervalId); observer.disconnect(); }, 45000);
    })();
    </script>""", height=0)

    # ── Tabs : Lot normal / Lot Brocante ──
    with st.expander("➕ Créer un nouveau lot", expanded=False):
        st.subheader("Nouveau lot")
        c1,c2,c3=st.columns(3)
        nm=c1.text_input("Nom du lot",placeholder="Ex: Lot EV 4.5",key="new_lot_name")
        pa=c2.number_input("Prix d'achat (€)",0.,99999.,0.,0.5,key="new_lot_price")
        va=c3.number_input("Déjà vendu (€)",0.,99999.,0.,0.5,key="new_lot_sold")

        # Options du lot
        opt1, opt2 = st.columns(2)
        is_brocante_new = opt1.checkbox("🎪 Lot Brocante", key="new_lot_brocante",
                                         help="Lot acheté en brocante / vide-grenier")
        is_collection_new = opt2.checkbox("🏠 Lot Collection", key="new_lot_collection",
                                           help="Une partie pour ta collection, une partie à vendre")

        valeur_totale_mixte = 0.
        if is_collection_new:
            st.info("💡 La valeur des cartes à vendre sera calculée automatiquement depuis leurs prix suggérés une fois ajoutées. Saisis juste la valeur totale du lot.")
            valeur_totale_mixte = st.number_input("Valeur totale du lot (€)", 0., 99999., 0., 1., key="new_lot_valeur_totale",
                                                   help="Valeur marchande totale de toutes les cartes du lot (vendues + collection)")

        if st.button("✨ Créer le lot", type="primary"):
            if not nm:
                st.error("Nom requis")
            else:
                cd=ld()
                nl={
                    "nom": nm,
                    "prix_achat": pa,
                    "cards": [], "ventes": [],
                    "created": datetime.now().isoformat(),
                }
                if is_brocante_new:
                    nl["is_brocante"] = True
                if is_collection_new and valeur_totale_mixte > 0:
                    nl["is_mixte"] = True
                    nl["prix_achat_reel"] = pa
                    nl["valeur_totale"] = valeur_totale_mixte
                if va > 0:
                    nl["ventes"].append({"date":datetime.now().isoformat(),"price":float(va),"card_name":"Vente initiale","is_lot_sale":True})
                cd["lots"].append(nl)
                sd(cd)
                badges = []
                if is_brocante_new: badges.append("🎪 Brocante")
                if is_collection_new: badges.append("🏠 Collection")
                st.success(f"Lot créé ! {' · '.join(badges)}" if badges else "Lot créé !")
                st.rerun()

    st.markdown("---")
    cd=ld()
    if not cd.get("lots"):
        st.info("Aucun lot")
    else:
        def lot_default_sort_key(item):
            ix, lot = item
            if is_trade_lot(lot) or is_storage_lot(lot):
                category = 3
            elif lot.get("is_brocante", False):
                category = 2
            elif lot.get("is_mixte", False):
                category = 1
            else:
                category = 0
            created = lot.get("created") or f"{ix:06d}"
            return (category, created, ix)

        lots_with_idx = sorted(list(enumerate(cd["lots"])), key=lot_default_sort_key)
        completed_lots = [
            lot.get("nom", f"Lot {i+1}")
            for i, lot in lots_with_idx
            if not is_trade_lot(lot)
            and not is_storage_lot(lot)
            and lot.get("cards")
            and lot_remaining_including_storage(cd.get("lots", []), lot) == 0
        ]
        if completed_lots:
            st.success("Lots entièrement vendus, stockage inclus : " + " · ".join(completed_lots) + ". Tu peux les archiver.")

        filter_defs = [
            ("Tous", lambda item: True),
            ("Brocantes", lambda item: item[1].get("is_brocante", False)),
            ("Mixtes", lambda item: item[1].get("is_mixte", False)),
            ("Non remboursés", lambda item: (not is_trade_lot(item[1])) and (not is_storage_lot(item[1])) and cp(item[1]) < 0),
            ("Remboursés", lambda item: (not is_trade_lot(item[1])) and (not is_storage_lot(item[1])) and cp(item[1]) >= 0),
            ("Classiques", lambda item: not item[1].get("is_brocante", False) and not item[1].get("is_mixte", False) and not is_trade_lot(item[1]) and not is_storage_lot(item[1])),
            ("Spécial", lambda item: is_trade_lot(item[1]) or is_storage_lot(item[1])),
        ]

        filter_counts = {name: sum(1 for item in lots_with_idx if predicate(item)) for name, predicate in filter_defs}
        filter_labels = [f"{name} ({filter_counts[name]})" for name, _ in filter_defs]
        selected_filter_label = st.radio(
            "Afficher",
            filter_labels,
            horizontal=True,
            label_visibility="collapsed",
            key="lots_filter_v2",
        )
        selected_filter = selected_filter_label.split(" (", 1)[0]
        selected_predicate = next(predicate for name, predicate in filter_defs if name == selected_filter)
        visible_lots = [item for item in lots_with_idx if selected_predicate(item)]

        if not visible_lots:
            st.info("Aucun lot dans cette catégorie.")

        for display_ix,(ix,lt) in enumerate(visible_lots):
            is_brocante = lt.get("is_brocante", False)
            is_collection = lt.get("is_mixte", False)
            is_trade = is_trade_lot(lt)
            is_storage = is_storage_lot(lt)

            rv=cr(lt)
            pf=cp(lt)
            rp=crp(lt)

            is_profitable = pf >= 0

            if is_storage:
                lot_status = "storage"
            elif is_trade:
                lot_status = "trade"
            elif is_brocante:
                lot_status = "brocante"
            elif is_collection:
                lot_status = "collection"
            elif is_profitable:
                lot_status = "profitable"
            else:
                lot_status = "not-profitable"

            st.session_state[f"lot_status_{ix}"] = lot_status
            color_dot = {"storage":"📈","trade":"🔄","brocante":"🟠","collection":"🔵","profitable":"🟢","not-profitable":"🔴"}.get(lot_status,"🟢")
            # Marker pour colorLotBorders - display_ix suit l'ordre des lots visibles apres filtre.
            st.markdown(f'<div data-lot-index="{ix}" data-display-index="{display_ix}" data-lot-status="{lot_status}" style="display:none"></div>', unsafe_allow_html=True)

            # Badge 🎉 si lot vient d'atteindre 100%
            just_reached_100 = rp >= 100 and is_profitable and not is_brocante and not is_trade
            badge_100 = " 🎉" if just_reached_100 else ""
            badge_mixte = " 🗂️" if lt.get("is_mixte") else ""
            expander_title = f"{color_dot} {'🎪 ' if is_brocante else ''}{lt['nom']} - {fp(lt.get('prix_achat',0))}{badge_mixte}{badge_100}"
            is_active_lot = st.session_state.get("active_lot_ix") == ix
            row_prefix = "▼" if is_active_lot else "›"
            if st.button(
                f"{row_prefix} {expander_title}",
                key=f"lot_row_{ix}",
                use_container_width=True,
                type="secondary",
            ):
                if is_active_lot:
                    st.session_state.pop("active_lot_ix", None)
                else:
                    st.session_state["active_lot_ix"] = ix
                st.rerun()

            if not is_active_lot:
                continue

            with st.container():

                if is_storage:
                    st.markdown('<b style="color:#7c3aed;font-size:1.2rem">📈 LOT STOCKAGE — Cartes mises de côté</b>', unsafe_allow_html=True)
                elif is_trade:
                    st.markdown('<b style="color:#0891b2;font-size:1.2rem">🔄 LOT TRADE — Cartes reçues par échange</b>', unsafe_allow_html=True)
                elif is_brocante:
                    st.markdown('<b style="color:#f97316;font-size:1.2rem">🎪 LOT BROCANTE</b>', unsafe_allow_html=True)
                elif just_reached_100:
                    st.markdown(f'''
                    <div style="background:linear-gradient(135deg,#22c55e,#16a34a);color:white;padding:1rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-size:1.1rem;font-weight:800;text-align:center;">
                        🎉 LOT REMBOURSÉ À {rp:.1f}% — BÉNÉFICE : {fp(pf)}
                    </div>
                    ''', unsafe_allow_html=True)
                else:
                    status_text = "✅ REMBOURSÉ" if is_profitable else "❌ NON REMBOURSÉ"
                    border_color = "#22c55e" if is_profitable else "#ee1515"
                    st.markdown(f'<b style="color:{border_color};font-size:1.2rem">{status_text}</b>',unsafe_allow_html=True)

                # Pour un lot mixte : recalculer le prix_achat effectif dynamiquement
                if lt.get("is_mixte") and lt.get("valeur_totale", 0) > 0:
                    valeur_vente_auto = lot_tracked_cote_value(lt)
                    pa_effectif_auto = (valeur_vente_auto / lt["valeur_totale"]) * lt.get("prix_achat_reel", lt.get("prix_achat", 0.))
                    # Mettre à jour prix_achat si différent
                    if abs(pa_effectif_auto - float(lt.get("prix_achat", 0.))) > 0.01 and pa_effectif_auto > 0:
                        cdd = ld()
                        cdd["lots"][ix]["prix_achat"] = pa_effectif_auto
                        cdd["lots"][ix]["valeur_vente"] = valeur_vente_auto
                        sd(cdd)
                        lt = cdd["lots"][ix]  # recharger le lot mis à jour
                        rv = cr(lt)
                        pf = cp(lt)  # recalculer le bénéfice correctement

                # Calculs corrects — pf recalculé après éventuelle mise à jour mixte
                pf = cp(lt)  # toujours recalculer ici avec le lt à jour
                total_qty = sum(c.get("quantity", 0) for c in lt.get("cards", []))
                stock_qty = sum(card_available_qty(c) for c in lt.get("cards", []))
                stock_val = sum(card_available_qty(c) * c.get("suggested_price", 0.) for c in lt.get("cards", []))
                trade_stock_val = 0. if is_trade else trade_stock_value_for_lot(cd.get("lots", []), ix)
                stock_val += trade_stock_val

                # Valeur estimée = stock actuel (suggested_price corrects) + CA réel
                ca_reel_lot = rv
                valeur_estimee_lot = stock_val + ca_reel_lot

                # % estimé si tout le stock est vendu
                pa = lt.get("prix_achat", 0.)
                rp_estime = ((rv + stock_val) / pa * 100) if pa > 0 else 100.
                rp_estime_color = "#22c55e" if rv + stock_val >= pa else "#ee1515"

                c1,c2,c3,c4,c5=st.columns(5)
                c1.metric("Stock", f"{stock_qty} · {fp(stock_val)}")
                if trade_stock_val > 0:
                    c1.caption(f"part Trade : {fp(trade_stock_val)}")
                c2.metric("Valeur estimée", fp(valeur_estimee_lot))
                c3.metric("CA", fp(rv))
                with c4:
                    rp_color = "#22c55e" if rv + stock_val >= pa else "#ee1515"
                    st.metric("%", f"{rp:.1f}%", delta=f"Si tout vendu : {rp_estime:.0f}%", delta_color="normal" if rv + stock_val >= pa else "inverse")
                    components.html(f'<script>setTimeout(()=>{{const d=parent.document.querySelectorAll(\'[data-testid="stMetricDelta"]\');if(d.length)d[d.length-1].style.backgroundColor="{rp_color}";}},100);</script>', height=0)
                c5.metric("Bénéfice", fp(pf))

                # Info lot mixte
                if lt.get("is_mixte"):
                    valeur_vente_aff = lt.get("valeur_vente", 0.)
                    valeur_totale_aff = lt.get("valeur_totale", 0.)
                    pa_reel_aff = lt.get("prix_achat_reel", lt.get("prix_achat", 0.))
                    pa_eff_aff = lt.get("prix_achat", 0.)
                    pct_vente = (valeur_vente_aff / valeur_totale_aff * 100) if valeur_totale_aff > 0 else 0
                    st.markdown(f"""
                    <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:0.5rem 1rem;margin-bottom:0.5rem;font-size:0.82rem;color:#166534;">
                      🗂️ <b>Lot mixte</b> — Prix réel payé : <b>{fp(pa_reel_aff)}</b> · 
                      Valeur à vendre : <b>{fp(valeur_vente_aff)}</b> / <b>{fp(valeur_totale_aff)}</b> ({pct_vente:.0f}%) · 
                      Coût attribué vente : <b>{fp(pa_eff_aff)}</b>
                      <span style="color:#86efac;font-size:0.75rem;"> ← mis à jour automatiquement</span>
                    </div>
                    """, unsafe_allow_html=True)

                st.markdown("---")

                # ── Formulaire ajout carte ──
                st.markdown(f'<div data-add-card-form-marker="{ix}"></div>', unsafe_allow_html=True)
                st.markdown("**➕ Ajouter une carte**")

                if f"form_ts_{ix}"not in st.session_state:
                    st.session_state[f"form_ts_{ix}"]=time.time()
                ts=st.session_state[f"form_ts_{ix}"]

                is_divers_lot = lt.get("is_divers", False)

                if is_divers_lot:
                    co1,co2,co3,co4,co5=st.columns(5)
                    nm=co1.text_input("Nom",key=f"n{ix}{ts}",placeholder="Dracaufeu")
                    nu=co2.text_input("Numéro",key=f"nu{ix}{ts}",placeholder="004")
                    qt_raw=co3.text_input("Qté",key=f"q{ix}{ts}",placeholder="1")
                    pa_divers_raw=co4.text_input("Prix achat (€)",key=f"pad{ix}{ts}",placeholder="0.00")
                    pi_raw=co5.text_input("Prix vente (€)",key=f"p{ix}{ts}",placeholder="0.00")
                    try: pa_divers = float(pa_divers_raw.replace(",",".")) if pa_divers_raw.strip() else 0.
                    except: pa_divers = 0.
                else:
                    co1,co2,co3,co4=st.columns(4)
                    nm=co1.text_input("Nom",key=f"n{ix}{ts}",placeholder="Dracaufeu")
                    nu=co2.text_input("Numéro",key=f"nu{ix}{ts}",placeholder="004")
                    qt_raw=co3.text_input("Qté",key=f"q{ix}{ts}",placeholder="1")
                    pi_raw=co4.text_input("Prix (€)",key=f"p{ix}{ts}",placeholder="0.00")
                    pa_divers = 0.

                sn=""
                pa_broc=None

                # Conversion sécurisée
                try:
                    qt = int(qt_raw) if qt_raw.strip() else 1
                    qt = max(1, qt)
                except:
                    qt = 1
                try:
                    pi = float(pi_raw.replace(",",".")) if pi_raw.strip() else 0.
                except:
                    pi = 0.

                co8,co9,co10,co11=st.columns(4)
                rv_check=co8.checkbox("Reverse",key=f"r{ix}{ts}")
                ed=co9.checkbox("1ère Éd",key=f"e{ix}{ts}")
                is_jp=co10.checkbox("🇯🇵 Japonaise",key=f"jp{ix}{ts}")
                special_tag=co11.selectbox("Spécial", ["", "Scellé", "Stamp", "Promo", "Master Ball", "Poké Ball"], key=f"sp{ix}{ts}")
                cn="NM"
                
                # Popup multi-choix
                popup_files=glob.glob(f"popup_{ix}_*.json")
                
                for popup_file in popup_files:
                    try:
                        with open(popup_file,"r")as f:
                            popup_data=json.load(f)
                        
                        st.warning(f"⚠️ {len(popup_data['matches'])} résultats trouvés — choisissez la bonne carte :")
                        
                        cols=st.columns(min(len(popup_data["matches"]),4))
                        popup_lang = popup_data.get("lang", "fr")
                        for idx_p,(card_dict,set_name)in enumerate(popup_data["matches"]):
                            with cols[idx_p%4]:
                                # Image du popup
                                img = card_dict.get("image","")
                                if not img:
                                    set_id_p = card_dict.get("set",{}).get("id","") if isinstance(card_dict.get("set"),dict) else ""
                                    local_id_p = card_dict.get("localId","") or card_dict.get("number","")
                                    if set_id_p and local_id_p:
                                        img = f"https://assets.tcgdex.net/{popup_lang}/{set_id_p}/{local_id_p}/high.webp"
                                if img and "tcgdex.net" in img and not any(img.endswith(e) for e in ['.jpg','.png','.jpeg','.webp']):
                                    img = f"{img}/high.webp"
                                if img:
                                    st.markdown(f'<img src="{proxy_img(img)}" style="width:100%;border-radius:8px;">', unsafe_allow_html=True)
                                else:
                                    st.markdown("🃏")
                                    # Bouton Cardmarket si pas d'image (surtout pour JA)
                                    if popup_lang == "ja":
                                        card_name_cm = card_dict.get("name","").replace(" ","_")
                                        set_id_cm = card_dict.get("set",{}).get("id","") if isinstance(card_dict.get("set"),dict) else ""
                                        # URL recherche Cardmarket JA
                                        cm_url = f"https://www.cardmarket.com/fr/Pokemon/Products/Search?searchString={card_dict.get('name','')}"
                                        st.markdown(f'<a href="{cm_url}" target="_blank" style="font-size:0.75rem;color:#3b4cca;text-decoration:none;">🔍 Voir sur Cardmarket</a>', unsafe_allow_html=True)
                                # Afficher le set plutôt que le nom JA
                                display_name = set_name.replace("🇯🇵 ","") if popup_lang == "ja" else card_dict.get('name','')
                                st.caption(f"{display_name}")
                                if st.button(f"Choisir",key=f"choose_{popup_file}_{idx_p}"):
                                    os.remove(popup_file)
                                    pending_vals = list(popup_data["pending"]); pending_vals += [""] * (9 - len(pending_vals)); n,sn,num,q,co,p,ir,ie,special_tag = pending_vals[:9]
                                    popup_lang = popup_data.get("lang", "fr")
                                    name_override = popup_data.get("name_override", "")
                                    pa_carte_popup = popup_data.get("pa_carte", 0.)
                                    cd_add = ld()
                                    nc = ecd(card_dict, set_name, lang=popup_lang)
                                    nc["card_uid"] = new_uid("card")
                                    nc["quantity"] = q if q else 1
                                    nc["condition"] = co
                                    nc["suggested_price"] = p if p else 0.
                                    nc["is_reverse"] = ir
                                    nc["is_ed1"] = ie
                                    if name_override:
                                        nc["name"] = name_override
                                    if lt.get("is_divers") and pa_carte_popup > 0:
                                        nc["purchase_price"] = pa_carte_popup
                                    if special_tag:
                                        nc["special_tag"] = special_tag
                                    cd_add["lots"][ix]["cards"].append(nc)
                                    if lt.get("is_divers"):
                                        cd_add["lots"][ix]["prix_achat"] = sum(c.get("purchase_price",0.) for c in cd_add["lots"][ix]["cards"])
                                    sd(cd_add)
                                    st.session_state[f"lot_expanded_{ix}"]=True
                                    st.session_state[f"form_ts_{ix}"]=time.time()
                                    st.rerun()
                    except Exception as e:
                        try:
                            os.remove(popup_file)
                        except:
                            pass
                
                if st.button("Ajouter",key=f"ad{ix}",disabled=st.session_state.get("searching",False)):
                    st.session_state["searching"]=True
                    final_qt=qt
                    final_pi=pi
                    ok,mg=acm(ix,nm,sn,nu,final_qt,cn,final_pi,rv_check,ed,lang="ja" if is_jp else "fr",purchase_price=pa_divers if is_divers_lot else 0.,special_tag=special_tag)
                    st.session_state["searching"]=False
                    if ok:
                        st.session_state[f"form_ts_{ix}"]=time.time()
                        st.session_state[f"lot_expanded_{ix}"]=True
                        st.success(mg)
                        st.rerun()
                    else:
                        st.error(mg)
                
                st.markdown("---")
                st.markdown("**📦 Cartes du lot**")
                
                # ── Séparer en stock / vendues (ordre d'ajout conservé) ──
                cards_all = lt.get("cards", [])
                lot_card_search = st.text_input(
                    "🔍 Rechercher dans ce lot",
                    placeholder="Nom de carte...",
                    key=f"lot_card_search_{ix}",
                )
                if lot_card_search:
                    cards_all = [
                        c for c in cards_all
                        if normalize_name(lot_card_search) in normalize_name(c.get("name", ""))
                    ]
                # Attacher l'index original à chaque carte pour éviter le bug de mélange
                cards_with_idx = [(i, c) for i, c in enumerate(lt.get("cards", [])) if c in cards_all]
                cards_in_stock_lot = [(i, c) for i, c in cards_with_idx if card_available_qty(c) > 0]
                cards_stored_lot = [(i, c) for i, c in cards_with_idx if card_available_qty(c) <= 0 and int(c.get("stored_quantity", 0)) > 0]
                cards_sold_lot = [(i, c) for i, c in cards_with_idx if card_available_qty(c) <= 0 and int(c.get("stored_quantity", 0)) <= 0]
                show_all_cards = st.checkbox(
                    "Afficher toutes les cartes du lot",
                    key=f"show_all_cards_{ix}",
                    value=False,
                    help="Désactivé par défaut pour accélérer l'ajout quand le lot contient beaucoup de cartes."
                )
                if not show_all_cards:
                    visible_stock_lot = cards_in_stock_lot[-48:]
                    visible_sold_lot = cards_sold_lot[-24:]
                    visible_stored_lot = cards_stored_lot[-24:]
                    hidden_cards_count = max(len(cards_in_stock_lot) - len(visible_stock_lot), 0) + max(len(cards_sold_lot) - len(visible_sold_lot), 0) + max(len(cards_stored_lot) - len(visible_stored_lot), 0)
                    if hidden_cards_count > 0:
                        st.caption(f"Affichage rapide : {hidden_cards_count} ancienne(s) carte(s) masquée(s). Coche la case pour tout afficher.")
                else:
                    visible_stock_lot = cards_in_stock_lot
                    visible_stored_lot = cards_stored_lot
                    visible_sold_lot = cards_sold_lot
                
                def render_card_grid(card_list_with_idx, sold=False):
                    COLS_PER_ROW = 6
                    for row_start in range(0, len(card_list_with_idx), COLS_PER_ROW):
                        cols = st.columns(COLS_PER_ROW)
                        for col_idx, (real_cix, crd) in enumerate(card_list_with_idx[row_start:row_start + COLS_PER_ROW]):
                            stock = card_available_qty(crd)

                            with cols[col_idx]:
                                # Image
                                img_url = crd.get("image_url","")
                                if img_url:
                                    if sold:
                                        st.markdown(f'<div style="opacity:0.35;filter:grayscale(100%)"><img src="{proxy_img(img_url)}" style="width:100%;border-radius:12px;border:3px solid #e2e8f0;"></div>', unsafe_allow_html=True)
                                    else:
                                        st.markdown(f'<img src="{proxy_img(img_url)}" style="width:100%;border-radius:12px;">', unsafe_allow_html=True)
                                else:
                                    # Pas d'image — bouton upload
                                    st.markdown("🃏 *Pas d'image*")
                                    uploaded = st.file_uploader(
                                        "📷 Uploader",
                                        type=["jpg","jpeg","png","webp"],
                                        key=f"upload_{ix}_{real_cix}",
                                        label_visibility="collapsed"
                                    )
                                    if uploaded:
                                        # Sauvegarder dans card_images/
                                        img_dir = os.path.join(os.getcwd(), "card_images")
                                        os.makedirs(img_dir, exist_ok=True)
                                        card_id = crd.get("id","") or f"{ix}_{real_cix}"
                                        safe_id = card_id.replace("/","_").replace(" ","_")
                                        ext = uploaded.name.split(".")[-1]
                                        img_path = os.path.join(img_dir, f"{safe_id}.{ext}")
                                        with open(img_path, "wb") as f:
                                            f.write(uploaded.read())
                                        # Mettre à jour data.json
                                        cdd = ld()
                                        cdd["lots"][ix]["cards"][real_cix]["image_url"] = f"card_images/{safe_id}.{ext}"
                                        sd(cdd)
                                        st.success("✅ Photo ajoutée !")
                                        st.rerun()

                                # Nom + badges + stock sur une ligne
                                badges = ""
                                if crd.get("is_reverse"): badges += ' <span class="badge badge-reverse" style="font-size:0.6rem;padding:0.2rem 0.4rem;">R</span>'
                                if crd.get("is_ed1"):
                                    badges += ' <span class="badge badge-ed1" style="font-size:0.6rem;padding:0.2rem 0.4rem;">1E</span>'
                                if crd.get("special_tag"):
                                    badges += f' <span class="badge" style="background:#0f766e;color:white;font-size:0.6rem;padding:0.2rem 0.4rem;border-radius:6px;">{crd.get("special_tag")}</span>'
                                stock_txt = "✅" if sold else f"{stock}/{crd['quantity']}"
                                if crd.get("stored_quantity", 0):
                                    stock_txt += f" · 📈 {int(crd.get('stored_quantity', 0))}"
                                st.markdown(f'<div style="font-size:0.85rem;font-weight:700;margin:0.2rem 0;">{crd["name"]}{badges} <span style="color:#64748b;font-weight:500;">· {stock_txt}</span></div>', unsafe_allow_html=True)

                                # Prix : pour les cartes vendues, afficher le prix de vente réel
                                if sold and crd.get("sold_entries"):
                                    last_sale = crd["sold_entries"][-1]
                                    prix_reel = float(last_sale.get("price", 0)) / max(int(last_sale.get("quantity",1)), 1)
                                    st.markdown(f'<div style="font-size:0.9rem;font-weight:700;color:#64748b;">Vendu : <span style="color:#10b981;">{prix_reel:.2f}€</span></div>', unsafe_allow_html=True)
                                    # Mettre à jour silencieusement le suggested_price si différent (correction données corrompues)
                                    if abs(float(crd.get("suggested_price", 0)) - prix_reel) > 0.01:
                                        pass  # sera corrigé par le bouton global
                                else:
                                    # Prix modifiable - sauvegarde sur perte de focus (Enter)
                                    def save_price(ix=ix, real_cix=real_cix):
                                        cdd = ld()
                                        new_price = st.session_state[f"ep{ix}_{real_cix}"]
                                        old_price = cdd["lots"][ix]["cards"][real_cix].get("suggested_price", 0.)
                                        cdd["lots"][ix]["cards"][real_cix]["suggested_price"] = new_price
                                        if new_price != old_price:
                                            cdd["lots"][ix]["cards"][real_cix].setdefault("price_history", []).append({
                                                "date": datetime.now().isoformat()[:10],
                                                "price": new_price
                                            })
                                        sd(cdd)

                                    st.number_input("Prix (€)", 0., 9999., value=float(crd.get("suggested_price") or 0), step=0.5, key=f"ep{ix}_{real_cix}", on_change=save_price)

                                    # Historique prix mini
                                    ph = crd.get("price_history", [])
                                    if ph and len(ph) >= 2:
                                        diff = ph[-1]["price"] - ph[-2]["price"]
                                        col_h = "#22c55e" if diff > 0 else "#ee1515"
                                        st.markdown(f'<span style="color:{col_h};font-size:0.72rem;font-weight:700;">{"↑" if diff>0 else "↓"} {fp(abs(diff))}</span>', unsafe_allow_html=True)

                                if not sold:
                                    st.number_input(
                                        "Qté totale",
                                        min_value=int(crd.get("sold_quantity", 0)),
                                        max_value=9999,
                                        value=int(crd.get("quantity", 1)),
                                        step=1,
                                        key=f"qty_edit_{ix}_{real_cix}",
                                        on_change=update_card_quantity,
                                        args=(ix, real_cix),
                                    )
                                    if (not is_storage) and stock > 0:
                                        store_panel_key = f"show_store_{ix}_{real_cix}"
                                        if st.button("📈 Stocker", key=f"store_btn_{ix}_{real_cix}", use_container_width=True):
                                            st.session_state[store_panel_key] = True

                                        if st.session_state.get(store_panel_key, False):
                                            transfer_qty = st.number_input(
                                                "Qté à stocker",
                                                min_value=1,
                                                max_value=int(stock),
                                                value=1,
                                                step=1,
                                                key=f"store_qty_{ix}_{real_cix}",
                                            )
                                            storage_cote = st.number_input(
                                                "Cote stockage (€)",
                                                min_value=0.0,
                                                max_value=99999.0,
                                                value=float(crd.get("suggested_price", 0.) or 0.),
                                                step=0.5,
                                                key=f"store_cote_{ix}_{real_cix}",
                                            )
                                            col_store_ok, col_store_cancel = st.columns(2)
                                            if col_store_ok.button("Valider", key=f"store_confirm_{ix}_{real_cix}", use_container_width=True):
                                                ok, msg = transfer_card_to_storage(ix, real_cix, transfer_qty, storage_cote)
                                                if ok:
                                                    st.session_state[store_panel_key] = False
                                                    st.success(msg)
                                                    st.rerun()
                                                else:
                                                    st.error(msg)
                                            if col_store_cancel.button("Annuler", key=f"store_cancel_{ix}_{real_cix}", use_container_width=True):
                                                st.session_state[store_panel_key] = False
                                                st.rerun()

                                # Checkboxes Reverse / 1ère Éd + bouton modifier image
                                def save_badges(ix=ix, real_cix=real_cix):
                                    cdd = ld()
                                    cdd["lots"][ix]["cards"][real_cix]["is_reverse"] = st.session_state.get(f"erv{ix}_{real_cix}", False)
                                    cdd["lots"][ix]["cards"][real_cix]["is_ed1"] = st.session_state.get(f"eed{ix}_{real_cix}", False)
                                    sd(cdd)

                                col_rv, col_ed, col_img = st.columns([2, 2, 1])
                                col_rv.checkbox("Reverse", value=crd.get("is_reverse", False), key=f"erv{ix}_{real_cix}", on_change=save_badges)
                                col_ed.checkbox("1ère Éd", value=crd.get("is_ed1", False), key=f"eed{ix}_{real_cix}", on_change=save_badges)
                                if col_img.button("🖼️", key=f"edit_img_{ix}_{real_cix}", help="Modifier l'image"):
                                    st.session_state[f"show_upload_{ix}_{real_cix}"] = True

                                if st.session_state.get(f"show_upload_{ix}_{real_cix}", False):
                                    uploaded = st.file_uploader(
                                        "Nouvelle image",
                                        type=["jpg","jpeg","png","webp"],
                                        key=f"reupload_{ix}_{real_cix}",
                                    )
                                    if uploaded:
                                        img_dir = os.path.join(os.getcwd(), "card_images")
                                        os.makedirs(img_dir, exist_ok=True)
                                        card_id = crd.get("id","") or f"{ix}_{real_cix}"
                                        safe_id = card_id.replace("/","_").replace(" ","_")
                                        ext = uploaded.name.split(".")[-1]
                                        img_path = os.path.join(img_dir, f"{safe_id}.{ext}")
                                        with open(img_path, "wb") as f:
                                            f.write(uploaded.read())
                                        cdd = ld()
                                        cdd["lots"][ix]["cards"][real_cix]["image_url"] = f"card_images/{safe_id}.{ext}"
                                        sd(cdd)
                                        st.session_state[f"show_upload_{ix}_{real_cix}"] = False
                                        st.rerun()

                                # Restaurer (cartes vendues)
                                if sold:
                                    if st.button("↩️ Restaurer", key=f"restore_card_{ix}_{real_cix}", use_container_width=True):
                                        cdd = ld()
                                        card_data = cdd["lots"][ix]["cards"][real_cix]
                                        # Retirer la dernière vente
                                        if card_data.get("sold_entries"):
                                            last_entry = card_data["sold_entries"].pop()
                                            qty_restored = last_entry.get("quantity", 1)
                                            card_data["sold_quantity"] = max(0, card_data.get("sold_quantity", 0) - qty_restored)
                                            sale_id = last_entry.get("sale_id")
                                            if sale_id:
                                                for lot_restore in cdd.get("lots", []):
                                                    lot_restore["ventes"] = [
                                                        v for v in lot_restore.get("ventes", [])
                                                        if v.get("source_sale_id") != sale_id
                                                    ]
                                        else:
                                            card_data["sold_quantity"] = max(0, card_data.get("sold_quantity", 0) - 1)
                                        sd(cdd)
                                        st.success("↩️ Vente annulée !")
                                        st.rerun()

                                # Supprimer
                                if st.button("🗑️", key=f"dc{ix}_{real_cix}", use_container_width=True):
                                    ok, er = dc(ix, real_cix)
                                    if ok:
                                        st.rerun()

                        st.markdown("---")
                
                if not cards_all:
                    st.info("Aucune carte dans ce lot")
                else:
                    # ── En stock ──
                    if visible_stock_lot:
                        st.markdown(f"**🟢 En stock ({len(cards_in_stock_lot)})**")
                        render_card_grid(visible_stock_lot, sold=False)

                    if visible_stored_lot:
                        st.markdown(f"**📈 En stockage ({len(cards_stored_lot)})**")
                        render_card_grid(visible_stored_lot, sold=False)
                    
                    # ── Vendues ──
                    if visible_sold_lot:
                        st.markdown(f'<div style="margin-top:1.5rem;padding:1rem;background:#f8fafc;border-radius:12px;border:2px dashed #cbd5e1;"><span style="font-weight:800;color:#64748b;font-size:0.9rem;">✅ VENDUES ({len(cards_sold_lot)})</span></div>', unsafe_allow_html=True)
                        render_card_grid(visible_sold_lot, sold=True)
                
                # Actions lot
                st.markdown("### Actions")

                # ── Bouton correction des prix corrompus ──
                nb_correctable = sum(
                    1 for c in lt.get("cards", [])
                    if c.get("sold_entries") and c.get("sold_quantity", 0) >= c.get("quantity", 1)
                    and c.get("sold_entries")
                    and abs(float(c.get("suggested_price", 0)) - float(c["sold_entries"][-1].get("price", 0)) / max(int(c["sold_entries"][-1].get("quantity", 1)), 1)) > 0.01
                )
                if nb_correctable > 0:
                    st.warning(f"⚠️ {nb_correctable} carte(s) ont un prix suggéré qui ne correspond pas à leur prix de vente réel (données possiblement corrompues par un ancien bug).")
                    if st.button(f"🔄 Corriger les prix ({nb_correctable} cartes)", key=f"fix_prices_{ix}", type="primary"):
                        cdd = ld()
                        nb_fixed = 0
                        for ci, card in enumerate(cdd["lots"][ix]["cards"]):
                            if card.get("sold_entries") and card.get("sold_quantity", 0) >= card.get("quantity", 1):
                                last = card["sold_entries"][-1]
                                prix_reel = float(last.get("price", 0)) / max(int(last.get("quantity", 1)), 1)
                                if abs(float(card.get("suggested_price", 0)) - prix_reel) > 0.01:
                                    cdd["lots"][ix]["cards"][ci]["suggested_price"] = prix_reel
                                    cdd["lots"][ix]["cards"][ci]["suggested_price_at_sale"] = prix_reel
                                    nb_fixed += 1
                        sd(cdd)
                        st.success(f"✅ {nb_fixed} prix corrigés !")
                        st.rerun()

                # Renommage (déclenché par clic sur ✏️ dans le titre)
                if is_trade or is_storage:
                    st.caption("Nom réservé au système.")
                elif st.session_state.get(f"renaming_{ix}", False):
                    new_name = st.text_input("Nouveau nom", value=lt['nom'], key=f"rename_input_{ix}")
                    col_ok, col_cancel = st.columns(2)
                    if col_ok.button("✅ Valider", key=f"rename_ok_{ix}"):
                        cdd = ld()
                        cdd["lots"][ix]["nom"] = new_name
                        sd(cdd)
                        st.session_state[f"renaming_{ix}"] = False
                        st.rerun()
                    if col_cancel.button("❌ Annuler", key=f"rename_cancel_{ix}"):
                        st.session_state[f"renaming_{ix}"] = False
                else:
                    if st.button("✏️", key=f"rename_{ix}", help="Renommer ce lot"):
                        st.session_state[f"renaming_{ix}"] = True
                
                st.markdown("---")
                st.markdown("**Actions**")
                if is_trade:
                    st.info("Le lot Trade est permanent : il sert de coffre central pour les cartes reçues par échange.")
                elif is_storage:
                    st.info("Le lot Stockage est permanent : il sert à mettre de côté les cartes que tu veux garder.")
                else:
                    col_a, col_b = st.columns(2)

                    if col_a.button(f"📦 Archiver", key=f"arch_{ix}", use_container_width=True):
                        st.session_state[f"confirm_arch_{ix}"] = True

                    if col_b.button(f"🗑️ Supprimer", key=f"dl_{ix}", type="secondary", use_container_width=True):
                        st.session_state[f"cd_{ix}"] = True

                if (not is_trade) and st.session_state.get(f"confirm_arch_{ix}", False):
                    st.warning("⚠️ Archiver ce lot ?")
                    ca1, ca2 = st.columns(2)
                    if ca1.button("✅ Oui", key=f"arch_yes_{ix}"):
                        archive_file = "lots_archives.json"
                        archives = []
                        if os.path.exists(archive_file):
                            with open(archive_file, "r", encoding="utf-8") as f:
                                archives = json.load(f)
                        lot_to_archive = cd["lots"][ix].copy()
                        lot_to_archive["archived_date"] = datetime.now().isoformat()
                        archives.append(lot_to_archive)
                        safe_write_json(archive_file, archives, indent=2)
                        cd["lots"].pop(ix)
                        sd(cd)
                        st.session_state[f"confirm_arch_{ix}"] = False
                        st.rerun()
                    if ca2.button("❌ Non", key=f"arch_no_{ix}"):
                        st.session_state[f"confirm_arch_{ix}"] = False

                if (not is_trade) and st.session_state.get(f"cd_{ix}", False):
                    st.warning(f"⚠️ Supprimer définitivement '{lt['nom']}' ? Cette action est irréversible.")
                    cy, cn_btn = st.columns(2)
                    if cy.button("✅ Oui, supprimer", key=f"y_{ix}", type="primary"):
                        cd["lots"].pop(ix)
                        sd(cd)
                        st.session_state[f"cd_{ix}"] = False
                        st.rerun()
                    if cn_btn.button("❌ Non", key=f"n_{ix}"):
                        st.session_state[f"cd_{ix}"] = False
            
            st.markdown('</div>', unsafe_allow_html=True)


# ============================================================
# PAGE HISTORIQUE
# ============================================================
elif st.session_state.current_page=="Historique":
    st.markdown('<h2>📋 Historique des ventes</h2>', unsafe_allow_html=True)

    cd_hist = ld()

    # ── Construire l'historique enrichi avec coût d'achat par carte ──
    hist_enriched = []

    archives_hist = []
    if os.path.exists("lots_archives.json"):
        with open("lots_archives.json","r",encoding="utf-8") as f:
            archives_hist = json.load(f)

    all_lots_hist = cd_hist.get("lots",[])
    for lot_idx_h, lot in enumerate(all_lots_hist + archives_hist):
        prix_lot = float(lot.get("prix_achat", 0.))
        real_idx = lot_idx_h if lot_idx_h < len(all_lots_hist) else None
        ventes_avec_cout, valeur_est_hist = calc_cout_lot(lot, lot_idx=real_idx)

        # Ventes en lot (ventes[])
        for v in lot.get("ventes",[]):
            if v.get("is_lot_sale") or v.get("is_exchange_benefit"):
                continue
            price_v = float(v.get("price",0))
            if lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
                cout_v = (price_v / float(lot.get("valeur_totale", 1.) or 1.)) * float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
            else:
                cout_v = (price_v / (valeur_est_hist or 1.0)) * effective_purchase_price(lot)
            hist_enriched.append({
                "date": v.get("date",""),
                "card_name": v.get("card_name","Vente lot"),
                "card_set": "", "card_number": "",
                "lot_name": lot.get("nom","?"),
                "price": price_v,
                "cout": cout_v,
                "benef": price_v - cout_v,
                "image_url": "",
                "type": "lot",
            })

        # Ventes rapides — coût calculé par calc_cout_lot
        for card, se, cout_total in ventes_avec_cout:
            if se.get("is_exchange"):
                continue
            img = card.get("image_url","") or card.get("image","")
            price = float(se.get("price",0))
            hist_enriched.append({
                "date": se.get("date",""),
                "card_name": se.get("card_name", card.get("name","?")),
                "card_set": se.get("card_set", card.get("set","")),
                "card_number": se.get("card_number", card.get("number","")),
                "lot_name": lot.get("nom","?"),
                "price": price,
                "cout": cout_total,
                "benef": price - cout_total,
                "image_url": img,
                "type": "card",
                "quantity": int(se.get("quantity",1)),
                "canal": se.get("canal",""),
            })

    hist_enriched = sorted(hist_enriched, key=lambda x: x.get("date",""), reverse=True)

    if not hist_enriched:
        st.info("Aucune vente enregistrée.")
    else:
        # ── Filtres ──
        col_search, col_filter, col_sort = st.columns([3, 1, 1])
        search_hist = col_search.text_input("🔍 Rechercher une carte", placeholder="Nom de carte...", key="search_historique")

        # Mois en FR
        MOIS_FR_HIST = {1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
                        7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"}
        def mois_fr_label(m_str):
            try:
                d = datetime.strptime(m_str, "%Y-%m")
                return f"{MOIS_FR_HIST[d.month]} {d.year}"
            except:
                return m_str

        mois_disponibles = sorted({h["date"][:7] for h in hist_enriched if h.get("date")}, reverse=True)
        mois_labels = ["Tous"] + [mois_fr_label(m) for m in mois_disponibles]
        mois_map = {mois_fr_label(m): m for m in mois_disponibles}

        filter_month_label = col_filter.selectbox("Mois", mois_labels)
        filter_month = mois_map.get(filter_month_label, None)

        sort_opt = col_sort.selectbox("Trier par", ["Date (récent)", "Date (ancien)", "Prix (↓)", "Prix (↑)", "Bénéf (↓)", "Bénéf (↑)"])

        filtered = hist_enriched
        if search_hist:
            search_hist_norm = normalize_name(search_hist)
            filtered = [
                h for h in filtered
                if search_hist_norm in normalize_name(str(h.get("card_name", "")))
            ]
        if filter_month:
            filtered = [h for h in filtered if h.get("date","").startswith(filter_month)]

        # Tri
        if sort_opt == "Date (récent)":
            filtered = sorted(filtered, key=lambda h: h.get("date",""), reverse=True)
        elif sort_opt == "Date (ancien)":
            filtered = sorted(filtered, key=lambda h: h.get("date",""))
        elif sort_opt == "Prix (↓)":
            filtered = sorted(filtered, key=lambda h: h.get("price", 0), reverse=True)
        elif sort_opt == "Prix (↑)":
            filtered = sorted(filtered, key=lambda h: h.get("price", 0))
        elif sort_opt == "Bénéf (↓)":
            filtered = sorted(filtered, key=lambda h: h.get("benef", 0), reverse=True)
        elif sort_opt == "Bénéf (↑)":
            filtered = sorted(filtered, key=lambda h: h.get("benef", 0))

        # ── Résumé ──
        total_ca_h = sum(h["price"] for h in filtered)
        total_benef_h = sum(h.get("benef", h["price"]) for h in filtered)
        total_nb_h = sum(int(h.get("quantity", 1)) for h in filtered)

        s1,s2,s3 = st.columns(3)
        s1.metric("🧾 Ventes", str(total_nb_h))
        s2.metric("💰 CA", f"{total_ca_h:.2f}€")
        s3.metric("💎 Bénéfice estimé", f"{total_benef_h:.2f}€")

        current_hist_signature = f"{search_hist}|{filter_month or ''}|{sort_opt}|{len(filtered)}"
        if st.session_state.get("history_signature") != current_hist_signature:
            st.session_state["history_signature"] = current_hist_signature
            st.session_state["history_visible_count"] = 40
        history_visible_count = int(st.session_state.get("history_visible_count", 40))
        visible_history = filtered[:history_visible_count]
        if len(visible_history) < len(filtered):
            st.caption(f"Affichage progressif : {len(visible_history)} vente(s) sur {len(filtered)}.")
        st.markdown("---")

        # ── Lignes de l'historique ──
        for h in visible_history:
            benef = h.get("benef", h["price"])
            cout = h.get("cout", 0.)
            benef_color = "#10b981" if benef >= 0 else "#ef4444"
            date_str = h.get("date","")[:10] if h.get("date") else "—"

            img_col, info_col, prix_col = st.columns([1, 4, 2])

            with img_col:
                img = h.get("image_url","")
                if img:
                    st.markdown(f'<img loading="lazy" src="{proxy_img(img)}" style="width:60px;border-radius:6px;box-shadow:0 2px 6px rgba(0,0,0,0.12);">', unsafe_allow_html=True)
                else:
                    st.markdown('<div style="width:60px;height:84px;background:#f1f5f9;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:1.4rem;">🃏</div>', unsafe_allow_html=True)

            with info_col:
                set_num = f" · {h['card_set']} #{h['card_number']}" if h.get("card_set") else ""
                qty_h = int(h.get("quantity", 1))
                qty_badge = f' <span style="background:#dbeafe;color:#1d4ed8;border-radius:999px;padding:1px 7px;font-size:0.72rem;font-weight:800;">x{qty_h}</span>' if qty_h > 1 else ""
                canal_h = h.get("canal", "")
                canal_icons = {"Main propre":"🤝","Brocante":"🎪","Dexify_TCG":"⚡","Pokédeal":"🎴","Échange":"🔄"}
                canal_badge = f' <span style="background:#f1f5f9;border-radius:6px;padding:1px 6px;font-size:0.72rem;color:#64748b;">{canal_icons.get(canal_h,"📦")} {canal_h}</span>' if canal_h else ""
                st.markdown(f"""
                <div style="padding:0.2rem 0;">
                  <div style="font-weight:700;font-size:0.98rem;color:#1e293b;">{h['card_name']}{qty_badge}{canal_badge}</div>
                  <div style="font-size:0.8rem;color:#64748b;margin-top:2px;">{h['lot_name']}{set_num}</div>
                  <div style="font-size:0.78rem;color:#94a3b8;margin-top:2px;">📅 {date_str}</div>
                </div>
                """, unsafe_allow_html=True)

            with prix_col:
                st.markdown(f"""
                <div style="text-align:right;padding:0.2rem 0;">
                  <div style="font-size:1.1rem;font-weight:800;color:#1e293b;">{h['price']:.2f}€</div>
                  <div style="font-size:0.78rem;color:#94a3b8;">Acheté ~{cout:.2f}€</div>
                  <div style="font-size:0.85rem;font-weight:700;color:{benef_color};">Bénéf : {benef:+.2f}€</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown('<hr style="margin:0.4rem 0;border:none;border-top:1px solid #f1f5f9;">', unsafe_allow_html=True)

        if len(visible_history) < len(filtered):
            st.markdown('<div id="history-load-more-anchor"></div>', unsafe_allow_html=True)
            if st.button("Charger plus d'historique", key="history_load_more", use_container_width=True):
                st.session_state["history_visible_count"] = history_visible_count + 40
                st.rerun()
            components.html("""
            <script>
            (function() {
                const win = parent.window;
                const doc = parent.document;
                if (win.codexHistoryAutoLoadAttached) return;
                win.codexHistoryAutoLoadAttached = true;
                win.addEventListener('scroll', function() {
                    clearTimeout(win.codexHistoryAutoLoadTimer);
                    win.codexHistoryAutoLoadTimer = setTimeout(function() {
                        const anchor = doc.getElementById('history-load-more-anchor');
                        if (!anchor) return;
                        const rect = anchor.getBoundingClientRect();
                        if (rect.top > win.innerHeight + 300) return;
                        const buttons = Array.from(doc.querySelectorAll('button'));
                        const btn = buttons.find(function(b) {
                            return (b.innerText || '').trim() === "Charger plus d'historique";
                        });
                        if (btn && !btn.disabled) btn.click();
                    }, 200);
                }, {passive: true});
            })();
            </script>
            """, height=0)



# ============================================================
# PAGE ARCHIVÉS
# ============================================================
elif st.session_state.current_page=="Archivés":
    st.markdown('<h2>Lots archivés</h2>', unsafe_allow_html=True)
    
    archive_file="lots_archives.json"
    if os.path.exists(archive_file):
        with open(archive_file,"r",encoding="utf-8")as f:
            archives=json.load(f)
        
        if archives:
            st.info(f"📦 {len(archives)} lot(s) archivé(s)")
            
            for ix,lot in enumerate(archives):
                rp_arch = crp(lot)
                pf_arch = cp(lot)
                color = "#22c55e" if pf_arch >= 0 else "#ee1515"
                with st.expander(f"{lot['nom']} - Archivé le {lot.get('archived_date','N/A')[:10]}"):
                    c1,c2,c3,c4=st.columns(4)
                    c1.metric("Prix achat",fp(lot.get("prix_achat",0)))
                    c2.metric("CA",fp(cr(lot)))
                    c3.metric("%",f"{rp_arch:.1f}%")
                    c4.metric("Bénéfice",fp(pf_arch))
                    
                    if st.button(f"Restaurer",key=f"restore_{ix}",type="primary"):
                        restored_lot=archives.pop(ix)
                        del restored_lot["archived_date"]
                        cd=ld()
                        cd["lots"].append(restored_lot)
                        sd(cd)
                        safe_write_json(archive_file, archives, indent=2)
                        st.success("✅ Lot restauré!")
                        st.rerun()
        else:
            st.info("Aucun lot archivé")
    else:
        st.info("Aucun lot archivé")


# ============================================================
# PAGE BROCANTE
# ============================================================
elif st.session_state.current_page=="Brocante":
    st.markdown('<h2>🎪 Brocante</h2>', unsafe_allow_html=True)

    cd = ld()

    # ── S'assurer que le lot Divers existe ──
    divers_lot = next((l for l in cd.get("lots",[]) if l.get("is_divers")), None)
    if divers_lot is None:
        cd["lots"].append({
            "nom": "🗂️ Divers",
            "prix_achat": 0.,
            "cards": [], "ventes": [],
            "created": datetime.now().isoformat(),
            "is_brocante": True,
            "is_divers": True
        })
        sd(cd)
        cd = ld()

    # ── Créer un nouveau lot brocante ──
    st.subheader("➕ Nouveau lot brocante")
    c_broc1, c_broc2 = st.columns(2)
    nm_broc = c_broc1.text_input("Nom du lot", placeholder="Ex: Brocante Vannes Mai 2026", key="new_broc_name2")
    pa_broc2 = c_broc2.number_input("Prix payé (€)", min_value=0., value=0., step=0.5, key="new_broc_pa2")
    col_btn_b, _ = st.columns([1, 9])
    with col_btn_b:
        if st.button("🎪 Créer", type="primary", use_container_width=True, key="create_broc2"):
            if not nm_broc:
                st.error("Nom requis")
            else:
                cd = ld()
                cd["lots"].append({
                    "nom": nm_broc, "prix_achat": pa_broc2,
                    "cards": [], "ventes": [],
                    "created": datetime.now().isoformat(),
                    "is_brocante": True
                })
                sd(cd)
                st.success("Lot brocante créé !")
                st.rerun()

    st.markdown("---")
    cd = ld()

    # ── Afficher d'abord le lot Divers en évidence ──
    broc_lots = [(i, l) for i, l in enumerate(cd.get("lots",[])) if l.get("is_brocante")]
    divers_lots = [(i, l) for i, l in broc_lots if l.get("is_divers")]
    other_broc_lots = [(i, l) for i, l in broc_lots if not l.get("is_divers")]

    def render_broc_lot(ix, lt, is_divers=False):
        rv = cr(lt); pf = cp(lt); rp = crp(lt)
        is_profitable = pf >= 0

        if f"broc_expanded_{ix}" not in st.session_state:
            st.session_state[f"broc_expanded_{ix}"] = False

        dot_broc = "🟣" if is_divers else "🟠"
        title_prefix = "" if is_divers else "🎪 "
        badge = " 🎉" if rp >= 100 and is_profitable else ""
        expander_title = f"{dot_broc} {title_prefix}{lt['nom']} - {fp(lt.get('prix_achat',0))}{badge}"

        with st.expander(expander_title, expanded=st.session_state.get(f"broc_expanded_{ix}", False)):
            if is_divers:
                st.markdown('<b style="color:#8b5cf6;font-size:1.2rem">🗂️ LOT DIVERS — Achats à l\'unité</b>', unsafe_allow_html=True)
            else:
                color = "#22c55e" if is_profitable else "#ee1515"
                status = "✅ REMBOURSÉ" if is_profitable else "❌ NON REMBOURSÉ"
                st.markdown(f'<b style="color:{color};font-size:1.2rem">{status}</b>', unsafe_allow_html=True)

            # Métriques
            total_qty = sum(c.get("quantity",0) for c in lt.get("cards",[]))
            stock_qty = sum(c.get("quantity",0)-c.get("sold_quantity",0) for c in lt.get("cards",[]))
            stock_val = sum((c.get("quantity",0)-c.get("sold_quantity",0))*c.get("suggested_price",0.) for c in lt.get("cards",[]))
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Cartes", total_qty)
            c2.metric("Stock", f"{stock_qty} · {fp(stock_val)}")
            c3.metric("CA", fp(rv))
            c4.metric("%", f"{rp:.1f}%")
            c5.metric("Bénéfice", fp(pf))
            st.markdown("---")

            # Prix payé modifiable
            new_pa = st.number_input("💰 Prix payé pour ce lot (€)", min_value=0., value=float(lt.get("prix_achat",0.)), step=0.5, key=f"broc_pa_{ix}")
            if new_pa != lt.get("prix_achat", 0.):
                cdd = ld(); cdd["lots"][ix]["prix_achat"] = new_pa; sd(cdd); st.rerun()

            # Formulaire ajout carte
            st.markdown("**➕ Ajouter une carte**")
            if f"broc_ts_{ix}" not in st.session_state:
                st.session_state[f"broc_ts_{ix}"] = time.time()
            ts = st.session_state[f"broc_ts_{ix}"]

            if is_divers:
                co1,co2,co3,co4,co5b = st.columns(5)
                nm_c = co1.text_input("Nom", key=f"bn{ix}{ts}", placeholder="Dracaufeu")
                nu_c = co2.text_input("Numéro", key=f"bnu{ix}{ts}", placeholder="004")
                qt_raw_b = co3.text_input("Qté", key=f"bq{ix}{ts}", placeholder="1")
                pa_carte_raw = co4.text_input("Prix achat (€)", key=f"bpa{ix}{ts}", placeholder="0.00")
                pi_raw_b = co5b.text_input("Prix vente (€)", key=f"bp{ix}{ts}", placeholder="0.00")
                try: qt_b = max(1, int(qt_raw_b)) if qt_raw_b.strip() else 1
                except: qt_b = 1
                try: pa_carte = float(pa_carte_raw.replace(",",".")) if pa_carte_raw.strip() else 0.
                except: pa_carte = 0.
                try: pi_b = float(pi_raw_b.replace(",",".")) if pi_raw_b.strip() else 0.
                except: pi_b = 0.
            else:
                co1,co2,co3,co4 = st.columns(4)
                nm_c = co1.text_input("Nom", key=f"bn{ix}{ts}", placeholder="Dracaufeu")
                nu_c = co2.text_input("Numéro", key=f"bnu{ix}{ts}", placeholder="004")
                qt_raw_b = co3.text_input("Qté", key=f"bq{ix}{ts}", placeholder="1")
                pi_raw_b = co4.text_input("Prix vente (€)", key=f"bp{ix}{ts}", placeholder="0.00")
                try: qt_b = max(1, int(qt_raw_b)) if qt_raw_b.strip() else 1
                except: qt_b = 1
                try: pi_b = float(pi_raw_b.replace(",",".")) if pi_raw_b.strip() else 0.
                except: pi_b = 0.
                pa_carte = 0.

            co8, co9 = st.columns(2)
            rv_b = co8.checkbox("Reverse", key=f"brv{ix}{ts}")
            ed_b = co9.checkbox("1ère Éd", key=f"bed{ix}{ts}")

            # Popup multi-choix
            popup_files = glob.glob(f"popup_{ix}_*.json")
            for popup_file in popup_files:
                try:
                    with open(popup_file,"r") as f:
                        popup_data = json.load(f)
                    st.warning(f"⚠️ {len(popup_data['matches'])} résultats — choisissez :")
                    cols_p = st.columns(min(len(popup_data["matches"]),4))
                    for idx_p,(card_dict,set_name) in enumerate(popup_data["matches"]):
                        with cols_p[idx_p%4]:
                            if card_dict.get("image"):
                                img = card_dict["image"]
                                if "tcgdex.net" in img and not any(img.endswith(e) for e in ['.jpg','.png','.jpeg','.webp']):
                                    img = f"{img}/high.webp"
                                st.image(proxy_img(img), width="stretch")
                            st.caption(f"{card_dict.get('name')} ({set_name})")
                            if st.button("Choisir", key=f"bchoose_{popup_file}_{idx_p}"):
                                # Supprimer popup AVANT d'ajouter
                                os.remove(popup_file)
                                n,sn,num,q,co,p,ir,ie = popup_data["pending"]
                                pa_carte_popup = popup_data.get("pa_carte", 0.)
                                cdd = ld()
                                nc = ecd(card_dict, set_name)
                                nc["quantity"] = q if q else 1
                                nc["condition"] = co
                                nc["suggested_price"] = p if p else 0.
                                nc["is_reverse"] = ir
                                nc["is_ed1"] = ie
                                if is_divers and pa_carte_popup > 0:
                                    nc["purchase_price"] = pa_carte_popup
                                cdd["lots"][ix]["cards"].append(nc)
                                if is_divers:
                                    cdd["lots"][ix]["prix_achat"] = sum(c.get("purchase_price",0.) for c in cdd["lots"][ix]["cards"])
                                sd(cdd)
                                st.session_state[f"broc_expanded_{ix}"] = True
                                st.session_state[f"broc_ts_{ix}"] = time.time()
                                st.rerun()
                except:
                    try: os.remove(popup_file)
                    except: pass

            if st.button("Ajouter", key=f"badd{ix}", disabled=st.session_state.get("searching",False)):
                st.session_state["searching"] = True
                ok, mg = acm(ix, nm_c, "", nu_c, qt_b, "NM", pi_b, rv_b, ed_b, purchase_price=pa_carte if is_divers else 0.)
                st.session_state["searching"] = False
                if ok:
                    st.session_state[f"broc_ts_{ix}"] = time.time()
                    st.session_state[f"broc_expanded_{ix}"] = True
                    st.success(mg); st.rerun()
                else:
                    st.error(mg)

            # Grille cartes
            st.markdown("---")
            st.markdown("**📦 Cartes du lot**")
            cards_all_b = lt.get("cards", [])
            cards_stock_b = [(i, c) for i, c in enumerate(cards_all_b) if c['quantity']-c.get('sold_quantity',0) > 0]
            cards_sold_b = [(i, c) for i, c in enumerate(cards_all_b) if c['quantity']-c.get('sold_quantity',0) <= 0]
            show_all_broc_cards = st.checkbox(
                "Afficher toutes les cartes du lot",
                key=f"show_all_broc_cards_{ix}",
                value=False,
                help="Désactivé par défaut pour accélérer l'ajout quand le lot contient beaucoup de cartes."
            )
            if not show_all_broc_cards:
                visible_stock_b = cards_stock_b[-48:]
                visible_sold_b = cards_sold_b[-24:]
                hidden_broc_count = max(len(cards_stock_b) - len(visible_stock_b), 0) + max(len(cards_sold_b) - len(visible_sold_b), 0)
                if hidden_broc_count > 0:
                    st.caption(f"Affichage rapide : {hidden_broc_count} ancienne(s) carte(s) masquée(s). Coche la case pour tout afficher.")
            else:
                visible_stock_b = cards_stock_b
                visible_sold_b = cards_sold_b

            def render_broc_grid(card_list, sold=False):
                COLS = 6
                for row_start in range(0, len(card_list), COLS):
                    cols_g = st.columns(COLS)
                    for col_idx, (real_cix, crd) in enumerate(card_list[row_start:row_start+COLS]):
                        stock = crd['quantity'] - crd.get('sold_quantity',0)
                        with cols_g[col_idx]:
                            if crd.get("image_url"):
                                if sold:
                                    st.markdown(f'<div style="opacity:0.35;filter:grayscale(100%)"><img src="{proxy_img(crd["image_url"])}" style="width:100%;border-radius:12px;"></div>', unsafe_allow_html=True)
                                else:
                                    st.image(proxy_img(crd["image_url"]), width="stretch")
                            else:
                                uploaded_b = st.file_uploader("📷", type=["jpg","jpeg","png","webp"], key=f"bup_{ix}_{real_cix}", label_visibility="collapsed")
                                if uploaded_b:
                                    img_dir = os.path.join(os.getcwd(),"card_images"); os.makedirs(img_dir,exist_ok=True)
                                    safe_id = (crd.get("id","") or f"{ix}_{real_cix}").replace("/","_").replace(" ","_")
                                    ext = uploaded_b.name.split(".")[-1]
                                    with open(os.path.join(img_dir,f"{safe_id}.{ext}"),"wb") as f: f.write(uploaded_b.read())
                                    cdd=ld(); cdd["lots"][ix]["cards"][real_cix]["image_url"]=f"card_images/{safe_id}.{ext}"; sd(cdd); st.rerun()

                            badges=""
                            if crd.get("is_reverse"): badges+=' <span class="badge badge-reverse" style="font-size:0.6rem;padding:0.2rem 0.4rem;">R</span>'
                            if crd.get("is_ed1"): badges+=' <span class="badge badge-ed1" style="font-size:0.6rem;padding:0.2rem 0.4rem;">1E</span>'
                            stock_txt = "✅" if sold else f"{stock}/{crd['quantity']}"
                            st.markdown(f'<div style="font-size:0.85rem;font-weight:700;">{crd["name"]}{badges} <span style="color:#64748b;">· {stock_txt}</span></div>', unsafe_allow_html=True)

                            if is_divers and crd.get("purchase_price"):
                                st.caption(f"🛒 Acheté : {fp(crd['purchase_price'])}")

                            def save_price_b(ix=ix, real_cix=real_cix):
                                cdd=ld(); cdd["lots"][ix]["cards"][real_cix]["suggested_price"]=st.session_state[f"bep{ix}_{real_cix}"]; sd(cdd)
                            st.number_input("Prix (€)",0.,9999.,value=float(crd.get("suggested_price") or 0),step=0.5,key=f"bep{ix}_{real_cix}",on_change=save_price_b)

                            if sold:
                                if st.button("↩️ Restaurer",key=f"brestore_{ix}_{real_cix}",use_container_width=True):
                                    cdd=ld()
                                    card_data=cdd["lots"][ix]["cards"][real_cix]
                                    if card_data.get("sold_entries"):
                                        last=card_data["sold_entries"].pop()
                                        card_data["sold_quantity"]=max(0,card_data.get("sold_quantity",0)-last.get("quantity",1))
                                    else:
                                        card_data["sold_quantity"]=max(0,card_data.get("sold_quantity",0)-1)
                                    sd(cdd); st.rerun()
                            if st.button("🗑️",key=f"bdc{ix}_{real_cix}",use_container_width=True):
                                ok,er=dc(ix,real_cix)
                                if ok: st.rerun()
                    st.markdown("---")

            if visible_stock_b:
                st.markdown(f"**🟢 En stock ({len(cards_stock_b)})**")
                render_broc_grid(visible_stock_b, sold=False)
            if visible_sold_b:
                st.markdown(f'<div style="padding:0.5rem 1rem;background:#f8fafc;border-radius:12px;border:2px dashed #cbd5e1;"><span style="font-weight:800;color:#64748b;">✅ VENDUES ({len(cards_sold_b)})</span></div>', unsafe_allow_html=True)
                render_broc_grid(visible_sold_b, sold=True)

            # Actions
            st.markdown("### Actions")
            if st.session_state.get(f"broc_renaming_{ix}", False):
                new_name_b = st.text_input("Nouveau nom", value=lt['nom'], key=f"broc_rename_input_{ix}")
                col_ok_b, col_cancel_b = st.columns(2)
                if col_ok_b.button("✅ Valider", key=f"broc_rename_ok_{ix}"):
                    cdd=ld(); cdd["lots"][ix]["nom"]=new_name_b; sd(cdd)
                    st.session_state[f"broc_renaming_{ix}"]=False; st.rerun()
                if col_cancel_b.button("❌ Annuler", key=f"broc_rename_cancel_{ix}"):
                    st.session_state[f"broc_renaming_{ix}"]=False
            else:
                if not is_divers:
                    if st.button("✏️ Renommer", key=f"broc_rename_{ix}"):
                        st.session_state[f"broc_renaming_{ix}"] = True

            if not is_divers:
                col_a_b, col_b_b = st.columns(2)
                if col_a_b.button("📦 Archiver", key=f"barch_{ix}"):
                    st.session_state[f"bconfirm_arch_{ix}"] = True
                if st.session_state.get(f"bconfirm_arch_{ix}", False):
                    st.warning("⚠️ Archiver ce lot ?")
                    ba1,ba2=st.columns(2)
                    if ba1.button("✅ Oui",key=f"barch_yes_{ix}"):
                        archive_file="lots_archives.json"; archives=[]
                        if os.path.exists(archive_file):
                            with open(archive_file,"r",encoding="utf-8") as f: archives=json.load(f)
                        lot_arch=cd["lots"][ix].copy(); lot_arch["archived_date"]=datetime.now().isoformat()
                        archives.append(lot_arch)
                        safe_write_json(archive_file, archives, indent=2)
                        cd["lots"].pop(ix); sd(cd)
                        st.session_state[f"bconfirm_arch_{ix}"]=False; st.rerun()
                    if ba2.button("❌ Non",key=f"barch_no_{ix}"):
                        st.session_state[f"bconfirm_arch_{ix}"]=False
                if col_b_b.button("Supprimer lot", key=f"bdl_{ix}", type="secondary"):
                    st.session_state[f"bcd_{ix}"] = True
                if st.session_state.get(f"bcd_{ix}", False):
                    st.warning(f"⚠️ Supprimer '{lt['nom']}' ?")
                    by,bn=st.columns(2)
                    if by.button("✅ Oui",key=f"by_{ix}"):
                        cd["lots"].pop(ix); sd(cd)
                        st.session_state[f"bcd_{ix}"]=False; st.rerun()
                    if bn.button("❌ Non",key=f"bn_{ix}"):
                        st.session_state[f"bcd_{ix}"]=False

    # ── Affichage : Divers en premier, puis les autres lots brocante ──
    if divers_lots:
        st.markdown('<div style="background:linear-gradient(135deg,#8b5cf6,#7c3aed);color:white;padding:0.75rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-weight:800;">🗂️ LOT DIVERS — Toutes vos cartes achetées à l\'unité</div>', unsafe_allow_html=True)
        for ix, lt in divers_lots:
            render_broc_lot(ix, lt, is_divers=True)

    if other_broc_lots:
        st.markdown("---")
        st.markdown("**🎪 Lots brocante**")
        for ix, lt in other_broc_lots:
            render_broc_lot(ix, lt, is_divers=False)

# ============================================================
# PAGE STATISTIQUES
# ============================================================
elif st.session_state.current_page == "Statistiques":
    import plotly.graph_objects as go
    import plotly.express as px
    from collections import defaultdict

    st.markdown("## 📊 Statistiques & Défis")

    cd = ld()
    now = datetime.now()
    current_month = now.strftime("%Y-%m")
    MOIS_FR = {1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
               7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"}
    def mois_label(dt):
        return f"{MOIS_FR[dt.month]} {dt.year}"

    current_month_label = mois_label(now)
    with st.expander("⚙️ Calcul du bénéfice", expanded=False):
        st.caption("Le coût d'achat d'une carte vendue est calculé avec sa cote au moment de la vente, la valeur estimée totale de son lot et le prix d'achat du lot.")
        st.markdown("**Formule :** coût carte = cote carte vendue ÷ valeur estimée du lot × prix d'achat du lot.")
        st.caption("Pour les lots mixtes, la formule utilise directement prix réel payé ÷ valeur totale du lot, afin de ne pas double compter les cartes déjà vendues.")
        st.caption("Le bénéfice utilise ensuite le prix réellement vendu, donc les négociations sont bien prises en compte.")

    # ── Collecter TOUTES les ventes : sold_entries (vente rapide) + ventes[] (vente en lot) ──
    # On exclut les "ventes initiales" créées à la création du lot (is_lot_sale=True)
    all_sales = []
    all_lots = list(cd.get("lots", []))
    archives_list = []
    if os.path.exists("lots_archives.json"):
        with open("lots_archives.json", "r", encoding="utf-8") as f:
            archives_list = json.load(f)

    for lot_idx_s, lot in enumerate(all_lots + archives_list):
        real_lot_idx = lot_idx_s if lot_idx_s < len(all_lots) else None
        ventes_avec_cout, valeur_est = calc_cout_lot(lot, lot_idx=real_lot_idx)

        # Ventes en lot
        for v in lot.get("ventes", []):
            if v.get("is_lot_sale") or v.get("is_exchange_benefit"):
                continue
            try:
                d = datetime.fromisoformat(v["date"])
                price = float(v.get("price", 0))
                qty = int(v.get("quantity", 1))
                if lot.get("is_mixte") and float(lot.get("valeur_totale", 0.) or 0.) > 0:
                    cout_v = (price / float(lot.get("valeur_totale", 1.) or 1.)) * float(lot.get("prix_achat_reel", lot.get("prix_achat", 0.)) or 0.)
                else:
                    cout_v = (price / (valeur_est or 1.0)) * effective_purchase_price(lot)
                all_sales.append({
                    "date": d, "month": d.strftime("%Y-%m"),
                    "price": price, "quantity": qty,
                    "card_name": v.get("card_name", "Vente lot"),
                    "card_image": v.get("card_image", ""),
                    "lot": lot.get("nom", "?"),
                    "unit_price": price / max(qty, 1),
                    "cost": cout_v, "benef": price - cout_v,
                    "cote": price,
                })
            except:
                pass

        # Ventes rapides
        for card, se, cout_total in ventes_avec_cout:
            if se.get("is_exchange"):
                continue
            try:
                d = datetime.fromisoformat(se["date"])
                qty = int(se.get("quantity", 1))
                price = float(se.get("price", 0))
                card_img = card.get("image_url", "") or card.get("image", "")
                cote_total = float(se.get("suggested_price_at_sale", 0.) or card.get("suggested_price", 0.) or 0.) * qty
                if cote_total <= 0:
                    cote_total = price
                all_sales.append({
                    "date": d, "month": d.strftime("%Y-%m"),
                    "price": price, "quantity": qty,
                    "card_name": se.get("card_name", card.get("name", "?")),
                    "card_image": card_img,
                    "lot": lot.get("nom", "?"),
                    "unit_price": price / max(qty, 1),
                    "cost": cout_total,
                    "benef": price - cout_total,
                    "cote": cote_total,
                })
            except:
                pass

    # ── CA, quantités et bénéfice par mois ──
    ca_by_month = defaultdict(float)
    qty_by_month = defaultdict(int)
    benef_by_month = defaultdict(float)

    for s in all_sales:
        ca_by_month[s["month"]] += s["price"]
        qty_by_month[s["month"]] += s["quantity"]
        benef_by_month[s["month"]] += s.get("benef", s["price"] - s.get("cost", 0))

    months_sorted = sorted(ca_by_month.keys())

    if not months_sorted:
        st.info("Aucune vente enregistrée pour le moment. Commence à vendre des cartes pour voir tes statistiques !")
        st.stop()

    import datetime as dt_module
    prev_month = (now.replace(day=1) - dt_module.timedelta(days=1)).strftime("%Y-%m")
    ca_this = ca_by_month.get(current_month, 0)
    ca_prev = ca_by_month.get(prev_month, 0)
    qty_this = qty_by_month.get(current_month, 0)
    qty_prev = qty_by_month.get(prev_month, 0)
    benef_this = benef_by_month.get(current_month, 0)
    benef_prev = benef_by_month.get(prev_month, 0)

    def pct_change(new, old):
        if old == 0:
            return None
        return ((new - old) / old) * 100

    pct_ca = pct_change(ca_this, ca_prev)
    pct_qty = pct_change(qty_this, qty_prev)

    # ─────────────────────────────────────────────
    # SECTION 1 : KPIs du mois courant
    # ─────────────────────────────────────────────
    st.markdown(f"### 📅 {current_month_label}")

    k1, k2, k3, k4 = st.columns(4)

    def delta_str(pct):
        if pct is None: return None
        return f"{'+' if pct >= 0 else ''}{pct:.1f}% vs mois préc."

    k1.metric("💰 CA du mois", f"{ca_this:.2f}€", delta_str(pct_ca))
    k2.metric("🃏 Cartes vendues", str(qty_this), delta_str(pct_qty))

    # Bénéfice du mois (CA × part - coût × part)
    pct_benef = pct_change(benef_this, benef_prev)
    k3.metric("💎 Bénéfice estimé", f"{benef_this:.2f}€", delta_str(pct_benef))

    # Prix moyen par carte
    avg_price = (ca_this / qty_this) if qty_this > 0 else 0
    avg_price_prev = (ca_prev / qty_prev) if qty_prev > 0 else 0
    pct_avg = pct_change(avg_price, avg_price_prev)
    k4.metric("📈 Prix moyen / carte", f"{avg_price:.2f}€", delta_str(pct_avg))

    st.markdown("---")

    # ─────────────────────────────────────────────
    # SECTION 2 : Graphiques
    # ─────────────────────────────────────────────
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.markdown("#### 📊 CA par mois")
        months_labels = [mois_label(datetime.strptime(m, "%Y-%m")) for m in months_sorted]
        ca_values = [ca_by_month[m] for m in months_sorted]
        colors = ["#3b4cca" if m != current_month else "#ffcb05" for m in months_sorted]
        fig_bar = go.Figure(go.Bar(
            x=months_labels, y=ca_values,
            marker_color=colors,
            text=[f"{v:.0f}€" for v in ca_values],
            textposition="outside",
            hovertemplate="%{x}<br>CA : %{y:.2f}€<extra></extra>"
        ))
        fig_bar.update_layout(
            height=300, margin=dict(t=20, b=0, l=0, r=0),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(gridcolor="#f1f5f9", showgrid=True),
            xaxis=dict(showgrid=False),
            showlegend=False,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_g2:
        st.markdown("#### 🃏 Cartes vendues par mois")
        qty_values = [qty_by_month[m] for m in months_sorted]
        fig_qty = go.Figure(go.Bar(
            x=months_labels, y=qty_values,
            marker_color=["#10b981" if m != current_month else "#f59e0b" for m in months_sorted],
            text=[str(v) for v in qty_values],
            textposition="outside",
            hovertemplate="%{x}<br>Cartes : %{y}<extra></extra>"
        ))
        fig_qty.update_layout(
            height=300, margin=dict(t=20, b=0, l=0, r=0),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(gridcolor="#f1f5f9", showgrid=True),
            xaxis=dict(showgrid=False),
            showlegend=False,
        )
        st.plotly_chart(fig_qty, use_container_width=True)

    st.markdown("#### 💎 Bénéfice par mois")
    benef_values = [benef_by_month[m] for m in months_sorted]
    fig_benef_month = go.Figure(go.Bar(
        x=months_labels,
        y=benef_values,
        marker_color=["#10b981" if v >= 0 else "#ef4444" for v in benef_values],
        text=[f"{v:.0f}€" for v in benef_values],
        textposition="outside",
        hovertemplate="%{x}<br>Bénéfice : %{y:.2f}€<extra></extra>",
    ))
    fig_benef_month.update_layout(
        height=280, margin=dict(t=20, b=0, l=0, r=0),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(gridcolor="#f1f5f9", showgrid=True, zeroline=True, zerolinecolor="#cbd5e1"),
        xaxis=dict(showgrid=False),
        showlegend=False,
    )
    st.plotly_chart(fig_benef_month, use_container_width=True)

    with st.expander("🔎 Détail du bénéfice du mois"):
        detail_rows = []
        for s in sorted([x for x in all_sales if x["month"] == current_month], key=lambda x: x["date"], reverse=True):
            detail_rows.append({
                "Date": s["date"].strftime("%d/%m/%Y"),
                "Carte": s.get("card_name", ""),
                "Lot": s.get("lot", ""),
                "Vendu": round(float(s.get("price", 0)), 2),
                "Cote utilisée": round(float(s.get("cote", s.get("price", 0))), 2),
                "Coût estimé": round(float(s.get("cost", 0)), 2),
                "Bénéfice": round(float(s.get("benef", 0)), 2),
            })
        st.dataframe(detail_rows, use_container_width=True, hide_index=True)
        st.caption("Calcul actuel : coût = cote vendue ÷ valeur estimée du lot × prix d'achat du lot. Pour les lots mixtes : coût = cote vendue ÷ valeur totale du lot × prix réel payé.")

    # Graphique tendance CA (courbe lissée)
    if len(months_sorted) >= 2:
        st.markdown("#### 📈 Tendance du CA — évolution mensuelle")
        fig_line = go.Figure()
        fig_line.add_trace(go.Scatter(
            x=months_labels, y=ca_values,
            mode="lines+markers+text",
            line=dict(color="#3b4cca", width=3),
            marker=dict(size=10, color=colors, line=dict(width=2, color="white")),
            text=[f"{v:.0f}€" for v in ca_values],
            textposition="top center",
            fill="tozeroy",
            fillcolor="rgba(59,76,202,0.08)",
            hovertemplate="%{x}<br>CA : %{y:.2f}€<extra></extra>"
        ))
        fig_line.update_layout(
            height=250, margin=dict(t=20, b=0, l=0, r=0),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(gridcolor="#f1f5f9"),
            xaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_line, use_container_width=True)

    # ── CA et bénéfice par lot — mois courant ──
    st.markdown("---")
    pie1, pie2 = st.columns(2)

    ca_by_lot_month = defaultdict(float)
    benef_by_lot_month = defaultdict(float)
    for s in all_sales:
        if s["month"] == current_month:
            ca_by_lot_month[s["lot"]] += s["price"]
            benef_by_lot_month[s["lot"]] += s.get("benef", s["price"] - s.get("cost", 0))

    PALETTE = ["#3b4cca","#ffcb05","#10b981","#f59e0b","#8b5cf6","#ef4444"]

    with pie1:
        st.markdown("#### 🗂️ CA par lot — ce mois")
        top_ca = sorted(ca_by_lot_month.items(), key=lambda x: x[1], reverse=True)[:6]
        if top_ca:
            names_ca, vals_ca = zip(*top_ca)
            fig_ca = go.Figure(go.Pie(
                labels=names_ca, values=vals_ca, hole=0.4,
                marker_colors=PALETTE,
                textinfo="percent+label",
                hovertemplate="%{label}<br>CA : %{value:.2f}€<extra></extra>"
            ))
            fig_ca.update_layout(height=280, margin=dict(t=10,b=0,l=0,r=0),
                                 paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
            st.plotly_chart(fig_ca, use_container_width=True)
        else:
            st.info("Aucune vente ce mois.")

    with pie2:
        st.markdown("#### 💎 Bénéfice par lot — ce mois")
        top_benef = sorted(benef_by_lot_month.items(), key=lambda x: x[1], reverse=True)[:8]
        if top_benef:
            names_b = [t[0] for t in top_benef]
            vals_b = [t[1] for t in top_benef]
            colors_b = ["#10b981" if v >= 0 else "#ef4444" for v in vals_b]
            fig_benef = go.Figure(go.Bar(
                x=vals_b,
                y=names_b,
                orientation="h",
                marker_color=colors_b,
                text=[f"{v:+.1f}€" for v in vals_b],
                textposition="outside",
                hovertemplate="%{y}<br>Bénéfice : %{x:.2f}€<extra></extra>",
            ))
            fig_benef.update_layout(
                height=280, margin=dict(t=10, b=0, l=0, r=60),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=True, gridcolor="#f1f5f9", zeroline=True, zerolinecolor="#cbd5e1", zerolinewidth=2),
                yaxis=dict(showgrid=False),
                showlegend=False,
            )
            st.plotly_chart(fig_benef, use_container_width=True)
        else:
            st.info("Aucune donnée de bénéfice ce mois.")

    # ─────────────────────────────────────────────
    # SECTION 3 : DÉFIS MENSUELS
    # ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🎯 Défis du mois")

    # ── Chargement du fichier objectifs ──
    GOALS_FILE = "monthly_goals.json"
    if os.path.exists(GOALS_FILE):
        with open(GOALS_FILE, "r", encoding="utf-8") as f:
            goals_data = json.load(f)
    else:
        goals_data = {}

    # ── Auto-génération des objectifs si le mois n'en a pas encore ──
    # Logique : on prend les données réelles du mois précédent et on ajoute +15%
    PROGRESSION_RATE = 0.15  # +15% par mois automatiquement
    if current_month not in goals_data:
        prev_ca_real = ca_by_month.get(prev_month, 0)
        prev_qty_real = qty_by_month.get(prev_month, 0)
        prev_avg_real = (prev_ca_real / prev_qty_real) if prev_qty_real > 0 else 0

        if prev_ca_real > 0:
            prev_benef_real = benef_by_month.get(prev_month, 0)
            auto_ca = round(prev_ca_real * (1 + PROGRESSION_RATE), 2)
            auto_qty = max(1, round(prev_qty_real * (1 + PROGRESSION_RATE)))
            auto_benef = round(prev_benef_real * (1 + PROGRESSION_RATE), 2) if prev_benef_real > 0 else round(auto_ca * 0.3, 2)
            goals_data[current_month] = {
                "ca_target": auto_ca,
                "qty_target": auto_qty,
                "benef_target": auto_benef,
                "auto_generated": True,
                "based_on": prev_month,
            }
        else:
            mois_avec_data = [m for m in months_sorted if m < current_month and ca_by_month.get(m, 0) > 0]
            if mois_avec_data:
                ref_month = mois_avec_data[-1]
                ref_ca = ca_by_month.get(ref_month, 100)
                ref_qty = qty_by_month.get(ref_month, 20)
                ref_benef = benef_by_month.get(ref_month, ref_ca * 0.3)
                goals_data[current_month] = {
                    "ca_target": round(ref_ca * (1 + PROGRESSION_RATE), 2),
                    "qty_target": max(1, round(ref_qty * (1 + PROGRESSION_RATE))),
                    "benef_target": round(ref_benef * (1 + PROGRESSION_RATE), 2),
                    "auto_generated": True,
                    "based_on": ref_month,
                }
            else:
                goals_data[current_month] = {"ca_target": 100.0, "qty_target": 20, "benef_target": 30.0, "auto_generated": False}
        safe_write_json(GOALS_FILE, goals_data)

    month_goals = goals_data[current_month]

    # ── Affichage info auto-génération ──
    if month_goals.get("auto_generated"):
        ref = month_goals.get("based_on", "")
        try:
            ref_label = mois_label(datetime.strptime(ref, "%Y-%m"))
        except:
            ref_label = ref
        st.info(f"🤖 Objectifs générés automatiquement (+{int(PROGRESSION_RATE*100)}% par rapport à **{ref_label}**). Tu peux les ajuster ci-dessous.")

    # ── Formulaire modification manuelle ──
    with st.expander("⚙️ Modifier mes objectifs du mois"):
        gc1, gc2, gc3 = st.columns(3)
        new_ca_t = gc1.number_input("🎯 Objectif CA (€)", 0., 99999., value=float(month_goals.get("ca_target", 100.)), step=10.)
        new_qty_t = gc2.number_input("🎯 Cartes à vendre", 0, 9999, value=int(month_goals.get("qty_target", 20)), step=5)
        new_benef_t = gc3.number_input("🎯 Objectif bénéfice (€)", 0., 99999., value=float(month_goals.get("benef_target", 30.)), step=10.)
        if st.button("💾 Sauvegarder les objectifs"):
            goals_data[current_month] = {
                "ca_target": new_ca_t,
                "qty_target": new_qty_t,
                "benef_target": new_benef_t,
                "auto_generated": False,
            }
            safe_write_json(GOALS_FILE, goals_data)
            st.success("✅ Objectifs mis à jour !")
            st.rerun()

    ca_target = month_goals.get("ca_target", 100.)
    qty_target = month_goals.get("qty_target", 20)
    benef_target = month_goals.get("benef_target", ca_target * 0.3)

    def render_challenge(label, current, target, unit="€", icon="🎯", color="#3b4cca", motivation=""):
        pct = min((current / target * 100) if target > 0 else 0, 100)
        done = pct >= 100
        bar_color = "#10b981" if done else color
        emoji = "🏆" if done else icon
        val_fmt = f"{current:.0f}" if unit == "" else f"{current:.2f}"
        tgt_fmt = f"{target:.0f}"
        status = "ACCOMPLI !" if done else f"{val_fmt}{unit} / {tgt_fmt}{unit}"
        remaining = max(0, target - current)
        msg = "✅ Objectif atteint, bravo !" if done else motivation.format(remaining=f"{remaining:.1f}{unit}")

        st.markdown(f"""
        <div style="background:white;border-radius:16px;padding:1.2rem 1.5rem;margin-bottom:1rem;
                    border:2px solid {'#10b981' if done else '#e2e8f0'};
                    box-shadow:{'0 4px 12px rgba(16,185,129,0.15)' if done else '0 2px 8px rgba(0,0,0,0.06)'};">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem;">
            <span style="font-size:1rem;font-weight:700;color:#1e293b;">{emoji} {label}</span>
            <span style="font-size:0.95rem;font-weight:800;color:{bar_color};">{status}</span>
          </div>
          <div style="background:#f1f5f9;border-radius:99px;height:14px;overflow:hidden;">
            <div style="height:100%;width:{pct:.1f}%;background:{'linear-gradient(90deg,#10b981,#34d399)' if done else f'linear-gradient(90deg,{color},{color}cc)'};
                        border-radius:99px;"></div>
          </div>
          <div style="margin-top:0.5rem;font-size:0.82rem;color:{'#10b981' if done else '#64748b'};">{msg}</div>
        </div>
        """, unsafe_allow_html=True)

    render_challenge(
        "Chiffre d'affaires du mois", ca_this, ca_target, "€", "💰", "#3b4cca",
        "Plus que {remaining} à réaliser pour atteindre ton objectif, tu y es presque !"
    )
    render_challenge(
        "Cartes vendues", float(qty_this), float(qty_target), "", "🃏", "#8b5cf6",
        "Il te reste {remaining} cartes à vendre ce mois-ci, allez !"
    )
    render_challenge(
        "Bénéfice du mois", benef_this, benef_target, "€", "💎", "#10b981",
        "Plus que {remaining} de bénéfice à réaliser, continue !"
    )

    # ─────────────────────────────────────────────
    # SECTION 4 : RECORDS & PALMARES
    # ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🏅 Records & Palmarès")

    rec1, rec2, rec3 = st.columns(3)

    # Meilleur mois CA
    best_month = max(ca_by_month, key=ca_by_month.get) if ca_by_month else None
    if best_month:
        bm_label = mois_label(datetime.strptime(best_month, "%Y-%m"))
        rec1.metric("🥇 Meilleur mois (CA)", bm_label, f"{ca_by_month[best_month]:.2f}€")

    # Meilleur mois quantité
    best_qty_month = max(qty_by_month, key=qty_by_month.get) if qty_by_month else None
    if best_qty_month:
        bqm_label = mois_label(datetime.strptime(best_qty_month, "%Y-%m"))
        rec2.metric("🃏 Plus de ventes", bqm_label, f"{qty_by_month[best_qty_month]} cartes")

    # CA total cumulé
    total_ca = sum(ca_by_month.values())
    rec3.metric("💎 CA total cumulé", f"{total_ca:.2f}€", f"{len(all_sales)} ventes au total")

    # ── Carte la plus chère vendue ce mois ──
    sales_this_month = [s for s in all_sales if s["month"] == current_month]
    if sales_this_month:
        best_sale = max(sales_this_month, key=lambda s: s["unit_price"])
        st.markdown("---")
        st.markdown("#### 🌟 Meilleure vente du mois")
        img_col, info_col = st.columns([1, 3])
        with img_col:
            img_url = best_sale.get("card_image", "")
            if img_url:
                st.markdown(f'<img src="{proxy_img(img_url)}" style="width:100%;border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,0.15);">', unsafe_allow_html=True)
            else:
                st.markdown('<div style="width:100%;aspect-ratio:0.71;background:#f1f5f9;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:2rem;">🃏</div>', unsafe_allow_html=True)
        with info_col:
            st.markdown(f"""
            <div style="padding:1rem;">
              <div style="font-size:1.3rem;font-weight:800;color:#1e293b;">{best_sale['card_name']}</div>
              <div style="font-size:0.9rem;color:#64748b;margin-top:0.3rem;">Lot : {best_sale['lot']}</div>
              <div style="font-size:2rem;font-weight:900;color:#3b4cca;margin-top:0.5rem;">{best_sale['unit_price']:.2f}€</div>
              <div style="font-size:0.85rem;color:#94a3b8;">Vendue le {best_sale['date'].strftime('%d/%m/%Y')}</div>
            </div>
            """, unsafe_allow_html=True)

    # Streak : combien de mois consécutifs avec des ventes
    streak = 0
    check_m = now
    for _ in range(24):
        mk = check_m.strftime("%Y-%m")
        if mk in ca_by_month and ca_by_month[mk] > 0:
            streak += 1
            check_m = (check_m.replace(day=1) - dt_module.timedelta(days=1))
        else:
            break

    # Message de motivation dynamique
    if ca_this == 0:
        motivation_msg = "💤 Aucune vente ce mois-ci... C'est le moment de sortir tes meilleures cartes !"
        motivation_color = "#64748b"
    elif pct_ca and pct_ca > 20:
        motivation_msg = f"🚀 En feu ce mois-ci ! +{pct_ca:.0f}% par rapport au mois dernier, continue comme ça !"
        motivation_color = "#10b981"
    elif pct_ca and pct_ca < -20:
        motivation_msg = f"📉 Mois un peu calme... {abs(pct_ca):.0f}% de moins que le mois dernier. Relance la machine !"
        motivation_color = "#f59e0b"
    else:
        motivation_msg = f"👍 Mois régulier — {streak} mois consécutif{'s' if streak > 1 else ''} avec des ventes !"
        motivation_color = "#3b4cca"

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{motivation_color}15,{motivation_color}05);
                border-left:4px solid {motivation_color};border-radius:12px;
                padding:1rem 1.5rem;margin-top:1.5rem;font-size:1.05rem;font-weight:600;color:{motivation_color};">
        {motivation_msg}
    </div>
    """, unsafe_allow_html=True)


# ============================================================
# PAGE COMPTEURS
# ============================================================
elif st.session_state.current_page == "Compteurs":
    import datetime as dt_module

    st.markdown("## 🎰 Compteurs de ventes")
    st.caption("Suivi de tes ventes par canal depuis des dates de référence.")

    COUNTERS_FILE = "counters.json"

    # ── Charger ou initialiser le fichier compteurs ──
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    year_str = str(now.year)

    if os.path.exists(COUNTERS_FILE):
        with open(COUNTERS_FILE, "r", encoding="utf-8") as f:
            counters = json.load(f)
    else:
        counters = {}

    # Structure par défaut
    counters.setdefault("main_brocante", {
        "start_date": today_str,
        "label": "Main propre & Brocante",
        "reset_mode": "manual",
    })
    counters.setdefault("dexify", {
        "year": year_str,
        "start_date": today_str,
        "label": "Dexify_TCG",
        "reset_mode": "manual",
    })
    counters.setdefault("pokedeal", {
        "year": year_str,
        "start_date": today_str,
        "label": "Pokédeal",
        "reset_mode": "manual",
    })
    counters["main_brocante"].setdefault("start_date", today_str)
    counters["dexify"].setdefault("start_date", f"{counters['dexify'].get('year', year_str)}-01-01")
    counters["pokedeal"].setdefault("start_date", f"{counters['pokedeal'].get('year', year_str)}-01-01")

    # ── Calculer les compteurs depuis les ventes réelles ──
    cd = ld()
    all_lots = cd.get("lots", [])
    archives_cnt = []
    if os.path.exists("lots_archives.json"):
        with open("lots_archives.json", "r", encoding="utf-8") as f:
            archives_cnt = json.load(f)

    start_date_mb = counters["main_brocante"]["start_date"]
    dexify_year = counters["dexify"].get("year", year_str)
    pokedeal_year = counters["pokedeal"].get("year", year_str)
    dexify_start_date = counters["dexify"].get("start_date", f"{dexify_year}-01-01")
    pokedeal_start_date = counters["pokedeal"].get("start_date", f"{pokedeal_year}-01-01")
    start_dt_mb = counters["main_brocante"].get("start_datetime", start_date_mb)
    dexify_start_dt = counters["dexify"].get("start_datetime", dexify_start_date)
    pokedeal_start_dt = counters["pokedeal"].get("start_datetime", pokedeal_start_date)

    def sale_after_start(sale_date, start_date, start_datetime):
        sale_date = str(sale_date or "")
        if "T" in str(start_datetime):
            return sale_date >= str(start_datetime)
        return sale_date[:10] >= str(start_date)

    with st.expander("⚙️ Données de départ (à saisir une seule fois)", expanded=True):
        st.caption("Ces valeurs sont ajoutées aux ventes calculées par l'application. Elles sont lues avant l'affichage des compteurs.")
        vi1, vi2, vi3 = st.columns(3)
        mb_init_ca = vi1.number_input("🤝 Main propre & Brocante — CA (€)", 0., 999999., float(counters["main_brocante"].get("init_ca", 0.)), key="counter_mb_init")
        dx_init_ca = vi2.number_input("⚡ Dexify_TCG — CA (€)", 0., 999999., float(counters["dexify"].get("init_ca", 0.)), key="counter_dx_init")
        pk_init_ca = vi3.number_input("🎴 Pokédeal — CA (€)", 0., 999999., float(counters["pokedeal"].get("init_ca", 0.)), key="counter_pk_init")
        if st.button("💾 Sauvegarder les données de départ", type="primary", key="save_counter_inits"):
            counters["main_brocante"]["init_ca"] = float(mb_init_ca)
            counters["dexify"]["init_ca"] = float(dx_init_ca)
            counters["pokedeal"]["init_ca"] = float(pk_init_ca)
            counters["main_brocante"]["start_date"] = today_str
            counters["dexify"]["start_date"] = today_str
            counters["pokedeal"]["start_date"] = today_str
            counters["main_brocante"]["start_datetime"] = now.isoformat()
            counters["dexify"]["start_datetime"] = now.isoformat()
            counters["pokedeal"]["start_datetime"] = now.isoformat()
            counters["dexify"]["year"] = year_str
            counters["pokedeal"]["year"] = year_str
            safe_write_json(COUNTERS_FILE, counters)
            st.success("✅ Valeurs initiales sauvegardées ! Les compteurs repartent d'aujourd'hui.")
            st.rerun()

    init_mb_display = float(mb_init_ca)
    init_dx_display = float(dx_init_ca)
    init_pk_display = float(pk_init_ca)

    # Compteurs calculés
    cnt_main_brocante = {"nb": 0, "ca": 0.}
    cnt_dexify = {"nb": 0, "ca": 0.}
    cnt_pokedeal = {"nb": 0, "ca": 0.}

    for lot in all_lots + archives_cnt:
        for v in lot.get("ventes", []):
            if v.get("is_lot_sale") or v.get("is_exchange_benefit"):
                continue
            canal = canal_key(v.get("canal", ""))
            if not canal:
                continue
            raw_date = v.get("date", "")
            date_str = raw_date[:10]
            price = float(v.get("price", 0))
            if canal in ("main", "brocante"):
                if sale_after_start(raw_date, start_date_mb, start_dt_mb):
                    cnt_main_brocante["ca"] += price
            elif canal == "dexify":
                if sale_after_start(raw_date, dexify_start_date, dexify_start_dt):
                    cnt_dexify["ca"] += price
            elif canal == "pokedeal":
                if sale_after_start(raw_date, pokedeal_start_date, pokedeal_start_dt):
                    cnt_pokedeal["ca"] += price
        for card in lot.get("cards", []):
            for se in card.get("sold_entries", []):
                canal = canal_key(se.get("canal", ""))
                if not canal:
                    continue  # ignorer les ventes sans canal (avant la mise à jour)
                raw_date = se.get("date", "")
                date_str = raw_date[:10]
                price = float(se.get("price", 0))
                qty = int(se.get("quantity", 1))

                if canal in ("main", "brocante"):
                    if sale_after_start(raw_date, start_date_mb, start_dt_mb):
                        cnt_main_brocante["ca"] += price

                elif canal == "dexify":
                    if sale_after_start(raw_date, dexify_start_date, dexify_start_dt):
                        cnt_dexify["ca"] += price

                elif canal == "pokedeal":
                    if sale_after_start(raw_date, pokedeal_start_date, pokedeal_start_dt):
                        cnt_pokedeal["ca"] += price

    # ── Affichage ──
    st.markdown("---")

    # ── Compteur Main propre & Brocante ──
    col_mb, col_dx, col_pk = st.columns(3)

    with col_mb:
        days_since = (now.date() - dt_module.date.fromisoformat(start_date_mb)).days
        total_mb_ca = cnt_main_brocante["ca"] + init_mb_display
        st.markdown(f"""
        <div style="background:white;border-radius:16px;padding:1.5rem;border:2px solid #e2e8f0;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);text-align:center;">
          <div style="font-size:1rem;font-weight:700;color:#64748b;margin-bottom:0.5rem;">🤝 Main propre & Brocante</div>
          <div style="font-size:3rem;font-weight:900;color:#10b981;">{total_mb_ca:.2f}€</div>
          <div style="font-size:0.75rem;color:#94a3b8;margin-top:0.5rem;">Depuis le {dt_module.date.fromisoformat(start_date_mb).strftime('%d/%m/%Y')} ({days_since}j)</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔄 Remettre à zéro", key="reset_mb", use_container_width=True):
            st.session_state["confirm_reset_mb"] = True
        if st.session_state.get("confirm_reset_mb"):
            st.warning("Confirmer la remise à zéro ?")
            r1, r2 = st.columns(2)
            if r1.button("✅ Oui", key="reset_mb_ok"):
                counters["main_brocante"]["start_date"] = today_str
                counters["main_brocante"]["init_ca"] = 0.
                st.session_state["init_mb_ca_input"] = 0.
                safe_write_json(COUNTERS_FILE, counters)
                st.session_state["confirm_reset_mb"] = False
                st.success(f"✅ Compteur remis à zéro depuis aujourd'hui ({today_str})")
                st.rerun()
            if r2.button("❌ Non", key="reset_mb_no"):
                st.session_state["confirm_reset_mb"] = False

    with col_dx:
        total_dx_ca = cnt_dexify["ca"] + init_dx_display
        st.markdown(f"""
        <div style="background:white;border-radius:16px;padding:1.5rem;border:2px solid #e2e8f0;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);text-align:center;">
          <div style="font-size:1rem;font-weight:700;color:#64748b;margin-bottom:0.5rem;">⚡ Dexify_TCG</div>
          <div style="font-size:3rem;font-weight:900;color:#10b981;">{total_dx_ca:.2f}€</div>
          <div style="font-size:0.75rem;color:#94a3b8;margin-top:0.5rem;">Depuis le {dexify_start_date}</div>
        </div>
        """, unsafe_allow_html=True)
        new_year_dx = st.selectbox("Année affichée", [str(y) for y in range(2023, now.year+2)],
                                    index=[str(y) for y in range(2023, now.year+2)].index(dexify_year),
                                    key="sel_year_dx")
        if new_year_dx != dexify_year:
            counters["dexify"]["year"] = new_year_dx
            safe_write_json(COUNTERS_FILE, counters)
            st.rerun()

    with col_pk:
        total_pk_ca = cnt_pokedeal["ca"] + init_pk_display
        st.markdown(f"""
        <div style="background:white;border-radius:16px;padding:1.5rem;border:2px solid #e2e8f0;
                    box-shadow:0 2px 8px rgba(0,0,0,0.06);text-align:center;">
          <div style="font-size:1rem;font-weight:700;color:#64748b;margin-bottom:0.5rem;">🎴 Pokédeal</div>
          <div style="font-size:3rem;font-weight:900;color:#10b981;">{total_pk_ca:.2f}€</div>
          <div style="font-size:0.75rem;color:#94a3b8;margin-top:0.5rem;">Depuis le {pokedeal_start_date}</div>
        </div>
        """, unsafe_allow_html=True)
        new_year_pk = st.selectbox("Année affichée", [str(y) for y in range(2023, now.year+2)],
                                    index=[str(y) for y in range(2023, now.year+2)].index(pokedeal_year),
                                    key="sel_year_pk")
        if new_year_pk != pokedeal_year:
            counters["pokedeal"]["year"] = new_year_pk
            safe_write_json(COUNTERS_FILE, counters)
            st.rerun()

    # ── Récap global ──
    st.markdown("---")
    st.markdown("### 📊 Récapitulatif")
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("🤝 Main propre & Brocante", f"{total_mb_ca:.2f}€")
    rc2.metric("⚡ Dexify_TCG", f"{total_dx_ca:.2f}€")
    rc3.metric("🎴 Pokédeal", f"{total_pk_ca:.2f}€")


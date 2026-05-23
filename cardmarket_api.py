# cardmarket_api.py - Interface API Cardmarket
import requests
from requests_oauthlib import OAuth1
import json
import os

CONFIG_FILE = "config.json"

def load_config():
    """Charge la configuration depuis config.json"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            try: return json.load(f)
            except: return {}
    return {}

def cardmarket_request(endpoint, params=None):
    """
    Fait une requête OAuth1 vers l'API Cardmarket
    
    Args:
        endpoint: str - ex. "/products/find"
        params: dict - paramètres de la requête
    
    Returns:
        (data, error) - tuple avec les données ou l'erreur
    """
    config = load_config()
    mkm = config.get("mkm", {})
    
    app_token = mkm.get("app_token")
    app_secret = mkm.get("app_secret")
    access_token = mkm.get("access_token")
    access_secret = mkm.get("access_secret")
    
    if not all([app_token, app_secret, access_token, access_secret]):
        return None, "❌ Configuration Cardmarket manquante dans config.json"
    
    # URL de base
    base_url = "https://api.cardmarket.com/ws/v2.0/output.json"
    url = base_url.replace("/output.json", "") + endpoint
    
    # OAuth1 authentication
    auth = OAuth1(
        app_token,
        client_secret=app_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_secret,
        signature_method='HMAC-SHA1',
        signature_type='auth_header'
    )
    
    try:
        resp = requests.get(url, params=params, auth=auth, timeout=15)
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.HTTPError as e:
        return None, f"❌ Erreur HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        return None, f"❌ Erreur Cardmarket: {str(e)}"

def search_card(name, set_name=None, language="fr"):
    """
    Recherche une carte sur Cardmarket
    
    Args:
        name: str - nom de la carte
        set_name: str - nom du set (optionnel)
        language: str - langue (défaut: fr)
    
    Returns:
        (results, error) - liste de cartes trouvées ou erreur
    """
    params = {
        "search": name,
        "exact": "false",
        "idGame": "3",  # Pokemon
        "idLanguage": "2" if language == "fr" else "1"  # 1=EN, 2=FR
    }
    
    data, err = cardmarket_request("/products/find", params)
    if err:
        return None, err
    
    products = data.get("product", [])
    if not isinstance(products, list):
        products = [products] if products else []
    
    # Filtrer par set si demandé
    if set_name and products:
        products = [p for p in products if set_name.lower() in (p.get("expansion") or "").lower()]
    
    # Formater les résultats
    results = []
    for p in products[:20]:  # Limite à 20 résultats
        results.append({
            "id": p.get("idProduct"),
            "name": p.get("locName") or p.get("enName"),
            "set": p.get("expansionName") or p.get("expansion"),
            "number": p.get("number"),
            "rarity": p.get("rarity"),
            "image_url": p.get("image"),
            "price_trend": float(p.get("priceGuide", {}).get("TREND", 0)),
            "price_avg": float(p.get("priceGuide", {}).get("AVG7", 0)),
            "price_low": float(p.get("priceGuide", {}).get("LOWPRICE", 0)),
            "cardmarket_url": p.get("website"),
            "full_data": p
        })
    
    return results, None

def get_card_by_id(product_id):
    """
    Récupère les infos d'une carte par son ID Cardmarket
    
    Args:
        product_id: int - ID du produit Cardmarket
    
    Returns:
        (card_info, error)
    """
    data, err = cardmarket_request(f"/products/{product_id}")
    if err:
        return None, err
    
    p = data.get("product", {})
    
    card_info = {
        "id": p.get("idProduct"),
        "name": p.get("locName") or p.get("enName"),
        "set": p.get("expansionName") or p.get("expansion"),
        "number": p.get("number"),
        "rarity": p.get("rarity"),
        "image_url": p.get("image"),
        "price_trend": float(p.get("priceGuide", {}).get("TREND", 0)),
        "price_avg": float(p.get("priceGuide", {}).get("AVG7", 0)),
        "price_low": float(p.get("priceGuide", {}).get("LOWPRICE", 0)),
        "cardmarket_url": p.get("website"),
        "full_data": p
    }
    
    return card_info, None
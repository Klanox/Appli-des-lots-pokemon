"""Recherche d'image de carte TCGdex en arriere-plan (Estimations).

Quand une carte choisie n'a pas d'URL d'image dans l'index local, l'ancien code interrogeait l'API TCGdex pendant le clic
(~400 ms bloquants). Ici l'appel part dans un thread : la carte est ajoutee et sauvegardee tout de suite, et l'URL trouvee est
rattachee a la carte au rendu suivant (voir `_adopt_prefetched_images` dans ui/pages/estimations.py).

Le thread ne touche ni a Streamlit, ni a la session, ni aux fichiers de donnees : il se contente de memoriser une URL.
"""

import threading

try:
    import requests
except Exception:  # pragma: no cover - requests est une dependance de l'application
    requests = None

_LOCK = threading.Lock()
_PENDING = set()
_DONE = {}
_MAX_DONE = 200
_IMAGE_EXTENSIONS = (".jpg", ".png", ".webp")

# Remplacable dans les tests (aucun acces reseau).
_http_get = None


def fetch_tcgdex_image_url(card_id, lang="fr", timeout=3):
    """Meme logique que le bloc « appel API » de ecd() : renvoie l'URL d'image, ou "" si rien n'est trouve."""
    card_id = str(card_id or "").strip()
    if not card_id:
        return ""
    getter = _http_get or (requests.get if requests is not None else None)
    if getter is None:
        return ""
    try:
        for try_lang in ([lang, "en"] if lang != "ja" else ["ja", "en"]):
            response = getter(f"https://api.tcgdex.net/v2/{try_lang}/cards/{card_id}", timeout=timeout)
            if response.status_code == 200:
                image = response.json().get("image", "")
                if image:
                    if not any(image.endswith(ext) for ext in _IMAGE_EXTENSIONS):
                        image = f"{image}/high.webp"
                    return image
    except Exception:
        pass
    return ""


def _worker(card_uid, card_id, lang):
    try:
        url = fetch_tcgdex_image_url(card_id, lang)
    except Exception:
        url = ""
    with _LOCK:
        _PENDING.discard(card_uid)
        if url:
            _DONE[card_uid] = url
            while len(_DONE) > _MAX_DONE:
                _DONE.pop(next(iter(_DONE)))


def start_card_image_lookup(card_uid, card_id, lang="fr"):
    """Lance la recherche en arriere-plan. Renvoie True si un thread a ete demarre (jamais d'exception)."""
    card_uid = str(card_uid or "")
    card_id = str(card_id or "")
    if not card_uid or not card_id:
        return False
    with _LOCK:
        if card_uid in _PENDING or card_uid in _DONE:
            return False
        _PENDING.add(card_uid)
    try:
        threading.Thread(
            target=_worker,
            args=(card_uid, card_id, lang),
            name="card-image-lookup",
            daemon=True,
        ).start()
    except Exception:
        with _LOCK:
            _PENDING.discard(card_uid)
        return False
    return True


def has_results():
    return bool(_DONE)


def pop_ready_image_urls(card_uids):
    """Retire et renvoie {card_uid: url} pour les cartes demandees dont la recherche est terminee."""
    wanted = {str(uid) for uid in (card_uids or []) if uid}
    if not wanted or not _DONE:
        return {}
    with _LOCK:
        ready = {uid: _DONE.pop(uid) for uid in list(_DONE) if uid in wanted}
    return ready

"""Pure card display helpers."""

import html
import os


def collection_placeholder_html(width="100%"):
    return (
        f'<div class="collection-img-placeholder" style="display:flex;align-items:center;'
        f'justify-content:center;aspect-ratio:0.72;width:{html.escape(str(width), quote=True)};'
        f'border-radius:12px;background:#f8fafc;border:2px dashed #cbd5e1;'
        f'color:#64748b;font-weight:800;text-align:center;padding:0.6rem;">'
        f'Image indisponible</div>'
    )


def collection_image_html(
    card,
    width="100%",
    style="border-radius:12px;box-shadow:0 4px 12px rgba(15,23,42,0.18);",
    *,
    proxy_img_func=None,
    cached_image_candidates_func=None,
    session_state=None,
    placeholder_token="__placeholder__",
):
    """Return fast Collection image HTML with local/cache fallbacks only."""
    proxy = proxy_img_func or (lambda value: value)
    state = session_state if session_state is not None else {}
    card_uid = card.get("card_uid") or card.get("id") or str(
        hash(str(card.get("name", "")) + str(card.get("number", "")) + str(card.get("set", "")))
    )
    cache_seed = "|".join(
        str(card.get(key, "") or "")
        for key in (
            "manual_image_path",
            "manual_image_url",
            "resolved_collection_image_url",
            "image_url",
            "image_url_en",
            "local_image",
            "image_path",
            "photo_path",
        )
    )
    cache_key = f"collection_img_html_{card_uid}_{width}_{hash(style)}_{hash(cache_seed)}"
    if cache_key in state:
        return state[cache_key]

    candidates = []

    def add_candidate(url):
        url = str(url or "").strip()
        if not url or url == placeholder_token:
            return
        if url.startswith(("card_images/", "card_images\\")) or os.path.exists(url):
            if not os.path.exists(url):
                return
        if url and url != placeholder_token and url not in candidates:
            candidates.append(url)

    resolved = str(card.get("resolved_collection_image_url", "") or "").strip()
    # Priority: manual local image, manual URL, resolved/cache, stored URLs, then placeholder.
    for key in ("manual_image_path",):
        add_candidate(card.get(key, ""))
    for key in ("manual_image_url",):
        add_candidate(card.get(key, ""))
    for key in ("resolved_collection_image_url",):
        add_candidate(card.get(key, ""))
    for key in ("local_image", "image_path", "photo_path"):
        add_candidate(card.get(key, ""))
    for key in ("image_url", "image_url_en"):
        add_candidate(card.get(key, ""))

    if not candidates and resolved == placeholder_token:
        result = collection_placeholder_html(width)
        state[cache_key] = result
        return result

    if not candidates and cached_image_candidates_func is not None:
        for url in cached_image_candidates_func(card):
            add_candidate(url)

    safe_style = html.escape(style, quote=True)
    placeholder = (
        '<div class="collection-img-placeholder" '
        'style="display:flex;align-items:center;justify-content:center;aspect-ratio:0.72;'
        'width:100%;border-radius:12px;background:#f8fafc;border:2px dashed #cbd5e1;color:#64748b;font-weight:800;">'
        'Image indisponible</div>'
    )
    if not candidates:
        result = collection_placeholder_html(width)
        state[cache_key] = result
        return result

    src = html.escape(proxy(candidates[0]), quote=True)
    fallback_chain = [html.escape(proxy(url), quote=True) for url in candidates[1:]]
    onerror_parts = []
    if fallback_chain:
        js_array = "[" + ",".join("'" + url.replace("'", "\\'") + "'" for url in fallback_chain) + "]"
        onerror_parts.append(
            "this.dataset.fallbackIndex=this.dataset.fallbackIndex||0;"
            f"const f={js_array};"
            "const i=parseInt(this.dataset.fallbackIndex,10);"
            "if(i<f.length){this.dataset.fallbackIndex=i+1;this.src=f[i];return;}"
        )
    safe_placeholder_js = placeholder.replace("\\", "\\\\").replace("'", "\\'")
    onerror_parts.append(f"this.style.display='none';this.parentElement.innerHTML='{safe_placeholder_js}';")
    onerror = html.escape("".join(onerror_parts), quote=True)
    result = (
        f'<div class="collection-img-wrap" style="width:{width};">'
        f'<img src="{src}" onerror="{onerror}" style="width:100%;{safe_style}">'
        f'</div>'
    )
    state[cache_key] = result
    return result


def img_with_fallback(url, url_en="", width="100%", style="border-radius:12px;", proxy_img_func=None):
    """Return an image tag with an English-image fallback if available."""
    proxy = proxy_img_func or (lambda value: value)
    proxied_fr = proxy(url)
    if url_en:
        proxied_en = proxy(url_en)
        return f'<img src="{proxied_fr}" onerror="this.onerror=null;this.src=\'{proxied_en}\';" style="width:{width};{style}">'
    return f'<img src="{proxied_fr}" style="width:{width};{style}">'

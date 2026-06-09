"""Helpers for extracting preview images from Vinted listing pages."""

import html
import json
import re
from urllib.parse import urlparse

import requests
import urllib3


IMAGE_URL_PATTERN = re.compile(
    r"https?://[^\"'\\\s]+(?:vinted|vinted-reserved|images)[^\"'\\\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^\"'\\\s]*)?",
    re.I,
)


def _clean_image_url(value):
    found = html.unescape(str(value or "").strip())
    found = found.replace("\\u002F", "/").replace("\\/", "/")
    if found.startswith("//"):
        found = "https:" + found
    if found.startswith("http://") or found.startswith("https://"):
        return found
    return ""


def _find_image_in_json(payload):
    if isinstance(payload, str):
        return _clean_image_url(payload) if IMAGE_URL_PATTERN.search(payload) else ""
    if isinstance(payload, list):
        for item in payload:
            found = _find_image_in_json(item)
            if found:
                return found
    if isinstance(payload, dict):
        preferred_keys = (
            "image",
            "image_url",
            "photo",
            "thumbnail",
            "thumbnail_url",
            "url",
        )
        for key in preferred_keys:
            if key in payload:
                found = _find_image_in_json(payload.get(key))
                if found:
                    return found
        for value in payload.values():
            found = _find_image_in_json(value)
            if found:
                return found
    return ""


def _find_image_in_html(html_text):
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        r'"photo":\s*\{[^{}]*"url":\s*"([^"]+)"',
        r'"url":\s*"(https?://[^"]+(?:vinted|vinted-reserved|images)[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text or "", re.I)
        if match:
            found = _clean_image_url(match.group(1))
            if found:
                return found

    match = IMAGE_URL_PATTERN.search(html_text or "")
    if match:
        return _clean_image_url(match.group(0))
    return ""


def fetch_listing_preview_image(url):
    """Return the first preview image URL found for a Vinted listing."""
    url = str(url or "").strip()
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    if "vinted." not in host:
        return ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    }

    try:
        try:
            response = requests.get(url, headers=headers, timeout=5)
        except requests.exceptions.SSLError:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.get(url, headers=headers, timeout=5, verify=False)

        if response.status_code >= 400:
            return ""

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            payload = None
        if payload is not None:
            found = _find_image_in_json(payload)
            if found:
                return found

        return _find_image_in_html(response.text)
    except requests.RequestException as exc:
        print(f"Warning: Could not fetch listing preview from {url}: {exc}")
    except Exception as exc:
        print(f"Warning: Could not parse listing preview from {url}: {exc}")
    return ""

"""Vignettes de suggestions (Estimations) : chargement immédiat, priorité haute pour les premières ; cartes suivies inchangées (lazy).

Contrôle sur le HTML produit. Le moment réel du départ des requêtes est mesuré à part dans Chromium.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui.pages import estimations

CARD = {"name": "Évoli", "set": "Base", "number": "55", "rarity": "Commune", "image_url": "https://assets.tcgdex.net/fr/base/base1/55/high.webp"}


def compact_html(**kwargs):
    captured = []
    fake_st = SimpleNamespace(markdown=lambda body, **k: captured.append(body))
    with patch.object(estimations, "st", fake_st):
        estimations._render_compact_suggestion(CARD, language="fr", proxy_img_func=lambda u: u, **kwargs)
    return captured[0]


class SuggestionThumbLoadingTest(unittest.TestCase):
    def test_first_thumbnails_are_eager_with_high_priority(self):
        body = compact_html(high_priority=True)
        self.assertIn('loading="eager"', body)
        self.assertIn('fetchpriority="high"', body)
        self.assertNotIn('loading="lazy"', body)

    def test_other_thumbnails_are_eager_without_priority_hint(self):
        body = compact_html()
        self.assertIn('loading="eager"', body)
        self.assertNotIn("fetchpriority", body)

    def test_thumbnail_url_and_size_rules_unchanged(self):
        body = compact_html(high_priority=True)
        self.assertIn("/low.webp", body)                      # vignette légère tcgdex, jamais l'image haute définition
        self.assertIn('class="est-sugg-thumb"', body)
        self.assertEqual(body.count("<img"), 1)

    def test_tracked_card_images_stay_lazy(self):
        body = estimations._estimation_image_html("https://assets.tcgdex.net/fr/base/base1/55/high.webp", proxy_img_func=lambda u: u)
        self.assertIn('loading="lazy"', body)
        self.assertNotIn("fetchpriority", body)

    def test_invalid_priority_value_is_ignored(self):
        body = estimations._estimation_image_html("https://example.invalid/a.webp", fetch_priority="evil\" onload=\"x", loading="eager")
        self.assertNotIn("fetchpriority", body)
        self.assertNotIn("onload=", body)


if __name__ == "__main__":
    unittest.main()

"""Régression : HTML brut (<em>, </div>) affiché dans les suggestions du formulaire Estimations.

Cause : sans alias, le rendu compact laissait une ligne vide dans son bloc HTML ; Markdown
coupait alors le bloc et affichait la fin en texte brut. Aucun accès aux données réelles.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui.pages import estimations

try:
    from markdown_it import MarkdownIt
except ImportError:  # parseur optionnel : le contrôle de ligne vide reste actif
    MarkdownIt = None

FR_CARD = {"name": "Zénith Suprême", "set": "Zénith Suprême", "number": "GG28", "rarity": "Illustration rare"}
JP_CARD = {"name": "Dracaufeu", "set": "Base", "number": "4", "rarity": "Rare", "lang": "ja", "name_fr": "Dracaufeu FR"}


def rendered_html(card, language="fr"):
    captured = []
    fake_st = SimpleNamespace(markdown=lambda body, **kwargs: captured.append((body, kwargs)))
    with patch.object(estimations, "st", fake_st):
        estimations._render_compact_suggestion(card, language=language)
    assert len(captured) == 1 and captured[0][1].get("unsafe_allow_html") is True
    return captured[0][0]


class EstimationSuggestionHtmlTest(unittest.TestCase):
    def test_html_has_no_blank_line_with_or_without_alias(self):
        # Une ligne vide termine un bloc HTML Markdown : le reste devient du texte brut.
        for card, language in ((FR_CARD, "fr"), (JP_CARD, "ja")):
            body = rendered_html(card, language)
            self.assertFalse(
                any(not line.strip() for line in body.strip().splitlines()),
                f"ligne vide dans le HTML de la suggestion : {body!r}",
            )
            self.assertIn("<em>", body)
            self.assertEqual(body.count("<div"), body.count("</div>"))

    @unittest.skipIf(MarkdownIt is None, "markdown-it-py absent")
    def test_markdown_renders_html_not_a_code_block(self):
        # Même règle que le navigateur : tout doit rester un seul bloc HTML.
        for card, language in ((FR_CARD, "fr"), (JP_CARD, "ja")):
            tokens = MarkdownIt("commonmark", {"html": True}).parse(rendered_html(card, language))
            self.assertEqual([t.type for t in tokens], ["html_block"])


if __name__ == "__main__":
    unittest.main()

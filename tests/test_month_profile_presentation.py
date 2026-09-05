import copy
import html
import unittest
from unittest.mock import patch

from ui.pages.statistics import (
    MONTHLY_PROFILE_EXPLANATIONS,
    _inject_stats_css,
    _profile_help_html,
    _render_stats_v3_timeline,
)


class MonthProfilePresentationTests(unittest.TestCase):
    def test_copy_is_natural_and_specific_for_every_existing_profile(self):
        self.assertEqual(len(MONTHLY_PROFILE_EXPLANATIONS), 12)
        for label, phrase in MONTHLY_PROFILE_EXPLANATIONS.items():
            self.assertFalse(any(char.isdigit() for char in phrase))
            self.assertNotIn('%', phrase)
            self.assertLess(len(phrase), 130)
            markup = _profile_help_html(label)
            self.assertIn(html.escape(phrase), markup)
            self.assertIn('<summary', markup)
            self.assertNotIn('title="', markup)
        self.assertEqual(len(set(MONTHLY_PROFILE_EXPLANATIONS.values())), 12)
        self.assertIn('chiffre d’affaires', MONTHLY_PROFILE_EXPLANATIONS['🏆 Mois record'])
        self.assertIn('acquis', MONTHLY_PROFILE_EXPLANATIONS['🛒 Mois acheteur'])

    def test_cards_keep_values_and_render_full_badge_interpretation_and_current_month(self):
        profiles = list(MONTHLY_PROFILE_EXPLANATIONS.items())
        months = [f'2026-{i + 1:02}' for i in range(len(profiles))]
        stats = {month: {'ca': 255.0, 'benef': 129.9} for month in months}
        original = copy.deepcopy(stats)
        with patch('ui.pages.statistics._month_profile', side_effect=profiles), patch('ui.pages.statistics.st.markdown') as render:
            _render_stats_v3_timeline(stats, months, months[-1])
        markup = render.call_args.args[0]
        self.assertEqual(stats, original)
        self.assertEqual(markup.count('class="ps-stats-month-node'), 12)
        self.assertEqual(markup.count('is-current'), 1)
        self.assertEqual(markup.count('class="interpretation"'), 0)
        self.assertEqual(markup.count('255,00'), 12)
        self.assertEqual(markup.count('129,90'), 12)
        for label, phrase in profiles:
            self.assertIn(html.escape(label), markup)
            self.assertIn(html.escape(phrase), markup)
        self.assertIn('Mars 2026', markup)

    def test_grid_has_four_two_one_columns_without_internal_scroll(self):
        with patch('ui.pages.statistics.st.markdown') as render:
            _inject_stats_css()
        css = render.call_args.args[0]
        self.assertIn('.ps-stats-timeline{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))', css)
        self.assertIn('.ps-stats-timeline{grid-template-columns:repeat(2,minmax(0,1fr))', css)
        self.assertIn('@media (max-width:540px){.ps-stats-timeline{grid-template-columns:minmax(0,1fr)}', css)
        for rule in css.split('}'):
            if '.ps-stats-timeline' in rule or '.ps-stats-month-node' in rule:
                self.assertNotIn('overflow:auto', rule)
                self.assertNotIn('overflow:scroll', rule)


if __name__ == '__main__':
    unittest.main()

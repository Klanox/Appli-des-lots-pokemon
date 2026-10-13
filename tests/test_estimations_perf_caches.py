"""Optimisations de performance d'Estimations : résultats strictement identiques, caches invalidés quand les données changent."""
import os
import tempfile
import unicodedata
import unittest

from ui.pages import estimations

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")


def _old_fold(value):
    text = str(value or "").strip().lower()
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


class FoldTextEquivalenceTest(unittest.TestCase):
    def test_same_result_as_full_normalisation(self):
        samples = ["Marisson", "Évoli ex", "ピカチュウ", "Noeunoeuf #192 151/165", "Écarlate et Violet — Étincelles", "ÀÉÎÕÜ ñ ç ß ı İ", "  Pikachu  ", "", None, 12]
        for sample in samples:
            self.assertEqual(estimations._fold_text(sample), _old_fold(sample), repr(sample))


class KnownSetTagsCacheTest(unittest.TestCase):
    def _expected(self, cards):
        tags = set(estimations._STATIC_SET_TAG_ALIASES)
        for item in cards:
            tags.update(item.get("set_tags") or [])
        return tags

    def test_same_result_and_recomputed_when_index_changes(self):
        cards = [{"set_tags": ["a", "b"]}, {"set_tags": ["c"]}, {}]
        self.assertEqual(estimations._known_set_tags(cards), self._expected(cards))
        self.assertEqual(estimations._known_set_tags(cards), self._expected(cards))
        cards.append({"set_tags": ["nouveau"]})
        self.assertIn("nouveau", estimations._known_set_tags(cards))
        self.assertEqual(estimations._known_set_tags(cards), self._expected(cards))
        other = [{"set_tags": ["zzz"]}]
        self.assertEqual(estimations._known_set_tags(other), self._expected(other))
        self.assertNotIn("zzz", estimations._known_set_tags(cards))

    def test_returned_set_is_a_copy_and_none_still_works(self):
        cards = [{"set_tags": ["a"]}]
        first = estimations._known_set_tags(cards)
        first.add("pollution")
        self.assertNotIn("pollution", estimations._known_set_tags(cards))
        self.assertEqual(estimations._known_set_tags(None), set(estimations._STATIC_SET_TAG_ALIASES))


class DataUriCacheTest(unittest.TestCase):
    def test_same_data_uri_and_invalidated_when_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "carte.png")
            with open(path, "wb") as f:
                f.write(PNG)
            first = estimations._image_file_to_data_uri(path)
            self.assertEqual(first, estimations._image_file_to_data_uri_uncached(path))
            self.assertEqual(first, estimations._image_file_to_data_uri(path))
            with open(path, "wb") as f:
                f.write(PNG + b"\x00\x00")
            second = estimations._image_file_to_data_uri(path)
            self.assertNotEqual(first, second)
            self.assertEqual(second, estimations._image_file_to_data_uri_uncached(path))
            os.remove(path)
            self.assertEqual(estimations._image_file_to_data_uri(path), "")


if __name__ == "__main__":
    unittest.main()

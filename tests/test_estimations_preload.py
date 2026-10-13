"""Préchargement en arrière-plan de l'index de recherche : même index que la construction normale, repli silencieux en cas d'échec."""
import unittest
from unittest import mock

from ui.pages import estimations

CARD = {"id": "xy-1", "name": "Marisson", "number": "1", "rarity": "Rare"}


def cards_index():
    return {"marisson": [(dict(CARD), "XY", "xy")]}


class PreloadTest(unittest.TestCase):
    def setUp(self):
        estimations._reset_estimation_search_memory_cache()
        self.addCleanup(estimations._reset_estimation_search_memory_cache)

    def test_background_build_gives_same_index_and_foreground_reuses_it(self):
        norm = lambda v: str(v or "").strip().lower()
        with mock.patch("services.card_cache_service.load_cards_cache_from_disk", return_value=cards_index()):
            estimations._preload_estimations_worker(0)
        preloaded = estimations._ESTIMATION_SEARCH_INDEX
        self.assertEqual(len(preloaded), 1)
        self.assertEqual(estimations._ESTIMATION_SEARCH_INDEX_SOURCE_ID, estimations._search_index_source_id(cards_index()))
        self.assertIs(estimations._build_search_index(cards_index(), norm), preloaded)      # la page relit l'index prêt, sans le reconstruire
        estimations._reset_estimation_search_memory_cache()
        rebuilt = estimations._build_search_index(cards_index(), norm)                      # construction normale (sans préchargement)
        self.assertEqual([(i["card"]["id"], i["search_text"], i["set_tags"]) for i in preloaded],
                         [(i["card"]["id"], i["search_text"], i["set_tags"]) for i in rebuilt])

    def test_failure_is_silent_and_start_happens_once(self):
        with mock.patch("services.card_cache_service.load_cards_cache_from_disk", side_effect=RuntimeError("cache illisible")):
            estimations._preload_estimations_worker(0)                                      # ne lève rien : l'appli fonctionnera comme avant
        self.assertEqual(estimations._ESTIMATION_SEARCH_INDEX, [])
        with mock.patch.dict(estimations._PRELOAD_STATE, {"started": False}), mock.patch.object(estimations.threading, "Thread") as thread:
            self.assertTrue(estimations.preload_estimations_in_background())
            self.assertFalse(estimations.preload_estimations_in_background())
            thread.assert_called_once()


if __name__ == "__main__":
    unittest.main()

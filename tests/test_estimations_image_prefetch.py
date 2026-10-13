"""Après « Choisir » : le téléchargement de l'image ne bloque plus le clic — données temporaires, aucun réseau.

Le thread ne fait que télécharger (fonction remplacée par un faux) ; le chemin est rattaché à la carte plus tard, dans le script principal.
"""
import os
import tempfile
import threading
import unittest
from unittest import mock

from ui.pages import estimations

DETAILS = {"image_url": "https://assets.tcgdex.net/fr/base/base1/55/high.webp", "name": "Évoli", "number": "55"}


def new_estimate():
    return {"cards": [{"uid": "c1", "name": "Évoli", "number": "55", "id": "base1-55"}]}


class ImagePrefetchTest(unittest.TestCase):
    def setUp(self):
        estimations._IMAGE_PREFETCH_DONE.clear()
        self.addCleanup(estimations._IMAGE_PREFETCH_DONE.clear)
        self.tmp = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.old_cwd)

    def make_file(self, rel="images/estimation_cache/base1-55.webp"):
        os.makedirs(os.path.dirname(rel), exist_ok=True)
        with open(rel, "wb") as f:
            f.write(b"x" * 600)
        return rel

    def test_click_path_does_not_wait_for_the_download(self):
        release = threading.Event()
        started = threading.Event()
        rel = self.make_file()

        def slow_download(card, sources):
            started.set()
            release.wait(5)
            return rel

        estimate = new_estimate()
        with mock.patch.object(estimations, "_download_estimation_image", slow_download):
            estimations._apply_selected_card_details(estimate, DETAILS)       # rend la main sans attendre le « réseau »
            self.assertNotIn("cached_image_path", estimate["cards"][-1])
            self.assertTrue(started.wait(2))
            release.set()
            for thread in threading.enumerate():
                if thread.name == "estimation-image-prefetch":
                    thread.join(5)
        self.assertEqual(estimate["cards"][-1].get("cached_image_path", ""), "")       # le thread n'a PAS touché aux données
        self.assertEqual(estimations._IMAGE_PREFETCH_DONE, {"c1": rel})

    def test_adoption_attaches_path_once_and_saves_once(self):
        rel = self.make_file()
        estimations._IMAGE_PREFETCH_DONE["c1"] = rel
        estimate, saves = new_estimate(), []
        self.assertTrue(estimations._adopt_prefetched_images(estimate, {"e": 1}, lambda data: saves.append(data)))
        self.assertEqual(estimate["cards"][0]["cached_image_path"], rel)
        self.assertEqual(len(saves), 1)
        self.assertFalse(estimations._adopt_prefetched_images(estimate, {"e": 1}, lambda data: saves.append(data)))
        self.assertEqual(len(saves), 1)                                    # rien de nouveau : aucune écriture

    def test_adoption_never_overrides_an_existing_or_manual_image_and_ignores_missing_file(self):
        rel = self.make_file()
        saves = []
        for existing in ({"manual_image_path": "images/manual/x.png"}, {"cached_image_path": "images/estimation_cache/old.webp"}):
            estimations._IMAGE_PREFETCH_DONE["c1"] = rel
            estimate = new_estimate()
            estimate["cards"][0].update(existing)
            before = dict(estimate["cards"][0])
            self.assertFalse(estimations._adopt_prefetched_images(estimate, {}, lambda data: saves.append(data)))
            self.assertEqual(estimate["cards"][0], before)
        estimations._IMAGE_PREFETCH_DONE["c1"] = "images/estimation_cache/does-not-exist.webp"
        estimate = new_estimate()
        self.assertFalse(estimations._adopt_prefetched_images(estimate, {}, lambda data: saves.append(data)))
        self.assertNotIn("cached_image_path", estimate["cards"][0])
        self.assertEqual(saves, [])

    def test_failed_download_is_silent_and_adopts_nothing(self):
        estimate = new_estimate()
        with mock.patch.object(estimations, "_download_estimation_image", mock.Mock(side_effect=OSError("réseau coupé"))):
            estimations._apply_selected_card_details(estimate, DETAILS)
            for thread in threading.enumerate():
                if thread.name == "estimation-image-prefetch":
                    thread.join(5)
        self.assertEqual(estimations._IMAGE_PREFETCH_DONE, {})
        self.assertFalse(estimations._adopt_prefetched_images(estimate, {}, lambda data: self.fail("aucune sauvegarde attendue")))

    def test_card_without_uid_keeps_the_synchronous_behavior(self):
        rel = self.make_file()
        estimate = {"cards": [{"name": "Évoli", "number": "55", "id": "base1-55"}]}
        with mock.patch.object(estimations, "_download_estimation_image", lambda card, sources: rel):
            estimations._apply_selected_card_details(estimate, DETAILS)
        self.assertEqual(estimate["cards"][0]["cached_image_path"], rel)

    def test_prefetch_can_be_disabled(self):
        rel = self.make_file()
        estimate = new_estimate()
        with mock.patch.object(estimations, "_IMAGE_PREFETCH_ENABLED", False), mock.patch.object(estimations, "_download_estimation_image", lambda card, sources: rel):
            estimations._apply_selected_card_details(estimate, DETAILS)
        self.assertEqual(estimate["cards"][0]["cached_image_path"], rel)


if __name__ == "__main__":
    unittest.main()

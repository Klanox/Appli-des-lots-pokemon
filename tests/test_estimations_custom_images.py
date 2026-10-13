"""Images personnalisées (custom_card_images.json) dans Estimations : copie temporaire, jamais le vrai fichier."""
import json
import os
import tempfile
import unittest
from unittest import mock

from services import custom_card_image_service as svc
from ui.pages import estimations

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")
OFFICIAL = "https://assets.tcgdex.net/fr/svp/svp/208/high.webp"


class CustomImageResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.img = os.path.join(self.tmp.name, "svp-208.png")
        with open(self.img, "wb") as f:
            f.write(PNG)
        self.registry = os.path.join(self.tmp.name, "custom_card_images.json")
        # ancienne entrée « lots_upload » : sans drapeau override_official, comme dans la vraie base
        with open(self.registry, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 1, "images": {"id:svp-208": {"set": "SVP Black Star Promos", "number": "208", "source": "lots_upload",
                       "card_name": "Victini", "image_ref": self.img, "local_image_ref": self.img}}}, f)
        real = svc.resolve_custom_card_image
        patches = [
            mock.patch.object(estimations, "resolve_custom_card_image", lambda card, **k: real(card, path=self.registry)),
            mock.patch.object(estimations, "CUSTOM_CARD_IMAGES_FILE", self.registry),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        estimations._ESTIMATION_IMAGE_RESOLUTION_CACHE.clear()
        estimations._ESTIMATION_SUGGESTION_IMAGE_CACHE.clear()
        self.addCleanup(estimations._ESTIMATION_IMAGE_RESOLUTION_CACHE.clear)
        self.addCleanup(estimations._ESTIMATION_SUGGESTION_IMAGE_CACHE.clear)

    tracked = {"name": "Victini", "number": "208", "set": "SVP Black Star Promos", "id": "svp-208", "card_id": "svp-208", "image_url": OFFICIAL, "lang": "fr"}
    suggestion = {"id": "svp-208", "localId": "208", "name": "Victini", "number": "208", "set": "SVP Black Star Promos", "lang": "fr"}

    def test_tracked_card_uses_custom_image_before_official_url(self):
        info = estimations._resolve_estimation_card_image(dict(self.tracked), log=False)
        self.assertEqual(info["source"], "custom_library")
        self.assertEqual(info["url"], self.img)

    def test_upload_made_on_the_estimation_card_wins_over_registry(self):
        manual = os.path.join(self.tmp.name, "manuel.png")
        with open(manual, "wb") as f:
            f.write(PNG)
        info = estimations._resolve_estimation_card_image({**self.tracked, "manual_image_path": manual}, log=False)
        self.assertEqual(info["source"], "manual_image_path")
        self.assertEqual(info["url"], manual)

    def test_suggestion_uses_custom_image_first_and_html_embeds_it(self):
        info = estimations._suggestion_image_info(dict(self.suggestion))
        self.assertEqual(info["url"], self.img)
        self.assertTrue(any("tcgdex" in u for u in info["fallbacks"]))
        html = estimations._estimation_image_html(info["url"], "", fallbacks=info["fallbacks"], placeholder_class="est-sugg-thumb-ph")
        self.assertIn("data:image/png;base64,", html)

    def test_without_custom_entry_behaviour_is_unchanged(self):
        other_t = {**self.tracked, "id": "svp-999", "card_id": "svp-999", "number": "999"}
        other_s = {**self.suggestion, "id": "svp-999", "localId": "999", "number": "999"}
        self.assertEqual(estimations._resolve_estimation_card_image(other_t, log=False)["url"], OFFICIAL)
        self.assertIn("assets.tcgdex.net", estimations._suggestion_image_info(other_s)["url"])

    def test_registry_file_is_not_modified_by_resolution(self):
        before = open(self.registry, "rb").read()
        estimations._resolve_estimation_card_image(dict(self.tracked), log=False)
        estimations._suggestion_image_info(dict(self.suggestion))
        self.assertEqual(open(self.registry, "rb").read(), before)


if __name__ == "__main__":
    unittest.main()

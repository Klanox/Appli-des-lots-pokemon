from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

from services import photo_recognition_service as recognition
from services.photo_upload_service import ordered_manifest_entries, receive_upload_batch


def _jpeg(seed: int) -> bytes:
    output = BytesIO()
    Image.new("RGB", (24, 16), (seed % 255, (seed * 7) % 255, (seed * 13) % 255)).save(
        output,
        format="JPEG",
        quality=88,
    )
    return output.getvalue()


def _entry(index: int, *, name: str | None = None, batch_index=0, seed: int | None = None):
    import hashlib

    raw = _jpeg(index if seed is None else seed)
    return {
        "client_id": f"client-{index}-{seed}",
        "hash": hashlib.sha256(raw).hexdigest(),
        "original_index": index,
        "original_filename": name or f"IMG_{index:04d}.png",
        "batch_index": batch_index,
        "selected_at": "2026-09-05T12:00:00",
        "data_base64": base64.b64encode(raw).decode("ascii"),
    }


class UploadedBytes(BytesIO):
    def __init__(self, name: str, payload: bytes):
        super().__init__(payload)
        self.name = name
        self.size = len(payload)


class BrowserPhotoUploadTests(unittest.TestCase):
    def test_ten_photos_keep_exact_manifest_order(self):
        with TemporaryDirectory() as directory:
            result = receive_upload_batch(
                directory,
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-1",
                entries=[_entry(index) for index in range(10)],
            )
            self.assertEqual(result["manifest"]["count"], 10)
            manifest = recognition.manifest_from_folder(Path(result["folder"]))
            self.assertEqual([row["original_index"] for row in manifest["photos"]], list(range(10)))

    def test_successive_selections_append_in_global_order(self):
        with TemporaryDirectory() as directory:
            first = receive_upload_batch(
                directory,
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-1",
                entries=[_entry(index, batch_index=0) for index in range(6)],
            )
            second = receive_upload_batch(
                directory,
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-2",
                entries=[_entry(index, batch_index=1) for index in range(6, 10)],
            )
            manifest = recognition.manifest_from_folder(Path(second["folder"]))
            self.assertEqual(first["manifest"]["count"], 6)
            self.assertEqual([row["batch_index"] for row in manifest["photos"]], [0] * 6 + [1] * 4)

    def test_duplicate_hash_is_idempotent(self):
        with TemporaryDirectory() as directory:
            entry = _entry(0)
            receive_upload_batch(
                directory,
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-1",
                entries=[entry],
            )
            duplicate = {**entry, "client_id": "duplicate", "original_index": 1}
            result = receive_upload_batch(
                directory,
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-2",
                entries=[duplicate],
            )
            self.assertEqual(result["manifest"]["count"], 1)
            self.assertEqual(result["acknowledgements"][0]["status"], "already_received")

    def test_resume_only_adds_missing_photos(self):
        with TemporaryDirectory() as directory:
            existing = [_entry(index) for index in range(3)]
            receive_upload_batch(
                directory,
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-1",
                entries=existing,
            )
            result = receive_upload_batch(
                directory,
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-2",
                entries=[{**existing[1], "client_id": "resent"}, _entry(3)],
            )
            self.assertEqual(result["manifest"]["count"], 4)
            self.assertEqual(
                [row["status"] for row in result["acknowledgements"]],
                ["already_received", "received"],
            )

    def test_filename_collision_does_not_overwrite(self):
        with TemporaryDirectory() as directory:
            result = receive_upload_batch(
                directory,
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-1",
                entries=[_entry(0, name="IMG_0001.jpg", seed=1), _entry(1, name="IMG_0001.jpg", seed=2)],
            )
            manifest = recognition.manifest_from_folder(Path(result["folder"]))
            self.assertEqual(result["manifest"]["count"], 2)
            self.assertEqual({row["original_filename"] for row in manifest["photos"]}, {"IMG_0001.jpg"})
            self.assertEqual(len({row["stored_filename"] for row in manifest["photos"]}), 2)

    def test_bad_entry_does_not_block_rest_of_batch(self):
        with TemporaryDirectory() as directory:
            bad = {**_entry(0), "data_base64": "not-base64"}
            result = receive_upload_batch(
                directory,
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-1",
                entries=[bad, _entry(1)],
            )
            self.assertEqual([row["status"] for row in result["acknowledgements"]], ["error", "received"])
            self.assertEqual(result["manifest"]["count"], 1)

    def test_manifest_with_1200_rows_sorts_without_filesystem_order(self):
        rows = [
            {"original_index": index, "hash": f"{index:064x}", "original_filename": f"photo-{index}.jpg"}
            for index in reversed(range(1200))
        ]
        ordered = ordered_manifest_entries({"photos": rows})
        self.assertEqual(len(ordered), 1200)
        self.assertEqual([row["original_index"] for row in ordered], list(range(1200)))

    def test_recognition_facade_receives_manifest_sequence(self):
        with TemporaryDirectory() as directory, patch.object(recognition, "PRODUCTION_CACHE_DIR", Path(directory)):
            first = recognition.receive_browser_upload_batch(
                drop_id="drop-test",
                upload_session_id="upload-test",
                batch_id="batch-1",
                entries=[_entry(0, name="z-last-name.jpg"), _entry(1, name="a-first-name.jpg")],
            )
            captured = {}

            def fake_analyze_sample(**kwargs):
                captured["photos"] = kwargs["ordered_photos"]
                return {"analysis_meta": {"folder": kwargs["folder"]}, "groups": [], "sample_photos": []}

            with patch.object(recognition, "analyze_sample", side_effect=fake_analyze_sample), patch.object(
                recognition, "initialize_drop_photo_session", return_value={}
            ), patch.object(recognition, "reconcile_poc_validations", return_value=({}, {})):
                recognition.analyze_drop_photos(first["folder"], "drop-test")

            self.assertEqual([photo.original_filename for photo in captured["photos"]], ["z-last-name.jpg", "a-first-name.jpg"])
            self.assertEqual([photo.original_index for photo in captured["photos"]], [0, 1])
            self.assertEqual([photo.capture_index for photo in captured["photos"]], [1, 2])

    def test_legacy_folder_upload_remains_available(self):
        with TemporaryDirectory() as directory, patch.object(recognition, "PRODUCTION_CACHE_DIR", Path(directory)):
            folder = recognition.persist_uploaded_photos(
                "drop-test",
                [UploadedBytes("photo-a.jpg", _jpeg(1)), UploadedBytes("photo-b.jpg", _jpeg(2))],
            )
            self.assertEqual(len(recognition.list_ordered_photos(folder)), 2)

    def test_launched_drop_blocks_new_browser_import(self):
        self.assertTrue(recognition.browser_photo_upload_allowed({"id": "drop-new", "drop_launched_at": None}))
        self.assertFalse(
            recognition.browser_photo_upload_allowed(
                {"id": "drop-live", "drop_launched_at": "2026-08-27T17:27:35"}
            )
        )


if __name__ == "__main__":
    unittest.main()

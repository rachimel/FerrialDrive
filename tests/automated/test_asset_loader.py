"""공통 에셋 등록·공유 수명·실패 시 보존·디버그 갱신 계약."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ferrial_drive.assets import AssetCatalog, AssetDefinition, AssetManager, detect_kind
from ferrial_drive.assets.catalog import read_document
from samples.asset_loader.make_sample import write_samples


class FakeResource:
    def __init__(self, document):
        self.payload = b"".join(p.read_bytes() for p in document.dependencies)
        self.estimated_bytes = len(self.payload)
        self.closed = 0

    def close(self):
        self.closed += 1


class FakeBackend:
    def __init__(self):
        self.resources = []
        self.after_load = None

    def load(self, document):
        if document.definition.source.read_bytes() == b"broken":
            raise ValueError("손상된 이미지")
        resource = FakeResource(document)
        self.resources.append(resource)
        if self.after_load:
            self.after_load(document)
        return resource


class AssetLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fdrive-assets-")
        self.root = write_samples(self.temporary.name)
        self.backend = FakeBackend()
        self.catalog = AssetCatalog.load(self.root / "catalog.json")
        self.managers = []

    def tearDown(self):
        for manager in self.managers:
            manager.close()
        self.temporary.cleanup()

    def manager(self, **options):
        manager = AssetManager(self.catalog, self.backend, **options)
        self.managers.append(manager)
        return manager

    def change(self, name, data):
        path = self.root / name
        before = path.stat().st_mtime_ns
        path.write_bytes(data)
        os.utime(path, ns=(before + 1000000, before + 1000000))

    def test_catalog_roundtrip_is_relative_and_independent_of_working_directory(self):
        target = self.root / "export/catalog.json"
        self.catalog.save(target)
        self.assertEqual(json.loads(target.read_text())["assets"][0]["source"], "../image.png")
        previous = Path.cwd()
        try:
            os.chdir(self.root / "export")
            loaded = AssetCatalog.load(target)
            self.assertEqual(loaded.definitions["sample_image"].source, self.root / "image.png")
        finally:
            os.chdir(previous)

    def test_duplicate_registration_and_invalid_catalog_are_rejected(self):
        with self.assertRaises(ValueError):
            self.catalog.add(self.catalog.definitions["sample_image"])
        for value in ("", "contains space", "../escape"):
            with self.assertRaises(ValueError):
                AssetDefinition(value, "image", self.root / "image.png")
        self.change("catalog.json", b'{"version":99,"assets":[]}')
        with self.assertRaises(ValueError):
            AssetCatalog.load(self.root / "catalog.json")

    def test_kind_detection_and_existing_sheet_bundle_formats(self):
        for name, kind, dependency_count in (("image.png", "image", 1), ("body.json", "sheet", 2), ("bundle.json", "bundle", 5)):
            self.assertEqual(detect_kind(self.root / name), kind)
            document = read_document(AssetDefinition("asset", kind, self.root / name))
            self.assertEqual(len(document.dependencies), dependency_count)

    def test_same_id_shares_resource_and_last_handle_releases_it(self):
        manager = self.manager()
        first, second = manager.acquire("sample_image"), manager.acquire("sample_image")
        resource = first.resource
        self.assertIs(resource, second.resource)
        self.assertEqual(manager.snapshot()["sample_image"]["references"], 2)
        first.close()
        first.close()
        self.assertEqual(resource.closed, 0)
        second.close()
        self.assertEqual(resource.closed, 1)
        with self.assertRaises(RuntimeError):
            _ = second.resource

    def test_debug_off_never_polls_files_even_with_force(self):
        manager = self.manager()
        handle = manager.acquire("sample_image")
        with patch("ferrial_drive.assets.manager.fingerprint", side_effect=AssertionError("unexpected stat")):
            self.assertEqual(manager.poll_reload(force=True), [])
        self.assertEqual(handle.generation, 1)

    def test_successful_hot_reload_updates_existing_shared_handles(self):
        manager = self.manager(debug=True)
        first, second = manager.acquire("sample_image"), manager.acquire("sample_image")
        previous = first.resource
        self.change("image.png", b"new image")
        self.assertTrue(manager.poll_reload(now=1)[0].success)
        self.assertIs(first.resource, second.resource)
        self.assertIsNot(first.resource, previous)
        self.assertEqual(previous.closed, 1)
        self.assertEqual(first.generation, 2)

    def test_failed_reload_keeps_last_good_resource_and_recovers(self):
        manager = self.manager(debug=True)
        handle = manager.acquire("sample_image")
        previous = handle.resource
        self.change("image.png", b"broken")
        self.assertFalse(manager.poll_reload(now=1)[0].success)
        self.assertIs(handle.resource, previous)
        self.assertEqual(previous.closed, 0)
        self.change("image.png", b"fixed")
        self.assertTrue(manager.poll_reload(now=2)[0].success)
        self.assertEqual(previous.closed, 1)

    def test_sheet_image_dependency_change_is_detected(self):
        manager = self.manager(debug=True)
        handle = manager.acquire("sample_sheet")
        self.change("body.png", b"changed pixels")
        self.assertTrue(manager.poll_reload(now=1)[0].success)
        self.assertEqual(handle.generation, 2)

    def test_invalid_metadata_and_missing_dependency_preserve_previous(self):
        manager = self.manager(debug=True)
        handle = manager.acquire("sample_sheet")
        previous = handle.resource
        original = (self.root / "body.json").read_bytes()
        self.change("body.json", b"{")
        self.assertFalse(manager.poll_reload(now=1)[0].success)
        self.assertIs(handle.resource, previous)
        self.change("body.json", original)
        (self.root / "body.png").unlink()
        self.assertFalse(manager.poll_reload(now=2)[0].success)
        self.assertIs(handle.resource, previous)
        (self.root / "body.png").write_bytes(b"restored")
        self.assertTrue(manager.poll_reload(now=3)[0].success)

    def test_wrong_metadata_root_is_reported_without_destroying_previous(self):
        manager = self.manager(debug=True)
        handle = manager.acquire("sample_sheet")
        previous = handle.resource
        self.change("body.json", b"[]")
        self.assertFalse(manager.poll_reload(now=1)[0].success)
        self.assertIs(handle.resource, previous)

    def test_catalog_source_change_swaps_only_after_success(self):
        manager = self.manager(debug=True)
        handle = manager.acquire("sample_image")
        old = handle.resource
        data = json.loads((self.root / "catalog.json").read_text())
        data["assets"][0]["source"] = "replacement.png"
        self.change("catalog.json", json.dumps(data).encode())
        self.assertFalse(manager.poll_reload(now=1)[0].success)
        self.assertIs(handle.resource, old)
        (self.root / "replacement.png").write_bytes(b"replacement")
        self.assertTrue(manager.poll_reload(now=2)[0].success)
        self.assertEqual(old.closed, 1)

    def test_invalid_catalog_does_not_destroy_registered_resources(self):
        manager = self.manager(debug=True)
        handle = manager.acquire("sample_image")
        old = handle.resource
        self.change("catalog.json", b"{")
        self.assertFalse(manager.poll_reload(now=1)[0].success)
        self.assertIs(handle.resource, old)
        self.assertIn("sample_image", manager.catalog.definitions)

    def test_removed_registration_keeps_live_handle_but_rejects_new_acquire(self):
        manager = self.manager(debug=True)
        handle = manager.acquire("sample_image")
        old = handle.resource
        self.change("catalog.json", b'{"version":1,"assets":[]}')
        manager.poll_reload(now=1)
        with self.assertRaises(KeyError):
            manager.acquire("sample_image")
        self.assertIs(handle.resource, old)
        handle.close()
        self.assertEqual(old.closed, 1)

    def test_source_changed_during_load_disposes_candidate_without_swapping(self):
        manager = self.manager(debug=True)
        handle = manager.acquire("sample_image")
        old = handle.resource
        self.change("image.png", b"new")
        self.backend.after_load = lambda document: self.change("image.png", b"changed during loading")
        self.assertFalse(manager.poll_reload(now=1)[0].success)
        self.assertIs(handle.resource, old)
        self.assertEqual(self.backend.resources[-1].closed, 1)

    def test_poll_interval_and_manager_shutdown(self):
        manager = self.manager(debug=True, poll_interval=1)
        handle = manager.acquire("sample_image")
        manager.poll_reload(now=1)
        self.change("image.png", b"new")
        self.assertEqual(manager.poll_reload(now=1.5), [])
        self.assertTrue(manager.poll_reload(now=2)[0].success)
        resource = handle.resource
        manager.close()
        handle.close()
        manager.close()
        self.assertEqual(resource.closed, 1)

    def test_optional_timing_recorder_collects_only_when_connected(self):
        from ferrial_drive.diagnostics import TimingRecorder
        recorder = TimingRecorder(enabled=True, session="asset-test")
        manager = self.manager(timings=recorder)
        manager.acquire("sample_image").close()
        names = {row["name"] for row in recorder.snapshot()["measurements"]}
        self.assertEqual(names, {"assets.metadata", "assets.texture_load"})


if __name__ == "__main__":
    unittest.main()

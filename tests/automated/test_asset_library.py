"""data/catalog 초기화·등록 목록 보존·에셋 종속 파일의 로컬 보관을 검사한다."""

import json
from pathlib import Path
import tempfile
import unittest

from ferrial_drive.assets import AssetCatalog, AssetDefinition, SpriteBundle
from samples.asset_loader.make_sample import write_samples
from Tools.asset_loader.library import prepare_library, store_asset


class AssetLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="asset-library-")
        self.root = Path(self.temporary.name)
        self.source = write_samples(self.root / "public_sample")
        self.library = self.root / "data/catalog"

    def tearDown(self):
        self.temporary.cleanup()

    def test_sample_copy_and_catalog_references_stay_inside_library(self):
        catalog = prepare_library(self.library, sample_source=self.source)
        self.assertEqual(set(catalog.definitions), {"sample_image", "sample_sheet", "sample_mech"})
        self.assertTrue((self.library / "prerender").is_dir())
        for definition in catalog.definitions.values():
            self.assertIn(self.library, definition.source.parents)
        self.assertEqual(SpriteBundle.load(catalog.definitions["sample_mech"].source).asset_id, "sample_mech")
        document = json.loads((self.library / "catalog.json").read_text())
        self.assertTrue(all(row["source"].startswith("samples/asset_loader/") for row in document["assets"]))

    def test_reinitializing_does_not_overwrite_user_catalog_or_sample_edits(self):
        catalog = prepare_library(self.library, sample_source=self.source)
        catalog.add(AssetDefinition("added", "image", self.source / "image.png"))
        catalog.save()
        sample = self.library / "samples/asset_loader/image.png"
        sample.write_bytes(b"local edit")
        before = (self.library / "catalog.json").read_bytes()
        prepare_library(self.library, sample_source=self.source)
        self.assertEqual((self.library / "catalog.json").read_bytes(), before)
        self.assertEqual(sample.read_bytes(), b"local edit")

    def test_bundle_import_copies_layers_and_uses_relative_internal_paths(self):
        definition = AssetDefinition("imported", "bundle", self.source / "bundle.json")
        stored = store_asset(definition, root=self.library)
        self.assertEqual(stored.kind, "bundle")
        self.assertIn(self.library / "prerender/imported", stored.source.parents)
        self.assertEqual(SpriteBundle.load(stored.source).asset_id, "imported")
        self.assertEqual((stored.source.parent / "body.png").read_bytes(), (self.source / "body.png").read_bytes())
        self.assertEqual(store_asset(stored, root=self.library), stored)
        self.assertEqual(len(list((self.library / "prerender/imported").iterdir())), 1)

    def test_image_and_sheet_import_preserve_asset_kind(self):
        for kind, filename in (("image", "image.png"), ("sheet", "body.json")):
            with self.subTest(kind=kind):
                stored = store_asset(AssetDefinition(kind, kind, self.source / filename), root=self.library)
                self.assertEqual(stored.kind, kind)
                self.assertTrue(stored.source.is_file())
                self.assertIn(self.library / "prerender", stored.source.parents)

    def test_internal_metadata_with_external_image_is_copied_with_dependency(self):
        self.library.mkdir(parents=True)
        data = json.loads((self.source / "body.json").read_text())
        data["image"]["path"] = str(self.source / "body.png")
        source = self.library / "external_sheet.json"
        source.write_text(json.dumps(data))
        stored = store_asset(AssetDefinition("mixed", "sheet", source), root=self.library)
        self.assertNotEqual(stored.source, source)
        self.assertTrue((stored.source.parent / "body.png").is_file())
        self.assertEqual(json.loads(stored.source.read_text())["image"]["path"], "body.png")


if __name__ == "__main__":
    unittest.main()

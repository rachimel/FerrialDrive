"""SDL dummy에서 실제 이미지 검증·자원 교체·등록·툴 화면을 확인한다."""

import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from ferrial_drive.assets import AssetCatalog, AssetManager
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from samples.asset_loader.make_sample import write_png, write_samples


class PicoAssetLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pico2d.pico2d as pico
        cls.pico = pico
        pico.open_canvas(1280, 800)
        if not pico.renderer:
            pico.renderer = pico.SDL_CreateRenderer(pico.window, -1, pico.SDL_RENDERER_SOFTWARE)
        if not pico.renderer:
            raise RuntimeError("SDL dummy 렌더러 생성 실패")

    @classmethod
    def tearDownClass(cls):
        cls.pico.close_canvas()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fdrive-pico-assets-")
        self.root = write_samples(self.temporary.name)
        self.catalog = AssetCatalog.load(self.root / "catalog.json")
        self.manager = AssetManager(self.catalog, PicoAssetBackend(), debug=True)

    def tearDown(self):
        self.manager.close()
        self.temporary.cleanup()

    def test_actual_image_sheet_bundle_load_and_draw(self):
        for asset_id in ("sample_image", "sample_sheet", "sample_mech"):
            with self.manager.acquire(asset_id) as handle:
                resource = handle.resource
                self.assertGreater(resource.estimated_bytes, 0)
                name = next(iter(resource.clips))
                resource.draw(name, 0, 100, 100)
                resource.draw(name, 0, 100, 100, body=False, shadow=True)
        self.assertEqual(self.manager.snapshot(), {})

    def test_default_library_registration_imports_asset_and_keeps_catalog_local(self):
        from unittest.mock import patch
        from Tools.asset_loader.app import AssetLoaderApp
        from Tools.asset_loader.library import prepare_library, store_asset
        library = self.root / "library"
        prepare_library(library, sample_source=self.root)
        catalog_path = library / "catalog.json"
        app = AssetLoaderApp(source=self.root / "bundle.json", catalog=catalog_path)
        def initialize():
            return prepare_library(library, sample_source=self.root)
        def store(definition, **options):
            return store_asset(definition, root=library, **options)
        with patch("Tools.asset_loader.app.DEFAULT_CATALOG", catalog_path), \
             patch("Tools.asset_loader.app.prepare_library", side_effect=initialize), \
             patch("Tools.asset_loader.app.store_asset", side_effect=store):
            try:
                app.enter()
                app.asset_id = "registered_mech"
                app.register()
                definition = AssetCatalog.load(catalog_path).definitions["registered_mech"]
                self.assertIn(library / "prerender", definition.source.parents)
                self.assertEqual(app.source, definition.source)
                self.assertEqual(len(app.catalog.definitions), 4)
            finally:
                app.exit()

    def test_assembled_bundle_opens_its_selected_default_animation(self):
        from Tools.asset_loader.assembly import SpriteAssembly
        from Tools.asset_loader.app import AssetLoaderApp
        assembly = SpriteAssembly(self.catalog.definitions["sample_mech"])
        assembly.apply("idle/e", "attack", [1, 0], 12, None)
        path = assembly.save(self.root / "assembled", asset_id="assembled")
        app = AssetLoaderApp(source=path, catalog=self.root / "catalog.json")
        try:
            app.enter()
            self.assertFalse(app.error)
            self.assertEqual(app.clip_name, "attack/e")
            self.assertEqual(app.clip.fps, 12)
        finally:
            app.exit()

    def test_metadata_size_mismatch_keeps_previous_texture_and_recovers(self):
        handle = self.manager.acquire("sample_sheet")
        previous = handle.resource
        write_png(self.root / "body.png", 4, 4, lambda x, y: (255, 0, 0, 255))
        self.assertFalse(self.manager.poll_reload(force=True)[0].success)
        self.assertIs(handle.resource, previous)
        self.assertFalse(previous.closed)
        write_samples(self.root)
        self.assertTrue(self.manager.poll_reload(force=True)[0].success)
        self.assertTrue(previous.closed)

    def test_corrupt_actual_png_keeps_last_good_and_recovers(self):
        handle = self.manager.acquire("sample_image")
        previous = handle.resource
        (self.root / "image.png").write_bytes(b"invalid PNG")
        self.assertFalse(self.manager.poll_reload(force=True)[0].success)
        self.assertIs(handle.resource, previous)
        write_png(self.root / "image.png", 16, 16, lambda x, y: (0, 255, 0, 255))
        self.assertTrue(self.manager.poll_reload(force=True)[0].success)
        self.assertEqual(handle.resource.sizes["body"], (16, 16))

    def test_partial_bundle_texture_load_failure_can_be_retried(self):
        (self.root / "shadow.png").write_bytes(b"broken")
        with self.assertRaises(OSError):
            self.manager.acquire("sample_mech")
        self.assertEqual(self.manager.snapshot(), {})
        write_samples(self.root)
        with self.manager.acquire("sample_mech") as handle:
            self.assertEqual(len(handle.resource.textures), 2)

    def test_preview_registration_roundtrip_duplicate_and_external_update(self):
        from Tools.asset_loader.app import AssetLoaderApp
        destination = self.root / "workspace/catalog.json"
        app = AssetLoaderApp(source=self.root / "bundle.json", catalog=destination, debug=True)
        try:
            app.enter()
            self.assertFalse(app.error)
            self.assertEqual(app.asset_id, "sample_mech")
            app.register()
            self.assertEqual(AssetCatalog.load(destination).definitions["sample_mech"].source, self.root / "bundle.json")
            before = destination.read_bytes()
            with self.assertRaises(ValueError):
                app.register()
            self.assertEqual(before, destination.read_bytes())
            data = json.loads(before)
            data["assets"].append({"id": "external", "kind": "image", "source": "../image.png"})
            destination.write_text(json.dumps(data), encoding="utf-8")
            app.asset_id = "second"
            app.register()
            self.assertIn("external", AssetCatalog.load(destination).definitions)
            app.draw()
        finally:
            app.exit()

    def test_preview_preserves_previous_on_invalid_new_file_and_hot_reload(self):
        from Tools.asset_loader.app import AssetLoaderApp
        app = AssetLoaderApp(source=self.root / "body.json", catalog=self.root / "new/catalog.json", debug=True)
        try:
            app.enter()
            previous = app.handle.resource
            self.assertFalse(app.open_source(self.root / "missing.png"))
            self.assertIs(app.handle.resource, previous)
            (self.root / "body.png").write_bytes(b"broken")
            app.apply_reload(app.manager.poll_reload(force=True))
            self.assertTrue(app.error)
            self.assertIs(app.handle.resource, previous)
            write_samples(self.root)
            app.apply_reload(app.manager.poll_reload(force=True))
            self.assertFalse(app.error)
            self.assertEqual(app.handle.generation, 2)
            app.draw()
        finally:
            app.exit()

    def test_registration_revalidates_source_and_keeps_existing_catalog_on_failure(self):
        from Tools.asset_loader.app import AssetLoaderApp
        destination = self.root / "workspace/catalog.json"
        app = AssetLoaderApp(source=self.root / "image.png", catalog=destination)
        try:
            app.enter()
            app.register()
            before = destination.read_bytes()
            app.asset_id = "broken_new_registration"
            (self.root / "image.png").write_bytes(b"broken")
            with self.assertRaises(OSError):
                app.register()
            self.assertEqual(before, destination.read_bytes())
            self.assertNotIn(app.asset_id, app.catalog.definitions)
        finally:
            app.exit()

    def test_bundle_same_texture_path_is_allocated_once(self):
        shadow_path = self.root / "shadow.json"
        shadow = json.loads(shadow_path.read_text())
        shadow["image"]["path"] = "body.png"
        shadow_path.write_text(json.dumps(shadow), encoding="utf-8")
        with self.manager.acquire("sample_mech") as handle:
            self.assertEqual(handle.resource.estimated_bytes, 256 * 512 * 4)

    def test_shadow_opacity_does_not_dim_shared_body_or_leave_texture_state_changed(self):
        from ctypes import byref, c_ubyte
        from unittest.mock import patch
        data = json.loads((self.root / "shadow.json").read_text())
        data["image"]["path"] = "body.png"
        (self.root / "shadow.json").write_text(json.dumps(data))
        with self.manager.acquire("sample_mech") as handle:
            resource, observed = handle.resource, []
            original = self.pico.SDL_RenderCopy
            def draw(renderer, texture, source, destination):
                alpha = c_ubyte()
                self.pico.SDL_GetTextureAlphaMod(texture, byref(alpha))
                observed.append(alpha.value)
                return original(renderer, texture, source, destination)
            with patch.object(self.pico, "SDL_RenderCopy", side_effect=draw):
                resource.draw("idle/e", 0, 100, 100)
                resource.draw("idle/e", 0, 100, 100, shadow_opacity=1)
            self.assertEqual(observed, [128, 255, 255, 255])
            current = c_ubyte()
            self.pico.SDL_GetTextureAlphaMod(resource.textures["body"], byref(current))
            self.assertEqual(current.value, 255)

    def test_shadow_opacity_restores_alpha_after_failed_draw_and_rejects_invalid_values(self):
        from ctypes import byref, c_ubyte
        from unittest.mock import patch
        with self.manager.acquire("sample_mech") as handle:
            resource = handle.resource
            self.pico.SDL_SetTextureAlphaMod(resource.textures["shadow"], 100)
            with patch.object(self.pico, "SDL_RenderCopy", side_effect=RuntimeError("draw failed")):
                with self.assertRaisesRegex(RuntimeError, "draw failed"):
                    resource.draw("idle/e", 0, 100, 100)
            current = c_ubyte()
            self.pico.SDL_GetTextureAlphaMod(resource.textures["shadow"], byref(current))
            self.assertEqual(current.value, 100)
            for opacity in (-1, 2, float("nan")):
                with self.assertRaises(ValueError):
                    resource.draw("idle/e", 0, 100, 100, shadow_opacity=opacity)

    def test_preview_keyboard_controls_and_readonly_sample_catalog(self):
        from types import SimpleNamespace
        from Tools.asset_loader.app import AssetLoaderApp, ROOT
        app = AssetLoaderApp(source=self.root / "bundle.json", catalog=self.root / "unused.json")
        try:
            app.enter()
            def key(value):
                app.handle_event(SimpleNamespace(type=self.pico.SDL_KEYDOWN, key=value))
            first = app.clip_name
            key(self.pico.SDLK_RIGHT)
            self.assertNotEqual(app.clip_name, first)
            key(self.pico.SDLK_SPACE)
            self.assertTrue(app.paused)
            before = app.frame_index
            key(self.pico.SDLK_PERIOD)
            self.assertEqual(app.frame_index, (before + 1) % len(app.clip.frames))
            key(self.pico.SDLK_b)
            self.assertFalse(app.show_body)
            key(self.pico.SDLK_d)
            self.assertTrue(app.manager.debug)
            app.catalog_path = ROOT / "samples/asset_loader/catalog.json"
            with self.assertRaises(ValueError):
                app.register()
            app.draw()
        finally:
            app.exit()


if __name__ == "__main__":
    unittest.main()

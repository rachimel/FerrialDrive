"""모델 렌더 설정과 본체/그림자 동시 조립·원본 보존·로더 연결을 검사한다."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ferrial_drive.assets import AssetDefinition, SpriteBundle
from ferrial_drive.assets.sprites import SpriteSheet
from samples.asset_loader.make_sample import write_samples
from Tools.asset_loader.assembly import SpriteAssembly
from Tools.asset_loader.production import frame_numbers, render_config


class AssetProductionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fdrive-production-")
        self.root = write_samples(self.temporary.name)
        self.definition = AssetDefinition("sample_mech", "bundle", self.root / "bundle.json")
        self.assembly = SpriteAssembly(self.definition)

    def tearDown(self):
        self.temporary.cleanup()

    def test_recipe_keeps_existing_rig_options_and_rejects_invalid_work(self):
        values = dict(asset_id="rig", animation_name="walk", frames="1,3", fps="24", width="128", height="128",
                      ortho_scale="4.5", samples="2", root_object="SampleRig", use_scene_camera=False)
        config = render_config(**values)
        self.assertEqual(config["frames"], [1, 3])
        self.assertEqual(config["root_object"], "SampleRig")
        self.assertEqual(len(config["directions"]), 8)
        self.assertFalse(config["use_scene_camera"])
        self.assertEqual(config["light"]["position"], [-3, -4, 12])
        self.assertEqual(config["light"]["energy"], 1400)
        self.assertFalse(config["use_scene_lighting"])
        self.assertEqual(config["postprocess"], {"sharpen": 0.35})
        self.assertTrue(config["auto_fit"])
        self.assertFalse(render_config(**(values | {"use_scene_camera": True}))["auto_fit"])
        self.assertFalse(render_config(**(values | {"auto_fit": False}))["auto_fit"])
        for key, value in (("fps", "nan"), ("frames", "1,1"), ("width", "0"), ("animation_name", "../walk"),
                           ("samples", "0"), ("ortho_scale", "inf"), ("fps", "23.5")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                render_config(**(values | {key: value}))
        self.assertEqual(frame_numbers("3,1,2"), [3, 1, 2])

    def test_directional_reorder_repeat_and_pivot_keep_layers_equal(self):
        self.assembly.apply("idle/e", "attack", [3, 1, 1, 0], 12.5, (20, 8))
        path = self.assembly.save(self.root / "export", asset_id="edited")
        bundle = SpriteBundle.load(path)
        self.assertEqual(bundle.directions["e"], "attack/e")
        for direction in bundle.directions:
            name = "attack/" + direction
            self.assertEqual(bundle.body.clips[name], bundle.shadow.clips[name])
            clip = bundle.body.clips[name]
            self.assertEqual(clip.fps, 12.5)
            self.assertEqual(clip.frames[0].rect[0], 192)
            self.assertEqual(clip.frames[1], clip.frames[2])
            self.assertEqual(clip.frames[0].pivot, (20, 8))
        self.assertEqual(SpriteBundle.load(self.definition.source).asset_id, "sample_mech")
        self.assertEqual(len(SpriteBundle.load(self.definition.source).body.clips), 8)

    def test_invalid_edit_is_transactional_and_export_never_overwrites(self):
        before = deepcopy(self.assembly.layers)
        for order, fps, pivot in (([999], 8, None), ([], 8, None), ([0], 0, None), ([0], 8, (999, 0))):
            with self.assertRaises(ValueError):
                self.assembly.apply("idle/e", "bad", order, fps, pivot)
            self.assertEqual(before, self.assembly.layers)
        with self.assertRaises(ValueError):
            self.assembly.save(self.root, asset_id="edited")

    def test_single_direction_edit_preserves_other_directions_and_bindings(self):
        body = self.root / "body.json"
        data = json.loads(body.read_text())
        data["event_bindings"] = {"idle": "idle/e"}
        body.write_text(json.dumps(data))
        self.assembly = SpriteAssembly(self.definition)
        self.assembly.apply("idle/e", "idle", [1, 0], 10, None, all_directions=False)
        path = self.assembly.save(self.root / "single", asset_id="single")
        bundle = SpriteBundle.load(path)
        self.assertEqual(len(bundle.body.clips["idle/e"].frames), 2)
        self.assertEqual(len(bundle.body.clips["idle/n"].frames), 4)
        self.assertEqual(json.loads((path.parent / "body.json").read_text())["event_bindings"], {"idle": "idle/e"})

    def test_image_and_sheet_assembly_export_standalone_projects(self):
        for kind, filename, size in (("image", "image.png", (128, 128)), ("sheet", "body.json", None)):
            assembly = SpriteAssembly(AssetDefinition(kind, kind, self.root / filename), image_size=size)
            name = assembly.names[0]
            assembly.apply(name, "edited", [0, 0], 24, (16, 8))
            path = assembly.save(self.root / (kind + "-export"), asset_id=kind)
            sheet = SpriteSheet.load(path)
            target = "edited/e" if "/" in name else "edited"
            self.assertEqual(len(sheet.clips[target].frames), 2)
            self.assertTrue(sheet.image_path.is_file())

    def test_failed_copy_does_not_publish_or_leave_partial_export(self):
        destination = self.root / "broken"
        with patch("Tools.asset_loader.assembly.shutil.copyfile", side_effect=OSError("copy failed")):
            with self.assertRaises(OSError):
                self.assembly.save(destination, asset_id="broken")
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".broken.*")), [])

    def test_existing_ssheet_editor_reads_assembled_frames(self):
        import runpy
        self.assembly.apply("idle/e", "attack", [2, 0], 18, (32, 9))
        path = self.assembly.save(self.root / "compat", asset_id="compat")
        editor = runpy.run_path(str(Path(__file__).resolve().parents[2] / "Tools/SSheetCutil.py"), run_name="sheet_compatibility")
        project, _ = editor["import_project"](path.parent / "body.json")
        clip = next(clip for clip in project.animations if clip.name == "attack/e")
        self.assertEqual(clip.fps, 18)
        self.assertEqual(clip.frames[0].rect[0], 128)

    def test_completed_render_opens_result_and_failed_render_keeps_preview(self):
        from Tools.asset_loader.app import AssetLoaderApp
        app = AssetLoaderApp()
        app.build = SimpleNamespace(process=object(), poll=lambda: True, result=self.definition.source,
                                    progress_text="프리렌더 완료 100% (64/64)")
        with patch.object(app, "open_source") as opened:
            app.update(0.1)
            opened.assert_called_once_with(self.definition.source)
        self.assertEqual(app.message, "프리렌더 완료 100% (64/64)")
        app.build = SimpleNamespace(process=object(), poll=lambda: False, error="render failed")
        with patch.object(app, "open_source") as opened:
            app.update(0.1)
            opened.assert_not_called()
        self.assertEqual(app.message, "render failed")

    def test_render_panel_returns_recipe_without_starting_another_loop(self):
        from Tools.asset_loader.app import AssetLoaderApp
        from Tools.asset_loader.editors import RenderPanel
        app = AssetLoaderApp()
        source = self.root / "model.blend"
        source.write_bytes(b"fixture")
        app.configure_render(source)
        self.assertIsInstance(app.panel, RenderPanel)
        app.panel.fields["frames"].text = "1,5"
        with patch.object(app, "start_render") as start:
            app.panel.submit()
        self.assertIsNone(app.panel)
        model, config = start.call_args.args
        self.assertEqual(model, source)
        self.assertEqual(config["frames"], [1, 5])
        self.assertTrue(config["auto_fit"])


if __name__ == "__main__":
    unittest.main()

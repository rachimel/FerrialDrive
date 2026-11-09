"""AI 진입점의 JSON 계약·GUI 작업본 교환·실패 시 원본 보존을 검사한다."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from ferrial_drive.assets import AssetCatalog, MechBundle
from ferrial_drive.assets.sprites import SpriteBundle
from Tools.asset_loader.automation import execute
from Tools.asset_loader.mech_plan import default_plan, load_plan, save_plan, plan_path
from Tools.asset_loader.production import render_config
from samples.mech_asset.make_sample import write_sample


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "Tools/asset_loader/asset_pipeline.py"
SAMPLE = ROOT / "samples/asset_loader/bundle.json"


class AssetAutomationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="asset-automation-")
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def request(self, operation, **fields):
        return execute({"version": 1, "operation": operation, **fields}, base_dir=self.root)

    def cli(self, content=None, *, request_file=None):
        args = [sys.executable, str(ENTRY)]
        if content is not None or request_file:
            args += ["--request", str(request_file) if request_file else "-"]
        result = subprocess.run(args, input=content.encode("utf-8") if content is not None else None,
                                cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        response = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(result.returncode, 0 if response["ok"] else 1, result.stderr)
        return response

    def create_plan(self):
        return self.request("plan.create", source=str(SAMPLE), asset_id="automation_mech", output="plan.json")

    def test_discovery_and_import_need_neither_window_nor_sdl(self):
        response = self.cli()
        self.assertIn("plan.export", response["result"]["operations"])
        code = ("import sys; from Tools.asset_loader.automation import describe; describe(); "
                "assert 'Tools.asset_loader.app' not in sys.modules; assert 'pico2d.pico2d' not in sys.modules")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")

    def test_cli_resolves_request_relative_paths_from_other_working_directory(self):
        request = ROOT / "samples/asset_loader/requests/inspect_bundle.json"
        result = self.cli(request_file=request)["result"]
        self.assertEqual(Path(result["source"]), SAMPLE)
        self.assertEqual(result["clips"]["idle/s"]["frame_count"], 4)
        self.assertEqual(len(result["images"]), 2)

    def test_cli_errors_are_json_utf8_with_nonzero_exit_and_no_partial_output(self):
        for content in ("{", "[]", '{"version":2,"operation":"describe"}',
                        '{"version":1,"operation":"없는작업"}',
                        '{"version":1,"operation":"asset.inspect","source":"없음.png"}',
                        '{"version":1,"operation":"describe","typo":true}',
                        '{"version":1,"operation":"describe","unused":NaN}',
                        '{"version":1,"operation":NaN}'):
            with self.subTest(content=content):
                response = self.cli(content)
                self.assertFalse(response["ok"])
                self.assertIn("code", response["error"])

    def test_image_inspection_and_assembly_use_actual_decoded_size_without_window(self):
        source = ROOT / "samples/asset_loader/image.png"
        result = self.request("asset.inspect", source=str(source), include_frames=True)
        self.assertEqual(result["default_clip"], "image")
        self.assertEqual(result["clips"]["image"]["frames"][0]["rect"][2:], result["images"][0]["size"])
        result = self.request("sprite.assemble", source=str(source), asset_id="still", output="still", edits=[
            {"source_clip": "image", "name": "hold", "order": [0, 0], "fps": 2}])
        self.assertTrue(Path(result["source"]).is_file())
        self.assertIn("hold", result["clips"])

    def test_inspection_rejects_wrong_dimensions_and_corrupt_pixels(self):
        data = json.loads((SAMPLE.parent / "body.json").read_text(encoding="utf-8"))
        data["image"]["path"] = str(SAMPLE.parent / "body.png")
        data["image"]["size"][0] += 1
        target = self.root / "wrong.json"
        target.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "실제 이미지"):
            self.request("asset.inspect", source="wrong.json")
        (self.root / "bad.png").write_bytes(b"not a png")
        with self.assertRaisesRegex(ValueError, "이미지를 읽을"):
            self.request("asset.inspect", source="bad.png")

    def test_gui_plan_roundtrip_and_failed_batch_preserve_file(self):
        created = self.create_plan()
        path = Path(created["plan"])
        self.assertEqual(load_plan(path, asset_id="automation_mech", source=SAMPLE), created["data"])
        self.assertEqual(self.request("plan.read", plan="plan.json")["data"], created["data"])
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.request("plan.update", plan="plan.json", edits=[
                {"action": "part.add", "id": "antenna", "name": "안테나"},
                {"action": "set", "path": ["render", "fps"], "value": "0"}])
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(FileExistsError):
            self.create_plan()
        self.assertEqual(path.read_bytes(), before)
        result = self.request("plan.update", plan="plan.json", edits=[
            {"action": "part.add", "id": "antenna", "name": "안테나"},
            {"action": "set", "path": ["layers", "antenna", "objects"], "value": "Antenna"},
            {"action": "state.add", "part": "antenna", "id": "folded", "name": "접힘"},
            {"action": "order.preset", "motion": "aim", "direction": "s", "preset": "back"},
            {"action": "order.copy_all", "motion": "aim", "direction": "s"}])
        self.assertEqual(result["data"]["layers"]["antenna"]["objects"], "Antenna")
        orders = result["data"]["motions"]["aim"]["orders"]
        self.assertTrue(all(order == orders["s"] for order in orders.values()))

    def test_default_plan_location_is_the_gui_location(self):
        with patch("Tools.asset_loader.automation.plan_path", return_value=self.root / "gui.json") as location:
            result = self.request("plan.create", source=str(SAMPLE), asset_id="same_gui")
        location.assert_called_once_with("same_gui", SAMPLE)
        self.assertEqual(Path(result["plan"]), self.root / "gui.json")
        self.assertNotEqual(plan_path("same_gui", SAMPLE), plan_path("different", SAMPLE))

    def test_mapping_and_reference_cleanup_use_shared_part_operations(self):
        self.create_plan()
        result = self.request("plan.update", plan="plan.json", edits=[
            {"action": "mapping.apply", "preset": "npc"},
            {"action": "part.add", "id": "back", "name": "등 스러스터", "template": "thrusters"},
            {"action": "set", "path": ["motions", "aim", "part_states"], "value": {"back": "horizontal"}},
            {"action": "part.add", "id": "back_copy", "name": "복제", "duplicate": "back"},
            {"action": "state.remove", "part": "back_copy", "id": "horizontal"},
            {"action": "part.remove", "id": "back"}])
        self.assertEqual(set(result["data"]["layers"]), {"body", "back_copy"})
        self.assertEqual(result["data"]["motions"]["aim"]["part_states"], {})

    def test_structure_validation_is_distinct_from_export_readiness(self):
        self.create_plan()
        result = self.request("plan.validate", plan="plan.json")
        self.assertTrue(result["structure_valid"])
        self.assertFalse(result["sheets_checked"])
        with self.assertRaises(ValueError):
            self.request("plan.validate", plan="plan.json", check_sheets=True)
        with self.assertRaises(ValueError):
            self.request("plan.export", plan="plan.json", output="incomplete")
        self.assertFalse((self.root / "incomplete").exists())

    def test_mech_export_preserves_split_images_and_can_be_reopened(self):
        paths = write_sample(self.root / "sample")
        plan = default_plan("split", self.root / "source.json")
        plan["render"].update(width="96", height="96", pivot="48,10")
        for key, values in paths.items():
            plan["layers"][key].update(values)
        save_plan(self.root / "plan.json", plan)
        self.assertTrue(self.request("plan.validate", plan="plan.json", check_sheets=True)["sheets_checked"])
        exported = self.request("plan.export", plan="plan.json", output="exported")
        mech = MechBundle.load(exported["source"])
        self.assertEqual(len(list((self.root / "exported").rglob("*.png"))), 6)
        for key, row in paths.items():
            self.assertEqual(Path(row["sheet"]).with_suffix(".png").read_bytes(), mech.sheets[key].image_path.read_bytes())
        imported = self.request("plan.create", source=exported["source"], asset_id="reopened", output="reopened.json")
        self.assertEqual(set(imported["data"]["layers"]), set(mech.layer_rows))

    def test_sprite_assembly_preserves_source_and_synchronizes_directions(self):
        before = SAMPLE.read_bytes()
        result = self.request("sprite.assemble", source=str(SAMPLE), asset_id="reverse", output="reverse", edits=[
            {"source_clip": "idle/s", "name": "reverse", "order": [3, 1, 1, 0], "fps": 9.5}])
        bundle = SpriteBundle.load(result["source"])
        self.assertEqual(len(bundle.directions), 8)
        for name in bundle.directions.values():
            self.assertTrue(name.startswith("reverse/"))
            self.assertEqual(bundle.body.clips[name], bundle.shadow.clips[name])
            self.assertEqual(bundle.body.clips[name].fps, 9.5)
        self.assertEqual(SAMPLE.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.request("sprite.assemble", source=str(SAMPLE), asset_id="reverse", output="reverse", edits=[
                {"source_clip": "idle/s", "name": "reverse", "order": [0], "fps": 4}])

    def test_catalog_registration_duplicate_and_read_only_sample(self):
        result = self.request("catalog.register", source=str(SAMPLE), asset_id="registered", catalog="catalog.json")
        self.assertEqual(AssetCatalog.load(result["catalog"]).definitions["registered"].source, SAMPLE)
        before = (self.root / "catalog.json").read_bytes()
        with self.assertRaises(ValueError):
            self.request("catalog.register", source=str(SAMPLE), asset_id="registered", catalog="catalog.json")
        self.assertEqual((self.root / "catalog.json").read_bytes(), before)
        self.assertEqual(self.request("catalog.list", catalog="catalog.json")["assets"][0]["asset_id"], "registered")
        with self.assertRaisesRegex(ValueError, "읽기 전용"):
            self.request("catalog.register", source=str(SAMPLE), asset_id="other", catalog=str(SAMPLE.parent / "catalog.json"))

    def test_render_wait_success_failure_and_timeout_always_close_child(self):
        config = render_config(asset_id="render_sample", animation_name="idle", frames="1,3", fps=8,
                               width=96, height=96, ortho_scale=4.5, samples=2)
        (self.root / "render.json").write_text(json.dumps(config), encoding="utf-8")
        for outcome in (True, False, None):
            with self.subTest(outcome=outcome):
                build = MagicMock(result=self.root / "bundle.json", directory=self.root / "rendered",
                                  completed_images=32, total_images=32, error="렌더 실패")
                build.poll.return_value = outcome
                with patch("Tools.blender_pipeline.asset_build.AssetBuild", return_value=build), \
                     patch("Tools.asset_loader.automation.time.monotonic", side_effect=[0, 2]):
                    fields = {"config": "render.json",
                              "sample": True, "timeout_seconds": 1}
                    if outcome is True:
                        result = self.request("render.run", **fields)
                        self.assertEqual(result["completed_images"], 32)
                    else:
                        with self.assertRaises(TimeoutError if outcome is None else RuntimeError):
                            self.request("render.run", **fields)
                build.close.assert_called_once()

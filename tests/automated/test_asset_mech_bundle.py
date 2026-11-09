"""분리 시트 합성·내보내기와 동작 범위 프리셋·슬롯 호환을 확인한다."""

from copy import deepcopy
from ctypes import c_ubyte
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from ferrial_drive.assets import AssetCatalog, AssetDefinition, AssetManager, MechBundle, detect_kind
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from Tools.asset_loader.mech_export import build_mech, copy_mech, import_mech
from Tools.asset_loader.mech_plan import default_plan, load_plan
from Tools.asset_loader.mech_presets import apply_all_directions, apply_mapping, apply_order_preset, save_mapping
from samples.mech_asset.make_sample import write_sample


class MechBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pico2d.pico2d as pico
        cls.pico = pico
        cls.temporary = tempfile.TemporaryDirectory(prefix="split-mech-")
        cls.root = Path(cls.temporary.name)
        cls.paths = write_sample(cls.root / "sample")
        pico.open_canvas(1280, 800)
        if not pico.renderer:
            pico.renderer = pico.SDL_CreateRenderer(pico.window, -1, pico.SDL_RENDERER_SOFTWARE)

    @classmethod
    def tearDownClass(cls):
        cls.pico.close_canvas()
        cls.temporary.cleanup()

    def setUp(self):
        self.plan = default_plan("test_mech", self.root / "input.json")
        self.plan["render"].update(width="96", height="96", pivot="48,10")
        for key, row in self.paths.items():
            self.plan["layers"][key].update(row)
        self.local = tempfile.TemporaryDirectory(dir=self.root)
        self.folder = Path(self.local.name)

    def tearDown(self):
        self.local.cleanup()

    def test_export_keeps_each_color_and_mask_byte_identical_and_relative(self):
        source = build_mech(self.plan)
        result = copy_mech(source, self.folder / "exported")
        self.assertEqual(detect_kind(result), "mech")
        loaded = MechBundle.load(result)
        for key, sheet in source.sheets.items():
            self.assertEqual(sheet.image_path.read_bytes(), loaded.sheets[key].image_path.read_bytes())
            self.assertTrue(loaded.sheet_paths[key].is_relative_to(result.parent))
        self.assertEqual(len(list(result.parent.rglob("*.png"))), 6)
        before = result.read_bytes()
        with self.assertRaises(ValueError):
            copy_mech(source, result.parent)
        self.assertEqual(result.read_bytes(), before)
        relocated = self.folder / "relocated"
        result.parent.rename(relocated)
        self.assertEqual(MechBundle.load(relocated / "mech.json").rows, loaded.rows)

    def test_runtime_uses_frame_order_and_import_preserves_exported_pose(self):
        self.plan["motions"]["equipped_idle"]["orders"]["s"].reverse()
        self.plan["motions"]["equipped_idle"]["overrides"] = [{"direction": "s", "frame": 3,
            "order": list(reversed(self.plan["motions"]["equipped_idle"]["orders"]["s"]))}]
        mech = build_mech(self.plan)
        self.assertNotEqual(mech.order("equipped_idle/s", 0), mech.order("equipped_idle/s", 1))
        result = copy_mech(mech, self.folder / "game")
        manager = AssetManager(AssetCatalog([AssetDefinition("mech", "mech", result)]), PicoAssetBackend("nearest"))
        try:
            with manager.acquire("mech") as handle:
                resource = handle.resource
                resource.draw("equipped_idle/s", 0, 400, 400, scale=2)
                resource.draw("equipped_idle/s", 1, 400, 400, scale=2)
                self.assertEqual(resource.clips["equipped_idle/s"].fps, 8)
                restored = import_mech(default_plan("test_mech", result), resource.mech)
                self.assertEqual(build_mech(restored).rows, mech.rows)
        finally:
            manager.close()

    def test_rendered_overlap_changes_with_front_and_back_presets(self):
        from Tools.asset_loader.mech_export import mech_document
        resource = PicoAssetBackend("nearest").load(mech_document(self.plan))
        def pixel(order):
            self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 0, 0, 0, 255)
            self.pico.SDL_RenderClear(self.pico.renderer)
            resource.draw("equipped_idle/s", 0, 48, 10, layer_order=order)
            rect = self.pico.SDL_Rect(45, 744, 1, 1)
            data = (c_ubyte * 4)()
            self.assertEqual(self.pico.SDL_RenderReadPixels(self.pico.renderer, rect, self.pico.SDL_PIXELFORMAT_RGBA32, data, 4), 0)
            return tuple(data[:3])
        try:
            # 캔버스 좌표는 bottom-left이고 소스 이미지는 top-left다.
            front = pixel(["sheath", "body", "left_hand", "right_hand"])
            back = pixel(["sheath", "left_hand", "right_hand", "body"])
            self.assertNotEqual(front, back)
        finally:
            resource.close()

    def test_misaligned_mask_and_missing_direction_are_rejected(self):
        mask = json.loads(Path(self.paths["body"]["energy_sheet"]).read_text())
        mask["image"]["path"] = str(Path(self.paths["body"]["energy_sheet"]).with_suffix(".png"))
        mask["animations"][0]["frames"][0]["pivot"] = [47, 10]
        path = self.folder / "bad.json"
        path.write_text(json.dumps(mask))
        self.plan["layers"]["body"]["energy_sheet"] = str(path)
        with self.assertRaises(ValueError):
            build_mech(self.plan)

    def test_presets_and_apply_all_change_only_the_current_motion(self):
        previous = deepcopy(self.plan["motions"]["slash"])
        self.plan["motions"]["equipped_idle"]["overrides"] = [{"direction": "s", "frame": 3,
            "order": list(self.plan["motions"]["equipped_idle"]["orders"]["s"])}]
        apply_order_preset(self.plan, "equipped_idle", "s", "back")
        overrides = deepcopy(self.plan["motions"]["equipped_idle"]["overrides"])
        apply_all_directions(self.plan, "equipped_idle", "s")
        self.assertEqual(self.plan["motions"]["slash"], previous)
        self.assertEqual(self.plan["motions"]["equipped_idle"]["overrides"], overrides)
        orders = self.plan["motions"]["equipped_idle"]["orders"]
        self.assertTrue(all(order == orders["s"] for order in orders.values()))
        apply_all_directions(self.plan, "equipped_idle", "s", 3)
        self.assertEqual(len(self.plan["motions"]["equipped_idle"]["overrides"]), 8)

    def test_mapping_preset_preserves_sheet_links_and_bad_preset_preserves_plan(self):
        self.plan["layers"]["body"]["objects"] = "Actor"
        preset = save_mapping("표준 메카", self.plan, root=self.folder)
        self.plan["layers"]["body"]["objects"] = "Changed"
        sheet = self.plan["layers"]["body"]["sheet"]
        apply_mapping(self.plan, str(preset))
        self.assertEqual(self.plan["layers"]["body"]["objects"], "Actor")
        self.assertEqual(self.plan["layers"]["body"]["sheet"], sheet)
        before = deepcopy(self.plan)
        invalid = json.loads(preset.read_text(encoding="utf-8"))
        invalid["layers"]["body"]["energy_mask"]["mode"] = "unknown"
        preset.write_text(json.dumps(invalid), encoding="utf-8")
        with self.assertRaises(ValueError):
            apply_mapping(self.plan, str(preset))
        self.assertEqual(self.plan, before)

    def test_old_eight_layer_plan_gains_slots_without_reordering_existing_parts(self):
        legacy = deepcopy(self.plan)
        added = {"side_slot_l", "side_slot_r"}
        for key in added:
            legacy["layers"].pop(key)
        for motion in legacy["motions"].values():
            for direction, order in motion["orders"].items():
                motion["orders"][direction] = [key for key in order if key not in added]
        path = self.folder / "old.json"
        path.write_text(json.dumps(legacy))
        loaded = load_plan(path, asset_id=legacy["asset_id"], source=legacy["source"])
        self.assertTrue(added.issubset(loaded["layers"]))
        self.assertEqual([key for key in loaded["motions"]["equipped_idle"]["orders"]["s"] if key not in added],
                         legacy["motions"]["equipped_idle"]["orders"]["s"])

    def test_catalog_storage_copies_the_entire_split_package(self):
        from Tools.asset_loader.library import store_asset
        result = copy_mech(build_mech(self.plan), self.folder / "source")
        stored = store_asset(AssetDefinition("test_mech", "mech", result), root=self.folder / "library")
        self.assertEqual(stored.kind, "mech")
        loaded = MechBundle.load(stored.source)
        self.assertTrue(all(path.is_relative_to(self.folder / "library") for path in loaded.dependencies))
        for key, sheet in build_mech(self.plan).sheets.items():
            self.assertEqual(sheet.image_path.read_bytes(), loaded.sheets[key].image_path.read_bytes())


if __name__ == "__main__":
    unittest.main()

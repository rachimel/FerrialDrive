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
from Tools.asset_loader.part_model import add_part, add_state, all_orders, remove_part, remove_state


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
        legacy["version"] = 1
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

    def test_part_clone_delete_and_name_changes_preserve_ids_and_references(self):
        motion = self.plan["motions"]["equipped_idle"]
        motion["overrides"] = [{"direction": "s", "frame": 3, "order": list(motion["orders"]["s"])}]
        add_part(self.plan, "npc_decoration", "NPC 장식")
        add_state(self.plan, "npc_decoration", "wind", "바람")
        motion["part_states"]["npc_decoration"] = "wind"
        add_part(self.plan, "decoration_copy", "장식 복제", duplicate="npc_decoration")
        self.plan["layers"]["npc_decoration"]["name"] = "이름 변경"
        self.assertEqual(motion["part_states"]["decoration_copy"], "wind")
        self.assertTrue(all("npc_decoration" in order and "decoration_copy" in order for order in all_orders(self.plan)))
        remove_state(self.plan, "npc_decoration", "wind")
        self.assertNotIn("npc_decoration", motion["part_states"])
        self.assertIn("wind", self.plan["layers"]["decoration_copy"]["states"])
        remove_part(self.plan, "npc_decoration")
        self.assertTrue(all("npc_decoration" not in order for order in all_orders(self.plan)))
        before = deepcopy(self.plan)
        with self.assertRaises(ValueError):
            remove_part(self.plan, "body")
        self.assertEqual(before, self.plan)

    def test_npc_preset_and_v2_roundtrip_do_not_reinsert_fixed_mech_parts(self):
        from Tools.asset_loader.mech_plan import save_plan
        apply_mapping(self.plan, "npc")
        add_part(self.plan, "npc_ribbon", "NPC 장식")
        self.plan["layers"]["npc_ribbon"]["sheet"] = self.paths["left_hand"]["sheet"]
        path = self.folder / "npc.json"
        save_plan(path, self.plan)
        loaded = load_plan(path, asset_id=self.plan["asset_id"], source=self.plan["source"])
        self.assertEqual(loaded["version"], 2)
        self.assertEqual(set(loaded["layers"]), {"body", "npc_ribbon"})
        self.assertEqual(set(build_mech(loaded).layer_rows), {"body", "npc_ribbon"})

    def test_state_selection_changes_actual_pixels_and_survives_split_export(self):
        from Tools.asset_loader.mech_export import mech_document
        add_part(self.plan, "npc_ribbon", "NPC 장식")
        part = self.plan["layers"]["npc_ribbon"]
        part.update(sheet=self.paths["left_hand"]["sheet"], energy_sheet=self.paths["body"]["energy_sheet"])
        add_state(self.plan, "npc_ribbon", "horizontal", "수평")
        part["states"]["horizontal"]["sheet"] = self.paths["right_hand"]["sheet"]
        add_state(self.plan, "npc_ribbon", "hidden", "숨김")
        part["states"]["hidden"]["enabled"] = False
        resource = PicoAssetBackend("nearest").load(mech_document(self.plan))
        def pixel(state):
            self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 0, 0, 0, 255)
            self.pico.SDL_RenderClear(self.pico.renderer)
            resource.draw("equipped_idle/s", 0, 48, 10, part_states={"npc_ribbon": state})
            rect, data = self.pico.SDL_Rect(45, 754, 1, 1), (c_ubyte * 4)()
            self.assertEqual(self.pico.SDL_RenderReadPixels(self.pico.renderer, rect, self.pico.SDL_PIXELFORMAT_RGBA32, data, 4), 0)
            return tuple(data[:3])
        try:
            self.assertNotEqual(pixel("base"), pixel("horizontal"))
            self.assertNotIn("npc_ribbon", resource.mech.selection("equipped_idle/s", {"npc_ribbon": "hidden"}))
        finally:
            resource.close()
        self.plan["motions"]["equipped_idle"]["part_states"]["npc_ribbon"] = "horizontal"
        mech = build_mech(self.plan)
        exported = copy_mech(mech, self.folder / "states")
        loaded = MechBundle.load(exported)
        self.assertEqual(loaded.selection("equipped_idle/s")["npc_ribbon"][0], "npc_ribbon:horizontal")
        self.assertIn("npc_ribbon", loaded.masks)
        self.assertNotIn("npc_ribbon:horizontal", loaded.masks)
        restored = import_mech(default_plan("test_mech", exported), loaded)
        self.assertEqual(build_mech(restored).rows, mech.rows)
        for key, sheet in mech.sheets.items():
            self.assertEqual(sheet.image_path.read_bytes(), loaded.sheets[key].image_path.read_bytes())

    def test_state_clip_alias_and_alignment_are_checked_when_selected(self):
        add_part(self.plan, "back_thrusters", "등 스러스터", template="thrusters")
        part = self.plan["layers"]["back_thrusters"]
        part["sheet"] = self.paths["left_hand"]["sheet"]
        state = part["states"]["to_horizontal"]
        data = json.loads(Path(self.paths["right_hand"]["sheet"]).read_text())
        data["image"]["path"] = str(Path(self.paths["right_hand"]["sheet"]).with_suffix(".png"))
        for row in data["animations"]:
            row["name"] = row["name"].replace("equipped_idle/", "turn/")
        path = self.folder / "turn.json"
        path.write_text(json.dumps(data))
        state.update(sheet=str(path), clip="turn")
        self.plan["motions"]["equipped_idle"]["part_states"]["back_thrusters"] = "to_horizontal"
        mech = build_mech(self.plan)
        self.assertEqual(mech.selection("equipped_idle/s")["back_thrusters"][1], "turn/s")
        data["animations"][0]["frames"][0]["pivot"] = [47, 10]
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            build_mech(self.plan)

    def test_dynamic_preset_restores_parts_states_and_preserves_matching_sheet_paths(self):
        add_part(self.plan, "npc_cape", "NPC 망토")
        add_state(self.plan, "npc_cape", "moving", "이동")
        self.plan["layers"]["npc_cape"]["sheet"] = self.paths["left_hand"]["sheet"]
        self.plan["layers"]["npc_cape"]["states"]["moving"]["sheet"] = self.paths["right_hand"]["sheet"]
        preset = save_mapping("NPC 파츠 구성", self.plan, root=self.folder)
        before = deepcopy(self.plan["layers"]["npc_cape"])
        self.plan["layers"]["npc_cape"]["name"] = "변경"
        apply_mapping(self.plan, str(preset))
        self.assertEqual(self.plan["layers"]["npc_cape"], before)
        apply_order_preset(self.plan, "equipped_idle", "s", "front")
        self.assertEqual(self.plan["motions"]["equipped_idle"]["orders"]["s"][-1], "npc_cape")
        remove_part(self.plan, "npc_cape")
        apply_mapping(self.plan, str(preset))
        self.assertIn("moving", self.plan["layers"]["npc_cape"]["states"])

    def test_unsafe_or_case_colliding_part_ids_are_rejected_without_changes(self):
        before = deepcopy(self.plan)
        for key in ("../decor", "CON", "Body", "body", "1_part"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                add_part(self.plan, key, "장식")
        self.assertEqual(before, self.plan)


if __name__ == "__main__":
    unittest.main()

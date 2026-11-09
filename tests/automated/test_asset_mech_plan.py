"""메카 작업본의 좌우 분리·프레임 검증·저장 실패 보존과 단일 창 편집 흐름."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from Tools.asset_loader.mech_plan import default_plan, load_plan, plan_path, save_plan, validate_plan


class MechPlanTests(unittest.TestCase):
    def setUp(self):
        self.source = Path("samples/asset_loader/bundle.json").resolve()
        self.data = default_plan("sample_mech", self.source)

    def validate(self, data):
        validate_plan(data, asset_id="sample_mech", source=self.source)

    def test_directions_motions_and_left_right_orders_are_independent(self):
        self.validate(self.data)
        motions = self.data["motions"]
        self.assertLess(motions["draw"]["orders"]["s"].index("body"), motions["draw"]["orders"]["s"].index("left_hand"))
        self.assertGreater(motions["draw"]["orders"]["n"].index("body"), motions["draw"]["orders"]["n"].index("right_hand"))
        previous = deepcopy(motions["stow"])
        motions["draw"]["orders"]["s"].reverse()
        self.assertEqual(motions["stow"], previous)
        self.assertNotEqual(motions["draw"]["orders"]["s"], motions["draw"]["orders"]["sw"])

    def test_all_transition_types_are_separate_for_each_hand_and_weapon(self):
        from Tools.asset_loader.mech_plan import EVENTS
        events = [{"kind": key, "side": side, "weapon": weapon, "frame": 3}
                  for key, _ in EVENTS for side in ("left", "right") for weapon in ("sword", "gun")]
        self.data["motions"]["draw"]["events"] = events
        self.validate(self.data)
        events.append(deepcopy(events[0]))
        with self.assertRaises(ValueError):
            self.validate(self.data)

    def test_event_and_override_must_use_motion_frame_not_playback_index(self):
        motion = self.data["motions"]["draw"]
        motion["events"] = [{"kind": "attach_hand", "side": "left", "weapon": "sword", "frame": 2}]
        with self.assertRaises(ValueError):
            self.validate(self.data)
        motion["events"][0]["frame"] = 3
        motion["overrides"] = [{"direction": "s", "frame": 3, "order": list(reversed(motion["orders"]["s"]))}]
        self.validate(self.data)
        motion["overrides"].append(deepcopy(motion["overrides"][0]))
        with self.assertRaises(ValueError):
            self.validate(self.data)

    def test_roundtrip_and_invalid_save_preserve_last_good_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "plan.json"
            save_plan(target, self.data)
            self.assertEqual(load_plan(target, asset_id="sample_mech", source=self.source), self.data)
            before = target.read_bytes()
            self.data["render"]["scale"] = "nan"
            with self.assertRaises(ValueError):
                save_plan(target, self.data)
            self.assertEqual(target.read_bytes(), before)
            with self.assertRaises(ValueError):
                load_plan(target, asset_id="other", source=self.source)

    def test_source_and_id_both_scope_the_plan(self):
        self.assertNotEqual(plan_path("sample_mech", self.source), plan_path("other", self.source))
        self.assertNotEqual(plan_path("sample_mech", self.source), plan_path("sample_mech", self.source.with_name("other.json")))

    def test_bad_common_camera_contract_and_sword_reset_are_rejected(self):
        for key, value in (("fps", "8.5"), ("width", "0"), ("pivot", "240,300"), ("height", "inf")):
            data = deepcopy(self.data)
            data["render"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(data)
        self.data["sword_reset_frame"] = "2"
        with self.assertRaises(ValueError):
            self.validate(self.data)

    def test_motion_frames_inherit_common_unless_overridden(self):
        self.data["render"]["frames"] = "2,4,6"
        self.data["motions"]["draw"]["events"] = [{"kind": "grip", "side": "left", "weapon": "sword", "frame": 4}]
        self.validate(self.data)
        self.data["motions"]["draw"]["frames"] = "1,3,5"
        with self.assertRaises(ValueError):
            self.validate(self.data)

    def test_legacy_plan_load_adds_unassigned_masks_without_rewriting_original(self):
        from Tools.asset_loader.mech_plan import ENERGY_CHECKS
        legacy = deepcopy(self.data)
        for layer in legacy["layers"].values():
            layer.pop("energy_mask")
        for key, _ in ENERGY_CHECKS:
            legacy["checks"].pop(key)
        legacy["layers"]["left_hand"]["empty_hand"] = "LeftHand"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            original = path.read_bytes()
            loaded = load_plan(path, asset_id="sample_mech", source=self.source)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(loaded["motions"], legacy["motions"])
            self.assertEqual(loaded["layers"]["left_hand"]["empty_hand"], "LeftHand")
            self.assertEqual(loaded["layers"]["body"]["energy_mask"], {"mode": "unassigned", "source": ""})
            save_plan(path, loaded)
            self.assertEqual(load_plan(path, asset_id="sample_mech", source=self.source), loaded)

    def test_masks_are_owner_scoped_and_invalid_mode_preserves_saved_file(self):
        self.data["layers"]["body"]["energy_mask"].update(mode="material", source="Core_EnergyMask")
        self.data["layers"]["sheath"]["energy_mask"].update(mode="objects", source="Sheath_Energy")
        self.assertEqual(self.data["layers"]["left_hand"]["energy_mask"]["mode"], "unassigned")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "masks.json"
            save_plan(path, self.data)
            before = path.read_bytes()
            self.data["layers"]["body"]["energy_mask"]["mode"] = "unknown"
            with self.assertRaises(ValueError):
                save_plan(path, self.data)
            self.assertEqual(path.read_bytes(), before)


class MechPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pico2d.pico2d as pico
        cls.pico = pico
        pico.open_canvas(1280, 800)
        if not pico.renderer:
            pico.renderer = pico.SDL_CreateRenderer(pico.window, -1, pico.SDL_RENDERER_SOFTWARE)

    @classmethod
    def tearDownClass(cls):
        cls.pico.close_canvas()

    def setUp(self):
        from samples.asset_loader.make_sample import write_samples
        from Tools.asset_loader.app import AssetLoaderApp
        self.temporary = tempfile.TemporaryDirectory()
        self.root = write_samples(self.temporary.name)
        self.app = AssetLoaderApp(source=self.root / "bundle.json", catalog=self.root / "catalog.json")
        self.app.enter()
        self.app.action("mech")
        self.panel = self.app.panel
        self.panel.path = self.root / "mech-plan.json"

    def tearDown(self):
        self.app.exit()
        self.temporary.cleanup()

    def test_all_tabs_draw_in_existing_window_and_invalid_event_keeps_input(self):
        window = self.pico.window
        for tab in range(5):
            self.panel.switch(tab=tab)
            self.app.draw()
            self.assertIs(self.pico.window, window)
        self.panel.switch(tab=3)
        self.panel.fields["grip"].text = "2"
        self.panel.attempt(lambda: self.panel.switch(side="right"))
        self.assertEqual(self.panel.side, "left")
        self.assertEqual(self.panel.value("grip"), "2")
        self.assertTrue(self.panel.error)

    def test_switch_hand_weapon_and_save_restore_do_not_lose_other_events(self):
        self.panel.switch(tab=3, motion=2)
        self.panel.fields["grip"].text = "3"
        self.panel.switch(side="right", weapon="gun")
        self.panel.fields["attach_hand"].text = "5"
        self.panel.submit()
        self.panel.switch(side="left", weapon="sword")
        self.assertEqual(self.panel.value("grip"), "3")
        self.panel.reload()
        self.assertEqual(len(self.panel.current_motion["events"]), 2)
        self.panel.path.write_text("{}", encoding="utf-8")
        before = deepcopy(self.panel.data)
        self.panel.attempt(self.panel.reload)
        self.assertEqual(self.panel.data, before)
        self.assertTrue(self.panel.error)

    def test_layer_mapping_and_empty_hand_survive_close_and_reopen(self):
        self.panel.switch(tab=1, layer=1)
        self.panel.fields["left_hand.objects"].text = "Hand.L,Sword"
        self.panel.fields["left_hand.empty_hand"].text = "Hand.L"
        self.panel.close()
        from Tools.asset_loader.mech_panel import MechPanel
        with patch("Tools.asset_loader.mech_panel.plan_path", return_value=self.panel.path):
            reopened = MechPanel(self.app)
        reopened.switch(tab=1, layer=1)
        self.assertEqual(reopened.value("left_hand.empty_hand"), "Hand.L")
        self.assertEqual(reopened.value("left_hand.objects"), "Hand.L,Sword")

    def test_step_buttons_and_catalog_wheel_keep_preview_controls_separate(self):
        self.panel.close()
        self.app.action("previous")
        self.assertTrue(self.app.paused)
        self.assertEqual(self.app.frame_index, 3)
        self.app.action("next")
        self.assertEqual(self.app.frame_index, 0)
        from Tools.asset_loader.app import CATALOG_RECT
        self.app.mouse = (CATALOG_RECT.x + 8, CATALOG_RECT.y + 8)
        zoom = self.app.zoom
        self.app.handle_event(SimpleNamespace(type=self.pico.SDL_MOUSEWHEEL, y=-1))
        self.assertEqual(self.app.zoom, zoom)

    def test_frame_order_edit_does_not_change_default_or_other_direction(self):
        self.panel.switch(tab=2, motion=2)
        self.panel.toggle("frame_options")
        original = deepcopy(self.panel.current_motion["orders"])
        self.panel.fields["override_frame"].text = "3"
        self.panel.add_override()
        self.panel.order_index = 4
        self.panel.move_order(-1)
        self.assertEqual(self.panel.current_motion["orders"], original)
        changed = list(self.panel.current_order)
        self.assertNotEqual(changed, original["s"])
        self.panel.base_order()
        self.assertEqual(self.panel.current_order, original["s"])
        self.panel.fields["override_frame"].text = "3"
        self.panel.add_override()
        self.assertEqual(self.panel.current_order, changed)
        self.panel.submit()
        self.panel.reload()
        self.assertEqual(self.panel.current_motion["overrides"][0]["order"], changed)

    def test_motion_dropdown_selects_directly_and_escape_only_dismisses_list(self):
        self.panel.switch(tab=2)
        self.panel.fields["clip"].text = "edited_idle"
        button = next(row for row in self.panel.buttons if row[0].startswith("동작:"))
        self.panel.handle_event(SimpleNamespace(type=self.pico.SDL_MOUSEBUTTONDOWN,
            button=self.pico.SDL_BUTTON_LEFT, x=button[1].x + 4, y=button[1].y + 4))
        popup = self.panel.choice_popup[0]
        self.app.draw()
        self.panel.handle_event(SimpleNamespace(type=self.pico.SDL_MOUSEBUTTONDOWN,
            button=self.pico.SDL_BUTTON_LEFT, x=popup.x + 4, y=popup.y + 7 * 28 + 4))
        self.assertEqual(self.panel.motion, 7)
        self.assertEqual(self.panel.data["motions"]["stowed_idle"]["clip"], "edited_idle")
        next(row for row in self.panel.buttons if row[0].startswith("동작:"))[2]()
        self.panel.handle_event(SimpleNamespace(type=self.pico.SDL_KEYDOWN, key=self.pico.SDLK_ESCAPE))
        self.assertIsNone(self.panel.choice_popup)
        self.assertIs(self.app.panel, self.panel)
        next(row for row in self.panel.buttons if row[0].startswith("동작:"))[2]()
        self.panel.handle_event(SimpleNamespace(type=self.pico.SDL_KEYDOWN, key=self.pico.SDLK_F4, mod=self.pico.KMOD_ALT))
        self.assertFalse(self.app.running)

    def test_folded_settings_and_multiple_layer_rows_keep_their_values(self):
        self.panel.switch(tab=1)
        self.panel.fields["left_hand.objects"].text = "LeftHand,Sword"
        self.panel.fields["right_hand.objects"].text = "RightHand,Gun"
        self.panel.switch(tab=0)
        self.panel.toggle("advanced")
        self.panel.fields["scale"].text = "6.5"
        self.panel.toggle("advanced")
        self.assertNotIn("scale", self.panel.fields)
        self.panel.submit()
        self.panel.reload()
        self.panel.toggle("advanced")
        self.assertEqual(self.panel.value("scale"), "6.5")
        self.panel.switch(tab=1)
        self.assertEqual(self.panel.value("left_hand.objects"), "LeftHand,Sword")
        self.assertEqual(self.panel.value("right_hand.objects"), "RightHand,Gun")

    def test_color_and_energy_views_keep_owner_mapping_and_saved_masks(self):
        self.panel.switch(tab=1)
        self.panel.fields["left_hand.objects"].text = "LeftHand,Sword"
        self.panel.select_layer_view("energy")
        mask = self.panel.data["layers"]["left_hand"]["energy_mask"]
        self.panel.choose(mask, "mode", "material")
        self.panel.fields["left_hand.energy_source"].text = "Hand_Mask,Sword_Mask"
        sheath = self.panel.data["layers"]["sheath"]["energy_mask"]
        self.panel.choose(sheath, "mode", "objects")
        self.panel.fields["sheath.energy_source"].text = "Sheath_Light"
        self.app.draw()
        self.panel.select_layer_view("color")
        self.assertEqual(self.panel.value("left_hand.objects"), "LeftHand,Sword")
        self.panel.submit()
        self.panel.reload()
        self.panel.select_layer_view("energy")
        self.assertEqual(self.panel.value("left_hand.energy_source"), "Hand_Mask,Sword_Mask")
        self.assertEqual(self.panel.value("sheath.energy_source"), "Sheath_Light")
        self.assertEqual(self.panel.current_motion["orders"]["s"].count("left_hand"), 1)


if __name__ == "__main__":
    unittest.main()

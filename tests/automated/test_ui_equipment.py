"""무장 표시 규격과 미리보기 입력 경계. Pico2D 창은 열지 않는다."""

from dataclasses import replace
from contextlib import nullcontext
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

from ferrial_drive.ui.state import LoadoutInfo, WeaponInfo
from ferrial_drive.ui.weapon_swap import WeaponSwap


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("equipment_ui_sample", ROOT / "tests/ui_test.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)


class EquipmentTests(unittest.TestCase):
    def test_invalid_ammo_and_loadout_selection_are_rejected(self):
        for rounds in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                WeaponInfo("기관단총", rounds)
        with self.assertRaises(ValueError):
            LoadoutInfo(WeaponInfo("카타나"), WeaponInfo("기관단총"))
        sample = SAMPLE.SampleHud(SAMPLE.SAMPLE_PATH)
        with self.assertRaises(ValueError):
            replace(sample.state, active_loadout_index=2)
        with self.assertRaises(ValueError):
            replace(sample.state, loadouts=sample.state.loadouts * 2)

    def test_switching_and_reset_preserve_per_loadout_ammo(self):
        sample = SAMPLE.SampleHud(SAMPLE.SAMPLE_PATH)
        original = sample.state.loadouts
        sample.switch_loadout()
        sample.switch_weapon()
        self.assertEqual(sample.state.active_loadout_index, 1)
        self.assertEqual(sample.state.active_weapon_kind, "melee")
        self.assertEqual(sample.state.loadouts, original)
        sample.switch_loadout()
        self.assertEqual(sample.state.active_loadout_index, 0)
        sample.reset()
        self.assertEqual(sample.state.active_weapon_kind, "ranged")

    def test_equipment_keys_are_blocked_in_menu_transition_and_pause(self):
        program = SAMPLE.UiTest()
        program.pico = SimpleNamespace(SDL_MOUSEMOTION=1, SDL_MOUSEBUTTONDOWN=2,
                                      SDL_MOUSEBUTTONUP=3, SDL_KEYDOWN=4,
                                      SDLK_ESCAPE=27, SDLK_e=101, SDLK_f=102,
                                      SDL_BUTTON_LEFT=1)
        event = SimpleNamespace(type=4, key=102, repeat=False)
        program.handle_event(event)
        self.assertEqual(program.sample.state.active_loadout_index, 0)
        program.change_scene("combat")
        program.handle_event(event)
        self.assertEqual(program.sample.state.active_loadout_index, 0)
        program.transition.update(1)
        program.handle_event(event)
        self.assertEqual(program.sample.state.active_loadout_index, 1)
        program.set_paused(True)
        program.pause.update(1)
        program.handle_event(event)
        self.assertEqual(program.sample.state.active_loadout_index, 1)
        program.handle_event(SimpleNamespace(type=4, key=101, repeat=False))
        self.assertEqual(program.sample.state.active_weapon_kind, "ranged")
        program.set_paused(False)
        program.pause.update(1)
        program.handle_event(SimpleNamespace(type=4, key=101, repeat=True))
        self.assertEqual(program.sample.state.active_weapon_kind, "ranged")
        program.handle_event(SimpleNamespace(type=4, key=101, repeat=False))
        self.assertEqual(program.sample.state.active_weapon_kind, "melee")
        self.assertEqual(program.sample.state.active_loadout_index, 1)

    def test_gun_name_image_and_ammo_placement_without_reserve(self):
        from ferrial_drive.ui.view import UiView

        class Recorder:
            def __init__(self):
                self.texts = []
                self.images = []

            def text(self, *args, **kwargs):
                self.texts.append(args)

            def text_size(self, text, role):
                return (89, 56) if role == "ammo_number" else (40, 17)

            def image(self, *args, **kwargs):
                self.images.append(args)

            def rect(self, *args, **kwargs):
                pass

            def line(self, *args):
                pass

            def metallic_rect(self, *args, **kwargs):
                pass

            def clip(self, rect):
                return nullcontext()

        program = SAMPLE.UiTest()
        state = program.sample.state
        loadout = LoadoutInfo(WeaponInfo("카타나", image_path="sword.png"),
                              WeaponInfo("시험 기관단총", 0, "test.png"))
        state = replace(state, loadouts=(loadout,))
        renderer = Recorder()
        UiView(program.config, renderer).equipment(state, 1, 0)
        name = next(item for item in renderer.texts if item[0] == "시험 기관단총")
        ammo = next(item for item in renderer.texts if item[3] == "ammo_number")
        image = next(item[1] for item in renderer.images if item[0] == "test.png")
        self.assertEqual(ammo[0], "0")
        self.assertLess(name[2], image.y)
        self.assertLess(image.x + image.width, ammo[1])
        large_card = program.config.layout["equipment_slots"]["active"]["panel"]
        self.assertEqual(ammo[2] + 56 / 2,
                         program.config.layout["equipment_panel"][1] + large_card[1] + large_card[3] / 2)
        self.assertFalse(any("∞" in item[0] or "/" in item[0] for item in renderer.texts))
        removed = {"잔탄", "사용 중", "E  로드아웃", "F  무기 전환"}
        self.assertFalse(any(item[0] in removed for item in renderer.texts))
        self.assertEqual(program.config.font_paths["ammo_number"].name, "SCDream5.otf")
        self.assertEqual(program.config.font_paths["equipment_number"].name, "SCDream5.otf")

        switched = Recorder()
        UiView(program.config, switched).equipment(replace(state, active_weapon_kind="melee"), 1, 0)
        small_gun = next(item[1] for item in switched.images if item[0] == "test.png")
        large_sword = next(item[1] for item in switched.images if item[0] == "sword.png")
        self.assertLess(small_gun.y, large_sword.y)
        self.assertLess(small_gun.width, image.width)
        self.assertGreater(large_sword.width, image.width)
        self.assertEqual(large_sword.x + large_sword.width,
                         program.config.layout["equipment_panel"][0] + large_card[0] + large_card[2] - 16)
        self.assertEqual(next(item[0] for item in switched.texts if item[3] == "ammo_number"), "0")
        small_ammo = next(item for item in switched.texts if item[3] == "ammo_number")
        small_card = program.config.layout["equipment_slots"]["inactive"]["panel"]
        self.assertEqual(small_ammo[2] + 56 * 0.5 / 2,
                         program.config.layout["equipment_panel"][1] + small_card[1] + small_card[3] / 2)
        triple_loadout = replace(loadout, ranged=replace(loadout.ranged, rounds=999))
        triple = Recorder()
        UiView(program.config, triple).equipment(replace(state, loadouts=(triple_loadout,)), 1, 0)
        ammo = next(item for item in triple.texts if item[3] == "ammo_number")
        gun = next(item[1] for item in triple.images if item[0] == "test.png")
        self.assertEqual(ammo[0], "999")
        # SCDream5 48px에서 세 자리 폭은 약 89px다. 실루엣과 16px 이상 분리한다.
        self.assertGreaterEqual(ammo[1] - 89 - (gun.x + gun.width), 16)

    def test_swap_holds_new_position_and_next_input_continues_same_orbit(self):
        swap = WeaponSwap("ranged", 0.24)
        swap.request("melee")
        swap.update(0.12)
        self.assertAlmostEqual(swap.ranged_weight, 0.5)
        self.assertEqual(swap.visual.orbit_direction, -1)
        swap.update(1)
        self.assertEqual(swap.ranged_weight, 0)
        swap.update(5)
        self.assertEqual(swap.ranged_weight, 0)
        swap.request("ranged")
        self.assertEqual(swap.ranged_weight, 0)
        self.assertEqual(swap.visual.orbit_direction, 1)
        swap.update(0.12)
        self.assertAlmostEqual(swap.ranged_weight, 0.5)
        swap.update(1)
        self.assertEqual(swap.ranged_weight, 1)
        swap.update(5)
        self.assertEqual(swap.ranged_weight, 1)

    def test_rapid_swap_is_queued_without_reversing_current_cycle(self):
        swap = WeaponSwap("ranged", 0.24)
        swap.request("melee")
        swap.update(0.12)
        swap.request("ranged")
        self.assertEqual(swap.visual.end_weight, 0)
        self.assertAlmostEqual(swap.ranged_weight, 0.5)
        swap.update(0.12)
        self.assertEqual(swap.ranged_weight, 0)
        self.assertEqual(swap.visual.orbit_direction, 1)
        swap.update(1)
        self.assertEqual(swap.ranged_weight, 1)

    def test_swap_is_frame_rate_independent(self):
        for fps in (30, 60, 144):
            swap = WeaponSwap("ranged", 1)
            swap.request("melee")
            for _ in range(fps // 2):
                swap.update(1 / fps)
            self.assertAlmostEqual(swap.ranged_weight, 0.5)

    def test_pause_freezes_swap_and_reset_removes_in_progress_motion(self):
        program = SAMPLE.UiTest()
        program.sample.switch_weapon()
        program.update(0.12)
        self.assertAlmostEqual(program.weapon_swap.ranged_weight, 0.5)
        program.set_paused(True)
        program.update(5)
        self.assertAlmostEqual(program.weapon_swap.ranged_weight, 0.5)
        program.set_paused(False)
        program.update(5)
        self.assertAlmostEqual(program.weapon_swap.ranged_weight, 0.5)
        program.update(0.12)
        self.assertEqual(program.weapon_swap.ranged_weight, 0)
        program.sample.switch_weapon()
        program.update(0.06)
        program.perform("reset")
        self.assertEqual(program.weapon_swap.ranged_weight, 1)
        self.assertEqual(program.sample.state.active_weapon_kind, "ranged")


if __name__ == "__main__":
    unittest.main()

"""로드아웃 경계 전환·방향 잔상·클리핑 복원을 창 없이 확인한다."""

from contextlib import contextmanager
from ctypes import Structure, c_int
from collections import OrderedDict
from types import SimpleNamespace
import importlib.util
from pathlib import Path
import unittest

from ferrial_drive.ui.components import Rect
from ferrial_drive.animation import ease_in_out_quint
from ferrial_drive.ui.loadout_slide import LoadoutSlide
from ferrial_drive.ui.pico_renderer import PicoRenderer
from ferrial_drive.ui.view import UiView
from ferrial_drive.ui.weapon_swap import WeaponSwap, diamond_offset


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("loadout_slide_sample", ROOT / "tests/ui_test.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)


class Recorder:
    def __init__(self):
        self.clips = []
        self.panels = []
        self.texts = []
        self.lines = []
        self.panel_styles = []
        self.silhouettes = []

    @contextmanager
    def clip(self, rect):
        self.clips.append(rect)
        yield

    def rect(self, *args, **kwargs):
        pass

    def line(self, *args):
        self.lines.append(args)

    def text(self, *args, **kwargs):
        self.texts.append(args)

    def text_size(self, text, role):
        return (89, 56) if role == "ammo_number" else (40, 17)

    def weapon_silhouette(self, *args):
        self.silhouettes.append(args)

    def metallic_rect(self, rect, *args, **kwargs):
        self.panels.append(rect)
        self.panel_styles.append(kwargs)


class LoadoutSlideTests(unittest.TestCase):
    def test_quint_applies_once_per_half_cycle_with_linear_clock(self):
        self.assertEqual(ease_in_out_quint(-1), 0)
        self.assertEqual(ease_in_out_quint(2), 1)
        slide = LoadoutSlide(0, 0.28)
        slide.request(1)
        slide.update(0.28 / 8)
        self.assertAlmostEqual(slide.visual.progress_before(), 0.125)
        shift, alpha, index = slide.visual.pose(320)
        self.assertAlmostEqual(shift, 5)
        self.assertAlmostEqual(alpha, 63 / 64)
        self.assertEqual(index, 0)
        slide.update(0.28 / 4)
        self.assertAlmostEqual(slide.visual.pose(320)[0], 315)
        slide.update(0.28 / 4)
        shift, alpha, index = slide.visual.pose(320)
        self.assertAlmostEqual(shift, 315)
        self.assertAlmostEqual(alpha, 1 / 64)
        self.assertEqual(index, 1)

    def test_queued_input_keeps_current_transition_and_ends_at_latest_selection(self):
        slide = LoadoutSlide(0, 0.28)
        slide.request(1)
        slide.update(0.14)
        self.assertAlmostEqual(slide.visual.progress_before(), 0.5)
        slide.request(0)
        self.assertEqual(slide.visual.incoming_index, 1)
        self.assertAlmostEqual(slide.visual.progress_before(), 0.5)
        slide.update(0.14)
        self.assertEqual((slide.visual.outgoing_index, slide.visual.incoming_index), (1, 0))
        self.assertEqual(slide.visual.progress_before(), 0)
        slide.update(1)
        self.assertFalse(slide.visual.moving)
        self.assertEqual(slide.visual.incoming_index, 0)

    def test_extra_switch_back_to_current_target_cancels_pending_transition(self):
        slide = LoadoutSlide(0, 0.28)
        slide.request(1)
        slide.update(0.1)
        slide.request(0)
        slide.request(1)
        slide.update(1)
        self.assertFalse(slide.visual.moving)
        self.assertEqual(slide.visual.incoming_index, 1)

    def test_group_transition_changes_loadout_only_while_fully_hidden(self):
        slide = LoadoutSlide(0, 0.28)
        slide.request(1)
        self.assertEqual(slide.visual.pose(320), (0, 1, 0))
        slide.update(0.14)
        self.assertEqual(slide.visual.pose(320), (320, 0, 1))
        slide.update(1)
        self.assertEqual(slide.visual.pose(320), (0, 1, 1))

    def test_loadout_numbers_change_selection_while_faded_out_beyond_screen_edge(self):
        slide = LoadoutSlide(0, 0.28)
        slide.request(1)
        self.assertEqual(slide.visual.pose(320), (0, 1, 0))
        slide.update(0.07)
        offset, opacity, index = slide.visual.pose(320)
        self.assertGreater(offset, 0)
        self.assertLess(opacity, 1)
        self.assertEqual(index, 0)
        slide.update(0.07)
        offset, opacity, index = slide.visual.pose(320)
        self.assertAlmostEqual(offset, 320)
        self.assertAlmostEqual(opacity, 0)
        self.assertGreater(972 + offset, 1280)
        self.assertEqual(index, 1)
        slide.update(1)
        self.assertEqual(slide.visual.pose(320), (0, 1, 1))

    def test_optional_image_projection_compresses_height_without_shrinking_width(self):
        class NativeRect(Structure):
            _fields_ = [(key, c_int) for key in ("x", "y", "w", "h")]

        copies = []

        def copy(renderer, texture, source, destination):
            copies.append(tuple(getattr(destination._obj, key) for key in ("x", "y", "w", "h")))

        renderer = PicoRenderer.__new__(PicoRenderer)
        renderer.pico = SimpleNamespace(renderer=object(), SDL_Rect=NativeRect,
                                       SDL_SetTextureAlphaMod=lambda *args: None, SDL_RenderCopy=copy)
        path = str((ROOT / "test-drum-icon.png").resolve())
        renderer.images = OrderedDict({path: ("texture", 200, 100)})
        renderer.image(path, Rect(10, 20, 100, 25), vertical_scale=0.5)
        renderer.image(path, Rect(10, 20, 100, 50))
        self.assertEqual(copies, [(10, 20, 100, 25), (10, 20, 100, 50)])

    def test_loadout_panels_and_numbers_share_offset_fade_and_keep_full_height(self):
        program = SAMPLE.UiTest()
        program.config.data["equipment_motion_blur"]["samples"] = 0
        renderer = Recorder()
        view = UiView(program.config, renderer)
        slide = LoadoutSlide(0, 0.28)
        slide.request(1)
        slide.update(0.07)
        layers = []
        view.equipment_loadout = lambda loadout, weight, x, y, alpha, **kw: layers.append(
            (loadout, x, y, alpha, kw.get("scale_y", 1)))
        view.equipment(program.sample.state, 1, 0, loadout_visual=slide.visual)
        panel_x, panel_y, width, height = program.config.layout["equipment_panel"]
        self.assertEqual(renderer.clips, [Rect(0, 0, 1280, 720)])
        for advance, expected_rounds in ((0, 45), (0.14, 18)):
            if advance:
                slide.update(advance)
                layers.clear()
                renderer.texts.clear()
                view.equipment(program.sample.state, 1, 0, loadout_visual=slide.visual)
            self.assertEqual(len(layers), 1)
            loadout, x, y, alpha, scale = layers[0]
            number = next(item for item in renderer.texts if item[3] == "equipment_number")
            self.assertAlmostEqual(x - panel_x, number[1] - (panel_x + width - 16 - 76 + 17))
            self.assertAlmostEqual(alpha, number[5])
            self.assertEqual((y, scale, loadout.ranged.rounds), (panel_y, 1, expected_rounds))

        program.config.data["equipment_motion_blur"]["samples"] = 5
        for elapsed, direction in ((0.07, -1), (0.21, 1)):
            motion = LoadoutSlide(0, 0.28)
            motion.request(1)
            motion.update(elapsed)
            layers.clear()
            view.equipment(program.sample.state, 1, 0, loadout_visual=motion.visual)
            self.assertEqual(len(layers), 6)
            for layer in layers[:-1]:
                delta = layer[1] - layers[-1][1]
                self.assertGreaterEqual(delta * direction, 0)
                self.assertLessEqual(abs(delta), 28.000001)

    def test_weapon_cards_follow_opposite_diamond_sides_without_screen_clipping(self):
        program = SAMPLE.UiTest()
        renderer = Recorder()
        view = UiView(program.config, renderer)
        view.equipment(program.sample.state, 1, 0, ranged_weight=0.5)
        melee, ranged = renderer.panels
        self.assertLess(melee.x + melee.width / 2, ranged.x + ranged.width / 2)
        for panel in renderer.panels:
            self.assertGreaterEqual(panel.x, 0)
            self.assertLessEqual(panel.x + panel.width, 1280 - 8)
        self.assertEqual(diamond_offset("melee", 0, 64, 44), 0)
        self.assertEqual(diamond_offset("ranged", 1, 64, 44), 0)
        self.assertLess(diamond_offset("melee", 0.5, 64, 44), 0)
        self.assertGreater(diamond_offset("ranged", 0.5, 64, 44), 0)
        for kind in ("melee", "ranged"):
            self.assertAlmostEqual(diamond_offset(kind, 0.25, 64, 44) * 2,
                                   diamond_offset(kind, 0.5, 64, 44))
            self.assertAlmostEqual(diamond_offset(kind, 0.5, 64, 44, 1) + 44,
                                   -(diamond_offset(kind, 0.5, 64, 44, -1) + 44))

    def test_vertical_swap_trails_follow_opposite_directions_and_stop_at_rest(self):
        program = SAMPLE.UiTest()
        renderer = Recorder()
        view = UiView(program.config, renderer)
        swap = WeaponSwap("ranged", 0.24)
        swap.request("melee")
        swap.update(0.12)
        layers = []
        view.equipment_weapon = lambda weapon, kind, weight, x, y, alpha, **kw: layers.append((kind, weight))
        view.equipment(program.sample.state, 1, 0, swap_visual=swap.visual)
        for kind, weight in layers[:-2]:
            if kind == "melee":
                self.assertLess(weight, 0.5)
            else:
                self.assertGreater(weight, 0.5)
        swap.update(1)
        layers.clear()
        view.equipment(program.sample.state, 1, 0, swap_visual=swap.visual)
        self.assertEqual(len(layers), 2)

    def test_idle_weapon_cards_are_independent_and_debug_buttons_do_not_overlap(self):
        program = SAMPLE.UiTest()
        renderer = Recorder()
        UiView(program.config, renderer).equipment(program.sample.state, 1, 0)
        self.assertEqual(len(renderer.panels), 2)
        first, second = sorted(renderer.panels, key=lambda rect: rect.y)
        self.assertLess(first.y + first.height, second.y)
        self.assertLess(first.height, second.height)
        self.assertLess(first.width, second.width / 2)
        self.assertEqual(first.x + first.width, second.x + second.width)
        self.assertEqual(renderer.panel_styles[0]["corner_cut_ratio"],
                         renderer.panel_styles[1]["corner_cut_ratio"])
        self.assertTrue(all(value > 0 for value in renderer.panel_styles[0]["corner_cut_ratio"]))
        number = next(item for item in renderer.texts if item[3] == "equipment_number")
        self.assertEqual(number[2], program.config.layout["equipment_panel"][1] + 3)
        self.assertTrue(any(line[0] != line[2] and line[1] != line[3] for line in renderer.lines))
        for button in program.config.buttons["combat"]:
            self.assertLessEqual(button.rect.x + button.rect.width, first.x)

    def test_pause_freezes_both_motions_and_reset_clears_old_loadout(self):
        program = SAMPLE.UiTest()
        program.sample.switch_weapon()
        program.sample.switch_loadout()
        program.update(0.1)
        weight = program.weapon_swap.ranged_weight
        progress = program.loadout_slide.visual.progress_before()
        program.set_paused(True)
        program.update(5)
        program.set_paused(False)
        program.update(5)
        self.assertEqual(program.weapon_swap.ranged_weight, weight)
        self.assertEqual(program.loadout_slide.visual.progress_before(), progress)
        program.perform("reset")
        self.assertFalse(program.loadout_slide.visual.moving)
        self.assertEqual(program.loadout_slide.visual.incoming_index, 0)
        self.assertEqual(program.weapon_swap.ranged_weight, 1)

    def test_native_clip_intersects_nested_regions_and_restores_after_exception(self):
        class NativeRect(Structure):
            _fields_ = [(key, c_int) for key in ("x", "y", "w", "h")]

        class FakeSdl:
            SDL_Rect = NativeRect
            renderer = object()
            region = None

            def SDL_RenderIsClipEnabled(self, renderer):
                return self.region is not None

            def SDL_RenderGetClipRect(self, renderer, pointer):
                for key, value in zip(("x", "y", "w", "h"), self.region or (0, 0, 0, 0)):
                    setattr(pointer._obj, key, value)

            def SDL_RenderSetClipRect(self, renderer, pointer):
                self.region = None if pointer is None else tuple(
                    getattr(pointer._obj, key) for key in ("x", "y", "w", "h"))
                return 0

        renderer = PicoRenderer.__new__(PicoRenderer)
        renderer.pico = FakeSdl()
        with self.assertRaisesRegex(RuntimeError, "stop"):
            with renderer.clip(Rect(10, 20, 100, 80)):
                with renderer.clip(Rect(50, 60, 100, 80)):
                    self.assertEqual(renderer.pico.region, (50, 60, 60, 40))
                self.assertEqual(renderer.pico.region, (10, 20, 100, 80))
                raise RuntimeError("stop")
        self.assertIsNone(renderer.pico.region)


if __name__ == "__main__":
    unittest.main()

"""디버그 버튼의 시간 경계·숨김 입력·정지 상태를 창 없이 확인한다."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

from ferrial_drive.ui.auto_hide import AutoHidePanel
from ferrial_drive.ui.components import Button, ButtonInput, Rect


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("debug_toolbar_sample", ROOT / "tests/ui_test.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)


class DebugToolbarTests(unittest.TestCase):
    def program(self):
        program = SAMPLE.UiTest()
        program.pico = SimpleNamespace(SDL_MOUSEMOTION=1, SDL_MOUSEBUTTONDOWN=2,
                                      SDL_MOUSEBUTTONUP=3, SDL_KEYDOWN=4,
                                      SDLK_ESCAPE=27, SDLK_e=101, SDLK_f=102,
                                      SDL_BUTTON_LEFT=1, SDL_WINDOWEVENT=5,
                                      SDL_WINDOWEVENT_LEAVE=6, SDL_WINDOWEVENT_FOCUS_LOST=7)
        program.change_scene("combat")
        program.transition.update(1)
        return program

    def test_starts_hidden_and_waits_one_second_after_leaving(self):
        panel = AutoHidePanel(1, 0.2, 24)
        self.assertEqual(panel.opacity, 0)
        self.assertFalse(panel.interactive)
        panel.update(0.1, True)
        self.assertAlmostEqual(panel.opacity, 0.5)
        self.assertAlmostEqual(panel.offset_y, 12)
        self.assertFalse(panel.interactive)
        panel.update(0.1, True)
        self.assertTrue(panel.interactive)
        panel.update(1, False)
        self.assertEqual(panel.opacity, 1)
        self.assertFalse(panel.interactive)
        panel.update(0.1, False)
        self.assertAlmostEqual(panel.opacity, 0.5)
        panel.update(0.1, False)
        self.assertEqual(panel.opacity, 0)

    def test_hover_keeps_visible_and_reentry_reverses_without_jump(self):
        panel = AutoHidePanel(1, 0.2, 24)
        panel.update(10, True)
        self.assertTrue(panel.interactive)
        panel.update(1.1, False)
        opacity = panel.opacity
        self.assertAlmostEqual(opacity, 0.5)
        panel.update(0, True)
        self.assertEqual(panel.opacity, opacity)
        panel.update(0.2, True)
        self.assertTrue(panel.interactive)
        panel.update(3, False)
        self.assertEqual(panel.opacity, 0)

    def test_hidden_and_transitioning_buttons_do_not_apply_damage(self):
        program = self.program()

        def click():
            for kind in (2, 3):
                program.handle_event(SimpleNamespace(type=kind, button=1, x=120, y=680))

        initial_hp = program.sample.state.target.health.current
        click()
        self.assertEqual(program.sample.state.target.health.current, initial_hp)
        program.update(0.1)
        click()
        self.assertEqual(program.sample.state.target.health.current, initial_hp)
        program.update(0.1)
        click()
        self.assertEqual(program.sample.state.target.health.current, initial_hp - 120)
        program.mouse = (500, 300)
        program.update(1.1)
        click()
        self.assertEqual(program.sample.state.target.health.current, initial_hp - 120)

    def test_drag_capture_keeps_buttons_visible(self):
        program = self.program()
        program.mouse = (120, 680)
        program.update(0.2)
        program.handle_event(SimpleNamespace(type=2, button=1, x=120, y=680))
        program.handle_event(SimpleNamespace(type=1, x=500, y=300))
        program.update(5)
        self.assertTrue(program.debug_toolbar.interactive)
        program.handle_event(SimpleNamespace(type=3, button=1, x=500, y=300))
        program.update(1.2)
        self.assertEqual(program.debug_toolbar.opacity, 0)

    def test_pause_freezes_timeout_and_scene_change_resets_toolbar(self):
        program = self.program()
        program.mouse = (120, 680)
        program.update(0.2)
        program.mouse = (500, 300)
        program.update(0.5)
        program.set_paused(True)
        program.update(5)
        self.assertEqual(program.debug_toolbar.remaining_seconds, 0.5)
        program.set_paused(False)
        program.update(5)
        self.assertEqual(program.debug_toolbar.remaining_seconds, 0.5)
        program.update(0.6)
        self.assertAlmostEqual(program.debug_toolbar.opacity, 0.5)
        program.change_scene("menu")
        self.assertEqual(program.debug_toolbar.opacity, 0)

    def test_window_leave_cancels_capture_and_starts_timeout(self):
        program = self.program()
        program.mouse = (120, 680)
        program.update(0.2)
        program.inputs.pressed_id = "damage_target"
        program.handle_event(SimpleNamespace(type=5, window_event=6))
        self.assertIsNone(program.inputs.pressed_id)
        self.assertEqual(program.mouse, (-1, -1))
        program.update(3)
        self.assertEqual(program.debug_toolbar.opacity, 0)

    def test_button_hit_uses_both_transition_offsets(self):
        button = Button("test", "run", "버튼", Rect(20, 40, 100, 30))
        inputs = ButtonInput()
        self.assertFalse(inputs.handle("down", 80, 50, [button], 50, 24).consumed)
        self.assertTrue(inputs.handle("down", 80, 75, [button], 50, 24).consumed)
        self.assertEqual(inputs.handle("up", 80, 75, [button], 50, 24).action, "run")


if __name__ == "__main__":
    unittest.main()

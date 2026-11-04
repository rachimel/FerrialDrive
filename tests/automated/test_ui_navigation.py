"""타이틀·전투·일시정지의 ESC 경로와 전환 중 입력 경계."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("navigation_ui_sample", ROOT / "tests/ui_test.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.program = SAMPLE.UiTest()
        self.program.pico = SimpleNamespace(
            SDL_MOUSEMOTION=1, SDL_MOUSEBUTTONDOWN=2, SDL_MOUSEBUTTONUP=3,
            SDL_KEYDOWN=4, SDLK_ESCAPE=27, SDL_BUTTON_LEFT=1, SDLK_e=101, SDLK_f=102)

    def escape(self, *, repeat=False):
        self.program.handle_event(SimpleNamespace(type=4, key=27, repeat=repeat))

    def enter_combat(self):
        self.program.perform("show_hud")
        self.program.update(1)

    def test_initial_title_ignores_escape_and_button_still_enters_combat(self):
        for repeat in (False, True):
            self.escape(repeat=repeat)
            self.assertEqual(self.program.transition.target, "menu")
            self.assertFalse(self.program.transition.active)
            self.assertFalse(self.program.pause.blocking)
        self.enter_combat()
        self.assertEqual(self.program.transition.target, "combat")
        self.assertFalse(self.program.transition.active)

    def test_escape_pauses_and_resumes_without_repeat_or_fade_bounce(self):
        self.enter_combat()
        self.program.perform("damage_target")
        self.program.update(0.01)
        self.escape()
        self.escape()
        self.assertTrue(self.program.pause.opened)
        self.program.update(1)
        held_time = self.program.counter_visibility.elapsed_seconds
        self.escape(repeat=True)
        self.assertTrue(self.program.pause.opened)
        self.program.update(1)
        self.assertEqual(self.program.counter_visibility.elapsed_seconds, held_time)
        self.escape()
        self.assertFalse(self.program.pause.opened)
        self.assertTrue(self.program.pause.transitioning)
        self.escape()
        self.program.update(1)
        self.assertFalse(self.program.pause.blocking)
        self.assertEqual(self.program.transition.target, "combat")
        self.assertEqual(self.program.counter_visibility.elapsed_seconds, held_time)
        self.program.update(0.01)
        self.assertGreater(self.program.counter_visibility.elapsed_seconds, held_time)

    def test_returned_title_does_not_resume_combat_on_escape(self):
        self.enter_combat()
        self.program.perform("damage_target")
        state = self.program.sample.state
        self.escape()
        self.program.update(1)
        self.program.perform("show_menu")
        self.escape()
        self.program.update(1)
        self.escape()
        self.assertEqual(self.program.transition.target, "menu")
        self.assertFalse(self.program.transition.active)
        self.assertFalse(self.program.pause.blocking)
        self.assertEqual(self.program.sample.state.player_health, state.player_health)
        self.assertEqual(self.program.sample.state.target, state.target)
        self.enter_combat()
        self.assertFalse(self.program.pause.blocking)


if __name__ == "__main__":
    unittest.main()

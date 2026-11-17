"""아코디언 메뉴의 표시·판정 동기화와 빠른 재선택을 확인한다."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from ferrial_drive.continuation import ContinueSession
from ferrial_drive.ui.components import ButtonInput
from ferrial_drive.ui_v2.preview import HudPreview

ROOT = Path(__file__).resolve().parents[2]


class TitleMenuTests(unittest.TestCase):
    def setUp(self):
        self.preview = HudPreview(initial_scene="menu", settings_file=ROOT / "output/ui_review/title_settings.json")

    def test_start_pushes_remaining_rows_and_closing_restores_positions(self):
        before = self.preview.config.buttons["menu"]
        self.preview.perform("toggle_start")
        self.preview.update(.2)
        after = self.preview.config.buttons["menu"]
        self.assertEqual(after[0].rect, before[0].rect)
        self.assertEqual(after[1].rect, before[1].rect)
        for previous, current in zip(before[2:], after[2:5]):
            self.assertEqual(current.rect.y - previous.rect.y, 144)
        self.assertEqual([button.label for button in after[-2:]], ["NEW GAME", "SURVIVAL"])
        self.preview.perform("toggle_start")
        self.preview.update(.2)
        self.assertEqual(self.preview.config.buttons["menu"], before)

    def test_rapid_toggle_reverses_from_current_expansion(self):
        self.preview.perform("toggle_start")
        self.preview.update(.08)
        previous = self.preview.title_menu_motion.expansion
        self.preview.perform("toggle_start")
        self.assertEqual(self.preview.title_menu_motion.expansion, previous)
        self.preview.update(.2)
        self.assertEqual(self.preview.title_menu_motion.expansion, 0)

    def test_hover_tracking_reverses_without_changing_click_rect(self):
        motion = self.preview.title_menu_motion
        before = motion.buttons[0].rect
        motion.update(.09, "start")
        halfway = motion.hover_amounts["start"]
        self.assertGreater(halfway, .9)
        self.assertLess(halfway, 1)
        motion.update(0, None)
        self.assertEqual(motion.hover_amounts["start"], halfway)
        motion.update(.18, None)
        self.assertEqual(motion.hover_amounts["start"], 0)
        self.assertEqual(motion.buttons[0].rect, before)

    def test_hover_replays_the_same_curve_backward_and_reenters_continuously(self):
        motion = self.preview.title_menu_motion
        motion.update(.03, "start")
        first = motion.hover_amounts["start"]
        motion.update(.03, "start")
        second = motion.hover_amounts["start"]
        motion.update(0, None)
        self.assertEqual(motion.hover_amounts["start"], second)
        motion.update(.03, None)
        self.assertAlmostEqual(motion.hover_amounts["start"], first)
        motion.update(0, "start")
        self.assertAlmostEqual(motion.hover_amounts["start"], first)
        motion.update(.03, "start")
        self.assertAlmostEqual(motion.hover_amounts["start"], second)
        motion.update(1, "start")
        self.assertEqual(motion.hover_amounts["start"], 1)
        motion.update(1, "load")
        self.assertEqual(motion.hover_amounts["start"], 0)
        self.assertEqual(motion.hover_amounts["load"], 0)

    def test_unimplemented_items_are_disabled_and_config_uses_moved_hit_box(self):
        self.preview.perform("toggle_start")
        self.preview.update(.2)
        buttons = self.preview.config.buttons["menu"]
        inputs = ButtonInput()
        for button in buttons:
            x, y = button.rect.x + 20, button.rect.y + 20
            inputs.handle("down", x, y, buttons)
            result = inputs.handle("up", x, y, buttons)
            if button.button_id in ("load", "new_game", "survival"):
                self.assertFalse(button.enabled)
                self.assertIsNone(result.action)
            elif button.action == "settings":
                self.assertEqual(result.action, "settings")

    def test_settings_freezes_expansion_and_reset_collapses_menu(self):
        self.preview.perform("toggle_start")
        self.preview.update(.08)
        before = self.preview.title_menu_motion.expansion
        self.preview.perform("settings")
        self.preview.update(1)
        self.assertEqual(self.preview.title_menu_motion.expansion, before)
        self.preview.graphics_settings.cancel()
        self.preview.perform("reset")
        self.assertEqual(self.preview.title_menu_motion.expansion, 0)

    def test_training_title_pointer_opens_start_and_reflowed_config(self):
        import pico2d.pico2d as pico
        from ferrial_drive.combat.movement_application import MovementApplication
        from ferrial_drive.ui_v2.movement_hud import MovementHud

        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", mute=True)
        app.pico = pico
        app.hud = MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json",
                              ROOT / "samples/ui_unit_test_v2/hud_sample.json")
        app.hud.scene = "menu"
        app.hud.transition.update(1)
        start = next(button for button in app.hud.config.buttons["menu"] if button.action == "toggle_start")
        for kind in (pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP):
            app.handle_event(SimpleNamespace(type=kind, button=pico.SDL_BUTTON_LEFT,
                                             x=start.rect.x + 20, y=start.rect.y + 20))
        self.assertTrue(app.hud.title_menu_motion.opened)
        app.update(.1)
        app.update(.1)
        self.assertEqual(app.hud.title_menu_motion.expansion, 1)
        button = next(button for button in app.hud.config.buttons["menu"] if button.action == "settings")
        for kind in (pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP):
            app.handle_event(SimpleNamespace(type=kind, button=pico.SDL_BUTTON_LEFT,
                                             x=button.rect.x + 20, y=button.rect.y + 20))
        self.assertTrue(app.hud.graphics_settings.opened)

    def test_continue_returns_to_test_without_resetting_state(self):
        preview = self.preview
        preview.transition.update(1)
        preview.perform("show_hud")
        preview.transition.update(1)
        preview.perform("damage_player", damage_amount=17)
        before = preview.state
        preview.perform("show_menu")
        preview.transition.update(1)
        button = next(button for button in preview.config.buttons["menu"] if button.action == "continue")
        self.assertTrue(button.enabled)
        preview.perform("continue")
        self.assertEqual(preview.transition.target, "combat")
        self.assertEqual(preview.state, before)

    def test_game_continue_loads_last_save_once_before_transition(self):
        loader = Mock(return_value=True)
        available = Mock(return_value=True)
        preview = HudPreview(initial_scene="menu", continuation=ContinueSession(
            mode="game", has_last_save=available, load_last_save=loader))
        preview.transition.update(1)
        def load():
            self.assertEqual(preview.transition.target, "menu")
            return True
        loader.side_effect = load
        preview.perform("continue")
        preview.perform("continue")
        loader.assert_called_once_with()
        self.assertEqual(preview.transition.target, "combat")

    def test_game_without_save_or_failed_load_remains_on_title(self):
        for exists in (False, True):
            loader = Mock(return_value=False)
            preview = HudPreview(initial_scene="menu", continuation=ContinueSession(
                mode="game", has_last_save=lambda: exists, load_last_save=loader))
            preview.transition.update(1)
            button = next(button for button in preview.config.buttons["menu"] if button.action == "continue")
            self.assertEqual(button.enabled, exists)
            preview.perform("continue")
            self.assertEqual(preview.transition.target, "menu")
            self.assertEqual(loader.call_count, int(exists))
        preview = HudPreview(initial_scene="menu", continuation=ContinueSession(mode="game"))
        self.assertFalse(next(button for button in preview.config.buttons["menu"]
                              if button.action == "continue").enabled)

    def test_game_rechecks_save_at_click_and_when_returning_to_title(self):
        loader = Mock(return_value=True)
        availability = {"value": True}
        preview = HudPreview(initial_scene="menu", continuation=ContinueSession(
            mode="game", has_last_save=lambda: availability["value"], load_last_save=loader))
        preview.transition.update(1)
        availability["value"] = False
        preview.perform("continue")
        loader.assert_not_called()
        self.assertEqual(preview.transition.target, "menu")
        self.assertFalse(next(button for button in preview.config.buttons["menu"]
                              if button.action == "continue").enabled)
        availability["value"] = True
        preview.perform("show_menu")
        self.assertTrue(next(button for button in preview.config.buttons["menu"]
                             if button.action == "continue").enabled)


if __name__ == "__main__":
    unittest.main()

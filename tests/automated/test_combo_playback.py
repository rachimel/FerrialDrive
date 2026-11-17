"""프레임 재생·클릭 연계·예약 한도·Idle 복귀 경계를 검사한다."""
from types import SimpleNamespace
import unittest

from ferrial_drive.assets.combo import ComboPlayback
from ferrial_drive.assets.directional import DirectionalPlayback, SCREEN_DIRECTIONS
from ferrial_drive.assets.sprites import SpriteClip, SpriteFrame
from ferrial_drive.ui_v2.preview import HudPreview


def combo_clips():
    return {f"combo_{index:02}/{direction}": SpriteClip(12, tuple(
        SpriteFrame((0, 0, 10, 10), (5, 5)) for _ in range(count)))
        for index, count in enumerate((6, 6, 6, 8), 1) for direction in SCREEN_DIRECTIONS}


class ComboPlaybackTests(unittest.TestCase):
    def test_each_click_advances_and_waiting_uses_exact_next_entry(self):
        player = ComboPlayback(combo_clips())
        for index, duration in enumerate((0.5, 0.5, 0.5, 8 / 12)):
            player.request("w" if index == 0 else "e")
            self.assertEqual(player.clip_name, f"combo_{index+1:02}/w")
            player.update(duration - 0.01)
            self.assertEqual(player.frame_index, (6 if index < 3 else 8) - 1)
            player.update(0.01)
            if index < 3:
                self.assertTrue(player.waiting_for_input)
                self.assertEqual(player.clip_name, f"combo_{index+2:02}/w")
                self.assertEqual(player.frame_index, 0)
                player.update(10)
                self.assertTrue(player.waiting_for_input)
        self.assertFalse(player.active)

    def test_repeated_early_clicks_reserve_only_one_strike(self):
        player = ComboPlayback(combo_clips())
        player.request("n")
        for _ in range(20):
            player.request("s")
        player.update(0.6)
        self.assertEqual(player.attack_index, 1)
        self.assertAlmostEqual(player.elapsed_seconds, 0.1)
        player.update(1)
        self.assertTrue(player.waiting_for_input)
        self.assertEqual(player.attack_index, 1)
        self.assertEqual(player.direction, "n")

    def test_clear_and_reset_drop_the_buffer(self):
        player = ComboPlayback(combo_clips())
        player.request("se")
        player.request("se")
        player.clear_buffer()
        player.update(0.5)
        self.assertTrue(player.waiting_for_input)
        player.reset()
        self.assertFalse(player.active)
        self.assertFalse(player.queued)
        for delta in (-1, float("nan")):
            with self.assertRaises(ValueError):
                player.update(delta)

    def test_ui_left_click_is_blocked_in_pause_and_menu(self):
        program = HudPreview(initial_scene="combat")
        frame = SpriteFrame((0, 0, 10, 10), (5, 5))
        program.player_idle = DirectionalPlayback({f"equipped_idle/{d}": SpriteClip(12, (frame,))
                                                   for d in SCREEN_DIRECTIONS})
        program.player_combo = ComboPlayback(combo_clips())
        program.pico = SimpleNamespace(SDL_WINDOWEVENT=1, SDL_KEYDOWN=2, SDL_MOUSEMOTION=3,
                                       SDL_MOUSEBUTTONDOWN=4, SDL_MOUSEBUTTONUP=5,
                                       SDL_BUTTON_LEFT=1, SDL_BUTTON_RIGHT=3)
        event = SimpleNamespace(type=4, button=1, x=900, y=360)
        program.handle_event(event)
        self.assertTrue(program.player_combo.active)
        elapsed = program.player_combo.elapsed_seconds
        program.pause.request(True)
        program.update(0.1)
        self.assertEqual(program.player_combo.elapsed_seconds, elapsed)
        program.player_combo.reset()
        program.handle_event(event)
        self.assertFalse(program.player_combo.active)
        program.perform("show_menu")
        program.handle_event(event)
        self.assertFalse(program.player_combo.active)


if __name__ == "__main__":
    unittest.main()

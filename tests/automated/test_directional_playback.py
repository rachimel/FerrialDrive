"""방향 전환 중 재생 위상과 UI 일시정지·초기화를 확인한다."""

import importlib.util
from pathlib import Path
import unittest

from ferrial_drive.assets.directional import DirectionalPlayback, SCREEN_DIRECTIONS
from ferrial_drive.assets.sprites import SpriteClip, SpriteFrame


ROOT = Path(__file__).resolve().parents[2]


def sample_playback():
    frames = tuple(SpriteFrame((i, 0, 1, 1), (0, 0)) for i in range(12))
    return DirectionalPlayback({f"equipped_idle/{direction}": SpriteClip(12, frames)
                                for direction in SCREEN_DIRECTIONS})


class DirectionalPlaybackTests(unittest.TestCase):
    def test_all_screen_directions_and_zero_vector(self):
        playback = sample_playback()
        for dx, dy, expected in ((1, 0, "e"), (1, 1, "se"), (0, 1, "s"), (-1, 1, "sw"),
                                 (-1, 0, "w"), (-1, -1, "nw"), (0, -1, "n"), (1, -1, "ne")):
            playback.face(dx, dy)
            self.assertEqual(playback.direction, expected)
        playback.face(0, 0)
        self.assertEqual(playback.direction, "ne")

    def test_turning_preserves_phase_and_loop(self):
        playback = sample_playback()
        playback.update(0.25)
        self.assertEqual(playback.frame_index, 3)
        playback.face(-1, 0)
        self.assertEqual((playback.clip_name, playback.frame_index), ("equipped_idle/w", 3))
        playback.update(0.75)
        self.assertEqual(playback.frame_index, 0)
        playback.reset()
        self.assertEqual((playback.direction, playback.elapsed_seconds), ("se", 0))

    def test_invalid_time_and_incomplete_directions_are_rejected(self):
        playback = sample_playback()
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                playback.update(value)
        with self.assertRaises(ValueError):
            playback.face(float("inf"), 0)
        with self.assertRaises(ValueError):
            DirectionalPlayback({})

    def test_ui_v2_updates_mouse_facing_and_freezes_during_pause(self):
        spec = importlib.util.spec_from_file_location("ui_v2_idle_sample", ROOT / "ferrial_drive/ui_v2/preview.py")
        sample = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sample)
        program = sample.create_preview()
        program.player_idle = sample_playback()
        x, y = program.camera.world_to_screen(program.player_world)
        program.mouse = (x + 400, y)
        program.update(0.25)
        self.assertEqual((program.player_idle.direction, program.player_idle.frame_index), ("e", 3))
        program.pause.request(True)
        program.update(0.5)
        self.assertEqual(program.player_idle.elapsed_seconds, 0.25)
        program.reset()
        self.assertEqual((program.player_idle.direction, program.player_idle.elapsed_seconds), ("se", 0))


if __name__ == "__main__":
    unittest.main()

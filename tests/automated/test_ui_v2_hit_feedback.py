"""피격 오프셋 상한·독립 수명·고정 흡수 경로·거리 기반 필압을 검사한다."""

from contextlib import nullcontext
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("feedback_ui_sample", ROOT / "tests/ui_unit_test_v2.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)

from ferrial_drive.ui_v2.effects import HealthHitMotion, HealthHitVisual
from ferrial_drive.ui_v2.geometry import resource_geometry
from ferrial_drive.ui_v2.view import UiV2View


class HealthHitTests(unittest.TestCase):
    def test_offsets_stay_within_screen_limits_and_repeated_hits_do_not_stack(self):
        motion = HealthHitMotion(max_offset_pixels=(0, 4))
        self.assertEqual(motion.visual, HealthHitVisual())
        for frame in range(1200):
            if frame % 71 == 0:
                motion.trigger()
            motion.update(1 / 1000)
            x, y = motion.visual.offset_pixels
            self.assertEqual(x, 0)
            self.assertLessEqual(abs(y), 4)
        motion.update(1)
        self.assertEqual(motion.visual, HealthHitVisual())

    def test_velocity_matches_offset_and_timing_is_independent_of_frame_steps(self):
        motion = HealthHitMotion()
        motion.trigger()
        motion.update(0.063)
        before = motion.visual
        epsilon = 1e-7
        motion.update(epsilon)
        derivative = (motion.visual.offset_pixels[1] - before.offset_pixels[1]) / epsilon
        self.assertAlmostEqual(derivative, before.velocity_pixels_per_second[1], delta=0.01)
        other = HealthHitMotion()
        other.trigger()
        for _ in range(63):
            other.update(0.001)
        self.assertAlmostEqual(other.visual.offset_pixels[1], before.offset_pixels[1])

    def test_damage_pause_target_switch_zero_damage_and_reset(self):
        program = SAMPLE.UiUnitTestV2(initial_scene="combat")
        program.perform("damage_target")
        self.assertEqual(program.particle_system.commands[0].count, 6)
        self.assertEqual(program.target_hit.elapsed_seconds, 0)
        self.assertEqual(program.player_hit.visual, HealthHitVisual())
        program.perform("damage_player")
        program.update(0.02)
        player, target = program.player_hit.visual, program.target_hit.visual
        program.pause.request(True)
        program.update(0.1)
        self.assertEqual(program.player_hit.visual, player)
        self.assertEqual(program.target_hit.visual, target)
        program.apply_target("enemy_b")
        self.assertEqual(program.target_hit.visual, HealthHitVisual())
        self.assertEqual(program.player_hit.visual, player)
        program.reset()
        self.assertEqual(program.player_hit.visual, HealthHitVisual())
        self.assertFalse(program.particle_system.commands)
        program.set_hud(player_health=replace(program.state.hud.player_health, current=0))
        program.perform("damage_player")
        self.assertEqual(program.player_hit.visual, HealthHitVisual())

    def test_player_offset_is_screen_pixels_and_only_hp_moves(self):
        program = SAMPLE.UiUnitTestV2(initial_scene="combat")
        renderer = Mock()
        renderer.text_size.return_value = (20, 18)
        renderer.directional_blur.side_effect = lambda *args: nullcontext()
        view = UiV2View(program.config, renderer)
        geometry = resource_geometry(view.layout, view.style["level_bevel_pixels"])
        with patch.object(view, "meter") as meter:
            view.player_health(program.state.hud, geometry, 1, 1, (), HealthHitVisual((0, 4), (0, 500)))
        shifted = meter.call_args.kwargs["shape"]
        for old, new in zip(geometry.hp_shape, shifted):
            self.assertEqual(old[0], new[0])
            self.assertAlmostEqual((new[1] - old[1]) * view.style["hud_scale"], 4)
        blur = renderer.directional_blur.call_args.args[1]
        self.assertEqual(blur[0], 0)
        self.assertAlmostEqual(blur[1] * view.style["hud_scale"], view.style['player_health_blur']['max_length_pixels'])
        self.assertEqual(geometry, resource_geometry(view.layout, view.style["level_bevel_pixels"]))




if __name__ == "__main__":
    unittest.main()

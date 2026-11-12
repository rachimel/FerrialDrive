"""피격 오프셋 상한·독립 수명·고정 흡수 경로·거리 기반 필압을 검사한다."""

from contextlib import nullcontext
from dataclasses import replace
import importlib.util
from math import hypot
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("feedback_ui_sample", ROOT / "tests/ui_unit_test_v2.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)

from ferrial_drive.ui_v2.effects import EnergyAbsorption, HealthHitMotion, HealthHitVisual
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
        self.assertEqual(len(program.absorption.trails), 3)
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
        self.assertFalse(program.absorption.trails)
        program.set_hud(player_health=replace(program.state.hud.player_health, current=0))
        program.perform("damage_player")
        self.assertEqual(program.player_hit.visual, HealthHitVisual())

    def test_player_offset_is_screen_pixels_and_only_hp_moves(self):
        program = SAMPLE.UiUnitTestV2(initial_scene="combat")
        renderer = Mock()
        renderer.text_size.return_value = (20, 18)
        renderer.directional_blur.side_effect = lambda *args: nullcontext()
        view = UiV2View(program.config, renderer)
        geometry = resource_geometry(view.layout, view.style["level_curve_radius_pixels"])
        with patch.object(view, "meter") as meter:
            view.player_health(program.state.hud, geometry, 1, 1, (), HealthHitVisual((0, 4), (0, 500)))
        shifted = meter.call_args.kwargs["shape"]
        for old, new in zip(geometry.hp_shape, shifted):
            self.assertEqual(old[0], new[0])
            self.assertAlmostEqual((new[1] - old[1]) * view.style["hud_scale"], 4)
        blur = renderer.directional_blur.call_args.args[1]
        self.assertEqual(blur[0], 0)
        self.assertAlmostEqual(blur[1] * view.style["hud_scale"], 3)
        self.assertEqual(geometry, resource_geometry(view.layout, view.style["level_curve_radius_pixels"]))


class AbsorptionRouteTests(unittest.TestCase):
    def make_effect(self):
        return EnergyAbsorption(1, seed=51)

    def test_paths_vary_between_orbs_stay_fixed_and_keep_all_endpoints(self):
        effect = self.make_effect()
        self.assertEqual({side: len(paths) for side, paths in effect.routes.items()}, {-1: 6, 1: 6})
        for _ in range(12):
            effect.add((650, 350), (320, 620), (650, 650))
        routes = {trail.point(0.35) for trail in effect.trails}
        self.assertGreater(len(routes), 3)
        for trail in effect.trails:
            self.assertIn(trail.route_offsets, effect.routes[-1])
            self.assertEqual(trail.point(0), trail.start)
            self.assertEqual(trail.point(0.72), trail.icon)
            self.assertEqual(trail.point(1), trail.destination)
            saved = trail.point(0.35)
            effect.update(0.001)
            self.assertEqual(trail.point(0.35), saved)
            self.assertLessEqual(max(abs(v) for point in trail.route_offsets for v in point), 70)
        repeated = self.make_effect()
        repeated.add((650, 350), (320, 620), (650, 650))
        self.assertEqual(effect.trails[0].route_offsets, repeated.trails[0].route_offsets)

    def test_pen_pressure_increases_with_distance_along_tail_toward_orb(self):
        effect = self.make_effect()
        effect.add((650, 350), (320, 620), (650, 650))
        trail = effect.trails[0]
        trail.elapsed_seconds = 0.5
        ribbon = trail.ribbon()
        self.assertEqual(ribbon[0][1], 0)
        self.assertEqual(ribbon[-1][1], 1)
        self.assertEqual(ribbon[-1][0], trail.point(trail.progress))
        distances = [0]
        for a, b in zip(ribbon, ribbon[1:]):
            self.assertLessEqual(a[1], b[1])
            distances.append(distances[-1] + hypot(b[0][0] - a[0][0], b[0][1] - a[0][1]))
        for (_, pressure), distance in zip(ribbon, distances):
            self.assertAlmostEqual(pressure, (distance / distances[-1]) ** 1.5)
        trail.elapsed_seconds = 1.15
        self.assertAlmostEqual(trail.ribbon()[-1][1], 0.5)
        trail.elapsed_seconds = 1.3
        self.assertFalse(trail.ribbon())

    def test_zero_hp_does_not_spawn_more_orbs_and_effect_count_is_bounded(self):
        program = SAMPLE.UiUnitTestV2(initial_scene="combat")
        for _ in range(100):
            program.perform("damage_target")
        self.assertGreater(len(program.absorption.trails), 0)
        self.assertLessEqual(len(program.absorption.trails), 24)
        old = tuple(program.absorption.trails)
        program.perform("damage_target")
        self.assertEqual(tuple(program.absorption.trails), old)
        for _ in range(100):
            program.absorb()
        self.assertEqual(len(program.absorption.trails), 24)

    def test_right_enemy_uses_right_waypoint_and_enters_bar_from_right(self):
        program = SAMPLE.UiUnitTestV2(initial_scene="combat")
        program.apply_target("enemy_b")
        program.perform("damage_target")
        trail = program.absorption.trails[1]
        self.assertEqual(trail.approach_side, 1)
        self.assertGreater(trail.icon[0], program.camera.world_to_screen(program.player_world)[0])
        self.assertGreater(trail.point(0.95)[0], trail.destination[0])
        self.assertEqual(trail.point(1), trail.destination)
        program.apply_target("enemy_a")
        program.perform("damage_target")
        self.assertEqual(program.absorption.trails[-1].approach_side, -1)


if __name__ == "__main__":
    unittest.main()

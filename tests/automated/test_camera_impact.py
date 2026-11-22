"""명중 충격의 상한·시간 독립성과 조준·HUD·훈련장 연결을 검사한다."""

from math import hypot
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.combat.camera_impact import CameraImpact
from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.combat.movement_application import MovementApplication
from ferrial_drive.combat.sword_effects import SwordTarget
from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.ui_v2.movement_hud import MovementHud


ROOT = Path(__file__).resolve().parents[2]


class CameraImpactTests(unittest.TestCase):
    def test_direction_bound_decay_and_frame_step_independence(self):
        impact = CameraImpact()
        impact.trigger(1, (3, 4))
        self.assertAlmostEqual(hypot(*impact.offset_pixels), 3)
        self.assertGreater(impact.offset_pixels[0], 0)
        self.assertGreater(impact.offset_pixels[1], 0)
        reference = CameraImpact()
        reference.trigger(1, (3, 4))
        reference.update(0.04)
        for _ in range(40):
            impact.update(0.001)
            self.assertLessEqual(hypot(*impact.offset_pixels), 3)
        for a, b in zip(impact.offset_pixels, reference.offset_pixels):
            self.assertAlmostEqual(a, b)
        self.assertLess(impact.offset_pixels[0], 0)
        impact.update(0.1)
        self.assertEqual(impact.offset_pixels, (0, 0))
        impact.trigger(2, (1, 0))
        for _ in range(6):
            impact.update(1 / 60)
        self.assertEqual(impact.offset_pixels, (0, 0))

    def test_same_strike_does_not_restart_and_next_strike_does_not_stack(self):
        impact = CameraImpact()
        impact.trigger(7, (1, 0))
        impact.update(0.04)
        before = impact.offset_pixels
        impact.trigger(7, (0, 1))
        self.assertEqual(impact.offset_pixels, before)
        impact.update(1)
        impact.trigger(7, (1, 0))
        self.assertEqual(impact.offset_pixels, (0, 0))
        for strike_id in range(8, 100):
            impact.trigger(strike_id, (1, 1))
            self.assertAlmostEqual(hypot(*impact.offset_pixels), 3)
        impact.reset()
        impact.trigger(7, (1, 0))
        self.assertEqual(impact.offset_pixels, (3, 0))

    def test_disabled_and_invalid_settings(self):
        for options in ({"enabled": False}, {"amplitude_pixels": 0}):
            impact = CameraImpact(**options)
            impact.trigger(1, (1, 0))
            self.assertEqual(impact.offset_pixels, (0, 0))
        for options in ({"amplitude_pixels": -1}, {"duration_seconds": 0}, {"duration_seconds": float("nan")},
                        {"overdrive_amplitude_pixels": -1}, {"overdrive_amplitude_pixels": float("nan")},
                        {"frequency_hz": 0}, {"frequency_hz": float("inf")},
                        {"damping": -1}, {"damping": float("nan")}):
            with self.assertRaises(ValueError):
                CameraImpact(**options)
        with self.assertRaises(ValueError):
            CameraImpact().update(-0.01)

    def test_damped_rebounds_shrink_and_settle_smoothly(self):
        impact = CameraImpact(amplitude_pixels=16, duration_seconds=.2, frequency_hz=12, damping=1.8)
        impact.trigger(1, (1, 0))
        rebounds = []
        for _ in range(4):
            impact.update(1 / 24)
            rebounds.append(impact.offset_pixels[0])
        self.assertLess(rebounds[0], 0)
        self.assertGreater(rebounds[1], 0)
        self.assertLess(rebounds[2], 0)
        self.assertGreater(rebounds[3], 0)
        self.assertTrue(all(abs(a) > abs(b) for a, b in zip([16] + rebounds, rebounds)))
        impact.update(.2 - impact.elapsed_seconds - .0001)
        self.assertLess(hypot(*impact.offset_pixels), .00001)
        impact.update(.0001)
        self.assertEqual(impact.offset_pixels, (0, 0))

    def test_overdrive_amplitude_is_fixed_at_hit_and_never_stacks(self):
        impact = CameraImpact(amplitude_pixels=16, overdrive_amplitude_pixels=24)
        impact.trigger(1, (3, 4))
        self.assertAlmostEqual(hypot(*impact.offset_pixels), 16)
        impact.trigger(1, (3, 4), overdrive=True)
        self.assertAlmostEqual(hypot(*impact.offset_pixels), 16)
        impact.trigger(2, (3, 4), overdrive=True)
        self.assertAlmostEqual(hypot(*impact.offset_pixels), 24)
        impact.trigger(3, (3, 4))
        self.assertAlmostEqual(hypot(*impact.offset_pixels), 16)

    def test_visual_inverse_and_stable_aim_across_zoom_levels(self):
        camera = LookAheadCamera(1920, 1080)
        camera.reset((200, 300))
        for zoom in (1, 0.9, 0.85):
            camera.update((200, 300), None, 0.3, target_zoom=zoom)
            before = camera.position, camera.velocity_pixels_per_second
            point = (600, 400)
            base = camera.world_to_screen(point, include_feedback=False)
            stable_aim = camera.screen_to_world((1100, 500), include_feedback=False)
            camera.feedback_offset_pixels = (1.8, 2.4)
            shown = camera.world_to_screen(point)
            self.assertAlmostEqual(shown[0] - base[0], 1.8)
            self.assertAlmostEqual(shown[1] - base[1], 2.4)
            for a, b in zip(camera.screen_to_world(shown), point):
                self.assertAlmostEqual(a, b)
            self.assertEqual(camera.screen_to_world((1100, 500), include_feedback=False), stable_aim)
            self.assertEqual((camera.position, camera.velocity_pixels_per_second), before)
        camera.reset((200, 300))
        self.assertEqual(camera.feedback_offset_pixels, (0, 0))


class CameraImpactIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        self.hud = MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json",
                               ROOT / "samples/ui_unit_test_v2/hud_sample.json")
        self.app.hud = self.hud
        origin = Vec2(*self.app.projection.project(self.app.controller.position_m))
        self.app.sword_targets = [SwordTarget("A", origin + Vec2(100, -50), 26),
                                  SwordTarget("B", origin + Vec2(130, -50), 26)]
        self.app.target_hits = {"A": 0, "B": 0}
        self.app.playback = Mock()
        self.app.current_energy_color = Mock(return_value="#9DDFEA")
        section = SimpleNamespace(strike_id=1, tip_a=origin + Vec2(90, -50), tip_b=origin + Vec2(120, -50))
        self.app.sword_effects = SimpleNamespace(hits=[], sections=[section], update=Mock(), reset=Mock())
        self.app.bind_hud_world()

    def test_dash_kicks_at_launch_and_shift_transition_without_repeating(self):
        app = self.app
        app.keys.add("d")
        app.update(1 / 60)
        weak_kick = app.camera.feedback_offset_pixels[0]
        self.assertAlmostEqual(weak_kick, -app.dash_camera_kick.amplitude_pixels * .65)
        self.assertEqual(app.camera.feedback_offset_pixels[1], 0)
        app.update(1 / 60)
        self.assertGreater(app.camera.feedback_offset_pixels[0], weak_kick)

        app.keys.add("left_shift")
        app.update(1 / 60)
        strong_kick = -app.dash_camera_kick.amplitude_pixels
        self.assertAlmostEqual(app.camera.feedback_offset_pixels[0], strong_kick)
        app.trigger_camera_hit(1, "A")
        self.assertAlmostEqual(app.camera.feedback_offset_pixels[0], strong_kick + app.camera_impact.amplitude_pixels)
        app.keys.remove("left_shift")
        app.update(1 / 60)
        self.assertAlmostEqual(app.dash_camera_kick.elapsed_seconds, 1 / 60)
        app.reset()
        self.assertEqual(app.dash_camera_kick.offset_pixels, (0, 0))

    def test_only_live_actual_hits_trigger_once_and_pause_reset_work(self):
        self.app.update(1 / 60)
        self.assertEqual(self.app.camera.feedback_offset_pixels, (0, 0))
        self.app.perform_hud_action("damage_target")
        self.assertEqual(self.app.camera.feedback_offset_pixels, (0, 0))
        self.app.sword_effects.hits = [(1, "A"), (1, "B")]
        self.app.update(1 / 60)
        self.assertEqual(self.app.camera.feedback_offset_pixels, (self.app.camera_impact.amplitude_pixels, 0))
        self.app.sword_effects.hits = []
        self.app.update(0.04)
        before = self.app.camera.feedback_offset_pixels
        self.app.paused = True
        self.app.update(0.5)
        self.assertEqual(self.app.camera.feedback_offset_pixels, before)
        self.app.paused = False
        self.app.reset()
        self.assertEqual(self.app.camera.feedback_offset_pixels, (0, 0))
        self.assertEqual(self.app.camera_impact.offset_pixels, (0, 0))
        self.app.bind_hud_world()
        self.hud.damage_target("A", 100000)
        self.app.trigger_camera_hit(2, "A")
        self.assertEqual(self.app.camera.feedback_offset_pixels, (0, 0))

    def test_aim_selection_target_health_and_popup_follow_correct_coordinates(self):
        target = self.app.sword_targets[0]
        self.app.mouse = self.app.camera.world_to_screen((target.center.x, target.center.y))
        self.app.bind_hud_world()
        self.hud.update_world_view(0)
        self.hud.update_world_view(1.1)
        aim = self.app.aim()
        selected = self.hud.selected_target_id
        before = self.hud.state.target_body
        self.app.trigger_camera_hit(1, "A")
        self.assertEqual(self.app.aim(), aim)
        self.hud.update_world_view(0)
        self.assertEqual(self.hud.selected_target_id, selected)
        after = self.hud.state.target_body
        self.assertEqual((after.x - before.x, after.y - before.y), (self.app.camera_impact.amplitude_pixels, 0))
        self.hud.damage_target("A")
        self.hud.damage_numbers.update(.1)
        self.hud.view = Mock()
        self.hud.draw_layers(actors=False)
        args, kwargs = self.hud.view.combat.call_args
        popup = self.hud.damage_numbers.visuals[0]
        displayed = args[1][0]
        self.assertEqual((displayed.x, displayed.y), self.app.camera.world_to_screen((popup.x, popup.y)))
        self.assertEqual(kwargs["player_screen"],
                         self.app.camera.world_to_screen(self.hud.player_world, include_feedback=False))

    def test_overdrive_hit_uses_configured_amplitude_with_unscaled_damping_time(self):
        self.hud.set_energy_charge(EnergyCharge(4))
        self.hud.perform("activate_overdrive")
        self.app.sword_effects.hits = [(1, "A"), (1, "B")]
        self.app.update(1 / 60)
        self.assertEqual(self.app.camera.feedback_offset_pixels, (self.app.camera_impact.overdrive_amplitude_pixels, 0))
        self.app.sword_effects.hits = []
        self.app.update(.04)
        self.assertAlmostEqual(self.app.camera_impact.elapsed_seconds, .04)
        offset = self.app.camera.feedback_offset_pixels
        self.hud.perform("overdrive")
        self.assertFalse(self.hud.state.overdrive)
        self.app.update(0)
        self.assertEqual(self.app.camera.feedback_offset_pixels, offset)
        self.app.update(.1)
        self.app.update(.06)
        self.assertEqual(self.app.camera.feedback_offset_pixels, (0, 0))
        self.app.trigger_camera_hit(2, "A")
        self.assertAlmostEqual(hypot(*self.app.camera.feedback_offset_pixels), self.app.camera_impact.amplitude_pixels)


if __name__ == "__main__":
    unittest.main()

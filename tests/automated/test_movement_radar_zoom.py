"""레이더 상태 전환·일시정지와 줌 중 조준 좌표·복귀를 검사한다."""

from pathlib import Path
import unittest
from unittest.mock import Mock

from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.combat.movement_application import MovementApplication
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.state import RadarContact
from ferrial_drive.ui.view import UiView
from ferrial_drive.ui_v2.movement_hud import MovementHud
from ferrial_drive.ui_v2.radar import RadarMotion


ROOT = Path(__file__).resolve().parents[2]
UI_CONFIG = ROOT / "samples/ui_unit_test_v2/ui_config.json"


class RadarZoomTests(unittest.TestCase):
    def setUp(self):
        self.config = UiConfig(UI_CONFIG)
        self.motion = RadarMotion(self.config.data["radar"]["motion"])

    def test_state_sizes_use_enlarged_idle_radius_and_recover(self):
        radius = self.config.data["radar"]["radius_pixels"]
        self.assertEqual(radius, 260)
        for state, scale, solid in (("run", .9, 0), ("dash", .75, 1), ("boost", .7, 1), ("idle", 1, 0)):
            self.motion.update(state, .21)
            self.assertAlmostEqual(radius * self.motion.scale.value, radius * scale)
            self.assertEqual(self.motion.solid_ratio.value, solid)

    def test_transition_restarts_from_current_value_without_jump_and_is_bounded(self):
        self.motion.update("dash", .1)
        self.assertAlmostEqual(self.motion.scale.value, .875)
        self.assertAlmostEqual(self.motion.solid_ratio.value, .5)
        self.motion.update("boost", 0)
        self.assertAlmostEqual(self.motion.scale.value, .875)
        self.motion.update("boost", .1)
        self.assertGreater(self.motion.scale.value, .7)
        self.assertLess(self.motion.scale.value, .875)
        self.motion.update("idle", .3)
        self.assertEqual(self.motion.scale.value, 1)
        self.assertEqual(self.motion.solid_ratio.value, 0)

    def test_transition_duration_is_independent_of_frame_rate(self):
        for fps in (30, 60, 120):
            motion = RadarMotion(self.config.data["radar"]["motion"])
            for _ in range(fps // 10):
                motion.update("dash", 1 / fps)
            self.assertAlmostEqual(motion.scale.value, .875)

    def test_dashing_ring_and_distant_arrows_are_opaque_but_scene_fade_remains(self):
        renderer = Mock()
        view = UiView(self.config, renderer)
        contact = RadarContact(.8, 0, 1600, 540)
        view.radar((contact,), .7, center=(960, 540), scale=.75, solid_ratio=1)
        self.assertAlmostEqual(renderer.ring.call_args.args[2], 260 * .75)
        self.assertEqual(renderer.ring.call_args.args[-1], .7)
        self.assertEqual(renderer.filled_triangle.call_args.args[-1], .7)
        view.radar((contact,), 1, center=(960, 540))
        self.assertEqual(renderer.ring.call_args.args[-1], .4)
        self.assertLess(renderer.filled_triangle.call_args.args[-1], 1)

    def test_pause_and_reset_preserve_motion_contract(self):
        hud = MovementHud(UI_CONFIG, ROOT / "samples/ui_unit_test_v2/hud_sample.json")
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        app.controller.state = "dash"
        hud.update(app.controller, .1, paused=False, interpolation=False)
        before = hud.state.radar_scale, hud.state.radar_solid_ratio
        hud.update(app.controller, .5, paused=True, interpolation=False)
        self.assertEqual((hud.state.radar_scale, hud.state.radar_solid_ratio), before)
        hud.reset_training()
        self.assertEqual(hud.state.radar_scale, 1)
        self.assertEqual(hud.state.radar_solid_ratio, 0)

    def test_zoom_changes_screen_distance_and_keeps_mouse_world_inverse(self):
        camera = LookAheadCamera(1920, 1080)
        camera.reset((3000, 4000))
        for target in (.9, .85, 1):
            camera.update((3000, 4000), None, .21, target_zoom=target)
            point = (3200, 3900)
            screen = camera.world_to_screen(point)
            self.assertAlmostEqual(screen[0] - 960, 200 * target)
            for expected, actual in zip(point, camera.screen_to_world(screen)):
                self.assertAlmostEqual(expected, actual)
        camera.reset((3000, 4000))
        self.assertEqual(camera.zoom, 1)

    def test_zoom_retarget_has_no_position_jump_at_zero_time(self):
        camera = LookAheadCamera(1920, 1080)
        camera.update((0, 0), None, .1, target_zoom=.9)
        self.assertAlmostEqual(camera.zoom, .95)
        screen = camera.world_to_screen((400, 100))
        camera.update((0, 0), None, 0, target_zoom=.85)
        self.assertEqual(camera.world_to_screen((400, 100)), screen)
        camera.update((0, 0), None, .21, target_zoom=.85)
        self.assertEqual(camera.zoom, .85)

    def test_invalid_zoom_is_rejected(self):
        for zoom in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                LookAheadCamera(1920, 1080).update((0, 0), None, .1, target_zoom=zoom)

    def test_application_uses_configured_zoom_and_freezes_when_paused(self):
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        app.playback = Mock()
        app.controller.update = Mock()
        app.controller.state = "dash"
        app.controller.strong_dash = True
        app.keys = {"d", "left_shift"}
        for _ in range(3):
            app.update(.1)
        self.assertEqual(app.camera.zoom, .9)
        app.controller.state = "boost"
        app.update(.1)
        before = app.camera.zoom
        app.paused = True
        app.update(.5)
        self.assertEqual(app.camera.zoom, before)
        app.paused = False
        for _ in range(3):
            app.update(.1)
        self.assertEqual(app.camera.zoom, .85)
        app.controller.state = "idle"
        for _ in range(3):
            app.update(.1)
        self.assertEqual(app.camera.zoom, 1)


if __name__ == "__main__":
    unittest.main()

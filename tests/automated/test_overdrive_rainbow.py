"""무지개 순환·공유 팔레트·일시정지·원복과 독립 실행 경계를 확인한다."""

from copy import deepcopy
from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock, patch

from ferrial_drive.combat.movement_application import MovementApplication
from ferrial_drive.rendering.overdrive_palette import rainbow_color
from ferrial_drive.ui.theme import widget_colors
from ferrial_drive.ui_v2.movement_hud import MovementHud
from ferrial_drive.ui_v2.view import UiV2View


ROOT = Path(__file__).resolve().parents[2]


class OverdriveRainbowTests(unittest.TestCase):
    def make_app(self, enabled=True):
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True,
                                  overdrive_rainbow=enabled)
        app.hud = MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json",
                              ROOT / "samples/ui_unit_test_v2/hud_sample.json")
        app.hud.view = UiV2View(app.hud.config, Mock())
        app.playback = Mock()
        app.bind_hud_world()
        return app

    def test_full_cycle_is_continuous_periodic_and_uses_real_seconds(self):
        self.assertEqual(rainbow_color(0), "#FF3333")
        self.assertEqual(rainbow_color(1), "#33FF33")
        self.assertEqual(rainbow_color(2), "#3333FF")
        self.assertEqual(rainbow_color(3), rainbow_color(0))
        self.assertEqual(rainbow_color(0.5), rainbow_color(3.5))
        for elapsed, period in ((-1, 3), (0, 0), (float("nan"), 3), (0, float("inf"))):
            with self.assertRaises(ValueError):
                rainbow_color(elapsed, period)

    def test_rim_trail_hud_and_glow_share_hue_without_mutating_config(self):
        app = self.make_app()
        before = deepcopy(app.config), deepcopy(app.hud.config.data), dict(app.hud.config.colors)
        app.perform_hud_action("overdrive")
        for _ in range(10):
            app.update(0.1)
        self.assertEqual(app.overdrive_color, rainbow_color(1))
        self.assertEqual(app.current_energy_color(), app.overdrive_color)
        self.assertEqual(app.hud.view.level_energy_color(3, 1), app.overdrive_color)
        rim = app.current_rim_light()
        self.assertEqual(tuple(round(value * 255) for value in rim[:3]), (51, 255, 51))
        view = app.hud.view
        view.overdrive_palette = True
        with widget_colors(view, "global"):
            accent = view.config.colors["ui_accent"]
            self.assertGreater(int(accent[3:5], 16), int(accent[1:3], 16))
            self.assertEqual(view.config.colors["energy"], before[2]["energy"])
        self.assertEqual(app.config, before[0])
        self.assertEqual(app.hud.config.data, before[1])
        self.assertEqual(app.hud.config.colors, before[2])

    def test_pause_freezes_color_and_expiry_reset_and_cancellation_restore(self):
        app = self.make_app()
        app.perform_hud_action("overdrive")
        app.update(0.1)
        before = app.overdrive_color, app.hud.state.overdrive_remaining_seconds
        app.paused = True
        app.update(0.5)
        self.assertEqual((app.overdrive_color, app.hud.state.overdrive_remaining_seconds), before)
        app.paused = False
        app.hud.pause.reset()
        app.update_hud(app.hud.state.overdrive_remaining_seconds)
        self.assertIsNone(app.overdrive_color)
        self.assertIsNone(app.hud.view.overdrive_color)
        self.assertEqual(app.current_rim_light()[3], 0)
        app.perform_hud_action("overdrive")
        self.assertEqual(app.overdrive_color, rainbow_color(0))
        app.perform_hud_action("overdrive")
        self.assertIsNone(app.overdrive_color)
        app.perform_hud_action("overdrive")
        app.reset()
        self.assertIsNone(app.overdrive_color)
        self.assertIsNone(app.hud.view.overdrive_color)

    def test_normal_entry_preserves_red_overdrive(self):
        app = self.make_app(False)
        app.perform_hud_action("overdrive")
        app.update(0.1)
        self.assertIsNone(app.overdrive_color)
        self.assertEqual(app.current_energy_color(), "#FF4044")

    def test_runner_entry_is_import_safe_and_passes_rainbow_default(self):
        entry = ROOT / "tests/overdrive_rainbow_test.py"
        with patch("ferrial_drive.combat.movement_launcher.launch_movement_test") as launch:
            namespace = runpy.run_path(str(entry), run_name="rainbow_import_check")
            launch.assert_not_called()
            self.assertEqual(namespace["UNIT_TEST_ENTRYPOINT"], "standalone")
            namespace["main"]()
            self.assertTrue(launch.call_args.kwargs["overdrive_rainbow"])
        from Tools.unit_test_runner.processes import prepare_test
        plan = prepare_test(entry)
        self.assertIn(str(entry), plan.command)
        self.assertNotIn("worker.py", " ".join(plan.command))


if __name__ == "__main__":
    unittest.main()

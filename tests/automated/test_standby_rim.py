"""Standby 림의 호흡 범위·주기와 정지를 검사한다."""

import unittest
from ferrial_drive.rendering.rim_light import standby_rim
from ferrial_drive.combat.movement_application import MovementApplication
from pathlib import Path


class StandbyRimTests(unittest.TestCase):
    def test_standby_trail_is_redder_without_changing_energy_color(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from ferrial_drive.ui_v2.movement_hud import MovementHud
        from ferrial_drive.ui_v2.view import UiV2View

        root = Path(__file__).resolve().parents[2]
        app = MovementApplication(root / "samples/sword_movement/movement_config.json", demo=True)
        app.hud = MovementHud(root / "samples/ui_unit_test_v2/ui_config.json",
                              root / "samples/ui_unit_test_v2/hud_sample.json")
        app.hud.view = UiV2View(app.hud.config, Mock())
        self.assertEqual(app.current_trail_color(), app.current_energy_color())
        app.hud.state = replace(app.hud.state, energy_level=3, overdrive=False,
                                overdrive_charge_ratio=1, overdrive_standby_seconds=3)
        energy_before = app.current_energy_color()
        trail = app.current_trail_color()
        rgb = tuple(int(trail[index:index + 2], 16) for index in (1, 3, 5))
        self.assertGreater(rgb[0], max(rgb[1:]))
        self.assertEqual(app.current_energy_color(), energy_before)
        app.hud.state = replace(app.hud.state, overdrive=True, overdrive_standby_seconds=0)
        self.assertEqual(app.current_trail_color(), app.current_energy_color())

    def test_red_pulse_keeps_strong_floor_and_repeats(self):
        high = standby_rim({}, 0, True)
        low = standby_rim({}, 0.9, True)
        self.assertGreater(high[0], high[1])
        self.assertGreater(high[0], high[2])
        self.assertEqual(high[3], 1)
        self.assertAlmostEqual(low[3], 0.65)
        self.assertEqual(high, standby_rim({}, 1.8, True))
        self.assertEqual(standby_rim({}, 0, False)[3], 0)

    def test_pause_freezes_breath_and_leaving_standby_resets(self):
        from ferrial_drive.ui_v2.movement_hud import MovementHud
        root = Path(__file__).resolve().parents[2]
        app = MovementApplication(root / 'samples/sword_movement/movement_config.json', demo=True)
        app.hud = MovementHud(root / 'samples/ui_unit_test_v2/ui_config.json',
                              root / 'samples/ui_unit_test_v2/hud_sample.json')
        app.hud.perform('overdrive')
        app.update_hud(0.2)
        self.assertGreater(app.rim_elapsed_seconds, 0)
        before = app.rim_elapsed_seconds
        app.paused = True
        app.update_hud(0.2)
        self.assertEqual(app.rim_elapsed_seconds, before)
        app.hud.perform('overdrive')
        app.update_hud(0)
        self.assertEqual(app.rim_elapsed_seconds, 0)

"""도착별 에너지 반영·처치 퇴장·자원 UI 묶음 진동과 아래쪽 경유를 검사한다."""

from contextlib import contextmanager
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('energy_ui_sample', ROOT / 'tests/ui_unit_test_v2.py')
SAMPLE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SAMPLE)

from ferrial_drive.ui_v2.effects import HealthHitVisual
from ferrial_drive.ui_v2.view import UiV2View
from ferrial_drive.ui.energy import EnergyCharge, energy_color


class EnergyFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.program = SAMPLE.UiUnitTestV2(initial_scene='combat')

    def test_six_particles_route_below_bar_without_ultimate_icon(self):
        for target_id, side in (('enemy_a', -1), ('enemy_b', 1)):
            self.program.apply_target(target_id)
            self.program.absorb()
            command = self.program.particle_system.commands[-1]
            channel, left, right = self.program.energy_geometry()
            self.assertEqual(command.count, 6)
            self.assertEqual(command.gain_units, 100000)
            self.assertEqual(command.side, side)
            self.assertGreater(command.waypoint[1], max(point[1] for point in channel))
            self.assertTrue(left[0] < command.waypoint[0] < right[0])
            self.assertGreater(command.arrival_spacing_seconds, 0)

    def test_recovery_waits_for_receipts_splits_amount_and_flashes(self):
        before = self.program.state.energy_ratio
        self.program.perform('energy_up')
        self.assertEqual(self.program.state.energy_ratio, before)
        self.program.particle_system.accept_receipt(16667, 1, 0)
        self.program.update(0)
        self.assertAlmostEqual(self.program.state.energy_ratio, before + 0.016667)
        self.assertEqual(self.program.energy_flash.opacity, 1)
        self.program.particle_system.accept_receipt(100000, 6, 0)
        self.program.update(0)
        self.assertAlmostEqual(self.program.state.energy_ratio, before + 0.1)
        self.program.particle_system.accept_receipt(100000, 6, 0)
        self.program.update(0)
        self.assertAlmostEqual(self.program.state.energy_ratio, before + 0.1)

    def test_death_hp_fade_and_marker_survive_immediate_selection_change(self):
        self.program.lock_motion.update(1)
        for _ in range(20):
            self.program.perform('damage_target')
        self.assertEqual(self.program.state.hud.target.health.current, 0)
        self.assertEqual(len(self.program.defeated_targets.visuals), 1)
        self.program.apply_target('enemy_b')
        self.program.lock_motion.update(0.08)
        self.program.defeated_targets.update(0.08)
        ghost = self.program.defeated_targets.visuals[0]
        marker = next(visual for visual in self.program.lock_motion.visuals if visual.target_id == 'enemy_a')
        self.assertTrue(0 < ghost.opacity < 1)
        self.assertGreater(marker.scale, 1)
        self.assertGreater(marker.angle_degrees, 45)
        self.assertEqual(marker.offset_pixels, (0, 0))
        self.program.lock_motion.update(1)
        self.program.defeated_targets.update(1)
        self.assertFalse(self.program.defeated_targets.visuals)
        self.assertFalse(any(v.target_id == 'enemy_a' for v in self.program.lock_motion.visuals))

    def test_nonfatal_hit_pulses_marker_and_returns_to_its_normal_pose(self):
        self.program.lock_motion.update(1)
        self.program.perform('damage_target')
        self.assertGreater(self.program.state.hud.target.health.current, 0)
        self.program.lock_motion.update(0.06)
        marker = next(v for v in self.program.lock_motion.visuals if v.target_id == 'enemy_a')
        self.assertTrue(1 < marker.scale <= 1.12)
        self.assertNotEqual(marker.offset_pixels, (0, 0))
        self.assertLessEqual(max(map(abs, marker.offset_pixels)), 1.5)
        self.assertFalse(self.program.defeated_targets.visuals)
        self.program.lock_motion.update(1)
        marker = next(v for v in self.program.lock_motion.visuals if v.target_id == 'enemy_a')
        self.assertEqual(marker.scale, 1)
        self.assertEqual(marker.offset_pixels, (0, 0))

    def test_resource_contents_share_translation_while_dash_stays_fixed(self):
        renderer = Mock()
        active = []
        @contextmanager
        def translated(dx, dy):
            active.append((dx, dy))
            yield
            active.pop()
        renderer.translated.side_effect = translated
        view = UiV2View(self.program.config, renderer)
        def contents(*args, **kwargs):
            self.assertTrue(active)
            self.assertAlmostEqual(active[0][1] * view.style['hud_scale'], 4)
            self.assertEqual(kwargs['hit_visual'].offset_pixels, (0, 0))
        def dash(*args):
            self.assertFalse(active)
        with patch.object(view, '_resource_contents', side_effect=contents) as body, \
                patch.object(view, 'dash_indicator', side_effect=dash):
            view.resources(self.program.state, 1, 0, 1, hit_visual=HealthHitVisual((0, 4)))
            body.assert_called_once()

    def test_pause_freezes_death_and_flash_and_recovery_clamps_to_full(self):
        self.program.state = replace(self.program.state, energy_ratio=0.99)
        self.program.particle_system.accept_receipt(100000, 6, 0)
        self.program.update(0)
        self.assertEqual(self.program.state.energy_ratio, 1)
        self.program.energy_flash.trigger()
        self.program.pause.request(True)
        self.program.update(0.5)
        self.assertEqual(self.program.energy_flash.opacity, 1)

    def test_level_rolls_and_overdrive_requires_one_more_full_charge(self):
        self.program.set_energy_charge(EnergyCharge(0.99))
        self.program.particle_system.accept_receipt(20000, 1, 0)
        self.program.update(0)
        self.assertEqual(self.program.state.energy_level, 2)
        self.assertAlmostEqual(self.program.state.energy_ratio, 0.01)
        self.assertTrue(self.program.level_counter.visual.moving)
        self.assertEqual(self.program.hit_counter.vertical_easing, 'elastic_in_out')
        self.assertLess(self.program.hit_counter.duration_seconds, 0.2)
        self.program.set_energy_charge(EnergyCharge(3))
        self.assertFalse(self.program.state.overdrive)
        self.assertEqual(self.program.state.energy_ratio, 1)
        self.assertEqual(self.program.particle_system.energy_target[-1], 0)
        self.program.set_energy_charge(EnergyCharge(3.5))
        self.assertEqual(self.program.state.overdrive_charge_ratio, 0.5)
        self.assertFalse(self.program.state.overdrive)
        self.program.set_energy_charge(EnergyCharge(4))
        self.assertTrue(self.program.state.overdrive)
        self.assertEqual(self.program.state.overdrive_charge_ratio, 1)

    def test_red_tint_is_shared_by_bar_and_particles(self):
        style, colors = self.program.config.data['v2']['style'], self.program.config.colors
        self.program.set_energy_charge(EnergyCharge(3.5))
        middle = energy_color(colors['energy'], style['overdrive_red'], 0.5)
        self.assertNotEqual(middle, colors['energy'])
        renderer = Mock()
        renderer.text_size.side_effect = lambda text, role: (len(text) * 10, 18)
        view = UiV2View(self.program.config, renderer)
        with patch.object(view, 'polygon') as polygon:
            view.resources(self.program.state, 1, 0, 1)
        self.assertTrue(any(call.args[1] == middle for call in polygon.call_args_list))
        view.absorption((), 1, self.program.particle_system, 0.5)
        self.assertEqual(renderer.draw_compute_particles.call_args.args[2], middle)
        self.assertEqual(energy_color(colors['energy'], style['overdrive_red'], 1), '#FF4044')

    def test_selection_exit_preserves_live_health_then_fades(self):
        old = self.program.selected_target_id
        ratio = self.program.state.hud.target.health.ratio
        self.program.apply_target('enemy_b')
        ghost = next(v for v in self.program.defeated_targets.visuals if v.target_id == old)
        self.assertEqual(ghost.current_ratio, ratio)
        self.program.defeated_targets.update(0.16)
        self.assertTrue(0 < self.program.defeated_targets.visuals[0].opacity < 1)
        self.program.defeated_targets.update(0.2)
        self.assertFalse(self.program.defeated_targets.visuals)


if __name__ == '__main__':
    unittest.main()

"""경계 불꽃 요청·Overdrive 확산·V키 쿨다운·준비 강조선·감쇠를 검사한다."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('ready_vfx_sample', ROOT / 'tests/ui_unit_test_v2.py')
SAMPLE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SAMPLE)

from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.ui_v2.effects import (BoundaryParticleEmitter, HealthHitMotion, OverdriveMotion, OverdriveVisual,
                                       UltimateReadyVisual, damped_oscillation)
from ferrial_drive.ui_v2.geometry import resource_geometry
from ferrial_drive.ui_v2.lock_on import accent_position, outline_segment
from ferrial_drive.ui_v2.view import UiV2View


class ReadyVfxTests(unittest.TestCase):
    def setUp(self):
        self.program = SAMPLE.UiUnitTestV2(initial_scene='combat')

    def test_matching_bevel_vectors_and_longer_vertical_side(self):
        geometry = resource_geometry(self.program.config.data['v2']['layout'], 12)
        upper, side, lower, bottom = geometry.level_shape[3:7]
        self.assertEqual((side[0] - upper[0], side[1] - upper[1]),
                         (lower[0] - bottom[0], bottom[1] - lower[1]))
        self.assertEqual(side[0], lower[0])
        self.assertGreater(lower[1] - side[1], 20)

    def test_overdrive_spreads_flashes_then_only_fades_out(self):
        motion = OverdriveMotion()
        motion.request(True)
        self.assertEqual(motion.visual.opacity, 0)
        first_spread = motion.visual.spread
        motion.update(0.12)
        self.assertGreater(motion.visual.spread, first_spread)
        self.assertGreater(motion.visual.flash, 0)
        motion.update(1)
        self.assertEqual(motion.visual.opacity, 1)
        self.assertEqual(motion.visual.spread, 1)
        self.assertEqual(motion.visual.flash, 0)
        motion.request(False)
        motion.update(0.09)
        self.assertAlmostEqual(motion.visual.opacity, 0.5)
        self.assertEqual(motion.visual.spread, 1)
        self.assertEqual(motion.visual.flash, 0)
        motion.request(True)
        self.assertAlmostEqual(motion.visual.opacity, 0.5)
        motion.update(1)
        self.assertEqual(motion.visual.opacity, 1)

    def test_ultimate_requires_level_three_and_zero_cooldown(self):
        for level, seconds, ready in ((1, 0, False), (2, 0, False), (3, 0, True), (3, 0.01, False)):
            state = replace(self.program.state, energy_level=level, ultimate_cooldown_seconds=seconds)
            self.assertEqual(state.ultimate_ready, ready)
        before = EnergyCharge.from_state(self.program.state).total
        self.program.perform('ultimate')
        self.assertEqual(self.program.state.ultimate_cooldown_seconds, 5)
        self.assertEqual(EnergyCharge.from_state(self.program.state).total, before)
        self.program.update(4.99)
        self.assertFalse(self.program.state.ultimate_ready)
        remaining = self.program.state.ultimate_cooldown_seconds
        self.program.perform('ultimate')
        self.assertEqual(self.program.state.ultimate_cooldown_seconds, remaining)
        self.program.update(0.02)
        self.assertTrue(self.program.state.ultimate_ready)
        self.assertEqual(self.program.ultimate_motion.visual.flash, 1)
        self.program.update(0.14)
        self.assertTrue(0 < self.program.ultimate_motion.visual.flash < 1)
        self.program.update(0.2)
        self.assertEqual(self.program.ultimate_motion.visual.flash, 0)
        self.assertEqual(self.program.ultimate_motion.visual.opacity, 1)

    def test_horizontal_entry_streak_expands_once_and_fades_with_exit(self):
        view = UiV2View(self.program.config, Mock())
        with patch.object(view, 'polygon') as polygon:
            view.overdrive_entry_streak((100, 100), 140, OverdriveVisual(1, entry_seconds=0), '#FF4044', 1)
            self.assertFalse(polygon.called)
            view.overdrive_entry_streak((100, 100), 140, OverdriveVisual(1, entry_seconds=0.02), '#FF4044', 1)
            fade_in = polygon.call_args.args[2]
            early_points = polygon.call_args.args[0]
            polygon.reset_mock()
            view.overdrive_entry_streak((100, 100), 140, OverdriveVisual(1, entry_seconds=0.06), '#FF4044', 1)
            peak = polygon.call_args.args[2]
            points = polygon.call_args.args[0]
            self.assertGreater(peak, fade_in)
            self.assertEqual(len(points), 4)
            width = max(p[0] for p in points) - min(p[0] for p in points)
            height = max(p[1] for p in points) - min(p[1] for p in points)
            self.assertGreater(width, height * 20)
            self.assertGreater(width, max(p[0] for p in early_points) - min(p[0] for p in early_points))
            polygon.reset_mock()
            view.overdrive_entry_streak((100, 100), 140, OverdriveVisual(0.5, entry_seconds=0.06), '#FF4044', 1)
            self.assertAlmostEqual(polygon.call_args.args[2], peak / 2)
            polygon.reset_mock()
            view.overdrive_entry_streak((100, 100), 140, OverdriveVisual(1, entry_seconds=0.25), '#FF4044', 1)
            view.overdrive_entry_streak((100, 100), 140, OverdriveVisual(1, entry_seconds=1.41), '#FF4044', 1)
            self.assertFalse(polygon.called)
        self.program.perform('overdrive')
        self.program.update(0.2)
        age = self.program.overdrive_motion.visual.entry_seconds
        self.program.pause.request(True)
        self.program.update(1)
        self.assertEqual(self.program.overdrive_motion.visual.entry_seconds, age)
        motion = self.program.overdrive_motion
        motion.request(False)
        motion.update(0.09)
        self.assertEqual(motion.visual.entry_seconds, age)
        self.assertAlmostEqual(motion.visual.opacity, 0.5)

    def test_v_key_starts_cooldown_and_pause_freezes_it(self):
        import pico2d as p
        from types import SimpleNamespace
        self.program.pico = p
        self.program.handle_event(SimpleNamespace(type=p.SDL_KEYDOWN, key=p.SDLK_v, repeat=False))
        self.assertEqual(self.program.state.ultimate_cooldown_seconds, 5)
        self.program.pause.request(True)
        self.program.update(1)
        self.assertEqual(self.program.state.ultimate_cooldown_seconds, 5)
        for invalid in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                replace(self.program.state, ultimate_cooldown_seconds=invalid)

    def test_ultimate_emphasis_uses_lock_on_patrol_only_when_ready(self):
        renderer = Mock()
        renderer.text_size.side_effect = lambda text, role: (len(text) * 10, 18)
        view = UiV2View(self.program.config, renderer)
        geometry = resource_geometry(view.layout, view.style['level_bevel_pixels'])
        x, y = geometry.icon_center
        radius = geometry.icon_radius
        diamond = ((x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y))
        settings = view.style['lock_motion']
        age = 0.17
        position = accent_position(age, settings['move_seconds'], settings['hold_seconds'])
        segments = [outline_segment(diamond, p - 0.325) for p in (position, position + 2)]
        for seconds, count in ((0, 2), (1, 0)):
            with patch.object(view, 'stroke') as stroke:
                view.resources(replace(self.program.state, ultimate_cooldown_seconds=seconds), 1, 0, 1,
                               ultimate_visual=UltimateReadyVisual(age))
            found = [call for call in stroke.call_args_list if call.args[0] in segments]
            self.assertEqual(len(found), count)

    def test_boundary_emission_has_no_gain_and_stops_at_empty_full_or_pause(self):
        self.program.update(0.1)
        sparks = [c for c in self.program.particle_system.commands if getattr(c, 'effect_type', -1) == 1]
        self.assertTrue(sparks)
        self.assertTrue(all(c.gain_units == 0 for c in sparks))
        self.assertEqual(self.program.particle_system.requested_gain_units, 0)
        for charge in (EnergyCharge(0), EnergyCharge(3), EnergyCharge(4)):
            self.program.particle_system.commands.clear()
            self.program.set_energy_charge(charge)
            self.program.emit_boundary_particles(0.1)
            self.assertFalse(self.program.particle_system.commands)
        emitter = BoundaryParticleEmitter(32)
        self.assertEqual(sum(emitter.update(1 / 64, True) for _ in range(64)), 32)
        self.assertLessEqual(emitter.update(100, True), 5)

    def test_damage_and_lock_on_damp_without_accumulating_displacement(self):
        motion = HealthHitMotion(duration_seconds=0.34, frequency_hz=16, max_offset_pixels=(0, 7), damping=1.8)
        motion.trigger()
        motion.update(0.07)
        weak, _ = damped_oscillation(0.07, 0.34, 16, 0)
        self.assertLess(abs(motion.visual.offset_pixels[1]), abs(weak * 7))
        motion.trigger()
        self.assertEqual(motion.visual.offset_pixels, (0, 0))
        motion.update(1)
        self.assertEqual(motion.visual.offset_pixels, (0, 0))
        lock = self.program.lock_motion
        lock.update(1)
        lock.hit('enemy_a')
        lock.update(0.01)
        damped = lock.visuals[0].offset_pixels
        lock.hit_damping = 0
        undamped = lock.visuals[0].offset_pixels
        self.assertTrue(all(abs(a) < abs(b) for a, b in zip(damped, undamped)))
        lock.update(1)
        self.assertEqual(lock.visuals[0].offset_pixels, (0, 0))


if __name__ == '__main__':
    unittest.main()

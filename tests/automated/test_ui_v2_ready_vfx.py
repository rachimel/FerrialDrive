"""경계 불꽃 요청·Overdrive 확산·V키 쿨다운·준비 강조선·감쇠를 검사한다."""

from dataclasses import replace
from contextlib import contextmanager, nullcontext
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('ready_vfx_sample', ROOT / 'tests/ui_unit_test_v2.py')
SAMPLE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SAMPLE)

from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.ui_v2.effects import (BoundaryParticleEmitter, HealthHitMotion, OverdriveMotion, OverdriveVisual,
                                       UltimateReadyVisual, damped_oscillation)
from ferrial_drive.ui_v2.geometry import hatched_stroke_mesh, resource_geometry
from ferrial_drive.ui.counter import CounterVisual
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui_v2.lock_on import accent_position, outline_segment
from ferrial_drive.ui_v2.view import UiV2View


class ReadyVfxTests(unittest.TestCase):
    def setUp(self):
        self.program = SAMPLE.UiUnitTestV2(initial_scene='combat')

    def test_matching_bevel_vectors_and_longer_vertical_side(self):
        geometry = resource_geometry(self.program.config.data['v2']['layout'], 12)
        self.assertEqual(geometry.level_top, self.program.config.data['v2']['layout']['hp_bar'][1])
        upper, side, lower, bottom = geometry.level_shape[2:6]
        self.assertEqual((side[0] - upper[0], side[1] - upper[1]),
                         (lower[0] - bottom[0], bottom[1] - lower[1]))
        self.assertEqual(side[0], lower[0])
        self.assertGreater(lower[1] - side[1], 20)

    def test_accent_speed_peaks_at_midpoint_and_stops_at_both_ends(self):
        duration, hold, step = 0.32, 0.2, 0.00001
        def velocity(t):
            age = t * duration
            return (accent_position(age + step, duration, hold) - accent_position(age, duration, hold)) / step
        self.assertGreater(velocity(0.5), velocity(0.25))
        self.assertGreater(velocity(0.25), velocity(0.05))
        self.assertAlmostEqual(velocity(0.25), velocity(0.75), delta=0.01)
        self.assertLess(velocity(0), 0.001)
        self.assertAlmostEqual(accent_position(duration, duration, hold), 5.5)
        self.assertAlmostEqual(accent_position(duration + hold / 2, duration, hold), 5.5)

    def test_hatches_stay_inside_band_and_spacing_tightens_at_the_head(self):
        shapes = hatched_stroke_mesh(((0, 0), (40, 0)), 4, 8, 2.5, 1.1)
        self.assertTrue(shapes)
        self.assertTrue(all(0 <= x <= 40 and -2 <= y <= 2 for shape in shapes for x, y in shape))
        centers = [(min(x for x, _ in s) + max(x for x, _ in s)) / 2 for s in shapes
                   if min(x for x, _ in s) > 0 and max(x for x, _ in s) < 40]
        gaps = [b - a for a, b in zip(centers, centers[1:])]
        self.assertGreater(len(gaps), 2)
        self.assertTrue(all(a > b for a, b in zip(gaps, gaps[1:])))

    def test_level_smear_trails_rising_digits_and_keeps_static_digits_sharp(self):
        renderer = Mock()
        renderer.text_size.return_value = (16, 40)
        view = UiV2View(self.program.config, renderer)
        visual = CounterVisual(1, 2, 0.06, 0.12, 'elastic_in_out')
        view.rolling_digit(visual, '1', '2', 0, 40, 'v2_level', '#FFFFFF',
                           lambda x, y: (x, y), 1, 1, Rect(0, 0, 16, 40))
        tops = [call.args[2] for call in renderer.warped_text.call_args_list if call.args[0] == '2']
        self.assertGreater(len(tops), 1)
        self.assertGreater(max(tops), min(tops))
        self.assertAlmostEqual(min(tops), 40 * (1 - visual.vertical_progress))
        renderer.warped_text.reset_mock()
        view.rolling_digit(visual, '2', '2', 0, 40, 'v2_level', '#FFFFFF',
                           lambda x, y: (x, y), 1, 1, Rect(0, 0, 16, 40))
        self.assertEqual(renderer.warped_text.call_count, 1)

    def test_counter_gpu_blur_follows_projected_motion_and_excludes_static_digits_and_labels(self):
        renderer = Mock()
        renderer.text_size.side_effect = lambda text, role: (len(text) * 16, 40)
        renderer.digit_ink_bottom.return_value = 34
        renderer.clip.side_effect = lambda rect: nullcontext()
        active, drawn = [], []
        @contextmanager
        def blur(*args, **kwargs):
            active.append(True)
            yield
            active.pop()
        renderer.directional_blur.side_effect = blur
        renderer.warped_text.side_effect = lambda *args, **kwargs: drawn.append((bool(active), args[0], args[3]))
        view = UiV2View(self.program.config, renderer)
        view.perspective_counter(CounterVisual(98, 99, 0.06, 0.12, 'elastic_in_out'),
                                 'combo_number', 'combo', 276, 1)
        self.assertEqual(renderer.directional_blur.call_count, 1)
        _, motion, strength, samples = renderer.directional_blur.call_args.args
        self.assertLess(motion[1], 0)
        self.assertGreater(abs(motion[1]), abs(motion[0]))
        self.assertGreater(strength, 0)
        self.assertEqual(samples, 49)
        self.assertEqual(renderer.directional_blur.call_args.kwargs['forward_bias'], 1)
        self.assertTrue(any(not filtered and char == '9' and role == 'combo_number' for filtered, char, role in drawn))
        self.assertTrue(all(role == 'combo_number' for filtered, _, role in drawn if filtered))
        self.assertFalse(active)

    def test_energy_tint_interpolates_without_delaying_charge_and_freezes_on_pause(self):
        self.program.perform('overdrive')
        self.assertTrue(self.program.state.overdrive)
        self.assertEqual(EnergyCharge.from_state(self.program.state).total, 4)
        self.assertEqual(self.program.energy_tint.ratio, 0)
        self.program.update(0.12)
        self.assertAlmostEqual(self.program.energy_tint.ratio, 0.5)
        self.program.renderer, self.program.view = Mock(), MagicMock()
        self.program.draw_layers()
        self.assertAlmostEqual(self.program.view.combat.call_args.kwargs['energy_tint_ratio'], 0.5)
        self.program.pause.request(True)
        self.program.update(1)
        self.assertAlmostEqual(self.program.energy_tint.ratio, 0.5)
        self.program.pause.reset()
        self.program.renderer = None
        self.program.update(0.12)
        self.assertEqual(self.program.energy_tint.ratio, 1)
        self.program.perform('overdrive')
        self.program.update(0.12)
        self.assertAlmostEqual(self.program.energy_tint.ratio, 0.5)
        self.assertFalse(self.program.state.overdrive)

    def test_counter_exposure_uses_instantaneous_speed_and_keeps_streak_margin(self):
        renderer = Mock()
        renderer.clip.side_effect = lambda rect: nullcontext()
        renderer.directional_blur.side_effect = lambda *args, **kwargs: nullcontext()
        view = UiV2View(self.program.config, renderer)
        lengths = []
        for elapsed in (0.001, 0.09, 0.179):
            visual = CounterVisual(1, 2, elapsed, 0.18, 'elastic_in_out')
            with view.counter_motion_blur(visual, lambda x, y: (x, y), 80, 60, 50, 1):
                pass
            bounds, motion, strength, _ = renderer.directional_blur.call_args.args
            clipping = renderer.clip.call_args.args[0]
            self.assertLess(clipping.y, bounds.y)
            self.assertGreater(clipping.y + clipping.height, bounds.y + bounds.height)
            self.assertGreaterEqual(bounds.y - clipping.y, abs(motion[1]) / 2 + 8 - 0.00001)
            self.assertEqual(strength, view.style['loadout_blur']['opacity'])
            lengths.append(abs(motion[1]))
        self.assertGreater(lengths[1], lengths[0])
        self.assertGreater(lengths[1], lengths[2])

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
        renderer.clip.side_effect = lambda rect: nullcontext()
        view = UiV2View(self.program.config, renderer)
        geometry = resource_geometry(view.layout, view.style['level_bevel_pixels'])
        x, y = geometry.icon_center
        radius = geometry.icon_radius
        diamond = ((x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y))
        settings = view.style['lock_motion']
        age = 0.17
        position = accent_position(age, settings['move_seconds'], settings['hold_seconds'],
                                   settings.get('minimum_speed_ratio', 0))
        length = view.style['accent_profile']['length_sides']
        segments = [outline_segment(diamond, p - length / 2, length) for p in (position, position + 2)]
        for seconds, count in ((0, 2), (1, 0)):
            with patch.object(view, 'accent_stroke') as accent:
                view.resources(replace(self.program.state, ultimate_cooldown_seconds=seconds), 1, 0, 1,
                               ultimate_visual=UltimateReadyVisual(age))
            found = [call for call in accent.call_args_list if call.args[0] in segments]
            self.assertEqual(len(found), count)

    def test_ultimate_cooldown_darkens_and_reveals_only_the_lower_region(self):
        renderer = Mock()
        active = []
        @contextmanager
        def clip(rect):
            active.append(rect)
            yield
            active.pop()
        renderer.clip.side_effect = clip
        view = UiV2View(self.program.config, renderer)
        geometry = resource_geometry(view.layout, view.style['level_bevel_pixels'])
        state = replace(self.program.state, ultimate_cooldown_seconds=2.5, ultimate_cooldown_duration_seconds=5)
        drawn = []
        def stroke(points, color, opacity=1, width=1):
            drawn.append((bool(active), opacity, width))
        with patch.object(view, 'stroke', side_effect=stroke):
            view.ultimate_icon(state, geometry, '#FFFFFF', 1)
        rect = renderer.clip.call_args.args[0]
        self.assertEqual(rect.y, geometry.icon_center[1])
        self.assertEqual(rect.height, geometry.icon_radius + view.style['ultimate_border_width_pixels'])
        self.assertTrue(any(not clipped and alpha < 0.3 for clipped, alpha, _ in drawn))
        self.assertTrue(any(clipped and alpha == 0.9 for clipped, alpha, _ in drawn))
        self.assertFalse(active)
        self.assertEqual(replace(state, ultimate_cooldown_seconds=5).ultimate_recovery_ratio, 0)
        self.assertEqual(replace(state, ultimate_cooldown_seconds=0).ultimate_recovery_ratio, 1)
        for invalid in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                replace(state, ultimate_cooldown_duration_seconds=invalid)

    def test_boundary_emission_has_no_gain_and_stops_at_empty_full_or_pause(self):
        self.program.update(0.1)
        sparks = [c for c in self.program.particle_system.commands if getattr(c, 'effect_type', -1) == 1]
        self.assertTrue(sparks)
        self.assertTrue(all(c.gain_units == 0 for c in sparks))
        self.assertEqual(self.program.particle_system.requested_gain_units, 0)
        for charge in (EnergyCharge(0), EnergyCharge(3)):
            self.program.particle_system.commands.clear()
            self.program.set_energy_charge(charge)
            self.program.emit_boundary_particles(0.1)
            self.assertFalse(self.program.particle_system.commands)
        self.program.set_energy_charge(EnergyCharge(4))
        self.program.emit_boundary_particles(0.1)
        sparks = self.program.particle_system.commands[-1]
        self.assertEqual(sparks.effect_type, 1)
        self.assertGreater(sparks.count, 4)
        self.assertGreater(sparks.intensity, 1)
        self.assertGreater(sparks.duration_seconds, 0.8)
        self.assertEqual(sparks.gain_units, 0)
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

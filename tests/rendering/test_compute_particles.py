"""실제 GPU 생성·상태 갱신·고정 경로·간접 드로·읽기 없는 프레임·상태 복원을 검사한다."""

import ctypes as ct
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_directional_blur as blur_tests
from ferrial_drive.particles import GpuParticleSystem
from ferrial_drive.rendering.compute_particles import SSBO, SSBO_BINDING, INDIRECT
from ferrial_drive.ui_v2.effects import AbsorptionTrail
from ferrial_drive.ui_v2.particle_texture import ATLAS_SIZE, build_particle_atlas


class ComputeParticleTests(unittest.TestCase):
    setUp = blur_tests.DirectionalBlurTests.setUp
    tearDown = blur_tests.DirectionalBlurTests.tearDown
    pixels = blur_tests.DirectionalBlurTests.pixels

    settings = dict(samples=24, head_width_pixels=4, orb_radius_pixels=4)

    def test_soft_atlas_has_transparent_orb_corners_and_a_bright_center(self):
        data = build_particle_atlas()
        width, height = ATLAS_SIZE
        alpha = lambda x, y: data[(y * width + x) * 4 + 3]
        self.assertEqual(len(data), width * height * 4)
        self.assertEqual(alpha(0, 0), 0)
        self.assertGreater(alpha(32, 32), 250)
        self.assertGreater(alpha(32, 32), alpha(45, 32))
        self.assertEqual(alpha(70, 32), alpha(120, 32))

    def make_system(self, capacity=8, *, profiling=False):
        system = GpuParticleSystem(1, capacity=capacity, seed=27)
        backend = self.renderer.prepare_compute_particles(system, profiling=profiling)
        return system, backend

    def draw(self, system):
        self.renderer.draw_compute_particles(system, self.settings, '#FFFFFF', '#FFFFFF', 1)

    def test_two_compute_programs_create_particles_and_gpu_draw_commands(self):
        system, backend = self.make_system()
        self.assertEqual(set(backend.compute_programs), {'spawn', 'update'})
        system.emit((20, 20), (40, 35), (70, 40), count=3, spread_pixels=0)
        self.draw(system)
        snapshot = backend.snapshot()
        self.assertEqual(snapshot['active_count'], 3)
        self.assertEqual(snapshot['spawn_cursor'], 3)
        self.assertEqual(snapshot['draw_commands'][1], 6)
        self.assertEqual(snapshot['draw_commands'][5], 9)
        self.assertEqual(system.commands, [])
        self.assertEqual(backend.frame_particle_upload_bytes, 0)
        self.assertGreater(self.pixels()[(20 * 96 + 20) * 4], 150)

    def test_gpu_path_and_position_follow_prescribed_route_then_expire(self):
        system, backend = self.make_system()
        system.emit((20, 20), (40, 35), (70, 40), count=1, spread_pixels=0)
        elapsed = 0
        for target in (0, 0.2, 0.72, 1, 1.1):
            system.update(target - elapsed)
            self.draw(system)
            particle = backend.snapshot()['particles'][0]
            profile = system.profiles[int(particle[11])]
            a, b, c, d = profile
            trail = AbsorptionTrail((20, 20), (40, 35), (70, 40), 1,
                                     route_offsets=((0, 0), a, b, (0, 0), (0, 0), c, d, (0, 0)))
            expected = trail.point(min(1, target))
            self.assertAlmostEqual(particle[12], expected[0], delta=0.0002)
            self.assertAlmostEqual(particle[13], expected[1], delta=0.0002)
            self.assertAlmostEqual(particle[0], target, delta=0.00001)
            self.assertAlmostEqual(particle[14], target, delta=0.00001)
            elapsed = target
        system.update(0.201)
        self.draw(system)
        self.assertEqual(backend.snapshot()['active_count'], 0)

    def test_cpu_frame_never_reads_gpu_particle_state(self):
        system, backend = self.make_system()
        with patch.object(backend, 'glGetBufferSubData', side_effect=AssertionError('프레임 readback 금지')):
            system.emit((20, 20), (40, 35), (70, 40), count=4)
            for _ in range(5):
                system.update(1 / 60)
                self.draw(system)
        self.assertEqual(backend.snapshot()['active_count'], 4)
        self.assertEqual(backend.spawn_requests_submitted, 1)

    def test_capacity_overflow_reuses_old_slots_and_reset_clears_gpu(self):
        system, backend = self.make_system(capacity=4)
        system.emit((10, 10), (40, 35), (70, 40), count=100, spread_pixels=0)
        self.draw(system)
        system.update(0.1)
        system.emit((30, 30), (40, 35), (70, 40), count=2, spread_pixels=0)
        self.draw(system)
        snapshot = backend.snapshot()
        self.assertEqual(snapshot['active_count'], 4)
        self.assertEqual(sum(p[4] == 30 for p in snapshot['particles']), 2)
        system.clear()
        self.draw(system)
        snapshot = backend.snapshot()
        self.assertEqual(snapshot['active_count'], 0)
        self.assertEqual(snapshot['spawn_cursor'], 0)

    def test_right_side_uses_right_profile_and_returns_to_target_from_right(self):
        system, backend = self.make_system()
        system.emit((80, 10), (75, 50), (50, 50), count=1, side=1, spread_pixels=0)
        system.update(0.95)
        self.draw(system)
        particle = backend.snapshot()['particles'][0]
        self.assertEqual(particle[3], 1)
        self.assertGreater(particle[12], 50)
        self.assertTrue(0 <= particle[11] < 6)

    def test_gl_bindings_unpack_and_lifetime_are_preserved_without_updates(self):
        system, backend = self.make_system()
        system.emit((20, 20), (40, 35), (70, 40), count=1)
        self.draw(system)
        backend.glBindBufferBase(SSBO, 0, backend.buffers[4])
        backend.glBindBuffer(INDIRECT, backend.buffers[2])
        keys = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
        original = tuple(backend.integer(key) for key in keys)
        try:
            for key, value in zip(keys, (8, 17, 3, 2)):
                backend.glPixelStorei(key, value)
            generic = backend.integer(SSBO_BINDING)
            self.draw(system)
            self.assertEqual(backend.integer(SSBO_BINDING), generic)
            self.assertEqual(backend.integer(0x8F43), backend.buffers[2])
            value = ct.c_int()
            backend.glGetIntegeri_v(SSBO_BINDING, 0, ct.byref(value))
            self.assertEqual(value.value, backend.buffers[4])
            self.assertEqual(tuple(backend.integer(key) for key in keys), (8, 17, 3, 2))
        finally:
            for key, value in zip(keys, original):
                backend.glPixelStorei(key, value)
        self.assertEqual(backend.snapshot()['particles'][0][0], 0)

    def test_gpu_timer_and_resource_cleanup(self):
        system, backend = self.make_system(profiling=True)
        system.emit((20, 20), (40, 35), (70, 40), count=1)
        system.update(0.02)
        self.draw(system)
        timings = backend.collect_timings(wait=True)
        self.assertEqual(set(timings), {'spawn', 'update', 'render'})
        self.assertTrue(all(value >= 0 for value in timings.values()))
        self.renderer.close()
        self.assertFalse(backend.compute_programs)
        self.assertFalse(backend.buffers)
        self.assertFalse(backend.textures)
        self.assertFalse(backend.query_names)
        self.assertEqual(backend.program, 0)

    def test_ribbon_pressure_and_selected_route_remain_on_gpu(self):
        system, backend = self.make_system(capacity=24)
        system.emit((20, 20), (40, 35), (70, 40), count=24, spread_pixels=0)
        system.update(0.5)
        self.draw(system)
        before = backend.snapshot()
        routes = [particle[11] for particle in before['particles']]
        self.assertGreaterEqual(len(set(routes)), 4)
        ribbon = (ct.c_float * (25 * 8))()
        with backend.batch(), backend._state():
            backend.glMemoryBarrier(0x0200)
            backend.glBindBuffer(SSBO, backend.buffers[6])
            backend.glGetBufferSubData(SSBO, 0, ct.sizeof(ribbon), ribbon)
        pressure = [ribbon[index * 8 + 4] for index in range(25)]
        self.assertEqual(pressure[0], 0)
        self.assertAlmostEqual(pressure[-1], 1)
        self.assertTrue(all(a <= b for a, b in zip(pressure, pressure[1:])))
        system.update(0.1)
        self.draw(system)
        self.assertEqual([particle[11] for particle in backend.snapshot()['particles']], routes)

    def test_stress_benchmark_records_every_gpu_frame_without_loop_readback(self):
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location('gpu_stress_benchmark', root / 'tests/massive_energy_particle_stress.py')
        sample = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sample)
        program = sample.create_test(capacity=64)
        program.config['width'], program.config['height'] = 96, 64
        try:
            program.enter()
            with tempfile.TemporaryDirectory(dir=root / 'output') as temporary, \
                    patch.object(program.backend, 'snapshot', wraps=program.backend.snapshot) as snapshots:
                report = program.run_benchmark(counts=[1, 32], warmup=2, frames=3,
                                               output_path=Path(temporary) / 'stress.json')
                self.assertEqual(snapshots.call_count, 2)
                self.assertFalse(report['readback_in_measured_loop'])
                for count, row in zip((1, 32), report['results']):
                    self.assertEqual(row['active_count'], count)
                    self.assertEqual(row['gpu_update']['samples'], 3)
                    self.assertEqual(row['gpu_render']['samples'], 3)
                    self.assertEqual(row['cpu']['measurements'][0]['calls'], 3)
        finally:
            program.exit()

    def test_compute_does_not_change_cached_ui_text_between_frames(self):
        from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer
        root = Path(__file__).resolve().parents[2]
        font = root / 'data/fonts/Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf'
        self.renderer.close()
        self.renderer = PicoV2Renderer({'label': font}, {'label': 16})
        system, backend = self.make_system(capacity=24)
        self.renderer.clear('#000000')
        self.renderer.text('HP 123', 2, 2, 'label', '#FFFFFF')
        baseline = self.pixels()[:96 * 26 * 4]
        for frame in range(16):
            self.renderer.clear('#000000')
            self.renderer.text('HP 123', 2, 2, 'label', '#FFFFFF')
            if frame % 4 == 0:
                system.emit((70, 1000), (60, 1000), (80, 1000), count=24, spread_pixels=0)
            system.update(1 / 60)
            self.draw(system)
            self.assertEqual(self.pixels()[:96 * 26 * 4], baseline, f'UI 글자 변경: {frame}')

    def test_arrivals_split_energy_exactly_once_and_follow_moving_fill_tip(self):
        system, backend = self.make_system(capacity=16)
        system.set_energy_target((10, 45), (80, 45), 0.25)
        system.emit((20, 20), (40, 58), (27.5, 45), count=6, spread_pixels=0,
                    gain_ratio=0.1, arrival_spacing_seconds=0.05)
        system.update(0.99)
        self.draw(system)
        self.assertEqual(backend.snapshot()['arrived_units'], 0)
        system.update(0.02)
        self.draw(system)
        first = backend.snapshot()
        self.assertEqual(first['arrival_count'], 1)
        self.assertEqual(first['arrived_units'], 16667)
        backend.poll_arrivals(wait=True)
        gain, count = system.take_arrivals()
        self.assertAlmostEqual(gain, 0.016667)
        self.assertEqual(count, 1)
        system.update(0.25)
        self.draw(system)
        final = backend.snapshot()
        self.assertEqual(final['arrival_count'], 6)
        self.assertEqual(final['arrived_units'], 100000)
        backend.poll_arrivals(wait=True)
        gain2, count2 = system.take_arrivals()
        self.assertAlmostEqual(gain + gain2, 0.1)
        self.assertEqual(count + count2, 6)
        self.assertEqual(system.pending_gain_units, 0)
        self.assertAlmostEqual(system.energy_target[-1], 0.35)
        # 도착한 꼬리 끝도 새로 채워진 위치를 따른다.
        system.update(0.01)
        self.draw(system)
        live = [p for p in backend.snapshot()['particles'] if p[2] and p[14] >= 1]
        self.assertTrue(live)
        self.assertTrue(all(abs(p[12] - 34.5) < 0.001 for p in live))

    def test_large_step_still_credits_contact_before_particle_expires(self):
        system, backend = self.make_system()
        system.set_energy_target((10, 45), (80, 45), 0.2)
        system.emit((20, 20), (40, 58), (24, 45), count=6, gain_ratio=0.1)
        system.update(4)
        self.draw(system)
        snapshot = backend.snapshot()
        self.assertEqual(snapshot['active_count'], 0)
        self.assertEqual(snapshot['arrived_units'], 100000)
        backend.poll_arrivals(wait=True)
        self.assertAlmostEqual(system.take_arrivals()[0], 0.1)

    def test_gpu_fill_target_wraps_levels_and_tracks_extra_overdrive_charge(self):
        for total, expected in ((0.99, 0.09), (2.99, 0.09), (3.45, 0.55), (3.95, 1)):
            with self.subTest(total=total):
                system, backend = self.make_system()
                ratio = total - 3 if total >= 3 else total % 1
                system.set_energy_target((10, 45), (80, 45), ratio, charge_total=total)
                system.emit((20, 20), (40, 58), (10 + 70 * ratio, 45), count=6,
                            gain_ratio=0.1, spread_pixels=0, arrival_spacing_seconds=0.05)
                system.update(1.26)
                self.draw(system)
                self.assertEqual(backend.snapshot()['arrived_units'], 100000)
                backend.poll_arrivals(wait=True)
                self.assertAlmostEqual(system.energy_target[-1], expected)
                # 집계 수신 후에도 GPU 목표가 같은 충전 단계의 끝을 가리킨다.
                system.update(0.01)
                self.draw(system)
                live = [p for p in backend.snapshot()['particles'] if p[2] and p[14] >= 1]
                self.assertTrue(live)
                self.assertTrue(all(abs(p[12] - (10 + 70 * expected)) < 0.001 for p in live))
                backend.close()

    def test_reset_discards_inflight_receipts_and_overflow_does_not_award_dropped_particles(self):
        system, backend = self.make_system(capacity=2)
        system.set_energy_target((10, 45), (80, 45), 0.2)
        for _ in range(2):
            system.emit((20, 20), (40, 58), (24, 45), count=2, gain_ratio=0.1)
        system.update(1.01)
        self.draw(system)
        snapshot = backend.snapshot()
        self.assertEqual(snapshot['cancelled_units'], 100000)
        self.assertEqual(snapshot['arrived_units'], 100000)
        system.clear()
        self.draw(system)
        backend.poll_arrivals(wait=True)
        self.assertEqual(system.take_arrivals(), (0, 0))
        self.assertEqual(backend.snapshot()['arrived_units'], 0)

    def test_bar_entry_stays_below_target_and_translation_restores_state(self):
        system, backend = self.make_system()
        system.emit((20, 20), (40, 58), (70, 45), count=1, spread_pixels=0)
        elapsed = 0
        for time in (0.72, 0.85, 0.95):
            system.update(time - elapsed)
            self.draw(system)
            self.assertGreater(backend.snapshot()['particles'][0][13], 45)
            elapsed = time
        before = self.renderer.draw_transform()
        with self.renderer.translated(3, 4):
            self.assertNotEqual(self.renderer.draw_transform(), before)
        self.assertEqual(self.renderer.draw_transform(), before)

    def test_unready_recovery_fence_never_blocks_or_reads_particle_buffer(self):
        system, backend = self.make_system()
        system.set_energy_target((10, 45), (80, 45), 0.2)
        system.emit((20, 20), (40, 58), (24, 45), count=1, gain_ratio=0.1)
        self.draw(system)
        with patch.object(backend, 'glClientWaitSync', return_value=0x911B) as check, \
                patch.object(backend, 'glGetBufferSubData', side_effect=AssertionError('미완료 집계 읽기 금지')):
            backend.poll_arrivals()
            self.assertEqual(check.call_args.args[1:], (0, 0))
        self.assertEqual(system.take_arrivals(), (0, 0))


if __name__ == '__main__':
    unittest.main()

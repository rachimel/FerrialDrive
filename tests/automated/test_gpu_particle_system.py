"""GPU 파티클의 CPU 요청·순서·정지·초기화·독립 실행 규약을 검사한다."""

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ferrial_drive.particles import GpuParticleSystem, SpawnParticles, StepParticles
from Tools.unit_test_runner.entrypoints import inspect_entrypoint, read_test_header, read_test_source


def load_sample(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ParticleRequestTests(unittest.TestCase):
    def test_emission_only_queues_request_without_cpu_particle_state(self):
        system = GpuParticleSystem(capacity=32, seed=11)
        system.emit((10, 20), (30, 40), (50, 60), count=25)
        self.assertEqual(len(system.commands), 1)
        self.assertIsInstance(system.commands[0], SpawnParticles)
        self.assertEqual(system.commands[0].count, 25)
        self.assertFalse(hasattr(system, 'trails'))
        self.assertFalse(hasattr(system, 'particles'))

    def test_steps_coalesce_but_never_cross_spawn_events(self):
        system = GpuParticleSystem()
        system.update(0.1)
        system.update(0.2)
        system.emit((10, 20), (30, 40), (50, 60))
        system.update(0.4)
        self.assertEqual(len(system.commands), 3)
        self.assertAlmostEqual(system.commands[0].delta_seconds, 0.3)
        self.assertIsInstance(system.commands[1], SpawnParticles)
        self.assertEqual(system.commands[2], StepParticles(0.4))

    def test_fixed_profiles_reset_and_capacity_limit(self):
        system = GpuParticleSystem(capacity=8)
        self.assertEqual(len(system.profiles), 12)
        self.assertTrue(all(len(profile) == 4 for profile in system.profiles))
        system.emit((10, 20), (30, 40), (50, 60), count=100)
        self.assertEqual(system.commands[0].count, 8)
        system.clear()
        self.assertFalse(system.commands)
        self.assertEqual(system.generation, 1)

    def test_invalid_requests_are_rejected_before_gpu_submission(self):
        for capacity in (0, -1, 1.5, 65537):
            with self.assertRaises(ValueError):
                GpuParticleSystem(capacity=capacity)
        system = GpuParticleSystem()
        for seconds in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                system.update(seconds)
        for options in ({'side': 0}, {'count': 0}, {'effect_type': 9}, {'duration_seconds': 0}):
            with self.assertRaises(ValueError):
                system.emit((10, 20), (30, 40), (50, 60), **options)

    def test_ui_default_uses_compute_burst_and_pause_freezes_command_stream(self):
        sample = load_sample('compute_ui_sample', 'tests/ui_unit_test_v2.py')
        program = sample.UiUnitTestV2(initial_scene='combat')
        self.assertIsNotNone(program.particle_system)
        program.perform('damage_target')
        requests = [command for command in program.particle_system.commands if isinstance(command, SpawnParticles)]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].count, 6)
        self.assertFalse(program.absorption.trails)
        before = list(program.particle_system.commands)
        program.pause.request(True)
        program.update(0.3)
        self.assertEqual(program.particle_system.commands, before)
        program.reset()
        self.assertFalse(program.particle_system.commands)

    def test_stress_program_is_standalone_and_construction_opens_no_window(self):
        path = ROOT / 'tests/massive_energy_particle_stress.py'
        self.assertEqual(inspect_entrypoint(path), 'standalone')
        self.assertEqual(read_test_header(read_test_source(path))[0], 'Massive Energy Particle Stress')
        sample = load_sample('particle_stress_sample', 'tests/massive_energy_particle_stress.py')
        program = sample.create_test()
        self.assertIsNone(program.renderer)
        self.assertEqual(program.system.capacity, 16384)


if __name__ == '__main__':
    unittest.main()

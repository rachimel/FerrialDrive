"""v2 독립 실행 계약·표시 데이터·흡수 경로·일시정지 경계 검사."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("ui_v2_sample", ROOT / "tests/ui_unit_test_v2.py")
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)

from ferrial_drive.ui_v2.effects import AbsorptionTrail, EnergyAbsorption


class UiV2Tests(unittest.TestCase):
    def setUp(self):
        self.program = SAMPLE.create_test()

    def test_runner_reads_standalone_header_without_execution(self):
        from Tools.unit_test_runner.entrypoints import inspect_entrypoint, read_test_header, read_test_source

        path = ROOT / "tests/ui_unit_test_v2.py"
        self.assertEqual(inspect_entrypoint(path), "standalone")
        self.assertEqual(read_test_header(read_test_source(path))[0], "ui-unit-test-v2")

    def test_import_and_construction_from_other_directory_do_not_load_pico(self):
        code = ("import runpy,sys; "
                f"m=runpy.run_path({str(ROOT / 'tests/ui_unit_test_v2.py')!r}); "
                "m['create_test'](); "
                "assert not any(n == 'pico2d' or n.startswith('pico2d.') for n in sys.modules)")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT.parent,
                                 capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_energy_and_level_reject_invalid_values(self):
        for energy in (-1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                replace(self.program.state, energy_ratio=energy)
        for level in (0, 4, True):
            with self.assertRaises(ValueError):
                replace(self.program.state, energy_level=level)

    def test_absorption_passes_through_icon_then_reaches_bar(self):
        trail = AbsorptionTrail((600, 360), (300, 660), (650, 680), 1)
        self.assertEqual(trail.point(0), (600, 360))
        self.assertEqual(trail.point(0.72), (300, 660))
        self.assertEqual(trail.point(1), (650, 680))
        effect = EnergyAbsorption(0.8)
        effect.add(trail.start, trail.icon, trail.destination)
        effect.update(0.8)
        self.assertTrue(effect.trails)
        effect.update(0.25)
        self.assertFalse(effect.trails)

    def test_pause_freezes_trail_and_resumes_from_same_time(self):
        self.program.absorb()
        self.program.pause.request(True)
        self.program.update(1)
        self.assertEqual(self.program.absorption.trails[0].elapsed_seconds, 0)
        self.program.perform("resume")
        self.program.update(1)
        self.assertEqual(self.program.absorption.trails[0].elapsed_seconds, 0)
        self.program.update(0.1)
        self.assertAlmostEqual(self.program.absorption.trails[0].elapsed_seconds, 0.1)

    def test_player_damage_does_not_increment_attack_counters(self):
        before = self.program.state.hud
        self.program.perform("damage_player")
        after = self.program.state.hud
        self.assertLess(after.player_health.current, before.player_health.current)
        self.assertEqual(after.combo_count, before.combo_count)
        self.assertEqual(after.total_damage_dealt, before.total_damage_dealt)

    def test_target_switch_and_reset_do_not_share_v1_state(self):
        before = self.program.state
        self.program.perform("next_target")
        self.assertNotEqual(self.program.state.hud.target.name, before.hud.target.name)
        self.program.perform("energy_up")
        self.assertTrue(self.program.absorption.trails)
        self.program.perform("reset")
        self.assertEqual(self.program.state, before)
        self.assertFalse(self.program.absorption.trails)

    def test_pause_blocks_sample_shortcuts(self):
        self.program.pico = SimpleNamespace(SDL_WINDOWEVENT=1, SDL_KEYDOWN=2,
                                            SDLK_F1=1001, SDLK_ESCAPE=27)
        self.program.pause.request(True)
        self.program.update(1)
        before = self.program.state
        self.program.handle_event(SimpleNamespace(type=2, key=49, repeat=False))
        self.assertEqual(self.program.state, before)


if __name__ == "__main__":
    unittest.main()

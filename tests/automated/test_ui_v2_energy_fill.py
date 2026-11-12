"""에너지 표시 보간·연속 증가·레벨 경계·논리 값 및 일시정지 분리를 확인한다."""

from dataclasses import replace
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.ui.energy_fill import EnergyFillMotion
from ferrial_drive.ui_v2.view import UiV2View

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('energy_fill_sample', ROOT / 'tests/ui_unit_test_v2.py')
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)


class EnergyFillTests(unittest.TestCase):
    def test_dense_arrivals_do_not_extend_the_original_catchup_window(self):
        for delta in (1 / 60, 1 / 120, 0.01):
            motion = EnergyFillMotion()
            elapsed, target = 0, 0
            while elapsed < 0.12 - 1e-9:
                target += 0.03
                before = motion.visual.total
                motion.request(target)
                self.assertEqual(motion.visual.total, before)
                step = min(delta, 0.12 - elapsed)
                motion.update(step)
                elapsed += step
            self.assertAlmostEqual(motion.visual.total, target)
            motion.request(target + 0.2)
            self.assertAlmostEqual(motion.visual.total, target)
            motion.update(0.12)
            self.assertAlmostEqual(motion.visual.total, target + 0.2)

    def test_repeated_scene_charge_updates_catch_up_without_delaying_real_energy(self):
        program = SAMPLE.create_test()
        program.set_energy_charge(EnergyCharge(0))
        for frame in range(12):
            total = (frame + 1) / 10
            program.set_energy_charge(EnergyCharge(total))
            self.assertAlmostEqual(EnergyCharge.from_state(program.state).total, total)
            program.update(0.01)
        self.assertAlmostEqual(program.energy_fill.visual.total, 1.2)

    def test_retarget_starts_from_current_display_and_identical_target_does_not_restart(self):
        motion = EnergyFillMotion()
        motion.reset(0.2)
        motion.request(0.8)
        self.assertEqual(motion.visual.total, 0.2)
        motion.update(0.06)
        self.assertAlmostEqual(motion.visual.total, 0.5)
        motion.request(0.9)
        self.assertAlmostEqual(motion.visual.total, 0.5)
        motion.update(0.06)
        motion.request(0.9)
        motion.update(0.06)
        self.assertEqual(motion.visual.total, 0.9)
        motion.request(0.1)
        self.assertEqual(motion.visual.total, 0.1)

    def test_level_crossing_moves_forward_in_total_and_overdrive_uses_its_own_fill(self):
        motion = EnergyFillMotion()
        motion.reset(0.95)
        motion.request(1.05)
        totals, levels = [], []
        for _ in range(12):
            motion.update(0.01)
            totals.append(motion.visual.total)
            levels.append(motion.visual.level)
        self.assertEqual(totals, sorted(totals))
        self.assertIn(1, levels)
        self.assertIn(2, levels)
        self.assertAlmostEqual(motion.visual.ratio, 0.05)
        motion.reset(3)
        motion.request(4)
        motion.update(0.06)
        self.assertEqual(motion.visual.ratio, 1)
        self.assertAlmostEqual(motion.visual.overdrive_ratio, 0.5)
        self.assertFalse(motion.visual.active)

    def test_actual_charge_is_immediate_while_display_freezes_on_pause_and_resets(self):
        program = SAMPLE.create_test()
        program.set_energy_charge(EnergyCharge(0.2))
        program.set_energy_charge(EnergyCharge(0.8))
        self.assertEqual(EnergyCharge.from_state(program.state).total, 0.8)
        self.assertEqual(program.energy_fill.visual.total, 0.2)
        program.update(0.06)
        self.assertAlmostEqual(program.energy_fill.visual.total, 0.5)
        program.pause.request(True)
        program.pause.update(1)
        program.update(1)
        self.assertAlmostEqual(program.energy_fill.visual.total, 0.5)
        program.pause.request(False)
        program.pause.update(1)
        program.update(0.06)
        self.assertEqual(program.energy_fill.visual.total, 0.8)
        program.reset()
        self.assertEqual(program.energy_fill.visual, EnergyCharge.from_state(program.state))

    def test_view_uses_display_boundary_without_changing_logical_readiness(self):
        program = SAMPLE.create_test()
        state = replace(program.state, energy_level=3, energy_ratio=1)
        renderer = Mock()
        renderer.text_size.return_value = (12, 18)
        view = UiV2View(program.config, renderer)
        with patch.object(view, 'energy_boundary') as boundary, patch.object(view, 'ultimate_icon') as icon:
            view.resources(state, 1, 0, 1, energy_visual=EnergyCharge(1.4))
        self.assertAlmostEqual(boundary.call_args.args[1], 0.4)
        self.assertTrue(icon.call_args.args[0].ultimate_ready)


if __name__ == '__main__':
    unittest.main()

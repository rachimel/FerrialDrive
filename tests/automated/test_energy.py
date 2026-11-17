"""실제 에너지 용량·자연 감소 유예·레벨 경계와 HUD 회복 연결을 검사한다."""

from math import isclose
from pathlib import Path
import unittest

from ferrial_drive.combat.energy import EnergyAmount, EnergyDecay, EnergySettings
from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.ui_v2.movement_hud import MovementHud
from ferrial_drive.ui_v2.preview import HudPreview


ROOT = Path(__file__).resolve().parents[2]


class EnergyTests(unittest.TestCase):
    def test_level_capacities_and_overdrive_are_real_units_with_independent_ratios(self):
        for total, amount, extra, level, ratio in ((.5, 50, 0, 1, .5), (1.5, 200, 0, 2, .5),
                                                  (2.5, 500, 0, 3, .5), (3.5, 700, 100, 3, 1),
                                                  (4, 700, 200, 3, 1)):
            with self.subTest(total=total):
                energy = EnergyAmount.from_display(total)
                self.assertEqual((energy.amount, energy.overdrive_amount, energy.level, energy.ratio),
                                 (amount, extra, level, ratio))
                self.assertEqual(energy.display_total, total)
        energy = EnergyAmount.from_ratios(2, .25, .5)
        self.assertEqual((energy.amount, energy.overdrive_amount, energy.display_total), (150, 100, 1.25))

    def test_raw_recovery_carries_over_level_and_general_capacity_boundaries(self):
        energy = EnergyAmount(98).recover(5)
        self.assertEqual((energy.amount, energy.level, energy.ratio), (103, 2, .015))
        energy = EnergyAmount(699, 190).recover(21)
        self.assertEqual((energy.amount, energy.overdrive_amount), (700, 200))
        self.assertEqual(energy.recover(1000), energy)

    def test_consumption_preserves_extra_charge_and_applies_previous_max_minus_one(self):
        energy = EnergyAmount(300.25, 100).consume(.5)
        self.assertEqual((energy.amount, energy.level, energy.overdrive_amount), (298.75, 2, 100))
        self.assertEqual(energy.ratio, 198.75 / 200)
        self.assertEqual(EnergyAmount(100, 100).consume(.5).amount, 98.5)
        self.assertEqual(energy.consume(1000), EnergyAmount(0, 100))
        self.assertEqual(EnergyAmount(300).consume(0).amount, 300)

    def test_two_second_grace_and_decay_are_independent_of_frame_partition(self):
        settings = EnergySettings()
        self.assertEqual(settings.capacity, 700)
        decay = EnergyDecay(settings)
        self.assertEqual(decay.update(1.5), 0)
        self.assertEqual(decay.update(.5), 0)
        self.assertEqual(decay.update(.5), .25)
        decay.reset()
        self.assertEqual(decay.grace_remaining_seconds, 2)
        self.assertEqual(decay.update(20, suspended=True), 0)
        self.assertEqual(decay.grace_remaining_seconds, 2)
        whole, split = EnergyAmount(301, 100), EnergyAmount(301, 100)
        whole_decay, split_decay = EnergyDecay(), EnergyDecay()
        whole = whole.consume(whole_decay.update(7))
        for _ in range(700):
            split = split.consume(split_decay.update(.01))
        self.assertAlmostEqual(split.amount, whole.amount)
        self.assertEqual(split.overdrive_amount, whole.overdrive_amount)

    def test_invalid_settings_amounts_and_time_are_rejected(self):
        for options in ({"level_capacities": [100, 200]}, {"level_capacities": [100, 0, 400]},
                        {"overdrive_capacity": 0}, {"decay_margin_seconds": -1},
                        {"decay_per_second": float("nan")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                EnergySettings(**options)
        for options in ({"amount": -1}, {"amount": 701}, {"overdrive_amount": 201}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                EnergyAmount(**options)
        for value in (-1, float("inf"), float("nan")):
            for operation in (EnergyAmount().consume, EnergyAmount().recover, EnergyAmount().recover_ratio,
                              EnergyDecay().update):
                with self.subTest(operation=operation, value=value), self.assertRaises(ValueError):
                    operation(value)


class EnergyHudTests(unittest.TestCase):
    def test_half_absorption_gain_applies_to_cpu_and_compute_arrivals(self):
        for compute in (False, True):
            recovered = []
            for multiplier in (1, .5):
                hud = MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json",
                    ROOT / "samples/ui_unit_test_v2/hud_sample.json",
                    energy_settings=EnergySettings(absorption_gain_multiplier=multiplier))
                if not compute:
                    hud.particle_system = None
                hud.set_energy_amount(EnergyAmount(0, settings=hud.energy_settings))
                hud.absorb()
                if compute:
                    hud.particle_system.accept_receipt(100000, 3, 0)
                    HudPreview.update(hud, 0)
                else:
                    HudPreview.update(hud, max(t.duration_seconds for t in hud.absorption.trails))
                recovered.append(hud.energy_amount.amount)
            self.assertGreater(recovered[0], 0)
            self.assertAlmostEqual(recovered[1], recovered[0] * .5)

    def make_hud(self):
        return MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json",
                           ROOT / "samples/ui_unit_test_v2/hud_sample.json")

    def test_decay_uses_real_units_for_each_level_and_freezes_on_pause(self):
        for amount, level, capacity in ((50, 1, 100), (200, 2, 200), (500, 3, 400)):
            with self.subTest(level=level):
                hud = self.make_hud()
                hud.set_energy_amount(EnergyAmount(amount))
                HudPreview.update(hud, 2)
                self.assertAlmostEqual(hud.energy_amount.amount, amount)
                hud.pause.request(True)
                HudPreview.update(hud, 20)
                self.assertAlmostEqual(hud.energy_amount.amount, amount)
                hud.pause.reset()
                HudPreview.update(hud, .5)
                self.assertAlmostEqual(hud.energy_amount.amount, amount - .25)
                self.assertAlmostEqual(hud.state.energy_ratio, .5 - .25 / capacity)

    def test_actual_cpu_and_compute_recovery_restart_grace_not_emission(self):
        for compute in (False, True):
            with self.subTest(compute=compute):
                hud = self.make_hud()
                if not compute:
                    hud.particle_system = None
                hud.set_energy_amount(EnergyAmount(200))
                HudPreview.update(hud, 1.9)
                hud.absorb()
                self.assertAlmostEqual(hud.energy_decay.grace_remaining_seconds, .1)
                if compute:
                    hud.particle_system.accept_receipt(100000, 3, 0)
                    HudPreview.update(hud, 0)
                else:
                    HudPreview.update(hud, hud.absorption.trails[0].duration_seconds)
                self.assertGreater(hud.energy_amount.amount, 200)
                self.assertEqual(hud.energy_decay.grace_remaining_seconds, 2)
                before = hud.energy_amount.amount
                HudPreview.update(hud, 2)
                self.assertAlmostEqual(hud.energy_amount.amount, before)
                HudPreview.update(hud, .2)
                self.assertAlmostEqual(hud.energy_amount.amount, before - .1)

    def test_partial_overdrive_charge_survives_decay_without_filling_regular_energy(self):
        hud = self.make_hud()
        hud.set_energy_amount(EnergyAmount(700, 100))
        HudPreview.update(hud, 2.5)
        self.assertAlmostEqual(hud.energy_amount.amount, 699.75)
        self.assertEqual(hud.energy_amount.overdrive_amount, 100)
        self.assertEqual(hud.state.overdrive_charge_ratio, .5)
        self.assertLess(EnergyCharge.from_state(hud.state).total, 3)
        self.assertFalse(hud.state.overdrive_ready)

    def test_standby_suspends_decay_and_expiry_restarts_grace(self):
        hud = self.make_hud()
        hud.set_energy_charge(EnergyCharge(4))
        HudPreview.update(hud, 1)
        self.assertEqual(hud.energy_decay.grace_remaining_seconds, 2)
        self.assertEqual(hud.energy_amount.amount, 700)
        HudPreview.update(hud, 2)
        self.assertFalse(hud.state.overdrive_ready)
        self.assertEqual((hud.energy_amount.amount, hud.energy_decay.grace_remaining_seconds), (300, 2))
        HudPreview.update(hud, 2)
        self.assertEqual(hud.energy_amount.amount, 300)
        HudPreview.update(hud, .2)
        self.assertAlmostEqual(hud.energy_amount.amount, 298.9)
        self.assertEqual(hud.state.energy_level, 2)

    def test_overdrive_keeps_separate_clock_and_menu_does_not_consume_grace(self):
        hud = self.make_hud()
        hud.set_energy_charge(EnergyCharge(4))
        hud.perform("activate_overdrive")
        HudPreview.update(hud, 1)
        self.assertEqual(hud.energy_decay.grace_remaining_seconds, 2)
        remaining = hud.overdrive_controller.settings.duration_seconds - 1
        self.assertEqual(hud.state.overdrive_remaining_seconds, remaining)
        HudPreview.update(hud, remaining)
        self.assertFalse(hud.state.overdrive)
        self.assertEqual((hud.energy_amount.amount, hud.energy_decay.grace_remaining_seconds), (0, 2))
        hud.set_energy_amount(EnergyAmount(200))
        hud.transition.request("menu")
        HudPreview.update(hud, 10)
        self.assertTrue(isclose(hud.energy_amount.amount, 200))
        self.assertEqual(hud.energy_decay.grace_remaining_seconds, 2)


if __name__ == "__main__":
    unittest.main()

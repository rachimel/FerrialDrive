"""Standby·수동 발동·종료·독립 시계와 이동·피해·스왑 강화를 확인한다."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from ferrial_drive.combat.locomotion import LocomotionController
from ferrial_drive.combat.movement_application import MovementApplication
from ferrial_drive.combat.overdrive import OverdriveController
from ferrial_drive.combat.sword_effects import SwordTarget
from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.particles.system import StepParticles
from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.ui_v2.movement_hud import MovementHud
from ferrial_drive.ui_v2.preview import HudPreview

ROOT = Path(__file__).resolve().parents[2]


class OverdriveTests(unittest.TestCase):
    def make_hud(self):
        return MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json", ROOT / "samples/ui_unit_test_v2/hud_sample.json")

    def test_only_full_charge_enters_standby_and_recovery_does_not_extend_it(self):
        control = OverdriveController()
        control.observe_charge(3.99)
        self.assertFalse(control.activate())
        control.observe_charge(4)
        self.assertTrue(control.ready)
        self.assertFalse(control.active)
        self.assertEqual(control.cooldown_remaining_seconds, 30)
        control.update(1)
        control.observe_charge(4)
        self.assertEqual(control.standby_remaining_seconds, 2)
        self.assertEqual(control.update(2), 2)
        self.assertFalse(control.ready)
        self.assertFalse(control.activate())
        self.assertEqual(control.cooldown_remaining_seconds, 27)
        control.observe_charge(4)
        control.update(26.5)
        self.assertFalse(control.ready)
        control.update(.75)
        self.assertTrue(control.ready)
        self.assertAlmostEqual(control.standby_remaining_seconds, 2.75)
        self.assertAlmostEqual(control.cooldown_remaining_seconds, 29.75)

    def test_active_duration_is_ten_real_seconds_and_cannot_be_restarted(self):
        control = OverdriveController()
        control.observe_charge(4)
        control.update(1)
        self.assertTrue(control.activate())
        control.update(2)
        self.assertFalse(control.activate())
        control.observe_charge(4)
        self.assertEqual(control.active_remaining_seconds, 8)
        self.assertEqual(control.update(8), 0)
        self.assertFalse(control.active)
        self.assertEqual(control.cooldown_remaining_seconds, 19)

    def test_hud_separates_animation_cooldown_and_overdrive_clocks_and_freezes_on_pause(self):
        hud = self.make_hud()
        hud.set_energy_charge(EnergyCharge(4))
        hud.perform("activate_overdrive")
        hud.state = replace(hud.state, ultimate_cooldown_seconds=5, skill_cooldown_seconds=5,
                            back_weapon_cooldown_seconds=5)
        hud.perform("swap")
        HudPreview.update(hud, .04)
        self.assertAlmostEqual(hud.weapon_swap.visual.elapsed_seconds, .08)
        self.assertAlmostEqual(hud.state.overdrive_remaining_seconds, 9.96)
        for name in ("ultimate_cooldown_seconds", "skill_cooldown_seconds", "back_weapon_cooldown_seconds"):
            self.assertAlmostEqual(getattr(hud.state, name), 4.92)
        before = hud.state
        hud.pause.request(True)
        HudPreview.update(hud, .4)
        self.assertEqual(hud.state.overdrive_remaining_seconds, before.overdrive_remaining_seconds)
        self.assertEqual(hud.state.back_weapon_cooldown_seconds, before.back_weapon_cooldown_seconds)
        hud.pause.reset()
        HudPreview.update(hud, 9.96)
        self.assertFalse(hud.state.overdrive)
        self.assertEqual(EnergyCharge.from_state(hud.state).total, 0)

    def test_r_activates_only_standby_and_never_resets_the_player(self):
        import pico2d.pico2d as pico
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        app.hud, app.pico = self.make_hud(), pico
        app.controller.position_m = (400, 400)
        event = SimpleNamespace(type=pico.SDL_KEYDOWN, key=pico.SDLK_r, repeat=False)
        app.handle_event(event)
        self.assertFalse(app.hud.state.overdrive)
        self.assertEqual(app.controller.position_m, (400, 400))
        app.hud.set_energy_charge(EnergyCharge(4))
        app.handle_event(event)
        self.assertTrue(app.hud.state.overdrive)
        self.assertEqual(app.controller.position_m, (400, 400))
        app.update_hud(.2)
        app.handle_event(event)
        self.assertAlmostEqual(app.hud.state.overdrive_remaining_seconds, 9.8)

    def test_movement_multiplier_affects_run_dash_boost_and_attack_override_once(self):
        for dash, boost, attack_speed in ((False, False, None), (True, False, None), (False, True, None), (False, False, 27)):
            distances = []
            for multiplier in (1, 1.5):
                controller = LocomotionController()
                controller.speed_multiplier = multiplier
                if boost:
                    controller.request_boost((1, 0), (1, 0))
                options = {} if attack_speed is None else {"movement_speed_mps": attack_speed}
                controller.update(.2, (1, 0), (1, 0), dash=dash, **options)
                distances.append(controller.position_m[0] - 500)
            self.assertAlmostEqual(distances[1], distances[0] * 1.5)

    def test_active_sword_hit_deals_150_and_supplies_trail_and_animation_multipliers(self):
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        app.hud = self.make_hud()
        app.sword_targets = [SwordTarget("A", Vec2(50, 25), 3)]
        app.bind_hud_world()
        app.hud.set_energy_charge(EnergyCharge(4))
        app.hud.perform("activate_overdrive")
        app.playback = Mock()
        app.current_energy_color = Mock(return_value="#FF4044")
        app.sword_effects = SimpleNamespace(hits=[(1, "A")], update=Mock())
        app.target_hits = {"A": 0}
        before = app.hud.enemies["A"]["health"].current
        app.update(.1)
        self.assertEqual(before - app.hud.enemies["A"]["health"].current, 150)
        self.assertEqual(app.hud.damage_numbers.popups[0].amount, 150)
        self.assertAlmostEqual(app.sword_effects.update.call_args.args[0], .1)
        self.assertEqual(app.sword_effects.update.call_args.kwargs["reach_multiplier"], 1.15)
        self.assertEqual(app.controller.speed_multiplier, 1.5)

    def test_attack_animation_doubles_and_modifiers_restore_at_expiry(self):
        from tests.automated.test_sword_movement_combat import combat
        phases = []
        for active in (False, True):
            app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
            app.combat = combat(acceleration="constant")
            app.controller = app.combat.controller
            app.playback, app.hud = Mock(), self.make_hud()
            if active:
                app.hud.set_energy_charge(EnergyCharge(4))
                app.hud.perform("activate_overdrive")
            app.combat.request_attack((1, 0))
            app.update(.05)
            phases.append(app.combat.combo.elapsed_seconds)
            if active:
                app.update_hud(9.95)
                self.assertFalse(app.hud.state.overdrive)
                self.assertEqual(app.controller.speed_multiplier, 1)
                self.assertEqual(app.combat.speed, 1.5)
        self.assertAlmostEqual(phases[1], phases[0] * 2)

    def test_sword_trail_follows_attack_phase_but_ages_and_pauses_in_real_time(self):
        from tests.automated.test_sword_effects import make_effects
        from tests.automated.test_sword_movement_combat import combat

        phases = []
        for active in (False, True):
            with self.subTest(overdrive=active):
                app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
                app.combat = combat(acceleration="constant")
                app.controller = app.combat.controller
                app.playback, app.hud = Mock(), self.make_hud()
                app.hud.set_energy_charge(EnergyCharge(4 if active else 3))
                if active:
                    app.hud.perform("activate_overdrive")
                app.energy_level = 3
                app.current_energy_color = Mock(return_value="#FF4044" if active else "#A0E6FF")
                app.sword_effects = make_effects()
                app.combat.request_attack((1, 0))
                app.update(.05)

                phase = app.combat.combo.elapsed_seconds
                phases.append(phase)
                effect = app.sword_effects
                self.assertAlmostEqual(effect.time_seconds, .05)
                self.assertTrue(effect.sections)
                self.assertTrue(effect.echoes)
                self.assertLessEqual(max(section.created_seconds for section in effect.sections), .05 + 1e-9)
                edge = effect.sections[-1].tip_b - effect.sections[-1].root_b
                self.assertAlmostEqual(edge.y / edge.x, phase)

                # 공격 종료 뒤에도 남은 Trail·잔상의 수명은 동일한 실제 초로 흐른다.
                app.combat = None
                section, echo = effect.sections[-1], effect.echoes[-1]
                before = effect.opacity(section), effect.opacity(echo)
                app.paused = True
                app.update(.1)
                self.assertEqual((effect.opacity(section), effect.opacity(echo)), before)
                app.paused = False
                app.hud.pause.reset()
                app.update(.1)
                self.assertAlmostEqual(effect.opacity(section), before[0] - .1 / section.lifetime_seconds)
                self.assertAlmostEqual(effect.opacity(echo), before[1] - .1 / echo.lifetime_seconds)
                app.update(.1)
                self.assertIn(section, effect.sections)
                app.update(.1)
                self.assertFalse(effect.sections)
                self.assertFalse(effect.echoes)
        self.assertAlmostEqual(phases[1], phases[0] * 2)

    def test_ground_vfx_and_rim_use_real_time_while_body_animation_stays_fast(self):
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        app.hud, app.playback = self.make_hud(), Mock()
        app.hud.set_energy_charge(EnergyCharge(4))
        app.hud.perform("activate_overdrive")
        app.ground_effects = Mock()
        app.update_ground_effects = Mock()
        app.update(.04)
        self.assertAlmostEqual(app.update_ground_effects.call_args.args[0], .04)
        self.assertAlmostEqual(app.rim_elapsed_seconds, .04)
        self.assertAlmostEqual(app.playback.update.call_args.args[2], .08)
        app.paused = True
        app.update(.04)
        app.update_ground_effects.assert_called_once()
        self.assertAlmostEqual(app.rim_elapsed_seconds, .04)

    def test_hud_vfx_use_real_time_for_cpu_and_compute_and_freeze_on_pause(self):
        for compute in (False, True):
            with self.subTest(compute=compute):
                hud = self.make_hud()
                if not compute:
                    hud.particle_system = None
                    hud.absorption.add((0, 0), (10, 0), (20, 0))
                hud.set_energy_charge(EnergyCharge(4))
                hud.perform("activate_overdrive")
                hud.perform("swap")
                hud.energy_flash.trigger()
                hud.player_flash.trigger(1, .5)
                hud.target_flash.trigger(1, .5)
                HudPreview.update(hud, .04)
                self.assertAlmostEqual(hud.weapon_swap.visual.elapsed_seconds, .08)
                self.assertAlmostEqual(hud.energy_flash.elapsed_seconds, .04)
                before = (hud.player_flash.visuals, hud.target_flash.visuals)
                self.assertTrue(all(before))
                if compute:
                    commands = list(hud.particle_system.commands)
                    self.assertAlmostEqual(sum(command.delta_seconds for command in commands
                                               if isinstance(command, StepParticles)), .04)
                else:
                    trail = hud.absorption.trails[0]
                    self.assertAlmostEqual(trail.progress, .04 / trail.duration_seconds)
                    progress = trail.progress
                hud.pause.request(True)
                HudPreview.update(hud, .4)
                self.assertAlmostEqual(hud.energy_flash.elapsed_seconds, .04)
                self.assertEqual((hud.player_flash.visuals, hud.target_flash.visuals), before)
                if compute:
                    self.assertEqual(hud.particle_system.commands, commands)
                else:
                    self.assertEqual(hud.absorption.trails[0].progress, progress)


if __name__ == "__main__":
    unittest.main()

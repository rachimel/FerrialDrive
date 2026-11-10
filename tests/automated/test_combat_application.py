"""실제 Pico2D 렌더링과 입력·일시정지·포커스 상실·재시작 연결을 검사한다."""

import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ferrial_drive.combat.application import CombatApplication
from ferrial_drive.combat.simulation import Vec2
from ferrial_drive.rendering import PicoCanvas
from ferrial_drive.runtime import run_application


ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "samples/combat_prototype/combat_config.json"
UI_CONFIG = ROOT / "samples/ui_unit_test/ui_config.json"


class CombatApplicationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, SDL_VIDEODRIVER="dummy")
        self.environment.start()
        self.program = CombatApplication(SCENARIO, UI_CONFIG)
        self.canvas = PicoCanvas(1280, 720, "Combat integration").open()
        try:
            self.program.enter()
        except BaseException:
            self.program.exit()
            self.canvas.close()
            self.environment.stop()
            raise

    def tearDown(self):
        try:
            self.program.exit()
        finally:
            self.canvas.close()
            self.environment.stop()

    def key(self, key, down=True):
        p = self.program.pico
        self.program.handle_event(SimpleNamespace(type=p.SDL_KEYDOWN if down else p.SDL_KEYUP,
                                                   key=key, repeat=False))

    def start(self):
        self.key(self.program.pico.SDLK_RETURN)

    def test_start_pause_and_focus_loss_prevent_stuck_movement(self):
        app, p = self.program, self.program.pico
        start = app.world.player.position
        app.update(0.1)
        app.draw()
        self.assertEqual(app.world.player.position, start)
        self.start()
        self.key(p.SDLK_w)
        app.update(0.1)
        moved = app.world.player.position
        self.assertGreater(moved.y, start.y)
        app.handle_event(SimpleNamespace(type=p.SDL_WINDOWEVENT, window_event=p.SDL_WINDOWEVENT_FOCUS_LOST))
        app.update(0.1)
        self.assertTrue(app.paused)
        self.assertFalse(app.keys)
        self.assertEqual(app.world.player.position, moved)
        self.start()
        app.update(0.1)
        self.assertEqual(app.world.player.position, moved)

    def test_actual_shooting_drives_hud_and_restart_clears_all_state(self):
        app, p = self.program, self.program.pico
        self.start()
        self.key(p.SDLK_e)
        x, y = app.view.project(app.world.enemy.position, app.world.player.position)
        app.handle_event(SimpleNamespace(type=p.SDL_MOUSEBUTTONDOWN, button=p.SDL_BUTTON_LEFT, x=x, y=y))
        for _ in range(40):
            app.update(1 / 60)
        app.draw()
        self.assertGreater(app.world.total_damage, 0)
        self.assertGreater(app.world.hit_count, 0)
        self.assertLess(app.view.hud_state(app.world).target.health.ratio, 1)
        self.assertLess(app.view.hud_state(app.world).loadouts[0].ranged.rounds, 45)
        self.key(p.SDLK_r)
        self.assertEqual(app.world.total_damage, 0)
        self.assertEqual(app.world.ammo, 45)
        self.assertFalse(app.damage_numbers.popups)
        self.assertFalse(app.buttons)
        self.assertEqual(app.damage_counter.visual.value, 0)
        app.draw()

    def test_projection_and_inverse_aim_share_the_same_world_direction(self):
        view, world = self.program.view, self.program.world
        for direction in (Vec2(1, 0), Vec2(0, 1), Vec2(-1, -1)):
            screen = view.project(world.player.position + direction * 100, world.player.position)
            recovered = view.aim_direction(screen).normalized()
            expected = direction.normalized()
            self.assertAlmostEqual(recovered.x, expected.x)
            self.assertAlmostEqual(recovered.y, expected.y)

    def hit_enemy(self):
        app = self.program
        app.world.enemy.position = app.world.player.position + Vec2(100, 0)
        app.mouse = app.view.project(app.world.enemy.position, app.world.player.position)
        app.attack_pressed = True
        app.update(0.12)

    def test_counter_expiry_resets_values_and_next_hit_starts_new_totals(self):
        app = self.program
        self.start()
        self.hit_enemy()
        first_damage = app.world.total_damage
        self.assertEqual(app.world.hit_count, 1)
        visibility = app.counter_visibility
        app.update(visibility.hold_seconds + visibility.fade_seconds / 2 - visibility.elapsed_seconds)
        self.assertGreater(visibility.opacity, 0)
        self.assertLess(visibility.opacity, 1)
        self.assertEqual(app.world.total_damage, first_damage)
        enemy_health = app.world.enemy.health
        app.update(visibility.fade_seconds / 2 + 0.01)
        self.assertEqual(visibility.opacity, 0)
        self.assertEqual((app.world.hit_count, app.world.total_damage), (0, 0))
        self.assertEqual(app.world.enemy.health, enemy_health)
        for counter in (app.hit_counter, app.damage_counter):
            self.assertEqual((counter.visual.previous_value, counter.visual.value, counter.latest_value), (0, 0, 0))
        app.draw()
        self.hit_enemy()
        self.assertEqual(app.world.hit_count, 1)
        self.assertEqual(app.world.total_damage, first_damage)
        self.assertEqual(visibility.opacity, 1)

    def test_hit_during_counter_fade_extends_totals_and_pause_freezes_expiry(self):
        app = self.program
        self.start()
        self.hit_enemy()
        first_damage = app.world.total_damage
        visibility = app.counter_visibility
        app.update(visibility.hold_seconds + visibility.fade_seconds / 2 - visibility.elapsed_seconds)
        self.hit_enemy()
        self.assertEqual(app.world.hit_count, 2)
        self.assertEqual(app.world.total_damage, first_damage * 2)
        self.assertEqual(visibility.opacity, 1)
        self.key(app.pico.SDLK_ESCAPE)
        elapsed = visibility.elapsed_seconds
        app.update(visibility.hold_seconds + visibility.fade_seconds + 1)
        self.assertEqual(visibility.elapsed_seconds, elapsed)
        self.assertEqual(app.world.hit_count, 2)
        self.start()
        app.update(visibility.hold_seconds + visibility.fade_seconds)
        self.assertEqual((app.world.hit_count, app.world.total_damage), (0, 0))

    def test_ammo_recovery_pauses_and_restart_clears_recovery_state(self):
        app, p = self.program, self.program.pico
        self.start()
        app.world.ammo = 10
        app.update(0.2)
        app.draw()
        for _ in range(6):
            app.update(0.2)
        app.draw()
        self.assertGreater(app.world.ammo_recovery_fraction, 0)
        self.key(p.SDLK_ESCAPE)
        before = (app.world.elapsed_seconds, app.world.ammo, app.world.ammo_recovery_fraction)
        app.update(0.2)
        self.assertEqual(before, (app.world.elapsed_seconds, app.world.ammo, app.world.ammo_recovery_fraction))
        self.key(p.SDLK_r)
        self.assertEqual(app.world.ammo, 45)
        self.assertEqual(app.world.ammo_recovery_fraction, 0)
        self.assertEqual(app.world.last_shot_seconds, 0)

    def test_repeat_key_does_not_retrigger_dash_and_close_is_local(self):
        app, p = self.program, self.program.pico
        self.start()
        self.key(p.SDLK_SPACE)
        app.update(0.2)
        position = app.world.player.position
        self.key(p.SDLK_SPACE)
        app.update(0.1)
        self.assertEqual(app.world.player.position, position)
        app.handle_event(SimpleNamespace(type=p.SDL_WINDOWEVENT, window_event=p.SDL_WINDOWEVENT_CLOSE))
        self.assertFalse(app.running)

    def test_overlay_draws_after_victory_and_defeat(self):
        self.start()
        for result in ("victory", "defeat"):
            self.program.world.result = result
            self.program.draw()


class CombatRuntimeTests(unittest.TestCase):
    def test_separate_runs_release_canvas_and_fonts(self):
        with patch.dict(os.environ, SDL_VIDEODRIVER="dummy"):
            for _ in range(2):
                program = CombatApplication(SCENARIO, UI_CONFIG)
                run_application(program, width=1280, height=720, title="Combat lifecycle", frame_limit=2)
                self.assertFalse(program.renderer.fonts)
                self.assertIsNone(program.pico.renderer)


if __name__ == "__main__":
    unittest.main()

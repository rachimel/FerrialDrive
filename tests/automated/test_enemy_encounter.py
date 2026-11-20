"""다수 적 교전의 공격 방향·회피·사망·승패와 기존 HUD 연결을 확인한다."""

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ferrial_drive.combat.enemy_encounter import EnemyEncounter, EnemyProjectile
from ferrial_drive.combat.enemy_sprites import EnemySprite
from ferrial_drive.combat.encounter_application import EncounterApplication
from ferrial_drive.combat.encounter_view import use_shared_frame
from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.rendering.canvas import PicoCanvas
from Tools.unit_test_runner.entrypoints import inspect_entrypoint

ROOT = Path(__file__).resolve().parents[2]
ENCOUNTER = ROOT / "samples/combat_test_v1_5/encounter.json"
CONFIG = ROOT / "samples/sword_movement/movement_config.json"


def world(kind="small", position=(510, 500)):
    settings = json.loads(ENCOUNTER.read_text(encoding="utf-8"))
    settings["spawns"] = [{"id": "test", "profile": kind, "position_m": position}]
    return EnemyEncounter(settings, map_size_m=1000, player_radius_m=2.5)


class EnemyRulesTests(unittest.TestCase):
    def test_crowd_uses_requested_formation_across_reset(self):
        for count in (900, 1000):
            with self.subTest(count=count):
                app = EncounterApplication(CONFIG, encounter_path=ENCOUNTER, demo=True, mute=True,
                                           enemy_count=count, enemy_spacing_m=24)
                enemies = app.encounter.enemies
                self.assertEqual(len(enemies), count)
                self.assertEqual(enemies["crowd0001"].position_m.x - enemies["crowd0000"].position_m.x, 24)
                self.assertEqual(enemies["crowd0030"].profile, enemies["crowd0000"].profile)
                positions = [enemy.position_m for enemy in enemies.values()]
                app.encounter.reset()
                self.assertEqual([enemy.position_m for enemy in app.encounter.enemies.values()], positions)
        default = EncounterApplication(CONFIG, encounter_path=ENCOUNTER, demo=True, mute=True)
        self.assertEqual(len(default.encounter.enemies), 30)
        self.assertIn("S1", default.encounter.enemies)

    def test_invalid_crowd_rejected_before_start(self):
        for count, spacing in ((0, 12), (900, 0), (900, float("nan")), (1000, 1000)):
            with self.subTest(count=count, spacing=spacing), self.assertRaises(ValueError):
                EncounterApplication(CONFIG, encounter_path=ENCOUNTER, demo=True, mute=True,
                                     enemy_count=count, enemy_spacing_m=spacing)

    def test_shared_frame_distance_and_lock(self):
        enemy = world(position=(516, 500)).enemies["test"]
        self.assertFalse(use_shared_frame(enemy, (500, 500), None, 16))
        enemy.position_m = Vec2(516, 501)
        self.assertTrue(use_shared_frame(enemy, (500, 500), None, 16))
        self.assertFalse(use_shared_frame(enemy, (500, 500), "test", 16))
        self.assertFalse(use_shared_frame(enemy, (500, 500), None, None))

    def test_configured_attack_motion_uses_its_own_phase_frames(self):
        enemy = world("humanoid").enemies["test"]
        counts = dict(move=12, attack=12, hit=4, **{"break": 12}, rifle=18)
        resource = SimpleNamespace(data={"sample_fps": 24, "motions": dict.fromkeys(counts, tuple("01234567"))})
        sprite = EnemySprite(resource, 1, 16, (4, 8), {}, counts, {"ranged": {"motion": "rifle", "attack_frames": [6, 14]}})
        sprite.validate()
        enemy.phase, enemy.remaining_seconds = "active", enemy.profile.active_seconds
        for kind, expected in (("melee", ("attack", 4)), ("ranged", ("rifle", 6))):
            enemy.attack_kind = kind
            motion, _, seconds = sprite.playback(enemy)
            self.assertEqual((motion, seconds * 12), expected)
        sprite.attack_motions["ranged"]["attack_frames"] = [14, 19]
        with self.assertRaises(ValueError):
            sprite.validate()

    def test_gun_knockback_is_weak_and_frame_rate_independent(self):
        for kind, distance in (("small", .3), ("medium", .14), ("humanoid", .07)):
            for fps in (30, 60, 144):
                encounter = world(kind, (500, 500))
                enemy = encounter.enemies['test']
                enemy.phase, enemy.remaining_seconds = 'windup', .5
                encounter.knock_back('test', Vec2(3, 4), source='gun')
                for _ in range(fps):
                    encounter.advance_reactions(1 / fps)
                self.assertAlmostEqual(enemy.position_m.x, 500 + distance * .6)
                self.assertAlmostEqual(enemy.position_m.y, 500 + distance * .8)
                self.assertEqual(enemy.phase, 'windup')
                self.assertEqual(enemy.remaining_seconds, .5)
                self.assertEqual(enemy.knockback_remaining_seconds, 0)

    def test_continuous_gun_hits_do_not_cancel_enemy_attack(self):
        encounter = world('medium', (530, 500))
        for _ in range(30):
            encounter.knock_back('test', Vec2(1, 0), source='gun')
            encounter.advance(.03, (500, 500), (500, 500))
        self.assertGreater(encounter.shots_fired, 0)
        self.assertFalse(encounter.enemies['test'].knockback_interrupts)

    def test_gun_push_does_not_stack_velocity_or_overwrite_sword_reaction(self):
        encounter = world()
        enemy = encounter.enemies['test']
        encounter.knock_back('test', Vec2(1, 0), source='gun')
        velocity = enemy.knockback_velocity_mps
        for _ in range(10):
            encounter.knock_back('test', Vec2(1, 0), source='gun')
        self.assertEqual(enemy.knockback_velocity_mps, velocity)
        encounter.knock_back('test', Vec2(0, 1))
        encounter.advance_reactions(.02)
        reaction = enemy.knockback_velocity_mps, enemy.knockback_remaining_seconds
        encounter.knock_back('test', Vec2(1, 0), source='gun')
        self.assertEqual((enemy.knockback_velocity_mps, enemy.knockback_remaining_seconds), reaction)
        self.assertTrue(enemy.knockback_interrupts)

    def test_knockback_distance_matches_weight_and_frame_rate(self):
        for kind, distance in (("small", 3), ("medium", 1.4), ("humanoid", .7)):
            for fps in (30, 60, 144):
                encounter = world(kind, (500, 500))
                encounter.knock_back("test", Vec2(3, 4))
                remaining = encounter.knockback_seconds
                while remaining > 1e-9:
                    seconds = min(remaining, 1 / fps)
                    encounter.advance_reactions(seconds)
                    remaining -= seconds
                enemy = encounter.enemies["test"]
                self.assertAlmostEqual(enemy.position_m.x, 500 + distance * .6)
                self.assertAlmostEqual(enemy.position_m.y, 500 + distance * .8)
                self.assertEqual(enemy.knockback_remaining_seconds, 0)

    def test_knockback_interrupts_windup_and_lethal_motion_survives_victory(self):
        encounter = world("medium", (510, 500))
        encounter.advance(.1, (500, 500), (500, 500))
        encounter.knock_back("test", Vec2(1, 0))
        encounter.advance(.1, (500, 500), (500, 500))
        self.assertEqual(encounter.shots_fired, 0)
        enemy = encounter.enemies["test"]
        encounter.sync_health({"test": 0}, 100)
        self.assertEqual(encounter.result, "victory")
        before = enemy.position_m
        encounter.advance_reactions(.01)
        self.assertGreater(enemy.position_m.x, before.x)
        self.assertGreater(enemy.death_remaining_seconds, 0)
        encounter.advance_reactions(.3)
        self.assertEqual(enemy.death_remaining_seconds, 0)
        self.assertEqual(encounter.shots_fired, 0)
        encounter.reset()
        self.assertEqual(encounter.enemies["test"].knockback_remaining_seconds, 0)

    def test_knockback_stops_at_arena_boundary(self):
        encounter = world(position=(998, 500))
        encounter.knock_back("test", Vec2(1, 0))
        encounter.advance_reactions(.12)
        self.assertEqual(encounter.enemies["test"].position_m.x, 998.5)

    def test_sprite_death_plays_once_even_without_knockback(self):
        encounter = world()
        encounter.sprite_death_seconds["small"] = 1.0
        enemy = encounter.enemies["test"]
        encounter.sync_health({"test": 0}, 100)
        self.assertEqual(enemy.death_remaining_seconds, 1.0)
        encounter.advance_reactions(.4)
        encounter.sync_health({"test": 0}, 100)
        self.assertAlmostEqual(enemy.death_remaining_seconds, .6)
        encounter.advance_reactions(1.0)
        self.assertEqual(enemy.death_remaining_seconds, 0)

    def test_damage_without_hud_clamps_and_does_not_repeat_death(self):
        encounter = world()
        enemy = encounter.enemies["test"]
        encounter.knock_back("test", Vec2(1, 0))
        maximum = enemy.health
        with self.assertRaises(ValueError):
            encounter.damage_enemy("test", -1)
        self.assertEqual(encounter.damage_enemy("test", 1), (maximum, maximum - 1))
        self.assertEqual(encounter.damage_enemy("test", maximum), (maximum - 1, 0))
        elapsed = encounter.death_seconds / 2
        encounter.advance_reactions(elapsed)
        self.assertEqual(encounter.damage_enemy("test", 1), (0, 0))
        self.assertAlmostEqual(enemy.death_remaining_seconds, encounter.death_seconds - elapsed)
        self.assertEqual(encounter.result, "victory")

    def test_small_closes_distance_and_hits_once_per_attack(self):
        encounter = world(position=(520, 500))
        encounter.advance(.2, (500, 500), (500, 500))
        self.assertLess(encounter.enemies["test"].position_m.x, 520)
        encounter.advance(.65, (500, 500), (500, 500))
        self.assertEqual(encounter.hits, [("test", 35)])
        hit, = encounter.hit_events
        self.assertEqual((hit.attacker_id, hit.attack_kind, hit.damage), ("test", "melee", 35))
        self.assertEqual(hit.direction, encounter.enemies["test"].facing)

    def test_windup_keeps_direction_and_sideways_dodge_avoids_melee(self):
        encounter = world(position=(507, 500))
        encounter.advance(.1, (500, 500), (500, 500))
        facing = encounter.enemies["test"].facing
        encounter.advance(.4, (500, 500), (507, 520))
        self.assertEqual(encounter.enemies["test"].facing, facing)
        self.assertEqual(encounter.hits, [])

    def test_medium_stays_ranged_even_when_close_and_retreats(self):
        encounter = world("medium", (510, 500))
        encounter.advance(.65, (500, 500), (500, 500))
        enemy = encounter.enemies["test"]
        self.assertEqual(enemy.attack_kind, "ranged")
        self.assertEqual(encounter.shots_fired, 1)
        encounter.advance(.2, (500, 500), (500, 500))
        self.assertGreater(enemy.position_m.x, 510)

    def test_sprite_plays_backward_walk_during_ranged_repositioning(self):
        encounter = world("medium", (510, 500))
        enemy = encounter.enemies["test"]
        sprite = EnemySprite(SimpleNamespace(data={"sample_fps": 24}), 1, 16, (7, 9), {},
                            {"move": 12, "attack": 12, "hit": 4, "break": 12})
        encounter.advance(.65, (500, 500), (500, 500))
        self.assertEqual(sprite.frame(enemy)[0], "attack/w")
        encounter.advance(.18, (500, 500), (500, 500))
        self.assertEqual(enemy.phase, "recovery")
        self.assertGreater(enemy.locomotion_step_m.x, 0)
        self.assertEqual(sprite.frame(enemy)[0], "move/w")
        frame = sprite.frame(enemy)[1]
        encounter.advance(.07, (500, 500), (500, 500))
        self.assertLess(sprite.frame(enemy)[1], frame)
        distance = enemy.locomotion_m
        encounter.knock_back("test", Vec2(1, 0))
        encounter.advance_reactions(.05)
        self.assertEqual(enemy.locomotion_m, distance)
        self.assertEqual(sprite.frame(enemy)[0], "hit/w")

    def test_humanoid_chooses_both_weapons_by_distance(self):
        for distance, kind in ((10, "melee"), (40, "ranged")):
            encounter = world("humanoid", (500 + distance, 500))
            encounter.advance(.01, (500, 500), (500, 500))
            self.assertEqual(encounter.enemies["test"].attack_kind, kind)

    def test_projectile_sweeps_against_moving_player_and_expires(self):
        encounter = world(position=(800, 800))
        encounter.projectiles = [EnemyProjectile("test", Vec2(490, 500), Vec2(490, 500), Vec2(1, 0), 100, 120, 17)]
        encounter.advance(.2, (500, 490), (500, 510))
        self.assertEqual(encounter.hits, [("test", 17)])
        hit, = encounter.hit_events
        self.assertEqual((hit.attacker_id, hit.attack_kind, hit.direction), ("test", "ranged", Vec2(1, 0)))
        self.assertEqual(encounter.projectiles, [])
        encounter.projectiles = [EnemyProjectile("test", Vec2(100, 100), Vec2(100, 100), Vec2(1, 0), 1, 120, 17)]
        encounter.advance(.1, (500, 500), (500, 500))
        self.assertEqual(encounter.projectiles, [])

    def test_death_cancels_windup_and_result_freezes_then_reset_restores(self):
        encounter = world("medium")
        encounter.advance(.1, (500, 500), (500, 500))
        encounter.sync_health({"test": 0}, 100)
        encounter.advance(3, (500, 500), (500, 500))
        self.assertEqual((encounter.result, encounter.shots_fired), ("victory", 0))
        self.assertAlmostEqual(encounter.elapsed_seconds, .1)
        encounter.reset()
        self.assertEqual((encounter.result, encounter.enemies["test"].health), ("running", 480))
        encounter.sync_health({"test": 0}, 0)
        self.assertEqual(encounter.result, "defeat")

    def test_enemy_fire_damage_is_consistent_at_common_frame_rates(self):
        values = []
        for fps in (30, 60, 144):
            encounter = world("medium", (530, 500))
            damage = 0
            for _ in range(fps * 3):
                damage += sum(amount for _, amount in encounter.advance(1 / fps, (500, 500), (500, 500)))
            values.append((damage, encounter.shots_fired))
        self.assertEqual(values, [values[0]] * 3)
        self.assertGreater(values[0][0], 0)


class EncounterIntegrationTests(unittest.TestCase):
    def test_title_continue_preserves_test_world_and_timers(self):
        from types import SimpleNamespace
        import pico2d.pico2d as pico

        program = EncounterApplication(CONFIG, encounter_path=ENCOUNTER, demo=True, mute=True)
        with patch.dict(os.environ, SDL_VIDEODRIVER="dummy"), PicoCanvas(*program.window_size, "타이틀 복귀 확인"):
            try:
                program.enter()
                program.hud.scene = "combat"
                program.hud.transition.update(1)
                program.controller.position_m = (510, 510)
                program.gun.ammo = 13
                program.hud.perform("damage_player", damage_amount=17)
                program.hud.damage_target("S1", 60)
                program.hud.perform("overdrive")
                program.sync_encounter_health()
                program.paused = True
                program.hud.pause.request(True)
                program.hud.pause.update(1)

                def snapshot():
                    return (program.controller.position_m, program.gun.ammo, program.gun.elapsed_seconds,
                            program.hud.state.hud.player_health, program.encounter.elapsed_seconds,
                            program.hud.state.overdrive_remaining_seconds,
                            tuple((enemy.enemy_id, enemy.health, enemy.position_m, enemy.phase)
                                  for enemy in program.encounter.enemies.values()))

                def click(scene, action):
                    button = next(button for button in program.hud.config.buttons[scene] if button.action == action)
                    for kind in (pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP):
                        program.handle_event(SimpleNamespace(type=kind, button=pico.SDL_BUTTON_LEFT,
                            x=button.rect.x + 20, y=button.rect.y + 20))

                before = snapshot()
                click("pause", "show_menu")
                for _ in range(20):
                    program.update(.1)
                self.assertEqual(program.hud.scene, "menu")
                self.assertEqual(snapshot(), before)
                program.keys.add("w")
                click("menu", "continue")
                self.assertEqual(program.hud.scene, "combat")
                self.assertFalse(program.paused)
                self.assertFalse(program.keys)
                self.assertFalse(program.attack_held)
                self.assertEqual(snapshot(), before)
                program.hud.transition.update(1)
                program.update(1 / 60)
                self.assertGreater(program.encounter.elapsed_seconds, before[4])
            finally:
                program.exit()

    def test_real_gun_hit_pushes_enemy_in_unprojected_bullet_direction(self):
        program = EncounterApplication(CONFIG, encounter_path=ENCOUNTER, demo=True, mute=True)
        with patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), PicoCanvas(*program.window_size, '총탄 넉백 확인'):
            try:
                program.enter()
                program.hud.scene = 'combat'
                enemy = program.encounter.enemies['S1']
                enemy.position_m = Vec2(510, 500)
                program.bind_hud_world()
                program.hud.apply_target('S1')
                program.controller.facing = (1, 0)
                program.weapon_animation.request('ranged')
                program.weapon_animation.update(2, program.weapon_durations)
                program.gun.settings = replace(program.gun.settings, hip_spread_degrees=1e-9)
                program.request_primary_attack()
                program.update_guns(.1, program.projection.project(program.controller.position_m))
                self.assertEqual(program.target_hits['S1'], 1)
                self.assertFalse(enemy.knockback_interrupts)
                self.assertAlmostEqual(enemy.knockback_remaining_seconds, .06)
                impact = program.gun.hit_details[1]
                direction = Vec2(*program.projection.unproject((impact.direction.x, impact.direction.y))).normalized()
                origin = enemy.position_m
                program.encounter.advance_reactions(.06)
                self.assertAlmostEqual(enemy.position_m.x, origin.x + direction.x * .3)
                self.assertAlmostEqual(enemy.position_m.y, origin.y + direction.y * .3)
            finally:
                program.exit()

    def test_runner_detects_standalone_without_import(self):
        result = inspect_entrypoint(ROOT / "tests/combat_test_v1_5.py")
        self.assertEqual(result, "standalone")

    def test_real_pico_hud_health_lock_death_pause_and_reset(self):
        program = EncounterApplication(CONFIG, encounter_path=ENCOUNTER, demo=True, mute=True)
        with patch.dict(os.environ, SDL_VIDEODRIVER="dummy"), PicoCanvas(*program.window_size, "교전 확인"):
            try:
                program.enter()
                expected_ids = {f"{prefix}{index}" for prefix, count in (("S", 22), ("M", 6), ("H", 2))
                                for index in range(1, count + 1)}
                self.assertEqual(set(program.hud.enemies), expected_ids)
                self.assertEqual(program.hud.enemies["H1"]["health"].maximum, 1200)
                self.assertEqual(program.hud.enemies["S1"]["health"].maximum, 180)
                program.hud.scene = "combat"
                program.hud.transition.update(1)
                program.hud.apply_target("S1")
                program.hud.damage_target("S1", 60)
                self.assertEqual(program.encounter.enemies["S1"].health, 120)
                program.hud.damage_target("S2", 1)
                self.assertEqual(program.encounter.enemies["S2"].health, 179)
                program.encounter.damage_enemy("S1", 3)
                program.update(.05)
                self.assertEqual(program.encounter.enemies["S1"].health, 117)
                self.assertEqual(program.hud.state.hud.target.health.current, 117)
                self.assertEqual(program.hud.state.hud.total_damage_dealt, 61)
                self.assertEqual(program.hud.selected_target_id, "S1")
                program.on_sword_hit(999, "S1")
                self.assertGreater(program.encounter.enemies["S1"].knockback_remaining_seconds, 0)
                before = program.encounter.elapsed_seconds
                reaction_before = program.encounter.enemies["S1"].knockback_remaining_seconds
                program.paused = True
                program.update(.1)
                self.assertEqual(program.encounter.elapsed_seconds, before)
                self.assertEqual(program.encounter.enemies["S1"].knockback_remaining_seconds, reaction_before)
                program.paused = False
                program.hud.pause.update(1)
                program.hud.pause.request(False)
                program.hud.pause.update(1)
                initial_health = program.hud.state.hud.player_health.current
                enemy = program.encounter.enemies["S2"]
                enemy.position_m = Vec2(507, 500)
                enemy.facing = Vec2(-1, 0)
                enemy.phase, enemy.attack_kind, enemy.remaining_seconds = "active", "melee", .1
                program.update(.05)
                self.assertLess(program.hud.state.hud.player_health.current, initial_health)
                for enemy_id in program.hud.enemies:
                    program.hud.damage_target(enemy_id, 99999)
                program.update(.05)
                self.assertEqual(program.encounter.result, "victory")
                program.gun_contact.emit(Vec2(), Vec2(1, 0), 'metal')
                before = program.controller.position_m, program.encounter.elapsed_seconds
                program.keys = {"d"}
                program.update(.1)
                self.assertEqual((program.controller.position_m, program.encounter.elapsed_seconds), before)
                program.update(.1)
                program.update(program.gun_contact.lifetime_seconds)
                self.assertFalse(program.gun_contact.sparks)
                program.draw()
                program.reset()
                self.assertEqual(program.encounter.result, "running")
                self.assertEqual(program.hud.enemies["S1"]["health"].current, 180)
                self.assertEqual(program.hud.state.hud.player_health.current, initial_health)
                program.hud.perform("damage_player", damage_amount=99999)
                program.update(.05)
                self.assertEqual(program.encounter.result, "defeat")
            finally:
                program.exit()


if __name__ == "__main__":
    unittest.main()

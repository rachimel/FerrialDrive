"""전투의 시간 일관성·대시 캔슬·충돌·피해·재시작을 창 없이 검사한다."""

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import unittest

from ferrial_drive.combat import Arena, CombatConfig, CombatInput, CombatWorld, Vec2, Wall, load_scenario
from ferrial_drive.combat.simulation import Bullet, segment_box, segment_circle


ROOT = Path(__file__).resolve().parents[2]


def advance(world, seconds, command=None, fps=60):
    command = command or CombatInput()
    count = round(seconds * fps)
    for index in range(count):
        world.advance(1 / fps, command if index == 0 else replace(
            command, attack_pressed=False, dash_pressed=False, swap_pressed=False))


def quiet_world(**changes):
    config = replace(CombatConfig(), enemy_speed_units_per_second=0.01, enemy_health=5000, **changes)
    return CombatWorld(config, Arena(player_spawn=(300, 400), enemy_spawn=(1300, 900)))


class CombatTests(unittest.TestCase):
    def test_import_does_not_open_canvas_or_import_tools(self):
        source = ('import sys; import ferrial_drive.combat; '
                  'assert not any(k.startswith(("pico2d", "Tools", "tests")) for k in sys.modules)')
        subprocess.run([sys.executable, "-c", source], cwd=ROOT, check=True, capture_output=True)

    def test_public_scenario_and_invalid_settings(self):
        config, arena, style = load_scenario(ROOT / "samples/combat_prototype/combat_config.json")
        self.assertEqual(config.magazine_rounds, 45)
        self.assertEqual(len(arena.walls), 2)
        self.assertGreater(style["projection_y_scale"], 0)
        CombatWorld(config, arena)
        for changes in ({"reload_seconds": 0}, {"sword_damage": 1.5}, {"walk_speed_units_per_second": float("nan")}):
            with self.assertRaises(ValueError):
                replace(config, **changes)

    def test_walk_is_consistent_at_30_60_and_144_fps_and_stops_immediately(self):
        positions = []
        for fps in (30, 60, 144):
            world = quiet_world()
            advance(world, 1, CombatInput(movement=Vec2(1, 0)), fps)
            positions.append(world.player.position.x)
            stopped = world.player.position
            advance(world, 0.5)
            self.assertEqual(world.player.position, stopped)
        for x in positions:
            self.assertAlmostEqual(x, 540)

    def test_diagonal_is_normalized_and_sprint_is_faster(self):
        world = quiet_world()
        start = world.player.position
        advance(world, 1, CombatInput(movement=Vec2(1, 1)))
        self.assertAlmostEqual((world.player.position - start).length, world.config.walk_speed_units_per_second)
        world = quiet_world()
        start = world.player.position
        advance(world, 1, CombatInput(movement=Vec2(1, 0), sprint=True))
        self.assertAlmostEqual((world.player.position - start).length, world.config.sprint_speed_units_per_second)

    def test_dash_direction_distance_and_reinput_are_fixed(self):
        world = quiet_world()
        start = world.player.position
        world.advance(0.05, CombatInput(movement=Vec2(1, 0), dash_pressed=True))
        world.advance(0.05, CombatInput(movement=Vec2(0, 1), aim=Vec2(0, 1), dash_pressed=True))
        world.advance(0.1, CombatInput(aim=Vec2(-1, 0)))
        self.assertIsNone(world.player.dash)
        self.assertAlmostEqual(world.player.position.x - start.x, world.config.dash_distance_units)
        self.assertAlmostEqual(world.player.position.y, start.y)
        self.assertEqual(world.player.facing, Vec2(-1, 0))

    def test_stationary_dash_uses_aim_and_has_no_extra_cooldown(self):
        world = quiet_world()
        start = world.player.position
        world.advance(0.2, CombatInput(aim=Vec2(0, 1), dash_pressed=True))
        world.advance(0.2, CombatInput(aim=Vec2(1, 0), dash_pressed=True))
        self.assertAlmostEqual(world.player.position.y - start.y, 210)
        self.assertAlmostEqual(world.player.position.x - start.x, 210)

    def test_normal_attack_can_be_dash_cancelled_in_all_phases(self):
        for time in (0.03, 0.14, 0.29):
            with self.subTest(time=time):
                world = quiet_world()
                world.advance(time, CombatInput(attack_pressed=True))
                self.assertIsNotNone(world.player.attack)
                world.advance(0.01, CombatInput(dash_pressed=True, aim=Vec2(0, 1)))
                self.assertIsNone(world.player.attack)
                self.assertIsNotNone(world.player.dash)

    def test_dash_attack_direction_is_dash_direction_and_late_attack_uses_aim(self):
        world = quiet_world()
        world.advance(0.02, CombatInput(movement=Vec2(1, 0), aim=Vec2(0, 1),
                                       dash_pressed=True, attack_pressed=True))
        self.assertTrue(world.player.attack.dash_attack)
        self.assertEqual(world.player.attack.direction, Vec2(1, 0))
        world = quiet_world()
        world.advance(0.12, CombatInput(dash_pressed=True))
        world.advance(0.02, CombatInput(attack_pressed=True, aim=Vec2(0, 1)))
        self.assertFalse(world.player.attack.dash_attack)
        self.assertEqual(world.player.attack.direction, Vec2(0, 1))

    def test_melee_stops_walk_and_hits_once_per_swing(self):
        world = quiet_world()
        world.enemy.position = Vec2(390, 400)
        before = world.enemy.health
        world.advance(0.05, CombatInput(movement=Vec2(1, 0), attack_pressed=True))
        self.assertEqual(world.player.position, Vec2(300, 400))
        advance(world, 0.35)
        self.assertEqual(world.enemy.health, before - world.config.sword_damage)
        self.assertEqual(world.hit_count, 1)

    def test_combo_queues_one_attack_and_cycles_four_stages(self):
        world = quiet_world()
        indices = []
        world.advance(0.02, CombatInput(attack_pressed=True))
        for _ in range(4):
            indices.append(world.player.attack.combo_index)
            world.advance(0.24, CombatInput())
            world.advance(0.02, CombatInput(attack_pressed=True))
            world.advance(0.16, CombatInput())
        self.assertEqual(indices, [0, 1, 2, 3])
        self.assertEqual(world.player.attack.combo_index, 0)

    def test_enemy_commits_direction_and_can_be_evaded(self):
        world = quiet_world()
        world.enemy.position = Vec2(390, 400)
        world.advance(0.02, CombatInput())
        direction = world.enemy.attack.direction
        world.advance(0.2, CombatInput(dash_pressed=True, aim=Vec2(0, 1)))
        advance(world, 0.4)
        self.assertEqual(world.enemy.attack.direction, direction)
        self.assertEqual(world.player.health, world.config.player_health)

    def test_dash_does_not_grant_invulnerability(self):
        world = quiet_world()
        world.enemy.position = Vec2(390, 400)
        world.advance(0.25, CombatInput())
        world.advance(0.04, CombatInput())
        world.advance(0.04, CombatInput(dash_pressed=True, aim=Vec2(1, 0)))
        self.assertLess(world.player.health, world.config.player_health)

    def test_thin_wall_stops_dash_and_bullets(self):
        arena = Arena(player_spawn=(300, 400), enemy_spawn=(900, 400), walls=(Wall(380, 300, 5, 200),))
        world = CombatWorld(arena=arena)
        world.advance(0.2, CombatInput(dash_pressed=True))
        self.assertLessEqual(world.player.position.x, 360)
        world.bullets.append(Bullet(Vec2(350, 400), Vec2(1, 0), 900))
        world.advance(0.1, CombatInput())
        self.assertFalse(world.bullets)
        self.assertEqual(world.enemy.health, world.config.enemy_health)

    def test_swept_bullet_hits_and_wall_has_priority(self):
        world = quiet_world(bullet_speed_units_per_second=40000)
        world.enemy.position = Vec2(500, 400)
        world.bullets.append(Bullet(Vec2(300, 400), Vec2(1, 0), 900))
        world.advance(0.01, CombatInput())
        self.assertEqual(world.enemy.health, 5000 - world.config.bullet_damage)
        self.assertFalse(world.bullets)

    def test_enemy_takes_no_melee_damage_through_wall_or_behind_player(self):
        world = quiet_world()
        world.enemy.position = Vec2(210, 400)
        world.advance(0.25, CombatInput(attack_pressed=True))
        self.assertEqual(world.enemy.health, 5000)
        arena = Arena(player_spawn=(300, 400), enemy_spawn=(390, 400), walls=(Wall(345, 370, 5, 60),))
        world = CombatWorld(arena=arena)
        world.advance(0.25, CombatInput(attack_pressed=True))
        self.assertEqual(world.enemy.health, world.config.enemy_health)

    def test_ammo_auto_reload_continues_while_swapped(self):
        world = quiet_world(magazine_rounds=1)
        world.advance(0.02, CombatInput(swap_pressed=True, fire_held=True))
        self.assertEqual(world.ammo, 0)
        self.assertGreater(world.reload_remaining_seconds, 0)
        advance(world, 0.3)
        world.advance(0.02, CombatInput(swap_pressed=True))
        self.assertEqual(world.weapon_kind, "melee")
        advance(world, 1.1)
        self.assertEqual(world.ammo, 1)
        self.assertEqual(world.reload_remaining_seconds, 0)

    def test_switch_is_allowed_in_dash_and_blocked_during_melee(self):
        world = quiet_world()
        world.advance(0.02, CombatInput(attack_pressed=True))
        world.advance(0.02, CombatInput(swap_pressed=True))
        self.assertEqual(world.weapon_kind, "melee")
        world.advance(0.02, CombatInput(dash_pressed=True, swap_pressed=True))
        self.assertEqual(world.weapon_kind, "ranged")

    def test_enemy_routes_around_obstacle_and_reaches_attack_range(self):
        arena = Arena(player_spawn=(300, 400), enemy_spawn=(900, 400), walls=(Wall(520, 300, 150, 200),))
        world = CombatWorld(arena=arena)
        route = world._find_route(world.enemy.position, world.player.position)
        self.assertGreater(len(route), 1)
        advance(world, 6)
        self.assertLess(world.player.health, world.config.player_health)
        self.assertTrue(world._walkable(world.enemy.position, world.config.actor_radius_units))

    def test_victory_defeat_freeze_and_reset(self):
        world = quiet_world()
        world.enemy.position = Vec2(390, 400)
        world.enemy.health = 1
        world.advance(0.2, CombatInput(attack_pressed=True))
        self.assertEqual(world.result, "victory")
        state = (world.player.position, world.elapsed_seconds)
        advance(world, 1, CombatInput(movement=Vec2(1, 0)))
        self.assertEqual((world.player.position, world.elapsed_seconds), state)
        world.reset()
        self.assertEqual(world.result, "running")
        self.assertEqual(world.hit_count, 0)
        self.assertFalse(world.bullets)
        self.assertIsNone(world.player.attack)
        world.enemy.position = Vec2(390, 400)
        world.player.health = 1
        advance(world, 1)
        self.assertEqual(world.result, "defeat")

    def test_input_edges_survive_frames_shorter_than_fixed_step(self):
        world = quiet_world()
        world.advance(0.001, CombatInput(dash_pressed=True))
        self.assertIsNone(world.player.dash)
        world.advance(0.01, CombatInput())
        self.assertIsNotNone(world.player.dash)

    def test_invalid_time_and_spawn_are_rejected(self):
        world = quiet_world()
        for delta in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                world.advance(delta, CombatInput())
        with self.assertRaises(ValueError):
            CombatWorld(arena=Arena(player_spawn=(10, 10)))

    def test_segment_geometry(self):
        self.assertAlmostEqual(segment_box(Vec2(), Vec2(100, 0), Wall(50, -10, 5, 20)), 0.5)
        self.assertIsNone(segment_box(Vec2(), Vec2(100, 0), Wall(50, 10, 5, 20)))
        self.assertAlmostEqual(segment_circle(Vec2(), Vec2(100, 0), Vec2(50, 0), 10), 0.4)


if __name__ == "__main__":
    unittest.main()

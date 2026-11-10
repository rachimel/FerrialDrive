"""실제 Trail 접촉·프레임 사이 궤적·타격 종료와 캔슬을 검사한다."""

from dataclasses import replace
import unittest

from ferrial_drive.combat import Arena, CombatConfig, CombatInput, CombatWorld, Vec2, Wall
from ferrial_drive.combat.geometry import moving_circle_touches_polygon
from ferrial_drive.combat.simulation import Attack
from ferrial_drive.combat.trails import trail_section


def make_world(**changes):
    config = replace(CombatConfig(), enemy_speed_units_per_second=0.01, **changes)
    return CombatWorld(config, Arena(player_spawn=(300, 400), enemy_spawn=(1300, 900)))


class CombatTrailTests(unittest.TestCase):
    def test_trail_exists_only_during_active_attack(self):
        world = make_world()
        world.advance(0.05, CombatInput(attack_pressed=True))
        attack = world.player.attack
        self.assertEqual(attack.phase, "windup")
        self.assertFalse(attack.trail_sections)
        world.advance(0.05, CombatInput())
        self.assertEqual(attack.phase, "active")
        self.assertTrue(attack.trail_sections)
        world.advance(attack.windup_seconds + attack.active_seconds - attack.elapsed_seconds
                      + world.config.fixed_step_seconds, CombatInput())
        self.assertEqual(attack.phase, "recovery")
        self.assertFalse(attack.trail_sections)
        before = world.enemy.health
        world.enemy.position = world.player.position + Vec2(80, 0)
        world.advance(0.05, CombatInput())
        self.assertEqual(world.enemy.health, before)

    def test_thrust_does_not_hit_target_inside_sector_but_outside_trail(self):
        world = make_world()
        world.combo_index, world.combo_remaining_seconds = 2, 1
        world.enemy.position = Vec2(380, 450)
        before = world.enemy.health
        world.advance(0.2, CombatInput(attack_pressed=True))
        self.assertEqual(world.enemy.health, before)
        self.assertEqual(world.hit_count, 0)

    def test_fast_swing_hits_between_start_and_end_blade_poses(self):
        world = make_world(sword_windup_seconds=0.01, sword_active_seconds=0.004)
        world.combo_index, world.combo_remaining_seconds = 1, 1
        world.enemy.position = Vec2(410, 400)
        before = world.enemy.health
        world.advance(0.025, CombatInput(attack_pressed=True))
        self.assertEqual(world.enemy.health, before - world.config.sword_damage)
        self.assertEqual(world.hit_count, 1)

    def test_fast_target_crossing_trail_is_not_missed(self):
        world = make_world(dash_distance_units=3000)
        world.player.position = Vec2(320, 460)
        world.enemy.position = Vec2(400, 400)
        world.enemy.attack = Attack(Vec2(-1, 0), 0.01, 0.2, 0.2, 100, 48, 0,
                                    world.config.enemy_damage, combo_index=2)
        world.advance(0.1, CombatInput())
        self.assertEqual(world.player.health, world.config.player_health)
        world.advance(world.config.fixed_step_seconds, CombatInput(dash_pressed=True, aim=Vec2(0, -1)))
        self.assertLess(world.player.position.y, 400)
        self.assertEqual(world.player.health, world.config.player_health - world.config.enemy_damage)

    def test_previous_trail_section_still_hits_during_active_attack(self):
        world = make_world()
        world.combo_index, world.combo_remaining_seconds = 1, 1
        world.advance(0.13, CombatInput(attack_pressed=True))
        world.enemy.position = world.player.position + Vec2(85, -50)
        current_pose = world.blade_pose(world.player)
        current_blade = trail_section(current_pose, current_pose, world.config.melee_trail_half_width_units, 0)
        self.assertFalse(moving_circle_touches_polygon(world.enemy.position, world.enemy.position,
                                                       world.config.actor_radius_units, current_blade.vertices))
        before = world.enemy.health
        world.advance(world.config.fixed_step_seconds, CombatInput())
        self.assertEqual(world.enemy.health, before - world.config.sword_damage)

    def test_target_crossing_before_active_window_is_not_hit(self):
        world = make_world(dash_distance_units=3000)
        world.player.position = Vec2(355, 460)
        world.enemy.position = Vec2(400, 400)
        world.enemy.attack = Attack(Vec2(-1, 0), 0.107, 0.2, 0.2, 100, 48, 0,
                                    world.config.enemy_damage, combo_index=2)
        world.advance(0.1, CombatInput())
        world.advance(world.config.fixed_step_seconds, CombatInput(dash_pressed=True, aim=Vec2(0, -1)))
        self.assertLess(world.player.position.y, 400)
        self.assertEqual(world.player.health, world.config.player_health)

    def test_dash_cancel_removes_trail_and_future_hit(self):
        world = make_world()
        world.advance(0.1, CombatInput(attack_pressed=True))
        attack = world.player.attack
        self.assertTrue(attack.trail_sections)
        world.advance(world.config.fixed_step_seconds, CombatInput(dash_pressed=True))
        self.assertIsNone(world.player.attack)
        self.assertFalse(attack.trail_sections)
        world.enemy.position = world.player.position + Vec2(0, 80)
        before = world.enemy.health
        world.advance(0.1, CombatInput())
        self.assertEqual(world.enemy.health, before)

    def test_wall_clips_visible_trail_and_blocks_damage(self):
        arena = Arena(player_spawn=(300, 400), enemy_spawn=(390, 400),
                      walls=(Wall(345, 370, 5, 60),))
        world = CombatWorld(arena=arena)
        world.combo_index, world.combo_remaining_seconds = 2, 1
        world.advance(0.12, CombatInput(attack_pressed=True))
        attack = world.player.attack
        self.assertTrue(attack.trail_sections)
        self.assertLessEqual(world.blade_pose(world.player).tip.x, 341 + 1e-9)
        self.assertTrue(all(v.x <= 345 for section in attack.trail_sections for v in section.vertices))
        self.assertEqual(world.enemy.health, world.config.enemy_health)

    def test_dash_trail_stays_in_world_space_while_actor_moves(self):
        world = make_world()
        world.advance(0.12, CombatInput(dash_pressed=True, attack_pressed=True))
        sections = world.player.attack.trail_sections
        self.assertTrue(sections)
        self.assertTrue(any(v.x < world.player.position.x - 30 for section in sections for v in section.vertices))

    def test_melee_hit_is_consistent_across_display_rates(self):
        for fps in (30, 60, 144):
            with self.subTest(fps=fps):
                world = make_world()
                world.enemy.position = Vec2(400, 400)
                before = world.enemy.health
                for frame in range(fps):
                    world.advance(1 / fps, CombatInput(attack_pressed=frame == 0))
                self.assertEqual(world.enemy.health, before - world.config.sword_damage)
                self.assertEqual(world.hit_count, 1)

    def test_circle_contact_includes_edges_but_not_distant_space(self):
        polygon = (Vec2(0, -4), Vec2(100, -4), Vec2(100, 4), Vec2(0, 4))
        self.assertTrue(moving_circle_touches_polygon(Vec2(50, 30), Vec2(50, -30), 2, polygon))
        self.assertTrue(moving_circle_touches_polygon(Vec2(50, 24), Vec2(50, 24), 20, polygon))
        self.assertFalse(moving_circle_touches_polygon(Vec2(50, 25), Vec2(50, 25), 20, polygon))


if __name__ == "__main__":
    unittest.main()

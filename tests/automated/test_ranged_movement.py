"""총 연사·회복·연속 명중과 무기/조준 모션의 입력 경계를 검사한다."""

from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from ferrial_drive.combat.config import CombatConfig
from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.combat.muzzle_tracks import MuzzleTracks
from ferrial_drive.combat.ranged_combat import RangedCombat
from ferrial_drive.combat.weapon_animation import WeaponAnimation


class RangedRulesTests(unittest.TestCase):
    def test_explosion_uses_ground_distance_even_when_enemy_display_heights_differ(self):
        from ferrial_drive.combat.ranged_combat import GunImpact, explosion_targets
        from ferrial_drive.combat.sword_effects import SwordTarget
        from ferrial_drive.combat.training_ground import GroundProjection
        projection = GroundProjection(25.6, .3209)
        primary = SwordTarget('A', Vec2(0, -24), 20, position_m=(0, 0))
        nearby = SwordTarget('B', Vec2(51.2, -48), 20, position_m=(2, 0))
        outside = SwordTarget('C', Vec2(0, -10), 20, position_m=(0, 4))
        impact = GunImpact(primary.center, Vec2(1, 0), 35, 3, 18)
        self.assertEqual([t.target_id for t in explosion_targets(impact, primary,
                         (primary, nearby, outside), projection)], ['A', 'B'])

    def test_one_penetration_hits_two_distinct_targets_in_distance_order_at_all_frame_rates(self):
        from ferrial_drive.combat.sword_effects import SwordTarget
        settings = replace(CombatConfig(), hip_spread_degrees=1e-9, bullet_speed_units_per_second=100)
        targets = tuple(SwordTarget(name, Vec2(x, 0), 8) for name, x in (("C", 90), ("B", 60), ("A", 30)))
        for fps in (10, 30, 60, 144):
            gun = RangedCombat(settings, penetration_count=1)
            gun.update(.001, Vec2(), Vec2(1000, 0), targets, firing=True, max_shots=1, damage=25)
            events = list(gun.impact_events)
            for _ in range(fps * 2):
                gun.update(1 / fps, Vec2(), Vec2(1000, 0), targets)
                events.extend(gun.impact_events)
            self.assertEqual([target for _, target, _ in events], ["A", "B"], fps)
            self.assertLess(events[0][2].position.x, events[1][2].position.x)
            self.assertTrue(all(impact.damage == 25 for _, _, impact in events))
            self.assertFalse(gun.projectiles)

    def test_same_step_penetrations_keep_separate_impacts_and_fired_explosion_settings(self):
        from ferrial_drive.combat.sword_effects import SwordTarget
        settings = replace(CombatConfig(), hip_spread_degrees=1e-9, bullet_speed_units_per_second=100)
        gun = RangedCombat(settings, penetration_count=1)
        targets = (SwordTarget("B", Vec2(60, 0), 1), SwordTarget("A", Vec2(30, 0), 1))
        gun.update(.01, Vec2(), Vec2(1000, 0), targets, firing=True, max_shots=1, damage=35,
                   explosion_radius_m=3, explosion_damage=18)
        gun.update(1, Vec2(), Vec2(1000, 0), targets, damage=15)
        self.assertEqual(gun.hits, [(1, "A"), (1, "B")])
        self.assertEqual([round(impact.position.x) for _, _, impact in gun.impact_events], [26, 56])
        self.assertTrue(all((impact.damage, impact.explosion_radius_m, impact.explosion_damage) == (35, 3, 18)
                            for _, _, impact in gun.impact_events))

    def test_meter_range_expires_at_75_meters_in_every_direction_and_frame_rate(self):
        from ferrial_drive.combat.training_ground import GroundProjection

        projection = GroundProjection(25.6, .3209)
        settings = replace(CombatConfig(), hip_spread_degrees=1e-9, bullet_speed_units_per_second=5500)
        for axis in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
            for fps in (30, 60, 144):
                gun = RangedCombat(settings, range_m=75, projection=projection)
                target = Vec2(*projection.project(axis)) * 200
                gun.update(.000001, Vec2(), target, firing=True, max_shots=1)
                bullet = gun.projectiles[0]
                for _ in range(fps):
                    gun.update(1 / fps, Vec2(), target)
                    if not gun.projectiles:
                        break
                self.assertFalse(gun.projectiles, (axis, fps))
                self.assertAlmostEqual(Vec2(*projection.unproject((bullet.position.x, bullet.position.y))).length,
                                       75, places=6)

    def test_meter_range_hits_inside_boundary_and_cannot_hit_beyond_it(self):
        from ferrial_drive.combat.training_ground import GroundProjection

        projection = GroundProjection(25.6, .3209)
        settings = replace(CombatConfig(), hip_spread_degrees=1e-9, bullet_speed_units_per_second=5500)
        for axis in (Vec2(1, 0), Vec2(0, 1), Vec2(1, 1).normalized()):
            def point(distance):
                return Vec2(*projection.project((axis.x * distance, axis.y * distance)))
            for distance, expected in ((74, [(1, 'target')]), (76, [])):
                gun = RangedCombat(settings, range_m=75, projection=projection)
                target = SimpleNamespace(target_id='target', center=point(distance), radius_pixels=.1)
                gun.update(1, Vec2(), point(200), (target,), firing=True, max_shots=1)
                self.assertEqual(gun.hits, expected)

    def test_overdrive_fires_with_empty_magazine_without_consuming_ammo(self):
        gun = RangedCombat()
        gun.ammo, gun.last_shot_seconds = 0, 0
        gun.update(.5, Vec2(), Vec2(1000, 0), firing=True, consume_ammo=False, rate=2, damage=30)
        self.assertGreater(gun.shots_fired, 0)
        self.assertEqual(gun.ammo, 0)
        self.assertNotIn('empty', gun.trigger_events)
        before = gun.shots_fired
        gun.update(.1, Vec2(), Vec2(1000, 0), firing=True)
        self.assertEqual(gun.shots_fired, before)
        self.assertIn('empty', gun.trigger_events)

    def test_projectile_keeps_damage_from_firing_when_level_changes_in_flight(self):
        gun = RangedCombat(replace(CombatConfig(), bullet_speed_units_per_second=100, hip_spread_degrees=1e-9))
        target = SimpleNamespace(target_id='metal', center=Vec2(100, 0), radius_pixels=1)
        gun.update(.1, Vec2(), Vec2(1000, 0), (target,), firing=True, max_shots=1, damage=12)
        gun.update(.9, Vec2(), Vec2(1000, 0), (target,), damage=30)
        self.assertEqual(gun.hit_details[1].damage, 12)
        self.assertLess(gun.hit_details[1].position.x, 100)

    def test_trigger_events_follow_actual_shots_then_empty_attempts_and_clear(self):
        gun = RangedCombat(replace(CombatConfig(), magazine_rounds=1))
        gun.update(.2, Vec2(), Vec2(1000, 0), firing=True)
        self.assertEqual(gun.trigger_events, ["shot", "empty", "empty"])
        self.assertEqual(gun.shots_fired, 1)
        self.assertEqual(gun.last_shot_seconds, 0)
        gun.update(0, Vec2(), Vec2(1000, 0), firing=True)
        self.assertEqual(gun.trigger_events, [])
        gun.update(.2, Vec2(), Vec2(1000, 0))
        self.assertEqual(gun.trigger_events, [])
        gun.reset()
        self.assertEqual(gun.trigger_events, [])

    def test_recovery_doubles_accumulated_rounds_after_the_same_delay(self):
        settings = CombatConfig()
        self.assertEqual(settings.ammo_recovery_initial_rounds_per_second, 4)
        slow = RangedCombat(replace(settings, ammo_recovery_initial_rounds_per_second=2))
        fast = RangedCombat(settings)
        for gun in (slow, fast):
            gun.ammo, gun.last_shot_seconds = 0, 0
            gun.update(1, Vec2(), Vec2(1000, 0))
            self.assertEqual((gun.ammo, gun.recovery_fraction), (0, 0))
            gun.update(.5, Vec2(), Vec2(1000, 0))
        self.assertAlmostEqual(fast.ammo + fast.recovery_fraction,
                               2 * (slow.ammo + slow.recovery_fraction))

    def test_projectile_accumulates_travel_for_frame_independent_trail(self):
        for fps in (30, 60, 144):
            gun = RangedCombat(replace(CombatConfig(), bullet_speed_units_per_second=5500))
            gun.update(0.001, Vec2(), Vec2(1000, 0), firing=True, max_shots=1)
            bullet = gun.projectiles[0]
            self.assertAlmostEqual(bullet.traveled_pixels, 5.5)
            for _ in range(fps // 10):
                gun.update(1 / fps, Vec2(), Vec2(1000, 0))
            self.assertAlmostEqual(bullet.traveled_pixels, (bullet.position - Vec2()).length)
            self.assertEqual(min(108, bullet.traveled_pixels), 108)

    def test_held_fire_matches_across_frame_rates_and_paused_time(self):
        results = []
        for fps in (30, 60, 144):
            gun = RangedCombat()
            for _ in range(fps):
                gun.update(1/fps, Vec2(), Vec2(1000, 0), firing=True)
            snapshot = gun.elapsed_seconds, gun.ammo, gun.shots_fired
            gun.update(0, Vec2(), Vec2(1000, 0), firing=True)
            self.assertEqual(snapshot, (gun.elapsed_seconds, gun.ammo, gun.shots_fired))
            results.append((gun.ammo, gun.shots_fired))
        self.assertEqual(results, [(33, 12)] * 3)

    def test_empty_attempt_does_not_postpone_recovery_and_holstered_recovers(self):
        gun = RangedCombat()
        gun.ammo, gun.last_shot_seconds = 0, 0
        gun.update(0.9, Vec2(), Vec2(1000, 0), firing=True)
        self.assertEqual((gun.ammo, gun.last_shot_seconds), (0, 0))
        gun.update(0.5, Vec2(), Vec2(1000, 0))
        self.assertGreater(gun.ammo, 0)
        gun.update(3, Vec2(), Vec2(1000, 0))
        self.assertEqual(gun.ammo, 45)

    def test_overdrive_rate_doubles_shots_using_real_ammo_time(self):
        gun = RangedCombat()
        for _ in range(60):
            gun.update(1/60, Vec2(), Vec2(1000, 0), firing=True, rate=2)
        self.assertEqual((gun.shots_fired, gun.ammo), (24, 21))
        self.assertAlmostEqual(gun.elapsed_seconds, 1)

    def test_fast_bullet_hits_nearest_circle_without_tunnelling(self):
        gun = RangedCombat(replace(CombatConfig(), hip_spread_degrees=1e-9))
        targets = [SimpleNamespace(target_id=name, center=Vec2(x, 0), radius_pixels=1)
                   for name, x in (("far", 60), ("near", 25))]
        gun.update(0.1, Vec2(), Vec2(1000, 0), targets, firing=True)
        self.assertEqual(gun.hits, [(1, "near")])

    def test_shots_sample_moving_muzzle_at_their_own_times(self):
        gun, sampled = RangedCombat(), []
        def muzzle(seconds):
            sampled.append(seconds)
            return Vec2(seconds*100, 0)
        gun.update(0.1, muzzle, Vec2(1000, 0), firing=True)
        self.assertEqual(sampled, [0, 0.085])


class WeaponMotionTests(unittest.TestCase):
    def armed(self):
        motion = WeaponAnimation()
        self.assertTrue(motion.request("ranged"))
        motion.update(1, {})
        self.assertEqual(motion.kind, "ranged")
        return motion

    def choose(self, motion, state="idle", age=100):
        return motion.select(state, shot_age_seconds=age,
                             shot_interval_seconds=0.085, durations={})

    def test_switch_runs_sheath_then_draw_before_committing_kind(self):
        motion = WeaponAnimation()
        motion.request("ranged")
        motion.update(0.49, {})
        self.assertEqual(self.choose(motion).name, "sword_sheath")
        motion.update(0.02, {})
        self.assertEqual(self.choose(motion).name, "gun_draw")
        self.assertEqual(motion.kind, "melee")
        motion.update(0.5, {})
        self.assertFalse(motion.switching)
        self.assertEqual(motion.kind, "ranged")

    def test_aim_enter_hold_exit_and_moving_shots_keep_leg_motion(self):
        motion = self.armed()
        motion.update(0.1, {}, aiming=True)
        self.assertEqual(self.choose(motion).name, "gun_aim_enter")
        motion.update(0.7, {}, aiming=True)
        self.assertEqual(self.choose(motion).name, "gun_aim_hold")
        motion.update(0.1, {}, aiming=True, state="dash")
        self.assertEqual(self.choose(motion, "dash", age=0).name, "gun_aim_dash")
        motion.update(0.1, {}, aiming=False)
        self.assertEqual(self.choose(motion).name, "gun_aim_exit")

    def test_boost_and_aim_dash(self):
        motion = self.armed()
        motion.update(0.1, {}, aiming=True, state="boost")
        self.assertEqual(self.choose(motion, "boost").name, "gun_aim_enter")
        motion.update(0.7, {}, aiming=True, state="boost")
        self.assertEqual(self.choose(motion, "boost", age=0).name, "gun_aim_dash")

    def test_dash_aim_enter_exit_return_to_dash(self):
        motion = self.armed()
        motion.update(0.1, {}, state="dash", aiming=True)
        self.assertEqual(self.choose(motion, "dash").name, "gun_aim_enter")
        motion.update(0.7, {}, state="dash", aiming=True)
        self.assertEqual(self.choose(motion, "dash").name, "gun_aim_dash")
        motion.update(0.1, {}, state="dash", aiming=False)
        self.assertEqual(self.choose(motion, "dash").name, "gun_aim_exit")
        motion.update(0.7, {}, state="dash", aiming=False)
        self.assertEqual(self.choose(motion, "dash").name, "gun_hip_dash")

    def test_swap_speed_halves_both_directions_and_combines_with_overdrive(self):
        for animation_speed in (1, 2):
            motion = WeaponAnimation(swap_speed=2)
            for kind in ("ranged", "melee"):
                self.assertTrue(motion.request(kind))
                self.assertEqual(self.choose(motion).playback_speed, 2 * (motion.animation_speed))
                motion.update(0.49 / animation_speed, {}, animation_speed=animation_speed)
                self.assertTrue(motion.switching)
                self.assertAlmostEqual(self.choose(motion).playback_speed, 2 * animation_speed)
                motion.update(0.01 / animation_speed, {}, animation_speed=animation_speed)
                self.assertFalse(motion.switching)
                self.assertEqual(motion.kind, kind)

    def test_aim_speed_halves_enter_exit_in_idle_dash_boost_with_overdrive(self):
        for state in ("idle", "dash", "boost"):
            for animation_speed in (1, 2):
                motion = WeaponAnimation(aim_speed=2)
                motion.request("ranged")
                motion.update(1, {})
                for aiming in (True, False):
                    motion.update(0, {}, state=state, aiming=aiming, animation_speed=animation_speed)
                    expected = "gun_aim_enter" if aiming else "gun_aim_exit"
                    self.assertEqual(self.choose(motion, state).name, expected)
                    self.assertEqual(self.choose(motion, state).playback_speed, 2 * animation_speed)
                    motion.update(0.32 / animation_speed, {}, state=state, aiming=aiming,
                                  animation_speed=animation_speed)
                    self.assertEqual(self.choose(motion, state).name, expected)
                    motion.update(0.02 / animation_speed, {}, state=state, aiming=aiming,
                                  animation_speed=animation_speed)
                    self.assertIsNone(motion.aim_transition)
                # 조준 배율은 이동 반복 모션을 가속하지 않는다.
                self.assertEqual(self.choose(motion, state).playback_speed, animation_speed)

    def test_muzzle_clamps_end_and_loops_at_same_geometry_origin(self):
        tracks = MuzzleTracks({"gun/s": [[0, 10, -20], [0.5, 30, -40], [1, 10, -20]]})
        self.assertEqual(tracks.sample("gun/s", 0.25), Vec2(20, -30))
        self.assertEqual(tracks.sample("gun/s", 1.25, loop=True), Vec2(20, -30))
        self.assertEqual(tracks.sample("gun/s", 10), Vec2(10, -20))

    def test_aim_plane_cancels_horizontal_offsets_of_eight_views(self):
        from math import cos, sin, tau
        from ferrial_drive.assets.directional import SCREEN_DIRECTIONS
        tracks = MuzzleTracks({f'gun/{direction}': [[0, cos(index*tau/8)*20, -40+sin(index*tau/8)*10],
            [1, cos(index*tau/8)*20, -40+sin(index*tau/8)*10]] for index,direction in enumerate(SCREEN_DIRECTIONS)})
        actual = tracks.aim_plane_offset('gun', .5)
        self.assertAlmostEqual(actual.x, 0)
        self.assertAlmostEqual(actual.y, -40)


class MovementGunIntegrationTests(unittest.TestCase):
    def test_overdrive_explosion_damages_nearby_without_changing_lock_and_normal_shots_do_not_explode(self):
        from ferrial_drive.combat.sword_effects import SwordTarget
        app, root = self.place_two_targets()
        app.sound_player = Mock()
        app.sword_targets = [replace(target, material='metal') for target in app.sword_targets]
        app.sword_targets.extend((SwordTarget("C", root + Vec2(100, -30), 1),
                                  SwordTarget("D", root + Vec2(100, 0), 1)))
        app.target_hits.update(C=0, D=0)
        app.bind_hud_world()
        app.hud.apply_target("A")
        before = {key: entry['health'].current for key, entry in app.hud.enemies.items()}
        app.hud.perform('overdrive')
        app.request_primary_attack()
        app.update_guns(.03, (root.x, root.y))
        self.assertEqual(before['B'] - app.hud.enemies['B']['health'].current, 25 + 13)
        self.assertEqual(before['C'] - app.hud.enemies['C']['health'].current, 13)
        self.assertEqual(before['D'], app.hud.enemies['D']['health'].current)
        self.assertEqual(before['A'], app.hud.enemies['A']['health'].current)
        self.assertEqual(app.hud.selected_target_id, 'A')
        self.assertEqual(len(app.gun_contact.explosions), 1)
        self.assertEqual([c.args[0] for c in app.sound_player.play.call_args_list], ['gun_fire', 'gun_explosion'])
        self.assertAlmostEqual(app.gun_contact.explosions[0].radii_pixels.x, 76.8)
        app.reset()
        self.assertFalse(app.gun_contact.explosions)
        self.assertEqual(app.gun_recoil.offset_pixels, (0, 0))
        self.assertEqual(app.gun.ammo, 60)
        app.weapon_animation.kind = 'ranged'
        app.sound_player.reset_mock()
        app.request_primary_attack()
        app.update_guns(.03, app.projection.project(app.controller.position_m))
        self.assertFalse(app.gun_contact.explosions)
        self.assertNotIn('gun_explosion', [c.args[0] for c in app.sound_player.play.call_args_list])

    def test_explosion_sound_follows_fired_projectile_after_overdrive_expires(self):
        app, root = self.place_two_targets()
        app.sound_player = Mock()
        app.hud.apply_target('A')
        app.hud.perform('overdrive')
        app.request_primary_attack()
        app.update_guns(.001, (root.x, root.y))
        self.assertEqual([c.args[0] for c in app.sound_player.play.call_args_list], ['gun_fire'])
        app.hud.perform('overdrive')
        self.assertFalse(app.hud.state.overdrive)
        app.sound_player.reset_mock()
        app.update_guns(.029, (root.x, root.y))
        self.assertEqual(len(app.gun_contact.explosions), 1)
        self.assertEqual([c.args[0] for c in app.sound_player.play.call_args_list], ['gun_explosion'])

    def test_firing_recoils_on_miss_but_empty_attempt_does_not_trigger(self):
        app = self.app
        app.sword_targets = []
        root = app.projection.project(app.controller.position_m)
        app.request_primary_attack()
        app.update_guns(.01, root)
        direction = app.gun.shot_direction
        offset = Vec2(*app.gun_recoil.offset_pixels)
        self.assertAlmostEqual(offset.length, 2)
        self.assertLess(offset.x * direction.x + offset.y * direction.y, 0)
        app.gun_recoil.update(.1)
        app.gun.ammo, app.gun.last_shot_seconds = 0, app.gun.elapsed_seconds
        app.request_primary_attack()
        app.update_guns(.1, root)
        self.assertEqual(app.gun_recoil.offset_pixels, (0, 0))

    def test_impact_audio_follows_actual_contact_and_metal_material(self):
        for material in ("generic", "metal", "steel"):
            with self.subTest(material=material):
                app, root = self.place_two_targets()
                app.gun.reset()
                app.sword_targets = [replace(target, material=material) for target in app.sword_targets]
                app.hud.apply_target("A")
                app.sound_player = Mock()
                app.request_primary_attack()
                app.update_guns(.001, (root.x, root.y))
                self.assertEqual([call.args[0] for call in app.sound_player.play.call_args_list], ["gun_fire"])
                app.sound_player.reset_mock()
                app.update_guns(.029, (root.x, root.y))
                expected = ["gun_hit"] + (["gun_hit_metal"] if material != "generic" else [])
                self.assertEqual([call.args[0] for call in app.sound_player.play.call_args_list], expected)
                self.assertEqual(app.gun.hits[-1][1], "B")
                app.sound_player.reset_mock()
                app.update_guns(.03, (root.x, root.y))
                self.assertEqual([call.args[0] for call in app.sound_player.play.call_args_list], expected)
                self.assertEqual(app.gun.hits[-1][1], "A")
                app.sound_player.reset_mock()
                app.update_guns(.03, (root.x, root.y))
                app.sound_player.play.assert_not_called()

    def test_empty_and_missed_shots_do_not_play_impact_audio(self):
        app, root = self.place_two_targets()
        app.sword_targets = []
        app.sound_player = Mock()
        app.request_primary_attack()
        app.update_guns(.1, (root.x, root.y))
        self.assertEqual([call.args[0] for call in app.sound_player.play.call_args_list], ["gun_fire"])
        app.sound_player.reset_mock()
        app.gun.ammo = 0
        app.gun.last_shot_seconds = app.gun.elapsed_seconds
        app.request_primary_attack()
        app.update_guns(.1, (root.x, root.y))
        self.assertEqual([call.args[0] for call in app.sound_player.play.call_args_list], ["gun_empty"])

    def test_audio_plays_for_actual_shots_and_empty_attempts_only(self):
        app = self.app
        app.sound_player = Mock()
        app.attack_held = True
        root = app.projection.project(app.controller.position_m)
        app.update_guns(.1, root)
        self.assertEqual([c.args[0] for c in app.sound_player.play.call_args_list], ["gun_fire", "gun_fire"])
        app.sound_player.reset_mock()
        app.gun.ammo = 0
        app.gun.last_shot_seconds = app.gun.elapsed_seconds
        app.update_guns(.1, root)
        calls = app.sound_player.play.call_args_list
        self.assertTrue(calls)
        self.assertTrue(all(c.args == ("gun_empty",) for c in calls))
        app.sound_player.reset_mock()
        app.attack_held = False
        app.update_guns(.1, root)
        app.sound_player.play.assert_not_called()

    def setUp(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        from ferrial_drive.combat.locomotion import LocomotionPlayback
        from ferrial_drive.ui_v2.movement_hud import MovementHud
        from tests.automated.test_sword_movement import sample_clips
        from tests.automated.test_sword_movement_combat import combat
        root = Path(__file__).resolve().parents[2]
        self.app = MovementApplication(root/'samples/sword_movement/movement_config.json', demo=True)
        self.app.weapons_enabled = True
        self.assertTrue(all(gun.range_m == 75 and gun.projection is self.app.projection for gun in self.app.guns))
        self.app.hud = MovementHud(root/'samples/ui_unit_test_v2/ui_config.json',
                                   root/'samples/ui_unit_test_v2/hud_sample.json')
        self.app.hud.scene = 'combat'
        self.app.combat = combat()
        self.app.combat.controller = self.app.controller
        self.app.playback = LocomotionPlayback(sample_clips())
        self.app.perform_hud_action('swap')
        for _ in range(60):
            self.app.update(1/60)
        self.assertEqual(self.app.weapon_animation.kind, 'ranged')

    def test_training_config_fires_900_rpm_at_all_frame_rates(self):
        settings = self.app.gun.settings
        self.assertAlmostEqual(60 / settings.shot_interval_seconds, 900)
        self.assertEqual(settings.bullet_speed_units_per_second, 5500)
        for fps in (30, 60, 144):
            gun = RangedCombat(settings)
            for _ in range(fps):
                gun.update(1 / fps, Vec2(), Vec2(1000, 0), firing=True)
            self.assertEqual((gun.shots_fired, gun.ammo), (15, 45))

    def place_two_targets(self):
        from ferrial_drive.combat.sword_effects import SwordTarget
        app = self.app
        root = Vec2(*app.projection.project(app.controller.position_m))
        app.controller.facing = (1, 0)
        app.sword_targets = [SwordTarget("A", root + Vec2(300, -48), 20),
                             SwordTarget("B", root + Vec2(100, -48), 20)]
        app.target_hits = {"A": 0, "B": 0}
        app.bind_hud_world()
        app.gun.settings = replace(app.gun.settings, hip_spread_degrees=1e-9)
        return app, root

    def test_fires_toward_locked_target_instead_of_cursor(self):
        app, root = self.place_two_targets()
        app.hud.apply_target("A")
        app.mouse = app.camera.world_to_screen((root.x - 300, root.y - 48))
        app.request_primary_attack()
        app.update_guns(0.001, (root.x, root.y))
        self.assertGreater(app.aim()[0], 0)
        self.assertAlmostEqual(app.gun.shot_direction.x, 1)
        self.assertAlmostEqual(app.gun.shot_direction.y, 0)
        self.assertEqual(app.hud.selected_target_id, "A")

    def test_intercepting_enemy_takes_damage_without_stealing_lock(self):
        app, root = self.place_two_targets()
        app.hud.apply_target("A")
        app.request_primary_attack()
        health = app.hud.enemies["B"]["health"].current
        app.update_guns(0.03, (root.x, root.y))
        self.assertEqual(app.target_hits, {"A": 0, "B": 1})
        self.assertEqual(app.hud.enemies["B"]["health"].current, health - 15)
        self.assertEqual(app.hud.selected_target_id, "A")

    def test_first_acquisition_occurs_before_first_shot_and_no_fire_is_needed(self):
        app, root = self.place_two_targets()
        app.mouse = app.camera.world_to_screen((root.x + 300, root.y - 48))
        app.update(1 / 60)
        self.assertEqual(app.hud.selected_target_id, "A")
        self.assertEqual(app.gun.shots_fired, 0)
        app.request_primary_attack()
        app.update(1 / 60)
        expected = (app.locked_target_position() - app.gun.muzzle).normalized()
        self.assertEqual(app.gun.shots_fired, 1)
        self.assertAlmostEqual(app.gun.shot_direction.x, expected.x)
        self.assertAlmostEqual(app.gun.shot_direction.y, expected.y)

    def test_dash_aim_transition_keeps_sliding_and_accurate_fire(self):
        app = self.app
        self.assertEqual(app.weapon_animation.aim_speed, 2)
        app.keys = {'d', 'left_shift'}
        app.hud.aiming = True
        before = app.controller.position_m
        app.update(1 / 60)
        self.assertEqual(app.controller.state, 'dash')
        self.assertGreater(app.controller.position_m[0], before[0])
        self.assertEqual(app.current_weapon_motion().name, 'gun_aim_enter')
        self.assertTrue(app.weapon_animation.aiming)

    def test_configured_speed_sweeps_nearest_target(self):
        gun = RangedCombat(replace(self.app.gun.settings, hip_spread_degrees=1e-9))
        targets = [SimpleNamespace(target_id=name, center=Vec2(x, 0), radius_pixels=1)
                   for name, x in (("far", 80), ("near", 40))]
        gun.update(1 / 60, Vec2(), Vec2(1000, 0), targets, firing=True)
        self.assertEqual(gun.hits, [(1, "near")])

    def test_moving_fire_and_boost_swap_keep_position_and_hud_ammo(self):
        app = self.app
        app.keys = {'d'}
        app.attack_held = True
        app.update(1/60)
        self.assertEqual(app.gun.shots_fired, 1)
        self.assertEqual(app.hud.state.hud.loadouts[0].ranged.rounds, 59)
        self.assertEqual(app.current_weapon_motion().name, "gun_hip_dash")
        self.assertFalse(app.combat.active)
        app.controller.request_boost((1, 0), app.aim())
        app.update(0.1)
        app.perform_hud_action('swap')
        before = app.controller.position_m
        app.update(0.05)
        self.assertTrue(app.weapon_animation.switching)
        self.assertTrue(app.combat.boosting)
        self.assertGreater(app.controller.position_m[0], before[0])
        self.assertIn('holster', app.current_weapon_motion().name)

    def test_pause_freezes_ammo_projectiles_and_equip_clock(self):
        app = self.app
        app.attack_held = True
        app.update(1/60)
        app.perform_hud_action('swap')
        app.paused = True
        before = (app.gun.ammo, app.gun.elapsed_seconds, app.weapon_animation.elapsed_seconds,
                  tuple(p.position for p in app.gun.projectiles))
        for _ in range(60):
            app.update(1/60)
        self.assertEqual(before, (app.gun.ammo, app.gun.elapsed_seconds, app.weapon_animation.elapsed_seconds,
                                  tuple(p.position for p in app.gun.projectiles)))

    def test_fast_tap_survives_mouse_release_and_fires_once_during_a_slow_frame(self):
        app = self.app
        app.request_primary_attack()
        app.release_attack(discard_requested=False)
        app.update(0.1)
        self.assertEqual(app.gun.shots_fired, 1)
        app.request_primary_attack()
        app.release_attack()
        app.update(0.1)
        self.assertEqual(app.gun.shots_fired, 1)

    def test_real_projectile_hit_updates_target_damage_and_counters(self):
        from ferrial_drive.combat.sword_effects import SwordTarget
        app = self.app
        point = Vec2(*app.projection.project(app.controller.position_m)) + Vec2(100, -48)
        app.sword_targets = [SwordTarget('A', point, 20)]
        app.target_hits = {'A': 0}
        app.mouse = app.camera.world_to_screen((point.x, point.y))
        app.bind_hud_world()
        health = app.hud.enemies['A']['health'].current
        app.request_primary_attack()
        app.update(0.1)
        self.assertEqual(health - app.hud.enemies['A']['health'].current, 15)
        self.assertEqual(app.target_hits['A'], 1)
        self.assertEqual(app.hud.state.hud.total_damage_dealt, 15)
        self.assertEqual(len(app.gun_contact.impacts), 1)
        impact = app.gun_contact.impacts[0]
        self.assertEqual(impact.origin, app.gun.hit_details[1].position)

    def test_energy_damage_camera_and_metal_sparks_follow_current_smg_mode(self):
        app, root = self.place_two_targets()
        app.sword_targets = [replace(target, material='metal') for target in app.sword_targets]
        app.hud.apply_target('A')
        for level, overdrive, damage in ((1, False, 15), (2, False, 20), (3, False, 25), (3, True, 38)):
            app.set_energy_level(level)
            if overdrive:
                app.hud.perform('overdrive')
            app.gun.reset()
            app.gun_contact.reset()
            app.camera_impact.reset()
            if overdrive:
                app.gun.ammo = 0
            before = app.hud.enemies['B']['health'].current
            app.request_primary_attack()
            app.update_guns(.03, (root.x, root.y))
            self.assertEqual(before - app.hud.enemies['B']['health'].current, damage)
            self.assertEqual(app.camera_impact.active_amplitude_pixels, 16 if overdrive else 10)
            self.assertEqual(len(app.gun_contact.sparks), 10)
            self.assertLess(app.gun_contact.sparks_per_hit, app.config['sword_effects']['contact_effects']['sparks_per_hit'])
            if overdrive:
                self.assertEqual(app.gun.ammo, 0)


if __name__ == "__main__":
    unittest.main()

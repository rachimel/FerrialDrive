"""컴포넌트 재배치와 세대 핸들 수명을 검사한다."""

from dataclasses import replace
import unittest

from ferrial_drive.combat.config import CombatConfig
from ferrial_drive.combat.enemy_storage import EnemyActors
from ferrial_drive.combat.entity_storage import EntityRegistry, SLOT_MASK
from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.combat.locomotion import LocomotionController
from ferrial_drive.combat.projectile_storage import EnemyProjectile, EnemyProjectileView, ProjectileGroup, projectile_storage
from ferrial_drive.combat.ranged_combat import RangedCombat
from ferrial_drive.combat.sword_effects import SwordTarget

from test_enemy_encounter import world


class EntityStorageTests(unittest.TestCase):
    def test_replace_and_release_preserve_spawn_order_and_invalidate_handles(self):
        encounter = world()
        actors = encounter.enemies
        first = actors["test"]
        original_position = first.position_m
        second = replace(first, enemy_id="second", position_m=Vec2(300, 300))
        actors["second"] = second
        actors["test"] = replace(first, position_m=Vec2(200, 200))
        self.assertIsInstance(actors, EnemyActors)
        self.assertEqual(list(actors), ["test", "second"])
        self.assertEqual([enemy.enemy_id for enemy in actors.values()], ["test", "second"])
        self.assertEqual(first.position_m, original_position)
        self.assertFalse(encounter.registry.valid(first.eid))
        with self.assertRaises(KeyError):
            actors.storage.index(first.eid)
        encounter.registry.release(actors["test"].eid)
        self.assertEqual(list(actors), ["second"])
        self.assertEqual(actors["second"].position_m, Vec2(300, 300))

    def test_shared_projectile_rows_rebind_after_swap_and_growth(self):
        registry = EntityRegistry()
        storage = projectile_storage(registry)
        left = ProjectileGroup(storage, EnemyProjectileView)
        right = ProjectileGroup(storage, EnemyProjectileView)
        template = EnemyProjectile("test", Vec2(1, 2), Vec2(), Vec2(1, 0), 5, 1, 10)
        left.append(template)
        for x in range(16):
            right.append(replace(template, position_m=Vec2(x, 5)))
        old, last = left[0], right[-1]
        registry.release(old.eid)
        self.assertEqual(len(left), 0)
        self.assertEqual(storage.index(last.eid), 0)
        self.assertEqual(last.position_m, Vec2(15, 5))
        right.append(template)
        self.assertEqual(old.eid & SLOT_MASK, right[-1].eid & SLOT_MASK)
        self.assertNotEqual(old.eid, right[-1].eid)
        old.position_m = Vec2(90, 90)
        self.assertEqual(right[-1].position_m, template.position_m)

    def test_penetration_history_does_not_block_a_replacement_target(self):
        registry = EntityRegistry()
        player = LocomotionController(registry=registry)
        settings = replace(CombatConfig(), bullet_speed_units_per_second=100, hip_spread_degrees=0.000001)
        gun = RangedCombat(settings, penetration_count=2, projectiles=projectile_storage(registry),
                           owner_eid=player.eid)
        target = SwordTarget("same", Vec2(20, 0), 8, eid=registry.create())
        gun.update(.2, Vec2(), Vec2(1, 0), (target,), firing=True, max_shots=1)
        bullet = gun.projectiles[0]
        self.assertEqual(gun.hits, [(1, "same")])
        self.assertEqual(bullet.owner_eid, player.eid)
        self.assertIn(target.eid, bullet.hit_target_ids)
        gun.update(.01, Vec2(), Vec2(1, 0), (target,))
        self.assertEqual(gun.hits, [])
        registry.release(target.eid)
        new_target = replace(target, eid=registry.create())
        self.assertEqual(target.eid & SLOT_MASK, new_target.eid & SLOT_MASK)
        gun.update(.01, Vec2(), Vec2(1, 0), (target, new_target))
        self.assertEqual(gun.hits, [(1, "same")])
        self.assertEqual(bullet.hit_target_ids, {target.eid, new_target.eid})

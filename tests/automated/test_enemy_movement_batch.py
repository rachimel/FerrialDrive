"""군집 이동의 순차 충돌과 같은 틱의 전투 결과를 개별 갱신과 대조한다."""

from copy import deepcopy
import json
from math import sin
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from ferrial_drive.combat import enemy_encounter
from ferrial_drive.combat.enemy_encounter import EnemyEncounter, crowd_spawns
from ferrial_drive.combat.geometry import Vec2


ROOT = Path(__file__).resolve().parents[2]


def settings(count):
    config = json.loads((ROOT / "samples/combat_test_v1_5/encounter.json").read_bytes())
    config["spawns"] = crowd_spawns(config["spawns"], count, 4, (500, 500), 1000)
    return config


class EnemyMovementFallbackTests(unittest.TestCase):
    def test_missing_numba_uses_normal_encounter(self):
        with patch.dict(sys.modules, {"numba": None}):
            world = EnemyEncounter(settings(64), map_size_m=1000, player_radius_m=2.5)
        self.assertIsNone(world.movement_batch)
        world.advance(1 / 60, (500, 500), (500, 501))
        self.assertTrue(any(enemy.travel_m for enemy in world.enemies.values()))


class EnemyMovementBatchTests(unittest.TestCase):
    def setUp(self):
        config = settings(64)
        self.batch = EnemyEncounter(config, map_size_m=1000, player_radius_m=2.5)
        if self.batch.movement_batch is None:
            self.skipTest("Numba JIT가 필요하다.")
        with patch.object(enemy_encounter, "_movement_batch", return_value=None):
            self.reference = EnemyEncounter(config, map_size_m=1000, player_radius_m=2.5)
        self.worlds = self.reference, self.batch

    def assert_same_world(self):
        a, b = self.worlds
        self.assertEqual(a.enemies, b.enemies)
        self.assertEqual(a.projectiles, b.projectiles)
        self.assertEqual(a.hit_events, b.hit_events)
        self.assertEqual(a.shots_fired, b.shots_fired)
        self.assertEqual(a.elapsed_seconds, b.elapsed_seconds)
        self.assertEqual(a.result, b.result)

    def test_mixed_combat_matches_every_tick(self):
        for world in self.worlds:
            # 같은 좌표·벽·연쇄 밀림 및 근접/사격을 한 교전에 섞는다.
            for i, enemy in enumerate(world.enemies.values()):
                if i < 9:
                    enemy.position_m = Vec2(3 + i // 3 * 2, 3)
                if i % 5 == 0:
                    enemy.profile = world.profiles["humanoid"]
        start = (500, 500)
        for frame in range(160):
            end = (500 + 14 * sin(frame / 33), 500 + 5 * sin(frame / 11))
            for world in self.worlds:
                if frame in (4, 16, 37):
                    world.knock_back("crowd0021", Vec2(1., .4), source="sword" if frame == 16 else "gun")
                if frame == 17:
                    world.damage_enemy("crowd0021", 10000)
                if frame == 44:
                    world.enemies["crowd0015"].position_m = Vec2(502, 499)
                world.advance((1 / 120, 1 / 60, 1 / 30)[frame % 3], start, end)
            self.assert_same_world()
            start = end
        self.assertGreater(self.batch.shots_fired, 0)

    def test_reactions_after_combat_growth_and_reset(self):
        for world in self.worlds:
            extra = deepcopy(world.enemies["crowd0001"])
            extra.enemy_id = "extra"
            world.enemies[extra.enemy_id] = extra
            world.knock_back("extra", Vec2(-1, .25))
            world.knock_back("crowd0001", Vec2(1, 0), source="gun")
            world.damage_enemy("crowd0001", 10000)
            world.update_result(player_health=0)
        for seconds in (0., .017, .045, .25):
            for world in self.worlds:
                world.advance_reactions(seconds)
            self.assert_same_world()
        self.batch.reset()
        with patch.object(enemy_encounter, "_movement_batch", return_value=None):
            self.reference.reset()
        self.assert_same_world()

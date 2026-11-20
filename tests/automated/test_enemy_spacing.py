"""밀집·경계·연쇄 밀림을 격자와 전수 검사로 동일하게 재현한다."""

from dataclasses import dataclass
from random import Random
from types import SimpleNamespace
import unittest

from ferrial_drive.combat.enemy_spacing import EnemySpacing
from ferrial_drive.combat.geometry import Vec2


@dataclass
class Body:
    enemy_id: str
    profile: object
    position_m: Vec2
    alive: bool


def full_scan(enemy, candidate, enemies):
    for other in enemies:
        if other is enemy or not other.alive:
            continue
        offset = candidate - other.position_m
        minimum = enemy.profile.radius_m + other.profile.radius_m
        if offset.length < minimum:
            candidate = other.position_m + offset.normalized(Vec2(1, 0)) * minimum
    return candidate


class EnemySpacingTests(unittest.TestCase):
    def test_chain_enters_previously_distant_cells_in_spawn_order(self):
        profile = SimpleNamespace(radius_m=2)
        bodies = [Body(str(i), profile, Vec2(x, 0), True) for i, x in enumerate((24, 3, 6, 9, 12, 15))]
        grid = EnemySpacing(bodies, 4)
        self.assertEqual(grid.separate(bodies[0], Vec2(3, 0)), Vec2(19, 0))

    def test_moving_mixed_radii_and_dead_bodies_match_full_scan(self):
        rng = Random(815)
        bodies = [Body(str(i), SimpleNamespace(radius_m=rng.choice((1.5, 2.5, 2.8))),
                       Vec2(rng.randrange(20), rng.randrange(20)), i % 6 != 0) for i in range(80)]
        grid = EnemySpacing(bodies, 5.6)
        for _ in range(8):
            for enemy in bodies:
                if not enemy.alive:
                    continue
                destination = enemy.position_m + Vec2(rng.uniform(-4, 4), rng.uniform(-4, 4))
                resolved = grid.separate(enemy, destination)
                self.assertEqual(resolved, full_scan(enemy, destination, bodies))
                grid.moved(enemy, resolved)
                enemy.position_m = resolved

    def test_sync_tracks_teleport_death_and_replacement(self):
        profile = SimpleNamespace(radius_m=2)
        bodies = [Body(str(i), profile, Vec2(x, 0), True) for i, x in enumerate((0, 30, 33))]
        grid = EnemySpacing(bodies, 4)
        bodies[1].position_m = Vec2(1, 0)
        self.assertIs(grid.sync(bodies), grid)
        self.assertEqual(grid.separate(bodies[0], Vec2()), Vec2(-3, 0))
        bodies[1].alive = False
        grid = grid.sync(bodies)
        self.assertEqual(grid.separate(bodies[0], Vec2()), Vec2())
        bodies[1] = Body("replacement", profile, Vec2(1, 0), True)
        grid = grid.sync(bodies)
        self.assertEqual(grid.separate(bodies[0], Vec2()), Vec2(-3, 0))

"""미터 좌표 격자로 교전 적의 순차 몸체 분리 후보를 좁힌다."""

from bisect import bisect_left, bisect_right, insort
from math import floor, hypot

from .geometry import Vec2


class EnemySpacing:
    def __init__(self, enemies, cell_size_m):
        self.cell_size_m = cell_size_m
        self.enemies = list(enemies)
        self.positions = [enemy.position_m for enemy in self.enemies]
        self.radii = [enemy.profile.radius_m for enemy in self.enemies]
        self.cells = {}
        self.members = {}
        for index, enemy in enumerate(self.enemies):
            if enemy.alive:
                bounds = self.bounds(enemy, enemy.position_m)
                self.members[enemy.enemy_id] = index, bounds
                for cell in self.covered_cells(bounds):
                    self.cells.setdefault(cell, []).append(index)

    def sync(self, enemies):
        """리셋·사망·직접 재배치까지 반영한다. 보통 프레임은 저장된 위치와 비교한다."""
        if len(enemies) == len(self.enemies):
            for index, enemy in enumerate(enemies):
                if (enemy is not self.enemies[index] or enemy.profile.radius_m != self.radii[index]
                        or enemy.alive != (enemy.enemy_id in self.members)):
                    break
                if enemy.alive and enemy.position_m != self.positions[index]:
                    self.moved(enemy, enemy.position_m)
            else:
                return self
        return EnemySpacing(enemies, 2 * max((enemy.profile.radius_m for enemy in enemies), default=.5))

    def cell(self, point):
        return floor(point.x / self.cell_size_m), floor(point.y / self.cell_size_m)

    def bounds(self, enemy, point):
        reach = enemy.profile.radius_m + self.cell_size_m * .5
        size = self.cell_size_m
        return (floor((point.x - reach) / size), floor((point.y - reach) / size),
                floor((point.x + reach) / size), floor((point.y + reach) / size))

    @staticmethod
    def covered_cells(bounds):
        left, top, right, bottom = bounds
        return ((x, y) for x in range(left, right + 1) for y in range(top, bottom + 1))

    def separate(self, enemy, candidate):
        # 다른 몸체를 최대 이동체 반경만큼 확장해 등록했으므로 한 칸만 조회한다.
        last = -1
        cell = self.cell(candidate)
        x_m, y_m = candidate.x, candidate.y
        while True:
            nearby = self.cells.get(cell, ())
            first = bisect_right(nearby, last) if last >= 0 else 0
            for i in range(first, len(nearby)):
                index = nearby[i]
                other = self.enemies[index]
                if other is enemy:
                    continue
                minimum = enemy.profile.radius_m + other.profile.radius_m
                position = self.positions[index]
                dx = x_m - position.x
                dy = y_m - position.y
                if abs(dx) >= minimum or abs(dy) >= minimum:
                    continue
                distance = hypot(dx, dy)
                if distance < minimum:
                    if distance > 1e-9:
                        inverse = 1 / distance
                        dx, dy = dx * inverse, dy * inverse
                    else:
                        dx, dy = 1, 0
                    x_m, y_m = position.x + dx * minimum, position.y + dy * minimum
                    next_cell = floor(x_m / self.cell_size_m), floor(y_m / self.cell_size_m)
                    if next_cell != cell:
                        # 밀려난 위치의 이웃을 원래 출현 순서의 다음 적부터 검사한다.
                        last = index
                        cell = next_cell
                        break
            else:
                return Vec2(x_m, y_m) if x_m != candidate.x or y_m != candidate.y else candidate

    def moved(self, enemy, destination):
        index, previous = self.members[enemy.enemy_id]
        current = self.bounds(enemy, destination)
        self.positions[index] = destination
        if previous != current:
            old, new = set(self.covered_cells(previous)), set(self.covered_cells(current))
            for cell in old - new:
                bucket = self.cells[cell]
                bucket.pop(bisect_left(bucket, index))
                if not bucket:
                    del self.cells[cell]
            for cell in new - old:
                insort(self.cells.setdefault(cell, []), index)
            self.members[enemy.enemy_id] = index, current

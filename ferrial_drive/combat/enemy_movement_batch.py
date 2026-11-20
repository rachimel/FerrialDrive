"""군집의 한 서브스텝을 CPU에서 출현 순서대로 계산한다."""

from math import floor, frexp, isfinite, ldexp, sqrt

import numpy as np
from numba import njit, types
from numba.extending import intrinsic, overload, register_jitable

from .enemy_steering import MELEE_ATTACK, NO_ATTACK, movement_length, pursuit, ranged_recovery
from .geometry import Vec2


register_jitable(pursuit)
register_jitable(ranged_recovery)

BLOCKED, HOLD, PURSUE, RECOVER = range(4)
BODY = np.dtype([
    ("x", "f8"), ("y", "f8"), ("fx", "f8"), ("fy", "f8"), ("radius", "f8"),
    ("max_step", "f8"), ("melee_distance", "f8"), ("fire_distance", "f8"), ("preferred", "f8"),
    ("alive", "?"), ("mode", "i1"), ("pushed", "?"), ("push_x", "f8"), ("push_y", "f8"),
    ("travel", "f8"),
])
RESULT = np.dtype([
    ("x", "f8"), ("y", "f8"), ("fx", "f8"), ("fy", "f8"), ("travel", "f8"),
    ("walk_x", "f8"), ("walk_y", "f8"), ("walk_distance", "f8"), ("attack", "i1"),
])


@intrinsic
def _square_error(typing_context, x, square):
    def emit(context, builder, signature, args):
        value, rounded = args
        return builder.fma(value, value, builder.fneg(rounded))
    return types.float64(types.float64, types.float64), emit


@overload(movement_length)
def _native_movement_length(x, y):
    # 제곱과 합에서 버려진 비트를 복원해 밀집한 몸체의 거리 판정이 누적해서 갈라지지 않게 한다.
    def length(x, y):
        a, b = max(abs(x), abs(y)), min(abs(x), abs(y))
        if b <= a * 2.0 ** -27 or not isfinite(a):
            return a
        exponent = 0
        if a < 1e-140 or a > 1e140:
            a, exponent = frexp(a)
            b = ldexp(b, -exponent)
        aa, bb = a * a, b * b
        total = aa + bb
        residual = (aa - total) + bb + (_square_error(a, aa) + _square_error(b, bb))
        root = sqrt(total)
        square = root * root
        root += ((total - square) + (residual - _square_error(root, square))) / (2 * root)
        return ldexp(root, exponent) if exponent else root
    return length


@register_jitable
def _bucket(cx, cy, mask):
    return ((cx * 73856093) ^ (cy * 19349663)) & mask


@register_jitable
def _separate(bodies, heads, links, index, x, y, cell_size):
    # 버킷 충돌은 후보만 늘린다. 실제 겹친 적 중 출현 순서가 가장 빠른 적부터 적용한다.
    last = -1
    radius = bodies[index].radius
    mask = len(heads) - 1
    while True:
        cx, cy = floor(x / cell_size), floor(y / cell_size)
        first = len(bodies)
        for gx in range(cx - 1, cx + 2):
            for gy in range(cy - 1, cy + 2):
                other = heads[_bucket(gx, gy, mask)]
                while other >= 0:
                    if last < other < first and other != index:
                        target = bodies[other]
                        minimum = radius + target.radius
                        dx, dy = x - target.x, y - target.y
                        if abs(dx) < minimum and abs(dy) < minimum and movement_length(dx, dy) < minimum:
                            first = other
                    other = links[other]
        if first == len(bodies):
            return x, y
        target = bodies[first]
        dx, dy = x - target.x, y - target.y
        distance = movement_length(dx, dy)
        if distance > 1e-9:
            inverse = 1 / distance
            dx, dy = dx * inverse, dy * inverse
        else:
            dx, dy = 1., 0.
        minimum = radius + target.radius
        x, y = target.x + dx * minimum, target.y + dy * minimum
        last = first


@register_jitable
def _move(bodies, heads, links, index, mx, my, map_size, cell_size):
    body = bodies[index]
    radius = body.radius
    maximum = map_size - radius
    x = max(radius, min(maximum, body.x + mx))
    y = max(radius, min(maximum, body.y + my))
    if body.alive:
        x, y = _separate(bodies, heads, links, index, x, y, cell_size)
        x, y = max(radius, min(maximum, x)), max(radius, min(maximum, y))
        mask = len(heads) - 1
        old = _bucket(floor(body.x / cell_size), floor(body.y / cell_size), mask)
        new = _bucket(floor(x / cell_size), floor(y / cell_size), mask)
        if old != new:
            current = heads[old]
            if current == index:
                heads[old] = links[index]
            else:
                while links[current] != index:
                    current = links[current]
                links[current] = links[index]
            links[index] = heads[new]
            heads[new] = index
    dx, dy = x - body.x, y - body.y
    body.x, body.y = x, y
    distance = movement_length(dx, dy)
    body.travel += distance
    return dx, dy, distance


@njit(cache=True)
def _step(bodies, result, heads, links, player_x, player_y, player_radius, map_size):
    if not len(bodies):
        return
    cell_size = 2 * np.max(bodies.radius)
    heads.fill(-1)
    for i in range(len(bodies)):
        body = bodies[i]
        if body.alive:
            key = _bucket(floor(body.x / cell_size), floor(body.y / cell_size), len(heads) - 1)
            links[i], heads[key] = heads[key], i

    for i in range(len(bodies)):
        body = bodies[i]
        fx, fy = body.fx, body.fy
        walk_x = walk_y = walk_distance = 0.
        attack = NO_ATTACK
        if body.pushed:
            _move(bodies, heads, links, i, body.push_x, body.push_y, map_size, cell_size)
        if body.mode == PURSUE or body.mode == RECOVER:
            dx, dy = player_x - body.x, player_y - body.y
            if body.mode == PURSUE:
                fx, fy, mx, my, attack = pursuit(dx, dy, fx, fy, body.max_step, body.radius, player_radius,
                                                 body.melee_distance, body.fire_distance)
            else:
                mx, my = ranged_recovery(dx, dy, body.max_step, body.preferred)
            if attack == NO_ATTACK:
                dx, dy, distance = _move(bodies, heads, links, i, mx, my, map_size, cell_size)
                if movement_length(mx, my) > 1e-9:
                    walk_x, walk_y, walk_distance = dx, dy, distance
        if body.mode == BLOCKED:
            attack = -1
        row = result[i]
        row.x, row.y, row.fx, row.fy, row.travel = body.x, body.y, fx, fy, body.travel
        row.walk_x, row.walk_y, row.walk_distance, row.attack = walk_x, walk_y, walk_distance, attack


class EnemyMovementBatch:
    def __init__(self, count):
        self._reserve(count)
        # 실제 전투와 동일한 배열 서명을 로딩 중에 컴파일한다.
        _step(self.bodies[:0], self.result[:0], self.heads, self.links, 0., 0., 1., 1.)

    def _reserve(self, count):
        self.bodies = np.empty(count, dtype=BODY)
        self.result = np.empty(count, dtype=RESULT)
        self.links = np.empty(count, dtype=np.intp)
        self.heads = np.empty(1 << (max(1, 2 * count) - 1).bit_length(), dtype=np.intp)

    def advance(self, world, seconds, start, end, *, reactions_only=False):
        enemies = world.enemies.values()
        count = len(enemies)
        if count > len(self.bodies):
            self._reserve(count)
        bodies, result = self.bodies[:count], self.result[:count]
        player_radius = world.player_radius_m
        rows = []
        for enemy in enemies:
            profile = enemy.profile
            alive = enemy.alive
            reacting = enemy.knockback_remaining_seconds > 0
            blocked = reactions_only or not alive or (reacting and enemy.knockback_interrupts)
            push = world._take_reaction_movement(enemy, seconds) if reacting or not alive else None
            mode = HOLD
            if blocked:
                mode = BLOCKED
            elif enemy.phase == "move":
                mode = PURSUE
            elif enemy.phase == "recovery" and enemy.attack_kind == "ranged":
                mode = RECOVER
            rows.append((enemy.position_m.x, enemy.position_m.y, enemy.facing.x, enemy.facing.y,
                         profile.radius_m, profile.speed_mps * seconds,
                         profile.melee_reach_m + player_radius if profile.kind != "medium" else -1.,
                         profile.fire_range_m if profile.kind != "small" else -1., profile.preferred_range_m,
                         alive, mode, push is not None, push.x if push else 0., push.y if push else 0., enemy.travel_m))
        bodies[:] = rows
        _step(bodies, result, self.heads, self.links, float(end.x), float(end.y), float(player_radius),
              float(world.map_size_m))
        for enemy, (x, y, fx, fy, travel, dx, dy, distance, attack) in zip(enemies, result.tolist()):
            if x != enemy.position_m.x or y != enemy.position_m.y:
                enemy.position_m = Vec2(x, y)
            if fx != enemy.facing.x or fy != enemy.facing.y:
                enemy.facing = Vec2(fx, fy)
            enemy.travel_m = travel
            if distance:
                enemy.locomotion_m += distance
                enemy.locomotion_step_m = Vec2(enemy.locomotion_step_m.x + dx, enemy.locomotion_step_m.y + dy)
            if attack < 0:
                continue
            if attack:
                world._begin_attack(enemy, "melee" if attack == MELEE_ATTACK else "ranged")
            if enemy.phase != "move":
                world._advance_attack(enemy, seconds, start, end)

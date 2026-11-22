"""군집의 한 서브스텝을 CPU에서 출현 순서대로 계산한다."""

from math import floor, frexp, isfinite, ldexp, sqrt

import numpy as np
from numba import njit, types
from numba.extending import intrinsic, overload, register_jitable

from .enemy_steering import MELEE_ATTACK, NO_ATTACK, movement_length, pursuit, ranged_recovery
from .enemy_storage import EnemyRecord, BREAK, MOVE, RANGED, RECOVERY


register_jitable(pursuit)
register_jitable(ranged_recovery)

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
    if body.health > 0:
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
def _step(bodies, pending, heads, links, seconds, player_x, player_y, player_radius, map_size, reactions_only):
    if not len(bodies):
        return 0
    cell_size = 2 * np.max(bodies.radius)
    heads.fill(-1)
    for i in range(len(bodies)):
        body = bodies[i]
        if body.health > 0:
            key = _bucket(floor(body.x / cell_size), floor(body.y / cell_size), len(heads) - 1)
            links[i], heads[key] = heads[key], i

    count = 0
    for i in range(len(bodies)):
        body = bodies[i]
        remaining = body.push_remaining
        elapsed = min(seconds, remaining)
        if elapsed > 0:
            amount = (remaining * elapsed - elapsed * elapsed / 2) / body.push_duration
            body.push_remaining = max(0., remaining - elapsed)
            if body.push_remaining < 1e-9:
                body.push_remaining = 0.
                if body.health > 0 and body.interrupts and body.phase != BREAK:
                    body.phase = MOVE
            _move(bodies, heads, links, i, body.push_x * amount, body.push_y * amount, map_size, cell_size)
        if body.health <= 0:
            body.death_remaining = max(0., body.death_remaining - seconds)
        if reactions_only or body.health <= 0:
            continue
        if body.phase == BREAK:
            body.remaining = max(0., body.remaining - seconds)
            if body.remaining <= 1e-9:
                body.phase = MOVE
            continue
        if remaining > 0 and body.interrupts:
            continue
        attack = NO_ATTACK
        pursues = body.phase == MOVE
        if pursues or (body.phase == RECOVERY and body.attack_kind == RANGED):
            dx, dy = player_x - body.x, player_y - body.y
            max_step = body.speed * seconds
            if pursues:
                melee_distance = body.melee_reach + player_radius if body.melee_reach >= 0 else -1.
                fx, fy, mx, my, attack = pursuit(dx, dy, body.fx, body.fy, max_step, body.radius,
                                                 player_radius, melee_distance, body.fire_distance)
                body.fx, body.fy = fx, fy
            else:
                mx, my = ranged_recovery(dx, dy, max_step, body.preferred)
            if attack == NO_ATTACK:
                dx, dy, distance = _move(bodies, heads, links, i, mx, my, map_size, cell_size)
                if distance and movement_length(mx, my) > 1e-9:
                    body.walk += distance
                    body.walk_x += dx
                    body.walk_y += dy
        if not pursues or attack != NO_ATTACK:
            pending[count, 0] = i
            pending[count, 1] = attack
            count += 1
    return count


class EnemyMovementBatch:
    def __init__(self, count):
        self._records = None
        self._reserve(count)
        # 실제 전투와 동일한 배열 서명을 로딩 중에 컴파일한다.
        empty = np.ctypeslib.as_array((EnemyRecord * 1)())[:0]
        _step(empty, self.pending, self.heads, self.links, 0., 0., 0., 1., 1., False)

    def _reserve(self, count):
        self.pending = np.empty((count, 2), dtype=np.intp)
        self.links = np.empty(count, dtype=np.intp)
        self.heads = np.empty(1 << (max(1, 2 * count) - 1).bit_length(), dtype=np.intp)

    def _bodies(self, storage):
        if self._records is not storage.records:
            self._records = storage.records
            self._array = np.ctypeslib.as_array(self._records)
        return self._array[:len(storage.views)]

    def reset_locomotion(self, storage):
        bodies = self._bodies(storage)
        bodies["walk_x"].fill(0)
        bodies["walk_y"].fill(0)

    def advance(self, world, seconds, start, end, *, reactions_only=False):
        storage = world.enemies.storage
        bodies = self._bodies(storage)
        if len(bodies) > len(self.links):
            self._reserve(len(storage.records))
        count = _step(bodies, self.pending, self.heads, self.links, float(seconds), float(end.x), float(end.y),
                      float(world.player_radius_m), float(world.map_size_m), reactions_only)
        for index, attack in self.pending[:count].tolist():
            enemy = storage.views[index]
            if attack:
                world._begin_attack(enemy, "melee" if attack == MELEE_ATTACK else "ranged")
            world._advance_attack(enemy, seconds, start, end)

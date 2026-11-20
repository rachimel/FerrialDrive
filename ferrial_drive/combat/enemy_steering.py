"""개별 갱신과 군집 갱신이 공유하는 추적·사격 거리 조절 규칙."""

from math import hypot


NO_ATTACK, MELEE_ATTACK, RANGED_ATTACK = range(3)


def movement_length(x, y):
    return hypot(x, y)


def pursuit(dx, dy, facing_x, facing_y, max_step, radius, player_radius, melee_distance, fire_distance):
    distance = movement_length(dx, dy)
    if distance > 1e-9:
        inverse = 1 / distance
        facing_x, facing_y = dx * inverse, dy * inverse
    if distance <= melee_distance:
        return facing_x, facing_y, 0., 0., MELEE_ATTACK
    if distance <= fire_distance:
        return facing_x, facing_y, 0., 0., RANGED_ATTACK
    step = min(max_step, max(0., distance - radius - player_radius))
    return facing_x, facing_y, facing_x * step, facing_y * step, NO_ATTACK


def ranged_recovery(dx, dy, max_step, preferred_distance):
    distance = movement_length(dx, dy)
    if distance <= 1e-9:
        return 0., 0.
    inverse = 1 / distance
    step = max(-max_step, min(max_step, distance - preferred_distance))
    return dx * inverse * step, dy * inverse * step

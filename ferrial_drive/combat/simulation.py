"""고정 주기의 이동·공격·피해·승패. Pico2D와 화면 좌표를 사용하지 않는다."""

from dataclasses import dataclass, field, replace
from heapq import heappop, heappush
from math import acos, asin, ceil, cos, exp, expm1, floor, hypot, isfinite, log1p, radians, sin
from random import Random

from .config import Arena, CombatConfig


@dataclass(frozen=True)
class Vec2:
    x: float = 0
    y: float = 0

    def __add__(self, other):
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar):
        return Vec2(self.x * scalar, self.y * scalar)

    @property
    def length(self):
        return hypot(self.x, self.y)

    def normalized(self, fallback=None):
        return self * (1 / self.length) if self.length > 1e-9 else (fallback or Vec2())


@dataclass(frozen=True)
class CombatInput:
    movement: Vec2 = Vec2()
    aim: Vec2 = Vec2(1, 0)
    sprint: bool = False
    fire_held: bool = False
    aiming: bool = False
    attack_pressed: bool = False
    dash_pressed: bool = False
    swap_pressed: bool = False


@dataclass
class Attack:
    direction: Vec2
    windup_seconds: float
    active_seconds: float
    recovery_seconds: float
    reach_units: float
    half_angle_degrees: float
    step_units: float
    damage: int
    combo_index: int = 0
    dash_attack: bool = False
    elapsed_seconds: float = 0
    hit_owners: set[str] = field(default_factory=set)

    @property
    def phase(self):
        if self.elapsed_seconds < self.windup_seconds:
            return "windup"
        if self.elapsed_seconds < self.windup_seconds + self.active_seconds:
            return "active"
        return "recovery"

    @property
    def duration_seconds(self):
        return self.windup_seconds + self.active_seconds + self.recovery_seconds


@dataclass
class Dash:
    direction: Vec2
    elapsed_seconds: float = 0


@dataclass
class Fighter:
    owner: str
    position: Vec2
    facing: Vec2
    health: int
    maximum_health: int
    attack: Attack | None = None
    dash: Dash | None = None
    hit_flash_seconds: float = 0
    travel_units: float = 0

    @property
    def alive(self):
        return self.health > 0


@dataclass
class Bullet:
    position: Vec2
    direction: Vec2
    remaining_units: float


@dataclass(frozen=True)
class HitEvent:
    owner: str
    amount: int
    position: Vec2
    direction: Vec2


def segment_box(start, end, box):
    """선분이 사각형에 최초 접촉하는 0~1 비율. 접촉이 없으면 None이다."""
    low, high = 0.0, 1.0
    for origin, delta, minimum, maximum in (
            (start.x, end.x - start.x, box.x, box.x + box.width),
            (start.y, end.y - start.y, box.y, box.y + box.height)):
        if abs(delta) < 1e-9:
            if not minimum <= origin <= maximum:
                return None
        else:
            near, far = sorted(((minimum - origin) / delta, (maximum - origin) / delta))
            low, high = max(low, near), min(high, far)
            if low > high:
                return None
    return low


def segment_circle(start, end, center, radius):
    delta, offset = end - start, start - center
    a = delta.x * delta.x + delta.y * delta.y
    c = offset.x * offset.x + offset.y * offset.y - radius * radius
    if c <= 0:
        return 0.0
    if a < 1e-12:
        return None
    b = 2 * (offset.x * delta.x + offset.y * delta.y)
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return None
    result = (-b - discriminant ** 0.5) / (2 * a)
    return result if 0 <= result <= 1 else None


class CombatWorld:
    def __init__(self, config=None, arena=None, *, seed=0):
        self.config = config or CombatConfig()
        self.arena = arena or Arena()
        self.seed = seed
        self.reset()

    def reset(self):
        c = self.config
        self.player = Fighter("player", Vec2(*self.arena.player_spawn), Vec2(1, 0),
                              c.player_health, c.player_health)
        self.enemy = Fighter("enemy", Vec2(*self.arena.enemy_spawn), Vec2(-1, 0),
                             c.enemy_health, c.enemy_health)
        for actor in (self.player, self.enemy):
            if not self._walkable(actor.position, c.actor_radius_units):
                raise ValueError("출현 위치가 경계·장애물과 겹친다.")
        if (self.player.position - self.enemy.position).length < c.actor_radius_units * 2:
            raise ValueError("두 기체의 출현 위치가 겹친다.")
        self.random = Random(self.seed)
        self.weapon_kind = "melee"
        self.ammo = c.magazine_rounds
        self.last_shot_seconds = 0.0
        self.ammo_recovery_fraction = 0.0
        self.shot_remaining_seconds = 0.0
        self.swap_remaining_seconds = 0.0
        self.combo_remaining_seconds = 0.0
        self.combo_index = 0
        self.queued_melee = False
        self.hit_count = self.total_damage = 0
        self.elapsed_seconds = self.accumulator_seconds = 0.0
        self.result = "running"
        self.bullets = []
        self.events = []
        self.enemy_route = []
        self.path_remaining_seconds = 0.0
        self.pending_attack = self.pending_dash = self.pending_swap = False

    def advance(self, delta_seconds, command):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("갱신 시간은 0 이상의 유한한 초여야 한다.")
        if not all(isfinite(v) for v in (command.movement.x, command.movement.y, command.aim.x, command.aim.y)):
            raise ValueError("이동·조준 입력은 유한한 좌표여야 한다.")
        self.events = []
        if self.result != "running":
            return ()
        self.pending_attack |= command.attack_pressed
        self.pending_dash |= command.dash_pressed
        self.pending_swap |= command.swap_pressed
        self.accumulator_seconds += min(delta_seconds, self.config.max_frame_seconds)
        step = self.config.fixed_step_seconds
        while self.accumulator_seconds + 1e-10 >= step and self.result == "running":
            inputs = replace(command, attack_pressed=self.pending_attack,
                             dash_pressed=self.pending_dash, swap_pressed=self.pending_swap)
            self.pending_attack = self.pending_dash = self.pending_swap = False
            self._step(step, inputs)
            self.accumulator_seconds = max(0, self.accumulator_seconds - step)
        return tuple(self.events)

    def _step(self, seconds, inputs):
        c, player = self.config, self.player
        self.elapsed_seconds += seconds
        for name in ("shot_remaining_seconds", "swap_remaining_seconds",
                     "combo_remaining_seconds", "path_remaining_seconds"):
            previous = getattr(self, name)
            setattr(self, name, max(0, previous - seconds))
        for actor in (player, self.enemy):
            actor.hit_flash_seconds = max(0, actor.hit_flash_seconds - seconds)
        aim = inputs.aim.normalized(player.facing)
        player.facing = aim
        if inputs.dash_pressed and player.dash is None and not (player.attack and player.attack.dash_attack):
            player.dash = Dash(inputs.movement.normalized(aim))
            player.attack = None
            self.queued_melee = False
        if inputs.swap_pressed and self.swap_remaining_seconds == 0 and player.attack is None:
            self.weapon_kind = "ranged" if self.weapon_kind == "melee" else "melee"
            self.swap_remaining_seconds = c.swap_cooldown_seconds
            self.queued_melee = False
        if self.combo_remaining_seconds == 0 and player.attack is None:
            self.combo_index = 0
        if inputs.attack_pressed and self.weapon_kind == "melee":
            if player.attack is None:
                self._start_player_melee(aim)
            elif (not player.attack.dash_attack
                  and player.attack.duration_seconds - player.attack.elapsed_seconds <= c.combo_buffer_seconds):
                self.queued_melee = True
        if self.weapon_kind == "ranged" and inputs.fire_held:
            if self.shot_remaining_seconds == 0 and self.ammo > 0:
                self._shoot(aim, inputs.aiming)
        self._advance_ammo_recovery(seconds)
        if player.dash is not None:
            dash = player.dash
            remaining = c.dash_duration_seconds - dash.elapsed_seconds
            self._move(player, dash.direction * (c.dash_distance_units / c.dash_duration_seconds * min(seconds, remaining)))
            dash.elapsed_seconds += seconds
            if dash.elapsed_seconds + 1e-9 >= c.dash_duration_seconds:
                player.dash = None
        elif player.attack is None:
            speed = c.sprint_speed_units_per_second if inputs.sprint else c.walk_speed_units_per_second
            self._move(player, inputs.movement.normalized() * (speed * seconds))
        self._enemy_think(seconds)
        self._advance_attack(player, self.enemy, seconds)
        self._advance_attack(self.enemy, player, seconds)
        self._advance_bullets(seconds)
        if not player.alive or not self.enemy.alive:
            self.result = "defeat" if not player.alive else "victory"
            self.bullets.clear()
            player.dash = None
            player.attack = self.enemy.attack = None

    def _start_player_melee(self, aim):
        c, player = self.config, self.player
        dash_attack = (player.dash is not None
                       and player.dash.elapsed_seconds <= c.dash_attack_window_seconds)
        direction = player.dash.direction if dash_attack else aim
        index = self.combo_index
        player.attack = Attack(direction, c.sword_windup_seconds, c.sword_active_seconds,
                               c.sword_recovery_seconds, c.sword_reach_units,
                               c.sword_half_angle_degrees, c.sword_step_units,
                               c.sword_damage, index, dash_attack)
        self.combo_index = (index + 1) % 4
        self.combo_remaining_seconds = c.combo_reset_seconds

    def _shoot(self, aim, aiming):
        c = self.config
        spread = c.aim_spread_degrees if aiming else c.hip_spread_degrees
        angle = radians(self.random.uniform(-spread, spread))
        direction = Vec2(aim.x * cos(angle) - aim.y * sin(angle), aim.x * sin(angle) + aim.y * cos(angle))
        # 총구까지 건너뛰지 않고 중심부터 추적하여 인접 장애물 관통을 막는다.
        self.bullets.append(Bullet(self.player.position, direction, c.bullet_range_units))
        self.ammo -= 1
        self.shot_remaining_seconds = c.shot_interval_seconds
        self.last_shot_seconds = self.elapsed_seconds
        self.ammo_recovery_fraction = 0.0

    @property
    def ammo_recovery_wait_seconds(self):
        if self.ammo >= self.config.magazine_rounds:
            return 0.0
        return max(0.0, self.config.ammo_recovery_delay_seconds
                   - (self.elapsed_seconds - self.last_shot_seconds))

    def _ammo_recovery_time(self, time_seconds):
        c = self.config
        # 빈 탄창 완충에 필요한 시간까지만 계산하여 장시간 대기 중 지수 발산을 막는다.
        full_seconds = log1p(c.magazine_rounds * c.ammo_recovery_growth_per_second
                            / c.ammo_recovery_initial_rounds_per_second) / c.ammo_recovery_growth_per_second
        return min(full_seconds, max(0.0, time_seconds - self.last_shot_seconds - c.ammo_recovery_delay_seconds))

    @property
    def ammo_recovery_rate_rounds_per_second(self):
        if self.ammo >= self.config.magazine_rounds or self.ammo_recovery_wait_seconds > 1e-9:
            return 0.0
        c = self.config
        return c.ammo_recovery_initial_rounds_per_second * exp(
            c.ammo_recovery_growth_per_second * self._ammo_recovery_time(self.elapsed_seconds))

    def _advance_ammo_recovery(self, seconds):
        c = self.config
        if self.ammo >= c.magazine_rounds:
            self.ammo_recovery_fraction = 0.0
            return
        before = self._ammo_recovery_time(self.elapsed_seconds - seconds)
        after = self._ammo_recovery_time(self.elapsed_seconds)
        # 회복 속도 r(t)=r0*exp(k*t)를 구간 적분한다. 부분 탄약도 다음 갱신으로 이월한다.
        restored = (c.ammo_recovery_initial_rounds_per_second / c.ammo_recovery_growth_per_second
                    * exp(c.ammo_recovery_growth_per_second * before)
                    * expm1(c.ammo_recovery_growth_per_second * (after - before)))
        progress = self.ammo_recovery_fraction + restored
        rounds = min(c.magazine_rounds - self.ammo, floor(progress + 1e-9))
        self.ammo += rounds
        self.ammo_recovery_fraction = (max(0.0, progress - rounds) if self.ammo < c.magazine_rounds else 0.0)

    def _enemy_think(self, seconds):
        enemy, c = self.enemy, self.config
        if not enemy.alive or enemy.attack is not None:
            return
        difference = self.player.position - enemy.position
        enemy.facing = difference.normalized(enemy.facing)
        if (difference.length <= c.enemy_reach_units + c.actor_radius_units - 5
                and self._line_clear(enemy.position, self.player.position)):
            enemy.attack = Attack(enemy.facing, c.enemy_windup_seconds, c.enemy_active_seconds,
                                  c.enemy_recovery_seconds, c.enemy_reach_units,
                                  c.enemy_half_angle_degrees, c.enemy_step_units, c.enemy_damage)
            return
        if self._line_clear(enemy.position, self.player.position, c.actor_radius_units + 2):
            self.enemy_route = []
            direction = difference.normalized()
        else:
            if self.path_remaining_seconds == 0:
                self.enemy_route = self._find_route(enemy.position, self.player.position)
                self.path_remaining_seconds = c.enemy_path_refresh_seconds
            while self.enemy_route and (self.enemy_route[0] - enemy.position).length < 3:
                self.enemy_route.pop(0)
            direction = (self.enemy_route[0] - enemy.position).normalized() if self.enemy_route else Vec2()
        self._move(enemy, direction * (c.enemy_speed_units_per_second * seconds))

    def _advance_attack(self, actor, target, seconds):
        attack = actor.attack
        if attack is None or not actor.alive:
            return
        old = attack.elapsed_seconds
        attack.elapsed_seconds += seconds
        active_start, active_end = attack.windup_seconds, attack.windup_seconds + attack.active_seconds
        active_time = max(0, min(attack.elapsed_seconds, active_end) - max(old, active_start))
        if active_time > 0:
            if actor.dash is None:
                self._move(actor, attack.direction * (attack.step_units * active_time / attack.active_seconds))
            if target.alive and target.owner not in attack.hit_owners and self._melee_touches(actor, target, attack):
                attack.hit_owners.add(target.owner)
                self._damage(target, attack.damage, attack.direction)
        if actor is self.player:
            actor.facing = attack.direction
        if attack.elapsed_seconds + 1e-9 >= attack.duration_seconds:
            actor.attack = None
            if actor == self.player:
                self.combo_remaining_seconds = self.config.combo_reset_seconds
                if self.queued_melee:
                    self.queued_melee = False
                    self._start_player_melee(actor.facing)

    def _melee_touches(self, actor, target, attack):
        offset = target.position - actor.position
        distance = offset.length
        if distance > attack.reach_units + self.config.actor_radius_units:
            return False
        if not self._line_clear(actor.position, target.position):
            return False
        unit = offset.normalized(attack.direction)
        dot = max(-1.0, min(1.0, unit.x * attack.direction.x + unit.y * attack.direction.y))
        allowance = asin(min(1.0, self.config.actor_radius_units / max(distance, 1e-9)))
        return acos(dot) <= radians(attack.half_angle_degrees) + allowance

    def _advance_bullets(self, seconds):
        c = self.config
        remaining = []
        for bullet in self.bullets:
            travel = min(bullet.remaining_units, c.bullet_speed_units_per_second * seconds)
            end = bullet.position + bullet.direction * travel
            wall_hits = [hit for wall in self.arena.walls
                         if (hit := segment_box(bullet.position, end, wall.expanded(c.bullet_radius_units))) is not None]
            wall_hit = min(wall_hits, default=2)
            target_hit = (segment_circle(bullet.position, end, self.enemy.position,
                                        c.actor_radius_units + c.bullet_radius_units) if self.enemy.alive else None)
            if target_hit is not None and target_hit < wall_hit:
                self._damage(self.enemy, c.bullet_damage, bullet.direction)
                continue
            if wall_hit <= 1:
                continue
            bullet.position = end
            bullet.remaining_units -= travel
            if bullet.remaining_units > 0 and 0 <= end.x <= self.arena.width_units and 0 <= end.y <= self.arena.height_units:
                remaining.append(bullet)
        self.bullets = remaining

    def _damage(self, target, amount, direction):
        applied = min(target.health, amount)
        if applied <= 0:
            return
        target.health -= applied
        target.hit_flash_seconds = 0.12
        self.events.append(HitEvent(target.owner, applied, target.position, direction))
        if target == self.enemy:
            self.hit_count += 1
            self.total_damage += applied

    def _move(self, actor, delta):
        radius = self.config.actor_radius_units
        count = max(1, ceil(delta.length / (radius * 0.4)))
        increment = delta * (1 / count)
        for _ in range(count):
            before = actor.position
            for axis in (Vec2(increment.x, 0), Vec2(0, increment.y)):
                position = actor.position + axis
                position = Vec2(max(radius, min(self.arena.width_units - radius, position.x)),
                                max(radius, min(self.arena.height_units - radius, position.y)))
                other = self.enemy if actor == self.player else self.player
                if other.alive and (position - other.position).length < radius * 2 - 1e-6:
                    continue
                if self._walkable(position, radius):
                    actor.position = position
            actor.travel_units += (actor.position - before).length

    def _walkable(self, point, radius):
        if not radius <= point.x <= self.arena.width_units - radius or not radius <= point.y <= self.arena.height_units - radius:
            return False
        for wall in self.arena.walls:
            nearest = Vec2(max(wall.x, min(wall.x + wall.width, point.x)),
                           max(wall.y, min(wall.y + wall.height, point.y)))
            if (point - nearest).length < radius - 1e-6:
                return False
        return True

    def _line_clear(self, start, end, margin=0):
        return all(segment_box(start, end, wall.expanded(margin)) is None for wall in self.arena.walls)

    def _find_route(self, start, goal):
        """작은 사각형 훈련장의 모서리 후보에 A*를 적용한다."""
        margin = self.config.actor_radius_units + 8
        points = [start, goal]
        for wall in self.arena.walls:
            box = wall.expanded(margin)
            for point in (Vec2(box.x, box.y), Vec2(box.x + box.width, box.y),
                          Vec2(box.x, box.y + box.height), Vec2(box.x + box.width, box.y + box.height)):
                if self._walkable(point, self.config.actor_radius_units):
                    points.append(point)
        frontier, costs, parents = [(0, 0)], {0: 0}, {}
        while frontier:
            _, index = heappop(frontier)
            if index == 1:
                route = []
                while index != 0:
                    route.append(points[index])
                    index = parents[index]
                return list(reversed(route))
            for next_index, point in enumerate(points):
                if next_index == index or not self._line_clear(points[index], point, self.config.actor_radius_units + 1):
                    continue
                cost = costs[index] + (point - points[index]).length
                if cost < costs.get(next_index, float("inf")):
                    costs[next_index], parents[next_index] = cost, index
                    heappush(frontier, (cost + (goal - point).length, next_index))
        return []

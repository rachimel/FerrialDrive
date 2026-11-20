"""소형 근접·중형 사격·인간형 복합 교전. 거리 m·시간 초이며 창을 소유하지 않는다."""

from dataclasses import dataclass
from math import ceil, hypot, isfinite

from .geometry import Vec2, moving_circle_touches_polygon, segment_circle
from .enemy_spacing import EnemySpacing


@dataclass(frozen=True)
class EnemyProfile:
    name: str
    kind: str
    health: int
    radius_m: float
    height_pixels: float
    hit_radius_pixels: float
    speed_mps: float
    melee_reach_m: float
    melee_damage: int
    preferred_range_m: float
    fire_range_m: float
    shot_damage: int
    projectile_speed_mps: float
    projectile_range_m: float
    windup_seconds: float
    active_seconds: float
    recovery_seconds: float
    color: str

    def __post_init__(self):
        if self.kind not in ("small", "medium", "humanoid"):
            raise ValueError("적 유형은 small/medium/humanoid다.")
        for name in ("health", "melee_damage", "shot_damage"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError("적 HP·피해량은 양수 정수다.")
        for name in ("radius_m", "height_pixels", "hit_radius_pixels", "speed_mps", "melee_reach_m",
                     "preferred_range_m", "fire_range_m", "projectile_speed_mps", "projectile_range_m",
                     "windup_seconds", "active_seconds", "recovery_seconds"):
            if not isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"적 설정 {name}은 양수 유한값이다.")
        if self.fire_range_m < self.preferred_range_m:
            raise ValueError("사격 개시 거리는 유지 거리 이상이어야 한다.")


@dataclass
class EncounterEnemy:
    enemy_id: str
    profile: EnemyProfile
    position_m: Vec2
    health: int
    facing: Vec2 = Vec2(-1, 0)
    phase: str = "move"
    attack_kind: str = "melee"
    remaining_seconds: float = 0
    hit_player: bool = False
    travel_m: float = 0
    knockback_remaining_seconds: float = 0
    knockback_velocity_mps: Vec2 = Vec2()
    knockback_duration_seconds: float = .12
    knockback_interrupts: bool = False
    death_remaining_seconds: float = 0

    @property
    def alive(self):
        return self.health > 0

    @property
    def attack_polygon(self):
        length = self.profile.melee_reach_m
        side = Vec2(-self.facing.y, self.facing.x) * (length * .3)
        end = self.position_m + self.facing * length
        return (self.position_m - side, end - side, end + side, self.position_m + side)


@dataclass
class EnemyProjectile:
    owner: str
    position_m: Vec2
    previous_m: Vec2
    direction: Vec2
    remaining_m: float
    speed_mps: float
    damage: int


@dataclass(frozen=True, slots=True)
class EnemyHit:
    attacker_id: str
    attack_kind: str
    damage: int
    direction: Vec2


class EnemyEncounter:
    def __init__(self, settings, *, map_size_m, player_radius_m):
        self.settings = settings
        self.map_size_m, self.player_radius_m = map_size_m, player_radius_m
        if not all(isfinite(v) and v > 0 for v in (map_size_m, player_radius_m)):
            raise ValueError("훈련장 크기·플레이어 반경은 양수다.")
        self.profiles = {key: EnemyProfile(**value) for key, value in settings["profiles"].items()}
        reaction = settings.get("knockback", {})
        self.knockback_seconds = reaction.get("duration_seconds", .12)
        self.death_seconds = reaction.get("death_seconds", .22)
        self.knockback_distances = {"small": 3, "medium": 1.4, "humanoid": .7,
                                   **reaction.get("distance_m_by_kind", {})}
        gun = settings.get("gun_knockback", {})
        self.gun_knockback_seconds = gun.get("duration_seconds", .06)
        self.gun_knockback_distances = {"small": .3, "medium": .14, "humanoid": .07,
                                       **gun.get("distance_m_by_kind", {})}
        if not all(isfinite(value) and value > 0 for value in
                   (self.knockback_seconds, self.death_seconds, *self.knockback_distances.values(),
                    self.gun_knockback_seconds, *self.gun_knockback_distances.values())):
            raise ValueError("넉백 거리·시간과 사망 표시 시간은 양수 유한값이다.")
        self.reset()

    def reset(self):
        self.enemies = {}
        for row in self.settings["spawns"]:
            profile = self.profiles[row["profile"]]
            position = Vec2(*row["position_m"])
            radius = profile.radius_m
            if (row["id"] in self.enemies or not row["id"]
                    or not all(isfinite(v) and radius <= v <= self.map_size_m - radius
                               for v in (position.x, position.y))):
                raise ValueError("적 ID 중복 또는 출현 위치 범위 오류")
            self.enemies[row["id"]] = EncounterEnemy(row["id"], profile, position, profile.health)
        if not self.enemies:
            raise ValueError("교전에는 적이 한 기 이상 필요하다.")
        self.spacing = EnemySpacing(self.enemies.values(), 2 * max(enemy.profile.radius_m for enemy in self.enemies.values()))
        self.projectiles = []
        self.hit_events = []
        self.changed_health_ids = set()
        self.elapsed_seconds = 0
        self.result = "running"
        self.shots_fired = 0

    @property
    def hits(self):
        return [(hit.attacker_id, hit.damage) for hit in self.hit_events]

    @property
    def hit_directions(self):
        return [hit.direction for hit in self.hit_events]

    def _set_enemy_health(self, enemy, health):
        before = enemy.health
        enemy.health = max(0, min(enemy.profile.health, health))
        if enemy.health != before:
            self.changed_health_ids.add(enemy.enemy_id)
            if not enemy.alive and enemy.knockback_remaining_seconds > 0:
                enemy.death_remaining_seconds = self.death_seconds
        return before, enemy.health

    def damage_enemy(self, enemy_id, amount):
        """교전에서 피해를 확정하고 피격 직전·직후 HP를 반환한다."""
        if type(amount) is not int or amount < 0:
            raise ValueError("피해량은 0 이상의 정수여야 한다.")
        enemy = self.enemies[enemy_id]
        before, after = self._set_enemy_health(enemy, enemy.health - amount)
        if before > 0 and after == 0:
            self.update_result()
        return before, after

    def sync_health(self, health_by_id, player_health):
        for enemy_id, health in health_by_id.items():
            self._set_enemy_health(self.enemies[enemy_id], health)
        self.update_result(player_health)

    def update_result(self, player_health=None):
        if player_health is not None and player_health <= 0:
            self.result = "defeat"
        elif self.result == "running" and not any(enemy.alive for enemy in self.enemies.values()):
            self.result = "victory"
        if self.result != "running":
            self.projectiles.clear()

    def knock_back(self, enemy_id, direction, *, source="sword"):
        """명중 한 번의 감속 이동. 총탄은 행동을 끊지 않으며 강한 검 넉백을 덮지 않는다."""
        if source not in ("sword", "gun"):
            raise ValueError("넉백 발생원은 sword 또는 gun이다.")
        enemy = self.enemies[enemy_id]
        if not all(isfinite(value) for value in (direction.x, direction.y)):
            raise ValueError("넉백 방향은 유한한 벡터다.")
        if not enemy.alive or direction.length < 1e-9:
            return
        if source == "gun" and enemy.knockback_interrupts and enemy.knockback_remaining_seconds > 0:
            return
        interrupts = source == "sword"
        duration = self.knockback_seconds if interrupts else self.gun_knockback_seconds
        distances = self.knockback_distances if interrupts else self.gun_knockback_distances
        distance = distances[enemy.profile.kind]
        enemy.knockback_velocity_mps = direction.normalized() * (2 * distance / duration)
        enemy.knockback_remaining_seconds = enemy.knockback_duration_seconds = duration
        enemy.knockback_interrupts = interrupts
        if interrupts:
            enemy.phase, enemy.remaining_seconds = "stagger", 0

    def _advance_reaction(self, enemy, seconds):
        remaining = enemy.knockback_remaining_seconds
        elapsed = min(seconds, remaining)
        if elapsed > 0:
            # 선형 감속 속도를 구간 적분해 프레임 수와 관계없이 지정 거리만큼 민다.
            amount = (remaining * elapsed - elapsed * elapsed / 2) / enemy.knockback_duration_seconds
            self._move(enemy, enemy.knockback_velocity_mps * amount)
            enemy.knockback_remaining_seconds = max(0, remaining - elapsed)
            if enemy.knockback_remaining_seconds < 1e-9:
                enemy.knockback_remaining_seconds = 0
                if enemy.alive and enemy.knockback_interrupts:
                    enemy.phase = "move"
        if not enemy.alive:
            enemy.death_remaining_seconds = max(0, enemy.death_remaining_seconds - seconds)

    def advance_reactions(self, seconds):
        """교전 종료 뒤에도 잔여 밀림·사망 표시만 진행한다. 공격·게임 시간은 멈춘다."""
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("피격 표현 갱신은 0 이상의 유한한 초다.")
        self.spacing = self.spacing.sync(self.enemies.values())
        for enemy in self.enemies.values():
            self._advance_reaction(enemy, seconds)

    def _move(self, enemy, movement):
        radius = enemy.profile.radius_m
        maximum = self.map_size_m - radius
        origin = enemy.position_m
        candidate = Vec2(max(radius, min(maximum, origin.x + movement.x)),
                         max(radius, min(maximum, origin.y + movement.y)))
        if enemy.alive:
            resolved = self.spacing.separate(enemy, candidate)
            if resolved is not candidate:
                candidate = Vec2(max(radius, min(maximum, resolved.x)), max(radius, min(maximum, resolved.y)))
            self.spacing.moved(enemy, candidate)
        dx, dy = candidate.x - origin.x, candidate.y - origin.y
        distance = hypot(dx, dy)
        enemy.travel_m += distance
        enemy.position_m = candidate

    def _begin_attack(self, enemy, kind):
        enemy.attack_kind = kind
        enemy.phase = "windup"
        enemy.remaining_seconds = enemy.profile.windup_seconds
        enemy.hit_player = False

    def _think(self, enemy, seconds, player):
        profile = enemy.profile
        dx, dy = player.x - enemy.position_m.x, player.y - enemy.position_m.y
        distance = hypot(dx, dy)
        if distance > 1e-9:
            inverse = 1 / distance
            enemy.facing = Vec2(dx * inverse, dy * inverse)
        if profile.kind != "medium" and distance <= profile.melee_reach_m + self.player_radius_m:
            self._begin_attack(enemy, "melee")
            return
        if profile.kind != "small" and distance <= profile.fire_range_m:
            self._begin_attack(enemy, "ranged")
            return
        self._move(enemy, enemy.facing * min(profile.speed_mps * seconds,
                                           max(0, distance - profile.radius_m - self.player_radius_m)))

    def _advance_enemy(self, enemy, seconds, start, end):
        interrupts = enemy.knockback_interrupts and enemy.knockback_remaining_seconds > 0
        if enemy.knockback_remaining_seconds > 0 or not enemy.alive:
            self._advance_reaction(enemy, seconds)
            if interrupts or not enemy.alive:
                return
        profile = enemy.profile
        if enemy.phase == "move":
            self._think(enemy, seconds, end)
        elif enemy.phase == "recovery":
            # 사격 후 회수 중에 거리를 조절한다. 준비·공격 중에는 방향을 고정한다.
            if enemy.attack_kind == "ranged":
                delta = end - enemy.position_m
                error = delta.length - profile.preferred_range_m
                self._move(enemy, delta.normalized() * max(-profile.speed_mps * seconds,
                                                          min(profile.speed_mps * seconds, error)))
        if enemy.phase == "active" and enemy.attack_kind == "melee" and not enemy.hit_player:
            if moving_circle_touches_polygon(start, end, self.player_radius_m, enemy.attack_polygon):
                self.hit_events.append(EnemyHit(enemy.enemy_id, "melee", profile.melee_damage, enemy.facing))
                enemy.hit_player = True
        if enemy.phase == "move":
            return
        enemy.remaining_seconds -= seconds
        if enemy.remaining_seconds > 1e-9:
            return
        if enemy.phase == "windup":
            enemy.phase = "active"
            enemy.remaining_seconds += profile.active_seconds
            if enemy.attack_kind == "ranged":
                muzzle = enemy.position_m + enemy.facing * (profile.radius_m + .5)
                self.projectiles.append(EnemyProjectile(enemy.enemy_id, muzzle, muzzle, enemy.facing,
                    profile.projectile_range_m, profile.projectile_speed_mps, profile.shot_damage))
                self.shots_fired += 1
        elif enemy.phase == "active":
            enemy.phase = "recovery"
            enemy.remaining_seconds += profile.recovery_seconds
        else:
            enemy.phase, enemy.remaining_seconds = "move", 0

    def advance(self, seconds, previous_player_m, player_m):
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("교전 갱신 시간은 0 이상의 유한한 초다.")
        self.hit_events = []
        if self.result != "running" or seconds == 0:
            return ()
        start, end = Vec2(*previous_player_m), Vec2(*player_m)
        if not all(isfinite(v) for v in (start.x, start.y, end.x, end.y)):
            raise ValueError("플레이어 위치는 유한한 미터 좌표다.")
        count = max(1, ceil(seconds * 120))
        step = seconds / count
        self.spacing = self.spacing.sync(self.enemies.values())
        for index in range(count):
            first = start + (end - start) * (index / count)
            last = start + (end - start) * ((index + 1) / count)
            # 새 탄환은 다음 구간부터 이동시켜 발사 전 시간을 소비하지 않는다.
            survivors = []
            for bullet in self.projectiles:
                distance = min(bullet.remaining_m, bullet.speed_mps * step)
                destination = bullet.position_m + bullet.direction * distance
                fraction = distance / (bullet.speed_mps * step)
                target_end = first + (last - first) * fraction
                if segment_circle(bullet.position_m - first, destination - target_end,
                                  Vec2(), self.player_radius_m + .35) is not None:
                    self.hit_events.append(EnemyHit(bullet.owner, "ranged", bullet.damage, bullet.direction))
                    continue
                bullet.previous_m, bullet.position_m = bullet.position_m, destination
                bullet.remaining_m -= distance
                if (bullet.remaining_m > 1e-9 and 0 <= destination.x <= self.map_size_m
                        and 0 <= destination.y <= self.map_size_m):
                    survivors.append(bullet)
            self.projectiles = survivors
            for enemy in self.enemies.values():
                self._advance_enemy(enemy, step, first, last)
            self.elapsed_seconds += step
        return tuple(self.hits)

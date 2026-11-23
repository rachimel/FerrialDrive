"""소형 근접·중형 사격·인간형 복합 교전. 거리 m·시간 초이며 창을 소유하지 않는다."""

from dataclasses import dataclass
from math import ceil, hypot, isfinite, isqrt

from .geometry import Vec2, _segment_circle_fraction, moving_circle_touches_polygon
from .enemy_spacing import EnemySpacing
from .enemy_storage import EncounterEnemy, EnemyActors
from .entity_storage import EntityRegistry
from .projectile_storage import EnemyProjectile, EnemyProjectileView, ProjectileGroup, projectile_storage
from .enemy_steering import MELEE_ATTACK, pursuit, ranged_recovery
from .numeric_runtime import configure_combat_blas


ENEMY_KINDS = ("small", "medium", "humanoid")
MIN_BATCH_ENEMIES = 8


def _movement_batch(count):
    if count < MIN_BATCH_ENEMIES:
        return None
    configure_combat_blas()
    try:
        from numba import config
    except ModuleNotFoundError as error:
        if error.name not in {"numba", "numpy"}:
            raise
        return None
    if config.DISABLE_JIT:
        return None
    from .enemy_movement_batch import EnemyMovementBatch
    return EnemyMovementBatch(count)


def crowd_spawns(source, count, spacing_m, center_m, map_size_m):
    """기존 출현 순서의 기종을 반복해 플레이어 중심의 시험 대형을 만든다."""
    if type(count) is not int or count < 1 or not source:
        raise ValueError("대형에는 양수 적 수와 기존 출현 기종이 필요하다.")
    if not isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError("적 간격은 양수 유한 거리여야 한다.")
    columns = isqrt(count - 1) + 1
    rows = (count + columns - 1) // columns
    px, py = center_m
    half_width = (columns - 1) * spacing_m / 2
    half_height = (rows - 1) * spacing_m / 2
    if half_width > min(px, map_size_m - px) or half_height > min(py, map_size_m - py):
        raise ValueError("적 대형이 전장 범위를 벗어난다.")
    return [{"id": f"crowd{i:04}", "profile": source[i % len(source)]["profile"],
             "position_m": [px - half_width + (i % columns) * spacing_m,
                            py - half_height + (i // columns) * spacing_m]} for i in range(count)]


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
        if self.kind not in ENEMY_KINDS:
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


@dataclass(frozen=True, slots=True)
class EnemyHit:
    attacker_id: str
    attack_kind: str
    damage: int
    direction: Vec2


class EnemyEncounter:
    def __init__(self, settings, *, map_size_m, player_radius_m, registry=None, projectiles=None):
        self.settings = settings
        self.map_size_m, self.player_radius_m = map_size_m, player_radius_m
        if not all(isfinite(v) and v > 0 for v in (map_size_m, player_radius_m)):
            raise ValueError("훈련장 크기·플레이어 반경은 양수다.")
        self.profiles = {key: EnemyProfile(**value) for key, value in settings["profiles"].items()}
        reaction = settings.get("knockback", {})
        self.knockback_seconds = reaction.get("duration_seconds", .12)
        self.death_seconds = reaction.get("death_seconds", .22)
        self.sprite_death_seconds = {}
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
        self.registry = registry if registry is not None else EntityRegistry()
        self.enemies = EnemyActors(self.registry, len(settings["spawns"]))
        storage = projectile_storage(self.registry) if projectiles is None else projectiles
        self._projectiles = ProjectileGroup(storage, EnemyProjectileView)
        self.reset()

    @property
    def projectiles(self):
        return self._projectiles

    @projectiles.setter
    def projectiles(self, bullets):
        bullets = list(bullets)
        self._projectiles.clear()
        for bullet in bullets:
            owner = self.enemies.get(bullet.owner)
            self._projectiles.append(bullet, owner_eid=owner.eid if owner is not None else None)

    def reset(self):
        spawns = {}
        for row in self.settings["spawns"]:
            profile = self.profiles[row["profile"]]
            position = Vec2(*row["position_m"])
            radius = profile.radius_m
            if (row["id"] in spawns or not row["id"]
                    or not all(isfinite(v) and radius <= v <= self.map_size_m - radius
                               for v in (position.x, position.y))):
                raise ValueError("적 ID 중복 또는 출현 위치 범위 오류")
            spawns[row["id"]] = EncounterEnemy(row["id"], profile, position, profile.health)
        if not spawns:
            raise ValueError("교전에는 적이 한 기 이상 필요하다.")
        self.enemies.clear()
        self.enemies.update(spawns)
        self.movement_batch = _movement_batch(len(spawns))
        self._spacing = None
        if self.movement_batch is None:
            self._sync_spacing()
        self.changed_health_ids = set()
        self.projectiles.clear()
        self.hit_events = []
        self.elapsed_seconds = 0
        self.result = "running"
        self.shots_fired = 0

    def _sync_spacing(self):
        enemies = self.enemies.values()
        if self._spacing is None:
            self._spacing = EnemySpacing(enemies, 2 * max((enemy.profile.radius_m for enemy in enemies), default=.5))
        else:
            self._spacing = self._spacing.sync(enemies)
        return self._spacing

    @property
    def spacing(self):
        return self._sync_spacing()

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
            if not enemy.alive:
                duration = self.sprite_death_seconds.get(enemy.profile.kind)
                if duration is not None or enemy.knockback_remaining_seconds > 0:
                    enemy.death_remaining_seconds = self.death_seconds if duration is None else duration
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
        if interrupts and enemy.phase != "break":
            enemy.phase, enemy.remaining_seconds = "stagger", 0

    def counter_break(self, enemy_id, direction, duration_seconds):
        enemy = self.enemies.get(enemy_id)
        if enemy is None or not enemy.alive:
            return
        self.knock_back(enemy_id, direction)
        enemy.phase = "break"
        enemy.remaining_seconds = enemy.break_duration_seconds = duration_seconds

    def _take_reaction_movement(self, enemy, seconds):
        remaining = enemy.knockback_remaining_seconds
        elapsed = min(seconds, remaining)
        movement = None
        if elapsed > 0:
            # 선형 감속 속도를 구간 적분해 프레임 수와 관계없이 지정 거리만큼 민다.
            amount = (remaining * elapsed - elapsed * elapsed / 2) / enemy.knockback_duration_seconds
            movement = enemy.knockback_velocity_mps * amount
            enemy.knockback_remaining_seconds = max(0, remaining - elapsed)
            if enemy.knockback_remaining_seconds < 1e-9:
                enemy.knockback_remaining_seconds = 0
                if enemy.alive and enemy.knockback_interrupts and enemy.phase != "break":
                    enemy.phase = "move"
        if not enemy.alive:
            enemy.death_remaining_seconds = max(0, enemy.death_remaining_seconds - seconds)
        return movement

    def _advance_reaction(self, enemy, seconds):
        movement = self._take_reaction_movement(enemy, seconds)
        if movement is not None:
            self._move(enemy, movement)

    def advance_reactions(self, seconds):
        """교전 종료 뒤에도 잔여 밀림·사망 표시만 진행한다. 공격·게임 시간은 멈춘다."""
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("피격 표현 갱신은 0 이상의 유한한 초다.")
        if self.movement_batch is not None:
            self.movement_batch.advance(self, seconds, Vec2(), Vec2(), reactions_only=True)
        else:
            self._sync_spacing()
            for enemy in self.enemies.values():
                self._advance_reaction(enemy, seconds)

    def _move(self, enemy, movement, *, locomotion=False):
        body = enemy._record
        radius = body.radius
        maximum = self.map_size_m - radius
        candidate = Vec2(max(radius, min(maximum, body.x + movement.x)),
                         max(radius, min(maximum, body.y + movement.y)))
        if enemy.alive:
            resolved = self._spacing.separate(enemy, candidate)
            if resolved is not candidate:
                candidate = Vec2(max(radius, min(maximum, resolved.x)), max(radius, min(maximum, resolved.y)))
            self._spacing.moved(enemy, candidate)
        dx, dy = candidate.x - body.x, candidate.y - body.y
        distance = hypot(dx, dy)
        body.travel += distance
        if locomotion and movement.length > 1e-9:
            body.walk += distance
            body.walk_x += dx
            body.walk_y += dy
        body.x, body.y = candidate.x, candidate.y

    def _begin_attack(self, enemy, kind):
        enemy.attack_kind = kind
        enemy.phase = "windup"
        enemy.remaining_seconds = enemy.profile.windup_seconds
        enemy.hit_player = False

    def _think(self, enemy, seconds, player):
        body = enemy._record
        dx, dy = player.x - body.x, player.y - body.y
        reach = body.melee_reach + self.player_radius_m if body.melee_reach >= 0 else -1.
        fx, fy, mx, my, attack = pursuit(dx, dy, body.fx, body.fy, body.speed * seconds,
                                         body.radius, self.player_radius_m, reach, body.fire_distance)
        body.fx, body.fy = fx, fy
        if attack:
            self._begin_attack(enemy, "melee" if attack == MELEE_ATTACK else "ranged")
        else:
            self._move(enemy, Vec2(mx, my), locomotion=True)

    def _advance_enemy(self, enemy, seconds, start, end):
        interrupts = enemy.knockback_interrupts and enemy.knockback_remaining_seconds > 0
        if enemy.knockback_remaining_seconds > 0 or not enemy.alive:
            self._advance_reaction(enemy, seconds)
            if (interrupts and enemy.phase != "break") or not enemy.alive:
                return
        if enemy.phase == "break":
            enemy.remaining_seconds = max(0, enemy.remaining_seconds - seconds)
            if enemy.remaining_seconds <= 1e-9:
                enemy.phase = "move"
            return
        profile = enemy.profile
        if enemy.phase == "move":
            self._think(enemy, seconds, end)
        elif enemy.phase == "recovery":
            # 사격 후 회수 중에 거리를 조절한다. 준비·공격 중에는 방향을 고정한다.
            if enemy.attack_kind == "ranged":
                delta = end - enemy.position_m
                movement = ranged_recovery(delta.x, delta.y, profile.speed_mps * seconds, profile.preferred_range_m)
                self._move(enemy, Vec2(*movement), locomotion=True)
        self._advance_attack(enemy, seconds, start, end)

    def _advance_attack(self, enemy, seconds, start, end):
        profile = enemy.profile
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
                self.projectiles.spawn(enemy.eid, owner=enemy.enemy_id, position_m=muzzle, previous_m=muzzle,
                    direction=enemy.facing, remaining_m=profile.projectile_range_m,
                    speed_mps=profile.projectile_speed_mps, damage=profile.shot_damage)
                self.shots_fired += 1
        elif enemy.phase == "active":
            enemy.phase = "recovery"
            enemy.remaining_seconds += profile.recovery_seconds
        else:
            enemy.phase, enemy.remaining_seconds = "move", 0

    def _advance_enemies(self, step, start, end):
        if self.movement_batch is not None:
            self.movement_batch.advance(self, step, start, end)
        else:
            for enemy in self.enemies.values():
                self._advance_enemy(enemy, step, start, end)

    def advance(self, seconds, previous_player_m, player_m):
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("교전 갱신 시간은 0 이상의 유한한 초다.")
        self.hit_events = []
        if self.movement_batch is None:
            stationary = Vec2()
            for enemy in self.enemies.values():
                enemy.locomotion_step_m = stationary
        else:
            self.movement_batch.reset_locomotion(self.enemies.storage)
        if self.result != "running" or seconds == 0:
            return ()
        start, end = Vec2(*previous_player_m), Vec2(*player_m)
        if not all(isfinite(v) for v in (start.x, start.y, end.x, end.y)):
            raise ValueError("플레이어 위치는 유한한 미터 좌표다.")
        count = max(1, ceil(seconds * 120))
        step = seconds / count
        if self.movement_batch is None:
            self._sync_spacing()
        for index in range(count):
            first = start + (end - start) * (index / count)
            last = start + (end - start) * ((index + 1) / count)
            # 새 탄환은 다음 구간부터 이동시켜 발사 전 시간을 소비하지 않는다.
            self._advance_projectiles(step, first, last)
            self._advance_enemies(step, first, last)
            self.elapsed_seconds += step
        return tuple(self.hits)


    def _advance_projectiles(self, seconds, start, end):
        expired = []
        move_x, move_y = end.x - start.x, end.y - start.y
        radius = self.player_radius_m + .35
        for bullet in self.projectiles:
            row = bullet._record
            step = row.speed * seconds
            distance = min(row.remaining, step)
            x, y = row.x, row.y
            dx, dy = x + row.dx * distance, y + row.dy * distance
            fraction = distance / step
            from_x, from_y = x - start.x, y - start.y
            ray_x = dx - (start.x + move_x * fraction) - from_x
            ray_y = dy - (start.y + move_y * fraction) - from_y
            if _segment_circle_fraction(ray_x, ray_y, ray_x * ray_x + ray_y * ray_y, from_x, from_y, radius) >= 0:
                self.hit_events.append(EnemyHit(bullet.owner, "ranged", bullet.damage, bullet.direction))
                expired.append(bullet)
                continue
            row.previous_x, row.previous_y, row.x, row.y = x, y, dx, dy
            row.remaining -= distance
            if row.remaining <= 1e-9 or not (0 <= dx <= self.map_size_m and 0 <= dy <= self.map_size_m):
                expired.append(bullet)
        for bullet in expired:
            self.projectiles.discard(bullet)

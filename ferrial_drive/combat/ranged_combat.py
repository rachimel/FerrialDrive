"""기관단총의 연사·회복·투영 월드 좌표 탄환. 창·HUD·이미지와 독립이다."""

from dataclasses import dataclass, field
from math import cos, floor, hypot, isfinite, radians, sin
from random import Random

from .ammo import recovered_rounds
from .config import CombatConfig
from .geometry import Vec2, segment_circle


@dataclass
class GunProjectile:
    shot_id: int
    position: Vec2
    direction: Vec2
    remaining_pixels: float
    previous: Vec2
    traveled_pixels: float = 0
    damage: int = 9
    penetrations_remaining: int = 0
    hit_target_ids: set = field(default_factory=set)
    explosion_radius_m: float = 0
    explosion_damage: int = 0


@dataclass(frozen=True)
class GunImpact:
    position: Vec2
    direction: Vec2
    damage: int
    explosion_radius_m: float = 0
    explosion_damage: int = 0


def explosion_targets(impact, primary_target, targets, projection):
    """명중점과 적 중심의 지면 거리를 비교한다. 표시 높이는 거리에서 제외한다."""
    offset = Vec2(*projection.unproject((impact.position.x - primary_target.center.x,
                                         impact.position.y - primary_target.center.y)))
    primary_position = primary_target.position_m
    for target in targets:
        if primary_position is not None and target.position_m is not None:
            delta = Vec2(*target.position_m) - Vec2(*primary_position) - offset
        else:
            delta = Vec2(*projection.unproject((target.center.x - impact.position.x,
                                               target.center.y - impact.position.y)))
        if delta.length <= impact.explosion_radius_m:
            yield target


class RangedCombat:
    def __init__(self, settings=None, *, seed=0, range_m=None, projection=None, penetration_count=0):
        if (range_m is None) != (projection is None):
            raise ValueError("미터 사거리와 월드 투영은 함께 지정해야 한다.")
        if range_m is not None and (isinstance(range_m, bool) or not isfinite(range_m) or range_m <= 0):
            raise ValueError("탄환 사거리는 양수 유한 미터 값이어야 한다.")
        if type(penetration_count) is not int or penetration_count < 0:
            raise ValueError("탄환 관통 횟수는 0 이상 정수다.")
        self.penetration_count = penetration_count
        self.settings = settings or CombatConfig()
        self.seed = seed
        self.range_m, self.projection = range_m, projection
        self.reset()

    def reset(self):
        self.random = Random(self.seed)
        self.elapsed_seconds = 0.0
        self.ammo = self.settings.magazine_rounds
        self.recovery_fraction = 0.0
        self.last_shot_seconds = -1e6
        self.next_shot_seconds = 0.0
        self.projectiles = []
        self.hits = []
        self.hit_details = {}
        self.impact_events = []
        self.trigger_events = []
        self.shots_fired = 0
        self.muzzle = Vec2()
        self.shot_direction = Vec2(1, 0)
        self.rate = 1.0

    @property
    def shot_age_seconds(self):
        return self.elapsed_seconds - self.last_shot_seconds

    @property
    def interval_seconds(self):
        return self.settings.shot_interval_seconds / self.rate

    def _recover_until(self, time_seconds):
        amount = recovered_rounds(self.settings, self.elapsed_seconds, time_seconds, self.last_shot_seconds)
        progress = self.recovery_fraction + amount
        whole = min(self.settings.magazine_rounds - self.ammo, floor(progress + 1e-9))
        self.ammo += whole
        self.recovery_fraction = max(0, progress - whole) if self.ammo < self.settings.magazine_rounds else 0
        self.elapsed_seconds = time_seconds

    def _advance_projectile(self, projectile, seconds, targets):
        distance = min(projectile.remaining_pixels, self.settings.bullet_speed_units_per_second * seconds)
        end = projectile.position + projectile.direction * distance
        contacts = [(time, target.target_id) for target in targets
                    if target.target_id not in projectile.hit_target_ids and (time := segment_circle(
            projectile.position, end, target.center, target.radius_pixels + self.settings.bullet_radius_units)) is not None]
        for time, target_id in sorted(contacts):
            position = projectile.position + (end - projectile.position) * time
            impact = GunImpact(position, projectile.direction, projectile.damage,
                               projectile.explosion_radius_m, projectile.explosion_damage)
            self.hits.append((projectile.shot_id, target_id))
            self.hit_details[projectile.shot_id] = impact
            self.impact_events.append((projectile.shot_id, target_id, impact))
            projectile.hit_target_ids.add(target_id)
            if projectile.penetrations_remaining <= 0:
                projectile.previous, projectile.position = projectile.position, position
                projectile.traveled_pixels += distance * time
                projectile.remaining_pixels -= distance * time
                return False
            projectile.penetrations_remaining -= 1
        projectile.previous, projectile.position = projectile.position, end
        projectile.remaining_pixels -= distance
        projectile.traveled_pixels += distance
        return projectile.remaining_pixels > 1e-9

    def update(self, delta_seconds, origin, target, targets=(), *, firing=False, aiming=False, rate=1, max_shots=None,
               damage=None, consume_ammo=True, explosion_radius_m=0, explosion_damage=0):
        if not isfinite(delta_seconds) or delta_seconds < 0 or not isfinite(rate) or rate <= 0:
            raise ValueError("갱신 시간은 0 이상 초, 연사 배율은 양수다.")
        if max_shots is not None and (type(max_shots) is not int or max_shots <= 0):
            raise ValueError("단발 요청의 발사 한도는 양수 정수다.")
        damage = self.settings.bullet_damage if damage is None else damage
        if type(damage) is not int or damage <= 0 or type(consume_ammo) is not bool:
            raise ValueError("총탄 피해량은 양수 정수, 탄약 소모 여부는 bool이다.")
        if (not isfinite(explosion_radius_m) or explosion_radius_m < 0
                or type(explosion_damage) is not int or explosion_damage < 0
                or bool(explosion_radius_m) != bool(explosion_damage)):
            raise ValueError("폭발 반경·피해는 함께 양수 또는 함께 0이어야 한다.")
        start, end = self.elapsed_seconds, self.elapsed_seconds + delta_seconds
        self.hits = []
        self.hit_details = {}
        self.impact_events = []
        self.trigger_events = []
        if rate != self.rate:
            self.next_shot_seconds = start + max(0, self.next_shot_seconds - start) * self.rate / rate
            self.rate = rate
        self.projectiles = [p for p in self.projectiles if self._advance_projectile(p, delta_seconds, targets)]
        if firing:
            time = max(start, self.next_shot_seconds)
            attempts = 0
            while time < end - 1e-10 and (max_shots is None or attempts < max_shots):
                attempts += 1
                self._recover_until(time)
                if self.ammo or not consume_ammo:
                    muzzle = origin(time - start) if callable(origin) else origin
                    spread = self.settings.aim_spread_degrees if aiming else self.settings.hip_spread_degrees
                    angle = radians(self.random.uniform(-spread, spread))
                    direction = (target - muzzle).normalized(Vec2(1, 0))
                    direction = Vec2(direction.x * cos(angle) - direction.y * sin(angle),
                                     direction.x * sin(angle) + direction.y * cos(angle))
                    if consume_ammo:
                        self.ammo -= 1
                        self.recovery_fraction = 0
                    self.last_shot_seconds = time
                    self.shots_fired += 1
                    self.trigger_events.append("shot")
                    self.muzzle, self.shot_direction = muzzle, direction
                    range_pixels = self.settings.bullet_range_units
                    if self.range_m is not None:
                        # 실제 발사 방향을 역투영해 1 투영 픽셀에 해당하는 미터를 구한다.
                        meters_per_pixel = hypot(*self.projection.unproject((direction.x, direction.y)))
                        range_pixels = self.range_m / meters_per_pixel
                    projectile = GunProjectile(self.shots_fired, muzzle, direction,
                        range_pixels, muzzle, damage=damage, penetrations_remaining=self.penetration_count,
                        explosion_radius_m=explosion_radius_m, explosion_damage=explosion_damage)
                    if self._advance_projectile(projectile, end - time, targets):
                        self.projectiles.append(projectile)
                else:
                    self.trigger_events.append("empty")
                self.next_shot_seconds = time + self.interval_seconds
                time = self.next_shot_seconds
        else:
            self.next_shot_seconds = max(start, self.next_shot_seconds)
        self._recover_until(end)

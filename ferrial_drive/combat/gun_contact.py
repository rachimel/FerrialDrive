"""총탄의 에너지 명중과 금속 불꽃. 판정·피해·카메라·렌더러를 소유하지 않는다."""

from dataclasses import dataclass
from math import cos, isfinite, sin
from random import Random

from .geometry import Vec2


@dataclass(frozen=True)
class GunMetalSpark:
    origin: Vec2
    velocity: Vec2
    created_seconds: float
    lifetime_seconds: float
    width_pixels: float


@dataclass(frozen=True)
class GunEnergyImpact:
    origin: Vec2
    direction: Vec2
    created_seconds: float
    lifetime_seconds: float
    radius_pixels: float


@dataclass(frozen=True)
class GunExplosion:
    origin: Vec2
    radii_pixels: Vec2
    created_seconds: float
    lifetime_seconds: float
    seed: int


class GunContactEffects:
    def __init__(self, settings=None):
        settings = settings or {}
        self.sparks_per_hit = settings.get("sparks_per_hit", 4)
        self.max_sparks = settings.get("max_sparks", 128)
        self.lifetime_seconds = settings.get("lifetime_seconds", .24)
        self.speed_pixels_per_second = settings.get("speed_pixels_per_second", 900)
        self.width_pixels = settings.get("width_pixels", 3.2)
        energy = settings.get("energy_impact", {})
        self.impact_seconds = energy.get("lifetime_seconds", .16)
        self.impact_radius_pixels = energy.get("radius_pixels", 36)
        self.max_impacts = energy.get("max_impacts", 64)
        explosion = settings.get("explosion", {})
        self.explosion_seconds = explosion.get("lifetime_seconds", .28)
        self.max_explosions = explosion.get("max_count", 48)
        self.explosion_rays = explosion.get("rays", 10)
        if any(type(v) is not int or v < 1 for v in (self.sparks_per_hit, self.max_sparks, self.max_impacts)):
            raise ValueError("총 명중 불꽃 수·상한은 양수 정수다.")
        if any(type(v) is not int or v < 1 for v in (self.max_explosions, self.explosion_rays)):
            raise ValueError("폭발 표시 상한·광선 수는 양수 정수다.")
        if not all(isfinite(v) and v > 0 for v in
                   (self.lifetime_seconds, self.speed_pixels_per_second, self.width_pixels,
                    self.impact_seconds, self.impact_radius_pixels, self.explosion_seconds)):
            raise ValueError("총 명중 불꽃의 시간·속도·너비는 양수 유한값이다.")
        self.reset()

    def reset(self):
        self.time_seconds = 0
        self.sparks = []
        self.impacts = []
        self.explosions = []

    def update(self, seconds):
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("총 불꽃 갱신은 0 이상의 유한한 초다.")
        self.time_seconds += seconds
        self.sparks = [spark for spark in self.sparks
                       if self.time_seconds - spark.created_seconds < spark.lifetime_seconds]
        self.impacts = [impact for impact in self.impacts
                        if self.time_seconds - impact.created_seconds < impact.lifetime_seconds]
        self.explosions = [blast for blast in self.explosions
                           if self.time_seconds - blast.created_seconds < blast.lifetime_seconds]

    def emit_explosion(self, position, radii_pixels, *, seed=0):
        if not all(isfinite(v) and v > 0 for v in radii_pixels):
            raise ValueError("폭발 표시 반경은 양수 유한 픽셀 두 값이다.")
        self.explosions.append(GunExplosion(position, Vec2(*radii_pixels), self.time_seconds,
                                           self.explosion_seconds, seed))
        self.explosions = self.explosions[-self.max_explosions:]

    def emit(self, position, direction, material, *, seed=0):
        direction = direction.normalized(Vec2(1, 0))
        self.impacts.append(GunEnergyImpact(position, direction, self.time_seconds,
            self.impact_seconds, self.impact_radius_pixels))
        self.impacts = self.impacts[-self.max_impacts:]
        if material not in ("metal", "steel"):
            return
        random = Random(seed)
        backward = direction * -1
        for _ in range(self.sparks_per_hit):
            angle = random.uniform(-1.1, 1.1)
            velocity = Vec2(backward.x * cos(angle) - backward.y * sin(angle),
                            backward.x * sin(angle) + backward.y * cos(angle))
            velocity = velocity * (self.speed_pixels_per_second * random.uniform(.45, 1))
            self.sparks.append(GunMetalSpark(position, velocity, self.time_seconds,
                self.lifetime_seconds * random.uniform(.65, 1), self.width_pixels))
        self.sparks = self.sparks[-self.max_sparks:]

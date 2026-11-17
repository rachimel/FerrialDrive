"""검 Trail을 따르는 명중 베임선과 재질별 금속 마찰 입자. 창·판정과 독립이다."""

from dataclasses import dataclass
from math import cos, isfinite, pi, sin
from random import Random

from .geometry import Vec2


@dataclass
class SlashMark:
    strike_id: int
    target_id: str
    points: tuple
    size_scale: float = 1
    material: str = "generic"
    angle_offset_degrees: float = 0
    spark_angle_offset_degrees: float = 0
    age_seconds: float = 0


@dataclass(frozen=True)
class MetalSpark:
    origin: Vec2
    velocity: Vec2
    created_seconds: float
    lifetime_seconds: float
    width_pixels: float
    size_scale: float = 1


class SwordContactEffects:
    def __init__(self, settings):
        self.settings = settings
        self.level_size_scales = tuple(settings.get("level_size_scales", (1, 1, 1)))
        if len(self.level_size_scales) != 3 or any(not isfinite(scale) or scale <= 0 for scale in self.level_size_scales):
            raise ValueError("명중 효과 크기는 에너지 1~3단계별 양수 유한 배율이어야 한다.")
        for name in ("slash_seconds", "spark_seconds", "spark_speed_pixels_per_second",
                     "slash_width_pixels", "spark_width_pixels"):
            if not isfinite(settings[name]) or settings[name] <= 0:
                raise ValueError("명중 효과 시간·속도·너비는 양수 유한값이다.")
        for name in ("sparks_per_hit", "max_sparks", "max_slashes"):
            if type(settings[name]) is not int or settings[name] < 1:
                raise ValueError("명중 효과 입자·베임선 상한은 양수 정수다.")
        grow, hold = settings.get("slash_grow_seconds", 0.07), settings.get("slash_hold_seconds", 0.03)
        if not all(isfinite(v) for v in (grow, hold)) or grow <= 0 or hold < 0 or grow + hold >= settings["slash_seconds"]:
            raise ValueError("베임선은 성장·유지 뒤에 사라질 시간이 필요하다.")
        jitter, angle = settings.get("size_jitter", 0.1), settings.get("angle_jitter_degrees", 6)
        if not isfinite(jitter) or not 0 <= jitter < 1 or not isfinite(angle) or not 0 <= angle <= 45:
            raise ValueError("명중 크기 변주는 0~1 미만, 각도 변주는 0~45도여야 한다.")
        blur, samples = settings.get("fade_blur_ratio",.18), settings.get("fade_blur_samples",8)
        if not isfinite(blur) or not 0 <= blur <= 1 or type(samples) is not int or not 1 <= samples <= 32:
            raise ValueError("베임선 지움 블러 범위·표본 수 오류")
        opacity_ratio = settings.get("fade_opacity_ratio", 0.1)
        if not isfinite(opacity_ratio) or not 0 < opacity_ratio <= 1:
            raise ValueError("베임선 소멸 경계의 투명도 보간 폭은 0 초과 1 이하다.")
        if not .5 < settings.get("slash_front_peak_ratio",.825) < 1:
            raise ValueError("베임선의 가장 굵은 지점은 진행 방향 앞쪽이어야 한다.")
        for exponent in (settings.get("slash_fade_exponent",6),settings.get("slash_shrink_exponent",10)):
            if not isfinite(exponent) or not 0 < exponent <= 20:
                raise ValueError("베임선 지움·축소의 지수 계수는 0 초과 20 이하다.")
        self.reset()

    def reset(self):
        self.time_seconds = 0
        self.slashes, self.sparks = [], []

    def slash_fade_progress(self, mark):
        grow = self.settings.get("slash_grow_seconds",.07)
        hold = self.settings.get("slash_hold_seconds",.03)
        duration = self.settings["slash_seconds"]-grow-hold
        return min(1,max(0,(mark.age_seconds-grow-hold)/duration))

    def slash_visual(self, mark):
        """Smoothstep 확대 후 위치·크기를 유지하며 전체 알파를 줄인다."""
        grow = self.settings.get("slash_grow_seconds", 0.07)
        progress = min(1, max(0, mark.age_seconds / grow))
        spread = progress * progress * (3 - 2 * progress)
        center = mark.points[1]
        points = tuple(center + (point - center) * (0.65 + 0.35 * spread) for point in mark.points)
        fade = self.slash_fade_progress(mark)
        opacity = 1 - fade * fade * (3 - 2 * fade)
        return points, (0.05 + 0.95 * spread) * mark.size_scale, opacity

    def slash_width_scale(self, visibility):
        """지워지는 경계만 가늘게 만들고 아직 보이는 구간의 두께는 유지한다."""
        exponent = self.settings.get("slash_shrink_exponent", 10)
        return 1 - (2 ** (exponent * (1 - visibility)) - 1) / (2 ** exponent - 1)

    def slash_visibility(self, mark, position):
        """지움 경계의 투명도를 Smoothstep 보간하고 별도로 진행축 블러를 적용한다."""
        progress = self.slash_fade_progress(mark)
        if progress <= 0:
            return 1
        if progress >= 1:
            return 0
        exponent = self.settings.get("slash_fade_exponent",6)
        progress = (2 ** (exponent * progress)-1)/(2 ** exponent-1)
        blur = self.settings.get("fade_blur_ratio",0.18)
        samples = self.settings.get("fade_blur_samples",8)
        opacity_width = self.settings.get("fade_opacity_ratio", 0.1)
        boundary = progress * (1+blur) - blur * .5
        values = []
        for index in range(samples):
            offset = blur * ((index+.5)/samples-.5)
            edge = min(1,max(0,(position-boundary-offset)/opacity_width+.5))
            values.append(edge*edge*(3-2*edge))
        return sum(values)/samples

    def update(self, seconds, hits, sections, targets, *, energy_level=1):
        if type(energy_level) is not int or not 1 <= energy_level <= 3:
            raise ValueError("명중 효과의 에너지 레벨은 1~3 정수여야 한다.")
        level_scale = self.level_size_scales[energy_level - 1]
        self.time_seconds += seconds
        paths = {}
        for section in sections:
            path = paths.setdefault(section.strike_id, [section.tip_a])
            path.append(section.tip_b)
        for mark in self.slashes:
            mark.age_seconds += seconds
        self.slashes = [mark for mark in self.slashes if mark.age_seconds < self.settings["slash_seconds"]]
        self.sparks = [spark for spark in self.sparks
                       if self.time_seconds - spark.created_seconds < spark.lifetime_seconds]
        if not self.settings.get("enabled", True):
            self.slashes, self.sparks = [], []
            return
        targets = {target.target_id: target for target in targets}
        for strike_id, target_id in hits:
            target = targets.get(target_id)
            path = paths.get(strike_id)
            if target is None or not path:
                continue
            # 표적에 가장 가까운 실제 검날 이동 구간의 접선으로 흩뿌린다.
            pairs = list(zip(path, path[1:]))
            start, end = min(pairs, key=lambda pair: ((pair[0] + pair[1]) * 0.5 - target.center).length)
            tangent = (end - start).normalized(Vec2(1, 0))
            origin = target.center
            random = Random(strike_id * 97 + sum(map(ord, target_id)))
            jitter = self.settings.get("size_jitter", 0.1)
            size_scale = random.uniform(1 - jitter, 1 + jitter)
            contact_scale = size_scale * level_scale
            angle_jitter = self.settings.get("angle_jitter_degrees", 6)
            slash_angle = random.uniform(-angle_jitter, angle_jitter)
            spark_angle = random.uniform(-angle_jitter, angle_jitter)

            def rotate(degrees):
                angle = degrees * pi / 180
                return Vec2(tangent.x * cos(angle) - tangent.y * sin(angle),
                            tangent.x * sin(angle) + tangent.y * cos(angle))

            slash_axis, spark_axis = rotate(slash_angle), rotate(spark_angle)
            half_length = min(48, target.radius_pixels + 12) * self.settings.get("slash_length_scale", 1) * contact_scale
            peak_ratio = self.settings.get("slash_front_peak_ratio",0.825)
            points = (origin - slash_axis * half_length, origin,
                      origin + slash_axis * half_length * (2 * peak_ratio - 1), origin + slash_axis * half_length)
            self.slashes.append(SlashMark(strike_id, target_id, points, size_scale=contact_scale,
                material=target.material, angle_offset_degrees=slash_angle, spark_angle_offset_degrees=spark_angle))
            if target.material != "metal":
                continue
            for _ in range(self.settings["sparks_per_hit"]):
                angle = random.uniform(-0.85, 0.85)
                direction = Vec2(spark_axis.x * cos(angle) - spark_axis.y * sin(angle),
                                 spark_axis.x * sin(angle) + spark_axis.y * cos(angle))
                speed = self.settings["spark_speed_pixels_per_second"] * random.uniform(0.45, 1.25) * size_scale
                self.sparks.append(MetalSpark(origin, direction * speed, self.time_seconds,
                    self.settings["spark_seconds"] * random.uniform(0.65, 1),
                    self.settings["spark_width_pixels"] * random.uniform(0.6, 1) * contact_scale,
                    size_scale=level_scale))
        self.slashes = self.slashes[-self.settings["max_slashes"]:]
        self.sparks = self.sparks[-self.settings["max_sparks"]:]

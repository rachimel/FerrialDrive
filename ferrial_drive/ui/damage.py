"""대상별 순간 피해 합산·숫자의 자릿수 크기·겹침 없는 배치·표시 수명."""

from dataclasses import dataclass
from math import atan2, cos, hypot, isfinite, radians, sin, tan
from random import Random
from typing import Callable

from ..animation import ScalarAnimation, smooth_step
from .components import Rect


@dataclass(frozen=True)
class DamageVisual:
    amount: int
    x: float
    y: float
    opacity: float
    owner: str = ""
    width_progress: float = 1.0
    height_progress: float = 1.0
    font_scale: float = 1.0


@dataclass
class DamagePopup:
    owner: str
    amount: int
    x: float
    y: float
    animation: ScalarAnimation
    font_scale: float
    width: float
    height: float
    offset_x_range: tuple[float, float]

    @property
    def bounds(self):
        start, end = self.offset_x_range
        return Rect(self.x - self.width / 2 + start, self.y, self.width + end - start, self.height)


@dataclass
class PendingDamage:
    owner: str
    amount: int
    x: float
    y: float
    ready_seconds: float
    offset_x_range: tuple[float, float]
    direction: tuple[float, float] | None


class DamageNumbers:
    def __init__(self, duration_seconds: float, scatter_x_pixels: float, scatter_y_pixels: float,
                 *, measure_text: Callable[[str], tuple[float, float]],
                 digit_scales=(1.0,), gap_pixels=6, overall_scale=1.0,
                 cone_half_angle_degrees=45.0, spawn_min_radius_pixels=48.0, spawn_max_radius_pixels=84.0,
                 cone_expand_hits=4,
                 width_expand_seconds: float = 0.10, height_expand_seconds: float = 0.12,
                 accumulation_seconds: float = 0.0):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("피해 숫자 표시 시간은 양수인 초 단위 값이어야 한다.")
        if not all(isfinite(value) and value >= 0 for value in (scatter_x_pixels, scatter_y_pixels)):
            raise ValueError("피해 숫자 분산 범위는 0 이상의 유한한 픽셀 값이어야 한다.")
        if not all(isfinite(value) and value >= 0 for value in
                   (width_expand_seconds, height_expand_seconds)):
            raise ValueError("피해 숫자 펼침 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        if 2 * (width_expand_seconds + height_expand_seconds) >= duration_seconds:
            raise ValueError("피해 숫자 등장·퇴장 시간의 합은 전체 표시 시간보다 짧아야 한다.")
        digit_scales = tuple(digit_scales)
        if not digit_scales or not all(isfinite(value) and value > 0 for value in digit_scales):
            raise ValueError("피해 숫자 자릿수 배율은 양수인 유한한 값이어야 한다.")
        if any(first > second for first, second in zip(digit_scales, digit_scales[1:])):
            raise ValueError("피해 숫자의 자릿수가 늘어날 때 배율이 줄어들 수 없다.")
        if not isfinite(gap_pixels) or gap_pixels < 0:
            raise ValueError("피해 숫자 간격은 0 이상의 유한한 픽셀 값이어야 한다.")
        if not isfinite(overall_scale) or overall_scale <= 0:
            raise ValueError("피해 숫자 전체 배율은 양수인 유한한 값이어야 한다.")
        if not isfinite(cone_half_angle_degrees) or not 0 < cone_half_angle_degrees < 90:
            raise ValueError("피해 숫자 부채꼴의 반각은 0도 초과 90도 미만이어야 한다.")
        if type(cone_expand_hits) is not int or cone_expand_hits < 2:
            raise ValueError("피해 숫자 부채꼴이 완전히 넓어지는 적중 횟수는 2 이상의 정수여야 한다.")
        if (not all(isfinite(value) for value in (spawn_min_radius_pixels, spawn_max_radius_pixels))
                or not 0 <= spawn_min_radius_pixels <= spawn_max_radius_pixels):
            raise ValueError("피해 숫자 생성 반경은 0 이상의 최소·최대 픽셀 값이어야 한다.")
        if not callable(measure_text):
            raise ValueError("실제 표시 글꼴의 크기를 측정하는 함수가 필요하다.")
        if not isfinite(accumulation_seconds) or accumulation_seconds < 0:
            raise ValueError("피해 합산 구간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.accumulation_seconds = accumulation_seconds
        self.elapsed_seconds = 0.0
        self.pending: dict[str, PendingDamage] = {}
        self.duration_seconds = duration_seconds
        self.width_expand_seconds = width_expand_seconds
        self.height_expand_seconds = height_expand_seconds
        self.scatter_x_pixels = scatter_x_pixels
        self.scatter_y_pixels = scatter_y_pixels
        self.measure_text = measure_text
        self.digit_scales = digit_scales
        self.gap_pixels = gap_pixels
        self.overall_scale = overall_scale
        self.cone_half_angle = radians(cone_half_angle_degrees)
        self.cone_expand_hits = cone_expand_hits
        self._directed_hit_counts: dict[str, int] = {}
        self.spawn_min_radius_pixels = spawn_min_radius_pixels
        self.spawn_max_radius_pixels = spawn_max_radius_pixels
        self.random = Random()
        self.popups: list[DamagePopup] = []

    def add(self, owner: str, amount: int, x: float, y: float, *, offset_x_range=(0.0, 0.0),
            direction: tuple[float, float] | None = None):
        """방향은 화면 기준 오른쪽 +X·아래쪽 +Y이며 연속 적중은 owner별로 센다."""
        if type(amount) is not int:
            raise ValueError("피해량은 정수여야 한다.")
        if amount <= 0:
            return
        if not all(isfinite(value) for value in (x, y)):
            raise ValueError("피격 좌표는 유한한 픽셀 값이어야 한다.")
        if (len(offset_x_range) != 2 or not all(isfinite(value) for value in offset_x_range)
                or offset_x_range[0] > offset_x_range[1]):
            raise ValueError("장면 이동 범위는 순서가 맞는 유한한 두 픽셀 값이어야 한다.")
        if direction is not None:
            if len(direction) != 2 or not all(isfinite(value) for value in direction):
                raise ValueError("피해 숫자 공격 방향은 유한한 2차원 벡터여야 한다.")
            length = hypot(*direction)
            if not isfinite(length) or length == 0:
                raise ValueError("피해 숫자 공격 방향은 길이가 0이 아닌 유한한 벡터여야 한다.")
        if self.accumulation_seconds > 0:
            pending = self.pending.get(owner)
            if pending is None:
                self.pending[owner] = PendingDamage(owner, amount, x, y,
                    self.elapsed_seconds + self.accumulation_seconds, tuple(offset_x_range),
                    tuple(direction) if direction is not None else None)
            else:
                # 첫 명중의 마감과 위치를 고정해 연사 중에도 표시를 계속 미루지 않는다.
                pending.amount += amount
            return
        self._create_popup(owner, amount, x, y, offset_x_range, direction)

    def _create_popup(self, owner, amount, x, y, offset_x_range, direction):
        text = str(amount)
        scale = self.overall_scale * self.digit_scales[min(len(text), len(self.digit_scales)) - 1]
        width, height = self.measure_text(text)
        if not all(isfinite(value) and value > 0 for value in (width, height)):
            raise ValueError("피해 숫자의 측정 크기는 양수인 유한한 픽셀 값이어야 한다.")
        width, height = width * scale, height * scale
        start, end = offset_x_range
        # 장면 전환 때 플레이어는 고정되고 타겟 숫자는 이동하므로 이동 폭도 예약한다.
        center_offset = (start + end) / 2
        if direction is None:
            x += self.random.uniform(-self.scatter_x_pixels, self.scatter_x_pixels)
            y += self.random.uniform(-self.scatter_y_pixels, self.scatter_y_pixels)
            x, y = self._vacant_position(x + center_offset, y, width + end - start, height)
        else:
            length = hypot(*direction)
            unit = (direction[0] / length, direction[1] / length)
            hit_count = self._directed_hit_counts.get(owner, 0)
            spread = self.cone_half_angle * min(1.0, hit_count / (self.cone_expand_hits - 1))
            x, y = self._vacant_cone_position(x + center_offset, y, width + end - start, height, unit, spread)
            self._directed_hit_counts[owner] = min(hit_count + 1, self.cone_expand_hits - 1)
        x -= center_offset
        self.popups.append(DamagePopup(owner, amount, x, y,
                                       ScalarAnimation(0, 1, self.duration_seconds), scale, width, height,
                                       (start, end)))

    def _vacant_cone_position(self, origin_x, origin_y, width, height, direction, spread):
        """중심 배치각을 점차 넓히고, 완성 크기는 최대 부채꼴 안에서 기존 숫자를 피한다."""
        occupied = [popup.bounds for popup in self.popups]
        gap = self.gap_pixels
        dx, dy = direction
        tangent = tan(self.cone_half_angle)
        forward = abs(dx) * width / 2 + abs(dy) * height / 2
        sideways = abs(dy) * width / 2 + abs(dx) * height / 2
        radius = max(self.random.uniform(self.spawn_min_radius_pixels, self.spawn_max_radius_pixels),
                     forward + sideways / tangent + gap)
        angle = atan2(dy, dx)
        random_angle = self.random.uniform(-spread, spread)
        offsets = (random_angle, 0, -spread / 2, spread / 2, -spread / 4, spread / 4)
        farthest = max((hypot(cx - origin_x, cy - origin_y)
                        for rect in occupied for cx in (rect.x, rect.x + rect.width)
                        for cy in (rect.y, rect.y + rect.height)), default=0)
        clear_radius = max(radius, farthest + hypot(width, height) + gap + radius)
        step = max(16.0, height + gap, width / 2 + gap)
        while True:
            for offset in offsets:
                cx, cy = origin_x + cos(angle + offset) * radius, origin_y + sin(angle + offset) * radius
                left, top = cx - width / 2, cy - height / 2
                if not all(
                    (px - origin_x) * dx + (py - origin_y) * dy > 0
                    and abs((px - origin_x) * dy - (py - origin_y) * dx)
                    <= ((px - origin_x) * dx + (py - origin_y) * dy) * tangent + 1e-8
                    for px in (left, left + width) for py in (top, top + height)
                ):
                    continue
                if all(left + width + gap <= rect.x or left >= rect.x + rect.width + gap
                       or top + height + gap <= rect.y or top >= rect.y + rect.height + gap
                       for rect in occupied):
                    return cx, top
            if radius >= clear_radius:
                raise RuntimeError("공격 방향 피해 숫자의 빈자리를 찾을 수 없다.")
            radius = min(clear_radius, radius + step)

    def _vacant_position(self, x, y, width, height):
        """초기 분산 위치에서 가까운 빈자리를 고르고 기존 완성 크기를 피한다."""
        occupied = [popup.bounds for popup in self.popups]
        gap = self.gap_pixels

        def vacant(cx, cy):
            left, right = cx - width / 2, cx + width / 2
            return all(right + gap <= rect.x or left >= rect.x + rect.width + gap
                       or cy + height + gap <= rect.y or cy >= rect.y + rect.height + gap
                       for rect in occupied)

        if vacant(x, y):
            return x, y
        xs, ys = {x}, {y}
        for rect in occupied:
            xs.update((rect.x - gap - width / 2, rect.x + rect.width + gap + width / 2))
            ys.update((rect.y - gap - height, rect.y + rect.height + gap))
        candidates = sorted(((cx, cy) for cx in xs for cy in ys),
                            key=lambda point: ((point[0] - x) ** 2 + (point[1] - y) ** 2,
                                               point[1], point[0]))
        for cx, cy in candidates:
            if vacant(cx, cy):
                return cx, cy
        raise RuntimeError("피해 숫자의 배치 후보가 없다.")

    def update(self, delta_seconds, *, accumulation_delta_seconds=None):
        """표시 애니메이션 시간과 실제 초 기준 피해 합산 시간을 구분한다."""
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("피해 숫자 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        if accumulation_delta_seconds is None:
            accumulation_delta_seconds = delta_seconds
        if not isfinite(accumulation_delta_seconds) or accumulation_delta_seconds < 0:
            raise ValueError("피해 합산 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.elapsed_seconds += accumulation_delta_seconds
        for popup in self.popups:
            popup.animation.update(delta_seconds)
        self.popups = [popup for popup in self.popups if not popup.animation.finished]
        for owner, pending in list(self.pending.items()):
            if self.elapsed_seconds + 1e-9 < pending.ready_seconds:
                continue
            del self.pending[owner]
            animation_speed = delta_seconds / accumulation_delta_seconds if accumulation_delta_seconds else 1
            overdue = max(0, self.elapsed_seconds - pending.ready_seconds) * animation_speed
            if overdue >= self.duration_seconds:
                continue
            self._create_popup(owner, pending.amount, pending.x, pending.y,
                               pending.offset_x_range, pending.direction)
            self.popups[-1].animation.update(overdue)
        active_owners = {popup.owner for popup in self.popups} | self.pending.keys()
        self._directed_hit_counts = {owner: count for owner, count in self._directed_hit_counts.items()
                                    if owner in active_owners}

    def clear(self, owner: str | None = None):
        if owner is None:
            self.popups.clear()
            self.pending.clear()
            self.elapsed_seconds = 0.0
            self._directed_hit_counts.clear()
        else:
            self.popups = [popup for popup in self.popups if popup.owner != owner]
            self.pending.pop(owner, None)
            self._directed_hit_counts.pop(owner, None)

    @property
    def visuals(self) -> tuple[DamageVisual, ...]:
        visuals = []
        for popup in self.popups:
            elapsed = popup.animation.elapsed_seconds
            # 남은 시간을 같은 펼침 곡선에 넣어 세로→가로 순서로 되감는다.
            phase_seconds = min(elapsed, self.duration_seconds - elapsed)
            width = (smooth_step(phase_seconds / self.width_expand_seconds)
                     if self.width_expand_seconds > 0 else 1.0)
            if phase_seconds < self.width_expand_seconds:
                height = 0.0
            else:
                height = (smooth_step((phase_seconds - self.width_expand_seconds) / self.height_expand_seconds)
                          if self.height_expand_seconds > 0 else 1.0)
            visuals.append(DamageVisual(popup.amount, popup.x, popup.y, 1.0, popup.owner,
                                        width, height, popup.font_scale))
        return tuple(visuals)

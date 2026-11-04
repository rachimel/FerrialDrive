"""이번 피해 숫자의 자릿수 크기·겹침 없는 배치·표시 수명."""

from dataclasses import dataclass
from math import isfinite
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


class DamageNumbers:
    def __init__(self, duration_seconds: float, scatter_x_pixels: float, scatter_y_pixels: float,
                 *, measure_text: Callable[[str], tuple[float, float]],
                 digit_scales=(1.0,), gap_pixels=6,
                 width_expand_seconds: float = 0.10, height_expand_seconds: float = 0.12):
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
        if not callable(measure_text):
            raise ValueError("실제 표시 글꼴의 크기를 측정하는 함수가 필요하다.")
        self.duration_seconds = duration_seconds
        self.width_expand_seconds = width_expand_seconds
        self.height_expand_seconds = height_expand_seconds
        self.scatter_x_pixels = scatter_x_pixels
        self.scatter_y_pixels = scatter_y_pixels
        self.measure_text = measure_text
        self.digit_scales = digit_scales
        self.gap_pixels = gap_pixels
        self.random = Random()
        self.popups: list[DamagePopup] = []

    def add(self, owner: str, amount: int, x: float, y: float, *, offset_x_range=(0.0, 0.0)):
        if type(amount) is not int:
            raise ValueError("피해량은 정수여야 한다.")
        if amount <= 0:
            return
        if not all(isfinite(value) for value in (x, y)):
            raise ValueError("피격 좌표는 유한한 픽셀 값이어야 한다.")
        text = str(amount)
        scale = self.digit_scales[min(len(text), len(self.digit_scales)) - 1]
        width, height = self.measure_text(text)
        if not all(isfinite(value) and value > 0 for value in (width, height)):
            raise ValueError("피해 숫자의 측정 크기는 양수인 유한한 픽셀 값이어야 한다.")
        width, height = width * scale, height * scale
        if (len(offset_x_range) != 2 or not all(isfinite(value) for value in offset_x_range)
                or offset_x_range[0] > offset_x_range[1]):
            raise ValueError("장면 이동 범위는 순서가 맞는 유한한 두 픽셀 값이어야 한다.")
        start, end = offset_x_range
        # 피격 순간 한 번만 배치하고, 수명 중에는 같은 위치를 유지한다.
        x += self.random.uniform(-self.scatter_x_pixels, self.scatter_x_pixels)
        y += self.random.uniform(-self.scatter_y_pixels, self.scatter_y_pixels)
        # 장면 전환 때 플레이어는 고정되고 타겟 숫자는 이동하므로 이동 폭도 예약한다.
        center_offset = (start + end) / 2
        x, y = self._vacant_position(x + center_offset, y, width + end - start, height)
        x -= center_offset
        self.popups.append(DamagePopup(owner, amount, x, y,
                                       ScalarAnimation(0, 1, self.duration_seconds), scale, width, height,
                                       (start, end)))

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

    def update(self, delta_seconds):
        for popup in self.popups:
            popup.animation.update(delta_seconds)
        self.popups = [popup for popup in self.popups if not popup.animation.finished]

    def clear(self, owner: str | None = None):
        if owner is None:
            self.popups.clear()
        else:
            self.popups = [popup for popup in self.popups if popup.owner != owner]

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

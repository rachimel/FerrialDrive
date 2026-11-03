"""피격 위치 주변의 이번 피해 숫자·무작위 배치·표시 수명."""

from dataclasses import dataclass
from math import isfinite
from random import Random

from ..animation import ScalarAnimation, smooth_step


@dataclass(frozen=True)
class DamageVisual:
    amount: int
    x: float
    y: float
    opacity: float
    owner: str = ""
    width_progress: float = 1.0
    height_progress: float = 1.0


@dataclass
class DamagePopup:
    owner: str
    amount: int
    x: float
    y: float
    animation: ScalarAnimation


class DamageNumbers:
    def __init__(self, duration_seconds: float, scatter_x_pixels: float, scatter_y_pixels: float,
                 *, width_expand_seconds: float = 0.10, height_expand_seconds: float = 0.12):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("피해 숫자 표시 시간은 양수인 초 단위 값이어야 한다.")
        if not all(isfinite(value) and value >= 0 for value in (scatter_x_pixels, scatter_y_pixels)):
            raise ValueError("피해 숫자 분산 범위는 0 이상의 유한한 픽셀 값이어야 한다.")
        if not all(isfinite(value) and value >= 0 for value in
                   (width_expand_seconds, height_expand_seconds)):
            raise ValueError("피해 숫자 펼침 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        if 2 * (width_expand_seconds + height_expand_seconds) >= duration_seconds:
            raise ValueError("피해 숫자 등장·퇴장 시간의 합은 전체 표시 시간보다 짧아야 한다.")
        self.duration_seconds = duration_seconds
        self.width_expand_seconds = width_expand_seconds
        self.height_expand_seconds = height_expand_seconds
        self.scatter_x_pixels = scatter_x_pixels
        self.scatter_y_pixels = scatter_y_pixels
        self.random = Random()
        self.popups: list[DamagePopup] = []

    def add(self, owner: str, amount: int, x: float, y: float):
        if amount <= 0:
            return
        # 피격 순간 한 번만 배치하고, 수명 중에는 같은 위치를 유지한다.
        x += self.random.uniform(-self.scatter_x_pixels, self.scatter_x_pixels)
        y += self.random.uniform(-self.scatter_y_pixels, self.scatter_y_pixels)
        self.popups.append(DamagePopup(owner, amount, x, y,
                                       ScalarAnimation(0, 1, self.duration_seconds)))

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
                                        width, height))
        return tuple(visuals)

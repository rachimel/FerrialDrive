"""UI와 렌더러에 의존하지 않는 초 단위 수치 애니메이션."""

from dataclasses import dataclass
from math import isfinite, sin, tau
from typing import Callable


def linear(progress: float) -> float:
    return max(0.0, min(1.0, progress))


def smooth_step(progress: float) -> float:
    progress = max(0.0, min(1.0, progress))
    return progress * progress * (3.0 - 2.0 * progress)


def ease_in_quad(progress: float) -> float:
    progress = max(0.0, min(1.0, progress))
    return progress * progress


def ease_in_out_quint(progress: float) -> float:
    progress = linear(progress)
    if progress < 0.5:
        return 16 * progress ** 5
    return 1 - (-2 * progress + 2) ** 5 / 2


def elastic_in_out(progress: float, period: float = 0.4) -> float:
    """입력 시간은 제한하되 출력의 탄성 범위 초과는 유지한다."""
    if not isfinite(period) or period <= 0:
        raise ValueError("탄성 주기는 양수인 유한한 값이어야 한다.")
    if progress <= 0:
        return 0.0
    if progress >= 1:
        return 1.0
    phase = 2 * progress - 1
    wave = sin((phase - period / 4) * tau / period)
    if phase < 0:
        return -0.5 * 2 ** (10 * phase) * wave
    return 0.5 * 2 ** (-10 * phase) * wave + 1


@dataclass
class ScalarAnimation:
    start_value: float
    end_value: float
    duration_seconds: float
    easing: Callable[[float], float] = smooth_step
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        values = (self.start_value, self.end_value, self.duration_seconds,
                  self.elapsed_seconds)
        if not all(isfinite(value) for value in values):
            raise ValueError("애니메이션 값은 유한한 수여야 한다.")
        if self.duration_seconds < 0 or self.elapsed_seconds < 0:
            raise ValueError("애니메이션 시간은 음수일 수 없다.")

    @property
    def finished(self) -> bool:
        return self.elapsed_seconds >= self.duration_seconds

    @property
    def value(self) -> float:
        if self.finished:
            return self.end_value
        progress = self.elapsed_seconds / self.duration_seconds
        return self.start_value + (self.end_value - self.start_value) * self.easing(progress)

    def update(self, delta_seconds: float) -> float:
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.elapsed_seconds = min(self.duration_seconds,
                                   self.elapsed_seconds + delta_seconds)
        return self.value

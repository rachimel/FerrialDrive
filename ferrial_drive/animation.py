"""UI와 렌더러에 의존하지 않는 초 단위 수치 애니메이션."""

from dataclasses import dataclass
from math import isfinite
from typing import Callable


def smooth_step(progress: float) -> float:
    progress = max(0.0, min(1.0, progress))
    return progress * progress * (3.0 - 2.0 * progress)


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

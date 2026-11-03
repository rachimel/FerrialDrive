"""실제 HP와 분리된 감소 구간의 표시 상태."""

from math import isfinite

from ..animation import ScalarAnimation, ease_in_quad


class HealthTrail:
    def __init__(self, duration_seconds: float, initial_ratio: float):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("HP 감소 효과 시간은 양수인 유한한 초 단위 값이어야 한다.")
        self.duration_seconds = duration_seconds
        self.reset(initial_ratio)

    @staticmethod
    def _validate_ratio(ratio):
        if not isfinite(ratio) or not 0 <= ratio <= 1:
            raise ValueError("HP 비율은 0~1의 유한한 값이어야 한다.")

    def reset(self, ratio: float):
        self._validate_ratio(ratio)
        self.target_ratio = ratio
        self.animation = ScalarAnimation(ratio, ratio, self.duration_seconds,
                                         easing=ease_in_quad, elapsed_seconds=self.duration_seconds)

    def set_ratio(self, ratio: float):
        self._validate_ratio(ratio)
        if ratio == self.target_ratio:
            return
        if ratio > self.target_ratio:
            self.reset(ratio)
            return
        # 추가 피해는 지금 보이는 끝점에서 이어지고 진행 시간만 0으로 돌아간다.
        start_ratio = self.trailing_ratio
        self.target_ratio = ratio
        self.animation = ScalarAnimation(start_ratio, ratio, self.duration_seconds, easing=ease_in_quad)

    def update(self, delta_seconds: float):
        self.animation.update(delta_seconds)

    @property
    def trailing_ratio(self) -> float:
        return self.animation.value

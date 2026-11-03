"""누적 수치의 회전 표시 상태. 원본 수치·렌더러·게임 로직과 독립적이다."""

from dataclasses import dataclass
from math import isfinite

from ..animation import ScalarAnimation, elastic_in_out, smooth_step


@dataclass(frozen=True)
class CounterVisual:
    previous_value: int
    value: int
    elapsed_seconds: float
    duration_seconds: float
    vertical_easing: str = "smooth_step"
    elastic_strength: float = 0.35
    elastic_period: float = 0.4

    def progress_before(self, seconds_ago: float = 0) -> float:
        return smooth_step((self.elapsed_seconds - seconds_ago) / self.duration_seconds)

    @property
    def progress(self) -> float:
        """페이드·블러 전용 진행률. 항상 0~1 범위를 유지한다."""
        return self.progress_before()

    @property
    def vertical_progress(self) -> float:
        """숫자 세로 이동 전용 진행률. 탄성 출력은 제한하지 않는다."""
        if self.vertical_easing == "smooth_step":
            return self.progress
        time_fraction = max(0.0, min(1.0, self.elapsed_seconds / self.duration_seconds))
        elastic = elastic_in_out(time_fraction, self.elastic_period)
        return self.progress + self.elastic_strength * (elastic - self.progress)

    @property
    def moving(self) -> bool:
        return self.previous_value != self.value and self.elapsed_seconds < self.duration_seconds


class CounterVisibility:
    """적중 이벤트가 갱신하는 공통 표시 수명. 카운터 값은 변경하지 않는다."""

    def __init__(self, hold_seconds: float, fade_seconds: float):
        if not isfinite(hold_seconds) or hold_seconds <= 0:
            raise ValueError("카운터 유지 시간은 양수인 유한한 초 단위 값이어야 한다.")
        if not isfinite(fade_seconds) or fade_seconds < 0:
            raise ValueError("카운터 페이드 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.hold_seconds = hold_seconds
        self.fade_seconds = fade_seconds
        self.hide()

    def show(self):
        self.elapsed_seconds = 0.0

    def hide(self):
        self.elapsed_seconds = self.hold_seconds + self.fade_seconds

    def update(self, delta_seconds: float) -> bool:
        """자연스럽게 표시 수명이 끝난 프레임에만 True를 반환한다."""
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        end_seconds = self.hold_seconds + self.fade_seconds
        was_visible = self.elapsed_seconds < end_seconds
        self.elapsed_seconds = min(end_seconds, self.elapsed_seconds + delta_seconds)
        return was_visible and self.elapsed_seconds >= end_seconds

    @property
    def opacity(self) -> float:
        if self.elapsed_seconds < self.hold_seconds:
            return 1.0
        if self.fade_seconds == 0:
            return 0.0
        return 1.0 - smooth_step((self.elapsed_seconds - self.hold_seconds) / self.fade_seconds)


class RollingCounter:
    def __init__(self, duration_seconds: float, initial_value: int = 0, *,
                 vertical_easing: str = "smooth_step", elastic_strength: float = 0.35,
                 elastic_period: float = 0.4):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("카운터 회전 시간은 양수인 초 단위 값이어야 한다.")
        if vertical_easing not in ("smooth_step", "elastic_in_out"):
            raise ValueError("카운터 세로 이동 보간은 smooth_step 또는 elastic_in_out이어야 한다.")
        if not isfinite(elastic_strength) or not 0 <= elastic_strength <= 1:
            raise ValueError("카운터 탄성 혼합 비율은 0~1이어야 한다.")
        if not isfinite(elastic_period) or elastic_period <= 0:
            raise ValueError("카운터 탄성 주기는 양수인 유한한 값이어야 한다.")
        self.duration_seconds = duration_seconds
        self.vertical_easing = vertical_easing
        self.elastic_strength = elastic_strength
        self.elastic_period = elastic_period
        self.reset(initial_value)

    @staticmethod
    def _validate_value(value):
        if not isinstance(value, int) or value < 0:
            raise ValueError("카운터 값은 0 이상의 정수여야 한다.")

    def reset(self, value: int = 0):
        self._validate_value(value)
        self.previous_value = self.value = self.latest_value = value
        self.animation = ScalarAnimation(0, 1, self.duration_seconds,
                                         elapsed_seconds=self.duration_seconds)

    def _begin(self, value):
        self.previous_value, self.value = self.value, value
        self.animation = ScalarAnimation(0, 1, self.duration_seconds)

    def set_value(self, value: int):
        self._validate_value(value)
        if value < self.latest_value:
            self.reset(value)
            return
        self.latest_value = value
        if self.animation.finished and value != self.value:
            self._begin(value)

    def update(self, delta_seconds: float):
        remaining = self.duration_seconds - self.animation.elapsed_seconds
        self.animation.update(delta_seconds)
        if self.animation.finished and self.latest_value != self.value:
            # 진행 중 입력은 최신 합계 하나로 병합하고 남은 프레임 시간을 넘긴다.
            self._begin(self.latest_value)
            self.animation.update(max(0.0, delta_seconds - remaining))

    @property
    def visual(self) -> CounterVisual:
        previous = self.value if self.animation.finished else self.previous_value
        return CounterVisual(previous, self.value, self.animation.elapsed_seconds,
                             self.duration_seconds, self.vertical_easing,
                             self.elastic_strength, self.elastic_period)

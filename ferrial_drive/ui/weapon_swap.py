"""실제 무기 선택과 분리된 무장 패널의 위치·크기 전환 상태."""

from math import isfinite
from dataclasses import dataclass

from ..animation import ScalarAnimation, smooth_step


def diamond_offset(kind, weight, half_width, edge_inset=0, orbit_direction=-1):
    """두 패널이 마름모의 반대쪽 변을 따라 자리 교환하도록 좌우로 분리한다."""
    peak = 1 - abs(2 * max(0.0, min(1.0, weight)) - 1)
    side = -1 if kind == "melee" else 1
    side *= -orbit_direction
    return peak * (side * half_width - edge_inset)


@dataclass(frozen=True)
class WeaponSwapVisual:
    start_weight: float
    end_weight: float
    elapsed_seconds: float
    duration_seconds: float

    @property
    def moving(self):
        return self.start_weight != self.end_weight and self.elapsed_seconds < self.duration_seconds

    @property
    def orbit_direction(self):
        return -1 if self.end_weight < self.start_weight else 1

    def weight_before(self, seconds_ago=0):
        if self.duration_seconds == 0:
            return self.end_weight
        progress = smooth_step((self.elapsed_seconds - seconds_ago) / self.duration_seconds)
        return self.start_weight + (self.end_weight - self.start_weight) * progress

    @property
    def velocity(self):
        """가중치의 초당 순간 변화량. 시작·끝에서 부드럽게 0이 된다."""
        if not self.moving:
            return 0.0
        progress = max(0, min(1, self.elapsed_seconds / self.duration_seconds))
        return (self.end_weight - self.start_weight) * 6 * progress * (1 - progress) / self.duration_seconds


class WeaponSwap:
    def __init__(self, initial_kind, duration_seconds):
        if not isfinite(duration_seconds) or duration_seconds < 0:
            raise ValueError("무장 전환 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.duration_seconds = duration_seconds
        self.reset(initial_kind)

    @staticmethod
    def _value(kind):
        if kind not in ("melee", "ranged"):
            raise ValueError("무기 종류는 melee 또는 ranged여야 한다.")
        return 1.0 if kind == "ranged" else 0.0

    @property
    def ranged_weight(self):
        return self.animation.value

    @property
    def visual(self):
        animation = self.animation
        return WeaponSwapVisual(animation.start_value, animation.end_value,
                                animation.elapsed_seconds, animation.duration_seconds)

    def reset(self, kind):
        self.latest_kind = kind
        value = self._value(kind)
        self.animation = ScalarAnimation(value, value, 0)

    def request(self, kind):
        value = self._value(kind)
        self.latest_kind = kind
        if self.animation.finished and self.animation.end_value != value:
            start = self.ranged_weight
            self.animation = ScalarAnimation(start, value, self.duration_seconds * abs(value - start))

    def update(self, delta_seconds):
        remaining = self.animation.duration_seconds - self.animation.elapsed_seconds
        self.animation.update(delta_seconds)
        target = self._value(self.latest_kind)
        if self.animation.finished and self.animation.end_value != target:
            self.animation = ScalarAnimation(self.ranged_weight, target, self.duration_seconds)
            self.animation.update(max(0.0, delta_seconds - remaining))

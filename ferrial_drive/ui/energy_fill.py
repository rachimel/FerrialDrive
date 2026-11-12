"""게임 수치와 분리된 누적 에너지 채움 표시. 증가만 짧게 보간한다."""

from math import isfinite

from ferrial_drive.animation import ScalarAnimation
from .energy import EnergyCharge


class EnergyFillMotion:
    def __init__(self, duration_seconds=0.12):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError('에너지 채움 시간은 양수인 유한한 초 단위 값이어야 한다.')
        self.duration_seconds = duration_seconds
        self.reset(0)

    def reset(self, total):
        EnergyCharge(total)
        self.animation = ScalarAnimation(total, total, 0)

    def request(self, total):
        EnergyCharge(total)
        if total < self.animation.end_value:
            self.reset(total)
        elif total != self.animation.end_value:
            remaining = (self.duration_seconds if self.animation.finished else
                         self.animation.duration_seconds - self.animation.elapsed_seconds)
            # 연속 도착은 최초 증가의 남은 시간 안에 따라잡는다.
            self.animation = ScalarAnimation(self.animation.value, total, remaining)

    def update(self, delta_seconds):
        self.animation.update(delta_seconds)

    @property
    def visual(self):
        return EnergyCharge(self.animation.value)

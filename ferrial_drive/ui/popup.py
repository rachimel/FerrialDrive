"""팝업 공통 등장 표시값. 시간은 호출자가 초 단위로 갱신한다."""

from math import isfinite

from ferrial_drive.animation import ScalarAnimation


class PopupMotion:
    def __init__(self, duration_seconds=.16, initial_scale=.97):
        if (not isfinite(duration_seconds) or duration_seconds <= 0
                or not isfinite(initial_scale) or not 0 < initial_scale <= 1):
            raise ValueError("팝업 등장 시간은 양수, 시작 배율은 0 초과 1 이하여야 한다.")
        self.duration_seconds = duration_seconds
        self.initial_scale = initial_scale
        self.reset()

    def reset(self):
        self.animation = ScalarAnimation(0, 0, 0)

    def open(self):
        self.animation = ScalarAnimation(0, 1, self.duration_seconds)

    def update(self, delta_seconds):
        self.animation.update(delta_seconds)

    @property
    def entering(self):
        return not self.animation.finished

    @property
    def opacity(self):
        return self.animation.value

    @property
    def scale(self):
        return self.initial_scale + (1 - self.initial_scale) * self.opacity

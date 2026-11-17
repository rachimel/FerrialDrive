"""HIT·DAMAGE의 오른쪽부터 나타나고 사라지는 표시 수명."""

from dataclasses import dataclass
from math import isfinite

from ferrial_drive.animation import smooth_step


@dataclass(frozen=True)
class CounterMotionVisual:
    fraction: float = 1
    entering: bool = False
    exiting: bool = False
    offset_x: float = 0
    label_spacing_pixels: float = 5


class CounterMotion:
    def __init__(self, enter_seconds=0.24, hold_seconds=2.5, exit_seconds=0.28,
                 label_spacing_pixels=5, slide_pixels=54):
        if (not all(isfinite(v) and v > 0 for v in (enter_seconds, hold_seconds, exit_seconds))
                or not all(isfinite(v) and v >= 0 for v in (label_spacing_pixels, slide_pixels))):
            raise ValueError("카운터 표시 시간과 간격 오류")
        self.enter_seconds, self.hold_seconds, self.exit_seconds = enter_seconds, hold_seconds, exit_seconds
        self.label_spacing_pixels, self.slide_pixels = label_spacing_pixels, slide_pixels
        self.reset()

    def reset(self, value=0):
        self.value = value
        self.age = self.enter_seconds if value else self.enter_seconds + self.hold_seconds + self.exit_seconds

    def update(self, value, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("카운터 갱신 시간 오류")
        if value > self.value:
            if self.age >= self.enter_seconds + self.hold_seconds:
                self.age = 0
            else:
                self.age = min(self.age, self.enter_seconds)
        elif value < self.value:
            self.reset(value)
        self.value = value
        self.age += delta_seconds

    @property
    def visual(self):
        if self.age < self.enter_seconds:
            amount = smooth_step(self.age / self.enter_seconds)
            return CounterMotionVisual(amount, True, False, self.slide_pixels * (1 - amount),
                                       self.label_spacing_pixels * amount)
        elapsed = self.age - self.enter_seconds - self.hold_seconds
        if elapsed >= 0:
            amount = 1 - smooth_step(elapsed / self.exit_seconds)
            return CounterMotionVisual(amount, False, True, 0, self.label_spacing_pixels)
        return CounterMotionVisual(label_spacing_pixels=self.label_spacing_pixels)

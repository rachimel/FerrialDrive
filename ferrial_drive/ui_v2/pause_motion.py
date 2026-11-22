"""일시정지 호버의 이동·호흡 표시값. 그리기와 입력 판정을 변경하지 않는다."""

from dataclasses import dataclass
from math import cos, isfinite, tau

from ferrial_drive.animation import ScalarAnimation


@dataclass(frozen=True)
class PauseButtonVisual:
    hover_ratio: float = 0
    offset_pixels: float = 0
    light_opacity: float = 0


class PauseHoverMotion:
    def __init__(self, offset_pixels=8, transition_seconds=.14, breathing_seconds=1.4, minimum_light=.35):
        if (not all(map(isfinite, (offset_pixels, transition_seconds, breathing_seconds, minimum_light)))
                or offset_pixels < 0 or min(transition_seconds, breathing_seconds) <= 0
                or not 0 <= minimum_light <= 1):
            raise ValueError("호버 이동은 0 이상, 시간은 양수, 최소 밝기는 0~1이어야 한다.")
        self.offset_pixels = offset_pixels
        self.transition_seconds = transition_seconds
        self.breathing_seconds = breathing_seconds
        self.minimum_light = minimum_light
        self.reset()

    def reset(self):
        self.tracks = {}
        self.elapsed_seconds = {}

    def update(self, delta_seconds, hovered_id, buttons, *, active):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("호버 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        if not active:
            self.reset()
            return
        ids = {button.button_id for button in buttons}
        self.tracks = {key: value for key, value in self.tracks.items() if key in ids}
        self.elapsed_seconds = {key: value for key, value in self.elapsed_seconds.items() if key in ids}
        for button in buttons:
            key = button.button_id
            target = float(button.enabled and key == hovered_id)
            track = self.tracks.setdefault(key, ScalarAnimation(0, 0, 0))
            if track.end_value != target:
                track = self.tracks[key] = ScalarAnimation(track.value, target, self.transition_seconds)
            track.update(delta_seconds)
            if target:
                self.elapsed_seconds[key] = (self.elapsed_seconds.get(key, 0) + delta_seconds) % self.breathing_seconds
            elif track.value == 0:
                self.elapsed_seconds[key] = 0

    @property
    def visuals(self):
        result = {}
        for key, track in self.tracks.items():
            phase = self.elapsed_seconds.get(key, 0) / self.breathing_seconds
            pulse = (1 + cos(tau * phase)) / 2
            light = track.value * (self.minimum_light + (1 - self.minimum_light) * pulse)
            result[key] = PauseButtonVisual(track.value, -self.offset_pixels * track.value, light)
        return result

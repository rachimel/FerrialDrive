"""타이틀 배경 격자의 스크롤과 셀 발광을 같은 좌표계로 표시한다."""

from dataclasses import dataclass
from math import ceil, floor
from random import Random

from ferrial_drive.animation import smooth_step
from ferrial_drive.ui.components import Rect

PULSE_DURATION_SECONDS = (2.8, 3.8)
PULSE_INTERVAL_SECONDS = (1.15, 1.65)
PULSE_RISE_END = .36
PULSE_SHRINK_START = .45

@dataclass
class CellPulse:
    column: int
    row: int
    born: float
    duration: float


class TitleGrid:
    def __init__(self):
        self.rng = Random()
        self.next_pulse = 0.0
        self.pulses = []

    def draw(self, r, width, height, seconds):
        cell = height / 19
        dx, dy = seconds * .23, seconds * .10
        cols = width / cell
        if seconds >= self.next_pulse:
            self.pulses.append(CellPulse(floor(self.rng.uniform(.48, .94) * cols - dx),
                                         floor(self.rng.uniform(1, 18) - dy), seconds,
                                         self.rng.uniform(*PULSE_DURATION_SECONDS)))
            self.next_pulse = seconds + self.rng.uniform(*PULSE_INTERVAL_SECONDS)
        self.pulses[:] = [p for p in self.pulses if seconds < p.born + p.duration]

        ink = "#91B6C7"
        stroke = max(1, height / 850)
        cross_stroke = 2 * stroke
        fade_left, fade_right = width * .30, width * .65
        def visibility(x):
            return smooth_step((x - fade_left) / (fade_right - fade_left))

        for col in range(floor(fade_left / cell - dx), ceil(cols - dx)):
            x = (col + dx) * cell
            alpha = visibility(x)
            r.rect(Rect(x, 0, stroke, height), ink, alpha * (.24 if col % 4 == 0 else .105))
            if col % 8 == 0:
                for row in range(ceil(-dy / 8) * 8, ceil(19 - dy), 8):
                    y = (row + dy) * cell
                    cx, cy = x + stroke / 2, y + stroke / 2
                    r.rect(Rect(cx - cell * .085, cy - cross_stroke / 2, cell * .17, cross_stroke), ink, .60 * alpha)
                    r.rect(Rect(cx - cross_stroke / 2, cy - cell * .085, cross_stroke, cell * .17), ink, .60 * alpha)
        for row in range(floor(-dy), ceil(19 - dy)):
            y = (row + dy) * cell
            alpha = .24 if row % 4 == 0 else .105
            r.rect(Rect(fade_right, y, width - fade_right, stroke), ink, alpha)
            points = ((fade_left, y), (fade_right, y), (fade_right, y + stroke), (fade_left, y + stroke))
            clear, bright = r.rgba(ink, 0), r.rgba(ink, alpha)
            r._geometry_polygon(points, bright, colors=(clear, bright, bright, clear))
        for pulse in self.pulses:
            phase = (seconds - pulse.born) / pulse.duration
            shrink = smooth_step((phase - PULSE_SHRINK_START) / (1 - PULSE_SHRINK_START))
            size = cell * .94 * (1 - shrink)
            x, y = (pulse.column + dx + .5) * cell, (pulse.row + dy + .5) * cell
            alpha = .35 * smooth_step(phase / PULSE_RISE_END) * (1 - shrink) * visibility(x)
            r.rect(Rect(x - size / 2, y - size / 2, size, size), "#8AC7DC", alpha)

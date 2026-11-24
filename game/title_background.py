"""본편 타이틀의 실루엣·입자 흐름·호버 파동을 그린다."""

from math import exp, sin, tau
from pathlib import Path
from random import Random

from ferrial_drive.ui.components import Rect
from .splash import smooth


OUTLINE = Path(__file__).resolve().parents[1] / "data/runtime/images/ui/title_mech_outline.png"


class TitleBackground:
    def __init__(self):
        self.elapsed = self.travel = self.energy = 0.0
        self.wave = 1.0
        self.hovered = None
        self.has_outline = OUTLINE.is_file()
        rng = Random(37)
        self.particles = [(rng.random(), rng.random(), rng.uniform(.45, 1.5), rng.random() * tau)
                          for _ in range(94)]

    def update(self, dt, hovered):
        if hovered and hovered != self.hovered:
            self.wave = 0.0
        self.hovered = hovered
        self.wave = min(1, self.wave + dt / .62)
        self.elapsed += dt
        target = max(float(bool(hovered)), 1 - smooth(self.elapsed / 1.15))
        self.energy += (target - self.energy) * (1 - exp(-9 * dt))
        self.travel += dt * (.035 + .11 * self.energy)

    def draw(self, view, width, height):
        r = view.renderer
        r.clear("#222429")
        if self.has_outline:
            r.image(OUTLINE, Rect(width * .39, height * .10, width * .56, height * .80), .87)
        with view.draw_batch():
            for i, (x, y, speed, phase) in enumerate(self.particles):
                px = (x + self.travel * speed) % 1
                py = (y - self.travel * speed * .42 + .012 * sin(phase + self.travel * 9)) % 1
                alpha = (.20 + .44 * self.energy) * speed
                size = max(1, height * .0015 * speed)
                color = "#B5EBF4" if i % 4 == 0 else "#D8E0E7"
                r.rect(Rect(px * width, py * height, size * (1.4 + self.energy * 4), size), color, alpha)
            if self.wave < 1:
                spread = smooth(self.wave) * height * .53
                for direction in (-1, 1):
                    y = height / 2 + direction * spread
                    for thickness, alpha in ((.009, .045), (.003, .12), (.0012, .38)):
                        h = max(1, height * thickness)
                        r.rect(Rect(0, y - h / 2, width, h), "#FFFFFF", alpha * (1 - self.wave))

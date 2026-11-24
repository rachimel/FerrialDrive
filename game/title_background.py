"""본편 타이틀의 하단 입자·메뉴 음영·호버 파동을 그린다."""

from ctypes import c_char_p
from math import exp, hypot, sin, tau
from random import Random

from ferrial_drive.ui.components import Rect
from .splash import smooth


class TitleBackground:
    def __init__(self):
        self.elapsed = self.travel = self.energy = 0.0
        self.wave = 1.0
        self.hovered = None
        self.shade = None
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
        self.travel += dt * (.085 + .19 * self.energy)

    def _prepare_shade(self, p):
        # 정규화된 화면 좌표로 한 번 만들고 창 크기에 맞춰 선형 보간한다.
        width, height = 160, 96
        pixels = bytearray(width * height * 4)
        for row in range(height):
            y = row / (height - 1)
            for col in range(width):
                x = col / (width - 1)
                bar = .67 * (1 - smooth((x - .13) / .35))
                radius = hypot((x - .5) * 2, (y - .5) * 2)
                vignette = .58 * smooth((radius - .36) / 1.05)
                pixels[(row * width + col) * 4 + 3] = round(255 * (bar + (1 - bar) * vignette))
        texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_STATIC, width, height)
        if not texture:
            raise RuntimeError("타이틀 음영 텍스처 생성 실패")
        if (p.SDL_UpdateTexture(texture, None, c_char_p(bytes(pixels)), width * 4)
                or p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_BLEND)
                or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear)):
            p.SDL_DestroyTexture(texture)
            raise RuntimeError("타이틀 음영 텍스처 준비 실패")
        self.shade = texture

    def close(self, pico):
        if self.shade:
            pico.SDL_DestroyTexture(self.shade)
            self.shade = None

    def draw(self, view, width, height):
        r = view.renderer
        r.clear("#222429")
        with view.draw_batch():
            for i, (x, delay, speed, phase) in enumerate(self.particles):
                progress = self.travel * speed - delay * .36
                if progress < 0:
                    continue
                rise = progress % 1
                px = x + .025 * (sin(phase + rise * 5) - sin(phase)) + .04 * rise
                py = 1 - rise
                alpha = (.32 + .44 * self.energy) * speed * smooth(rise / .035) * smooth((1 - rise) / .25)
                size = max(1, height * .0015 * speed)
                color = "#B5EBF4" if i % 4 == 0 else "#D8E0E7"
                r.rect(Rect(px * width, py * height, size, size * (1.8 + self.energy * 4)), color, alpha)
            if self.wave < 1:
                spread = smooth(self.wave) * height * .53
                for direction in (-1, 1):
                    y = height / 2 + direction * spread
                    for thickness, alpha in ((.009, .045), (.003, .12), (.0012, .38)):
                        h = max(1, height * thickness)
                        r.rect(Rect(0, y - h / 2, width, h), "#FFFFFF", alpha * (1 - self.wave))
        p = r.pico
        if self.shade is None:
            self._prepare_shade(p)
        p.SDL_RenderCopy(p.renderer, self.shade, None, None)

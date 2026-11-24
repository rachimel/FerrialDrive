"""본편 타이틀의 하단 입자·메뉴 음영·호버 파동을 그린다."""

from ctypes import c_char_p
from dataclasses import dataclass
from math import cos, exp, hypot, sin, tau
from random import Random

from ferrial_drive.animation import ease_in_quad
from ferrial_drive.ui.components import Rect
from .splash import smooth


@dataclass
class HoverSpark:
    x: float
    speed: float
    drift: float
    phase: float
    born: float
    fade_at: float


def draw_drifting_spark(renderer, width, height, origin, rise, launch, wind, curl,
                        size, length, color, alpha):
    # 세로 속도는 서서히 줄고, 가로 속도는 발사 방향에서 바람 방향으로 이어진다.
    bend = rise * (1 - rise)
    drift = launch * rise + (wind - launch) * rise * rise / 2
    x = width * (origin + drift + curl * bend * rise)
    y = height * (1 - rise * (1.24 - .24 * rise))
    vx = width * (launch + (wind - launch) * rise + curl * rise * (2 - 3 * rise))
    vy = -height * (1.24 - .48 * rise)
    step = size / hypot(vx, vy)
    dx, dy = vx * step, vy * step
    tx, ty = x - dx * length, y - dy * length
    points = ((x - dy / 2, y + dx / 2), (x + dy / 2, y - dx / 2),
              (tx + dy / 3, ty - dx / 3), (tx - dy / 3, ty + dx / 3))
    renderer._geometry_polygon(points, renderer.rgba(color, alpha))


class TitleBackground:
    def __init__(self):
        self.elapsed = self.travel = self.energy = 0.0
        self.wave = 1.0
        self.hovered = None
        self.bar_pulse = 1.0
        self.bar_button = None
        self.shade = None
        rng = Random(37)
        self.particles = [(rng.random(), rng.random(), rng.uniform(.45, 1.5), rng.random() * tau)
                          for _ in range(94)]
        self.rng = rng
        self.sparks = []
        self.spawn_credit = 0.0

    def update(self, dt, hovered):
        if self.hovered and not hovered:
            for spark in self.sparks:
                spark.fade_at = min(spark.fade_at, self.elapsed)
            self.spawn_credit = 0.0
        if hovered and hovered != self.hovered:
            self.wave = 0.0
            self.bar_button = hovered
            self.bar_pulse = 0.0
        self.hovered = hovered
        self.wave = min(1, self.wave + dt / .46)
        self.bar_pulse = min(1, self.bar_pulse + dt / .40)
        self.elapsed += dt
        target = max(float(bool(hovered)), 1 - smooth(self.elapsed / 1.15))
        self.energy += (target - self.energy) * (1 - exp(-9 * dt))
        self.travel += dt * (.085 + .19 * self.energy)
        self.sparks[:] = [spark for spark in self.sparks if self.elapsed < spark.fade_at + .9]
        if hovered:
            self.spawn_credit += dt * 30
            count = int(self.spawn_credit)
            self.spawn_credit -= count
            for _ in range(count):
                self.sparks.append(HoverSpark(
                    self.rng.random(), self.rng.uniform(.21, .34), self.rng.uniform(-.10, .10),
                    self.rng.random() * tau, self.elapsed, self.elapsed + self.rng.uniform(1.2, 2.0)))

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
                vignette = .44 * smooth((radius - .36) / 1.05)
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
        scan = view.style["panel_scanlines"]
        r.clear("#222429")
        with view.draw_batch():
            surface = ((0, 0), (width, 0), (width, height), (0, height))
            for i, (x, delay, speed, phase) in enumerate(self.particles):
                progress = self.travel * speed - delay * .36
                if progress < 0:
                    continue
                rise = progress % 1
                wind = .20 * sin(tau * x + .8 * int(progress))
                alpha = (.32 + .44 * self.energy) * speed * smooth(rise / .035) * smooth((1 - rise) / .25)
                size = max(1, height * .0015 * speed)
                color = "#B5EBF4" if i % 4 == 0 else "#D8E0E7"
                draw_drifting_spark(r, width, height, x, rise, .08 * cos(phase), wind,
                                    .30 * sin(phase), size, 1.8 + self.energy * 4, color, alpha)
            for spark in self.sparks:
                age = self.elapsed - spark.born
                wind = .42 * sin(tau * spark.x + .48 * spark.born)
                alpha = smooth(age / .09) * (1 - smooth((self.elapsed - spark.fade_at) / .9))
                size = max(1, height * .0018)
                draw_drifting_spark(r, width, height, spark.x, age * spark.speed,
                                    spark.drift / spark.speed, wind, .55 * sin(spark.phase),
                                    size, 3.4, "#C3EDF6", alpha * .76)
            r.scanline_layer(surface, "#000000", .22, scan["spacing_pixels"], scan["thickness_pixels"], 0)
            if self.wave < 1:
                spread = smooth(self.wave) * height * .53
                (_, sy), (_, vy, _, _), _, _ = r.draw_transform()
                band_height = max(2, round(height * sy * .009))
                for direction in (-1, 1):
                    top = (height / 2 + direction * spread + vy) * sy - band_height / 2
                    r.scanline_layer(surface, "#FFFFFF", .34 * (1 - self.wave),
                                     scan["spacing_pixels"], scan["thickness_pixels"], 0,
                                     bright_band=(top, band_height))
        if self.bar_pulse < 1:
            button = next((b for b in view.config.buttons["menu"] if b.button_id == self.bar_button), None)
            if button:
                box = button.rect
                y = box.y + box.height / 2
                reach = box.width * (0.12 + .96 * smooth(self.bar_pulse))
                strength = round(52 * sin(self.bar_pulse * tau / 2))
                left = box.x - box.height * .65
                top, bottom = y - box.height * .44, y + box.height * .44
                points = ((left, top), (left + reach, top), (left + reach, bottom), (left, bottom))
                color = (175, 199, 213, strength)
                clear = (*color[:3], 0)
                with view.draw_batch():
                    r._geometry_polygon(points, color, colors=(color, clear, clear, color))
                    r.scanline_layer(points, "#DBEAF1", strength / 360,
                                     scan["spacing_pixels"], scan["thickness_pixels"],
                                     round(self.bar_pulse * scan["spacing_pixels"]))
        p = r.pico
        if self.shade is None:
            self._prepare_shade(p)
        p.SDL_RenderCopy(p.renderer, self.shade, None, None)

    def draw_overlay(self, view, width, height):
        r = view.renderer
        with view.draw_batch():
            opening = ease_in_quad(self.elapsed / .52)
            if opening < 1:
                edge = height * .5 * (1 - opening)
                r.rect(Rect(0, 0, width, edge), "#000000")
                r.rect(Rect(0, height - edge, width, edge), "#000000")
                for y in (edge, height - edge):
                    r.rect(Rect(0, y, width, max(1, height / 540)), "#C3EDF6", .35 * (1 - opening))

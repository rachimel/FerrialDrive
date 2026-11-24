"""한국공학대학교와 제작자 이름을 표시하는 본편 시작 화면."""

from ctypes import byref
from math import cos, pi, sin
from pathlib import Path
from time import perf_counter, sleep

from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.loading import LoadingCancelled
from ferrial_drive.ui.pico_renderer import PicoRenderer


DATA = Path(__file__).resolve().parents[1] / "data"
# 한국공학대학교 공식 홈페이지의 투명 흰색 시그니처.
# https://www.tukorea.ac.kr/sites/tukorea/images/common/logo_w.png
LOGO = DATA / "runtime/images/ui/tukorea_white.png"
FONT = DATA / "fonts/SUITE-otf/SUITE-Bold.otf"
LOGO_HOLD_SECONDS = 0.55
TURN_SECONDS = 1.15
FINAL_HOLD_SECONDS = 0.65


def smooth(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


class GameSplash:
    def __init__(self, pico, window_size):
        self.pico = pico
        self.width, self.height = window_size
        self.scale = min(self.width / 960, self.height / 540)
        self.renderer = PicoRenderer({"name": FONT}, {"name": max(1, round(34 * self.scale))})
        self.name_width, self.name_height = self.renderer.text_size("Rachimel", "name")
        self.first_present = None

    def poll(self):
        event = self.pico.SDL_Event()
        while self.pico.SDL_PollEvent(byref(event)):
            if event.type == self.pico.SDL_QUIT:
                raise LoadingCancelled()
            if (event.type == self.pico.SDL_WINDOWEVENT
                    and event.window.event == self.pico.SDL_WINDOWEVENT_SIZE_CHANGED):
                native = getattr(self.pico, "fdrive_native_gl", None)
                if native:
                    native.resize_window()

    def draw(self, phase):
        r, s = self.renderer, self.scale
        cy = self.height / 2
        left = (self.width - 263 * s - self.name_width) / 2
        r.clear("#000000")
        if LOGO.is_file():
            r.image(LOGO, Rect(left, cy - 21.5 * s, 195 * s, 43 * s))
        else:
            r.text("한국공학대학교", left, cy - self.name_height / 2, "name", "#FFFFFF")
        turn = smooth(phase)
        cx = left + 229 * s
        for angle in (turn * pi / 4, turn * pi / 4 + pi / 2):
            dx, dy = cos(angle), sin(angle)
            thickness = max(1, round(2 * s))
            for i in range(thickness):
                offset = i - (thickness - 1) / 2
                x, y = cx - dy * offset, cy + dx * offset
                r.line(x - dx * 9 * s, y - dy * 9 * s,
                       x + dx * 9 * s, y + dy * 9 * s, "#FFFFFF", turn)
        r.text("Rachimel", left + 263 * s, cy - self.name_height / 2,
               "name", "#FFFFFF", smooth((phase - 0.25) / 0.75))

    def show(self, progress, label, *, before_present=None):
        self.poll()
        if self.first_present is None:
            self.draw(0)
            self.pico.SDL_RenderPresent(self.pico.renderer)
            self.first_present = perf_counter()
        if progress < 1:
            return
        start = max(perf_counter(), self.first_present + LOGO_HOLD_SECONDS)
        while True:
            self.poll()
            elapsed = perf_counter() - start
            self.draw(elapsed / TURN_SECONDS)
            done = elapsed >= TURN_SECONDS + FINAL_HOLD_SECONDS
            if done and before_present:
                before_present()
            self.pico.SDL_RenderPresent(self.pico.renderer)
            if done:
                return
            sleep(1 / 60)

    def close(self):
        self.renderer.close()

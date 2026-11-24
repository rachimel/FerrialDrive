"""한국공학대학교와 제작자 이름을 표시하는 본편 시작 화면."""

from ctypes import byref
from math import cos, pi, sin
from pathlib import Path
from time import perf_counter, sleep

from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.loading import LoadingCancelled
from ferrial_drive.ui.pico_renderer import PicoRenderer


DATA = Path(__file__).resolve().parents[1] / "data"
# 공식 벡터의 한·영문 가로 시그니처에서 만든 투명 PNG.
# https://www.tukorea.ac.kr/sites/tukorea/files/UI/signature.ai
LOGO = DATA / "runtime/images/ui/tukorea_white_hd.png"
FONT = DATA / "fonts/SUITE-otf/SUITE-Regular.otf"
LOGO_HOLD_SECONDS = 0.55
SLIDE_SECONDS = 0.70
REVEAL_START_SECONDS = 0.43
TURN_SECONDS = 0.28
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
        self.has_logo = LOGO.is_file()
        self.logo_width = (240 * self.scale if self.has_logo else
                           self.renderer.text_size("한국공학대학교", "name")[0])
        self.name_height = self.renderer.text_size("Rachimel", "name")[1]
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

    def draw(self, elapsed_seconds):
        r, s = self.renderer, self.scale
        cx, cy = self.width / 2, self.height / 2
        slide = smooth(elapsed_seconds / SLIDE_SECONDS)
        gap = 34 * s
        left = cx - self.logo_width / 2 - slide * (self.logo_width / 2 + gap)
        r.clear("#000000")
        if self.has_logo:
            height = self.logo_width * 312 / 1472
            r.image(LOGO, Rect(left, cy - height / 2, self.logo_width, height))
        else:
            r.text("한국공학대학교", left, cy - self.name_height / 2, "name", "#FFFFFF")
        turn = smooth((elapsed_seconds - REVEAL_START_SECONDS) / TURN_SECONDS)
        if turn == 0:
            return
        for angle in (turn * pi / 4, turn * pi / 4 + pi / 2):
            dx, dy = cos(angle), sin(angle)
            thickness = max(1, round(2 * s))
            for i in range(thickness):
                offset = i - (thickness - 1) / 2
                x, y = cx - dy * offset, cy + dx * offset
                r.line(x - dx * 9 * s, y - dy * 9 * s,
                       x + dx * 9 * s, y + dy * 9 * s, "#FFFFFF", turn)
        r.text("Rachimel", cx + gap, cy - self.name_height / 2, "name", "#FFFFFF", turn)

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
            self.draw(elapsed)
            done = elapsed >= max(SLIDE_SECONDS, REVEAL_START_SECONDS + TURN_SECONDS) + FINAL_HOLD_SECONDS
            if done and before_present:
                before_present()
            self.pico.SDL_RenderPresent(self.pico.renderer)
            if done:
                return
            sleep(1 / 60)

    def close(self):
        self.renderer.close()

"""한국공학대학교와 제작자 이름을 표시하는 본편 시작 화면."""

from ctypes import byref, c_char_p
from math import cos, pi, sin
from pathlib import Path
from time import perf_counter, sleep

from PIL import Image

from ferrial_drive.ui.loading import LoadingCancelled
from ferrial_drive.ui.pico_renderer import PicoRenderer


DATA = Path(__file__).resolve().parents[1] / "data"
# 공식 벡터의 한·영문 가로 시그니처에서 만든 투명 PNG.
# https://www.tukorea.ac.kr/sites/tukorea/files/UI/signature.ai
LOGO = DATA / "runtime/images/ui/tukorea_white_hd.png"
FONT = DATA / "fonts/SUITE-otf/SUITE-Regular.otf"
LOGO_HOLD_SECONDS = 0.15
SLIDE_SECONDS = 0.50
REVEAL_START_SECONDS = 0.16
TURN_SECONDS = 0.28
FINAL_HOLD_SECONDS = 0.10
FADE_OUT_SECONDS = 0.22
# 960×540 캡처에서 측정한 기존 좌우 빈칸 27px와 69px의 평균.
SIGNATURE_GAP = 48


def smooth(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


class GameSplash:
    def __init__(self, pico, window_size):
        self.pico = pico
        self.width, self.height = window_size
        self.scale = min(self.width / 960, self.height / 540)
        self.renderer = PicoRenderer({"name": FONT}, {"name": max(1, round(34 * self.scale))})
        self.logo_texture = None
        self.name_width, self.name_height = self.renderer.text_size("Rachimel", "name")
        if LOGO.is_file():
            try:
                self._prepare_logo()
            except Exception:
                self.close()
                raise
        else:
            self.logo_width = self.renderer.text_size("한국공학대학교", "name")[0]
        self.first_present = None

    def _prepare_logo(self):
        p = self.pico
        with Image.open(LOGO) as source:
            self.logo_width = max(1, round(240 * self.scale))
            self.logo_height = max(1, round(self.logo_width * source.height / source.width))
            size = (self.logo_width, self.logo_height)
            alpha = source.getchannel("A").resize(size, Image.Resampling.LANCZOS)
        image = Image.new("RGBA", size, "white")
        image.putalpha(alpha)
        self.logo_texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32,
                                                p.SDL_TEXTUREACCESS_STATIC, *size)
        if not self.logo_texture:
            raise RuntimeError("스플래시 로고 텍스처를 만들 수 없다.")
        if (p.SDL_UpdateTexture(self.logo_texture, None, c_char_p(image.tobytes()), self.logo_width * 4)
                or p.SDL_SetTextureBlendMode(self.logo_texture, p.SDL_BLENDMODE_BLEND)):
            raise RuntimeError("스플래시 로고를 업로드할 수 없다.")

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
        # ×의 반폭 7px와 SUITE R의 왼쪽 글리프 여백 2px를 반영한다.
        gap = round((SIGNATURE_GAP + 7) * s)
        name_gap = gap - round(2 * s)
        opacity = 1 - smooth((elapsed_seconds - SLIDE_SECONDS - FINAL_HOLD_SECONDS) / FADE_OUT_SECONDS)
        left = cx - self.logo_width / 2 - slide * (self.logo_width / 2 + gap)
        r.clear("#000000")
        if self.logo_texture:
            self.pico.SDL_SetTextureAlphaMod(self.logo_texture, round(255 * opacity))
            target = self.pico.SDL_Rect(round(left), round(cy - self.logo_height / 2),
                                        self.logo_width, self.logo_height)
            self.pico.SDL_RenderCopy(self.pico.renderer, self.logo_texture, None, byref(target))
        else:
            r.text("한국공학대학교", left, cy - self.name_height / 2, "name", "#FFFFFF", opacity)
        turn = smooth((elapsed_seconds - REVEAL_START_SECONDS) / TURN_SECONDS)
        name_left = cx - self.name_width / 2 + slide * (self.name_width / 2 + name_gap)
        r.text("Rachimel", name_left, cy - self.name_height / 2, "name", "#FFFFFF", slide * slide * opacity)
        if turn == 0:
            return
        for angle in (turn * pi / 4, turn * pi / 4 + pi / 2):
            dx, dy = cos(angle), sin(angle)
            thickness = max(1, round(2 * s))
            for i in range(thickness):
                offset = i - (thickness - 1) / 2
                x, y = cx - dy * offset, cy + dx * offset
                r.line(x - dx * 9 * s, y - dy * 9 * s,
                       x + dx * 9 * s, y + dy * 9 * s, "#FFFFFF", turn * opacity)

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
            done = elapsed >= SLIDE_SECONDS + FINAL_HOLD_SECONDS + FADE_OUT_SECONDS
            if done and before_present:
                before_present()
            self.pico.SDL_RenderPresent(self.pico.renderer)
            if done:
                return
            sleep(1 / 60)

    def close(self):
        if self.logo_texture:
            self.pico.SDL_DestroyTexture(self.logo_texture)
            self.logo_texture = None
        self.renderer.close()

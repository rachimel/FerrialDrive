"""한국공학대학교와 제작자 이름을 표시하는 본편 시작 화면."""

from ctypes import byref, c_char_p, string_at
from math import cos, pi, sin, sqrt
from pathlib import Path
from time import perf_counter, sleep

from PIL import Image

from ferrial_drive.animation import ease_in_out_quint
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.loading import LoadingCancelled
from ferrial_drive.ui.pico_renderer import PicoRenderer


DATA = Path(__file__).resolve().parents[1] / "data"
# 공식 벡터의 한·영문 가로 시그니처에서 만든 투명 PNG.
# https://www.tukorea.ac.kr/sites/tukorea/files/UI/signature.ai
LOGO = DATA / "runtime/images/ui/tukorea_white_hd.png"
FONT = DATA / "fonts/SUITE-otf/SUITE-Regular.otf"
LIGHT_FONT = FONT.with_name("SUITE-Light.otf")
LOGO_HOLD_SECONDS = 0.15
SLIDE_SECONDS = 0.50
CROSS_FADE_START_SECONDS = 0.18
CROSS_FADE_SECONDS = 0.07
TURN_START_SECONDS = 0.26
NAME_FADE_SECONDS = 0.75
FINAL_HOLD_SECONDS = 0.10
FADE_OUT_SECONDS = 2.00
FADE_OUT_START_SECONDS = max(SLIDE_SECONDS, TURN_START_SECONDS + NAME_FADE_SECONDS) + FINAL_HOLD_SECONDS
PROJECT_START_SECONDS = FADE_OUT_START_SECONDS + FADE_OUT_SECONDS
PROJECT_SECONDS = 1.35
PROJECT_FADE_OUT_SECONDS = 1.0
PROJECT_LABEL = "2D Game Programming PROJECT"
# 960×540 캡처에서 측정한 기존 좌우 빈칸 27px와 69px의 평균.
SIGNATURE_GAP = 48
CROSS_RADIUS = 13


def smooth(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


class GameSplash:
    def __init__(self, pico, window_size):
        self.pico = pico
        self.width, self.height = window_size
        self.scale = min(self.width / 960, self.height / 540)
        self.renderer = PicoRenderer({"name": FONT, "project": LIGHT_FONT},
                                    {"name": max(1, round(34 * self.scale)),
                                     "project": max(1, round(24 * self.scale))})
        self.logo_texture = None
        self.project_width, self.project_height = self.renderer.text_size(PROJECT_LABEL, "project")
        self.project_glyphs = []
        for index, char in enumerate(PROJECT_LABEL):
            if char != " ":
                right = self.renderer.text_size(PROJECT_LABEL[:index + 1], "project")[0]
                glyph_width = self.renderer.text_size(char, "project")[0]
                self.project_glyphs.append((index, char, right - glyph_width))
        self.name_height = self.renderer.text_size("Rachimel", "name")[1]
        self.name_inset, self.name_width = self._ink_metrics("Rachimel")
        self.logo_inset = 0
        if LOGO.is_file():
            try:
                self._prepare_logo()
            except Exception:
                self.close()
                raise
        else:
            self.logo_inset, self.logo_width = self._ink_metrics("한국공학대학교")
        self.first_present = None

    def _ink_metrics(self, text):
        """실제 글리프의 왼쪽 여백과 불투명 픽셀이 차지하는 폭을 구한다."""
        p = self.pico
        surface = self.renderer._text_surface(text, "name", "#FFFFFF", False, 0, 0)
        try:
            rgba = p.SDL_ConvertSurfaceFormat(surface, p.SDL_PIXELFORMAT_RGBA32, 0)
            if not rgba:
                raise RuntimeError("스플래시 글자 경계를 읽을 수 없다.")
            try:
                src = rgba.contents
                pixels = string_at(src.pixels, src.pitch * src.h)
                image = Image.frombytes("RGBA", (src.w, src.h), pixels, "raw", "RGBA", src.pitch)
                left, _, right, _ = image.getchannel("A").getbbox()
                return left, right - left
            finally:
                p.SDL_FreeSurface(rgba)
        finally:
            p.SDL_FreeSurface(surface)

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
        if elapsed_seconds >= PROJECT_START_SECONDS:
            elapsed = elapsed_seconds - PROJECT_START_SECONDS
            opacity = smooth(elapsed / .28) * smooth((PROJECT_SECONDS - elapsed) / PROJECT_FADE_OUT_SECONDS)
            tracking = (2 + 9 * ease_in_out_quint(elapsed / PROJECT_SECONDS)) * s
            left = cx - (self.project_width + (len(PROJECT_LABEL) - 1) * tracking) / 2
            r.clear("#000000")
            for index, char, offset in self.project_glyphs:
                r.text(char, left + offset + index * tracking, cy - self.project_height / 2,
                       "project", "#FFFFFF", opacity)
            sweep = smooth((elapsed - PROJECT_SECONDS + .24) / .24)
            if sweep:
                r.rect(Rect(cx * (1 - sweep), cy, self.width * sweep, max(1, round(s))),
                       "#C3EDF6", .62 * sweep)
            return
        slide = smooth(elapsed_seconds / SLIDE_SECONDS)
        thickness = max(1, round(2 * s))
        cross_half = round((CROSS_RADIUS * s + (thickness - 1) / 2) / sqrt(2))
        gap = round(SIGNATURE_GAP * s)
        # 조합의 바깥 경계가 화면 중심을 기준으로 대칭이 되도록 기호를 배치한다.
        # 기호의 중심 픽셀도 한 칸을 차지한다.
        final_cross_x = round(cx + (self.logo_width - self.name_width - 1) / 2)
        cross_x = round(cx + slide * (final_cross_x - cx))
        start_left = cx - self.logo_width / 2
        end_left = final_cross_x - cross_half - gap - self.logo_width
        opacity = 1 - smooth((elapsed_seconds - FADE_OUT_START_SECONDS) / FADE_OUT_SECONDS)
        left = start_left + slide * (end_left - start_left)
        r.clear("#000000")
        if self.logo_texture:
            self.pico.SDL_SetTextureAlphaMod(self.logo_texture, round(255 * opacity))
            target = self.pico.SDL_Rect(round(left), round(cy - self.logo_height / 2),
                                        self.logo_width, self.logo_height)
            self.pico.SDL_RenderCopy(self.pico.renderer, self.logo_texture, None, byref(target))
        else:
            r.text("한국공학대학교", left - self.logo_inset, cy - self.name_height / 2, "name", "#FFFFFF", opacity)
        turn = smooth((elapsed_seconds - TURN_START_SECONDS) / (SLIDE_SECONDS - TURN_START_SECONDS))
        cross_opacity = smooth((elapsed_seconds - CROSS_FADE_START_SECONDS) / CROSS_FADE_SECONDS)
        start_name = cx - self.name_width / 2
        end_name = final_cross_x + cross_half + 1 + gap
        name_left = start_name + slide * (end_name - start_name) - self.name_inset
        name_opacity = smooth((elapsed_seconds - TURN_START_SECONDS) / NAME_FADE_SECONDS)
        r.text("Rachimel", name_left, cy - self.name_height / 2, "name", "#FFFFFF", name_opacity * opacity)
        if cross_opacity == 0:
            return
        for angle in (turn * pi / 4, turn * pi / 4 + pi / 2):
            dx, dy = cos(angle), sin(angle)
            for i in range(thickness):
                offset = i - (thickness - 1) / 2
                x, y = cross_x - dy * offset, cy + dx * offset
                r.line(x - dx * CROSS_RADIUS * s, y - dy * CROSS_RADIUS * s,
                       x + dx * CROSS_RADIUS * s, y + dy * CROSS_RADIUS * s, "#FFFFFF", cross_opacity * opacity)

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
            done = elapsed >= PROJECT_START_SECONDS + PROJECT_SECONDS
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

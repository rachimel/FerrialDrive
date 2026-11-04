"""공통 테마를 사용하는 Pico2D 도형·텍스트 렌더링."""

from collections import OrderedDict
from contextlib import contextmanager
from ctypes import byref, c_int
from importlib.resources import files
from pathlib import Path

from theme_reference import load_theme, rgb
from .text_layout import display_text, wrap_gap_lines


def plain(text):
    return display_text(text)[0]


class Canvas:
    def __init__(self, backend):
        self.backend, self.pico = backend, backend.pico
        self.theme = load_theme()
        self.colors = {key: rgb(value) for key, value in self.theme["colors"].items()}
        self.fonts, self.textures, self.measurements = {}, OrderedDict(), OrderedDict()
        self.wraps = OrderedDict()
        try:
            for role, settings in self.theme["fonts"].items():
                path = Path(__file__).resolve().parents[2] / "data/fonts" / settings["path"]
                if not path.is_file():
                    path = files("pico2d").joinpath("data", "ConsolaMalgun.ttf")
                self.fonts[role] = self.pico.load_font(str(path), settings["size"])
            self.pico.SDL_SetRenderDrawBlendMode(self.pico.renderer, self.pico.SDL_BLENDMODE_BLEND)
        except BaseException:
            self.close()
            raise

    def fill(self, rect, color):
        pico = self.pico
        pico.SDL_SetRenderDrawColor(pico.renderer, *self.colors[color], 255)
        target = pico.SDL_Rect(*(round(value) for value in rect))
        pico.SDL_RenderFillRect(pico.renderer, byref(target))

    def border(self, rect, color="line"):
        x, y, width, height = rect
        for area in ((x,y,width,1),(x,y+height-1,width,1),(x,y,1,height),(x+width-1,y,1,height)):
            self.fill(area, color)

    def panel(self, rect, color="panel"):
        self.fill(rect, color)
        self.border(rect)

    def size(self, text, role="body"):
        key = (text, role)
        if key not in self.measurements:
            width, height = c_int(), c_int()
            if self.pico.TTF_SizeUTF8(self.fonts[role].font, text.encode("utf-8"), byref(width), byref(height)) != 0:
                raise RuntimeError("글자 크기 측정 실패")
            self.measurements[key] = (width.value, height.value)
            if len(self.measurements) > 2048:
                self.measurements.popitem(last=False)
        return self.measurements[key]

    def fit(self, text, width, role="body"):
        if self.size(text, role)[0] <= width:
            return text
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if self.size(text[:middle] + "…", role)[0] <= width:
                low = middle
            else:
                high = middle - 1
        return text[:low] + "…"

    def text(self, text, x, y, role="body", color="text", max_width=None):
        if max_width is not None:
            text = self.fit(text, max_width, role)
        if not text:
            return
        key = (text, role, color)
        pico = self.pico
        if key not in self.textures:
            surface = pico.TTF_RenderUTF8_Blended(self.fonts[role].font, text.encode("utf-8"),
                                                 pico.SDL_Color(*self.colors[color], 255))
            if not surface:
                raise RuntimeError("텍스트 렌더링 실패")
            try:
                texture = pico.SDL_CreateTextureFromSurface(pico.renderer, surface)
                if not texture:
                    raise RuntimeError("텍스트 텍스처 생성 실패")
                self.textures[key] = (texture, surface.contents.w, surface.contents.h)
            finally:
                pico.SDL_FreeSurface(surface)
            if len(self.textures) > 512:
                old, _, _ = self.textures.popitem(last=False)[1]
                pico.SDL_DestroyTexture(old)
        self.textures.move_to_end(key)
        texture, width, height = self.textures[key]
        target = pico.SDL_Rect(round(x), round(y), width, height)
        pico.SDL_RenderCopy(pico.renderer, texture, None, byref(target))

    def wrap(self, text, width, role="small"):
        key = (text, width, role)
        if key not in self.wraps:
            lines = []
            for paragraph in text.splitlines():
                current = ""
                for char in paragraph:
                    if current and self.size(current + char, role)[0] > width:
                        lines.append(current)
                        current = ""
                    current += char
                lines.append(current)
            self.wraps[key] = lines or [""]
            if len(self.wraps) > 256:
                self.wraps.popitem(last=False)
        return self.wraps[key]

    def gap_lines(self, text, width, role="small"):
        key = ("gaps", text, width, role)
        if key not in self.wraps:
            self.wraps[key] = wrap_gap_lines(text, width, lambda value: self.size(value, role)[0])
            if len(self.wraps) > 256:
                self.wraps.popitem(last=False)
        return self.wraps[key]

    def gap_line(self, line, x, y, selected_token=None):
        cursor = 0
        for mark in line.marks:
            prefix = line.text[cursor:mark.start]
            self.text(prefix, x, y, "small")
            x += self.size(prefix, "small")[0]
            label = line.text[mark.start:mark.end]
            width, height = self.size(label, "small")
            selected = mark.token == selected_token
            self.fill((x, y, width, height), "warning" if selected else "selected")
            self.text(label, x, y, "small", "button_text" if selected else "warning")
            if not selected:
                self.fill((x, y + height - 1, width, 1), "warning")
            x += width
            cursor = mark.end
        self.text(line.text[cursor:], x, y, "small")

    @contextmanager
    def clip(self, rect):
        pico = self.pico
        previous = pico.SDL_Rect()
        enabled = pico.SDL_RenderIsClipEnabled(pico.renderer)
        pico.SDL_RenderGetClipRect(pico.renderer, byref(previous))
        target = pico.SDL_Rect(*(round(value) for value in rect))
        pico.SDL_RenderSetClipRect(pico.renderer, byref(target))
        try:
            yield
        finally:
            pico.SDL_RenderSetClipRect(pico.renderer, byref(previous) if enabled else None)

    def close(self):
        for texture, _, _ in self.textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.textures.clear()
        for font in self.fonts.values():
            self.pico.TTF_CloseFont(font.font)
        self.fonts.clear()

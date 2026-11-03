"""Pico2D가 연 SDL 렌더러에 그리는 어댑터. 라이브러리 원본은 수정하지 않는다."""

from collections import OrderedDict
from ctypes import byref, c_int
from math import cos, sin, tau
from pathlib import Path

from .components import Rect


class PicoRenderer:
    def __init__(self, font_paths: dict[str, Path], font_sizes: dict[str, int]):
        import pico2d.pico2d as pico

        self.pico = pico
        self.fonts = {}
        self.textures = OrderedDict()
        try:
            for role, size in font_sizes.items():
                self.fonts[role] = pico.load_font(str(font_paths[role]), size)
        except BaseException:
            self.close()
            raise
        pico.SDL_SetRenderDrawBlendMode(pico.renderer, pico.SDL_BLENDMODE_BLEND)

    @staticmethod
    def rgba(color: str, opacity: float = 1) -> tuple[int, int, int, int]:
        value = color.removeprefix("#")
        return (*(int(value[index:index + 2], 16) for index in (0, 2, 4)),
                round(max(0.0, min(1.0, opacity)) * 255))

    def clear(self, color: str):
        self.pico.SDL_SetRenderDrawColor(self.pico.renderer, *self.rgba(color))
        self.pico.SDL_RenderClear(self.pico.renderer)

    def rect(self, rect: Rect, color: str, opacity: float = 1, filled: bool = True):
        pico = self.pico
        pico.SDL_SetRenderDrawColor(pico.renderer, *self.rgba(color, opacity))
        target = pico.SDL_Rect(round(rect.x), round(rect.y), round(rect.width), round(rect.height))
        draw = pico.SDL_RenderFillRect if filled else pico.SDL_RenderDrawRect
        draw(pico.renderer, byref(target))

    def line(self, x1: float, y1: float, x2: float, y2: float,
             color: str, opacity: float = 1):
        pico = self.pico
        pico.SDL_SetRenderDrawColor(pico.renderer, *self.rgba(color, opacity))
        pico.SDL_RenderDrawLine(pico.renderer, round(x1), round(y1), round(x2), round(y2))

    def circle(self, x: float, y: float, radius: float, color: str, opacity: float = 1):
        segments = max(24, round(radius * 2))
        for index in range(segments):
            first, second = tau * index / segments, tau * (index + 1) / segments
            self.line(x + cos(first) * radius, y + sin(first) * radius,
                      x + cos(second) * radius, y + sin(second) * radius, color, opacity)

    def _measure(self, text: str, role: str) -> tuple[int, int]:
        width, height = c_int(), c_int()
        if self.pico.TTF_SizeUTF8(self.fonts[role].font, text.encode("utf-8"),
                                  byref(width), byref(height)) != 0:
            raise RuntimeError("텍스트 크기를 계산할 수 없다.")
        return width.value, height.value

    def text_size(self, text: str, role: str) -> tuple[int, int]:
        return self._measure(text, role)

    def text_ascent(self, role: str) -> int:
        return self.pico.TTF_FontAscent(self.fonts[role].font)

    def text(self, text: str, x: float, y: float, role: str, color: str,
             opacity: float = 1, max_width: float | None = None, align: str = "left"):
        if opacity <= 0 or not text:
            return
        if max_width is not None and self._measure(text, role)[0] > max_width:
            while text and self._measure(text + "…", role)[0] > max_width:
                text = text[:-1]
            if not text:
                return
            text += "…"
        key = (text, role, color)
        pico = self.pico
        if key not in self.textures:
            red, green, blue, _ = self.rgba(color)
            surface = pico.TTF_RenderUTF8_Blended(
                self.fonts[role].font, text.encode("utf-8"), pico.SDL_Color(red, green, blue, 255))
            if not surface:
                raise RuntimeError(f"텍스트 렌더링 실패: {text}")
            width, height = surface.contents.w, surface.contents.h
            texture = pico.SDL_CreateTextureFromSurface(pico.renderer, surface)
            pico.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError("텍스트 텍스처 생성 실패")
            self.textures[key] = (texture, width, height)
            if len(self.textures) > 256:
                _, (old_texture, _, _) = self.textures.popitem(last=False)
                pico.SDL_DestroyTexture(old_texture)
        self.textures.move_to_end(key)
        texture, width, height = self.textures[key]
        if align == "right":
            x -= width
        elif align == "center":
            x -= width / 2
        destination = pico.SDL_Rect(round(x), round(y), width, height)
        pico.SDL_SetTextureAlphaMod(texture, self.rgba(color, opacity)[3])
        pico.SDL_RenderCopy(pico.renderer, texture, None, byref(destination))

    def save_frame(self, path: Path, width: int, height: int):
        """자동 실행 확인용 PNG. 프레젠트하기 전의 현재 화면을 저장한다."""
        pico = self.pico
        surface = pico.SDL_CreateRGBSurfaceWithFormat(0, width, height, 32,
                                                      pico.SDL_PIXELFORMAT_RGBA32)
        if not surface:
            raise RuntimeError("화면 저장용 surface 생성 실패")
        try:
            if pico.SDL_RenderReadPixels(pico.renderer, None, pico.SDL_PIXELFORMAT_RGBA32,
                                         surface.contents.pixels, surface.contents.pitch) != 0:
                raise RuntimeError("화면 읽기 실패")
            path.parent.mkdir(parents=True, exist_ok=True)
            if pico.IMG_SavePNG(surface, str(path).encode("utf-8")) != 0:
                raise RuntimeError("PNG 저장 실패")
        finally:
            pico.SDL_FreeSurface(surface)

    def close(self):
        for texture, _, _ in self.textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.textures.clear()
        for font in self.fonts.values():
            self.pico.TTF_CloseFont(font.font)
        self.fonts.clear()

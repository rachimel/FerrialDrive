"""Pico2D가 연 SDL 렌더러에 그리는 어댑터. 라이브러리 원본은 수정하지 않는다."""

from collections import OrderedDict
from ctypes import byref, c_int
from math import ceil, cos, floor, sin, sqrt, tau
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

    def ring(self, x, y, radius, thickness, color, opacity=1):
        """동심원 띠를 한 번씩 채워 두꺼운 링의 알파 중첩을 막는다."""
        outer = radius + thickness / 2
        inner = max(0.0, radius - thickness / 2)
        for pixel_y in range(ceil(y - outer - 0.5), floor(y + outer - 0.5) + 1):
            dy = pixel_y + 0.5 - y
            outer_span = sqrt(max(0.0, outer * outer - dy * dy))
            left, right = ceil(x - outer_span - 0.5), floor(x + outer_span - 0.5)
            spans = [(left, right)]
            if abs(dy) < inner:
                inner_span = sqrt(inner * inner - dy * dy)
                left_end = floor(x - inner_span - 0.5)
                right_start = max(left_end + 1, ceil(x + inner_span - 0.5))
                spans = [(left, left_end), (right_start, right)]
            for start, end in spans:
                if start <= end:
                    self.line(start, pixel_y, end, pixel_y, color, opacity)

    def filled_triangle(self, first, second, third, color: str, opacity: float = 1):
        """픽셀 중심을 기준으로 내부를 한 번씩 채워 전환 중 알파 중첩을 막는다."""
        if opacity <= 0:
            return
        pico = self.pico
        vertices = (first, second, third)
        edges = tuple(zip(vertices, vertices[1:] + vertices[:1]))
        top = max(0, ceil(min(point[1] for point in vertices) - 0.5))
        bottom = min(pico.get_canvas_height() - 1, floor(max(point[1] for point in vertices) - 0.5))
        pico.SDL_SetRenderDrawColor(pico.renderer, *self.rgba(color, opacity))
        for pixel_y in range(top, bottom + 1):
            scan_y = pixel_y + 0.5
            intersections = []
            for (x1, y1), (x2, y2) in edges:
                if min(y1, y2) <= scan_y < max(y1, y2):
                    intersections.append(x1 + (scan_y - y1) * (x2 - x1) / (y2 - y1))
            if len(intersections) < 2:
                continue
            left = max(0, ceil(min(intersections) - 0.5))
            right = min(pico.get_canvas_width() - 1, floor(max(intersections) - 0.5))
            if left <= right:
                pico.SDL_RenderDrawLine(pico.renderer, left, pixel_y, right, pixel_y)

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
             opacity: float = 1, max_width: float | None = None, align: str = "left",
             scale_x: float = 1, scale_y: float = 1, clip_rect: Rect | None = None):
        if opacity <= 0 or not text or scale_x <= 0 or scale_y <= 0:
            return
        if max_width is not None and self._measure(text, role)[0] > max_width:
            while text and self._measure(text + "…", role)[0] > max_width:
                text = text[:-1]
            if not text:
                return
            text += "…"
        texture, width, height = self._text_texture(text, role, color)
        pico = self.pico
        draw_width, draw_height = round(width * scale_x), round(height * scale_y)
        if draw_width <= 0 or draw_height <= 0:
            return
        if align == "right":
            x -= draw_width
        elif align == "center":
            x -= draw_width / 2
        destination = pico.SDL_Rect(round(x), round(y), draw_width, draw_height)
        source = None
        if clip_rect is not None:
            left = max(destination.x, ceil(clip_rect.x))
            top = max(destination.y, ceil(clip_rect.y))
            right = min(destination.x + draw_width, floor(clip_rect.x + clip_rect.width))
            bottom = min(destination.y + draw_height, floor(clip_rect.y + clip_rect.height))
            if right <= left or bottom <= top:
                return
            source_left = max(0, floor((left - destination.x) * width / draw_width))
            source_top = max(0, floor((top - destination.y) * height / draw_height))
            source_right = min(width, ceil((right - destination.x) * width / draw_width))
            source_bottom = min(height, ceil((bottom - destination.y) * height / draw_height))
            source = pico.SDL_Rect(source_left, source_top, source_right - source_left,
                                   source_bottom - source_top)
            destination = pico.SDL_Rect(left, top, right - left, bottom - top)
        pico.SDL_SetTextureAlphaMod(texture, self.rgba(color, opacity)[3])
        pico.SDL_RenderCopy(pico.renderer, texture, byref(source) if source is not None else None,
                            byref(destination))

    def _text_texture(self, text: str, role: str, color: str):
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
        return self.textures[key]

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

"""Pico2D의 기존 글자 캐시를 유지하는 v2 전용 사각형 텍스처 투영."""

from contextlib import contextmanager
from ctypes import byref, c_float, c_int
from math import isfinite

from ferrial_drive.ui.pico_renderer import PicoRenderer


class PicoV2Renderer(PicoRenderer):
    def __init__(self, font_paths, font_sizes):
        self.ink_bottoms = {}
        super().__init__(font_paths, font_sizes)

    def digit_ink_bottom(self, role):
        """글꼴의 빈 하단 여백을 제외한 숫자 기준선을 캐시한다."""
        if role not in self.ink_bottoms:
            ascent = self.text_ascent(role)
            bottoms = []
            for digit in "0123456789":
                metrics = [c_int() for _ in range(5)]
                result = self.pico.TTF_GlyphMetrics(self.fonts[role].font, ord(digit),
                                                   *(byref(value) for value in metrics))
                if result != 0:
                    raise RuntimeError("숫자 기준선 측정 실패")
                bottoms.append(ascent - metrics[2].value)
            self.ink_bottoms[role] = min(self.text_size("0", role)[1], max(bottoms))
        return self.ink_bottoms[role]

    @contextmanager
    def scaled(self, amount, anchor):
        """HUD 묶음의 앵커를 유지하며 크기만 조절하고 SDL 상태를 복원한다."""
        if not isfinite(amount) or amount <= 0:
            raise ValueError("HUD 크기 배율은 양수여야 한다.")
        p = self.pico
        sx, sy = c_float(), c_float()
        viewport = p.SDL_Rect()
        p.SDL_RenderGetScale(p.renderer, byref(sx), byref(sy))
        p.SDL_RenderGetViewport(p.renderer, byref(viewport))
        # SDL의 viewport 원점도 배율을 받으므로 보상값은 새 배율로 나눈다.
        offset_x = round((viewport.x + (1 - amount) * anchor[0]) / amount)
        offset_y = round((viewport.y + (1 - amount) * anchor[1]) / amount)
        target = p.SDL_Rect(offset_x, offset_y, viewport.w, viewport.h)
        try:
            p.SDL_RenderSetScale(p.renderer, sx.value * amount, sy.value * amount)
            p.SDL_RenderSetViewport(p.renderer, byref(target))
            yield
        finally:
            p.SDL_RenderSetScale(p.renderer, sx.value, sy.value)
            p.SDL_RenderSetViewport(p.renderer, byref(viewport))

    def filled_triangle(self, first, second, third, color, opacity=1):
        """축소 후에도 면 사이 틈이 생기지 않게 SDL의 삼각형 채움을 사용한다."""
        if opacity <= 0:
            return
        p = self.pico
        color_mod = p.SDL_Color(*self.rgba(color, opacity))
        vertices = (p.SDL_Vertex * 3)(*(
            p.SDL_Vertex(p.SDL_FPoint(*point), color_mod, p.SDL_FPoint(0, 0))
            for point in (first, second, third)))
        if p.SDL_RenderGeometry(p.renderer, None, vertices, 3, None, 0) != 0:
            raise RuntimeError("v2 도형 채움 실패: " + p.SDL_GetError().decode("utf-8", errors="replace"))

    def warped_text(self, text, x, y, role, color, project, opacity=1, *,
                    scale_x=1, scale_y=1, clip_rect=None):
        """평면에서 글자를 자른 뒤 투영해 회전 카운터의 경계를 유지한다."""
        if not text or opacity <= 0 or scale_x <= 0 or scale_y <= 0:
            return
        texture, width, height = self._text_texture(text, role, color)
        draw_width, draw_height = width * scale_x, height * scale_y
        left, top, right, bottom = x, y, x + draw_width, y + draw_height
        if clip_rect is not None:
            left, top = max(left, clip_rect.x), max(top, clip_rect.y)
            right = min(right, clip_rect.x + clip_rect.width)
            bottom = min(bottom, clip_rect.y + clip_rect.height)
        if right <= left or bottom <= top:
            return
        coordinates = ((left, top), (right, top), (right, bottom), (left, bottom))
        p = self.pico
        color_mod = p.SDL_Color(255, 255, 255, self.rgba(color, opacity)[3])
        vertices = (p.SDL_Vertex * 4)(*(
            p.SDL_Vertex(p.SDL_FPoint(*project(px, py)), color_mod,
                         p.SDL_FPoint((px - x) / draw_width, (py - y) / draw_height))
            for px, py in coordinates))
        indices = (c_int * 6)(0, 1, 2, 0, 2, 3)
        p.SDL_SetTextureAlphaMod(texture, 255)
        p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear)
        if p.SDL_RenderGeometry(p.renderer, texture, vertices, 4, indices, 6) != 0:
            raise RuntimeError("v2 글자 투영 실패: " + p.SDL_GetError().decode("utf-8", errors="replace"))

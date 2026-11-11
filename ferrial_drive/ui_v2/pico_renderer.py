"""Pico2D의 기존 글자 캐시를 유지하는 v2 전용 사각형 텍스처 투영."""

from contextlib import contextmanager
from collections import OrderedDict
from ctypes import byref, c_float, c_int, c_ubyte, memmove
from math import ceil, floor, isfinite

from ferrial_drive.ui.pico_renderer import PicoRenderer
from .panels import clip_panel_band


class PicoV2Renderer(PicoRenderer):
    def __init__(self, font_paths, font_sizes):
        self.ink_bottoms = {}
        self.filtered_textures = OrderedDict()
        self.scanline_textures = OrderedDict()
        super().__init__(font_paths, font_sizes)

    def _scanline_texture(self, height, spacing, thickness, color):
        """위상과 무관한 세로 반복 패턴. 두 배 해상도로 만들어 선형 보간한다."""
        p = self.pico
        logical_height = ceil(height + spacing)
        key = (logical_height, spacing, thickness, color)
        if key not in self.scanline_textures:
            surface = p.SDL_CreateRGBSurfaceWithFormat(0, 1, logical_height * 2, 32, p.SDL_PIXELFORMAT_RGBA32)
            if not surface:
                raise RuntimeError("Scanline 패턴 surface 생성 실패")
            try:
                if p.SDL_LockSurface(surface) != 0:
                    raise RuntimeError("Scanline 패턴 surface 잠금 실패")
                try:
                    rgb = self.rgba(color)[:3]
                    for index in range(logical_height * 2):
                        offset = ((index + 0.5) / 2) % spacing
                        alpha = 255 if (offset - spacing / 2) % spacing < thickness else 0
                        memmove(surface.contents.pixels + index * surface.contents.pitch,
                                bytes((*rgb, alpha)), 4)
                finally:
                    p.SDL_UnlockSurface(surface)
                texture = p.SDL_CreateTextureFromSurface(p.renderer, surface)
            finally:
                p.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError("Scanline 패턴 텍스처 생성 실패")
            if (p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_BLEND) != 0
                    or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear) != 0):
                p.SDL_DestroyTexture(texture)
                raise RuntimeError("Scanline 패턴 필터 설정 실패")
            self.scanline_textures[key] = texture
            if len(self.scanline_textures) > 8:
                _, old = self.scanline_textures.popitem(last=False)
                p.SDL_DestroyTexture(old)
        self.scanline_textures.move_to_end(key)
        return self.scanline_textures[key], logical_height

    def scanline_layer(self, surface, color, opacity, spacing_pixels, thickness_pixels,
                       offset_pixels, *, bright_band=None):
        """패턴 UV만 스크롤한다. 밝은 띠는 같은 패턴 위의 밝기 구간으로 그린다."""
        if opacity <= 0:
            return
        top = min(y for _, y in surface)
        height = max(y for _, y in surface) - top
        polygons = (surface,)
        if bright_band is not None:
            band_top, band_height = bright_band
            polygons = tuple(clip_panel_band(surface, band_top + index * band_height / 2, band_height / 2)
                             for index in range(2))
        polygons = tuple(polygon for polygon in polygons if len(polygon) >= 3)
        if not polygons:
            return
        texture, texture_height = self._scanline_texture(height, spacing_pixels, thickness_pixels, color)
        p = self.pico
        p.SDL_SetTextureAlphaMod(texture, 255)
        offset = spacing_pixels - offset_pixels % spacing_pixels
        for polygon in polygons:
            vertices = []
            for x, y in polygon:
                weight = 1
                if bright_band is not None:
                    weight = max(0, 1 - abs((y - band_top - band_height / 2) / (band_height / 2)))
                tint = p.SDL_Color(255, 255, 255, self.rgba(color, opacity * weight)[3])
                vertices.append(p.SDL_Vertex(p.SDL_FPoint(x, y), tint,
                                             p.SDL_FPoint(0.5, (y - top + offset) / texture_height)))
            indices = tuple(value for index in range(1, len(vertices) - 1) for value in (0, index, index + 1))
            if p.SDL_RenderGeometry(p.renderer, texture, (p.SDL_Vertex * len(vertices))(*vertices),
                                    len(vertices), (c_int * len(indices))(*indices), len(indices)) != 0:
                raise RuntimeError("Scanline 스크롤 표시 실패")

    def filtered_polygons(self, polygons, color, opacity=1, samples=2):
        """확대 렌더를 선형 축소하고 이동·투명도와 무관한 도형 텍스처를 재사용한다."""
        if opacity <= 0:
            return
        if type(samples) is not int or not 2 <= samples <= 4:
            raise ValueError("도형 필터 배율은 2~4의 정수여야 한다.")
        left = floor(min(x for polygon in polygons for x, _ in polygon)) - 1
        top = floor(min(y for polygon in polygons for _, y in polygon)) - 1
        width = ceil(max(x for polygon in polygons for x, _ in polygon)) - left + 1
        height = ceil(max(y for polygon in polygons for _, y in polygon)) - top + 1
        local = tuple(tuple((round(x - left, 6), round(y - top, 6)) for x, y in polygon)
                      for polygon in polygons)
        key = (local, color, samples)
        p = self.pico
        if key not in self.filtered_textures:
            self.filtered_textures[key] = self._filtered_texture(local, color, width, height, samples)
            if len(self.filtered_textures) > 32:
                _, old = self.filtered_textures.popitem(last=False)
                p.SDL_DestroyTexture(old)
        self.filtered_textures.move_to_end(key)
        texture = self.filtered_textures[key]
        p.SDL_SetTextureAlphaMod(texture, self.rgba(color, opacity)[3])
        destination = p.SDL_FRect(left, top, width, height)
        if p.SDL_RenderCopyF(p.renderer, texture, None, byref(destination)) != 0:
            raise RuntimeError("필터 도형 표시 실패")

    def _filtered_texture(self, polygons, color, width, height, samples):
        p = self.pico
        texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA8888,
                                      p.SDL_TEXTUREACCESS_TARGET, width * samples, height * samples)
        if not texture:
            raise RuntimeError("필터 도형 텍스처 생성 실패")
        target = p.SDL_GetRenderTarget(p.renderer)
        sx, sy, blend = c_float(), c_float(), c_int()
        viewport, clip = p.SDL_Rect(), p.SDL_Rect()
        rgba = [c_ubyte() for _ in range(4)]
        p.SDL_RenderGetScale(p.renderer, byref(sx), byref(sy))
        p.SDL_RenderGetViewport(p.renderer, byref(viewport))
        clipped = p.SDL_RenderIsClipEnabled(p.renderer)
        p.SDL_RenderGetClipRect(p.renderer, byref(clip))
        p.SDL_GetRenderDrawBlendMode(p.renderer, byref(blend))
        p.SDL_GetRenderDrawColor(p.renderer, *(byref(value) for value in rgba))
        try:
            try:
                if p.SDL_SetRenderTarget(p.renderer, texture) != 0:
                    raise RuntimeError("필터 도형 렌더 대상 설정 실패")
                p.SDL_RenderSetScale(p.renderer, 1, 1)
                p.SDL_RenderSetViewport(p.renderer, None)
                p.SDL_RenderSetClipRect(p.renderer, None)
                # 투명 여백도 같은 RGB로 채워 선형 필터의 검은 가장자리를 방지한다.
                p.SDL_SetRenderDrawColor(p.renderer, *self.rgba(color)[:3], 0)
                p.SDL_RenderClear(p.renderer)
                p.SDL_SetRenderDrawBlendMode(p.renderer, p.SDL_BLENDMODE_NONE)
                for polygon in polygons:
                    points = tuple((x * samples, y * samples) for x, y in polygon)
                    for index in range(1, len(points) - 1):
                        self.filled_triangle(points[0], points[index], points[index + 1], color)
            finally:
                p.SDL_SetRenderTarget(p.renderer, target)
                p.SDL_RenderSetScale(p.renderer, sx.value, sy.value)
                p.SDL_RenderSetViewport(p.renderer, byref(viewport))
                p.SDL_RenderSetClipRect(p.renderer, byref(clip) if clipped else None)
                p.SDL_SetRenderDrawBlendMode(p.renderer, blend.value)
                p.SDL_SetRenderDrawColor(p.renderer, *(value.value for value in rgba))
            if (p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_BLEND) != 0
                    or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear) != 0):
                raise RuntimeError("도형 축소 필터 설정 실패")
        except BaseException:
            p.SDL_DestroyTexture(texture)
            raise
        return texture

    def close(self):
        for texture in self.scanline_textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.scanline_textures.clear()
        for texture in self.filtered_textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.filtered_textures.clear()
        self.ink_bottoms.clear()
        super().close()

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

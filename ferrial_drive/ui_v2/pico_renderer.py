"""Pico2D의 기존 글자 캐시를 유지하는 v2 전용 사각형 텍스처 투영."""

from contextlib import contextmanager
from collections import OrderedDict
from ctypes import byref, c_float, c_int, c_ubyte, memmove, string_at
from math import ceil, exp, floor, isfinite, log2
from random import Random
from struct import Struct

from ferrial_drive.ui.pico_renderer import PicoRenderer
from .panels import clip_panel_band, clip_panel_rect, visible_panel_y_range


PARTICLE_VERTEX = Struct("=ff4Bff")


class PicoV2Renderer(PicoRenderer):
    def __init__(self, font_paths, font_sizes):
        self.ink_bottoms = {}
        self.filtered_textures = OrderedDict()
        self.scanline_textures = OrderedDict()
        self.grain_textures = OrderedDict()
        self.neon_textures = OrderedDict()
        self.neon_font_sizes = dict(font_sizes)
        self.motion_texture = None
        self.motion_size = None
        self.motion_sampler = None
        self.particle_texture = None
        self.particle_indices = None
        self.particle_instances = None
        self.compute_particles = None
        self.particle_instancing_supported = None
        super().__init__(font_paths, font_sizes)

    def draw_transform(self):
        p = self.pico
        sx, sy = c_float(), c_float()
        viewport, clipping = p.SDL_Rect(), p.SDL_Rect()
        width, height = c_int(), c_int()
        p.SDL_RenderGetScale(p.renderer, byref(sx), byref(sy))
        p.SDL_RenderGetViewport(p.renderer, byref(viewport))
        p.SDL_GetRendererOutputSize(p.renderer, byref(width), byref(height))
        p.SDL_RenderGetClipRect(p.renderer, byref(clipping))
        clip = tuple(getattr(clipping, key) for key in ("x", "y", "w", "h")) if p.SDL_RenderIsClipEnabled(p.renderer) else None
        return ((sx.value, sy.value), tuple(getattr(viewport, key) for key in ("x", "y", "w", "h")),
                (width.value, height.value), clip)

    def panel_y_range(self, surface):
        return visible_panel_y_range(surface, self.draw_transform())

    def _grain_texture(self, cells, seed, frame_index):
        p = self.pico
        key = (cells, seed, frame_index)
        if key not in self.grain_textures:
            surface = p.SDL_CreateRGBSurfaceWithFormat(0, cells, cells, 32, p.SDL_PIXELFORMAT_RGBA32)
            if not surface:
                raise RuntimeError("Film grain surface 생성 실패")
            try:
                if p.SDL_LockSurface(surface) != 0:
                    raise RuntimeError("Film grain surface 잠금 실패")
                try:
                    random = Random(seed + frame_index * 104729)
                    for y in range(cells):
                        row = bytearray()
                        for _ in range(cells):
                            shade = random.randrange(256)
                            row.extend((shade, shade, shade, 255))
                        memmove(surface.contents.pixels + y * surface.contents.pitch, bytes(row), cells * 4)
                finally:
                    p.SDL_UnlockSurface(surface)
                texture = p.SDL_CreateTextureFromSurface(p.renderer, surface)
            finally:
                p.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError("Film grain 텍스처 생성 실패")
            if (p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_BLEND) != 0
                    or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear) != 0):
                p.SDL_DestroyTexture(texture)
                raise RuntimeError("Film grain 필터 설정 실패")
            self.grain_textures[key] = texture
            if len(self.grain_textures) > 16:
                _, old = self.grain_textures.popitem(last=False)
                p.SDL_DestroyTexture(old)
        self.grain_textures.move_to_end(key)
        return self.grain_textures[key]

    def film_grain(self, surface, opacity, frame_index, *, tile_pixels=64, cell_pixels=1.25, seed=173):
        """화면 좌표의 작은 흑백 타일을 패널 면 안에서만 반복한다."""
        if opacity <= 0:
            return
        if not all(map(isfinite, (tile_pixels, cell_pixels))) or not 0 < cell_pixels <= tile_pixels:
            raise ValueError("Film grain 입자·타일 크기는 양수이며 입자가 타일보다 클 수 없다.")
        p = self.pico
        sx, sy = c_float(), c_float()
        viewport, output_width, output_height = p.SDL_Rect(), c_int(), c_int()
        p.SDL_RenderGetScale(p.renderer, byref(sx), byref(sy))
        p.SDL_RenderGetViewport(p.renderer, byref(viewport))
        p.SDL_GetRendererOutputSize(p.renderer, byref(output_width), byref(output_height))
        screen = tuple(((x + viewport.x) * sx.value, (y + viewport.y) * sy.value) for x, y in surface)
        screen = clip_panel_rect(screen, 0, 0, output_width.value, output_height.value)
        if len(screen) < 3:
            return
        texture = self._grain_texture(ceil(tile_pixels / cell_pixels), seed, frame_index)
        p.SDL_SetTextureAlphaMod(texture, 255)
        color = p.SDL_Color(255, 255, 255, self.rgba("#FFFFFF", opacity)[3])
        for row in range(floor(min(y for _, y in screen) / tile_pixels), ceil(max(y for _, y in screen) / tile_pixels)):
            for column in range(floor(min(x for x, _ in screen) / tile_pixels), ceil(max(x for x, _ in screen) / tile_pixels)):
                left, top = column * tile_pixels, row * tile_pixels
                polygon = clip_panel_rect(screen, left, top, tile_pixels, tile_pixels)
                if len(polygon) < 3:
                    continue
                vertices = tuple(p.SDL_Vertex(p.SDL_FPoint(x / sx.value - viewport.x, y / sy.value - viewport.y),
                                              color, p.SDL_FPoint((x - left) / tile_pixels, (y - top) / tile_pixels))
                                 for x, y in polygon)
                for index in range(1, len(vertices) - 1):
                    triangle = (p.SDL_Vertex * 3)(vertices[0], vertices[index], vertices[index + 1])
                    if p.SDL_RenderGeometry(p.renderer, texture, triangle, 3, None, 0) != 0:
                        raise RuntimeError("Film grain 표시 실패")

    def _neon_texture(self, text, role, color, radius, *, bold=False):
        p = self.pico
        key = (text, role, color, radius, bold)
        if key not in self.neon_textures:
            with self._font_style(role, bold) as font:
                original = p.TTF_RenderUTF8_Blended(font, text.encode("utf-8"), p.SDL_Color(255, 255, 255, 255))
            if not original:
                raise RuntimeError("네온 글자 마스크 생성 실패")
            try:
                source = p.SDL_ConvertSurfaceFormat(original, p.SDL_PIXELFORMAT_RGBA32, 0)
            finally:
                p.SDL_FreeSurface(original)
            if not source:
                raise RuntimeError("네온 글자 마스크 변환 실패")
            pad = ceil(radius)
            width, height = source.contents.w + pad * 2, source.contents.h + pad * 2
            mask = [0] * (width * height)
            try:
                if p.SDL_LockSurface(source) != 0:
                    raise RuntimeError("네온 글자 마스크 잠금 실패")
                try:
                    for y in range(source.contents.h):
                        row = string_at(source.contents.pixels + y * source.contents.pitch, source.contents.w * 4)
                        start = (y + pad) * width + pad
                        mask[start:start + source.contents.w] = row[3::4]
                finally:
                    p.SDL_UnlockSurface(source)
            finally:
                p.SDL_FreeSurface(source)
            sigma = max(0.5, radius / 2)
            weights = [exp(-offset * offset / (2 * sigma * sigma)) for offset in range(-pad, pad + 1)]
            total = sum(weights)
            kernel = tuple((offset, weight / total) for offset, weight in zip(range(-pad, pad + 1), weights))
            horizontal = [sum(mask[y * width + x + offset] * weight for offset, weight in kernel if 0 <= x + offset < width)
                          for y in range(height) for x in range(width)]
            blurred = [sum(horizontal[(y + offset) * width + x] * weight for offset, weight in kernel if 0 <= y + offset < height)
                       for y in range(height) for x in range(width)]
            surface = p.SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, p.SDL_PIXELFORMAT_RGBA32)
            if not surface:
                raise RuntimeError("네온 광 surface 생성 실패")
            try:
                if p.SDL_LockSurface(surface) != 0:
                    raise RuntimeError("네온 광 surface 잠금 실패")
                try:
                    rgb = self.rgba(color)[:3]
                    for y in range(height):
                        row = b"".join(bytes((*rgb, round(alpha))) for alpha in blurred[y * width:(y + 1) * width])
                        memmove(surface.contents.pixels + y * surface.contents.pitch, row, width * 4)
                finally:
                    p.SDL_UnlockSurface(surface)
                texture = p.SDL_CreateTextureFromSurface(p.renderer, surface)
            finally:
                p.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError("네온 광 텍스처 생성 실패")
            if (p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_BLEND) != 0
                    or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear) != 0):
                p.SDL_DestroyTexture(texture)
                raise RuntimeError("네온 광 필터 설정 실패")
            self.neon_textures[key] = (texture, width, height, pad)
            if len(self.neon_textures) > 64:
                _, (old, _, _, _) = self.neon_textures.popitem(last=False)
                p.SDL_DestroyTexture(old)
        self.neon_textures.move_to_end(key)
        return self.neon_textures[key]

    def _draw_neon_glow(self, text, x, y, role, color, opacity, radius, *, bold=False):
        texture, width, height, pad = self._neon_texture(text, role, color, radius, bold=bold)
        self.pico.SDL_SetTextureAlphaMod(texture, self.rgba(color, opacity)[3])
        destination = self.pico.SDL_FRect(x - pad, y - pad, width, height)
        if self.pico.SDL_RenderCopyF(self.pico.renderer, texture, None, byref(destination)) != 0:
            raise RuntimeError("네온 광 표시 실패")

    def _draw_neon_core(self, text, x, y, role, color, opacity, *, bold=False):
        """본문은 3배 해상도에서 만들어 광과 같은 소수점 좌표에 축소한다."""
        p = self.pico
        key = (text, role, color, bold, "neon_core")
        if key not in self.textures:
            width, height = self.text_size(text, role, bold=bold)
            size = self.neon_font_sizes[role]
            with self._font_style(role, bold) as font:
                if p.TTF_SetFontSize(font, size * 3) != 0:
                    raise RuntimeError("네온 본문 확대 실패")
                try:
                    surface = p.TTF_RenderUTF8_Blended(font, text.encode("utf-8"), p.SDL_Color(*self.rgba(color)))
                finally:
                    if p.TTF_SetFontSize(font, size) != 0:
                        raise RuntimeError("네온 본문 글꼴 크기 복원 실패")
            if not surface:
                raise RuntimeError("네온 본문 생성 실패")
            try:
                texture = p.SDL_CreateTextureFromSurface(p.renderer, surface)
            finally:
                p.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError("네온 본문 텍스처 생성 실패")
            if p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear) != 0:
                p.SDL_DestroyTexture(texture)
                raise RuntimeError("네온 본문 필터 설정 실패")
            self.textures[key] = (texture, width, height)
            if len(self.textures) > 256:
                _, (old, _, _) = self.textures.popitem(last=False)
                p.SDL_DestroyTexture(old)
        self.textures.move_to_end(key)
        texture, width, height = self.textures[key]
        p.SDL_SetTextureAlphaMod(texture, self.rgba(color, opacity)[3])
        destination = p.SDL_FRect(x, y, width, height)
        if p.SDL_RenderCopyF(p.renderer, texture, None, byref(destination)) != 0:
            raise RuntimeError("네온 본문 표시 실패")

    def neon_text(self, text, x, y, role, color, opacity=1, *, glow_color, radius_pixels=4, glow_opacity=0.12,
                  glow_passes=1, bold=False):
        """캐시한 가우시안 광을 먼저 그리고 원래 글자를 같은 위치에 겹친다."""
        if opacity <= 0 or not text:
            return
        if glow_opacity > 0 and radius_pixels > 0:
            for _ in range(glow_passes):
                self._draw_neon_glow(text, x, y, role, glow_color, opacity * glow_opacity, radius_pixels, bold=bold)
        self._draw_neon_core(text, x, y, role, color, opacity, bold=bold)

    def _scanline_texture(self, height, spacing, thickness, color):
        """위상과 무관한 세로 반복 패턴. 두 배 해상도로 만들어 선형 보간한다."""
        p = self.pico
        # 높이를 64/128/256/512… 단위로 묶어 패턴 재생성을 막는다.
        logical_height = 1 << max(6, ceil(log2(height + spacing)))
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
        """화면 좌표의 반복 패턴과 밝은 띠를 패널 내부에만 그린다."""
        if opacity <= 0:
            return
        p = self.pico
        sy = c_float()
        sx = c_float()
        viewport = p.SDL_Rect()
        output_width, output_height = c_int(), c_int()
        p.SDL_RenderGetScale(p.renderer, byref(sx), byref(sy))
        p.SDL_RenderGetViewport(p.renderer, byref(viewport))
        p.SDL_GetRendererOutputSize(p.renderer, byref(output_width), byref(output_height))
        screen_y = lambda y: (y + viewport.y) * sy.value
        left = min(x for x, _ in surface)
        width = max(x for x, _ in surface) - left
        visible_surface = clip_panel_band(surface, -viewport.y, output_height.value / sy.value)
        polygons = (visible_surface,)
        if bright_band is not None:
            band_top, band_height = bright_band
            local_top = band_top / sy.value - viewport.y
            local_height = band_height / sy.value
            polygons = tuple(clip_panel_band(visible_surface, local_top + index * local_height / 2, local_height / 2)
                             for index in range(2))
        polygons = tuple(polygon for polygon in polygons if len(polygon) >= 3)
        if not polygons:
            return
        texture, texture_height = self._scanline_texture(output_height.value, spacing_pixels, thickness_pixels, color)
        p.SDL_SetTextureAlphaMod(texture, 255)
        offset = spacing_pixels - offset_pixels % spacing_pixels
        for polygon in polygons:
            vertices = []
            for x, y in polygon:
                weight = 1
                if bright_band is not None:
                    weight = max(0, 1 - abs((screen_y(y) - band_top - band_height / 2) / (band_height / 2)))
                tint = p.SDL_Color(255, 255, 255, self.rgba(color, opacity * weight)[3])
                vertices.append(p.SDL_Vertex(p.SDL_FPoint(x, y), tint,
                                             p.SDL_FPoint((x - left) / width, (screen_y(y) + offset) / texture_height)))
            # 사각형 복사 경로를 피하고 배율이 달라도 UV 위상을 유지한다.
            for index in range(1, len(vertices) - 1):
                triangle = (p.SDL_Vertex * 3)(vertices[0], vertices[index], vertices[index + 1])
                if p.SDL_RenderGeometry(p.renderer, texture, triangle, 3, None, 0) != 0:
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

    @contextmanager
    def directional_blur(self, bounds, displacement, strength, samples=33):
        """현재 카드 한 장을 같은 화면 좌표에 렌더한 뒤 연속 방향성 필터로 합성한다."""
        from ferrial_drive.rendering.canvas import renderer_info
        if strength <= 0 or renderer_info(self.pico).name != 'opengl':
            yield
            return
        p = self.pico
        scale, viewport_values, output_size, clipping = self.draw_transform()
        if self.motion_sampler is None:
            from ferrial_drive.rendering.directional_blur import DirectionalBlurSampler
            self.motion_sampler = DirectionalBlurSampler(p)
        if self.motion_size != output_size:
            if self.motion_texture:
                p.SDL_DestroyTexture(self.motion_texture)
                self.motion_texture = None
            texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA8888,
                                          p.SDL_TEXTUREACCESS_TARGET, *output_size)
            if not texture:
                raise RuntimeError('모션 블러 대상 텍스처 생성 실패')
            p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear)
            self.motion_texture, self.motion_size = texture, output_size
        target = p.SDL_GetRenderTarget(p.renderer)
        viewport = p.SDL_Rect(*viewport_values)
        clip = p.SDL_Rect(*clipping) if clipping is not None else None
        blend = c_int()
        rgba = [c_ubyte() for _ in range(4)]
        p.SDL_GetRenderDrawBlendMode(p.renderer, byref(blend))
        p.SDL_GetRenderDrawColor(p.renderer, *(byref(value) for value in rgba))
        try:
            if p.SDL_SetRenderTarget(p.renderer, self.motion_texture) != 0:
                raise RuntimeError('모션 블러 대상 연결 실패')
            p.SDL_SetRenderDrawColor(p.renderer, 0, 0, 0, 0)
            p.SDL_RenderClear(p.renderer)
            p.SDL_RenderSetScale(p.renderer, *scale)
            p.SDL_RenderSetViewport(p.renderer, byref(viewport))
            p.SDL_RenderSetClipRect(p.renderer, byref(clip) if clip is not None else None)
            yield
        finally:
            p.SDL_SetRenderTarget(p.renderer, target)
            p.SDL_RenderSetScale(p.renderer, *scale)
            p.SDL_RenderSetViewport(p.renderer, byref(viewport))
            p.SDL_RenderSetClipRect(p.renderer, byref(clip) if clip is not None else None)
            p.SDL_SetRenderDrawBlendMode(p.renderer, blend.value)
            p.SDL_SetRenderDrawColor(p.renderer, *(value.value for value in rgba))
        sx, sy = scale
        vx, vy, _, _ = viewport_values
        pad_x, pad_y = abs(displacement[0]) + 8, abs(displacement[1]) + 8
        left = max(0, floor((bounds.x - pad_x + vx) * sx))
        top = max(0, floor((bounds.y - pad_y + vy) * sy))
        right = min(output_size[0], ceil((bounds.x + bounds.width + pad_x + vx) * sx))
        bottom = min(output_size[1], ceil((bounds.y + bounds.height + pad_y + vy) * sy))
        if right <= left or bottom <= top:
            return
        source = p.SDL_Rect(left, top, right - left, bottom - top)
        # 이미 화면 배율로 그린 레이어는 화면 픽셀에 1:1로 합성한다.
        # 논리 좌표로 되돌려 재확대하면 SDL viewport의 정수 반올림과 겹쳐
        # 가로 블러에서도 세로 방향으로 소수 픽셀만큼 재필터링된다.
        destination = p.SDL_FRect(left, top, source.w, source.h)
        try:
            p.SDL_RenderSetScale(p.renderer, 1, 1)
            p.SDL_RenderSetViewport(p.renderer, None)
            screen_clip = None
            if clipping is not None:
                cx, cy, cw, ch = clipping
                screen_clip = p.SDL_Rect(round((cx + vx) * sx), round((cy + vy) * sy),
                                         round(cw * sx), round(ch * sy))
            p.SDL_RenderSetClipRect(p.renderer, byref(screen_clip) if screen_clip is not None else None)
            self.motion_sampler.draw_blurred(self.motion_texture, output_size, source, destination,
                                             (displacement[0] * sx, displacement[1] * sy), strength, samples)
        finally:
            p.SDL_RenderSetScale(p.renderer, *scale)
            p.SDL_RenderSetViewport(p.renderer, byref(viewport))
            p.SDL_RenderSetClipRect(p.renderer, byref(clip) if clip is not None else None)

    def prepare_compute_particles(self, system, *, profiling=False):
        if self.compute_particles is not None and self.compute_particles.system is system:
            if profiling:
                self.compute_particles.profiling = True
            return self.compute_particles
        import ctypes as ct
        import os
        from ferrial_drive.rendering.canvas import renderer_info
        if renderer_info(self.pico).name != 'opengl':
            raise RuntimeError('Compute 파티클은 OpenGL 4.3 이상이 필요하다.')
        prototype = ct.WINFUNCTYPE if os.name == 'nt' else ct.CFUNCTYPE
        query = prototype(ct.c_char_p, ct.c_uint)(self.pico.SDL_GL_GetProcAddress(b'glGetString'))
        version = query(0x1F02).decode().split()[0].split('.')
        if not all(v.isdigit() for v in version[:2]) or tuple(map(int, version[:2])) < (4, 3):
            raise RuntimeError('Compute 파티클은 OpenGL 4.3 이상이 필요하다.')
        if self.compute_particles is not None and self.compute_particles.system is not system:
            self.compute_particles.close()
            self.compute_particles = None
        if self.compute_particles is None:
            from ferrial_drive.rendering.compute_particles import ComputeParticles
            self.compute_particles = ComputeParticles(self.pico, system, profiling=profiling)
        return self.compute_particles

    def draw_compute_particles(self, system, settings, color, core_color, opacity):
        backend = self.prepare_compute_particles(system)
        scale, _, _, _ = self.draw_transform()
        backend.render(settings, tuple(v / 255 for v in self.rgba(color, opacity)),
                       tuple(v / 255 for v in self.rgba(core_color, opacity)), scale)

    def draw_instanced_particles(self, trails, settings, color, core_color, opacity):
        from ferrial_drive.rendering.canvas import renderer_info
        if settings.get("renderer") != "instanced" or renderer_info(self.pico).name != "opengl":
            return False
        if self.particle_instancing_supported is None:
            import ctypes as ct
            import os
            prototype = ct.WINFUNCTYPE if os.name == "nt" else ct.CFUNCTYPE
            query = prototype(ct.c_char_p, ct.c_uint)(self.pico.SDL_GL_GetProcAddress(b"glGetString"))
            version = query(0x1F02).decode().split()[0].split(".")
            self.particle_instancing_supported = (len(version) >= 2 and all(v.isdigit() for v in version[:2])
                                                  and tuple(map(int, version[:2])) >= (3, 3))
        if not self.particle_instancing_supported:
            return False
        if not trails:
            if self.particle_instances is not None:
                self.particle_instances.slots.clear()
            return True
        if self.particle_instances is None:
            from ferrial_drive.rendering.instanced_particles import InstancedParticles
            self.particle_instances = InstancedParticles(self.pico)
        scale, _, _, _ = self.draw_transform()
        base = tuple(value / 255 for value in self.rgba(color, opacity))
        core = tuple(value / 255 for value in self.rgba(core_color, opacity))
        self.particle_instances.render(trails, settings, base, core, scale)
        return True

    def particle_quads(self, quads):
        """공용 오브/Trail 텍스처 하나로 모든 파티클의 사각형을 한 번에 그린다."""
        if not quads:
            return
        p = self.pico
        from .particle_texture import ATLAS_SIZE, CELL_SIZE, build_particle_atlas
        if self.particle_texture is None:
            width, height = ATLAS_SIZE
            surface = p.SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, p.SDL_PIXELFORMAT_RGBA32)
            if not surface:
                raise RuntimeError("파티클 아틀라스 surface 생성 실패")
            try:
                pixels = build_particle_atlas()
                if p.SDL_LockSurface(surface) != 0:
                    raise RuntimeError("파티클 아틀라스 surface 잠금 실패")
                try:
                    for row in range(height):
                        memmove(surface.contents.pixels + row * surface.contents.pitch,
                                pixels[row * width * 4:(row + 1) * width * 4], width * 4)
                finally:
                    p.SDL_UnlockSurface(surface)
                texture = p.SDL_CreateTextureFromSurface(p.renderer, surface)
            finally:
                p.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError("파티클 아틀라스 GPU 업로드 실패")
            if (p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_BLEND) != 0
                    or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear) != 0):
                p.SDL_DestroyTexture(texture)
                raise RuntimeError("파티클 텍스처 필터 설정 실패")
            self.particle_texture = texture
        # SDL 구조체 객체를 꼭짓점마다 여러 개 만들지 않고 연속 버퍼에 채운다.
        data = bytearray(len(quads) * 4 * PARTICLE_VERTEX.size)
        vertices = (p.SDL_Vertex * (len(quads) * 4)).from_buffer(data)
        index_count = len(quads) * 6
        if self.particle_indices is None or len(self.particle_indices) < index_count:
            self.particle_indices = (c_int * index_count)(*(index * 4 + corner
                                      for index in range(len(quads)) for corner in (0, 1, 2, 0, 2, 3)))
        uv_regions = []
        for region in (0, 1):
            u0, u1 = (region * CELL_SIZE + 0.5) / ATLAS_SIZE[0], ((region + 1) * CELL_SIZE - 0.5) / ATLAS_SIZE[0]
            v0, v1 = 0.5 / CELL_SIZE, 1 - 0.5 / CELL_SIZE
            uv_regions.append(((u0, v0), (u1, v0), (u1, v1), (u0, v1)))
        for index, (points, colors, region) in enumerate(quads):
            # 셀 가장자리의 반 texel을 안쪽으로 옮겨 인접 셀 혼입을 막는다.
            for corner, (point, color, uv) in enumerate(zip(points, colors, uv_regions[region])):
                PARTICLE_VERTEX.pack_into(data, (index * 4 + corner) * PARTICLE_VERTEX.size, *point, *color, *uv)
        if p.SDL_RenderGeometry(p.renderer, self.particle_texture, vertices, len(vertices), self.particle_indices, index_count) != 0:
            raise RuntimeError("파티클 묶음 렌더 실패: " + p.SDL_GetError().decode("utf-8", errors="replace"))

    def close(self):
        if self.compute_particles is not None:
            self.compute_particles.close()
            self.compute_particles = None
        if self.particle_instances is not None:
            self.particle_instances.close()
            self.particle_instances = None
        self.particle_indices = None
        if self.particle_texture:
            self.pico.SDL_DestroyTexture(self.particle_texture)
            self.particle_texture = None
        if self.motion_sampler is not None:
            self.motion_sampler.close()
            self.motion_sampler = None
        if self.motion_texture:
            self.pico.SDL_DestroyTexture(self.motion_texture)
            self.motion_texture = None
            self.motion_size = None
        for texture, _, _, _ in self.neon_textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.neon_textures.clear()
        for texture in self.grain_textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.grain_textures.clear()
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
    def translated(self, dx, dy):
        p = self.pico
        viewport = p.SDL_Rect()
        p.SDL_RenderGetViewport(p.renderer, byref(viewport))
        target = p.SDL_Rect(viewport.x + round(dx), viewport.y + round(dy), viewport.w, viewport.h)
        try:
            p.SDL_RenderSetViewport(p.renderer, byref(target))
            yield
        finally:
            p.SDL_RenderSetViewport(p.renderer, byref(viewport))

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
                    scale_x=1, scale_y=1, clip_rect=None, bold=False):
        """평면에서 글자를 자른 뒤 투영해 회전 카운터의 경계를 유지한다."""
        if not text or opacity <= 0 or scale_x <= 0 or scale_y <= 0:
            return
        texture, width, height = self._text_texture(text, role, color, bold=bold)
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

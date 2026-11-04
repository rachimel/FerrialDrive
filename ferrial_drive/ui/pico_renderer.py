"""Pico2D가 연 SDL 렌더러에 그리는 어댑터. 라이브러리 원본은 수정하지 않는다."""

from collections import OrderedDict
from contextlib import contextmanager
from ctypes import byref, c_int, memmove
from functools import lru_cache
from math import ceil, cos, exp, floor, sin, sqrt, tau
from pathlib import Path

from .components import Rect
from .weapon_icons import weapon_icon_pixels


@lru_cache(maxsize=64)
def _rgb(color):
    value = color.removeprefix("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


@lru_cache(maxsize=32)
def _ring_spans(radius, thickness, fraction_x, fraction_y):
    """정수 이동과 무관한 픽셀 범위를 저장하고 소수점 중심은 구분한다."""
    outer = radius + thickness / 2
    inner = max(0.0, radius - thickness / 2)
    rows = []
    for pixel_y in range(ceil(fraction_y - outer - 0.5), floor(fraction_y + outer - 0.5) + 1):
        dy = pixel_y + 0.5 - fraction_y
        outer_span = sqrt(max(0.0, outer * outer - dy * dy))
        left = ceil(fraction_x - outer_span - 0.5)
        right = floor(fraction_x + outer_span - 0.5)
        spans = ((left, right),)
        if abs(dy) < inner:
            inner_span = sqrt(inner * inner - dy * dy)
            left_end = floor(fraction_x - inner_span - 0.5)
            right_start = max(left_end + 1, ceil(fraction_x + inner_span - 0.5))
            spans = ((left, left_end), (right_start, right))
        rows.extend((start, pixel_y, end) for start, end in spans if start <= end)
    return tuple(rows)


class PicoRenderer:
    def __init__(self, font_paths: dict[str, Path], font_sizes: dict[str, int]):
        import pico2d.pico2d as pico

        self.pico = pico
        self.fonts = {}
        self.textures = OrderedDict()
        self.panel_textures = OrderedDict()
        self.images = OrderedDict()
        self.weapon_icons = {}
        self.measurements = OrderedDict()
        self.ascents = {}
        try:
            for role, size in font_sizes.items():
                self.fonts[role] = pico.load_font(str(font_paths[role]), size)
        except BaseException:
            self.close()
            raise
        pico.SDL_SetRenderDrawBlendMode(pico.renderer, pico.SDL_BLENDMODE_BLEND)

    @staticmethod
    def rgba(color: str, opacity: float = 1) -> tuple[int, int, int, int]:
        return (*_rgb(color), round(max(0.0, min(1.0, opacity)) * 255))

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

    @contextmanager
    def clip(self, rect):
        """패널 경계에서 그리기를 잘라내고 중첩·예외 시에도 이전 영역을 복원한다."""
        pico = self.pico
        previous = pico.SDL_Rect()
        enabled = pico.SDL_RenderIsClipEnabled(pico.renderer)
        pico.SDL_RenderGetClipRect(pico.renderer, byref(previous))
        left, top = ceil(rect.x), ceil(rect.y)
        right, bottom = floor(rect.x + rect.width), floor(rect.y + rect.height)
        if enabled:
            left, top = max(left, previous.x), max(top, previous.y)
            right = min(right, previous.x + previous.w)
            bottom = min(bottom, previous.y + previous.h)
        target = pico.SDL_Rect(left, top, max(0, right - left), max(0, bottom - top))
        if pico.SDL_RenderSetClipRect(pico.renderer, byref(target)) != 0:
            raise RuntimeError("패널 클리핑 영역 설정 실패")
        try:
            yield
        finally:
            pico.SDL_RenderSetClipRect(pico.renderer, byref(previous) if enabled else None)

    def metallic_rect(self, rect: Rect, color: str, opacity: float = 1, *,
                      contrast: float = 0.28, highlight_center=(0.5, 1.15),
                      highlight_radius=(1.25, 1.3), corner_cut_ratio=(0.0, 0.0)):
        """넓은 방사형 광택을 저장해 패널마다 한 번의 복사로 그린다."""
        if opacity <= 0 or rect.width <= 0 or rect.height <= 0:
            return
        center_x, center_y = highlight_center
        radius_x, radius_y = highlight_radius
        cut_x, cut_y = corner_cut_ratio
        key = (color, contrast, center_x, center_y, radius_x, radius_y, cut_x, cut_y)
        pico = self.pico
        if key not in self.panel_textures:
            width, height = 128, 256
            surface = pico.SDL_CreateRGBSurfaceWithFormat(
                0, width, height, 32, pico.SDL_PIXELFORMAT_RGBA32)
            if not surface:
                raise RuntimeError("금속 패널 surface 생성 실패")
            try:
                if pico.SDL_LockSurface(surface) != 0:
                    raise RuntimeError("금속 패널 surface 잠금 실패")
                try:
                    base = _rgb(color)
                    horizontal = tuple(((x / (width - 1) - center_x) / radius_x) ** 2
                                       for x in range(width))
                    for y in range(height):
                        # 왼쪽 위와 오른쪽 아래 모서리를 같은 비율로 자른다.
                        left_edge = (cut_x * width * max(0.0, 1 - (y + 0.5) / (cut_y * height))
                                     if cut_y > 0 else 0.0)
                        right_edge = width - (cut_x * width * max(
                            0.0, 1 - (height - y - 0.5) / (cut_y * height)) if cut_y > 0 else 0.0)
                        vertical = ((y / (height - 1) - center_y) / radius_y) ** 2
                        row = bytearray()
                        for x, distance_x in enumerate(horizontal):
                            # 아래쪽 중심에서 부드럽게 어두워지는 넓은 광택을 만든다.
                            light = exp(-2 * (distance_x + vertical))
                            shade = 1 + contrast * (2 * light - 1)
                            row.extend(max(0, min(255, round(channel * shade))) for channel in base)
                            coverage = max(0.0, min(1.0, x + 1 - left_edge, right_edge - x))
                            row.append(round(255 * coverage))
                        memmove(surface.contents.pixels + y * surface.contents.pitch,
                                bytes(row), width * 4)
                finally:
                    pico.SDL_UnlockSurface(surface)
                texture = pico.SDL_CreateTextureFromSurface(pico.renderer, surface)
            finally:
                pico.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError("금속 패널 텍스처 생성 실패")
            pico.SDL_SetTextureBlendMode(texture, pico.SDL_BLENDMODE_BLEND)
            self.panel_textures[key] = texture
            if len(self.panel_textures) > 8:
                _, old_texture = self.panel_textures.popitem(last=False)
                pico.SDL_DestroyTexture(old_texture)
        self.panel_textures.move_to_end(key)
        texture = self.panel_textures[key]
        pico.SDL_SetTextureAlphaMod(texture, self.rgba(color, opacity)[3])
        destination = pico.SDL_Rect(round(rect.x), round(rect.y), round(rect.width), round(rect.height))
        pico.SDL_RenderCopy(pico.renderer, texture, None, byref(destination))

    def circle(self, x: float, y: float, radius: float, color: str, opacity: float = 1):
        segments = max(24, round(radius * 2))
        for index in range(segments):
            first, second = tau * index / segments, tau * (index + 1) / segments
            self.line(x + cos(first) * radius, y + sin(first) * radius,
                      x + cos(second) * radius, y + sin(second) * radius, color, opacity)

    def ring(self, x, y, radius, thickness, color, opacity=1):
        """동심원 띠를 한 번씩 채워 두꺼운 링의 알파 중첩을 막는다."""
        if opacity <= 0:
            return
        base_x, base_y = floor(x), floor(y)
        spans = _ring_spans(radius, thickness, x - base_x, y - base_y)
        pico = self.pico
        pico.SDL_SetRenderDrawColor(pico.renderer, *self.rgba(color, opacity))
        for start, pixel_y, end in spans:
            pico.SDL_RenderDrawLine(pico.renderer, base_x + start, base_y + pixel_y,
                                    base_x + end, base_y + pixel_y)

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
        key = (text, role)
        if key in self.measurements:
            self.measurements.move_to_end(key)
            return self.measurements[key]
        width, height = c_int(), c_int()
        if self.pico.TTF_SizeUTF8(self.fonts[role].font, text.encode("utf-8"),
                                  byref(width), byref(height)) != 0:
            raise RuntimeError("텍스트 크기를 계산할 수 없다.")
        size = (width.value, height.value)
        self.measurements[key] = size
        if len(self.measurements) > 512:
            self.measurements.popitem(last=False)
        return size

    def text_size(self, text: str, role: str) -> tuple[int, int]:
        return self._measure(text, role)

    def text_ascent(self, role: str) -> int:
        if role not in self.ascents:
            self.ascents[role] = self.pico.TTF_FontAscent(self.fonts[role].font)
        return self.ascents[role]

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

    def image(self, path, rect, opacity=1, *, vertical_scale=1.0):
        """무기 이미지는 비율을 유지하며 영역 중앙에 맞춘다."""
        pico = self.pico
        key = str(Path(path).resolve())
        if key not in self.images:
            surface = pico.IMG_Load(key.encode("utf-8"))
            if not surface:
                raise RuntimeError(f"무기 이미지 로드 실패: {key}")
            try:
                width, height = surface.contents.w, surface.contents.h
                texture = pico.SDL_CreateTextureFromSurface(pico.renderer, surface)
            finally:
                pico.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError(f"무기 이미지 텍스처 생성 실패: {key}")
            pico.SDL_SetTextureBlendMode(texture, pico.SDL_BLENDMODE_BLEND)
            self.images[key] = (texture, width, height)
            if len(self.images) > 8:
                _, (old_texture, _, _) = self.images.popitem(last=False)
                pico.SDL_DestroyTexture(old_texture)
        self.images.move_to_end(key)
        texture, width, height = self.images[key]
        if vertical_scale <= 0:
            return
        scale = min(rect.width / width, rect.height / vertical_scale / height)
        draw_height = height * scale * vertical_scale
        destination = pico.SDL_Rect(round(rect.x + (rect.width - width * scale) / 2),
                                    round(rect.y + (rect.height - draw_height) / 2),
                                    round(width * scale), round(draw_height))
        pico.SDL_SetTextureAlphaMod(texture, self.rgba("#FFFFFF", opacity)[3])
        pico.SDL_RenderCopy(pico.renderer, texture, None, byref(destination))

    def weapon_silhouette(self, kind, rect, color, opacity, outline_color, outline_width):
        """부품별 반올림 대신 합쳐 둔 원본을 일정 비율로 그린다."""
        pico = self.pico
        key = (kind, color, outline_color, outline_width)
        if key not in self.weapon_icons:
            width, height, pixels = weapon_icon_pixels(kind, _rgb(color), _rgb(outline_color), outline_width)
            surface = pico.SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, pico.SDL_PIXELFORMAT_RGBA32)
            if not surface:
                raise RuntimeError("무기 실루엣 surface 생성 실패")
            try:
                if pico.SDL_LockSurface(surface) != 0:
                    raise RuntimeError("무기 실루엣 surface 잠금 실패")
                try:
                    for y in range(height):
                        row = bytes(pixels[y * width * 4:(y + 1) * width * 4])
                        memmove(surface.contents.pixels + y * surface.contents.pitch, row, width * 4)
                finally:
                    pico.SDL_UnlockSurface(surface)
                texture = pico.SDL_CreateTextureFromSurface(pico.renderer, surface)
            finally:
                pico.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError("무기 실루엣 텍스처 생성 실패")
            try:
                pico.SDL_SetTextureBlendMode(texture, pico.SDL_BLENDMODE_BLEND)
                if pico.SDL_SetTextureScaleMode(texture, pico.SDL_ScaleModeLinear) != 0:
                    raise RuntimeError("무기 실루엣 축소 필터 설정 실패")
            except BaseException:
                pico.SDL_DestroyTexture(texture)
                raise
            self.weapon_icons[key] = texture
        texture = self.weapon_icons[key]
        pico.SDL_SetTextureAlphaMod(texture, self.rgba(color, opacity)[3])
        target = pico.SDL_Rect(round(rect.x), round(rect.y), round(rect.width), round(rect.height))
        pico.SDL_RenderCopy(pico.renderer, texture, None, byref(target))

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
        for texture in self.weapon_icons.values():
            self.pico.SDL_DestroyTexture(texture)
        self.weapon_icons.clear()
        for texture, _, _ in self.images.values():
            self.pico.SDL_DestroyTexture(texture)
        self.images.clear()
        for texture in self.panel_textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.panel_textures.clear()
        for texture, _, _ in self.textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.textures.clear()
        for font in self.fonts.values():
            self.pico.TTF_CloseFont(font.font)
        self.fonts.clear()
        self.measurements.clear()
        self.ascents.clear()

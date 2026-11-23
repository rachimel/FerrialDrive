"""HUD 글자 표면을 공통 텍스처에 배치한다."""

from ctypes import byref, c_char_p, string_at


class HudTextAtlas:
    """같은 배치에 단색 도형이 필요하면 마지막 행의 텍셀을 예약한다."""
    def __init__(self, pico, flush, size=1024, *, solid_texel=False):
        self.pico, self.flush, self.size = pico, flush, size
        self.content_height = size - int(solid_texel)
        self.texture = None
        self.entries = {}
        self.x = self.y = self.row_height = 0
        self.hits = self.uploads = self.resets = 0

    def get(self, key, render_surface):
        rect = self.entries.get(key)
        if rect is not None:
            self.hits += 1
            return rect
        p = self.pico
        surface = render_surface()
        try:
            width, height = surface.contents.w, surface.contents.h
            if min(width, height) < 1 or width + 2 > self.size or height + 2 > self.content_height:
                return None
            packed = self._padded_pixels(surface, width, height)
        finally:
            p.SDL_FreeSurface(surface)
        if self.texture is None:
            self._allocate()
        span, rows = width + 2, height + 2
        if self.x + span > self.size:
            self.x, self.y, self.row_height = 0, self.y + self.row_height, 0
        if self.y + rows > self.content_height:
            self.flush()
            self.entries.clear()
            self.x = self.y = self.row_height = 0
            self.resets += 1
        target = p.SDL_Rect(self.x, self.y, span, rows)
        if p.SDL_UpdateTexture(self.texture, byref(target), c_char_p(packed), span * 4):
            raise RuntimeError("HUD 텍스트 아틀라스 업로드 실패")
        rect = self.x + 1, self.y + 1, width, height
        self.entries[key] = rect
        self.x += span
        self.row_height = max(self.row_height, rows)
        self.uploads += 1
        return rect

    def _allocate(self):
        p = self.pico
        texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_STATIC,
                                      self.size, self.size)
        if not texture:
            raise RuntimeError("HUD 텍스트 아틀라스 생성 실패")
        if (p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_BLEND)
                or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear)):
            p.SDL_DestroyTexture(texture)
            raise RuntimeError("HUD 텍스트 아틀라스 필터 설정 실패")
        if self.content_height < self.size:
            texel = p.SDL_Rect(0, self.content_height, 1, 1)
            if p.SDL_UpdateTexture(texture, byref(texel), c_char_p(b"\xff" * 4), 4):
                p.SDL_DestroyTexture(texture)
                raise RuntimeError("아틀라스 단색 텍셀 업로드 실패")
        self.texture = texture

    def solid_uv(self):
        if self.content_height == self.size:
            raise RuntimeError("단색 텍셀을 예약한 아틀라스가 필요하다.")
        if self.texture is None:
            self._allocate()
        return (0.5 / self.size, (self.content_height + 0.5) / self.size)

    def _padded_pixels(self, surface, width, height):
        p = self.pico
        rgba_surface = p.SDL_ConvertSurfaceFormat(surface, p.SDL_PIXELFORMAT_RGBA32, 0)
        if not rgba_surface:
            raise RuntimeError("HUD 텍스트 표면 변환 실패")
        try:
            pixels = rgba_surface.contents
            rows = []
            for y in range(height):
                row = string_at(pixels.pixels + y * pixels.pitch, width * 4)
                rows.append(row[:4] + row + row[-4:])
            return b"".join((rows[0], *rows, rows[-1]))
        finally:
            p.SDL_FreeSurface(rgba_surface)

    def close(self):
        if self.texture:
            self.pico.SDL_DestroyTexture(self.texture)
            self.texture = None
        self.entries.clear()
        self.x = self.y = self.row_height = 0

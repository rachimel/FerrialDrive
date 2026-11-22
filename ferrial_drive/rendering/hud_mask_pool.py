"""HUD 마스크가 빠져나간 SDL 타깃을 같은 크기의 마스크에 재사용한다."""

from collections import OrderedDict
from ctypes import byref, c_int


class HudMaskPool:
    def __init__(self, pico, *, max_bytes=2 * 1024**2, max_targets=24):
        self.pico = pico
        self.max_bytes, self.max_targets = max_bytes, max_targets
        self.available = OrderedDict()
        self.storage_bytes = 0
        self.reuses = 0

    def take(self, width, height):
        p = self.pico
        for key in reversed(self.available):
            if key[:2] != (width, height):
                continue
            texture = self.available.pop(key)
            self.storage_bytes -= width * height * 4
            if p.SDL_SetTextureColorMod(texture, 255, 255, 255) or p.SDL_SetTextureAlphaMod(texture, 255):
                p.SDL_DestroyTexture(texture)
                raise RuntimeError("재사용 HUD 마스크의 색 상태를 초기화할 수 없다.")
            self.reuses += 1
            return texture
        return p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA8888, p.SDL_TEXTUREACCESS_TARGET,
                                   width, height)

    def store(self, texture):
        p = self.pico
        width, height = c_int(), c_int()
        if p.SDL_QueryTexture(texture, None, None, byref(width), byref(height)):
            p.SDL_DestroyTexture(texture)
            return
        cost = width.value * height.value * 4
        if cost > self.max_bytes:
            p.SDL_DestroyTexture(texture)
            return
        while self.available and (self.storage_bytes + cost > self.max_bytes or
                                  len(self.available) >= self.max_targets):
            (w, h, _), old = self.available.popitem(last=False)
            self.storage_bytes -= w * h * 4
            p.SDL_DestroyTexture(old)
        self.available[(width.value, height.value, id(texture))] = texture
        self.storage_bytes += cost

    def close(self):
        for texture in self.available.values():
            self.pico.SDL_DestroyTexture(texture)
        self.available.clear()
        self.storage_bytes = 0

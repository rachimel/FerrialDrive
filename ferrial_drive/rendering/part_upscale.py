"""네이티브 크기로 합성한 파츠를 알파 보존 Bicubic으로 확대한다."""

from contextlib import contextmanager
import ctypes as ct
from math import ceil

from .bicubic import acquire_sampler


@contextmanager
def render_target(pico, texture):
    renderer = pico.renderer
    previous = pico.SDL_GetRenderTarget(renderer)
    rgba = tuple(ct.c_ubyte() for _ in range(4))
    pico.SDL_GetRenderDrawColor(renderer, *(ct.byref(channel) for channel in rgba))
    if previous:
        sx, sy = ct.c_float(), ct.c_float()
        viewport, clip = pico.SDL_Rect(), pico.SDL_Rect()
        pico.SDL_RenderGetScale(renderer, ct.byref(sx), ct.byref(sy))
        pico.SDL_RenderGetViewport(renderer, ct.byref(viewport))
        clipped = pico.SDL_RenderIsClipEnabled(renderer)
        if clipped:
            pico.SDL_RenderGetClipRect(renderer, ct.byref(clip))
    if pico.SDL_SetRenderTarget(renderer, texture):
        raise RuntimeError("플레이어 렌더 타깃을 연결할 수 없다.")
    try:
        pico.SDL_SetRenderDrawColor(renderer, 0, 0, 0, 0)
        pico.SDL_RenderClear(renderer)
        yield
    finally:
        pico.SDL_SetRenderTarget(renderer, previous)
        if previous:
            pico.SDL_RenderSetScale(renderer, sx.value, sy.value)
            pico.SDL_RenderSetViewport(renderer, ct.byref(viewport))
            pico.SDL_RenderSetClipRect(renderer, ct.byref(clip) if clipped else None)
        pico.SDL_SetRenderDrawColor(renderer, *(channel.value for channel in rgba))


class PartUpscaler:
    def __init__(self, pico, aa_mode="off"):
        self.pico = pico
        self.sampler = acquire_sampler(pico)
        if self.sampler is None:
            raise RuntimeError("플레이어 Bicubic 확대에 OpenGL 렌더러가 필요하다.")
        self.texture = None
        self.size = (0, 0)
        self.aa = None
        self.aa_draws = 0
        try:
            with self.prepare_aa(aa_mode) as apply:
                if apply is not None:
                    apply()
        except BaseException:
            self.close()
            raise

    @property
    def aa_mode(self):
        return "smaa" if self.aa is not None else "off"

    @property
    def aa_storage_bytes(self):
        return self.aa.storage_bytes if self.aa is not None else 0

    @contextmanager
    def prepare_aa(self, mode):
        if mode == self.aa_mode:
            yield None
            return
        candidate = None
        if mode == "smaa":
            from .smaa import Smaa1x
            candidate = Smaa1x(self.pico)
        elif mode != "off":
            raise ValueError("확대 안티앨리어싱은 off 또는 smaa여야 한다.")

        def apply():
            nonlocal candidate
            previous, self.aa, candidate = self.aa, candidate, None
            if previous is not None:
                previous.close()

        try:
            yield apply
        finally:
            if candidate is not None:
                candidate.close()

    @contextmanager
    def native_target(self, width, height):
        p = self.pico
        size = tuple(max(old, (required + 63) // 64 * 64)
                     for old, required in zip(self.size, (width, height), strict=True))
        if size != self.size:
            texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_TARGET, *size)
            if not texture:
                raise RuntimeError("플레이어 확대용 렌더 타깃을 만들 수 없다.")
            if self.texture:
                p.SDL_DestroyTexture(self.texture)
            self.texture, self.size = texture, size
        with render_target(p, self.texture):
            yield

    def draw(self, width, height, destination):
        p = self.pico
        source = p.SDL_Rect(0, 0, width, height)
        if self.aa is None:
            self.sampler.draw(self.texture, self.size, source, destination, premultiplied=True)
            return
        scale_x, scale_y = ct.c_float(), ct.c_float()
        p.SDL_RenderGetScale(p.renderer, ct.byref(scale_x), ct.byref(scale_y))
        pixels = max(1, ceil(destination.w * scale_x.value)), max(1, ceil(destination.h * scale_y.value))
        self.aa.draw(self.sampler, self.texture, self.size, source, destination, pixels, render_target)
        self.aa_draws += 1

    def close(self):
        if self.aa is not None:
            self.aa.close()
            self.aa = None
        if self.texture:
            self.pico.SDL_DestroyTexture(self.texture)
            self.texture = None
        self.sampler.release()

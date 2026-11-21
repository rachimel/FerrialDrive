"""네이티브 크기로 합성한 파츠를 알파 보존 Bicubic으로 확대한다."""

from contextlib import contextmanager
import ctypes as ct
from math import ceil

from .bicubic import FRAGMENT_SHADER, acquire_sampler
from .gl_pass import COLOR_AND_SCISSOR_STATE
from .instanced_quads import InstancedQuads


PART_UPSCALE_BORDER = 2


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
            with self.sampler.batch(raster_attributes=COLOR_AND_SCISSOR_STATE):
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


class PartEchoTarget:
    """잔상 PBR의 작은 프리멀티플라이 타깃을 반복해서 사용한다."""

    def __init__(self, pico):
        self.pico = pico
        self.texture = None
        self.size = (0, 0)

    def draw(self, width, height, destination, paint):
        p = self.pico
        border = PART_UPSCALE_BORDER // 2
        inner = p.SDL_Rect(border, border, (width + 1) // 2, (height + 1) // 2)
        source = p.SDL_Rect(0, 0, inner.w + 2 * border, inner.h + 2 * border)
        size = tuple(max(old, (required + 31) // 32 * 32)
                     for old, required in zip(self.size, (source.w, source.h), strict=True))
        if size != self.size:
            texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_TARGET, *size)
            if not texture:
                raise RuntimeError("잔상 합성 타깃을 만들 수 없다.")
            blend = p.SDL_ComposeCustomBlendMode(p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
                p.SDL_BLENDOPERATION_ADD, p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
                p.SDL_BLENDOPERATION_ADD)
            if p.SDL_SetTextureBlendMode(texture, blend) or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear):
                p.SDL_DestroyTexture(texture)
                raise RuntimeError("잔상 합성 타깃 필터를 설정할 수 없다.")
            self.close()
            self.texture, self.size = texture, size
        with render_target(p, self.texture):
            paint(inner)
        if p.SDL_RenderCopy(p.renderer, self.texture, source, destination):
            raise RuntimeError("반해상도 잔상 그리기 실패")

    def close(self):
        if self.texture:
            self.pico.SDL_DestroyTexture(self.texture)
            self.texture = None
            self.size = (0, 0)


class PartSheetUpscaler:
    """네이티브 시트의 파츠를 영역별로 확대하고 시트 단위로 AA를 적용한다."""

    def __init__(self, pico):
        from .smaa import Smaa1x

        self.pico = pico
        fragment = FRAGMENT_SHADER.replace(b"uniform vec4 frameBounds;",
                                           b"flat in vec4 sourceBounds;\n#define frameBounds sourceBounds", 1)
        fragment = fragment.replace(b"varying vec2 texel;", b"in vec2 texel;", 1)
        self.sampler = InstancedQuads(pico, fragment_shader=fragment, per_instance_source=True,
                                      extra_uniforms=("artwork", "atlasSize", "modulation", "premultipliedSource"))
        try:
            self.aa = Smaa1x(pico, sheet=True)
        except BaseException:
            self.sampler.close()
            raise

    def draw(self, source, source_size, output, output_size, regions):
        sampler = self.sampler

        def paint_color():
            with sampler.batch():
                if self.pico.SDL_GL_BindTexture(source, None, None):
                    raise RuntimeError("적 확대 시트 OpenGL 연결 실패")
                sampler.glUniform1i(sampler.uniforms["artwork"], 0)
                sampler.glUniform2f(sampler.uniforms["atlasSize"], *source_size)
                sampler.glUniform4f(sampler.uniforms["modulation"], 1, 1, 1, 1)
                sampler.glUniform1f(sampler.uniforms["premultipliedSource"], 1)
                sampler.draw_rectangles(regions)

        self.aa.draw_sheet(paint_color, output, [destination for _, destination in regions], output_size, render_target)

    def close(self):
        self.aa.close()
        self.sampler.close()

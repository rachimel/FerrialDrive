"""근거리 적 시트의 합성·확대를 SDL 사이의 한 OpenGL 구간에서 실행한다."""

from contextlib import contextmanager
import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from .atlas_texture_cache import AtlasTextureBindings
from .smaa_sheet_layers import SmaaSheetLayers


DRAW_FRAMEBUFFER = 0x8CA9
COLOR_ATTACHMENT = 0x8CE0
TEXTURE_2D = 0x0DE1
RASTER_STATE = 0x00004000 | 0x00080000 | 0x00000800 | 0x00002000


class EnemyGlSheet:
    use_smaa_layers = True

    def __init__(self, pico):
        self.pico = pico
        self.textures = ()
        self.targets = {}
        self.size = None
        self.clear_color = (ct.c_float * 4)()
        self.smaa_layers = None
        u, i, ptr = ct.c_uint, ct.c_int, ct.c_void_p
        for name, result, args in (
            ("glGenFramebuffers", None, [i, ptr]), ("glDeleteFramebuffers", None, [i, ptr]),
            ("glBindFramebuffer", None, [u, u]),
            ("glFramebufferTexture2D", None, [u, u, u, u, i]),
            ("glCheckFramebufferStatus", u, [u]), ("glClearBufferfv", None, [u, i, ptr]),
            ("glColorMask", None, [ct.c_ubyte] * 4),
        ):
            setattr(self, name, bind_gl(pico, name, result, args))
        if self.use_smaa_layers:
            try:
                self.smaa_layers = SmaaSheetLayers(pico)
            except RuntimeError:
                pass

    def _prepare_targets(self, sampler, textures, smaa_size):
        layer_names = {}
        if self.smaa_layers is not None and smaa_size:
            self.smaa_layers.reserve(sampler, smaa_size)
            layer_names = {id(key): name for key, name in zip(self.smaa_layers.keys, self.smaa_layers.names[1:])}
            textures = (*textures, *self.smaa_layers.keys)
        if len(textures) == len(self.textures) and all(new is old for new, old in zip(textures, self.textures)):
            return
        self._release_targets()
        old = sampler.integer(0x8069)
        try:
            for texture in textures:
                name = layer_names.get(id(texture))
                if name is None:
                    if self.pico.SDL_GL_BindTexture(texture, None, None):
                        raise RuntimeError("적 시트 SDL 텍스처를 연결할 수 없다.")
                    name = sampler.integer(0x8069)
                framebuffer = ct.c_uint()
                self.glGenFramebuffers(1, ct.byref(framebuffer))
                if not framebuffer.value:
                    raise RuntimeError("적 시트 OpenGL 프레임버퍼를 만들 수 없다.")
                self.targets[id(texture)] = name, framebuffer
            for name, framebuffer in self.targets.values():
                self.glBindFramebuffer(DRAW_FRAMEBUFFER, framebuffer.value)
                self.glFramebufferTexture2D(DRAW_FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE_2D, name, 0)
                if self.glCheckFramebufferStatus(DRAW_FRAMEBUFFER) != 0x8CD5:
                    raise RuntimeError("적 시트 OpenGL 프레임버퍼가 완전하지 않다.")
        except BaseException:
            self._release_targets()
            raise
        finally:
            sampler.glBindTexture(TEXTURE_2D, old)
        self.textures = textures

    @contextmanager
    def frame(self, sampler, textures, *, smaa_size=None):
        p = self.pico
        p.SDL_RenderFlush(p.renderer)
        framebuffer = sampler.integer(0x8CA6)
        program, active = sampler.integer(0x8B8D), sampler.integer(0x84E0)
        with sampler._preserve_raster_attributes(RASTER_STATE):
            sampler.glActiveTexture(0x84C0)
            try:
                self._prepare_targets(sampler, textures, smaa_size)
                self.sampler = sampler
                with AtlasTextureBindings(sampler) as bindings:
                    self.bindings = bindings
                    yield
            finally:
                self.glBindFramebuffer(DRAW_FRAMEBUFFER, framebuffer)
                sampler.glUseProgram(program)
                sampler.glActiveTexture(active)

    @contextmanager
    def target(self, texture, size):
        sampler = self.sampler
        self.size = size
        self.glBindFramebuffer(DRAW_FRAMEBUFFER, self.targets[id(texture)][1].value)
        sampler.glViewport(0, 0, *size)
        sampler.glDisable(0x0C11)
        self.glColorMask(1, 1, 1, 1)
        self.glClearBufferfv(0x1800, 0, self.clear_color)
        yield

    @contextmanager
    def batch(self, sampler):
        width, height = self.size
        sampler.output_size = self.size
        sampler.target_flip = -1
        sampler.glUseProgram(sampler.program)
        sampler.glEnable(0x0BE2)
        sampler.glBlendEquationSeparate(0x8006, 0x8006)
        sampler.glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)
        sampler.glUniform2f(sampler.uniforms["outputSize"], width, height)
        sampler.glUniform1f(sampler.uniforms["targetFlip"], -1)
        sampler.depth = 1
        sampler.direct_target = True
        try:
            yield
        finally:
            sampler.depth = 0
            sampler.direct_target = False

    @contextmanager
    def bind_input(self, sampler, unit, texture, *, sdl=False):
        name = self.targets[id(texture)][0] if sdl else texture
        self.bindings.apply(({},), (name,), first_unit=unit)
        yield

    def _release_targets(self):
        for _, framebuffer in self.targets.values():
            self.glDeleteFramebuffers(1, ct.byref(framebuffer))
        self.targets.clear()
        self.textures = ()

    def close(self):
        self._release_targets()
        if self.smaa_layers is not None:
            self.smaa_layers.close()

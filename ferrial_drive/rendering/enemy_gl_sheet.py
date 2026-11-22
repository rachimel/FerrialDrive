"""한 교전의 근거리 적 시트가 공유하는 OpenGL 상태와 타깃."""

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
        self.targets = {}
        self.intermediate = ()
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

    def _prepare_targets(self, textures, smaa_size, intermediate):
        sampler = self.sampler
        layers = self.smaa_layers
        if layers is not None and smaa_size is not None:
            layers.reserve(sampler, smaa_size)
            intermediate = layers.keys
        if intermediate and intermediate != self.intermediate:
            for texture in self.intermediate:
                self.forget(texture)
            self.intermediate = intermediate
        targets = (*textures, *intermediate)
        if all(id(texture) in self.targets for texture in targets):
            return
        layer_names = {id(key): name for key, name in zip(layers.keys, layers.names[1:])} if layers else {}
        old = sampler.integer(0x8069)
        try:
            for texture in targets:
                if id(texture) in self.targets:
                    continue
                name = layer_names.get(id(texture))
                if name is None:
                    if self.pico.SDL_GL_BindTexture(texture, None, None):
                        raise RuntimeError("적 시트 SDL 텍스처를 연결할 수 없다.")
                    name = sampler.integer(0x8069)
                self._attach(texture, name)
        finally:
            sampler.glBindTexture(TEXTURE_2D, old)

    def _attach(self, texture, name):
        framebuffer = ct.c_uint()
        self.glGenFramebuffers(1, ct.byref(framebuffer))
        if not framebuffer.value:
            raise RuntimeError("적 시트 OpenGL 프레임버퍼를 만들 수 없다.")
        try:
            self._bind_target(framebuffer.value)
            self.glFramebufferTexture2D(DRAW_FRAMEBUFFER, COLOR_ATTACHMENT, TEXTURE_2D, name, 0)
            if self.glCheckFramebufferStatus(DRAW_FRAMEBUFFER) != 0x8CD5:
                raise RuntimeError("적 시트 OpenGL 프레임버퍼가 완전하지 않다.")
        except BaseException:
            self.glDeleteFramebuffers(1, ct.byref(framebuffer))
            raise
        self.targets[id(texture)] = texture, name, framebuffer

    def _bind_target(self, framebuffer):
        if self.framebuffer != framebuffer:
            self.glBindFramebuffer(DRAW_FRAMEBUFFER, framebuffer)
            self.framebuffer = framebuffer

    @contextmanager
    def frame(self, sampler, textures, *, smaa_size=None, intermediate=()):
        p = self.pico
        p.SDL_RenderFlush(p.renderer)
        self.framebuffer = framebuffer = sampler.integer(0x8CA6)
        self.program = program = sampler.integer(0x8B8D)
        active = sampler.integer(0x84E0)
        self.sampler = sampler
        self.size = self.blend = None
        with sampler._preserve_raster_attributes(RASTER_STATE):
            if active != 0x84C0:
                sampler.glActiveTexture(0x84C0)
            try:
                self._prepare_targets(textures, smaa_size, intermediate)
                sampler.glDisable(0x0C11)
                self.glColorMask(1, 1, 1, 1)
                with AtlasTextureBindings(sampler) as bindings:
                    self.bindings = bindings
                    yield
            finally:
                self._bind_target(framebuffer)
                if self.program != program:
                    sampler.glUseProgram(program)
                if active != 0x84C0:
                    sampler.glActiveTexture(active)
                self.sampler = self.bindings = None

    @contextmanager
    def target(self, texture, size):
        self._bind_target(self.targets[id(texture)][2].value)
        if self.size != size:
            self.sampler.glViewport(0, 0, *size)
            self.size = size
        self.glClearBufferfv(0x1800, 0, self.clear_color)
        yield

    @contextmanager
    def batch(self, sampler, *, blend=True):
        width, height = self.size
        sampler.output_size = self.size
        sampler.target_flip = -1
        if sampler.program != self.program:
            sampler.glUseProgram(sampler.program)
            self.program = sampler.program
        if self.blend is None:
            sampler.glBlendEquationSeparate(0x8006, 0x8006)
            sampler.glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)
        if blend != self.blend:
            (sampler.glEnable if blend else sampler.glDisable)(0x0BE2)
            self.blend = blend
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
        name = self.targets[id(texture)][1] if sdl else texture
        self.bindings.apply(({},), (name,), first_unit=unit)
        yield

    def forget(self, texture):
        target = self.targets.pop(id(texture), None)
        if target is not None:
            _, _, framebuffer = target
            self.glDeleteFramebuffers(1, ct.byref(framebuffer))

    def close(self):
        for _, _, framebuffer in self.targets.values():
            self.glDeleteFramebuffers(1, ct.byref(framebuffer))
        self.targets.clear()
        self.intermediate = ()
        if self.smaa_layers is not None:
            self.smaa_layers.close()

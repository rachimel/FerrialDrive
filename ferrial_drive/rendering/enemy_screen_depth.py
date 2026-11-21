"""근거리 적끼리 공유하는 화면 좌표 깊이 텍스처."""

from contextlib import contextmanager
import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl


class EnemyScreenDepth:
    def __init__(self, pico):
        self.size = (0, 0)
        self.texture, self.fbo = ct.c_uint(), ct.c_uint()
        self.clear_depth = ct.c_float(1)
        u, i, p = ct.c_uint, ct.c_int, ct.c_void_p
        for name, result, args in (
            ("glGenTextures", None, [i, p]), ("glDeleteTextures", None, [i, p]),
            ("glTexStorage2D", None, [u, i, u, i, i]), ("glTexParameteri", None, [u, u, i]),
            ("glGenFramebuffers", None, [i, p]), ("glDeleteFramebuffers", None, [i, p]),
            ("glBindFramebuffer", None, [u, u]), ("glFramebufferTexture2D", None, [u, u, u, u, i]),
            ("glDrawBuffer", None, [u]), ("glReadBuffer", None, [u]), ("glCheckFramebufferStatus", u, [u]),
            ("glClearBufferfv", None, [u, i, p]), ("glDepthMask", None, [ct.c_ubyte]),
            ("glDepthFunc", None, [u]),
        ):
            setattr(self, name, bind_gl(pico, name, result, args))

    @property
    def storage_bytes(self):
        return self.size[0] * self.size[1] * 4

    def reserve(self, sampler, required_size):
        size = tuple(min(limit, max(old, (required + 63) // 64 * 64))
                     for limit, old, required in zip(sampler.output_size, self.size, required_size, strict=True))
        if size == self.size:
            return
        self.close()
        texture = sampler.integer(0x8069)
        read_fbo, draw_fbo = sampler.integer(0x8CAA), sampler.integer(0x8CA6)
        try:
            self.glGenTextures(1, ct.byref(self.texture))
            self.glGenFramebuffers(1, ct.byref(self.fbo))
            sampler.glBindTexture(0x0DE1, self.texture.value)
            self.glTexStorage2D(0x0DE1, 1, 0x8CAC, *size)  # GL_DEPTH_COMPONENT32F
            for param in (0x2800, 0x2801):
                self.glTexParameteri(0x0DE1, param, 0x2600)
            self.glBindFramebuffer(0x8D40, self.fbo.value)
            self.glFramebufferTexture2D(0x8D40, 0x8D00, 0x0DE1, self.texture.value, 0)
            self.glDrawBuffer(0)
            self.glReadBuffer(0)
            if self.glCheckFramebufferStatus(0x8D40) != 0x8CD5:
                raise RuntimeError("적 화면 깊이 버퍼 생성 실패")
            self.size = size
        except BaseException:
            self.close()
            raise
        finally:
            sampler.glBindTexture(0x0DE1, texture)
            self.glBindFramebuffer(0x8CA8, read_fbo)
            self.glBindFramebuffer(0x8CA9, draw_fbo)

    @contextmanager
    def bind(self, sampler, required_size, *, clear):
        self.reserve(sampler, required_size)
        fbo = sampler.integer(0x8CA6)
        depth_test = sampler.glIsEnabled(0x0B71)
        depth_mask, depth_func = sampler.integer(0x0B72), sampler.integer(0x0B74)
        flip = sampler.target_flip
        output_size, viewport = sampler.output_size, sampler.viewport
        try:
            self.glBindFramebuffer(0x8CA9, self.fbo.value)
            sampler.glEnable(0x0B71)
            self.glDepthMask(1)
            self.glDepthFunc(0x0201)  # GL_LESS
            # SDL 타깃과 시트의 좌표계처럼 깊이 텍스처의 y=0을 화면 위로 잡는다.
            sampler.target_flip = -1
            sampler.output_size = self.size
            sampler.viewport = (0, 0, *self.size)
            sampler.glViewport(0, 0, *self.size)
            sampler.glUniform2f(sampler.uniforms["outputSize"], *self.size)
            sampler.glUniform1f(sampler.uniforms["targetFlip"], -1)
            if clear:
                sampler.glDisable(0x0C11)
                self.glClearBufferfv(0x1801, 0, ct.byref(self.clear_depth))
            yield
        finally:
            sampler.target_flip = flip
            sampler.output_size, sampler.viewport = output_size, viewport
            sampler.glViewport(0, 0, *output_size)
            sampler.glUniform2f(sampler.uniforms["outputSize"], *output_size)
            sampler.glUniform1f(sampler.uniforms["targetFlip"], flip)
            self.glDepthFunc(depth_func)
            self.glDepthMask(depth_mask)
            (sampler.glEnable if depth_test else sampler.glDisable)(0x0B71)
            self.glBindFramebuffer(0x8CA9, fbo)

    def close(self):
        if self.fbo.value:
            self.glDeleteFramebuffers(1, ct.byref(self.fbo))
            self.fbo.value = 0
        if self.texture.value:
            self.glDeleteTextures(1, ct.byref(self.texture))
            self.texture.value = 0
        self.size = (0, 0)

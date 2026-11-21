"""Pico2D SDL 상태와 OpenGL 드로우 구간의 경계."""

from contextlib import contextmanager
import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl

from .gl_program import FRAGMENT_STAGE, VERTEX_STAGE, ShaderProgram


QUAD_VERTEX_SHADER = b'''#version 120
uniform vec2 outputSize;
uniform float targetFlip;
varying vec2 texel;
void main() {
    vec2 p = gl_Vertex.xy / outputSize;
    gl_Position = vec4(p.x * 2.0 - 1.0, (1.0 - p.y * 2.0) * targetFlip, 0.0, 1.0);
    texel = gl_MultiTexCoord0.xy;
}
'''

class SdlOpenGLPass:
    """프로그램을 소유하고 SDL과 공유하는 GL 상태를 배치 경계에서 복구한다."""

    def __init__(self, pico, *, vertex_shader, fragment_shader, extra_uniforms=()):
        self.pico = pico
        self.depth = 0
        self._bind_functions()
        self.shader = ShaderProgram(pico, ((VERTEX_STAGE, vertex_shader), (FRAGMENT_STAGE, fragment_shader)),
                                    ("outputSize", "targetFlip", *extra_uniforms))
        self.uniforms = self.shader.uniforms

    @property
    def program(self):
        return self.shader.handle

    def close(self):
        self.shader.close()

    def _bind_functions(self):
        uint, integer, floating, pointer = ct.c_uint, ct.c_int, ct.c_float, ct.c_void_p
        signatures = {
            'glUseProgram': (None, [uint]), 'glUniform1i': (None, [integer, integer]),
            'glUniform1f': (None, [integer, floating]), 'glUniform2f': (None, [integer, floating, floating]),
            'glUniform4f': (None, [integer, floating, floating, floating, floating]),
            'glGetIntegerv': (None, [uint, pointer]), 'glIsEnabled': (ct.c_ubyte, [uint]),
            'glEnable': (None, [uint]), 'glDisable': (None, [uint]), 'glActiveTexture': (None, [uint]),
            'glBindTexture': (None, [uint, uint]), 'glBlendFuncSeparate': (None, [uint, uint, uint, uint]),
            'glBlendEquationSeparate': (None, [uint, uint]), 'glViewport': (None, [integer]*4),
            'glScissor': (None, [integer]*4),
        }
        for name, (result, arguments) in signatures.items():
            setattr(self, name, bind_gl(self.pico, name, result, arguments))

    def integer(self, name, count=1):
        value = (ct.c_int * count)()
        self.glGetIntegerv(name, value)
        return tuple(value) if count > 1 else value[0]

    @contextmanager
    def _preserve_blend_and_clip(self):
        factors = tuple(self.integer(key) for key in (0x80C9, 0x80C8, 0x80CB, 0x80CA))
        equations = self.integer(0x8009), self.integer(0x883D)
        blend, clipped = self.glIsEnabled(0x0BE2), self.glIsEnabled(0x0C11)
        scissor = self.integer(0x0C10, 4)
        try:
            yield
        finally:
            self.glBlendFuncSeparate(*factors)
            self.glBlendEquationSeparate(*equations)
            (self.glEnable if blend else self.glDisable)(0x0BE2)
            (self.glEnable if clipped else self.glDisable)(0x0C11)
            self.glScissor(*scissor)

    @contextmanager
    def batch(self, *, preserve_raster=None):
        if self.depth:
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1
            return
        p = self.pico
        # SDL의 지연된 viewport/clip 상태를 화면 밖 점으로 먼저 확정한다.
        p.SDL_RenderDrawPoint(p.renderer, -1000000, -1000000)
        p.SDL_RenderFlush(p.renderer)
        program, active = self.integer(0x8B8D), self.integer(0x84E0)
        viewport = self.integer(0x0BA2, 4)
        width, height = ct.c_int(), ct.c_int()
        target = p.SDL_GetRenderTarget(p.renderer)
        if target:
            p.SDL_QueryTexture(target, None, None, ct.byref(width), ct.byref(height))
        else:
            p.SDL_GetRendererOutputSize(p.renderer, ct.byref(width), ct.byref(height))
        self.output_size = width.value, height.value
        self.target_flip = -1 if target else 1
        self.viewport = (viewport[0], height.value - viewport[1] - viewport[3] if not target else viewport[1],
                         viewport[2], viewport[3])
        with (preserve_raster or self._preserve_blend_and_clip)():
            self.glActiveTexture(0x84C0)
            texture = self.integer(0x8069)
            self.depth = 1
            try:
                self.glUseProgram(self.program)
                self.glEnable(0x0BE2)
                self.glBlendEquationSeparate(0x8006, 0x8006)
                self.glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)
                self.glViewport(0, 0, width.value, height.value)
                self.glUniform2f(self.uniforms['outputSize'], width.value, height.value)
                self.glUniform1f(self.uniforms['targetFlip'], self.target_flip)
                yield
            finally:
                self.depth = 0
                self.glUseProgram(program)
                self.glBindTexture(0x0DE1, texture)
                self.glActiveTexture(active)
                self.glViewport(*viewport)


class TexturedQuadPass(SdlOpenGLPass):
    """텍스처 좌표를 가진 SDL 화면 사각형을 전달한다."""

    def __init__(self, pico, *, fragment_shader, vertex_shader=QUAD_VERTEX_SHADER, extra_uniforms=()):
        super().__init__(pico, vertex_shader=vertex_shader, fragment_shader=fragment_shader,
                         extra_uniforms=("artwork", "atlasSize", "frameBounds", "modulation",
                                         "premultipliedSource", *extra_uniforms))

    def _bind_functions(self):
        super()._bind_functions()
        floating = ct.c_float
        self.glBegin = bind_gl(self.pico, "glBegin", None, [ct.c_uint])
        self.glEnd = bind_gl(self.pico, "glEnd", None, [])
        self.glTexCoord2f = bind_gl(self.pico, "glTexCoord2f", None, [floating, floating])
        self.glVertex2f = bind_gl(self.pico, "glVertex2f", None, [floating, floating])

    @contextmanager
    def batch(self):
        outer = not self.depth
        with super().batch():
            if outer:
                self.glUniform1i(self.uniforms["artwork"], 0)
            yield

    def draw(self, texture, size, source, destination, *, premultiplied=False):
        if not self.depth:
            with self.batch():
                self.draw(texture, size, source, destination, premultiplied=premultiplied)
            return
        p = self.pico
        if texture is not None:
            texw, texh = ct.c_float(), ct.c_float()
            if p.SDL_GL_BindTexture(texture, ct.byref(texw), ct.byref(texh)) != 0:
                raise RuntimeError('SDL 텍스처 OpenGL 연결 실패')
            if abs(texw.value - 1) > 1e-5 or abs(texh.value - 1) > 1e-5:
                raise RuntimeError('텍스처 사각형 패스는 정규화된 2D 텍스처가 필요하다.')
        clip = p.SDL_Rect()
        vx, vy, vw, vh = self.viewport
        scale_x, scale_y = ct.c_float(), ct.c_float()
        p.SDL_RenderGetScale(p.renderer, ct.byref(scale_x), ct.byref(scale_y))
        left = vx + destination.x * scale_x.value
        top = vy + destination.y * scale_y.value
        right, bottom = left + destination.w * scale_x.value, top + destination.h * scale_y.value
        if p.SDL_RenderIsClipEnabled(p.renderer):
            p.SDL_RenderGetClipRect(p.renderer, ct.byref(clip))
            clip = p.SDL_Rect(vx + int(clip.x * scale_x.value), vy + int(clip.y * scale_y.value),
                              int(clip.w * scale_x.value), int(clip.h * scale_y.value))
        else:
            clip = p.SDL_Rect(vx, vy, vw, vh)
        self.glEnable(0x0C11)
        cy = self.output_size[1] - clip.y - clip.h if self.target_flip > 0 else clip.y
        self.glScissor(clip.x, cy, clip.w, clip.h)
        color = (1, 1, 1, 1)
        if texture is not None:
            rgba = [ct.c_ubyte() for _ in range(4)]
            p.SDL_GetTextureColorMod(texture, *(ct.byref(value) for value in rgba[:3]))
            p.SDL_GetTextureAlphaMod(texture, ct.byref(rgba[3]))
            color = tuple(value.value / 255 for value in rgba)
        self.glUniform4f(self.uniforms['modulation'], *color)
        if self.uniforms['premultipliedSource'] >= 0:
            self.glUniform1f(self.uniforms['premultipliedSource'], float(premultiplied))
        self.glUniform2f(self.uniforms['atlasSize'], *size)
        self.glUniform4f(self.uniforms['frameBounds'], source.x, source.y, source.x + source.w, source.y + source.h)
        self.glBegin(0x0005)
        for x, y, u, v in ((left, top, source.x, source.y), (left, bottom, source.x, source.y + source.h),
                           (right, top, source.x + source.w, source.y), (right, bottom, source.x + source.w, source.y + source.h)):
            self.glTexCoord2f(u, v)
            self.glVertex2f(x, y)
        self.glEnd()

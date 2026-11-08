"""SDL OpenGL 텍스처를 재사용하는 화면 픽셀 Bicubic. PNG·Pico2D 원본은 변경하지 않는다."""

from contextlib import contextmanager
import ctypes as ct
import os


VERTEX_SHADER = b'''#version 120
uniform vec2 outputSize;
uniform float targetFlip;
varying vec2 texel;
void main() {
    vec2 p = gl_Vertex.xy / outputSize;
    gl_Position = vec4(p.x * 2.0 - 1.0, (1.0 - p.y * 2.0) * targetFlip, 0.0, 1.0);
    texel = gl_MultiTexCoord0.xy;
}
'''

FRAGMENT_SHADER = b'''#version 120
uniform sampler2D artwork;
uniform vec2 atlasSize;
uniform vec4 frameBounds;
uniform vec4 modulation;
varying vec2 texel;
vec4 weights(float t) {
    float t2=t*t, t3=t2*t;
    return vec4(-0.5*t+t2-0.5*t3, 1.0-2.5*t2+1.5*t3,
                0.5*t+2.0*t2-1.5*t3, -0.5*t2+0.5*t3);
}
void main() {
    vec2 p=texel-0.5, base=floor(p), f=fract(p);
    vec4 wx=weights(f.x), wy=weights(f.y), total=vec4(0.0);
    for (int j=0;j<4;++j) for (int i=0;i<4;++i) {
        vec2 pixel=clamp(base+vec2(float(i-1),float(j-1))+0.5,
                         frameBounds.xy+0.5, frameBounds.zw-0.5);
        vec4 s=texture2D(artwork,pixel/atlasSize);
        total += vec4(s.rgb*s.a,s.a)*wx[i]*wy[j];
    }
    float alpha=clamp(total.a,0.0,1.0);
    vec3 rgb=alpha>0.00001 ? clamp(total.rgb,0.0,alpha)/alpha : vec3(0.0);
    gl_FragColor=vec4(rgb*modulation.rgb,alpha*modulation.a);
}
'''

_SAMPLERS = {}


def renderer_name(pico):
    info = pico.SDL_RendererInfo()
    if pico.SDL_GetRendererInfo(pico.renderer, ct.byref(info)) != 0:
        raise RuntimeError('렌더러 정보 조회 실패')
    return info.name.decode('utf-8')


def acquire_sampler(pico):
    if renderer_name(pico) != 'opengl':
        return None
    key = ct.cast(pico.renderer, ct.c_void_p).value
    if key not in _SAMPLERS:
        _SAMPLERS[key] = BicubicSampler(pico, key)
    sampler = _SAMPLERS[key]
    sampler.references += 1
    return sampler


class BicubicSampler:
    def __init__(self, pico, key):
        self.pico, self.key, self.references, self.depth = pico, key, 0, 0
        self.functions = {}
        self.program = 0
        self._bind_functions()
        shaders = []
        try:
            for kind, source in ((0x8B31, VERTEX_SHADER), (0x8B30, FRAGMENT_SHADER)):
                shader = self.glCreateShader(kind)
                shaders.append(shader)
                pointer = ct.c_char_p(source)
                self.glShaderSource(shader, 1, ct.byref(pointer), None)
                self.glCompileShader(shader)
                result = ct.c_int()
                self.glGetShaderiv(shader, 0x8B81, ct.byref(result))
                if not result.value:
                    message = ct.create_string_buffer(4096)
                    self.glGetShaderInfoLog(shader, 4096, None, message)
                    raise RuntimeError('Bicubic 셰이더 컴파일 실패: ' + message.value.decode(errors='replace'))
            self.program = self.glCreateProgram()
            for shader in shaders:
                self.glAttachShader(self.program, shader)
            self.glLinkProgram(self.program)
            result = ct.c_int()
            self.glGetProgramiv(self.program, 0x8B82, ct.byref(result))
            if not result.value:
                raise RuntimeError('Bicubic 셰이더 연결 실패')
            self.uniforms = {name: self.glGetUniformLocation(self.program, name.encode())
                             for name in ('outputSize', 'targetFlip', 'artwork', 'atlasSize', 'frameBounds', 'modulation')}
        except BaseException:
            if self.program:
                self.glDeleteProgram(self.program)
            raise
        finally:
            for shader in shaders:
                self.glDeleteShader(shader)

    def _bind_functions(self):
        uint, integer, floating, pointer = ct.c_uint, ct.c_int, ct.c_float, ct.c_void_p
        signatures = {
            'glCreateShader': (uint, [uint]), 'glShaderSource': (None, [uint, integer, pointer, pointer]),
            'glCompileShader': (None, [uint]), 'glGetShaderiv': (None, [uint, uint, pointer]),
            'glGetShaderInfoLog': (None, [uint, integer, pointer, pointer]), 'glDeleteShader': (None, [uint]),
            'glCreateProgram': (uint, []), 'glAttachShader': (None, [uint, uint]),
            'glLinkProgram': (None, [uint]), 'glGetProgramiv': (None, [uint, uint, pointer]),
            'glDeleteProgram': (None, [uint]), 'glUseProgram': (None, [uint]),
            'glGetUniformLocation': (integer, [uint, ct.c_char_p]), 'glUniform1i': (None, [integer, integer]),
            'glUniform1f': (None, [integer, floating]), 'glUniform2f': (None, [integer, floating, floating]),
            'glUniform4f': (None, [integer, floating, floating, floating, floating]),
            'glGetIntegerv': (None, [uint, pointer]), 'glIsEnabled': (ct.c_ubyte, [uint]),
            'glEnable': (None, [uint]), 'glDisable': (None, [uint]), 'glActiveTexture': (None, [uint]),
            'glBindTexture': (None, [uint, uint]), 'glBlendFuncSeparate': (None, [uint, uint, uint, uint]),
            'glBlendEquationSeparate': (None, [uint, uint]), 'glViewport': (None, [integer]*4),
            'glScissor': (None, [integer]*4), 'glBegin': (None, [uint]), 'glEnd': (None, []),
            'glTexCoord2f': (None, [floating, floating]), 'glVertex2f': (None, [floating, floating]),
        }
        prototype = ct.WINFUNCTYPE if os.name == 'nt' else ct.CFUNCTYPE
        for name, (result, arguments) in signatures.items():
            address = self.pico.SDL_GL_GetProcAddress(name.encode())
            if not address:
                raise RuntimeError('OpenGL 기능 미지원: ' + name)
            setattr(self, name, prototype(result, *arguments)(address))

    def integer(self, name, count=1):
        value = (ct.c_int * count)()
        self.glGetIntegerv(name, value)
        return tuple(value) if count > 1 else value[0]

    @contextmanager
    def batch(self):
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
        old = {name: self.integer(enum) for name, enum in
               (('program', 0x8B8D), ('active', 0x84E0), ('src', 0x80C9), ('dst', 0x80C8),
                ('src_alpha', 0x80CB), ('dst_alpha', 0x80CA), ('equation', 0x8009), ('equation_alpha', 0x883D))}
        old['viewport'], old['scissor'] = self.integer(0x0BA2, 4), self.integer(0x0C10, 4)
        old['blend'], old['clipped'] = self.glIsEnabled(0x0BE2), self.glIsEnabled(0x0C11)
        self.glActiveTexture(0x84C0)
        old['texture'] = self.integer(0x8069)
        width, height = ct.c_int(), ct.c_int()
        target = p.SDL_GetRenderTarget(p.renderer)
        if target:
            p.SDL_QueryTexture(target, None, None, ct.byref(width), ct.byref(height))
        else:
            p.SDL_GetRendererOutputSize(p.renderer, ct.byref(width), ct.byref(height))
        self.output_size = width.value, height.value
        self.target_flip = -1 if target else 1
        viewport = old['viewport']
        self.viewport = (viewport[0], height.value - viewport[1] - viewport[3] if not target else viewport[1],
                         viewport[2], viewport[3])
        self.depth = 1
        try:
            self.glUseProgram(self.program)
            self.glEnable(0x0BE2)
            self.glBlendEquationSeparate(0x8006, 0x8006)
            self.glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)
            self.glViewport(0, 0, width.value, height.value)
            self.glUniform1i(self.uniforms['artwork'], 0)
            self.glUniform2f(self.uniforms['outputSize'], width.value, height.value)
            self.glUniform1f(self.uniforms['targetFlip'], self.target_flip)
            yield
        finally:
            self.depth = 0
            self.glUseProgram(old['program'])
            self.glBindTexture(0x0DE1, old['texture'])
            self.glActiveTexture(old['active'])
            self.glBlendFuncSeparate(old['src'], old['dst'], old['src_alpha'], old['dst_alpha'])
            self.glBlendEquationSeparate(old['equation'], old['equation_alpha'])
            (self.glEnable if old['blend'] else self.glDisable)(0x0BE2)
            (self.glEnable if old['clipped'] else self.glDisable)(0x0C11)
            self.glScissor(*old['scissor'])
            self.glViewport(*old['viewport'])

    def draw(self, texture, size, source, destination):
        if not self.depth:
            with self.batch():
                self.draw(texture, size, source, destination)
            return
        p = self.pico
        texw, texh = ct.c_float(), ct.c_float()
        if p.SDL_GL_BindTexture(texture, ct.byref(texw), ct.byref(texh)) != 0:
            raise RuntimeError('SDL 텍스처 OpenGL 연결 실패')
        if abs(texw.value - 1) > 1e-5 or abs(texh.value - 1) > 1e-5:
            raise RuntimeError('Bicubic은 정규화된 2D 텍스처가 필요하다.')
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
        color = [ct.c_ubyte() for _ in range(4)]
        p.SDL_GetTextureColorMod(texture, *(ct.byref(value) for value in color[:3]))
        p.SDL_GetTextureAlphaMod(texture, ct.byref(color[3]))
        self.glUniform4f(self.uniforms['modulation'], *(value.value / 255 for value in color))
        self.glUniform2f(self.uniforms['atlasSize'], *size)
        self.glUniform4f(self.uniforms['frameBounds'], source.x, source.y, source.x + source.w, source.y + source.h)
        self.glBegin(0x0005)
        for x, y, u, v in ((left, top, source.x, source.y), (left, bottom, source.x, source.y + source.h),
                           (right, top, source.x + source.w, source.y), (right, bottom, source.x + source.w, source.y + source.h)):
            self.glTexCoord2f(u, v)
            self.glVertex2f(x, y)
        self.glEnd()

    def release(self):
        self.references -= 1
        if self.references == 0:
            self.glDeleteProgram(self.program)
            _SAMPLERS.pop(self.key, None)

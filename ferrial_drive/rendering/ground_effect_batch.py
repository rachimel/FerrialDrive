"""입자 순서를 보존하는 지면 효과 데이터 업로드·연속 텍스처 인스턴싱."""

import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from .bicubic import BicubicSampler
from .ground_effect_shaders import INSTANCED_FRAGMENT_SHADER


INSTANCE_FLOATS = 28
VERTEX_SHADER = b'''#version 330
uniform vec2 outputSize;
uniform float targetFlip;
uniform sampler2D instances;
uniform int instanceOffset;
uniform vec4 screenTransform;
out vec2 texel;
out vec2 screenPoint;
flat out vec4 frameBounds;
flat out vec4 ink;
flat out float fade;
flat out float cutoff;
flat out float detail;
flat out float roundness;
flat out int mode;
flat out int depthMode;
flat out vec2 emitterOrigin;
flat out float nearRadius;
flat out float headFeather;
void main() {
    int row = gl_InstanceID + instanceOffset;
    vec4 geometry = texelFetch(instances, ivec2(0, row), 0);
    frameBounds = texelFetch(instances, ivec2(1, row), 0);
    vec4 centerRotation = texelFetch(instances, ivec2(2, row), 0);
    vec4 mirrorOrigin = texelFetch(instances, ivec2(3, row), 0);
    ink = texelFetch(instances, ivec2(4, row), 0);
    vec4 appearance = texelFetch(instances, ivec2(5, row), 0);
    vec4 modes = texelFetch(instances, ivec2(6, row), 0);
    fade = appearance.x; cutoff = appearance.y; detail = appearance.z; roundness = appearance.w;
    mode = int(modes.x); depthMode = int(modes.y); headFeather = modes.z;
    emitterOrigin = mirrorOrigin.yz; nearRadius = mirrorOrigin.w;
    vec2 corner = vec2(float(gl_VertexID / 2), float(gl_VertexID % 2));
    vec2 point = screenTransform.xy + (geometry.xy + geometry.zw * corner) * screenTransform.zw;
    vec2 delta = point - centerRotation.xy;
    delta.x *= mirrorOrigin.x;
    point = centerRotation.xy + vec2(centerRotation.z * delta.x - centerRotation.w * delta.y,
                                    centerRotation.w * delta.x + centerRotation.z * delta.y);
    screenPoint = point;
    texel = mix(frameBounds.xy, frameBounds.zw, corner);
    vec2 p = point / outputSize;
    gl_Position = vec4(p.x * 2.0 - 1.0, (1.0 - p.y * 2.0) * targetFlip, 0.0, 1.0);
}
'''


class GroundEffectBatch(BicubicSampler):
    def __init__(self, pico):
        self.texture = self.capacity = self.gpu_capacity = self.count = 0
        self.data = None
        self.runs = []
        self.stats = {}
        super().__init__(pico, None, vertex_shader=VERTEX_SHADER, fragment_shader=INSTANCED_FRAGMENT_SHADER,
                         extra_uniforms=("instances", "instanceOffset", "screenTransform"))
        self.max_rows = self.integer(0x0D33)

    def _bind_functions(self):
        super()._bind_functions()
        integer, uint, pointer = ct.c_int, ct.c_uint, ct.c_void_p
        for name, (result, arguments) in {
            "glGenTextures": (None, [integer, pointer]), "glDeleteTextures": (None, [integer, pointer]),
            "glTexParameteri": (None, [uint, uint, integer]),
            "glTexImage2D": (None, [uint, integer, integer, integer, integer, integer, uint, uint, pointer]),
            "glTexSubImage2D": (None, [uint, integer, integer, integer, integer, integer, uint, uint, pointer]),
            "glDrawArraysInstanced": (None, [uint, integer, integer, integer]),
            "glPixelStorei": (None, [uint, integer]), "glBindBuffer": (None, [uint, uint]),
        }.items():
            setattr(self, name, bind_gl(self.pico, name, result, arguments))

    def begin(self):
        self.count = 0
        self.runs.clear()
        self.stats = dict(particles=0, submits=0, upload_bytes=0, buffer_allocations=0)

    def append(self, texture, size, values):
        if self.count == self.capacity:
            capacity = min(self.max_rows, max(64, self.capacity * 2))
            if capacity <= self.count:
                raise ValueError("지면 효과 배치가 GL 데이터 텍스처 행 상한을 넘었다.")
            data = (ct.c_float * (capacity * INSTANCE_FLOATS))()
            if self.count:
                ct.memmove(data, self.data, self.count * INSTANCE_FLOATS * ct.sizeof(ct.c_float))
            self.data, self.capacity = data, capacity
            self.stats["buffer_allocations"] += 1
        offset = self.count * INSTANCE_FLOATS
        self.data[offset:offset + INSTANCE_FLOATS] = values
        if self.runs and self.runs[-1][0] == texture:
            self.runs[-1][3] += 1
        else:
            self.runs.append([texture, size, self.count, 1])
        self.count += 1

    def render(self):
        self.stats["particles"] = self.count
        if not self.count:
            return
        p = self.pico
        with self.batch():
            self.glActiveTexture(0x84C1)
            old_texture = self.integer(0x8069)
            keys = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
            unpack = tuple(self.integer(key) for key in keys)
            old_buffer = self.integer(0x88EF)
            try:
                self.glBindBuffer(0x88EC, 0)
                for key, value in zip(keys, (4, 0, 0, 0)):
                    self.glPixelStorei(key, value)
                if not self.texture:
                    texture = ct.c_uint()
                    self.glGenTextures(1, ct.byref(texture))
                    self.texture = texture.value
                self.glBindTexture(0x0DE1, self.texture)
                if self.capacity > self.gpu_capacity:
                    self.glTexParameteri(0x0DE1, 0x2801, 0x2600)
                    self.glTexParameteri(0x0DE1, 0x2800, 0x2600)
                    self.glTexImage2D(0x0DE1, 0, 0x8814, 7, self.capacity, 0, 0x1908, 0x1406, None)
                    self.gpu_capacity = self.capacity
                self.glTexSubImage2D(0x0DE1, 0, 0, 0, 7, self.count, 0x1908, 0x1406, self.data)
                self.stats["upload_bytes"] = self.count * INSTANCE_FLOATS * 4
                self.glUniform1i(self.uniforms["instances"], 1)
                sx, sy = ct.c_float(), ct.c_float()
                p.SDL_RenderGetScale(p.renderer, ct.byref(sx), ct.byref(sy))
                vx, vy, vw, vh = self.viewport
                self.glUniform4f(self.uniforms["screenTransform"], vx, vy, sx.value, sy.value)
                clip = p.SDL_Rect(vx, vy, vw, vh)
                if p.SDL_RenderIsClipEnabled(p.renderer):
                    p.SDL_RenderGetClipRect(p.renderer, ct.byref(clip))
                    clip = p.SDL_Rect(vx + int(clip.x * sx.value), vy + int(clip.y * sy.value),
                                      int(clip.w * sx.value), int(clip.h * sy.value))
                self.glEnable(0x0C11)
                cy = self.output_size[1] - clip.y - clip.h if self.target_flip > 0 else clip.y
                self.glScissor(clip.x, cy, clip.w, clip.h)
                self.glActiveTexture(0x84C0)
                for texture, size, first, count in self.runs:
                    tw, th = ct.c_float(), ct.c_float()
                    if p.SDL_GL_BindTexture(texture, ct.byref(tw), ct.byref(th)) != 0:
                        raise RuntimeError("지면 효과 텍스처 OpenGL 연결 실패")
                    if abs(tw.value - 1) > 1e-5 or abs(th.value - 1) > 1e-5:
                        raise RuntimeError("지면 효과는 정규화된 2D 텍스처가 필요하다.")
                    self.glUniform2f(self.uniforms["atlasSize"], *size)
                    self.glUniform1i(self.uniforms["instanceOffset"], first)
                    self.glDrawArraysInstanced(0x0005, 0, 4, count)
                    self.stats["submits"] += 1
            finally:
                self.glActiveTexture(0x84C1)
                self.glBindTexture(0x0DE1, old_texture)
                self.glActiveTexture(0x84C0)
                for key, value in zip(keys, unpack):
                    self.glPixelStorei(key, value)
                self.glBindBuffer(0x88EC, old_buffer)

    def close(self):
        if self.texture:
            texture = ct.c_uint(self.texture)
            self.glDeleteTextures(1, ct.byref(texture))
            self.texture = 0
        if self.program:
            self.glDeleteProgram(self.program)
            self.program = 0
        self.data = None
        self.capacity = self.gpu_capacity = self.count = 0
        self.runs.clear()

"""고정 리본·오브의 GPU Instancing. 경로는 생성 시, 진행률만 매 프레임 전송한다."""

import ctypes as ct
from math import hypot
import os

from .bicubic import BicubicSampler
from ferrial_drive.ui_v2.particle_texture import ATLAS_SIZE, build_particle_atlas


VERTEX_SHADER = b'''#version 330
uniform vec2 outputSize;
uniform float targetFlip;
uniform sampler2D paths;
uniform sampler2D instances;
uniform vec4 transform;
uniform vec4 baseColor;
uniform vec4 coreColor;
uniform float headWidth;
uniform float orbRadius;
uniform float tailFraction;
uniform int segments;
uniform int particleCount;
uniform int mode;
out vec2 uv;
out vec4 ink;
vec3 pathPoint(float t, int slot) {
    float p = clamp(t, 0.0, 1.0) * 200.0;
    int i = min(199, int(p));
    return mix(texelFetch(paths, ivec2(i, slot), 0).xyz,
               texelFetch(paths, ivec2(i + 1, slot), 0).xyz, p - float(i));
}
void main() {
    int index = gl_InstanceID % particleCount;
    int layer = gl_InstanceID / particleCount;
    vec4 state = texelFetch(instances, ivec2(0, index), 0);
    float progress = state.x;
    int slot = int(state.y);
    vec2 point;
    if (mode == 0) {
        float along = float(gl_VertexID / 2) / float(segments);
        float edge = float(gl_VertexID % 2);
        float head = min(1.0, progress);
        float tail = max(0.0, progress - tailFraction);
        float t = mix(tail, head, along);
        vec3 p = pathPoint(t, slot);
        float low = pathPoint(tail, slot).z;
        float high = pathPoint(head, slot).z;
        float fade = clamp(1.0 - max(0.0, progress - 1.0) / tailFraction, 0.0, 1.0);
        float pressure = pow(clamp((p.z - low) / max(0.00001, high - low), 0.0, 1.0), 1.5) * fade;
        vec2 tangent = pathPoint(t + 0.005, slot).xy - pathPoint(t - 0.005, slot).xy;
        vec2 normal = vec2(-tangent.y, tangent.x) / max(0.00001, length(tangent));
        float width = headWidth * (layer == 0 ? 2.0 : 0.5);
        point = p.xy + normal * (edge - 0.5) * width * pressure;
        ink = layer == 0 ? baseColor : coreColor;
        ink.a *= pressure * (layer == 0 ? 0.85 : 0.9);
        uv = vec2((64.5 + along * 63.0) / 128.0, (0.5 + edge * 63.0) / 64.0);
    } else {
        vec2 corner = vec2(float(gl_VertexID / 2), float(gl_VertexID % 2));
        float radius = orbRadius * (layer == 0 ? 2.4 : (layer == 1 ? 1.0 : 0.45));
        point = pathPoint(min(1.0, progress), slot).xy + (corner * 2.0 - 1.0) * radius;
        ink = layer == 2 ? coreColor : baseColor;
        ink.a *= (progress <= 1.0 ? 1.0 : 0.0) * (layer == 0 ? 0.1 : (layer == 1 ? 0.9 : 1.0));
        uv = (vec2(0.5) + corner * 63.0) / vec2(128.0, 64.0);
    }
    vec2 screen = transform.xy + point * transform.zw;
    vec2 ndc = screen / outputSize;
    gl_Position = vec4(ndc.x * 2.0 - 1.0, (1.0 - ndc.y * 2.0) * targetFlip, 0.0, 1.0);
}
'''

FRAGMENT_SHADER = b'''#version 330
uniform sampler2D artwork;
in vec2 uv;
in vec4 ink;
out vec4 result;
void main() {
    result = vec4(ink.rgb, ink.a * texture(artwork, uv).a);
}
'''


class InstancedParticles(BicubicSampler):
    def __init__(self, pico):
        self.textures = []
        self.capacity = 0
        self.slots = {}
        self.path_uploads = 0
        self.instance_upload_bytes = 0
        super().__init__(pico, None, vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER,
                         extra_uniforms=('paths', 'instances', 'transform', 'baseColor', 'coreColor',
                                         'headWidth', 'orbRadius', 'tailFraction', 'segments', 'particleCount', 'mode'))

    def _bind_functions(self):
        super()._bind_functions()
        uint, integer, pointer = ct.c_uint, ct.c_int, ct.c_void_p
        signatures = {
            'glGenTextures': (None, [integer, pointer]),
            'glDeleteTextures': (None, [integer, pointer]),
            'glTexParameteri': (None, [uint, uint, integer]),
            'glTexImage2D': (None, [uint, integer, integer, integer, integer, integer, uint, uint, pointer]),
            'glTexSubImage2D': (None, [uint, integer, integer, integer, integer, integer, uint, uint, pointer]),
            'glDrawArraysInstanced': (None, [uint, integer, integer, integer]),
            'glPixelStorei': (None, [uint, integer]),
            'glBindBuffer': (None, [uint, uint]),
        }
        prototype = ct.WINFUNCTYPE if os.name == 'nt' else ct.CFUNCTYPE
        for name, (result, arguments) in signatures.items():
            address = self.pico.SDL_GL_GetProcAddress(name.encode())
            if not address:
                raise RuntimeError('파티클 Instancing 미지원: ' + name)
            setattr(self, name, prototype(result, *arguments)(address))

    def _texture(self, unit, width, height, pixels=None, *, floating=True):
        self.glActiveTexture(0x84C0 + unit)
        self.glBindTexture(0x0DE1, self.textures[unit])
        for key, value in ((0x2801, 0x2600), (0x2800, 0x2600), (0x2802, 0x812F), (0x2803, 0x812F)):
            self.glTexParameteri(0x0DE1, key, value)
        self.glTexImage2D(0x0DE1, 0, 0x8814 if floating else 0x8058, width, height, 0,
                          0x1908, 0x1406 if floating else 0x1401, pixels)

    def _prepare(self, trails):
        if len(trails) > self.capacity:
            if not self.textures:
                names = (ct.c_uint * 3)()
                self.glGenTextures(3, names)
                self.textures = list(names)
                pixels = ct.create_string_buffer(build_particle_atlas())
                self._texture(0, *ATLAS_SIZE, pixels, floating=False)
                self.glTexParameteri(0x0DE1, 0x2801, 0x2601)
                self.glTexParameteri(0x0DE1, 0x2800, 0x2601)
            self.capacity = max(32, 1 << (len(trails) - 1).bit_length())
            self._texture(1, 201, self.capacity)
            self._texture(2, 1, self.capacity)
            self.slots.clear()
        alive = {id(trail) for trail in trails}
        self.slots = {key: value for key, value in self.slots.items() if key in alive}
        free = iter(sorted(set(range(self.capacity)) - {slot for _, slot in self.slots.values()}))
        self.glActiveTexture(0x84C1)
        self.glBindTexture(0x0DE1, self.textures[1])
        instances = []
        for trail in trails:
            key = id(trail)
            if key not in self.slots:
                slot = next(free)
                # 객체를 보존해 수명 중 id 재사용을 막고, 경로는 생성/용량 변경 때만 보낸다.
                self.slots[key] = trail, slot
                data = []
                distance = 0.0
                previous = trail.path_points[0]
                for point in trail.path_points:
                    distance += hypot(point[0] - previous[0], point[1] - previous[1])
                    data.extend((*point, distance, 0))
                    previous = point
                pixels = (ct.c_float * len(data))(*data)
                self.glTexSubImage2D(0x0DE1, 0, 0, slot, 201, 1, 0x1908, 0x1406, pixels)
                self.path_uploads += 1
            slot = self.slots[key][1]
            instances.extend((trail.progress, slot, 0, 0))
        self.glActiveTexture(0x84C2)
        self.glBindTexture(0x0DE1, self.textures[2])
        pixels = (ct.c_float * len(instances))(*instances)
        self.glTexSubImage2D(0x0DE1, 0, 0, 0, 1, len(trails), 0x1908, 0x1406, pixels)
        self.instance_upload_bytes = len(instances) * 4

    def render(self, trails, settings, color, core_color, scale):
        if not trails:
            self.slots.clear()
            return
        with self.batch():
            previous = []
            unpack_keys = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
            unpack = tuple(self.integer(key) for key in unpack_keys)
            unpack_buffer = self.integer(0x88EF)
            for unit in range(3):
                self.glActiveTexture(0x84C0 + unit)
                previous.append(self.integer(0x8069))
            try:
                # SDL 글자 업로드가 남긴 row length/skip/PBO 상태를 상속하지 않는다.
                self.glBindBuffer(0x88EC, 0)
                for key, value in zip(unpack_keys, (4, 0, 0, 0)):
                    self.glPixelStorei(key, value)
                self._prepare(trails)
                for unit, name in enumerate(('artwork', 'paths', 'instances')):
                    self.glActiveTexture(0x84C0 + unit)
                    self.glBindTexture(0x0DE1, self.textures[unit])
                    self.glUniform1i(self.uniforms[name], unit)
                vx, vy, vw, vh = self.viewport
                self.glUniform4f(self.uniforms['transform'], vx, vy, *scale)
                self.glUniform4f(self.uniforms['baseColor'], *color)
                self.glUniform4f(self.uniforms['coreColor'], *core_color)
                self.glUniform1f(self.uniforms['headWidth'], settings['head_width_pixels'])
                self.glUniform1f(self.uniforms['orbRadius'], settings['orb_radius_pixels'])
                self.glUniform1f(self.uniforms['tailFraction'], settings['tail_fraction'])
                self.glUniform1i(self.uniforms['segments'], settings['samples'])
                self.glUniform1i(self.uniforms['particleCount'], len(trails))
                self.glUniform1i(self.uniforms['mode'], 0)
                self.glDrawArraysInstanced(0x0005, 0, (settings['samples'] + 1) * 2, len(trails) * 2)
                self.glUniform1i(self.uniforms['mode'], 1)
                self.glDrawArraysInstanced(0x0005, 0, 4, len(trails) * 3)
            finally:
                for key, value in zip(unpack_keys, unpack):
                    self.glPixelStorei(key, value)
                self.glBindBuffer(0x88EC, unpack_buffer)
                for unit, texture in enumerate(previous):
                    self.glActiveTexture(0x84C0 + unit)
                    self.glBindTexture(0x0DE1, texture)
                self.glActiveTexture(0x84C0)

    def close(self):
        if self.textures:
            names = (ct.c_uint * len(self.textures))(*self.textures)
            self.glDeleteTextures(len(names), names)
            self.textures.clear()
        self.slots.clear()
        if self.program:
            self.glDeleteProgram(self.program)
            self.program = 0

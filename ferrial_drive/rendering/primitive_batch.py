"""순서를 보존하는 2D 도형 배치와 공통 쿼드 인스턴싱. 텍스트는 마지막 층이다."""

from contextlib import contextmanager
import ctypes as ct
from math import cos, hypot, sin, tau

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from .canvas import renderer_name
from .gl_pass import SdlOpenGLPass
from .hud_batch import HudBatchQueue
from .hud_text_atlas import HudTextAtlas


VERTEX_SHADER = b'''#version 330
uniform vec2 outputSize;
uniform float targetFlip;
uniform sampler2D instances;
uniform vec4 transform;
out vec4 ink;
void main() {
    vec4 geometry = texelFetch(instances, ivec2(0, gl_InstanceID), 0);
    ink = texelFetch(instances, ivec2(1, gl_InstanceID), 0);
    float kind = texelFetch(instances, ivec2(2, gl_InstanceID), 0).x;
    vec2 corner = vec2(float(gl_VertexID / 2), float(gl_VertexID % 2));
    vec2 point;
    if (kind < 0.5) {
        point = mix(geometry.xy, geometry.zw, corner);
    } else {
        vec2 delta = geometry.zw - geometry.xy;
        float size = length(delta);
        vec2 axis = size > 0.00001 ? delta / size : vec2(1.0, 0.0);
        vec2 normal = vec2(-axis.y, axis.x);
        point = mix(geometry.xy, geometry.zw, corner.x)
              + axis * (corner.x - 0.5) + normal * (corner.y - 0.5);
    }
    vec2 screen = transform.xy + point * transform.zw;
    vec2 ndc = screen / outputSize;
    gl_Position = vec4(ndc.x * 2.0 - 1.0, (1.0 - ndc.y * 2.0) * targetFlip, 0.0, 1.0);
}
'''

FRAGMENT_SHADER = b'''#version 330
in vec4 ink;
out vec4 result;
void main() { result = ink; }
'''


def primitive_points(row):
    """인스턴스와 SDL 배치가 같은 쿼드·선 끝 정사각형을 사용한다."""
    x1, y1, x2, y2 = row[:4]
    if row[8] == 0:
        return ((x1, y1), (x1, y2), (x2, y2), (x2, y1))
    length = hypot(x2 - x1, y2 - y1)
    dx, dy = ((x2 - x1) / length, (y2 - y1) / length) if length > 1e-5 else (1, 0)
    return tuple((x1 + (x2 - x1) * along + dx * (along - .5) - dy * (edge - .5),
                  y1 + (y2 - y1) * along + dy * (along - .5) + dx * (edge - .5))
                 for along, edge in ((0, 0), (0, 1), (1, 1), (1, 0)))


class PrimitiveInstances(SdlOpenGLPass):
    def __init__(self, pico):
        self.texture = 0
        self.capacity = 0
        super().__init__(pico, vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER,
                         extra_uniforms=("instances", "transform"))

    def _bind_functions(self):
        super()._bind_functions()
        self.max_rows = self.integer(0x0D33)  # GL_MAX_TEXTURE_SIZE
        uint, integer, pointer = ct.c_uint, ct.c_int, ct.c_void_p
        signatures = {
            'glGenTextures': (None, [integer, pointer]), 'glDeleteTextures': (None, [integer, pointer]),
            'glTexParameteri': (None, [uint, uint, integer]),
            'glTexImage2D': (None, [uint, integer, integer, integer, integer, integer, uint, uint, pointer]),
            'glTexSubImage2D': (None, [uint, integer, integer, integer, integer, integer, uint, uint, pointer]),
            'glDrawArraysInstanced': (None, [uint, integer, integer, integer]),
            'glPixelStorei': (None, [uint, integer]), 'glBindBuffer': (None, [uint, uint]),
        }
        for name, (result, arguments) in signatures.items():
            setattr(self, name, bind_gl(self.pico, name, result, arguments))

    def render(self, data, count, capacity, *, vertices=4, primitive=0x0005, instances_per_row=1):
        if not count:
            return 0
        capacity = min(capacity, self.max_rows)
        with self.batch():
            keys = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
            unpack, buffer = tuple(self.integer(key) for key in keys), self.integer(0x88EF)
            try:
                self.glBindBuffer(0x88EC, 0)
                for key, value in zip(keys, (4, 0, 0, 0)):
                    self.glPixelStorei(key, value)
                if not self.texture:
                    texture = ct.c_uint()
                    self.glGenTextures(1, ct.byref(texture))
                    self.texture = texture.value
                self.glBindTexture(0x0DE1, self.texture)
                if capacity > self.capacity:
                    self.glTexParameteri(0x0DE1, 0x2801, 0x2600)
                    self.glTexParameteri(0x0DE1, 0x2800, 0x2600)
                    self.glTexImage2D(0x0DE1, 0, 0x8814, 3, capacity, 0, 0x1908, 0x1406, None)
                    self.capacity = capacity
                sx, sy = ct.c_float(), ct.c_float()
                self.pico.SDL_RenderGetScale(self.pico.renderer, ct.byref(sx), ct.byref(sy))
                self.glUniform1i(self.uniforms['instances'], 0)
                self.glUniform4f(self.uniforms['transform'], *self.viewport[:2], sx.value, sy.value)
                for start in range(0, count, capacity):
                    rows = min(count - start, capacity)
                    self.glTexSubImage2D(0x0DE1, 0, 0, 0, 3, rows, 0x1908, 0x1406, ct.byref(data, start * 48))
                    self.glDrawArraysInstanced(primitive, 0, vertices, rows * instances_per_row)
            finally:
                for key, value in zip(keys, unpack):
                    self.glPixelStorei(key, value)
                self.glBindBuffer(0x88EC, buffer)
        return (count + capacity - 1) // capacity

    def close(self):
        if self.texture:
            texture = ct.c_uint(self.texture)
            self.glDeleteTextures(1, ct.byref(texture))
            self.texture = 0
        super().close()
        self.capacity = 0


class PrimitiveBatch:
    """도형은 입력 순서로 한 배치, 글자는 뒤에 제출한다. 렌더러 수명은 외부 소유다."""
    def __init__(self, renderer, *, backend="auto"):
        if backend not in ("auto", "immediate", "batched", "instanced"):
            raise ValueError("도형 백엔드는 auto/immediate/batched/instanced다.")
        self.renderer = renderer
        self.pico = renderer.pico
        self.backend = ("instanced" if renderer_name(self.pico) == "opengl" else "batched") if backend == "auto" else backend
        if self.backend == "instanced" and renderer_name(self.pico) != "opengl":
            raise ValueError("도형 인스턴싱에는 SDL OpenGL 렌더러가 필요하다.")
        self.native = PrimitiveInstances(self.pico) if self.backend == "instanced" else None
        self.queue = HudBatchQueue(self.pico) if self.backend == "batched" else None
        self.capacity = self.count = 0
        self.data = None
        self.texts = []
        self.label_atlas = None
        self.stats = {}

    @contextmanager
    def frame(self):
        self.count = 0
        self.texts.clear()
        self.stats = dict(backend=self.backend, primitives=0, geometry_submits=0, text_submits=0,
                          instance_upload_bytes=0, buffer_allocations=0)
        try:
            yield self
            self.flush()
        finally:
            self.count = 0
            self.texts.clear()

    def _append(self, geometry, color, opacity, kind):
        if self.count == self.capacity:
            capacity = max(1024, self.capacity * 2)
            data = (ct.c_float * (capacity * 12))()
            if self.data is not None:
                ct.memmove(data, self.data, self.count * 48)
            self.data, self.capacity = data, capacity
            self.stats['buffer_allocations'] += 1
        rgba = self.renderer.rgba(color, opacity)
        row = (*geometry, *(channel / 255 for channel in rgba), kind, 0, 0, 0)
        offset = self.count * 12
        for index, value in enumerate(row):
            self.data[offset + index] = value
        self.count += 1
        self.stats['primitives'] += 1

    def line(self, x1, y1, x2, y2, color, opacity=1):
        if self.backend == "immediate":
            self.stats['primitives'] += 1
            return self.renderer.line(x1, y1, x2, y2, color, opacity)
        self._append((round(x1) + .5, round(y1) + .5, round(x2) + .5, round(y2) + .5), color, opacity, 1)

    def rect(self, rect, color, opacity=1, filled=True):
        if self.backend == "immediate":
            self.stats['primitives'] += 1
            return self.renderer.rect(rect, color, opacity, filled)
        x, y, width, height = (round(value) for value in (rect.x, rect.y, rect.width, rect.height))
        if width <= 0 or height <= 0:
            return
        if filled:
            self._append((x, y, x + width, y + height), color, opacity, 0)
        else:
            points = ((x, y), (x + width - 1, y), (x + width - 1, y + height - 1), (x, y + height - 1))
            for first, second in zip(points, points[1:] + points[:1]):
                self.line(*first, *second, color, opacity)

    def circle(self, x, y, radius, color, opacity=1):
        segments = max(24, round(radius * 2))
        for index in range(segments):
            first, second = tau * index / segments, tau * (index + 1) / segments
            self.line(x + cos(first) * radius, y + sin(first) * radius,
                      x + cos(second) * radius, y + sin(second) * radius, color, opacity)

    def text(self, *args, **kwargs):
        self.stats['text_submits'] += 1
        if self.backend == "immediate":
            return self.renderer.text(*args, **kwargs)
        self.texts.append((args, kwargs))

    def flush(self):
        self.renderer.flush_batch()
        if self.count and self.native:
            self.stats['geometry_submits'] += self.native.render(self.data, self.count, self.capacity)
            self.stats['instance_upload_bytes'] += self.count * 48
        elif self.count and self.queue:
            with self.queue.frame():
                for index in range(self.count):
                    row = self.data[index * 12:(index + 1) * 12]
                    rgba = tuple(round(value * 255) for value in row[4:8])
                    self.queue.polygon(primitive_points(row), rgba, separate_triangles=True)
            self.stats['geometry_submits'] += self.queue.stats['geometry_submits']
        if self.texts:
            if self.label_atlas is None and self.renderer.text_atlas is not None:
                self.label_atlas = HudTextAtlas(self.pico, self.renderer.flush_batch, size=2048)
            with self.renderer.hud_batch(text_atlas=self.label_atlas):
                for args, kwargs in self.texts:
                    self.renderer.text(*args, **kwargs)
        self.count = 0
        self.texts.clear()

    def close(self):
        if self.label_atlas is not None:
            self.label_atlas.close()
            self.label_atlas = None
        if self.native:
            self.native.close()
        if self.queue:
            self.queue.close()
        self.data = None
        self.capacity = self.count = 0
        self.texts.clear()

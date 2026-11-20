"""같은 아틀라스 영역을 기체별 위치와 보간율로 한 번에 그린다."""

import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from .gl_pass import SdlOpenGLPass


QUAD_LIMIT = 64
VERTEX = b"""#version 140
uniform vec2 outputSize;
uniform float targetFlip;
uniform vec4 destinations[QUAD_LIMIT], sourceRect, screenTransform;
#ifdef SOURCE_PER_INSTANCE
uniform vec4 sources[QUAD_LIMIT];
#endif
uniform vec4 poseTimes[QUAD_LIMIT];
out vec2 texel;
out float localPhase;
flat out int pairIndex;
void main() {
    vec2 corner=vec2(float(gl_VertexID / 2),float(gl_VertexID % 2));
    vec4 dest=destinations[gl_InstanceID];
    vec2 pixel=screenTransform.xy+(dest.xy+corner*dest.zw)*screenTransform.zw;
    vec2 p=pixel/outputSize;
    gl_Position=vec4(p.x*2.0-1.0,(1.0-p.y*2.0)*targetFlip,0.0,1.0);
#ifdef SOURCE_PER_INSTANCE
    vec4 src=sources[gl_InstanceID];
#else
    vec4 src=sourceRect;
#endif
    texel=src.xy+corner*src.zw;
    localPhase=poseTimes[gl_InstanceID].x;
    pairIndex=int(poseTimes[gl_InstanceID].y);
}
""".replace(b"QUAD_LIMIT", str(QUAD_LIMIT).encode())


class InstancedQuads(SdlOpenGLPass):
    def __init__(self, pico, *, fragment_shader, extra_uniforms, per_instance_source=False):
        fragment = fragment_shader.replace(b"#version 120", b"#version 140", 1)
        vertex = VERTEX.replace(b"#version 140", b"#version 140\n#define SOURCE_PER_INSTANCE", 1) if per_instance_source else VERTEX
        super().__init__(pico, vertex_shader=vertex, fragment_shader=fragment,
                         extra_uniforms=(*extra_uniforms, "destinations[0]", "poseTimes[0]", "sources[0]", "sourceRect", "screenTransform"))
        self.rects = (ct.c_float * (QUAD_LIMIT * 4))()
        self.sources = (ct.c_float * (QUAD_LIMIT * 4))() if per_instance_source else None
        self.times = (ct.c_float * (QUAD_LIMIT * 4))()
        self.submits = 0

    def _bind_functions(self):
        super()._bind_functions()
        args = [ct.c_int, ct.c_int, ct.c_void_p]
        self.uniform_rects = bind_gl(self.pico, "glUniform4fv", None, args)
        self.draw_instanced = bind_gl(self.pico, "glDrawArraysInstanced", None,
                                      [ct.c_uint, ct.c_int, ct.c_int, ct.c_int])
        uint, integer, pointer = ct.c_uint, ct.c_int, ct.c_void_p
        for name, args in (
            ("glGenTextures", [integer, pointer]), ("glDeleteTextures", [integer, pointer]),
            ("glTexParameteri", [uint, uint, integer]), ("glBindBuffer", [uint, uint]),
            ("glPixelStorei", [uint, integer]),
            ("glTexImage2D", [uint, integer, integer, integer, integer, integer, uint, uint, pointer]),
            ("glTexSubImage2D", [uint, integer, integer, integer, integer, integer, uint, uint, pointer]),
        ):
            setattr(self, name, bind_gl(self.pico, name, None, args))
        self.max_texture_size = self.integer(0x0D33)

    def upload_rows(self, table, width, height, rows):
        old_texture = self.integer(0x8069)
        settings = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
        unpack = tuple(self.integer(key) for key in settings)
        buffer = self.integer(0x88EF)
        try:
            self.glBindBuffer(0x88EC, 0)
            for key, value in zip(settings, (1, 0, 0, 0)):
                self.glPixelStorei(key, value)
            allocate = not table.value
            if allocate:
                self.glGenTextures(1, ct.byref(table))
            self.glBindTexture(0x0DE1, table.value)
            if allocate:
                for name in (0x2801, 0x2800):
                    self.glTexParameteri(0x0DE1, name, 0x2600)
                self.glTexImage2D(0x0DE1, 0, 0x8814, width, height, 0, 0x1908, 0x1406, None)
            for row, values in rows:
                self.glTexSubImage2D(0x0DE1, 0, 0, row, width, 1, 0x1908, 0x1406, values)
        finally:
            self.glBindTexture(0x0DE1, old_texture)
            for key, value in zip(settings, unpack):
                self.glPixelStorei(key, value)
            self.glBindBuffer(0x88EC, buffer)

    def draw_instances(self, bounds, instances, *, sources=None):
        p = self.pico
        vx, vy, vw, vh = self.viewport
        sx, sy = ct.c_float(), ct.c_float()
        p.SDL_RenderGetScale(p.renderer, ct.byref(sx), ct.byref(sy))
        self.glUniform4f(self.uniforms["screenTransform"], vx, vy, sx.value, sy.value)
        self.glUniform4f(self.uniforms["sourceRect"], *bounds)
        if p.SDL_RenderIsClipEnabled(p.renderer):
            clip = p.SDL_Rect()
            p.SDL_RenderGetClipRect(p.renderer, ct.byref(clip))
            vx, vy = vx + int(clip.x * sx.value), vy + int(clip.y * sy.value)
            vw, vh = int(clip.w * sx.value), int(clip.h * sy.value)
        self.glEnable(0x0C11)
        self.glScissor(vx, self.output_size[1] - vy - vh if self.target_flip > 0 else vy, vw, vh)
        for first in range(0, len(instances), QUAD_LIMIT):
            batch = instances[first:first + QUAD_LIMIT]
            for i, (rect, phase, first_sample) in enumerate(batch):
                offset = 4 * i
                self.rects[offset:offset + 4] = rect
                self.times[offset:offset + 2] = phase, first_sample
                if sources is not None:
                    self.sources[offset:offset + 4] = sources[first + i]
            if sources is not None:
                self.uniform_rects(self.uniforms["sources[0]"], len(batch), self.sources)
            self.uniform_rects(self.uniforms["destinations[0]"], len(batch), self.rects)
            self.uniform_rects(self.uniforms["poseTimes[0]"], len(batch), self.times)
            self.draw_instanced(0x0005, 0, 4, len(batch))
            self.submits += 1

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
flat out vec4 sourceBounds;
#endif
#ifdef TILE_PLACEMENTS
uniform vec4 anchorScale;
#endif
uniform vec4 poseTimes[QUAD_LIMIT];
#ifdef INSTANCE_TABLE
uniform samplerBuffer instanceTable;
uniform int instanceStart, screenDepthReady;
uniform vec2 depthOrigin;
#endif
#ifdef SCREEN_DEPTH
uniform vec4 screenPlacements[QUAD_LIMIT];
flat out vec3 screenPlacement;
#endif
out vec2 texel;
out float localPhase;
flat out int pairIndex;
void main() {
    vec2 corner=vec2(float(gl_VertexID / 2),float(gl_VertexID % 2));
#ifdef INSTANCE_TABLE
    int row=3*(instanceStart+gl_InstanceID);
    vec4 screenRect=texelFetch(instanceTable,row);
    vec4 sheetRect=texelFetch(instanceTable,row+1);
    vec4 pose=texelFetch(instanceTable,row+2);
    localPhase=pose.x;
    pairIndex=int(pose.y);
    vec4 src=sourceRect;
#ifdef COVERAGE_INSTANCES
    vec4 dest=screenRect;
    dest.xy-=depthOrigin;
    screenPlacement=vec3(0.0,0.0,pose.z);
#else
    vec4 dest=sheetRect;
    screenPlacement=vec3(screenRect.xy-sheetRect.xy-depthOrigin,screenDepthReady!=0?pose.z*pose.w:0.0);
#endif
    vec2 pos=dest.xy+corner*dest.zw;
#else
    vec4 dest=destinations[gl_InstanceID];
#ifdef TILE_PLACEMENTS
    vec4 src=sources[int(dest.z)];
    vec2 pos=dest.xy+(src.xy-anchorScale.xy)*anchorScale.z+corner*max(vec2(1.0),src.zw*anchorScale.z);
    pairIndex=int(dest.w);
    localPhase=0.0;
#else
    vec2 pos=dest.xy+corner*dest.zw;
#ifdef SOURCE_PER_INSTANCE
    vec4 src=sources[gl_InstanceID];
#else
    vec4 src=sourceRect;
#endif
    localPhase=poseTimes[gl_InstanceID].x;
    pairIndex=int(poseTimes[gl_InstanceID].y);
#endif
#ifdef SCREEN_DEPTH
    screenPlacement=screenPlacements[gl_InstanceID].xyz;
#endif
#endif
    vec2 p=(screenTransform.xy+pos*screenTransform.zw)/outputSize;
    gl_Position=vec4(p.x*2.0-1.0,(1.0-p.y*2.0)*targetFlip,0.0,1.0);
#ifdef SCREEN_DEPTH
    gl_Position.z=2.0*screenPlacement.z-1.0;
#endif
    texel=src.xy+corner*src.zw;
#ifdef SOURCE_PER_INSTANCE
    sourceBounds=vec4(src.xy,src.xy+src.zw);
#endif
}
""".replace(b"QUAD_LIMIT", str(QUAD_LIMIT).encode())


class InstancedQuads(SdlOpenGLPass):
    def __init__(self, pico, *, fragment_shader, extra_uniforms, per_instance_source=False, tile_placements=False,
                 screen_depth=False, instance_table=False, coverage_instances=False):
        fragment = fragment_shader.replace(b"#version 120", b"#version 140", 1)
        defines = b""
        if per_instance_source or tile_placements:
            defines += b"\n#define SOURCE_PER_INSTANCE"
        if tile_placements:
            defines += b"\n#define TILE_PLACEMENTS"
        if screen_depth:
            defines += b"\n#define SCREEN_DEPTH"
            extra_uniforms = (*extra_uniforms, "screenPlacements[0]")
        if instance_table:
            defines += b"\n#define INSTANCE_TABLE"
            if coverage_instances:
                defines += b"\n#define COVERAGE_INSTANCES"
            extra_uniforms = (*extra_uniforms, "instanceTable", "instanceStart", "depthOrigin", "screenDepthReady")
        vertex = VERTEX.replace(b"#version 140", b"#version 140" + defines, 1)
        super().__init__(pico, vertex_shader=vertex, fragment_shader=fragment,
                         extra_uniforms=(*extra_uniforms, "destinations[0]", "poseTimes[0]", "sources[0]",
                                         "sourceRect", "screenTransform", "anchorScale"))
        self.rects = (ct.c_float * (QUAD_LIMIT * 4))()
        self.sources = (ct.c_float * (QUAD_LIMIT * 4))() if per_instance_source or tile_placements else None
        self.times = (ct.c_float * (QUAD_LIMIT * 4))()
        self.screen_placements = (ct.c_float * (QUAD_LIMIT * 4))() if screen_depth and not instance_table else None
        self.submits = 0
        self.instance_uploads = self.instance_upload_bytes = 0

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

    def _set_screen_transform(self):
        p = self.pico
        vx, vy, vw, vh = self.viewport
        sx, sy = ct.c_float(), ct.c_float()
        p.SDL_RenderGetScale(p.renderer, ct.byref(sx), ct.byref(sy))
        self.glUniform4f(self.uniforms["screenTransform"], vx, vy, sx.value, sy.value)
        if p.SDL_RenderIsClipEnabled(p.renderer):
            clip = p.SDL_Rect()
            p.SDL_RenderGetClipRect(p.renderer, ct.byref(clip))
            vx, vy = vx + int(clip.x * sx.value), vy + int(clip.y * sy.value)
            vw, vh = int(clip.w * sx.value), int(clip.h * sy.value)
        self.glEnable(0x0C11)
        self.glScissor(vx, self.output_size[1] - vy - vh if self.target_flip > 0 else vy, vw, vh)

    def draw_tile_placements(self, groups, pivot, scale):
        """포즈당 원본 영역 하나와 기체별 발 위치·깊이 타일만 보낸다."""
        if len(groups) > QUAD_LIMIT:
            raise ValueError("한 번에 보낼 그림자 영역 수를 초과했다.")
        self._set_screen_transform()
        self.glUniform4f(self.uniforms["anchorScale"], *pivot, scale, 0)
        for index, (source, _, _) in enumerate(groups):
            self.sources[index * 4:index * 4 + 4] = source
        self.uniform_rects(self.uniforms["sources[0]"], len(groups), self.sources)
        count = 0
        for index, (_, slot, positions) in enumerate(groups):
            for x, y in positions:
                self.rects[count * 4:count * 4 + 4] = x, y, index, slot
                count += 1
                if count == QUAD_LIMIT:
                    self._submit_rects(count)
                    count = 0
        if count:
            self._submit_rects(count)

    def _submit_rects(self, count):
        self.uniform_rects(self.uniforms["destinations[0]"], count, self.rects)
        self.draw_instanced(0x0005, 0, 4, count)
        self.submits += 1

    def draw_rectangles(self, regions):
        """포즈 데이터 없이 서로 다른 텍스처 영역을 묶는다."""
        self._set_screen_transform()
        for first in range(0, len(regions), QUAD_LIMIT):
            chunk = regions[first:first + QUAD_LIMIT]
            for i, (source, destination) in enumerate(chunk):
                offset = i * 4
                self.sources[offset:offset + 4] = source
                self.rects[offset:offset + 4] = destination
            self.uniform_rects(self.uniforms["sources[0]"], len(chunk), self.sources)
            self._submit_rects(len(chunk))

    def draw_instances(self, bounds, instances, *, sources=None, screen_placements=None):
        self._set_screen_transform()
        self.glUniform4f(self.uniforms["sourceRect"], *bounds)
        for first in range(0, len(instances), QUAD_LIMIT):
            batch = instances[first:first + QUAD_LIMIT]
            for i, (rect, phase, first_sample) in enumerate(batch):
                offset = 4 * i
                self.rects[offset:offset + 4] = rect
                self.times[offset:offset + 2] = phase, first_sample
                if sources is not None:
                    self.sources[offset:offset + 4] = sources[first + i]
                if self.screen_placements is not None:
                    self.screen_placements[offset:offset + 4] = (
                        (0, 0, 0, 0) if screen_placements is None else screen_placements[first + i])
            if sources is not None:
                self.uniform_rects(self.uniforms["sources[0]"], len(batch), self.sources)
            if self.screen_placements is not None:
                self.uniform_rects(self.uniforms["screenPlacements[0]"], len(batch), self.screen_placements)
            self.uniform_rects(self.uniforms["poseTimes[0]"], len(batch), self.times)
            self._submit_rects(len(batch))
            arrays = 2 + int(self.screen_placements is not None) + int(sources is not None)
            self.instance_uploads += arrays
            self.instance_upload_bytes += arrays * len(batch) * 16

    def draw_instance_range(self, bounds, start, count, depth_origin, depth_ready):
        self._set_screen_transform()
        uniforms = self.uniforms
        self.glUniform4f(uniforms["sourceRect"], *bounds)
        self.glUniform1i(uniforms["instanceStart"], start)
        self.glUniform2f(uniforms["depthOrigin"], *depth_origin)
        self.glUniform1i(uniforms["screenDepthReady"], int(depth_ready))
        self.draw_instanced(0x0005, 0, 4, count)
        self.submits += 1

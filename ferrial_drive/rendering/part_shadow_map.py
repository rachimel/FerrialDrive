"""파츠 표면과 지면 투영에 필요한 광원 깊이 맵을 그린다."""

import ctypes as ct
from collections import OrderedDict
from contextlib import contextmanager
from math import ceil, cos, floor, hypot, radians, sin
from struct import Struct

from ferrial_drive.diagnostics.texture_metrics import bind_gl
from .gl_pass import SdlOpenGLPass, TexturedQuadPass
from .direction_reprojection import dot


DEPTH_SIZE = 512
GROUND_SHADOW_SCALE = 0.5
LIGHT_VECTOR = (.40, .60, 1.0)
DEPTH_RANGE_CM = 1500
SHADOW_UNIFORMS = ("lightDepth", "lightRight", "lightUp", "lightNear", "lightDirection",
                   "cameraOrigin", "cameraRight", "cameraUp", "cameraForward", "shadowOn", "shadowTexel",
                   "surfaceLightRight", "surfaceLightUp", "surfaceLightForward", "surfaceLightRange")
SURFACE_PROJECTION = b"""
uniform vec4 surfaceLightRight, surfaceLightUp, surfaceLightForward;
uniform vec2 surfaceLightRange;
vec4 surfaceLightClip(vec3 position) {
    vec4 point=vec4(position,1.0);
    float depth=dot(surfaceLightForward,point);
    float linearDepth=(depth-surfaceLightRange.x)*surfaceLightRange.y;
    return vec4(dot(surfaceLightRight,point),dot(surfaceLightUp,point),linearDepth*depth,depth);
}
vec3 surfaceLightCoordinates(vec3 point) {
    vec4 clip=surfaceLightClip(point);
    if(clip.w<=0.0) return vec3(-1.0);
    return clip.xyz/clip.w*0.5+0.5;
}
"""
SHADOW_FUNCTIONS = b"""
uniform sampler2D lightDepth;
uniform vec4 lightRight, lightUp, lightNear, lightDirection;
uniform vec4 cameraOrigin, cameraRight, cameraUp, cameraForward;
uniform float shadowOn, shadowTexel;
vec3 worldAt(vec2 pixel, float depth) {
    return cameraOrigin.xyz+cameraRight.xyz*pixel.x+cameraUp.xyz*pixel.y+cameraForward.xyz*depth;
}
vec3 lightCoordinates(vec3 point) {
    vec4 p=vec4(point,1.0);
    return vec3(dot(lightRight,p),dot(lightUp,p),dot(lightNear,p))*0.5+0.5;
}
""" + SURFACE_PROJECTION + b"""
float visibilityAtCoordinates(vec3 s) {
    if(shadowOn<0.5) return 1.0;
    if(any(lessThan(s,vec3(0.0)))||any(greaterThan(s,vec3(1.0)))) return 1.0;
    s.z-=0.004;
    return 0.25*(
        step(s.z,texture2D(lightDepth,s.xy+vec2(-0.5,-0.5)*shadowTexel).r)+
        step(s.z,texture2D(lightDepth,s.xy+vec2( 0.5,-0.5)*shadowTexel).r)+
        step(s.z,texture2D(lightDepth,s.xy+vec2(-0.5, 0.5)*shadowTexel).r)+
        step(s.z,texture2D(lightDepth,s.xy+vec2( 0.5, 0.5)*shadowTexel).r));
}
float visibilityAt(vec3 point) {
    return visibilityAtCoordinates(lightCoordinates(point));
}
float surfaceVisibilityAt(vec3 point) {
    return visibilityAtCoordinates(surfaceLightCoordinates(point));
}
"""
DEPTH_VERTEX = b"""#version 120
attribute vec3 shadowVertex;
void main() { gl_Position=vec4(shadowVertex,1.0); }
"""
PERSPECTIVE_BOX_VERTEX = b"""#version 120
attribute vec3 shadowVertex;
""" + SURFACE_PROJECTION + b"""
void main() { gl_Position=surfaceLightClip(shadowVertex); }
"""
DEPTH_FRAGMENT = b"""#version 120
void main() { gl_FragColor=vec4(1.0); }
"""
SURFACE_CASTER_VERTEX = b"""#version 130
uniform sampler2D casterSurface;
uniform vec4 casterGrid;
uniform vec2 casterOrigin;
uniform vec4 cameraOrigin, cameraRight, cameraUp, cameraForward;
""" + SURFACE_PROJECTION + b"""
void main() {
    int columns=int(casterGrid.x);
    ivec2 pixel=ivec2(gl_VertexID%columns,gl_VertexID/columns);
    vec4 encoded=texelFetch(casterSurface,pixel+ivec2(int(casterGrid.y)),0);
    gl_PointSize=casterGrid.z;
    if(encoded.a<0.5) {
        gl_Position=vec4(2.0,2.0,2.0,1.0);
        return;
    }
    float depth=dot(floor(encoded.rgb*255.0+0.5),vec3(65536.0,256.0,1.0))*0.25;
    vec2 source=casterOrigin+vec2(pixel)+0.5;
    vec3 point=cameraOrigin.xyz+cameraRight.xyz*source.x+cameraUp.xyz*source.y+cameraForward.xyz*depth;
    gl_Position=surfaceLightClip(point);
}
"""
SURFACE_CASTER_FRAGMENT = b"""#version 130
void main() { gl_FragColor=vec4(1.0); }
"""
GROUND_FRAGMENT = b"""#version 120
uniform float opacity, perspectiveGround, groundShadowRadius;
varying vec2 texel;
""" + SHADOW_FUNCTIONS + b"""
float projectedVisibility(vec3 point) {
    vec3 s=surfaceLightCoordinates(point);
    if(any(lessThan(s,vec3(0.0)))||any(greaterThan(s,vec3(1.0)))) return 1.0;
    s.z-=0.004;
    float sum=0.0;
    for(int y=-1;y<=1;++y) {
        for(int x=-1;x<=1;++x) {
            vec2 offset=vec2(float(x),float(y));
            float weight=(2.0-abs(offset.x))*(2.0-abs(offset.y));
            sum+=weight*step(s.z,texture2D(lightDepth,s.xy+offset*groundShadowRadius).r);
        }
    }
    return sum/16.0;
}
void main() {
    vec3 point=worldAt(texel,0.0);
    point-=cameraForward.xyz*(point.z/cameraForward.z);
    float visibility=perspectiveGround>0.5 ? projectedVisibility(point) : visibilityAt(point);
    gl_FragColor=vec4(0.0,0.0,0.0,opacity*(1.0-visibility));
}
"""


def unit(values):
    length = hypot(*values)
    return tuple(value / length for value in values)


def cross(a, b):
    ax, ay, az = a
    bx, by, bz = b
    return ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx


def interpolate_rotation(a, b, weight):
    # 같은 회전을 나타내는 두 부호 중 가까운 쪽을 보간한다.
    sign = 1 if dot(a, b) >= 0 else -1
    x, y, z, w = (start * (1 - weight) + end * (sign * weight) for start, end in zip(a, b))
    factor = 2 / (x * x + y * y + z * z + w * w)
    xx, xy, xz, xw = factor * x * x, factor * x * y, factor * x * z, factor * x * w
    yy, yz, yw = factor * y * y, factor * y * z, factor * y * w
    zz, zw = factor * z * z, factor * z * w
    return ((1 - yy - zz, xy - zw, xz + yw),
            (xy + zw, 1 - xx - zz, yz - xw),
            (xz - yw, yz + xw, 1 - xx - yy))


class PartShadowMap:
    """리그의 축 정렬 바운드를 포즈에 맞춰 광원 깊이로 그린다."""

    def __init__(self, pico, data, *, scale, light_vector=LIGHT_VECTOR, caster_bones=None, surface_light_position=None):
        self.pico = pico
        self.size = max(1, round(DEPTH_SIZE * scale))
        self.ground_size = round(DEPTH_SIZE * GROUND_SHADOW_SCALE) if surface_light_position is not None else self.size
        camera = data["surface_camera"]
        self.forward = unit(tuple(target - origin for target, origin in zip(camera["target"], camera["position"])))
        right = unit((-self.forward[1], self.forward[0], 0))
        up = cross(self.forward, right)
        width, height = data["size"]
        cm_per_pixel = camera["width_cm"] / width
        self.caster_point_size = max(1, ceil(1.4 * cm_per_pixel * self.size / DEPTH_RANGE_CM))
        self.camera_x = tuple(component * cm_per_pixel for component in right)
        self.camera_y = tuple(-component * cm_per_pixel for component in up)
        self.camera_zero = tuple(
            origin - forward * camera["depth_offset_cm"] - dx * width / 2 - dy * height / 2
            for origin, forward, dx, dy in zip(camera["position"], self.forward, self.camera_x, self.camera_y)
        )
        self.light = unit(light_vector)
        light_right = unit(cross((0, 0, 1), self.light))
        light_up = cross(self.light, light_right)
        self.light_matrix = tuple(tuple(component * (2 / DEPTH_RANGE_CM) for component in axis)
                                  for axis in (light_right, light_up, tuple(-value for value in self.light)))
        self.light_origin = tuple(row[2] * 220 for row in self.light_matrix)
        self.surface_light_position = surface_light_position
        if surface_light_position is not None:
            lx, ly, lz = surface_light_position
            to_light = (lx, ly, lz - 220)
            distance = hypot(*to_light)
            toward = unit(to_light)
            sx = unit(cross((0, 0, 1), toward)) if lx or ly else (1, 0, 0)
            sy = cross(toward, sx)
            scale_xy = 2 * distance / DEPTH_RANGE_CM
            rows = (tuple(value * scale_xy for value in sx), tuple(value * scale_xy for value in sy),
                    tuple(-value for value in toward))
            self.surface_light_matrix = tuple((*row, -dot(row, surface_light_position)) for row in rows)
            self.surface_light_range = distance, 2 / DEPTH_RANGE_CM
        # 광선 방향으로 지면에 투영한 뒤 화면 픽셀로 바꾸는 두 축이다.
        self.ground_axes = tuple(
            (axis[0] / dot(axis, axis), axis[1] / dot(axis, axis),
             -(axis[0] * self.light[0] + axis[1] * self.light[1]) / (self.light[2] * dot(axis, axis)))
            for axis in (self.camera_x, self.camera_y)
        )
        self.pivot = data["pivot_top_left"]
        self.pixel_scale = data["pixel_scale"]
        proxy = data["shadow_proxy"]
        bones = proxy["bones"]
        self.caster_bones = tuple(bones if caster_bones is None else caster_bones)
        self.caster_indices = tuple(bones.index(bone) for bone in self.caster_bones)
        bounds = (proxy["bounds"][index] for index in self.caster_indices)
        self.corners = [tuple(tuple((lo + hi) * .5 + (hi - lo) * (.43 if index & (1 << axis) else -.43)
                                    for axis, (lo, hi) in enumerate(zip(low, high)))
                              for index in range(8))
                        for low, high in bounds]
        self.triangles = (
            0, 2, 3, 0, 3, 1, 4, 5, 7, 4, 7, 6, 0, 1, 5, 0, 5, 4,
            2, 6, 7, 2, 7, 3, 0, 4, 6, 0, 6, 2, 1, 3, 7, 1, 7, 5)
        self.vertex_count = len(self.corners) * len(self.triangles)
        self.vertex_data = Struct(f"={self.vertex_count * 3}f")
        self.waist = bones.index(proxy.get("anchor_bone", "waist"))
        self.tracks = {}
        for name, row in proxy["clips"].items():
            upper_bones = set(row.get("upper_bones", bones))
            self.tracks[name] = row["hz"], row["poses"], tuple(bone in upper_bones for bone in bones)
        self.texture, self.surface_texture = ct.c_uint(), ct.c_uint()
        self.framebuffer = ct.c_uint()
        self.buffer = ct.c_uint()
        self.vao = ct.c_uint()
        self.depth_sampler = self.ground_sampler = self.surface_sampler = None
        self.pose_key = None
        self.ground_geometry = OrderedDict()
        self.ground_bounds = None
        self.depth_draws = self.ground_draws = self.surface_draws = 0
        self.projected_ground_draws = 0
        self.ground_geometry_hits = 0
        self.enabled = True
        try:
            self._bind()
            box_vertex = PERSPECTIVE_BOX_VERTEX if surface_light_position is not None else DEPTH_VERTEX
            self.depth_sampler = SdlOpenGLPass(pico, fragment_shader=DEPTH_FRAGMENT, vertex_shader=box_vertex,
                                                extra_uniforms=SHADOW_UNIFORMS)
            self.ground_sampler = TexturedQuadPass(pico, fragment_shader=GROUND_FRAGMENT,
                                                 extra_uniforms=SHADOW_UNIFORMS + (
                                                     "opacity", "perspectiveGround", "groundShadowRadius"))
            if surface_light_position is not None:
                self.surface_sampler = SdlOpenGLPass(pico, fragment_shader=SURFACE_CASTER_FRAGMENT, vertex_shader=SURFACE_CASTER_VERTEX,
                    extra_uniforms=SHADOW_UNIFORMS + ("casterSurface", "casterGrid", "casterOrigin"))
            self._allocate()
        except BaseException:
            self.close()
            raise

    def _bind(self):
        u, i, f, p = ct.c_uint, ct.c_int, ct.c_float, ct.c_void_p
        for name, result, args in (
            ("GenTextures", None, [i, p]), ("DeleteTextures", None, [i, p]),
            ("TexImage2D", None, [u, i, i, i, i, i, u, u, p]), ("TexParameteri", None, [u, u, i]),
            ("GenFramebuffers", None, [i, p]), ("DeleteFramebuffers", None, [i, p]),
            ("BindFramebuffer", None, [u, u]), ("FramebufferTexture2D", None, [u, u, u, u, i]),
            ("CheckFramebufferStatus", u, [u]), ("DrawBuffer", None, [u]), ("ReadBuffer", None, [u]),
            ("GenVertexArrays", None, [i, p]), ("DeleteVertexArrays", None, [i, p]), ("BindVertexArray", None, [u]),
            ("GenBuffers", None, [i, p]), ("DeleteBuffers", None, [i, p]), ("BindBuffer", None, [u, u]),
            ("BufferData", None, [u, ct.c_size_t, p, u]), ("BufferSubData", None, [u, ct.c_size_t, ct.c_size_t, p]),
            ("GetAttribLocation", i, [u, ct.c_char_p]), ("EnableVertexAttribArray", None, [u]),
            ("VertexAttribPointer", None, [u, i, u, ct.c_ubyte, i, p]),
            ("DepthMask", None, [ct.c_ubyte]), ("DepthFunc", None, [u]), ("ClearDepth", None, [ct.c_double]),
            ("GetDoublev", None, [u, p]), ("Clear", None, [u]), ("DrawArrays", None, [u, i, i]),
        ):
            setattr(self, name, bind_gl(self.pico, "gl" + name, result, args))

    @property
    def storage_bytes(self):
        return (self.ground_size ** 2 + (self.size ** 2 if self.surface_texture.value else 0)) * 4

    def _allocate(self):
        s = self.depth_sampler
        self.GenFramebuffers(1, ct.byref(self.framebuffer))
        self.GenBuffers(1, ct.byref(self.buffer))
        self.GenVertexArrays(1, ct.byref(self.vao))
        bound = s.integer(0x8069)
        previous_draw, previous_read = s.integer(0x8CA6), s.integer(0x8CAA)
        previous_vao, previous_buffer = s.integer(0x85B5), s.integer(0x8894)
        try:
            maps = [(self.texture, self.ground_size)]
            if self.surface_sampler:
                maps.append((self.surface_texture, self.size))
            for texture, size in maps:
                self.GenTextures(1, ct.byref(texture))
                s.glBindTexture(0x0DE1, texture.value)
                self.TexImage2D(0x0DE1, 0, 0x8CAC, size, size, 0, 0x1902, 0x1406, None)
                for parameter, value in ((0x2801, 0x2600), (0x2800, 0x2600), (0x2802, 0x812F), (0x2803, 0x812F)):
                    self.TexParameteri(0x0DE1, parameter, value)
            self.BindFramebuffer(0x8D40, self.framebuffer.value)
            self.FramebufferTexture2D(0x8D40, 0x8D00, 0x0DE1, self.texture.value, 0)
            self.DrawBuffer(0)
            self.ReadBuffer(0)
            if self.CheckFramebufferStatus(0x8D40) != 0x8CD5:
                raise RuntimeError("그림자 깊이 프레임버퍼 생성 실패")
            self.BindVertexArray(self.vao.value)
            self.BindBuffer(0x8892, self.buffer.value)
            self.BufferData(0x8892, self.vertex_data.size, None, 0x88E8)
            position = self.GetAttribLocation(s.program, b"shadowVertex")
            self.EnableVertexAttribArray(position)
            self.VertexAttribPointer(position, 3, 0x1406, 0, 12, None)
        finally:
            self.BindBuffer(0x8892, previous_buffer)
            self.BindVertexArray(previous_vao)
            self.BindFramebuffer(0x8CA9, previous_draw)
            self.BindFramebuffer(0x8CA8, previous_read)
            s.glBindTexture(0x0DE1, bound)

    def prepare(self, name, seconds, yaw, loop, duration, *, cache_geometry=False):
        if not self.enabled:
            return
        elapsed = seconds % duration if loop else min(seconds, duration)
        key = name, elapsed, yaw
        if key == self.pose_key:
            return
        vertices, self.ground_bounds = self.pose_geometry(key, cache_geometry)
        self.pico.SDL_RenderFlush(self.pico.renderer)
        self.render_depth(vertices)
        self.pose_key = key

    def pose_geometry(self, key, cache_geometry):
        geometry = self.ground_geometry.get(key) if cache_geometry else None
        if geometry is None:
            name, elapsed, yaw = key
            hz, poses, upper = self.tracks[name]
            index = min(floor(elapsed * hz), len(poses) - 1)
            weight = elapsed * hz - index
            a, b = poses[index], poses[min(index + 1, len(poses) - 1)]
            geometry = self.project_pose(a, b, weight, upper, yaw)
            if cache_geometry:
                self.ground_geometry[key] = geometry
                if len(self.ground_geometry) > 128:
                    self.ground_geometry.popitem(last=False)
        else:
            self.ground_geometry.move_to_end(key)
            self.ground_geometry_hits += 1
        return geometry

    def project_pose(self, a, b, weight, upper, yaw):
        upper_angle, lower_angle = map(radians, yaw)
        upper_c, upper_s = cos(upper_angle), sin(upper_angle)
        lower_c, lower_s = cos(lower_angle), sin(lower_angle)
        waist_x, waist_y = (first * (1 - weight) + second * weight
                           for first, second in zip(a[self.waist][:2], b[self.waist][:2]))
        shift_x = (lower_c - upper_c) * waist_x - (lower_s - upper_s) * waist_y
        shift_y = (lower_s - upper_s) * waist_x + (lower_c - upper_c) * waist_y
        (gx, gy, gz), (hx, hy, hz) = self.ground_axes
        (lx, ly, lz), (ux, uy, uz), (nx, ny, nz) = self.light_matrix
        light_x, light_y, light_z = self.light_origin
        perspective = self.surface_light_position is not None
        if perspective:
            key_x, key_y, key_z = self.surface_light_position
        vertices, pixel_xs, pixel_ys = [], [], []
        for index, corners in zip(self.caster_indices, self.corners):
            start, end = a[index], b[index]
            tx, ty, tz = (first * (1 - weight) + second * weight
                          for first, second in zip(start[:3], end[:3]))
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = interpolate_rotation(start[3:], end[3:], weight)
            c, s, dx, dy = (upper_c, upper_s, shift_x, shift_y) if upper[index] else (lower_c, lower_s, 0, 0)
            projected = []
            for x, y, z in corners:
                px = ax * x + ay * y + az * z + tx
                py = bx * x + by * y + bz * z + ty
                pz = cx * x + cy * y + cz * z + tz
                wx, wy = c * px - s * py + dx, s * px + c * py + dy
                if perspective:
                    cast = key_z / max(1.0, key_z - pz)
                    floor_x, floor_y = key_x + (wx - key_x) * cast, key_y + (wy - key_y) * cast
                    pixel_xs.append(gx * floor_x + gy * floor_y)
                    pixel_ys.append(hx * floor_x + hy * floor_y)
                    projected.append((wx, wy, pz))
                else:
                    pixel_xs.append(gx * wx + gy * wy + gz * pz)
                    pixel_ys.append(hx * wx + hy * wy + hz * pz)
                    projected.append((lx * wx + ly * wy + lz * pz - light_x,
                                      ux * wx + uy * wy + uz * pz - light_y,
                                      nx * wx + ny * wy + nz * pz - light_z))
            for corner in self.triangles:
                vertices.extend(projected[corner])
        pivot_x, pivot_y = self.pivot
        left, top = floor(min(pixel_xs) + pivot_x) - 3, floor(min(pixel_ys) + pivot_y) - 3
        right, bottom = ceil(max(pixel_xs) + pivot_x) + 3, ceil(max(pixel_ys) + pivot_y) + 3
        return self.vertex_data.pack(*vertices), (left, top, right - left, bottom - top)

    def render_depth(self, vertices, *, texture=None, tile=None):
        with self.depth_pass(self.depth_sampler, self.texture if texture is None else texture, self.ground_size, tile=tile):
            if self.surface_light_position is not None:
                self.upload_projection(self.depth_sampler)
            self.BindBuffer(0x8892, self.buffer.value)
            self.BufferSubData(0x8892, 0, len(vertices), vertices)
            self.DrawArrays(0x0004, 0, self.vertex_count)
        self.depth_draws += 1

    def render_surface(self, texture, bounds, border):
        s, p = self.surface_sampler, self.pico
        x, y, width, height = bounds
        p.SDL_RenderFlush(p.renderer)
        active = s.integer(0x84E0)
        s.glActiveTexture(0x84C0)
        previous = s.integer(0x8069)
        try:
            if p.SDL_GL_BindTexture(texture, None, None):
                raise RuntimeError("본체 깊이 텍스처를 그림자 셰이더에 연결할 수 없다.")
            try:
                with self.depth_pass(s, self.surface_texture, self.size, points=True):
                    s.glUniform1i(s.uniforms["casterSurface"], 0)
                    s.glUniform4f(s.uniforms["casterGrid"], width, border, self.caster_point_size, 0)
                    s.glUniform2f(s.uniforms["casterOrigin"], x, y)
                    self.upload_projection(s)
                    self.DrawArrays(0x0000, 0, width * height)
            finally:
                p.SDL_GL_UnbindTexture(texture)
        finally:
            s.glActiveTexture(0x84C0)
            s.glBindTexture(0x0DE1, previous)
            s.glActiveTexture(active)
        self.surface_draws += 1

    @contextmanager
    def depth_pass(self, s, texture, size, *, points=False, tile=None):
        viewport, program = s.integer(0x0BA2, 4), s.integer(0x8B8D)
        framebuffer, vao, buffer = s.integer(0x8CA6), s.integer(0x85B5), s.integer(0x8894)
        flags = {flag: s.glIsEnabled(flag) for flag in (0x0B71, 0x0B44, 0x0C11, 0x8642)}
        old_scissor = s.integer(0x0C10, 4) if tile is not None else None
        depth_mask, depth_func = s.integer(0x0B72), s.integer(0x0B74)
        clear = ct.c_double()
        self.GetDoublev(0x0B73, ct.byref(clear))
        try:
            self.BindFramebuffer(0x8CA9, self.framebuffer.value)
            self.FramebufferTexture2D(0x8CA9, 0x8D00, 0x0DE1, texture.value, 0)
            vx, vy = tile or (0, 0)
            s.glViewport(vx, vy, size, size)
            s.glDisable(0x0B44)
            if tile is None:
                s.glDisable(0x0C11)
            else:
                s.glEnable(0x0C11)
                s.glScissor(vx, vy, size, size)
            s.glEnable(0x0B71)
            if points:
                s.glEnable(0x8642)
            self.DepthMask(1)
            self.DepthFunc(0x0201)
            self.ClearDepth(1)
            self.Clear(0x00000100)
            s.glUseProgram(s.program)
            self.BindVertexArray(self.vao.value)
            yield
        finally:
            self.BindBuffer(0x8892, buffer)
            self.BindVertexArray(vao)
            s.glUseProgram(program)
            self.BindFramebuffer(0x8CA9, framebuffer)
            s.glViewport(*viewport)
            for flag, enabled in flags.items():
                (s.glEnable if enabled else s.glDisable)(flag)
            if old_scissor is not None:
                s.glScissor(*old_scissor)
            self.DepthMask(depth_mask)
            self.DepthFunc(depth_func)
            self.ClearDepth(clear.value)

    def upload_projection(self, sampler):
        for name, row, offset in zip(("lightRight", "lightUp", "lightNear"), self.light_matrix, self.light_origin):
            sampler.glUniform4f(sampler.uniforms[name], *row, -offset)
        for name, vector in (("cameraOrigin", self.camera_zero), ("cameraRight", self.camera_x),
                             ("cameraUp", self.camera_y), ("cameraForward", self.forward), ("lightDirection", self.light)):
            sampler.glUniform4f(sampler.uniforms[name], *vector, 0)
        if self.surface_light_position is not None:
            names = ("surfaceLightRight", "surfaceLightUp", "surfaceLightForward")
            for name, row in zip(names, self.surface_light_matrix, strict=True):
                sampler.glUniform4f(sampler.uniforms[name], *row)
            sampler.glUniform2f(sampler.uniforms["surfaceLightRange"], *self.surface_light_range)

    @contextmanager
    def bind_texture(self, sampler, unit_index, texture):
        sampler.glActiveTexture(0x84C0 + unit_index)
        old = sampler.integer(0x8069)
        try:
            sampler.glBindTexture(0x0DE1, texture.value)
            sampler.glActiveTexture(0x84C0)
            yield
        finally:
            sampler.glActiveTexture(0x84C0 + unit_index)
            sampler.glBindTexture(0x0DE1, old)
            sampler.glActiveTexture(0x84C0)

    @contextmanager
    def bind(self, sampler, unit_index, *, sample_shadow=True, surface=False):
        texture = self.surface_texture if surface else self.texture
        with self.bind_texture(sampler, unit_index, texture):
            sampler.glUniform1i(sampler.uniforms["lightDepth"], unit_index)
            sampler.glUniform1f(sampler.uniforms["shadowOn"], float(self.enabled and sample_shadow))
            sampler.glUniform1f(sampler.uniforms["shadowTexel"], 1 / (self.size if surface else self.ground_size))
            self.upload_projection(sampler)
            yield

    def draw_ground(self, x, y, scale, opacity, *, softness_pixels=0):
        return bool(self.draw_ground_many(((x, y),), scale, opacity, softness_pixels=softness_pixels))

    def ground_region(self, factor, softness_pixels, bounds=None):
        left, top, width, height = self.ground_bounds if bounds is None else bounds
        radius = 0.5 / self.ground_size
        if self.surface_light_position is not None:
            softness = max(0, softness_pixels) / factor if factor > 0 else 0
            padding = ceil(max(softness, radius * DEPTH_RANGE_CM / hypot(*self.camera_x)))
            radius = max(radius, softness * hypot(*self.camera_x) / DEPTH_RANGE_CM)
            left, top = left - padding, top - padding
            width, height = width + 2 * padding, height + 2 * padding
        return (left, top, width, height), radius

    def draw_ground_many(self, placements, scale, opacity, *, softness_pixels=0):
        if not self.enabled or self.ground_bounds is None:
            return 0
        p = self.pico
        factor = scale * self.pixel_scale
        pivot_x, pivot_y = self.pivot
        (left, top, width, height), radius = self.ground_region(factor, softness_pixels)
        perspective = self.surface_light_position is not None
        if perspective:
            self.projected_ground_draws += len(placements)
        source = p.SDL_Rect(left, top, width, height)
        offset_x, offset_y = (left - pivot_x) * factor, (top - pivot_y) * factor
        target = p.SDL_FRect(0, 0, max(1, width * factor), max(1, height * factor))
        sampler = self.ground_sampler
        with sampler.batch(), self.bind(sampler, 1):
            sampler.glUniform1f(sampler.uniforms["opacity"], opacity)
            sampler.glUniform1f(sampler.uniforms["perspectiveGround"], float(perspective))
            sampler.glUniform1f(sampler.uniforms["groundShadowRadius"], radius)
            for x, y in placements:
                target.x, target.y = x + offset_x, y + offset_y
                sampler.draw(None, (1, 1), source, target)
        self.ground_draws += len(placements)
        return len(placements)

    def close(self):
        self.ground_geometry.clear()
        for sampler in (self.depth_sampler, self.ground_sampler, self.surface_sampler):
            if sampler is not None:
                sampler.close()
        self.depth_sampler = self.ground_sampler = self.surface_sampler = None
        for name, value in (("Textures", self.texture), ("Textures", self.surface_texture), ("Framebuffers", self.framebuffer),
                            ("Buffers", self.buffer), ("VertexArrays", self.vao)):
            if value.value:
                getattr(self, "Delete" + name)(1, ct.byref(value))
                value.value = 0

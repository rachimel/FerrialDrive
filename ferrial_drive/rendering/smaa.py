"""확대된 파츠의 프리멀티플라이 RGBA에 SMAA 1×를 적용한다."""

import ctypes as ct
from contextlib import contextmanager
from pathlib import Path

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from .gl_pass import QUAD_VERTEX_SHADER, TexturedQuadPass


SOURCE = Path(__file__).parent / "vendor/smaa"
LOOKUP_FORMATS = (("area.rg8", 160, 560, 2, 0x822B, 0x8227), ("search.r8", 64, 16, 1, 0x8229, 0x1903))
HEADER = b"""#version 130
#define SMAA_GLSL_3
#define SMAA_PRESET_HIGH
#define SMAA_RT_METRICS metrics
uniform vec4 metrics;
uniform sampler2D artwork;
varying vec2 texel;
"""
EDGE_SHADER = b"""
float rgbaDelta(vec4 a, vec4 b) {
    vec4 d=abs(a-b);
    return max(max(d.r,d.g),max(d.b,d.a));
}
void main() {
    vec2 uv=texel*metrics.xy;
    vec4 offset[3];
    SMAAEdgeDetectionVS(uv,offset);
    vec4 center=texture(artwork,uv);
    vec4 left=texture(artwork,offset[0].xy), top=texture(artwork,offset[0].zw);
    vec2 delta=vec2(rgbaDelta(center,left),rgbaDelta(center,top));
    if(max(delta.x,delta.y)<SMAA_THRESHOLD) discard;
    float local=max(max(delta.x,delta.y),max(rgbaDelta(center,texture(artwork,offset[1].xy)),
                                            rgbaDelta(center,texture(artwork,offset[1].zw))));
    local=max(local,max(rgbaDelta(left,texture(artwork,offset[2].xy)),
                        rgbaDelta(top,texture(artwork,offset[2].zw))));
    vec2 edges=step(vec2(SMAA_THRESHOLD),delta)*step(vec2(local),SMAA_LOCAL_CONTRAST_ADAPTATION_FACTOR*delta);
    gl_FragColor=vec4(edges,0.0,0.0);
}
"""
WEIGHT_SHADER = b"""
uniform sampler2D areaLookup, searchLookup;
void main() {
    vec2 uv=texel*metrics.xy, pixel;
    vec4 offset[3];
    SMAABlendingWeightCalculationVS(uv,pixel,offset);
    gl_FragColor=SMAABlendingWeightCalculationPS(uv,pixel,offset,artwork,areaLookup,searchLookup,vec4(0.0));
}
"""
NEIGHBORHOOD_SHADER = b"""
uniform sampler2D blendWeights;
void main() {
    vec2 uv=texel*metrics.xy;
    vec4 offset;
    SMAANeighborhoodBlendingVS(uv,offset);
    vec4 color=SMAANeighborhoodBlendingPS(uv,offset,artwork,blendWeights);
    gl_FragColor=vec4(color.a>0.0 ? clamp(color.rgb/color.a,0.0,1.0) : vec3(0.0),color.a);
}
"""


class Smaa1x:
    def __init__(self, pico):
        self.pico = pico
        self.size = (0, 0)
        self.targets = []
        self.programs = []
        self.lookups = (ct.c_uint * 2)()
        u, i, p = ct.c_uint, ct.c_int, ct.c_void_p
        self.gen_textures = bind_gl(pico, "glGenTextures", None, [i, p])
        self.delete_textures = bind_gl(pico, "glDeleteTextures", None, [i, p])
        self.tex_image = bind_gl(pico, "glTexImage2D", None, [u, i, i, i, i, i, u, u, p])
        self.tex_parameter = bind_gl(pico, "glTexParameteri", None, [u, u, i])
        self.pixel_store = bind_gl(pico, "glPixelStorei", None, [u, i])
        self.bind_buffer = bind_gl(pico, "glBindBuffer", None, [u, u])
        try:
            source = HEADER + (SOURCE / "SMAA.hlsl").read_bytes() + b"\n"
            vertex = QUAD_VERTEX_SHADER.replace(b"#version 120", b"#version 130", 1)
            for fragment, uniforms in ((EDGE_SHADER, ()), (WEIGHT_SHADER, ("areaLookup", "searchLookup")),
                                       (NEIGHBORHOOD_SHADER, ("blendWeights",))):
                self.programs.append(TexturedQuadPass(pico, vertex_shader=vertex, fragment_shader=source + fragment,
                                                    extra_uniforms=("metrics",) + uniforms))
            self._upload_lookups()
        except BaseException:
            self.close()
            raise

    def _upload_lookups(self):
        sampler = self.programs[0]
        previous = sampler.integer(0x8069)
        unpack = {key: sampler.integer(key) for key in (0x0CF2, 0x0CF3, 0x0CF4, 0x0CF5)}
        unpack_buffer = sampler.integer(0x88EF)
        self.gen_textures(2, self.lookups)
        try:
            self.bind_buffer(0x88EC, 0)
            for key in unpack:
                self.pixel_store(key, int(key == 0x0CF5))
            for texture, lookup in zip(self.lookups, LOOKUP_FORMATS, strict=True):
                name, width, height, channels, internal, pixel_format = lookup
                pixels = (SOURCE / name).read_bytes()
                if len(pixels) != width * height * channels or not texture:
                    raise RuntimeError("SMAA 조회 텍스처를 읽을 수 없다.")
                sampler.glBindTexture(0x0DE1, texture)
                buffer = (ct.c_ubyte * len(pixels)).from_buffer_copy(pixels)
                self.tex_image(0x0DE1, 0, internal, width, height, 0, pixel_format, 0x1401, buffer)
                for parameter, value in ((0x2800, 0x2601), (0x2801, 0x2601), (0x2802, 0x812F), (0x2803, 0x812F)):
                    self.tex_parameter(0x0DE1, parameter, value)
        finally:
            self.bind_buffer(0x88EC, unpack_buffer)
            for key, value in unpack.items():
                self.pixel_store(key, value)
            sampler.glBindTexture(0x0DE1, previous)

    @property
    def storage_bytes(self):
        width, height = self.size
        lookup_bytes = sum(w * h * channels for _, w, h, channels, _, _ in LOOKUP_FORMATS)
        return 4 * len(self.targets) * width * height + lookup_bytes

    def ensure_size(self, width, height):
        size = tuple(max(old, (value + 63) // 64 * 64) for old, value in zip(self.size, (width, height), strict=True))
        if size == self.size:
            return
        p = self.pico
        targets = []
        try:
            for _ in range(3):
                target = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_TARGET, *size)
                if not target:
                    raise RuntimeError("SMAA 렌더 타깃을 만들 수 없다.")
                targets.append(target)
                if p.SDL_SetTextureScaleMode(target, p.SDL_ScaleModeLinear):
                    raise RuntimeError("SMAA 렌더 타깃에 선형 필터를 설정할 수 없다.")
        except BaseException:
            for target in targets:
                p.SDL_DestroyTexture(target)
            raise
        for target in self.targets:
            p.SDL_DestroyTexture(target)
        self.targets, self.size = targets, size

    @contextmanager
    def bind_input(self, sampler, unit, texture, *, sdl=False):
        sampler.glActiveTexture(0x84C0 + unit)
        previous = sampler.integer(0x8069)
        try:
            if sdl:
                if self.pico.SDL_GL_BindTexture(texture, None, None):
                    raise RuntimeError("SMAA 가중치 텍스처를 연결할 수 없다.")
            else:
                sampler.glBindTexture(0x0DE1, texture)
            sampler.glActiveTexture(0x84C0)
            yield
        finally:
            sampler.glActiveTexture(0x84C0 + unit)
            sampler.glBindTexture(0x0DE1, previous)
            sampler.glActiveTexture(0x84C0)

    def _upload_metrics(self, sampler):
        width, height = self.size
        sampler.glUniform4f(sampler.uniforms["metrics"], 1 / width, 1 / height, width, height)

    def draw(self, bicubic, native_texture, native_size, source, destination, pixels, render_target):
        self.ensure_size(*pixels)
        color, edges, weights = self.targets
        edge, weight, blend = self.programs
        rect = self.pico.SDL_Rect(0, 0, *pixels)
        with render_target(self.pico, color):
            bicubic.draw(native_texture, native_size, source, rect, premultiplied=True)
        with render_target(self.pico, edges), edge.batch():
            edge.glDisable(0x0BE2)
            self._upload_metrics(edge)
            edge.draw(color, self.size, rect, rect)
        with (render_target(self.pico, weights), weight.batch(),
              self.bind_input(weight, 1, self.lookups[0]), self.bind_input(weight, 2, self.lookups[1])):
            weight.glDisable(0x0BE2)
            self._upload_metrics(weight)
            weight.glUniform1i(weight.uniforms["areaLookup"], 1)
            weight.glUniform1i(weight.uniforms["searchLookup"], 2)
            weight.draw(edges, self.size, rect, rect)
        with blend.batch(), self.bind_input(blend, 1, weights, sdl=True):
            self._upload_metrics(blend)
            blend.glUniform1i(blend.uniforms["blendWeights"], 1)
            blend.draw(color, self.size, rect, destination)

    def close(self):
        for target in self.targets:
            self.pico.SDL_DestroyTexture(target)
        self.targets.clear()
        for sampler in self.programs:
            sampler.close()
        self.programs.clear()
        self.delete_textures(2, self.lookups)
        self.lookups[:] = 0, 0

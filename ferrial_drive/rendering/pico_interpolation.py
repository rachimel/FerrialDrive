"""Pico2D의 기존 OpenGL 경로에서 양방향 모션 벡터로 스프라이트를 보간한다."""

from contextlib import contextmanager
from collections import OrderedDict
import ctypes as ct
from math import isfinite

from ferrial_drive.diagnostics import TimingRecorder
from ferrial_drive.diagnostics.texture_metrics import bind_gl

from .bicubic import BicubicSampler, renderer_name
from .motion_vectors import EASING_CODES, MotionClip, MotionPair, premultiply_rgba, validate_phase


MOTION_SHADER = b'''#version 120
uniform sampler2D artwork;
uniform sampler2D nextImage;
uniform sampler2D forwardMap;
uniform sampler2D backwardMap;
uniform vec2 atlasSize;
uniform vec4 modulation;
uniform vec4 colorMix;
uniform vec4 rimLight;
uniform float brightness;
uniform float phase;
uniform float pairCount;
uniform float blurSpan;
uniform float blurStrength;
uniform float blurBias;
uniform float playbackDirection;
uniform int easing;
uniform int mode;
varying vec2 texel;
vec2 uvAt(vec2 p, float index) {
    p=clamp(p,vec2(0.5),atlasSize-0.5);
    return vec2(p.x/atlasSize.x,(p.y/atlasSize.y+index)/pairCount);
}
vec2 flow(sampler2D field, vec2 p, float index) {
    vec4 v=texture2D(field,uvAt(p,index))*255.0;
    return (vec2(v.r*256.0+v.g,v.b*256.0+v.a)-32768.0)/64.0;
}
vec4 colorAt(sampler2D image, vec2 p, float index) {
    if (p.x<0.0 || p.y<0.0 || p.x>atlasSize.x || p.y>atlasSize.y) return vec4(0.0);
    return texture2D(image,uvAt(p,index));
}
vec4 evaluate(float clockPhase) {
    float goal=clamp(clockPhase,0.0,1.0);
    if (easing==1) goal=smoothstep(0.0,1.0,goal);
    else if (easing==2) goal=goal*goal*goal*(2.0-goal);
    else if (easing==3) goal=goal*goal*goal*goal*goal;
    float index=min(floor(goal*pairCount),pairCount-1.0);
    float t=goal*pairCount-index;
    vec4 c;
    if (t<=0.0) c=colorAt(artwork,texel,index);
    else if (t>=1.0) c=colorAt(nextImage,texel,index);
    else if (mode==0) c=colorAt(artwork,texel,index);
    else if (mode==1) c=mix(colorAt(artwork,texel,index),colorAt(nextImage,texel,index),t);
    else {
        vec2 a=texel, b=texel;
        for (int i=0;i<16;++i) {
            a=mix(a,texel-t*flow(forwardMap,a,index),0.5);
            b=mix(b,texel-(1.0-t)*flow(backwardMap,b,index),0.5);
        }
        c=mix(colorAt(artwork,a,index),colorAt(nextImage,b,index),t);
    }
    return c;
}
void main() {
    vec4 c=vec4(0.0);
    if (mode==2 && blurSpan>0.0) {
        for (int i=0;i<9;++i) c+=evaluate(phase+(float(i)/8.0-0.5+blurBias)*blurSpan*playbackDirection)/9.0;
        c=mix(evaluate(phase),c,blurStrength);
    } else c=evaluate(phase);
    vec3 rgb=c.a>0.00001 ? c.rgb/c.a : vec3(0.0);
    vec3 tinted=colorMix.rgb*max(dot(rgb,vec3(0.299,0.587,0.114)),0.25);
    rgb=mix(rgb,tinted,colorMix.a);

    if (rimLight.a > 0.0) {
        vec2 gradient=vec2(dFdx(c.a),dFdy(c.a));
        float edge=clamp(length(gradient)*4.5,0.0,1.0);
        float directional=0.3+0.7*max(0.0,dot(normalize(gradient+vec2(0.00001)),normalize(vec2(0.6,-0.8))));
        rgb=mix(rgb,rimLight.rgb,edge*directional*rimLight.a);
    }
    gl_FragColor=vec4(rgb*modulation.rgb*brightness,c.a*modulation.a);
}
'''


class PicoFrameInterpolator:
    """전체 프레임 좌표·동일 크기를 전제로 한다. 가림 복원은 아직 수행하지 않는다."""

    def __init__(self, pico, *, cache_capacity=4, timings=None):
        if type(cache_capacity) is not int or cache_capacity < 1:
            raise ValueError("클립 캐시 크기는 양수 정수여야 한다.")
        if not pico.renderer or renderer_name(pico) != "opengl":
            raise RuntimeError("프레임 보간에는 열린 Pico2D OpenGL 렌더러가 필요하다.")
        self.pico = pico
        self.timings = timings or TimingRecorder(enabled=False)
        self.finish = bind_gl(pico, "glFinish", None, []) if self.timings.enabled else None
        self.textures = []
        self.pair = None
        self.clip = None
        self.clip_cache = OrderedDict()
        self.cache_capacity = cache_capacity
        self.sampler = BicubicSampler(pico, None, fragment_shader=MOTION_SHADER,
                                     extra_uniforms=("nextImage", "forwardMap", "backwardMap", "phase", "mode",
                                                     "pairCount", "blurSpan", "easing", "blurBias", "playbackDirection", "blurStrength", "colorMix", "rimLight", "brightness"))

    def _texture(self, width, height, pixels):
        if self.finish:
            self.finish()
        with self.timings.scope("load.upload_complete"):
            texture = self._create_texture(width, height, pixels)
            if self.finish:
                self.finish()
            return texture

    def _create_texture(self, width, height, pixels):
        p = self.pico
        texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32,
                                      p.SDL_TEXTUREACCESS_STATIC, width, height)
        if not texture:
            raise RuntimeError("보간 텍스처 생성 실패")
        try:
            buffer = ct.create_string_buffer(pixels)
            if p.SDL_UpdateTexture(texture, None, buffer, width * 4) != 0:
                raise RuntimeError("보간 텍스처 전송 실패")
            if p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear) != 0:
                raise RuntimeError("보간 텍스처 필터 설정 실패")
            p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_NONE)
            return texture
        except BaseException:
            p.SDL_DestroyTexture(texture)
            raise

    def set_pair(self, pair: MotionPair):
        self.set_clip(MotionClip((pair,)))

    def set_clip(self, clip: MotionClip):
        if self.sampler is None:
            raise RuntimeError("해제한 보간 렌더러다.")
        pair = clip.pairs[0]
        cached = self.clip_cache.get(id(clip))
        if cached is not None:
            self.clip_cache.move_to_end(id(clip))
            self.clip, self.pair, self.textures = clip, pair, cached[1]
            return
        atlas_height = pair.height * len(clip.pairs)
        maximum = self.sampler.integer(0x0D33)
        if max(pair.width, atlas_height) > maximum:
            raise ValueError("클립 텍스처가 GPU 최대 크기를 초과했다. 짧은 클립으로 나눈다.")
        created = []
        try:
            for field in ("rgba_a", "rgba_b", "forward", "backward"):
                pixels = b"".join(getattr(item, field) for item in clip.pairs)
                if field.startswith("rgba"):
                    with self.timings.scope("load.premultiply"):
                        pixels = premultiply_rgba(pixels)
                created.append(self._texture(pair.width, atlas_height, pixels))
        except BaseException:
            for texture in created:
                self.pico.SDL_DestroyTexture(texture)
            raise
        self.textures, self.pair = created, pair
        self.clip = clip
        self.clip_cache[id(clip)] = (clip, created)
        while len(self.clip_cache) > self.cache_capacity:
            _, (_, textures) = self.clip_cache.popitem(last=False)
            for texture in textures:
                self.pico.SDL_DestroyTexture(texture)

    @contextmanager
    def _extra_textures(self):
        s, p = self.sampler, self.pico
        previous = []
        try:
            for unit, texture in enumerate(self.textures[1:], 1):
                s.glActiveTexture(0x84C0 + unit)
                previous.append((unit, s.integer(0x8069)))
                texw, texh = ct.c_float(), ct.c_float()
                if p.SDL_GL_BindTexture(texture, ct.byref(texw), ct.byref(texh)) != 0:
                    raise RuntimeError("보간 보조 텍스처 연결 실패")
                if abs(texw.value - 1) > 1e-5 or abs(texh.value - 1) > 1e-5:
                    raise RuntimeError("정규화된 보간 텍스처가 필요하다.")
            s.glActiveTexture(0x84C0)
            yield
        finally:
            for unit, texture in previous:
                s.glActiveTexture(0x84C0 + unit)
                s.glBindTexture(0x0DE1, texture)
            s.glActiveTexture(0x84C0)

    def draw(self, phase, destination, *, mode="motion", easing="smoothstep", shutter_seconds=0.0,
             blur_direction="trailing", playback_direction=1, blur_strength=1.0, tint=(1, 1, 1), tint_mix=0, rim_light=(0, 0, 0, 0), brightness=1):
        if len(tint) != 3 or any(not isfinite(v) or not 0 <= v <= 1 for v in (*tint, tint_mix)):
            raise ValueError("혼합 색상과 비율은 0~1의 유한값이어야 한다.")
        phase = validate_phase(phase)
        if self.sampler is None or self.pair is None:
            raise RuntimeError("프레임 쌍을 연결한 보간 렌더러가 필요하다.")
        if mode not in ("hold", "blend", "motion"):
            raise ValueError("지원하지 않는 프레임 표시 방식이다.")
        if easing not in EASING_CODES:
            raise ValueError("지원하지 않는 위상 곡선이다.")
        if blur_direction not in ("trailing", "centered", "leading") or type(playback_direction) is not int or playback_direction not in (-1, 1):
            raise ValueError("블러 방향·재생 방향 설정 오류")
        if not isfinite(shutter_seconds) or not 0 <= shutter_seconds <= self.clip.duration_seconds:
            raise ValueError("노출 시간은 0~클립 길이 범위의 초 단위여야 한다.")
        if not isfinite(blur_strength) or not 0 <= blur_strength <= 1:
            raise ValueError("블러 강도는 0~1 범위여야 한다.")
        if destination.w <= 0 or destination.h <= 0:
            return
        s, pair = self.sampler, self.pair
        with s.batch(), self._extra_textures():
            for name, unit in (("nextImage", 1), ("forwardMap", 2), ("backwardMap", 3)):
                s.glUniform1i(s.uniforms[name], unit)
            s.glUniform1f(s.uniforms["phase"], phase)
            s.glUniform1f(s.uniforms["pairCount"], len(self.clip.pairs))
            s.glUniform1f(s.uniforms["blurSpan"], shutter_seconds / self.clip.duration_seconds)
            s.glUniform1f(s.uniforms["blurStrength"], blur_strength)
            s.glUniform1f(s.uniforms["blurBias"], {"trailing": -0.5, "centered": 0.0, "leading": 0.5}[blur_direction])
            s.glUniform1f(s.uniforms["playbackDirection"], playback_direction)
            s.glUniform1i(s.uniforms["easing"], EASING_CODES[easing])
            s.glUniform1i(s.uniforms["mode"], ("hold", "blend", "motion").index(mode))
            s.glUniform4f(s.uniforms["colorMix"], *tint, tint_mix)
            s.glUniform4f(s.uniforms["rimLight"], *rim_light)
            s.glUniform1f(s.uniforms["brightness"], brightness)
            s.draw(self.textures[0], (pair.width, pair.height),
                   self.pico.SDL_Rect(0, 0, pair.width, pair.height), destination)

    def close(self):
        for _, textures in self.clip_cache.values():
            for texture in textures:
                self.pico.SDL_DestroyTexture(texture)
        self.clip_cache.clear()
        self.textures = []
        if self.sampler is not None:
            self.sampler.glDeleteProgram(self.sampler.program)
            self.sampler = None
        self.pair = None
        self.clip = None


def read_rgba_image(pico, path):
    """외부 PNG를 동일한 위쪽 원점 RGBA 바이트로 읽는다."""
    surface = pico.IMG_Load(str(path).encode("utf-8"))
    if not surface:
        raise OSError(f"이미지 읽기 실패: {path}")
    converted = None
    try:
        converted = pico.SDL_ConvertSurfaceFormat(surface, pico.SDL_PIXELFORMAT_RGBA32, 0)
        if not converted:
            raise RuntimeError("RGBA 이미지 변환 실패")
        value = converted.contents
        if pico.SDL_LockSurface(converted) != 0:
            raise RuntimeError("RGBA 이미지 잠금 실패")
        try:
            pixels = b"".join(ct.string_at(value.pixels + y * value.pitch, value.w * 4)
                              for y in range(value.h))
        finally:
            pico.SDL_UnlockSurface(converted)
        return value.w, value.h, pixels
    finally:
        if converted:
            pico.SDL_FreeSurface(converted)
        pico.SDL_FreeSurface(surface)

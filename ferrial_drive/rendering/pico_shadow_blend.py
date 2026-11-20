"""기존 그림자 시트의 두 프레임 알파를 GPU에서 한 번 합성한다."""

from math import ceil, floor, isfinite
import ctypes as ct

from .gl_pass import TexturedQuadPass
from ferrial_drive.assets.pico_opacity import shadow_opacity


SHADOW_BLEND_SHADER = b'''#version 120
uniform sampler2D artwork;
uniform sampler2D nextArtwork;
uniform vec2 atlasSize;
uniform vec2 nextAtlasSize;
uniform vec2 currentTexelMargin, nextTexelMargin;
uniform vec4 frameBounds;
uniform vec4 currentBounds;
uniform vec4 nextBounds;
uniform vec4 currentTarget;
uniform vec4 nextTarget;
uniform vec4 modulation;
uniform float phase;
uniform float softnessPixels;
uniform float contactRadius;
uniform vec2 contactPoint;
varying vec2 texel;
float alphaAt(sampler2D image, vec2 point, vec4 target, vec4 bounds, vec2 size, vec2 margin) {
    vec2 u=(point-target.xy)/target.zw;
    if (u.x<0.0 || u.y<0.0 || u.x>1.0 || u.y>1.0) return 0.0;
    vec2 unit=margin*2.0, middle=(bounds.xy+bounds.zw)*0.5;
    vec2 low=min((ceil(bounds.xy/unit-0.0001)+0.5)*unit,middle);
    vec2 high=max((floor(bounds.zw/unit+0.0001)-0.5)*unit,middle);
    vec2 p=clamp(bounds.xy+u*(bounds.zw-bounds.xy),low,high);
    return texture2D(image,p/size).a;
}
float weight(int i) {
    if (i==0 || i==4) return 1.0;
    if (i==1 || i==3) return 4.0;
    return 6.0;
}
float softAlpha(sampler2D image, vec4 target, vec4 bounds, vec2 size, float radius, vec2 margin) {
    if (radius<=0.0) return alphaAt(image,texel,target,bounds,size,margin);
    float sum=0.0;
    for (int y=0;y<5;++y) for (int x=0;x<5;++x) {
        vec2 offset=vec2(float(x)-2.0,float(y)-2.0)*radius*0.5;
        sum+=alphaAt(image,texel+offset,target,bounds,size,margin)*weight(x)*weight(y);
    }
    return sum/256.0;
}
void main() {
    float distanceFactor=smoothstep(0.0,contactRadius,length(texel-contactPoint));
    float radius=softnessPixels*mix(0.25,1.0,distanceFactor);
    float a=softAlpha(artwork,currentTarget,currentBounds,atlasSize,radius,currentTexelMargin);
    float b=a;
    if (phase>0.0) b=softAlpha(nextArtwork,nextTarget,nextBounds,nextAtlasSize,radius,nextTexelMargin);
    gl_FragColor=vec4(vec3(0.0)*modulation.rgb,mix(a,b,phase)*modulation.a);
}
'''


def frame_blend_indices(position, count, *, loop):
    position = position % count if loop else max(0, min(count, position))
    index = min(count - 1, floor(position))
    return index, (index + 1) % count if loop else min(count - 1, index + 1), position - index


class PicoShadowBlend:
    def __init__(self, pico, *, softness_pixels=0.0, contact_radius_pixels=56.0):
        if not isfinite(softness_pixels) or softness_pixels < 0 or not isfinite(contact_radius_pixels) or contact_radius_pixels <= 0:
            raise ValueError("그림자 번짐 반경은 0 이상, 접지 반경은 양수여야 한다.")
        self.pico = pico
        self.softness_pixels, self.contact_radius_pixels = softness_pixels, contact_radius_pixels
        self.sampler = TexturedQuadPass(pico, fragment_shader=SHADOW_BLEND_SHADER,
                                      extra_uniforms=("currentBounds", "nextBounds", "currentTarget", "nextTarget",
                                                      "phase", "nextArtwork", "nextAtlasSize", "softnessPixels",
                                                      "contactRadius", "contactPoint", "currentTexelMargin", "nextTexelMargin"))

    def draw(self, resource, clip_name, frame_position, x, y, *, scale, opacity, endpoint=None,
             endpoint_resource=None, loop=True):
        clip = resource.mech.sheets["shadow"].clips[resource.mech.rows[clip_name]["source_clip"]]
        index, following_index, phase = frame_blend_indices(frame_position, len(clip.frames), loop=loop)
        following = clip.frames[following_index]
        next_resource = resource
        if endpoint is not None and index == len(clip.frames) - 1:
            next_resource = endpoint_resource if endpoint_resource is not None else resource
            following = next_resource.mech.sheets["shadow"].clips[next_resource.mech.rows[endpoint]["source_clip"]].frames[0]
        frame = clip.frames[index]
        height = resource.sizes["shadow"][1]
        source = self.pico.SDL_Rect(frame.rect[0], height - frame.rect[1] - frame.rect[3], *frame.rect[2:])
        next_rect = (following.rect[0], next_resource.sizes["shadow"][1] - following.rect[1] - following.rect[3], *following.rect[2:])
        current_target = resource.target_rect(frame, x, y, scale)
        next_target = next_resource.target_rect(following, x, y, scale)
        left, top = min(current_target.x, next_target.x), min(current_target.y, next_target.y)
        right = max(current_target.x + current_target.w, next_target.x + next_target.w)
        bottom = max(current_target.y + current_target.h, next_target.y + next_target.h)
        padding = ceil(self.softness_pixels)
        left, top, right, bottom = left - padding, top - padding, right + padding, bottom + padding
        destination = self.pico.SDL_Rect(left, top, right - left, bottom - top)
        virtual_source = self.pico.SDL_Rect(0, 0, destination.w, destination.h)
        sampler = self.sampler
        with shadow_opacity(self.pico, resource.textures["shadow"], opacity), sampler.batch():
            texw, texh = ct.c_float(), ct.c_float()
            if self.pico.SDL_GL_BindTexture(next_resource.textures["shadow"], ct.byref(texw), ct.byref(texh)) != 0:
                raise RuntimeError("다음 그림자의 OpenGL 텍스처 연결 실패")
            if abs(texw.value - 1) > 1e-5 or abs(texh.value - 1) > 1e-5:
                raise RuntimeError("그림자 보간에는 정규화된 2D 텍스처가 필요하다.")
            next_texture = sampler.integer(0x8069)
            sampler.glActiveTexture(0x84C1)
            previous_texture = sampler.integer(0x8069)
            try:
                sampler.glBindTexture(0x0DE1, next_texture)
                sampler.glUniform1i(sampler.uniforms["nextArtwork"], 1)
                sampler.glUniform2f(sampler.uniforms["nextAtlasSize"], *next_resource.sizes["shadow"])
                for name,item in (("currentTexelMargin",resource),("nextTexelMargin",next_resource)):
                    logical = item.sizes["shadow"]
                    actual = getattr(item,"texture_sizes",{}).get("shadow")
                    if actual is None:
                        from ctypes import c_int, byref
                        width,height = c_int(),c_int()
                        if self.pico.SDL_QueryTexture(item.textures["shadow"],None,None,byref(width),byref(height)):
                            raise RuntimeError("그림자 실제 텍스처 크기 조회 실패")
                        actual = width.value,height.value
                    sampler.glUniform2f(sampler.uniforms[name],*(a/b*.5 for a,b in zip(logical,actual)))
                sampler.glActiveTexture(0x84C0)
                sampler.glUniform4f(sampler.uniforms["currentBounds"], source.x, source.y,
                                    source.x + source.w, source.y + source.h)
                sampler.glUniform4f(sampler.uniforms["nextBounds"], next_rect[0], next_rect[1],
                                    next_rect[0] + next_rect[2], next_rect[1] + next_rect[3])
                for name, target in (("currentTarget", current_target), ("nextTarget", next_target)):
                    sampler.glUniform4f(sampler.uniforms[name], target.x - left, target.y - top, target.w, target.h)
                sampler.glUniform1f(sampler.uniforms["phase"], phase)
                sampler.glUniform1f(sampler.uniforms["softnessPixels"], self.softness_pixels)
                sampler.glUniform1f(sampler.uniforms["contactRadius"], self.contact_radius_pixels)
                sampler.glUniform2f(sampler.uniforms["contactPoint"], x - left, y - top)
                sampler.draw(resource.textures["shadow"], resource.sizes["shadow"], virtual_source, destination)
            finally:
                sampler.glActiveTexture(0x84C1)
                sampler.glBindTexture(0x0DE1, previous_texture)
                sampler.glActiveTexture(0x84C0)

    def close(self):
        if self.sampler is not None:
            self.sampler.close()
            self.sampler = None

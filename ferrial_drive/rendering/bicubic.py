"""SDL OpenGL 텍스처를 재사용하는 화면 픽셀 Bicubic. PNG·Pico2D 원본은 변경하지 않는다."""

import ctypes as ct

from .canvas import renderer_name
from .gl_pass import TexturedQuadPass


FRAGMENT_SHADER = b'''#version 120
uniform sampler2D artwork;
uniform vec2 atlasSize;
uniform vec4 frameBounds;
uniform vec4 modulation;
uniform float premultipliedSource;
varying vec2 texel;
vec4 weights(float t) {
    float t2=t*t, t3=t2*t;
    return vec4(-0.5*t+t2-0.5*t3, 1.0-2.5*t2+1.5*t3,
                0.5*t+2.0*t2-1.5*t3, -0.5*t2+0.5*t3);
}
void main() {
    vec2 p=texel-0.5, base=floor(p), f=fract(p);
    vec4 wx=weights(f.x), wy=weights(f.y), total=vec4(0.0);
    vec4 lo=vec4(1.0), hi=vec4(0.0);
    for (int j=0;j<4;++j) for (int i=0;i<4;++i) {
        vec2 pixel=clamp(base+vec2(float(i-1),float(j-1))+0.5,
                         frameBounds.xy+0.5, frameBounds.zw-0.5);
        vec4 s=texture2D(artwork,pixel/atlasSize);
        if (premultipliedSource<0.5) s.rgb*=s.a;
        if (premultipliedSource>0.5 && i>=1 && i<=2 && j>=1 && j<=2) { lo=min(lo,s); hi=max(hi,s); }
        total += s*wx[i]*wy[j];
    }
    if (premultipliedSource>0.5) total=clamp(total,lo,hi);
    float alpha=clamp(total.a,0.0,1.0);
    vec3 rgb=alpha>0.00001 ? clamp(total.rgb,0.0,alpha)/alpha : vec3(0.0);
    gl_FragColor=vec4(rgb*modulation.rgb,alpha*modulation.a);
}
'''

_SAMPLERS = {}


def acquire_sampler(pico):
    if renderer_name(pico) != 'opengl':
        return None
    key = ct.cast(pico.renderer, ct.c_void_p).value
    if key not in _SAMPLERS:
        _SAMPLERS[key] = BicubicSampler(pico, key)
    sampler = _SAMPLERS[key]
    sampler.references += 1
    return sampler


class BicubicSampler(TexturedQuadPass):
    """4×4 Bicubic 필터와 렌더러별 공유 수명을 관리한다."""

    def __init__(self, pico, key):
        super().__init__(pico, fragment_shader=FRAGMENT_SHADER)
        self.key = key
        self.references = 0

    def release(self):
        self.references -= 1
        if self.references == 0:
            self.close()
            _SAMPLERS.pop(self.key, None)

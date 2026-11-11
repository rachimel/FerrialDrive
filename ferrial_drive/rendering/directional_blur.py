"""한 번 렌더한 투명 레이어에 적용하는 OpenGL 방향성 모션 블러."""

from .bicubic import BicubicSampler


FRAGMENT_SHADER = b'''#version 120
uniform sampler2D artwork;
uniform vec2 atlasSize;
uniform vec4 modulation;
uniform vec2 motionVector;
uniform float blurStrength;
uniform int sampleCount;
varying vec2 texel;
vec4 sampleLayer(vec2 pixel) {
    if (pixel.x < 0.0 || pixel.y < 0.0 || pixel.x >= atlasSize.x || pixel.y >= atlasSize.y)
        return vec4(0.0);
    return texture2D(artwork, pixel / atlasSize);
}
void main() {
    vec4 blurred = vec4(0.0);
    float total = 0.0;
    for (int i = 0; i < 65; ++i) {
        if (i >= sampleCount) break;
        float t = float(i) / float(sampleCount - 1);
        float weight = 1.0 - 0.75 * t;
        blurred += sampleLayer(texel + motionVector * t) * weight;
        total += weight;
    }
    vec4 result = mix(sampleLayer(texel), blurred / total, blurStrength);
    vec3 rgb = result.a > 0.00001 ? result.rgb / result.a : vec3(0.0);
    gl_FragColor = vec4(rgb * modulation.rgb, result.a * modulation.a);
}
'''


class DirectionalBlurSampler(BicubicSampler):
    def __init__(self, pico):
        super().__init__(pico, None, fragment_shader=FRAGMENT_SHADER,
                         extra_uniforms=('motionVector', 'blurStrength', 'sampleCount'))

    def draw_blurred(self, texture, size, source, destination, displacement, strength, samples=33):
        with self.batch():
            self.glUniform2f(self.uniforms['motionVector'], *displacement)
            self.glUniform1f(self.uniforms['blurStrength'], strength)
            self.glUniform1i(self.uniforms['sampleCount'], max(2, min(65, samples)))
            self.draw(texture, size, source, destination)

    def close(self):
        if self.program:
            self.glDeleteProgram(self.program)
            self.program = 0

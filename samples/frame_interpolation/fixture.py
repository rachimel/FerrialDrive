"""게임 에셋 없는 도형과 정확한 표면 대응 변위를 작성한다. 3D 렌더 검증과 구분한다."""

from math import cos, sin, radians

from ferrial_drive.rendering.motion_vectors import MotionClip, MotionPair, encode_vector


def local_position(x, y, phase, scene):
    ax, ay = scene["center_a"]
    bx, by = scene["center_b"]
    angle = radians(scene["angle_a_degrees"] * (1 - phase) + scene["angle_b_degrees"] * phase)
    dx, dy = x - (ax * (1 - phase) + bx * phase), y - (ay * (1 - phase) + by * phase)
    return cos(angle) * dx + sin(angle) * dy, -sin(angle) * dx + cos(angle) * dy


def signed_distance(x, y, half_width, half_height):
    return max(abs(x) - half_width, abs(y) - half_height)


def pixel(x, y, phase, scene):
    lx, ly = local_position(x, y, phase, scene)
    distance = signed_distance(lx, ly, *scene["half_size"])
    coverage = max(0, min(1, 0.5 - distance))
    split = max(0, min(1, lx + 0.5))
    rgb = tuple(a * (1 - split) + b * split for a, b in zip((0.45, 0.68, 0.8), (0.76, 0.88, 0.93)))
    stripe = max(0, min(1, 2.5 - abs(ly)))
    rgb = tuple(a * (1 - stripe) + b * stripe for a, b in zip(rgb, (0.95, 0.57, 0.3)))
    premultiplied = [value * coverage for value in rgb]
    if scene["occluder"]:
        front_alpha = max(0, min(1, 0.5 - signed_distance(x - 96, y - 96, 17, 70)))
        front = (0.3, 0.4, 0.46)
        premultiplied = [front[i] * front_alpha + value * (1 - front_alpha)
                         for i, value in enumerate(premultiplied)]
        coverage = front_alpha + coverage * (1 - front_alpha)
    rgb = [value / coverage if coverage else 0 for value in premultiplied]
    return bytes(round(max(0, min(1, value)) * 255) for value in (*rgb, coverage))


def render_pixels(scene, size, phase):
    return b"".join(pixel(x + 0.5, y + 0.5, phase, scene)
                    for y in range(size) for x in range(size))


def vector_pixels(scene, size, source_phase, destination_phase):
    center = [a * (1 - destination_phase) + b * destination_phase
              for a, b in zip(scene["center_a"], scene["center_b"])]
    angle = radians(scene["angle_a_degrees"] * (1 - destination_phase)
                    + scene["angle_b_degrees"] * destination_phase)
    result = bytearray()
    for y in range(size):
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            lx, ly = local_position(px, py, source_phase, scene)
            # 투명 바깥쪽까지 표면 변위를 연장한다. 실제 출력도 벡터 패딩이 필요하다.
            static = scene["occluder"] and signed_distance(px - 96, py - 96, 17, 70) <= 0
            dx = 0 if static else center[0] + cos(angle) * lx - sin(angle) * ly - px
            dy = 0 if static else center[1] + sin(angle) * lx + cos(angle) * ly - py
            result.extend(encode_vector(dx, dy))
    return bytes(result)


def build_clip(scene, size, duration_seconds, intervals=6):
    phases = [index / intervals for index in range(intervals + 1)]
    images = [render_pixels(scene, size, phase) for phase in phases]
    pairs = tuple(MotionPair(size, size, images[i], images[i + 1],
                             vector_pixels(scene, size, phases[i], phases[i + 1]),
                             vector_pixels(scene, size, phases[i + 1], phases[i]),
                             duration_seconds, scene["name"]) for i in range(intervals))
    return MotionClip(pairs)


def reference_shader(scene):
    """같은 시각의 실제 도형 변환을 독립적으로 그리는 정답 표시용 셰이더다."""
    ax, ay = scene["center_a"]
    bx, by = scene["center_b"]
    hx, hy = scene["half_size"]
    source = '''#version 120
uniform float phase;
uniform float blurSpan;
uniform float blurStrength;
uniform float blurBias;
uniform float playbackDirection;
uniform int easing;
uniform vec4 modulation;
varying vec2 texel;
float coverage(vec2 p,vec2 halfSize) { return clamp(0.5-max(abs(p.x)-halfSize.x,abs(p.y)-halfSize.y),0.0,1.0); }
vec4 evaluate(float clockPhase) {
    float t=clamp(clockPhase,0.0,1.0);
    if (easing==1) t=smoothstep(0.0,1.0,t);
    else if (easing==2) t=t*t*t*(2.0-t);
    else if (easing==3) t=t*t*t*t*t;
    float angle=radians(mix(ANGLE_A,ANGLE_B,t));
    vec2 p=texel-mix(vec2(AX,AY),vec2(BX,BY),t);
    vec2 local=vec2(cos(angle)*p.x+sin(angle)*p.y,-sin(angle)*p.x+cos(angle)*p.y);
    float a=coverage(local,vec2(HX,HY));
    vec3 rgb=mix(vec3(0.45,0.68,0.8),vec3(0.76,0.88,0.93),clamp(local.x+0.5,0.0,1.0));
    rgb=mix(rgb,vec3(0.95,0.57,0.3),clamp(2.5-abs(local.y),0.0,1.0));
    vec3 color=rgb*a;
    float front=OCCLUDER*coverage(texel-vec2(96.0),vec2(17.0,70.0));
    color=vec3(0.3,0.4,0.46)*front+color*(1.0-front);
    a=front+a*(1.0-front);
    return vec4(color,a);
}
void main() {
    vec4 c=vec4(0.0);
    if (blurSpan>0.0) {
        for (int i=0;i<9;++i) c+=evaluate(phase+(float(i)/8.0-0.5+blurBias)*blurSpan*playbackDirection)/9.0;
        c=mix(evaluate(phase),c,blurStrength);
    } else c=evaluate(phase);
    gl_FragColor=vec4((c.a>0.00001 ? c.rgb/c.a : vec3(0.0))*modulation.rgb,c.a*modulation.a);
}
'''
    values = {"ANGLE_A": scene["angle_a_degrees"], "ANGLE_B": scene["angle_b_degrees"],
              "AX": ax, "AY": ay, "BX": bx, "BY": by, "HX": hx, "HY": hy,
              "OCCLUDER": int(scene["occluder"])}
    for key, value in values.items():
        source = source.replace(key, f"{value:.8f}")
    return source.encode("ascii")

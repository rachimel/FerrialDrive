"""생성·갱신 Compute Ubershader 두 개와 공통 입자 렌더 셰이더."""

MAX_SEGMENTS = 64
PATH_POINTS = 201
PARTICLE_BYTES = 80

COMMON = r'''
const uint MAX_SEGMENTS = 64u;
const uint PATH_POINTS = 201u;
struct Particle { vec4 life; vec4 anchors; vec4 target; vec4 motion; vec4 payload; };
layout(std430, binding=0) buffer ParticlePool { Particle particles[]; };
layout(std430, binding=1) buffer PoolCounters { uint cursor; uint arrived_units; uint arrival_count; uint cancelled_units; };
layout(std430, binding=2) buffer ActiveParticles { uint active_indices[]; };
layout(std430, binding=3) buffer DrawCommands { uint draws[]; };
layout(std430, binding=4) buffer RouteProfiles { vec4 profiles[]; };
layout(std430, binding=5) buffer ParticlePaths { vec4 path_points[]; };
layout(std430, binding=6) buffer ParticleRibbons { vec4 ribbon_points[]; };
uniform int energy_enabled;
uniform vec4 energy_geometry;
uniform float energy_ratio;
uniform int energy_charge_mode;
uniform float energy_charge_total;
uniform uint energy_acknowledged;
vec3 sample_path(uint slot, float t) {
    float p = clamp(t, 0.0, 1.0) * 200.0;
    uint i = min(199u, uint(p));
    vec3 result = mix(path_points[slot * PATH_POINTS + i].xyz,
               path_points[slot * PATH_POINTS + i + 1u].xyz, p - float(i));
    Particle particle = particles[slot];
    if (energy_enabled != 0 && particle.payload.z > 0.0) {
        uint gain_so_far = atomicAdd(arrived_units, 0u);
        float gain = float(gain_so_far - energy_acknowledged) / 1000000.0;
        float ratio = clamp(energy_ratio + gain, 0.0, 1.0);
        if (energy_charge_mode != 0) {
            float total = min(4.0, energy_charge_total + gain);
            ratio = total >= 3.0 ? total - 3.0 : fract(total);
        }
        vec2 target = mix(energy_geometry.xy, energy_geometry.zw, ratio);
        result.xy += (target - particle.target.xy) * smoothstep(0.72, 1.0, t);
    }
    return result;
}
'''

SPAWN_SHADER = ('#version 430\n' + COMMON + r'''
layout(local_size_x=64) in;
uniform uint capacity;
uniform uint request_count;
uniform uint request_seed;
uniform int effect_type;
uniform vec4 anchors;
uniform vec4 destination;
uniform vec4 spawn_settings; // duration, side, spread, tail fraction
uniform uint gain_units;
uniform float arrival_spacing;
uint hash_value(uint x) {
    x ^= x >> 16u; x *= 0x7feb352du; x ^= x >> 15u; x *= 0x846ca68bu;
    return x ^ (x >> 16u);
}
vec2 bezier(vec2 a, vec2 b, vec2 c, vec2 d, float t) {
    return mix(mix(mix(a, b, t), mix(b, c, t), t),
               mix(mix(b, c, t), mix(c, d, t), t), t);
}
vec2 energy_path(Particle p, float t) {
    uint profile = uint(p.target.w) + (p.life.w < 0.0 ? 0u : 6u);
    uint base = profile * 4u;
    vec2 start = p.anchors.xy, waypoint = p.anchors.zw, target = p.target.xy;
    float side = p.life.w;
    if (t <= 0.72) {
        return bezier(start, start + vec2(-side * 90.0, 100.0) + profiles[base].xy,
                      waypoint + vec2(side * 90.0, -110.0) + profiles[base + 1u].xy,
                      waypoint, t / 0.72);
    }
    float below = max(waypoint.y, target.y + 10.0);
    return bezier(waypoint, vec2(waypoint.x - side * 40.0, below) + profiles[base + 2u].xy,
                  vec2(target.x + side * 35.0, below) + profiles[base + 3u].xy,
                  target, (t - 0.72) / 0.28);
}
void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= request_count) return;
    uint ticket = atomicAdd(cursor, 1u);
    uint slot = ticket % capacity;
    Particle old = particles[slot];
    if (old.life.z != 0.0 && old.payload.y == 0.0 && old.payload.x > 0.0)
        atomicAdd(cancelled_units, uint(old.payload.x));
    Particle p;
    p.life = vec4(0.0, spawn_settings.x + float(index) * arrival_spacing, 0.0, spawn_settings.y);
    p.anchors = anchors;
    p.target = vec4(destination.xy, float(effect_type), 0.0);
    p.motion = vec4(anchors.xy, 0.0, spawn_settings.w);
    uint share = gain_units / request_count + (index < gain_units % request_count ? 1u : 0u);
    p.payload = vec4(float(share), 0.0, gain_units > 0u ? 1.0 : 0.0, 0.0);
    switch (effect_type) {
        case 0: {
            float shift = (float(index) - float(request_count - 1u) * 0.5) * spawn_settings.z;
            p.anchors.xy += vec2(shift, -shift);
            // 인접 ticket의 홀짝을 나눠 동일 경로가 연속 선택되지 않게 한다.
            uint route = (hash_value((ticket / 2u) ^ request_seed) % 3u) * 2u + ticket % 2u;
            p.target.w = float(route);
            p.life.z = 1.0;
            p.motion.xy = p.anchors.xy;
            float distance = 0.0;
            vec2 previous = p.anchors.xy;
            for (uint i=0u; i<PATH_POINTS; ++i) {
                vec2 point = energy_path(p, float(i) / 200.0);
                distance += length(point - previous);
                path_points[slot * PATH_POINTS + i] = vec4(point, distance, 0.0);
                previous = point;
            }
            break;
        }
        default: break;
    }
    particles[slot] = p;
}
''').encode()

UPDATE_SHADER = ('#version 430\n' + COMMON + r'''
layout(local_size_x=64) in;
uniform uint capacity;
uniform float delta_seconds;
uniform int segments;
void main() {
    uint slot = gl_GlobalInvocationID.x;
    if (slot >= capacity) return;
    Particle p = particles[slot];
    if (p.life.z == 0.0) return;
    p.life.x += delta_seconds;
    if (p.life.x >= p.life.y && p.payload.y == 0.0) {
        if (p.payload.x > 0.0) {
            atomicAdd(arrived_units, uint(p.payload.x));
            atomicAdd(arrival_count, 1u);
        }
        p.payload.y = 1.0;
    }
    if (p.life.x >= p.life.y * (1.0 + p.motion.w)) {
        p.life.z = 0.0;
        particles[slot] = p;
        return;
    }
    switch (int(p.target.z)) {
        case 0: {
            float progress = p.life.x / p.life.y;
            float head = min(1.0, progress), tail = max(0.0, progress - p.motion.w);
            p.motion.xy = sample_path(slot, head).xy;
            p.motion.z = progress;
            float fade = clamp(1.0 - max(0.0, progress - 1.0) / p.motion.w, 0.0, 1.0);
            float distance = 0.0;
            vec2 previous = sample_path(slot, tail).xy;
            for (int i=0; i<=segments; ++i) {
                float t = mix(tail, head, float(i) / float(segments));
                vec3 point = sample_path(slot, t);
                vec2 tangent = sample_path(slot, t + 0.005).xy - sample_path(slot, t - 0.005).xy;
                vec2 normal = vec2(-tangent.y, tangent.x) / max(0.00001, length(tangent));
                distance += length(point.xy - previous);
                previous = point.xy;
                uint base = (slot * (MAX_SEGMENTS + 1u) + uint(i)) * 2u;
                ribbon_points[base] = vec4(point.xy, normal);
                ribbon_points[base + 1u] = vec4(distance, 0.0, 0.0, 0.0);
            }
            for (int i=0; i<=segments; ++i) {
                uint base = (slot * (MAX_SEGMENTS + 1u) + uint(i)) * 2u + 1u;
                ribbon_points[base].x = pow(clamp(ribbon_points[base].x / max(0.00001, distance), 0.0, 1.0), 1.5) * fade;
            }
            break;
        }
        default: p.life.z = 0.0; break;
    }
    particles[slot] = p;
    if (p.life.z != 0.0) {
        uint active_index = atomicAdd(draws[1], 2u) / 2u;
        atomicAdd(draws[5], 3u);
        active_indices[active_index] = slot;
    }
}
''').encode()

VERTEX_SHADER = ('#version 430\n' + COMMON + r'''
uniform vec2 outputSize;
uniform float targetFlip;
uniform vec4 transform;
uniform vec4 base_color;
uniform vec4 core_color;
uniform float head_width;
uniform float orb_radius;
uniform int segments;
uniform int mode;
out vec2 uv;
out vec4 ink;
void main() {
    uint layers = mode == 0 ? 2u : 3u;
    uint slot = active_indices[uint(gl_InstanceID) / layers];
    uint layer = uint(gl_InstanceID) % layers;
    Particle p = particles[slot];
    vec2 point;
    if (mode == 0) {
        uint node = uint(gl_VertexID) / 2u;
        float edge = float(gl_VertexID % 2);
        uint base = (slot * (MAX_SEGMENTS + 1u) + node) * 2u;
        vec4 ribbon = ribbon_points[base];
        float pressure = ribbon_points[base + 1u].x;
        float width = head_width * (layer == 0u ? 2.0 : 0.5);
        point = ribbon.xy + ribbon.zw * (edge - 0.5) * width * pressure;
        ink = layer == 0u ? base_color : core_color;
        ink.a *= pressure * (layer == 0u ? 0.85 : 0.9);
        uv = vec2((64.5 + float(node) / float(segments) * 63.0) / 128.0, (0.5 + edge * 63.0) / 64.0);
    } else {
        vec2 corner = vec2(float(gl_VertexID / 2), float(gl_VertexID % 2));
        float radius = orb_radius * (layer == 0u ? 2.4 : (layer == 1u ? 1.0 : 0.45));
        point = p.motion.xy + (corner * 2.0 - 1.0) * radius;
        ink = layer == 2u ? core_color : base_color;
        ink.a *= (p.motion.z <= 1.0 ? 1.0 : 0.0) * (layer == 0u ? 0.1 : (layer == 1u ? 0.9 : 1.0));
        uv = (vec2(0.5) + corner * 63.0) / vec2(128.0, 64.0);
    }
    vec2 screen = transform.xy + point * transform.zw;
    vec2 ndc = screen / outputSize;
    gl_Position = vec4(ndc.x * 2.0 - 1.0, (1.0 - ndc.y * 2.0) * targetFlip, 0.0, 1.0);
}
''').encode()

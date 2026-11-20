"""접지 마찰의 수명·재질별 발생과 프리렌더 부착 좌표. 창을 생성하지 않는다."""

from dataclasses import dataclass, replace
import json
from math import atan2, cos, hypot, radians, sin
from pathlib import Path
from random import Random


MATERIAL_EFFECTS = {"soil": ("scrape_gray", "dirt_debris_gray", "smoke_gray"),
                    "metal": ("spark", "smoke_gray")}


def ground_effect_mode(state, *, attack_index=None, dash=False, waiting=False):
    if state == "boost":
        return "boost"
    if attack_index is not None:
        if waiting:
            return None
        return "dash_attack" if dash else ("attack" if attack_index >= 2 else None)
    return state if state in ("dash", "boost") else None


def trail_in_front(direction):
    return direction not in ("s", "sw", "se")


@dataclass
class GroundParticle:
    kind: str
    position: tuple
    velocity: tuple
    size: tuple
    angle: float
    lifetime_seconds: float
    variant: int
    color: str = "#FFFFFF"
    age_seconds: float = 0
    brightness: float = 1
    alpha_cutoff: float = 0.5
    opacity: float = 1
    gravity: float = 0
    detail: float = 1
    roundness: float = 0
    growth: float = 0.1
    emitter: str = "ground"
    mirror_x: bool = False


class GroundEffects:
    def __init__(self, anchors, *, appearance, capacity=128, emission_seconds=0.04, seed=13, near_front_pixels=32):
        if capacity < 1 or emission_seconds <= 0:
            raise ValueError("입자 수와 발생 간격은 양수여야 한다.")
        self.anchors = json.loads(Path(anchors).read_text(encoding="utf-8"))["clips"]
        self.capacity, self.emission_seconds = capacity, emission_seconds
        self.random = Random(seed)
        self.appearance = appearance
        self.particles = []
        self.emission_elapsed = 0
        self.trail_lengths = {}
        self.trail_ramps = {}
        self.trail_strengths = {}
        self.strength_ramps = {}
        self.near_front_pixels = near_front_pixels
        self.emitter_origins = {}
        self.reverse_motion = False
        self.contact_elapsed_seconds = 0
        self.was_boosting = False
        self.echo_index = 0
        self.emission_index = 0

    def attachment_offsets(self, clip_name, elapsed_seconds, *, loop, scale):
        clip = self.anchors.get(clip_name)
        if clip is None:
            return {}
        time = elapsed_seconds % clip["duration_seconds"] if loop else elapsed_seconds
        position = max(0, min(len(clip["samples"]) - 1, time * clip["sample_hz"]))
        index = int(position)
        a, b = clip["samples"][index], clip["samples"][min(index + 1, len(clip["samples"]) - 1)]
        return {name: tuple((x + (y - x) * (position - index)) * scale for x, y in zip(a[name], b[name]))
                for name in a}

    @staticmethod
    def _resize_trail(particle, length):
        shift = (particle.size[0] - length) / 2
        particle.position = (particle.position[0] + cos(particle.angle) * shift,
                             particle.position[1] + sin(particle.angle) * shift)
        particle.size = (length, particle.size[1])

    def _advance_trail_length(self, emitter, target, seconds, *, fading=False):
        style = self.appearance["trail"]
        duration = style["fade_out_seconds"] if fading else style["length_interpolation_seconds"]
        return self._linear_channel(self.trail_lengths, self.trail_ramps, emitter, target, seconds, duration)

    @staticmethod
    def _linear_channel(values, ramps, emitter, target, seconds, duration):
        current = values.get(emitter, 0)
        ramp = ramps.get(emitter)
        if ramp is None or ramp[1] != target:
            ramp = [current, target, 0]
            ramps[emitter] = ramp
        ramp[2] = min(duration, ramp[2] + seconds)
        value = ramp[0] + (target - ramp[0]) * ramp[2] / duration
        values[emitter] = value
        return value

    def _advance_trail_strength(self, emitter, target, seconds, *, fading=False):
        style = self.appearance["trail"]
        duration = style["fade_out_seconds"] if fading else style["strength_interpolation_seconds"]
        return self._linear_channel(self.trail_strengths, self.strength_ramps, emitter, target, seconds, duration)

    def _fade_trails(self, seconds, active_emitters=()):
        hold = self.appearance["trail"]["afterimage_hold_seconds"]
        for particle in self.particles:
            if particle.kind not in ("trail", "trail_echo") or particle.emitter in active_emitters:
                continue
            elapsed = min(seconds, max(0, particle.age_seconds - hold))
            if elapsed <= 0:
                continue
            length = self._advance_trail_length(particle.emitter, 0, elapsed, fading=True)
            self._resize_trail(particle, length)
            particle.opacity = self._advance_trail_strength(particle.emitter, 0, elapsed, fading=True)

    def _retain_boost_trails(self):
        for particle in list(self.particles):
            if particle.kind != "trail" or not particle.emitter.startswith("calf"):
                continue
            self.echo_index += 1
            key = f"echo_{self.echo_index}_{particle.emitter}"
            self.trail_lengths[key] = particle.size[0]
            self.trail_strengths[key] = particle.opacity
            self.emitter_origins[key] = self.emitter_origins.get(particle.emitter, particle.position)
            self.particles.append(replace(particle, kind="trail_echo", emitter=key))

    def update(self, delta_seconds, *, center, velocity, offsets, active, material, energy_color, strength=1,
               boost_active=False, ground_color=None, reverse_motion=False, foot_contact=False, foot_facing_x=None,
               effect_opacity=None):
        if material not in MATERIAL_EFFECTS:
            raise ValueError("지원하지 않는 지면 재질: " + material)
        self.reverse_motion = reverse_motion
        self.contact_elapsed_seconds += delta_seconds
        self.particles[:] = [p for p in self.particles if p.kind != "foot_friction"]
        for side in ("l", "r"):
            for emitter, key in ((f"sole_{side}", f"sole_{side}"), (f"calf_{side}", f"calf_nozzle_{side}"),
                                 (f"back_{side}", f"back_nozzle_{side}")):
                if key in offsets:
                    self.emitter_origins[emitter] = tuple(c + o for c, o in zip(center, offsets[key]))
        for particle in self.particles:
            particle.age_seconds += delta_seconds
        for particle in self.particles:
            if particle.kind in ("trail", "trail_echo") and particle.age_seconds >= particle.lifetime_seconds:
                for mapping in (self.trail_lengths, self.trail_ramps, self.trail_strengths, self.strength_ramps):
                    mapping.pop(particle.emitter, None)
                if particle.kind == "trail_echo":
                    self.emitter_origins.pop(particle.emitter, None)
        self.particles[:] = [p for p in self.particles if p.age_seconds < p.lifetime_seconds]
        if self.was_boosting and not boost_active:
            self._retain_boost_trails()
        self.was_boosting = boost_active
        if not active or strength <= 0 or not offsets or hypot(*velocity) < 1:
            self._fade_trails(delta_seconds)
            self.emission_elapsed = 0
            return
        self.emission_elapsed += delta_seconds
        trail_opacity = strength if effect_opacity is None else effect_opacity
        opacity_scale = min(1, trail_opacity)
        interval = self.emission_seconds / strength
        speed = hypot(*velocity)
        direction = tuple(v / speed for v in velocity)
        angle = atan2(direction[1], direction[0])
        nozzles = []
        for side in ("l", "r"):
            nozzle = tuple(c + o for c, o in zip(center, offsets[f"calf_nozzle_{side}"]))
            nozzles.append((nozzle, tuple(-v for v in direction), 1, f"calf_{side}"))
            if boost_active and f"back_nozzle_{side}" in offsets:
                origin = offsets[f"back_nozzle_{side}"]
                nozzles.append((tuple(c + o for c, o in zip(center, origin)),
                                tuple(-v for v in direction), self.appearance["thruster_smoke"]["back_scale"],
                                f"back_{side}"))
        active_emitters = {row[3] for row in nozzles}
        self.particles[:] = [p for p in self.particles if p.kind != "trail" or p.emitter not in active_emitters]
        self._fade_trails(delta_seconds, active_emitters)
        for nozzle, exhaust, multiplier, emitter in nozzles:
            style = self.appearance["trail"]
            length = min(style["max_length_pixels"], max(style["min_length_pixels"], speed * style["length_seconds"])) * strength * multiplier
            if boost_active and emitter.startswith("calf"):
                length *= style["boost_length_scale"]
            length = self._advance_trail_length(emitter, length, delta_seconds)
            intensity = self._advance_trail_strength(emitter, trail_opacity, delta_seconds)
            position = tuple(c + d * length / 2 for c, d in zip(nozzle, exhaust))
            self.particles.append(GroundParticle("trail", position, (0, 0), (length, style["width_pixels"] * strength * multiplier),
                atan2(-exhaust[1], -exhaust[0]), style["afterimage_hold_seconds"] + style["fade_out_seconds"], 0, energy_color,
                emitter=emitter, growth=-style["size_decay"], opacity=intensity))
        while self.emission_elapsed >= interval:
            self.emission_elapsed -= interval
            self.emission_index += 1
            for nozzle, exhaust, multiplier, emitter in nozzles:
                orb = self.appearance["energy_orb"]
                if self.emission_index % orb["emission_every"] == 0:
                    for sign in (-1, 1):
                        spread = sign * self.random.uniform(0.5, 1) * orb["spread_pixels_per_second"] * strength * multiplier
                        drift = orb["drift_pixels_per_second"] * strength * multiplier
                        self.particles.append(GroundParticle("energy_orb", nozzle,
                            (exhaust[0] * drift - exhaust[1] * spread, exhaust[1] * drift + exhaust[0] * spread),
                            tuple(v * strength * multiplier for v in orb["size_pixels"]),
                            0, orb["lifetime_seconds"], 0, energy_color, opacity=orb["opacity"] * opacity_scale,
                            growth=orb["growth"], emitter=emitter))
                style = self.appearance["thruster_smoke"]
                spread = self.random.uniform(-1, 1) * style["spread_pixels_per_second"] * multiplier
                drift = style["drift_pixels_per_second"] * strength * multiplier
                self.particles.append(GroundParticle("thruster_smoke", nozzle,
                    (exhaust[0] * drift - exhaust[1] * spread, exhaust[1] * drift + exhaust[0] * spread),
                    tuple(v * strength * multiplier for v in style["size_pixels"]),
                    self.random.uniform(-3.14, 3.14), style["lifetime_seconds"], self.random.randrange(4), style["color"],
                    opacity=style["opacity"] * opacity_scale, detail=style["detail"], roundness=style["roundness"],
                    growth=style["growth"], emitter=emitter))
                for _ in range(style.get("count", 1) - 1):
                    self.particles.append(replace(self.particles[-1], variant=self.random.randrange(4),
                        position=(nozzle[0] + self.random.uniform(-3, 3) * multiplier,
                                  nozzle[1] + self.random.uniform(-3, 3) * multiplier)))
            for side in ("l", "r"):
                foot = tuple(c + o for c, o in zip(center, offsets[f"sole_{side}"]))
                surface_color = ground_color(foot) if ground_color is not None else "#FFFFFF"
                for kind in MATERIAL_EFFECTS[material]:
                    style = self.appearance[kind]
                    size = tuple(value * self.random.uniform(0.85, 1.15) * strength for value in style["size_pixels"])
                    position = foot
                    if kind == "scrape_gray":
                        size = (max(size[0], speed * interval * 1.2), size[1])
                        position = tuple(p - d * size[0] / 2 for p, d in zip(foot, direction))
                    spread = self.random.uniform(-1, 1) * style.get("spread_pixels_per_second", 12)
                    drift = style["drift_pixels_per_second"] * strength
                    self.particles.append(GroundParticle(kind, position,
                        (-direction[0] * drift - direction[1] * spread,
                         -direction[1] * drift + direction[0] * spread - style.get("rise_pixels_per_second", 0)),
                        size, angle + radians(self.random.uniform(-1, 1) * style.get("spread_degrees", 0)),
                        style["lifetime_seconds"], self.random.randrange(4),
                        "#FFCF80" if kind == "spark" else surface_color,
                        brightness=style.get("brightness", 1), alpha_cutoff=style.get("alpha_cutoff", 0.5),
                        opacity=style.get("opacity", 1) * opacity_scale, gravity=style.get("gravity_pixels_per_second_squared", 0),
                        detail=style.get("detail", 1), roundness=style.get("roundness", 0), growth=style.get("growth", 0.1),
                        emitter=f"sole_{side}"))
                    for _ in range(style.get("count", 1) - 1):
                        spread = style.get("spawn_spread_pixels", 8)
                        self.particles.append(replace(self.particles[-1], variant=self.random.randrange(4),
                            position=(position[0] + self.random.uniform(-spread, spread),
                                      position[1] + self.random.uniform(-spread, spread))))
        if foot_contact and (style := self.appearance.get("foot_friction")):
            for side in ("l", "r"):
                foot = tuple(c + o for c, o in zip(center, offsets[f"sole_{side}"]))
                color = ground_color(foot) if ground_color is not None else style["color"]
                self.particles.append(GroundParticle("foot_friction", foot, (0, 0),
                    tuple(value * strength for value in style["size_pixels"]), 0, 1,
                    int(self.contact_elapsed_seconds * style["variant_hz"]) % 4, color,
                    opacity=style["opacity"] * opacity_scale, detail=style["detail"], growth=0, emitter=f"sole_{side}",
                    mirror_x=(velocity[0] if foot_facing_x is None else foot_facing_x) < 0))
        anchored = [p for p in self.particles if p.kind in ("trail", "trail_echo")]
        anchored += [p for p in self.particles if p.kind == "foot_friction"]
        anchored = anchored[-self.capacity:]
        count = self.capacity - len(anchored)
        clouds = [p for p in self.particles if p.kind not in ("trail", "trail_echo", "foot_friction")]
        self.particles[:] = (clouds[-count:] if count else []) + anchored

    def reset(self):
        self.contact_elapsed_seconds = 0
        self.particles.clear()
        self.emission_elapsed = 0
        self.trail_lengths.clear()
        self.trail_ramps.clear()
        self.trail_strengths.clear()
        self.strength_ramps.clear()
        self.emitter_origins.clear()
        self.reverse_motion = False
        self.was_boosting = False
        self.echo_index = 0
        self.emission_index = 0

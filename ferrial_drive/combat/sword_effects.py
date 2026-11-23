"""실제 검날 궤적의 Trail·에너지별 판정 면·전신 잔상. 창과 입력을 소유하지 않는다."""

from bisect import bisect_right
from dataclasses import dataclass
from math import ceil, cos, isfinite, pi, sin, sqrt

from ferrial_drive.rendering.motion_vectors import target_phase
from ferrial_drive.rendering.part_metadata import PackedTrackRows
from ferrial_drive.rendering.part_metadata_archive import read_track_metadata
from ferrial_drive.assets.directional import SCREEN_DIRECTIONS
from .geometry import Capsule, Vec2, bounding_capsule, capsule_touches_circle, convex_hull, moving_circle_touches_polygon
from .sword_contact import SwordContactEffects


def camera_root(camera):
    """Unreal 직교 카메라의 지면 root를 원본 이미지 왼쪽 위 좌표로 투영한다."""
    forward = [b - a for a, b in zip(camera["position"], camera["target"])]
    length = sqrt(sum(v * v for v in forward))
    forward = [v / length for v in forward]
    right = [-forward[1], forward[0], 0]
    length = sqrt(sum(v * v for v in right))
    right = [v / length for v in right]
    up = [forward[1] * right[2] - forward[2] * right[1],
          forward[2] * right[0] - forward[0] * right[2],
          forward[0] * right[1] - forward[1] * right[0]]
    width, height = camera.get("size", [768, 768])
    scale = width / camera["width_cm"]
    offset = [-v for v in camera["target"]]
    return Vec2(width / 2 + sum(a * b for a, b in zip(offset, right)) * scale,
                height / 2 - sum(a * b for a, b in zip(offset, up)) * scale)


class BladeTrajectory:
    def __init__(self, clips):
        if not clips or any(not self._valid_times(rows) for rows in clips.values()):
            raise ValueError("검 궤적은 클립마다 시간 순서의 표본 두 개 이상이 필요하다.")
        self.clips = clips

    @staticmethod
    def _valid_times(rows):
        if len(rows) < 2:
            return False
        if isinstance(rows, PackedTrackRows):
            return all(rows.time_at(i - 1) < rows.time_at(i) for i in range(1, len(rows)))
        return not any(a[0] >= b[0] for a, b in zip(rows, rows[1:]))

    @classmethod
    def load(cls, path):
        data = read_track_metadata(path)
        if data.get("type") in ("sword_trail_sample", "sword_blade_projection"):
            return cls({name: rows if isinstance(rows, PackedTrackRows) else
                        [(row["time_seconds"], Vec2(*row["root"]), Vec2(*row["tip"]))
                               for row in rows] for name, rows in data["clips"].items()})
        clips = {}
        for clip in data["clips"]:
            rows = [row for row in data["samples"] if row["clip_index"] == clip["index"]]
            for direction, camera in data["cameras"].items():
                origin = camera_root(camera)
                clips[f"combo_{clip['index']:02}/{direction}"] = [
                    (row["clip_time_seconds"],
                     Vec2(*row["screen_top_left_px"][direction]["cutting_edge_root"]) - origin,
                     Vec2(*row["screen_top_left_px"][direction]["cutting_edge_tip"]) - origin)
                    for row in rows]
        return cls(clips)

    def pose(self, name, seconds, scale, reach_scale):
        rows = self.clips[name]
        if isinstance(rows, PackedTrackRows):
            next_index = bisect_right(range(len(rows)), seconds, key=rows.time_at)
            index = max(0, min(len(rows) - 2, next_index - 1))
            a, b = [(row["time_seconds"], Vec2(*row["root"]), Vec2(*row["tip"]))
                    for row in rows[index:index + 2]]
        else:
            index = max(0, min(len(rows) - 2, bisect_right(rows, seconds, key=lambda row: row[0]) - 1))
            a, b = rows[index:index + 2]
        fraction = max(0, min(1, (seconds - a[0]) / max(1e-9, b[0] - a[0])))
        root = (a[1] + (b[1] - a[1]) * fraction) * scale
        tip = (a[2] + (b[2] - a[2]) * fraction) * scale
        return root, root + (tip - root) * reach_scale


@dataclass(frozen=True)
class SwordSection:
    vertices: tuple
    root_a: Vec2
    tip_a: Vec2
    root_b: Vec2
    tip_b: Vec2
    created_seconds: float
    lifetime_seconds: float
    strike_id: int
    energy_level: int
    hit_vertices: tuple
    chevron: tuple = ()
    hit_capsule: Capsule | None = None
    color: str | None = None


@dataclass(frozen=True)
class AttackEcho:
    clip_name: str
    elapsed_seconds: float
    position_m: tuple
    created_seconds: float
    lifetime_seconds: float
    opacity: float
    tint: tuple = (1, 1, 1)
    tint_mix: float = 0
    pose_clip_name: str | None = None


@dataclass(frozen=True)
class SwordTarget:
    target_id: str
    center: Vec2
    radius_pixels: float
    material: str = "generic"
    position_m: tuple[float, float] | None = None
    eid: int | None = None

    def __post_init__(self):
        if self.position_m is not None and (len(self.position_m) != 2 or not all(map(isfinite, self.position_m))):
            raise ValueError("표적의 지면 위치는 유한한 2차원 미터 좌표여야 한다.")


@dataclass(frozen=True)
class BodyWind:
    center: Vec2
    arc: tuple
    energy_level: int
    radius_pixels: float
    band_width_pixels: float

    @property
    def triangles(self):
        return tuple((self.center, first, second) for first, second in zip(self.arc, self.arc[1:]))


def body_wind_sector(center, direction, settings, energy_level):
    """등 뒤의 열린 부채꼴을 닫지 않고 나머지를 삼각형으로 나눈다."""
    scales = settings.get("level_scales", (1, 1.25, 1.5))
    if (type(energy_level) is not int or not 1 <= energy_level <= 3 or len(scales) != 3
            or not all(isfinite(value) and value > 0 for value in scales)):
        raise ValueError("몸 주변 검풍은 에너지 1~3의 양수 크기 배율이 필요하다.")
    scale = scales[energy_level - 1]
    radius = settings.get("radius_pixels", 96) * scale
    band_width = settings.get("band_width_pixels", 18) * scale
    half_angle = settings.get("rear_half_angle_degrees", 30)
    segments = settings.get("segments", 30)
    offset = settings.get("center_offset_pixels", (0, -80))
    if (not isfinite(radius) or radius <= 0 or not isfinite(band_width) or not 0 < band_width <= radius
            or not isfinite(half_angle) or not 0 < half_angle < 180
            or type(segments) is not int or segments < 3 or len(offset) != 2
            or not all(isfinite(value) for value in offset)):
        raise ValueError("몸 주변 검풍의 반경·후방 제외 각도·분할 오류")
    center = center + Vec2(*offset)
    facing = SCREEN_DIRECTIONS.index(direction) * pi / 4
    start = facing - pi + half_angle * pi / 180
    sweep = 2 * pi - 2 * half_angle * pi / 180
    arc = tuple(center + Vec2(cos(start + sweep * i / segments), sin(start + sweep * i / segments)) * radius
                for i in range(segments + 1))
    return BodyWind(center, arc, energy_level, radius, band_width)


class SwordEffects:
    def __init__(self, trajectory, settings, *, scale, project, easing="accelerate", y_pixels_per_meter=1,
                 hitbox_type="polygon"):
        if hitbox_type not in ("polygon","capsule"):
            raise ValueError("근접 판정은 polygon 또는 capsule이다.")
        self.hitbox_type = hitbox_type
        self.trajectory, self.settings = trajectory, settings
        self.scale, self.project, self.easing = scale, project, easing
        self.y_pixels_per_meter = y_pixels_per_meter
        self.profiles = settings["levels"]
        if (len(self.profiles) != 3 or any(
                not isfinite(p["reach_scale"]) or p["reach_scale"] <= 0
                or not isfinite(p["trail_seconds"]) or p["trail_seconds"] <= 0
                or type(p["echo_count"]) is not int or p["echo_count"] < 0
                or p["echo_seconds"] <= 0 or p["echo_interval_seconds"] <= 0
                or not 0 <= p["echo_opacity"] <= 1
                or not 0 <= p.get("echo_tint_mix", 0) <= 1 for p in self.profiles)):
            raise ValueError("검 효과는 양수 범위·수명의 에너지 1~3 프로필이 필요하다.")
        if (not isfinite(settings["sample_seconds"]) or settings["sample_seconds"] <= 0
                or type(settings["max_sections"]) is not int or settings["max_sections"] <= 0
                or not isfinite(y_pixels_per_meter) or y_pixels_per_meter <= 0
                or settings.get("hit_y_margin_m", 0) < 0):
            raise ValueError("검 효과 표본 간격·상한·투영 배율은 양수이며 Y 여유는 0 이상이어야 한다.")
        self.contact_effects = SwordContactEffects(settings["contact_effects"]) if "contact_effects" in settings else None
        self.reset()

    def reset(self):
        self.time_seconds = 0
        self.sections, self.hit_sections, self.echoes, self.hits = [], [], [], []
        self._hit_strike_id, self._hit_targets = None, set()
        self._next_echo_seconds = 0
        self.body_winds = []
        self.last_collision_checks = 0
        if self.contact_effects:
            self.contact_effects.reset()

    def _window(self, step):
        low, high = self.settings["active_phase_windows"][int(step.clip_name[6:8]) - 1]
        result = []
        for boundary in (low, high):
            a, b = 0.0, 1.0
            for _ in range(24):
                middle = (a + b) / 2
                if target_phase(middle, easing=self.easing) < boundary:
                    a = middle
                else:
                    b = middle
            result.append((a + b) / 2 * step.duration_seconds)
        return result

    def update(self, seconds, steps, energy_level, targets=(), *, energy_color=None, trail_color=None, reach_multiplier=1):
        if not isfinite(reach_multiplier) or reach_multiplier <= 0:
            raise ValueError("검 범위 배율은 양수 유한값이어야 한다.")
        if not isfinite(seconds) or seconds < 0 or type(energy_level) is not int or not 1 <= energy_level <= 3:
            raise ValueError("시간은 0 이상의 유한값, 에너지 레벨은 1~3 정수여야 한다.")
        profile = self.profiles[energy_level - 1]
        energy_color = energy_color or profile.get("color", "#9DDFEA")
        trail_color = trail_color or energy_color
        tint = tuple(int(energy_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        frame_start = self.time_seconds
        self.time_seconds += seconds
        self.last_collision_checks = 0
        self.hit_sections, self.hits = [], []
        self.body_winds = []
        cursor = 0
        for step in steps:
            window_start, window_end = self._window(step)
            low, high = max(step.start_seconds, window_start), min(step.end_seconds, window_end)
            if high <= low or step.end_seconds <= step.start_seconds:
                self.body_winds = []
                cursor += step.real_seconds
                continue
            fraction_a = (low - step.start_seconds) / (step.end_seconds - step.start_seconds)
            fraction_b = (high - step.start_seconds) / (step.end_seconds - step.start_seconds)
            count = max(1, ceil((fraction_b - fraction_a) * step.real_seconds / self.settings["sample_seconds"]))
            previous = None
            for index in range(count + 1):
                fraction = fraction_a + (fraction_b - fraction_a) * index / count
                elapsed = step.start_seconds + (step.end_seconds - step.start_seconds) * fraction
                position = tuple(a + (b - a) * fraction for a, b in zip(step.start_position_m, step.end_position_m))
                origin = Vec2(*self.project(position))
                source_seconds = target_phase(elapsed / step.duration_seconds, easing=self.easing) * step.duration_seconds
                reach = profile["reach_scale"] * reach_multiplier * (self.settings.get("dash_reach_scale", 1) if step.dash else 1)
                root, tip = self.trajectory.pose(step.clip_name, source_seconds, self.scale, reach)
                root, tip = root + origin, tip + origin
                created = frame_start + cursor + fraction * step.real_seconds
                if previous is not None:
                    before_root, before_tip = previous
                    normal = Vec2(-(tip - root).y, (tip - root).x).normalized() * self.settings["half_width_pixels"]
                    points = [p + offset for p in (before_root, before_tip, root, tip)
                              for offset in (normal, normal * -1)]
                    chevron = ()
                    if step.clip_name.startswith("combo_03/"):
                        for base, end in ((before_root, before_tip), (root, tip)):
                            axis = end - base
                            width = (axis.length * self.settings.get("thrust_width_ratio", 0.25)
                                     / (2 * self.profiles[0]["reach_scale"]))
                            side = Vec2(-axis.y, axis.x).normalized(Vec2(0, 1)) * width
                            back = end - axis * 0.35
                            wings = (back + side, end, back - side)
                            points.extend(wings)
                        chevron = wings
                    margin_m = (self.settings.get("capsule_margin_m",self.settings.get("hit_y_margin_m",0))
                                if self.hitbox_type == "capsule" else self.settings.get("hit_y_margin_m",0))
                    margin_pixels = margin_m*self.y_pixels_per_meter
                    capsule = None
                    if self.hitbox_type == "capsule":
                        axis_start = Vec2((before_root.x+root.x)*.5,(before_root.y+root.y)*.5)
                        axis_end = Vec2((before_tip.x+tip.x)*.5,(before_tip.y+tip.y)*.5)
                        capsule = bounding_capsule(points,axis_start,axis_end,margin_pixels)
                        vertices,hit_vertices = tuple(points),()
                    else:
                        vertices = convex_hull(points)
                        margin = Vec2(0,margin_pixels)
                        hit_vertices = convex_hull([p+offset for p in vertices for offset in (margin,margin*-1)])
                    section = SwordSection(vertices, before_root, before_tip, root, tip, created,
                                           profile["trail_seconds"], step.strike_id, energy_level, hit_vertices, chevron,capsule,
                                           color=trail_color)
                    self.sections.append(section)
                    self.hit_sections.append(section)
                    if self._hit_strike_id != step.strike_id:
                        self._hit_strike_id, self._hit_targets = step.strike_id, set()
                    for target in targets:
                        if target.target_id in self._hit_targets:
                            continue
                        self.last_collision_checks += 1
                        contact = (capsule_touches_circle(capsule,target.center,target.radius_pixels) if capsule else
                                   moving_circle_touches_polygon(target.center,target.center,target.radius_pixels,hit_vertices))
                        if contact:
                            self._hit_targets.add(target.target_id)
                            self.hits.append((step.strike_id, target.target_id))
                if profile["echo_count"] and created + 1e-9 >= self._next_echo_seconds:
                    self.echoes.append(AttackEcho(step.clip_name, elapsed, position, created,
                                                profile["echo_seconds"], profile["echo_opacity"],
                                                tint, profile.get("echo_tint_mix", 0),
                                                (self.trajectory.echo_clip_name(step.clip_name,elapsed)
                                                 if hasattr(self.trajectory,"echo_clip_name") else None)))
                    self._next_echo_seconds = created + profile["echo_interval_seconds"]
                previous = root, tip
            wind_settings = self.settings.get("body_wind", {})
            if wind_settings.get("enabled", False):
                origins = [Vec2(*self.project(tuple(a + (b - a) * fraction for a, b in
                           zip(step.start_position_m, step.end_position_m)))) for fraction in (fraction_a, fraction_b)]
                winds = [body_wind_sector(origin, step.clip_name.rsplit("/", 1)[1], wind_settings, energy_level)
                         for origin in origins]
                # 이동 중에도 각 삼각형만 쓸어 검사한다. 전체 볼록 외곽은 후방 빈틈을 메우므로 금지한다.
                if self.hitbox_type == "capsule":
                    swept = []
                    for before,after in zip(winds[0].triangles,winds[1].triangles):
                        a = Vec2((before[0].x+after[0].x)*.5,(before[0].y+after[0].y)*.5)
                        b = Vec2((before[1].x+before[2].x+after[1].x+after[2].x)*.25,
                                 (before[1].y+before[2].y+after[1].y+after[2].y)*.25)
                        swept.append(bounding_capsule(before+after,a,b))
                else:
                    swept = [convex_hull(before+after) for before,after in zip(winds[0].triangles,winds[1].triangles)]
                for target in targets:
                    if target.target_id in self._hit_targets:
                        continue
                    for volume in swept:
                        self.last_collision_checks += 1
                        contact = (capsule_touches_circle(volume,target.center,target.radius_pixels)
                                   if self.hitbox_type == "capsule" else moving_circle_touches_polygon(
                                       target.center,target.center,target.radius_pixels,volume))
                        if contact:
                            self._hit_targets.add(target.target_id)
                            self.hits.append((step.strike_id,target.target_id))
                            break
                # 끝난 유효 구간의 검풍은 공간에 남기지 않는다.
                if step.end_seconds <= window_end + 1e-9:
                    self.body_winds = [winds[1]]
                else:
                    self.body_winds = []
            cursor += step.real_seconds
        self.sections = [s for s in self.sections if self.time_seconds - s.created_seconds < s.lifetime_seconds]
        self.sections = self.sections[-self.settings["max_sections"]:]
        self.echoes = [e for e in self.echoes if self.time_seconds - e.created_seconds < e.lifetime_seconds]
        self.echoes = self.echoes[-profile["echo_count"]:] if profile["echo_count"] else []
        if self.contact_effects:
            self.contact_effects.update(seconds, self.hits, self.sections, targets, energy_level=energy_level)

    def opacity(self, item):
        return max(0, 1 - (self.time_seconds - item.created_seconds) / item.lifetime_seconds)

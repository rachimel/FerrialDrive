"""교전 상태를 기존 메카 번들과 독립 PBR 파츠의 재생 시각으로 변환한다."""

from dataclasses import dataclass, field
import json
from math import isfinite

from ferrial_drive.assets.catalog import AssetCatalog, read_document
from ferrial_drive.assets.directional import SCREEN_DIRECTIONS
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from .enemy_encounter import ENEMY_KINDS
from .locomotion import direction_name


ATTACK_PHASES = ("windup", "active", "recovery")
MOTIONS = ("move", "attack", "hit")
PART_DIRECTIONS = ("s", "sw", "w", "nw", "n", "ne", "e", "se")


@dataclass
class EnemySprite:
    resource: object
    scale: float
    stride_m: float
    attack_frames: tuple
    muzzle_offsets: dict
    part_counts: dict | None = None
    attack_motions: dict = field(default_factory=dict)
    pose_cache: object = field(default=None, init=False, repr=False)
    body_batch: object = field(default=None, init=False, repr=False)
    shadow_batch: object = field(default=None, init=False, repr=False)
    shadow_batch_unavailable: str | None = field(default=None, init=False, repr=False)

    def close(self):
        if self.shadow_batch is not None:
            self.shadow_batch.close()
        if self.body_batch is not None:
            self.body_batch.close()
        if self.pose_cache is not None:
            self.pose_cache.close()
        self.resource.close()

    @property
    def break_motion(self):
        return "break" if self.part_counts or "break/s" in self.resource.clips else "death"

    @property
    def sample_fps(self):
        return self.resource.data["sample_fps"] if self.part_counts else 12

    def frame_count(self, motion, direction="s"):
        if self.part_counts:
            return self.part_counts[motion] * self.sample_fps // 12 + 1
        return len(self.resource.clips[f"{motion}/{direction}"].frames)

    @classmethod
    def load(cls, definition, settings, backend):
        scale, stride_m = settings["scale"], settings["stride_m"]
        attack_frames = tuple(settings["attack_frames"])
        sprite = cls(backend.load(read_document(definition)), scale, stride_m, attack_frames,
                     settings.get("muzzle_offsets", {}), attack_motions=settings.get("attack_motions", {}))
        try:
            sprite.validate()
        except BaseException:
            sprite.resource.close()
            raise
        return sprite

    def validate(self):
        if not all(isfinite(v) and v > 0 for v in (self.scale, self.stride_m)):
            raise ValueError("적 스프라이트 배율과 보폭은 양수여야 한다.")
        if not isinstance(self.attack_motions, dict):
            raise ValueError("적 공격 모션은 공격 종류별 설정이 필요하다.")
        attacks = [("attack", self.attack_frames)]
        for kind, spec in self.attack_motions.items():
            if (not isinstance(kind, str) or not kind or not isinstance(spec, dict)
                    or not isinstance(spec.get("motion"), str) or not spec["motion"]
                    or not isinstance(spec.get("attack_frames"), (list, tuple))):
                raise ValueError("적 공격 모션에는 이름과 공격·회수 시작 프레임이 필요하다.")
            attacks.append((spec["motion"], spec["attack_frames"]))
        attack_names = {motion for motion, _ in attacks}
        for motion in {*MOTIONS, self.break_motion, *attack_names}:
            if self.part_counts:
                if self.part_counts.get(motion, 0) < 1 or set(self.resource.data["motions"].get(motion, ())) != set("01234567"):
                    raise ValueError(f"적 파츠의 {motion}에 8방향과 재생 길이가 필요하다.")
            else:
                rows = [self.resource.clips.get(f"{motion}/{direction}") for direction in SCREEN_DIRECTIONS]
                if any(clip is None for clip in rows) or len({(len(clip.frames), clip.fps) for clip in rows}) != 1:
                    raise ValueError(f"적 스프라이트에 {motion}의 동일한 8방향 클립이 필요하다.")
        for motion, cuts in attacks:
            count = self.part_counts[motion] if self.part_counts else self.frame_count(motion)
            if len(cuts) != 2 or any(type(value) is not int for value in cuts) or not 0 < cuts[0] < cuts[1] < count:
                raise ValueError(f"{motion}의 공격·회수 시작 프레임이 동작 범위를 벗어났다.")
        for name, frames in self.muzzle_offsets.items():
            motion, _, direction = name.partition("/")
            if motion not in attack_names or direction not in SCREEN_DIRECTIONS:
                raise ValueError("포구 좌표는 공격 클립에만 연결한다.")
            if len(frames) != self.frame_count(motion, direction) or any(
                    len(point) != 2 or not all(isfinite(v) for v in point)
                    for frame in frames for point in frame):
                raise ValueError("포구 좌표가 프레임과 일치하지 않는다.")

    @property
    def death_seconds(self):
        return self.duration(self.break_motion)

    def duration(self, motion):
        if self.part_counts:
            return self.part_counts[motion] / 12
        return self.resource.clips[f"{motion}/s"].duration_ms / 1000

    def playback(self, enemy):
        direction = direction_name((enemy.facing.x, enemy.facing.y))
        if not enemy.alive:
            return self.break_motion, direction, max(0, self.death_seconds - enemy.death_remaining_seconds)
        if enemy.knockback_remaining_seconds > 0:
            fraction = 1 - enemy.knockback_remaining_seconds / enemy.knockback_duration_seconds
            return "hit", direction, max(0, fraction) * self.duration("hit")
        movement = enemy.locomotion_step_m
        walking_recovery = (
            enemy.phase == "recovery" and enemy.attack_kind == "ranged"
            and enemy.profile.recovery_seconds - enemy.remaining_seconds >= .12
            and movement.length > 1e-6
        )
        if enemy.phase in ATTACK_PHASES and not walking_recovery:
            spec = self.attack_motions.get(enemy.attack_kind)
            motion = spec["motion"] if spec else "attack"
            end_frame = self.part_counts[motion] if self.part_counts else self.frame_count(motion)
            cuts = (0, *(spec["attack_frames"] if spec else self.attack_frames), end_frame)
            phase = ATTACK_PHASES.index(enemy.phase)
            duration = getattr(enemy.profile, f"{enemy.phase}_seconds")
            first, end = cuts[phase:phase + 2]
            fraction = min(.999999, max(0, 1 - enemy.remaining_seconds / duration))
            return motion, direction, (first + fraction * (end - first)) / 12
        backwards = movement.x * enemy.facing.x + movement.y * enemy.facing.y < -1e-6
        distance = -enemy.locomotion_m if backwards else enemy.locomotion_m
        if not backwards and movement.length > 1e-6:
            direction = direction_name((movement.x, movement.y))
        return "move", direction, (distance / self.stride_m % 1) * self.duration("move")

    def frame(self, enemy):
        motion, direction, seconds = self.playback(enemy)
        index = min(self.frame_count(motion, direction) - 1, int(seconds * self.sample_fps + 1e-7))
        return f"{motion}/{direction}", index

    @staticmethod
    def part_clip(motion, direction):
        index = PART_DIRECTIONS.index(direction)
        return f"{motion}/u{index}l{index}"

    def prepare_frame(self, playbacks):
        if self.resource.stream_budget is None:
            return
        clips = dict.fromkeys(self.part_clip(motion, direction) for motion, direction, _ in playbacks)
        self.resource.prepare_frame(clips, self.resource.data["quality"])

    def display_playback(self, playback):
        motion, direction, seconds = playback
        pose = self.resource.display_pose(self.part_clip(motion, direction), seconds)
        if pose is None:
            return None
        name, seconds, _ = pose
        return name.rsplit("/", 1)[0], PART_DIRECTIONS[int(name[-1])], seconds

    def ground_shadow_pose(self, playback):
        motion, direction, seconds = playback
        clip = self.part_clip(motion, direction)
        return clip, int(seconds * self.sample_fps + 1e-7) / self.sample_fps

    def draw_ground_shadow(self, shadow_pose, x, foot, zoom, opacity, softness_pixels):
        clip, seconds = shadow_pose
        return self.resource.draw_ground_shadow(clip, seconds, x, foot, self.scale * zoom,
                                                opacity, softness_pixels=softness_pixels, cache_geometry=True)

    def shared_frames(self):
        if self.pose_cache is None:
            from ferrial_drive.rendering.enemy_pose_cache import EnemyPoseCache
            self.pose_cache = EnemyPoseCache(self.resource)
        return self.pose_cache

    def draw_ground_shadows(self, shadow_pose, placements, zoom, opacity, softness_pixels, *, shared_frame=False):
        if shared_frame:
            return self.shared_frames().draw_shadows(shadow_pose, placements, self.scale * zoom, opacity, softness_pixels)
        clip, seconds = shadow_pose
        return self.resource.draw_ground_shadows(clip, seconds, placements, self.scale * zoom,
                                                 opacity, softness_pixels=softness_pixels, cache_geometry=True)

    def prepare_bodies(self, requests, zoom):
        if self.body_batch is None:
            from ferrial_drive.rendering.enemy_part_batch import EnemyPartBatch
            self.body_batch = EnemyPartBatch(self.resource)
        return self.body_batch.prepare(requests, self.scale * zoom)

    def draw_near_shadows(self, groups, zoom, opacity, softness):
        shadow = self.resource.shadow_map
        if shadow is None or not shadow.enabled or opacity <= 0:
            return 0, 0
        if len(groups) >= 2 and self.shadow_batch is None and not self.shadow_batch_unavailable:
            from ferrial_drive.rendering.enemy_shadow_batch import EnemyShadowBatch
            try:
                self.shadow_batch = EnemyShadowBatch(self.resource)
            except RuntimeError as exc:
                self.shadow_batch_unavailable = str(exc)
        if self.shadow_batch is not None:
            count = self.shadow_batch.draw(groups, self.scale * zoom, opacity, softness)
            return count, self.shadow_batch.submits
        return sum(self.draw_ground_shadows(pose, positions, zoom, opacity, softness)
                   for pose, positions in groups), 0

    def draw(self, enemy, x, foot, zoom, *, playback=None, shared_frame=False, prepared=None):
        motion, direction, seconds = playback if playback is not None else self.playback(enemy)
        name = f"{motion}/{direction}"
        index = min(self.frame_count(motion, direction) - 1, int(seconds * self.sample_fps + 1e-7))
        scale = self.scale * zoom
        if self.part_counts:
            clip = self.part_clip(motion, direction)
            if prepared is not None:
                top = self.body_batch.copy(prepared)
            elif shared_frame:
                top = self.shared_frames().draw(clip, index, x, foot, scale)
            else:
                top = self.resource.draw(clip, seconds, x, foot, scale=scale, sample_shadow=False).y
            scale *= self.resource.data["pixel_scale"]
        else:
            y = self.resource.pico.get_canvas_height() - foot
            self.resource.draw(name, index, x, y, scale=scale)
            top = self.resource.target_rect(self.resource.clips[name].frames[index], x, y, scale).y
        offsets = self.muzzle_offsets.get(name)
        muzzles = tuple((x + dx * scale, foot + dy * scale) for dx, dy in offsets[index]) if offsets else ()
        return top, muzzles, motion


def load_enemy_part_sprites(path, pico, lighting, settings, timings, stream_budget=None):
    """전투의 적도 플레이어와 동일한 PBR 아틀라스 로더에 올린다."""
    from ferrial_drive.rendering.pico_part_motion import PicoPartMotion

    if not path.is_file():
        return {}
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    sprites = {}
    try:
        for kind, row in config["profiles"].items():
            if kind not in ENEMY_KINDS:
                raise ValueError(f"교전 프로필에서 지원하지 않는 적 유형이다: {kind}")
            source = path.parent / row["qualities"][settings.texture_quality]
            resource = PicoPartMotion(pico, source, timings=timings, direction_warp=False,
                                      max_directions=32, cache_budget_bytes=48 * 1024**2,
                                      pbr_lighting=lighting, upscale_aa=settings.upscale_aa)
            sprite = EnemySprite(resource, 1, row["stride_m"], tuple(row["attack_frames"]),
                                row.get("muzzle_offsets", {}), row["frames"], row.get("attack_motions", {}))
            sprites[kind] = sprite
            if "energy_color" in row:
                color = tuple(row["energy_color"])
                if len(color) != 3 or any(not 0 <= channel <= 1 for channel in color):
                    raise ValueError("적 발광색에는 0~1 범위의 RGB 값 세 개가 필요하다.")
                resource.energy_color = color
            sprite.validate()
            if (not resource.pbr_lighting or resource.data["quality"] != settings.texture_quality
                    or resource.data.get("sample_fps") != 24 or resource.data.get("color_codec") != "bc7_zlib"
                    or resource.data.get("vector_divisor") != 2):
                raise ValueError("적 파츠는 플레이어와 동일한 품질의 BC7·24fps PBR 규격을 사용한다.")
            if stream_budget is not None:
                resource.enable_streaming(stream_budget, "move")
    except BaseException:
        for sprite in sprites.values():
            sprite.resource.close()
        raise
    return sprites


def load_enemy_sprites(path):
    """공개 시연은 로컬 에셋이 없어도 기존 도형으로 실행된다."""
    if not path.is_file():
        return {}
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    catalog = AssetCatalog.load(path.parent / config["catalog"])
    backend = PicoAssetBackend("linear", layers=("body",))
    sprites = {}
    try:
        for kind, row in config["profiles"].items():
            definition = catalog.definitions[row["asset"]]
            if kind not in ENEMY_KINDS or definition.kind != "mech":
                raise ValueError("교전 적 에셋은 지원하는 적 유형의 메카 번들이 필요하다.")
            sprites[kind] = EnemySprite.load(definition, row, backend)
    except BaseException:
        for sprite in sprites.values():
            sprite.resource.close()
        raise
    return sprites

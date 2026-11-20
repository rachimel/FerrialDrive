"""원거리 적의 PBR 본체·지면 그림자 표본을 GPU 텍스처로 공유한다."""

from collections import OrderedDict
from dataclasses import dataclass

from .part_motion_atlas import frame_state
from .part_upscale import render_target
from .pose_copy_batch import MIN_POSE_COPIES, create_pose_copy_batch


@dataclass(frozen=True, slots=True)
class PoseTexture:
    texture: object
    left: int
    top: int
    width: int
    height: int


class EnemyPoseCache:
    def __init__(self, resource, budget_bytes=32 * 1024 ** 2):
        self.resource = resource
        self.entries = OrderedDict()
        self.budget_bytes = budget_bytes
        self.bytes = 0
        self.hits = self.misses = 0
        self.copy_batch = create_pose_copy_batch(resource.pico)

    def _lookup(self, key):
        entry = self.entries.get(key)
        if entry is not None:
            self.entries.move_to_end(key)
            self.hits += 1
        return entry

    def _capture(self, key, bounds, paint):
        resource = self.resource
        p = resource.pico
        left, top, width, height = bounds
        cost = width * height * 4
        if cost > self.budget_bytes:
            return None
        while self.bytes + cost > self.budget_bytes:
            _, old = self.entries.popitem(last=False)
            p.SDL_DestroyTexture(old.texture)
            self.bytes -= old.width * old.height * 4
        texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_TARGET, width, height)
        if not texture:
            raise RuntimeError("적 공유 프레임 텍스처 생성 실패")
        try:
            blend = p.SDL_ComposeCustomBlendMode(p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
                p.SDL_BLENDOPERATION_ADD, p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
                p.SDL_BLENDOPERATION_ADD)
            if p.SDL_SetTextureBlendMode(texture, blend) or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear):
                raise RuntimeError("적 공유 프레임 블렌딩 설정 실패")
            pivot_x, pivot_y = resource.data["pivot_top_left"]
            with render_target(p, texture):
                paint(pivot_x - left, pivot_y - top)
        except BaseException:
            p.SDL_DestroyTexture(texture)
            raise
        entry = self.entries[key] = PoseTexture(texture, *bounds)
        self.bytes += cost
        self.misses += 1
        return entry

    def _copy(self, entry, placements, scale):
        p = self.resource.pico
        pivot_x, pivot_y = self.resource.data["pivot_top_left"]
        factor = scale * self.resource.data["pixel_scale"]
        dx, dy = (entry.left - pivot_x) * factor, (entry.top - pivot_y) * factor
        width, height = max(1, round(entry.width * factor)), max(1, round(entry.height * factor))
        if self.copy_batch is not None and len(placements) >= MIN_POSE_COPIES:
            if self.copy_batch.draw(entry.texture, placements, dx, dy, width, height):
                return round(placements[-1][1] + dy)
            self.copy_batch = None
        destination = p.SDL_Rect(0, 0, width, height)
        for x, foot in placements:
            destination.x, destination.y = round(x + dx), round(foot + dy)
            if p.SDL_RenderCopy(p.renderer, entry.texture, None, destination):
                raise RuntimeError("적 공유 프레임 그리기 실패")
        return destination.y

    def draw(self, clip_name, index, x, foot, scale):
        key = "body", clip_name, index
        entry = self._lookup(key)
        if entry is None:
            resource = self.resource
            motion, pair = clip_name.rsplit("/", 1)
            clip = resource.get(motion, pair[1])["data"]["clip"]
            seconds = index / resource.data["sample_fps"]
            bounds = frame_state(clip, clip, seconds)["bounds"]
            entry = self._capture(key, bounds, lambda px, py: resource.draw(clip_name, seconds, px, py,
                                  scale=1 / resource.data["pixel_scale"], sample_shadow=False))
            if entry is None:
                return resource.draw(clip_name, seconds, x, foot, scale=scale, sample_shadow=False).y
        return self._copy(entry, ((x, foot),), scale)

    def draw_shadows(self, pose, placements, scale, opacity, softness_pixels):
        resource = self.resource
        shadow = resource.shadow_map
        if shadow is None or not shadow.enabled or opacity <= 0:
            return 0
        # 블러 폭은 네이티브 픽셀 단위로 맞춘다. 같은 포즈·폭·불투명도만 공유한다.
        softness = round(softness_pixels / (scale * shadow.pixel_scale), 1)
        key = "shadow", pose, softness, opacity
        entry = self._lookup(key)
        if entry is None:
            if not resource.prepare_shadow(*pose, cache_geometry=True) or shadow.ground_bounds is None:
                return 0
            bounds, _ = shadow.ground_region(1, softness)
            entry = self._capture(key, bounds, lambda px, py: shadow.draw_ground(
                px, py, 1 / shadow.pixel_scale, opacity, softness_pixels=softness))
            if entry is None:
                return shadow.draw_ground_many(placements, scale, opacity, softness_pixels=softness_pixels)
        self._copy(entry, placements, scale)
        return len(placements)

    def close(self):
        for entry in self.entries.values():
            self.resource.pico.SDL_DestroyTexture(entry.texture)
        self.entries.clear()
        self.bytes = 0

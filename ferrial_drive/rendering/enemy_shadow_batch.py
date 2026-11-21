"""근거리 적의 지면 깊이 맵을 타일에 보관하고 그림자를 묶어 그린다."""

from collections import OrderedDict
import ctypes as ct
from math import ceil, floor
from struct import iter_unpack

from .enemy_part_batch import SheetLayout, SheetTarget
from .hud_batch import HudBatchQueue
from .instanced_quads import InstancedQuads, QUAD_LIMIT
from .part_shadow_map import GROUND_FRAGMENT, SHADOW_UNIFORMS
from .part_upscale import render_target


TILES_PER_SIDE = 8
SHADOW_TILE_LOOKUP = b"""
flat in int pairIndex;
uniform int tileSize, tilesPerSide;
vec4 lookupDepth(vec2 uv) {
    ivec2 texel=ivec2(clamp(floor(uv*float(tileSize)),vec2(0.0),vec2(float(tileSize-1))));
    ivec2 offset=ivec2(pairIndex%tilesPerSide,pairIndex/tilesPerSide)*tileSize;
    return texelFetch(lightDepth,offset+texel,0);
}
"""


class EnemyShadowBatch:
    def __init__(self, resource):
        self.resource = resource
        self.shadow = resource.shadow_map
        fragment = GROUND_FRAGMENT.replace(b"texture2D(lightDepth,", b"lookupDepth(")
        fragment = fragment.replace(b"float visibilityAtCoordinates(", SHADOW_TILE_LOOKUP + b"float visibilityAtCoordinates(")
        self.sampler = InstancedQuads(resource.pico, fragment_shader=fragment, tile_placements=True,
            extra_uniforms=(*SHADOW_UNIFORMS, "opacity", "perspectiveGround", "groundShadowRadius", "tileSize", "tilesPerSide"))
        self.tiles_per_side = min(TILES_PER_SIDE, self.sampler.max_texture_size // self.shadow.ground_size)
        self.texture = ct.c_uint()
        self.slots = OrderedDict()
        self.submits = 0
        try:
            self._allocate()
        except BaseException:
            self.close()
            raise

    def _allocate(self):
        shadow = self.shadow
        size = self.tiles_per_side * shadow.ground_size
        if size == 0:
            raise RuntimeError("적 그림자 깊이 타일을 생성할 수 없다.")
        s = self.sampler
        old = s.integer(0x8069)
        try:
            shadow.GenTextures(1, ct.byref(self.texture))
            s.glBindTexture(0x0DE1, self.texture.value)
            shadow.TexImage2D(0x0DE1, 0, 0x8CAC, size, size, 0, 0x1902, 0x1406, None)
            for param in (0x2800, 0x2801):
                shadow.TexParameteri(0x0DE1, param, 0x2600)
            draw_fbo = s.integer(0x8CA6)
            try:
                shadow.BindFramebuffer(0x8CA9, shadow.framebuffer.value)
                shadow.FramebufferTexture2D(0x8CA9, 0x8D00, 0x0DE1, self.texture.value, 0)
                if shadow.CheckFramebufferStatus(0x8CA9) != 0x8CD5:
                    raise RuntimeError("적 그림자 타일 프레임버퍼 생성 실패")
            finally:
                shadow.FramebufferTexture2D(0x8CA9, 0x8D00, 0x0DE1, shadow.texture.value, 0)
                shadow.BindFramebuffer(0x8CA9, draw_fbo)
        finally:
            s.glBindTexture(0x0DE1, old)

    def _slot(self, pose, pinned, pending):
        if pose in self.slots:
            self.slots.move_to_end(pose)
            return self.slots[pose]
        shadow = self.shadow
        clip_name, seconds = pose
        motion, pair = clip_name.rsplit("/", 1)
        direction = int(pair[3])
        clip = self.resource.get(motion, direction)["data"]["clip"]
        duration = clip["duration_seconds"]
        elapsed = seconds % duration if clip["loop"] else min(seconds, duration)
        key = motion, elapsed, (int(pair[1]) * 45, direction * 45)
        vertices, bounds = shadow.pose_geometry(key, True)
        slot = len(self.slots)
        if slot >= self.tiles_per_side ** 2:
            old = next(key for key in self.slots if key not in pinned)
            slot, _ = self.slots.pop(old)
        size = shadow.ground_size
        position = (slot % self.tiles_per_side * size, slot // self.tiles_per_side * size)
        pending.append((position, vertices))
        self.slots[pose] = slot, bounds
        return slot, bounds

    def draw(self, groups, scale, opacity, softness):
        shadow, sampler = self.shadow, self.sampler
        factor = scale * shadow.pixel_scale
        before = sampler.submits
        capacity = min(self.tiles_per_side ** 2, QUAD_LIMIT)
        count = 0
        self.resource.pico.SDL_RenderFlush(self.resource.pico.renderer)
        for start in range(0, len(groups), capacity):
            chunk = groups[start:start + capacity]
            pinned = {pose for pose, _ in chunk}
            tiles, pending = [], []
            try:
                for pose, positions in chunk:
                    slot, bounds = self._slot(pose, pinned, pending)
                    source, radius = shadow.ground_region(factor, softness, bounds)
                    tiles.append((source, slot, positions))
                    count += len(positions)
                # 방향 적재와 타일 배치를 끝낸 뒤 GL 패스에 들어간다.
                shadow.render_depth_tiles(self.texture, pending)
            except BaseException:
                self.slots.clear()
                raise
            with sampler.batch(), shadow.bind_texture(sampler, 0, self.texture):
                u = sampler.uniforms
                shadow.upload_projection(sampler)
                sampler.glUniform1i(u["lightDepth"], 0)
                sampler.glUniform1i(u["tileSize"], shadow.ground_size)
                sampler.glUniform1i(u["tilesPerSide"], self.tiles_per_side)
                sampler.glUniform1f(u["shadowOn"], 1)
                sampler.glUniform1f(u["shadowTexel"], 1 / shadow.ground_size)
                sampler.glUniform1f(u["opacity"], opacity)
                sampler.glUniform1f(u["perspectiveGround"], float(shadow.surface_light_position is not None))
                sampler.glUniform1f(u["groundShadowRadius"], radius)
                sampler.draw_tile_placements(tiles, shadow.pivot, factor)
        self.submits = sampler.submits - before
        shadow.ground_draws += count
        if shadow.surface_light_position is not None:
            shadow.projected_ground_draws += count
        return count

    def close(self):
        if self.texture.value:
            self.shadow.DeleteTextures(1, ct.byref(self.texture))
            self.texture.value = 0
        self.slots.clear()
        self.sampler.close()


class EnemyBoxMask:
    """근거리의 투영 Box를 반해상도 바닥 마스크에 한 번에 기록한다."""

    def __init__(self, pico):
        self.pico = pico
        self.target = SheetTarget(pico)
        self.batch = HudBatchQueue(pico)
        self.submits = 0

    @property
    def storage_bytes(self):
        width, height = self.target.size
        return width * height * 4

    def draw(self, groups_by_kind, sprites, zoom, opacity, window_size):
        self.submits = 0
        points, faces = [], []
        count = 0
        for kind, groups in groups_by_kind.items():
            sprite = sprites[kind]
            resource, shadow = sprite.resource, sprite.resource.shadow_map
            if not shadow.enabled:
                continue
            key_x, key_y, key_z = shadow.surface_light_position
            (gx, gy, _), (hx, hy, _) = shadow.ground_axes
            scale = zoom * sprite.scale * shadow.pixel_scale
            indices = tuple(box * 8 + corner for box in range(len(shadow.corners)) for corner in shadow.triangles)
            for (clip_name, seconds), placements in groups:
                motion, pair = clip_name.rsplit("/", 1)
                bank = pair[3]
                clip = resource.get(motion, bank)["data"]["clip"]
                duration = clip["duration_seconds"]
                elapsed = seconds % duration if clip["loop"] else min(seconds, duration)
                body, _ = shadow.pose_geometry((motion, elapsed, (int(pair[1]) * 45, int(bank) * 45)), True)
                projected = []
                for x, y, z in iter_unpack("=fff", body):
                    amount = key_z / max(1, key_z - z)
                    px, py = key_x + (x - key_x) * amount, key_y + (y - key_y) * amount
                    projected.append(((gx * px + gy * py) * scale, (hx * px + hy * py) * scale))
                for x, foot in placements:
                    start = len(points)
                    points.extend((x + px, foot + py) for px, py in projected)
                    faces.extend(start + index for index in indices)
                    count += 1
        if not points:
            return 0
        left = max(0, floor(min(x for x, _ in points)) - 2)
        top = max(0, floor(min(y for _, y in points)) - 2)
        right = min(window_size[0], ceil(max(x for x, _ in points)) + 2)
        bottom = min(window_size[1], ceil(max(y for _, y in points)) + 2)
        if left >= right or top >= bottom:
            return 0
        width, height = ceil((right - left) / 2), ceil((bottom - top) / 2)
        layout = SheetLayout()
        if layout.place(width, height) is None:
            raise RuntimeError("근거리 Box 그림자 마스크는 고정 시트 범위를 넘었다.")
        self.target.reserve(layout)
        p, texture = self.pico, self.target.texture
        black = (0, 0, 0, 255)
        vertices = [((x - left) * .5, (y - top) * .5, black) for x, y in points]
        with render_target(p, texture):
            p.SDL_SetRenderDrawColor(p.renderer, 0, 0, 0, 0)
            p.SDL_RenderClear(p.renderer)
            with self.batch.frame():
                self.batch.colored_mesh(vertices, faces)
        self.submits = self.batch.stats["geometry_submits"]
        source = p.SDL_Rect(0, 0, width, height)
        destination = p.SDL_Rect(left, top, width * 2, height * 2)
        if (p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear)
                or p.SDL_SetTextureAlphaMod(texture, round(max(0, min(1, opacity)) * 255))
                or p.SDL_RenderCopy(p.renderer, texture, source, destination)):
            raise RuntimeError("근거리 Box 그림자 화면 합성 실패")
        return count

    def close(self):
        self.batch.close()
        self.target.close()

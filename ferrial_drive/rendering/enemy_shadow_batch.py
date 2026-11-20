"""근거리 적의 원본 정밀도 깊이 맵을 타일에 보관하고 지면 그림자를 묶어 그린다."""

from collections import OrderedDict
import ctypes as ct

from .instanced_quads import InstancedQuads
from .part_shadow_map import GROUND_FRAGMENT, SHADOW_UNIFORMS


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
        self.sampler = InstancedQuads(resource.pico, fragment_shader=fragment, per_instance_source=True,
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

    def _slot(self, pose, pinned):
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
        try:
            shadow.render_depth(vertices, texture=self.texture,
                                tile=(slot % self.tiles_per_side * size, slot // self.tiles_per_side * size))
        except BaseException:
            self.slots.clear()
            raise
        self.slots[pose] = slot, bounds
        return slot, bounds

    def draw(self, groups, scale, opacity, softness):
        shadow, sampler = self.shadow, self.sampler
        factor = scale * shadow.pixel_scale
        px, py = shadow.pivot
        before = sampler.submits
        capacity = self.tiles_per_side ** 2
        count = 0
        self.resource.pico.SDL_RenderFlush(self.resource.pico.renderer)
        for start in range(0, len(groups), capacity):
            chunk = groups[start:start + capacity]
            pinned = {pose for pose, _ in chunk}
            instances, sources = [], []
            for pose, positions in chunk:
                slot, bounds = self._slot(pose, pinned)
                source, radius = shadow.ground_region(factor, softness, bounds)
                left, top, w, h = source
                dx, dy = (left - px) * factor, (top - py) * factor
                width, height = max(1, w * factor), max(1, h * factor)
                for x, y in positions:
                    instances.append(((x + dx, y + dy, width, height), 0, slot))
                    sources.append(source)
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
                sampler.draw_instances((0, 0, 1, 1), instances, sources=sources)
            count += len(instances)
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

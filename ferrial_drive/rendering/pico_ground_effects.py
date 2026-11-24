"""회색 마찰/파편 cutout·연기 알파·에너지 Trail의 Pico2D OpenGL 표현."""

import json
from ctypes import byref
from contextlib import nullcontext
from functools import lru_cache
from math import cos, sin
from pathlib import Path

from .gl_pass import TexturedQuadPass
from .ground_effect_batch import GroundEffectBatch


from .ground_effect_shaders import VERTEX_SHADER, FRAGMENT_SHADER


@lru_cache(maxsize=64)
def _particle_rgb(color):
    return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))


class PicoGroundEffects:
    def __init__(self, pico, atlas_path, *, backend="batched"):
        if backend not in ("individual", "batched"):
            raise ValueError("지면 효과 백엔드는 individual 또는 batched다.")
        self.pico = pico
        self.textures = {}
        self.sampler = None
        self.batch_sampler = None
        self.batch_texture = None
        self.atlas_offsets = {}
        self.backend = backend
        self.stats = {}
        path = Path(atlas_path)
        self.atlas_directory = path.parent
        self.atlas = json.loads(path.read_text(encoding="utf-8"))["assets"]
        try:
            self.sampler = TexturedQuadPass(pico, vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER,
                extra_uniforms=("quadCenter", "rotation", "mirrorX", "ink", "fade", "cutoff", "detail", "roundness", "mode",
                                "depthMode", "emitterOrigin", "nearRadius", "headFeather"))
            self.batch_sampler = GroundEffectBatch(pico)
            self._load_batch_atlas()
            if backend == "individual":
                self._load_individual_textures()
        except BaseException:
            self.close()
            raise

    def _load_individual_textures(self):
        pico = self.pico
        for name, row in self.atlas.items():
            if name not in self.textures:
                texture = pico.IMG_LoadTexture(pico.renderer, str(self.atlas_directory / row["file"]).encode("utf-8"))
                if not texture:
                    raise OSError("마찰 입자 텍스처 로딩 실패: " + name)
                self.textures[name] = texture
                pico.SDL_SetTextureBlendMode(texture, pico.SDL_BLENDMODE_BLEND)

    def _load_batch_atlas(self):
        """원본 시트는 보존하고 로딩 중에만 공통 RGBA 시트를 조립한다."""
        pico = self.pico
        limit = self.batch_sampler.max_rows
        x = y = column_width = width = height = 0
        for name, row in self.atlas.items():
            w, h = row["size_px"]
            if min(w, h) <= 0 or max(w, h) > limit:
                raise ValueError("지면 효과 시트 크기가 GL 텍스처 상한을 넘었다.")
            if y + h > limit:
                x += column_width
                y = column_width = 0
            self.atlas_offsets[name] = x, y
            width, height = max(width, x + w), max(height, y + h)
            column_width = max(column_width, w)
            y += h
        if width > limit or not self.atlas:
            raise ValueError("지면 효과 공통 아틀라스를 구성할 수 없다.")
        packed = pico.SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, pico.SDL_PIXELFORMAT_RGBA32)
        if not packed:
            raise MemoryError("지면 효과 공통 아틀라스 표면 생성 실패")
        try:
            pico.SDL_FillRect(packed, None, 0)
            for name, row in self.atlas.items():
                source = pico.IMG_Load(str(self.atlas_directory / row["file"]).encode("utf-8"))
                if not source:
                    raise OSError("지면 효과 시트 로딩 실패: " + name)
                try:
                    if (source.contents.w, source.contents.h) != tuple(row["size_px"]):
                        raise ValueError("지면 효과 시트와 명세의 크기가 다르다: " + name)
                    pico.SDL_SetSurfaceBlendMode(source, pico.SDL_BLENDMODE_NONE)
                    rect = pico.SDL_Rect(*self.atlas_offsets[name], *row["size_px"])
                    if pico.SDL_UpperBlit(source, None, packed, byref(rect)) != 0:
                        raise RuntimeError("지면 효과 공통 아틀라스 복사 실패")
                finally:
                    pico.SDL_FreeSurface(source)
            self.batch_texture = pico.SDL_CreateTextureFromSurface(pico.renderer, packed)
            if not self.batch_texture:
                raise MemoryError("지면 효과 공통 아틀라스 업로드 실패")
            pico.SDL_SetTextureBlendMode(self.batch_texture, pico.SDL_BLENDMODE_BLEND)
            self.batch_size = width, height
        finally:
            pico.SDL_FreeSurface(packed)

    def draw(self, effects, camera, *, foreground=False, trail_in_front=False):
        sampler, pico = self.sampler, self.pico
        batched = self.backend == "batched"
        self.stats = dict(particles=0, submits=0, upload_bytes=0, buffer_allocations=0)
        if batched:
            self.batch_sampler.begin()
        elif len(self.textures) != len(self.atlas):
            self._load_individual_textures()
        if not effects.particles:
            return
        with nullcontext() if batched else sampler.batch():
            for particle in effects.particles:
                spatial_split = effects.reverse_motion and particle.kind in ("trail", "thruster_smoke", "energy_orb")
                in_front = (particle.kind == "foot_friction" or
                            particle.kind in ("trail", "thruster_smoke", "energy_orb") and trail_in_front)
                if not spatial_split and in_front != foreground:
                    continue
                name = "smoke_gray" if particle.kind == "thruster_smoke" else particle.kind
                name = name if name in self.atlas else "scrape_gray"
                row = self.atlas[name]
                variant = row["variants"][particle.variant]
                x, y, width, height = variant.get("render_rect_top_left_px", variant["source_rect_top_left_px"])
                original_width, original_height = width, height
                if particle.kind == "foot_friction":
                    padding = min(round(min(width, height) * 0.08), x, y,
                                  row["size_px"][0] - x - width, row["size_px"][1] - y - height)
                    x, y = x - padding, y - padding
                    width, height = width + padding * 2, height + padding * 2
                age = particle.age_seconds
                progress = age / particle.lifetime_seconds
                px, py = particle.position
                vx, vy = particle.velocity
                point = (px + vx * age, py + vy * age + 0.5 * particle.gravity * age * age)
                cx, cy = camera.world_to_screen(point)
                growth = 1 + progress * particle.growth
                zoom = camera.zoom
                w, h = particle.size
                w, h = w * growth * zoom, h * growth * zoom
                if particle.kind == "foot_friction":
                    w, h = w * width / original_width, h * height / original_height
                if particle.kind in ("trail", "trail_echo"):
                    shift = (particle.size[0] * zoom - w) / 2
                    cx += cos(particle.angle) * shift
                    cy += sin(particle.angle) * shift
                origin = effects.emitter_origins.get(particle.emitter, particle.position)
                ox, oy = camera.world_to_screen(origin)
                if spatial_split:
                    distance = ((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5
                    radius = (w * w + h * h) ** 0.5 / 2
                    if foreground and distance - radius >= effects.near_front_pixels * zoom:
                        continue
                    if not foreground and distance + radius < effects.near_front_pixels * zoom:
                        continue
                destination_values = (round(cx - w / 2), round(cy - h / 2), max(1, round(w)), max(1, round(h)))
                red, green, blue = _particle_rgb(particle.color)
                brightness = particle.brightness
                color = red * brightness, green * brightness, blue * brightness
                fade = max(0, 1 if particle.kind in ("trail", "trail_echo") else 1 - progress)
                depth_mode = (2 if foreground else 1) if spatial_split else 0
                head_feather = 0.14 if particle.emitter.startswith("back") else 0.04
                mode = (4 if particle.kind in ("trail", "trail_echo") else
                        3 if particle.kind == "energy_orb" else
                        2 if particle.kind == "spark" else int(particle.kind in ("smoke_gray", "thruster_smoke", "foot_friction")))
                if batched:
                    ax, ay = self.atlas_offsets[name]
                    self.batch_sampler.append(self.batch_texture, self.batch_size, (
                        *destination_values, x + ax, y + ay, x + ax + width, y + ay + height,
                        cx, cy, cos(particle.angle), sin(particle.angle),
                        -1 if particle.mirror_x else 1, ox, oy, effects.near_front_pixels * zoom,
                        *color, particle.opacity, fade, particle.alpha_cutoff, particle.detail, particle.roundness,
                        mode, depth_mode, head_feather, 0))
                    continue
                source = pico.SDL_Rect(x, y, width, height)
                destination = pico.SDL_Rect(*destination_values)
                sampler.glUniform2f(sampler.uniforms["quadCenter"], cx, cy)
                sampler.glUniform2f(sampler.uniforms["rotation"], cos(particle.angle), sin(particle.angle))
                sampler.glUniform1f(sampler.uniforms["mirrorX"], -1 if particle.mirror_x else 1)
                sampler.glUniform4f(sampler.uniforms["ink"], *color, particle.opacity)
                sampler.glUniform1f(sampler.uniforms["fade"], fade)
                sampler.glUniform1f(sampler.uniforms["cutoff"], particle.alpha_cutoff)
                sampler.glUniform1f(sampler.uniforms["detail"], particle.detail)
                sampler.glUniform1f(sampler.uniforms["roundness"], particle.roundness)
                sampler.glUniform1i(sampler.uniforms["depthMode"], depth_mode)
                sampler.glUniform2f(sampler.uniforms["emitterOrigin"], ox, oy)
                sampler.glUniform1f(sampler.uniforms["nearRadius"], effects.near_front_pixels * zoom)
                sampler.glUniform1f(sampler.uniforms["headFeather"], head_feather)
                sampler.glUniform1i(sampler.uniforms["mode"], mode)
                sampler.draw(self.textures[name], row["size_px"], source, destination)
                self.stats["particles"] += 1
                self.stats["submits"] += 1
        if batched:
            self.batch_sampler.render()
            self.stats = dict(self.batch_sampler.stats)

    def close(self):
        if self.batch_texture:
            self.pico.SDL_DestroyTexture(self.batch_texture)
            self.batch_texture = None
        if self.batch_sampler is not None:
            self.batch_sampler.close()
            self.batch_sampler = None
        for texture in self.textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.textures.clear()
        if self.sampler is not None:
            self.sampler.close()
            self.sampler = None

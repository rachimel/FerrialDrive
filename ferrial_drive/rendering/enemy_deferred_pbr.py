"""근거리 적의 표면 시트 기록과 공통 조명을 비교하는 렌더 경로."""

from contextlib import contextmanager, nullcontext
import ctypes as ct
from dataclasses import dataclass, field

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from .atlas_texture_cache import bind_atlas_textures
from .enemy_part_batch import EnemyPartBatch, EnemyUpscaleScratch, SheetLayout, SheetTarget, UPSCALE_GUTTER
from .gl_pass import TexturedQuadPass
from .instance_texture_buffer import InstanceTextureBuffer
from .keypose_sample_buffer import KeyposeSampleBuffer
from .part_motion_atlas import frame_phase, frame_state
from .part_painter import PartPainter
from .part_pbr import PBR_FUNCTIONS, PBR_UNIFORMS
from .part_upscale import PART_UPSCALE_BORDER, render_target


ATTACHMENT_FORMATS = (0x881A, 0x881A, 0x8058, 0x881A)  # RGBA16F, RGBA16F, RGBA8, RGBA16F
SURFACE_BYTES_PER_PIXEL = 28
MAX_PROFILES = 3
DEPTH_RANK_SCALE = 65536
NO_SCREEN_PLACEMENT = (0, 0, 0, 0)
LIGHT_FRAGMENT = b"""#version 120
#define COAT
uniform sampler2D albedo, normalEnergy, materialCoat, positionCoat;
uniform vec2 atlasSize;
uniform vec4 viewDirections[3], emissionColors[3];
varying vec2 texel;
""" + PBR_FUNCTIONS + b"""
void main() {
    vec2 uv=texel/atlasSize;
    vec4 base=texture2D(albedo,uv);
    if(base.a<=0.000001) {
        gl_FragColor=vec4(0.0);
        return;
    }
    vec4 point=texture2D(positionCoat,uv);
    vec3 rgb=base.rgb;
    if(point.w>=2.0) {
        int profile=int(floor(point.w/2.0))-1;
        vec4 field=texture2D(normalEnergy,uv), material=texture2D(materialCoat,uv);
        rgb=shadePbr(srgbToLinear(base.rgb),normalize(field.rgb),point.xyz,material.rgb,
                     vec2(material.a,mod(point.w,2.0)),1.0,viewDirections[profile].xyz);
        rgb=mix(rgb,emissionColors[profile].xyz,field.a);
    }
    gl_FragColor=vec4(rgb*base.a,base.a);
}
"""


class SurfaceTargets:
    """SDL 타깃 크기와 동일한 MRT를 사용하고 드로우 FBO 상태를 복원한다."""

    def __init__(self, pico):
        self.size = (0, 0)
        count = len(ATTACHMENT_FORMATS)
        self.textures = (ct.c_uint * count)()
        self.attachments = (ct.c_uint * count)(*(0x8CE0 + i for i in range(count)))
        self.fbo = ct.c_uint()
        self.zero = (ct.c_float * 4)()
        u, i, p = ct.c_uint, ct.c_int, ct.c_void_p
        for name, result, args in (
            ("glGenTextures", None, [i, p]), ("glDeleteTextures", None, [i, p]),
            ("glTexStorage2D", None, [u, i, u, i, i]), ("glTexParameteri", None, [u, u, i]),
            ("glGenFramebuffers", None, [i, p]), ("glDeleteFramebuffers", None, [i, p]),
            ("glBindFramebuffer", None, [u, u]), ("glFramebufferTexture2D", None, [u, u, u, u, i]),
            ("glDrawBuffers", None, [i, p]), ("glCheckFramebufferStatus", u, [u]),
            ("glClearBufferfv", None, [u, i, p]),
        ):
            setattr(self, name, bind_gl(pico, name, result, args))

    @property
    def storage_bytes(self):
        return self.size[0] * self.size[1] * SURFACE_BYTES_PER_PIXEL

    def reserve(self, sampler, size):
        if size == self.size:
            return
        self.close()
        previous_texture = sampler.integer(0x8069)
        previous_fbo = sampler.integer(0x8CA6)
        try:
            self.glGenTextures(len(self.textures), self.textures)
            self.glGenFramebuffers(1, ct.byref(self.fbo))
            self.glBindFramebuffer(0x8CA9, self.fbo.value)
            for texture, attachment, format_name in zip(self.textures, self.attachments, ATTACHMENT_FORMATS):
                sampler.glBindTexture(0x0DE1, texture)
                self.glTexStorage2D(0x0DE1, 1, format_name, *size)
                for parameter in (0x2800, 0x2801):
                    self.glTexParameteri(0x0DE1, parameter, 0x2600)
                self.glFramebufferTexture2D(0x8CA9, attachment, 0x0DE1, texture, 0)
            self.glDrawBuffers(len(self.attachments), self.attachments)
            if self.glCheckFramebufferStatus(0x8CA9) != 0x8CD5:
                raise RuntimeError("Deferred 표면 시트 프레임버퍼 생성 실패")
            self.size = size
        except BaseException:
            self.close()
            raise
        finally:
            sampler.glBindTexture(0x0DE1, previous_texture)
            self.glBindFramebuffer(0x8CA9, previous_fbo)

    @contextmanager
    def bind(self, sampler, *, clear=False):
        previous = sampler.integer(0x8CA6)
        try:
            self.glBindFramebuffer(0x8CA9, self.fbo.value)
            sampler.glDisable(0x0BE2)
            if clear:
                sampler.glDisable(0x0C11)
                for index in (0, 3):
                    self.glClearBufferfv(0x1800, index, self.zero)
            yield
        finally:
            sampler.glEnable(0x0BE2)
            self.glBindFramebuffer(0x8CA9, previous)

    def close(self):
        if self.fbo.value:
            self.glDeleteFramebuffers(1, ct.byref(self.fbo))
            self.fbo.value = 0
        if any(self.textures):
            self.glDeleteTextures(len(self.textures), self.textures)
            self.textures[:] = (0,) * len(self.textures)
        self.size = (0, 0)


@dataclass
class DeferredGroup:
    bank_data: dict
    clip: dict
    state: dict
    instances: list = field(default_factory=list)
    samples: dict = field(default_factory=dict)
    ids: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    coverage_instances: list = field(default_factory=list)
    coverage_placements: list = field(default_factory=list)
    coverage_tiles: list = field(default_factory=list)
    material_placements: list = field(default_factory=list)
    instance_range: tuple = (0, 0)
    sample_cached_tiles: int = 0


class EnemyDeferredPbr:
    def __init__(self, pico, *, screen_depth=False, batch_upload=True, cache_keypose_samples=False):
        if cache_keypose_samples and not (screen_depth and batch_upload):
            raise ValueError("키포즈 좌표 재사용에는 깊이 선행 패스와 공유 인스턴스 버퍼가 필요하다.")
        self.pico = pico
        self.parts = {}
        self.coverage = {}
        self.depth = None
        if screen_depth:
            from .enemy_screen_depth import EnemyScreenDepth
            self.depth = EnemyScreenDepth(pico)
        self.instance_buffer = InstanceTextureBuffer(pico) if screen_depth and batch_upload else None
        self.keypose_buffer = KeyposeSampleBuffer(pico) if cache_keypose_samples else None
        self.scratch = EnemyUpscaleScratch(pico)
        self.output = SheetTarget(pico)
        self.surfaces = SurfaceTargets(pico)
        self.lighting = TexturedQuadPass(pico, fragment_shader=LIGHT_FRAGMENT,
            extra_uniforms=(*PBR_UNIFORMS, "albedo", "normalEnergy", "materialCoat", "positionCoat",
                            "viewDirections[0]", "emissionColors[0]"))
        self.upload_array = bind_gl(pico, "glUniform4fv", None, [ct.c_int, ct.c_int, ct.c_void_p])
        self.surface_submits = self.light_submits = 0
        self.depth_submits = self.depth_bodies = self.depth_tested_tiles = 0
        self.instance_uploads = self.instance_upload_bytes = 0
        self.keypose_samples = self.keypose_cached_tiles = 0

    @property
    def storage_bytes(self):
        upscaler = self.scratch.upscaler
        sheet_bytes = sum(target.size[0] * target.size[1] * 4 for target in (self.output, self.scratch.native))
        return (self.surfaces.storage_bytes + sheet_bytes + sum(batch.table_bytes for batch in self.parts.values())
                + (upscaler.aa.storage_bytes if upscaler is not None else 0)
                + (self.depth.storage_bytes if self.depth is not None else 0)
                + (self.instance_buffer.storage_bytes if self.instance_buffer is not None else 0)
                + (self.keypose_buffer.storage_bytes if self.keypose_buffer is not None else 0))

    def _make_painter(self, resource, *, coverage=False):
        formats = {name: getattr(resource, name) for name in ("hermite_flow", "compact_depth")
                   if hasattr(resource, name)}
        return PartPainter(self.pico, part_count=resource.catalog.part_count, frame_crop=resource.catalog.frame_crop,
            surface=True, pbr=True, deferred=not coverage, depth_coverage=coverage,
            screen_depth=self.depth is not None and not coverage,
            instance_table=self.instance_buffer is not None,
            cache_keypose_samples=self.keypose_buffer is not None,
            coat=resource.catalog.coat_members is not None, instanced=True, **formats)

    def _batch(self, resource):
        if resource not in self.parts:
            batch = EnemyPartBatch(resource, scratch=self.scratch)
            batch.painter = self._make_painter(resource)
            self.parts[resource] = batch
        return self.parts[resource]

    def _upload_instances(self, jobs, *, cache_samples):
        values = []
        for _, resource, groups in jobs:
            for group in groups.values():
                start = len(values) // 12
                coverage, duplicates = {}, []
                for tile, (rect, phase, first), placement in zip(
                        group.coverage_tiles, group.coverage_instances, group.coverage_placements, strict=True):
                    if tile in coverage:
                        duplicates.append((rect, phase, first, placement[2]))
                    else:
                        coverage[tile] = rect, placement[2]
                for tile, ((sheet, phase, first), material) in enumerate(
                        zip(group.instances, group.material_placements, strict=True)):
                    screen, z = coverage.get(tile, (NO_SCREEN_PLACEMENT, 0))
                    placement = int(material[2] > 0)
                    if cache_samples and placement and 0 < ct.c_float(phase).value < 1:
                        count = sheet[2] * sheet[3] * resource.catalog.part_count
                        if self.keypose_samples + count <= self.keypose_buffer.sample_limit:
                            # 0은 깊이 검사 생략, 1은 직접 보간, 2 이상은 좌표 시작 인덱스다.
                            placement = self.keypose_samples + 2
                            self.keypose_samples += count
                            group.sample_cached_tiles += 1
                    values.extend((*screen, *sheet, phase, first, z, placement))
                # 같은 포즈의 다른 화면 위치는 깊이만 기록하고 시트 슬롯을 공유한다.
                for screen, phase, first, z in duplicates:
                    values.extend((*screen, *NO_SCREEN_PLACEMENT, phase, first, z, 0))
                group.instance_range = start, len(values) // 12 - start
        self.instance_buffer.upload(self.lighting, values)
        self.instance_uploads = 1
        self.instance_upload_bytes = self.instance_buffer.storage_bytes

    @staticmethod
    def _depth_region(jobs, viewport):
        rectangles = [rect for _, _, groups in jobs for group in groups.values()
                      for rect, _, _ in group.coverage_instances]
        if len(rectangles) < 2:
            return None
        left = max(0, min(rect[0] for rect in rectangles))
        top = max(0, min(rect[1] for rect in rectangles))
        right = min(viewport.w, max(x + w for x, _, w, _ in rectangles))
        bottom = min(viewport.h, max(y + h for _, y, _, h in rectangles))
        if right <= left or bottom <= top:
            return None
        return (left, top), (right - left, bottom - top)

    def _write_depth(self, jobs, region):
        (left, top), size = region
        clear = True
        for _, resource, groups in jobs:
            if not any(group.coverage_instances for group in groups.values()):
                continue
            if resource not in self.coverage:
                self.coverage[resource] = self._make_painter(resource, coverage=True)
            painter = self.coverage[resource]
            batch, sampler = self._batch(resource), painter.sampler
            before = sampler.submits, sampler.instance_uploads, sampler.instance_upload_bytes
            with sampler.batch(), self.depth.bind(sampler, size, clear=clear):
                clear = False
                for key, group in groups.items():
                    if not group.coverage_instances:
                        continue
                    table = batch._table(key, group.bank_data, group.samples)
                    if table is not None:
                        if self.instance_buffer is None:
                            instances = [((x - left, y - top, w, h), phase, first)
                                         for (x, y, w, h), phase, first in group.coverage_instances]
                            painter.paint(resource.cache, (group.bank_data,), group.state, None, instances=instances,
                                          pose_table=table, screen_placements=group.coverage_placements)
                        else:
                            painter.paint(resource.cache, (group.bank_data,), group.state, None, pose_table=table,
                                          instance_texture=self.instance_buffer.texture.value,
                                          instance_range=group.instance_range, depth_origin=(left, top))
                        self.depth_bodies += len(group.coverage_instances)
            self.depth_submits += sampler.submits - before[0]
            self.instance_uploads += sampler.instance_uploads - before[1]
            self.instance_upload_bytes += sampler.instance_upload_bytes - before[2]
        return self.depth.texture.value if self.depth_submits else None

    def _resolve(self, resources, layout, target):
        sampler = self.lighting
        resource = resources[0]
        uniforms, lighting = sampler.uniforms, resource.pbr_lighting
        p = self.pico
        rect = p.SDL_Rect(0, 0, layout.width, layout.height)
        entries = [{"gl_texture": texture} for texture in self.surfaces.textures] + [lighting["entry"]]
        with sampler.batch(), bind_atlas_textures(sampler, resource.cache, entries):
            sampler.glDisable(0x0BE2)
            for unit, name in enumerate(("albedo", "normalEnergy", "materialCoat", "positionCoat", "pbrEnvironment")):
                sampler.glUniform1i(uniforms[name], unit)
            for name, field in (("pbrEnvironmentSize", "environment_size"), ("pbrKeyPosition", "key_position"),
                                ("pbrKeyColor", "key_color"), ("pbrKeyDirection", "key_direction")):
                sampler.glUniform4f(uniforms[name], *lighting[field])
            sampler.glUniform1f(uniforms["pbrExposure"], lighting["exposure"])
            view_vectors = [(-x, -y, -z, 0) for x, y, z in (r.shadow_map.forward for r in resources)]
            emission = [(*(r.energy_color if r.energy_color and r.energy_mask_gain > 0 else (.08, .72, .94)), 0)
                        for r in resources]
            for name, rows in (("viewDirections[0]", view_vectors), ("emissionColors[0]", emission)):
                self.upload_array(uniforms[name], len(rows), (ct.c_float * (4 * len(rows)))(*(v for row in rows for v in row)))
            sampler.draw(None, target.size, rect, rect)
        self.light_submits = 1

    def prepare(self, body_requests, sprites, zoom, *, body_depth_ranks=None):
        self.surface_submits = self.light_submits = 0
        self.depth_submits = self.depth_bodies = self.depth_tested_tiles = 0
        self.instance_uploads = self.instance_upload_bytes = 0
        self.keypose_samples = self.keypose_cached_tiles = 0
        for resource in self.parts.keys() - {sprite.resource for sprite in sprites.values()}:
            self.parts.pop(resource).close()
            if resource in self.coverage:
                self.coverage.pop(resource).close()
        p = self.pico
        sx, sy = ct.c_float(), ct.c_float()
        p.SDL_RenderGetScale(p.renderer, ct.byref(sx), ct.byref(sy))
        if (sx.value, sy.value) != (1, 1) or len(body_requests) > MAX_PROFILES:
            return {}
        viewport = p.SDL_Rect()
        if body_depth_ranks:
            p.SDL_RenderGetViewport(p.renderer, ct.byref(viewport))
        use_depth = (self.depth is not None and body_depth_ranks and not (viewport.x or viewport.y)
                     and not p.SDL_RenderIsClipEnabled(p.renderer)
                     and max(body_depth_ranks.values()) < DEPTH_RANK_SCALE)
        native_layout, output_layout = SheetLayout(), SheetLayout(UPSCALE_GUTTER)
        resources, jobs, copies = [], [], {}
        for kind, requests in body_requests.items():
            r = sprites[kind].resource
            if r.paged or not r.pbr_lighting or r.shadow_map is None or r.rim_light[3] or r.realtime_light:
                continue
            factor = zoom * sprites[kind].scale * r.data["pixel_scale"]
            upscale = factor > 1 and r.upscaler is not None and r.data.get("upscale_filter") == "bounded_bicubic"
            if upscale and r.upscaler.aa_mode != "smaa":
                continue
            if upscale and self.scratch.get_upscaler() is None:
                continue
            border = PART_UPSCALE_BORDER if upscale else 0
            pad = round(border * factor)
            pivot_x, pivot_y = r.data["pivot_top_left"]
            profile = len(resources)
            resources.append(r)
            groups, poses = {}, {}
            for enemy_id, motion, bank, seconds, x, foot in requests:
                key = motion, bank
                if key not in groups:
                    bank_data = r.get(*key)
                    clip = bank_data["data"]["clip"]
                    groups[key] = DeferredGroup(bank_data, clip, frame_state(clip, clip, seconds))
                group = groups[key]
                first, phase = frame_phase(group.clip, seconds)
                left, top, width, height = group.state["bounds"]
                draw_w, draw_h = max(1, round(width * factor)), max(1, round(height * factor))
                destination = p.SDL_Rect(round(x - (pivot_x - left) * factor) - pad,
                    round(foot - (pivot_y - top) * factor) - pad, draw_w + 2 * pad, draw_h + 2 * pad)
                # 확대 필터의 이웃 픽셀은 기존 시트에서 함께 처리한다.
                z = body_depth_ranks.get(enemy_id, 0) / DEPTH_RANK_SCALE if use_depth and not upscale else 0
                pose = (*key, first, phase)
                if pose not in poses:
                    slot = native_layout.place(width + 2 * border, height + 2 * border) if upscale else native_layout.place(draw_w, draw_h)
                    if slot is None:
                        continue
                    paint_slot = slot
                    source = output_layout.place(destination.w, destination.h) if upscale else slot
                    if source is None:
                        continue
                    if upscale:
                        paint_slot = slot[0] + border, slot[1] + border, width, height
                        group.regions.append((slot, source))
                    poses[pose] = (self.output if upscale else self.scratch.native, p.SDL_Rect(*source), len(group.instances))
                    group.instances.append((paint_slot, phase, first))
                    group.samples[first] = seconds
                    if self.depth is not None:
                        group.material_placements.append((destination.x - slot[0], destination.y - slot[1], z, 0)
                                                         if z else NO_SCREEN_PLACEMENT)
                elif self.depth is not None:
                    # 공유 포즈는 모든 배치에서 같은 시트 픽셀을 읽는다.
                    group.material_placements[poses[pose][2]] = NO_SCREEN_PLACEMENT
                if z:
                    group.coverage_instances.append(((destination.x, destination.y, destination.w, destination.h), phase, first))
                    group.coverage_placements.append((0, 0, z, 0))
                    group.coverage_tiles.append(poses[pose][2])
                target, rect, _ = poses[pose]
                copies[enemy_id] = target, rect, destination
                group.ids.append(enemy_id)
            jobs.append((profile, r, groups))
        if not copies:
            return {}
        depth_region = self._depth_region(jobs, viewport) if use_depth else None
        if self.instance_buffer is not None:
            self._upload_instances(jobs, cache_samples=self.keypose_buffer is not None and depth_region is not None)
        depth_texture = None
        depth_left, depth_top = (0, 0)
        if depth_region is not None:
            depth_left, depth_top = depth_region[0]
            keyposes = self.keypose_buffer.bind(self.lighting, self.keypose_samples) if self.keypose_buffer else nullcontext()
            with keyposes:
                depth_texture = self._write_depth(jobs, depth_region)
                if self.keypose_samples:
                    self.keypose_buffer.sync()
        target = self.scratch.native
        target.reserve(native_layout)
        self.surfaces.reserve(self.lighting, target.size)
        regions, clear = [], True
        keyposes = self.keypose_buffer.bind(self.lighting, self.keypose_samples) if self.keypose_buffer else nullcontext()
        with render_target(p, target.texture), keyposes:
            for profile, r, groups in jobs:
                batch = self._batch(r)
                painter, sampler = batch.painter, batch.painter.sampler
                before = sampler.submits, sampler.instance_uploads, sampler.instance_upload_bytes
                with sampler.batch(), self.surfaces.bind(sampler, clear=clear):
                    clear = False
                    sampler.glUniform1f(sampler.uniforms["deferredProfile"], profile)
                    for key, group in groups.items():
                        if not group.instances:
                            continue
                        table = batch._table(key, group.bank_data, group.samples)
                        if table is None:
                            for enemy_id in group.ids:
                                copies.pop(enemy_id, None)
                            continue
                        instance_options = {}
                        if self.instance_buffer is not None:
                            instance_options.update(instance_texture=self.instance_buffer.texture.value,
                                                    instance_range=group.instance_range, depth_origin=(depth_left, depth_top))
                        else:
                            placements = None
                            if depth_texture is not None:
                                placements = [(x - depth_left, y - depth_top, z, 0)
                                              for x, y, z, _ in group.material_placements]
                            instance_options.update(instances=group.instances, screen_placements=placements)
                        painter.paint(r.cache, (group.bank_data,), group.state, None, energy_color=r.energy_color,
                            energy_gain=r.energy_mask_gain, shadow_map=r.shadow_map, pbr_lighting=r.pbr_lighting,
                            sample_shadow=False, pose_table=table, screen_depth=depth_texture, **instance_options)
                        if depth_texture is not None:
                            self.depth_tested_tiles += sum(placement[2] > 0 for placement in group.material_placements)
                            self.keypose_cached_tiles += group.sample_cached_tiles
                        regions.extend(group.regions)
                self.surface_submits += sampler.submits - before[0]
                self.instance_uploads += sampler.instance_uploads - before[1]
                self.instance_upload_bytes += sampler.instance_upload_bytes - before[2]
            if self.keypose_samples:
                self.keypose_buffer.sync()
            self._resolve(resources, native_layout, target)
        if regions:
            self.output.reserve(output_layout)
            self.scratch.get_upscaler().draw(target.texture, target.size, self.output.texture, self.output.size, regions)
        return copies

    def copy(self, record):
        target, source, destination = record
        if self.pico.SDL_RenderCopy(self.pico.renderer, target.texture, source, destination):
            raise RuntimeError("Deferred 적 본체 복사 실패")
        return destination.y

    def close(self):
        for batch in self.parts.values():
            batch.close()
        self.parts.clear()
        for painter in self.coverage.values():
            painter.close()
        self.coverage.clear()
        if self.depth is not None:
            self.depth.close()
        if self.instance_buffer is not None:
            self.instance_buffer.close()
        if self.keypose_buffer is not None:
            self.keypose_buffer.close()
        self.lighting.close()
        self.surfaces.close()
        self.output.close()
        self.scratch.close()

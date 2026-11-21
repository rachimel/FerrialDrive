"""근거리 적의 표면 시트 기록과 공통 조명을 비교하는 렌더 경로."""

from contextlib import contextmanager
import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from .atlas_texture_cache import bind_atlas_textures
from .enemy_part_batch import EnemyPartBatch, EnemyUpscaleScratch, SheetLayout, SheetTarget, UPSCALE_GUTTER
from .gl_pass import TexturedQuadPass
from .part_motion_atlas import frame_phase, frame_state
from .part_painter import PartPainter
from .part_pbr import PBR_FUNCTIONS, PBR_UNIFORMS
from .part_upscale import PART_UPSCALE_BORDER, render_target


ATTACHMENT_FORMATS = (0x881A, 0x881A, 0x8058, 0x881A)  # RGBA16F, RGBA16F, RGBA8, RGBA16F
SURFACE_BYTES_PER_PIXEL = 28
MAX_PROFILES = 3
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


class EnemyDeferredPbr:
    def __init__(self, pico):
        self.pico = pico
        self.parts = {}
        self.scratch = EnemyUpscaleScratch(pico)
        self.output = SheetTarget(pico)
        self.surfaces = SurfaceTargets(pico)
        self.lighting = TexturedQuadPass(pico, fragment_shader=LIGHT_FRAGMENT,
            extra_uniforms=(*PBR_UNIFORMS, "albedo", "normalEnergy", "materialCoat", "positionCoat",
                            "viewDirections[0]", "emissionColors[0]"))
        self.upload_array = bind_gl(pico, "glUniform4fv", None, [ct.c_int, ct.c_int, ct.c_void_p])
        self.surface_submits = self.light_submits = 0

    @property
    def storage_bytes(self):
        upscaler = self.scratch.upscaler
        sheet_bytes = sum(target.size[0] * target.size[1] * 4 for target in (self.output, self.scratch.native))
        return (self.surfaces.storage_bytes + sheet_bytes + sum(batch.table_bytes for batch in self.parts.values())
                + (upscaler.aa.storage_bytes if upscaler is not None else 0))

    def _batch(self, resource):
        if resource not in self.parts:
            batch = EnemyPartBatch(resource, scratch=self.scratch)
            formats = {name: getattr(resource, name) for name in ("hermite_flow", "compact_depth")
                       if hasattr(resource, name)}
            batch.painter = PartPainter(self.pico, part_count=resource.catalog.part_count,
                frame_crop=resource.catalog.frame_crop, surface=True, pbr=True, deferred=True,
                coat=resource.catalog.coat_members is not None, instanced=True, **formats)
            self.parts[resource] = batch
        return self.parts[resource]

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

    def prepare(self, body_requests, sprites, zoom):
        self.surface_submits = self.light_submits = 0
        for resource in self.parts.keys() - {sprite.resource for sprite in sprites.values()}:
            self.parts.pop(resource).close()
        p = self.pico
        sx, sy = ct.c_float(), ct.c_float()
        p.SDL_RenderGetScale(p.renderer, ct.byref(sx), ct.byref(sy))
        if (sx.value, sy.value) != (1, 1) or len(body_requests) > MAX_PROFILES:
            return {}
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
                    groups[key] = (bank_data, clip, frame_state(clip, clip, seconds), [], {}, [], [])
                bank_data, clip, state, instances, samples, ids, regions = groups[key]
                first, phase = frame_phase(clip, seconds)
                left, top, width, height = state["bounds"]
                draw_w, draw_h = max(1, round(width * factor)), max(1, round(height * factor))
                destination = p.SDL_Rect(round(x - (pivot_x - left) * factor) - pad,
                    round(foot - (pivot_y - top) * factor) - pad, draw_w + 2 * pad, draw_h + 2 * pad)
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
                        regions.append((slot, source))
                    poses[pose] = (self.output if upscale else self.scratch.native, p.SDL_Rect(*source))
                    instances.append((paint_slot, phase, first))
                    samples[first] = seconds
                target, rect = poses[pose]
                copies[enemy_id] = target, rect, destination
                ids.append(enemy_id)
            jobs.append((profile, r, groups))
        if not copies:
            return {}
        target = self.scratch.native
        target.reserve(native_layout)
        self.surfaces.reserve(self.lighting, target.size)
        regions, clear = [], True
        with render_target(p, target.texture):
            for profile, r, groups in jobs:
                batch = self._batch(r)
                painter, sampler = batch.painter, batch.painter.sampler
                before = sampler.submits
                with sampler.batch(), self.surfaces.bind(sampler, clear=clear):
                    clear = False
                    sampler.glUniform1f(sampler.uniforms["deferredProfile"], profile)
                    for key, (bank_data, _, state, instances, samples, ids, upsized) in groups.items():
                        if not instances:
                            continue
                        table = batch._table(key, bank_data, samples)
                        if table is None:
                            for enemy_id in ids:
                                copies.pop(enemy_id, None)
                            continue
                        painter.paint(r.cache, (bank_data,), state, None, energy_color=r.energy_color,
                            energy_gain=r.energy_mask_gain, shadow_map=r.shadow_map, pbr_lighting=r.pbr_lighting,
                            sample_shadow=False, instances=instances, pose_table=table)
                        regions.extend(upsized)
                self.surface_submits += sampler.submits - before
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
        self.lighting.close()
        self.surfaces.close()
        self.output.close()
        self.scratch.close()

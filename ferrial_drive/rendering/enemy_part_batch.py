"""같은 파츠 표본 쌍을 묶어 근거리 기체별 보간 결과를 화면 해상도로 합성한다."""

import ctypes as ct
from collections import OrderedDict
from contextlib import nullcontext

from .atlas_texture_cache import AtlasTextureBindings
from .enemy_gl_sheet import EnemyGlSheet
from .part_motion_atlas import frame_phase, frame_state
from .part_painter import PartPainter
from .part_upscale import PART_UPSCALE_BORDER, PartSheetUpscaler, render_target


SHEET_WIDTH = 1024
MAX_SHEET_HEIGHT = 2048
TABLE_BUDGET_BYTES = 8 * 1024 ** 2
UPSCALE_GUTTER = 4


class SheetLayout:
    def __init__(self, gutter=0):
        self.gutter = gutter
        self.left = self.top = self.row_height = self.width = 0

    @property
    def height(self):
        return self.top + self.row_height

    def place(self, width, height):
        width_padded, height_padded = width + self.gutter, height + self.gutter
        if width_padded > SHEET_WIDTH or height_padded > MAX_SHEET_HEIGHT:
            return None
        if self.left + width_padded > SHEET_WIDTH:
            self.left, self.top, self.row_height = 0, self.height, 0
        if self.top + height_padded > MAX_SHEET_HEIGHT:
            return None
        slot = self.left, self.top, width, height
        self.left += width_padded
        self.width = max(self.width, self.left)
        self.row_height = max(self.row_height, height_padded)
        return slot


class SheetTarget:
    def __init__(self, pico):
        self.pico = pico
        self.texture = None
        self.size = (0, 0)

    def reserve(self, layout, gl_sheet=None):
        size = tuple(max(old, max(64, 1 << (required - 1).bit_length()))
                     for old, required in zip(self.size, (layout.width, layout.height), strict=True))
        if size == self.size:
            return
        p = self.pico
        texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_TARGET, *size)
        if not texture:
            raise RuntimeError("적 기체 묶음 타깃 생성 실패")
        blend = p.SDL_ComposeCustomBlendMode(p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
            p.SDL_BLENDOPERATION_ADD, p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
            p.SDL_BLENDOPERATION_ADD)
        if p.SDL_SetTextureBlendMode(texture, blend) or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeNearest):
            p.SDL_DestroyTexture(texture)
            raise RuntimeError("적 기체 묶음 합성 설정 실패")
        self.close(gl_sheet)
        self.texture, self.size = texture, size

    def close(self, gl_sheet=None):
        if self.texture:
            if gl_sheet is not None:
                gl_sheet.forget(self.texture)
            self.pico.SDL_DestroyTexture(self.texture)
            self.texture = None
            self.size = (0, 0)


class EnemyUpscaleScratch:
    """한 교전의 시트 합성용 상태, 렌더 타깃과 필터를 공유한다."""

    def __init__(self, pico):
        self.native = SheetTarget(pico)
        self.upscalers = {}
        self.gl_sheet = None
        self.gl_sheet_unavailable = False

    def get_upscaler(self, aa_mode="smaa"):
        if aa_mode not in self.upscalers:
            try:
                self.upscalers[aa_mode] = PartSheetUpscaler(self.native.pico, aa_mode)
            except RuntimeError:
                self.upscalers[aa_mode] = None
        return self.upscalers[aa_mode]

    def get_gl_sheet(self):
        if self.gl_sheet is None and not self.gl_sheet_unavailable:
            try:
                self.gl_sheet = EnemyGlSheet(self.native.pico)
            except RuntimeError:
                self.gl_sheet_unavailable = True
        return self.gl_sheet

    def close(self):
        if self.gl_sheet is not None:
            self.gl_sheet.close()
            self.gl_sheet = None
        self.native.close()
        for upscaler in self.upscalers.values():
            if upscaler is not None:
                upscaler.close()
        self.upscalers.clear()


class EnemyPartBatch:
    def __init__(self, resource, *, scratch=None):
        self.resource = resource
        self.painter = None
        self.output = SheetTarget(resource.pico)
        self.scratch = scratch if scratch is not None else EnemyUpscaleScratch(resource.pico)
        self.owns_scratch = scratch is None
        self.pad = 0
        self.submits = 0
        self.unavailable = None
        self.tables = OrderedDict()
        self.table_bytes = 0

    @property
    def texture(self):
        return self.output.texture

    def _table(self, key, bank, samples, *, bindings=None):
        clip = bank["data"]["clip"]
        painter = self.painter
        sampler = painter.sampler
        width = len(painter.arrays) * len(clip["parts"])
        height = len(clip.get("keyframe_seconds", clip["anchors"])) - 1
        cost = width * height * 16
        if cost > TABLE_BUDGET_BYTES or max(width, height) > sampler.max_texture_size:
            return None
        if key not in self.tables:
            if bindings is not None and self.table_bytes + cost > TABLE_BUDGET_BYTES:
                bindings.restore()
            while self.table_bytes + cost > TABLE_BUDGET_BYTES:
                _, (old, _, size) = self.tables.popitem(last=False)
                sampler.glDeleteTextures(1, ct.byref(old))
                self.table_bytes -= size
            self.tables[key] = ct.c_uint(), set(), cost
            self.table_bytes += cost
        self.tables.move_to_end(key)
        table, resident, _ = self.tables[key]
        missing = samples.keys() - resident
        if missing:
            rows = []
            for first in missing:
                state = frame_state(clip, clip, samples[first])
                fields = painter.frame_arrays(self.resource.cache, (bank,), state)
                values = [value for part in range(len(state["parts"])) for field in painter.arrays
                          for value in fields[field][4*part:4*part+4]]
                rows.append((first, (ct.c_float * len(values))(*values)))
            sampler.upload_rows(table, width, height, rows)
            resident.update(missing)
        return table.value

    def prepare(self, requests, scale, *, direct_sheet=False):
        """보간 위상을 보존하고 Bicubic·SMAA는 기종별 시트에 적용한다."""
        self.submits = 0
        r = self.resource
        factor = scale * r.data["pixel_scale"]
        if len(requests) < 2 or self.unavailable or r.paged or not r.pbr_lighting:
            return {}
        upscale = factor > 1 and r.upscaler is not None and r.data.get("upscale_filter") == "bounded_bicubic"
        p = r.pico
        sx, sy = ct.c_float(), ct.c_float()
        p.SDL_RenderGetScale(p.renderer, ct.byref(sx), ct.byref(sy))
        if sx.value != 1 or sy.value != 1:
            return {}
        if self.painter is None:
            try:
                self.painter = PartPainter(p, part_count=r.catalog.part_count, frame_crop=r.catalog.frame_crop,
                    surface=True, pbr=True, coat=r.catalog.coat_members is not None, instanced=True,
                    hermite_flow=r.hermite_flow, compact_depth=r.compact_depth)
            except RuntimeError as exc:
                self.unavailable = str(exc)
                return {}
        sheet_upscaler = self.scratch.get_upscaler(r.upscaler.aa_mode) if upscale else None
        if upscale and sheet_upscaler is None:
            return {}
        border = PART_UPSCALE_BORDER if upscale else 0
        pad = self.pad = round(border * factor)
        output_layout = SheetLayout(UPSCALE_GUTTER if upscale else 0)
        native_layout = SheetLayout() if upscale else output_layout
        groups, copies = {}, {}
        pose_slots = {}
        px, py = r.data["pivot_top_left"]
        for enemy_id, motion, direction, seconds, x, foot in requests:
            key = motion, direction
            group = groups.get(key)
            if group is None:
                clip = r.get(*key)["data"]["clip"]
                state = frame_state(clip, clip, seconds)
                bx, by, bw, bh = state["bounds"]
                geometry = ((px - bx) * factor, (py - by) * factor,
                            max(1, round(bw * factor)) + 2 * pad,
                            max(1, round(bh * factor)) + 2 * pad, bw, bh)
                group = groups[key] = clip, state, geometry, [], {}, [], []
            clip, _, geometry, instances, samples, ids, regions = group
            first, phase = frame_phase(clip, seconds)
            offset_x, offset_y, width, height, bw, bh = geometry
            destination = p.SDL_Rect(round(x - offset_x) - pad, round(foot - offset_y) - pad, width, height)
            pose = motion, direction, first, phase
            source = pose_slots.get(pose)
            if source is not None:
                copies[enemy_id] = source, destination
                ids.append(enemy_id)
                continue
            slot = output_layout.place(destination.w, destination.h)
            if slot is None:
                continue
            paint_slot = slot
            if upscale:
                native_slot = native_layout.place(bw + 2 * border, bh + 2 * border)
                if native_slot is None:
                    continue
                nx, ny, _, _ = native_slot
                paint_slot = nx + border, ny + border, bw, bh
                regions.append((native_slot, slot))
            source = pose_slots[pose] = p.SDL_Rect(*slot)
            copies[enemy_id] = source, destination
            instances.append((paint_slot, phase, first))
            samples[first] = seconds
            ids.append(enemy_id)
        if not copies:
            return {}
        target = self.scratch.native if upscale else self.output
        target.reserve(native_layout, self.scratch.gl_sheet)
        sampler = self.painter.sampler
        before = sampler.submits
        direct_supported = (not upscale or sheet_upscaler.aa is not None
                            or getattr(p, "fdrive_native_gl", None) is not None)
        direct = self.scratch.get_gl_sheet() if direct_sheet and r.stream_budget is not None and direct_supported else None
        if direct:
            textures, intermediate, smaa_size = (target.texture,), (), None
            if upscale:
                self.output.reserve(output_layout, direct)
                textures += (self.texture,)
                if sheet_upscaler.aa is not None:
                    smaa_size = self.output.size
                    if direct.smaa_layers is None:
                        sheet_upscaler.aa.ensure_size(*smaa_size)
                        intermediate = tuple(sheet_upscaler.aa.targets)
            with direct.frame(sampler, textures, smaa_size=smaa_size, intermediate=intermediate):
                with direct.target(target.texture, target.size), direct.batch(sampler):
                    regions = self._paint_groups(groups, copies, direct.bindings)
                if regions:
                    sheet_upscaler.draw(target.texture, target.size, self.texture, self.output.size, regions,
                                        gl_sheet=direct)
        else:
            scope = sampler.batch() if r.stream_budget is not None else nullcontext()
            textures = AtlasTextureBindings(sampler) if r.stream_budget is not None else nullcontext()
            with render_target(p, target.texture), scope, textures as bindings:
                regions = self._paint_groups(groups, copies, bindings)
            if regions:
                self.output.reserve(output_layout, self.scratch.gl_sheet)
                sheet_upscaler.draw(target.texture, target.size, self.texture, self.output.size, regions)
        self.submits = sampler.submits - before
        return copies

    def _paint_groups(self, groups, copies, bindings):
        r = self.resource
        upscale_regions = []
        for key, (_, state, _, instances, samples, ids, regions) in groups.items():
            if not instances:
                continue
            bank = r.get(*key)
            table = self._table(key, bank, samples, bindings=bindings)
            if table is None:
                for enemy_id in ids:
                    del copies[enemy_id]
                continue
            self.painter.paint(r.cache, (bank,), state, None, energy_color=r.energy_color,
                energy_gain=r.energy_mask_gain, rim=r.rim_light, realtime_light=r.realtime_light,
                shadow_map=r.shadow_map, pbr_lighting=r.pbr_lighting, sample_shadow=False,
                instances=instances, pose_table=table, texture_bindings=bindings)
            upscale_regions.extend(regions)
        return upscale_regions

    def copy(self, record):
        source, destination = record
        p = self.resource.pico
        if p.SDL_RenderCopy(p.renderer, self.texture, source, destination):
            raise RuntimeError("적 기체 묶음 합성 실패")
        return destination.y + self.pad

    def close(self):
        self.output.close(self.scratch.gl_sheet)
        if self.owns_scratch:
            self.scratch.close()
        if self.painter is not None:
            for table, _, _ in self.tables.values():
                self.painter.sampler.glDeleteTextures(1, ct.byref(table))
            self.table_bytes = 0
            self.tables.clear()
            self.painter.close()
            self.painter = None

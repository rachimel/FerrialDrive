"""같은 파츠 표본 쌍을 묶어 근거리 기체별 보간 결과를 화면 해상도로 합성한다."""

import ctypes as ct
from collections import OrderedDict

from .part_motion_atlas import frame_phase, frame_state
from .part_painter import PartPainter
from .part_upscale import render_target


SHEET_WIDTH = 1024
MAX_SHEET_HEIGHT = 2048
TABLE_BUDGET_BYTES = 8 * 1024 ** 2


class EnemyPartBatch:
    def __init__(self, resource):
        self.resource = resource
        self.painter = self.texture = None
        self.height = 0
        self.submits = 0
        self.unavailable = None
        self.tables = OrderedDict()
        self.table_bytes = 0

    def _table(self, key, bank, samples):
        clip = bank["data"]["clip"]
        painter = self.painter
        sampler = painter.sampler
        width = len(painter.arrays) * len(clip["parts"])
        height = len(clip.get("keyframe_seconds", clip["anchors"])) - 1
        cost = width * height * 16
        if cost > TABLE_BUDGET_BYTES or max(width, height) > sampler.max_texture_size:
            return None
        if key not in self.tables:
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

    def _reserve(self, height):
        if height <= self.height:
            return
        p = self.resource.pico
        height = max(64, 1 << (height - 1).bit_length())
        texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_TARGET,
                                      SHEET_WIDTH, height)
        if not texture:
            raise RuntimeError("적 기체 묶음 타깃 생성 실패")
        blend = p.SDL_ComposeCustomBlendMode(p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
            p.SDL_BLENDOPERATION_ADD, p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
            p.SDL_BLENDOPERATION_ADD)
        if p.SDL_SetTextureBlendMode(texture, blend) or p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeNearest):
            p.SDL_DestroyTexture(texture)
            raise RuntimeError("적 기체 묶음 합성 설정 실패")
        if self.texture:
            p.SDL_DestroyTexture(self.texture)
        self.texture, self.height = texture, height

    def prepare(self, requests, scale):
        """기체별 원래 표본 간 위상을 보존한다. 시트 밖·전용 확대 필터는 기존 경로로 그린다."""
        self.submits = 0
        r = self.resource
        factor = scale * r.data["pixel_scale"]
        if (len(requests) < 2 or self.unavailable or r.paged or not r.pbr_lighting
                or (factor > 1 and r.data.get("upscale_filter") == "bounded_bicubic")):
            return {}
        p = r.pico
        sx, sy = ct.c_float(), ct.c_float()
        p.SDL_RenderGetScale(p.renderer, ct.byref(sx), ct.byref(sy))
        if sx.value != 1 or sy.value != 1:
            return {}
        if self.painter is None:
            try:
                self.painter = PartPainter(p, part_count=r.catalog.part_count, frame_crop=r.catalog.frame_crop,
                    surface=True, pbr=True, coat=r.catalog.coat_members is not None, instanced=True)
            except RuntimeError as exc:
                self.unavailable = str(exc)
                return {}

        groups, copies = {}, {}
        pose_slots = {}
        left = top = row_height = 0
        px, py = r.data["pivot_top_left"]
        for enemy_id, motion, direction, seconds, x, foot in requests:
            clip = r.get(motion, direction)["data"]["clip"]
            first, phase = frame_phase(clip, seconds)
            key = motion, direction
            group = groups.get(key)
            if group is None:
                state = frame_state(clip, clip, seconds)
                group = groups[key] = state, [], {}, []
            state, instances, samples, ids = group
            bx, by, bw, bh = state["bounds"]
            width, height = max(1, round(bw * factor)), max(1, round(bh * factor))
            destination = p.SDL_Rect(round(x - (px - bx) * factor), round(foot - (py - by) * factor), width, height)
            pose = motion, direction, first, phase
            source = pose_slots.get(pose)
            if source is not None:
                copies[enemy_id] = source, destination
                ids.append(enemy_id)
                continue
            if width > SHEET_WIDTH or height > MAX_SHEET_HEIGHT:
                continue
            if left + width > SHEET_WIDTH:
                left, top, row_height = 0, top + row_height, 0
            if top + height > MAX_SHEET_HEIGHT:
                continue
            slot = left, top, width, height
            source = pose_slots[pose] = p.SDL_Rect(*slot)
            copies[enemy_id] = source, destination
            instances.append((slot, phase, first))
            samples[first] = seconds
            ids.append(enemy_id)
            left += width
            row_height = max(row_height, height)
        if not copies:
            return {}
        self._reserve(top + row_height)
        sampler = self.painter.sampler
        before = sampler.submits
        with render_target(p, self.texture):
            for key, (state, instances, samples, ids) in groups.items():
                if instances:
                    bank = r.get(*key)
                    table = self._table(key, bank, samples)
                    if table is None:
                        for enemy_id in ids:
                            del copies[enemy_id]
                        continue
                    self.painter.paint(r.cache, (bank,), state, None, energy_color=r.energy_color,
                        energy_gain=r.energy_mask_gain, rim=r.rim_light, realtime_light=r.realtime_light,
                        shadow_map=r.shadow_map, pbr_lighting=r.pbr_lighting, sample_shadow=False,
                        instances=instances, pose_table=table)
        self.submits = sampler.submits - before
        return copies

    def copy(self, record):
        source, destination = record
        p = self.resource.pico
        if p.SDL_RenderCopy(p.renderer, self.texture, source, destination):
            raise RuntimeError("적 기체 묶음 합성 실패")
        return destination.y

    def close(self):
        if self.texture:
            self.resource.pico.SDL_DestroyTexture(self.texture)
            self.texture = None
            self.height = 0
        if self.painter is not None:
            for table, _, _ in self.tables.values():
                self.painter.sampler.glDeleteTextures(1, ct.byref(table))
            self.table_bytes = 0
            self.tables.clear()
            self.painter.close()
            self.painter = None

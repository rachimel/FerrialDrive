"""반해상도 PBR 잔상을 아틀라스 뱅크별 인스턴스로 한 타깃에 그린다."""

from collections import OrderedDict
import ctypes as ct

from .atlas_texture_cache import AtlasTextureBindings
from .enemy_part_batch import SheetLayout
from .gl_pass import COLOR_AND_SCISSOR_STATE
from .instanced_quads import QUAD_LIMIT
from .part_motion_atlas import frame_state
from .part_painter import PartPainter
from .part_upscale import PART_UPSCALE_BORDER, PartEchoTarget, render_target


class PartEchoBatch:
    def __init__(self, resource):
        self.resource = resource
        self.painter = PartPainter(resource.pico, part_count=resource.catalog.part_count,
            frame_crop=resource.catalog.frame_crop, surface=True, pbr=True,
            coat=resource.catalog.coat_members is not None, instanced=True, echo_instances=True,
            hermite_flow=resource.hermite_flow, compact_depth=resource.compact_depth)
        self.table = ct.c_uint()
        self.width = len(self.painter.arrays) * resource.catalog.part_count
        self.rows = OrderedDict()
        self.target = PartEchoTarget(resource.pico)

    @property
    def storage_bytes(self):
        return 16 * self.width * QUAD_LIMIT + 4 * self.target.size[0] * self.target.size[1] if self.table.value else 0

    def _prepare_rows(self, poses):
        for key in poses:
            if key in self.rows:
                self.rows.move_to_end(key)
        updates = []
        for key, (resources, state) in poses.items():
            if key in self.rows:
                continue
            slot = len(self.rows)
            if slot == QUAD_LIMIT:
                _, slot = self.rows.popitem(last=False)
            fields = self.painter.frame_arrays(self.resource.cache, resources, state)
            values = (value for i in range(len(state["parts"])) for name in self.painter.arrays
                      for value in fields[name][4*i:4*i+4])
            updates.append((slot, (ct.c_float * (self.width * 4))(*values)))
            self.rows[key] = slot
        if updates:
            try:
                self.painter.sampler.upload_rows(self.table, self.width, QUAD_LIMIT, updates)
            except BaseException:
                self.rows.clear()
                raise

    def draw(self, requests, scale, **appearance):
        r, p = self.resource, self.resource.pico
        resources = r.residency.resources
        layout = SheetLayout(gutter=2)
        groups, poses, copies, drawn = {}, {}, [], []
        factor = scale * r.data["pixel_scale"]
        px, py = r.data["pivot_top_left"]
        border = PART_UPSCALE_BORDER // 2
        pad = round(PART_UPSCALE_BORDER * factor)
        for name, seconds, x, y, opacity, tint, brightness in requests:
            if r.display_pose(name, seconds, allow_fallback=False) is None:
                continue
            motion, pair = name.rsplit("/", 1)
            directions = (pair[1],) if pair[1] == pair[3] else (pair[1], pair[3])
            keys = tuple((motion, direction) for direction in directions)
            if any(key not in resources for key in keys):
                return False
            banks = tuple(resources[key] for key in keys)
            if "gl_texture" not in banks[0]["pages"]["color"]:
                return False
            state = frame_state(banks[0]["data"]["clip"], banks[-1]["data"]["clip"], seconds)
            left, top, width, height = state["bounds"]
            inner_w, inner_h = (width + 1) // 2, (height + 1) // 2
            tile_w, tile_h = inner_w + 2 * border, inner_h + 2 * border
            # 화면 미분에 쓰이는 2×2 픽셀 묶음을 개별 타깃과 같은 위치에 맞춘다.
            tile = layout.place(tile_w + tile_w % 2, tile_h + tile_h % 2)
            if tile is None:
                return False
            tx, ty, _, _ = tile
            destination = p.SDL_Rect(round(x - (px - left) * factor) - pad,
                round(y - (py - top) * factor) - pad, max(1, round(width * factor)) + 2 * pad,
                max(1, round(height * factor)) + 2 * pad)
            copies.append((p.SDL_Rect(tx, ty, tile_w, tile_h), destination))
            # 혼합 뱅크의 허리 보정은 같은 키포즈 쌍 안에서도 원본 위상에 따라 달라진다.
            key = (tuple(bank["pose_identity"] for bank in banks), state["first"],
                   state["anchor_phase"] if len(banks) > 1 else None)
            poses.setdefault(key, (banks, state))
            groups.setdefault(keys, []).append((key, (tx + border, ty + border, inner_w, inner_h),
                                                state, (tint, brightness, opacity)))
            drawn.append((motion, keys))
        if len(drawn) < 2:
            return not drawn
        sampler = self.painter.sampler
        if max(layout.width, layout.height, self.width) > sampler.max_texture_size:
            return False
        target = self.target
        target.reserve(layout.width, layout.height)
        with render_target(p, target.texture), sampler.batch(raster_attributes=COLOR_AND_SCISSOR_STATE):
            self._prepare_rows(poses)
            with AtlasTextureBindings(sampler) as bindings:
                for records in groups.values():
                    banks = poses[records[0][0]][0]
                    instances = [(rect, state["alpha"], self.rows[key]) for key, rect, state, _ in records]
                    self.painter.paint(r.cache, banks, records[0][2], None, sample_shadow=False,
                        instances=instances, pose_table=self.table.value, texture_bindings=bindings,
                        instance_sources=[state["bounds"] for _, _, state, _ in records],
                        echo_styles=[style for _, _, _, style in records], **appearance)
        for source, destination in copies:
            if p.SDL_RenderCopy(p.renderer, target.texture, source, destination):
                raise RuntimeError("인스턴스 잔상 화면 합성 실패")
        for motion, keys in drawn:
            for key in keys:
                resources.move_to_end(key)
            r.draws_by_motion[motion] += 1
        r.draws += len(drawn)
        return True

    def close(self):
        self.target.close()
        if self.table.value:
            self.painter.sampler.glDeleteTextures(1, ct.byref(self.table))
        self.painter.close()

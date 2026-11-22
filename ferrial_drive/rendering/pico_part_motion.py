"""Pico2D 아틀라스 캐시를 재사용하는 파츠별 GPU 보간·픽셀별 깊이 합성."""

from collections import Counter
from contextlib import nullcontext
import ctypes as ct
import json
from math import cos, radians, sin
from pathlib import Path
import re

from ferrial_drive.diagnostics import TimingRecorder
from ferrial_drive.diagnostics.texture_metrics import bind_gl
from .atlas_texture_cache import AtlasTextureCache
from .direction_reprojection import direction_banks, direction_frame, direction_span
from .part_atlas_residency import PartAtlasResidency
from .part_motion_atlas import COMPACT_DEPTH_ENCODING, frame_interval, frame_state
from .part_motion_catalog import PartMotionCatalog
from .part_pbr import COAT_CHANNELS
from .part_painter import PART_SAMPLE_FIELDS, PartPainter
from .part_page_cache import PartPageCache
from .part_upscale import PART_UPSCALE_BORDER, PartEchoTarget, PartUpscaler
from .texture_codecs import find_ktx_library


class PicoPartMotion:
    def __init__(self, pico, source, *, timings=None, mixed_directions=False, max_directions=2, direction_warp=True,
                 cache_budget_bytes=None, pbr_lighting=None, part_spaces=None, upscale_aa="off"):
        self.pico = pico
        self.catalog = PartMotionCatalog(source, part_spaces=part_spaces, max_records=max_directions)
        self.source, self.data = self.catalog.source, self.catalog.data
        self.texture_scale, self.paged = self.catalog.texture_scale, self.catalog.paged
        surface, pbr = self.catalog.surface, self.catalog.pbr
        coat = self.catalog.coat_members is not None
        self.timings = timings or TimingRecorder(enabled=False)
        ktx_library = find_ktx_library() if self.data.get("color_codec") == "ktx2_uastc" else None
        if pbr:
            if not surface or not pbr_lighting:
                raise ValueError("PBR 표면에 실제 조명 설정과 환경 맵이 필요하다.")
            angular = direction_warp and bool(self.data.get("direction_correspondence_by_motion")
                                             or self.data.get("direction_correspondence"))
            units = ct.c_int()
            bind_gl(pico, "glGetIntegerv", None, [ct.c_uint, ct.c_void_p])(0x8872, ct.byref(units))
            banks = 4 if angular else 2
            required_units = (6 if coat else 5) * banks + 2
            if units.value < required_units:
                raise RuntimeError(f"PBR 렌더의 프래그먼트 텍스처 단위가 {required_units}개 필요하다. 현재 {units.value}개다.")
            lighting_path = Path(pbr_lighting).resolve()
            self.pbr_lighting = json.loads(lighting_path.read_text(encoding="utf-8"))
        else:
            self.pbr_lighting = None
        self.hermite_flow = self.data.get("hermite_flow", False)
        self.compact_depth = self.data.get("depth_encoding") == COMPACT_DEPTH_ENCODING
        self.painter = PartPainter(pico, part_count=self.catalog.part_count, paged=self.paged, frame_crop=self.catalog.frame_crop,
                                   surface=surface, pbr=pbr, coat=coat, hermite_flow=self.hermite_flow,
                                   compact_depth=self.compact_depth)
        self.correspondence = {}
        if direction_warp:
            self.correspondence = self.data.get("direction_correspondence_by_motion", {})
            if self.data.get("direction_correspondence"):
                self.correspondence = dict.fromkeys(self.data["motions"], self.data["direction_correspondence"])
        self.direction_sample_fps = self.data.get("direction_sample_fps") if self.correspondence else None
        self.adjacent_pairs = {name: {tuple(pair) for pair in value["pairs"]} for name, value in self.correspondence.items()}
        self.angular_painter = None
        self.upscaler = None
        self.echo_target = None
        self.echo_instances = None
        self.echo_instancing_unavailable = None
        self.shadow_map = None
        try:
            if surface:
                from .part_shadow_map import PartShadowMap
                lighting = ({"light_vector": self.pbr_lighting["shadow_light_vector"],
                             "surface_light_position": self.pbr_lighting["key_position"][:3]} if pbr else {})
                self.shadow_map = PartShadowMap(pico, self.data, scale=self.texture_scale, **lighting)
            if self.correspondence:
                self.angular_painter = PartPainter(pico, angular=True, part_count=self.catalog.part_count,
                                                   paged=self.paged, frame_crop=self.catalog.frame_crop, surface=surface, pbr=pbr,
                                                   coat=coat, hermite_flow=self.hermite_flow, compact_depth=self.compact_depth)
            if pbr or self.data.get("upscale_filter") == "bounded_bicubic":
                aa_mode = upscale_aa if self.data.get("upscale_filter") == "bounded_bicubic" else "off"
                self.upscaler = PartUpscaler(pico, aa_mode)
            if self.paged:
                self.cache = PartPageCache(pico, self.source.parent, self.timings, cache_budget_bytes)
            else:
                self.cache = AtlasTextureCache(pico, timings=self.timings, ktx_library=ktx_library,
                                               synchronize_upload=False)
                if pbr:
                    self.environment_key, self.pbr_lighting["entry"] = self.cache.acquire(
                        self.pbr_lighting["environment"], lighting_path.parent)
        except BaseException:
            if self.shadow_map is not None:
                self.shadow_map.close()
            if self.upscaler is not None:
                self.upscaler.close()
            if self.angular_painter is not None:
                self.angular_painter.close()
            self.painter.close()
            raise
        self.residency = PartAtlasResidency(self.catalog, self.cache, self.timings,
                                            max_directions=max_directions, budget_bytes=cache_budget_bytes)
        self.enabled, self.mixed_directions = True, mixed_directions
        self.direction_enabled = direction_warp
        self.energy_color, self.energy_mask_gain, self.rim_light = None, 1, (0, 0, 0, 0)
        self.realtime_light = 0
        self.draws = self.angular_draws = 0
        self.stream_budget = None
        self.stream_fallbacks = ()
        self.stream_pins = ()
        self.fallback_draws = 0
        self.draws_by_motion = Counter()
        self.paged_lookahead = None

    @property
    def cache_budget_bytes(self):
        return self.residency.cache_budget_bytes

    @cache_budget_bytes.setter
    def cache_budget_bytes(self, value):
        self.residency.cache_budget_bytes = value
        if not self.paged and self.cache.pool_enabled:
            self.cache.configure_pool(value)

    def supports(self, clip_name, quality="high"):
        match = re.fullmatch(r"(.+)/u([0-7])l([0-7])", clip_name)
        if not self.enabled or quality != self.data["quality"] or match is None:
            return False
        motion, upper, lower = match.groups()
        available = self.data["motions"].get(motion, {})
        return upper in available and lower in available and (upper == lower or self.mixed_directions)

    def angular_span(self, clip_name, yaw_degrees, quality="high"):
        motion = clip_name.rsplit("/", 1)[0]
        if not self.enabled or not self.direction_enabled or motion not in self.correspondence or not yaw_degrees or quality != self.data["quality"]:
            return None
        spans = direction_span(*yaw_degrees)
        if spans is None or any((a, b) not in self.adjacent_pairs[motion] for a, b, _ in spans if a != b):
            return None
        available = self.data["motions"][motion]
        return spans if all(str(direction) in available for direction in direction_banks(spans)) else None

    def get(self, motion, direction):
        if self.stream_budget is not None:
            return self.residency.resources[motion, str(direction)]
        return self.residency.get(motion, direction)

    def enable_streaming(self, budget, *fallback_motions):
        motions = self.data["motions"]
        self.stream_fallbacks = tuple((motion, "0") for motion in fallback_motions
                                      if "0" in motions.get(motion, ()))
        if not self.paged:
            self.cache.configure_pool(self.cache_budget_bytes)
        self.residency.require(self.stream_fallbacks)
        self.stream_pins = self.stream_fallbacks
        self.stream_budget = budget

    def pin_streaming_motions(self, names):
        if self.stream_budget is None or self.paged:
            return
        motions = self.data["motions"]
        pins = tuple((motion, direction) for motion in dict.fromkeys(names)
                     for direction in sorted(motions.get(motion, ()))
                     if (motion, direction) not in self.stream_pins)
        previous_limit = self.residency.max_directions
        budget_bytes = self.cache_budget_bytes
        # 다른 동작에도 기존 캐시 예산의 4분의 1을 남긴다.
        preload_limit = budget_bytes * 3 // 4 if budget_bytes is not None else None
        self.residency.max_directions += len(pins)
        self.residency.require(pins, preload_limit_bytes=preload_limit)
        loaded = tuple(key for key in pins if key in self.residency.resources)
        self.stream_pins += loaded
        self.residency.max_directions = previous_limit + len(loaded)

    def display_pose(self, clip_name, seconds, angular_span=None, *, allow_fallback=True):
        if self.stream_budget is None:
            return clip_name, seconds, angular_span
        motion, pair = clip_name.rsplit("/", 1)
        directions = direction_banks(angular_span) if angular_span is not None else (pair[1], pair[3])
        resident = self.residency.resources
        if all((motion, str(direction)) in resident for direction in directions):
            return clip_name, seconds, angular_span
        if not allow_fallback:
            return None
        available = tuple(direction for name, direction in resident if name == motion)
        if available:
            desired = int(pair[3])
            direction = min(available, key=lambda value: abs((int(value) - desired + 4) % 8 - 4))
            return f"{motion}/u{direction}l{direction}", seconds, None
        fallbacks = self.stream_fallbacks
        if motion.startswith("gun_"):
            fallbacks = tuple(reversed(fallbacks))
        for fallback, direction in fallbacks:
            if (fallback, direction) in resident:
                return f"{fallback}/u{direction}l{direction}", 0, None
        return None

    def prepare_frame(self, clip_names, quality="high", angular_pose=None, yaw_pose=None):
        if not self.enabled or quality != self.data["quality"]:
            self.release_pages()
            return
        needed = {}
        remaining = list(clip_names)
        if angular_pose is not None:
            name, spans = angular_pose
            if name in remaining:
                remaining.remove(name)
            motion = name.rsplit("/", 1)[0]
            needed.update(dict.fromkeys((motion, str(direction)) for direction in direction_banks(spans)))
        for name in remaining:
            if self.supports(name, quality):
                motion, pair = name.rsplit("/", 1)
                needed.update(dict.fromkeys(((motion, pair[1]), (motion, pair[3]))))
        if self.stream_budget is not None:
            if self.stream_pins and not self.residency.resources:
                self.residency.require(self.stream_pins)
            lookahead = None
            if yaw_pose is not None:
                motion = yaw_pose[0].rsplit("/", 1)[0]
                if motion in self.correspondence:
                    candidates = self.residency.adjacent_candidates(motion, yaw_pose[1])
                    if candidates:
                        _, lookahead = min(candidates)
            self.residency.stream(tuple(needed), self.stream_pins, self.stream_budget, lookahead=lookahead)
            return
        needed = set(needed)
        ordered = sorted(needed)
        if self.paged:
            self.residency.require(ordered)
            for key in ordered:
                self.residency.resources.move_to_end(key)
            while len(self.residency.resources) > max(self.residency.max_directions, len(ordered)):
                self.residency.resources.popitem(last=False)
            self.paged_lookahead = None
            if yaw_pose is not None and self.residency.last_yaw_pose is not None and yaw_pose[0].rsplit("/", 1)[0] == self.residency.last_yaw_pose[0]:
                predicted = tuple(current + 4 * ((current - previous + 180) % 360 - 180)
                                  for current, previous in zip(yaw_pose[1], self.residency.last_yaw_pose[1], strict=True))
                span = self.angular_span(yaw_pose[0], predicted, quality)
                if span is not None:
                    self.paged_lookahead = yaw_pose[0].rsplit("/", 1)[0], span
            self.residency.last_yaw_pose = (yaw_pose[0].rsplit("/", 1)[0], yaw_pose[1]) if yaw_pose is not None else None
            return
        motion = yaw_pose[0].rsplit("/", 1)[0] if yaw_pose is not None and self.direction_enabled else None
        if motion not in self.correspondence:
            motion = None
        if self.residency.prefetch is not None and self.residency.prefetch.key[0] != motion:
            self.residency.cancel_prefetch()
        cold_frame = any(key not in self.residency.resources for key in needed)
        self.residency.require(ordered)
        for key in ordered:
            self.residency.resources.move_to_end(key)
        if motion is not None:
            self.residency.prepare_adjacent(motion, yaw_pose[1], needed, allow_upload=not cold_frame)
        else:
            self.residency.last_yaw_pose = None
        self.residency.evict(needed)

    @property
    def estimated_bytes(self):
        return self.cache.gpu_storage_bytes

    def batch_cached(self, clip_names, quality):
        if self.upscaler is not None:
            return nullcontext()
        for name in clip_names:
            if not name or not self.supports(name, quality):
                return nullcontext()
            motion, pair = name.rsplit("/", 1)
            if (motion, pair[1]) not in self.residency.resources or (motion, pair[3]) not in self.residency.resources:
                return nullcontext()
        return self.painter.sampler.batch()

    def _page_requests(self, resources, state, *, lookahead=False):
        requests = {}
        energy = self.energy_color is not None and self.energy_mask_gain > 0
        flow = lookahead or 0 < state["alpha"] < 1
        for part in state["parts"]:
            resource = resources[part["bank"] if len(resources) > 1 else 0]
            frames = resource["data"]["frames"]
            for _, kind, end, field in PART_SAMPLE_FIELDS:
                if (kind == "energy" and not energy) or (kind == "vector" and not flow):
                    continue
                page = frames[kind][part[end][field]]["page"]
                if page >= 0:
                    _, key, spec = resource["pages"][kind][page]
                    requests[key] = spec
        return requests

    def _page_lookahead(self, resources, clips, motion, directions, span, seconds):
        future = seconds + 1 / clips[0]["fps"]
        if span is None:
            next_state = frame_state(clips[0], clips[-1], future)
        else:
            interval = frame_interval(clips[0], clips[-1], future)
            next_state = direction_frame(self.correspondence[motion], dict(zip(directions, clips)), span, interval)
        requests = self._page_requests(resources, next_state, lookahead=True)
        if self.paged_lookahead is not None and self.paged_lookahead[0] == motion:
            future_span = self.paged_lookahead[1]
            future_dirs = direction_banks(future_span)
            if set(future_dirs) - set(directions):
                future_resources = tuple(self.get(motion, direction) for direction in future_dirs)
                future_clips = tuple(resource["data"]["clip"] for resource in future_resources)
                interval = frame_interval(future_clips[0], future_clips[-1], future)
                next_state = direction_frame(self.correspondence[motion], dict(zip(future_dirs, future_clips)), future_span, interval)
                requests.update(self._page_requests(future_resources, next_state, lookahead=True))
        return requests

    def prepare_shadow(self, clip_name, elapsed_seconds, angular_span=None, *, cache_geometry=False):
        pose = self.display_pose(clip_name, elapsed_seconds, angular_span)
        if pose is None:
            return False
        clip_name, elapsed_seconds, angular_span = pose
        motion, pair = clip_name.rsplit("/", 1)
        yaw = (int(pair[1]) * 45, int(pair[3]) * 45) if angular_span is None else tuple(
            (first + phase) * 45 for first, _, phase in angular_span)
        direction = int(pair[3]) if angular_span is None else angular_span[1][0]
        clip = self.get(motion, direction)["data"]["clip"]
        with self.timings.scope("parts.shadow_depth"):
            self.shadow_map.prepare(motion, elapsed_seconds, yaw, clip["loop"], clip["duration_seconds"],
                                    cache_geometry=cache_geometry)
        return True

    def draw_ground_shadow(self, clip_name, seconds, x, y, scale, opacity, *,
                           softness_pixels=0, angular_span=None, cache_geometry=False):
        return bool(self.draw_ground_shadows(clip_name, seconds, ((x, y),), scale, opacity,
                    softness_pixels=softness_pixels, angular_span=angular_span, cache_geometry=cache_geometry))

    def draw_ground_shadows(self, clip_name, seconds, placements, scale, opacity, *,
                            softness_pixels=0, angular_span=None, cache_geometry=False):
        shadow = self.shadow_map
        if shadow is None or not shadow.enabled or opacity <= 0:
            return 0
        if not self.prepare_shadow(clip_name, seconds, angular_span, cache_geometry=cache_geometry):
            return 0
        with self.timings.scope("parts.shadow_ground"):
            return shadow.draw_ground_many(placements, scale, opacity, softness_pixels=softness_pixels)

    def draw(self, clip_name, elapsed_seconds, x, y, *, scale=1, opacity=1, tint=(1, 1, 1), tint_mix=0, brightness=1,
             angular_span=None, sample_shadow=True, before_body=None, allow_fallback=True, half_resolution_echo=False):
        pose = self.display_pose(clip_name, elapsed_seconds, angular_span, allow_fallback=allow_fallback)
        if pose is None:
            return None
        self.fallback_draws += pose[0] != clip_name or pose[2] != angular_span
        clip_name, elapsed_seconds, angular_span = pose
        motion, pair = clip_name.rsplit("/", 1)
        directions = direction_banks(angular_span) if angular_span is not None else (pair[1], pair[3])
        if angular_span is None and directions[0] == directions[1]:
            directions = directions[:1]
        keys = tuple((motion, str(direction)) for direction in directions)
        if self.stream_budget is None and any(key not in self.residency.resources for key in keys):
            self.residency.require(keys)
        for key in keys:
            self.residency.resources.move_to_end(key)
        resources = tuple(self.residency.resources[key] for key in keys)
        clips = tuple(resource["data"]["clip"] for resource in resources)
        if self.shadow_map and sample_shadow and self.pbr_lighting is None:
            self.prepare_shadow(clip_name, elapsed_seconds, angular_span)
        painter = self.painter
        with self.timings.scope("parts.select_state"):
            select_state = frame_state if angular_span is None else frame_interval
            state = select_state(clips[0], clips[-1], elapsed_seconds)
            pose_key = None
            if self.pbr_lighting is not None and not self.paged:
                span_banks = tuple(span[:2] for span in angular_span) if angular_span is not None else ()
                pose_key = tuple(resource["pose_identity"] for resource in resources), state["first"], span_banks
            if angular_span is not None:
                state = direction_frame(self.correspondence[motion], dict(zip(directions, clips)), angular_span, state)
                if self.shadow_map:
                    angles = (radians((phase - step) * 45) for first, second, phase in angular_span
                              for step in (0, first != second))
                    state["normal_yaw"] = tuple(value for angle in angles for value in (cos(angle), sin(angle), 0, 0))
                painter = self.angular_painter
                self.angular_draws += 1
        left, top, width, height = state["bounds"]
        factor = scale * self.data["pixel_scale"]
        pivot = self.data["pivot_top_left"]
        destination = self.pico.SDL_Rect(round(x - (pivot[0] - left) * factor), round(y - (pivot[1] - top) * factor),
                                         max(1, round(width * factor)), max(1, round(height * factor)))
        with self.timings.scope("parts.draw_angle" if angular_span is not None else "parts.draw"):
            if self.paged:
                with self.timings.scope("parts.page_prepare"):
                    self.cache.ensure(self._page_requests(resources, state),
                                      self._page_lookahead(resources, clips, motion, directions, angular_span, elapsed_seconds))
            options = dict(energy_color=self.energy_color, energy_gain=self.energy_mask_gain, rim=self.rim_light,
                           opacity=opacity, tint=tint, tint_mix=tint_mix, brightness=brightness,
                           realtime_light=self.realtime_light, shadow_map=self.shadow_map, pbr_lighting=self.pbr_lighting,
                           sample_shadow=sample_shadow, pose_key=pose_key)
            border = PART_UPSCALE_BORDER
            buffer_size = width + 2 * border, height + 2 * border
            native = self.pico.SDL_Rect(border, border, width, height)
            if self.pbr_lighting and self.shadow_map.enabled and sample_shadow:
                with self.timings.scope("parts.shadow_surface"):
                    with self.upscaler.native_target(*buffer_size):
                        painter.paint(self.cache, resources, state, native, depth_output=True,
                                      pbr_lighting=self.pbr_lighting, shadow_map=self.shadow_map,
                                      sample_shadow=False, pose_key=pose_key)
                    self.shadow_map.render_surface(self.upscaler.texture, state["bounds"], border)
            if before_body is not None:
                before_body()
            if half_resolution_echo and self.pbr_lighting:
                if self.echo_target is None:
                    self.echo_target = PartEchoTarget(self.pico)
                pad = round(border * factor)
                grown = self.pico.SDL_Rect(destination.x - pad, destination.y - pad,
                                           destination.w + 2 * pad, destination.h + 2 * pad)
                with self.timings.scope("parts.echo_half"):
                    self.echo_target.draw(width, height, grown,
                                          lambda tile: painter.paint(self.cache, resources, state, tile, **options))
            elif self.upscaler is not None and factor > 1 and self.data.get("upscale_filter") == "bounded_bicubic":
                with self.upscaler.native_target(*buffer_size):
                    painter.paint(self.cache, resources, state, native, **options)
                pad = round(border * factor)
                grown = self.pico.SDL_Rect(destination.x - pad, destination.y - pad,
                                           destination.w + 2 * pad, destination.h + 2 * pad)
                with self.timings.scope("parts.upscale"):
                    self.upscaler.draw(*buffer_size, grown)
            else:
                painter.paint(self.cache, resources, state, destination, **options)
        self.draws += 1
        self.draws_by_motion[motion] += 1
        return destination

    def draw_echo_batch(self, requests, scale):
        if self.paged or not self.pbr_lighting or self.echo_instancing_unavailable:
            return False
        from .part_echo_batch import PartEchoBatch, QUAD_LIMIT

        if not 2 <= len(requests) <= QUAD_LIMIT:
            return False
        if self.echo_instances is None:
            try:
                self.echo_instances = PartEchoBatch(self)
            except RuntimeError as exc:
                self.echo_instancing_unavailable = str(exc)
                return False
        with self.timings.scope("parts.echo_instanced"):
            return self.echo_instances.draw(requests, scale,
                energy_color=self.energy_color, energy_gain=self.energy_mask_gain, rim=self.rim_light,
                realtime_light=self.realtime_light, shadow_map=self.shadow_map, pbr_lighting=self.pbr_lighting)

    def report(self):
        return {**self.cache.report(), "draws": self.draws, "angular_draws": self.angular_draws, "direction_loads": self.residency.loads,
                "draws_by_motion": dict(self.draws_by_motion),
                "resident_directions": len(self.residency.resources), "mixed_directions": self.mixed_directions,
                "prefetch_uploads": self.residency.prefetch_uploads, "prefetch_completed": self.residency.prefetch_completed,
                "coroutine_pages": self.residency.coroutine_pages, "threaded_pages": self.residency.threaded_pages,
                "fallback_draws": self.fallback_draws,
                "pinned_directions": len(self.stream_pins),
                "cache_budget_bytes": self.cache_budget_bytes,
                "direction_sample_fps": self.direction_sample_fps,
                "capture_sample_fps": next(iter(self.residency.resources.values()))["data"]["clip"]["fps"] if self.residency.resources else None,
                "shadow_map": None if self.shadow_map is None else {
                    "depth_draws": self.shadow_map.depth_draws, "ground_draws": self.shadow_map.ground_draws,
                    "size": self.shadow_map.size, "depth_payload_bytes": self.shadow_map.storage_bytes,
                    "ground_map_size": self.shadow_map.ground_size,
                    "ground_shadow_source": "rig_boxes",
                    "caster_boxes": len(self.shadow_map.corners),
                    "caster_bones": self.shadow_map.caster_bones,
                    "surface_depth_draws": self.shadow_map.surface_draws,
                    "projected_ground_draws": self.shadow_map.projected_ground_draws,
                    "ground_geometry_hits": self.shadow_map.ground_geometry_hits,
                    "body_shadow_source": "surface_depth" if self.pbr_lighting else "rig_boxes"},
                "texture_scale": self.texture_scale,
                "material_channels": self.data.get("material_channels"),
                "coat_channels": COAT_CHANNELS if self.catalog.coat_members else (),
                "enabled": self.enabled, "source": str(self.source),
                "upscale_filter": self.data.get("upscale_filter"),
                "upscale_aa": self.upscaler.aa_mode if self.upscaler else "off",
                "upscale_aa_draws": self.upscaler.aa_draws if self.upscaler else 0,
                "upscale_aa_storage_bytes": self.upscaler.aa_storage_bytes if self.upscaler else 0,
                "upscale_storage_bytes": 4 * self.upscaler.size[0] * self.upscaler.size[1] if self.upscaler else 0,
                "echo_storage_bytes": (4 * self.echo_target.size[0] * self.echo_target.size[1] if self.echo_target else 0)
                    + (self.echo_instances.storage_bytes if self.echo_instances else 0)}

    def close(self):
        self.residency.close()
        if self.pbr_lighting:
            self.cache.release(self.environment_key)
        if not self.paged:
            self.cache.purge_pool()
        if self.angular_painter is not None:
            self.angular_painter.close()
        if self.echo_target is not None:
            self.echo_target.close()
        if self.echo_instances is not None:
            self.echo_instances.close()
        if self.upscaler is not None:
            self.upscaler.close()
        if self.shadow_map is not None:
            self.shadow_map.close()
        self.painter.close()

    def release_pages(self):
        self.residency.clear()
        if not self.paged:
            self.cache.purge_pool()
        self.paged_lookahead = None

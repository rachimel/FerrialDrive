"""Pico2D의 기존 아틀라스·발광 셰이더로 동일 자세의 상·하체 출력을 표시한다."""

from collections import OrderedDict
import json

from ferrial_drive.rendering.motion_vectors import target_phase
from .direction_reprojection import direction_span
from .pico_motion_atlas import PicoAtlasSprite
from .texture_codecs import texture_payload_size


class PicoPoseTable:
    parts_only = False
    surface_parts = None

    def __init__(self,pico,catalog,quality,*,progress=None,timings=None,budget_bytes=1536*1024**2,parts=None,parts_only=False,
                 surface_parts=None):
        self.catalog,self.quality = catalog,quality
        self.pico,self.timings,self.budget_bytes = pico,timings,budget_bytes
        self.sprites,self.paths,self.sizes = OrderedDict(),{},{}
        self.pinned = set()
        self.parts, self.shadow_mode = parts, set()
        self.surface_parts = surface_parts
        self.clip_bounds = {}
        self.energy_color,self.energy_mask_gain = None,1
        self.rim_light = (0,0,0,0)
        self.parts_only = parts_only
        if parts_only:
            if parts is None or parts.data["quality"] != quality:
                raise ValueError("선택 품질에 맞는 독립 파츠 아틀라스가 필요하다.")
            if surface_parts is not None:
                pixel_scale = parts.data["pixel_scale"] * parts.data["size"][0] / surface_parts.data["size"][0]
                surface_parts.data["pixel_scale"] = pixel_scale
                surface_parts.shadow_map.pixel_scale = pixel_scale
            return
        preload_bytes = 0
        try:
            for index,(name,spec) in enumerate(catalog.motions.items()):
                path = catalog.directory/spec["variants"][quality]
                data = json.loads(path.read_text(encoding="utf-8"))
                for clip_name, clip in data["clips"].items():
                    if not clip_name.startswith("shadow/"):
                        factor = clip["pixel_scale"]
                        self.clip_bounds[clip_name] = (-clip["pivot"][0] * factor, -clip["pivot"][1] * factor,
                                                      clip["source_size"][0] * factor, clip["source_size"][1] * factor)
                self.paths[name] = path
                self.sizes[name] = sum(texture_payload_size(p["codec"],p["width"],p["height"])
                                       for pages in data["pages"].values() for p in pages)
                # 단축으로 줄인 여유를 새 전 동작 선적재에 다시 소비하지 않는다.
                preload_bytes += data.get("compaction",{}).get("before_bytes",self.sizes[name])
                if progress:
                    progress((index+1)/len(catalog.motions))
            if preload_bytes <= budget_bytes:
                for name in self.paths:
                    self.get(name)
            else:
                self.get("idle_loop" if "idle_loop" in self.paths else next(iter(self.paths)))
            if parts is not None and quality == parts.data["quality"]:
                for name, relative in parts.data.get("shadow_sources", {}).items():
                    path = parts.source.parent / relative
                    data = json.loads(path.read_text(encoding="utf-8"))
                    key = "shadow/" + name
                    self.paths[key] = path
                    self.sizes[key] = sum(texture_payload_size(page["codec"], page["width"], page["height"])
                                          for pages in data["pages"].values() for page in pages)
        except BaseException:
            self.close()
            raise

    @property
    def estimated_bytes(self):
        return sum(s.estimated_bytes for s in self.sprites.values()) + sum(
            sprite.estimated_bytes for sprite in (self.parts, self.surface_parts) if sprite is not None)

    def get(self,name):
        if name not in self.sprites:
            self.evict(self.sizes[name])
            self.sprites[name] = PicoAtlasSprite(self.pico,self.paths[name],timings=self.timings)
        self.sprites.move_to_end(name)
        return self.sprites[name]

    def evict(self,incoming_bytes=0):
        for name in list(self.sprites):
            if self.estimated_bytes+incoming_bytes <= self.budget_bytes:
                break
            if name not in self.pinned:
                self.sprites.pop(name).close()

    def prepare_frame(self,clip_names, *, angular_pose=None, part_only_pose=None):
        # 살아 있는 잔상의 자세를 프레임 도중 축출해 다시 올리지 않는다.
        names = [name for name in clip_names if name is not None]
        if self.parts_only:
            name, angles = part_only_pose
            parts, span = self.select_parts(name, angles)
            active = (name, span) if span is not None else None
            if parts is self.surface_parts and parts is not None:
                self.parts.prepare_frame(names, self.quality)
                parts.prepare_frame([name], self.quality, angular_pose=active, yaw_pose=part_only_pose)
            else:
                self.parts.prepare_frame([name, *names], self.quality, angular_pose=active,
                                         yaw_pose=part_only_pose if angles is not None else None)
            return
        self.shadow_mode = set()
        if self.parts is not None:
            active = part_only_pose or angular_pose
            part_names = names + [part_only_pose[0]] if part_only_pose else names
            span = self.parts.angular_span(*active, self.quality) if active else None
            if span is not None:
                self.parts.prepare_frame(part_names, self.quality, angular_pose=(active[0], span))
            else:
                self.parts.prepare_frame(part_names, self.quality)
            # 같은 이름의 잔상도 미지원이면 기존 본체를 유지한다.
            support_name = angular_pose[0] if angular_pose and span and names.count(angular_pose[0]) == 1 else None
            for motion in {name.split("/")[0] for name in names}:
                if ("shadow/" + motion in self.paths and all(name == support_name or self.parts.supports(name, self.quality)
                        for name in names if name.split("/")[0] == motion)):
                    self.shadow_mode.add(motion)
                    if motion in self.sprites:
                        self.sprites.pop(motion).close()
                elif "shadow/" + motion in self.sprites:
                    self.sprites.pop("shadow/" + motion).close()
        self.pinned = {("shadow/" if name.split("/")[0] in self.shadow_mode else "") + name.split("/")[0] for name in names}
        for name in sorted(self.pinned):
            self.get(name)
        self.evict()

    def draw_frame(self,clip_name,frame_index,x,y,*,scale=1,shadow=False,opacity=1,**options):
        name = clip_name.split("/")[0]
        if not shadow and self.draw_motion(clip_name, frame_index / 12, x, y, scale=scale, opacity=opacity, **options):
            return
        sprite = self.get(("shadow/" if shadow and name in self.shadow_mode else "") + name)
        sprite.energy_color = None if shadow else self.energy_color
        sprite.energy_mask_gain = self.energy_mask_gain
        sprite.rim_light = (0,0,0,0) if shadow else self.rim_light
        sprite.draw_frame(("shadow/" if shadow else "")+clip_name,frame_index,x,y,
                          scale=scale,opacity=opacity,**options)

    def draw_echo(self,clip_name,seconds,x,y,*,easing="linear",**options):
        name = clip_name.split("/")[0]
        spec = self.catalog.motions[name]
        phase = target_phase(min(1,seconds/(spec["source_frame_count"]/12)),easing=easing)
        echo_options = options
        if getattr(self.parts, "pbr_lighting", None):
            echo_options = dict(options, sample_shadow=False, allow_fallback=False, half_resolution_echo=True)
        if self.draw_motion(clip_name, phase * spec["source_frame_count"] / 12, x, y, use_surface=False, **echo_options):
            return
        frame = min(spec["frames"]-1,int(phase*spec["source_frame_count"]))
        self.draw_frame(clip_name,frame,x,y,**options)

    def select_parts(self, clip_name, yaw_degrees=None, *, use_surface=True):
        surface = getattr(self, "surface_parts", None)
        if use_surface and surface is not None and self.parts.enabled:
            angles = yaw_degrees if self.parts.direction_enabled else None
            span = surface.angular_span(clip_name, angles, self.quality) if angles is not None else None
            if span is not None or ((angles is None or direction_span(*angles) is None)
                                    and surface.supports(clip_name, self.quality)):
                return surface, span
        if self.parts is not None:
            span = self.parts.angular_span(clip_name, yaw_degrees, self.quality) if yaw_degrees is not None else None
            if span is not None or self.parts.supports(clip_name, self.quality):
                return self.parts, span
        return None, None

    def draw_motion(self, clip_name, seconds, x, y, *, yaw_degrees=None, use_surface=True, **options):
        parts, span = self.select_parts(clip_name, yaw_degrees, use_surface=use_surface)
        if parts is None:
            return False
        parts.energy_color, parts.energy_mask_gain = self.energy_color, self.energy_mask_gain
        parts.rim_light = self.rim_light
        if span is not None:
            options["angular_span"] = span
        parts.draw(clip_name, seconds, x, y, **options)
        return True

    def close(self):
        for sprite in self.sprites.values():
            sprite.close()
        self.sprites.clear()
        if self.surface_parts is not None:
            self.surface_parts.close()
            self.surface_parts = None

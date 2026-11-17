"""Pico2D의 기존 아틀라스·발광 셰이더로 동일 자세의 상·하체 출력을 표시한다."""

from collections import OrderedDict
import json

from ferrial_drive.rendering.motion_vectors import target_phase
from .pico_motion_atlas import PicoAtlasSprite
from .texture_codecs import texture_payload_size


class PicoPoseTable:
    def __init__(self,pico,catalog,quality,*,progress=None,timings=None,budget_bytes=1536*1024**2):
        self.catalog,self.quality = catalog,quality
        self.pico,self.timings,self.budget_bytes = pico,timings,budget_bytes
        self.sprites,self.paths,self.sizes = OrderedDict(),{},{}
        self.pinned = set()
        self.clip_bounds = {}
        self.energy_color,self.energy_mask_gain = None,1
        self.rim_light = (0,0,0,0)
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
        except BaseException:
            self.close()
            raise

    @property
    def estimated_bytes(self):
        return sum(s.estimated_bytes for s in self.sprites.values())

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

    def prepare_frame(self,clip_names):
        # 살아 있는 잔상의 자세를 프레임 도중 축출해 다시 올리지 않는다.
        self.pinned = {name.split("/")[0] for name in clip_names if name is not None}
        for name in sorted(self.pinned):
            self.get(name)
        self.evict()

    def draw_frame(self,clip_name,frame_index,x,y,*,scale=1,shadow=False,opacity=1,**options):
        name = clip_name.split("/")[0]
        sprite = self.get(name)
        sprite.energy_color = None if shadow else self.energy_color
        sprite.energy_mask_gain = self.energy_mask_gain
        sprite.rim_light = (0,0,0,0) if shadow else self.rim_light
        sprite.draw_frame(("shadow/" if shadow else "")+clip_name,frame_index,x,y,
                          scale=scale,opacity=opacity,**options)

    def draw_echo(self,clip_name,seconds,x,y,*,easing="linear",**options):
        name = clip_name.split("/")[0]
        spec = self.catalog.motions[name]
        phase = target_phase(min(1,seconds/(spec["source_frame_count"]/12)),easing=easing)
        frame = min(spec["frames"]-1,int(phase*spec["source_frame_count"]))
        self.draw_frame(clip_name,frame,x,y,**options)

    def close(self):
        for sprite in self.sprites.values():
            sprite.close()
        self.sprites.clear()

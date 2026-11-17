"""상·하체 방향의 자세 표 선택과 같은 Unreal 본 추적의 부착점 투영."""

from bisect import bisect_right
from dataclasses import dataclass
import json
from math import cos, floor, isfinite, pi, sin, sqrt
from pathlib import Path

from .aim_follow import angle_delta_degrees
from .geometry import Vec2
from ferrial_drive.rendering.motion_vectors import target_phase


def direction_index(yaw_degrees):
    if not isfinite(yaw_degrees):
        raise ValueError("시선 방향은 유한한 도 단위다.")
    return floor(yaw_degrees / 45 + .5) % 8


def rotate_yaw(point, yaw_degrees):
    angle = yaw_degrees * pi / 180
    c, s = cos(angle), sin(angle)
    x,y,z = point
    return (c*x-s*y,s*x+c*y,z)


@dataclass(frozen=True)
class PoseSelection:
    clip_name: str
    frame_index: int
    upper: int
    lower: int


class UpperLowerCatalog:
    def __init__(self, data, directory=Path(".")):
        if (data.get("version") != 1 or data.get("type") != "upper_lower_pose_table"
                or data.get("directions") != 8 or data.get("fps") != 12 or not data.get("motions")):
            raise ValueError("12fps·8방향 상하체 자세 표가 필요하다.")
        self.data, self.directory = data, Path(directory)
        self.motions = data["motions"]

    @classmethod
    def load(cls, path):
        path = Path(path)
        return cls(json.loads(path.read_text(encoding="utf-8")),path.parent)

    def select(self, motion, seconds, upper_yaw, lower_yaw, *, loop=None):
        if motion not in self.motions:
            return None
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("동작 시간은 0 이상의 유한한 초다.")
        spec = self.motions[motion]
        looping = spec["loop"] if loop is None else loop
        duration = spec["source_frame_count"]/12
        frame = floor((seconds % duration if looping else seconds)*12+1e-8)
        frame = min(frame,spec["frames"]-1)
        upper,lower = direction_index(upper_yaw),direction_index(lower_yaw)
        return PoseSelection(f"{motion}/u{upper}l{lower}",frame,upper,lower)


class PoseAttachments:
    def __init__(self, catalog):
        self.catalog = catalog
        self.tracks = catalog.data["attachments"]
        self.previous = self.current = (45.0,45.0)
        camera = catalog.data["camera"]
        forward = [b-a for a,b in zip(camera["position"],camera["target"])]
        length = sqrt(sum(v*v for v in forward))
        forward = [v/length for v in forward]
        right = [-forward[1],forward[0],0]
        length = sqrt(sum(v*v for v in right))
        self.right = [v/length for v in right]
        self.up = [forward[1]*self.right[2]-forward[2]*self.right[1],
                   forward[2]*self.right[0]-forward[0]*self.right[2],
                   forward[0]*self.right[1]-forward[1]*self.right[0]]
        self.pixels_per_cm = camera["size"][0]/camera["width_cm"] * catalog.data.get("pixel_scale",1)
        self.steps, self.seconds = [],0
        self.easing = "linear"

    def begin_frame(self, previous, current, steps, seconds):
        self.previous = tuple(direction_index(v)*45 for v in previous)
        self.current = tuple(direction_index(v)*45 for v in current)
        self.steps,self.seconds = steps,seconds

    def angles_at(self, fraction=1):
        return tuple(a+angle_delta_degrees(b,a)*max(0,min(1,fraction)) for a,b in zip(self.previous,self.current))

    def point(self,motion,seconds,label,*,fraction=1):
        spec = self.tracks[motion]
        seconds = seconds % spec["duration_seconds"] if spec["loop"] else min(spec["duration_seconds"],max(0,seconds))
        rows = spec["samples"]
        index = min(len(rows)-1,max(1,bisect_right(rows,seconds,key=lambda row:row["seconds"])))
        a,b = rows[index-1:index+1]
        t = (seconds-a["seconds"])/(b["seconds"]-a["seconds"])
        blend = lambda x,y: tuple(v+(w-v)*t for v,w in zip(x,y))
        root,waist,p = blend(a["root"],b["root"]),blend(a["waist"],b["waist"]),blend(a["points"][label],b["points"][label])
        upper,lower = self.angles_at(fraction)
        if label in spec["upper_points"]:
            pivot = rotate_yaw(tuple(v-r for v,r in zip(waist,root)),lower)
            delta = rotate_yaw(tuple(v-w for v,w in zip(p,waist)),upper)
            return tuple(r+w+d for r,w,d in zip(root,pivot,delta))
        delta = rotate_yaw(tuple(v-r for v,r in zip(p,root)),lower)
        return tuple(r+d for r,d in zip(root,delta))

    def projected(self,motion,seconds,label,*,fraction=1):
        point = self.point(motion,seconds,label,fraction=fraction)
        return Vec2(sum(a*b for a,b in zip(point,self.right))*self.pixels_per_cm,
                    -sum(a*b for a,b in zip(point,self.up))*self.pixels_per_cm)

    def aim_plane_offset(self,motion,seconds):
        height = self.point(motion,seconds,"muzzle")[2]
        return Vec2(0,-height*self.up[2]*self.pixels_per_cm)

    def ground_offsets(self,motion,seconds,scale):
        result = {}
        for name in self.tracks[motion]["samples"][0]["points"]:
            if name not in ("muzzle","blade_root","blade_tip"):
                point = self.projected(motion,seconds,name)*scale
                result[name] = (point.x,point.y)
        return result

    def frame_fraction(self,name,source_seconds):
        cursor = 0
        for step in self.steps:
            if step.clip_name.split("/")[0] == name:
                low,high = 0.0,1.0
                source_phase = source_seconds/step.duration_seconds
                for _ in range(20):
                    middle = (low+high)/2
                    if target_phase(middle,easing=self.easing)<source_phase:
                        low = middle
                    else:
                        high = middle
                elapsed = (low+high)/2*step.duration_seconds
                ratio = (elapsed-step.start_seconds)/max(1e-9,step.end_seconds-step.start_seconds)
                return max(0,min(1,(cursor+ratio*step.real_seconds)/max(1e-9,self.seconds)))
            cursor += step.real_seconds
        return 1


class PoseBladeTrajectory:
    def __init__(self,attachments,fallback):
        self.attachments,self.fallback = attachments,fallback

    def pose(self,name,seconds,scale,reach_scale):
        motion = name.split("/")[0]
        if motion not in self.attachments.tracks:
            return self.fallback.pose(name,seconds,scale,reach_scale)
        fraction = self.attachments.frame_fraction(motion,seconds)
        root = self.attachments.projected(motion,seconds,"blade_root",fraction=fraction)*scale
        tip = self.attachments.projected(motion,seconds,"blade_tip",fraction=fraction)*scale
        return root,root+(tip-root)*reach_scale

    def echo_clip_name(self,name,seconds):
        motion = name.split("/")[0]
        if motion not in self.attachments.tracks:
            return None
        duration = self.attachments.catalog.motions[motion]["source_frame_count"]/12
        source = target_phase(min(1,seconds/duration),easing=self.attachments.easing)*duration
        upper,lower = self.attachments.angles_at(self.attachments.frame_fraction(motion,source))
        return f"{motion}/u{direction_index(upper)}l{direction_index(lower)}"

"""PBR 파츠 카탈로그와 방향별 프레임·코팅 메타데이터."""

from collections import OrderedDict
import json
from pathlib import Path

from .part_motion_atlas import MAX_PARTS
from .part_pbr import COAT_CHANNELS


class PartMotionCatalog:
    def __init__(self, source, *, part_spaces=None, max_records=32):
        self.coat_folder = self.coat_members = None
        self.records = OrderedDict()
        self.max_records = max(2, max_records)
        self.source = Path(source).resolve()
        self.data = json.loads(self.source.read_text(encoding="utf-8"))
        if part_spaces:
            spaces = self.data.setdefault("part_spaces", {})
            for name, parts in part_spaces.items():
                spaces.setdefault(name, {}).update(parts)
        self.texture_scale = self.data.get("texture_scale") or 1 / (self.data.get("texture_divisor") or 1)
        layout = self.data.get("part_pages")
        self.paged = layout is not None
        self.frame_crop = self.paged and layout.get("geometry_crop") == "frame"
        if self.paged and layout.get("version") != 1:
            raise ValueError("지원하지 않는 파츠 페이지 형식이다.")
        if self.data.get("type") != "part_motion_gpu" or self.data.get("version") != 1:
            raise ValueError("독립 파츠 GPU 카탈로그 v1이 필요하다.")
        self.part_count = len(self.data["parts"])
        if not 1 <= self.part_count <= MAX_PARTS:
            raise ValueError("지원 범위의 파츠 수가 필요하다.")
        self.surface = self.data.get("surface_encoding") == "world_normal_rgb_energy_a"
        self.pbr = self.data.get("material_channels") == ["Metallic", "Roughness", "Specular"]
        coat_index = self.data.get("coat_index")
        if coat_index:
            if not self.pbr:
                raise ValueError("코팅 데이터는 PBR 아틀라스에 연결해야 한다.")
            index_path = (self.source.parent / coat_index).resolve()
            if not index_path.is_relative_to(self.source.parent):
                raise ValueError("코팅 인덱스가 품질 폴더 밖에 있다.")
            coat_data = json.loads(index_path.read_text(encoding="utf-8"))
            members = {path for row in self.data["motions"].values() for path in row.values()}
            if tuple(coat_data["channels"]) != COAT_CHANNELS or set(coat_data["members"]) != members:
                raise ValueError("코팅 인덱스의 프레임 범위 또는 채널이 PBR 아틀라스와 다르다.")
            self.coat_folder = index_path.parent
            self.coat_members = coat_data["members"]
        if self.surface and self.paged:
            raise ValueError("표면 시험본은 방향별 페이지를 사용한다.")

    def direction(self, motion, direction):
        relative = self.data["motions"][motion][direction]
        path = self.source.parent / relative
        if relative not in self.records:
            self.records[relative] = self._read_direction(relative, path)
            if len(self.records) > self.max_records:
                self.records.popitem(last=False)
        self.records.move_to_end(relative)
        data = self.records[relative]
        spaces = self.data.get("part_spaces", {}).get(motion, {})
        if spaces:
            clip = data["clip"]
            parts = {name: dict(spec, space=spaces[name]) if name in spaces else spec
                     for name, spec in clip["parts"].items()}
            data = dict(data, clip=dict(clip, parts=parts))
        return path, data

    def _read_direction(self, relative, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if self.coat_members:
            coat_path = (self.coat_folder / self.coat_members[relative]).resolve()
            if not coat_path.is_relative_to(self.coat_folder):
                raise ValueError("코팅 프레임이 코팅 폴더 밖에 있다.")
            coat = json.loads(coat_path.read_text(encoding="utf-8"))
            page = coat["page"]
            texture = (coat_path.parent / page["file"]).resolve()
            if not texture.is_relative_to(self.coat_folder):
                raise ValueError("코팅 페이지가 코팅 폴더 밖에 있다.")
            data["pages"]["coat"] = [dict(page, file=str(texture))]
            data["frames"]["coat"] = coat["frames"]
            for part, spec in data["clip"]["parts"].items():
                for frame, tile in zip(spec["frames"], coat["parts"][part], strict=True):
                    frame["coat"] = tile
        return data

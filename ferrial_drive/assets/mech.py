"""분리 시트를 유지하는 메카 합성 규격. 게임과 제작 도구가 함께 읽는다."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import re

from .sprites import SpriteClip, SpriteSheet, read_json


@dataclass(frozen=True)
class MechBundle:
    asset_id: str
    sheets: dict
    sheet_paths: dict
    masks: dict
    rows: dict
    clips: dict
    layer_rows: dict

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        return cls.from_data(read_json(path), path.parent)

    @classmethod
    def from_data(cls, data, base):
        try:
            if data.get("version") != 1 or data.get("type") != "mech":
                raise ValueError("지원하지 않는 메카 합성 규격")
            if not isinstance(data["asset_id"], str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", data["asset_id"]):
                raise ValueError("메카 에셋 ID가 필요하다.")
            sheets, paths, masks = {}, {}, {}
            for key, row in data["layers"].items():
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                    raise ValueError("출력 단위 이름 오류")
                paths[key] = (Path(base) / row["sheet"]).resolve()
                sheets[key] = SpriteSheet.load(paths[key])
                if row.get("energy_mask"):
                    mask = key + ":energy"
                    paths[mask] = (Path(base) / row["energy_mask"]).resolve()
                    sheets[mask] = SpriteSheet.load(paths[mask])
                    masks[key] = mask
            if "body" not in sheets or not data["clips"]:
                raise ValueError("본체 시트와 사용할 동작이 필요하다.")
            clips = {}
            owners = set(data["layers"])
            for name, row in data["clips"].items():
                source = row["source_clip"]
                reference = sheets["body"].clips[source]
                fps = row["fps"]
                frames = row["source_frames"]
                if (not isinstance(name, str) or not name or type(fps) not in (int, float)
                        or not isfinite(fps) or not 0 < fps <= 240
                        or len(frames) != len(reference.frames) or any(type(frame) is not int or frame < 0 for frame in frames)
                        or len(set(frames)) != len(frames)):
                    raise ValueError("메카 동작·FPS·원본 프레임 오류")
                for sheet in sheets.values():
                    clip = sheet.clips[source]
                    layout = lambda value: [(frame.rect[2:], frame.pivot) for frame in value.frames]
                    if clip.fps != reference.fps or layout(clip) != layout(reference):
                        raise ValueError("메카 색상/마스크의 FPS·프레임 크기·기준점 불일치")
                for order in [row["order"], *row.get("order_overrides", {}).values()]:
                    if len(order) != len(owners) or set(order) != owners:
                        raise ValueError("메카 순서는 각 출력 단위를 한 번 포함해야 한다.")
                for frame in row.get("order_overrides", {}):
                    if str(int(frame)) != frame or int(frame) not in frames:
                        raise ValueError("메카 순서 예외의 원본 프레임 오류")
                clips[name] = SpriteClip(float(fps), reference.frames)
            return cls(data["asset_id"], sheets, paths, masks, data["clips"], clips, data["layers"])
        except (KeyError, TypeError, AttributeError, IndexError) as error:
            raise ValueError("메카 합성 메타데이터의 필수 항목·형식 오류") from error

    def order(self, clip_name, frame_index):
        row = self.rows[clip_name]
        frame = row["source_frames"][frame_index]
        return row.get("order_overrides", {}).get(str(frame), row["order"])

    @property
    def dependencies(self):
        return tuple(dict.fromkeys([*self.sheet_paths.values(), *(sheet.image_path for sheet in self.sheets.values())]))

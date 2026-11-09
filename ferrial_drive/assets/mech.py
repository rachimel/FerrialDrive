"""분리 시트를 유지하는 메카 합성 규격. 게임과 제작 도구가 함께 읽는다."""

from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
import re

from .sprites import SpriteClip, SpriteSheet, read_json


def valid_part_id(value):
    return (isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value) is not None
            and re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", value, re.IGNORECASE) is None)


@dataclass(frozen=True)
class MechBundle:
    asset_id: str
    sheets: dict
    sheet_paths: dict
    masks: dict
    rows: dict
    clips: dict
    layer_rows: dict
    variants: dict
    _checked: set = field(default_factory=set, repr=False, compare=False)

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        return cls.from_data(read_json(path), path.parent)

    @classmethod
    def from_data(cls, data, base):
        try:
            if data.get("version") not in (1, 2) or data.get("type") != "mech":
                raise ValueError("지원하지 않는 메카 합성 규격")
            if not isinstance(data["asset_id"], str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", data["asset_id"]):
                raise ValueError("메카 에셋 ID가 필요하다.")
            sheets, paths, masks, variants = {}, {}, {}, {}
            if len({key.casefold() for key in data["layers"]}) != len(data["layers"]):
                raise ValueError("대소문자만 다른 파츠 ID는 함께 사용할 수 없다.")
            def add_variant(key, value, parent):
                paths[key] = (Path(base) / (value.get("sheet") or parent["sheet"])).resolve()
                sheets[key] = SpriteSheet.load(paths[key])
                mask_path = value.get("energy_mask") or (parent.get("energy_mask") if not value.get("sheet") else "")
                if mask_path:
                    mask = key + ":energy"
                    paths[mask] = (Path(base) / mask_path).resolve()
                    sheets[mask] = SpriteSheet.load(paths[mask])
                    masks[key] = mask
                if type(value.get("enabled", True)) is not bool or not isinstance(value.get("clip", ""), str):
                    raise ValueError("파츠 상태의 표시 여부·클립 오류")
                variants[key] = {"enabled": value.get("enabled", True) if ":" in key else True,
                                 "clip": value.get("clip") or parent.get("clip", "")}
            for key, row in data["layers"].items():
                if not valid_part_id(key):
                    raise ValueError("출력 단위 이름 오류")
                add_variant(key, row, row)
                if len({state.casefold() for state in row.get("states", {})}) != len(row.get("states", {})):
                    raise ValueError("대소문자만 다른 상태 ID는 함께 사용할 수 없다.")
                for state, value in row.get("states", {}).items():
                    if not valid_part_id(state) or state.casefold() == "base":
                        raise ValueError("파츠 상태 ID 오류")
                    add_variant(key + ":" + state, value, row)
                default = row.get("default_state", "base")
                if default != "base" and default not in row.get("states", {}):
                    raise ValueError("파츠 기본 상태 참조 오류")
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
                for order in [row["order"], *row.get("order_overrides", {}).values()]:
                    if len(order) != len(owners) or set(order) != owners:
                        raise ValueError("메카 순서는 각 출력 단위를 한 번 포함해야 한다.")
                for frame in row.get("order_overrides", {}):
                    if str(int(frame)) != frame or int(frame) not in frames:
                        raise ValueError("메카 순서 예외의 원본 프레임 오류")
                clips[name] = SpriteClip(float(fps), reference.frames)
            result = cls(data["asset_id"], sheets, paths, masks, data["clips"], clips, data["layers"], variants)
            for name in clips:
                result.selection(name)
            return result
        except (KeyError, TypeError, AttributeError, IndexError) as error:
            raise ValueError("메카 합성 메타데이터의 필수 항목·형식 오류") from error

    def order(self, clip_name, frame_index):
        row = self.rows[clip_name]
        frame = row["source_frames"][frame_index]
        return row.get("order_overrides", {}).get(str(frame), row["order"])

    def selection(self, clip_name, part_states=None, part_visibility=None):
        """파츠 상태는 동작과 분리해 선택하며 같은 프레임 좌표 규약을 검증한다."""
        row = self.rows[clip_name]
        choices = {**row.get("part_states", {}), **(part_states or {})}
        if any(key not in self.layer_rows for key in choices):
            raise ValueError("알 수 없는 파츠 상태 참조")
        source, result = row["source_clip"], {}
        reference = self.sheets["body"].clips[source]
        for owner, part in self.layer_rows.items():
            state = choices.get(owner, part.get("default_state", "base"))
            key = owner if state == "base" else owner + ":" + state
            if key not in self.variants:
                raise ValueError(f"파츠 상태를 찾을 수 없다: {owner}/{state}")
            variant = self.variants[key]
            enabled = (part_visibility or {}).get(owner, part.get("enabled", True))
            if not enabled or not variant["enabled"]:
                continue
            clip = variant["clip"] + "/" + source.rsplit("/", 1)[-1] if variant["clip"] else source
            identity = (clip_name, key, clip)
            if identity not in self._checked:
                for sheet_key in (key, self.masks.get(key)):
                    if sheet_key is None:
                        continue
                    candidate = self.sheets[sheet_key].clips.get(clip)
                    layout = lambda value: [(frame.rect[2:], frame.pivot) for frame in value.frames]
                    if candidate is None or candidate.fps != reference.fps or layout(candidate) != layout(reference):
                        raise ValueError(f"파츠 상태의 동작·FPS·프레임·기준점 불일치: {owner}/{state}")
                self._checked.add(identity)
            result[owner] = (key, clip)
        return result

    @property
    def dependencies(self):
        return tuple(dict.fromkeys([*self.sheet_paths.values(), *(sheet.image_path for sheet in self.sheets.values())]))

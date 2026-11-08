"""SSheetCutil v1 규격의 프레임 순서·FPS·피봇 조립. 본체/그림자를 함께 편집한다."""

from copy import deepcopy
import json
from math import isfinite
import os
from pathlib import Path
import shutil
from uuid import uuid4

from ferrial_drive.assets import AssetDefinition
from ferrial_drive.assets.catalog import read_document
from ferrial_drive.assets.sprites import SpriteBundle, SpriteSheet


class SpriteAssembly:
    def __init__(self, definition, *, image_size=None):
        document = read_document(definition)
        self.definition = definition
        self.layers = {}
        self.images = {}
        self.bundle = None
        if definition.kind == "bundle":
            self.bundle = json.loads(definition.source.read_text(encoding="utf-8-sig"))
        for layer, sheet in document.sheets.items():
            self.images[layer] = sheet.image_path
            metadata = definition.source.parent / self.bundle[layer] if self.bundle else definition.source
            self.layers[layer] = json.loads(metadata.read_text(encoding="utf-8-sig"))
        if not self.layers:
            if image_size is None:
                raise ValueError("일반 이미지는 실제 로딩한 크기가 필요하다.")
            width, height = image_size
            self.images["body"] = definition.source
            self.layers["body"] = {"version": 1, "coordinates": "bottom-left",
                "image": {"path": "", "size": [width, height]}, "event_bindings": {},
                "animations": [{"name": "image", "fps": 1,
                    "frames": [{"rect": [0, 0, width, height], "pivot": [width / 2, 0]}]}]}
        self.dirty = False

    @property
    def names(self):
        return [row["name"] for row in self.layers["body"]["animations"]]

    def row(self, name):
        return deepcopy(next(row for row in self.layers["body"]["animations"] if row["name"] == name))

    def apply(self, source_name, name, order, fps, pivot, *, all_directions=True):
        if not name.strip() or any(separator in name for separator in ("/", "\\")):
            raise ValueError("동작 이름은 경로 구분자 없이 작성한다.")
        order = tuple(order)
        fps = float(fps)
        if not isfinite(fps) or not 0.1 <= fps <= 240:
            raise ValueError("FPS는 0.1~240 범위여야 한다.")
        if not order or any(type(index) is not int for index in order):
            raise ValueError("프레임을 하나 이상 지정한다.")
        if pivot is not None and (len(pivot) != 2 or any(not isfinite(value) for value in pivot)):
            raise ValueError("피봇은 유한한 X·Y 좌표여야 한다.")
        suffix = source_name.rsplit("/", 1)
        prefix = suffix[0] if len(suffix) == 2 else source_name
        selected = [source_name]
        if self.bundle is not None and all_directions and len(suffix) == 2:
            selected = [clip for clip in self.names if clip.startswith(prefix + "/")]
        candidate = deepcopy(self.layers)
        for layer in candidate.values():
            rows = layer["animations"]
            for source in selected:
                row = deepcopy(next(row for row in rows if row["name"] == source))
                if any(index < 0 or index >= len(row["frames"]) for index in order):
                    raise ValueError("프레임 순서가 원본 범위를 벗어났다.")
                row["frames"] = [deepcopy(row["frames"][index]) for index in order]
                for frame in row["frames"]:
                    if pivot is not None:
                        if not 0 <= pivot[0] <= frame["rect"][2] or not 0 <= pivot[1] <= frame["rect"][3]:
                            raise ValueError("피봇이 프레임 영역을 벗어났다.")
                        frame["pivot"] = list(pivot)
                row["fps"] = fps
                row["name"] = name.strip() + ("/" + source.rsplit("/", 1)[1] if "/" in source else "")
                target = next((i for i, entry in enumerate(rows) if entry["name"] == row["name"]), None)
                if target is None:
                    rows.append(row)
                else:
                    rows[target] = row
        self.layers, self.dirty = candidate, True
        if self.bundle is not None:
            for direction, clip in self.bundle["directions"].items():
                if clip in selected:
                    self.bundle["directions"][direction] = name.strip() + ("/" + clip.rsplit("/", 1)[1] if "/" in clip else "")
        return name.strip() + ("/" + suffix[1] if len(suffix) == 2 else "")

    def save(self, destination, *, asset_id):
        AssetDefinition(asset_id, "image", self.definition.source)
        destination = Path(destination).resolve()
        if destination.exists():
            raise ValueError("출력 폴더가 이미 존재한다. 새 폴더를 지정한다.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name("." + destination.name + "." + uuid4().hex)
        temporary.mkdir()
        try:
            for layer, original in self.layers.items():
                data = deepcopy(original)
                image = layer + self.images[layer].suffix.lower()
                shutil.copyfile(self.images[layer], temporary / image)
                data["image"]["path"] = image
                (temporary / f"{layer}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
                SpriteSheet.load(temporary / f"{layer}.json")
            entry = "body.json"
            if self.bundle is not None:
                data = deepcopy(self.bundle)
                data.update(asset_id=asset_id, body="body.json", shadow="shadow.json")
                (temporary / "bundle.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                SpriteBundle.load(temporary / "bundle.json")
                entry = "bundle.json"
            os.rename(temporary, destination)
        finally:
            if temporary.exists():
                assert temporary.resolve().parent == destination.parent
                shutil.rmtree(temporary)
        self.dirty = False
        return destination / entry

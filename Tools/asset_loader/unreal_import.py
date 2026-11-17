"""Unreal 파츠 프레임을 기존 메카 시트·조립 규약으로 변환한다."""
import json
import math
from pathlib import Path
import re

from ferrial_drive.assets.mech import MechBundle, valid_part_id


MAX_SHEET_SIZE = 8192


def check_pivot(pivot, size):
    if (not isinstance(pivot, (list, tuple)) or len(pivot) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= limit
                   for v, limit in zip(pivot, size))):
        raise ValueError("bottom-left 기준점 오류")


def import_render(source, output, *, trim_padding=False):
    try:
        from PIL import Image
    except ModuleNotFoundError as error:
        if error.name != "PIL":
            raise
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "automate/runtime/image/python"))
        from PIL import Image
    source, output = Path(source).resolve(), Path(output).resolve()
    if type(trim_padding) is not bool:
        raise ValueError("trim_padding은 bool이어야 한다.")
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if data.get("type") != "unreal_prerender" or data.get("version") != 1:
        raise ValueError("Unreal 프리렌더 manifest v1이 필요하다.")
    if "shadow_pending" in data:
        raise ValueError("그림자 후처리를 마친 manifest.json을 사용한다.")
    if output.exists():
        raise FileExistsError(output)
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", data["asset_id"]):
        raise ValueError("에셋 ID 오류")
    width, height = data["size"]
    if any(type(v) is not int or not 0 < v <= 8192 for v in (width, height)):
        raise ValueError("이미지 크기 오류")
    pivot = data["pivot"]
    check_pivot(pivot, (width, height))
    layers, clips = data["layers"], data["clips"]
    if "body" not in layers or not layers or not clips or any(not valid_part_id(k) for k in layers):
        raise ValueError("body와 유효한 파츠 ID·클립이 필요하다.")
    if len({k.casefold() for k in layers}) != len(layers):
        raise ValueError("파츠 ID 중복")
    frame_count = sum(len(clip["frames"]) for clip in clips)
    prepared = {key: [] for key in layers}
    energy_prepared, energy_keys = {}, None
    animations, rows, names = [], {}, set()
    y = 0
    for clip in clips:
        name, fps, frames = clip["name"], clip["fps"], clip["frames"]
        if name in names or not isinstance(name, str) or not name:
            raise ValueError("클립 이름 중복·오류")
        names.add(name)
        if type(fps) not in (int, float) or not math.isfinite(fps) or not 0 < fps <= 240 or not 1 <= len(frames) <= 12:
            raise ValueError("FPS 또는 프레임 수 오류")
        clip_pivot = clip.get("pivot", pivot)
        check_pivot(clip_pivot, (width, height))
        order = clip.get("order", list(layers))
        energy_frames = clip.get("energy_frames", [])
        if energy_frames and len(energy_frames) != len(frames):
            raise ValueError("에너지 마스크와 색상 프레임 수가 다르다.")
        keys = set(energy_frames[0]) if energy_frames else set()
        if not keys <= set(layers) or (energy_keys is not None and keys != energy_keys):
            raise ValueError("클립마다 같은 에너지 마스크 파츠가 필요하다.")
        energy_keys = keys
        for key in keys:
            energy_prepared.setdefault(key, [])
        overrides = clip.get("order_overrides", {})
        for candidate in [order, *overrides.values()]:
            if len(candidate) != len(layers) or set(candidate) != set(layers):
                raise ValueError("레이어 순서는 모든 파츠를 한 번씩 포함한다.")
        if any(str(int(k)) != k or not 0 <= int(k) < len(frames) for k in overrides):
            raise ValueError("프레임별 순서 인덱스 오류")
        rects = []
        for i, frame in enumerate(frames):
            if set(frame) != set(layers):
                raise ValueError("모든 프레임에 같은 파츠가 필요하다.")
            for key, relative in frame.items():
                path = (source.parent / relative).resolve()
                if not path.is_relative_to(source.parent):
                    raise ValueError("렌더 묶음 밖의 이미지 참조")
                with Image.open(path) as image:
                    if image.size != (width, height) or image.mode != "RGBA":
                        raise ValueError("RGBA 이미지 크기·채널 불일치: " + str(path))
                    prepared[key].append(image.copy())
            if energy_frames:
                if set(energy_frames[i]) != keys:
                    raise ValueError("프레임마다 같은 에너지 마스크 파츠가 필요하다.")
                for key, relative in energy_frames[i].items():
                    path = (source.parent / relative).resolve()
                    if not path.is_relative_to(source.parent):
                        raise ValueError("렌더 묶음 밖의 에너지 마스크 참조")
                    with Image.open(path) as image:
                        if image.mode != "RGBA" or image.size != (width,height):
                            raise ValueError("에너지 마스크의 RGBA·크기가 다르다.")
                        if image.getchannel("A").tobytes() != prepared[key][-1].getchannel("A").tobytes():
                            raise ValueError("에너지 마스크와 색상 파츠의 실루엣이 다르다.")
                        energy_prepared[key].append(image.copy())
            rects.append({"rect": [0, 0, width, height], "pivot": clip_pivot})
            y += 1
        animations.append({"name": name, "fps": fps, "frames": rects})
        rows[name] = {"source_clip": name, "source_frames": list(range(len(frames))), "fps": fps,
                      "order": order, "order_overrides": overrides, "events": clip.get("events", [])}
    # 모든 입력을 확인한 뒤 출력한다. 소스 이미지와 manifest는 수정하지 않는다.
    if not any(image.getchannel("A").getextrema()[1] for image in prepared["body"]):
        raise ValueError("본체가 모든 프레임에서 투명하다. Unreal 카메라·레이어를 확인한다.")
    if {key.casefold()+"_energy" for key in energy_prepared} & {key.casefold() for key in layers}:
        raise ValueError("에너지 시트 파일명과 색상 파츠 이름이 충돌한다.")
    crop_box = (0, 0, width, height)
    if trim_padding:
        # 모든 방향·파츠에 같은 영역을 적용한다. 기준점과 필터 여백도 보존한다.
        bounds = [image.getchannel("A").getbbox() for images in prepared.values() for image in images]
        bounds = [box for box in bounds if box]
        pivots = [frame["pivot"] for animation in animations for frame in animation["frames"]]
        left = min(min(box[0] for box in bounds), math.floor(min(p[0] for p in pivots)))
        top = min(min(box[1] for box in bounds), math.floor(height - max(p[1] for p in pivots)))
        right = max(max(box[2] for box in bounds), math.ceil(max(p[0] for p in pivots)))
        bottom = max(max(box[3] for box in bounds), math.ceil(height - min(p[1] for p in pivots)))
        crop_box = (max(0, left - 2), max(0, top - 2), min(width, right + 2), min(height, bottom + 2))
        pivot = [pivot[0] - crop_box[0], pivot[1] - (height - crop_box[3])]
        width, height = crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]
        for collection in (prepared, energy_prepared):
            for key, images in collection.items():
                collection[key] = [image.crop(crop_box) for image in images]
    max_columns, max_rows = MAX_SHEET_SIZE // width, MAX_SHEET_SIZE // height
    if not max_columns or not max_rows or not frame_count or frame_count > max_columns * max_rows:
        raise ValueError("프레임이 최대 시트 크기를 넘는다. 묶음을 나눈다.")
    columns = math.ceil(frame_count / max_rows)
    sheet_rows = math.ceil(frame_count / columns)
    index = 0
    for animation in animations:
        for frame in animation["frames"]:
            original = frame["pivot"]
            adjusted = [original[0] - crop_box[0], original[1] - (data["size"][1] - crop_box[3])]
            frame.update(rect=[(index % columns) * width, (index // columns) * height, width, height], pivot=adjusted)
            index += 1
    output.mkdir(parents=True)
    for key, images in {**prepared, **{key+"_energy":images for key,images in energy_prepared.items()}}.items():
        sheet = Image.new("RGBA", (columns * width, sheet_rows * height))
        for i, image in enumerate(images):
            sheet.paste(image, ((i % columns) * width, (sheet_rows - i // columns - 1) * height))
        sheet.save(output / (key + ".png"))
        metadata = {"version": 1, "coordinates": "bottom-left", "image": {"path": key + ".png", "size": list(sheet.size)}, "animations": animations}
        (output / (key + ".json")).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    bundle = {"version": 2, "type": "mech", "asset_id": data["asset_id"], "layers": {
        key: {"sheet": key + ".json", "name": value.get("name", key), "anchor": value.get("anchor", "root")} for key, value in layers.items()}, "clips": rows}
    for key in energy_prepared:
        bundle["layers"][key]["energy_mask"] = key+"_energy.json"
    path = output / "mech.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    MechBundle.load(path)
    (output / "render_provenance.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    packing = {"source_size": data["size"], "source_pivot": data["pivot"],
               "crop_box_top_left": list(crop_box), "frame_size": [width, height], "pivot": pivot,
               "clip_pivots": {a["name"]: a["frames"][0]["pivot"] for a in animations}}
    (output / "packing.json").write_text(json.dumps(packing, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"source": str(path), "layers": list(layers), "clips": list(rows), "frames": y}

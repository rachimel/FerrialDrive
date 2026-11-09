"""메카 합성 정보를 구성하고 색상·마스크 시트를 각각 보관한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from ferrial_drive.assets import AssetDefinition, MechBundle
from ferrial_drive.assets.catalog import AssetDocument
from ferrial_drive.assets.sprites import read_json
from .mech_plan import DIRECTIONS, MOTIONS, validate_plan
from .production import frame_numbers


def build_mech(plan):
    validate_plan(plan, asset_id=plan["asset_id"], source=plan["source"])
    base = Path(plan["source"]).resolve().parent
    layers = {}
    for key, row in plan["layers"].items():
        if not row.get("sheet"):
            if row.get("energy_sheet"):
                raise ValueError("에너지 시트에는 대응하는 색상 시트가 필요하다.")
            continue
        layers[key] = {"sheet": str((base / row["sheet"]).resolve()), "anchor": row["anchor"]}
        if row.get("energy_sheet"):
            layers[key]["energy_mask"] = str((base / row["energy_sheet"]).resolve())
    if "body" not in layers:
        raise ValueError("출력 단위의 분리 시트에서 본체 시트를 연결한다.")
    from ferrial_drive.assets.sprites import SpriteSheet
    body = SpriteSheet.load(layers["body"]["sheet"])
    clips = {}
    for key, _ in MOTIONS:
        motion = plan["motions"][key]
        for direction in DIRECTIONS:
            source = motion["clip"] + "/" + direction
            if source not in body.clips:
                continue
            frames = frame_numbers(motion["frames"] or plan["render"]["frames"])
            clips[key + "/" + direction] = {
                "source_clip": source, "source_frames": frames, "fps": float(plan["render"]["fps"]),
                "order": [layer for layer in motion["orders"][direction] if layer in layers],
                "order_overrides": {str(row["frame"]): [layer for layer in row["order"] if layer in layers]
                                    for row in motion["overrides"] if row["direction"] == direction},
                "events": deepcopy(motion["events"]),
            }
    data = {"version": 1, "type": "mech", "asset_id": plan["asset_id"], "layers": layers, "clips": clips}
    return MechBundle.from_data(data, base)


def mech_document(plan):
    mech = build_mech(plan)
    return AssetDocument(AssetDefinition(plan["asset_id"], "mech", plan["source"]), mech.sheets,
                         mech.dependencies, mech.asset_id, next(iter(mech.clips)), mech)


def import_mech(plan, mech):
    """내보낸 분리 메카의 연결과 순서를 새 작업본으로 가져온다."""
    for key in plan["layers"]:
        if key in mech.layer_rows:
            plan["layers"][key]["sheet"] = str(mech.sheet_paths[key])
            plan["layers"][key]["energy_sheet"] = str(mech.sheet_paths[mech.masks[key]]) if key in mech.masks else ""
            plan["layers"][key]["anchor"] = mech.layer_rows[key].get("anchor", plan["layers"][key]["anchor"])
    for name, row in mech.rows.items():
        key, direction = name.rsplit("/", 1)
        if key not in plan["motions"] or direction not in DIRECTIONS:
            continue
        motion = plan["motions"][key]
        motion["clip"] = row["source_clip"].rsplit("/", 1)[0]
        motion["frames"] = ",".join(map(str, row["source_frames"]))
        motion["events"] = deepcopy(row.get("events", []))
        missing = [layer for layer in motion["orders"][direction] if layer not in row["order"]]
        motion["orders"][direction] = [*row["order"], *missing]
        for frame, order in row.get("order_overrides", {}).items():
            motion["overrides"].append({"direction": direction, "frame": int(frame), "order": [*order, *missing]})
    first = next(iter(mech.clips.values()))
    width, height = first.frames[0].rect[2:]
    plan["render"].update(fps=f"{first.fps:g}", width=str(width), height=str(height),
                           pivot=",".join(map(str, first.frames[0].pivot)))
    return plan


def copy_mech(mech, destination, *, asset_id=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("이미 존재하는 폴더다. 새 출력 폴더를 지정한다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("." + destination.name + "." + uuid4().hex)
    temporary.mkdir()
    try:
        rows = deepcopy(mech.layer_rows)
        for owner, row in rows.items():
            for key, layer, folder in (("sheet", owner, "color"), ("energy_mask", mech.masks.get(owner), "energy")):
                if layer is None:
                    continue
                directory = temporary / folder
                directory.mkdir(exist_ok=True)
                image = mech.sheets[layer].image_path
                image_name = owner + image.suffix.lower()
                shutil.copyfile(image, directory / image_name)
                data = read_json(mech.sheet_paths[layer])
                data["image"]["path"] = image_name
                (directory / (owner + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                row[key] = folder + "/" + owner + ".json"
        data = {"version": 1, "type": "mech", "asset_id": asset_id or mech.asset_id,
                "layers": rows, "clips": mech.rows}
        (temporary / "mech.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        MechBundle.load(temporary / "mech.json")
        os.rename(temporary, destination)
    finally:
        if temporary.exists():
            assert temporary.resolve().parent == destination.parent and temporary.name.startswith(".")
            shutil.rmtree(temporary)
    return destination / "mech.json"

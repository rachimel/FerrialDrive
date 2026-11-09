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
from .part_model import part_defaults, state_defaults, replace_parts
from .production import frame_numbers


def build_mech(plan):
    validate_plan(plan, asset_id=plan["asset_id"], source=plan["source"])
    base = Path(plan["source"]).resolve().parent
    layers = {}
    def runtime_row(row):
        result = {"name": row["name"], "enabled": row["enabled"], "clip": row["clip"],
                  "sheet": str((base / row["sheet"]).resolve()) if row["sheet"] else ""}
        if row["energy_sheet"]:
            result["energy_mask"] = str((base / row["energy_sheet"]).resolve())
        return result
    for key, row in plan["layers"].items():
        source = row
        if not source["sheet"] and row["default_state"] != "base":
            source = {**row, **row["states"][row["default_state"]]}
        if not source["sheet"]:
            if row["energy_sheet"] or any(state["sheet"] or state["energy_sheet"] for state in row["states"].values()):
                raise ValueError("에너지 시트에는 대응하는 색상 시트가 필요하다.")
            continue
        layers[key] = {**runtime_row(source), "name": row["name"], "enabled": row["enabled"],
                       "anchor": row["anchor"], "clip": row["clip"], "default_state": row["default_state"],
                       "states": {state: runtime_row(value) for state, value in row["states"].items()}}
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
                "part_states": {owner: state for owner, state in motion["part_states"].items() if owner in layers},
            }
    data = {"version": 2, "type": "mech", "asset_id": plan["asset_id"], "layers": layers, "clips": clips}
    return MechBundle.from_data(data, base)


def mech_document(plan):
    mech = build_mech(plan)
    return AssetDocument(AssetDefinition(plan["asset_id"], "mech", plan["source"]), mech.sheets,
                         mech.dependencies, mech.asset_id, next(iter(mech.clips)), mech)


def import_mech(plan, mech):
    """내보낸 분리 메카의 연결과 순서를 새 작업본으로 가져온다."""
    rows = {}
    for key, row in mech.layer_rows.items():
        value = part_defaults(row.get("name", key), row.get("anchor", "root"))
        value.update(sheet=str(mech.sheet_paths[key]),
                     energy_sheet=str(mech.sheet_paths[mech.masks[key]]) if key in mech.masks else "",
                     enabled=row.get("enabled", True), clip=row.get("clip", ""), default_state=row.get("default_state", "base"))
        for state, source in row.get("states", {}).items():
            alias = key + ":" + state
            value["states"][state] = {**state_defaults(source.get("name", state)),
                "sheet": str(mech.sheet_paths[alias]) if source.get("sheet") else "",
                "energy_sheet": str(mech.sheet_paths[mech.masks[alias]]) if source.get("energy_mask") else "",
                "clip": source.get("clip", ""), "enabled": source.get("enabled", True)}
        rows[key] = value
    replace_parts(plan, rows)
    for name, row in mech.rows.items():
        key, direction = name.rsplit("/", 1)
        if key not in plan["motions"] or direction not in DIRECTIONS:
            continue
        motion = plan["motions"][key]
        motion["clip"] = row["source_clip"].rsplit("/", 1)[0]
        motion["frames"] = ",".join(map(str, row["source_frames"]))
        motion["events"] = deepcopy(row.get("events", []))
        motion["part_states"] = deepcopy(row.get("part_states", {}))
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
        def copy_variant(alias, row, owner, state=None):
            for key, layer, folder in (("sheet", alias, "color"), ("energy_mask", mech.masks.get(alias), "energy")):
                if layer is None or not row.get(key):
                    continue
                relative = Path(folder) / owner / state if state else Path(folder) / owner
                directory = temporary / relative.parent
                directory.mkdir(parents=True, exist_ok=True)
                image = mech.sheets[layer].image_path
                image_name = relative.name + image.suffix.lower()
                shutil.copyfile(image, directory / image_name)
                data = read_json(mech.sheet_paths[layer])
                data["image"]["path"] = image_name
                (directory / (relative.name + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                row[key] = relative.as_posix() + ".json"
        for owner, row in rows.items():
            copy_variant(owner, row, owner)
            for state, value in row.get("states", {}).items():
                copy_variant(owner + ":" + state, value, owner, state)
        data = {"version": 2, "type": "mech", "asset_id": asset_id or mech.asset_id,
                "layers": rows, "clips": mech.rows}
        (temporary / "mech.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        MechBundle.load(temporary / "mech.json")
        os.rename(temporary, destination)
    finally:
        if temporary.exists():
            assert temporary.resolve().parent == destination.parent and temporary.name.startswith(".")
            shutil.rmtree(temporary)
    return destination / "mech.json"

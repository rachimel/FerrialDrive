"""저장된 Unreal 본 추적을 총구·접지·검날 화면 좌표로 변환한다. 자세를 수정하지 않는다."""

import argparse
import hashlib
import json
from math import isfinite
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from automate.unreal.blade_tracking import project_to_screen
from automate.unreal.pose_math import add, rotate, sub


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def projected_offset(row, anchor, camera):
    transform = row["extra_bones"][anchor["bone"]]
    point = add(transform["position_cm"], rotate(transform["rotation_xyzw"], anchor["local_cm"]))
    return sub(project_to_screen(point, camera), project_to_screen([0, 0, 0], camera))


def prepare(request):
    destination = (ROOT / request["output"]).resolve()
    if (not any(destination.is_relative_to(ROOT / name) for name in ("data", "output")) or destination.exists()):
        raise ValueError("data 또는 output 아래의 새 출력 폴더가 필요하다.")
    sources = []
    for guard in request["sources"]:
        path = (ROOT / guard["path"]).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != guard["sha256"]:
            raise ValueError("부착 기준 파일의 해시가 다르다: " + str(path))
        sources.append(guard)
    feet, muzzle, blade = {}, {}, {}
    for entry in request["profiles"]:
        profile = read(ROOT / entry["profile"])
        for clip in profile["clips"]:
            tracking = ROOT / entry["tracking_directory"] / ("tracking_" + clip["name"] + ".json")
            data = read(tracking)
            if data["space"] != "skeletal_component_cm" or data["source_fps"] != 12:
                raise ValueError("Unreal component cm / 12 FPS 추적이 필요하다.")
            if abs(data["duration_seconds"] - clip["frames"] / 12) > 1e-7:
                raise ValueError("동작과 본 추적의 길이가 다르다.")
            times = [row["time_seconds"] for row in data["samples"]]
            if len(times) < 2 or abs(times[0]) > 1e-9 or any(a >= b for a, b in zip(times, times[1:])):
                raise ValueError("시간 순서의 끝점 포함 추적이 필요하다.")
            sources.append({"path": tracking.relative_to(ROOT).as_posix(),
                            "sha256": hashlib.sha256(tracking.read_bytes()).hexdigest()})
            for direction, camera in profile["cameras"].items():
                camera = {**camera, "size": profile["scene_template"]["size"]}
                name = clip["name"] + "/" + direction
                ground_samples, muzzle_samples, blade_samples = [], [], []
                for row in data["samples"]:
                    ground_samples.append({key: projected_offset(row, anchor, camera)
                                           for key, anchor in request["ground_anchors"].items()})
                    muzzle_samples.append([row["time_seconds"], *projected_offset(row, request["muzzle"], camera)])
                    if clip["name"] in request["blade_clips"]:
                        blade_samples.append({"time_seconds": row["time_seconds"],
                            **{key: projected_offset(row, anchor, camera) for key, anchor in request["blade"].items()}})
                feet[name] = {"sample_hz": data["sample_hz"], "duration_seconds": data["duration_seconds"],
                              "samples": ground_samples}
                muzzle[name] = muzzle_samples
                if blade_samples:
                    blade[name] = blade_samples
                alias = request.get("aliases", {}).get(clip["name"])
                if alias:
                    alias += "/" + direction
                    feet[alias], muzzle[alias] = feet[name], muzzle[name]
                    if blade_samples:
                        blade[alias] = blade_samples
    for rows in muzzle.values():
        if any(not all(isfinite(value) for value in row) for row in rows):
            raise ValueError("총구 좌표에 유한하지 않은 값이 있다.")
    destination.mkdir(parents=True)
    documents = {
        "ground_anchors.json": {"version": 1, "space": "render_pixel_offset_from_root_top_left",
                                 "anchors": request["ground_anchors"], "clips": feet},
        "muzzle_tracks.json": {"version": 1, "space": "root_relative_top_left_px", "tracks": muzzle},
        "blade_trajectory.json": {"version": 1, "type": "sword_blade_projection", "clips": blade},
        "provenance.json": {"sources": sources, "request": request,
                            "method": "native_component_bone_transform_then_orthographic_projection",
                            "clip_counts": {"ground": len(feet), "muzzle": len(muzzle), "blade": len(blade)}}}
    for filename, document in documents.items():
        (destination / filename).write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"output": str(destination), "clips": len(feet), "blade_clips": len(blade)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(read(args.request)), ensure_ascii=False))

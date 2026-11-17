"""기존 동작을 보존한 상·하체 시선 추종 표본과 Unreal 제작 요청을 준비한다."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automate.unreal.pose_math import forward_pose, from_euler, inverse, qmul, rotate, sub, to_euler
from automate.unreal.animation_clip import sample_controls
from ferrial_drive.combat.aim_follow import AimFollow, AimFollowSettings


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def aim_controls(plan, base_controls, upper_yaw_degrees, lower_yaw_degrees):
    """기존 로컬 자세를 보존하고 Root·허리 회전으로 월드 조준을 분리한다."""
    controls = deepcopy(base_controls)
    reference = forward_pose(plan, base_controls)
    parents = {bone["name"]: bone["parent"] for bone in plan["bones"]}
    root_rotation = qmul(from_euler([0, lower_yaw_degrees, 0]), reference["Root"][1])
    controls.setdefault("Root", {})["rotation_delta_deg"] = to_euler(root_rotation)
    turned = forward_pose(plan, controls)
    upper_rotation = qmul(from_euler([0, upper_yaw_degrees, 0]), reference["waist"][1])
    local_rotation = qmul(inverse(turned[parents["waist"]][1]), upper_rotation)
    controls.setdefault("waist", {})["rotation_delta_deg"] = to_euler(local_rotation)
    return controls


def rigid_attachment(plan, base_controls, bone, driver):
    reference = forward_pose(plan, base_controls)
    position, rotation = reference[bone]
    driver_position, driver_rotation = reference[driver]
    return {"bone": bone, "driver": driver,
            "offset_cm": rotate(inverse(driver_rotation), sub(position, driver_position)),
            "local_rotation_quat": qmul(inverse(driver_rotation), rotation)}


def local_attachments(plan, base_controls, attachments):
    """첫 자세의 월드 파지를 고정 로컬 변환으로 바꿔 클립 경계 회전을 보존한다."""
    reference = forward_pose(plan, base_controls)
    result = deepcopy(attachments)
    for item in result:
        if "local_rotation_quat" not in item:
            item["local_rotation_quat"] = (qmul(inverse(reference[item["driver"]][1]),
                from_euler(item["world_rotation_deg"])) if "world_rotation_deg" in item
                else [0, 0, 0, 1])
        item.pop("world_rotation_deg", None)
    return result


def motion_sequence(request, baseline, frame_count):
    """연속 구간의 원본 동작을 읽는다. 기존 요청은 첫 자세 고정을 유지한다."""
    sequence, sources, next_frame = [], {}, 0
    for row in request.get("motion_sequence", []):
        start, count = row["start_frame"], row["frame_count"]
        if (type(start) is not int or type(count) is not int or start != next_frame or count <= 0
                or type(row.get("loop", False)) is not bool):
            raise ValueError("원본 동작 구간은 0부터 빈틈 없이 이어지는 정수 프레임이어야 한다.")
        source = sources.setdefault(row["request"], read(row["request"]))
        if (source["source_mesh"] != baseline["source_mesh"] or source.get("fps", 12) != 12
                or source["poses"][0]["frame"] != 0
                or source["poses"][-1]["frame"] != source["frame_count"]
                or (not row.get("loop") and count > source["frame_count"])):
            raise ValueError("같은 메시의 12fps 원본 동작과 유효한 재생 길이가 필요하다.")
        if row.get("loop") and source["poses"][0]["controls"] != source["poses"][-1]["controls"]:
            raise ValueError("반복할 원본 동작의 시작·끝 자세가 다르다.")
        sequence.append((row, source))
        next_frame += count
    if sequence and next_frame != frame_count:
        raise ValueError("원본 동작 구간의 총 길이가 검토 프레임 수와 달라서는 안 된다.")
    return sequence, sources


def motion_controls(sequence, frame, fallback):
    if not sequence:
        return fallback
    row, source = next(((row, source) for row, source in reversed(sequence)
                        if row["start_frame"] <= frame), sequence[0])
    local_frame = frame - row["start_frame"]
    if row.get("loop"):
        local_frame %= source["frame_count"]
    return sample_controls(source["poses"], min(local_frame, source["frame_count"]))


def split_body(plan, groups=None):
    """허리 하위 본에 속한 body 부품만 상체로 분리한다. 기존 손·무장은 유지한다."""
    parents = {bone["name"]: bone["parent"] for bone in plan["bones"]}
    parts = {part["id"]: part for part in plan["parts"]}
    if groups is None:
        # 새 스커트 부품처럼 ID가 바뀐 작업본은 현행 본 연결에서 목록을 만든다.
        groups = {"body": []}
        separate = {"head": "head", "hand_l": "left_hand", "hand_r": "right_hand",
                    "weapon_gun": "gun", "weapon_sword": "sword", "scabbard": "scabbard",
                    "slot_l": "left_slot", "slot_r": "right_slot"}
        for part in plan["parts"]:
            bone = part["bone"]
            while bone not in separate and bone in parents:
                bone = parents[bone]
            groups.setdefault(separate.get(bone, "body"), []).append(part["id"])
    result = {key: list(value) for key, value in groups.items() if key != "body"}
    result.update(upper_body=[], lower_body=[])
    for part_id in groups["body"]:
        bone = parts[part_id]["bone"]
        ancestry = []
        while bone and bone != "Root":
            if bone in ancestry:
                raise ValueError("골격 부모가 순환한다.")
            ancestry.append(bone)
            bone = parents[bone]
        result["upper_body" if "waist" in ancestry else "lower_body"].append(part_id)
    if not result["upper_body"] or not result["lower_body"]:
        raise ValueError("상·하체에 각각 body 부품이 필요하다.")
    return result


def prepare(request):
    workspace = (ROOT / request["workspace"]).resolve()
    if not workspace.is_relative_to(ROOT / "automate/workspace"):
        raise ValueError("새 automate 작업본이 필요하다.")
    if (workspace / "batch.json").exists():
        raise FileExistsError(workspace / "batch.json")
    workspace.mkdir(parents=True, exist_ok=True)
    plan, baseline = read(request["rig_plan"]), read(request["baseline_request"])
    settings = AimFollowSettings(**request["follow"])
    follow = AimFollow(settings)
    frame_count = request["frame_count"]
    if type(frame_count) is not int or frame_count % 12 or not 12 <= frame_count <= 384:
        raise ValueError("검토 동작은 12프레임 단위, 최대 384프레임이다.")
    targets = request["targets"]
    times = [row["seconds"] for row in targets]
    if not times or times[0] != 0 or times != sorted(set(times)):
        raise ValueError("0초부터 정렬된 시선 목표가 필요하다.")
    rows, poses = [], []
    base_controls = baseline["poses"][0]["controls"]
    sequence, sources = motion_sequence(request, baseline, frame_count)
    attachments = [item for item in local_attachments(plan, base_controls, baseline.get("attachments", ()))
                   if item["bone"] not in request.get("attachments", {})]
    attachments.extend(rigid_attachment(plan, base_controls, bone, driver)
                       for bone, driver in request.get("attachments", {}).items())
    target_index = 0
    for sample in range(frame_count * 10 + 1):
        seconds = sample / 120
        if sample:
            follow.update(1 / 120, targets[target_index]["yaw_degrees"])
        # 이 시각에 들어온 입력은 이후 구간에 적용한다.
        while target_index + 1 < len(targets) and times[target_index + 1] <= seconds + 1e-9:
            target_index += 1
        rows.append({"seconds": seconds, "target_yaw_degrees": targets[target_index]["yaw_degrees"],
                     "upper_yaw_degrees": follow.upper_yaw_degrees,
                     "lower_yaw_degrees": follow.lower_yaw_degrees,
                     "relative_yaw_degrees": follow.relative_yaw_degrees,
                     "lower_following": follow.lower_following})
        poses.append({"frame": sample / 10, "controls": aim_controls(
            plan, motion_controls(sequence, sample / 10, base_controls),
            follow.upper_yaw_degrees, follow.lower_yaw_degrees)})
    # Euler의 등가 360도 표기가 프레임 사이 역회전으로 이어지지 않게 한다.
    previous = {}
    for pose in poses:
        for bone, control in pose["controls"].items():
            if "rotation_delta_deg" not in control:
                continue
            angles = control["rotation_delta_deg"]
            if bone in previous:
                angles = [value + 360 * round((old - value) / 360) for value, old in zip(angles, previous[bone])]
                control["rotation_delta_deg"] = angles
            previous[bone] = angles
    relative_workspace = workspace.relative_to(ROOT).as_posix()
    tracking_workspace = (Path("Tools/unreal_pipeline/workspace")
                          / workspace.relative_to(ROOT / "automate/workspace")).as_posix()
    clips = []
    for index, start in enumerate(range(0, frame_count, 12)):
        clip = deepcopy(baseline)
        clip.pop("scene", None)
        clip.pop("inspect_only", None)
        name = f"aim_turn_{index:02d}"
        clip.update(animation_asset=f"{request['asset_root']}/{name}/A_{name}",
                    frame_count=12, fps=12, loop=False, bake_substeps=10,
                    attachments=attachments,
                    report=f"{relative_workspace}/{name}_native.json")
        clip["poses"] = [{"frame": pose["frame"] - start, "controls": pose["controls"]}
                         for pose in poses[start * 10:(start + 12) * 10 + 1]]
        if clip.get("tracking"):
            clip["tracking"]["output"] = f"{tracking_workspace}/{name}_tracking.json"
            clip["tracking"]["extra_bones"] = ["Root"] + [bone["name"] for bone in plan["bones"]]
        clips.append(clip)
        (workspace / f"{name}.json").write_text(json.dumps(clip, indent=2), encoding="utf-8")
    batch = {"operation": "animation_clip", "clips": clips, "report": f"{relative_workspace}/batch_native.json"}
    (workspace / "batch.json").write_text(json.dumps(batch, indent=2), encoding="utf-8")
    (workspace / "samples.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (workspace / "groups.json").write_text(json.dumps(split_body(plan), indent=2), encoding="utf-8")
    hashes = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
              for path in dict.fromkeys([request["rig_plan"], request["baseline_request"], *sources])}
    evidence = {"status": "prepared_not_executed", "settings_status": "preview_only",
                "follow": request["follow"], "source_sha256": hashes,
                "clips": [clip["animation_asset"] for clip in clips],
                "preserved": ["geometry", "materials", "baseline_local_pose", "attachments"],
                "motion_sequence": request.get("motion_sequence", []),
                "user_visual_approval": False, "discovery": request.get("discovery", {})}
    (workspace / "recipe.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"batch": f"{relative_workspace}/batch.json", "clips": len(clips), "samples": len(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(read(args.request)), ensure_ascii=False))


if __name__ == "__main__":
    main()

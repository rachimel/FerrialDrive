"""기준 포즈와 월드 목표 JSON을 공통 Unreal 애니메이션 요청으로 변환한다."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

if __package__:
    from .pose_math import add, align_frame, chain_controls, forward_pose, from_euler, inverse, qmul, rotate, slerp, sub
else:
    from pose_math import add, align_frame, chain_controls, forward_pose, from_euler, inverse, qmul, rotate, slerp, sub

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def blend(a, b, t):
    return [x+(y-x)*t for x, y in zip(a, b)]


def create(recipe):
    frames = [row["frame"] for row in recipe["targets"]]
    if frames != sorted(set(frames)) or frames[0] != 0 or frames[-1] != recipe["frame_count"]:
        raise ValueError("정렬된 시작·끝 목표 프레임이 필요하다.")
    output = (ROOT / recipe["output"]).resolve()
    if not output.is_relative_to(ROOT / "automate/workspace"):
        raise ValueError("포즈 요청은 automate/workspace 안에 저장한다.")
    if output.exists():
        raise FileExistsError(output)
    plan = read(recipe["rig_plan"])
    idle = read(recipe["idle_request"])
    source = idle["poses"][0]["controls"]
    reference = forward_pose(plan, source)
    evaluated = read(recipe["idle_evaluation"])["evaluated"][0]["bones"]
    sword = evaluated["weapon_sword"]
    grip_rotation = qmul(inverse(reference["hand_r"][1]), sword["rotation"])
    old_direction = rotate(sword["rotation"], recipe["blade_axis_local"])
    old_normal = rotate(sword["rotation"], recipe["blade_normal_local"])
    rows = recipe["targets"]
    for row in rows:
        if "weapon_direction" in row:
            row["hand_r_rotation"] = qmul(qmul(align_frame(old_direction, old_normal,
                row["weapon_direction"], row["weapon_normal"]), sword["rotation"]), inverse(grip_rotation))
        else:
            row["hand_r_rotation"] = reference["hand_r"][1]
    substeps = recipe.get("bake_substeps", 1)
    if type(substeps) is not int or not 1 <= substeps <= 10:
        raise ValueError("제작 프레임의 중간 계산 횟수는 1~10 정수여야 한다.")
    linear_targets = set(recipe.get("linear_targets", []))
    generated, metrics = [], []
    for sample in range(recipe["frame_count"] * substeps + 1):
        frame = sample / substeps
        a, b = next((a, b) for a, b in zip(rows, rows[1:]) if a["frame"] <= frame <= b["frame"])
        linear_t = (frame-a["frame"]) / (b["frame"]-a["frame"])
        t = linear_t*linear_t*(3-2*linear_t)
        controls = deepcopy(source)
        for name in set(a.get("body", {})) | set(b.get("body", {})):
            for field in ("rotation_delta_deg", "translation_delta_cm"):
                offset = blend(a.get("body", {}).get(name, {}).get(field, [0, 0, 0]),
                               b.get("body", {}).get(name, {}).get(field, [0, 0, 0]), t)
                controls.setdefault(name, {})[field] = add(source.get(name, {}).get(field, [0, 0, 0]), offset)
        joints, end_targets = {}, {}
        for chain in recipe["chains"]:
            names, end = chain["bones"], chain["bones"][-1]
            target_t = linear_t if end in linear_targets else t
            target = blend(a.get(end, reference[end][0]), b.get(end, reference[end][0]), target_t)
            pole_a = a.get(end+"_pole", reference[names[1]][0])
            pole_b = b.get(end+"_pole", reference[names[1]][0])
            if end == "hand_r":
                rotation = slerp(a["hand_r_rotation"], b["hand_r_rotation"], t)
            else:
                qa = from_euler(a[end+"_rotation_deg"]) if end+"_rotation_deg" in a else reference[end][1]
                qb = from_euler(b[end+"_rotation_deg"]) if end+"_rotation_deg" in b else reference[end][1]
                rotation = slerp(qa, qb, t)
            contact = a.get(end+"_contact_cm")
            contact_local = a.get(end+"_contact_local_cm")
            planted = (contact is not None and contact_local is not None
                       and contact == b.get(end+"_contact_cm")
                       and contact_local == b.get(end+"_contact_local_cm"))
            if planted:
                target = sub(contact, rotate(rotation, contact_local))
            try:
                joints[end] = chain_controls(plan, controls, reference, names, target, blend(pole_a, pole_b, t), rotation)
            except ValueError as error:
                raise ValueError(f"{frame}프레임 {end}: {error}") from error
            end_targets[end] = {"position_cm": target, "rotation_xyzw": rotation, "planted": planted}
            if planted:
                end_targets[end].update(contact_cm=contact, contact_local_cm=contact_local)
        idle_frame = str(int(frame)) if frame.is_integer() else str(frame)
        if idle_frame in recipe.get("idle_frames", {}):
            controls = deepcopy(idle["poses"][recipe["idle_frames"][idle_frame]]["controls"])
        generated.append({"frame": frame, "controls": controls})
        metrics.append({"frame": frame, "joints": joints, "end_targets": end_targets})
    # Euler 표기의 360도 차이는 실제 관절 회전으로 보간하지 않는다.
    previous = {}
    for pose in generated:
        for name, control in pose["controls"].items():
            if "rotation_delta_deg" not in control:
                continue
            value = control["rotation_delta_deg"]
            if name in previous:
                value = [v+360*round((old-v)/360) for v, old in zip(value, previous[name])]
            control["rotation_delta_deg"], previous[name] = value, value
    request = {**deepcopy(recipe["request"]), "poses": generated}
    if substeps > 1:
        request["bake_substeps"] = substeps
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    output.with_suffix(".targets.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return {"request": str(output), "frames": len(generated)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create(json.loads(args.request.read_text(encoding="utf-8-sig"))), ensure_ascii=False))

"""Unreal 기본 자세에서 새 동작 키와 본 추종 파지를 작성한다."""
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def sample_controls(poses, frame):
    """작은 로컬 Euler 변화에만 쓰는 구간별 완만한 보간."""
    left, right = poses[0], poses[-1]
    for a, b in zip(poses, poses[1:]):
        if a["frame"] <= frame <= b["frame"]:
            left, right = a, b
            break
    t = (frame - left["frame"]) / max(1e-9, right["frame"] - left["frame"])
    t = max(0, min(1, t))
    t = t*t*(3 - 2*t)
    controls = {}
    for name in left["controls"].keys() | right["controls"].keys():
        controls[name] = {}
        for key in ("rotation_delta_deg", "translation_delta_cm"):
            a = left["controls"].get(name, {}).get(key, [0, 0, 0])
            b = right["controls"].get(name, {}).get(key, [0, 0, 0])
            controls[name][key] = [x + (y - x)*t for x, y in zip(a, b)]
    return controls


def pack(t):
    return {"translation": [t.translation.x, t.translation.y, t.translation.z],
            "rotation": [t.rotation.x, t.rotation.y, t.rotation.z, t.rotation.w]}


def create(request):
    import unreal
    source = unreal.load_asset(request["source_mesh"])
    if not isinstance(source, unreal.SkeletalMesh):
        raise ValueError("기존 Unreal Skeletal Mesh가 필요하다.")
    destination = request["animation_asset"]
    if not destination.startswith("/Game/MechLab/") or ".." in destination:
        raise ValueError("MechLab의 새 동작 경로가 필요하다.")
    inspect_only = request.get("inspect_only", False)
    if unreal.EditorAssetLibrary.does_asset_exist(destination) and not inspect_only:
        raise FileExistsError(destination)
    count, fps, poses = request["frame_count"], request.get("fps", 12), request["poses"]
    maximum = 4096 if request.get("pose_table") is True else 12
    if fps != 12 or type(count) is not int or not 2 <= count <= maximum or count % 2:
        raise ValueError(f"기본 30fps 압축과 호환되는 12fps, 2~{maximum} 짝수 프레임 길이가 필요하다.")
    substeps = request.get("bake_substeps", 1)
    if type(substeps) is not int or not 1 <= substeps <= 10:
        raise ValueError("제작 프레임의 중간 계산 횟수는 1~10 정수여야 한다.")
    if [p["frame"] for p in poses] != sorted(set(p["frame"] for p in poses)) or poses[0]["frame"] != 0 or poses[-1]["frame"] != count:
        raise ValueError("정렬된 시작/끝 키가 필요하다.")
    if request.get("loop") and poses[0]["controls"] != poses[-1]["controls"]:
        raise ValueError("반복 동작의 시작·끝 자세가 달라서는 안 된다.")
    modifier = unreal.SkeletonModifier()
    modifier.set_skeletal_mesh(source)
    names = [str(n) for n in modifier.get_all_bone_names()]
    parents = {name: str(modifier.get_parent_name(name)) for name in names}
    base = {name: modifier.get_bone_transform(name) for name in names}
    used = {n for pose in poses for n in pose["controls"]}
    if used - set(names):
        raise ValueError("없는 본: " + str(used - set(names)))
    attachments = request.get("attachments", [])
    if len({a["bone"] for a in attachments}) != len(attachments):
        raise ValueError("중복 부착 본")
    for item in attachments:
        if item["bone"] not in names or item["driver"] not in names or names.index(item["driver"]) >= names.index(item["bone"]):
            raise ValueError("부착 대상은 먼저 평가되는 본이어야 한다.")
    sampled, globals_by_frame = [], []
    attachment_local = {}
    contact = None
    if request.get("contact_response") and not inspect_only:
        from contact_response import ContactResponse
        contact = ContactResponse(request["contact_response"], base, parents, poses)
    # 저장된 동작 검사에는 부착 오프셋을 정하는 첫 자세만 필요하다.
    for sample in range(1 if inspect_only else count * substeps + 1):
        frame = sample / substeps
        controls = sample_controls(poses, frame)
        locals_, globals_ = {}, {}
        for name in names:
            t = base[name]
            delta = controls.get(name, {}).get("rotation_delta_deg", [0, 0, 0])
            shift = controls.get(name, {}).get("translation_delta_cm", [0, 0, 0])
            local = unreal.Transform()
            local.translation = t.translation + unreal.Vector(*shift)
            r = t.rotation.rotator()
            local.rotation = unreal.Rotator(pitch=r.pitch+delta[0], yaw=r.yaw+delta[1], roll=r.roll+delta[2]).quaternion()
            local.scale3d = t.scale3d
            parent = globals_.get(parents[name], unreal.Transform())
            world = unreal.MathLibrary.compose_transforms(local, parent)
            for item in attachments:
                if item["bone"] != name:
                    continue
                driver = globals_[item["driver"]]
                if frame == 0:
                    grip = unreal.Transform()
                    grip.translation = unreal.MathLibrary.transform_location(driver, unreal.Vector(*item["offset_cm"]))
                    if "local_rotation_quat" in item:
                        relative = unreal.Transform()
                        relative.translation = unreal.Vector(*item["offset_cm"])
                        relative.rotation = unreal.Quat(*item["local_rotation_quat"])
                        grip = unreal.MathLibrary.compose_transforms(relative, driver)
                    elif "world_rotation_deg" in item:
                        p, y, r = item["world_rotation_deg"]
                        grip.rotation = unreal.Rotator(pitch=p, yaw=y, roll=r).quaternion()
                    else:
                        grip.rotation = driver.rotation
                    attachment_local[name] = unreal.MathLibrary.make_relative_transform(grip, driver)
                world = unreal.MathLibrary.compose_transforms(attachment_local[name], driver)
                local = unreal.MathLibrary.make_relative_transform(world, parent)
            locals_[name], globals_[name] = local, world
        if contact:
            contact.apply(frame, locals_, globals_)
        sampled.append(locals_)
        globals_by_frame.append(globals_)
    if not inspect_only:
        folder, name = destination.rsplit("/", 1)
        factory = unreal.AnimSequenceFactory()
        factory.target_skeleton = source.skeleton
        animation = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.AnimSequence, factory)
        controller = animation.get_editor_property("controller")
        controller.open_bracket("새 동작 키 작성", False)
        controller.set_frame_rate(unreal.FrameRate(60, 1), False)
        controller.set_frame_rate(unreal.FrameRate(fps * substeps, 1), False)
        controller.set_number_of_frames(unreal.FrameNumber(count * substeps), False)
        for bone in names:
            controller.add_bone_curve(bone, False)
            if not controller.set_bone_track_keys(bone, [v[bone].translation for v in sampled],
                                                 [v[bone].rotation for v in sampled], [v[bone].scale3d for v in sampled], False):
                raise RuntimeError("키 작성 실패: " + bone)
        controller.close_bracket(False)
        unreal.EditorAssetLibrary.save_loaded_asset(animation)
    # 저장된 AnimSequence를 다시 읽어 입력 키·본 위치와 비교한다.
    animation = unreal.load_asset(destination)
    if not isinstance(animation, unreal.AnimSequence) or animation.get_editor_property("skeleton") != source.skeleton:
        raise ValueError("검사할 동작과 Skeleton이 일치하지 않는다.")
    evaluated = []
    evaluation_step = 2 if request.get("pose_table") is True else 1
    evaluation_frames = list(range(0, count + 1, evaluation_step))
    for frame in evaluation_frames:
        world = {}
        for bone in names:
            # 압축 대상은 30fps일 수 있으므로 제작 프레임 번호 대신 초로 조회한다.
            local = unreal.AnimationLibrary.get_bone_pose_for_time(animation, bone, frame/fps, False)
            world[bone] = unreal.MathLibrary.compose_transforms(local, world.get(parents[bone], unreal.Transform()))
        evaluated.append(world)
    rows = []
    report_bones = set(request.get("report_bones", names))
    if not report_bones <= set(names):
        raise ValueError("보고할 본이 골격에 없다.")
    for frame, world in zip(evaluation_frames, evaluated):
        row = {"frame": frame, "bones": {bone: pack(value) for bone, value in world.items() if bone in report_bones}}
        row["attachment_position_error_cm"] = {}
        for item in attachments:
            expected = unreal.MathLibrary.compose_transforms(attachment_local[item["bone"]], world[item["driver"]])
            delta = world[item["bone"]].translation - expected.translation
            row["attachment_position_error_cm"][item["bone"]] = math.sqrt(delta.x**2+delta.y**2+delta.z**2)
        rows.append(row)
    result = {"animation": animation.get_path_name(), "source_mesh": source.get_path_name(),
              "skeleton": source.skeleton.get_path_name(), "fps": fps, "frame_count": count,
              "key_pose_frames": [p["frame"] for p in poses], "sample_count": len(evaluation_frames),
              "pose_table": request.get("pose_table", False),
              "bake_sample_hz": fps * substeps, "baked_sample_count": count * substeps + 1,
              "evaluation": "seconds_at_source_fps", "inspect_only": inspect_only,
              "loop": request.get("loop", False), "evaluated": rows, "quality_approval": False}
    result["phase"] = "animation_written"
    if contact:
        result["contact_response"] = contact.report()
    (ROOT / request["report"]).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if request.get("tracking"):
        from blade_tracking import capture
        result["tracking"] = capture(animation, source, modifier, names, parents, count, fps, request["tracking"])
    if request.get("scene"):
        from render_units import prepare
        scene = {**request["scene"], "animation": destination, "frame_count": count}
        prepare(scene)
        result["scene_report"] = scene["report"]
    result["phase"] = "complete"
    (ROOT / request["report"]).write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import unreal
    request = json.loads(Path(os.environ["FD_UNITS_REQUEST"]).read_text(encoding="utf-8-sig"))
    target = ROOT / request["report"]
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if "clips" in request:
            clips = request["clips"]
            if not isinstance(clips, list) or not 1 <= len(clips) <= 32:
                raise ValueError("동작 일괄 작성은 1~32개 요청이 필요하다.")
            if (len({clip["animation_asset"] for clip in clips}) != len(clips)
                    or len({clip["report"] for clip in clips}) != len(clips)
                    or request["report"] in {clip["report"] for clip in clips}):
                raise ValueError("각 동작과 완료 보고는 서로 다른 경로가 필요하다.")
            for clip in clips:
                create(clip)
            target.write_text(json.dumps({"phase": "complete", "clips": [clip["report"] for clip in clips]}, indent=2), encoding="utf-8")
        else:
            create(request)
    except Exception:
        import traceback
        target.with_suffix(".error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    unreal.SystemLibrary.quit_editor()

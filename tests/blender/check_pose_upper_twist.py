"""상박·허벅지 추종과 IK 비틀림 검사

기존 동작 변환, 손발·손가락 추종, 굽힘 방향, 취소, 동작 전환과 재로딩을 검사한다.
--capture는 고정 조건의 전후 6면과 관절 확대 이미지를 남긴다.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
from mathutils import Matrix, Vector
from Tools.pose_tool import addon, scene as engine
from Tools.pose_tool.native import key_all, select_part
from Tools.pose_tool.part_editing import PartEditing
from Tools.pose_tool.profile import default_profile
from check_pose_shoulders_knees import error, record_clips, capture


def maximum(before, after):
    return max(error(matrix, after[name]) for name, matrix in before.items())


def finger_bases(parts):
    return {b.name: b.matrix_basis.copy() for side in ("L", "R") for b in parts.finger_bones(side)}


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    addon.register()
    if args.source:
        source = args.source.resolve()
        bpy.ops.wm.open_mainfile(filepath=str(source))
    else:
        from samples.pose_tool.make_sample import create_sample
        create_sample()
        source = output/"sample_source.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if engine.STATE not in bpy.context.scene:
        engine.prepare(default_profile(), source)
    engine.upgrade_palm_handles()
    engine.upgrade_shoulders()
    parts = PartEditing(initialize=False)
    parts.link_wrists()
    parts.prepare_assemblies()
    before = record_clips(parts.rig)
    scene = bpy.context.scene
    active, frame = engine.state()["active"], scene.frame_current
    # 아직 키를 찍지 않은 현재 파지와 손 목표도 자동 변환 시 보존해야 한다.
    parts.curl_fingers("R", "all", 12)
    parts.translate("hand.L", (.025, .01, .02))
    if "Sword" in engine.state().get("independent_parts", []):
        parts.translate("object:Sword", (.02, -.02, .01))
        dirty_sword = parts.world("object:Sword")
    else:
        dirty_sword = None
    dirty = engine.world_bones(parts.rig)
    fingers = finger_bases(parts)
    changed = engine.upgrade_upper_handles()
    assert maximum(dirty, engine.world_bones(parts.rig)) < .003, "현재 편집 보존"
    if dirty_sword is not None:
        assert error(dirty_sword, parts.world("object:Sword")) < 1e-5, "독립 무기 현재 편집 보존"
    assert all(error(matrix, parts.proxy.pose.bones[name].matrix_basis) < 1e-5 for name, matrix in fingers.items())
    before[active][frame] = dirty
    after = record_clips(parts.rig)
    migration_error = max(maximum(worlds, after[name][f]) for name, frames in before.items() for f, worlds in frames.items())
    assert migration_error < .003, ("기존 동작 보존", migration_error)
    assert engine.upgrade_upper_handles() == []
    print("UPPER_MIGRATION", len(before), migration_error, flush=True)
    clips = engine.state()["clips"]
    if len(clips) > 1:
        # 한 동작을 미방문 상태로 되돌려 새 동작 초기화 경로도 검사한다.
        unseen = clips[-1]
        data = engine.state()
        del data["sessions"][unseen["name"]]
        engine.store(data)
        engine.activate_clip(unseen["name"])
        for f, expected in before[unseen["name"]].items():
            scene.frame_set(f)
            assert maximum(expected, engine.world_bones(parts.rig)) < .003, "미방문 동작 초기화"
        engine.activate_clip(active)
        scene.frame_set(frame)
    addon.configure_scene()
    parts = PartEditing(initialize=False)
    camera = None
    if args.capture:
        camera = bpy.data.objects.new("UpperTwistCamera", bpy.data.cameras.new("UpperTwistCamera"))
        scene.collection.objects.link(camera)
        scene.camera = camera
        camera.data.type = "ORTHO"
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x = scene.render.resolution_y = 640
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_cavity = True
        scene.display.render_aa = "8"
        points = [m.translation for m in engine.world_bones(parts.rig).values()]
        low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        framing = ((low+high)*.5, max(high-low)*1.6)
        capture(parts, output, "before", camera, framing)
    results = []
    for end, limb in engine.state()["profile"]["limbs"].items():
        key, pole = "upper."+end, "pole."+end
        select_part(bpy.context, key)
        assert scene.fd_pose_transform == "rotate"
        assert engine.controls()[end].parent == engine.controls()[key]
        assert engine.controls()[pole].parent == engine.controls()[key]
        parts.set_joint_angle(pole, 65)
        key_all(parts)
        start = parts.world(key)
        for axis in "XYZ":
            old = engine.world_bones(parts.rig)
            locals_before = finger_bases(parts)
            pivot = old[limb["upper"]].translation
            transform = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(25), 4, axis) @ Matrix.Translation(-pivot)
            parts.rotate(key, axis, 25)
            key_all(parts)
            scene.frame_set(scene.frame_current)
            new = engine.world_bones(parts.rig)
            names = [limb[field] for field in ("upper", "lower", "end")]
            if end.startswith("hand."):
                names += [b.name for b in parts.finger_bones(end[-1])]
            follow_error = max(error(transform@old[name], new[name]) for name in names)
            print("UPPER_STEP", end, axis, follow_error, flush=True)
            assert follow_error < .003, ("손발 추종", end, axis, follow_error)
            assert all(error(m, parts.proxy.pose.bones[n].matrix_basis) < 1e-5 for n, m in locals_before.items()), "파지 보존"
            parts.set_world(key, start)
            key_all(parts)
            results.append({"limb": end, "axis": axis, "follow_error": follow_error})
        # 회전 전용 제어점은 관절에서 떨어뜨릴 수 없다.
        try:
            parts.translate(key, (.1, 0, 0))
            raise AssertionError("상박 이동 허용")
        except ValueError:
            pass
        pose = parts.joint_pose(pole)
        old = engine.world_bones(parts.rig)
        angle = abs(parts.joint_angle(pole))
        locals_before = finger_bases(parts)
        origin = old[limb["upper"]].translation
        axis = (old[limb["end"]].translation-origin).normalized()
        expected_joint = origin+Matrix.Rotation(math.radians(40), 3, axis)@(old[limb["lower"]].translation-origin)
        parts.twist_joint(pole, 40)
        key_all(parts)
        scene.frame_set(scene.frame_current)
        new = engine.world_bones(parts.rig)
        twist_error = (new[limb["lower"]].translation-expected_joint).length
        assert twist_error < .003, ("IK 방향", end, twist_error)
        assert error(old[limb["end"]], new[limb["end"]]) < .003, "손발 고정"
        assert abs(abs(parts.joint_angle(pole))-angle) < .12, "굽힘 각도 보존"
        assert all(error(m, parts.proxy.pose.bones[n].matrix_basis) < 1e-5 for n, m in locals_before.items()), "방향 조절 중 파지 보존"
        parts.restore_joint_pose(pole, pose)
        assert maximum(old, engine.world_bones(parts.rig)) < .003, "드래그 취소 복구"
        parts.twist_joint(pole, 30)
        parts.set_joint_angle(pole, 90)
        assert abs(parts.joint_angle(pole)-90) < .12, "방향 변경 후 굽힘"
        parts.rotate(key, "X", 20 if end[-1] == "L" else -20)
        key_all(parts)
    engine.support_pin(True)
    pin_before = parts.joint_pose("pole.hand.R")
    parts.twist_joint("pole.hand.R", 20)
    assert engine.controls()["hand.L"].constraints.get(engine.PREFIX+"Support"), "방향 변경 중 양손 고정 보존"
    parts.restore_joint_pose("pole.hand.R", pin_before)
    saved_main = parts.world("upper.hand.R")
    old_main, old_support = parts.world("hand.R"), parts.world("hand.L")
    parts.rotate("upper.hand.R", "Z", 10)
    delta = parts.world("hand.R") @ old_main.inverted()
    assert error(delta@old_support, parts.world("hand.L")) < .003, "주 팔 회전 중 양손 연동"
    parts.set_world("upper.hand.R", saved_main)
    parts.rotate("upper.hand.L", "Z", 5)
    assert not engine.controls()["hand.L"].constraints.get(engine.PREFIX+"Support"), "보조 팔 회전 시 고정 해제"
    key_all(parts)
    saved = engine.world_bones(parts.rig)
    fingers = finger_bases(parts)
    # 다른 동작을 방문해도 새 제어점 Action과 현재 파지를 되찾는다.
    for clip in engine.state()["clips"]:
        engine.activate_clip(clip["name"])
    engine.activate_clip(active)
    scene.frame_set(frame)
    assert maximum(saved, engine.world_bones(parts.rig)) < .003, "동작 전환"
    work = engine.save_work(output/"work.blend")
    scene.frame_set(frame+1)
    scene.frame_set(frame)
    assert maximum(saved, engine.world_bones(parts.rig)) < .003, "프레임 전환"
    if camera:
        capture(parts, output, "after", camera, framing)
    bpy.ops.wm.open_mainfile(filepath=str(work))
    parts = PartEditing()
    assert maximum(saved, engine.world_bones(parts.rig)) < .003, "재로딩"
    assert all(error(m, parts.proxy.pose.bones[n].matrix_basis) < 1e-5 for n, m in fingers.items()), "재로딩 후 파지"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    report = {"migration_controls": changed, "migration_clips": len(before), "migration_error": migration_error,
              "upper_rotations": results, "twist_limbs": 4, "reloaded": True, "source_preserved": True,
              "screen_input_checked": False}
    (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("POSE_UPPER_TWIST_OK", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", action="store_true")
    run(parser.parse_args(sys.argv[sys.argv.index("--")+1:]))

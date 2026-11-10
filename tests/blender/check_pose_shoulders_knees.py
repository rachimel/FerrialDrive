"""어깨 상하부 연동과 무릎 각도 검사

기존 작업본 변환·어깨 상하부 동시 회전·허벅지 유지·발 추종·저장/재로딩을 검사한다.
--legacy는 하부 어깨 컨트롤로 준비한 동작들의 자세 보존을 확인한다.
--capture는 전후 6면과 양쪽 어깨·무릎 확대 렌더를 남긴다.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Matrix, Quaternion, Vector
from Tools.pose_tool import addon, scene as engine
from Tools.pose_tool.native import key_all, select_part
from Tools.pose_tool.part_editing import PartEditing
from Tools.pose_tool.profile import default_profile


def error(a, b):
    return max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))


def record_clips(rig):
    data = engine.state()
    active, frame = data["active"], bpy.context.scene.frame_current
    result = {}
    for clip in data["clips"]:
        engine.activate_clip(clip["name"])
        result[clip["name"]] = {}
        for f in range(clip["start"], clip["end"]+1):
            bpy.context.scene.frame_set(f)
            result[clip["name"]][f] = engine.world_bones(rig)
    engine.activate_clip(active)
    bpy.context.scene.frame_set(frame)
    return result


def capture(parts, output, label, camera, framing):
    scene = bpy.context.scene
    center, span = framing
    views = (("front", (1, 0, 0)), ("back", (-1, 0, 0)), ("left", (0, 1, 0)),
             ("right", (0, -1, 0)), ("top", (0, 0, 1)), ("bottom", (0, 0, -1)))
    shots = [(name, center, span, Vector(direction)) for name, direction in views]
    worlds = engine.world_bones(parts.rig)
    for side in ("L", "R"):
        shots.append(("knee_"+side, worlds["Shin."+side].translation, span*.5,
                      parts.joint_axis("pole.foot."+side)))
        shots.append(("shoulder_"+side, worlds["ShoulderWingUpper."+side].translation,
                      span*.35, Vector((1, .35 if side == "L" else -.35, .15))))
    for name, target, scale, direction in shots:
        camera.location = target+direction.normalized()*span*2
        camera.rotation_euler = (target-camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.ortho_scale = scale
        scene.render.filepath = str(output/f"{label}_{name}.png")
        bpy.ops.render.render(write_still=True)


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
        if args.legacy:
            # 상하부에 독립적인 원본 동작을 넣어 변환이 이를 지우지 않는지 확인한다.
            rig = bpy.data.objects["PlayerRigidRig"]
            for f in range(31, 55):
                bpy.context.scene.frame_set(f)
                phase = math.sin((f-31)/23*math.pi)
                for stem, angle in (("ShoulderWingUpper", .2), ("ShoulderWingLower", -.15)):
                    bone = rig.pose.bones[stem+".L"]
                    bone.rotation_quaternion = Quaternion((1, 0, 0), angle*phase)
                    engine.key_transform(bone, f)
            bpy.context.scene.frame_set(1)
        source = output/"sample_source.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if engine.STATE not in bpy.context.scene:
        profile = default_profile()
        if args.legacy:
            for side in ("L", "R"):
                profile["body"]["shoulder."+side] = "ShoulderWingLower."+side
        engine.prepare(profile, source)
    engine.upgrade_palm_handles()
    rig, _ = engine.rig_objects()
    before_clips = record_clips(rig)
    changed = engine.upgrade_shoulders()
    after_clips = record_clips(rig)
    migration_error = max(error(world, after_clips[name][f][bone])
                          for name, frames in before_clips.items() for f, worlds in frames.items()
                          for bone, world in worlds.items())
    assert migration_error < .003, ("기존 포즈 변환", migration_error)
    print("SHOULDER_MIGRATION", changed, migration_error, flush=True)
    assert engine.upgrade_shoulders() == []
    addon.configure_scene()
    parts = PartEditing(initialize=False)
    scene = bpy.context.scene
    camera = None
    if args.capture:
        camera = bpy.data.objects.new("ShoulderKneeCheckCamera", bpy.data.cameras.new("ShoulderKneeCheckCamera"))
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
        points = [world.translation for world in engine.world_bones(parts.rig).values()]
        low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        framing = ((low+high)*.5, max(high-low)*1.6)
        capture(parts, output, "before", camera, framing)
    shoulder_results = []
    for side in ("L", "R"):
        key = "shoulder."+side
        assert engine.state()["profile"]["body"][key] == "ShoulderWingUpper."+side
        assert not parts.proxy.pose.bones["ShoulderWingLower."+side].constraints.get(engine.PREFIX+"Body")
        start = parts.world(key)
        for axis in "XYZ":
            before = engine.world_bones(parts.rig)
            pivot = parts.world(key).translation
            transform = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(15), 4, axis) @ Matrix.Translation(-pivot)
            parts.rotate(key, axis, 15)
            key_all(parts)
            scene.frame_set(scene.frame_current)
            after = engine.world_bones(parts.rig)
            maximum = max(error(transform@before[stem+"."+side], after[stem+"."+side])
                          for stem in ("ShoulderWingUpper", "ShoulderWingLower"))
            assert maximum < .003, ("어깨 연동", side, axis, maximum)
            other = "R" if side == "L" else "L"
            assert error(before["ShoulderWingUpper."+other], after["ShoulderWingUpper."+other]) < .003
            shoulder_results.append({"side": side, "axis": axis, "matrix_error": maximum})
            parts.set_world(key, start)
            key_all(parts)
        parts.rotate(key, "X", 12 if side == "L" else -12)
        key_all(parts)
    knee_results = []
    for side in ("L", "R"):
        key = "pole.foot."+side
        select_part(bpy.context, key)
        last = None
        for degrees in (30, 90, 120, 179.9, 0, -15, 0, 60, 60, 15, 90):
            before = engine.world_bones(parts.rig)
            pivot = before["Shin."+side].translation
            transform = (Matrix.Translation(pivot)
                         @ Matrix.Rotation(math.radians(degrees-parts.joint_angle(key)), 4, parts.joint_axis(key))
                         @ Matrix.Translation(-pivot))
            scene.fd_pose_joint_angle = degrees
            assert bpy.ops.fdpose.command(command="joint_angle", target=key) == {"FINISHED"}
            scene.frame_set(scene.frame_current)
            after = engine.world_bones(parts.rig)
            upper_error = error(before["Thigh."+side], after["Thigh."+side])
            foot_error = error(transform@before["Foot."+side], after["Foot."+side])
            angle_error = abs(parts.joint_angle(key)-degrees)
            print("KNEE_STEP", side, degrees, upper_error, foot_error, angle_error, flush=True)
            assert upper_error < .003, ("허벅지 유지", side, degrees, upper_error)
            assert foot_error < .003, ("발 추종", side, degrees, foot_error)
            assert angle_error < .12, ("무릎 각도", side, degrees, angle_error)
            other = "R" if side == "L" else "L"
            assert max(error(before[n+"."+other], after[n+"."+other]) for n in ("Thigh", "Shin", "Foot")) < .003
            assert max(error(before["Hand."+s], after["Hand."+s]) for s in ("L", "R")) < .003
            if degrees == last:
                assert max(error(before[n], after[n]) for n in before) < .00001, ("반복 각도", side, angle_error)
            if degrees == 90:
                inverse = parts.rig.matrix_world.inverted()
                assert (inverse@after["Foot."+side].translation).x < (inverse@pivot).x-.1, "무릎 뒤쪽 굽힘"
            last = degrees
            knee_results.append({"side": side, "degrees": degrees, "thigh_error": upper_error,
                                 "foot_error": foot_error, "angle_error_degrees": angle_error})
        saved = parts.joint_pose(key)
        expected = engine.world_bones(parts.rig)
        parts.set_joint_angle(key, 45)
        parts.restore_joint_pose(key, saved)
        assert max(error(expected[n], m) for n, m in engine.world_bones(parts.rig).items()) < .003
        scene.fd_pose_angle = 5
        assert bpy.ops.fdpose.command(command="joint_bend", target=key) == {"FINISHED"}
        assert abs(parts.joint_angle(key)-95) < .12
        assert bpy.ops.fdpose.command(command="joint_bend", target=key, direction=-1) == {"FINISHED"}
    engine.support_pin(True)
    pose = parts.joint_pose("pole.foot.R")
    parts.set_joint_angle("pole.foot.R", 45)
    assert any(obj.constraints.get(engine.PREFIX+"Support") for obj in engine.controls().values()), "무릎 조절 중 양손 고정 해제"
    parts.restore_joint_pose("pole.foot.R", pose)
    engine.support_pin(False)
    key_all(parts)
    if camera:
        capture(parts, output, "after", camera, framing)
    saved = engine.world_bones(parts.rig)
    frame = scene.frame_current
    work = engine.save_work(output/"work.blend")
    scene.frame_set(frame+1)
    scene.frame_set(frame)
    assert max(error(saved[n], m) for n, m in engine.world_bones(parts.rig).items()) < .003
    bpy.ops.wm.open_mainfile(filepath=str(work))
    assert engine.upgrade_shoulders() == []
    restored, _ = engine.rig_objects()
    assert max(error(saved[n], m) for n, m in engine.world_bones(restored).items()) < .003
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    report = {"shoulder_steps": shoulder_results, "knee_steps": knee_results,
              "migration": {"controls": changed, "clips": len(before_clips),
                            "frames": sum(map(len, before_clips.values())), "max_matrix_error": migration_error},
              "reloaded": True, "source_preserved": True, "screen_input_checked": False}
    (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("POSE_SHOULDERS_KNEES_OK", json.dumps(report["migration"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--capture", action="store_true")
    run(parser.parse_args(sys.argv[sys.argv.index("--")+1:]))

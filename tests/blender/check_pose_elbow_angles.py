"""팔꿈치 각도 편집 검사

상박 유지·손 추종·양팔 굽힘/펴기·드래그 취소용 복구·저장 재로딩을 검사한다.
--capture로 고정 구도의 전후 6면과 좌우 팔 확대를 남긴다.
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
from mathutils import Matrix, Vector
from Tools.pose_tool import addon, scene as engine
from Tools.pose_tool.native import key_all, select_part
from Tools.pose_tool.part_editing import PartEditing
from Tools.pose_tool.profile import default_profile


def matrix_error(a, b):
    return max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))


def capture(parts, output, label, camera, center, span):
    scene = bpy.context.scene
    for name, direction in (("front", (1, 0, 0)), ("back", (-1, 0, 0)),
                            ("left", (0, 1, 0)), ("right", (0, -1, 0)),
                            ("top", (0, 0, 1)), ("bottom", (0, 0, -1))):
        camera.location = center+Vector(direction)*span*2
        camera.rotation_euler = (center-camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.ortho_scale = span
        scene.render.filepath = str(output/f"{label}_{name}.png")
        bpy.ops.render.render(write_still=True)
    worlds = engine.world_bones(parts.rig)
    for side in ("L", "R"):
        key = "pole.hand."+side
        pivot = worlds["Forearm."+side].translation
        axis = parts.joint_axis(key)
        camera.location = pivot+axis*span
        camera.rotation_euler = (pivot-camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.ortho_scale = span*.45
        scene.render.filepath = str(output/f"{label}_elbow_{side}.png")
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
        source = output/"sample_source.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if engine.STATE not in bpy.context.scene:
        engine.prepare(default_profile(), source)
    engine.upgrade_palm_handles()
    addon.configure_scene()
    parts = PartEditing(initialize=False)
    scene = bpy.context.scene
    camera = None
    if args.capture:
        camera = bpy.data.objects.new("ElbowCheckCamera", bpy.data.cameras.new("ElbowCheckCamera"))
        scene.collection.objects.link(camera)
        camera.data.type = "ORTHO"
        scene.camera = camera
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x = scene.render.resolution_y = 640
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.film_transparent = False
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_cavity = True
        scene.display.render_aa = "8"
        points = [world.translation for world in engine.world_bones(parts.rig).values()]
        low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        center, span = (low+high)*.5, max(high-low)*1.5
        capture(parts, output, "before", camera, center, span)
    results = []
    for side in ("L", "R"):
        key = "pole.hand."+side
        other = "R" if side == "L" else "L"
        select_part(bpy.context, key)
        for degrees in (30, 90, 120, 179.9, 0, -30, 0, 60, 60, 15, 90):
            before = engine.world_bones(parts.rig)
            axis = parts.joint_axis(key, before)
            pivot = before["Forearm."+side].translation
            rotation = (Matrix.Translation(pivot)
                        @ Matrix.Rotation(math.radians(degrees-parts.joint_angle(key)), 4, axis)
                        @ Matrix.Translation(-pivot))
            expected_hand = rotation @ before["Hand."+side]
            scene.fd_pose_joint_angle = degrees
            assert bpy.ops.fdpose.command(command="joint_angle", target=key) == {"FINISHED"}
            scene.frame_set(scene.frame_current)
            after = engine.world_bones(parts.rig)
            upper_error = matrix_error(before["UpperArm."+side], after["UpperArm."+side])
            hand_error = matrix_error(expected_hand, after["Hand."+side])
            angle_error = abs(parts.joint_angle(key)-degrees)
            opposite_error = max(matrix_error(before[n+"."+other], after[n+"."+other])
                                 for n in ("UpperArm", "Forearm", "Hand"))
            print("ELBOW_STEP", side, degrees, upper_error, hand_error, angle_error, flush=True)
            assert upper_error < .003, (side, degrees, "상박 이동", upper_error)
            assert hand_error < .003, (side, degrees, "손 추종", hand_error)
            assert angle_error < .12, (side, degrees, "각도 오차", angle_error)
            assert opposite_error < .003, (side, degrees, "반대 팔 이동", opposite_error)
            if args.expect_forward_flexion and degrees == 90:
                inverse = parts.rig.matrix_world.inverted()
                assert (inverse @ after["Hand."+side].translation).x > (inverse @ after["Forearm."+side].translation).x+.1, "앞쪽 굽힘 방향"
            if results and results[-1]["side"] == side and results[-1]["degrees"] == degrees:
                assert max(matrix_error(before[n], after[n]) for n in before) < .00001, "같은 각도 반복 시 자세 누적"
            results.append({"side": side, "degrees": degrees, "upper_matrix_error": upper_error,
                            "hand_matrix_error": hand_error, "angle_error_degrees": angle_error,
                            "opposite_matrix_error": opposite_error})
        scene.fd_pose_angle = 5
        assert bpy.ops.fdpose.command(command="joint_bend", target=key) == {"FINISHED"}
        scene.frame_set(scene.frame_current)
        assert abs(parts.joint_angle(key)-95) < .12
        assert bpy.ops.fdpose.command(command="joint_bend", target=key, direction=-1) == {"FINISHED"}
        key_all(parts)
        saved = parts.joint_pose(key)
        before = engine.world_bones(parts.rig)
        parts.set_joint_angle(key, 45)
        parts.restore_joint_pose(key, saved)
        after = engine.world_bones(parts.rig)
        assert max(matrix_error(before[name], after[name]) for name in before) < .003
        for invalid in (-180, 180, float("nan"), float("inf")):
            try:
                parts.set_joint_angle(key, invalid)
            except ValueError:
                pass
            else:
                raise AssertionError(("범위 밖 각도 허용", invalid))
        # 각도 조절 뒤 손 목표를 직접 움직이는 기존 IK 경로도 계속 사용한다.
        hand = parts.world("hand."+side)
        parts.translate("hand."+side, Vector((.01, 0, 0)))
        key_all(parts)
        scene.frame_set(scene.frame_current)
        limb = engine.state()["profile"]["limbs"]["hand."+side]
        actual = engine.target_matrix(engine.world_bones(parts.rig), parts.rig, "hand."+side, limb)
        assert (actual.translation-parts.world("hand."+side).translation).length < .001
        parts.set_world("hand."+side, hand)
        key_all(parts)
    # 양손 고정을 풀고 한쪽 팔꿈치를 편집해도 반대 팔은 움직이지 않는다.
    engine.support_pin(True)
    pinned = parts.joint_pose("pole.hand.R")
    before = engine.world_bones(parts.rig)
    parts.set_joint_angle("pole.hand.R", 45)
    after = engine.world_bones(parts.rig)
    assert matrix_error(before["Hand.L"], after["Hand.L"]) < .003
    assert not any(o.constraints.get(engine.PREFIX+"Support") for o in engine.controls().values())
    parts.restore_joint_pose("pole.hand.R", pinned)
    assert any(o.constraints.get(engine.PREFIX+"Support") for o in engine.controls().values())
    restored = engine.world_bones(parts.rig)
    assert max(matrix_error(before[n], restored[n]) for n in before) < .003
    engine.support_pin(False)
    if camera:
        capture(parts, output, "after", camera, center, span)
    key_all(parts)
    saved = engine.world_bones(parts.rig)
    frame = scene.frame_current
    work = engine.save_work(output/"work.blend")
    scene.frame_set(frame+1)
    scene.frame_set(frame)
    assert max(matrix_error(saved[n], m) for n, m in engine.world_bones(parts.rig).items()) < .003
    bpy.ops.wm.open_mainfile(filepath=str(work))
    parts = PartEditing(initialize=False)
    reloaded = engine.world_bones(parts.rig)
    assert max(matrix_error(saved[n], reloaded[n]) for n in saved) < .003
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    report = {"steps": results, "source_preserved": True, "reloaded": True,
              "frame_roundtrip": True, "restore_joint_pose": True,
              "screen_input_checked": False, "blender_version": bpy.app.version_string}
    (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("POSE_ELBOW_ANGLES_OK", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--expect-forward-flexion", action="store_true", help="정면 +X인 기본 자세의 양팔 앞쪽 굽힘을 검사한다.")
    run(parser.parse_args(sys.argv[sys.argv.index("--")+1:]))

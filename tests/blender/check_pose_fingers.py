"""주먹 굽힘 방향 검사

양손 네 손가락의 실제 굽힘 방향·일관성·증분 조작·저장 복구를 검사한다.
--capture로 손바닥/측면 확대 이미지를 남긴다.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Matrix, Vector
from Tools.pose_tool import addon, scene as engine
from Tools.pose_tool.part_editing import PartEditing
from Tools.pose_tool.profile import default_profile

FINGERS = ("Index", "Middle", "Ring", "Little")


def finger_geometry(parts, side):
    rig = parts.rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
    hand = rig.matrix_world @ rig.pose.bones["Hand."+side].matrix
    inverse = hand.inverted()
    result = {}
    for finger in FINGERS:
        bones = [rig.pose.bones[finger+joint+"."+side] for joint in ("01", "02", "03")]
        points = [inverse @ rig.matrix_world @ b.head for b in bones]
        points.append(inverse @ rig.matrix_world @ bones[-1].tail)
        result[finger] = {"points": points, "directions": [(b-a).normalized() for a, b in zip(points, points[1:])]}
    return result


def check_shape(opened, closed):
    result = {}
    for finger in FINGERS:
        initial, bent = opened[finger], closed[finger]
        # 기존 무기 파지 계약에서 Hand 로컬 -Z가 손바닥 안쪽이다.
        palm_depth = initial["points"][1].z-bent["points"][1].z
        length = (initial["points"][1]-initial["points"][0]).length
        assert palm_depth > length*.5, (finger, "손등 방향 굽힘", palm_depth)
        dots = [a.dot(b) for a, b in zip(bent["directions"], closed["Middle"]["directions"])]
        assert min(dots) > .999, (finger, "다른 손가락과 굽힘 방향 불일치", dots)
        initial_span = (initial["points"][-1]-initial["points"][0]).length
        closed_span = (bent["points"][-1]-bent["points"][0]).length
        assert closed_span < initial_span*.8, (finger, closed_span, initial_span)
        result[finger] = {"palm_depth": palm_depth, "direction_dots": dots, "tip_span_ratio": closed_span/initial_span}
    return result


def capture(parts, side, pose, output, camera, framing):
    scene = bpy.context.scene
    rig = parts.rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
    hand = rig.matrix_world @ rig.pose.bones["Hand."+side].matrix
    if side not in framing:
        points = [rig.matrix_world @ rig.pose.bones["Hand."+side].head]
        for finger in FINGERS:
            points += [rig.matrix_world @ rig.pose.bones[finger+j+"."+side].head for j in ("01", "02", "03")]
            points.append(rig.matrix_world @ rig.pose.bones[finger+"03."+side].tail)
        center = sum(points, Vector())/len(points)
        span = max((p-center).length for p in points)*2.7
        framing[side] = (center, span)
    center, span = framing[side]
    bones = {"Hand."+side, "WristSwivel."+side} | {bone.name for bone in parts.finger_bones(side)}
    meshes = {obj: obj.hide_render for obj in scene.objects if obj.type == "MESH"}
    try:
        for obj, hidden in meshes.items():
            obj.hide_render = hidden or not (obj.parent_bone in bones or any(group.name in bones for group in obj.vertex_groups))
        for view, local in (("palm", (0, -.2, -1)), ("side", (1, -.15, -.15))):
            backward = (hand.to_3x3() @ Vector(local)).normalized()
            up = -(hand.to_3x3().col[1]).normalized()
            right = up.cross(backward).normalized()
            up = backward.cross(right).normalized()
            camera.matrix_world = Matrix((right, up, backward)).transposed().to_4x4()
            camera.location = center+backward*span*3
            camera.data.ortho_scale = span
            scene.render.filepath = str(output/(side+"_"+pose+"_"+view+".png"))
            bpy.ops.render.render(write_still=True)
    finally:
        for obj, hidden in meshes.items():
            obj.hide_render = hidden


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
    framing = {}
    camera = None
    if args.capture:
        camera = bpy.data.objects.new("FingerCheckCamera", bpy.data.cameras.new("FingerCheckCamera"))
        scene.collection.objects.link(camera)
        camera.data.type = "ORTHO"
        scene.camera = camera
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x, scene.render.resolution_y = 640, 560
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.film_transparent = True
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_cavity = True
        scene.display.render_aa = "8"

    def edit(command, side):
        assert bpy.ops.fdpose.command(command=command, target="hand."+side) == {"FINISHED"}
        scene.frame_set(scene.frame_current)

    report = {}
    for side in ("L", "R"):
        edit("open", side)
        opened = finger_geometry(parts, side)
        if camera:
            capture(parts, side, "open", output, camera, framing)
        edit("fist", side)
        closed = finger_geometry(parts, side)
        (output/(side+"_points.json")).write_text(json.dumps({"open": {k: [list(p) for p in v["points"]] for k, v in opened.items()},
                                                            "fist": {k: [list(p) for p in v["points"]] for k, v in closed.items()}}, indent=2), encoding="utf-8")
        if camera:
            capture(parts, side, "fist", output, camera, framing)
        report[side] = check_shape(opened, closed)
        edit("fist", side)
        repeated = finger_geometry(parts, side)
        assert all((a-b).length < .00001 for finger in FINGERS
                   for a, b in zip(closed[finger]["points"], repeated[finger]["points"]))
        edit("open", side)
        scene.fd_pose_angle = 25
        edit("fingers", side)
        bent = finger_geometry(parts, side)
        for finger in FINGERS:
            assert opened[finger]["points"][1].z > bent[finger]["points"][1].z
            assert min(a.dot(b) for a, b in zip(bent[finger]["directions"], bent["Middle"]["directions"])) > .999
        edit("fist", side)
    saved = {side: finger_geometry(parts, side) for side in ("L", "R")}
    work = engine.save_work(output/"work.blend")
    bpy.ops.wm.open_mainfile(filepath=str(work))
    parts = PartEditing(initialize=False)
    for side in ("L", "R"):
        restored = finger_geometry(parts, side)
        assert all((a-b).length < .00001 for finger in FINGERS
                   for a, b in zip(saved[side][finger]["points"], restored[finger]["points"]))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    report["source_preserved"] = True
    report["reloaded"] = True
    (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("POSE_FINGERS_CHECK_OK", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", action="store_true")
    run(parser.parse_args(sys.argv[sys.argv.index("--")+1:]))

"""손목 연결·파츠 월드 변환·손가락·복제·칼집 정렬·Undo 통합 검사."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Matrix, Vector
from Tools.pose_tool.worker import PoseWorker
from Tools.pose_tool import scene as engine


def error(a, b):
    return max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))


def run(source, output):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    worker = PoseWorker({"source": str(source.resolve()), "work": str(output.resolve()/"work.blend")}, output.resolve())

    def edit(command, **fields):
        worker.execute({"command": command, **fields})
        if worker.dirty:
            engine.key_pose()
            worker.parts.key_current()
        bpy.context.scene.frame_set(bpy.context.scene.frame_current)

    edit("rotate", control="hand.R", axis="Z", degrees=30)
    worlds = engine.world_bones(worker.parts.rig)
    wrist_gap = (worlds["WristSwivel.R"].translation-worlds["Hand.R"].translation).length
    target = bpy.data.objects[engine.PREFIX+"WristFollow.R"].matrix_world
    wrist_angle = worlds["WristSwivel.R"].to_quaternion().rotation_difference(target.to_quaternion()).angle
    assert wrist_gap < .0001, wrist_gap
    assert min(wrist_angle, 6.283185307-wrist_angle) < .002, wrist_angle
    edit("undo")
    gun = bpy.data.objects["Gun"]
    before = gun.matrix_world.copy()
    count = len(worker.history.entries)
    edit("move", control="object:Gun", world=list(before.translation+Vector((.1, 0, 0))), gesture="test_drag")
    edit("move", control="object:Gun", world=list(before.translation+Vector((.2, 0, 0))), gesture="test_drag")
    assert len(worker.history.entries) == count+1
    assert abs(gun.matrix_world.translation.x-before.translation.x-.2) < .0001
    edit("undo")
    assert error(gun.matrix_world, before) < .0001
    edit("translate", control="object:Gun", axis="Y", amount=.15)
    independent = gun.matrix_world.copy()
    edit("translate", control="hand.R", axis="X", amount=.05)
    assert error(gun.matrix_world, independent) < .0001
    edit("undo")
    fingers = {b.name: b.matrix_basis.copy() for b in worker.parts.finger_bones("R", "Index")}
    edit("fingers", side="R", finger="Index", degrees=20)
    assert all(error(worker.parts.proxy.pose.bones[n].matrix_basis, m) > .01 for n, m in fingers.items())
    edit("undo")
    assert all(error(worker.parts.proxy.pose.bones[n].matrix_basis, m) < .0001 for n, m in fingers.items())
    edit("translate", control="object:Scabbard", axis="Z", amount=.2)
    edit("rotate", control="object:Scabbard", axis="Y", degrees=15)
    sword, scabbard = bpy.data.objects["Sword"], bpy.data.objects["Scabbard"]
    sword_before = sword.matrix_world.copy()
    edit("align_sword")
    expected = scabbard.matrix_world @ Matrix(engine.state()["sword_alignment"])
    assert error(sword.matrix_world, expected) < .0001
    assert sword.parent is None and scabbard.parent is None and gun.parent is None
    edit("undo")
    assert error(sword.matrix_world, sword_before) < .0001
    edit("key")
    clips = engine.state()["clips"]
    if len(clips) > 1:
        frame = clips[1]["start"]
        edit("clip", name=clips[1]["name"])
        bpy.context.scene.frame_set(frame-1)
        previous = gun.matrix_world.copy()
        bpy.context.scene.frame_set(frame)
        edit("translate", control="object:Gun", axis="X", amount=.4)
        edit("copy_previous", control="object:Gun")
        assert error(gun.matrix_world, previous) < .0001
    edit("save")
    edit("export", seq=777)
    assert Path(worker.exported).is_file()
    exported = worker.exported
    # 출력은 별도 프로세스이므로 기존 Undo Action과 객체 참조가 유지된다.
    edit("undo")
    assert worker.file_dirty
    worker.render()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    preset = json.loads(Path(exported).read_text(encoding="utf-8"))
    assert set(preset["extra_root_objects"]) == {"Gun", "Sword", "Scabbard"}
    baked = Path(exported).parent.parent/"animations.blend"
    bpy.ops.wm.open_mainfile(filepath=str(baked))
    from Tools.blender_pipeline.render_asset_sample import prepare_saved_scene
    scene, root, _ = prepare_saved_scene(preset)
    assert all(bpy.data.objects[name].parent == root for name in ("Gun", "Sword", "Scabbard"))
    from math import pi
    point = bpy.data.objects["Gun"].matrix_world.translation.copy()
    root.rotation_euler.z = pi/2
    scene.frame_set(scene.frame_current)
    engine.update()
    assert (bpy.data.objects["Gun"].matrix_world.translation-Matrix.Rotation(pi/2, 3, "Z")@point).length < .0001
    report = {"wrist_gap": wrist_gap, "wrist_angle": wrist_angle,
              "undo_after_export": True, "source_unchanged": True, "export": exported, "render_parts_included": True}
    (output/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("POSE_PARTS_CHECK_PASSED", json.dumps(report))


parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
run(args.source, args.output)

"""Blender 포즈 편집 검사

기본 도형 또는 모델에서 파츠·손가락·정렬·복제·저장·출력을 검사한다.
--screen은 실제 Blender 창의 관절 손잡이와 기본 Undo를 추가 검사한다.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Matrix, Vector
from ferrial_drive.diagnostics import TimingRecorder
from Tools.pose_tool import addon, scene as engine
from Tools.pose_tool.native import select_part, key_all
from Tools.pose_tool.part_editing import PartEditing
from Tools.pose_tool.profile import default_profile


def matrix_error(a, b):
    return max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))


def run(args):
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    addon.register()
    if args.source:
        source = args.source.resolve()
        bpy.ops.wm.open_mainfile(filepath=str(source))
    else:
        from samples.pose_tool.make_sample import create_sample
        create_sample()
        source = args.output/"sample_source.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if engine.STATE not in bpy.context.scene:
        metadata_path = source.parent/"clips.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else None
        engine.prepare(default_profile(), source, metadata)
    engine.upgrade_palm_handles()
    addon.configure_scene()
    parts = PartEditing(initialize=False)
    timings = TimingRecorder(enabled=True, session="pose_native")

    def edit(command, **fields):
        result = bpy.ops.fdpose.command(command=command, **fields)
        assert result == {"FINISHED"}, (command, result)
        bpy.context.scene.frame_set(bpy.context.scene.frame_current)

    gun = parts.world("object:Gun")
    for _ in range(10):
        with timings.scope("world_axis_key_and_evaluate"):
            edit("axis", target="object:Gun", axis="X", direction=1)
    assert abs(parts.world("object:Gun").translation.x-gun.translation.x-.5) < .0001
    independent = parts.world("object:Gun")
    bpy.context.scene.fd_pose_transform = "rotate"
    edit("axis", target="hand.R", axis="Y", direction=1)
    assert matrix_error(parts.world("object:Gun"), independent) < .0001
    worlds = engine.world_bones(parts.rig)
    wrist = bpy.data.objects[engine.PREFIX+"WristFollow.R"].matrix_world
    assert worlds["WristSwivel.R"].to_quaternion().rotation_difference(wrist.to_quaternion()).angle < .002
    fists = {}
    def fingertip_distance(side):
        evaluated = parts.rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
        return (evaluated.pose.bones["Middle03."+side].tail-evaluated.pose.bones["Middle01."+side].head).length

    for side in ("L", "R"):
        edit("open", target="hand."+side)
        open_distance = fingertip_distance(side)
        edit("fist", target="hand."+side)
        assert fingertip_distance(side) < open_distance*.8, (side, fingertip_distance(side), open_distance)
        closed = {b.name: b.matrix_basis.copy() for b in parts.finger_bones(side)}
        edit("fist", target="hand."+side)
        assert all(matrix_error(b.matrix_basis, closed[b.name]) < .0001 for b in parts.finger_bones(side))
        assert all(b.rotation_quaternion.angle > .1 for b in parts.finger_bones(side))
        fists[side] = {b.name: round(b.rotation_quaternion.angle, 4) for b in parts.finger_bones(side)}
        edit("open", target="hand."+side)
        assert all(b.rotation_quaternion.angle < .0001 for b in parts.finger_bones(side))
    edit("fist", target="hand.R")
    foot_before = engine.world_bones(parts.rig)["Foot.R"].translation
    joint = parts.joint_position("pole.foot.R")
    limb = engine.state()["profile"]["limbs"]["foot.R"]
    worlds = engine.world_bones(parts.rig)
    origin = worlds[limb["upper"]].translation
    axis = (worlds[limb["end"]].translation-origin).normalized()
    parts.bend_joint("pole.foot.R", origin+Matrix.Rotation(.25, 3, axis)@(joint-origin))
    key_all(parts)
    assert (engine.world_bones(parts.rig)["Foot.R"].translation-foot_before).length < .003
    assert (parts.joint_position("pole.foot.R")-joint).length > .0001
    bpy.context.scene.fd_pose_transform = "translate"
    edit("axis", target="object:Scabbard", axis="Z", direction=1)
    edit("align_sword")
    expected = parts.world("object:Scabbard") @ Matrix(engine.state()["sword_alignment"])
    assert matrix_error(parts.world("object:Sword"), expected) < .0001
    assert all(bpy.data.objects[name].parent is None for name in ("Gun", "Sword", "Scabbard"))
    frame = bpy.context.scene.frame_current
    before = parts.world("object:Gun")
    bpy.context.scene.frame_set(frame+1)
    edit("axis", target="object:Gun", axis="Y", direction=1)
    edit("copy_previous", target="object:Gun")
    assert matrix_error(parts.world("object:Gun"), before) < .0001
    bpy.context.scene.fd_pose_category = "body"
    bpy.context.scene.fd_pose_part = "hand.R"
    select_part(bpy.context, "hand.R")
    work = args.output/"work.blend"
    engine.save_work(work)
    exported = None
    if args.export:
        assert bpy.ops.fdpose.export_clip(directory=str(args.output/"export")) == {"FINISHED"}
        exported = bpy.context.scene.fd_pose_export
        preset = json.loads(Path(exported).read_text(encoding="utf-8"))
        assert preset["frame_size_pixels"] == [240, 240]
        assert set(preset["extra_root_objects"]) == {"Gun", "Sword", "Scabbard"}
        assert bpy.data.filepath == str(work)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    timings.write_json(ROOT/"output/performance"/(args.output.name+".json"))
    report = {"source": str(source), "work": str(work), "fists": fists,
              "source_preserved": True, "exported": exported, "background_checks": True}
    if not args.screen:
        (args.output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("POSE_NATIVE_CHECK_OK", flush=True)
        return
    addon.configure_view()
    stage = 0
    initial = parts.world("hand.R")
    ui_initial = None

    def screen_check():
        nonlocal stage, ui_initial
        try:
            area = next(a for a in bpy.context.window.screen.areas if a.type == "VIEW_3D")
            region = next(r for r in area.regions if r.type == "WINDOW")
            with bpy.context.temp_override(area=area, region=region):
                if stage == 0:
                    bpy.ops.ed.undo_push(message="포즈 검사 시작")
                    edit("axis", target="hand.R", axis="X", direction=1)
                    # Python 타이머 호출은 UI 이벤트의 연산자 Undo push를 실행하지 않는다.
                    bpy.ops.ed.undo_push(message="월드 축 이동")
                    stage += 1
                    return .8
                if stage == 1:
                    assert bpy.ops.ed.undo() == {"FINISHED"}
                    actual = PartEditing(initialize=False).world("hand.R")
                    assert matrix_error(actual, initial) < .0001, matrix_error(actual, initial)
                    report["native_undo"] = True
                    stage += 1
                    return .8
                if stage == 2:
                    addon.configure_view()
                    edit("fist", target="hand.R")
                    stage += 1
                    return 1
                if stage == 3:
                    for target_area in bpy.context.window.screen.areas:
                        target_area.tag_redraw()
                    stage += 1
                    return .5
                if stage == 4:
                    if args.ui_input:
                        click(area.x+area.width-16, bpy.context.window.height-470)
                    stage += 1
                    return .8
                if stage == 5:
                    if args.ui_input:
                        ui_initial = PartEditing(initialize=False).world("hand.R")
                        edit("axis", target="hand.R", axis="X", direction=1)
                        bpy.ops.ed.undo_push(message="키보드 Undo 검사 이동")
                        stage += 1
                        return .8
                    stage = 8
                if stage == 6:
                    actual = PartEditing(initialize=False).world("hand.R")
                    assert abs(actual.translation.x-ui_initial.translation.x-.05) < .0001, actual.translation
                    bpy.context.window.event_simulate(type="Z", value="PRESS", ctrl=True)
                    bpy.context.window.event_simulate(type="Z", value="RELEASE", ctrl=True)
                    stage += 1
                    return .8
                if stage == 7:
                    actual = PartEditing(initialize=False).world("hand.R")
                    assert matrix_error(actual, ui_initial) < .0001, matrix_error(actual, ui_initial)
                    report["keyboard_ctrl_z"] = True
                    stage += 1
                    return .8
                if stage == 8:
                    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
                    bpy.ops.screen.screenshot(filepath=str(args.output/"blender_pose.png"))
                    report["screen"] = True
                    (args.output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    print("POSE_NATIVE_SCREEN_OK", flush=True)
                    if not args.keep_open:
                        bpy.ops.wm.quit_blender()
                    return None
        except Exception:
            (args.output/"failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
            traceback.print_exc()
            if not args.keep_open:
                bpy.ops.wm.quit_blender()
            return None
    bpy.app.timers.register(screen_check, first_interval=2)


def click(x, y):
    for event_type, value in (("MOUSEMOVE", "NOTHING"), ("LEFTMOUSE", "PRESS"), ("LEFTMOUSE", "RELEASE")):
        bpy.context.window.event_simulate(type=event_type, value=value, x=x, y=y)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--screen", action="store_true")
    parser.add_argument("--ui-input", action="store_true", help="1500×1000 창과 --enable-event-simulate 필요")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    run(args)


if __name__ == "__main__":
    main()

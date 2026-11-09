"""Pose Tool의 실제 Blender IK·키·동작 전환·저장·출력 계약 검사."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import bpy
from mathutils import Vector
from samples.pose_tool.make_sample import create_sample
from Tools.pose_tool import scene as tool
from Tools.pose_tool.profile import default_profile


def matrix_error(a, b):
    return max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))


def run():
    with tempfile.TemporaryDirectory(prefix="fd_pose_") as directory:
        folder = Path(directory)
        rig = create_sample()
        source = folder / "source.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        before = tool.world_bones(rig)
        tool.prepare(default_profile(), source)
        after = tool.world_bones(rig)
        initial_error = max(matrix_error(before[n], after[n]) for n in before)
        print("INITIAL_ERROR", initial_error)
        assert initial_error < .002, initial_error
        ctrls = tool.controls()
        foot_before = {side: after[f"Foot.{side}"].translation.copy() for side in ("L", "R")}
        pelvis = ctrls["pelvis"]
        pelvis.location.z -= .1
        tool.update()
        crouched = tool.world_bones(rig)
        foot_error = max((crouched[f"Foot.{s}"].translation-foot_before[s]).length for s in foot_before)
        assert foot_error < .002, foot_error
        hand = ctrls["hand.L"]
        target = hand.matrix_world.translation + Vector((.08, -.05, .08))
        world = hand.matrix_world.copy()
        world.translation = target
        hand.matrix_world = world
        tool.update()
        endpoint_error = (tool.target_matrix(tool.world_bones(rig), rig, "hand.L", default_profile()["limbs"]["hand.L"]).translation-target).length
        assert endpoint_error < .003, endpoint_error
        tool.key_pose()
        keyed = hand.matrix_world.copy()
        bpy.context.scene.frame_set(2)
        bpy.context.scene.frame_set(1)
        assert matrix_error(hand.matrix_world, keyed) < .0001
        tool.mirror_pose("L_TO_R")
        tool.key_pose()
        tool.update()
        mirrored = ctrls["hand.R"].matrix_world.translation.copy()
        assert abs(mirrored.y+target.y) < .001, (mirrored, target)
        tool.activate_clip("sample_reach")
        tool.activate_clip("sample_idle")
        assert (ctrls["hand.L"].matrix_world.translation-target).length < .001
        tool.support_pin(True)
        main = ctrls["hand.R"]
        support_before = ctrls["hand.L"].matrix_world.translation.copy()
        main.location.x += .04
        tool.update()
        assert abs((ctrls["hand.L"].matrix_world.translation-support_before).x-.04) < .001
        tool.key_pose()
        tool.activate_clip("sample_reach")
        tool.activate_clip("sample_idle")
        assert ctrls["hand.L"].constraints.get(tool.PREFIX + "Support") is not None
        tool.support_pin(False)
        tool.key_pose()
        work = folder / "work.blend"
        tool.save_work(work)
        try:
            tool.save_work(source)
            raise AssertionError("원본 덮어쓰기 방어 실패")
        except ValueError:
            pass
        bpy.ops.wm.open_mainfile(filepath=str(work))
        assert tool.state()["active"] == "sample_idle"
        manifest = tool.export_clip(folder / "export")
        from Tools.blender_pipeline.animation_pipeline import bake
        bake(manifest, folder / "export/baked")
        result = json.loads((folder / "export/baked/clips.json").read_text(encoding="utf-8"))
        assert result["max_reload_error"] < .0001
        baked = bpy.data.objects["PlayerRigidRig"]
        bpy.context.scene.frame_set(1)
        sample = json.loads(manifest.read_text(encoding="utf-8"))["clips"][0]["samples"][0]
        from mathutils import Matrix
        for name, rows in sample["bones"].items():
            assert matrix_error(baked.pose.bones[name].matrix_basis, Matrix(rows)) < .0001
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        print("POSE_TOOL_TEST_PASSED", json.dumps({"initial_error": initial_error,
              "feet_error": foot_error, "hand_error": endpoint_error, "reload_error": result["max_reload_error"]}))


run()

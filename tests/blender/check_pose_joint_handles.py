"""실제 관절 위 포즈 손잡이와 굽힘 방향 조작을 Blender에서 검사한다."""

import argparse
import json
from pathlib import Path
import sys
import math

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Vector, Matrix
from Tools.pose_tool.worker import PoseWorker
from Tools.pose_tool import scene as engine

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
if args.output.exists():
    raise FileExistsError(args.output)
args.output.mkdir(parents=True)
worker = PoseWorker({"source": str(args.source.resolve()), "work": str(args.output.resolve()/"work.blend")}, args.output.resolve())
rig, _ = engine.rig_objects()
before = engine.world_bones(rig)
results = []
for view in ("oblique", "front", "side", "top"):
    worker.view(view)
    snapshot = worker.snapshot()
    from bpy_extras.object_utils import world_to_camera_view
    for side in ("L", "R"):
        point = snapshot["points"]["pole.foot."+side]
        knee = before["Shin."+side].translation
        expected = world_to_camera_view(bpy.context.scene, worker.camera, knee)
        error = max(abs(point["uv"][i]-expected[i]) for i in range(3))
        assert error < 1e-6, (view, side, error)
        assert (Vector(point["world"])-knee).length < 1e-6
        results.append({"view": view, "side": side, "projection_error": error})
worker.view("oblique")
side = "R"
origin = before["Thigh."+side].translation
axis = (before["Foot."+side].translation-origin).normalized()
joint = before["Shin."+side].translation
radial = joint-origin-axis*(joint-origin).dot(axis)
desired_radial = Matrix.Rotation(math.radians(25), 3, axis)@radial
desired = origin+axis*(joint-origin).dot(axis)+desired_radial
worker.execute({"command": "bend", "control": "pole.foot.R", "world": list(desired)})
after = engine.world_bones(rig)
foot_error = (after["Foot.R"].translation-before["Foot.R"].translation).length
knee_error = (after["Shin.R"].translation-desired).length
assert foot_error < .001, foot_error
assert knee_error < .002, knee_error
worker.render()
result = {"source": worker.snapshot()["source"], "projection_checks": results,
          "foot_error": foot_error, "knee_target_error": knee_error}
(args.output/"report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("POSE_JOINT_HANDLES_PASSED", json.dumps(result))

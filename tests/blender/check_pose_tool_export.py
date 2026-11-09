"""편집 작업본의 평가 포즈와 출력·재로딩한 기존 리그를 비교한다."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import bpy
from Tools.pose_tool import scene as tool
from Tools.blender_pipeline.animation_pipeline import bake


parser = argparse.ArgumentParser()
parser.add_argument("--work", type=Path, required=True)
parser.add_argument("--clip", required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
bpy.ops.wm.open_mainfile(filepath=str(args.work.resolve()))
tool.activate_clip(args.clip)
rig, _ = tool.rig_objects()
clip = next(c for c in tool.state()["clips"] if c["name"] == args.clip)
expected = {}
for frame in range(clip["start"], clip["end"]+1):
    bpy.context.scene.frame_set(frame)
    expected[frame] = tool.world_bones(rig)
manifest = tool.export_clip(args.output)
rig_name = rig.name
bake(manifest, args.output / "baked")
rig = bpy.data.objects[rig_name]
max_error = 0
for frame, worlds in expected.items():
    bpy.context.scene.frame_set(frame)
    actual = tool.world_bones(rig)
    max_error = max(max_error, max(abs(actual[name][i][j]-worlds[name][i][j])
                                 for name in worlds for i in range(4) for j in range(4)))
assert max_error < .0001, max_error
result = {"clip": args.clip, "frames": len(expected), "max_matrix_error": max_error,
          "events": json.loads(manifest.read_text(encoding="utf-8"))["clips"][0]["events"]}
(args.output / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("POSE_EXPORT_CHECK_PASSED", json.dumps(result))

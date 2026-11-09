"""기존 손목 컨트롤 작업본을 손바닥 컨트롤로 옮길 때 포즈 보존을 확인한다."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bpy
from Tools.pose_tool import scene as engine

parser = argparse.ArgumentParser()
parser.add_argument("--work", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
bpy.ops.wm.open_mainfile(filepath=str(args.work.resolve()))
rig, _ = engine.rig_objects()
clips = engine.state()["clips"]
before = {}
for clip in clips:
    engine.activate_clip(clip["name"])
    before[clip["name"]] = {}
    for frame in {clip["start"], (clip["start"]+clip["end"])//2, clip["end"]}:
        bpy.context.scene.frame_set(frame)
        before[clip["name"]][frame] = engine.world_bones(rig)
engine.upgrade_palm_handles()
maximum = 0
for clip in clips:
    engine.activate_clip(clip["name"])
    for frame, matrices in before[clip["name"]].items():
        bpy.context.scene.frame_set(frame)
        actual = engine.world_bones(rig)
        maximum = max(maximum, max(abs(matrix[i][j]-actual[name][i][j])
                                 for name, matrix in matrices.items() for i in range(4) for j in range(4)))
assert maximum < .0001, maximum
result = {"clips": len(clips), "max_matrix_error": maximum, "source_saved": False}
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps(result), encoding="utf-8")
print("POSE_HANDLE_MIGRATION_PASSED", json.dumps(result))

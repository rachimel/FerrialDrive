"""지정한 실제 에셋의 동작 불러오기와 편집 작업본을 독립 검사한다."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import bpy
from Tools.pose_tool import scene as tool
from Tools.pose_tool.profile import load_profile, clip_ranges


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    digest = hashlib.sha256(args.source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    profile = load_profile(args.profile)
    rig = bpy.data.objects[profile["rig"]]
    metadata_path = args.source.parent / "clips.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else None
    clips = clip_ranges(bpy.context.scene, metadata)
    references = {}
    for clip in clips:
        references[clip["name"]] = {}
        for frame in sorted({clip["start"], (clip["start"]+clip["end"])//2, clip["end"]}):
            bpy.context.scene.frame_set(frame)
            references[clip["name"]][frame] = tool.world_bones(rig)
    bpy.context.scene.frame_set(clips[0]["start"])
    tool.prepare(profile, args.source, metadata)
    results = []
    for clip in clips:
        tool.activate_clip(clip["name"])
        errors = []
        for frame, expected in references[clip["name"]].items():
            bpy.context.scene.frame_set(frame)
            actual = tool.world_bones(rig)
            for name in expected:
                angle = actual[name].to_quaternion().rotation_difference(expected[name].to_quaternion()).angle
                errors.append({"frame": frame, "bone": name,
                               "location": (actual[name].translation-expected[name].translation).length,
                               "angle": min(angle, math.tau-angle)})
        worst = max(errors, key=lambda e: e["location"])
        max_angle = max(e["angle"] for e in errors)
        results.append({"clip": clip["name"], "worst": worst, "max_angle": max_angle})
        print("POSE_CLIP_CHECK", json.dumps(results[-1]), flush=True)
    tool.activate_clip("gun_aim" if any(c["name"] == "gun_aim" for c in clips) else clips[0]["name"])
    from Tools.pose_tool import addon
    addon.register()
    addon.configure_view()
    bpy.context.scene.fd_pose_clip = tool.state()["active"]
    tool.save_work(args.output / "pose_work.blend")
    report = {"clips": results, "source_unchanged": hashlib.sha256(args.source.read_bytes()).hexdigest() == digest,
              "visual_approval": False}
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert report["source_unchanged"]
    assert max(r["worst"]["location"] for r in results) < .01, "포즈 불러오기 위치 오차"
    assert max(r["max_angle"] for r in results) < .03, "포즈 불러오기 회전 오차"
    print("POSE_ASSET_CHECK_PASSED", flush=True)


main()

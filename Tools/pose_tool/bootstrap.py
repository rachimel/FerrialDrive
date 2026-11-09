"""별도 Blender 프로세스에서 작업본과 패널을 준비한다."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import bpy
from Tools.pose_tool import addon, scene
from Tools.pose_tool.profile import load_profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    addon.register()
    if args.sample:
        from samples.pose_tool.make_sample import create_sample
        create_sample()
        args.source = args.work.parent / "sample_source.blend"
        if args.source.exists():
            raise FileExistsError(args.source)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.source))
    elif args.source:
        bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    if scene.STATE not in bpy.context.scene:
        metadata_path = args.source.parent / "clips.json" if args.source else None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path and metadata_path.is_file() else None
        scene.prepare(load_profile(args.profile), args.source, metadata)
    scene.upgrade_palm_handles()
    bpy.context.scene.fd_pose_clip = scene.state()["active"]
    if args.work.exists() and args.work.resolve() != Path(bpy.data.filepath).resolve():
        raise FileExistsError(args.work)
    scene.save_work(args.work)
    if not bpy.app.background:
        def initialize_view():
            addon.configure_view()
            return None
        bpy.app.timers.register(initialize_view, first_interval=.2)
    print("POSE_TOOL_READY " + str(args.work), flush=True)


if __name__ == "__main__":
    main()

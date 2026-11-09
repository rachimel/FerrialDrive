"""FDrive Pose Tool

별도 Blender 작업본에서 손·발 IK와 동작 포즈를 편집한다.
"""

import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--background", action="store_true", help="창 없이 준비와 저장만 수행")
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    from Tools.blender_pipeline.asset_build import find_blender
    blender = find_blender(args.blender)
    source = args.source
    if not source and not args.sample:
        source = ROOT / "data/models/basic_weapons/animation_blocking/animations.blend"
        if not source.is_file():
            args.sample = True
            source = None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    work = args.work or ROOT / "Tools/pose_tool/workspace" / stamp / "pose_work.blend"
    work = work.resolve()
    if work.exists() and (source is None or source.resolve() != work):
        parser.error("기존 작업본을 덮어쓸 수 없다. 재개하려면 해당 작업본을 source로 지정한다.")
    work.parent.mkdir(parents=True, exist_ok=True)
    command = [str(blender), "--factory-startup"]
    if args.background:
        command.append("--background")
    command += ["--python-exit-code", "1", "--python", str(Path(__file__).with_name("bootstrap.py")),
                "--", "--work", str(work)]
    if args.sample:
        command.append("--sample")
    elif source:
        command += ["--source", str(source.resolve())]
    if args.profile:
        command += ["--profile", str(args.profile.resolve())]
    subprocess.run(command, check=True, cwd=ROOT)


if __name__ == "__main__":
    main()

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


def launch_command(source=None, *, sample=False, profile=None, blender=None, work=None, background=False, tool_python=None):
    from Tools.blender_pipeline.asset_build import find_blender
    blender = find_blender(blender)
    source = Path(source).expanduser().resolve() if source else None
    if source is None and not sample:
        default = ROOT / "data/models/basic_weapons/base_pose.blend"
        if not default.is_file():
            raise FileNotFoundError("모델 .blend 파일을 실행기에 전달하거나 --sample을 지정한다.")
        source = default
    if source and (not source.is_file() or source.suffix.lower() != ".blend"):
        raise FileNotFoundError(f"Blender 모델 / 작업본을 찾을 수 없다: {source}")
    if source and sample:
        raise ValueError("모델 파일과 도형 샘플 중 하나만 지정한다.")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    work_name = source.name if source else "sample_pose.blend"
    work = Path(work).resolve() if work else ROOT / "Tools/pose_tool/workspace" / stamp / work_name
    if work.exists() and source != work:
        raise FileExistsError("기존 작업본을 덮어쓸 수 없다. 재개하려면 해당 작업본을 source로 지정한다.")
    work.parent.mkdir(parents=True, exist_ok=True)
    command = [str(blender), "--factory-startup"]
    if background:
        command.append("--background")
    command += ["--python-exit-code", "1", "--python", str(Path(__file__).with_name("bootstrap.py")),
                "--", "--work", str(work), "--tool-python", str(tool_python or sys.executable)]
    if sample:
        command.append("--sample")
    else:
        command += ["--source", str(source)]
    if profile:
        command += ["--profile", str(Path(profile).resolve())]
    return command


def launch_native(source=None, *, sample=False, tool_python=None):
    """Asset Tool에서 독립 Blender 창을 연다. 호출 앱 종료와 수명을 분리한다."""
    return subprocess.Popen(launch_command(source, sample=sample, tool_python=tool_python), cwd=ROOT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--background", action="store_true", help="창 없이 준비와 저장만 수행")
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    command = launch_command(args.source, sample=args.sample, profile=args.profile,
                             blender=args.blender, work=args.work, background=args.background)
    subprocess.run(command, check=True, cwd=ROOT)


if __name__ == "__main__":
    main()

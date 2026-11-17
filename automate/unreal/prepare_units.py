"""출력 단위 제작 요청을 전용 Unreal 프로세스에서 실행한다."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unreal", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--python-mode", choices=("editor", "commandlet"), default="editor",
                        help="기본 편집기 실행 또는 명령줄 전용 Python 실행")
    parser.add_argument("--engine-arg", action="append", default=[], help="전용 Unreal 프로세스의 추가 시작 옵션")
    args = parser.parse_args()
    for path in (args.unreal, args.project, args.request):
        if not path.is_file():
            raise FileNotFoundError(path)
    data = json.loads(args.request.read_text(encoding="utf-8-sig"))
    operation = data.get("operation", "render_units")
    scripts = {"render_units": "render_units.py", "animation_clip": "animation_clip.py", "surface_import": "surface_assets.py", "surface_usage":"surface_assets.py", "rig_workspace": "rig_workspace.py", "contact_test": "contact_response.py", "contact_geometry": "contact_response.py", "contact_probe": "contact_response.py"}
    if operation not in scripts:
        raise ValueError("지원하지 않는 Unreal 작업")
    report = (ROOT / data["report"]).resolve()
    if not report.is_relative_to(ROOT / "automate/workspace") or report.exists() or report.with_suffix(".error.txt").exists():
        raise ValueError("새 자동화 작업본의 보고 경로가 필요하다.")
    environment = {**os.environ, "FD_UNITS_REQUEST": str(args.request.resolve()), "FD_UNREAL_BATCH_WORKER": "1"}
    script = ROOT / "automate/unreal" / scripts[operation]
    python_arguments = (["-run=pythonscript", "-script=" + str(script)] if args.python_mode == "commandlet"
                        else ["-ExecutePythonScript=" + str(script)])
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
    process_log = report.with_suffix(".process.log")
    process_log.parent.mkdir(parents=True, exist_ok=True)
    stream = process_log.open("wb")
    process = subprocess.Popen([str(args.unreal.resolve()), str(args.project.resolve()),
        *python_arguments, "-unattended", "-nosplash", "-nosound", *args.engine_arg],
        cwd=ROOT, env=environment, startupinfo=startup, stdout=stream, stderr=subprocess.STDOUT)
    try:
        process.wait(timeout=args.timeout)
        error = report.with_suffix(".error.txt")
        if not report.exists() or error.exists():
            raise RuntimeError(error.read_text(encoding="utf-8") if error.exists() else
                               f"출력 단위 보고가 없다. Unreal 종료 코드: {process.returncode}. 시작 로그: {process_log}")
        if process.returncode:
            raise RuntimeError("결과 파일은 생성됐지만 Unreal이 비정상 종료됐다. 새 프로세스에서 재로딩을 확인한다: "+str(report))
        print(json.dumps({"report": str(report)}, ensure_ascii=False))
    finally:
        if process.poll() is None:
            process.terminate()
        stream.close()


if __name__ == "__main__":
    main()

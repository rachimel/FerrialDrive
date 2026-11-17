"""별도 Unreal 렌더 프로세스를 실행하고 완료 manifest를 확인한다."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unreal", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--engine-arg", action="append", default=[], help="전용 Unreal 프로세스의 추가 시작 옵션")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.demo and not args.project.exists():
        target = args.project.resolve()
        if not target.is_relative_to(ROOT / "automate/workspace") or (target.parent.exists() and any(target.parent.iterdir())):
            raise ValueError("시연 프로젝트는 automate/workspace의 새 빈 폴더에 만든다.")
        (target.parent / "Config").mkdir(parents=True)
        shutil.copyfile(ROOT / "samples/unreal_pipeline/PrerenderLab.uproject", target)
        shutil.copyfile(ROOT / "samples/unreal_pipeline/DefaultEngine.ini", target.parent / "Config/DefaultEngine.ini")
    for path in (args.unreal, args.project, args.request):
        if not path.is_file():
            raise FileNotFoundError(path)
    request = json.loads(args.request.read_text(encoding="utf-8-sig"))
    output = (ROOT / request["output"]).resolve()
    if output.exists():
        raise FileExistsError(output)
    if not request.get("quit_when_finished") or args.timeout <= 0:
        raise ValueError("전용 프로세스는 quit_when_finished=true와 양수 제한 시간이 필요하다.")
    script = ROOT / ("samples/unreal_pipeline/prerender_demo.py" if args.demo else "automate/unreal/prerender.py")
    environment = {**os.environ, "FD_PRERENDER_REQUEST": str(args.request.resolve()), "FD_UNREAL_BATCH_WORKER": "1"}
    process = subprocess.Popen([str(args.unreal.resolve()), str(args.project.resolve()),
        "-ExecutePythonScript=" + str(script), "-EnablePlugins=MovieRenderPipeline",
        "-ini:Engine:[/Script/Engine.RendererSettings]:r.CustomDepth=3",
        "-ini:Engine:[/Script/Engine.RendererSettings]:r.PostProcessing.PropagateAlpha=1",
        "-unattended", "-nosplash", "-nosound", *args.engine_arg],
        cwd=ROOT, env=environment, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        end = time.monotonic() + args.timeout
        while not (output / "status.json").is_file():
            if process.poll() is not None:
                raise RuntimeError("Unreal이 완료 기록 전에 종료됐다. 프로젝트 Saved/Logs를 확인한다.")
            if time.monotonic() >= end:
                raise TimeoutError("Unreal 렌더 제한 시간 초과")
            time.sleep(.2)
        status = json.loads((output / "status.json").read_text(encoding="utf-8"))
        if not status["success"]:
            raise RuntimeError(status.get("error", "렌더 실패"))
        for member in request.get("requests", [request]):
            member_output = (ROOT / member["output"]).resolve()
            if (member_output / "native_manifest.json").exists():
                from shadow_pass import finalize_shadow
                try:
                    finalize_shadow(member_output)
                except Exception as error:
                    (output / "status.json").write_text(json.dumps({"success": False, "phase": "shadow_failed", "error": str(error)}), encoding="utf-8")
                    raise
            if not (member_output / "manifest.json").is_file():
                raise FileNotFoundError(member_output / "manifest.json")
            (member_output / "status.json").write_text(json.dumps({"success": True, "phase": "complete"}), encoding="utf-8")
        (output / "status.json").write_text(json.dumps({"success": True, "phase": "complete"}), encoding="utf-8")
        print(json.dumps({"manifest": str(output / "manifest.json")}, ensure_ascii=False))
    finally:
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.terminate()


if __name__ == "__main__":
    main()

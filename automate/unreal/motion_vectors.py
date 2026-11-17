"""전용 Unreal 프로세스의 벡터 출력을 실행하고 완료 상태를 확인한다."""

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
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--engine-arg", action="append", default=[])
    args = parser.parse_args()
    for path in (args.unreal, args.project, args.request):
        if not path.is_file():
            raise FileNotFoundError(path)
    request = json.loads(args.request.read_text(encoding="utf-8"))
    output = (ROOT / request["output"]).resolve()
    if not output.is_relative_to(ROOT / "output") or output.exists():
        raise ValueError("output 아래 새 렌더 경로가 필요하다.")
    environment = {**os.environ, "FD_MOTION_REQUEST": str(args.request.resolve()), "FD_UNREAL_BATCH_WORKER": "1"}
    engine_args = list(args.engine_arg)
    if not any(value.lower().startswith("-shaderworkingdir=") for value in engine_args):
        shaders = ROOT / "automate/workspace/unreal_shaders"
        shaders.mkdir(parents=True, exist_ok=True)
        engine_args.append("-ShaderWorkingDir=" + str(shaders))
    command = [str(args.unreal.resolve()), str(args.project.resolve()),
               "-ExecutePythonScript=" + str(ROOT / "automate/unreal/motion_vector_capture.py"),
               "-EnablePlugins=MovieRenderPipeline",
               "-ini:Engine:[/Script/Engine.RendererSettings]:r.PostProcessing.PropagateAlpha=1",
               "-unattended", "-nosplash", "-nosound", *engine_args]
    process = subprocess.Popen(command, cwd=ROOT, env=environment,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        process.wait(timeout=args.timeout)
        status_path = output / "status.json"
        if not status_path.is_file():
            raise RuntimeError("완료 기록이 없다. 전용 Unreal 프로세스 로그를 확인한다.")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if not status["success"] or process.returncode:
            raise RuntimeError(status.get("error", "Unreal 벡터 출력 실패"))
        print(json.dumps({"output": str(output), "success": True}))
    finally:
        if process.poll() is None:
            process.terminate()


if __name__ == "__main__":
    main()

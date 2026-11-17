"""발견·스키마 확인을 마친 정확한 MCP 도구로 동작 요청을 순서대로 실행한다."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--existing-first", action="store_true")
    parser.add_argument("--results-name", default="calls")
    args = parser.parse_args()
    data = json.loads(args.batch.read_text(encoding="utf-8"))
    directory = args.batch.resolve().parent
    results = directory/args.results_name
    results.mkdir(exist_ok=True)
    for index, clip in enumerate(data["clips"]):
        if index < args.start_index:
            continue
        name = clip["name"]
        operations = ["create_batch_clip", "inspect_batch", "key_batch_clip", "export_batch_clip"]
        if args.existing_first and index == args.start_index:
            operations.remove("create_batch_clip")
        for operation in operations:
            output = results/(name+"."+operation+".json")
            if output.exists():
                raise FileExistsError("이전 호출 결과가 있다. 상태를 확인한 뒤 재개 범위를 정한다: "+str(output))
            payload = {"operation":operation, "request_path":str(directory/(name+".request.json"))}
            started = time.monotonic()
            for attempt in range(40 if operation == "inspect_batch" else 1):
                process = subprocess.run([str(args.cli.resolve()),"--output","json","call",args.tool,"--json-file","-"],
                                         input=json.dumps(payload),capture_output=True,text=True,encoding="utf-8",timeout=100)
                output.write_text(process.stdout,encoding="utf-8")
                output.with_suffix(".stderr.txt").write_text(process.stderr,encoding="utf-8")
                if not process.stdout.strip():
                    raise RuntimeError("호출 결과가 없다. 실행 여부를 확인한다: "+process.stderr[:500])
                response = json.loads(process.stdout)
                envelope = response.get("result",{}).get("structuredContent",{})
                if process.returncode or not response.get("success") or not envelope.get("success"):
                    raise RuntimeError("호출 실패·부분 실행 가능. 재실행하지 않고 결과를 확인한다: "+str(output))
                value = envelope["context"]["result"]
                if operation != "inspect_batch" or value["status"] == "ready":
                    break
                time.sleep(.25)
            if operation == "inspect_batch" and value["status"] != "ready":
                raise RuntimeError("FK 제어점 초기화 대기. 다음 변경 호출은 실행하지 않았다.")
            if operation == "inspect_batch" and (value.get("key_metadata") or value.get("key_count",0)):
                raise RuntimeError("이미 키가 있는 Sequence를 덮어쓰지 않는다.")
            if operation == "key_batch_clip" and value["max_control_position_error_cm"] > .005:
                raise RuntimeError("제어점 조회 오차가 허용 범위를 넘었다.")
            if operation == "export_batch_clip":
                filename = Path(value["fbx"])
                if hashlib.sha256(filename.read_bytes()).hexdigest() != value["sha256"]:
                    raise ValueError("FBX 결과 해시 불일치")
            print(json.dumps({"index":index+1,"total":len(data["clips"]),"clip":name,"operation":operation,"seconds":round(time.monotonic()-started,2)},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()

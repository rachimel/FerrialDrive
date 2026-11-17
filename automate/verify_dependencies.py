"""분리한 자동화 파일의 무결성과 현재 요청 경로를 읽기 전용으로 확인한다."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    manifest = json.loads((ROOT / "automate/workspace/output_dependency_migration.json").read_text(encoding="utf-8"))
    failures = []
    for row in manifest["files"]:
        destination = Path(row["destination"])
        if not destination.is_file() or digest(destination) != row["sha256"]:
            failures.append(str(destination))
        if Path(row["source"]).exists():
            failures.append("이전 경로가 남음: " + row["source"])
    runtime = manifest["runtime"]
    for name, expected in runtime["sha256"].items():
        target = Path(runtime["destination"]) / name
        if not target.is_file() or digest(target) != expected:
            failures.append(str(target))
    if Path(runtime["source"]).exists():
        failures.append("이전 런타임이 남음")
    for row in manifest["updated_requests"]:
        request = json.loads((ROOT / row["file"]).read_text(encoding="utf-8-sig"))
        if request[row["field"]] != row["after"] or not Path(row["after"]).is_file():
            failures.append(row["file"] + ": " + row["field"])
    result = {"files": len(manifest["files"]), "runtime_files": len(runtime["sha256"]),
              "requests": len(manifest["updated_requests"]), "failures": failures,
              "note": "파일·경로 검사다. CLI 자동 업데이트나 시각적 품질 검증은 포함하지 않는다."}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()

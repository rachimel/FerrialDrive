"""output에 잘못 배치된 자동화 의존 파일을 해시 확인 후 분리한다."""
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
AUTOMATE = ROOT / "automate"
MANIFEST = AUTOMATE / "workspace" / "output_dependency_migration.json"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def move_verified(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if not source.is_relative_to(ROOT) or not destination.is_relative_to(AUTOMATE):
        raise ValueError("프로젝트의 자동화 분리 범위를 벗어났다.")
    if not source.is_file():
        if destination.is_file():
            return {"source": str(source), "destination": str(destination), "sha256": digest(destination), "status": "already_moved"}
        raise FileNotFoundError(source)
    expected, size = digest(source), source.stat().st_size
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    shutil.move(str(source), str(destination))
    if digest(destination) != expected or source.exists():
        raise RuntimeError("이동 결과의 해시/원래 경로 확인 실패")
    return {"source": str(source), "destination": str(destination), "sha256": expected, "bytes": size, "status": "moved"}


def main():
    if MANIFEST.exists():
        raise FileExistsError("기존 이동 기록이 있다. 상태를 먼저 확인한다.")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "files": [], "updated_requests": [], "runtime": {}}
    try:
        pairs = [
            (ROOT / "output/unreal_roundtrip_setup/bin/dcc-mcp-cli.exe", AUTOMATE / "bin/dcc-mcp-cli.exe"),
            (ROOT / "output/unreal_roundtrip_setup/dcc_mcp_unreal-0.3.0-py3-none-any.whl", AUTOMATE / "packages/dcc_mcp_unreal-0.3.0-py3-none-any.whl"),
        ]
        references = json.loads((ROOT / "Tools/unreal_pipeline/workspace/fresh_rig_20261110/output_input_references.json").read_text(encoding="utf-8"))
        for row in references:
            source = Path(row["value"]).resolve()
            if not source.is_relative_to(ROOT / "output"):
                raise ValueError("보존 입력이 output 범위 밖이다.")
            destination = AUTOMATE / "workspace/retained_inputs" / source.relative_to(ROOT / "output")
            pairs.append((source, destination))
        for source, destination in pairs:
            if not source.is_file():
                raise FileNotFoundError(source)
            if destination.exists():
                raise FileExistsError(destination)
        for source, destination in pairs:
            entry = move_verified(source, destination)
            report["files"].append(entry)
            MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        runtime_source = ROOT / "Tools/unreal_pipeline/workspace/roundtrip_20261110/python"
        runtime_destination = AUTOMATE / "runtime/unreal/python"
        if not runtime_source.resolve().is_relative_to(ROOT) or not runtime_destination.resolve().is_relative_to(AUTOMATE):
            raise ValueError("런타임 이동 경로가 프로젝트 범위를 벗어났다.")
        runtime_hashes = {p.relative_to(runtime_source).as_posix(): digest(p) for p in runtime_source.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
        if runtime_destination.exists():
            raise FileExistsError(runtime_destination)
        runtime_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(runtime_source), str(runtime_destination))
        differences = [name for name, expected in runtime_hashes.items() if digest(runtime_destination / name) != expected]
        if differences or runtime_source.exists():
            raise RuntimeError("런타임 이동 결과가 원본과 다르다.")
        report["runtime"] = {"source": str(runtime_source), "destination": str(runtime_destination), "files": len(runtime_hashes), "sha256": runtime_hashes, "verified": True}
        for row in references:
            request = ROOT / row["file"]
            raw = request.read_bytes()
            text = raw.decode("utf-8-sig")
            data = json.loads(text)
            source = Path(row["value"]).resolve()
            destination = AUTOMATE / "workspace/retained_inputs" / source.relative_to(ROOT / "output")
            key = row["field"].removeprefix(".")
            if data[key] != row["value"]:
                raise ValueError("요청 입력 경로가 조사 후 변경됐다.")
            backup = AUTOMATE / "workspace/request_backups" / row["file"]
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(raw)
            data[key] = str(destination)
            request.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            report["updated_requests"].append({"file": row["file"], "field": key, "before": row["value"], "after": str(destination)})
        report["completed"] = True
    finally:
        MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"completed": True, "moved_files": len(report["files"]), "runtime_files": report["runtime"]["files"], "updated_requests": len(report["updated_requests"]), "manifest": str(MANIFEST)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

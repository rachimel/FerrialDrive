"""검증된 Unreal 출력에 런타임 별칭을 붙이고 이동·공격 카탈로그를 조립한다."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ferrial_drive.assets.catalog import AssetCatalog
from ferrial_drive.assets.mech import MechBundle


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def relative(path, base):
    return Path(os.path.relpath(path, base)).as_posix()


def assemble(request):
    output, interpolation = [(ROOT / request[key]).resolve() for key in ("output", "interpolation_output")]
    if any(path.exists() or not any(path.is_relative_to(ROOT / name) for name in ("data", "output"))
           for path in (output, interpolation)):
        raise ValueError("data 또는 output 아래의 새 카탈로그 경로 두 개가 필요하다.")
    aliases = request.get("aliases", {})
    groups, rows, guards, names = {"movement": [], "combat": []}, [], {}, set()
    def guard(path):
        guards[Path(path).resolve()] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for source_index, source in enumerate(request["sources"]):
        asset_path = ROOT / source["asset_catalog"]
        motion_path = ROOT / source["interpolation_catalog"]
        motion = read(motion_path)
        available = set()
        for item in motion.get("source_assets", []):
            path = (motion_path.parent / item["path"]).resolve()
            guard(path)
            if guards[path] != item["sha256"]:
                raise ValueError("보간 카탈로그의 제작 입력 해시가 다르다.")
        guard(asset_path)
        guard(motion_path)
        for definition in AssetCatalog.load(asset_path).definitions.values():
            if definition.kind != "mech":
                raise ValueError("메카 번들만 런타임 카탈로그로 연결한다.")
            document = read(definition.source)
            available.update(document["clips"])
            guard(definition.source)
            selected = {key: {} for key in groups}
            for name, clip in document["clips"].items():
                motion_name, direction = name.rsplit("/", 1)
                group = "combat" if motion_name in request["attack_motions"] else "movement"
                selected[group][name] = clip
                if motion_name in aliases:
                    selected[group][aliases[motion_name] + "/" + direction] = clip
            for group, clips in selected.items():
                if not clips:
                    continue
                identifier = f"source_{source_index}_{definition.asset_id}"
                target = output / group / identifier / "mech.json"
                clone = copy.deepcopy(document)
                clone["asset_id"] += "_runtime_" + group
                clone["clips"] = clips
                for layer in clone["layers"].values():
                    for key in ("sheet", "energy_mask"):
                        if key in layer:
                            layer[key] = relative(definition.source.parent / layer[key], target.parent)
                write(target, clone)
                MechBundle.load(target)
                guard(target)
                groups[group].append({"id": identifier, "kind": "mech", "source": relative(target, output / group)})
        for row in motion["clips"]:
            if row["name"] not in available or not (motion_path.parent / row["path"]).is_file():
                raise ValueError("같은 동작의 기체 번들과 보간 입력이 필요하다.")
            if row["name"] in names:
                raise ValueError("원본 클립 이름이 중복됐다.")
            names.add(row["name"])
            clone = {**row, "path": relative(motion_path.parent / row["path"], interpolation)}
            rows.append(clone)
            motion_name, direction = row["name"].rsplit("/", 1)
            if motion_name in aliases:
                rows.append({**clone, "name": aliases[motion_name] + "/" + direction})
    if len({row["name"] for row in rows}) != len(rows):
        raise ValueError("별칭과 원본 클립 이름이 중복됐다.")
    for group, assets in groups.items():
        if not assets:
            raise ValueError("이동·공격 양쪽에 출력할 클립이 필요하다.")
        write(output / group / "catalog.json", {"version": 1, "assets": assets})
    write(interpolation / "catalog.json", {"schema_version": 1, "clips": rows,
        "source_assets": [{"path": relative(path, interpolation), "sha256": value} for path, value in guards.items()]})
    if request.get("atlas_sources"):
        from ferrial_drive.rendering.motion_atlas import merge_variants
        atlas_output = (ROOT / request["atlas_output"]).resolve()
        if not any(atlas_output.is_relative_to(ROOT / name) for name in ("data", "output")):
            raise ValueError("아틀라스 결과는 data 또는 output 아래에 둔다.")
        guard(interpolation / "catalog.json")
        for quality, sources in request["atlas_sources"].items():
            if quality not in ("high", "medium", "low"):
                raise ValueError("지원하지 않는 품질 이름이다.")
            merge_variants([ROOT / source for source in sources], atlas_output / quality,
                           aliases=aliases, source_guards=guards)
    result = {"raw_clips": len(names), "runtime_clips": len(rows),
              "bundles": {key: len(value) for key, value in groups.items()}, "request": request}
    write(output / "provenance.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--request", type=Path)
    mode.add_argument("--demo", type=Path, help="게임 에셋 없는 공개 도형 입력과 결과를 새 폴더에 준비한다.")
    args = parser.parse_args()
    if args.demo:
        from samples.unreal_pipeline.runtime_fixture import write_runtime_fixture
        request = write_runtime_fixture(args.demo.resolve())
    else:
        request = read(args.request)
    print(json.dumps(assemble(request), ensure_ascii=False))

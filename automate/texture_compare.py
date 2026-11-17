"""원본 보존형 텍스처·보간 아틀라스 후보와 독립 비교 입력을 준비한다."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOCAL_RUNTIME = ROOT / "automate/runtime/texture_compare/python"
if (LOCAL_RUNTIME.is_dir() and
        any(importlib.util.find_spec(name) is None for name in ("numpy", "PIL"))):
    sys.path.insert(0, str(LOCAL_RUNTIME))


def prepare(args):
    from ferrial_drive.rendering.motion_atlas import build_variant, encode_variant, payload_summary, select_catalogs
    config = json.loads(args.config.read_text(encoding="utf-8-sig")) if args.config.is_file() else {}
    if args.add_oodle_scale is not None:
        destination = args.output.resolve()
        comparison = destination / "comparison.json"
        document = json.loads(comparison.read_text(encoding="utf-8"))
        library = args.oodle_library or config.get("oodle_library") or document["dependencies"].get("oodle_library")
        selected = select_catalogs([destination / document["cases"]["legacy"]["path"]], None)
        percent = round(args.add_oodle_scale * 100)
        raw, name = f"atlas_{percent}", f"oodle_{percent}"
        build_variant(selected, destination / raw, 1 / args.add_oodle_scale, max_side=args.page_size)
        encode_variant(destination / raw, destination / name, codec="oodle",
                       oodle_library=library, rdo_lambda=args.rdo_lambda)
        document["cases"][name] = {"label": f"{percent}% Oodle BC7 / RDO {args.rdo_lambda}",
                                   "kind": "atlas", "path": f"{name}/atlas.json"}
        document["payload_estimates"][name] = payload_summary(destination / name / "atlas.json")
        comparison.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"prepared": name, "summary": document["payload_estimates"][name]}, ensure_ascii=True), flush=True)
        return
    if args.add_oodle_75:
        destination = args.output.resolve()
        comparison = destination / "comparison.json"
        document = json.loads(comparison.read_text(encoding="utf-8"))
        library = args.oodle_library or config.get("oodle_library") or document["dependencies"].get("oodle_library")
        selected = select_catalogs([destination / document["cases"]["legacy"]["path"]], None)
        build_variant(selected, destination / "atlas_75", 4/3, max_side=args.page_size)
        encode_variant(destination / "atlas_75", destination / "oodle_75", codec="oodle",
                       oodle_library=library, rdo_lambda=args.rdo_lambda)
        document["cases"]["oodle_75"] = {"label": f"75% Oodle BC7 / RDO {args.rdo_lambda}",
                                          "kind": "atlas", "path": "oodle_75/atlas.json"}
        document["payload_estimates"]["oodle_75"] = payload_summary(destination / "oodle_75/atlas.json")
        comparison.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"prepared": "oodle_75", "summary": document["payload_estimates"]["oodle_75"]}, ensure_ascii=True), flush=True)
        return
    if args.add_oodle_full:
        destination = args.output.resolve()
        comparison = destination / "comparison.json"
        document = json.loads(comparison.read_text(encoding="utf-8"))
        library = args.oodle_library or config.get("oodle_library") or document["dependencies"].get("oodle_library")
        encode_variant(destination / "atlas_full", destination / "oodle_full", codec="oodle",
                       oodle_library=library, rdo_lambda=args.rdo_lambda)
        document["cases"]["oodle_full"] = {"label": f"원해상도 Oodle BC7 / RDO {args.rdo_lambda}",
                                            "kind": "atlas", "path": "oodle_full/atlas.json"}
        document["payload_estimates"]["oodle_full"] = payload_summary(destination / "oodle_full/atlas.json")
        comparison.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"prepared": "oodle_full", "summary": document["payload_estimates"]["oodle_full"]}, ensure_ascii=True), flush=True)
        return
    if args.demo:
        from samples.texture_comparison.fixture import write_fixture
        catalogs = [write_fixture(ROOT / "output/texture_comparison/demo_source")]
    else:
        catalogs = args.catalog or [ROOT / "data/runtime/frame_interpolation/player_sword_locomotion/catalog.json",
                                    ROOT / "data/runtime/frame_interpolation/sword_movement_combo/catalog.json"]
    patterns = None if args.all or args.demo else args.clip
    selected = select_catalogs(catalogs, patterns)
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    # 원본 클립을 참조하는 독립 입력이며 게임 쪽 카탈로그 선택은 바꾸지 않는다.
    rows = []
    for catalog, row in selected:
        clone = dict(row)
        clone["path"] = str((catalog.parent / row["path"]).resolve())
        rows.append(clone)
    legacy = destination / "legacy_catalog.json"
    legacy.write_text(json.dumps({"schema_version": 1, "clips": rows}, indent=2), encoding="utf-8")
    started = perf_counter()
    cases = {"legacy": {"label": "기존 클립별 RGBA", "kind": "legacy", "path": "legacy_catalog.json"}}
    if args.oodle_scales:
        library = args.oodle_library or config.get("oodle_library")
        if not library or not Path(library).is_file():
            raise FileNotFoundError("oodle_library 경로가 필요하다.")
        for scale in dict.fromkeys(args.oodle_scales):
            percent = round(scale * 100)
            raw, name = f"atlas_{percent}", f"oodle_{percent}"
            build_variant(selected, destination / raw, 1 / scale, max_side=args.page_size)
            encode_variant(destination / raw, destination / name, codec="oodle",
                           oodle_library=library, rdo_lambda=args.rdo_lambda)
            cases[name] = {"label": f"{percent}% Oodle BC7 / RDO {args.rdo_lambda}",
                           "kind": "atlas", "path": f"{name}/atlas.json"}
            print(json.dumps({"prepared": name, "clips": len(selected)}), flush=True)
        document = {"version": 1, "cases": cases, "dependencies": {"oodle_library": str(library)},
                    "clips": [row["name"] for _, row in selected], "prepare_seconds": perf_counter()-started,
                    "scope": "기체 색상 BC7·무손실 벡터와 선택 Energy Mask. 그림자·HUD·바닥 제외",
                    "payload_estimates": {name: payload_summary(destination / case["path"])
                                          for name, case in cases.items() if name != "legacy"}}
        (destination / "comparison.json").write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    for name, divisor in (("atlas_full", 1), ("atlas_half", 2)):
        build_variant(selected, destination / name, divisor, max_side=args.page_size)
        cases[name] = {"label": "공유 아틀라스 원해상도" if divisor == 1 else "공유 아틀라스 반해상도",
                       "kind": "atlas", "path": f"{name}/atlas.json"}
        print(json.dumps({"prepared": name, "clips": len(selected)}, ensure_ascii=True), flush=True)
    dependencies = {}
    for name, key in (("ktx", "ktx_executable"), ("oodle", "oodle_library")):
        value = getattr(args, key) or config.get(key)
        if not value or not Path(value).is_file():
            raise FileNotFoundError(f"{key} 경로가 필요하다. --config 또는 해당 인자를 지정한다.")
        dependencies[key] = str(Path(value).resolve())
        encode_variant(destination / "atlas_half", destination / name, codec=name,
                       ktx_executable=value if name == "ktx" else None,
                       oodle_library=value if name == "oodle" else None, rdo_lambda=args.rdo_lambda)
        cases[name] = {"label": "반해상도 KTX2 / BC7" if name == "ktx" else f"반해상도 Oodle BC7 / RDO {args.rdo_lambda}",
                       "kind": "atlas", "path": f"{name}/atlas.json"}
        print(json.dumps({"prepared": name}, ensure_ascii=True), flush=True)
    dependencies["ktx_library"] = str(Path(dependencies["ktx_executable"]).with_name("ktx.dll"))
    encode_variant(destination / "atlas_full", destination / "oodle_full", codec="oodle",
                   oodle_library=dependencies["oodle_library"], rdo_lambda=args.rdo_lambda)
    cases["oodle_full"] = {"label": f"원해상도 Oodle BC7 / RDO {args.rdo_lambda}", "kind": "atlas", "path": "oodle_full/atlas.json"}
    build_variant(selected, destination / "atlas_75", 4/3, max_side=args.page_size)
    encode_variant(destination / "atlas_75", destination / "oodle_75", codec="oodle",
                   oodle_library=dependencies["oodle_library"], rdo_lambda=args.rdo_lambda)
    cases["oodle_75"] = {"label": f"75% Oodle BC7 / RDO {args.rdo_lambda}", "kind": "atlas", "path": "oodle_75/atlas.json"}
    report = {name: payload_summary(destination / case["path"]) for name, case in cases.items() if name != "legacy"}
    document = {"version": 1, "cases": cases, "dependencies": dependencies,
                "clips": [row["name"] for _, row in selected], "prepare_seconds": perf_counter()-started,
                "coverage": "all selected catalogs" if not patterns else "selected clips; not all 160",
                "scope": "보간 계층. 일반 본체/그림자 시트·HUD·바닥 제외", "payload_estimates": report}
    path = destination / "comparison.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"comparison": str(path), "cases": report}, ensure_ascii=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "automate/texture_compare.local.json")
    parser.add_argument("--catalog", type=Path, action="append")
    parser.add_argument("--clip", action="append")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "data/runtime/textures/sword_all_half_20261113")
    parser.add_argument("--ktx-executable", type=Path)
    parser.add_argument("--oodle-library", type=Path)
    parser.add_argument("--rdo-lambda", type=int, default=30)
    parser.add_argument("--page-size", type=int, default=2048)
    parser.add_argument("--oodle-scales", type=float, nargs="+", choices=(0.25, 0.5, 0.75, 1.0),
                        help="지정한 비율의 게임용 Oodle 아틀라스만 준비한다.")
    parser.add_argument("--add-oodle-full", action="store_true", help="준비된 후보에 원해상도 Oodle만 추가한다.")
    parser.add_argument("--add-oodle-75", action="store_true", help="준비된 후보에 75% Oodle을 추가한다.")
    parser.add_argument("--add-oodle-scale", type=float, choices=(0.25, 0.5, 0.75, 1.0),
                        help="기존 원본 카탈로그에서 지정한 해상도 비율의 Oodle 후보를 추가한다.")
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()

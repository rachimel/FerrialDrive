"""PNG 그림자를 원본 보존형 알파 전용 데이터로 준비한다. 창을 생성하지 않는다."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOCAL_RUNTIME = ROOT / "automate/runtime/texture_compare/python"
if LOCAL_RUNTIME.is_dir() and any(importlib.util.find_spec(name) is None for name in ("numpy", "PIL")):
    sys.path.append(str(LOCAL_RUNTIME))

from ferrial_drive.assets.alpha_data import prepare_alpha_data
from ferrial_drive.assets.catalog import AssetCatalog, read_document
from ferrial_drive.settings import SHADOW_QUALITY_SCALES


def collect_shadow_images(catalogs):
    images = []
    for source in catalogs:
        for definition in AssetCatalog.load(source).definitions.values():
            sheet = read_document(definition).sheets.get("shadow")
            if sheet is not None:
                images.append(sheet.image_path.resolve())
    return images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, action="append", default=[])
    parser.add_argument("--image", type=Path, action="append", default=[])
    parser.add_argument("--demo", type=Path, help="게임과 독립된 기본 도형 샘플을 지정 폴더에 준비한다.")
    parser.add_argument("--scale", type=float, choices=(0.125, 0.25, 0.5, 1.0), default=0.5,
                        help="그림자 가로·세로 배율. 기본 0.5, 원본 PNG·프레임 좌표는 유지한다.")
    parser.add_argument("--quality-profiles",action="store_true",help="높음/보통/낮음 그림자 3배율을 별도 파일로 준비한다.")
    args = parser.parse_args()
    catalogs = list(args.catalog)
    if args.demo is not None:
        from samples.asset_loader.make_sample import write_samples
        catalogs.append(write_samples(args.demo.resolve()) / "catalog.json")
    images = list(dict.fromkeys([*(path.resolve() for path in args.image), *collect_shadow_images(catalogs)]))
    if not images:
        parser.error("--catalog, --image 또는 --demo로 그림자를 지정한다.")
    results = []
    for path in images:
        for scale in dict.fromkeys(SHADOW_QUALITY_SCALES.values()) if args.quality_profiles else (args.scale,):
            result = prepare_alpha_data(path, scale=scale, scaled_path=args.quality_profiles)
            results.append(result)
            print(json.dumps(result, ensure_ascii=True), flush=True)
    print(json.dumps({"prepared": len(results), "alpha_bytes": sum(row["alpha_bytes"] for row in results),
                      "source_bytes": sum(row["source_bytes"] for row in results)}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()

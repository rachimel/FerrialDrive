"""텍스처 압축·공유 아틀라스 비교
기존 적재·반해상도·KTX2·Oodle의 화면과 디스크/RAM/GPU 적재량을 비교한다.
별도 프로세스 계측과 블러 켬/끔의 PSNR·SSIM 비교를 제공한다.
"""

from time import perf_counter

STARTED = perf_counter()

import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
UNIT_TEST_ENTRYPOINT = "standalone"
sys.path.insert(0, str(ROOT))
LOCAL_RUNTIME = ROOT / "automate/runtime/texture_compare/python"
if LOCAL_RUNTIME.is_dir():
    sys.path.append(str(LOCAL_RUNTIME))


def benchmark(args):
    from PIL import Image
    from ferrial_drive.diagnostics.texture_metrics import image_quality
    source = args.bundle.resolve()
    document = json.loads(source.read_text(encoding="utf-8"))
    benchmark_root = source.parent / "benchmark"
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d_%H%M%S")
    output = benchmark_root / "runs" / f"{stamp}_{uuid4().hex[:6]}"
    output.mkdir(parents=True, exist_ok=True)
    cases, quality = {}, {}
    clip = args.clip or next((name for name in document["clips"] if name.startswith("combo_03/")), document["clips"][0])
    selected_cases = list(document["cases"])
    reference_directory = output / "legacy"
    artifacts = {}
    if args.case:
        summary_path = benchmark_root / "summary.json"
        if not summary_path.is_file():
            raise ValueError("단일 후보 추가 측정 전에 전체 기준 측정을 실행한다.")
        previous = json.loads(summary_path.read_text(encoding="utf-8"))
        if previous["quality_scope"]["clip"] != clip:
            raise ValueError("기존 품질 비교와 클립이 다르다. 같은 --clip을 지정한다.")
        cases, quality = previous["cases"], previous["quality"]
        selected_cases = [args.case]
        if args.case != "legacy":
            reference_directory = benchmark_root / previous.get("reference_directory", "legacy")
        artifacts = previous.get("case_artifacts", {})
        for previous_name in cases:
            artifacts.setdefault(previous_name, {"report": f"{previous_name}.json", "images": previous_name})
    for name in selected_cases:
        report = output / f"{name}.json"
        images = output / name
        command = [sys.executable, str(Path(__file__).resolve()), "--bundle", str(source), "--case", name,
                   "--measure", "--frames", str(args.frames or 90), "--report", str(report),
                   "--clip", clip, "--quality-directory", str(images), "--phase", "0.37"]
        subprocess.run(command, check=True, cwd=ROOT)
        cases[name] = json.loads(report.read_text(encoding="utf-8"))
        quality[name] = []
        for capture in cases[name]["quality_captures"]:
            filename = capture["file"]
            with Image.open(reference_directory / filename) as reference, Image.open(images / filename) as candidate:
                quality[name].append({**capture, **image_quality(reference, candidate)})
        artifacts[name] = {"report": str(report.relative_to(benchmark_root)),
                           "images": str(images.relative_to(benchmark_root))}
        print(json.dumps({"completed": name, "gpu_mib": cases[name]["gpu"]["gpu_storage_bytes"]/2**20,
                          "ram_mib": cases[name]["memory_loaded"].get("working_set_bytes", 0)/2**20,
                          "first_present_seconds": cases[name]["first_present_seconds"]}, ensure_ascii=True), flush=True)
    summary = {"version": 1, "cases": cases, "quality": quality, "scope": document["scope"],
               "run_directory": str(output.relative_to(benchmark_root)), "case_artifacts": artifacts,
               "reference_directory": str(reference_directory.relative_to(benchmark_root)),
               "cache_policy": "별도 프로세스에서 실행한다. OS 디스크 캐시는 비우지 않으며 cold start를 주장하지 않는다.",
               "quality_scope": {"clip": clip, "phases": [0.15, 0.5, 0.85], "blur": [False, True], "viewport": [512, 512]}}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (benchmark_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(benchmark_root / "summary.json"), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--bundle", type=Path, help="준비한 비교 입력")
    source.add_argument("--demo", action="store_true", help="기본 도형의 기존·공유 RGBA 비교")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--case", choices=("legacy", "atlas_full", "atlas_half", "ktx", "oodle", "oodle_full", "oodle_75"))
    parser.add_argument("--frames", type=int)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--phase", type=float)
    parser.add_argument("--clip")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--metrics", action="store_true")
    parser.add_argument("--candidate", choices=("atlas_full", "atlas_half", "ktx", "oodle", "oodle_full", "oodle_75"))
    parser.add_argument("--quality-directory", type=Path)
    args = parser.parse_args()
    if args.phase is not None and not 0 <= args.phase <= 1:
        parser.error("위상은 0~1이다.")
    default_bundle = ROOT / "data/runtime/textures/sword_all_half_20261113/comparison.json"
    demo = args.demo or (args.bundle is None and not default_bundle.is_file())
    if demo:
        available = {None, "legacy", "atlas_full", "atlas_half"}
        if args.case not in available or args.candidate not in available:
            parser.error("압축 후보를 비교하려면 해당 후보가 포함된 --bundle을 지정한다.")
        output = ROOT / "output/texture_comparison/demo_runs" / uuid4().hex
        subprocess.run([sys.executable, str(ROOT / "automate/run.py"), "texture-compare", "--demo", "--rgba-only",
                        "--output", str(output)], cwd=ROOT, check=True)
        args.bundle = output / "comparison.json"
    elif args.bundle is None:
        args.bundle = default_bundle
    if not args.bundle.is_file():
        parser.error("비교 입력이 없다. python automate/run.py texture-compare 로 먼저 준비한다.")
    if args.benchmark:
        benchmark(args)
        return
    from ferrial_drive.diagnostics.texture_comparison import TextureComparison, WINDOW_SIZE
    from ferrial_drive.runtime import run_application
    program = TextureComparison(args.bundle, case=args.case, report=args.report, capture=args.capture,
                                phase=args.phase, clip=args.clip, measure=args.measure,
                                quality_directory=args.quality_directory, started=STARTED, candidate=args.candidate)
    program.show_metrics = args.metrics or (args.case is None and args.capture is None and bool(program.benchmark_summary))
    title = "Ferrial Drive | Texture Compression"
    if demo:
        title += " | 기본 도형"
    run_application(program, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], title=title, frame_limit=args.frames)


if __name__ == "__main__":
    main()

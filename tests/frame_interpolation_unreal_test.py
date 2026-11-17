"""Unreal 검 동작 프레임 보간
실제 검 휘두르기와 Unreal 모션 벡터를 불러와 보간·블러·중간 렌더를 비교한다.
로컬 프리렌더 데이터가 필요하다.
"""

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UNIT_TEST_ENTRYPOINT = "standalone"


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(PROJECT_ROOT))
    from ferrial_drive.diagnostics.interpolation_preview import ComboBoundaryComparison, FrameInterpolationTest, WINDOW_SIZE
    from ferrial_drive.runtime import run_application
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "data/runtime/frame_interpolation/player_combo/catalog.json")
    parser.add_argument("--frames", type=int)
    parser.add_argument("--phase", type=float)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-blur", action="store_true")
    parser.add_argument("--linear", action="store_true")
    parser.add_argument("--compare", action="store_true", default=True, help="연계 경계의 A/B 비교")
    parser.add_argument("--single", action="store_false", dest="compare", help="원본/혼합/벡터/정답 네 패널을 표시한다.")
    parser.add_argument("--profile", type=Path, help="선택적 CPU 호출 계측 결과")
    args = parser.parse_args()
    if not args.dataset.is_file():
        parser.error("Unreal 검 동작 데이터가 없다. docs/unit-tests/frame_interpolation.md의 Unreal 출력 경로를 실행한다.")
    if args.compare:
        program = ComboBoundaryComparison(args.dataset, phase=args.phase, capture=args.capture)
        for child in (program.program,):
            child.blur_enabled = not args.no_blur
            child.easing = "linear" if args.linear else "smoothstep"
    else:
        program = FrameInterpolationTest(dataset=args.dataset, phase=args.phase, capture=args.capture,
                                         report=args.report, blur=not args.no_blur,
                                         easing="linear" if args.linear else "smoothstep")
    profiler = None
    if args.profile:
        import cProfile
        profiler = cProfile.Profile()
        profiler.enable()
    try:
        run_application(program, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                        title="Ferrial Drive | Unreal Sword Interpolation", frame_limit=args.frames)
    finally:
        if profiler:
            profiler.disable()
            args.profile.parent.mkdir(parents=True, exist_ok=True)
            profiler.dump_stats(str(args.profile))


if __name__ == "__main__":
    main()

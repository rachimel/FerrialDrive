"""FDrive 에셋 로더

이미지·스프라이트·본체/그림자 번들을 검증하고 등록한다.
디버그 모드에서 변경 파일을 감지해 정상 자원으로 교체한다.
"""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UNIT_TEST_ENTRYPOINT = "standalone"


def main():
    from Tools.asset_loader.app import AssetLoaderApp, DEFAULT_CATALOG, WINDOW
    from ferrial_drive.runtime import run_application

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--debug", action="store_true", help="파일 변경에 대한 핫 로드 활성화")
    parser.add_argument("--pose", action="store_true", help="Blender 포즈 편집 창 열기")
    parser.add_argument("--pose-sample", action="store_true", help="포즈 편집의 독립 도형 샘플 열기")
    parser.add_argument("--render-preset", type=Path, help="3D 렌더 설정을 불러온 상태로 열기")
    parser.add_argument("--frames", type=int)
    parser.add_argument("--capture", type=Path, help="화면 검증용 PNG 저장")
    parser.add_argument("--profile", type=Path, help="선택적 로딩 성능 기록 JSON")
    args = parser.parse_args()
    timings = None
    if args.profile:
        from ferrial_drive.diagnostics import TimingRecorder
        timings = TimingRecorder(enabled=True, session="asset_loader")
    app = AssetLoaderApp(source=args.source, catalog=args.catalog, debug=args.debug,
                         timings=timings, capture=args.capture, pose=args.pose, pose_sample=args.pose_sample,
                         render_preset=args.render_preset)
    try:
        run_application(app, **WINDOW, frame_limit=args.frames, timings=timings)
    finally:
        if timings is not None:
            active_error = sys.exc_info()[1]
            try:
                timings.write_json(args.profile)
            except Exception as report_error:
                if active_error is None:
                    raise
                active_error.add_note(f"성능 로그 저장 실패: {report_error}")
    if app.error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""프로젝트 위치 기준 대화 기록 편집기 진입점."""

import argparse
from pathlib import Path
import shutil
import sys
import traceback

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="대화 요약 열람과 누락 보완")
    parser.add_argument("--demo", action="store_true", help="독립 시연용 로그 복사본 사용")
    parser.add_argument("--logs", type=Path, help="열람·보완할 로그 폴더")
    parser.add_argument("--workspace", type=Path, help="로컬 보완 이력·임시 입력 폴더")
    parser.add_argument("--frames", type=int, help="자동 확인용 실행 프레임 수")
    parser.add_argument("--screenshot", type=Path, help="자동 확인용 첫 화면 PNG")
    parser.add_argument("--select", help="처음 선택할 로그 파일명")
    args = parser.parse_args(argv)
    if args.frames is not None and args.frames <= 0:
        parser.error("--frames는 양수여야 한다.")
    workspace = args.workspace or Path(__file__).with_name("workspace")
    directory = args.logs or root / "docs/ai-dev-log"
    if args.demo:
        directory = workspace / "demo_logs"
        directory.mkdir(parents=True, exist_ok=True)
        for source in (root / "samples/conversation_log_viewer").glob("*.md"):
            target = directory / source.name
            if not target.exists():
                shutil.copy2(source, target)
    if not directory.is_dir():
        parser.error("로그 폴더가 없다.")
    from conversation_log_viewer.gui import run_gui
    run_gui(directory, workspace, frame_limit=args.frames, screenshot=args.screenshot,
            selected_file=args.select)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        detail = traceback.format_exc()
        workspace = Path(__file__).with_name("workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "last_error.txt").write_text(detail, encoding="utf-8")
        if sys.stderr is not None:
            sys.stderr.write(detail)
        if sys.platform == "win32" and Path(sys.executable).stem.lower() == "pythonw":
            from ctypes import windll
            windll.user32.MessageBoxW(None, "대화 기록 실행 실패. Tools/conversation_log_viewer/workspace/last_error.txt를 확인한다.", "대화 기록", 0x10)
        raise SystemExit(1)

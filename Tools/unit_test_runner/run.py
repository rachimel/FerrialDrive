"""Zed 터미널 등에서 테스트 .py 하나를 실행하는 진입점."""

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unit_test_runner import run
from unit_test_runner.gui import run_gui
from unit_test_runner.loader import load_test


def main(argv=None):
    parser = argparse.ArgumentParser(description="독립 테스트 .py를 Pico2D 창에서 실행한다.")
    parser.add_argument("test_file", type=Path, nargs="?", help="테스트 .py 경로. 생략하면 드롭 GUI 실행")
    parser.add_argument("--frames", type=int, default=None, help="자동 확인용 최대 프레임 수")
    args = parser.parse_args(argv)
    if args.frames is not None and args.frames <= 0:
        parser.error("--frames는 양수여야 한다.")
    if args.test_file is None:
        run_gui(frame_limit=args.frames)
    else:
        program, window = load_test(args.test_file)
        run(program, window, frame_limit=args.frames)


if __name__ == "__main__":
    main()

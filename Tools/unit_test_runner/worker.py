"""기존 create_test 규약을 새 프로세스에서만 실행하는 호환 진입점."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unit_test_runner import run
from unit_test_runner.loader import load_test


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="기존 테스트 실행 호환 경로")
    parser.add_argument("test_file", type=Path)
    parser.add_argument("--frames", type=int, default=None)
    arguments = parser.parse_args(argv)
    program, window = load_test(arguments.test_file)
    run(program, window, frame_limit=arguments.frames)


if __name__ == "__main__":
    main()

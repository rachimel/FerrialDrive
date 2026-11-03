"""파일 없이 GUI를 열거나 받은 파일 인자를 CLI에 전달하고 실패 내용을 유지한다."""

from pathlib import Path
import sys
import traceback

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unit_test_runner.run import main as run_main


def main(argv=None) -> int:
    try:
        exit_code = run_main(argv)
        if not exit_code:
            return 0
    except SystemExit as error:
        exit_code = 0 if error.code is None else error.code if isinstance(error.code, int) else 1
    except Exception:
        traceback.print_exc()
        exit_code = 1
    if exit_code:
        try:
            input("종료: Enter ")
        except EOFError:
            pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

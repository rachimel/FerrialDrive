"""성능 프로파일러. py-spy로 Python 스택을 수집하고 Flame Graph·AI 분석용 기록을 저장한다."""

import argparse
from datetime import datetime
from pathlib import Path
import sys
import subprocess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ferrial_drive.diagnostics.profiler import find_py_spy, record_profile


def _positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("양수 정수를 지정한다.")
    return number


def _from_root(path):
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--py-spy", type=Path, help="py-spy 실행 파일. 생략 시 프로젝트 런타임/PATH 사용")
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="새 실행 또는 실행 중인 프로세스의 호출 스택 수집")
    targets = record.add_mutually_exclusive_group(required=True)
    targets.add_argument("--target", type=Path, help="실행할 .py 파일. 측정 종료 시 이 실행도 종료한다.")
    targets.add_argument("--pid", type=_positive_int, help="실행 중인 Python PID. 측정 후에도 게임 유지")
    record.add_argument("--python", type=Path, default=Path(sys.executable), help="대상 실행용 Python")
    record.add_argument("--cwd", type=Path, default=ROOT, help="대상 작업 폴더. 기본 프로젝트 루트")
    record.add_argument("--duration", type=_positive_int, default=30, metavar="SECONDS")
    record.add_argument("--rate", type=_positive_int, default=100, metavar="HZ")
    record.add_argument("--include-idle", action="store_true", help="대기 중인 스레드도 수집한다.")
    record.add_argument("--subprocesses", action="store_true", help="PID 연결의 자식 프로세스도 수집한다. 새 실행은 기본 포함")
    record.add_argument("--output", type=Path, help="새 결과 폴더. 생략 시 output/performance/에 생성")
    record.add_argument("target_args", nargs=argparse.REMAINDER, help="-- 뒤에 대상 실행 인자를 전달한다.")
    args = parser.parse_args(argv)
    target_args = args.target_args[1:] if args.target_args[:1] == ["--"] else args.target_args
    if args.pid is not None and target_args:
        parser.error("PID 연결에는 대상 실행 인자를 전달할 수 없다.")
    output = (_from_root(args.output) if args.output else ROOT / "output/performance" /
              datetime.now().astimezone().strftime("profiler-%Y%m%d-%H%M%S-%f%z"))
    try:
        print(f"성능 프로파일러: {args.duration}초 수집 / 결과: {output}", flush=True)
        destination = record_profile(py_spy=find_py_spy(ROOT, _from_root(args.py_spy) if args.py_spy else None),
                                     output_dir=output, cwd=_from_root(args.cwd),
                                     duration_seconds=args.duration, rate_hz=args.rate,
                                     python_executable=_from_root(args.python),
                                     target=_from_root(args.target) if args.target else None,
                                     target_args=target_args, pid=args.pid, include_idle=args.include_idle,
                                     include_subprocesses=args.subprocesses)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"성능 프로파일러 오류: {error}", file=sys.stderr)
        return 1
    print(f"수집 완료: {destination}\nFlame Graph: profile.speedscope.json을 Speedscope에서 열고 Left Heavy 선택")
    print("AI 분석: summary.json / 실행 조건: session.json / 수집 로그: collector.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

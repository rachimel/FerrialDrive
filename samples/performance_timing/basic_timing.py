"""게임·Pico2D 없이 호출 집계와 반복 측정 JSON을 만드는 최소 예제."""

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ferrial_drive.diagnostics import TimingRecorder


def main():
    parser = argparse.ArgumentParser(description="선택적 성능 계측 최소 예제")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--output", type=Path,
                        default=PROJECT_ROOT / "output/performance/timing_sample.json")
    arguments = parser.parse_args()
    recorder = TimingRecorder(enabled=True, session="timing_sample")
    values = tuple(range(256))

    def calculate():
        return sum(value * value for value in values)

    measured = recorder.wrap(calculate, name="sample.calculate")
    with recorder.scope("sample.batch"):
        for _ in range(10):
            measured()
    recorder.benchmark("sample.repeat", calculate, iterations=arguments.iterations,
                       repeat=arguments.repeat, warmup=arguments.warmup)
    print(f"성능 로그 저장: {recorder.write_json(arguments.output)}")


if __name__ == "__main__":
    main()

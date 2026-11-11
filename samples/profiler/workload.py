"""성능 프로파일러 독립 시연

정수 계산과 짧은 대기를 반복하여 서로 다른 호출 경로를 만든다.
게임 에셋·Pico2D·창 없이 실행한다.
"""

import argparse
from time import perf_counter, sleep


def calculate():
    return sum(number * number for number in range(100_000))


def update():
    return calculate()


def draw():
    return calculate() + calculate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=4.0)
    args = parser.parse_args()
    deadline = perf_counter() + args.seconds
    while perf_counter() < deadline:
        update()
        draw()
        sleep(0.005)


if __name__ == "__main__":
    main()

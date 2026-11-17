"""오버드라이브의 선택적 무지개 팔레트. 게임 시계와 저장 테마를 소유하지 않는다."""

from colorsys import hsv_to_rgb
from math import isfinite


def rainbow_color(elapsed_seconds, cycle_seconds=3):
    if (not isfinite(elapsed_seconds) or elapsed_seconds < 0
            or not isfinite(cycle_seconds) or cycle_seconds <= 0):
        raise ValueError("무지개 팔레트의 경과 시간은 0 이상, 순환 주기는 양수 초 단위 값이어야 한다.")
    rgb = hsv_to_rgb((elapsed_seconds / cycle_seconds) % 1, 0.8, 1)
    return "#" + "".join(f"{round(value * 255):02X}" for value in rgb)

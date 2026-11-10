"""UI의 가벼운 원근·기울기 투영. 렌더러와 게임 상태에 의존하지 않는다."""

from dataclasses import dataclass
from math import isfinite


def scaled_point(point, anchor, amount):
    return tuple(center + (value - center) * amount for value, center in zip(point, anchor))


def slanted_meter(bar, ratio=1):
    """채움 끝도 외곽과 같은 사선인 평행사변형. 직사각형 클립을 쓰지 않는다."""
    x, y, width, height = bar
    cut = min(18, height * 0.65)
    fill_width = width * max(0, min(1, ratio))
    return ((x - cut, y), (x - cut + fill_width, y),
            (x + fill_width, y + height), (x, y + height))


def energy_frame(bar, level_width, level_rise):
    """게이지 오른쪽 접점에서 레벨 외곽까지 이어지는 단일 실루엣."""
    x, y, width, height = bar
    join, right = x + width, x + width + level_width
    return ((x - 20, y - 5), (join - 16, y - 5), (join - 24, y - level_rise),
            (right - 18, y - level_rise + 4), (right + 5, y + 8),
            (right - 7, y + height + 4), (x + 8, y + height + 4))


@dataclass(frozen=True)
class PerspectivePlane:
    x: float
    y: float
    width: float
    height: float
    depth: float = 0.25
    lean: float = 0.15
    slope: float = 0.06

    def __post_init__(self):
        if not all(isfinite(value) for value in (self.x, self.y, self.width, self.height,
                                                self.depth, self.lean, self.slope)):
            raise ValueError("UI 투영 값은 유한해야 한다.")
        if self.width <= 0 or self.height <= 0 or not 0 <= self.depth <= 1:
            raise ValueError("투영 크기는 양수, 원근 강도는 0~1이어야 한다.")

    def point(self, x, y):
        denominator = 1 + self.depth * (1 - x / self.width)
        local_y = (y - self.height / 2) / denominator
        local_x = x / denominator
        return (self.x + local_x - self.lean * local_y,
                self.y + local_y + self.height / 2 + self.slope * local_x)

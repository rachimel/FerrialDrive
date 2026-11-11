"""흡수 Trail과 패널 Scanline의 시간 상태. 입력·렌더러와 분리한다."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ScanlineVisual:
    line_offset_pixels: float = 0
    highlight_travel_pixels: float = 0
    elapsed_seconds: float = 0


class ScanlineMotion:
    def __init__(self, spacing_pixels, slow_speed_pixels_per_second, fast_speed_pixels_per_second):
        if (not all(map(isfinite, (spacing_pixels, slow_speed_pixels_per_second, fast_speed_pixels_per_second)))
                or spacing_pixels <= 0 or not 0 <= slow_speed_pixels_per_second < fast_speed_pixels_per_second):
            raise ValueError("Scanline 간격은 양수이며 밝은 띠의 속도가 기본 스크롤보다 커야 한다.")
        self.spacing_pixels = spacing_pixels
        self.slow_speed_pixels_per_second = slow_speed_pixels_per_second
        self.fast_speed_pixels_per_second = fast_speed_pixels_per_second
        self.reset()

    def reset(self):
        self.visual = ScanlineVisual()

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("Scanline 갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        self.visual = ScanlineVisual(
            (self.visual.line_offset_pixels + self.slow_speed_pixels_per_second * delta_seconds) % self.spacing_pixels,
            self.visual.highlight_travel_pixels + self.fast_speed_pixels_per_second * delta_seconds,
            self.visual.elapsed_seconds + delta_seconds)


def _bezier(points, amount):
    while len(points) > 1:
        points = tuple((a[0] + (b[0] - a[0]) * amount,
                        a[1] + (b[1] - a[1]) * amount)
                       for a, b in zip(points, points[1:]))
    return points[0]


@dataclass
class AbsorptionTrail:
    start: tuple[float, float]
    icon: tuple[float, float]
    destination: tuple[float, float]
    duration_seconds: float
    elapsed_seconds: float = 0.0

    def point(self, amount):
        amount = max(0.0, min(1.0, amount))
        sx, sy = self.start
        ix, iy = self.icon
        dx, dy = self.destination
        if amount <= 0.72:
            return _bezier(((sx, sy), (sx + 90, sy + 100),
                            (ix - 90, iy - 110), (ix, iy)), amount / 0.72)
        return _bezier(((ix, iy), (ix + 55, iy + 55),
                        (dx - 75, dy + 30), (dx, dy)), (amount - 0.72) / 0.28)

    @property
    def progress(self):
        return self.elapsed_seconds / self.duration_seconds


class EnergyAbsorption:
    def __init__(self, duration_seconds=0.85):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("흡수 효과 시간은 양수인 초 단위 값이어야 한다.")
        self.duration_seconds = duration_seconds
        self.trails = []

    def add(self, start, icon, destination):
        if not all(isfinite(value) for point in (start, icon, destination) for value in point):
            raise ValueError("흡수 효과 좌표는 유한한 화면 픽셀이어야 한다.")
        self.trails.append(AbsorptionTrail(tuple(start), tuple(icon), tuple(destination),
                                          self.duration_seconds))
        # 빠른 반복 입력에서도 표시 효과의 수를 제한한다.
        self.trails = self.trails[-24:]

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("효과 갱신 시간은 0 이상의 초 단위 값이어야 한다.")
        for trail in self.trails:
            trail.elapsed_seconds += delta_seconds
        self.trails = [trail for trail in self.trails if trail.progress < 1.3]

    def clear(self):
        self.trails.clear()

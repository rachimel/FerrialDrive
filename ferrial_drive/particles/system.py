"""CPU는 요청·시간만 보관한다. 입자 생성·경로 선택·수명·이동 상태는 GPU가 소유한다."""

from dataclasses import dataclass
from math import isfinite
from secrets import randbits


DEFAULT_PROFILES = (
    ((30, -45), (-30, 30), (15, -15), (-15, -5)),
    ((-45, -20), (35, -50), (25, -30), (-10, -10)),
    ((55, 30), (20, -55), (-15, -20), (20, -5)),
    ((-30, 50), (-55, -15), (30, -10), (-20, -20)),
    ((65, -25), (-10, 45), (10, -35), (-25, -5)),
    ((-60, 5), (55, 25), (-20, -25), (15, -15)),
)


@dataclass(frozen=True)
class SpawnParticles:
    start: tuple
    waypoint: tuple
    destination: tuple
    count: int
    side: int
    spread_pixels: float
    duration_seconds: float
    effect_type: int = 0


@dataclass(frozen=True)
class StepParticles:
    delta_seconds: float


class GpuParticleSystem:
    def __init__(self, duration_seconds=0.85, *, capacity=24, paths_by_side=None,
                 tail_fraction=0.3, seed=None):
        if type(capacity) is not int or not 1 <= capacity <= 65536:
            raise ValueError('입자 풀 크기는 1~65536의 정수여야 한다.')
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError('입자 수명은 양수인 초 단위 값이어야 한다.')
        if not isfinite(tail_fraction) or not 0 < tail_fraction <= 1:
            raise ValueError('꼬리 비율은 0 초과 1 이하여야 한다.')
        self.capacity, self.duration_seconds = capacity, duration_seconds
        self.tail_fraction = tail_fraction
        self.seed = randbits(32) if seed is None else int(seed) & 0xffffffff
        profiles = paths_by_side if paths_by_side is not None else {
            'left': DEFAULT_PROFILES,
            'right': tuple(tuple((-x, y) for x, y in profile) for profile in DEFAULT_PROFILES),
        }
        self.profiles = []
        for key in ('left', 'right'):
            entries = profiles[key]
            if len(entries) != 6 or any(len(entry) != 4 or any(len(point) != 2
                    or not all(map(isfinite, point)) for point in entry) for entry in entries):
                raise ValueError('방향별 고정 경로 6개와 후보별 유한한 제어점 4개가 필요하다.')
            self.profiles.extend(tuple(tuple(point) for point in entry) for entry in entries)
        self.profiles = tuple(self.profiles)
        self.commands = []
        self.generation = 0

    def emit(self, start, waypoint, destination, *, count=3, side=-1, spread_pixels=15,
             duration_seconds=None, effect_type=0):
        if any(len(point) != 2 or not all(map(isfinite, point)) for point in (start, waypoint, destination)):
            raise ValueError('생성 좌표는 유한한 화면 픽셀의 두 성분이어야 한다.')
        if type(count) is not int or count <= 0 or side not in (-1, 1):
            raise ValueError('요청 수는 양수 정수이며 방향은 -1 또는 1이어야 한다.')
        duration = self.duration_seconds if duration_seconds is None else duration_seconds
        if not isfinite(duration) or duration <= 0 or not isfinite(spread_pixels) or spread_pixels < 0:
            raise ValueError('수명은 양수이며 생성 간격은 0 이상이어야 한다.')
        if effect_type != 0:
            raise ValueError('현재 지원하는 효과 종류는 에너지 오브 0이다.')
        self.commands.append(SpawnParticles(tuple(start), tuple(waypoint), tuple(destination),
                                            min(count, self.capacity), side, spread_pixels, duration, effect_type))

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError('갱신 시간은 0 이상의 유한한 초 단위 값이어야 한다.')
        if delta_seconds == 0:
            return
        if self.commands and isinstance(self.commands[-1], StepParticles):
            delta_seconds += self.commands.pop().delta_seconds
        self.commands.append(StepParticles(delta_seconds))

    def clear(self):
        self.commands.clear()
        self.generation += 1

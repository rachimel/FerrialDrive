"""CPU는 요청·시간만 보관한다. 입자 생성·경로 선택·수명·이동 상태는 GPU가 소유한다."""

from dataclasses import dataclass
from math import isfinite
from secrets import randbits

ENERGY_UNITS = 1_000_000


DEFAULT_PROFILES = (
    ((30, -45), (-30, 30), (15, 0), (-15, 0)),
    ((-45, -20), (35, -50), (25, 2), (-10, 1)),
    ((55, 30), (20, -55), (-15, 0), (20, 2)),
    ((-30, 50), (-55, -15), (30, 3), (-20, 1)),
    ((65, -25), (-10, 45), (10, 1), (-25, 3)),
    ((-60, 5), (55, 25), (-20, 2), (15, 0)),
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
    gain_units: int = 0
    arrival_spacing_seconds: float = 0


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
        self.energy_target = None
        self.energy_charge_total = None
        self._clear_receipts()

    def _clear_receipts(self):
        self.arrived_units = self.arrived_count = self.cancelled_units = 0
        self.requested_gain_units = self.received_gain_units = self.lost_gain_units = 0
        self._gain_ready = self._arrivals_ready = 0

    @property
    def pending_gain_units(self):
        return max(0, self.requested_gain_units - self.received_gain_units - self.lost_gain_units)

    def set_energy_target(self, left, right, ratio, *, charge_total=None):
        if (any(len(point) != 2 or not all(map(isfinite, point)) for point in (left, right))
                or not isfinite(ratio) or not 0 <= ratio <= 1):
            raise ValueError('에너지 바 목표 좌표와 0~1 비율이 필요하다.')
        self.energy_target = (*left, *right, ratio)
        if charge_total is not None and (not isfinite(charge_total) or not 0 <= charge_total <= 4):
            raise ValueError('누적 충전량은 0~4이어야 한다.')
        self.energy_charge_total = charge_total

    def accept_receipt(self, units, count, cancelled):
        gain = (units - self.arrived_units) & 0xffffffff
        arrivals = (count - self.arrived_count) & 0xffffffff
        lost = (cancelled - self.cancelled_units) & 0xffffffff
        self.arrived_units, self.arrived_count, self.cancelled_units = units, count, cancelled
        self.received_gain_units += gain
        self.lost_gain_units += lost
        self._gain_ready += gain
        self._arrivals_ready += arrivals
        if self.energy_target is not None:
            *geometry, ratio = self.energy_target
            if self.energy_charge_total is None:
                ratio = min(1, ratio + gain / ENERGY_UNITS)
            else:
                self.energy_charge_total = min(4, self.energy_charge_total + gain / ENERGY_UNITS)
                total = self.energy_charge_total
                ratio = total - 3 if total >= 3 else total % 1
            self.energy_target = (*geometry, ratio)

    def take_arrivals(self):
        result = self._gain_ready / ENERGY_UNITS, self._arrivals_ready
        self._gain_ready = self._arrivals_ready = 0
        return result

    def emit(self, start, waypoint, destination, *, count=3, side=-1, spread_pixels=15,
             duration_seconds=None, effect_type=0, gain_ratio=0, arrival_spacing_seconds=0):
        if any(len(point) != 2 or not all(map(isfinite, point)) for point in (start, waypoint, destination)):
            raise ValueError('생성 좌표는 유한한 화면 픽셀의 두 성분이어야 한다.')
        if type(count) is not int or count <= 0 or side not in (-1, 1):
            raise ValueError('요청 수는 양수 정수이며 방향은 -1 또는 1이어야 한다.')
        duration = self.duration_seconds if duration_seconds is None else duration_seconds
        if not isfinite(duration) or duration <= 0 or not isfinite(spread_pixels) or spread_pixels < 0:
            raise ValueError('수명은 양수이며 생성 간격은 0 이상이어야 한다.')
        if effect_type not in (0, 1):
            raise ValueError('지원 효과는 에너지 오브 0·경계 불꽃 1이다.')
        if (not isfinite(gain_ratio) or not 0 <= gain_ratio <= 1
                or not isfinite(arrival_spacing_seconds) or arrival_spacing_seconds < 0):
            raise ValueError('회복 비율은 0~1이며 도착 간격은 0 이상의 초 단위 값이어야 한다.')
        units = round(gain_ratio * ENERGY_UNITS)
        if effect_type == 1 and (units or arrival_spacing_seconds):
            raise ValueError('경계 불꽃은 회복·도착 간격을 사용하지 않는다.')
        self.commands.append(SpawnParticles(tuple(start), tuple(waypoint), tuple(destination),
                                            min(count, self.capacity), side, spread_pixels, duration, effect_type,
                                            units, arrival_spacing_seconds))
        self.requested_gain_units += units

    def emit_sparks(self, top, bottom, *, count=1, duration_seconds=0.65, spread_pixels=2):
        self.emit(top, bottom, (0, 0), effect_type=1, count=count, side=1,
                  spread_pixels=spread_pixels, duration_seconds=duration_seconds)

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
        self._clear_receipts()

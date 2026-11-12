"""레벨 세 구간과 추가 Overdrive 충전 한 구간의 예제 규칙."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class EnergyCharge:
    total: float

    def __post_init__(self):
        if not isfinite(self.total) or not 0 <= self.total <= 4:
            raise ValueError('누적 충전량은 0~4 구간이어야 한다.')

    @classmethod
    def from_state(cls, state):
        if state.overdrive:
            return cls(4)
        return cls(min(4, state.energy_level - 1 + state.energy_ratio + state.overdrive_charge_ratio))

    def add(self, amount):
        if not isfinite(amount):
            raise ValueError('충전 변화량은 유한해야 한다.')
        return EnergyCharge(min(4, max(0, round(self.total + amount, 6))))

    @property
    def level(self):
        return min(3, int(self.total) + 1)

    @property
    def ratio(self):
        return min(1, self.total - (self.level - 1))

    @property
    def overdrive_ratio(self):
        return max(0, self.total - 3)

    @property
    def arrival_ratio(self):
        return self.overdrive_ratio if self.total >= 3 else self.ratio

    @property
    def active(self):
        return self.total >= 4


def energy_color(base, red, ratio):
    """충전 정도에 따른 표시 색상. 바와 VFX가 같은 보간을 사용한다."""
    if isinstance(base, str):
        base = tuple(int(base[i:i + 2], 16) for i in (1, 3, 5))
    rgb = tuple(round(a + (b - a) * ratio) for a, b in zip(base, red))
    return '#' + ''.join(f'{value:02X}' for value in rgb)

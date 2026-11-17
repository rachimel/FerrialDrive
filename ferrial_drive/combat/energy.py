"""실제 에너지 용량·레벨별 표시 비율·회복 후 자연 감소를 계산한다."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class EnergySettings:
    level_capacities: tuple = (100, 200, 400)
    overdrive_capacity: float = 200
    decay_margin_seconds: float = 2
    decay_per_second: float = 0.5
    absorption_gain_multiplier: float = 1

    def __post_init__(self):
        capacities = tuple(self.level_capacities)
        if len(capacities) != 3 or any(not isfinite(value) or value < 1 for value in capacities):
            raise ValueError("에너지 레벨 용량은 1 이상의 유한값 세 개여야 한다.")
        if not isfinite(self.overdrive_capacity) or self.overdrive_capacity <= 0:
            raise ValueError("Overdrive 추가 용량은 양수 유한값이어야 한다.")
        if any(not isfinite(value) or value < 0 for value in (self.decay_margin_seconds, self.decay_per_second)):
            raise ValueError("에너지 유예 초·초당 감소량은 0 이상의 유한값이어야 한다.")
        if not isfinite(self.absorption_gain_multiplier) or not 0 <= self.absorption_gain_multiplier <= 1:
            raise ValueError("명중 흡수 배율은 0~1의 유한값이어야 한다.")
        object.__setattr__(self, "level_capacities", capacities)

    @property
    def capacity(self):
        return sum(self.level_capacities)


@dataclass(frozen=True)
class EnergyAmount:
    amount: float = 0
    overdrive_amount: float = 0
    settings: EnergySettings = EnergySettings()

    def __post_init__(self):
        if (not isfinite(self.amount) or not 0 <= self.amount <= self.settings.capacity
                or not isfinite(self.overdrive_amount)
                or not 0 <= self.overdrive_amount <= self.settings.overdrive_capacity):
            raise ValueError("에너지는 일반·Overdrive 각각의 용량 안에 있어야 한다.")

    @classmethod
    def from_display(cls, total, settings=None):
        settings = settings or EnergySettings()
        if not isfinite(total) or not 0 <= total <= 4:
            raise ValueError("에너지 표시 충전량은 0~4여야 한다.")
        amount = sum(capacity * max(0, min(1, total - index))
                     for index, capacity in enumerate(settings.level_capacities))
        return cls(amount, max(0, total - 3) * settings.overdrive_capacity, settings)

    @classmethod
    def from_ratios(cls, level, ratio, overdrive_ratio, settings=None):
        settings = settings or EnergySettings()
        if (type(level) is not int or not 1 <= level <= 3
                or any(not isfinite(value) or not 0 <= value <= 1 for value in (ratio, overdrive_ratio))):
            raise ValueError("에너지 레벨은 1~3, 충전 비율은 0~1이어야 한다.")
        amount = sum(settings.level_capacities[:level - 1]) + ratio * settings.level_capacities[level - 1]
        return cls(amount, overdrive_ratio * settings.overdrive_capacity, settings)

    @property
    def level(self):
        first, second, _ = self.settings.level_capacities
        return 3 if self.amount >= first + second else 2 if self.amount >= first else 1

    @property
    def ratio(self):
        level = self.level
        return (self.amount - sum(self.settings.level_capacities[:level - 1])) / self.settings.level_capacities[level - 1]

    @property
    def overdrive_ratio(self):
        return self.overdrive_amount / self.settings.overdrive_capacity

    @property
    def display_total(self):
        return self.level - 1 + self.ratio + (self.overdrive_ratio if self.amount == self.settings.capacity else 0)

    def recover(self, amount):
        """일반 용량을 채운 뒤 초과량을 별도의 Overdrive 충전에 더한다."""
        if not isfinite(amount) or amount < 0:
            raise ValueError("에너지 회복량은 0 이상의 유한값이어야 한다.")
        regular = min(self.settings.capacity, self.amount + amount)
        extra = min(self.settings.overdrive_capacity,
                    self.overdrive_amount + max(0, self.amount + amount - self.settings.capacity))
        return EnergyAmount(regular, extra, self.settings)

    def recover_ratio(self, ratio):
        """기존 HUD 시연의 회복 비율을 실제 레벨별 용량으로 변환한다."""
        if not isfinite(ratio) or ratio < 0:
            raise ValueError("에너지 회복 비율은 0 이상의 유한값이어야 한다.")
        general = self.level - 1 + self.ratio
        regular = EnergyAmount.from_display(min(3, general + ratio), self.settings).amount
        extra = min(self.settings.overdrive_capacity,
                    self.overdrive_amount + max(0, general + ratio - 3) * self.settings.overdrive_capacity)
        return EnergyAmount(regular, extra, self.settings)

    def consume(self, amount):
        """일반 에너지만 소모하며 레벨 하락 시 이전 게이지 최대치−1을 적용한다."""
        if not isfinite(amount) or amount < 0:
            raise ValueError("에너지 소비량은 0 이상의 유한값이어야 한다.")
        current, remaining = self.amount, amount
        boundaries = (self.settings.level_capacities[0], sum(self.settings.level_capacities[:2]))
        for boundary in reversed(boundaries):
            if current >= boundary and current - remaining < boundary:
                remaining -= current - boundary
                current = boundary - 1
        return EnergyAmount(max(0, current - remaining), self.overdrive_amount, self.settings)


class EnergyDecay:
    def __init__(self, settings=None):
        self.settings = settings or EnergySettings()
        self.reset()

    def reset(self):
        self.grace_remaining_seconds = self.settings.decay_margin_seconds

    def update(self, delta_seconds, *, suspended=False):
        """유예를 넘긴 실제 시간에 해당하는 에너지 소비량을 반환한다."""
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("에너지 감소 갱신 시간은 0 이상의 유한한 초여야 한다.")
        if suspended:
            return 0
        decay_seconds = max(0, delta_seconds - self.grace_remaining_seconds)
        self.grace_remaining_seconds = max(0, self.grace_remaining_seconds - delta_seconds)
        return decay_seconds * self.settings.decay_per_second

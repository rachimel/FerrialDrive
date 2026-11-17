"""충전·Standby·발동의 실제 시간과 강화 수치를 관리한다."""

from dataclasses import dataclass, fields
from math import isfinite


@dataclass(frozen=True)
class OverdriveSettings:
    standby_seconds: float = 3
    cooldown_seconds: float = 30
    duration_seconds: float = 10
    animation_speed: float = 2
    movement_speed: float = 1.5
    cooldown_speed: float = 2
    trail_scale: float = 1.15
    pitch_scale: float = 1.1
    sword_damage: int = 150
    standby_tint_ratio: float = 0.18
    standby_rim_strength: float = 0.25

    def __post_init__(self):
        if any(not isfinite(getattr(self, field.name)) or getattr(self, field.name) <= 0 for field in fields(self)):
            raise ValueError("Overdrive의 시간·속도·배율은 양수 유한값이어야 한다.")
        if (type(self.sword_damage) is not int or self.standby_tint_ratio > 1
                or self.standby_rim_strength > 1 or not .5 <= self.pitch_scale <= 2):
            raise ValueError("Overdrive의 피해량·색·피치 범위 오류")


class OverdriveController:
    def __init__(self, settings=None):
        self.settings = settings or OverdriveSettings()
        self.reset()

    def reset(self):
        self.phase = "charging"
        self.standby_remaining_seconds = 0.0
        self.active_remaining_seconds = 0.0
        self.cooldown_remaining_seconds = 0.0
        self.charge_total = 0.0

    @property
    def active(self):
        return self.phase == "active"

    @property
    def ready(self):
        return self.phase == "standby"

    def observe_charge(self, total):
        if not isfinite(total) or not 0 <= total <= 4:
            raise ValueError("Overdrive 충전량은 0~4여야 한다.")
        self.charge_total = total
        if self.phase == "charging" and total >= 4 and self.cooldown_remaining_seconds <= 0:
            self.phase = "standby"
            self.standby_remaining_seconds = self.settings.standby_seconds
            self.cooldown_remaining_seconds = self.settings.cooldown_seconds

    def activate(self, *, force=False):
        if self.active or not (self.ready or force):
            return False
        self.phase = "active"
        self.standby_remaining_seconds = 0.0
        self.active_remaining_seconds = self.settings.duration_seconds
        if force:
            self.cooldown_remaining_seconds = max(self.cooldown_remaining_seconds, self.settings.cooldown_seconds)
        return True

    def cancel(self):
        self.phase = "charging"
        self.standby_remaining_seconds = self.active_remaining_seconds = 0.0

    def update(self, seconds):
        """실제 초로 갱신하고 만료 시 적용할 에너지 총량을 반환한다."""
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("Overdrive 갱신 시간은 0 이상의 유한값이어야 한다.")
        remaining, reset_total = seconds, None
        while remaining > 1e-10:
            boundary = (self.standby_remaining_seconds if self.ready else self.active_remaining_seconds
                        if self.active else self.cooldown_remaining_seconds
                        if self.charge_total >= 4 and self.cooldown_remaining_seconds > 0 else remaining)
            elapsed = min(remaining, boundary)
            self.cooldown_remaining_seconds = max(0, self.cooldown_remaining_seconds - elapsed)
            remaining = max(0, remaining - elapsed)
            if self.ready:
                self.standby_remaining_seconds = max(0, self.standby_remaining_seconds - elapsed)
                if self.standby_remaining_seconds <= 1e-10:
                    self.cancel()
                    reset_total = self.charge_total = 2
            elif self.active:
                self.active_remaining_seconds = max(0, self.active_remaining_seconds - elapsed)
                if self.active_remaining_seconds <= 1e-10:
                    self.cancel()
                    reset_total = self.charge_total = 0
            self.observe_charge(self.charge_total)
        return reset_total

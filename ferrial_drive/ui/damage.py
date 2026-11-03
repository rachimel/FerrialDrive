"""이번 피해량의 표시 수명과 이동. 누적 피해와 원본 HP는 변경하지 않는다."""

from dataclasses import dataclass
from math import isfinite

from ..animation import ScalarAnimation


@dataclass(frozen=True)
class DamageVisual:
    amount: int
    x: float
    y: float
    opacity: float
    owner: str = ""


@dataclass
class DamagePopup:
    owner: str
    amount: int
    x: float
    y: float
    animation: ScalarAnimation


class DamageNumbers:
    def __init__(self, duration_seconds: float, rise_pixels: float):
        if not isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("피해 숫자 표시 시간은 양수인 초 단위 값이어야 한다.")
        if not isfinite(rise_pixels) or rise_pixels < 0:
            raise ValueError("피해 숫자 이동량은 0 이상이어야 한다.")
        self.duration_seconds = duration_seconds
        self.rise_pixels = rise_pixels
        self.popups: list[DamagePopup] = []

    def add(self, owner: str, amount: int, x: float, y: float):
        if amount <= 0:
            return
        self.popups.append(DamagePopup(owner, amount, x, y,
                                       ScalarAnimation(0, 1, self.duration_seconds)))

    def update(self, delta_seconds):
        for popup in self.popups:
            popup.animation.update(delta_seconds)
        self.popups = [popup for popup in self.popups if not popup.animation.finished]

    def clear(self, owner: str | None = None):
        if owner is None:
            self.popups.clear()
        else:
            self.popups = [popup for popup in self.popups if popup.owner != owner]

    @property
    def visuals(self) -> tuple[DamageVisual, ...]:
        return tuple(DamageVisual(popup.amount, popup.x,
                                  popup.y - self.rise_pixels * popup.animation.value,
                                  1 - popup.animation.value, owner=popup.owner) for popup in self.popups)

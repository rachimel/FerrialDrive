"""표시 위치와 입력 판정이 공유하는 도형·버튼 상태."""

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def contains(self, x: float, y: float, padding: float = 0) -> bool:
        return (self.x - padding <= x < self.x + self.width + padding
                and self.y - padding <= y < self.y + self.height + padding)

    def translated(self, offset_x: float, offset_y: float = 0) -> "Rect":
        return Rect(self.x + offset_x, self.y + offset_y, self.width, self.height)


@dataclass(frozen=True)
class Button:
    button_id: str
    action: str
    label: str
    rect: Rect
    hit_padding: float = 0
    enabled: bool = True


@dataclass(frozen=True)
class InputResult:
    consumed: bool = False
    action: str | None = None


class ButtonInput:
    """좌클릭 누름을 포획하고 같은 버튼 안에서 놓았을 때 동작을 반환한다."""

    def __init__(self) -> None:
        self.hovered_id: str | None = None
        self.pressed_id: str | None = None

    def reset(self) -> None:
        self.hovered_id = None
        self.pressed_id = None

    def handle(self, kind: str, x: float, y: float,
               buttons: Iterable[Button], offset_x: float = 0) -> InputResult:
        buttons = tuple(buttons)
        hit = next((button for button in reversed(buttons)
                    if button.rect.translated(offset_x).contains(
                        x, y, button.hit_padding)), None)
        self.hovered_id = hit.button_id if hit and hit.enabled else None
        if kind == "move":
            return InputResult(self.pressed_id is not None)
        if kind == "down":
            self.pressed_id = hit.button_id if hit and hit.enabled else None
            return InputResult(hit is not None)
        if kind == "up":
            captured = self.pressed_id
            self.pressed_id = None
            action = hit.action if hit and hit.enabled and hit.button_id == captured else None
            return InputResult(captured is not None or hit is not None, action)
        raise ValueError(f"지원하지 않는 포인터 입력: {kind}")

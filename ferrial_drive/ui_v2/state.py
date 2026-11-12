"""게임에서 직접 공급할 수 있는 v2 HUD 표시 데이터."""

from dataclasses import dataclass
from math import isfinite

from ferrial_drive.ui.state import HudState
from ferrial_drive.ui.components import Rect


@dataclass(frozen=True)
class DialogueInfo:
    speaker: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class HudV2State:
    hud: HudState
    energy_ratio: float
    energy_level: int
    overdrive: bool = False
    counter: bool = False
    dash_ready: bool = True
    target_body: Rect | None = None
    dialogue: DialogueInfo | None = None
    overdrive_charge_ratio: float = 0

    def __post_init__(self):
        if not isfinite(self.energy_ratio) or not 0 <= self.energy_ratio <= 1:
            raise ValueError("에너지 표시 비율은 0~1이어야 한다.")
        if type(self.energy_level) is not int or not 1 <= self.energy_level <= 3:
            raise ValueError("에너지 레벨은 1~3의 정수여야 한다.")
        if not isfinite(self.overdrive_charge_ratio) or not 0 <= self.overdrive_charge_ratio <= 1:
            raise ValueError('Overdrive 추가 충전 비율은 0~1이어야 한다.')
        body = self.target_body
        if body is not None and (not all(isfinite(value) for value in (body.x, body.y, body.width, body.height))
                                 or body.width <= 0 or body.height <= 0):
            raise ValueError("표적 몸통은 유한한 화면 좌표와 양수 크기가 필요하다.")

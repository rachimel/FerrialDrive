"""게임에서 직접 공급할 수 있는 v2 HUD 표시 데이터."""

from dataclasses import dataclass
from math import isfinite

from ferrial_drive.ui.state import HudState


@dataclass(frozen=True)
class HudV2State:
    hud: HudState
    energy_ratio: float
    energy_level: int
    overdrive: bool = False
    counter: bool = False
    dash_ready: bool = True

    def __post_init__(self):
        if not isfinite(self.energy_ratio) or not 0 <= self.energy_ratio <= 1:
            raise ValueError("에너지 표시 비율은 0~1이어야 한다.")
        if type(self.energy_level) is not int or not 1 <= self.energy_level <= 3:
            raise ValueError("에너지 레벨은 1~3의 정수여야 한다.")

"""게임과 UI 테스트가 공유하는 표시용 값. 엔티티·실행기에 의존하지 않는다."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Health:
    current: float
    maximum: float

    def __post_init__(self):
        if not all(isfinite(value) for value in (self.current, self.maximum)):
            raise ValueError("HP는 유한한 값이어야 한다.")
        if self.maximum <= 0 or not 0 <= self.current <= self.maximum:
            raise ValueError("HP 최대값은 양수이고 현재값은 0~최대값이어야 한다.")

    @property
    def ratio(self):
        return self.current / self.maximum


@dataclass(frozen=True)
class TargetInfo:
    name: str
    health: Health


@dataclass(frozen=True)
class RadarContact:
    """플레이어 기준 상대 좌표. 감지 거리 설정과 같은 단위를 사용한다."""

    x: float
    y: float
    kind: str = "enemy"

    def __post_init__(self):
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError("레이더 좌표는 유한한 값이어야 한다.")
        if self.kind not in ("enemy", "ally"):
            raise ValueError("레이더 종류는 enemy 또는 ally여야 한다.")


@dataclass(frozen=True)
class HudState:
    player_health: Health
    target: TargetInfo | None
    combo_count: int
    total_damage_dealt: int
    radar_contacts: tuple[RadarContact, ...]

    def __post_init__(self):
        if self.combo_count < 0 or self.total_damage_dealt < 0:
            raise ValueError("콤보와 누적 피해는 음수일 수 없다.")

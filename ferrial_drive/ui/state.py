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
    """감지용 상대 좌표와 카메라 투영 후 화면 픽셀 좌표를 함께 전달한다."""

    x: float
    y: float
    screen_x: float
    screen_y: float
    kind: str = "enemy"

    def __post_init__(self):
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError("레이더 좌표는 유한한 값이어야 한다.")
        if not isfinite(self.screen_x) or not isfinite(self.screen_y):
            raise ValueError("레이더 대상의 화면 좌표는 유한한 픽셀 값이어야 한다.")
        if self.kind not in ("enemy", "ally"):
            raise ValueError("레이더 종류는 enemy 또는 ally여야 한다.")


@dataclass(frozen=True)
class WeaponInfo:
    name: str
    rounds: int | None = None
    image_path: str | None = None
    base_attribute: str = ""
    additional_attributes: tuple[str, ...] = ()
    auxiliary_kind: str | None = None
    auxiliary_image_path: str | None = None

    def __post_init__(self):
        if self.rounds is not None and (type(self.rounds) is not int or self.rounds < 0):
            raise ValueError("잔탄수는 0 이상의 정수 또는 None이어야 한다.")
        if not isinstance(self.base_attribute, str):
            raise ValueError("기본 속성 표시는 문자열이어야 한다.")
        if not isinstance(self.additional_attributes, (tuple, list)) or any(
                not isinstance(value, str) or not value.strip() for value in self.additional_attributes):
            raise ValueError("추가 속성은 비어 있지 않은 표시 문자열 목록이어야 한다.")
        object.__setattr__(self, "additional_attributes", tuple(self.additional_attributes))
        if self.auxiliary_kind not in (None, "back_weapon", "counter"):
            raise ValueError("보조 슬롯은 back_weapon 또는 counter여야 한다.")


@dataclass(frozen=True)
class LoadoutInfo:
    melee: WeaponInfo
    ranged: WeaponInfo

    def __post_init__(self):
        if self.melee.rounds is not None or self.ranged.rounds is None:
            raise ValueError("근접 무기는 잔탄이 없고 원거리 무기는 잔탄수가 필요하다.")


@dataclass(frozen=True)
class HudState:
    player_health: Health
    target: TargetInfo | None
    combo_count: int
    total_damage_dealt: int
    radar_contacts: tuple[RadarContact, ...]
    attack_direction_x: int = 1
    loadouts: tuple[LoadoutInfo, ...] = ()
    active_loadout_index: int = 0
    active_weapon_kind: str = "ranged"

    def __post_init__(self):
        if self.combo_count < 0 or self.total_damage_dealt < 0:
            raise ValueError("콤보와 누적 피해는 음수일 수 없다.")
        if self.attack_direction_x not in (-1, 1):
            raise ValueError("공격 좌우 방향은 왼쪽 -1 또는 오른쪽 1이어야 한다.")
        if len(self.loadouts) > 2:
            raise ValueError("로드아웃은 최대 2세트다.")
        if (type(self.active_loadout_index) is not int
                or not 0 <= self.active_loadout_index < max(1, len(self.loadouts))):
            raise ValueError("활성 로드아웃 번호가 표시 세트 범위를 벗어났다.")
        if self.active_weapon_kind not in ("melee", "ranged"):
            raise ValueError("현재 무기는 melee 또는 ranged여야 한다.")

"""공통 UI 부품 검사의 가짜 상태. 실행 창이나 입력 처리가 없다."""
from pathlib import Path
from types import SimpleNamespace
import json
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.state import Health, HudState, LoadoutInfo, RadarContact, TargetInfo, WeaponInfo

def make_ui_fixture():
    directory = Path(__file__).resolve().parents[2] / "samples/ui_unit_test"
    data = json.loads((directory / "hud_sample.json").read_text(encoding="utf-8"))
    target = data["target"]
    state = HudState(Health(**data["player_health"]), TargetInfo(target["name"], Health(**target["health"])),
                     data["combo_count"], data["total_damage_dealt"],
                     tuple(RadarContact(**entry) for entry in data["radar_contacts"]), data["attack_direction_x"],
                     tuple(LoadoutInfo(WeaponInfo(**row["melee"]), WeaponInfo(**row["ranged"])) for row in data["loadouts"]),
                     data["active_loadout_index"], data["active_weapon_kind"])
    return SimpleNamespace(config=UiConfig(directory / "ui_config.json"), sample=SimpleNamespace(state=state))

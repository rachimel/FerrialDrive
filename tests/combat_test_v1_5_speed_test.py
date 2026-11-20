"""Combat Test v1.5 · 플레이어 이동 3배속
기본 30기 또는 선택한 대형과 약출력 대시 150m/s·강출력 대시 300m/s·부스트 시작 750m/s로 교전한다.
공격 전진도 3배이며 WASD 이동·Shift 대시·Space 부스트·좌클릭 공격·F5 재시작을 사용한다.
성능 측정은 hardware_profile_benchmark.py --scenario combat --movement-speed-multiplier 3을 사용한다.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UNIT_TEST_ENTRYPOINT = "standalone"
UNIT_TEST_PRESETS = (
    {"id": "standard", "label": "기본 교전 · 30기", "args": []},
    {"id": "crowd_900", "label": "900기 · 24m · 무음", "args": ["--enemy-count", "900", "--enemy-spacing-m", "24", "--mute"]},
    {"id": "crowd_1000", "label": "1,000기 · 24m · 무음", "args": ["--enemy-count", "1000", "--enemy-spacing-m", "24", "--mute"]},
)


def main():
    sys.path.insert(0, str(ROOT))
    from ferrial_drive.combat.encounter_application import EncounterApplication
    from ferrial_drive.combat.movement_launcher import launch_movement_test

    launch_movement_test(description=__doc__, application_type=EncounterApplication,
                         encounter_path=ROOT / "samples/combat_test_v1_5/encounter.json",
                         movement_speed_multiplier=3,
                         window_title="Ferrial Drive | Combat Test v1.5")


if __name__ == "__main__":
    main()

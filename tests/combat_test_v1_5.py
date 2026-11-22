"""Combat Test v1.5 · 소형·중형·인간형 교전
기존 이동·검·기관단총·록온·HUD에 소형 22기·중형 6기·인간형 2기의 전투를 연결한다.
WASD 이동, Shift 대시, Space 부스트, 좌클릭 공격, E 무기 전환, F5 재시작.
성능 측정·보고서는 hardware_profile_benchmark.py --scenario combat을 사용한다.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UNIT_TEST_ENTRYPOINT = "standalone"
UNIT_TEST_SUPPORTS_MUTE = True
UNIT_TEST_PRESETS = (
    {"id": "standard", "label": "기본 교전 · 30기", "args": []},
    {"id": "crowd_900", "label": "900기 · 24m", "args": ["--enemy-count", "900", "--enemy-spacing-m", "24"]},
    {"id": "crowd_1000", "label": "1,000기 · 24m · HP 10만",
     "args": ["--enemy-count", "1000", "--enemy-spacing-m", "24", "--player-hp", "100000"]},
)


def main():
    sys.path.insert(0, str(ROOT))
    from ferrial_drive.combat.encounter_application import EncounterApplication
    from ferrial_drive.combat.movement_launcher import launch_movement_test

    launch_movement_test(description=__doc__, application_type=EncounterApplication,
                         encounter_path=ROOT / "samples/combat_test_v1_5/encounter.json",
                         window_title="Ferrial Drive | Combat Test v1.5")


if __name__ == "__main__":
    main()

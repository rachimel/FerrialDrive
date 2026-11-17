"""Combat Test v1.5 · 플레이어 이동 3배속
소형 22기·중형 6기·인간형 2기와 이동 90m/s·대시 300m/s·부스트 시작 750m/s로 교전한다.
공격 전진도 3배이며 WASD 이동·Shift 대시·Space 부스트·좌클릭 공격·F5 재시작을 사용한다.
성능 측정은 hardware_profile_benchmark.py --scenario combat --movement-speed-multiplier 3을 사용한다.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UNIT_TEST_ENTRYPOINT = "standalone"


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

"""검 이동 3배속 테스트
일반 이동 90m/s·대시 300m/s·부스트 시작 750m/s와 공격 전진 3배를 시험한다.
모션 재생·가감속 시간·1km 맵은 유지한다. WASD 이동, Shift 대시, Space 부스트, 좌클릭 공격.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UNIT_TEST_ENTRYPOINT = "standalone"


def main():
    sys.path.insert(0, str(ROOT))
    from ferrial_drive.combat.movement_launcher import launch_movement_test

    launch_movement_test(description=__doc__, movement_speed_multiplier=3)


if __name__ == "__main__":
    main()

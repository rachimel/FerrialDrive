"""오버드라이브 무지개색 훈련장
오버드라이브 중 기체 림·검 Trail·HUD의 색을 함께 순환한다.
F6 강제 발동·해제, 좌클릭 검 공격, WASD 이동, Esc 일시정지, F5 초기화.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UNIT_TEST_ENTRYPOINT = "standalone"


def main():
    sys.path.insert(0, str(ROOT))
    from ferrial_drive.combat.movement_launcher import launch_movement_test

    launch_movement_test(description=__doc__, overdrive_rainbow=True)


if __name__ == "__main__":
    main()

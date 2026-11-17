"""이동·UI 훈련장
1km 훈련장에서 검 콤보·총 사격/조준·무기 전환과 레벨/Overdrive 발광을 확인한다.
WASD 이동, Shift 대시, Space 부스트, 좌클릭 공격, 우클릭 조준, E/F 무기/로드아웃, Esc 일시정지.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UNIT_TEST_ENTRYPOINT = "standalone"


def main():
    sys.path.insert(0, str(ROOT))
    from ferrial_drive.combat.movement_launcher import launch_movement_test

    launch_movement_test(description=__doc__)


if __name__ == "__main__":
    main()

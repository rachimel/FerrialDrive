"""도형 기체 1대1 전투

이동·대시·검과 기관단총·적 한 기와의 교전을 확인한다.
일반 적은 별도 공격 경고 없이 동작을 보고 회피한다.
Enter 시작, Esc 일시정지, R 재시작, F10 종료.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ferrial_drive.combat.application import CombatApplication
from ferrial_drive.runtime import run_application


UNIT_TEST_ENTRYPOINT = "standalone"
SCENARIO_PATH = ROOT / "samples/combat_prototype/combat_config.json"
UI_CONFIG_PATH = ROOT / "samples/ui_unit_test/ui_config.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=SCENARIO_PATH)
    parser.add_argument("--frames", type=int)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()
    window = json.loads(UI_CONFIG_PATH.read_text(encoding="utf-8"))["window"]
    program = CombatApplication(args.config, UI_CONFIG_PATH, profile_path=args.profile)
    run_application(program, width=window["width"], height=window["height"],
                    title="Ferrial Drive | Combat Prototype", frame_limit=args.frames,
                    timings=program.timings)


if __name__ == "__main__":
    main()

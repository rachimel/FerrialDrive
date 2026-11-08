"""FDrive 에셋 로더

이미지·시트·번들 미리보기와 등록을 확인한다.
디버그 모드에서 원본 변경과 실패 복구를 확인한다.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UNIT_TEST_ENTRYPOINT = "standalone"


if __name__ == "__main__":
    from Tools.asset_loader.run import main
    main()

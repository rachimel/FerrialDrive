# 공통 테스트 실행기 아이콘 드롭 지원

- 작성일: 2026-11-03, 한국 시간
- 사용자 결정: 실행기 아이콘에 테스트 `.py`를 드롭해 시작하며, 기존 인자 실행과 같은 로더를 사용한다.

## 구현

- `Tools/unit_test_runner/create_launcher.py`: 실행한 Python 환경에 연결된 Windows `.lnk`를 생성한다. 추가 패키지 없이 Windows 기본 PowerShell·WScript.Shell을 사용한다. 경로는 스크립트 문자열에 삽입하지 않고 환경 변수로 전달한다.
- 로컬 `Tools/unit_test_runner/workspace/Unit Test Runner.lnk`를 현재 `game2d` Python으로 생성했다. 개인 경로가 든 바로가기는 기존 workspace 제외 규칙에 따라 Git에 포함하지 않는다.
- `desktop_launcher.py`: 파일 인자와 옵션을 기존 `run.py`에 전달한다. 사용법 오류·파일 오류·실행 오류가 있으면 종료 코드를 유지하고 Enter를 기다려 내용을 확인할 수 있게 한다.
- `run.main(argv)`로 인자 진입점을 공유한다. 테스트별 UI·입력·데이터·애니메이션과 실행 루프의 책임은 변경하지 않았다.

## 검증

- 기존 20개와 런처 검사 8개를 합한 **자동 검사 28개 통과**.
- 공백·한글·`&`·`!`·작은따옴표·`%`가 있는 도구·테스트 경로를 확인했다.
- 잘못된 파일, 여러 파일, 미입력, 잘못된 factory, 기존 옵션 전달과 도움말·정상 종료의 대기 생략을 확인했다.
- 생성한 바로가기의 Python 대상·인자·작업 폴더와 실제 Windows Shell 실행을 확인했다.
- Computer Use로 파일 탐색기에서 프로브 `.py`를 실행기 바로가기에 실제 드롭했다. 테스트 초기화가 남긴 `output/runner_drag_verification/drop_probe.loaded`에서 `drop_received`를 확인했다.
- 두 화면 샘플도 실제 드롭했고, Pico2D 창의 시작 화면·문구·경과 시간 표시를 확인했다.
- 이후 사용자가 **직접 조작하겠다**고 하여 UI 자동 조작을 중단했다. Esc·버튼 조작의 완료 여부와 사용감은 사용자 확인으로 남긴다. 해당 요청 뒤 새 자동 검사를 실행하지 않았다.

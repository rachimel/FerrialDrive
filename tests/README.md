# 직접 실행 확인

1. `Unit Test Runner.lnk`를 더블클릭해 Python GUI를 연다.
2. 같은 폴더의 **`ui_test.py`를 열린 GUI 창에 드롭**한다.
3. Esc로 메뉴·전투 HUD를 전환하고, 피해·타겟·초기화 버튼을 확인한다. 메뉴의 테스트 종료로 대기 화면에 복귀한다.

`ui_test.py`는 실제 메뉴·전투 HUD 테스트다. [표시 규칙과 조작 순서](../samples/ui_unit_test/README.md)를 따른다. 이번 구현은 사용자 실행·조작 확인 전이다.

`basic_flow.py`는 바로 확인하기 위해 `samples/unit_test_runner/basic_flow.py`를 복사한 샘플이다. 독립 실행 규약은 [공통 실행기 안내](../Tools/unit_test_runner/README.md)를 따른다.

자동 검사 코드는 `automated/`에 분리했다. GUI에 드롭할 파일은 `ui_test.py` 또는 공통 실행기 최소 샘플 `basic_flow.py`다. 바로가기는 현재 로컬 Python에 연결되며 Git에서 제외한다.

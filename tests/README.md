# 직접 실행 확인

1. `Unit Test Runner.lnk`를 더블클릭해 Python GUI를 연다.
2. 같은 폴더의 **`ui_test.py`를 열린 GUI 창에 드롭**한다.
3. 별도 UI 테스트 창에서 피해·타겟·초기화 버튼과 Esc 일시정지·계속·타이틀 복귀를 확인한다. 설정 버튼은 타이틀·일시정지에 비활성으로 배치돼 있다. 메뉴 종료·UI 창 X는 해당 테스트만 닫고 Runner는 유지한다. 같은 파일을 Runner에 다시 드롭하면 이전 테스트를 종료하고 새로 실행한다.

`ui_test.py`는 Runner 없이 `python tests/ui_test.py`로 직접 실행할 수 있는 메뉴·전투 HUD 테스트다. Runner 창 X는 소유한 테스트도 종료한다. [표시 규칙과 조작 순서](../samples/ui_unit_test/README.md)를 따른다. [현재 작업 상태](../docs/unit-tests/ui_checkpoint.md)에서 사용자 시안 마감과 최근 변경의 실행 미확인을 구분한다.

`basic_flow.py`는 바로 확인하기 위해 `samples/unit_test_runner/basic_flow.py`를 복사한 샘플이다. 독립 실행 규약은 [공통 실행기 안내](../Tools/unit_test_runner/README.md)를 따른다.

`asset_load_test.py`는 기본 도형의 실제 Blender 8방향 렌더·본체/그림자 시트 생성·Pico2D 로딩을 확인한다. Runner 목록에서 선택하거나 창에 드롭한다. 최초 생성에 Blender가 필요하며 설정이 같은 다음 실행은 성공 결과를 재사용한다. R로 다시 생성하고 Space·방향 카드·본체/그림자 토글로 확인한다. [샘플과 실행 안내](../samples/asset_load_test/README.md)를 따른다.

자동 검사 코드는 `automated/`에 분리했다. GUI에 드롭할 파일은 `ui_test.py`, `asset_load_test.py` 또는 공통 실행기 최소 샘플 `basic_flow.py`다. 바로가기는 현재 로컬 Python에 연결되며 Git에서 제외한다.

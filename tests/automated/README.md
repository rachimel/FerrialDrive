# 자동 검사

Pico2D가 설치된 환경에서 프로젝트 루트 기준으로 실행한다.

```text
python -m unittest discover -s tests/automated -q
python -m unittest discover -s tests/automated -p test_movement_hud_integration.py -v
python -m unittest discover -s tests/automated -p "test_unreal*.py" -v
```

이동·전투·UI·에셋 검증·도구·Runner와 Unreal 수치/이관을 검사한다. 실제 OpenGL·로컬 에셋이 필요한 검사는 각 파일의 선택 조건을 따른다. `ui_fixture.py`는 공통 UI 부품 검사용 입력이다.

직접 조작용 진입점은 [상위 목록](../README.md)을 따른다. 자동 검사·지정 입력 렌더·물리 키보드/마우스 조작·사용자 외관 승인은 별도로 기록한다. 검증 이력은 `docs/ai-dev-log/`에서 관리한다.

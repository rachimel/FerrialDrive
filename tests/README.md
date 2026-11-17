# 직접 실행 확인

Pico2D가 설치된 Python으로 실행하거나 Unit Test Runner에서 파일을 선택·드롭한다. Runner는 별도 프로세스로 실행하며 새 파일을 실행하면 이전 테스트를 종료한다.

| 진입점 | 확인 범위 |
| --- | --- |
| `sword_movement_test.py` | 이동·검 4타·부스트·보간·훈련 표적·UI v2 |
| `sword_movement_speed_test.py` | 동일 훈련장의 3배속 시험 |
| `overdrive_rainbow_test.py` | 오버드라이브 기체 림·검 Trail·HUD의 무지개 순환 시험 |
| `combat_test.py` | 기본 도형의 검/기관단총·적 한 기 교전·승패 |
| `combat_test_v1_5.py` | 소형 22기·중형 6기·인간형 2기의 다수 교전·검 넉백·기존 플레이어/HUD 연결 |
| `combat_test_v1_5_speed_test.py` | 같은 30기 교전에서 플레이어 이동·공격 전진 3배 |
| `asset_loader_test.py` | 2D 에셋 툴 |
| `frame_interpolation_unreal_test.py` | 로컬 Unreal 검 동작의 보간·블러 비교 |
| `texture_compression_test.py` | 텍스처 압축·화질·저장량 비교 |
| `massive_energy_particle_stress.py` | GPU 입자 부하·단계별 시간 비교 |

~~~text
python tests/sword_movement_test.py
python tests/sword_movement_test.py --demo
~~~

이동·UI 조작은 [훈련장 안내](../samples/sword_movement/README.md), UI 범위는 [공통 명세](../docs/unit-tests/ui_unit_test.md)를 따른다. `--demo`는 실제 게임 에셋 없이 공개 도형·수치로 실행한다.

`automated/`는 화면을 직접 조작하는 프로그램 목록과 분리한 자동 검사다. Unreal 수치·이관 검사도 이 폴더에서 실행한다. `rendering/`은 실제 GPU 픽셀 검사를 담는다. 자동 검사 통과와 사용자 직접 조작·외관 승인은 구분한다.

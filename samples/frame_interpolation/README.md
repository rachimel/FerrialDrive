# 프레임 보간 검사 입력

`fixture.py`는 이동·회전·가림의 공개 도형과 수치 모션 벡터를 만든다. `tests/automated/test_frame_interpolation.py`에서 공통 보간·블러 경로와 픽셀을 검사한다.

Unreal 검 콤보 비교는 `python tests/frame_interpolation_unreal_test.py`로 실행하며 로컬 프리렌더 입력이 필요하다. 이동·UI 훈련장은 `python tests/sword_movement_test.py --demo`로 게임 에셋 없이 실행한다.

[위상·데이터·검증 범위](../../docs/unit-tests/frame_interpolation.md)를 따른다.

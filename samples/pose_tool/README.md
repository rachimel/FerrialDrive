# Pose Tool 독립 샘플

실제 메카/이미지/게임 실행 없이 기본 큐브와 직접 작성한 리그·3개 동작으로 포즈 도구를 시연한다. Blender만 필요하다. 메카와 같은 기본 본 매핑을 사용한다.

```powershell
python Tools/pose_tool/run.py --sample
python Tools/asset_loader/run.py --pose-sample
```

두 실행 모두 Blender 창을 연다. 작업본과 샘플 원본은 `Tools/pose_tool/workspace/<실행시각>/`에 분리해 저장한다. 샘플 원본을 수정하지 않는다. `N` → **Pose Tool**에서 손바닥 이동, 실제 관절 손잡이의 팔꿈치/무릎 방향, 골반 이동과 발 고정, 동작 전환과 포즈 키 저장을 확인한다. 검사는 `tests/blender/check_pose_native.py`를 사용한다.

샘플에는 기본 도형으로 만든 손목·손가락과 총·칼·칼집 파츠 및 칼집 정렬 기준점을 포함한다. Blender 패널에서 월드 이동/회전, 손가락 조작과 주먹/펴기, 이전 프레임 복제, 자동 정렬, Ctrl+Z를 시연한다. 실제 무기의 형상·파지·삽입 여유나 수납 모션을 검증하는 샘플은 아니다. 이전 내장 화면의 검사 진입점은 호환용으로 유지한다.

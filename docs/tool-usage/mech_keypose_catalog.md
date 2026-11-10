# 메카 키포즈 카탈로그

기존 [기본 무기 애니메이션 사양](../ai-asset-pipeline/basic_weapon_animations.md)의 동작을 정지 키포즈 묶음으로 검토한다. 원본 모델과 옛 후보를 보존하고 새 작업본을 만든다. 키포즈 번호는 자세 ID이며 동작 길이·타격 프레임·연결 타이밍이 아니다.

## 제작과 검토

- 공통 제작: `Tools/blender_pipeline/keypose_pipeline.py -- --config 요청.json --output 새작업본폴더`. Blender의 `--python`으로 실행한다.
- 숫자 요청과 자세별 설명: `Tools/blender_pipeline/workspace/<asset_id>/`.
- 결과: `animations.blend`, `clips.json`, `keypose_groups.json`, `pose_measurements.json`.
- 기존 `model_pipeline.py`의 `operations: []`와 `review`로 저장·재로딩 후 6면·사선의 확대/표시 크기 이미지를 만든다. `model_review.py`에 AI 판단과 사용자 응답을 따로 남긴다.
- `keypose_gallery.py --catalog keypose_groups.json --review 검토폴더`는 이미지·자세 ID·동작 묶음을 연결한 `index.html`과 240px 접촉 시트를 만든다. Pillow가 필요하다. 게임 에셋의 렌더·패킹 경로와 구분한다.
- `check_keypose_catalog.py`는 기준 해시·메시 구조·rest 본·기존 본 제약 보존·연결 본·발 접지를 독립 검사한다. `--source`, `--settings`, `--output`은 기존 독립 검사 규약과 같다.

정지 키포즈 카탈로그의 검토 렌더는 `review.engine="BLENDER_WORKBENCH"`, `disable_bevel=true`를 선택할 수 있다. 형상을 생략하지 않으며 재질 최종 렌더를 대신하지 않는다. 기본값은 기존 Cycles다. `per_frame_framing=true`는 자세별 범위로 카메라를 맞추되 그 자세의 모든 방향·크기에 같은 범위를 적용한다. 연결 애니메이션이나 게임 시트에는 이 자동 구도 변경을 적용하지 않는다.

## 현재 초안의 해석

- 기준은 사용자가 지정한 `data/models/basic_weapons/base_pose.blend`다. 기준 해시는 로컬 요청에 기록한다.
- 이번 초안에는 각도 Constraint와 임시 허용각을 추가하지 않는다. 굽힘 수치는 측정 기록이며 허용각 통과 판정이 아니다.
- 전체 실루엣·실제 굽힘 면·관절 연결·체중 방향·발 접지·파지를 함께 검토한다. IK 도달이나 자동 검사만으로 자연스러운 자세를 승인하지 않는다.
- 총의 손 파지 기준점은 새 후보에서만 보정한다. 부모 본과 수납 슬롯 대응은 유지한다.
- 총 슬롯 접근 후보의 손잡이 접촉은 미해결이다. 명시적인 `allow_stow_approach`만 미도달 목표까지의 거리를 기록하고 접근 자세를 만든다. 접촉 성공으로 판정하지 않는다.
- 보행의 하체 방향과 상하체 파츠 분리 구조는 미정이다. 정면 조준 상태의 전후좌우 스텝은 검토 후보이며 설계 확정이 아니다.
- 대시 중 무기 전환의 접촉 경로, 칼집 길이 방향의 연속 인출, 전체 장갑 간섭, 타이밍·판정·게임 연결은 별도 확인한다.

게임과 독립된 시연은 [기본 도형 샘플](../../samples/keypose_pipeline/README.md)을 사용한다. 실제 후보에 대한 AI 검토와 사용자 피드백은 [애니메이션 제작 흐름](../ai-asset-pipeline/animation_workflow.md)을 따른다.

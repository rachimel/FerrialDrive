# Blender 모델 제작 파이프라인 1차

새 모델과 기존 모델 수정은 **공통 모듈 + 에셋별 JSON**을 사용한다. 버전마다 Python 파일을 새로 복사하거나 구버전 스크립트를 연쇄 실행하지 않는다. 제작, 품질 검사, 게임 프리렌더는 서로 독립된 단계다.

메카의 조형 판단과 메시·계층·UV·리깅·애니메이션 기준은 [메카 디자인·제작 규칙](mech_design_rules.md)을 먼저 따른다. 이 문서는 실행 경로와 도구의 책임을 관리한다. 디자인 규칙의 존재와 현재 모델의 검증 완료를 구분한다.

플레이어 기체의 기준은 사용자가 확정한 **1차 최종 플레이어 모델 v078**이다. 최종 기준 경로·해시·승인 범위는 로컬 `data/models/player_mech/release_v1.json`에 기록한다. 새 에셋이 플레이어 모델이나 과거 버전 파일에 의존하게 만들지 않는다.

## 책임과 실행 파일

| 파일 | 책임 |
| --- | --- |
| `Tools/blender_pipeline/model_pipeline.py` | JSON 연산 적용, 원본 해시/수정 범위 확인, 새 후보 저장·재로딩, 선택적 검토 렌더 |
| `model_operations.py` | 설정으로 선택하는 공통 수정 연산 |
| `model_primitives.py` | 닫힌 단면을 이어 만드는 범용 메시 |
| `model_geometry.py` | root 좌표/Shape Key 변환, 장착 부모 프레임 보존 |
| `model_snapshot.py` | 객체 구조 지문 |
| `model_review.py` | 고정 6면 렌더, 이미지 근거 검증, AI 판단과 사용자 중간 OK 기록 |
| `model_design.py`, `model_design_schema.py` | 기존 부위/프로파일·본·재질·장착 편집 기능을 공통화한 JSON 편집기 |
| `export_model_registry.py` | 새 모델의 부위/본/제어 레지스트리 추출 |
| `check_model_geometry.py` | 독립 형상 검사 |
| `check_model_uv.py` | 독립 UV 검사 |
| `check_model_images.py` | 독립 이미지/패킹 검사 |
| `check_model_collisions.py` | 독립 자세별 접촉 쌍 검사 |
| `model_check_io.py` | 검사별 입력/JSON 출력만 공유. 검사를 묶어 실행하지 않음 |
| `inspect_model_dependencies.py` | 파일 정리 전 외부 의존성·패킹 확인 |
| `catalog_history.py` | 구버전 스크립트 정적 목록화. 실행하지 않음 |

## 작업 순서

1. 디자인·제작 규칙을 읽고 기준 버전·수정 부위·유지할 실루엣·참고 이미지의 대상 면을 정한다. 실루엣, 실제 형상, 음영, 도장 중 무엇을 바꾸는지 구분한다. 좌우·좌표계와 무기 마운트/인접 부품의 영향 범위를 명시한다. 위치가 애매할 때만 확인한다.
2. 기존 모델은 source 경로와 SHA-256을 고정한다. 새 모델은 source=null이다. 에셋별 JSON은 `Tools/blender_pipeline/workspace/<asset_id>/`에 둔다.
3. 공통 연산으로 새 후보를 만든다. 제작 CLI는 기존 원본/출력 폴더를 덮어쓰지 않는다. 사용자가 원본 수정을 명시한 경우에도 임시 후보에서 검증한 후 요청 경로에 반영하고 해시·레지스트리를 동기화한다. 생성 후 결과는 **candidate_unchecked**이며 검사나 승인이 끝났다는 뜻이 아니다.
4. 변경 종류에 맞는 검사 파일을 각각 실행한다. 검사 설정·결과 JSON도 종류별로 나눈다. 제작 명령에 모든 검사를 강제로 묶지 않는다.
5. AI가 사용자 요청에서 개선 목표·보존 대상·확인 항목을 정리하고, 고정 조건으로 앞/뒤/좌/우/위/아래 6면을 확대와 실제 표시 크기로 출력한다. 홈·관절·틈은 국소 확대, 동작은 주요 포즈도 포함한다. AI가 실제 이미지를 열어 요청과의 일치·미해결 결함·회귀를 판단한다. 시각적 확인과 자동 검사 결과를 구분한다.
6. AI 검토를 통과한 중간 이미지와 판단 근거를 사용자에게 제시한다. 사용자의 OK 또는 동등한 명시 응답 이후 다음 단계로 진행한다. AI가 찾은 명백한 불일치는 같은 단계에서 수정·재검토한다. 중간 OK는 해당 결과의 다음 단계 진행만 허용하며 정식 릴리스·전체 모션·게임 출력의 승인이 아니다.
7. 최종 사용자 승인 근거와 미검증 범위를 기록해 정식 모델 기준을 고정한다. 기존 프리렌더/패킹/게임 로더 경로로 넘긴다.

이미 허용된 수정·검사는 반복해서 허락을 받지 않는다. 별도로 요청된 중간 이미지 확인 시점에는 실제 결과를 제시하고 응답을 기다린다. 위험한 설계 선택은 구체적인 영향과 함께 의견을 확인한다.

애니메이션은 [애니메이션 제작 흐름](animation_workflow.md)을 함께 따른다. AI가 제시한 키포즈를 사용자 검수와 AI 수정으로 확정한 뒤 사이 동작을 연결한다. 정지 키포즈와 연결된 동작은 별도로 검수하며, 이 문서의 중간 이미지 승인만으로 동작 전체를 승인한 것으로 간주하지 않는다.

## JSON으로 모델 만들기

[기본 도형 샘플](../../samples/model_pipeline/README.md)을 실행하면 에셋별 Python 없이 모델을 만들 수 있다. 기존 `.blend`를 읽고 `operations: []`로 복사 후보만 만드는 것도 가능하다.

| 연산 | 입력/범위 |
| --- | --- |
| `create_empty` | name, 선택적 parent/location |
| `create_box` | name, size, parent/location, 선택적 material |
| `create_profile` | name, profiles: 동일 순서/정점 수의 3차원 단면 배열, capped, parent/material |
| `create_material` | name, color, roughness, metallic, 선택적 transmission/ior/coat |
| `add_bevel` | object, width, segments |
| `transform_vertices` | object, root, pivot, scale, offset. Basis와 Shape Key를 함께 변환 |
| `set_properties` | object, values. 이미 존재하는 장치 제어 속성만 변경 |
| `set_visibility` | object, hidden |
| `assign_material` | object, material, 기존 slot |
| `pack_images` | 파일/생성 이미지를 현재 후보에 패킹 |
| `apply_pbr_surface` | 기존 단일 Principled 재질의 색/거칠기/노멀에 외부 맵 적용. 부품 로컬 박스 투영, 선택적 UV 패널 도안. 발광 연결 유지 |
| `generate_panel_detail` | 지정 장갑면의 로컬 좌표 도안을 기존 UV에 투영하여 1K 색/높이 아틀라스 생성. UV/형상은 변경하지 않음 |
| `project_panel_uv` | 면 방향별 명시 영역에 패널 전용 UV 추가/명시 갱신(overwrite). projection_axis로 경사면을 같은 투영에 연결. 기존 다른 UV와 활성 렌더 UV 유지 |
| `generate_boundary_texture` | 실제 경계·급격한 꺾임을 1K 마스크로 생성. 다른 UV 보존. overwrite로 갱신, width_overrides로 부위별 선 폭, face_filters로 면 방향/위치 범위, disable_objects로 기존 대상 해제 |
| `apply_boundary_texture` | 연결된 표면 색에 구분선 마스크를 합성. 적용 속성이 없는 메시에는 표시하지 않으며 공유 재질·노멀·발광 유지 |
| `set_boundary_enabled` | objects, enabled. 기존 구분선 적용 속성만 켜거나 끈다. 공유 마스크·재질·모든 UV 보존 |
| `set_surface_finish` | 공통 PBR 재질의 거칠기 범위·모서리 거칠기·반사 강도 조정. 기본 선택에서 유리/발광 전용 재질 제외 |
| `set_frame` / `freeze_pose` | 검토 프레임 선택 / 후보 Armature의 Action·NLA를 멈추고 현재 포즈 유지. 드라이버는 유지 |
| `aim_bone` | object, bone, world_direction. 본 길이와 연결을 유지하며 후보 포즈 방향 조정 |
| `pose_limb` | object, upper/lower/end, target_world, bend_world, 선택적 end_rotation_world. 본 길이를 유지하는 두 관절 포즈. 도달 불가 목표는 실패 처리 |
| `repair_unweighted` | object, source, enabled=true. 가중치가 빠진 정점만 기준 메시의 가장 가까운 가중치 정점에서 보완한다. 기존 가중치·형상·본 계층은 보존한다. 기준과 대상은 동일한 모델 좌표 배치를 사용하며 보완 후 실제 변형을 별도 확인한다. |
| `attach_world` | object, parent, 선택적 bone, matrix_world. 평가된 부모 프레임에서 명시한 월드 배치 유지 |
| `attachment_switch` | control/property, stowed_target, held_target. 동일 오브젝트의 수납/파지 앵커 전환. 연속 발도 동작은 별도 |

생성 연산은 선택적으로 `rotation_degrees`와 `properties`를 받는다. 재질의 `energy_control`은 지정 객체의 `energy_color_r/g/b`, `energy_strength` 속성으로 발광을 구동한다. 검토 렌더는 `objects`로 확대 대상, `views`로 방향을 지정할 수 있다. 무기별 치수·포즈는 공통 코드에 넣지 않고 로컬 에셋 JSON으로 관리한다.

manifest의 `schema_version`은 1, `asset_id`는 에셋 식별자다. 기존 source에는 `source_sha256`이 필수다. 경로는 manifest 위치 기준으로 해석한다. `change_objects`에 수정할 기존 객체명을 선언하고 `allow_additions`로 새 객체 추가를 허용한다. source가 없는 새 에셋은 allow_additions=true를 사용한다.

지원하지 않는 조형은 버전별 `.py`로 우회하지 않는다. 새로운 일반 기능이면 공통 모듈/연산으로 한 번 구현하고 기본 도형으로 검증한다. 유일한 특수 조형이면 먼저 기존 Blender 편집과 후보 저장 경로로 처리할 수 있는지 판단하고, 자동화 범위를 명시한다. 모든 조형·리깅·UV 베이크를 현재 JSON 연산이 지원하는 것은 아니다.

출력 폴더에는 `candidate.blend`, `request.json`, `report.json`이 생긴다. `review`를 지정하면 기본 6방향 × 확대/표시 크기의 12장을 만든다. 기존 모델 수정은 `before/`, `after/`에 전후 24장을 출력한다. 연산이 없는 단순 조회/복사는 동일한 전후를 중복 렌더하지 않고 after 12장만 만든다. 기본 표시는 240px이며 실제 에셋 출력 크기가 다르면 `game_size`에 명시한다. 검토 장면의 카메라/광원은 후보 파일에 다시 저장하지 않는다. 검토 배율은 게임의 공통 출력 배율과 구별한다. 기존 검사/복사용 CLI의 `review` 생략은 호환되지만, AI 외형 작업에는 반드시 지정한다.

## 이미지 검토와 중간 확인

`review`는 root_object, 선택적 objects/views/frames, detail_size/game_size/samples와 `intent`를 받는다. `intent`의 goal(개선 목표), preserve(보존 대상 배열), criteria(id/expectation 배열)는 AI가 기존 요청에서 정리한다. 취향이나 위치가 모호할 때만 사용자에게 묻는다.

- 기존 모델은 수정 전의 프레임별 경계에서 중심/배율을 한 번 계산해 `review_fixture.json`에 고정한다. 후보에서도 같은 카메라·조명·프레임·색 관리·샘플 시드를 사용한다. 후보가 화면을 벗어나면 성공으로 판단하지 말고 양쪽을 포함하는 새 비교 조건을 정한다.
- `visual_review.json`에는 후보/이미지 해시, 촬영 조건 지문, 관찰 근거와 중간 확인 상태를 남긴다. 렌더 완료는 `awaiting_ai_review`다. 픽셀 차이만으로 품질을 자동 판정하지 않는다.
- AI는 제공된 모든 방향과 크기의 이미지를 직접 확인한다. `record_ai_review()` 또는 CLI의 `--ai-review`로 항목별 met/unmet/uncertain, 관찰 내용, 근거 이미지, 보존 여부, 다음 행동을 기록한다. 비교 항목은 전후 양쪽 이미지를 지정한다. 전 항목 충족이면 `awaiting_user`, 결함은 `needs_revision`, 판독 불가는 `uncertain`이다.
- 사용자에게 이미지와 판단을 제시한 뒤 실제 응답만 `--user-decision ok --statement "실제 응답"` 또는 revise로 기록한다. 아직 받지 않은 OK를 작성하지 않는다. OK는 `approved_for_next_stage`와 stage_approval=true이며 제작 보고서의 최종 visual_approval/quality_checks_run을 바꾸지 않는다.
- 중간 검토가 붙은 후보를 다음 수정·동작 생성·보정·베이크의 source로 쓰면 OK를 확인한다. 기존에 검토 기록이 없는 에셋을 소급 차단하지 않는다. 같은 단계의 결함 수정은 `review_revision=true`와 새 review를 지정하며, needs_revision/uncertain 후보에서만 승인 없이 반복할 수 있다.
- 이 절차는 AI 작업 절차와 로컬 기록이다. 별도 비전 모델의 자동 판정이나 사용자의 실제 응답을 검증하는 인증 시스템은 아니다. 승인된 파일로의 직접 교체와 기존 게임 출력 진입점까지 전역 차단하는 기능은 포함하지 않는다.

정점 위치만으로 목표 형상을 표현할 수 있는지 조형 전에 판단한다. 면 연결이 원인이면 문제 영역의 구성 방식을 바꾼다. 같은 가설과 방식으로 두 번 개선이 없으면 수치 튜닝을 중단한다. 범용 연산 추가는 실제로 반복되는 필요가 확인됐을 때 수행한다.

`report.json.timings`는 로딩·연산·저장/재로딩·검토 렌더·전체 경과 시간을 초 단위로 기록한다. 전체 시간에는 구조 지문 등 나머지 작업도 포함되므로 부분 항목 합계와 다를 수 있다. 실행 파일 시작 시간과 AI/사용자의 검토 시간은 별도다. 실행 예시는 [중간 검토 샘플](../../samples/model_pipeline/README.md#6면-중간-검토)이다.

팔 보정은 `allow_shift=false`가 기본이다. 손 위치 유지로 목표 손목 각도를 달성하지 못하면 requires_strategy_change와 unresolved_samples에 남기며, 도달 불가 위치는 오류로 처리한다. 목표 이동은 명시적 true에서만 허용한다. 동작 생성의 `weight_repair`는 enabled=true로 별도 요청해야 실행한다. `simplified_preview=true`는 형상을 생략하는 빠른 참고 화면이며 최종 외형 근거로 사용하지 않는다.

구조 지문은 좌표·면/재질 인덱스·UV·웨이트·Shape Key·부모/변환·본·사용자 속성·가시성을 확인한다. **모디파이어 설정, 재질 노드 내부, 드라이버 표현식, Action 전체의 동등성을 증명하지 않는다.** 해당 변경은 별도 검증이 필요하다. 제작 보고서의 `quality_checks_run`과 `visual_approval`은 false다.

## 독립 검사

모든 검사는 별도 백그라운드 Blender에서 source를 읽기만 한다. 명령에는 `--python-exit-code 1`을 넣어 Python 오류를 실패 종료로 전달한다. 설정과 결과는 검사별 파일로 나눈다. 실행 예시는 샘플 README에 있다.

| 검사 | 설정 | 판정과 한계 |
| --- | --- | --- |
| 형상 | required_objects, planarity_tolerance | 유한 좌표/면적 0 삼각형 오류. 비평면 면은 경고이며 자동 삼각분할 안 함 |
| UV | uv_objects, uv_layer | 0~1 범위/면적 0 검사. 아일랜드 겹침·패딩·밀도는 별도 |
| 이미지 | max_texture_size, require_packed | 파일/생성 이미지 크기와 패킹. 색공간/노드 연결은 별도 |
| 간섭 | collision_pairs, states | 평가된 메시의 면 교차. 완전한 내부 포함·거리 여유·연속 충돌은 미검증 |

UV 대상이나 간섭 쌍을 지정하지 않으면 `not_configured`를 기록하며 통과로 가장하지 않는다. `states`는 name/frame과 선택적인 properties 배열(object/property/value)로 구성한다. 각 상태 뒤 속성과 프레임은 복원한다. 서로 다른 포즈는 에셋의 Action/장치 제어와 연결해 명시한다. 누락된 메시·잘못된 속성·검사 오류는 실패로 기록한다.

**장착 슬롯/덮개 대 본체, 스커트 대 다리, 손 대 무기, 관절 내부**는 서로 다른 검사다. 한 항목의 성공을 다른 항목이나 전체 전투 모션의 성공으로 확대하지 않는다. UV가 범위 안이라는 사실도 텍스처 품질/아일랜드 겹침이 정상이라는 뜻은 아니다.

## 반복 작업에서 얻은 개선 규칙

아래는 도구 사용 시 주의할 좌표·평가 특성이다. 조형·표면·가동 검증의 상위 기준은 [디자인·제작 규칙](mech_design_rules.md#4-모델링과-데이터-구조)에서 관리한다.

- root 좌표계와 부품의 본/부모/모디파이어 순서를 먼저 확인한다. 플레이어 메카는 +X 전방/+Z 상방이지만 새 에셋에 무조건 하드코딩하지 않는다.
- VERTEX_3 장착은 표면과 정점 인덱스 변화에 영향을 받는다. 저장·재로딩·frame_set 후의 월드 위치까지 확인한다. `set_world_matrix_from_parent_frame()`는 평가된 부모 프레임에서 matrix_basis를 계산한다.
- 0도 AXIS_ANGLE 행렬은 회전축을 보존하지 못한다. 같은 부모 프레임으로 옮길 때는 로컬 축을 유지한다. 공통 장착 helper는 AXIS_ANGLE 입력을 거부한다.
- 비평면 면의 분할과 실제 형태 평탄화는 다르다. 삼각분할은 UV 보간/노멀/부울 결과를 바꿀 수 있으므로 같은 자세·조명에서 비교한다. 평평한 캡까지 무조건 smooth 처리하지 않는다.
- 스커트를 줄이면 다리 조인트와 장착부가 새로 충돌할 수 있다. 실루엣을 바꾸는 작업에는 인접 본체 부품 간섭 검사도 포함한다.
- 본의 기본 방향을 수정하면 제약/드라이버가 사용한 기존 로컬 회전축도 재검토한다. 좌우 Rest Pose가 대칭이어도 평가된 최종 자세는 비대칭일 수 있다.

## v001~v078 정보 요약

번호는 작업 이력이지 승인 순서가 아니다. 원문·실패·정정은 `docs/ai-dev-log/`와 로컬 작업 스크립트에 남긴다.

| 버전군 | 주요 작업 | 재사용할 정보 |
| --- | --- | --- |
| 001~006 | 체형·어깨/허리/다리와 초기 출력 | 큰 실루엣·축·기준점 먼저 |
| 007~023 | 손/머리/팔/발·관절 상세 | 부위 역할·본 연결·확대/축소 검토 |
| 024~036 | 주석 기반 단차/부피, 롤백, 재질 시험 | 승인 기준과 버전 번호 분리, 국소 수정 |
| 037~048 | 긴 다리·층진 허리·연결 스커트 | 단면과 연결부/관절의 동시 검토 |
| 049~060 | 고리·서브암·추진기·리액터 | 장치 계층/장착 프레임/가동 범위 |
| 061~062 | 설정 기반 부위 편집/레지스트리/UV | 기준 해시와 버전별 역할 목록 |
| 063~069 | 지역 UV·PBR·에너지·고해상도 | 기능별 도안·색공간·재질 책임 |
| 070~073 | 1K·볼 수납·전용 UV·중앙 링 | 텍셀 밀도·축 보존·검증 범위 |
| 074~076 | 팔 면·평판 스커트·열린 틈 | 본체 간섭 별도 검사·재로딩 장착 확인 |
| 077~078 | 테두리 위치 정정·파인 틈 발광 | 표현 이름보다 실제 위치 확인 |

`catalog_history.py`는 524개 Python 파일에서 해시·docstring·함수·버전 참조·동적 exec 사용을 정적으로 추출했다. v001~v078 참조가 모두 있으나 이는 모든 버전 재생산 성공의 증거가 아니다. 로컬 목록은 `output/model_pipeline/history_001_078.json`이다.

과거 문자열 치환/소스 조각 exec 연쇄는 새 경로에 가져오지 않는다. v061 전용 편집기에서 재사용할 기능은 `model_design.py`와 `model_design_schema.py`로 옮겼다. 레지스트리는 `export_model_registry.py`로 새 기준에서 다시 추출한다. 본 가중치별 자동 묶음 중 multi_bind는 편집 전 확인한다. [부위 편집 샘플](../../samples/mech_design/README.md)은 공통 편집기로 실행된다.

사용자 요청으로 과거 스크립트·설정·제어 문서 672개를 `Tools/blender_pipeline/99_Archives/player_mech_history_001_078.zip`에 검증 보관하고 중복 개별 파일 670개와 캐시를 정리했다. v001~v077 모델/출력물은 삭제했으므로 과거 스크립트 전체 재실행은 보장하지 않는다. 현재 작업 폴더는 기준/레지스트리·검사별 JSON과 README만 사용한다.

## 최종 모델과 게임 출력

로컬 `release_v1.json`은 **1차 최종 플레이어 모델**의 경로·해시·사용자 승인 범위를 고정한다. 모델 파일을 중복 복제하지 않는다. 후속 후보 생성은 해당 해시를 manifest의 source_sha256으로 사용한다. 외부 참조 없는 패킹 상태를 확인했으며 모델/텍스처/이미지는 공개 저장소에 넣지 않는다.

게임 출력은 기존 `asset_build.py` → `render_asset_sample.py` → `pack_sprites.py` → `ferrial_drive/assets/` 경로를 재사용한다. [Asset Load Test](../unit-tests/asset_load_test.md)의 `--scene` 입력으로 승인 모델을 넘기되 root/애니메이션/ShadowCatcher/카메라/공통 배율 등 기존 입력 계약을 맞춘다. 모델 검토 이미지와 게임 번들을 혼동하지 않는다.

1차 범위 밖: 범용 자동 조형·자동 리깅·UV 베이크/겹침·연속 충돌·전체 전투 모션·맵 구역 출력·승인 UI. v078을 새 공통 도구로 재생성했다고 주장하지 않는다.

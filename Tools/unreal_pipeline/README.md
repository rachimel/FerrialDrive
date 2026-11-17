# Unreal 새 리그와 애니메이션 조작

현행 기준은 **Blender 모델링 → 리그 없는 형상 → Unreal 새 리깅·애니메이션·프리렌더 → PNG 파츠+JSON → 툴 2D 조립·패킹 → Pico2D**이다. 기존 Blender 리그는 재사용하지 않는다. 프리렌더는 Unreal에서 수행하고 PNG 파츠+JSON을 툴의 2D 조립·패킹으로 인계한다.  [인계 조건](../../docs/ai-asset-pipeline/unreal_pipeline.md)과 [전체 동작 재생 검수](../../docs/ai-asset-pipeline/animation_workflow.md)를 따른다. 별도 KeyPose 사전 승인과 Pose Tool은 사용하지 않는다.

자동화 진입점·필수 실행 파일·런타임·요청과 보존 입력은 [automate](../../automate/README.md)에서 관리한다. `automate/unreal/`의 형상 인계·새 골격/웨이트·FK 제어점을 최소 도형으로 확인한다. 실제 메카의 새 리그·KeyPose·시각적 품질과 기존 출력 연결은 별도 완료 조건이다.

새 작업본을 여는 법과 제어점 선택·회전·이동·키 저장은 [Unreal 메카 편집 안내](../../docs/tool-usage/unreal_animation_editing.md)를 따른다.

## 기존 골격 왕복 실험의 구현 기록

아래는 기존 Blender 골격의 FK/Sequencer 조작과 FBX → 같은 골격 Action·별도 `.blend` 반환 기록이다. 새 제작의 리그로 재사용하지 않는다. 단일 동작·41개 초안 기록을 신규 리깅 전체 지원이나 사용자 품질 승인으로 확대하지 않는다.

## 기존 골격의 단일 동작 왕복 작업본

- 작업본: `workspace/roundtrip_20261110/`.
- Unreal 프로젝트: `UnrealProject/MechAnimationLab.uproject`.
- 맵: `/Game/MechLab/AnimationLab`, 편집 원본: `/Game/MechLab/RoughTorso`.
- 현재 Unreal 메시: `/Game/MechLab/PlayerMech_FollowFix`. 기존 `/Game/MechLab/PlayerMech`는 가중치 이름 연결 문제가 있었던 이전 사본이다.
- 소스: `data/source/models/basic_weapons/base_pose.blend`. 현재 교환본의 요청·매핑은 `export_follow_fix_request.json`과 `transfer_follow_fix/transfer_map.json`이다. 기존 사본의 기록은 보존한다.
- AI 초안 반환본: `return/rough_torso.blend`, 활성 Action: `Unreal_RoughTorso`.
- 사용자 수정 반환본: `return/user_torso.blend`, 활성 Action: `Unreal_UserTorso`. 두 파일 모두 30 FPS, 0~30프레임이다.
- AI 초안은 15프레임의 `chest_CONTROL` 로컬 Yaw가 8도이며, 사용자 수정본은 28도다. 양 끝은 0도다. 현재 본 축에서는 상체 기울기로 나타나는 간단한 연결 시험이다.

## 단일 동작 작업본의 기존 조작 절차

1. Unreal의 `RoughTorso` Sequence를 연다. 작업 인계 시 15프레임과 `chest_CONTROL`을 선택한다.
2. 상체 제어점이 선택된 상태에서 회전 값을 조금 수정한다. 기즈모는 E로 회전 모드에 들어간다.
3. Sequencer에서 해당 회전 채널의 다이아몬드 버튼으로 키를 저장하고 Ctrl+S로 Sequence를 저장한다.
4. AI에 수정 완료를 알린다. AI는 현재 Sequence를 새 Animation Sequence/FBX로 베이크한 뒤 새 `.blend`로 반환한다. `key_clip`을 다시 호출하지 않는다.

카메라는 뷰포트에서 우클릭을 누른 채 마우스/WASD로 이동한다. 이번 입력 필드에서는 사용자가 Enter로 값을 반영했고, MCP 조회에서 15프레임 키 28도를 확인했다. 사용자 직접 조작·수정본 반환은 한 차례 확인했으며 전반적인 편집 편의와 제작 품질 평가는 별도다.

## 현재 41개 초안에서 조작하기

1. `workspace/roundtrip_20261110/UnrealProject/MechAnimationLab.uproject`에서 `/Game/MechLab/Rebuild41_Map`을 연다.
2. 원하는 `/Game/MechLab/Rebuild41_<clip_name>` Sequence를 연다. 예: 검 1타는 `Rebuild41_sword_combo_1`이다.
3. Sequencer의 FK 제어점과 프레임을 선택해 조작하고 채널에 키를 저장한다. 전체 동작을 재생해 자세·타이밍·중간 궤적을 확인한 뒤 Sequence를 저장한다.
4. AI는 해당 `<clip_name>.request.json`을 사용해 `inspect_batch`로 현재 키를 읽고 필요하면 `open_clip`으로 Sequence·프레임·제어점을 연다. 사용자 편집 후 `create_batch_clip`·`key_batch_clip`을 재실행하지 않는다.
5. 현재 편집 키를 `export_batch_clip`으로 베이크한 뒤 새 출력 경로의 요청으로 `.blend`에 반환한다. 기존 FBX/반환본과 사용자 편집 Sequence는 보존한다. 반환 수치 검사와 사용자 재생 품질 검수는 별개다.

이 절차는 기존 골격 작업본의 조작 경로이며 신규 Unreal 리그 제작·반환 경로의 완료를 뜻하지 않는다. 조작 단축키와 베이크 개념은 [Epic FK Control Rig 안내](https://dev.epicgames.com/documentation/unreal-engine/fk-control-rig-in-unreal-engine)를 참고한다.

## 재사용 진입점

Blender는 `blender_transfer.py -- --request 요청.json`을 사용한다. 실행은 프로젝트 루트 기준이며 요청 내부의 상대 경로도 현재 작업 폴더 기준이다. 원본 해시가 다르거나 출력이 이미 있으면 거부한다.

| operation | 역할 |
| --- | --- |
| `export_model` 또는 생략 | 현재 평가 자세를 교환용 Rest Pose로 복사하고 FBX·본 이름 매핑 출력 |
| `import_animation` | FBX 본 행렬을 원래 리그 좌표계로 변환하고 새 Action·별도 blend 저장 |
| `verify_return` | 저장한 blend를 다시 열어 반환 FBX와 31개 정수 프레임·2개 중간 시각의 본 행렬 비교 |
| `create_sample` | 게임 에셋 없는 세 본·세 상자 샘플 생성 및 공통 FBX 출력 |
| `prepare_batch` | 기존 숫자 초안의 초기 이관용. 현재 소스 평가 → Unreal 본별 월드 키 JSON. 새 동작 편집 경로가 아님 |
| `import_batch` | Unreal의 클립별 FBX를 원래 리그·무기 객체 키와 구간 마커가 있는 별도 blend로 반환 |
| `verify_batch` | 저장·재로딩한 전 정수 프레임의 본·무기 행렬 및 원본 구조/패킹 이미지 비교 |
| `review_batch` | 반환 후보의 고정 6면 검토와 사선·측면 프레임 출력 |

Unreal은 `skills/mech-animation-lab`의 `animation_lab` MCP 도구를 사용한다. inspect → create_clip → 초기화 확인 → key_clip 순서다. 사용자 편집 이후에는 export_clip을 사용한다. open_clip은 편집 화면을 준비한다. 임의 Python 문자열을 실행하는 도구는 추가하지 않는다.

## 41개 동작 재제작 작업본

- 작업 위치: `workspace/roundtrip_20261110/rebuild41_20261110/`.
- 새 작업 맵: `/Game/MechLab/Rebuild41_Map`. Actor는 `PlayerMech_Rebuild41`, 현재 교환 메시는 `/Game/MechLab/PlayerMech_Anim41Ready`다. 기존 `AnimationLab`·`RoughTorso`·사용자 수정 반환본을 보존한다.
- `batch.json`은 41개 동작·405프레임, 12fps·동작당 최대 12프레임이다. 기존 3차 숫자 초안과 최신 검 대기 후보를 참고한 재제작 초안이며 최종 품질 승인이 아니다. 긴 구간을 줄일 때 무기 장착 이벤트의 표본을 보존한다.
- `export_model`의 `object_controls`에 등록한 무기만 교환 사본의 별도 본으로 출력한다. 원래 Blender 본 구조를 바꾸지 않는다. 반환에서는 원래 무기 객체에 키를 작성하고 해당 반환 사본의 장착 Constraint를 mute한다.
- 순서는 `create_batch_clip` → `inspect_batch`의 실제 제어점 초기화 확인 → `key_batch_clip` → `export_batch_clip`이다. 초기화는 다음 에디터 틱이 필요하므로 제어점이 없는 상태에서 키를 쓰지 않는다. `run_unreal_batch.py`는 이 순서를 정확한 MCP 도구 slug에 대해 실행하며, 실패·결과 유실 후 변경 호출을 자동 재전송하지 않는다.
- 새 Skeleton은 메시와 함께 저장한다. 30fps로 생성된 빈 Animation Sequence는 공배수인 60fps를 거쳐 12fps로 초기화한다. Sequence·베이크·FBX의 프레임 범위를 함께 설정한다.
- 맵은 작업 시작 전에 준비하며 클립별로 같은 이름의 레벨을 새로 저장하지 않는다. 재시작 뒤 FK 바인딩과 Skeleton 파일을 확인하고 이어간다. 복구 사본은 `recovery_backup/`에 해시 목록과 함께 보존한다.
- 반환 구간은 `.clips.json`과 Blender 타임라인 마커로 구분한다. `build_preview.py --catalog 구간.json --review 검토폴더`는 두 방향 프레임을 12fps 미리보기·프레임 슬라이더·접촉 시트로 묶는다. Pillow가 필요하다.
- 무기 루트 외의 가동 부품·형상 변화, 장갑 연속 간섭, 미정인 보행 방향 조합과 Pico2D 연결은 별도 검증 범위다. 재생 초안·자동 왕복 검사·사용자 수정·품질 승인을 구분한다.

메시 교환 수정은 import_mesh_candidate로 기존 Skeleton을 재사용하는 새 후보를 가져오고, 검증 후 bind_mesh_candidate로 현재 Actor에 연결한다. 기존 메시 에셋과 Sequence 키는 덮어쓰지 않는다.

본 왕복 수치 검사와 실제 스킨 추종은 별도다. `check_model_follow.py -- --source 모델.blend또는.fbx --output 새결과.json`은 잘못된 가중치 이름과 부모 회전 전달을 검사한다. 실제 Unreal에서 내보낸 메시에도 실행하여 교환 단계에서 끊긴 연결을 확인한다. 사용 가능한 축은 `--axis X/Y/Z`다.

## 보존과 한계

- Unreal은 `.blend`를 직접 출력하지 않는다. FBX로 베이크한 본 움직임을 원래 Blender 모델에 연결한다. Control Rig와 Blender 제약·드라이버를 서로 변환하는 경로가 아니다.
- 교환용 사본에서만 평가된 형상과 본을 복사한다. 본 이름의 점을 밑줄로 바꾸며 매핑을 저장한다. 원본 메시·본·UV·재질·장착 구조는 덮어쓰지 않는다.
- 단일 상체 시험은 장착 상태가 고정돼 있다. 41개 초안 경로는 등록된 무기 루트의 객체 키를 전달한다. 덮개·도신 변형 등 모든 가동 부품이나 수납/발도 경로의 품질까지 검증된 것은 아니다.
- Unreal 표시는 단순 재질이다. FBX 출력에서 기존 패킹 이미지 2개의 디스크 경로 누락 경고가 있었으며 Unreal 재질 이식의 완료를 주장하지 않는다. 반환 blend는 원본 재질과 패킹 이미지를 사용한다.
- 반환 애니메이션은 프레임별 본 키다. 기존 회전 모드와 4개 Pose Constraint를 유지했으며, 전체 동작·연속 간섭·Pico2D 재생은 미검증이다.
- 단일 상체 교환본은 71개 본, 무기 제어를 추가한 41개 초안 교환본은 73개 본이다. 기존 반환 매핑의 원래 본은 69개다. 이 숫자는 새 Unreal 리그의 공통 규격이 아니다.
- 샘플과 확인 범위는 [독립 시연 데이터](../../samples/unreal_pipeline/README.md)를 따른다.
- 모델·프로젝트·의존 패키지는 무시되는 workspace에, 캐시·이미지·검증 결과는 output에 둔다. 공개 코드에 생성 에셋을 포함하지 않는다.

기존 단일 동작의 검증 근거는 `output/unreal_roundtrip_setup/`, 반환 수치 검사는 `return/rough_torso.verification.json`과 `return/user_torso.verification.json`에 있다. 세부 상태는 [실험 기록](../../docs/ai-dev-log/2026-11-10-unreal-animation-review.md)에 남긴다.

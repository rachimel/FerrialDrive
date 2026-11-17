# Unreal 메카 제어점 편집

## 현재 작업본

- 프로젝트: `Tools/unreal_pipeline/workspace/roundtrip_20261110/UnrealProject/MechAnimationLab.uproject`
- 새 리그 폴더: `/Game/MechLab/FreshRigMech_20261110`
- 편집 맵: `MAP_Edit`, 편집 Sequence: `LS_KeyPoses`, 메시: `SK_FreshRig`.
- 기존 Blender 리그를 가져오지 않고 Unreal에서 본 59개와 부품 연결 417개를 새로 작성했다. 형상·UV·재질·텍스처·마스크는 인계한다. 현재는 강체 부품별 연결 후보이며 완성 리그·모션 품질 승인 상태가 아니다. 새 검 Idle은 아래 별도 AnimSequence에 작성했으며 기존 `LS_KeyPoses` 편집 키는 재사용하지 않았다.
- 자동화 진입점·런타임·요청은 [automate](../../automate/README.md), 제작 요구사항은 [애니메이션 사양](../ai-asset-pipeline/basic_weapon_animations.md)을 따른다.

## 선택과 키 편집

접촉 반응을 구워 저장하는 선택 필드는 아래 [메시 접촉 제어](#메시-접촉-제어)를 따른다. 실제 작업본 경로·해시·대상 동작은 로컬 제작 카탈로그에서 확인하며, 이 문서의 이전 후보를 최신 승인 결과로 취급하지 않는다.

1. Content Browser에서 `MechLab/FreshRigMech_20261110/MAP_Edit`를 열고 `LS_KeyPoses`를 연다.
2. Sequencer에서 `FreshRig_Editable`의 `FKControlRig` 트랙을 선택한다. 필요하면 **Shift+7**로 애니메이션 모드를 연다.
3. **Anim Outliner**에서 관절을 선택한다. 선택한 제어점의 위치·회전은 **Anim Details**에 표시된다. 뷰포트의 본이나 Sequencer의 본 목록으로도 선택할 수 있다. [Epic 애니메이션 모드](https://dev.epicgames.com/documentation/unreal-engine/animation-editor-mode-in-unreal-engine), [FK Control Rig](https://dev.epicgames.com/documentation/unreal-engine/fk-control-rig-in-unreal-engine).
4. 프레임을 지정하고 Location 또는 Rotation 값을 변경한다. 이동·회전 기즈모를 사용해도 된다. 각 채널 옆 다이아몬드로 키를 저장한다. 뷰포트에 포커스가 있으면 **S**, Sequencer에 포커스가 있으면 **Enter**로 키를 만들 수 있다. [Epic FK 키 편집](https://dev.epicgames.com/documentation/unreal-engine/fk-control-rig-in-unreal-engine).
5. Sequence와 맵을 저장한다. AI 초안 생성 명령을 다시 실행해 편집 키를 덮어쓰지 않는다. 현재 표시는 12fps이며 개별 동작은 최대 12프레임으로 제작한다.

공통 자동화 요청의 `bake_substeps`는 출력 프레임 사이에 저장할 자세 수를 지정한다. 기본값은 1이며 1~10 정수를 지원한다. 12fps·값 10이면 Unreal에는 120Hz로 계산한 FK 자세를 저장하고 출력 길이와 이미지 수는 유지한다. `unreal-plan`의 `linear_targets`에 발 본 이름을 지정하면 발 위치 목표를 등속 보간한다. 상체는 기존 완만한 보간을 사용한다. 이는 제작 단계의 접지 보정이며 게임의 실시간 지형 IK와 구분한다. 정수 프레임뿐 아니라 저장·재로딩한 동작의 중간 시각도 검사한다.

| 제어점 이름 | 역할 |
| --- | --- |
| `Root`, `pelvis` | 전체 기준·골반 위치 |
| `waist`, `chest`, `head` | 허리·가슴·머리 회전 |
| `shoulder_upper_l/r`, `shoulder_lower_l/r` | 어깨 상·하부 |
| `arm_upper_l/r`, `arm_lower_l/r`, `hand_l/r` | 상완·팔꿈치/하완·손목 |
| `thigh_l/r`, `shin_l/r`, `foot_l/r` | 고관절·무릎/정강이·발목 |
| `finger_*_l/r` | 손가락 관절 |
| `weapon_gun`, `weapon_sword`, `scabbard`, `slot_l/r` | 무기·칼집·수납부 |
| `thruster_l/r`, `subarm` | 스러스터·보조 암 |

`l/r`은 메카 자신의 좌우다. 화면 좌우로 판단하지 않는다. API 요청에서는 이름 뒤에 `_CONTROL`이 붙으며 `Root`의 API 이름은 `root_CONTROL`이다.

팔꿈치 형상의 주축은 X, 무릎 형상의 주축은 거의 Y다. 현재 FK 후보는 각 축의 회전을 직접 제공하며 손 목표 IK·자동 관절 제한·자동 파지/수납 전환은 구현하지 않았다. 관절 허용각은 미정이다. 관절 Location을 바꾸면 부품 사이 거리가 변하므로 각도 조정과 구분한다. 발목·가슴 피벗, 벨로즈·피스톤 추종과 큰 자세에서의 간섭도 추가 확인 대상이다.

## 메시 접촉 제어

`unreal-animation`의 `animation_clip` 요청에 `contact_response`를 지정하면 몸·장비의 기존 자세를 평가한 뒤 패널 본만 접촉 보정한다. 설정은 `rig_plan`, `collider_bones`, `panels`, `step_angle_deg`, `angle_tolerance_deg`, `separation_epsilon_deg`다. 각 패널은 `bone`, 단일 축 `axis_deg`, 골반 기준 본의 유효 힌지 오프셋 `pivot_offset_cm`, 탐색 상한 `max_angle_deg`를 가진다. 기본 회전이 없는 강체 말단 본만 지원하며 같은 본의 수동 키를 섞지 않는다.

경계 상자로 후보를 거른 뒤 Unreal Static Mesh의 삼각형 교차와 양방향 체적 포함을 검사한다. 닫힌 상태가 비접촉이면 추가 변환은 0이다. 접촉이면 처음 분리되는 탐색 구간을 이분 탐색하고 접촉 표본에만 수치 여유각을 더한다. 제한 안에서 분리하지 못하면 실패한다. 보고의 `contact_response.samples`에 표본별 접촉 대상·개방각을 남긴다. 탐색 간격보다 좁은 분리 구간, 저장 표본 사이의 연속 충돌, 관성·마찰은 보증 범위가 아니다.

`operation=contact_test`는 게임 에셋 없이 기본 도형 4종을 네이티브 API로 검사한다. [독립 시연](../../samples/unreal_pipeline/contact_response/README.md)을 사용한다. `operation=contact_geometry`는 `rig_plan`·`objects`에 지정한 실제 Static Mesh의 삼각분할을 새 `Tools/unreal_pipeline/workspace/`의 `output` JSON으로 내보낸다. 보고에는 파일 해시를 기록한다.

`operation=contact_probe`는 `tracking`의 저장 자세에서 `probes`의 `frame`·`bone`을 골라 `steps_deg`별 분리각을 비교한다. 같은 `contact_response` 설정을 사용하며 에셋이나 키를 작성하지 않는다. 탐색 간격 때문에 좁은 비접촉 구간을 놓쳤는지 진단하는 기능이다. 최소 분리 자세가 시간에 따라 부드럽다는 보증은 아니다.

`check_model_unreal_intersections.py`에 선택 필드 `geometry_snapshot`·`geometry_snapshot_sha256`를 전달하면 실제 Unreal 삼각형과 저장·재로딩한 추적 변환을 독립 Blender BVH로 검사한다. 스냅샷의 리그 계획 해시·부품·본·에셋 참조도 맞아야 한다. 필드가 없으면 기존 원본 `.blend` 형상을 검사한다. 두 메시의 정점 위치가 같아도 삼각분할은 다를 수 있으므로 검사 종류를 결과에 명시한다. 이 검사는 표면 교차만 다루며 체적 포함·전신 간섭·사용자 외관 승인을 대체하지 않는다.

## 메카 파츠 클릭이 선택되지 않을 때

현재 메카는 여러 부품을 하나의 Skeletal Mesh로 조립한 에셋이다. 장갑 표면 클릭을 개별 관절 편집으로 연결하지 않으며, **본/제어점을 선택해 편집한다**. Anim Outliner가 가장 확실한 선택 경로다.

애니메이션 모드 설정에서 `Display Hierarchy`는 켜고 `Hide Control Shapes`는 끈다. 가려진 제어점은 `Show Controls as Overlay`로 표시한다. `Only Select Rig Controls`를 켜면 일반 Actor와 메카 표면 선택이 제한된다. [Epic 선택·표시 설정](https://dev.epicgames.com/documentation/unreal-engine/animation-editor-mode-in-unreal-engine).

이번 확인에서 `Only Select Rig Controls`는 원래 꺼져 있었다. 이 설정을 기존 선택 문제의 원인으로 확정하지 않는다. 새 작업본에서 계층 표시·Overlay를 켜고 `arm_lower_l` 선택과 회전 채널 표시를 확인했다. 기본 도형 샘플은 회전 키에 따른 실제 메시 이동을 화면에서 확인했다. 실제 메카의 마우스 직접 클릭·기즈모 조작·모든 관절 가동 검증은 별도다.

별도 새 플러그인 없이 기본 FK Control Rig를 먼저 사용한다. 손 위치 고정 IK나 별도 모양의 제어 손잡이가 필요하면 현재 리그의 확인된 부족한 부분에 추가한다. 기존 프로젝트의 Pose Tool은 사용하지 않는다.

## 출력 단위·그림자 결과 열기

### 현재 검 Idle 초안

- 애니메이션: `/Game/MechLab/SwordIdle_KneeFlex_20261111/A_SwordIdle`.
- 표면 복원 메시: `/Game/MechLab/SurfaceFull_20261111/SK_Surface`. 원본 이미지·마스크 116개는 같은 폴더의 `SourceTextures`에 보존한다.
- 출력 맵·Sequence: `/Game/MechLab/RenderUnits_KneeFlex_20261111_se/MAP_Render`, `LS_Render`. 별도 에너지 출력은 같은 폴더의 `MAP_Energy`, `LS_Energy`다.
- 12fps·1초·출력 12프레임이며 0~12의 키 중 12는 반복 연결용 끝점이다. 현재 Unreal 초안을 수정하며 과거 Blender/41개 동작은 사용하지 않는다.
- 손목→손가락 방향과 칼의 실제 길이축은 약 90도다. 빈주먹·손바닥 안쪽 방향·허리/가슴/팔 회전 키와 검 파지를 유지한다. 허리를 숙이는 구간에 골반을 추가로 0~14cm 낮추고 양발의 위치·회전을 유지해 무릎 굽힘을 변화시킨다. 하강 깊이는 AI의 검토용 수치이며 최종 품질 승인은 별도다. 기존 골반 12cm 하강·왼발 35cm 전진을 기준으로 한다.
- 현재 동작은 FK 키를 구운 AnimSequence다. 발 고정 조건으로 계산한 허벅지·정강이·발 회전을 저장하며 새 IK 노드나 리그 구조를 추가하지 않았다. 이미지 재생은 12fps·1초·12프레임이다.
- 루트 `모션 보기.lnk` 또는 `output/motion/idle.gif`로 정면 재생을 연다. `slow.gif`는 느린 정면, `review.gif`는 정면·측면·사선 동시 재생이다. 실제 GUI 재생은 미검증이며 프레임·별도 프로세스 재로딩 확인과 구분한다.
- 마지막 조명 조정은 위치 `(-350,350,1500) cm`만 적용했다. 조명 회전·세기·재질을 이 위치 조정과 함께 변경하지 않았다. Blender 원본과의 완전한 외관 일치는 승인하지 않은 상태다.
- 프로젝트 루트의 **`모션 보기.lnk`**를 열면 현재 `output/motion/idle.gif`가 바로 열린다. 같은 폴더에 `slow.gif`·`hands.png`·`compare.png`가 있다. 사선·정면·측면·검 파지를 함께 확인한다.
- 현재 Idle의 조립 결과는 `data/runtime/catalog/prerender/player_mech_idle_centered_8dir/mech.json`이다. 본체·양손·장비 8파츠와 Energy Mask를 사용하며 UI v2에서 팔을 곧게 내린 정면 기준 자세의 양쪽 어깨 바깥쪽 너비가 128px인 공통 배율로 표시한다. 검 표시는 유지하고 Idle·콤보에 같은 배율을 적용한다. 방향별로 같은 메카 중심점을 피봇으로 삼는다. 이전 `output/sword_idle_20261111/assembled/mech.json`은 현재 연결 결과가 아니다.
- 자동화의 현재 작업본 표시는 `Tools/unreal_pipeline/workspace/current_animation.json`을 따른다. 초안이며 사용자 동작 승인·GUI 조작 확인은 별도다.

출력 `LS_Render`는 AnimSequence 재생용이다. 새 Idle을 제어점으로 수정하려면 별도 편집 Level Sequence에 `SK_Surface`를 추가하고 Animation 트랙에 `A_SwordIdle`을 연결한 뒤 Skeletal Mesh 트랙을 우클릭해 **Edit With FK Control Rig**로 키를 베이크한다. 이후 위의 제어점 편집 절차를 사용한다. 별도 Sequence로 저장해 원본 초안과 수동 수정본을 구분한다. 이 경로는 [Epic FK 베이크 안내](https://dev.epicgames.com/documentation/unreal-engine/fk-control-rig-in-unreal-engine)를 따른다. 이번 작업에서 이 베이크·GUI 키 편집을 직접 수행해 확인하지는 않았으며 설치 버전에 따라 메뉴 표시는 다를 수 있다.

### 현재 기본 4단 콤보 초안

- 현재 동작은 `current_animation.json`의 `basic_combo.animations`를 따른다. 1타는 `/Game/MechLab/SwordCombo_Follow_20261112/01/A_Combo01`, 2~4타는 `/Game/MechLab/SwordCombo_Follow_v02_20261112/`에 있다. 내려베기·가로베기·중앙 찌르기·후방 뽑아베기의 순서이며 타수별 6·6·6·8프레임·12fps, 전체 약 2.17초다.
- 하체를 낮추고 허리 굽힘·반대 팔 연동을 강화한다. 3타와 복귀는 양발의 접지 슬라이딩으로 표현하고 4타는 뒤쪽까지 베는 궤적을 사용한다. 파란 부분은 칼등, 커터칼 형태는 칼날이다. 사용자 최종 동작 품질 승인은 대기다.
- Idle 0프레임에서 시작하고 4타 끝점은 같은 Idle에 연결한다. 편집은 원래 `MechAnimationLab.uproject`의 동작 에셋을 사용한다. 출력 장면은 `automate/workspace/prerender_host/PrerenderLab.uproject`에 있으며 정확한 경로는 `basic_combo.scene_roots`를 따른다.
- 게임 묶음은 `data/runtime/catalog/prerender/player_mech_combo_follow_8dir/mech.json`이다. 8방향·32클립·208프레임과 파츠별 Energy Mask를 UI v2의 좌클릭 연계에 연결한다. 1~3타 종료 시 다음 타격 시작 자세에서 대기하고 4타 뒤 Idle로 복귀한다. 경로를 변경한 뒤에는 실행 프로그램을 다시 연다.
- `output/motion/combo_thrust_slide_rear.gif`·`combo_thrust_slide_rear_slow.gif`·`combo_thrust_slide_rear_trail.gif`는 정상/느린 재생·칼날 좌표 검토용이다. `output/motion/combo_follow_8dir.gif`는 8방향 재생이다. 모든 미리보기와 UI는 팔을 내린 정면의 어깨 너비 128px 기준 배율을 공유한다.
- `data/runtime/animations/player_mech/basic_combo_follow_20261112/blade_trajectory.json`은 검 위치·회전·길이축/칼날/칼등 기준점·8카메라 투영과 추가 본 8개를 120Hz로 기록한 261표본이다. Trail에는 실제 칼날 `cutting_edge_root/tip`을 사용한다. `blade_root/tip`은 길이축 기준점이다. `display`의 고정 배율·방향별 피봇·패킹 경로를 사용한다. component cm·이미지 좌표·게임 좌표를 구분한다.
- 현재 결과는 12fps FK 키다. 120Hz 중간 평가는 파지/접지 보간 오차를 포함한다. 게임 타격 창·연속 실시간 IK와 구분한다. SDL 자동 입력과 실제 OpenGL 창 캡처·직접 마우스 조작의 확인 범위는 [8방향 연결 기록](../ai-dev-log/2026-11-12-sword-combo-eight-direction-connect.md)을 따른다.

### 현재 검 이동 초안

- 기본 이동은 양팔을 앞뒤로 휘두르는 달리기, 대시는 낮은 접지 활주 자세, 부스트는 대시보다 낮은 골반과 큰 상체 전경으로 구분한다. Shift·Space의 입력 규칙은 [기본 무기 애니메이션](../ai-asset-pipeline/basic_weapon_animations.md)을 따른다.
- 현재 동작 선택은 `current_animation.json`의 `sword_locomotion.animations`를 따른다. `SwordLocomotion_v03_20261113/r02`의 15개 동작이다. 편집 프로젝트의 AnimSequence를 사용하고 렌더 장면은 `automate/workspace/prerender_host/PrerenderLab.uproject`에 둔다.
- 반복 3개와 대기·달리기·대시·부스트 사이 전환 12개를 12fps로 출력한다. 접지 목표를 푼 120Hz FK 자세를 저장하며, 달리기 지지발은 검토 이동량에 맞춰 등속으로 움직인다. 정면·측면·사선의 비교는 `output/motion/sword_locomotion.gif`, 전환 포함 재생은 `output/motion/sword_locomotion_transitions.gif`다. 팔을 내린 정면 어깨 너비 128px의 공통 배율을 사용한다.
- 전진 이동 초안이다. [검 이동 독립 테스트](../unit-tests/sword_movement.md)에 8방향 출력과 입력을 연결하며, 본편 게임·상하체 독립 조합은 별도다. 검 기본 달리기와 대시는 몸 전체가 이동 방향을 바라보는 설계이며 달리기는 전진 모션을 재사용한다. 옆걸음·뒷걸음 모션 제작과 마우스/록온 방향 유지 이동은 향후 과제로, 이 출력에 포함하지 않는다. 사용자 품질 승인과 GUI 편집 확인은 별도다.

### 기존 분리 진단 결과 상세

출력용 후보는 원래 프로젝트의 `/Game/MechLab/RenderUnits_20261111_v5/MAP_Render`와 `LS_Render`다. 본체·좌우 손·총·검·칼집·좌우 슬롯은 별도 Actor이며 공통 `PoseMaster`의 포즈를 따른다. 출력 메시 8개는 `/Game/MechLab/RenderUnits_20261111/SK_*`다. 초기 생성 폴더의 실패한 진단 동작은 인계하지 않았으며 유효한 장면/동작은 `_v5`에 있다. 이미 켜 둔 에디터에서 새 파일이 보이지 않으면 프로젝트를 다시 연다.

`A_SplitCheck`는 분리 메시가 손목 회전을 따라오는지 확인하는 진단용이다. 제작용 동작이나 KeyPose 후보가 아니다. 원래 `FreshRigMech_20261110/LS_KeyPoses`의 편집 키는 바꾸지 않았다. 저장한 같은 Skeleton의 AnimSequence를 분리 요청의 `animation`에 지정해 출력 장면에 연결한다. 현재 분리 요청의 `validation_motion=true`는 이때 제거한다.

Asset Tool에서는 로컬 `output/render_units_20261111/assembled/mech.json`을 연다. body·left_hand·right_hand·gun·sword·scabbard·left_slot·right_slot·shadow 9개 파츠다. `shadow`는 맨 아래이며 수신면은 포함하지 않는다. 편집 작업본은 `Tools/asset_loader/workspace/player_mech_render_units_20261111/plan.json`이다. 두 프레임은 진단용이며 전체 애니메이션 제작 완료를 뜻하지 않는다.

자동화 렌더는 별도 `automate/workspace/prerender_host/PrerenderLab.uproject`에서 확인했다. 원래 편집 프로젝트에서 MRQ를 직접 실행하려면 Movie Render Queue 플러그인과 Alpha Output, Custom Depth-Stencil Pass의 Enabled with Stencil을 설정한다. 기존 프로젝트의 실행 설정과 현재 창은 자동 변경하지 않았다. GUI 직접 열기·선택·키 편집·수동 렌더는 사용자 확인 대상으로 남긴다.

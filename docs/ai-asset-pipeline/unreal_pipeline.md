# Unreal 제작·프리렌더와 2D 파츠 조립

## 현행 경로

**Blender 모델링 → 리그 없는 형상 → Unreal 새 리깅·애니메이션·프리렌더 → PNG 파츠+JSON → 툴 2D 조립·패킹 → Pico2D**

| 담당 | 책임 |
| --- | --- |
| Blender | 형상·UV·재질 원본. 모델 원본 `.blend`는 보존한다. |
| Unreal | 새 골격·웨이트·제어점·동작·3D 부착·파지·카메라·조명·레이어 렌더 |
| Asset Tool | RGBA 프레임 가져오기·시트 패킹·파츠 상태·레이어 순서·프레임별 순서·2D 미리보기·메카 출력 |
| Pico2D | 기존 메카 묶음 로딩·재생. Unreal은 게임 실행 의존성이 아니다. |

기존 Blender 리그·본·웨이트·Constraint는 새 리그에 재사용하지 않는다. FBX는 모델 형상 교환용이다. 동작을 `.blend`로 반환하거나 Blender에서 다시 프리렌더하는 경로는 기존 호환 기능으로 보존하며 현행 제작의 필수 단계로 사용하지 않는다. Pose Tool·별도 KeyPose 승인 게이트도 사용하지 않는다.

## 표면 정보와 조명 인계

기존 Blender 리그 제외는 표면 정보의 폐기를 뜻하지 않는다. Blender 원본의 형상·부품 ID·기존 UV·재질 슬롯·텍스처·표면 마스크·에너지 마스크는 보존한다. FBX의 복잡한 Blender 노드 변환과 텍스처 자동 연결을 보장하지 않으므로 실제로 저장된 Unreal 재질/텍스처와 재로딩 표시까지 확인한다.

`automate/unreal/model_source.py`의 `inspect_surface`는 이미지 경로·패킹·색 공간·UV·노드 연결·광원/환경광을 조사한다. `surface_source.py`는 원본을 저장하지 않고 이관 후보의 새 UV0에 최종 색·거칠기·금속성·노멀·에너지 마스크·코팅 값을 베이크하며 기존 UV도 유지한다. 절차적 표면과 높이/범프 보정은 노멀에 포함한다. 원본 텍스처와 마스크는 별도로 계속 보존한다. `surface_assets.py`는 새 Unreal 경로에 이미지를 가져와 색상은 sRGB, 수치/마스크는 비색상, 노멀은 Normal Map 설정으로 연결하고, 형상 위치·크기와 재질 슬롯을 대조한다. 기존 Skeleton을 사용하는 새 표면 후보에서 애니메이션을 재사용한다.

Unreal은 재질을 적용한 상태로 프리렌더한다. 에너지 마스크는 무조명 전용 재질/장면에서 같은 포즈·카메라·캔버스로 별도 출력하며 툴의 `energy_mask` 시트로 인계한다. 표면 RGB 마스크를 최종 에너지 마스크와 혼동하지 않는다. 표면 마스크가 제어한 결과는 PBR/코팅 베이크에 포함되고 원본 RGB 마스크는 Blender 원본과 이미지에 보존한다.

광원 위치·방향·크기·색, 환경광과 노출/색 관리 기준을 함께 기록한다. Blender의 W와 Unreal의 광도 단위는 직접 동등하지 않으므로 이관 초기값과 실제 외관 대조/보정 완료를 구분한다. 기본 재질·임시 방향광을 쓴 검토 결과는 자세 진단용이며 원래 외관을 복원한 최종 렌더가 아니다.

### 광원 위치 변환

현재 형상 인계의 축 규약은 Blender 미터 좌표 `(x,y,z)` → Unreal 센티미터 좌표 `(100x,-100y,100z)`다. 모델 루트의 월드 변환을 형상에서 제거한 경우 광원에도 같은 역변환을 먼저 적용한다.

`p_UE = 100 × diag(1,-1,1) × xyz(inverse(M_root) × [p_Blender,1])`

`M_root`는 인계 전 모델 루트의 월드 행렬이다. 원점·회전이 같고 균일 배율만 `s`이면 `(100x/s,-100y/s,100z/s)`로 줄어든다. 역방향은 Unreal 좌표의 단위·Y축을 되돌린 뒤 `M_root`를 곱한다. 다른 FBX 축 프리셋을 쓰면 해당 프리셋의 기저 변환을 사용한다. 회전은 Euler 값의 부호만 임의로 바꾸지 않고 방향 벡터를 같은 기저로 변환한다.

루트 역변환은 `lighting_transfer.normalize_lights`, 축·센티미터 변환은 `render_units.py`가 담당한다. Unreal 기준에서 조명 위치를 수정하면 요청에도 해당 좌표를 반영한다. 이 위치 변환을 노출·광도·색상의 완전한 일치로 확대하지 않는다. 조명 범위가 모델까지 닿는지도 별도로 확인한다.

## 렌더와 파츠 경계

리그·손/무기 부착·3D 위치·파지·가림 관계는 Unreal에서 유지한다. 툴에서 새 3D 리그나 조명을 만들지 않는다. 출력 단위는 본체·손/무기·수납부·그림자·에너지 마스크 등 실제 조립 단위다. 모델의 작은 장식 417개를 모두 개별 이미지로 출력하는 규칙이 아니다.

새 보간 출력의 제작 방향은 **파츠별 색상·양방향 모션 벡터 프리렌더 → 게임 재생 중 파츠별 보간 → 가림을 반영한 합성**이다. 색상·에너지 마스크·벡터의 시간·카메라·좌표·기준점을 맞춘다. 가려진 표면 확보와 중간 시각의 가림 처리 방식은 구현·검증 후 확정한다. 현행 Stencil Layers 출력과 전체 프레임 보간을 이 구조의 구현 완료로 간주하지 않는다. 현재 지원 범위는 [프레임 보간](../unit-tests/frame_interpolation.md)을 따른다.

같은 기체의 상부·하부 동작은 공통으로 재사용한다. 공통 동작과 조합별 동작을 구분하고 같은 동작을 무기 조합마다 중복 제작하지 않는다. 실제 출력의 상하체 경계·공유 피봇·허리 연결·프레임과 가림 관계를 확인한 조합을 사용한다. 파츠가 분리돼 있다는 사실만으로 서로 다른 자세의 이미지 조합까지 검증됐다고 간주하지 않는다.

Unreal Actor Layer에 출력 단위를 부여하고 Movie Render Queue의 Stencil Clip Layers로 출력한다. `unreal-units`가 부품 목록을 출력 단위별 Skeletal Mesh와 Actor로 구성한다. 모든 단위는 기존 Unreal Skeleton을 공유하며 숨긴 전체 메시 `PoseMaster`를 Leader Pose로 따른다. 전체 메시 하나가 숨김 그림자를 투사하고 분리 메시의 중복 그림자는 끈다. 공유 골격의 동일 포즈와 같은 카메라·크기·프레임·기준점을 사용한다. 수동으로 파츠를 숨기며 따로 찍는 방식으로 그림자·반사가 유지됐다고 가정하지 않는다.

현재 파츠 정합 프리셋은 자동 노출·블룸·모션블러와 다중 픽셀 후처리를 끄고 공간/시간 샘플을 각각 1로 사용한다. 자동 노출을 유지한 레이어는 색상이 달라질 수 있다. 최종 안티앨리어싱 품질을 변경하면 전체 참조와 재합성을 다시 비교한다. Alpha Output과 Custom Depth-Stencil Pass의 Enabled with Stencil 설정이 필요하다.

레이어의 알파·가림 결과는 해당 3D 조합에 종속된다. 가려진 부분까지 복원되는 범용 교체 이미지가 아니다. 장비 교체로 3D 가림·그림자·파지가 달라지면 Unreal에서 그 조합을 다시 출력한다. 지면 그림자는 아래 전용 패스로 출력한다. 본체 표면의 자체 음영은 색상 이미지에 유지한다. 에너지 마스크의 별도 출력은 표면 이관 후보에서 확인하며, 기본 형상 진단 결과와 구분한다.

## 출력 단위 제작

`python automate/run.py unreal-units --unreal UnrealEditor.exe --project 프로젝트.uproject --request 분리요청.json`으로 전용 작업 프로세스에서 생성한다. 현재 사용자 에디터를 조작하지 않는다.

분리 요청은 프로젝트 루트 기준 `rig_plan`(부품의 `id/asset/bone`), 기존 Unreal `source_mesh`, `groups={출력ID:[부품ID]}`, 새 `/Game/MechLab/RenderUnits_*`의 `asset_root`, `size`, `camera={position,target,width_cm}`, 새 `automate/workspace/`의 `report`를 받는다. 부품 누락·중복·빈 그룹을 거부한다. 출력 Mesh마다 전체 본 이름과 순서를 확인한다. `reuse_mesh_root`는 같은 Skeleton의 이미 생성한 분리 메시를 재사용할 때만 사용한다.

`animation`에는 같은 Skeleton의 저장된 AnimSequence를 지정한다. 생략하면 Rest Pose다. `validation_motion=true`일 때만 손목 진단 동작을 생성하며 `animation`과 함께 사용할 수 없다. `frame_count`는 1~12(기본 2), 표시 속도는 12fps다. `MAP_Render/LS_Render`와 분리 전 비교용 `MAP_Reference/LS_Reference`를 별도로 생성하고 기존 경로를 덮어쓰지 않는다. 사용자의 제작용 FK/Control Rig 키를 수정하지 않는다.

Head 분리 후보의 출력 단위는 본체 247, Head 29, 왼손 38, 오른손 38, 총 22, 검 19, 칼집 12, 좌우 슬롯 각 6개 부품으로 총 417개다. 9개 색상 레이어에 각각 같은 프레임·기준점의 에너지 마스크를 연결한다. 지면 그림자는 별도 파츠다. 분리는 새 출력 후보에 적용하며 원본 리그를 보존한다. 이 규격과 활성 게임 Atlas 교체·장비 조합 공유의 완료 상태는 구분한다.

## 그림자 전용 패스

렌더 요청에 `"shadow":{"receiver_layer":"shadow_receiver","part_id":"shadow"}`를 지정한다. 출력 장면에는 중성 회색 또는 흰색 불투명 수신면과 중성 조명이 필요하다. 권장 기준은 같은 조명 품질·카메라·포즈를 유지하고 전체 메시의 그림자 투사만 끈 별도 장면이다. `unreal-units`의 `shadow_reference_only` 요청이 `MAP_Clear/LS_Clear`를 만들며, 렌더 요청 `shadow.reference`의 `map/sequence`에 지정한다. 원래 출력 장면의 조명이나 그림자 설정은 변경하지 않는다. 수신면의 가림/알파가 다르면 실패한다. 두 이미지의 화면 공간 밝기 비율을 검정 RGB와 가변 알파의 RGBA 그림자로 변환한다.

단순 시연용 기존 요청은 `r.ShadowQuality=0` 기준 렌더도 지원한다. 이 방식은 광원 종류에 따라 그림자 외의 지면 밝기까지 바뀔 수 있으므로 실제 면광원 출력에서는 별도 기준 장면을 사용한다.

`shadow/*.png`는 다른 파츠와 동일한 캔버스·기준점을 사용하며 조립 순서 맨 아래에 들어간다. 가려진 지면 영역은 투명하게 유지한다. 수신면 자체와 그림자 없는 기준 이미지는 진단용이며 최종 조립 파츠에서 제외한다. 변환 완료 전에는 `native_manifest.json`만 쓰고, 후처리 완료 후 `manifest.json`을 생성한다. 가져오기는 `shadow_pending`이 남은 입력을 거부한다.

이 방식은 중성 수신면의 **표시 색상 밝기 비율**이며 임의 바닥 재질의 물리 조명 복원은 아니다. 컬러 조명/바닥, 매우 어두운 기준면은 거부한다. 장비 조합이나 조명·카메라가 바뀌면 해당 조합을 다시 렌더한다. 색상 레이어에 있는 자체 음영을 제거하는 기능은 아니다.

구성 근거: [Epic 모듈형 캐릭터의 Leader Pose](https://dev.epicgames.com/documentation/unreal-engine/working-with-modular-characters-in-unreal-engine), [Epic MRQ 렌더 패스](https://dev.epicgames.com/documentation/unreal-engine/cinematic-render-passes-in-unreal-engine).

## 실행과 인계

- 렌더: `python automate/run.py unreal-render --unreal UnrealEditor.exe --project 프로젝트.uproject --request 렌더요청.json`.
- Unreal 시작 스크립트: `automate/unreal/prerender.py`. 저장된 맵·Camera Cut이 있는 Sequence·Actor Layer·12fps·최대 12프레임을 입력한다. 기존 렌더 큐와 출력 폴더를 덮어쓰지 않는다.
- 성공 시 `manifest.json`, 파츠별 RGBA PNG, 전체 참조 이미지와 `status.json`을 출력한다. 성공 콜백과 파일 존재 확인 전에는 완료 manifest를 쓰지 않는다.
- 툴 인계: `python automate/run.py asset --request 가져오기.json`. 요청은 `{"version":1,"operation":"unreal.import","source":"렌더폴더/manifest.json","output":"새묶음폴더"}`다. 요청 내부 경로는 요청 파일 위치 기준이다.
- 결과 `mech.json`을 기존 Asset Tool에서 열면 파츠 선택·레이어 순서·상태·프레임 미리보기를 사용한다. `plan.create`로 편집 작업본을 만들고 `plan.update/export`로 기존 경로를 재사용한다.
- 프레임 크기·기준점·FPS·파츠 목록·RGBA 채널을 검사한 뒤 시트를 저장한다. 파츠 이름은 안전한 ID이며 모든 프레임에 같은 파츠가 있어야 한다. 부분 입력·없는 파일·기존 출력은 거부한다.

manifest v1은 `type=unreal_prerender`, `asset_id`, `size=[폭,높이]`, `pivot=[x,y]`(bottom-left), `layers={파츠ID:{name,anchor}}`, `clips=[{name,fps,frames:[{파츠ID:PNG상대경로}],order,order_overrides,events}]`다. PNG는 같은 전체 캔버스를 사용하며 임의 크롭을 하지 않는다. 레이어별 시트는 기존 SSheet v1, 메카 묶음은 기존 v2다. 원본 프레임 번호·맵·Sequence 등의 출처는 `render_provenance.json`에 보존한다.

## 보존·검증 범위

모델 원본은 `data/`, 사용자 Unreal 편집 프로젝트는 `Tools/unreal_pipeline/workspace/`, 자동화 진입점·런타임·필수 요청은 [automate](../../automate/README.md), 재생성 가능한 렌더와 검증 결과는 `output/`에 둔다. AI 생성 모델·이미지·프로젝트는 공개 저장소에 넣지 않는다.

먼저 [기본 도형 시연](../../samples/unreal_pipeline/README.md)으로 실제 렌더→툴 패킹→재합성을 확인한다. 단순 도형의 통과를 실제 메카의 파지·간섭·재질·그림자·모든 동작 검증으로 확대하지 않는다. Head 포함 후보는 9개 색상 단위·9개 에너지 마스크로 인계하고 그림자를 별도 출력한다. 통짜 메시와 분리 메시의 완전한 픽셀 일치는 별도 비교하며 경계 차이를 숨기지 않는다. 전체 가동 품질·최종 게임 크기·GUI 직접 조작과 동작 승인은 별도 확인 대상이다. 검 Idle의 이전 출력은 [표면 인계 기록](../ai-dev-log/2026-11-11-unreal-sword-idle-surface.md), Head 분리와 전투 후보의 확인 범위는 [후보 제작 기록](../ai-dev-log/2026-11-16-animation-candidates-head-energy.md)을 따른다.

[애니메이션 흐름](animation_workflow.md), [제어점 편집](../tool-usage/unreal_animation_editing.md), [툴 자동화](../tool-usage/asset_tool_automation.md)를 따른다.

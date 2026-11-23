# 자동화 실행 경로

- 아틀라스 채널 단축: `python automate/run.py atlas-compact prepare --catalog 원본/catalog.json --output 새폴더`, 별도 검증은 `atlas-compact verify --catalog 새폴더/catalog.json`이다. 기본 BC7 아틀라스는 `--manifest 원본/atlas.json`을 사용한다. [형식·제약](../docs/tool-usage/atlas_memory_options.md)과 [독립 시연](../samples/atlas_compact/README.md)을 따른다.

- CPU 방향·추적 패킹: `python automate/run.py part-metadata-cache --catalog 품질/catalog.json --track 추적.json --output 새캐시.zip`을 사용한다. 입력 옵션을 반복해 여러 품질과 추적을 한 파일로 준비한다. [런타임 연결](../docs/tool-usage/atlas_memory_options.md#cpu-방향자세-메타데이터-패킹)과 [독립 시연](../samples/part_metadata_cache/README.md)을 따른다.

- 상·하체 정지 조준 후보: `python automate/run.py unreal-aim-review --request 요청.json`. 기존 자세에서 상체 선행 보간·±45° 초과 시 하체 추종의 표본과 `unreal-animation`용 요청을 준비한다. 준비와 실제 Unreal 생성·분리 렌더를 구분하며 [검토 범위](../docs/unit-tests/upper_lower_aim.md)를 따른다.
- 상·하체 입력 표: `python automate/run.py unreal-pose-table prepare/run/pack/extend-canvas/merge --request 요청.json`. 원본 자세를 방향 조합별로 평가·분리 출력하며 [입력용 표의 연결 규약](../docs/tool-usage/unreal_runtime_catalog.md)을 따른다.

- Unreal 출력 연결: `unreal-attachments`는 저장된 본 추적의 총구·접지·검날 투영, `unreal-runtime`은 원본 보존형 이동/공격 카탈로그·별칭 조립을 담당한다. [요청·출력·품질별 준비](../docs/tool-usage/unreal_runtime_catalog.md)와 [게임 없는 시연](../samples/unreal_pipeline/runtime_catalog/README.md)을 따른다.

- Audacity 프로젝트: `python automate/run.py sound-project --source 프로젝트.aup3`로 저장된 트랙 정보를 검사한다. `--mapping 트랙별파일명.json --output 새폴더 --headroom 0.5`는 원본 샘플레이트·스테레오·타이밍·트랙 게인을 보존한 WAV를 만든다. 전체에 같은 감쇠만 적용하며 개별 정규화는 하지 않는다. 저장된 float32·트랙당 한 클립·중앙 패닝·빈 실시간 효과/엔벌로프를 지원하고 미지원 편집·미저장 작업은 거절한다. MP3 출력과 게임 bank 수정은 포함하지 않는다.

- 외부 HUD 테마 편집기: `python automate/run.py hud-theme`. 팔레트·위젯 색 연결과 툴 내부의 실제 Pico2D 미리보기를 제공한다. [사용 안내](../Tools/hud_theme_editor/README.md)를 따른다.

- 정지 HUD 아이콘: `python automate/run.py model-icon --request 제작JSON`. 원본 해시와 선택 루트·카메라·출력 크기를 고정하고 평가된 메시 복사본에서 투명 원본 렌더와 단색 아이콘을 출력한다. 원본 모델을 저장하지 않는다. 정지 UI 이미지용이며 Unreal 모션 프리렌더와 구분한다.

- 효과음: `sound-sources --download`로 CC0 원본·출처를 보존하고 `sound-effects`로 공통 음원을 가공한다. `sound-import`는 사용자 선택 파일을 원본 보존 후 가져오며 `sound-preview`는 실제 혼합 청취 파일을 기록한다. 모두 `python automate/run.py` 뒤에 경로를 붙인다. [실행·출처 안내](../samples/sound_effects/README.md)를 따른다.

- Trail 결 준비는 `python automate/run.py trail-texture`를 사용한다. `--demo`로 공개 도형 시연용 파일을 미리 만들 수 있다. 데모에서 파일이 없으면 로딩 중에 메모리에서 준비한다. [준비·로딩 안내](../docs/tool-usage/trail_texture_preparation.md)

- 그림자 알파 전용 데이터 준비: `python automate/run.py alpha-textures --catalog 카탈로그.json`. 원본 PNG를 보존하며 [준비·오류·시연 안내](../docs/tool-usage/alpha_textures.md)를 따른다.

프로젝트 자동화의 실행 진입점·필수 실행 파일·의존성과 보존 입력을 이 폴더에 분리한다. 기존 `Tools/`의 공통 구현은 재사용한다. `output/`에는 재생성 가능한 이미지·캐시·검사 결과만 두며 필수 실행 파일이나 보존할 제작 입력으로 사용하지 않는다.

| 경로 | 역할 |
| --- | --- |
| `run.py` | Asset Tool·모델 제작·MCP의 공통 실행 진입점. 기존 공통 구현에 인자를 전달한다. |
| `unreal/` | 리그 없는 형상 인계와 새 Unreal 리그 자동화 |
| `bin/` | 로컬 DCC CLI 등 자동화 실행 파일 |
| `runtime/` | Unreal 자동화에 사용하는 설치된 Python 의존 패키지와 네이티브 서버 |
| `packages/` | 재설치용 패키지 원본·출처·무결성 정보 |
| `workspace/retained_inputs/` | 이전 제작 요청의 재실행에 필요한 입력 사본. 새 리그·모션의 품질 기준은 아님 |
| `workspace/` | 자동화 경로 이동 목록·해시·재실행 설정·작업 기록 |

위 로컬 실행 파일·패키지·입력/설정은 Git에서 제외한다. 외부 패키지의 라이선스·고지는 런타임과 설치 원본에 포함된 상태로 보존한다. 게임 원본·텍스처는 `data/`, 사용자 편집 작업본은 기존 툴의 `workspace/`에 둔다.

현재 Unreal 프로젝트의 `Content/Python/init_unreal.py`는 얇은 시작 연결 코드다. 실제 서버 시작은 `unreal/bootstrap.py`, 호스트 의존성은 `runtime/unreal/python/`, 연결 정보는 `workspace/unreal/mcp_ready.json`에서 관리한다. 필수 경로가 없으면 명시적으로 실패하며 `output`의 실행 파일이나 예전 런타임으로 대체하지 않는다.

DCC CLI는 기존 설치본의 시작 과정에서 예약된 업데이트 적용을 시도한 이력이 있다. 안전한 시작 경로를 확인하기 전에는 자동 호출하지 않는다. 파일 이동·해시 일치는 CLI의 실행 안전성·Unreal 연결 성공과 별개다.

## 실행

프로젝트 루트에서 실제 Python 인터프리터로 실행한다. `python` 명령의 Microsoft Store 별칭은 사용하지 않는다.

```powershell
python automate/run.py asset
python automate/run.py model -- --help
python automate/run.py mcp -- --help
python automate/verify_dependencies.py
```

`asset`과 `model`의 공통 기능은 기존 `Tools/` 모듈을 그대로 사용한다. `model`은 Blender 백그라운드 호스트를 통해 실행한다. Blender 경로는 `--blender` 인자 → `config.local.json`의 `blender_executable` → PATH 순서로 찾는다. 로컬 설정은 `config.example.json`을 복사해 작성하며 Git에서 제외한다. 형상 교환은 `blender --background --python automate/unreal/model_source.py -- --request 요청.json`을 사용한다. 모델/형상 요청의 상대 경로는 프로젝트 루트를 기준으로 하며 Asset Tool 요청 내부 경로는 기존 JSON 규약을 따른다.

`mcp`는 `runtime/client/python`의 공식 MCP SDK로 로컬 서버에 직접 연결한다. `--url`을 생략하면 `workspace/unreal/mcp_ready.json`에서 서버 주소를 읽는다. 이전 실행의 포트를 고정하지 않는다. `--output`은 기존 파일 덮어쓰기를 거부한다. 기존 사용자 작업본의 `mcp_ready.json`은 호환용 생성 메타데이터다.

클라이언트 런타임 재설치는 `python -m pip install --target automate/runtime/client/python -r automate/requirements-client.txt`를 사용한다. 실제 설치 패키지·URL·해시는 로컬 `workspace/client_runtime_install.json`에 남긴다. Unreal 호스트용 런타임과 섞어 설치하지 않는다. Unreal 어댑터 원본 wheel은 `packages/`에 보존한다.

## 이동 기록과 범위

- `workspace/output_dependency_migration.json`: 실행 파일·패키지·보존 입력 7개, Unreal 런타임 441개, 갱신한 요청 5개와 SHA-256.
- `workspace/request_backups/`: 경로 수정 전 요청 원문.
- `migrate_output_dependencies.py`: 완료한 일회성 이동의 재현용 기록. 기존 기록이 있으면 재실행을 거부한다.
- `verify_dependencies.py`: 이동한 파일의 해시, 이전 경로 부재, 수정한 요청의 실제 입력 존재를 확인하는 읽기 전용 검사.

Unreal 편집 프로젝트는 사용자 작업본이므로 `Tools/unreal_pipeline/workspace/`에 유지한다. 자동화 런타임과 새 요청·결과는 `automate/`에서 관리한다. 과거 개발 로그의 `output/` 경로는 당시 결과의 출처이며 현행 실행 의존성으로 사용하지 않는다. `output/` 전체의 삭제 가능성을 보장하는 검사는 아니다.

## Unreal 프리렌더

`unreal-directional --profile 제작JSON --unreal 실행파일 --project 프로젝트`는 기존 AnimSequence와 8방향 카메라를 재사용해 장면 준비·MRQ 출력·`unreal.import` 패킹을 연결한다. `--stage plan/render/pack`으로 분리하며 제작 입력이 바뀌면 새 작업 폴더를 사용한다. `--stage shadows`는 완료한 장면에 같은 포즈·광원의 무그림자 기준과 그림자 패스를 추가하고 `body`·`shadow`를 함께 패킹한다. `scene_template.reuse_meshes`는 출력 ID별 기존 메시 경로를 지정한다. [검 이동 테스트 인계](../docs/unit-tests/sword_movement.md)를 참고한다.

`unreal-motion-vectors`는 기존 애니메이션의 정방향·역방향 MRQ 벡터와 고빈도 정답 렌더를 전용 프로세스에서 출력한다. `motion_vector_convert.py`는 Blender의 이미지 디코더로 이를 독립 Pico2D 보간 입력으로 변환한다. 현재 검 콤보 시연·강도/방향/노출·입력 규약은 [프레임 보간 Unit Test](../docs/unit-tests/frame_interpolation.md)를 따른다. 원본 애니메이션 키는 수정하지 않는다.

`python automate/run.py unreal-render --unreal 실행파일 --project 프로젝트 --request 요청.json`이 별도 Unreal 프로세스에서 MRQ 렌더 완료를 기다린다. `--demo`는 게임 에셋 없는 최소 도형 시연이다. 출력은 PNG+JSON이며 `asset`의 `unreal.import`로 기존 파츠 묶음으로 패킹한다. [인계 규약](../docs/ai-asset-pipeline/unreal_pipeline.md)과 [시연](../samples/unreal_pipeline/README.md)을 따른다. 이미지 패킹 의존성은 `requirements-image.txt`와 `runtime/image/python/`에서 관리한다.

여러 장면은 루트 요청의 `requests` 배열에 기존 렌더 요청을 1~32개 넣어 같은 MRQ 큐에서 출력한다. 루트 `output`은 일괄 완료 보고 경로이며, 개별 `output`은 서로 다른 새 경로를 사용한다. 각 결과의 manifest·완료 기록을 보존하고 루트에도 요약을 남긴다. 실패·시간 초과 뒤에는 개별 출력과 보고부터 확인하며 완료된 출력을 다시 실행하지 않는다. 장면 제작은 기존 `unreal-units`의 `scenes` 배열을 재사용한다.

## 출력 단위와 지면 그림자

`python automate/run.py unreal-units --unreal 실행파일 --project 프로젝트 --request 분리요청.json`은 기존 Unreal 골격을 유지한 단위별 메시·공유 포즈·카메라·중성 수신면·비교 장면을 만든다. 부품 ID가 빠지거나 중복되면 실패한다. 요청과 보고는 `automate/workspace/`에 보존하고 원본 프로젝트를 덮어쓰지 않는 새 에셋 경로를 사용한다.

`unreal-render`의 `shadow` 요청은 수신면의 그림자 유무를 2회 렌더한 뒤 `unreal/shadow_pass.py`로 검정 RGBA 그림자를 만든다. 별도 `shadow` 파츠로 순서 맨 아래에 넣으며 수신면은 인계에서 제외한다. `manifest.json`은 후처리 완료 시점에만 생성한다. [입력 필드와 제약](../docs/ai-asset-pipeline/unreal_pipeline.md), [독립 그림자 시연](../samples/unreal_pipeline/README.md)을 따른다.

현재 메카의 보존 요청은 로컬 `workspace/render_units_20261111/prepare_v5.json`과 `render_v5.json`이다. 같은 요청의 에셋·결과 경로는 이미 존재하므로 재실행할 때 새 경로를 사용한다. `verify_parts.py`는 원본 해시·실루엣·손목 전달·검정 그림자·재합성과 통짜 렌더 차이를 기록한다. GUI 조작은 포함하지 않는다.

## 새 애니메이션 키와 표면 정보

`unreal-rig`는 `operation=rig_workspace`와 기존 `rig_workspace` 연산을 전용 Unreal 프로세스에서 실행한다. `import_static_geometry`는 리그 없는 FBX를 새 `FreshRig` 후보에 가져오고 명시한 단색 PBR 재질을 만든다. `geometry_root`와 `expected_geometry_count`는 저장된 Static Mesh를 먼저 확인한 뒤 재사용하는 복구 경로다. `build_rigid_rig`의 부품은 읽기만 하며 기존 `MechLab` 재질·형상을 보존한다. 새 본·웨이트는 Unreal에서 작성한다.

부품의 선택 `axis_binding`은 `axis`와 `knots: [[좌표_cm, {본명: 웨이트}]]`를 받는다. 구간별로 보간하고 끝에서는 끝값을 유지한다. 망원부 끝단·모서리를 보존하는 승강/확장에 사용하며 각 구간의 웨이트 합은 1이다. 강체 부품의 기본 바인딩은 유지한다. `material_override`는 새 부품의 단색 재질 지정에 사용한다.

`unreal-rig`·`unreal-animation`·`unreal-units`·`unreal-render`는 반복 가능한 `--engine-arg`로 전용 프로세스 시작 옵션을 받는다. 사용자 폴더에 쓸 수 없는 환경에서는 프로젝트 내 `-LocalDataCachePath`와 `-ddc=InstalledNoZenLocalFallback`을 지정한다. `-noshaderworker`는 외부 컴파일 작업 폴더를 쓰지 않는 선택 사항이며 엔진 설치 설정은 수정하지 않는다. 렌더 작업에는 `-nullrhi`를 사용하지 않는다.

`unreal-animation`은 `operation=animation_clip` 요청으로 기존 Unreal Skeleton의 새 AnimSequence를 작성한다. `poses`의 프레임·로컬 회전/이동과 `attachments`의 본 추종 파지를 사용하며 이전 키를 읽지 않는다. 생성은 12fps, 기본 30fps 압축 길이와 호환되는 2~12 짝수 프레임이다. 반복 동작은 같은 끝점 키를 포함하고 출력에서는 중복 끝점을 제외한다. 저장 결과 검사는 `frame/fps` 초 단위로 조회한다. `inspect_only=true`는 새 에셋 작성 없이 기존 결과를 읽는다.

`unreal-plan --request 목표.json`은 기준 포즈·본 위치·두 관절 말단/굽힘 면 목표를 공통 `animation_clip` 요청으로 변환한다. 본 길이를 유지하며 도달 범위 밖의 목표는 거절한다. 출력은 새 `automate/workspace/` 경로를 사용한다. 게임/Unreal 없이 계산 경로를 확인하는 [수치 샘플](../samples/unreal_pipeline/pose_targets/README.md)을 제공한다. 실제 관절 외관 검수는 Unreal에서 별도로 수행한다.

말단 이름 뒤의 `_rotation_deg`는 component 기준 회전 `[pitch,yaw,roll]`이다. `_contact_cm`과 `_contact_local_cm`을 연속 목표에 동일하게 지정하면 해당 점을 고정한 채 말단을 회전시킨다. 발끝 피봇과 뒤꿈치 들기에 사용하며 골격에 IK 노드를 추가하지 않는다. `tracking.extra_bones`는 지지발·몸통 등 추가 본의 평가 좌표를 함께 기록한다.

`unreal-review --request 검토.json`은 파츠 재합성·통짜 실루엣 비교·Energy Mask 소유 영역 검사와 고정 배율/피봇 GIF·전체 프레임 시트를 만든다. 요청에는 `views`별 Idle 합성 폴더·콤보 `directory`/`tracking` 목록·`pivot_top_left_px`, 공통 `scale`·`canvas`·`anchor`·`fps`·`idle_frames`, `font`·`contact_crop`·`output`을 지정한다. 검 오버레이는 `cutting_edge_root/tip` 투영 좌표를 사용한다. 결과 검사는 화면 조작·외관 승인을 대신하지 않는다.

선택 `contact_response`는 Unreal 실제 메시 접촉 시에만 강체 말단 패널을 분리한다. 비접촉 추가 변환은 0이며 준정적 보정 결과를 AnimSequence에 저장한다. `operation=contact_test/contact_geometry`는 기본 도형 검사와 실제 삼각분할 내보내기다. [설정·한계](../docs/tool-usage/unreal_animation_editing.md#메시-접촉-제어), [에셋 없는 시연](../samples/unreal_pipeline/contact_response/README.md)을 따른다.

`attachments[].local_rotation_quat`은 손 기준 파지 회전 `xyzw`를 유지한다. 연계 클립마다 같은 로컬 변환을 사용한다. 선택 `tracking`은 저장된 AnimSequence를 초 단위로 다시 평가해 검 본의 위치·회전·날 양끝을 기록한다. `bone`, `sample_hz`, 새 `Tools/unreal_pipeline/workspace/`의 `output`을 지정한다. 양끝은 `points_local_cm`으로 전달하거나 `blade_mesh`·`blade_axis_bind`로 실제 메시 정점에서 추출한다. 카메라별 좌표는 선택 `cameras`를 사용한다. 좌표계는 메카 component cm이며 게임 월드 좌표와 구분한다. `visual_phase_candidates`는 검토용 구간이고 확정 타격 판정이 아니다.

`model_source.py`의 `inspect_surface`와 `surface_source.py`는 Blender 백그라운드에서 원본 해시를 고정해 표면을 조사/베이크한다. `unreal-surface`의 `operation=surface_import`는 이관 후보의 `surface.json`을 읽어 새 Unreal 재질·텍스처·형상·동일 Skeleton의 출력 메시를 만든다. 완료·실패 보고와 실제 재로딩/렌더 확인을 구분한다. 기본 형상 FBX의 재질 생성 기록만으로 표면 이관 완료를 주장하지 않는다. [표면·조명 인계 규약](../docs/ai-asset-pipeline/unreal_pipeline.md)을 따른다.

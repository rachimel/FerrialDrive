# Asset Tool AI·자동화 진입점

> 현행 입력은 Unreal에서 프리렌더한 RGBA 파츠와 JSON이다. `unreal.import`로 기존 메카 묶음으로 패킹한 뒤 GUI·plan.create/update/export로 2D 조립한다. 3D 파지·부착·가림은 Unreal에서 유지한다. 기존 Blender 렌더는 호환 기능이다. [인계 규약](../ai-asset-pipeline/unreal_pipeline.md)을 따른다.

공통 실행 진입점은 `python automate/run.py asset`이다. 인자는 기존 모듈에 그대로 전달한다. 필수 실행 파일·런타임·보존 입력의 위치는 [자동화 경로](../../automate/README.md)를 따른다.

사용자는 기존 `Tools/asset_loader/run.py` GUI를 사용한다. AI는 **`Tools/asset_loader/asset_pipeline.py`**로 같은 조립·메카 작업본·검증·내보내기 로직을 호출한다. 화면이나 GUI 이벤트 루프를 시작하지 않는다. 이미지 검증·조립·패킹은 기존 Pico2D의 SDL 이미지 디코더를 사용하며, 모델 렌더에는 별도 Blender가 필요하다.

## 호출

프로젝트 루트에서 실행한다. 다른 폴더에서는 진입 스크립트와 요청 파일에 절대 경로를 전달한다.

```text
python Tools/asset_loader/asset_pipeline.py
python Tools/asset_loader/asset_pipeline.py --request samples/asset_loader/requests/inspect_bundle.json
python Tools/asset_loader/asset_pipeline.py --request 요청.json
python Tools/asset_loader/asset_pipeline.py --request -
```

인자 생략은 `describe`다. 지원 작업, 필수/선택 필드, 편집 형식, 방향·동작·프리셋, 예제를 JSON으로 조회한다. 필드 이름 끝의 `?`는 선택 항목이라는 표시이며 실제 요청 키에는 붙이지 않는다. `--request -`는 UTF-8 표준 입력에서 요청 하나를 읽는다. Python에서는 `Tools.asset_loader.automation.execute(request, base_dir=...)`를 호출한다. 이 함수는 결과 사전을 반환하고 실패 시 예외를 전달한다.

## 요청과 응답

```json
{"version": 1, "operation": "asset.inspect", "source": "bundle.json", "include_frames": true}
```

- 표준 출력: UTF-8 JSON 응답 하나. 정상은 `{"version":1,"ok":true,"operation":"...","result":{...}}`이다.
- 실패: `{"version":1,"ok":false,"operation":"...","error":{"code":"...","message":"..."}}`와 종료 코드 `1`이다. 정상 종료 코드는 `0`이다. 라이브러리 진단은 표준 오류로 분리한다.
- 오류 코드: `invalid_request`, `not_found`, `already_exists`, `io_error`, `dependency_error`, `operation_failed`, `timeout`, `cancelled`.
- 요청 파일 안의 입력·출력 경로는 **그 요청 파일의 상위 폴더** 기준이다. 표준 입력과 Python API의 기본 기준은 현재 폴더다. `base_dir`로 Python API 기준 폴더를 지정할 수 있다.
- 시트 JSON의 이미지 참조는 시트 JSON 기준, 카탈로그 참조는 카탈로그 기준이다. **메카 작업본 안의 `sheet`·`energy_sheet`는 작업본 `source`의 상위 폴더 기준**이며 GUI와 같다. AI는 절대 경로로 지정해도 된다.

## 지원 작업

| operation | 필수 입력 | 결과/동작 |
|---|---|---|
| `describe` | 없음 | 지원 작업·입력 형식·편집 예제 |
| `catalog.list` | 없음 | `catalog`의 ID·종류·원본 목록. 생략 시 기본 카탈로그 |
| `asset.inspect` | `source` | 종류·의존 파일·실제 이미지 크기·클립/FPS/전체 시간/프레임 수. `include_frames: true`면 영역·피봇·`duration_ms` 포함 |
| `catalog.register` | `source`, `asset_id` | 실제 이미지/메타데이터 검증 후 등록. 선택 `catalog`, `kind` |
| `sprite.assemble` | `source`, `asset_id`, `output`, `edits` | 일반 이미지·시트·본체/그림자 번들 조립 후 새 폴더에 출력 |
| `map.import` | `source` | 맵·실제 이미지 검증 후 편집 데이터 반환. 선택 `output`으로 새 폴더에 복사 |
| `map.export` | `output`, `source` 또는 `data` | 배경·바닥·합성 PNG·이동 구역을 새 맵 번들로 출력 |
| `plan.create` | `source`, `asset_id` | GUI 작업본 생성. 선택 `output`, 매핑 `preset`. 원본 `.blend`는 읽기 대상 식별에만 사용 |
| `plan.read` | `plan` | GUI와 교환할 작업본 전체 `data` |
| `plan.update` | `plan`, `edits` | 편집 목록을 메모리에서 적용·구조 검증 후 저장. 선택 `output`으로 새 작업본 저장 |
| `plan.validate` | `plan` | 기본은 구조만 확인. `check_sheets: true`면 분리 색상/마스크/상태 시트의 프레임·FPS·피봇·실제 크기 정합 검사 |
| `plan.export` | `plan`, `output` | 정합 확인 후 색상·마스크·상태 시트가 분리된 새 폴더와 `mech.json` 출력 |

`catalog.list`는 없는 카탈로그를 자동 생성하지 않는다. `catalog.register`는 저장 직전에 현재 목록을 읽고 중복 ID를 거절한다. 기본 카탈로그는 필요한 파일을 `data/runtime/catalog/prerender/`로 복사하며, 별도 카탈로그는 지정 원본을 참조한다. 공개 `samples/` 카탈로그는 등록할 수 없다.

`unreal.import`는 여러 방향의 클립을 하나의 메카 묶음으로 가져온다. 프레임·피봇·픽셀을 유지하며 각 변 8192px 안의 격자 시트로 배치한다. 짧은 입력은 기존 한 열 배치를 유지한다. 최대 시트 면적을 넘는 입력은 출력 전에 거절한다. 완성 `mech.json`은 Asset Tool과 공통 Pico2D 에셋 로더에서 읽는다.

선택 `trim_padding: true`는 모든 방향·프레임·파츠의 공통 투명 여백만 제거한다. 색상·Energy Mask에 같은 영역을 적용하고 피봇·필터 여백을 보존한다. 원본 PNG와 manifest는 변경하지 않으며 원본 크기·피봇·잘라낸 영역은 `packing.json`에 기록한다. 원본 대비 표시 배율은 그대로 사용한다. 기본값은 `false`다.

입력 manifest의 `clips[].pivot`은 방향별 bottom-left 기준점을 지정하며 생략하면 최상위 `pivot`을 사용한다. 같은 클립의 모든 색상·마스크 프레임에 동일하게 적용한다. 방향 정렬은 메카의 같은 3D 기준점을 각 렌더 카메라로 투영해 지정한다. 프레임마다 실루엣의 bounding box 중심을 다시 계산하지 않는다. 공통 여백 제거 시 클립별 피봇도 함께 보정하며 `packing.json.clip_pivots`에 기록한다.

## 메카 편집과 GUI 교환

`plan.create`의 `output`을 생략하면 GUI와 같은 `asset_id`·절대 `source` 조합의 `Tools/asset_loader/workspace/mech_plans/`에 저장한다. 기존 파일은 덮어쓰지 않는다. 같은 에셋을 GUI에서 열고 **메카 설정 → 저장본 불러오기**로 읽는다. AI가 편집하기 전에는 GUI 내용을 **저장**하고, AI 편집 뒤에는 GUI에서 다시 불러온다. 저장하지 않은 GUI 편집 내용은 공유하지 않으며, 동시 저장 충돌을 자동 병합하지 않는다.

공개 도형으로 작업본 생성:

```text
python Tools/asset_loader/asset_pipeline.py --request samples/asset_loader/requests/create_plan.json
```

이 예제는 `Tools/asset_loader/workspace/ai_demo/plan.json`에 저장하므로 후속 요청은 그 절대 경로 또는 요청 파일 기준 상대 경로를 사용한다. GUI 기본 경로와는 별도다.

`plan.update`의 `edits`는 다음처럼 작성한다. `set.path`는 기존 필드까지의 문자열 목록이다. 목록 값은 통째로 교체한다. 파츠·상태 추가/삭제는 전용 작업을 사용해 그리기 순서와 참조도 함께 정리한다.

```json
{
  "version": 1,
  "operation": "plan.update",
  "plan": "plan.json",
  "edits": [
    {"action": "part.add", "id": "back_thrusters", "name": "등 스러스터", "template": "thrusters"},
    {"action": "set", "path": ["layers", "back_thrusters", "anchor"], "value": "back_thruster_root"},
    {"action": "set", "path": ["layers", "back_thrusters", "states", "horizontal", "sheet"], "value": "thrusters_horizontal.json"},
    {"action": "set", "path": ["motions", "equipped_idle", "part_states"], "value": {"back_thrusters": "horizontal"}},
    {"action": "order.preset", "motion": "equipped_idle", "direction": "s", "preset": "front"},
    {"action": "order.copy_all", "motion": "equipped_idle", "direction": "s"}
  ]
}
```

마지막 `order.copy_all`은 해당 동작의 모든 방향에 같은 순서를 적용한다. 방향별 앞뒤가 달라야 하면 이 작업을 생략한다. `order.preset`의 `directional`은 기본 8방향 순서를 적용한다. `frame`을 지정하면 해당 Blender 프레임의 예외 순서를 다룬다.

편집 종류는 `set`, `part.add/remove`, `state.add/remove`, `order.preset`, `order.copy_all`, `mapping.apply`다. `part.add`는 `duplicate`로 복제할 파츠 ID를 지정할 수 있다. 새 매핑은 `default/mech/npc` 또는 프리셋 파일 경로를 사용한다. 한 요청의 편집 중 오류가 나면 그 요청은 작업본을 저장하지 않는다. ID·원본·버전은 `set`으로 변경하지 않는다.

## 스프라이트 조립

`sprite.assemble.edits`의 각 항목은 `source_clip`, 출력 동작 `name`, 0부터 시작하는 프레임 인덱스 `order`, 출력 프레임별 `durations_ms`를 포함한다. 기존 `fps` 요청도 읽는다. `pivot`은 `[x,y]` 또는 `null`/생략으로 원본 유지, `all_directions`의 기본값은 `true`다. 번들은 본체/그림자를 함께 편집한다. 예: `{"source_clip":"idle/s","name":"reverse","order":[3,2,1,0],"durations_ms":[100,40,60,180]}`.

맵 형식·GUI 조작·경로 해석은 [맵 번들·프레임 시간](asset_maps_timing.md)을 따른다.


조립·메카 내보내기는 기존 폴더를 덮어쓰지 않는다. `plan.update`는 지정한 입력 작업본만 갱신하거나 존재하지 않는 새 `output`에 저장한다. 원본 모델과 시트 픽셀을 수정하지 않는다. 3D 제작은 이 API의 범위에 포함하지 않는다.

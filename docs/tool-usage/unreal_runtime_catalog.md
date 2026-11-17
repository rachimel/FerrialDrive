# Unreal 출력의 훈련장 연결

리깅·자세·키·3D 부착은 Unreal에서 작성한다. 아래 경로는 저장된 출력과 본 추적을 투영·패킹·연결하며 원본 모델과 동작을 수정하지 않는다. 명령은 프로젝트 루트에서 실행한다.

## 제작 데이터

- `unreal-directional --profile 프로필.json --stage shadows`: 방향별 기체·Energy Mask·그림자를 출력하고 기존 메카 번들로 패킹한다.
- `unreal-directional --profile 프로필.json --stage vectors`: 원본 전후 프레임·정역방향 네이티브 벡터·24fps 참조와 같은 시각의 마스크를 출력한다. `--unreal`, `--project`, `--blender`를 지정한다. Blender는 EXR 디코딩·변환에만 사용한다.
- `unreal-attachments --request 요청.json`: 같은 동작의 본 추적·카메라와 검증된 본 로컬 기준점으로 총구·접지·검날의 root 상대 픽셀을 출력한다. 길이·시각·입력 해시를 검사한다. 본 로컬 기준점의 단위는 cm다.
- `unreal-runtime --request 요청.json`: 기체/보간 카탈로그의 원본 클립을 보존하고 런타임 별칭을 추가한다. 이동·공격 번들은 원래 시트와 마스크를 참조한다. 보간 카탈로그에는 원본·조립 메타데이터 해시를 포함한다.

실행 진입점은 모두 `python automate/run.py 경로`다. 요청의 파일 경로는 프로젝트 루트 기준이다. 출력은 `data/` 또는 `output/`의 새 폴더를 사용한다. 실제 제작 좌표는 `data/`, 재생성 가능한 검사·시연 출력은 `output/`에 둔다.

벡터 실행기는 Movie Render Pipeline을 명시적으로 로드하고 셰이더 작업 폴더를 `automate/workspace/unreal_shaders/`로 지정한다. `--engine-arg`로 전용 프로세스 옵션을 전달한다. 같은 Unreal 프로젝트의 worker는 직렬 실행한다.

실패 출력은 보존한다. 프로필의 `vector_batch_output`, `vector_render_output`, `vector_asset_root`로 새 시도를 분리할 수 있다. `passes: ["energy"]`는 동일한 동작의 마스크만 새 경로에 출력한다. `vector_energy_overrides`는 클립 이름별 대체 마스크 경로이며 동작·FPS·크기·길이·에너지 맵·실루엣 일치를 검사한다. 마스크의 전신 표시 상태는 별도 맵으로 저장한 뒤 MRQ에서 재로딩한다.

## 아틀라스

완성된 자세표의 무손실 채널 단축은 `python automate/run.py atlas-compact prepare --catalog 원본/catalog.json --output 새폴더`를 사용한다. 검증은 `atlas-compact verify --catalog 새폴더/catalog.json`으로 분리한다. 그림자의 검은 RGB만 제거해 R8로 저장하고 에너지 RGB는 유지한 채 미사용 알파를 제거한다. 기존 BC7 기본 아틀라스는 `--manifest`로 에너지 알파만 제거한다. 새 원본 출력을 만든 뒤에는 다시 후보 제작·검증해야 하며 이전 후보의 성공을 새 출력 검증으로 확대하지 않는다. [용량·형식·명령 안내](atlas_memory_options.md)를 따른다.

`python automate/run.py texture-compare --all --catalog 보간카탈로그.json --oodle-scales 0.75 0.5 0.25 --oodle-library 라이브러리.dll --output 새폴더`로 게임용 3해상도를 준비한다. NumPy·Pillow와 호환되는 Python을 사용한다. 색상만 BC7으로 인코딩하고 벡터·마스크는 무손실로 유지한다. `alpha-textures --catalog 메카카탈로그.json --quality-profiles`는 그림자 3배율을 준비한다.

마스크 쌍은 색상과 크기·알파·시각이 같아야 한다. 실제 게임 표시에서는 기체와 동일한 보간 좌표를 사용한다. `presentation.energy_mask_gain`은 얇은 발광선에 남는 원래 색의 혼합 정도를 조정하는 표현값이다. 기체의 알파와 마스크 밖 색상을 바꾸지 않는다.

`unreal-runtime` 요청의 선택 `atlas_sources`는 high/medium/low별 완성 아틀라스 목록, `atlas_output`은 병합 출력 폴더다. 같은 품질·알파·벡터 규격의 페이지/프레임 참조를 연결하므로 변하지 않은 클립을 다시 인코딩하지 않는다. 제작 입력·원본 아틀라스 해시와 별칭을 함께 보존한다. 최종 페이지는 보존할 `data/` 안에 준비한다.

전환을 기존 동작에서 가져올 때 원본 보존과 새 반복 동작의 연결 호환성을 별도로 검사한다. 대기·달리기·대시·부스트 사이의 양끝 본 변환과 무기 마운트를 먼저 확인하고, 일치하는 후보를 렌더한다. 비접촉 개방·다리 표면 교차 검사와 실제 재생 검수를 구분한다.

게임 없이 실행하는 [공개 도형·수치 시연](../../samples/unreal_pipeline/runtime_catalog/README.md)을 제공한다. 실제 엔진 출력 확인·자동 입력 재생·직접 조작·사용자 외관 승인은 별도로 기록한다.

## 상·하체 입력용 자세 표

`unreal-pose-table`의 단계는 `prepare`, `run`, `pack`, `extend-canvas`, `merge`다. 각 단계에 `--request 요청.json`을 전달한다. 게임 없이 실행하는 [독립 수치 시연](../../samples/unreal_pipeline/pose_table/README.md)은 `transform` 단계를 사용한다.

- `prepare`: `workspace`·`rig_plan`·`scene_template`와 선택 `scene_index`, 새 `asset_root`, `motions={런타임 이름:원본 요청 경로}`, `output`·`runtime`·`pivot`을 받는다. 저장된 원본의 모든 본 추적을 사용하며 같은 동작 위상에서 상체 8방향×하체 8방향을 함께 평가한다. 부착 선언이 없는 원본의 파지는 `attachment_drivers={무기 본:손 본}`으로 명시한다.
- `run`: 기존 `unreal-animation`·`unreal-units`·`unreal-render`를 직렬 실행한다. 동작 저장 뒤 Euler 환산 이전의 의도한 월드 쿼터니언을 검사해 렌더 전에 회전 손실을 거른다. 표의 자세는 두 프레임씩 유지하며 짝수 프레임만 출력한다. `pose_table=true`인 자료만 최대 4,096프레임을 허용한다.
- `pack`: 같은 자세의 상체/장비·하체를 재합성해 전체 참조와 비교한다. 그림자는 별도이며 에너지 마스크는 색상과 알파가 같아야 한다. `attachment_definitions`의 검날·총구·발 기준점을 원본 120Hz 본 추적에 적용한다. `pixel_scale`은 기존 게임 표시 크기와 맞춘다. 기존 `automate/runtime/`의 `python_paths`와 선택 `pack_workers`를 사용할 수 있다.
- `extend-canvas`: 경계에 닿는 동작만 출력 해상도와 직교 폭을 함께 늘려 cm당 픽셀 수를 유지한다. 실패한 출력을 보존하고 새 장면·경로를 만든다.
- `merge`: `sources`의 완성된 표를 새 `destination` 카탈로그에서 참조한다. 동작 이름 중복과 투영 배율 차이는 거부한다. 실행 자료는 `data/runtime/`에 두며 게임이 제작용 `output/`을 읽지 않게 한다.

실시간 회전 상태는 연속 각도지만 표현은 각 8방향·12fps 원본 프레임 선택이다. 영 벡터 페이지는 기존 아틀라스 셰이더의 정지 프레임 규약이며 모션 벡터 보간 결과가 아니다. 현재 기체와 살아 있는 잔상의 표는 캐시에서 유지하고, 나머지 표는 예산에 따라 해제한다. 자세 표에 없는 전환·부스트·조준 이동/사격은 기존 출력으로 재생한다. 실제 연결 범위는 [상·하체 검토](../unit-tests/upper_lower_aim.md)를 따른다.

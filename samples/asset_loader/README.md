# 에셋 로더 독립 샘플

직접 작성한 기본 도형으로 만든 공개 가능한 샘플이다. 기본 이미지 시연은 Blender 없이 실행하며 실제 게임 에셋·AI 생성물을 사용하지 않는다.

이 폴더는 공개 샘플 원본이다. 도구가 실제로 사용하는 사본은 최초 실행 시 `data/catalog/samples/asset_loader/`에 준비한다. 기존 사본은 덮어쓰지 않는다.

- `image.png`: 일반 투명 이미지.
- `body.json` / `body.png`: SSheetCutil v1 시트. 8방향·방향별 4프레임·6FPS.
- `shadow.json` / `shadow.png`: 같은 프레임·피봇의 분리 그림자.
- `bundle.json`: 본체·그림자를 묶은 기존 프리렌더 번들.
- `catalog.json`: 세 종류를 등록한 카탈로그 규격 예제.
- `make_sample.py`: Python 표준 라이브러리로 도형 PNG와 메타데이터를 재생성한다. 실행하면 이 샘플 폴더의 파일을 다시 작성한다.

## 시연

Pico2D가 설치된 Python 환경에서 프로젝트 루트 기준으로 실행한다.

```text
python Tools/asset_loader/run.py --debug
```

기본 도형이 열리면 방향·프레임·피봇·본체/그림자 표시를 확인한다. 기본 목록 `data/catalog/catalog.json`에는 샘플 3종이 등록되어 있다. ID를 변경하고 등록하면 별도 항목으로 추가된다. 조립해 저장한 완성 에셋은 `data/catalog/prerender/<ID>/<버전>/`에 남는다.

이미지·시트·번들을 각각 열려면:

```text
python Tools/asset_loader/run.py samples/asset_loader/image.png
python Tools/asset_loader/run.py samples/asset_loader/body.json
python Tools/asset_loader/run.py samples/asset_loader/bundle.json --debug
```

핫 로드 검증에는 `data/catalog/samples/asset_loader/`의 사본을 사용한다. 디버그를 켠 상태에서 이미지나 JSON을 바꾸면 세대가 증가한다. 잘못된 JSON·이미지 크기·손상 PNG에서는 이전 정상 화면과 오류를 확인하고, 수정 후 정상 자원으로 돌아오는지 확인한다. 공개 샘플 원본은 변경하지 않는다.

실행 위치와 다른 작업 폴더에서 실행할 때는 진입 스크립트와 입력에 절대 경로를 전달한다. 메타데이터의 이미지 참조는 메타데이터 파일 위치, 카탈로그 참조는 카탈로그 파일 위치를 기준으로 읽는다.

UI 사용법과 런타임 연결은 [도구 안내](../../Tools/asset_loader/README.md)를 따른다.

## AI·자동화 시연

동일한 Python 환경에서 GUI 없이 샘플을 조회한다. 요청 파일 안의 경로는 요청 파일 기준으로 해석한다.

```text
python Tools/asset_loader/asset_pipeline.py --request samples/asset_loader/requests/inspect_bundle.json
python Tools/asset_loader/asset_pipeline.py --request samples/asset_loader/requests/create_plan.json
```

첫 요청은 8방향·4프레임/FPS·피봇과 본체/그림자 이미지 정보를 JSON으로 출력한다. 둘째 요청은 공개 샘플을 참조하는 작업본을 `Tools/asset_loader/workspace/ai_demo/plan.json`에 생성하며 같은 파일이 있으면 거절한다. 원본 샘플은 변경하지 않는다. 후속 파츠 편집·정합 검사·분리 출력은 [AI 진입점 안내](../../docs/tool-usage/asset_tool_automation.md)를 따른다.

## 3D 리그 샘플

`make_rig_sample.py`는 Blender에서 큐브·단일 본·스키닝·1/3/5프레임 키프레임을 생성한다. 실제 게임 모델과 별개이며 모델 자동 리깅 기능이 아니다.

```text
blender --background --factory-startup --python samples/asset_loader/make_rig_sample.py -- --output Tools/asset_loader/workspace/rig_sample.blend
```

에셋 로더에서 **제작 → 3D 프리렌더**로 생성한 모델을 선택한다. 모델 루트는 `SampleRig`, 프레임은 `1,3`, 해상도는 `96×96`, FPS는 `8`, 렌더 샘플은 `2`로 지정한다. 카메라는 도구 설정을 사용한다. 이는 빠른 기능 확인용 값이다.

완료 후 8방향·방향별 2프레임·본체/그림자 분리를 확인한다. **제작 → 애니메이션 조립**에서 순서를 바꾸거나 반복하고 FPS·피봇을 편집해 저장한다. 저장한 시트의 방향별 동작과 그림자가 일치하고 원본 `.blend`가 보존되는지 확인한다. 새 결과는 작업/출력 폴더에만 남긴다.

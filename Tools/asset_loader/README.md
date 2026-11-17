# FDrive 에셋 로더

Unreal의 PNG 파츠+JSON을 받아 **2D 파츠 조립·프레임 편집·시트 패킹·미리보기·등록**을 수행한다. 제작 입력은 [Unreal 인계 규약](../../docs/ai-asset-pipeline/unreal_pipeline.md)을 따른다.

## 실행

Pico2D가 설치된 Python 3.11 이상 환경에서 실행한다.

~~~text
python Tools/asset_loader/run.py
python Tools/asset_loader/run.py 경로/bundle.json --debug
python Tools/asset_loader/run.py --catalog 작업경로/catalog.json --debug
~~~

인자 없이 실행하면 공개 도형 샘플을 연다. 기본 카탈로그는 `data/runtime/catalog/catalog.json`이다. 샘플 준비와 등록은 기존 파일을 덮어쓰지 않는다. 별도 카탈로그는 `--catalog`로 지정한다. [Runner 진입점](../../tests/asset_loader_test.py)으로도 실행할 수 있다.

로컬 바로가기는 `python Tools/asset_loader/create_launcher.py`로 만든다. 현재 환경의 경로를 포함하는 바로가기와 실제 에셋은 Git에 포함하지 않는다.

## 조작

왼쪽은 등록 에셋, 가운데는 미리보기, 오른쪽은 동작·방향 탐색기다. 프레임 썸네일은 선택 시 재생을 멈추고 해당 프레임으로 이동한다. 프레임별 유지 시간의 단위는 ms다.

| 조작 | 동작 |
| --- | --- |
| 불러오기 | PNG·JPG·BMP·시트·번들·메카 JSON 선택 |
| 등록 | 실제 이미지와 메타데이터를 검증한 뒤 카탈로그에 추가 |
| 메카 설정 | 파츠·상태·색상/마스크 시트·순서·전환 메타데이터 편집 |
| 애니메이션 조립 | 동작·프레임 순서·유지 시간·피봇 편집 |
| 맵 작업 | 맵 레이어·이동 구역·번들 편집 |
| 관리 | ID 변경·카탈로그 열기·핫 로드·새로고침 |
| ← / → | 동작·방향 변경 |
| Space / . | 재생·정지 / 다음 프레임 |
| 미리보기 휠·맞춤·1:1 | 배율 조작 |
| 탐색기·썸네일 휠 | 해당 목록 이동 |
| 본체·그림자 | 레이어 표시 전환 |
| 필터 메뉴 | Nearest·Linear·GPU Bicubic 비교 |
| Esc | 열린 패널 닫기 또는 도구 종료 |

파일·ID·조립 설정은 같은 Pico2D 창 안의 패널에서 편집한다. 경로 붙여넣기·Enter·더블클릭을 지원한다. Tab/Shift+Tab으로 필드를 이동하고 Ctrl+A/C/V로 선택·복사·붙여넣기한다.

## 메카 조립

`unreal.import`로 만든 `mech.json`을 열고 **메카 설정**에서 편집한다.

- **조립 기준:** 원본 프레임 번호·FPS·시트 크기·공통 피봇·사용 목적.
- **출력 파츠:** 이름·부착 식별자·상태·색상 시트·에너지 마스크. 추가·복제·삭제와 프리셋을 지원한다.
- **동작·순서:** 동작·방향별 레이어 순서와 원본 프레임별 예외.
- **전환 시점:** 가져온 출력과 연결되는 전환 이벤트.
- **무기 조건·검수:** 수동 확인 상태와 메모.
- **조립 미리보기:** 연결한 시트의 재생·갱신·색상/마스크 비교와 독립 도형 시연.

순서는 위에서 아래로 뒤→앞이다. 파츠 ID는 이름 변경과 독립이다. 상대 시트 경로는 작업본 원본 파일의 폴더를 기준으로 해석한다. 작업본은 `Tools/asset_loader/workspace/mech_plans/`, 프리셋은 `workspace/mech_presets/`에 보관한다.

내보내기는 색상·에너지 마스크와 합성 메타데이터를 분리 보관한다. 기존 출력 폴더를 덮어쓰지 않으며 원본 이미지·모델을 수정하지 않는다. 게임은 같은 공통 메카 로더로 결과를 읽는다. [파츠·무기·이벤트 규격](../../docs/tool-usage/mech_assets.md)을 따른다.

## 표시·검증

미리보기의 기본 필터는 GPU Bicubic이다. 지원하지 않는 렌더러에서는 Linear를 사용하며 실제 필터를 표시한다. 분리 그림자의 기본 표시 불투명도는 50%다. 원본 픽셀과 알파는 보존한다.

등록 전 원본과 의존 이미지를 다시 검증한다. 기본 카탈로그는 외부 에셋의 필요한 파일을 `data/runtime/catalog/prerender/`에 복사하며 중복 ID는 거절한다. 디버그 핫 로드 실패 시 직전 정상 자원을 유지한다.

공개 시연 데이터는 [에셋 샘플](../../samples/asset_loader/README.md), [맵 샘플](../../samples/asset_loader/map/README.md)을 사용한다.

## 자동화

~~~text
python automate/run.py asset
python automate/run.py asset --request 요청.json
~~~

`unreal.import`·검증·등록·스프라이트 조립·맵 작업·메카 작업본 편집과 출력을 지원한다. [요청·결과·경로 규약](../../docs/tool-usage/asset_tool_automation.md)을 따른다.

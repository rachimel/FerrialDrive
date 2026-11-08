# FDrive 에셋 로더

이미지·스프라이트 시트·본체/그림자 번들의 **미리보기·로딩 검증·ID 등록·디버그 핫 로드**를 제공한다. Blender 없이 기존 출력물을 읽는다.

## 실행

Pico2D가 설치된 Python 3.11 이상 환경에서 실행한다.

```text
python Tools/asset_loader/run.py
python Tools/asset_loader/run.py 경로/bundle.json --debug
python Tools/asset_loader/run.py --catalog 작업경로/catalog.json --debug
```

인자 없이 실행하면 공개 가능한 도형 샘플을 연다. 기본 등록 위치는 `Tools/asset_loader/workspace/catalog.json`이며 Git 추적에서 제외한다. 이미지는 원래 위치에서 참조하고 복사·수정하지 않는다.

Windows 바로가기 생성:

```text
python Tools/asset_loader/create_launcher.py
```

프로젝트 루트의 `FDrive Asset Loader.lnk`는 디버그 모드로 연다. 바로가기는 현재 환경의 경로를 포함하며 Git에서 제외한다. [독립 테스트 진입점](../../tests/asset_loader_test.py)도 Runner 목록에서 실행할 수 있다.

## 조작

| 조작 | 동작 |
|---|---|
| 불러오기 / O | PNG·JPG·BMP 또는 시트·번들 JSON 선택 |
| ID 변경 / I | 등록할 ID 변경. 영문·숫자·밑줄·점·하이픈 |
| 등록 / S | 현재 원본을 다시 검증하고 카탈로그에 추가. 중복 ID는 거절 |
| 핫 로드 / D | 디버그 자동 갱신 켜기·끄기 |
| 새로고침 / R | 다시 불러오기. 디버그에서는 실패 시 이전 정상 자원 유지 |
| 카탈로그 | 기존 등록 파일 열기. 목록 항목 클릭으로 미리보기 |
| ← / → | 동작·방향 변경 |
| Space / . | 재생·정지 / 다음 프레임 |
| 휠 / 맞춤 F / 1:1 | 확대·축소 / 영역 맞춤 / 원래 배율 |
| B / H | 본체 / 그림자 표시 |
| PgUp / PgDn | 등록 목록 페이지 이동 |
| Esc / 창 X | 종료·GPU 자원 정리 |

화면의 십자는 프레임 피봇이며 기존 시트의 bottom-left 규격을 따른다. RGBA8 추정치는 픽셀 수 × 4바이트로 계산하며 실제 GPU 점유·임시 복사본·드라이버 비용을 측정한 값이 아니다.

## 지원 규격과 등록

- 일반 이미지: PNG/JPG/BMP. 단일 프레임·아래 중앙 피봇으로 미리보기한다.
- 시트: SSheetCutil v1 JSON의 이미지·동작·FPS·프레임·피봇.
- 번들: 기존 `bundle.json`의 본체/그림자 시트와 방향별 동작. 본체와 그림자의 크기·프레임·FPS·피봇 일치를 검사한다.
- 카탈로그: [샘플 규격](../../samples/asset_loader/catalog.json)의 `version: 1`, `assets` 목록, 항목별 `id`·`kind`·`source`.

등록은 ID·참조 경로를 저장한다. 저장 위치 기준 상대 경로를 사용하며 Windows의 서로 다른 드라이브는 절대 경로로 저장한다. 이동·배포하려면 참조 이미지와 메타데이터도 함께 옮겨야 한다. 카탈로그만으로 에셋 파일을 패키징하는 기능은 아니다.

원본 파일을 손상시킨 상태에서는 마지막 정상 미리보기가 남아 있어도 등록을 거절한다. 외부에서 변경한 카탈로그는 등록 직전에 다시 읽어 보존한다. 샘플 카탈로그는 읽기 전용이다.

## FDrive·Unit Test 공통 사용

재사용 모듈은 `ferrial_drive/assets/`다. 게임은 `Tools`나 테스트 실행부를 import하지 않는다.

1. 열린 Pico2D 렌더러에서 `AssetCatalog.load(path)`와 `PicoAssetBackend`로 `AssetManager`를 구성한다.
2. `manager.acquire(asset_id)`로 핸들을 얻는다. 같은 관리자에서 같은 ID를 획득하면 자원을 공유한다. 서로 다른 ID나 서로 다른 관리자는 별도 캐시다.
3. 개체마다 재생 시간·동작을 관리하고 그릴 때 `handle.resource`의 최신 자원을 조회한다. `generation` 변화로 동작·프레임 구성 변경에 대응할 수 있다.
4. 사용이 끝난 핸들은 `close()`한다. 마지막 핸들이 닫히면 자원을 해제한다. 관리자 종료는 모든 소유 자원을 해제하며 렌더러를 닫기 전에 수행한다.
5. 개발 실행에서만 `debug=True`로 구성하고 프레임 갱신에서 `poll_reload()`를 호출한다. 기본 폴링 간격은 0.4초다.

핫 로드는 카탈로그·메타데이터·참조 이미지를 감지한다. 새 자원을 완전히 검증·로딩한 뒤 교체하고 이전 자원을 해제한다. 실패하면 정상 자원을 유지하고 디버그 다음 폴링에서 복구를 다시 시도한다. 사용 중인 ID가 카탈로그에서 삭제되면 기존 핸들은 해제 전까지 유지하며 신규 획득은 거절한다.

파일 처리와 GPU 교체는 **렌더러 소유 스레드에서 동기적으로 실행**한다. 작업 스레드·비동기 스트리밍 로더가 아니다. 일반 실행의 `debug=False`에서는 자동 파일 조회·핫 로드를 하지 않는다.

## 선택적 계측·화면 검증

```text
python Tools/asset_loader/run.py --debug --profile output/performance/asset-loader.json
python Tools/asset_loader/run.py --frames 3 --capture output/asset_loader_review/tool.png
```

기존 TimingRecorder를 선택적으로 연결한다. `assets.metadata`와 `assets.texture_load`, 화면 표시·프레임 대기를 기록한다. GPU 실행시간·전체 메모리 실측과 구분한다.

## 확인 상태

- 공통 로더·실제 Pico2D 로딩·등록·핫 로드·실패 복구 자동 검사 25개 통과.
- 기존 에셋 파이프라인 호환 검사 8개 통과.
- SDL dummy로 실제 도형 이미지·시트·번들 로딩, 합성 키 입력·등록 저장/재로딩과 툴 화면을 확인했다.
- 실제 데스크톱의 파일 선택 대화상자·마우스 조작·파일 저장 도중의 체감·대형 게임 에셋과 낮은 사양 기기의 성능은 사용자 확인 전이다.

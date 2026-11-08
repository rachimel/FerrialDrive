# 에셋 로더 독립 샘플

직접 작성한 기본 도형으로 만든 공개 가능한 샘플이다. 실제 게임 이미지·Blender·AI 생성물을 사용하지 않는다.

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

기본 도형이 열리면 방향·프레임·피봇·본체/그림자 표시를 확인한다. ID를 변경하고 등록하면 **작업 카탈로그**인 `Tools/asset_loader/workspace/catalog.json`에 추가된다. 종료 후 같은 카탈로그의 등록 항목을 클릭해 다시 확인한다.

이미지·시트·번들을 각각 열려면:

```text
python Tools/asset_loader/run.py samples/asset_loader/image.png
python Tools/asset_loader/run.py samples/asset_loader/body.json
python Tools/asset_loader/run.py samples/asset_loader/bundle.json --debug
```

핫 로드 검증에는 샘플 폴더를 작업 경로로 복사하고 복사본을 연다. 디버그를 켠 상태에서 이미지나 JSON을 바꾸면 세대가 증가한다. 잘못된 JSON·이미지 크기·손상 PNG에서는 이전 정상 화면과 오류를 확인하고, 수정 후 정상 자원으로 돌아오는지 확인한다. 샘플 원본은 변경하지 않는다.

실행 위치와 다른 작업 폴더에서 실행할 때는 진입 스크립트와 입력에 절대 경로를 전달한다. 메타데이터의 이미지 참조는 메타데이터 파일 위치, 카탈로그 참조는 카탈로그 파일 위치를 기준으로 읽는다.

UI 사용법과 런타임 연결은 [도구 안내](../../Tools/asset_loader/README.md)를 따른다.

# 맵 도형 샘플

외부 모델이나 게임 데이터 없이 배경·바닥·합성·이동 가능 구역을 확인한다. 이미지는 직접 작성한 도형이다.

- Pico2D 설치 환경에서 `python Tools/asset_loader/run.py samples/asset_loader/map/bundle.json` 실행.
- 오른쪽 목록에서 `background`, `ground`, `composite`, `walkable` 선택.
- **맵 작업**에서 레이어 확인, 이동 구역 꼭짓점 추가·확정, 새 출력 폴더로 내보내기.
- 내보낸 `bundle.json`을 **불러오기** 또는 **맵 작업 → 맵 불러오기**로 다시 연다.
- 합성 순서는 배경 위에 바닥이다. 모든 레이어는 320×180이며 좌표는 bottom-left 픽셀이다.
- 원본과 출력 폴더는 분리한다. 빈 출력 경로는 로컬 에셋 라이브러리에 새 번들을 생성한다.
- 재생성: 프로젝트 루트에서 `python -m samples.asset_loader.map.make_sample`.

빈 `walkable`은 이동 가능한 구역이 없다는 뜻이다. 다각형 여러 개는 합집합이며 경계를 포함한다.

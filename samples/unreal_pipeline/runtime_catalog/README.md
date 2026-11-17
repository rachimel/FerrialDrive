# 본 추적 투영·런타임 카탈로그 시연

게임 모델·세이브·Unreal 실행 상태 없이 공통 자동화 경로를 확인한다. 숫자 추적은 직접 작성한 예제이며 실제 Unreal 평가 결과가 아니다. 사각형 PNG와 보간용 이동 도형은 공개 시연 생성기가 작성한다.

- `python automate/run.py unreal-attachments --request samples/unreal_pipeline/attachment_projection/request.json`: 총구·접지·검날의 투영과 별칭을 `output/unreal_pipeline/attachment_demo/`에 출력한다. Python 표준 라이브러리를 사용한다.
- `python automate/run.py unreal-runtime --demo output/unreal_pipeline/runtime_demo`: NumPy·Pillow가 있는 Python에서 실행한다. 입력은 `input/`, 결과는 `runtime/`으로 분리한다. 출력 폴더는 새 경로를 사용한다.

런타임 시연은 원본 2클립에 `idle_loop/s`·`combo_01/s` 별칭을 추가한다. 이동/공격 번들과 마스크는 같은 원본 시트를 참조하고 보간 카탈로그는 같은 원본 구간을 참조한다. 원본 메타데이터는 덮어쓰지 않는다. 실제 엔진 출력·전체 게임 조작·모델 외관 승인은 이 시연의 범위가 아니다.

# Trail 결 사전 준비와 셰이더 로딩

Trail 결은 제작 단계에서 파일로 준비하고 게임 로딩에서는 파일 읽기·GPU 전송만 한다. 절차적 픽셀 생성·셰이더 컴파일·버퍼 첫 할당·GPU 첫 실행을 첫 공격의 책임으로 두지 않는다.

## 준비

프로젝트 루트에서 실행한다. 준비 명령은 Python 표준 라이브러리만 사용하며 Pico2D·창·게임 에셋이 필요 없다.

```text
python automate/run.py trail-texture
python automate/run.py trail-texture --demo
python automate/run.py trail-texture --config 설정.json
```

- 기본 설정은 `samples/sword_movement/movement_config.json`의 `sword_effects`다.
- 실제 게임용은 설정의 `flow_texture_directory`, 시연은 `demo_flow_texture_directory`를 사용한다. 설정 안의 상대 경로는 설정 파일 위치를 기준으로 한다. 명령의 `--output-directory`는 저장 폴더를 명시하며 실행 시 설정도 그 폴더를 가리켜야 한다.
- 현재 게임용 파일은 로컬 `data/runtime/effects/sword_trail/`, 시연용은 `samples/sword_movement/generated/trail_flow/`에 둔다. 시연 파일은 게임용 `data/` 없이 같은 생성기로 만들 수 있다. 두 생성물 경로는 Git에서 제외한다.
- 같은 설정의 정상 파일은 다시 만들지 않는다. 가닥 수·부드러움·크기·생성기 버전이 달라지면 별도 키의 파일을 만든다. 기존 파일을 임의로 삭제하지 않는다.

## 준비 파일

`.trailflow`는 `manifest.json`과 `pixels.rgba`를 담은 ZIP이다. 원래 512×128 RGBA8 픽셀을 무손실로 압축한다. 현재 픽셀은 256KiB이며 준비 파일은 약 33KiB다. 파일 크기와 GPU 점유량을 같은 값으로 해석하지 않는다.

- manifest에는 생성기 버전·크기·가닥 수·부드러움과 RGBA SHA-256을 저장한다.
- 실행 시 설정·크기·해시를 확인한다. 미준비·다른 설정·손상 파일은 오류로 알리고 게임 중 픽셀 생성으로 조용히 대체하지 않는다.
- 원래 절차적 생성기는 제작·검사 기준으로 보존한다. 알고리즘을 바꿀 때 `FLOW_GENERATOR_VERSION`도 올리고 다시 준비한다.

## 게임 로딩

- 열린 Pico2D 캔버스와 GL context에서 `PicoSwordEffects.prepare(settings)`를 호출한다. 훈련장은 로딩의 `Trail 준비` 단계에 연결한다.
- 파일을 읽어 SDL 텍스처로 올리고 Compute·Vertex·Fragment 프로그램을 준비한다. Compute 미지원 환경은 기존 CPU 경로를 유지하며 CPU 경로도 같은 준비 파일을 읽는다.
- `max_sections`를 기준으로 제어점·job·출력 SSBO 공간을 미리 예약한다. 작은 별도 렌더 대상에서 Compute와 실제 그리기를 실행하고 완료를 기다린다. SSBO·GL·SDL 렌더 대상·배율·viewport·clip은 복원한다. 게임의 공격 시간·궤적·명중 상태를 진행시키지 않는다.
- 일반 프레임은 준비된 자원을 재사용한다. 같은 설정의 `prepare()`는 자원을 다시 만들지 않는다. 표시 모듈을 독립 연결할 때도 로딩 단계에서 준비 호출을 연결한다.
- `--profile`의 `loading.sword_trail.prepare`는 파일 읽기부터 GPU 첫 실행 완료까지의 포함 경과 시간이다. 첫 전투 프레임과 전체 프로세스 시작 시간은 별도로 측정한다.

## 확인 범위

- `tests/automated/test_trail_flow_preparation.py`: 원래 픽셀과 일치, 로드 중 무생성, 설정 변경·손상 거절, 저장 실패 정리, 게임 에셋 없는 다른 작업 폴더의 준비 명령.
- `tests/automated/test_compute_sword_trail.py`: 기존 CPU/Compute 좌표·UV·알파·픽셀 비교와 실제 GPU 사전 실행·상태 복원·첫 draw의 무생성/무컴파일/무할당. 실제 GPU 검사는 `FDRIVE_GPU_TESTS=1`일 때 선택 실행한다.
- 첫 공격 전후의 실제 측정과 미검증 범위는 [개발 기록](../ai-dev-log/2026-11-15-trail-prebake-loading-warmup.md)을 따른다. 부분 검사 통과를 최소 사양 60FPS·권장 165FPS 보장으로 확대하지 않는다.

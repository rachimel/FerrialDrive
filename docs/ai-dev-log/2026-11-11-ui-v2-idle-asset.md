# UI v2 플레이어 Idle 에셋 연결

- **기록 ID:** `FDLOG-20261111-ui-v2-idle-asset`
- 정리 기준: 2026-11-11 22:43:03 KST 이후 현재 코드·실제 렌더 결과다. 개별 발언 시각은 이 시각으로 대체하지 않는다.
- 개별 사용자 발언의 정확한 시각은 미확인이다. [[FDLOG_MISSING_TIME:FDLOG-20261111-ui-v2-idle-asset:scope]] 현재 대화의 “old unit test들 정리”, “아니지”, “ui-unit-test-v2에 저 idle asset 넣어봐”를 검색한다.
- 상태: 구현·에셋 패킹·자동 검사·OpenGL 창 렌더·합성 입력 확인 완료. 직접 마우스 조작·사용자 외관 승인·커밋·업로드는 미수행이다.

## 1. 사용자가 제안한 것

- **U1:** 현재 8방향 Idle 에셋을 `ui-unit-test-v2`에 넣는다. 직접 근거는 “ui-unit-test-v2에 저 idle asset 넣어봐”다.
- 기존 Unit Test 정리/새 테스트 지시는 후속 “아니지”와 U1로 이번 작업 범위에서 제외했다.

## 2. 사용자 제안 중 AI가 수용한 것

- U1: v2의 플레이어 도형 자리에 현재 Idle을 연결한다. 적 샘플·HUD 배치를 유지하고 기존 Unit Test를 삭제하거나 정리하지 않는다.
- 보존 원본은 앞서 출력한 8방향 RGBA 96장이다. 로컬 제작 입력과 실행용 에셋을 `output/` 밖에 보존한다.

## 3. AI가 제안한 것

- **A1, 구현상 판단:** 마우스 방향으로 8방향을 선택하며 방향 변경 중 재생 위상을 유지한다. 전투에서만 시간을 갱신하고 일시정지·타이틀에서는 멈추며 F5로 초기화한다. 최초 `se`·표시 배율 0.25는 시험값이다.
- **A2, 공통 수정:** 기존 `unreal.import`의 한 열 패킹을 최대 변 8192px의 격자로 확장한다. 96장을 원본 해상도·피봇 그대로 한 메카 묶음으로 읽기 위한 수정이며 작은 입력의 기존 한 열 배치는 유지한다.
- **A3, 배포 경계:** 공개 샘플은 로컬 에셋이 없으면 도형으로 실행한다. 실행은 공통 `PicoAssetResource`, 순수 방향/재생은 `DirectionalPlayback`을 사용한다. GUI는 실행부에서만 연다.
- 제시·구현 개별 시각은 scope의 미확인 항목이다. 근거는 기존 UI 플레이어 도형·공통 로더·세로 시트 제한을 직접 확인한 결과다.

## 4. AI가 제안한 것 중 사용자가 수용한 것

- U1의 에셋 연결은 사용자 직접 요청이다. A1의 입력 방식·표시 배율 및 새 화면의 외관에 대한 별도 사용자 수용은 아직 확인하지 않았다.

## 5. 반영 후 발견한 문제

- **I1:** 기존 세로 패킹은 768px × 96장의 높이가 제한을 넘었다. 한 묶음의 8방향 표시를 위해 격자가 필요했다.
- **I2:** 첫 자동 검사에서 game2d 환경에 Pillow가 직접 설치되지 않아 이미지 검사 모듈 하나를 읽지 못했다. 나머지 검사는 실행됐다. 새 설치 없이 프로젝트에 보존한 CPython 3.11 이미지 런타임을 사용했다.

## 6. 사용자 해결 제안과 실제 해결 과정

- U1에 맞춰 다른 테스트 정리 대신 기존 v2 실행부를 수정했다. I1·I2에 대한 별도 사용자 해결 제안은 이번 구현 중 받지 않았다.

## 7. AI 해결 제안과 실제 해결 과정

- **I1 / A2:** `Tools/asset_loader/unreal_import.py`에서 bottom-left 프레임 좌표와 상하 행 배치를 함께 계산한다. 클립/행/열 경계를 넘는 6개 도형 프레임·복수 파츠 픽셀 보존 검사를 추가했다. 기존 에너지 마스크·그림자·원본 보존 검사도 통과했다.
- 입력 96장과 manifest를 로컬 `Tools/asset_loader/workspace/player_mech_idle_8dir/input/`에 보존하고 공통 `automate/run.py asset`의 `unreal.import`로 `data/catalog/prerender/player_mech_idle_8dir/mech.json`을 생성했다. 실제 시트는 7680×7680, 텍스처 메모리 추정은 225MiB다. 이후 96프레임 전부를 원본과 픽셀 단위로 대조했다.
- UI는 `v2.player_asset.source/scale/direction`을 읽는다. 에셋 로딩은 `enter()`, 해제는 `exit()`에서 수행하고 import·생성자만으로 Pico2D를 불러오거나 창을 열지 않는다. 플레이어만 교체하며 마우스·카메라 좌표와 기존 전환 불투명도를 유지한다.
- **I2 / 자동 검사:** 프로젝트 이미지 런타임을 경로에 연결해 `tests.test_unreal_prerender_import`, `tests.automated.test_directional_playback`, `tests.automated.test_ui_v2` 총 63개가 통과했다. 별도 패키지 설치는 하지 않았다.
- **실제 렌더:** 수정된 일반 진입점을 OpenGL 창으로 90프레임 실행·종료하고 첫 화면을 저장했다. 별도 OpenGL 검증에서 합성 마우스 입력으로 8방향 각 12프레임을 렌더하고 정지/재개·타이틀 중 정지·F5 초기화·종료 텍스처 해제를 확인했다. 기본·좌우/후면·일시정지 이미지를 직접 열어 표시를 검토했다. 결과는 `output/ui_unit_test_v2/idle_asset/verification.json`·PNG·`preview.gif`다.
- 이는 실제 Pico2D/OpenGL 렌더와 합성 입력 검사다. 사람의 직접 마우스 조작·사용감·최종 외관 승인·게임 전투 모션 연결 완료로 확대하지 않는다. AI 생성 이미지·시트는 Git 제외 경로에 유지한다.
- 실행 인계: 수정한 `tests/ui_unit_test_v2.py --scene combat`을 별도 프로세스로 시작했고 3초 뒤 생존과 `Ferrial Drive | ui-unit-test-v2` 창 핸들을 확인했다. 실행 근거는 로컬 `live_launch.json`이다. 기존 Runner와 다른 테스트를 종료하거나 정리하지 않았다.

# 180기 첫 프레임 커밋과 OpenBLAS 초기화

- **기록 ID** `FDLOG-20261123-combat-openblas-commit`
- 작업일 2026-11-23 KST.

## 1. 사용자가 제안한 것

- **U1** 첫 프레임의 커밋 증가를 함수별로 추적한다. 같은 180기 입력과 화질에서 FPS·P99를 유지하며 2GiB 제한을 통과하고, 전후 계측과 코드를 별도 커밋한다. 요청 시각은 미확인이다. `[[FDLOG_MISSING_TIME:FDLOG-20261123-combat-openblas-commit:U1]]` 검색 단서는 `첫 프레임에서 커밋 메모리가 어디서 늘어나는지`다.

## 2. 사용자 제안 중 AI가 수용한 것

- **U1** Windows Private Bytes의 호출 전후 차이와 Job의 최대 커밋을 측정한다. 첫 프레임의 계측 실행과 정상 성능 반복 실행을 나눈다. 이전 무기 시트 중복 제거가 적용된 작업 트리에서 두 조건을 비교한다.

## 3. AI가 제안한 것

- **A1, 구현상 판단** 전투에 필요한 NumPy·Numba가 초기화되기 전에 OpenBLAS의 기본 작업 스레드 수를 1로 둔다. 전투 커널은 BLAS를 호출하지 않는다. 사용자 환경에 스레드 설정이 있거나 NumPy가 이미 초기화됐으면 구성을 유지한다.

## 4. AI가 제안한 것 중 사용자가 수용한 것

- **A1**은 U1의 메모리 예산을 맞추기 위한 구현상 판단이다.

## 5. 반영 후 발견한 문제

- **I1** 첫 예열 프레임에서 커밋이 1,836.49→1,961.26MiB가 됐다. `benchmark.before_step`은 0.00MiB, `MovementApplication.update`는 1.00MiB, 화면 효과용 `SDL_CreateTexture` 두 번은 17.97MiB, `MovementApplication.draw_scene`은 105.24MiB, `PicoCanvas.present`는 0.55MiB 증가했다.
- **I1** `draw_scene` 안에서 `UiV2View._combat` 49.27MiB, `EncounterView.draw` 19.24MiB, 지연 `ShaderProgram.__init__` 7.85MiB를 확인했다. HUD 안에서는 `weapons` 15.05MiB, `dialogue` 11.53MiB, `resources` 9.33MiB, `minimap` 8.20MiB였다. 적 렌더 안에서 `PicoRenderer._atlas_text`가 텍스처를 만들 때 17.03MiB가 늘었다. 포함 시간과 포함 메모리 변화는 부모에 다시 합산하지 않는다. 샘플은 프로세스 전체의 순간 순변화이며 드라이버의 내부 할당이나 작업자 할당을 직접 귀속하지 않는다.
- **I2** 별도 무계측 기준에서 첫 프레임 직후 1,952.55MiB였고 예열 30번 프레임에는 2,268MiB 이상이었다. 현재 2GiB 벤치마크는 128MiB 종료 여유를 유지해 첫 프레임 직후 다음 갱신을 중단했다.
- **I3** Numba를 제거하는 진단은 로딩 커밋을 약 774MiB 줄였지만 업데이트 평균이 2.74→5.33ms로 늘었다. 가속 경로를 복원하고 import를 나눴다. 별도 프로세스의 Private Bytes는 초기 11MiB에서 NumPy import 뒤 757MiB, llvmlite 뒤 761MiB, Numba 뒤 779MiB였다. NumPy 2.5.4의 BLAS는 scipy-openblas 0.3.34.106.0이다. `OPENBLAS_NUM_THREADS`를 1·2·4로 지정한 NumPy import 직후는 18.09·50.14·114.51MiB였다.

## 6. 사용자 해결 제안과 실제 해결 과정

- **U1** Intel(R) Graphics 32.0.101.8860에서 180기·간격 15m·HP 100,000·FHD Medium/SMAA·자동 검 60Hz·예열 120·측정 480프레임으로 검증했다. 기준은 이 호스트의 기존 자동 선택과 같은 OpenBLAS 스레드 24개로 재현하고 후보는 게임 기본값을 사용했다. 실제 제한 검사는 논리 CPU 8개·Job CPU 50%·커밋 2GiB를 유지했다. 순서 교차 성능 비교는 같은 CPU 조건에서 양쪽에 4GiB 상한을 적용했다.

## 7. AI 해결 제안과 실제 해결 과정

- **A1** 탄환 충돌과 적 이동이 의존성을 가져오는 지점에 적용했다. `OPENBLAS_NUM_THREADS`, `OPENBLAS_DEFAULT_NUM_THREADS`, `GOTO_NUM_THREADS`, `OMP_NUM_THREADS`를 명시한 환경과 이미 로드된 NumPy는 그대로 둔다. 스레드 기본값은 BLAS 초기화 단계에 적용되며 Numba 커널과 렌더링은 같은 경로를 사용한다. [OpenBLAS 초기화 설정](https://github.com/OpenMathLib/OpenBLAS/blob/develop/docs/runtime_variables.md)
- **2GiB 실기 제한** 로딩 직후 커밋 1,837.55→1,090.48MiB, 첫 프레임 후 1,958.80→1,215.77MiB였다. 전은 두 번째 예열 프레임을 시작하기 전에 중단했고, 후는 예열 120·측정 480프레임을 마쳤다. 변경 후 Job의 최대 커밋은 1,711.21MiB, FPS는 39.72, 작업 P99는 50.76ms였다. 외부 환경 변수만으로 먼저 재현한 실행도 480프레임을 마쳤고 Job 최대 커밋은 1,711.82MiB였다.
- **제한 없는 교차 비교** 전후 각 세 번의 중앙값은 30.75→32.60 FPS, 작업 P99 48.61→47.63ms, 표본 커밋 피크 2,422.30→1,699.05MiB였다. 시간순 각 짝의 P99는 43.85→49.75, 53.26→44.93, 48.61→47.63ms였다.
- **4GiB 상한과 CPU 50% 교차 비교** 전후 각 두 번 평균은 37.20→39.30 FPS, 작업 P99 43.25→51.42ms였다. 업데이트 평균은 3.41→3.29ms였다. 변경 후 가장 느린 프레임은 첫 실행에서 그리기 제출 56.41ms, 두 번째에서 제출 25.20ms와 present 지연이 겹쳤다. 제한 없는 결과와 구분하며 이 CPU 제한 조건의 P99 유지 여부는 판정하지 않았다.
- **현재 작업 트리 재확인** 병행 진행된 HUD 변경이 적용된 상태에서 첫 프레임 커밋 증분은 107.21→109.33MiB, 프레임 직후 총량은 1,973.03→1,234.51MiB였다. `PicoOverdriveFeedback.prepare`는 17.04→17.03MiB, `MovementApplication.draw_scene`은 89.16→91.26MiB였다. 이 안에서 월드 그리기 27.46→28.03MiB와 HUD 47.69→48.37MiB를 확인했다. 새 2GiB 실행도 480프레임을 마쳤다. Job 최대 커밋 1,772.21MiB, FPS 41.76, 작업 P99 64.36ms였다.
- **CPU 100%와 24개 논리 CPU로 맞춘 메모리 제한 교차 비교** 기준에 4GiB, 후보에 2GiB Windows Job 상한을 검증해 적용했다. 같은 해상도·입력·그래픽 설정·적 카탈로그에서 각 두 번 모두 120프레임 예열과 480프레임 측정을 마쳤다. 양쪽 평균은 49.44→48.70 FPS, 작업 P99 35.87→33.61ms, 프로세스 커밋 최고치 2,479.52→1,767.55MiB다. 두 짝의 FPS는 47.09→48.98과 51.79→48.42, P99는 36.79→36.05와 34.94→31.17ms였다. 후보의 두 번 중 최대 커밋은 1,779.12MiB였다.
- 동작·충돌·환경 우선순위 자동 검사 48개가 통과했다. 원자료와 첫 프레임 함수 계측은 `output/performance/first_frame_commit_20261123/`에 보관했다.

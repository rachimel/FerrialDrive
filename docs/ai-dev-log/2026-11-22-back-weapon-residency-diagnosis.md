# 등 무기 방향 캐시 재적재 병목

- 기록 ID `FDLOG-20261122-back-weapon-residency-diagnosis`
- 기록일 2026-11-22 KST
- 기준 `d67cc49`와 당시 작업 트리. NVIDIA GeForce RTX 5070 Laptop GPU, OpenGL 4.6.

## 1. 사용자가 제안한 것

- U1 · 2026-11-22 KST 대화 `[[FDLOG_MISSING_TIME:FDLOG-20261122-back-weapon-residency-diagnosis:U1]]`.
- 전투 중 순환 GC 억제 후 다른 병목을 찾을 필요가 있다고 했다.

## 2. 사용자 제안 중 AI가 수용한 것

- U1을 같은 180기 교전의 후속 병목 계측으로 진행했다.

## 3. AI가 제안한 것

- A1 · 2026-11-22 KST 작업 대화. 이전 실험에서 가장 긴 그리기 구간을 CPU 스레드·SDL 제출과 GPU 구간으로 나눴다. 반복 로드의 조건을 분리하려고 텍스처 메모리 한도와 방향 보관 개수를 각각 바꿔 진단했다.

## 4. AI가 제안한 것 중 사용자가 수용한 것

- 계측 범위와 진단 변형은 AI가 정했다.

## 5. 반영 후 발견한 문제

- I1. CPU 구간 계측의 `MovementApplication.draw_world`는 평균 13.47 ms, P99 24.05 ms였다. `MovementHud.draw` 평균 6.30 ms, `EncounterView.draw` 평균 4.65 ms였다. 마지막 `SDL_RenderFlush` P99는 0.003 ms였다.
- I2. `draw_back_weapon`은 480프레임 중 등 무기 방향 재적재가 발생한 49프레임에서 평균 7.58 ms, 나머지에서 평균 1.05 ms였다. 재적재 프레임에서 `PartAtlasResidency.require` 평균 5.61 ms, 그 안의 `AtlasTextureCache.acquire` 2.54 ms, 방향 기술 정보 구성 1.38 ms, `Future.result` 0.13 ms였다. `acquire` 안의 SDL 적재는 0.99 ms였다. 수치는 중첩 경과 시간이다.
- I3. `PicoV2Renderer._filtered_texture`는 P99 5.14 ms였다. 그 안에서 `SDL_CreateTexture`와 `SDL_SetRenderTarget`의 프레임별 합계 P99는 각각 2.26, 2.23 ms였다.

## 6. 사용자 해결 제안과 실제 해결 과정

- U1은 병목 탐색 범위로 진행했다.

## 7. AI 해결 제안과 실제 해결 과정

- FHD Medium·SMAA, 180기·15m·HP 100,000·자동 검 입력, 무음·VSync 끔으로 예열 120프레임과 측정 480프레임을 실행했다. 각 실행의 최종 교전 상태 해시가 일치했다.
- GPU 타임스탬프 실행에서 적 패스 평균 0.34 ms, P99 0.45 ms였다. 월드 전체 타임스탬프의 P99는 14.95 ms였다. 범위 내부의 CPU 제출 간격과 GPU 유휴 시간도 포함되므로 GPU 바쁜 시간으로 해석하지 않는다.
- A1, I2. 등 무기는 `back_deploy` 전용 비페이지 아틀라스다. 프레임 업로드 예산에 연결된 스트리밍을 사용하지 않으며 `synchronize_upload=False`였다. `max_directions=2` 상태에서 상주하지 않은 방향이 필요할 때 `require`가 전체 방향을 재적재했다. 245회 업로드의 합계는 106.40 MiB였다.
- 비교 시 용량 한도만 64→160 MiB로 변경하자 업로드 245회가 재현됐다. 용량을 64 MiB로 유지하고 방향 보관 수만 2→8로 바꾸자 예열 이후 업로드는 0회였다. 동일 계측의 `draw_back_weapon` P99는 13.58→3.77 ms, 등 무기 캐시 최대 상주량은 7.10→17.59 MiB였다.
- 무계측 원래 설정 2회는 44.39/26.96 FPS, 프레임 P99 33.70/54.23 ms였다. 방향 보관 8개 진단은 27.62 FPS, P99 48.31 ms였다. 실행별 변동이 커 전체 프레임 개선량을 확정하지 않았다.
- 첫 진입에서 방향을 준비하는 시점과 화면 픽셀 검사는 후속 구현에서 확인한다. 이번 변경은 계측 기록이다. 원시 프레임과 함수별 자료는 로컬 `output/performance/combat_next_bottleneck_20261122/`에 보관했다.

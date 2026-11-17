# Combat Test 하드웨어 벤치마크·보고서 연결

- **기록 ID:** `FDLOG-20261117-combat-hardware-benchmark-link`
- 대화 범위: 현재 세션의 combat test 최적화 준비·벤치마크 연결. 개별 발언의 정확한 시각은 제공되지 않았다. `[[FDLOG_MISSING_TIME:FDLOG-20261117-combat-hardware-benchmark-link:scope]]` 검색 단서: `hardware_profile_benchmark.py를 combat test에 연결`.
- 기록 작성: 2026-11-17 KST. 검증은 현재 세션 실행 결과다.
- 상태: 코드·문서 반영, 자동 검사·짧은 실제 렌더 실행 확인. 사용자 직접 조작·사용감 검수·장시간 성능 판정·커밋·업로드는 미수행.

## 1. 사용자가 제안한 것

- **사용자 제안 1 (U1):** combat test를 최적화할 예정이므로 `hardware_profile_benchmark.py`를 연결하고 보고서를 작성할 수 있게 한다. 의도는 현재 전투 최적화 준비다. 근거: 현재 사용자 요청. 시각은 scope 참조.

## 2. 사용자 제안 중 AI가 수용한 것

- U1을 수용해 기존 실행기에 실제 `EncounterApplication`과 현행 적 배치를 연결했다. 게임 동작·렌더러 최적화 완료로 확대하지 않는다.

## 3. AI가 제안한 것

- **AI 제안 1 (A1, 구현상 판단):** `--scenario combat`, 기관단총·Overdrive 자동 입력, 3배속 배율을 추가한다. 기존 제한 게이트·GPU 가드·프레임 계측을 재사용한다. 근거: 현재 코드와 진행 보고. 시각은 scope 참조.
- **AI 제안 2 (A2, 구현상 판단):** JSON에서 한국어 Markdown 보고서를 만들고 생존 적·양측 투사체·전투 진행·일시정지·Overdrive·원거리 무장 프레임을 집계한다. 전투 종료로 낮아진 부하를 구분하기 위함이다. 상세 AI·표현 구간은 `--detail`에만 연결한다. 근거: 현재 코드와 진행 보고. 시각은 scope 참조.

## 4. AI가 제안한 것 중 사용자가 수용한 것

- A1/A2는 U1의 구현상 선택이다. 별도 사용자 응답은 현재 세션에 없으며 세부 방식의 명시 수용·최종 성능 승인으로 취급하지 않는다.

## 5. 반영 후 발견한 문제

- **I1:** 첫 실제 실행에서 자동 조준의 플레이어 좌표를 Vec2로 가정했다. 실제 값은 tuple이므로 AttributeError가 발생했다. AI가 실행 오류로 확인했고 실패 JSON·Markdown은 저장됐다. 시각은 scope 참조.
- **I2:** 기존 Windows 자식 제한 검사에서 UTF-8 자식 출력과 부모 cp949 디코딩이 충돌했다. 기능 오류와 실행 환경 문제를 구분한다. 시각은 scope 참조.

## 6. 사용자 해결 제안과 실제 해결 과정

- 현재 세션에 I1/I2에 대한 별도 사용자 해결 제안은 없다. 요청한 연결·보고서 범위 안에서 AI가 수정·검증했다.

## 7. AI 해결 제안과 실제 해결 과정

- I1: 플레이어 tuple을 풀어 적 Vec2와 제곱 거리로 비교했다. 죽은 적 제외·최근접 선택·좌표 형식 회귀 검사를 추가했다.
- I2: `PYTHONUTF8=1`로 같은 검사를 다시 실행해 통과했다. 기존 검사 파일은 수정하지 않았다.
- 자동 검사: 보고서·자동 입력·교전 집계 6개, 기존 프레임 입력·복구 4개, 하드웨어 프로필 14개 중 13개 통과·1개 GPU 선택 검사 제외. 총 23개 통과·1개 제외다. Windows Job CPU/affinity·64MiB 커밋 조회 검증을 포함한다.
- 실제 실행: low 품질 기관단총+강제 Overdrive, 준비 10/측정 150프레임 완료. 적 30기, Overdrive 150프레임, 진행 중 136프레임, 적 렌더링 instanced, GPU 기능 위반 0을 확인했다. 상세 계측 오버헤드·전투 종료 구간을 포함하므로 최소 사양 충족·장시간 기준 성능으로 확정하지 않는다. 근거: `output/performance/combat_benchmark_link_smg_v2/`.
- 실제 실행: 검 baseline/no_hud 2회 역순 교차, 조건별 준비 3/측정 20프레임으로 비교 4행과 progress 저장 확인. 직접 조작 모드는 준비 3/측정 20프레임의 무입력 실행으로 모드·저장을 확인했으며 사용감 검수는 아니다. 공개 도형 combat은 준비 2/측정 10프레임 완료. 근거: `output/performance/combat_benchmark_link_compare/`, `combat_benchmark_link_manual/`, `combat_benchmark_link_demo/`.
- 실행별 `report.json`, `report.md`, `timings.json`, `limits_final.json`을 저장하고 보고서만 다시 만드는 CLI를 제공한다. 실기 UHD 630 처리량 재현·장시간 조작·3배속 실제 렌더 검증은 미수행이다.

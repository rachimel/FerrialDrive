# Runner의 Combat·Movement 직접 조작 선택

- **기록 ID:** `FDLOG-20261117-runner-benchmark-scenarios`
- 원대화·작성 범위: 2026-11-17 KST 현재 세션. 요청과 진행 보고의 개별 시각은 제공되지 않았다. `[[FDLOG_MISSING_TIME:FDLOG-20261117-runner-benchmark-scenarios:scope]]` 검색 단서: `내가 조작하는 unit_test`, `combat scenario랑 movement`, `Unit Test Runner의 사양 변경`.
- 상태: 코드·현재 실행 규약·문서 반영. 자동 검사·선택창 이미지 검토·제한 프레임 실제 실행 확인. 사용자 직접 조작·외관 수용·장시간 성능 판정·커밋·업로드는 미수행.

## 1. 사용자가 제안한 것

- **사용자 제안 1 (U1):** 직접 조작할 Unit Test를 Runner에서 Combat·Movement로 골라 실행하도록 사양을 변경한다. 이유·의도는 앞서 연결한 벤치마크의 장면 선택과 직접 조작이다. 근거: 현재 사용자 발언. 시각은 scope 참조.

## 2. 사용자 제안 중 AI가 수용한 것

- U1을 수용해 벤치마크 파일의 더블클릭·Enter·드롭에서 실행 선택창을 연다. Combat은 실제 교전, Movement는 기존 `--scenario sword` 훈련장이다. 두 선택 모두 자동 공격·프레임 제한 없이 상세 계측하며 정상 종료 시 보고서를 저장한다.

## 3. AI가 제안한 것

- **AI 제안 1 (A1, 구현상 판단):** 최상위 리터럴 `UNIT_TEST_PRESETS`를 AST로 읽는 공통 선택 규약을 사용한다. 특정 파일 이름을 Runner에 고정하지 않고 테스트 import 없이 선택지를 제공하기 위함이다. 각 항목은 `id`, `label`, 문자열 인자 목록 `args`다. 근거: 현재 코드·진행 보고. 시각은 scope 참조.
- **AI 제안 2 (A2, 구현상 판단):** 선택 전에는 기존 프로세스를 유지하고 Esc로 취소한다. 선택 완료 시 소스와 선택지 ID를 재검사한 뒤 교체한다. 취소·오류 때문에 진행 중인 테스트를 잃지 않도록 한다. 근거: 현재 코드·진행 보고. 시각은 scope 참조.

## 4. AI가 제안한 것 중 사용자가 수용한 것

- A1/A2는 U1의 구현상 선택이며 별도 사용자 수용 응답은 현재 세션에 없다. 외관 승인·사용감 확인으로 확대하지 않는다.

## 5. 반영 후 발견한 문제

- **I1:** 기존 실행 계획 검사의 문자열 경로 비교가 Windows 패키지 임시 경로의 `openai.codex`/`OpenAI.Codex` 대소문자 차이로 실패했다. `.resolve()`는 수정 전부터 사용했으며 실행 경계 기능의 회귀와 구분한다. AI가 자동 검사에서 발견했다. 시각은 scope 참조.

## 6. 사용자 해결 제안과 실제 해결 과정

- 현재 세션에 I1에 대한 사용자 해결 제안은 없다. 요청 범위 안에서 AI가 검사 비교 방식을 수정했다.

## 7. AI 해결 제안과 실제 해결 과정

- I1: 문자열 포함 대신 `Path` 비교를 사용해 해당 OS의 경로 동등성으로 검사한다. 다른 기존 검사 변경은 덮어쓰지 않았다.
- 새 선택 규약 8개와 기존 Runner 검사 38개, 총 **46개 통과**. 비실행 AST 판별·잘못된 메타데이터 차단·취소 시 기존 프로세스 보존·클릭/키보드 선택·선택 후 소스 재검사·실제 자식 argv·기본 즉시 실행 호환을 확인했다.
- 실제 `DropView`와 프로젝트 폰트를 SDL dummy로 렌더링해 선택창 이미지를 직접 열었다. Combat·Movement 행과 안내 문구의 겹침·잘림이 없음을 확인했다. 근거: `output/performance/runner_scenario_selection/selection.png`. 데스크톱 마우스/키보드 조작 검수와 구분한다.
- `prepare_test(..., preset=...)`의 명령을 `RunningTest.start`로 실행했다. 검증용으로만 low·준비 2/측정 10프레임·격리 결과 경로를 덧붙였다. Combat·Movement 모두 `input_mode=interactive`, 완료·GPU 기능 위반 0·JSON/Markdown 저장 확인. UI의 실제 선택값에는 품질 강제·자동 공격·프레임 제한을 넣지 않았다. 근거: `output/performance/runner_scenario_selection/combat/`, `movement/`.
- 사용자는 Runner를 한 번 완전히 닫고 다시 열어 새 GUI를 적용한다. 정상 테스트 창 종료로 보고서를 저장하며 강제 교체·Runner 종료에서는 저장을 보장하지 않는다. 현행 규칙은 `AGENTS.md`, 사용법은 `Tools/unit_test_runner/README.md`와 하드웨어 벤치마크 안내에 반영했다.

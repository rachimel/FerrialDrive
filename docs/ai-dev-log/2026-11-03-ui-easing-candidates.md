# UI 보간 후보 추가

<!-- FDLOG_REVIEW_V1 -->

- 기록 ID: `FDLOG-2026-11-03-ui-easing-candidates`
- 재정리 시각: 2026-11-04 15:59:22 KST
- 범위: 당시 대화/기존 요약의 회고 보완. 이번 재정리가 새 구현·재검증·사용자 승인을 뜻하지 않는다.
- 확인 범위: 이전 요약 문서만 확인했다. 파일명 날짜를 개별 발언 시각으로 사용하지 않는다.
- 원래 대화 시각/범위 — 모름 `[[FDLOG_MISSING_TIME:FDLOG-2026-11-03-ui-easing-candidates:scope]]`. 보완 검색: 원기록 제목 ‘UI 보간 후보 추가’와 관련 대화
- 제안·수용을 직접 입증할 원문 — 모름 `[[FDLOG_MISSING_SOURCE:FDLOG-2026-11-03-ui-easing-candidates:scope]]`. 보완 검색: 원기록의 주제/참고 대화/관련 문서

## 1. 사용자가 제안한 것

- U1(이전 요약 기준): 요청: Flutter의 보간 곡선을 추가 후보로 검토한다.

- 세부 제안별 최초 발의자/원문 — 모름 `[[FDLOG_MISSING_PROPOSAL:FDLOG-2026-11-03-ui-easing-candidates:U1]]`. 보완 검색: 아래 원기록의 요청·결정 절

- 직접 밝힌 이유·의도·판단 근거 — 모름 `[[FDLOG_MISSING_REASON:FDLOG-2026-11-03-ui-easing-candidates:U1]]`. 보완 검색: 해당 제안 전후의 사용자 발언

## 2. AI가 제안한 것

- 독립된 AI 제안의 존재·내용/제안자 — 모름 `[[FDLOG_MISSING_PROPOSAL:FDLOG-2026-11-03-ui-easing-candidates:A1]]`. 보완 검색: 연결된 사용자 발언 사이의 AI 설명·확인 질문

- 원기록의 세부 수치·구조 선택은 구현상 판단일 수 있다. 그것만으로 별도 AI 제안이나 사용자 수용을 확정하지 않는다.

## 3. 사용자 제안 중 AI가 수용한 것

- 이전 요약에서 보고한 반영 범위는 아래와 같다. 원문 수준의 수용 발언은 정확한 AI 수용 발언/시각 — 모름 `[[FDLOG_MISSING_ACCEPTANCE:FDLOG-2026-11-03-ui-easing-candidates:U1]]`. 보완 검색: 요청 직후 AI 응답과 원기록의 반영 절

- 당시 원기록의 반영 보고: `fastEaseInToSlowEaseOut`, `fastLinearToSlowEaseIn`도 후보에 추가했다.

- 당시 원기록의 반영 보고: 기본 SmoothStep 방향은 유지한다. 실제 레이아웃에서 비교한 뒤 곡선별 적용 위치와 채택 여부를 정한다.

- 제안 수용/착수 응답 시각 — 모름 `[[FDLOG_MISSING_TIME:FDLOG-2026-11-03-ui-easing-candidates:adoption]]`. 보완 검색: 연결된 사용자 요청 이후 AI 응답 또는 해당 변경 보고

## 4. AI 제안 중 사용자가 수용한 것

- AI 제안에 대한 사용자 수용·거절 여부 — 모름 `[[FDLOG_MISSING_ACCEPTANCE:FDLOG-2026-11-03-ui-easing-candidates:A1]]`. 보완 검색: A1 원문 확인 후 직후 사용자 답변

- AI가 구현했다는 사실, 침묵이나 다음 요청만으로 승인했다고 쓰지 않는다.

## 5. 반영 후 발견한 문제

- 현재 연결한 자료에서 별도 후속 문제를 확정하지 않았다. 문제가 전혀 없었다는 뜻은 아니다.

- 반영 뒤 문제 제시 여부·발견자·시각 — 모름 `[[FDLOG_MISSING_PROBLEM:FDLOG-2026-11-03-ui-easing-candidates:I1]]`. 보완 검색: 이 주제의 반영 보고 이후 사용자 피드백·검사 결과

## 6. 사용자 해결 제안과 실제 해결 과정

- 후속 문제가 확인되지 않아 사용자 해결안/실제 조치를 단정하지 않는다. I1을 보완한 뒤 U 항목에 연결한다.

## 7. AI 해결 제안과 실제 해결 과정

- 후속 문제가 확인되지 않아 AI 해결안/실제 조치를 단정하지 않는다. 구현 세부를 사후에 해결 제안으로 바꾸지 않는다.

- 당시 확인 결과와 남은 범위:

  - 이번 변경은 후보 정리다. Flutter 도입이나 Python 보간 모듈의 구현·시각 검증 완료를 의미하지 않는다.

- 검증을 수행/보고한 정확한 시각 — 모름 `[[FDLOG_MISSING_TIME:FDLOG-2026-11-03-ui-easing-candidates:V1]]`. 보완 검색: 당시 검사·렌더링 보고의 타임스탬프; 현재 시간으로 대체하지 않는다

## 원기록 — 이전 형식/당시 상태 보존

> 아래 내용은 당시 작성한 기록이다. 위 정리와 후속 결정이 우선한다. 원래 수치·오해·미검증 상태를 지우지 않았다.

# UI 보간 후보 추가

- 작성일: 2026-11-03, 한국 시간
- 요청: Flutter의 보간 곡선을 추가 후보로 검토한다.

## 후보와 의견

- `easeInOutCubicEmphasized`: 사용자가 첫 등장 효과에 관심을 보였다.
- `easeInOutQuint`: 사용자가 중간 진행을 더 빠르게 하고 싶을 때의 후보로 제안했다.
- `elasticInOut`: 탄성 효과 후보이며 적용 여부는 미정이다.
- `fastEaseInToSlowEaseOut`, `fastLinearToSlowEaseIn`도 후보에 추가했다.
- 기본 SmoothStep 방향은 유지한다. 실제 레이아웃에서 비교한 뒤 곡선별 적용 위치와 채택 여부를 정한다.

## 후속 확정

- 사용자가 **elastic 계열을 투명도에 사용하지 않기**로 결정했다. 다른 속성의 적용 여부는 계속 후보로 남긴다.

## 확인과 반영

- 공식 Flutter 문서에서 성질과 구현 형태를 확인하고 [UI Unit Test 명세](../unit-tests/ui_unit_test.md)에 링크와 검토 용도를 추가했다.
- 범위 초과가 있는 탄성 곡선과 투명도 등의 속성 제한, 일부 곡선의 `ThreePointCubic` 구성을 구분해 기록했다.
- 이번 변경은 후보 정리다. Flutter 도입이나 Python 보간 모듈의 구현·시각 검증 완료를 의미하지 않는다.

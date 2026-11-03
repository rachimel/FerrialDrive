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

- 공식 Flutter 문서에서 성질과 구현 형태를 확인하고 [UI Unit Test 명세](../ui_unit_test.md)에 링크와 검토 용도를 추가했다.
- 범위 초과가 있는 탄성 곡선과 투명도 등의 속성 제한, 일부 곡선의 `ThreePointCubic` 구성을 구분해 기록했다.
- 이번 변경은 후보 정리다. Flutter 도입이나 Python 보간 모듈의 구현·시각 검증 완료를 의미하지 않는다.

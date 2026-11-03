# 카운터 숫자 세로 이동 보간 분리

- 작성일: 2026-11-03, 한국 시간
- 사용자 요청: 카운터 갱신에서 숫자의 세로 이동을 페이드·블러와 분리한다. 직전 합의 방향은 세로 이동에만 약한 elasticInOut을 사용하고 다른 효과는 기존 진행률을 유지하는 것이다.
- 공통 애니메이션에 [Flutter 공식 수식](https://api.flutter.dev/flutter/animation/ElasticInOutCurve/transformInternal.html)을 참고한 `elastic_in_out`을 추가했다. 시간 입력의 시작·끝은 0·1로 맞추고, 탄성 출력의 범위 초과는 제한하지 않는다.
- `CounterVisual.vertical_progress`를 위치 전용으로 추가했다. 기존 `progress`·`progress_before`는 SmoothStep의 0~1 값을 유지해 이전 숫자 페이드·블러 강도·길이에 사용한다. `CounterVisibility`의 출현·숨김은 변경하지 않는다.
- 설정 `vertical_easing=elastic_in_out`·`elastic_strength=0.35`·`elastic_period=0.4`는 비교용 시안이다. SmoothStep과 탄성 곡선을 같은 시간에서 혼합하며, 강도 0은 기존 이동·1은 전체 탄성 곡선이다. 보간을 `smooth_step`으로 바꿔도 다른 효과에는 영향을 주지 않는다.
- HIT·DAMAGE에 같은 설정을 연결했다. 표시 원본 값·적중 조건·표시 시간·갱신 병합·초기화·정렬·레이아웃은 유지한다.
- 변경 코드·연결·설정을 읽어 검토했다. 사용자 직접 테스트 방침에 따라 자동 검사·실행·렌더링·실제 창 조작은 수행하지 않았다. 세로 이동의 탄성 인상과 강한 블러와의 조합은 실제 화면 확인 전이다.

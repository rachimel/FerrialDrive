# AI 개발 로그

Ferrial Drive 프로젝트 대화에서 나온 결정과 작업 흐름을 요약한다.

현재 상태는 [UI 작업 정리](../unit-tests/ui_checkpoint.md)와 [UI 명세](../unit-tests/ui_unit_test.md)를 먼저 확인한다. 아래 기록은 변경 이력이며 이전 폰트·수치·표시 동작을 현재 기준으로 적용하지 않는다.

## 기록

- [2026-11-03 레이더 가독성·반경 기준](2026-11-03-radar-readability-radius.md): 화살표 폭 30px·최소 알파 0.3·시선 고정 주변시 평가·200px 임시 유지
- [2026-11-03 현재 UI 폰트 배포 갱신](2026-11-03-font-distribution-update.md): 깍두기 제거·Cafe24 2종/학교안심 OTF와 OFL 고지 포함·별도 다운로드 안내 정리
- [2026-11-03 스틸 블루 UI 배색](2026-11-03-steel-blue-ui-colors.md): 레이블·패널 강조 스틸 블루·HUD 버튼 Bezel·메뉴 버튼 스틸 블루
- [2026-11-03 패널 방사형 그라데이션](2026-11-03-radial-panel-gradient.md): 반사 띠·결 제거·아래 중심의 넓은 광택·숫자 아래 간격 3px
- [2026-11-03 카운터 레이블 크기 정정](2026-11-03-counter-label-size-correction.md): HIT 숫자 76px 복원·후속 조정 HIT/DAMAGE 레이블 18px·추가 자간 5px
- [2026-11-03 금속 패널·카운터 배치](2026-11-03-metallic-panels-counter-labels.md): 정적 금속 질감 재사용·레이블 하단 배치·숫자 확대 오해는 후속 정정
- [2026-11-03 Bezel 패널 시연](2026-11-03-bezel-panel-preview.md): 패널 채움 #39444A 임시 근사색·기존 알파 유지·본편 최종 팔레트와 구분
- [2026-11-03 메인 컬러 Bezel](2026-11-03-main-color-cool-blue-gray.md): Pantone 20-0011 TPM Bezel 참조색 확정·게임용 HEX/RGB/세부 팔레트 미정
- [2026-11-03 선택적 성능 계측](2026-11-03-optional-performance-timing.md): 게임/테스트 공통 시간·호출 수·반복 측정·JSON 로그·UI 선택 연결
- [2026-11-03 UI 승인·최종 코드 정리](2026-11-03-ui-approved-final-cleanup.md): 승인된 표현 유지·글자/링 캐시·반복 상태 생성과 색 설정 감소·실측 전
- [2026-11-03 UI 작업 정리·커밋](2026-11-03-ui-work-checkpoint.md): 현재 상태 요약·완료/미정/미검증 구분·실행기/UI/문서 분리 기록
- [2026-11-03 크로스헤어 상시 갱신](2026-11-03-crosshair-always-update.md): 일시정지·전환 중에도 유효한 포인터 위치 반영
- [2026-11-03 일시정지 제목·설정 버튼](2026-11-03-pause-ohsquare-settings-buttons.md): Ohsquare 일반형 제목·타이틀/일시정지 설정 버튼·설정 기능은 미정
- [2026-11-03 HUD 테스트 버튼 하단 배치](2026-11-03-hud-test-buttons-bottom.md): 테스트 버튼 4개·아래 여백 16px
- [2026-11-03 타이틀 초기화 제거·일시정지 알파](2026-11-03-title-reset-remove-pause-opacity.md): 타이틀 버튼 2개·일시정지 패널 채움 알파 0.85
- [2026-11-03 적 이름 축소·세로 정렬](2026-11-03-target-name-small-center.md): 적 이름 Regular 18px·TARGET과 세로 중심 정렬
- [2026-11-03 전투 HUD 시안 마감](2026-11-03-combat-hud-wrap-up.md): TARGET 14px·적 이름 Regular·사용자 마감 결정·메뉴 후속 작업
- [2026-11-03 레이더 내부 화살표 숨김·HUD 범위](2026-11-03-radar-inner-hide-hud-scope.md): 화면 반경 200px 내부·경계 제외·타겟팅은 고정 샘플 단계
- [2026-11-03 피해 숫자 역순 퇴장·레이더 200px](2026-11-03-damage-tv-off-radar-200.md): 세로→가로 접힘·자체 알파 유지·레이더 반지름 확대
- [2026-11-03 레이더 150px·십자 2px](2026-11-03-radar-150-crosshair-2.md): 레이더 반지름 정수 조정·원과 십자 두께 분리
- [2026-11-03 카운터 페이드 완료 초기화](2026-11-03-counter-reset-on-fade.md): 완전히 숨긴 뒤 HIT·DAMAGE 0으로 재시작·페이드 중 재적중은 누적
- [2026-11-03 일시정지·HUD 반응 조정](2026-11-03-pause-and-hud-response.md): 테스트 기체 표시 분리·Esc 일시정지·카운터 0.20초·레이더 20% 확대·크로스헤어 3px
- [2026-11-03 타겟 표시기 축소](2026-11-03-target-panel-smaller.md): 372×58px·중앙 정렬·여백과 바 폭 조정
- [2026-11-03 HP 감소 구간 효과](2026-11-03-health-loss-trail.md): 진한 빨강 구간·t² 가속·연속 피격 시 현재 위치에서 재시작
- [2026-11-03 피해 TV 등장 가속](2026-11-03-damage-tv-faster.md): 가로 0.05초·세로 0.06초·등장 총 0.11초
- [2026-11-03 피해 숫자 TV 등장·HIT 폰트](2026-11-03-damage-tv-on-hit-font.md): 1px 가로 펼침→세로 펼침·학교안심 운동장 HIT
- [2026-11-03 메뉴 Ohsquare·피해 폰트](2026-11-03-menu-ohsquare-damage-font.md): 메뉴 비교 시안·학교안심 운동장 피해 숫자·HIT 에스코어 드림 유지
- [2026-11-03 전체 폰트·오류 표시](2026-11-03-all-s-core-and-error-summary.md): 에스코어 드림 통일·누락 Cafe24 참조 해소·오류 원인 우선 표시
- [2026-11-03 Runner·UI 독립 실행](2026-11-03-independent-test-processes.md): 자체 UI 루프·별도 프로세스·새로 불러오기·기존 샘플 호환
- [2026-11-03 크로스헤어·실행기 경계](2026-11-03-crosshair-pointer-runner-boundary.md): 마우스 추적·흰색 크로스헤어·Runner 의존과 실행 격리 점검
- [2026-11-03 피해 숫자 무작위 배치](2026-11-03-damage-random-scatter.md): 피격 기체 주변 생성·위쪽 이동 제거·위치 고정 페이드
- [2026-11-03 제목·적 이름 Medium](2026-11-03-title-target-medium.md): 전투 제목 한 단계 굵게·적 이름 한 단계 가늘게·TARGET 유지
- [2026-11-03 카운터 세로 이동 분리](2026-11-03-counter-vertical-easing.md): 이동 보간·페이드/블러 분리·약한 elasticInOut 혼합 시안
- [2026-11-03 적중 시 카운터 표시](2026-11-03-counters-on-target-hit.md): 유효 적중만 HIT/DAMAGE 출현·표시 수명 분리·2초+0.3초 시안
- [2026-11-03 플레이어 옆 HP·레이더](2026-11-03-player-side-hp-radar.md): 공격 반대편 HP 바·제목 Regular·레이더 확대·HIT 명칭·출현 조건 확인 대기
- [2026-11-03 타겟 상단·Bold·6px 바](2026-11-03-target-top-bold.md): 상단 24px 여백·TARGET/적 이름 Bold·HP 바 두께 조정
- [2026-11-03 타겟 패널 압축](2026-11-03-target-compact-header.md): TARGET·이름 양쪽 정렬·HP 숫자 숨김·4px HP 바
- [2026-11-03 HUD 텍스트 폰트 복원](2026-11-03-hud-text-s-core-restore.md): HUD 에스코어 드림·메뉴 Cafe24 PRO·학교안심 운동장 숫자 유지
- [2026-11-03 카운터들 여백 중앙 배치](2026-11-03-counters-center-gap.md): 사용자 명칭·여백 중심을 화면 높이 절반에 고정
- [2026-11-03 콤보·데미지 오른쪽 정렬](2026-11-03-counter-right-stack.md): 공통 오른쪽 끝·콤보 아래 데미지·8px 행 간격
- [2026-11-03 콤보 카운터 효과](2026-11-03-combo-counter-effect.md): 공통 숫자 표시·독립 콤보 상태·동일한 방향성 블러
- [2026-11-03 카운터 방향성 스미어](2026-11-03-counter-directional-smear.md): 변경 숫자만 밀기·위쪽 방향으로 쓸리는 블러
- [2026-11-03 카운터 밀기·페이드](2026-11-03-counter-push-fade.md): 모든 숫자 자리의 위쪽 밀기·이전 숫자 알파 감소·블러 강화
- [2026-11-03 DAMAGE 회전 카운터](2026-11-03-damage-rolling-counter.md): 숫자 옆 DAMAGE 배치·자리별 회전·셔터 잔상과 표시 상태 분리
- [2026-11-03 UI 폰트·배치·거리 표현](2026-11-03-ui-font-layout-distance.md): 학교안심 운동장·Cafe24 PRO 시안, HUD 배치와 적 거리별 삼각형 크기·알파 감소
- [2026-11-03 레이더 채운 삼각형](2026-11-03-filled-radar-indicator.md): 방향 화살표를 채워진 이등변삼각형으로 변경
- [2026-11-03 전투 HUD 제목](2026-11-03-combat-title-layout.md): 좌상단 배치와 전용 크기 설정
- [2026-11-03 적 방향 레이더](2026-11-03-player-direction-radar.md): 플레이어 주변 링과 범위 내 적 방향 화살표
- [2026-11-03 플레이어 중앙 고정](2026-11-03-player-screen-center.md): 화면 크기 기반 중앙 배치와 피해 숫자 기준 정리
- [2026-11-03 UI 글꼴·패널 조정](2026-11-03-ui-font-and-panel.md): 에스코어 드림 통일·Bold 피해·가로 콤보·장식 제거
- [2026-11-03 실제 UI 테스트](2026-11-03-ui-hud-test.md): 메뉴·전투 HUD·분리한 피해 표시·전환 중 입력 소비 구현
- [2026-11-03 자동 검사 폴더 분리](2026-11-03-automated-tests-folder.md): 자동 검사 4개를 tests/automated로 이동
- [2026-11-03 tests 바로 확인](2026-11-03-tests-quick-access.md): 실행기 바로가기와 드롭용 샘플을 tests에 배치
- [2026-11-03 GUI 창 드롭·data 통합](2026-11-03-gui-drop-and-data-merge.md): 드롭 대상을 실행된 Python GUI로 정정하고 폰트를 data로 통합
- [2026-11-03 실행기 아이콘 드롭](2026-11-03-runner-drop-launcher.md): Windows 바로가기·공통 인자 실행·오류 표시와 실제 드롭 확인
- [2026-11-03 화면 설명 문구 기준](2026-11-03-ui-text-style.md): 대화체를 `~한다.` 문체 또는 간결한 표현으로 변경
- [2026-11-03 공통 테스트 실행기](2026-11-03-common-test-runner.md): 게임과 독립된 실행 규약·도구와 두 화면 샘플 구현
- [2026-11-03 UI Unit Test 구현 시작](2026-11-03-ui-unit-test-implementation.md): 공통 애니메이션·버튼·메뉴 렌더링과 확인 대기 항목
- [2026-11-03 프로젝트 대화 요약](2026-11-03-project-summary.md): 툴 선행 개발부터 전투 기획, 저장소 구성, UI Unit Test 범위 확정까지
- [2026-11-03 이미지 파이프라인 정리](2026-11-03-image-pipeline-legacy.md): JANIMA·GPT 흐름 명시와 이전 LoRA 자료 이동
- [2026-11-03 툴 시연 데이터 요구](2026-11-03-tool-demo-data.md): 게임과 독립된 최소 샘플 제공 원칙
- [2026-11-03 UI Unit Test 범위 확정](2026-11-03-ui-unit-test-scope.md): 두 장면·입력·HUD·애니메이션과 `.py` 진입점
- [2026-11-03 UI 보간 후보 추가](2026-11-03-ui-easing-candidates.md): Flutter 곡선 5종의 성질과 검토 용도
- [2026-11-03 현행 문서 정리](2026-11-03-document-maintenance.md): 레거시 안내 제거, 공통 이미지 체크리스트 재사용과 중복 명세 축소
- [2026-11-03 보존 데이터 이동](2026-11-03-output-data-migration.md): output 원본 분리, 참조 수정과 제거 후보 조사
- [2026-11-03 툴 내부 작업 폴더](2026-11-03-tool-workspace.md): 저장 프로젝트·레이아웃·영역 작업의 기본 위치 변경

## 작성 기준

- 날짜는 한국 시간 기준이다. 뒤늦게 정리한 과거 대화는 요약 작성일과 원래 대화 범위를 구분한다.
- 주요 결정·변경 이유·후보·보류·실제 작업 상태를 남긴다. 인사나 같은 내용의 반복은 압축한다.
- 최신 사용자 수정이 현재 기준이다. 이전 검토안과 폐기·후순위 결정을 구분한다.
- 기획·구현·검증·커밋·업로드를 구분한다. 과거 검사 결과는 당시 기록으로 표시한다.
- 원문 전체와 도구 실행 내역은 복사하지 않는다. 민감 정보와 무관한 다른 프로젝트의 대화는 포함하지 않는다.
- 새 기록은 `YYYY-MM-DD-주제.md`로 추가하고 이 목록에 연결한다.

현재 기준은 [작업 지침](../../AGENTS.md)과 [PRE-PRD](../Ferrial_Drive_PRE_PRD_v0.1.md)를 따른다. 로그의 과거 기록은 최신 규칙을 덮어쓰지 않는다.

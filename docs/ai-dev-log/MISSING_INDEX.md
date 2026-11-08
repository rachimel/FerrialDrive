# 대화 기록의 누락 인덱스

- 갱신 기준일: 2026-11-08 KST
- 로컬 전용 서사 기록은 집계에서 제외한다.
- 새 요약 영역만 집계한다. 원기록은 변경하거나 집계하지 않는다.
- 기록 112개 · 누락 필드 456개.
- 사용자 보완은 원문 확인/회고의 출처 표시와 함께 각 기록에 남는다.

[작성 규칙](FORMAT.md) · [기록 양식](_template.md)

검색: `rg -n 'FDLOG_MISSING_' docs/ai-dev-log -g '2026-*.md'`

## 기록별 빠진 필드

| 기록 | 개수 | 종류·항목 |
| --- | ---: | --- |
| [에셋 그림자·광원](2026-11-08-asset-shadow-light.md) | 1 | TIME(scope) |
| [data/catalog 에셋 보관](2026-11-08-asset-catalog-directory.md) | 1 | TIME(scope) |
| [에셋 로더 단일 창](2026-11-08-asset-loader-single-window.md) | 1 | TIME(scope) |
| [에셋 카메라 자동 맞춤](2026-11-08-asset-camera-framing.md) | 1 | TIME(scope) |
| [에셋 로더 제작 흐름](2026-11-08-asset-loader-production.md) | 1 | TIME(scope) |
| [FDrive 에셋 로더](2026-11-08-fdrive-asset-loader.md) | 1 | TIME(scope) |
| [FDrive 60FPS·Live2D 24FPS·화면 옵션](2026-11-08-fdrive-fps-display-options.md) | 1 | TIME(scope) |
| [FDrive 2GiB·적과 이펙트 우선](2026-11-08-fdrive-2gib-resource-priority.md) | 1 | TIME(scope) |
| [FDrive 이펙트 레이어·예산](2026-11-08-fdrive-effect-layer-budget.md) | 1 | TIME(scope) |
| [FDrive 균일 격자·경로 탐색](2026-11-08-fdrive-uniform-grid-pathfinding.md) | 1 | TIME(scope) |
| [FDrive 전투 장면·ADV 요구](2026-11-08-fdrive-combat-scene-adv-requirements.md) | 1 | TIME(scope) |
| [FDrive 초기 책임·선택적 계측](2026-11-08-fdrive-framework-binding-plan.md) | 1 | TIME(scope) |
| [카드 형태·번호/잔탄 정렬](2026-11-04-equipment-cards.md) | 4 | REASON(U2); REASON(U3); PROPOSAL(A1); ACCEPTANCE(A1) |
| [무장 패널 내부 세로 정렬](2026-11-04-equipment-vertical-alignment.md) | 2 | TIME(A1); TIME(V1) |
| [Runner 정렬·루트 링크·종료 복귀](2026-11-04-runner-alignment-focus.md) | 5 | REASON(U2); REASON(U3); REASON(U4); PROPOSAL(A1); ACCEPTANCE(A1) |
| [Runner 텍스트 테마 일치](2026-11-04-runner-typography.md) | 6 | REASON(U1); REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [개별 Unit Test 소개 헤더](2026-11-04-runner-test-introductions.md) | 4 | REASON(U1); TIME(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [Runner 목록·영역·색상 정리](2026-11-04-runner-separators-theme.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [Unit Test Runner 파일 탐색](2026-11-04-runner-file-browser.md) | 2 | REASON(U1); TIME(adoption) |
| [로드아웃 전환 시간 연장](2026-11-04-loadout-duration-half-second.md) | 3 | TIME(A1); ACCEPTANCE(A1); CAUSE(I1) |
| [사용 무기 사다리꼴·스왑 위치 유지·번호 Medium](2026-11-04-weapon-trapezoid-orbit-hold.md) | 5 | REASON(U1); REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [로드아웃 easeInOutQuint 비교](2026-11-04-loadout-ease-in-out-quint.md) | 3 | PROPOSAL(A1); ACCEPTANCE(A1); CAUSE(I1) |
| [무기 스왑 E·로드아웃 교체 F](2026-11-04-weapon-e-loadout-f.md) | 4 | PROPOSAL(A1); RESULT(U1); ACCEPTANCE(A1); PROBLEM(I1) |
| [E 전체 페이드·F 마름모 궤도](2026-11-04-loadout-fade-weapon-diamond.md) | 6 | REASON(U1); REASON(U2); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1) |
| [로드아웃 드럼·번호 페이드·활성 패널 축소](2026-11-04-loadout-drum-number-fade.md) | 7 | REASON(U1); REASON(U2); REASON(U3); TIME(A1); REASON(A1); TIME(adoption); PROBLEM(I1) |
| [도검 패널 축소·PDW 실루엣](2026-11-04-sword-pdw-layout.md) | 6 | REASON(U2); REASON(U3); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1) |
| [오른쪽 무장 HUD·독립 패널·로드아웃 경계 전환](2026-11-04-right-equipment-loadout-slide.md) | 5 | REASON(U1); REASON(U2); TIME(A1); REASON(A1); PROBLEM(I1) |
| [무장 패널 간소화·스왑 애니메이션](2026-11-04-weapon-panel-swap.md) | 5 | REASON(U1); REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [디버그 버튼 하단 진입·자동 숨김](2026-11-04-debug-toolbar-auto-hide.md) | 3 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1) |
| [무장 HUD·메뉴 비선택 명도](2026-11-04-equipment-hud-menu-brightness.md) | 5 | REASON(U2); REASON(U3); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [텍스트 대비 개선](2026-11-04-text-contrast.md) | 6 | REASON(U1); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [레이더·크로스헤어 포인트색 통일](2026-11-04-radar-crosshair-accent.md) | 5 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [레이더 화살표 밑변 추가 확대](2026-11-04-radar-arrow-width.md) | 6 | REASON(U1); REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [레이더 화살표 가독성·반경 평가 기준](2026-11-03-radar-readability-radius.md) | 4 | PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1) |
| [현재 UI 폰트 배포 갱신](2026-11-03-font-distribution-update.md) | 5 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [스틸 블루 UI·장면별 버튼 배색](2026-11-03-steel-blue-ui-colors.md) | 5 | REASON(U2); REASON(U3); REASON(U4); TIME(adoption); PROBLEM(I1) |
| [패널 방사형 그라데이션·레이블 간격](2026-11-03-radial-panel-gradient.md) | 4 | REASON(U2); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1) |
| [카운터 레이블 크기 정정](2026-11-03-counter-label-size-correction.md) | 3 | REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1) |
| [금속 패널·카운터 레이블 시안](2026-11-03-metallic-panels-counter-labels.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [Bezel 근사색 패널 시연](2026-11-03-bezel-panel-preview.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [메인 컬러 레퍼런스: Pantone 20-0011 TPM Bezel](2026-11-03-main-color-cool-blue-gray.md) | 6 | REASON(U1); REASON(U3); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); RESULT(V1) |
| [게임·테스트 공통 성능 계측](2026-11-03-optional-performance-timing.md) | 4 | REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [UI Unit Test 승인·최종 코드 정리](2026-11-03-ui-approved-final-cleanup.md) | 3 | PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [UI 작업 정리·기능별 커밋](2026-11-03-ui-work-checkpoint.md) | 6 | REASON(U1); REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [크로스헤어 위치 상시 갱신](2026-11-03-crosshair-always-update.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [일시정지 제목 Ohsquare·설정 버튼](2026-11-03-pause-ohsquare-settings-buttons.md) | 7 | REASON(U1); REASON(U2); REASON(U3); REASON(U4); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [HUD 테스트 버튼 하단 배치](2026-11-03-hud-test-buttons-bottom.md) | 6 | REASON(U1); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [타이틀 초기화 제거·일시정지 패널 알파](2026-11-03-title-reset-remove-pause-opacity.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [적 이름 축소·세로 중심 정렬](2026-11-03-target-name-small-center.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [전투 HUD 시안 마감·메뉴 후속 작업](2026-11-03-combat-hud-wrap-up.md) | 3 | PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [레이더 원 안의 화살표 숨김·HUD 범위 평가](2026-11-03-radar-inner-hide-hud-scope.md) | 5 | REASON(U1); REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [피해 숫자 역순 퇴장·레이더 200px](2026-11-03-damage-tv-off-radar-200.md) | 6 | REASON(U1); REASON(U2); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1) |
| [레이더 150px·십자 2px](2026-11-03-radar-150-crosshair-2.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [카운터 페이드 완료 시 초기화](2026-11-03-counter-reset-on-fade.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [일시정지·테스트 표시 분리·HUD 반응 조정](2026-11-03-pause-and-hud-response.md) | 6 | REASON(U1); REASON(U2); REASON(U3); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [타겟 표시기 가로·세로 축소](2026-11-03-target-panel-smaller.md) | 4 | PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [HP 감소 구간·진한 빨강·가속·재피격 재시작](2026-11-03-health-loss-trail.md) | 5 | REASON(U2); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1) |
| [피해 숫자 TV 등장 속도 증가](2026-11-03-damage-tv-faster.md) | 5 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [피해 숫자 TV 켜짐 등장·HIT 숫자 폰트](2026-11-03-damage-tv-on-hit-font.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [메뉴 Ohsquare Air 비교·피해 숫자 학교안심 운동장 복원](2026-11-03-menu-ohsquare-damage-font.md) | 5 | REASON(U1); REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [UI 전체 에스코어 드림 통일·실행 오류 가독성 수정](2026-11-03-all-s-core-and-error-summary.md) | 5 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [Runner와 UI 테스트 실행 경계 분리](2026-11-03-independent-test-processes.md) | 3 | PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1) |
| [흰색 크로스헤어 마우스 추적·실행기 경계 점검](2026-11-03-crosshair-pointer-runner-boundary.md) | 6 | REASON(U2); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [이번 피해 숫자를 피격 위치 주변에 무작위 배치](2026-11-03-damage-random-scatter.md) | 6 | REASON(U1); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [전투 제목·적 이름 굵기 한 단계 조정](2026-11-03-title-target-medium.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [카운터 숫자 세로 이동 보간 분리](2026-11-03-counter-vertical-easing.md) | 4 | REASON(U1); REASON(U2); TIME(adoption); PROBLEM(I1) |
| [플레이어 옆 HP 바·제목 굵기·레이더 조정](2026-11-03-player-side-hp-radar.md) | 4 | REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [적중 시 HIT·DAMAGE 표시](2026-11-03-counters-on-target-hit.md) | 5 | REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [타겟 패널 상단 이동·Bold·6px 바](2026-11-03-target-top-bold.md) | 6 | REASON(U1); REASON(U2); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1) |
| [타겟 패널을 한 줄 제목과 얇은 HP 바로 압축](2026-11-03-target-compact-header.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [HUD 텍스트를 에스코어 드림으로 복원](2026-11-03-hud-text-s-core-restore.md) | 6 | REASON(U1); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [카운터들 사이 여백을 화면 중앙에 배치](2026-11-03-counters-center-gap.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [콤보·데미지 오른쪽 정렬과 좁은 행 간격](2026-11-03-counter-right-stack.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [콤보에 동일한 카운터 효과 적용](2026-11-03-combo-counter-effect.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [변경 숫자만 이동·방향성 스미어](2026-11-03-counter-directional-smear.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [누적 피해 카운터 밀어 올리기·페이드·블러 강화](2026-11-03-counter-push-fade.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [DAMAGE 가로 배치와 회전 카운터](2026-11-03-damage-rolling-counter.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [UI 폰트 시안·배치·레이더 거리 표현](2026-11-03-ui-font-layout-distance.md) | 6 | REASON(U1); REASON(U2); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1) |
| [레이더 방향 표시를 채운 삼각형으로 변경](2026-11-03-filled-radar-indicator.md) | 5 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [전투 HUD 제목 좌상단 배치](2026-11-03-combat-title-layout.md) | 5 | PROPOSAL(A1); RESULT(U1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [플레이어 주변 적 방향 레이더](2026-11-03-player-direction-radar.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [플레이어 화면 중앙 고정](2026-11-03-player-screen-center.md) | 6 | REASON(U1); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [UI 글꼴·패널·콤보 표시 조정](2026-11-03-ui-font-and-panel.md) | 4 | REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [실제 메뉴·전투 HUD 테스트 구현](2026-11-03-ui-hud-test.md) | 8 | REASON(U1); REASON(U2); REASON(U3); REASON(U4); REASON(U5); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [자동 검사 폴더 분리](2026-11-03-automated-tests-folder.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [tests 폴더에서 바로 확인](2026-11-03-tests-quick-access.md) | 5 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [GUI 창 드롭으로 정정하고 에셋 폴더 통합](2026-11-03-gui-drop-and-data-merge.md) | 3 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1) |
| [공통 테스트 실행기 아이콘 드롭 지원](2026-11-03-runner-drop-launcher.md) | 3 | PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [화면 설명 문구 작성 기준](2026-11-03-ui-text-style.md) | 4 | REASON(U1); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [게임과 독립된 공통 테스트 실행기](2026-11-03-common-test-runner.md) | 6 | REASON(U1); REASON(U2); PROPOSAL(A1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1) |
| [UI Unit Test 구현 시작](2026-11-03-ui-unit-test-implementation.md) | 4 | REASON(U2); PROPOSAL(A1); ACCEPTANCE(A1); PROBLEM(I1) |
| [UI Unit Test 범위 확정](2026-11-03-ui-unit-test-scope.md) | 10 | TIME(scope); SOURCE(scope); PROPOSAL(U1); REASON(U1); PROPOSAL(A1); ACCEPTANCE(U1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [UI 보간 후보 추가](2026-11-03-ui-easing-candidates.md) | 10 | TIME(scope); SOURCE(scope); PROPOSAL(U1); REASON(U1); PROPOSAL(A1); ACCEPTANCE(U1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [툴 내부 작업 폴더](2026-11-03-tool-workspace.md) | 10 | TIME(scope); SOURCE(scope); PROPOSAL(U1); REASON(U1); PROPOSAL(A1); ACCEPTANCE(U1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [툴 시연 데이터 요구](2026-11-03-tool-demo-data.md) | 10 | TIME(scope); SOURCE(scope); PROPOSAL(U1); REASON(U1); PROPOSAL(A1); ACCEPTANCE(U1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [프로젝트 대화 요약](2026-11-03-project-summary.md) | 10 | TIME(scope); SOURCE(scope); PROPOSAL(U1); REASON(U1); PROPOSAL(A1); ACCEPTANCE(U1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [보존 데이터 이동과 제거 후보 조사](2026-11-03-output-data-migration.md) | 10 | TIME(scope); SOURCE(scope); PROPOSAL(U1); REASON(U1); PROPOSAL(A1); ACCEPTANCE(U1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [이미지 파이프라인 정리](2026-11-03-image-pipeline-legacy.md) | 10 | TIME(scope); SOURCE(scope); PROPOSAL(U1); REASON(U1); PROPOSAL(A1); ACCEPTANCE(U1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); TIME(V1) |
| [현행 문서 정리](2026-11-03-document-maintenance.md) | 10 | TIME(scope); SOURCE(scope); REASON(U1); PROPOSAL(A1); ACCEPTANCE(U1); TIME(adoption); ACCEPTANCE(A1); PROBLEM(I1); RESULT(V1); TIME(V1) |

## 유형별 남은 필드

| 유형 | 개수 |
| --- | ---: |
| ACCEPTANCE | 89 |
| CAUSE | 2 |
| PROBLEM | 76 |
| PROPOSAL | 86 |
| REASON | 111 |
| RESULT | 4 |
| SOURCE | 8 |
| TIME | 80 |

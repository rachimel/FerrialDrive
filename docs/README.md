# Ferrial Drive 문서

현재 기준은 최신 사용자 지시 → `AGENTS.md` → PRE-PRD·현행 개별 명세에서 확인한다. 날짜가 있는 개발 기록·과거 보고서·보관 도구는 당시 상태의 근거이며 현재 제작 방법이나 품질 승인으로 재사용하지 않는다.

3D 흐름은 **Blender 모델링 → 리그 없는 형상 → Unreal 새 리깅·애니메이션·프리렌더 → PNG 파츠+JSON → 툴 2D 조립·패킹 → Pico2D**다. 기존 Blender 리그는 재사용하지 않는다. 프리렌더는 Unreal, 2D 파츠 조립·패킹은 기존 툴에서 수행한다. [제작·인계 조건](ai-asset-pipeline/unreal_pipeline.md)과 [자동화 경로](../automate/README.md)를 따른다.

## 기획

- [전투 테스트](../samples/combat_test_v1_5/README.md): 다수 적 교전 실행과 조작
- [초기 1대1 전투 기록](unit-tests/combat_prototype.md): 도형 기체 교전 구현과 과거 검증 범위
- [검 이동 Unit Test](unit-tests/sword_movement.md): 실제 검 장착 기체·1km 흙바닥·눈금·달리기/대시/부스트·그림자

- [사전 PRD v0.1](Ferrial_Drive_PRE_PRD_v0.1.md): 현재 게임 설계·훈련 데모 범위·검토안·미정 사항
- [메카·군사 기술 세계관](FerrialDrive_Mech_Worldbuilding.md): AI/파일럿·범용 훈련 플랫폼·주동력 리액터/폐열 회수·무장 운용과 후보 설정
- 후속 서사 기획: 로컬 전용으로 관리하며 Git 추적·공개 대상에서 제외한다.
- [UI Unit Test 명세](unit-tests/ui_unit_test.md): 이동·UI 훈련장의 검증 범위와 미정 사항
- [상세 기획서 PPT](presentation/기획서.pptx): 기존 29쪽 초안. 이후 결정은 PRE-PRD와 개별 명세를 따른다.

## 발표

- [발표자료 PPT](presentation/발표자료.pptx): 기존 10쪽 공개본. AI 콘셉트 이미지는 제외

## 현재 도구

- [FDrive 공통 실행부·렌더링](rendering.md): 본편/도구/독립 테스트의 OpenGL 캔버스·Bicubic·입력/표시 루프·자원 수명
- [FDrive 에셋 로더](../Tools/asset_loader/README.md): 2D 파츠·애니메이션 조립·미리보기·등록·디버그 핫 로드·공통 자원 관리
- [대화 기록](../Tools/conversation_log_viewer/README.md): 읽기용 Markdown·누락 설명·Codex 원문 검색·한국 시각·범위 가져오기·저장/취소
- [Codex 원문 근거 작성](tool-usage/conversation_log_evidence.md): 대화/발언 식별·짧은 인용·회고와 원문 확인 구분
- [Theme Reference](theme_reference.md): 도구 공통 색상·글꼴·간격·선의 역할
- [독립 Unit Test 실행기](../Tools/unit_test_runner/README.md): `.py` 선택·별도 프로세스 실행·종료·오류 표시
- [공통 성능 계측](tool-usage/performance_timing.md): 게임·테스트의 선택적 구간/함수 측정·반복 벤치마크·JSON 로그
- [표정 스튜디오 및 AI 영역 지정](tool-usage/portrait_editor.md)
- [Blender 모델링·기존 출력](ai-asset-pipeline/blender_pipeline.md)
- [Unreal 제작·프리렌더·2D 인계](ai-asset-pipeline/unreal_pipeline.md)
- [Unreal 조작 도구](../Tools/unreal_pipeline/README.md): 기존 골격 FK 편집·FBX 왕복과 현재 작업본
- [Unreal 메카 제어점 편집](tool-usage/unreal_animation_editing.md): 새 리그 열기·본 선택·이동/회전·키 저장·표시 설정
- [자동화 경로](../automate/README.md): 실행 진입점·필수 파일·런타임·보존 입력
- [툴 시연용 테스트 데이터 기준](tool-usage/tool_demo_data.md): 게임과 독립된 최소 샘플과 시연 완료 조건
- [저장 경로 안내](tool-usage/storage_layout.md): 보존 데이터와 재생성 가능한 출력 구분
- [제거 후보 목록](tool-usage/cleanup_candidates.md): 용량·중복 조사 결과, 사용자 판단 전 삭제 보류

## 개발 기록

- [AI 개발 로그](ai-dev-log/README.md): 프로젝트 대화의 주요 결정, 변경 이유와 작업 상태

## 아트 제작

메카의 조형 기준은 [메카 디자인·제작 규칙](ai-asset-pipeline/mech_design_rules.md), 실행 절차는 [모델 제작 흐름](ai-asset-pipeline/model_workflow.md)에서 관리한다.

현재 흐름은 **JANIMA로 레퍼런스 이미지 생성 → GPT로 디테일 보정**이다.
AI 생성 이미지·모델과 가공 에셋은 로컬에 보관한다.

- [이미지 제작 파이프라인](ai-asset-pipeline/image_pipeline.md): 현행 제작 흐름과 이전 LoRA 자료의 경계
- [애니메이션 제작 흐름](ai-asset-pipeline/animation_workflow.md): Unreal 짧은 동작 초안·전체 재생 검수·수정·반환. 별도 KeyPose 사전 승인 없음
- [동작 검토와 이전 카탈로그](tool-usage/mech_keypose_catalog.md): 현재 재생 검토 항목과 보관된 Blender 정지 자세 자료
- [이미지 보정 체크리스트](ai-asset-pipeline/image_correction_checklist.md): 손·발·겹침·비율·조명 확인에 재사용하는 품질 기준
- [로제 프롬프트 기록](ai-asset-pipeline/rose_art_prompts.md): 현재 기준 레퍼런스와 생성·편집 이력

## 이전 자료


- [legacy 안내](../legacy/README.md): 이전 LoRA 검토 자료, 현행 파이프라인과 분리

## 시험 및 개선 기록

과거 시험 기록은 로컬 `docs/report-archive/`에 보관하며 Git 업로드에서는 제외한다.
시험 기록의 실행 스크립트와 일부 산출물은 정리되어 현재 구성과 다를 수 있다.
현재 실행 방법은 위 도구 문서를 기준으로 한다. 도구가 참조하는 로컬 에셋은 저장소에 포함하지 않는다.

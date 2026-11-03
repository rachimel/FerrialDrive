# Ferrial Drive 문서

## 기획

- [사전 PRD v0.1](Ferrial_Drive_PRE_PRD_v0.1.md)
- [UI Unit Test 명세](ui_unit_test.md): 메뉴·전투 HUD의 독립 검증 범위와 미정 사항
- [상세 기획서 PPT](기획서.pptx): 기존 29쪽 초안. 이후 결정은 PRE-PRD와 개별 명세를 따른다.

## 발표

- [발표자료 PPT](발표자료.pptx): 기존 10쪽 공개본. AI 콘셉트 이미지는 제외

## 현재 도구

- [표정 스튜디오 및 AI 영역 지정](portrait_editor.md)
- [Blender 원본 생성](blender_pipeline.md)
- [툴 시연용 테스트 데이터 기준](tool_demo_data.md): 게임과 독립된 최소 샘플과 시연 완료 조건

## 개발 기록

- [AI 개발 로그](ai-dev-log/README.md): 프로젝트 대화의 주요 결정, 변경 이유와 작업 상태

## 아트 제작

현재 흐름은 **JANIMA로 레퍼런스 이미지 생성 → GPT로 디테일 보정**이다.
AI 생성 이미지·모델과 가공 에셋은 로컬에 보관한다.

- [이미지 제작 파이프라인](image_pipeline.md): 현행 제작 흐름과 이전 LoRA 자료의 경계
- [이미지 보정 체크리스트](image_correction_checklist.md): 손·발·겹침·비율·조명 확인에 재사용하는 품질 기준
- [로제 프롬프트 기록](rose_art_prompts.md): 현재 기준 레퍼런스와 생성·편집 이력

## 이전 자료

- [legacy 안내](../legacy/README.md): 이전 LoRA 검토 자료, 현행 파이프라인과 분리

## 시험 및 개선 기록

과거 시험 기록은 로컬 `docs/report-archive/`에 보관하며 Git 업로드에서는 제외한다.
시험 기록의 실행 스크립트와 일부 산출물은 정리되어 현재 구성과 다를 수 있다.
현재 실행 방법은 위 도구 문서를 기준으로 한다. 도구가 참조하는 로컬 에셋은 저장소에 포함하지 않는다.

# 제거 후보 목록

기준일: 2026-11-03, 한국 시간. **후보만 조사했으며 삭제하지 않았다.**

A는 재생성 가능한 자료 위주, B는 이전 작업·원본 보관 여부를 확인할 자료다. 제거 여부는 사용자가 결정한다.

## 후보

| ID | 대상 | 파일 수 | 크기(MiB) | 판단 근거 |
| --- | --- | ---: | ---: | --- |
| A1 | **실행용 모델 캐시** — `output/portrait_editor/.runtime/` | 458 | 446.42 | 리깅 원본·저장 프로젝트에서 다시 생성. 툴 종료 후 정리 후보. |
| A2 | **셰이더 복사본** — `output/**/shader-runtime-*/` | 69 | 0.13 | 설치된 런타임의 셰이더에서 다시 생성. 원본 라이선스·설치 패키지는 유지. |
| A3 | **자동 검증·성능 진단 결과** — `output/**/qa*/`, `performance-diagnosis/` | 109 | 32.32 | 테스트 산출물. 이전 결과를 비교할 필요가 없다면 정리 후보. |
| A4 | **발표자료 미리보기·렌더 캐시** — `output/presentation*/`, `repository-presentations/`의 PNG·PDF·LibreOffice 프로필 | 460 | 37.64 | PPT·제작 원본과 분리된 렌더 자료. 보관할 PPT를 먼저 확인. |
| A5 | **임시 점검 스크립트·보고서** — `output/repository-maintenance/` | 9 | 0.79 | 이번 정리의 보조 자료. 이동·복구 기록은 data에 별도 보존. |
| A6 | **실행 로그·일반 파생 파일** — 그 밖의 `output/` 실행 기록 | 2 | 0.03 | 기본 실행에 필요한 원본으로는 참조되지 않음. 문제 추적 필요 여부를 판단. |
| A7 | **Python 바이트코드 캐시** — `Tools/**/__pycache__/` | 12 | 0.28 | 소스에서 다시 생성. 가상환경과 vendor 원본은 포함하지 않음. |
| B1 | **과거 Live2D 시험 자료** — 남은 `output/capability_test/` | 124 | 48.21 | 현행 원본은 옮겼지만 과거 모델·보정 전후 이미지·구버전 기록이 남음. 보관 여부 확인 후 판단. |
| B2 | **발표자료 작업본·제작 스크립트** — 발표 폴더의 나머지 PPT·원본·JS·JSON | 134 | 40.78 | 수정 이력이나 유일한 제작 스크립트일 수 있음. 최종 보관본을 결정하기 전 전체 삭제 보류. |
| B3 | **Blender 이전 저장본** — `data/portrait_editor/rig/portrait-refined-rig.blend1` | 1 | 1.50 | 현행 blend와 별개인 이전 저장본. 되돌릴 필요가 있는지 사용자가 판단. |

현재 output 합계는 약 **606.30 MiB**다. 도구 캐시를 다시 생성하면 수치는 변한다. 후보 분류는 중복 합산하지 않았으며, 아래 동일본 목록은 위 분류의 일부다.

## 공개 보관본과 내용이 같은 PPT

SHA-256으로 동일함을 확인한 output 파일이다. 오른쪽 보관본을 유지하는 조건으로 중복 제거를 검토할 수 있다.

| output 후보 | 유지할 공개 보관본 |
| --- | --- |
| `output/repository-presentations/build/기획서-초안.pptx` | `docs/presentation/기획서.pptx` |
| `output/repository-presentations/build/발표자료-공개초안.pptx` | `docs/presentation/발표자료.pptx` |
| `output/repository-presentations/deliverables/기획서-제압규칙.pptx` | `docs/presentation/기획서.pptx` |
| `output/repository-presentations/deliverables/발표자료.pptx` | `docs/presentation/발표자료.pptx` |

## 현재 보존할 데이터

- `data/portrait_editor/rig/`: 현행 리깅 JSON·텍스처·Blender 파일과 원본 모델 묶음. 위 B3만 별도 검토 후보다.
- `data/portrait_editor/inputs/`: Blender 재생성 입력과 생성 기록.
- `data/portrait_editor/workspace/`: 저장 프로젝트와 레이아웃.
- `data/portrait_editor/exports/`: 기존 내보내기 보관본. 원본과 비교하기 전 제거 후보로 잡지 않았다.
- `data/migrations/2026-11-03-output-assets/`: 이동 목록·해시와 프로젝트 원본 백업.
- `Tools/`, 실행 가상환경, vendor의 제3자 소스·라이선스, Git 기록과 사용자가 재배치한 문서는 유지한다.

## 이번 이동

원본·작업 파일 43개를 옮겼다. 전부 이동 직후 해시가 일치했으며, 저장 프로젝트는 리깅 참조만 새 위치로 변경했다. 다른 편집 값은 원본 백업과 비교했다. 그 밖의 후보는 이동·삭제하지 않았다.

데이터 위치와 검증 범위는 [저장 경로 안내](storage_layout.md)를 따른다. 상세 파일 목록은 로컬 `output/repository-maintenance/cleanup-inventory.json`에 남긴다.

# 저장 경로 안내

`output/`에는 재생성 가능한 출력·캐시·검증 결과만 둔다. 원본·편집 프로젝트·설정은 밖에 보존한다.

원본·에셋의 최상위 폴더는 **`data/`로 통합**한다. 기존 `assets/fonts/`의 공개 폰트·이용 조건 9개를 `data/fonts/`로 옮겼다. 기존 data 자료와 폰트는 덮어쓰지 않았고, 9개 파일 모두 이동 전후 SHA-256이 같다. 이동 기록은 `data/experiments/migrations/2026-11-03-assets-merge/manifest.json`에 보관한다.

## 3D 제작 작업본과 반환

현행 역할은 [Unreal 제작·반환 계약](../ai-asset-pipeline/unreal_pipeline.md)을 따른다.

| 경로 | 용도 |
| --- | --- |
| `data/source/models/` | Blender 모델링 원본·최종 모델·텍스처 |
| `Tools/blender_pipeline/workspace/<asset_id>/` | 모델링/검사 설정과 부품 레지스트리 |
| `Tools/unreal_pipeline/workspace/<asset_id>/` | Unreal 프로젝트·리그·Sequence·출력 단위·카메라 |
| `automate/` | 자동화 진입점·공통 모듈 라우팅·형상 인계·새 리그 작업 |
| `automate/bin/`, `automate/runtime/`, `automate/packages/` | 필수 실행 파일·런타임·재설치 패키지. 로컬 전용 |
| `automate/workspace/` | 자동화 요청·보존 입력·이동 목록/해시. 로컬 전용 |
| `Tools/asset_loader/workspace/` | Unreal 렌더를 입력한 2D 파츠/레이어 작업본·설정 |
| `output/` | 재생성 가능한 렌더·미리보기·캐시·검사 결과 |
| `samples/unreal_pipeline/` | 게임 에셋과 독립된 기본 도형 교환 요청·안내 |

Unreal 편집 프로젝트와 인계 파일을 구분해 보존한다. 프리렌더는 Unreal에서 수행하고 PNG 파츠+JSON을 툴의 2D 조립·패킹으로 인계한다.  기존 실험 경로는 보존하고 새 자동화의 요청·런타임은 [automate](../../automate/README.md)에서 관리한다. Pose Tool의 기존 작업본은 보관 자료다. 위 모델·프로젝트·교환/반환 산출물은 Git 제외 범위에 둔다.

## 표정 스튜디오

| 경로 | 용도 |
| --- | --- |
| `data/fonts/` | 공개 폰트와 저작권·이용 조건. 지정 경로만 Git에 포함 |
| `data/source/portrait_editor/rig/` | 리깅 JSON·텍스처·Blender 파일·원본 모델 |
| `data/source/portrait_editor/inputs/` | Blender 생성 입력 이미지와 생성 기록 |
| `Tools/portrait_editor/workspace/` | 저장 프로젝트·레이아웃·영역 편집 작업의 기본 위치 |
| `data/source/portrait_editor/exports/` | 내보내기 기본 폴더와 기존 보관본 |
| `data/experiments/migrations/2026-11-03-output-assets/` | 이동 목록·해시·프로젝트 원본 백업 |
| `output/portrait_editor/` | 실행용 모델 캐시·캡처·로그·검증 결과 |
| `output/blender_pipeline/previews/` | Blender 미리보기 렌더 |

경로는 실행 위치 대신 프로젝트·모듈 위치를 기준으로 해석한다. 실행용 모델 캐시는 리깅 원본과 저장 프로젝트에서 다시 만든다. 작업 저장과 내보내기는 목적이 다르므로, 내보낸 모델만 남기고 편집 프로젝트를 지우지 않는다.

AI 생성 이미지·모델과 가공 에셋을 포함한 `data/`는 공개 폰트 지정 경로만 예외로 두고 Git에서 제외한다. `output/`·`Tools/*/workspace/`도 제외한다. 작업 폴더는 툴 실행 시 생성한다. 공개 시연용 최소 샘플은 별도 요구사항이며 이번 이동으로 제공된 것은 아니다.

## 2026-11-03 이동

- 원본·생성 입력·작업 파일 43개, 약 14.35 MiB를 이동했다. 덮어쓰거나 삭제하지 않았다.
- 이동 직후 43개 모두 SHA-256이 일치했다. 저장 프로젝트는 `rig_source`만 `../rig/blender-keyforms.json`으로 바꾸고, 나머지 값과 원본 백업을 비교했다.
- 도구의 기본 경로와 Blender 생성 경로를 수정했다. MCP 실행에서도 스크립트의 실제 위치를 전달한다.
- 기존 자동 검사 14개와 기본 원본을 사용하는 CLI 모델 내보내기를 확인했다. 실제 창 조작과 Blender 재생성은 이번에 실행하지 않았다.
- 다른 작업 폴더에서 저장 프로젝트를 불러왔고 리깅·모델 3개의 텍스처 참조가 모두 존재했다. 문서 23개의 내부 파일 링크에 누락이 없고, 공개 PPT 두 개의 내용도 이동 전과 같았다.

이후 사용자가 output 삭제를 알렸다. [제거 후보 목록](cleanup_candidates.md)은 삭제 전 조사 기록이며 현재 파일 목록으로 보지 않는다. 툴 실행·자동 검사로 output 캐시가 다시 생길 수 있다.

## 툴 내부 작업 폴더로 변경

저장 프로젝트와 레이아웃을 `data/source/portrait_editor/workspace/`에서 `Tools/portrait_editor/workspace/`로 옮겼다. 프로젝트의 리깅 참조만 새 상대 경로로 바꾸고 다른 편집 값은 유지했다. 이동 기록과 수정 전 백업은 `data/experiments/migrations/2026-11-03-tool-workspace/`에 보관한다. 원본과 내보내기 위치는 위 표를 따른다.

# 데이터 배치

| 경로 | 용도 |
| --- | --- |
| `source/models/` | Blender 모델 원본, 재질·텍스처와 기준 레지스트리 |
| `source/portrait_editor/` | 초상화 제작 입력·리그·보존할 내보내기 |
| `source/audio/` | 오디오 수집 원본·편집 프로젝트·수정본 |
| `runtime/catalog/` | 파츠·메카·프리렌더 에셋 카탈로그 |
| `runtime/frame_interpolation/` | 보간 카탈로그·기준 프레임·모션 벡터 |
| `runtime/animations/` | 검 궤적·총구·접지 좌표와 표시 기준 |
| `runtime/textures/` | 게임 및 비교 프로그램이 사용하는 압축 아틀라스·품질별 묶음 |
| `runtime/images/` | UI·VFX·렌더링용 이미지 |
| `runtime/audio/` | 게임용 음원·음원 bank |
| `runtime/effects/` | 게임 효과의 보존 입력 |
| `references/` | 캐릭터·장착 등 참고 이미지 |
| `experiments/migrations/` | 과거 이관 기록·스크립트 보관본 |
| `fonts/` | 공용 폰트·출처·이용 조건 |
| `settings/` | 게임 설정 |

- 날짜·버전이 붙은 하위 폴더도 다른 카탈로그가 참조할 수 있다. 이름만으로 삭제하거나 최신 폴더 하나만 남기지 않는다.
- JSON의 경로 기준은 해당 모듈의 규약을 따른다. 문서 상대 경로와 프로젝트 루트 상대 경로를 구분한다.
- 압축 비교에서 만든 결과라도 현재 게임이 읽는 묶음은 `runtime/textures/`에서 관리한다. 재생성 가능한 일시 출력·캐시·검증 결과는 `output/`에 둔다.
- 툴의 새 편집 작업본·설정은 `Tools/<tool_name>/workspace/` 규칙을 따른다. 기존 제작 데이터의 경로는 해당 툴의 경로 모듈에서 관리한다.
- `experiments/migrations/`의 과거 경로는 이력이다. 보관 스크립트를 현재 제작 명령으로 실행하지 않는다.
- AI 생성 에셋은 공개 저장소에 포함하지 않는다. 이 안내와 명시적으로 허용된 폰트만 Git 추적 대상이다.

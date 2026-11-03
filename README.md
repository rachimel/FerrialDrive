# Ferrial Drive

Python과 Pico2D로 개발할 **2D 실시간 메카 액션 RPG**.
JRPG식 3/4 Top-Down 화면과 사전 렌더링한 2D 에셋을 사용한다.

## 현재 상태

현재는 **메뉴·전투 HUD·장면 전환을 확인할 독립 UI Unit Test**를 구현하는 단계다. 공통 애니메이션·버튼 입력·메뉴 렌더링 초안이 있으며, HUD·장면 전환·독립 실행 진입점은 아직 연결하지 않았다. 게임 전투 프로토타입은 미구현이다.

- [사전 PRD](docs/Ferrial_Drive_PRE_PRD_v0.1.md): 게임 방향, 현재 결정한 규칙, 미정 사항
- [UI Unit Test 명세](docs/unit-tests/ui_unit_test.md): 현재 우선 검증할 두 장면·입력·HUD·애니메이션
- [독립 Unit Test 실행기](Tools/unit_test_runner/README.md): 공통 실행 규약과 테스트 `.py` 실행 방법
- [문서 목록](docs/README.md): 제작 도구와 데이터 준비 문서
- [이미지 제작 파이프라인](docs/ai-asset-pipeline/image_pipeline.md): JANIMA 레퍼런스 생성 → GPT 디테일 보정
- [상세 기획서 PPT](docs/presentation/기획서.pptx): 기존 29쪽 초안. 이후 결정은 PRE-PRD를 따른다.
- [발표자료 PPT](docs/presentation/발표자료.pptx): AI 콘셉트 이미지를 제외한 기존 10쪽 공개본

## UI 검증 이후 전투 프로토타입 목표

임시 에셋으로 메카 한 기와 적 한 기가 교전하는 작은 테스트 맵을 `TestScene`에 만든다. 이후 전투 로직을 실제 게임플레이에서 재사용하고, 타이틀 화면과 게임플레이 사이의 장면 전환을 연결할 수 있도록 구성한다.

1. 메카 이동, 장애물 충돌, 기본적인 앞뒤 가림 표현
2. 카타나·기관단총의 기본 공격과 피격
3. 근접 콤보, 무기 스와핑 후 공격 연계, 대시 공격
4. 적과의 실시간 교전, 전투 종료 및 재시작

세부 범위와 규칙은 사전 PRD를 기준으로 한다. 기획한 기능을 구현 완료 기능으로 표시하지 않는다.

## 저장소 구성

| 경로 | 내용 |
| --- | --- |
| `docs/` | 기획과 제작 도구 사용 문서 |
| `ferrial_drive/` | 재사용 UI·애니메이션 모듈 초안 |
| `samples/ui_unit_test/` | UI 표현 설정과 현재 확인 방법 |
| `data/fonts/` | 지정 공개 폰트와 저작권·이용 조건 |
| `tests/` | 실행기 바로가기와 직접 조작용 샘플 |
| `tests/automated/` | 실행기·시간 진행·버튼 판정 자동 검사 |
| `Tools/unit_test_runner/` | 게임과 독립된 공통 테스트 실행 도구 |
| `samples/unit_test_runner/` | 공통 실행기의 두 화면·흐름 전환 샘플 |
| `Tools/portrait_editor/` | 표정 스튜디오와 영역 지정 도구 |
| `Tools/blender_pipeline/` | Blender 기반 원본 생성 도구 |
| `Tools/SSheetCutil.py` | 기존 스프라이트 시트 편집 도구 |
| `run_portrait_editor.cmd` | 로컬 표정 스튜디오 실행 파일 |

UI Unit Test는 별도 `.py` 진입점으로 실행할 예정이다. 소스 구조와 실행 명령은 구현 후 추가한다.

공통 실행기는 Pico2D가 설치된 Python으로 실행한다. 파일 인자 없이 실행하면 대기 GUI가 열린다. 그 창에 `samples/unit_test_runner/basic_flow.py`를 드롭해 두 화면 샘플을 실행한다. 이 샘플은 위 UI 메뉴·전투 HUD와 별개다.

```text
python Tools/unit_test_runner/run.py
```

바로가기는 `Tools/unit_test_runner/create_launcher.py`로 생성한다. `Tools/unit_test_runner/workspace/Unit Test Runner.lnk`를 열면 같은 GUI가 실행된다. 테스트 파일은 **열린 GUI 창에 드롭**한다. 파일 경로를 인자로 주는 직접 실행도 지원한다. [실행기 안내](Tools/unit_test_runner/README.md)에 사용법을 정리했다.

## 제작 도구 실행 조건

도구별 의존성은 각 폴더의 `requirements.txt`에 있다.
현재 실행 파일은 로컬 `.venv-capability-test` 환경을 사용한다.

**저장소를 복제하는 것만으로 제작 도구를 바로 실행할 수는 없다.**
표정 스튜디오와 Blender 생성기는 로컬 `data/portrait_editor/`의 원본·텍스처·생성 입력을 참조한다. 저장 프로젝트·레이아웃·영역 작업의 기본 위치는 툴 내부 `Tools/portrait_editor/workspace/`다. `output/`에는 재생성 가능한 출력·캐시·검증 결과만 둔다.
스프라이트 시트 도구의 테스트 데이터도 별도로 준비해야 한다.

툴마다 게임과 독립된 최소 시연 데이터를 제공하는 것을 요구사항으로 정했다. 공통 테스트 실행기는 두 화면 샘플을 제공한다. 기존 제작 도구의 샘플·시연 연결은 미구현이며, [툴 시연용 테스트 데이터 기준](docs/tool-usage/tool_demo_data.md)을 따른다.

- [표정 스튜디오](docs/tool-usage/portrait_editor.md)
- [Blender 원본 생성](docs/ai-asset-pipeline/blender_pipeline.md)

## Git 관리 범위

기획 문서와 도구 소스를 관리한다. 다음 항목은 로컬에 보관하며 업로드에서 제외한다.

- Python 가상환경과 캐시
- `data/`의 기존 테스트 이미지와 애니메이션 데이터. 공개 폰트·이용 조건의 지정 경로만 예외로 포함
- `output/`의 생성 이미지·모델·검증 결과와 발표자료 작업본
- `docs/report-archive/`의 과거 실험 기록
- `docs/`의 발표자료 작업 원본. 공개용 `발표자료.pptx`와 `기획서.pptx`는 관리 대상
- 환경변수 파일과 개인 편집기 설정

저작권 이슈를 고려해 **AI 생성 이미지·모델과 이를 가공한 에셋은 업로드하지 않는다.**
문서와 발표자료에 포함된 경우도 공개 대상에서 제외한다.
그 밖의 발표자료와 게임용 에셋은 공개할 파일이 확정되면 별도로 추가한다.

작성 방식과 파일 관리 규칙은 [작업 지침](AGENTS.md)을 따른다.

## 제3자 소스

`Tools/portrait_editor/export_moc3.py`에는 기존 GPL-3.0-or-later 표기가 있다.
참고·수정에 사용한 Ayatsuri2D 소스의 출처와 라이선스는
[`Tools/portrait_editor/vendor/ayatsuri_2d/UPSTREAM.md`](Tools/portrait_editor/vendor/ayatsuri_2d/UPSTREAM.md)에 보관한다.
해당 폴더의 라이선스와 고지 파일을 함께 유지한다.

프로젝트 전체에 적용할 라이선스는 아직 정하지 않았다.

# Ferrial Drive

Python과 Pico2D로 개발할 **2D 실시간 메카 액션 RPG**.
JRPG식 3/4 Top-Down 화면과 사전 렌더링한 2D 에셋을 사용한다.

## 현재 상태

게임 기획과 제작 도구를 정리하는 단계다. 이 저장소에는 기획 문서와 기존 아트 제작 도구가 있으며, 실행 가능한 게임 프로토타입은 아직 없다.

- [사전 PRD](docs/Ferrial_Drive_PRE_PRD_v0.1.md): 게임 방향, 현재 결정한 규칙, 미정 사항
- [문서 목록](docs/README.md): 제작 도구와 데이터 준비 문서

## 첫 프로토타입 목표

임시 에셋으로 메카 한 기와 적 한 기가 교전하는 작은 테스트 맵을 만든다.

1. 메카 이동, 장애물 충돌, 기본적인 앞뒤 가림 표현
2. 카타나·기관단총의 기본 공격과 피격
3. 근접 콤보, 무기 스와핑 후 공격 연계, 대시 공격
4. 적과의 실시간 교전, 전투 종료 및 재시작

세부 범위와 규칙은 사전 PRD를 기준으로 한다. 기획한 기능을 구현 완료 기능으로 표시하지 않는다.

## 저장소 구성

| 경로 | 내용 |
| --- | --- |
| `docs/` | 기획과 제작 도구 사용 문서 |
| `Tools/portrait_editor/` | 표정 스튜디오와 영역 지정 도구 |
| `Tools/blender_pipeline/` | Blender 기반 원본 생성 도구 |
| `Tools/SSheetCutil.py` | 기존 스프라이트 시트 편집 도구 |
| `run_portrait_editor.cmd` | 로컬 표정 스튜디오 실행 파일 |

게임 소스의 폴더 구조와 진입점은 첫 구현 범위가 정해질 때 추가한다.

## 제작 도구 실행 조건

도구별 의존성은 각 폴더의 `requirements.txt`에 있다.
현재 실행 파일은 로컬 `.venv-capability-test` 환경을 사용한다.

**저장소를 복제하는 것만으로 제작 도구를 바로 실행할 수는 없다.**
표정 스튜디오와 Blender 생성기는 로컬 `output/capability_test/`의 이미지·모델·키폼 데이터를 참조한다.
스프라이트 시트 도구의 테스트 데이터도 별도로 준비해야 한다.

- [표정 스튜디오](docs/portrait_editor.md)
- [Blender 원본 생성](docs/blender_pipeline.md)

## Git 관리 범위

기획 문서와 도구 소스를 관리한다. 다음 항목은 로컬에 보관하며 업로드에서 제외한다.

- Python 가상환경과 캐시
- `data/`의 기존 테스트 이미지와 애니메이션 데이터
- `output/`의 생성 이미지·모델·검증 결과와 발표자료 작업본
- `docs/report-archive/`의 과거 실험 기록
- `docs/`의 발표자료 파일
- 환경변수 파일과 개인 편집기 설정

발표자료 최종본과 게임용 에셋은 업로드할 파일이 확정되면 별도로 추가한다.

## 제3자 소스

`Tools/portrait_editor/export_moc3.py`에는 기존 GPL-3.0-or-later 표기가 있다.
참고·수정에 사용한 Ayatsuri2D 소스의 출처와 라이선스는
[`Tools/portrait_editor/vendor/ayatsuri_2d/UPSTREAM.md`](Tools/portrait_editor/vendor/ayatsuri_2d/UPSTREAM.md)에 보관한다.
해당 폴더의 라이선스와 고지 파일을 함께 유지한다.

프로젝트 전체에 적용할 라이선스는 아직 정하지 않았다.

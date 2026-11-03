# 독립 Unit Test 실행기

Runner는 **파일 선택·별도 테스트 실행·종료·상태·오류 표시**를 담당한다. 테스트의 게임 코드·UI·폰트·렌더링 모듈은 Runner GUI 프로세스에 import하지 않는다. GUI에 드롭하면 테스트가 별도 창으로 열린다.

## 실행

Python 3.11 이상과 `requirements.txt`의 Pico2D 1.5.1 환경에서 실행한다.

```text
python Tools/unit_test_runner/run.py
```

열린 **Runner GUI 창**에 테스트 `.py` 하나를 드롭한다. 테스트 창은 파일을 받는 실행기 창과 구분한다. 같은 파일을 다시 드롭하면 이전 테스트를 종료하고 새 프로세스에서 다시 실행한다. UI 모듈·설정 변경은 재드롭으로 반영하는 경로다.

- 테스트 창 X·테스트 자체 종료: 해당 테스트만 종료하고 Runner는 유지한다.
- Runner 창 X: Runner가 시작한 테스트를 종료하고 실행기도 닫는다.
- 여러 파일·없는 파일·구문 오류: 오류를 표시하고 기존 테스트는 유지한다.
- 새 테스트 시작·실행 실패: 종료 코드와 오류 출력 끝부분을 표시하고 다음 드롭을 받는다.

현재 구조 변경을 처음 적용할 때는 기존 Runner를 한 번 완전히 닫고 다시 연다. 이후 UI 테스트 코드를 바꿀 때 Runner 전체를 다시 켤 필요 없이 재드롭하는 구조다. 실제 동작은 사용자 확인 전이다.

파일 인자 실행도 별도 프로세스를 사용한다.

```text
python Tools/unit_test_runner/run.py tests/ui_test.py
python Tools/unit_test_runner/run.py samples/unit_test_runner/basic_flow.py
```

`--frames N`은 제한 프레임 실행용이다. GUI에서는 Runner 프레임을 제한하며, 파일 인자 실행에서는 테스트에 제한값을 전달한다.

## 새 독립 테스트

새 테스트는 일반 Python 프로그램으로 직접 실행할 수 있어야 한다. Runner를 import하거나 TestProgram을 상속하지 않는다. 최상위에 리터럴 메타데이터 `UNIT_TEST_ENTRYPOINT = "standalone"`을 선언하고 `__main__`에서 자체 실행을 시작한다. `--frames`를 쓰려면 해당 인자를 지원한다.

Runner는 소스 구문·메타데이터를 AST로 확인한 뒤 현재 Python 환경으로 파일을 실행한다. 파일 경로는 인자 목록으로 전달하며 shell을 사용하지 않는다. 작업 폴더는 선택 파일의 부모 폴더이므로 데이터·에셋은 파일 위치 기준 경로를 사용한다.

`tests/ui_test.py`가 이 방식이다. `python tests/ui_test.py`는 `Tools/unit_test_runner` 없이 동작하는 코드 경로이며, 자체 Pico2D 루프는 `ferrial_drive/ui/standalone.py`에 있다. 프로젝트 UI 모듈·설정·폰트·Pico2D는 여전히 필요하다. UI 모듈 import만으로 창·루프를 시작하지 않는다.

## 기존 create_test 호환

메타데이터가 없거나 `legacy`인 기존 파일은 새 자식 프로세스의 `worker.py`에서만 읽는다. 기존 `TestProgram`·`WindowSpec`·`Stop`·`SwitchTo`·`create_test()` 규약은 이 경로에서 유지한다. 새 UI 테스트는 이 규약을 사용하지 않는다.

| 기존 요소 | 역할 |
| --- | --- |
| `create_test()` | TestProgram 인스턴스 반환 |
| `WINDOW` | 선택적인 WindowSpec |
| `enter()` | 자식 창 생성 뒤 리소스 준비 |
| `handle_event(event)` | 자식 창의 입력 해석 |
| `update(delta_seconds)` | 초 단위 상태·시간 갱신 |
| `draw()` | 배경부터 테스트 화면 전체 그리기 |
| `exit()` | 정상 종료·장면 교체 시 정리 |

기존 샘플의 SwitchTo는 **자식 테스트 창 안에서** 장면을 바꾼다. Stop과 자식 창 X는 테스트만 종료하며 Runner GUI는 유지한다. 호환 코드는 `interface.py`·`loader.py`·`runner.py`에 두고, GUI는 TestHost나 테스트 렌더러를 사용하지 않는다.

## 다시 실행과 정리

매 실행은 새 프로세스·새 모듈 상태를 사용한다. 바이트코드 캐시도 실행별 탐색 경로로 분리하고 쓰기를 막으므로 예전 보조 모듈 pyc를 재사용하지 않는다. 기존 프로세스 안에서 importlib.reload로 섞어 갱신하지 않는다.

교체·Runner 종료는 소유한 직접 자식 프로세스를 종료하고 기다린다. 필요하면 강제 종료해 운영체제가 자식 창·렌더러·폰트 등 프로세스 자원을 회수한다. **교체·강제 종료에서는 테스트의 Python exit 콜백은 보장하지 않는다.** 저장이 필요한 테스트는 자체 저장·종료 경로를 제공해야 한다. 이 UI 테스트는 샘플 원본을 실행 중 수정하지 않는다.

이 분리는 OS 보안 격리가 아니다. 테스트가 따로 만든 손자 프로세스까지 종료하는 기능은 제공하지 않는다. 자식 stdout/stderr는 GUI 경로에서 임시 파일로 받고 오류 끝부분만 읽어 파이프 대기로 멈추는 문제를 피한다.

## 바로가기와 샘플

기존 바로가기 경로·대상 스크립트는 유지한다. Python 환경이 바뀌거나 바로가기를 새로 만들 때 다음 명령을 사용한다.

```text
python Tools/unit_test_runner/create_launcher.py
```

`Tools/unit_test_runner/workspace/Unit Test Runner.lnk` 또는 기존 `tests/Unit Test Runner.lnk`를 더블클릭하면 드롭 GUI가 열린다. 테스트 파일은 **열린 Runner GUI에** 드롭한다. 생성한 바로가기에는 로컬 Python 경로가 들어가므로 Git에서 제외한다.

- [메뉴·전투 HUD](../../samples/ui_unit_test/README.md): Runner에 의존하지 않는 새 독립 진입점.
- [기존 두 화면 샘플](../../samples/unit_test_runner/README.md): create_test 호환 경로.
- [자동 검사 준비 파일](../../tests/automated/README.md): 실행 경계·교체·캐시·오류 정리 검사.

## 확인 상태

2026-11-03 이번 프로세스 분리 변경은 코드를 읽어 검토했다. 자동 검사·프로그램 실행·렌더링·실제 창 조작은 수행하지 않았다. 준비한 검사 항목의 통과를 주장하지 않으며, 이전 구조의 자동 검사·화면 확인 결과를 이번 구조에 재사용하지 않는다.

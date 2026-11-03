# 독립 Unit Test 실행기

게임과 독립된 Pico2D 도구다. **GUI 창의 파일 드롭·로딩·실행 루프·화면 교체·종료**를 관리한다. 테스트별 UI·샘플 데이터·버튼·단축키·애니메이션은 테스트 파일 또는 해당 재사용 모듈에서 구현한다.

## 실행

Python 3.11 이상과 `requirements.txt`의 Pico2D 1.5.1이 필요하다. 프로젝트 루트의 Zed PowerShell 터미널에서 실행한다.

```powershell
python Tools/unit_test_runner/run.py
```

대기 GUI 창에 테스트 `.py` **하나**를 드롭한다. `samples/unit_test_runner/basic_flow.py`로 두 화면 샘플을 시작할 수 있다. 테스트가 `Stop()`을 반환하면 대기 화면으로 돌아온다. 실행 중 다른 파일을 드롭하면 현재 테스트를 정리하고 새 테스트로 교체한다. 파일 불러오기가 실패하면 현재 테스트를 유지하고 오류를 표시한다. 새 테스트의 초기화·실행이 실패하면 정리 후 대기 화면에서 오류를 표시한다.

Python 환경에 Pico2D가 없다면 먼저 해당 환경에 설치한다.

```powershell
python -m pip install -r Tools/unit_test_runner/requirements.txt
```

기존 로컬 `game2d` 환경에서는 다음 명령으로 실행할 수 있다. 도구와 샘플 코드에는 이 개인 경로를 넣지 않는다.

```powershell
& 'C:\Users\3este\miniconda3\envs\game2d\python.exe' Tools/unit_test_runner/run.py
```

실행기와 테스트 파일을 절대 경로로 지정하면 다른 작업 폴더에서도 실행할 수 있다. 실행기 폴더는 이름 `unit_test_runner`를 유지해 다른 작업 공간에 복사할 수 있다. 게임 패키지·게임 에셋·세이브를 참조하지 않는다.

파일 경로를 인자로 주면 기존처럼 해당 테스트만 직접 실행한다. 이 모드는 테스트의 `Stop()` 또는 창 닫기로 종료한다.

```powershell
python Tools/unit_test_runner/run.py samples/unit_test_runner/basic_flow.py
```

자동 실행 확인에는 `--frames 5`처럼 최대 프레임 수를 지정한다. GUI 모드의 기본 실행은 창을 닫을 때까지 유지된다.

## GUI 실행 바로가기

Pico2D가 설치된 Python 환경에서 한 번 실행해 Windows 바로가기를 생성한다.

```powershell
python Tools/unit_test_runner/create_launcher.py
```

생성 위치는 `Tools/unit_test_runner/workspace/Unit Test Runner.lnk`다. 바로가기를 더블클릭하면 GUI가 열린다. **테스트 파일은 열린 Python GUI 창에 드롭한다.** GUI와 인자 실행은 같은 `load_test()` 규약을 사용한다.

바로가기는 생성에 사용한 Python 실행 파일을 기억한다. 현재 작업 폴더나 `.py` 기본 연결 프로그램에 의존하지 않는다. 한글·공백·특수문자가 있는 경로도 인자로 전달한다. 다른 PC나 폴더로 도구·Python 환경을 옮기면 그 환경에서 바로가기를 다시 생성한다.

GUI의 파일·실행 오류는 창에 표시하며 다시 드롭해 진행할 수 있다. 바로가기 실행 자체가 실패하거나 파일 인자 직접 실행에서 오류가 발생하면 콘솔에 내용을 표시하고 Enter를 기다린다.

개인 Python 경로가 들어가는 `.lnk`는 로컬 `workspace/`에만 생성하며 Git 관리에서 제외한다. 바로가기 생성에는 Windows 기본 `WScript.Shell`을 사용한다. [Microsoft 공식 생성 방식](https://learn.microsoft.com/en-us/troubleshoot/windows-client/admin-development/create-desktop-shortcut-with-wsh)을 따른다.

## 테스트 .py의 규약

| 요소 | 역할 |
| --- | --- |
| `create_test()` | 최초 `TestProgram` 인스턴스를 반환하는 필수 함수 |
| `WINDOW` | 선택적인 `WindowSpec`. 기본 1280×720·60 FPS 상한 |
| `enter()` | 창이 열린 뒤 리소스 준비 |
| `handle_event(event)` | 원본 Pico2D 입력 해석. 필요하면 흐름 요청 반환 |
| `update(delta_seconds)` | 초 단위 시간 갱신. 필요하면 흐름 요청 반환 |
| `draw()` | 배경 지우기부터 화면 전체 그리기. 유일한 필수 구현 메서드 |
| `exit()` | 화면 교체·실행 종료 때 리소스 정리 |

공통 타입은 `unit_test_runner`에서 import한다. `enter` 등은 필요한 것만 재정의한다. 테스트 모듈을 읽거나 `create_test()`를 호출할 때에는 창 생성·게임 루프·폰트 로드를 시작하지 않는다. 창이 필요한 준비는 `enter()`에서 수행한다. 테스트의 추가 데이터·에셋 경로는 각 테스트 파일 위치를 기준으로 해석한다. 보조 모듈은 테스트 파일의 최상위 import에서 연결할 수 있다.

## 흐름 전환

- `None`: 현재 화면을 계속 실행한다.
- `SwitchTo(next_program)`: 현재 화면의 `exit()` 후 다음 인스턴스의 `enter()`를 호출한다. 창은 유지한다.
- `Stop()`: 현재 테스트를 정리한다. 직접 실행 모드는 창을 닫고, GUI 모드는 대기 화면으로 돌아간다.

흐름 요청은 입력·갱신 콜백이 반환한 직후 적용한다. 같은 프레임의 남은 입력은 새 화면에 전달한다. 갱신에서 교체하면 새 화면을 바로 그리며, 새 화면의 첫 갱신은 다음 프레임에 수행한다. 창의 X는 실행기가 종료 처리한다. 나머지 키와 클릭의 의미는 테스트가 정한다.

화면 전환은 즉시 교체다. 이동·페이드·전환 중 입력 처리 같은 표현과 정책은 각 테스트에서 구현한 뒤 교체 시점에 요청을 반환한다. 테스트 내부 전환에서는 창 규격을 유지한다. GUI에서 새 파일을 드롭하면 그 파일의 `WINDOW`에 맞춰 같은 창의 크기를 조정한다.

## 정리와 오류

직접 실행 중 오류는 호출자에게 전달하되 현재 테스트의 `exit()`를 실행하고 창을 닫는다. GUI 모드는 오류를 표시하고 다음 드롭을 기다린다. `enter()` 도중 실패해도 `exit()`가 호출되므로, 테스트는 아직 준비되지 않은 리소스도 안전하게 처리해야 한다. 같은 활성 상태에 대한 정리는 한 번만 호출한다.

GUI의 드롭 입력은 실행기가 소비한다. Pico2D 원본은 수정하지 않고 실행기의 SDL 이벤트 어댑터에서 일반 입력과 파일 드롭을 전달한다. 드롭 파일명 메모리는 [SDL_DropEvent 규약](https://wiki.libsdl.org/SDL2/SDL_DropEvent)에 따라 해제한다.

## 샘플과 확인 범위

- [두 화면 샘플](../../samples/unit_test_runner/README.md): Esc·마우스 버튼 전환, 화면별 경과 시간, 종료.
- 자동 검사는 프로젝트 루트에서 `python -m unittest discover -s tests -v`로 실행한다. 창을 대체하는 검사와 실제 창·조작 확인을 구분한다.
- 게임 UI의 메뉴·HUD 구현 완료 여부는 [UI Unit Test 명세](../../docs/unit-tests/ui_unit_test.md)를 따른다. 이 도구의 두 화면 샘플과 별개다.

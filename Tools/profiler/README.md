# 성능 프로파일러 — FDrive Profiler

기존 [py-spy](https://github.com/benfred/py-spy)로 게임·독립 테스트의 Python 호출 스택을 수집한다. 게임 코드에 계측 코드를 넣지 않는다. 기록은 `output/performance/`의 새 폴더에 저장하며 기존 결과를 덮어쓰지 않는다.

## 설치

프로젝트 루트에서 실제 Python 인터프리터로 실행한다. 아래 `python`은 작업에 사용할 Python이다. 전투 테스트에는 Pico2D가 설치된 Python을 사용한다. 프로파일러 자체와 요약 처리는 표준 라이브러리만 사용한다.

```text
python -m pip download --only-binary=:all: --no-deps --dest automate/packages/profiler -r automate/requirements-profiler.txt
python -m pip install --no-index --find-links automate/packages/profiler --no-deps --target automate/runtime/profiler/python -r automate/requirements-profiler.txt
```

실행 파일은 명시한 `--py-spy` 경로 → `automate/runtime/profiler/python/bin/` → PATH 순서로 찾는다. 설치 패키지와 런타임은 기존 Git 제외 규칙에 포함된다. py-spy는 MIT License이며 설치 wheel의 라이선스·고지를 유지한다. 게임의 기본 의존성에는 추가하지 않는다.

## 실행 중인 게임에 연결

```text
python Tools/profiler/run.py record --pid 12345 --duration 30
```

`12345`를 실제 Python 프로세스 PID로 바꾼다. 측정 종료 후 게임은 계속 실행된다. Runner를 측정할 때는 Runner GUI가 아니라 실제 테스트 프로세스에 연결한다. Windows 가상환경의 실행 중개 프로세스 PID를 선택했다면 `--subprocesses`로 실제 Python 자식도 수집한다.

## 파일 실행과 함께 수집

```text
python Tools/profiler/run.py record --target tests/combat_test.py --duration 30
python Tools/profiler/run.py record --python path/to/python.exe --target tests/ui_test.py --duration 30 -- --frames 600
```

`--` 뒤는 대상 프로그램의 인자다. `--python`을 생략하면 프로파일러를 실행한 Python을 사용한다. 파일·출력·작업 폴더의 상대 경로는 프로젝트 루트 기준이며 대상 인자 안의 상대 경로는 `--cwd` 기준이다.

새 실행은 자식 수집을 기본으로 켠다. py-spy는 측정 종료 시 자신이 직접 시작한 프로세스를 중지한다. 자식 프로세스 트리 전체의 종료나 대상 프로그램의 정상 정리·저장은 보장하지 않는다. 계속 조작하거나 종료 시 저장하는 게임은 PID 연결을 사용한다. 프레임 제한으로 정상 종료를 확인하려면 측정 시간을 충분히 길게 지정하고 대상의 정상 종료 결과도 확인한다. `session.status=complete`는 수집·요약 완료를 뜻하며 대상 프로그램의 성공 종료 판정이 아니다.

## 결과 열기

| 파일 | 용도 |
| --- | --- |
| `profile.speedscope.json` | py-spy가 생성한 원본 스택·가중치·스레드/프로세스 정보 |
| `summary.json` | AI 분석용 함수별 자체/하위 포함 비중, 전체 호출 경로, 파일·줄 번호 |
| `session.json` | 실행 명령·작업 폴더·시각·대상 파일 해시·수집 조건·완료/실패 |
| `collector.log` | py-spy와 대상 프로그램의 출력·수집 오류 |

[Speedscope](https://www.speedscope.app/)에서 `profile.speedscope.json`을 열고 **Left Heavy**를 선택한다. 경로 확대·검색과 호출자/하위 호출은 뷰어의 기존 기능을 사용한다. [공식 안내](https://github.com/jlfwong/speedscope#usage)에 따르면 파일은 브라우저 안에서 처리되며 서버로 업로드되지 않는다. 오프라인 뷰어 설치도 공식 안내를 따른다. 자체 뷰어·전용 GUI·자동 브라우저 실행은 이번 범위에 포함하지 않는다.

AI에게는 같은 폴더의 원본·요약·실행 조건·로그와 함께 재현한 장면·입력·기대 동작을 전달한다. `summary.json`의 호출 경로는 원본 `frames` 인덱스의 루트→말단 순서다. 함수 목록은 자체 가중치 우선이다. 재귀는 경로에 보존하지만 한 샘플 안의 같은 프레임은 포함 비중에서 한 번만 센다.

## 해석과 한계

- 기본은 초당 100회 수집이며 대기 스레드는 제외한다. `--rate`와 `--include-idle`로 조건을 바꾸고 비교 시 일치시킨다. 샘플에 나타나지 않은 짧은 호출이 존재할 수 있다.
- 샘플 수는 함수 호출 횟수가 아니며 가중치·비중은 정확한 함수 실행 시간이나 CPU 사용률이 아니다. 스레드별 비중은 각 스레드의 수집된 가중치가 분모다. 하위 포함 비중을 서로 합산하지 않는다.
- py-spy의 Speedscope 출력은 샘플당 명목 수집 간격을 가중치로 쓴다. 누락·대기·필터링이 반영된 실제 프레임 시간축이나 정확한 수집 시각으로 해석하지 않는다. CPU/GPU 그래프와 구간 선택을 동기화하는 타임라인 연결은 별도 작업이다.
- 이번 연결은 Python 스택만 수집한다. CPU·GPU 사용률, GPU 실행시간, 네이티브 내부 스택, 프레임별 시간 원본은 수집하지 않는다. 기존 [TimingRecorder](../../docs/tool-usage/performance_timing.md)의 선택적 구간 계측은 별도로 사용할 수 있다.
- `collector_elapsed_ns`는 수집 프로세스의 시작·종료까지 포함한 경과 시간이며 계측 오버헤드가 아니다. `postprocess_elapsed_ns`는 수집 후 JSON 요약·저장 시간이다. 실제 수집 오버헤드는 미측정이고 시간 차감 보정은 적용하지 않는다.
- 스택이 없거나 수집이 실패하면 실패 상태와 로그를 남긴다. 샘플 0개를 성공으로 처리하지 않는다. 접근 제한·지원하지 않는 Python 실행 환경은 수집 로그에서 확인한다.

## 독립 시연과 검증

[게임 없는 시연](../../samples/profiler/README.md)은 정수 계산과 대기만 사용한다. 게임 에셋·Pico2D·Unreal·세이브가 필요 없다.

2026-11-11 확인: 프로파일러 자동 검사 9개와 기존 구간 타이머 검사 7개 통과. Windows/Python 3.13 독립 시연 296샘플 수집과 PID 연결 종료 후 대상 생존을 확인했다. Python 3.11/Pico2D 전투 테스트는 SDL dummy에서 180프레임 정상 종료·273샘플/수집 오류 0개·기존 시간 로그 저장을 확인했고 원본이 Speedscope에서 열렸다. 전투 테스트는 초기 대기/렌더링 경로이며 직접 전투 조작·실제 GPU 렌더 성능·오버헤드 비교·최종 사용성은 미검증이다. 검증 이력은 [개발 기록](../../docs/ai-dev-log/2026-11-11-performance-profiler.md)에 남긴다.

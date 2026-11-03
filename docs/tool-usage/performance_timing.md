# 공통 성능 계측

## 목적과 범위

게임·유닛 테스트·성능 모니터링에서 필요한 때만 함수와 코드 구간을 측정하고, 개발자와 AI가 병목을 분석할 JSON 로그를 남긴다. 구현은 `ferrial_drive/diagnostics/timing.py`의 `TimingRecorder`이며 Python 3.11 표준 라이브러리만 사용한다. UI·Pico2D·Runner를 import하거나 창·실행 루프를 생성하지 않는다.

기본은 비활성이다. 비활성 `wrap()`은 원함수를 그대로 반환하고, `scope()`는 타이머를 읽지 않는다. 비활성 `benchmark()`는 대상 작업을 실행하지 않으며 `write_json()`도 폴더·파일을 만들지 않는다. 활성 여부는 레코더 생성 시 선택한다.

## 함수·구간 계측

게임이나 테스트의 연결부에서 레코더를 만들고 측정할 호출만 감싼다. 원함수의 반환값과 예외는 유지하며 예외로 끝난 호출도 횟수와 시간에 포함한다.

```python
from ferrial_drive.diagnostics import TimingRecorder

timings = TimingRecorder(enabled=monitoring_enabled, session="combat")
update = timings.wrap(update, name="combat.update")

with timings.scope("combat.step"):
    update(delta_seconds)

# 측정 구간 밖의 명시적인 저장 시점에 호출한다.
timings.write_json("output/performance/combat.json")
```

- 함수 전체는 `wrap(function, name=...)`, 코드 일부는 `scope(name)`로 지정한다. `wrap()`은 동기 함수만 지원한다. 비동기·제너레이터는 함수 호출과 실제 작업 실행 시점이 다르므로 실행할 코드 안에 구간을 직접 지정한다.
- 이름별 호출 수·실패 수·누적/평균/최소/최대 경과 시간을 기록한다. 실패 수는 예외로 끝난 호출 수다. 매 호출의 원시 샘플 배열은 보관하지 않는다. 이름은 `renderer.ring`처럼 고정해서 사용하며 객체 ID·타임스탬프를 이름에 넣지 않는다.
- 스레드가 같은 레코더를 공유해도 집계와 스냅샷을 잠금으로 보호한다. 완료된 호출만 스냅샷에 들어간다. 실행 중인 구간의 부분 시간은 포함하지 않는다.
- 시간은 `perf_counter_ns()` 기반의 **하위 호출·대기를 포함한 경과 시간**이다. 부모 구간은 자식 계측·집계 비용도 포함하므로 중첩된 여러 행의 시간을 합해 프레임 시간으로 해석하지 않는다.
- 계측 자체에도 비용이 있다. 작은 함수의 호출 횟수와 넓은 구간의 누적 시간을 함께 보고, 실제 성능 수치를 비교할 때 계측 조건을 맞춘다.

## 반복 측정

```python
timings.benchmark(
    "operation.warm", operation,
    iterations=1000, repeat=5, warmup=20,
    prepare=reset_sample_state,
)
timings.write_json("output/performance/operation.json")
```

각 회차는 `prepare()` → warmup회 예열 → iterations회 측정 순서다. 준비와 예열은 측정 시간에서 제외한다. `prepare`는 선택 사항이며 상태를 바꾸는 작업을 반복할 때 회차별 초기 상태를 맞추는 용도다. 예열 뒤 상태도 바뀐다는 점을 고려한다. 캐시의 최초 실행을 재려면 예열을 0으로 두고 준비 작업에서 해당 캐시를 비운다. 예열 후의 비용과 최초 실행 비용을 구분한다.

반복 측정에는 래핑 전의 원함수를 전달한다. 계측 래퍼를 씌운 함수를 넘기면 래퍼·집계 비용도 반복 시간에 포함된다.

`timeit.Timer`로 회차별 총시간을 기록한다. `mean_ns_per_call`은 전체 측정 시간/호출 수이며, `median_batch_mean_ns`·`min_batch_mean_ns`·`max_batch_mean_ns`는 회차별 평균 함수당 시간의 요약이다. 개별 호출의 최소·최대 시간을 측정한 값은 아니다. 총 측정 호출 수는 iterations×repeat이며 예열 호출 수는 warmup×repeat다. 반복 회차 결과는 같은 이름으로 다시 측정하면 최신 결과로 교체한다.

반복 측정은 timeit 기본 정책에 따라 측정 루프에서 GC를 비활성화한다. 일반 구간 계측은 GC를 변경하지 않는다. GC 비용이 포함된 실제 실행과 반복 벤치마크를 같은 조건으로 단정하지 않는다. 대상 함수가 실패하면 예외를 전달하며 해당 벤치마크 결과는 저장하지 않는다.

반복 벤치마크는 별도 테스트 실행에서 단일 스레드로 수행한다. 일반 계측의 스레드 안전 집계가 반복 작업의 실행 환경까지 격리해 주는 것은 아니다.

## UI 테스트에 선택적으로 연결

기존 Runner 드롭·직접 실행은 계측 비활성이다. 직접 실행 시에만 다음 옵션을 추가한다.

```text
python tests/ui_test.py --profile
python tests/ui_test.py --profile output/performance/ui-comparison.json --frames 300
```

첫 명령은 UTC 시각이 붙은 `output/performance/ui-...Z.json`을 사용한다. 두 번째처럼 경로를 지정하면 비교할 파일을 정할 수 있다. 상대 경로는 실행한 작업 폴더 기준이다. 기본 실행과 승인된 설정·배치·효과 값은 유지하며 프레임별 계측 호출은 활성 실행에서만 추가한다.

- enter·입력·update·draw, 장면/피해/카운터/HP 갱신, 메뉴·HUD·일시정지·레이더·카운터 그리기, 링·텍스트·글자 측정·텍스처 조회를 집계한다. enter는 렌더러·글꼴 준비 구간이며 프로그램 생성 전 전체 시작 시간을 뜻하지 않는다. 실제 호출된 항목만 로그에 있다. 표시하지 않은 화면의 비용이 0이라고 단정하지 않는다.
- `loop.present`는 화면 표시 호출, `loop.frame_wait`는 프레임 제한을 위한 대기다. 대기가 가장 큰 행으로 나와도 계산 병목으로 해석하지 않는다. `ui.draw`는 화면 표시 호출을 포함하지 않는다.
- 메뉴에서 조작하지 않고 프레임 제한만 걸면 메뉴 위주로 수집된다. 전투 비용을 보려면 HUD에 진입해 피해·카운터·일시정지 등 해당 동작을 수행한다.
- UI 창 종료·테스트 종료·정상 프레임 제한 종료 시 `exit()`에서 저장한다. Runner 재드롭·강제 종료·프로세스 종료에서는 저장을 보장하지 않는다. 수집을 마친 뒤 정상 종료하거나 프레임 제한을 사용한다.

## 로그와 해석

JSON의 `schema_version`은 1이다. `session`·UTC 시작/저장 시각·Python 버전·시계 구현/해상도·`measurements`·`benchmarks`를 포함한다. 구간 행은 누적 시간이 큰 순으로 정렬한다. 값은 ns 단위이며, 나노초 단위 기록이 실제 1ns 정확도를 뜻하지 않는다. 시계 해상도도 함께 확인한다.

`time_semantics=inclusive_wall`, `gpu_time_measured=false`를 명시한다. 이 모듈은 Python 측 경과 시간을 기록한다. OpenGL의 GPU 실행시간을 직접 측정하는 기능은 별도다.

측정 호출 안에서는 출력하거나 파일을 쓰지 않는다. `write_json()`을 호출할 때 스냅샷을 만들고 같은 폴더의 임시 파일을 완성한 뒤 대상 파일로 교체한다. 같은 경로는 새 결과로 덮어쓰므로 변경 전후 비교는 파일명을 나눈다. 로그는 기존 제외 규칙에 맞춰 `output/performance/`에 둔다. 레코더는 자동 종료 처리·백그라운드 저장·업로드를 수행하지 않는다. 장기 모니터링은 연결부가 안전한 시점에 스냅샷을 저장한다.

## 예제와 확인 상태

- [게임 없이 실행하는 최소 예제](../../samples/performance_timing/README.md): 정수 데이터로 호출 집계·반복 수·JSON 구조 확인.
- `tests/automated/test_timing.py`: 비활성 무동작, 중첩 시간, 반환/예외 유지, 예열 제외와 반복 수, 비동기 오측정 방지, 스레드 집계, 저장 실패 시 이전 로그 보존 계약을 준비했다.
- 이번 구현에서 자동 검사·예제 실행·UI 실행·성능 실측은 수행하지 않았다. 준비한 검사 파일과 사용법을 실행 성공 결과로 표시하지 않는다.

참고: [Python 3.11 시간 함수](https://docs.python.org/3.11/library/time.html#time.perf_counter_ns), [timeit](https://docs.python.org/3.11/library/timeit.html), [전체 함수 탐색용 cProfile](https://docs.python.org/3.11/library/profile.html).

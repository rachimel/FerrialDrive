# 성능 계측 최소 예제

Python 3.11 표준 라이브러리만 사용한다. 게임·Pico2D·폰트·Runner가 필요 없고 창을 열지 않는다. 기본 정수 데이터의 제곱 합을 대상으로 함수·구간 집계와 반복 측정 결과를 JSON으로 저장한다.

프로젝트 루트에서 실행한다.

```text
python samples/performance_timing/basic_timing.py --iterations 1000 --repeat 5 --warmup 10
```

기본 출력은 `output/performance/timing_sample.json`이다. `--output`으로 다른 파일을 지정하면 비교용 로그를 남길 수 있다. 기존 파일 경로를 다시 지정하면 새 결과로 교체한다. 샘플 원본은 수정하지 않는다.

- `measurements`에는 `sample.batch` 1회·`sample.calculate` 10회가 있어야 한다. 외부 구간은 내부 측정·집계 비용도 포함하므로 두 행의 시간을 합하지 않는다.
- `benchmarks`에는 `sample.repeat`가 있다. 전체 예열 호출 수는 warmup×repeat, 실제 측정 호출 수는 iterations×repeat다. 예열과 prepare는 반복 측정 시간에서 제외한다.
- 위 기본값의 실제 측정 호출 수는 5,000회, 예열은 50회다. `samples_total_ns`는 회차별 총 경과 시간이며 함수당 시간은 각 회차 값을 iterations로 나눠 계산한다.
- 반복 측정은 timeit 기본 정책에 따라 측정 루프 동안 GC를 비활성화한다. 실제 실행 구간 계측은 GC를 바꾸지 않는다. 두 결과를 같은 실행 조건의 값으로 단정하지 않는다.

구조·로그 해석과 UI 연결은 [공통 계측 안내](../../docs/tool-usage/performance_timing.md)를 따른다. 샘플·자동 검사 파일은 준비했으며 이번 구현에서 실행·실측은 수행하지 않았다.

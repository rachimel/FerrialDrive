# 성능 프로파일러 독립 시연

`workload.py`는 `update`·`draw` 아래에서 같은 정수 계산을 호출하고 짧게 대기한다. 게임 원본·세이브·이미지·Pico2D·DCC 프로그램이 필요 없다. 원본은 수정하지 않으며 결과는 별도 `output/performance/`에 저장한다.

Python 3.11 이상과 [프로파일러 설치](../../Tools/profiler/README.md#설치)가 필요하다. 프로젝트 루트에서 실행한다.

```text
python Tools/profiler/run.py record --target samples/profiler/workload.py --duration 6 -- --seconds 4
```

확인할 결과:

- 새 결과 폴더에 `profile.speedscope.json`, `summary.json`, `session.json`, `collector.log`가 생성된다.
- `session.json`의 `status`는 `complete`, `total_samples`는 양수다. 실제 샘플 수는 실행 환경에 따라 달라진다.
- [Speedscope](https://www.speedscope.app/)에 원본을 열고 Left Heavy를 선택하면 `update`/`draw`→`calculate` 호출 경로가 보인다. 짧은 호출은 샘플에 잡히지 않을 수 있다.
- 요약에는 함수·파일·줄 번호·자체/포함 가중치와 호출 경로가 있다. `--include-idle`을 추가하면 대기 스택을 포함하므로 기본 실행과 비중이 달라질 수 있다.

2026-11-11 Windows/Python 3.13에서 실제 시연 수집 296샘플과 요약 생성을 확인했다. 실행 중인 별도 샘플에 2초 동안 PID 연결 후 대상이 살아 있는 것도 확인했다. 사용법·측정 의미는 [성능 프로파일러](../../Tools/profiler/README.md)를 따른다.

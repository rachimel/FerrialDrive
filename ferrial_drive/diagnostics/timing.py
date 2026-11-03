"""선택한 함수·구간 시간과 반복 측정을 집계하고 요청 시 JSON 로그로 저장한다."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
import os
from pathlib import Path
from statistics import median
import sys
import tempfile
from threading import Lock
from time import get_clock_info, perf_counter_ns
from timeit import Timer


_NOOP_SCOPE = nullcontext()


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("측정 이름은 비어 있지 않은 문자열이어야 한다.")
    return value


def _iterations(value, *, allow_zero=False):
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"반복 횟수는 {minimum} 이상의 정수여야 한다.")
    return value


def _sync_callable(function):
    if not callable(function):
        raise TypeError("측정 대상은 호출 가능한 함수여야 한다.")
    for target in (function, getattr(function, "__call__", None)):
        if (inspect.iscoroutinefunction(target) or inspect.isgeneratorfunction(target)
                or inspect.isasyncgenfunction(target)):
            raise TypeError("비동기·제너레이터 대상은 실행할 코드 안에 scope를 직접 배치한다.")


@dataclass
class _TimingStats:
    calls: int = 0
    failures: int = 0
    total_ns: int = 0
    min_ns: int | None = None
    max_ns: int = 0

    def add(self, elapsed_ns, failed):
        self.calls += 1
        self.failures += int(failed)
        self.total_ns += elapsed_ns
        self.min_ns = elapsed_ns if self.min_ns is None else min(self.min_ns, elapsed_ns)
        self.max_ns = max(self.max_ns, elapsed_ns)

    def report(self, name):
        return {"name": name, "calls": self.calls, "failures": self.failures,
                "total_ns": self.total_ns, "mean_ns": self.total_ns / self.calls,
                "min_ns": self.min_ns, "max_ns": self.max_ns}


class _TimedScope:
    def __init__(self, recorder, name):
        self.recorder = recorder
        self.name = name

    def __enter__(self):
        self.started_ns = perf_counter_ns()
        return self

    def __exit__(self, error_type, error, traceback):
        elapsed_ns = perf_counter_ns() - self.started_ns
        self.recorder._record(self.name, elapsed_ns, error_type is not None)
        return False


class TimingRecorder:
    """구간 시간은 하위 호출·대기를 포함한다. 중첩 구간의 합은 프레임 시간이 아니다."""

    def __init__(self, *, enabled=False, session="default"):
        if not isinstance(enabled, bool):
            raise TypeError("계측 활성 여부는 bool 값이어야 한다.")
        self._enabled = enabled
        self.session = _name(session)
        self.started_at_utc = _timestamp()
        self._measurements = {}
        self._benchmarks = {}
        self._lock = Lock()

    @property
    def enabled(self):
        return self._enabled

    def scope(self, name):
        if not self.enabled:
            return _NOOP_SCOPE
        return _TimedScope(self, _name(name))

    def wrap(self, function, *, name=None):
        """비활성 상태에서는 원함수를 그대로 반환한다. 동기 함수만 계측한다."""
        if not callable(function):
            raise TypeError("측정 대상은 호출 가능한 함수여야 한다.")
        if not self.enabled:
            return function
        _sync_callable(function)
        label = _name(name if name is not None else getattr(function, "__qualname__", type(function).__name__))

        @wraps(function)
        def measured(*args, **kwargs):
            with self.scope(label):
                return function(*args, **kwargs)

        return measured

    def _record(self, name, elapsed_ns, failed):
        with self._lock:
            stats = self._measurements.get(name)
            if stats is None:
                stats = self._measurements[name] = _TimingStats()
            stats.add(elapsed_ns, failed)

    def benchmark(self, name, function, *, iterations, repeat=5, warmup=0, prepare=None):
        """매 회차 준비·예열을 제외하고 timeit으로 반복한다. 비활성이면 실행하지 않는다."""
        if not self.enabled:
            return None
        label = _name(name)
        _iterations(iterations)
        _iterations(repeat)
        _iterations(warmup, allow_zero=True)
        _sync_callable(function)
        if prepare is not None:
            _sync_callable(prepare)
        timer = Timer(function, timer=perf_counter_ns)
        samples = []
        for _ in range(repeat):
            if prepare is not None:
                prepare()
            for _ in range(warmup):
                function()
            samples.append(int(timer.timeit(number=iterations)))
        result = {"name": label, "iterations": iterations, "repeat": repeat,
                  "warmup_per_repeat": warmup, "measured_calls": iterations * repeat,
                  "warmup_calls": warmup * repeat, "samples_total_ns": samples,
                  "mean_ns_per_call": sum(samples) / (iterations * repeat),
                  "median_batch_mean_ns": median(samples) / iterations,
                  "min_batch_mean_ns": min(samples) / iterations,
                  "max_batch_mean_ns": max(samples) / iterations,
                  "gc_policy": "timeit_default_disabled_during_timed_loop"}
        with self._lock:
            self._benchmarks[label] = result
        return deepcopy(result)

    def snapshot(self):
        with self._lock:
            measurements = [stats.report(name) for name, stats in self._measurements.items()]
            benchmarks = deepcopy(list(self._benchmarks.values()))
        measurements.sort(key=lambda row: (-row["total_ns"], row["name"]))
        benchmarks.sort(key=lambda row: row["name"])
        clock = get_clock_info("perf_counter")
        return {"schema_version": 1, "session": self.session, "enabled": self.enabled,
                "started_at_utc": self.started_at_utc, "saved_at_utc": _timestamp(),
                "python_version": sys.version.split()[0], "unit": "nanoseconds",
                "time_semantics": "inclusive_wall", "gpu_time_measured": False,
                "clock": {"name": "perf_counter_ns", "implementation": clock.implementation,
                          "resolution_seconds": clock.resolution, "monotonic": clock.monotonic},
                "measurements": measurements, "benchmarks": benchmarks}

    def write_json(self, path):
        """기록 중에는 쓰지 않고 명시적인 호출 시 임시 파일을 거쳐 저장한다."""
        if not self.enabled:
            return None
        report = self.snapshot()
        destination = Path(path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                             prefix=f".{destination.name}.", suffix=".tmp",
                                             delete=False) as output:
                temporary_path = Path(output.name)
                json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.write("\n")
            os.replace(temporary_path, destination)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return destination

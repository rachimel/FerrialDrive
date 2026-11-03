"""선택적 계측의 무동작·중첩·예외·반복 수·로그 저장 계약. 실행 여부와 구분한다."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ferrial_drive.diagnostics import TimingRecorder


class TimingTests(unittest.TestCase):
    def measurements(self, recorder):
        return {row["name"]: row for row in recorder.snapshot()["measurements"]}

    def test_disabled_recorder_returns_original_and_does_not_time_run_bench_or_write(self):
        recorder = TimingRecorder()
        function = lambda: 7
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "unused" / "result.json"
            with patch("ferrial_drive.diagnostics.timing.perf_counter_ns") as clock:
                self.assertIs(recorder.wrap(function), function)
                with recorder.scope("unused"):
                    self.assertEqual(function(), 7)
                self.assertIsNone(recorder.benchmark("unused", function, iterations=10))
                self.assertIsNone(recorder.write_json(destination))
                clock.assert_not_called()
            self.assertFalse(destination.parent.exists())
        self.assertEqual(self.measurements(recorder), {})

    def test_nested_scopes_keep_inclusive_time_without_merging_child_into_parent_twice(self):
        recorder = TimingRecorder(enabled=True)
        with patch("ferrial_drive.diagnostics.timing.perf_counter_ns", side_effect=[100, 120, 160, 200]):
            with recorder.scope("outer"):
                with recorder.scope("inner"):
                    pass
        rows = self.measurements(recorder)
        self.assertEqual(rows["outer"]["total_ns"], 100)
        self.assertEqual(rows["inner"]["total_ns"], 40)
        self.assertEqual(rows["outer"]["calls"], 1)
        self.assertEqual(recorder.snapshot()["time_semantics"], "inclusive_wall")

    def test_wrapped_function_keeps_result_metadata_and_records_failure_without_swallowing_it(self):
        recorder = TimingRecorder(enabled=True)

        def calculate(value):
            if value < 0:
                raise ValueError("negative")
            return value * 2

        wrapped = recorder.wrap(calculate, name="calculate")
        with patch("ferrial_drive.diagnostics.timing.perf_counter_ns", side_effect=[0, 20, 30, 70]):
            self.assertEqual(wrapped(3), 6)
            with self.assertRaisesRegex(ValueError, "negative"):
                wrapped(-1)
        row = self.measurements(recorder)["calculate"]
        self.assertEqual(wrapped.__name__, calculate.__name__)
        self.assertEqual((row["calls"], row["failures"], row["total_ns"]), (2, 1, 60))
        self.assertEqual((row["min_ns"], row["max_ns"], row["mean_ns"]), (20, 40, 30))

    def test_benchmark_excludes_prepare_and_warmup_and_reports_actual_iteration_counts(self):
        recorder = TimingRecorder(enabled=True)
        events = []
        with patch("ferrial_drive.diagnostics.timing.perf_counter_ns", side_effect=[0, 80, 100, 220]):
            result = recorder.benchmark("repeat", lambda: events.append("work"), iterations=2,
                                        repeat=2, warmup=1, prepare=lambda: events.append("prepare"))
        self.assertEqual(events, ["prepare", "work", "work", "work"] * 2)
        self.assertEqual(result["samples_total_ns"], [80, 120])
        self.assertEqual((result["measured_calls"], result["warmup_calls"]), (4, 2))
        self.assertEqual(result["mean_ns_per_call"], 50)
        self.assertEqual((result["min_batch_mean_ns"], result["max_batch_mean_ns"]), (40, 60))
        result["samples_total_ns"].clear()
        self.assertEqual(recorder.snapshot()["benchmarks"][0]["samples_total_ns"], [80, 120])

    def test_invalid_counts_and_async_or_generator_functions_are_rejected_before_execution(self):
        recorder = TimingRecorder(enabled=True)
        for count in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                recorder.benchmark("invalid", lambda: None, iterations=count)

        async def coroutine():
            return 1

        def generator():
            yield 1

        class AsyncCallable:
            async def __call__(self):
                return 1

        for function in (coroutine, generator, AsyncCallable()):
            with self.assertRaises(TypeError):
                recorder.wrap(function)
            with self.assertRaises(TypeError):
                recorder.benchmark("invalid", function, iterations=1)

    def test_shared_recorder_keeps_completed_call_count_across_threads(self):
        recorder = TimingRecorder(enabled=True)

        def work(_):
            with recorder.scope("work"):
                pass

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(work, range(100)))
        self.assertEqual(self.measurements(recorder)["work"]["calls"], 100)

    def test_json_is_machine_readable_and_failed_replace_preserves_previous_report(self):
        recorder = TimingRecorder(enabled=True, session="한글 세션")
        with recorder.scope("work"):
            pass
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "result.json"
            recorder.write_json(destination)
            previous = destination.read_bytes()
            report = json.loads(previous)
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["session"], "한글 세션")
            self.assertFalse(report["gpu_time_measured"])
            self.assertEqual(report["measurements"][0]["calls"], 1)
            with patch("ferrial_drive.diagnostics.timing.os.replace", side_effect=PermissionError):
                with self.assertRaises(PermissionError):
                    recorder.write_json(destination)
            self.assertEqual(destination.read_bytes(), previous)
            self.assertEqual(list(Path(directory).iterdir()), [destination])


if __name__ == "__main__":
    unittest.main()

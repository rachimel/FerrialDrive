"""스택 샘플 해석과 외부 수집의 실패·출력 보존 계약을 확인한다."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ferrial_drive.diagnostics.profiler import record_profile, summarize_speedscope


ROOT = Path(__file__).resolve().parents[2]


def profile_document():
    return {"exporter": "py-spy@test", "shared": {"frames": [
        {"name": "main", "file": "demo.py", "line": 1},
        {"name": "update", "file": "demo.py", "line": 5},
        {"name": "draw", "file": "demo.py", "line": 9}]}, "profiles": [
        {"type": "sampled", "name": "Thread 1", "unit": "seconds",
         "samples": [[0, 1], [0, 2], [0, 1, 1]], "weights": [0.01, 0.02, 0.03]}]}


class SummaryTests(unittest.TestCase):
    def test_recursion_preserves_path_without_double_counting_inclusive_weight(self):
        source = profile_document()
        original = deepcopy(source)
        report = summarize_speedscope(source)
        profile = report["profiles"][0]
        functions = {row["name"]: row for row in profile["functions"]}
        self.assertEqual(report["total_samples"], 3)
        self.assertAlmostEqual(functions["update"]["inclusive_weight"], 0.04)
        self.assertEqual(functions["update"]["inclusive_samples"], 2)
        self.assertAlmostEqual(functions["main"]["self_weight"], 0)
        self.assertAlmostEqual(sum(row["self_weight"] for row in functions.values()), 0.06)
        self.assertIn([0, 1, 1], [row["frames"] for row in profile["call_paths"]])
        self.assertEqual(source, original)

    def test_threads_with_different_units_remain_separate(self):
        source = profile_document()
        other = deepcopy(source["profiles"][0])
        other.update(name="Thread 2", unit="none", weights=[1, 1, 1])
        source["profiles"].append(other)
        report = summarize_speedscope(source)
        self.assertEqual(report["total_samples"], 6)
        self.assertEqual([p["weight_unit"] for p in report["profiles"]], ["seconds", "none"])

    def test_invalid_frame_or_weight_is_rejected(self):
        for invalid in (-1, 3, True, "1"):
            with self.subTest(frame=invalid):
                source = profile_document()
                source["profiles"][0]["samples"][0] = [invalid]
                with self.assertRaises(ValueError):
                    summarize_speedscope(source)
        for invalid in (-1, float("nan"), float("inf"), True):
            with self.subTest(weight=invalid):
                source = profile_document()
                source["profiles"][0]["weights"][0] = invalid
                with self.assertRaises(ValueError):
                    summarize_speedscope(source)

    def test_missing_weight_and_unsupported_profile_are_rejected(self):
        source = profile_document()
        source["profiles"][0]["weights"].pop()
        with self.assertRaises(ValueError):
            summarize_speedscope(source)
        source = profile_document()
        source["profiles"][0]["type"] = "evented"
        with self.assertRaises(ValueError):
            summarize_speedscope(source)


class RecordingTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "output/performance/test_scratch"
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.destination = Path(self.temporary.name) / "capture"
        self.arguments = dict(py_spy=sys.executable, output_dir=self.destination,
                              cwd=ROOT, duration_seconds=2, rate_hz=100, pid=1234)
        self.commands = []

    def collect(self, command, **kwargs):
        self.commands.append(command)
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "py-spy test\n", "")
        destination = Path(command[command.index("--output") + 1])
        destination.write_text(json.dumps(profile_document()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    def test_attach_preserves_raw_data_and_does_not_request_launch_or_shell(self):
        with patch("ferrial_drive.diagnostics.profiler.subprocess.run", side_effect=self.collect) as run:
            record_profile(**self.arguments)
        command = self.commands[-1]
        self.assertEqual(command[-2:], ["--pid", "1234"])
        self.assertNotIn("--subprocesses", command)
        self.assertNotIn("--", command)
        self.assertNotIn("shell", run.call_args.kwargs)
        raw = json.loads((self.destination / "profile.speedscope.json").read_text())
        self.assertEqual(raw, profile_document())
        session = json.loads((self.destination / "session.json").read_text())
        self.assertEqual(session["status"], "complete")
        self.assertFalse(session["overhead_correction_applied"])
        self.assertFalse(session["gpu_utilization_measured"])
        self.assertTrue((self.destination / "summary.json").is_file())

    def test_launch_follows_venv_children_and_preserves_argument_boundaries(self):
        self.arguments.pop("pid")
        self.arguments.update(target=ROOT / "samples/profiler/workload.py", python_executable=sys.executable,
                              target_args=["--label", "space and & characters"])
        with patch("ferrial_drive.diagnostics.profiler.subprocess.run", side_effect=self.collect):
            record_profile(**self.arguments)
        self.assertIn("--subprocesses", self.commands[-1])
        self.assertEqual(self.commands[-1][-2:], ["--label", "space and & characters"])

    def test_existing_capture_is_preserved(self):
        self.destination.mkdir()
        original = self.destination / "session.json"
        original.write_text("original", encoding="utf-8")
        with patch("ferrial_drive.diagnostics.profiler.subprocess.run", side_effect=self.collect):
            with self.assertRaises(FileExistsError):
                record_profile(**self.arguments)
        self.assertEqual(original.read_text(), "original")
        self.assertEqual(len(self.commands), 1)

    def test_collector_failure_keeps_log_and_marks_session_failed(self):
        def fail(command, **kwargs):
            if "--version" in command:
                return self.collect(command, **kwargs)
            kwargs["stdout"].write("access denied\n")
            return subprocess.CompletedProcess(command, 1)
        with patch("ferrial_drive.diagnostics.profiler.subprocess.run", side_effect=fail):
            with self.assertRaises(RuntimeError):
                record_profile(**self.arguments)
        self.assertIn("access denied", (self.destination / "collector.log").read_text())
        self.assertEqual(json.loads((self.destination / "session.json").read_text())["status"], "failed")
        self.assertFalse((self.destination / "summary.json").exists())

    def test_zero_samples_do_not_pass_as_success(self):
        def empty(command, **kwargs):
            result = self.collect(command, **kwargs)
            if "--output" in command:
                data = profile_document()
                data["profiles"] = []
                Path(command[command.index("--output") + 1]).write_text(json.dumps(data))
            return result
        with patch("ferrial_drive.diagnostics.profiler.subprocess.run", side_effect=empty):
            with self.assertRaisesRegex(RuntimeError, "스택 샘플이 없다"):
                record_profile(**self.arguments)
        self.assertEqual(json.loads((self.destination / "session.json").read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()

"""화면 교체·수명 주기·실패 시 정리를 창 없이 확인한다."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))

from unit_test_runner import Stop, SwitchTo, TestProgram, WindowSpec, run
from unit_test_runner.loader import load_test
from unit_test_runner.runner import TestHost


class RecordingProgram(TestProgram):
    def __init__(self, name, log, *, events=None, update_request=None, fail=None):
        self.name, self.log = name, log
        self.events = events or {}
        self.update_request, self.fail = update_request, fail

    def record(self, operation):
        self.log.append(f"{self.name}.{operation}")
        if self.fail == operation:
            raise RuntimeError("테스트에서 의도한 실패")

    def enter(self):
        self.record("enter")

    def handle_event(self, event):
        self.record(f"event:{event}")
        return self.events.get(event)

    def update(self, delta_seconds):
        if delta_seconds < 0:
            raise AssertionError("시간 역행")
        self.record("update")
        return self.update_request

    def draw(self):
        self.record("draw")

    def exit(self):
        self.record("exit")


class FakeWindow:
    def __init__(self, log, batches=()):
        self.log = log
        self.batches = iter(batches)

    def open(self, window):
        self.log.append("window.open")

    def events(self):
        return next(self.batches, [])

    def is_close_event(self, event):
        return event == "window.close_request"

    def present(self):
        self.log.append("window.present")

    def close(self):
        self.log.append("window.close")


class RunnerTests(unittest.TestCase):
    def test_switch_keeps_window_and_routes_remaining_events_to_new_program(self):
        log = []
        second = RecordingProgram("second", log, events={"stop": Stop()})
        first = RecordingProgram("first", log, events={"next": SwitchTo(second)})
        backend = FakeWindow(log, [["next", "after_switch"], ["stop"]])
        run(first, backend=backend, frame_limit=3)
        self.assertEqual(log, [
            "window.open", "first.enter", "first.event:next", "first.exit",
            "second.enter", "second.event:after_switch", "second.update", "second.draw",
            "window.present", "second.event:stop", "second.exit", "window.close",
        ])

    def test_update_can_request_flow_change_before_draw(self):
        log = []
        second = RecordingProgram("second", log)
        first = RecordingProgram("first", log, update_request=SwitchTo(second))
        run(first, backend=FakeWindow(log), frame_limit=1)
        self.assertNotIn("first.draw", log)
        self.assertIn("second.draw", log)
        self.assertLess(log.index("first.exit"), log.index("second.enter"))

    def test_window_close_does_not_dispatch_or_draw_again(self):
        log = []
        run(RecordingProgram("screen", log),
            backend=FakeWindow(log, [["window.close_request", "stale_event"]]))
        self.assertEqual(log, ["window.open", "screen.enter", "screen.exit", "window.close"])

    def test_failures_release_program_before_window(self):
        for operation in ("enter", "event:click", "update", "draw", "exit"):
            with self.subTest(operation=operation):
                log = []
                program = RecordingProgram("screen", log, fail=operation)
                with self.assertRaisesRegex(RuntimeError, "의도한 실패"):
                    run(program, backend=FakeWindow(log, [["click"]]), frame_limit=1)
                self.assertEqual(log[-2:], ["screen.exit", "window.close"])
                self.assertEqual(log.count("screen.exit"), 1)

    def test_failed_replacement_is_cleaned_up(self):
        log = []
        second = RecordingProgram("second", log, fail="enter")
        first = RecordingProgram("first", log, events={"next": SwitchTo(second)})
        with self.assertRaises(RuntimeError):
            run(first, backend=FakeWindow(log, [["next"]]))
        self.assertEqual(log[-4:], ["first.exit", "second.enter", "second.exit", "window.close"])

    def test_close_is_idempotent(self):
        log = []
        host = TestHost()
        host.switch_to(RecordingProgram("screen", log))
        host.close()
        host.close()
        self.assertEqual(log, ["screen.enter", "screen.exit"])

    def test_invalid_flow_return_is_reported_and_cleaned_up(self):
        log = []
        program = RecordingProgram("screen", log, events={"click": True})
        with self.assertRaisesRegex(TypeError, "반환값"):
            run(program, backend=FakeWindow(log, [["click"]]))
        self.assertEqual(log[-2:], ["screen.exit", "window.close"])

    def test_frame_limit_validation_happens_before_open(self):
        log = []
        with self.assertRaises(ValueError):
            run(RecordingProgram("screen", log), backend=FakeWindow(log), frame_limit=0)
        self.assertEqual(log, [])

    def test_sample_loads_without_window_font_or_game_imports(self):
        before = set(sys.modules)
        program, window = load_test(ROOT / "samples/unit_test_runner/basic_flow.py")
        self.assertIsInstance(program, TestProgram)
        self.assertEqual((window.width, window.height), (1280, 720))
        self.assertIsNone(program.font)
        added = set(sys.modules) - before
        self.assertFalse(any(name.startswith(("pico2d", "ferrial_drive")) for name in added))

    def test_missing_file_fails_before_open(self):
        with self.assertRaisesRegex(ValueError, "파일"):
            load_test(ROOT / "samples/unit_test_runner/missing.py")

    def test_window_rejects_invalid_dimensions_and_time(self):
        for changes in ({"width": 0}, {"height": -1}, {"width": 12.5},
                        {"frames_per_second": 0}, {"frames_per_second": float("nan")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                WindowSpec(**changes)


if __name__ == "__main__":
    unittest.main()

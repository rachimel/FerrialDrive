"""GUI 드롭의 교체·실패 복구·대기 화면 복귀 계약. 사용자 확인용으로 준비한다."""

from ctypes import Structure, addressof, c_char_p, c_uint32, cast, create_string_buffer
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))

from unit_test_runner.events import FilesDropped
from unit_test_runner.gui import DropSession, DropView, LAUNCHER_WINDOW, run_gui, summarize_failure
from unit_test_runner.processes import LaunchPlan
from unit_test_runner.runner import PicoWindow


class NativeDrop(Structure):
    _fields_ = [("type", c_uint32), ("timestamp", c_uint32),
                ("file", c_char_p), ("windowID", c_uint32)]


class Child:
    def __init__(self, log, name):
        self.log, self.name = log, name
        self.returncode = None
        self.closed = False
        self.log.append(f"{name}.start")

    def poll(self):
        return self.returncode

    def output_tail(self):
        return "RuntimeError: 초기화 실패"

    def close(self):
        if not self.closed:
            self.log.append(f"{self.name}.close")
            self.closed = True


class Backend:
    def __init__(self, log, batches=()):
        self.log = log
        self.batches = iter(batches)
        self.spec = LAUNCHER_WINDOW

    def open(self, window):
        self.spec = window
        self.log.append("window.open")

    def resize(self, window):
        self.spec = window
        self.log.append("window.resize")

    def events(self):
        return next(self.batches, [])

    def is_close_event(self, event):
        return event == "close"

    def present(self):
        self.log.append("window.present")

    def close(self):
        self.log.append("window.close")


class View:
    def __init__(self, backend):
        self.log = backend.log

    def idle(self, active_path=None):
        self.log.append("view.idle")

    def error(self, message):
        if message:
            self.log.append("view.error")

    def close(self):
        self.log.append("view.close")


class GuiTests(unittest.TestCase):
    def test_exception_summary_precedes_traceback_location(self):
        detail = ('Traceback (most recent call last):\n'
                  '  File "C:\\workspace\\config.py", line 47, in __init__\n'
                  '    raise FileNotFoundError("폰트 파일이 없다")\n'
                  'FileNotFoundError: 폰트 파일이 없다: menu.otf\n')
        message = summarize_failure(detail)
        self.assertTrue(message.startswith("FileNotFoundError: 폰트 파일이 없다"))
        self.assertIn("config.py:47", message)
        self.assertNotIn("raise FileNotFoundError", message)

    def test_error_wrapping_uses_measured_width_and_marks_truncation(self):
        view = DropView.__new__(DropView)
        view._text_width = lambda text: sum(20 if ord(char) > 127 else 10 for char in text)
        lines = view._wrap_error("폰트 파일이 없다: " + "very_long_path/" * 20, 160, 6)
        self.assertLessEqual(len(lines), 6)
        self.assertTrue(all(view._text_width(line) <= 160 for line in lines))
        self.assertTrue(lines[-1].endswith("…"))

    def session(self, log):
        children = {}
        def prepare(path):
            if path.name == "bad.py":
                raise ValueError("파일 오류")
            return LaunchPlan(path, ())
        def start(plan):
            child = Child(log, plan.path.name)
            children[plan.path.name] = child
            return child
        return DropSession(prepare=prepare, start=start), children

    def drop_backend(self, accept_files=True):
        freed = []
        backend = PicoWindow(accept_files=accept_files)
        backend.pico = SimpleNamespace(
            SDL_DROPBEGIN=0x1002, SDL_DROPFILE=0x1000, SDL_DROPTEXT=0x1001,
            SDL_DROPCOMPLETE=0x1003, window=object(), SDL_GetWindowID=lambda window: 42,
            SDL_free=lambda pointer: freed.append(pointer.value))
        return backend, freed

    def test_native_drop_groups_files_and_frees_original_filename_pointers(self):
        backend, freed = self.drop_backend()
        events = []
        begin = SimpleNamespace(type=0x1002, drop=NativeDrop(0x1002, 0, None, 42))
        backend._collect_drop(begin, events)
        buffers = [create_string_buffer(name.encode("utf-8")) for name in ("한글.py", "second.py")]
        for buffer in buffers:
            raw = SimpleNamespace(type=0x1000,
                                  drop=NativeDrop(0x1000, 0, cast(buffer, c_char_p), 42))
            backend._collect_drop(raw, events)
        complete = SimpleNamespace(type=0x1003, drop=NativeDrop(0x1003, 0, None, 42))
        backend._collect_drop(complete, events)
        self.assertEqual(events, [FilesDropped((Path("한글.py"), Path("second.py")))])
        self.assertEqual(freed, [addressof(buffer) for buffer in buffers])

    def test_ignored_native_drop_still_frees_filename(self):
        backend, freed = self.drop_backend(accept_files=False)
        buffer = create_string_buffer(b"ignored.py")
        raw = SimpleNamespace(type=0x1000,
                              drop=NativeDrop(0x1000, 0, cast(buffer, c_char_p), 42))
        events = []
        backend._collect_drop(raw, events)
        self.assertEqual(events, [])
        self.assertEqual(freed, [addressof(buffer)])

    def test_replacement_closes_previous_process_before_starting_next(self):
        log = []
        session, children = self.session(log)
        session.drop((Path("first.py"),))
        session.drop((Path("second.py"),))
        self.assertLess(log.index("first.py.close"), log.index("second.py.start"))
        self.assertIs(session.child, children["second.py"])
        session.close()

    def test_invalid_file_preserves_current_process(self):
        log = []
        session, children = self.session(log)
        session.drop((Path("current.py"),))
        with patch("unit_test_runner.gui.traceback.print_exc"):
            session.drop((Path("bad.py"),))
        self.assertIs(session.child, children["current.py"])
        self.assertNotIn("current.py.close", log)
        self.assertIn("파일 오류", session.error)
        session.close()

    def test_multiple_files_are_rejected_without_import(self):
        def loader(path):
            raise AssertionError("여러 파일을 불러오면 안 된다.")
        session = DropSession(prepare=loader)
        session.drop((Path("first.py"), Path("second.py")))
        self.assertIn("하나", session.error)
        self.assertIsNone(session.child)

    def test_failed_child_returns_to_idle_without_duplicate_cleanup(self):
        log = []
        session, children = self.session(log)
        session.drop((Path("broken.py"),))
        children["broken.py"].returncode = 1
        session.poll()
        session.close()
        self.assertIsNone(session.child)
        self.assertEqual(log.count("broken.py.close"), 1)
        self.assertIn("초기화 실패", session.error)

    def test_completed_child_keeps_launcher_window(self):
        log = []
        session, children = self.session(log)
        session.drop((Path("sample.py"),))
        children["sample.py"].returncode = 0
        backend = Backend(log, [[FilesDropped((Path("sample.py"),))]])
        with patch("unit_test_runner.gui.DropSession", return_value=session):
            with patch.object(session, "drop"):
                run_gui(backend=backend, view_factory=View, frame_limit=2)
        self.assertEqual(log.count("window.open"), 1)
        self.assertEqual(log.count("sample.py.close"), 1)
        self.assertEqual(log.count("view.idle"), 2)
        self.assertNotIn("window.resize", log)
        self.assertEqual(log[-2:], ["view.close", "window.close"])

    def test_window_close_does_not_draw_another_frame(self):
        log = []
        run_gui(backend=Backend(log, [["close"]]), view_factory=View)
        self.assertEqual(log, ["window.open", "view.close", "window.close"])

    def test_launcher_close_stops_owned_child(self):
        log = []
        session, children = self.session(log)
        session.drop((Path("sample.py"),))
        with patch("unit_test_runner.gui.DropSession", return_value=session):
            run_gui(backend=Backend(log, [["close"]]), view_factory=View)
        self.assertTrue(children["sample.py"].closed)
        self.assertLess(log.index("sample.py.close"), log.index("window.close"))


if __name__ == "__main__":
    unittest.main()

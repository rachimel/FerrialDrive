"""GUI 드롭의 교체·실패 복구·대기 화면 복귀 계약. 사용자 확인용으로 준비한다."""

from ctypes import Structure, addressof, c_char_p, c_uint32, cast, create_string_buffer
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Tools"))

from unit_test_runner import Stop, TestProgram, WindowSpec
from unit_test_runner.events import FilesDropped
from unit_test_runner.gui import DropSession, LAUNCHER_WINDOW, run_gui
from unit_test_runner.runner import PicoWindow


class NativeDrop(Structure):
    _fields_ = [("type", c_uint32), ("timestamp", c_uint32),
                ("file", c_char_p), ("windowID", c_uint32)]


class Program(TestProgram):
    def __init__(self, log, name, *, stop=False, fail=False):
        self.log, self.name = log, name
        self.stop, self.fail = stop, fail

    def enter(self):
        self.log.append(f"{self.name}.enter")
        if self.fail:
            raise RuntimeError("초기화 실패")

    def update(self, delta_seconds):
        return Stop() if self.stop else None

    def draw(self):
        self.log.append(f"{self.name}.draw")

    def exit(self):
        self.log.append(f"{self.name}.exit")


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

    def idle(self):
        self.log.append("view.idle")

    def error(self, message):
        if message:
            self.log.append("view.error")

    def close(self):
        self.log.append("view.close")


class GuiTests(unittest.TestCase):
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

    def test_replacement_closes_previous_program_before_entering_next(self):
        log = []
        programs = {"first.py": Program(log, "first"), "second.py": Program(log, "second")}
        session = DropSession(Backend(log), lambda path: (programs[path.name], WindowSpec()))
        session.drop((Path("first.py"),))
        session.drop((Path("second.py"),))
        self.assertLess(log.index("first.exit"), log.index("second.enter"))
        self.assertIs(session.host.current, programs["second.py"])
        session.host.close()

    def test_invalid_file_preserves_current_program(self):
        log = []
        current = Program(log, "current")
        def loader(path):
            if path.name == "bad.py":
                raise ValueError("파일 오류")
            return current, WindowSpec()
        session = DropSession(Backend(log), loader)
        session.drop((Path("current.py"),))
        with patch("unit_test_runner.gui.traceback.print_exc"):
            session.drop((Path("bad.py"),))
        self.assertIs(session.host.current, current)
        self.assertNotIn("current.exit", log)
        self.assertIn("파일 오류", session.error)
        session.host.close()

    def test_multiple_files_are_rejected_without_import(self):
        def loader(path):
            raise AssertionError("여러 파일을 불러오면 안 된다.")
        session = DropSession(Backend([]), loader)
        session.drop((Path("first.py"), Path("second.py")))
        self.assertIn("하나", session.error)
        self.assertIsNone(session.host.current)

    def test_failed_enter_returns_to_idle_without_duplicate_exit(self):
        log = []
        program = Program(log, "broken", fail=True)
        backend = Backend(log)
        session = DropSession(backend, lambda path: (program, WindowSpec(640, 480)))
        with patch("unit_test_runner.gui.traceback.print_exc"):
            session.drop((Path("broken.py"),))
        self.assertIsNone(session.host.current)
        self.assertEqual(log.count("broken.exit"), 1)
        self.assertEqual(backend.spec, LAUNCHER_WINDOW)
        self.assertIn("실행 오류", session.error)

    def test_stopped_program_returns_to_idle_and_keeps_window(self):
        log = []
        program = Program(log, "sample", stop=True)
        backend = Backend(log, [[FilesDropped((Path("sample.py"),))]])
        class Session(DropSession):
            def __init__(self, window):
                super().__init__(window, lambda path: (program, WindowSpec()))
        with patch("unit_test_runner.gui.DropSession", Session):
            run_gui(backend=backend, view_factory=View, frame_limit=2)
        self.assertEqual(log.count("window.open"), 1)
        self.assertEqual(log.count("sample.exit"), 1)
        self.assertEqual(log.count("view.idle"), 2)
        self.assertEqual(log[-2:], ["view.close", "window.close"])

    def test_window_close_does_not_draw_another_frame(self):
        log = []
        run_gui(backend=Backend(log, [["close"]]), view_factory=View)
        self.assertEqual(log, ["window.open", "view.close", "window.close"])


if __name__ == "__main__":
    unittest.main()

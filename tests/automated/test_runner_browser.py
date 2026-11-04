"""탐색 필터·비실행 판별·목록 조작과 실제 실행 경계의 일치를 확인한다."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))

from unit_test_runner.browser import FileBrowser
from unit_test_runner.gui import BROWSER_TOP, handle_browser_event
from unit_test_runner.loader import load_test
from unit_test_runner.processes import prepare_test


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runner-browser-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        keys = ("SDL_KEYDOWN", "SDL_MOUSEWHEEL", "SDL_MOUSEBUTTONDOWN", "SDL_BUTTON_LEFT",
                "SDLK_UP", "SDLK_DOWN", "SDLK_PAGEUP", "SDLK_PAGEDOWN", "SDLK_BACKSPACE",
                "SDLK_F5", "SDLK_RETURN", "SDLK_KP_ENTER")
        self.pico = SimpleNamespace(**{name: index for index, name in enumerate(keys)})

    def source(self, name, text):
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def event(self, browser, **values):
        return handle_browser_event(browser, SimpleNamespace(**values), self.pico, 1280)

    def test_filter_sort_and_inspection_do_not_execute_sources(self):
        (self.directory / "z_folder").mkdir()
        (self.directory / "a_folder").mkdir()
        self.source("ignore.txt", "ignored")
        marker = self.directory / "executed"
        self.source("b.PY", '"""테스트 제목\n\n실행하지 않고 읽는 소개다.\n"""\n'
                    'UNIT_TEST_ENTRYPOINT: str = "standalone"\n'
                    f'open({str(marker)!r}, "w").close()\nraise RuntimeError("실행 금지")\n')
        self.source("a.py", "def create_test():\n    pass\n")
        self.source("helper.py", '"""보조 모듈\n실행 대상이 아닌 파일이다.\n"""\nVALUE = 1\n')
        browser = FileBrowser(self.directory)
        self.assertEqual([entry.display_name for entry in browser.entries],
                         ["..", "a_folder", "z_folder", "a.py", "b.PY", "helper.py"])
        self.assertTrue(browser.entries[0].is_parent)
        self.assertEqual(browser.entries[0].path, self.directory.parent)
        self.assertEqual([entry.mode for entry in browser.entries[3:]], ["legacy", "standalone", ""])
        self.assertFalse(marker.exists())
        self.assertIn("진입점 없음", browser.entries[-1].reason)
        self.assertEqual((browser.entries[4].title, browser.entries[4].description),
                         ("테스트 제목", "실행하지 않고 읽는 소개다."))
        self.assertEqual(browser.entries[-1].title, "보조 모듈")

    def test_invalid_files_are_disabled_and_rejected_by_launch_preparation(self):
        for name, text, reason in (
                ("syntax.py", "def broken(:\n", "문법 오류"),
                ("return.py", "return 1\n", "문법 오류"),
                ("mode.py", 'UNIT_TEST_ENTRYPOINT = "other"\n', "standalone 또는 legacy"),
                ("dynamic.py", 'UNIT_TEST_ENTRYPOINT = pick_mode()\n', "리터럴"),
                ("async.py", "async def create_test():\n    pass\n", "진입점 없음"),
                ("args.py", "def create_test(required):\n    pass\n", "필수 인자"),
                ("keyword.py", "def create_test(*, required):\n    pass\n", "필수 인자")):
            path = self.source(name, text)
            with self.subTest(name=name):
                with self.assertRaises((SyntaxError, ValueError)):
                    prepare_test(path)
        browser = FileBrowser(self.directory)
        for index, entry in enumerate(browser.entries):
            if entry.is_parent:
                continue
            self.assertFalse(entry.runnable)
            self.assertTrue(entry.reason)
            browser.select(index)
            self.assertIsNone(browser.activate())

    def test_refresh_picks_up_edits_and_preserves_selection(self):
        path = self.source("test.py", "VALUE = 1\n")
        browser = FileBrowser(self.directory)
        browser.select(1)
        self.assertEqual((browser.selected.title, browser.selected.description), ("", ""))
        self.assertFalse(browser.selected.runnable)
        path.write_text('UNIT_TEST_ENTRYPOINT = "standalone"\n', encoding="utf-8")
        self.event(browser, type=self.pico.SDL_KEYDOWN, key=self.pico.SDLK_F5)
        self.assertTrue(browser.selected.runnable)
        self.assertEqual(browser.activate(), path)
        # 목록 판별 후 수정한 파일도 시작 직전에 다시 검사한다.
        path.write_text("VALUE = 2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            prepare_test(path)

    def test_uppercase_extension_legacy_file_loads_through_the_same_contract(self):
        path = self.source("legacy.PY", 'from unit_test_runner import TestProgram\n'
                           'class Sample(TestProgram):\n    def draw(self):\n        pass\n'
                           'def create_test():\n    return Sample()\n')
        self.assertIn("worker.py", " ".join(prepare_test(path).command))
        program, window = load_test(path)
        self.assertEqual(type(program).__name__, "Sample")

    def test_double_click_navigation_parent_and_failed_navigation(self):
        folder = self.directory / "folder"
        folder.mkdir()
        browser = FileBrowser(self.directory)
        self.event(browser, type=self.pico.SDL_MOUSEBUTTONDOWN,
                   button=self.pico.SDL_BUTTON_LEFT, x=60, y=BROWSER_TOP + 42, clicks=2)
        self.assertEqual(browser.directory, folder)
        self.assertEqual([entry.display_name for entry in browser.entries], [".."])
        browser.select(0)
        self.assertIsNone(browser.activate())
        self.assertEqual(browser.directory, self.directory)
        browser.navigate(folder)
        self.event(browser, type=self.pico.SDL_KEYDOWN, key=self.pico.SDLK_BACKSPACE)
        self.assertEqual(browser.directory, self.directory)
        self.assertFalse(browser.navigate(self.directory / "missing"))
        self.assertEqual(browser.directory, self.directory)
        self.assertEqual(browser.entries[1].path, folder)
        self.assertTrue(browser.error)

    def test_click_selects_double_click_or_enter_launches_and_removed_buttons_do_nothing(self):
        self.source("disabled.py", "VALUE = 1\n")
        path = self.source("enabled.py", 'UNIT_TEST_ENTRYPOINT = "standalone"\n')
        browser = FileBrowser(self.directory)
        click = dict(type=self.pico.SDL_MOUSEBUTTONDOWN, button=self.pico.SDL_BUTTON_LEFT,
                     x=60, y=BROWSER_TOP + 42)
        self.assertIsNone(self.event(browser, **click, clicks=2))
        self.assertIsNone(self.event(browser, type=self.pico.SDL_MOUSEBUTTONDOWN,
                                     button=self.pico.SDL_BUTTON_LEFT, x=1140, y=90))
        click["y"] += 32
        self.assertIsNone(self.event(browser, **click, clicks=1))
        self.assertEqual(browser.selected.path, path)
        self.assertEqual(self.event(browser, **click, clicks=2), path)
        self.assertEqual(self.event(browser, type=self.pico.SDL_KEYDOWN,
                                    key=self.pico.SDLK_RETURN), path)
        self.assertIsNone(self.event(browser, type=self.pico.SDL_MOUSEBUTTONDOWN,
                                     button=self.pico.SDL_BUTTON_LEFT, x=1140, y=90))

    def test_scrolling_keyboard_selection_and_bounds(self):
        for index in range(20):
            self.source(f"{index:02}.py", "VALUE = 1\n")
        browser = FileBrowser(self.directory, visible_rows=3)
        self.event(browser, type=self.pico.SDL_MOUSEWHEEL, y=-1)
        self.assertEqual(browser.offset, 3)
        browser.scroll(100)
        self.assertEqual(browser.offset, 18)
        self.event(browser, type=self.pico.SDL_KEYDOWN, key=self.pico.SDLK_DOWN)
        self.assertEqual((browser.selected_index, browser.offset), (0, 0))
        browser.move_selection(100)
        self.assertEqual((browser.selected_index, browser.offset), (20, 18))
        browser.move_selection(-100)
        self.assertEqual((browser.selected_index, browser.offset), (0, 0))


if __name__ == "__main__":
    unittest.main()

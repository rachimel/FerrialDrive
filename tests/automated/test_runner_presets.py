"""시나리오 선택의 비실행 판별·취소 보존·인자 전달·시작 전 재검사를 확인한다."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))

from unit_test_runner.browser import FileBrowser
from unit_test_runner.gui import DropSession, handle_preset_event, preset_layout
from unit_test_runner.processes import prepare_test, run_file


PRESETS = (
    {"id": "combat", "label": "Combat", "args": ["--scenario", "combat", "--detail"]},
    {"id": "movement", "label": "Movement", "args": ["--scenario", "sword", "--detail"]},
)


class PresetTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="runner-presets-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "scenario.py"
        self.source = 'UNIT_TEST_ENTRYPOINT = "standalone"\nUNIT_TEST_PRESETS = ' + repr(PRESETS) + "\n"
        self.path.write_text(self.source + 'raise RuntimeError("부모 실행 금지")\n', encoding="utf-8")
        keys = ("SDL_KEYDOWN", "SDL_MOUSEBUTTONDOWN", "SDL_BUTTON_LEFT", "SDLK_ESCAPE",
                "SDLK_UP", "SDLK_DOWN", "SDLK_RETURN", "SDLK_KP_ENTER")
        self.pico = SimpleNamespace(**{name: index for index, name in enumerate(keys)})

    def test_prepare_and_browser_read_choices_without_executing_source(self):
        plan = prepare_test(self.path, preset="movement")
        self.assertEqual(plan.command[-3:], ("--scenario", "sword", "--detail"))
        self.assertEqual([item.preset_id for item in plan.presets], ["combat", "movement"])
        browser = FileBrowser(self.directory)
        self.assertTrue(next(entry for entry in browser.entries if entry.path == self.path).runnable)

    def test_invalid_or_dynamic_metadata_is_disabled_consistently(self):
        for metadata in ("make_choices()", "[]", "[{'id': 'a'}]", repr((PRESETS[0], PRESETS[0])),
                         "[{'id':'a','label':'A','args':[123]}]"):
            self.path.write_text('UNIT_TEST_ENTRYPOINT="standalone"\nUNIT_TEST_PRESETS=' + metadata, encoding="utf-8")
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                prepare_test(self.path)
            browser = FileBrowser(self.directory)
            self.assertFalse(next(entry for entry in browser.entries if entry.path == self.path).runnable)

    def session(self):
        previous = Mock()
        start = Mock(return_value=Mock())
        session = DropSession(start=start)
        session.child = previous
        return session, previous, start

    def key(self, session, key):
        return handle_preset_event(session, SimpleNamespace(type=self.pico.SDL_KEYDOWN, key=key),
                                   self.pico, 1280, 720)

    def test_open_and_cancel_preserve_active_child(self):
        session, previous, start = self.session()
        session.drop((self.path,))
        self.assertIsNotNone(session.pending_plan)
        previous.close.assert_not_called()
        start.assert_not_called()
        self.assertTrue(self.key(session, self.pico.SDLK_ESCAPE))
        self.assertIsNone(session.pending_plan)
        self.assertIs(session.child, previous)
        previous.close.assert_not_called()

    def test_keyboard_selection_passes_only_selected_arguments(self):
        session, previous, start = self.session()
        session.drop((self.path,))
        self.key(session, self.pico.SDLK_DOWN)
        self.key(session, self.pico.SDLK_RETURN)
        previous.close.assert_called_once()
        self.assertEqual(start.call_args.args[0].command[-3:], ("--scenario", "sword", "--detail"))
        self.assertIsNone(session.pending_plan)

    def test_mouse_selection_uses_same_launch_path(self):
        session, previous, start = self.session()
        session.drop((self.path,))
        x, y, _, _ = preset_layout(1280, 720, 2)
        event = SimpleNamespace(type=self.pico.SDL_MOUSEBUTTONDOWN, button=self.pico.SDL_BUTTON_LEFT,
                                x=x + 40, y=y + 76 + 44 + 20)
        self.assertTrue(handle_preset_event(session, event, self.pico, 1280, 720))
        self.assertEqual(start.call_args.args[0].command[-3:], ("--scenario", "sword", "--detail"))

    def test_source_changed_during_selection_is_rechecked_before_replacement(self):
        session, previous, start = self.session()
        session.drop((self.path,))
        self.path.write_text('UNIT_TEST_ENTRYPOINT="standalone"\n', encoding="utf-8")
        with patch("unit_test_runner.gui.traceback.print_exc"):
            session.launch_selected()
        self.assertIn("실행 옵션이 없다", session.error)
        previous.close.assert_not_called()
        start.assert_not_called()

    def test_actual_child_receives_preset_and_frame_limit(self):
        self.path.write_text(self.source + 'import json, sys\nfrom pathlib import Path\n'
                             'Path(__file__).with_suffix(".json").write_text(json.dumps(sys.argv[1:]))\n', encoding="utf-8")
        self.assertEqual(run_file(self.path, frame_limit=3, preset="combat"), 0)
        self.assertEqual(json.loads(self.path.with_suffix(".json").read_text()),
                         ["--scenario", "combat", "--detail", "--frames", "3"])

    def test_benchmark_choices_are_interactive_and_unlimited(self):
        for preset in ("combat", "movement"):
            plan = prepare_test(ROOT / "tests/hardware_profile_benchmark.py", preset=preset)
            self.assertNotIn("--auto", plan.command)
            self.assertNotIn("--frames", plan.command)
            self.assertIn("--detail", plan.command)


if __name__ == "__main__":
    unittest.main()

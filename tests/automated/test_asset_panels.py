"""제작·파일·ID 입력을 메인 SDL 창에서 처리하고 종료 입력이 계속 전달되는지 검사한다."""

import builtins
from ctypes import byref
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from samples.asset_loader.make_sample import write_samples
from ferrial_drive.assets import SpriteBundle
from ferrial_drive.ui.standalone import _events, run_preview
from Tools.asset_loader.app import AssetLoaderApp
from Tools.asset_loader.editors import AssemblyPanel, RenderPanel
from Tools.asset_loader.file_panel import FilePanel, IdPanel


class AssetPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pico2d.pico2d as pico
        cls.pico = pico
        pico.open_canvas(1280, 800)
        if not pico.renderer:
            pico.renderer = pico.SDL_CreateRenderer(pico.window, -1, pico.SDL_RENDERER_SOFTWARE)

    @classmethod
    def tearDownClass(cls):
        cls.pico.close_canvas()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="asset-panels-")
        self.root = write_samples(self.temporary.name)
        self.app = AssetLoaderApp(source=self.root / "bundle.json", catalog=self.root / "catalog.json", debug=True)
        self.app.enter()

    def tearDown(self):
        self.app.exit()
        self.temporary.cleanup()

    def key(self, key, mod=0):
        self.app.handle_event(SimpleNamespace(type=self.pico.SDL_KEYDOWN, key=key, mod=mod))

    def click(self, rect, *, clicks=1, up=False):
        self.app.handle_event(SimpleNamespace(type=self.pico.SDL_MOUSEBUTTONUP if up else self.pico.SDL_MOUSEBUTTONDOWN,
            button=self.pico.SDL_BUTTON_LEFT, x=rect.x + 4, y=rect.y + 4, clicks=clicks))

    def test_all_editors_return_immediately_and_use_one_window(self):
        original_import = builtins.__import__
        def no_tk(name, *args, **kwargs):
            if name.startswith("tkinter"):
                raise AssertionError("Unexpected child window")
            return original_import(name, *args, **kwargs)
        window = self.pico.window
        with patch("builtins.__import__", side_effect=no_tk):
            for action, kind in (("render", RenderPanel), ("compose", AssemblyPanel), ("id", IdPanel),
                                 ("open", FilePanel), ("catalog", FilePanel)):
                with self.subTest(action=action):
                    self.app.action(action)
                    self.assertIsInstance(self.app.panel, kind)
                    self.app.update(0.1)
                    self.app.draw()
                    self.assertIs(self.pico.window, window)
                    self.key(self.pico.SDLK_ESCAPE)
                    self.assertIsNone(self.app.panel)
                    self.assertTrue(self.app.running)

    def test_visible_close_button_and_window_close_work_with_panel_open(self):
        self.app.action("render")
        self.click(self.app.panel.close_rect)
        self.assertIsNone(self.app.panel)
        self.app.action("compose")
        self.app.handle_event(SimpleNamespace(type=self.pico.SDL_WINDOWEVENT, window_event=self.pico.SDL_WINDOWEVENT_CLOSE))
        self.assertFalse(self.app.running)

    def test_filter_dropdown_changes_shared_display_and_escape_only_closes_menu(self):
        from Tools.asset_loader.app import FILTER_RECT
        self.click(FILTER_RECT)
        self.assertTrue(self.app.filter_popup)
        self.click(SimpleNamespace(x=882, y=405))
        self.assertEqual(self.app.handle.resource.filtering, 'nearest')
        self.assertEqual(self.app.filtering, 'nearest')
        self.click(FILTER_RECT)
        self.app.draw()
        self.key(self.pico.SDLK_ESCAPE)
        self.assertFalse(self.app.filter_popup)
        self.assertTrue(self.app.running)

    def test_alt_f4_is_not_swallowed_by_a_focused_text_field(self):
        self.app.action("id")
        self.key(self.pico.SDLK_F4, self.pico.KMOD_ALT)
        self.assertFalse(self.app.running)

    def test_file_browser_cancel_returns_to_render_settings_without_losing_fields(self):
        self.app.action("render")
        panel = self.app.panel
        panel.fields["fps"].text = "24"
        panel.browse()
        self.assertIsInstance(self.app.panel, FilePanel)
        self.app.draw()
        self.key(self.pico.SDLK_ESCAPE)
        self.assertIs(self.app.panel, panel)
        self.assertEqual(panel.value("fps"), "24")

    def test_file_selection_supports_paths_and_keeps_bad_input_visible(self):
        self.app.action("open")
        browser = self.app.panel
        browser.fields["path"].text = str(self.root / "missing.json")
        self.key(self.pico.SDLK_RETURN)
        self.assertIs(self.app.panel, browser)
        self.assertTrue(browser.error)
        browser.fields["path"].text = str(self.root / "image.png")
        self.key(self.pico.SDLK_RETURN)
        self.assertIsNone(self.app.panel)
        self.assertEqual(self.app.source, self.root / "image.png")

    def test_unicode_text_and_composition_do_not_trigger_main_shortcuts(self):
        self.app.action("id")
        panel = self.app.panel
        self.key(self.pico.SDLK_a, self.pico.KMOD_CTRL)
        self.app.handle_event(SimpleNamespace(type=self.pico.SDL_TEXTEDITING, text="한"))
        self.assertEqual(panel.fields["id"].composition, "한")
        self.app.handle_event(SimpleNamespace(type=self.pico.SDL_TEXTINPUT, text="한글"))
        self.assertEqual(panel.value("id"), "한글")
        self.assertEqual(panel.fields["id"].composition, "")
        self.assertFalse(self.app.paused)
        self.key(self.pico.SDLK_RETURN)
        self.assertIs(self.app.panel, panel)
        self.assertTrue(panel.error)
        self.key(self.pico.SDLK_a, self.pico.KMOD_CTRL)
        self.app.handle_event(SimpleNamespace(type=self.pico.SDL_TEXTINPUT, text="edited_id"))
        self.key(self.pico.SDLK_RETURN)
        self.assertIsNone(self.app.panel)
        self.assertEqual(self.app.asset_id, "edited_id")

    def test_assembly_drag_repeat_fps_and_save_share_the_existing_renderer(self):
        self.app.action("compose")
        panel = self.app.panel
        self.click(panel.timeline)
        target = SimpleNamespace(x=panel.timeline.x + 210, y=panel.timeline.y)
        self.click(target, up=True)
        self.assertEqual(panel.order, [1, 2, 0, 3])
        panel.fields["name"].text = "attack"
        panel.fields["fps"].text = "12"
        self.key(self.pico.SDLK_d, self.pico.KMOD_CTRL)
        self.assertEqual(len(panel.order), 5)
        self.key(self.pico.SDLK_DELETE)
        self.assertEqual(len(panel.order), 4)
        self.app.draw()
        with patch("Tools.asset_loader.editors.asset_directory", return_value=self.root / "prerender/edited"):
            panel.submit()
        self.assertIsNone(self.app.panel)
        self.assertEqual(self.app.clip_name, "attack/e")
        bundle = SpriteBundle.load(self.app.source)
        self.assertEqual(bundle.body.clips["attack/e"].fps, 12)
        self.assertEqual(bundle.body.clips["attack/e"], bundle.shadow.clips["attack/e"])

    def test_sdl_adapter_forwards_utf8_and_modifiers_only_when_requested(self):
        list(_events(self.pico, accept_text=True))
        raw = self.pico.SDL_Event()
        raw.type = self.pico.SDL_TEXTINPUT
        raw.text.text = "한글".encode("utf-8")
        self.pico.SDL_PushEvent(byref(raw))
        events = list(_events(self.pico, accept_text=True))
        self.assertEqual(next(event.text for event in events if event.type == self.pico.SDL_TEXTINPUT), "한글")
        raw.type = self.pico.SDL_KEYDOWN
        raw.key.keysym.sym, raw.key.keysym.mod, raw.key.repeat = self.pico.SDLK_a, self.pico.KMOD_CTRL, 1
        self.pico.SDL_PushEvent(byref(raw))
        event = next(event for event in _events(self.pico, accept_text=True) if event.type == self.pico.SDL_KEYDOWN)
        self.assertTrue(event.mod & self.pico.KMOD_CTRL)
        self.assertTrue(event.repeat)


class AssetPanelLoopTests(unittest.TestCase):
    def test_quit_event_still_reaches_main_loop_while_render_settings_are_open(self):
        import pico2d.pico2d as pico
        app = AssetLoaderApp()
        original_enter = app.enter
        def enter():
            original_enter()
            app.action("render")
            event = pico.SDL_Event()
            event.type = pico.SDL_QUIT
            pico.SDL_PushEvent(byref(event))
        with patch.object(app, "enter", side_effect=enter):
            run_preview(app, width=1280, height=800, title="Asset panel close test", frame_limit=2)
        self.assertFalse(app.running)
        self.assertIsNone(app.panel)
        self.assertTrue(app.manager.closed)


if __name__ == "__main__":
    unittest.main()

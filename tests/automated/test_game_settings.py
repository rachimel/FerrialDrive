"""품질 기본값·원자적 저장·취소·메뉴 입력 차단·실행용 프로필 선택을 검사한다."""

from pathlib import Path
from dataclasses import replace
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ferrial_drive.settings import GameSettings, GameSettingsStore, SCREEN_RESOLUTIONS, resolve_texture_profile
from ferrial_drive.ui.settings import GraphicsSettingsMenu
from ferrial_drive.ui.config import UiConfig


class GameSettingsTests(unittest.TestCase):
    def test_resolution_round_trip_cancel_and_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GameSettingsStore(Path(folder)/"preferences.json")
            self.assertIsNone(store.load().screen_resolution)
            menu = GraphicsSettingsMenu(store)
            for resolution in SCREEN_RESOLUTIONS:
                menu.open()
                menu.perform(f"resolution_{resolution[0]}x{resolution[1]}")
                menu.perform("texture_medium")
                menu.draft = replace(menu.draft, show_key_hints=False)
                self.assertEqual(menu.perform("settings_save"), "settings_saved")
                self.assertEqual(store.load(), GameSettings("medium", False, resolution))
            menu.open()
            menu.perform("resolution_1280x720")
            menu.cancel()
            self.assertEqual(store.load().screen_resolution, (1920, 1080))

    def test_invalid_screen_resolutions_are_rejected(self):
        for resolution in ((0, 0), (1280, 800), (1280, True), (1280., 720), [1280, 720], "1280x720", (1280,)):
            with self.subTest(resolution=resolution), self.assertRaises(ValueError):
                GameSettings(screen_resolution=resolution)

    def test_resolution_changes_output_preserves_pointer_mapping_and_rolls_back_failed_save(self):
        from ctypes import byref, c_float, c_int
        from ferrial_drive.rendering import PicoCanvas
        from ferrial_drive.ui.pico_renderer import PicoRenderer

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), \
                PicoCanvas(1920, 1080, '해상도 설정') as canvas:
            p = canvas.pico
            store = GameSettingsStore(Path(folder)/"preferences.json")
            menu = GraphicsSettingsMenu(store)
            config = UiConfig(ROOT/"samples/ui_unit_test_v2/ui_config.json")
            menu.enable_buttons(config)
            for width, height in SCREEN_RESOLUTIONS:
                menu.open()
                menu.perform(f"resolution_{width}x{height}")
                self.assertEqual(menu.perform("settings_save"), "settings_saved")
                w, h = c_int(), c_int()
                self.assertEqual(p.SDL_GetRendererOutputSize(p.renderer, byref(w), byref(h)), 0)
                self.assertEqual((w.value, h.value), (width, height))
                p.SDL_RenderGetLogicalSize(p.renderer, byref(w), byref(h))
                self.assertEqual((w.value, h.value), (1920, 1080))
                x, y = c_float(), c_float()
                p.SDL_RenderWindowToLogical(p.renderer, width//2, height//2, byref(x), byref(y))
                self.assertAlmostEqual(x.value, 960, places=3)
                self.assertAlmostEqual(y.value, 540, places=3)
            menu.open()
            menu.perform("resolution_1280x720")
            with patch.object(store, 'save', side_effect=OSError('저장 실패')):
                self.assertIsNone(menu.perform("settings_save"))
            self.assertTrue(menu.opened)
            self.assertEqual((canvas.width, canvas.height), (1920, 1080))
            self.assertEqual(store.load().screen_resolution, (1920, 1080))
            menu.cancel()
            menu.open()
            menu.perform("resolution_1280x720")
            menu.perform("settings_save")
            from ferrial_drive.runtime import poll_events
            for event in poll_events(p):
                pass
            for event_type in (p.SDL_MOUSEMOTION, p.SDL_MOUSEBUTTONDOWN, p.SDL_MOUSEBUTTONUP):
                event = p.SDL_Event()
                event.type = event_type
                source = event.motion if event_type == p.SDL_MOUSEMOTION else event.button
                source.windowID, source.x, source.y = p.SDL_GetWindowID(p.window), 640, 360
                if event_type != p.SDL_MOUSEMOTION:
                    source.button = p.SDL_BUTTON_LEFT
                self.assertEqual(p.SDL_PushEvent(byref(event)), 1)
            pointers = [event for event in poll_events(p) if event.type in
                        (p.SDL_MOUSEMOTION, p.SDL_MOUSEBUTTONDOWN, p.SDL_MOUSEBUTTONUP)]
            self.assertEqual(len(pointers), 3)
            self.assertTrue(all((event.x, event.y) == (960, 540) for event in pointers))
            renderer = PicoRenderer({}, {})
            try:
                renderer.clear('#202020')
                image = Path(folder)/'output.png'
                renderer.save_frame(image, 1920, 1080)
                from PIL import Image
                with Image.open(image) as capture:
                    self.assertEqual(capture.size, (1280, 720))
            finally:
                renderer.close()

    def test_shadow_quality_is_independent_of_color_scale(self):
        for quality,scale in (("high",.5),("medium",.25),("low",.125)):
            self.assertEqual(GameSettings(quality).shadow_scale,scale)

    def test_failed_save_keeps_staged_shadows_and_atlas_unchanged(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        app = MovementApplication(ROOT/"samples/sword_movement/movement_config.json")
        app.game_settings = GameSettings("low")
        app.quality_atlas,app.pico = True,None
        app.motion_sprite = app.attack_sprite = previous = Mock()
        events = []
        @contextmanager
        def staged(scale):
            events.append(("prepare",scale))
            try:
                yield lambda: events.append(("apply",scale))
            finally:
                events.append(("close",scale))
        shadow = Mock(alpha_layers=("shadow",))
        shadow.prepare_alpha_scale.side_effect = staged
        app.sprites = [shadow]
        candidate = Mock()
        with patch("ferrial_drive.rendering.pico_motion_atlas.PicoAtlasSprite",return_value=candidate):
            with self.assertRaises(OSError):
                with app.prepare_settings(GameSettings("high")):
                    raise OSError("저장 실패")
        self.assertEqual(events,[("prepare",.5),("close",.5)])
        self.assertIs(app.motion_sprite,previous)
        previous.close.assert_not_called()
        candidate.close.assert_called_once()

    def test_shadow_prepare_failure_discards_new_atlas(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        app = MovementApplication(ROOT/"samples/sword_movement/movement_config.json")
        app.game_settings = GameSettings("low")
        app.quality_atlas,app.pico = True,None
        app.motion_sprite = app.attack_sprite = previous = Mock()
        shadow = Mock(alpha_layers=("shadow",))
        shadow.prepare_alpha_scale.side_effect = FileNotFoundError("그림자 데이터 없음")
        app.sprites = [shadow]
        candidate = Mock()
        with patch("ferrial_drive.rendering.pico_motion_atlas.PicoAtlasSprite",return_value=candidate):
            with self.assertRaises(FileNotFoundError):
                with app.prepare_settings(GameSettings("high")):
                    self.fail("준비 실패인데 설정 적용에 진입했다.")
        self.assertIs(app.motion_sprite,previous)
        candidate.close.assert_called_once()

    def test_live_quality_is_staged_then_installed_without_resetting_game(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        app = MovementApplication(ROOT/"samples/sword_movement/movement_config.json")
        app.game_settings = GameSettings("low")
        app.quality_atlas, app.pico = True, None
        previous, candidate = Mock(), Mock()
        app.motion_sprite = app.attack_sprite = previous
        app.combat = Mock()
        state = app.controller.position_m, app.combat
        with patch("ferrial_drive.rendering.pico_motion_atlas.PicoAtlasSprite", return_value=candidate):
            with app.prepare_settings(GameSettings("high")) as apply:
                self.assertIs(app.motion_sprite, previous)
                apply()
        self.assertIs(app.motion_sprite, candidate)
        self.assertIs(app.attack_sprite, candidate)
        self.assertEqual((app.controller.position_m, app.combat), state)
        previous.close.assert_called_once()
        candidate.close.assert_not_called()

    def test_failed_settings_save_discards_staged_quality_and_keeps_previous(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        app = MovementApplication(ROOT/"samples/sword_movement/movement_config.json")
        app.game_settings = GameSettings("low")
        app.quality_atlas, app.pico = True, None
        app.motion_sprite = app.attack_sprite = previous = Mock()
        candidate = Mock()
        store = Mock()
        store.load.return_value = app.game_settings
        store.save.side_effect = OSError("저장 실패")
        menu = GraphicsSettingsMenu(store)
        menu.prepare_apply = app.prepare_settings
        menu.open()
        menu.perform("texture_high")
        with patch("ferrial_drive.rendering.pico_motion_atlas.PicoAtlasSprite", return_value=candidate):
            self.assertIsNone(menu.perform("settings_save"))
        self.assertIs(app.motion_sprite, previous)
        self.assertEqual(app.game_settings.texture_quality, "low")
        self.assertTrue(menu.opened)
        self.assertEqual(menu.error, "저장 실패")
        previous.close.assert_not_called()
        candidate.close.assert_called_once()

    def test_old_settings_default_to_visible_hints_and_toggle_survives_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GameSettingsStore(Path(folder)/"preferences.json")
            store.path.write_text(json.dumps({"version":1, "graphics":{"texture_quality":"medium"},
                                              "interface":{"hud_scale":0.9}}), encoding="utf-8")
            self.assertTrue(store.load().show_key_hints)
            store.save(GameSettings("medium", show_key_hints=False))
            self.assertFalse(GameSettingsStore(store.path).load().show_key_hints)
            data = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(data["interface"]["hud_scale"], 0.9)

    def test_hint_toggle_cancel_save_and_quality_selection_preserve_each_other(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GameSettingsStore(Path(folder)/"preferences.json")
            menu = GraphicsSettingsMenu(store)
            menu.open()
            menu.perform("key_hints_toggle")
            self.assertFalse(menu.draft.show_key_hints)
            menu.cancel()
            self.assertTrue(menu.saved.show_key_hints)
            self.assertFalse(store.path.exists())
            menu.open()
            menu.perform("key_hints_toggle")
            menu.perform("texture_medium")
            self.assertFalse(menu.draft.show_key_hints)
            menu.perform("settings_save")
            self.assertEqual(store.load(), GameSettings("medium", False))
            menu.open()
            menu.perform("key_hints_toggle")
            menu.perform("settings_save")
            self.assertEqual(store.load(), GameSettings("medium", True))

    def test_key_hint_setting_rejects_non_boolean_values(self):
        for value in (0, 1, "false", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GameSettings(show_key_hints=value)

    def test_first_run_is_quarter_resolution_without_creating_file(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GameSettingsStore(Path(folder)/"preferences.json")
            self.assertEqual(store.load().texture_quality, "low")
            self.assertEqual(store.load().texture_scale, 0.25)
            self.assertFalse(store.path.exists())

    def test_each_quality_round_trips_and_preserves_other_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GameSettingsStore(Path(folder)/"preferences.json")
            store.path.write_text(json.dumps({"version": 1, "graphics": {"vsync": True}, "audio": {"volume": 0.5}}), encoding="utf-8")
            for quality, scale in (("high", 0.75), ("medium", 0.5), ("low", 0.25)):
                store.save(GameSettings(quality))
                self.assertEqual(store.load().texture_scale, scale)
                data = json.loads(store.path.read_text(encoding="utf-8"))
                self.assertTrue(data["graphics"]["vsync"])
                self.assertEqual(data["audio"]["volume"], 0.5)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_cancel_does_not_write_draft_but_save_persists_it(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GameSettingsStore(Path(folder)/"preferences.json")
            menu = GraphicsSettingsMenu(store)
            menu.open()
            menu.perform("texture_medium")
            self.assertEqual(menu.draft.texture_quality, "medium")
            menu.cancel()
            self.assertEqual(menu.saved.texture_quality, "low")
            self.assertFalse(store.path.exists())
            menu.open()
            menu.perform("texture_high")
            self.assertEqual(menu.perform("settings_save"), "settings_saved")
            self.assertFalse(menu.opened)
            self.assertEqual(store.load().texture_quality, "high")


class GameSettingsIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS") == "1", "실제 게임 OpenGL 검사는 선택 실행한다.")
    def test_pause_menu_save_and_fresh_process_quality_selection(self):
        if not (ROOT/"data/runtime/textures/sword_all_half_20261113/oodle_75/atlas.json").is_file():
            self.skipTest("기체 품질 후보를 먼저 준비한다.")
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            code = r'''
import json,sys
from pathlib import Path
from types import SimpleNamespace
from ferrial_drive.combat.movement_application import MovementApplication
from ferrial_drive.runtime import run_application
from ferrial_drive.settings import GameSettingsStore,GameSettings
settings=Path(sys.argv[1]);report=Path(sys.argv[2])
GameSettingsStore(settings).save(GameSettings('high'))
class MenuApplication(MovementApplication):
 def click(self,button):
  x=button.rect.x+button.rect.width/2;y=button.rect.y+button.rect.height/2
  for event_type in (self.pico.SDL_MOUSEBUTTONDOWN,self.pico.SDL_MOUSEBUTTONUP):
   self.handle_event(SimpleNamespace(type=event_type,button=self.pico.SDL_BUTTON_LEFT,x=x,y=y))
 def update(self,dt):
  super().update(dt)
  p=self.pico
  if self.frame==1:
   self.paused=False
   self.handle_event(SimpleNamespace(type=p.SDL_KEYDOWN,key=p.SDLK_ESCAPE))
   assert self.paused
   self.click(next(b for b in self.hud.config.buttons['pause'] if b.action=='settings'))
   assert self.hud.graphics_settings.opened
   self.handle_event(SimpleNamespace(type=p.SDL_KEYDOWN,key=p.SDLK_w))
   assert 'w' not in self.keys
   self.before_position=self.controller.position_m
  elif self.frame==2:
   assert self.controller.position_m==self.before_position
   menu=self.hud.graphics_settings
   self.click(next(b for b in menu.buttons(self.hud.config) if b.action=='texture_medium'))
   self.click(next(b for b in menu.buttons(self.hud.config) if b.action=='settings_save'))
   assert not menu.opened and self.paused
   assert self.settings_store.load().texture_quality=='medium'
   assert self.game_settings.texture_quality=='medium'
   assert all(resource.alpha_scale==0.25 for resource in self.sprites if resource.alpha_layers)
app=MenuApplication('samples/sword_movement/movement_config.json',settings_file=settings,report=report)
run_application(app,width=app.window_size[0],height=app.window_size[1],title='Game Settings Save Contract',frame_limit=3)
'''
            settings = directory/"settings.json"
            first, second = directory/"high.json", directory/"medium.json"
            subprocess.run([sys.executable, "-c", code, str(settings), str(first)], cwd=ROOT, check=True,
                           capture_output=True, text=True, timeout=120)
            subprocess.run([sys.executable, str(ROOT/"tests/sword_movement_test.py"), "--settings-file", str(settings),
                            "--frames", "3", "--report", str(second)], cwd=ROOT, check=True,
                           capture_output=True, text=True, timeout=120)
            high = json.loads(first.read_text(encoding="utf-8"))
            medium = json.loads(second.read_text(encoding="utf-8"))
            self.assertEqual(high["texture_quality"], "medium")
            self.assertEqual(medium["texture_quality"], "medium")
            self.assertTrue(high["quality_atlas"] and medium["quality_atlas"])
            self.assertEqual(high["shadow_scale"],.25)
            self.assertEqual(medium["shadow_scale"],.25)
            self.assertEqual(medium["interpolation_bytes"], high["interpolation_bytes"])

    def test_invalid_settings_are_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"preferences.json"
            path.write_text('{broken', encoding="utf-8")
            with self.assertRaises(ValueError):
                GameSettingsStore(path).load()
            self.assertEqual(path.read_text(encoding="utf-8"), '{broken')
        with self.assertRaises(ValueError):
            GameSettings("unsupported")

    def test_missing_profile_does_not_fall_back_to_other_quality(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"high.json").write_text('{}', encoding="utf-8")
            profiles = {"high": "high.json", "medium": "missing.json"}
            self.assertEqual(resolve_texture_profile(profiles, GameSettings("high"), root), root/"high.json")
            with self.assertRaises(FileNotFoundError):
                resolve_texture_profile(profiles, GameSettings("medium"), root)

    def test_game_menu_buttons_and_hit_regions_use_same_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            config = UiConfig(ROOT/"samples/ui_unit_test_v2/ui_config.json")
            menu = GraphicsSettingsMenu(GameSettingsStore(Path(folder)/"preferences.json"))
            menu.enable_buttons(config)
            for scene in ("menu", "pause"):
                self.assertTrue(next(button for button in config.buttons[scene] if button.action == "settings").enabled)
            menu.open()
            button = next(button for button in menu.buttons(config) if button.action == "texture_medium")
            menu.update(.16)
            x, y = button.rect.x+button.rect.width/2, button.rect.y+button.rect.height/2
            menu.pointer("down", x, y, config)
            menu.pointer("up", x, y, config)
            self.assertEqual(menu.draft.texture_quality, "medium")


if __name__ == "__main__":
    unittest.main()

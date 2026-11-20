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

from ferrial_drive.settings import GameSettings, GameSettingsStore, SCREEN_RESOLUTIONS
from ferrial_drive.ui.settings import GraphicsSettingsMenu
from ferrial_drive.ui.config import UiConfig


def movement_application():
    from ferrial_drive.combat.movement_application import MovementApplication

    app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json")
    app.game_settings = GameSettings("low")
    app.pico = None
    return app


class GameSettingsTests(unittest.TestCase):
    def test_upscale_aa_save_and_rollback_keep_the_active_part_renderer(self):
        app = movement_application()
        app.part_sprite = Mock(data={"upscale_filter": "bounded_bicubic"})
        apply = Mock()

        @contextmanager
        def prepare_aa(mode):
            self.assertEqual(mode, "off")
            yield apply

        app.part_sprite.upscaler.prepare_aa = prepare_aa
        sprite = app.part_sprite
        with tempfile.TemporaryDirectory() as folder:
            store = GameSettingsStore(Path(folder) / "preferences.json")
            store.path.write_text('{"version": 1, "graphics": {"texture_quality": "low"}}', encoding="utf-8")
            menu = GraphicsSettingsMenu(store)
            menu.enable_buttons(UiConfig(ROOT / "samples/ui_unit_test_v2/ui_config.json"))
            menu.prepare_apply = app.prepare_settings
            self.assertEqual(menu.saved.upscale_aa, "smaa")
            menu.open()
            menu.perform("upscale_aa_off")
            self.assertFalse(menu.requires_restart)
            with patch.object(store, "save", side_effect=OSError("저장 실패")):
                self.assertIsNone(menu.perform("settings_save"))
            apply.assert_not_called()
            self.assertEqual(app.game_settings.upscale_aa, "smaa")
            self.assertEqual(menu.perform("settings_save"), "settings_saved")
            self.assertIs(app.part_sprite, sprite)
            apply.assert_called_once_with()
            self.assertEqual(store.load().upscale_aa, "off")
            self.assertEqual(app.game_settings.upscale_aa, "off")
        with self.assertRaises(ValueError):
            GameSettings(upscale_aa="taa")

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

    def test_failed_save_closes_staged_part_quality_and_shadow_without_installing(self):
        app = movement_application()
        app.parts_only = True
        app.part_sprite = live_parts = Mock(direction_enabled=True)
        app.pose_sprite = live_pose = Mock()
        next_parts, next_pose = Mock(), Mock()
        events = []

        @contextmanager
        def staged(scale):
            events.append(("prepare", scale))
            try:
                yield lambda: events.append(("apply", scale))
            finally:
                events.append(("close", scale))

        shadow = Mock(alpha_layers=("shadow",))
        shadow.prepare_alpha_scale.side_effect = staged
        app.sprites = [shadow]
        with patch.object(app, "load_part_profile", return_value=next_parts), \
                patch("ferrial_drive.rendering.pico_pose_table.PicoPoseTable", return_value=next_pose), \
                self.assertRaises(OSError):
            with app.prepare_settings(GameSettings("high")):
                raise OSError("저장 실패")
        self.assertEqual(events, [("prepare", .5), ("close", .5)])
        self.assertIs(app.part_sprite, live_parts)
        self.assertIs(app.pose_sprite, live_pose)
        next_parts.close.assert_called_once()
        next_pose.close.assert_called_once()

    def test_parts_quality_save_failure_leaves_current_renderer_and_direction_mode(self):
        from ferrial_drive.combat.movement_application import MovementApplication

        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json")
        app.game_settings = GameSettings("low")
        app.parts_only = True
        app.pico = None
        app.part_sprite = live_parts = Mock(direction_enabled=False)
        app.pose_sprite = live_pose = Mock()
        next_parts, next_pose = Mock(), Mock()
        with patch.object(app, "load_part_profile", return_value=next_parts), \
                patch("ferrial_drive.rendering.pico_pose_table.PicoPoseTable", return_value=next_pose):
            with self.assertRaises(OSError):
                with app.prepare_settings(GameSettings("high")):
                    self.assertIs(app.part_sprite, live_parts)
                    raise OSError("저장 실패")
        self.assertIs(app.part_sprite, live_parts)
        self.assertIs(app.pose_sprite, live_pose)
        self.assertEqual(app.game_settings.texture_quality, "low")
        self.assertFalse(next_parts.direction_enabled)
        next_parts.close.assert_called_once()
        next_pose.close.assert_called_once()
        live_parts.close.assert_not_called()
        live_pose.close.assert_not_called()

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

    def test_first_run_is_half_resolution_without_creating_file(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GameSettingsStore(Path(folder)/"preferences.json")
            self.assertEqual(store.load().texture_quality, "low")
            self.assertEqual(store.load().texture_scale, 0.5)
            self.assertFalse(store.path.exists())

    def test_each_quality_round_trips_and_preserves_other_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GameSettingsStore(Path(folder)/"preferences.json")
            store.path.write_text(json.dumps({"version": 1, "graphics": {"vsync": True}, "audio": {"volume": 0.5}}), encoding="utf-8")
            for quality, scale in (("high", 1.0), ("medium", 0.75), ("low", 0.5)):
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
        config = ROOT / "samples/sword_movement/movement_config.json"
        profiles = json.loads(config.read_text(encoding="utf-8"))["upper_lower"]["pbr_catalog_profiles"]
        for quality in ("high", "medium"):
            candidates = profiles[quality]
            paths = (candidates,) if isinstance(candidates, str) else candidates
            if not any((config.parent / path).is_file() for path in paths):
                self.skipTest(f"기체 {quality} 품질 카탈로그가 필요하다.")
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
   menu.update(1)
   self.click(next(b for b in menu.buttons(self.hud.config) if b.action=='texture_medium'))
   self.click(next(b for b in menu.buttons(self.hud.config) if b.action=='settings_save'))
   assert not menu.opened and self.paused, menu.error
   assert self.settings_store.load().texture_quality=='medium'
   assert self.game_settings.texture_quality=='medium'
   assert all(resource.alpha_scale==0.25 for resource in self.sprites if resource.alpha_layers)
   self.previous_parts=self.part_sprite
   menu.open()
   menu.update(1)
   self.click(next(b for b in menu.buttons(self.hud.config) if b.action=='upscale_aa_off'))
   assert menu.draft.upscale_aa=='off'
   self.click(next(b for b in menu.buttons(self.hud.config) if b.action=='settings_save'))
   assert not menu.opened and self.part_sprite is self.previous_parts, menu.error
   assert self.game_settings.upscale_aa=='off' and self.part_sprite.upscaler.aa_mode=='off'
app=MenuApplication('samples/sword_movement/movement_config.json',settings_file=settings,report=report,mute=True)
run_application(app,width=app.window_size[0],height=app.window_size[1],title='Game Settings Save Contract',frame_limit=3)
'''
            settings = directory/"settings.json"
            first, second = directory/"high.json", directory/"medium.json"
            changed = subprocess.run([sys.executable, "-c", code, str(settings), str(first)], cwd=ROOT,
                                     capture_output=True, text=True, timeout=120)
            self.assertEqual(changed.returncode, 0, changed.stderr)
            fresh = subprocess.run([sys.executable, str(ROOT/"tests/sword_movement_test.py"), "--settings-file", str(settings),
                                    "--frames", "3", "--report", str(second), "--mute"], cwd=ROOT,
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(fresh.returncode, 0, fresh.stderr)
            high = json.loads(first.read_text(encoding="utf-8"))
            medium = json.loads(second.read_text(encoding="utf-8"))
            self.assertEqual(high["texture_quality"], "medium")
            self.assertEqual(medium["texture_quality"], "medium")
            self.assertEqual(high["part_renderer"]["texture_scale"], 0.75)
            self.assertEqual(medium["part_renderer"]["texture_scale"], 0.75)
            self.assertEqual(high["part_renderer"]["source"], medium["part_renderer"]["source"])
            self.assertEqual(high["shadow_scale"],.25)
            self.assertEqual(medium["shadow_scale"],.25)
            self.assertEqual(medium["part_renderer"]["upscale_aa"], "off")
            self.assertEqual(medium["part_renderer"]["shadow_map"]["ground_map_size"], 128)

    def test_invalid_settings_are_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"preferences.json"
            path.write_text('{broken', encoding="utf-8")
            with self.assertRaises(ValueError):
                GameSettingsStore(path).load()
            self.assertEqual(path.read_text(encoding="utf-8"), '{broken')
        with self.assertRaises(ValueError):
            GameSettings("unsupported")

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

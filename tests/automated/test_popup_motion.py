"""팝업 SmoothStep 등장·재진입·입력 차단을 확인한다."""

from pathlib import Path
import unittest

from ferrial_drive.ui.popup import PopupMotion
from ferrial_drive.ui.settings import GraphicsSettingsMenu
from ferrial_drive.settings import GameSettingsStore
from ferrial_drive.ui.config import UiConfig

ROOT = Path(__file__).resolve().parents[2]


class PopupMotionTests(unittest.TestCase):
    def test_restart_notice_only_tracks_changed_registered_fields(self):
        menu = GraphicsSettingsMenu(GameSettingsStore(ROOT / "output/ui_review/popup_settings.json"))
        config = UiConfig(ROOT / "samples/ui_unit_test_v2/ui_config.json")
        menu.enable_buttons(config)
        menu.open()
        menu.perform("texture_medium")
        self.assertFalse(menu.requires_restart)
        # 향후 재시작 필요 항목이 등록됐을 때의 변경 판정만 독립적으로 확인한다.
        menu.restart_required_fields = ("texture_quality",)
        self.assertTrue(menu.requires_restart)
        menu.perform("texture_low")
        self.assertFalse(menu.requires_restart)
        menu.perform("key_hints_toggle")
        self.assertFalse(menu.requires_restart)

    def test_smoothstep_opacity_and_scale_have_shared_midpoint(self):
        motion = PopupMotion()
        motion.open()
        self.assertEqual(motion.opacity, 0)
        self.assertEqual(motion.scale, .97)
        motion.update(.08)
        self.assertAlmostEqual(motion.opacity, .5)
        self.assertAlmostEqual(motion.scale, .985)
        motion.update(.08)
        self.assertEqual(motion.opacity, 1)
        self.assertEqual(motion.scale, 1)
        self.assertFalse(motion.entering)

    def test_click_is_not_captured_while_panel_is_growing(self):
        menu = GraphicsSettingsMenu(GameSettingsStore(ROOT / "output/ui_review/popup_settings.json"))
        config = UiConfig(ROOT / "samples/ui_unit_test_v2/ui_config.json")
        menu.enable_buttons(config)
        menu.open()
        button = next(button for button in menu.buttons(config) if button.action == "key_hints_toggle")
        point = button.rect.x + 20, button.rect.y + 20
        menu.pointer("down", *point, config)
        menu.update(.2)
        menu.pointer("up", *point, config)
        self.assertTrue(menu.draft.show_key_hints)
        menu.pointer("down", *point, config)
        menu.pointer("up", *point, config)
        self.assertFalse(menu.draft.show_key_hints)
        menu.cancel()
        menu.open()
        self.assertEqual(menu.motion.opacity, 0)
        self.assertEqual(menu.motion.scale, .97)


if __name__ == "__main__":
    unittest.main()

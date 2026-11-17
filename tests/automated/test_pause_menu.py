"""일시정지 호버 전환의 연속성·고정 입력 영역·초기화를 확인한다."""

import unittest

from ferrial_drive.ui.components import Button, ButtonInput, Rect
from ferrial_drive.ui_v2.pause_motion import PauseHoverMotion


class PauseHoverTests(unittest.TestCase):
    def setUp(self):
        self.buttons = (Button("resume", "resume", "계속", Rect(72, 438, 420, 94)),
                        Button("disabled", "settings", "설정", Rect(528, 548, 420, 94), enabled=False))
        self.motion = PauseHoverMotion()

    def update(self, seconds, hovered="resume", *, active=True):
        self.motion.update(seconds, hovered, self.buttons, active=active)

    def test_reversing_mid_slide_preserves_position_and_returns_to_origin(self):
        self.update(.06)
        before = self.motion.visuals["resume"].offset_pixels
        self.assertTrue(-8 < before < 0)
        self.update(0, None)
        self.assertEqual(self.motion.visuals["resume"].offset_pixels, before)
        self.update(.14, None)
        self.assertEqual(self.motion.visuals["resume"].offset_pixels, 0)

    def test_stationary_pointer_keeps_capture_while_visual_slides(self):
        inputs = ButtonInput()
        box = self.buttons[0].rect
        pointer = (box.x + box.width - 1, box.y + box.height / 2)
        inputs.handle("down", *pointer, self.buttons)
        self.update(.14, inputs.hovered_id)
        self.assertEqual(self.motion.visuals["resume"].offset_pixels, -8)
        self.assertEqual(self.buttons[0].rect, box)
        self.assertEqual(inputs.handle("up", *pointer, self.buttons).action, "resume")

    def test_breathing_changes_light_without_changing_settled_position(self):
        self.update(1.4)
        first = self.motion.visuals["resume"]
        self.update(.7)
        second = self.motion.visuals["resume"]
        self.assertEqual(first.offset_pixels, second.offset_pixels)
        self.assertAlmostEqual(first.light_opacity, 1)
        self.assertAlmostEqual(second.light_opacity, .35)

    def test_disabled_and_closed_menu_have_no_lingering_hover(self):
        self.update(.2, "disabled")
        self.assertEqual(self.motion.visuals["disabled"].hover_ratio, 0)
        self.update(.2)
        self.update(.2, active=False)
        self.assertEqual(self.motion.visuals, {})
        self.update(0, None)
        self.assertEqual(self.motion.visuals["resume"].offset_pixels, 0)


if __name__ == "__main__":
    unittest.main()

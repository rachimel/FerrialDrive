"""장면 표시와 별개로 확인하는 시간·좌표·입력 계약."""

import sys
import unittest

from ferrial_drive.animation import ScalarAnimation, smooth_step
from ferrial_drive.ui.components import Button, ButtonInput, Rect


class AnimationTests(unittest.TestCase):
    def test_frame_rate_independent_progress(self):
        values = []
        for fps in (30, 60, 144):
            animation = ScalarAnimation(-30, 70, 1)
            for _ in range(fps // 2):
                animation.update(1 / fps)
            values.append(animation.value)
        for value in values:
            self.assertAlmostEqual(value, 20)

    def test_zero_duration_and_oversized_frame_finish_at_target(self):
        self.assertEqual(ScalarAnimation(0, 1, 0).value, 1)
        animation = ScalarAnimation(0, 1, 0.2)
        self.assertEqual(animation.update(10), 1)
        self.assertTrue(animation.finished)

    def test_invalid_time_is_rejected(self):
        for duration in (-1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                ScalarAnimation(0, 1, duration)
        with self.assertRaises(ValueError):
            ScalarAnimation(0, 1, 1).update(-1)

    def test_smoothstep_has_bounded_endpoints(self):
        self.assertEqual(smooth_step(-1), 0)
        self.assertEqual(smooth_step(2), 1)
        self.assertAlmostEqual(smooth_step(0.5), 0.5)


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.button = Button("test", "original_action", "표시명", Rect(20, 40, 100, 30), 4)
        self.inputs = ButtonInput()

    def test_animated_position_and_padding_are_used_for_hit(self):
        self.assertFalse(self.inputs.handle("down", 18, 50, [self.button], 50).consumed)
        self.assertTrue(self.inputs.handle("down", 68, 50, [self.button], 50).consumed)
        result = self.inputs.handle("up", 68, 50, [self.button], 50)
        self.assertEqual(result.action, "original_action")

    def test_dragging_out_consumes_release_without_activation(self):
        self.inputs.handle("down", 50, 50, [self.button])
        result = self.inputs.handle("up", 400, 400, [self.button])
        self.assertTrue(result.consumed)
        self.assertIsNone(result.action)

    def test_release_without_press_does_not_activate(self):
        self.assertIsNone(self.inputs.handle("up", 50, 50, [self.button]).action)

    def test_reset_cancels_capture(self):
        self.inputs.handle("down", 50, 50, [self.button])
        self.inputs.reset()
        self.assertIsNone(self.inputs.handle("up", 50, 50, [self.button]).action)

    def test_import_has_no_rendering_dependency(self):
        self.assertNotIn("pico2d", sys.modules)


if __name__ == "__main__":
    unittest.main()

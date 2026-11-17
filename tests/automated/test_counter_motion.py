"""HIT·DAMAGE 표시의 수명·연타·초기화를 검사한다."""

import unittest

from ferrial_drive.ui_v2.counter_motion import CounterMotion


class CounterMotionTests(unittest.TestCase):
    def test_enter_hold_exit_and_hidden(self):
        motion = CounterMotion()
        self.assertEqual(motion.visual.fraction, 0)
        motion.update(1, 0)
        start = motion.visual
        motion.update(1, 0.12)
        middle = motion.visual
        self.assertTrue(middle.entering)
        self.assertGreater(middle.fraction, start.fraction)
        self.assertLess(middle.offset_x, start.offset_x)
        self.assertGreater(middle.label_spacing_pixels, start.label_spacing_pixels)
        motion.update(1, 0.13)
        self.assertEqual(motion.visual.fraction, 1)
        motion.update(1, 2.6)
        self.assertTrue(motion.visual.exiting)
        self.assertGreater(motion.visual.fraction, 0)
        self.assertLess(motion.visual.fraction, 1)
        motion.update(1, 0.3)
        self.assertEqual(motion.visual.fraction, 0)

    def test_continuous_hits_extend_hold_without_replaying_entry(self):
        motion = CounterMotion()
        motion.update(1, 0.3)
        motion.update(1, 2)
        motion.update(2, 0.1)
        self.assertFalse(motion.visual.entering)
        self.assertEqual(motion.visual.fraction, 1)
        motion.update(2, 2)
        self.assertFalse(motion.visual.exiting)

    def test_hit_during_exit_reenters_and_reset_hides(self):
        motion = CounterMotion()
        motion.reset(9)
        motion.update(9, 2.6)
        self.assertTrue(motion.visual.exiting)
        motion.update(10, 0.1)
        self.assertTrue(motion.visual.entering)
        motion.update(0, 0)
        self.assertEqual(motion.visual.fraction, 0)

    def test_zero_time_preserves_animation(self):
        motion = CounterMotion()
        motion.update(1, 0.1)
        visual = motion.visual
        motion.update(1, 0)
        self.assertEqual(motion.visual, visual)

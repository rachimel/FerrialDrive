"""록온 곡선·동시 교체·현재 상태 기반 퇴장·외곽 순환을 검사한다."""

import unittest
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui_v2.lock_on import LockOnMotion, cubic, emphasized, elastic_out, outline_point, outline_segment


class LockOnTests(unittest.TestCase):
    def test_zero_hold_restarts_immediately_without_changing_easing(self):
        motion = LockOnMotion(move_seconds=0.5, hold_seconds=0)
        motion.select('a', Rect(0, 0, 20, 20))
        motion.update(motion.enter_seconds + motion.label_seconds + motion.move_seconds)
        boundary = motion.visuals[0].border_position
        self.assertAlmostEqual(boundary, 5.5)
        motion.update(0.05)
        early = motion.visuals[0].border_position
        self.assertGreater(early, boundary)
        self.assertLess(early - boundary, 0.05)
        motion.update(0.2)
        self.assertAlmostEqual(motion.visuals[0].border_position, 6.5)
        for hold in (-0.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                LockOnMotion(hold_seconds=hold)

    def test_exit_after_frame_entry_uses_normal_exit_even_before_label(self):
        body = Rect(0, 0, 20, 20)
        for elapsed in (0.4, 0.5, 0.6):
            motion = LockOnMotion()
            motion.select("a", body)
            motion.update(elapsed)
            motion.select("b", body)
            self.assertAlmostEqual(motion.tracks[0].exit_start_angle_degrees, 45)
            motion.update(0.125)
            self.assertAlmostEqual(motion.visuals[0].angle_degrees, 67.5)
            self.assertEqual(motion.visuals[0].label_progress, 0)

    def test_marker_uses_square_even_for_non_square_body(self):
        from pathlib import Path
        from math import dist
        from unittest.mock import Mock, patch
        from ferrial_drive.ui.config import UiConfig
        from ferrial_drive.ui_v2.view import UiV2View
        from ferrial_drive.ui_v2.lock_on import LockOnVisual
        config = UiConfig(Path(__file__).resolve().parents[2] / "samples/ui_unit_test_v2/ui_config.json")
        view = UiV2View(config, Mock())
        with patch.object(view, "stroke") as stroke:
            view.lock_marker(LockOnVisual("a", Rect(0, 0, 20, 40), angle_degrees=0, label_progress=0), 1)
        points = stroke.call_args_list[0].args[0]
        lengths = [dist(a, b) for a, b in zip(points, points[1:])]
        self.assertEqual(len(lengths), 4)
        for length in lengths:
            self.assertAlmostEqual(length, lengths[0])
        self.assertEqual(points[0][1], points[1][1])

    def test_curve_endpoints_midpoint_and_elastic_overshoot(self):
        for curve in (emphasized, elastic_out):
            self.assertAlmostEqual(curve(0), 0)
            self.assertAlmostEqual(curve(1), 1)
        self.assertAlmostEqual(emphasized(0.166666), 0.4)
        self.assertGreater(elastic_out(0.2), 1)
        self.assertAlmostEqual(cubic(0.5, 0.42, 0, 0.58, 1), 0.5)

    def test_switch_keeps_old_body_until_exit_and_reveals_new_label_after_entry(self):
        motion = LockOnMotion()
        old, new = Rect(0, 0, 20, 20), Rect(200, 100, 20, 20)
        motion.select("a", old)
        motion.update(0.4)
        self.assertEqual(motion.visuals[0].label_progress, 0)
        motion.update(0.2)
        self.assertAlmostEqual(motion.visuals[0].label_progress, 1)
        motion.select("b", new)
        motion.update(0.125)
        a, b = motion.visuals
        self.assertEqual(a.body, old)
        self.assertEqual(b.body, new)
        self.assertEqual(a.label_progress, 0)
        self.assertAlmostEqual(a.angle_degrees, 67.5)
        self.assertGreater(a.scale, 1)
        self.assertAlmostEqual(a.opacity, 0.5)
        self.assertEqual(b.label_progress, 0)
        motion.update(0.125)
        self.assertEqual([v.target_id for v in motion.visuals], ["b"])

    def test_interrupted_entry_exits_from_current_angle_and_scale_without_reversing(self):
        body = Rect(0, 0, 20, 20)
        motion = LockOnMotion()
        motion.select("a", body)
        for elapsed in (0, 0.04, 0.08, 0.16, 0.3):
            motion.reset("a", body)
            motion.update(elapsed)
            before = motion.visuals[0]
            motion.select("b", body)
            self.assertEqual(motion.visuals[0], before)
            motion.update(0.125)
            during = motion.visuals[0]
            self.assertAlmostEqual(during.angle_degrees, before.angle_degrees * 1.5)
            self.assertGreater(during.scale, before.scale)
            self.assertAlmostEqual(during.opacity, 0.5)
            motion.tracks[0].exit_age = 0.25
            end = motion.visuals[0]
            self.assertAlmostEqual(end.angle_degrees, before.angle_degrees * 2)
            self.assertAlmostEqual(end.scale, before.scale * motion.exit_scale)
            self.assertEqual(end.opacity, 0)
            motion.update(0)
            self.assertEqual([v.target_id for v in motion.visuals], ["b"])

    def test_opposed_segments_swap_places_along_outline_then_pause(self):
        points = ((0, -10), (10, 0), (0, 10), (-10, 0))
        self.assertEqual(outline_segment(points, 3.8, 0.65)[1], points[0])
        for position in (0.1, 0.5, 0.9, 1.2):
            a, b = outline_point(points, position), outline_point(points, position + 2)
            self.assertAlmostEqual(a[0], -b[0])
            self.assertAlmostEqual(a[1], -b[1])
        motion = LockOnMotion()
        motion.select("a", Rect(0, 0, 20, 20))
        motion.update(0.6)
        self.assertAlmostEqual(motion.visuals[0].border_position, 3.5)
        motion.update(0.2)
        self.assertAlmostEqual(motion.visuals[0].border_position, 4.5)
        motion.update(0.2)
        self.assertAlmostEqual(motion.visuals[0].border_position, 5.5)
        motion.update(0.2)
        self.assertAlmostEqual(motion.visuals[0].border_position, 5.5)


if __name__ == "__main__":
    unittest.main()

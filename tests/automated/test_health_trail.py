"""체력 감소 효과의 연속 피격·가속·표시 초기화 계약. 실행 결과와 구분한다."""

import unittest

from ferrial_drive.ui.health import HealthTrail


class HealthTrailTests(unittest.TestCase):
    def test_hit_during_animation_preserves_visible_endpoint_and_restarts_time(self):
        trail = HealthTrail(1.0, 1.0)
        trail.set_ratio(0.7)
        trail.update(0.4)
        before = trail.trailing_ratio
        trail.set_ratio(0.3)
        self.assertEqual(trail.trailing_ratio, before)
        self.assertEqual(trail.target_ratio, 0.3)
        self.assertEqual(trail.animation.elapsed_seconds, 0)
        trail.update(0.2)
        self.assertLess(trail.trailing_ratio, before)
        self.assertGreaterEqual(trail.trailing_ratio, trail.target_ratio)

    def test_unchanged_health_does_not_restart_time(self):
        trail = HealthTrail(1.0, 1.0)
        trail.set_ratio(0.5)
        trail.update(0.4)
        position = trail.trailing_ratio
        trail.set_ratio(0.5)
        self.assertEqual(trail.trailing_ratio, position)
        self.assertEqual(trail.animation.elapsed_seconds, 0.4)

    def test_later_equal_time_interval_moves_faster_and_death_finishes_at_zero(self):
        trail = HealthTrail(1.0, 1.0)
        trail.set_ratio(0.0)
        trail.update(0.25)
        first_position = trail.trailing_ratio
        first_distance = 1.0 - first_position
        trail.update(0.25)
        second_distance = first_position - trail.trailing_ratio
        self.assertGreater(second_distance, first_distance)
        trail.update(2.0)
        self.assertEqual(trail.trailing_ratio, 0.0)

    def test_recovery_and_reset_clear_old_loss_region(self):
        trail = HealthTrail(1.0, 1.0)
        trail.set_ratio(0.3)
        trail.update(0.2)
        trail.set_ratio(0.7)
        self.assertEqual(trail.trailing_ratio, 0.7)
        trail.set_ratio(0.1)
        trail.reset(0.9)
        trail.update(0.3)
        self.assertEqual(trail.trailing_ratio, 0.9)


if __name__ == "__main__":
    unittest.main()

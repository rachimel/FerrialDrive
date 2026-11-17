"""상체 보간·하체 여유각과 정렬까지의 추종을 검사한다."""

import unittest

from ferrial_drive.combat.aim_follow import AimFollow, AimFollowSettings, angle_delta_degrees


class AimFollowTest(unittest.TestCase):
    def make_follow(self, yaw=0):
        return AimFollow(AimFollowSettings(.12, .24), yaw_degrees=yaw)

    def test_upper_interpolates_and_lower_waits_inside_margin(self):
        follow = self.make_follow()
        follow.update(1 / 60, 30)
        self.assertGreater(follow.upper_yaw_degrees, 0)
        self.assertLess(follow.upper_yaw_degrees, 30)
        follow.update(2, 30)
        self.assertAlmostEqual(follow.upper_yaw_degrees, 30, places=5)
        self.assertEqual(follow.lower_yaw_degrees, 0)
        self.assertFalse(follow.lower_following)

    def test_lower_continues_beyond_reentry_and_settles_towards_upper(self):
        follow = self.make_follow()
        entered = False
        for _ in range(240):
            follow.update(1 / 120, 90)
            if follow.lower_following and abs(follow.relative_yaw_degrees) < 40:
                entered = True
        self.assertTrue(entered)
        self.assertLess(abs(follow.relative_yaw_degrees), .1)
        self.assertGreater(follow.lower_yaw_degrees, 89)
        self.assertFalse(follow.lower_following)

    def test_shortest_arc_wrap_and_reverse_while_following(self):
        follow = self.make_follow(179)
        follow.update(.2, -179)
        self.assertLess(abs(angle_delta_degrees(-179, follow.upper_yaw_degrees)), 1)
        self.assertEqual(follow.lower_yaw_degrees, 179)
        follow.update(.1, 90)
        follow.update(3, -90)
        self.assertLess(abs(angle_delta_degrees(-90, follow.upper_yaw_degrees)), .1)
        self.assertLess(abs(follow.relative_yaw_degrees), .1)

    def test_frame_rates_have_same_follow_order_and_close_directions(self):
        results = []
        for fps in (30, 60, 144):
            follow = self.make_follow()
            for target, seconds in ((30, .5), (90, .5), (-90, .5)):
                for _ in range(round(seconds * fps)):
                    follow.update(1 / fps, target)
            results.append((follow.upper_yaw_degrees, follow.lower_yaw_degrees))
        for upper, lower in results[1:]:
            self.assertLess(abs(angle_delta_degrees(upper, results[0][0])), .01)
            self.assertLess(abs(angle_delta_degrees(lower, results[0][1])), .5)

    def test_reset_pause_and_invalid_input(self):
        follow = self.make_follow()
        follow.update(0, 90)
        self.assertEqual(follow.upper_yaw_degrees, 0)
        follow.update(.5, 90)
        follow.reset(20)
        self.assertEqual(follow.upper_yaw_degrees, 20)
        self.assertEqual(follow.lower_yaw_degrees, 20)
        self.assertFalse(follow.lower_following)
        for delta, target in ((-1, 0), (float('nan'), 0), (0, float('inf'))):
            with self.assertRaises(ValueError):
                follow.update(delta, target)
        with self.assertRaises(ValueError):
            AimFollowSettings(0, .2)


if __name__ == "__main__":
    unittest.main()

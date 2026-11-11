"""월드/화면 변환·시선 카메라·최근접 자동 선택의 대기 경계를 검사한다."""

import unittest
from math import hypot

from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.combat.mouse_targeting import MouseAutoTargeting
from ferrial_drive.combat.targeting import TargetCandidate


class CameraTargetingTests(unittest.TestCase):
    def test_camera_deadzone_direction_limit_and_inverse_transform(self):
        camera = LookAheadCamera(1280, 720)
        player = (1000, 2000)
        camera.reset(player)
        camera.update(player, (720, 360), 1)
        self.assertEqual(camera.position, player)
        camera.update(player, (0, 0), 3)
        self.assertLess(camera.position[0], player[0])
        self.assertLess(camera.position[1], player[1])
        self.assertLessEqual(hypot(*(a - b for a, b in zip(camera.position, player))), 120)
        point = (725, 1830)
        restored = camera.screen_to_world(camera.world_to_screen(point))
        for a, b in zip(point, restored):
            self.assertAlmostEqual(a, b)
        screen_player = camera.world_to_screen(player)
        self.assertGreater(screen_player[0], 640)
        self.assertGreater(screen_player[1], 360)

    def test_camera_smoothing_matches_split_updates_and_returns_without_mouse(self):
        a, b = LookAheadCamera(1280, 720), LookAheadCamera(1280, 720)
        for camera in (a, b):
            camera.reset((640, 360))
        a.update((640, 360), (1000, 360), 1)
        for _ in range(60):
            b.update((640, 360), (1000, 360), 1 / 60)
        self.assertAlmostEqual(a.position[0], b.position[0])
        a.update((640, 360), None, 3)
        self.assertAlmostEqual(a.position[0], 640, places=5)

    def test_new_closest_enemy_waits_a_full_second_from_first_observation(self):
        targeting = MouseAutoTargeting(330, 460)
        targeting.reset("a")
        a = TargetCandidate("a", (100, 0))
        b = TargetCandidate("b", (200, 0))
        self.assertEqual(targeting.update((a, b), (0, 0), (200, 0), 5), "a")
        self.assertEqual(targeting.pending_seconds, 0)
        self.assertEqual(targeting.update((a, b), (0, 0), (200, 0), 0.99), "a")
        self.assertEqual(targeting.update((a, b), (0, 0), (200, 0), 0.01), "b")

    def test_changing_best_candidate_restarts_margin_and_invalid_current_clears(self):
        targeting = MouseAutoTargeting(330, 460)
        targeting.reset("a")
        entries = (TargetCandidate("a", (100, 0)), TargetCandidate("b", (200, 0)))
        targeting.update(entries, (0, 0), (200, 0), 0)
        targeting.update(entries, (0, 0), (200, 0), 0.8)
        targeting.update(entries, (0, 0), (100, 0), 0.1)
        self.assertIsNone(targeting.pending_id)
        targeting.update(entries, (0, 0), (200, 0), 0.8)
        self.assertEqual(targeting.pending_seconds, 0)
        self.assertIsNone(targeting.update(entries[1:], (0, 0), (200, 0), 0.2))
        self.assertEqual(targeting.selected_id, None)

    def test_world_mouse_distance_and_player_range_are_separate(self):
        targeting = MouseAutoTargeting(330, 460)
        entries = (TargetCandidate("near", (100, 100)), TargetCandidate("aim", (400, 0)))
        targeting.update(entries, (0, 0), (400, 0), 0)
        self.assertEqual(targeting.pending_id, "near")
        targeting.update(entries, (0, 0), (400, 0), 0, aiming=True)
        self.assertEqual(targeting.pending_id, "aim")
        targeting.update(entries, (0, 0), (400, 0), 1, aiming=True)
        self.assertEqual(targeting.selected_id, "aim")
        self.assertIsNone(targeting.update(entries, (0, 0), (400, 0), 0, aiming=False))

    def test_auto_selection_depends_on_mouse_position_not_just_angle(self):
        targeting = MouseAutoTargeting(330, 460, switch_margin_seconds=0)
        entries = (TargetCandidate("near", (100, 0)), TargetCandidate("far", (300, 0)))
        self.assertEqual(targeting.update(entries, (0, 0), (110, 0), 0), "near")
        self.assertEqual(targeting.update(entries, (0, 0), (290, 0), 0), "far")


if __name__ == "__main__":
    unittest.main()

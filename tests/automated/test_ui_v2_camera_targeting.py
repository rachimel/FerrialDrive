"""월드/화면 변환·시선 카메라·최근접 자동 선택의 대기 경계를 검사한다."""

import unittest
from math import hypot

from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.combat.mouse_targeting import MouseAutoTargeting
from ferrial_drive.combat.targeting import TargetCandidate


class CameraTargetingTests(unittest.TestCase):
    def test_separate_acquisition_and_release_boundaries(self):
        targeting = MouseAutoTargeting(200, 300, release_range_units=400)
        for aiming, acquire in ((False, 200), (True, 300)):
            for distance, expected in ((acquire + 0.001, None), (acquire, "a")):
                targeting.reset()
                candidates = (TargetCandidate("a", (distance, 0)),)
                self.assertEqual(targeting.update(candidates, (0, 0), (distance, 0), 0, aiming=aiming), expected)
            for distance in (350, 400):
                candidates = (TargetCandidate("a", (distance, 0)),)
                self.assertEqual(targeting.update(candidates, (0, 0), (distance, 0), 0, aiming=aiming), "a")
            candidates = (TargetCandidate("a", (400.001, 0)),)
            self.assertIsNone(targeting.update(candidates, (0, 0), (400, 0), 0, aiming=aiming))
            # 해제된 뒤에는 유지 범위에만 있는 적을 다시 획득하지 않는다.
            candidates = (TargetCandidate("a", (350, 0)),)
            self.assertIsNone(targeting.update(candidates, (0, 0), (350, 0), 0, aiming=aiming))

    def test_aim_release_keeps_lock_and_switch_only_uses_acquisition_candidates(self):
        targeting = MouseAutoTargeting(200, 300, release_range_units=400)
        candidates = (TargetCandidate("a", (250, 0)),)
        self.assertEqual(targeting.update(candidates, (0, 0), (250, 0), 0, aiming=True), "a")
        self.assertEqual(targeting.update(candidates, (0, 0), (250, 0), 0, aiming=False), "a")
        candidates += (TargetCandidate("b", (280, 0)),)
        self.assertEqual(targeting.update(candidates, (0, 0), (280, 0), 2), "a")
        self.assertIsNone(targeting.pending_id)
        targeting.update(candidates, (0, 0), (280, 0), 0, aiming=True)
        self.assertEqual(targeting.update(candidates, (0, 0), (280, 0), 0.99, aiming=True), "a")
        self.assertEqual(targeting.update(candidates, (0, 0), (280, 0), 0.01, aiming=True), "b")

    def test_range_metric_is_independent_of_cursor_metric(self):
        targeting = MouseAutoTargeting(200, 300, release_range_units=400)
        candidates = (TargetCandidate("a", (10000, 0)), TargetCandidate("b", (1, 0)))
        self.assertEqual(targeting.update(candidates, (0, 0), (10000, 0), 0,
                                         range_distances={"a": 200, "b": 300}), "a")
        with self.assertRaises(ValueError):
            targeting.update(candidates, (0, 0), (0, 0), 0, range_distances={"a": 10})
        for bad in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                targeting.update(candidates[:1], (0, 0), (0, 0), 0, range_distances={"a": bad})
        with self.assertRaises(ValueError):
            MouseAutoTargeting(200, 300, release_range_units=299)

    def test_camera_velocity_tracks_displacement_and_clears_on_reset_or_zero_time(self):
        camera = LookAheadCamera(1920, 1080)
        camera.reset((640, 360))
        camera.update((640, 360), (1500, 540), 0.02)
        self.assertAlmostEqual(camera.velocity_pixels_per_second[0], (camera.position[0] - 640) / 0.02)
        self.assertEqual(camera.velocity_pixels_per_second[1], 0)
        camera.update((640, 360), (1500, 540), 0)
        self.assertEqual(camera.velocity_pixels_per_second, (0, 0))
        camera.reset((640, 360))
        self.assertEqual(camera.velocity_pixels_per_second, (0, 0))

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
        self.assertEqual(targeting.update(entries[1:], (0, 0), (200, 0), 0.2), "b")
        self.assertIsNone(targeting.pending_id)
        self.assertIsNone(targeting.update((), (0, 0), (200, 0), 0))

    def test_world_mouse_distance_and_player_range_are_separate(self):
        targeting = MouseAutoTargeting(330, 460)
        entries = (TargetCandidate("near", (100, 100)), TargetCandidate("aim", (400, 0)))
        targeting.update(entries, (0, 0), (400, 0), 0)
        self.assertEqual(targeting.selected_id, "near")
        self.assertIsNone(targeting.pending_id)
        targeting.update(entries, (0, 0), (400, 0), 0, aiming=True)
        self.assertEqual(targeting.pending_id, "aim")
        targeting.update(entries, (0, 0), (400, 0), 1, aiming=True)
        self.assertEqual(targeting.selected_id, "aim")
        self.assertEqual(targeting.update(entries, (0, 0), (400, 0), 0, aiming=False), "near")

    def test_initial_acquisition_is_immediate_and_range_exit_clears(self):
        targeting = MouseAutoTargeting(330, 460)
        entries = (TargetCandidate("a", (100, 0)),)
        self.assertEqual(targeting.update(entries, (0, 0), (100, 0), 0), "a")
        self.assertIsNone(targeting.update(entries, (500, 0), (100, 0), 0))
        self.assertIsNone(targeting.pending_id)
        self.assertEqual(targeting.update(entries, (0, 0), (100, 0), 0), "a")

    def test_locked_camera_centers_midpoint_independent_of_cursor_and_frame_rate(self):
        cameras = []
        for fps in (30, 60, 144):
            camera = LookAheadCamera(1280, 720)
            camera.reset((0, 0))
            for _ in range(fps):
                camera.update((0, 0), (-1000, 1000), 1 / fps, focus_world=(400, 200))
            cameras.append(camera)
        for camera in cameras[1:]:
            for a, b in zip(camera.position, cameras[0].position):
                self.assertAlmostEqual(a, b)
        camera = cameras[0]
        camera.update((0, 0), None, 3, focus_world=(400, 200))
        self.assertAlmostEqual(camera.position[0], 200, places=5)
        self.assertAlmostEqual(camera.position[1], 100, places=5)
        a, b = camera.world_to_screen((0, 0)), camera.world_to_screen((400, 200))
        self.assertAlmostEqual((a[0] + b[0]) / 2, camera.screen_center[0], places=5)
        camera.update((0, 0), None, 3)
        self.assertAlmostEqual(camera.position[0], 0, places=5)

    def test_auto_selection_depends_on_mouse_position_not_just_angle(self):
        targeting = MouseAutoTargeting(330, 460, switch_margin_seconds=0)
        entries = (TargetCandidate("near", (100, 0)), TargetCandidate("far", (300, 0)))
        self.assertEqual(targeting.update(entries, (0, 0), (110, 0), 0), "near")
        self.assertEqual(targeting.update(entries, (0, 0), (290, 0), 0), "far")


if __name__ == "__main__":
    unittest.main()

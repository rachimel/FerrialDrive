"""거리·각도 우선 획득과 R 순환 이력의 동작 계약."""

from math import cos, radians, sin
import unittest

from ferrial_drive.combat.targeting import TargetAcquisition, TargetCandidate


class TargetAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.selection = TargetAcquisition(100, 150, 1)

    def test_direction_precedes_distance_and_ties_prefer_nearer_target(self):
        candidates = (TargetCandidate("near", (30, 30)), TargetCandidate("aligned", (90, 0)))
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (100, 0)), "aligned")
        self.selection.clear()
        candidates = (TargetCandidate("far", (90, 0)), TargetCandidate("near", (40, 0)))
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (100, 0)), "near")

    def test_close_angles_use_configured_tolerance(self):
        candidates = (TargetCandidate("aligned", (90, 0)),
                      TargetCandidate("near", (40 * cos(radians(0.5)), 40 * sin(radians(0.5)))))
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (100, 0)), "near")

    def test_range_and_aim_expansion_include_exact_boundary(self):
        candidates = (TargetCandidate("edge", (100, 0)), TargetCandidate("aim_only", (150, 0)),
                      TargetCandidate("outside", (151, 0)))
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (100, 0)), "edge")
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (100, 0), aiming=True), "aim_only")
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (100, 0), aiming=True), "edge")

    def test_no_candidate_clears_history(self):
        candidate = TargetCandidate("a", (50, 0))
        self.selection.acquire((candidate,), (0, 0), (100, 0))
        self.assertIsNone(self.selection.acquire((TargetCandidate("far", (200, 0)),), (0, 0), (100, 0)))
        self.assertFalse(self.selection.acquired_ids)

    def test_same_press_restarts_cycle_and_reranks_with_current_cursor(self):
        candidates = (TargetCandidate("right", (50, 0)), TargetCandidate("up", (0, -50)),
                      TargetCandidate("left", (-50, 0)))
        self.assertEqual([self.selection.acquire(candidates, (0, 0), (100, 0)) for _ in range(3)],
                         ["right", "up", "left"])
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (0, -100)), "up")
        self.assertEqual(self.selection.acquired_ids, {"up"})

    def test_only_current_candidates_determine_cycle_exhaustion(self):
        self.selection.acquired_ids.update(("gone", "right"))
        candidates = (TargetCandidate("right", (50, 0)), TargetCandidate("up", (0, -50)))
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (100, 0)), "up")
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (100, 0)), "right")

    def test_zero_cursor_direction_uses_distance_and_duplicate_ids_are_rejected(self):
        candidates = (TargetCandidate("far", (90, 0)), TargetCandidate("near", (-20, 0)))
        self.assertEqual(self.selection.acquire(candidates, (0, 0), (0, 0)), "near")
        with self.assertRaises(ValueError):
            self.selection.acquire((candidates[0], candidates[0]), (0, 0), (100, 0))


if __name__ == "__main__":
    unittest.main()

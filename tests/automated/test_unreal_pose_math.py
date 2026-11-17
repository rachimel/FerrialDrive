"""목표 포즈의 길이·힌지 평면·Unreal 좌표 변환을 검사한다."""
import math
import unittest

from automate.unreal.pose_math import (align_frame, chain_controls, dot, forward_pose,
                                      from_euler, length, rotate, solve_two_bone, sub, to_euler)


class PoseMathTest(unittest.TestCase):
    def test_attachment_projection_rotates_local_point_and_removes_camera_root(self):
        from automate.unreal.project_attachments import projected_offset
        camera = {"position": [10, 0, 0], "target": [0, 0, 1], "width_cm": 10, "size": [100, 100]}
        anchor = {"bone": "gun", "local_cm": [0, 2, 0]}
        row = {"extra_bones": {"gun": {"position_cm": [0, 0, 3], "rotation_xyzw": from_euler([0, 90, 0])}}}
        actual = projected_offset(row, anchor, camera)
        self.assertAlmostEqual(actual[0], 0)
        self.assertAlmostEqual(actual[1], -28 / math.sqrt(1.01))

    def test_unreal_euler_roundtrip_and_axis_signs(self):
        self.assertAlmostEqual(rotate(from_euler([90, 0, 0]), [1, 0, 0])[2], 1)
        for value in ([25, -80, 45], [-40, 130, -95], [0, 179, 0]):
            actual = from_euler(to_euler(from_euler(value)))
            self.assertAlmostEqual(abs(dot(actual, from_euler(value))), 1)

    def test_two_bone_keeps_lengths_and_pole_side(self):
        elbow = solve_two_bone([0, 0, 0], [6, 0, 0], 5, 5, [0, 10, 0])
        self.assertAlmostEqual(length(elbow), 5)
        self.assertAlmostEqual(length(sub([6, 0, 0], elbow)), 5)
        self.assertGreater(elbow[1], 0)
        with self.assertRaises(ValueError):
            solve_two_bone([0, 0, 0], [11, 0, 0], 5, 5, [0, 10, 0])

    def test_frame_alignment_preserves_normal_and_direction(self):
        q = align_frame([1, 0, 0], [0, 0, 1], [0, 1, 0], [1, 0, 0])
        self.assertAlmostEqual(dot(rotate(q, [1, 0, 0]), [0, 1, 0]), 1)
        self.assertAlmostEqual(dot(rotate(q, [0, 0, 1]), [1, 0, 0]), 1)

    def test_chain_moves_target_without_changing_bind_translations(self):
        plan = {"bones": [{"name": "upper", "parent": "Root", "position_cm": [0, 0, 0]},
                          {"name": "lower", "parent": "upper", "position_cm": [3, 4, 0]},
                          {"name": "end", "parent": "lower", "position_cm": [6, 0, 0]}]}
        reference = forward_pose(plan, {})
        controls = {}
        chain_controls(plan, controls, reference, ["upper", "lower", "end"], [0, 6, 0], [-10, 0, 0], [0, 0, 0, 1])
        world = forward_pose(plan, controls)
        self.assertLess(length(sub(world["end"][0], [0, 6, 0])), 1e-8)
        self.assertAlmostEqual(length(sub(world["lower"][0], world["upper"][0])), 5)
        self.assertAlmostEqual(length(sub(world["end"][0], world["lower"][0])), 5)


if __name__ == "__main__":
    unittest.main()

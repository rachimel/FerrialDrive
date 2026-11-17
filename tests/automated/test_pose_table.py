"""저장 자세의 상·하체 회전과 루트·파지 변환을 확인한다."""

import unittest

from automate.unreal.pose_table import turn_pose, upper_bone_names, turned_world
from automate.unreal.pose_math import forward_pose, from_euler, rotate, to_euler, dot


class PoseTableTest(unittest.TestCase):
    def test_vertical_weapon_keeps_orientation_for_all_yaw_roll_combinations(self):
        for pitch in (-90,-89.9999999,89.9999999,90):
            for yaw in range(-180,181,45):
                for roll in (-135,0,45,150):
                    before = from_euler([pitch,yaw,roll])
                    after = from_euler(to_euler(before))
                    self.assertAlmostEqual(abs(dot(before,after)),1,places=12)
    def setUp(self):
        self.plan = {"bones": [{"name": name, "parent": parent, "position_cm": position}
            for name, parent, position in [("Root", None, [0, 0, 0]), ("waist", "Root", [1, 0, 5]),
                ("hand_r", "waist", [3, 0, 5]), ("weapon_sword", "Root", [4, 0, 5]), ("foot_l", "Root", [1, 0, 0])]]}
        self.bones = {row["name"]: {"position_cm": row["position_cm"], "rotation_xyzw": [0, 0, 0, 1]}
                      for row in self.plan["bones"]}
        self.upper = upper_bone_names(self.plan, [{"bone": "weapon_sword", "driver": "hand_r"}])

    def assert_vector(self, a, b):
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=6)

    def test_zero_turn_retains_saved_pose(self):
        pose = forward_pose(self.plan, turn_pose(self.plan, self.bones, self.upper, 0, 0))
        for name, row in self.bones.items():
            self.assert_vector(pose[name][0], row["position_cm"])

    def test_waist_location_uses_lower_rotation_and_grip_uses_upper(self):
        pose = forward_pose(self.plan, turn_pose(self.plan, self.bones, self.upper, 90, -90))
        self.assert_vector(pose["waist"][0], [0, -1, 5])
        self.assert_vector(pose["foot_l"][0], [0, -1, 0])
        self.assert_vector(pose["hand_r"][0], [0, 1, 5])
        self.assert_vector(pose["weapon_sword"][0], [0, 2, 5])
        self.assertIn("weapon_sword", self.upper)

    def test_all_direction_pairs_keep_hand_weapon_distance(self):
        for upper in range(0, 360, 45):
            for lower in range(0, 360, 45):
                pose = forward_pose(self.plan, turn_pose(self.plan, self.bones, self.upper, upper, lower))
                offset = [b-a for a,b in zip(pose["hand_r"][0], pose["weapon_sword"][0])]
                self.assert_vector(offset, rotate(from_euler([0,upper,0]), [1,0,0]))

    def test_implicit_root_and_vertical_weapon_keep_requested_world_quaternions(self):
        self.plan["bones"] = self.plan["bones"][1:]
        self.bones["weapon_sword"]["rotation_xyzw"] = from_euler([90,0,0])
        for upper in range(0,360,45):
            for lower in range(0,360,45):
                controls = turn_pose(self.plan,self.bones,self.upper,upper,lower)
                self.assertIn("Root",controls)
                actual = forward_pose(self.plan,controls)
                expected = turned_world(self.bones,self.upper,upper,lower)
                for bone in expected:
                    self.assert_vector(actual[bone][0],expected[bone][0])
                    self.assertAlmostEqual(abs(dot(actual[bone][1],expected[bone][1])),1,places=10)

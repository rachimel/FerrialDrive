"""막대 다리의 발끝 피벗·회전 목표와 입력 보존을 검사한다."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automate.unreal import pose_targets
from automate.unreal.pose_math import add, forward_pose, length, rotate, sub


class PoseTargetsTest(unittest.TestCase):
    def test_planted_tip_stays_fixed_while_end_rotates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = {"bones": [
                {"name": "pelvis", "parent": "Root", "position_cm": [0, 0, 6]},
                {"name": "upper", "parent": "pelvis", "position_cm": [0, 0, 6]},
                {"name": "lower", "parent": "upper", "position_cm": [3, 0, 2]},
                {"name": "foot", "parent": "lower", "position_cm": [6, 0, 6]},
                {"name": "hand_r", "parent": "pelvis", "position_cm": [0, 3, 6]},
                {"name": "weapon_sword", "parent": "pelvis", "position_cm": [0, 3, 6]}]}
            files = {"rig.json": plan, "idle.json": {"poses": [{"controls": {}}]},
                     "evaluation.json": {"evaluated": [{"bones": {
                         "weapon_sword": {"rotation": [0, 0, 0, 1]}}}]}}
            for name, data in files.items():
                (root/name).write_text(json.dumps(data), encoding="utf-8")
            points = [{"frame": frame, "foot": [6, 0, 6], "foot_rotation_deg": rotation,
                       "foot_contact_cm": [7, 0, 6], "foot_contact_local_cm": [1, 0, 0]}
                      for frame, rotation in ((0, [0, 0, 0]), (4, [-15, 30, 0]))]
            recipe = {"rig_plan": "rig.json", "idle_request": "idle.json",
                      "idle_evaluation": "evaluation.json", "blade_axis_local": [1, 0, 0],
                      "blade_normal_local": [0, 0, 1], "targets": points,
                      "chains": [{"bones": ["upper", "lower", "foot"]}],
                      "frame_count": 4, "bake_substeps": 10,
                      "request": {}, "output": "automate/workspace/demo/create.json"}
            before = {name: (root/name).read_bytes() for name in files}
            with patch.object(pose_targets, "ROOT", root):
                result = pose_targets.create(recipe)
            data = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
            self.assertEqual(len(data["poses"]), 41)
            self.assertEqual(data["bake_substeps"], 10)
            for pose in data["poses"]:
                world = forward_pose(plan, pose["controls"])
                point = add(world["foot"][0], rotate(world["foot"][1], [1, 0, 0]))
                self.assertLess(length(sub(point, [7, 0, 6])), 1e-8)
                self.assertAlmostEqual(length(sub(world["lower"][0], world["upper"][0])), 5)
                self.assertAlmostEqual(length(sub(world["foot"][0], world["lower"][0])), 5)
            self.assertEqual(before, {name: (root/name).read_bytes() for name in files})
            # 이동하는 지지발 목표도 일정한 속도와 높이를 유지한다.
            recipe["output"] = "automate/workspace/demo/linear.json"
            recipe["linear_targets"] = ["foot"]
            recipe["targets"] = [
                {"frame": frame, "foot": [6-frame/4, 0, 6], "foot_rotation_deg": [0, 0, 0],
                 "body": {"pelvis": {"translation_delta_cm": [0, 0, -frame/4]}}}
                for frame in [0, 4]]
            with patch.object(pose_targets, "ROOT", root):
                result = pose_targets.create(recipe)
            data = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
            for pose in data["poses"]:
                foot = forward_pose(plan, pose["controls"])["foot"][0]
                self.assertLess(length(sub(foot, [6-pose["frame"]/4, 0, 6])), 1e-8)


if __name__ == "__main__":
    unittest.main()

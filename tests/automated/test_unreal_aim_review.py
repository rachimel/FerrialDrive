"""기본 골격으로 상하체 분리 요청의 자세·파지·부품 보존을 검사한다."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automate.unreal.aim_review import (aim_controls, local_attachments, motion_controls,
                                      motion_sequence, rigid_attachment, split_body)
from automate.unreal.pose_math import dot, forward_pose, from_euler, qmul, rotate, sub


class AimReviewTest(unittest.TestCase):
    def setUp(self):
        self.plan = {"bones": [
            {"name": "pelvis", "parent": "Root", "position_cm": [0, 0, 3]},
            {"name": "waist", "parent": "pelvis", "position_cm": [0, 0, 4]},
            {"name": "head", "parent": "waist", "position_cm": [0, 0, 6]},
            {"name": "hand_r", "parent": "waist", "position_cm": [1, 1, 5]},
            {"name": "foot", "parent": "pelvis", "position_cm": [1, 1, 0]},
            {"name": "weapon_gun", "parent": "Root", "position_cm": [2, 1, 5]}],
            "parts": [{"id": "a", "bone": "waist"}, {"id": "b", "bone": "pelvis"},
                      {"id": "c", "bone": "hand_r"}, {"id": "d", "bone": "foot"}]}
        self.controls = {"pelvis": {"rotation_delta_deg": [10, 0, 3]},
                         "waist": {"rotation_delta_deg": [5, 12, 7]}}

    def test_upper_yaw_is_world_rotation_and_does_not_accumulate_lower_yaw(self):
        old = forward_pose(self.plan, self.controls)
        new = forward_pose(self.plan, aim_controls(self.plan, self.controls, 60, 20))
        for name, yaw in (("waist", 60), ("head", 60), ("foot", 20)):
            expected = qmul(from_euler([0, yaw, 0]), old[name][1])
            self.assertAlmostEqual(abs(dot(expected, new[name][1])), 1)
        self.assertAlmostEqual(sum(v*v for v in sub(new["head"][0], new["waist"][0])),
                               sum(v*v for v in sub(old["head"][0], old["waist"][0])))
        self.assertEqual(self.controls["waist"]["rotation_delta_deg"], [5, 12, 7])

    def test_rigid_grip_reconstructs_baseline_weapon(self):
        from automate.unreal.pose_math import add
        old = forward_pose(self.plan, self.controls)
        attachment = rigid_attachment(self.plan, self.controls, "weapon_gun", "hand_r")
        expected_position = add(old["hand_r"][0], rotate(old["hand_r"][1], attachment["offset_cm"]))
        expected_rotation = qmul(old["hand_r"][1], attachment["local_rotation_quat"])
        for actual, expected in zip(old["weapon_gun"][0], expected_position):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(abs(dot(old["weapon_gun"][1], expected_rotation)), 1)

    def test_split_preserves_all_parts_and_existing_separate_hands(self):
        result = split_body(self.plan, {"body": ["a", "b", "d"], "right_hand": ["c"]})
        self.assertEqual(result["upper_body"], ["a"])
        self.assertEqual(result["lower_body"], ["b", "d"])
        self.assertEqual(result["right_hand"], ["c"])
        self.assertEqual(sorted(part for parts in result.values() for part in parts), ["a", "b", "c", "d"])

    def test_split_uses_current_bones_for_replaced_part_ids(self):
        result = split_body(self.plan)
        self.assertEqual(result["upper_body"], ["a"])
        self.assertEqual(result["lower_body"], ["b", "d"])
        self.assertEqual(result["right_hand"], ["c"])

    def test_world_grip_becomes_a_stable_local_rotation(self):
        reference = forward_pose(self.plan, self.controls)
        source = [{"bone": "weapon_gun", "driver": "hand_r", "offset_cm": [1, 2, 3],
                   "world_rotation_deg": [20, 60, 10]}]
        result = local_attachments(self.plan, self.controls, source)
        actual = qmul(reference["hand_r"][1], result[0]["local_rotation_quat"])
        self.assertAlmostEqual(abs(dot(actual, from_euler([20, 60, 10]))), 1)
        self.assertNotIn("world_rotation_deg", result[0])
        self.assertEqual(result[0]["offset_cm"], [1, 2, 3])
        self.assertIn("world_rotation_deg", source[0])

    def test_motion_sequence_plays_multiple_sources_and_loops(self):
        source = {"frame_count": 12, "poses": [
            {"frame": 0, "controls": {"foot": {"translation_delta_cm": [0, 0, 0]}}},
            {"frame": 6, "controls": {"foot": {"translation_delta_cm": [0, 2, 1]}}},
            {"frame": 12, "controls": {"foot": {"translation_delta_cm": [0, 0, 0]}}}]}
        other = {"frame_count": 6, "poses": [
            {"frame": 0, "controls": {"foot": {"translation_delta_cm": [0, 0, 0]}}},
            {"frame": 6, "controls": {"foot": {"translation_delta_cm": [3, 0, 0]}}}]}
        sequence = [({"start_frame": 0, "loop": True}, source),
                    ({"start_frame": 24}, other)]
        self.assertEqual(motion_controls(sequence, 18, {})["foot"]["translation_delta_cm"], [0, 2, 1])
        self.assertEqual(motion_controls(sequence, 24, {})["foot"]["translation_delta_cm"], [0, 0, 0])
        self.assertEqual(motion_controls(sequence, 30, {})["foot"]["translation_delta_cm"], [3, 0, 0])

    def test_sequence_rejects_gaps_or_wrong_total_length(self):
        from automate.unreal import aim_review
        source = {"source_mesh": "/Game/Sample", "frame_count": 12, "fps": 12,
                  "poses": [{"frame": n, "controls": self.controls} for n in (0, 12)]}
        with patch.object(aim_review, "read", return_value=source):
            for row in ({"start_frame": 1, "frame_count": 24, "loop": True},
                        {"start_frame": 0, "frame_count": 12, "loop": True},
                        {"start_frame": 0, "frame_count": 24, "loop": False}):
                with self.subTest(row=row), self.assertRaises(ValueError):
                    motion_sequence({"motion_sequence": [{**row, "request": "source.json"}]}, source, 24)

    def test_prepare_preserves_animated_leg_keys_and_clip_boundary_grip(self):
        from automate.unreal import aim_review
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.json").write_text(json.dumps(self.plan), encoding="utf-8")
            middle = {**self.controls, "foot": {"translation_delta_cm": [0, 2, 1]}}
            baseline = {"source_mesh": "/Game/Sample", "frame_count": 12, "fps": 12,
                        "poses": [{"frame": 0, "controls": self.controls},
                                  {"frame": 6, "controls": middle},
                                  {"frame": 12, "controls": self.controls}],
                        "attachments": [{"bone": "weapon_gun", "driver": "hand_r",
                                         "offset_cm": [1, 2, 3], "world_rotation_deg": [10, 20, 30]}]}
            (root / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
            before = (root / "baseline.json").read_bytes()
            request = {"workspace": "automate/workspace/moving", "rig_plan": "plan.json",
                       "baseline_request": "baseline.json", "asset_root": "/Game/MechLab/Moving",
                       "frame_count": 24, "follow": {"upper_response_seconds": .12, "lower_response_seconds": .24},
                       "targets": [{"seconds": 0, "yaw_degrees": 0}],
                       "motion_sequence": [{"request": "baseline.json", "start_frame": 0,
                                            "frame_count": 24, "loop": True}]}
            with patch.object(aim_review, "ROOT", root):
                aim_review.prepare(request)
            batch = json.loads((root / request["workspace"] / "batch.json").read_text())
            a, b = batch["clips"]
            for clip in (a, b):
                self.assertEqual(clip["poses"][60]["controls"]["foot"]["translation_delta_cm"], [0, 2, 1])
                self.assertNotIn("world_rotation_deg", clip["attachments"][0])
            self.assertEqual(a["attachments"], b["attachments"])
            self.assertEqual(a["poses"][-1]["controls"], b["poses"][0]["controls"])
            self.assertEqual((root / "baseline.json").read_bytes(), before)

    def test_prepare_writes_continuous_clips_without_changing_sources(self):
        from automate.unreal import aim_review
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, baseline_path = root / "plan.json", root / "baseline.json"
            plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
            baseline = {"source_mesh": "/Game/Sample", "poses": [{"frame": 0, "controls": self.controls}],
                        "tracking": {"output": "Tools/unreal_pipeline/workspace/original.json"}}
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            before = baseline_path.read_bytes()
            request = {"workspace": "automate/workspace/check", "rig_plan": "plan.json",
                       "baseline_request": "baseline.json", "asset_root": "/Game/MechLab/AimCheck",
                       "frame_count": 24, "follow": {"upper_response_seconds": .12, "lower_response_seconds": .24},
                       "attachments": {"weapon_gun": "hand_r"},
                       "targets": [{"seconds": 0, "yaw_degrees": 90}]}
            with patch.object(aim_review, "ROOT", root):
                result = aim_review.prepare(request)
            output = root / request["workspace"]
            batch = json.loads((output / "batch.json").read_text(encoding="utf-8"))
            a, b = batch["clips"]
            self.assertEqual(a["poses"][-1]["controls"], b["poses"][0]["controls"])
            self.assertEqual(a["attachments"], b["attachments"])
            for clip in batch["clips"]:
                self.assertTrue(Path(clip["tracking"]["output"]).is_relative_to(
                    Path("Tools/unreal_pipeline/workspace/check")))
            self.assertNotEqual(a["tracking"]["output"], b["tracking"]["output"])
            self.assertEqual(result["samples"], 241)
            self.assertEqual(baseline_path.read_bytes(), before)
            groups = json.loads((output / "groups.json").read_text(encoding="utf-8"))
            self.assertEqual(sum(map(len, groups.values())), 4)


if __name__ == "__main__":
    unittest.main()

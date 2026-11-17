"""승강 부품의 모서리 길이·중간 위상·축 뒤집힘 거부를 검사한다."""

import unittest

from automate.unreal.part_deformation import deform_point
from automate.unreal.rig_workspace import axis_bone_weights


class PartDeformationTests(unittest.TestCase):
    def test_skin_weights_reproduce_slide_without_stretching_caps(self):
        binding = {"axis": 2, "knots": [[0, {"base": 1}], [0.2, {"base": 1}],
                    [10, {"tip": 1}], [10.2, {"tip": 1}]]}
        positions = []
        for z in (-1, 0, 0.2, 5.1, 10, 10.2, 11):
            values = axis_bone_weights((3, 4, z), binding)
            self.assertAlmostEqual(sum(values.values()), 1)
            positions.append(z + values.get("tip", 0)*10)
        self.assertAlmostEqual(positions[3], 10.1)
        self.assertAlmostEqual(positions[2]-positions[1], 0.2)
        self.assertAlmostEqual(positions[5]-positions[4], 0.2)
        self.assertEqual(positions[0], -1)
        self.assertEqual(positions[-1], 21)

    def test_invalid_skin_weight_knots_are_rejected(self):
        invalid = [
            {"axis": 3, "knots": [[0, {"a": 1}], [1, {"b": 1}]]},
            {"axis": 0, "knots": [[0, {"a": 1}], [0, {"b": 1}]]},
            {"axis": 0, "knots": [[0, {"a": 0.5}], [1, {"b": 1}]]},
            {"axis": 0, "knots": [[0, {"a": -1, "b": 2}], [1, {"b": 1}]]},
        ]
        for settings in invalid:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                axis_bone_weights((0, 0, 0), settings)

    def test_end_caps_keep_their_length_while_middle_extends(self):
        settings = {"axis_maps": [{"axis": 2, "points": [[0, 0], [0.2, 0.2], [10, 20], [10.2, 20.2]]}]}
        positions = [deform_point((3, 4, z), settings) for z in (0, 0.2, 10, 10.2)]
        self.assertAlmostEqual(positions[1][2]-positions[0][2], 0.2)
        self.assertAlmostEqual(positions[3][2]-positions[2][2], 0.2)
        self.assertAlmostEqual(positions[2][2]-positions[1][2], 19.8)
        self.assertEqual(positions[2][:2], [3, 4])

    def test_mid_phase_and_translation_use_the_same_amount(self):
        settings = {"amount": 0.5, "translation_cm": [0, 39, 104],
                    "axis_maps": [{"axis": 0, "points": [[0, 0], [10, 20]]}]}
        self.assertEqual(deform_point((10, 0, 0), settings), [15, 19.5, 52])
        settings["amount"] = 0
        self.assertEqual(deform_point((10, 0, 0), settings), [10, 0, 0])

    def test_folded_duplicate_and_invalid_axes_are_rejected(self):
        for mapping in ({"axis": 0, "points": [[0, 0], [1, -1]]},
                        {"axis": 0, "points": [[0, 0], [0, 1]]},
                        {"axis": 3, "points": [[0, 0], [1, 1]]}):
            with self.assertRaises(ValueError):
                deform_point((0, 0, 0), {"axis_maps": [mapping]})


if __name__ == "__main__":
    unittest.main()

"""분절 강조선의 길이·빈 간격·굵기 변화와 모서리 연결을 확인한다."""

import unittest

from ferrial_drive.ui_v2.geometry import segmented_stroke_mesh


class SegmentedAccentTests(unittest.TestCase):
    def test_sections_leave_real_gaps_and_taper_from_tail_to_head(self):
        shapes = segmented_stroke_mesh(((0, 0), (100, 0)), 4,
                                       ((0, 0.2, 0.2, 0.3), (0.3, 0.4, 0.4, 0.6), (0.5, 1, 0.7, 1)))
        self.assertEqual(len(shapes), 3)
        self.assertEqual([(shape[0][0], shape[1][0]) for shape in shapes], [(0, 20), (30, 40), (50, 100)])
        self.assertAlmostEqual(shapes[0][0][1] - shapes[0][3][1], 0.8)
        self.assertAlmostEqual(shapes[-1][1][1] - shapes[-1][2][1], 4)

    def test_corner_uses_one_cross_section_and_keeps_global_width(self):
        first, second = segmented_stroke_mesh(((0, 0), (50, 0), (50, 50)), 4, ((0, 1, 0.5, 1),))
        self.assertEqual(first[1], second[0])
        self.assertEqual(first[2], second[3])
        self.assertEqual(first[1], (48.5, 1.5))
        self.assertEqual(first[2], (51.5, -1.5))

    def test_exact_corner_endpoint_duplicates_do_not_create_zero_length_edges(self):
        expected = segmented_stroke_mesh(((0, 0), (20, 0)), 4, ((0, 1, 0.5, 1),))
        self.assertEqual(segmented_stroke_mesh(((0, 0), (0, 0), (20, 0), (20, 0)), 4,
                                              ((0, 1, 0.5, 1),)), expected)
        self.assertEqual(segmented_stroke_mesh(((0, 0), (0, 0)), 4, ((0, 1, 0.5, 1),)), ())

    def test_overlap_and_nonfinite_or_zero_widths_are_rejected(self):
        for sections in (((0, 0.6, 1, 1), (0.5, 1, 1, 1)), ((0, 1, 0, 1),), ((0, 1, 1, float('nan')),)):
            with self.assertRaises(ValueError):
                segmented_stroke_mesh(((0, 0), (20, 0)), 4, sections)


if __name__ == '__main__':
    unittest.main()

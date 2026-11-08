"""기체·프레임·그림자 전체 경계를 공통 정사영 카메라로 맞추는 계산을 검사한다."""

import unittest

from Tools.blender_pipeline.framing import orthographic_fit


class AssetFramingTests(unittest.TestCase):
    def test_tall_model_recenters_without_cropping(self):
        center, scale, depth = orthographic_fit([(-1, 0, -2), (1, 8, 3)], 1, 1, 4.5)
        self.assertEqual(center, (0, 4))
        self.assertGreater(scale, 8)
        self.assertEqual(depth, (-2, 3))

    def test_shadow_and_different_poses_share_one_scale_and_center(self):
        points = [(-1, 0, 0), (1, 3, 2), (7, -2, 0), (-3, 4, 1)]
        center, scale, _ = orthographic_fit(iter(points), 1, 1, 4.5)
        for point in points:
            self.assertLessEqual(abs(point[0] - center[0]), scale * 0.42)
            self.assertLessEqual(abs(point[1] - center[1]), scale * 0.42)

    def test_real_viewport_spans_handle_landscape_and_portrait(self):
        points = [(-4, -2, 0), (4, 2, 0)]
        for width, height in ((1, 0.5), (0.5, 1)):
            with self.subTest(viewport=(width, height)):
                _, scale, _ = orthographic_fit(points, width, height, 1)
                self.assertGreaterEqual(scale * width * 0.84, 8)
                self.assertGreaterEqual(scale * height * 0.84, 4)

    def test_manual_minimum_scale_is_preserved(self):
        _, scale, _ = orthographic_fit([(0, 0, 0), (1, 1, 1)], 1, 1, 20)
        self.assertEqual(scale, 20)

    def test_empty_invalid_points_and_invalid_camera_are_rejected(self):
        for points in ([], [(0, float('nan'), 0)], [(0, 1)]):
            with self.assertRaises(ValueError):
                orthographic_fit(points, 1, 1, 4.5)
        for width, height, minimum in ((0, 1, 4.5), (1, -1, 4.5), (1, 1, float('inf'))):
            with self.assertRaises(ValueError):
                orthographic_fit([(0, 0, 0)], width, height, minimum)


if __name__ == '__main__':
    unittest.main()

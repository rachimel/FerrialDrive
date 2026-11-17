"""실제 OpenGL 빛띠의 연속 감쇠·둥근 끝·마스크 재사용을 확인한다."""

import unittest

import test_directional_blur as blur_tests


class SoftLineTests(unittest.TestCase):
    setUp = blur_tests.DirectionalBlurTests.setUp
    tearDown = blur_tests.DirectionalBlurTests.tearDown
    pixels = blur_tests.DirectionalBlurTests.pixels

    def test_glow_fades_across_width_and_end_without_rectangle_corners(self):
        self.renderer.soft_line((24, 32), (72, 32), '#FFFFFF', width_pixels=16)
        pixels = self.pixels()
        red = lambda x, y: pixels[(y * 96 + x) * 4]
        across = [red(48, y) for y in range(24, 32)]
        end = [red(x, 32) for x in range(16, 25)]
        self.assertEqual(red(16, 24), 0)
        self.assertEqual(red(48, 23), 0)
        self.assertEqual(red(15, 32), 0)
        self.assertLess(across[0], across[-1] * .05)
        self.assertLess(end[0], end[-1] * .05)
        self.assertGreater(across[-1], 240)
        self.assertEqual(across, sorted(across))
        self.assertEqual(end, sorted(end))
        self.assertGreater(len(set(across)), 6)
        self.assertGreater(len(set(end)), 6)

    def test_rotated_translated_and_dimmed_lines_reuse_mask_and_release_it(self):
        r = self.renderer
        r.soft_line((24, 32), (72, 32), '#FFFFFF', width_pixels=16)
        bright = max(self.pixels()[::4])
        r.clear('#000000')
        with r.hud_batch():
            r.soft_line((40, 8), (40, 56), '#FF0000', .5, 16)
        dim = max(self.pixels()[::4])
        self.assertAlmostEqual(dim, bright / 2, delta=2)
        self.assertEqual(len(r.soft_line_textures), 1)
        r.close()
        self.assertFalse(r.soft_line_textures)


if __name__ == '__main__':
    unittest.main()

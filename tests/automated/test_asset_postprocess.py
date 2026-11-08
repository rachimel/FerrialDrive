"""사전 샤프닝의 해상도·투명 경계·원본 보존과 공통 표시 선택을 검사한다."""

from Tools.blender_pipeline.postprocess import sharpen_rgba
import unittest


class AssetPostprocessTests(unittest.TestCase):
    def test_sharpen_increases_local_contrast_without_changing_alpha_or_size(self):
        data = bytes(channel for y in range(5) for x in range(5)
                     for channel in ((120, 120, 120, 255) if (x, y) == (2, 2) else (100, 100, 100, 255)))
        processed = sharpen_rgba(data, 5, 5)
        self.assertEqual(len(processed), len(data))
        self.assertEqual(processed[3::4], data[3::4])
        self.assertGreater(processed[(2 * 5 + 2) * 4], 120)
        self.assertLess(processed[(2 * 5 + 1) * 4], 100)

    def test_invisible_colour_does_not_leak_into_transparent_outline(self):
        data = bytes(channel for y in range(5) for x in range(5)
                     for channel in ((100, 130, 160, 80 if x == 1 else 255)
                                     if 1 <= x <= 3 and 1 <= y <= 3 else (255, 0, 255, 0)))
        processed = sharpen_rgba(data, 5, 5)
        self.assertEqual(processed[3::4], data[3::4])
        for i in range(0, len(data), 4):
            self.assertEqual(processed[i:i + 3], bytes((100, 130, 160)) if data[i + 3] else b'\0\0\0')

    def test_disabled_processing_is_exact_and_invalid_settings_are_rejected(self):
        data = bytes((255, 0, 255, 0, 50, 100, 150, 255))
        self.assertEqual(sharpen_rgba(data, 2, 1, 0), data)
        for amount in (-1, 3, float('nan'), True):
            with self.assertRaises(ValueError):
                sharpen_rgba(data, 2, 1, amount)
        with self.assertRaises(ValueError):
            sharpen_rgba(data, 3, 1)


if __name__ == '__main__':
    unittest.main()

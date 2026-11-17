"""피탄음 추출의 타격 분리·시간 보존과 잘못된 구간 거부를 검사한다."""

from math import inf, nan
import unittest

from automate.sound_effects import SAMPLE_RATE, extract_region


class SoundExtractRegionTests(unittest.TestCase):
    def test_extract_preserves_impulse_positions_and_excludes_next_hit(self):
        samples = [0.0] * SAMPLE_RATE
        samples[4410] = 0.8
        samples[4851] = -0.4
        samples[8820] = 1.0
        result = extract_region(samples, {"start_seconds": 0.09, "end_seconds": 0.18})
        self.assertEqual(len(result), 3969)
        self.assertEqual([i for i, value in enumerate(result) if value], [441, 882])
        self.assertAlmostEqual(result[441], 0.58)
        self.assertAlmostEqual(result[882], -0.29)

    def test_fades_remove_boundary_steps(self):
        result = extract_region([0.5] * SAMPLE_RATE,
                                {"start_seconds": 0.1, "end_seconds": 0.2})
        self.assertEqual(result[0], 0)
        self.assertEqual(result[-1], 0)
        self.assertAlmostEqual(max(result), 0.58)

    def test_rejects_invalid_ranges_nonfinite_values_and_silence(self):
        base = {"start_seconds": 0.1, "end_seconds": 0.2}
        for changes in ({"start_seconds": -0.1}, {"end_seconds": 1.1},
                        {"start_seconds": 0.2}, {"peak": nan}, {"peak": inf},
                        {"fade_in_seconds": 0}, {"fade_out_seconds": 0.2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                extract_region([0.5] * SAMPLE_RATE, base | changes)
        with self.assertRaises(ValueError):
            extract_region([0.0] * SAMPLE_RATE, base)


if __name__ == "__main__":
    unittest.main()

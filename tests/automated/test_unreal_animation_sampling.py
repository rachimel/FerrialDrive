"""중간 키 간격이 한 프레임보다 짧아도 끝 자세와 중앙 보간을 유지한다."""
import unittest

from automate.unreal.animation_clip import sample_controls


class AnimationSamplingTest(unittest.TestCase):
    def test_fractional_interval_reaches_both_keys(self):
        poses = [{"frame": frame, "controls": {"pelvis": {"translation_delta_cm": [value, 0, 0]}}}
                 for frame, value in [(0, 0), (0.1, 10), (0.2, 20)]]
        for frame, expected in [(0, 0), (0.05, 5), (0.1, 10), (0.15, 15), (0.2, 20)]:
            self.assertAlmostEqual(sample_controls(poses, frame)["pelvis"]["translation_delta_cm"][0], expected)

    def test_default_integer_key_midpoint(self):
        poses = [{"frame": frame, "controls": {"foot": {"rotation_delta_deg": [value, 0, 0]}}}
                 for frame, value in [(0, 10), (4, 30)]]
        self.assertEqual(sample_controls(poses, 2)["foot"]["rotation_delta_deg"], [20, 0, 0])


if __name__ == "__main__":
    unittest.main()

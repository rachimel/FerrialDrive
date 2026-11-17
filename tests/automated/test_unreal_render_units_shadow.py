"""출력 단위의 부품 보존과 그림자 마스크의 색·가림 분리를 검사한다."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automate/runtime/image/python"))
from PIL import Image
from automate.unreal.render_units import partition_parts
from automate.unreal.shadow_pass import extract_shadow


class RenderUnitsTest(unittest.TestCase):
    def test_partition_has_no_lost_or_duplicate_parts(self):
        plan = {"parts": [{"id": "p0"}, {"id": "p1"}]}
        self.assertEqual(len(partition_parts(plan, {"body": ["p0"], "hand": ["p1"]})), 2)
        for groups in [{"body": ["p0"]}, {"body": ["p0", "p0"], "hand": ["p1"]},
                       {"body": ["p0"], "hand": ["p0", "p1"]}]:
            with self.assertRaises(ValueError):
                partition_parts(plan, groups)

    def test_shadow_contains_black_rgb_and_preserves_cutout(self):
        clear = Image.new("RGBA", (3, 1))
        clear.putdata([(240, 240, 240, 255), (240, 240, 240, 255), (0, 0, 0, 0)])
        dark = Image.new("RGBA", (3, 1))
        dark.putdata([(120, 120, 120, 255), (240, 240, 240, 255), (255, 0, 0, 0)])
        shadow = extract_shadow(dark, clear)
        self.assertEqual(list(shadow.get_flattened_data()), [(0, 0, 0, 128), (0, 0, 0, 0), (0, 0, 0, 0)])
        composed = Image.alpha_composite(clear, shadow)
        self.assertLessEqual(abs(composed.getpixel((0, 0))[0] - 120), 1)

    def test_non_neutral_receiver_rejected(self):
        with self.assertRaises(ValueError):
            extract_shadow(Image.new("RGBA", (1, 1), (100, 50, 20, 255)),
                           Image.new("RGBA", (1, 1), (200, 100, 50, 255)))

    def test_different_visibility_rejected(self):
        with self.assertRaises(ValueError):
            extract_shadow(Image.new("RGBA", (1, 1), (120, 120, 120, 0)),
                           Image.new("RGBA", (1, 1), (240, 240, 240, 255)))

    def test_identical_invalid_receiver_is_still_rejected(self):
        for color in ((80, 50, 20, 255), (7, 7, 7, 255)):
            image = Image.new("RGBA", (8, 8), color)
            with self.assertRaises(ValueError):
                extract_shadow(image, image)

    def test_sparse_shadow_keeps_full_canvas_and_checks_alpha_outside_bounds(self):
        clear = Image.new("RGBA", (64, 64), (240, 240, 240, 255))
        dark = clear.copy()
        dark.putpixel((30, 40), (120, 120, 120, 255))
        result = extract_shadow(dark, clear)
        self.assertEqual(result.size, clear.size)
        self.assertEqual(result.getchannel("A").getbbox(), (30, 40, 31, 41))
        self.assertEqual(result.getpixel((30, 40)), (0, 0, 0, 128))
        dark.putpixel((0, 0), (240, 240, 240, 252))
        with self.assertRaises(ValueError):
            extract_shadow(dark, clear)


if __name__ == "__main__":
    unittest.main()

"""알파 전용 제작 데이터의 원본 일치·손상·갱신 실패 계약을 검사한다."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
LOCAL_RUNTIME = ROOT / "automate/runtime/texture_compare/python"
if LOCAL_RUNTIME.is_dir():
    sys.path.insert(0, str(LOCAL_RUNTIME))

from ferrial_drive.assets.alpha_data import alpha_data_path, prepare_alpha_data, read_alpha_data
from samples.asset_loader.make_sample import write_png


class AlphaDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "shadow.png"
        write_png(self.source, 7, 5, lambda x, y: (0, 0, 0, (x * 37 + y * 13) % 256))

    def test_exact_alpha_and_original_bytes_survive_preparation(self):
        original = self.source.read_bytes()
        prepare_alpha_data(self.source)
        width, height, pixels = read_alpha_data(self.source)
        self.assertEqual((width, height), (7, 5))
        self.assertEqual(pixels, bytes((x * 37 + y * 13) % 256 for y in range(5) for x in range(7)))
        self.assertEqual(self.source.read_bytes(), original)

    def test_missing_data_returns_none_without_writing(self):
        self.assertIsNone(read_alpha_data(self.source))
        self.assertFalse(alpha_data_path(self.source).exists())

    def test_source_change_invalidates_data_until_prepared_again(self):
        prepare_alpha_data(self.source)
        write_png(self.source, 3, 2, lambda x, y: (0, 0, 0, 123))
        self.assertIsNone(read_alpha_data(self.source))
        prepare_alpha_data(self.source)
        self.assertEqual(read_alpha_data(self.source), (3, 2, bytes([123]) * 6))

    def test_truncated_extra_and_corrupt_payloads_are_rejected(self):
        prepare_alpha_data(self.source)
        path = alpha_data_path(self.source)
        original = path.read_bytes()
        for data in (original[:8], original[:-1], original + b"tail", original[:-1] + bytes([original[-1] ^ 1])):
            with self.subTest(size=len(data)):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    read_alpha_data(self.source)

    def test_missing_source_is_not_masked_by_prepared_data(self):
        prepare_alpha_data(self.source)
        self.source.unlink()
        with self.assertRaises(FileNotFoundError):
            read_alpha_data(self.source)

    def test_failed_replace_keeps_last_good_data_and_removes_temporary(self):
        prepare_alpha_data(self.source)
        original = alpha_data_path(self.source).read_bytes()
        with patch("ferrial_drive.assets.alpha_data.os.replace", side_effect=OSError("쓰기 실패")):
            with self.assertRaises(OSError):
                prepare_alpha_data(self.source)
        self.assertEqual(alpha_data_path(self.source).read_bytes(), original)
        self.assertEqual(list(self.source.parent.glob(".alpha-*.tmp")), [])

    def test_catalog_collection_uses_public_sample_without_game_assets(self):
        from automate.alpha_textures import collect_shadow_images
        from samples.asset_loader.make_sample import write_samples
        root = write_samples(self.source.parent / "demo")
        images = collect_shadow_images([root / "catalog.json"])
        self.assertEqual(images, [root / "shadow.png"])

    def test_half_resolution_keeps_source_dimensions_and_area_filtered_alpha(self):
        from PIL import Image
        from ferrial_drive.assets.alpha_data import png_dimensions
        original = self.source.read_bytes()
        result = prepare_alpha_data(self.source, scale=0.5)
        with Image.open(self.source) as image:
            expected = image.getchannel("A").resize((4, 3), Image.Resampling.BOX).tobytes()
        self.assertEqual(read_alpha_data(self.source), (4, 3, expected))
        self.assertEqual(png_dimensions(self.source), (7, 5))
        self.assertEqual(result["source_size"], [7, 5])
        self.assertEqual(self.source.read_bytes(), original)

    def test_invalid_shadow_scale_is_rejected_before_output(self):
        for scale in (0, -1, 0.3, float("nan")):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                prepare_alpha_data(self.source, scale=scale)
        self.assertFalse(alpha_data_path(self.source).exists())

    def test_quality_files_coexist_preserve_source_and_tiny_odd_dimensions(self):
        original = self.source.read_bytes()
        for scale,size in ((.5,(4,3)),(.25,(2,2)),(.125,(1,1))):
            prepare_alpha_data(self.source,scale=scale,scaled_path=True)
            self.assertEqual(read_alpha_data(self.source,scale=scale)[:2],size)
        self.assertEqual(self.source.read_bytes(),original)
        self.assertFalse(alpha_data_path(self.source).exists())
        self.assertEqual(len(list(self.source.parent.glob("*.alpha8.x*"))),3)

    def test_wrong_scale_file_is_rejected(self):
        prepare_alpha_data(self.source,scale=.5,scaled_path=True)
        alpha_data_path(self.source,scale=.25).write_bytes(alpha_data_path(self.source,scale=.5).read_bytes())
        with self.assertRaises(ValueError):
            read_alpha_data(self.source,scale=.25)


if __name__ == "__main__":
    unittest.main()

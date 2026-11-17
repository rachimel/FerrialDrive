"""Unreal 파츠 인계의 좌표·원본 보존·오입력 거부를 검사한다."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from Tools.asset_loader.unreal_import import import_render
from ferrial_drive.assets.mech import MechBundle


class UnrealImportTest(unittest.TestCase):
    def test_review_compares_body_without_shadow_and_uses_manifest_energy_paths(self):
        from Tools.unreal_pipeline.motion_review import compose
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = Image.new("RGBA", (8, 8))
            body.paste((30, 40, 50, 255), (3, 2, 5, 5))
            body.save(root / "body.png")
            (root / "energy").mkdir()
            body.save(root / "energy/mask.png")
            shadow = Image.new("RGBA", (8, 8))
            shadow.paste((0, 0, 0, 128), (1, 6, 7, 7))
            shadow.save(root / "shadow.png")
            data = {"size": [8, 8], "clips": [{"frames": [{"body": "body.png", "shadow": "shadow.png"}],
                "energy_frames": [{"body": "energy/mask.png"}], "order": ["shadow", "body"]}],
                "reference_mask_frames": {"unsplit_reference": ["body.png"]}}
            (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
            images, checks = compose(root, comparison_exclude=("shadow",))
            self.assertEqual(checks[0]["alpha_max_difference"], 0)
            self.assertEqual(checks[0]["energy_alpha_max_difference"], 0)
            self.assertEqual(checks[0]["comparison_bbox"], (3, 2, 5, 5))
            self.assertEqual(images[0].getpixel((1, 6))[3], 128)
            self.assertGreater(compose(root)[1][0]["alpha_max_difference"], 0)

    def test_direction_pivots_align_every_part_and_energy_mask(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data = self.fixture(root)
            data["pivot"] = [16, 16]
            data["size"] = [32, 32]
            for i in range(2):
                for part in data["layers"]:
                    image = Image.new("RGBA", (32, 32))
                    image.paste((30, 40, 50, 255), (8, 8, 24, 24))
                    image.save(root / f"{part}{i}.png")
            first = data["clips"][0]
            first["pivot"] = [12, 15]
            first["energy_frames"] = [{part: f"{part}{i}.png" for part in data["layers"]} for i in range(2)]
            second = {**first, "name": "idle/n", "pivot": [21, 17]}
            data["clips"].append(second)
            source.write_text(json.dumps(data), encoding="utf-8")
            result = import_render(source, root / "packed", trim_padding=True)
            bundle = MechBundle.load(result["source"])
            for sheet in bundle.sheets.values():
                for name, expected in (("idle/s", (6, 9)), ("idle/n", (15, 11))):
                    self.assertTrue(all(frame.pivot == expected for frame in sheet.clips[name].frames))
                    self.assertEqual(sheet.clips[name].frames[0].rect[2:], (20, 20))

    def test_invalid_direction_pivot_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data = self.fixture(root)
            data["clips"][0]["pivot"] = [float("nan"), 1]
            source.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                import_render(source, root / "packed")
            self.assertFalse((root / "packed").exists())

    def test_shared_trim_preserves_pixels_masks_and_world_placement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data = self.fixture(root)
            data.update(size=[32, 32], pivot=[16, 16])
            data["clips"][0]["energy_frames"] = []
            for i in range(2):
                masks = {}
                for part, box in (("body", (8, 7, 16, 20)), ("weapon", (18, 12, 22, 23))):
                    image = Image.new("RGBA", (32, 32))
                    image.paste((20 + i, 40, 60, 255), box)
                    image.save(root / f"{part}{i}.png")
                    mask = Image.new("RGBA", (32, 32))
                    mask.paste((128, 128, 128, 255), box)
                    mask.save(root / f"{part}_mask{i}.png")
                    masks[part] = f"{part}_mask{i}.png"
                data["clips"][0]["energy_frames"].append(masks)
            source.write_text(json.dumps(data), encoding="utf-8")
            hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
            result = import_render(source, root / "packed", trim_padding=True)
            bundle = MechBundle.load(result["source"])
            for key, sheet in bundle.sheets.items():
                owner = key.split(":")[0]
                suffix = "_mask" if ":energy" in key else ""
                with Image.open(sheet.image_path) as atlas:
                    for i, frame in enumerate(sheet.clips["idle/s"].frames):
                        x, y, width, height = frame.rect
                        self.assertEqual((width, height), (18, 20))
                        self.assertEqual(frame.pivot, (10, 9))
                        restored = Image.new("RGBA", (32, 32))
                        restored.paste(atlas.crop((x, atlas.height-y-height, x+width, atlas.height-y)), (6, 5))
                        with Image.open(root / f"{owner}{suffix}{i}.png") as expected:
                            self.assertEqual(restored.tobytes(), expected.tobytes())
            self.assertEqual(hashes, {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in hashes})

    def test_trim_keeps_pivot_when_it_is_outside_visible_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data = self.fixture(root)
            data.update(size=[32, 32], pivot=[2, 1])
            for i in range(2):
                for part in data["layers"]:
                    image = Image.new("RGBA", (32, 32))
                    image.paste((30, 40, 50, 255), (10, 10, 20, 20))
                    image.save(root / f"{part}{i}.png")
            source.write_text(json.dumps(data), encoding="utf-8")
            result = import_render(source, root / "packed", trim_padding=True)
            frame = MechBundle.load(result["source"]).clips["idle/s"].frames[0]
            self.assertEqual(frame.pivot, (2, 1))
            self.assertEqual(frame.rect[2:], (22, 24))

    def test_grid_packing_preserves_every_clip_frame_and_part(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data = self.fixture(root)
            for index in range(6):
                for part, alpha in (("body", 255), ("weapon", 128)):
                    Image.new("RGBA", (8, 8), (20 + index, 40, 60, alpha)).save(root / f"{part}{index}.png")
            data["clips"] = [{"name": "idle/" + direction, "fps": 12,
                              "frames": [{part: f"{part}{i}.png" for part in ("body", "weapon")}
                                         for i in range(start, start + 3)]}
                             for direction, start in (("s", 0), ("n", 3))]
            source.write_text(json.dumps(data), encoding="utf-8")
            with patch("Tools.asset_loader.unreal_import.MAX_SHEET_SIZE", 24):
                result = import_render(source, root / "packed")
            bundle = MechBundle.load(result["source"])
            for part in ("body", "weapon"):
                sheet = bundle.sheets[part]
                self.assertEqual(sheet.size, (16, 24))
                with Image.open(sheet.image_path) as image:
                    for direction, start in (("s", 0), ("n", 3)):
                        for index, frame in enumerate(sheet.clips["idle/" + direction].frames):
                            x, y, width, height = frame.rect
                            actual = image.crop((x, image.height - y - height, x + width, image.height - y))
                            with Image.open(root / f"{part}{start + index}.png") as expected:
                                self.assertEqual(actual.tobytes(), expected.tobytes())

    def fixture(self, root):
        for i in range(2):
            for part, color in [("body", (20 + i, 40, 60, 255)), ("weapon", (90, 50 + i, 10, 128))]:
                Image.new("RGBA", (8, 8), color).save(root / f"{part}{i}.png")
        data = {"version": 1, "type": "unreal_prerender", "asset_id": "demo", "size": [8, 8], "pivot": [4, 1],
                "layers": {"body": {}, "weapon": {}}, "clips": [{"name": "idle/s", "fps": 12,
                "frames": [{k: f"{k}{i}.png" for k in ("body", "weapon")} for i in range(2)],
                "order": ["body", "weapon"], "order_overrides": {"1": ["weapon", "body"]}}]}
        path = root / "manifest.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path, data

    def test_native_bundle_frame_coordinates_and_source_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _ = self.fixture(root)
            hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
            result = import_render(source, root / "packed")
            bundle = MechBundle.load(result["source"])
            self.assertEqual(bundle.order("idle/s", 1), ["weapon", "body"])
            self.assertEqual(bundle.clips["idle/s"].fps, 12)
            with Image.open(root / "packed/body.png") as image:
                self.assertEqual(image.getpixel((0, 0)), (21, 40, 60, 255))
                self.assertEqual(image.getpixel((0, 8)), (20, 40, 60, 255))
            self.assertEqual(hashes, {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in hashes})

    def test_bad_frame_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data = self.fixture(root)
            data["clips"][0]["frames"][1].pop("weapon")
            source.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                import_render(source, root / "packed")
            self.assertFalse((root / "packed").exists())

    def test_external_path_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data = self.fixture(root)
            data["clips"][0]["frames"][0]["body"] = "../outside.png"
            source.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                import_render(source, root / "packed")

    def test_empty_body_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _ = self.fixture(root)
            for i in range(2):
                Image.new("RGBA", (8, 8)).save(root / f"body{i}.png")
            with self.assertRaises(ValueError):
                import_render(source, root / "packed")
            self.assertFalse((root / "packed").exists())

    def test_pending_shadow_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, data = self.fixture(root)
            data["shadow_pending"] = {"frames": []}
            source.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                import_render(source, root / "packed")
            self.assertFalse((root / "packed").exists())

    def test_energy_mask_packed_and_loaded_with_same_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source,data=self.fixture(root)
            for i in range(2):
                Image.new("RGBA",(8,8),(80+i,80+i,80+i,255)).save(root/f"mask{i}.png")
            data["clips"][0]["energy_frames"]=[{"body":f"mask{i}.png"} for i in range(2)]
            source.write_text(json.dumps(data),encoding="utf-8")
            result=import_render(source,root/"packed")
            bundle=MechBundle.load(result["source"])
            self.assertEqual(bundle.masks["body"],"body:energy")
            with Image.open(root/"packed/body_energy.png") as image:
                self.assertEqual(image.getpixel((0,0)),(81,81,81,255))
                self.assertEqual(image.getpixel((0,8)),(80,80,80,255))
            bundle.selection("idle/s")

    def test_missing_energy_frame_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source,data=self.fixture(root)
            data["clips"][0]["energy_frames"]=[{"body":"body0.png"}]
            source.write_text(json.dumps(data),encoding="utf-8")
            with self.assertRaises(ValueError):
                import_render(source,root/"packed")
            self.assertFalse((root/"packed").exists())

    def test_energy_silhouette_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source,data=self.fixture(root)
            Image.new("RGBA",(8,8),(255,255,255,0)).save(root/"mask.png")
            data["clips"][0]["energy_frames"]=[{"body":"mask.png"} for _ in range(2)]
            source.write_text(json.dumps(data),encoding="utf-8")
            with self.assertRaises(ValueError):
                import_render(source,root/"packed")
            self.assertFalse((root/"packed").exists())

    def test_energy_sheet_filename_collision_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source,data=self.fixture(root)
            data["layers"]["body_energy"]=data["layers"].pop("weapon")
            clip=data["clips"][0]
            clip["order"]=["body","body_energy"]
            clip["order_overrides"]={}
            for frame in clip["frames"]:
                frame["body_energy"]=frame.pop("weapon")
            clip["energy_frames"]=[{"body":"body0.png"},{"body":"body1.png"}]
            source.write_text(json.dumps(data),encoding="utf-8")
            with self.assertRaises(ValueError):
                import_render(source,root/"packed")
            self.assertFalse((root/"packed").exists())


if __name__ == "__main__":
    unittest.main()

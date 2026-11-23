"""패킹한 방향 자료의 정밀도와 호환 경로 검사."""

import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from automate.part_metadata_cache import build
from ferrial_drive.rendering.part_metadata import PackedFrameRows, PackedShadowPoses, PackedTrackRows, TILE_FIELDS
from ferrial_drive.rendering.part_metadata_archive import PackedMetadataArchive
from ferrial_drive.rendering.part_motion_atlas import frame_state
from ferrial_drive.rendering.part_motion_catalog import PartMotionCatalog


class PackedPartMetadataTests(unittest.TestCase):
    def test_frame_flags_preserve_absence_defaults_and_signed_indices(self):
        rows = [
            {"page": -1, "rect": [0, 0, 4, 4]},
            {"page": 0, "rect": [16, 8, 4, 4], "flow_step": [0.001, -0.0]},
        ]
        packed = PackedFrameRows(rows, TILE_FIELDS)
        self.assertEqual(list(packed), rows)
        self.assertEqual(packed[-1], rows[-1])
        self.assertEqual(packed[::-1], rows[::-1])
        self.assertEqual(math.copysign(1, packed[1]["flow_step"][1]), -1)
        self.assertEqual(packed[0].get("flow_step", (0, 0)), (0, 0))
        with self.assertRaises(IndexError):
            packed[2]

    def test_direction_loader_keeps_out_of_range_tables_and_part_space_overlay(self):
        tile = {"page": 0, "rect": [16, 8, 4, 4]}
        fallback = {"page": 0, "rect": [40_000, 8, 4, 4]}
        clip = {
            "loop": False, "duration_seconds": 1, "fps": 1,
            "anchors": [{"waist": [0, 0, 0]}, {"waist": [1, 1, 1]}],
            "parts": {"body": {"space": "upper", "crop": [0, 0, 4, 4], "frames": [
                {"color": 0, "forward": 0, "backward": 0},
                {"color": 1, "forward": 0, "backward": 0},
            ]}},
        }
        pose = [1.2345678901234567, -0.0, 3, 0, 0, 0, 1]
        catalog = {
            "version": 1, "type": "part_motion_gpu", "parts": ["body"],
            "motions": {"idle": {"0": "direction.json"}},
            "shadow_proxy": {"bones": ["waist"], "clips": {"idle": {"poses": [[pose], [pose]]}}},
        }
        direction = {"pages": {}, "frames": {"color": [tile, tile], "vector": [fallback]}, "clip": clip}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "catalog.json"
            source.write_text(json.dumps(catalog), encoding="utf-8")
            (root / "direction.json").write_text(json.dumps(direction), encoding="utf-8")
            spaces = {"idle": {"body": "lower"}}
            baseline = PartMotionCatalog(source, part_spaces=spaces)
            candidate = PartMotionCatalog(source, part_spaces=spaces, packed=True)
            prepared = candidate.read_direction("idle", "0")
            self.assertFalse(candidate.records)
            _, packed = candidate.direction("idle", "0", prepared=prepared)
            _, plain = baseline.direction("idle", "0")
            self.assertEqual(frame_state(packed["clip"], packed["clip"], .4),
                             frame_state(plain["clip"], plain["clip"], .4))
            self.assertIsInstance(packed["frames"]["color"], PackedFrameRows)
            self.assertEqual(packed["frames"]["vector"], [fallback])
            self.assertEqual(prepared["clip"]["parts"]["body"]["space"], "upper")
            poses = candidate.data["shadow_proxy"]["clips"]["idle"]["poses"]
            self.assertIsInstance(poses, PackedShadowPoses)
            self.assertEqual(poses[0], (tuple(pose),))
            self.assertIs(poses[0], poses[0])
            self.assertEqual(math.copysign(1, poses[0][0][1]), -1)

    def test_unknown_fields_preserve_the_existing_rows(self):
        from ferrial_drive.rendering.part_metadata import pack_direction_metadata

        data = {"frames": {"vector": [{"page": 0, "new_bounds": [3, 6]}]}, "clip": {"parts": {}}}
        before = copy.deepcopy(data)
        pack_direction_metadata(data)
        self.assertEqual(data, before)

    def test_archive_reads_packed_tracks_and_ignores_an_updated_source(self):
        first = {"seconds": 0.0, "root": [0, 0, 0], "waist": [4, 5, 6], "points": {"muzzle": [7, 8, 9]}}
        second = {**first, "seconds": 1.0, "points": {"muzzle": [11, 12, 13]}}
        data = {"type": "upper_lower_pose_table", "attachments": {"idle": {"samples": [first, second]}}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "pose.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            output = root / "cache.zip"
            self.assertEqual(build((), output, (source,)), 1)
            cache = PackedMetadataArchive(output)
            with cache.archive:
                rows = cache.read(source)["attachments"]["idle"]["samples"]
                self.assertIsInstance(rows, PackedTrackRows)
                self.assertEqual(rows.time_at(1), 1)
                self.assertEqual(rows[1]["points"]["muzzle"], (11, 12, 13))
                source.write_text("{}", encoding="utf-8")
                self.assertIsNone(cache.read(source))
                with self.assertRaises(FileExistsError):
                    build((), output, (source,))

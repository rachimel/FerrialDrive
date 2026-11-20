"""가변 키 시각, 원본 허리 타임라인, 키 사이 모션 벡터를 검사한다."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np

from automate.part_sparse_atlas import TilePage, compose_flow, read_page, select_keys
from ferrial_drive.combat.encounter_view import EncounterView
from ferrial_drive.combat.enemy_sprites import EnemySprite
from ferrial_drive.rendering.part_motion_atlas import frame_phase, frame_state


class SparsePartAtlasTests(unittest.TestCase):
    def test_nonuniform_key_time_preserves_dense_waist_motion(self):
        upper = {
            "fps": 4, "duration_seconds": 1, "loop": False, "keyframe_seconds": [0, .25, 1],
            "anchors": [{"waist": [0, 0, 0]} for _ in range(5)],
            "parts": {"body": {"space": "upper", "crop": [0, 0, 20, 20], "frames": [0, 1, 4]}},
        }
        lower = deepcopy(upper)
        lower["anchors"][2]["waist"] = [12, 0, 3]
        state = frame_state(upper, lower, .5)
        self.assertEqual((state["first"], state["alpha"]), (1, 1 / 3))
        self.assertEqual(state["anchor_phase"], (2, 0))
        self.assertEqual(state["parts"][0]["shift"], [12, 0, 3])
        self.assertEqual((state["parts"][0]["a"], state["parts"][0]["b"]), (1, 4))
        self.assertEqual(frame_phase(upper, .25), (1, 0))
        self.assertEqual(frame_phase(upper, 1.25), (1, 1))
        self.assertEqual(frame_phase(dict(upper, loop=True), 1.25), (1, 0))

    def test_selection_retains_bend_and_omits_linear_poses(self):
        poses = [[[x, y, 0, 0, 0, 0, 1]] for x, y in enumerate((0, 0, 5, 0, 0))]
        proxy = {"bounds": [[[0, 0, 0], [1, 1, 1]]], "clips": {"move": {"hz": 4, "poses": poses}}}
        self.assertEqual(select_keys(proxy, "move", 5, 4, 1, 1.5), [0, 1, 2, 3, 4])
        poses[2][0][1] = 0
        self.assertEqual(select_keys(proxy, "move", 5, 4, 1, 1.5), [0, 4])

    def test_flow_composition_samples_the_second_field_at_the_moved_pixel(self):
        vectors = np.full((2, 8, 2), 128, dtype=np.uint8)
        vectors[:, :4, 0] = 129
        vectors[:, 4:, 1] = [128, 130, 132, 134]
        tiles = [{"rect": [x, 0, 4, 2], "flow_step": [1, 1]} for x in (0, 4)]
        codes, metadata = compose_flow(vectors, tiles)
        flow = (codes.astype(float) - 128) * metadata["flow_step"]
        np.testing.assert_allclose(flow[0], [[1, 2], [1, 4], [1, 6], [1, 6]], atol=.05)

    def test_bc7_repack_preserves_key_blocks_and_crop_offsets(self):
        blocks = np.arange(3 * 4 * 16, dtype=np.uint8).reshape(3, 4, 16)
        pack = TilePage("bc7_zlib")
        keep = pack.retain(blocks, {"rect": [5, 1, 6, 6]}, 3)
        pack.retain(blocks, {"rect": [0, 8, 8, 4]}, 0)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            page, frames = pack.write(root, root / "catalog.json", 16)
            x, y, width, height = frames[keep]["rect"]
            self.assertEqual((x % 4, y % 4, width, height), (1, 1, 6, 6))
            restored = read_page(page, root)[y // 4:y // 4 + 2, x // 4:x // 4 + 2]
            np.testing.assert_array_equal(restored, blocks[:2, 1:3])

    def test_shared_enemy_tick_preserves_the_gameplay_frame_index(self):
        resource = SimpleNamespace(data={"sample_fps": 24, "shared_pose_fps": 60})
        sprite = EnemySprite(resource, 1, 1, (2, 3), {}, {"attack": 12})
        self.assertEqual(sprite.frame_index("attack", "s", .35), 8)
        self.assertEqual(sprite.shared_frame_index("attack", "s", .35), 21)
        self.assertEqual(sprite.ground_shadow_pose(("attack", "s", .351)), ("attack/u0l0", 8 / 24))
        self.assertEqual(sprite.shared_frame_index("attack", "s", 1.5), 60)
        del resource.data["shared_pose_fps"]
        self.assertEqual(sprite.shared_frame_index("attack", "s", .35), 8)

    def test_only_duplicate_sparse_poses_enter_the_persistent_body_cache(self):
        view = EncounterView.__new__(EncounterView)
        view.show_enemy_labels = False
        resource = SimpleNamespace(data={"sample_fps": 24, "shared_pose_fps": 60})
        sprite = EnemySprite(resource, 1, 1, (2, 3), {}, {"move": 12})
        small = SimpleNamespace(profile=SimpleNamespace(kind="small"), phase="move")
        other = SimpleNamespace(profile=SimpleNamespace(kind="medium"), phase="move")
        rows = [(100, x, enemy, sprite, ("move", direction, seconds), True)
                for x, enemy, direction, seconds in (
                    (100, small, "s", .025), (200, small, "s", .03), (300, small, "s", .055),
                    (400, small, "e", .03), (500, other, "s", .03))]
        view._select_shared_bodies(rows)
        self.assertEqual([row[-1] for row in rows], [True, True, False, False, False])

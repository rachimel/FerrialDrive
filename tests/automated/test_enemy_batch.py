"""교전의 묶음 제출을 실제 파츠·그림자 개별 제출 픽셀과 대조한다."""

import ctypes as ct
import json
import os
from pathlib import Path
import unittest

from ferrial_drive.combat.enemy_sprites import load_enemy_part_sprites
from ferrial_drive.diagnostics.timing import TimingRecorder
from ferrial_drive.rendering.canvas import PicoCanvas
from ferrial_drive.rendering.part_atlas_residency import AtlasFrameBudget
from ferrial_drive.rendering.part_shadow_map import GROUND_GEOMETRY_BUDGET_BYTES, MAX_GROUND_GEOMETRY_POSES
from ferrial_drive.rendering.pose_copy_batch import MIN_POSE_COPIES
from ferrial_drive.settings import GameSettings


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS") == "1", "실제 GPU 검사는 선택 실행한다.")
class EnemyBatchGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        combat = ROOT / "samples/combat_test_v1_5/encounter.json"
        movement = ROOT / "samples/sword_movement/movement_config.json"
        catalog = combat.parent / json.loads(combat.read_text(encoding="utf8"))["rendering"]["enemy_part_sprites"]
        light = movement.parent / json.loads(movement.read_text(encoding="utf8"))["upper_lower"]["pbr_lighting"]
        if not catalog.is_file() or not light.is_file():
            raise unittest.SkipTest("로컬 적 파츠와 조명 에셋이 필요하다.")
        cls.catalog, cls.light = catalog, light
        canvas = cls.enterClassContext(PicoCanvas(512, 512, "기체 묶음 픽셀 검사", vsync=False))
        cls.pico = canvas.pico
        cls.sprites = load_enemy_part_sprites(catalog, cls.pico, light, GameSettings(texture_quality="medium"), TimingRecorder())
        if not cls.sprites:
            raise AssertionError("비교할 적 기종이 없다.")
        for sprite in cls.sprites.values():
            cls.addClassCleanup(sprite.close)

    def capture(self, paint):
        import numpy as np
        p = self.pico
        p.SDL_SetRenderDrawColor(p.renderer, 140, 170, 200, 255)
        p.SDL_RenderClear(p.renderer)
        paint()
        pixels = np.empty((512, 512, 4), dtype=np.uint8)
        self.assertEqual(p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32,
                                               pixels.ctypes.data_as(ct.c_void_p), 2048), 0)
        return pixels[:, :, :3].astype("int16")

    def compare(self, reference, batched, tolerance):
        import numpy as np
        baseline, result = self.capture(reference), self.capture(batched)
        mask = np.any(baseline != [140, 170, 200], axis=2) | np.any(result != [140, 170, 200], axis=2)
        self.assertGreater(mask.sum(), 100)
        difference = np.abs(baseline - result)[mask]
        self.assertLess(difference.mean(), 1)
        self.assertLessEqual(difference.max(), tolerance)
        np.testing.assert_array_equal(result, self.capture(batched))

    def test_first_move_and_attack_use_preloaded_pages_and_metadata(self):
        sprites = load_enemy_part_sprites(self.catalog, self.pico, self.light, GameSettings(texture_quality="medium"),
                                          TimingRecorder(), AtlasFrameBudget())
        for sprite in sprites.values():
            self.addCleanup(sprite.close)
        for kind, sprite in sprites.items():
            with self.subTest(kind=kind):
                resource = sprite.resource
                catalog = resource.catalog
                for motion in ("move", "attack"):
                    self.assertTrue(set(catalog.data["motions"][motion].values()) <= catalog.records.keys())
                self.assertLessEqual(resource.estimated_bytes, resource.cache_budget_bytes * 3 // 4)
                poses = [("move", direction, .125) for direction in ("s", "sw", "w", "nw", "n", "ne", "e", "se")]
                poses.extend(("attack", direction, .125) for direction in ("s", "n"))
                uploads = resource.cache.uploads
                sprite.prepare_frame(poses)
                self.assertEqual([sprite.display_playback(pose) for pose in poses], poses)
                self.assertEqual(resource.cache.uploads, uploads)
                self.assertIsNone(resource.residency.prefetch)

    def test_overlap_preserves_order_and_each_interpolation_phase(self):
        for kind, sprite in self.sprites.items():
            for motion in ("move", "attack", "break"):
                with self.subTest(kind=kind, motion=motion):
                    resource = sprite.resource
                    scale = 1 / resource.data["pixel_scale"]
                    clip = sprite.part_clip(motion, "s")
                    requests = [(i, motion, "0", (1 + i % 10 + (i % 4) * .219) / 24,
                                 120 + (i % 7) * 35.7, 135 + (i // 7) * 16.35) for i in range(68)]

                    def reference():
                        for _, _, _, seconds, x, y in requests:
                            resource.draw(clip, seconds, x, y, scale=scale, sample_shadow=False)

                    def batched():
                        copies = sprite.prepare_bodies(requests, scale)
                        self.assertEqual(len(copies), len(requests))
                        self.assertEqual(sprite.body_batch.submits, 2)
                        for enemy_id, *_ in requests:
                            sprite.body_batch.copy(copies[enemy_id])

                    self.compare(reference, batched, 4)

    def test_shadow_geometry_cache_respects_rig_size_and_recent_use(self):
        for kind, sprite in self.sprites.items():
            with self.subTest(kind=kind):
                shadow = sprite.resource.shadow_map
                shadow.ground_geometry.clear()
                self.addCleanup(shadow.ground_geometry.clear)
                limit = shadow.ground_geometry_limit
                self.assertGreater(limit, 1)
                keys = [("move", 0, (i / 4, i / 4)) for i in range(limit + 1)]
                first = shadow.pose_geometry(keys[0], True)
                for key in keys[1:limit]:
                    shadow.pose_geometry(key, True)
                self.assertIs(shadow.pose_geometry(keys[0], True), first)
                shadow.pose_geometry(keys[-1], True)
                self.assertIn(keys[0], shadow.ground_geometry)
                self.assertNotIn(keys[1], shadow.ground_geometry)
                entries = shadow.ground_geometry.values()
                self.assertLessEqual(len(entries), MAX_GROUND_GEOMETRY_POSES)
                self.assertLessEqual(sum(len(vertices) for vertices, _ in entries), GROUND_GEOMETRY_BUDGET_BYTES)

    def test_shared_pose_copies_preserve_pixels_overlap_and_rounding(self):
        sprite = self.sprites["small"]
        cache = sprite.shared_frames()
        if cache.copy_batch is None:
            self.skipTest("Numba가 필요하다.")
        points = [(-4.5, 100.5), (100.5, 112.5), (104.5, 116.5), (250.25, 185.75),
                  (503.5, 490.5)] * 3
        pose = sprite.part_clip("move", "s"), 3 / 24
        def render(placements):
            return cache.draw_shadows(pose, placements, .85, .5, 3)

        def individual():
            for point in points:
                render([point])

        p = self.pico
        sx, sy = ct.c_float(), ct.c_float()
        p.SDL_RenderGetScale(p.renderer, ct.byref(sx), ct.byref(sy))
        self.addCleanup(p.SDL_RenderSetScale, p.renderer, sx.value, sy.value)
        for scale in (1, .75):
            p.SDL_RenderSetScale(p.renderer, scale, scale)
            baseline = self.capture(individual)
            before = cache.copy_batch.submits
            result = self.capture(lambda: render(points))
            self.assertEqual(cache.copy_batch.submits, before + 1)
            self.assertTrue((baseline != [140, 170, 200]).any())
            self.assertTrue((baseline == result).all())
            self.capture(lambda: render(points[:MIN_POSE_COPIES - 1]))
            self.assertEqual(cache.copy_batch.submits, before + 1)

    def test_shadows_across_tile_eviction_and_instance_limit(self):
        for kind, sprite in self.sprites.items():
            with self.subTest(kind=kind):
                scale = 1 / sprite.resource.data["pixel_scale"]
                groups = []
                for face in ("s", "ne", "w", "n", "sw", "e", "se", "nw"):
                    for i in range(10):
                        n = len(groups)
                        points = [(130 + n % 8 * 27.5, 140 + n % 5 * 23.8), (145 + n % 8 * 26.1, 155 + n % 5 * 22.7)]
                        groups.append(((sprite.part_clip("move", face), i / 24), points))

                def reference():
                    for pose, positions in groups:
                        sprite.draw_ground_shadows(pose, positions, scale, .45, 3)

                def batched():
                    count, submits = sprite.draw_near_shadows(groups, scale, .45, 3)
                    self.assertEqual((count, submits), (160, 3))

                self.compare(reference, batched, 8)

"""교전의 묶음 제출을 실제 파츠·그림자 개별 제출 픽셀과 대조한다."""

import ctypes as ct
import json
import os
from pathlib import Path
import unittest

from ferrial_drive.combat.enemy_sprites import load_enemy_part_sprites
from ferrial_drive.diagnostics.timing import TimingRecorder
from ferrial_drive.rendering.canvas import PicoCanvas
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

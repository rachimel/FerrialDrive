"""교전의 묶음 제출을 실제 파츠·그림자 개별 제출 픽셀과 대조한다."""

import ctypes as ct
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.combat.encounter_view import EncounterView
from ferrial_drive.combat.enemy_encounter import EnemyEncounter
from ferrial_drive.combat.enemy_sprites import load_enemy_part_sprites
from ferrial_drive.combat.training_ground import GroundProjection
from ferrial_drive.diagnostics.timing import TimingRecorder
from ferrial_drive.rendering.canvas import PicoCanvas
from ferrial_drive.rendering.enemy_crowd_atlas import EnemyCrowdAtlas
from ferrial_drive.rendering.part_atlas_residency import AtlasFrameBudget
from ferrial_drive.rendering.part_shadow_map import GROUND_GEOMETRY_BUDGET_BYTES, MAX_GROUND_GEOMETRY_POSES
from ferrial_drive.rendering.pose_copy_batch import MIN_POSE_COPIES
from ferrial_drive.settings import GameSettings
from ferrial_drive.ui.pico_renderer import PicoRenderer


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
                    requests = [(i, motion, "0", (1 + i % 10 + i * .003) / 24,
                                 120 + (i % 7) * 35.7, 135 + (i // 7) * 16.35) for i in range(68)]
                    requests.append((68, motion, "0", requests[0][3], 240, 110))

                    def reference():
                        for _, _, _, seconds, x, y in requests:
                            resource.draw(clip, seconds, x, y, scale=scale, sample_shadow=False)

                    def batched():
                        copies = sprite.prepare_bodies(requests, scale)
                        self.assertEqual(len(copies), len(requests))
                        self.assertEqual(sprite.body_batch.submits, 2)
                        self.assertIs(copies[0][0], copies[68][0])
                        self.assertIsNot(copies[0][0], copies[10][0])
                        for enemy_id, *_ in requests:
                            sprite.body_batch.copy(copies[enemy_id])

                    self.compare(reference, batched, 4)

    def test_upscaled_smaa_sheet_preserves_individual_filters_and_order(self):
        from ferrial_drive.rendering.enemy_part_batch import EnemyPartBatch, EnemyUpscaleScratch

        scratch = EnemyUpscaleScratch(self.pico)
        self.addCleanup(scratch.close)
        for kind, sprite in self.sprites.items():
            resource = sprite.resource
            previous_mode = resource.upscaler.aa_mode
            self.addCleanup(self.set_upscale_mode, resource, previous_mode)
            batch = EnemyPartBatch(resource, scratch=scratch)
            self.addCleanup(batch.close)
            rows = [(i, motion, direction, (i + 1.23) / 24, 155 + i % 4 * 27.5, 160 + i * 18.25)
                    for i, (motion, direction) in enumerate(
                        (("move", "0"), ("attack", "2"), ("move", "0"), ("move", "4"),
                         ("attack", "2"), ("move", "4"), ("move", "0"), ("attack", "2")))]
            self.set_upscale_mode(resource, "off")
            self.assertEqual(batch.prepare(rows, 1.2 / resource.data["pixel_scale"]), {})
            self.set_upscale_mode(resource, "smaa")
            for factor in (1.2, 1.85):
                with self.subTest(kind=kind, factor=factor):
                    scale = factor / resource.data["pixel_scale"]

                    def reference():
                        for _, motion, d, seconds, x, y in rows:
                            resource.draw(f"{motion}/u{d}l{d}", seconds, x, y, scale=scale, sample_shadow=False)

                    def batched():
                        copies = batch.prepare(rows, scale)
                        self.assertEqual(len(copies), len(rows), scratch.unavailable)
                        self.assertEqual(batch.submits, 3)
                        for enemy_id, *_ in rows:
                            batch.copy(copies[enemy_id])

                    self.compare(reference, batched, 8)

    @staticmethod
    def set_upscale_mode(resource, mode):
        with resource.upscaler.prepare_aa(mode) as apply:
            if apply:
                apply()

    def test_shadow_geometry_cache_respects_rig_size_and_recent_use(self):
        for kind, sprite in self.sprites.items():
            with self.subTest(kind=kind):
                shadow = sprite.resource.shadow_map
                self.assertEqual(shadow.vertex_data.size, len(shadow.caster_indices) * 8 * 3 * 4)
                self.assertEqual(shadow.index_count, len(shadow.caster_indices) * 12 * 3)
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

    def test_depth_tiles_query_once_and_restore_on_failure(self):
        from ferrial_drive.rendering.enemy_shadow_batch import EnemyShadowBatch

        resource = next(iter(self.sprites.values())).resource
        shadow = resource.shadow_map
        sampler = shadow.depth_sampler
        motion = next(iter(shadow.tracks))
        vertices, _ = shadow.pose_geometry((motion, 0, (0, 0)), False)
        tiles = [((0, 0), vertices), ((shadow.ground_size, 0), vertices)]
        batch = EnemyShadowBatch(resource)
        self.addCleanup(batch.close)
        self.pico.SDL_RenderFlush(self.pico.renderer)

        def state():
            integers = tuple(sampler.integer(key, count) for key, count in
                             ((0x0BA2, 4), (0x0C10, 4), (0x8B8D, 1), (0x8CA6, 1), (0x8CAA, 1),
                              (0x85B5, 1), (0x8894, 1), (0x0B72, 1), (0x0B74, 1)))
            flags = tuple(sampler.glIsEnabled(key) for key in (0x0B71, 0x0B44, 0x0C11))
            clear = ct.c_double()
            shadow.GetDoublev(0x0B73, ct.byref(clear))
            return integers, flags, clear.value

        original = state()
        with patch.object(sampler, "glGetIntegerv", wraps=sampler.glGetIntegerv) as integers:
            with patch.object(shadow, "GetDoublev", wraps=shadow.GetDoublev) as clear:
                shadow.render_depth_tiles(batch.texture, tiles)
            self.assertEqual(clear.call_count, 1)
            self.assertEqual(integers.call_count, 8)
        self.assertEqual(state(), original)
        with patch.object(shadow, "BufferSubData", side_effect=RuntimeError("타일 제출 중단")):
            with self.assertRaisesRegex(RuntimeError, "타일 제출 중단"):
                shadow.render_depth_tiles(batch.texture, tiles)
        self.assertEqual(state(), original)

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

    def test_shared_body_runs_keep_depth_order_lock_and_attack_effects(self):
        config = json.loads((ROOT / "samples/combat_test_v1_5/encounter.json").read_bytes())
        config["rendering"]["shared_frame_distance_m"] = 10
        config["spawns"] = [{"id": str(i), "profile": "medium" if i == 8 else "small",
                             "position_m": [500 + (i % 3) * 2, 500 + i * .8]} for i in range(20)]
        encounter = EnemyEncounter(config, map_size_m=1000, player_radius_m=2.5)
        active = encounter.enemies["8"]
        active.phase, active.attack_kind = "active", "ranged"
        projection = GroundProjection(8, .5)
        camera = LookAheadCamera(512, 512)
        camera.reset(projection.project((500, 500)))
        renderer = PicoRenderer({"small": ROOT / "data/fonts/SUITE-otf/SUITE-Bold.otf"}, {"small": 12})
        self.addCleanup(renderer.close)
        view = EncounterView(renderer, camera, projection, backend="immediate")
        self.addCleanup(view.primitives.close)
        view.sprites = self.sprites

        def draw():
            view.draw(encounter, {}, (512, 512), player_position_m=(400, 400), locked_id="13")

        with patch.object(view, "_shared_body_key", return_value=None):
            baseline = self.capture(draw)
            expected = dict(view.primitives.stats)
        result = self.capture(draw)
        self.assertTrue((baseline != [140, 170, 200]).any())
        self.assertTrue((result == baseline).all())
        self.assertEqual(view.primitives.stats, expected)
        self.assertEqual(expected["shared_frame_draws"], 19)

    def test_single_far_enemy_uses_atlas_without_preparing_pbr(self):
        import numpy as np

        path = ROOT / "samples/combat_test_v1_5/encounter.json"
        config = json.loads(path.read_bytes())
        atlas_path = (path.parent / config["rendering"]["enemy_repacked_sprites"]).with_name("crowd_atlas.json")
        if not atlas_path.is_file():
            self.skipTest("로컬 군집 아틀라스가 필요하다.")
        config["spawns"] = [{"id": "far", "profile": "small", "position_m": [500, 500]}]
        encounter = EnemyEncounter(config, map_size_m=1000, player_radius_m=2.5)
        projection = GroundProjection(8, .5)
        camera = LookAheadCamera(512, 512)
        camera.reset(projection.project((500, 500)))
        renderer = PicoRenderer({"small": ROOT / "data/fonts/SUITE-otf/SUITE-Bold.otf"}, {"small": 12})
        self.addCleanup(renderer.close)
        view = EncounterView(renderer, camera, projection, backend="immediate")
        self.addCleanup(view.primitives.close)
        view.crowd_atlas = EnemyCrowdAtlas(self.pico, atlas_path)
        self.addCleanup(view.crowd_atlas.close)
        sprite = self.sprites["small"]
        view.sprites = {"small": sprite}

        with patch.object(sprite, "prepare_frame") as prepare, patch.object(sprite.resource, "get") as get:
            pixels = self.capture(lambda: view.draw(encounter, {}, (512, 512), player_position_m=(400, 400)))
            shadow_pixels = self.capture(lambda: view.draw(encounter, {}, (512, 512), player_position_m=(400, 400),
                                                           shadow_opacity=.5))
            prepare.assert_not_called()
            get.assert_not_called()
        self.assertEqual(view.primitives.stats["crowd_atlas_draws"], 1)
        self.assertEqual(view.primitives.stats["pbr_pose_requests"], 0)
        self.assertEqual(view.primitives.stats["shadow_draws"], 1)
        self.assertGreater(np.any(pixels != shadow_pixels, axis=2).sum(), 0)
        self.assertGreater(np.any(pixels[200:270, 200:312] != [140, 170, 200], axis=2).sum(), 100)

        with patch.object(sprite, "prepare_frame") as prepare:
            view.draw(encounter, {}, (512, 512), player_position_m=(400, 400), locked_id="far")
            prepare.assert_called_once()
        self.assertEqual(view.primitives.stats["crowd_atlas_draws"], 0)

    def test_fixed_atlas_batches_preserve_overlap_locks_and_attack_effects(self):
        import numpy as np

        path = ROOT / "samples/combat_test_v1_5/encounter.json"
        config = json.loads(path.read_bytes())
        atlas_path = (path.parent / config["rendering"]["enemy_repacked_sprites"]).with_name("crowd_atlas.json")
        if not atlas_path.is_file():
            self.skipTest("로컬 군집 아틀라스가 필요하다.")
        config["spawns"] = [{"id": str(i), "profile": "small" if i % 2 else "medium",
                             "position_m": [501 + (i % 3) * .7, 499 + i * .36]} for i in range(24)]
        encounter = EnemyEncounter(config, map_size_m=1000, player_radius_m=2.5)
        for index, kind in ((7, "melee"), (12, "ranged")):
            enemy = encounter.enemies[str(index)]
            enemy.phase, enemy.attack_kind = "active", kind
            enemy.remaining_seconds = enemy.profile.active_seconds * .5
        projection = GroundProjection(10, .5)
        camera = LookAheadCamera(512, 512)
        camera.reset(projection.project((500, 500)))
        renderer = PicoRenderer({"small": ROOT / "data/fonts/SUITE-otf/SUITE-Bold.otf"}, {"small": 12})
        self.addCleanup(renderer.close)
        view = EncounterView(renderer, camera, projection, backend="immediate")
        self.addCleanup(view.primitives.close)
        view.sprites = self.sprites
        atlas = view.crowd_atlas = EnemyCrowdAtlas(self.pico, atlas_path)
        self.addCleanup(atlas.close)

        def draw():
            view.draw(encounter, {}, (512, 512), player_position_m=(400, 400), locked_id="17",
                      shadow_opacity=.54)

        with patch.object(view, "batch_crowd_atlas", False):
            baseline = self.capture(draw)
        with patch.object(atlas, "_submit_quads", wraps=atlas._submit_quads) as submits:
            batched = self.capture(draw)
        self.assertEqual(view.primitives.stats["crowd_atlas_draws"], 23)
        self.assertEqual(view.primitives.stats["crowd_atlas_batched_bodies"], 21)
        # 그림자 1묶음과 두 공격 이펙트·록온으로 나뉜 본체 4묶음
        self.assertEqual(submits.call_count, 5)
        self.assertGreater(np.any(baseline[200:305, 201:321] != [140, 170, 200], axis=2).sum(), 100)
        self.assertLessEqual(np.abs(batched - baseline).max(), 1)

        with patch("ferrial_drive.rendering.enemy_crowd_atlas.MAX_QUADS", 6), \
                patch.object(atlas, "_submit_quads", wraps=atlas._submit_quads) as submits:
            split = self.capture(draw)
        self.assertEqual(submits.call_count, 9)
        np.testing.assert_array_equal(split, batched)

    def test_deferred_shades_both_profiles_once_and_keeps_body_placement(self):
        from ferrial_drive.rendering.enemy_deferred_pbr import EnemyDeferredPbr

        requests = {"small": [("a", "move", "0", .18, 180, 240), ("b", "attack", "1", .35, 210, 265)],
                    "medium": [("c", "move", "3", .4, 260, 240), ("d", "attack", "4", .5, 275, 260)]}
        deferred = EnemyDeferredPbr(self.pico)
        self.addCleanup(deferred.close)

        def draw_reference():
            for kind, rows in requests.items():
                sprite = self.sprites[kind]
                records = sprite.prepare_bodies(rows, .7)
                self.assertEqual(len(records), 2)
                for enemy_id, *_ in rows:
                    sprite.body_batch.copy(records[enemy_id])

        def draw_deferred():
            records = deferred.prepare(requests, self.sprites, .7)
            self.assertEqual((len(records), deferred.light_submits), (4, 1))
            for rows in requests.values():
                for enemy_id, *_ in rows:
                    deferred.copy(records[enemy_id])

        self.compare(draw_reference, draw_deferred, 8)

    def test_deferred_depth_skips_covered_tile_pixels_and_preserves_blending(self):
        import numpy as np
        from ferrial_drive.rendering.enemy_deferred_pbr import EnemyDeferredPbr

        requests = {"small": [("behind", "move", "0", .18, 202, 230),
                              ("front", "move", "0", .18001, 204, 230)]}
        ranks = {"behind": 2, "front": 1}
        baseline = EnemyDeferredPbr(self.pico)
        uniforms = EnemyDeferredPbr(self.pico, screen_depth=True, batch_upload=False)
        experiment = EnemyDeferredPbr(self.pico, screen_depth=True)
        cached = EnemyDeferredPbr(self.pico, screen_depth=True, cache_keypose_samples=True)
        fp16 = EnemyDeferredPbr(self.pico, screen_depth=True, cache_keypose_samples=True, keypose_samples_fp16=True)
        offsets = EnemyDeferredPbr(self.pico, screen_depth=True, cache_keypose_samples=True,
                                   keypose_samples_fp16=True, keypose_samples_offsets=True)
        for renderer in (baseline, uniforms, experiment, cached, fp16, offsets):
            self.addCleanup(renderer.close)

        def draw(renderer, *, behind_only=False):
            records = renderer.prepare(requests, self.sprites, .7, body_depth_ranks=ranks)
            self.assertEqual(len(records), len(ranks))
            for enemy_id in sorted(ranks, key=ranks.get, reverse=True):
                if not behind_only or enemy_id == "behind":
                    renderer.copy(records[enemy_id])

        def compare_fp16(renderer, reference, tiles):
            result = self.capture(lambda: draw(renderer))
            error = np.abs(reference - result)
            nonbackground = np.any(reference != [140, 170, 200], axis=2) | np.any(result != [140, 170, 200], axis=2)
            self.assertEqual(renderer.keypose_cached_tiles, tiles)
            mean_error = error[nonbackground].mean()
            self.assertLess(mean_error, .5)
            self.assertLess(np.any(error[nonbackground] > 4, axis=1).mean(), .01)
            np.testing.assert_array_equal(result, self.capture(lambda: draw(renderer)))
            return mean_error

        reference = self.capture(lambda: draw(baseline))
        result = self.capture(lambda: draw(experiment))
        np.testing.assert_array_equal(reference, result)
        np.testing.assert_array_equal(self.capture(lambda: draw(uniforms)), result)
        np.testing.assert_array_equal(self.capture(lambda: draw(cached)), result)
        self.assertEqual(cached.keypose_cached_tiles, 2)
        self.assertGreater(cached.keypose_buffer.storage_bytes, 16)
        absolute_error = compare_fp16(fp16, result, 2)
        self.assertLessEqual(compare_fp16(offsets, result, 2), absolute_error)
        self.assertEqual(fp16.keypose_buffer.sample_bytes * 2, cached.keypose_buffer.sample_bytes)
        self.assertLessEqual(fp16.keypose_buffer.storage_bytes, cached.keypose_buffer.storage_bytes)
        self.assertEqual(offsets.keypose_buffer.storage_bytes, fp16.keypose_buffer.storage_bytes)
        self.assertEqual((experiment.depth_submits, experiment.depth_bodies, experiment.depth_tested_tiles), (1, 2, 2))
        self.assertEqual((uniforms.instance_uploads, uniforms.instance_upload_bytes), (6, 192))
        self.assertEqual((experiment.instance_uploads, experiment.instance_upload_bytes), (1, 96))

        full = self.capture(lambda: draw(baseline, behind_only=True))
        culled = self.capture(lambda: draw(experiment, behind_only=True))
        background = np.array([140, 170, 200])
        removed = np.any(full != background, axis=2) & np.all(culled == background, axis=2)
        self.assertGreater(removed.sum(), 50)
        self.assertGreater(np.any(culled != background, axis=2).sum(), 20)

        requests["small"].append(("reused", "move", "0", .18, 414, 465))
        ranks["reused"] = 3
        result = self.capture(lambda: draw(experiment))
        np.testing.assert_array_equal(self.capture(lambda: draw(uniforms)), result)
        np.testing.assert_array_equal(self.capture(lambda: draw(cached)), result)
        self.assertEqual(cached.keypose_cached_tiles, 1)
        compare_fp16(fp16, result, 1)
        compare_fp16(offsets, result, 1)
        self.assertEqual((experiment.depth_bodies, experiment.depth_tested_tiles), (3, 1))
        self.assertEqual((experiment.instance_uploads, experiment.instance_upload_bytes), (1, 144))

        requests["small"] = [("behind", "move", "0", .18, 12, 230)]
        requests["medium"] = [("front", "attack", "4", .500012, 21, 230)]
        del ranks["reused"]
        result = self.capture(lambda: draw(experiment))
        # 클리핑된 쿼드의 픽셀 중심을 두 패스에서 같게 계산할 때 최종 RGBA8에 반올림 차이가 날 수 있다.
        np.testing.assert_allclose(self.capture(lambda: draw(cached)), result, rtol=0, atol=1)
        self.assertEqual(cached.keypose_cached_tiles, 2)
        compare_fp16(fp16, result, 2)
        compare_fp16(offsets, result, 2)

        del requests["medium"]
        del ranks["front"]
        result = self.capture(lambda: draw(experiment))
        np.testing.assert_array_equal(self.capture(lambda: draw(cached)), result)
        np.testing.assert_array_equal(self.capture(lambda: draw(fp16)), result)
        np.testing.assert_array_equal(self.capture(lambda: draw(offsets)), result)
        self.assertEqual(cached.keypose_cached_tiles, 0)
        self.assertEqual(fp16.keypose_cached_tiles, 0)
        self.assertEqual(offsets.keypose_cached_tiles, 0)

    def test_deferred_box_mask_submits_both_profiles_once(self):
        import numpy as np
        from ferrial_drive.rendering.enemy_shadow_batch import EnemyBoxMask

        mask = EnemyBoxMask(self.pico)
        self.addCleanup(mask.close)
        groups = {"small": [(("move/u0l0", .18), [(200, 260), (213, 255)])],
                  "medium": [(("move/u3l3", .4), [(242, 264)])]}
        pixels = self.capture(lambda: self.assertEqual(mask.draw(groups, self.sprites, 1, .5, (512, 512)), 3))
        self.assertEqual(mask.submits, 1)
        self.assertGreater(np.any(pixels != [140, 170, 200], axis=2).sum(), 100)

    def test_one_shadow_tile_spans_multiple_placement_batches(self):
        sprite = self.sprites["medium"]
        scale = .77 / sprite.resource.data["pixel_scale"]
        points = [(35.25 + i % 9 * 51, 72.75 + i // 9 * 42) for i in range(71)]
        groups = [((sprite.part_clip("move", "se"), .125), points),
                  ((sprite.part_clip("attack", "n"), .25), points[-3:])]

        def individual():
            for pose, positions in groups:
                sprite.draw_ground_shadows(pose, positions, scale, .55, 3)

        def batched():
            self.assertEqual(sprite.draw_near_shadows(groups, scale, .55, 3), (74, 2))

        self.compare(individual, batched, 8)

    def test_shared_texture_can_cross_only_disjoint_bodies(self):
        sprite = self.sprites["small"]
        cache = sprite.shared_frames()
        zoom = 1 / (sprite.scale * sprite.resource.data["pixel_scale"])
        renderer = PicoRenderer({}, {})
        self.addCleanup(renderer.close)
        view = EncounterView(renderer, None, None, backend="immediate")
        self.addCleanup(view.primitives.close)
        enemy = SimpleNamespace(profile=SimpleNamespace(kind="small"), phase="move")
        rows = []
        placements = [("s", 90), ("e", 430)] * 4 + [("e", 97), ("s", 99)]
        for i, (direction, x) in enumerate(placements):
            rows.append((210 + i, x, enemy, sprite, ("move", direction, 0.), True))

        def paint():
            for foot, x, _, _, (motion, direction, _), _ in rows:
                cache.draw(sprite.part_clip(motion, direction), 0, x, foot, sprite.scale * zoom)

        baseline = self.capture(paint)
        runs = list(view._body_runs(rows, zoom))
        self.assertEqual([(key[3], len(points)) for key, points, _ in runs], [("s", 4), ("e", 5), ("s", 1)])

        def batched():
            for (_, _, motion, direction, index), points, _ in runs:
                cache.draw_bodies(sprite.part_clip(motion, direction), index, points, sprite.scale * zoom)

        self.assertTrue((baseline != [140, 170, 200]).any())
        self.assertTrue((baseline == self.capture(batched)).all())

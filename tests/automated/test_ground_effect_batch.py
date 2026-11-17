"""입자 제출 순서·버퍼 재사용과 실제 GL의 개별/배치 픽셀·상태 복원을 검사한다."""

import ctypes as ct
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ferrial_drive.combat.ground_effects import GroundParticle
from ferrial_drive.rendering.ground_effect_batch import GroundEffectBatch, INSTANCE_FLOATS


class BatchBufferTests(unittest.TestCase):
    def batch(self):
        batch = GroundEffectBatch.__new__(GroundEffectBatch)
        batch.capacity, batch.count, batch.max_rows = 0, 0, 1024
        batch.data, batch.runs = None, []
        batch.begin()
        return batch

    def test_only_adjacent_textures_merge_and_input_order_is_preserved(self):
        batch = self.batch()
        for index, texture in enumerate((11, 11, 22, 11)):
            batch.append(texture, (32, 32), (index,) * INSTANCE_FLOATS)
        self.assertEqual([(row[0], row[2], row[3]) for row in batch.runs], [(11, 0, 2), (22, 2, 1), (11, 3, 1)])
        self.assertEqual([batch.data[i * INSTANCE_FLOATS] for i in range(4)], [0, 1, 2, 3])

    def test_growth_preserves_rows_and_next_pass_reuses_capacity(self):
        batch = self.batch()
        for index in range(70):
            batch.append(11, (32, 32), (index,) * INSTANCE_FLOATS)
        self.assertEqual(batch.data[69 * INSTANCE_FLOATS], 69)
        self.assertEqual(batch.data[0], 0)
        data = batch.data
        batch.begin()
        batch.append(22, (32, 32), (7,) * INSTANCE_FLOATS)
        self.assertIs(batch.data, data)
        self.assertEqual(batch.stats["buffer_allocations"], 0)
        self.assertEqual(batch.count, 1)


@unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS") == "1", "실제 GPU 선택 검사")
class GroundBatchGpuTests(unittest.TestCase):
    def setUp(self):
        import pico2d.pico2d as pico
        from ferrial_drive.diagnostics.gpu_profile import Uhd630Profile
        from ferrial_drive.rendering.canvas import PicoCanvas
        from ferrial_drive.rendering.pico_ground_effects import PicoGroundEffects
        self.environment = patch.dict(os.environ, SDL_VIDEODRIVER="windows")
        self.environment.start()
        original = pico.SDL_CreateWindow
        self.hidden = patch.object(pico, "SDL_CreateWindow", side_effect=lambda title, x, y, w, h, flags:
            original(title, x, y, w, h, (flags & ~pico.SDL_WINDOW_SHOWN) | pico.SDL_WINDOW_HIDDEN))
        self.hidden.start()
        self.canvas = PicoCanvas(128, 128, "지면 효과 배치 검사").open()
        self.pico = pico
        self.guard = Uhd630Profile(pico)
        self.guard.__enter__()
        self.temporary = TemporaryDirectory(prefix="ground-batch-")
        directory = Path(self.temporary.name)
        surface = pico.SDL_CreateRGBSurfaceWithFormat(0, 32, 32, 32, pico.SDL_PIXELFORMAT_RGBA32)
        try:
            pixels = (ct.c_ubyte * (32 * 32 * 4)).from_address(surface.contents.pixels)
            for y in range(32):
                for x in range(32):
                    i = (y * 32 + x) * 4
                    pixels[i:i+4] = (40 + x * 5, 30 + y * 6, 120, min(255, (x + y) * 5))
            self.assertEqual(pico.IMG_SavePNG(surface, str(directory / "pattern.png").encode("utf-8")), 0)
        finally:
            pico.SDL_FreeSurface(surface)
        kinds = ("scrape_gray", "dirt_debris_gray", "smoke_gray", "foot_friction", "trail", "trail_echo", "spark", "energy_orb")
        atlas = {kind: {"file": "pattern.png", "size_px": [32, 32], "variants": [
            {"source_rect_top_left_px": [4, 4, 24, 24]}]} for kind in kinds}
        path = directory / "atlas.json"
        path.write_text(json.dumps({"assets": atlas}), encoding="utf-8")
        self.renderer = PicoGroundEffects(pico, path)
        self.camera = SimpleNamespace(zoom=1, world_to_screen=lambda point: point)
        self.effects = SimpleNamespace(particles=[GroundParticle(kind, (44 + i * 5, 56 + i % 2 * 5),
            (3, 2), (42, 25), .17 * (i - 2), 1, 0, color="#88BBEE", opacity=.65,
            age_seconds=.2, detail=.4, roundness=.2, mirror_x=bool(i % 2), emitter="back_l")
            for i, kind in enumerate((*kinds, "smoke_gray", "smoke_gray", "scrape_gray"))],
            reverse_motion=False, emitter_origins={"back_l": (55, 58)}, near_front_pixels=18)

    def tearDown(self):
        try:
            self.renderer.close()
            self.guard.__exit__(None, None, None)
            self.canvas.close()
            self.temporary.cleanup()
        finally:
            self.hidden.stop()
            self.environment.stop()

    def pixels(self):
        p = self.pico
        data = (ct.c_ubyte * (128 * 128 * 4))()
        self.assertEqual(p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32, data, 512), 0)
        return bytes(data)

    def render(self, backend):
        p = self.pico
        p.SDL_SetRenderDrawColor(p.renderer, 16, 24, 32, 255)
        p.SDL_RenderClear(p.renderer)
        self.renderer.backend = backend
        for foreground in (False, True):
            self.renderer.draw(self.effects, self.camera, foreground=foreground)
        # 후속 SDL 렌더링까지 포함해 GL 상태 복원을 확인한다.
        p.SDL_SetRenderDrawColor(p.renderer, 255, 80, 32, 255)
        p.SDL_RenderFillRect(p.renderer, p.SDL_Rect(112, 112, 10, 10))
        return self.pixels()

    def test_individual_and_batch_match_with_clip_scale_target_and_reverse_split(self):
        p = self.pico
        target = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA8888, p.SDL_TEXTUREACCESS_TARGET, 128, 128)
        try:
            for destination in (None, target):
                for reverse in (False, True):
                    with self.subTest(target=bool(destination), reverse=reverse):
                        self.effects.reverse_motion = reverse
                        p.SDL_SetRenderTarget(p.renderer, destination)
                        p.SDL_RenderSetScale(p.renderer, .9, .9)
                        clip = p.SDL_Rect(8, 10, 116, 114)
                        p.SDL_RenderSetClipRect(p.renderer, ct.byref(clip))
                        before, after = self.render("individual"), self.render("batched")
                        self.assertLessEqual(max(abs(a-b) for a, b in zip(before, after)), 2)
        finally:
            p.SDL_RenderSetScale(p.renderer, 1, 1)
            p.SDL_RenderSetClipRect(p.renderer, None)
            p.SDL_SetRenderTarget(p.renderer, None)
            p.SDL_DestroyTexture(target)
        self.assertFalse(self.guard.violations)

    def test_same_texture_particles_collapse_to_one_submit_and_reuse_buffer(self):
        particle = self.effects.particles[2]
        self.effects.particles = [particle] * 100
        self.renderer.draw(self.effects, self.camera)
        self.assertEqual(self.renderer.stats["particles"], 100)
        self.assertEqual(self.renderer.stats["submits"], 1)
        data = self.renderer.batch_sampler.data
        self.renderer.draw(self.effects, self.camera)
        self.assertIs(self.renderer.batch_sampler.data, data)
        self.assertEqual(self.renderer.stats["buffer_allocations"], 0)
        self.assertEqual(self.renderer.stats["upload_bytes"], 100 * 112)

    def test_mixed_artwork_keeps_order_in_a_single_submit(self):
        self.renderer.draw(self.effects, self.camera)
        self.assertGreater(self.renderer.stats["particles"], 5)
        self.assertEqual(self.renderer.stats["submits"], 1)

    def test_failed_submission_restores_state_and_next_pass_is_clean(self):
        sampler = self.renderer.batch_sampler
        with patch.object(self.pico, "SDL_GL_BindTexture", return_value=-1):
            with self.assertRaisesRegex(RuntimeError, "텍스처 OpenGL 연결 실패"):
                self.renderer.draw(self.effects, self.camera)
        self.assertEqual(sampler.depth, 0)
        self.renderer.draw(self.effects, self.camera)
        self.assertEqual(self.renderer.stats["submits"], 1)

    def test_texture_unit_and_unpack_state_are_restored(self):
        sampler = self.renderer.batch_sampler
        texture = ct.c_uint()
        sampler.glGenTextures(1, ct.byref(texture))
        sampler.glActiveTexture(0x84C1)
        sampler.glBindTexture(0x0DE1, texture.value)
        sampler.glActiveTexture(0x84C3)
        keys = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
        expected = (8, 17, 2, 3)
        for key, value in zip(keys, expected):
            sampler.glPixelStorei(key, value)
        try:
            self.renderer.draw(self.effects, self.camera)
            self.assertEqual(sampler.integer(0x84E0), 0x84C3)
            self.assertEqual(tuple(sampler.integer(key) for key in keys), expected)
            sampler.glActiveTexture(0x84C1)
            self.assertEqual(sampler.integer(0x8069), texture.value)
        finally:
            sampler.glBindTexture(0x0DE1, 0)
            sampler.glDeleteTextures(1, ct.byref(texture))
            sampler.glActiveTexture(0x84C0)
            for key, value in zip(keys, (4, 0, 0, 0)):
                sampler.glPixelStorei(key, value)


if __name__ == "__main__":
    unittest.main()

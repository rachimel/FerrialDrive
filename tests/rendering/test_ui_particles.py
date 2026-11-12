"""파티클 아틀라스의 업로드 횟수·묶음 출력·해제와 소프트 마스크를 검사한다."""

import ctypes
import unittest
from unittest.mock import patch

import test_directional_blur as blur_tests
from ferrial_drive.ui_v2.particle_texture import ATLAS_SIZE, build_particle_atlas
from ferrial_drive.ui_v2.effects import AbsorptionTrail


class ParticleTextureTests(unittest.TestCase):
    setUp = blur_tests.DirectionalBlurTests.setUp
    tearDown = blur_tests.DirectionalBlurTests.tearDown
    pixels = blur_tests.DirectionalBlurTests.pixels

    def instance_settings(self):
        return dict(renderer='instanced', samples=24, tail_fraction=0.3, head_width_pixels=4, orb_radius_pixels=4)

    def test_gpu_instancing_draws_orb_and_reuses_uploaded_paths(self):
        trail = AbsorptionTrail((20, 20), (40, 30), (70, 40), 1)
        self.renderer.draw_instanced_particles([trail], self.instance_settings(), '#FFFFFF', '#FFFFFF', 1)
        sampler = self.renderer.particle_instances
        self.assertEqual(sampler.path_uploads, 1)
        self.assertEqual(sampler.instance_upload_bytes, 16)
        self.assertGreater(self.pixels()[(20 * 96 + 20) * 4], 150)
        with patch.object(sampler, 'glDrawArraysInstanced', wraps=sampler.glDrawArraysInstanced) as draw:
            trail.elapsed_seconds = 0.5
            self.renderer.draw_instanced_particles([trail], self.instance_settings(), '#FFFFFF', '#FFFFFF', 1)
            self.assertEqual(draw.call_count, 2)
        self.assertEqual(sampler.path_uploads, 1)
        self.renderer.close()
        self.assertEqual(sampler.program, 0)
        self.assertFalse(sampler.textures)

    def test_large_instance_batch_restores_sdl_pixel_unpack_state(self):
        trail = AbsorptionTrail((20, 20), (40, 30), (70, 40), 1, elapsed_seconds=0.5)
        self.renderer.draw_instanced_particles([trail], self.instance_settings(), '#FFFFFF', '#FFFFFF', 1)
        sampler = self.renderer.particle_instances
        keys = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
        original = tuple(sampler.integer(key) for key in keys)
        try:
            for key, value in zip(keys, (8, 17, 3, 2)):
                sampler.glPixelStorei(key, value)
            self.renderer.draw_instanced_particles([trail] * 512, self.instance_settings(), '#FFFFFF', '#FFFFFF', 1)
            self.assertEqual(tuple(sampler.integer(key) for key in keys), (8, 17, 3, 2))
            self.assertEqual(sampler.instance_upload_bytes, 512 * 16)
        finally:
            for key, value in zip(keys, original):
                sampler.glPixelStorei(key, value)

    def test_soft_atlas_has_transparent_orb_corners_and_a_bright_center(self):
        data = build_particle_atlas()
        width, height = ATLAS_SIZE
        alpha = lambda x, y: data[(y * width + x) * 4 + 3]
        self.assertEqual(len(data), width * height * 4)
        self.assertEqual(alpha(0, 0), 0)
        self.assertGreater(alpha(32, 32), 250)
        self.assertGreater(alpha(32, 32), alpha(45, 32))
        self.assertEqual(alpha(70, 32), alpha(120, 32))

    def test_one_upload_and_one_geometry_submission_per_nonempty_batch(self):
        points = ((40, 24), (48, 24), (48, 32), (40, 32))
        colors = ((255, 255, 255, 255),) * 4
        quad = (points, colors, 0)
        with patch.object(self.p, 'SDL_CreateTextureFromSurface', wraps=self.p.SDL_CreateTextureFromSurface) as upload, \
                patch.object(self.p, 'SDL_RenderGeometry', wraps=self.p.SDL_RenderGeometry) as draw:
            for _ in range(3):
                self.renderer.particle_quads([quad, quad])
            self.assertEqual(upload.call_count, 1)
            self.assertEqual(draw.call_count, 3)
            self.assertEqual(draw.call_args.args[3], 8)
        data = self.pixels()
        self.assertGreater(data[(28 * 96 + 44) * 4], 200)
        self.assertEqual(data[(24 * 96 + 40) * 4], 0)
        texture = ctypes.cast(self.renderer.particle_texture, ctypes.c_void_p).value
        self.assertTrue(texture)
        self.renderer.close()
        self.assertIsNone(self.renderer.particle_texture)

    def test_empty_batch_does_not_create_texture(self):
        self.renderer.particle_quads([])
        self.assertIsNone(self.renderer.particle_texture)


if __name__ == '__main__':
    unittest.main()

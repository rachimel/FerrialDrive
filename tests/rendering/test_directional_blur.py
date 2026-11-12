"""실제 OpenGL 방향성 필터의 연속성·방향·알파·상태 복원·자원 수명을 검사한다."""

from ctypes import c_ubyte
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ferrial_drive.rendering import PicoCanvas
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer


class DirectionalBlurTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ)
        self.environment.start()
        os.environ.pop('SDL_VIDEODRIVER', None)
        import pico2d.pico2d as p
        self.p = p
        create_window = p.SDL_CreateWindow
        def hidden(title, x, y, width, height, flags):
            return create_window(title, x, y, width, height, (flags & ~p.SDL_WINDOW_SHOWN) | p.SDL_WINDOW_HIDDEN)
        with patch.object(p, 'SDL_CreateWindow', side_effect=hidden):
            self.canvas = PicoCanvas(96, 64, 'Directional blur tests').open()
        self.renderer = PicoV2Renderer({}, {})
        self.assertEqual(self.canvas.info.name, 'opengl')
        self.renderer.clear('#000000')

    def tearDown(self):
        self.renderer.close()
        self.canvas.close()
        self.environment.stop()

    def pixels(self):
        data = (c_ubyte * (96 * 64 * 4))()
        self.assertEqual(self.p.SDL_RenderReadPixels(self.p.renderer, None, self.p.SDL_PIXELFORMAT_RGBA32,
                                                   data, 96 * 4), 0)
        return bytes(data)

    def test_both_directions_form_centered_continuous_streak_without_repeated_shapes(self):
        for displacement in (12, -12):
            self.renderer.clear('#000000')
            with self.renderer.directional_blur(Rect(40, 24, 6, 8), (displacement, 0), 1):
                self.renderer.rect(Rect(40, 24, 6, 8), '#FFFFFF')
            data = self.pixels()
            row = [data[(28 * 96 + x) * 4] for x in range(96)]
            support = [x for x, value in enumerate(row) if value > 0]
            self.assertGreater(len(support), 6)
            self.assertEqual(support, list(range(min(support), max(support) + 1)))
            self.assertLess(min(support), 40)
            self.assertGreater(max(support), 45)
            center = sum(x * value for x, value in enumerate(row)) / sum(row)
            self.assertAlmostEqual(center, 42.5, delta=0.05)

    def test_changing_blur_width_does_not_move_visible_center(self):
        centers = []
        for displacement in (0, 0.1, 1, 8, 24, 48, 8, 0):
            self.renderer.clear('#000000')
            with self.renderer.directional_blur(Rect(40, 24, 6, 8), (displacement, 0), 0.9, 49):
                self.renderer.rect(Rect(40, 24, 6, 8), '#FFFFFF')
            data = self.pixels()
            row = [data[(28 * 96 + x) * 4] for x in range(96)]
            centers.append(sum(x * value for x, value in enumerate(row)) / sum(row))
        self.assertLess(max(centers) - min(centers), 0.1)

    def test_translucent_layer_is_not_multiplied_by_alpha_twice(self):
        with self.renderer.directional_blur(Rect(24, 20, 40, 20), (8, 0), 1):
            self.renderer.rect(Rect(24, 20, 40, 20), '#FF0000', 0.5)
        data = self.pixels()
        red = data[(28 * 96 + 40) * 4]
        self.assertGreaterEqual(red, 120)
        self.assertLessEqual(red, 130)

    def test_sdl_state_is_restored_on_success_and_failure(self):
        with self.renderer.scaled(0.8, (48, 32)), self.renderer.clip(Rect(2, 3, 90, 55)):
            before = self.renderer.draw_transform()
            with self.renderer.directional_blur(Rect(20, 20, 20, 20), (8, 0), 0.75):
                self.renderer.rect(Rect(20, 20, 20, 20), '#FFFFFF')
            self.assertEqual(self.renderer.draw_transform(), before)
            with self.assertRaises(RuntimeError):
                with self.renderer.directional_blur(Rect(20, 20, 20, 20), (8, 0), 0.75):
                    raise RuntimeError('의도한 그리기 실패')
            self.assertEqual(self.renderer.draw_transform(), before)
            self.assertFalse(self.p.SDL_GetRenderTarget(self.p.renderer))

    def test_render_target_is_reused_and_resources_are_released(self):
        textures = []
        import ctypes
        for x in (20, 25):
            with self.renderer.directional_blur(Rect(x, 20, 20, 20), (8, 0), 0.75):
                self.renderer.rect(Rect(x, 20, 20, 20), '#FFFFFF')
            textures.append(ctypes.cast(self.renderer.motion_texture, ctypes.c_void_p).value)
        self.assertEqual(textures[0], textures[1])
        sampler = self.renderer.motion_sampler
        self.renderer.close()
        self.assertEqual(sampler.program, 0)
        self.assertIsNone(self.renderer.motion_texture)


if __name__ == '__main__':
    unittest.main()

"""실제 SDL 도형 필터의 경계 픽셀·캐시·렌더 상태 복원을 확인한다."""

from ctypes import byref, c_float, c_ubyte
import os
import unittest
from unittest.mock import patch

from ferrial_drive.rendering import PicoCanvas
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer


class UiV2FilteringTests(unittest.TestCase):
    def setUp(self):
        self.previous_driver = os.environ.get("SDL_VIDEODRIVER")
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        self.canvas = PicoCanvas(96, 96, "UI filter check").open()
        self.renderer = PicoV2Renderer({}, {})
        self.pico = self.renderer.pico
        self.shape = (((10.25, 10.25), (70.25, 10.25), (10.25, 70.25)),)

    def tearDown(self):
        self.renderer.close()
        self.canvas.close()
        if self.previous_driver is None:
            os.environ.pop("SDL_VIDEODRIVER", None)
        else:
            os.environ["SDL_VIDEODRIVER"] = self.previous_driver

    def red_values(self):
        pixels = (c_ubyte * (96 * 96 * 4))()
        self.assertEqual(self.pico.SDL_RenderReadPixels(self.pico.renderer, None,
                         self.pico.SDL_PIXELFORMAT_RGBA32, pixels, 96 * 4), 0)
        return set(pixels[::4])

    def render_state(self):
        p = self.pico
        sx, sy = c_float(), c_float()
        viewport, clip = p.SDL_Rect(), p.SDL_Rect()
        p.SDL_RenderGetScale(p.renderer, byref(sx), byref(sy))
        p.SDL_RenderGetViewport(p.renderer, byref(viewport))
        p.SDL_RenderGetClipRect(p.renderer, byref(clip))
        return (bool(p.SDL_GetRenderTarget(p.renderer)), sx.value, sy.value,
                tuple(getattr(viewport, key) for key in ("x", "y", "w", "h")),
                bool(p.SDL_RenderIsClipEnabled(p.renderer)),
                tuple(getattr(clip, key) for key in ("x", "y", "w", "h")))

    def test_filter_adds_partial_coverage_to_diagonal_edges(self):
        self.renderer.clear("#000000")
        self.renderer.filled_triangle(*self.shape[0], "#FFFFFF")
        self.assertEqual(self.red_values(), {0, 255})
        self.renderer.clear("#000000")
        self.renderer.filtered_polygons(self.shape, "#FFFFFF")
        self.assertTrue(any(0 < value < 255 for value in self.red_values()))

    def test_cache_reuses_translation_and_opacity_and_releases_textures(self):
        self.renderer.filtered_polygons(self.shape, "#FFFFFF")
        shifted = tuple(tuple((x + 4, y + 4) for x, y in polygon) for polygon in self.shape)
        self.renderer.clear("#000000")
        self.renderer.filtered_polygons(shifted, "#FFFFFF", 0.5)
        self.assertEqual(len(self.renderer.filtered_textures), 1)
        self.assertIn(max(self.red_values()), (127, 128))
        self.renderer.close()
        self.assertFalse(self.renderer.filtered_textures)

    def test_filter_restores_scaled_viewport_and_clip_even_after_failure(self):
        with self.renderer.scaled(0.8, (48, 48)), self.renderer.clip(Rect(4, 5, 70, 72)):
            before = self.render_state()
            self.renderer.filtered_polygons(self.shape, "#FFFFFF")
            self.assertEqual(self.render_state(), before)
            with patch.object(self.renderer, "filled_triangle", side_effect=RuntimeError("의도한 검사 실패")):
                with self.assertRaises(RuntimeError):
                    self.renderer.filtered_polygons(self.shape, "#FF0000")
            self.assertEqual(self.render_state(), before)
            self.assertEqual(len(self.renderer.filtered_textures), 1)

    def test_scrolling_scanlines_reuse_patterns_and_release_them(self):
        images = []
        for frame in range(120):
            self.renderer.clear("#000000")
            self.renderer.scanline_layer(self.shape[0], "#91AEBB", 0.1, 4, 1, frame / 60 * 3)
            self.renderer.scanline_layer(self.shape[0], "#FFFFFF", 0.22, 4, 1, frame / 60 * 3,
                                          bright_band=(frame / 60 * 120 % 84 - 24, 24))
            if frame in (0, 30):
                pixels = (c_ubyte * (96 * 96 * 4))()
                self.assertEqual(self.pico.SDL_RenderReadPixels(self.pico.renderer, None,
                                 self.pico.SDL_PIXELFORMAT_RGBA32, pixels, 96 * 4), 0)
                images.append(bytes(pixels))
        self.assertNotEqual(*images)
        self.assertEqual(len(self.renderer.scanline_textures), 2)
        self.assertFalse(self.renderer.filtered_textures)
        for height in (8, 19, 24, 26, 70, 130, 160, 414):
            shape = ((10, 10), (50, 10), (50, 10 + height), (10, 10 + height))
            for color in ("#91AEBB", "#FFFFFF"):
                self.renderer.scanline_layer(shape, color, 0.1, 4, 1, 2)
        self.assertLessEqual(len(self.renderer.scanline_textures), 8)
        self.renderer.close()
        self.assertFalse(self.renderer.scanline_textures)

    def test_global_scanline_rows_and_bright_band_align_across_scaled_panels(self):
        p = self.pico
        left = ((0, 0), (45, 0), (45, 96), (0, 96))
        right = ((96, 0), (192, 0), (192, 192), (96, 192))
        for band in (None, (25, 24)):
            self.renderer.clear("#000000")
            self.renderer.scanline_layer(left, "#FFFFFF", 1, 4, 1, 1.5, bright_band=band)
            with self.renderer.scaled(0.5, (0, 6)):
                viewport = p.SDL_Rect(0, 6, 192, 192)
                p.SDL_RenderSetViewport(p.renderer, byref(viewport))
                self.renderer.scanline_layer(right, "#FFFFFF", 1, 4, 1, 1.5, bright_band=band)
            pixels = (c_ubyte * (96 * 96 * 4))()
            self.assertEqual(p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32, pixels, 96 * 4), 0)
            for y in range(5, 90):
                self.assertLessEqual(abs(pixels[(y * 96 + 20) * 4] - pixels[(y * 96 + 70) * 4]), 2)


if __name__ == "__main__":
    unittest.main()

"""실제 SDL 도형 필터의 경계 픽셀·캐시·렌더 상태 복원을 확인한다."""

from ctypes import byref, c_float, c_ubyte
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ferrial_drive.rendering import PicoCanvas
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer
from ferrial_drive.ui_v2.panel_probe import PanelProbeRenderer
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui_v2.view import UiV2View
from ferrial_drive.ui_v2.lock_on import LockOnVisual


class UiV2FilteringTests(unittest.TestCase):
    def test_lock_label_caret_renders_with_actual_renderer(self):
        root = Path(__file__).resolve().parents[2]
        config = UiConfig(root / "samples/ui_unit_test_v2/ui_config.json")
        renderer = PicoV2Renderer(config.font_paths, config.font_sizes)
        try:
            view = UiV2View(config, renderer)
            view.lock_marker(LockOnVisual("a", Rect(32, 32, 12, 12), label_progress=0.5), 1)
            self.assertTrue(renderer.textures)
        finally:
            renderer.close()

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

    def test_film_grain_is_subtle_masked_and_reuses_animation_frames(self):
        images = []
        for frame in (0, 1, 0):
            self.renderer.clear("#000000")
            self.renderer.film_grain(self.shape[0], 0.08, frame)
            pixels = (c_ubyte * (96 * 96 * 4))()
            self.assertEqual(self.pico.SDL_RenderReadPixels(self.pico.renderer, None,
                             self.pico.SDL_PIXELFORMAT_RGBA32, pixels, 96 * 4), 0)
            self.assertEqual(pixels[(80 * 96 + 80) * 4], 0)
            self.assertLessEqual(max(pixels[::4]), 21)
            self.assertGreater(max(pixels[::4]), 0)
            images.append(bytes(pixels))
        self.assertNotEqual(images[0], images[1])
        self.assertEqual(images[0], images[2])
        self.assertEqual(len(self.renderer.grain_textures), 2)
        self.renderer.close()
        self.assertFalse(self.renderer.grain_textures)

    def test_neon_preserves_crisp_core_and_limits_halo(self):
        with patch.object(self.renderer, "text") as draw, patch.object(self.renderer, "_draw_neon_glow") as glow:
            self.renderer.neon_text("45", 20, 30, "ammo", "#FFFFFF", 0.5,
                                     glow_color="#91AEBB", radius_pixels=2, glow_opacity=0.12)
            self.assertEqual(draw.call_args.args, ("45", 20, 30, "ammo", "#FFFFFF", 0.5))
            self.assertEqual(draw.call_count, 1)
            self.assertEqual(glow.call_args.args, ("45", 20, 30, "ammo", "#91AEBB", 0.06, 2))

    def test_panel_probe_matches_real_scale_viewport_and_clip_without_drawing(self):
        shape = ((10, 10), (80, 10), (80, 80), (10, 80))
        probe = PanelProbeRenderer(self.renderer)
        with self.renderer.scaled(0.8, (48, 96)), probe.scaled(0.8, (48, 96)):
            with self.renderer.clip(Rect(20, 25, 40, 30)), probe.clip(Rect(20, 25, 40, 30)):
                actual = self.renderer.panel_y_range(shape)
                probe.include(shape)
                self.assertEqual(actual, probe.ranges[0])
        self.assertFalse(self.renderer.scanline_textures)
        self.assertFalse(self.renderer.filtered_textures)

    def test_neon_blur_extends_glyph_mask_and_reuses_texture(self):
        font = Path(__file__).resolve().parents[2] / "data/fonts/Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf"
        renderer = PicoV2Renderer({"text": font}, {"text": 24})
        p = self.pico
        def pixels():
            data = (c_ubyte * (96 * 96 * 4))()
            self.assertEqual(p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32, data, 96 * 4), 0)
            return tuple(zip(data[::4], data[1::4], data[2::4]))
        try:
            renderer.clear("#000000")
            renderer.text("45", 20, 20, "text", "#FFFFFF", 0.82)
            normal = pixels()
            renderer.clear("#000000")
            renderer.neon_text("45", 20, 20, "text", "#FFFFFF", 0.82,
                               glow_color="#65DCC8", radius_pixels=4, glow_opacity=0.12)
            blurred = pixels()
            halo = [rgb for before, rgb in zip(normal, blurred) if before == (0, 0, 0) and max(rgb) > 0]
            self.assertTrue(halo)
            self.assertTrue(any(green > blue > red for red, green, blue in halo))
            renderer.neon_text("45", 20, 20, "text", "#FFFFFF", 0.82,
                               glow_color="#65DCC8", radius_pixels=4, glow_opacity=0.12)
            self.assertEqual(len(renderer.neon_textures), 1)
        finally:
            renderer.close()
        self.assertFalse(renderer.neon_textures)

    def test_bold_changes_ink_and_metrics_without_leaking_font_style_or_cache(self):
        font = Path(__file__).resolve().parents[2] / "data/fonts/Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf"
        renderer = PicoV2Renderer({"text": font}, {"text": 24})
        p = self.pico
        def pixels():
            data = (c_ubyte * (96 * 96 * 4))()
            self.assertEqual(p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32, data, 96 * 4), 0)
            return bytes(data)
        try:
            original_style = p.TTF_GetFontStyle(renderer.fonts["text"].font)
            images = []
            widths = []
            for bold in (False, True, False):
                renderer.clear("#000000")
                renderer.text("RF5", 8, 20, "text", "#FFFFFF", bold=bold)
                images.append(pixels())
                widths.append(renderer.text_size("RF5", "text", bold=bold)[0])
                self.assertEqual(p.TTF_GetFontStyle(renderer.fonts["text"].font), original_style)
            self.assertNotEqual(images[0], images[1])
            self.assertEqual(images[0], images[2])
            self.assertGreaterEqual(widths[1], widths[0])
            self.assertEqual(len(renderer.textures), 2)
            self.assertEqual(len(renderer.measurements), 2)
            with patch.object(p, "TTF_SizeUTF8", return_value=-1), self.assertRaises(RuntimeError):
                renderer.text_size("failure", "text", bold=True)
            self.assertEqual(p.TTF_GetFontStyle(renderer.fonts["text"].font), original_style)
        finally:
            renderer.close()

    def test_inline_bold_uses_styled_advances_baselines_and_width_limit(self):
        font = Path(__file__).resolve().parents[2] / "data/fonts/Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf"
        renderer = PicoV2Renderer({"text": font}, {"text": 24})
        try:
            text = "**R** target **F5** reset"
            with patch.object(renderer, "text") as draw:
                renderer.rich_text(text, 5, 10, "text", "#FFFFFF")
                calls = draw.call_args_list
                self.assertEqual([call.args[0] for call in calls], ["R", " target ", "F5", " reset"])
                self.assertEqual([call.kwargs["bold"] for call in calls], [True, False, True, False])
                cursor = 5
                for call in calls:
                    self.assertEqual(call.args[1], cursor)
                    cursor += renderer.text_size(call.args[0], "text", bold=call.kwargs["bold"])[0]
                self.assertEqual(renderer.rich_text_size(text, "text")[0], cursor - 5)
                draw.reset_mock()
                renderer.rich_text(text, 5, 10, "text", "#AAAAAA", 0.8,
                                   bold_color="#FFFFFF", regular_opacity=0.78)
                self.assertEqual([call.args[4] for call in draw.call_args_list],
                                 ["#FFFFFF", "#AAAAAA", "#FFFFFF", "#AAAAAA"])
                self.assertEqual([call.args[5] for call in draw.call_args_list],
                                 [0.8, 0.8 * 0.78, 0.8, 0.8 * 0.78])
                draw.reset_mock()
                renderer.rich_text(text, 5, 10, "text", "#FFFFFF", max_width=1)
                self.assertEqual(draw.call_count, 1)
                self.assertEqual(draw.call_args.kwargs["max_width"], 1)
            self.assertEqual(renderer._bold_runs("unclosed **key"), (("unclosed **key", False),))
            self.assertEqual(renderer._bold_runs("**"), (("**", False),))
        finally:
            renderer.close()


if __name__ == "__main__":
    unittest.main()

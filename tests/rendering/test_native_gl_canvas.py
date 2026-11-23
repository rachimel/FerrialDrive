"""SDL 렌더러 없는 Pico2D 캔버스의 타깃·클립·텍스처 픽셀을 대조한다."""

import ctypes as ct
from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import patch

from ferrial_drive.rendering import PicoCanvas


@contextmanager
def canvas(driver):
    import pico2d.pico2d as pico

    create_window = pico.SDL_CreateWindow

    def hidden(title, x, y, width, height, flags):
        flags = (flags & ~pico.SDL_WINDOW_SHOWN) | pico.SDL_WINDOW_HIDDEN
        return create_window(title, x, y, width, height, flags)

    with patch.object(pico, "SDL_CreateWindow", hidden):
        with PicoCanvas(64, 48, "직접 OpenGL 픽셀 검사", driver=driver) as opened:
            yield opened


class NativeGlCanvasTests(TestCase):
    def render_scene(self, driver):
        with canvas(driver) as opened:
            p, renderer = opened.pico, opened.pico.renderer
            texture = p.SDL_CreateTexture(renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_TARGET, 12, 10)
            self.assertTrue(texture)
            try:
                self.assertEqual(p.SDL_SetRenderTarget(renderer, texture), 0)
                p.SDL_SetRenderDrawColor(renderer, 170, 40, 0, 255)
                self.assertEqual(p.SDL_RenderClear(renderer), 0)
                self.assertEqual(p.SDL_RenderSetViewport(renderer, ct.byref(p.SDL_Rect(1, 1, 8, 7))), 0)
                self.assertEqual(p.SDL_RenderSetClipRect(renderer, ct.byref(p.SDL_Rect(1, 0, 3, 6))), 0)
                p.SDL_SetRenderDrawColor(renderer, 24, 224, 48, 255)
                self.assertEqual(p.SDL_RenderFillRect(renderer, ct.byref(p.SDL_Rect(0, 0, 8, 4))), 0)
                self.assertEqual(p.SDL_SetRenderTarget(renderer, None), 0)
                p.SDL_SetRenderDrawColor(renderer, 8, 16, 40, 255)
                self.assertEqual(p.SDL_RenderClear(renderer), 0)
                self.assertEqual(p.SDL_RenderCopy(renderer, texture, None, ct.byref(p.SDL_Rect(14, 12, 12, 10))), 0)
                pixels = (ct.c_ubyte * (64 * 48 * 4))()
                self.assertEqual(p.SDL_RenderReadPixels(renderer, None, p.SDL_PIXELFORMAT_RGBA32,
                                                        pixels, 64 * 4), 0)
                return bytes(pixels)
            finally:
                p.SDL_DestroyTexture(texture)

    def test_texture_orientation_and_clip_match_sdl(self):
        expected = self.render_scene("opengl")
        actual = self.render_scene("native_gl")
        self.assertEqual(actual, expected)

    def test_creates_no_sdl_renderer_and_maps_letterboxed_input(self):
        import pico2d.pico2d as p

        with patch.object(p, "SDL_CreateRenderer", side_effect=AssertionError("SDL 렌더러 생성")) as create:
            with canvas("native_gl") as opened:
                native = p.fdrive_native_gl
                opened.resize_output(64, 48, logical_size=(32, 16))
                self.assertEqual(native.window_to_logical(32, 24), (16, 8))
                self.assertEqual(native.window_to_logical(0, 8), (0, 0))
            create.assert_not_called()
        self.assertFalse(hasattr(p, "fdrive_native_gl"))

"""SDL 렌더러 없는 Pico2D 캔버스의 타깃·클립·텍스처 픽셀을 대조한다."""

import ctypes as ct
from contextlib import contextmanager
import os
from pathlib import Path
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
                tiles = [(26, 12, 38, 22), (38, 12, 50, 22)]
                if driver == "native_gl":
                    self.assertEqual(p.fdrive_native_gl.copy_tiles(texture, tiles), 0)
                else:
                    for x, y, right, bottom in tiles:
                        destination = p.SDL_Rect(x, y, right - x, bottom - y)
                        self.assertEqual(p.SDL_RenderCopy(renderer, texture, None, ct.byref(destination)), 0)
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

    def test_streamed_draws_match_client_arrays(self):
        with patch.dict(os.environ, {"FDRIVE_NATIVE_VERTEX_SUBMISSION": "client"}):
            expected = self.render_scene("native_gl")
        with patch.dict(os.environ, {"FDRIVE_NATIVE_VERTEX_SUBMISSION": "vbo"}):
            self.assertEqual(self.render_scene("native_gl"), expected)

    def test_streamed_indices_and_texture_update_preserve_order(self):
        with patch.dict(os.environ, {"FDRIVE_NATIVE_VERTEX_SUBMISSION": "vbo"}), canvas("native_gl") as opened:
            p, renderer = opened.pico, opened.pico.renderer
            texture = p.SDL_CreateTexture(renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_STATIC, 1, 1)
            try:
                self.assertEqual(p.SDL_UpdateTexture(texture, None, bytes((200, 0, 0, 255)), 4), 0)
                p.SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255)
                p.SDL_RenderClear(renderer)
                p.SDL_RenderCopy(renderer, texture, None, ct.byref(p.SDL_Rect(0, 0, 8, 8)))
                self.assertEqual(p.SDL_UpdateTexture(texture, None, bytes((0, 200, 0, 255)), 4), 0)
                p.SDL_RenderCopy(renderer, texture, None, ct.byref(p.SDL_Rect(8, 0, 8, 8)))
                vertices = (p.SDL_Vertex * 3)()
                for vertex, (x, y) in zip(vertices, ((16, 0), (24, 0), (16, 8)), strict=True):
                    vertex.position = p.SDL_FPoint(x, y)
                    vertex.color = p.SDL_Color(0, 0, 200, 255)
                indices = (ct.c_int * 3)(0, 1, 2)
                self.assertEqual(p.SDL_RenderGeometry(renderer, None, vertices, 3, indices, 3), 0)
                pixels = (ct.c_ubyte * (24 * 4))()
                self.assertEqual(p.SDL_RenderReadPixels(renderer, ct.byref(p.SDL_Rect(0, 0, 24, 1)),
                                                        p.SDL_PIXELFORMAT_RGBA32, pixels, 24 * 4), 0)
                for x, color in ((1, (200, 0, 0, 255)), (9, (0, 200, 0, 255)), (17, (0, 0, 200, 255))):
                    self.assertEqual(tuple(pixels[x * 4:x * 4 + 4]), color)
            finally:
                p.SDL_DestroyTexture(texture)

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

    def test_atlas_upload_preserves_storage_format_and_pixels(self):
        from ferrial_drive.diagnostics.gpu_profile import bind_gl
        from ferrial_drive.rendering.atlas_texture_cache import AtlasTextureCache
        from ferrial_drive.rendering.texture_page_work import TexturePagePayload

        with canvas("native_gl") as opened:
            p = opened.pico
            cache = AtlasTextureCache(p, synchronize_upload=False)
            read = bind_gl(p, "glGetTexImage", None, [ct.c_uint] * 4 + [ct.c_void_p])
            read_compressed = bind_gl(p, "glGetCompressedTexImage", None, [ct.c_uint, ct.c_int, ct.c_void_p])
            for codec, pixel_format, pixels in (
                ("rgba_zlib", 0x1908, bytes((34, 45, 56, 67)) * 16),
                ("a8_zlib", 0x1903, bytes((59,)) * 16),
                ("bc7_zlib", None, bytes((0x40,)) + bytes(15)),
            ):
                with self.subTest(codec=codec):
                    page = dict(file=codec, sha256=codec, width=4, height=4, codec=codec)
                    key = cache.page_key(page, Path.cwd())
                    prepared = TexturePagePayload(key, (4, 4), codec, len(pixels), pixels, pixel_format is None)
                    _, entry = cache.acquire(page, Path.cwd(), prepared=prepared)
                    try:
                        buffer = (ct.c_ubyte * len(pixels))()
                        with cache.binding.bound():
                            cache.binding.bind_texture(0x0DE1, entry["gl_name"])
                            if pixel_format is None:
                                read_compressed(0x0DE1, 0, buffer)
                            else:
                                read(0x0DE1, 0, pixel_format, 0x1401, buffer)
                        self.assertEqual(bytes(buffer), pixels)
                        self.assertEqual(entry["gpu"]["storage_bytes"], len(pixels))
                    finally:
                        cache.release(key)
            self.assertEqual(cache.report()["gpu_allocated_bytes"], 0)

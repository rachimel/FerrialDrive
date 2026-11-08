"""FDRIVE_GPU_TESTS=1에서 숨긴 실제 OpenGL 창으로 Bicubic·클리핑·SDL 공존을 검사한다."""

from ctypes import byref, create_string_buffer
import os
from pathlib import Path
import tempfile
import unittest

from ferrial_drive.assets import AssetCatalog, AssetDefinition, AssetManager
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from ferrial_drive.assets.sprites import SpriteFrame
from samples.asset_loader.make_sample import write_png


@unittest.skipUnless(os.environ.get('FDRIVE_GPU_TESTS') == '1', '실제 GPU 검사는 명시적으로 실행한다.')
class AssetBicubicGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pico2d.pico2d as pico
        cls.pico = pico
        cls.previous_driver = os.environ.pop('SDL_VIDEODRIVER', None)
        if os.name == 'nt':
            os.environ['SDL_VIDEODRIVER'] = 'windows'
        pico.SDL_Init(pico.SDL_INIT_VIDEO)
        pico.SDL_SetHint(pico.SDL_HINT_RENDER_DRIVER, b'opengl')
        pico.window = pico.SDL_CreateWindow(b'FDrive Bicubic GPU check', 0, 0, 64, 64,
                                           pico.SDL_WINDOW_HIDDEN | pico.SDL_WINDOW_OPENGL)
        pico.renderer = pico.SDL_CreateRenderer(pico.window, -1, pico.SDL_RENDERER_ACCELERATED | pico.SDL_RENDERER_TARGETTEXTURE)
        if not pico.renderer:
            raise RuntimeError(pico.SDL_GetError())
        pico.canvas_width = pico.canvas_height = 64

    @classmethod
    def tearDownClass(cls):
        cls.pico.SDL_DestroyRenderer(cls.pico.renderer)
        cls.pico.SDL_DestroyWindow(cls.pico.window)
        cls.pico.SDL_Quit()
        cls.pico.SDL_ResetHint(cls.pico.SDL_HINT_RENDER_DRIVER)
        os.environ.pop('SDL_VIDEODRIVER', None)
        if cls.previous_driver is not None:
            os.environ['SDL_VIDEODRIVER'] = cls.previous_driver

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='asset-bicubic-gpu-')
        self.root = Path(self.temporary.name)
        self.managers = []
        self.pico.SDL_SetRenderTarget(self.pico.renderer, None)
        self.pico.SDL_RenderSetViewport(self.pico.renderer, None)
        self.pico.SDL_RenderSetScale(self.pico.renderer, 1, 1)
        self.pico.SDL_RenderSetClipRect(self.pico.renderer, None)
        self.clear()

    def tearDown(self):
        for manager in self.managers:
            manager.close()
        self.temporary.cleanup()

    def clear(self):
        self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 0, 0, 0, 255)
        self.pico.SDL_RenderClear(self.pico.renderer)

    def resource(self, width, height, pixel):
        path = self.root / f'{len(self.managers)}.png'
        write_png(path, width, height, pixel)
        manager = AssetManager(AssetCatalog([AssetDefinition('gpu', 'image', path)]), PicoAssetBackend())
        self.managers.append(manager)
        resource = manager.acquire('gpu').resource
        self.assertEqual(resource.filtering, 'bicubic')
        return resource

    def pixels(self):
        data = create_string_buffer(64 * 64 * 4)
        self.assertEqual(self.pico.SDL_RenderReadPixels(self.pico.renderer, None, self.pico.SDL_PIXELFORMAT_RGBA32, data, 64 * 4), 0)
        return data.raw

    def at(self, data, x, y):
        return tuple(data[(y * 64 + x) * 4:(y * 64 + x) * 4 + 4])

    def test_identity_preserves_rgb_and_shared_sampler_lifetime(self):
        pixel = lambda x, y: (x * 30, y * 30, (x + y) * 15, 255)
        resource = self.resource(8, 8, pixel)
        second = self.resource(8, 8, pixel)
        self.assertIs(resource.sampler, second.sampler)
        resource.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 48, shadow=False)
        data = self.pixels()
        for y in range(8):
            for x in range(8):
                self.assertEqual(self.at(data, 8 + x, 8 + y), pixel(x, y))

    def test_magnification_is_bicubic_instead_of_linear(self):
        pixel = lambda x, y: (255 if x >= 4 else 0, 64, 0, 255)
        resource = self.resource(8, 8, pixel)
        frame = SpriteFrame((0, 0, 8, 8), (0, 0))
        resource.draw_frame(frame, 8, 24, scale=4, shadow=False)
        cubic = self.pixels()
        self.clear()
        resource.set_filtering('linear')
        resource.draw_frame(frame, 8, 24, scale=4, shadow=False)
        linear = self.pixels()
        self.assertNotEqual(self.at(cubic, 22, 28)[0], self.at(linear, 22, 28)[0])
        # 출력 x=22는 원본 x=3.125에 대응하며 Catmull-Rom 가중치는 0.083984375다.
        self.assertAlmostEqual(self.at(cubic, 22, 28)[0], 255 * 0.083984375, delta=2)

    def test_atlas_neighbour_and_transparent_rgb_do_not_bleed(self):
        resource = self.resource(16, 8, lambda x, y: (255, 0, 0, 255) if x < 8 else (0, 255, 0, 255))
        resource.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 24, scale=4, shadow=False)
        data = self.pixels()
        self.assertEqual(self.at(data, 39, 28)[:3], (255, 0, 0))
        self.clear()
        transparent = self.resource(8, 8, lambda x, y: (0, 255, 0, 255) if 2 <= x <= 5 and 2 <= y <= 5 else (255, 0, 255, 0))
        transparent.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 24, scale=4, shadow=False)
        data = self.pixels()
        for x in range(8, 40):
            color = self.at(data, x, 28)
            self.assertEqual((color[0], color[2]), (0, 0))

    def test_clipping_and_subsequent_sdl_draw_remain_correct(self):
        resource = self.resource(8, 8, lambda x, y: (255, 0, 0, 255))
        clip = self.pico.SDL_Rect(12, 14, 8, 8)
        self.pico.SDL_RenderSetClipRect(self.pico.renderer, byref(clip))
        resource.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 24, scale=4, shadow=False)
        self.pico.SDL_RenderSetClipRect(self.pico.renderer, None)
        self.pico.SDL_SetRenderDrawColor(self.pico.renderer, 0, 255, 0, 255)
        box = self.pico.SDL_Rect(48, 48, 4, 4)
        self.pico.SDL_RenderFillRect(self.pico.renderer, byref(box))
        data = self.pixels()
        self.assertEqual(self.at(data, 14, 16)[:3], (255, 0, 0))
        self.assertEqual(self.at(data, 10, 16)[:3], (0, 0, 0))
        self.assertEqual(self.at(data, 49, 49)[:3], (0, 255, 0))

    def test_render_target_uses_matching_sdl_orientation(self):
        target = self.pico.SDL_CreateTexture(self.pico.renderer, self.pico.SDL_PIXELFORMAT_RGBA8888,
                                            self.pico.SDL_TEXTUREACCESS_TARGET, 64, 64)
        try:
            self.assertEqual(self.pico.SDL_SetRenderTarget(self.pico.renderer, target), 0)
            self.clear()
            resource = self.resource(8, 8, lambda x, y: (y * 30, 0, 0, 255))
            resource.draw_frame(SpriteFrame((0, 0, 8, 8), (0, 0)), 8, 48, shadow=False)
            data = self.pixels()
            self.assertEqual(self.at(data, 8, 8)[0], 0)
            self.assertEqual(self.at(data, 8, 15)[0], 210)
        finally:
            self.pico.SDL_SetRenderTarget(self.pico.renderer, None)
            self.pico.SDL_DestroyTexture(target)

    def test_viewport_scale_clip_matches_the_sdl_coordinate_system(self):
        resource = self.resource(8, 8, lambda x, y: (255, 0, 0, 255))
        viewport, clip = self.pico.SDL_Rect(8, 10, 48, 40), self.pico.SDL_Rect(1, 1, 8, 8)
        self.pico.SDL_RenderSetViewport(self.pico.renderer, byref(viewport))
        self.pico.SDL_RenderSetScale(self.pico.renderer, 1.5, 2)
        self.pico.SDL_RenderSetClipRect(self.pico.renderer, byref(clip))
        source, target = self.pico.SDL_Rect(0, 0, 8, 8), self.pico.SDL_Rect(0, 0, 12, 12)
        resource.sampler.draw(resource.textures['body'], (8, 8), source, target)
        cubic = self.pixels()
        self.clear()
        self.pico.SDL_RenderCopy(self.pico.renderer, resource.textures['body'], byref(source), byref(target))
        self.assertEqual(self.pixels(), cubic)


if __name__ == '__main__':
    unittest.main()

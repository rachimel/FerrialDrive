"""실제 OpenGL에서 PNG·알파 전용 데이터의 그림자 표시와 전송 상태를 비교한다."""

import ctypes as ct
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
LOCAL_RUNTIME = ROOT / "automate/runtime/texture_compare/python"
if LOCAL_RUNTIME.is_dir():
    sys.path.append(str(LOCAL_RUNTIME))

from ferrial_drive.assets.alpha_data import prepare_alpha_data
from ferrial_drive.rendering import PicoCanvas
from ferrial_drive.rendering.bicubic import acquire_sampler
from ferrial_drive.rendering.pico_alpha_texture import load_alpha_texture
from ferrial_drive.diagnostics.texture_metrics import bind_gl
from samples.asset_loader.make_sample import write_png


@unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS") == "1", "실제 GPU 검사는 선택 실행한다.")
class AlphaTextureGpuTests(unittest.TestCase):
    def test_quality_switch_stages_commits_and_cancels_without_changing_geometry(self):
        import pico2d.pico2d as pico
        from ferrial_drive.assets.catalog import AssetCatalog, read_document
        from ferrial_drive.assets.pico_assets import PicoAssetBackend
        from samples.asset_loader.make_sample import write_samples

        create_window = pico.SDL_CreateWindow
        def hidden(t,x,y,w,h,f):
            return create_window(t,x,y,w,h,(f & ~pico.SDL_WINDOW_SHOWN)|pico.SDL_WINDOW_HIDDEN)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{"SDL_VIDEODRIVER":"windows"}), \
             patch.object(pico,"SDL_CreateWindow",side_effect=hidden):
            root = write_samples(Path(folder)/"sample")
            documents = (read_document(definition) for definition in AssetCatalog.load(root/"catalog.json").definitions.values())
            document = next(document for document in documents if "shadow" in document.sheets)
            path = document.sheets["shadow"].image_path
            for scale in (.5,.25,.125):
                prepare_alpha_data(path,scale=scale,scaled_path=True)
            with PicoCanvas(64,64,"Shadow quality transaction"):
                resource = PicoAssetBackend(layers=("shadow",),alpha_layers=("shadow",),alpha_scale=.5).load(document)
                try:
                    old_texture,old_bytes = resource.textures["shadow"],resource.estimated_bytes
                    logical_size = dict(resource.sizes)
                    clips = resource.clips
                    for scale in (.25,.125,.5):
                        previous = resource.textures["shadow"]
                        with resource.prepare_alpha_scale(scale) as apply:
                            self.assertIs(resource.textures["shadow"],previous)
                            apply()
                        width,height = ct.c_int(),ct.c_int()
                        self.assertEqual(pico.SDL_QueryTexture(resource.textures["shadow"],None,None,ct.byref(width),ct.byref(height)),0)
                        from ferrial_drive.assets.alpha_data import alpha_dimensions
                        self.assertEqual((width.value,height.value),alpha_dimensions(logical_size["shadow"],scale))
                        self.assertEqual(resource.estimated_bytes,width.value*height.value)
                        self.assertEqual(resource.sizes,logical_size)
                        self.assertIs(resource.clips,clips)
                        self.assertEqual(resource.alpha_scale,scale)
                        mode = ct.c_int()
                        self.assertEqual(pico.SDL_GetTextureScaleMode(resource.textures["shadow"],ct.byref(mode)),0)
                        self.assertEqual(mode.value,pico.SDL_ScaleModeLinear)
                    current,footprint = resource.textures["shadow"],resource.estimated_bytes
                    with self.assertRaisesRegex(OSError,"저장 실패"):
                        with resource.prepare_alpha_scale(.125):
                            raise OSError("저장 실패")
                    self.assertIs(resource.textures["shadow"],current)
                    self.assertEqual(resource.estimated_bytes,footprint)
                    self.assertEqual(resource.alpha_scale,.5)
                    self.assertEqual(resource.estimated_bytes,old_bytes)
                finally:
                    resource.close()

    def test_prepared_alpha_matches_png_pixels_without_png_decoder_and_restores_unpack(self):
        import pico2d.pico2d as pico

        previous_driver = os.environ.get("SDL_VIDEODRIVER")
        os.environ["SDL_VIDEODRIVER"] = "windows"
        create_window = pico.SDL_CreateWindow

        def hidden_window(title, x, y, width, height, flags):
            return create_window(title, x, y, width, height, (flags & ~pico.SDL_WINDOW_SHOWN) | pico.SDL_WINDOW_HIDDEN)

        try:
            with tempfile.TemporaryDirectory() as folder, patch.object(pico, "SDL_CreateWindow", side_effect=hidden_window):
                with PicoCanvas(32, 32, "Alpha texture verification"):
                    sampler = acquire_sampler(pico)
                    try:
                        store = bind_gl(pico, "glPixelStorei", None, [ct.c_uint, ct.c_int])
                        previous = [sampler.integer(key) for key in (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)]
                        try:
                            for width in (7, 8):
                                with self.subTest(width=width):
                                    path = Path(folder) / f"shadow_{width}.png"
                                    write_png(path, width, 5, lambda x, y: (0, 0, 0, 255 if (x, y) == (3, 2) else (x * 37 + y * 13) % 256))

                                    def render():
                                        texture = load_alpha_texture(pico, path, sampler)
                                        try:
                                            pico.SDL_SetRenderDrawColor(pico.renderer, 255, 255, 255, 255)
                                            pico.SDL_RenderClear(pico.renderer)
                                            sampler.draw(texture, (width, 5), pico.SDL_Rect(0, 0, width, 5),
                                                         pico.SDL_Rect(8, 8, width, 5))
                                            pixels = ct.create_string_buffer(32 * 32 * 4)
                                            self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer, None, pico.SDL_PIXELFORMAT_RGBA32, pixels, 32 * 4), 0)
                                            return pixels.raw
                                        finally:
                                            pico.SDL_DestroyTexture(texture)

                                    baseline = render()
                                    prepare_alpha_data(path)
                                    for key, value in zip((0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4), (8, 19, 2, 3)):
                                        store(key, value)
                                    with patch("ferrial_drive.rendering.pico_alpha_texture.read_rgba_image", side_effect=AssertionError("PNG 디코더 호출")):
                                        actual = render()
                                    self.assertEqual(actual, baseline)
                                    self.assertEqual(actual[((8 + 2) * 32 + 8 + 3) * 4], 0)
                                    self.assertEqual([sampler.integer(key) for key in (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)], [8, 19, 2, 3])
                                    for key, value in zip((0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4), previous):
                                        store(key, value)
                        finally:
                            for key, value in zip((0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4), previous):
                                store(key, value)
                    finally:
                        sampler.release()
        finally:
            if previous_driver is None:
                os.environ.pop("SDL_VIDEODRIVER", None)
            else:
                os.environ["SDL_VIDEODRIVER"] = previous_driver


if __name__ == "__main__":
    unittest.main()

"""축소 벡터의 단위·투명 경계·공유 패킹·손상 데이터·품질 지표 계약."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
LOCAL_RUNTIME = ROOT / "automate/runtime/texture_compare/python"
if LOCAL_RUNTIME.is_dir():
    sys.path.append(str(LOCAL_RUNTIME))

from ferrial_drive.rendering.motion_atlas import AtlasItem, UniqueFrames, pack_items, resize_color, resize_vectors
from ferrial_drive.rendering.motion_vectors import decode_vector, encode_vector
from ferrial_drive.rendering.texture_codecs import bc7_size, unpack_payload


HAS_IMAGE_RUNTIME = importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("PIL") is not None


class TexturePayloadTests(unittest.TestCase):
    def test_bc7_rounds_to_whole_blocks(self):
        self.assertEqual(bc7_size(5, 7), 64)

    def test_zlib_requires_exact_payload_and_stream_end(self):
        self.assertEqual(unpack_payload("rgba_zlib", zlib.compress(b"a"*64), 4, 4), (b"a"*64, False))
        for packed in (zlib.compress(b"a"*65), zlib.compress(b"a"*64)[:-1], zlib.compress(b"a"*64)+b"tail"):
            with self.subTest(packed=packed[-8:]), self.assertRaises(ValueError):
                unpack_payload("rgba_zlib", packed, 4, 4)

    def test_identical_frames_share_but_shapes_do_not(self):
        frames = UniqueFrames()
        first = frames.add(b"a"*64, 4, 4)
        self.assertEqual(first, frames.add(b"a"*64, 4, 4))
        self.assertNotEqual(first, frames.add(b"a"*64, 8, 2))
        self.assertEqual(frames.references, 3)
        self.assertEqual(len(frames.items), 2)


@unittest.skipUnless(HAS_IMAGE_RUNTIME, "numpy/Pillow 로컬 실행 환경 필요")
class ResolutionContracts(unittest.TestCase):
    def test_75_percent_vectors_keep_pixel_units(self):
        pixels, width, height = resize_vectors(encode_vector(16, -8)*16*16, 16, 16, 4/3)
        self.assertEqual((width, height), (12, 12))
        self.assertEqual(decode_vector(pixels[:4]), (12, -6))

    def test_signed_vectors_rescale_by_real_new_dimensions(self):
        raw = encode_vector(16, -8)*5*7
        pixels, width, height = resize_vectors(raw, 5, 7, 2)
        self.assertEqual((width, height), (3, 4))
        dx, dy = decode_vector(pixels[:4])
        self.assertAlmostEqual(dx, 16*3/5, delta=1/64)
        self.assertAlmostEqual(dy, -8*4/7, delta=1/64)

    def test_packed_channel_carry_is_not_resized_as_color(self):
        raw = encode_vector(-0.015625, 0)+encode_vector(0.015625, 0)
        pixels, width, height = resize_vectors(raw*2, 2, 2, 2)
        self.assertEqual((width, height), (1, 1))
        self.assertEqual(decode_vector(pixels), (0, 0))

    def test_transparent_color_cannot_bleed_into_opaque_neighbor(self):
        pixels, width, height = resize_color(bytes((255, 0, 0, 0, 0, 0, 200, 255))*2, 2, 2, 2)
        self.assertEqual((width, height), (1, 1))
        self.assertEqual(pixels[0], 0)
        self.assertAlmostEqual(pixels[2], 100, delta=1)
        self.assertAlmostEqual(pixels[3], 128, delta=1)

    def test_padding_repeats_edges_and_pages_do_not_overlap(self):
        items = [AtlasItem(5, 7, bytes((value, 2, 3, 255))*35) for value in range(9)]
        pages, positions = pack_items(items, max_side=32)
        self.assertGreater(len(pages), 1)
        for index, position in enumerate(positions):
            page = pages[position["page"]]
            x, y, w, h = position["rect"]
            self.assertEqual((x % 4, y % 4), (0, 0))
            self.assertLessEqual(x+w+4, page.width)
            self.assertLessEqual(y+h+4, page.height)
            offset = ((y-1)*page.width+x-1)*4
            self.assertEqual(page.pixels[offset:offset+4], bytes((index, 2, 3, 255)))

    def test_quality_metrics_detect_visible_difference(self):
        import numpy as np
        from ferrial_drive.diagnostics.texture_metrics import image_quality
        left = np.zeros((32, 32, 4), dtype=np.uint8)
        left[:, :, 3] = 255
        right = left.copy()
        right[8:24, 8:24, :3] = 200
        same, changed = image_quality(left, left), image_quality(left, right)
        self.assertTrue(same["identical"])
        self.assertEqual(same["ssim"], 1)
        self.assertLess(changed["ssim"], 1)
        self.assertIsNotNone(changed["psnr_db"])


@unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS") == "1", "실제 OpenGL 검사는 선택 실행한다.")
class SharedGpuCacheTests(unittest.TestCase):
    def test_atlas_quint_phase_matches_cpu_reference_pixels(self):
        import ctypes as ct
        from ferrial_drive.rendering import PicoCanvas
        from ferrial_drive.rendering.motion_vectors import target_phase
        from ferrial_drive.rendering.pico_motion_atlas import AtlasPainter, AtlasTextureCache, PicoMotionAtlas
        source = ROOT / "output/texture_comparison/demo_bundle/comparison.json"
        if not source.is_file():
            self.skipTest("기본 도형의 비교 입력을 먼저 준비한다.")
        document = json.loads(source.read_text(encoding="utf-8"))
        with PicoCanvas(192, 192, "Atlas Playback Phase", driver="opengl"):
            import pico2d.pico2d as pico
            painter = AtlasPainter(pico)
            cache = AtlasTextureCache(pico, painter.sampler)
            resource = PicoMotionAtlas(pico, source.parent / document["cases"]["atlas_full"]["path"], cache)
            try:
                for phase in (0, 0.25, 0.5, 0.75, 1):
                    captures = []
                    for clock, easing in ((phase, "quint_in"),
                                          (target_phase(phase, easing="quint_in"), "linear")):
                        pico.SDL_SetRenderDrawColor(pico.renderer, 32, 40, 48, 255)
                        pico.SDL_RenderClear(pico.renderer)
                        painter.draw(resource, document["clips"][0], clock,
                                     pico.SDL_Rect(0, 0, 192, 192), easing=easing)
                        pixels = ct.create_string_buffer(192*192*4)
                        self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer, None, pico.SDL_PIXELFORMAT_RGBA32,
                                                                  pixels, 192*4), 0)
                        captures.append(pixels.raw)
                    self.assertEqual(*captures, msg=f"시간 위상 {phase}")
            finally:
                resource.close()
                painter.close()

    def test_r8_shadow_matches_rgba_and_restores_graphics_state(self):
        import ctypes as ct
        from PIL import Image
        from ferrial_drive.assets.catalog import AssetDefinition, read_document
        from ferrial_drive.assets.pico_assets import PicoAssetBackend
        from ferrial_drive.rendering import PicoCanvas
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"shadow.png"
            pixels = b"".join(bytes((0, 0, 0, (x*13+y*7) % 256)) for y in range(64) for x in range(64))
            Image.frombytes("RGBA", (64, 64), pixels).save(path)
            document = read_document(AssetDefinition("shadow", "image", path))
            with PicoCanvas(128, 64, "R8 Shadow Contract", driver="opengl"):
                import pico2d.pico2d as pico
                baseline = PicoAssetBackend().load(document)
                candidate = PicoAssetBackend(alpha_layers=("body",)).load(document)
                try:
                    self.assertEqual(baseline.estimated_bytes, 64*64*4)
                    self.assertEqual(candidate.estimated_bytes, 64*64)
                    pico.SDL_SetRenderDrawColor(pico.renderer, 255, 255, 255, 255)
                    pico.SDL_RenderClear(pico.renderer)
                    baseline.draw("image", 0, 32, 0)
                    candidate.draw("image", 0, 96, 0)
                    buffer = ct.create_string_buffer(128*64*4)
                    self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer, None, pico.SDL_PIXELFORMAT_RGBA32, buffer, 128*4), 0)
                    for y in range(64):
                        offset = y*128*4
                        self.assertEqual(buffer.raw[offset:offset+64*4], buffer.raw[offset+64*4:offset+128*4])
                finally:
                    candidate.close()
                    baseline.close()

    def test_ktx_and_oodle_share_the_same_vector_texture(self):
        import json
        from ferrial_drive.rendering import PicoCanvas
        from ferrial_drive.rendering.pico_motion_atlas import AtlasPainter, AtlasTextureCache, PicoMotionAtlas
        source = ROOT / "output/texture_comparison/demo_bundle/comparison.json"
        if not source.is_file():
            self.skipTest("기본 도형의 비교 입력을 먼저 준비한다.")
        document = json.loads(source.read_text(encoding="utf-8"))
        with PicoCanvas(320, 240, "Atlas Cache Contract", driver="opengl"):
            import pico2d.pico2d as pico
            painter = AtlasPainter(pico)
            cache = AtlasTextureCache(pico, painter.sampler, ktx_library=document["dependencies"]["ktx_library"])
            resources = []
            try:
                resources.append(PicoMotionAtlas(pico, source.parent / document["cases"]["ktx"]["path"], cache))
                first_count = len(cache.entries)
                resources.append(PicoMotionAtlas(pico, source.parent / document["cases"]["oodle"]["path"], cache))
                self.assertEqual(first_count, 2)
                self.assertEqual(len(cache.entries), 3)
                self.assertIs(resources[0].pages["vector"][0], resources[1].pages["vector"][0])
                self.assertEqual(resources[0].pages["vector"][0]["references"], 2)
                for resource in resources:
                    painter.draw(resource, document["clips"][0], 0.5, pico.SDL_Rect(0, 0, 192, 192), blur=True)
                cache.finish()
            finally:
                for resource in resources:
                    resource.close()
                self.assertEqual(len(cache.entries), 0)
                painter.close()


if __name__ == "__main__":
    unittest.main()

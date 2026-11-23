"""방향 배열의 패딩 예산과 2D 뷰 저장소의 수명을 확인한다."""

import ctypes as ct
import os
from pathlib import Path
import unittest

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from ferrial_drive.rendering.atlas_texture_cache import AtlasTextureCache
from ferrial_drive.rendering.canvas import PicoCanvas
from ferrial_drive.rendering.direction_texture_arrays import plan_direction_arrays
from ferrial_drive.rendering.texture_page_work import TexturePagePayload


class DirectionArrayTests(unittest.TestCase):
    def setUp(self):
        self.pages = tuple({"file": f"page_{width}", "sha256": str(width),
                            "width": width, "height": 4, "codec": "rgba_zlib"} for width in (4, 8))
        self.keys = tuple(AtlasTextureCache.page_key(page, Path.cwd()) for page in self.pages)
        self.pending = dict(zip(self.keys, self.pages, strict=True))
        self.resources = {("move", str(index)): {"pages": {"color": key}} for index, key in enumerate(self.keys)}

    def test_padding_counts_against_entire_motion_budget(self):
        self.assertEqual(plan_direction_arrays(self.resources, self.pending, 63, 32, 256), {})
        plan = plan_direction_arrays(self.resources, self.pending, 64, 32, 256)
        first, second = (plan[key] for key in self.keys)
        self.assertIs(first[0], second[0])
        self.assertEqual((first[1], second[1], first[0].storage_bytes), (0, 1, 256))

    @unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS") == "1", "실제 GPU 검사는 선택 실행한다.")
    def test_views_preserve_pixels_and_release_array_once(self):
        with PicoCanvas(128, 128, "방향 배열 검사") as canvas:
            cache = AtlasTextureCache(canvas.pico, synchronize_upload=False)
            cache.use_direction_arrays = True
            plan = cache.plan_arrays(self.resources, self.pending, 256)
            if not cache.use_direction_arrays:
                self.skipTest("OpenGL 4.3 텍스처 뷰가 필요하다.")
            self.assertEqual(set(plan), set(self.keys))
            download = bind_gl(canvas.pico, "glGetTexImage", None,
                               [ct.c_uint, ct.c_int, ct.c_uint, ct.c_uint, ct.c_void_p])
            try:
                for color, key, page in zip((b"\xFE\x00\x05\xFF", b"\x03\xEF\x00\xFF"),
                                            self.keys, self.pages, strict=True):
                    size = page["width"], page["height"]
                    payload = TexturePagePayload(key, size, page["codec"], 0, color * (size[0] * size[1]), False)
                    _, entry = cache.acquire(page, Path.cwd(), prepared=payload, array_slot=plan[key])
                    self.assertEqual(cache.gpu_storage_bytes, 256)
                    buffer = (ct.c_ubyte * 128)()
                    with cache.binding.bound():
                        cache.binding.bind_texture(0x0DE1, entry["gl_texture"])
                        download(0x0DE1, 0, 0x1908, 0x1401, buffer)
                    for row in range(size[1]):
                        self.assertEqual(bytes(buffer[row * 32:row * 32 + size[0] * 4]), color * size[0])
                cache.release(self.keys[0])
                self.assertEqual(cache.gpu_storage_bytes, 256)
            finally:
                for key in tuple(cache.entries):
                    cache.release(key)
            self.assertEqual((cache.gpu_storage_bytes, cache.array_count), (0, 0))

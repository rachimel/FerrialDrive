"""방향 배열의 패딩 예산과 2D 뷰 저장소의 수명을 확인한다."""

import ctypes as ct
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from ferrial_drive.rendering.atlas_texture_cache import AtlasTextureCache, bind_atlas_textures
from ferrial_drive.rendering.canvas import PicoCanvas
from ferrial_drive.rendering.direction_texture_arrays import TEXTURE_ARRAY, TEXTURE_BINDING_ARRAY, plan_direction_arrays
from ferrial_drive.rendering.gl_pass import TexturedQuadPass
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

    @unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS") == "1", "실제 GPU 검사는 선택 실행한다.")
    def test_mixed_array_and_2d_bindings_return_to_sdl_on_error(self):
        with PicoCanvas(128, 128, "배열 상태 복원 검사") as canvas:
            cache = AtlasTextureCache(canvas.pico, synchronize_upload=False)
            sampler = TexturedQuadPass(canvas.pico, fragment_shader=b"#version 120\nvoid main() { gl_FragColor=vec4(1); }")
            names = (ct.c_uint * 4)()
            cache.gen_texture(len(names), names)

            def snapshot():
                bindings = []
                for unit in range(3):
                    sampler.glActiveTexture(0x84C0 + unit)
                    bindings.append((sampler.integer(TEXTURE_BINDING_ARRAY), sampler.integer(0x8069)))
                sampler.glActiveTexture(0x84C0)
                return bindings

            try:
                for unit in range(3):
                    sampler.glActiveTexture(0x84C0 + unit)
                    sampler.glBindTexture(TEXTURE_ARRAY, names[0])
                    sampler.glBindTexture(0x0DE1, names[1])
                sampler.glActiveTexture(0x84C0)
                sampler.glBindTexture(TEXTURE_ARRAY, names[2])
                sampler.glBindTexture(0x0DE1, names[3])
                supports_arrays = sampler.texture_stack_covers(2, names[2], array=True)
                supports_2d = sampler.texture_stack_covers(3, names[3])
                array = {"gl_texture": names[2], "gl_target": TEXTURE_ARRAY, "gl_binding": TEXTURE_BINDING_ARRAY}
                entries = (array, array, {"gl_texture": names[3]})
                with sampler.batch():
                    previous = snapshot()
                    capacity = sampler._array_texture_stack_units
                    for allowed in (True, False):
                        with (self.subTest(allowed=allowed),
                              patch.object(sampler, "_array_texture_stack_units", capacity if allowed else 0),
                              patch.object(sampler, "preserve_texture_bindings",
                                           wraps=sampler.preserve_texture_bindings) as stack):
                            with self.assertRaisesRegex(RuntimeError, "제출 실패"):
                                with bind_atlas_textures(sampler, cache, entries, restore_unit_zero=False):
                                    self.assertEqual(snapshot(), [(names[2], names[3]), (names[2], names[1]),
                                                                   (names[0], names[3])])
                                    raise RuntimeError("제출 실패")
                            self.assertEqual(stack.call_count, int(allowed and supports_arrays and supports_2d))
                            self.assertEqual(snapshot(), previous)
            finally:
                cache.delete_texture(len(names), names)
                sampler.close()

"""동일 깊이와 픽셀별 순서 교차를 실제 GLSL 및 CPU 업로드에서 검사한다."""

import ctypes as ct
from unittest import TestCase

import numpy as np

from ferrial_drive.rendering.gl_pass import TexturedQuadPass
from ferrial_drive.rendering.part_depth_order import (
    CPU_ORDER_DECLARATION, INSERTION_SORT_LIMIT, CpuDepthOrderQuadPass, depth_order_shader, packed_depth_order,
)
from test_native_gl_canvas import canvas


class PartDepthOrderTests(TestCase):
    def test_cpu_order_matches_stable_reference(self):
        rng = np.random.default_rng(61)
        for parts in (1, 13, INSERTION_SORT_LIMIT + 1):
            with self.subTest(parts=parts):
                depths = rng.integers(-3, 7, size=(256, parts)).astype(np.float32)
                depths[0, 0] = -0.0
                packed = packed_depth_order(depths)
                indices = np.arange(parts)
                decoded = (packed[:, indices // 4] >> ((indices % 4) * 8)) & 255
                np.testing.assert_array_equal(decoded, np.argsort(depths, axis=-1, kind="stable"))

    def test_gpu_and_cpu_paths_keep_order_across_pixels(self):
        with canvas("native_gl") as opened:
            for parts in (13, INSERTION_SORT_LIMIT + 1):
                for cpu in (False, True):
                    with self.subTest(parts=parts, cpu=cpu):
                        self.check_shader(opened.pico, parts, cpu)

    def check_shader(self, pico, parts, cpu):
        version = b"#version 430 compatibility\n" if cpu else b"#version 120\n"
        program = version + f"#define PARTS {parts}\n".encode()
        if cpu:
            program += CPU_ORDER_DECLARATION
        program += b"""
void main() {
    int order[PARTS];
    float depths[PARTS];
    for(int i=0;i<PARTS;++i) {
        order[i]=i;
        depths[i]=mod(float(PARTS-1-i)+floor(gl_FragCoord.x)+floor(gl_FragCoord.y),7.0);
    }
""" + depth_order_shader(parts, cpu=cpu) + b"""
    int rank=int(floor(gl_FragCoord.x));
    gl_FragColor=vec4(float(order[rank])/255.0,0.0,0.0,1.0);
}
"""
        sampler = (CpuDepthOrderQuadPass(pico, part_count=parts, fragment_shader=program, extra_uniforms=())
                   if cpu else TexturedQuadPass(pico, fragment_shader=program))
        try:
            rect = pico.SDL_Rect(0, 0, parts, 3)
            sampler.draw(None, (parts, 3), rect, rect)
            pixels = (ct.c_ubyte * (parts * 3 * 4))()
            self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer, ct.byref(rect), pico.SDL_PIXELFORMAT_RGBA32,
                                                       pixels, parts * 4), 0)
            for y in range(3):
                for x in range(parts):
                    depths = [(parts - 1 - i + x + 47 - y) % 7 for i in range(parts)]
                    expected = sorted(range(parts), key=depths.__getitem__)[x]
                    self.assertEqual(pixels[(y * parts + x) * 4], expected, (x, y))
        finally:
            sampler.close()

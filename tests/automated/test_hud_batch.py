"""HUD 큐의 순서·버퍼 수명·실패 정리와 실제 SDL 픽셀 동일성을 검사한다."""

from contextlib import contextmanager
import ctypes as ct
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ferrial_drive.rendering.hud_batch import HudBatchQueue


class Point(ct.Structure):
    _fields_ = [('x', ct.c_float), ('y', ct.c_float)]


class Color(ct.Structure):
    _fields_ = [(name, ct.c_ubyte) for name in ('r', 'g', 'b', 'a')]


class Vertex(ct.Structure):
    _fields_ = [('position', Point), ('color', Color), ('tex_coord', Point)]


class Rectangle(ct.Structure):
    _fields_ = [(name, ct.c_int) for name in ('x', 'y', 'w', 'h')]


TRIANGLE = ((4, 5), (30, 5), (4, 32))
WHITE = (255, 255, 255, 128)


class HudBatchQueueTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def geometry(renderer, texture, vertices, count, indices, index_count):
            self.calls.append(('geometry', texture, bytes(vertices)[:count * ct.sizeof(Vertex)],
                               tuple(indices[:index_count])))
            return 0
        self.pico = SimpleNamespace(renderer=object(), SDL_Vertex=Vertex, SDL_Rect=Rectangle,
            SDL_RenderGeometry=geometry, SDL_SetRenderDrawColor=lambda *args: 0,
            SDL_RenderFillRects=lambda renderer, rects, count: self.calls.append(
                ('rectangles', tuple((r.x, r.y, r.w, r.h) for r in rects[:count]))) or 0,
            SDL_GetError=lambda: b'intended failure')
        self.queue = HudBatchQueue(self.pico)

    def test_adjacent_triangles_keep_vertex_colors_in_one_submission(self):
        with self.queue.frame():
            self.queue.polygon(TRIANGLE, WHITE)
            with self.queue.frame():
                self.queue.polygon(TRIANGLE, (1, 2, 3, 64))
            self.assertEqual(self.calls, [])
        self.assertEqual(len(self.calls), 1)
        vertices = (Vertex * 6).from_buffer_copy(self.calls[0][2])
        self.assertEqual((vertices[0].color.a, vertices[3].color.r, vertices[3].color.a), (128, 1, 64))
        self.assertEqual(self.calls[0][3], (0, 1, 2, 3, 4, 5))

    def test_texture_and_primitive_changes_preserve_painter_order(self):
        first, second = object(), object()
        with self.queue.frame():
            self.queue.polygon(TRIANGLE, WHITE, texture=first)
            self.queue.polygon(TRIANGLE, WHITE, texture=second)
            self.queue.rectangles(((3, 4, 5, 1),), WHITE)
            self.queue.polygon(TRIANGLE, WHITE, texture=first)
        self.assertEqual([row[0] for row in self.calls], ['geometry', 'geometry', 'rectangles', 'geometry'])
        self.assertIs(self.calls[0][1], first)
        self.assertIs(self.calls[1][1], second)

    def test_capacity_flush_and_following_frame_reuse_the_same_storage(self):
        self.queue = HudBatchQueue(self.pico, vertex_capacity=3, rect_capacity=1)
        with self.queue.frame():
            self.queue.polygon(TRIANGLE, WHITE)
            self.queue.polygon(TRIANGLE, WHITE)
            self.queue.rectangles(((0, 0, 4, 1), (0, 1, 4, 1)), WHITE)
        self.assertEqual(len(self.calls), 4)
        identities = id(self.queue.vertices), id(self.queue.indices), id(self.queue.rects)
        with self.queue.frame():
            self.queue.polygon(TRIANGLE, WHITE)
            self.queue.rectangles(((0, 0, 4, 1),), WHITE)
        self.assertEqual(identities, (id(self.queue.vertices), id(self.queue.indices), id(self.queue.rects)))
        self.assertEqual(self.queue.stats['buffer_allocations'], 0)

    def test_independent_indices_prevent_sdl_reinterpreting_a_fan_as_a_copy(self):
        with self.queue.frame():
            self.queue.polygon(((0, 0), (20, 0), (20, 20), (0, 20)), WHITE, separate_triangles=True)
        self.assertEqual(self.calls[0][3], (0, 1, 2, 3, 4, 5))
        self.assertEqual(len(self.calls[0][2]), 6 * ct.sizeof(Vertex))

    def test_exception_discards_pending_work_and_native_failure_does_not_replay(self):
        with self.assertRaisesRegex(ValueError, 'cancel'):
            with self.queue.frame():
                self.queue.polygon(TRIANGLE, WHITE)
                raise ValueError('cancel')
        self.queue.flush()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.queue.depth, 0)
        self.pico.SDL_RenderGeometry = lambda *args: -1
        with self.assertRaisesRegex(RuntimeError, 'intended failure'):
            with self.queue.frame():
                self.queue.polygon(TRIANGLE, WHITE)
        self.queue.flush()
        self.assertIsNone(self.queue.kind)
        self.assertEqual(self.queue.depth, 0)


class BatchPixelChecks:
    driver = 'dummy'

    def setUp(self):
        from ferrial_drive.rendering.canvas import PicoCanvas
        from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer
        import pico2d.pico2d as pico
        self.environment = patch.dict(os.environ, {'SDL_VIDEODRIVER': self.driver})
        self.environment.start()
        original = pico.SDL_CreateWindow
        self.hidden = patch.object(pico, 'SDL_CreateWindow', side_effect=lambda title, x, y, w, h, flags:
            original(title, x, y, w, h, (flags & ~pico.SDL_WINDOW_SHOWN) | pico.SDL_WINDOW_HIDDEN))
        self.hidden.start()
        try:
            self.canvas = PicoCanvas(128, 128, 'HUD batch verification').open()
            self.renderer = PicoV2Renderer({}, {})
        except BaseException:
            self.hidden.stop()
            self.environment.stop()
            raise

    def tearDown(self):
        try:
            self.renderer.close()
            self.canvas.close()
        finally:
            self.hidden.stop()
            self.environment.stop()

    def pixels(self):
        p = self.canvas.pico
        pixels = (ct.c_ubyte * (128 * 128 * 4))()
        self.assertEqual(p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32, pixels, 128 * 4), 0)
        return bytes(pixels)

    def test_mixed_transparency_state_and_target_changes_match_immediate_drawing(self):
        from ferrial_drive.ui.components import Rect
        r = self.renderer
        shape = ((12.25, 12.5), (100.75, 15), (94.5, 100.75), (14, 96))
        images = []
        for enabled in (False, True):
            r.batch_queue.enabled = enabled
            r.clear('#152637')
            with r.hud_batch():
                r.filled_triangle(*TRIANGLE, '#FF0000', .4)
                r.filled_triangle((15, 12), (70, 12), (15, 70), '#00FF00', .5)
                r.rect(Rect(24, 24, 40, 30), '#0000FF', .35)
                r.ring(64.25, 64.125, 29, 4, '#FFFFFF', .5)
                with r.clip(Rect(20, 18, 75, 83)), r.translated(3, 2), r.scaled(.8, (64, 64)):
                    r.filled_triangle(*TRIANGLE, '#FF00FF', .3)
                    r.ring(64, 64, 25, 3, '#FFFF00', .4)
                    r.scanline_layer(shape, '#FFFFFF', .35, 4, 1, 1.5)
                r.filtered_polygons((shape,), '#00FF00', .25, grain=(.1, 32, 1.25, 173))
                r.film_grain(shape, .2, 0, tile_pixels=32)
                r.line(5, 100, 120, 30, '#FFFFFF', .5)
                r.filled_triangle((100, 30), (120, 30), (110, 100), '#FF0000', .5)
            images.append(self.pixels())
        self.assertEqual(images[0], images[1])
        self.assertEqual(r.batch_queue.vertex_count, 0)

    def test_many_triangles_and_ring_reduce_native_submissions(self):
        r = self.renderer
        with r.hud_batch():
            for _ in range(12):
                r.filled_triangle(*TRIANGLE, '#FFFFFF', .1)
            r.ring(64, 64, 25, 4, '#FFFFFF', .5)
        self.assertEqual(r.batch_queue.stats['geometry_requests'], 12)
        self.assertEqual(r.batch_queue.stats['geometry_submits'], 1)
        self.assertEqual(r.batch_queue.stats['rectangle_submits'], 1)

    def test_filtered_masks_share_one_submission_after_warmup(self):
        r = self.renderer
        r.filtered_polygons((TRIANGLE,), '#112233')
        shifted = tuple((x + 24, y + 18) for x, y in TRIANGLE)
        with r.hud_batch():
            r.filtered_polygons((TRIANGLE,), '#FF5555', .7)
            r.filtered_polygons((shifted,), '#55FF88', .4)
        self.assertGreater(r._filtered_geometry_cache.cache_info().hits, 0)
        self.assertEqual(r.batch_queue.stats['filtered_requests'], 2)
        self.assertEqual(r.batch_queue.stats['geometry_submits'], 1)

    def test_filtered_batch_keeps_overlap_clip_scale_and_additive_grain(self):
        from ferrial_drive.ui.components import Rect
        r = self.renderer
        shape = ((12.25, 12.5), (100.75, 15), (94.5, 100.75), (14, 96))
        for scale in (1, .8):
            images = []
            for enabled in (False, True, False):
                r.filtered_polygons_batch_enabled = enabled
                r.clear('#31435C')
                with r.hud_batch(), r.clip(Rect(20, 18, 92, 92)), r.scaled(scale, (64, 64)):
                    r.filtered_polygons((shape,), '#2165A8', .63, grain=(.18, 32, 1.25, 173))
                    r.scanline_layer(shape, '#91ABDE', .7, 4, 1, 1.5)
                    r.filtered_polygons((shape,), '#A0B8FE', .28)
                    r.filtered_polygons((shape,), '#F955AB', .15)
                    r.rect(Rect(32, 30, 36, 40), '#CCA722', .31)
                    r.filtered_polygons((shape,), '#402B98', .47, grain=(.18, 32, 1.25, 173))
                images.append(self.pixels())
            self.assertEqual(images[0], images[1], scale)
            self.assertEqual(images[0], images[2], scale)

    def test_radar_submits_ring_and_all_arrows_as_one_geometry(self):
        r = self.renderer
        # 큐 초기 용량보다 큰 군집에서도 레이더 메시를 분할하지 않는다.
        arrows = ((TRIANGLE, .2),) * 650
        with r.hud_batch():
            r.radar_geometry(64, 64, 38, 2, '#FFFFFF', .5, arrows)
        self.assertEqual(r.batch_queue.stats['geometry_requests'], 1)
        self.assertEqual(r.batch_queue.stats['geometry_submits'], 1)
        self.assertEqual(r.batch_queue.stats['rectangle_submits'], 0)

    def test_failed_flush_restores_clip_scale_viewport_and_render_target(self):
        from ferrial_drive.ui.components import Rect
        r, p = self.renderer, self.canvas.pico
        with self.assertRaisesRegex(RuntimeError, 'HUD 배치 제출 실패'):
            with patch.object(p, 'SDL_RenderGeometry', return_value=-1):
                with r.hud_batch(), r.clip(Rect(5, 5, 80, 80)), r.scaled(.8, (64, 64)):
                    r.filled_triangle(*TRIANGLE, '#FFFFFF')
        scale, viewport, _, clipping = r.draw_transform()
        self.assertEqual(scale, (1, 1))
        self.assertEqual(viewport, (0, 0, 128, 128))
        self.assertIsNone(clipping)
        self.assertFalse(p.SDL_GetRenderTarget(p.renderer))
        self.assertEqual(r.batch_queue.depth, 0)

    def test_failed_target_submission_restores_state_before_destroying_the_texture(self):
        r, p = self.renderer, self.canvas.pico
        with self.assertRaisesRegex(RuntimeError, 'HUD 배치 제출 실패'):
            with patch.object(p, 'SDL_RenderGeometry', return_value=-1), r.hud_batch():
                r.filtered_polygons((TRIANGLE,), '#FF0000')
        self.assertFalse(p.SDL_GetRenderTarget(p.renderer))
        self.assertEqual(r.draw_transform()[0], (1, 1))
        self.assertEqual(r.batch_queue.depth, 0)
        self.assertIsNone(r.batch_queue.kind)
        self.assertEqual(r.filtered_textures, {})


class HudBatchSoftwareTests(BatchPixelChecks, unittest.TestCase):
    pass


@unittest.skipUnless(os.environ.get('FDRIVE_GPU_TESTS') == '1', '실제 GPU 검사는 선택 실행한다.')
class HudBatchGpuTests(BatchPixelChecks, unittest.TestCase):
    driver = 'windows'


if __name__ == '__main__':
    unittest.main()

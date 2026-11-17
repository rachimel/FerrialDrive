"""도형 배치의 순서·예외·버퍼 재사용과 실제 OpenGL 인스턴싱을 확인한다."""

import ctypes as ct
import os
import unittest
from unittest.mock import patch

from ferrial_drive.rendering.canvas import PicoCanvas
from ferrial_drive.rendering.primitive_batch import PrimitiveBatch
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer


class PrimitiveBatchChecks:
    driver = "dummy"

    def setUp(self):
        import pico2d.pico2d as pico
        self.environment = patch.dict(os.environ, SDL_VIDEODRIVER=self.driver)
        self.environment.start()
        original = pico.SDL_CreateWindow
        self.hidden = patch.object(pico, 'SDL_CreateWindow', side_effect=lambda title, x, y, w, h, flags:
            original(title, x, y, w, h, (flags & ~pico.SDL_WINDOW_SHOWN) | pico.SDL_WINDOW_HIDDEN))
        self.hidden.start()
        self.canvas = PicoCanvas(128, 128, "도형 배치 확인").open()
        self.pico = pico
        self.renderer = PicoV2Renderer({}, {})
        self.batches = []

    def tearDown(self):
        try:
            for batch in self.batches:
                batch.close()
            self.renderer.close()
            self.canvas.close()
        finally:
            self.hidden.stop()
            self.environment.stop()

    def batch(self, backend):
        batch = PrimitiveBatch(self.renderer, backend=backend)
        self.batches.append(batch)
        return batch

    def pixels(self):
        data = (ct.c_ubyte * (128 * 128 * 4))()
        p = self.pico
        self.assertEqual(p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32, data, 512), 0)
        return bytes(data)

    def shapes(self, batch):
        with batch.frame():
            batch.rect(Rect(10, 12, 75, 64), '#C08040', .7)
            batch.rect(Rect(45, 24, 45, 66), '#2080E0', .45)
            batch.line(10, 100, 100, 18, '#FFFFFF', .8)
            batch.line(23, 9, 23, 95, '#FF0000')
            batch.line(61, 61, 61, 61, '#00FF00')

    def test_ordered_rectangles_match_immediate_and_reuse_buffer(self):
        batch = self.batch('batched')
        images = []
        for enabled in (False, True):
            self.renderer.clear('#102030')
            if enabled:
                with batch.frame():
                    batch.rect(Rect(10, 12, 75, 64), '#C08040', .7)
                    batch.rect(Rect(45, 24, 45, 66), '#2080E0', .45)
            else:
                self.renderer.rect(Rect(10, 12, 75, 64), '#C08040', .7)
                self.renderer.rect(Rect(45, 24, 45, 66), '#2080E0', .45)
            images.append(self.pixels())
        # SDL software의 FillRect와 Geometry는 알파 정수 반올림이 조금 다르다.
        self.assertLessEqual(max(abs(a - b) for a, b in zip(*images)), 2)
        self.assertEqual(batch.stats['geometry_submits'], 1)
        data = batch.data
        self.shapes(batch)
        self.assertIs(batch.data, data)
        self.assertEqual(batch.stats['buffer_allocations'], 0)

    def test_failed_frame_discards_geometry_and_text_and_next_frame_is_clean(self):
        batch = self.batch('batched')
        self.renderer.clear('#102030')
        before = self.pixels()
        with patch.object(self.renderer, 'text') as text:
            with self.assertRaisesRegex(ValueError, 'cancel'):
                with batch.frame():
                    batch.rect(Rect(0, 0, 128, 128), '#FF0000')
                    batch.text('취소', 0, 0, 'body', '#FFFFFF')
                    raise ValueError('cancel')
            text.assert_not_called()
        self.assertEqual(before, self.pixels())
        self.assertEqual(batch.count, 0)
        self.shapes(batch)
        self.assertEqual(batch.stats['primitives'], 5)

    def test_labels_are_submitted_after_geometry(self):
        batch = self.batch('batched')
        with patch.object(self.renderer, 'text') as text:
            with batch.frame():
                batch.text('앞', 0, 0, 'body', '#FFFFFF')
                batch.rect(Rect(10, 12, 5, 5), '#FF0000')
                text.assert_not_called()
            text.assert_called_once()
        self.assertEqual(batch.stats['geometry_submits'], 1)

    def test_explicit_flush_does_not_replay_and_counts_each_submission(self):
        batch = self.batch('batched')
        with batch.frame():
            batch.rect(Rect(10, 12, 5, 5), '#FF0000', .5)
            batch.flush()
            self.assertEqual(batch.count, 0)
            batch.flush()
            self.assertEqual(batch.stats['geometry_submits'], 1)
            batch.rect(Rect(30, 12, 5, 5), '#00FF00')
        self.assertEqual(batch.stats['geometry_submits'], 2)


class PrimitiveSoftwareTests(PrimitiveBatchChecks, unittest.TestCase):
    pass


@unittest.skipUnless(os.environ.get('FDRIVE_GPU_TESTS') == '1', '실제 GPU 검사는 선택 실행한다.')
class PrimitiveGpuTests(PrimitiveBatchChecks, unittest.TestCase):
    driver = "windows"

    def test_instancing_matches_geometry_with_clip_scale_and_render_target(self):
        p = self.pico
        batches = [self.batch(mode) for mode in ('batched', 'instanced')]
        target = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA8888, p.SDL_TEXTUREACCESS_TARGET, 128, 128)
        self.assertTrue(target)
        try:
            for destination in (None, target):
                images = []
                for batch in batches:
                    p.SDL_SetRenderTarget(p.renderer, destination)
                    self.renderer.clear('#102030')
                    with self.renderer.clip(Rect(12, 15, 85, 90)), self.renderer.scaled(.9, (0, 0)):
                        self.shapes(batch)
                    # SDL 그리기를 이어서 실행해 상태 복원도 확인한다.
                    self.renderer.rect(Rect(110, 110, 10, 10), '#E0A030')
                    images.append(self.pixels())
                changed = sum(a != b for a, b in zip(*images))
                self.assertLess(changed, 128)
                self.assertEqual(batches[1].stats['geometry_submits'], 1)
                self.assertEqual(batches[1].stats['instance_upload_bytes'], 5 * 48)
        finally:
            p.SDL_SetRenderTarget(p.renderer, None)
            p.SDL_DestroyTexture(target)


if __name__ == '__main__':
    unittest.main()

"""격자선과 눈금 글자를 함께 제출할 때 순서와 픽셀을 확인한다."""

import ctypes as ct
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.combat.training_ground import GroundProjection, TrainingGroundView
from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer
from test_native_gl_canvas import canvas


class TrainingGroundBatchTests(TestCase):
    def test_grid_matches_legacy_with_overlapping_labels_and_clip(self):
        font = Path(__file__).resolve().parents[2] / "data/fonts/SUITE-otf/SUITE-Regular.otf"
        with canvas("native_gl") as opened:
            pico = opened.pico
            renderer = PicoV2Renderer({"small": font}, {"small": 10})
            camera = LookAheadCamera(64, 48)
            projection = GroundProjection(4, 0.75)
            settings = {"grid_m": 3, "major_grid_m": 9}
            try:
                for position in ((19.3, 15.8), (71.2, 47.4), (120.6, 88.8)):
                    camera.reset(position)
                    frames = []
                    for mode in ("legacy", "batch"):
                        with patch.dict(os.environ, {"FDRIVE_GROUND_GRID_SUBMISSION": mode}):
                            ground = TrainingGroundView(renderer, projection, settings)
                        try:
                            ground.draw(camera, (64, 48), 32)
                            if mode == "batch":
                                self.assertEqual(renderer.batch_queue.stats["geometry_submits"], 1)
                            pixels = (ct.c_ubyte * (64 * 48 * 4))()
                            self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer, None, pico.SDL_PIXELFORMAT_RGBA32,
                                                                       pixels, 64 * 4), 0)
                            frames.append(bytes(pixels))
                        finally:
                            ground.close()
                    self.assertEqual(frames[0], frames[1], position)
            finally:
                renderer.close()

"""전체 KeyFrame 위상·변위 계약과 선택적 실제 OpenGL 보간 품질을 검사한다."""

import importlib.util
import json
from math import asin, sin
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ferrial_drive.rendering.motion_vectors import (MotionClip, MotionPair, advance_combo_phase, decode_vector, encode_vector,
                                                    frame_interval, load_clip, premultiply_rgba, target_phase)
from Tools.unit_test_runner.entrypoints import inspect_entrypoint, read_test_header, read_test_source


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "ferrial_drive/diagnostics/interpolation_preview.py"


def load_program_module():
    spec = importlib.util.spec_from_file_location("frame_interpolation_sample", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MotionContractTests(unittest.TestCase):
    def test_combo_boundary_candidates_and_first_frame(self):
        durations = (0.5, 0.5, 0.5, 2 / 3)
        index, phase = advance_combo_phase(0, 0.98, 0.1, durations, boundary="carry")
        self.assertEqual(index, 1)
        self.assertAlmostEqual(phase, 0.18)
        self.assertEqual(advance_combo_phase(0, 0.98, 0.1, durations, boundary="zero"), (1, 0))
        self.assertEqual(advance_combo_phase(3, 0.99, 0.1, durations, boundary="zero"), (0, 0))
        self.assertEqual(advance_combo_phase(1, 0, 0.01, durations, boundary="zero"), (1, 0.02))

    def test_signed_subpixel_vectors_and_out_of_range(self):
        for value in ((0, 0), (42.5, -11.25), (-512, 511.984375)):
            self.assertEqual(decode_vector(encode_vector(*value)), value)
        for value in (float("nan"), float("inf"), 512, -513):
            with self.assertRaises(ValueError):
                encode_vector(value, 0)

    def test_smoothstep_is_applied_once_to_whole_keyframe_span(self):
        goal = target_phase(0.25)
        self.assertEqual(goal, 0.15625)
        index, alpha = frame_interval(goal, 6)
        self.assertEqual(index, 0)
        self.assertEqual(alpha, 0.9375)
        # 원본 경계를 통과해도 전체 목표 위상의 속도가 끊기지 않는다.
        left, right = target_phase(0.5 - 1e-5), target_phase(0.5 + 1e-5)
        self.assertAlmostEqual((right - left) / 2e-5, 1.5, places=6)
        self.assertEqual(frame_interval(target_phase(1), 6), (5, 1))
        self.assertEqual(target_phase(0.25, start=0.2, end=0.8), 0.29375)
        self.assertEqual(target_phase(0.25, easing="linear"), 0.25)

    def test_accelerated_phase_keeps_duration_and_increases_playback_speed(self):
        self.assertEqual(target_phase(0, easing="accelerate"), 0)
        self.assertEqual(target_phase(1, easing="accelerate"), 1)
        self.assertEqual(target_phase(0.5, easing="accelerate"), 0.1875)
        samples = [target_phase(index/100, easing="accelerate") for index in range(101)]
        speeds = [b-a for a, b in zip(samples, samples[1:])]
        self.assertTrue(all(0 < a < b for a, b in zip(speeds, speeds[1:])))
        self.assertAlmostEqual(sum(speeds), 1)

    def test_quint_phase_keeps_endpoints_and_defers_motion_until_late_in_strike(self):
        self.assertEqual(target_phase(0, easing="quint_in"), 0)
        self.assertEqual(target_phase(1, easing="quint_in"), 1)
        self.assertEqual(target_phase(0.5, easing="quint_in"), 1/32)
        self.assertLess(target_phase(0.5, easing="quint_in"), target_phase(0.5, easing="accelerate"))
        samples = [target_phase(index/100, easing="quint_in") for index in range(101)]
        speeds = [b-a for a, b in zip(samples, samples[1:])]
        self.assertTrue(all(0 < a < b for a, b in zip(speeds, speeds[1:])))

    def test_invalid_phase_size_and_time(self):
        for value in (-0.1, 1.1, float("inf"), float("nan"), True):
            with self.assertRaises(ValueError):
                target_phase(value)
        for width, duration in ((0, 1), (1, 0), (1, float("nan"))):
            with self.assertRaises(ValueError):
                MotionPair(width, 1, bytes(4), bytes(4), bytes(4), bytes(4), duration)
        with self.assertRaises(ValueError):
            MotionPair(2, 2, bytes(4), bytes(4), bytes(4), bytes(4), 1)
        with self.assertRaises(ValueError):
            MotionClip(())

    def test_premultiplication_keeps_transparent_color_out(self):
        self.assertEqual(premultiply_rgba(bytes((255, 128, 64, 0, 200, 100, 50, 128))),
                         bytes((0, 0, 0, 0, 100, 50, 25, 128)))

    def test_dataset_relative_paths_and_boundary_continuity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "f.rgba").write_bytes(encode_vector(2, -1))
            (root / "b.rgba").write_bytes(encode_vector(-2, 1))
            data = {"schema_version": 1, "size_pixels": [1, 1], "duration_seconds": 0.1,
                    "origin": "top_left", "vector_units": "pixels_per_pair",
                    "vector_encoding": "signed16_rgba_x64", "image_a": "a.png", "image_b": "b.png",
                    "forward_a_to_b": "f.rgba", "backward_b_to_a": "b.rgba"}
            manifest = root / "pair.json"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            colors = {"a.png": bytes((255, 0, 0, 255)), "b.png": bytes((0, 255, 0, 255))}
            def read_image(path):
                self.assertEqual(path.parent, root)
                return 1, 1, colors[path.name]
            clip = load_clip(manifest, read_image)
            self.assertEqual(decode_vector(clip.pairs[0].forward), (2, -1))
            with self.assertRaises(ValueError):
                MotionClip((clip.pairs[0], clip.pairs[0]))
            data["vector_units"] = "pixels_per_second"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_clip(manifest, read_image)


    def test_pause_step_and_large_delta_ping_pong(self):
        module = load_program_module()
        program = module.FrameInterpolationTest(phase=0.25)
        pair = MotionPair(1, 1, bytes(4), bytes(4), bytes(4), bytes(4), 1)
        program.clip = MotionClip((pair,))
        program.update(0.4)
        self.assertEqual(program.phase, 0.25)
        program.paused = False
        program.update(4.5)
        self.assertAlmostEqual(program.phase, 0.75)
        program.update(0.5)
        self.assertAlmostEqual(program.phase, 0.75)
        self.assertEqual(program.direction, -1)


@unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS") == "1", "실제 OpenGL 검사는 선택 실행한다.")
class MotionGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pico2d.pico2d as pico
        from ferrial_drive.rendering import PicoCanvas
        cls.pico = pico
        cls.environment = patch.dict(os.environ, SDL_VIDEODRIVER="windows")
        cls.environment.start()
        create = pico.SDL_CreateWindow
        def hidden(title, x, y, width, height, flags):
            return create(title, x, y, width, height, (flags & ~pico.SDL_WINDOW_SHOWN) | pico.SDL_WINDOW_HIDDEN)
        cls.canvas = PicoCanvas(1232, 690, "FDrive interpolation GPU check")
        with patch.object(pico, "SDL_CreateWindow", side_effect=hidden):
            cls.canvas.open()
        cls.module = load_program_module()
        cls.program = cls.module.FrameInterpolationTest(phase=0.43, blur=False)
        try:
            cls.program.enter()
        except BaseException:
            cls.program.exit()
            cls.canvas.close()
            cls.environment.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.program.exit()
        cls.canvas.close()
        cls.environment.stop()

    def setUp(self):
        self.program.phase = 0.43
        self.program.easing = "smoothstep"
        self.program.select_scene(0)

    def test_translation_improves_over_hold_and_blend(self):
        report = self.program.quality_report()
        motion = report["metrics"]["motion"]
        for mode in ("hold", "blend"):
            self.assertLess(motion["premultiplied_mae_in_visible_union"],
                            report["metrics"][mode]["premultiplied_mae_in_visible_union"] * 0.25)
        self.assertGreater(motion["alpha_iou"], 0.97)

    def test_endpoints_and_easing_gpu_match_reference(self):
        for easing in ("linear", "smoothstep", "accelerate", "quint_in"):
            self.program.easing = easing
            for phase in (0, 0.25, 0.5, 0.75, 1):
                self.program.phase = phase
                expected = self.program.read_mode_pixels("reference")
                actual = self.program.read_mode_pixels("motion")
                metrics = self.module.pixel_metrics(expected, actual)
                # 중간 시점은 이미 래스터화한 경계를 다시 샘플하므로 직접 도형과 필터 폭이 다르다.
                tolerance = 0.003 if phase in (0, 1) else 0.03
                self.assertLess(metrics["premultiplied_mae_in_visible_union"], tolerance,
                                msg=f"{easing=} {phase=} {metrics=}")
                self.assertGreater(metrics["alpha_iou"], 0.97)

    def test_motion_blur_changes_image_and_crosses_source_boundary(self):
        self.program.phase = 0.5
        sharp = self.program.read_mode_pixels("motion")
        blurred = self.program.read_mode_pixels("motion", shutter_seconds=0.12)
        self.assertNotEqual(sharp, blurred)
        reference = self.program.read_mode_pixels("reference", shutter_seconds=0.12)
        self.assertLess(self.module.pixel_metrics(reference, blurred)["premultiplied_mae_in_visible_union"], 0.02)

    def test_directional_blur_and_reverse_playback(self):
        self.program.phase = 0.43
        self.program.direction = 1
        self.program.blur_direction = "trailing"
        trailing = self.program.read_mode_pixels("motion", shutter_seconds=0.12)
        self.program.blur_direction = "leading"
        leading = self.program.read_mode_pixels("motion", shutter_seconds=0.12)
        self.assertNotEqual(trailing, leading)
        self.program.blur_direction = "trailing"
        self.program.direction = -1
        reversed_trailing = self.program.read_mode_pixels("motion", shutter_seconds=0.12)
        self.assertEqual(reversed_trailing, leading)
        self.program.direction = 1

    def test_blur_strength_zero_is_sharp_and_full_strength_changes_image(self):
        self.program.phase = 0.43
        sharp = self.program.read_mode_pixels("motion")
        self.program.blur_strength = 0
        zero = self.program.read_mode_pixels("motion", shutter_seconds=0.12)
        self.assertEqual(sharp, zero)
        self.program.blur_strength = 1
        full = self.program.read_mode_pixels("motion", shutter_seconds=0.12)
        self.assertNotEqual(sharp, full)
        self.program.blur_strength = 0.65

    @unittest.skipUnless(os.environ.get("FDRIVE_NATIVE_INTERPOLATION_TESTS") == "1", "실제 Unreal 출력은 로컬 선택 검사다.")
    def test_native_boundary_comparison_first_frame(self):
        comparison = self.module.ComboBoundaryComparison(ROOT / "data/runtime/frame_interpolation/player_combo/catalog.json")
        try:
            comparison.enter()
            program = comparison.program
            self.assertEqual(program.scene_index, 0)
            self.assertEqual(len(program.interpolator.clip_cache), 4)
            cache_ids = tuple(program.interpolator.clip_cache)
            program.phase = 0.98
            comparison.update(0.1)
            self.assertEqual(program.scene_index, 1)
            self.assertGreater(program.phase, 0)
            program.select_scene(0)
            program.phase = 0.98
            program.combo_boundary = "zero"
            comparison.update(0.1)
            self.assertEqual(program.scene_index, 1)
            self.assertEqual(program.phase, 0)
            self.assertEqual(set(program.interpolator.clip_cache), set(cache_ids))
            comparison.draw()
            program.ui.save_frame(ROOT / "output/frame_interpolation/combo_boundary_comparison.png", 1232, 690)
        finally:
            comparison.exit()

    @unittest.skipUnless(os.environ.get("FDRIVE_NATIVE_INTERPOLATION_TESTS") == "1", "실제 Unreal 출력은 로컬 선택 검사다.")
    def test_real_unreal_sword_intermediate_frames(self):
        catalog = ROOT / "data/runtime/frame_interpolation/player_combo/catalog.json"
        self.program.dataset_catalog_path = catalog
        self.program.dataset_catalog = json.loads(catalog.read_text(encoding="utf-8"))["clips"]
        self.program.dataset = catalog.parent / self.program.dataset_catalog[0]["path"]
        try:
            rows = []
            for attack in range(4):
                self.program.select_scene(attack)
                count = len(self.program.clip.pairs)
                for index in range(count):
                    goal = (index + 0.5) / count
                    self.program.phase = 0.5 - sin(asin(1 - 2 * goal) / 3)
                    report = self.program.quality_report()
                    report["attack"] = attack + 1
                    self.assertTrue(report["unreal_motion_vectors_verified"])
                    self.assertLess(report["reference_time_error_seconds"], 1e-10)
                    self.assertGreater(report["metrics"]["motion"]["alpha_iou"], 0.5)
                    rows.append(report)
            self.program.phase = 0.99
            self.program.paused = False
            self.program.update(0.1)
            self.assertEqual(self.program.scene_index, 0)
            self.assertEqual(self.program.phase, 0)
            output = ROOT / "output/frame_interpolation/native_checks.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            self.program.dataset = None
            self.program.dataset_catalog = []

    def test_gl_state_sdl_and_resource_replacement(self):
        s, p = self.program.interpolator.sampler, self.pico
        p.SDL_RenderDrawPoint(p.renderer, -1000000, -1000000)
        p.SDL_RenderFlush(p.renderer)
        state = (s.integer(0x8B8D), s.integer(0x84E0), s.integer(0x0BA2, 4))
        self.program.interpolator.draw(0.43, p.SDL_Rect(16, 16, 288, 288))
        self.assertEqual((s.integer(0x8B8D), s.integer(0x84E0), s.integer(0x0BA2, 4)), state)
        self.program.select_scene(1)
        self.program.draw()
        self.program.select_scene(2)
        report = self.program.quality_report()
        self.assertFalse(report["occlusion_reconstruction"])
        self.assertFalse(report["unreal_motion_vectors_verified"])
        self.assertEqual(len(self.program.interpolator.textures), 4)
        p.SDL_SetRenderDrawColor(p.renderer, 255, 0, 0, 255)
        p.SDL_RenderDrawPoint(p.renderer, 0, 0)
        data = self.program.read_mode_pixels("motion")
        self.assertEqual(len(data), 192 * 192 * 4)


if __name__ == "__main__":
    unittest.main()

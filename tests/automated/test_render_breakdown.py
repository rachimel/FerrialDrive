"""직접 조작 입력·표본 상한·진단 후 원상 복구를 검사한다."""

from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ferrial_drive.diagnostics.frame_benchmark import benchmark_program
from ferrial_drive.diagnostics.render_breakdown import RenderBreakdown


class FakeTimer:
    available = True

    def __init__(self, pico):
        self.samples_ms = []

    def begin(self):
        pass

    def end(self):
        self.samples_ms.append(1)

    def collect(self):
        pass

    def close(self):
        pass


class InteractiveBenchmarkTests(unittest.TestCase):
    def run_frames(self, interactive):
        events, deltas = [], []
        pico = SimpleNamespace(SDL_QUIT=256, SDL_RenderFlush=lambda renderer: None, renderer=None)
        app = SimpleNamespace(running=True, handle_event=events.append, update=deltas.append, draw=lambda: None)
        canvas = SimpleNamespace(pico=pico, present=lambda: None)
        key_down, key_up, quit_event = (SimpleNamespace(type=value) for value in (10, 11, 256))
        ticks = iter(i*.01 for i in range(200))
        with patch("ferrial_drive.runtime.poll_events", side_effect=[[key_down], [], [key_up], [quit_event]]), \
             patch("ferrial_drive.diagnostics.frame_benchmark.bind_gl", return_value=lambda: None), \
             patch("ferrial_drive.diagnostics.frame_benchmark.GpuFrameTimer", FakeTimer), \
             patch("ferrial_drive.diagnostics.frame_benchmark.process_memory", return_value={}), \
             patch("ferrial_drive.diagnostics.frame_benchmark.perf_counter", side_effect=lambda: next(ticks)):
            result = benchmark_program(app, canvas, interactive=interactive, frames=None if interactive else 10,
                                       warmup=0, paced=False, sample_capacity=2)
        return result, events, deltas

    def test_manual_forwards_key_events_and_uses_real_delta_with_bounded_samples(self):
        result, events, deltas = self.run_frames(True)
        self.assertEqual([event.type for event in events], [10, 11])
        self.assertEqual(len(deltas), 3)
        self.assertTrue(all(delta != 1/165 for delta in deltas))
        self.assertEqual(result["total_measured_frames"], 3)
        self.assertEqual(len(result["frames"]), 2)
        self.assertIsNone(result["fixed_update_seconds"])
        self.assertTrue(result["completed"])

    def test_auto_ignores_player_events_and_uses_fixed_delta(self):
        result, events, deltas = self.run_frames(False)
        self.assertFalse(events)
        self.assertTrue(all(delta == 1/165 for delta in deltas))
        self.assertFalse(result["completed"])


class ProbeRestorationTests(unittest.TestCase):
    def test_inherited_method_restored_without_instance_override(self):
        class Target:
            def draw(self):
                return 42

        target = Target()
        probe = RenderBreakdown(None, detailed=True)
        probe.method(target, "draw", "world.total")
        probe.method(target, "draw", "world.total")
        probe.step(True)
        self.assertEqual(target.draw(), 42)
        self.assertEqual(probe.report()["timings"]["measurements"][0]["calls"], 1)
        probe.close()
        self.assertNotIn("draw", target.__dict__)
        self.assertEqual(target.draw(), 42)

    def test_blur_exception_preserves_context_cleanup(self):
        cleanup = []

        @contextmanager
        def blur(*a):
            try:
                yield
            finally:
                cleanup.append(True)

        renderer = SimpleNamespace(directional_blur=blur)
        probe = RenderBreakdown(None, detailed=True)
        probe._install_blur(renderer)
        probe.step(True)
        with self.assertRaisesRegex(ValueError, "inner"):
            with renderer.directional_blur():
                raise ValueError("inner")
        self.assertEqual(cleanup, [True])
        probe.close()
        self.assertIs(renderer.directional_blur, blur)


if __name__ == "__main__":
    unittest.main()

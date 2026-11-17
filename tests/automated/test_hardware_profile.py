"""기능 초과 차단·오판 방지·실제 Windows 자식 제한을 검사한다."""

import ctypes as ct
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from ferrial_drive.diagnostics.frame_benchmark import summarize_frames
from ferrial_drive.diagnostics.gpu_profile import GpuProfileViolation, Uhd630Profile
from ferrial_drive.diagnostics.resource_limits import ResourceLimits, run_gated_child


ROOT = Path(__file__).resolve().parents[2]


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.profile = Uhd630Profile(None)

    def test_future_and_vendor_functions_rejected(self):
        for name in ("glSpecializeShader", "glDrawMeshTasksNV", "glMadeUpFunction"):
            with self.assertRaises(GpuProfileViolation):
                self.profile.check_function(name)
        self.profile.check_function("glDispatchCompute")

    def test_shader_sources_checked_before_native_call(self):
        calls = []
        guarded = self.profile.wrap("glShaderSource", lambda *a: calls.append(True))
        source = ct.c_char_p(b"#version 460\nvoid main() {}")
        with self.assertRaises(GpuProfileViolation):
            guarded(1, 1, ct.byref(source), None)
        self.assertEqual(calls, [])

    def test_split_shader_directive_cannot_bypass_guard(self):
        chunks = (ct.c_char_p * 2)(b"#version ", b"460\nvoid main() {}")
        with self.assertRaises(GpuProfileViolation):
            self.profile.wrap("glShaderSource", lambda *a: None)(1, 2, chunks, None)

    def test_shader_compatibility_and_compute(self):
        self.profile.shader_source(b"#version 120\nvoid main() {}")
        self.profile.shader_source(b"#version 430\nlayout(local_size_x=64) in;")
        with self.assertRaises(GpuProfileViolation):
            self.profile.shader_source(b"#version 430\nlayout(local_size_x=1024, local_size_y=2) in;")
        with self.assertRaises(GpuProfileViolation):
            self.profile.shader_source(b"#version 450\n#extension GL_NV_mesh_shader : require")
        with self.assertRaises(GpuProfileViolation):
            self.profile.shader_source(b"#version 450\n#extension all : warn")
        with self.assertRaises(GpuProfileViolation):
            self.profile.shader_source(b"#version 4\\\n60\nvoid main() {}")

    def test_texture_buffer_and_dispatch_rejected_before_driver(self):
        for name, args in (("glTexImage2D", (0x0DE1, 0, 0x8058, 16385, 1, 0, 0, 0, None)),
                           ("glBufferData", (0x90D2, 128*1024**2+1, None, 0)),
                           ("glDispatchCompute", (65536, 1, 1)),
                           ("glActiveTexture", (0x84C0+16,))):
            calls = []
            with self.subTest(name=name), self.assertRaises(GpuProfileViolation):
                self.profile.wrap(name, lambda *a: calls.append(True))(*args)
            self.assertEqual(calls, [])

    def test_limit_query_preserves_lower_host_cap(self):
        def query(enum, pointer):
            ct.cast(pointer, ct.POINTER(ct.c_int))[0] = 8192
        value = ct.c_int()
        self.profile.wrap("glGetIntegerv", query)(0x0D33, ct.byref(value))
        self.assertEqual(value.value, 8192)

    def test_deadline_miss_is_not_hidden_by_average(self):
        rows = [dict.fromkeys(("work_ms", "events_ms", "update_ms", "draw_submit_ms", "present_ms", "interval_ms"), v)
                for v in (1, 1, 1, 20)]
        result = summarize_frames(rows, target_fps=165, expected_frames=4, elapsed_seconds=.024)
        self.assertLess(result["work_ms"]["mean"], result["budget_ms"])
        self.assertFalse(result["all_work_within_budget"])
        self.assertEqual(result["deadline_miss_percent"], 25)

    def test_incomplete_run_never_passes(self):
        self.assertFalse(summarize_frames([], target_fps=165, expected_frames=1, elapsed_seconds=0)["all_work_within_budget"])

    def test_pacing_failure_does_not_pass_on_work_time_alone(self):
        row = dict.fromkeys(("work_ms", "events_ms", "update_ms", "draw_submit_ms", "present_ms", "interval_ms"), 1)
        self.assertFalse(summarize_frames([row], target_fps=165, expected_frames=1, elapsed_seconds=.1)["target_met"])

    def test_entrypoint_import_opens_no_window(self):
        code = """
import importlib.util, sys
s = importlib.util.spec_from_file_location('hardware_benchmark', 'tests/hardware_profile_benchmark.py')
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
assert m.UNIT_TEST_ENTRYPOINT == 'standalone'
assert not any(name.startswith('pico2d') for name in sys.modules)
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_resource_limits(self):
        for args in ({"logical_cpus": 0}, {"cpu_percent": 0}, {"cpu_percent": float("nan")}, {"memory_mib": 32}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ResourceLimits(**args)


@unittest.skipUnless(os.name == "nt", "Windows Job Objects 전용")
class NativeLimitsTests(unittest.TestCase):
    def test_job_membership_affinity_cpu_and_commit_ceiling(self):
        code = """
import ctypes as c
from ferrial_drive.diagnostics.resource_limits import wait_for_limits
r = wait_for_limits()
assert r['verified'] and r['in_job'] and len(r['logical_cpu_ids']) == 1
k = c.WinDLL('kernel32', use_last_error=True)
k.VirtualAlloc.restype = c.c_void_p
k.VirtualAlloc.argtypes = [c.c_void_p, c.c_size_t, c.c_uint32, c.c_uint32]
p = k.VirtualAlloc(None, 128*1024**2, 0x3000, 4)
assert not p, '커밋 제한이 적용되지 않았다.'
print('Windows Job CPU/affinity/64MiB commit verified', flush=True)
"""
        result, report = run_gated_child([sys.executable, "-c", code], cwd=ROOT,
                                        limits=ResourceLimits(logical_cpus=1, cpu_percent=5, memory_mib=64))
        self.assertEqual(result, 0)
        self.assertEqual(report["cpu_rate_units"], 500)
        self.assertEqual(report["process_memory_limit_bytes"], 64*1024**2)

    def test_no_gate_signal_fails_before_work(self):
        result = subprocess.run([sys.executable, "-c",
            "from ferrial_drive.diagnostics.resource_limits import wait_for_limits; wait_for_limits()"],
            input="", text=True, capture_output=True, cwd=ROOT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RuntimeError", result.stderr)


@unittest.skipUnless(os.environ.get("FDRIVE_GPU_TESTS") == "1", "실제 GPU 검사는 선택 실행한다.")
class ProfileGpuTests(unittest.TestCase):
    def test_real_shader_texture_guard_and_restoration_after_failure(self):
        import pico2d.pico2d as pico
        from ferrial_drive.diagnostics.gpu_profile import bind_gl
        from ferrial_drive.rendering import PicoCanvas
        from ferrial_drive.rendering.bicubic import acquire_sampler

        create_window = pico.SDL_CreateWindow

        def hidden_window(title, x, y, width, height, flags):
            return create_window(title, x, y, width, height, (flags & ~pico.SDL_WINDOW_SHOWN) | pico.SDL_WINDOW_HIDDEN)

        with patch.dict(os.environ, {"SDL_VIDEODRIVER": "windows"}), patch.object(pico, "SDL_CreateWindow", side_effect=hidden_window):
            with PicoCanvas(32, 32, "Hardware profile verification"):
                originals = [pico.SDL_CreateTexture, pico.SDL_CreateTextureFromSurface, pico.IMG_LoadTexture]
                guard = Uhd630Profile(pico)
                with self.assertRaises(GpuProfileViolation):
                    with guard:
                        sampler = acquire_sampler(pico)
                        try:
                            self.assertLessEqual(sampler.integer(0x0D33), 16384)
                            self.assertIn(120, guard.shader_versions)
                            with self.assertRaises(GpuProfileViolation):
                                pico.SDL_CreateTexture(pico.renderer, pico.SDL_PIXELFORMAT_RGBA32, 0, 16385, 1)
                            bind_gl(pico, "glDrawMeshTasksNV", None, [ct.c_uint, ct.c_uint])
                        finally:
                            sampler.release()
                self.assertEqual([pico.SDL_CreateTexture, pico.SDL_CreateTextureFromSurface, pico.IMG_LoadTexture], originals)


if __name__ == "__main__":
    unittest.main()

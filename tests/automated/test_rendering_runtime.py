"""FDrive 공통 실행부의 수명·실패 정리·입력 중단과 드라이버 격리를 검사한다."""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from ferrial_drive.assets import AssetCatalog, AssetManager
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from ferrial_drive.rendering import PicoCanvas
from ferrial_drive.runtime import run_application


ROOT = Path(__file__).resolve().parents[2]


class SampleProgram:
    def __init__(self):
        self.running = True
        self.actions = []
        self.manager = None

    def enter(self):
        import pico2d.pico2d as pico
        self.pico = pico
        self.actions.append('enter')
        self.manager = AssetManager(AssetCatalog.load(ROOT / 'samples/asset_loader/catalog.json'), PicoAssetBackend())
        self.handle = self.manager.acquire('sample_mech')

    def handle_event(self, event):
        pass

    def update(self, delta_seconds):
        assert delta_seconds >= 0
        self.actions.append('update')

    def draw(self):
        self.actions.append('draw')
        self.handle.resource.draw('idle/s', 0, 32, 16, scale=0.25)

    def exit(self):
        assert self.pico.renderer
        self.actions.append('exit')
        if self.manager is not None:
            self.manager.close()


class RenderingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, SDL_VIDEODRIVER='dummy')
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def run_program(self, program, **kwargs):
        with patch('ferrial_drive.runtime.sleep'):
            options = {'width': 64, 'height': 64, 'title': 'FDrive lifecycle', 'frame_limit': 2}
            options.update(kwargs)
            run_application(program, **options)

    def test_import_does_not_load_pico_tools_or_test_programs(self):
        script = ('import sys; import ferrial_drive.rendering; import ferrial_drive.runtime; '
                  'assert not any(k.startswith(("pico2d", "Tools", "tests")) for k in sys.modules)')
        subprocess.run([sys.executable, '-c', script], cwd=ROOT, check=True, capture_output=True)

    def test_frame_limit_keeps_resource_cleanup_before_canvas_and_can_restart(self):
        for _ in range(2):
            program = SampleProgram()
            self.run_program(program)
            self.assertEqual(program.actions, ['enter', 'update', 'draw', 'update', 'draw', 'exit'])
            self.assertTrue(program.manager.closed)
            self.assertIsNone(program.pico.renderer)

    def test_draw_failure_still_closes_resources_and_canvas(self):
        program = SampleProgram()
        with patch.object(program, 'draw', side_effect=RuntimeError('draw failed')):
            with self.assertRaisesRegex(RuntimeError, 'draw failed'):
                self.run_program(program)
        self.assertEqual(program.actions[-1], 'exit')
        self.assertTrue(program.manager.closed)
        self.assertIsNone(program.pico.renderer)

    def test_enter_failure_still_calls_exit_and_closes_canvas(self):
        program = SampleProgram()
        enter = program.enter
        def fail_after_load():
            enter()
            raise RuntimeError('enter failed')
        with patch.object(program, 'enter', side_effect=fail_after_load):
            with self.assertRaisesRegex(RuntimeError, 'enter failed'):
                self.run_program(program)
        self.assertEqual(program.actions, ['enter', 'exit'])
        self.assertTrue(program.manager.closed)
        self.assertIsNone(program.pico.renderer)

    def test_quit_event_stops_before_update_and_draw(self):
        from ctypes import byref
        program = SampleProgram()
        enter = program.enter
        def enter_and_quit():
            enter()
            event = program.pico.SDL_Event()
            event.type = program.pico.SDL_QUIT
            program.pico.SDL_PushEvent(byref(event))
        with patch.object(program, 'enter', side_effect=enter_and_quit):
            self.run_program(program)
        self.assertEqual(program.actions, ['enter', 'exit'])
        self.assertFalse(program.running)

    def test_canvas_restores_driver_hint_rejects_nested_owner_and_closes_once(self):
        import pico2d.pico2d as pico
        previous = pico.SDL_GetHint(pico.SDL_HINT_RENDER_DRIVER)
        pico.SDL_SetHint(pico.SDL_HINT_RENDER_DRIVER, b'software')
        try:
            canvas = PicoCanvas(64, 64, 'FDrive canvas')
            with canvas:
                self.assertEqual(canvas.info.name, 'software')
                self.assertEqual(pico.SDL_GetHint(pico.SDL_HINT_RENDER_DRIVER), b'software')
                with self.assertRaises(RuntimeError):
                    PicoCanvas(64, 64, 'nested').open()
            canvas.close()
            with self.assertRaises(RuntimeError):
                canvas.present()
        finally:
            if previous is None:
                pico.SDL_ResetHint(pico.SDL_HINT_RENDER_DRIVER)
            else:
                pico.SDL_SetHint(pico.SDL_HINT_RENDER_DRIVER, previous)

    def test_invalid_settings_do_not_open_a_canvas(self):
        for width, height in ((0, 64), (64, -1), (True, 64), (64.5, 64)):
            with self.assertRaises(ValueError):
                PicoCanvas(width, height, 'invalid')
        with patch('ferrial_drive.runtime.PicoCanvas') as canvas:
            for kwargs in ({'frames_per_second': 0}, {'frame_limit': -1}):
                with self.assertRaises(ValueError):
                    self.run_program(SampleProgram(), **kwargs)
            canvas.assert_not_called()

    def test_failed_open_restores_driver_hint_and_allows_a_new_canvas(self):
        import pico2d.pico2d as pico
        previous = pico.SDL_GetHint(pico.SDL_HINT_RENDER_DRIVER)
        with patch('ferrial_drive.rendering.canvas.renderer_info', side_effect=RuntimeError('query failed')):
            with self.assertRaisesRegex(RuntimeError, 'query failed'):
                PicoCanvas(64, 64, 'failed').open()
        self.assertEqual(pico.SDL_GetHint(pico.SDL_HINT_RENDER_DRIVER), previous)
        self.assertIsNone(pico.renderer)
        with PicoCanvas(64, 64, 'recovered') as canvas:
            self.assertEqual(canvas.info.name, 'software')


if __name__ == '__main__':
    unittest.main()

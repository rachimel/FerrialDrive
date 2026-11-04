"""에셋 로딩·재생·실제 RGBA 패킹과 실패한 빌드의 완료 표시 경계를 확인한다."""

from copy import deepcopy
from ctypes import string_at
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zlib

from ferrial_drive.assets import SpriteBundle, SpritePlayback
from Tools.blender_pipeline.asset_build import AssetBuild, pipeline_signature
from Tools.blender_pipeline.pack_sprites import pack_rendered_frames


ROOT = Path(__file__).resolve().parents[2]


def write_png(path, color):
    # 외부 게임 이미지·Pillow에 의존하지 않는 4×4 RGBA fixture.
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    rows = []
    for y in range(4):
        rows.append(b'\x00' + b''.join(bytes(color if 1 <= x <= 2 and 1 <= y <= 2 else (0, 0, 0, 0))
                                      for x in range(4)))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 4, 4, 8, 6, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))


class AssetPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='asset-pipeline-')
        self.directory = Path(self.temporary.name)
        rows = []
        for index, direction in enumerate(('e', 'ne', 'n', 'nw', 'w', 'sw', 's', 'se')):
            frames = []
            for frame in range(2):
                entry = {}
                for layer in ('body', 'shadow'):
                    path = self.directory / f'{direction}-{frame}-{layer}.png'
                    write_png(path, (index * 25, frame * 80, 180, 128) if layer == 'body' else (0, 0, 0, 80))
                    entry[layer] = path.name
                frames.append(entry)
            rows.append({'id': direction, 'frames': frames})
        self.data = {'asset_id': 'fixture', 'frame_size_pixels': [4, 4], 'pivot': [2, 1],
                     'fps': 8, 'directions': rows, 'config_sha256': 'fixture-hash', 'blender_version': 'test'}
        self.source = self.directory / 'rendered_frames.json'
        self.source.write_text(json.dumps(self.data), encoding='utf-8')
        self.bundle_path = pack_rendered_frames(self.source)

    def tearDown(self):
        self.temporary.cleanup()

    def test_pack_preserves_rgba_and_bottom_left_frame_coordinates(self):
        import pico2d.pico2d as pico
        bundle = SpriteBundle.load(self.bundle_path)
        self.assertEqual(bundle.body.size, (8, 32))
        self.assertEqual(bundle.body.clips['walk/e'].frames[0].rect, (0, 28, 4, 4))
        self.assertEqual(bundle.body.clips['walk/se'].frames[1].rect, (4, 0, 4, 4))
        surface = pico.IMG_Load(str(bundle.body.image_path).encode('utf-8'))
        rgba = None
        try:
            rgba = pico.SDL_ConvertSurfaceFormat(surface, pico.SDL_PIXELFORMAT_RGBA32, 0)
            raw = string_at(rgba.contents.pixels, rgba.contents.pitch * 32)
            for row in range(8):
                for frame in range(2):
                    offset = (row * 4 + 1) * rgba.contents.pitch + (frame * 4 + 1) * 4
                    self.assertEqual(tuple(raw[offset:offset + 4]), (row * 25, frame * 80, 180, 128))
        finally:
            if rgba:
                pico.SDL_FreeSurface(rgba)
            pico.SDL_FreeSurface(surface)

    def test_time_based_playback_direction_pause_step_and_loop(self):
        player = SpritePlayback(SpriteBundle.load(self.bundle_path))
        player.update(0.125)
        self.assertEqual(player.frame_index, 1)
        player.select_direction('sw')
        self.assertEqual(player.frame_index, 1)
        player.paused = True
        player.update(10)
        self.assertEqual(player.frame_index, 1)
        player.step()
        self.assertEqual(player.frame_index, 0)
        with self.assertRaises(ValueError):
            player.update(float('nan'))

    def test_missing_image_invalid_bounds_and_shadow_mismatch_are_rejected(self):
        path = self.directory / 'shadow.json'
        original = json.loads(path.read_text())
        for change in ('bounds', 'fps', 'missing'):
            data = deepcopy(original)
            if change == 'bounds':
                data['animations'][0]['frames'][0]['rect'][2] = 9999
            elif change == 'fps':
                data['animations'][0]['fps'] = 9
            else:
                data['image']['path'] = 'missing.png'
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises((ValueError, FileNotFoundError)):
                SpriteBundle.load(self.bundle_path)
        path.write_text(json.dumps(original), encoding='utf-8')

    def test_cache_must_match_current_config_and_stay_inside_output_root(self):
        config = self.directory / 'config.json'
        config.write_text('{}')
        job = AssetBuild(config, output_root=self.directory)
        pointer = self.directory / 'latest.json'
        pointer.write_text(json.dumps({'bundle': 'bundle.json'}))
        self.assertIsNone(job.cached_result())  # fixture-hash와 실제 설정 해시가 다르다.
        import hashlib
        data = json.loads(self.bundle_path.read_text())
        data['config_sha256'] = hashlib.sha256(config.read_bytes()).hexdigest()
        data['pipeline_sha256'] = pipeline_signature()
        self.bundle_path.write_text(json.dumps(data))
        self.assertEqual(job.cached_result(), self.bundle_path)
        pointer.write_text(json.dumps({'bundle': '../outside/bundle.json'}))
        self.assertIsNone(job.cached_result())

    def test_failed_blender_does_not_publish_a_new_latest_pointer(self):
        pointer = self.directory / 'latest.json'
        pointer.write_text('previous')
        job = AssetBuild(self.source, output_root=self.directory)
        job.directory = self.directory
        job.log = io.BytesIO()
        job.process = SimpleNamespace(poll=lambda: 1, returncode=1)
        self.assertFalse(job.poll())
        self.assertEqual(pointer.read_text(), 'previous')
        self.assertIsNone(job.result)
        self.assertIn('Blender', job.error)

    def test_existing_sheet_editor_reads_the_generated_projects(self):
        import runpy
        editor = runpy.run_path(str(ROOT / 'Tools/SSheetCutil.py'), run_name='sheet_format_check')
        project, size = editor['import_project'](self.directory / 'body.json')
        self.assertEqual(size, (8, 32))
        self.assertEqual(len(project.animations), 8)
        self.assertEqual(project.animations[0].frames[0].pivot, (2, 1))

    def test_standalone_import_does_not_start_a_process_or_open_a_window(self):
        script = ('import runpy\nfrom unittest.mock import patch\n'
                  'with patch("subprocess.Popen", side_effect=AssertionError("unexpected process")):\n'
                  f'    data=runpy.run_path({str(ROOT / "tests/asset_load_test.py")!r}, run_name="import_check")\n'
                  '    app=data["create_test"]()\n'
                  '    assert app.renderer is None and app.build.process is None\n')
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=self.directory,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()

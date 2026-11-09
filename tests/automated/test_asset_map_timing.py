"""맵 번들 이동·합성·이동 구역과 가변 프레임 시간의 왕복을 검증한다."""

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

from ferrial_drive.assets import AssetDefinition, MapBundle, SpriteBundle, SpritePlayback, detect_kind
from ferrial_drive.assets.sprites import SpriteSheet
from samples.asset_loader.make_sample import write_samples
from samples.asset_loader.map.make_sample import write_sample
from Tools.asset_loader.assembly import SpriteAssembly
from Tools.asset_loader.automation import execute
from Tools.asset_loader.map_export import export_map, composite_rgba


class MapTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = write_sample(self.root / 'input')

    def tearDown(self):
        self.temp.cleanup()

    def request(self, operation, **fields):
        return execute(dict(version=1, operation=operation, **fields), base_dir=self.root)

    def test_map_export_move_import_preserves_layers_and_polygon_coordinates(self):
        before = {p.name: p.read_bytes() for p in self.source.parent.iterdir()}
        self.assertEqual(detect_kind(self.source), 'map')
        result = self.request('map.export', source=str(self.source), output='exported')
        shutil.move(self.root / 'exported', self.root / 'relocated')
        result = self.request('map.import', source='relocated/bundle.json')
        bundle = MapBundle.load(result['source'])
        self.assertEqual(bundle.data['walkable'], MapBundle.load(self.source).data['walkable'])
        self.assertTrue(bundle.contains(40, 40))
        self.assertTrue(bundle.contains(20, 12))
        self.assertFalse(bundle.contains(40, 150))
        self.assertEqual(bundle.paths['background'].read_bytes(), before['background.png'])
        self.assertEqual(bundle.paths['ground'].read_bytes(), before['ground.png'])
        self.assertTrue(bundle.paths['composite'].is_file())
        self.assertEqual({p.name: p.read_bytes() for p in self.source.parent.iterdir()}, before)
        inspected = self.request('asset.inspect', source=result['source'])
        self.assertEqual(set(inspected['clips']), {'background', 'ground', 'composite', 'walkable'})
        self.assertEqual(len(inspected['images']), 3)
        copied = self.request('map.import', source=result['source'], output='imported')
        self.assertTrue(Path(copied['source']).is_file())

    def test_map_composite_uses_background_then_ground_and_alpha(self):
        import pico2d.pico2d as pico
        from ctypes import c_uint8, byref
        output = self.request('map.export', source=str(self.source), output='out')
        bundle = MapBundle.load(output['source'])
        surface = pico.IMG_Load(str(bundle.paths['composite']).encode('utf-8'))
        try:
            def pixel(x, y):
                address = surface.contents.pixels + y * surface.contents.pitch + x * 4
                value = int.from_bytes(bytes((c_uint8 * 4).from_address(address)), 'little')
                rgba = [c_uint8() for _ in range(4)]
                pico.SDL_GetRGBA(value, surface.contents.format, *[byref(v) for v in rgba])
                return tuple(v.value for v in rgba)
            self.assertEqual(pixel(10, 10), (42, 60, 78, 255))
            self.assertEqual(pixel(10, 100), (88, 109, 111, 255))
        finally:
            pico.SDL_FreeSurface(surface)

    def test_composite_keeps_straight_alpha_for_transparent_backgrounds(self):
        self.assertEqual(composite_rgba(bytes([0, 0, 0, 0]), bytes([200, 80, 40, 128])), bytes([200, 80, 40, 128]))
        self.assertEqual(composite_rgba(bytes([200, 80, 40, 128]), bytes([0, 0, 0, 0])), bytes([200, 80, 40, 128]))
        self.assertEqual(composite_rgba(bytes([255, 0, 0, 128]), bytes([0, 0, 255, 128])), bytes([85, 0, 170, 192]))

    def test_map_failures_do_not_publish_or_overwrite(self):
        data = MapBundle.load(self.source).data
        for updates in ({'size': [1, 1]}, {'walkable': [[[0, 0], [1, 1]]]},
                        {'walkable': [[[0, 0], [1, 1], [2, 2]]]}, {'type': 'other'}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                export_map(dict(data, **updates), self.root / 'bad', base_dir=self.source.parent)
            self.assertFalse((self.root / 'bad').exists())
        with patch('Tools.asset_loader.map_export.shutil.copyfile', side_effect=OSError('copy')):
            with self.assertRaises(OSError):
                export_map(data, self.root / 'bad', base_dir=self.source.parent)
        self.assertEqual(list(self.root.glob('.bad.*')), [])
        exported = self.request('map.export', source=str(self.source), output='good')
        before = Path(exported['source']).read_bytes()
        with self.assertRaises(FileExistsError):
            self.request('map.export', source=str(self.source), output='good')
        self.assertEqual(Path(exported['source']).read_bytes(), before)

    def test_variable_frame_boundaries_step_and_roundtrip_sync_layers(self):
        path = write_samples(self.root / 'sprites') / 'bundle.json'
        assembly = SpriteAssembly(AssetDefinition('timed', 'bundle', path))
        assembly.apply('idle/e', 'attack', [3, 1, 1], durations_ms=[50, 200, 75])
        saved = assembly.save(self.root / 'timed', asset_id='timed')
        bundle = SpriteBundle.load(saved)
        clip = bundle.body.clips['attack/e']
        self.assertEqual(clip.durations_ms, (50, 200, 75))
        self.assertEqual(clip.duration_ms, 325)
        for seconds, index in ((0, 0), (.049, 0), (.05, 1), (.249, 1), (.25, 2), (.325, 0), (10.075, 0)):
            self.assertEqual(clip.frame_at(seconds), index)
        playback = SpritePlayback(bundle)
        playback.step()
        self.assertEqual(playback.frame_index, 1)
        playback.step()
        self.assertEqual(playback.frame_index, 2)
        playback.step()
        self.assertEqual(playback.frame_index, 0)
        self.assertTrue(all(bundle.body.clips[name] == bundle.shadow.clips[name] for name in bundle.directions.values()))
        self.assertEqual(SpriteBundle.load(path).body.clips['idle/e'].durations_ms, (1000 / 6,) * 4)

    def test_duration_only_sheet_and_invalid_times(self):
        path = write_samples(self.root / 'sprites') / 'body.json'
        data = json.loads(path.read_text())
        for row in data['animations']:
            row.pop('fps')
            for frame in row['frames']:
                frame['duration_ms'] = 80
        path.write_text(json.dumps(data))
        self.assertEqual(SpriteSheet.load(path).clips['idle/e'].duration_ms, 320)
        for duration in (0, -1, True, None, float('inf')):
            data['animations'][0]['frames'][0]['duration_ms'] = duration
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                SpriteSheet.load(path)

    def test_automation_accepts_per_frame_times_without_fps(self):
        path = write_samples(self.root / 'sprites') / 'bundle.json'
        result = self.request('sprite.assemble', source=str(path), asset_id='timed', output='timed', edits=[
            dict(source_clip='idle/e', name='timed', order=[0, 1], durations_ms=[45, 155])])
        bundle = SpriteBundle.load(result['source'])
        self.assertEqual(bundle.body.clips['timed/e'].durations_ms, (45, 155))


if __name__ == '__main__':
    unittest.main()

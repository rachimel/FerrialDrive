"""Energy Mask의 원본 위상·품질별 정렬·기체 밖 색상 보존을 검사한다."""

import ctypes as ct
import json
import os
from pathlib import Path
import tempfile
import unittest

from ferrial_drive.rendering.motion_atlas import build_variant, merge_variants, select_catalogs
from samples.texture_comparison.fixture import write_fixture


class MaskPreparationTests(unittest.TestCase):
    def test_merged_atlas_keeps_each_source_page_rect_and_mask_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            documents = []
            for index in range(2):
                source = write_fixture(root/f'input_{index}', energy_mask=True)
                if index:
                    catalog = json.loads(source.read_text())
                    for row in catalog['clips']:
                        row['name'] = 'other_' + row['name']
                    source.write_text(json.dumps(catalog))
                directory = root/f'atlas_{index}'
                documents.append((directory, build_variant(select_catalogs([source], None), directory, 4/3)))
            joined = root/'joined'
            result = merge_variants([d/'atlas.json' for d, _ in documents], joined,
                                    aliases={'sample_0': 'idle_loop'})
            self.assertEqual(len(result['clips']), 5)
            self.assertEqual(result['clips']['idle_loop/s'], result['clips']['sample_0/s'])
            for directory, original in documents:
                for name, clip in original['clips'].items():
                    for before, after in zip(clip['pairs'], result['clips'][name]['pairs']):
                        for field, kind in enumerate(('color','color','vector','vector','energy','energy')):
                            a, b = original['frames'][kind][before[field]], result['frames'][kind][after[field]]
                            self.assertEqual(a['rect'], b['rect'])
                            first = (directory/original['pages'][kind][a['page']]['file']).resolve()
                            second = (joined/result['pages'][kind][b['page']]['file']).resolve()
                            self.assertEqual(first, second)
            changed = documents[1][0]/'atlas.json'
            broken = json.loads(changed.read_text()); broken['divisor'] = 2
            changed.write_text(json.dumps(broken))
            with self.assertRaises(ValueError):
                merge_variants([d/'atlas.json' for d, _ in documents], root/'rejected')

    def test_mask_shares_pair_geometry_and_survives_each_resolution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = write_fixture(root/'source', energy_mask=True)
            for divisor in (1, 4/3, 2, 4):
                result = build_variant(select_catalogs([source], None), root/str(divisor), divisor)
                self.assertGreater(len(result['pages']['energy']), 0)
                for clip in result['clips'].values():
                    for pair in clip['pairs']:
                        self.assertEqual(len(pair), 6)
                        self.assertEqual(result['frames']['color'][pair[0]]['rect'][2:],
                                         result['frames']['energy'][pair[4]]['rect'][2:])

    def test_wrong_mask_alpha_or_frame_count_is_rejected(self):
        from PIL import Image
        for change in ('alpha', 'count'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                source = write_fixture(root/'source', energy_mask=True)
                path = source.parent/'clip.json'
                data = json.loads(path.read_text(encoding='utf-8'))
                if change == 'count':
                    data['energy_frames'].pop()
                    path.write_text(json.dumps(data), encoding='utf-8')
                else:
                    image = Image.open(source.parent/data['energy_frames'][0]).convert('RGBA')
                    image.putpixel((0, 0), (0, 0, 0, 255))
                    image.save(source.parent/data['energy_frames'][0])
                with self.assertRaises(ValueError):
                    build_variant(select_catalogs([source], None), root/'atlas', 1)

    def test_legacy_clip_keeps_four_indices_without_mask_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = build_variant(select_catalogs([write_fixture(root/'source')], None), root/'atlas', 1)
            self.assertNotIn('energy', result['pages'])
            self.assertTrue(all(len(pair) == 4 for clip in result['clips'].values() for pair in clip['pairs']))


@unittest.skipUnless(os.environ.get('FDRIVE_GPU_TESTS') == '1', '실제 OpenGL 검사는 선택 실행한다.')
class MaskGpuTests(unittest.TestCase):
    def test_interpolated_glow_changes_only_mask_and_keeps_alpha(self):
        import numpy as np
        from ferrial_drive.rendering import PicoCanvas
        from ferrial_drive.rendering.pico_motion_atlas import AtlasPainter, AtlasTextureCache, PicoMotionAtlas
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = write_fixture(root/'source', energy_mask=True)
            build_variant(select_catalogs([source], None), root/'atlas', 1)
            with PicoCanvas(192, 192, 'Energy Mask Contract', driver='opengl'):
                import pico2d.pico2d as pico
                painter = AtlasPainter(pico)
                cache = AtlasTextureCache(pico, painter.sampler)
                resource = PicoMotionAtlas(pico, root/'atlas/atlas.json', cache)
                target = pico.SDL_CreateTexture(pico.renderer, pico.SDL_PIXELFORMAT_RGBA32,
                                                pico.SDL_TEXTUREACCESS_TARGET, 192, 192)
                self.assertTrue(target)
                try:
                    self.assertEqual(pico.SDL_SetRenderTarget(pico.renderer, target), 0)
                    for phase in (0, 0.5, 1):
                        captures = []
                        for color in (None, (1, 0, 0), (0, 1, 0)):
                            pico.SDL_SetRenderDrawColor(pico.renderer, 0, 0, 0, 0)
                            pico.SDL_RenderClear(pico.renderer)
                            painter.draw(resource, 'sample_0/s', phase, pico.SDL_Rect(0, 0, 192, 192), energy_color=color,
                                         energy_mask_gain=4)
                            pixels = ct.create_string_buffer(192*192*4)
                            self.assertEqual(pico.SDL_RenderReadPixels(pico.renderer, None, pico.SDL_PIXELFORMAT_RGBA32, pixels, 192*4), 0)
                            captures.append(np.frombuffer(pixels.raw, dtype=np.uint8).reshape(192, 192, 4))
                        changed = np.any(captures[0] != captures[1], axis=2)
                        self.assertGreater(np.count_nonzero(changed), 0)
                        self.assertTrue(np.array_equal(captures[0][:, :, 3], captures[1][:, :, 3]))
                        self.assertGreater(np.count_nonzero((captures[0][:, :, 3] > 0) & (captures[0][:, :, 3] < 255)), 0)
                        self.assertTrue(np.array_equal(captures[0][~changed], captures[2][~changed]))
                        scene = json.loads((Path(__file__).parents[2]/'samples/texture_comparison/scene.json').read_text())
                        cx = (scene['start'][0] + (scene['end'][0]-scene['start'][0])*phase) * 192/scene['size']
                        _, xs = np.nonzero(changed)
                        self.assertTrue(np.all(np.abs(xs+0.5-cx) < 192/scene['size']*7))
                finally:
                    pico.SDL_SetRenderTarget(pico.renderer, None)
                    pico.SDL_DestroyTexture(target)
                    resource.close()
                    painter.close()

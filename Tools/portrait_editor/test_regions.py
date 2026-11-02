"""Region masks must survive portable saves and preserve source pixel positions."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import numpy as np
import pygame

from region_document import RegionDocument
from region_workspace import RegionWorkspace


class RegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((1, 1))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def document(self):
        image = pygame.Surface((160, 120), pygame.SRCALPHA)
        image.fill((50, 80, 120, 255))
        image.set_at((0, 0), (20, 30, 40, 0))
        return RegionDocument(image, '원본.png')

    def paint(self, doc):
        doc.start_stroke((30, 40), 8, False)
        doc.extend_stroke((90, 40))

    def test_erase_undo_regions_and_disconnected_strokes(self):
        doc = self.document()
        self.paint(doc)
        baseline = pygame.surfarray.array2d(doc.mask())
        self.assertEqual(baseline[50, 40], 255)
        doc.start_stroke((50, 40), 3, True)
        self.assertEqual(doc.mask().get_at((50, 40))[0], 0)
        doc.undo()
        np.testing.assert_array_equal(pygame.surfarray.array2d(doc.mask()), baseline)
        doc.undo(redo=True)
        self.assertEqual(doc.mask().get_at((50, 40))[0], 0)
        doc.add()
        self.assertFalse(pygame.surfarray.array2d(doc.mask()).any())
        doc.start_stroke((20, 80), 3, False)
        doc.extend_stroke(None)
        doc.extend_stroke((100, 80))
        self.assertEqual(doc.mask().get_at((60, 80))[0], 0)
        doc.selected = 0
        self.assertEqual(doc.mask().get_at((30, 40))[0], 255)

    def test_portable_roundtrip_export_and_original_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            doc = self.document()
            original = pygame.image.tobytes(doc.image, 'RGBA')
            self.paint(doc)
            doc.rename('左 eye / 눈')
            doc.add()
            doc.start_stroke((100, 85), 9, False)
            path = folder / 'portable.regions.zip'
            doc.save(path)
            self.assertFalse(doc.dirty)
            reopened = RegionDocument.load(path)
            self.assertEqual(reopened.regions, json.loads(json.dumps(doc.regions)))
            self.assertEqual(pygame.image.tobytes(reopened.image, 'RGBA'), original)
            for i in range(2):
                np.testing.assert_array_equal(pygame.surfarray.array2d(doc.mask(i)), pygame.surfarray.array2d(reopened.mask(i)))
            output = reopened.export(folder)
            manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['size'], [160, 120])
            self.assertEqual(len(manifest['regions']), 2)
            self.assertEqual(pygame.image.tobytes(pygame.image.load(str(output / 'source.png')), 'RGBA'), original)
            with self.assertRaises(ValueError):
                reopened.save(output / 'source.png')
            self.assertEqual(pygame.image.tobytes(pygame.image.load(str(output / 'source.png')), 'RGBA'), original)
            for i, entry in enumerate(manifest['regions']):
                mask = pygame.image.load(str(output / entry['mask']))
                self.assertEqual(mask.get_size(), (160, 120))
                # Check color values as a downstream consumer would, independently of palette indices.
                np.testing.assert_array_equal(pygame.surfarray.array3d(mask)[:, :, 0], pygame.surfarray.array2d(doc.mask(i)))
                self.assertEqual(pygame.image.load(str(output / entry['guide'])).get_size(), (160, 120))
            self.assertIn('대략적인 위치', (output / 'request.txt').read_text(encoding='utf-8'))
            self.assertEqual(pygame.image.tobytes(doc.image, 'RGBA'), original)

    def test_reject_empty_export_and_bad_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            doc = self.document()
            with self.assertRaises(ValueError):
                doc.export(folder)
            self.assertEqual(list(folder.iterdir()), [])
            self.paint(doc)
            path = folder / 'bad.regions.zip'
            doc.save(path)
            with zipfile.ZipFile(path) as archive:
                source = archive.read('source.png')
                payload = json.loads(archive.read('regions.json'))
            payload['regions'][0]['strokes'][0]['points'][0] = [900, 40]
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('source.png', source)
                archive.writestr('regions.json', json.dumps(payload))
            with self.assertRaises(ValueError):
                RegionDocument.load(path)

    def test_screen_to_source_mapping_resize_and_unsaved_guard(self):
        workspace = RegionWorkspace(Path('.'), lambda: None)
        workspace.replace(self.document())
        for size, zoom, pan in [((1600, 940), 1., [0., 0.]), ((1280, 800), 2.3, [20., -35.])]:
            workspace.zoom, workspace.pan = zoom, pan
            workspace.render(size)
            position = (workspace.image_rect.x + round(80 * workspace.scale), workspace.image_rect.y + round(60 * workspace.scale))
            point = workspace.point(position)
            self.assertIsNotNone(point)
            self.assertLessEqual(abs(point[0] - 80), 1)
            self.assertLessEqual(abs(point[1] - 60), 1)
        called = []
        workspace.guard(lambda: called.append(True))
        self.assertFalse(called)
        workspace.action('cancel')
        self.assertIsNone(workspace.pending)
        workspace.guard(lambda: called.append(True))
        workspace.action('discard')
        self.assertEqual(called, [True])


if __name__ == '__main__':
    unittest.main(verbosity=2)

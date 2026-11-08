"""완료 PNG 로그의 증분 처리·정확한 분모·패킹/실패/취소 상태를 검사한다."""

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from Tools.blender_pipeline.asset_build import AssetBuild


class AssetProgressTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='asset-progress-')
        self.root = Path(self.temporary.name)
        self.config = {'directions': [{'id': name} for name in ('e', 'ne', 'n', 'nw', 'w', 'sw', 's', 'se')],
                       'frames': [1, 3, 5, 7]}
        path = self.root / 'config.json'
        path.write_text(json.dumps(self.config))
        self.job = AssetBuild(path, output_root=self.root)
        self.job._prepare_progress(path.read_bytes())
        self.job.directory = self.root
        self.path = self.root / 'blender.log'
        self.path.write_bytes(b'')
        self.job._progress_reader = self.path.open('rb')
        self.job.log = io.BytesIO()
        self.job.source_sha256 = None

    def tearDown(self):
        self.job.close()
        self.temporary.cleanup()

    def append(self, data):
        with self.path.open('ab') as stream:
            stream.write(data)

    def markers(self):
        return [f'ASSET_FRAME {direction["id"]} {frame} {layer}\n'.encode()
                for direction in self.config['directions'] for frame in self.config['frames']
                for layer in ('body', 'shadow')]

    def test_expected_count_and_percent_follow_actual_completed_pngs(self):
        self.assertEqual(self.job.progress_text, '프리렌더 0% (0/64) · 준비 중')
        self.append(b''.join(self.markers()[:29]))
        self.job._read_progress()
        self.assertEqual(self.job.completed_images, 29)
        self.assertEqual(self.job.progress_percent, 45)
        self.assertEqual(self.job.progress_text, '프리렌더 45% (29/64)')

    def test_partial_duplicate_and_unrelated_log_lines_do_not_inflate_progress(self):
        self.append(b'ASSET_FRAME e 1 bo')
        self.job._read_progress()
        self.assertEqual(self.job.completed_images, 0)
        self.append(b'dy\r\nASSET_FRAME e 1 body\nASSET_FRAME invalid 1 body\n'
                    b'ASSET_FRAME e 999 shadow\nBlender saved file\nASSET_FRAME e 1 shadow\n')
        self.job._read_progress()
        self.assertEqual(self.job.completed_images, 2)
        self.job._read_progress()
        self.assertEqual(self.job.completed_images, 2)

    def test_success_displays_packing_before_publishing_completion(self):
        self.append(b''.join(self.markers()))
        self.job.process = SimpleNamespace(poll=lambda: 0, returncode=0)
        bundle = self.root / 'bundle.json'
        bundle.write_text('{}')
        with patch('Tools.blender_pipeline.asset_build.pack_rendered_frames', return_value=bundle) as pack, \
             patch('Tools.blender_pipeline.asset_build.SpriteBundle.load'):
            self.assertIsNone(self.job.poll())
            self.assertEqual(self.job.progress_text, '프리렌더 100% (64/64) · 시트 패킹 중')
            self.assertIsNotNone(self.job.process)
            pack.assert_not_called()
            self.assertFalse((self.root / 'latest.json').exists())
            self.assertTrue(self.job.poll())
        self.assertEqual(self.job.progress_text, '프리렌더 완료 100% (64/64)')
        self.assertIsNone(self.job.process)
        self.assertIsNone(self.job._progress_reader)

    def test_failed_process_keeps_partial_count_and_closes_progress_reader(self):
        self.append(self.markers()[0])
        self.job.process = SimpleNamespace(poll=lambda: 1, returncode=1)
        self.assertFalse(self.job.poll())
        self.assertEqual(self.job.completed_images, 1)
        self.assertEqual(self.job.stage, 'failed')
        self.assertIsNone(self.job._progress_reader)
        self.assertFalse((self.root / 'latest.json').exists())

    def test_failed_pack_does_not_claim_completion_after_all_images_render(self):
        self.append(b''.join(self.markers()))
        self.job.process = SimpleNamespace(poll=lambda: 0, returncode=0)
        with patch('Tools.blender_pipeline.asset_build.pack_rendered_frames', side_effect=ValueError('bad sheet')):
            self.assertIsNone(self.job.poll())
            self.assertFalse(self.job.poll())
        self.assertEqual(self.job.stage, 'failed')
        self.assertNotIn('완료', self.job.progress_text)
        self.assertEqual(self.job.completed_images, 64)

    def test_cancel_preserves_count_and_restart_resets_progress(self):
        self.append(self.markers()[0])
        self.job._read_progress()
        process = Mock()
        process.poll.return_value = None
        self.job.process = process
        self.job.close()
        process.terminate.assert_called_once()
        self.assertEqual(self.job.stage, 'cancelled')
        self.assertEqual(self.job.completed_images, 1)
        self.assertIsNone(self.job._progress_reader)
        self.job._prepare_progress(json.dumps(self.config).encode())
        self.assertEqual(self.job.progress_percent, 0)
        self.assertEqual(self.job.completed_images, 0)

    def test_tool_message_follows_shared_build_progress(self):
        from Tools.asset_loader.app import AssetLoaderApp
        app = AssetLoaderApp()
        app.build = SimpleNamespace(process=object(), poll=lambda: None,
                                    progress_text='프리렌더 45% (29/64)')
        app.update(0.1)
        self.assertEqual(app.message, '프리렌더 45% (29/64)')
        self.assertFalse(app.error)


if __name__ == '__main__':
    unittest.main()

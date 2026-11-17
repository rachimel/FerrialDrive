"""Trail 준비 파일의 원본 일치·무생성 로드·실패 시 보존과 자동화 경로를 검사한다."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from ferrial_drive.assets.trail_flow import flow_texture_path, load_flow_texture, prepare_flow_texture
from ferrial_drive.rendering.sword_trail_texture import trail_flow_pixels


ROOT = Path(__file__).resolve().parents[2]


class TrailFlowPreparationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.directory = Path(self.workspace.name)
        self.settings = dict(flow_strands=3, flow_softness=.018)

    def prepare(self):
        return prepare_flow_texture(self.settings, self.directory, width=32, height=16)

    def load(self):
        return load_flow_texture(self.settings, self.directory, width=32, height=16)

    def test_prepared_bytes_match_original_generator_and_load_never_generates(self):
        self.prepare()
        expected = trail_flow_pixels(32,16,strands=3,softness=.018)
        with patch('ferrial_drive.rendering.sword_trail_texture.trail_flow_pixels', side_effect=AssertionError('런타임 생성')):
            recipe,pixels = self.load()
            reused = self.prepare()
        self.assertEqual(pixels,expected)
        self.assertEqual((recipe['width'],recipe['height']),(32,16))
        self.assertTrue(reused['reused'])

    def test_missing_file_does_not_generate_and_parameter_change_keeps_original(self):
        with patch('ferrial_drive.rendering.sword_trail_texture.trail_flow_pixels', side_effect=AssertionError('자동 생성')):
            with self.assertRaises(FileNotFoundError):
                self.load()
        result = self.prepare()
        path = Path(result['path'])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        changed = dict(self.settings,flow_strands=4)
        self.assertNotEqual(flow_texture_path(changed,self.directory),flow_texture_path(self.settings,self.directory))
        with self.assertRaises(FileNotFoundError):
            load_flow_texture(changed,self.directory,width=32,height=16)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_corrupted_payload_hash_and_recipe_are_rejected(self):
        result = self.prepare()
        path = Path(result['path'])
        with ZipFile(path) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            pixels = archive.read('pixels.rgba')
        for mutation in ('hash','size','recipe'):
            row = json.loads(json.dumps(manifest))
            payload = pixels
            if mutation=='hash':
                payload = bytes([pixels[0]^1])+pixels[1:]
            elif mutation=='size':
                payload = pixels[:-1]
            else:
                row['recipe']['version'] += 1
            with ZipFile(path,'w') as archive:
                archive.writestr('manifest.json',json.dumps(row))
                archive.writestr('pixels.rgba',payload)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                self.load()

    def test_failed_write_removes_temporary_file_and_does_not_publish_partial_asset(self):
        with patch('ferrial_drive.assets.trail_flow.ZipFile.writestr',side_effect=OSError('의도한 저장 실패')):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_automation_runs_without_game_assets_from_another_working_directory(self):
        source = self.directory/'config.json'
        source.write_text(json.dumps({'sword_effects':dict(self.settings,demo_flow_texture_directory='prepared')}),encoding='utf-8')
        completed = subprocess.run([sys.executable,str(ROOT/'automate/run.py'),'trail-texture','--config',str(source),'--demo'],
                                   cwd=self.directory,capture_output=True,text=True,check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(Path(result['path']).parent,self.directory/'prepared')
        self.assertEqual(result['rgba_bytes'],512*128*4)


if __name__=='__main__':
    unittest.main()

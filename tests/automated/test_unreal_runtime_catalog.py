"""공개 도형으로 별칭·이동/공격 분리와 원본 참조·해시 거부를 확인한다."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automate.unreal.runtime_catalog import assemble
from ferrial_drive.assets.catalog import AssetCatalog
from ferrial_drive.assets.mech import MechBundle
from samples.unreal_pipeline.runtime_fixture import write_runtime_fixture


class RuntimeCatalogTests(unittest.TestCase):
    def test_aliases_preserve_original_frames_and_masks_in_separate_runtime_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = root/'output/fixture'
            request = write_runtime_fixture(fixture)
            motion = fixture/'input/motion/catalog.json'
            original = fixture/'input/source/packed/mech.json'
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            asset_root = Path(request['output'])
            motion_root = Path(request['interpolation_output'])
            with patch('automate.unreal.runtime_catalog.ROOT', root):
                report = assemble(request)
            self.assertEqual(report['runtime_clips'], 4)
            for group, names in [('movement', {'sample_0/s', 'idle_loop/s'}), ('combat', {'sample_1/s', 'combo_01/s'})]:
                definition = next(iter(AssetCatalog.load(asset_root/group/'catalog.json').definitions.values()))
                bundle = MechBundle.load(definition.source)
                self.assertEqual(set(bundle.clips), names)
                self.assertEqual(bundle.sheet_paths['body:energy'].parent, original.parent)
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), digest)
            document = json.loads((motion_root/'catalog.json').read_text())
            aliases = {row['name']: row['path'] for row in document['clips']}
            self.assertEqual(aliases['sample_0/s'], aliases['idle_loop/s'])
            guarded = document['source_assets'][0]
            target = (motion_root/guarded['path']).resolve()
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), guarded['sha256'])
            motion_data = json.loads(motion.read_text())
            motion_data['source_assets'] = [{'path': '../source/packed/mech.json', 'sha256': digest}]
            motion.write_text(json.dumps(motion_data), encoding='utf-8')
            original.write_bytes(original.read_bytes() + b'\n')
            request.update(output='data/rejected', interpolation_output='data/rejected_motion')
            with patch('automate.unreal.runtime_catalog.ROOT', root), self.assertRaises(ValueError):
                assemble(request)
            self.assertFalse((root/'data/rejected').exists())


if __name__ == '__main__':
    unittest.main()

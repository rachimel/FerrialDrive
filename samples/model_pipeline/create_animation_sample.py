"""게임 에셋 없이 단일 본·상자 애니메이션과 출력 설정을 만든다."""
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'Tools/blender_pipeline'))
from animation_pipeline import bake

directory = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
directory.mkdir(parents=True, exist_ok=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
actor = bpy.data.objects.new('SampleActor', None)
bpy.context.scene.collection.objects.link(actor)
bpy.ops.object.armature_add()
rig = bpy.context.object
rig.name = 'SampleRig'
rig.parent = actor
bpy.ops.mesh.primitive_cube_add(size=.4, location=(0, 0, 1))
box = bpy.context.object
box.parent = rig
box.parent_type = 'BONE'
box.parent_bone = 'Bone'
source = directory / 'source.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(source))
samples = [{'frame': i+1, 'bones': {'Bone': [list(row) for row in Matrix.Rotation(angle, 4, 'X')]}}
           for i, angle in enumerate((0, .3, -.3, 0))]
manifest = directory / 'poses.json'
manifest.write_text(json.dumps({'version': 1, 'asset_id': 'animation_sample', 'source': 'source.blend',
    'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'fps': 8,
    'rig': rig.name, 'root': actor.name,
    'clips': [{'name': 'sway', 'label': '흔들기', 'loop': True, 'samples': samples}]}), encoding='utf-8')
bake(manifest, directory / 'result')

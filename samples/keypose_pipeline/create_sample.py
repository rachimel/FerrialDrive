"""기본 도형 리그로 정지 키포즈 제작·재로딩 경로를 시연한다."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Tools/blender_pipeline'))
from keypose_pipeline import build


def create(directory):
    directory = Path(directory).resolve()
    if directory.exists():
        raise FileExistsError(directory)
    directory.mkdir(parents=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = bpy.data.objects.new('ActorRoot', None)
    bpy.context.scene.collection.objects.link(root)
    bpy.ops.object.armature_add()
    rig = bpy.context.object
    rig.name = 'SampleRig'
    rig.parent = root
    bpy.ops.object.mode_set(mode='EDIT')
    rig.data.edit_bones.remove(rig.data.edit_bones[0])
    specs = [('Pelvis', (0, 0, 1.54), (0, 0, 1.72), None),
             ('Waist', (0, 0, 1.77), (0, 0, 1.90), 'Pelvis'),
             ('Chest', (0, 0, 1.90), (0, 0, 2.50), 'Waist')]
    for side, sign in [('L', 1), ('R', -1)]:
        specs.extend([(f'Thigh.{side}', (0, sign*.26, 1.54), (-.02, sign*.28, .96), 'Pelvis'),
                      (f'Shin.{side}', (-.02, sign*.28, .96), (0, sign*.32, .15), f'Thigh.{side}'),
                      (f'Foot.{side}', (0, sign*.32, .15), (.31, sign*.32, .10), f'Shin.{side}'),
                      (f'UpperArm.{side}', (0, sign*.52, 2.49), (.03, sign*.78, 2.16), 'Chest'),
                      (f'Forearm.{side}', (.03, sign*.78, 2.16), (.02, sign*.96, 1.87), f'UpperArm.{side}'),
                      (f'Hand.{side}', (.02, sign*.96, 1.87), (.02, sign*1.11, 1.62), f'Forearm.{side}')])
    for name, head, tail, parent in specs:
        bone = rig.data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        if parent:
            bone.parent = rig.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    for name, head, tail, _ in specs:
        a, b = Vector(head), Vector(tail)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(a+b)/2)
        obj = bpy.context.object
        obj.name = 'Sample_'+name
        obj.scale = (.12, .12, (b-a).length*.8)
        obj.rotation_euler = (b-a).to_track_quat('Z', 'Y').to_euler()
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        obj.parent = root
        group = obj.vertex_groups.new(name=name)
        group.add(list(range(len(obj.data.vertices))), 1, 'REPLACE')
        obj.modifiers.new('Rig', 'ARMATURE').object = rig
    control = bpy.data.objects.new('SampleControl', None)
    bpy.context.scene.collection.objects.link(control)
    control.parent = root
    control['sword_stowed'] = control['gun_stowed'] = 1
    source = directory/'source.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    config = {'asset_id': 'sample_keyposes', 'source': str(source),
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'rig': rig.name, 'root': root.name, 'control': control.name, 'weapons': {},
              'poses': [{'id': 'stand', 'label': '기본 지지 자세', 'parameters': {'pelvis': [0, 0, -.08]}},
                        {'id': 'step', 'label': '한쪽 발 통과 자세', 'parameters': {'pelvis': [0, 0, -.12], 'foot_R': [0, 0, .12]}}],
              'groups': [{'id': 'sample', 'label': '기본 도형 자세', 'poses': ['stand', 'step']}]}
    request = directory/'request.json'
    request.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    build(request, directory/'keyposes')
    print('SAMPLE_KEYPOSES_COMPLETE')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    create(args.output)

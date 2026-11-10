"""에셋별 포즈 표본 JSON을 기존 프레임 기반 출력 툴용 장면으로 굽는다."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


def validate(data):
    if data['version'] != 1 or not isinstance(data['fps'], int) or not 1 <= data['fps'] <= 240:
        raise ValueError('지원하지 않는 버전 또는 FPS')
    names = set()
    occupied = set()
    for clip in data['clips']:
        if not clip['name'] or clip['name'] in names or any(c in clip['name'] for c in '/\\'):
            raise ValueError('동작 이름은 고유해야 한다.')
        names.add(clip['name'])
        if not clip['samples']:
            raise ValueError('빈 동작')
        frames = [sample['frame'] for sample in clip['samples']]
        if frames != sorted(frames):
            raise ValueError('표본은 재생 순서로 작성한다.')
        for event in clip.get('events', []):
            if type(event['frame']) is not int or not 0 <= event['frame'] < len(frames):
                raise ValueError('이벤트는 동작 안의 0 기반 표본 번호여야 한다.')
        for sample in clip['samples']:
            frame = sample['frame']
            if type(frame) is not int or frame < 1 or frame in occupied:
                raise ValueError('프레임 중복 또는 잘못된 프레임')
            occupied.add(frame)
            for rows in [*sample['bones'].values(), *sample.get('objects', {}).values()]:
                if len(rows) != 4 or any(len(row) != 4 for row in rows) or not all(math.isfinite(v) for row in rows for v in row):
                    raise ValueError('유효한 4x4 행렬이 필요하다.')
    return data


def curves(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves


def bake(manifest, destination):
    import bpy
    from mathutils import Matrix
    manifest, destination = Path(manifest).resolve(), Path(destination).resolve()
    data = validate(json.loads(manifest.read_text(encoding='utf-8')))
    source = (manifest.parent / data['source']).resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != data['source_sha256']:
        raise ValueError('원본 해시 불일치')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_review import require_stage_approval
    require_stage_approval(source)
    if destination.exists():
        raise FileExistsError('새 출력 폴더가 필요하다.')
    bpy.ops.wm.open_mainfile(filepath=str(source))
    if data.get('setup_operations'):
        from model_operations import apply_operations
        apply_operations(data['setup_operations'])
    rig = bpy.data.objects[data['rig']]
    animated = {rig.name}
    keyed_paths = {rig.name: set()}
    transform_channels = ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale')
    for clip in data['clips']:
        for sample in clip['samples']:
            animated.update(sample.get('objects', {}))
            animated.update(sample.get('properties', {}))
            for bone_name in sample['bones']:
                bone = rig.pose.bones[bone_name]
                keyed_paths[rig.name].update(bone.path_from_id(channel) for channel in transform_channels)
            for name in sample.get('objects', {}):
                keyed_paths.setdefault(name, set()).update(transform_channels)
    for name in animated:
        obj = bpy.data.objects[name]
        if obj.animation_data:
            obj.animation_data.action = None
            for track in obj.animation_data.nla_tracks:
                track.mute = True
            # 이미 표본에 포함한 변환을 출력 사본의 드라이버로 다시 적용하지 않는다.
            for driver in obj.animation_data.drivers:
                if driver.data_path in keyed_paths.get(name, ()):
                    driver.mute = True
    scene = bpy.context.scene
    scene.render.fps = data['fps']
    scene.render.fps_base = 1
    scene.timeline_markers.clear()
    for clip in data['clips']:
        scene.timeline_markers.new(clip['name'], frame=clip['samples'][0]['frame'])
        for sample in clip['samples']:
            frame = sample['frame']
            for name, rows in sample['bones'].items():
                bone = rig.pose.bones[name]
                bone.rotation_mode = 'QUATERNION'
                bone.matrix_basis = Matrix(rows)
                for channel in ('location', 'rotation_quaternion', 'scale'):
                    bone.keyframe_insert(channel, frame=frame, group=name)
            for name, rows in sample.get('objects', {}).items():
                obj = bpy.data.objects[name]
                obj.rotation_mode = 'QUATERNION'
                obj.matrix_basis = Matrix(rows)
                for channel in ('location', 'rotation_quaternion', 'scale'):
                    obj.keyframe_insert(channel, frame=frame)
            for name, values in sample.get('properties', {}).items():
                obj = bpy.data.objects[name]
                for key, value in values.items():
                    obj[key] = value
                    obj.keyframe_insert(f'["{key}"]', frame=frame)
    for name in animated:
        action = bpy.data.objects[name].animation_data.action
        action.name = data['asset_id'] + '_' + name
        for curve in curves(action):
            for point in curve.keyframe_points:
                point.interpolation = 'CONSTANT'
    scene.frame_start = min(s['frame'] for c in data['clips'] for s in c['samples'])
    scene.frame_end = max(s['frame'] for c in data['clips'] for s in c['samples'])
    scene.frame_set(scene.frame_start)
    destination.mkdir(parents=True)
    output = destination / 'animations.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    bpy.ops.wm.open_mainfile(filepath=str(output))
    rig = bpy.data.objects[data['rig']]
    maximum = 0
    for clip in data['clips']:
        for sample in clip['samples']:
            scene = bpy.context.scene
            scene.frame_set(sample['frame'])
            for name, rows in sample['bones'].items():
                matrix = rig.pose.bones[name].matrix_basis
                maximum = max(maximum, max(abs(matrix[i][j]-rows[i][j]) for i in range(4) for j in range(4)))
            for name, rows in sample.get('objects', {}).items():
                matrix = bpy.data.objects[name].matrix_basis
                maximum = max(maximum, max(abs(matrix[i][j]-rows[i][j]) for i in range(4) for j in range(4)))
            for name, values in sample.get('properties', {}).items():
                for key, value in values.items():
                    if abs(bpy.data.objects[name][key]-value) > 1e-6:
                        raise ValueError('장착 상태 재로딩 불일치')
    if maximum > 1e-4:
        raise ValueError(f'포즈 재로딩 불일치: {maximum}')
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from Tools.asset_loader.production import render_config
    configs = destination / 'export_configs'
    configs.mkdir()
    index = []
    render_settings = data.get('render_settings', {})
    for clip in data['clips']:
        frames = [s['frame'] for s in clip['samples']]
        config = render_config(asset_id=data['asset_id'], animation_name=clip['name'], frames=','.join(map(str, frames)),
                               fps=data['fps'], width=192, height=192, ortho_scale=render_settings.get('ortho_scale', 5.8), samples=16,
                               root_object=data['root'], auto_fit=False)
        config['camera'].update(position=[0,-8,6], target=render_settings.get('camera_target', [0,0,1.5]))
        config['source_blend'] = '../animations.blend'
        (configs / (clip['name']+'.json')).write_text(json.dumps(config, indent=2), encoding='utf-8')
        events = [dict(event, frame=frames[event['frame']], clip_frame=event['frame']) for event in clip.get('events', [])]
        index.append({k:v for k,v in clip.items() if k != 'samples'} | {'events': events, 'frames':frames,'fps':data['fps'],'render_config':'export_configs/'+clip['name']+'.json'})
    report = {'version':1,'source':str(source),'source_sha256':data['source_sha256'],'blend':'animations.blend',
              'clips':index,'max_reload_error':maximum,'visual_approval':False,'game_exported':False,
              'source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==data['source_sha256']}
    (destination/'clips.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'clips':len(index),'reload_error':maximum,'output':str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    bake(args.manifest, args.output)

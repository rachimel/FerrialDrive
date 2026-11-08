"""JSON 공통 연산으로 모델 후보를 제작한다. 품질 검사는 별도 파일에서 실행한다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def review(config, directory):
    import bpy
    from mathutils import Vector
    scene = bpy.context.scene
    root = bpy.data.objects[config['root_object']]
    candidates = ([bpy.data.objects[name] for name in config['objects']] if config.get('objects')
                  else [root, *root.children_recursive])
    meshes = [o for o in candidates if o.type == 'MESH' and not o.hide_render]
    points = []
    for obj in meshes:
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        points.extend(evaluated.matrix_world @ Vector(c) for c in evaluated.bound_box)
    if not points:
        raise ValueError('검토할 메시가 없다.')
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    center = (low + high) / 2
    radius = max((p - center).length for p in points)
    if radius <= 0:
        raise ValueError('검토 범위가 0이다.')
    # 후보 파일 저장/재로딩 뒤의 일회용 장면만 바꾼다.
    for obj in scene.objects:
        if obj.type == 'LIGHT' or (obj.type == 'MESH' and obj not in meshes):
            obj.hide_render = True
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = config.get('samples', 16)
    scene.cycles.use_denoising = True
    scene.render.film_transparent = True
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.view_settings.view_transform = 'AgX'
    if not scene.world:
        scene.world = bpy.data.worlds.new('ReviewWorld')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .25
    for direction, power in (((3, -4, 5), 500), ((-3, 2, 4), 350)):
        bpy.ops.object.light_add(type='AREA', location=center + Vector(direction).normalized() * radius * 3)
        light = bpy.context.object
        light.data.energy = power * radius * radius
        light.data.size = radius * 2
        light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    scene.camera = camera
    output = []
    for name, direction in config.get('views', [('front', (1, 0, .25)), ('rear', (-1, 0, .25)), ('oblique', (1, -1, .5))]):
        camera.location = center + Vector(direction).normalized() * radius * 4
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        for label, size in [('detail', config.get('detail_size', 640)), ('game', config.get('game_size', 192))]:
            camera.data.ortho_scale = radius * 2.2
            scene.render.resolution_x = scene.render.resolution_y = size
            path = directory / f'{name}_{label}.png'
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            output.append(path.name)
    return output


def build(manifest, output):
    import bpy
    from model_snapshot import fingerprint
    from model_operations import apply_operations
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    config = json.loads(manifest.read_text(encoding='utf-8'))
    if config.get('schema_version') != 1 or not config.get('asset_id'):
        raise ValueError('schema_version=1 및 asset_id가 필요하다.')
    if output.exists():
        raise FileExistsError('새 출력 폴더를 사용한다. 기존 작업은 덮어쓰지 않는다.')
    def path(value):
        return (manifest.parent / value).resolve()
    source = path(config['source']) if config.get('source') else None
    if source and sha256(source) != config.get('source_sha256'):
        raise ValueError('기준 파일 해시가 다르다. 기준 버전을 확인한다.')
    if 'recipe' in config:
        raise ValueError('버전별 Python recipe 대신 operations JSON을 사용한다.')
    if not isinstance(config.get('operations'), list):
        raise ValueError('operations 배열이 필요하다. 검사/복사용 후보는 빈 배열을 사용한다.')
    output.mkdir(parents=True)
    report = {'schema_version': 1, 'asset_id': config['asset_id'], 'status': 'failed',
              'source_sha256': sha256(source) if source else None,
              'manifest_sha256': sha256(manifest), 'blender_version': bpy.app.version_string,
              'visual_approval': False, 'game_exported': False, 'quality_checks_run': False,
              'scope_check_excludes': ['modifier settings', 'material node contents', 'driver expressions', 'actions']}
    report['tool_hashes'] = {name: sha256(Path(__file__).with_name(name)) for name in
                            ('model_pipeline.py', 'model_operations.py', 'model_primitives.py',
                             'model_geometry.py', 'model_snapshot.py')}
    (output / 'request.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        if source:
            bpy.ops.wm.open_mainfile(filepath=str(source))
        else:
            bpy.ops.wm.read_factory_settings(use_empty=True)
        before = {o.name: fingerprint(o) for o in bpy.data.objects}
        for operation in config['operations']:
            target = operation.get('object')
            if target in before and target not in config.get('change_objects', []):
                raise ValueError(f'선언한 수정 범위 밖의 대상: {target}')
        apply_operations(config['operations'])
        bpy.context.view_layer.update()
        after = {o.name: fingerprint(o) for o in bpy.data.objects}
        changed = sorted(n for n in before if before[n] != after.get(n))
        added = sorted(set(after) - set(before))
        report.update(changed_objects=changed, added_objects=added)
        unexpected = set(changed) - set(config.get('change_objects', []))
        if unexpected or (added and not config.get('allow_additions', False)):
            raise ValueError(f'선언한 수정 범위 밖의 변경: {sorted(unexpected)}; additions={added}')
        candidate = output / 'candidate.blend'
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(candidate))
        bpy.ops.wm.open_mainfile(filepath=str(candidate))
        loaded = {o.name: fingerprint(o) for o in bpy.data.objects}
        if loaded != after:
            raise ValueError('저장/재로딩 뒤 구조가 달라졌다.')
        report['candidate_sha256'] = sha256(candidate)
        if config.get('review'):
            report['previews'] = review(config['review'], output)
        report['status'] = 'candidate_unchecked'
        return report
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        if source:
            report['source_unchanged'] = sha256(source) == report['source_sha256']
            if not report['source_unchanged']:
                report['status'] = 'failed'
                report['error'] = '기준 파일 해시가 변경됐다. 원본 보존을 확인한다.'
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if report.get('source_unchanged') is False:
            raise RuntimeError(report['error'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    print(json.dumps(build(args.manifest, args.output), ensure_ascii=True))


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()

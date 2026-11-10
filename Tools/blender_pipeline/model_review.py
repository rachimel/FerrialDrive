"""고정 구도의 중간 렌더와 AI 검토·사용자 확인을 각각 기록한다."""
import argparse
import hashlib
import json
import math
from pathlib import Path


DEFAULT_VIEWS = [('front', (1, 0, 0)), ('rear', (-1, 0, 0)),
                 ('left', (0, 1, 0)), ('right', (0, -1, 0)),
                 ('top', (0, 0, 1)), ('bottom', (0, 0, -1))]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def review_meshes(config):
    import bpy
    root = bpy.data.objects[config['root_object']]
    candidates = ([bpy.data.objects[name] for name in config['objects']] if config.get('objects')
                  else [root, *root.children_recursive])
    meshes = [obj for obj in candidates if obj.type == 'MESH' and not obj.hide_render]
    if not meshes:
        raise ValueError('검토할 메시가 없다.')
    return meshes


def capture_fixture(config):
    """수정 전 장면에서 프레임·구도·배율을 고정한다. 후보에 다시 맞추지 않는다."""
    import bpy
    from mathutils import Vector
    scene = bpy.context.scene
    original_frame = scene.frame_current
    frames = config.get('frames', [original_frame])
    if not frames or any(type(frame) is not int for frame in frames):
        raise ValueError('검토 프레임은 비어 있지 않은 정수 배열이어야 한다.')
    points = []
    frame_bounds = {}
    try:
        for frame in frames:
            scene.frame_set(frame)
            frame_points = []
            for obj in review_meshes(config):
                evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
                frame_points.extend(evaluated.matrix_world @ Vector(c) for c in evaluated.bound_box)
            points.extend(frame_points)
            if config.get('per_frame_framing'):
                low = Vector([min(p[i] for p in frame_points) for i in range(3)])
                high = Vector([max(p[i] for p in frame_points) for i in range(3)])
                center = (low+high)/2
                frame_bounds[str(frame)] = {'center': list(center), 'radius': max((p-center).length for p in frame_points)}
    finally:
        scene.frame_set(original_frame)
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    center = (low + high) / 2
    radius = max((point - center).length for point in points)
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError('검토 범위가 유효하지 않다.')
    views = config.get('views', DEFAULT_VIEWS)
    if not views or len({name for name, _ in views}) != len(views):
        raise ValueError('검토 방향 이름은 비어 있지 않고 고유해야 한다.')
    for name, direction in views:
        if not name or any(c in name for c in '/\\') or len(direction) != 3:
            raise ValueError('잘못된 검토 방향이다.')
        if not all(math.isfinite(v) for v in direction) or Vector(direction).length < 1e-8:
            raise ValueError('검토 방향은 유한한 비영 벡터여야 한다.')
    sizes = {'detail': config.get('detail_size', 640), 'game': config.get('game_size', 240)}
    if any(type(size) is not int or size < 1 for size in sizes.values()):
        raise ValueError('검토 크기는 양의 정수여야 한다.')
    return {'center': list(center), 'radius': radius, 'frames': frames, 'views': views,
            'sizes': sizes, 'samples': config.get('samples', 16), 'seed': 0,
            'view_transform': 'AgX', 'exposure': 0.0, 'gamma': 1.0,
            'engine': config.get('engine', 'CYCLES'), 'frame_bounds': frame_bounds,
            'disable_bevel': config.get('disable_bevel', False),
            'lights': [{'direction': direction, 'power': power} for direction, power in
                       [([3, -4, 5], 500), ([-3, 2, 4], 350), ([1, 2, -4], 250)]]}


def render_review(config, directory, fixture=None):
    import bpy
    from mathutils import Vector
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fixture = fixture or capture_fixture(config)
    scene = bpy.context.scene
    center, radius = Vector(fixture['center']), fixture['radius']
    meshes = review_meshes(config)
    for obj in scene.objects:
        if obj.type == 'LIGHT' or (obj.type == 'MESH' and obj not in meshes):
            obj.hide_render = True
    scene.render.engine = fixture.get('engine', 'CYCLES')
    if scene.render.engine == 'CYCLES':
        scene.cycles.samples = fixture['samples']
        scene.cycles.seed = fixture['seed']
        scene.cycles.use_animated_seed = False
        scene.cycles.use_denoising = True
    elif scene.render.engine == 'BLENDER_WORKBENCH':
        scene.display.shading.light = 'STUDIO'
        scene.display.shading.color_type = 'MATERIAL'
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
        scene.display.shading.cavity_type = 'BOTH'
        scene.display.render_aa = '8'
    else:
        raise ValueError('검토 렌더는 CYCLES 또는 BLENDER_WORKBENCH를 사용한다.')
    if fixture.get('disable_bevel'):
        for obj in meshes:
            for modifier in obj.modifiers:
                if modifier.type == 'BEVEL':
                    modifier.show_render = False
    scene.render.film_transparent = True
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.view_settings.view_transform = fixture['view_transform']
    scene.view_settings.exposure = fixture['exposure']
    scene.view_settings.gamma = fixture['gamma']
    # 원본 World의 노드 연결이 조명을 바꾸지 않도록 검토 전용 World를 쓴다.
    scene.world = bpy.data.worlds.new('PipelineReviewWorld')
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes['Background']
    background.inputs['Color'].default_value = (.35, .35, .35, 1)
    background.inputs['Strength'].default_value = .25
    for light_config in fixture['lights']:
        direction, power = light_config['direction'], light_config['power']
        bpy.ops.object.light_add(type='AREA', location=center + Vector(direction).normalized() * radius * 3)
        light = bpy.context.object
        light.data.energy = power * radius * radius
        light.data.size = radius * 2
        light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = radius * 2.2
    scene.camera = camera
    evidence = []
    for frame in fixture['frames']:
        scene.frame_set(frame)
        bounds = fixture.get('frame_bounds', {}).get(str(frame))
        if bounds:
            center, radius = Vector(bounds['center']), bounds['radius']
            camera.data.ortho_scale = radius*2.2
        for name, direction in fixture['views']:
            camera.location = center + Vector(direction).normalized() * radius * 4
            camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
            for label, size in fixture['sizes'].items():
                scene.render.resolution_x = scene.render.resolution_y = size
                suffix = f'_f{frame}' if len(fixture['frames']) > 1 else ''
                path = directory / f'{name}{suffix}_{label}.png'
                scene.render.filepath = str(path)
                bpy.ops.render.render(write_still=True)
                evidence.append({'file': path.name, 'sha256': digest(path),
                                 'view': name, 'frame': frame, 'size': size, 'scale': label})
    return evidence


def write_pending_review(directory, intent, evidence, candidate_sha256, fixture):
    path = Path(directory) / 'visual_review.json'
    payload = {'status': 'awaiting_ai_review', 'intent': intent,
               'candidate_sha256': candidate_sha256, 'fixture_sha256': json_digest(fixture),
               'evidence': evidence, 'evidence_digest': json_digest(evidence),
               'ai_review': None, 'user_decision': None, 'stage_approval': False}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload['status']


def verify_evidence(directory, review):
    directory = Path(directory).resolve()
    if digest(directory / 'candidate.blend') != review['candidate_sha256']:
        raise ValueError('검토 이후 후보가 바뀌었다. 이미지를 다시 확인한다.')
    if json_digest(review['evidence']) != review['evidence_digest']:
        raise ValueError('검토 이미지 목록이 바뀌었다.')
    for item in review['evidence']:
        path = (directory / item['file']).resolve()
        if not path.is_relative_to(directory) or digest(path) != item['sha256']:
            raise ValueError('검토 이미지가 변경됐거나 범위를 벗어났다.')


def require_stage_approval(source, *, revision=False):
    """중간 검토가 붙은 후보로 다음 작업을 시작할 때 실제 OK를 확인한다."""
    source = Path(source).resolve()
    path = source.parent / 'visual_review.json'
    if not path.exists():
        return
    review = json.loads(path.read_text(encoding='utf-8'))
    verify_evidence(source.parent, review)
    if digest(source) != review['candidate_sha256']:
        raise ValueError('중간 검토가 다른 후보에 연결돼 있다.')
    if revision and review['status'] in ('needs_revision', 'uncertain'):
        return
    if review['status'] != 'approved_for_next_stage' or not review.get('stage_approval'):
        raise ValueError('중간 이미지를 제시하고 사용자의 OK를 받은 뒤 다음 단계로 진행한다.')


def record_ai_review(directory, assessment):
    """실제로 이미지를 읽은 AI의 판단을 받는다. 픽셀 차이로 품질을 자동 판정하지 않는다."""
    directory = Path(directory)
    path = directory / 'visual_review.json'
    review = json.loads(path.read_text(encoding='utf-8'))
    verify_evidence(directory, review)
    if review['user_decision'] is not None:
        raise ValueError('사용자 판단이 있는 후보는 새 후보에서 검토한다.')
    if any(assessment.get(key) != review[key] for key in ('candidate_sha256', 'evidence_digest')):
        raise ValueError('판단 대상 후보 또는 이미지가 일치하지 않는다.')
    criteria = review['intent'].get('criteria', [])
    if not review['intent'].get('goal') or not criteria or not review['intent'].get('preserve'):
        raise ValueError('AI가 요청에서 목표·확인 항목·보존 대상을 정리해야 한다.')
    ids = [item['id'] for item in criteria]
    checks = assessment.get('checks', [])
    if len(ids) != len(set(ids)) or sorted(item['criterion'] for item in checks) != sorted(ids):
        raise ValueError('모든 확인 항목을 한 번씩 판단해야 한다.')
    known = {item['file'] for item in review['evidence']}
    observations = [*checks, assessment.get('preservation', {})]
    for item in observations:
        if item.get('verdict') not in ('met', 'unmet', 'uncertain') or not item.get('observation', '').strip():
            raise ValueError('판정과 실제 이미지에서 관찰한 근거가 필요하다.')
        if not item.get('images') or not set(item['images']) <= known:
            raise ValueError('관찰한 이미지 파일을 지정해야 한다.')
        kinds = {entry['kind'] for entry in review['evidence'] if entry['file'] in item['images']}
        if kinds != {entry['kind'] for entry in review['evidence']}:
            raise ValueError('비교 판단에는 수정 전후 이미지가 모두 필요하다.')
    if set(assessment.get('inspected_images', [])) != known:
        raise ValueError('6면과 실제 표시 크기를 포함해 제공된 모든 이미지를 검토해야 한다.')
    if not assessment.get('next_action', '').strip():
        raise ValueError('다음 수정 또는 사용자에게 확인할 내용을 기록한다.')
    verdicts = [item['verdict'] for item in observations]
    review['status'] = ('needs_revision' if 'unmet' in verdicts else
                        'uncertain' if 'uncertain' in verdicts else 'awaiting_user')
    review['ai_review'] = assessment
    save_review(directory, review)
    return review['status']


def record_user_decision(directory, decision, statement):
    directory = Path(directory)
    path = directory / 'visual_review.json'
    review = json.loads(path.read_text(encoding='utf-8'))
    verify_evidence(directory, review)
    if review['status'] != 'awaiting_user' or not statement.strip():
        raise ValueError('AI 검토 통과 후 사용자의 실제 응답을 기록한다.')
    if decision not in ('ok', 'revise'):
        raise ValueError('사용자 판단은 ok 또는 revise다.')
    review['user_decision'] = {'decision': decision, 'statement': statement}
    review['status'] = 'approved_for_next_stage' if decision == 'ok' else 'needs_revision'
    review['stage_approval'] = decision == 'ok'
    save_review(directory, review)
    return review['status']


def save_review(directory, review):
    directory = Path(directory)
    report_path = directory / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report['candidate_sha256'] != review['candidate_sha256']:
        raise ValueError('제작 보고서의 후보가 다르다.')
    report['review_checkpoint'] = review['status']
    (directory / 'visual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--ai-review', type=Path)
    choice.add_argument('--user-decision', choices=('ok', 'revise'))
    parser.add_argument('--statement', default='')
    args = parser.parse_args()
    if args.ai_review:
        status = record_ai_review(args.directory, json.loads(args.ai_review.read_text(encoding='utf-8')))
    else:
        status = record_user_decision(args.directory, args.user_decision, args.statement)
    print(json.dumps({'status': status}, ensure_ascii=False))


if __name__ == '__main__':
    main()

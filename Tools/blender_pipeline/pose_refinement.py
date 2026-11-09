"""기존 포즈 표본의 팔 방향과 말단 관절 회전을 함께 보정한다."""
import math


def repair_arm(rig, upper_name, lower_name, swivel_name, hand_name,
               target, max_swing_degrees=55.0, allow_shift=True):
    """파지 회전을 유지하며 손목 굽힘을 줄인다. 도달 보정량을 반환한다."""
    import bpy
    from mathutils import Matrix, Vector
    from model_operations import apply_operations

    upper, lower, swivel, hand = [rig.pose.bones[n] for n in
                                  (upper_name, lower_name, swivel_name, hand_name)]
    shoulder = rig.matrix_world @ upper.head
    la = (rig.matrix_world.to_3x3() @ (upper.tail-upper.head)).length
    lb = (rig.matrix_world.to_3x3() @ (lower.tail-lower.head)).length
    # 손과 전완의 rest 축 차이를 제거한 목표 전완 방향.
    rest_link = lower.bone.matrix_local.inverted() @ hand.bone.matrix_local
    desired_lower = target.to_quaternion() @ rest_link.to_quaternion().inverted()
    direction = desired_lower @ Vector((0, 1, 0))
    original = target.translation.copy()
    preferred_elbow = original - direction * lb - shoulder
    if preferred_elbow.length < 1e-6:
        preferred_elbow = Vector((0, 1, -1))
    straight_target = shoulder + preferred_elbow.normalized() * la + direction * lb

    def solve(point):
        delta = point - shoulder
        distance = max(abs(la-lb)+.005, min(la+lb-.005, delta.length))
        axis = delta.normalized()
        point = shoulder + axis * distance
        along = (la*la-lb*lb+distance*distance)/(2*distance)
        pole = -direction + axis * direction.dot(axis)
        if pole.length < 1e-5:
            pole = rig.matrix_world @ lower.head - shoulder
            pole -= axis * pole.dot(axis)
        if pole.length < 1e-5:
            pole = axis.cross(Vector((1, 0, 0)))
        elbow = shoulder + axis*along + pole.normalized()*math.sqrt(max(0, la*la-along*along))
        forearm = (point-elbow).normalized()
        return point, elbow, forearm, math.degrees(forearm.angle(direction))

    point, elbow, forearm, swing = solve(original)
    if allow_shift and swing > max_swing_degrees:
        lo, hi = 0.0, 1.0
        for _ in range(18):
            t = (lo+hi)/2
            candidate = solve(original.lerp(straight_target, t))
            if candidate[3] > max_swing_degrees:
                lo = t
            else:
                hi = t
        point, elbow, forearm, swing = solve(original.lerp(straight_target, hi))
    apply_operations([dict(op='aim_bone', object=rig.name, bone=upper.name,
                           world_direction=list(elbow-shoulder))])
    bpy.context.view_layer.update()
    # 전완의 회전축을 먼저 정렬해서 손에 뒤틀림을 떠넘기지 않는다.
    lower_rotation = direction.rotation_difference(forearm) @ desired_lower
    scale = (rig.matrix_world @ lower.matrix).to_scale()
    lower.matrix = rig.matrix_world.inverted() @ Matrix.LocRotScale(elbow, lower_rotation, scale)
    swivel.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    actual = rig.matrix_world @ hand.matrix
    hand.matrix = rig.matrix_world.inverted() @ Matrix.LocRotScale(actual.translation, target.to_quaternion(), actual.to_scale())
    bpy.context.view_layer.update()
    return {'shift': (point-original).length,
            'swing_degrees': swing,
            'endpoint_error': (rig.matrix_world@hand.head-point).length}


def refine_manifest(manifest_path, settings_path, output_path):
    """포즈 수정 수치·프레임 유지표는 별도 JSON에서 받는다."""
    import copy
    import json
    from pathlib import Path
    import bpy
    from mathutils import Matrix, Vector
    from model_operations import apply_operations
    from animation_pipeline import validate

    data = validate(json.loads(Path(manifest_path).read_text(encoding='utf-8')))
    cfg = json.loads(Path(settings_path).read_text(encoding='utf-8'))
    target_path = Path(output_path)
    if target_path.exists():
        raise FileExistsError(target_path)
    bpy.ops.wm.open_mainfile(filepath=cfg['scene'])
    rig = bpy.data.objects[data['rig']]
    for obj in bpy.data.objects:
        if obj.animation_data:
            obj.animation_data.action = None
            for track in obj.animation_data.nla_tracks:
                track.mute = True
    # 계산 중 메시 평가만 잠시 끈다. 저장은 원본을 다시 여는 bake가 담당한다.
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            obj.hide_viewport = True
            for mod in obj.modifiers:
                mod.show_viewport = False
    matrix_rows = lambda m: [list(row) for row in m]
    mount_basis = {item['object']: bpy.data.objects[item['object']].matrix_basis.copy()
                   for item in cfg.get('mounts', [])}
    report = []
    result = copy.deepcopy(data)
    result['fps'] = cfg['fps']
    result['asset_id'] = cfg['asset_id']
    result['clips'] = []
    frame = 1
    for clip in data['clips']:
        settings = cfg['clips'][clip['name']]
        corrected = []
        for index, sample in enumerate(clip['samples']):
            for name, rows in sample['bones'].items():
                rig.pose.bones[name].matrix_basis = Matrix(rows)
            for name, rows in sample.get('objects', {}).items():
                bpy.data.objects[name].matrix_basis = Matrix(rows)
            for name, values in sample.get('properties', {}).items():
                for key, value in values.items():
                    bpy.data.objects[name][key] = value
                bpy.data.objects[name].update_tag()
            bpy.context.view_layer.update()
            mount_delta = {}
            for mount in cfg.get('mounts', []):
                obj = bpy.data.objects[mount['object']]
                obj.matrix_basis = mount_basis[obj.name]
                bpy.context.view_layer.update()
                old_world = obj.matrix_world.copy()
                obj.matrix_basis = mount_basis[obj.name]@Matrix.Rotation(math.radians(mount['degrees']), 4, mount['axis'])
                bpy.context.view_layer.update()
                mount_delta[mount['hand']] = obj.matrix_world@old_world.inverted()
            # 원래 접지 프레임은 보존하고 이동 폭·공중 높이만 확대한다.
            feet = {leg['end']: rig.matrix_world@rig.pose.bones[leg['end']].matrix for leg in cfg['legs']}
            for bone_name, angle in settings.get('tilt', {}).items():
                bone = rig.pose.bones[bone_name]
                world = rig.matrix_world@bone.matrix
                bone.matrix = rig.matrix_world.inverted()@Matrix.Translation(world.translation)@Matrix.Rotation(math.radians(angle), 4, 'Y')@Matrix.Translation(-world.translation)@world
                bpy.context.view_layer.update()
            for leg in cfg['legs']:
                foot = feet[leg['end']]
                foot.translation.x *= settings.get('stride', 1)
                foot.translation.z = leg['ground']+(foot.translation.z-leg['ground'])*settings.get('lift', 1)
                start = rig.matrix_world@rig.pose.bones[leg['upper']].head
                a, b = rig.pose.bones[leg['upper']], rig.pose.bones[leg['lower']]
                reach = (rig.matrix_world.to_3x3()@(a.tail-a.head)).length+(rig.matrix_world.to_3x3()@(b.tail-b.head)).length-.005
                delta = foot.translation-start
                if delta.length > reach:
                    foot.translation = start+delta.normalized()*reach
                apply_operations([dict(op='pose_limb', object=rig.name, upper=leg['upper'], lower=leg['lower'], end=leg['end'], target_world=list(foot.translation), bend_world=leg['pole'], end_rotation_world=list(foot.to_quaternion()))])
            for arm in cfg['arms']:
                hand = rig.pose.bones[arm['hand']]
                target = rig.matrix_world@hand.matrix
                weight = settings.get('mount_weights', {}).get(arm['hand'], [0]*len(clip['samples']))[index]
                if weight and arm['hand'] in mount_delta:
                    changed = mount_delta[arm['hand']]@target
                    loc, rot, scale = target.decompose()
                    cloc, crot, _ = changed.decompose()
                    target = Matrix.LocRotScale(loc.lerp(cloc, weight), rot.slerp(crot, weight), scale)
                free_indices = settings.get('free', {}).get(arm['hand'], [])
                free = free_indices == 'all' or index in free_indices
                if free:
                    # 손은 전완 축을 따라 쉬고, 달릴 때 팔 전체가 앞뒤로 움직인다.
                    phase = index*math.tau/len(clip['samples'])
                    target.translation.x += settings.get('arm_swing', 0)*math.cos(phase)*arm['swing_sign']
                    lower = rig.pose.bones[arm['lower']]
                    rest = lower.bone.matrix_local.inverted()@hand.bone.matrix_local
                    target = Matrix.LocRotScale(target.translation, (rig.matrix_world@lower.matrix).to_quaternion()@rest.to_quaternion(), target.to_scale())
                metric = repair_arm(rig, arm['upper'], arm['lower'], arm['swivel'], arm['hand'], target,
                                    settings.get('max_swing', 55), settings.get('allow_shift', True))
                if free:
                    rig.pose.bones[arm['swivel']].matrix_basis = Matrix.Identity(4)
                    hand.matrix_basis = Matrix.Identity(4)
                    bpy.context.view_layer.update()
                metric.update(clip=clip['name'], sample=index, hand=arm['hand'], free=free)
                report.append(metric)
            item = copy.deepcopy(sample)
            item['bones'] = {b.name: matrix_rows(b.matrix_basis) for b in rig.pose.bones}
            for name in mount_basis:
                item.setdefault('objects', {})[name] = matrix_rows(bpy.data.objects[name].matrix_basis)
            corrected.append(item)
        order = settings.get('order', list(range(len(corrected))))
        new_clip = {k: copy.deepcopy(v) for k, v in clip.items() if k not in ('samples', 'events')}
        new_clip['samples'] = []
        for index in order:
            item = copy.deepcopy(corrected[index])
            item['frame'] = frame
            frame += 1
            new_clip['samples'].append(item)
        new_clip['events'] = []
        for event in clip.get('events', []):
            if event['frame'] not in order:
                raise ValueError('이벤트 프레임을 삭제할 수 없다.')
            new_clip['events'].append(dict(event, frame=order.index(event['frame'])))
        result['clips'].append(new_clip)
        frame += 2
    validate(result)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    target_path.with_name('refinement_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return {'clips': len(result['clips']), 'samples': sum(len(c['samples']) for c in result['clips']),
            'max_swing': max(r['swing_degrees'] for r in report),
            'max_shift': max(r['shift'] for r in report),
            'max_endpoint_error': max(r['endpoint_error'] for r in report)}

"""저장된 키포즈의 구조·관절 연결·발 접지를 독립 확인한다."""

import hashlib
import json
from pathlib import Path
import sys


def check(config):
    import bpy
    from mathutils import Vector
    from model_snapshot import fingerprint
    candidate = Path(bpy.data.filepath)
    source = Path(config['baseline'])
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != config['baseline_sha256']:
        raise ValueError('기준 파일 해시 불일치')
    bpy.ops.wm.open_mainfile(filepath=str(source))
    baseline = {o.name: fingerprint(o) for o in bpy.data.objects if o.type == 'MESH'}
    rig = bpy.data.objects[config['rig']]
    rest = {b.name: [list(row) for row in b.matrix_local] for b in rig.data.bones}
    constraints = {b.name: [(c.name, c.type, c.mute, c.influence) for c in b.constraints] for b in rig.pose.bones}
    weights = {o.name: {o.vertex_groups[g.group].name for v in o.data.vertices for g in v.groups if g.weight > .001}
               for o in bpy.data.objects if o.type == 'MESH' and not o.hide_render}
    foot_objects = {s: [name for name, groups in weights.items() if groups == {'Foot.'+s}] for s in ('L', 'R')}

    def foot_floor(names):
        points = []
        graph = bpy.context.evaluated_depsgraph_get()
        for name in names:
            obj = bpy.data.objects[name].evaluated_get(graph)
            mesh = obj.to_mesh()
            try:
                points.extend((obj.matrix_world @ v.co).z for v in mesh.vertices)
            finally:
                obj.to_mesh_clear()
        if not points:
            raise ValueError('발 접지 검사 대상이 없다.')
        return min(points)

    floors = {s: foot_floor(names) for s, names in foot_objects.items()}
    bpy.ops.wm.open_mainfile(filepath=str(candidate))
    loaded = {o.name: fingerprint(o) for o in bpy.data.objects if o.type == 'MESH'}
    rig = bpy.data.objects[config['rig']]
    errors, samples = [], []
    if baseline != loaded:
        errors.append('mesh_structure_changed')
    if rest != {b.name: [list(row) for row in b.matrix_local] for b in rig.data.bones}:
        errors.append('rest_bones_changed')
    actual_constraints = {b.name: [(c.name, c.type, c.mute, c.influence) for c in b.constraints] for b in rig.pose.bones}
    if constraints != actual_constraints:
        errors.append('bone_constraints_changed')
    for state in config['states']:
        bpy.context.scene.frame_set(state['frame'])
        maximum = max(((b.head-b.parent.tail).length for b in rig.pose.bones if b.parent and b.bone.use_connect), default=0)
        feet = {s: foot_floor(names)-floors[s] for s, names in foot_objects.items()}
        foot_error = max(abs(feet[s]-state.get('foot_lift', {}).get(s, 0)) for s in ('L', 'R'))
        samples.append({'pose': state['name'], 'frame': state['frame'], 'max_connected_gap_model_units': maximum,
                        'foot_lift_world_units': feet, 'foot_target_error_world_units': foot_error})
        if maximum > .0001:
            errors.append('connected_gap:'+state['name'])
        if foot_error > .001:
            errors.append('foot_target:'+state['name'])
    return {'errors': errors, 'samples': samples, 'pose_count': len(samples),
            'mesh_structure_preserved': baseline == loaded, 'rest_bones_preserved': not 'rest_bones_changed' in errors,
            'bone_constraints_preserved': constraints == actual_constraints,
            'angular_limits_checked': False,
            'not_tested': ['관절별 허용각', '전체 장갑 간섭', '연속 동작', '게임 연결', '사용자 외관 승인']}


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_check_io import main
    main(check)

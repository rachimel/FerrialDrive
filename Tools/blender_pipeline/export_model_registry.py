"""현재 모델의 객체·본·제어를 공통 디자인 모듈용 JSON으로 추출한다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def export(source, root_name, rig_name):
    import bpy
    bpy.ops.wm.open_mainfile(filepath=str(source))
    root, rig = bpy.data.objects[root_name], bpy.data.objects[rig_name]
    result = {'schema_version': 1, 'baseline': str(source), 'baseline_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'root': root_name, 'rig': rig_name, 'parts': {}, 'bones': {}, 'materials': {}, 'controls': {}, 'mounts': {}}
    def numeric_properties(obj):
        return {k: {'default': obj[k], 'ui': obj.id_properties_ui(k).as_dict()}
                for k in obj.keys() if isinstance(obj[k], (int, float)) and not isinstance(obj[k], bool)}
    for obj in sorted(root.children_recursive, key=lambda o: o.name):
        if obj.type == 'EMPTY' and numeric_properties(obj):
            result['mounts'][obj.name] = {'object': obj.name, 'controls': {k: v['ui'] for k, v in numeric_properties(obj).items()}}
        if obj.type != 'MESH' or not obj.data.vertices:
            continue
        weights = {obj.vertex_groups[g.group].name for v in obj.data.vertices for g in v.groups if g.weight > .001}
        name = 'helpers' if obj.hide_render else next(iter(weights)) if len(weights) == 1 else 'multi_bind' if weights else 'unbound'
        part = result['parts'].setdefault(name, {'objects': [], 'points': [], 'bindings': {}})
        part['objects'].append(obj.name)
        part['bindings'][obj.name] = sorted(weights)
        matrix = root.matrix_world.inverted() @ obj.matrix_world
        part['points'].extend(list(matrix @ v.co) for v in obj.data.vertices)
    for part in result['parts'].values():
        points = part.pop('points')
        part['bounds_min'] = [min(p[i] for p in points) for i in range(3)]
        part['bounds_max'] = [max(p[i] for p in points) for i in range(3)]
        part['pivot'] = [(a + b) / 2 for a, b in zip(part['bounds_min'], part['bounds_max'])]
        part['dimensions'] = [b - a for a, b in zip(part['bounds_min'], part['bounds_max'])]
    matrix = root.matrix_world.inverted() @ rig.matrix_world
    for bone in rig.data.bones:
        result['bones'][bone.name] = {'head': list(matrix @ bone.head_local), 'tail': list(matrix @ bone.tail_local),
                                    'parent': bone.parent.name if bone.parent else None, 'connected': bone.use_connect}
    for material in bpy.data.materials:
        result['materials'][material.name] = {'use_nodes': material.use_nodes}
    result['controls'] = numeric_properties(root)
    result['grouping'] = 'Visible meshes grouped by weighted bone; inspect multi_bind before editing.'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--root', required=True)
    parser.add_argument('--rig', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.output.exists():
        raise FileExistsError(args.output)
    result = export(args.source.resolve(), args.root, args.rig)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('REGISTRY_EXPORTED', len(result['parts']), len(result['bones']))

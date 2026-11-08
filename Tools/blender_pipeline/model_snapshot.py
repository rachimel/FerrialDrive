"""객체 구조 지문. 검사 실행과 별개인 데이터 보조 함수."""
import hashlib
import json
import math


def fingerprint(obj):
    """국소 수정 범위 확인용. Blender 데이터 전체의 동등성 증명은 아니다."""
    data = {'type': obj.type, 'parent': obj.parent.name if obj.parent else None,
            'parent_type': obj.parent_type, 'parent_vertices': list(obj.parent_vertices),
            'matrix_basis': [list(r) for r in obj.matrix_basis],
            'matrix_parent_inverse': [list(r) for r in obj.matrix_parent_inverse],
            'axis_angle': list(obj.rotation_axis_angle) if obj.rotation_mode == 'AXIS_ANGLE' else None,
            'hidden': obj.hide_render,
            'properties': {k: obj[k].to_list() if hasattr(obj[k], 'to_list') else
                           obj[k].to_dict() if hasattr(obj[k], 'to_dict') else str(obj[k])
                           for k in obj.keys() if k != '_RNA_UI'}}
    if obj.type == 'MESH':
        data.update(vertices=[list(v.co) for v in obj.data.vertices],
                    polygons=[(list(p.vertices), p.material_index, p.use_smooth) for p in obj.data.polygons],
                    uv={u.name: [list(l.uv) for l in u.data] for u in obj.data.uv_layers},
                    weights=[[(obj.vertex_groups[g.group].name, g.weight) for g in v.groups] for v in obj.data.vertices],
                    materials=[m.name if m else None for m in obj.data.materials],
                    keys={k.name: [list(v.co) for v in k.data] for k in obj.data.shape_keys.key_blocks}
                    if obj.data.shape_keys else {})
    if obj.type == 'ARMATURE':
        data['bones'] = [(b.name, b.parent.name if b.parent else None, [list(r) for r in b.matrix_local], b.length)
                         for b in obj.data.bones]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

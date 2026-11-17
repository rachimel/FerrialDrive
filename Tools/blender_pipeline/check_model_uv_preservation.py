"""원래 면의 UV와 절단 모서리의 보간 UV를 비교하는 독립 검사."""
import math


def snapshot(mesh, layer_name, coordinate_attribute=None):
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return None
    tags = mesh.attributes.get('FD_PartitionSourceFace')
    faces = []
    for face in mesh.polygons:
        corners = []
        for index in face.loop_indices:
            vertex_index = mesh.loops[index].vertex_index
            point = (mesh.attributes[coordinate_attribute].data[vertex_index].vector.copy()
                     if coordinate_attribute else mesh.vertices[vertex_index].co.copy())
            corners.append((index, point, layer.data[index].uv.copy()))
        faces.append({'source': tags.data[face.index].value if tags else face.index, 'corners': corners})
    return faces


def compare_snapshots(reference, target, tolerance):
    if reference is None or target is None:
        return {'errors': ['missing_uv_layer'], 'checked_corners': 0}
    errors, checked, caps, maximum = [], 0, 0, 0.0
    for face_index, face in enumerate(target):
        source_index = face['source']
        if source_index < 0:
            caps += 1
            continue
        if source_index >= len(reference):
            errors.append(f'unknown_source_face:{source_index}')
            continue
        corners = [(point, uv) for _, point, uv in reference[source_index]['corners']]
        for index, point, uv in face['corners']:
            nearest = None
            for (a, ua), (b, ub) in zip(corners, corners[1:] + corners[:1]):
                edge = b - a
                if edge.length_squared < 1e-20:
                    continue
                amount = min(1.0, max(0.0, (point - a).dot(edge) / edge.length_squared))
                distance = (point - a.lerp(b, amount)).length
                if nearest is None or distance < nearest[0]:
                    nearest = (distance, ua.lerp(ub, amount))
            if nearest is None or nearest[0] > tolerance * 10:
                errors.append(f'corner_outside_source_edges:{face_index}:{index}')
                continue
            error = (uv - nearest[1]).length
            maximum = max(maximum, error)
            checked += 1
            if not math.isfinite(error) or error > tolerance:
                errors.append(f'uv_changed:{face_index}:{index}')
    if not checked:
        errors.append('no_comparable_corners')
    return {'errors': errors, 'checked_corners': checked, 'new_cap_faces': caps,
            'maximum_uv_error': maximum}


def compare_mesh_uv(reference, target, layer_name, coordinate_attribute=None, tolerance=1e-6):
    return compare_snapshots(snapshot(reference, layer_name, coordinate_attribute),
                             snapshot(target, layer_name, coordinate_attribute), tolerance)


def check(config):
    import bpy
    import hashlib
    from pathlib import Path
    mappings = config.get('mappings', [])
    if not mappings:
        return {'errors': ['no_configured_mapping']}
    layer = config.get('uv_layer', 'UV_Paint')
    attribute = config.get('coordinate_attribute')
    targets = {row['target']: snapshot(bpy.data.objects[row['target']].data, layer, attribute) for row in mappings}
    source_names = sorted({row['reference'] for row in mappings})
    reference = Path(config['reference_source']).resolve()
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    if digest != config['reference_source_sha256']:
        raise ValueError('기준 파일 해시가 다르다.')
    bpy.ops.wm.open_mainfile(filepath=str(reference))
    bpy.context.scene.frame_set(config.get('reference_frame', 1))
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    sources = {name: snapshot(bpy.data.objects[name].evaluated_get(graph).data, layer, attribute)
               for name in source_names}
    rows, errors = {}, []
    for row in mappings:
        result = compare_snapshots(sources[row['reference']], targets[row['target']], config.get('tolerance', 1e-6))
        rows[row['target']] = result
        errors.extend(f"{row['target']}:{error}" for error in result['errors'])
    unchanged = hashlib.sha256(reference.read_bytes()).hexdigest() == digest
    if not unchanged:
        errors.append('reference_changed')
    return {'errors': errors, 'objects': rows, 'reference_sha256': digest, 'reference_unchanged': unchanged,
            'not_tested': ['원본 UV의 면적·중첩·패딩 품질', '새 절단면의 UV', '표면 색상 이관']}


if __name__ == '__main__':
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_check_io import main
    main(check)

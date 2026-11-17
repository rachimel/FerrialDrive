"""Blender 모델 수정에 사용하는 명시적 좌표·장착 보조 함수. import 부작용 없음."""
import math


def set_world_matrix_from_parent_frame(obj, desired_world):
    """VERTEX_3 등 평가된 부모 프레임을 보존하며 원하는 월드 변환을 적용한다.

    호출 전/후 view_layer.update()가 필요하다. 0도 AXIS_ANGLE의 축은
    행렬만으로 복원할 수 없으므로 축이 중요한 회전 조인트에는 사용하지 않는다.
    """
    if obj.rotation_mode == 'AXIS_ANGLE':
        raise ValueError('Axis Angle 조인트는 명시한 로컬 축/각도를 보존해 편집한다.')
    parent_frame = obj.matrix_world @ obj.matrix_basis.inverted()
    obj.matrix_basis = parent_frame.inverted() @ desired_world


def transform_vertices(obj, root, transform):
    """root 좌표 변환을 Basis와 모든 Shape Key에 적용한다. UV 재검토는 별도다."""
    if obj.type != 'MESH':
        raise TypeError('메시만 변환할 수 있다.')
    matrix = root.matrix_world.inverted() @ obj.matrix_world
    inverse = matrix.inverted()
    blocks = ([key.data for key in obj.data.shape_keys.key_blocks]
              if obj.data.shape_keys else [obj.data.vertices])
    for vertices in blocks:
        for vertex in vertices:
            vertex.co = inverse @ transform(matrix @ vertex.co)
    obj.data.update()


def freeze_evaluated_meshes(names):
    """같은 평가 시점의 표면을 복사한 뒤 지정 메시의 모디파이어만 제거한다."""
    import bpy
    objects = [bpy.data.objects[name] for name in names]
    if not objects or len(set(names)) != len(names) or any(o.type != 'MESH' for o in objects):
        raise ValueError('중복 없는 메시 배열이 필요하다.')
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    snapshots = [(obj, bpy.data.meshes.new_from_object(
        obj.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph)) for obj in objects]
    for obj, mesh in snapshots:
        obj.data = mesh
        obj.modifiers.clear()


def partition_mesh_faces(obj, groups, cap_material=None, *, planes=False):
    """원래 면·UV·코너 노멀을 보존해 강체 패널로 분리한다. 선택적으로 절단면을 막는다."""
    import bpy
    import bmesh
    if obj.type != 'MESH' or obj.data.shape_keys or obj.modifiers:
        raise ValueError('Shape Key·모디파이어가 없는 정적 메시만 분리한다.')
    names = [group['name'] for group in groups]
    faces = [] if planes else [index for group in groups for index in group['faces']]
    if len(groups) < 2 or len(names) != len(set(names)):
        raise ValueError('이름이 고유한 두 개 이상의 분할이 필요하다.')
    if not planes and (any(not group['faces'] for group in groups)
            or any(type(index) is not int for index in faces)
            or len(faces) != len(set(faces)) or set(faces) != set(range(len(obj.data.polygons)))):
        raise ValueError('모든 면을 중복 없이 포함하는 두 개 이상의 분할이 필요하다.')
    if planes:
        for group in groups:
            if not group.get('planes'):
                raise ValueError('절단 평면이 필요하다.')
            for plane in group['planes']:
                if len(plane) != 4 or any(not isinstance(value, (float, int)) or not math.isfinite(value) for value in plane):
                    raise ValueError('평면은 유한한 [nx, ny, nz, 거리] 배열이다.')
                if sum(value * value for value in plane[:3]) < 1e-12:
                    raise ValueError('평면의 법선은 영벡터일 수 없다.')
    if any(name in bpy.data.objects for name in names):
        raise ValueError('새 패널 이름이 기존 객체와 겹친다.')
    source = obj.data
    face_tag, vertex_tag = 'FD_PartitionSourceFace', 'FD_PartitionSourceVertex'
    if any(name in source.attributes for name in (face_tag, vertex_tag)):
        raise ValueError('분리 검사 속성명이 기존 메시와 겹친다.')
    normals = {(polygon.index, source.loops[index].vertex_index): source.corner_normals[index].vector.copy()
               for polygon in source.polygons for index in polygon.loop_indices}
    material = bpy.data.materials[cap_material] if cap_material else None
    outputs = []
    for group in groups:
        mesh = source.copy()
        mesh.name = group['name'] + '_Mesh'
        face_ids = mesh.attributes.new(face_tag, 'INT', 'FACE')
        face_ids.data.foreach_set('value', list(range(len(mesh.polygons))))
        vertex_ids = mesh.attributes.new(vertex_tag, 'INT', 'POINT')
        vertex_ids.data.foreach_set('value', list(range(len(mesh.vertices))))
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            face_layer = bm.faces.layers.int[face_tag]
            if planes:
                from mathutils import Vector
                normal_layer = bm.loops.layers.float_vector.new('FD_PartitionNormal')
                for face in bm.faces:
                    for loop in face.loops:
                        loop[normal_layer] = normals[(face[face_layer], loop.vert.index)]
            else:
                chosen = set(group['faces'])
                bmesh.ops.delete(bm, geom=[face for face in bm.faces if face[face_layer] not in chosen], context='FACES')
            cuts = group['planes'] if planes else [None]
            for plane in cuts:
                if plane is not None:
                    normal = Vector(plane[:3])
                    bmesh.ops.bisect_plane(bm, geom=[*bm.verts, *bm.edges, *bm.faces],
                                          dist=1e-6, plane_co=normal * (plane[3] / normal.length_squared),
                                          plane_no=normal, clear_inner=True, clear_outer=False)
                if material:
                    _cap_partition(bm, mesh, material, face_layer)
            if material:
                # 원본 구멍까지 메우지 않도록 닫힌 원본만 허용한다.
                edge_counts = {}
                for polygon in source.polygons:
                    vertices = list(polygon.vertices)
                    for a, b in zip(vertices, vertices[1:] + vertices[:1]):
                        edge = tuple(sorted((a, b)))
                        edge_counts[edge] = edge_counts.get(edge, 0) + 1
                if any(count != 2 for count in edge_counts.values()):
                    raise ValueError('절단면 마감은 모든 모서리에 면이 두 개 연결된 원본만 지원한다.')
                if any(not edge.is_manifold for edge in bm.edges):
                    counts = {}
                    for edge in bm.edges:
                        counts[len(edge.link_faces)] = counts.get(len(edge.link_faces), 0) + 1
                    raise ValueError(f"{group['name']}: 마감 후 모서리 연결이 잘못됐다: {counts}")
            bm.normal_update()
            bm.to_mesh(mesh)
        finally:
            bm.free()
        transferred = []
        for polygon in mesh.polygons:
            source_face = mesh.attributes[face_tag].data[polygon.index].value
            for index in polygon.loop_indices:
                source_vertex = mesh.attributes[vertex_tag].data[mesh.loops[index].vertex_index].value
                if source_face >= 0:
                    value = (mesh.attributes['FD_PartitionNormal'].data[index].vector.normalized()
                             if planes else normals[(source_face, source_vertex)])
                else:
                    value = polygon.normal.copy()
                transferred.append(value)
        mesh.normals_split_custom_set(transferred)
        mesh.update()
        panel = obj.copy()
        panel.data = mesh
        panel.name = group['name']
        for collection in obj.users_collection:
            collection.objects.link(panel)
        panel['fd_partition_source'] = obj.name
        outputs.append(panel)
    obj.hide_render = True
    obj.hide_viewport = True
    return outputs


def _cap_partition(bm, mesh, material, face_layer):
    """단순한 절단 경계를 닫고 기존 면과 구분되는 내부 재질을 지정한다."""
    import bmesh
    boundary = [edge for edge in bm.edges if edge.is_boundary]
    if any(sum(edge.is_boundary for edge in vertex.link_edges) != 2
           for vertex in bm.verts if vertex.is_boundary):
        raise ValueError('절단 경계가 단순한 고리로 이어지지 않는다.')
    if material.name not in mesh.materials:
        mesh.materials.append(material)
    material_index = mesh.materials.find(material.name)
    caps = bmesh.ops.holes_fill(bm, edges=boundary, sides=0)['faces']
    for face in caps:
        face[face_layer] = -1
        face.material_index = material_index
        face.smooth = False
    for face in bmesh.ops.triangulate(bm, faces=caps)['faces']:
        face[face_layer] = -1

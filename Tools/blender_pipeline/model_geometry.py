"""Blender 모델 수정에 사용하는 명시적 좌표·장착 보조 함수. import 부작용 없음."""


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

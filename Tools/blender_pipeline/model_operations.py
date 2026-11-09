"""새 모델/버전별 Python 파일 없이 JSON 작업을 적용하는 공통 연산."""
import math
from model_geometry import transform_vertices


def vector(value):
    if not isinstance(value, list) or len(value) != 3 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in value):
        raise ValueError('유한한 숫자 3개의 배열이 필요하다.')
    return value


def apply_operations(operations):
    import bpy
    from mathutils import Vector
    for operation in operations:
        kind = operation['op']
        if kind in ('create_empty', 'create_box', 'create_profile'):
            name = operation['name']
            if name in bpy.data.objects:
                raise ValueError(f'중복 객체: {name}')
            if kind == 'create_empty':
                obj = bpy.data.objects.new(name, None)
                bpy.context.scene.collection.objects.link(obj)
            elif kind == 'create_profile':
                from model_primitives import profile_mesh
                obj = profile_mesh(name, operation['profiles'], operation.get('capped', True))
            else:
                bpy.ops.mesh.primitive_cube_add(size=1)
                obj = bpy.context.object
                obj.name = name
                obj.scale = vector(operation.get('size', [1, 1, 1]))
                if min(obj.scale) <= 0:
                    raise ValueError('크기는 양수여야 한다.')
            if operation.get('parent'):
                obj.parent = bpy.data.objects[operation['parent']]
            obj.location = vector(operation.get('location', [0, 0, 0]))
            obj.rotation_euler = [math.radians(x) for x in vector(operation.get('rotation_degrees', [0, 0, 0]))]
            for key, value in operation.get('properties', {}).items():
                obj[key] = value
            if operation.get('material') and obj.type == 'MESH':
                obj.data.materials.append(bpy.data.materials[operation['material']])
        elif kind == 'set_frame':
            bpy.context.scene.frame_set(int(operation['frame']))
        elif kind == 'freeze_pose':
            obj = bpy.data.objects[operation['object']]
            if obj.type != 'ARMATURE':
                raise TypeError('포즈 고정 대상은 Armature여야 한다.')
            matrices = {b.name: b.matrix_basis.copy() for b in obj.pose.bones}
            if obj.animation_data:
                obj.animation_data.action = None
                for track in obj.animation_data.nla_tracks:
                    track.mute = True
            for name, matrix in matrices.items():
                obj.pose.bones[name].matrix_basis = matrix
        elif kind == 'set_constraint_mute':
            obj = bpy.data.objects[operation['object']]
            owner = obj.pose.bones[operation['bone']] if operation.get('bone') else obj
            owner.constraints[operation['constraint']].mute = bool(operation['muted'])
        elif kind == 'aim_bone':
            from mathutils import Matrix
            obj = bpy.data.objects[operation['object']]
            bone = obj.pose.bones[operation['bone']]
            desired = Vector(vector(operation['world_direction']))
            if desired.length < 1e-8:
                raise ValueError('본 방향은 영벡터일 수 없다.')
            world = obj.matrix_world @ bone.matrix
            delta = world.to_3x3().col[1].normalized().rotation_difference(desired.normalized())
            world = Matrix.Translation(world.translation) @ delta.to_matrix().to_4x4() @ Matrix.Translation(-world.translation) @ world
            bone.matrix = obj.matrix_world.inverted() @ world
        elif kind == 'pose_limb':
            from mathutils import Matrix, Quaternion
            obj = bpy.data.objects[operation['object']]
            upper, lower, end = [obj.pose.bones[operation[k]] for k in ('upper', 'lower', 'end')]
            root = obj.matrix_world @ upper.head
            target = Vector(vector(operation['target_world']))
            delta = target - root
            distance = delta.length
            length_a = (obj.matrix_world.to_3x3() @ (upper.tail - upper.head)).length
            length_b = (obj.matrix_world.to_3x3() @ (lower.tail - lower.head)).length
            if not abs(length_a - length_b) + 1e-6 < distance < length_a + length_b - 1e-6:
                raise ValueError('두 관절의 도달 범위 밖이다.')
            axis = delta.normalized()
            bend = Vector(vector(operation['bend_world'])) - root
            bend -= axis * bend.dot(axis)
            if bend.length < 1e-6:
                raise ValueError('굽힘 기준이 목표축과 겹친다.')
            along = (length_a**2 - length_b**2 + distance**2) / (2 * distance)
            elbow = root + axis * along + bend.normalized() * math.sqrt(max(0, length_a**2 - along**2))
            for bone, direction in ((upper, elbow - root), (lower, target - elbow)):
                apply_operations([{'op': 'aim_bone', 'object': obj.name, 'bone': bone.name,
                                   'world_direction': list(direction)}])
            if 'end_rotation_world' in operation:
                values = operation['end_rotation_world']
                if len(values) != 4 or not all(math.isfinite(v) for v in values) or sum(v*v for v in values) < 1e-12:
                    raise ValueError('유한한 비영 쿼터니언이 필요하다.')
                world = obj.matrix_world @ end.matrix
                rotation = Quaternion(values).normalized().to_matrix().to_4x4()
                world = Matrix.Translation(world.translation) @ rotation @ Matrix.Diagonal((*world.to_scale(), 1))
                end.matrix = obj.matrix_world.inverted() @ world
                bpy.context.view_layer.update()
            if (obj.matrix_world @ end.head - target).length > 1e-4:
                raise ValueError('연결 체인 또는 제약 때문에 말단이 목표에 도달하지 못했다.')
        elif kind == 'attach_world':
            from mathutils import Matrix
            from model_geometry import set_world_matrix_from_parent_frame
            obj = bpy.data.objects[operation['object']]
            rows = operation['matrix_world']
            if len(rows) != 4 or any(len(row) != 4 or not all(math.isfinite(x) for x in row) for row in rows):
                raise ValueError('유한한 4x4 월드 행렬이 필요하다.')
            obj.parent = bpy.data.objects[operation['parent']]
            obj.parent_type = 'BONE' if operation.get('bone') else 'OBJECT'
            obj.parent_bone = operation.get('bone', '')
            if obj.parent_type == 'BONE' and obj.parent_bone not in obj.parent.data.bones:
                raise ValueError('장착 대상 본이 없다.')
            bpy.context.view_layer.update()
            set_world_matrix_from_parent_frame(obj, Matrix(rows))
        elif kind == 'attachment_switch':
            obj = bpy.data.objects[operation['object']]
            control = bpy.data.objects[operation['control']]
            key = operation['property']
            if key not in control:
                raise ValueError('전환 제어 속성이 없다.')
            for target, driven in ((operation['stowed_target'], False), (operation['held_target'], True)):
                constraint = obj.constraints.new('COPY_TRANSFORMS')
                constraint.target = bpy.data.objects[target]
                if driven:
                    driver = constraint.driver_add('influence').driver
                    variable = driver.variables.new()
                    variable.name = 'stowed'
                    variable.targets[0].id = control
                    variable.targets[0].data_path = f'["{key}"]'
                    driver.expression = '1-min(max(stowed,0),1)'
        elif kind == 'create_material':
            name = operation['name']
            if name in bpy.data.materials:
                raise ValueError(f'중복 재질: {name}')
            material = bpy.data.materials.new(name)
            material.use_nodes = True
            node = material.node_tree.nodes.get('Principled BSDF')
            node.inputs['Base Color'].default_value = (*vector(operation.get('color', [.3, .3, .3])), 1)
            for field, socket, default in [('roughness', 'Roughness', .5), ('metallic', 'Metallic', 0),
                                           ('transmission', 'Transmission Weight', 0), ('coat', 'Coat Weight', 0)]:
                value = operation.get(field, default)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError(f'{field}는 0~1이어야 한다.')
                node.inputs[socket].default_value = value
            ior = operation.get('ior', 1.5)
            if not isinstance(ior, (int, float)) or not math.isfinite(ior) or not 1 <= ior <= 4:
                raise ValueError('굴절률은 1~4여야 한다.')
            node.inputs['IOR'].default_value = ior
            if operation.get('energy_control'):
                control = bpy.data.objects[operation['energy_control']]
                for index, key in enumerate(('energy_color_r', 'energy_color_g', 'energy_color_b')):
                    driver = node.inputs['Emission Color'].driver_add('default_value', index).driver
                    var = driver.variables.new()
                    var.name = 'value'
                    var.targets[0].id = control
                    var.targets[0].data_path = f'["{key}"]'
                    driver.expression = 'value'
                driver = node.inputs['Emission Strength'].driver_add('default_value').driver
                var = driver.variables.new()
                var.name = 'value'
                var.targets[0].id = control
                var.targets[0].data_path = '["energy_strength"]'
                driver.expression = 'value'
        elif kind == 'add_bevel':
            obj = bpy.data.objects[operation['object']]
            width = operation.get('width', .005)
            if not math.isfinite(width) or width <= 0:
                raise ValueError('bevel 폭은 양수여야 한다.')
            modifier = obj.modifiers.new('Pipeline_Bevel', 'BEVEL')
            modifier.width = width
            modifier.segments = operation.get('segments', 2)
        elif kind == 'transform_vertices':
            obj = bpy.data.objects[operation['object']]
            root = bpy.data.objects[operation['root']]
            scale = Vector(vector(operation.get('scale', [1, 1, 1])))
            if min(scale) <= 0:
                raise ValueError('스케일은 양수여야 한다. 반전은 별도 조형 기능으로 처리한다.')
            offset = Vector(vector(operation.get('offset', [0, 0, 0])))
            pivot = Vector(vector(operation.get('pivot', [0, 0, 0])))
            transform_vertices(obj, root, lambda p: pivot + Vector([(p[i] - pivot[i]) * scale[i] for i in range(3)]) + offset)
        elif kind == 'set_properties':
            obj = bpy.data.objects[operation['object']]
            for key, value in operation['values'].items():
                if key not in obj:
                    raise ValueError(f'기존 제어 속성만 변경한다: {obj.name}.{key}')
                obj[key] = value
            obj.update_tag()
        elif kind == 'set_visibility':
            obj = bpy.data.objects[operation['object']]
            obj.hide_render = bool(operation['hidden'])
            obj.hide_set(bool(operation['hidden']))
        elif kind == 'assign_material':
            obj = bpy.data.objects[operation['object']]
            material = bpy.data.materials[operation['material']]
            slot = operation.get('slot', 0)
            if slot < 0 or slot >= len(obj.data.materials):
                raise ValueError('기존 재질 슬롯만 변경한다.')
            obj.data.materials[slot] = material
        elif kind == 'set_boundary_enabled':
            from boundary_detail import set_boundary_enabled
            set_boundary_enabled(operation)
        elif kind == 'repair_unweighted':
            from model_weights import repair_unweighted
            if operation.get('enabled') is not True:
                raise ValueError('가중치 보완에는 enabled=true가 필요하다.')
            repair_unweighted(bpy.data.objects[operation['source']], bpy.data.objects[operation['object']])
        elif kind == 'set_surface_finish':
            from material_surface import set_surface_finish
            set_surface_finish(operation)
        elif kind == 'generate_boundary_texture':
            from boundary_detail import generate_boundary_texture
            generate_boundary_texture(operation)
        elif kind == 'apply_boundary_texture':
            from boundary_detail import apply_boundary_texture
            apply_boundary_texture(operation)
        elif kind == 'project_panel_uv':
            from panel_detail import project_panel_uv
            project_panel_uv(operation)
        elif kind == 'generate_panel_detail':
            from panel_detail import generate_panel_detail
            generate_panel_detail(operation)
        elif kind == 'apply_pbr_surface':
            from material_surface import apply_pbr_surface
            apply_pbr_surface(operation)
        elif kind == 'pack_images':
            for image in bpy.data.images:
                if image.source in ('FILE', 'GENERATED'):
                    image.pack()
        else:
            raise ValueError(f'지원하지 않는 연산: {kind}. 버전 스크립트 대신 공통 연산을 확장한다.')
        bpy.context.view_layer.update()

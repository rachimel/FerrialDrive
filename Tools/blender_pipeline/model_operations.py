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
            if operation.get('material') and obj.type == 'MESH':
                obj.data.materials.append(bpy.data.materials[operation['material']])
        elif kind == 'create_material':
            name = operation['name']
            if name in bpy.data.materials:
                raise ValueError(f'중복 재질: {name}')
            material = bpy.data.materials.new(name)
            material.use_nodes = True
            node = material.node_tree.nodes.get('Principled BSDF')
            node.inputs['Base Color'].default_value = (*vector(operation.get('color', [.3, .3, .3])), 1)
            for field, socket, default in [('roughness', 'Roughness', .5), ('metallic', 'Metallic', 0)]:
                value = operation.get(field, default)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError(f'{field}는 0~1이어야 한다.')
                node.inputs[socket].default_value = value
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
        elif kind == 'pack_images':
            for image in bpy.data.images:
                if image.source in ('FILE', 'GENERATED'):
                    image.pack()
        else:
            raise ValueError(f'지원하지 않는 연산: {kind}. 버전 스크립트 대신 공통 연산을 확장한다.')
        bpy.context.view_layer.update()

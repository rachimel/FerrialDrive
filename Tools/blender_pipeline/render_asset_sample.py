"""별도 Blender 백그라운드 인스턴스에서 기본 도형의 8방향 본체·그림자를 출력한다."""

import argparse
import hashlib
import json
from math import pi, radians, sin
from pathlib import Path
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Tools.blender_pipeline.framing import orthographic_fit


def material(name, color):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1)
    result.use_nodes = True
    shader = result.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = 0.65
    return result


def cube(name, position, size, surface, parent):
    bpy.ops.mesh.primitive_cube_add(size=1, location=position)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(surface)
    obj.parent = parent
    bevel = obj.modifiers.new('Edge', 'BEVEL')
    bevel.width, bevel.segments = 0.035, 1
    return obj


def build_scene(config):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    width, height = config['frame_size_pixels']
    scene.render.engine = config['render']['engine']
    if scene.render.engine != 'CYCLES':
        raise ValueError('이 샘플의 분리 그림자는 Cycles를 사용한다.')
    scene.cycles.device = 'CPU'
    scene.cycles.samples = config['render']['samples']
    scene.cycles.seed = config['render']['seed']
    scene.cycles.use_denoising = config['render'].get('denoise', False)
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.view_settings.view_transform = 'Standard'
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.25
    scene.render.fps = config['fps']
    scene.frame_start, scene.frame_end = 1, 9

    root = bpy.data.objects.new('ActorRoot', None)
    scene.collection.objects.link(root)
    steel = material('Steel', (0.19, 0.36, 0.43))
    pale = material('Pale', (0.54, 0.70, 0.73))
    orange = material('ForwardMarker', (0.95, 0.28, 0.06))
    actor = [cube('Body', (0, 0, 0.95), (0.65, 0.65, 0.75), steel, root),
             cube('Head', (0, 0, 1.52), (0.43, 0.46, 0.35), pale, root),
             cube('Front', (0.37, 0, 1.07), (0.18, 0.36, 0.22), orange, root)]
    for side in (-1, 1):
        actor.append(cube(f'Arm{side}', (0, side * 0.49, 0.92), (0.32, 0.25, 0.70), pale, root))
        leg = cube(f'Leg{side}', (0, side * 0.22, 0.28), (0.37, 0.28, 0.52), steel, root)
        actor.append(leg)
        for frame in (1, 3, 5, 7, 9):
            leg.location.x = side * 0.18 * sin((frame - 1) * pi / 4)
            leg.location.z = 0.28 + max(0, side * sin((frame - 1) * pi / 4)) * 0.08
            leg.keyframe_insert(data_path='location', frame=frame)

    bpy.ops.mesh.primitive_plane_add(size=200)
    floor = bpy.context.object
    floor.name, floor.is_shadow_catcher = 'ShadowCatcher', True
    bpy.ops.object.camera_add(location=config['camera']['position'])
    camera = bpy.context.object
    camera.rotation_euler = (Vector(config['camera']['target']) - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type, camera.data.ortho_scale = 'ORTHO', config['camera']['ortho_scale']
    scene.camera = camera
    bpy.ops.object.light_add(type='AREA', location=config['light']['position'])
    light = bpy.context.object
    light.rotation_euler = (-light.location).to_track_quat('-Z', 'Y').to_euler()
    light.data.energy, light.data.shape, light.data.size = config['light']['energy'], 'DISK', config['light']['size']
    return scene, root, actor, floor


def prepare_saved_scene(config):
    """원본을 덮어쓰지 않고 기존 계층·리그·키프레임을 렌더용 부모 아래 보존한다."""
    scene = bpy.context.scene
    root_name = config.get('root_object', '')
    model = bpy.data.objects.get(root_name) if root_name else bpy.data.objects.get('ActorRoot')
    if root_name and model is None:
        raise ValueError(f'모델 루트 오브젝트가 없다: {root_name}')
    root = bpy.data.objects.new('FDriveExportRoot', None)
    scene.collection.objects.link(root)
    floor = bpy.data.objects.get('ShadowCatcher')
    objects = [model] if model else [obj for obj in scene.objects
        if obj.parent is None and obj is not root and obj is not floor
        and obj.type not in {'CAMERA', 'LIGHT'}]
    if not objects:
        raise ValueError('렌더할 모델이 없다.')
    for obj in objects:
        world = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_world = world
    if not any(obj.type == 'MESH' for obj in root.children_recursive):
        raise ValueError('모델 루트 아래에 메시가 필요하다.')
    if floor is None:
        bpy.ops.mesh.primitive_plane_add(size=200)
        floor = bpy.context.object
        floor.name = 'ShadowCatcher'
    floor.is_shadow_catcher = True
    if not config.get('use_scene_camera', True) or scene.camera is None:
        bpy.ops.object.camera_add(location=config['camera']['position'])
        camera = bpy.context.object
        camera.rotation_euler = (Vector(config['camera']['target']) - camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.type, camera.data.ortho_scale = 'ORTHO', config['camera']['ortho_scale']
        scene.camera = camera
    if not any(obj.type == 'LIGHT' and not obj.hide_render for obj in scene.objects):
        bpy.ops.object.light_add(type='AREA', location=config['light']['position'])
        light = bpy.context.object
        light.rotation_euler = (-light.location).to_track_quat('-Z', 'Y').to_euler()
        light.data.energy, light.data.shape, light.data.size = config['light']['energy'], 'DISK', config['light']['size']
    scene.render.fps = int(config['fps'])
    return scene, root, floor


def light_rays(lights):
    result = []
    for obj in lights:
        if obj.data.type == 'SUN':
            result.append(('direction', obj.matrix_world.to_quaternion() @ Vector((0, 0, -1))))
        else:
            result.append(('position', obj.matrix_world.translation.copy()))
            if obj.data.type == 'AREA':
                half_x = obj.data.size / 2
                half_y = getattr(obj.data, 'size_y', obj.data.size) / 2 if obj.data.shape in {'RECTANGLE', 'ELLIPSE'} else half_x
                for x in (-half_x, half_x):
                    for y in (-half_y, half_y):
                        result.append(('position', obj.matrix_world @ Vector((x, y, 0))))
    return result


def fit_camera(scene, root, floor, actor, config):
    """모든 방향·프레임과 지면 그림자를 같은 카메라에 맞춰 재생 중 배율을 유지한다."""
    camera = scene.camera
    if camera.data.type != 'ORTHO':
        raise ValueError('자동 맞춤은 정사영 카메라가 필요하다.')
    rotation = camera.matrix_world.to_quaternion()
    inverse = rotation.inverted()
    old_scale = camera.data.ortho_scale
    camera.data.ortho_scale = 1
    viewport = camera.data.view_frame(scene=scene)
    camera.data.ortho_scale = old_scale
    left, right = min(p.x for p in viewport), max(p.x for p in viewport)
    bottom, top = min(p.y for p in viewport), max(p.y for p in viewport)
    original_rotation, original_frame = root.rotation_euler.copy(), scene.frame_current
    lights = [obj for obj in scene.objects if obj.type == 'LIGHT' and not obj.hide_render and obj.data.energy > 0]
    ground = floor.matrix_world.translation.copy()
    normal = floor.matrix_world.to_quaternion() @ Vector((0, 0, 1))
    def points():
        # 지면 원점(피봇)도 출력 영역에 포함한다.
        yield tuple(inverse @ Vector((0, 0, 0)))
        try:
            for direction in config['directions']:
                root.rotation_euler.z = radians(direction['heading_degrees'])
                for frame in config['frames']:
                    scene.frame_set(frame)
                    depsgraph = bpy.context.evaluated_depsgraph_get()
                    rays = light_rays(lights)
                    for obj in actor:
                        if obj.hide_render:
                            continue
                        evaluated = obj.evaluated_get(depsgraph)
                        for corner in evaluated.bound_box:
                            point = evaluated.matrix_world @ Vector(corner)
                            yield tuple(inverse @ point)
                            for kind, light in rays:
                                ray = light if kind == 'direction' else point - light
                                denominator = ray.dot(normal)
                                if abs(denominator) < 1e-6:
                                    continue
                                distance = (ground - point).dot(normal) / denominator
                                if distance >= 0:
                                    yield tuple(inverse @ (point + distance * ray))
        finally:
            root.rotation_euler = original_rotation
            scene.frame_set(original_frame)
    center, scale, depth = orthographic_fit(points(), right - left, top - bottom, old_scale)
    local = inverse @ camera.location
    local.x = center[0] - (left + right) * scale / 2
    local.y = center[1] - (bottom + top) * scale / 2
    local.z = max(local.z, depth[1] + max(scale, 1))
    camera.location = rotation @ local
    camera.data.ortho_scale = scale
    camera.data.clip_end = max(camera.data.clip_end, local.z - depth[0] + scale)
    bpy.context.view_layer.update()
    result = {'ortho_scale': scale, 'position': list(camera.location), 'padding': 0.08}
    print('ASSET_FRAMING ' + json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work-file', type=Path, required=True)
    parser.add_argument('--source-blend', type=Path, help='기존 모델·리그·키프레임을 가진 저장 장면')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    config_bytes = args.config.read_bytes()
    config = json.loads(config_bytes)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.source_blend:
        bpy.ops.wm.open_mainfile(filepath=str(args.source_blend.resolve()))
        scene, root, floor = prepare_saved_scene(config)
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = config['render']['samples']
        scene.cycles.seed = config['render']['seed']
        scene.cycles.use_denoising = config['render'].get('denoise', False)
        scene.render.resolution_x, scene.render.resolution_y = config['frame_size_pixels']
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '8'
    else:
        scene, root, actor, floor = build_scene(config)
    root_name = root.name
    scene.frame_set(1)
    floor.hide_render = True
    actor = [obj for obj in root.children_recursive if obj.type == 'MESH' and obj is not floor]
    framing = None
    if config.get('auto_fit', not config.get('use_scene_camera', True)):
        framing = fit_camera(scene, root, floor, actor, config)
    args.work_file.parent.mkdir(parents=True, exist_ok=True)
    # 렌더 전 설정·애니메이션을 재사용할 수 있는 작업본으로 남긴다.
    bpy.ops.wm.save_as_mainfile(filepath=str(args.work_file.resolve()))
    # 메모리의 장면만 렌더하지 않고 저장된 작업본을 실제로 다시 불러온다.
    bpy.ops.wm.open_mainfile(filepath=str(args.work_file.resolve()))
    scene = bpy.context.scene
    root, floor = bpy.data.objects[root_name], bpy.data.objects['ShadowCatcher']
    actor = [obj for obj in root.children_recursive if obj.type == 'MESH' and obj is not floor]
    scene.frame_set(1)
    point = world_to_camera_view(scene, scene.camera, Vector((0, 0, 0)))
    width, height = config['frame_size_pixels']
    rows = []
    for direction in config['directions']:
        root.rotation_euler.z = radians(direction['heading_degrees'])
        frames = []
        for frame in config['frames']:
            scene.frame_set(frame)
            paths = {}
            for layer in ('body', 'shadow'):
                scene.cycles.samples = config['render'].get('shadow_samples', config['render']['samples']) if layer == 'shadow' else config['render']['samples']
                floor.hide_render = layer == 'body'
                for obj in actor:
                    # 카메라에서만 숨겨 본체가 그림자를 계속 드리우게 한다.
                    obj.visible_camera = layer == 'body'
                relative = Path('frames') / direction['id'] / f'{frame:04}-{layer}.png'
                path = output / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                scene.render.filepath = str(path)
                bpy.ops.render.render(write_still=True)
                paths[layer] = relative.as_posix()
                print(f'ASSET_FRAME {direction["id"]} {frame} {layer}', flush=True)
            frames.append(paths)
        rows.append({'id': direction['id'], 'heading_degrees': direction['heading_degrees'], 'frames': frames})
    document = {'version': 1, 'asset_id': config['asset_id'], 'frame_size_pixels': [width, height],
                'animation_name': config.get('animation_name', 'walk'),
                'pivot': [point.x * width, point.y * height], 'fps': config['fps'], 'directions': rows,
                'config': config, 'config_sha256': hashlib.sha256(config_bytes).hexdigest(),
                'framing': framing,
                'blender_version': bpy.app.version_string}
    (output / 'rendered_frames.json').write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

"""Independent collisions check. Run in background Blender."""
import math


def check(config):
    import bpy
    from mathutils.bvhtree import BVHTree
    errors, warnings, objects, images = [], [], [], []
    if not config.get('collision_pairs'):
        return {'errors': [], 'status': 'not_configured', 'collision_samples': []}
    def tree(name):
        obj = bpy.data.objects.get(name)
        if not obj or obj.type != 'MESH' or obj.hide_render:
            raise ValueError(f'검사할 가시 메시가 없다: {name}')
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            return BVHTree.FromPolygons([evaluated.matrix_world @ v.co for v in mesh.vertices],
                                       [list(p.vertices) for p in mesh.polygons])
        finally:
            evaluated.to_mesh_clear()

    collisions = []
    states = config.get('states', [{'name': 'saved_pose', 'frame': bpy.context.scene.frame_current}])
    if not states:
        raise ValueError('states는 적어도 한 자세를 포함해야 한다.')
    for state in states:
        # 각 상태의 독립성을 위해 아래의 변경분을 매번 복원한다.
        previous = []
        frame = bpy.context.scene.frame_current
        try:
            bpy.context.scene.frame_set(state.get('frame', frame))
            for change in state.get('properties', []):
                obj = bpy.data.objects[change['object']]
                if change['property'] not in obj:
                    raise ValueError(f"없는 제어 속성: {change}")
                previous.append((obj, change['property'], obj[change['property']]))
                obj[change['property']] = change['value']
                obj.update_tag()
            bpy.context.view_layer.update()
            cache = {}
            for pair in config.get('collision_pairs', []):
                for name in pair:
                    if name not in cache:
                        cache[name] = tree(name)
                count = len(cache[pair[0]].overlap(cache[pair[1]]))
                collisions.append({'state': state['name'], 'pair': pair, 'surface_intersections': count})
                if count:
                    errors.append(f"intersection:{state['name']}:{pair}")
        finally:
            for obj, key, value in previous:
                obj[key] = value
                obj.update_tag()
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
    return {'errors': errors, 'collision_samples': collisions, 'not_tested': ['solid containment', 'continuous collision', 'all poses']}


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_check_io import main
    main(check)

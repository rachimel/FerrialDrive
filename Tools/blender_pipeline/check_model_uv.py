"""Independent uv check. Run in background Blender."""
import math


def check(config):
    import bpy
    from mathutils.bvhtree import BVHTree
    errors, warnings, objects, images = [], [], [], []
    if not config.get('uv_objects'):
        return {'errors': [], 'status': 'not_configured'}
    for name in config.get('uv_objects', []):
        obj = bpy.data.objects.get(name)
        if not obj or obj.type != 'MESH':
            errors.append(f'missing_uv_object:{name}')
            continue
        layer = obj.data.uv_layers.get(config.get('uv_layer', 'UV_Paint'))
        if layer is None:
            errors.append(f'missing_uv_layer:{name}')
            continue
        if any(not math.isfinite(x) or x < 0 or x > 1 for loop in layer.data for x in loop.uv):
            errors.append(f'uv_bounds:{name}')
        obj.data.calc_loop_triangles()
        for triangle in obj.data.loop_triangles:
            a, b, c = [layer.data[i].uv for i in triangle.loops]
            if abs((b - a).cross(c - a)) < 1e-12:
                errors.append(f'zero_area_uv:{name}')
                break
    return {'errors': errors, 'not_tested': ['island overlap', 'texel density', 'padding']}


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_check_io import main
    main(check)

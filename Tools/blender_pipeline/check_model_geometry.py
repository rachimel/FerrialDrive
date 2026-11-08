"""Independent geometry check. Run in background Blender."""
import math


def check(config):
    import bpy
    from mathutils.bvhtree import BVHTree
    errors, warnings, objects, images = [], [], [], []
    for name in config.get('required_objects', []):
        if name not in bpy.data.objects:
            errors.append(f'missing_object:{name}')
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.hide_render:
            continue
        mesh = obj.data
        finite = all(math.isfinite(x) for v in mesh.vertices for x in v.co)
        if not finite:
            errors.append(f'nonfinite_vertices:{obj.name}')
            continue
        mesh.calc_loop_triangles()
        zero_area = sum(t.area < 1e-12 for t in mesh.loop_triangles)
        warped = sum(len(p.vertices) > 3 and max(abs((mesh.vertices[i].co - p.center).dot(p.normal))
                     for i in p.vertices) > config.get('planarity_tolerance', .001) for p in mesh.polygons)
        if zero_area:
            errors.append(f'zero_area_geometry:{obj.name}:{zero_area}')
        if warped:
            warnings.append(f'nonplanar_faces:{obj.name}:{warped}')
        objects.append({'name': obj.name, 'vertices': len(mesh.vertices), 'triangles': len(mesh.loop_triangles),
                        'nonplanar_faces': warped})
    return {'errors': errors, 'warnings': warnings, 'objects': objects}


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_check_io import main
    main(check)

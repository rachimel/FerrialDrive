"""Independent images check. Run in background Blender."""
import math


def check(config):
    import bpy
    from mathutils.bvhtree import BVHTree
    errors, warnings, objects, images = [], [], [], []
    for im in bpy.data.images:
        if im.source == 'VIEWER':
            continue
        images.append({'name': im.name, 'size': list(im.size), 'packed': bool(im.packed_file)})
        if not all(im.size) or max(im.size) > config.get('max_texture_size', 1024):
            errors.append(f'image_size:{im.name}')
        if config.get('require_packed', True) and not im.packed_file:
            errors.append(f'unpacked_image:{im.name}')

    return {'errors': errors, 'images': images, 'not_tested': ['material node connections', 'colorspace semantics']}


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_check_io import main
    main(check)

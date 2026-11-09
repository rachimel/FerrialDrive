"""PBR 표면·UV 패널 샘플. 실제 메카와 다운로드 에셋 없이 상자로 검증한다."""
import argparse
from pathlib import Path
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools/blender_pipeline'))
from model_operations import apply_operations
from model_snapshot import fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    apply_operations([{'op': 'create_material', 'name': 'Coating'},
                      {'op': 'create_box', 'name': 'PanelBox', 'size': [1, 1, 1], 'material': 'Coating'}])
    obj = bpy.data.objects['PanelBox']
    material = bpy.data.materials['Coating']
    shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    emission = material.node_tree.nodes.new('ShaderNodeRGB')
    emission.outputs[0].default_value = (.01, .2, .5, 1)
    material.node_tree.links.new(emission.outputs[0], shader.inputs['Emission Color'])
    shader.inputs['Emission Strength'].default_value = .03
    before = fingerprint(obj)
    regions = {key: [(i%2)*.5+.02, (i//2)/3+.02, (i%2)*.5+.48, (i//2+1)/3-.02]
               for i, key in enumerate(('+X', '-X', '+Y', '-Y', '+Z', '-Z'))}
    apply_operations([dict(op='project_panel_uv', uv_layer='UV_Panel', objects=[dict(name=obj.name, regions=regions)])])
    assert fingerprint(obj, excluded_uv=('UV_Panel',)) == before
    assert next(layer.name for layer in obj.data.uv_layers if layer.active_render) == 'UVMap'
    before = fingerprint(obj)
    maps = {}
    for role in ('color', 'roughness', 'height'):
        im = bpy.data.images.new('Demo_'+role, width=32, height=32)
        pixels = np.ones((32, 32, 4), dtype=np.float32)
        pixels[..., :3] = np.linspace(.2, .8, 32)[None, :, None]
        im.pixels.foreach_set(pixels.ravel())
        im.filepath_raw = str(output / (role+'.png'))
        im.file_format = 'PNG'
        im.save()
        maps[role] = im.filepath_raw
    panels = dict(op='generate_panel_detail', material='Coating', objects=[dict(name=obj.name, profile='limb', uv_layer='UV_Panel')],
                  output_color=str(output/'panel_color.png'), output_height=str(output/'panel_height.png'))
    apply_operations([panels])
    operation = dict(op='apply_pbr_surface', material='Coating', maps=maps, scale=2,
                     color_low=[.1, .12, .15], color_high=[.3, .35, .4],
                     panel_detail=dict(color=panels['output_color'], height=panels['output_height'], uv_layer='UV_Panel'))
    for _ in range(2):
        apply_operations([operation])
        assert fingerprint(obj) == before, '형상·UV·재질 슬롯 변경'
        assert shader.inputs['Emission Color'].links[0].from_node == emission, '발광 연결 손실'
        assert abs(shader.inputs['Emission Strength'].default_value-.03) < 1e-6
    names = [n.name for n in material.node_tree.nodes if n.name.startswith('SurfacePBR::')]
    assert all(not name.endswith('.001') for name in names), '반복 적용 노드 중복'
    assert any(n.type == 'BUMP' and n.label == '새 패널 이음 깊이' for n in material.node_tree.nodes)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    apply_operations([dict(op='pack_images')])
    target = output/'sample.blend'
    object_name = obj.name
    bpy.ops.wm.save_as_mainfile(filepath=str(target))
    bpy.ops.wm.open_mainfile(filepath=str(target))
    assert fingerprint(bpy.data.objects[object_name]) == before
    print('PBR_SURFACE_DEMO passed: UV/geometry, emission, repeat apply, save/reload', flush=True)


if __name__ == '__main__':
    main()

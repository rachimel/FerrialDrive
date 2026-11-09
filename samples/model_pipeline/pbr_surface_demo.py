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
    folded_mesh = bpy.data.meshes.new('FoldedPanelMesh')
    folded_mesh.from_pydata([(1,-1,-1),(1,0,-1),(1,0,1),(1,-1,1),(-1,1,-1),(-1,1,1)], [], [(0,1,2,3),(1,4,5,2)])
    folded_mesh.update()
    folded = bpy.data.objects.new('FoldedPanel', folded_mesh)
    bpy.context.scene.collection.objects.link(folded)
    region_map = {key: [.02+i*.15,.1,.14+i*.15,.9] for i,key in enumerate(('+X','-X','+Y','-Y','+Z','-Z'))}
    apply_operations([dict(op='project_panel_uv',uv_layer='UV_Fold',objects=[dict(name=folded.name,regions=region_map,projection_axis=0)])])
    layer = folded_mesh.uv_layers['UV_Fold']
    for vertex in (1, 2):
        coordinates = [tuple(layer.data[loop.index].uv) for loop in folded_mesh.loops if loop.vertex_index==vertex]
        assert len(set(coordinates)) == 1, '접힌 면의 UV가 방향 경계에서 끊김'
    apply_operations([dict(op='project_panel_uv',uv_layer='UV_Fold',overwrite=True,objects=[dict(name=folded.name,regions=region_map,projection_axis=0)])])
    assert len(folded_mesh.uv_layers) == 1, 'UV 갱신 시 중복 레이어 생성'
    apply_operations([dict(op='create_material',name='ClearCover',transmission=1,ior=1.45,roughness=.045)])
    folded_mesh.materials.append(bpy.data.materials['ClearCover'])
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
    boundary_before = fingerprint(obj)
    boundary_path = str(output/'boundary_mask.png')
    apply_operations([dict(op='generate_boundary_texture',objects=[obj.name],output=boundary_path,width=.015)])
    assert fingerprint(obj, excluded_uv=('UV_Boundary',)) == boundary_before
    assert next(layer.name for layer in obj.data.uv_layers if layer.active_render) == 'UVMap'
    apply_operations([dict(op='generate_boundary_texture',objects=[obj.name],output=boundary_path,width=.015,
                           overwrite=True,width_overrides={obj.name:.01})])
    assert len([layer for layer in obj.data.uv_layers if layer.name=='UV_Boundary']) == 1
    assert fingerprint(obj, excluded_uv=('UV_Boundary',)) == boundary_before
    apply_operations([dict(op='create_box',name='DisabledBox',size=[1,1,1],location=[-2,0,0],material='Coating')])
    apply_operations([dict(op='generate_boundary_texture',objects=[obj.name,'DisabledBox'],output=boundary_path,width=.015,overwrite=True)])
    apply_operations([dict(op='generate_boundary_texture',objects=[obj.name],disable_objects=['DisabledBox'],output=boundary_path,
        width=.015,overwrite=True,face_filters={obj.name:dict(normal_axis=0,min_abs_normal=.9,position_axis=0,outer_fraction=.28)})])
    assert all(v.value==0 for v in bpy.data.objects['DisabledBox'].data.attributes['boundary_detail_enabled'].data)
    mask_images=[im for im in bpy.data.images if im.filepath and Path(bpy.path.abspath(im.filepath)).resolve()==Path(boundary_path)]
    assert len(mask_images)==1,'마스크 갱신 시 이미지 중복'
    mask=np.array(mask_images[0].pixels).reshape(1024,1024,4)
    boundary_uv=obj.data.uv_layers['UV_Boundary']
    for polygon in obj.data.polygons:
        points=[boundary_uv.data[i].uv for i in polygon.loop_indices]
        center=sum(points[1:],points[0].copy())/len(points)
        edge=(points[0]+points[1])*.5
        pixel=edge*.995+center*.005
        x,y=np.clip(np.floor(np.array(pixel)*1024).astype(int),0,1023)
        value=float(mask[y,x,0])
        assert value>.1 if abs(polygon.normal.x)>.9 else value<.1,'지정하지 않은 방향에 선 표시'
    assert fingerprint(obj, excluded_uv=('UV_Boundary',))==boundary_before
    apply_operations([dict(op='create_box',name='UnmarkedBox',size=[1,1,1],location=[2,0,0],material='Coating')])
    assert bpy.data.objects['UnmarkedBox'].data.attributes.get('boundary_detail_enabled') is None
    normal_link = shader.inputs['Normal'].links[0].from_node.name
    for _ in range(2):
        apply_operations([dict(op='apply_boundary_texture',material='Coating',image=boundary_path)])
        assert shader.inputs['Normal'].links[0].from_node.name == normal_link
        assert shader.inputs['Emission Color'].links[0].from_node == emission
    assert material.node_tree.nodes.get('BoundaryDetail::지정 외장만 적용').attribute_name == 'boundary_detail_enabled'
    assert all(not n.name.endswith('.001') for n in material.node_tree.nodes if n.name.startswith('BoundaryDetail::'))
    untouched = fingerprint(obj)
    image_bytes = Path(boundary_path).read_bytes()
    apply_operations([dict(op='set_boundary_enabled',objects=[obj.name],enabled=False)])
    assert all(v.value==0 for v in obj.data.attributes['boundary_detail_enabled'].data)
    assert fingerprint(obj)==untouched and Path(boundary_path).read_bytes()==image_bytes
    apply_operations([dict(op='set_boundary_enabled',objects=[obj.name],enabled=True)])
    assert all(v.value==1 for v in obj.data.attributes['boundary_detail_enabled'].data)
    apply_operations([dict(op='set_surface_finish',roughness_range=[.60,.80],specular=.28,edge_roughness=.60)])
    assert abs(material.node_tree.nodes['SurfacePBR::거칠기 범위'].inputs['To Min'].default_value-.60)<1e-6
    assert abs(shader.inputs['Specular IOR Level'].default_value-.28)<1e-6
    before = fingerprint(obj)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.context.preferences.filepaths.file_preview_type = 'NONE'
    apply_operations([dict(op='pack_images')])
    target = output/'sample.blend'
    object_name = obj.name
    bpy.ops.wm.save_as_mainfile(filepath=str(target))
    bpy.ops.wm.open_mainfile(filepath=str(target))
    assert fingerprint(bpy.data.objects[object_name]) == before
    assert all(v.value==1 for v in bpy.data.objects[object_name].data.attributes['boundary_detail_enabled'].data)
    glass = bpy.data.materials['ClearCover'].node_tree.nodes.get('Principled BSDF')
    assert glass.inputs['Transmission Weight'].default_value == 1
    assert abs(glass.inputs['Roughness'].default_value-.045) < 1e-5
    assert abs(glass.inputs['IOR'].default_value-1.45) < 1e-5
    print('PBR_SURFACE_DEMO passed: UV/geometry, emission, repeat apply, save/reload', flush=True)


if __name__ == '__main__':
    main()

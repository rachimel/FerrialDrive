"""기본 상자만으로 메카 디자인 편집기를 시연할 데이터를 만든다."""
from pathlib import Path
import argparse, sys, json, hashlib
import bpy

parser = argparse.ArgumentParser()
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
out = args.output_dir.resolve()
out.mkdir(parents=True, exist_ok=True)
model = out / 'sample_baseline.blend'
if model.exists():
    raise FileExistsError(model)
bpy.ops.wm.read_factory_settings(use_empty=True)
root = bpy.data.objects.new('ActorRoot', None)
bpy.context.scene.collection.objects.link(root)
bpy.ops.object.armature_add()
rig = bpy.context.object
rig.name = 'PlayerRigidRig'
rig.parent = root
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1))
cube = bpy.context.object
cube.name = 'Sample_Armor'
cube.parent = root
group = cube.vertex_groups.new(name=rig.data.bones[0].name)
group.add(list(range(8)), 1, 'REPLACE')
modifier = cube.modifiers.new('Armature', 'ARMATURE')
modifier.object = rig
material = bpy.data.materials.new('Sample_Material')
material.use_nodes = True
cube.data.materials.append(material)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(model))
registry = {'schema_version': 1, 'baseline': str(model), 'baseline_sha256': hashlib.sha256(model.read_bytes()).hexdigest(), 'root': root.name, 'rig': rig.name, 'parts': {'armor': {'objects': [cube.name], 'bounds_min': [-.5, -.5, .5], 'bounds_max': [.5, .5, 1.5], 'dimensions': [1, 1, 1], 'pivot': [0, 0, 1]}}, 'materials': {material.name: {}}, 'controls': {}}
(out / 'sample_registry.json').write_text(json.dumps(registry, indent=2), encoding='utf-8')
config = {'name': 'primitive_armor_demo', 'parts': [{'part': 'armor', 'scale': [1.1, 1, 1], 'profiles': [{'along_axis': 'Z', 'deform_axis': 'Y', 'knots': [[0, 1.1, 0], [.5, .85, 0], [1, 1, 0]]}]}], 'materials': [{'material': material.name, 'roughness': .65}]}
(out / 'sample_config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
print('MECH_DESIGN_SAMPLE_CREATED', out, flush=True)

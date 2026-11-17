"""원본 재질을 변경하지 않고 이관용 UV·PBR·에너지 마스크를 베이크한다."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_source import load_geometry, sha256, inspect_surface


def main():
    import bpy
    import bmesh
    from array import array
    from mathutils import Matrix
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    request = json.loads(args.request.read_text(encoding="utf-8-sig"))
    output = Path(request["output"]).resolve()
    if output.exists():
        raise FileExistsError(output)
    source, root, depsgraph, objects, parts = load_geometry(request)
    original_surface = inspect_surface(objects)
    output.mkdir(parents=True)
    scene = bpy.data.scenes.new("SurfaceTransfer")
    scene.world = bpy.context.scene.world
    scene.render.engine = "CYCLES"
    scene.cycles.samples = request.get("samples", 4)
    scene.render.bake.use_clear = False
    scene.render.bake.margin = 8
    scene.render.bake.use_selected_to_active = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    snapshots = []
    for obj, part in zip(sorted(objects, key=lambda o:o.name), parts):
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph)
        clone = bpy.data.objects.new(part["id"], mesh)
        clone.matrix_world = root.matrix_world.inverted() @ obj.evaluated_get(depsgraph).matrix_world
        # 오브젝트 속성을 읽는 기존 셰이더 입력을 유지한다.
        for key in obj.keys():
            if key != "_RNA_UI":
                try:
                    clone[key] = obj[key]
                except TypeError:
                    pass
        scene.collection.objects.link(clone)
        bake_uv = mesh.uv_layers.new(name="UV_UnrealBake")
        mesh.uv_layers.active = bake_uv
        for uv in mesh.uv_layers:
            uv.active_render = uv == bake_uv
        snapshots.append(clone)
        part["material_slots"] = [m.name if m else None for m in mesh.materials]
    bpy.context.window.scene = scene
    bpy.context.scene.tool_settings.use_uv_select_sync = True
    bpy.context.scene.tool_settings.mesh_select_mode = (False,False,True)
    materials = sorted({m for obj in snapshots for m in obj.data.materials if m}, key=lambda m:m.name)
    chosen = set(request.get("materials", [m.name for m in materials]))
    if chosen - {m.name for m in materials}:
        raise ValueError("없는 베이크 재질")
    shaders = {}
    for material in materials:
        shaders[material.name] = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    for material in materials:
        if material.name not in chosen:
            continue
        bpy.ops.object.select_all(action="DESELECT")
        selected = []
        for obj in snapshots:
            found = False
            for polygon in obj.data.polygons:
                polygon.select = obj.data.materials[polygon.material_index] == material
                found |= polygon.select
            if found:
                obj.select_set(True)
                selected.append(obj)
        if not selected:
            print("UNUSED_MATERIAL_SLOT " + material.name,flush=True)
            continue
        bpy.context.view_layer.objects.active = selected[0]
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        for obj in selected:
            bm=bmesh.from_edit_mesh(obj.data)
            for face in bm.faces:
                face.select_set(obj.data.materials[face.material_index] == material)
            bmesh.update_edit_mesh(obj.data,loop_triangles=False,destructive=False)
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.005, area_weight=.5, scale_to_bounds=True)
        bpy.ops.uv.pack_islands(rotate=False, margin=.005,shape_method="CONVEX")
        bpy.ops.object.mode_set(mode="OBJECT")
        print("PACKED "+material.name,flush=True)
    metadata = {}
    channels = request.get("channels", ["base_color", "roughness", "metallic", "normal", "energy_mask", "coat"])
    for material in materials:
        shader = shaders[material.name]
        color_node = material.node_tree.nodes.get("FD_EnergyColor")
        level_node = material.node_tree.nodes.get("FD_EnergyLevel")
        strength_node = material.node_tree.nodes.get("FD_EnergyStrength")
        metadata[material.name] = {"maps": {}, "energy_color": list(color_node.outputs[0].default_value if color_node else shader.inputs["Emission Color"].default_value),
                                  "base_color": list(shader.inputs["Base Color"].default_value),
                                  "roughness": shader.inputs["Roughness"].default_value,
                                  "metallic": shader.inputs["Metallic"].default_value,
                                  "coat": shader.inputs["Coat Weight"].default_value,
                                  "energy_strength": (level_node.outputs[0].default_value*strength_node.outputs[0].default_value) if level_node and strength_node else shader.inputs["Emission Strength"].default_value,
                                  "ior": shader.inputs["IOR"].default_value, "specular": shader.inputs["Specular IOR Level"].default_value,
                                  "coat_roughness": shader.inputs["Coat Roughness"].default_value,
                                  "transmission": shader.inputs["Transmission Weight"].default_value}
    for channel in channels:
        images, targets, saved = {}, {}, {}
        for index, material in enumerate(materials):
            tree, shader = material.node_tree, shaders[material.name]
            output_node = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL")
            saved[material.name] = [(link.from_socket, link.to_socket) for link in output_node.inputs["Surface"].links]
            size = request.get("size", 1024) if material.name in chosen else 1
            image = bpy.data.images.new(f"UE_{index:02d}_{channel}", width=size, height=size, alpha=False, float_buffer=False)
            image.colorspace_settings.name = "sRGB" if channel == "base_color" else "Non-Color"
            node = tree.nodes.new("ShaderNodeTexImage")
            node.image = image
            node.select = True
            tree.nodes.active = node
            targets[material.name] = node
            images[material.name] = image
            if channel != "normal":
                emit = tree.nodes.new("ShaderNodeEmission")
                socket_name = {"base_color":"Base Color", "roughness":"Roughness", "metallic":"Metallic", "coat":"Coat Weight"}.get(channel)
                if channel == "energy_mask":
                    mask = tree.nodes.get("FD_EnergyMask")
                    if mask:
                        tree.links.new(mask.outputs[0], emit.inputs["Color"])
                    else:
                        value = 1.0 if metadata[material.name]["energy_strength"] > 0 else 0.0
                        emit.inputs["Color"].default_value = (value,value,value,1)
                else:
                    socket = shader.inputs[socket_name]
                    if socket.is_linked:
                        tree.links.new(socket.links[0].from_socket, emit.inputs["Color"])
                    else:
                        value = socket.default_value
                        emit.inputs["Color"].default_value = value if hasattr(value,"__len__") else (value,value,value,1)
                emit.name = "UE_BAKE_EMIT"
                tree.links.new(emit.outputs[0], output_node.inputs["Surface"])
        bpy.ops.object.select_all(action="DESELECT")
        selected = [obj for obj in snapshots if any(m and m.name in chosen for m in obj.data.materials)]
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = selected[0]
        bpy.ops.object.bake(type="NORMAL" if channel == "normal" else "EMIT", normal_space="TANGENT", use_clear=False)
        for index, material in enumerate(materials):
            tree = material.node_tree
            if material.name in chosen:
                path = output / f"M{index:02d}_{channel}.png"
                image = images[material.name]
                image.filepath_raw = str(path)
                image.file_format = "PNG"
                image.save()
                metadata[material.name]["maps"][channel] = path.name
            tree.nodes.remove(targets[material.name])
            emit = tree.nodes.get("UE_BAKE_EMIT")
            if emit:
                tree.nodes.remove(emit)
            for a,b in saved[material.name]:
                tree.links.new(a,b)
        (output / "progress.json").write_text(json.dumps({"completed": channel}),encoding="utf-8")
        print("BAKED " + channel, flush=True)
    # 교환용 UV0를 추가하고 기존 UV 이름과 값도 보존한다.
    for obj in snapshots:
        mesh = obj.data
        layers = []
        for uv in mesh.uv_layers:
            values = array('f', [0.0])*(len(uv.data)*2)
            uv.data.foreach_get("uv", values)
            layers.append((uv.name,values))
        layers.sort(key=lambda row:row[0] != "UV_UnrealBake")
        while mesh.uv_layers:
            mesh.uv_layers.remove(mesh.uv_layers[0])
        for name, values in layers:
            uv = mesh.uv_layers.new(name=name)
            uv.data.foreach_set("uv",values)
        mesh.uv_layers.active_index = 0
        mesh.uv_layers[0].active_render = True
        mesh.transform(obj.matrix_world)
        obj.matrix_world = Matrix.Identity(4)
    backgrounds = original_surface["world_background"]
    environment = None
    if len(backgrounds) == 1:
        background = backgrounds[0]
        image = bpy.data.images.new("UE_SourceEnvironment", width=64,height=32,alpha=False,float_buffer=True)
        rgb = [c*background["strength"] for c in background["color"][:3]]
        image.pixels.foreach_set(array('f',[*rgb,1])* (64*32))
        image.filepath_raw = str(output/"environment.hdr")
        image.file_format = "HDR"
        image.save()
        environment = "environment.hdr"
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(filepath=str(output/"geometry.fbx"), use_selection=True, object_types={"MESH"},
                            use_mesh_modifiers=False,bake_anim=False,add_leaf_bones=False,axis_forward="-Y",axis_up="Z",path_mode="AUTO")
    report = {"source":str(source),"source_sha256":request["source_sha256"],"source_unchanged":sha256(source)==request["source_sha256"],
              "root_matrix_world":[list(row) for row in root.matrix_world],
              "materials":metadata,"parts":parts,"uv0":"UV_UnrealBake","baked_materials":sorted(chosen),
              "lights":original_surface["lights"],"world_background":original_surface["world_background"],"environment":environment,
              "source_images":original_surface["images"],"color_management":original_surface["color_management"],
              "fbx":"geometry.fbx","fbx_sha256":sha256(output/"geometry.fbx"),"partial":len(chosen)!=len(materials)}
    (output/"surface.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("RESULT "+json.dumps({"materials":len(chosen),"parts":len(parts),"output":str(output),"source_unchanged":report["source_unchanged"]}),flush=True)


if __name__ == "__main__":
    main()

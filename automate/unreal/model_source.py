"""Blender 모델의 형상 정보 조사와 리그 없는 FBX 교환을 담당한다."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect_surface(objects):
    import bpy
    def value(socket):
        data = getattr(socket, "default_value", None)
        if isinstance(data, (str, float, int, bool)) or data is None:
            return data
        try:
            return list(data)
        except TypeError:
            return str(data)
    materials = {slot.material for obj in objects for slot in obj.material_slots if slot.material}
    return {"materials": {mat.name: {
        "nodes": [{"name": n.name, "type": n.bl_idname,
                   "inputs": {s.name: value(s) for s in n.inputs},
                   "properties": {key: getattr(n, key) for key in
                                  ("operation", "blend_type", "attribute_name", "uv_map", "projection", "extension") if hasattr(n, key)},
                   "image": n.image.name if n.type == "TEX_IMAGE" and n.image else None}
                  for n in mat.node_tree.nodes] if mat.use_nodes else [],
        "links": [[l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name]
                  for l in mat.node_tree.links] if mat.use_nodes else []} for mat in materials},
        "images": [{"name": im.name, "path": str(Path(bpy.path.abspath(im.filepath))),
                    "exists": Path(bpy.path.abspath(im.filepath)).is_file(), "packed": bool(im.packed_file),
                    "colorspace": im.colorspace_settings.name, "size": list(im.size)}
                   for im in bpy.data.images if im.source != "VIEWER"],
        "mesh_uvs": {obj.name: {"layers": [u.name for u in obj.data.uv_layers],
                                  "active_render": next((u.name for u in obj.data.uv_layers if u.active_render), None),
                                  "attributes": [a.name for a in obj.data.attributes if not a.name.startswith('.')],
                                  "boundary_enabled": obj.get("fd_boundary_enabled")}
                      for obj in objects},
        "lights": [{"name": obj.name, "type": obj.data.type, "energy": obj.data.energy,
                    "size": getattr(obj.data,"size",None), "size_y":getattr(obj.data,"size_y",None), "shape":getattr(obj.data,"shape",None),
                    "color": list(obj.data.color), "matrix_world": [list(row) for row in obj.matrix_world]}
                   for obj in bpy.data.objects if obj.type == "LIGHT"],
        "world_background": [{"color":list(n.inputs["Color"].default_value),"strength":n.inputs["Strength"].default_value}
                             for n in bpy.context.scene.world.node_tree.nodes if n.type=="BACKGROUND"] if bpy.context.scene.world and bpy.context.scene.world.use_nodes else [],
        "color_management": {"view_transform": bpy.context.scene.view_settings.view_transform,
                             "look": bpy.context.scene.view_settings.look,
                             "exposure": bpy.context.scene.view_settings.exposure}}


def load_geometry(request):
    import bpy
    from mathutils import Vector

    source = Path(request["source"]).resolve()
    expected = request["source_sha256"]
    if sha256(source) != expected:
        raise ValueError("모델 원본 해시 불일치")
    bpy.ops.wm.open_mainfile(filepath=str(source))
    bpy.context.scene.frame_set(request.get("frame", 1))
    root = bpy.data.objects[request["root"]]
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    inverse = root.matrix_world.inverted()
    meshes = [obj for obj in root.children_recursive if obj.type == "MESH" and not obj.hide_render]
    if "objects" in request:
        selected = request["objects"]
        if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected):
            raise ValueError("내보낼 객체는 중복 없는 이름 배열이어야 한다.")
        known = {obj.name: obj for obj in meshes}
        if set(selected) - set(known):
            raise ValueError("루트 아래의 표시 가능한 메시만 선택한다: " + str(set(selected) - set(known)))
        meshes = [known[name] for name in selected]
    parts = []
    for index, obj in enumerate(sorted(meshes, key=lambda item: item.name)):
        evaluated = obj.evaluated_get(depsgraph)
        matrix = inverse @ evaluated.matrix_world
        bounds = [matrix @ vertex.co for vertex in evaluated.data.vertices]
        if not bounds:
            raise ValueError("정점이 없는 부품: " + obj.name)
        low = [min(point[axis] for point in bounds) for axis in range(3)]
        high = [max(point[axis] for point in bounds) for axis in range(3)]
        parts.append({"id": f"FDPart_{index:04d}", "name": obj.name,
                      "min": low, "max": high,
                      "center": [(a + b) * .5 for a, b in zip(low, high)],
                      "origin": list(matrix.translation),
                      "dimensions": [b - a for a, b in zip(low, high)],
                      "vertices": len(evaluated.data.vertices),
                      "materials": [slot.material.name if slot.material else None for slot in obj.material_slots]})
        if any(token in obj.name for token in ("Internal_Axle", "Knee_Joint", "Internal_Pivot")):
            import numpy as np
            coordinates = np.array([list(point) for point in bounds])
            eigenvalues, eigenvectors = np.linalg.eigh(np.cov(coordinates.T))
            parts[-1]["geometry_principal_variances"] = eigenvalues.tolist()
            parts[-1]["geometry_principal_axes"] = eigenvectors.T.tolist()
    return source, root, depsgraph, meshes, parts


def main():
    import bpy

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    request = json.loads(args.request.read_text(encoding="utf-8-sig"))
    output = Path(request["output"]).resolve()
    if output.exists():
        raise FileExistsError(output)
    if request["operation"] == "create_sample":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        sample_root = bpy.data.objects.new("SampleRoot", None)
        bpy.context.scene.collection.objects.link(sample_root)
        for index, height in enumerate((.4, 1.2, 2.0)):
            bpy.ops.mesh.primitive_cube_add(size=.7, location=(0, 0, height))
            box = bpy.context.object
            box.name = "SamplePart_" + str(index)
            box.parent = sample_root
        output.mkdir(parents=True)
        sample_source = output / "sample_source.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(sample_source))
        request.update(operation="export_geometry", source=str(sample_source),
                       source_sha256=sha256(sample_source), root="SampleRoot")
    source, root, depsgraph, objects, parts = load_geometry(request)
    output.mkdir(parents=True, exist_ok=True)
    report = {"source": str(source), "source_sha256": request["source_sha256"],
              "root_matrix_world":[list(row) for row in root.matrix_world],
              "blender": bpy.app.version_string, "parts": parts,
              "original_armatures": len([obj for obj in bpy.data.objects if obj.type == "ARMATURE"]),
              "rig_policy": "geometry_only_no_bones_weights_constraints", "operation": request["operation"]}
    if request["operation"] == "export_geometry":
        inverse = root.matrix_world.inverted()
        snapshots = []
        for obj, part in zip(sorted(objects, key=lambda item: item.name), parts):
            evaluated = obj.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
            mesh.transform(inverse @ evaluated.matrix_world)
            snapshots.append((part["id"], mesh))
        scene = bpy.data.scenes.new("GeometryOnly")
        bpy.context.window.scene = scene
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.scale_length = 1.0
        for name, mesh in snapshots:
            obj = bpy.data.objects.new(name, mesh)
            scene.collection.objects.link(obj)
            obj.vertex_groups.clear()
            obj.select_set(True)
        bpy.context.view_layer.update()
        bpy.ops.export_scene.fbx(filepath=str(output / "geometry.fbx"), use_selection=True,
                                object_types={"MESH"}, use_mesh_modifiers=False,
                                bake_anim=False, add_leaf_bones=False,
                                axis_forward="-Y", axis_up="Z", path_mode="AUTO")
        report.update({"fbx": str(output / "geometry.fbx"), "fbx_sha256": sha256(output / "geometry.fbx"),
                       "exported_armatures": sum(obj.type == "ARMATURE" for obj in scene.objects),
                       "exported_vertex_groups": sum(len(obj.vertex_groups) for obj in scene.objects),
                       "exported_constraints": sum(len(obj.constraints) for obj in scene.objects)})
    elif request["operation"] == "inspect_surface":
        report["surface"] = inspect_surface(objects)
        if request.get("export_packed_images"):
            import shutil
            directory=output/"images"
            directory.mkdir()
            extracted=[]
            for index,image in enumerate(im for im in bpy.data.images if im.source != "VIEWER"):
                suffix=Path(image.filepath).suffix or ".png"
                filename=f"S{index:03d}_"+re.sub(r"[^A-Za-z0-9_.-]","_",image.name)+suffix
                target=directory/filename
                if image.packed_file:
                    target.write_bytes(bytes(image.packed_file.data))
                else:
                    shutil.copyfile(bpy.path.abspath(image.filepath),target)
                extracted.append({"name":image.name,"file":"images/"+filename,
                                  "sha256":sha256(target),"colorspace":image.colorspace_settings.name,
                                  "source_path":image.filepath,"packed":bool(image.packed_file)})
            report["source_images"]=extracted
    elif request["operation"] != "inspect":
        raise ValueError("지원하지 않는 모델 작업")
    if request.get("reference_render"):
        from mathutils import Vector
        config=request["reference_render"]
        scene=bpy.context.scene
        for obj in scene.objects:
            if obj.type=="MESH" and obj not in objects:
                obj.hide_render=True
        camera=bpy.data.objects.new("SurfaceReferenceCamera",bpy.data.cameras.new("SurfaceReferenceCamera"))
        scene.collection.objects.link(camera)
        camera.location=root.matrix_world @ Vector(config["position_m"])
        target=root.matrix_world @ Vector(config["target_m"])
        camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.type="ORTHO"
        root_scale=root.matrix_world.to_scale()
        if max(root_scale)-min(root_scale)>.00001:
            raise ValueError("비균일 루트 배율의 비교 카메라는 별도 보정이 필요하다.")
        camera.data.ortho_scale=config["width_m"]*root_scale.x
        scene.camera=camera
        scene.render.engine="CYCLES"
        scene.cycles.samples=32
        scene.cycles.use_denoising=True
        scene.render.resolution_x,scene.render.resolution_y=config["size"]
        scene.render.resolution_percentage=100
        scene.render.film_transparent=True
        scene.render.image_settings.file_format="PNG"
        scene.render.image_settings.color_mode="RGBA"
        scene.render.filepath=str(output/"source_reference.png")
        bpy.ops.render.render(write_still=True)
        report["reference_render"]="source_reference.png"
    report["source_unchanged"] = sha256(source) == request["source_sha256"]
    if not report["source_unchanged"]:
        raise RuntimeError("원본 모델이 변경됐다.")
    (output / "geometry.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT " + json.dumps({"operation": request["operation"], "parts": len(parts), "output": str(output), "source_unchanged": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()

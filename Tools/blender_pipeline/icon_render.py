"""기존 모델을 변경하지 않고 투명 원본 렌더와 HUD용 단색 아이콘을 출력한다."""

import argparse
import hashlib
import json
from math import cos, pi, sin
from pathlib import Path
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_icon(entry, output, evidence):
    import bpy
    from mathutils import Matrix, Vector

    source = Path(entry["source"]).resolve()
    before_hash = digest(source)
    if before_hash != entry["source_sha256"]:
        raise ValueError("아이콘 원본 모델 해시가 요청과 다르다.")
    bpy.ops.wm.open_mainfile(filepath=str(source))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    root = bpy.data.objects[entry["root_object"]]
    inverse = root.evaluated_get(depsgraph).matrix_world.inverted()
    originals = [obj for obj in (root, *root.children_recursive) if obj.type == "MESH" and not obj.hide_render]
    if not originals:
        raise ValueError("아이콘으로 출력할 메시가 없다.")
    scene = bpy.data.scenes.new("HudIconCapture")
    objects, vertices = [], []
    for original in originals:
        evaluated = original.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
        mesh.transform(inverse @ evaluated.matrix_world)
        obj = bpy.data.objects.new("Icon_" + original.name, mesh)
        scene.collection.objects.link(obj)
        objects.append(obj)
        vertices.extend(vertex.co.copy() for vertex in mesh.vertices)
    bpy.context.window.scene = scene
    backward = Vector(entry["camera_direction"]).normalized()
    up = Vector(entry.get("camera_up", [0, 0, 1]))
    up = (up - backward * up.dot(backward)).normalized()
    right = up.cross(backward).normalized()
    axes = (right, up, backward)
    low = [min(point.dot(axis) for point in vertices) for axis in axes]
    high = [max(point.dot(axis) for point in vertices) for axis in axes]
    center = sum((axis * ((a + b) / 2) for axis, a, b in zip(axes, low, high)), Vector())
    width, height = entry["size_pixels"]
    aspect = width / height
    span = max(high[0] - low[0], (high[1] - low[1]) * aspect)
    scale = span * entry.get("framing_scale", 1.1)
    camera_data = bpy.data.cameras.new("IconCamera")
    camera = bpy.data.objects.new("IconCamera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type, camera_data.sensor_fit, camera_data.ortho_scale = "ORTHO", "HORIZONTAL", scale
    camera.location = center + backward * max(2, scale * 4)
    camera.rotation_euler = Matrix((right, up, backward)).transposed().to_euler()
    scene.camera = camera
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.world = bpy.data.worlds.new("IconWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = .35
    for index, (direction, energy) in enumerate((((-2, -3, 4), 650), ((3, 2, 2), 450))):
        light_data = bpy.data.lights.new("IconLight" + str(index), "AREA")
        light = bpy.data.objects.new(light_data.name, light_data)
        scene.collection.objects.link(light)
        light.location = center + Vector(direction).normalized() * scale * 3
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
        light_data.energy, light_data.size = energy * scale * scale, scale * 2
    scene.render.engine = "CYCLES"
    scene.cycles.samples, scene.cycles.use_denoising = 16, True
    scene.view_settings.view_transform = "AgX"
    raw_path = evidence / (entry["name"] + "_source.png")
    scene.render.filepath = str(raw_path)
    bpy.ops.render.render(write_still=True)

    material = bpy.data.materials.new("HudIconPaleBlue")
    material.diffuse_color = tuple(entry.get("icon_color", [.45, .65, .72, 1]))
    for obj in objects:
        obj.data.materials.clear()
        obj.data.materials.append(material)
        for face in obj.data.polygons:
            face.material_index = 0
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.view_settings.view_transform = "Standard"
    shading = scene.display.shading
    shading.light, shading.color_type = "FLAT", "MATERIAL"
    shading.show_shadows, shading.show_cavity = True, True
    shading.cavity_type = "BOTH"
    shading.curvature_ridge_factor, shading.curvature_valley_factor = 1.4, 1.1
    shading.show_object_outline = False
    scene.display.render_aa = "32"
    if entry.get("circle"):
        disk_material = bpy.data.materials.new("IconDisk")
        disk_material.diffuse_color = (.024, .045, .057, 1)
        rim_material = bpy.data.materials.new("IconRim")
        rim_material.diffuse_color = (.45, .65, .72, 1)

        def disk(name, outer, inner, ink):
            rings = [[center - backward * scale + (right * cos(i * pi / 64) + up * sin(i * pi / 64)) * radius
                      for i in range(128)] for radius in (outer, inner)]
            points = rings[0] + rings[1]
            faces = [(i, (i + 1) % 128, (i + 1) % 128 + 128, i + 128) for i in range(128)]
            mesh = bpy.data.meshes.new(name)
            mesh.from_pydata(points, [], faces)
            mesh.materials.append(ink)
            obj = bpy.data.objects.new(name, mesh)
            scene.collection.objects.link(obj)

        disk("IconCircleBackground", scale * .45, 0, disk_material)
        disk("IconCircleRim", scale * .48, scale * .45, rim_material)
    icon_path = output / (entry["name"] + ".png")
    scene.render.filepath = str(icon_path)
    bpy.ops.render.render(write_still=True)
    if digest(source) != before_hash:
        raise RuntimeError("아이콘 원본 모델 해시가 변경됐다.")
    return {"name": entry["name"], "source": str(source), "source_sha256": before_hash,
            "root_object": root.name, "mesh_count": len(objects), "icon": str(icon_path),
            "source_render": str(raw_path), "camera_direction": list(backward), "camera_up": list(up),
            "size_pixels": [width, height], "source_unchanged": True, "model_saved": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    request = json.loads(args.request.read_text(encoding="utf-8-sig"))
    output, evidence = (Path(request[key]).resolve() for key in ("output_directory", "evidence_directory"))
    output.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    for entry in request["icons"]:
        for path in (output / (entry["name"] + ".png"), evidence / (entry["name"] + "_source.png")):
            if path.exists():
                raise FileExistsError(path)
    report = {"icons": [render_icon(entry, output, evidence) for entry in request["icons"]]}
    (output / "render_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rendered": len(report["icons"]), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

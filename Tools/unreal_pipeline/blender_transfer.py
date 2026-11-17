"""Blender 모델의 평가된 형상·본을 Unreal 교환용 사본으로 출력한다."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys


def export_model(request):
    import bpy

    source = Path(request["source"]).resolve()
    output = Path(request["output"]).resolve()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != request["source_sha256"]:
        raise ValueError("원본 해시가 요청과 다르다.")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    bpy.context.scene.frame_set(request.get("frame", 1))
    rig = bpy.data.objects[request["rig"]]
    root = bpy.data.objects[request["root"]]
    objects = [o for o in root.children_recursive if o.type == "MESH" and not o.hide_render]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    rig_eval = rig.evaluated_get(depsgraph)
    bone_map = {b.name: re.sub(r"[^A-Za-z0-9_]", "_", b.name) for b in rig.data.bones}
    if len(set(bone_map.values())) != len(bone_map):
        raise ValueError("변환한 본 이름이 중복된다.")
    matrices = {b.name: b.matrix.copy() for b in rig_eval.pose.bones}
    object_controls = request.get("object_controls", {})
    object_matrices = {name: obj.evaluated_get(depsgraph).matrix_world.copy()
                       for name in object_controls for obj in [bpy.data.objects[name]]}
    lengths = {b.name: b.length for b in rig.data.bones}
    parents = {b.name: b.parent.name if b.parent else None for b in rig.data.bones}
    rig_world = rig_eval.matrix_world.copy()

    def rigid_binding(obj, visited=None):
        visited = set() if visited is None else visited
        if obj is None or obj.name in visited or obj == root:
            return "Root"
        visited.add(obj.name)
        if obj.name in object_controls:
            return object_controls[obj.name]
        if obj.parent_type == "BONE" and obj.parent == rig:
            return bone_map[obj.parent_bone]
        evaluated = obj.evaluated_get(depsgraph)
        for constraint in reversed(list(evaluated.constraints)):
            target = getattr(constraint, "target", None)
            if constraint.influence > .999 and target is not None:
                subtarget = getattr(constraint, "subtarget", "")
                if target.original == rig and subtarget:
                    return bone_map[subtarget]
                return rigid_binding(target.original, visited)
        return rigid_binding(obj.parent, visited)

    snapshots = []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True,
                                              depsgraph=depsgraph)
        groups = [g.name for g in obj.vertex_groups]
        is_skinned = any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers)
        snapshots.append((obj.name, mesh, evaluated.matrix_world.copy(), groups,
                          None if is_skinned else rigid_binding(obj)))

    scene = bpy.data.scenes.new("UnrealTransfer")
    bpy.context.window.scene = scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    data = bpy.data.armatures.new("TransferSkeleton")
    transfer_rig = bpy.data.objects.new("MechSkeleton", data)
    scene.collection.objects.link(transfer_rig)
    transfer_rig.matrix_world = rig_world
    bpy.context.view_layer.objects.active = transfer_rig
    transfer_rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root_bone = data.edit_bones.new("Root")
    root_bone.head, root_bone.tail = (0, 0, 0), (0, .1, 0)
    for original, name in bone_map.items():
        bone = data.edit_bones.new(name)
        bone.matrix = matrices[original]
        bone.length = lengths[original]
    for original, name in bone_map.items():
        data.edit_bones[name].parent = data.edit_bones[bone_map[parents[original]]] if parents[original] else root_bone
    helper_matrices = {}
    for original, name in object_controls.items():
        if name in data.edit_bones:
            raise ValueError("교환용 객체 본 이름 중복: " + name)
        matrix = rig_world.inverted() @ object_matrices[original]
        normalized = matrix.to_quaternion().to_matrix().to_4x4()
        normalized.translation = matrix.translation
        bone = data.edit_bones.new(name)
        bone.matrix, bone.length, bone.parent = normalized, .1, root_bone
        helper_matrices[original] = [list(row) for row in normalized]
    bpy.ops.object.mode_set(mode="OBJECT")
    bindings = {}
    transferred = []
    for name, mesh, world, groups, rigid_bone in snapshots:
        obj = bpy.data.objects.new(name + "_Transfer", mesh)
        scene.collection.objects.link(obj)
        obj.matrix_world = world
        if rigid_bone:
            obj.vertex_groups.clear()
            group = obj.vertex_groups.new(name=rigid_bone)
            group.add(list(range(len(mesh.vertices))), 1.0, "REPLACE")
            bindings[name] = rigid_bone
        else:
            # Blender 5.2의 평가 메시에는 그룹 이름도 복사된다. 새 그룹을
            # 덧붙이지 않고 기존 인덱스의 이름을 본 이름과 함께 변환한다.
            if not obj.vertex_groups:
                for group_name in groups:
                    obj.vertex_groups.new(name=group_name)
            if [g.name for g in obj.vertex_groups] != groups:
                raise ValueError(f"{name}: 평가 메시의 가중치 그룹 순서가 원본과 다르다.")
            for group in obj.vertex_groups:
                group.name = bone_map.get(group.name, group.name)
            actual_groups = [g.name for g in obj.vertex_groups]
            unweighted = [v.index for v in mesh.vertices if not any(
                g.weight > 0 and actual_groups[g.group] in data.bones for g in v.groups)]
            if unweighted:
                raise ValueError(f"{name}: 유효한 본 가중치가 없는 정점 {len(unweighted)}개")
        modifier = obj.modifiers.new("TransferSkin", "ARMATURE")
        modifier.object = transfer_rig
        obj.select_set(True)
        transferred.append(obj)
    bpy.context.view_layer.update()
    # 교환용 작업본에서만 원본 장면을 제거한다. 디스크의 원본은 저장하지 않는다.
    owned = set(transferred + [transfer_rig])
    for obj in list(bpy.data.objects):
        if obj not in owned:
            bpy.data.objects.remove(obj, do_unlink=True)
    for other in list(bpy.data.scenes):
        if other != scene:
            bpy.data.scenes.remove(other)
    for image in bpy.data.images:
        if image.source == "FILE" and not image.packed_file:
            image.pack()
    scene.frame_start, scene.frame_end = 0, 30
    scene.render.fps = 30
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "transfer.blend"))
    bpy.ops.export_scene.fbx(filepath=str(output / "mech.fbx"), use_selection=True,
        object_types={"ARMATURE", "MESH"}, add_leaf_bones=False,
        bake_anim=False, use_armature_deform_only=False, use_mesh_modifiers=False,
        axis_forward="-Y", axis_up="Z", path_mode="COPY", embed_textures=False)
    report = {"source": str(source), "source_sha256": source_hash,
              "blender": bpy.app.version_string, "bone_map": bone_map,
              "synthetic_root": "Root", "rig_world": [list(row) for row in rig_world],
              "source_pose_matrices": {k: [list(row) for row in v] for k, v in matrices.items()},
              "rigid_bindings": bindings, "meshes": len(transferred), "bones": len(data.bones),
              "fbx_sha256": hashlib.sha256((output / "mech.fbx").read_bytes()).hexdigest(),
              "object_controls": object_controls,
              "object_bind_world": {k: [list(row) for row in v] for k, v in object_matrices.items()},
              "helper_pose_matrices": helper_matrices,
              "status": "exported_unchecked",
              "limitations": ["명시한 객체 제어 외의 가동 부품·형상은 출력 시점으로 고정",
                              "재질의 Unreal 표시와 왕복 변환은 별도 검증"]}
    (output / "transfer_map.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    print("RESULT " + json.dumps({"meshes": len(transferred), "bones": len(data.bones),
                                  "output": str(output)}))


def import_animation(request):
    import bpy
    from mathutils import Matrix

    source = Path(request["source"]).resolve()
    output = Path(request["output_blend"]).resolve()
    mapping = json.loads(Path(request["transfer_map"]).read_text(encoding="utf-8"))
    if hashlib.sha256(source.read_bytes()).hexdigest() != mapping["source_sha256"]:
        raise ValueError("원본이 교환용 출력 당시와 다르다.")
    if output.exists():
        raise FileExistsError(output)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    rig = bpy.data.objects[request["rig"]]
    source_objects = set(bpy.data.objects)
    original_modes = {b.name: b.rotation_mode for b in rig.pose.bones}
    bpy.ops.import_scene.fbx(filepath=str(Path(request["fbx"]).resolve()), use_anim=True, anim_offset=0)
    imported = [o for o in bpy.data.objects if o not in source_objects]
    imported_rigs = [o for o in imported if o.type == "ARMATURE"]
    if len(imported_rigs) != 1:
        raise ValueError("반환 FBX의 Armature가 하나가 아니다.")
    incoming = imported_rigs[0]
    bone_map = mapping["bone_map"]
    missing = [name for name in bone_map.values() if name not in incoming.pose.bones]
    if missing:
        raise ValueError("반환 FBX의 본이 누락됐다: " + repr(missing))
    start, end = request.get("frame_start", 0), request.get("frame_end", 30)
    bpy.context.scene.frame_set(start)
    source_world = Matrix(mapping["rig_world"])
    incoming_world = incoming.matrix_world.copy()
    corrections = {name: (incoming_world @ incoming.data.bones[external].matrix_local).inverted()
                   @ source_world @ Matrix(mapping["source_pose_matrices"][name])
                   for name, external in bone_map.items()}
    targets = {}
    for frame in range(start, end + 1):
        bpy.context.scene.frame_set(frame)
        evaluated = incoming.evaluated_get(bpy.context.evaluated_depsgraph_get())
        targets[frame] = {name: source_world.inverted() @ evaluated.matrix_world
                         @ evaluated.pose.bones[external].matrix @ corrections[name]
                         for name, external in bone_map.items()}
    action = bpy.data.actions.new(request.get("action_name", "Unreal_Return"))
    action.use_fake_user = True
    rig.animation_data_create().action = action
    for frame, pose in targets.items():
        bpy.context.scene.frame_set(frame)
        for name, matrix in pose.items():
            bone = rig.pose.bones[name]
            options = {"invert": True}
            if bone.parent:
                options.update(parent_matrix=pose[bone.parent.name],
                               parent_matrix_local=bone.parent.bone.matrix_local)
            bone.matrix_basis = bone.bone.convert_local_to_pose(matrix, bone.bone.matrix_local, **options)
            bone.keyframe_insert("location", frame=frame, group=name)
            channel = ("rotation_quaternion" if bone.rotation_mode == "QUATERNION" else
                       "rotation_axis_angle" if bone.rotation_mode == "AXIS_ANGLE" else "rotation_euler")
            bone.keyframe_insert(channel, frame=frame, group=name)
            bone.keyframe_insert("scale", frame=frame, group=name)
    errors = []
    for frame in sorted({start, (start + end) // 2, end}):
        bpy.context.scene.frame_set(frame)
        evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for name, target in targets[frame].items():
            actual = evaluated.pose.bones[name].matrix
            errors.append({"frame": frame, "bone": name,
                           "position_error": (actual.translation - target.translation).length,
                           "angle_error": orientation_error(actual, target)})
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end, scene.render.fps = start, end, 30
    scene.frame_set(start)
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    report = {"source_sha256": mapping["source_sha256"], "output_blend": str(output),
              "action": action.name, "frames": [start, end], "mapped_bones": len(bone_map),
              "rotation_modes_preserved": original_modes == {b.name: b.rotation_mode for b in rig.pose.bones},
              "constraints_preserved": sum(len(b.constraints) for b in rig.pose.bones),
              "max_position_error": max(e["position_error"] for e in errors),
              "max_angle_error": max(e["angle_error"] for e in errors),
              "largest_errors": sorted(errors, key=lambda e: e["position_error"], reverse=True)[:5],
              "status": "returned_candidate_visual_review_pending",
              "user_edit_status": request.get("user_edit_status", "not_recorded")}
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == mapping["source_sha256"]
    print("RESULT " + json.dumps(report))


def orientation_error(actual, expected):
    difference = actual.to_quaternion().rotation_difference(expected.to_quaternion()).normalized()
    return 2 * math.atan2(math.sqrt(difference.x ** 2 + difference.y ** 2 + difference.z ** 2), abs(difference.w))


def verify_return(request):
    import bpy
    from mathutils import Matrix
    mapping = json.loads(Path(request["transfer_map"]).read_text(encoding="utf-8"))
    output = Path(request["output_blend"]).resolve()
    bpy.ops.wm.open_mainfile(filepath=str(output))
    rig = bpy.data.objects[request["rig"]]
    source_names = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(Path(request["fbx"]).resolve()), use_anim=True, anim_offset=0)
    incoming = next(o for o in bpy.data.objects if o not in source_names and o.type == "ARMATURE")
    scene = bpy.context.scene
    scene.frame_set(0)
    source_world = Matrix(mapping["rig_world"])
    correction = {name: (incoming.matrix_world @ incoming.data.bones[external].matrix_local).inverted()
                  @ source_world @ Matrix(mapping["source_pose_matrices"][name])
                  for name, external in mapping["bone_map"].items()}
    errors = []
    for frame in [*range(31), 7.5, 22.5]:
        scene.frame_set(int(frame), subframe=frame % 1)
        graph = bpy.context.evaluated_depsgraph_get()
        imported, target = incoming.evaluated_get(graph), rig.evaluated_get(graph)
        for name, external in mapping["bone_map"].items():
            expected = source_world.inverted() @ imported.matrix_world @ imported.pose.bones[external].matrix @ correction[name]
            actual = target.pose.bones[name].matrix
            errors.append({"frame": frame, "bone": name,
                "position": (actual.translation - expected.translation).length,
                "angle": orientation_error(actual, expected)})
    report = {"reloaded_blend": str(output), "samples": len(errors),
              "max_position_error_rig_units": max(e["position"] for e in errors),
              "max_angle_error_radians": max(e["angle"] for e in errors),
              "worst_position": max(errors, key=lambda e: e["position"]),
              "worst_angle": max(errors, key=lambda e: e["angle"]),
              "source_hash_unchanged": hashlib.sha256(Path(request["source"]).read_bytes()).hexdigest() == mapping["source_sha256"]}
    output.with_suffix(".verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT " + json.dumps(report))


def create_sample(request):
    import bpy
    output = Path(request["output"]).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = bpy.data.objects.new("SampleRoot", None)
    bpy.context.scene.collection.objects.link(root)
    data = bpy.data.armatures.new("SampleSkeleton")
    rig = bpy.data.objects.new("SampleRig", data)
    bpy.context.scene.collection.objects.link(rig)
    rig.parent = root
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    pelvis = data.edit_bones.new("Pelvis")
    pelvis.head, pelvis.tail = (0, 0, 0), (0, 0, 1)
    chest = data.edit_bones.new("Chest")
    chest.head, chest.tail, chest.parent = (0, 0, 1), (0, 0, 2), pelvis
    arm = data.edit_bones.new("Arm.L")
    arm.head, arm.tail, arm.parent = (0, 0, 1.5), (1, 0, 1.5), chest
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, location, size, color in [
        ("Pelvis", (0, 0, .5), (.7, .5, .9), (.18, .28, .42, 1)),
        ("Chest", (0, 0, 1.5), (1.0, .5, .9), (.72, .44, .12, 1)),
        ("Arm.L", (.9, 0, 1.5), (.8, .3, .3), (.3, .65, .35, 1))]:
        bpy.ops.mesh.primitive_cube_add(size=1, location=location)
        cube = bpy.context.object
        cube.name = "Sample_" + name
        cube.scale = size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        cube.parent = root
        group = cube.vertex_groups.new(name=name)
        group.add(list(range(8)), 1.0, "REPLACE")
        cube.modifiers.new("Skin", "ARMATURE").object = rig
        material = bpy.data.materials.new("Sample_" + name)
        material.diffuse_color = color
        cube.data.materials.append(material)
    if request.get("include_prop"):
        from mathutils import Matrix
        prop = bpy.data.objects.new("SampleProp", None)
        bpy.context.scene.collection.objects.link(prop)
        prop.parent, prop.parent_type, prop.parent_bone = rig, "BONE", "Arm.L"
        bpy.context.view_layer.update()
        prop.matrix_world = Matrix.Translation((1.4, 0, 1.5))
        bpy.ops.mesh.primitive_cube_add(size=.2,location=(1.4,0,1.5))
        cube = bpy.context.object
        cube.name, cube.parent = "SampleProp_Mesh", prop
        cube.matrix_world = Matrix.Translation((1.4, 0, 1.5))
    source = output / "sample.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    export_request = {"source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "root": root.name, "rig": rig.name, "output": str(output / "transfer")}
    if request.get("include_prop"):
        export_request["object_controls"] = {"SampleProp":"FD_Prop"}
    (output / "export_request.json").write_text(json.dumps(export_request, indent=2), encoding="utf-8")
    export_model(export_request)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    request = json.loads(args.request.read_text(encoding="utf-8-sig"))
    if request.get("operation", "export_model") == "import_animation":
        import_animation(request)
    elif request.get("operation") == "verify_return":
        verify_return(request)
    elif request.get("operation") == "create_sample":
        create_sample(request)
    elif request.get("operation") in {"prepare_batch", "import_batch", "verify_batch", "review_batch"}:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from sequence_batch import run
        run(request)
    else:
        export_model(request)


if __name__ == "__main__":
    main()

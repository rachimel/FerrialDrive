"""부모 본 회전의 하위 본·스킨 전달을 사본 프로세스에서 검사한다. 파일은 저장하지 않는다."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


def check(source, bone_name="Chest", axis="Z", degrees=30):
    import bpy
    from mathutils import Matrix
    source = Path(source).resolve()
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source.suffix.lower() == ".fbx":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    else:
        bpy.ops.wm.open_mainfile(filepath=str(source))
    rigs = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if len(rigs) != 1 or bone_name not in rigs[0].pose.bones:
        raise ValueError("대상 본을 포함하는 Armature가 하나여야 한다.")
    rig = rigs[0]
    affected = {bone_name, *[bone.name for bone in rig.data.bones[bone_name].children_recursive]}
    objects = [obj for obj in bpy.data.objects if obj.type == "MESH" and not obj.hide_render
               and any(mod.type == "ARMATURE" and mod.object == rig for mod in obj.modifiers)]
    before, indices, invalid, weighted = {}, {}, [], set()

    def mesh_data(obj):
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        groups = [{obj.vertex_groups[g.group].name for g in vertex.groups if g.weight > .001}
                  for vertex in mesh.vertices]
        evaluated.to_mesh_clear()
        return points, groups

    for obj in objects:
        points, groups = mesh_data(obj)
        for names in groups:
            weighted.update(names)
        unknown = set().union(*groups) - set(rig.data.bones.keys()) if groups else set()
        invalid.extend({"mesh": obj.name, "group": name} for name in sorted(unknown))
        indices[obj.name] = [i for i, names in enumerate(groups) if names and names <= affected]
        before[obj.name] = points
    parent_before = rig.matrix_world @ rig.pose.bones[bone_name].matrix
    rig.pose.bones[bone_name].matrix_basis = rig.pose.bones[bone_name].matrix_basis @ Matrix.Rotation(math.radians(degrees), 4, axis)
    bpy.context.view_layer.update()
    delta = (rig.matrix_world @ rig.pose.bones[bone_name].matrix) @ parent_before.inverted()
    errors, moves = [], []
    for obj in objects:
        after, _ = mesh_data(obj)
        if len(before[obj.name]) != len(after):
            raise ValueError("검사 중 정점 수가 바뀌었다.")
        for index in indices[obj.name]:
            errors.append((after[index] - delta @ before[obj.name][index]).length)
            moves.append((after[index] - before[obj.name][index]).length)
    result = {"source": str(source), "bone": bone_name, "axis": axis, "degrees": degrees,
              "weighted_bone_groups": sorted(weighted), "invalid_groups": invalid,
              "pure_descendant_vertices": len(errors), "affected_bones": len(affected),
              "max_position_error_world": max(errors, default=None), "max_vertex_move_world": max(moves, default=0),
              "source_hash_unchanged": hashlib.sha256(source.read_bytes()).hexdigest() == original_hash}
    result["passed"] = bool(errors) and not invalid and max(errors) < 1e-5 and max(moves) > 1e-4 and result["source_hash_unchanged"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bone", default="Chest")
    parser.add_argument("--axis", choices=("X", "Y", "Z"), default="Z")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.output.exists():
        raise FileExistsError(args.output)
    result = check(args.source, args.bone, args.axis)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("RESULT " + json.dumps(result))
    if not result["passed"]:
        raise RuntimeError("본 이름 매핑 또는 부모 회전 추종 검사 실패")


if __name__ == "__main__":
    main()

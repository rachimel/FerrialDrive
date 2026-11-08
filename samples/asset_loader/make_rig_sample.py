"""Blender에서 기본 도형·단일 본 키프레임 샘플을 생성한다. 게임 모델은 사용하지 않는다."""

import argparse
from pathlib import Path
import sys

import bpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.object.armature_add(location=(0, 0, 0))
    rig = bpy.context.object
    rig.name = "SampleRig"
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.7))
    mesh = bpy.context.object
    mesh.name = "SampleBody"
    mesh.scale = (0.45, 0.35, 0.65)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    material = bpy.data.materials.new("SampleBlue")
    material.diffuse_color = (0.15, 0.55, 0.75, 1)
    mesh.data.materials.append(material)
    mesh.parent = rig
    group = mesh.vertex_groups.new(name=rig.data.bones[0].name)
    group.add(list(range(len(mesh.data.vertices))), 1, "REPLACE")
    modifier = mesh.modifiers.new("SampleArmature", "ARMATURE")
    modifier.object = rig
    bone = rig.pose.bones[0]
    for frame, offset in ((1, 0), (3, 0.3), (5, 0)):
        bone.location.x = offset
        bone.keyframe_insert(data_path="location", frame=frame)
    bpy.context.scene.frame_set(1)
    target = args.output.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(target))


if __name__ == "__main__":
    main()

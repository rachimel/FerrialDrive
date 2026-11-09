"""메카 에셋 없이 사용하는 기본 도형 리그. Blender에서 실행한다."""

import math
import bpy
from mathutils import Vector


def create_sample():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    data = bpy.data.armatures.new("SampleSkeleton")
    rig = bpy.data.objects.new("PlayerRigidRig", data)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    definitions = [
        ("Pelvis", (0, 0, 1.5), (0, 0, 1.7), None),
        ("Waist", (0, 0, 1.7), (0, 0, 1.9), "Pelvis"),
        ("Chest", (0, 0, 1.9), (0, 0, 2.5), "Waist"),
        ("Head", (0, 0, 2.5), (0, 0, 2.9), "Chest"),
    ]
    for side, sign in (("L", 1), ("R", -1)):
        definitions.extend([
            (f"ShoulderWingLower.{side}", (0, sign*.35, 2.4), (0, sign*.55, 2.4), "Chest"),
            (f"UpperArm.{side}", (0, sign*.55, 2.4), (.10, sign*.85, 1.95), f"ShoulderWingLower.{side}"),
            (f"Forearm.{side}", (.10, sign*.85, 1.95), (.0, sign*1.0, 1.5), f"UpperArm.{side}"),
            (f"WristSwivel.{side}", (.0, sign*1.0, 1.5), (.0, sign*1.02, 1.45), f"Forearm.{side}"),
            (f"Hand.{side}", (.0, sign*1.0, 1.5), (.0, sign*1.08, 1.3), f"WristSwivel.{side}"),
            (f"Thigh.{side}", (0, sign*.25, 1.5), (.13, sign*.27, .85), "Pelvis"),
            (f"Shin.{side}", (.13, sign*.27, .85), (0, sign*.27, .15), f"Thigh.{side}"),
            (f"Foot.{side}", (0, sign*.27, .15), (.3, sign*.27, .1), f"Shin.{side}"),
        ])
        for index, finger in enumerate(("Thumb", "Index", "Middle", "Ring", "Little")):
            parent = f"Hand.{side}"
            for joint in range(3):
                suffix = ("Base", "01", "02")[joint] if finger == "Thumb" else f"{joint+1:02}"
                name = f"{finger}{suffix}.{side}"
                x = (index-2)*.045
                definitions.append((name, (x, sign*1.08, 1.32-joint*.07),
                                    (x, sign*1.09, 1.25-joint*.07), parent))
                parent = name
    for name, head, tail, parent in definitions:
        bone = data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        if parent:
            bone.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, head, tail, _ in definitions:
        a, b = Vector(head), Vector(tail)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(a+b)/2)
        obj = bpy.context.object
        obj.name = "Sample_" + name
        width = .22 if name.startswith(("Thigh", "Shin")) else .17
        if name.startswith(("Thumb", "Index", "Middle", "Ring", "Little")):
            width = .025
        elif name.startswith("WristSwivel"):
            width = .09
        if name == "Chest":
            width = .6
        obj.scale = (width, width, (b-a).length*.9)
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = Vector((0, 0, 1)).rotation_difference((b-a).normalized())
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        mat = bpy.data.materials.new("Sample_" + name)
        mat.diffuse_color = (.35, .58, .68, 1) if name.endswith(".L") else (.60, .37, .30, 1)
        obj.data.materials.append(mat)
        world = obj.matrix_world.copy()
        obj.parent, obj.parent_type, obj.parent_bone = rig, "BONE", name
        bpy.context.view_layer.update()
        obj.matrix_world = world
    for start, label in ((1, "sample_idle"), (31, "sample_reach"), (61, "sample_crouch")):
        bpy.context.scene.timeline_markers.new(label, frame=start)
        for frame in range(start, start+24):
            phase = math.sin((frame-start)/23 * math.pi)
            for bone in rig.pose.bones:
                bone.rotation_mode = "QUATERNION"
                bone.rotation_quaternion.identity()
                bone.location = (0, 0, 0)
            if start == 31:
                from mathutils import Quaternion
                rig.pose.bones["UpperArm.R"].rotation_quaternion = Quaternion((1, 0, 0), phase*.5)
                rig.pose.bones["Forearm.R"].rotation_quaternion = Quaternion((1, 0, 0), phase*.7)
            if start == 61:
                rig.pose.bones["Pelvis"].location.y = -.1 * phase
            for bone in rig.pose.bones:
                for channel in ("location", "rotation_quaternion", "scale"):
                    bone.keyframe_insert(channel, frame=frame)
    equipment = bpy.data.objects.new("BasicWeapons", None)
    bpy.context.collection.objects.link(equipment)
    equipment["sword_stowed"] = 1.0
    equipment["gun_stowed"] = 1.0
    equipment.hide_select = True
    def box(name, parent, location, size, color):
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.object
        obj.name, obj.parent, obj.location, obj.scale = name, parent, location, size
        mat = bpy.data.materials.new(name+"_Color")
        mat.diffuse_color = (*color, 1)
        obj.data.materials.append(mat)
    roots = {}
    for name, location in (("Gun", (.55, -.45, 1.9)), ("Sword", (.65, .48, 1.8)), ("Scabbard", (-.4, .48, 1.8))):
        obj = bpy.data.objects.new(name, None)
        bpy.context.collection.objects.link(obj)
        obj.location = location
        roots[name] = obj
    box("SampleGun", roots["Gun"], (0, 0, 0), (.42, .16, .2), (.3, .4, .45))
    box("SampleGunGrip", roots["Gun"], (-.12, 0, -.15), (.1, .1, .16), (.18, .25, .28))
    box("SampleBlade", roots["Sword"], (0, 0, -.34), (.07, .025, .68), (.5, .7, .8))
    box("SampleGuard", roots["Sword"], (0, 0, 0), (.22, .1, .05), (.3, .45, .5))
    box("SampleGrip", roots["Sword"], (0, 0, .1), (.07, .07, .16), (.25, .3, .35))
    for sign in (-1, 1):
        box("SampleSheathWall"+str(sign), roots["Scabbard"], (0, sign*.045, -.36), (.12, .045, .75), (.55, .42, .24))
    anchor = bpy.data.objects.new("Sword_StowAnchor", None)
    bpy.context.collection.objects.link(anchor)
    anchor.location = roots["Scabbard"].location
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end, scene.render.fps = 1, 84, 12
    scene.frame_set(1)
    return rig

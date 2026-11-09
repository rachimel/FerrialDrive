"""Blender 포즈 패널 등록과 뷰포트 초기화."""

from .native import register, unregister, configure_scene


def configure_view():
    import bpy
    from mathutils import Vector
    from . import scene as engine
    if bpy.context.window and bpy.context.window.workspace.name != "Layout" and "Layout" in bpy.data.workspaces:
        bpy.context.window.workspace = bpy.data.workspaces["Layout"]
        bpy.app.timers.register(configure_view, first_interval=.1)
        return
    rig, _ = engine.rig_objects()
    points = [rig.matrix_world @ bone.head for bone in rig.pose.bones]
    low = Vector(tuple(min(point[i] for point in points) for i in range(3)))
    high = Vector(tuple(max(point[i] for point in points) for i in range(3)))
    screens = [bpy.context.window.screen] if bpy.context.window else []
    for screen in screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            space.show_region_ui = True
            space.shading.type = "SOLID"
            space.shading.light = "STUDIO"
            space.shading.color_type = "MATERIAL"
            space.overlay.show_relationship_lines = False
            space.show_gizmo = True
            space.show_gizmo_object_translate = False
            space.show_gizmo_object_rotate = bpy.context.scene.fd_pose_transform == "rotate"
            space.region_3d.view_location = (low+high)*.5
            space.region_3d.view_distance = max((high-low).length*1.4, 2)
            space.region_3d.view_rotation = Vector((6, -8, 3)).to_track_quat("Z", "Y")
            space.region_3d.view_perspective = "ORTHO"

"""실제 관절 위치의 굽힘 손잡이와 굵은 월드 이동 화살표."""

import bpy
from bpy.props import StringProperty
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector
from . import scene as engine
from .part_editing import PartEditing


class BendJoint(bpy.types.Operator):
    bl_idname = "fdpose.bend_drag"
    bl_label = "관절 굽힘 방향"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}
    target: StringProperty()

    def invoke(self, context, event):
        from .native import select_part
        select_part(context, self.target)
        parts = PartEditing(initialize=False)
        self.before = parts.world(self.target)
        self.origin = parts.joint_position(self.target)
        point = (event.mouse_region_x, event.mouse_region_y)
        self.start = view3d_utils.region_2d_to_location_3d(context.region, context.region_data, point, self.origin)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        parts = PartEditing(initialize=False)
        if event.type in {"ESC", "RIGHTMOUSE"}:
            parts.set_world(self.target, self.before)
            context.workspace.status_text_set(None)
            context.area.tag_redraw()
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            from .native import key_all
            key_all(parts)
            context.workspace.status_text_set(None)
            return {"FINISHED"}
        if event.type == "MOUSEMOVE":
            point = (event.mouse_region_x, event.mouse_region_y)
            location = view3d_utils.region_2d_to_location_3d(context.region, context.region_data, point, self.origin)
            try:
                parts.bend_joint(self.target, self.origin+location-self.start)
            except ValueError as error:
                context.workspace.status_text_set(str(error))
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}


class JointHandles(bpy.types.GizmoGroup):
    bl_idname = "FDPOSE_GGT_joints"
    bl_label = "포즈 관절"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT", "SHOW_MODAL_ALL"}

    @classmethod
    def poll(cls, context):
        return engine.STATE in context.scene and context.mode in {"OBJECT", "POSE"}

    def setup(self, context):
        self.handles = {}
        for key in engine.controls():
            if not key.startswith("pole."):
                continue
            gizmo = self.gizmos.new("GIZMO_GT_move_3d")
            gizmo.draw_style = "RING_2D"
            gizmo.color = (.30, .74, .90) if key.endswith(".L") else (.92, .52, .41)
            gizmo.alpha = .85
            gizmo.color_highlight = (1, 1, .4)
            gizmo.alpha_highlight = 1
            gizmo.line_width = 3
            gizmo.scale_basis = .12
            gizmo.use_draw_modal = True
            gizmo.target_set_operator("fdpose.bend_drag").target = key
            self.handles[key] = gizmo

    def draw_prepare(self, context):
        parts = PartEditing(initialize=False)
        worlds = engine.world_bones(parts.rig)
        limbs = engine.state()["profile"]["limbs"]
        for key, gizmo in self.handles.items():
            gizmo.matrix_basis = Matrix.Translation(worlds[limbs[key.removeprefix("pole.")]["lower"]].translation)


class WorldArrows(bpy.types.GizmoGroup):
    bl_idname = "FDPOSE_GGT_world_axes"
    bl_label = "포즈 월드 축 이동"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        return engine.STATE in context.scene and context.mode in {"OBJECT", "POSE"}

    def setup(self, context):
        self.arrows = []
        for i, color in enumerate(((.95, .24, .20), (.30, .85, .28), (.25, .53, 1))):
            gizmo = self.gizmos.new("GIZMO_GT_arrow_3d")
            gizmo.draw_style = "NORMAL"
            gizmo.line_width = 3
            gizmo.color = gizmo.color_highlight = color
            gizmo.alpha, gizmo.alpha_highlight = .9, 1
            op = gizmo.target_set_operator("transform.translate")
            op.orient_type = "GLOBAL"
            op.constraint_axis = tuple(j == i for j in range(3))
            self.arrows.append(gizmo)

    def draw_prepare(self, context):
        from .native import current_key
        key = current_key(context)
        valid = context.view_layer.objects.active is not None and not key.startswith("pole.")
        parts = PartEditing(initialize=False)
        for i, gizmo in enumerate(self.arrows):
            gizmo.hide = not valid or context.scene.fd_pose_transform != "translate"
            if not gizmo.hide:
                direction = Vector(tuple(int(j == i) for j in range(3)))
                gizmo.matrix_basis = direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
                gizmo.matrix_basis.translation = parts.world(key).translation


CLASSES = (BendJoint, JointHandles, WorldArrows)

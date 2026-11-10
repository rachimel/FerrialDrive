"""실제 관절 위치의 굽힘 손잡이와 굵은 월드 이동 화살표."""

import bpy
from bpy.props import StringProperty
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector
from . import scene as engine
from .part_editing import PartEditing, CORE_LABELS


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
        self.twists = {}
        self.uppers = {}
        for key in engine.controls():
            if key.startswith("upper."):
                gizmo = self.gizmos.new("GIZMO_GT_move_3d")
                gizmo.draw_style = "RING_2D"
                gizmo.color = (.30, .74, .90) if key.endswith(".L") else (.92, .52, .41)
                gizmo.alpha, gizmo.alpha_highlight = .85, 1
                gizmo.color_highlight = (1, 1, .4)
                gizmo.line_width, gizmo.scale_basis = 4, .10
                op = gizmo.target_set_operator("fdpose.command")
                op.command, op.target = "select", key
                self.uppers[key] = gizmo
            if not key.startswith("pole."):
                continue
            gizmo = self.gizmos.new("GIZMO_GT_move_3d")
            gizmo.draw_style = "RING_2D"
            gizmo.color = (.30, .74, .90) if key.endswith(".L") else (.92, .52, .41)
            gizmo.alpha = .85
            gizmo.color_highlight = (1, 1, .4)
            gizmo.alpha_highlight = 1
            gizmo.line_width = 4
            gizmo.scale_basis = .18
            gizmo.use_draw_modal = True
            gizmo.target_set_operator("fdpose.joint_drag").target = key
            self.handles[key] = gizmo
            twist = self.gizmos.new("GIZMO_GT_move_3d")
            twist.draw_style = "RING_2D"
            twist.color, twist.color_highlight = (.68, .52, .95), (1, 1, .4)
            twist.alpha, twist.alpha_highlight = .8, 1
            twist.line_width, twist.scale_basis = 3, .36
            twist.use_draw_modal = True
            twist.target_set_operator("fdpose.twist_drag").target = key
            self.twists[key] = twist

    def draw_prepare(self, context):
        parts = PartEditing(initialize=False)
        worlds = engine.world_bones(parts.rig)
        limbs = engine.state()["profile"]["limbs"]
        for key, gizmo in self.handles.items():
            gizmo.matrix_basis = Matrix.Translation(worlds[limbs[key.removeprefix("pole.")]["lower"]].translation)
            self.twists[key].matrix_basis = gizmo.matrix_basis
        for key, gizmo in self.uppers.items():
            limb = limbs[key.removeprefix("upper.")]
            position = worlds[limb["upper"]].translation.lerp(worlds[limb["lower"]].translation, .45)
            gizmo.matrix_basis = Matrix.Translation(position)


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
        valid = context.view_layer.objects.active is not None and not key.startswith(("pole.", "upper."))
        parts = PartEditing(initialize=False)
        for i, gizmo in enumerate(self.arrows):
            gizmo.hide = not valid or context.scene.fd_pose_transform != "translate"
            if not gizmo.hide:
                direction = Vector(tuple(int(j == i) for j in range(3)))
                gizmo.matrix_basis = direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
                gizmo.matrix_basis.translation = parts.world(key).translation


class BendLimb(bpy.types.Operator):
    bl_idname = "fdpose.joint_drag"
    bl_label = "팔꿈치·무릎 굽힘 각도"
    bl_description = "좌우로 끌어 굽힘 각도를 조절한다. 손 또는 발이 함께 움직인다"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}
    target: StringProperty()

    def invoke(self, context, event):
        from .native import select_part
        select_part(context, self.target)
        parts = PartEditing(initialize=False)
        self.before = parts.joint_pose(self.target)
        self.start_angle = parts.joint_angle(self.target)
        self.start_x = event.mouse_x
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        parts = PartEditing(initialize=False)
        if event.type in {"ESC", "RIGHTMOUSE"}:
            parts.restore_joint_pose(self.target, self.before)
            context.workspace.status_text_set(None)
            context.area.tag_redraw()
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            from .native import key_all
            key_all(parts)
            context.workspace.status_text_set(None)
            return {"FINISHED"}
        if event.type == "MOUSEMOVE":
            degrees = max(-179.9, min(179.9, self.start_angle+(event.mouse_x-self.start_x)*.5))
            try:
                parts.restore_joint_pose(self.target, self.before)
                parts.set_joint_angle(self.target, degrees)
                context.workspace.status_text_set(f"{CORE_LABELS[self.target]} {degrees:.1f}° · 좌우 드래그 · Esc 취소")
            except ValueError as error:
                context.workspace.status_text_set(str(error))
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}


class TwistLimb(bpy.types.Operator):
    bl_idname = "fdpose.twist_drag"
    bl_label = "IK 비틀림 · 굽힘 방향"
    bl_description = "좌우로 끌어 굽힘 방향을 돌린다. 손·발의 위치와 회전은 유지한다"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}
    target: StringProperty()

    def invoke(self, context, event):
        from .native import select_part
        select_part(context, self.target)
        self.before = PartEditing(initialize=False).joint_pose(self.target)
        self.start_x = event.mouse_x
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        parts = PartEditing(initialize=False)
        if event.type in {"ESC", "RIGHTMOUSE"}:
            parts.restore_joint_pose(self.target, self.before)
            context.workspace.status_text_set(None)
            context.area.tag_redraw()
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            from .native import key_all
            key_all(parts)
            context.workspace.status_text_set(None)
            return {"FINISHED"}
        if event.type == "MOUSEMOVE":
            degrees = (event.mouse_x-self.start_x)*.5
            try:
                parts.restore_joint_pose(self.target, self.before)
                parts.twist_joint(self.target, degrees)
                context.workspace.status_text_set(f"{CORE_LABELS[self.target]} IK 방향 {degrees:+.1f}° · Esc 취소")
            except ValueError as error:
                context.workspace.status_text_set(str(error))
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}


CLASSES = (BendJoint, BendLimb, TwistLimb, JointHandles, WorldArrows)

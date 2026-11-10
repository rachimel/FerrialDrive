"""Blender 안에서 실시간으로 조작하는 포즈·파츠 패널."""

from datetime import datetime
from pathlib import Path
import bpy
from bpy.props import EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Matrix, Vector

from . import scene as engine
from .part_editing import PartEditing, FINGERS

_clip_items = []
_part_items = []
_signature = None


def clip_items(self, context):
    global _clip_items
    if engine.STATE not in context.scene:
        return []
    items = [(c["name"], c["label"], f'{c["start"]}–{c["end"]}') for c in engine.state()["clips"]]
    if items != _clip_items:
        _clip_items = items
    return _clip_items


def part_items(self, context):
    global _part_items, _signature
    if engine.STATE not in context.scene:
        return []
    entries = PartEditing(initialize=False).entries()
    category = context.scene.fd_pose_category
    signature = (category, tuple((k, v["label"]) for k, v in entries.items()))
    if signature != _signature:
        _signature = signature
        _part_items = [(key, value["label"], key, "NONE", index)
                       for index, (key, value) in enumerate(entries.items())
                       if category == "all" or value["category"] == category]
    return _part_items


def object_mode(context):
    active = context.view_layer.objects.active
    if active and active.mode != "OBJECT":
        with context.temp_override(active_object=active, object=active):
            bpy.ops.object.mode_set(mode="OBJECT")


def select_part(context, key):
    parts = PartEditing(initialize=False)
    object_mode(context)
    for obj in context.view_layer.objects:
        if obj.select_get():
            obj.select_set(False)
    context.view_layer.objects.active = None
    context.scene.fd_pose_joint = key if key.startswith("pole.") else ""
    parts.proxy.hide_set(not key.startswith("bone:"))
    if key.startswith("pole."):
        return
    target = parts.proxy if key.startswith("bone:") else parts.target(key)
    target.hide_set(False)
    target.hide_select = False
    target.select_set(True)
    context.view_layer.objects.active = target
    if key.startswith("bone:"):
        for bone in parts.proxy.data.bones:
            bone.select = False
        bone = parts.proxy.data.bones[key[5:]]
        bone.hide = False
        bone.select = True
        parts.proxy.data.bones.active = bone
        with context.temp_override(active_object=target, object=target):
            bpy.ops.object.mode_set(mode="POSE")
        stem = key[5:].split(".")[0]
        finger = next((name for name in FINGERS if stem.startswith(name)), None)
        if finger:
            context.scene.fd_pose_finger = finger
            context.scene.fd_pose_finger_joint = stem[len(finger):]
    elif key.startswith("hand."):
        context.scene.fd_pose_finger = context.scene.fd_pose_finger_joint = "all"
    context.scene.transform_orientation_slots[0].type = "GLOBAL"


def selection_changed(self, context):
    if engine.STATE in context.scene and context.scene.fd_pose_part:
        select_part(context, context.scene.fd_pose_part)


def category_changed(self, context):
    if engine.STATE in context.scene:
        category = context.scene.fd_pose_category
        key = next((key for key, value in PartEditing(initialize=False).entries().items()
                    if category == "all" or value["category"] == category), None)
        if key:
            context.scene.fd_pose_part = key


def transform_changed(self, context):
    if context.window:
        for area in context.window.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.show_gizmo_object_rotate = context.scene.fd_pose_transform == "rotate"


def current_key(context):
    obj = context.view_layer.objects.active
    if obj:
        if "fd_pose_control" in obj:
            return obj["fd_pose_control"]
        if obj.mode == "POSE" and obj.data.bones.active:
            return "bone:"+obj.data.bones.active.name
        if obj.name in engine.state().get("independent_parts", []):
            return "object:"+obj.name
    return context.scene.fd_pose_joint or context.scene.fd_pose_part


def key_all(parts=None):
    engine.key_pose()
    (parts or PartEditing(initialize=False)).key_current()


def configure_scene():
    parts = PartEditing()
    for key, obj in engine.controls().items():
        obj.hide_select = key.startswith("pole.")
        if key.startswith("pole."):
            obj.empty_display_size = 0
    for name in engine.state().get("independent_parts", []):
        obj = bpy.data.objects[name]
        obj.hide_select = False
        obj.hide_set(False)
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = .08
        obj.show_in_front = True
    parts.proxy.hide_select = False
    parts.proxy.data.display_type = "STICK"
    parts.proxy.show_in_front = True
    editable = {key[5:] for key in parts.entries() if key.startswith("bone:")}
    for bone in parts.proxy.data.bones:
        bone.hide = bone.name not in editable
    scene = bpy.context.scene
    scene.tool_settings.use_keyframe_insert_auto = True
    scene.transform_orientation_slots[0].type = "GLOBAL"
    scene.fd_pose_clip = engine.state()["active"]
    scene.fd_pose_category = "body"
    scene.fd_pose_part = "hand.R"


class PoseCommand(bpy.types.Operator):
    bl_idname = "fdpose.command"
    bl_label = "포즈 편집"
    bl_options = {"REGISTER", "UNDO"}
    command: StringProperty()
    target: StringProperty()
    axis: EnumProperty(items=[(a, a, "") for a in "XYZ"])
    direction: FloatProperty(default=1)

    def execute(self, context):
        try:
            parts = PartEditing(initialize=False)
            key = self.target or current_key(context)
            if self.command == "select":
                select_part(context, key)
            elif self.command == "clip":
                object_mode(context)
                key_all(parts)
                engine.activate_clip(context.scene.fd_pose_clip)
            elif self.command == "first":
                key_all(parts)
                context.scene.frame_set(context.scene.frame_start)
            elif self.command in ("joint_angle", "joint_bend"):
                degrees = (context.scene.fd_pose_joint_angle if self.command == "joint_angle"
                           else max(-179.9, min(179.9, parts.joint_angle(key)+context.scene.fd_pose_angle*self.direction)))
                parts.set_joint_angle(key, degrees)
                key_all(parts)
            elif self.command == "axis":
                if context.scene.fd_pose_transform == "translate":
                    delta = Vector((0, 0, 0))
                    delta["XYZ".index(self.axis)] = context.scene.fd_pose_distance*self.direction
                    if key.startswith("pole."):
                        parts.bend_joint(key, parts.joint_position(key)+delta)
                    else:
                        parts.translate(key, delta)
                elif key.startswith("pole."):
                    pivot = parts.joint_position(key)
                    matrix = parts.world(key)
                    from math import radians
                    rotation = Matrix.Rotation(radians(context.scene.fd_pose_angle*self.direction), 3, self.axis)
                    matrix.translation = pivot+rotation@(matrix.translation-pivot)
                    parts.set_world(key, matrix)
                else:
                    parts.rotate(key, self.axis, context.scene.fd_pose_angle*self.direction)
                key_all(parts)
            elif self.command in ("fist", "open", "fingers"):
                side = key[-1] if key.startswith(("hand.", "bone:")) and key.endswith((".L", ".R")) else context.scene.fd_pose_hand
                if self.command == "fingers":
                    parts.curl_fingers(side, context.scene.fd_pose_finger,
                                       context.scene.fd_pose_angle*self.direction, context.scene.fd_pose_finger_joint)
                else:
                    parts.hand_pose(side, self.command)
                key_all(parts)
            elif self.command == "copy_previous":
                parts.copy_previous(key)
                key_all(parts)
            elif self.command == "align_sword":
                parts.align_sword()
                key_all(parts)
            elif self.command == "key":
                key_all(parts)
            elif self.command == "save":
                key_all(parts)
                engine.save_work(bpy.data.filepath)
            else:
                raise ValueError("지원하지 않는 포즈 명령")
            for area in context.screen.areas if context.screen else []:
                area.tag_redraw()
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class SavePoseWork(bpy.types.Operator, ExportHelper):
    bl_idname = "fdpose.save_work"
    bl_label = "작업본 다른 이름으로 저장"
    filename_ext = ".blend"
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})

    def execute(self, context):
        try:
            key_all()
            engine.save_work(self.filepath)
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class OpenPoseModel(bpy.types.Operator, ImportHelper):
    bl_idname = "fdpose.open_model"
    bl_label = "모델 / 작업본 열기"
    filename_ext = ".blend"
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})

    def execute(self, context):
        try:
            from .run import launch_native
            launch_native(self.filepath, tool_python=context.scene.fd_pose_python or None)
            self.report({"INFO"}, "새 Blender 창에서 연다. 현재 작업은 유지된다.")
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class ExportPoseClip(bpy.types.Operator):
    bl_idname = "fdpose.export_clip"
    bl_label = "현재 동작 출력"
    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.directory = str(Path(bpy.data.filepath).parent/(engine.state()["active"]+"_"+stamp))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            from .exporting import bake_clip
            key_all()
            engine.save_work(bpy.data.filepath)
            preset = bake_clip(self.directory)
            context.scene.fd_pose_export = str(preset)
            self.report({"INFO"}, "동작 출력 완료 · 렌더 설정 생성")
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class OpenPoseRender(bpy.types.Operator):
    bl_idname = "fdpose.open_render"
    bl_label = "출력 → Asset Tool 3D 렌더"

    def execute(self, context):
        path = Path(context.scene.fd_pose_export)
        if not path.is_file():
            self.report({"ERROR"}, "먼저 현재 동작을 출력한다.")
            return {"CANCELLED"}
        python = Path(context.scene.fd_pose_python)
        if not python.is_file() or not python.stem.lower().startswith("python"):
            self.report({"ERROR"}, "실행기로 다시 열거나 Asset Tool에서 출력 설정을 불러온다.")
            return {"CANCELLED"}
        import subprocess
        root = Path(__file__).resolve().parents[2]
        subprocess.Popen([str(python), str(root/"Tools/asset_loader/run.py"), "--render-preset", str(path)],
                         cwd=root, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"FINISHED"}


def command(layout, label, action, target="", icon="NONE", **fields):
    op = layout.operator("fdpose.command", text=label, icon=icon)
    op.command, op.target = action, target
    for name, value in fields.items():
        setattr(op, name, value)
    return op


class PosePanel(bpy.types.Panel):
    bl_label = "Pose Tool"
    bl_idname = "FDPOSE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Pose Tool"

    def draw(self, context):
        layout, scene = self.layout, context.scene
        layout.operator("fdpose.open_model", icon="FILE_FOLDER")
        if engine.STATE not in scene:
            layout.label(text="루트의 Pose Tool로 실행한다.")
            return
        data = engine.state()
        box = layout.box()
        box.label(text="동작", icon="ACTION")
        box.prop(scene, "fd_pose_clip", text="")
        command(box, "선택 동작 열기", "clip")
        row = box.row(align=True)
        command(row, "처음", "first", icon="REW")
        row.operator("screen.animation_play", text="", icon="PLAY")
        row.prop(scene, "frame_current", text="프레임")
        box = layout.box()
        box.label(text="파츠", icon="OUTLINER_OB_GROUP_INSTANCE")
        box.prop(scene, "fd_pose_category", text="")
        box.prop(scene, "fd_pose_part", text="")
        key = current_key(context)
        label = PartEditing(initialize=False).entries().get(key, {}).get("label", "파츠 선택")
        box.label(text=label, icon="RESTRICT_SELECT_OFF")
        box.row(align=True).prop(scene, "fd_pose_transform", expand=True)
        row = box.row(align=True)
        row.prop(scene, "fd_pose_distance", text="이동")
        row.prop(scene, "fd_pose_angle", text="각도")
        row = box.row(align=True)
        for axis in "XYZ":
            col = row.column(align=True)
            col.label(text=axis)
            pair = col.row(align=True)
            command(pair, "", "axis", key, icon="REMOVE", axis=axis, direction=-1)
            command(pair, "", "axis", key, icon="ADD", axis=axis, direction=1)
        command(box, "이전 프레임 파츠 복제", "copy_previous", key, icon="DUPLICATE")
        if key.startswith("pole.hand."):
            box = layout.box()
            box.label(text="팔꿈치 굽힘", icon="DRIVER_ROTATIONAL_DIFFERENCE")
            box.label(text=f"현재 {PartEditing(initialize=False).joint_angle(key):.1f}° · 0°는 편 자세")
            row = box.row(align=True)
            row.prop(scene, "fd_pose_joint_angle", text="목표 각도")
            command(row, "적용", "joint_angle", key)
            row = box.row(align=True)
            command(row, "펴기 −", "joint_bend", key, direction=-1)
            command(row, "굽히기 +", "joint_bend", key)
            box.label(text="하박과 손이 함께 회전한다.")
        if key.startswith(("hand.", "bone:Thumb", "bone:Index", "bone:Middle", "bone:Ring", "bone:Little")):
            box = layout.box()
            box.label(text="손가락", icon="VIEW_PAN")
            row = box.row(align=True)
            command(row, "주먹", "fist", key)
            command(row, "손 펴기", "open", key)
            row = box.row(align=True)
            row.prop(scene, "fd_pose_finger", text="")
            row.prop(scene, "fd_pose_finger_joint", text="")
            row = box.row(align=True)
            command(row, "펴기 −", "fingers", key, direction=-1)
            command(row, "굽히기 +", "fingers", key)
        if key in ("object:Sword", "object:Scabbard"):
            command(layout, "칼 → 칼집 자동 정렬", "align_sword", icon="SNAP_ON")
        row = layout.row(align=True)
        row.operator("ed.undo", text="되돌리기", icon="LOOP_BACK")
        row.operator("ed.redo", text="다시 실행", icon="LOOP_FORWARDS")
        command(layout, "현재 프레임 포즈 키 저장", "key", icon="KEY_HLT")
        row = layout.row(align=True)
        command(row, "작업본 저장", "save", icon="FILE_TICK")
        row.operator("fdpose.save_work", text="다른 이름")
        layout.operator("fdpose.export_clip", icon="EXPORT")
        if scene.fd_pose_export:
            layout.operator("fdpose.open_render", icon="FILE_FOLDER")
        layout.label(text="G 이동 · R 회전 · X/Y/Z 월드 축")
        layout.label(text="Ctrl+Z 되돌리기 · 자동 키 켜짐")
        layout.label(text="팔꿈치 원 좌우 드래그: 굽힘 각도")
        layout.label(text="무릎 원 드래그: 굽힘 방향")


CLASSES = (PoseCommand, SavePoseWork, OpenPoseModel, ExportPoseClip, OpenPoseRender, PosePanel)
PROPERTIES = {
    "fd_pose_clip": lambda: EnumProperty(name="동작", items=clip_items),
    "fd_pose_category": lambda: EnumProperty(name="분류", update=category_changed, items=[("body", "몸체 · IK", ""), ("fingers", "손가락", ""), ("equipment", "총 · 칼 · 칼집", ""), ("detail", "기타 파츠", ""), ("all", "전체", "")]),
    "fd_pose_part": lambda: EnumProperty(name="파츠", items=part_items, update=selection_changed),
    "fd_pose_joint": lambda: StringProperty(),
    "fd_pose_transform": lambda: EnumProperty(name="월드 축", update=transform_changed, items=[("translate", "이동", ""), ("rotate", "회전", "")]),
    "fd_pose_distance": lambda: FloatProperty(name="이동량", default=.05, min=.0001, max=100, precision=3),
    "fd_pose_angle": lambda: FloatProperty(name="회전각", default=5, min=.1, max=180),
    "fd_pose_joint_angle": lambda: FloatProperty(name="팔꿈치 굽힘 각도", default=90, min=-179.9, max=179.9, precision=1),
    "fd_pose_hand": lambda: EnumProperty(items=[("R", "오른손", ""), ("L", "왼손", "")]),
    "fd_pose_finger": lambda: EnumProperty(items=[("all", "손가락 전체", "")]+[(k, v, "") for k, v in FINGERS.items()]),
    "fd_pose_finger_joint": lambda: EnumProperty(items=[("all", "관절 전체", ""), ("Base", "엄지 뿌리", ""), ("01", "1번", ""), ("02", "2번", ""), ("03", "3번", "")]),
    "fd_pose_export": lambda: StringProperty(subtype="FILE_PATH"),
    "fd_pose_python": lambda: StringProperty(subtype="FILE_PATH"),
}


def register():
    from .gizmos import CLASSES as GIZMOS
    for cls in (*CLASSES, *GIZMOS):
        bpy.utils.register_class(cls)
    for name, factory in PROPERTIES.items():
        setattr(bpy.types.Scene, name, factory())


def unregister():
    from .gizmos import CLASSES as GIZMOS
    for name in PROPERTIES:
        delattr(bpy.types.Scene, name)
    for cls in reversed((*CLASSES, *GIZMOS)):
        bpy.utils.unregister_class(cls)

"""Pose Tool의 Blender 패널과 사용자 명령."""

from pathlib import Path
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from . import scene as engine


LABELS = {"pelvis": "골반", "waist": "허리", "chest": "몸통", "head": "머리",
          "shoulder.L": "왼쪽 어깨", "shoulder.R": "오른쪽 어깨",
          "hand.L": "왼손", "hand.R": "오른손", "foot.L": "왼발", "foot.R": "오른발",
          "pole.hand.L": "왼쪽 팔꿈치", "pole.hand.R": "오른쪽 팔꿈치",
          "pole.foot.L": "왼쪽 무릎", "pole.foot.R": "오른쪽 무릎"}
_clip_items = []
_clip_signature = None


def clip_items(self, context):
    global _clip_items, _clip_signature
    if engine.STATE not in context.scene:
        return []
    # Enum 콜백 문자열은 Blender가 참조하는 동안 보관한다.
    signature = tuple((c["name"], c["label"], c["start"], c["end"]) for c in engine.state()["clips"])
    if signature != _clip_signature:
        _clip_signature = signature
        _clip_items = [(name, label, f"{start}–{end} 프레임") for name, label, start, end in signature]
    return _clip_items


class PoseCommand(bpy.types.Operator):
    bl_idname = "fdpose.command"
    bl_label = "Pose Tool"
    bl_options = {"REGISTER", "UNDO"}
    command: StringProperty()
    target: StringProperty()

    def execute(self, context):
        try:
            if self.command == "clip":
                engine.activate_clip(context.scene.fd_pose_clip)
                self.report({"INFO"}, "동작 선택 · 첫 프레임")
            elif self.command == "select":
                bpy.ops.object.select_all(action="DESELECT")
                obj = engine.controls()[self.target]
                obj.select_set(True)
                context.view_layer.objects.active = obj
                context.scene.tool_settings.transform_pivot_point = "MEDIAN_POINT"
            elif self.command == "key":
                self.report({"INFO"}, f"{engine.key_pose()} 프레임 포즈 키 저장")
            elif self.command == "mirror":
                engine.mirror_pose(self.target)
            elif self.command == "support":
                engine.support_pin(self.target == "on")
            elif self.command == "first":
                context.scene.frame_set(context.scene.frame_start)
            elif self.command == "pin_feet":
                for key, obj in engine.controls().items():
                    if key.startswith("foot."):
                        engine.key_transform(obj, context.scene.frame_current)
                self.report({"INFO"}, "발 위치 키 저장 · 골반과 독립적으로 유지")
            elif self.command == "equipment":
                eq = engine.state()["profile"]["equipment"]
                obj = bpy.data.objects.get(eq["object"])
                if not obj:
                    raise ValueError("장비 제어 객체가 없다.")
                for prop in eq["properties"]:
                    if prop in obj:
                        obj[prop] = 1.0 if self.target == "stowed" else 0.0
                obj.update_tag()
                engine.update()
            elif self.command == "save":
                engine.save_work(bpy.data.filepath)
                self.report({"INFO"}, "작업본 저장")
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
            engine.save_work(self.filepath)
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class ExportPoseClip(bpy.types.Operator):
    bl_idname = "fdpose.export_clip"
    bl_label = "현재 동작 출력"
    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        self.directory = str(Path(bpy.data.filepath).parent / (engine.state()["active"] + "_export"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            path = engine.export_clip(self.directory)
            # 굽기까지 같은 요청 경로에서 완료한다. 원본은 열지 않는다.
            from Tools.blender_pipeline.animation_pipeline import bake
            work = bpy.data.filepath
            engine.save_work(work)
            try:
                bake(path, Path(self.directory) / "baked")
            finally:
                bpy.ops.wm.open_mainfile(filepath=work)
            self.report({"INFO"}, "동작 출력 완료 · baked/animations.blend")
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


def command(layout, label, action, target="", icon="NONE"):
    op = layout.operator("fdpose.command", text=label, icon=icon)
    op.command, op.target = action, target


class PosePanel(bpy.types.Panel):
    bl_label = "Pose Tool"
    bl_idname = "FDPOSE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Pose Tool"

    def draw(self, context):
        layout = self.layout
        if engine.STATE not in context.scene:
            layout.label(text="실행기로 모델 또는 샘플을 연다.")
            return
        data = engine.state()
        box = layout.box()
        box.label(text="동작", icon="ACTION")
        box.prop(context.scene, "fd_pose_clip", text="")
        command(box, "선택 동작 열기", "clip")
        row = box.row(align=True)
        command(row, "첫 프레임", "first", icon="REW")
        row.operator("screen.animation_play", text="재생 / 정지", icon="PLAY")
        box.label(text=f"편집 중: {data['active']}")
        row = box.row(align=True)
        row.prop(context.scene, "frame_current", text="프레임")
        row = layout.row()
        row.scale_y = 1.3
        command(row, "현재 프레임 포즈 키 저장", "key", icon="KEY_HLT")
        row = layout.row(align=True)
        command(row, "작업본 저장", "save", icon="FILE_TICK")
        row.operator("fdpose.save_work", text="다른 이름")
        layout.operator("fdpose.export_clip", text="현재 동작 출력", icon="EXPORT")
        box = layout.box()
        box.label(text="컨트롤 선택", icon="ORIENTATION_GLOBAL")
        ctrls = engine.controls()
        for keys in (("pelvis", "waist"), ("chest", "head"), ("shoulder.L", "shoulder.R"),
                     ("hand.L", "hand.R"), ("pole.hand.L", "pole.hand.R"),
                     ("foot.L", "foot.R"), ("pole.foot.L", "pole.foot.R")):
            row = box.row(align=True)
            for key in keys:
                if key in ctrls:
                    command(row, LABELS[key], "select", key)
        box.label(text="G 이동 · R 회전 · X/Y/Z 축 제한")
        box.label(text="가운데 드래그 시점 · 휠 확대")
        obj = context.active_object
        if obj and "fd_pose_control" in obj:
            box.label(text=LABELS.get(obj["fd_pose_control"], obj.name))
            box.prop(context.scene, "fd_pose_precision", text="정밀 이동", toggle=True)
            if context.scene.fd_pose_precision:
                box.prop(obj, "location", text="이동")
        rig, _ = engine.rig_objects()
        evaluated = rig.evaluated_get(context.evaluated_depsgraph_get())
        errors = [(key, (evaluated.matrix_world @ evaluated.pose.bones[limb["end"]].head -
                        engine.rig_objects()[1].pose.bones[limb["lower"]].constraints[engine.PREFIX + "IK"].target.matrix_world.translation).length)
                  for key, limb in data["profile"]["limbs"].items()]
        if any(error > .005 for _, error in errors):
            box.label(text="손·발 목표가 가동 범위를 벗어남", icon="ERROR")
        command(box, "발 위치 고정 키", "pin_feet")
        box = layout.box()
        box.label(text="편집")
        row = box.row(align=True)
        command(row, "왼쪽 → 오른쪽", "mirror", "L_TO_R")
        command(row, "오른쪽 → 왼쪽", "mirror", "R_TO_L")
        command(box, "좌우 전체 반전", "mirror", "BOTH")
        eq = data["profile"].get("equipment", {})
        equipment = bpy.data.objects.get(eq.get("object", ""))
        if equipment:
            box = layout.box()
            box.label(text="무기 · 양손 파지")
            for prop in eq.get("properties", []):
                if prop in equipment:
                    box.prop(equipment, f'["{prop}"]', text={"sword_stowed": "검 수납", "gun_stowed": "총 수납"}.get(prop, prop), slider=True)
            row = box.row(align=True)
            command(row, "모두 수납", "equipment", "stowed")
            command(row, "모두 파지", "equipment", "held")
            row = box.row(align=True)
            command(row, "보조손 고정", "support", "on")
            command(row, "고정 해제", "support", "off")
            box.label(text="현재 파지 간격 유지 · 자동 파지 아님")
        layout.separator()
        layout.label(text="키 저장 후 작업본을 저장한다.")


CLASSES = (PoseCommand, SavePoseWork, ExportPoseClip, PosePanel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fd_pose_clip = EnumProperty(name="동작", items=clip_items)
    bpy.types.Scene.fd_pose_precision = BoolProperty(name="정밀 이동", default=False)


def configure_view():
    import json
    theme = json.loads((Path(__file__).resolve().parents[1] / "theme_reference/theme.json").read_text(encoding="utf-8"))
    color = theme["colors"]["background"].lstrip("#")
    # 비활성 Screen의 영역을 갱신하면 Blender UI에 소유 Window가 없어 충돌할 수 있다.
    screens = [bpy.context.window.screen] if bpy.context.window else []
    for screen in screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.show_region_ui = True
                space.shading.type = "SOLID"
                space.shading.light = "STUDIO"
                space.shading.color_type = "MATERIAL"
                space.shading.background_type = "VIEWPORT"
                space.shading.background_color = tuple(int(color[i:i+2], 16)/255 for i in (0, 2, 4))
                space.overlay.show_relationship_lines = False
                space.show_gizmo = True
                space.show_gizmo_object_translate = True
                space.show_gizmo_object_rotate = True
                rig, _ = engine.rig_objects()
                from mathutils import Vector
                points = [rig.matrix_world @ b.head for b in rig.pose.bones]
                low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
                high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
                space.region_3d.view_location = (low+high)*.5
                space.region_3d.view_distance = max((high-low).length*1.4, 2)
                space.region_3d.view_rotation = Vector((6, -8, 3)).to_track_quat("Z", "Y")
                space.region_3d.view_perspective = "ORTHO"


def unregister():
    del bpy.types.Scene.fd_pose_clip
    del bpy.types.Scene.fd_pose_precision
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

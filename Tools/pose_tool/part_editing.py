"""포즈 파츠·손목 연결·손가락·독립 무기 편집. 원본 메시와 rest 본은 보존한다."""

import math
import bpy
from mathutils import Matrix, Vector
from . import scene as engine


ASSEMBLIES = {"Gun": "총", "Sword": "칼", "Scabbard": "칼집"}
FINGERS = {"Thumb": "엄지", "Index": "검지", "Middle": "중지", "Ring": "약지", "Little": "소지"}
CORE_LABELS = {"pelvis": "골반", "waist": "허리", "chest": "몸통", "head": "머리",
               "shoulder.L": "왼쪽 어깨", "shoulder.R": "오른쪽 어깨",
               "upper.hand.L": "왼쪽 상박", "upper.hand.R": "오른쪽 상박",
               "upper.foot.L": "왼쪽 허벅지", "upper.foot.R": "오른쪽 허벅지",
               "hand.L": "왼손", "hand.R": "오른손", "foot.L": "왼발", "foot.R": "오른발",
               "pole.hand.L": "왼쪽 팔꿈치", "pole.hand.R": "오른쪽 팔꿈치",
               "pole.foot.L": "왼쪽 무릎", "pole.foot.R": "오른쪽 무릎"}


def rows(matrix):
    return [list(row) for row in matrix]


class PartEditing:
    def __init__(self, *, initialize=True):
        self.rig, self.proxy = engine.rig_objects()
        if initialize:
            engine.upgrade_shoulders()
            engine.upgrade_upper_handles()
            self.link_wrists()
            self.prepare_assemblies()

    def link_wrists(self):
        controls = engine.controls()
        data = engine.state()
        collection = bpy.data.collections[engine.PREFIX + "Controls"]
        for side in ("L", "R"):
            wrist = self.proxy.pose.bones.get("WristSwivel."+side)
            hand = self.proxy.pose.bones.get("Hand."+side)
            if not wrist or not hand or "hand."+side not in controls:
                continue
            name = engine.PREFIX + "WristFollow."+side
            target = bpy.data.objects.get(name)
            if target is None:
                target = bpy.data.objects.new(name, None)
                collection.objects.link(target)
                target.empty_display_size = 0
                target.hide_select = True
                target.parent = controls["hand."+side]
                offset = engine.palm_offset(self.rig, "hand."+side, data["profile"]["limbs"]["hand."+side])
                relative = hand.bone.matrix_local.inverted() @ wrist.bone.matrix_local
                target.matrix_basis = Matrix.Translation(-offset) @ relative
            constraint = wrist.constraints.get(engine.PREFIX + "HandLinked")
            if constraint is None:
                constraint = wrist.constraints.new("COPY_ROTATION")
                constraint.name = engine.PREFIX + "HandLinked"
            constraint.target = target
            constraint.owner_space = constraint.target_space = "WORLD"
        engine.update()

    def prepare_assemblies(self):
        data = engine.state()
        if "independent_parts" in data:
            return
        objects = [bpy.data.objects[name] for name in ASSEMBLIES if name in bpy.data.objects]
        frame = bpy.context.scene.frame_current
        current = {obj.name: obj.matrix_world.copy() for obj in objects}
        scabbard, stow = bpy.data.objects.get("Scabbard"), bpy.data.objects.get("Sword_StowAnchor")
        # 제작된 칼집 좌표계와 수납 기준점 사이의 관계를 보존한다.
        alignment = scabbard.matrix_world.inverted() @ stow.matrix_world if scabbard and stow else None
        frames = sorted({f for clip in data["clips"] for f in range(clip["start"], clip["end"]+1)})
        samples = {}
        if objects:
            with engine.suspend_meshes():
                engine.source_mode(True)
                try:
                    for sample_frame in frames:
                        bpy.context.scene.frame_set(sample_frame)
                        samples[sample_frame] = {obj.name: obj.matrix_world.copy() for obj in objects}
                finally:
                    engine.source_mode(False)
                    bpy.context.scene.frame_set(frame)
                # 현재 동작에 저장한 컨트롤 편집도 분리 전 위치에 반영한다.
                active = next(c for c in data["clips"] if c["name"] == data["active"])
                for sample_frame in range(active["start"], active["end"]+1):
                    bpy.context.scene.frame_set(sample_frame)
                    samples[sample_frame] = {obj.name: obj.matrix_world.copy() for obj in objects}
                bpy.context.scene.frame_set(frame)
            samples[frame] = current
            for obj in objects:
                for constraint in obj.constraints:
                    constraint.mute = True
                if obj.animation_data:
                    obj.animation_data.action = None
                    for track in obj.animation_data.nla_tracks:
                        track.mute = True
                    for driver in obj.animation_data.drivers:
                        if driver.data_path in ("location", "rotation_euler", "rotation_quaternion", "scale"):
                            driver.mute = True
                obj.parent = None
                obj.rotation_mode = "QUATERNION"
                previous = None
                for sample_frame in frames:
                    obj.matrix_world = samples[sample_frame][obj.name]
                    if previous and previous.dot(obj.rotation_quaternion) < 0:
                        obj.rotation_quaternion.negate()
                    previous = obj.rotation_quaternion.copy()
                    engine.key_transform(obj, sample_frame)
                if obj.animation_data and obj.animation_data.action:
                    obj.animation_data.action.name = engine.PREFIX+"Part_"+obj.name
                    engine.linear_keys(obj.animation_data.action)
        data["independent_parts"] = [obj.name for obj in objects]
        data["sword_alignment"] = rows(alignment) if alignment is not None else None
        engine.store(data)
        bpy.context.scene.frame_set(frame)
        engine.update()

    def entries(self):
        result = {key: {"label": CORE_LABELS.get(key, key), "category": "body", "kind": "control"}
                  for key in engine.controls()}
        owned = set(engine.state()["profile"]["body"].values())
        owned.update(name for limb in engine.state()["profile"]["limbs"].values() for name in limb.values())
        for bone in self.proxy.pose.bones:
            if bone.name in owned or bone.name.startswith("WristSwivel."):
                continue
            finger = next((prefix for prefix in FINGERS if bone.name.startswith(prefix)), None)
            if finger:
                side = "왼손" if bone.name.endswith(".L") else "오른손"
                joint = bone.name.split(".")[0][len(finger):].replace("Base", "뿌리")
                label = f"{side} {FINGERS[finger]} {joint}"
            else:
                label = bone.name
            result["bone:"+bone.name] = {"label": label, "category": "fingers" if finger else "detail", "kind": "bone"}
        for name in engine.state().get("independent_parts", []):
            result["object:"+name] = {"label": ASSEMBLIES.get(name, name), "category": "equipment", "kind": "object"}
        return result

    def target(self, key):
        if key.startswith("bone:"):
            return self.proxy.pose.bones[key[5:]]
        if key.startswith("object:") and key[7:] in engine.state().get("independent_parts", []):
            return bpy.data.objects[key[7:]]
        return engine.controls()[key]

    def world(self, key):
        target = self.target(key)
        return self.proxy.matrix_world @ target.matrix if key.startswith("bone:") else target.matrix_world.copy()

    def set_world(self, key, matrix, *, moving=False):
        target = self.target(key)
        if key.startswith("upper."):
            if moving:
                raise ValueError("상박·허벅지는 회전으로 조절한다.")
            # 다른 프레임의 파츠 복제도 현재 관절 원점과 크기를 유지한다.
            matrix = Matrix.LocRotScale(target.matrix_world.translation, matrix.to_quaternion(), target.matrix_world.to_scale())
            end = engine.controls()[key.removeprefix("upper.")]
            if end.constraints.get(engine.PREFIX+"Support"):
                engine.support_pin(False)
        if key.startswith("bone:"):
            if moving and target.bone.use_connect:
                raise ValueError("연결된 손가락 관절은 회전으로 조절한다.")
            target.matrix = self.proxy.matrix_world.inverted() @ matrix
        else:
            if target.constraints.get(engine.PREFIX+"Support"):
                engine.support_pin(False)
            target.matrix_world = matrix
        engine.update()

    def translate(self, key, delta):
        if key.startswith("pole."):
            raise ValueError("팔꿈치·무릎은 화면 손잡이로 굽힘 방향을 조절한다.")
        matrix = self.world(key)
        matrix.translation += Vector(delta)
        self.set_world(key, matrix, moving=True)

    def rotate(self, key, axis, degrees):
        matrix = self.world(key)
        pivot = matrix.translation
        self.set_world(key, Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(degrees), 4, axis) @ Matrix.Translation(-pivot) @ matrix)

    def finger_bones(self, side, finger="all", joint="all"):
        prefix = next((name for name, label in FINGERS.items() if finger in (name, label)), None)
        return [b for b in self.proxy.pose.bones if b.name.endswith("."+side)
                and any(b.name.startswith(name) for name in FINGERS)
                and (finger == "all" or prefix and b.name.startswith(prefix))
                and (joint == "all" or b.name.split(".")[0].endswith(joint))]

    def curl_fingers(self, side, finger, degrees, joint="all"):
        bones = self.finger_bones(side, finger, joint)
        if not bones:
            raise ValueError("선택한 손가락 관절이 없다.")
        # 네 손가락은 손바닥 기준의 공통 축을 각 마디 좌표로 변환한다.
        for bone in bones:
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = bone.rotation_quaternion @ Matrix.Rotation(math.radians(degrees), 3, self.finger_axis(bone)).to_quaternion()
        engine.update()

    def finger_axis(self, bone):
        finger = next(name for name in FINGERS if bone.name.startswith(name))
        if finger == "Thumb":
            root = self.proxy.data.bones["ThumbBase"+bone.name[-2:]]
            axis = root.matrix_local.to_3x3().col[2]
            if bone.name.endswith(".L"):
                axis = -axis
        else:
            side = bone.name[-1]
            names = ("Index", "Middle", "Ring", "Little")
            roots = [self.proxy.data.bones.get(name+"01."+side) for name in names]
            roots = [root for root in roots if root]
            hand_name = engine.state()["profile"]["limbs"]["hand."+side]["end"]
            hand = self.proxy.data.bones[hand_name]
            forward = sum((root.matrix_local.to_3x3().col[1] for root in roots), Vector()).normalized()
            axis = roots[-1].head_local-roots[0].head_local if len(roots) > 1 else hand.matrix_local.to_3x3().col[0]
            axis -= forward*axis.dot(forward)
            if axis.length < 1e-6:
                raise ValueError("네 손가락의 공통 굽힘 축을 정할 수 없다.")
            axis.normalize()
            # 기존 무기 파지 좌표계에서 손바닥 면은 Hand 로컬 -Z다.
            palm_normal = -hand.matrix_local.to_3x3().col[2]
            if axis.cross(forward).dot(palm_normal) < 0:
                axis.negate()
        return (bone.bone.matrix_local.to_3x3().inverted() @ axis).normalized()

    def hand_pose(self, side, pose):
        """관절의 로컬 회전을 절대값으로 설정한다. 반복 클릭해도 더 꺾이지 않는다."""
        if side not in ("L", "R") or pose not in ("fist", "open"):
            raise ValueError("손 / 손 모양 오류")
        bones = self.finger_bones(side)
        if not bones:
            raise ValueError("손가락 본이 없다.")
        angles = {"01": 70, "02": 90, "03": 65}
        thumb = {"Base": 25, "01": 55, "02": 65}
        for bone in bones:
            stem = bone.name.split(".")[0]
            table = thumb if stem.startswith("Thumb") else angles
            angle = next((value for suffix, value in table.items() if stem.endswith(suffix)), 0)
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = Matrix.Rotation(math.radians(angle if pose == "fist" else 0), 3, self.finger_axis(bone)).to_quaternion()
        engine.update()

    def joint_position(self, key):
        limb = engine.state()["profile"]["limbs"][key.removeprefix("pole.")]
        return engine.world_bones(self.rig)[limb["lower"]].translation

    def joint_angle(self, key):
        """완전히 편 자세를 0도로 하는 실제 관절 굽힘 각도."""
        limb = engine.state()["profile"]["limbs"][key.removeprefix("pole.")]
        worlds = engine.world_bones(self.rig)
        upper = worlds[limb["lower"]].translation-worlds[limb["upper"]].translation
        lower = worlds[limb["end"]].translation-worlds[limb["lower"]].translation
        axis = self.joint_axis(key, worlds)
        return math.degrees(math.atan2(axis.dot(upper.cross(lower)), upper.dot(lower)))

    def joint_axis(self, key, worlds=None):
        """현재 굽힘 면을 사용하고, 편 자세에서는 해당 팔다리의 rest 축으로 복구한다."""
        limb = engine.state()["profile"]["limbs"][key.removeprefix("pole.")]
        worlds = worlds or engine.world_bones(self.rig)
        upper = (worlds[limb["lower"]].translation-worlds[limb["upper"]].translation).normalized()
        lower = (worlds[limb["end"]].translation-worlds[limb["lower"]].translation).normalized()
        bones = self.rig.data.bones
        rest_upper, rest_lower, rest_end = (bones[limb[field]] for field in ("upper", "lower", "end"))
        rest_direction = rest_lower.head_local-rest_upper.head_local
        rest_axis = rest_direction.cross(rest_end.head_local-rest_lower.head_local)
        # 기준 정면은 +X다. 양의 굽힘은 팔꿈치 앞쪽, 무릎 뒤쪽이다.
        forward = -1 if key.startswith("pole.foot.") else 1
        if rest_axis.cross(rest_direction).x*forward < 0:
            rest_axis.negate()
        reference = worlds[limb["upper"]].to_3x3() @ rest_upper.matrix_local.to_3x3().inverted() @ rest_axis
        axis = upper.cross(lower)
        if axis.length < 1e-3:
            axis = reference
            if axis.length < 1e-6:
                axis = (self.world(key).translation-worlds[limb["lower"]].translation).cross(upper)
        elif axis.dot(reference) < 0:
            axis.negate()
        axis -= upper*axis.dot(upper)
        if axis.length < 1e-6:
            raise ValueError("관절의 굽힘 축을 정할 수 없다.")
        return axis.normalized()

    def joint_pose(self, key):
        """드래그 취소 시 복구할 컨트롤·IK 입력만 보관한다."""
        end = key.removeprefix("pole.")
        limb = engine.state()["profile"]["limbs"][end]
        constraint = self.proxy.pose.bones[limb["lower"]].constraints[engine.PREFIX+"IK"]
        support = end.startswith("hand.") and any(obj.constraints.get(engine.PREFIX+"Support") for obj in engine.controls().values())
        anchor = bpy.data.objects.get(engine.PREFIX+"SupportAnchor")
        return {"end": self.world(end), "pole": self.world(key),
                "basis": {limb[field]: self.proxy.pose.bones[limb[field]].matrix_basis.copy()
                          for field in ("upper", "lower")},
                "angle": constraint.pole_angle,
                "support": anchor.matrix_basis.copy() if support and anchor else None}

    def restore_joint_pose(self, key, pose):
        end = key.removeprefix("pole.")
        limb = engine.state()["profile"]["limbs"][end]
        self.set_world(end, pose["end"])
        self.set_world(key, pose["pole"])
        for name, basis in pose["basis"].items():
            self.proxy.pose.bones[name].matrix_basis = basis
        self.proxy.pose.bones[limb["lower"]].constraints[engine.PREFIX+"IK"].pole_angle = pose["angle"]
        if pose["support"] is not None:
            engine.support_pin(True)
            bpy.data.objects[engine.PREFIX+"SupportAnchor"].matrix_basis = pose["support"]
        engine.update()

    def set_joint_angle(self, key, degrees):
        """상위 마디를 유지하며 관절 회전에 하위 마디와 손·발 목표를 함께 움직인다."""
        if not key.startswith("pole.") or key.removeprefix("pole.") not in engine.state()["profile"]["limbs"]:
            raise ValueError("팔꿈치 또는 무릎을 선택한다.")
        if not math.isfinite(degrees) or not -179.9 <= degrees <= 179.9:
            raise ValueError("관절 굽힘 각도는 -179.9~179.9도다.")
        current_angle = self.joint_angle(key)
        # 표시 정밀도(0.1도)보다 작은 IK 잔차 때문에 같은 입력이 누적되지 않게 한다.
        if abs(degrees-current_angle) < .01:
            return
        end = key.removeprefix("pole.")
        limb = engine.state()["profile"]["limbs"][end]
        worlds = engine.world_bones(self.rig)
        axis = self.joint_axis(key, worlds)
        pivot = worlds[limb["lower"]].translation
        rotation = (Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(degrees-current_angle), 4, axis)
                    @ Matrix.Translation(-pivot))
        desired = dict(worlds)
        for field in ("lower", "end"):
            desired[limb[field]] = rotation @ worlds[limb[field]]
        before = self.joint_pose(key)
        constraint = self.proxy.pose.bones[limb["lower"]].constraints[engine.PREFIX+"IK"]
        try:
            # 이전 IK 해의 굽힘을 재사용하지 않고 새 입력 자세에서 평가한다.
            constraint.mute = True
            engine.update()
            if before["support"] is not None:
                engine.support_pin(False)
            self.set_world(end, engine.target_matrix(desired, self.rig, end, limb))
            pole = self.world(key)
            if abs(degrees) < .1:
                direction = (pivot-worlds[limb["upper"]].translation).normalized()
                pole.translation = pivot-axis.cross(direction).normalized()*self.rig.data.bones[limb["lower"]].length
            else:
                pole.translation = engine.pole_position(desired, limb)
            self.set_world(key, pole)
            # IK 입력 자세도 목표와 맞춰 상박·허벅지의 roll이 바뀌지 않게 한다.
            bases = engine.local_basis(self.proxy, desired)
            for field in ("upper", "lower"):
                self.proxy.pose.bones[limb[field]].matrix_basis = bases[limb[field]]
            engine.update()
            constraint.mute = False
            engine.update()
            with engine.suspend_meshes():
                engine.calibrate_pole(self.proxy, limb, desired)
        except Exception:
            constraint.mute = False
            self.restore_joint_pose(key, before)
            raise

    def bend_joint(self, key, location):
        limb = engine.state()["profile"]["limbs"][key.removeprefix("pole.")]
        worlds = engine.world_bones(self.rig)
        origin = worlds[limb["upper"]].translation
        axis = (worlds[limb["end"]].translation-origin).normalized()
        current = worlds[limb["lower"]].translation-origin
        desired = Vector(location)-origin
        current -= axis*current.dot(axis)
        desired -= axis*desired.dot(axis)
        if current.length < 1e-5 or desired.length < 1e-5:
            raise ValueError("관절이 완전히 펴졌다. 골반·손·발 위치로 먼저 굽힘을 만든다.")
        angle = math.atan2(axis.dot(current.cross(desired)), current.dot(desired))
        matrix = self.world(key)
        matrix.translation = origin + Matrix.Rotation(angle, 3, axis) @ (matrix.translation-origin)
        self.set_world(key, matrix)

    def twist_joint(self, key, degrees):
        """손·발의 위치와 회전을 유지하고 IK 굽힘 면을 돌린다."""
        if not key.startswith("pole.") or key.removeprefix("pole.") not in engine.state()["profile"]["limbs"]:
            raise ValueError("팔꿈치 또는 무릎을 선택한다.")
        if not math.isfinite(degrees):
            raise ValueError("유한한 회전각을 입력한다.")
        limb = engine.state()["profile"]["limbs"][key.removeprefix("pole.")]
        worlds = engine.world_bones(self.rig)
        origin = worlds[limb["upper"]].translation
        axis = worlds[limb["end"]].translation-origin
        upper = worlds[limb["lower"]].translation-origin
        if axis.length < 1e-5 or upper.cross(axis.normalized()).length < 1e-4:
            raise ValueError("편 자세에서는 먼저 관절을 조금 굽힌다.")
        matrix = self.world(key)
        matrix.translation = origin+Matrix.Rotation(math.radians(degrees), 3, axis.normalized())@(matrix.translation-origin)
        self.set_world(key, matrix)

    def align_sword(self):
        if not all(name in engine.state().get("independent_parts", []) for name in ("Sword", "Scabbard")):
            raise ValueError("칼과 칼집 파츠가 필요하다.")
        if engine.state().get("sword_alignment") is None:
            raise ValueError("칼집 수납 기준점 Sword_StowAnchor가 필요하다.")
        sword, scabbard = bpy.data.objects["Sword"], bpy.data.objects["Scabbard"]
        sword.matrix_world = scabbard.matrix_world @ Matrix(engine.state()["sword_alignment"])
        engine.update()

    def key_current(self):
        frame = bpy.context.scene.frame_current
        for key, entry in self.entries().items():
            if entry["kind"] != "control":
                engine.key_transform(self.target(key), frame)
        for limb in engine.state()["profile"]["limbs"].values():
            for field in ("upper", "lower"):
                engine.key_transform(self.proxy.pose.bones[limb[field]], frame)
            self.proxy.pose.bones[limb["lower"]].constraints[engine.PREFIX+"IK"].keyframe_insert("pole_angle", frame=frame)
        for curve in engine.all_curves(self.proxy.animation_data.action):
            if curve.data_path.endswith(".pole_angle"):
                for point in curve.keyframe_points:
                    point.interpolation = "CONSTANT"
        for name in engine.state().get("independent_parts", []):
            obj = bpy.data.objects[name]
            if obj.animation_data and obj.animation_data.action:
                engine.linear_keys(obj.animation_data.action)

    def copy_previous(self, key):
        frame = bpy.context.scene.frame_current
        data = engine.state()
        previous = next((c for c in data["clips"] if c["start"] <= frame-1 <= c["end"]), None)
        if previous is None:
            raise ValueError("복제할 이전 프레임이 없다.")
        engine.key_pose()
        self.key_current()
        active = data["active"]
        local = key.startswith("bone:")
        finger_matrices = {}
        try:
            if previous["name"] != active:
                engine.activate_clip(previous["name"])
            bpy.context.scene.frame_set(frame-1)
            matrix = self.target(key).matrix_basis.copy() if local else self.world(key)
            if key.startswith("hand."):
                finger_matrices = {b.name: b.matrix_basis.copy() for b in self.finger_bones(key[-1])}
        finally:
            if engine.state()["active"] != active:
                engine.activate_clip(active)
            bpy.context.scene.frame_set(frame)
        if local:
            self.target(key).matrix_basis = matrix
        else:
            self.set_world(key, matrix, moving=True)
        for name, basis in finger_matrices.items():
            self.proxy.pose.bones[name].matrix_basis = basis
        engine.update()
